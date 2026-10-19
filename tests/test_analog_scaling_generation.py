"""Execute generated SCL against hand-calculated analog calibrations; no TIA/API/map writes."""
from __future__ import annotations

import copy

import pytest

from code_generator import generate_implementation_from_ir
from ir_builder import build_project_ir
from platforms.siemens_scl_adapter import SiemensSCLAdapter
from project_packager import generate_project_package
from semantic_validator import validate_semantic_output
from test_analog_configuration import configured_channel
from trial_experiments.scl_sim import SclMachine
from utils import get_project_root, load_json_file
from verifier import verify_project_ir


def bench():
    sensor, actuator = configured_channel(), configured_channel(True)
    sensor['analog_config'].update(engineering_max=200.0, engineering_unit='cm')
    actuator['analog_config']['fault_value'] = 10.0
    return {'variables': [sensor, actuator,
        {'name': 'I_Run', 'type': 'BOOL', 'class': 'input', 'location': '%IX16.0'},
        {'name': 'I_Emergency', 'type': 'BOOL', 'class': 'input', 'location': '%IX16.1'},
        {'name': 'Q_Pump', 'type': 'BOOL', 'class': 'output', 'location': '%QX8.0'}]}


def semantic(requirements):
    return {'intent_id': 'INT_UNKNOWN', 'case_id': None, 'command_text': 'Control analógico',
        'normalized_command': 'control analogico', 'interaction_profile': 'normal',
        'parameters': {'emergency_input': 'I_Emergency'}, 'confidence': 1.0, 'ambiguities': [],
        'requires_clarification': False, 'clarification_question': None, 'assumptions': [],
        'recognized_tags': [], 'unrecognized_terms': [], 'functional_requirements': requirements}


def hysteresis(**extra):
    return {'type': 'hysteresis_switch', 'input': 'AI_Level', 'output': 'Q_Pump',
            'on_above': 150, 'off_below': 120, **extra}


def output(value=50, **extra):
    return {'type': 'analog_output', 'output': 'AO_Valve', 'value': value, 'unit': '%', **extra}


def validation(payload, io_map):
    root = get_project_root() / 'config'
    return validate_semantic_output(payload, io_map, load_json_file(root / 'intents_catalog.json'),
                                    load_json_file(root / 'safety_rules.json'))


def machine(requirements, io_map=None):
    project = build_project_ir(semantic(requirements), io_map or bench(), 'SIEMENS_SCL_V18')
    project.pou.implementation_code = generate_implementation_from_ir(project)
    assert verify_project_ir(project)['is_valid'], verify_project_ir(project)
    plc = SclMachine(SiemensSCLAdapter().render_full_program(project))
    io = {}
    plc.initialize(io)
    return plc, io, project


def test_configured_hysteresis_uses_physical_units_and_detects_invalid_raw():
    plc, io, _ = machine([hysteresis()])
    for raw, expected in [(13824, False), (22118, True), (18000, True), (14000, False),
                          (27648, True), (-1, False), (32767, False)]:
        io['AI_Level'] = raw
        plc.scan(io)
        assert io['Q_Pump'] is expected


@pytest.mark.parametrize('raw,want', [(0, 0.0), (13824, 100.0), (27648, 200.0)])
def test_raw_to_real_endpoints_and_midpoint(raw, want):
    plc, io, project = machine([hysteresis()])
    binding = project.metadata['analog_bindings'][0]
    io['AI_Level'] = raw
    plc.scan(io)
    assert io[plc.static_key(binding['engineering_variable'])] == pytest.approx(want)
    assert io[plc.static_key(binding['valid_variable'])] is True


@pytest.mark.parametrize('value,want', [(0, 0), (50, 13824), (100, 27648)])
def test_analog_output_uses_inverse_calibration(value, want):
    plc, io, _ = machine([output(value)])
    plc.scan(io)
    assert io['AO_Valve'] == want
    assert type(io['AO_Valve']) is int


def test_analog_command_condition_and_emergency_use_configured_safe_value():
    plc, io, _ = machine([output(condition='I_Run')])
    for run, emergency, want in [(False, False, 2765), (True, False, 13824), (True, True, 2765)]:
        io.update(I_Run=run, I_Emergency=emergency)
        plc.scan(io)
        assert io['AO_Valve'] == want


