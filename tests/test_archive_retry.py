"""
Robustez de Project.Archive ante la carrera interna de TIA V18 con IM/SearchIndex.

Causa (auditada en T0010/T0012/T0034): Project.Archive copia el proyecto a %TEMP%\\#TempArchive_<pid>\\<n>.zap18
mientras el indexador de busqueda de TIA reescribe IM/SearchIndex tras Save -> EngineeringTargetInvocationException
"Could not find file '...\\Txxxx.zap18'" en 127-256 ms; reintentar el mismo ensayo funciona.

Politica (tia_openness_bridge/Program.cs::ArchiveWithRetry, solo ensayos):
  espera fija de 2 s tras Save; hasta 3 intentos en la MISMA sesion TIA (mismo proyecto guardado/compilado,
  mismo workspace, mismo trial y mismo attempt de evaluacion); backoff 2 s y 3 s; solo se reintenta
  EngineeringTargetInvocationException con "Could not find file"; un destino ZIP completo nunca se
  sobrescribe y uno parcial se pone en cuarentena (.partial_attemptN), nunca se borra.

  1. El motor C# real se ejercita con la accion "self_test" del exe compilado (sin TIA, sin esperas reales).
  2. La integracion Python usa _FakeBridge con el mismo contrato de reporte (archive_attempts, ...).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tia_openness import build_openness_bridge  # noqa: E402
from trial_experiments import deferred_evaluator as DE  # noqa: E402
from trial_experiments import experimental_design as ED  # noqa: E402
from trial_experiments import tia_workspace as TW  # noqa: E402
from trial_experiments import trial_model  # noqa: E402
from utils import get_project_root  # noqa: E402

from test_phase4a_deferred_evaluation import _FakeBridge, _evaluate, _generated_trial, _master, _project, no_regeneration  # noqa: E402,F401

_ROOT = Path(__file__).resolve().parents[1]
_ATTEMPT_FIELDS = {"attempt_number", "started_at", "completed_at", "duration_ms", "status", "exception_type",
                   "error_message", "transient"}


# ---------------------------------------------------------------------------------------------
# 1. Motor real del bridge (self_test, sin TIA)
# ---------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def archive_scenarios(tmp_path_factory) -> dict[str, dict[str, Any]]:
    build = build_openness_bridge(get_project_root())
    if not build.get("built"):
        pytest.skip(f"El bridge TIA Openness no se puede compilar en este entorno: {build.get('errors')}")
    work = tmp_path_factory.mktemp("archive_self_test")
    request, result = work / "request.json", work / "result.json"
    request.write_text(json.dumps({"action": "self_test", "result_path": str(result)}), encoding="utf-8")
    completed = subprocess.run([build["exe_path"], str(request)], capture_output=True, text=True, timeout=60, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(result.read_text(encoding="utf-8-sig"))
    assert report["status"] == "SELF_TEST_PASSED", report.get("errors")
    return {check["archive_scenario"]: check for check in report["checks"] if "archive_scenario" in check}


def test_a_bridge_archive_pass_on_first_attempt_has_no_wait(archive_scenarios):
    s = archive_scenarios["pass_first"]
    assert (s["status"], s["attempt_count"], s["calls"], s["recovered"], s["sleeps"]) == ("CREATED", 1, 1, False, [])
    assert s["attempt_statuses"] == ["CREATED"] and s["sha256"] and s["error_kept"] is False


def test_b_bridge_could_not_find_file_then_pass_on_second_attempt(archive_scenarios):
    s = archive_scenarios["transient_then_pass"]
    assert (s["status"], s["attempt_count"], s["recovered"], s["sleeps"]) == ("CREATED", 2, True, [2000])
    assert s["attempt_statuses"] == ["FAILED", "CREATED"] and s["transient_flags"] == [True, False]
    assert s["error_kept"] is False  # el error del intento 1 queda solo en archive_attempts


def test_c_bridge_two_failures_then_pass_on_third_attempt(archive_scenarios):
    s = archive_scenarios["two_transient_then_pass"]
    assert (s["status"], s["attempt_count"], s["recovered"], s["sleeps"]) == ("CREATED", 3, True, [2000, 3000])
    assert s["attempt_statuses"] == ["FAILED", "FAILED", "CREATED"]


def test_d_bridge_three_failures_stop_at_the_maximum(archive_scenarios):
    s = archive_scenarios["three_transient"]
    assert (s["status"], s["attempt_count"], s["calls"], s["recovered"]) == ("TRIAL_ARCHIVE_FAILED", 3, 3, False)
    assert s["sleeps"] == [2000, 3000] and s["files"] == [] and s["error_kept"] is True


@pytest.mark.parametrize("scenario", ["other_error_no_retry", "io_exception_no_retry"])
def test_e_bridge_other_archive_errors_are_never_retried(archive_scenarios, scenario):
    # ETIE con otro mensaje, o el mismo texto en otro tipo de excepcion: un solo intento, sin espera.
    s = archive_scenarios[scenario]
    assert (s["status"], s["attempt_count"], s["calls"], s["sleeps"]) == ("TRIAL_ARCHIVE_FAILED", 1, 1, [])
    assert s["transient_flags"] == [False]


def test_bridge_partial_target_is_quarantined_never_deleted(archive_scenarios):
    s = archive_scenarios["partial_target_quarantined"]
    assert s["status"] == "CREATED" and s["target_after_failure"][0] == "PARTIAL_QUARANTINED"
    assert s["files"] == ["T0001.zap18", "T0001.zap18.partial_attempt1"]


def test_bridge_complete_target_after_failure_is_kept_and_not_overwritten(archive_scenarios):
    s = archive_scenarios["complete_target_kept"]
    assert (s["status"], s["calls"], s["target_after_failure"]) == ("TRIAL_ARCHIVE_FAILED", 1, ["COMPLETE_KEPT"])
    assert s["files"] == ["T0001.zap18"]


def test_bridge_preexisting_target_is_never_archived_over(archive_scenarios):
    s = archive_scenarios["preexisting_target"]
    assert (s["status"], s["attempt_count"], s["calls"]) == ("TRIAL_ARCHIVE_FAILED", 0, 0)


def test_l_bridge_every_attempt_records_all_fields(archive_scenarios):
    assert all(s["attempt_fields_complete"] for s in archive_scenarios.values())


def test_policy_is_wired_only_into_the_trial_path_after_save():
    source = (_ROOT / "tia_openness_bridge" / "Program.cs").read_text(encoding="utf-8")
    assert "TrialArchiveMaxAttempts = 3" in source and "TrialArchiveSettleMs = 2000" in source
    assert "ArchiveRetryBackoffMs = { 2000, 3000 }" in source
    trial = source.index('ArchiveProject(project, trialArchiveDir, trialArchiveName, report, "TRIAL", TrialArchiveMaxAttempts)')
    save, settle = source.rindex("project.Save();", 0, trial), source.rindex("Thread.Sleep(TrialArchiveSettleMs)", 0, trial)
    assert save < settle < trial  # Save -> espera fija -> Archive con reintento
    assert 'ArchiveProject(project, archiveDir, archiveName, report, "MASTER");' in source  # MASTER: un intento


# ---------------------------------------------------------------------------------------------
# 2. Integracion Python (mismo contrato de reporte que el bridge)
# ---------------------------------------------------------------------------------------------

def _attempt_dir(trial_dir: Path) -> Path:
    return trial_dir / "evaluation" / "attempt_001"


@pytest.mark.parametrize("outcome,count", [("PASS", 1), ("ARCHIVE_RECOVERED", 2), ("ARCHIVE_RECOVERED_3", 3)])
def test_recovered_archive_continues_to_evidence_handshake_download_and_oracle(tmp_path, outcome, count):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    bridge = _FakeBridge(outcome)
    result = _evaluate(root, trial_dir, bridge)
    record = trial_model.load_trial(trial_dir)
    # Un fallo transitorio recuperado NO convierte el ensayo en INFRASTRUCTURE_ERROR.
    assert result["final_status"] == "PASS" and record["failure_category"] == ED.SUCCESS
    assert record["tia_archive"]["status"] == "CREATED"
    assert record["tia_archive"]["attempt_count"] == count
    assert record["tia_archive"]["recovered_after_retry"] is (count > 1)
    assert result["archive_attempt_count"] == count and result["archive_recovered_after_retry"] is (count > 1)
    assert bridge.decisions == [{"download": True, "reason": "EVIDENCE_VERIFIED"}]  # F: download tras archive valido
    assert (_attempt_dir(trial_dir) / DE.DOWNLOAD_REPORT).exists() and record["stages"]["download_success"] is True


def test_f_g_d_all_attempts_failed_is_archive_failure_with_download_not_run(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    bridge = _FakeBridge("ARCHIVE_FAILED")
    result = _evaluate(root, trial_dir, bridge)
    record = trial_model.load_trial(trial_dir)
    assert result["final_status"] == "INFRASTRUCTURE_ERROR"
    assert record["failure_category"] == ED.ARCHIVE_FAILURE and record["infrastructure_error"] is True
    assert getattr(bridge, "decisions", []) == []  # nunca hubo handshake: Download jamas se llamo
    assert not (_attempt_dir(trial_dir) / DE.DOWNLOAD_REPORT).exists()
    assert record["stages"]["download_success"] is None and result["download_success"] is None  # nunca False
    summary = DE.trial_stage_summary(record)
    assert summary["compilation"] == "PASS" and summary["tia_archive"] == "FAIL"
    for stage in ("download", "runtime", "functional", "safety"):
        assert summary[stage] == DE.STAGE_NOT_RUN, stage
    assert summary["final_verdict"] == "INFRASTRUCTURE_ERROR"
    assert "Could not find file" in record["tia_archive"]["reason"]
    assert record["tia_archive"]["attempt_count"] == 3 and record["tia_archive"]["recovered_after_retry"] is False
    assert (root / "tiaw" / "T0001").exists()  # workspace conservado para diagnostico


def test_h_i_retry_never_reinterprets_or_regenerates(tmp_path, no_regeneration):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    frozen = {name: DE.sha256_file(trial_dir / name) for name in (DE.PROGRAM_FILENAME, DE.VARIABLES_FILENAME, DE.SEMANTIC_FILENAME)}
    bridge = _FakeBridge("ARCHIVE_RECOVERED_3")
    result = _evaluate(root, trial_dir, bridge)  # no_regeneration: cualquier LLM/IR/SCL lanzaria AssertionError
    assert result["final_status"] == "PASS"
    assert {name: DE.sha256_file(trial_dir / name) for name in frozen} == frozen
    # Los reintentos ocurren DENTRO de una unica sesion del bridge (sin Retrieve/compilacion nuevos).
    assert len(bridge.requests) == 1
    assert bridge.requests[0]["source_path"].endswith(".scl")


def test_j_retry_never_modifies_master(tmp_path):
    root = _project(tmp_path)
    _master(root)
    master = DE.load_master_config(root)
    snapshot = Path(master["snapshot"]["archive_path"])
    before = (DE.sha256_file(snapshot), DE.master_folder_fingerprint(master["path"]))
    result = _evaluate(root, _generated_trial(root), _FakeBridge("ARCHIVE_RECOVERED"))
    assert result["master_intact"] is True
    assert (DE.sha256_file(snapshot), DE.master_folder_fingerprint(master["path"])) == before


def test_k_same_trial_same_evaluation_attempt_same_workspace(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    result = _evaluate(root, trial_dir, _FakeBridge("ARCHIVE_RECOVERED_3"))
    record = trial_model.load_trial(trial_dir)
    assert result["attempt"] == 1 and len(record["evaluation"]["attempts"]) == 1
    assert sorted(p.name for p in (trial_dir / "evaluation").iterdir()) == ["attempt_001"]
    assert list(TW.load_registry(root)["workspaces"]) == ["T0001"]  # un unico workspace TIA


def test_l_all_archive_attempts_are_persisted_in_reports(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    _evaluate(root, trial_dir, _FakeBridge("ARCHIVE_RECOVERED_3"))
    compile_report = json.loads((_attempt_dir(trial_dir) / DE.COMPILE_REPORT).read_text(encoding="utf-8"))
    manifest = json.loads((_attempt_dir(trial_dir) / "tia" / DE.TIA_PROJECT_MANIFEST).read_text(encoding="utf-8"))
    for archive in (compile_report["archive"], manifest["archive"]):
        assert archive["attempt_count"] == 3 and archive["recovered_after_retry"] is True
        assert [a["status"] for a in archive["attempts"]] == ["FAILED", "FAILED", "CREATED"]
        assert [a["transient"] for a in archive["attempts"]] == [True, True, False]
        assert all(_ATTEMPT_FIELDS <= set(a) for a in archive["attempts"])
        assert archive["settle_ms"] == 2000 and archive["max_attempts"] == 3 and archive["retry_backoff_ms"] == [2000, 3000]


def test_m_final_zap18_has_a_valid_verified_hash(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    _evaluate(root, trial_dir, _FakeBridge("ARCHIVE_RECOVERED"))
    record = trial_model.load_trial(trial_dir)
    evidence = Path(record["tia_archive"]["zap18_path"])
    manifest = json.loads((_attempt_dir(trial_dir) / "tia" / DE.TIA_PROJECT_MANIFEST).read_text(encoding="utf-8"))
    assert evidence.is_file()
    assert DE.sha256_file(evidence) == record["tia_archive"]["zap18_hash"] == manifest["archive"]["evidence_hash"] \
        == manifest["archive"]["workspace_hash"]


def test_legacy_bridge_without_archive_trace_is_reported_as_unknown_never_invented():
    assert DE.archive_attempts_trace({"archive_status": "CREATED"})["attempt_count"] is None
    assert DE.archive_attempts_trace({})["attempts"] == []


def test_legacy_record_with_archive_fail_shows_download_not_run_and_archive_failure():
    # trial.json real anterior a la correccion: Archive NOT_CREATED y download_success=False por omision.
    record = {"final_status": "INFRASTRUCTURE_ERROR", "final_verdict": "INFRASTRUCTURE_ERROR",
              "stages": {"compile_success": True, "download_success": False},
              "tia_archive": {"status": "NOT_CREATED"}, "download": {"status": None, "cpu_run_confirmed": None},
              "evaluation": {"status": "INFRASTRUCTURE_ERROR", "final_verdict": "INFRASTRUCTURE_ERROR",
                             "attempts": [{"attempt": 1, "download_success": False}]}}
    assert ED.classify_trial(record)["failure_category"] == ED.ARCHIVE_FAILURE
    assert ED.ARCHIVE_FAILURE in ED.INFRASTRUCTURE_CATEGORIES
    summary = DE.trial_stage_summary(record)
    assert summary["tia_archive"] == "FAIL" and summary["download"] == DE.STAGE_NOT_RUN


def test_not_run_only_marks_the_tail_never_a_gap_between_executed_stages():
    # Runtime con evidencia pero Download sin ella: Download es desconocido ("-"), nunca NOT_RUN ni PASS deducido.
    record = {"stages": {}, "tia_archive": {"status": "CREATED"}, "download": {"cpu_run_confirmed": True},
              "evaluation": {"final_verdict": "INFRASTRUCTURE_ERROR", "attempts": [{"attempt": 1}]}}
    summary = DE.trial_stage_summary(record)
    assert (summary["download"], summary["runtime"]) == ("-", "PASS")
    assert (summary["functional"], summary["safety"]) == (DE.STAGE_NOT_RUN, DE.STAGE_NOT_RUN)


def test_pending_trial_keeps_dash_not_not_run():
    record = {"stages": {}, "evaluation": {"status": "PENDING", "attempts": []}}
    summary = DE.trial_stage_summary(record)
    assert all(summary[stage] == "-" for stage in ("download", "runtime", "functional", "safety"))
