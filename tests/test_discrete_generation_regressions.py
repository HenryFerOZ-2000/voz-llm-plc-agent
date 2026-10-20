"""Observed product failures reproduced offline, without API or TIA calls."""
import copy

import pytest

from composition_check import analyze_composition
from functional_requirements import get_functional_requirement_tags, timed_sequence_missing_data
from test_normal_mode_hardening import _program, _Plc


@pytest.mark.parametrize('alarm', ['Q_Alarm', 'Q_Alarm_Custom'])
def test_safe_start_alarm_has_one_owner_and_preserves_alarm_behavior(tmp_path, alarm):
    result = _program('Activa una alarma al intentar arrancar sin permiso.',
        [{'type': 'alarm_output', 'target': alarm}], tmp_path,
        intent='INT_SAFE_START_ALARM', parameters={'trigger_input': 'I_Start',
            'safety_input': 'I_Permission', 'alarm_output': alarm, 'motor_output': 'Q_Motor_Enable',
            'fault_latch': 'M_FaultLatch', 'emergency_input': 'FALSE'})
    plc = _Plc(result['scl'])
    plc.run(20)
    assert not plc.on(alarm)
    plc.set(I_Start=True, I_Permission=False)
    plc.run(20)
    assert plc.on(alarm) == {alarm}
    assert not plc.on('Q_Motor_Enable')


@pytest.mark.parametrize('intent,parameters,requirement', [
    ('INT_VFD_ENABLE_NO_ALARM', {'trigger_input':'I_Start', 'alarm_input':'I_Alarm_Active',
        'motor_output':'Q_Motor_Enable', 'emergency_input':'FALSE'},
     {'type':'force_off','condition':'I_Alarm_Active','outputs':['Q_Motor_Enable']}),
    ('INT_MAINTENANCE_BLOCK', {'trigger_input':'I_Start','motor_output':'Q_Custom',
        'maintenance_input':'I_Maintenance','emergency_input':'FALSE'},
     {'type':'force_off','condition':'I_Block','outputs':['Q_Custom']}),
])
def test_stop_modifier_does_not_erase_the_main_intent(tmp_path, intent, parameters, requirement):
    # A different catalog intent covers the same dispatch defect, not only the thesis example.
    result = _program('Activa la salida con Start, bloqueada por la condicion indicada.',
        [copy.deepcopy(requirement)], tmp_path, intent=intent, parameters=parameters)
    plc = _Plc(result['scl'])
    output = requirement['outputs'][0]
    block = requirement['condition']
    plc.run(20)
    assert not plc.on(output)
    plc.set(I_Start=True, **{block:False})
    plc.run(20)
    assert plc.on(output) == {output}
    plc.set(**{block:True})
    plc.run(20)
    assert not plc.on(output)
    plc.set(I_Start=False, **{block:False})
    plc.run(20)
    assert not plc.on(output)


@pytest.mark.parametrize('selector', ['I_Mode_Auto', 'I_Selector'])
def test_shared_selector_uses_complementary_modes_and_ignores_other_command(tmp_path, selector):
    requirements = [
        {'type':'automatic_mode','mode_input':selector},
        {'type':'manual_mode','mode_input':selector,'commands':[
            {'input':'I_Manual_Command','output':'Q_Motor_Enable','behavior':'maintained'}]},
        {'type':'conditional_output','condition':f'{selector} AND I_Auto_Command',
            'outputs':['Q_Motor_Enable']},
    ]
    result = _program('Un selector elige la orden manual o automatica del motor.', requirements,
        tmp_path, intent='INT_MANUAL_AUTO_MODE', parameters={'auto_input':selector,
            'manual_command_input':'I_Manual_Command','auto_command_input':'I_Auto_Command',
            'motor_output':'Q_Motor_Enable','emergency_input':'FALSE'})
    plc = _Plc(result['scl'])
    for auto in (False, True):
        for manual_command in (False, True):
            for auto_command in (False, True):
                plc.set(**{selector:auto,'I_Manual_Command':manual_command,'I_Auto_Command':auto_command})
                plc.run(20)
                assert bool(plc.on('Q_Motor_Enable')) == (auto_command if auto else manual_command)


def test_explicit_mode_input_does_not_require_a_different_catalog_input():
    assert get_functional_requirement_tags({'type':'manual_mode','mode_input':'I_Selector'}) == [
        'I_Selector','M_ManualMode']


@pytest.mark.parametrize('modifier', [
    {'type':'reset_behavior'},
    {'type':'never_together','outputs':['Q_Custom','Q_Other']},
    {'type':'run_pilot'},
    {'type':'maintenance_inhibit'},
])
def test_stop_override_with_other_modifiers_retains_the_main_program(tmp_path, modifier):
    result = _program('Activa la salida con Start y bloqueala durante mantenimiento.',
        [{'type':'force_off','condition':'I_Block','outputs':['Q_Custom']}, modifier], tmp_path,
        intent='INT_MAINTENANCE_BLOCK', parameters={'trigger_input':'I_Start','motor_output':'Q_Custom',
            'maintenance_input':'I_Maintenance','emergency_input':'FALSE'})
    plc = _Plc(result['scl'])
    plc.set(I_Start=True, I_Maintenance=False, I_Block=False)
    plc.run(20)
    assert plc.on('Q_Custom') == {'Q_Custom'}
    plc.set(I_Block=True)
    plc.run(20)
    assert not plc.on('Q_Custom')
    if modifier['type'] == 'run_pilot':
        assert not plc.on('Q_Pilot_Run')


