"""Captured finite-fill response: numeric stage commands must survive the whole pipeline."""
import copy
import json
from pathlib import Path

import pytest

from functional_resources import resolve_functional_resources
from functional_requirements import timed_sequence_missing_data
from ir_builder import build_project_ir
from code_generator import generate_implementation_from_ir
from product_engine import interpret_product_command
from platforms.siemens_scl_adapter import SiemensSCLAdapter
from trial_experiments.scl_sim import SclMachine
from verifier import verify_project_ir

FIX = Path(__file__).parent / 'fixtures/natural_commands'


def response():
    return json.loads((FIX / 'analog_sequence_incident.json').read_text(encoding='utf-8'))


def bench(confirmed=True):
    value = json.loads((FIX / 'prepared_map.json').read_text(encoding='utf-8'))
    for row in value['variables']:
        if 'analog_config' in row:
            row['analog_config']['confirmed'] = confirmed
    return value


def build(value=None, io_map=None):
    ir = build_project_ir(value or response(), io_map or bench(), 'SIEMENS_SCL_V18')
    ir.pou.implementation_code = generate_implementation_from_ir(ir)
    assert verify_project_ir(ir)['is_valid'], verify_project_ir(ir)
    plc = SclMachine(SiemensSCLAdapter().render_full_program(ir))
    io = {'I_Start': False, 'I_Stop': False, 'I_Emergency': False, 'AI_Level_Raw': 5530}
    plc.initialize(io)
    plc.scan(io)
    return ir, plc, io


def test_captured_numeric_stage_is_resolved_without_discarding_its_value():
    result = resolve_functional_resources(response()['functional_requirements'])
    assert result['errors'] == []
    assert result['requirements'][0]['steps'][0]['analog_outputs'] == [
        {'output': 'AO_Fill_Command', 'value': 100, 'unit': '%'}]
    assert 'AO_Fill_Command' in result['referenced_tags']
    assert timed_sequence_missing_data(result['requirements']) == []


def test_captured_response_does_not_ask_for_already_declared_stages(intents_catalog, safety_rules):
    value = response()
    result = interpret_product_command(value['command_text'], io_map=bench(),
        intents_catalog=intents_catalog, safety_rules=safety_rules, mode='llm', llm_response_text=value)
    assert not result['requires_clarification'], result['semantic_validation']
    assert result['semantic_validation']['is_valid'], result['semantic_validation']
    assert not result['semantic_validation'].get('io_assignment_proposals')


def test_fill_stops_at_threshold_and_waits_for_a_new_start_edge():
    ir, plc, io = build()
    assert not ir.pid_loops
    assert io['AO_Fill_Command'] == 0
    io['I_Start'] = True; plc.scan(io)
    assert io['AO_Fill_Command'] == 27648
    io['AI_Level_Raw'] = 22119; plc.scan(io)
    assert io['AO_Fill_Command'] == 0
    io['AI_Level_Raw'] = 5530; plc.scan(io)
    assert io['AO_Fill_Command'] == 0
    io['I_Start'] = False; plc.scan(io)
    io['I_Start'] = True; plc.scan(io)
    assert io['AO_Fill_Command'] == 27648


@pytest.mark.parametrize('signal', ['I_Stop', 'I_Emergency'])
def test_stop_or_emergency_cancels_the_analog_stage_without_automatic_restart(signal):
    _, plc, io = build()
    io['I_Start'] = True; plc.scan(io)
    assert io['AO_Fill_Command'] == 27648
    io[signal] = True; plc.scan(io)
    assert io['AO_Fill_Command'] == 0
    io[signal] = False; plc.scan(io)
    assert io['AO_Fill_Command'] == 0
    io['I_Start'] = False; plc.scan(io)
    io['I_Start'] = True; plc.scan(io)
    assert io['AO_Fill_Command'] == 27648


def test_exclusive_stages_can_command_different_values_of_the_same_valve():
    value = response()
    step = value['functional_requirements'][0]['steps'][0]
    step['advance_on'] = 'AI_Level_Raw >= 40'
    second = copy.deepcopy(step)
    second.update(advance_on='AI_Level_Raw >= 80')
    second['analog_outputs'][0]['value'] = 50
    value['functional_requirements'][0]['steps'].append(second)
    _, plc, io = build(value)
    io['I_Start'] = True; plc.scan(io)
    assert io['AO_Fill_Command'] == 27648
    io['AI_Level_Raw'] = 13824; plc.scan(io)
    assert io['AO_Fill_Command'] == 13824
    io['AI_Level_Raw'] = 22119; plc.scan(io)
    assert io['AO_Fill_Command'] == 0


def test_analog_sequence_preserves_numeric_commands_and_safe_values_in_generated_cases():
    ir, _, _ = build()
    cases = {case['test_id']: case for case in ir.test_cases}
    assert cases['SEQ1_START']['expected_outputs']['AO_Fill_Command'] == 27648
    assert cases['SEQ1_STOP']['expected_outputs']['AO_Fill_Command'] == 0


@pytest.mark.parametrize('value', [None, True, float('nan'), float('inf'), -1, 101])
def test_invalid_numeric_stage_commands_never_generate_a_program(value):
    semantic = response()
    semantic['functional_requirements'][0]['steps'][0]['analog_outputs'][0]['value'] = value
    with pytest.raises(ValueError, match='ANALOG_COMMAND_(VALUE|RANGE)'):
        build_project_ir(semantic, bench(), 'SIEMENS_SCL_V18')


def test_a_second_independent_writer_for_the_valve_is_rejected():
    value = response()
    value['functional_requirements'].append({'type': 'analog_output', 'output': 'AO_Fill_Command', 'value': 25, 'unit': '%'})
    with pytest.raises(ValueError, match='ANALOG_MULTIPLE_WRITERS'):
        build_project_ir(value, bench(), 'SIEMENS_SCL_V18')


