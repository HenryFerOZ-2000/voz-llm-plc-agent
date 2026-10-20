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
    # Validacion de setpoint en el PLC: la solicitud (Level_SP_Command) solo pasa a Level_SP si esta en
    # [min, max]; fuera de rango se rechaza y Level_SP conserva el ultimo valor valido.
    "reject_unsafe_setpoint": [],
    "enable_pid": ["I_Emergency"],
    "disable_pid": [],
    "high_level_alarm": ["Q_Alarm"],
    "low_level_alarm": ["Q_Alarm"],
    "sensor_range_fault": [],
    "conditional_alarm_reset": ["I_Reset"],
    "safe_overfill_stop": ["Q_Pump_Enable", "Q_Alarm"],
    # Bomba en marcha en operacion normal (salvo emergencia / condicion segura activa).
    "enable_pump": ["Q_Pump_Enable"],
    # Manual (MODE_AUTO = FALSE): la bomba sigue solo la orden manual del operador (manual_pump_input).
    "manual_pump_enable": ["I_Manual_Pump_Command", "Q_Pump_Enable"],
    # --- Primitivas COMPONIBLES genericas (Modo Normal): sus tags son dinamicos (vienen de la
    # propia instancia) - ver get_functional_requirement_tags. Lista vacia = "tipo de catalogo".
    "timed_sequence": [],
    "never_together": [],
    # Supervision generica de un sensor: si no cambia de estado dentro de `timeout` tras el
    # arranque, detiene las salidas afectadas y enclava una alarma (tags dinamicos por instancia).
    "sensor_timeout_alarm": [],
    # Salida(s) gobernada(s) por una condicion (mantenida mientras se cumple, o pulso temporizado al cumplirse).
    "conditional_output": [],
    # Conmutacion con histeresis sobre una entrada analogica (activa por encima/debajo de un umbral y se
    # desactiva al cruzar el otro): nunca una comparacion simple.
    "hysteresis_switch": [],
    "analog_output": [],
    "pid_control": [],
    # Condicion que fuerza salidas a FALSE de inmediato (y detiene la secuencia que las maneja).
    "force_off": [],
    # Enclavamiento generico set/reset (reset con prioridad): marcha/paro, alarma con reconocimiento, ...
    "latch": [],
    # Contador ascendente (CTU) con salidas EXPLICITAS: alcanzado (BOOL) y valor actual (INT).
    "pulse_counter": []
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
    "Safe_Stop": "BOOL",
    "Level_SP_Command": "REAL"
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
    "reject_unsafe_setpoint": ["Level_SP_Command", "Level_SP"],
    "conditional_alarm_reset": ["High_Level_Alarm", "Low_Level_Alarm", "Sensor_Fault"],
    "safe_overfill_stop": ["Level_PV", "Safe_Stop", "PID_Enable"],
    "enable_pump": [],
    "manual_pump_enable": ["Auto_Mode"]
}

# Nombres historicos / sinonimos de requisitos -> nombre CANONICO (una sola taxonomia interna). Se
# normalizan al entrar al pipeline (llm_parser) y al comparar con las expectativas de un Oracle; el
# significado nunca cambia: cada alias designa exactamente el mismo comportamiento que su canonico.
FUNCTIONAL_REQUIREMENT_ALIASES: dict[str, str] = {
    "manual_pump_limit": "manual_pump_enable",
    "enable_pid_in_auto": "enable_pid",
}


def canonical_requirement_type(req_type: Any) -> str:
    text = str(req_type or "").strip()
    return FUNCTIONAL_REQUIREMENT_ALIASES.get(text, text)


def canonicalize_functional_requirements(functional_requirements: Any) -> list[dict[str, Any]]:
    """Copia con cada `type` en su nombre canonico (registra el alias original en `type_alias`)."""
    canonical: list[dict[str, Any]] = []
    for requirement in functional_requirements or []:
        if not isinstance(requirement, dict):
            canonical.append(requirement)
            continue
        req_type = str(requirement.get("type", "")).strip()
        target = canonical_requirement_type(req_type)
        if target != req_type:
            requirement = {**requirement, "type": target, "type_alias": req_type}
        canonical.append(requirement)
    return canonical


# Requisitos MUTUAMENTE INCOMPATIBLES dentro de UNA misma interpretacion (fuente declarativa). Cada regla:
# types (todos presentes -> conflicto), unless_parameters (el conflicto desaparece si la semantica trae
# alguno de esos parametros: una entrada de seleccion convierte las dos ordenes de modo en un selector
# coherente) y reason. Pares revisados en todo el catalogo: solo las ordenes de modo opuestas son
# incompatibles por si mismas; enable_pid/disable_pid componen (la deshabilitacion es la prioridad de
# seguridad), automatic_mode/manual_mode describen un selector y los requisitos POR ACTOR se comparan por
# `target` (_detect_same_type_conflicts).
FUNCTIONAL_REQUIREMENT_CONFLICTS: tuple[dict[str, Any], ...] = (
    {
        "types": ("set_auto_mode", "set_manual_mode"),
        "unless_parameters": ("auto_input",),
        "reason": ("set_auto_mode y set_manual_mode son ORDENES opuestas de cambio de modo sin una entrada de "
                   "seleccion que las condicione: escribirian Auto_Mode := TRUE y Auto_Mode := FALSE en el mismo ciclo."),
    },
)

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
    # Salida de alarma como ACCION ("activa una alarma"); "alarma activa" como condicion de entrada no la sugiere.
    "alarm_output": ["activa una alarma", "activa la alarma", "salida de alarma", "enciende la alarma", "enciende una alarma",
                     "suene una alarma", "suene la alarma", "salte una alarma", "genera una alarma", "activa alarma"],
    "interlock": ["no permitas activar ambos", "enclavamiento mutuo", "nunca al mismo tiempo", "no simultaneamente"],
    # "bloquea el arranque" suelto no es especifico de mantenimiento (tambien lo hace una emergencia).
    "maintenance_inhibit": ["en mantenimiento", "modo mantenimiento"],
    "automatic_mode": ["modo automatico"],
    "manual_mode": ["modo manual"],
    "counter_requirement": ["cuenta pulsos", "cuenta los pulsos", "contar pulsos", "contador de pulsos", "pulsos"],
    "reset_behavior": ["boton de reset", "reinicio de falla", "reinicia la falla"],
    # --- PID supervisory (P01-P12) ---
    # set_auto_mode / set_manual_mode son ACCIONES (orden de cambiar el modo): solo frases de accion. "en modo
    # automatico", "mientras este en Manual" son CONDICIONES y no deben sugerir una orden de cambio de modo.
    "set_auto_mode": ["pasa a modo automatico", "pasar a modo automatico", "cambia a modo automatico",
                      "pon el sistema en automatico", "habilita el automatico", "activa el automatico",
                      "entre en automatico", "entrar en automatico"],
    "set_manual_mode": ["pasa a modo manual", "pasar a modo manual", "cambia a modo manual", "pon el sistema en manual"],
    # Un valor de setpoint concreto; "setpoint" suelto tambien aparece al hablar de rangos o validacion.
    "set_level_setpoint": ["setpoint de nivel a", "setpoint del nivel al", "setpoint del nivel a", "consigna de nivel a",
                           "nivel del tanque en", "establece el nivel", "configura level_sp"],
    "reject_unsafe_setpoint": ["setpoint fuera de rango", "setpoint fuera del rango", "rechazalo y conserva",
                               "conserva el ultimo valor valido", "conservando el ultimo valido", "rechaza cualquier valor",
                               "se rechaza y se conserva"],
    "enable_pid": ["habilita el pid", "activa el pid", "habilita el control", "activa el control"],
    "disable_pid": ["desactiva el pid", "deshabilita el pid", "desactiva el control pid"],
    "high_level_alarm": ["alarma si el nivel supera", "nivel alto", "supera el", "nivel > "],
    "low_level_alarm": ["nivel bajo", "por debajo del", "nivel < "],
    "sensor_range_fault": ["fallo de sensor", "sensor fuera de rango", "sensor invalido"],
    "conditional_alarm_reset": ["reinicia la alarma", "reset de alarma", "limpia la alarma"],
    "safe_overfill_stop": ["sobrellenado", "parada segura", "detente de forma segura", "detén de forma segura"],
    "manual_pump_enable": ["orden manual del operador", "operacion manual de la bomba", "bomba en manual",
                           "controla la bomba manualmente"]
}


