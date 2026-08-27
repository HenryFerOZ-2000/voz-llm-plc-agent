from __future__ import annotations

from typing import Any

from plc_ir import PLCFunctionBlockInstance, PLCPOU, PLCProjectIR, PLCTask, PLCVariable
from utils import build_io_map_index, get_project_root, load_json_file, sanitize_filename


INTENT_TEMPLATE_NOT_IMPLEMENTED = "INTENT_TEMPLATE_NOT_IMPLEMENTED"
SUPPORTED_STANDARD_BLOCK_TYPES = {"TON", "TP", "CTU", "R_TRIG", "F_TRIG"}

EXTERNAL_PREFIXES = ("I_", "Q_")
INTERNAL_PREFIXES = ("M_", "T_", "C_", "R_", "F_")

# Tipo IEC/clase de cada recurso interno ya usado por las intenciones existentes.
# Permite generarlos automaticamente sin exigir que preexistan en el mapa PLC.
INTERNAL_RESOURCE_SPECS: dict[str, dict[str, str]] = {
    "M_RunLatch": {"type": "BOOL", "class": "internal"},
    "M_FaultLatch": {"type": "BOOL", "class": "internal"},
    "M_AutoMode": {"type": "BOOL", "class": "internal"},
    "M_ManualMode": {"type": "BOOL", "class": "internal"},
    "M_Step": {"type": "INT", "class": "internal"},
    "M_StopDelayActive": {"type": "BOOL", "class": "internal"},
    "M_SensorLastState": {"type": "BOOL", "class": "internal"},
    "T_Pulse5s": {"type": "TP", "class": "timer"},
    "T_DelayStart": {"type": "TON", "class": "timer"},
    "T_OperationLimit": {"type": "TON", "class": "timer"},
    "T_SensorTimeout": {"type": "TON", "class": "timer"},
    "T_StopDelay": {"type": "TON", "class": "timer"},
    "T_CycleOn": {"type": "TON", "class": "timer"},
    "T_CycleOff": {"type": "TON", "class": "timer"},
    "C_PulseCount": {"type": "CTU", "class": "counter"},
    "R_SensorPulse": {"type": "R_TRIG", "class": "auxiliary"},
    "R_CycleStart": {"type": "R_TRIG", "class": "auxiliary"}
}

# Tipo por defecto cuando un recurso interno no esta en el registro ni en el mapa.
INTERNAL_PREFIX_TYPE_FALLBACK: dict[str, dict[str, str]] = {
    "M_": {"type": "BOOL", "class": "internal"},
    "T_": {"type": "TON", "class": "timer"},
    "C_": {"type": "CTU", "class": "counter"},
    "R_": {"type": "R_TRIG", "class": "auxiliary"},
    "F_": {"type": "F_TRIG", "class": "auxiliary"}
}


def _normalize_target_platform(target_platform: str) -> str:
    normalized = (target_platform or "").strip().upper()
    if normalized in {"OPENPLC", "OPENPLC_ST"}:
        return "OPENPLC_ST"
    if normalized in {"SIEMENS", "SIEMENS_SCL", "SIEMENS_SCL_V18", "TIA", "TIA_V18"}:
        return "SIEMENS_SCL_V18"
    return "CODESYS_ST"


def _default_project_name(intent_id: str, case_id: str | None) -> str:
    safe_case = sanitize_filename(case_id or "NOCASE")
    safe_intent = sanitize_filename(intent_id or "INT_UNKNOWN")
    return f"PLC_PROJECT_{safe_case}_{safe_intent}"


def _load_safety_rules() -> dict[str, Any]:
    project_root = get_project_root()
    return load_json_file(project_root / "config" / "safety_rules.json")


def _flatten_safety_rules(safety_rules: dict[str, Any]) -> list[str]:
    flattened: list[str] = []
    for key in ("priority_rules", "forbidden_conditions", "validation_requirements"):
        for item in safety_rules.get(key, []):
            if isinstance(item, str):
                flattened.append(item)
    return flattened


