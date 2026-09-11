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

import re
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
    "manual_mode": ["I_Mode_Manual", "M_ManualMode"],
    # --- PID supervisory (P01-P12) - external/physical side only. Level_PV, Level_SP,
    # PID_Enable, Auto_Mode, Manual_Mode and the *_Alarm/*_Fault/Safe_Stop flags are deliberately
    # NOT here: they are software functional variables (see PID_PROCESS_VARIABLES below), never
    # converted to I_/Q_ tags, per the explicit instruction not to invent physical I/O for them.
    "set_auto_mode": [],
    "set_manual_mode": [],
    "set_level_setpoint": [],
    "enable_pid": ["I_Emergency"],
    "disable_pid": [],
    "high_level_alarm": ["Q_Alarm"],
    "low_level_alarm": ["Q_Alarm"],
    "sensor_range_fault": [],
    "conditional_alarm_reset": ["I_Reset"],
    "safe_overfill_stop": ["Q_Pump_Enable", "Q_Alarm"],
    "manual_pump_limit": ["Q_Pump_Enable"]
    # "interlock" is intentionally absent here: its tags are dynamic (output_a/output_b come
    # from the requirement instance itself, not a fixed pair) - see get_functional_requirement_tags.
}

# PID functional/process variables: software variables with NO I_/Q_/M_/T_/C_/R_/F_ prefix,
# resolved via the ad-hoc named-variable mechanism (ir_builder._resolve_functional_variables) -
# the SAME mechanism already used by generic functional variables like a setpoint. Never treated
# as physical I/O; never subject to the external-resource-must-exist-in-map rule.
PID_PROCESS_VARIABLES: dict[str, str] = {
    "Level_PV": "REAL",
    "Level_SP": "REAL",
    "PID_Enable": "BOOL",
    "Auto_Mode": "BOOL",
    "Manual_Mode": "BOOL",
    "High_Level_Alarm": "BOOL",
    "Low_Level_Alarm": "BOOL",
    "Sensor_Fault": "BOOL",
    "Safe_Stop": "BOOL"
}

# type -> which PID_PROCESS_VARIABLES names it touches (subset of PID_PROCESS_VARIABLES.keys()).
FUNCTIONAL_REQUIREMENT_PROCESS_VARIABLES: dict[str, list[str]] = {
    "set_auto_mode": ["Auto_Mode", "Manual_Mode"],
    "set_manual_mode": ["Auto_Mode", "Manual_Mode"],
    "set_level_setpoint": ["Level_SP"],
    "enable_pid": ["PID_Enable", "Auto_Mode", "Sensor_Fault", "Safe_Stop"],
    "disable_pid": ["PID_Enable"],
    "high_level_alarm": ["Level_PV", "High_Level_Alarm"],
    "low_level_alarm": ["Level_PV", "Low_Level_Alarm"],
    "sensor_range_fault": ["Level_PV", "Sensor_Fault", "PID_Enable"],
    "conditional_alarm_reset": ["High_Level_Alarm", "Low_Level_Alarm", "Sensor_Fault"],
    "safe_overfill_stop": ["Level_PV", "Safe_Stop", "PID_Enable"],
    "manual_pump_limit": ["Manual_Mode"]
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
    "reset_behavior": ["boton de reset", "reinicio de falla", "reinicia la falla"],
    # --- PID supervisory (P01-P12) ---
    "set_auto_mode": ["modo automatico", "habilita el automatico", "activa el automatico"],
    "set_manual_mode": ["modo manual"],
    "set_level_setpoint": ["setpoint", "set point", "nivel del tanque en", "nivel en", "establece el nivel", "configura level_sp"],
    "enable_pid": ["habilita el pid", "activa el pid", "habilita el control", "activa el control"],
    "disable_pid": ["desactiva el pid", "deshabilita el pid", "desactiva el control pid"],
    "high_level_alarm": ["alarma si el nivel supera", "nivel alto", "supera el", "nivel > "],
    "low_level_alarm": ["nivel bajo", "por debajo del", "nivel < "],
    "sensor_range_fault": ["fallo de sensor", "sensor fuera de rango", "sensor invalido"],
    "conditional_alarm_reset": ["reinicia la alarma", "reset de alarma", "limpia la alarma"],
    "safe_overfill_stop": ["sobrellenado", "parada segura", "detente de forma segura", "detén de forma segura"],
    "manual_pump_limit": ["operacion manual de la bomba", "bomba en manual", "controla la bomba manualmente"]
}


