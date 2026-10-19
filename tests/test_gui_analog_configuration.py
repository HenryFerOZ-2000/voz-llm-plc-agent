from __future__ import annotations

import json

import pytest

import gui
from test_analog_configuration import configured_channel
from test_gui_full_map_window import temp_map  # noqa: F401


def set_up_analog(dialog, *, output=False, confirmed=True):
    dialog._on_kind_changed("Salida analógica (AO)" if output else "Entrada analógica (AI)")
    dialog.name_var.set("AO_Valve" if output else "AI_Level")
    dialog.location_var.set("QW4" if output else "IW4")
    panel = dialog.analog_panel
    panel.enabled_var.set(True)
    for field, value in configured_channel(output)["analog_config"].items():
        if field == "schema_version":
            continue
        panel.variables[field].set("" if value is None else value)
    panel.variables["confirmed"].set(confirmed)
    return panel


def test_gui_creates_a_configured_current_sensor(app):
    dialog = gui.VariableEditorDialog(app, "Nueva")
    panel = set_up_analog(dialog)
    dialog._confirm()
    try:
        assert dialog.result is not None
        assert dialog.result["analog_config"] == configured_channel()["analog_config"]
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_signal_preset_never_guesses_the_raw_range(app):
    dialog = gui.VariableEditorDialog(app, "Nueva")
    try:
        panel = set_up_analog(dialog, confirmed=False)
        panel.variables["raw_min"].set("")
        panel.variables["raw_max"].set("")
        panel._on_signal_changed("4-20mA")
        assert float(panel.variables["electrical_min"].get()) == 4
        assert float(panel.variables["electrical_max"].get()) == 20
        assert panel.variables["raw_min"].get() == panel.variables["raw_max"].get() == ""
        dialog._confirm()
        assert dialog.result["analog_config"]["raw_max"] is None
        assert dialog.result["analog_config"]["confirmed"] is False
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


@pytest.mark.parametrize("field,value", [("raw_max", ""), ("engineering_max", "bad"), ("raw_min", "nan")])
def test_incomplete_confirmed_or_malformed_configuration_stays_open(app, field, value):
    dialog = gui.VariableEditorDialog(app, "Nueva")
    try:
        panel = set_up_analog(dialog)
        panel.variables[field].set(value)
        panel.variables["confirmed"].set(True)
        dialog._confirm()
        assert dialog.result is None
        assert dialog.error_var.get()
        assert dialog.winfo_exists()
    finally:
        dialog.destroy()


def test_analog_configuration_survives_full_and_main_window_round_trip(app, temp_map, monkeypatch):
    window = gui.FullIOMapWindow(app)
    def complete(dialog):
        set_up_analog(dialog, output=True)
        dialog._confirm()
    monkeypatch.setattr(window, "wait_window", complete)
    try:
        window.add_variable()
        assert app.save_io_map(show_success=False)
        saved = json.loads(temp_map.read_text(encoding="utf-8"))
        channel = next(v for v in saved["variables"] if v["name"] == "AO_Valve")
        assert channel["analog_config"] == configured_channel(True)["analog_config"]
    finally:
        window.destroy()


def test_main_panel_edit_carries_configuration_to_new_address(app, temp_map, monkeypatch):
    payload = json.loads(temp_map.read_text(encoding="utf-8"))
    payload["variables"].append(configured_channel())
    temp_map.write_text(json.dumps(payload), encoding="utf-8")
    app.io_variables = gui.load_io_map_variables(temp_map)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    item = next(item for item in app.io_tree.get_children() if app.io_tree.item(item, "values")[0] == "AI_Level")
    app.io_tree.selection_set(item)
    def edit_dialog(_title, data):
        assert data["analog_config"] == configured_channel()["analog_config"]
        return {**data, "location": "%IW6"}
    monkeypatch.setattr(app, "_run_variable_dialog", edit_dialog)
    try:
        app.edit_variable()
        assert app.save_io_map(show_success=False)
        saved = json.loads(temp_map.read_text(encoding="utf-8"))
        channel = next(v for v in saved["variables"] if v["location"] == "%IW6")
        assert channel["analog_config"] == configured_channel()["analog_config"]
    finally:
        app.active_map_dirty = False


def test_editing_device_parameters_clears_previous_confirmation(app):
    dialog = gui.VariableEditorDialog(app, "Editar", configured_channel())
    try:
        panel = dialog.analog_panel
        assert panel.variables["confirmed"].get()
        panel.variables["engineering_max"].set("200")
        assert not panel.variables["confirmed"].get()
    finally:
        dialog.destroy()


def test_changing_the_physical_address_requires_confirmation_again(app):
    dialog = gui.VariableEditorDialog(app, "Editar", configured_channel())
    try:
        assert dialog.analog_panel.variables["confirmed"].get()
        dialog.location_var.set("IW6")
        assert not dialog.analog_panel.variables["confirmed"].get()
    finally:
        dialog.destroy()
