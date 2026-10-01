"""
Fase 4A.0b: en benchmark v2 `allowed_variables` es metadata historica, nunca una whitelist.
Los recursos se validan contra el working_io_map del ensayo (binding real, tipo compatible,
LOCKED intacto, sin ghost resources). La whitelist por perfil queda aislada para benchmark v1.
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
import re
import textwrap
from pathlib import Path
from typing import Any

import gui  # noqa: E402
import io_allocator  # noqa: E402
from semantic_validator import validate_semantic_output  # noqa: E402
from trial_experiments import batch_runner as B  # noqa: E402
from trial_experiments import experimental_design as ED  # noqa: E402
from trial_experiments import resource_policy as RP  # noqa: E402
from trial_experiments import trial_io_map, trial_model  # noqa: E402
from utils import load_json_file  # noqa: E402

from test_phase1_download_and_trials import _arm_experiment_trial, _run, pipeline  # noqa: E402
from test_execute_full_pipeline import _base_semantic_output, temp_map, _tia_ready  # noqa: E402
from test_experiment_working_io_map import _allocating_parse, _use_bench_copy, bench_map  # noqa: E402

__all__ = ["pipeline", "temp_map", "_tia_ready", "bench_map"]

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)
_PROFILES = load_json_file(_ROOT / "data" / "plc_maps" / "profiles.json")
_D12_PROFILE = next(p for p in (_PROFILES["profiles"] if isinstance(_PROFILES, dict) else _PROFILES) if p.get("case_id") == "D12")


def _config(name: str) -> dict[str, Any]:
    return load_json_file(_ROOT / "config" / name)


def _frozen_trial(tmp_path: Path, bench: Path, requests: list[dict[str, Any]], parameters: dict[str, Any]) -> dict[str, Any]:
    """Working map real del ensayo + asignacion del IOAllocator + snapshot congelado."""
    reference = trial_io_map.create_working_map(tmp_path / "trial", bench)
    working = trial_io_map.load_working_map(Path(reference["working_map_path"]))
    proposals = io_allocator.propose_assignment(working, requests)
    trial_io_map.apply_proposals_to_working_map(
        Path(reference["working_map_path"]), [p for p in proposals if not p.get("blocked")], "TEXT_EXPLICIT", trial_io_map.STATE_PREPARING)
    semantic = _base_semantic_output("INT_DIRECT_OUTPUT", parameters, list(parameters.values()))
    semantic["semantic_validation"]["io_assignment_proposals"] = proposals
    frozen = trial_io_map.freeze_working_map(reference, semantic, trial_io_map.STATE_PREPARING, "D12_V1_TEXT_DEV_001")
    return {"proposals": proposals, "snapshot": json.loads(Path(frozen["snapshot_path"]).read_text(encoding="utf-8"))}


def _var(name: str, location: str, var_class: str, var_type: str = "BOOL") -> dict[str, Any]:
    return {"name": name, "type": var_type, "class": var_class, "location": location}


# ---------- 1 / 7: politica por version de benchmark ----------

def test_whitelist_only_applies_to_legacy_benchmark_v1():
    assert RP.legacy_profile_whitelist_applies(1) is True
    for version in (2, 3, "2", None, "x"):
        assert RP.legacy_profile_whitelist_applies(version) is False
    assert RP.resource_policy(2) == RP.POLICY_WORKING_MAP_BINDING
    assert RP.resource_policy(1) == RP.POLICY_LEGACY_PROFILE_WHITELIST


def test_v2_runtime_configuration_ignores_profile_whitelist_and_v1_keeps_it(app, monkeypatch):
    profile = _D12_PROFILE
    assert "Q_Motor_1" not in profile["allowed_variables"]
    monkeypatch.setattr(app, "active_profile_id", profile["profile_id"])
    monkeypatch.setattr(app, "active_trial", None)
    io_map, _, _ = app._load_runtime_configuration()  # benchmark vigente: v2
    names = {v["name"] for v in io_map["variables"]}
    assert "Q_Motor_1" in names, "v2 no debe filtrar el mapa por allowed_variables"
    monkeypatch.setattr(app, "_benchmark_version", lambda: 1)  # ruta legacy explicita
    legacy_names = {v["name"] for v in app._load_runtime_configuration()[0]["variables"]}
    assert "Q_Motor_1" not in legacy_names and set(profile["allowed_variables"]) & legacy_names


# ---------- 2: una variable asignada por el IOAllocator no falla aunque no este en allowed_variables ----------

def test_allocator_assigned_resource_passes_without_being_in_allowed_variables(tmp_path, bench_map):
    trial = _frozen_trial(tmp_path, bench_map, [{"functional_name_hint": "Q_Bomba_Nueva", "role_text": "bomba"}],
                          {"trigger_input": "I_Start", "output": "Q_Bomba_Nueva"})
    proposal = trial["proposals"][0]
    assert not proposal.get("blocked")
    assert "Q_Bomba_Nueva" not in _D12_PROFILE["allowed_variables"]
    variables = [_var("I_Start", "%IX16.0", "input"), _var("Q_Bomba_Nueva", proposal["address"], "output"),
                 _var("M_Latch", "", "internal")]
    result = RP.verify_program_resources(variables, trial["snapshot"])
    assert result["success"] is True and result["errors"] == []
    assert result["checked_external_resources"] == ["I_Start", "Q_Bomba_Nueva"]

    # El validador semantico (core, sin cambios) tampoco lo rechaza sobre el working map.
    working = copy.deepcopy(load_json_file(bench_map))
    semantic = _base_semantic_output("INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Bomba_Nueva"},
                                     ["I_Start", "Q_Bomba_Nueva"])
    validation = validate_semantic_output(semantic, working, _config("intents_catalog.json"), _config("safety_rules.json"))
    assert validation["unauthorized_tags"] == []
    assert RP.unresolved_resources({"semantic_validation": validation}) == []


# ---------- 3: recurso no resuelto ----------

def test_unresolved_resource_fails(tmp_path, bench_map):
    io_map = load_json_file(bench_map)
    for variable in io_map["variables"]:
        if str(variable.get("location", "")).startswith("%QX"):
            variable["state"] = "LOCKED"  # sin canales digitales de salida disponibles
    semantic = _base_semantic_output("INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Bomba_Nueva"},
                                     ["I_Start", "Q_Bomba_Nueva"])
    validation = validate_semantic_output(semantic, io_map, _config("intents_catalog.json"), _config("safety_rules.json"))
    assert validation["is_valid"] is False
    issues = RP.unresolved_resources({"semantic_validation": validation})
    assert issues and {issue["code"] for issue in issues} == {RP.ERROR_UNRESOLVED_RESOURCE}
    record = {"final_status": "FAIL", "failure_stage": RP.STAGE_IO_ALLOCATION, "stages": {"semantic_success": False},
              "io_map": {"error": RP.ERROR_UNRESOLVED_RESOURCE}, "errors": []}
    assert ED.classify_trial(record)["failure_category"] == "IO_ALLOCATION_FAILURE"


# ---------- 4: tipo incompatible ----------

def test_incompatible_type_fails(tmp_path, bench_map):
    snapshot = _frozen_trial(tmp_path, bench_map, [], {"trigger_input": "I_Start"})["snapshot"]
    digital_out = next(c for c in snapshot["channels"] if c["signal"] == "DO")
    as_input = RP.verify_program_resources([_var(digital_out["functional_name"], digital_out["address"], "input")], snapshot)
    assert not as_input["success"] and as_input["errors"][0]["code"] == RP.ERROR_TYPE_INCOMPATIBLE
    analog = next(c for c in snapshot["channels"] if c["signal"] == "AI")
    as_bool = RP.verify_program_resources([_var(analog["functional_name"], analog["address"], "input", "BOOL")], snapshot)
    assert not as_bool["success"] and as_bool["errors"][0]["code"] == RP.ERROR_TYPE_INCOMPATIBLE


# ---------- 5: LOCKED ----------

def test_locked_channel_modification_fails(tmp_path, bench_map):
    io_map = load_json_file(bench_map)
    locked = next(v for v in io_map["variables"] if v.get("state") == "LOCKED")
    proposals = io_allocator.propose_assignment(io_map, [{"address": locked["location"], "requested_name": "I_Otro_Uso",
                                                          "functional_name_hint": "I_Otro_Uso"}])
    assert all(p.get("blocked") or p.get("proposed_name") != "I_Otro_Uso" or p.get("address") != locked["location"] for p in proposals)
    snapshot = _frozen_trial(tmp_path, bench_map, [], {"trigger_input": "I_Start"})["snapshot"]
    tampered = copy.deepcopy(snapshot)
    tampered["allocation_history"].append({"address": locked["location"], "old_name": locked["name"], "new_name": "I_Otro_Uso",
                                           "old_state": "LOCKED", "new_state": "ASSIGNED", "source": "TEXT_EXPLICIT"})
    result = RP.verify_program_resources([], tampered)
    assert not result["success"] and result["errors"][0]["code"] == RP.ERROR_LOCKED_VIOLATION
    assert RP.verify_program_resources([], snapshot)["success"] is True


# ---------- 6: ghost resource ----------

def test_ghost_resource_fails(tmp_path, bench_map):
    snapshot = _frozen_trial(tmp_path, bench_map, [], {"trigger_input": "I_Start"})["snapshot"]
    unknown = RP.verify_program_resources([_var("Q_Fantasma", "%QX8.7", "output")], snapshot)
    assert not unknown["success"] and unknown["errors"][0]["code"] == RP.ERROR_GHOST_RESOURCE
    moved = RP.verify_program_resources([_var("I_Start", "%IX16.5", "input")], snapshot)
    assert not moved["success"] and moved["errors"][0]["code"] == RP.ERROR_GHOST_RESOURCE
    record = {"final_status": "FAIL", "failure_stage": RP.STAGE_RESOURCE_BINDING,
              "stages": {"semantic_success": True, "verification_success": True}, "errors": []}
    assert ED.classify_trial(record)["failure_category"] == "IR_FAILURE"


# ---------- GUI: pipeline real con working map ----------

def _generation_writing(pipeline_state: dict[str, Any], variables_factory):
    package_dir = pipeline_state["package_dir"]

    def _generate(**kwargs):
        (package_dir / "variables.json").write_text(json.dumps(variables_factory()), encoding="utf-8")
        return {
            "verification": {"is_valid": True, "errors": [], "warnings": []},
            "artifacts": {"package_dir": str(package_dir), "pou_path": str(package_dir / "implementation.st")},
            "project_ir": {"metadata": {"generated_functional_variables": []}},
            "rendered_files": {},
        }
    return _generate


def _arm(app, bench_map, monkeypatch, requests, parameters):
    _use_bench_copy(app, bench_map)
    monkeypatch.setattr(gui, "record_trial_summary", lambda *a, **k: None)
    parse, _ = _allocating_parse(requests, parameters, list(parameters.values()))
    monkeypatch.setattr(gui, "parse_command", parse)
    monkeypatch.setattr(app, "active_profile_id", _D12_PROFILE["profile_id"])  # whitelist legacy presente pero ignorada
    trial_directory = _arm_experiment_trial(app)
    assert app._prepare_trial_working_map() is True
    return trial_directory


def _snapshot_address(trial_directory: Path, name: str) -> str:
    snapshot = json.loads((trial_directory / "io_map_snapshot.json").read_text(encoding="utf-8"))
    return next(c["address"] for c in snapshot["channels"] if c["functional_name"] == name)


def test_gui_v2_trial_accepts_allocated_resource_outside_allowed_variables(pipeline, bench_map, monkeypatch):
    app = pipeline["app"]
    holder: dict[str, Path] = {}
    monkeypatch.setattr(gui, "generate_project_package", _generation_writing(pipeline, lambda: [
        _var("I_Start", "%IX16.0", "input"), _var("Q_Bomba_Nueva", _snapshot_address(holder["dir"], "Q_Bomba_Nueva"), "output")]))
    holder["dir"] = _arm(app, bench_map, monkeypatch, [{"functional_name_hint": "Q_Bomba_Nueva", "role_text": "bomba"}],
                         {"trigger_input": "I_Start", "output": "Q_Bomba_Nueva"})
    _run(app)
    record = trial_model.load_trial(holder["dir"])
    assert record["resource_check"]["success"] is True and record["resource_check"]["policy"] == RP.POLICY_WORKING_MAP_BINDING
    assert record["final_status"] == trial_model.FINAL_STATUS_PREPARED
    assert len(pipeline["download_calls"]) == 1


def test_gui_v2_ghost_resource_stops_before_compile(pipeline, bench_map, monkeypatch):
    app = pipeline["app"]
    compile_calls: list[Any] = []
    monkeypatch.setattr(gui, "validate_package_with_tia", lambda *a, **k: compile_calls.append(a) or {})
    monkeypatch.setattr(gui, "generate_project_package", _generation_writing(pipeline, lambda: [
        _var("I_Start", "%IX16.0", "input"), _var("Q_Fantasma", "%QX8.7", "output")]))
    trial_directory = _arm(app, bench_map, monkeypatch, [], {"trigger_input": "I_Start"})
    assert _run(app) is False
    record = trial_model.load_trial(trial_directory)
    assert record["final_status"] == trial_model.FINAL_STATUS_FAIL
    assert record["failure_category"] == "IR_FAILURE" and record["failure_stage"] == RP.STAGE_RESOURCE_BINDING
    assert record["resource_check"]["errors"][0]["code"] == RP.ERROR_GHOST_RESOURCE
    assert compile_calls == [] and pipeline["download_calls"] == []


def test_gui_v2_unresolved_resource_is_io_failure_without_case_whitelist_dialog(pipeline, bench_map, monkeypatch):
    app = pipeline["app"]
    warnings: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, message, **k: warnings.append(title))
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, message, **k: warnings.append(title))
    trial_directory = _arm(app, bench_map, monkeypatch, [], {"trigger_input": "I_Start", "output": "Q_No_Resuelto"})

    def _parse(command_text, **kwargs):
        output = _base_semantic_output("INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_No_Resuelto"},
                                       ["I_Start", "Q_No_Resuelto"])
        output["semantic_validation"].update({"is_valid": False, "unauthorized_tags": ["Q_No_Resuelto"],
                                              "errors": ["Recurso funcional sin canal fisico disponible"]})
        return output
    monkeypatch.setattr(gui, "parse_command", _parse)
    assert _run(app) is False
    record = trial_model.load_trial(trial_directory)
    assert record["final_status"] == trial_model.FINAL_STATUS_FAIL
    assert record["failure_category"] == "IO_ALLOCATION_FAILURE"
    assert record["io_map"]["error"] == RP.ERROR_UNRESOLVED_RESOURCE
    assert "Incompatibilidad experimental" not in warnings  # nunca el dialogo de whitelist por caso


# ---------- 8: sin case_id para escoger recursos ----------

def test_resource_validation_never_depends_on_case_id_or_profile():
    for function in (RP.verify_program_resources, RP.unresolved_resources, RP.locked_violations):
        node = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
        if ast.get_docstring(node):
            node.body = node.body[1:]
        source = ast.unparse(node)  # sin docstring ni comentarios: solo el codigo que decide
        assert "case_id" not in source and "allowed_variables" not in source and "profile" not in source
    gui_source = inspect.getsource(gui.VozLLMPLCGUI._load_runtime_configuration)
    assert "legacy_profile_whitelist_applies" in gui_source  # el filtro por perfil solo existe en la ruta v1
    for path in (_ROOT / "src" / "trial_experiments" / "resource_policy.py", _ROOT / "src" / "trial_experiments" / "trial_io_map.py"):
        code = "\n".join(line.split("#", 1)[0] for line in path.read_text(encoding="utf-8").splitlines())
        assert not re.search(r"\bcase_id\s*(==|!=|\bin\b)", code)
        assert not re.search(r"""["'](D(0[1-9]|1\d|20)|P(0[1-9]|1[0-2]))["']""", code)


# ---------- 9 / 10 / 11: integridad ----------

def test_oracles_benchmark_and_maps_untouched():
    after = B.integrity_snapshot(_ROOT)
    assert B.integrity_differences(_INTEGRITY_BEFORE, after) == []
    assert all(e["status"] == "FROZEN" and e["stored_hash"] == e["computed_hash"] for e in after["oracles"].values())
    assert len(after["oracles"]) == 32
    assert all(after["files"][m] for m in B.MAP_FILES)
