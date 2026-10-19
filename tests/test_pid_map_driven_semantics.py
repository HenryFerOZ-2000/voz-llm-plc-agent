import copy

import pytest

from pid_control import resolve_pid_loops
from tank_bench_setup import prepare_tank_bench
from test_native_pid_resolution import payload, request
from test_process_signals import db_entry
from test_tank_bench_setup import bench


def test_normal_policy_does_not_deny_native_pid_generation():
    from normal_interaction import NORMAL_MODE_POLICY
    assert 'la infraestructura del regulador todavía no se genera' not in NORMAL_MODE_POLICY
    assert 'pid_control' in NORMAL_MODE_POLICY


def test_legacy_llm_modes_do_not_change_native_ir():
    source = prepare_tank_bench(bench())
    loops = [resolve_pid_loops([request(mode=m)], source, 'SIEMENS_SCL_V18')[0].to_dict()
             for m in ('SIMULATION', 'PHYSICAL', None)]
    assert loops[0] == loops[1] == loops[2]
    assert 'mode' not in loops[0] and 'simulation' not in loops[0]
    assert loops[0]['input_binding']['address'] == '%IW4'
    assert loops[0]['controller']['status'] == 'UNTUNED'


def test_hardware_db_ambiguity_has_no_destination_preference():
    source = prepare_tank_bench(bench())
    source['variables'].append(db_entry())
    with pytest.raises(ValueError, match='PID_DEVICE_AMBIGUOUS'):
        resolve_pid_loops([request()], source, 'SIEMENS_SCL_V18')
    loop = resolve_pid_loops([request(process_input='M_Level')], source, 'SIEMENS_SCL_V18')[0]
    assert loop.input_binding['representation'] == 'DB_ENGINEERING'


def test_missing_resources_never_create_model():
    with pytest.raises(ValueError, match='PID_DEVICE_MISSING'):
        resolve_pid_loops([request()], {'variables': []}, 'SIEMENS_SCL_V18')


def test_units_convert_setpoint_and_overfill_once():
    source = prepare_tank_bench(bench())
    source['variables'][18]['analog_config'].update(engineering_unit='cm', engineering_max=200)
    req = request(setpoint=1, unit='m', overfill_limit=1.9)
    loop = resolve_pid_loops([req], source, 'SIEMENS_SCL_V18')[0]
    assert loop.setpoint == 100 and loop.overfill_limit == 190
    assert req['setpoint'] == 1 and req['overfill_limit'] == 1.9


def test_yes_does_not_confirm_calibration(intents_catalog, safety_rules):
    from llm_parser import _repair_and_validate
    source = prepare_tank_bench(bench())
    before = copy.deepcopy(source)
    semantic = payload(request(mode='PHYSICAL'))
    semantic['parameters']['pid_mode'] = 'PHYSICAL'
    semantic['clarification_context'] = {'answers': [{'answer': 'Sí'}]}
    parsed, validation = _repair_and_validate(semantic, source, intents_catalog, safety_rules, pid_mode='PHYSICAL')
    assert validation['is_valid'], validation
    assert source == before
    assert 'pid_mode' not in parsed['parameters']
    assert 'mode' not in parsed['functional_requirements'][0]
    assert parsed['metadata']['pid_legacy_fields_ignored']


def test_explicit_sensor_alias_is_resolved():
    source = prepare_tank_bench(bench())
    source['variables'][18]['aliases'] = ['transmisor del tanque']
    loop = resolve_pid_loops([request(process_input='transmisor del tanque')], source, 'SIEMENS_SCL_V18')[0]
    assert loop.process_input == 'AI_Level_Raw'


def test_db_storage_conflict_rejected_before_generation():
    first, second = db_entry(), db_entry('M_Fill', 'MANIPULATED', 'levelvalid')
    with pytest.raises(ValueError, match='PID_STORAGE_CONFLICT'):
        resolve_pid_loops([request()], {'variables': [first, second]}, 'SIEMENS_SCL_V18')
