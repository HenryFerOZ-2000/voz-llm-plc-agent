"""Regression: program resources survive provisional I/O allocation (no API/TIA)."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

import gui
from io_allocator import propose_assignment
from ir_builder import required_external_resources
from semantic_validator import validate_semantic_output
from test_execute_full_pipeline import temp_map, _tia_ready  # noqa: F401
from test_experiment_working_io_map import _use_bench_copy
from test_normal_functional_composition import normal, _script  # noqa: F401
from test_normal_mode_hardening import _Plc, _bench, _channel, _configs, _generate, _interpret, _llm
from test_phase1_download_and_trials import pipeline  # noqa: F401


COMMAND = (
    "Cuando presione Start, enciende la bomba durante 5 segundos, luego apagala y abre la valvula durante 3 "
    "segundos. Al finalizar, apaga todas las salidas y queda listo para iniciar otra vez. "
    "Si se presiona Stop en cualquier momento, deten inmediatamente todo el proceso."
)


def _sequence(intent="INT_UNKNOWN", pump="Q_Aux_Output"):
    payload = _llm(COMMAND, [{
        "type": "timed_sequence", "start_input": "I_Start", "stop_input": "I_Stop", "repeat": "once",
        "steps": [{"outputs": [pump], "duration": "T#5s"},
                  {"outputs": ["Q_Valve_Open"], "duration": "T#3s"}],
    }], intent=intent, parameters={"delay_time": "T#5s", "emergency_input": "FALSE"})
    payload["interaction_profile"] = "normal"
    return payload


def _validate(payload, io_map):
    catalog, safety = _configs()
    return {**payload, "semantic_validation": validate_semantic_output(payload, io_map, catalog, safety)}


def _legacy_map():
    io_map = _bench(free_do=0, free_di=0, free_ai=0)
    io_map["variables"] += [
        _channel("Q_Motor_Enable", "%QX0.0", "FREE"),
        _channel("Q_Alarm", "%QX0.1", "FREE"),
        _channel("Q_Aux_Output", "%QX0.4", "FREE"),
    ]
    return io_map


def test_composed_sequence_does_not_inherit_unused_template_outputs():
    io_map = _legacy_map()
    required = required_external_resources(_sequence("INT_SEQUENCE_THREE_STEPS"), io_map)
    assert set(required) == {"I_Start", "I_Stop", "Q_Aux_Output", "Q_Valve_Open"}


@pytest.mark.parametrize("intent", ["INT_UNKNOWN", "INT_SEQUENCE_THREE_STEPS"])
def test_reported_pump_valve_command_generates_and_behaves_correctly(intent, tmp_path):
    io_map = _legacy_map()
    before = copy.deepcopy(io_map)
    result = _generate(_validate(_sequence(intent), io_map), io_map, tmp_path)
    assert io_map == before
    names = {v["name"] for v in result["ir"]["pou"]["variables"]}
    assert "Q_Motor_Enable" not in names  # this template output is not used by the compositor
    assert "Q_Motor_Enable" not in json.dumps(result["ir"]["test_cases"])
    plc = _Plc(result["scl"])
    outputs = ("Q_Aux_Output", "Q_Valve_Open")
    plc.press("I_Start")
    assert plc.on(*outputs) == {"Q_Aux_Output"}
    plc.run(4800)
    assert plc.on(*outputs) == {"Q_Aux_Output"}
    plc.run(200)
    assert plc.on(*outputs) == {"Q_Valve_Open"}
    plc.run(3100)
    assert plc.on(*outputs) == set()
    plc.run(1000)
    assert plc.on(*outputs) == set()  # no automatic restart
    for elapsed in (100, 5100):
        plc.press("I_Start")
        plc.run(elapsed)
        plc.press("I_Stop")
        assert plc.on(*outputs) == set()


@pytest.mark.parametrize("intent", ["INT_UNKNOWN", "INT_SEQUENCE_THREE_STEPS"])
def test_command_uses_the_production_parser_before_resource_allocation(intent, tmp_path):
    io_map = _legacy_map()
    semantic = _interpret(COMMAND, _sequence(intent), io_map)
    result = _generate(semantic, io_map, tmp_path)
    assert "Q_Motor_Enable" not in {v["name"] for v in result["ir"]["pou"]["variables"]}


@pytest.mark.parametrize("reverse", [False, True])
def test_new_output_cannot_take_a_free_channel_used_by_the_same_program(reverse, tmp_path):
    io_map = _legacy_map()
    # Valve is encountered before Pump; the existing Pump symbol must still be reserved.
    io_map["variables"][2] = _channel("Q_Pump", "%QX0.0", "FREE")
    payload = _sequence(pump="Q_Pump")
    payload["functional_requirements"][0]["steps"].reverse()
    if reverse:
        io_map["variables"].reverse()
    semantic = _validate(payload, io_map)
    proposals = semantic["semantic_validation"]["io_assignment_proposals"]
    assert [(p["proposed_name"], p["address"]) for p in proposals] == [("Q_Valve_Open", "%QX0.1")]
    result = _generate(semantic, io_map, tmp_path)
    by_name = {v["name"]: v for v in result["map"]["variables"]}
    assert by_name["Q_Pump"]["location"] == "%QX0.0"


def test_explicit_assignment_cannot_overwrite_another_output_used_by_the_program():
    io_map = _legacy_map()
    io_map["variables"][2] = _channel("Q_Pump", "%QX0.0", "FREE")
    payload = _sequence(pump="Q_Pump")
    payload["requested_io_assignments"] = [{"functional_name_hint": "Q_Valve_Open", "address": "%QX0.0"}]
    validation = _validate(payload, io_map)["semantic_validation"]
    assert not validation["is_valid"]
    assert any(p["blocked"] for p in validation["io_assignment_proposals"])


def test_reserved_assigned_channel_is_not_a_reassignment_candidate():
    io_map = _bench(free_do=0, free_di=0, free_ai=0)
    io_map["variables"].append(_channel("Q_Pump", "%QX0.0", "ASSIGNED"))
    requests = [{"functional_name_hint": "Q_Valve_Open"}]
    assert propose_assignment(io_map, requests, reserved_names={"Q_Pump"})[0]["blocked"]
    # Callers without program reservations keep the existing allocator policy.
    assert not propose_assignment(io_map, requests)[0]["blocked"]


def test_missing_capacity_is_detected_before_generation_without_stealing_the_pump():
    io_map = _bench(free_do=0, free_di=0, free_ai=0)
    io_map["variables"].append(_channel("Q_Pump", "%QX0.0", "FREE"))
    validation = _validate(_sequence(pump="Q_Pump"), io_map)["semantic_validation"]
    assert not validation["is_valid"]
    assert validation["capability_gap"]
    assert all(p["blocked"] for p in validation["io_assignment_proposals"])


def test_provisional_revalidation_cannot_accept_unapplied_resource_assignments():
    io_map = _legacy_map()
    semantic = _validate(_sequence(), io_map)
    changed = copy.deepcopy(io_map)
    changed["variables"][-1]["name"] = "Q_Free"
    opened = []
    app = SimpleNamespace(
        active_trial=None, active_profile_id=None,
        _program_base_map=lambda: changed,
        _open_map_transaction=lambda *args: opened.append(args),
        _log=lambda *args: None,
    )
    catalog, safety = _configs()
    result = gui.VozLLMPLCGUI._prepare_provisional_allocation(app, semantic, catalog, safety)
    assert result is not None
    assert not result["semantic_validation"]["is_valid"]
    assert "Q_Aux_Output" in " ".join(result["semantic_validation"]["errors"])
    assert opened == []


def test_gui_commits_the_reported_sequence_only_after_verified_generation(normal, monkeypatch, tmp_path):
    import project_packager

    app, state = normal["app"], normal["state"]
    path = tmp_path / "sequence_map.json"
    path.write_text(json.dumps(_legacy_map()), encoding="utf-8")
    _use_bench_copy(app, path)
    app.save_io_map(show_success=False)
    before = path.read_bytes()
    io_map = json.loads(before)
    semantic = _interpret(COMMAND, _sequence("INT_SEQUENCE_THREE_STEPS"), io_map)
    _script(monkeypatch, state, [semantic])
    app.command_textbox.delete("1.0", "end")
    app.command_textbox.insert("1.0", COMMAND)
    produced = []
    real = project_packager.generate_project_package
    monkeypatch.setattr(gui, "generate_project_package", lambda **kw:
                        produced.append(real(**{**kw, "output_dir": tmp_path / "generated"})) or produced[-1])
    assert app.process_command()
    provisional_on_disk = json.loads(path.read_bytes())
    assert provisional_on_disk["variables"] == io_map["variables"]
    assert provisional_on_disk.get("history", []) == io_map.get("history", [])
    assert app.generate_package()
    assert not state["errors"] and not state["dialogs"]
    committed = {v["name"]: v for v in json.loads(path.read_bytes())["variables"]}
    for variable in produced[-1]["project_ir"]["pou"]["variables"]:
        if variable["name"].startswith(("I_", "Q_")):
            assert committed[variable["name"]]["location"] == variable["location"]