def fold_text(text: Any) -> str:
    """Minusculas y sin tildes: las palabras clave del catalogo se escriben sin tildes ("automatico", "ultimo")."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def strip_external_prefix(tag: str) -> str:
    """'Q_Motor_2' -> 'Motor_2' (also I_/AI_/AO_). Used to derive a per-actor internal name from
    an external tag, e.g. for a multi-actor motor_start_latch - never invented, always derived
    from the tag the requirement/parser already resolved."""
    for prefix in ("AI_", "AO_", "Q_", "I_"):
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return tag


TIME_LITERAL_PATTERN = re.compile(r"^T#\d+(ms|s|m|h)(\d+(ms|s|m))?$", re.IGNORECASE)
_BARE_TIME_PATTERN = re.compile(r"^(\d+)\s*(ms|s|m|h)$", re.IGNORECASE)

# ---------------------------------------------------------------------------------------------
# Secuencias (Modo Normal): un unico modelo generico de N etapas para cualquier maquina.
#
#   TRIGGER      start_input (pulsador, flanco) | mode_condition (habilitacion por nivel) | automatico
#                (solo en ciclo continuo sin disparador: inferido y registrado)
#   STEPS        steps[] en orden; cada etapa enumera TODAS sus salidas activas (outputs[] o actions[])
#   TRANSITIONS  duration (IEC TIME) y/o advance_on (condicion booleana/comparacion); con ambas avanza
#                con lo que ocurra primero, salvo timeout_alarm_output: si vence el tiempo antes de la
#                condicion la secuencia termina en falla y enclava esa alarma
#   REPEAT       once (al terminar -> reposo) | continuous (tras la ultima vuelve a la etapa 1) |
#                hold_last (la ultima se mantiene hasta Stop)
#   FINAL_STATE  reposo: todas las etapas en FALSE -> todas las salidas de la secuencia apagadas
# ---------------------------------------------------------------------------------------------
SEQUENCE_REPEAT_ONCE = "once"
SEQUENCE_REPEAT_CONTINUOUS = "continuous"
SEQUENCE_REPEAT_HOLD = "hold_last"
_SEQUENCE_REPEAT_ALIASES = {
    "once": SEQUENCE_REPEAT_ONCE, "single": SEQUENCE_REPEAT_ONCE, "single_cycle": SEQUENCE_REPEAT_ONCE,
    "one_shot": SEQUENCE_REPEAT_ONCE, "no_repeat": SEQUENCE_REPEAT_ONCE, "none": SEQUENCE_REPEAT_ONCE,
    "continuous": SEQUENCE_REPEAT_CONTINUOUS, "cyclic": SEQUENCE_REPEAT_CONTINUOUS, "loop": SEQUENCE_REPEAT_CONTINUOUS,
    "repeat": SEQUENCE_REPEAT_CONTINUOUS, "forever": SEQUENCE_REPEAT_CONTINUOUS,
    "hold_last": SEQUENCE_REPEAT_HOLD, "hold": SEQUENCE_REPEAT_HOLD, "until_stop": SEQUENCE_REPEAT_HOLD,
}
_ADVANCE_KEYS = ("advance_on", "transition_condition", "until")
_TIMEOUT_ALARM_KEYS = ("timeout_alarm_output", "timeout_alarm")
PROVENANCE_EXPLICIT = "EXPLICIT"
PROVENANCE_INFERRED = "INFERRED"
PROVENANCE_DEFAULT = "DEFAULT"


def normalize_time_literal(value: Any) -> str | None:
    """'T#5s' se conserva; '5s'/'5 s' -> 'T#5s' (misma unidad, sin reinterpretar); vacio -> None."""
    text = str(value or "").strip()
    if not text:
        return None
    bare = _BARE_TIME_PATTERN.match(text)
    return f"T#{bare.group(1)}{bare.group(2).lower()}" if bare else text


def _first_text(mapping: dict[str, Any], keys: tuple[str, ...]) -> str:
    return next((str(mapping[key]).strip() for key in keys if str(mapping.get(key) or "").strip()), "")


def _step_outputs(step: dict[str, Any]) -> list[str]:
    """Salidas ACTIVAS de una etapa: outputs[] o actions[{output, state/value}] (las OFF quedan implicitas)."""
    outputs = [str(o).strip() for o in (step.get("outputs") or []) if isinstance(o, str) and str(o).strip()]
    for action in step.get("actions") or []:
        if not isinstance(action, dict):
            continue
        name = _first_text(action, ("output", "target", "tag"))
        state = action.get("state", action.get("value", True))
        active = state if isinstance(state, bool) else str(state).strip().upper() not in ("FALSE", "OFF", "0")
        if name and active and name not in outputs:
            outputs.append(name)
    return outputs


def _raw_sequence_steps(requirement: dict[str, Any]) -> list[dict[str, Any]]:
    steps = []
    for step in requirement.get("steps") or []:
        if not isinstance(step, dict):
            continue
        steps.append({"outputs": _step_outputs(step),
                      "duration": normalize_time_literal(step.get("duration")),
                      "advance_on": _first_text(step, _ADVANCE_KEYS) or None,
                      "timeout_alarm_output": _first_text(step, _TIMEOUT_ALARM_KEYS) or None})
        if 'analog_outputs' in step:
            steps[-1]['analog_outputs'] = step['analog_outputs']
    return steps


def sequence_step_outputs(step: dict[str, Any]) -> list[str]:
    """All stage-owned outputs, keeping numeric commands separate from Boolean energization."""
    commands = step.get('analog_outputs')
    commands = commands if isinstance(commands, list) else []
    analog = [command['output'] for command in commands
              if isinstance(command, dict) and isinstance(command.get('output'), str) and command['output']]
    return list(dict.fromkeys([*step.get('outputs', []), *analog]))


def _is_end_marker(step: dict[str, Any]) -> bool:
    """Etapa final sin salidas, sin duracion y sin condicion: solo dice 'todo apagado' (estado final)."""
    return not sequence_step_outputs(step) and not step["duration"] and not step["advance_on"] and not step["timeout_alarm_output"]


def timed_sequence_steps(requirement: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Etapas efectivas de un timed_sequence: [{"outputs", "duration", "advance_on", "timeout_alarm_output"}].
    Las etapas finales vacias (marcador de "todo apagado") se descartan: describen el estado final de
    reposo, no una etapa que necesite salidas.
    """
    steps = _raw_sequence_steps(requirement)
    while steps and _is_end_marker(steps[-1]):
        steps.pop()
    return steps


