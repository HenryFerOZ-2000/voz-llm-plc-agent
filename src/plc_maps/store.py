from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from plc_maps.schema import new_map_payload
from utils import ensure_directory, load_json_file, sanitize_filename


PLC_MAPS_DIRNAME = "plc_maps"
MAP_FILE_SUFFIX = ".json"
RESERVED_STEMS = {"_active_map"}


def get_plc_maps_dir(project_root: Path) -> Path:
    return project_root / "data" / PLC_MAPS_DIRNAME


def _map_files(maps_dir: Path) -> list[Path]:
    if not maps_dir.exists():
        return []
    return sorted(
        path for path in maps_dir.glob(f"*{MAP_FILE_SUFFIX}")
        if path.stem not in RESERVED_STEMS
    )


def list_plc_maps(project_root: Path) -> list[dict[str, Any]]:
    """Return lightweight summaries (metadata only) for every saved map."""
    summaries: list[dict[str, Any]] = []
    for path in _map_files(get_plc_maps_dir(project_root)):
        try:
            payload = load_json_file(path)
        except (FileNotFoundError, ValueError):
            continue
        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        summaries.append(
            {
                "path": path,
                "map_id": metadata.get("map_id", path.stem),
                "name": metadata.get("name", path.stem),
                "version": metadata.get("version", 1),
                "variable_count": len(payload.get("variables", [])) if isinstance(payload, dict) else 0,
                "sync_status": metadata.get("sync_status", "unknown"),
                "dirty": bool(metadata.get("dirty", False))
            }
        )
    return summaries


def load_plc_map(path: Path) -> dict[str, Any]:
    return load_json_file(path)


def _map_path_for_id(project_root: Path, map_id: str) -> Path:
    safe_stem = sanitize_filename(map_id).lower() or "mapa"
    return get_plc_maps_dir(project_root) / f"{safe_stem}{MAP_FILE_SUFFIX}"


def create_plc_map(
    project_root: Path,
    name: str,
    description: str = "",
    target_platform: str = "SIEMENS_SCL_V18",
    variables: list[dict[str, Any]] | None = None
) -> Path:
    maps_dir = ensure_directory(get_plc_maps_dir(project_root))
    map_id = re.sub(r"\s+", "_", name.strip()) or f"mapa_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    path = _map_path_for_id(project_root, map_id)
    suffix = 2
    while path.exists():
        path = _map_path_for_id(project_root, f"{map_id}_{suffix}")
        suffix += 1

    payload = new_map_payload(map_id=path.stem, name=name.strip() or path.stem, description=description, target_platform=target_platform)
    if variables is not None:
        payload["variables"] = variables

    maps_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_plc_map(
    path: Path,
    variables: list[dict[str, Any]],
    metadata_patch: dict[str, Any] | None = None
) -> None:
    """Persist a map file, preserving/patching its metadata block."""
    existing_payload: dict[str, Any] = {}
    if path.exists():
        try:
            existing_payload = load_json_file(path)
        except (FileNotFoundError, ValueError):
            existing_payload = {}

    metadata = dict(existing_payload.get("metadata") or new_map_payload(path.stem, path.stem)["metadata"])
    metadata["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if metadata_patch:
        metadata.update(metadata_patch)

    payload = {
        "schema_version": existing_payload.get("schema_version", 1),
        "metadata": metadata,
        "naming_convention": existing_payload.get("naming_convention", new_map_payload(path.stem, path.stem)["naming_convention"]),
        "variables": variables
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def delete_plc_map(path: Path) -> None:
    if path.exists():
        path.unlink()
