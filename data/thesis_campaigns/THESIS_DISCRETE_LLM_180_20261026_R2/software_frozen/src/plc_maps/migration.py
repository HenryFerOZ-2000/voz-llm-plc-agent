from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from plc_maps.registry import save_active_map_id
from plc_maps.schema import new_map_metadata
from plc_maps.store import get_plc_maps_dir, list_plc_maps
from utils import ensure_directory, iter_io_map_entries, load_json_file

LEGACY_MAP_ID = "legacy_io_map"
ALWAYS_CRITICAL_TAGS = {"I_Emergency"}


def migrate_legacy_io_map(legacy_path: Path, target_dir: Path, safety_rules: dict[str, Any] | None = None) -> Path:
    """Wrap the legacy config/io_map.json into the new PLCVariableMap schema."""
    legacy_payload = load_json_file(legacy_path)
    critical_tags = set(ALWAYS_CRITICAL_TAGS)
    if safety_rules:
        critical_tags.update(safety_rules.get("critical_outputs", []))

    variables: list[dict[str, Any]] = []
    for entry in iter_io_map_entries(legacy_payload):
        variable = dict(entry)
        variable.setdefault("aliases", [])
        variable.setdefault("semantic_role", "")
        variable.setdefault("llm_allowed", True)
        variable.setdefault("safety_level", "critical" if variable.get("name") in critical_tags else "normal")
        variable.setdefault("unit", "")
        variable.setdefault("min", None)
        variable.setdefault("max", None)
        variable.setdefault("comments", "")
        variables.append(variable)

    target_path = target_dir / f"{LEGACY_MAP_ID}.json"
    payload = {
        "schema_version": 1,
        "metadata": new_map_metadata(
            map_id=LEGACY_MAP_ID,
            name="Mapa heredado (config/io_map.json)",
            description="Migrado automaticamente desde config/io_map.json.",
            target_platform="SIEMENS_SCL_V18"
        ),
        "naming_convention": legacy_payload.get("naming_convention", {}),
        "variables": variables
    }
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target_path


def ensure_plc_maps_library(project_root: Path, safety_rules: dict[str, Any] | None = None) -> Path:
    """Create data/plc_maps/ on first run and seed it from config/io_map.json if empty."""
    maps_dir = ensure_directory(get_plc_maps_dir(project_root))
    if not list_plc_maps(project_root):
        legacy_path = project_root / "config" / "io_map.json"
        if legacy_path.exists():
            migrate_legacy_io_map(legacy_path, maps_dir, safety_rules)
            save_active_map_id(project_root, LEGACY_MAP_ID)
    return maps_dir
