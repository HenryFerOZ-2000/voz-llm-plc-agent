from __future__ import annotations

from datetime import datetime
from typing import Any


SCHEMA_VERSION = 1

ADVANCED_VARIABLE_FIELDS = (
    "aliases", "semantic_role", "llm_allowed", "safety_level", "unit", "min", "max", "comments"
)

ADVANCED_VARIABLE_DEFAULTS: dict[str, Any] = {
    "aliases": [],
    "semantic_role": "",
    "llm_allowed": True,
    "safety_level": "normal",
    "unit": "",
    "min": None,
    "max": None,
    "comments": ""
}

SAFETY_LEVELS = ["normal", "critical"]

DEFAULT_NAMING_CONVENTION = {
    "inputs": "I_",
    "outputs": "Q_",
    "internal_memory": "M_",
    "timers": "T_",
    "counters": "C_",
    "auxiliary": "R_"
}


def new_map_metadata(
    map_id: str,
    name: str,
    description: str = "",
    target_platform: str = "SIEMENS_SCL_V18",
    version: int = 1
) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "map_id": map_id,
        "name": name,
        "version": version,
        "description": description,
        "target_platform": target_platform,
        "created_at": now,
        "updated_at": now,
        "tia_project_path": "",
        "tia_plc_name": "",
        "sync_status": "unknown",
        "dirty": False
    }


def new_map_payload(map_id: str, name: str, description: str = "", target_platform: str = "SIEMENS_SCL_V18") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": new_map_metadata(map_id, name, description, target_platform),
        "naming_convention": dict(DEFAULT_NAMING_CONVENTION),
        "variables": []
    }
