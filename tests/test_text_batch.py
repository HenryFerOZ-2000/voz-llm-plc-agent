"""
LOTE TEXT secuencial (trial_experiments.text_batch + controlador de la GUI).

Sin TIA/PLCSIM/LLM reales: la generacion se sustituye por un ensayo GENERADO valido (como lo deja
EJECUTAR ENSAYO COMPLETO tras el LLM) y la evaluacion es la REAL (deferred_evaluator.evaluate_trial en
el hilo de la GUI) con los dobles de bridge/Runtime/Oracle de la suite.
"""
from __future__ import annotations

import csv
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from trial_experiments import batch_runner as B  # noqa: E402
from trial_experiments import benchmark_catalog as BC  # noqa: E402
from trial_experiments import deferred_evaluator as DE  # noqa: E402
from trial_experiments import text_batch as TB  # noqa: E402
from trial_experiments import trial_io_map, trial_model  # noqa: E402

from test_execute_full_pipeline import _base_semantic_output  # noqa: E402
from test_phase4a_deferred_evaluation import _SCL, _FakeBridge, _master, _oracle_pass, _project, _runtime  # noqa: E402
from test_phase4a_voice_flow import complete_flow  # noqa: E402,F401
from test_phase1_download_and_trials import pipeline  # noqa: E402,F401
from test_execute_full_pipeline import temp_map, _tia_ready  # noqa: E402,F401
from test_experiment_working_io_map import bench_map  # noqa: E402,F401

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)
_FROZEN = ("data/experiment_cases/canonical_cases.json", "data/experimental_design.json",
           "data/plc_maps/mapa_banco_fisico_base.json", "data/plc_maps/profiles.json", "data/plc_maps/experiment_variants.json")
_FROZEN_BEFORE = {name: B.file_hash(_ROOT / name) for name in _FROZEN}
DEV = trial_model.PHASE_DEVELOPMENT
FORMAL = trial_model.PHASE_FORMAL
NO_GIT = {"commit": "abc123", "dirty": False, "dirty_files": []}


# ---------------------------------------------------------------------------------------------
# Plan (motor puro)
# ---------------------------------------------------------------------------------------------

def test_full_text_plan_is_96_trials_in_benchmark_order():
    plan = TB.build_plan(_ROOT)
    assert len(plan) == 96
    expected = [(f"D{i:02d}", v) for i in range(1, 21) for v in ("V1", "V2", "V3")] + \
               [(f"P{i:02d}", v) for i in range(1, 13) for v in ("V1", "V2", "V3")]
    assert [(e["case_id"], e["variant_id"]) for e in plan] == expected
    assert [e["index"] for e in plan] == list(range(96)) and {e["input_mode"] for e in plan} == {"TEXT"}
    case = BC.get_case(_ROOT, "D05")
    entry = next(e for e in plan if e["case_id"] == "D05" and e["variant_id"] == "V2")
    assert entry["reference_text"] == case["variants"]["V2"] and entry["variant_hash"] == BC.variant_hash(case["variants"]["V2"])


def test_plan_order_does_not_depend_on_the_selection_order():
    assert [(e["case_id"], e["variant_id"]) for e in TB.build_plan(_ROOT, ["D03", "D01", "D02"], ["V3", "V1", "V2"])] == \
           [(c, v) for c in ("D01", "D02", "D03") for v in ("V1", "V2", "V3")]


def test_subset_d01_d03_by_v1_v3_is_9_trials():
    cases = TB.parse_case_selection(_ROOT, "D01-D03", ["D", "P"])
    assert cases == ["D01", "D02", "D03"] and len(TB.build_plan(_ROOT, cases, ["V1", "V2", "V3"])) == 9
    assert TB.parse_case_selection(_ROOT, "", ["P"]) == [f"P{i:02d}" for i in range(1, 13)]
    assert TB.parse_case_selection(_ROOT, "P02, D01", ["D"]) == ["D01", "P02"]
    with pytest.raises(ValueError):
        TB.parse_case_selection(_ROOT, "D19-P02", ["D"])
    with pytest.raises(ValueError):
        TB.build_plan(_ROOT, ["D99"])


