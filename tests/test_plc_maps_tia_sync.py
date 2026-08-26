from __future__ import annotations

import plc_maps.tia_sync as tia_sync


def test_prepare_sync_request_builds_tag_payload_from_io_variables_only() -> None:
    map_payload = {
        "variables": [
            {"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0", "description": "Arranque."},
            {"name": "Q_Motor_Enable", "class": "output", "type": "BOOL", "location": "%QX0.0", "description": ""},
            {"name": "M_RunLatch", "class": "internal", "type": "BOOL", "location": ""}
        ]
    }
    request = tia_sync.prepare_sync_request(map_payload)
    names = {tag["name"] for tag in request["tags"]}
    assert names == {"I_Start", "Q_Motor_Enable"}
    assert request["physical_download_allowed"] is False

    start_tag = next(tag for tag in request["tags"] if tag["name"] == "I_Start")
    assert start_tag["address"] == "%I0.0"
    assert start_tag["data_type"] == "Bool"
    assert start_tag["comment"] == "Arranque."


def test_sync_map_with_tia_returns_bridge_result(monkeypatch) -> None:
    monkeypatch.setattr(
        tia_sync,
        "_run_bridge_action",
        lambda action, extra, project_root=None, timeout_seconds=None: {
            "status": "TIA_SYNC_PASSED", "action": action, "tags_sent": len(extra.get("tags", []))
        }
    )
    result = tia_sync.sync_map_with_tia({"variables": [{"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0"}]})
    assert result["status"] == "TIA_SYNC_PASSED"
    assert result["action"] == "sync_map"
    assert result["tags_sent"] == 1


def test_import_tags_from_tia_preserves_existing_aliases(monkeypatch) -> None:
    monkeypatch.setattr(
        tia_sync,
        "_run_bridge_action",
        lambda action, extra, project_root=None, timeout_seconds=None: {
            "status": "TIA_READ_TAGS_PASSED",
            "tag_tables": [
                {
                    "table_name": "PLC_Agent_IO",
                    "tags": [
                        {"name": "I_Start", "data_type": "Bool", "address": "%I0.0", "comment": "Arranque."},
                        {"name": "I_NewSensor", "data_type": "Bool", "address": "%I0.5", "comment": "Sensor nuevo."}
                    ]
                }
            ]
        }
    )
    local_map = {
        "variables": [
            {
                "name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0",
                "aliases": ["pulsador verde"], "semantic_role": "start_command",
                "llm_allowed": True, "safety_level": "normal", "description": "Vieja descripcion"
            }
        ]
    }

    result = tia_sync.import_tags_from_tia(local_map)
    assert result["new_count"] == 1
    assert result["refreshed_count"] == 1

    merged_by_name = {v["name"]: v for v in result["merged_map"]["variables"]}
    assert merged_by_name["I_Start"]["aliases"] == ["pulsador verde"]
    assert merged_by_name["I_Start"]["semantic_role"] == "start_command"
    assert merged_by_name["I_Start"]["description"] == "Vieja descripcion"

    new_variable = merged_by_name["I_NewSensor"]
    assert new_variable["llm_allowed"] is False
    assert new_variable["class"] == "input"
    assert new_variable["location"] == "%IX0.5"


def test_import_tags_from_tia_reports_failed_bridge_without_merging(monkeypatch) -> None:
    monkeypatch.setattr(
        tia_sync,
        "_run_bridge_action",
        lambda action, extra, project_root=None, timeout_seconds=None: {"status": "TIA_NOT_READY"}
    )
    local_map = {"variables": [{"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0"}]}
    result = tia_sync.import_tags_from_tia(local_map)
    assert result["new_count"] == 0
    assert result["merged_map"] == local_map
