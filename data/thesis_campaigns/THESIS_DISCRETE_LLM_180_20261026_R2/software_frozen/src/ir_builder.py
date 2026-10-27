from __future__ import annotations

from typing import Any
from analog_scaling import prepare_analog_bindings

from functional_requirements import (
    CLASS_CATALOG,
    classify_functional_requirement,
    composition_tags,
    detect_multi_actor_motor_targets,
    get_functional_requirement_process_variables,
    get_functional_requirement_tags,
    detect_composed_program,
    detect_timed_sequences,
    has_composable_program,
    resolve_parameter_resources,
    SEQUENCE_REPEAT_CONTINUOUS,
    SEQUENCE_REPEAT_ONCE,
    timed_sequence_repeat,
    timed_sequence_start_mode
)
from functional_resources import FunctionalResourceError, resolve_functional_resources
from plc_ir import PLCFunctionBlockInstance, PLCPOU, PLCProjectIR, PLCTask, PLCVariable
from utils import build_io_map_index, get_project_root, load_json_file, sanitize_filename


INTENT_TEMPLATE_NOT_IMPLEMENTED = "INTENT_TEMPLATE_NOT_IMPLEMENTED"
SUPPORTED_STANDARD_BLOCK_TYPES = {"TON", "TP", "CTU", "R_TRIG", "F_TRIG"}

# AI_/AO_ (entradas/salidas analogicas fisicas del banco PID - ver docs/21_pid_supervisory_control.md)
# se autorizan y verifican EXACTAMENTE igual que I_/Q_: deben existir en el mapa PLC activo y estar
# permitidas por el perfil, nunca inventadas por el LLM. AI_/AO_ se listan antes que I_/Q_ solo para
# que un nombre "AI_..."/"AO_..." nunca sea confundido por coincidencia de sufijo; con
# str.startswith(tuple) el orden no afecta el resultado, pero se deja explicito por claridad.
EXTERNAL_PREFIXES = ("AI_", "AO_", "I_", "Q_")
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
    "M_SupervisionActive": {"type": "BOOL", "class": "internal"},
    "T_SeqDelay": {"type": "TON", "class": "timer"},
    "T_Cycle": {"type": "TON", "class": "timer"},
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


# Recursos externos OPCIONALES por intent: representan una funcionalidad extra que el intent
# PUEDE incluir (reset manual, alarma, pilotos de estado...) pero que no es intrinseca a su
# significado base. A diferencia de las claves CORE de cada entrada de `parameter_overrides` (el
# resto de la lista - siempre resueltas via parameters.get(key, default_fisico)), una clave
# OPTIONAL_PARAMETER_KEYS solo debe aportar un recurso fisico exigido si el comando REALMENTE la
# pidio - es decir, si `parameters` ya trae un valor explicito para esa clave (puesto alli por el
# parser/LLM al reconocer la mencion, nunca por relleno automatico). Si esta ausente, la funcion
# se omite por completo: no se declara, no se exige, no aparece en el IR ni en el SCL. Este es el
# mismo principio que ya protege a `emergency_input` (via semantic_repair.
# strip_unavailable_emergency_reference), aplicado ahora a cualquier otra clave opcional sin
# necesitar un parche especifico por tag - ver tambien code_generator._generate_motor_start_stop_body
# y semantic_parser._build_motor_start_stop_parameters, que respetan la misma clasificacion.
OPTIONAL_PARAMETER_KEYS: dict[str, set[str]] = {
    "INT_MOTOR_START_STOP": {"reset_input", "alarm_output", "run_indicator", "fault_indicator"},
    # auto_input: entrada de seleccion de modo del operador (MODE_AUTO); manual_pump_input: orden manual de
    # la bomba. Solo existen si el comando describe esa funcion (o la exige un requisito presente).
    "INT_PID_SUPERVISOR": {"auto_input", "manual_pump_input"},
    # Ruta de arranque opcional (Start/Stop) subordinada a la emergencia.
    "INT_EMERGENCY_PRIORITY": {"trigger_input", "stop_input", "output", "alarm_output"},
    # Orden propia por modo (manual_command_input / auto_command_input); sin ellas, forma historica Start/Stop.
    "INT_MANUAL_AUTO_MODE": {"manual_command_input", "auto_command_input"},
    "INT_SEQUENCE_THREE_STEPS": {"reset_input", "stop_input"},
    # Supervision armada por la orden de arranque.
    "INT_SENSOR_TIMEOUT_ALARM": {"trigger_input", "reset_input"},
    # Entradas que el intent no necesita para su funcion: solo si el comando las pide (si no, neutro FALSE).
    "INT_DELAYED_START": {"stop_input"},
    "INT_AUTO_STOP_TIMER": {"stop_input"},
    "INT_COUNTER_PULSES": {"reset_input"},
    "INT_SAFE_START_ALARM": {"reset_input"},
    # Pilotos derivados de senales de estado (marcha/falla) y piloto de detenido.
    "INT_STATUS_PILOTS": {"run_state_input", "fault_input", "stop_indicator"},
    "INT_AUTO_CYCLE": {"auto_input", "stop_input"},
}