def test_pid_cases_are_marked_not_evaluable_from_the_frozen_oracles():
    plan = TB.build_plan(_ROOT)
    assert {e["case_id"] for e in plan if not e["evaluable"]} == {f"P{i:02d}" for i in range(1, 13)}


# ---------------------------------------------------------------------------------------------
# Manifiesto, persistencia y reanudacion (motor puro)
# ---------------------------------------------------------------------------------------------

def test_manifest_has_the_required_traceability(tmp_path):
    root = _project(tmp_path)
    batch_dir, manifest = TB.create_batch(root, DEV, ["D01", "D02", "D03"], list(TB.VARIANT_ORDER), host_id="DEV_PC", git=NO_GIT)
    saved = TB.load_manifest(batch_dir)
    for key in ("batch_id", "phase", "input_mode", "benchmark_version", "created_at", "started_at", "completed_at", "status",
                "total_trials", "completed_trials", "current_index", "next_trial", "ordered_trial_plan", "git_commit",
                "host_id", "trial_ids", "results"):
        assert key in saved, key
    assert saved["batch_id"].startswith("TEXT_DEV_") and saved["input_mode"] == "TEXT" and saved["total_trials"] == 9
    assert saved["status"] == TB.STATUS_CREATED and saved["git_commit"] == "abc123" and saved["host_id"] == "DEV_PC"
    assert saved["next_trial"]["case_id"] == "D01" and saved["next_trial"]["variant_id"] == "V1"
    assert batch_dir.parent == root / "results" / "batches"
    with pytest.raises(ValueError, match=TB.ERROR_OPEN_BATCH):
        TB.create_batch(root, DEV, ["D04"], ["V1"], git=NO_GIT)  # un solo lote abierto


def test_development_and_formal_batches_are_separated(tmp_path):
    root = _project(tmp_path)
    assert TB.new_batch_id(root, DEV).startswith("TEXT_DEV_") and TB.new_batch_id(root, FORMAL).startswith("TEXT_FORMAL_")
    assert trial_model.get_phase_results_dir(root, DEV) != trial_model.get_phase_results_dir(root, FORMAL)
    assert trial_model.trial_kind_for_phase(DEV) == trial_model.TRIAL_KIND_DEVELOPMENT
    with pytest.raises(ValueError):
        TB.create_batch(root, trial_model.PHASE_BASELINE, ["D01"], ["V1"], git=NO_GIT)


def test_formal_is_blocked_when_any_guard_fails(tmp_path):
    root = _project(tmp_path)
    plan = TB.build_plan(root, ["D01"], ["V1"])
    guards = TB.formal_guards(root, plan, git={"commit": "abc", "dirty": True, "dirty_files": ["src/gui.py"]})
    assert guards["ok"] is False
    failed = set(guards["failed"])
    assert {"software_frozen", "environment_master_plcsim_memory", "git_clean"} <= failed  # sin congelar, sin MASTER, arbol sucio
    assert "oracles_frozen_hash" not in failed and "benchmark_integrity" not in failed and "text_variants_from_benchmark" not in failed
    pid = TB.formal_guards(root, TB.build_plan(root, ["P01"], ["V1"]), git=NO_GIT)
    assert "cases_evaluable" in pid["failed"]


