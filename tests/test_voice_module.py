from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_client import APITimeoutError
from speech_recognizer import SpeechRecognizer


class DummyLLMClient:
    def is_transcription_configured(self) -> bool:
        return False

    def get_transcription_model(self) -> str | None:
        return None


def _write_minimal_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 160)


def _write_one_second_wav(path: Path, amplitude: int = 5000) -> None:
    # amplitude=5000 aproxima el nivel de una voz normal captada de cerca;
    # el valor previo (16) quedaba por debajo del umbral de silencio local.
    sample = amplitude.to_bytes(2, byteorder="little", signed=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(sample * 16000)


class DummyTranscriptionsAPI:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.arguments: dict = {}
        self.call_count = 0
        self._fail_times = fail_times

    def create(self, **kwargs):
        self.call_count += 1
        self.arguments = kwargs
        if self.call_count <= self._fail_times:
            raise APITimeoutError("Simulated transient timeout")
        return SimpleNamespace(
            text="Haz que el motor se encienda con Start y se apague con Stop",
            language="es",
            confidence=0.99
        )


class ConfiguredDummyLLMClient:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.transcriptions = DummyTranscriptionsAPI(fail_times=fail_times)
        self.config = {}

    def is_transcription_configured(self) -> bool:
        return True

    def get_transcription_model(self) -> str:
        return "gpt-4o-mini-transcribe"

    def get_openai_client(self):
        return SimpleNamespace(
            audio=SimpleNamespace(transcriptions=self.transcriptions)
        )


def test_voice_module_returns_clear_message_without_api(tmp_path: Path) -> None:
    audio_path = tmp_path / "sample.wav"
    _write_minimal_wav(audio_path)
    recognizer = SpeechRecognizer(
        llm_client=DummyLLMClient(),
        temp_dir=tmp_path / "tmp_audio",
        evidence_dir=tmp_path / "voice_evidence"
    )
    result = recognizer.transcribe_audio(audio_path)
    assert result["transcript"] == ""
    assert "requiere API" in result["error"]


def test_voice_transcription_uses_spanish_industrial_context(tmp_path: Path) -> None:
    audio_path = tmp_path / "industrial-command.wav"
    _write_one_second_wav(audio_path)
    llm_client = ConfiguredDummyLLMClient()
    recognizer = SpeechRecognizer(
        llm_client=llm_client,
        temp_dir=tmp_path / "tmp_audio",
        evidence_dir=tmp_path / "voice_evidence"
    )

    result = recognizer.transcribe_audio(audio_path)

    assert result["transcript"].endswith("Stop")
    assert result["language"] == "es"
    assert result["audio_metadata"]["duration_seconds"] == 1.0
    assert result["error"] is None
    assert llm_client.transcriptions.arguments["language"] == "es"
    assert "automatizacion industrial" in llm_client.transcriptions.arguments["prompt"]
    assert llm_client.transcriptions.arguments["response_format"] == "json"
    assert llm_client.transcriptions.arguments["temperature"] == 0


def test_voice_module_rejects_silent_recording_without_calling_api(tmp_path: Path) -> None:
    audio_path = tmp_path / "silence.wav"
    _write_one_second_wav(audio_path, amplitude=0)  # long enough, but RMS 0
    llm_client = ConfiguredDummyLLMClient()
    recognizer = SpeechRecognizer(
        llm_client=llm_client,
        temp_dir=tmp_path / "tmp_audio",
        evidence_dir=tmp_path / "voice_evidence"
    )

    with pytest.raises(RuntimeError, match="nivel de audio"):
        recognizer.transcribe_audio(audio_path)

    assert llm_client.transcriptions.call_count == 0


def test_voice_transcription_retries_on_transient_timeout_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("speech_recognizer.time.sleep", lambda *_args: None)
    audio_path = tmp_path / "industrial-command.wav"
    _write_one_second_wav(audio_path)
    llm_client = ConfiguredDummyLLMClient(fail_times=1)
    recognizer = SpeechRecognizer(
        llm_client=llm_client,
        temp_dir=tmp_path / "tmp_audio",
        evidence_dir=tmp_path / "voice_evidence",
        transcription_max_retries=1
    )

    result = recognizer.transcribe_audio(audio_path)

    assert result["transcript"].endswith("Stop")
    assert result["retries_used"] == 1
    assert llm_client.transcriptions.call_count == 2
    assert llm_client.transcriptions.arguments["timeout"] == recognizer.transcription_timeout_seconds


def test_voice_transcription_gives_up_after_exhausting_retries(tmp_path: Path) -> None:
    audio_path = tmp_path / "industrial-command.wav"
    _write_one_second_wav(audio_path)
    llm_client = ConfiguredDummyLLMClient(fail_times=5)
    recognizer = SpeechRecognizer(
        llm_client=llm_client,
        temp_dir=tmp_path / "tmp_audio",
        evidence_dir=tmp_path / "voice_evidence",
        transcription_max_retries=0
    )

    with pytest.raises(RuntimeError, match="fallas de red"):
        recognizer.transcribe_audio(audio_path)

    assert llm_client.transcriptions.call_count == 1


def test_voice_module_tracks_live_level_and_elapsed_time(tmp_path: Path) -> None:
    recognizer = SpeechRecognizer(
        llm_client=DummyLLMClient(),
        temp_dir=tmp_path / "tmp_audio",
        evidence_dir=tmp_path / "voice_evidence",
        max_recording_seconds=30
    )

    assert recognizer.get_current_level() == {"peak": 0, "rms": 0}
    assert recognizer.recording_elapsed_seconds() is None
    assert recognizer.was_auto_stopped() is False

    loud_sample = (5000).to_bytes(2, byteorder="little", signed=True) * 100
    recognizer._update_level(loud_sample)
    level = recognizer.get_current_level()
    assert level["peak"] == 5000
    assert level["rms"] == 5000


def test_voice_module_lists_input_devices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import speech_recognizer as speech_recognizer_module

    fake_devices = [
        {"name": "Microfono USB", "max_input_channels": 1, "default_samplerate": 48000.0},
        {"name": "Altavoces", "max_input_channels": 0, "default_samplerate": 48000.0},
        {"name": "Microfono integrado", "max_input_channels": 2, "default_samplerate": 44100.0}
    ]
    fake_sd = SimpleNamespace(query_devices=lambda *args, **kwargs: fake_devices)
    monkeypatch.setattr(speech_recognizer_module, "sd", fake_sd)

    recognizer = SpeechRecognizer(
        llm_client=DummyLLMClient(),
        temp_dir=tmp_path / "tmp_audio",
        evidence_dir=tmp_path / "voice_evidence"
    )

    devices = recognizer.list_input_devices()

    assert [device["name"] for device in devices] == ["Microfono USB", "Microfono integrado"]
    assert devices[0]["index"] == 0
    assert devices[1]["index"] == 2

    recognizer.set_input_device(2)
    assert recognizer.input_device_index == 2


def test_voice_module_discards_only_temporary_audio(tmp_path: Path) -> None:
    recognizer = SpeechRecognizer(
        llm_client=DummyLLMClient(),
        temp_dir=tmp_path / "tmp_audio",
        evidence_dir=tmp_path / "voice_evidence"
    )
    temporary_audio = recognizer.temp_dir / "temporary.wav"
    evidence_audio = recognizer.evidence_dir / "evidence.wav"
    _write_minimal_wav(temporary_audio)
    _write_minimal_wav(evidence_audio)

    assert recognizer.discard_audio(temporary_audio) is True
    assert temporary_audio.exists() is False
    assert recognizer.discard_audio(evidence_audio) is False
    assert evidence_audio.exists() is True
