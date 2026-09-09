from __future__ import annotations

import pytest

from ir_builder import build_project_ir
from semantic_parser import parse_command


def test_ir_generation_contains_required_motor_variables(io_map: dict) -> None:
    semantic_output = parse_command("Haz que el motor se encienda con Start y se apague con Stop")
    project_ir = build_project_ir(semantic_output, io_map, "CODESYS_ST")
    variable_names = [variable.name for variable in project_ir.pou.variables]
    assert "I_Start" in variable_names
    assert "I_Stop" in variable_names
    assert "I_Emergency" in variable_names
    assert "Q_Motor_Enable" in variable_names


def _minimal_map(io_map: dict, names: set[str]) -> dict:
    """Build a lean map containing only the given external variable names (no internals)."""
    return {
        "naming_convention": io_map.get("naming_convention", {}),
        "variables": [
            variable for variable in io_map.get("variables", [])
            if variable.get("name") in names
        ]
    }


def _semantic_output(intent_id: str, parameters: dict, recognized_tags: list[str]) -> dict:
    return {
        "intent_id": intent_id,
        "case_id": "TEST",
        "command_text": f"comando de prueba para {intent_id}",
        "parameters": parameters,
        "recognized_tags": recognized_tags
    }


def test_delayed_start_generates_timer_without_requiring_it_in_map(io_map: dict) -> None:
    # Caso A: mapa minimalista sin T_DelayStart; INT_DELAYED_START lo necesita como interno.
    minimal_map = _minimal_map(io_map, {"I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"})
    semantic_output = _semantic_output(
        "INT_DELAYED_START",
        {"trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency", "motor_output": "Q_Motor_Enable", "timer": "T_DelayStart"},
        ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable", "T_DelayStart"]
    )

    project_ir = build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")

    variables_by_name = {v.name: v for v in project_ir.pou.variables}
    assert "T_DelayStart" in variables_by_name
    assert variables_by_name["T_DelayStart"].data_type == "TON"
    assert variables_by_name["T_DelayStart"].source == "generated_internal"
    assert [v["name"] for v in project_ir.metadata["generated_internal_variables"]] == ["T_DelayStart"]


def test_delayed_stop_autogenerates_run_latch_stop_delay_active_and_timer(io_map: dict) -> None:
    # INT_DELAYED_STOP requiere M_RunLatch, M_StopDelayActive y T_StopDelay como internos -
    # ninguno esta en el mapa minimalista y ninguno debe requerir autorizacion del usuario.
    minimal_map = _minimal_map(io_map, {"I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"})
    semantic_output = _semantic_output(
        "INT_DELAYED_STOP",
        {
            "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
            "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch",
            "stop_delay_active": "M_StopDelayActive", "timer": "T_StopDelay"
        },
        ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"]
    )

    project_ir = build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")

    variables_by_name = {v.name: v for v in project_ir.pou.variables}
    generated_names = {v["name"] for v in project_ir.metadata["generated_internal_variables"]}
    assert generated_names == {"M_RunLatch", "M_StopDelayActive", "T_StopDelay"}
    assert variables_by_name["T_StopDelay"].source == "generated_internal"
    assert variables_by_name["T_StopDelay"].data_type == "TON"
    assert variables_by_name["M_RunLatch"].source == "generated_internal"
    assert variables_by_name["M_RunLatch"].data_type == "BOOL"
    # el mapa base no se modifica: build_project_ir es puro
    assert {v.get("name") for v in minimal_map["variables"]} == {"I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"}


def test_cyclic_motor_generates_multiple_internal_resources(io_map: dict) -> None:
    # Caso B: una logica que requiere varios recursos internos (M_Step, R_CycleStart, 2 timers).
    minimal_map = _minimal_map(io_map, {"I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"})
    semantic_output = _semantic_output(
        "INT_CYCLIC_MOTOR",
        {
            "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
            "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch", "step_memory": "M_Step",
            "start_edge": "R_CycleStart", "on_timer": "T_CycleOn", "off_timer": "T_CycleOff"
        },
        ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"]
    )

    project_ir = build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")

    generated_names = {v["name"] for v in project_ir.metadata["generated_internal_variables"]}
    assert generated_names == {"M_RunLatch", "M_Step", "R_CycleStart", "T_CycleOn", "T_CycleOff"}
    # el mapa minimalista original no se modifico (build_project_ir es puro, sin I/O a disco)
    assert {v.get("name") for v in minimal_map["variables"]} == {"I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"}


def test_counter_pulses_generates_counter_and_edge_detector(io_map: dict) -> None:
    # Caso C: mapa con sensor y salida, sin C_PulseCount/R_SensorPulse.
    minimal_map = _minimal_map(io_map, {"I_Sensor1", "I_Reset", "I_Emergency", "Q_Alarm"})
    semantic_output = _semantic_output(
        "INT_COUNTER_PULSES",
        {
            "pulse_input": "I_Sensor1", "reset_input": "I_Reset", "emergency_input": "I_Emergency",
            "output": "Q_Alarm", "counter": "C_PulseCount", "edge_detector": "R_SensorPulse", "preset": 5
        },
        ["I_Sensor1", "I_Reset", "I_Emergency", "Q_Alarm"]
    )

    project_ir = build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")

    variables_by_name = {v.name: v for v in project_ir.pou.variables}
    assert variables_by_name["C_PulseCount"].data_type == "CTU"
    assert variables_by_name["C_PulseCount"].source == "generated_internal"
    assert variables_by_name["R_SensorPulse"].data_type == "R_TRIG"


