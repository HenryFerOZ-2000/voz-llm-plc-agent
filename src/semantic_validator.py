from __future__ import annotations

import re
from typing import Any

from functional_requirements import detect_functional_requirement_conflicts, has_composable_program, timed_sequence_missing_data
from io_allocator import IEC_NAME_PATTERN, propose_assignment
from functional_requirements import (
    COMPOSABLE_TYPES,
    detect_multi_actor_motor_targets,
    detect_timed_sequences,
    is_catalog_functional_requirement,
)
from functional_resources import resolve_functional_resources
from ir_builder import INTENT_TEMPLATE_NOT_IMPLEMENTED, INTERNAL_PREFIXES, get_required_variables_for_intent
from schemas import (
    PLC_TAG_PATTERN,
    SemanticValidationResult,
    TIME_LITERAL_PATTERN,
    semantic_model_to_dict,
    validate_semantic_model,
    validate_semantic_payload_structure
)
from utils import build_io_map_index, get_project_root, load_json_file


def _load_pid_supervisor_config() -> dict[str, Any]:
    try:
        return load_json_file(get_project_root() / "config" / "pid_supervisor_config.json")
    except (FileNotFoundError, ValueError):
        return {}


def _detect_unsafe_level_setpoints(functional_requirements: list[dict[str, Any]]) -> list[str]:
    """
    Deterministic, config-driven range check (section 15): never left to the LLM's judgement.
    Returns human-readable messages for each set_level_setpoint requirement outside
    [min, max] from config/pid_supervisor_config.json.
    """
    config = _load_pid_supervisor_config().get("level_setpoint", {})
    min_value = config.get("min", 10.0)
    max_value = config.get("max", 90.0)
    messages: list[str] = []
    for requirement in functional_requirements:
        if requirement.get("type") != "set_level_setpoint":
            continue
        value = requirement.get("value")
        if not isinstance(value, (int, float)):
            continue
        if value < min_value or value > max_value:
            messages.append(
                f"El setpoint solicitado ({value}) esta fuera del rango seguro permitido "
                f"({min_value} a {max_value})."
            )
    return messages


INTENT_PARAMETER_RULES = {
    "INT_TIMED_PULSE": {
        "required": ["trigger_input", "emergency_input", "output", "duration", "timer"],
        "time_keys": ["duration"]
    },
    "INT_MOTOR_START_STOP": {
        "required": ["trigger_input", "stop_input", "emergency_input", "motor_output", "run_latch"],
        "time_keys": []
    },
    "INT_DELAYED_START": {
        "required": ["trigger_input", "stop_input", "emergency_input", "motor_output", "delay_time", "timer"],
        "time_keys": ["delay_time"]
    },
    "INT_DELAYED_STOP": {
        "required": [
            "trigger_input",
            "stop_input",
            "emergency_input",
            "motor_output",
            "run_latch",
            "stop_delay_active",
            "stop_delay_time",
            "timer"
        ],
        "time_keys": ["stop_delay_time"]
    },
    "INT_COUNTER_PULSES": {
        "required": ["pulse_input", "reset_input", "emergency_input", "output", "counter", "preset"],
        "time_keys": [],
        "positive_int_keys": ["preset"]
    },
    "INT_CYCLIC_MOTOR": {
        "required": [
            "trigger_input",
            "stop_input",
            "emergency_input",
            "motor_output",
            "run_latch",
            "step_memory",
            "start_edge",
            "on_timer",
            "off_timer",
            "on_time",
            "off_time"
        ],
        "time_keys": ["on_time", "off_time"]
    }
}


