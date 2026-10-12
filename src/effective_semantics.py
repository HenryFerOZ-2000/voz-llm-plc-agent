"""
SEMANTICA EFECTIVA: los recursos funcionales que de verdad usara el programa, explicitos y trazables.

Etapa entre parser/repair y validacion/IOAllocator/snapshot/IR/SCL (llm_parser._repair_and_validate,
la misma para reglas, LLM e hibrido, Modo Normal y Experimentacion). Antes de esta etapa el IR y el
generador rellenaban en silencio (`parameters.get("trigger_input", "I_Start")`) los recursos externos
que el parser no habia dado: el programa usaba I_Start/I_Stop/Q_Motor_Enable, pero `parameters` no los
contenia, el snapshot no los ligaba a ningun rol (parameter_bindings = {}) y el Oracle no podia
resolver START/STOP/MOTOR_MAIN (ensayo DEVELOPMENT D03_V2_TEXT_DEV_006).

Ahora:
  * `parameters` contiene TODOS los recursos externos funcionales del intent (mismos valores que el IR
    habria usado: fuente unica ir_builder.INTENT_RESOURCE_TABLE), con sus tipos de siempre (strings);
  * `parameter_provenance` (aparte, sin cambiar el schema de `parameters`) dice de donde salio cada uno:
    LLM / RULES / PARSER / REPAIR / DEFAULT;
  * `effective_semantics` guarda los parametros INTERPRETADOS (antes de defaults), los defaults
    tecnicos internos y de valor (solo trazados) y los errores estructurados.

Reglas (nunca inventar):
  * solo se completa una clave que el contrato del intent exige y que el parser no dio, nunca una clave
    OPCIONAL (reset/alarma/pilotos solo si el comando los pidio) ni una clave que la validacion exige
    que el parser exprese (INTENT_PARAMETER_RULES.required: su ausencia sigue siendo un error);
  * el recurso se resuelve contra el mapa activo/working map: si existe con ese nombre (LOCKED/ASSIGNED)
    se usa; si no existe, lo resuelve el MISMO IOAllocator en la validacion (canal FREE compatible,
    nunca un tag fantasma); emergencia nunca se crea: sin I_Emergency en el banco queda el literal FALSE;
  * dos candidatos (nombre duplicado en el mapa, o el nombre ya ocupa otro rol) -> AMBIGUOUS_FUNCTIONAL_RESOURCE,
    tipo de senal incompatible -> FUNCTIONAL_RESOURCE_KIND_MISMATCH: no se completa y la validacion falla.
"""
from __future__ import annotations

import copy
from typing import Any

from functional_requirements import (
    FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS,
    canonical_requirement_type,
    has_composable_program,
)
from ir_builder import EXTERNAL_PREFIXES, INTENT_VALUE_DEFAULTS, OPTIONAL_PARAMETER_KEYS, intent_resource_table, slot_value

SCHEMA_VERSION = 1

SOURCE_LLM = "LLM"
SOURCE_RULES = "RULES"
SOURCE_PARSER = "PARSER"
SOURCE_REPAIR = "REPAIR"
SOURCE_DEFAULT = "DEFAULT"
INTERPRETED_SOURCES = frozenset({SOURCE_LLM, SOURCE_RULES, SOURCE_PARSER, SOURCE_REPAIR})

CATEGORY_EXTERNAL = "EXTERNAL_FUNCTIONAL_RESOURCE"   # B: I_/Q_/AI_/AO_
CATEGORY_INTERNAL = "INTERNAL_TECHNICAL_RESOURCE"    # A: M_/T_/C_/R_ (autogenerado, nunca toca el mapa)
CATEGORY_SAFE_LITERAL = "SAFE_LITERAL"               # C: p.ej. emergency_input = FALSE
CATEGORY_VALUE = "FUNCTIONAL_VALUE_DEFAULT"          # D: duraciones/presets que usa la plantilla si faltan

STATUS_RESOLVED = "RESOLVED"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

RESOLUTION_MAP_EXISTING = "MAP_EXISTING"
RESOLUTION_IO_ALLOCATION = "IO_ALLOCATION"

ERROR_AMBIGUOUS = "AMBIGUOUS_FUNCTIONAL_RESOURCE"
ERROR_KIND_MISMATCH = "FUNCTIONAL_RESOURCE_KIND_MISMATCH"
ERROR_UNRESOLVED = "FUNCTIONAL_RESOURCE_UNRESOLVED"

EMERGENCY_KEY = "emergency_input"
EMERGENCY_TAG = "I_Emergency"
SAFE_FALSE = "FALSE"


