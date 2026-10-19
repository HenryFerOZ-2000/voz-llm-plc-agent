import copy

import pytest

from tank_bench_setup import prepare_tank_bench
from test_tank_bench_setup import bench


def request(**kw):
    return {'type':'pid_control','loop_id':'LevelLoop','setpoint':50.0,'unit':'%',
            'direction':'FILL','mode':'SIMULATION',**kw}


def resolve(requirements=None, io_map=None, mode='SIMULATION'):
    from pid_control import resolve_pid_loops
    return resolve_pid_loops(requirements or [request()], io_map if io_map is not None else prepare_tank_bench(bench()),
                             'SIEMENS_SCL_V18')


def test_resolves_unique_level_sensor_and_valve():
    source=prepare_tank_bench(bench()); before=copy.deepcopy(source)
    loop=resolve(io_map=source)[0]
    assert (loop.process_input,loop.control_output)==('AI_Level_Raw','AO_Fill_Command')
    assert loop.resources=={} and loop.setpoint==50 and loop.period_ms==100
    assert loop.controller['status']=='UNTUNED'
    assert source==before and loop.input_binding['analog_config']['confirmed'] is False


def test_renamed_relocated_devices_are_used():
    source=prepare_tank_bench(bench())
    for entry in source['variables']:
        if entry['name']=='AI_Level_Raw': entry.update(name='AI_Medicion',location='%IW120')
        if entry['name']=='AO_Fill_Command': entry.update(name='AO_Actuador',location='%QW220')
    loop=resolve(io_map=source)[0]
    assert (loop.process_input,loop.control_output)==('AI_Medicion','AO_Actuador')
    assert 'Tank' not in loop.symbols['db']


def test_locked_alarm_is_reused_but_not_reassigned():
    source=prepare_tank_bench(bench()); source['variables'][8].update(name='Q_Alarm',semantic_role='ALARM',state='LOCKED')
    loop=resolve([request(resources={'alarm_output':'Q_Alarm'})],source)[0]
    assert loop.resources=={'alarm_output':'Q_Alarm'}
    assert source['variables'][8]['state']=='LOCKED'


def test_explicit_locked_motor_cannot_be_used_as_alarm():
    source=prepare_tank_bench(bench());source['variables'][8].update(name='Q_Motor',semantic_role='MOTOR',state='LOCKED')
    with pytest.raises(ValueError,match='PID_RESOURCE_ROLE'):resolve([request(resources={'alarm_output':'Q_Motor'})],source)


def test_unknown_protected_output_function_is_not_guessed():
    source=prepare_tank_bench(bench());source['variables'][8].update(name='Q_Traffic_Green',state='LOCKED')
    with pytest.raises(ValueError,match='PID_RESOURCE_ROLE'):resolve([request(resources={'alarm_output':'Q_Traffic_Green'})],source)


def test_two_roles_cannot_share_a_physical_output():
    with pytest.raises(ValueError,match='PID_RESOURCE_CONFLICT'):
        resolve([request(resources={'alarm_output':'Q_Digital_0','enable_output':'Q_Digital_0'})])


def test_digital_outputs_not_requested_are_absent():
    from ir_builder import build_project_ir
    project=build_project_ir(payload(request()),prepare_tank_bench(bench()),'SIEMENS_SCL_V18')
    assert len(project.pid_loops)==1
    assert not [v for v in project.pou.variables if v.var_class=='output' and v.data_type=='BOOL']


def test_ambiguous_devices_require_process_clarification():
    source=prepare_tank_bench(bench()); other=copy.deepcopy(source['variables'][18]); other.update(name='AI_Otro',location='%IW40')
    source['variables'].append(other)
    with pytest.raises(ValueError,match='PID_DEVICE_AMBIGUOUS'): resolve(io_map=source)


def test_generation_keeps_unconfirmed_ranges_for_download_gate():
    loop=resolve([request(mode='PHYSICAL')],mode='PHYSICAL')[0]
    assert loop.input_binding['analog_config']['confirmed'] is False
    assert loop.output_binding['analog_config']['confirmed'] is False


