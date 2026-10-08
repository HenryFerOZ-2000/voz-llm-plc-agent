"""
Trazabilidad de etapas de un ensayo de Experimentacion: Compilation / Download / encabezado.

Causa real (reproducida): al persistir una evaluacion diferida COMPLETA, el parche del Oracle se aplicaba
con dict.update() plano y su seccion "stages" (functional/safety) reemplazaba la recien construida
(compile_success, download_success, ...); igual con "timing". La GUI mostraba Compilation "-" y
Download "-" con FINAL PASS. Ademas el dialogo dejaba "PENDIENTE DE EVALUACION" en el encabezado.

Fuente unica: deferred_evaluator.trial_stage_summary(record) -> detalle, encabezado, lista y futuro lote.
Sin TIA/PLCSIM reales: dobles de test_phase4a_deferred_evaluation.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from trial_experiments import deferred_evaluator as DE  # noqa: E402
from trial_experiments import trial_model  # noqa: E402
from trial_experiments import batch_runner as B  # noqa: E402

from test_phase4a_deferred_evaluation import _FakeBridge, _evaluate, _generated_trial, _master, _project  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)


class _DownloadFailBridge(_FakeBridge):
    """Compila y archiva, pero el bridge informa una descarga fallida."""

    def __call__(self, request, work_dir, project_root=None, on_archived=None):
        report = super().__call__(request, work_dir, project_root, on_archived)
        if "download" in report:
            report["download"] = {"status": "TIA_DOWNLOAD_FAILED", "success": False, "target_type": "PLCSIM_ADVANCED",
                                  "start_module_requested": True, "start_module_success": False, "cpu_run_requested": True,
                                  "errors": ["Descarga rechazada por el destino"]}
        return report


def _evaluated(tmp_path: Path, bridge: _FakeBridge | None = None) -> tuple[Path, Path, dict[str, Any]]:
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    _evaluate(root, trial_dir, bridge or _FakeBridge())
    return root, trial_dir, trial_model.load_trial(trial_dir)


def _without_stage_copies(record: dict[str, Any]) -> dict[str, Any]:
    """Registro como quedaba ANTES de la correccion (copias en stages perdidas; el resto de evidencia intacta)."""
    legacy = copy.deepcopy(record)
    for key in ("compile_success", "download_success", "start_module_success", "runtime_connection_success"):
        legacy["stages"].pop(key, None)
    return legacy


# --- Compilation ---------------------------------------------------------------------------------

def test_full_evaluation_persists_compile_and_download_evidence_in_stages(tmp_path):
    _, _, record = _evaluated(tmp_path)
    assert record["stages"]["compile_success"] is True and record["stages"]["download_success"] is True
    assert record["stages"]["functional_success"] is True and record["stages"]["safety_success"] is True
    assert record["timing"]["compile_ms"] is not None and record["timing"]["runtime_ms"] is not None  # timing tampoco se pierde
    summary = DE.trial_stage_summary(record)
    assert {key: summary[key] for key in DE.STAGE_KEYS} == {
        "semantic": "PASS", "io_allocation": "PASS", "ir": "PASS", "compilation": "PASS", "tia_archive": "PASS",
        "download": "PASS", "runtime": "PASS", "functional": "PASS", "safety": "PASS", "final_verdict": "PASS",
        "semantic_benchmark": "-"}  # el doble del Oracle no evalua semantica: nunca se inventa la coincidencia


def test_compilation_pass_persisted_is_shown_as_pass(tmp_path):
    _, _, record = _evaluated(tmp_path)
    assert dict(DE.verdict_table(record))["Compilation"] == "PASS"
    # Ensayo evaluado antes de la correccion: se lee la clasificacion REAL del reporte de compilacion.
    assert dict(DE.verdict_table(_without_stage_copies(record)))["Compilation"] == "PASS"


def test_compilation_fail_is_shown_as_fail(tmp_path):
    _, _, record = _evaluated(tmp_path, _FakeBridge("COMPILE_FAIL"))
    assert record["stages"]["compile_success"] is False
    assert dict(DE.verdict_table(record))["Compilation"] == "FAIL"
    assert dict(DE.verdict_table(_without_stage_copies(record)))["Compilation"] == "FAIL"


def test_compilation_not_run_never_invents_pass(tmp_path):
    root = _project(tmp_path)
    _master(root)
    pending = trial_model.load_trial(_generated_trial(root))
    assert DE.trial_stage_summary(pending)["compilation"] == "-"
    _, _, crashed = _evaluated(tmp_path / "b", _FakeBridge("NON_RECOVERABLE"))
    assert DE.trial_stage_summary(crashed)["compilation"] == "INFRA"  # TIA cayo: ni PASS ni FAIL del sistema


def test_compilation_is_never_inferred_from_archive_or_runtime():
    record = {"stages": {}, "tia_archive": {"status": "CREATED"}, "download": {"cpu_run_confirmed": True},
              "evaluation": {"final_verdict": "PASS", "attempts": [{"attempt": 1}]}}
    summary = DE.trial_stage_summary(record)
    assert summary["tia_archive"] == "PASS" and summary["runtime"] == "PASS"
    assert summary["compilation"] == "-" and summary["download"] == "-"


def test_compilation_with_imported_source_mismatch_is_not_pass():
    record = {"stages": {}, "compile": {"classification": {"category": "COMPILE_PASSED"}},
              "evaluation": {"attempts": [{"compile": "COMPILE_PASSED",
                                           "errors": [f"{DE.ERROR_INTEGRITY}: TIA importo un program.scl distinto"]}]}}
    assert DE.trial_stage_summary(record)["compilation"] == "FAIL"


# --- Download ------------------------------------------------------------------------------------

def test_download_pass_persisted_is_shown_as_pass(tmp_path):
    _, _, record = _evaluated(tmp_path)
    assert dict(DE.verdict_table(record))["Download"] == "PASS"
    assert dict(DE.verdict_table(_without_stage_copies(record)))["Download"] == "PASS"  # evidencia del bridge (intento)


def test_download_fail_is_shown_as_fail(tmp_path):
    _, _, record = _evaluated(tmp_path, _DownloadFailBridge())
    assert record["stages"]["download_success"] is False and record["final_status"] == "INFRASTRUCTURE_ERROR"
    assert dict(DE.verdict_table(record))["Download"] == "FAIL"
    assert dict(DE.verdict_table(_without_stage_copies(record)))["Download"] == "FAIL"
    assert dict(DE.verdict_table(record))["Runtime"] == "-"  # sin descarga no se consulta el Runtime


def test_download_not_run_never_invents_pass(tmp_path):
    _, _, record = _evaluated(tmp_path, _FakeBridge("COMPILE_FAIL"))
    assert record["stages"]["download_success"] is None
    assert dict(DE.verdict_table(record))["Download"] == "-"


# --- Runtime / Functional / Safety ---------------------------------------------------------------

def test_runtime_functional_and_safety_still_pass(tmp_path):
    _, _, record = _evaluated(tmp_path)
    table = dict(DE.verdict_table(record))
    assert (table["Runtime"], table["Functional"], table["Safety"], table["TIA Archive"]) == ("PASS",) * 4


# --- Encabezado / estado -------------------------------------------------------------------------

def test_final_pass_updates_the_header(tmp_path):
    root, trial_dir, record = _evaluated(tmp_path)
    assert DE.trial_status_label(record) == "PASS / COMPLETADO"
    assert "Estado: PASS / COMPLETADO" in DE.evaluation_summary_lines(root, trial_dir)


def test_final_fail_updates_the_header(tmp_path):
    root, trial_dir, record = _evaluated(tmp_path, _FakeBridge("COMPILE_FAIL"))
    assert DE.trial_status_label(record) == "FAIL / COMPLETADO"
    assert "Estado: FAIL / COMPLETADO" in DE.evaluation_summary_lines(root, trial_dir)


def test_infrastructure_error_is_shown(tmp_path):
    root, trial_dir, record = _evaluated(tmp_path, _FakeBridge("NON_RECOVERABLE"))
    assert DE.trial_status_label(record) == "INFRASTRUCTURE_ERROR"
    assert "Estado: INFRASTRUCTURE_ERROR" in DE.evaluation_summary_lines(root, trial_dir)


def test_pending_trial_still_shows_pending(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    record = trial_model.load_trial(trial_dir)
    assert DE.trial_status_label(record) == DE.STATUS_PENDING_LABEL
    assert f"Estado: {DE.STATUS_PENDING_LABEL}" in DE.evaluation_summary_lines(root, trial_dir)
    assert DE.trial_stage_summary(record)["final_verdict"] == "PENDIENTE"


def test_historical_display_is_unchanged_for_legacy_records():
    legacy = {"stages": {"semantic_success": True, "verification_success": True, "compile_success": True,
                         "download_success": True}, "download": {"cpu_run_confirmed": True}, "final_status": "PREPARED"}
    assert dict(DE.verdict_table(legacy))["FINAL"] == "PREPARED"  # misma fila FINAL que antes
    assert DE.trial_status_label(legacy) == "LEGACY"


# --- Fuente unica ----------------------------------------------------------------------------------

def test_detail_list_and_header_share_the_same_source(tmp_path, monkeypatch):
    root, trial_dir, record = _evaluated(tmp_path)
    calls = []
    original = DE.trial_stage_summary

    def _spy(rec):
        calls.append(rec.get("trial_id"))
        return original(rec)

    monkeypatch.setattr(DE, "trial_stage_summary", _spy)
    table = dict(DE.verdict_table(record))
    [row] = DE.list_trials(root)
    assert len(calls) == 2  # detalle y lista: la misma funcion
    assert {DE.STAGE_LABELS[key]: row["summary"][key] for key in DE.STAGE_KEYS} == table
    assert row["summary"]["status"] == DE.trial_status_label(record)


def test_gui_detail_dialog_and_main_panel_use_the_shared_summary(app, tmp_path, monkeypatch):
    import gui

    _, trial_dir, record = _evaluated(tmp_path)
    shown = []
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda title, text="", **k: shown.append(text))
    app.show_trial_detail(trial_dir)
    assert "Estado: PASS / COMPLETADO" in shown[0]
    assert "Compilation: PASS" in shown[0] and "Download: PASS" in shown[0]
    summary = app._apply_trial_summary_to_stages(trial_dir)
    assert summary == DE.trial_stage_summary(record)
    assert app._experiment_stage_states["Compilacion"] == "ok" and app._experiment_stage_states["Descarga"] == "ok"
    assert app._experiment_stage_states["CPU Start"] == "ok" and app._experiment_stage_states["Safety"] == "ok"
    app._reset_experiment_stages()


def test_evaluation_dialog_refreshes_its_header_when_the_evaluation_ends(app, tmp_path, monkeypatch):
    import gui

    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    monkeypatch.setattr(app, "project_root", root)
    dialog = gui.DeferredEvaluationDialog(app, trial_dir)
    try:
        assert f"Estado: {DE.STATUS_PENDING_LABEL}" in dialog.summary_box.get("1.0", "end")
        _evaluate(root, trial_dir, _FakeBridge())
        dialog.show_result("ok", {"aborted": False, "errors": []})
        header = dialog.summary_box.get("1.0", "end")
        assert "Estado: PASS / COMPLETADO" in header and DE.STATUS_PENDING_LABEL not in header
        result = dialog.result_box.get("1.0", "end")
        assert "Compilation" in result and "PASS" in result.split("Compilation", 1)[1].splitlines()[0]
    finally:
        dialog.destroy()


# --- .zap18 por ensayo ------------------------------------------------------------------------------

def test_tia_archive_pass_requires_the_trial_zap18(tmp_path):
    _, trial_dir, record = _evaluated(tmp_path)
    evidence = trial_dir / "evaluation" / "attempt_001" / "tia" / f"{trial_dir.name}.zap18"
    assert DE.trial_stage_summary(record)["tia_archive"] == "PASS"
    assert record["tia_archive"]["status"] == "CREATED" and Path(record["tia_archive"]["zap18_path"]) == evidence
    assert evidence.exists() and record["tia_archive"]["zap18_hash"] == DE.sha256_file(evidence)


def test_corrupted_zap18_is_never_archive_pass(tmp_path):
    _, _, record = _evaluated(tmp_path, _FakeBridge("CORRUPT_AFTER_ARCHIVE"))
    assert DE.trial_stage_summary(record)["tia_archive"] == "FAIL" and record["tia_archive"]["zap18_path"] is None


def test_experimentation_artifacts_unchanged():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
