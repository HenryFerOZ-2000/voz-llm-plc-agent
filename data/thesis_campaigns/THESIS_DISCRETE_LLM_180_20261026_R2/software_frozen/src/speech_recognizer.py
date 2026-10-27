from __future__ import annotations

import math
import tempfile
import threading
import time
import wave
from array import array
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_client import APIConnectionError, APITimeoutError, PLCInterpretationLLMClient
from utils import ensure_directory, get_project_root, sanitize_filename

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover - handled in demo mode
    sd = None


DEFAULT_TRANSCRIPTION_LANGUAGE = "es"
DEFAULT_TRANSCRIPTION_PROMPT = (
    "Comando de automatizacion industrial para un PLC. Vocabulario esperado: "
    "Start, Stop, emergencia, reset, motor, sensor, alarma, salida, temporizador, "
    "contador, modo manual, modo automatico, OpenPLC, CODESYS y Structured Text."
)
# Tope de seguridad: si el usuario olvida presionar "Detener", la grabacion se
# corta sola en lugar de crecer sin limite en memoria.
DEFAULT_MAX_RECORDING_SECONDS = 60.0
# Por debajo de este RMS (escala int16, +-32767) se considera que la grabacion
# no tiene contenido util (silencio, microfono muteado o desconectado).
DEFAULT_SILENCE_RMS_THRESHOLD = 150
DEFAULT_TRANSCRIPTION_TIMEOUT_SECONDS = 30
DEFAULT_TRANSCRIPTION_MAX_RETRIES = 1
_TRANSCRIPTION_RETRY_DELAY_SECONDS = 1.0


