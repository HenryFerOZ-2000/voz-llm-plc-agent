from __future__ import annotations

import pytest

import gui
from gui_helpers import load_io_map_variables
from plc_maps.store import save_plc_map
from test_analog_configuration import configured_channel


@pytest.fixture
def unit_dialog(app):
    entry = configured_channel(output=True)
    entry["analog_config"].update(quantity="Nivel", engineering_unit="cm", engineering_max=200, fault_value=20)
    dialog = gui.VariableEditorDialog(app, "Editar", entry)
    yield dialog
    if dialog.winfo_exists():
        dialog.destroy()


def test_unit_selector_offers_only_compatible_units(unit_dialog):
    panel = unit_dialog.analog_panel
    assert "cm" in panel.unit_menu.cget("values")
    assert "bar" not in panel.unit_menu.cget("values")


def test_changing_centimeters_to_meters_converts_limits_and_safe_value(unit_dialog):
    panel = unit_dialog.analog_panel
    panel._on_unit_selected("m")
    config = panel.read_configuration()
    assert (config["engineering_min"], config["engineering_max"], config["fault_value"]) == (0, 2, 0.2)
    assert config["engineering_unit"] == "m"
    assert (config["raw_min"], config["raw_max"]) == (0, 27648)
    assert (config["electrical_min"], config["electrical_max"]) == (4, 20)
    assert not config["confirmed"]
    unit_dialog._confirm()
    assert unit_dialog.result["analog_config"]["fault_value"] == 0.2


def test_percentage_to_distance_requires_new_physical_range(unit_dialog):
    panel = unit_dialog.analog_panel
    panel._on_unit_selected("%")
    config = panel.read_configuration()
    assert config["engineering_min"] is None and config["engineering_max"] is None
    assert config["fault_value"] is None
    assert not config["confirmed"]
    assert panel.unit_notice_var.get()


def test_temperature_offset_conversion_includes_fault_value(unit_dialog):
    panel = unit_dialog.analog_panel
    panel._on_quantity_selected("Temperatura")
    panel._on_unit_selected("°C")
    for field, value in [("engineering_min", "0"), ("engineering_max", "100"), ("fault_value", "25")]:
        panel.variables[field].set(value)
    panel._on_unit_selected("°F")
    config = panel.read_configuration()
    assert config["engineering_min"] == pytest.approx(32)
    assert config["engineering_max"] == pytest.approx(212)
    assert config["fault_value"] == pytest.approx(77)


def test_quantity_change_clears_old_physical_calibration(unit_dialog):
    panel = unit_dialog.analog_panel
    panel._on_quantity_selected("Presión")
    config = panel.read_configuration()
    assert "bar" in panel.unit_menu.cget("values")
    assert config["engineering_min"] is None and config["engineering_max"] is None
    assert config["fault_value"] is None
    assert not config["confirmed"]


def test_custom_unit_edit_cannot_silently_relabel_existing_limits(unit_dialog):
    panel = unit_dialog.analog_panel
    panel._on_unit_selected(panel.CUSTOM_CHOICE)
    panel.variables["engineering_unit"].set("Unidad especial")
    config = panel.read_configuration()
    assert config["engineering_unit"] == "Unidad especial"
    assert config["engineering_max"] is None and config["fault_value"] is None


def test_legacy_unknown_units_and_metadata_survive_open_and_accept(app):
    entry = configured_channel()
    entry["analog_config"].update(quantity="Sensor especial", engineering_unit="unidades/lote", future_field={"keep": True})
    dialog = gui.VariableEditorDialog(app, "Editar", entry)
    dialog._confirm()
    try:
        assert dialog.result["analog_config"] == entry["analog_config"]
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_device_kind_selector_preserves_device_name(unit_dialog):
    panel = unit_dialog.analog_panel
    panel._on_device_selected("Válvula proporcional")
    config = panel.read_configuration()
    assert config["device_kind"] == "PROPORTIONAL_VALVE"
    assert config["device_name"] == "Valve"
    assert not config["confirmed"]


def test_converted_configuration_survives_save_and_reopen(unit_dialog, app, tmp_path):
    unit_dialog.analog_panel._on_unit_selected("m")
    unit_dialog._confirm()
    path = tmp_path / "converted.json"
    save_plc_map(path, [unit_dialog.result])
    loaded = load_io_map_variables(path)[0]
    reopened = gui.VariableEditorDialog(app, "Editar", loaded)
    reopened._confirm()
    try:
        assert reopened.result["analog_config"] == loaded["analog_config"]
        assert reopened.result["analog_config"]["engineering_max"] == 2
        assert reopened.result["analog_config"]["fault_value"] == 0.2
    finally:
        if reopened.winfo_exists():
            reopened.destroy()