def test_reconcile_after_a_crash_never_infers_progress_from_folders(tmp_path):
    root = _project(tmp_path)
    _master(root)
    batch_dir, manifest = TB.create_batch(root, DEV, ["D01"], ["V1", "V2", "V3"], git=NO_GIT)
    first, second, third = manifest["ordered_trial_plan"]
    done = _make_trial(root, "D01", "V1")
    _evaluate_with(root, done, _FakeBridge())
    TB.begin_entry(manifest, first, done, done.name)        # el manifiesto quedo en GENERATING (caida antes de registrar)
    pending = _make_trial(root, "D01", "V2")
    TB.begin_entry(manifest, second, pending, pending.name)  # generado, evaluacion PENDING
    broken = _make_trial(root, "D01", "V3")
    TB.begin_entry(manifest, third, broken, broken.name)
    trial_model.update_trial(broken, {"evaluation": {"status": "RUNNING"}})  # evaluacion cortada a mitad
    TB.save_manifest(batch_dir, manifest)
    issues = TB.reconcile(root, manifest)
    assert first["status"] == TB.ENTRY_COMPLETED and first["result"]["final_verdict"] == "PASS"
    assert second["status"] == TB.ENTRY_EVALUATING  # se evaluara ese MISMO ensayo
    assert third["status"] == TB.ENTRY_INTERRUPTED and any("quedo a medias" in issue for issue in issues)


# ---------------------------------------------------------------------------------------------
# Controlador real de la GUI (evaluacion real con dobles de TIA/PLCSIM/Oracle)
# ---------------------------------------------------------------------------------------------

def _make_trial(root: Path, case_id: str, variant: str, phase: str = DEV, semantic_fail: bool = False) -> Path:
    """Ensayo como lo deja EJECUTAR ENSAYO COMPLETO tras generar (o con la semantica fallida)."""
    number = trial_model.next_trial_number(root, case_id, variant, "TEXT", phase)
    reference = BC.trial_benchmark_reference(root, case_id, variant)
    record = trial_model.new_trial_record(
        case_id, variant, "TEXT", number, command_text=BC.get_case(root, case_id)["variants"][variant], complexity="LOW", phase=phase,
        extra={key: reference.get(key) for key in ("benchmark_version", "canonical_case_hash", "variant_hash")})
    directory = trial_model.trial_directory(root, case_id, variant, record["trial_id"], phase)
    trial_model.save_trial(directory, record)
    if semantic_fail:
        trial_model.update_trial(directory, {"stages": {"semantic_success": False}, "failure_stage": "semantic"})
        trial_model.finalize_trial(directory, trial_model.FINAL_STATUS_FAIL, ["semantica no interpretable"])
        DE.finalize_generation(root, directory, None)
        return directory
    io_ref = trial_io_map.create_working_map(directory, root / "data" / "plc_maps" / "mapa_banco_fisico_base.json")
    semantic = _base_semantic_output("INT_MOTOR_START_STOP", {"start_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor"},
                                     ["I_Start", "I_Stop", "Q_Motor"])
    frozen = trial_io_map.freeze_working_map(io_ref, semantic, trial_io_map.STATE_PREPARING, record["trial_id"])
    trial_io_map.discard_working_map(frozen)
    (directory / DE.COMMAND_FILENAME).write_text(BC.get_case(root, case_id)["variants"][variant], encoding="utf-8")
    (directory / DE.SEMANTIC_FILENAME).write_text(json.dumps(semantic), encoding="utf-8")
    trial_model.update_trial(directory, {"stages": {"semantic_success": True, "verification_success": True},
                                         "io_map": trial_io_map.trial_record_reference(frozen)})
    package = directory.parent / f"pkg_{record['trial_id']}"
    package.mkdir()
    (package / "siemens_source.scl").write_text(_SCL, encoding="utf-8")
    (package / "variables.json").write_text(json.dumps([
        {"name": "I_Start", "type": "BOOL", "class": "input", "location": "%IX16.0", "siemens_type": "Bool", "siemens_address": "%I16.0"},
        {"name": "Q_Motor", "type": "BOOL", "class": "output", "location": "%QX8.0", "siemens_type": "Bool", "siemens_address": "%Q8.0"},
    ]), encoding="utf-8")
    DE.finalize_generation(root, directory, package)
    return directory


def _oracle_with(functional: bool = True, safety: bool = True):
    def _run(oracle, snapshot_path, runtime_report, target_type, semantic_output=None, project_root=None, **kwargs):
        result = _oracle_pass(oracle, snapshot_path, runtime_report, target_type, semantic_output, project_root)
        result["functional"] = {**result["functional"], "success": functional, "passed_checks": 3 if functional else 1}
        result["safety"] = {**result["safety"], "success": safety, "critical_violations": 0 if safety else 1}
        result["verdict"] = "PASS" if functional and safety else "FAIL"
        return result
    return _run


