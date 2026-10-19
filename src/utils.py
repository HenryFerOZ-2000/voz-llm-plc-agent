from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def get_project_root() -> Path:
    """Return the project root directory based on this file location."""
    return Path(__file__).resolve().parent.parent


def ensure_directory(path: Path) -> Path:
    """Create a directory if it does not already exist."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        try:
            subprocess.run(["attrib", "-R", str(path)], check=False, capture_output=True)
        except OSError:
            pass
    try:
        path.chmod(0o755)
    except OSError:
        pass
    return path


def load_json_file(path: Path) -> Any:
    """Load a JSON file and return its parsed representation."""
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Required JSON file was not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON content in file: {path}") from error


def current_timestamp(compact: bool = False) -> str:
    """Return the current timestamp in ISO or filename-safe format."""
    if compact:
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    return datetime.now().isoformat(timespec="seconds")


def pretty_json(data: Any) -> str:
    """Serialize data as human-readable JSON."""
    return json.dumps(data, indent=2, ensure_ascii=False)


def sanitize_filename(value: str | None) -> str:
    """
    Convert an arbitrary value into a Windows-safe file name fragment.
    """
    if value is None:
        return "NOCASE"

    normalized = str(value).strip().replace(" ", "_")
    if not normalized:
        return "NOCASE"

    normalized = re.sub(r'[<>:"/\\\\|?*]+', "", normalized)
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "", normalized)
    normalized = normalized.strip("._-")
    return normalized or "NOCASE"


_ADVANCED_VARIABLE_FIELDS = (
    "aliases", "semantic_role", "llm_allowed", "safety_level", "unit", "min", "max", "comments", "state"
)


def iter_io_map_entries(io_map: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return every PLC variable entry from io_map.

    Preferred format:
    {
      "variables": [
        {"name": "...", "type": "...", "class": "...", ...}
      ]
    }

    Legacy hierarchical formats are also normalized here to avoid breaking
    older files while the project migrates to a single source of truth.
    """
    variables = io_map.get("variables")
    if isinstance(variables, list):
        normalized_entries: list[dict[str, Any]] = []
        for entry in variables:
            if not isinstance(entry, dict) or "name" not in entry:
                continue
            normalized_entry = {
                "name": entry.get("name", ""),
                "type": entry.get("type", "BOOL"),
                "class": entry.get("class", "internal"),
                "location": entry.get("location", ""),
                "initial_value": entry.get("initial_value", ""),
                "description": entry.get("description", "")
            }
            for advanced_field in _ADVANCED_VARIABLE_FIELDS:
                if advanced_field in entry:
                    normalized_entry[advanced_field] = entry[advanced_field]
            if "analog_config" in entry:
                normalized_entry["analog_config"] = copy.deepcopy(entry["analog_config"])
            if "process_config" in entry:
                normalized_entry["process_config"] = copy.deepcopy(entry["process_config"])
            normalized_entries.append(normalized_entry)
        return normalized_entries

    entries: list[dict[str, Any]] = []
    legacy_section_map = {
        "inputs": "input",
        "outputs": "output",
        "internal": "internal",
        "timers": "timer",
        "counters": "counter",
        "auxiliary": "auxiliary"
    }
    for section_name, var_class in legacy_section_map.items():
        section = io_map.get(section_name, {})
        if not isinstance(section, dict):
            continue
        for var_type, names in section.items():
            if not isinstance(names, list):
                continue
            for name in names:
                entries.append(
                    {
                        "name": name,
                        "type": var_type,
                        "class": var_class,
                        "location": "",
                        "initial_value": "FALSE" if var_type == "BOOL" else "0" if var_type == "INT" else "",
                        "description": ""
                    }
                )
    return entries


def build_io_map_index(io_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a name -> variable entry lookup from io_map."""
    return {entry["name"]: entry for entry in iter_io_map_entries(io_map) if entry.get("name")}


def flatten_io_map(io_map: dict[str, Any]) -> set[str]:
    """Collect every authorized PLC tag from the normalized io_map."""
    return set(build_io_map_index(io_map))