def timed_sequence_repeat(requirement: dict[str, Any]) -> tuple[str, str]:
    """
    (politica de repeticion, procedencia). Explicita si `repeat` la indica; si no se infiere de la
    estructura: un marcador final de "todo apagado" o una ultima etapa con duracion/condicion -> once
    (termina y vuelve a reposo); una ultima etapa sin fin -> hold_last (se mantiene hasta Stop).
    """
    explicit = _SEQUENCE_REPEAT_ALIASES.get(str(requirement.get("repeat") or "").strip().lower())
    if explicit:
        return explicit, PROVENANCE_EXPLICIT
    raw, steps = _raw_sequence_steps(requirement), timed_sequence_steps(requirement)
    if not steps:
        return SEQUENCE_REPEAT_ONCE, PROVENANCE_INFERRED
    if len(raw) > len(steps) or steps[-1]["duration"] or steps[-1]["advance_on"]:
        return SEQUENCE_REPEAT_ONCE, PROVENANCE_INFERRED
    return SEQUENCE_REPEAT_HOLD, PROVENANCE_INFERRED


def timed_sequence_enable_condition(requirement: dict[str, Any]) -> str:
    return _first_text(requirement, ("mode_condition", "run_condition"))


def timed_sequence_start_mode(requirement: dict[str, Any]) -> str:
    """'input' (flanco del pulsador), 'condition' (habilitacion por nivel), 'auto' o '' (falta el disparador)."""
    if str(requirement.get("start_input") or "").strip() not in ("", "FALSE"):
        return "input"
    if timed_sequence_enable_condition(requirement):
        return "condition"
    if timed_sequence_repeat(requirement)[0] == SEQUENCE_REPEAT_CONTINUOUS:
        return "auto"
    return ""


def timed_sequence_internal_names(index: int, requirement: dict[str, Any]) -> list[dict[str, str]]:
    """Nombres internos deterministas por etapa: memoria M_Seq<k>_S<i> y temporizador T_Seq<k>_S<i>."""
    names = []
    steps = timed_sequence_steps(requirement)
    holds_last = timed_sequence_repeat(requirement)[0] == SEQUENCE_REPEAT_HOLD
    for position, step in enumerate(steps, start=1):
        timed = bool(step["duration"]) and not (holds_last and position == len(steps))
        names.append({"step": f"M_Seq{index}_S{position}", "timer": f"T_Seq{index}_S{position}" if timed else ""})
    return names


def timed_sequence_aux_names(index: int, requirement: dict[str, Any]) -> dict[str, str]:
    """Memorias auxiliares de la secuencia: flanco del pulsador de arranque y falla por tiempo excedido."""
    steps = timed_sequence_steps(requirement)
    return {"start_prev": f"M_Seq{index}_StartPrev" if timed_sequence_start_mode(requirement) == "input" else "",
            "fault": f"M_Seq{index}_Fault" if any(step["timeout_alarm_output"] for step in steps) else ""}


def detect_timed_sequences(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in functional_requirements or [] if isinstance(r, dict) and str(r.get("type", "")) == "timed_sequence"]


# Primitivas que SOLO el compositor de Modo Normal sabe generar: su presencia selecciona el programa compuesto.
# (never_together/alarm_output/reset_behavior/... tambien existen en programas de plantilla y no lo seleccionan.)
COMPOSED_PROGRAM_TYPES = ("timed_sequence", "conditional_output", "hysteresis_switch", "force_off", "latch", "pulse_counter", "analog_output")


def detect_composed_program(functional_requirements: list[dict[str, Any]], intent_id: str | None = None) -> bool:
    types = {str(r.get('type', '')) for r in functional_requirements or [] if isinstance(r, dict)}
    # A stop override is a modifier, not an alternative implementation of a known intent.
    # Without a known intent it retains the existing standalone composer behavior.
    modifiers = {'force_off', 'never_together', 'reset_behavior', 'emergency_priority',
                 'run_pilot', 'stop_pilot', 'fault_pilot', 'alarm_output', 'motor_start_latch',
                 'delayed_start', 'delayed_stop', 'maintenance_inhibit', 'counter_requirement',
                 'automatic_mode', 'manual_mode', 'interlock'}
    if (intent_id not in (None, '', 'INT_UNKNOWN') and 'force_off' in types and types <= modifiers
            and len(detect_multi_actor_motor_targets(functional_requirements)) < 2
            and not manual_commands(functional_requirements)):
        return False
    return bool(types.intersection(COMPOSED_PROGRAM_TYPES))


def has_composable_program(functional_requirements: list[dict[str, Any]], intent_id: str | None = None) -> bool:
    """
    Programa completo descrito SOLO por primitivas componibles (multi-actor o programa compuesto):
    un intent_id sin plantilla (INT_UNKNOWN) no es un error en ese caso.
    """
    return any(r.get('type')=='pid_control' for r in functional_requirements or []) or len(detect_multi_actor_motor_targets(functional_requirements or [])) >= 2 or detect_composed_program(functional_requirements, intent_id)


def _valid_time(value: str | None) -> bool:
    return bool(value) and bool(TIME_LITERAL_PATTERN.match(str(value)))


