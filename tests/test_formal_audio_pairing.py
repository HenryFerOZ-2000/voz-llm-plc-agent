"""
FORMAL v1.1: estimulos de voz PAREADOS clean/noisy (trial_experiments.formal_audio) y lotes VOICE_CLEAN (asistido) /
VOICE_NOISE (automatico). Audio sintetico, corpus y ruido maestro en tmp_path; sin microfono, ASR, LLM ni TIA reales.

A-R: corpus y estimulos. 1-15: lotes de voz y GUI.
"""
from __future__ import annotations

import csv
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import pytest

import gui  # noqa: E402
from trial_experiments import batch_runner as B  # noqa: E402
from trial_experiments import benchmark_catalog as BC  # noqa: E402
from trial_experiments import deferred_evaluator as DE  # noqa: E402
from trial_experiments import formal_audio as FA  # noqa: E402
from trial_experiments import results_backup as RB  # noqa: E402
from trial_experiments import text_batch as TB  # noqa: E402
from trial_experiments import trial_model  # noqa: E402
from trial_experiments import voice_protocol as VP  # noqa: E402

from audio_fixtures import audio_env, noise, tone  # noqa: E402,F401
from test_text_batch import batch, _make_trial, _pump, _status  # noqa: E402,F401
from test_phase4a_voice_flow import complete_flow, _set_mode  # noqa: E402,F401
from test_phase1_download_and_trials import pipeline  # noqa: E402,F401
from test_execute_full_pipeline import temp_map, _tia_ready  # noqa: E402,F401
from test_experiment_working_io_map import bench_map  # noqa: E402,F401

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)
_AUDIO_CONFIG_BEFORE = FA.sha256_file(_ROOT / FA.CONFIG_RELATIVE)
DEV = trial_model.PHASE_DEVELOPMENT
FORMAL = trial_model.PHASE_FORMAL
CLEAN, NOISY = FA.CONDITION_CLEAN, FA.CONDITION_NOISE


def _register(env, phase: str, case_id: str = "D01", variant: str = "V1", **tone_kwargs) -> dict[str, Any]:
    capture = tone(env["tmp"] / "captures" / f"{phase}_{case_id}_{variant}.wav", lead_silence=0.3, **tone_kwargs)
    return FA.register_capture(_ROOT, phase, case_id, variant, capture, "S01", {"recorded_at": "2026-10-13T10:00:00"})


def _active_snr(clean_path: Path, noisy_path: Path, post_gain: float, config: dict[str, Any]) -> float:
    clean, noisy = FA.read_wav(clean_path)["samples"], FA.read_wav(noisy_path)["samples"]
    start, end = FA.active_region(clean, 16000, config["active_speech_method"])
    speech = [post_gain * clean[i] for i in range(start, end)]
    residual = [noisy[i] - post_gain * clean[i] for i in range(start, end)]
    return 20 * math.log10(FA._rms(speech) / FA._rms(residual))


# ---------------------------------------------------------------------------------------------
# A-R: corpus pareado
# ---------------------------------------------------------------------------------------------

def test_a_b_same_capture_gives_the_same_clean_and_a_byte_identical_noisy(audio_env):
    formal, dev = _register(audio_env, FORMAL), _register(audio_env, DEV)
    assert formal["clean_sha256"] == dev["clean_sha256"]  # misma captura -> mismo clean (copia byte a byte, sin conversion)
    assert formal["noisy_sha256"] == dev["noisy_sha256"]  # misma celda + mismo master -> noisy identico byte a byte
    assert formal["clean_conversion"].startswith("NONE")
    assert FA.verify_cell(_ROOT, FORMAL, "D01", "V1", regenerate=True)["ok"]  # regeneracion byte a byte


def test_c_snr_is_10_db_within_tolerance_and_independently_recomputable(audio_env):
    manifest = _register(audio_env, FORMAL)
    directory = FA.cell_dir(_ROOT, FORMAL, "D01", "V1")
    config = audio_env["config"]
    assert manifest["target_snr_db"] == config["target_snr_db"] == 10.0
    assert abs(manifest["measured_snr_db"] - 10.0) <= config["snr_tolerance_db"] == 0.25
    recomputed = _active_snr(directory / FA.CLEAN_FILENAME, directory / FA.NOISE_FILENAME, manifest["post_mix_gain"], config)
    assert abs(recomputed - manifest["measured_snr_db"]) < 1e-3
    for key in ("speech_rms", "noise_rms_before_scaling", "noise_gain", "peak_after_mix", "clipping_detected", "active_speech_method",
                "noise_offset_samples", "noise_offset_seconds", "noise_segment_length", "noise_master_sha256", "post_mix_gain",
                "mixing_algorithm_version", "formal_freeze_id", "benchmark_version", "speaker_id", "capture_timestamp",
                "raw_format", "clean_format", "duration_seconds", "capture_raw_sha256", "paired_conditions"):
        assert key in manifest, key
    # Region de voz activa: excluye el silencio inicial (0.3 s) de la locucion.
    start, end = manifest["active_region_samples"]
    assert 0.28 * 16000 <= start <= 0.32 * 16000 and end - start >= 0.95 * 16000


