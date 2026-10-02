"""
Fase 4A-FINAL-TRIAL-FLOW: EJECUTAR ENSAYO COMPLETO (un clic = un ensayo) y protocolo de voz
TEXT / VOICE_CLEAN / VOICE_NOISE (audio RAW antes del ASR, ASR sin correccion, WER, ruido pareado
determinista). Microfono, ASR, LLM y TIA se sustituyen por dobles; audio sintetico.
"""
from __future__ import annotations

import json
import math
import shutil
from array import array
from pathlib import Path
from typing import Any

import pytest

import gui  # noqa: E402
from trial_experiments import batch_runner as B  # noqa: E402
from trial_experiments import benchmark_catalog as BC  # noqa: E402
from trial_experiments import deferred_evaluator as DE  # noqa: E402
from trial_experiments import experimental_design as ED  # noqa: E402
from trial_experiments import trial_model  # noqa: E402
from trial_experiments import voice_protocol as VP  # noqa: E402

from test_phase1_download_and_trials import pipeline  # noqa: E402
from test_execute_full_pipeline import temp_map, _tia_ready  # noqa: E402
from test_experiment_working_io_map import _use_bench_copy, bench_map  # noqa: E402
from test_phase4a_deferred_evaluation import _project  # noqa: E402

__all__ = ["pipeline", "temp_map", "_tia_ready", "bench_map"]

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)
_REFERENCE = BC.get_case(_ROOT, "D03")["variants"]["V1"]


def _tone(path: Path, seconds: float = 1.0, amplitude: int = 3000, frequency: float = 220.0, rate: int = 16000) -> Path:
    samples = array("h", (int(amplitude * math.sin(2 * math.pi * frequency * i / rate)) for i in range(int(seconds * rate))))
    VP.write_pcm16(path, samples, rate, 1)
    return path


def _noise(path: Path, seconds: float = 0.4, rate: int = 16000) -> Path:
    # ruido pseudoaleatorio determinista (LCG): sin dependencias externas
    state, samples = 12345, array("h")
    for _ in range(int(seconds * rate)):
        state = (1103515245 * state + 12345) % (2 ** 31)
        samples.append((state % 4001) - 2000)
    VP.write_pcm16(path, samples, rate, 1)
    return path


# ---------------------------------------------------------------------------------------------
# WER
# ---------------------------------------------------------------------------------------------

def test_wer_counts_substitution_deletion_insertion():
    assert VP.wer_metrics("arranca el motor", "arranca el motor")["wer"] == 0
    sub = VP.wer_metrics("arranca el motor", "arranca un motor")
    assert (sub["substitutions"], sub["deletions"], sub["insertions"]) == (1, 0, 0) and sub["wer"] == pytest.approx(1 / 3, abs=1e-6)
    deletion = VP.wer_metrics("arranca el motor", "arranca motor")
    assert (deletion["substitutions"], deletion["deletions"], deletion["insertions"]) == (0, 1, 0)
    insertion = VP.wer_metrics("arranca el motor", "arranca el motor ya")
    assert (insertion["substitutions"], insertion["deletions"], insertion["insertions"]) == (0, 0, 1)
    assert insertion["reference_word_count"] == 3 and insertion["wer"] == pytest.approx(1 / 3, abs=1e-6)


def test_wer_normalization_is_stable_and_documented():
    metrics = VP.wer_metrics("Arranca el motor con Start, y detenlo con Stop.", "arranca  el MOTOR con start y detenlo con stop")
    assert metrics["wer"] == 0 and metrics["normalized_transcript_match"] and not metrics["exact_transcript_match"]
    assert VP.normalize_for_wer("¿Apágalo? ¡Sí!") == "apágalo sí"  # tildes conservadas
    assert VP.wer_metrics("durante 5 segundos", "durante cinco segundos")["substitutions"] == 1  # sin conversion de numeros
    assert VP.normalize_for_wer(VP.normalize_for_wer(_REFERENCE)) == VP.normalize_for_wer(_REFERENCE)
    design = ED.load_design(_ROOT)["voice_protocol"]["wer"]
    assert design["formula"] == "(S + D + I) / N" and design["normalization_version"] == 1


# ---------------------------------------------------------------------------------------------
# Captura y ruido
# ---------------------------------------------------------------------------------------------