def _signal_direction(variable: dict[str, Any]) -> str | None:
    """'I' / 'Q' por la direccion fisica (o la clase si no tiene direccion)."""
    location = str(variable.get("location") or "").strip().upper()
    if location.startswith("%I"):
        return "I"
    if location.startswith("%Q"):
        return "Q"
    var_class = str(variable.get("class") or "").lower()
    return {"input": "I", "output": "Q"}.get(var_class)


def _expected_direction(name: str) -> str:
    return "I" if name.startswith(("I_", "AI_")) else "Q"


def _resolve_default(name: str, key: str, parameters: dict[str, Any], io_map: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(resolucion, error). Nunca adivina: 0 coincidencias -> IOAllocator; >1 o conflicto -> error."""
    others = sorted(other for other, value in parameters.items() if value == name and other != key)
    if others:
        return None, {"code": ERROR_AMBIGUOUS, "key": key, "candidates": [name],
                      "detail": f"{key}: el recurso por defecto {name} ya cumple otro rol ({', '.join(others)}); no se adivina."}
    matches = [variable for variable in io_map.get("variables", []) or [] if str(variable.get("name")) == name]
    if len(matches) > 1:
        return None, {"code": ERROR_AMBIGUOUS, "key": key, "candidates": sorted(str(m.get("location")) for m in matches),
                      "detail": f"{key}: {name} aparece {len(matches)} veces en el mapa; no se adivina cual usar."}
    if not matches:
        return {"resolution": RESOLUTION_IO_ALLOCATION, "address": None, "state": None}, None
    variable = matches[0]
    direction = _signal_direction(variable)
    if direction is not None and direction != _expected_direction(name):
        return None, {"code": ERROR_KIND_MISMATCH, "key": key, "candidates": [str(variable.get("location"))],
                      "detail": f"{key}: {name} existe en el mapa como senal de otro tipo ({variable.get('location')})."}
    return {"resolution": RESOLUTION_MAP_EXISTING, "address": variable.get("location"), "state": variable.get("state")}, None


def _bench_has_emergency(io_map: dict[str, Any]) -> bool:
    return any(str(variable.get("name")) == EMERGENCY_TAG for variable in io_map.get("variables", []) or [])


def normalize_effective_semantics(
    semantic_output: dict[str, Any],
    io_map: dict[str, Any],
    origin: str = SOURCE_PARSER,
    parameters_before_repair: dict[str, Any] | None = None,
    parser_required_keys: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """
    Devuelve una COPIA de semantic_output con parameters efectivos, parameter_provenance y
    effective_semantics. `parameters_before_repair` permite atribuir a REPAIR lo que cambio el repair;
    `parser_required_keys` son claves que el parser DEBE expresar (no se completan nunca).
    """
    result = dict(semantic_output)
    parameters = semantic_output.get("parameters")
    intent_id = str(semantic_output.get("intent_id") or "INT_UNKNOWN")
    if not isinstance(parameters, dict):
        result["effective_semantics"] = {"schema_version": SCHEMA_VERSION, "status": STATUS_NOT_APPLICABLE, "intent_id": intent_id,
                                         "reason": "parameters no es un objeto", "errors": []}
        return result
    before = parameters_before_repair if isinstance(parameters_before_repair, dict) else parameters
    interpreted = copy.deepcopy(parameters)
    provenance: dict[str, dict[str, Any]] = {}
    for key, value in parameters.items():
        repaired = key not in before or before.get(key) != value
        entry: dict[str, Any] = {"source": SOURCE_REPAIR if repaired else origin}
        if repaired:
            entry["original_value"] = before.get(key)
            entry["reason"] = "valor fijado por semantic_repair (normalizacion de forma o banco sin emergencia)"
        if value == SAFE_FALSE:
            entry["category"] = CATEGORY_SAFE_LITERAL
        provenance[key] = entry

    # Programas compuestos (multi-actor, secuencias temporizadas) no usan la plantilla del intent: sus
    # recursos salen de functional_requirements (functional_resources). No se completa nada aqui.
    composable = has_composable_program(list(semantic_output.get("functional_requirements") or []))
    table = None if composable else intent_resource_table(intent_id)
    effective = dict(parameters)
    errors: list[dict[str, Any]] = []
    defaulted: list[str] = []
    internal_defaults: dict[str, str] = {}
    value_defaults: dict[str, Any] = {}
    if table is None:
        status = STATUS_NOT_APPLICABLE  # intent sin plantilla o programa compuesto
    else:
        optional = OPTIONAL_PARAMETER_KEYS.get(intent_id, set())
        required_by_parser = set(parser_required_keys or ())
        for key, default in table:
            if key in effective or key in optional or slot_value(intent_id, effective, key) is not None:
                continue
            if not default.startswith(EXTERNAL_PREFIXES):
                internal_defaults[key] = default  # A: tecnico interno, lo autogenera el IR
                continue
            if key in required_by_parser:
                continue  # su ausencia es un error de validacion propio ("Faltan parametros requeridos")
            if key == EMERGENCY_KEY and not _bench_has_emergency(io_map):
                # Nunca se crea una emergencia: sin I_Emergency cableada, literal seguro (mismo criterio
                # que semantic_repair.strip_unavailable_emergency_reference).
                effective[key] = SAFE_FALSE
                provenance[key] = {"source": SOURCE_DEFAULT, "category": CATEGORY_SAFE_LITERAL, "original_value": None,
                                   "reason": "El banco no tiene I_Emergency cableada: literal FALSE (sin recurso fisico)."}
                defaulted.append(key)
                continue
            resolution, error = _resolve_default(default, key, effective, io_map)
            if error:
                errors.append(error)
                continue
            effective[key] = default
            provenance[key] = {
                "source": SOURCE_DEFAULT, "category": CATEGORY_EXTERNAL, "original_value": None,
                "reason": f"{intent_id} exige '{key}' y el parser no lo dio: recurso unico del contrato del intent.",
                **resolution,
            }
            defaulted.append(key)
        # Recursos que exige un REQUISITO presente (FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS): mismo criterio que
        # el contrato del intent - explicitos y trazados antes del IOAllocator, para que el snapshot los ligue
        # a su rol (p.ej. la orden manual de manual_pump_enable). Nunca se crea una emergencia.
        for requirement in semantic_output.get("functional_requirements") or []:
            if not isinstance(requirement, dict):
                continue
            req_type = canonical_requirement_type(requirement.get("type"))
            for key, default in (FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS.get(req_type) or {}).items():
                if key in effective or key == EMERGENCY_KEY or not default.startswith(EXTERNAL_PREFIXES):
                    continue
                resolution, error = _resolve_default(default, key, effective, io_map)
                if error:
                    errors.append(error)
                    continue
                effective[key] = default
                provenance[key] = {
                    "source": SOURCE_DEFAULT, "category": CATEGORY_EXTERNAL, "original_value": None,
                    "reason": f"El requisito '{req_type}' exige '{key}' y el parser no lo dio: recurso del contrato del requisito.",
                    **resolution,
                }
                defaulted.append(key)
        for key, default in (INTENT_VALUE_DEFAULTS.get(intent_id) or {}).items():
            if key not in effective:
                value_defaults[key] = default  # D: solo trazado; la plantilla lo usa, el comando no lo dijo
        status = STATUS_UNRESOLVED if errors else STATUS_RESOLVED

    result["parameters"] = effective
    result["parameter_provenance"] = provenance
    result["effective_semantics"] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "intent_id": intent_id,
        "origin": origin,
        "interpreted_parameters": interpreted,
        "defaulted_keys": defaulted,
        "internal_technical_defaults": internal_defaults,
        "functional_value_defaults": value_defaults,
        "errors": errors,
    }
    return result


def interpreted_parameters(semantic_output: dict[str, Any] | None) -> dict[str, Any]:
    """
    Parametros que de verdad expreso la interpretacion (sin los completados por DEFAULT). Es lo que debe
    mirar la evaluacion SEMANTICA del benchmark: un default trazado nunca cuenta como algo que el comando dijo.
    Ensayos anteriores (sin provenance): todos los parametros cuentan como interpretados.
    """
    semantic_output = semantic_output or {}
    parameters = semantic_output.get("parameters") or {}
    provenance = semantic_output.get("parameter_provenance") or {}
    if not isinstance(parameters, dict):
        return {}
    return {key: value for key, value in parameters.items()
            if (provenance.get(key) or {}).get("source", SOURCE_PARSER) in INTERPRETED_SOURCES}


def validation_errors(semantic_output: dict[str, Any]) -> list[str]:
    """Mensajes para la validacion semantica (se falla ANTES de IOAllocator/IR/SCL)."""
    return [f"{error['code']}: {error['detail']}" for error in (semantic_output.get("effective_semantics") or {}).get("errors") or []]


__all__ = [
    "normalize_effective_semantics", "interpreted_parameters", "validation_errors",
    "SOURCE_DEFAULT", "SOURCE_LLM", "SOURCE_RULES", "SOURCE_REPAIR", "SOURCE_PARSER",
    "STATUS_RESOLVED", "STATUS_UNRESOLVED", "STATUS_NOT_APPLICABLE",
    "ERROR_AMBIGUOUS", "ERROR_KIND_MISMATCH", "ERROR_UNRESOLVED",
]
