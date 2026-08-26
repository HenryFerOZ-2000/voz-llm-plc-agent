from __future__ import annotations

from pathlib import Path

from plc_maps.registry import load_active_map_id, resolve_active_map_path, save_active_map_id
from plc_maps.store import create_plc_map, list_plc_maps


def test_resolve_active_map_path_falls_back_when_no_pointer(tmp_path: Path) -> None:
    create_plc_map(tmp_path, name="Motor Basico")
    resolved = resolve_active_map_path(tmp_path)
    assert resolved.exists()


def test_switch_active_map_pointer_persists_and_resolves(tmp_path: Path) -> None:
    path_a = create_plc_map(tmp_path, name="Motor Basico")
    path_b = create_plc_map(tmp_path, name="Banda Transportadora")
    summaries = {summary["path"]: summary["map_id"] for summary in list_plc_maps(tmp_path)}

    save_active_map_id(tmp_path, summaries[path_b])
    assert load_active_map_id(tmp_path) == summaries[path_b]
    assert resolve_active_map_path(tmp_path) == path_b

    save_active_map_id(tmp_path, summaries[path_a])
    assert resolve_active_map_path(tmp_path) == path_a


def test_resolve_active_map_path_recovers_from_stale_pointer(tmp_path: Path) -> None:
    create_plc_map(tmp_path, name="Motor Basico")
    save_active_map_id(tmp_path, "mapa_que_no_existe")
    resolved = resolve_active_map_path(tmp_path)
    assert resolved.exists()
