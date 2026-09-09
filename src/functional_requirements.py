"""
Shared catalog for composable `functional_requirements`: additional behaviors a command can
request beyond its single main `intent_id` (e.g. "run_pilot", "delayed_stop"). One catalog,
reused by the parser (rule-based detection + LLM coverage check), the validator (conflict
detection), the IR builder (tag resolution -> external/internal split) and the code generator
(extra ST clauses) - never duplicated per module.

Design rule (mirrors the rest of the project): I_/Q_ tags are external and must already exist
in the active PLC map; M_/T_/C_/R_ tags are internal and are always auto-generated. A
functional_requirement type never bypasses that rule - it only says WHICH tags a behavior needs.
"""

from __future__ import annotations

from typing import Any

# type -> concrete PLC tags it requires (fixed set, resolved via the existing external/internal
# split in ir_builder.py - never invented, never variable per instance).
FUNCTIONAL_REQUIREMENT_TAGS: dict[str, list[str]] = {
    "motor_start_latch": ["M_RunLatch"],
    "delayed_start": ["T_DelayStart"],
    "delayed_stop": ["M_StopDelayActive", "T_StopDelay"],
    "run_pilot": ["Q_Pilot_Run"],
    "stop_pilot": ["Q_Pilot_Stop"],
    "fault_pilot": ["Q_Pilot_Fault"],
    "alarm_output": ["Q_Alarm"],
    "emergency_priority": ["I_Emergency"],
    "reset_behavior": ["I_Reset"],
    "maintenance_inhibit": ["I_Maintenance"],
    "counter_requirement": ["C_PulseCount", "R_SensorPulse"],
    "automatic_mode": ["I_Mode_Auto", "M_AutoMode"],
    "manual_mode": ["I_Mode_Manual", "M_ManualMode"]
    # "interlock" is intentionally absent here: its tags are dynamic (output_a/output_b come
    # from the requirement instance itself, not a fixed pair) - see get_functional_requirement_tags.
}

# type -> Spanish trigger phrases used ONLY to flag that the command probably needs this type
# (semantic coverage check). This is a heuristic keyword catalog, not an NLU model: it exists to
# catch silently-dropped requirements in a compound command, not to replace the parser.
FUNCTIONAL_REQUIREMENT_KEYWORDS: dict[str, list[str]] = {
    "motor_start_latch": ["se mantenga encendido", "quede encendido", "enclavamiento", "enclavado"],
    "delayed_start": ["arranque retardado", "arranca despues de", "encendido retardado", "espera antes de encender"],
    "delayed_stop": ["paro retardado", "apagado retardado", "se detendra a los", "detiene despues de", "para despues de"],
    "run_pilot": ["piloto de marcha", "luz piloto", "indicador de marcha", "lampara de marcha"],
    "stop_pilot": ["piloto de paro", "luz de paro", "indicador de paro", "lampara de paro"],
    "fault_pilot": ["piloto de falla", "luz de falla", "indicador de falla"],
    "alarm_output": ["alarma"],
    "interlock": ["no permitas activar ambos", "enclavamiento mutuo", "nunca al mismo tiempo", "no simultaneamente"],
    "maintenance_inhibit": ["en mantenimiento", "bloquea el arranque", "modo mantenimiento"],
    "automatic_mode": ["modo automatico"],
    "manual_mode": ["modo manual"],
    "counter_requirement": ["cuenta", "pulsos"],
    "reset_behavior": ["boton de reset", "reinicio de falla", "reinicia la falla"]
}


def get_functional_requirement_tags(requirement: dict[str, Any]) -> list[str]:
    """Resolve the concrete PLC tags one functional_requirement entry implies."""
    req_type = str(requirement.get("type", "")).strip()
    if req_type == "interlock":
        tags = [str(requirement.get("output_a", "")).strip(), str(requirement.get("output_b", "")).strip()]
        return [tag for tag in tags if tag]
    return list(FUNCTIONAL_REQUIREMENT_TAGS.get(req_type, []))


def is_catalog_functional_requirement(requirement: dict[str, Any]) -> bool:
    """True for the new composable {"type": "run_pilot", ...} shape (vs. the older ad-hoc
    named-variable shape {"name": "Level_SP", "type": "REAL", ...} already used by ir_builder)."""
    req_type = str(requirement.get("type", "")).strip()
    return req_type in FUNCTIONAL_REQUIREMENT_TAGS or req_type == "interlock"


def compute_intent_covered_types(intent_definition: dict[str, Any]) -> set[str]:
    """
    Which functional_requirement types an intent ALREADY implements by itself, derived purely
    from its required_inputs/outputs/internal in intents_catalog.json (never hand-authored).
    """
    intent_tags = (
        set(intent_definition.get("required_inputs", []))
        | set(intent_definition.get("required_outputs", []))
        | set(intent_definition.get("required_internal", []))
    )
    return {
        req_type
        for req_type, tags in FUNCTIONAL_REQUIREMENT_TAGS.items()
        if tags and set(tags).issubset(intent_tags)
    }


def compute_semantic_coverage(
    command_text: str,
    intent_id: str,
    functional_requirements: list[dict[str, Any]],
    intents_catalog: dict[str, Any]
) -> dict[str, Any]:
    """
    Detects requirement types the command text seems to ask for that are represented neither by
    the chosen intent's own behavior nor by an explicit functional_requirements entry. This is
    what flags "semantic_coverage_incomplete" (section 6): a silent drop, not a real ambiguity.
    """
    normalized = command_text.lower()
    detected_types = {
        req_type
        for req_type, keywords in FUNCTIONAL_REQUIREMENT_KEYWORDS.items()
        if any(keyword in normalized for keyword in keywords)
    }
    explicit_types = {str(requirement.get("type", "")) for requirement in functional_requirements}
    intent_definition = intents_catalog.get(intent_id, {}) if isinstance(intents_catalog, dict) else {}
    covered_by_intent = compute_intent_covered_types(intent_definition) if isinstance(intent_definition, dict) else set()

    missing_types = sorted(detected_types - explicit_types - covered_by_intent)
    return {
        "detected_types": sorted(detected_types),
        "covered_by_intent": sorted(covered_by_intent),
        "explicit_types": sorted(explicit_types),
        "missing_types": missing_types,
        "complete": not missing_types
    }


def detect_functional_requirement_conflicts(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Bounded conflict detection: two entries of the SAME type with materially different
    parameters (e.g. two delayed_stop with different delay) are a real conflict - composition
    cannot silently pick one. Two entries with identical parameters are just a harmless
    duplicate, not a conflict.
    """
    by_type: dict[str, list[dict[str, Any]]] = {}
    for requirement in functional_requirements:
        by_type.setdefault(str(requirement.get("type", "")), []).append(requirement)

    conflicts: list[dict[str, Any]] = []
    for req_type, entries in by_type.items():
        if len(entries) < 2:
            continue
        signatures = {
            tuple(sorted((key, value) for key, value in entry.items() if key != "type"))
            for entry in entries
        }
        if len(signatures) > 1:
            conflicts.append(
                {
                    "type": req_type,
                    "entries": entries,
                    "reason": f"Se detectaron multiples requisitos '{req_type}' con parametros distintos."
                }
            )
    return conflicts


__all__ = [
    "FUNCTIONAL_REQUIREMENT_TAGS",
    "FUNCTIONAL_REQUIREMENT_KEYWORDS",
    "get_functional_requirement_tags",
    "is_catalog_functional_requirement",
    "compute_intent_covered_types",
    "compute_semantic_coverage",
    "detect_functional_requirement_conflicts"
]
