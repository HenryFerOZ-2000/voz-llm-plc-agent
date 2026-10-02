"""
MODO NORMAL — CAPTURAR Y EJECUTAR POR VOZ: captura -> ASR -> transcripcion en el cuadro de comando ->
(sin otro clic) pipeline Normal existente -> proyecto TIA NORMAL -> compilacion -> descarga automatica.
Microfono, ASR, LLM, TIA y descarga simulados (fixture `pipeline` de Fase 1).
"""
from __future__ import annotations

import json
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
TRANSCRIPT = "enciende la salida del motor"


@pytest.fixture
def voice(pipeline, monkeypatch, tmp_path):
    app = pipeline["app"]
    state: dict[str, Any] = {"recording": False, "asr_calls": [], "parsed": [], "infos": [], "warnings": [], "errors": []}
    recognizer = app.speech_recognizer
    audio = tmp_path / "cmd.wav"
    audio.write_bytes(b"RIFF")

    monkeypatch.setattr(recognizer, "is_recording_available", lambda: True)
    monkeypatch.setattr(recognizer, "get_input_device_info", lambda: {"available": True, "name": "Mic"})
    monkeypatch.setattr(recognizer, "start_recording", lambda: state.update(recording=True) or {"input_device": {"name": "Mic"}})
    monkeypatch.setattr(recognizer, "is_recording", lambda: state["recording"])
    monkeypatch.setattr(recognizer, "stop_recording", lambda: state.update(recording=False) or audio)
    monkeypatch.setattr(recognizer, "cancel_recording", lambda: state.update(recording=False))
    monkeypatch.setattr(recognizer, "discard_audio", lambda *a, **k: True)

    def _asr(path, *args, **kwargs):
        state["asr_calls"].append(Path(path))
        return {"transcript": state.get("transcript", TRANSCRIPT), "model": "fake-asr"}

    monkeypatch.setattr(recognizer, "transcribe_audio", _asr)

    def _sync_transcription():  # el hilo "voice-transcription", sincrono
        app._voice_worker_active = True
        app._voice_worker_queue.put(("success", recognizer.transcribe_audio(app.voice_audio_path)))
        app._poll_voice_worker()

    monkeypatch.setattr(app, "_start_voice_transcription", _sync_transcription)
    base_parse = gui.parse_command

    def _parse(command_text, **kwargs):
        state["parsed"].append(command_text)
        state.setdefault("box_at_parse", []).append(app.command_textbox.get("1.0", "end").strip())
        return base_parse(command_text, **kwargs)

    monkeypatch.setattr(gui, "parse_command", _parse)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda t, m="", **k: state["infos"].append(m))
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda t, m="", **k: state["warnings"].append(m))
    monkeypatch.setattr(gui.messagebox, "showerror", lambda t, m="", **k: state["errors"].append(m))
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: pytest.fail("el flujo por voz no pide confirmacion"))
    monkeypatch.setattr(gui.tia_projects, "assert_normal_not_master", lambda *a, **k: None)
    monkeypatch.setattr(normal_voice, "load_config", lambda root: dict(normal_voice.DEFAULTS))
    app.work_mode_var.set("Normal")
    app.command_textbox.delete("1.0", "end")
    yield {"app": app, "state": state, "pipeline": pipeline}
    app._normal_voice_flow = None


def _speak(app) -> None:
    """Clic 1: grabar. Clic 2: detener -> TODO lo demas sin mas clics."""
    app.capture_and_execute_by_voice()
    app.capture_and_execute_by_voice()
    for _ in range(5):
        app.update()
    app._poll_tia_worker()
    if app._download_worker_active:
        app._poll_download_worker()


def test_voice_capture_calls_asr_and_transcript_goes_to_the_normal_pipeline(voice):
    app, state = voice["app"], voice["state"]
    _speak(app)
    assert len(state["asr_calls"]) == 1
    assert state["box_at_parse"] == [TRANSCRIPT]  # la transcripcion se mostro en el cuadro de comando
    assert app.voice_transcription["transcript"] == TRANSCRIPT
    assert state["parsed"] == [TRANSCRIPT]  # el pipeline Normal recibio la transcripcion sin otro clic


def test_compile_pass_triggers_auto_download_without_second_click(voice):
    app, pipeline = voice["app"], voice["pipeline"]
    _speak(app)
    assert len(pipeline["download_calls"]) == 1 and pipeline["download_calls"][0]["purpose"] == tia_openness.DOWNLOAD_PURPOSE_NORMAL
    result = app.last_normal_voice_result
    assert result["final"] == normal_voice.FINAL_LOADED and set(result["stages"].values()) == {"ok"}


def test_compile_fail_never_downloads(voice):
    app, pipeline = voice["app"], voice["pipeline"]
    pipeline["state"]["compile_status"] = "TIA_COMPILATION_FAILED"
    _speak(app)
    assert pipeline["download_calls"] == []
    assert app.last_normal_voice_result["failed_stage"] == "Compilacion"


def test_semantic_fail_never_downloads(voice, monkeypatch):
    app, pipeline = voice["app"], voice["pipeline"]
    invalid = _base_semantic_output("INT_UNKNOWN", {}, [])
    invalid["semantic_validation"].update({"is_valid": False, "errors": ["no interpretable"]})
    monkeypatch.setattr(gui, "parse_command", lambda text, **k: invalid)
    _speak(app)
    assert pipeline["download_calls"] == [] and app.last_normal_voice_result["failed_stage"] in ("Semantica", "I/O")


