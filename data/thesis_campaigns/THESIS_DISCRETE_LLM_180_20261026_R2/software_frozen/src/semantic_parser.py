from __future__ import annotations

import re
import unicodedata
from typing import Any


PHRASE_REPLACEMENTS = {
    "paro de emergencia": "emergency",
    "boton de emergencia": "emergency",
    "pulsador de emergencia": "emergency",
    "boton de arranque": "start",
    "boton de inicio": "start",
    "pulsador de arranque": "start",
    "pulsador de inicio": "start",
    "boton de encendido": "start",
    "pulsador de encendido": "start",
    "pulsante de encendido": "start",
    "boton de paro": "stop",
    "pulsador de paro": "stop",
    "pulsante de paro": "stop",
    "salida auxiliar": "aux_output",
    "piloto de marcha": "pilot_run",
    "piloto marcha": "pilot_run",
    "piloto de falla": "pilot_fault",
    "piloto falla": "pilot_fault",
    "contactor a": "contactor_a",
    "contactor b": "contactor_b",
    "modo manual": "manual_mode",
    "modo automatico": "auto_mode",
    "al mismo tiempo": "same_time",
    "apagado retardado": "stop_delay",
    "retardo de paro": "stop_delay",
    "retardo al paro": "stop_delay",
    "despues de presionar el stop": "after_stop",
    "despues de presionar stop": "after_stop",
    "despues de stop": "after_stop",
    "luego de stop": "after_stop",
    "tras stop": "after_stop",
    "no responde": "no_response",
    "no cambia": "no_change"
}

SYNONYM_REPLACEMENTS = {
    "prende": "enciende",
    "prender": "enciende",
    "activa": "enciende",
    "activar": "enciende",
    "habilita": "enciende",
    "habilitar": "enciende",
    "apaga": "stop",
    "apagar": "stop",
    "parar": "stop",
    "detiene": "stop",
    "detener": "stop",
    "detenga": "stop",
    "detienes": "stop",
    "deten": "stop",
    "inicio": "start",
    "marcha": "start",
    "arranque": "start",
    "arranca": "start",
    "arrancar": "start",
    "paro": "stop",
    "parada": "stop",
    "emergencia": "emergency",
    "pulsador": "input",
    "boton": "input",
    "pulsante": "input",
    "reinicio": "reset",
    "reiniciar": "reset",
    "resetea": "reset",
    "resetear": "reset",
    "manual": "manual",
    "automatico": "auto",
    "automatica": "auto",
    "mantenimiento": "maintenance",
    "lampara": "salida",
    "variador": "motor",
    "sirena": "alarma",
    "sensor uno": "sensor",
    "sensor 1": "sensor"
}

NUMBER_WORDS = {
    "un": "1",
    "uno": "1",
    "una": "1",
    "dos": "2",
    "tres": "3",
    "cuatro": "4",
    "cinco": "5",
    "seis": "6",
    "siete": "7",
    "ocho": "8",
    "nueve": "9",
    "diez": "10"
}

TIME_PATTERNS = (
    (re.compile(r"\b(\d+)\s*(segundos?|seg|s)\b"), "s"),
    (re.compile(r"\b(\d+)\s*(minutos?|min|m)\b"), "m")
)
TIME_SEQUENCE_PATTERN = re.compile(r"\b(\d+)\s*(segundos?|seg|s|minutos?|min|m)\b")

