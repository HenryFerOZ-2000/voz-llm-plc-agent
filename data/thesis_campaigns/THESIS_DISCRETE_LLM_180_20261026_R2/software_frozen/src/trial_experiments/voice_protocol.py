"""
Protocolo de voz del experimento (Fase 4A-FINAL-TRIAL-FLOW).

  TEXT         -> el texto EXACTO de la variante (benchmark v2) entra al pipeline.
  VOICE_CLEAN  -> se graba al hablante leyendo la frase de referencia; el WAV RAW se guarda ANTES
                  del ASR; la transcripcion del ASR se congela (sin correccion humana) y entra al
                  MISMO pipeline que TEXT.
  VOICE_NOISE  -> diseno PAREADO: se reutiliza el clean_audio.wav del ensayo VOICE_CLEAN del mismo
                  case/variant y se le suma un perfil de ruido congelado a un SNR definido en
                  experimental_design.json, con una mezcla determinista. Solo cambia el ruido.

Todo es Python puro (wave/array/math): sin dependencias numericas, mezcla reproducible.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import time
import unicodedata
import wave
from array import array
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

AUDIO_DIRNAME = "audio"
REFERENCE_FILENAME = "reference.txt"
CLEAN_AUDIO_FILENAME = "clean_audio.wav"
NOISE_REFERENCE_FILENAME = "noise_profile_reference.json"
NOISE_AUDIO_FILENAME = "voice_noise.wav"
ASR_RESULT_FILENAME = "asr_result.json"
AUDIO_ARTIFACTS = tuple(f"{AUDIO_DIRNAME}/{name}" for name in (
    REFERENCE_FILENAME, CLEAN_AUDIO_FILENAME, NOISE_REFERENCE_FILENAME, NOISE_AUDIO_FILENAME, ASR_RESULT_FILENAME))

ERROR_AUDIO_CAPTURE_INVALID = "AUDIO_CAPTURE_INVALID"
ERROR_CLEAN_AUDIO_REQUIRED = "CLEAN_AUDIO_REQUIRED"
ERROR_NOISE_NOT_CONFIGURED = "NOISE_PROFILE_NOT_CONFIGURED"
ERROR_NOISE_NOT_FROZEN = "NOISE_PROTOCOL_NOT_FROZEN"
ERROR_NOISE_PROFILE_INVALID = "NOISE_PROFILE_INVALID"
ERROR_ASR_UNAVAILABLE = "ASR_SERVICE_UNAVAILABLE"
ERROR_ASR_EMPTY = "ASR_EMPTY_TRANSCRIPT"
ERROR_SPEAKER_ID = "SPEAKER_ID_NOT_PSEUDONYMOUS"

STAGE_AUDIO_CAPTURE = "audio_capture"
STAGE_ASR = "asr"
STAGE_NOISE_MIX = "noise_mix"

NOISE_OFFSET_RULE = "ZERO_OFFSET_CYCLIC"
DEV_CONFIG_RELATIVE = Path("config") / "voice_protocol_dev.json"
SPEAKER_PATTERN = re.compile(r"^S\d{2,3}$")

DEFAULT_CAPTURE = {"format": "WAV_PCM16", "sample_rate": 16000, "channels": 1, "sample_width_bytes": 2,
                   "min_duration_ms": 300, "min_peak": 100, "min_rms": 20}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def protocol(project_root: Path) -> dict[str, Any]:
    from trial_experiments import experimental_design as ED

    return ED.load_design(project_root).get("voice_protocol") or {}


def capture_settings(project_root: Path) -> dict[str, Any]:
    return {**DEFAULT_CAPTURE, **(protocol(project_root).get("capture") or {})}


def validate_speaker_id(speaker_id: str | None) -> str | None:
    """Pseudonimo obligatorio para voz (S01, S02, ...): nunca datos personales."""
    if speaker_id and SPEAKER_PATTERN.match(speaker_id.strip()):
        return None
    return f"{ERROR_SPEAKER_ID}: use un pseudonimo S01, S02, ... (recibido {speaker_id!r})."


# ---------------------------------------------------------------------------------------------
# WER (normalizacion documentada, identica para todos los ensayos)
# ---------------------------------------------------------------------------------------------

WER_NORMALIZATION = (
    "1. Unicode NFC",
    "2. minusculas (casefold)",
    "3. todo caracter que no sea letra o digito (puntuacion, guiones, comillas) se sustituye por espacio",
    "4. espacios multiples -> uno; sin espacios al inicio/fin",
    "Sin quitar tildes, sin convertir numeros a palabras ni viceversa, sin correcciones semanticas.",
)


def normalize_for_wer(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").casefold()
    text = "".join(ch if (ch.isalnum()) else " " for ch in text)
    return " ".join(text.split())


def word_alignment(reference: list[str], hypothesis: list[str]) -> dict[str, int]:
    """Levenshtein por palabras con conteo S/D/I (desempate fijo: acierto/sustitucion, eliminacion, insercion)."""
    rows, cols = len(reference) + 1, len(hypothesis) + 1
    cost = [[0] * cols for _ in range(rows)]
    for i in range(1, rows):
        cost[i][0] = i
    for j in range(1, cols):
        cost[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            diagonal = cost[i - 1][j - 1] + (0 if reference[i - 1] == hypothesis[j - 1] else 1)
            cost[i][j] = min(diagonal, cost[i - 1][j] + 1, cost[i][j - 1] + 1)
    i, j = len(reference), len(hypothesis)
    substitutions = deletions = insertions = hits = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and cost[i][j] == cost[i - 1][j - 1] + (0 if reference[i - 1] == hypothesis[j - 1] else 1):
            if reference[i - 1] == hypothesis[j - 1]:
                hits += 1
            else:
                substitutions += 1
            i, j = i - 1, j - 1
        elif i > 0 and cost[i][j] == cost[i - 1][j] + 1:
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1
    return {"substitutions": substitutions, "deletions": deletions, "insertions": insertions, "hits": hits}


def wer_metrics(reference_text: str, transcript: str) -> dict[str, Any]:
    reference_norm, transcript_norm = normalize_for_wer(reference_text), normalize_for_wer(transcript)
    reference_words, transcript_words = reference_norm.split(), transcript_norm.split()
    counts = word_alignment(reference_words, transcript_words)
    errors = counts["substitutions"] + counts["deletions"] + counts["insertions"]
    return {
        "reference_word_count": len(reference_words),
        **{key: counts[key] for key in ("substitutions", "deletions", "insertions")},
        "wer": round(errors / len(reference_words), 6) if reference_words else None,
        "exact_transcript_match": (transcript or "").strip() == (reference_text or "").strip(),
        "normalized_transcript_match": reference_norm == transcript_norm,
        "reference_normalized": reference_norm,
        "asr_transcript_normalized": transcript_norm,
        "normalization_version": 1,
    }


# ---------------------------------------------------------------------------------------------
# Audio: lectura/analisis/validacion tecnica de la captura
# ---------------------------------------------------------------------------------------------

def read_pcm16(path: str | Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as wav:
        params = {"channels": wav.getnchannels(), "sample_width_bytes": wav.getsampwidth(), "sample_rate": wav.getframerate(),
                  "frames": wav.getnframes()}
        raw = wav.readframes(params["frames"])
    if params["sample_width_bytes"] != 2:
        raise ValueError(f"Solo se admite PCM de 16 bits (archivo con {params['sample_width_bytes'] * 8} bits).")
    samples = array("h")
    samples.frombytes(raw)
    return {**params, "samples": samples}


def write_pcm16(path: str | Path, samples: array, sample_rate: int, channels: int = 1) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples.tobytes())


def analyze_audio(path: str | Path) -> dict[str, Any]:
    data = read_pcm16(path)
    samples = data["samples"]
    count = len(samples)
    peak = max((abs(value) for value in samples), default=0)
    rms = math.sqrt(sum(value * value for value in samples) / count) if count else 0.0
    rate, channels = data["sample_rate"], data["channels"]
    duration_ms = int(round(1000 * count / (rate * channels))) if rate and channels else 0
    return {"sample_rate": rate, "channels": channels, "sample_width_bytes": data["sample_width_bytes"], "samples": count,
            "duration_ms": duration_ms, "peak": peak, "rms": round(rms, 3),
            "clipped_samples": sum(1 for value in samples if value in (32767, -32768))}


def validate_capture(path: str | Path | None, settings: dict[str, Any], device: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Validez TECNICA de la grabacion (no de la pronunciacion): existe, es WAV PCM16 legible, dura un
    minimo razonable y contiene senal. Umbrales permisivos documentados en experimental_design.json.
    """
    errors: list[str] = []
    analysis: dict[str, Any] = {}
    if device is not None and not device.get("available", True):
        errors.append(f"dispositivo de entrada no disponible: {device.get('error')}")
    if not path or not Path(path).is_file() or Path(path).stat().st_size == 0:
        errors.append("el archivo de audio no existe o esta vacio")
    else:
        try:
            analysis = analyze_audio(path)
        except (wave.Error, EOFError, ValueError) as error:
            errors.append(f"archivo de audio corrupto o no soportado: {error}")
        else:
            if analysis["duration_ms"] < settings["min_duration_ms"]:
                errors.append(f"duracion {analysis['duration_ms']} ms < {settings['min_duration_ms']} ms")
            if analysis["peak"] < settings["min_peak"] or analysis["rms"] < settings["min_rms"]:
                errors.append(f"sin senal util (pico {analysis['peak']}, RMS {analysis['rms']})")
            if analysis["channels"] != settings["channels"] or analysis["sample_rate"] != settings["sample_rate"]:
                errors.append(f"formato {analysis['sample_rate']} Hz/{analysis['channels']} canal(es) distinto del protocolo")
    return {"valid": not errors, "errors": [f"{ERROR_AUDIO_CAPTURE_INVALID}: {e}" for e in errors], "analysis": analysis}