def test_duplicate_commands_for_the_same_valve_in_one_stage_are_rejected():
    value = response()
    value['functional_requirements'][0]['steps'][0]['analog_outputs'].append(
        {'output': 'AO_Fill_Command', 'value': 25, 'unit': '%'})
    with pytest.raises(ValueError, match='ANALOG_MULTIPLE_WRITERS'):
        build_project_ir(value, bench(), 'SIEMENS_SCL_V18')


def test_unconfirmed_calibration_remains_blocked_without_mutating_the_map():
    io_map = bench(False)
    before = copy.deepcopy(io_map)
    with pytest.raises(ValueError, match='ANALOG_CONFIGURATION_REQUIRED'):
        build_project_ir(response(), io_map, 'SIEMENS_SCL_V18')
    assert io_map == before


def test_emergency_uses_the_maps_numeric_safe_value():
    io_map = bench()
    next(row for row in io_map['variables'] if row['name'] == 'AO_Fill_Command')['analog_config']['fault_value'] = 10
    _, plc, io = build(io_map=io_map)
    assert io['AO_Fill_Command'] == 2765
    io['I_Start'] = True; plc.scan(io)
    assert io['AO_Fill_Command'] == 27648
    io['I_Emergency'] = True; plc.scan(io)
    assert io['AO_Fill_Command'] == 2765


def test_independent_sequences_cannot_own_the_same_analog_output():
    value = response()
    value['functional_requirements'].append(copy.deepcopy(value['functional_requirements'][0]))
    with pytest.raises(ValueError, match='ANALOG_MULTIPLE_WRITERS'):
        build_project_ir(value, bench(), 'SIEMENS_SCL_V18')


def test_numeric_stage_cannot_target_a_digital_output():
    value = response()
    value['functional_requirements'][0]['steps'][0]['analog_outputs'][0]['output'] = 'Q_Traffic_Green'
    with pytest.raises(ValueError, match='ANALOG_CHANNEL_TYPE'):
        build_project_ir(value, bench(), 'SIEMENS_SCL_V18')


def test_stage_sensor_threshold_is_converted_to_the_maps_engineering_unit():
    value = response()
    value['command_text'] = 'Al pulsar Start, llena hasta 1.6 m y cierra la válvula.'
    step = value['functional_requirements'][0]['steps'][0]
    step.update(advance_on='AI_Level_Raw >= 1.6', condition_unit='m')
    io_map = bench()
    config = next(row for row in io_map['variables'] if row['name'] == 'AI_Level_Raw')['analog_config']
    config.update(engineering_max=200, engineering_unit='cm')
    _, plc, io = build(value, io_map)
    io['I_Start'] = True; plc.scan(io)
    io['AI_Level_Raw'] = 13824; plc.scan(io)
    assert io['AO_Fill_Command'] == 27648
    io['AI_Level_Raw'] = 22119; plc.scan(io)
    assert io['AO_Fill_Command'] == 0


def test_a_renamed_sensor_and_valve_use_the_map_addresses():
    value = response()
    io_map = bench()
    for old, new, address in [('AI_Level_Raw', 'AI_Tank_Measurement', '%IW64'),
                              ('AO_Fill_Command', 'AO_Inlet_Valve', '%QW72')]:
        row = next(row for row in io_map['variables'] if row['name'] == old)
        row.update(name=new, location=address)
        value = json.loads(json.dumps(value).replace(old, new))
    ir, plc, io = build(value, io_map)
    io.update(I_Start=True, AI_Tank_Measurement=5530); plc.scan(io)
    assert io['AO_Inlet_Valve'] == 27648
    io['AI_Tank_Measurement'] = 22119; plc.scan(io)
    assert io['AO_Inlet_Valve'] == 0
    variables = {row.name: row for row in ir.pou.variables}
    assert variables['AI_Tank_Measurement'].location == '%IW64'
    assert variables['AO_Inlet_Valve'].location == '%QW72'


@pytest.mark.parametrize('requested,device', [('bomba de velocidad variable', 'PROPORTIONAL_VALVE'),
                                           ('válvula proporcional', 'VARIABLE_SPEED_DRIVE')])
def test_numeric_stages_cannot_substitute_the_requested_actuator(requested, device, intents_catalog, safety_rules):
    value = response()
    value['command_text'] = f'Al pulsar Start, activa la {requested} al 100 % hasta que el nivel alcance el 80 %.'
    value['normalized_command'] = value['command_text'].lower()
    io_map = bench()
    next(row for row in io_map['variables'] if row['name'] == 'AO_Fill_Command')['analog_config']['device_kind'] = device
    result = interpret_product_command(value['command_text'], io_map=io_map,
        intents_catalog=intents_catalog, safety_rules=safety_rules, mode='llm', llm_response_text=value)
    assert not result['semantic_validation']['is_valid']
    assert any('CONTROL_ACTUATOR_MISMATCH' in error for error in result['semantic_validation']['errors'])
    with pytest.raises(ValueError, match='CONTROL_ACTUATOR_MISMATCH'):
        build_project_ir(value, io_map, 'SIEMENS_SCL_V18')


def test_an_incomplete_analog_stage_question_identifies_its_actual_output():
    value = response()
    del value['functional_requirements'][0]['steps'][0]['advance_on']
    gaps = timed_sequence_missing_data(value['functional_requirements'])
    assert gaps == [{'kind': 'duration', 'step': 1, 'outputs': ['AO_Fill_Command'],
                     'next_outputs': [], 'final': True}]