# CONTRATO DE RECURSOS POR INTENT (fuente unica): (clave semantica, valor por defecto) en el orden en
# que el IR declara las variables. La consumen get_required_variables_for_intent (IR), la etapa de
# semantica efectiva (effective_semantics.normalize_effective_semantics, que vuelve EXPLICITOS y
# trazables los defaults externos antes del IOAllocator y del snapshot) y el generador (code_generator:
# guardia de "ningun default externo oculto"). Los defaults I_/Q_/AI_/AO_ son recursos externos
# funcionales; M_/T_/C_/R_ son recursos internos tecnicos (se autogeneran, nunca tocan el mapa).
INTENT_RESOURCE_TABLE: dict[str, tuple[tuple[str, str], ...]] = {
    "INT_TIMED_PULSE": (
        ("trigger_input", "I_Start"), ("emergency_input", "I_Emergency"), ("output", "Q_Aux_Output"), ("timer", "T_Pulse5s")),
    "INT_DIRECT_OUTPUT": (
        ("trigger_input", "I_Start"), ("emergency_input", "I_Emergency"), ("output", "Q_Aux_Output")),
    "INT_MOTOR_START_STOP": (
        ("trigger_input", "I_Start"), ("stop_input", "I_Stop"), ("emergency_input", "I_Emergency"),
        ("motor_output", "Q_Motor_Enable"), ("run_latch", "M_RunLatch"),
        # fault_latch es un recurso INTERNO (M_, autogenerado sin exigir presencia en el mapa
        # fisico) usado por la logica CORE de arranque/paro para recordar que hubo una falla -
        # se mantiene incondicional, solo las claves externas opcionales dependen de si el comando
        # las pidio (OPTIONAL_PARAMETER_KEYS).
        ("fault_latch", "M_FaultLatch")),
    "INT_MOTOR_LATCH": (
        ("trigger_input", "I_Start"), ("stop_input", "I_Stop"), ("emergency_input", "I_Emergency"),
        ("motor_output", "Q_Motor_Enable"), ("run_latch", "M_RunLatch")),
    "INT_SAFE_START_ALARM": (
        ("trigger_input", "I_Start"), ("emergency_input", "I_Emergency"),
        ("safety_input", "I_Sensor1"), ("alarm_output", "Q_Alarm"), ("motor_output", "Q_Motor_Enable"),
        ("fault_latch", "M_FaultLatch")),
    "INT_DELAYED_START": (
        ("trigger_input", "I_Start"), ("emergency_input", "I_Emergency"),
        ("motor_output", "Q_Motor_Enable"), ("timer", "T_DelayStart")),
    "INT_DELAYED_STOP": (
        ("trigger_input", "I_Start"), ("stop_input", "I_Stop"), ("emergency_input", "I_Emergency"),
        ("motor_output", "Q_Motor_Enable"), ("run_latch", "M_RunLatch"), ("stop_delay_active", "M_StopDelayActive"),
        ("timer", "T_StopDelay")),
    "INT_AUTO_STOP_TIMER": (
        ("trigger_input", "I_Start"), ("emergency_input", "I_Emergency"),
        ("motor_output", "Q_Motor_Enable"), ("run_latch", "M_RunLatch"), ("timer", "T_OperationLimit")),
    "INT_EMERGENCY_PRIORITY": (
        ("emergency_input", "I_Emergency"), ("motor_output", "Q_Motor_Enable")),
    "INT_COUNTER_PULSES": (
        ("pulse_input", "I_Sensor1"), ("emergency_input", "I_Emergency"),
        ("output", "Q_Alarm"), ("counter", "C_PulseCount"), ("edge_detector", "R_SensorPulse")),
    "INT_COUNTER_RESET": (
        ("reset_input", "I_Reset"), ("counter", "C_PulseCount")),
    "INT_MUTUAL_INTERLOCK": (
        ("request_a", "I_Request_A"), ("request_b", "I_Request_B"), ("emergency_input", "I_Emergency"),
        ("contactor_a", "Q_Contactor_A"), ("contactor_b", "Q_Contactor_B")),
    "INT_VFD_ENABLE_NO_ALARM": (
        ("trigger_input", "I_Start"), ("emergency_input", "I_Emergency"), ("alarm_input", "I_Alarm"),
        ("motor_output", "Q_Motor_Enable")),
    "INT_MANUAL_AUTO_MODE": (
        ("manual_input", "I_Mode_Manual"), ("auto_input", "I_Mode_Auto"), ("trigger_input", "I_Start"),
        ("stop_input", "I_Stop"), ("emergency_input", "I_Emergency"), ("motor_output", "Q_Motor_Enable"),
        ("manual_mode_memory", "M_ManualMode"), ("auto_mode_memory", "M_AutoMode")),
    "INT_SEQUENCE_THREE_STEPS": (
        ("trigger_input", "I_Start"), ("emergency_input", "I_Emergency"), ("main_output", "Q_Motor_Enable"),
        ("aux_output", "Q_Aux_Output"), ("step_memory", "M_Step"), ("timer", "T_SeqDelay")),
    "INT_SENSOR_TIMEOUT_ALARM": (
        ("sensor_input", "I_Sensor1"), ("emergency_input", "I_Emergency"),
        ("alarm_output", "Q_Alarm"), ("timer", "T_SensorTimeout"), ("last_state_memory", "M_SensorLastState"),
        ("supervision_memory", "M_SupervisionActive")),
    "INT_MAINTENANCE_BLOCK": (
        ("maintenance_input", "I_Maintenance"), ("trigger_input", "I_Start"), ("emergency_input", "I_Emergency"),
        ("motor_output", "Q_Motor_Enable")),
    "INT_STATUS_PILOTS": (
        ("emergency_input", "I_Emergency"), ("motor_output", "Q_Motor_Enable"), ("alarm_output", "Q_Alarm"),
        ("run_indicator", "Q_Pilot_Run"), ("fault_indicator", "Q_Pilot_Fault")),
    "INT_CYCLIC_MOTOR": (
        ("trigger_input", "I_Start"), ("stop_input", "I_Stop"), ("emergency_input", "I_Emergency"),
        ("motor_output", "Q_Motor_Enable"), ("run_latch", "M_RunLatch"), ("step_memory", "M_Step"),
        ("start_edge", "R_CycleStart"), ("on_timer", "T_CycleOn"), ("off_timer", "T_CycleOff")),
    "INT_AUTO_CYCLE": (
        ("trigger_input", "I_Start"), ("reset_input", "I_Reset"), ("emergency_input", "I_Emergency"),
        ("run_output", "Q_Motor_Enable"), ("complete_output", "Q_Cycle_Complete"), ("step_memory", "M_Step"),
        ("timer", "T_Cycle")),
    "INT_SPEED_SELECTION": (
        ("speed_low_input", "I_Speed_Low"), ("speed_medium_input", "I_Speed_Medium"), ("speed_high_input", "I_Speed_High"),
        ("emergency_input", "I_Emergency"), ("speed_low_output", "Q_Speed_Low"),
        ("speed_medium_output", "Q_Speed_Medium"), ("speed_high_output", "Q_Speed_High")),
    "INT_PID_SUPERVISOR": (
        ("emergency_input", "I_Emergency"), ("reset_input", "I_Reset"), ("alarm_output", "Q_Alarm"),
        ("pump_output", "Q_Pump_Enable")),
}

