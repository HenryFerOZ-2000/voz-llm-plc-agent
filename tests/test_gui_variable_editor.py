from __future__ import annotations

import json

import pytest

import gui
from test_gui_full_map_window import temp_map  # noqa: F401


@pytest.fixture
def editor_window(app, temp_map):
    window = gui.FullIOMapWindow(app)
    yield window
    window.destroy()


def accept_dialog(window, monkeypatch, **fields):
    def complete(dialog):
        for name, value in fields.items():
            getattr(dialog, name + "_var").set(value)
        dialog._confirm()
        if dialog.winfo_exists():
            dialog.destroy()
    monkeypatch.setattr(window, "wait_window", complete)


def test_create_first_variable_from_full_empty_map(app, temp_map, monkeypatch):
    payload = json.loads(temp_map.read_text(encoding="utf-8"))
    payload["variables"] = []
    temp_map.write_text(json.dumps(payload), encoding="utf-8")
    window = gui.FullIOMapWindow(app)
    try:
        accept_dialog(window, monkeypatch, name="I_Start", location="I16.0")
        window.add_variable()
        saved = json.loads(temp_map.read_text(encoding="utf-8"))
        assert saved["variables"][0]["location"] == "%IX16.0"
        assert saved["variables"][0]["assignment_source"] == "MANUAL"
        assert window.tree.exists("%IX16.0")
        assert app.io_variables[0]["name"] == "I_Start"
        assert saved["metadata"]["map_id"] == payload["metadata"]["map_id"]
    finally:
        window.destroy()


def test_guided_analog_choice_limits_type_and_sets_prefix(app):
    dialog = gui.VariableEditorDialog(app, "Nueva variable")
    try:
        dialog._on_kind_changed("Entrada analógica (AI)")
        assert dialog.class_var.get() == "input"
        assert dialog.type_var.get() == "INT"
        assert dialog.type_menu.cget("values") == ["INT"]
        assert dialog.name_var.get() == "AI_"
        assert "IW" in dialog.address_hint.cget("text")
    finally:
        dialog.destroy()


@pytest.mark.parametrize("name,location", [("I_Start", "I16.2"), ("I_Other", "I16.0"), ("I_Other", "I16.9")])
def test_invalid_variable_keeps_dialog_open(app, temp_map, name, location):
    dialog = gui.VariableEditorDialog(app, "Nueva", other_variables=gui.load_io_map_variables(temp_map))
    try:
        dialog.name_var.set(name)
        dialog.location_var.set(location)
        dialog._confirm()
        assert dialog.result is None
        assert dialog.winfo_exists()
        assert dialog.error_var.get()
    finally:
        dialog.destroy()


def test_analog_overlap_rejected_in_dialog(app, temp_map):
    dialog = gui.VariableEditorDialog(app, "Nueva", other_variables=gui.load_io_map_variables(temp_map))
    try:
        dialog._on_kind_changed("Salida analógica (AO)")
        dialog.name_var.set("AO_Valve")
        dialog.location_var.set("QW8")
        dialog._confirm()
        assert dialog.result is None
        assert "Solapamiento" in dialog.error_var.get()
    finally:
        dialog.destroy()


def test_edit_preserves_device_metadata(editor_window, temp_map, monkeypatch):
    payload = json.loads(temp_map.read_text(encoding="utf-8"))
    payload["variables"][1]["device_config"] = {"future_field": "keep"}
    temp_map.write_text(json.dumps(payload), encoding="utf-8")
    editor_window._reload()
    editor_window.tree.selection_set("%QX8.1")
    accept_dialog(editor_window, monkeypatch, description="Nueva descripcion", location="Q8.2")
    editor_window.edit_variable()
    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    edited = next(v for v in saved["variables"] if v["name"] == "Q_Alarm")
    assert edited["device_config"] == {"future_field": "keep"}
    assert edited["location"] == "%QX8.2"
    assert edited["description"] == "Nueva descripcion"


