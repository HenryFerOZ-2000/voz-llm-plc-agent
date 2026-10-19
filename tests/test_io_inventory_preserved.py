"""
Regression tests for a real bug: after a MAP_CONFIG command, the physical map lost every channel
not referenced by the current program - the "Mapa I/O completo" window ended up showing only the
active program's tags instead of the full hardware inventory.

Root cause: `gui.py::_handle_map_config_command` used `io_map` (the function parameter, sourced
from `_load_runtime_configuration()`) as the PATCH BASE for `apply_assignments()`/`save_plc_map()`.
`_load_runtime_configuration()` runs that same `io_map` through `apply_profile_filter()`, which is
correct for INTERPRETING a command under an active experimental profile (it must only see
`allowed_variables`) but is the wrong base for a WRITE-BACK: persisting a profile-filtered view
permanently deletes every physical channel outside that profile's whitelist. `io_allocator.py`
itself (`propose_assignment`/`apply_assignments`) was verified clean in isolation - it always
patches over the full list it is given. The fix: `_handle_map_config_command` now reloads the
complete, unfiltered map directly from disk right before applying/saving, never trusting the
(possibly filtered) parameter for that step.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402
from semantic_validator import validate_semantic_output  # noqa: E402


def _variable(name, location, state, var_class="input", var_type="BOOL"):
    return {
        "name": name, "class": var_class, "type": var_type, "location": location,
        "initial_value": "FALSE", "description": "", "state": state, "llm_allowed": True
    }


def _full_bench_payload() -> dict[str, Any]:
    """24 canales: 8 DI + 8 DO + 4 AI + 4 AO (seccion 13/15)."""
    variables = [
        _variable("I_Start", "%IX16.0", "LOCKED"),
        _variable("I_Stop", "%IX16.1", "LOCKED"),
        _variable("I_Reset", "%IX16.2", "ASSIGNED"),
        _variable("I_Aux", "%IX16.3", "ASSIGNED"),
    ]
    for bit in range(4, 8):
        variables.append(_variable(f"I_Free{bit}", f"%IX16.{bit}", "FREE"))
    variables += [
        _variable("Q_Lamp", "%QX8.0", "ASSIGNED", var_class="output"),
        _variable("Q_Aux", "%QX8.1", "ASSIGNED", var_class="output"),
    ]
    for bit in range(2, 8):
        variables.append(_variable(f"Q_Free{bit}", f"%QX8.{bit}", "FREE", var_class="output"))
    for index, word in enumerate((0, 2, 4, 6)):
        variables.append(_variable(f"AI_IW{word}", f"%IW{word}", "FREE", var_type="INT"))
    for index, word in enumerate((0, 2, 4, 6)):
        variables.append(_variable(f"AO_QW{word}", f"%QW{word}", "FREE", var_class="output", var_type="INT"))
    return {
        "schema_version": 1,
        "metadata": {"map_id": "mapa_test_inventory", "name": "MAPA_TEST_INVENTORY", "version": 1},
        "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_", "auxiliary": "R_"},
        "variables": variables
    }


@pytest.fixture
def temp_map(app, tmp_path, monkeypatch):
    payload = _full_bench_payload()
    map_path = tmp_path / "mapa_test_inventory.json"
    map_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    original_path = app.io_map_path
    app.io_map_path = map_path
    app.io_variables = gui.load_io_map_variables(map_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    app.active_trial = None
    app.active_profile_id = None
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    yield map_path
    app.io_map_path = original_path
    # Ver test_autonomous_resource_resolution.py::temp_map - sin recargar io_variables/io_tree
    # desde el mapa real, el `app` compartido (session-scoped) queda apuntando al path correcto
    # pero mostrando el inventario pequeno de este test, y un save_io_map() posterior de otro
    # test sobreescribiria el mapa real con ese inventario obsoleto.
    app.io_variables = gui.load_io_map_variables(original_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    app.active_trial = None
    app.active_profile_id = None
    app.command_textbox.delete("1.0", "end")
    app.pending_semantic_output = None


def _two_motor_output(io_map: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "intent_id": "INT_MUTUAL_INTERLOCK",
        "case_id": None,
        "command_text": "dos motores",
        "normalized_command": "dos motores",
        "parameters": {
            "trigger_input": "I_Start_Motor_1", "stop_input": "I_Start_Motor_2",
            "contactor_a": "Q_Motor_1", "contactor_b": "Q_Motor_2"
        },
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start_Motor_1", "I_Start_Motor_2", "Q_Motor_1", "Q_Motor_2"],
        "unrecognized_terms": []
    }
    payload["semantic_validation"] = validate_semantic_output(payload, io_map, {"INT_MUTUAL_INTERLOCK": {}}, {})
    return payload


def _load(map_path: Path) -> dict[str, Any]:
    return json.loads(map_path.read_text(encoding="utf-8"))


# ---------- Section 15/16: channel count and address-set identity ----------

def test_channel_count_unchanged_after_map_config_command(app, temp_map, monkeypatch):
    before = _load(temp_map)
    assert len(before["variables"]) == 24

    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: _two_motor_output(before))
    app.command_textbox.insert("1.0", "dos motores independientes")
    app.process_command()

    after = _load(temp_map)
    assert len(after["variables"]) == 24


def test_address_set_identical_before_and_after(app, temp_map, monkeypatch):
    before = _load(temp_map)
    addresses_before = {v["location"] for v in before["variables"]}

    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: _two_motor_output(before))
    app.command_textbox.insert("1.0", "dos motores independientes")
    app.process_command()

    after = _load(temp_map)
    addresses_after = {v["location"] for v in after["variables"]}
    assert addresses_before == addresses_after


# ---------- Section 17: an unused channel stays present, FREE ----------

def test_unused_channel_stays_present_and_free(app, temp_map, monkeypatch):
    before = _load(temp_map)
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: _two_motor_output(before))
    app.command_textbox.insert("1.0", "dos motores independientes")
    app.process_command()

    after = _load(temp_map)
    by_address = {v["location"]: v for v in after["variables"]}
    assert "%IX16.7" in by_address
    assert by_address["%IX16.7"]["state"] == "FREE"


# ---------- Section 18: analog channels survive a purely digital command ----------

def test_analog_channels_survive_a_digital_only_command(app, temp_map, monkeypatch):
    before = _load(temp_map)
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: _two_motor_output(before))
    app.command_textbox.insert("1.0", "dos motores independientes")
    app.process_command()

    after = _load(temp_map)
    names_after = {v["name"] for v in after["variables"]}
    for word in (0, 2, 4, 6):
        assert f"AI_IW{word}" in names_after
        assert f"AO_QW{word}" in names_after


# ---------- LOCKED entries stay exactly as they were ----------

def test_locked_entries_untouched(app, temp_map, monkeypatch):
    before = _load(temp_map)
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: _two_motor_output(before))
    app.command_textbox.insert("1.0", "dos motores independientes")
    app.process_command()

    after = _load(temp_map)
    by_address = {v["location"]: v for v in after["variables"]}
    assert by_address["%IX16.0"]["name"] == "I_Start"
    assert by_address["%IX16.0"]["state"] == "LOCKED"
    assert by_address["%IX16.1"]["name"] == "I_Stop"
    assert by_address["%IX16.1"]["state"] == "LOCKED"


# ---------- Only the targeted channels actually changed ----------

def before_by_address_states(io_map):
    return [(v["location"], v["name"], v["state"]) for v in io_map["variables"]]


def test_only_targeted_channels_change_name_or_state(app, temp_map, monkeypatch):
    """
    Solo los 4 canales realmente reclamados por el allocator cambian - todo lo demas queda
    identico. No se asume CUALES 4 (el allocator prefiere FREE sobre reasignar ASSIGNED, seccion
    18 de una tarea anterior; con FREE disponible en %IX16.4/.5 y %QX8.2/.3, esos son los
    elegidos, no I_Reset/I_Aux/Q_Lamp/Q_Aux) - lo que importa aqui es que sean EXACTAMENTE 4 y que
    el resto del inventario, LOCKED incluido, no se toque.
    """
    before = _load(temp_map)
    before_by_address = {v["location"]: (v["name"], v["state"]) for v in before["variables"]}

    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: _two_motor_output(before))
    app.command_textbox.insert("1.0", "dos motores independientes")
    app.process_command()

    # Modo Normal transaccional: la asignacion es PROVISIONAL hasta que el programa se genera y verifica;
    # el archivo no cambia todavia y la seleccion de canales se comprueba sobre la copia provisional.
    assert {(v["location"], v["name"], v["state"]) for v in _load(temp_map)["variables"]} == set(before_by_address_states(before))
    after = app._pending_map_transaction["map"]
    after_by_address = {v["location"]: (v["name"], v["state"]) for v in after["variables"]}

    renamed = {address for address in before_by_address if before_by_address[address][0] != after_by_address[address][0]}
    assert len(renamed) == 4  # solo los 4 canales que el nuevo programa usa cambian de funcion
    assert "%IX16.0" not in renamed and "%IX16.1" not in renamed  # LOCKED, nunca tocados
    assert after_by_address["%IX16.0"] == before_by_address["%IX16.0"] and after_by_address["%IX16.1"] == before_by_address["%IX16.1"]
    # Programa NUEVO: los ASSIGNED automaticos del programa anterior que no se reutilizan vuelven a FREE (mismo
    # nombre, misma configuracion fisica); ningun otro canal cambia.
    for address, (name, state) in before_by_address.items():
        if address in renamed or after_by_address[address] == (name, state):
            continue
        assert (state, after_by_address[address]) == ("ASSIGNED", (name, "FREE")), address


# ---------- Full Mapa I/O completo window reflects the complete inventory ----------

def test_full_map_window_shows_all_channels_after_command(app, temp_map, monkeypatch):
    before = _load(temp_map)
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: _two_motor_output(before))
    app.command_textbox.insert("1.0", "dos motores independientes")
    app.process_command()

    window = gui.FullIOMapWindow(app)
    try:
        assert len(window.tree.get_children()) == 24
    finally:
        window.destroy()