# Claves equivalentes de un slot del contrato (nombre historico -> mismo recurso): si el parser uso el alias, el
# slot esta cubierto (no se completa el default) y la plantilla lee el valor del alias. INT_MUTUAL_INTERLOCK: las
# ordenes de cada contactor se expresaban historicamente como trigger_input / stop_input.
INTENT_SLOT_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "INT_MUTUAL_INTERLOCK": {"request_a": ("trigger_input",), "request_b": ("stop_input",)},
}


def slot_value(intent_id: str, parameters: dict[str, Any], key: str) -> Any:
    """Valor del slot `key` (o de su alias historico) presente en `parameters`; None si ninguno esta."""
    for candidate in (key, *INTENT_SLOT_ALIASES.get(intent_id, {}).get(key, ())):
        if candidate in parameters:
            return parameters[candidate]
    return None


# Valores funcionales (no recursos) que la plantilla del generador usa si el parser no los dio. Fuente
# unica para code_generator y para la traza de la semantica efectiva (nunca se rellenan en `parameters`:
# solo se registran, para que la evaluacion semantica no los confunda con algo que el comando dijo).
INTENT_VALUE_DEFAULTS: dict[str, dict[str, Any]] = {
    "INT_TIMED_PULSE": {"duration": "T#5s"},
    "INT_DELAYED_START": {"delay_time": "T#3s"},
    "INT_DELAYED_STOP": {"stop_delay_time": "T#10s"},
    "INT_AUTO_STOP_TIMER": {"operation_time": "T#10s"},
    "INT_COUNTER_PULSES": {"preset": 5},
    "INT_SENSOR_TIMEOUT_ALARM": {"timeout": "T#5s"},
    "INT_CYCLIC_MOTOR": {"on_time": "T#3s", "off_time": "T#3s"},
    "INT_SEQUENCE_THREE_STEPS": {"delay_time": "T#3s"},
    "INT_AUTO_CYCLE": {"cycle_time": "T#3s"},
}


def intent_resource_table(intent_id: str, parameters: dict[str, Any] | None = None) -> tuple[tuple[str, str], ...] | None:
    """(clave, default) de los recursos del intent; None si el intent no tiene plantilla."""
    table = INTENT_RESOURCE_TABLE.get(intent_id)
    if intent_id == 'INT_MANUAL_AUTO_MODE' and (parameters or {}).get('_mode_selection_only') is True:
        keys = {'auto_input', 'emergency_input', 'manual_mode_memory', 'auto_mode_memory'}
        return tuple(slot for slot in table if slot[0] in keys)
    return table