# ---------------------------------------------------------------------------------------------
# Ruido controlado: configuracion y mezcla determinista
# ---------------------------------------------------------------------------------------------

def dev_config_path(project_root: Path) -> Path:
    return Path(project_root) / DEV_CONFIG_RELATIVE


def load_dev_config(project_root: Path) -> dict[str, Any]:
    path = dev_config_path(project_root)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_dev_config(project_root: Path, noise_profile_path: str | None, snr_db: float | None) -> dict[str, Any]:
    config = {"noise_profile_path": noise_profile_path, "snr_db": snr_db, "updated_at": _now(),
              "note": "Solo DEVELOPMENT. FORMAL usa exclusivamente experimental_design.json -> voice_protocol.noise."}
    path = dev_config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return config


def resolve_noise_config(project_root: Path, phase: str) -> dict[str, Any]:
    """
    FORMAL: solo voice_protocol.noise de experimental_design.json, con status FROZEN y hash verificado.
    DEVELOPMENT: config de desarrollo (perfil + SNR elegidos en la GUI) o, si no hay, la del diseno.
    El SNR nunca se fija en el codigo.
    """
    from trial_experiments import trial_model

    design_noise = protocol(project_root).get("noise") or {}
    if phase == trial_model.PHASE_FORMAL:
        if design_noise.get("status") != "FROZEN":
            return {"ok": False, "errors": [f"{ERROR_NOISE_NOT_FROZEN}: congele voice_protocol.noise en experimental_design.json."]}
        source, profile_path, snr_db = "experimental_design", design_noise.get("profile_path"), design_noise.get("snr_db")
        expected_hash = design_noise.get("profile_sha256")
    else:
        dev = load_dev_config(project_root)
        if dev.get("noise_profile_path") and dev.get("snr_db") is not None:
            source, profile_path, snr_db, expected_hash = "development_config", dev["noise_profile_path"], dev["snr_db"], None
        else:
            source, profile_path, snr_db = "experimental_design", design_noise.get("profile_path"), design_noise.get("snr_db")
            expected_hash = design_noise.get("profile_sha256")
    if not profile_path or snr_db is None:
        return {"ok": False, "errors": [f"{ERROR_NOISE_NOT_CONFIGURED}: seleccione un perfil de ruido WAV y un SNR (dB)."]}
    path = Path(profile_path)
    if not path.is_absolute():
        path = Path(project_root) / path
    if not path.is_file():
        return {"ok": False, "errors": [f"{ERROR_NOISE_PROFILE_INVALID}: no existe {path}."]}
    profile_hash = sha256_file(path)
    if expected_hash and expected_hash != profile_hash:
        return {"ok": False, "errors": [f"{ERROR_NOISE_PROFILE_INVALID}: el hash del perfil no coincide con el congelado."]}
    return {"ok": True, "errors": [], "source": source, "noise_profile_id": path.stem, "noise_profile_path": str(path),
            "noise_profile_hash": profile_hash, "snr_db": float(snr_db), "noise_offset_rule": NOISE_OFFSET_RULE}