def test_d_no_clipping_loud_capture_uses_one_global_gain_and_persistent_clipping_aborts(audio_env, monkeypatch):
    manifest = _register(audio_env, FORMAL, amplitude=32000)
    assert manifest["post_mix_gain"] < 1.0 and manifest["clipping_detected"] is False
    assert manifest["peak_after_mix"] <= audio_env["config"]["clipping"]["post_mix_peak_limit"]
    assert abs(manifest["measured_snr_db"] - 10.0) <= 0.25  # la ganancia global no altera la SNR
    config = dict(audio_env["config"], clipping={"post_mix_peak_limit": 60000})  # sin margen: la mezcla satura
    capture = tone(audio_env["tmp"] / "loud.wav", amplitude=32000)
    with pytest.raises(FA.FormalAudioError) as error:
        FA.mix_pair(capture, audio_env["master"], "D01", "V2", audio_env["tmp"] / "x.wav", config)
    assert error.value.code == FA.ERROR_CLIPPING and not (audio_env["tmp"] / "x.wav").exists()


def test_e_noisy_references_its_own_clean(audio_env):
    manifest = _register(audio_env, DEV)
    directory = FA.cell_dir(_ROOT, DEV, "D01", "V1")
    noisy = FA.stimulus(_ROOT, DEV, "D01", "V1", NOISY)
    assert noisy["path"] == str(directory / FA.NOISE_FILENAME) and noisy["audio_sha256"] == FA.sha256_file(directory / FA.NOISE_FILENAME)
    assert noisy["audio_source_clean_sha256"] == manifest["clean_sha256"] == FA.sha256_file(directory / FA.CLEAN_FILENAME)
    assert noisy["paired_audio_sha256"] == manifest["clean_sha256"]
    clean = FA.stimulus(_ROOT, DEV, "D01", "V1", CLEAN)
    assert clean["paired_audio_sha256"] == noisy["audio_sha256"] and clean["audio_manifest_sha256"] == noisy["audio_manifest_sha256"]


def test_g_formal_noise_without_pair_or_without_used_clean_aborts_before_asr(audio_env):
    with pytest.raises(FA.FormalAudioError) as missing:
        FA.stimulus(_ROOT, FORMAL, "D02", "V1", NOISY)
    assert missing.value.code == FA.ERROR_PAIR_MISSING
    _register(audio_env, FORMAL, "D02", "V1")
    with pytest.raises(FA.FormalAudioError) as unused:  # FORMAL: el clean debe haberse usado antes en VOICE_CLEAN
        FA.stimulus(_ROOT, FORMAL, "D02", "V1", NOISY)
    assert unused.value.code == FA.ERROR_PAIR_MISSING
    FA.mark_used(_ROOT, FORMAL, "D02", "V1", CLEAN, "D02_V1_VOICE_CLEAN_001")
    assert FA.stimulus(_ROOT, FORMAL, "D02", "V1", NOISY)["clean_uses"][0]["trial_id"] == "D02_V1_VOICE_CLEAN_001"


def test_h_pair_is_immutable_after_use_and_rerecord_needs_a_human_decision(audio_env):
    first = _register(audio_env, FORMAL)
    with pytest.raises(FA.FormalAudioError) as exists:  # nunca se sustituye en silencio
        _register(audio_env, FORMAL, frequency=330.0)
    assert exists.value.code == FA.ERROR_CELL_EXISTS
    with pytest.raises(ValueError):
        FA.rerecord_cell(_ROOT, FORMAL, "D01", "V1", "", "")
    FA.rerecord_cell(_ROOT, FORMAL, "D01", "V1", "Henry Ochoa", "tos durante la locucion")
    second = _register(audio_env, FORMAL, frequency=330.0)
    entry = FA.cell_entry(FA.load_corpus(_ROOT, FORMAL), "D01", "V1")
    assert entry["attempts"][0]["previous_clean_sha256"] == first["clean_sha256"] != second["clean_sha256"]
    archived = audio_env["roots"][FORMAL] / entry["attempts"][0]["archived_to"]
    assert FA.sha256_file(archived / FA.CLEAN_FILENAME) == first["clean_sha256"]  # el intento anterior se conserva
    FA.mark_used(_ROOT, FORMAL, "D01", "V1", CLEAN, "T1")
    for action in (lambda: FA.rerecord_cell(_ROOT, FORMAL, "D01", "V1", "Henry Ochoa", "otra"),
                   lambda: _register(audio_env, FORMAL, frequency=440.0)):
        with pytest.raises(FA.FormalAudioError) as immutable:
            action()
        assert immutable.value.code == FA.ERROR_CELL_IMMUTABLE


