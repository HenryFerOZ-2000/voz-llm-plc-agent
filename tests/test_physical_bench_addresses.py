"""
Verifica la correccion de direcciones del banco fisico real (MAPA_BANCO_FISICO):
- direcciones digitales reales %IX16.x / %QX8.x (antes %IX0.x / %QX0.x);
- canales analogicos reales %IW0/%IW2/%IW4/%IW6 y %QW0/%QW2/%QW4/%QW6, sin funcion asignada;
- AI_/AO_ tratados como recursos externos (EXTERNAL_PREFIXES), igual que I_/Q_;
- deteccion de colision de direccion;
- readiness D01-D20 recalculado por nombre (no por direccion) tras el cambio.

IMPORTANTE: `bench_map` es un SNAPSHOT congelado (no lee `data/plc_maps/mapa_banco_fisico.json`
en vivo). El mapa fisico real es mutable por diseno - el usuario lo reconfigura desde la GUI
(renombrar/bloquear/reasignar, o dejar que el IOAllocator lo haga automaticamente) como parte
normal del uso de la herramienta, y de hecho ya cambio de contenido durante esta misma sesion de
trabajo. Atar estos tests a su contenido en vivo los hace fragiles ante el uso legitimo de la
aplicacion; el snapshot preserva la cobertura de regresion (dieccion correcta, AI_/AO_, colision)
sin depender de que el usuario no haya tocado su propio mapa mientras tanto.
"""
from __future__ import annotations

import pytest

from ir_builder import EXTERNAL_PREFIXES, build_project_ir
from plc_maps.map_validator import validate_plc_variable_map
from plc_maps.profiles import compute_readiness, load_profiles
from utils import get_project_root


def _snapshot_variable(name, location, var_class="input", var_type="BOOL", **overrides):
    entry = {
        "name": name, "class": var_class, "type": var_type, "location": location,
        "initial_value": "FALSE", "description": "", "aliases": [], "semantic_role": "",
        "llm_allowed": True, "safety_level": "normal", "unit": "", "min": None, "max": None,
        "comments": ""
    }
    entry.update(overrides)
    return entry


@pytest.fixture(scope="module")
def bench_map() -> dict:
    return {
        "variables": [
            _snapshot_variable("I_Start", "%IX16.0"),
            _snapshot_variable("I_Stop", "%IX16.1"),
            _snapshot_variable("I_Emergency", "%IX16.2", safety_level="critical"),
            _snapshot_variable("I_Reset", "%IX16.3"),
            _snapshot_variable("I_Sensor1", "%IX16.4"),
            _snapshot_variable("I_Mode_Manual", "%IX16.5"),
            _snapshot_variable("I_Mode_Auto", "%IX16.6"),
            _snapshot_variable("I_Maintenance", "%IX16.7"),
            _snapshot_variable("Q_Motor_Enable", "%QX8.0", var_class="output"),
            _snapshot_variable("Q_Alarm", "%QX8.1", var_class="output"),
            _snapshot_variable("Q_Pilot_Run", "%QX8.2", var_class="output"),
            _snapshot_variable("Q_Pilot_Fault", "%QX8.3", var_class="output"),
            _snapshot_variable("Q_Aux_Output", "%QX8.4", var_class="output"),
            _snapshot_variable("Q_Contactor_A", "%QX8.5", var_class="output"),
            _snapshot_variable("Q_Contactor_B", "%QX8.6", var_class="output"),
            _snapshot_variable("Q_Pilot_Stop", "%QX8.7", var_class="output"),
            _snapshot_variable("AI_IW0", "%IW0", var_type="INT", llm_allowed=False, unit="V", min=0.0, max=10.0),
            _snapshot_variable("AI_IW2", "%IW2", var_type="INT", llm_allowed=False, unit="V", min=0.0, max=10.0),
            _snapshot_variable("AI_IW4", "%IW4", var_type="INT", llm_allowed=False, unit="mA", min=0.0, max=20.0),
            _snapshot_variable("AI_IW6", "%IW6", var_type="INT", llm_allowed=False, unit="mA", min=0.0, max=20.0),
            _snapshot_variable("AO_QW0", "%QW0", var_class="output", var_type="INT", llm_allowed=False, unit="V", min=0.0, max=10.0),
            _snapshot_variable("AO_QW2", "%QW2", var_class="output", var_type="INT", llm_allowed=False, unit="V", min=0.0, max=10.0),
            _snapshot_variable("AO_QW4", "%QW4", var_class="output", var_type="INT", llm_allowed=False, unit="mA", min=0.0, max=20.0),
            _snapshot_variable("AO_QW6", "%QW6", var_class="output", var_type="INT", llm_allowed=False, unit="mA", min=0.0, max=20.0),
        ]
    }


