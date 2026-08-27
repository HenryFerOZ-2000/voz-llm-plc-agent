from __future__ import annotations

from pathlib import Path

from ir_builder import build_project_ir
from plc_maps.profiles import (
    HARDWARE_MAP_NAME,
    SIMULATION_MAP_NAME,
    apply_profile_filter,
    compute_readiness,
    profile_readiness_summary
)
from plc_maps.store import create_plc_map, save_plc_map


def _sample_io_map(io_map: dict) -> dict:
    """A representative slice of the real io_map (externals + internals) for filter tests."""
    names = {"I_Start", "I_Stop", "Q_Motor_Enable", "M_RunLatch", "T_DelayStart"}
    return {
        "naming_convention": io_map.get("naming_convention", {}),
        "variables": [v for v in io_map.get("variables", []) if v.get("name") in names]
    }


def test_compute_readiness_reports_missing_variables() -> None:
    ready, missing = compute_readiness(["I_Start", "I_Speed_Low"], {"I_Start", "I_Stop"})
    assert ready is False
    assert missing == ["I_Speed_Low"]


def test_compute_readiness_all_present() -> None:
    ready, missing = compute_readiness(["I_Start"], {"I_Start", "I_Stop"})
    assert ready is True
    assert missing == []


def test_apply_profile_filter_none_returns_same_object(io_map: dict) -> None:
    assert apply_profile_filter(io_map, None) is io_map


def test_apply_profile_filter_restricts_external_keeps_internal(io_map: dict) -> None:
    sample = _sample_io_map(io_map)
    profile = {"allowed_variables": ["I_Start"]}  # Q_Motor_Enable, I_Stop not authorized
    filtered = apply_profile_filter(sample, profile)
    names = {v["name"] for v in filtered["variables"]}
    assert "I_Start" in names
    assert "I_Stop" not in names
    assert "Q_Motor_Enable" not in names
    # internal resources are never filtered by a profile
    assert "M_RunLatch" in names
    assert "T_DelayStart" in names


def test_ir_builder_still_autogenerates_internal_resources_with_profile_filter(io_map: dict) -> None:
    # Perfil D07-like: solo I_Start/I_Stop/Q_Motor_Enable externas autorizadas; T_DelayStart
    # no esta en el mapa reducido y debe generarse automaticamente igual que sin perfil.
    minimal_map = {
        "naming_convention": io_map.get("naming_convention", {}),
        "variables": [
            v for v in io_map.get("variables", [])
            if v.get("name") in {"I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"}
        ]
    }
    profile = {"allowed_variables": ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"]}
    filtered = apply_profile_filter(minimal_map, profile)

    semantic_output = {
        "intent_id": "INT_DELAYED_START",
        "case_id": "TEST",
        "command_text": "test",
        "parameters": {
            "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
            "motor_output": "Q_Motor_Enable", "timer": "T_DelayStart"
        },
        "recognized_tags": ["I_Start", "I_Stop", "Q_Motor_Enable"]
    }

    project_ir = build_project_ir(semantic_output, filtered, "SIEMENS_SCL_V18")
    variables_by_name = {v.name: v for v in project_ir.pou.variables}
    assert variables_by_name["T_DelayStart"].source == "generated_internal"


def test_profile_readiness_summary_missing_hardware(tmp_path: Path) -> None:
    sim_path = create_plc_map(tmp_path, name=SIMULATION_MAP_NAME)
    save_plc_map(
        sim_path,
        [
            {"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0"},
            {"name": "I_Speed_Low", "class": "input", "type": "BOOL", "location": "%IX1.1"}
        ]
    )
    hw_path = create_plc_map(tmp_path, name=HARDWARE_MAP_NAME)
    save_plc_map(hw_path, [{"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0"}])

    profile = {"allowed_variables": ["I_Start", "I_Speed_Low"]}
    result = profile_readiness_summary(tmp_path, profile)
    assert result["simulation_ready"] is True
    assert result["hardware_ready"] is False
    assert result["missing_hardware_variables"] == ["I_Speed_Low"]


def test_profile_readiness_summary_handles_missing_reference_maps(tmp_path: Path) -> None:
    profile = {"allowed_variables": ["I_Start"]}
    result = profile_readiness_summary(tmp_path, profile)
    assert result["simulation_ready"] is False
    assert result["hardware_ready"] is False