def test_l_noise_offsets_are_deterministic_per_cell_and_recorded(audio_env):
    salt, length = audio_env["config"]["noise_offset"]["salt"], 48000
    assert salt == "FORMAL_V1_1"
    assert FA.noise_offset("D01", "V1", salt, length) == FA.noise_offset("D01", "V1", salt, length)
    offsets = {FA.noise_offset(case, variant, salt, 10 ** 9) for case, variant in FA.expected_cells(_ROOT)}
    assert len(offsets) == 96  # cada celda su propio segmento del master
    manifest = _register(audio_env, DEV, "P03", "V2")
    assert manifest["noise_offset_samples"] == FA.noise_offset("P03", "V2", salt, manifest["noise_master_length_samples"])
    assert manifest["noise_segment_length"] == manifest["clean_format"]["frames"]


@pytest.mark.parametrize("tamper", ["manifest", "corpus_hash", "snr_field"])
def test_m_manifest_tampering_is_detected(audio_env, tamper):
    _register(audio_env, FORMAL)
    path = FA.cell_dir(_ROOT, FORMAL, "D01", "V1") / FA.CELL_MANIFEST
    if tamper == "manifest":
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["speaker_id"] = "S99"
        path.write_text(json.dumps(manifest), encoding="utf-8")
    elif tamper == "corpus_hash":
        corpus = FA.load_corpus(_ROOT, FORMAL)
        FA.cell_entry(corpus, "D01", "V1")["clean_sha256"] = "0" * 64
        FA.save_corpus(_ROOT, FORMAL, corpus)
    else:
        corpus = FA.load_corpus(_ROOT, FORMAL)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["target_snr_db"] = 5.0
        path.write_text(json.dumps(manifest), encoding="utf-8")
        FA.cell_entry(corpus, "D01", "V1")["audio_manifest_sha256"] = FA.sha256_file(path)  # aun re-firmado: SNR fuera de lo congelado
        FA.save_corpus(_ROOT, FORMAL, corpus)
    assert not FA.verify_cell(_ROOT, FORMAL, "D01", "V1")["ok"]
    with pytest.raises(FA.FormalAudioError):
        FA.stimulus(_ROOT, FORMAL, "D01", "V1", CLEAN)


@pytest.mark.parametrize("damage", ["corrupt_noisy", "missing_clean", "master_changed"])
def test_n_corrupted_or_missing_audio_aborts_before_asr(audio_env, damage, tmp_path):
    _register(audio_env, DEV)
    directory = FA.cell_dir(_ROOT, DEV, "D01", "V1")
    if damage == "corrupt_noisy":
        data = bytearray((directory / FA.NOISE_FILENAME).read_bytes())
        data[-2:] = b"\x00\x01"
        (directory / FA.NOISE_FILENAME).write_bytes(bytes(data))
    elif damage == "missing_clean":
        (directory / FA.CLEAN_FILENAME).unlink()
    else:
        noise(audio_env["master"], seed=999)  # el master ya no es el aprobado
    calls: list[Path] = []
    with pytest.raises(FA.FormalAudioError):
        FA.stimulus(_ROOT, DEV, "D01", "V1", NOISY)
    assert calls == []


def test_o_6_retry_reuses_exactly_the_same_wav_and_asr_gets_the_frozen_stimulus(audio_env, tmp_path):
    _register(audio_env, DEV)
    received: list[str] = []

    def _asr(path: Path) -> dict[str, Any]:
        received.append(VP.sha256_file(path))
        return {"transcript": "arranca el motor", "model": "fake"}

    for attempt in (1, 2):  # p.ej. reintento por INFRASTRUCTURE_ERROR: misma celda, nuevo ensayo
        stimulus = {**FA.stimulus(_ROOT, DEV, "D01", "V1", CLEAN), "phase": DEV}
        result = VP.prepare_voice_input(_ROOT, tmp_path / f"trial_{attempt}", "VOICE_CLEAN", "arranca el motor", _asr, stimulus=stimulus)
        assert result["ok"] and result["voice"]["audio_sha256"] == result["voice"]["asr_audio_sha256"]
    clean_sha = FA.cell_entry(FA.load_corpus(_ROOT, DEV), "D01", "V1")["clean_sha256"]
    assert received == [clean_sha, clean_sha]
    assert [u["trial_id"] for u in FA.cell_entry(FA.load_corpus(_ROOT, DEV), "D01", "V1")["uses"]] == ["trial_1", "trial_2"]