def test_capture_validation_is_technical_and_permissive(tmp_path):
    settings = VP.DEFAULT_CAPTURE
    assert VP.validate_capture(_tone(tmp_path / "ok.wav"), settings)["valid"] is True
    quiet_but_valid = _tone(tmp_path / "quiet.wav", amplitude=300)
    assert VP.validate_capture(quiet_but_valid, settings)["valid"] is True  # voz baja no se rechaza
    for bad in (_tone(tmp_path / "short.wav", seconds=0.1), _tone(tmp_path / "silent.wav", amplitude=0)):
        result = VP.validate_capture(bad, settings)
        assert result["valid"] is False and all(VP.ERROR_AUDIO_CAPTURE_INVALID in e for e in result["errors"])
    corrupt = tmp_path / "corrupt.wav"
    corrupt.write_bytes(b"RIFF-not-really")
    assert VP.validate_capture(corrupt, settings)["valid"] is False
    assert VP.validate_capture(tmp_path / "missing.wav", settings)["valid"] is False
    assert VP.validate_capture(_tone(tmp_path / "ok2.wav"), settings, {"available": False, "error": "sin mic"})["valid"] is False


def test_noise_mixture_is_deterministic_and_hits_the_snr(tmp_path):
    clean, noise = _tone(tmp_path / "clean.wav"), _noise(tmp_path / "noise.wav")
    first = VP.mix_at_snr(clean, noise, 10.0, tmp_path / "a.wav")
    second = VP.mix_at_snr(clean, noise, 10.0, tmp_path / "b.wav")
    assert first["mixed_audio_hash"] == second["mixed_audio_hash"]  # bit a bit
    assert first["noise_offset_ms"] == 0 and first["noise_looped"] is True and first["clipped_samples"] == 0
    other = VP.mix_at_snr(clean, noise, 0.0, tmp_path / "c.wav")
    assert other["mixed_audio_hash"] != first["mixed_audio_hash"]
    c, m = VP.read_pcm16(clean)["samples"], VP.read_pcm16(tmp_path / "a.wav")["samples"]
    added = [mv - cv for cv, mv in zip(c, m)]
    achieved = 10 * math.log10((sum(v * v for v in c) / len(c)) / (sum(v * v for v in added) / len(added)))
    assert achieved == pytest.approx(10.0, abs=0.05)
    _tone(tmp_path / "r8k.wav", rate=8000)
    with pytest.raises(ValueError, match=VP.ERROR_NOISE_PROFILE_INVALID):
        VP.mix_at_snr(clean, tmp_path / "r8k.wav", 10.0, tmp_path / "d.wav")


def test_snr_comes_from_design_for_formal_and_never_from_code(tmp_path):
    root = _project(tmp_path)
    assert VP.resolve_noise_config(root, trial_model.PHASE_FORMAL)["errors"][0].startswith(VP.ERROR_NOISE_NOT_FROZEN)
    assert not VP.resolve_noise_config(root, trial_model.PHASE_DEVELOPMENT)["ok"]  # sin config: no hay SNR implicito
    noise = _noise(root / "data" / "ruido_planta.wav")
    VP.save_dev_config(root, str(noise), 5.0)
    dev = VP.resolve_noise_config(root, trial_model.PHASE_DEVELOPMENT)
    assert dev["ok"] and dev["snr_db"] == 5.0 and dev["source"] == "development_config"
    assert dev["noise_profile_hash"] == VP.sha256_file(noise)
    assert not VP.resolve_noise_config(root, trial_model.PHASE_FORMAL)["ok"]  # FORMAL ignora la config de desarrollo
    design_path = root / "data" / "experimental_design.json"
    design = json.loads(design_path.read_text(encoding="utf-8"))
    design["voice_protocol"]["noise"].update({"status": "FROZEN", "profile_path": "data/ruido_planta.wav",
                                              "profile_sha256": VP.sha256_file(noise), "snr_db": 10.0, "profile_id": "ruido_planta"})
    design_path.write_text(json.dumps(design), encoding="utf-8")
    formal = VP.resolve_noise_config(root, trial_model.PHASE_FORMAL)
    assert formal["ok"] and formal["snr_db"] == 10.0 and formal["source"] == "experimental_design"
    design["voice_protocol"]["noise"]["profile_sha256"] = "0" * 64
    design_path.write_text(json.dumps(design), encoding="utf-8")
    assert not VP.resolve_noise_config(root, trial_model.PHASE_FORMAL)["ok"]