def test_verifier_fail_never_downloads(voice):
    app, pipeline = voice["app"], voice["pipeline"]
    pipeline["state"]["verification_valid"] = False
    _speak(app)
    assert pipeline["download_calls"] == [] and app.last_normal_voice_result["failed_stage"] == "Verificacion"


def test_clarification_stops_the_automatic_download(voice, monkeypatch):
    app, pipeline = voice["app"], voice["pipeline"]
    ambiguous = _base_semantic_output("INT_UNKNOWN", {}, [])
    ambiguous.update({"requires_clarification": True, "clarification_question": "¿Que salida?"})
    ambiguous["semantic_validation"].update({"is_valid": False, "requires_clarification": True})
    monkeypatch.setattr(gui, "parse_command", lambda text, **k: ambiguous)

    class _NoAnswer:
        def __init__(self, parent, question):
            self.result = None

    monkeypatch.setattr(gui, "ClarificationDialog", _NoAnswer)
    monkeypatch.setattr(app, "wait_window", lambda *a, **k: None)
    _speak(app)
    result = app.last_normal_voice_result
    assert pipeline["download_calls"] == [] and result["clarification_pending"] is True
    assert result["stages"]["Compilacion"] == "pending" and result["stages"]["Descarga"] == "pending"  # antes de TIA


def test_answered_clarification_allows_download_but_pending_blocks_it(voice):
    flow = normal_voice.new_flow(_ROOT)
    for stage in ("Semantica", "I/O", "Generacion", "Verificacion"):
        flow["stages"][stage] = "ok"
    assert normal_voice.download_allowed(flow, True) == (True, "ok")
    flow["clarification_requested"] = True  # resuelta: no bloquea
    assert normal_voice.download_allowed(flow, True) == (True, "ok")
    flow["clarification_pending"] = True
    allowed, reason = normal_voice.download_allowed(flow, True)
    assert allowed is False and "pendiente" in reason


def test_auto_download_false_keeps_compilation_but_does_not_download(voice, monkeypatch):
    app, pipeline = voice["app"], voice["pipeline"]
    monkeypatch.setattr(normal_voice, "load_config", lambda root: {"auto_execute": True, "auto_download": False})
    _speak(app)
    assert pipeline["download_calls"] == []
    result = app.last_normal_voice_result
    assert result["stages"]["Compilacion"] == "ok" and result["stages"]["Descarga"] == "skipped"
    assert app._last_compiled_package_dir is not None  # CARGAR PROGRAMA AL PLC sigue disponible


def test_cancel_during_capture_runs_nothing(voice):
    app, state, pipeline = voice["app"], voice["state"], voice["pipeline"]
    app.capture_and_execute_by_voice()
    app.cancel_normal_voice_capture()
    assert state["asr_calls"] == [] and state["parsed"] == [] and pipeline["download_calls"] == []


def test_normal_voice_uses_normal_project_and_never_the_experiment_master(voice, monkeypatch, tmp_path):
    app, pipeline = voice["app"], voice["pipeline"]

    def _forbidden(*args, **kwargs):
        raise AssertionError("el flujo de voz Normal nunca usa el MASTER experimental, tiaw/ ni el evaluador de ensayos")

    for module, name in ((DE, "evaluate_trial"), (DE, "load_master_config"), (DE, "run_bridge"), (TW, "allocate"),
                         (tia_projects, "get_experiment_master")):
        monkeypatch.setattr(module, name, _forbidden)
    _speak(app)
    assert len(pipeline["download_calls"]) == 1  # descarga Normal (proyecto Normal) sin tocar nada experimental


def test_normal_voice_requests_target_the_normal_project(tmp_path):
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
    _, _, request = tia_openness.prepare_download_request(package, root, tia_openness.DOWNLOAD_PURPOSE_NORMAL)
    assert request["project_path"] == "C:/TIA/Normal/Normal.ap18" and "MASTER" not in request["project_path"]


def test_text_normal_flow_is_unchanged(voice):
    app, state, pipeline = voice["app"], voice["state"], voice["pipeline"]
    app.command_textbox.insert("1.0", "enciende la salida")
    assert app.execute_full_pipeline() is True
    app._poll_tia_worker()
    assert pipeline["download_calls"] == [] and state["asr_calls"] == []  # EJECUTAR COMANDO: generar + compilar
    assert app._last_compiled_package_dir is not None  # CARGAR PROGRAMA AL PLC sigue siendo manual


def test_voice_button_is_only_for_normal_mode(voice):
    app, state = voice["app"], voice["state"]
    app.work_mode_var.set("Experimentacion")
    app.capture_and_execute_by_voice()
    assert state["asr_calls"] == [] and state["warnings"] and app._normal_voice_flow is None
    app.work_mode_var.set("Normal")


def test_config_persistence(tmp_path):
    assert normal_voice.load_config(tmp_path) == {"auto_execute": True, "auto_download": True}
    normal_voice.save_config(tmp_path, auto_download=False)
    stored = json.loads((tmp_path / "config" / "normal_voice.json").read_text(encoding="utf-8"))
    assert stored == {"normal_voice": {"auto_execute": True, "auto_download": False}}


def test_experimentation_artifacts_unchanged():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