def test_noise_trial_asr_receives_the_noisy_of_the_same_clean(audio_env, tmp_path):
    _register(audio_env, DEV)
    received: list[str] = []
    stimulus = {**FA.stimulus(_ROOT, DEV, "D01", "V1", NOISY), "phase": DEV}
    result = VP.prepare_voice_input(_ROOT, tmp_path / "noise_trial", "VOICE_NOISE", "arranca el motor",
                                    lambda path: received.append(VP.sha256_file(path)) or {"transcript": "arranca", "model": "f"},
                                    stimulus=stimulus)
    voice = result["voice"]
    assert received == [stimulus["audio_sha256"]] and voice["audio_condition"] == "VOICE_NOISE"
    assert voice["audio_source_clean_sha256"] == voice["clean_audio_hash"] == stimulus["audio_source_clean_sha256"]
    assert voice["target_snr_db"] == 10.0 and abs(voice["measured_snr_db"] - 10.0) <= 0.25
    assert FA.cell_entry(FA.load_corpus(_ROOT, DEV), "D01", "V1")["state"] == FA.STATE_PAIR_READY  # DEV NOISE no marca clean usado


def test_master_missing_blocks_formal_and_approval_validates_the_file(tmp_path, monkeypatch):
    config = json.loads((_ROOT / FA.CONFIG_RELATIVE).read_text(encoding="utf-8"))
    project = tmp_path / "proj"
    (project / "config").mkdir(parents=True)
    (project / FA.CONFIG_RELATIVE).write_text(json.dumps(config), encoding="utf-8")
    status = FA.noise_master_status(project, FORMAL)
    assert not status["ready"] and FA.ERROR_MASTER_NOT_READY in status["error"] and "industrial_noise_master.wav" in status["error"]
    master = project / config["noise_master"]["path"]
    noise(master, seconds=2.0)
    with pytest.raises(FA.FormalAudioError):  # < 60 s: no se aprueba
        FA.approve_noise_master(project, "Henry Ochoa", "grabacion propia", "")
    noise(master, seconds=61.0)
    approved = FA.approve_noise_master(project, "Henry Ochoa", "grabacion propia del laboratorio", "propia")
    assert approved["sha256"] == FA.sha256_file(master)
    assert FA.noise_master_status(project, FORMAL)["ready"]
    noise(master, seconds=61.0, seed=7)  # cambiar el master despues de aprobarlo lo invalida
    assert not FA.noise_master_status(project, FORMAL)["ready"]


def test_repository_master_is_not_approved_yet_so_formal_voice_noise_is_blocked():
    # Estado real del repositorio: AUDIO_NOISE_MASTER_READY = NO hasta que exista y se apruebe el ruido maestro.
    config = FA.load_config(_ROOT)
    if config["noise_master"].get("sha256"):
        pytest.skip("ruido maestro ya aprobado")
    assert not FA.noise_master_status(_ROOT, FORMAL)["ready"]


def test_i_text_rows_and_summaries_are_unchanged():
    record = {"input_mode": "TEXT", "trial_id": "T"}
    row = TB.trial_row(_ROOT, record, {"input_mode": "TEXT"}, {"batch_id": "B"})
    assert not set(TB.VOICE_CSV_FIELDS) & set(row)
    voice_row = TB.trial_row(_ROOT, {"input_mode": "VOICE_NOISE", "voice": {"audio_sha256": "abc", "wer": 0.1}},
                             {"input_mode": "VOICE_NOISE"}, {"batch_id": "B"})
    assert voice_row["audio_sha256"] == "abc" and voice_row["wer"] == 0.1


def test_j_k_benchmark_oracles_audio_config_and_formal_v1_0_unchanged():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
    assert FA.sha256_file(_ROOT / FA.CONFIG_RELATIVE) == _AUDIO_CONFIG_BEFORE  # los tests nunca escriben la config real
    tag = subprocess.run(["git", "rev-parse", "formal-v1.0^{commit}"], cwd=_ROOT, capture_output=True, text=True)
    if tag.returncode != 0:
        pytest.skip("tag formal-v1.0 no disponible en este clon")
    assert tag.stdout.strip() == "a2e06a1a8c30e9a383fc1f3a1efd46da3ffed1b1"


def test_q_audio_is_ignored_by_git():
    paths = ["results/formal_audio/D01/V1/clean_stimulus.wav", "results/formal_audio/D01/V1/noise_stimulus.wav",
             "results/formal_audio/D01/V1/capture_raw.wav", "results/development_audio/D01/V1/clean_stimulus.wav",
             "formal_assets/audio/industrial_noise_master.wav"]
    result = subprocess.run(["git", "check-ignore", *paths], cwd=_ROOT, capture_output=True, text=True)
    if result.returncode == 128:
        pytest.skip("git no disponible")
    assert sorted(result.stdout.split()) == sorted(paths)
    tracked = subprocess.run(["git", "ls-files", "*.wav"], cwd=_ROOT, capture_output=True, text=True).stdout.split()
    assert tracked == []