_REAL_EVALUATE = DE.evaluate_trial


def _evaluate_with(root, trial_dir, bridge, oracle=None, retry_reason=None):
    return _REAL_EVALUATE(root, trial_dir, retry_reason, bridge=bridge, runtime_status_fn=_runtime,
                          oracle_fn=oracle or _oracle_pass, log=lambda _m: None)


@pytest.fixture
def batch(app, tmp_path, monkeypatch):
    """GUI real + proyecto temporal. outcomes[(case, variant)] decide la generacion y la evaluacion simuladas."""
    root = _project(tmp_path)
    _master(root)
    state: dict[str, Any] = {"root": root, "outcomes": {}, "events": [], "active": 0, "max_active": 0, "evaluated": [],
                             "lock": threading.Lock()}
    monkeypatch.setattr(app, "project_root", root)
    monkeypatch.setattr(app, "BATCH_STEP_DELAY_MS", 10)
    monkeypatch.setattr(app, "_configure_experiment_selection", lambda entry, phase: state["events"].append(("configure", entry["case_id"], entry["variant_id"])))
    monkeypatch.setattr(DE, "environment_precheck", lambda project_root, phase: {"ok": True, "errors": [], "warnings": []})

    def _fake_complete_trial(batch_trial=None):
        assert batch_trial is not None, "el lote siempre pasa por run_complete_trial(batch_trial=...)"
        entry = next(e for e in app._text_batch["manifest"]["ordered_trial_plan"] if e["index"] == batch_trial["index"])
        outcome = state["outcomes"].get((entry["case_id"], entry["variant_id"]), "PASS")
        assert state["active"] == 0, "no puede iniciarse un ensayo mientras otro esta en curso"
        state["events"].append(("start", entry["case_id"], entry["variant_id"]))
        directory = _make_trial(root, entry["case_id"], entry["variant_id"], app._text_batch["manifest"]["phase"],
                                semantic_fail=outcome == "SEMANTIC_FAIL")
        batch_trial["on_started"](directory)
        generation = trial_model.load_trial(directory)["generation"]["status"]
        app.after(0, lambda: batch_trial["on_generated"](directory, generation))
        return directory

    def _fake_evaluate(project_root, trial_dir, retry_reason=None, log=None, **kwargs):
        record = trial_model.load_trial(Path(trial_dir))
        key = (record["case_id"], record["variant_id"])
        outcome = state["outcomes"].get(key, "PASS")
        if outcome == "INFRA_ONCE" and retry_reason:
            outcome = "PASS"
        with state["lock"]:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        try:
            time.sleep(0.05)
            bridge = _FakeBridge({"COMPILE_FAIL": "COMPILE_FAIL", "INFRA": "NON_RECOVERABLE", "INFRA_ONCE": "NON_RECOVERABLE"}.get(outcome, "PASS"))
            oracle = _oracle_with(functional=outcome != "FUNCTIONAL_FAIL", safety=outcome != "SAFETY_FAIL")
            result = _evaluate_with(project_root, Path(trial_dir), bridge, oracle, retry_reason)
            state["evaluated"].append((Path(trial_dir).name, retry_reason))
            return result
        finally:
            with state["lock"]:
                state["active"] -= 1
            state["events"].append(("evaluated", *key))

    monkeypatch.setattr(app, "run_complete_trial", _fake_complete_trial)
    monkeypatch.setattr(DE, "evaluate_trial", _fake_evaluate)
    app._text_batch = None
    yield state
    app._text_batch = None
    app._batch_evaluating_dir = None