def strip_external_prefix(tag: str) -> str:
    """'Q_Motor_2' -> 'Motor_2' (also I_/AI_/AO_). Used to derive a per-actor internal name from
    an external tag, e.g. for a multi-actor motor_start_latch - never invented, always derived
    from the tag the requirement/parser already resolved."""
    for prefix in ("AI_", "AO_", "Q_", "I_"):
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return tag


def get_functional_requirement_tags(requirement: dict[str, Any]) -> list[str]:
    """Resolve the concrete PLC tags one functional_requirement entry implies."""
    req_type = str(requirement.get("type", "")).strip()
    if req_type == "interlock":
        tags = [str(requirement.get("output_a", "")).strip(), str(requirement.get("output_b", "")).strip()]
        return [tag for tag in tags if tag]
    if req_type == "motor_start_latch":
        # Un comando puede traer VARIAS instancias de motor_start_latch, una por actor (dos
        # motores independientes, por ejemplo) - cada una necesita su PROPIA memoria de
        # enclavamiento (nunca la misma "M_RunLatch" generica para los dos, que colapsaria el
        # estado de ambos actores en un solo bit). Se deriva del `target` de ESA instancia; sin
        # target (forma antigua/generica) se conserva el nombre fijo historico. Se incluye tambien
        # el propio `target` (tag externo, p.ej. "Q_Motor_2") - a diferencia del resto del
        # catalogo, aqui el target no necesariamente coincide con ningun parametro plano del
        # intent base (actor EXTRA de un comando multi-motor), asi que si no se declara aqui
        # podria quedar sin declarar en la IR.
        target = str(requirement.get("target", "")).strip()
        trigger_input = str(requirement.get("trigger_input", "")).strip()
        if target:
            tags = [target, f"M_{strip_external_prefix(target)}Latch"]
            if trigger_input:
                tags.append(trigger_input)
            return tags
    return list(FUNCTIONAL_REQUIREMENT_TAGS.get(req_type, []))


def get_functional_requirement_process_variables(requirement: dict[str, Any]) -> dict[str, str]:
    """
    Resolve the PID functional/process variables (no I_/Q_/M_ prefix - see PID_PROCESS_VARIABLES)
    one functional_requirement entry implies, as {name: iec_type}. Empty for D01-D20 types, which
    never touch process variables.
    """
    req_type = str(requirement.get("type", "")).strip()
    names = FUNCTIONAL_REQUIREMENT_PROCESS_VARIABLES.get(req_type, [])
    return {name: PID_PROCESS_VARIABLES[name] for name in names}