def test_missing_external_resource_stops_generation(io_map: dict) -> None:
    # Caso D: el mapa no tiene I_Sensor1, requerido como recurso externo.
    minimal_map = _minimal_map(io_map, {"I_Reset", "I_Emergency", "Q_Alarm"})
    semantic_output = _semantic_output(
        "INT_COUNTER_PULSES",
        {"pulse_input": "I_Sensor1", "reset_input": "I_Reset", "emergency_input": "I_Emergency", "output": "Q_Alarm"},
        ["I_Reset", "I_Emergency", "Q_Alarm"]
    )

    with pytest.raises(ValueError, match="Recurso externo no autorizado"):
        build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")


def test_functional_variable_is_created_when_absent(io_map: dict) -> None:
    # Caso E: mapa con Level_PV/Q_Pump, sin Level_SP; se solicita como variable funcional.
    minimal_map = {
        "naming_convention": io_map.get("naming_convention", {}),
        "variables": [
            {"name": "Level_PV", "class": "input", "type": "INT", "location": "%IW0", "description": "Nivel medido."},
            {"name": "Q_Pump", "class": "output", "type": "BOOL", "location": "%QX0.0", "description": "Bomba."},
            {"name": "I_Emergency", "class": "input", "type": "BOOL", "location": "%IX0.2", "description": "Emergencia."}
        ]
    }
    semantic_output = _semantic_output("INT_DIRECT_OUTPUT", {"trigger_input": "I_Emergency", "emergency_input": "I_Emergency", "output": "Q_Pump"}, ["I_Emergency", "Q_Pump"])

    project_ir = build_project_ir(
        semantic_output, minimal_map, "SIEMENS_SCL_V18",
        functional_requirements=[{"name": "Level_SP", "type": "REAL", "semantic_role": "setpoint"}]
    )

    generated = project_ir.metadata["generated_functional_variables"]
    assert [v["name"] for v in generated] == ["Level_SP"]
    variables_by_name = {v.name: v for v in project_ir.pou.variables}
    assert variables_by_name["Level_SP"].data_type == "REAL"
    assert variables_by_name["Level_SP"].source == "generated_functional"


def test_functional_variable_is_reused_not_duplicated(io_map: dict) -> None:
    # Caso F: Level_SP ya existe en el mapa (simulando que ya se persistio antes); debe reutilizarse.
    map_with_setpoint = {
        "naming_convention": io_map.get("naming_convention", {}),
        "variables": [
            {"name": "Level_PV", "class": "input", "type": "INT", "location": "%IW0", "description": "Nivel medido."},
            {"name": "Q_Pump", "class": "output", "type": "BOOL", "location": "%QX0.0", "description": "Bomba."},
            {"name": "I_Emergency", "class": "input", "type": "BOOL", "location": "%IX0.2", "description": "Emergencia."},
            {"name": "Level_SP", "class": "internal", "type": "REAL", "location": "", "description": "Setpoint de nivel."}
        ]
    }
    semantic_output = _semantic_output("INT_DIRECT_OUTPUT", {"trigger_input": "I_Emergency", "emergency_input": "I_Emergency", "output": "Q_Pump"}, ["I_Emergency", "Q_Pump"])

    project_ir = build_project_ir(
        semantic_output, map_with_setpoint, "SIEMENS_SCL_V18",
        functional_requirements=[{"name": "Level_SP", "type": "REAL", "semantic_role": "setpoint"}]
    )

    assert project_ir.metadata["generated_functional_variables"] == []
    variables_by_name = {v.name: v for v in project_ir.pou.variables}
    assert variables_by_name["Level_SP"].source == "plc_map"

    with pytest.raises(ValueError, match="incompatible"):
        build_project_ir(
            semantic_output, map_with_setpoint, "SIEMENS_SCL_V18",
            functional_requirements=[{"name": "Level_SP", "type": "INT", "semantic_role": "setpoint"}]
        )


def test_legacy_map_with_explicit_internal_variables_still_works(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    # Caso G: el mapa real del proyecto ya declara T_StopDelay/M_RunLatch explicitamente;
    # deben reutilizarse desde el mapa (source="plc_map"), comportamiento identico al actual.
    semantic_output = parse_command("Apaga el motor 10 segundos despues de presionar Stop")
    project_ir = build_project_ir(semantic_output, io_map, "SIEMENS_SCL_V18")

    variables_by_name = {v.name: v for v in project_ir.pou.variables}
    assert variables_by_name["T_StopDelay"].source == "plc_map"
    assert variables_by_name["M_RunLatch"].source == "plc_map"
    assert project_ir.metadata["generated_internal_variables"] == []