def mix_at_snr(clean_path: str | Path, noise_path: str | Path, snr_db: float, out_path: str | Path) -> dict[str, Any]:
    """
    Mezcla determinista: ruido desde el desplazamiento 0, repetido ciclicamente si es mas corto;
    ganancia g = sqrt(Pc / (Pn * 10^(SNR/10))) con Pc/Pn = potencia media de toda la senal limpia y
    del segmento de ruido usado; y = round(clean + g*ruido) saturado a int16. Mismo clean + ruido +
    SNR -> mismo archivo bit a bit (aritmetica IEEE-754 de Python, redondeo half-even).
    """
    clean, noise = read_pcm16(clean_path), read_pcm16(noise_path)
    if clean["channels"] != 1 or noise["channels"] != 1:
        raise ValueError(f"{ERROR_NOISE_PROFILE_INVALID}: la mezcla requiere audio mono.")
    if clean["sample_rate"] != noise["sample_rate"]:
        raise ValueError(f"{ERROR_NOISE_PROFILE_INVALID}: el perfil de ruido es {noise['sample_rate']} Hz y la voz "
                         f"{clean['sample_rate']} Hz (no se remuestrea).")
    c, n = clean["samples"], noise["samples"]
    if not c or not n:
        raise ValueError(f"{ERROR_NOISE_PROFILE_INVALID}: audio vacio.")
    segment = [n[i % len(n)] for i in range(len(c))]
    clean_power = sum(v * v for v in c) / len(c)
    noise_power = sum(v * v for v in segment) / len(segment)
    if clean_power <= 0 or noise_power <= 0:
        raise ValueError(f"{ERROR_NOISE_PROFILE_INVALID}: potencia nula (voz o ruido en silencio).")
    gain = math.sqrt(clean_power / (noise_power * (10.0 ** (float(snr_db) / 10.0))))
    mixed = array("h")
    clipped = 0
    for clean_value, noise_value in zip(c, segment):
        value = int(round(clean_value + gain * noise_value))
        if value > 32767 or value < -32768:
            clipped += 1
            value = max(-32768, min(32767, value))
        mixed.append(value)
    write_pcm16(out_path, mixed, clean["sample_rate"], 1)
    return {"snr_db": float(snr_db), "noise_gain": gain, "noise_offset_ms": 0, "noise_offset_rule": NOISE_OFFSET_RULE,
            "noise_looped": len(n) < len(c), "clipped_samples": clipped, "clean_power": clean_power, "noise_power": noise_power,
            "mixed_audio_hash": sha256_file(out_path)}