def latch_start_edge_names(memory: str) -> dict[str, str]:
    """Private BOOL state for the product's start/stop latch, without physical IO."""
    return {'previous': memory + '_StartPrevious', 'initialized': memory + '_StartInitialized',
            'pulse': memory + '_StartPulse'}


def single_latch_start_signal(expression: str) -> str | None:
    """Only a single positive command implies a start edge; preserve other Boolean logic."""
    text = str(expression or '').strip()
    while text.startswith('(') and text.endswith(')'):
        text = text[1:-1].strip()
    return text if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', text) else None


def timed_sequence_missing_data(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Datos FUNCIONALES indispensables que faltan (generico, nunca por frase), en orden para preguntar UNA
    cosa a la vez. Solo se pregunta lo que no puede inferirse con seguridad:
      * disparador: sin pulsador ni condicion de habilitacion (salvo ciclo continuo: arranque automatico);
      * etapas: ninguna etapa con salidas;
      * fin de etapa: toda etapa que debe terminar (no es la ultima de hold_last) necesita una duracion IEC
        o una condicion advance_on;
      * paro: una ultima etapa que se mantiene indefinidamente necesita Stop o condicion de habilitacion;
      * ciclo continuo de una sola etapa: no hay nada que alternar.
    """
    missing = []
    for requirement in detect_timed_sequences(functional_requirements):
        steps = timed_sequence_steps(requirement)
        repeat, _ = timed_sequence_repeat(requirement)
        if not timed_sequence_start_mode(requirement):
            missing.append({"kind": "start_input", "step": None, "outputs": []})
        if not any(sequence_step_outputs(step) for step in steps):
            missing.append({"kind": "outputs", "step": 1, "outputs": []})
            continue
        for position, step in enumerate(steps, start=1):
            outputs = sequence_step_outputs(step)
            last = position == len(steps)
            if last and repeat == SEQUENCE_REPEAT_HOLD:
                continue
            if step["duration"] and not _valid_time(step["duration"]):
                missing.append({"kind": "duration", "step": position, "outputs": outputs, "invalid": step["duration"],
                                "next_outputs": [] if last else sequence_step_outputs(steps[position]), "final": last})
            elif not step["duration"] and not step["advance_on"]:
                missing.append({"kind": "duration", "step": position, "outputs": outputs,
                                "next_outputs": sequence_step_outputs(steps[0]) if last and repeat == SEQUENCE_REPEAT_CONTINUOUS
                                else ([] if last else sequence_step_outputs(steps[position])),
                                "final": last and repeat == SEQUENCE_REPEAT_ONCE})
            if step["timeout_alarm_output"] and not (step["duration"] and step["advance_on"]):
                missing.append({"kind": "timeout_condition", "step": position, "outputs": outputs})
        stop_input = str(requirement.get("stop_input") or "").strip()
        if repeat == SEQUENCE_REPEAT_HOLD and stop_input in ("", "FALSE") and not timed_sequence_enable_condition(requirement):
            missing.append({"kind": "stop_input", "step": len(steps), "outputs": sequence_step_outputs(steps[-1])})
        if repeat == SEQUENCE_REPEAT_CONTINUOUS and len(steps) < 2:
            missing.append({"kind": "cycle", "step": 1, "outputs": sequence_step_outputs(steps[0])})
    return missing


def timed_sequence_inferences(functional_requirements: list[dict[str, Any]]) -> list[dict[str, str]]:
    """
    Lo que el sistema INFIERE o toma por DEFECTO (nunca en silencio): politica de repeticion deducida de la
    estructura, arranque automatico de un ciclo continuo sin disparador y el estado final de reposo.
    """
    inferences = []
    for index, requirement in enumerate(detect_timed_sequences(functional_requirements), start=1):
        repeat, source = timed_sequence_repeat(requirement)
        prefix = f"secuencia {index}"
        if source != PROVENANCE_EXPLICIT:
            reason = {SEQUENCE_REPEAT_ONCE: "la ultima etapa termina (duracion/condicion o 'todo apagado'): una sola ejecucion",
                      SEQUENCE_REPEAT_HOLD: "la ultima etapa no tiene fin: se mantiene hasta Stop"}.get(repeat, "")
            inferences.append({"field": f"{prefix}.repeat", "value": repeat, "provenance": source, "reason": reason})
        if timed_sequence_start_mode(requirement) == "auto":
            inferences.append({"field": f"{prefix}.trigger", "value": "AUTO", "provenance": PROVENANCE_INFERRED,
                               "reason": "ciclo continuo sin disparador: arranca solo, sin flanco de pulsador"})
        if repeat != SEQUENCE_REPEAT_HOLD:
            inferences.append({"field": f"{prefix}.final_state", "value": "ALL_OFF", "provenance": PROVENANCE_DEFAULT,
                               "reason": "al terminar o al detenerse, todas las salidas de la secuencia quedan apagadas"})
    return inferences


# Recursos de un requisito que NO son fijos sino que vienen de un PARAMETRO EFECTIVO del intent:
# type -> {parametro: tag por defecto del contrato}. El tag por defecto es el MISMO que usa la plantilla
# del generador cuando el parametro falta (code_generator: _param(parameters, key, default=...)), asi que
# requisito, IR, generador y verificador resuelven el recurso igual. enable_pid: el interlock de seguridad
# incidental "PID_Enable := NOT <emergency_input> AND ..." usa la emergencia del intent; en un banco sin
# I_Emergency la semantica efectiva la deja en el literal seguro FALSE y no hay recurso fisico que exigir.
# Requisitos cuya ESENCIA es la emergencia (emergency_priority) siguen con su tag fijo.
FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS: dict[str, dict[str, str]] = {
    "enable_pid": {"emergency_input": "I_Emergency"},
    "enable_pump": {"pump_output": "Q_Pump_Enable"},
    "manual_pump_enable": {"manual_pump_input": "I_Manual_Pump_Command", "pump_output": "Q_Pump_Enable"},
}

# Literales booleanos seguros (mismo criterio que effective_semantics.SAFE_FALSE / semantic_repair).
SAFE_BOOL_LITERALS = ("FALSE", "TRUE")
_PARAMETER_TAG_PATTERN = re.compile(r"^(I|Q|M|T|C|R|F|AI|AO)_[A-Za-z0-9_]+$")

RESOURCE_TAG = "TAG"                        # el parametro efectivo es un tag PLC: se exige ese tag
RESOURCE_SAFE_LITERAL = "SAFE_LITERAL"      # literal TRUE/FALSE: ninguna variable PLC que exigir
RESOURCE_CONTRACT_DEFAULT = "CONTRACT_DEFAULT"  # parametro ausente: el tag por defecto del contrato
ERROR_INVALID_PARAMETER_RESOURCE = "FUNCTIONAL_REQUIREMENT_INVALID_PARAMETER_RESOURCE"


class ParameterResourceError(ValueError):
    """Un recurso de requisito dependiente de parametro tiene un valor que no es tag PLC ni literal seguro."""

    def __init__(self, requirement_type: str, parameter: str, value: Any) -> None:
        super().__init__(
            f"{ERROR_INVALID_PARAMETER_RESOURCE}: el requisito '{requirement_type}' toma su recurso del parametro "
            f"'{parameter}', cuyo valor {value!r} no es un tag PLC valido ni un literal seguro TRUE/FALSE."
        )
        self.code = ERROR_INVALID_PARAMETER_RESOURCE
        self.requirement_type = requirement_type
        self.parameter = parameter
        self.value = value


def resolve_parameter_resources(requirement: dict[str, Any], parameters: dict[str, Any] | None = None,
                                provenance: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Resolucion trazable de los recursos dependientes de parametros de UN requisito:
    [{parameter, contract_default, value, resolution: TAG | SAFE_LITERAL | CONTRACT_DEFAULT, tag, provenance}].
    Nunca convierte un literal en tag ni inventa recursos; un valor invalido lanza ParameterResourceError.
    parameters=None (llamadas sin semantica efectiva) conserva el comportamiento del contrato.
    """
    req_type = canonical_requirement_type(requirement.get("type", ""))
    resolved: list[dict[str, Any]] = []
    for parameter, default in (FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS.get(req_type) or {}).items():
        entry: dict[str, Any] = {"parameter": parameter, "contract_default": default,
                                 "provenance": (provenance or {}).get(parameter)}
        if parameters is None or parameter not in parameters or parameters.get(parameter) in (None, ""):
            entry.update({"value": None, "resolution": RESOURCE_CONTRACT_DEFAULT, "tag": default})
        else:
            value = str(parameters[parameter]).strip()
            if value.upper() in SAFE_BOOL_LITERALS:
                entry.update({"value": value.upper(), "resolution": RESOURCE_SAFE_LITERAL, "tag": None})
            elif _PARAMETER_TAG_PATTERN.match(value):
                entry.update({"value": value, "resolution": RESOURCE_TAG, "tag": value})
            else:
                raise ParameterResourceError(req_type, parameter, parameters[parameter])
        resolved.append(entry)
    return resolved


def get_functional_requirement_tags(requirement: dict[str, Any], parameters: dict[str, Any] | None = None,
                                    provenance: dict[str, Any] | None = None) -> list[str]:
    """
    Resolve the concrete PLC tags one functional_requirement entry implies. Tags que dependen de un
    parametro (FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS) se resuelven con los parametros EFECTIVOS: un literal
    seguro no exige variable PLC; otro tag valido sustituye al por defecto; sin parametros, el contrato.
    """
    req_type = canonical_requirement_type(requirement.get("type", ""))
    if (parameters or {}).get('_mode_selection_only') is True and req_type in {'automatic_mode', 'manual_mode'}:
        memory = ('auto_mode_memory', 'M_AutoMode') if req_type == 'automatic_mode' else ('manual_mode_memory', 'M_ManualMode')
        return [parameters['auto_input'], parameters.get(memory[0]) or memory[1]]
    if req_type in {'automatic_mode', 'manual_mode'} and requirement.get('mode_input'):
        memory = AUTO_MODE_MEMORY if req_type == 'automatic_mode' else MANUAL_MODE_MEMORY
        return [str(requirement['mode_input']).strip(), memory]
    if req_type == 'force_off':
        return list(dict.fromkeys([*_condition_tags(requirement.get('condition', '')),
                                   *_output_list(requirement)]))
    if req_type in FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS:
        parameter_defaults = set(FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS[req_type].values())
        fixed = [tag for tag in FUNCTIONAL_REQUIREMENT_TAGS.get(req_type, []) if tag not in parameter_defaults]
        resolved = [entry["tag"] for entry in resolve_parameter_resources(requirement, parameters, provenance) if entry["tag"]]
        return list(dict.fromkeys(fixed + resolved))
    if req_type == "timed_sequence":
        tags = [str(requirement.get(key, "")).strip() for key in ("start_input", "stop_input", "reset_input")]
        tags.extend(_condition_tags(timed_sequence_enable_condition(requirement)))
        for step in timed_sequence_steps(requirement):
            tags.extend(sequence_step_outputs(step))
            tags.extend(_condition_tags(step["advance_on"] or ""))
            tags.append(step["timeout_alarm_output"] or "")
        index = int(requirement.get("_sequence_index", 1) or 1)
        for names in timed_sequence_internal_names(index, requirement):
            tags.extend([names["step"], names["timer"]])
        tags.extend(timed_sequence_aux_names(index, requirement).values())
        return [tag for tag in dict.fromkeys(tags) if tag and tag not in ("FALSE", "TRUE")]
    if req_type == "never_together":
        return [str(o).strip() for o in (requirement.get("outputs") or []) if isinstance(o, str) and str(o).strip()]
    if req_type == "analog_output":
        return [str(requirement.get("output", "")).strip(), *_condition_tags(requirement.get("condition", ""))]
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
    req_type = canonical_requirement_type(requirement.get("type", ""))
    names = list(FUNCTIONAL_REQUIREMENT_PROCESS_VARIABLES.get(req_type, []))
    # Generic comparators/latches can also refer to the existing supervisory
    # contract. Declare those members just as the dedicated PID primitives do;
    # otherwise SCL contains an undeclared measurement despite valid semantics.
    from functional_resources import resolve_functional_resources
    referenced=resolve_functional_resources([requirement]).get('referenced_tags',[])
    names += [name for name in referenced if name in PID_PROCESS_VARIABLES and name not in names]
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
    req_type = canonical_requirement_type(requirement.get("type", ""))
    return req_type in FUNCTIONAL_REQUIREMENT_TAGS or req_type == "interlock"


IEC_DATA_TYPES = {"BOOL", "BYTE", "WORD", "DWORD", "LWORD", "SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT",
                  "ULINT", "REAL", "LREAL", "TIME", "STRING", "WSTRING"}
CLASS_CATALOG = "catalog"
CLASS_VARIABLE = "variable"
CLASS_UNSUPPORTED = "unsupported"


def classify_functional_requirement(requirement: dict[str, Any]) -> str:
    """
    Tres clases (antes eran dos y "todo lo que no es catalogo" se trataba como variable ad-hoc):
      catalog     primitiva/comportamiento del catalogo ({"type": "timed_sequence", ...});
      variable    variable funcional con nombre propio ({"name": "Level_SP", "type": "REAL"});
      unsupported comportamiento desconocido: no es una variable y no se puede generar.
    """
    if is_catalog_functional_requirement(requirement):
        return CLASS_CATALOG
    if str(requirement.get("name") or "").strip() or str(requirement.get("type") or "").strip().upper() in IEC_DATA_TYPES:
        return CLASS_VARIABLE
    return CLASS_UNSUPPORTED


# ---------------------------------------------------------------------------------------------
# Composicion funcional (programa descrito por primitivas; ver code_generator._generate_composed_program)
# ---------------------------------------------------------------------------------------------

# Tipos que el compositor sabe renderizar dentro de un programa compuesto. Cualquier otro tipo de
# catalogo presente en la composicion se rechaza explicitamente (nunca se descarta en silencio).
COMPOSABLE_TYPES = {"timed_sequence", "never_together", "automatic_mode", "manual_mode", "sensor_timeout_alarm",
                    "alarm_output", "reset_behavior", "emergency_priority", "conditional_output", "hysteresis_switch",
                    "force_off", "latch", "pulse_counter", "analog_output"}
MANUAL_BEHAVIORS = {"maintained", "latched"}
AUTO_MODE_MEMORY = "M_AutoMode"
MANUAL_MODE_MEMORY = "M_ManualMode"


def _requirements_of(functional_requirements: list[dict[str, Any]], req_type: str) -> list[dict[str, Any]]:
    return [r for r in functional_requirements or [] if isinstance(r, dict) and str(r.get("type", "")) == req_type]


def _text(value: Any) -> str:
    return str(value or "").strip()


def mode_inputs(functional_requirements: list[dict[str, Any]]) -> dict[str, str]:
    """{"auto": I_..., "manual": I_...} de automatic_mode/manual_mode presentes (mode_input o el tag del catalogo)."""
    inputs = {}
    for requirement in _requirements_of(functional_requirements, "automatic_mode")[:1]:
        inputs["auto"] = _text(requirement.get("mode_input")) or FUNCTIONAL_REQUIREMENT_TAGS["automatic_mode"][0]
    for requirement in _requirements_of(functional_requirements, "manual_mode")[:1]:
        inputs["manual"] = _text(requirement.get("mode_input")) or FUNCTIONAL_REQUIREMENT_TAGS["manual_mode"][0]
    return inputs


def manual_commands(functional_requirements: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Ordenes manuales independientes {input, output, behavior, enable_condition} de manual_mode.commands[]."""
    commands = []
    for requirement in _requirements_of(functional_requirements, "manual_mode"):
        for command in requirement.get("commands") or []:
            if isinstance(command, dict):
                commands.append({"input": _text(command.get("input")), "output": _text(command.get("output")),
                                 "behavior": _text(command.get("behavior")).lower() or "maintained",
                                 "enable_condition": _text(command.get("enable_condition"))})
    return commands


def manual_latch_memory(output: str) -> str:
    return f"M_{strip_external_prefix(output)}_ManualLatch"


def sensor_watchdogs(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    watchdogs = []
    for requirement in _requirements_of(functional_requirements, "sensor_timeout_alarm"):
        affected = requirement.get("affected_outputs") or []
        watchdogs.append({"sensor_input": _text(requirement.get("sensor_input")),
                          "timeout": _text(requirement.get("timeout")),
                          "start_condition": _text(requirement.get("start_condition")),
                          "affected_outputs": [_text(o) for o in affected if isinstance(o, str) and _text(o)],
                          "alarm_output": _text(requirement.get("alarm_output"))})
    return watchdogs


def watchdog_internal_names(index: int) -> dict[str, str]:
    """Memorias/temporizador deterministas por supervision: M_Wd<k>_* y T_Wd<k>."""
    return {key: f"M_Wd{index}_{key}" for key in ("Armed", "Prev", "Last", "Fault", "Recovered")} | {"Timer": f"T_Wd{index}"}


def reset_input(functional_requirements: list[dict[str, Any]]) -> str:
    for requirement in _requirements_of(functional_requirements, "reset_behavior"):
        return _text(requirement.get("reset_input")) or FUNCTIONAL_REQUIREMENT_TAGS["reset_behavior"][0]
    return ""


def alarm_outputs(functional_requirements: list[dict[str, Any]]) -> list[str]:
    alarms = [w["alarm_output"] for w in sensor_watchdogs(functional_requirements) if w["alarm_output"]]
    for requirement in _requirements_of(functional_requirements, "alarm_output"):
        alarms.append(_text(requirement.get("target")) or FUNCTIONAL_REQUIREMENT_TAGS["alarm_output"][0])
    return list(dict.fromkeys(alarms))


def _condition_tags(expression: str) -> list[str]:
    from functional_resources import condition_identifiers  # import diferido: evita ciclo de modulos
    return condition_identifiers(expression) or []


def _output_list(requirement: dict[str, Any], keys: tuple[str, ...] = ("outputs", "output", "target")) -> list[str]:
    for key in keys:
        value = requirement.get(key)
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list):
            return [str(o).strip() for o in value if isinstance(o, str) and str(o).strip()]
    return []


def conditional_outputs(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """{condition, outputs, duration}: sin duracion la salida sigue a la condicion; con duracion, pulso al cumplirse."""
    return [{"condition": _text(r.get("condition")), "outputs": _output_list(r),
             "duration": normalize_time_literal(r.get("duration"))}
            for r in _requirements_of(functional_requirements, "conditional_output")]


def conditional_output_names(index: int) -> dict[str, str]:
    return {"prev": f"M_Cond{index}_Prev", "active": f"M_Cond{index}_Active", "timer": f"T_Cond{index}"}


def _number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def hysteresis_switches(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    {input, output, on_above, off_below} o {input, output, on_below, off_above}: la salida se activa al
    cruzar un umbral y solo se desactiva al cruzar el otro (memoria interna), nunca una comparacion simple.
    """
    switches = []
    for requirement in _requirements_of(functional_requirements, "hysteresis_switch"):
        switches.append({"input": _text(requirement.get("input") or requirement.get("analog_input")),
                         "output": (_output_list(requirement, ("output", "outputs", "target")) or [""])[0],
                         **{key: _number(requirement.get(key)) for key in ("on_above", "off_below", "on_below", "off_above")},
                         **{key: requirement[key] for key in ('enable_condition', 'on_value', 'off_value', 'output_unit') if key in requirement}})
    return switches


def hysteresis_memory(index: int) -> str:
    return f"M_Hyst{index}"


def latches(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """{set, reset, outputs}: la salida se enclava al cumplirse `set` y se libera con `reset` (prioritario)."""
    return [{"set": _text(r.get("set") or r.get("set_condition")), "reset": _text(r.get("reset") or r.get("reset_condition")),
             "outputs": _output_list(r)} for r in _requirements_of(functional_requirements, "latch")]


def counter_output_names(counter_tag: str) -> dict[str, str]:
    """
    Salidas EXPLICITAS de una instancia CTU ("C_PulseCount" -> M_PulseCount_Done / M_PulseCount_CV). El programa usa
    estos simbolos, nunca miembros de la instancia: en TIA V18 un CTU_INT no tiene ".Q" (su salida se llama QU) y en
    IEC si; la llamada "CTU(..., Q => done, CV => valor)" es la unica forma valida en todas las plataformas.
    """
    base = strip_external_prefix(counter_tag)
    base = base[2:] if base.startswith("C_") else base
    return {"done": f"M_{base}_Done", "value": f"M_{base}_CV"}


def pulse_counters(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """{name, count, reset, preset, outputs}: cuenta flancos de `count` hasta `preset`; `reset` lo pone a cero."""
    counters = []
    for index, requirement in enumerate(_requirements_of(functional_requirements, "pulse_counter"), start=1):
        raw_name = re.sub(r"[^A-Za-z0-9_]", "_", _text(requirement.get("name"))).strip("_")
        name = raw_name if raw_name and raw_name[0].isalpha() else f"Count{index}"
        preset = requirement.get("preset")
        counters.append({"name": name, "instance": f"C_{name}", **counter_output_names(f"C_{name}"),
                         "count": _text(requirement.get("count_condition") or requirement.get("count_input")),
                         "reset": _text(requirement.get("reset") or requirement.get("reset_input")),
                         "preset": preset if isinstance(preset, int) and not isinstance(preset, bool) else _number(preset),
                         "outputs": _output_list(requirement)})
    return counters


def latch_memory(index: int) -> str:
    return f"M_Latch{index}"


def force_offs(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"condition": _text(r.get("condition")), "outputs": _output_list(r)}
            for r in _requirements_of(functional_requirements, "force_off")]


def composition_conflicts(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Contradicciones FUNCIONALES deterministas de un programa compuesto (nunca se adivina cual prevalece):
      * una etapa o una salida condicionada activa a la vez salidas declaradas never_together;
      * una histeresis cuyos umbrales se cruzan (se activaria y desactivaria con el mismo valor).
    """
    conflicts: list[dict[str, Any]] = []
    exclusive_sets = [set(_output_list(r)) for r in _requirements_of(functional_requirements, "never_together")]
    simultaneous: list[tuple[str, list[str]]] = []
    for index, requirement in enumerate(detect_timed_sequences(functional_requirements), start=1):
        for position, step in enumerate(timed_sequence_steps(requirement), start=1):
            simultaneous.append((f"la etapa {position} de la secuencia {index}", sequence_step_outputs(step)))
    for index, entry in enumerate(conditional_outputs(functional_requirements), start=1):
        simultaneous.append((f"la salida condicionada {index}", entry["outputs"]))
    for where, outputs in simultaneous:
        for exclusive in exclusive_sets:
            both = [o for o in outputs if o in exclusive]
            if len(both) >= 2:
                conflicts.append({"type": "never_together_violation", "outputs": both,
                                  "reason": f"{where} activa a la vez {', '.join(both)}, pero el comando exige que nunca "
                                            "esten activas simultaneamente."})
    for index, switch in enumerate(hysteresis_switches(functional_requirements), start=1):
        on_above, off_below = switch["on_above"], switch["off_below"]
        on_below, off_above = switch["on_below"], switch["off_above"]
        if on_above is not None and off_below is not None and off_below >= on_above:
            conflicts.append({"type": "hysteresis_inverted", "outputs": [switch["output"]],
                              "reason": f"la histeresis {index} se activa por encima de {on_above:g} pero se desactiva por "
                                        f"debajo de {off_below:g}: el umbral de apagado debe ser menor que el de encendido."})
        if on_below is not None and off_above is not None and off_above <= on_below:
            conflicts.append({"type": "hysteresis_inverted", "outputs": [switch["output"]],
                              "reason": f"la histeresis {index} se activa por debajo de {on_below:g} pero se desactiva por "
                                        f"encima de {off_above:g}: el umbral de apagado debe ser mayor que el de encendido."})
    return conflicts


def invalid_conditions(functional_requirements: list[dict[str, Any]]) -> list[str]:
    """Condiciones de un programa compuesto que no son expresiones de tags/comparaciones (texto libre)."""
    from functional_resources import condition_identifiers  # import diferido: evita ciclo de modulos

    found: list[str] = []
    for requirement in functional_requirements or []:
        if not isinstance(requirement, dict):
            continue
        texts = [_text(requirement.get(key)) for key in ("mode_condition", "run_condition", "condition", "set", "reset",
                                                        "count_condition")]
        if str(requirement.get("type", "")) == "timed_sequence":
            texts += [step["advance_on"] or "" for step in timed_sequence_steps(requirement)]
        found += [text for text in texts if text and condition_identifiers(text) is None]
    return found


def composition_missing_data(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Datos indispensables de las primitivas no secuenciales (condicion, salidas, umbrales)."""
    missing: list[dict[str, Any]] = []
    for entry in conditional_outputs(functional_requirements):
        if not entry["condition"] or not entry["outputs"]:
            missing.append({"kind": "conditional_output", "outputs": entry["outputs"]})
        elif entry["duration"] and not _valid_time(entry["duration"]):
            missing.append({"kind": "duration", "step": None, "outputs": entry["outputs"], "invalid": entry["duration"]})
    for switch in hysteresis_switches(functional_requirements):
        complete = (switch["on_above"] is not None and switch["off_below"] is not None) or \
                   (switch["on_below"] is not None and switch["off_above"] is not None)
        if not switch["input"] or not switch["output"] or not complete:
            missing.append({"kind": "hysteresis", "outputs": [switch["output"]] if switch["output"] else []})
    for entry in force_offs(functional_requirements):
        if not entry["condition"] or not entry["outputs"]:
            missing.append({"kind": "force_off", "outputs": entry["outputs"]})
    for counter in pulse_counters(functional_requirements):
        preset = counter["preset"]
        if not counter["count"] or preset is None or float(preset) < 1 or float(preset) != int(preset):
            missing.append({"kind": "counter", "outputs": counter["outputs"]})
        elif not counter["reset"]:
            missing.append({"kind": "counter_reset", "outputs": counter["outputs"]})
    for entry in latches(functional_requirements):
        if not entry["set"] or not entry["outputs"]:
            missing.append({"kind": "conditional_output", "outputs": entry["outputs"]})
        elif not entry["reset"]:
            missing.append({"kind": "latch_reset", "outputs": entry["outputs"]})
    return missing


def composition_tags(functional_requirements: list[dict[str, Any]]) -> list[str]:
    """
    TODOS los tags (externos e internos) de un programa compuesto: secuencias, modos, ordenes
    manuales, permisivos, supervisiones de sensor, alarmas y reset. La IR los declara; el verificador
    rechaza cualquier identificador usado y no declarado.
    """
    tags: list[str] = []
    sequence_index = 0
    for requirement in functional_requirements or []:
        if not isinstance(requirement, dict):
            continue
        req_type = str(requirement.get("type", ""))
        if req_type == "timed_sequence":
            sequence_index += 1
            tags.extend(get_functional_requirement_tags({**requirement, "_sequence_index": sequence_index}))
        elif req_type == "never_together":
            tags.extend(get_functional_requirement_tags(requirement))
        elif req_type == "analog_output":
            tags.extend(get_functional_requirement_tags(requirement))
    for index, entry in enumerate(conditional_outputs(functional_requirements), start=1):
        tags.extend([*_condition_tags(entry["condition"]), *entry["outputs"]])
        if entry["duration"]:
            tags.extend(conditional_output_names(index).values())
    for index, switch in enumerate(hysteresis_switches(functional_requirements), start=1):
        tags.extend([switch["input"], switch["output"], hysteresis_memory(index),
                     *_condition_tags(switch.get('enable_condition', ''))])
    for entry in force_offs(functional_requirements):
        tags.extend([*_condition_tags(entry["condition"]), *entry["outputs"]])
    for index, entry in enumerate(latches(functional_requirements), start=1):
        tags.extend([*_condition_tags(entry["set"]), *_condition_tags(entry["reset"]), *entry["outputs"], latch_memory(index)])
    for counter in pulse_counters(functional_requirements):
        tags.extend([*_condition_tags(counter["count"]), *_condition_tags(counter["reset"]), *counter["outputs"],
                     counter["instance"], counter["done"], counter["value"]])
    modes = mode_inputs(functional_requirements)
    if "auto" in modes:
        tags.extend([modes["auto"], AUTO_MODE_MEMORY])
    if "manual" in modes:
        tags.extend([modes["manual"], MANUAL_MODE_MEMORY])
    for command in manual_commands(functional_requirements):
        tags.extend([command["input"], command["output"]])
        tags.extend(_condition_tags(command["enable_condition"]))
        if command["behavior"] == "latched":
            tags.append(manual_latch_memory(command["output"]))
    for index, watchdog in enumerate(sensor_watchdogs(functional_requirements), start=1):
        tags.extend([watchdog["sensor_input"], watchdog["alarm_output"], *watchdog["affected_outputs"]])
        tags.extend(_condition_tags(watchdog["start_condition"]))
        tags.extend(watchdog_internal_names(index).values())
    tags.append(reset_input(functional_requirements))
    tags.extend(alarm_outputs(functional_requirements))
    return [tag for tag in dict.fromkeys(tags) if tag and tag not in ("FALSE", "TRUE")]


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
    normalized = fold_text(command_text)
    is_pid_context = intent_id == "INT_PID_SUPERVISOR"
    detected_types = {
        req_type
        for req_type, keywords in FUNCTIONAL_REQUIREMENT_KEYWORDS.items()
        if (req_type in FUNCTIONAL_REQUIREMENT_PROCESS_VARIABLES) == is_pid_context
        and any(keyword in normalized for keyword in keywords)
    }
    explicit_types = {str(requirement.get("type", "")) for requirement in functional_requirements}
    if "never_together" in explicit_types:
        explicit_types.add("interlock")  # la invariante generica cubre "nunca al mismo tiempo"
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


def _detect_declared_incompatibilities(functional_requirements: list[dict[str, Any]],
                                       parameters: dict[str, Any] | None) -> list[dict[str, Any]]:
    present = {canonical_requirement_type(r.get("type")) for r in functional_requirements if isinstance(r, dict)}
    parameters = parameters if isinstance(parameters, dict) else {}
    conflicts: list[dict[str, Any]] = []
    for rule in FUNCTIONAL_REQUIREMENT_CONFLICTS:
        if not set(rule["types"]) <= present:
            continue
        if any(str(parameters.get(key) or "").strip() for key in rule.get("unless_parameters") or ()):
            continue
        conflicts.append({"type": "INCOMPATIBLE_REQUIREMENTS", "types": list(rule["types"]),
                          "entries": [r for r in functional_requirements
                                      if isinstance(r, dict) and canonical_requirement_type(r.get("type")) in rule["types"]],
                          "reason": rule["reason"]})
    return conflicts


def detect_functional_requirement_conflicts(functional_requirements: list[dict[str, Any]],
                                            parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Conflictos de UNA interpretacion: (1) pares de tipos declarados incompatibles en
    FUNCTIONAL_REQUIREMENT_CONFLICTS (con `parameters` como contexto: una entrada de seleccion puede
    hacerlos coherentes); (2) instancias del mismo tipo con parametros distintos (abajo).

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

    conflicts: list[dict[str, Any]] = _detect_declared_incompatibilities(functional_requirements, parameters)

    interlock_entries: list[dict[str, Any]] = []
    for req_type in list(by_type):
        if req_type in _INTERLOCK_TYPES:
            interlock_entries.extend(by_type.pop(req_type))
    if len(interlock_entries) >= 2:
        conflicts.extend(_detect_interlock_conflicts(interlock_entries))

    for req_type, entries in by_type.items():
        if len(entries) < 2 or req_type in MULTI_INSTANCE_TYPES:
            continue
        conflicts.extend(_detect_same_type_conflicts(req_type, entries))
    return conflicts


# Primitivas componibles cuyas instancias son independientes por definicion (cada una nombra sus propios
# recursos: dos secuencias, dos pares never_together, dos salidas condicionadas...). Varias instancias nunca
# son "el mismo requisito con parametros distintos"; sus contradicciones reales las detecta
# composition_conflicts. (Antes dos instancias con listas hacian fallar la comparacion con TypeError.)
MULTI_INSTANCE_TYPES = frozenset(COMPOSED_PROGRAM_TYPES) | {"never_together"}


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
    "FUNCTIONAL_REQUIREMENT_ALIASES",
    "FUNCTIONAL_REQUIREMENT_CONFLICTS",
    "canonical_requirement_type",
    "canonicalize_functional_requirements",
    "FUNCTIONAL_REQUIREMENT_TAGS",
    "FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS",
    "FUNCTIONAL_REQUIREMENT_KEYWORDS",
    "ParameterResourceError",
    "get_functional_requirement_tags",
    "resolve_parameter_resources",
    "is_catalog_functional_requirement",
    "compute_intent_covered_types",
    "compute_semantic_coverage",
    "detect_functional_requirement_conflicts",
    "detect_compositional_complexity",
    "normalize_interlock_requirement",
    "merge_interlock_requirements"
]