def test_input_inhibition_overrides_analog_output_in_same_scan():
    plc, io, _ = machine([hysteresis(), output()])
    io['AI_Level'] = 27648
    plc.scan(io)
    assert (io['Q_Pump'], io['AO_Valve']) == (True, 13824)
    io['AI_Level'] = -1
    plc.scan(io)
    assert (io['Q_Pump'], io['AO_Valve']) == (False, 2765)


def test_substitute_value_keeps_invalid_diagnostic_without_inhibiting():
    io_map = bench()
    io_map['variables'][0]['analog_config'].update(fault_action='SUBSTITUTE_VALUE', fault_value=180)
    plc, io, project = machine([hysteresis()], io_map)
    io['AI_Level'] = -1
    plc.scan(io)
    binding = project.metadata['analog_bindings'][0]
    assert io['Q_Pump'] is True
    assert io[plc.static_key(binding['valid_variable'])] is False


def test_explicit_threshold_unit_is_converted_to_sensor_units():
    plc, io, _ = machine([hysteresis(on_above=1.5, off_below=1.2, unit='m')])
    io['AI_Level'] = 13824  # 100 cm, below 1.5 m
    plc.scan(io)
    assert io['Q_Pump'] is False


@pytest.mark.parametrize('change,fragment', [
    ({'confirmed': False}, 'ANALOG_CONFIGURATION_REQUIRED'),
    ({'raw_max': 0}, 'ANALOG_CONFIGURATION_REQUIRED'),
    ({'engineering_max': 1e50}, 'ANALOG_REAL_RANGE'),
])
def test_used_channel_incomplete_or_unrepresentable_configuration_blocks_generation(change, fragment):
    io_map = bench()
    io_map['variables'][0]['analog_config'].update(change)
    with pytest.raises(ValueError, match=fragment):
        build_project_ir(semantic([hysteresis()]), io_map, 'SIEMENS_SCL_V18')


@pytest.mark.parametrize('requirement', [output(101), output(unit='m'), hysteresis(unit='L')])
def test_invalid_analog_commands_are_rejected_before_generation(requirement):
    result = validation(semantic([requirement]), bench())
    assert not result['is_valid']
    assert any('ANALOG_' in e for e in result['errors']), result


def test_explicit_analog_output_requires_configuration_even_for_legacy_map():
    io_map = bench()
    del io_map['variables'][1]['analog_config']
    with pytest.raises(ValueError, match='ANALOG_CONFIGURATION_REQUIRED'):
        build_project_ir(semantic([output()]), io_map, 'SIEMENS_SCL_V18')


def test_digital_primitive_cannot_write_boolean_to_configured_analog_output():
    with pytest.raises(ValueError, match='ANALOG_OUTPUT_COMMAND_REQUIRED'):
        machine([{'type': 'conditional_output', 'condition': 'I_Run', 'outputs': ['AO_Valve']}])


def test_unused_pending_channel_does_not_block_digital_program_or_mutate_map():
    io_map = bench()
    io_map['variables'][0]['analog_config']['confirmed'] = False
    before = copy.deepcopy(io_map)
    plc, io, project = machine([{'type': 'conditional_output', 'condition': 'I_Run', 'outputs': ['Q_Pump']}], io_map)
    io['I_Run'] = True
    plc.scan(io)
    assert io['Q_Pump'] is True
    assert not project.metadata.get('analog_bindings')
    assert io_map == before


def test_legacy_raw_hysteresis_remains_compatible():
    io_map = bench()
    del io_map['variables'][0]['analog_config']
    plc, io, _ = machine([hysteresis()], io_map)
    io['AI_Level'] = 151
    plc.scan(io)
    assert io['Q_Pump'] is True


def test_scaled_program_package_passes_composition_and_static_verification(tmp_path):
    result = generate_project_package(semantic([hysteresis(), output()]), 'SIEMENS_SCL_V18', bench(),
                                      output_dir=tmp_path / 'package')
    assert result['verification']['is_valid'], result['verification']
    assert result['verification']['package_verification']['composition']['valid']