# ---------------------------------------------------------------------------------------------
# Emparejamiento CLEAN / NOISE
# ---------------------------------------------------------------------------------------------

def find_paired_clean(project_root: Path, case_id: str, variant_id: str, phase: str) -> dict[str, Any] | None:
    """
    Ensayo VOICE_CLEAN del mismo case/variant con audio clean VALIDO e integro. FORMAL solo acepta
    un VOICE_CLEAN FORMAL; DEVELOPMENT acepta ensayos de desarrollo. El mas reciente gana.
    """
    from trial_experiments import trial_model

    phases = (trial_model.PHASE_FORMAL,) if phase == trial_model.PHASE_FORMAL else (
        trial_model.PHASE_DEVELOPMENT, trial_model.PHASE_BASELINE)
    candidates = []
    for candidate_phase in phases:
        base = trial_model.get_phase_results_dir(project_root, candidate_phase) / case_id / variant_id
        if not base.exists():
            continue
        for trial_json in base.glob("*/trial.json"):
            record = json.loads(trial_json.read_text(encoding="utf-8"))
            voice = record.get("voice") or {}
            audio = trial_json.parent / AUDIO_DIRNAME / CLEAN_AUDIO_FILENAME
            if (record.get("input_mode") != "VOICE_CLEAN" or not voice.get("audio_capture_success")
                    or not audio.is_file() or sha256_file(audio) != voice.get("clean_audio_hash")):
                continue
            candidates.append({"trial_id": record.get("trial_id"), "trial_dir": str(trial_json.parent), "audio_path": str(audio),
                               "audio_hash": voice["clean_audio_hash"], "speaker_id": record.get("speaker_id"),
                               "created_at": record.get("created_at") or "", "trial_kind": record.get("trial_kind")})
    return sorted(candidates, key=lambda c: (c["created_at"], c["trial_id"]))[-1] if candidates else None