def get_required_variables_for_intent(intent_id: str, parameters: dict[str, Any]) -> list[str]:
    table = intent_resource_table(intent_id, parameters)
    if table is None:
        raise ValueError(f"{INTENT_TEMPLATE_NOT_IMPLEMENTED}: {intent_id}")
    required: list[Any] = [
        slot_value(intent_id, parameters, key) if slot_value(intent_id, parameters, key) is not None else default
        for key, default in table
    ]
    # Claves OPCIONALES: solo aportan un recurso si el comando realmente las pidio (presentes en
    # `parameters`); nunca se sustituyen por un tag fisico por defecto.
    for optional_key in OPTIONAL_PARAMETER_KEYS.get(intent_id, ()):
        if optional_key in parameters:
            required.append(parameters[optional_key])

    ordered: list[str] = []
    for value in required:
        if not isinstance(value, str):
            continue
        if value.startswith(("I_", "Q_", "AI_", "AO_", "M_", "T_", "C_", "R_", "F_")) and value not in ordered:
            ordered.append(value)
    return ordered


def build_test_cases_for_composition(functional_requirements: list[dict[str, Any]],
                                     analog_bindings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """
    Casos de prueba GENERICOS derivados de la estructura de una secuencia compuesta (nunca de una
    maquina concreta): arranque -> etapa 1, avance por tiempo a cada etapa siguiente, Stop apaga todo
    y cada invariante never_together.
    """
    from functional_requirements import timed_sequence_steps, sequence_step_outputs

    analog = {binding['name']: binding['config'] for binding in analog_bindings or [] if binding['direction'] == 'output'}

    def expected(step, outputs):
        values = {output: output in (step or {}).get('outputs', []) for output in outputs}
        commands = {item['output']: item['value'] for item in (step or {}).get('analog_outputs', [])}
        for output in outputs:
            if output in analog:
                config = analog[output]
                eu = commands.get(output, config['fault_value'])
                values[output] = round(config['raw_min'] + (eu - config['engineering_min']) *
                    (config['raw_max'] - config['raw_min']) / (config['engineering_max'] - config['engineering_min']))
        return values

    cases: list[dict[str, Any]] = []
    for index, requirement in enumerate(detect_timed_sequences(functional_requirements), start=1):
        steps = timed_sequence_steps(requirement)
        all_outputs = list(dict.fromkeys(output for step in steps for output in sequence_step_outputs(step)))
        start_mode = timed_sequence_start_mode(requirement)
        start_input = requirement.get("start_input") or ("AUTO" if start_mode == "auto" else "I_Start")
        stop_input = requirement.get("stop_input") or "FALSE"
        repeat, _ = timed_sequence_repeat(requirement)
        if not steps:
            continue
        cases.append({
            "test_id": f"SEQ{index}_START",
            "description": "El disparo de la secuencia inicia la etapa 1.",
            "initial_state": expected(None, all_outputs),
            "input_sequence": [{start_input: True}],
            "expected_outputs": expected(steps[0], all_outputs),
            "safety_expectation": "Solo una etapa activa a la vez."
        })
        for position in range(1, len(steps)):
            previous = steps[position - 1]
            cases.append({
                "test_id": f"SEQ{index}_STEP{position + 1}",
                "description": f"Tras {previous['duration'] or previous['advance_on']} la secuencia pasa a la etapa {position + 1}.",
                "initial_state": expected(previous, all_outputs),
                "input_sequence": [{"wait": previous["duration"]} if previous["duration"] else {previous["advance_on"]: True}],
                "expected_outputs": expected(steps[position], all_outputs),
                "safety_expectation": "La transicion entre etapas es exclusiva."
            })
        if repeat in (SEQUENCE_REPEAT_ONCE, SEQUENCE_REPEAT_CONTINUOUS):
            final = steps[-1]
            cases.append({
                "test_id": f"SEQ{index}_{'CYCLE' if repeat == SEQUENCE_REPEAT_CONTINUOUS else 'END'}",
                "description": ("Tras la ultima etapa la secuencia vuelve a la etapa 1." if repeat == SEQUENCE_REPEAT_CONTINUOUS
                                else "Tras la ultima etapa la secuencia termina: todas sus salidas quedan apagadas."),
                "initial_state": expected(final, all_outputs),
                "input_sequence": [{"wait": final["duration"]} if final["duration"] else {final["advance_on"]: True}],
                "expected_outputs": expected(steps[0] if repeat == SEQUENCE_REPEAT_CONTINUOUS else None, all_outputs),
                "safety_expectation": "Estado final seguro y definido; sin rearranque sin un nuevo disparo."
            })
        cases.append({
            "test_id": f"SEQ{index}_STOP",
            "description": "Stop apaga todas las salidas de la secuencia.",
            "initial_state": expected(steps[-1], all_outputs),
            "input_sequence": [{stop_input: True}],
            "expected_outputs": expected(None, all_outputs),
            "safety_expectation": f"{stop_input} tiene prioridad sobre {start_input}."
        })
    for position, requirement in enumerate(functional_requirements, start=1):
        if str(requirement.get("type", "")) == "never_together":
            outputs = [o for o in requirement.get("outputs") or [] if isinstance(o, str)]
            cases.append({
                "test_id": f"NEVER_TOGETHER_{position}",
                "description": "Las salidas indicadas nunca pueden estar activas a la vez.",
                "initial_state": {},
                "input_sequence": [],
                "expected_outputs": {},
                "safety_expectation": f"Nunca simultaneamente: {', '.join(outputs)}."
            })
    cases.extend(_primitive_test_cases(functional_requirements))
    return cases


def _primitive_test_cases(functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Casos genericos de las primitivas no secuenciales (salida condicionada, histeresis, enclavamiento, bloqueo)."""
    from functional_requirements import conditional_outputs, force_offs, hysteresis_switches, latches

    cases: list[dict[str, Any]] = []
    for index, entry in enumerate(conditional_outputs(functional_requirements), start=1):
        cases.append({"test_id": f"COND{index}", "initial_state": {o: False for o in entry["outputs"]},
                      "description": (f"Al cumplirse {entry['condition']} las salidas se activan durante {entry['duration']}."
                                      if entry["duration"] else f"Las salidas siguen a la condicion {entry['condition']}."),
                      "input_sequence": [{entry["condition"]: True}], "expected_outputs": {o: True for o in entry["outputs"]},
                      "safety_expectation": "Sin la condicion las salidas quedan apagadas."})
    for index, switch in enumerate(hysteresis_switches(functional_requirements), start=1):
        cases.append({"test_id": f"HYST{index}", "initial_state": {switch["output"]: False},
                      "description": f"{switch['output']} conmuta con histeresis sobre {switch['input']}.",
                      "input_sequence": [], "expected_outputs": {},
                      "safety_expectation": "Entre ambos umbrales la salida conserva su estado (sin oscilar)."})
    for index, entry in enumerate(latches(functional_requirements), start=1):
        cases.append({"test_id": f"LATCH{index}", "initial_state": {o: False for o in entry["outputs"]},
                      "description": f"{entry['set']} enclava las salidas y {entry['reset']} las libera.",
                      "input_sequence": [{entry["set"]: True}, {entry["set"]: False}],
                      "expected_outputs": {o: True for o in entry["outputs"]},
                      "safety_expectation": f"{entry['reset']} tiene prioridad sobre {entry['set']}."})
    for index, entry in enumerate(force_offs(functional_requirements), start=1):
        cases.append({"test_id": f"FORCE_OFF{index}", "initial_state": {o: True for o in entry["outputs"]},
                      "description": f"{entry['condition']} apaga de inmediato las salidas.",
                      "input_sequence": [{entry["condition"]: True}], "expected_outputs": {o: False for o in entry["outputs"]},
                      "safety_expectation": "El bloqueo prevalece sobre cualquier otra contribucion."})
    for index, entry in enumerate((r for r in functional_requirements if r.get("type") == "analog_output"), start=1):
        cases.append({"test_id": f"ANALOG{index}", "initial_state": {}, "input_sequence": [],
                      "description": f"{entry['output']} aplica {entry.get('value')} {entry.get('unit', '')} con calibración confirmada.",
                      "expected_outputs": {},
                      "safety_expectation": "Sin habilitación o con emergencia aplica el valor ante fallo configurado."})
    return cases


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

    # MSS_03 solo debe esperar alarm_output si esa clave fue realmente solicitada (ver
    # OPTIONAL_PARAMETER_KEYS) - motor_output=False siempre se mantiene, es la parte CORE del
    # caso. MSS_04 (reset posterior a emergencia) prueba EXCLUSIVAMENTE la funcionalidad de reset:
    # si reset_input no fue pedido, ese caso no tiene nada que probar y se omite por completo en
    # vez de referenciar el tag fisico por defecto "I_Reset" que ya no se declara.
    motor_start_stop_mss_03_outputs: dict[str, Any] = {motor_output: False}
    if "alarm_output" in parameters:
        motor_start_stop_mss_03_outputs[alarm_output] = True
    motor_start_stop_cases = [
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
            "expected_outputs": motor_start_stop_mss_03_outputs,
            "safety_expectation": "La emergencia debe prevalecer sobre cualquier orden."
        }
    ]
    if "reset_input" in parameters:
        motor_start_stop_cases.append({
            "test_id": "MSS_04",
            "description": "Reset posterior a emergencia sin autoarranque.",
            "initial_state": {alarm_output: True} if "alarm_output" in parameters else {},
            "input_sequence": [{reset_input: True}],
            "expected_outputs": (
                {motor_output: False, alarm_output: False} if "alarm_output" in parameters
                else {motor_output: False}
            ),
            "safety_expectation": "El motor no debe reencender solo."
        })
    motor_start_stop_cases.append({
        "test_id": "MSS_05",
        "description": "Start y Stop simultaneos deben privilegiar Stop.",
        "initial_state": {motor_output: False},
        "input_sequence": [{start_input: True, stop_input: True}],
        "expected_outputs": {motor_output: False},
        "safety_expectation": "No debe existir arranque ambiguo."
    })

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
        "INT_MOTOR_START_STOP": motor_start_stop_cases,
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
                "description": "La emergencia desenergiza las salidas criticas.",
                "initial_state": {motor_output: True, **({output: True} if "output" in parameters else {})},
                "input_sequence": [{emergency_input: True}],
                "expected_outputs": {motor_output: False, **({output: False} if "output" in parameters else {}),
                                     **({alarm_output: True} if "alarm_output" in parameters else {})},
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
        "INT_AUTO_CYCLE",
        "INT_PID_SUPERVISOR",
        "INT_SPEED_SELECTION"
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
    if name.startswith("M_") and name.endswith("_CV"):
        # Valor actual EXPLICITO de un contador (salida CV de su CTU): mismo tipo que CV de CTU_INT.
        return {"type": "INT", "class": "internal"}
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


def _required_resources(
    semantic_output: dict[str, Any],
    io_map: dict[str, Any],
    functional_requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Recursos que la IR exige para esta semantica (contrato del intent con sus defaults, requisitos de
    catalogo, programa compuesto). UNICA fuente: la usan build_project_ir y, en Modo Normal, la resolucion
    de recursos previa (required_external_resources), de modo que el IOAllocator ve EXACTAMENTE los mismos
    nombres que la IR exigira despues.
    """
    intent_id = semantic_output.get("intent_id", "INT_UNKNOWN")
    parameters = semantic_output.get("parameters", {})
    # Dos formas conviven en el mismo parametro: entradas de catalogo ({"type": "run_pilot"}),
    # que se resuelven a tags fijos, y variables funcionales ad-hoc con nombre propio
    # ({"name": "Level_SP", "type": "REAL"}), que sigue resolviendo _resolve_functional_variables.
    catalog_requirements = [r for r in functional_requirements if classify_functional_requirement(r) == CLASS_CATALOG]
    ad_hoc_requirements = [r for r in functional_requirements if classify_functional_requirement(r) != CLASS_CATALOG]

    # Algunos tipos de catalogo (PID: set_level_setpoint, enable_pid, etc.) tambien implican
    # variables funcionales de proceso SIN prefijo I_/Q_/M_ (Level_SP, PID_Enable, Auto_Mode...).
    # Se expanden aqui a la forma ad-hoc existente {"name":..., "type":...} para que las resuelva
    # _resolve_functional_variables exactamente igual que cualquier otra variable funcional - sin
    # convertirlas nunca en recursos fisicos ni en recursos internos autogenerados por prefijo.
    existing_ad_hoc_names = {str(r.get("name", "")) for r in ad_hoc_requirements}
    for requirement in catalog_requirements:
        for name, iec_type in get_functional_requirement_process_variables(requirement).items():
            if name in existing_ad_hoc_names:
                continue
            ad_hoc_requirements.append({"name": name, "type": iec_type, "semantic_role": requirement.get("type", "")})
            existing_ad_hoc_names.add(name)

    # Comando multi-actor genuino (dos o mas motor_start_latch independientes - ver
    # code_generator.detect_multi_actor_motor_targets/_generate_multi_actor_motor_body): ningun
    # intent_id del catalogo representa esto por si solo, asi que intent_id puede legitimamente
    # no tener plantilla (INT_UNKNOWN) sin que eso sea un error - TODAS las variables que necesita
    # el programa llegan via functional_requirement_tags mas abajo, no via el intent base.
    if detect_composed_program(functional_requirements, intent_id):
        # El compositor genera TODO el programa desde sus requisitos, no desde la plantilla
        # del intent. Igual que effective_semantics, no heredar salidas/defaults que no usa.
        required_variables = []
    elif has_composable_program(functional_requirements, intent_id):
        try:
            required_variables = get_required_variables_for_intent(intent_id, parameters)
        except ValueError as error:
            if INTENT_TEMPLATE_NOT_IMPLEMENTED not in str(error):
                raise
            required_variables = []
    else:
        required_variables = get_required_variables_for_intent(intent_id, parameters)
    functional_requirement_tags: list[str] = []
    parameter_resources: list[dict[str, Any]] = []  # traza: recurso de requisito <- parametro efectivo
    if detect_composed_program(functional_requirements, intent_id):
        # La emergencia del compositor llega por `parameters` (semantic_repair la deja en "FALSE" si
        # el banco no la tiene): declararla si es un tag real, sin plantilla de intent que la aporte.
        emergency_tag = str(parameters.get("emergency_input") or "")
        if emergency_tag.startswith("I_"):
            functional_requirement_tags.append(emergency_tag)
    if detect_composed_program(functional_requirements, intent_id):
        # Programa compuesto: modos, ordenes manuales, permisivos, supervisiones y alarmas declaran
        # sus tags por instancia (ver functional_requirements.composition_tags).
        for tag in composition_tags(functional_requirements):
            if tag not in functional_requirement_tags:
                functional_requirement_tags.append(tag)
    else:
        # Mismos parametros EFECTIVOS que usa el generador: un recurso dependiente de parametro resuelto
        # a literal seguro (p.ej. emergency_input = FALSE) no se declara ni se exige.
        provenance = semantic_output.get("parameter_provenance") if isinstance(semantic_output.get("parameter_provenance"), dict) else None
        for requirement in catalog_requirements:
            for entry in resolve_parameter_resources(requirement, parameters, provenance):
                parameter_resources.append({"type": requirement.get("type"), **entry})
            for tag in get_functional_requirement_tags(requirement, parameters, provenance):
                if tag not in functional_requirement_tags:
                    functional_requirement_tags.append(tag)
    required_variables = list(dict.fromkeys(required_variables + functional_requirement_tags))
    product_start_edges = []
    if semantic_output.get("interaction_profile") == "normal":
        occupied = {str(v['name']).casefold() for v in io_map.get('variables', [])}
        occupied.update(str(name).casefold() for name in required_variables)
        occupied.update(str(entry.get('name', '')).casefold() for entry in ad_hoc_requirements)
        def reserve_start_names(names):
            for name in names.values():
                if name.casefold() in occupied or len(name) > 100:
                    raise ValueError(f'START_SYMBOL_CONFLICT: auxiliar de arranque ocupado o demasiado largo: {name}')
                occupied.add(name.casefold())
        if detect_composed_program(functional_requirements, intent_id):
            from io_allocator import _candidate_role_keys
            from functional_requirements import latches, latch_start_edge_names, single_latch_start_signal
            def is_start_input(variable):
                if variable.get('class') != 'input' or str(variable.get('type', '')).upper() != 'BOOL':
                    return False
                role = str(variable.get('semantic_role') or '').strip()
                if role:
                    # An explicit sensor/device role takes precedence over a misleading tag name.
                    role_keys = _candidate_role_keys({'name': '', 'semantic_role': role.replace('_', ' ')})
                    return 'start' in role_keys or role.upper() in {'START_BUTTON', 'PUSHBUTTON_START'}
                return any('start' in key.split() for key in _candidate_role_keys(variable))
            starts = {v['name'] for v in io_map.get('variables', [])
                      if is_start_input(v)}
            used_starts = {single_latch_start_signal(entry['set']) for entry in latches(functional_requirements)} & starts
            for index, signal in enumerate(sorted(used_starts), 1):
                names = latch_start_edge_names(f'M_ProductStart{index}')
                reserve_start_names(names)
                product_start_edges.append({'signal': signal, **names})
                required_variables = list(dict.fromkeys(required_variables + list(names.values())))
        if intent_id == 'INT_MOTOR_LATCH' and not detect_composed_program(functional_requirements, intent_id):
            from functional_requirements import latch_start_edge_names
            names = latch_start_edge_names(parameters.get('run_latch') or 'M_RunLatch')
            reserve_start_names(names)
            required_variables = list(dict.fromkeys(required_variables + list(names.values())))
        # Modo Normal: cada instancia CTU publica sus salidas EXPLICITAS (alcanzado / valor) como variables propias;
        # la logica las usa a ellas, nunca miembros de la instancia (ver functional_requirements.counter_output_names).
        from functional_requirements import counter_output_names

        for name in [n for n in required_variables if n.startswith("C_")]:
            outputs = counter_output_names(name)
            required_variables = list(dict.fromkeys(required_variables + [outputs["done"], outputs["value"]]))

    io_index = build_io_map_index(io_map)

    # Banco sin paro de emergencia cableado al PLC (seccion "regla definitiva" - I_Emergency solo
    # puede existir si el mapa activo ya la tiene, o el usuario la pidio explicitamente, en cuyo
    # caso MAP_CONFIG ya la habria agregado al mapa ANTES de llegar aqui). Defensa en profundidad:
    # semantic_repair.strip_unavailable_emergency_reference ya evita que "I_Emergency" llegue hasta
    # aqui por la via normal (parse_command), pero cualquier semantic_output construido por otro
    # camino (un intent_specs/parameter_overrides que la agrega por defecto mas arriba, sin pasar
    # por el repair) nunca debe terminar exigiendo un recurso fisico que el banco activo no tiene.
    if "I_Emergency" not in io_index:
        required_variables = [name for name in required_variables if name != "I_Emergency"]

    return {"catalog_requirements": catalog_requirements, "ad_hoc_requirements": ad_hoc_requirements,
            "required_variables": required_variables, "functional_requirement_tags": functional_requirement_tags,
            "parameter_resources": parameter_resources, "io_index": io_index,
            'product_start_edges': product_start_edges}


def required_external_resources(semantic_output: dict[str, Any], io_map: dict[str, Any]) -> list[str]:
    """Recursos EXTERNOS (I_/Q_/AI_/AO_) que build_project_ir exigira en el mapa para esta semantica."""
    from pid_control import has_native_pid, resolve_pid_loops
    requirements = list(semantic_output.get('functional_requirements') or [])
    if has_native_pid(requirements):
        loops = resolve_pid_loops(requirements,io_map,'SIEMENS_SCL_V18')
        return list(dict.fromkeys(n for loop in loops for n in [loop.process_input,loop.control_output,*loop.resources.values()] if n))
    resolution = resolve_functional_resources(requirements)
    if resolution["errors"]:
        return []
    try:
        required = _required_resources(semantic_output, io_map, resolution["requirements"])["required_variables"]
    except ValueError:
        return []  # sin plantilla ni composicion: lo informa la validacion, no hay recursos que resolver
    return [name for name in required if name.startswith(EXTERNAL_PREFIXES)]


def build_project_ir(
    semantic_output: dict[str, Any],
    io_map: dict[str, Any],
    target_platform: str,
    project_name: str | None = None,
    functional_requirements: list[dict[str, Any]] | None = None
) -> PLCProjectIR:
    from pid_control import has_native_pid, build_pid_project_ir
    native_semantic = {**semantic_output}
    if functional_requirements is not None:
        native_semantic['functional_requirements'] = functional_requirements
    from control_strategy import control_consistency_errors
    control_errors = control_consistency_errors(native_semantic, io_map)
    if control_errors:
        raise ValueError('; '.join(control_errors))
    if has_native_pid(native_semantic.get('functional_requirements') or []):
        return build_pid_project_ir(native_semantic,io_map,target_platform,project_name)
    intent_id = semantic_output.get("intent_id", "INT_UNKNOWN")
    command_text = semantic_output.get("command_text", "")
    case_id = semantic_output.get("case_id") or "NOCASE"
    parameters = semantic_output.get("parameters", {})

    # functional_requirements puede llegar explicito (project_packager.py) o, si no, se toma del
    # semantic_output directamente - asi el parametro queda activado de punta a punta sin exigir
    # que cada llamador lo repita.
    if functional_requirements is None:
        functional_requirements = list(semantic_output.get("functional_requirements") or [])

    # Todo recurso funcional debe ser identificable y nombrable ANTES de construir la IR: las
    # referencias {role, actor, kind} sin nombre reciben su tag canonico; lo no identificable o un
    # comportamiento no soportado se detiene aqui con un error estructurado (codigo + ruta JSON),
    # nunca mas tarde como "variable funcional sin nombre".
    resolution = resolve_functional_resources(functional_requirements)
    if resolution["errors"]:
        raise FunctionalResourceError(resolution["errors"])
    functional_requirements = resolution["requirements"]

    resources = _required_resources(semantic_output, io_map, functional_requirements)
    catalog_requirements = resources["catalog_requirements"]
    ad_hoc_requirements = resources["ad_hoc_requirements"]
    required_variables = resources["required_variables"]
    functional_requirement_tags = resources["functional_requirement_tags"]
    parameter_resources = resources["parameter_resources"]
    io_index = resources["io_index"]

    external_names = [name for name in required_variables if name.startswith(EXTERNAL_PREFIXES)]
    internal_names = [name for name in required_variables if name.startswith(INTERNAL_PREFIXES)]

    missing_variables = [name for name in external_names if name not in io_index]
    if missing_variables:
        raise ValueError(
            "FUNCTIONAL_RESOURCE_UNRESOLVED: Recurso externo no autorizado/no existente en el mapa PLC: "
            + ", ".join(missing_variables)
        )

    external_variables = [_build_variable_from_entry(io_index[name], source="plc_map") for name in external_names]
    internal_variables, generated_internal = _resolve_internal_resources(internal_names, io_index)
    functional_variables, generated_functional = _resolve_functional_variables(
        ad_hoc_requirements,
        io_index,
        already_resolved_names={variable.name for variable in external_variables + internal_variables}
    )

    variables = external_variables + internal_variables + functional_variables
    analog_bindings, functional_requirements = prepare_analog_bindings(
        functional_requirements, io_index, required_variables,
        set(io_index) | {variable.name for variable in variables})
    analog_variables = []
    for binding in analog_bindings:
        specs = [("engineering_variable", "REAL", "0.0"), ("valid_variable", "BOOL", "FALSE")]
        if binding['direction'] == 'output':
            specs.append(("raw_variable", "REAL", "0.0"))
        for key, data_type, initial in specs:
            analog_variables.append(_build_variable_from_entry({
                "name": binding[key], "type": data_type, "class": "internal", "location": "",
                "initial_value": initial, "description": f"Conversión analógica: {binding['name']}"},
                source="generated_analog"))
    variables += analog_variables
    function_blocks = _build_function_blocks(variables, parameters)
    safety_rules = _load_safety_rules()
    try:
        test_cases = build_test_cases_for_intent(intent_id, parameters)
    except ValueError as error:
        # Programa compuesto (INT_UNKNOWN + primitivas componibles): casos derivados de su estructura.
        if INTENT_TEMPLATE_NOT_IMPLEMENTED not in str(error) or not has_composable_program(functional_requirements, intent_id):
            raise
        test_cases = []
    if detect_composed_program(functional_requirements, intent_id):
        test_cases = test_cases + build_test_cases_for_composition(functional_requirements, analog_bindings)

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
        'product_start_edges': resources.get('product_start_edges', []),
        "semantic_output": dict(semantic_output),
        "parameters": dict(parameters),
        "required_variables": list(required_variables),
        "authorized_variables": sorted(set(io_index.keys()) | {variable.name for variable in variables}),
        "missing_variables": missing_variables,
        "platform_requested": normalized_target,
        "generated_internal_variables": [variable.to_dict() for variable in generated_internal],
        "generated_functional_variables": [variable.to_dict() for variable in generated_functional],
        "functional_requirements": list(functional_requirements),
        "analog_bindings": analog_bindings,
        "generated_analog_variables": [variable.to_dict() for variable in analog_variables],
        "functional_requirement_tags": functional_requirement_tags,
        # Recursos de requisito dependientes de parametros: valor efectivo, resolucion y procedencia.
        "functional_requirement_parameter_resources": parameter_resources
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
