import json
from pathlib import Path

import pytest

from gui_helpers import load_io_map_variables
from io_variable_editor import VariableEditorDialog
from plc_maps.store import save_plc_map
from test_process_signals import db_entry


def test_db_kind_selects_real_and_hides_address(app):
    dialog = VariableEditorDialog(app, 'Nueva señal')
    try:
        dialog._on_kind_changed('Señal de proceso en DB')
        assert dialog.type_var.get() == 'REAL'
        assert dialog.location_entry.cget('state') == 'disabled'
        assert dialog.location_var.get() == ''
        dialog.name_var.set('M_Level')
        panel = dialog.process_panel
        for key, value in {'db': 'DB_TankProcess', 'member': 'Level', 'validity_member': 'LevelValid',
                           'engineering_min': '0', 'engineering_max': '100'}.items():
            panel.variables[key].set(value)
        dialog._confirm()
        assert dialog.result is not None, dialog.error_var.get()
        assert dialog.result['process_config']['role'] == 'MEASUREMENT'
        assert 'analog_config' not in dialog.result
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_process_editor_roundtrip_and_units(app, tmp_path):
    entry = db_entry()
    entry['llm_allowed'] = False
    entry['process_config'].update(engineering_unit='cm', engineering_max=200)
    dialog = VariableEditorDialog(app, 'Editar señal', entry)
    try:
        panel = dialog.process_panel
        assert 'm' in panel.unit_menu.cget('values')
        assert 'bar' not in panel.unit_menu.cget('values')
        panel._on_unit_selected('m')
        config = panel.get_config()
        assert config['engineering_max'] == 2.0
        assert config['engineering_unit'] == 'm'
        dialog._confirm()
        assert dialog.result is not None, dialog.error_var.get()
        assert dialog.result['llm_allowed'] is False
        path = tmp_path / 'map.json'
        save_plc_map(path, [dialog.result])
        assert load_io_map_variables(path)[0]['process_config'] == config
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_example_does_not_change_active_map(project_root):
    paths = [project_root/'config/io_map.json', project_root/'data/plc_maps/mapa_banco_fisico_working.json']
    before = {p: p.read_bytes() for p in paths if p.exists()}
    example = project_root/'data/plc_maps/examples/pid_tank_db.json'
    assert example.is_file()
    variables = load_io_map_variables(example)
    configs = [v['process_config'] for v in variables if 'process_config' in v]
    assert len(configs) == 2
    assert {c['storage']['member'] for c in configs} == {'Level', 'FillCommand'}
    assert all(c['storage']['db'] == 'DB_TankProcess' for c in configs)
    assert all(path.read_bytes() == content for path, content in before.items())