# ---------------------------------------------------------------------------------------------
# Orquestacion de la entrada de voz de un ensayo ya creado
# ---------------------------------------------------------------------------------------------

def _prepare_paired_stimulus(project_root: Path, trial_dir: Path, input_mode: str, reference_text: str,
                             asr_fn: Callable[[Path], dict[str, Any]], stimulus: dict[str, Any]) -> dict[str, Any]:
    from trial_experiments import formal_audio

    audio_dir = trial_dir / AUDIO_DIRNAME
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / REFERENCE_FILENAME).write_text(reference_text, encoding="utf-8")
    voice: dict[str, Any] = {"protocol_version": 2, "reference_text": reference_text, "reference_text_hash": sha256_text(reference_text),
                             "transcript_review": "NONE", "clean_source": "PAIRED_AUDIO_CORPUS",
                             "audio_condition": input_mode, "audio_source_path": stimulus["path"],
                             "audio_sha256": stimulus["audio_sha256"], "paired_audio_sha256": stimulus["paired_audio_sha256"],
                             "audio_source_clean_sha256": stimulus["audio_source_clean_sha256"],
                             "audio_manifest_sha256": stimulus["audio_manifest_sha256"], "audio_manifest_path": stimulus["audio_manifest_path"],
                             "target_snr_db": stimulus["target_snr_db"], "measured_snr_db": stimulus["measured_snr_db"],
                             "noise_master_sha256": stimulus["noise_master_sha256"], "formal_freeze_id": stimulus["formal_freeze_id"],
                             "audio_speaker_id": stimulus.get("speaker_id"),
                             "paired_clean_trial_id": (stimulus.get("clean_uses") or [{}])[0].get("trial_id")}
    if input_mode != stimulus["condition"]:
        return _asr_failure(voice, STAGE_AUDIO_CAPTURE, formal_audio.ERROR_INTEGRITY, "el estimulo no corresponde a la modalidad", True)
    corpus_dir = Path(stimulus["path"]).parent
    clean_target = audio_dir / CLEAN_AUDIO_FILENAME
    shutil.copyfile(corpus_dir / formal_audio.CLEAN_FILENAME, clean_target)
    if sha256_file(clean_target) != stimulus["audio_source_clean_sha256"]:
        return _asr_failure(voice, STAGE_AUDIO_CAPTURE, formal_audio.ERROR_INTEGRITY, "la copia del clean no es identica", True)
    asr_audio = clean_target
    if input_mode == "VOICE_NOISE":
        asr_audio = audio_dir / NOISE_AUDIO_FILENAME
        shutil.copyfile(stimulus["path"], asr_audio)
        if sha256_file(asr_audio) != stimulus["audio_sha256"]:
            return _asr_failure(voice, STAGE_NOISE_MIX, formal_audio.ERROR_INTEGRITY, "la copia del noisy no es identica", True)
        voice.update({"snr_db": stimulus["target_snr_db"], "mixed_audio_hash": stimulus["audio_sha256"]})
    check = validate_capture(clean_target, capture_settings(project_root))
    voice.update({"clean_audio_hash": sha256_file(clean_target), "audio_capture_success": check["valid"],
                  "duration_ms": check["analysis"].get("duration_ms"), "sample_rate": check["analysis"].get("sample_rate"),
                  "channels": check["analysis"].get("channels"), "audio_peak": check["analysis"].get("peak"),
                  "audio_rms": check["analysis"].get("rms")})
    if not check["valid"]:
        return _asr_failure(voice, STAGE_AUDIO_CAPTURE, ERROR_AUDIO_CAPTURE_INVALID, "; ".join(check["errors"]), True)
    # El estimulo entra al ensayo: a partir de aqui la pareja es inmutable (un reintento reutiliza el MISMO WAV).
    formal_audio.mark_used(project_root, stimulus["phase"], stimulus["case_id"], stimulus["variant"], input_mode, trial_dir.name)
    return _run_asr(audio_dir, asr_audio, reference_text, asr_fn, voice)