def test_missing_map_channels_require_explicit_process_signals():
    with pytest.raises(ValueError,match='PID_DEVICE_MISSING'): resolve(io_map={'variables':[]})
    with pytest.raises(ValueError,match='PID_DEVICE_MISSING'): resolve([request(mode=None)],{'variables':[]},mode='')


def test_multiple_loops_are_rejected():
    with pytest.raises(ValueError,match='PID_MULTIPLE_LOOPS'): resolve([request(),request(loop_id='Other')])


def test_native_pid_does_not_change_supervisor_contract():
    from pid_control import resolve_pid_loops
    assert resolve_pid_loops([{'type':'enable_pid'}],{'variables':[]},'SIEMENS_SCL_V18')==[]


@pytest.mark.parametrize('period',[0,-1,1.5,True])
def test_invalid_period_is_rejected(period):
    with pytest.raises(ValueError,match='PID_PERIOD'): resolve([request(period_ms=period)])


def test_setpoint_conversion_and_incompatible_units():
    source=prepare_tank_bench(bench()); source['variables'][18]['analog_config'].update(engineering_unit='cm',engineering_max=200)
    loop=resolve([request(setpoint=1,unit='m')],source)[0]
    assert loop.setpoint==100 and loop.unit=='cm'
    with pytest.raises(ValueError,match='PID_UNIT'): resolve([request(unit='bar')],source)


def test_controller_honors_nondefault_percentage_sensor_range():
    source=prepare_tank_bench(bench());source['variables'][18]['analog_config'].update(engineering_min=50,engineering_max=100)
    loop=resolve([request(setpoint=70)],source)[0]
    assert loop.input_binding['engineering_min']==50 and loop.input_binding['engineering_max']==100
    assert 'simulation' not in loop.to_dict()


def test_overfill_limit_uses_the_same_units_as_the_command():
    source=prepare_tank_bench(bench());source['variables'][18]['analog_config'].update(engineering_unit='cm',engineering_max=200)
    loop=resolve([request(setpoint=1,unit='m',overfill_limit=1.9)],source)[0]
    assert loop.setpoint==100 and loop.overfill_limit==190


def test_disallowed_or_explicit_wrong_device_is_rejected():
    source=prepare_tank_bench(bench()); source['variables'][18]['llm_allowed']=False
    with pytest.raises(ValueError,match='PID_DEVICE'): resolve([request(process_input='AI_Level_Raw')],source)


def payload(req):
    return {'intent_id':'INT_UNKNOWN','case_id':None,'command_text':'Control PID','normalized_command':'control pid',
            'interaction_profile':'normal','parameters':{},'confidence':.99,'ambiguities':[],
            'requires_clarification':False,'clarification_question':None,'assumptions':[],
            'recognized_tags':[],'unrecognized_terms':[],'functional_requirements':[req]}


def test_semantic_validation_uses_native_resolution_without_legacy_output_defaults(intents_catalog,safety_rules):
    from semantic_validator import validate_semantic_output
    result=validate_semantic_output(payload(request()),prepare_tank_bench(bench()),intents_catalog,safety_rules)
    assert result['is_valid'],result
    source=prepare_tank_bench(bench()); source['variables'][18]['llm_allowed']=False
    result=validate_semantic_output(payload(request(process_input='AI_Level_Raw')),source,intents_catalog,safety_rules)
    assert not result['is_valid']


def test_requested_digital_is_allocated_without_reserving_unused_channels(intents_catalog,safety_rules):
    from semantic_validator import validate_semantic_output
    source=prepare_tank_bench(bench()); source['variables'][9]['state']='FREE'; before=copy.deepcopy(source)
    result=validate_semantic_output(payload(request(resources={'alarm_output':'Q_Alarm'})),source,intents_catalog,safety_rules)
    assert result['is_valid'],result
    assert result['io_assignment_proposals']
    assert source==before


def test_malformed_resources_produce_diagnostic(intents_catalog,safety_rules):
    from semantic_validator import validate_semantic_output
    result=validate_semantic_output(payload(request(resources=['I_Start'])),prepare_tank_bench(bench()),intents_catalog,safety_rules)
    assert not result['is_valid'] and any('PID_RESOURCES' in e for e in result['errors'])