def test_duplicate_requires_new_address_and_preserves_original(editor_window, temp_map, monkeypatch):
    editor_window.tree.selection_set("%QX8.1")
    def complete(dialog):
        assert dialog.location_var.get() == ""
        dialog.name_var.set("Q_Alarm_Copy")
        dialog.location_var.set("Q8.3")
        dialog._confirm()
    monkeypatch.setattr(editor_window, "wait_window", complete)
    editor_window.duplicate_variable()
    saved = json.loads(temp_map.read_text(encoding="utf-8"))["variables"]
    assert len(saved) == 4
    assert next(v for v in saved if v["name"] == "Q_Alarm")["location"] == "%QX8.1"
    assert next(v for v in saved if v["name"] == "Q_Alarm_Copy")["location"] == "%QX8.3"


@pytest.mark.parametrize("method", ["edit_variable", "delete_variable"])
def test_locked_variable_cannot_be_modified(editor_window, temp_map, monkeypatch, method):
    before = temp_map.read_bytes()
    editor_window.tree.selection_set("%IX16.0")
    monkeypatch.setattr(editor_window, "wait_window", lambda *_: pytest.fail("Locked editor opened"))
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *_a, **_k: pytest.fail("Locked delete prompted"))
    getattr(editor_window, method)()
    assert temp_map.read_bytes() == before


def test_delete_requires_confirmation(editor_window, temp_map, monkeypatch):
    editor_window.tree.selection_set("%QX8.1")
    before = temp_map.read_bytes()
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *_a, **_k: False)
    editor_window.delete_variable()
    assert temp_map.read_bytes() == before
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *_a, **_k: True)
    editor_window.delete_variable()
    assert not editor_window.tree.exists("%QX8.1")
    assert len(json.loads(temp_map.read_text(encoding="utf-8"))["variables"]) == 2


def test_two_internal_variables_have_independent_rows(app, temp_map):
    payload = json.loads(temp_map.read_text(encoding="utf-8"))
    payload["variables"] = [dict(name=name, type="BOOL", **{"class": "internal"}, location="")
                            for name in ("M_First", "M_Second")]
    temp_map.write_text(json.dumps(payload), encoding="utf-8")
    window = gui.FullIOMapWindow(app)
    try:
        assert len(window.tree.get_children()) == 2
        window.tree.selection_set("name:M_Second")
        window.lock_selected()
        saved = json.loads(temp_map.read_text(encoding="utf-8"))["variables"]
        assert saved[0].get("state", "ASSIGNED") == "ASSIGNED"
        assert saved[1]["state"] == "LOCKED"
    finally:
        window.destroy()


@pytest.mark.parametrize("method", ["add_variable", "edit_variable", "duplicate_variable", "delete_variable"])
def test_experiment_blocks_full_map_crud(editor_window, app, temp_map, monkeypatch, method):
    before = temp_map.read_bytes()
    app.active_trial = {"trial_id": "T01"}
    editor_window.tree.selection_set("%QX8.1")
    monkeypatch.setattr(editor_window, "wait_window", lambda *_: pytest.fail("Trial allowed editor"))
    try:
        getattr(editor_window, method)()
        assert temp_map.read_bytes() == before
    finally:
        app.active_trial = None


@pytest.mark.parametrize("kind,name,type_name,location,initial", [
    ("Entrada digital (DI)", "I_Sensor", "BOOL", "I17.0", "FALSE"),
    ("Salida digital (DO)", "Q_Motor", "BOOL", "Q9.0", "FALSE"),
    ("Entrada analógica (AI)", "AI_Level", "INT", "IW0", "0"),
    ("Salida analógica (AO)", "AO_Valve", "INT", "QW0", "0"),
    ("Memoria interna", "M_Ready", "BOOL", "", "FALSE"),
    ("Temporizador", "T_Delay", "TON", "", ""),
    ("Temporizador", "T_Pulse", "TP", "", ""),
    ("Contador", "C_Cycles", "CTU", "", ""),
    ("Detector de flanco", "R_Start", "R_TRIG", "", ""),
    ("Detector de flanco", "F_Stop", "F_TRIG", "", ""),
])
def test_supported_kinds_create_valid_entries(app, kind, name, type_name, location, initial):
    dialog = gui.VariableEditorDialog(app, "Nueva")
    dialog._on_kind_changed(kind)
    dialog.name_var.set(name)
    dialog.type_var.set(type_name)
    dialog.location_var.set(location)
    dialog._confirm()
    try:
        assert dialog.result is not None
        assert dialog.result["initial_value"] == initial
        assert dialog.result["type"] == type_name
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