def _pump(app, until, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.update()
        if until():
            for _ in range(5):
                app.update()
            return
        time.sleep(0.01)
    raise AssertionError("el lote no llego al estado esperado")


def _status(app) -> str:
    return app._text_batch["manifest"]["status"]


def _run_batch(app, cases, variants=("V1", "V2", "V3")) -> dict[str, Any]:
    result = app.start_text_batch(DEV, cases, list(variants))
    assert result["ok"], result
    _pump(app, lambda: _status(app) != TB.STATUS_RUNNING and not app._tia_busy())
    return app._text_batch["manifest"]


def test_pilot_runs_9_trials_strictly_sequentially_with_one_tia_at_a_time(app, batch):
    manifest = _run_batch(app, ["D01", "D02", "D03"])
    assert manifest["status"] == TB.STATUS_COMPLETED and manifest["completed_trials"] == 9
    assert batch["max_active"] == 1  # nunca dos evaluaciones TIA simultaneas
    starts = [e for e in batch["events"] if e[0] in ("start", "evaluated")]
    # start N -> evaluated N -> start N+1 ...: el siguiente nunca empieza antes de terminar el anterior.
    assert [e[0] for e in starts] == ["start", "evaluated"] * 9
    assert [(e[1], e[2]) for e in starts[::2]] == [(c, v) for c in ("D01", "D02", "D03") for v in ("V1", "V2", "V3")]
    assert all(entry["result"]["final_verdict"] == "PASS" for entry in manifest["ordered_trial_plan"])


def test_experimental_fails_are_recorded_and_the_batch_continues_without_retry(app, batch):
    batch["outcomes"] = {("D01", "V1"): "FUNCTIONAL_FAIL", ("D01", "V2"): "COMPILE_FAIL", ("D01", "V3"): "SAFETY_FAIL",
                         ("D02", "V1"): "SEMANTIC_FAIL"}
    manifest = _run_batch(app, ["D01", "D02"])
    assert manifest["status"] == TB.STATUS_COMPLETED
    results = {(e["case_id"], e["variant_id"]): e["result"] for e in manifest["ordered_trial_plan"]}
    assert results[("D01", "V1")]["functional"] == "FAIL" and results[("D01", "V1")]["final_verdict"] == "FAIL"
    assert results[("D01", "V2")]["compilation"] == "FAIL" and results[("D01", "V2")]["download"] == "-"
    assert results[("D01", "V3")]["safety"] == "FAIL" and results[("D01", "V3")]["final_verdict"] == "FAIL"
    assert results[("D02", "V1")]["semantic"] == "FAIL" and results[("D02", "V1")]["final_verdict"] == "FAIL"
    assert all(reason is None for _, reason in batch["evaluated"])  # nunca se reintenta un FAIL
    assert len(batch["evaluated"]) == 5  # la semantica fallida no llega a TIA


def test_infrastructure_error_pauses_and_retry_is_only_explicit_and_keeps_attempts(app, batch):
    batch["outcomes"] = {("D01", "V2"): "INFRA_ONCE"}
    manifest = _run_batch(app, ["D01"])
    assert manifest["status"] == TB.STATUS_PAUSED and manifest["pause_reason"] == TB.PAUSE_INFRASTRUCTURE
    entries = manifest["ordered_trial_plan"]
    assert [e["status"] for e in entries] == [TB.ENTRY_COMPLETED, TB.ENTRY_INFRASTRUCTURE, TB.ENTRY_PENDING]
    assert len(batch["evaluated"]) == 2  # no se siguio con D01 V3 ni se reintento solo
    assert "LOTE PAUSADO POR INFRASTRUCTURE_ERROR" in app.text_batch_progress_lines()[0]
    assert app.resume_text_batch()["ok"] is False  # reanudar no salta el ensayo con error
    assert app.retry_text_batch_trial("")["ok"] is False  # el motivo es obligatorio
    assert app.retry_text_batch_trial("PLCSIM reiniciado")["ok"] is True
    _pump(app, lambda: _status(app) != TB.STATUS_RUNNING and not app._tia_busy())
    manifest = app._text_batch["manifest"]
    assert manifest["status"] == TB.STATUS_COMPLETED
    retried = trial_model.load_trial(Path(entries[1]["trial_dir"]))
    attempts = retried["evaluation"]["attempts"]
    assert [a["final_status"] for a in attempts] == ["INFRASTRUCTURE_ERROR", "PASS"]  # attempt_001 se conserva
    assert (Path(entries[1]["trial_dir"]) / "evaluation" / "attempt_001").exists()
    assert entries[1]["result"]["attempts"] == 2 and entries[1]["trial_id"] == Path(entries[1]["trial_dir"]).name


def test_pause_after_current_and_resume_never_repeats_completed_trials(app, batch):
    result = app.start_text_batch(DEV, ["D01", "D02"], ["V1", "V2", "V3"])
    assert result["ok"]
    _pump(app, lambda: any(e[0] == "start" for e in batch["events"]))
    app.request_text_batch_pause()  # durante el primer ensayo: no se interrumpe
    _pump(app, lambda: _status(app) == TB.STATUS_PAUSED and not app._tia_busy())
    manifest = app._text_batch["manifest"]
    assert manifest["pause_reason"] == TB.PAUSE_USER and manifest["completed_trials"] == 1
    assert manifest["ordered_trial_plan"][0]["result"]["final_verdict"] == "PASS"
    started_before = [e for e in batch["events"] if e[0] == "start"]
    assert len(started_before) == 1
    assert app.resume_text_batch()["ok"] is True
    _pump(app, lambda: _status(app) != TB.STATUS_RUNNING and not app._tia_busy())
    starts = [(e[1], e[2]) for e in batch["events"] if e[0] == "start"]
    assert starts == [(c, v) for c in ("D01", "D02") for v in ("V1", "V2", "V3")]  # D01 V1 una sola vez
    assert app._text_batch["manifest"]["status"] == TB.STATUS_COMPLETED


def test_manifest_is_persisted_after_each_trial_and_survives_a_restart(app, batch):
    snapshots: list[int] = []
    original = TB.record_trial_result

    def _spy(project_root, batch_dir, manifest, entry):
        decision = original(project_root, batch_dir, manifest, entry)
        snapshots.append(TB.load_manifest(batch_dir)["completed_trials"])  # leido del DISCO tras cada ensayo
        if len(snapshots) == 2:
            manifest["pause_requested"] = True  # simula cierre de la GUI tras el 2.o ensayo
        return decision

    batch_ref = {}
    import trial_experiments.text_batch as module
    module_original = module.record_trial_result
    module.record_trial_result = _spy
    try:
        app.start_text_batch(DEV, ["D01"], ["V1", "V2", "V3"])
        batch_ref["dir"] = app._text_batch["dir"]
        _pump(app, lambda: _status(app) == TB.STATUS_PAUSED and not app._tia_busy())
    finally:
        module.record_trial_result = module_original
    assert snapshots == [1, 2]
    # "Reinicio": la GUI pierde el estado en memoria y lo recupera solo desde el disco.
    app._text_batch = None
    reopened = app._load_open_text_batch()
    assert reopened["batch_id"] == TB.load_manifest(batch_ref["dir"])["batch_id"] and reopened["completed_trials"] == 2
    assert app.resume_text_batch()["ok"] is True
    _pump(app, lambda: _status(app) != TB.STATUS_RUNNING and not app._tia_busy())
    assert app._text_batch["manifest"]["status"] == TB.STATUS_COMPLETED
    assert [(e[1], e[2]) for e in batch["events"] if e[0] == "start"] == [("D01", "V1"), ("D01", "V2"), ("D01", "V3")]


def test_summaries_have_one_row_per_trial_from_trial_stage_summary(app, batch, monkeypatch):
    calls = []
    original = DE.trial_stage_summary
    monkeypatch.setattr(DE, "trial_stage_summary", lambda record: calls.append(record["trial_id"]) or original(record))
    batch["outcomes"] = {("D01", "V2"): "FUNCTIONAL_FAIL"}
    manifest = _run_batch(app, ["D01"])
    batch_dir = app._text_batch["dir"]
    payload = json.loads((batch_dir / TB.SUMMARY_JSON).read_text(encoding="utf-8"))
    with (batch_dir / TB.SUMMARY_CSV).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(payload["trials"]) == len(rows) == 3 and tuple(rows[0]) == TB.CSV_FIELDS
    assert {row["trial_id"] for row in rows} == {e["trial_id"] for e in manifest["ordered_trial_plan"]}
    for row, entry in zip(rows, manifest["ordered_trial_plan"]):
        summary = original(trial_model.load_trial(Path(entry["trial_dir"])))
        assert all(row[key] == summary[key] for key in DE.STAGE_KEYS)
        assert row["oracle_hash"] and row["canonical_case_hash"] and row["variant_hash"]
    assert set(calls) >= {e["trial_id"] for e in manifest["ordered_trial_plan"]}
    totals = payload["totals"]
    assert totals["trials_recorded"] == 3 and totals["final"]["PASS"] == 2 and totals["final"]["FAIL"] == 1
    assert totals["stages"]["functional"] == {"PASS": 2, "FAIL": 1, "recorded": 3}
    assert "LOTE TEXT COMPLETADO" in TB.final_report_lines(manifest)[0]


def test_each_archive_pass_has_its_own_zap18_and_every_trial_starts_from_the_master(app, batch):
    starts_from: list[str] = []
    original = _FakeBridge.__call__

    def _spy(self, request, work_dir, project_root=None, on_archived=None):
        starts_from.append(request["master_archive_path"])
        return original(self, request, work_dir, project_root, on_archived)

    _FakeBridge.__call__ = _spy
    try:
        manifest = _run_batch(app, ["D01"])
    finally:
        _FakeBridge.__call__ = original
    zap18 = set()
    for entry in manifest["ordered_trial_plan"]:
        row = entry["result"]
        assert row["tia_archive"] == "PASS"
        evidence = Path(row["zap18_path"])
        assert evidence.exists() and DE.sha256_file(evidence) == row["zap18_hash"]
        assert evidence.parent.parent.parent.parent == Path(entry["trial_dir"])  # evaluation/attempt_NNN/tia/<trial>.zap18
        zap18.add(evidence)
    assert len(zap18) == 3 and len(set(starts_from)) == 1  # 3 archivos propios; todos parten del mismo MASTER


def test_not_evaluable_pid_trial_is_generated_recorded_and_the_batch_continues(app, batch):
    manifest = _run_batch(app, ["P01"], ["V1"])
    [entry] = manifest["ordered_trial_plan"]
    assert manifest["status"] == TB.STATUS_COMPLETED and entry["status"] == TB.ENTRY_NOT_EVALUABLE
    assert entry["result"]["semantic"] == "PASS" and entry["result"]["compilation"] == "-"
    assert batch["evaluated"] == []  # nunca se abrio TIA para un Oracle no ejecutable


def test_single_trial_button_is_blocked_while_a_batch_runs(app, batch, monkeypatch):
    shown = []
    import gui
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, message="", **k: shown.append(message))
    app._text_batch = {"dir": batch["root"], "manifest": {"status": TB.STATUS_RUNNING}, "dialogs": []}
    assert gui.VozLLMPLCGUI.run_complete_trial(app) is None and "LOTE TEXT" in shown[0]