EXACT_TAG_ALIASES = {
    "i_start": ("start", "I_Start"),
    "i_stop": ("stop", "I_Stop"),
    "i_emergency": ("emergency", "I_Emergency"),
    "i_reset": ("reset", "I_Reset"),
    "i_sensor1": ("sensor", "I_Sensor1"),
    "i_mode_manual": ("manual", "I_Mode_Manual"),
    "i_mode_auto": ("auto", "I_Mode_Auto"),
    "i_maintenance": ("maintenance", "I_Maintenance"),
    "q_motor_enable": ("motor", "Q_Motor_Enable"),
    "q_alarm": ("alarm", "Q_Alarm"),
    "q_pilot_run": ("pilot_run", "Q_Pilot_Run"),
    "q_pilot_fault": ("pilot_fault", "Q_Pilot_Fault"),
    "q_aux_output": ("output", "Q_Aux_Output"),
    "q_contactor_a": ("contactor_a", "Q_Contactor_A"),
    "q_contactor_b": ("contactor_b", "Q_Contactor_B"),
    "m_runlatch": ("run_latch", "M_RunLatch"),
    "m_faultlatch": ("fault_latch", "M_FaultLatch"),
    "m_automode": ("auto_mode_memory", "M_AutoMode"),
    "m_manualmode": ("manual_mode_memory", "M_ManualMode"),
    "m_step": ("step_memory", "M_Step"),
    "m_stopdelayactive": ("stop_delay_active", "M_StopDelayActive"),
    "m_sensorlaststate": ("last_state_memory", "M_SensorLastState"),
    "t_pulse5s": ("timer", "T_Pulse5s"),
    "t_delaystart": ("timer", "T_DelayStart"),
    "t_operationlimit": ("timer", "T_OperationLimit"),
    "t_sensortimeout": ("timer", "T_SensorTimeout"),
    "t_stopdelay": ("timer", "T_StopDelay"),
    "c_pulsecount": ("counter", "C_PulseCount"),
    "r_sensorpulse": ("edge_detector", "R_SensorPulse"),
}

TAG_TO_SLOT = {tag_name: slot_name for slot_name, tag_name in EXACT_TAG_ALIASES.values()}

KNOWN_CONTEXT_TOKENS = {
    "activa",
    "enciende",
    "haz",
    "programa",
    "genera",
    "cuenta",
    "con",
    "cuando",
    "si",
    "que",
    "el",
    "la",
    "los",
    "las",
    "debe",
    "de",
    "despues",
    "luego",
    "tras",
    "por",
    "durante",
    "presione",
    "presionar",
    "use",
    "usar",
    "implementa",
    "quiere",
    "quiero",
    "todo",
    "toda",
    "mismo",
    "tiempo",
    "al",
    "del",
    "un",
    "una",
    "segundos",
    "segundo",
    "minuto",
    "minutos",
    "motor",
    "sensor",
    "salida",
    "alarma",
    "start",
    "stop",
    "emergency",
    "reset",
    "manual",
    "auto",
    "maintenance",
    "contador",
    "pulsos",
    "pulso",
    "retardo",
    "pasos",
    "paso",
    "ciclo",
    "bucle",
    "ciclico",
    "ciclica",
    "intermitente",
    "alternar",
    "alterna",
    "repetir",
    "repite",
    "encendido",
    "apagado",
    "estado",
    "estados",
    "falla",
    "same_time",
    "stop_delay",
    "after_stop",
    "input",
    "aux_output",
    "pilot_run",
    "pilot_fault",
    "contactor_a",
    "contactor_b",
    "manual_mode",
    "auto_mode",
    "no_response",
    "no_change"
}

VAGUE_REFERENCES = {"eso", "esa", "ese", "algo", "cosa"}
EXPLICIT_TAG_PATTERN = re.compile(r"\b[IQMTCFR]_[A-Za-z0-9_]+\b", re.IGNORECASE)


def _contains_any(text: str, terms: tuple[str, ...] | list[str] | set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms)


def _replace_number_words_in_context(text: str) -> str:
    normalized = text
    ordered_numbers = sorted(NUMBER_WORDS.items(), key=lambda item: len(item[0]), reverse=True)
    for source, target in ordered_numbers:
        normalized = re.sub(
            rf"\b{re.escape(source)}\b(?=\s*(segundos?|seg|s|minutos?|min|m|pulsos?|pasos?))",
            target,
            normalized
        )
        normalized = re.sub(
            rf"\b{re.escape(source)}\b(?=\s*veces\b)",
            target,
            normalized
        )
    return normalized


