"""
Estimulos de voz PAREADOS clean/noise (FORMAL v1.1).

Por celda (case_id + variante) existe UNA locucion humana fuente:

  capture_raw.wav  -> grabacion original (nunca se sobrescribe)
  clean_stimulus.wav -> estimulo canonico (WAV PCM16, mono, 16 kHz) que recibe el ASR en VOICE_CLEAN; si la captura
                        ya tiene ese formato es una copia byte a byte (sin conversiones innecesarias)
  noise_stimulus.wav -> derivado del MISMO clean, generado INMEDIATAMENTE al congelar el clean y ANTES de cualquier
                        ASR: la condicion de ruido no puede adaptarse a posteriori al comportamiento del ASR
  audio_manifest.json -> hashes, formato, SNR objetivo/medido, ganancias, offset del ruido, algoritmo

y el corpus (audio_corpus_manifest.json) lista las 96 celdas con su estado:
NOT_RECORDED -> CLEAN_READY -> PAIR_READY -> USED_CLEAN -> USED_CLEAN_AND_NOISE. Una vez usado el clean en un ensayo,
la pareja es INMUTABLE: nunca se regraba (ni por un FAIL/REVIEW ni por un reintento de infraestructura).

Mezcla PAIRED_ACTIVE_RMS_SNR_V1 (Python puro, determinista):
  region activa  = tramas de 20 ms con RMS >= max(pico_trama * 10^(-30/20), 50), de la primera a la ultima activa;
  offset         = SHA256(case|variant|salt) mod N (master de N muestras), lazo ciclico si hace falta (registrado);
  g              = rms_voz_region / (rms_ruido_region * 10^(SNR/20));
  mezcla         = clean + g * ruido; si |mezcla| > limite, UN factor global post_mix_gain sobre toda la mezcla
                   (conserva el SNR); redondeo a int16; si aun hay clipping -> se aborta;
  SNR medido     = 20 log10(rms(post*clean) / rms(salida - post*clean)) en la region activa (incluye cuantizacion);
                   |medido - objetivo| <= tolerancia o el estimulo no se acepta.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import wave
from array import array
from datetime import datetime
from pathlib import Path
from typing import Any

CONFIG_RELATIVE = Path("config") / "formal_audio_config.json"
CORPUS_MANIFEST = "audio_corpus_manifest.json"
CELL_MANIFEST = "audio_manifest.json"
RAW_FILENAME = "capture_raw.wav"
CLEAN_FILENAME = "clean_stimulus.wav"
NOISE_FILENAME = "noise_stimulus.wav"
ATTEMPTS_DIRNAME = "attempts"

CONDITION_CLEAN = "VOICE_CLEAN"
CONDITION_NOISE = "VOICE_NOISE"

STATE_NOT_RECORDED = "NOT_RECORDED"
STATE_CLEAN_READY = "CLEAN_READY"
STATE_PAIR_READY = "PAIR_READY"
STATE_USED_CLEAN = "USED_CLEAN"
STATE_USED_BOTH = "USED_CLEAN_AND_NOISE"
CELL_STATES = (STATE_NOT_RECORDED, STATE_CLEAN_READY, STATE_PAIR_READY, STATE_USED_CLEAN, STATE_USED_BOTH)
USED_STATES = (STATE_USED_CLEAN, STATE_USED_BOTH)

ERROR_MASTER_NOT_READY = "AUDIO_NOISE_MASTER_NOT_READY"
ERROR_CAPTURE_FORMAT = "AUDIO_CAPTURE_FORMAT_UNSUPPORTED"
ERROR_NO_SPEECH = "AUDIO_NO_ACTIVE_SPEECH"
ERROR_SNR_OUT_OF_TOLERANCE = "AUDIO_SNR_OUT_OF_TOLERANCE"
ERROR_CLIPPING = "AUDIO_CLIPPING"
ERROR_CELL_EXISTS = "AUDIO_CELL_ALREADY_RECORDED"
ERROR_CELL_IMMUTABLE = "AUDIO_CELL_IMMUTABLE"
ERROR_PAIR_MISSING = "AUDIO_PAIR_MISSING"
ERROR_INTEGRITY = "AUDIO_INTEGRITY_FAILED"


class FormalAudioError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------------------------

def load_config(project_root: Path) -> dict[str, Any]:
    return json.loads((Path(project_root) / CONFIG_RELATIVE).read_text(encoding="utf-8"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def corpus_root(project_root: Path, phase: str, config: dict[str, Any] | None = None) -> Path:
    config = config or load_config(project_root)
    return Path(project_root) / config["corpus_roots"][phase]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


# ---------------------------------------------------------------------------------------------
# WAV PCM16
# ---------------------------------------------------------------------------------------------

def read_wav(path: str | Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as wav:
        params = {"channels": wav.getnchannels(), "sample_width_bytes": wav.getsampwidth(), "sample_rate": wav.getframerate(),
                  "frames": wav.getnframes(), "compression": wav.getcomptype()}
        raw = wav.readframes(params["frames"])
    if params["sample_width_bytes"] != 2 or params["compression"] != "NONE":
        raise FormalAudioError(ERROR_CAPTURE_FORMAT, f"{path}: solo WAV PCM de 16 bits sin compresion.")
    samples = array("h")
    samples.frombytes(raw)
    return {**params, "samples": samples}


def write_wav(path: str | Path, samples: array, sample_rate: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples.tobytes())


def wav_format(path: str | Path) -> dict[str, Any]:
    data = read_wav(path)
    return {"container": "WAV", "encoding": "PCM_S16LE", "sample_rate": data["sample_rate"], "channels": data["channels"],
            "sample_width_bytes": data["sample_width_bytes"], "frames": data["frames"],
            "duration_seconds": round(data["frames"] / data["sample_rate"], 4) if data["sample_rate"] else 0.0}


def canonicalize(capture_path: Path, clean_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    """clean = copia byte a byte si la captura ya es canonica; si no, mezcla de canales determinista. Nunca remuestrea."""
    canonical = config["canonical_format"]
    data = read_wav(capture_path)
    if data["sample_rate"] != canonical["sample_rate"]:
        raise FormalAudioError(ERROR_CAPTURE_FORMAT, f"la captura es {data['sample_rate']} Hz; se exige {canonical['sample_rate']} Hz "
                                                     "(no se remuestrea para no introducir un procesamiento oculto).")
    if data["channels"] == canonical["channels"]:
        shutil.copyfile(capture_path, clean_path)
        return {"conversion": "NONE (copia byte a byte)"}
    channels = data["channels"]
    frames = data["frames"]
    mono = array("h", (int(round(sum(data["samples"][i * channels + c] for c in range(channels)) / channels)) for i in range(frames)))
    write_wav(clean_path, mono, data["sample_rate"])
    return {"conversion": f"DOWNMIX_{channels}_TO_1 (media redondeada)"}


# ---------------------------------------------------------------------------------------------
# Region activa y mezcla
# ---------------------------------------------------------------------------------------------

def _rms(values: Any) -> float:
    count = len(values)
    return math.sqrt(sum(float(v) * float(v) for v in values) / count) if count else 0.0


def active_region(samples: array, sample_rate: int, method: dict[str, Any]) -> tuple[int, int]:
    frame = int(sample_rate * method["frame_ms"] / 1000)
    frames = [samples[i:i + frame] for i in range(0, len(samples) - frame + 1, frame)]
    rms = [_rms(chunk) for chunk in frames]
    if not rms:
        raise FormalAudioError(ERROR_NO_SPEECH, "audio mas corto que una trama.")
    threshold = max(max(rms) * 10 ** (method["relative_threshold_db"] / 20.0), float(method["absolute_floor_rms"]))
    active = [index for index, value in enumerate(rms) if value >= threshold]
    if not active:
        raise FormalAudioError(ERROR_NO_SPEECH, "no se detecto voz activa.")
    return active[0] * frame, (active[-1] + 1) * frame


def noise_offset(case_id: str, variant_id: str, salt: str, master_length: int) -> int:
    digest = hashlib.sha256(f"{case_id}|{variant_id}|{salt}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % master_length


def mix_pair(clean_path: Path, master_path: Path, case_id: str, variant_id: str, out_path: Path,
             config: dict[str, Any]) -> dict[str, Any]:
    clean, master = read_wav(clean_path), read_wav(master_path)
    canonical = config["canonical_format"]
    for label, data in (("clean", clean), ("ruido", master)):
        if data["channels"] != 1 or data["sample_rate"] != canonical["sample_rate"]:
            raise FormalAudioError(ERROR_CAPTURE_FORMAT, f"{label}: se exige mono {canonical['sample_rate']} Hz.")
    c, m = clean["samples"], master["samples"]
    length, master_length = len(c), len(m)
    if not length or not master_length:
        raise FormalAudioError(ERROR_CAPTURE_FORMAT, "audio vacio.")
    start, end = active_region(c, clean["sample_rate"], config["active_speech_method"])
    offset = noise_offset(case_id, variant_id, config["noise_offset"]["salt"], master_length)
    segment = [m[(offset + i) % master_length] for i in range(length)]
    speech_rms = _rms(c[start:end])
    noise_rms = _rms(segment[start:end])
    if speech_rms <= 0 or noise_rms <= 0:
        raise FormalAudioError(ERROR_NO_SPEECH, "potencia nula en la region activa (voz o ruido).")
    target = float(config["target_snr_db"])
    gain = speech_rms / (noise_rms * 10 ** (target / 20.0))
    mixed = [cv + gain * nv for cv, nv in zip(c, segment)]
    limit = float(config["clipping"]["post_mix_peak_limit"])
    peak = max(abs(v) for v in mixed)
    post_gain = 1.0 if peak <= limit else limit / peak
    out = array("h")
    clipping = False
    for value in mixed:
        rounded = int(round(value * post_gain))
        if rounded > 32767 or rounded < -32768:
            clipping = True
            rounded = max(-32768, min(32767, rounded))
        out.append(rounded)
    if clipping:
        raise FormalAudioError(ERROR_CLIPPING, "la mezcla satura incluso con la ganancia global; estimulo abortado.")
    clean_scaled = [post_gain * c[i] for i in range(start, end)]
    residual = [out[i] - post_gain * c[i] for i in range(start, end)]
    measured = 20.0 * math.log10(_rms(clean_scaled) / _rms(residual))
    tolerance = float(config["snr_tolerance_db"])
    if abs(measured - target) > tolerance:
        raise FormalAudioError(ERROR_SNR_OUT_OF_TOLERANCE, f"SNR medido {measured:.3f} dB fuera de {target} +/- {tolerance} dB.")
    write_wav(out_path, out, clean["sample_rate"])
    return {
        "target_snr_db": target, "measured_snr_db": round(measured, 4), "snr_tolerance_db": tolerance,
        "speech_rms": round(speech_rms, 4), "noise_rms_before_scaling": round(noise_rms, 4), "noise_gain": gain,
        "post_mix_gain": post_gain, "peak_after_mix": max(abs(v) for v in out), "clipping_detected": False,
        "active_speech_method": config["active_speech_method"]["id"], "active_region_samples": [start, end],
        "noise_offset_samples": offset, "noise_offset_seconds": round(offset / clean["sample_rate"], 4),
        "noise_segment_length": length, "noise_looped": offset + length > master_length,
        "noise_master_length_samples": master_length, "mixing_algorithm_version": config["mixing_algorithm_version"],
    }


# ---------------------------------------------------------------------------------------------
# Ruido maestro
# ---------------------------------------------------------------------------------------------

def noise_master_status(project_root: Path, phase: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """FORMAL: solo el master aprobado (sha256 registrado en la configuracion). DEVELOPMENT: el master o el ruido dev."""
    config = config or load_config(project_root)
    master = config["noise_master"]
    path = Path(project_root) / master["path"]
    approved = bool(master.get("sha256"))
    if path.is_file() and approved:
        actual = sha256_file(path)
        if actual == master["sha256"]:
            return {"ready": True, "path": str(path), "sha256": actual, "source": "FORMAL_MASTER"}
        return {"ready": False, "path": str(path), "sha256": actual, "error": f"{ERROR_MASTER_NOT_READY}: hash distinto del aprobado."}
    if phase != "FORMAL":
        dev = (config.get("development_noise") or {}).get("path")
        if not dev:  # ruido de desarrollo elegido en la GUI (config local, nunca versionada ni valida para FORMAL)
            dev_config = Path(project_root) / "config" / "voice_protocol_dev.json"
            if dev_config.is_file():
                dev = json.loads(dev_config.read_text(encoding="utf-8")).get("noise_profile_path")
        if dev and (Path(project_root) / dev).is_file():
            dev_path = Path(project_root) / dev
            return {"ready": True, "path": str(dev_path), "sha256": sha256_file(dev_path), "source": "DEVELOPMENT_NOISE"}
    reason = "no existe el archivo" if not path.is_file() else "no esta aprobado (sha256 sin registrar)"
    return {"ready": False, "path": str(path), "sha256": None,
            "error": f"{ERROR_MASTER_NOT_READY}: {reason}: {master['path']}. Requisitos: {'; '.join(master['requirements'])}."}


def approve_noise_master(project_root: Path, approved_by: str, provenance: str, license_text: str,
                         speech_review: dict[str, Any] | None = None, source: dict[str, Any] | None = None,
                         conversion: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Aprobacion HUMANA del ruido maestro: valida formato/duracion, exige la revision humana de ausencia de voz inteligible
    (speech_review.no_intelligible_speech = CONFIRMED) y registra su SHA-256, procedencia y conversion en la configuracion.
    source.original_path/original_sha256: si se indican, el archivo original debe existir con ese hash.
    """
    if not str(approved_by or "").strip() or not str(provenance or "").strip():
        raise ValueError("approved_by y provenance son obligatorios.")
    speech_review = dict(speech_review or {})
    if speech_review.get("no_intelligible_speech") != "CONFIRMED" or not str(speech_review.get("reviewed_by") or "").strip():
        raise ValueError("Se exige revision humana: no_intelligible_speech = CONFIRMED y reviewed_by.")
    speech_review.setdefault("review_date", _now())
    project_root = Path(project_root)
    config = load_config(project_root)
    master = config["noise_master"]
    path = project_root / master["path"]
    if not path.is_file():
        raise FormalAudioError(ERROR_MASTER_NOT_READY, f"no existe {path}.")
    fmt = wav_format(path)
    canonical = config["canonical_format"]
    if fmt["channels"] != 1 or fmt["sample_rate"] != canonical["sample_rate"]:
        raise FormalAudioError(ERROR_CAPTURE_FORMAT, f"el master debe ser mono {canonical['sample_rate']} Hz (es {fmt}).")
    if fmt["duration_seconds"] < master["min_duration_seconds"]:
        raise FormalAudioError(ERROR_MASTER_NOT_READY, f"el master dura {fmt['duration_seconds']} s (< {master['min_duration_seconds']} s).")
    source = dict(source or {})
    if source.get("original_path"):
        original = project_root / source["original_path"]
        if not original.is_file():
            raise FormalAudioError(ERROR_MASTER_NOT_READY, f"no existe el original {original}.")
        actual = sha256_file(original)
        if source.get("original_sha256") and source["original_sha256"] != actual:
            raise FormalAudioError(ERROR_INTEGRITY, "el SHA-256 del original no coincide con el declarado.")
        source["original_sha256"] = actual
    samples = read_wav(path)["samples"]
    peak = max(abs(min(samples)), max(samples)) if len(samples) else 0
    master.update({"sha256": sha256_file(path), "approved_by": approved_by.strip(), "approved_at": _now(),
                   "provenance": provenance.strip(), "license": (license_text or "").strip() or None,
                   "format": fmt, "peak": peak, "full_scale_samples": sum(1 for v in samples if v in (32767, -32768)),
                   "speech_review": speech_review, "source": source or None, "conversion": conversion or None})
    _write_json(project_root / CONFIG_RELATIVE, config)
    return master