@pytest.mark.parametrize('requirement', [
    {'type': 'analog_output', 'value': 50, 'unit': '%'},
    {'type': 'analog_output', 'output': 'AO_Valve', 'unit': '%'},
    output(True), output(float('nan')), output(condition=''),
])
def test_incomplete_analog_order_is_a_diagnostic_not_a_generator_crash(requirement):
    result = validation(semantic([requirement]), bench())
    assert not result['is_valid']
    with pytest.raises(ValueError, match='ANALOG_'):
        build_project_ir(semantic([requirement]), bench(), 'SIEMENS_SCL_V18')


def test_configuration_is_checked_before_packaging_in_experimental_profile():
    payload, io_map = semantic([hysteresis()]), bench()
    payload.pop('interaction_profile')
    io_map['variables'][0]['analog_config']['confirmed'] = False
    assert not validation(payload, io_map)['is_valid']


def test_generated_analog_helpers_are_not_persisted_as_user_functional_variables():
    _, _, project = machine([hysteresis(), output()])
    assert not project.metadata['generated_functional_variables']


def test_configured_input_cannot_be_used_as_boolean_condition():
    req = {'type': 'conditional_output', 'condition': 'AI_Level', 'outputs': ['Q_Pump']}
    with pytest.raises(ValueError, match='ANALOG_INPUT_COMPARISON_REQUIRED'):
        machine([req])


@pytest.mark.parametrize('raw_min,raw_max,raw,eng_min,eng_max,want', [
    (-27648, 27648, 0, -50, 150, 50),
    (-32768, 32767, 32767, 0, 200, 200),
    (5530, 27648, 16589, 0, 200, 100),
])
def test_calibration_honors_explicit_raw_domain(raw_min, raw_max, raw, eng_min, eng_max, want):
    io_map = bench()
    io_map['variables'][0]['analog_config'].update(raw_min=raw_min, raw_max=raw_max,
                                                engineering_min=eng_min, engineering_max=eng_max)
    plc, io, project = machine([hysteresis()], io_map)
    io['AI_Level'] = raw
    plc.scan(io)
    assert io[plc.static_key(project.metadata['analog_bindings'][0]['engineering_variable'])] == pytest.approx(want)


def test_output_bipolar_calibration_and_bad_runtime_command():
    io_map = bench()
    io_map['variables'][1]['analog_config'].update(raw_min=-27648, raw_max=27648)
    plc, io, _ = machine([output(0)], io_map)
    plc.scan(io)
    assert io['AO_Valve'] == -27648


def test_auxiliary_name_collision_is_reported_before_generating_code():
    io_map = bench()
    io_map['variables'].append({'name': 'M_AI_Level_EU', 'class': 'internal', 'type': 'REAL'})
    with pytest.raises(ValueError, match='ANALOG_VARIABLE_COLLISION'):
        machine([hysteresis()], io_map)


@pytest.mark.parametrize('lo,hi,value,want', [(1000, 1000.01, 1000.01, 27648),
                                           (0.1, 0.3, 0.1, 0), (0.1, 0.3, 0.3, 27648)])
def test_real_precision_preserves_calibrated_endpoints(lo, hi, value, want):
    io_map = bench()
    io_map['variables'][1]['analog_config'].update(engineering_min=lo, engineering_max=hi, fault_value=lo)
    plc, io, _ = machine([output(value)], io_map)
    plc.scan(io)
    assert io['AO_Valve'] == want


def test_output_runtime_out_of_range_uses_safe_value():
    # Execute the inverse conversion with an injected out-of-range engineering command as a future PID could emit.
    from analog_scaling import apply_analog_scaling
    project = build_project_ir(semantic([output()]), bench(), 'SIEMENS_SCL_V18')
    project.pou.implementation_code = apply_analog_scaling(project, 'AO_Valve := 120.0;')
    plc = SclMachine(SiemensSCLAdapter().render_full_program(project))
    io = {}
    plc.initialize(io)
    plc.scan(io)
    assert io['AO_Valve'] == 2765


