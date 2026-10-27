from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from utils import get_project_root


KEYWORD_HINTS = {
    "INT_TIMED_PULSE": ["pulso", "salida", "segundos", "temporizador"],
    "INT_MOTOR_START_STOP": ["motor", "start", "stop", "marcha", "paro"],
    "INT_DELAYED_START": ["retardo", "arranque", "motor", "segundos"],
    "INT_DELAYED_STOP": ["apagado", "retardo", "paro", "motor"],
    "INT_COUNTER_PULSES": ["contador", "pulsos", "sensor", "alarma"],
    "INT_EMERGENCY_PRIORITY": ["emergency", "emergencia", "seguridad", "paro"],
    "INT_MANUAL_AUTO_MODE": ["manual", "automatico", "modo"],
    "INT_MUTUAL_INTERLOCK": ["contactor", "interlock", "simultaneo"],
    "INT_MAINTENANCE_BLOCK": ["mantenimiento", "bloqueo", "motor"],
    "INT_SENSOR_TIMEOUT_ALARM": ["sensor", "timeout", "alarma", "retardo"],
    "INT_CYCLIC_MOTOR": ["motor", "bucle", "ciclico", "encendido", "apagado", "temporizador"],
    "INT_AUTO_CYCLE": ["ciclo", "secuencia", "paso", "auto"]
}


def _knowledge_base_dir() -> Path:
    return get_project_root() / "knowledge_base"


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def _score_document(content: str, keywords: set[str]) -> int:
    tokens = _tokenize(content)
    return sum(3 for keyword in keywords if keyword in tokens)


def retrieve_relevant_context(
    command_text: str,
    intent_id: str | None,
    platform: str | None,
    top_k: int = 5
) -> list[dict[str, Any]]:
    knowledge_dir = _knowledge_base_dir()
    if not knowledge_dir.exists():
        return []

    keywords = _tokenize(command_text)
    if intent_id and intent_id in KEYWORD_HINTS:
        keywords.update(KEYWORD_HINTS[intent_id])
    if platform:
        keywords.update(_tokenize(platform))

    ranked_items: list[dict[str, Any]] = []
    for doc_path in sorted(knowledge_dir.glob("*.md")):
        content = doc_path.read_text(encoding="utf-8")
        score = _score_document(content, keywords)
        if score <= 0:
            continue

        excerpt_lines = [line.strip() for line in content.splitlines() if line.strip()][:8]
        ranked_items.append(
            {
                "source": doc_path.name,
                "score": score,
                "excerpt": "\n".join(excerpt_lines)
            }
        )

    ranked_items.sort(key=lambda item: (-item["score"], item["source"]))
    return ranked_items[:top_k]