def test_r_backup_manifest_includes_audio_and_detects_damage(tmp_path):
    project = tmp_path / "proj"
    tone(project / "results" / "formal_audio" / "D01" / "V1" / FA.CLEAN_FILENAME)
    (project / "results" / "experiments" / "D01").mkdir(parents=True)
    (project / "results" / "experiments" / "D01" / "trial.json").write_text("{}", encoding="utf-8")
    (project / "results" / "batches").mkdir(parents=True)
    result = RB.backup_results(project, tmp_path / "backup", "b1")
    paths = {f["path"] for f in result["files"]}
    assert "results/formal_audio/D01/V1/clean_stimulus.wav" in paths and result["audio_files"] == 1
    assert RB.verify_backup(Path(result["target"]))["ok"]
    with pytest.raises(FileExistsError):
        RB.backup_results(project, tmp_path / "backup", "b1")
    (Path(result["target"]) / "results/formal_audio/D01/V1/clean_stimulus.wav").write_bytes(b"x")
    assert not RB.verify_backup(Path(result["target"]))["ok"]


def test_noise_batch_preflight_lists_missing_pairs_and_requires_96_for_formal(audio_env):
    preflight = FA.noise_batch_preflight(_ROOT, FORMAL, cells=[("D01", "V1")])
    assert preflight["total"] == 96 and preflight["pairs_ready"] == 0 and len(preflight["missing"]) == 96  # FORMAL ignora el subconjunto
    _register(audio_env, FORMAL)
    FA.mark_used(_ROOT, FORMAL, "D01", "V1", CLEAN, "T1")
    preflight = FA.noise_batch_preflight(_ROOT, FORMAL)
    assert preflight["pairs_ready"] == 1 and not preflight["ok"] and not preflight["missing"][0].startswith("D01 V1")
    dev = FA.noise_batch_preflight(_ROOT, DEV, cells=[("D01", "V1")])
    assert dev["total"] == 1 and dev["pairs_ready"] == 0  # DEV: celda no grabada en el corpus de desarrollo
    summary = FA.corpus_summary(_ROOT, FORMAL)
    assert (summary["recorded_clean"], summary["noise_pairs_ready"], summary["clean_trials"], summary["noise_trials"]) == (1, 1, 1, 0)


# ---------------------------------------------------------------------------------------------
# 1-15: lotes de voz (motor real de lotes + GUI real; generacion/evaluacion simuladas)
# ---------------------------------------------------------------------------------------------

def _forbid_microphone(monkeypatch, app) -> None:
    def _forbidden(*args, **kwargs):
        raise AssertionError("VOICE_NOISE nunca usa el microfono ni selecciona dispositivo de audio")
    for name in ("start_recording", "stop_recording", "get_input_device_info"):
        monkeypatch.setattr(app.speech_recognizer, name, _forbidden)
    monkeypatch.setattr(app, "_capture_voice", _forbidden)
    monkeypatch.setattr(gui, "VoiceCaptureDialog", _forbidden)
    monkeypatch.setattr(gui, "CleanBatchCellDialog", _forbidden)


@pytest.fixture
def voice_batch(app, batch, audio_env, monkeypatch):
    """Lote con la GUI real: el ensayo simulado pide el estimulo del corpus (mismo _corpus_stimulus) y lo pasa al ASR."""
    state = {**batch, "asr": [], "dialogs": 0, "captures": []}
    root = batch["root"]

    class _CellDialog:
        pause = False

        def __init__(self, parent, entry, manifest, audio_state, pair_state):
            state["dialogs"] += 1
            state["dialog_states"] = (audio_state, pair_state, entry["status"], entry["reference_text"])
            if _CellDialog.pause:
                self.result = None
                return
            path = tone(audio_env["tmp"] / "mic" / f"{entry['case_id']}_{entry['variant_id']}_{state['dialogs']}.wav", lead_silence=0.2)
            state["captures"].append(path)
            self.result = {"path": str(path), "device": {"name": "Mic test"}, "recorded_at": "2026-10-13T10:00:00"}

    def _fake_complete_trial(batch_trial=None):
        manifest = app._text_batch["manifest"]
        entry = next(e for e in manifest["ordered_trial_plan"] if e["index"] == batch_trial["index"])
        stimulus = app._corpus_stimulus(manifest["phase"], entry["case_id"], entry["variant_id"], entry["input_mode"],
                                        entry["reference_text"], "S01", batch_trial)
        if stimulus is None:
            return None  # PRECHECK ABORT antes de crear el ensayo (antes del ASR/LLM)
        outcome = state["outcomes"].get((entry["case_id"], entry["variant_id"]), "PASS")
        directory = _make_trial(root, entry["case_id"], entry["variant_id"], manifest["phase"], semantic_fail=outcome == "SEMANTIC_FAIL")
        batch_trial["on_started"](directory)

        def _asr(path: Path) -> dict[str, Any]:
            noisy = FA.cell_dir(root, manifest["phase"], entry["case_id"], entry["variant_id"]) / FA.NOISE_FILENAME
            state["asr"].append({"cell": (entry["case_id"], entry["variant_id"]), "sha": VP.sha256_file(path),
                                 "noisy_existed": noisy.is_file()})
            return {"transcript": entry["reference_text"], "model": "fake-asr"}

        # audio del ensayo en una carpeta hermana con el MISMO nombre (trial_id): el paquete simulado ya esta congelado
        result = VP.prepare_voice_input(root, directory.parent / "_voice" / directory.name, entry["input_mode"], entry["reference_text"],
                                        _asr, stimulus=stimulus)
        voice = result["voice"]
        trial_model.update_trial(directory, {"voice": voice, **{k: voice.get(k) for k in ("audio_condition", "audio_sha256",
                                                                                         "paired_audio_sha256", "audio_manifest_sha256")}})
        generation = trial_model.load_trial(directory)["generation"]["status"]
        app.after(0, lambda: batch_trial["on_generated"](directory, generation))
        return directory

    monkeypatch.setattr(app, "run_complete_trial", _fake_complete_trial)
    monkeypatch.setattr(gui, "CleanBatchCellDialog", _CellDialog)
    monkeypatch.setattr(app, "wait_window", lambda *a, **k: None)
    state["cell_dialog"] = _CellDialog
    yield state
    _CellDialog.pause = False


