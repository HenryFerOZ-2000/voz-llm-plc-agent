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

# The shared `app` fixture (one Tk root for the whole pytest session) lives in conftest.py.


def _temp_map_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "metadata": {"map_id": "mapa_test_full_window", "name": "MAPA_TEST_FULL_WINDOW", "version": 1},
        "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_", "auxiliary": "R_"},
        "variables": [
            {
                "name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX16.0",
                "initial_value": "FALSE", "description": "Inicio", "state": "LOCKED", "llm_allowed": True
            },
            {
                "name": "Q_Alarm", "class": "output", "type": "BOOL", "location": "%QX8.1",
                "initial_value": "FALSE", "description": "Alarma", "state": "ASSIGNED", "llm_allowed": True
            },
            {
                "name": "Q_Free1", "class": "output", "type": "BOOL", "location": "%QX8.0",
                "initial_value": "FALSE", "description": "Disponible", "state": "FREE", "llm_allowed": True
            }
        ]
    }


@pytest.fixture
def temp_map(app, tmp_path, monkeypatch):
    map_path = tmp_path / "mapa_test_full_window.json"
    map_path.write_text(json.dumps(_temp_map_payload(), indent=2), encoding="utf-8")
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


def test_free_channel_displays_dash_not_placeholder_name(app, temp_map):
    window = gui.FullIOMapWindow(app)
    try:
        values = window.tree.item("%QX8.0", "values")
        name_column_index = window.COLUMNS.index("name")
        assert values[name_column_index] == "—"
    finally:
        window.destroy()


def test_rename_via_window_persists_and_refreshes_main_app(app, temp_map, monkeypatch):
    window = gui.FullIOMapWindow(app)
    try:
        window.tree.selection_set("%QX8.1")
        monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: "Q_Motor_2")

        window.edit_name()

        saved = json.loads(temp_map.read_text(encoding="utf-8"))
        variable = next(v for v in saved["variables"] if v["location"] == "%QX8.1")
        assert variable["name"] == "Q_Motor_2"

        # La ventana Y el panel izquierdo de la app principal quedan sincronizados de inmediato.
        window_values = window.tree.item("%QX8.1", "values")
        assert window_values[window.COLUMNS.index("name")] == "Q_Motor_2"
        assert any(v["name"] == "Q_Motor_2" for v in app.io_variables)
    finally:
        window.destroy()


def test_rename_locked_channel_is_refused(app, temp_map, monkeypatch):
    window = gui.FullIOMapWindow(app)
    try:
        window.tree.selection_set("%IX16.0")
        called = {"value": False}
        monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: called.__setitem__("value", True) or "I_Reverse")

        window.edit_name()

        assert called["value"] is False  # never even prompted - blocked before asking
        saved = json.loads(temp_map.read_text(encoding="utf-8"))
        variable = next(v for v in saved["variables"] if v["location"] == "%IX16.0")
        assert variable["name"] == "I_Start"
    finally:
        window.destroy()


def test_rename_to_duplicate_name_is_rejected(app, temp_map, monkeypatch):
    window = gui.FullIOMapWindow(app)
    try:
        window.tree.selection_set("%QX8.0")  # Q_Free1, FREE
        monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: "Q_Alarm")  # ya existe en %QX8.1

        window.edit_name()

        saved = json.loads(temp_map.read_text(encoding="utf-8"))
        variable = next(v for v in saved["variables"] if v["location"] == "%QX8.0")
        assert variable["name"] == "Q_Free1"  # sin cambio
    finally:
        window.destroy()


def test_lock_unlock_mark_free_persist_immediately(app, temp_map):
    window = gui.FullIOMapWindow(app)
    try:
        window.tree.selection_set("%QX8.1")
        window.lock_selected()
        saved = json.loads(temp_map.read_text(encoding="utf-8"))
        assert next(v for v in saved["variables"] if v["location"] == "%QX8.1")["state"] == "LOCKED"

        window.unlock_selected()
        saved = json.loads(temp_map.read_text(encoding="utf-8"))
        assert next(v for v in saved["variables"] if v["location"] == "%QX8.1")["state"] == "ASSIGNED"

        window.mark_free_selected()
        saved = json.loads(temp_map.read_text(encoding="utf-8"))
        assert next(v for v in saved["variables"] if v["location"] == "%QX8.1")["state"] == "FREE"
    finally:
        window.destroy()


def test_window_is_read_only_during_experimental_trial(app, temp_map):
    app.active_trial = {"trial_id": "T01"}
    window = gui.FullIOMapWindow(app)
    try:
        assert window.read_only_message is not None
        window.tree.selection_set("%QX8.0")
        window.mark_free_selected()  # no-op: should refuse silently (warning mocked away)
        saved = json.loads(temp_map.read_text(encoding="utf-8"))
        variable = next(v for v in saved["variables"] if v["location"] == "%QX8.0")
        assert variable["state"] == "FREE"  # unchanged (was already FREE, and nothing applied)
    finally:
        window.destroy()
        app.active_trial = None


def test_window_read_only_during_experimental_profile(app, temp_map):
    app.active_profile_id = "D01"
    window = gui.FullIOMapWindow(app)
    try:
        assert window.read_only_message is not None
    finally:
        window.destroy()
        app.active_profile_id = None


def test_save_as_preserves_previous_map(app, temp_map, tmp_path, monkeypatch):
    """window.save_as() delega en app.save_plc_map_as() (infraestructura ya existente, seccion
    18) - se sustituye por una version que escribe en tmp_path en vez de la biblioteca real de
    mapas del proyecto, para no tocar _active_map.json/data/plc_maps/ reales desde un test."""
    new_map_path = tmp_path / "mapa_motor_reversible.json"

    def fake_save_as():
        variables = app._collect_io_variables()
        new_map_path.write_text(json.dumps({"variables": variables}, indent=2), encoding="utf-8")
        app.io_map_path = new_map_path

    monkeypatch.setattr(app, "save_plc_map_as", fake_save_as)

    window = gui.FullIOMapWindow(app)
    try:
        original_variable_count = len(json.loads(temp_map.read_text(encoding="utf-8"))["variables"])

        window.save_as()

        # El mapa original (MAPA_TEST_FULL_WINDOW) sigue existiendo con su contenido intacto.
        assert temp_map.exists()
        assert len(json.loads(temp_map.read_text(encoding="utf-8"))["variables"]) == original_variable_count
        # La app ahora apunta al mapa nuevo, sin haber destruido el anterior.
        assert app.io_map_path == new_map_path
        assert new_map_path.exists()
    finally:
        window.destroy()