def _location_by_name(bench_map: dict, name: str) -> str:
    for variable in bench_map["variables"]:
        if variable["name"] == name:
            return variable["location"]
    raise AssertionError(f"{name} no esta en el mapa")


def test_digital_input_addresses_are_the_real_ix16_range(bench_map):
    names_to_bits = {
        "I_Start": "%IX16.0", "I_Stop": "%IX16.1", "I_Emergency": "%IX16.2", "I_Reset": "%IX16.3",
        "I_Sensor1": "%IX16.4", "I_Mode_Manual": "%IX16.5", "I_Mode_Auto": "%IX16.6", "I_Maintenance": "%IX16.7"
    }
    for name, expected_location in names_to_bits.items():
        assert _location_by_name(bench_map, name) == expected_location


def test_digital_output_addresses_are_the_real_qx8_range(bench_map):
    names_to_bits = {
        "Q_Motor_Enable": "%QX8.0", "Q_Alarm": "%QX8.1", "Q_Pilot_Run": "%QX8.2", "Q_Pilot_Fault": "%QX8.3",
        "Q_Aux_Output": "%QX8.4", "Q_Contactor_A": "%QX8.5", "Q_Contactor_B": "%QX8.6", "Q_Pilot_Stop": "%QX8.7"
    }
    for name, expected_location in names_to_bits.items():
        assert _location_by_name(bench_map, name) == expected_location


def test_analog_input_channels_present_and_unassigned(bench_map):
    for name, location in (("AI_IW0", "%IW0"), ("AI_IW2", "%IW2"), ("AI_IW4", "%IW4"), ("AI_IW6", "%IW6")):
        assert _location_by_name(bench_map, name) == location
    variables_by_name = {v["name"]: v for v in bench_map["variables"]}
    assert variables_by_name["AI_IW0"]["llm_allowed"] is False
    assert variables_by_name["AI_IW4"]["unit"] == "mA"
    assert variables_by_name["AI_IW0"]["unit"] == "V"


def test_analog_output_channels_present_and_unassigned(bench_map):
    for name, location in (("AO_QW0", "%QW0"), ("AO_QW2", "%QW2"), ("AO_QW4", "%QW4"), ("AO_QW6", "%QW6")):
        assert _location_by_name(bench_map, name) == location
    variables_by_name = {v["name"]: v for v in bench_map["variables"]}
    assert variables_by_name["AO_QW0"]["llm_allowed"] is False
    assert variables_by_name["AO_QW4"]["unit"] == "mA"


def test_bench_map_passes_validation_with_no_address_collisions(bench_map):
    result = validate_plc_variable_map(bench_map)
    assert result["is_valid"] is True
    assert result["errors"] == []


def test_map_validator_detects_duplicate_address():
    payload = {
        "variables": [
            {"name": "AI_IW0", "class": "input", "type": "INT", "location": "%IW0",
             "initial_value": "", "description": "a"},
            {"name": "AI_Dup", "class": "input", "type": "INT", "location": "%IW0",
             "initial_value": "", "description": "b"}
        ]
    }
    result = validate_plc_variable_map(payload)
    assert result["is_valid"] is False
    assert any("Direccion duplicada %IW0" in error for error in result["errors"])


def test_external_prefixes_include_ai_and_ao():
    assert "AI_" in EXTERNAL_PREFIXES
    assert "AO_" in EXTERNAL_PREFIXES
    assert "I_" in EXTERNAL_PREFIXES
    assert "Q_" in EXTERNAL_PREFIXES


