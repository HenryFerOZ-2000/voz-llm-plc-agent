"""
Dobles del corpus de audio pareado (FORMAL v1.1) para los tests: corpus y ruido maestro en tmp_path, audio sintetico.
Nunca escribe en results/ ni en config/ del repositorio.
"""
from __future__ import annotations

import copy
import json
import math
from array import array
from pathlib import Path

import pytest

from trial_experiments import formal_audio as FA
from trial_experiments import voice_protocol as VP

ROOT = Path(__file__).resolve().parents[1]


def tone(path: Path, seconds: float = 1.0, amplitude: int = 3000, frequency: float = 220.0, rate: int = 16000,
         lead_silence: float = 0.0, channels: int = 1) -> Path:
    """Locucion sintetica: tono con silencio inicial/final opcional (para la region de voz activa)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pad = [0] * int(lead_silence * rate)
    body = [int(amplitude * math.sin(2 * math.pi * frequency * i / rate)) for i in range(int(seconds * rate))]
    mono = pad + body + pad
    samples = array("h", (value for value in mono for _ in range(channels)))
    VP.write_pcm16(path, samples, rate, channels)
    return path


def noise(path: Path, seconds: float = 3.0, rate: int = 16000, seed: int = 12345, amplitude: int = 2000) -> Path:
    """Ruido pseudoaleatorio determinista (LCG): solo para tests, nunca un ruido FORMAL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    state, samples = seed, array("h")
    for _ in range(int(seconds * rate)):
        state = (1103515245 * state + 12345) % (2 ** 31)
        samples.append((state % (2 * amplitude + 1)) - amplitude)
    VP.write_pcm16(path, samples, rate, 1)
    return path


@pytest.fixture
def audio_env(tmp_path, monkeypatch):
    """Corpus FORMAL/DEVELOPMENT en tmp_path y un ruido maestro sintetico 'aprobado' (sha en la config de test)."""
    config = json.loads((ROOT / FA.CONFIG_RELATIVE).read_text(encoding="utf-8"))
    master = noise(tmp_path / "assets" / "industrial_noise_master.wav")
    config["noise_master"].update({"path": str(master), "sha256": FA.sha256_file(master), "approved_by": "test"})
    config["development_noise"] = {"path": None}
    # Misma reparticion que la config real: FORMAL aparte; DEVELOPMENT_VALIDATION y BASELINE comparten corpus de desarrollo.
    roots = {phase: tmp_path / "audio" / Path(relative).name for phase, relative in config["corpus_roots"].items()}
    monkeypatch.setattr(FA, "load_config", lambda root: copy.deepcopy(config))
    monkeypatch.setattr(FA, "corpus_root", lambda root, phase, config=None: roots[phase])
    return {"config": config, "master": master, "roots": roots, "tmp": tmp_path}
