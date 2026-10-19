import json
import threading
from pathlib import Path

import pytest

from test_pid_plant_io import compiled, session_for_peer  # noqa: F401
from test_process_signals import db_entry


def profile(**changes):
    return dict(schema_version=1, model='TANK', initial_percent=20.0, fill_percent_per_s=2.0,
                drain_percent_per_s=.8, period_s=.1, duration_s=.25, **changes)


def test_profile_units_and_quantized_roundtrip():
    from pid_tank_model import TankModel
    inp = dict(engineering_min=0.0, engineering_max=200.0, unit='cm')
    out = dict(engineering_min=0.0, engineering_max=100.0, unit='%')
    model = TankModel(profile(), inp, out)
    assert model.level == 40.0
    assert model.step(100.0, 1.0) == pytest.approx(42.4)
    assert model.step(40.0, 10.0) == pytest.approx(42.4)
    assert model.step(0.0, 100.0) == 0.0
    other = TankModel(profile(direction='DRAIN'), inp, out)
    assert other.step(100.0, 1.0) == pytest.approx(37.6)


def test_model_reads_actual_mapped_output_only(compiled, monkeypatch):
    import pid_plant_test as module
    session = session_for_peer(compiled, monkeypatch)
    monkeypatch.setattr(module, 'PidPlantIOSession', lambda *_a, **_k: session)
    report = module.run_tank_test(compiled[0], {}, profile(), threading.Event(), compiled[1]/'models')
    trace = [json.loads(line) for line in Path(report['evidence'],'trace.jsonl').read_text().splitlines()]
    assert len(trace) >= 2
    assert all(row['command_percent'] == 40.0 for row in trace)
    assert all(row['provided_level'] == 20.0 for row in trace)  # 40% exactly balances the outlet.
    assert trace[0]['measurement_raw'] == 5530


def test_cancel_stops_and_restores_with_valid_identity(compiled, monkeypatch):
    import pid_plant_test as module
    session = session_for_peer(compiled, monkeypatch)
    monkeypatch.setattr(module, 'PidPlantIOSession', lambda *_a, **_k: session)
    cancel = threading.Event()
    timer = threading.Timer(.3, cancel.set)
    timer.start()
    try:
        p=profile();p['duration_s']=5
        report = module.run_tank_test(compiled[0], {}, p, cancel, compiled[1]/'models')
    finally:
        timer.cancel()
    assert report['status'] == 'CANCELLED' and report['cleanup']['cleanup_verified']
    assert session.closed


def test_sensor_injection_unavailable_is_not_pass():
    from pid_plant_test import fault_injection_status
    binding = dict(representation='HARDWARE_RAW', analog_config=dict(raw_min=-32768, raw_max=32767))
    assert fault_injection_status(binding)['status'] == 'UNSUPPORTED'
    binding['analog_config']['raw_min'] = 0
    assert fault_injection_status(binding)['raw'] == -1
    config = db_entry()['process_config']
    binding = dict(representation='DB_ENGINEERING', validity_member=config['validity_member'])
    assert fault_injection_status(binding)['quality_member'] == 'LevelValid'


def test_evidence_is_unique_and_requires_native_proof(compiled, monkeypatch):
    import pid_plant_test as module
    monkeypatch.setattr(module, 'PidPlantIOSession', lambda *_a, **_k: session_for_peer(compiled, monkeypatch))
    # Avoid stacking Popen doubles between sessions; construct two sessions before the runner calls.
    first = session_for_peer(compiled, monkeypatch)
    reports=[]
    monkeypatch.setattr(module, 'PidPlantIOSession', lambda *_a, **_k: first)
    reports.append(module.run_tank_test(compiled[0], {}, profile(), threading.Event(), compiled[1]/'models'))
    assert reports[0]['native_execution_verified'] is False
    assert reports[0]['status'] != 'PASSED'
    summary = json.loads(Path(reports[0]['evidence'],'summary.json').read_text())
    assert summary['model_profile_sha256'] and summary['artifact_hashes']
    # A second attempt cancelled before opening the backend still has independent evidence.
    cancelled=threading.Event();cancelled.set()
    reports.append(module.run_tank_test(compiled[0], {}, profile(), cancelled, compiled[1]/'models'))
    assert reports[0]['evidence'] != reports[1]['evidence']


@pytest.mark.parametrize('command,dt', [(float('nan'), .1), (101.0, .1), (40.0, -1.0), (40.0, float('inf'))])
def test_model_rejects_invalid_commands_and_time(command, dt):
    from pid_tank_model import TankModel
    model = TankModel(profile(), dict(engineering_min=0,engineering_max=100,unit='%'),
                      dict(engineering_min=0,engineering_max=100,unit='%'))
    with pytest.raises(ValueError):
        model.step(command, dt)
