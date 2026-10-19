"""Native PID may snapshot a saved, already-open template without closing it."""
import json
import subprocess
from types import SimpleNamespace

import pytest

import gui
import tia_openness as tia
from test_native_pid_package import package
from utils import get_project_root


def test_bridge_preserves_attached_template_lifecycle(tmp_path):
    built = tia.build_openness_bridge(get_project_root())
    assert built['built'], built
    request, result = tmp_path / 'request.json', tmp_path / 'result.json'
    request.write_text(json.dumps({'action': 'self_test', 'result_path': str(result)}))
    run = subprocess.run([built['exe_path'], str(request)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    checks = [c for c in json.loads(result.read_text())['checks'] if 'pid_source_case' in c]
    assert {c['pid_source_case'] for c in checks} == {
        'attached_saved', 'attached_unsaved', 'owned_saved', 'attached_archive_error', 'owned_archive_error'}
    assert all(c['passed'] for c in checks), checks


@pytest.mark.parametrize('attach', [True, False])
def test_normal_import_respects_configured_session_attachment(tmp_path, intents_catalog, safety_rules, monkeypatch, attach):
    directory = package(tmp_path, intents_catalog, safety_rules)
    config = tia.load_tia_config()
    monkeypatch.setattr(tia, 'load_tia_config', lambda root: {**config, 'attach_to_running': attach})
    _, _, request = tia.prepare_tia_request(directory)
    assert request['pid_archive_attach_to_running'] is attach
    assert request['attach_to_running'] is attach
    assert request['pid_project_mode'] == 'NORMAL_PROJECT'
    assert request['physical_download_allowed'] is False


@pytest.mark.parametrize('report, phrase', [
    ({'status': 'TIA_PROJECT_OPEN_FAILED', 'errors': ['It has already been opened by user TEST']}, 'abierto'),
    ({'status': 'PID_TEMPLATE_UNSAVED_CHANGES'}, 'guarde'),
    ({'status': 'TIA_OPENNESS_ERROR', 'errors': ['Openness unavailable']}, 'no se pudo'),
    ({'status': 'TIA_COMPILATION_FAILED', 'error_count': 2}, 'errores de compilacion'),
    ({'status': 'TIA_COMPILATION_PASSED', 'error_count': 0}, 'aprobada'),
])
def test_gui_explains_project_access_failures_separately_from_compiler_errors(report, phrase):
    app = SimpleNamespace(_build_files_summary=lambda files: '', _build_export_contents=lambda **kw: {})
    snapshot = {}
    gui.VozLLMPLCGUI._apply_tia_report_to_snapshot(app, snapshot, report)
    assert phrase in snapshot['validation_text'].lower()
    assert snapshot['validation_ok'] == (report['status'] == 'TIA_COMPILATION_PASSED')
