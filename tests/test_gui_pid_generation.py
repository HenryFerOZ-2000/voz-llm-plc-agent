"""Regression for native PID generation failing in the Normal GUI trace."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import gui
from ir_builder import build_project_ir
from project_packager import generate_project_package
from tank_bench_setup import prepare_tank_bench
from test_tank_bench_setup import bench
from test_process_signals import db_entry


@pytest.fixture(params=['hardware', 'db'])
def pid_case(request):
    semantic = json.loads((Path(__file__).parent / 'fixtures/pid_normal_generation_incident.json').read_text(encoding='utf-8'))
    source = prepare_tank_bench(bench())
    for index, name in enumerate(('I_Start', 'I_Stop', 'I_Reset', 'I_Emergency'), 1):
        source['variables'][index]['name'] = name
    if request.param == 'db':
        source['variables'] = source['variables'][:16] + [
            db_entry(), db_entry('M_Fill', 'MANIPULATED', 'FillCommand')]
        semantic['functional_requirements'][0].update(process_input='M_Level', control_output='M_Fill')
    return semantic, source


def test_pid_internal_resources_can_be_reported_by_normal_gui(pid_case):
    semantic, source = pid_case
    project = build_project_ir(semantic, source, 'SIEMENS_SCL_V18')
    messages = []
    gui.VozLLMPLCGUI._trace_normal_ir(SimpleNamespace(_log=messages.append), project.to_dict())
    assert any('NORMAL_INTERNAL_RESOURCES' in message and 'CmdStart' in message for message in messages)


def test_normal_gui_generates_and_displays_pid_package(app, pid_case, tmp_path, monkeypatch, intents_catalog, safety_rules):
    semantic, source = pid_case
    before = copy.deepcopy(source)
    errors, snapshots = [], []
    monkeypatch.setattr(gui.messagebox, 'showerror', lambda title, message: errors.append(message))
    monkeypatch.setattr(gui, 'generate_project_package',
                        lambda **kw: generate_project_package(**kw, output_dir=tmp_path / 'packages'))
    monkeypatch.setattr(app, '_record_history', lambda snapshot, **kw: snapshots.append(snapshot))
    monkeypatch.setattr(app, 'docs_dir', tmp_path / 'docs')
    monkeypatch.setattr(app, 'pending_semantic_output', semantic)
    monkeypatch.setattr(app, 'pending_runtime_config', (source, intents_catalog, safety_rules))
    monkeypatch.setattr(app, 'active_trial', None)
    monkeypatch.setattr(app, '_pending_map_transaction', None)
    app.work_mode_var.set('Normal')
    app.platform_var.set('Siemens TIA V18')
    assert app.generate_package(), errors
    assert errors == []
    assert snapshots[-1]['validation_ok'] is True
    result = snapshots[-1]['combined_results']['SIEMENS_SCL_V18']['package_result']
    assert result['verification']['is_valid'], result['verification']
    assert Path(result['artifacts']['package_dir'], 'pid_infrastructure.json').is_file()
    assert source == before