def test_parser_preserves_analog_order_and_unit_for_generation(tmp_path):
    # Inject structured interpretation at the network boundary, exercising the production parser/repair/validator.
    from llm_parser import parse_command
    payload = semantic([output(50, condition='I_Run')])
    root = get_project_root() / 'config'
    parsed = parse_command('Si Run está activo, abre la válvula proporcional al 50 por ciento.', mode='llm',
        io_map=bench(), intents_catalog=load_json_file(root / 'intents_catalog.json'),
        safety_rules=load_json_file(root / 'safety_rules.json'), llm_response_text=payload,
        interaction_profile='normal')
    assert parsed['semantic_validation']['is_valid'], parsed['semantic_validation']
    result = generate_project_package(parsed, 'SIEMENS_SCL_V18', bench(), output_dir=tmp_path / 'parsed')
    assert result['verification']['is_valid'], result['verification']


def test_interpreter_receives_sensor_units_without_having_to_invent_calibration():
    from llm_context_builder import build_llm_context
    io_map = bench()
    before = copy.deepcopy(io_map)
    context = build_llm_context('Controla nivel', io_map, {}, {})
    channel = next(c for c in context['authorized_io_map'] if c['name'] == 'AI_Level')
    assert channel['analog_config']['engineering_unit'] == 'cm'
    assert channel['analog_config']['engineering_max'] == 200
    assert channel['analog_config']['confirmed'] is True
    assert io_map == before


def test_huge_command_is_a_controlled_validation_error():
    result = validation(semantic([output(10 ** 500)]), bench())
    assert not result['is_valid']
    assert any('ANALOG_' in e for e in result['errors'])


@pytest.mark.parametrize('condition', ['AI_Level = I_Run', 'AI_Level > I_Run', 'I_Run < AI_Level'])
def test_analog_comparison_rejects_boolean_operand(condition):
    payload = semantic([{'type': 'conditional_output', 'condition': condition, 'outputs': ['Q_Pump']}])
    assert not validation(payload, bench())['is_valid']
    with pytest.raises(ValueError, match='ANALOG_INPUT_COMPARISON_REQUIRED'):
        build_project_ir(payload, bench(), 'SIEMENS_SCL_V18')


def test_analog_input_cannot_be_a_digital_sequence_trigger():
    payload = semantic([{'type': 'timed_sequence', 'start_input': 'AI_Level',
                         'steps': [{'outputs': ['Q_Pump'], 'duration': 'T#1s'}]}])
    with pytest.raises(ValueError, match='ANALOG_INPUT_COMPARISON_REQUIRED'):
        build_project_ir(payload, bench(), 'SIEMENS_SCL_V18')


def test_analog_output_cannot_be_a_boolean_condition():
    payload = semantic([output(condition='AO_Valve')])
    assert not validation(payload, bench())['is_valid']
    with pytest.raises(ValueError, match='ANALOG_INPUT_COMPARISON_REQUIRED'):
        build_project_ir(payload, bench(), 'SIEMENS_SCL_V18')


@pytest.mark.parametrize('condition', ['AI_Level > 1.5', '1.5 < AI_Level'])
def test_condition_threshold_unit_is_converted_deterministically(condition):
    plc, io, _ = machine([{'type': 'conditional_output', 'condition': condition, 'unit': 'm', 'outputs': ['Q_Pump']}])
    io['AI_Level'] = 13824  # 100 cm
    plc.scan(io)
    assert io['Q_Pump'] is False
    io['AI_Level'] = 27648
    plc.scan(io)
    assert io['Q_Pump'] is True


def test_analog_output_has_independent_order_and_condition_units():
    plc, io, _ = machine([output(condition='AI_Level > 1.5', condition_unit='m')])
    io['AI_Level'] = 13824
    plc.scan(io)
    assert io['AO_Valve'] == 2765
    io['AI_Level'] = 27648
    plc.scan(io)
    assert io['AO_Valve'] == 13824


def test_explicit_physical_comparison_requires_calibration_on_legacy_input():
    io_map = bench()
    del io_map['variables'][0]['analog_config']
    payload = semantic([{'type': 'conditional_output', 'condition': 'AI_Level > 1.5',
                         'unit': 'm', 'outputs': ['Q_Pump']}])
    with pytest.raises(ValueError, match='ANALOG_CONFIGURATION_REQUIRED'):
        build_project_ir(payload, io_map, 'SIEMENS_SCL_V18')
