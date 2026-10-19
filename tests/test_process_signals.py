import copy

import pytest

from gui_helpers import normalize_variable_entry, validate_io_map_variables
from plc_maps.map_validator import validate_plc_variable_map


def db_entry(name='M_Level', role='MEASUREMENT', member='Level'):
    config = {'schema_version': 1, 'role': role, 'quantity': 'Nivel' if role == 'MEASUREMENT' else 'Apertura',
              'engineering_unit': '%', 'engineering_min': 0.0, 'engineering_max': 100.0,
              'storage': {'kind': 'GENERATED_DB', 'db': 'DB_TankProcess', 'member': member}}
    config.update({'validity_member': 'LevelValid'} if role == 'MEASUREMENT' else {'fault_value': 0.0})
    return {'name': name, 'class': 'internal', 'type': 'REAL', 'location': '', 'aliases': ['nivel'],
            'llm_allowed': True, 'state': 'ASSIGNED', 'process_config': config}


def test_db_roundtrip_preserves_metadata_and_permission():
    entry = db_entry()
    entry['llm_allowed'] = False
    result = normalize_variable_entry(entry)
    assert result.get('process_config') == entry['process_config']
    result['process_config']['storage']['member'] = 'Changed'
    assert entry['process_config']['storage']['member'] == 'Level'
    assert result['llm_allowed'] is False
    assert result['location'] == ''
    assert validate_io_map_variables([entry]) == []


def test_storage_collision_case_insensitive():
    first, second = db_entry(), db_entry('M_Other', 'MANIPULATED', 'levelVALID')
    second['process_config']['storage']['db'] = 'db_tankprocess'
    report = validate_plc_variable_map({'variables': [first, second]})
    assert not report['is_valid']
    assert any('DB_TankProcess.LevelValid'.casefold() in error.casefold() for error in report['errors'])


def test_different_spelling_of_same_db_is_rejected_before_import():
    first,second=db_entry(),db_entry('M_Fill','MANIPULATED','Fill')
    second['process_config']['storage']['db']='db_tankprocess'
    report=validate_plc_variable_map({'variables':[first,second]})
    assert not report['is_valid'] and any('PID_STORAGE_CONFLICT' in e for e in report['errors'])


@pytest.mark.parametrize('low,high',[(0.,1e40),(100000000.,100000001.)])
def test_unrepresentable_real_range_is_a_validation_error(low,high):
    entry=db_entry();entry['process_config'].update(engineering_min=low,engineering_max=high)
    report=validate_plc_variable_map({'variables':[entry]})
    assert not report['is_valid'] and any('PID_REAL_RANGE' in e for e in report['errors'])


def test_measurement_requires_distinct_quality():
    entry = db_entry()
    entry['process_config']['validity_member'] = 'level'
    errors = validate_io_map_variables([entry])
    assert any('validity_member' in error for error in errors)
    entry['process_config'].pop('validity_member')
    assert any('validity_member' in error for error in validate_io_map_variables([entry]))


@pytest.mark.parametrize('field,value', [('engineering_min', float('nan')), ('engineering_max', float('inf')),
                                        ('engineering_min', 100.0), ('fault_value', 101.0)])
def test_nonfinite_and_fault_value_rejected(field, value):
    entry = db_entry('M_Fill', 'MANIPULATED', 'Fill')
    entry['process_config'][field] = value
    assert any(field in error for error in validate_io_map_variables([entry]))


def test_binding_is_explicit_and_permissions_not_inferred():
    from process_signals import normalize_process_binding
    entry = db_entry()
    binding = normalize_process_binding(entry, 'MEASUREMENT')
    assert binding['representation'] == 'DB_ENGINEERING'
    assert binding['storage'] == {'kind': 'GENERATED_DB', 'db': 'DB_TankProcess', 'member': 'Level'}
    assert binding['validity_member'] == 'LevelValid'
    assert binding['unit'] == '%'
    entry['llm_allowed'] = False
    with pytest.raises(ValueError, match='PID_DEVICE_PERMISSION'):
        normalize_process_binding(entry, 'MEASUREMENT')


def test_malformed_storage_reports_field_without_crash():
    entry = db_entry()
    entry['process_config']['storage'] = []
    assert any('storage' in e for e in validate_io_map_variables([entry]))


def test_hardware_binding_keeps_test_provenance_without_confirmation():
    from process_signals import normalize_process_binding
    from tank_bench_setup import prepare_tank_bench
    from test_tank_bench_setup import bench
    source = prepare_tank_bench(bench())['variables'][18]
    before = copy.deepcopy(source)
    result = normalize_process_binding(source, 'MEASUREMENT')
    assert result['provenance'] == 'ASSUMED_FOR_TEST'
    assert result['analog_config']['confirmed'] is False
    assert source == before


@pytest.mark.parametrize('low,high', [(0.0, 1e40), (1e20, 1e20 + 1e7)])
def test_process_range_must_be_distinguishable_in_plc_real(low, high):
    from process_signals import normalize_process_binding
    entry = db_entry()
    entry['process_config'].update(engineering_min=low, engineering_max=high)
    with pytest.raises(ValueError, match='PID_REAL_RANGE'):
        normalize_process_binding(entry, 'MEASUREMENT')