def _run_voice(app, phase, cases, variants, mode, expect_ok=True) -> dict[str, Any]:
    result = app.start_text_batch(phase, cases, list(variants), mode)
    assert result["ok"] is expect_ok, result
    if not expect_ok:
        return result
    _pump(app, lambda: _status(app) != TB.STATUS_RUNNING and not app._tia_busy())
    return app._text_batch["manifest"]


def test_1_2_3_14_clean_batch_asks_one_recording_per_cell_freezes_noisy_before_asr_and_advances(app, voice_batch):
    root = voice_batch["root"]
    manifest = _run_voice(app, DEV, ["D01", "D02"], ("V1", "V2", "V3"), "VOICE_CLEAN")
    assert manifest["status"] == TB.STATUS_COMPLETED and manifest["completed_trials"] == 6
    assert manifest["input_mode"] == "VOICE_CLEAN" and manifest["batch_kind"] == "ASSISTED_HUMAN_VOICE"
    assert manifest["batch_id"].startswith("VCLEAN_DEV_")
    assert voice_batch["dialogs"] == 6  # una interaccion humana por celda, en orden; avance automatico
    assert [a["cell"] for a in voice_batch["asr"]] == [(c, v) for c in ("D01", "D02") for v in ("V1", "V2", "V3")]
    assert all(a["noisy_existed"] for a in voice_batch["asr"])  # el par noisy se congelo ANTES del ASR
    corpus = FA.load_corpus(root, DEV)
    for entry in manifest["ordered_trial_plan"]:
        cell = FA.cell_entry(corpus, entry["case_id"], entry["variant_id"])
        assert cell["state"] == FA.STATE_USED_CLEAN and cell["uses"][0]["trial_id"] == entry["trial_id"]
        assert entry["result"]["audio_sha256"] == cell["clean_sha256"]  # 14: SHA del audio en los resultados del lote
        assert entry["result"]["paired_audio_sha256"] == cell["noisy_sha256"]
    rows = list(csv.DictReader((TB.batch_dir_for(root, manifest) / TB.SUMMARY_CSV).open(encoding="utf-8")))
    assert rows[0]["audio_sha256"] and rows[0]["audio_condition"] == "VOICE_CLEAN" and rows[0]["wer"] == "0.0"


def test_4_15_pausing_before_recording_pauses_the_batch_and_gui_shows_progress(app, voice_batch):
    voice_batch["cell_dialog"].pause = True
    manifest = _run_voice(app, DEV, ["D01"], ("V1", "V2"), "VOICE_CLEAN")
    assert manifest["status"] == TB.STATUS_PAUSED and manifest["pause_reason"] == TB.PAUSE_USER
    assert DE.list_trials(voice_batch["root"]) == [] and voice_batch["asr"] == []  # sin grabacion no hay ensayo
    assert voice_batch["dialog_states"][:3] == ("NOT RECORDED", "NOT READY", TB.ENTRY_PENDING)
    assert voice_batch["dialog_states"][3] == BC.get_case(voice_batch["root"], "D01")["variants"]["V1"]  # comando exacto
    lines = "\n".join(app.text_batch_progress_lines())
    assert "LOTE VOICE_CLEAN PAUSADO" in lines and "Ensayo actual: 1 / 2" in lines
    assert "AUDIO CLEAN: NOT RECORDED" in lines and "AUDIO NOISE PAIR: NOT READY" in lines and "SNR: 10.0 dB" in lines
    app._refresh_text_batch_button()
    assert app.voice_clean_batch_button.cget("text") == "LOTE VOICE_CLEAN (0/2) · PAUSED"
    assert app.voice_noise_batch_button.cget("text") == "EJECUTAR LOTE VOICE_NOISE"
    voice_batch["cell_dialog"].pause = False
    assert app.resume_text_batch()["ok"]
    _pump(app, lambda: _status(app) != TB.STATUS_RUNNING and not app._tia_busy())
    assert app._text_batch["manifest"]["status"] == TB.STATUS_COMPLETED and voice_batch["dialogs"] == 3