def detect_multi_actor_motor_targets(functional_requirements: list[dict[str, Any]]) -> list[dict[str, str]]:
    """
    A real command can request MULTIPLE independent motor actors in one go (two pushbuttons, two
    motors, mutually exclusive) - something NO single base intent template represents, since
    every INTENT template is written for exactly one actor. `motor_start_latch` functional
    requirements with an explicit target/trigger_input are how the parser/LLM already expresses
    "this actor needs its own independent start-and-hold behavior" (see
    tests/test_functional_requirements.py's per-actor conflict-detection tests) - this just
    collects the distinct actors described that way, in order, deduplicated by target. Shared by
    ir_builder.py (required_variables must not demand the single-actor intent's own flat
    parameters when this is actually a multi-actor program) and code_generator.py (dispatches to
    the multi-actor composer instead of a single-actor template).
    """
    actors: list[dict[str, str]] = []
    seen: set[str] = set()
    for requirement in functional_requirements:
        if str(requirement.get("type", "")) != "motor_start_latch":
            continue
        target = str(requirement.get("target", "")).strip()
        trigger_input = str(requirement.get("trigger_input", "")).strip()
        if target and trigger_input and target not in seen:
            seen.add(target)
            actors.append({"target": target, "trigger_input": trigger_input})
    return actors


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

    PID types (set_auto_mode, enable_pid, ...) and discrete D01-D20 types (automatic_mode,
    delayed_stop, ...) share some Spanish phrasing ("modo automatico" triggers both
    "automatic_mode" and "set_auto_mode"). Only the types belonging to the CURRENT intent's
    domain are considered, or a PID command would spuriously look "incomplete" for never
    mentioning a discrete-only type (and vice versa), wasting a retry on a false positive.
    """
    normalized = command_text.lower()
    is_pid_context = intent_id == "INT_PID_SUPERVISOR"
    detected_types = {
        req_type
        for req_type, keywords in FUNCTIONAL_REQUIREMENT_KEYWORDS.items()
        if (req_type in FUNCTIONAL_REQUIREMENT_PROCESS_VARIABLES) == is_pid_context
        and any(keyword in normalized for keyword in keywords)
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


_NUMBERED_ENTITY_PATTERN = re.compile(
    r"\b(motor|pulsante|pulsador|boton|bot[oó]n|bomba|v[aá]lvula|salida|sensor|entrada|contactor)\s*"
    r"(?:n[uú]mero\s*)?(\d+)\b",
    re.IGNORECASE
)
_RESPECTIVELY_PATTERN = re.compile(r"\brespectivamente\b", re.IGNORECASE)
_VICEVERSA_PATTERN = re.compile(r"\bviceversa\b", re.IGNORECASE)
_MUTUAL_EXCLUSION_PATTERN = re.compile(
    r"no\s+(?:pueden|puede)\w*\s+.{0,40}mismo\s+tiempo"
    r"|al\s+mismo\s+tiempo"
    r"|no\s+simult[aá]neamente"
    r"|enclavamiento\s+mutuo",
    re.IGNORECASE
)
_CROSS_TOGGLE_PATTERN = re.compile(
    r"si\s+se\s+(?:enciende|activa)\s+(?:uno|una).{0,50}se\s+(?:apaga|desactiva)\s+(?:el\s+otro|la\s+otra|el\s+otro)"
    r"|\b(?:uno|una)\b.{0,20}\bse\s+(?:apaga|desactiva)\b.{0,20}\b(?:otro|otra)\b",
    re.IGNORECASE
)
_CONDITION_MARKER_PATTERN = re.compile(r"\bcuando\b", re.IGNORECASE)


def detect_compositional_complexity(command_text: str) -> dict[str, Any]:
    """
    Señales ESTRUCTURALES (no palabras clave de un functional_requirement concreto) de que un
    comando es composicional - varios actores/relaciones que una intención simple probablemente
    no represente, aunque el parser por reglas este "seguro" de su propio match. Puramente
    determinista (regex sobre el texto), nunca decide el significado - solo si vale la pena
    consultar al LLM en modo hibrido en vez de confiar ciegamente en la confianza de reglas.
    """
    text = command_text or ""
    signals: list[str] = []

    numbered_entities: dict[str, set[str]] = {}
    for match in _NUMBERED_ENTITY_PATTERN.finditer(text):
        noun, number = match.group(1).lower(), match.group(2)
        numbered_entities.setdefault(noun, set()).add(number)
    repeated = {noun: sorted(numbers) for noun, numbers in numbered_entities.items() if len(numbers) >= 2}
    if repeated:
        signals.append(f"entidades numeradas repetidas: {repeated}")

    if _RESPECTIVELY_PATTERN.search(text):
        signals.append("conector 'respectivamente'")
    if _VICEVERSA_PATTERN.search(text):
        signals.append("conector 'viceversa'")
    if _MUTUAL_EXCLUSION_PATTERN.search(text):
        signals.append("exclusion mutua / al mismo tiempo")
    if _CROSS_TOGGLE_PATTERN.search(text):
        signals.append("apagado cruzado uno/otro")

    condition_markers = len(_CONDITION_MARKER_PATTERN.findall(text))
    if condition_markers >= 2:
        signals.append(f"{condition_markers} condiciones 'cuando'")

    return {
        "signals": signals,
        "score": len(signals),
        # Dos o mas senales independientes - una sola (p. ej. solo "cuando" aparece una vez, o un
        # unico numero suelto) no basta para forzar una consulta LLM adicional; evita falsos
        # positivos en comandos simples que mencionen un numero o una condicion aislada.
        "is_compositional": len(signals) >= 2
    }


_INTERLOCK_TYPES = {"interlock", "mutual_interlock"}


def _interlock_participants(requirement: dict[str, Any]) -> list[str]:
    if "participants" in requirement:
        raw = requirement.get("participants") or []
        return [str(participant).strip() for participant in raw if str(participant).strip()]
    tags = [requirement.get("output_a"), requirement.get("output_b")]
    return [str(tag).strip() for tag in tags if tag]


def normalize_interlock_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    """
    Canonical, comparison-only form for `interlock`/`mutual_interlock` functional_requirements
    (section "reutilizacion semantica de interlock"): participant ORDER never carries meaning -
    interlock(A, B) and interlock(B, A) describe the exact same mutual exclusion - so this always
    returns {"type": "mutual_interlock", "participants": <sorted, deduplicated list>, "max_active":
    <int, default 1>}, regardless of whether the input used the 2-way `interlock`
    output_a/output_b shape or was already a `mutual_interlock` with an explicit participants
    list. This is a COMPARISON helper only: it does not replace the original requirement in
    `functional_requirements`, and `get_functional_requirement_tags`/ir_builder keep resolving the
    original `interlock` entries exactly as before - only conflict/duplicate detection uses this
    canonical form.
    """
    participants = sorted(set(_interlock_participants(requirement)))
    max_active = requirement.get("max_active", 1)
    try:
        max_active = int(max_active)
    except (TypeError, ValueError):
        max_active = 1
    return {"type": "mutual_interlock", "participants": participants, "max_active": max_active}


def _detect_interlock_conflicts(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Real conflict for interlock/mutual_interlock: the EXACT same participant set (order-
    independent) requested with a DIFFERENT `max_active` - e.g. one requirement says only 1 of
    {Motor_1, Motor_2} may run while another says 2 of the same pair may. Different participant
    sets (a different pair, a subset, a complementary pair that together describe an N-way mutual
    exclusion) are never a conflict by themselves - see `merge_interlock_requirements`.
    """
    by_participants: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for entry in entries:
        normalized = normalize_interlock_requirement(entry)
        by_participants.setdefault(tuple(normalized["participants"]), []).append(normalized)

    conflicts: list[dict[str, Any]] = []
    for participants, normalized_entries in by_participants.items():
        max_active_values = {entry["max_active"] for entry in normalized_entries}
        if len(max_active_values) > 1:
            conflicts.append(
                {
                    "type": "interlock",
                    "entries": normalized_entries,
                    "reason": (
                        "Se detectaron requisitos 'interlock'/'mutual_interlock' con max_active "
                        f"distinto para los mismos participantes ({', '.join(participants)})."
                    )
                }
            )
    return conflicts


