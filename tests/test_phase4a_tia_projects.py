"""
Fase 4A-DEFERRED 6B-6E: proyecto TIA del MODO NORMAL y TIA MASTER de EXPERIMENTACION separados.

Guards:
  - el Modo Normal nunca usa el experiment_master;
  - Experimentacion nunca modifica el normal_project;
  - la evaluacion experimental nunca modifica el experiment_master;
  - el ensayo N nunca usa el ensayo N-1 como plantilla.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import gui  # noqa: E402
import tia_openness  # noqa: E402
import tia_projects  # noqa: E402
from trial_experiments import deferred_evaluator as DE  # noqa: E402

from test_phase4a_deferred_evaluation import _FakeBridge, _evaluate, _generated_trial, _master, _project  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]


def _ap18(root: Path, name: str) -> Path:
    folder = root / "tia_projects" / name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.ap18"
    path.write_bytes(name.encode())
    return path


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "config").mkdir(parents=True)
    shutil.copyfile(_ROOT / "config" / "tia_openness_config.json", root / "config" / "tia_openness_config.json")
    return root


# ---------- 6C: configuracion persistente separada ----------

def test_normal_and_master_are_stored_separately(tmp_path):
    root = _project(tmp_path)
    normal = _ap18(root, "NORMAL")
    tia_projects.set_normal_project(root, normal, "PLC_1")
    config = _master(root)
    stored = json.loads(tia_projects.config_path(root).read_text(encoding="utf-8"))["tia"]
    assert stored["normal_project"]["path"] == str(normal)
    assert set(stored["normal_project"]) >= {"path", "validation"}
    assert stored["experiment_master"]["path"] == config["path"] != str(normal)
    assert set(stored["experiment_master"]) >= {"path", "hash", "validation", "status"}
    assert stored["experiment_master"]["hash"] == config["snapshot"]["archive_sha256"]
    assert stored["experiment_master"]["status"] == config["validation"]["master_status"]
    # project_path del bridge = espejo del proyecto Normal, nunca el MASTER
    assert tia_openness.load_tia_config(root)["project_path"] == str(normal)


def test_selecting_one_never_changes_the_other(tmp_path):
    root = _project(tmp_path)
    normal_a, normal_b = _ap18(root, "NORMAL_A"), _ap18(root, "NORMAL_B")
    tia_projects.set_normal_project(root, normal_a)
    config = _master(root)
    tia_projects.set_normal_project(root, normal_b)
    assert DE.load_master_config(root)["path"] == config["path"]
    assert DE.load_master_config(root)["hash"] == config["hash"]
    DE.select_master(root, _ap18(root, "MASTER_2"))
    assert tia_projects.normal_project_path(root) == str(normal_b)


def test_legacy_project_path_is_an_explicit_fallback(tmp_path):
    root = _root(tmp_path)
    tia_openness.save_tia_config({"project_path": "C:/TIA/Demo.ap18"}, root)
    normal = tia_projects.get_normal_project(root)
    assert normal["path"] == "C:/TIA/Demo.ap18" and normal["source"] == "legacy_tia_openness_config.project_path"


# ---------- 6D: guards ----------

def test_normal_project_can_never_be_the_master(tmp_path):
    root = _project(tmp_path)
    config = _master(root)
    with pytest.raises(tia_projects.TiaProjectGuardError) as error:
        tia_projects.set_normal_project(root, config["path"])
    assert error.value.code == tia_projects.ERROR_NORMAL_IS_MASTER
    other_file_same_project = Path(config["path"]).with_name("OTRO.ap18")
    other_file_same_project.write_bytes(b"x")
    with pytest.raises(tia_projects.TiaProjectGuardError):
        tia_projects.set_normal_project(root, other_file_same_project)


def test_master_can_never_be_the_normal_project(tmp_path):
    root = _project(tmp_path)
    normal = _ap18(root, "NORMAL")
    tia_projects.set_normal_project(root, normal)
    with pytest.raises(tia_projects.TiaProjectGuardError) as error:
        DE.select_master(root, normal)
    assert error.value.code == tia_projects.ERROR_MASTER_IS_NORMAL


def test_normal_mode_never_uses_the_master(tmp_path):
    root = _project(tmp_path)
    normal = _ap18(root, "NORMAL")
    tia_projects.set_normal_project(root, normal)
    config = _master(root)
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "siemens_source.scl").write_text("(* scl *)", encoding="utf-8")
    (package / "variables.json").write_text("[]", encoding="utf-8")
    _, _, compile_request = tia_openness.prepare_tia_request(package, root)
    _, _, download_request = tia_openness.prepare_download_request(package, root, "normal")
    assert compile_request["project_path"] == download_request["project_path"] == str(normal)
    # Aunque alguien apunte a mano el proyecto Normal al MASTER, el Modo Normal se niega.
    data = tia_projects.load(root)
    data["tia"]["normal_project"]["path"] = config["path"]
    tia_projects.save(root, data)
    with pytest.raises(tia_projects.TiaProjectGuardError):
        tia_openness.prepare_tia_request(package, root)
    with pytest.raises(tia_projects.TiaProjectGuardError):
        tia_openness.prepare_download_request(package, root, "normal")
    diagnostic = tia_openness.diagnose_tia_openness(root)
    assert diagnostic["checks"]["normal_project_is_not_master"] is False and diagnostic["is_ready"] is False


def test_experiment_evaluation_never_touches_normal_project_or_master(tmp_path):
    root = _project(tmp_path)
    normal = _ap18(root, "NORMAL")
    tia_projects.set_normal_project(root, normal)
    config = _master(root)
    normal_bytes = normal.read_bytes()
    master_fingerprint = DE.master_folder_fingerprint(config["path"])
    trial_dir = _generated_trial(root)
    bridge = _FakeBridge()
    result = _evaluate(root, trial_dir, bridge)
    assert result["final_status"] == "PASS"
    request = bridge.requests[0]
    assert "project_path" not in request  # la evaluacion nunca abre un proyecto por ruta (ni Normal ni MASTER)
    assert str(normal) not in json.dumps(request) and config["path"] not in json.dumps(request)
    assert Path(request["master_archive_path"]) == Path(config["snapshot"]["archive_path"]).resolve()
    assert not Path(request["working_dir"]).is_relative_to(normal.parent)
    assert not Path(request["working_dir"]).is_relative_to(Path(config["path"]).parent)
    assert normal.read_bytes() == normal_bytes
    assert DE.master_folder_fingerprint(config["path"]) == master_fingerprint


def test_trial_inside_a_project_folder_or_template_from_a_trial_is_rejected(tmp_path):
    root = _project(tmp_path)
    config = _master(root)
    trial_dir = _generated_trial(root)
    # Plantilla = artefacto de otro ensayo -> TEMPLATE_GUARD
    fake_template = trial_dir / "evaluation" / "otro.zap18"
    fake_template.parent.mkdir(parents=True)
    fake_template.write_bytes(b"trial-copy")
    master = DE.load_master_config(root)
    master["snapshot"] = {**master["snapshot"], "archive_path": str(fake_template), "archive_sha256": DE.sha256_file(fake_template)}
    DE.save_master_config(root, master)
    check = DE.precheck(root, trial_dir)
    assert not check["ok"] and any("TEMPLATE_GUARD" in e for e in check["errors"])
    assert config["path"]


def test_gui_experiment_mode_never_compiles_into_normal_project(app, monkeypatch):
    calls: list[str] = []
    warnings: list[str] = []
    monkeypatch.setattr(gui, "validate_package_with_tia", lambda *a, **k: calls.append("compile") or {})
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, message, **k: warnings.append(message))
    monkeypatch.setattr(gui.VozLLMPLCGUI, "_legacy_immediate_experiment_allowed", lambda self: False)
    app.work_mode_var.set("Experimentacion")
    try:
        app.validate_latest_package_in_tia()
        app.run_experiment_trial()
        assert calls == []
        assert len(warnings) == 2 and all("EXPERIMENT_MODE_NEVER_MODIFIES_NORMAL_PROJECT" in w for w in warnings)
    finally:
        app.work_mode_var.set("Normal")


def test_batch_preflight_requires_explicit_legacy_pipeline(tmp_path):
    from trial_experiments import batch_runner as B
    from test_phase4a_experimental_design import _project_copy

    root = _project_copy(tmp_path)
    check = B.preflight(root, live=True,
                        runtime_status_fn=lambda r: {"status": "CONNECTED", "connected": True, "instance_name": "TESIS_PLC_SIM",
                                                     "cpu_type": "CPU1516", "network_match": True},
                        tia_diagnostic_fn=lambda r: {"is_ready": True, "project_path": "C:/TIA/N.ap18", "warnings": []},
                        llm_health_fn=lambda: {"llm_configured": True, "model_configured": True},
                        gui_running_fn=lambda: False)
    assert "legacy_immediate_pipeline_enabled" in check["failed_checks"]


# ---------- 6E: dialogo ----------

def test_tia_config_dialog_shows_independent_sections(app, tmp_path, monkeypatch):
    root = _project(tmp_path)
    normal = _ap18(root, "NORMAL")
    tia_projects.set_normal_project(root, normal)
    monkeypatch.setattr(app, "project_root", root)
    dialog = gui.TiaConfigDialog(app)
    try:
        assert dialog.normal_path_var.get() == str(normal) and dialog.master_path_var.get() == ""
        master = _ap18(root, "MASTER")
        dialog.select_master(str(master))
        assert dialog.master_path_var.get() == str(master)
        assert dialog.normal_path_var.get() == str(normal)  # seleccionar el MASTER no cambia el Normal
        assert "SIN VALIDAR" in dialog.info_box.get("1.0", "end") and "Ruta:" in dialog.normal_box.get("1.0", "end")
        warnings: list[str] = []
        monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, message, **k: warnings.append(message))
        dialog.select_master(str(normal))  # el Normal nunca puede ser MASTER
        assert warnings and tia_projects.ERROR_MASTER_IS_NORMAL in warnings[0]
        assert DE.load_master_config(root)["path"] == str(master)
    finally:
        dialog.destroy()
