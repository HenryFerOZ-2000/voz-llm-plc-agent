from __future__ import annotations

from typing import Any

from alias_resolver import filter_llm_allowed_entries
from ir_builder import OPTIONAL_PARAMETER_KEYS
from utils import build_io_map_index


INTENT_PARAMETER_HINTS = {
    "INT_TIMED_PULSE": ["trigger_input", "emergency_input", "output", "duration", "timer"],
    "INT_DIRECT_OUTPUT": ["trigger_input", "emergency_input", "output"],
    "INT_MOTOR_START_STOP": [
        "trigger_input",
        "stop_input",
        "emergency_input",
        "reset_input",
        "motor_output",
        "alarm_output",
        "run_indicator",
        "fault_indicator",
        "run_latch",
        "fault_latch"
    ],
    "INT_DELAYED_START": ["trigger_input", "stop_input", "emergency_input", "motor_output", "delay_time", "timer"],
    "INT_DELAYED_STOP": [
        "trigger_input",
        "stop_input",
        "emergency_input",
        "motor_output",
        "run_latch",
        "stop_delay_active",
        "stop_delay_time",
        "timer"
    ],
    "INT_COUNTER_PULSES": ["pulse_input", "reset_input", "emergency_input", "output", "counter", "preset"],
    "INT_MUTUAL_INTERLOCK": ["trigger_input", "stop_input", "emergency_input", "contactor_a", "contactor_b"],
    "INT_MANUAL_AUTO_MODE": [
        "manual_input",
        "auto_input",
        "emergency_input",
        "trigger_input",
        "motor_output",
        "manual_mode_memory",
        "auto_mode_memory"
    ],
    "INT_SENSOR_TIMEOUT_ALARM": ["sensor_input", "alarm_output", "timeout", "timer", "last_state_memory"],
    "INT_CYCLIC_MOTOR": [
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
    "INT_AUTO_CYCLE": ["auto_input", "trigger_input", "stop_input", "reset_input", "emergency_input", "step_memory", "motor_output"]
}

MINIMAL_FEW_SHOT_EXAMPLES = [
    {
        "command": "Haz que el motor se encienda con Start y se apague con Stop",
        "intent_id": "INT_MOTOR_START_STOP",
        "parameters": {
            "trigger_input": "I_Start",
            "stop_input": "I_Stop",
            "emergency_input": "I_Emergency",
            "motor_output": "Q_Motor_Enable"
        }
    },
    {
        "command": "Activa una salida por 8 segundos con Start",
        "intent_id": "INT_TIMED_PULSE",
        "parameters": {
            "trigger_input": "I_Start",
            "emergency_input": "I_Emergency",
            "output": "Q_Aux_Output",
            "duration": "T#8s",
            "timer": "T_Pulse5s"
        }
    },
    {
        "command": "Arranca el motor luego de 4 segundos",
        "intent_id": "INT_DELAYED_START",
        "parameters": {
            "trigger_input": "I_Start",
            "stop_input": "I_Stop",
            "emergency_input": "I_Emergency",
            "motor_output": "Q_Motor_Enable",
            "delay_time": "T#4s",
            "timer": "T_DelayStart"
        }
    },
    {
        "command": "Cuenta cinco pulsos del sensor y activa alarma",
        "intent_id": "INT_COUNTER_PULSES",
        "parameters": {
            "pulse_input": "I_Sensor1",
            "reset_input": "I_Reset",
            "emergency_input": "I_Emergency",
            "output": "Q_Alarm",
            "counter": "C_PulseCount",
            "preset": 5
        }
    },
    {
        "command": "Si hay emergencia apaga todo",
        "intent_id": "INT_EMERGENCY_PRIORITY",
        "parameters": {
            "emergency_input": "I_Emergency",
            "affected_outputs": [
                "Q_Motor_Enable",
                "Q_Aux_Output"
            ],
            "alarm_output": "Q_Alarm"
        }
    },
    {
        "command": "Enciende el motor con Start y alterna 3 segundos encendido y 3 segundos apagado hasta Stop",
        "intent_id": "INT_CYCLIC_MOTOR",
        "parameters": {
            "trigger_input": "I_Start",
            "stop_input": "I_Stop",
            "emergency_input": "I_Emergency",
            "motor_output": "Q_Motor_Enable",
            "run_latch": "M_RunLatch",
            "step_memory": "M_Step",
            "start_edge": "R_CycleStart",
            "on_timer": "T_CycleOn",
            "off_timer": "T_CycleOff",
            "on_time": "T#3s",
            "off_time": "T#3s"
        }
    }
]


def _summarize_intents(intents_catalog: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for intent_id, payload in intents_catalog.items():
        if not isinstance(payload, dict):
            continue
        optional_keys = OPTIONAL_PARAMETER_KEYS.get(intent_id, set())
        all_keys = INTENT_PARAMETER_HINTS.get(intent_id, [])
        summaries.append(
            {
                "intent_id": intent_id,
                "description": payload.get("description", ""),
                "required_inputs": payload.get("required_inputs", []),
                "required_outputs": payload.get("required_outputs", []),
                "required_internal": payload.get("required_internal", []),
                "plc_blocks": payload.get("plc_blocks", []),
                # "expected_parameters" NO es una checklist obligatoria: son los NOMBRES validos
                # que este intent reconoce. Los que tambien aparecen en "optional_parameter_names"
                # (p.ej. reset_input/alarm_output/run_indicator/fault_indicator en
                # INT_MOTOR_START_STOP) solo deben incluirse en "parameters" si el comando
                # REALMENTE pidio esa funcion (reset, alarma, piloto...) - omitelos si no se pidio,
                # nunca rellenes con el tag fisico historico "por si acaso".
                "expected_parameters": all_keys,
                "optional_parameter_names": sorted(optional_keys) if optional_keys else []
            }
        )
    return summaries


def _summarize_io_map(io_map: dict[str, Any]) -> list[dict[str, Any]]:
    io_index = build_io_map_index(filter_llm_allowed_entries(io_map))
    summary: list[dict[str, Any]] = []
    for tag_name in sorted(io_index):
        entry = io_index[tag_name]
        summary.append(
            {
                "name": tag_name,
                "class": entry.get("class", ""),
                "type": entry.get("type", ""),
                "location": entry.get("location", ""),
                "description": entry.get("description", ""),
                "aliases": entry.get("aliases", []),
                "semantic_role": entry.get("semantic_role", ""),
                # FREE/ASSIGNED/LOCKED (ver IOAllocator, docs/23_io_allocator.md): el LLM debe
                # saber que un nombre ASSIGNED es solo el rol ACTUAL de ese canal fisico, no una
                # etiqueta permanente - puede reutilizarse tal cual o, si el comando pide una
                # funcion distinta, el sistema lo reasignara automaticamente (nunca preguntando
                # por el tag). Solo LOCKED es realmente fijo.
                "state": entry.get("state", "ASSIGNED")
            }
        )
    return summary


def _summarize_safety_rules(safety_rules: dict[str, Any]) -> dict[str, Any]:
    return {
        "critical_outputs": safety_rules.get("critical_outputs", []),
        "priority_rules": safety_rules.get("priority_rules", []),
        "forbidden_conditions": safety_rules.get("forbidden_conditions", []),
        "validation_requirements": safety_rules.get("validation_requirements", [])
    }


def build_llm_context(
    command_text: str,
    io_map: dict[str, Any],
    intents_catalog: dict[str, Any],
    safety_rules: dict[str, Any]
) -> dict[str, Any]:
    """
    Build a compact, explicit and safe context for semantic interpretation.

    The context intentionally omits platform-specific deployment actions and
    any secret material. It only exposes approved intents, approved tags and
    a handful of examples relevant to industrial automation commands.
    """
    return {
        "command_text": command_text,
        "authorized_intents": _summarize_intents(intents_catalog),
        "authorized_io_map": _summarize_io_map(io_map),
        "authorized_tags": sorted(build_io_map_index(filter_llm_allowed_entries(io_map))),
        "io_allocation_policy": (
            "authorized_io_map.state dice FREE (canal fisico disponible, sin funcion todavia), "
            "ASSIGNED (tiene un rol actual, pero es REASIGNABLE - puedes describir un recurso "
            "funcional nuevo con ese mismo canal en mente, el sistema decide si lo reasigna) o "
            "LOCKED (fijo, nunca cambia de nombre - reutilizalo tal cual si la funcion coincide). "
            "No necesitas que el nombre exacto que necesitas ya exista en el mapa: si el comando "
            "pide una funcion fisica nueva (una entrada o salida que hoy no tiene ese rol), "
            "propon un nombre funcional claro con el prefijo correcto (I_/Q_/AI_/AO_) - el "
            "IOAllocator decide deterministicamente que canal fisico usar. NUNCA propongas una "
            "direccion (%I.../%Q...); solo el nombre funcional."
        ),
        "safety_rules": _summarize_safety_rules(safety_rules),
        "iec_time_format": {
            "description": "Use IEC 61131-3 TIME literals",
            "examples": ["T#5s", "T#10s", "T#1m", "T#100ms"]
        },
        "allowed_standard_blocks": ["IF", "CASE", "TON", "TP", "CTU", "R_TRIG", "F_TRIG", "NOT"],
        "examples": list(MINIMAL_FEW_SHOT_EXAMPLES)
    }