# ---------------------------------------------------------------------------------------------
# Entrada de voz de un ensayo
# ---------------------------------------------------------------------------------------------

def _asr(transcript: str, calls: list[Path] | None = None, expect_dir: Path | None = None):
    def _fn(path):
        path = Path(path)
        if expect_dir is not None:
            assert path.parent == expect_dir and path.is_file()  # el audio RAW ya esta congelado ANTES del ASR
        if calls is not None:
            calls.append(path)
        return {"transcript": transcript, "model": "fake-asr", "language": "es"}
    return _fn


def test_clean_audio_is_saved_before_asr_and_transcript_is_frozen(tmp_path):
    root, trial = _project(tmp_path), tmp_path / "trial"
    trial.mkdir()
    capture = {"path": str(_tone(tmp_path / "rec.wav")), "device": {"available": True, "name": "Mic"}, "recorded_at": "2026-10-01T10:00:00"}
    calls: list[Path] = []
    result = VP.prepare_voice_input(root, trial, "VOICE_CLEAN", _REFERENCE, _asr(_REFERENCE.upper(), calls, trial / "audio"), capture=capture)
    assert result["ok"] and result["effective_input_text"] == _REFERENCE.upper()  # sin correccion: texto del ASR tal cual
    assert calls == [trial / "audio" / VP.CLEAN_AUDIO_FILENAME]
    voice = result["voice"]
    assert voice["clean_audio_hash"] == VP.sha256_file(trial / "audio" / VP.CLEAN_AUDIO_FILENAME)
    assert voice["audio_capture_success"] and voice["duration_ms"] == 1000 and voice["audio_device"] == "Mic"
    assert voice["wer"] == 0 and voice["normalized_transcript_match"] and voice["transcript_review"] == "NONE"
    assert (trial / "audio" / VP.REFERENCE_FILENAME).read_text(encoding="utf-8") == _REFERENCE
    assert json.loads((trial / "audio" / VP.ASR_RESULT_FILENAME).read_text(encoding="utf-8"))["transcript_raw"] == _REFERENCE.upper()


def test_invalid_capture_is_infrastructure_and_asr_never_runs(tmp_path):
    root, trial = _project(tmp_path), tmp_path / "trial"
    trial.mkdir()
    calls: list[Path] = []
    capture = {"path": str(_tone(tmp_path / "silent.wav", amplitude=0)), "device": {"available": True}}
    result = VP.prepare_voice_input(root, trial, "VOICE_CLEAN", _REFERENCE, _asr("x", calls), capture=capture)
    assert not result["ok"] and result["failure"]["infrastructure"] is True and calls == []
    assert result["failure"]["stage"] == VP.STAGE_AUDIO_CAPTURE and VP.ERROR_AUDIO_CAPTURE_INVALID in result["failure"]["error"]
    assert (trial / "audio" / VP.CLEAN_AUDIO_FILENAME).exists()  # la evidencia del intento se conserva


def test_asr_outage_is_infrastructure_but_empty_transcript_is_asr_failure(tmp_path):
    root = _project(tmp_path)
    capture = {"path": str(_tone(tmp_path / "rec.wav")), "device": {"available": True}}

    def _down(path):
        raise RuntimeError("APIConnectionError")

    first = tmp_path / "t1"
    first.mkdir()
    outage = VP.prepare_voice_input(root, first, "VOICE_CLEAN", _REFERENCE, _down, capture=capture)
    assert outage["failure"]["infrastructure"] is True and outage["failure"]["code"] == VP.ERROR_ASR_UNAVAILABLE
    second = tmp_path / "t2"
    second.mkdir()
    empty = VP.prepare_voice_input(root, second, "VOICE_CLEAN", _REFERENCE, _asr(""), capture=capture)
    assert empty["failure"]["infrastructure"] is False and empty["failure"]["code"] == VP.ERROR_ASR_EMPTY
    record = {"final_status": "FAIL", "failure_stage": "asr", "stages": {}, "errors": []}
    assert ED.classify_trial(record)["failure_category"] == "ASR_FAILURE"
    record = {"final_status": "INFRASTRUCTURE_ERROR", "failure_stage": "audio_capture", "stages": {}, "errors": []}
    assert ED.classify_trial(record)["failure_category"] == "INFRASTRUCTURE_ERROR"