class SpeechRecognizer:
    """Local audio capture plus optional cloud transcription."""

    def __init__(
        self,
        llm_client: PLCInterpretationLLMClient | None = None,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        save_evidence: bool = False,
        temp_dir: Path | None = None,
        evidence_dir: Path | None = None,
        transcription_language: str | None = None,
        transcription_prompt: str | None = None,
        max_recording_seconds: float | None = None,
        silence_rms_threshold: int | None = None,
        transcription_timeout_seconds: int | None = None,
        transcription_max_retries: int | None = None,
        input_device_index: int | None = None
    ) -> None:
        self.llm_client = llm_client or PLCInterpretationLLMClient()
        self.sample_rate = sample_rate
        self.channels = channels
        self.save_evidence = save_evidence
        client_config = getattr(self.llm_client, "config", {})
        if not isinstance(client_config, dict):
            client_config = {}
        self.transcription_language = (
            transcription_language
            or str(client_config.get("transcription_language", DEFAULT_TRANSCRIPTION_LANGUAGE))
        ).strip()
        self.transcription_prompt = (
            transcription_prompt
            or str(client_config.get("transcription_prompt", DEFAULT_TRANSCRIPTION_PROMPT))
        ).strip()
        self.max_recording_seconds = float(
            max_recording_seconds
            if max_recording_seconds is not None
            else client_config.get("max_recording_seconds", DEFAULT_MAX_RECORDING_SECONDS)
        )
        self.silence_rms_threshold = int(
            silence_rms_threshold
            if silence_rms_threshold is not None
            else client_config.get("silence_rms_threshold", DEFAULT_SILENCE_RMS_THRESHOLD)
        )
        self.transcription_timeout_seconds = int(
            transcription_timeout_seconds
            if transcription_timeout_seconds is not None
            else client_config.get("transcription_timeout_seconds", DEFAULT_TRANSCRIPTION_TIMEOUT_SECONDS)
        )
        self.transcription_max_retries = int(
            transcription_max_retries
            if transcription_max_retries is not None
            else client_config.get("transcription_max_retries", DEFAULT_TRANSCRIPTION_MAX_RETRIES)
        )
        self.input_device_index = input_device_index
        self.project_root = get_project_root()
        default_temp_dir = Path(tempfile.gettempdir()) / "voz_llm_plc_agent" / "tmp_audio"
        default_evidence_dir = self.project_root / "voice_evidence"
        self.temp_dir = self._safe_directory(temp_dir or default_temp_dir, fallback=default_temp_dir)
        self.evidence_dir = self._safe_directory(evidence_dir or default_evidence_dir, fallback=default_temp_dir)
        self._stream: Any | None = None
        self._frames: list[bytes] = []
        self._recording_started_at: float | None = None
        self._current_audio_path: Path | None = None
        self._stream_status_messages: list[str] = []
        self._auto_stopped: bool = False
        self._level_lock = threading.Lock()
        self._current_peak: int = 0
        self._current_rms: int = 0

    def _safe_directory(self, requested: Path, fallback: Path) -> Path:
        try:
            return ensure_directory(requested)
        except OSError:
            return ensure_directory(fallback)

    def is_recording_available(self) -> bool:
        return bool(self.get_input_device_info().get("available", False))

    def is_recording(self) -> bool:
        return self._stream is not None

    def get_input_device_info(self) -> dict[str, Any]:
        if sd is None:
            return {
                "available": False,
                "name": None,
                "index": None,
                "error": "La libreria sounddevice no esta instalada."
            }

        try:
            if self.input_device_index is not None:
                device = sd.query_devices(self.input_device_index)
                device_index = self.input_device_index
            else:
                device = sd.query_devices(kind="input")
                device_index = int(device.get("index", sd.default.device[0]))
            return {
                "available": int(device.get("max_input_channels", 0)) > 0,
                "name": str(device.get("name", "Microfono predeterminado")),
                "index": device_index,
                "max_input_channels": int(device.get("max_input_channels", 0)),
                "default_samplerate": float(device.get("default_samplerate", 0.0)),
                "error": None
            }
        except Exception as error:  # pragma: no cover - depends on local audio host
            return {
                "available": False,
                "name": None,
                "index": None,
                "error": str(error)
            }

    def list_input_devices(self) -> list[dict[str, Any]]:
        """List every audio device with at least one input channel."""
        if sd is None:
            return []
        try:
            devices = sd.query_devices()
        except Exception:  # pragma: no cover - depends on local audio host
            return []

        input_devices: list[dict[str, Any]] = []
        for index, device in enumerate(devices):
            if int(device.get("max_input_channels", 0)) <= 0:
                continue
            input_devices.append(
                {
                    "index": index,
                    "name": str(device.get("name", f"Dispositivo {index}")),
                    "max_input_channels": int(device.get("max_input_channels", 0)),
                    "default_samplerate": float(device.get("default_samplerate", 0.0))
                }
            )
        return input_devices

    def set_input_device(self, device_index: int | None) -> None:
        if self.is_recording():
            raise RuntimeError("No se puede cambiar el microfono mientras hay una grabacion en curso.")
        self.input_device_index = device_index

    def start_recording(self) -> dict[str, Any]:
        if sd is None:
            raise RuntimeError("La libreria sounddevice no esta instalada.")
        if self.is_recording():
            raise RuntimeError("Ya existe una grabacion de voz en curso.")

        device_info = self.get_input_device_info()
        if not device_info.get("available"):
            detail = device_info.get("error") or "No existe un microfono de entrada disponible."
            raise RuntimeError(detail)

        self._frames = []
        self._stream_status_messages = []
        self._recording_started_at = time.perf_counter()
        self._current_audio_path = self._next_audio_path()
        self._auto_stopped = False
        self._current_peak = 0
        self._current_rms = 0

        def _callback(indata: bytes, _frames: int, _time_info: Any, status: Any) -> None:
            if status:
                self._stream_status_messages.append(str(status))
            data = bytes(indata)
            self._frames.append(data)
            self._update_level(data)
            if (
                self.max_recording_seconds > 0
                and self._recording_started_at is not None
                and (time.perf_counter() - self._recording_started_at) >= self.max_recording_seconds
            ):
                self._auto_stopped = True
                raise sd.CallbackStop()

        try:
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                device=device_info.get("index"),
                callback=_callback
            )
            self._stream.start()
        except Exception as error:  # pragma: no cover - depends on local microphone
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
            self._stream = None
            self._recording_started_at = None
            raise RuntimeError(f"No fue posible iniciar la grabacion: {error}") from error

        return {
            "status": "recording",
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "audio_file": str(self._current_audio_path),
            "input_device": device_info
        }

    def stop_recording(self) -> Path:
        if self._stream is None or self._current_audio_path is None:
            raise RuntimeError("No existe una grabacion en curso.")

        try:
            # El stream puede haberse detenido solo (tope de duracion via
            # sd.CallbackStop en el callback); stop()/close() deben tolerar
            # ese estado sin lanzar un error hacia el usuario.
            try:
                self._stream.stop()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
        finally:
            self._stream = None
            self._recording_started_at = None

        if not self._frames:
            raise RuntimeError("La grabacion no contiene audio util.")

        self._write_wav_file(self._current_audio_path, self._frames)
        return self._current_audio_path

    def _update_level(self, data: bytes) -> None:
        if not data:
            return
        samples = array("h", data)
        if not samples:
            return
        peak = max(abs(value) for value in samples)
        rms = round(math.sqrt(sum(value * value for value in samples) / len(samples)))
        with self._level_lock:
            self._current_peak = peak
            self._current_rms = rms

    def get_current_level(self) -> dict[str, int]:
        """Latest peak/RMS from the recording callback, for a live level meter."""
        with self._level_lock:
            return {"peak": self._current_peak, "rms": self._current_rms}

    def recording_elapsed_seconds(self) -> float | None:
        if self._recording_started_at is None:
            return None
        return round(time.perf_counter() - self._recording_started_at, 1)

    def was_auto_stopped(self) -> bool:
        """True when the last recording hit max_recording_seconds and stopped itself."""
        return self._auto_stopped

    def cancel_recording(self) -> None:
        stream = self._stream
        self._stream = None
        self._recording_started_at = None
        self._frames = []
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def _next_audio_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base_name = f"{timestamp}_command.wav"
        target_dir = self.evidence_dir if self.save_evidence else self.temp_dir
        return target_dir / sanitize_filename(base_name)

    def _write_wav_file(self, path: Path, frames: list[bytes]) -> None:
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(b"".join(frames))

    def inspect_audio_file(self, audio_path: Path) -> dict[str, Any]:
        with wave.open(str(audio_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            sample_width = wav_file.getsampwidth()
            raw_audio = wav_file.readframes(frame_count)

        samples = array("h", raw_audio) if sample_width == 2 else array("h")
        peak = max((abs(value) for value in samples), default=0)
        rms = 0
        if samples:
            rms = round(math.sqrt(sum(value * value for value in samples) / len(samples)))

        return {
            "duration_seconds": round(frame_count / sample_rate, 3) if sample_rate else 0.0,
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_width_bytes": sample_width,
            "peak": peak,
            "rms": rms,
            "stream_warnings": list(self._stream_status_messages)
        }

    def record_audio(self, duration_seconds: int | None = None) -> Path:
        duration = duration_seconds or 5
        self.start_recording()
        time.sleep(max(1, duration))
        return self.stop_recording()

    def transcribe_audio(self, audio_path: Path, enforce_quality_checks: bool = True) -> dict[str, Any]:
        """
        enforce_quality_checks=False: el protocolo experimental ya valido tecnicamente la captura con
        sus propios umbrales documentados (voice_protocol.validate_capture); aqui no se vuelve a filtrar.
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"El archivo de audio no existe: {audio_path}")
        if audio_path.stat().st_size == 0:
            raise RuntimeError("El archivo de audio esta vacio.")
        audio_metadata = self.inspect_audio_file(audio_path)
        if not self.llm_client.is_transcription_configured():
            return {
                "transcript": "",
                "language": None,
                "duration": None,
                "model": self.llm_client.get_transcription_model(),
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "confidence": None,
                "audio_file": str(audio_path),
                "audio_metadata": audio_metadata,
                "processing_seconds": None,
                "error": "La transcripcion requiere API y modelo configurados."
            }
        if enforce_quality_checks and audio_metadata["duration_seconds"] < 0.35:
            raise RuntimeError("La grabacion es demasiado corta. Hable durante al menos un segundo.")
        if enforce_quality_checks and audio_metadata["rms"] < self.silence_rms_threshold:
            raise RuntimeError(
                "La grabacion no tiene suficiente nivel de audio (posible silencio, microfono "
                "muteado o desconectado). Verifique el microfono e intente de nuevo."
            )

        client = self.llm_client.get_openai_client()
        model_name = self.llm_client.get_transcription_model()
        started_at = time.perf_counter()

        transcription: Any = None
        last_error: str | None = None
        attempt = 0
        for attempt in range(self.transcription_max_retries + 1):
            try:
                with audio_path.open("rb") as audio_file:
                    transcription = client.audio.transcriptions.create(
                        model=model_name,
                        file=audio_file,
                        language=self.transcription_language or None,
                        prompt=self.transcription_prompt or None,
                        # Los modelos GPT de transcripcion aceptan JSON simple; las
                        # metricas del audio se calculan localmente sobre el WAV.
                        response_format="json",
                        temperature=0,
                        timeout=self.transcription_timeout_seconds
                    )
                break
            except (APITimeoutError, APIConnectionError) as error:
                last_error = str(error)
                if attempt >= self.transcription_max_retries:
                    raise RuntimeError(
                        "No fue posible transcribir el audio tras "
                        f"{attempt + 1} intento(s) por fallas de red/tiempo de espera: {last_error}"
                    ) from error
                time.sleep(_TRANSCRIPTION_RETRY_DELAY_SECONDS)

        processing_seconds = round(time.perf_counter() - started_at, 3)
        transcript_text = str(getattr(transcription, "text", "") or "").strip()
        language = getattr(transcription, "language", None) or self.transcription_language
        confidence = getattr(transcription, "confidence", None)
        return {
            "transcript": transcript_text,
            "language": language,
            "duration": audio_metadata["duration_seconds"],
            "model": model_name,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "confidence": confidence,
            "audio_file": str(audio_path),
            "audio_metadata": audio_metadata,
            "processing_seconds": processing_seconds,
            "retries_used": attempt,
            "error": None if transcript_text else "La API no detecto voz inteligible en la grabacion."
        }

    def discard_audio(self, audio_path: Path | None, *, force: bool = False) -> bool:
        if audio_path is None or not audio_path.exists():
            return False

        is_temporary = False
        try:
            is_temporary = audio_path.resolve().is_relative_to(self.temp_dir.resolve())
        except OSError:
            is_temporary = False

        if not force and not is_temporary:
            return False
        try:
            audio_path.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def listen_and_transcribe(self) -> dict[str, Any]:
        audio_path = self.record_audio()
        result = self.transcribe_audio(audio_path)
        if not self.save_evidence:
            self.discard_audio(audio_path)
        return result
