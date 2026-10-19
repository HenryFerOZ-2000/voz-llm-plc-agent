import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_native_pid_package import package
from test_pid_manifest_v2 import compiled_package


@pytest.fixture
def compiled(tmp_path, intents_catalog, safety_rules):
    path = package(tmp_path, intents_catalog, safety_rules)
    compiled_package(path, tmp_path)
    return path, tmp_path


def session_for_peer(compiled, monkeypatch, scenario='ok'):
    import pid_plant_io as module
    package_dir, root = compiled
    original = subprocess.Popen
    peer = Path(__file__).parent/'fixtures/pid_plant_protocol_peer.py'
    monkeypatch.setattr(module, 'get_project_root', lambda: root)
    monkeypatch.setattr(module.plcsim_runtime, 'build_runtime_bridge', lambda *_a, **_k: {'built': True, 'exe_path': 'bridge.exe'})
    monkeypatch.setenv('PID_IO_TEST_SCENARIO', scenario)
    monkeypatch.setattr(module.subprocess, 'Popen', lambda command, **kwargs: original(
        [sys.executable, '-u', str(peer), command[-1]], **kwargs))
    return module.PidPlantIOSession(package_dir, {'target_type': 'PLCSIM_ADVANCED', 'instance_name': 'TESIS_PLC_SIM'},
                                    root/'evidence', 20)


def test_rejects_q_m_foreign_db_and_physical_target(compiled, monkeypatch):
    import pid_plant_io as module
    path, root = compiled
    monkeypatch.setattr(module, 'get_project_root', lambda: root)
    with pytest.raises(ValueError, match='PID_PLANT_TARGET'):
        module.PidPlantIOSession(path, {'target_type': 'PHYSICAL_PLC', 'instance_name': 'TESIS_PLC_SIM'}, root/'evidence', 20).start()
    manifest = json.loads((path/'pid_infrastructure.json').read_text())
    for address in ('%QW4', '%MW4'):
        bad = dict(manifest['loops'][0]['input_binding'], address=address)
        with pytest.raises(ValueError):
            module.validate_plant_binding(bad, 'MEASUREMENT', manifest)
    bad = {'representation': 'DB_ENGINEERING', 'role': 'MEASUREMENT', 'storage': {'db': 'DB_Foreign', 'member': 'PV'}}
    with pytest.raises(ValueError):
        module.validate_plant_binding(bad, 'MEASUREMENT', manifest)


def test_one_process_for_multiple_ticks_and_restored_close(compiled, monkeypatch):
    session = session_for_peer(compiled, monkeypatch)
    started = session.start()
    session.probe_input_word()
    first = session.exchange(50.0, True)
    second = session.exchange(25.0, True)
    assert first['measurement_raw'] == 13824 and second['measurement_raw'] == 6912
    assert first['peer_pid'] == second['peer_pid'] == started['peer_pid']
    assert session.close()['cleanup_verified'] is True


def test_program_change_blocks_tick_and_stale_cleanup(compiled, monkeypatch):
    session = session_for_peer(compiled, monkeypatch, 'changed')
    session.start()
    session.probe_input_word()
    with pytest.raises(ValueError, match='PID_PROGRAM_MISMATCH'):
        session.exchange(50.0, True)
    report = session.close()
    assert report['cleanup_verified'] is False and report['inputs_restored'] is False


@pytest.mark.parametrize('scenario', ['eof', 'timeout'])
def test_timeout_eof_and_cancel_capture_failed_cleanup(compiled, monkeypatch, scenario):
    import pid_plant_io as module
    monkeypatch.setattr(module, 'RESPONSE_TIMEOUT_S', .3)
    session = session_for_peer(compiled, monkeypatch, scenario)
    session.start()
    session.probe_input_word()
    start = time.monotonic()
    with pytest.raises(ValueError, match='PID_PLANT_(EOF|TIMEOUT)'):
        session.exchange(50.0, True)
    report = session.close()
    assert report['cleanup_verified'] is False
    assert time.monotonic()-start < 3
    saved = json.loads((compiled[1]/'evidence/session_report.json').read_text())
    assert saved['cleanup_verified'] is False and saved['errors']


def test_word_probe_requires_both_readbacks_and_restore(compiled, monkeypatch):
    session = session_for_peer(compiled, monkeypatch, 'bad_probe')
    session.start()
    with pytest.raises(ValueError, match='PID_WORD_PROBE_FAILED'):
        session.probe_input_word()
    with pytest.raises(ValueError, match='PID_WORD_PROBE_REQUIRED'):
        session.exchange(50.0, True)
    session.close()


def test_runtime_production_guards_have_word_and_identity_cases():
    import plcsim_runtime
    from utils import get_project_root
    report = plcsim_runtime.run_runtime_bridge('self_test', get_project_root())
    assert report['status'] == 'PLCSIM_RUNTIME_SELF_TEST_PASSED', report
    checks = {c['check']: c for c in report['checks']}
    for name in ('plant.word_input_allowed', 'plant.output_write_denied', 'plant.marker_denied',
                 'plant.foreign_db_denied', 'plant.changed_identity_denied', 'plant.physical_denied'):
        assert name in checks and checks[name]['passed']