def test_noise_reuses_the_same_clean_audio_and_asr_receives_the_mixture(tmp_path):
    root = _project(tmp_path)
    clean_trial, noise_trial = tmp_path / "clean", tmp_path / "noise"
    clean_trial.mkdir()
    noise_trial.mkdir()
    capture = {"path": str(_tone(tmp_path / "rec.wav")), "device": {"available": True}}
    clean = VP.prepare_voice_input(root, clean_trial, "VOICE_CLEAN", _REFERENCE, _asr(_REFERENCE), capture=capture)
    paired = {"trial_id": "D03_V1_VOICE_CLEAN_DEV_001", "audio_path": str(clean_trial / "audio" / VP.CLEAN_AUDIO_FILENAME),
              "audio_hash": clean["voice"]["clean_audio_hash"], "speaker_id": "S01"}
    noise_profile = _noise(tmp_path / "ruido.wav")
    noise = {"ok": True, "source": "development_config", "noise_profile_id": "ruido", "noise_profile_path": str(noise_profile),
             "noise_profile_hash": VP.sha256_file(noise_profile), "snr_db": 10.0, "noise_offset_rule": VP.NOISE_OFFSET_RULE}
    calls: list[Path] = []
    result = VP.prepare_voice_input(root, noise_trial, "VOICE_NOISE", _REFERENCE, _asr("arranca el motor", calls), paired=paired, noise=noise)
    voice = result["voice"]
    assert result["ok"] and calls == [noise_trial / "audio" / VP.NOISE_AUDIO_FILENAME]  # nunca el clean
    assert voice["clean_audio_hash"] == clean["voice"]["clean_audio_hash"] == voice["paired_clean_audio_hash"]
    assert voice["paired_clean_trial_id"] == paired["trial_id"] and voice["clean_source"] == "PAIRED_CLEAN_TRIAL"
    assert voice["noise_profile_hash"] == noise["noise_profile_hash"] and voice["snr_db"] == 10.0
    assert voice["mixed_audio_hash"] == VP.sha256_file(noise_trial / "audio" / VP.NOISE_AUDIO_FILENAME)
    assert voice["wer"] > 0  # la metrica se calcula, no se corrige