def test_batch_dialog_shows_the_total_and_an_incomplete_batch(app, batch):
    import gui
    dialog = gui.TextBatchDialog(app)
    try:
        dialog.range_var.set("D01-D03")
        assert "Total de ensayos: 9" in dialog.total_var.get()
        dialog.range_var.set("")
        dialog.p_var.set(True)
        dialog._update_total()
        assert "Total de ensayos: 96" in dialog.total_var.get() and "Runtime" in dialog.total_var.get()
    finally:
        dialog._close()


def test_configure_selection_loads_the_exact_benchmark_command(app):
    entry = TB.build_plan(_ROOT, ["D02"], ["V3"])[0]
    previous_mode = app.work_mode_var.get()
    try:
        app._configure_experiment_selection(entry, DEV)
        assert app._active_variant_command_text == entry["reference_text"]
        assert app._selected_phase() == DEV and app._selected_input_mode() == "TEXT"
    finally:
        app.work_mode_var.set(previous_mode)
        app._on_work_mode_changed()


def test_existing_trials_are_never_rewritten_by_a_batch(app, batch):
    old = _make_trial(batch["root"], "D01", "V1")
    _evaluate_with(batch["root"], old, _FakeBridge())
    before = {path: path.read_bytes() for path in old.rglob("*") if path.is_file()}
    manifest = _run_batch(app, ["D01"], ["V1"])
    [entry] = manifest["ordered_trial_plan"]
    assert Path(entry["trial_dir"]) != old  # el lote crea su propio ensayo; el anterior queda intacto
    assert {path: path.read_bytes() for path in old.rglob("*") if path.is_file()} == before