def get_required_variables_for_intent(intent_id: str, parameters: dict[str, Any]) -> list[str]:
    parameter_overrides = {
        "INT_TIMED_PULSE": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("output", "Q_Aux_Output"),
            parameters.get("timer", "T_Pulse5s")
        ],
        "INT_DIRECT_OUTPUT": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("output", "Q_Aux_Output")
        ],
        "INT_MOTOR_START_STOP": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("stop_input", "I_Stop"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("reset_input", "I_Reset"),
            parameters.get("motor_output", "Q_Motor_Enable"),
            parameters.get("alarm_output", "Q_Alarm"),
            parameters.get("run_indicator", "Q_Pilot_Run"),
            parameters.get("fault_indicator", "Q_Pilot_Fault"),
            parameters.get("run_latch", "M_RunLatch"),
            parameters.get("fault_latch", "M_FaultLatch")
        ],
        "INT_MOTOR_LATCH": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("stop_input", "I_Stop"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("motor_output", "Q_Motor_Enable"),
            parameters.get("run_latch", "M_RunLatch")
        ],
        "INT_SAFE_START_ALARM": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("reset_input", "I_Reset"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("safety_input", "I_Sensor1"),
            parameters.get("alarm_output", "Q_Alarm"),
            parameters.get("motor_output", "Q_Motor_Enable"),
            parameters.get("fault_latch", "M_FaultLatch")
        ],
        "INT_DELAYED_START": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("stop_input", "I_Stop"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("motor_output", "Q_Motor_Enable"),
            parameters.get("timer", "T_DelayStart")
        ],
        "INT_DELAYED_STOP": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("stop_input", "I_Stop"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("motor_output", "Q_Motor_Enable"),
            parameters.get("run_latch", "M_RunLatch"),
            parameters.get("stop_delay_active", "M_StopDelayActive"),
            parameters.get("timer", "T_StopDelay")
        ],
        "INT_AUTO_STOP_TIMER": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("stop_input", "I_Stop"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("motor_output", "Q_Motor_Enable"),
            parameters.get("run_latch", "M_RunLatch"),
            parameters.get("timer", "T_OperationLimit")
        ],
        "INT_EMERGENCY_PRIORITY": [
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("motor_output", "Q_Motor_Enable"),
            parameters.get("output", "Q_Aux_Output"),
            parameters.get("alarm_output", "Q_Alarm")
        ],
        "INT_COUNTER_PULSES": [
            parameters.get("pulse_input", "I_Sensor1"),
            parameters.get("reset_input", "I_Reset"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("output", "Q_Alarm"),
            parameters.get("counter", "C_PulseCount"),
            parameters.get("edge_detector", "R_SensorPulse")
        ],
        "INT_COUNTER_RESET": [
            parameters.get("reset_input", "I_Reset"),
            parameters.get("counter", "C_PulseCount")
        ],
        "INT_MUTUAL_INTERLOCK": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("stop_input", "I_Stop"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("contactor_a", "Q_Contactor_A"),
            parameters.get("contactor_b", "Q_Contactor_B")
        ],
        "INT_VFD_ENABLE_NO_ALARM": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("alarm_output", "Q_Alarm"),
            parameters.get("motor_output", "Q_Motor_Enable")
        ],
        "INT_MANUAL_AUTO_MODE": [
            parameters.get("manual_input", "I_Mode_Manual"),
            parameters.get("auto_input", "I_Mode_Auto"),
            parameters.get("trigger_input", "I_Start"),
            parameters.get("stop_input", "I_Stop"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("motor_output", "Q_Motor_Enable"),
            parameters.get("manual_mode_memory", "M_ManualMode"),
            parameters.get("auto_mode_memory", "M_AutoMode")
        ],
        "INT_SEQUENCE_THREE_STEPS": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("reset_input", "I_Reset"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("step_memory", "M_Step"),
            parameters.get("output", "Q_Aux_Output")
        ],
        "INT_SENSOR_TIMEOUT_ALARM": [
            parameters.get("sensor_input", "I_Sensor1"),
            parameters.get("reset_input", "I_Reset"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("alarm_output", "Q_Alarm"),
            parameters.get("timer", "T_SensorTimeout"),
            parameters.get("last_state_memory", "M_SensorLastState")
        ],
        "INT_MAINTENANCE_BLOCK": [
            parameters.get("maintenance_input", "I_Maintenance"),
            parameters.get("trigger_input", "I_Start"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("motor_output", "Q_Motor_Enable")
        ],
        "INT_STATUS_PILOTS": [
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("motor_output", "Q_Motor_Enable"),
            parameters.get("alarm_output", "Q_Alarm"),
            parameters.get("run_indicator", "Q_Pilot_Run"),
            parameters.get("fault_indicator", "Q_Pilot_Fault")
        ],
        "INT_CYCLIC_MOTOR": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("stop_input", "I_Stop"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("motor_output", "Q_Motor_Enable"),
            parameters.get("run_latch", "M_RunLatch"),
            parameters.get("step_memory", "M_Step"),
            parameters.get("start_edge", "R_CycleStart"),
            parameters.get("on_timer", "T_CycleOn"),
            parameters.get("off_timer", "T_CycleOff")
        ],
        "INT_AUTO_CYCLE": [
            parameters.get("trigger_input", "I_Start"),
            parameters.get("stop_input", "I_Stop"),
            parameters.get("emergency_input", "I_Emergency"),
            parameters.get("reset_input", "I_Reset"),
            parameters.get("motor_output", "Q_Motor_Enable"),
            parameters.get("aux_output", "Q_Aux_Output"),
            parameters.get("alarm_output", "Q_Alarm"),
            parameters.get("step_memory", "M_Step"),
            parameters.get("auto_input", "I_Mode_Auto")
        ]
    }

    required = parameter_overrides.get(intent_id)
    if required is None:
        raise ValueError(f"{INTENT_TEMPLATE_NOT_IMPLEMENTED}: {intent_id}")

    ordered: list[str] = []
    for value in required:
        if not isinstance(value, str):
            continue
        if value.startswith(("I_", "Q_", "M_", "T_", "C_", "R_", "F_")) and value not in ordered:
            ordered.append(value)
    return ordered


def build_test_cases_for_intent(intent_id: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
    emergency_input = parameters.get("emergency_input", "I_Emergency")
    start_input = parameters.get("trigger_input", "I_Start")
    stop_input = parameters.get("stop_input", "I_Stop")
    reset_input = parameters.get("reset_input", "I_Reset")
    motor_output = parameters.get("motor_output", "Q_Motor_Enable")
    alarm_output = parameters.get("alarm_output", "Q_Alarm")
    output = parameters.get("output", "Q_Aux_Output")
    delay_time = parameters.get("delay_time", parameters.get("duration", parameters.get("stop_delay_time", "T#5s")))
    timer_name = parameters.get("timer", "T_DelayStart")
    on_time = parameters.get("on_time", "T#3s")
    off_time = parameters.get("off_time", on_time)
    sensor_input = parameters.get("sensor_input", parameters.get("pulse_input", "I_Sensor1"))
    counter_name = parameters.get("counter", "C_PulseCount")
    preset = parameters.get("preset", 5)

    cases_map: dict[str, list[dict[str, Any]]] = {
        "INT_TIMED_PULSE": [
            {
                "test_id": "TP_01",
                "description": "Activa el pulso con el comando de arranque.",
                "initial_state": {output: False},
                "input_sequence": [{start_input: True}],
                "expected_outputs": {output: True},
                "safety_expectation": f"{emergency_input}=FALSE durante el pulso."
            },
            {
                "test_id": "TP_02",
                "description": "La emergencia cancela el pulso inmediatamente.",
                "initial_state": {output: True},
                "input_sequence": [{emergency_input: True}],
                "expected_outputs": {output: False},
                "safety_expectation": "La salida debe quedar desenergizada."
            },
            {
                "test_id": "TP_03",
                "description": "La salida se desactiva al finalizar el tiempo programado.",
                "initial_state": {output: True},
                "input_sequence": [{"wait": delay_time}],
                "expected_outputs": {output: False},
                "safety_expectation": f"El temporizador {timer_name} debe completar el pulso."
            }
        ],
        "INT_MOTOR_START_STOP": [
            {
                "test_id": "MSS_01",
                "description": "Arranque normal del motor con Start.",
                "initial_state": {motor_output: False},
                "input_sequence": [{start_input: True}],
                "expected_outputs": {motor_output: True},
                "safety_expectation": f"{emergency_input}=FALSE y {stop_input}=FALSE."
            },
            {
                "test_id": "MSS_02",
                "description": "Paro normal con Stop.",
                "initial_state": {motor_output: True},
                "input_sequence": [{stop_input: True}],
                "expected_outputs": {motor_output: False},
                "safety_expectation": f"{stop_input} tiene prioridad sobre {start_input}."
            },
            {
                "test_id": "MSS_03",
                "description": "La emergencia detiene el motor y activa la falla.",
                "initial_state": {motor_output: True},
                "input_sequence": [{emergency_input: True}],
                "expected_outputs": {motor_output: False, alarm_output: True},
                "safety_expectation": "La emergencia debe prevalecer sobre cualquier orden."
            },
            {
                "test_id": "MSS_04",
                "description": "Reset posterior a emergencia sin autoarranque.",
                "initial_state": {alarm_output: True},
                "input_sequence": [{reset_input: True}],
                "expected_outputs": {motor_output: False, alarm_output: False},
                "safety_expectation": "El motor no debe reencender solo."
            },
            {
                "test_id": "MSS_05",
                "description": "Start y Stop simultaneos deben privilegiar Stop.",
                "initial_state": {motor_output: False},
                "input_sequence": [{start_input: True, stop_input: True}],
                "expected_outputs": {motor_output: False},
                "safety_expectation": "No debe existir arranque ambiguo."
            }
        ],
        "INT_DELAYED_START": [
            {
                "test_id": "DS_01",
                "description": "Start inicia el TON y el motor arranca tras esperar.",
                "initial_state": {motor_output: False},
                "input_sequence": [{start_input: True}, {"wait": delay_time}],
                "expected_outputs": {motor_output: True},
                "safety_expectation": f"El temporizador {timer_name} debe alcanzar PT."
            },
            {
                "test_id": "DS_02",
                "description": "Stop antes del tiempo cancela el arranque.",
                "initial_state": {motor_output: False},
                "input_sequence": [{start_input: True}, {stop_input: True}],
                "expected_outputs": {motor_output: False},
                "safety_expectation": "No debe energizarse el motor."
            },
            {
                "test_id": "DS_03",
                "description": "La emergencia durante el retardo anula la orden.",
                "initial_state": {motor_output: False},
                "input_sequence": [{start_input: True}, {emergency_input: True}],
                "expected_outputs": {motor_output: False},
                "safety_expectation": "La emergencia debe abortar el temporizador."
            }
        ],
        "INT_DELAYED_STOP": [
            {
                "test_id": "DST_01",
                "description": "El motor queda encendido tras Start.",
                "initial_state": {motor_output: False},
                "input_sequence": [{start_input: True}],
                "expected_outputs": {motor_output: True},
                "safety_expectation": "La memoria de marcha debe quedar activa."
            },
            {
                "test_id": "DST_02",
                "description": "Stop inicia la espera sin apagar instantaneamente.",
                "initial_state": {motor_output: True},
                "input_sequence": [{stop_input: True}],
                "expected_outputs": {motor_output: True},
                "safety_expectation": "El apagado debe diferirse hasta completar PT."
            },
            {
                "test_id": "DST_03",
                "description": "Al cumplirse el retardo el motor se desactiva.",
                "initial_state": {motor_output: True},
                "input_sequence": [{stop_input: True}, {"wait": delay_time}],
                "expected_outputs": {motor_output: False},
                "safety_expectation": f"El temporizador {timer_name} debe completar el apagado."
            },
            {
                "test_id": "DST_04",
                "description": "La emergencia anula el retardo y para inmediatamente.",
                "initial_state": {motor_output: True},
                "input_sequence": [{emergency_input: True}],
                "expected_outputs": {motor_output: False},
                "safety_expectation": "El paro de emergencia siempre es inmediato."
            }
        ],
        "INT_EMERGENCY_PRIORITY": [
            {
                "test_id": "EP_01",
                "description": "La emergencia desenergiza motor y salida auxiliar.",
                "initial_state": {motor_output: True, output: True},
                "input_sequence": [{emergency_input: True}],
                "expected_outputs": {motor_output: False, output: False, alarm_output: True},
                "safety_expectation": "Prioridad absoluta de seguridad."
            }
        ],
        "INT_COUNTER_PULSES": [
            {
                "test_id": "CP_01",
                "description": "Cuenta pulsos hasta el preset programado.",
                "initial_state": {alarm_output: False},
                "input_sequence": [{sensor_input: "rising_edge"} for _ in range(int(preset))],
                "expected_outputs": {alarm_output: True},
                "safety_expectation": f"El contador {counter_name} debe alcanzar PV={preset}."
            },
            {
                "test_id": "CP_02",
                "description": "Reset limpia el contador y la alarma.",
                "initial_state": {alarm_output: True},
                "input_sequence": [{reset_input: True}],
                "expected_outputs": {alarm_output: False},
                "safety_expectation": "El conteo debe reiniciarse de forma segura."
            },
            {
                "test_id": "CP_03",
                "description": "La emergencia inhibe la salida de alarma.",
                "initial_state": {alarm_output: True},
                "input_sequence": [{emergency_input: True}],
                "expected_outputs": {alarm_output: False},
                "safety_expectation": "La salida no debe permanecer activa en emergencia."
            }
        ],
        "INT_CYCLIC_MOTOR": [
            {
                "test_id": "CM_01",
                "description": "Start inicia el ciclo en fase de motor encendido.",
                "initial_state": {motor_output: False},
                "input_sequence": [{start_input: "rising_edge"}],
                "expected_outputs": {motor_output: True},
                "safety_expectation": "El ciclo solo debe arrancar por un nuevo flanco de Start."
            },
            {
                "test_id": "CM_02",
                "description": "Al cumplirse el tiempo encendido comienza la fase apagada.",
                "initial_state": {motor_output: False},
                "input_sequence": [{start_input: "rising_edge"}, {"wait": on_time}],
                "expected_outputs": {motor_output: False},
                "safety_expectation": "La fase encendida debe respetar el TIME IEC configurado."
            },
            {
                "test_id": "CM_03",
                "description": "Tras las dos fases el motor vuelve a encenderse y repite el ciclo.",
                "initial_state": {motor_output: False},
                "input_sequence": [
                    {start_input: "rising_edge"},
                    {"wait": on_time},
                    {"wait": "T#1ms"},
                    {"wait": off_time}
                ],
                "expected_outputs": {motor_output: True},
                "safety_expectation": "El ciclo debe repetirse hasta recibir Stop o emergencia."
            },
            {
                "test_id": "CM_04",
                "description": "Stop detiene el ciclo y desenergiza el motor.",
                "initial_state": {motor_output: False},
                "input_sequence": [{start_input: "rising_edge"}, {stop_input: True}],
                "expected_outputs": {motor_output: False},
                "safety_expectation": "Stop tiene prioridad sobre el estado del ciclo."
            },
            {
                "test_id": "CM_05",
                "description": "La emergencia detiene el ciclo inmediatamente.",
                "initial_state": {motor_output: False},
                "input_sequence": [{start_input: "rising_edge"}, {emergency_input: True}],
                "expected_outputs": {motor_output: False},
                "safety_expectation": "I_Emergency tiene prioridad absoluta."
            }
        ]
    }

    if intent_id in cases_map:
        return cases_map[intent_id]

    if intent_id in {
        "INT_DIRECT_OUTPUT",
        "INT_MOTOR_LATCH",
        "INT_SAFE_START_ALARM",
        "INT_AUTO_STOP_TIMER",
        "INT_COUNTER_RESET",
        "INT_MUTUAL_INTERLOCK",
        "INT_VFD_ENABLE_NO_ALARM",
        "INT_MANUAL_AUTO_MODE",
        "INT_SEQUENCE_THREE_STEPS",
        "INT_SENSOR_TIMEOUT_ALARM",
        "INT_MAINTENANCE_BLOCK",
        "INT_STATUS_PILOTS",
        "INT_AUTO_CYCLE"
    }:
        return [
            {
                "test_id": f"{intent_id}_01",
                "description": "Verificacion funcional basica del caso generado.",
                "initial_state": {},
                "input_sequence": [],
                "expected_outputs": {},
                "safety_expectation": "Validar comportamiento segun la intencion detectada."
            }
        ]

    raise ValueError(f"{INTENT_TEMPLATE_NOT_IMPLEMENTED}: {intent_id}")


def _build_variable_from_entry(entry: dict[str, Any], source: str = "plc_map") -> PLCVariable:
    data_type = str(entry.get("type", "BOOL")).upper()
    location = str(entry.get("location", "")).strip() or None
    initial_value = str(entry.get("initial_value", "")).strip() or None
    return PLCVariable(
        name=str(entry.get("name", "")),
        data_type=data_type,
        var_class=str(entry.get("class", "internal")),
        location=location,
        initial_value=initial_value,
        description=str(entry.get("description", "")),
        source=source,
        is_standard_block=data_type in SUPPORTED_STANDARD_BLOCK_TYPES
    )


def _internal_resource_spec(name: str) -> dict[str, str]:
    spec = INTERNAL_RESOURCE_SPECS.get(name)
    if spec is not None:
        return spec
    for prefix, fallback in INTERNAL_PREFIX_TYPE_FALLBACK.items():
        if name.startswith(prefix):
            return fallback
    return {"type": "BOOL", "class": "internal"}


def _resolve_internal_resources(
    names: list[str],
    io_index: dict[str, dict[str, Any]]
) -> tuple[list[PLCVariable], list[PLCVariable]]:
    """Resolve internal implementation resources: reuse from the map if declared, else auto-generate."""
    resolved: list[PLCVariable] = []
    generated: list[PLCVariable] = []
    for name in names:
        if name in io_index:
            resolved.append(_build_variable_from_entry(io_index[name], source="plc_map"))
            continue
        spec = _internal_resource_spec(name)
        variable = _build_variable_from_entry(
            {
                "name": name,
                "type": spec["type"],
                "class": spec["class"],
                "location": "",
                "initial_value": "",
                "description": f"Recurso interno generado automaticamente ({spec['type']})."
            },
            source="generated_internal"
        )
        resolved.append(variable)
        generated.append(variable)
    return resolved, generated


def _resolve_functional_variables(
    requirements: list[dict[str, Any]],
    io_index: dict[str, dict[str, Any]],
    already_resolved_names: set[str]
) -> tuple[list[PLCVariable], list[PLCVariable]]:
    """
    Resolve functional/process variables (e.g. Level_SP): reuse from the map or a prior
    generation if already present with a compatible type; create and report as new otherwise.
    Never invents a variable when the requirement is ambiguous (missing type).
    """
    resolved: list[PLCVariable] = []
    generated: list[PLCVariable] = []
    seen_names: set[str] = set()

    for requirement in requirements:
        name = str(requirement.get("name", "")).strip()
        requested_type = str(requirement.get("type", "")).strip().upper()
        if not name:
            raise ValueError("Se solicito una variable funcional sin nombre.")
        if not requested_type:
            raise ValueError(f"Variable funcional ambigua: {name} no especifica un tipo. No se puede inventar.")
        if name in seen_names:
            continue
        seen_names.add(name)

        if name in already_resolved_names or name in {v.name for v in resolved}:
            raise ValueError(f"La variable funcional {name} coincide con un recurso ya resuelto de otro tipo.")

        if name in io_index:
            existing_type = str(io_index[name].get("type", "")).upper()
            if existing_type != requested_type:
                raise ValueError(
                    f"La variable funcional {name} ya existe en el mapa PLC con tipo {existing_type}, "
                    f"incompatible con el tipo solicitado {requested_type}."
                )
            resolved.append(_build_variable_from_entry(io_index[name], source="plc_map"))
            continue

        variable = _build_variable_from_entry(
            {
                "name": name,
                "type": requested_type,
                "class": "internal",
                "location": "",
                "initial_value": "",
                "description": str(requirement.get("semantic_role", "")) or "Variable funcional generada automaticamente."
            },
            source="generated_functional"
        )
        resolved.append(variable)
        generated.append(variable)

    return resolved, generated


def _build_function_blocks(variables: list[PLCVariable], parameters: dict[str, Any]) -> list[PLCFunctionBlockInstance]:
    function_blocks: list[PLCFunctionBlockInstance] = []

    for variable in variables:
        if not variable.is_standard_block:
            continue

        block_parameters: dict[str, Any] = {}
        for key, value in parameters.items():
            if value == variable.name:
                block_parameters["semantic_parameter"] = key
            if variable.data_type in {"TON", "TP"} and key in {
                "duration",
                "delay_time",
                "timeout",
                "stop_delay_time",
                "operation_time",
                "on_time",
                "off_time"
            }:
                block_parameters["PT"] = value
            if variable.data_type == "CTU" and key == "preset":
                block_parameters["PV"] = value

        function_blocks.append(
            PLCFunctionBlockInstance(
                instance_name=variable.name,
                block_type=variable.data_type,
                parameters=block_parameters,
                description=variable.description or f"Instancia auxiliar {variable.data_type}."
            )
        )

    return function_blocks


def build_project_ir(
    semantic_output: dict[str, Any],
    io_map: dict[str, Any],
    target_platform: str,
    project_name: str | None = None,
    functional_requirements: list[dict[str, Any]] | None = None
) -> PLCProjectIR:
    intent_id = semantic_output.get("intent_id", "INT_UNKNOWN")
    command_text = semantic_output.get("command_text", "")
    case_id = semantic_output.get("case_id") or "NOCASE"
    parameters = semantic_output.get("parameters", {})

    required_variables = get_required_variables_for_intent(intent_id, parameters)
    io_index = build_io_map_index(io_map)

    external_names = [name for name in required_variables if name.startswith(EXTERNAL_PREFIXES)]
    internal_names = [name for name in required_variables if name.startswith(INTERNAL_PREFIXES)]

    missing_variables = [name for name in external_names if name not in io_index]
    if missing_variables:
        raise ValueError(
            "Recurso externo no autorizado/no existente en el mapa PLC: "
            + ", ".join(missing_variables)
        )

    external_variables = [_build_variable_from_entry(io_index[name], source="plc_map") for name in external_names]
    internal_variables, generated_internal = _resolve_internal_resources(internal_names, io_index)
    functional_variables, generated_functional = _resolve_functional_variables(
        functional_requirements or [],
        io_index,
        already_resolved_names={variable.name for variable in external_variables + internal_variables}
    )

    variables = external_variables + internal_variables + functional_variables
    function_blocks = _build_function_blocks(variables, parameters)
    safety_rules = _load_safety_rules()
    test_cases = build_test_cases_for_intent(intent_id, parameters)

    pou = PLCPOU(
        name="PLC_PRG",
        pou_type="PROGRAM",
        language="ST",
        variables=variables,
        function_blocks=function_blocks,
        implementation_code="",
        comments=[
            "POU principal generada automaticamente por voz_llm_plc_agent.",
            f"Intencion detectada: {intent_id}.",
            "La sintaxis final se adapta posteriormente segun la plataforma destino."
        ]
    )
    task = PLCTask(
        name="MainTask",
        interval="T#100ms",
        priority=1,
        pou_name="PLC_PRG"
    )

    normalized_target = _normalize_target_platform(target_platform)
    ir_project_name = project_name or _default_project_name(intent_id, semantic_output.get("case_id"))
    metadata = {
        "semantic_output": dict(semantic_output),
        "parameters": dict(parameters),
        "required_variables": list(required_variables),
        "authorized_variables": sorted(set(io_index.keys()) | {variable.name for variable in variables}),
        "missing_variables": missing_variables,
        "platform_requested": normalized_target,
        "generated_internal_variables": [variable.to_dict() for variable in generated_internal],
        "generated_functional_variables": [variable.to_dict() for variable in generated_functional]
    }

    return PLCProjectIR(
        project_name=ir_project_name,
        target_platform=normalized_target,
        case_id=str(case_id),
        intent_id=intent_id,
        command_text=command_text,
        pou=pou,
        task=task,
        safety_rules=_flatten_safety_rules(safety_rules),
        test_cases=test_cases,
        metadata=metadata
    )
