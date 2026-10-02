from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from tia_openness import (
    normal_project_path,
    DEFAULT_PORTAL_ROOT,
    _bridge_paths,
    build_openness_bridge,
    diagnose_tia_openness,
    load_tia_config
)
from utils import build_io_map_index, get_project_root, load_json_file

SIEMENS_TYPE_MAP = {"BOOL": "Bool", "INT": "Int"}


def _to_siemens_address(location: str) -> str:
    normalized = (location or "").upper()
    return normalized.replace("%IX", "%I").replace("%QX", "%Q").replace("%MX", "%M")


def _build_map_tag_payload(map_payload: dict[str, Any]) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    for variable in map_payload.get("variables", []):
        if not isinstance(variable, dict) or variable.get("class") not in {"input", "output"}:
            continue
        tags.append(
            {
                "name": str(variable.get("name", "")),
                "data_type": SIEMENS_TYPE_MAP.get(str(variable.get("type", "BOOL")).upper(), "Bool"),
                "address": _to_siemens_address(str(variable.get("location", ""))),
                "comment": str(variable.get("description", ""))
            }
        )
    return tags


def _run_bridge_action(
    action: str,
    request_extra: dict[str, Any],
    project_root: Path | None = None,
    timeout_seconds: int | None = None
) -> dict[str, Any]:
    root = project_root or get_project_root()
    diagnostic = diagnose_tia_openness(root)
    if not diagnostic["checks"].get("bridge_built"):
        build_result = build_openness_bridge(root)
        if not build_result.get("built"):
            return {
                "executed": False,
                "status": "BRIDGE_BUILD_FAILED",
                "diagnostic": diagnostic,
                "build": build_result,
                "errors": build_result.get("errors", [])
            }
        diagnostic = diagnose_tia_openness(root)

    if not diagnostic.get("is_ready"):
        return {
            "executed": False,
            "status": "TIA_NOT_READY",
            "diagnostic": diagnostic,
            "errors": diagnostic.get("warnings", [])
        }

    config = load_tia_config(root)
    bridge = _bridge_paths(root)
    result_path = root / "tia_openness_bridge" / f"{action}_result.json"
    request = {
        "action": action,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "tia_version": "V18",
        "project_path": normal_project_path(root),  # Modo Normal: nunca el TIA MASTER
        "plc_name": str(config.get("plc_name", "")),
        "result_path": str(result_path.resolve()),
        "attach_to_running": bool(config.get("attach_to_running", True)),
        "with_user_interface": bool(config.get("with_user_interface", True)),
        **request_extra
    }
    request_path = root / "tia_openness_bridge" / f"{action}_request.json"
    request_path.write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")

    environment = os.environ.copy()
    environment["PATH"] = str(DEFAULT_PORTAL_ROOT / "Bin") + os.pathsep + environment.get("PATH", "")
    process_result = subprocess.run(
        [str(bridge["exe"]), str(request_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout_seconds or int(config.get("timeout_seconds", 300)),
        check=False,
        env=environment
    )

    report: dict[str, Any] = {}
    if result_path.exists():
        payload = load_json_file(result_path)
        if isinstance(payload, dict):
            report = payload
    report.update(
        {
            "executed": True,
            "bridge_return_code": process_result.returncode,
            "bridge_stdout": process_result.stdout.strip(),
            "bridge_stderr": process_result.stderr.strip(),
            "request_path": str(request_path),
            "request": request
        }
    )
    return report


def prepare_sync_request(map_payload: dict[str, Any]) -> dict[str, Any]:
    return {"tags": _build_map_tag_payload(map_payload), "physical_download_allowed": False}


def sync_map_with_tia(map_payload: dict[str, Any], project_root: Path | None = None) -> dict[str, Any]:
    """Create/update PLC tags in TIA from the active map, conservatively (never deletes)."""
    return _run_bridge_action("sync_map", prepare_sync_request(map_payload), project_root)


def import_tags_from_tia(map_payload: dict[str, Any], project_root: Path | None = None) -> dict[str, Any]:
    """
    Read existing PLC tags from TIA and merge them into map_payload.

    Existing local variables keep their aliases/semantic_role/llm_allowed/safety_level/
    description/comments; only location/type/class are refreshed. New tags are added with
    conservative defaults (llm_allowed=False) since a human has not reviewed them yet.
    """
    report = _run_bridge_action("read_tags", {}, project_root)
    if report.get("status") != "TIA_READ_TAGS_PASSED":
        return {"report": report, "merged_map": map_payload, "new_count": 0, "refreshed_count": 0}

    existing_index = build_io_map_index(map_payload)
    variables = list(map_payload.get("variables", []))
    variables_by_name = {variable.get("name"): variable for variable in variables}
    new_count = 0
    refreshed_count = 0

    for table in report.get("tag_tables", []):
        for tia_tag in table.get("tags", []):
            name = tia_tag.get("name")
            if not name:
                continue
            address = str(tia_tag.get("address", ""))
            var_class = "input" if address.startswith("%I") else "output" if address.startswith("%Q") else "internal"
            data_type = "BOOL" if tia_tag.get("data_type") == "Bool" else "INT" if tia_tag.get("data_type") == "Int" else str(tia_tag.get("data_type", "BOOL")).upper()
            location = address.replace("%I", "%IX").replace("%Q", "%QX") if address.startswith(("%I", "%Q")) else address

            if name in existing_index:
                variables_by_name[name]["location"] = location
                variables_by_name[name]["type"] = data_type
                variables_by_name[name]["class"] = var_class
                refreshed_count += 1
            else:
                new_variable = {
                    "name": name,
                    "class": var_class,
                    "type": data_type,
                    "location": location,
                    "initial_value": "",
                    "description": tia_tag.get("comment", ""),
                    "aliases": [],
                    "semantic_role": "",
                    "llm_allowed": False,
                    "safety_level": "normal",
                    "unit": "",
                    "min": None,
                    "max": None,
                    "comments": ""
                }
                variables.append(new_variable)
                variables_by_name[name] = new_variable
                new_count += 1

    merged_map = dict(map_payload)
    merged_map["variables"] = variables
    return {"report": report, "merged_map": merged_map, "new_count": new_count, "refreshed_count": refreshed_count}