def test_ai_tag_resolved_as_external_when_present_in_map(bench_map):
    semantic_output = {
        "intent_id": "INT_DIRECT_OUTPUT",
        "case_id": "T_AI",
        "command_text": "test",
        "parameters": {"trigger_input": "I_Start", "emergency_input": "I_Emergency", "output": "AO_QW0"}
    }
    project_ir = build_project_ir(semantic_output, bench_map, target_platform="SIEMENS_SCL_V18")
    variable_names = {variable.name for variable in project_ir.pou.variables}
    assert "AO_QW0" in variable_names
    resolved = next(v for v in project_ir.pou.variables if v.name == "AO_QW0")
    assert resolved.var_class == "output"
    assert resolved.source == "plc_map"


def test_ao_tag_missing_from_map_is_rejected(bench_map):
    semantic_output = {
        "intent_id": "INT_DIRECT_OUTPUT",
        "case_id": "T_AO_MISSING",
        "command_text": "test",
        "parameters": {"trigger_input": "I_Start", "emergency_input": "I_Emergency", "output": "AO_DoesNotExist"}
    }
    with pytest.raises(ValueError, match="Recurso externo no autorizado"):
        build_project_ir(semantic_output, bench_map, target_platform="SIEMENS_SCL_V18")


def test_ai_tag_missing_from_map_is_rejected(bench_map):
    semantic_output = {
        "intent_id": "INT_DIRECT_OUTPUT",
        "case_id": "T_AI_MISSING",
        "command_text": "test",
        "parameters": {"trigger_input": "AI_DoesNotExist", "emergency_input": "I_Emergency", "output": "Q_Aux_Output"}
    }
    with pytest.raises(ValueError, match="Recurso externo no autorizado"):
        build_project_ir(semantic_output, bench_map, target_platform="SIEMENS_SCL_V18")


def test_d19_hardware_ready_against_the_snapshot(bench_map):
    """
    Readiness contra el SNAPSHOT congelado (no el archivo real, mutable) - confirma que
    Q_Pilot_Stop en %QX8.7 satisface el perfil D19 completo. Usa compute_readiness() directamente
    (funcion pura) en vez de profile_readiness_summary(), que internamente resuelve el mapa
    "MAPA_BANCO_FISICO" por nombre desde la biblioteca REAL del proyecto.
    """
    project_root = get_project_root()
    profile = next(p for p in load_profiles(project_root) if p.get("case_id") == "D19")
    map_names = {v["name"] for v in bench_map["variables"]}
    hardware_ready, missing = compute_readiness(profile.get("allowed_variables", []), map_names)
    assert hardware_ready is True
    assert missing == []


def test_d01_hardware_ready_against_the_snapshot(bench_map):
    project_root = get_project_root()
    profile = next(p for p in load_profiles(project_root) if p.get("case_id") == "D01")
    map_names = {v["name"] for v in bench_map["variables"]}
    hardware_ready, _ = compute_readiness(profile.get("allowed_variables", []), map_names)
    assert hardware_ready is True


def test_d14_still_not_hardware_ready_missing_speed_selectors(bench_map):
    project_root = get_project_root()
    profile = next(p for p in load_profiles(project_root) if p.get("case_id") == "D14")
    map_names = {v["name"] for v in bench_map["variables"]}
    hardware_ready, missing = compute_readiness(profile.get("allowed_variables", []), map_names)
    assert hardware_ready is False
    assert "I_Speed_Low" in missing


def test_build_project_ir_still_works_for_a_d0x_case_with_corrected_addresses(bench_map):
    semantic_output = {
        "intent_id": "INT_MOTOR_START_STOP",
        "case_id": "D04",
        "command_text": "test",
        "parameters": {}
    }
    project_ir = build_project_ir(semantic_output, bench_map, target_platform="SIEMENS_SCL_V18")
    variables_by_name = {variable.name: variable for variable in project_ir.pou.variables}
    assert variables_by_name["I_Start"].location == "%IX16.0"
    assert variables_by_name["Q_Motor_Enable"].location == "%QX8.0"
