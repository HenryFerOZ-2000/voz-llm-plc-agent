from __future__ import annotations

import re
from typing import Any

from ir_builder import INTENT_TEMPLATE_NOT_IMPLEMENTED, get_required_variables_for_intent
from schemas import (
    PLC_TAG_PATTERN,
    SemanticValidationResult,
    TIME_LITERAL_PATTERN,
    semantic_model_to_dict,
    validate_semantic_model,
    validate_semantic_payload_structure
)
from utils import build_io_map_index


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
        "unrecognized_terms"
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


def _requires_emergency(intent_id: str, parameters: dict[str, Any], safety_rules: dict[str, Any]) -> bool:
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

    if intent_id not in intents_catalog and intent_id != "INT_UNKNOWN":
        errors.append(f"La intencion no existe en el catalogo: {intent_id}")

    if intent_id == "INT_UNKNOWN":
        warnings.append("La intencion es INT_UNKNOWN.")

    validation_rules = INTENT_PARAMETER_RULES.get(intent_id, {})
    for parameter_name in validation_rules.get("required", []):
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

    llm_disallowed_tags: list[str] = []
    for tag_name in recognized_tags + parameter_tags:
        if tag_name not in authorized_tags and tag_name not in unauthorized_tags:
            unauthorized_tags.append(tag_name)
        elif tag_name in io_index and io_index[tag_name].get("llm_allowed", True) is False and tag_name not in llm_disallowed_tags:
            llm_disallowed_tags.append(tag_name)

    if unauthorized_tags:
        errors.append("Se detectaron tags no autorizados: " + ", ".join(unauthorized_tags))

    if llm_disallowed_tags:
        errors.append(
            "Las siguientes variables existen en el mapa activo pero no estan autorizadas para uso por LLM "
            "(llm_allowed=false): " + ", ".join(llm_disallowed_tags)
        )

    if _requires_emergency(intent_id, parameters, safety_rules) and "I_Emergency" not in parameter_tags and parameters.get("emergency_input") != "I_Emergency":
        errors.append("La logica solicitada requiere incluir I_Emergency.")

    clarification_question = payload.get("clarification_question")
    requires_clarification = bool(payload.get("requires_clarification", False))
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
        if INTENT_TEMPLATE_NOT_IMPLEMENTED in message:
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
        requires_clarification=requires_clarification
    )
    return result.model_dump(mode="python")