# ---------------------------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------------------------

def expected_cells(project_root: Path, phase: str = 'FORMAL') -> list[tuple[str, str]]:
    from trial_experiments import benchmark_catalog as BC
    from trial_experiments import text_batch as TB

    from trial_experiments import experimental_design as ED
    cases = (ED.formal_case_ids(project_root) if phase == 'FORMAL' and ED.design_path(project_root).is_file()
             else BC.CASE_IDS)
    return [(case_id, variant) for case_id in cases for variant in TB.VARIANT_ORDER]


def cell_dir(project_root: Path, phase: str, case_id: str, variant_id: str) -> Path:
    return corpus_root(project_root, phase) / case_id / variant_id


def load_corpus(project_root: Path, phase: str) -> dict[str, Any]:
    root = corpus_root(project_root, phase)
    path = root / CORPUS_MANIFEST
    if path.is_file():
        corpus = json.loads(path.read_text(encoding="utf-8"))
        config = load_config(project_root)
        expected = {f'{c}_{v}' for c, v in expected_cells(project_root, phase)}
        if phase == 'FORMAL' and (corpus.get('formal_freeze_id') != config['freeze_id']
                or corpus.get('phase') != phase or set(corpus.get('cells', {})) != expected):
            raise FormalAudioError('CORPUS_IDENTITY', 'El corpus pertenece a otra versión o alcance; se conserva sin modificar.')
        return corpus
    config = load_config(project_root)
    from trial_experiments import benchmark_catalog as BC

    return {"schema_version": 1, "formal_freeze_id": config["freeze_id"], "phase": phase,
            "benchmark_version": BC.load_catalog(project_root).get("benchmark_version"),
            "target_snr_db": config["target_snr_db"], "mixing_algorithm_version": config["mixing_algorithm_version"],
            "created_at": _now(),
            "cells": {f"{c}_{v}": {"case_id": c, "variant": v, "state": STATE_NOT_RECORDED, "uses": [], "attempts": []}
                      for c, v in expected_cells(project_root, phase)}}