def normalize_text(text: str) -> str:
    """Normalize command text so intent detection depends on meaning, not exact wording."""
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9_\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    for source, target in sorted(PHRASE_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)

    for source, target in sorted(SYNONYM_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)

    for source, target in sorted(PHRASE_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)

    normalized = _replace_number_words_in_context(normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_time(text: str) -> str | None:
    """Extract an IEC 61131-3 TIME literal such as T#5s or T#2m."""
    normalized = normalize_text(text)
    for pattern, unit in TIME_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return f"T#{int(match.group(1))}{unit}"
    return None


def _extract_times(text: str) -> list[str]:
    """Extract every IEC TIME literal while preserving its textual order."""
    normalized = normalize_text(text)
    values: list[str] = []
    for match in TIME_SEQUENCE_PATTERN.finditer(normalized):
        unit_text = match.group(2)
        unit = "m" if unit_text.startswith("m") else "s"
        values.append(f"T#{int(match.group(1))}{unit}")
    return values


def extract_tags(text: str, alias_index: dict[str, str] | None = None) -> dict[str, str]:
    """Map user terminology to authorized PLC tags."""
    normalized = normalize_text(text)
    tags: dict[str, str] = {}

    for explicit_tag in EXPLICIT_TAG_PATTERN.findall(text):
        alias = EXACT_TAG_ALIASES.get(explicit_tag.lower())
        if alias is not None:
            semantic_name, tag_name = alias
            tags[semantic_name] = tag_name

    if alias_index:
        for alias_phrase in sorted(alias_index, key=len, reverse=True):
            if alias_phrase and re.search(rf"\b{re.escape(alias_phrase)}\b", normalized):
                canonical_tag = alias_index[alias_phrase]
                slot_name = TAG_TO_SLOT.get(canonical_tag)
                if slot_name:
                    tags[slot_name] = canonical_tag

    # setdefault, no asignacion directa: si `alias_index` (arriba) ya resolvio este slot contra un
    # tag REAL del mapa activo (p. ej. una variable LOCKED con un nombre distinto de la convencion
    # pero con "arranque"/"start" en sus aliases), esa resolucion dinamica tiene prioridad sobre
    # este valor de convencion fijo - "reutilizacion semantica de variables LOCKED": no debe
    # sobrescribirse silenciosamente un match real solo porque coincide con el nombre por defecto.
    if _contains_any(normalized, ("start",)):
        tags.setdefault("start", "I_Start")
    if _contains_any(normalized, ("stop", "after_stop", "stop_delay")):
        tags.setdefault("stop", "I_Stop")
    if _contains_any(normalized, ("emergency",)):
        tags.setdefault("emergency", "I_Emergency")
    if _contains_any(normalized, ("reset",)):
        tags.setdefault("reset", "I_Reset")
    if _contains_any(normalized, ("sensor",)):
        tags.setdefault("sensor", "I_Sensor1")
    if _contains_any(normalized, ("manual", "manual_mode")):
        tags.setdefault("manual", "I_Mode_Manual")
    if _contains_any(normalized, ("auto", "auto_mode")):
        tags.setdefault("auto", "I_Mode_Auto")
    if _contains_any(normalized, ("maintenance",)):
        tags.setdefault("maintenance", "I_Maintenance")
    if _contains_any(normalized, ("motor",)):
        tags.setdefault("motor", "Q_Motor_Enable")
    if _contains_any(normalized, ("alarma",)):
        tags.setdefault("alarm", "Q_Alarm")
    if _contains_any(normalized, ("pilot_run",)):
        tags.setdefault("pilot_run", "Q_Pilot_Run")
    if _contains_any(normalized, ("pilot_fault",)):
        tags.setdefault("pilot_fault", "Q_Pilot_Fault")
    if _contains_any(normalized, ("aux_output", "salida")):
        tags.setdefault("output", "Q_Aux_Output")
    if _contains_any(normalized, ("contactor_a",)):
        tags.setdefault("contactor_a", "Q_Contactor_A")
    if _contains_any(normalized, ("contactor_b",)):
        tags.setdefault("contactor_b", "Q_Contactor_B")
    return tags


def _extract_pulse_count(text: str) -> int | None:
    normalized = normalize_text(text)
    match = re.search(r"\b(\d+)\s*pulsos?\b", normalized)
    if match:
        return int(match.group(1))
    return None


def detect_intent(normalized_text: str, tags: dict[str, str], time_value: str | None) -> tuple[str, float]:
    """Detect the most likely intent using semantic rules."""
    has_start = "start" in tags
    has_stop = "stop" in tags
    has_emergency = "emergency" in tags
    has_reset = "reset" in tags
    has_sensor = "sensor" in tags
    has_manual = "manual" in tags
    has_auto = "auto" in tags
    has_maintenance = "maintenance" in tags
    has_motor = "motor" in tags or _contains_any(normalized_text, ("motor",))
    has_alarm = "alarm" in tags
    has_output = "output" in tags
    has_pilots = "pilot_run" in tags or "pilot_fault" in tags
    has_time = time_value is not None

    mentions_pulse_word = _contains_any(normalized_text, ("pulso", "pulsos"))
    mentions_counter_words = _contains_any(normalized_text, ("contador", "cuenta", "contar"))
    mentions_sequence = _contains_any(normalized_text, ("secuencia", "paso", "pasos"))
    mentions_cycle = _contains_any(normalized_text, ("ciclo", "estados", "estado"))
    mentions_loop = _contains_any(
        normalized_text,
        ("bucle", "ciclico", "ciclica", "intermitente", "alternar", "alterna", "repetir", "repite")
    )
    mentions_timeout = _contains_any(normalized_text, ("no_response", "no_change", "timeout"))
    mentions_same_time = _contains_any(normalized_text, ("same_time", "ambos", "simultaneo", "simultaneamente"))
    mentions_interlock = _contains_any(normalized_text, ("interlock", "enclavamiento"))
    mentions_delay = _contains_any(normalized_text, ("retardo", "despues", "luego", "tras"))
    mentions_stop_delay = _contains_any(normalized_text, ("stop_delay", "after_stop")) or bool(
        re.search(r"\bstop\b.*\bdespues\b", normalized_text) or re.search(r"\bcuando\b.*\bstop\b", normalized_text)
    )
    mentions_operation = _contains_any(normalized_text, ("operacion", "automaticamente", "tiempo"))
    mentions_everything = _contains_any(normalized_text, ("todo", "toda"))
    mentions_fault = _contains_any(normalized_text, ("falla", "fault"))

    if has_motor and has_stop and has_time and mentions_stop_delay:
        return "INT_DELAYED_STOP", 0.97

    if has_motor and has_start and has_stop and has_time and mentions_loop:
        return "INT_CYCLIC_MOTOR", 0.98

    if (_contains_any(normalized_text, ("contactor", "contactores")) and (mentions_same_time or mentions_interlock)) or (
        "contactor_a" in tags and "contactor_b" in tags
    ):
        return "INT_MUTUAL_INTERLOCK", 0.94

    if has_reset and _contains_any(normalized_text, ("contador", "cero", "reinicio")):
        return "INT_COUNTER_RESET", 0.93

    if has_sensor and mentions_timeout and (has_alarm or has_time):
        return "INT_SENSOR_TIMEOUT_ALARM", 0.92

    if (
        (has_sensor and (mentions_counter_words or mentions_pulse_word))
        or (mentions_counter_words and mentions_pulse_word)
        or (mentions_pulse_word and not has_time and (has_alarm or has_output))
    ):
        return "INT_COUNTER_PULSES", 0.96

    if has_maintenance and (has_motor or has_start or has_stop):
        return "INT_MAINTENANCE_BLOCK", 0.92

    if has_manual and has_auto:
        return "INT_MANUAL_AUTO_MODE", 0.93

    if has_pilots:
        return "INT_STATUS_PILOTS", 0.91

    if mentions_sequence and re.search(r"\b(3\s*pasos?|paso\s+[123])\b", normalized_text):
        return "INT_SEQUENCE_THREE_STEPS", 0.9

    if has_auto and (mentions_cycle or mentions_sequence):
        return "INT_AUTO_CYCLE", 0.89

    if has_motor and (has_alarm or mentions_fault) and _contains_any(normalized_text, ("solo", "mientras", "exista", "sin", "bloquea")):
        return "INT_VFD_ENABLE_NO_ALARM", 0.88

    if has_alarm and (has_start or has_motor) and _contains_any(normalized_text, ("seguridad", "seguro", "bloquea")):
        return "INT_SAFE_START_ALARM", 0.87

    if has_emergency and (has_motor or has_output or has_alarm or mentions_everything):
        return "INT_EMERGENCY_PRIORITY", 0.98

    if has_motor and _contains_any(normalized_text, ("memoria", "memorizado", "enclavamiento", "latch", "queda")):
        return "INT_MOTOR_LATCH", 0.92

    if has_motor and has_time and has_stop and mentions_operation:
        return "INT_AUTO_STOP_TIMER", 0.9

    if has_motor and has_time and (mentions_delay or has_start):
        return "INT_DELAYED_START", 0.95

    if has_motor and has_start and has_stop:
        return "INT_MOTOR_START_STOP", 0.97

    if has_time and (has_output or _contains_any(normalized_text, ("pulso", "genera"))):
        return "INT_TIMED_PULSE", 0.93

    if (has_output or has_alarm) and (has_start or has_sensor):
        return "INT_DIRECT_OUTPUT", 0.82

    return "INT_UNKNOWN", 0.0


def _extract_parameter_tag_values(parameters: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in parameters.values():
        if isinstance(value, str) and re.match(r"^[IQMTCFR]_[A-Za-z0-9_]+$", value):
            values.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and re.match(r"^[IQMTCFR]_[A-Za-z0-9_]+$", item):
                    values.append(item)
    return values


def _build_timed_pulse_parameters(tags: dict[str, str], time_value: str | None) -> dict[str, Any]:
    return {
        "trigger_input": tags.get("start", "I_Start"),
        "emergency_input": tags.get("emergency", "I_Emergency"),
        "output": tags.get("output", "Q_Aux_Output"),
        "duration": time_value or "T#5s",
        "timer": "T_Pulse5s"
    }


def _build_motor_start_stop_parameters(tags: dict[str, str]) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "trigger_input": tags.get("start", "I_Start"),
        "stop_input": tags.get("stop", "I_Stop"),
        "emergency_input": tags.get("emergency", "I_Emergency"),
        "motor_output": tags.get("motor", "Q_Motor_Enable"),
        "run_latch": "M_RunLatch",
        "fault_latch": "M_FaultLatch"
    }
    # reset/alarm/pilotos son funciones OPCIONALES de este intent (ir_builder.
    # OPTIONAL_PARAMETER_KEYS): solo se agregan si el comando realmente las menciono (extract_tags
    # ya solo llena "reset"/"alarm"/"pilot_run"/"pilot_fault" cuando el texto las contiene) - nunca
    # como relleno automatico con el tag fisico historico ("I_Reset", "Q_Alarm", ...), que el banco
    # activo podria no tener.
    for tag_key, param_key in (
        ("reset", "reset_input"), ("alarm", "alarm_output"),
        ("pilot_run", "run_indicator"), ("pilot_fault", "fault_indicator")
    ):
        if tag_key in tags:
            parameters[param_key] = tags[tag_key]
    return parameters


def _build_delayed_start_parameters(tags: dict[str, str], time_value: str | None) -> dict[str, Any]:
    return {
        "trigger_input": tags.get("start", "I_Start"),
        "stop_input": tags.get("stop", "I_Stop"),
        "emergency_input": tags.get("emergency", "I_Emergency"),
        "motor_output": tags.get("motor", "Q_Motor_Enable"),
        "delay_time": time_value or "T#3s",
        "timer": "T_DelayStart"
    }


def _build_delayed_stop_parameters(tags: dict[str, str], time_value: str | None) -> dict[str, Any]:
    return {
        "trigger_input": tags.get("start", "I_Start"),
        "stop_input": tags.get("stop", "I_Stop"),
        "emergency_input": tags.get("emergency", "I_Emergency"),
        "motor_output": tags.get("motor", "Q_Motor_Enable"),
        "run_latch": "M_RunLatch",
        "stop_delay_active": "M_StopDelayActive",
        "stop_delay_time": time_value or "T#10s",
        "timer": "T_StopDelay"
    }


def _build_emergency_priority_parameters(tags: dict[str, str]) -> dict[str, Any]:
    return {
        "emergency_input": tags.get("emergency", "I_Emergency"),
        "affected_outputs": [tags.get("motor", "Q_Motor_Enable"), tags.get("output", "Q_Aux_Output")],
        "alarm_output": tags.get("alarm", "Q_Alarm")
    }


def _build_counter_pulses_parameters(tags: dict[str, str], pulse_count: int | None) -> dict[str, Any]:
    return {
        "pulse_input": tags.get("sensor", "I_Sensor1"),
        "reset_input": tags.get("reset", "I_Reset"),
        "emergency_input": tags.get("emergency", "I_Emergency"),
        "output": tags.get("alarm", "Q_Alarm"),
        "counter": "C_PulseCount",
        "edge_detector": "R_SensorPulse",
        "preset": pulse_count or 5
    }


def _build_cyclic_motor_parameters(tags: dict[str, str], time_values: list[str]) -> dict[str, Any]:
    on_time = time_values[0] if time_values else "T#3s"
    off_time = time_values[1] if len(time_values) > 1 else on_time
    return {
        "trigger_input": tags.get("start", "I_Start"),
        "stop_input": tags.get("stop", "I_Stop"),
        "emergency_input": tags.get("emergency", "I_Emergency"),
        "motor_output": tags.get("motor", "Q_Motor_Enable"),
        "run_latch": "M_RunLatch",
        "step_memory": "M_Step",
        "start_edge": "R_CycleStart",
        "on_timer": "T_CycleOn",
        "off_timer": "T_CycleOff",
        "on_time": on_time,
        "off_time": off_time
    }


def _build_parameters(
    intent_id: str,
    tags: dict[str, str],
    time_value: str | None,
    pulse_count: int | None,
    time_values: list[str]
) -> dict[str, Any]:
    if intent_id == "INT_TIMED_PULSE":
        return _build_timed_pulse_parameters(tags, time_value)
    if intent_id == "INT_MOTOR_START_STOP":
        return _build_motor_start_stop_parameters(tags)
    if intent_id == "INT_DELAYED_START":
        return _build_delayed_start_parameters(tags, time_value)
    if intent_id == "INT_DELAYED_STOP":
        return _build_delayed_stop_parameters(tags, time_value)
    if intent_id == "INT_EMERGENCY_PRIORITY":
        return _build_emergency_priority_parameters(tags)
    if intent_id == "INT_COUNTER_PULSES":
        return _build_counter_pulses_parameters(tags, pulse_count)
    if intent_id == "INT_CYCLIC_MOTOR":
        return _build_cyclic_motor_parameters(tags, time_values)
    if intent_id == "INT_COUNTER_RESET":
        return {
            "reset_input": tags.get("reset", "I_Reset"),
            "counter": "C_PulseCount"
        }
    if intent_id == "INT_MUTUAL_INTERLOCK":
        return {
            "trigger_input": tags.get("start", "I_Start"),
            "stop_input": tags.get("stop", "I_Stop"),
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "contactor_a": tags.get("contactor_a", "Q_Contactor_A"),
            "contactor_b": tags.get("contactor_b", "Q_Contactor_B")
        }
    if intent_id == "INT_MANUAL_AUTO_MODE":
        return {
            "manual_input": tags.get("manual", "I_Mode_Manual"),
            "auto_input": tags.get("auto", "I_Mode_Auto"),
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "trigger_input": tags.get("start", "I_Start"),
            "stop_input": tags.get("stop", "I_Stop"),
            "motor_output": tags.get("motor", "Q_Motor_Enable"),
            "manual_mode_memory": "M_ManualMode",
            "auto_mode_memory": "M_AutoMode"
        }
    if intent_id == "INT_STATUS_PILOTS":
        return {
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "motor_output": tags.get("motor", "Q_Motor_Enable"),
            "alarm_output": tags.get("alarm", "Q_Alarm"),
            "run_indicator": tags.get("pilot_run", "Q_Pilot_Run"),
            "fault_indicator": tags.get("pilot_fault", "Q_Pilot_Fault")
        }
    if intent_id == "INT_MAINTENANCE_BLOCK":
        return {
            "maintenance_input": tags.get("maintenance", "I_Maintenance"),
            "trigger_input": tags.get("start", "I_Start"),
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "motor_output": tags.get("motor", "Q_Motor_Enable")
        }
    if intent_id == "INT_DIRECT_OUTPUT":
        return {
            "trigger_input": tags.get("sensor", tags.get("start", "I_Start")),
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "output": tags.get("output", "Q_Aux_Output")
        }
    if intent_id == "INT_MOTOR_LATCH":
        return {
            "trigger_input": tags.get("start", "I_Start"),
            "stop_input": tags.get("stop", "I_Stop"),
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "motor_output": tags.get("motor", "Q_Motor_Enable"),
            "run_latch": "M_RunLatch"
        }
    if intent_id == "INT_SAFE_START_ALARM":
        return {
            "trigger_input": tags.get("start", "I_Start"),
            "reset_input": tags.get("reset", "I_Reset"),
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "safety_input": tags.get("sensor", "I_Sensor1"),
            "alarm_output": tags.get("alarm", "Q_Alarm"),
            "motor_output": tags.get("motor", "Q_Motor_Enable"),
            "fault_latch": "M_FaultLatch"
        }
    if intent_id == "INT_AUTO_STOP_TIMER":
        return {
            "trigger_input": tags.get("start", "I_Start"),
            "stop_input": tags.get("stop", "I_Stop"),
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "motor_output": tags.get("motor", "Q_Motor_Enable"),
            "run_latch": "M_RunLatch",
            "operation_time": time_value or "T#10s",
            "timer": "T_OperationLimit"
        }
    if intent_id == "INT_VFD_ENABLE_NO_ALARM":
        return {
            "trigger_input": tags.get("start", "I_Start"),
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "alarm_output": tags.get("alarm", "Q_Alarm"),
            "motor_output": tags.get("motor", "Q_Motor_Enable")
        }
    if intent_id == "INT_SEQUENCE_THREE_STEPS":
        return {
            "trigger_input": tags.get("start", "I_Start"),
            "reset_input": tags.get("reset", "I_Reset"),
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "step_memory": "M_Step",
            "output": tags.get("output", "Q_Aux_Output")
        }
    if intent_id == "INT_SENSOR_TIMEOUT_ALARM":
        return {
            "sensor_input": tags.get("sensor", "I_Sensor1"),
            "reset_input": tags.get("reset", "I_Reset"),
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "alarm_output": tags.get("alarm", "Q_Alarm"),
            "timeout": time_value or "T#5s",
            "timer": "T_SensorTimeout",
            "last_state_memory": "M_SensorLastState"
        }
    if intent_id == "INT_AUTO_CYCLE":
        return {
            "auto_input": tags.get("auto", "I_Mode_Auto"),
            "trigger_input": tags.get("start", "I_Start"),
            "stop_input": tags.get("stop", "I_Stop"),
            "reset_input": tags.get("reset", "I_Reset"),
            "emergency_input": tags.get("emergency", "I_Emergency"),
            "step_memory": "M_Step",
            "motor_output": tags.get("motor", "Q_Motor_Enable")
        }
    return {}


def _extract_unrecognized_terms(command_text: str) -> list[str]:
    normalized = normalize_text(command_text)
    unrecognized: list[str] = []

    for explicit_tag in EXPLICIT_TAG_PATTERN.findall(command_text):
        if explicit_tag.lower() not in EXACT_TAG_ALIASES and explicit_tag not in unrecognized:
            unrecognized.append(explicit_tag)

    for token in normalized.split():
        if token.isdigit():
            continue
        if token in KNOWN_CONTEXT_TOKENS:
            continue
        if token in VAGUE_REFERENCES and token not in unrecognized:
            unrecognized.append(token)
    return unrecognized


def _build_ambiguities(
    command_text: str,
    intent_id: str,
    tags: dict[str, str],
    time_value: str | None,
    unrecognized_terms: list[str]
) -> list[str]:
    normalized = normalize_text(command_text)
    ambiguities: list[str] = []

    if any(term in VAGUE_REFERENCES for term in unrecognized_terms):
        ambiguities.append("El comando usa una referencia vaga para la accion o salida.")

    if intent_id == "INT_UNKNOWN":
        if not tags:
            ambiguities.append("No se reconocieron variables o senales autorizadas en el comando.")
        if not time_value and _contains_any(normalized, ("despues", "luego", "retardo", "tras")):
            ambiguities.append("Se menciona una accion diferida sin tiempo IEC identificable.")
        if not _contains_any(normalized, ("motor", "salida", "alarma", "sensor", "contactor")):
            ambiguities.append("No se reconoce el elemento industrial objetivo.")

    if unrecognized_terms and not ambiguities:
        ambiguities.append("Existen terminos que no pertenecen al mapa I/O autorizado.")

    return ambiguities


def _build_clarification_question(
    intent_id: str,
    ambiguities: list[str],
    unrecognized_terms: list[str]
) -> str | None:
    if intent_id == "INT_UNKNOWN":
        if any(term in VAGUE_REFERENCES for term in unrecognized_terms):
            return "Indique con precision la salida o equipo objetivo, la condicion de activacion y el tiempo si aplica."
        if unrecognized_terms:
            return "Los terminos indicados no existen en el mapa I/O. Indique un tag autorizado o describa la variable para mapearla."
        return "Aclare la accion industrial requerida, las variables involucradas y el tiempo si corresponde."

    if ambiguities:
        return "El comando requiere una aclaracion adicional antes de generar el paquete PLC."
    return None


def _build_assumptions(
    intent_id: str,
    parameters: dict[str, Any],
    tags: dict[str, str],
    time_value: str | None,
    pulse_count: int | None
) -> list[str]:
    assumptions: list[str] = []

    if intent_id in {
        "INT_MOTOR_START_STOP",
        "INT_MOTOR_LATCH",
        "INT_DELAYED_START",
        "INT_DELAYED_STOP",
        "INT_AUTO_STOP_TIMER",
        "INT_MANUAL_AUTO_MODE",
        "INT_MAINTENANCE_BLOCK",
        "INT_AUTO_CYCLE",
        "INT_CYCLIC_MOTOR"
    } and "emergency" not in tags:
        assumptions.append("Se agrega I_Emergency por seguridad industrial obligatoria.")

    if intent_id == "INT_TIMED_PULSE" and time_value is None:
        assumptions.append("Se usa una duracion por defecto de T#5s.")

    if intent_id == "INT_DELAYED_START" and time_value is None:
        assumptions.append("Se usa un retardo por defecto de T#3s.")

    if intent_id == "INT_DELAYED_STOP" and time_value is None:
        assumptions.append("Se usa un apagado retardado por defecto de T#10s.")

    if intent_id == "INT_COUNTER_PULSES" and pulse_count is None:
        assumptions.append("Se usa un preset de 5 pulsos por defecto.")

    if intent_id == "INT_CYCLIC_MOTOR" and time_value is not None and parameters.get("on_time") == parameters.get("off_time"):
        assumptions.append("Se usa el mismo tiempo para las fases de encendido y apagado.")

    if parameters.get("output") == "Q_Aux_Output" and "output" not in tags and intent_id in {"INT_TIMED_PULSE", "INT_DIRECT_OUTPUT"}:
        assumptions.append("Se usa Q_Aux_Output como salida generica autorizada.")

    return assumptions


def parse_command(command_text: str, alias_index: dict[str, str] | None = None) -> dict[str, Any]:
    """Parse a natural-language industrial command into a structured semantic output."""
    normalized_text = normalize_text(command_text)
    time_values = _extract_times(command_text)
    time_value = time_values[0] if time_values else None
    tags = extract_tags(command_text, alias_index=alias_index)
    pulse_count = _extract_pulse_count(command_text)
    intent_id, confidence = detect_intent(normalized_text, tags, time_value)
    parameters = _build_parameters(intent_id, tags, time_value, pulse_count, time_values)
    recognized_tags = sorted(set(tags.values()) | set(_extract_parameter_tag_values(parameters)))
    unrecognized_terms = _extract_unrecognized_terms(command_text)
    ambiguities = _build_ambiguities(command_text, intent_id, tags, time_value, unrecognized_terms)
    clarification_question = _build_clarification_question(intent_id, ambiguities, unrecognized_terms)
    requires_clarification = bool(intent_id == "INT_UNKNOWN" or clarification_question)
    assumptions = _build_assumptions(intent_id, parameters, tags, time_value, pulse_count)

    return {
        "intent_id": intent_id if intent_id else "INT_UNKNOWN",
        "case_id": None,
        "command_text": command_text,
        "normalized_command": normalized_text,
        "parameters": parameters,
        "confidence": round(confidence if intent_id != "INT_UNKNOWN" else 0.0, 2),
        "ambiguities": ambiguities,
        "requires_clarification": requires_clarification,
        "clarification_question": clarification_question,
        "assumptions": assumptions,
        "recognized_tags": recognized_tags,
        "unrecognized_terms": unrecognized_terms
    }
