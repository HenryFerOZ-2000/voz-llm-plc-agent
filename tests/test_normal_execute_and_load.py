"""
MODO NORMAL — dos flujos de texto sobre el MISMO pipeline:
  EJECUTAR COMANDO           -> generar + compilar (sin descarga)
  EJECUTAR Y CARGAR AL PLC   -> lo mismo + la descarga existente de CARGAR PROGRAMA AL PLC si todo pasa
PLCSIM: sin confirmacion. PLC fisico: confirmacion obligatoria (cancelar conserva la compilacion).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import gui  # noqa: E402
import normal_voice  # noqa: E402
import tia_openness  # noqa: E402
import tia_projects  # noqa: E402
from trial_experiments import batch_runner as B  # noqa: E402
from trial_experiments import deferred_evaluator as DE  # noqa: E402
from trial_experiments import tia_workspace as TW  # noqa: E402

from test_phase1_download_and_trials import pipeline  # noqa: E402
from test_execute_full_pipeline import _base_semantic_output, temp_map, _tia_ready  # noqa: E402

__all__ = ["pipeline", "temp_map", "_tia_ready"]

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)
QUESTION = "¿Cuánto tiempo debe permanecer encendida la salida?"


@pytest.fixture
def normal(pipeline, monkeypatch):
    app = pipeline["app"]
    state: dict[str, Any] = {"infos": [], "errors": [], "confirmations": [], "confirm": True, "parsed": [], "dialogs": [],
                             "answers": []}
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda t, m="", **k: state["infos"].append(m))
    monkeypatch.setattr(gui.messagebox, "showerror", lambda t, m="", **k: state["errors"].append(m))
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda t, m="", **k: state["errors"].append(m))
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: pytest.fail("el flujo encadenado no usa askyesno"))
    monkeypatch.setattr(gui.tia_projects, "assert_normal_not_master", lambda *a, **k: None)
    monkeypatch.setattr(app, "_confirm_physical_download",
                        lambda info: state["confirmations"].append(info) or state["confirm"])

    class _Dialog:
        def __init__(self, parent, question):
            state["dialogs"].append(question)
            self.result = state["answers"].pop(0) if state["answers"] else None

    monkeypatch.setattr(gui, "ClarificationDialog", _Dialog)
    monkeypatch.setattr(app, "wait_window", lambda *a, **k: None)
    base_parse = gui.parse_command

    def _parse(command_text, **kwargs):
        state["parsed"].append(kwargs)
        return base_parse(command_text, **kwargs)

    monkeypatch.setattr(gui, "parse_command", _parse)
    app.work_mode_var.set("Normal")
    yield {"app": app, "state": state, "pipeline": pipeline}
    app._normal_voice_flow = None


def _physical(monkeypatch):
    real = gui.resolve_download_target

    def _target(config, purpose=tia_openness.DOWNLOAD_PURPOSE_NORMAL):
        return {**real(config, purpose), "target_type": "PHYSICAL_PLC", "target_name": "CPU banco"}

    monkeypatch.setattr(gui, "resolve_download_target", _target)


def _finish(app) -> None:
    app._poll_tia_worker()
    if app._download_worker_active:
        app._poll_download_worker()


def _execute_and_load(app) -> None:
    app.execute_and_load_to_plc()
    _finish(app)


def test_execute_command_compiles_but_never_downloads(normal):
    app, pipeline = normal["app"], normal["pipeline"]
    assert app.execute_full_pipeline() is True
    _finish(app)
    assert pipeline["download_calls"] == [] and app._last_compiled_package_dir is not None


def test_execute_and_load_compiles_and_downloads_with_the_same_pipeline(normal):
    app, state, pipeline = normal["app"], normal["state"], normal["pipeline"]
    app.execute_full_pipeline()
    _finish(app)
    text_kwargs = state["parsed"][-1]
    _execute_and_load(app)
    load_kwargs = state["parsed"][-1]
    # Same product facade; its semantic profile is fixed inside the shared engine.
    assert sorted(load_kwargs) == sorted(text_kwargs)
    assert load_kwargs["mode"] == text_kwargs["mode"] and "interaction_profile" not in load_kwargs
    assert len(pipeline["download_calls"]) == 1 and pipeline["download_calls"][0]["purpose"] == tia_openness.DOWNLOAD_PURPOSE_NORMAL
    result = app.last_normal_voice_result
    assert result["final"] == normal_voice.FINAL_LOADED and result["source"] == normal_voice.SOURCE_TEXT
    assert state["confirmations"] == []  # PLCSIM: sin confirmacion adicional


def test_compile_failure_never_downloads(normal):
    app, pipeline = normal["app"], normal["pipeline"]
    pipeline["state"]["compile_status"] = "TIA_COMPILATION_FAILED"
    _execute_and_load(app)
    assert pipeline["download_calls"] == [] and app.last_normal_voice_result["failed_stage"] == "Compilacion"


def test_semantic_failure_never_downloads(normal, monkeypatch):
    app, pipeline = normal["app"], normal["pipeline"]
    invalid = _base_semantic_output("INT_DIRECT_OUTPUT", {}, [])
    invalid["semantic_validation"].update({"is_valid": False, "errors": ["Faltan parametros requeridos: output"]})
    monkeypatch.setattr(gui, "parse_command", lambda text, **k: invalid)
    _execute_and_load(app)
    assert pipeline["download_calls"] == [] and app.last_normal_voice_result["failed_stage"] in ("Semantica", "I/O")


def test_verifier_failure_never_downloads(normal):
    app, pipeline = normal["app"], normal["pipeline"]
    pipeline["state"]["verification_valid"] = False
    _execute_and_load(app)
    assert pipeline["download_calls"] == [] and app.last_normal_voice_result["failed_stage"] == "Verificacion"


def _ambiguous() -> dict[str, Any]:
    output = _base_semantic_output("INT_UNKNOWN", {}, [])
    output.update({"requires_clarification": True, "clarification_question": QUESTION})
    output["semantic_validation"].update({"is_valid": False, "requires_clarification": True})
    return output


def _resolved() -> dict[str, Any]:
    return _base_semantic_output("INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"])


def test_pending_clarification_never_downloads(normal, monkeypatch):
    app, state, pipeline = normal["app"], normal["state"], normal["pipeline"]
    monkeypatch.setattr(gui, "parse_command", lambda text, **k: _ambiguous())
    _execute_and_load(app)  # el usuario no responde
    assert state["dialogs"] == [QUESTION] and pipeline["download_calls"] == []
    assert app.last_normal_voice_result["clarification_pending"] is True


def test_resolved_clarification_allows_the_download(normal, monkeypatch):
    app, state, pipeline = normal["app"], normal["state"], normal["pipeline"]
    responses = [_ambiguous(), _resolved()]
    monkeypatch.setattr(gui, "parse_command", lambda text, **k: responses.pop(0))
    state["answers"] = ["5 segundos"]
    _execute_and_load(app)
    result = app.last_normal_voice_result
    assert result["clarification_requested"] is True and result["clarification_pending"] is False
    assert len(pipeline["download_calls"]) == 1 and result["final"] == normal_voice.FINAL_LOADED


def test_physical_plc_requires_confirmation(normal, monkeypatch):
    app, state, pipeline = normal["app"], normal["state"], normal["pipeline"]
    _physical(monkeypatch)
    _execute_and_load(app)
    assert len(state["confirmations"]) == 1 and len(pipeline["download_calls"]) == 1
    info = state["confirmations"][0]
    assert {"destino", "cpu", "ip"} <= set(info) and "PHYSICAL_PLC" in info["destino"]


def test_cancelling_physical_download_keeps_the_compilation(normal, monkeypatch):
    app, state, pipeline = normal["app"], normal["state"], normal["pipeline"]
    _physical(monkeypatch)
    state["confirm"] = False
    _execute_and_load(app)
    assert pipeline["download_calls"] == []
    assert app._last_compiled_package_dir is not None  # CARGAR PROGRAMA AL PLC sigue disponible
    assert "cancelada" in app.last_normal_voice_result["final"]
    assert app.last_normal_voice_result["stages"]["Compilacion"] == "ok"


def test_manual_load_program_still_works(normal, monkeypatch):
    app, pipeline = normal["app"], normal["pipeline"]
    app.execute_full_pipeline()
    _finish(app)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)  # confirmacion manual existente
    app.load_program_to_plc()
    if app._download_worker_active:
        app._poll_download_worker()
    assert len(pipeline["download_calls"]) == 1


def test_all_text_flows_use_the_normal_project_and_never_the_master(normal, monkeypatch):
    app, pipeline = normal["app"], normal["pipeline"]

    def _forbidden(*args, **kwargs):
        raise AssertionError("los flujos Normales nunca usan el MASTER experimental, tiaw/ ni el evaluador de ensayos")

    for module, name in ((DE, "evaluate_trial"), (DE, "load_master_config"), (DE, "run_bridge"), (TW, "allocate"),
                         (tia_projects, "get_experiment_master")):
        monkeypatch.setattr(module, name, _forbidden)
    app.execute_full_pipeline()
    _finish(app)
    _execute_and_load(app)
    assert len(pipeline["download_calls"]) == 1 and pipeline["download_calls"][0]["purpose"] == tia_openness.DOWNLOAD_PURPOSE_NORMAL


def test_download_requests_target_the_normal_project(tmp_path):
    root = tmp_path / "project"
    (root / "config").mkdir(parents=True)
    tia_openness.save_tia_config({"project_path": "C:/TIA/Normal/Normal.ap18"}, root)
    data = tia_projects.load(root)
    data["tia"]["experiment_master"] = {"path": "C:/TIA/MASTER/MASTER.ap18"}
    tia_projects.save(root, data)
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "siemens_source.scl").write_text("x", encoding="utf-8")
    (package / "variables.json").write_text("[]", encoding="utf-8")
    _, _, compile_request = tia_openness.prepare_tia_request(package, root)
    _, _, download_request = tia_openness.prepare_download_request(package, root, tia_openness.DOWNLOAD_PURPOSE_NORMAL)
    assert compile_request["project_path"] == download_request["project_path"] == "C:/TIA/Normal/Normal.ap18"


def test_execute_and_load_is_only_for_normal_mode(normal):
    app, state, pipeline = normal["app"], normal["state"], normal["pipeline"]
    app.work_mode_var.set("Experimentacion")
    try:
        app.execute_and_load_to_plc()
    finally:
        app.work_mode_var.set("Normal")
    assert state["errors"] and pipeline["download_calls"] == [] and app._normal_voice_flow is None


def test_gui_shows_the_four_normal_actions(normal):
    app = normal["app"]
    assert app.execute_command_button.cget("text")=="GENERAR Y COMPILAR"
    assert "GENERAR Y COMPILAR" in app.execute_command_button.cget("text")
    assert app.execute_and_load_button.cget("text").startswith("EJECUTAR Y CARGAR AL PLC")
    assert "CAPTURAR Y EJECUTAR POR VOZ" in app.normal_voice_button.cget("text")
    assert app.download_plc_button.cget("text") == "CARGAR PROGRAMA AL PLC"


def test_experimentation_artifacts_unchanged():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
