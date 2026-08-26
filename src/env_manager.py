from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, set_key

from utils import get_project_root


ENV_DEFAULTS = {
    "OPENAI_API_KEY": "",
    "PLC_LLM_MODEL": "",
    "PLC_TRANSCRIPTION_MODEL": "",
    "PARSER_MODE": "hybrid",
    "LLM_CONFIDENCE_THRESHOLD": "0.85",
    "ENABLE_LLM": "true",
    "ENABLE_VOICE": "true"
}


def get_env_path(project_root: Path | None = None) -> Path:
    return (project_root or get_project_root()) / ".env"


def _default_env_text() -> str:
    return (
        "# Configuracion local de OpenAI para Voz-LLM-PLC Agent\n"
        "# Complete estos valores para activar el parser LLM y la transcripcion.\n\n"
        "OPENAI_API_KEY=\n"
        "PLC_LLM_MODEL=\n"
        "PLC_TRANSCRIPTION_MODEL=\n"
        "PARSER_MODE=hybrid\n"
        "LLM_CONFIDENCE_THRESHOLD=0.85\n"
        "ENABLE_LLM=true\n"
        "ENABLE_VOICE=true\n"
    )


def ensure_env_file(env_path: Path | None = None) -> Path:
    path = env_path or get_env_path()
    if not path.exists():
        path.write_text(_default_env_text(), encoding="utf-8")
    return path


def load_llm_env_settings(env_path: Path | None = None) -> dict[str, str]:
    path = ensure_env_file(env_path)
    file_values = dotenv_values(path)
    settings: dict[str, str] = {}

    for key, default in ENV_DEFAULTS.items():
        value = file_values.get(key)
        if value is None:
            value = os.getenv(key, default)
        settings[key] = str(value if value is not None else default)

    return settings


def save_llm_env_settings(settings: dict[str, Any], env_path: Path | None = None) -> Path:
    path = ensure_env_file(env_path)

    for key, default in ENV_DEFAULTS.items():
        value = settings.get(key, default)
        normalized = str(value if value is not None else default).strip()
        set_key(str(path), key, normalized, quote_mode="never")
        os.environ[key] = normalized

    return path