def test_5_6_infrastructure_pause_and_retry_never_rerecord_and_reuse_the_same_wav(app, voice_batch):
    voice_batch["outcomes"].update({("D01", "V2"): "INFRA_ONCE"})
    manifest = _run_voice(app, DEV, ["D01"], ("V1", "V2", "V3"), "VOICE_CLEAN")
    assert manifest["status"] == TB.STATUS_PAUSED and manifest["pause_reason"] == TB.PAUSE_INFRASTRUCTURE  # 12: INFRA pausa
    assert voice_batch["dialogs"] == 2
    assert app.retry_text_batch_trial("PLCSIM no respondia")["ok"]
    _pump(app, lambda: _status(app) != TB.STATUS_RUNNING and not app._tia_busy())
    assert app._text_batch["manifest"]["status"] == TB.STATUS_COMPLETED
    assert voice_batch["dialogs"] == 3  # D01 V2 nunca se volvio a grabar
    # Una celda ya grabada/usada no vuelve a pedir locucion y reutiliza exactamente el mismo WAV.
    sha = FA.cell_entry(FA.load_corpus(voice_batch["root"], DEV), "D01", "V2")["clean_sha256"]
    assert app._batch_clean_capture({"case_id": "D01", "variant_id": "V2"}, {"phase": DEV}) is None
    stimulus = app._corpus_stimulus(DEV, "D01", "V2", "VOICE_CLEAN", "x", "S01", {"capture": None})
    assert stimulus["audio_sha256"] == sha and voice_batch["dialogs"] == 3


def test_11_functional_fail_and_review_continue_and_are_never_retried(app, voice_batch):
    voice_batch["outcomes"].update({("D01", "V1"): "FUNCTIONAL_FAIL", ("D01", "V2"): "SEMANTIC_FAIL"})
    manifest = _run_voice(app, DEV, ["D01"], ("V1", "V2", "V3"), "VOICE_CLEAN")
    assert manifest["status"] == TB.STATUS_COMPLETED
    assert [e["result"]["final_verdict"] for e in manifest["ordered_trial_plan"]] == ["FAIL", "FAIL", "PASS"]
    assert all(reason is None for _, reason in voice_batch["evaluated"])
    assert app.retry_text_batch_trial("quiero PASS")["ok"] is False  # P: FAIL/REVIEW nunca se reintenta


def test_7_8_9_10_13_noise_batch_requires_pairs_never_uses_the_mic_and_feeds_the_frozen_noisy(app, voice_batch, monkeypatch):
    root = voice_batch["root"]
    result = _run_voice(app, FORMAL, ["D01"], ("V1",), "VOICE_NOISE", expect_ok=False)  # 7: FORMAL exige 96/96
    assert result["errors"][0] == "PAIRS READY: 0 / 96" and any(FA.ERROR_PAIR_MISSING in e for e in result["errors"])
    assert app._text_batch is None  # no se creo el lote: abortado antes de cualquier ASR
    result = _run_voice(app, DEV, ["D01"], ("V1", "V2"), "VOICE_NOISE", expect_ok=False)
    assert result["errors"][0] == "PAIRS READY: 0 / 2"
    clean = _run_voice(app, DEV, ["D01"], ("V1", "V2"), "VOICE_CLEAN")  # 13: manifiesto CLEAN independiente
    clean_id = clean["batch_id"]
    _forbid_microphone(monkeypatch, app)  # 8: desde aqui cualquier uso del microfono falla
    voice_batch["asr"].clear()
    noise_manifest = _run_voice(app, DEV, ["D01"], ("V1", "V2"), "VOICE_NOISE")
    assert noise_manifest["status"] == TB.STATUS_COMPLETED and noise_manifest["batch_kind"] == "AUTOMATIC_FROZEN_STIMULI"
    assert noise_manifest["batch_id"].startswith("VNOISE_DEV_") and noise_manifest["batch_id"] != clean_id
    assert TB.load_manifest(TB.batch_dir_for(root, clean))["input_mode"] == "VOICE_CLEAN"  # el CLEAN no se toco
    corpus = FA.load_corpus(root, DEV)
    for asr, entry in zip(voice_batch["asr"], noise_manifest["ordered_trial_plan"]):
        cell = FA.cell_entry(corpus, *asr["cell"])
        assert asr["sha"] == cell["noisy_sha256"]  # 9: noisy correcto, del MISMO clean
        assert entry["result"]["audio_source_clean_sha256"] == cell["clean_sha256"]
        assert entry["result"]["paired_clean_trial_id"] == cell["uses"][0]["trial_id"]
        assert cell["state"] == FA.STATE_USED_BOTH