def test_repeat_reason_comes_from_the_batch_without_a_dialog(app, batch, monkeypatch):
    import gui
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: pytest.fail("el lote no abre dialogos"))
    old = _make_trial(batch["root"], "D02", "V1")
    repeat = app._repeat_info("D02", "V1", "TEXT", DEV, batch_reason="Lote TEXT_DEV_X")
    assert repeat == {"repeat_of_trial_id": old.name, "repeat_reason": "Lote TEXT_DEV_X"}  # se enlaza el anterior


def test_formal_batch_is_not_created_when_guards_fail(app, batch):
    result = app.start_text_batch(FORMAL, ["D01"], ["V1"])
    assert result["ok"] is False and any(TB.ERROR_FORMAL_GUARD in error for error in result["errors"])
    assert TB.list_batches(batch["root"]) == [] and app._text_batch is None


def test_batch_uses_the_real_complete_trial_flow_without_any_dialog(complete_flow, monkeypatch):
    """run_complete_trial REAL (pipeline de generacion de la GUI con LLM simulado) llamado como lo hace el lote."""
    app, seen = complete_flow["app"], complete_flow["seen"]
    app.experiment_input_mode_var.set(gui_module().INPUT_MODE_LABELS["TEXT"])
    app._on_experiment_input_mode_changed()
    monkeypatch.setattr(app, "_capture_voice", lambda *a, **k: pytest.fail("TEXT nunca usa el microfono"))
    calls: list[tuple[str, Any]] = []
    batch_trial = {"batch_id": "TEXT_DEV_TEST_001", "index": 0, "repeat_reason": "Lote TEXT_DEV_TEST_001",
                   "on_started": lambda directory: calls.append(("started", Path(directory))),
                   "on_generated": lambda directory, generation: calls.append(("generated", generation))}
    dialogs: list[dict[str, str]] = []
    with app._unattended_interactions(dialogs):
        first = app.run_complete_trial(batch_trial=batch_trial)
        for _ in range(5):
            app.update()
        second = app.run_complete_trial(batch_trial=batch_trial)  # repeticion: sin askstring
        for _ in range(5):
            app.update()
    assert calls == [("started", first), ("generated", "SUCCESS"), ("started", second), ("generated", "SUCCESS")]
    assert seen["dialogs"] == []  # el dialogo individual NUNCA se abre en el lote
    record = trial_model.load_trial(second)
    assert record["batch_id"] == "TEXT_DEV_TEST_001" and record["repeat_reason"] == "Lote TEXT_DEV_TEST_001"
    assert record["repeat_of_trial_id"] == trial_model.load_trial(first)["trial_id"]
    assert seen["commands"][-1] == record["reference_text"]  # mismo comando exacto del benchmark
    assert record["generation"]["status"] == "SUCCESS" and record["evaluation"]["status"] == "PENDING"


def gui_module():
    import gui
    return gui


def test_frozen_artifacts_unchanged():
    assert {name: B.file_hash(_ROOT / name) for name in _FROZEN} == _FROZEN_BEFORE
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
