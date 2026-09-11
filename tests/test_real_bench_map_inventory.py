"""
Section 1 of the request: a direct check that the REAL, live `mapa_banco_fisico.json` currently
contains exactly the 24 confirmed physical channels (8 DI + 8 DO + 4 AI + 4 AO). Unlike
`test_physical_bench_addresses.py` (which intentionally uses a frozen snapshot to stay decoupled
from live GUI usage), this test is explicitly requested as a live state check - it is expected to
be more fragile (it will fail if the user's own GUI session reduces the map again before this
runs), which is the point: it is the fastest signal that the real file has been mutilated again.
"""
from __future__ import annotations

import json

from utils import get_project_root


def test_real_bench_map_has_all_24_physical_channels():
    path = get_project_root() / "data" / "plc_maps" / "mapa_banco_fisico.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    addresses = {variable["location"] for variable in payload["variables"]}

    expected_digital_inputs = {f"%IX16.{bit}" for bit in range(8)}
    expected_digital_outputs = {f"%QX8.{bit}" for bit in range(8)}
    expected_analog_inputs = {"%IW0", "%IW2", "%IW4", "%IW6"}
    expected_analog_outputs = {"%QW0", "%QW2", "%QW4", "%QW6"}
    expected = expected_digital_inputs | expected_digital_outputs | expected_analog_inputs | expected_analog_outputs

    assert len(payload["variables"]) == 24
    assert addresses == expected


def test_real_bench_map_start_stop_are_locked():
    path = get_project_root() / "data" / "plc_maps" / "mapa_banco_fisico.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_address = {v["location"]: v for v in payload["variables"]}
    assert by_address["%IX16.0"]["state"] == "LOCKED"
    assert by_address["%IX16.1"]["state"] == "LOCKED"


def test_real_bench_map_has_no_i_emergency():
    """El paro de emergencia esta cableado externo al PLC - nunca debe existir I_Emergency en
    este mapa (no se crea automaticamente)."""
    path = get_project_root() / "data" / "plc_maps" / "mapa_banco_fisico.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    names = {v["name"] for v in payload["variables"]}
    assert "I_Emergency" not in names