@pytest.mark.parametrize("field,value", [("min", "abc"), ("max", "nan"), ("initial_value", "32768")])
def test_analog_invalid_numeric_fields_are_not_silently_discarded(app, field, value):
    dialog = gui.VariableEditorDialog(app, "Nueva")
    try:
        dialog._on_kind_changed("Entrada analógica (AI)")
        dialog.name_var.set("AI_Level")
        dialog.location_var.set("IW0")
        getattr(dialog, field + "_var").set(value)
        dialog._confirm()
        assert dialog.result is None
        assert dialog.error_var.get()
    finally:
        dialog.destroy()


def test_external_change_is_not_overwritten(editor_window, temp_map, monkeypatch):
    editor_window.tree.selection_set("%QX8.1")
    def complete(dialog):
        payload = json.loads(temp_map.read_text(encoding="utf-8"))
        payload["variables"][1]["description"] = "Edited elsewhere"
        temp_map.write_text(json.dumps(payload), encoding="utf-8")
        dialog.description_var.set("Stale edit")
        dialog._confirm()
    monkeypatch.setattr(editor_window, "wait_window", complete)
    editor_window.edit_variable()
    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    assert saved["variables"][1]["description"] == "Edited elsewhere"


def test_cancel_does_not_write(editor_window, temp_map, monkeypatch):
    before = temp_map.read_bytes()
    monkeypatch.setattr(editor_window, "wait_window", lambda d: d._cancel())
    editor_window.add_variable()
    assert temp_map.read_bytes() == before


def test_new_map_edit_invalidates_previous_compilation(editor_window, app, temp_map, monkeypatch):
    previous = app._last_compiled_package_dir
    app._last_compiled_package_dir = temp_map.parent
    accept_dialog(editor_window, monkeypatch, name="I_New", location="I16.7")
    try:
        editor_window.add_variable()
        assert app._last_compiled_package_dir is None
        assert app.download_plc_button.cget("state") == "disabled"
    finally:
        app._last_compiled_package_dir = previous


def test_pending_main_panel_edits_are_not_discarded(editor_window, app, temp_map, monkeypatch):
    before = temp_map.read_bytes()
    monkeypatch.setattr(app, "active_map_dirty", True)
    monkeypatch.setattr(editor_window, "wait_window", lambda *_: pytest.fail("Opened with unsaved edits"))
    editor_window.add_variable()
    assert temp_map.read_bytes() == before


def test_quick_rename_invalidates_previous_compilation(editor_window, app, temp_map, monkeypatch):
    previous = app._last_compiled_package_dir
    app._last_compiled_package_dir = temp_map.parent
    editor_window.tree.selection_set("%QX8.1")
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *_a, **_k: "Q_NewAlarm")
    try:
        editor_window.edit_name()
        assert app._last_compiled_package_dir is None
    finally:
        app._last_compiled_package_dir = previous


def test_save_does_not_restore_stale_map(editor_window, temp_map):
    payload = json.loads(temp_map.read_text(encoding="utf-8"))
    payload["variables"][1]["description"] = "External edit"
    temp_map.write_text(json.dumps(payload), encoding="utf-8")
    editor_window.save()
    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    assert saved["variables"][1]["description"] == "External edit"


@pytest.mark.parametrize("cls,type_name,name", [
    ("timer", "TON", "T_Delay"), ("timer", "TP", "T_Pulse"), ("counter", "CTU", "C_Cycles"),
    ("auxiliary", "R_TRIG", "R_Start"), ("auxiliary", "F_TRIG", "F_Stop"),
])
def test_existing_block_without_optional_initial_value_is_editable(app, cls, type_name, name):
    dialog = gui.VariableEditorDialog(app, "Editar", {"name": name, "class": cls, "type": type_name, "location": ""})
    dialog.description_var.set("Descripcion actualizada")
    dialog._confirm()
    try:
        assert dialog.result is not None
        assert dialog.result["initial_value"] == ""
        assert dialog.result["description"] == "Descripcion actualizada"
    finally:
        if dialog.winfo_exists():
            dialog.destroy()