def test_formal_pairing_only_accepts_formal_clean_with_intact_audio(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setattr(trial_model, "get_results_experiments_dir", lambda r: root / "results" / "experiments")

    def _clean_trial(phase: str, number: int) -> Path:
        record = trial_model.new_trial_record("D03", "V1", "VOICE_CLEAN", number, phase=phase)
        directory = trial_model.trial_directory(root, "D03", "V1", record["trial_id"], phase)
        audio = directory / "audio" / VP.CLEAN_AUDIO_FILENAME
        _tone(audio)
        record["voice"] = {"audio_capture_success": True, "clean_audio_hash": VP.sha256_file(audio)}
        trial_model.save_trial(directory, record)
        return directory

    _clean_trial(trial_model.PHASE_DEVELOPMENT, 1)
    assert VP.find_paired_clean(root, "D03", "V1", trial_model.PHASE_FORMAL) is None  # FORMAL nunca usa un clean DEV
    dev = VP.find_paired_clean(root, "D03", "V1", trial_model.PHASE_DEVELOPMENT)
    assert dev and dev["trial_id"] == "D03_V1_VOICE_CLEAN_DEV_001"
    formal_dir = _clean_trial(trial_model.PHASE_FORMAL, 1)
    assert VP.find_paired_clean(root, "D03", "V1", trial_model.PHASE_FORMAL)["trial_id"] == "D03_V1_VOICE_CLEAN_001"
    _tone(formal_dir / "audio" / VP.CLEAN_AUDIO_FILENAME, amplitude=1000)  # audio alterado tras el ensayo
    assert VP.find_paired_clean(root, "D03", "V1", trial_model.PHASE_FORMAL) is None


def test_speaker_must_be_pseudonymous():
    assert VP.validate_speaker_id("S01") is None and VP.validate_speaker_id("S123") is None
    for bad in ("P01", "Henry", "", None, "s01"):
        assert VP.validate_speaker_id(bad)


# ---------------------------------------------------------------------------------------------
# GUI: EJECUTAR ENSAYO COMPLETO
# ---------------------------------------------------------------------------------------------

@pytest.fixture
def complete_flow(pipeline, bench_map, monkeypatch, tmp_path):
    app = pipeline["app"]
    _use_bench_copy(app, bench_map)
    seen: dict[str, Any] = {"commands": [], "parse_kwargs": [], "dialogs": [], "captures": 0}
    base_parse = gui.parse_command

    def _parse(command_text, **kwargs):
        seen["commands"].append(command_text)
        seen["parse_kwargs"].append(sorted(kwargs))
        return base_parse(command_text, **kwargs)

    class _Dialog:
        def __init__(self, parent, trial_dir, retry=False, autostart=False):
            seen["dialogs"].append({"trial_dir": Path(trial_dir), "autostart": autostart})

        def transient(self, parent):
            pass

    monkeypatch.setattr(gui, "parse_command", _parse)
    monkeypatch.setattr(gui, "DeferredEvaluationDialog", _Dialog)
    monkeypatch.setattr(gui, "next_trial_id", lambda root: "TRIAL_TEST")
    monkeypatch.setattr(gui, "record_trial_summary", lambda *a, **k: None)
    monkeypatch.setattr(gui.deferred_evaluator, "environment_precheck", lambda root, phase: {"ok": True, "errors": [], "warnings": []})
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(app, "show_trial_detail", lambda trial_dir: seen.setdefault("detail", []).append(trial_dir))
    app.work_mode_var.set("Experimentacion")
    app._on_work_mode_changed()
    label = next(name for name, profile in app._experiment_profiles_by_case.items() if profile.get("case_id") == "D03")
    app.experiment_case_var.set(label)
    app._on_experiment_case_changed()
    app.experiment_variant_var.set("V1")
    app._on_experiment_variant_changed()
    app.experiment_speaker_var.set("S01")
    yield {"app": app, "seen": seen, "tmp_path": tmp_path, "pipeline": pipeline}
    app.experiment_input_mode_var.set(gui.INPUT_MODE_LABELS["TEXT"])
    app.experiment_phase_var.set(gui.EXPERIMENT_PHASE_LABELS[trial_model.PHASE_DEVELOPMENT])
    app.work_mode_var.set("Normal")
    app._on_work_mode_changed()


def _set_mode(app, mode: str) -> None:
    app.experiment_input_mode_var.set(gui.INPUT_MODE_LABELS[mode])
    app._on_experiment_input_mode_changed()


def _no_mic(monkeypatch, app):
    def _forbidden(*args, **kwargs):
        raise AssertionError("TEXT nunca usa el microfono")
    monkeypatch.setattr(app, "_capture_voice", _forbidden)
    monkeypatch.setattr(app, "_experiment_asr", _forbidden)


def test_text_complete_trial_uses_exact_variant_without_mic_and_one_click_one_trial(complete_flow, monkeypatch):
    app, seen = complete_flow["app"], complete_flow["seen"]
    _set_mode(app, "TEXT")
    _no_mic(monkeypatch, app)
    trial_dir = app.run_complete_trial()
    record = trial_model.load_trial(trial_dir)
    assert seen["commands"] == [_REFERENCE]  # texto EXACTO de la variante
    assert record["effective_input_text"] == record["reference_text"] == _REFERENCE
    assert record["reference_text_hash"] == VP.sha256_text(_REFERENCE) and record["trial_flow"] == "COMPLETE"
    assert record["generation"]["status"] == "SUCCESS" and record["timing"]["generation_total_ms"] is not None
    assert seen["dialogs"] == [{"trial_dir": trial_dir, "autostart": True}]  # la evaluacion sigue sola...
    assert len(DE.list_trials(app.project_root)) == 1  # ...pero nunca se inicia otro ensayo
    assert complete_flow["pipeline"]["download_calls"] == []  # nunca el pipeline inmediato/proyecto Normal


def test_voice_clean_complete_trial_feeds_frozen_asr_transcript_into_the_same_pipeline(complete_flow, monkeypatch):
    app, seen, tmp_path = complete_flow["app"], complete_flow["seen"], complete_flow["tmp_path"]
    _set_mode(app, "TEXT")
    _no_mic(monkeypatch, app)
    app.run_complete_trial()
    text_kwargs = seen["parse_kwargs"][-1]
    _set_mode(app, "VOICE_CLEAN")
    transcript = "Arranca el motor con estar, mantenlo en marcha al soltar el pulsador y detenlo con stop."
    monkeypatch.setattr(app, "_capture_voice", lambda *a: {"path": str(_tone(tmp_path / "rec.wav")),
                                                            "device": {"available": True, "name": "Mic"}, "recorded_at": "x"})
    monkeypatch.setattr(app, "_experiment_asr", lambda path: {"transcript": transcript, "model": "fake-asr"})
    trial_dir = app.run_complete_trial()
    record = trial_model.load_trial(trial_dir)
    assert seen["commands"][-1] == transcript == record["effective_input_text"]  # ASR congelado -> pipeline
    assert seen["parse_kwargs"][-1] == text_kwargs  # mismas llamadas que TEXT: sin prompt especial por modalidad
    assert record["voice"]["wer"] > 0 and record["voice"]["substitutions"] >= 1 and record["speaker_id"] == "S01"
    manifest = json.loads((trial_dir / DE.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert {"audio/clean_audio.wav", "audio/reference.txt", "audio/asr_result.json"} <= set(manifest["files"])
    assert dict(DE.verdict_table(record))["Voice Capture"] == "PASS"
    # Alterar el audio despues invalida la evaluacion (evidencia congelada).
    _tone(trial_dir / "audio" / VP.CLEAN_AUDIO_FILENAME, amplitude=10)
    assert DE.verify_trial_integrity(trial_dir)["ok"] is False


def test_cancel_before_recording_creates_no_trial(complete_flow, monkeypatch):
    app = complete_flow["app"]
    _set_mode(app, "VOICE_CLEAN")
    monkeypatch.setattr(app, "_capture_voice", lambda *a: None)
    assert app.run_complete_trial() is None
    assert DE.list_trials(app.project_root) == []


def test_formal_voice_noise_requires_paired_clean_and_never_records_again(complete_flow, monkeypatch):
    app = complete_flow["app"]
    _set_mode(app, "VOICE_NOISE")
    app.experiment_phase_var.set(gui.EXPERIMENT_PHASE_LABELS[trial_model.PHASE_FORMAL])
    warnings: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, message, **k: warnings.append(message))
    monkeypatch.setattr(gui.voice_protocol, "resolve_noise_config", lambda root, phase: {"ok": True, "errors": []})

    def _forbidden(*a, **k):
        raise AssertionError("FORMAL VOICE_NOISE nunca graba una nueva locucion")
    monkeypatch.setattr(app, "_capture_voice", _forbidden)
    assert app.run_complete_trial() is None
    assert warnings and VP.ERROR_CLEAN_AUDIO_REQUIRED in warnings[-1]
    assert DE.list_trials(app.project_root) == []


def test_generate_only_is_blocked_for_formal(complete_flow, monkeypatch):
    app = complete_flow["app"]
    warnings: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, message, **k: warnings.append(message))
    app.experiment_phase_var.set(gui.EXPERIMENT_PHASE_LABELS[trial_model.PHASE_FORMAL])
    assert app.generate_experiment_trial() is None and "EJECUTAR ENSAYO COMPLETO" in warnings[-1]


def test_repeating_a_cell_requires_a_reason_and_keeps_the_previous_trial(complete_flow, monkeypatch):
    app = complete_flow["app"]
    _set_mode(app, "TEXT")
    _no_mic(monkeypatch, app)
    first = app.run_complete_trial()
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: None)
    assert app.run_complete_trial() is None and len(DE.list_trials(app.project_root)) == 1
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: "LLM devolvio error de red")
    second = app.run_complete_trial()
    record = trial_model.load_trial(second)
    assert record["repeat_of_trial_id"] == first.name and record["repeat_reason"] == "LLM devolvio error de red"
    assert trial_model.load_trial(first)["generation"]["status"] == "SUCCESS"  # el anterior se conserva


def test_voice_panel_hides_audio_controls_for_text(complete_flow):
    app = complete_flow["app"]
    _set_mode(app, "TEXT")
    assert not app.voice_panel.winfo_manager()
    _set_mode(app, "VOICE_CLEAN")
    assert app.voice_panel.winfo_manager() and "Microfono" in app.voice_panel_var.get()


# ---------------------------------------------------------------------------------------------
# Efectos secundarios
# ---------------------------------------------------------------------------------------------

def test_maps_oracles_and_benchmark_unchanged():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
