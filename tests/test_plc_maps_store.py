from __future__ import annotations

from pathlib import Path

from plc_maps.store import create_plc_map, delete_plc_map, list_plc_maps, load_plc_map, save_plc_map


def test_create_plc_map_writes_schema_and_metadata(tmp_path: Path) -> None:
    path = create_plc_map(tmp_path, name="Motor Basico", description="Banco de pruebas")
    assert path.exists()
    payload = load_plc_map(path)
    assert payload["schema_version"] == 1
    assert payload["metadata"]["name"] == "Motor Basico"
    assert payload["metadata"]["description"] == "Banco de pruebas"
    assert payload["variables"] == []


def test_save_plc_map_updates_metadata_and_clears_dirty(tmp_path: Path) -> None:
    path = create_plc_map(tmp_path, name="Motor Basico")
    variables = [{"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0"}]
    save_plc_map(path, variables, metadata_patch={"dirty": False, "sync_status": "synced"})

    payload = load_plc_map(path)
    assert payload["variables"] == variables
    assert payload["metadata"]["dirty"] is False
    assert payload["metadata"]["sync_status"] == "synced"
    assert payload["metadata"]["name"] == "Motor Basico"


def test_load_plc_map_round_trip_preserves_advanced_fields(tmp_path: Path) -> None:
    path = create_plc_map(tmp_path, name="Motor Basico")
    variables = [
        {
            "name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0",
            "aliases": ["pulsador verde"], "semantic_role": "start_command",
            "llm_allowed": True, "safety_level": "normal"
        }
    ]
    save_plc_map(path, variables)

    reloaded = load_plc_map(path)
    assert reloaded["variables"][0]["aliases"] == ["pulsador verde"]
    assert reloaded["variables"][0]["semantic_role"] == "start_command"


def test_save_plc_map_omits_deleted_variable(tmp_path: Path) -> None:
    path = create_plc_map(tmp_path, name="Motor Basico")
    save_plc_map(path, [{"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0"}])
    save_plc_map(path, [])

    reloaded = load_plc_map(path)
    assert reloaded["variables"] == []


def test_list_plc_maps_returns_summaries(tmp_path: Path) -> None:
    create_plc_map(tmp_path, name="Motor Basico")
    create_plc_map(tmp_path, name="Banda Transportadora")

    summaries = list_plc_maps(tmp_path)
    names = {summary["name"] for summary in summaries}
    assert names == {"Motor Basico", "Banda Transportadora"}


def test_delete_plc_map_removes_file(tmp_path: Path) -> None:
    path = create_plc_map(tmp_path, name="Temporal")
    assert path.exists()
    delete_plc_map(path)
    assert not path.exists()