def _run_asr(audio_dir: Path, asr_audio: Path, reference_text: str, asr_fn: Callable[[Path], dict[str, Any]],
             voice: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = asr_fn(asr_audio)
    except Exception as error:  # red/API/configuracion: infraestructura
        voice.update({"asr_success": False, "asr_latency_ms": int(round((time.perf_counter() - started) * 1000))})
        return _asr_failure(voice, STAGE_ASR, ERROR_ASR_UNAVAILABLE, str(error), True)
    latency = int(round((time.perf_counter() - started) * 1000))
    transcript = str(result.get("transcript") or "").strip()
    asr_record = {"audio_file": asr_audio.name, "audio_hash": sha256_file(asr_audio), "transcript_raw": transcript,
                  "model": result.get("model"), "language": result.get("language"), "error": result.get("error"),
                  "latency_ms": latency, "frozen_at": _now()}
    (audio_dir / ASR_RESULT_FILENAME).write_text(json.dumps(asr_record, indent=2, ensure_ascii=False), encoding="utf-8")
    metrics = wer_metrics(reference_text, transcript)
    voice.update({"asr_audio": asr_audio.name, "asr_audio_sha256": asr_record["audio_hash"], "asr_success": bool(transcript),
                  "asr_model": result.get("model"), "asr_language": result.get("language"), "asr_latency_ms": latency,
                  "asr_transcript_raw": transcript, "asr_transcript_normalized": metrics["asr_transcript_normalized"],
                  **{k: metrics[k] for k in ("reference_word_count", "substitutions", "deletions", "insertions", "wer",
                                             "exact_transcript_match", "normalized_transcript_match")}})
    if result.get("error") and "configur" in str(result.get("error")).lower():
        return _asr_failure(voice, STAGE_ASR, ERROR_ASR_UNAVAILABLE, str(result["error"]), True)
    if not transcript:
        return _asr_failure(voice, STAGE_ASR, ERROR_ASR_EMPTY, "el ASR no devolvio texto", False)
    return {"ok": True, "voice": voice, "effective_input_text": transcript, "failure": None}


def _asr_failure(voice: dict[str, Any], stage: str, code: str, detail: str, infrastructure: bool) -> dict[str, Any]:
    return {"ok": False, "voice": voice, "effective_input_text": None,
            "failure": {"stage": stage, "code": code, "error": f"{code}: {detail}", "infrastructure": infrastructure}}


def prepare_voice_input(
    project_root: Path,
    trial_dir: Path,
    input_mode: str,
    reference_text: str,
    asr_fn: Callable[[Path], dict[str, Any]],
    capture: dict[str, Any] | None = None,
    paired: dict[str, Any] | None = None,
    noise: dict[str, Any] | None = None,
    stimulus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Congela la entrada de voz del ensayo y devuelve el texto efectivo para el pipeline.
      capture: {"path", "device", "sample_rate", "channels", "recorded_at"} (grabacion nueva)
      paired:  ensayo VOICE_CLEAN emparejado (VOICE_NOISE)
      noise:   resolve_noise_config(...) (VOICE_NOISE)
    El WAV RAW queda en audio/ ANTES del ASR. La transcripcion no se corrige ni se confirma.
      stimulus: estimulo PAREADO del corpus (formal_audio.stimulus + "phase"): el ASR recibe EXACTAMENTE el WAV congelado
                de la celda (clean para VOICE_CLEAN, noisy del MISMO clean para VOICE_NOISE); nunca se graba ni se mezcla
                aqui. Se marca usado ANTES del ASR: desde ese momento la pareja es inmutable.
    """
    if stimulus is not None:
        return _prepare_paired_stimulus(project_root, Path(trial_dir), input_mode, reference_text, asr_fn, stimulus)
    audio_dir = Path(trial_dir) / AUDIO_DIRNAME
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / REFERENCE_FILENAME).write_text(reference_text, encoding="utf-8")
    voice: dict[str, Any] = {"protocol_version": 1, "reference_text": reference_text, "reference_text_hash": sha256_text(reference_text),
                             "transcript_review": "NONE"}
    settings = capture_settings(project_root)
    clean_target = audio_dir / CLEAN_AUDIO_FILENAME

    # 1) Audio base (RAW, antes del ASR)
    if paired is not None:
        shutil.copyfile(paired["audio_path"], clean_target)
        voice.update({"clean_source": "PAIRED_CLEAN_TRIAL", "paired_clean_trial_id": paired["trial_id"],
                      "paired_clean_audio_hash": paired["audio_hash"], "paired_clean_speaker_id": paired.get("speaker_id")})
        if sha256_file(clean_target) != paired["audio_hash"]:
            return _asr_failure(voice, STAGE_AUDIO_CAPTURE, ERROR_AUDIO_CAPTURE_INVALID, "la copia del audio emparejado no es identica", True)
    elif capture is not None and capture.get("path") and Path(capture["path"]).is_file():
        shutil.copyfile(capture["path"], clean_target)
        voice.update({"clean_source": "CAPTURED", "audio_device": (capture.get("device") or {}).get("name"),
                      "recorded_at": capture.get("recorded_at")})
    else:
        voice.update({"audio_capture_success": False})
        return _asr_failure(voice, STAGE_AUDIO_CAPTURE, ERROR_AUDIO_CAPTURE_INVALID, "no hay grabacion", True)
    check = validate_capture(clean_target, settings, (capture or {}).get("device"))
    voice.update({"clean_audio_hash": sha256_file(clean_target), "audio_capture_success": check["valid"],
                  "duration_ms": check["analysis"].get("duration_ms"), "sample_rate": check["analysis"].get("sample_rate"),
                  "channels": check["analysis"].get("channels"), "audio_peak": check["analysis"].get("peak"),
                  "audio_rms": check["analysis"].get("rms")})
    if not check["valid"]:
        return _asr_failure(voice, STAGE_AUDIO_CAPTURE, ERROR_AUDIO_CAPTURE_INVALID, "; ".join(check["errors"]), True)

    # 2) VOICE_NOISE: mezcla determinista con el ruido congelado
    asr_audio = clean_target
    if input_mode == "VOICE_NOISE":
        if noise is None or not noise.get("ok"):
            return _asr_failure(voice, STAGE_NOISE_MIX, ERROR_NOISE_NOT_CONFIGURED, "; ".join((noise or {}).get("errors") or []), True)
        reference = {key: noise[key] for key in ("source", "noise_profile_id", "noise_profile_path", "noise_profile_hash", "snr_db",
                                                 "noise_offset_rule")}
        (audio_dir / NOISE_REFERENCE_FILENAME).write_text(json.dumps(reference, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            mix = mix_at_snr(clean_target, noise["noise_profile_path"], noise["snr_db"], audio_dir / NOISE_AUDIO_FILENAME)
        except (ValueError, wave.Error) as error:
            return _asr_failure(voice, STAGE_NOISE_MIX, ERROR_NOISE_PROFILE_INVALID, str(error), True)
        voice.update({**reference, **{k: mix[k] for k in ("noise_offset_ms", "noise_gain", "noise_looped", "clipped_samples", "mixed_audio_hash")}})
        asr_audio = audio_dir / NOISE_AUDIO_FILENAME

    # 3) ASR (sin correccion humana) sobre el audio de la modalidad
    started = time.perf_counter()
    try:
        result = asr_fn(asr_audio)
    except Exception as error:  # red/API/configuracion: infraestructura
        voice.update({"asr_success": False, "asr_latency_ms": int(round((time.perf_counter() - started) * 1000))})
        return _asr_failure(voice, STAGE_ASR, ERROR_ASR_UNAVAILABLE, str(error), True)
    latency = int(round((time.perf_counter() - started) * 1000))
    transcript = str(result.get("transcript") or "").strip()
    asr_record = {"audio_file": asr_audio.name, "audio_hash": sha256_file(asr_audio), "transcript_raw": transcript,
                  "model": result.get("model"), "language": result.get("language"), "error": result.get("error"),
                  "latency_ms": latency, "frozen_at": _now()}
    (audio_dir / ASR_RESULT_FILENAME).write_text(json.dumps(asr_record, indent=2, ensure_ascii=False), encoding="utf-8")
    metrics = wer_metrics(reference_text, transcript)
    voice.update({"asr_audio": asr_audio.name, "asr_success": bool(transcript), "asr_model": result.get("model"),
                  "asr_language": result.get("language"), "asr_latency_ms": latency, "asr_transcript_raw": transcript,
                  "asr_transcript_normalized": metrics["asr_transcript_normalized"],
                  **{k: metrics[k] for k in ("reference_word_count", "substitutions", "deletions", "insertions", "wer",
                                             "exact_transcript_match", "normalized_transcript_match")}})
    if result.get("error") and "configur" in str(result.get("error")).lower():
        return _asr_failure(voice, STAGE_ASR, ERROR_ASR_UNAVAILABLE, str(result["error"]), True)
    if not transcript:
        return _asr_failure(voice, STAGE_ASR, ERROR_ASR_EMPTY, "el ASR no devolvio texto", False)
    return {"ok": True, "voice": voice, "effective_input_text": transcript, "failure": None}