def test_10_noise_batch_pause_after_current_and_resume(app, voice_batch, monkeypatch):
    for variant in ("V1", "V2", "V3"):
        capture = tone(voice_batch["root"] / "tmpcap" / f"{variant}.wav", lead_silence=0.2)
        FA.register_capture(voice_batch["root"], DEV, "D01", variant, capture, "S01")
    _forbid_microphone(monkeypatch, app)
    original = app._batch_on_started

    def _pause_after_first(entry, directory):
        original(entry, directory)
        if entry["index"] == 0:
            app.request_text_batch_pause()
    monkeypatch.setattr(app, "_batch_on_started", _pause_after_first)
    manifest = _run_voice(app, DEV, ["D01"], ("V1", "V2", "V3"), "VOICE_NOISE")
    assert manifest["status"] == TB.STATUS_PAUSED and manifest["completed_trials"] == 1
    monkeypatch.setattr(app, "_batch_on_started", original)
    assert app.resume_text_batch()["ok"]
    _pump(app, lambda: _status(app) != TB.STATUS_RUNNING and not app._tia_busy())
    final = app._text_batch["manifest"]
    assert final["status"] == TB.STATUS_COMPLETED and len(voice_batch["asr"]) == 3  # nunca se repite un ensayo hecho


def test_noise_precheck_abort_in_batch_pauses_before_asr(app, voice_batch, monkeypatch):
    capture = tone(voice_batch["root"] / "tmpcap" / "v1.wav", lead_silence=0.2)
    FA.register_capture(voice_batch["root"], DEV, "D01", "V1", capture, "S01")
    _forbid_microphone(monkeypatch, app)
    original_create = app.start_text_batch
    result = original_create(DEV, ["D01"], ["V1"], "VOICE_NOISE")
    assert result["ok"]
    # el noisy se corrompe con el lote ya creado: el ensayo aborta en el precheck (antes del ASR) y el lote se pausa
    noisy = FA.cell_dir(voice_batch["root"], DEV, "D01", "V1") / FA.NOISE_FILENAME
    noisy.write_bytes(noisy.read_bytes()[:-4] + b"\x01\x02\x03\x04")
    _pump(app, lambda: _status(app) != TB.STATUS_RUNNING and not app._tia_busy())
    manifest = app._text_batch["manifest"]
    assert manifest["status"] == TB.STATUS_PAUSED and FA.ERROR_INTEGRITY in manifest["pause_detail"]
    assert voice_batch["asr"] == [] and DE.list_trials(voice_batch["root"]) == []


def test_gui_voice_noise_single_trial_never_records_and_records_the_pair(complete_flow, audio_env, monkeypatch):
    app = complete_flow["app"]
    FA.register_capture(app.project_root, DEV, "D03", "V1", tone(audio_env["tmp"] / "c.wav", lead_silence=0.2), "S01")
    _forbid_microphone(monkeypatch, app)
    received: list[str] = []
    monkeypatch.setattr(app, "_experiment_asr", lambda path: received.append(VP.sha256_file(path)) or
                        {"transcript": BC.get_case(_ROOT, "D03")["variants"]["V1"], "model": "fake"})
    _set_mode(app, "VOICE_NOISE")
    panel = app.voice_panel_var.get()
    assert "SOURCE CLEAN: D03_V1 " in panel and "SNR: 10.0 dB" in panel and "Microfono" not in panel
    assert not app.capture_voice_button.winfo_manager()  # VOICE_NOISE: sin boton de grabar
    trial_dir = app.run_complete_trial()
    record = trial_model.load_trial(trial_dir)
    cell = FA.cell_entry(FA.load_corpus(app.project_root, DEV), "D03", "V1")
    assert received == [cell["noisy_sha256"]] == [record["audio_sha256"]]
    assert record["audio_condition"] == "VOICE_NOISE" and record["audio_source_clean_sha256"] == cell["clean_sha256"]
    assert record["target_snr_db"] == 10.0 and record["audio_manifest_sha256"] == cell["audio_manifest_sha256"]


def test_text_trial_has_no_audio_fields(complete_flow, monkeypatch):
    app = complete_flow["app"]
    _set_mode(app, "TEXT")
    monkeypatch.setattr(app, "_experiment_asr", lambda *a: (_ for _ in ()).throw(AssertionError("TEXT sin ASR")))
    record = trial_model.load_trial(app.run_complete_trial())
    assert "audio_condition" not in record and "audio_sha256" not in record and record["effective_input_text"] == record["reference_text"]