@pytest.mark.parametrize('output_field', [{'outputs':'Q_Custom'}, {'output':'Q_Custom'}, {'target':'Q_Custom'}])
def test_stop_override_resources_use_the_same_output_aliases_as_codegen(tmp_path, output_field):
    result = _program('Activa la salida con Start y bloqueala cuando se indique.',
        [{'type':'force_off','condition':'I_Block',**output_field}], tmp_path,
        intent='INT_MAINTENANCE_BLOCK', parameters={'trigger_input':'I_Start','motor_output':'Q_Custom',
            'maintenance_input':'I_Maintenance','emergency_input':'FALSE'})
    plc = _Plc(result['scl'])
    plc.set(I_Start=True, I_Block=False); plc.run(20)
    assert plc.on('Q_Custom') == {'Q_Custom'}
    plc.set(I_Block=True); plc.run(20)
    assert not plc.on('Q_Custom')


def test_stop_override_of_latched_motor_requires_a_new_start(tmp_path):
    result = _program('Start enclava el motor; Stop o bloqueo lo detienen.',
        [{'type':'force_off','condition':'I_Block','outputs':['Q_Motor_Enable']}], tmp_path,
        intent='INT_MOTOR_LATCH', parameters={'trigger_input':'I_Start','stop_input':'I_Stop',
            'motor_output':'Q_Motor_Enable','run_latch':'M_RunLatch','emergency_input':'FALSE'})
    plc = _Plc(result['scl'])
    plc.run(30); plc.press('I_Start')
    assert plc.on('Q_Motor_Enable')
    plc.set(I_Start=True, I_Block=True); plc.run(20)
    assert not plc.on('Q_Motor_Enable')
    plc.set(I_Block=False); plc.run(20)
    assert not plc.on('Q_Motor_Enable')
    plc.set(I_Start=False); plc.run(20); plc.press('I_Start')
    assert plc.on('Q_Motor_Enable')


def test_manual_commands_are_independent_producers_despite_a_stop_modifier(tmp_path):
    result = _program('En Manual la orden manual manda el motor, salvo bloqueo.',
        [{'type':'manual_mode','mode_input':'I_Mode_Manual','commands':[
            {'input':'I_Manual_Command','output':'Q_Motor_Enable','behavior':'maintained'}]},
         {'type':'force_off','condition':'I_Block','outputs':['Q_Motor_Enable']}], tmp_path,
        intent='INT_MANUAL_AUTO_MODE', parameters={'manual_input':'I_Mode_Manual','auto_input':'I_Mode_Auto',
            'trigger_input':'I_Start','stop_input':'I_Stop','motor_output':'Q_Motor_Enable',
            'emergency_input':'FALSE'})
    plc = _Plc(result['scl'])
    plc.set(I_Mode_Manual=True,I_Manual_Command=True); plc.run(20)
    assert plc.on('Q_Motor_Enable')
    plc.set(I_Manual_Command=False,I_Start=True); plc.run(20)
    assert not plc.on('Q_Motor_Enable')


def test_stop_override_accepts_the_latch_requirement_owned_by_the_template(tmp_path):
    result = _program('Start enclava el motor; Stop o bloqueo lo detienen.',
        [{'type':'force_off','condition':'I_Block','outputs':['Q_Motor_Enable']},
         {'type':'motor_start_latch'}], tmp_path,
        intent='INT_MOTOR_LATCH', parameters={'trigger_input':'I_Start','stop_input':'I_Stop',
            'motor_output':'Q_Motor_Enable','run_latch':'M_RunLatch','emergency_input':'FALSE'})
    plc = _Plc(result['scl']); plc.run(30); plc.press('I_Start')
    assert plc.on('Q_Motor_Enable')
    plc.set(I_Block=True); plc.run(20)
    assert not plc.on('Q_Motor_Enable')
    plc.set(I_Block=False); plc.run(20)
    assert not plc.on('Q_Motor_Enable')
    plc.press('I_Start')
    assert plc.on('Q_Motor_Enable')


def test_real_conflicting_writes_are_still_rejected():
    source = 'FUNCTION_BLOCK "Test"\nVAR_OUTPUT\nQ_Output : BOOL;\nEND_VAR\nBEGIN\nQ_Output := TRUE;\nQ_Output := FALSE;\nEND_FUNCTION_BLOCK'
    report = analyze_composition(source)
    assert report['analyzed'] and not report['valid']


def test_open_ended_sequence_still_requires_a_stop_definition():
    missing = timed_sequence_missing_data([{'type':'timed_sequence','start_input':'I_Start',
        'steps':[{'outputs':['Q_Main'],'duration':'T#3s'},{'outputs':['Q_Main','Q_Aux']}]}])
    assert any(item['kind']=='stop_input' for item in missing)
