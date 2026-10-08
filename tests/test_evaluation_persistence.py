"""
Persistencia del veredicto ANTES de limpiar el workspace TIA (incidente TEXT_DEV_20261006_003:
D03_V1/V2_TEXT_DEV_001 terminaron el Oracle con REVIEW, pero shutil.rmtree del workspace fallo y
evaluate_trial lanzo antes de guardar trial.json -> evaluation RUNNING, attempts [], final_verdict null,
y el lote lo interpreto como INTERRUPTED).

La limpieza es mantenimiento: nunca puede impedir ni alterar un resultado experimental ya obtenido.
TIA/PLCSIM/Oracle se sustituyen por dobles; todo ocurre en copias temporales del proyecto.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from trial_experiments import batch_runner as B  # noqa: E402
from trial_experiments import deferred_evaluator as DE  # noqa: E402
from trial_experiments import persistence_audit as PA  # noqa: E402
from trial_experiments import text_batch as TB  # noqa: E402
from trial_experiments import tia_workspace as TW  # noqa: E402
from trial_experiments import trial_model  # noqa: E402

from test_phase4a_deferred_evaluation import (  # noqa: E402
    _FakeBridge, _generated_trial, _master, _oracle_pass, _project, _runtime, no_regeneration)

__all__ = ["no_regeneration"]

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)
_FROZEN = ("data/experiment_cases/canonical_cases.json", "data/experimental_design.json",
           "data/plc_maps/mapa_banco_fisico_base.json", "data/plc_maps/profiles.json", "data/plc_maps/experiment_variants.json")
_FROZEN_BEFORE = {name: B.file_hash(_ROOT / name) for name in _FROZEN}
NO_GIT = {"commit": "abc123", "dirty": False, "dirty_files": []}
_WINERROR_32 = "[WinError 32] El proceso no tiene acceso al archivo porque esta siendo utilizado por otro proceso"


def _oracle(verdict: str, duration_ms: int = 900):
    """Doble del Oracle con veredicto PASS / FAIL / REVIEW."""
    def _run(oracle, snapshot_path, runtime_report, target_type, semantic_output=None, project_root=None, **kwargs):
        result = _oracle_pass(oracle, snapshot_path, runtime_report, target_type, semantic_output, project_root)
        result["duration_ms"] = duration_ms
        if verdict == "FAIL":
            result["functional"] = {**result["functional"], "success": False, "passed_checks": 1}
            result.update({"verdict": "FAIL", "verdict_reason": "FUNCTIONAL_CHECK_FAILED"})
        elif verdict == "REVIEW":
            result["functional"] = {**result["functional"], "evaluated": False, "success": None}
            result["preconditions"] = {"success": False}
            result.update({"verdict": "REVIEW", "verdict_reason": "PRECONDITION_FAILED"})
        return result
    return _run


def _evaluate(root: Path, trial_dir: Path, verdict: str = "PASS", bridge: Any = None, duration_ms: int = 900,
              retry_reason: str | None = None) -> dict[str, Any]:
    return DE.evaluate_trial(root, trial_dir, retry_reason, bridge=bridge or _FakeBridge(), runtime_status_fn=_runtime,
                             oracle_fn=_oracle(verdict, duration_ms), log=lambda _m: None)


@pytest.fixture
def fast_cleanup(monkeypatch):
    monkeypatch.setattr(TW, "CLEANUP_RETRY_DELAYS_S", (0.0, 0.0))


@pytest.fixture
def rmtree_denied(monkeypatch, fast_cleanup):
    """shutil.rmtree del workspace falla como en la PC EVAL (WinError 32)."""
    calls: list[str] = []

    def _denied(path, *args, **kwargs):
        calls.append(str(path))
        raise PermissionError(13, _WINERROR_32, str(path))

    monkeypatch.setattr(TW.shutil, "rmtree", _denied)
    return calls


def _attempt(record: dict[str, Any]) -> dict[str, Any]:
    return record["evaluation"]["attempts"][-1]


def _assert_persisted(trial_dir: Path, verdict: str) -> dict[str, Any]:
    record = trial_model.load_trial(trial_dir)
    assert record["final_verdict"] == record["final_status"] == verdict
    assert record["evaluation"]["final_verdict"] == verdict
    assert record["evaluation"]["status"] == DE.EVALUATION_COMPLETED  # nunca RUNNING
    assert record["lifecycle_state"] == DE.STATE_EVALUATED
    assert len(record["evaluation"]["attempts"]) == 1 and _attempt(record)["final_status"] == verdict
    assert record["oracle"]["verdict"] == verdict
    return record


# ---------------------------------------------------------------------------------------------
# A-C, G: el veredicto sobrevive a un fallo de rmtree (PermissionError / WinError 32)
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("verdict", ["PASS", "FAIL", "REVIEW"])
def test_verdict_survives_rmtree_permission_error(tmp_path, rmtree_denied, verdict):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    result = _evaluate(root, trial_dir, verdict)  # no lanza
    assert result["aborted"] is False and result["final_status"] == verdict
    assert rmtree_denied, "la limpieza se intento"
    record = _assert_persisted(trial_dir, verdict)
    cleanup = _attempt(record)["workspace_cleanup"]
    assert cleanup["status"] == TW.CLEANUP_FAILED and cleanup["error_type"] == "PermissionError"
    assert "WinError 32" in cleanup["error_message"]
    assert cleanup["workspace_path"] == result["tia_workspace_path"] and cleanup["timestamp"]
    assert _attempt(record)["tia_workspace_cleaned"] is False and result["tia_workspace_cleaned"] is False
    # Diagnostico persistido (G): reporte del intento con traceback y registro del workspace.
    report = json.loads((trial_dir / "evaluation" / "attempt_001" / DE.CLEANUP_REPORT).read_text(encoding="utf-8"))
    assert report["status"] == TW.CLEANUP_FAILED and report["trial_id"] == trial_dir.name and report["attempt"] == 1
    assert "PermissionError" in report["traceback"]
    entry = TW.load_registry(root)["workspaces"][result["tia_workspace_id"]]
    assert entry["state"] == TW.STATE_KEPT and entry["keep_reason"].startswith("CLEANUP_FAILED")
    assert entry["final_status"] == verdict
    # El veredicto del Oracle en evaluation_report.json coincide con trial.json.
    evaluation_report = json.loads((trial_dir / "evaluation" / "attempt_001" / "evaluation_report.json").read_text(encoding="utf-8"))
    assert evaluation_report["final_status"] == verdict and evaluation_report["oracle_verdict"] == verdict


def test_failed_cleanup_keeps_every_workspace_file(tmp_path, rmtree_denied):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    result = _evaluate(root, trial_dir, "REVIEW")
    workspace = Path(result["tia_workspace_path"])
    assert workspace.is_dir() and (workspace / TW.SOURCE_FILENAME).is_file() and (workspace / f"{result['tia_workspace_id']}.zap18").is_file()
    assert not list(workspace.parent.glob(f"{result['tia_workspace_id']}{TW.CLEANUP_STAGING_SUFFIX}"))  # nada quedo a medio mover


# ---------------------------------------------------------------------------------------------
# D: REVIEW con duracion minima; M: timing completo
# ---------------------------------------------------------------------------------------------

def test_review_with_minimal_duration_is_persisted_with_its_timing(tmp_path, rmtree_denied):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    _evaluate(root, trial_dir, "REVIEW", duration_ms=0)
    record = _assert_persisted(trial_dir, "REVIEW")
    timing = record["timing"]
    assert timing["oracle_ms"] == 0 and timing["compile_ms"] is not None and timing["runtime_ms"] == 120
    assert timing["evaluation_ms"] is not None and timing["evaluation_ms"] >= 0
    assert record["stages"]["compile_success"] is True and record["stages"]["download_success"] is True
    assert DE.trial_stage_summary(record)["functional"] == "REVIEW"
    assert DE.trial_stage_summary(record)["final_verdict"] == "REVIEW"
    assert DE.trial_status_label(record) == "REVIEW / COMPLETADO"


# ---------------------------------------------------------------------------------------------
# E: limpieza exitosa (comportamiento previo intacto)
# ---------------------------------------------------------------------------------------------

def test_successful_cleanup_is_unchanged(tmp_path, fast_cleanup):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    result = _evaluate(root, trial_dir, "PASS")
    assert result["tia_workspace_cleaned"] is True and not Path(result["tia_workspace_path"]).exists()
    record = _assert_persisted(trial_dir, "PASS")
    assert _attempt(record)["tia_workspace_cleaned"] is True
    assert _attempt(record)["workspace_cleanup"]["status"] == TW.CLEANUP_CLEANED
    assert TW.load_registry(root)["workspaces"][result["tia_workspace_id"]]["state"] == TW.STATE_CLEANED
    assert not list(Path(result["tia_workspace_path"]).parent.glob(f"*{TW.CLEANUP_STAGING_SUFFIX}"))


def test_infrastructure_error_still_keeps_the_workspace_without_trying_to_clean(tmp_path, fast_cleanup, monkeypatch):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    monkeypatch.setattr(TW.shutil, "rmtree", lambda *a, **k: pytest.fail("un INFRASTRUCTURE_ERROR nunca se limpia"))
    result = _evaluate(root, trial_dir, bridge=_FakeBridge("NON_RECOVERABLE"))
    record = trial_model.load_trial(trial_dir)
    assert record["final_verdict"] == "INFRASTRUCTURE_ERROR" and record["evaluation"]["status"] == DE.EVALUATION_INFRASTRUCTURE
    assert _attempt(record)["workspace_cleanup"]["status"] == TW.CLEANUP_SKIPPED
    assert TW.load_registry(root)["workspaces"][result["tia_workspace_id"]]["state"] == TW.STATE_KEPT


# ---------------------------------------------------------------------------------------------
# F: workspace bloqueado (archivo abierto) -> KEPT sin borrar nada
# ---------------------------------------------------------------------------------------------

class _LockingBridge(_FakeBridge):
    """Como TIA cuando un proceso sigue reteniendo una base de datos del proyecto tras cerrar la sesion."""

    def __init__(self) -> None:
        super().__init__("PASS")
        self.handles: list[Any] = []

    def __call__(self, request, work_dir, project_root=None, on_archived=None):
        report = super().__call__(request, work_dir, project_root, on_archived)
        db = Path(request["working_dir"]) / "XRef.db"
        handle = open(db, "wb")
        handle.write(b"xref")
        handle.flush()
        self.handles.append(handle)
        return report


def test_locked_workspace_is_kept_untouched_and_the_verdict_persisted(tmp_path, fast_cleanup, monkeypatch):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    if os.name != "nt":  # en Windows el bloqueo es real; en otros sistemas se simula el mismo error
        def _busy(source, target):
            raise PermissionError(5, "[WinError 5] Acceso denegado", str(source))
        monkeypatch.setattr(TW, "_rename", _busy)
    removed: list[str] = []
    real_rmtree = shutil.rmtree
    monkeypatch.setattr(TW.shutil, "rmtree", lambda path, *a, **k: removed.append(str(path)) or real_rmtree(path, *a, **k))
    bridge = _LockingBridge()
    try:
        result = _evaluate(root, trial_dir, "REVIEW", bridge=bridge)
    finally:
        for handle in bridge.handles:
            handle.close()
    assert removed == []  # el sondeo detecto el bloqueo ANTES de borrar nada
    record = _assert_persisted(trial_dir, "REVIEW")
    cleanup = _attempt(record)["workspace_cleanup"]
    assert cleanup["status"] == TW.CLEANUP_FAILED and cleanup["error_code"] == TW.ERROR_WORKSPACE_IN_USE
    assert cleanup["probe_attempts"] == 3  # 1 + reintentos configurados
    workspace = Path(result["tia_workspace_path"])
    assert (workspace / "p" / "XRef.db").is_file() and (workspace / TW.SOURCE_FILENAME).is_file()
    assert TW.load_registry(root)["workspaces"][result["tia_workspace_id"]]["state"] == TW.STATE_KEPT
    # Cuando el proceso suelta el archivo, la limpieza manual (--include-kept) lo borra.
    assert TW.cleanup_workspaces(root, include_kept=True)["removed"] == [result["tia_workspace_id"]]
    assert not workspace.exists()


def test_unexpected_cleanup_exception_never_loses_the_verdict(tmp_path, fast_cleanup, monkeypatch):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)

    def _boom(*args, **kwargs):
        raise RuntimeError("fallo inesperado en el mantenimiento")

    monkeypatch.setattr(TW, "remove_workspace_safe", _boom)
    result = _evaluate(root, trial_dir, "FAIL")
    record = _assert_persisted(trial_dir, "FAIL")
    cleanup = _attempt(record)["workspace_cleanup"]
    assert cleanup["status"] == TW.CLEANUP_FAILED and cleanup["error_type"] == "RuntimeError"
    assert Path(result["tia_workspace_path"]).exists()
    assert TW.load_registry(root)["workspaces"][result["tia_workspace_id"]]["state"] == TW.STATE_KEPT


# ---------------------------------------------------------------------------------------------
# Seguridad: la limpieza solo actua sobre el workspace del ensayo
# ---------------------------------------------------------------------------------------------

def test_cleanup_guard_refuses_anything_but_the_trials_own_workspace(tmp_path, fast_cleanup):
    root = _project(tmp_path)
    config = _master(root)
    workspace = TW.allocate(root, "D03_V1_TEXT_DEV_001", 1, tmp_path / "t")
    TW.update_entry(root, workspace["workspace_id"], state=TW.STATE_EVIDENCE_COPIED, evidence_copied_ok=True)
    wrong_trial = TW.remove_workspace_safe(root, workspace["workspace_id"], expected_trial_id="D03_V2_TEXT_DEV_001", expected_attempt=1)
    wrong_attempt = TW.remove_workspace_safe(root, workspace["workspace_id"], expected_trial_id="D03_V1_TEXT_DEV_001", expected_attempt=2)
    for outcome in (wrong_trial, wrong_attempt):
        assert outcome["status"] == TW.CLEANUP_FAILED and outcome["error_code"] == TW.ERROR_WORKSPACE_GUARD
    assert Path(workspace["path"]).is_dir()
    for bad_id in ("..", "T0001/..", "tia_master", "results", "", "T1"):
        assert TW.remove_workspace_safe(root, bad_id)["error_code"] in (TW.ERROR_WORKSPACE_GUARD, None)
        assert TW.remove_workspace_safe(root, bad_id)["status"] != TW.CLEANUP_CLEANED
    # Un registro manipulado que apunta fuera de tiaw/ nunca se sigue.
    TW.update_entry(root, workspace["workspace_id"], path=str(root / "tia_master"))
    assert TW.remove_workspace_safe(root, workspace["workspace_id"])["error_code"] == TW.ERROR_WORKSPACE_GUARD
    # Raiz de workspaces mal configurada (dentro de results/ o del MASTER): nunca se borra nada.
    for protected in (root / "results" / "x", Path(config["path"]).parent / "w"):
        assert TW.check_cleanup_target(protected / "T0009", protected, "T0009", {}, project_root=root,
                                       protected=[Path(config["path"]).parent])
    assert Path(config["path"]).is_file() and Path(config["snapshot"]["archive_path"]).is_file()


def test_active_workspace_is_never_removed(tmp_path, fast_cleanup):
    root = _project(tmp_path)
    active = TW.allocate(root, "D03_V1_TEXT_DEV_001", 1, tmp_path / "t")
    outcome = TW.remove_workspace_safe(root, active["workspace_id"])
    assert outcome["status"] == TW.CLEANUP_SKIPPED and Path(active["path"]).is_dir()
    assert TW.load_registry(root)["workspaces"][active["workspace_id"]]["state"] == TW.STATE_ACTIVE


# ---------------------------------------------------------------------------------------------
# H, N: el lote recibe el REVIEW persistido, continua y no lo ve como INTERRUPTED al reanudar
# ---------------------------------------------------------------------------------------------

def test_batch_continues_with_a_persisted_review_despite_cleanup_failure(tmp_path, rmtree_denied):
    root = _project(tmp_path)
    _master(root)
    batch_dir, manifest = TB.create_batch(root, trial_model.PHASE_DEVELOPMENT, ["D03"], ["V1", "V2"], git=NO_GIT)
    first = manifest["ordered_trial_plan"][0]
    trial_dir = _generated_trial(root, "D03", "V1")
    TB.mark_started(manifest)
    TB.begin_entry(manifest, first, trial_dir, trial_dir.name)
    TB.mark_evaluating(manifest, first)
    _evaluate(root, trial_dir, "REVIEW")
    decision = TB.record_trial_result(root, batch_dir, manifest, first)
    assert decision == TB.DECISION_CONTINUE and first["status"] == TB.ENTRY_COMPLETED
    assert first["result"]["final_verdict"] == "REVIEW" and first["result"]["functional"] == "REVIEW"
    saved = TB.load_manifest(batch_dir)
    assert saved["results"][trial_dir.name] == "REVIEW" and saved["status"] == TB.STATUS_RUNNING
    assert TB.progress(saved)["review"] == 1 and TB.progress(saved)["interrupted"] == 0
    rows = (batch_dir / TB.SUMMARY_CSV).read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2 and ",REVIEW," in rows[1]


def test_resume_never_interprets_a_persisted_review_as_interrupted(tmp_path, rmtree_denied):
    root = _project(tmp_path)
    _master(root)
    batch_dir, manifest = TB.create_batch(root, trial_model.PHASE_DEVELOPMENT, ["D03"], ["V1"], git=NO_GIT)
    entry = manifest["ordered_trial_plan"][0]
    trial_dir = _generated_trial(root, "D03", "V1")
    TB.begin_entry(manifest, entry, trial_dir, trial_dir.name)
    TB.mark_evaluating(manifest, entry)
    TB.save_manifest(batch_dir, manifest)  # la GUI se cerro tras el Oracle, antes de registrar el resultado
    _evaluate(root, trial_dir, "REVIEW")
    issues = TB.reconcile(root, manifest)
    assert issues == [] and entry["status"] == TB.ENTRY_COMPLETED and entry["result"]["final_verdict"] == "REVIEW"


# ---------------------------------------------------------------------------------------------
# I, J, K, L: sin nueva generacion, intentos y evidencia intactos, MASTER intacto
# ---------------------------------------------------------------------------------------------

def test_no_regeneration_and_evidence_untouched_after_cleanup_failure(tmp_path, rmtree_denied, no_regeneration):
    root = _project(tmp_path)
    config = _master(root)
    master_fingerprint = DE.master_folder_fingerprint(config["path"])
    snapshot_hash = DE.sha256_file(Path(config["snapshot"]["archive_path"]))
    trial_dir = _generated_trial(root)
    frozen = {name: DE.sha256_file(trial_dir / name) for name in DE.FROZEN_ARTIFACTS}
    bridge = _FakeBridge()
    result = _evaluate(root, trial_dir, "REVIEW", bridge=bridge)
    attempt_dir = trial_dir / "evaluation" / "attempt_001"
    zap = attempt_dir / "tia" / f"{trial_dir.name}.zap18"
    record = _assert_persisted(trial_dir, "REVIEW")
    # K: .zap18 de evidencia identico al verificado.
    assert DE.sha256_file(zap) == record["tia_archive"]["zap18_hash"]
    evidence = {path.relative_to(attempt_dir): DE.sha256_file(path) for path in attempt_dir.rglob("*") if path.is_file()}
    # I: un REVIEW persistido nunca se vuelve a evaluar ni a generar (no es PENDING ni INFRASTRUCTURE_ERROR).
    again = _evaluate(root, trial_dir, "PASS", bridge=bridge)
    assert again["aborted"] is True and any(DE.ERROR_NOT_PENDING in error for error in again["errors"])
    assert len(bridge.requests) == 1
    # J: attempt_001 y los artefactos congelados quedan intactos; no aparece un attempt_002.
    assert {path.relative_to(attempt_dir): DE.sha256_file(path) for path in attempt_dir.rglob("*") if path.is_file()} == evidence
    assert not (trial_dir / "evaluation" / "attempt_002").exists()
    assert {name: DE.sha256_file(trial_dir / name) for name in DE.FROZEN_ARTIFACTS} == frozen
    # L: MASTER y su snapshot intactos.
    assert DE.master_folder_fingerprint(config["path"]) == master_fingerprint
    assert DE.sha256_file(Path(config["snapshot"]["archive_path"])) == snapshot_hash
    assert trial_model.load_trial(trial_dir)["final_verdict"] == "REVIEW"


def test_infrastructure_retry_keeps_attempt_001_when_cleanup_fails(tmp_path, rmtree_denied):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    _evaluate(root, trial_dir, bridge=_FakeBridge("NON_RECOVERABLE"))
    first = {path.relative_to(trial_dir): DE.sha256_file(path) for path in (trial_dir / "evaluation" / "attempt_001").rglob("*") if path.is_file()}
    _evaluate(root, trial_dir, "REVIEW", retry_reason="PLCSIM reiniciado")
    record = trial_model.load_trial(trial_dir)
    assert [a["final_status"] for a in record["evaluation"]["attempts"]] == ["INFRASTRUCTURE_ERROR", "REVIEW"]
    assert record["final_verdict"] == "REVIEW" and _attempt(record)["workspace_cleanup"]["status"] == TW.CLEANUP_FAILED
    assert {path.relative_to(trial_dir): DE.sha256_file(path) for path in (trial_dir / "evaluation" / "attempt_001").rglob("*") if path.is_file()} == first


# ---------------------------------------------------------------------------------------------
# O + diagnostico del worker: fallos inesperados ANTES del veredicto
# ---------------------------------------------------------------------------------------------

def test_unexpected_failure_before_the_verdict_is_diagnosed_and_stays_unfinished(tmp_path, fast_cleanup, monkeypatch):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value-1234567890")

    def _oracle_crash(*args, **kwargs):
        raise ValueError("Oracle exploto con sk-test-secret-value-1234567890 en el mensaje")

    with pytest.raises(ValueError) as caught:
        DE.evaluate_trial(root, trial_dir, None, bridge=_FakeBridge(), runtime_status_fn=_runtime, oracle_fn=_oracle_crash, log=lambda _m: None)
    diagnostic_path = Path(caught.value.diagnostic_path)
    payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic_path.parent == trial_dir / "evaluation" / DE.DIAGNOSTICS_DIRNAME
    assert payload["exception_type"] == "ValueError" and payload["phase"] == "oracle"
    assert payload["trial_id"] == trial_dir.name and payload["attempt"] == 1 and payload["timestamp"]
    assert "Traceback" in payload["traceback"] and "_oracle_crash" in payload["traceback"]
    text = diagnostic_path.read_text(encoding="utf-8")
    assert "sk-test-secret-value-1234567890" not in text  # nunca secretos
    record = trial_model.load_trial(trial_dir)
    # Sin veredicto: no se inventa ninguno; el ensayo sigue sin terminar (el lote lo vera INTERRUPTED).
    assert record["evaluation"]["status"] == "RUNNING" and record.get("final_verdict") is None
    assert record["evaluation"]["last_unexpected_error"]["phase"] == "oracle"
    assert TB.outcome_for_record(record) == (TB.ENTRY_INTERRUPTED, TB.PAUSE_INTERRUPTED)
    # El workspace queda conservado para diagnostico.
    entry = TW.load_registry(root)["workspaces"][record["evaluation"]["tia_workspace_id"]]
    assert entry["state"] == TW.STATE_KEPT and "UNEXPECTED_ERROR" in entry["keep_reason"]


def test_worker_exception_recorder_never_raises_and_redacts(tmp_path, monkeypatch):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-another-secret-abcdefghijkl")
    try:
        raise RuntimeError("api_key=sk-another-secret-abcdefghijkl password: hunter2")
    except RuntimeError as error:
        path = DE.record_unexpected_error(trial_dir, error, "gui_deferred_worker")
    text = Path(path).read_text(encoding="utf-8")
    assert "sk-another-secret" not in text and "hunter2" not in text and "gui_deferred_worker" in text
    assert DE.record_unexpected_error(tmp_path / "no_existe", RuntimeError("x"), "gui_deferred_worker") is None
    assert not (tmp_path / "no_existe").exists()


def test_failed_persistence_verification_never_cleans_the_workspace(tmp_path, fast_cleanup, monkeypatch):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    monkeypatch.setattr(DE, "_verify_persisted", lambda *a, **k: ["final_verdict no coincide"])
    monkeypatch.setattr(TW, "remove_workspace_safe", lambda *a, **k: pytest.fail("no se limpia sin veredicto verificado"))
    with pytest.raises(RuntimeError, match=DE.ERROR_PERSISTENCE_VERIFICATION) as caught:
        _evaluate(root, trial_dir, "REVIEW")
    payload = json.loads(Path(caught.value.diagnostic_path).read_text(encoding="utf-8"))
    assert payload["phase"] == "verify_persistence"


# ---------------------------------------------------------------------------------------------
# Escritura atomica de trial.json
# ---------------------------------------------------------------------------------------------

def test_trial_json_write_is_atomic_and_retries_a_transient_lock(tmp_path, monkeypatch):
    directory = tmp_path / "t"
    trial_model.save_trial(directory, {"trial_id": "X", "n": 1})
    monkeypatch.setattr(trial_model, "_REPLACE_RETRY_DELAYS_S", (0.0, 0.0))
    real_replace = os.replace
    failures = {"left": 2}

    def _flaky(source, target):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError(13, "[WinError 5] Acceso denegado (lector abierto)", str(target))
        return real_replace(source, target)

    monkeypatch.setattr(trial_model.os, "replace", _flaky)
    trial_model.save_trial(directory, {"trial_id": "X", "n": 2})
    assert trial_model.load_trial(directory)["n"] == 2 and not (directory / "trial.json.tmp").exists()
    failures["left"] = 5
    with pytest.raises(PermissionError):
        trial_model.save_trial(directory, {"trial_id": "X", "n": 3})
    assert trial_model.load_trial(directory)["n"] == 2  # nunca un trial.json a medio escribir


# ---------------------------------------------------------------------------------------------
# Auditoria READ-ONLY de ensayos historicos afectados
# ---------------------------------------------------------------------------------------------

def _simulate_historic_incident(root: Path, trial_dir: Path, verdict: str, monkeypatch) -> None:
    """Reproduce el estado de la PC EVAL: el resultado nunca llego a trial.json."""
    running = trial_model.load_trial(trial_dir)
    _evaluate(root, trial_dir, verdict)
    record = trial_model.load_trial(trial_dir)
    historic = {**running, "evaluation": {**record["evaluation"], "status": "RUNNING", "attempts": [], "final_verdict": None,
                                          "completed_at": None}}
    historic.pop("final_verdict", None)
    historic["final_status"] = None
    trial_model.save_trial(trial_dir, historic)


def _tree_hashes(directory: Path) -> dict[str, str]:
    return {str(path.relative_to(directory)): DE.sha256_file(path) for path in sorted(directory.rglob("*")) if path.is_file()}


def test_audit_reconstructs_the_original_review_without_writing_anything(tmp_path, fast_cleanup, monkeypatch, no_regeneration):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root, "D03", "V1")
    _simulate_historic_incident(root, trial_dir, "REVIEW", monkeypatch)
    before_trial = _tree_hashes(trial_dir)
    before_tiaw = _tree_hashes(root / "tiaw")
    monkeypatch.setattr(DE, "evaluate_trial", lambda *a, **k: pytest.fail("la auditoria nunca evalua"))
    audit = PA.audit_trial(root, trial_dir)
    assert audit["verdict"] == PA.VERDICT_RECONSTRUCTIBLE and audit["read_only"] is True, "\n".join(PA.summary_lines(audit))
    assert audit["orphan_attempts"] == ["attempt_001"]
    reconstructed = audit["attempt_audits"][-1]["reconstructed"]
    assert reconstructed["final_verdict"] == "REVIEW" and reconstructed["oracle_verdict"] == "REVIEW"
    assert reconstructed["attempt_summary"]["attempt"] == 1 and reconstructed["attempt_summary"]["recovered_from_evidence"]
    assert reconstructed["attempt_summary"]["completed_at"] is None  # nunca se inventa
    assert _tree_hashes(trial_dir) == before_trial and _tree_hashes(root / "tiaw") == before_tiaw
    assert PA.main(["--project-root", str(root), trial_dir.name]) == 0
    assert _tree_hashes(trial_dir) == before_trial


def test_audit_detects_tampered_evidence_and_already_persisted_trials(tmp_path, fast_cleanup, monkeypatch):
    root = _project(tmp_path)
    _master(root)
    persisted = _generated_trial(root, "D03", "V1")
    _evaluate(root, persisted, "PASS")
    assert PA.audit_trial(root, persisted)["verdict"] == PA.VERDICT_ALREADY_PERSISTED
    broken = _generated_trial(root, "D03", "V2")
    _simulate_historic_incident(root, broken, "REVIEW", monkeypatch)
    zap = broken / "evaluation" / "attempt_001" / "tia" / f"{broken.name}.zap18"
    zap.write_bytes(b"alterado")
    audit = PA.audit_trial(root, broken)
    assert audit["verdict"] == PA.VERDICT_NOT_RECONSTRUCTIBLE
    assert "zap18_hash_matches_manifest" in audit["attempt_audits"][-1]["failed_required"]
    pending = _generated_trial(root, "D03", "V3")
    assert PA.audit_trial(root, pending)["verdict"] == PA.VERDICT_NO_ORPHAN_ATTEMPT


def test_frozen_artifacts_unchanged():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
    assert {name: B.file_hash(_ROOT / name) for name in _FROZEN} == _FROZEN_BEFORE
