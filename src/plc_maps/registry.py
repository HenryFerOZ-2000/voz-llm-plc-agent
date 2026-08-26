from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from plc_maps.store import get_plc_maps_dir, list_plc_maps
from utils import load_json_file


ACTIVE_POINTER_FILENAME = "_active_map.json"


def get_active_pointer_path(project_root: Path) -> Path:
    return get_plc_maps_dir(project_root) / ACTIVE_POINTER_FILENAME


def load_active_map_id(project_root: Path) -> str | None:
    pointer_path = get_active_pointer_path(project_root)
    if not pointer_path.exists():
        return None
    try:
        payload = load_json_file(pointer_path)
    except (FileNotFoundError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    map_id = payload.get("active_map_id")
    return str(map_id) if map_id else None


def save_active_map_id(project_root: Path, map_id: str) -> None:
    pointer_path = get_active_pointer_path(project_root)
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"version": 1, "active_map_id": map_id}
    pointer_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_active_map_path(project_root: Path) -> Path:
    """Resolve the active map's file path, falling back gracefully if the pointer is stale."""
    summaries = list_plc_maps(project_root)
    active_map_id = load_active_map_id(project_root)

    if active_map_id:
        for summary in summaries:
            if summary["map_id"] == active_map_id:
                return summary["path"]

    if summaries:
        save_active_map_id(project_root, summaries[0]["map_id"])
        return summaries[0]["path"]

    return get_plc_maps_dir(project_root) / "legacy_io_map.json"