def _collect_parameter_tags(parameters: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for value in parameters.values():
        if isinstance(value, str) and PLC_TAG_PATTERN.match(value):
            if value not in tags:
                tags.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and PLC_TAG_PATTERN.match(item) and item not in tags:
                    tags.append(item)
    return tags


def _humanize_outputs(outputs: list[str]) -> str:
    names = []
    for tag in outputs:
        for prefix in ("Q_", "AO_", "I_", "AI_"):
            if tag.startswith(prefix):
                tag = tag[len(prefix):]
                break
        names.append(tag.replace("_", " ").strip())
    return ", ".join(names) or "las salidas indicadas"


def describe_sequence_gap(gap: dict[str, Any]) -> str:
    """Pregunta funcional (una sola) para el primer dato indispensable que falta en una secuencia."""
    if gap["kind"] == "duration":
        return (f"¿Cuánto tiempo debe permanecer activa la etapa {gap['step']} ({_humanize_outputs(gap['outputs'])}) "
                f"antes de pasar a la siguiente ({_humanize_outputs(gap.get('next_outputs') or [])})?")
    if gap["kind"] == "start_input":
        return "¿Con qué pulsador o señal debe iniciarse la secuencia?"
    return f"¿Qué salidas deben activarse en la etapa {gap['step']} de la secuencia?"


def _collect_functional_requirement_tags(functional_requirements: list[dict[str, Any]]) -> list[str]:
    """
    A functional_requirement's own fields (target, trigger_input, output_a, output_b, ...) can
    reference a physical tag that never appears anywhere in the base intent's flat `parameters` -
    a multi-actor command's SECOND motor_start_latch, for instance, is entirely described inside
    functional_requirements. _collect_parameter_tags only ever scanned `parameters`, so a
    brand-new tag referenced ONLY here (e.g. "I_Start_Motor_1" as a motor_start_latch
    trigger_input) never got flagged as needing allocation - it just silently reached
    ir_builder.build_project_ir's hard "recurso externo no autorizado" check later, with no
    io_assignment_proposal ever generated for it. Scans every string value in every requirement
    dict generically (field names vary per requirement type), exactly like _collect_parameter_tags
    does for `parameters`.
    """
    tags: list[str] = []
    for requirement in functional_requirements:
        if not isinstance(requirement, dict):
            continue
        _collect_nested_tags(requirement, tags)
    return tags


def _collect_nested_tags(value: Any, tags: list[str]) -> None:
    """Recorre strings, listas y dicts anidados (p.ej. timed_sequence.steps[].outputs[])."""
    if isinstance(value, str):
        if PLC_TAG_PATTERN.match(value) and value not in tags:
            tags.append(value)
    elif isinstance(value, list):
        for item in value:
            _collect_nested_tags(item, tags)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_nested_tags(item, tags)


def _core_semantic_payload(semantic_output: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "intent_id",
        "case_id",
        "command_text",
        "normalized_command",
        "parameters",
        "confidence",
        "ambiguities",
        "requires_clarification",
        "clarification_question",
        "assumptions",
        "recognized_tags",
        "unrecognized_terms",
        "functional_requirements",
        "operation_type",
        "requested_io_assignments"
    }
    return {
        key: semantic_output.get(key)
        for key in allowed_keys
        if key in semantic_output
    }


def _validate_time_literals(parameters: dict[str, Any], time_keys: list[str]) -> list[str]:
    errors: list[str] = []
    for key in time_keys:
        value = parameters.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not TIME_LITERAL_PATTERN.match(value):
            errors.append(f"El parametro {key} debe usar un TIME IEC valido.")
    return errors


def _validate_positive_ints(parameters: dict[str, Any], int_keys: list[str]) -> list[str]:
    errors: list[str] = []
    for key in int_keys:
        value = parameters.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or value <= 0:
            errors.append(f"El parametro {key} debe ser un entero positivo.")
    return errors


def _detect_contradictions(intent_id: str, parameters: dict[str, Any]) -> list[str]:
    contradictions: list[str] = []
    if parameters.get("trigger_input") and parameters.get("stop_input"):
        if parameters["trigger_input"] == parameters["stop_input"]:
            contradictions.append("trigger_input y stop_input no pueden referirse al mismo tag.")
    if intent_id == "INT_MUTUAL_INTERLOCK":
        if parameters.get("contactor_a") == parameters.get("contactor_b"):
            contradictions.append("Los dos contactores del enclavamiento mutuo deben ser distintos.")
    return contradictions


def _requires_emergency(
    intent_id: str,
    parameters: dict[str, Any],
    safety_rules: dict[str, Any],
    io_index: dict[str, Any]
) -> bool:
    # Seccion 4 (banco sin paro de emergencia cableado al PLC): nunca exigir I_Emergency si
    # fisicamente no existe en el mapa activo - de lo contrario CUALQUIER comando de un banco sin
    # esa senal fallaria siempre, sin remedio posible (no se puede autorizar un tag que no existe).
    if "I_Emergency" not in io_index:
        return False
    critical_outputs = set(safety_rules.get("critical_outputs", []))
    parameter_outputs = {
        value for key, value in parameters.items()
        if isinstance(value, str) and key.endswith("_output")
    }
    if parameter_outputs.intersection(critical_outputs):
        return True
    return intent_id in {
        "INT_MOTOR_START_STOP",
        "INT_MOTOR_LATCH",
        "INT_DELAYED_START",
        "INT_DELAYED_STOP",
        "INT_EMERGENCY_PRIORITY",
        "INT_MUTUAL_INTERLOCK",
        "INT_AUTO_STOP_TIMER",
        "INT_MANUAL_AUTO_MODE",
        "INT_MAINTENANCE_BLOCK",
        "INT_AUTO_CYCLE",
        "INT_CYCLIC_MOTOR"
    }


def validate_semantic_output(
    semantic_output: dict[str, Any],
    io_map: dict[str, Any],
    intents_catalog: dict[str, Any],
    safety_rules: dict[str, Any]
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    missing_parameters: list[str] = []
    unauthorized_tags: list[str] = []

    core_payload = _core_semantic_payload(semantic_output)
    structure_errors = validate_semantic_payload_structure(core_payload)
    errors.extend(structure_errors)

    try:
        semantic_model = validate_semantic_model(core_payload)
        payload = semantic_model_to_dict(semantic_model)
    except Exception as error:
        errors.append(f"El payload semantico no cumple el modelo Pydantic: {error}")
        payload = dict(core_payload)

    intent_id = str(payload.get("intent_id", "INT_UNKNOWN"))
    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict):
        parameters = {}

    # Recursos funcionales identificables, nombrables y asignables ANTES de IR/codegen (Modo Normal y
    # programas compuestos; Experimentacion conserva su validacion congelada). Las referencias
    # {role, actor, kind} sin nombre reciben su tag canonico, que luego entra al IOAllocator.
    functional_resource_errors: list[dict[str, Any]] = []
    composition_referenced_tags: list[str] = []
    raw_requirements = payload.get("functional_requirements", []) or []
    if semantic_output.get("interaction_profile") == "normal" or detect_timed_sequences(raw_requirements):
        resolution = resolve_functional_resources(raw_requirements)
        functional_resource_errors = resolution["errors"]
        composition_referenced_tags = resolution["referenced_tags"]
        payload["functional_requirements"] = resolution["requirements"]
        errors.extend(error["message"] for error in functional_resource_errors)
        if detect_timed_sequences(resolution["requirements"]):
            unsupported = [
                f"functional_requirements[{i}].type={r.get('type')!r}" for i, r in enumerate(resolution["requirements"])
                if isinstance(r, dict) and is_catalog_functional_requirement(r) and str(r.get("type")) not in COMPOSABLE_TYPES]
            if unsupported:
                errors.append("COMPOSITION_NOT_SUPPORTED: comportamiento no soportado dentro de un programa compuesto: "
                              + ", ".join(unsupported))

    if intent_id not in intents_catalog and intent_id != "INT_UNKNOWN":
        errors.append(f"La intencion no existe en el catalogo: {intent_id}")

    if intent_id == "INT_UNKNOWN":
        warnings.append("La intencion es INT_UNKNOWN.")

    # Comando multi-actor genuino (dos o mas motor_start_latch independientes): el intent_id base
    # elegido (p.ej. INT_DELAYED_STOP) se usa como "feature" para el timer/stop compartido, NO
    # como dueno exclusivo del programa - sus parametros planos de UN solo actor (motor_output,
    # run_latch, ...) dejan de ser obligatorios porque el compositor multi-actor
    # (code_generator._generate_multi_actor_motor_body) nunca los lee; toda la logica sale de
    # functional_requirements. Exigirlos igual reproduciria el bug real reportado ("faltan
    # motor_output, stop_delay_active, timer" en un comando que SI los representa, solo que de
    # forma composicional en vez de plana).
    is_multi_actor = len(detect_multi_actor_motor_targets(payload.get("functional_requirements", []) or [])) >= 2

    validation_rules = INTENT_PARAMETER_RULES.get(intent_id, {}) if not is_multi_actor else {}
    # Igual que _requires_emergency mas abajo (banco sin paro de emergencia cableado al PLC): la
    # lista "required" trata emergency_input como siempre obligatorio, pero eso contradice esa
    # misma politica ya establecida - se aplica la MISMA condicion aqui, nunca se exige
    # emergency_input si I_Emergency no existe fisicamente en el mapa activo.
    bench_has_emergency = any(str(variable.get("name")) == "I_Emergency" for variable in io_map.get("variables", []))
    for parameter_name in validation_rules.get("required", []):
        if parameter_name == "emergency_input" and not bench_has_emergency:
            continue
        if parameter_name not in parameters:
            missing_parameters.append(parameter_name)

    if missing_parameters:
        errors.append("Faltan parametros requeridos: " + ", ".join(missing_parameters))

    errors.extend(_validate_time_literals(parameters, validation_rules.get("time_keys", [])))
    errors.extend(_validate_positive_ints(parameters, validation_rules.get("positive_int_keys", [])))
    errors.extend(_detect_contradictions(intent_id, parameters))

    io_index = build_io_map_index(io_map)
    authorized_tags = set(io_index)
    recognized_tags = list(payload.get("recognized_tags", []))
    parameter_tags = _collect_parameter_tags(parameters)
    for tag in _collect_functional_requirement_tags(payload.get("functional_requirements", []) or []) + composition_referenced_tags:
        if tag not in parameter_tags:
            parameter_tags.append(tag)

    llm_disallowed_tags: list[str] = []
    for tag_name in recognized_tags + parameter_tags:
        if tag_name in authorized_tags:
            if tag_name in io_index and io_index[tag_name].get("llm_allowed", True) is False and tag_name not in llm_disallowed_tags:
                llm_disallowed_tags.append(tag_name)
            continue
        if tag_name.startswith(INTERNAL_PREFIXES):
            # Recurso interno de implementacion (timer/counter/memoria/flanco): puede no
            # existir todavia en el mapa activo, ir_builder lo genera automaticamente.
            continue
        if tag_name not in unauthorized_tags:
            unauthorized_tags.append(tag_name)

    # Dos niveles de validacion (seccion 11/12 - no confundir "no existe el nombre todavia" con
    # "no tiene sentido"): un tag no autorizado pero bien formado (prefijo fisico I_/Q_/AI_/AO_ +
    # identificador IEC valido) es una NECESIDAD FUNCIONAL, no un error - el IOAllocator intenta
    # resolverlo a un canal fisico real (FREE o ASSIGNED reasignable) ANTES de rechazarlo. Solo si
    # el allocator tampoco puede resolverlo (todo LOCKED/incompatible/insuficiente) es un error
    # real, y en ese caso el motivo es el del allocator (recursos insuficientes), nunca una
    # pregunta de "que tag usar".
    well_formed: list[str] = []
    if unauthorized_tags:
        well_formed = [tag for tag in unauthorized_tags if IEC_NAME_PATTERN.match(tag)]
        malformed = [tag for tag in unauthorized_tags if tag not in well_formed]
        if malformed:
            errors.append("Se detectaron tags no autorizados: " + ", ".join(malformed))

    if llm_disallowed_tags:
        errors.append(
            "Las siguientes variables existen en el mapa activo pero no estan autorizadas para uso por LLM "
            "(llm_allowed=false): " + ", ".join(llm_disallowed_tags)
        )

    if _requires_emergency(intent_id, parameters, safety_rules, io_index) and "I_Emergency" not in parameter_tags and parameters.get("emergency_input") != "I_Emergency":
        errors.append("La logica solicitada requiere incluir I_Emergency.")

    requirements_payload = payload.get("functional_requirements", []) or []
    functional_requirement_conflicts = detect_functional_requirement_conflicts(requirements_payload)
    unsafe_setpoints = _detect_unsafe_level_setpoints(requirements_payload)

    clarification_question = payload.get("clarification_question")
    requires_clarification = bool(payload.get("requires_clarification", False))
    if functional_requirement_conflicts and not requires_clarification:
        # Composicion != ambiguedad, PERO un conflicto real entre requisitos si necesita al
        # usuario: no se puede combinar automaticamente sin arbitrar entre valores distintos.
        requires_clarification = True
        conflict_summary = "; ".join(conflict["reason"] for conflict in functional_requirement_conflicts)
        clarification_question = (
            payload.get("clarification_question")
            or f"Se detecto un conflicto entre requisitos funcionales: {conflict_summary} "
            "Indique cual valor debe aplicarse."
        )
    sequence_gaps = timed_sequence_missing_data(requirements_payload)
    if sequence_gaps and not requires_clarification:
        # Dato FUNCIONAL indispensable ausente en una secuencia compuesta: se pregunta UNA sola cosa,
        # en lenguaje del proceso (nunca catalogo/intencion/schema).
        requires_clarification = True
        clarification_question = payload.get("clarification_question") or describe_sequence_gap(sequence_gaps[0])
    if unsafe_setpoints and not requires_clarification:
        # Regla deterministica (seccion 15 PID): el rango seguro NUNCA queda a criterio del LLM.
        requires_clarification = True
        clarification_question = payload.get("clarification_question") or (
            "; ".join(unsafe_setpoints) + " Indique un valor dentro del rango permitido."
        )
    requested_io_assignments = payload.get("requested_io_assignments") or []

    # Fase unica normalizada (seccion 6/7 de una tarea anterior): las propuestas IMPLICITAS
    # (tags no autorizados detectados en parametros/recognized_tags, `well_formed` arriba) y las
    # EXPLICITAS (requested_io_assignments del LLM/parser) se resuelven en UN SOLO lote de
    # propose_assignment() - nunca en dos llamadas independientes. Cada llamada a
    # propose_assignment() tiene su propio `claimed_in_batch` interno y su propia comprobacion de
    # nombre duplicado contra el mapa ORIGINAL (que todavia no conoce ningun nombre nuevo de este
    # comando); dos llamadas separadas para el MISMO nombre funcional (p.ej. un comando que
    # menciona "motor 2" a la vez como referencia implicita en un parametro y como asignacion de
    # mapa explicita) podian resolver, cada una por su cuenta, a un canal FREE DISTINTO - ninguna
    # de las dos veia la propuesta de la otra, y el resultado combinado terminaba con el MISMO
    # functional_name en dos direcciones fisicas activas (el bug real: "I_Start_Motor_2" duplicado
    # en el mapa). Un solo lote comparte `claimed_in_batch`, asi que la segunda mencion del mismo
    # nombre encuentra la PRIMERA propuesta ya resuelta (via find_variable_by_name/claimed
    # address) en vez de reclamar un canal libre distinto.
    combined_requests = (
        [{"functional_name_hint": tag} for tag in well_formed]
        + list(requested_io_assignments)
    )
    implicit_count = len(well_formed)
    io_assignment_proposals: list[dict[str, Any]] = []
    if combined_requests:
        combined_proposals = propose_assignment(io_map, combined_requests)
        implicit_proposals = combined_proposals[:implicit_count]
        explicit_proposals = combined_proposals[implicit_count:]
        io_assignment_proposals = combined_proposals

        resolved_names = {p["proposed_name"] for p in implicit_proposals if not p.get("blocked")}
        unauthorized_tags = [tag for tag in unauthorized_tags if tag not in resolved_names]
        for proposal in implicit_proposals:
            if proposal.get("blocked"):
                errors.append(f"Recurso funcional sin canal fisico disponible: {proposal.get('reason')}")

        # MAP_CONFIG (docs/23_io_allocator.md): el LLM/parser solo aporto menciones crudas de
        # texto (requested_io_assignments); TODA la resolucion de direccion/estado/compatibilidad
        # ocurre aqui, deterministicamente, contra el mapa activo real - nunca se confia en una
        # direccion que el LLM haya calculado por su cuenta.
        #
        # Politica de cero confirmaciones en Modo Normal (seccion 22 de una tarea anterior):
        # reasignar un canal ASSIGNED a un rol distinto NO fuerza requires_clarification - gui.py
        # aplica todo lo no bloqueado y lo informa despues (nunca antes). Solo lo realmente
        # irresoluble (blocked=True) es un error real.
        for proposal in explicit_proposals:
            if proposal.get("blocked"):
                errors.append(f"Asignacion de mapa rechazada: {proposal.get('reason')}")

    if requires_clarification and not clarification_question:
        errors.append("Se solicito aclaracion pero no existe clarification_question.")

    ambiguities = payload.get("ambiguities", [])
    if ambiguities and not requires_clarification:
        warnings.append("Se detectaron ambiguedades pero requires_clarification esta en false.")

    if payload.get("unrecognized_terms"):
        warnings.append("Existen terminos no reconocidos que requieren revision manual.")

    try:
        get_required_variables_for_intent(intent_id, parameters)
    except ValueError as error:
        message = str(error)
        # Comando multi-actor genuino (seccion "ningun intent_id representa varios motores
        # independientes por si solo" - ver ir_builder.build_project_ir/code_generator.
        # detect_multi_actor_motor_targets): intent_id sin plantilla (tipicamente INT_UNKNOWN) NO
        # es un error real aqui si functional_requirements ya describe >=2 actores independientes
        # con motor_start_latch - el compositor multi-actor genera el programa completo sin
        # depender de ningun template de un solo actor.
        if INTENT_TEMPLATE_NOT_IMPLEMENTED in message and has_composable_program(requirements_payload):
            pass
        elif INTENT_TEMPLATE_NOT_IMPLEMENTED in message:
            errors.append(f"La intencion no tiene plantilla implementada: {intent_id}")
        else:
            errors.append(message)

    normalized_command = str(payload.get("normalized_command", "")).lower()
    if "emergency" in normalized_command and intent_id not in {"INT_EMERGENCY_PRIORITY", "INT_MOTOR_START_STOP", "INT_DELAYED_START", "INT_DELAYED_STOP"}:
        warnings.append("El comando menciona emergencia y la intencion elegida podria requerir revision.")

    result = SemanticValidationResult(
        is_valid=not errors and not requires_clarification,
        errors=errors,
        warnings=warnings,
        missing_parameters=missing_parameters,
        unauthorized_tags=unauthorized_tags,
        requires_clarification=requires_clarification,
        clarification_question=clarification_question if requires_clarification else None,
        functional_requirement_conflicts=functional_requirement_conflicts,
        io_assignment_proposals=io_assignment_proposals
    )
    dumped = result.model_dump(mode="python")
    if functional_resource_errors:
        dumped["functional_resource_errors"] = functional_resource_errors  # detalle estructurado (codigo + ruta)
    return dumped