def save_corpus(project_root: Path, phase: str, corpus: dict[str, Any]) -> None:
    corpus["updated_at"] = _now()
    _write_json(corpus_root(project_root, phase) / CORPUS_MANIFEST, corpus)


def cell_entry(corpus: dict[str, Any], case_id: str, variant_id: str) -> dict[str, Any]:
    return corpus["cells"][f"{case_id}_{variant_id}"]


def register_capture(project_root: Path, phase: str, case_id: str, variant_id: str, capture_path: Path,
                     speaker_id: str | None, capture_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Primera captura de una celda: congela capture_raw/clean y genera el par noisy ANTES de cualquier ASR. Nunca sobrescribe:
    una celda ya grabada exige rerecord_cell (decision humana) y una celda usada es inmutable.
    """
    project_root = Path(project_root)
    config = load_config(project_root)
    corpus = load_corpus(project_root, phase)
    entry = cell_entry(corpus, case_id, variant_id)
    if entry["state"] in USED_STATES:
        raise FormalAudioError(ERROR_CELL_IMMUTABLE, f"{case_id} {variant_id}: el clean ya se uso en un ensayo; nunca se regraba.")
    if entry["state"] != STATE_NOT_RECORDED:
        raise FormalAudioError(ERROR_CELL_EXISTS, f"{case_id} {variant_id}: ya grabada ({entry['state']}); use rerecord_cell con "
                                                  "decision humana explicita.")
    master = noise_master_status(project_root, phase, config)
    if not master["ready"]:
        raise FormalAudioError(ERROR_MASTER_NOT_READY, master["error"])
    directory = cell_dir(project_root, phase, case_id, variant_id)
    if any((directory / name).exists() for name in (RAW_FILENAME, CLEAN_FILENAME, NOISE_FILENAME, CELL_MANIFEST)):
        raise FormalAudioError(ERROR_CELL_EXISTS, f"{directory} ya contiene audio: nunca se sobrescribe.")
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        shutil.copyfile(capture_path, staging / RAW_FILENAME)
        conversion = canonicalize(staging / RAW_FILENAME, staging / CLEAN_FILENAME, config)
        mix = mix_pair(staging / CLEAN_FILENAME, Path(master["path"]), case_id, variant_id, staging / NOISE_FILENAME, config)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    for name in (RAW_FILENAME, CLEAN_FILENAME, NOISE_FILENAME):
        os.replace(staging / name, directory / name)
    staging.rmdir()
    from trial_experiments import benchmark_catalog as BC

    manifest = {
        "schema_version": 1, "formal_freeze_id": config["freeze_id"], "phase": phase,
        "benchmark_version": BC.load_catalog(project_root).get("benchmark_version"),
        "case_id": case_id, "variant": variant_id, "speaker_id": speaker_id,
        "reference_text": BC.get_case(project_root, case_id)["variants"][variant_id],
        "capture_timestamp": (capture_meta or {}).get("recorded_at") or _now(), "frozen_at": _now(),
        "raw_format": wav_format(directory / RAW_FILENAME), "clean_format": wav_format(directory / CLEAN_FILENAME),
        "clean_conversion": conversion["conversion"],
        "duration_seconds": wav_format(directory / CLEAN_FILENAME)["duration_seconds"],
        "capture_raw_sha256": sha256_file(directory / RAW_FILENAME),
        "clean_sha256": sha256_file(directory / CLEAN_FILENAME),
        "noisy_sha256": sha256_file(directory / NOISE_FILENAME),
        "noise_master_sha256": master["sha256"], "noise_source": master["source"],
        **mix,
        "paired_conditions": [CONDITION_CLEAN, CONDITION_NOISE],
        "audio_device": ((capture_meta or {}).get("device") or {}).get("name"),
    }
    _write_json(directory / CELL_MANIFEST, manifest)
    entry.update({"state": STATE_PAIR_READY, "clean_sha256": manifest["clean_sha256"], "noisy_sha256": manifest["noisy_sha256"],
                  "capture_raw_sha256": manifest["capture_raw_sha256"], "audio_manifest_sha256": sha256_file(directory / CELL_MANIFEST),
                  "measured_snr_db": manifest["measured_snr_db"], "recorded_at": manifest["frozen_at"]})
    save_corpus(project_root, phase, corpus)
    return manifest


def rerecord_cell(project_root: Path, phase: str, case_id: str, variant_id: str, decided_by: str, reason: str) -> dict[str, Any]:
    """Decision humana explicita ANTES de usar la celda: archiva el intento anterior (nunca se borra) y la deja NOT_RECORDED."""
    if not str(decided_by or "").strip() or not str(reason or "").strip():
        raise ValueError("decided_by y reason son obligatorios.")
    corpus = load_corpus(project_root, phase)
    entry = cell_entry(corpus, case_id, variant_id)
    if entry["state"] in USED_STATES:
        raise FormalAudioError(ERROR_CELL_IMMUTABLE, f"{case_id} {variant_id}: ya usada en un ensayo; inmutable.")
    if entry["state"] == STATE_NOT_RECORDED:
        return entry
    directory = cell_dir(project_root, phase, case_id, variant_id)
    attempt = directory / ATTEMPTS_DIRNAME / f"attempt_{len(entry['attempts']) + 1:03d}"
    attempt.mkdir(parents=True)
    for name in (RAW_FILENAME, CLEAN_FILENAME, NOISE_FILENAME, CELL_MANIFEST):
        if (directory / name).exists():
            os.replace(directory / name, attempt / name)
    entry["attempts"].append({"archived_to": str(attempt.relative_to(corpus_root(project_root, phase))), "decided_by": decided_by.strip(),
                              "reason": reason.strip(), "at": _now(), "previous_clean_sha256": entry.get("clean_sha256")})
    for key in ("clean_sha256", "noisy_sha256", "capture_raw_sha256", "audio_manifest_sha256", "measured_snr_db", "recorded_at"):
        entry.pop(key, None)
    entry["state"] = STATE_NOT_RECORDED
    save_corpus(project_root, phase, corpus)
    return entry


def verify_cell(project_root: Path, phase: str, case_id: str, variant_id: str, regenerate: bool = True) -> dict[str, Any]:
    """Integridad READ-ONLY: hashes de archivos/manifiesto, master, SNR, clipping y (opcional) regeneracion byte a byte."""
    project_root = Path(project_root)
    config = load_config(project_root)
    corpus = load_corpus(project_root, phase)
    entry = cell_entry(corpus, case_id, variant_id)
    directory = cell_dir(project_root, phase, case_id, variant_id)
    errors: list[str] = []
    if entry["state"] == STATE_NOT_RECORDED:
        return {"ok": False, "errors": [f"{ERROR_PAIR_MISSING}: {case_id} {variant_id} sin grabar."], "entry": entry, "manifest": None}
    manifest_path = directory / CELL_MANIFEST
    if not manifest_path.is_file():
        return {"ok": False, "errors": [f"{ERROR_INTEGRITY}: falta {CELL_MANIFEST}."], "entry": entry, "manifest": None}
    if sha256_file(manifest_path) != entry.get("audio_manifest_sha256"):
        errors.append(f"{ERROR_INTEGRITY}: {CELL_MANIFEST} modificado.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, key in ((RAW_FILENAME, "capture_raw_sha256"), (CLEAN_FILENAME, "clean_sha256"), (NOISE_FILENAME, "noisy_sha256")):
        path = directory / name
        if not path.is_file():
            errors.append(f"{ERROR_INTEGRITY}: falta {name}.")
        elif sha256_file(path) != manifest.get(key) or manifest.get(key) != entry.get(key):
            errors.append(f"{ERROR_INTEGRITY}: {name} no coincide con el manifiesto.")
    from trial_experiments import benchmark_catalog as BC

    if manifest.get("benchmark_version") != BC.load_catalog(project_root).get("benchmark_version"):
        errors.append(f"{ERROR_INTEGRITY}: benchmark distinto.")
    if manifest.get("formal_freeze_id") != config["freeze_id"] or manifest.get("variant") != variant_id or manifest.get("case_id") != case_id:
        errors.append(f"{ERROR_INTEGRITY}: celda/freeze del manifiesto no coinciden.")
    if manifest.get("target_snr_db") != config["target_snr_db"] or \
            abs(float(manifest.get("measured_snr_db", 1e9)) - config["target_snr_db"]) > config["snr_tolerance_db"]:
        errors.append(f"{ERROR_SNR_OUT_OF_TOLERANCE}: SNR del par fuera de lo congelado.")
    if manifest.get("clipping_detected"):
        errors.append(f"{ERROR_CLIPPING}: el par registra clipping.")
    master = noise_master_status(project_root, phase, config)
    if not master["ready"] or master["sha256"] != manifest.get("noise_master_sha256"):
        errors.append(f"{ERROR_MASTER_NOT_READY}: el ruido maestro no coincide con el usado en el par.")
    if regenerate and not errors:
        scratch = directory / "_verify_noise.wav"
        try:
            mix_pair(directory / CLEAN_FILENAME, Path(master["path"]), case_id, variant_id, scratch, config)
            if sha256_file(scratch) != manifest.get("noisy_sha256"):
                errors.append(f"{ERROR_INTEGRITY}: el par noisy no es reproducible byte a byte.")
        finally:
            scratch.unlink(missing_ok=True)
    return {"ok": not errors, "errors": errors, "entry": entry, "manifest": manifest}


def stimulus(project_root: Path, phase: str, case_id: str, variant_id: str, condition: str) -> dict[str, Any]:
    """Estimulo congelado e integro para un ensayo (VOICE_CLEAN -> clean, VOICE_NOISE -> noisy del MISMO clean)."""
    check = verify_cell(project_root, phase, case_id, variant_id)
    if not check["ok"]:
        code = ERROR_PAIR_MISSING if check["entry"]["state"] == STATE_NOT_RECORDED else ERROR_INTEGRITY
        raise FormalAudioError(code, "; ".join(check["errors"]))
    if condition == CONDITION_NOISE and check["entry"]["state"] not in USED_STATES and phase == "FORMAL":
        raise FormalAudioError(ERROR_PAIR_MISSING, f"{case_id} {variant_id}: el clean aun no se uso en VOICE_CLEAN FORMAL.")
    directory = cell_dir(project_root, phase, case_id, variant_id)
    manifest = check["manifest"]
    path = directory / (CLEAN_FILENAME if condition == CONDITION_CLEAN else NOISE_FILENAME)
    return {
        "condition": condition, "case_id": case_id, "variant": variant_id, "path": str(path),
        "audio_sha256": manifest["clean_sha256"] if condition == CONDITION_CLEAN else manifest["noisy_sha256"],
        "paired_audio_sha256": manifest["noisy_sha256"] if condition == CONDITION_CLEAN else manifest["clean_sha256"],
        "audio_source_clean_sha256": manifest["clean_sha256"],
        "audio_manifest_path": str(directory / CELL_MANIFEST), "audio_manifest_sha256": check["entry"]["audio_manifest_sha256"],
        "target_snr_db": manifest["target_snr_db"], "measured_snr_db": manifest["measured_snr_db"],
        "noise_master_sha256": manifest["noise_master_sha256"], "speaker_id": manifest.get("speaker_id"),
        "formal_freeze_id": manifest["formal_freeze_id"], "benchmark_version": manifest["benchmark_version"],
        "clean_uses": [use for use in check["entry"]["uses"] if use["condition"] == CONDITION_CLEAN],
    }


def mark_used(project_root: Path, phase: str, case_id: str, variant_id: str, condition: str, trial_id: str) -> dict[str, Any]:
    """El estimulo entro a un ensayo (antes del ASR): desde aqui la pareja es INMUTABLE."""
    corpus = load_corpus(project_root, phase)
    entry = cell_entry(corpus, case_id, variant_id)
    if entry["state"] == STATE_NOT_RECORDED:
        raise FormalAudioError(ERROR_PAIR_MISSING, f"{case_id} {variant_id}: sin grabar.")
    entry["uses"].append({"condition": condition, "trial_id": trial_id, "at": _now()})
    used = {use["condition"] for use in entry["uses"]}
    entry["state"] = STATE_USED_BOTH if {CONDITION_CLEAN, CONDITION_NOISE} <= used else (
        STATE_USED_CLEAN if CONDITION_CLEAN in used else entry["state"])
    save_corpus(project_root, phase, corpus)
    return entry


def corpus_summary(project_root: Path, phase: str) -> dict[str, Any]:
    corpus = load_corpus(project_root, phase)
    cells = corpus["cells"].values()
    recorded = sum(1 for c in cells if c["state"] != STATE_NOT_RECORDED)
    pairs = sum(1 for c in cells if c["state"] in (STATE_PAIR_READY, *USED_STATES))
    clean_done = sum(1 for c in cells if any(u["condition"] == CONDITION_CLEAN for u in c["uses"]))
    noise_done = sum(1 for c in cells if any(u["condition"] == CONDITION_NOISE for u in c["uses"]))
    return {"total": len(corpus["cells"]), "recorded_clean": recorded, "noise_pairs_ready": pairs,
            "clean_trials": clean_done, "noise_trials": noise_done}


def noise_batch_preflight(project_root: Path, phase: str, cells: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """
    VOICE_NOISE exige todas las parejas de la campaña íntegras y con clean ya usado.
    cells limita la comprobacion solo en DEVELOPMENT; FORMAL exige la campaña completa.
    """
    cells = list(cells) if cells is not None and phase != "FORMAL" else expected_cells(project_root, phase)
    missing: list[str] = []
    errors: list[str] = []
    master = noise_master_status(project_root, phase)
    if not master["ready"]:
        errors.append(master["error"])
    ready = 0
    for case_id, variant in cells:
        check = verify_cell(project_root, phase, case_id, variant, regenerate=False)
        # Mismo criterio que stimulus(): en FORMAL el clean debe haberse usado ya en VOICE_CLEAN FORMAL.
        clean_used = any(use["condition"] == CONDITION_CLEAN for use in check["entry"]["uses"]) or phase != "FORMAL"
        if check["ok"] and clean_used:
            ready += 1
        else:
            missing.append(f"{case_id} {variant}: " + ("; ".join(check["errors"]) or "clean aun no usado en VOICE_CLEAN"))
    return {"ok": not errors and not missing, "pairs_ready": ready, "total": len(cells),
            "missing": missing, "errors": errors}


__all__ = ["register_capture", "rerecord_cell", "verify_cell", "stimulus", "mark_used", "mix_pair", "noise_offset",
           "noise_master_status", "approve_noise_master", "corpus_summary", "noise_batch_preflight", "load_corpus",
           "FormalAudioError", "CELL_STATES"]