def merge_interlock_requirements(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normalizes, deduplicates, and merges a list of interlock/mutual_interlock requirements
    (assumes `_detect_interlock_conflicts` already found no real conflict among them - never call
    this to paper over one). Two-participant entries with `max_active == 1` ("only one of these
    two may run") are merged into a single N-way `mutual_interlock` ONLY when they form a
    COMPLETE graph over their connected participants - i.e. every possible pair within that group
    was explicitly stated (interlock(A,B) + interlock(A,C) + interlock(B,C) -> one mutual_interlock
    over {A, B, C}). An INCOMPLETE set of pairs (e.g. only A-B and A-C given, B-C never mentioned)
    is never merged into a 3-way exclusion - that would forbid B+C running together when the
    command never said that - so those edges are kept as separate, individually normalized
    entries instead.
    """
    normalized = [normalize_interlock_requirement(entry) for entry in requirements]

    seen: set[tuple[tuple[str, ...], int]] = set()
    deduped: list[dict[str, Any]] = []
    for entry in normalized:
        key = (tuple(entry["participants"]), entry["max_active"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)

    pairwise = [entry for entry in deduped if len(entry["participants"]) == 2 and entry["max_active"] == 1]
    other = [entry for entry in deduped if entry not in pairwise]

    edges: dict[str, set[str]] = {}
    unique_pairs: set[tuple[str, str]] = set()
    for entry in pairwise:
        a, b = entry["participants"]
        edges.setdefault(a, set()).add(b)
        edges.setdefault(b, set()).add(a)
        unique_pairs.add((a, b))

    merged: list[dict[str, Any]] = []
    visited: set[str] = set()
    for node in sorted(edges):
        if node in visited:
            continue
        stack = [node]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(edges.get(current, set()) - component)
        visited |= component

        expected_pair_count = len(component) * (len(component) - 1) // 2
        actual_pair_count = sum(1 for pair in unique_pairs if set(pair) <= component)
        if len(component) > 2 and actual_pair_count == expected_pair_count:
            merged.append({"type": "mutual_interlock", "participants": sorted(component), "max_active": 1})
        else:
            merged.extend(
                entry for entry in pairwise
                if set(entry["participants"]) <= component
            )

    merged.extend(other)
    return merged


def detect_functional_requirement_conflicts(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Bounded conflict detection: two entries of the SAME type with materially different
    parameters (e.g. two delayed_stop with different delay) are a real conflict - composition
    cannot silently pick one. Two entries with identical parameters are just a harmless
    duplicate, not a conflict.

    `interlock`/`mutual_interlock` entries are handled separately, through
    `_detect_interlock_conflicts` (order-independent participant comparison) - a raw
    key/value-dict signature comparison would wrongly flag interlock(A,B) vs interlock(B,A), or
    the pairwise edges of a genuine N-way mutual exclusion, as conflicting with each other, even
    though none of them actually contradicts another (see docs on
    `merge_interlock_requirements`).
    """
    by_type: dict[str, list[dict[str, Any]]] = {}
    for requirement in functional_requirements:
        by_type.setdefault(str(requirement.get("type", "")), []).append(requirement)

    conflicts: list[dict[str, Any]] = []

    interlock_entries: list[dict[str, Any]] = []
    for req_type in list(by_type):
        if req_type in _INTERLOCK_TYPES:
            interlock_entries.extend(by_type.pop(req_type))
    if len(interlock_entries) >= 2:
        conflicts.extend(_detect_interlock_conflicts(interlock_entries))

    for req_type, entries in by_type.items():
        if len(entries) < 2:
            continue
        conflicts.extend(_detect_same_type_conflicts(req_type, entries))
    return conflicts


# Toda clave que un requirement pueda usar para identificar A QUIEN se aplica (motor_1, Q_Motor_1,
# etc.) - nunca un parametro comparable en si mismo. `target` es la convencion oficial que el
# prompt/parser deben usar de ahora en adelante para un tipo PER-ACTOR/repetible; `output`/`motor`/
# `resource` quedan como alias tolerados por si una interpretacion (tipicamente del LLM) usa uno de
# esos nombres en su lugar en vez de `target` exacto - nunca se exige un formato unico.
_TARGET_KEYS = ("target", "output", "motor", "resource")


def _requirement_target(requirement: dict[str, Any]) -> str | None:
    for key in _TARGET_KEYS:
        value = requirement.get(key)
        if value:
            return str(value).strip()
    return None


def _detect_same_type_conflicts(req_type: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Seccion "identidad del requisito": mismo `type` + parametros distintos NO es automaticamente
    un conflicto - primero hay que separar por A QUIEN se aplica cada instancia (su `target`, ver
    `_requirement_target`). Dos requisitos del mismo tipo para actores DISTINTOS (motor_1 vs
    motor_2) nunca se comparan entre si, sin importar que otros parametros traigan - son
    independientes por definicion. Solo entre instancias que comparten el MISMO target (incluido
    el caso "ninguna trae target explicito", que se compara tal cual se hacia antes - compatibilidad
    hacia atras para los tipos GLOBAL/SINGLETON que nunca tuvieron ni necesitan un target) se
    aplica la comparacion de parametros restantes; una diferencia real ahi (distinto delay, distinto
    enabled, etc.) si es un conflicto genuino que amerita aclaracion.
    """
    by_target: dict[str | None, list[dict[str, Any]]] = {}
    for entry in entries:
        by_target.setdefault(_requirement_target(entry), []).append(entry)

    conflicts: list[dict[str, Any]] = []
    for target, target_entries in by_target.items():
        if len(target_entries) < 2:
            continue
        signatures = {
            tuple(sorted((key, value) for key, value in entry.items() if key != "type" and key not in _TARGET_KEYS))
            for entry in target_entries
        }
        if len(signatures) > 1:
            conflicts.append(
                {
                    "type": req_type,
                    "target": target,
                    "entries": target_entries,
                    "reason": (
                        f"Se detectaron multiples requisitos '{req_type}'"
                        + (f" para '{target}'" if target else "")
                        + " con parametros distintos."
                    )
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
    "detect_functional_requirement_conflicts",
    "detect_compositional_complexity",
    "normalize_interlock_requirement",
    "merge_interlock_requirements"
]
