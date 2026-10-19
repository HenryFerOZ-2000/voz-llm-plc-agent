"""Command/architecture consistency, independent of the model's chosen intent label."""
import copy
import json
from types import SimpleNamespace
import pytest

from llm_client import PLCInterpretationLLMClient
from llm_parser import parse_command
from semantic_validator import validate_semantic_output
from ir_builder import build_project_ir
from schemas import SemanticOutput, LLMUsageMetadata
from test_native_pid_resolution import payload, request
from tank_bench_setup import prepare_tank_bench
from test_tank_bench_setup import bench


def mapped():
    return prepare_tank_bench(bench())


def semantic(command, requirements, intent='INT_UNKNOWN'):
    result=payload(request())
    result.update(command_text=command, normalized_command=command.lower(), intent_id=intent,
                  functional_requirements=requirements)
    return result


@pytest.mark.parametrize('command',[
    'Llena hasta el 80 % y detén la bomba.',
    'Al alcanzar 75 por ciento, para el llenado del tanque.',
    'Vacía hasta el 20 % y después apaga la bomba.',
    'Enciende la bomba por debajo del 30 % y apágala al llegar al 80 %.',
])
def test_discrete_level_request_rejects_native_pid(command,intents_catalog,safety_rules):
    result=validate_semantic_output(semantic(command,[request()]),mapped(),intents_catalog,safety_rules)
    assert not result['is_valid'],result
    assert any('CONTROL_STRATEGY' in error for error in result['errors']),result


@pytest.mark.parametrize('command',[
    'Mantén el nivel del tanque al 50 % mediante PID usando el sensor de nivel y la válvula proporcional de llenado.',
    'Regula continuamente el nivel al 60 % con un controlador PID.',
])
def test_new_pid_request_cannot_be_satisfied_by_supervision(command,intents_catalog,safety_rules):
    result=validate_semantic_output(semantic(command,[{'type':'set_level_setpoint','value':50},
        {'type':'enable_pid'}],'INT_PID_SUPERVISOR'),mapped(),intents_catalog,safety_rules)
    assert not result['is_valid'],result
    assert any('CONTROL_STRATEGY' in error for error in result['errors']),result


def test_threshold_cannot_use_unbound_supervisor_measurement(intents_catalog,safety_rules):
    result=validate_semantic_output(semantic('Llena hasta el 80 % y detén la bomba.',
        [{'type':'enable_pump'},{'type':'safe_overfill_stop','limit':80}], 'INT_PID_SUPERVISOR'),mapped(),intents_catalog,safety_rules)
    assert not result['is_valid'],result
    assert any('CONTROL_' in error for error in result['errors']),result


def test_pump_cannot_be_silently_replaced_with_proportional_valve(intents_catalog,safety_rules):
    result=validate_semantic_output(semantic('Regula con PID el nivel al 50 % usando la bomba de velocidad variable.',
        [request()]),mapped(),intents_catalog,safety_rules)
    assert not result['is_valid'],result
    assert any('CONTROL_ACTUATOR' in error for error in result['errors']),result


def test_ir_cannot_bypass_command_consistency_gate():
    with pytest.raises(ValueError,match='CONTROL_STRATEGY'):
        build_project_ir(semantic('Llena hasta el 80 % y detén la bomba.',[request()]),mapped(),'SIEMENS_SCL_V18')


def test_normal_policy_has_system_priority_without_affecting_experimentation():
    client=PLCInterpretationLLMClient()
    marker='NORMAL_POLICY_PRIORITY_SENTINEL'
    normal=client._build_messages('x',{'normal_mode_policy':marker})
    assert any(message['role']=='system' and marker in message['content'] for message in normal)
    historical=client._build_messages('x',{})
    assert marker not in str(historical)
    assert historical[0]['content']==client._prompt_text()


def test_failed_retry_does_not_change_stop_at_limit_into_pid(intents_catalog,safety_rules):
    command='Llena hasta el 80 % y detén la bomba.'
    first=semantic(command,[{'type':'enable_pump'},{'type':'safe_overfill_stop','limit':80}], 'INT_PID_SUPERVISOR')
    second=semantic(command,[request()])
    class Client:
        def __init__(self): self.calls=[]
        def is_configured(self): return True
        def interpret_command(self,text,context):
            self.calls.append(copy.deepcopy(context))
            return SemanticOutput.model_validate({k:v for k,v in (first if len(self.calls)==1 else second).items()
                if k!='interaction_profile'}),LLMUsageMetadata(provider='offline_replay')
    client=Client()
    parsed=parse_command(command,mode='llm',interaction_profile='normal',io_map=mapped(),
                         intents_catalog=intents_catalog,safety_rules=safety_rules,llm_client=client)
    assert not parsed['semantic_validation']['is_valid'],parsed
    assert parsed['requires_clarification'],parsed
    assert parsed['clarification_question']


def test_valid_native_loop_remains_available(intents_catalog,safety_rules):
    value=semantic('Mantén el nivel al 50 % mediante PID usando la válvula proporcional de llenado.',[request()])
    assert validate_semantic_output(value,mapped(),intents_catalog,safety_rules)['is_valid']


def test_historical_supervisor_contract_is_unchanged(intents_catalog,safety_rules):
    value=semantic('Establece el nivel del tanque en 50 %.',[{'type':'set_level_setpoint','value':50}],'INT_PID_SUPERVISOR')
    value.pop('interaction_profile')
    assert validate_semantic_output(value,mapped(),intents_catalog,safety_rules)['is_valid']


def test_explicit_without_pid_is_respected(intents_catalog,safety_rules):
    value=semantic('Sin PID, llena el tanque hasta el 80 % y apaga la bomba.',[request()])
    result=validate_semantic_output(value,mapped(),intents_catalog,safety_rules)
    assert not result['is_valid'],result
    assert any('CONTROL_STRATEGY' in e for e in result['errors'])


def test_hysteresis_cannot_be_replaced_with_memoryless_comparison(intents_catalog,safety_rules):
    value=semantic('Enciende la bomba por debajo del 30 % y apágala al llegar al 80 %.',
                   [{'type':'conditional_output','condition':'AI_Level_Raw < 30','outputs':['Q_Aux_Output']}])
    result=validate_semantic_output(value,mapped(),intents_catalog,safety_rules)
    assert not result['is_valid'],result
    assert any('CONTROL_STRATEGY' in e for e in result['errors'])


def test_explicit_pid_cannot_be_replaced_by_fixed_analog_command(intents_catalog,safety_rules):
    value=semantic('Mantén el nivel al 50 % mediante PID usando la válvula proporcional.',
                   [{'type':'analog_output','output':'AO_Fill_Command','value':50,'unit':'%'}])
    result=validate_semantic_output(value,mapped(),intents_catalog,safety_rules)
    assert not result['is_valid'],result
    assert any('CONTROL_STRATEGY' in e for e in result['errors'])


def test_pump_cannot_be_replaced_by_fixed_valve_command(intents_catalog,safety_rules):
    value=semantic('Llena hasta el 80 % y detén la bomba.',
                   [{'type':'analog_output','output':'AO_Fill_Command','value':100,'unit':'%'}])
    result=validate_semantic_output(value,mapped(),intents_catalog,safety_rules)
    assert not result['is_valid'],result
    assert any('CONTROL_ACTUATOR' in e for e in result['errors'])


@pytest.mark.parametrize('prefix',['No uses el PID','Sin utilizar un PID','No emplees ese PID'])
def test_negative_pid_variants_are_respected(prefix,intents_catalog,safety_rules):
    result=validate_semantic_output(semantic(prefix+': llena hasta el 80 % y cierra la válvula.',[request()]),mapped(),intents_catalog,safety_rules)
    assert any('CONTROL_STRATEGY' in e for e in result['errors']),result


def test_existing_supervision_cannot_replace_controller(intents_catalog,safety_rules):
    result=validate_semantic_output(semantic('Supervisa el PID existente y establece su consigna al 50 %.',[request()]),mapped(),intents_catalog,safety_rules)
    assert any('CONTROL_STRATEGY' in e for e in result['errors']),result


def test_actuator_name_comparison_matches_native_case_insensitivity(intents_catalog,safety_rules):
    req=request(control_output='ao_fill_command')
    result=validate_semantic_output(semantic('Regula con PID el nivel al 50 % usando la bomba de velocidad variable.',[req]),mapped(),intents_catalog,safety_rules)
    assert any('CONTROL_ACTUATOR' in e for e in result['errors']),result


@pytest.mark.parametrize('command',[
    'Llena el tanque hasta el 80 % y cierra la válvula.',
    'Aplica PID al nivel al 50 % usando la válvula proporcional.',
    'Crea un PID para regular el nivel al 50 % usando la plantilla existente.',
])
def test_control_request_cannot_become_unconditional_fixed_output(command,intents_catalog,safety_rules):
    io=mapped()
    for entry in io['variables']:
        if entry.get('analog_config'): entry['analog_config']['confirmed']=True
    result=validate_semantic_output(semantic(command,[{'type':'analog_output','output':'AO_Fill_Command','value':50,'unit':'%'}]),io,intents_catalog,safety_rules)
    assert any('CONTROL_' in e for e in result['errors']),result


def test_timer_duration_is_not_a_second_process_threshold(intents_catalog,safety_rules):
    value=semantic('Al pulsar marcha, enciende la bomba por 10 segundos o hasta llegar al 80 %, luego apágala.',
        [{'type':'timed_sequence','start_input':'I_Digital_1','repeat':'once',
          'steps':[{'outputs':['Q_Digital_1'],'duration':'T#10s','advance_on':'AI_Level_Raw >= 80'}]}])
    io=mapped()
    for entry in io['variables']:
        if entry.get('analog_config'):entry['analog_config']['confirmed']=True
    result=validate_semantic_output(value,io,intents_catalog,safety_rules)
    assert result['is_valid'],result


def test_measurement_for_other_output_does_not_stop_fixed_actuator(intents_catalog,safety_rules):
    io=mapped()
    for entry in io['variables']:
        if entry.get('analog_config'):entry['analog_config']['confirmed']=True
    value=semantic('Llena hasta el 80 % y cierra la válvula.',[
        {'type':'analog_output','output':'AO_Fill_Command','value':50,'unit':'%'},
        {'type':'conditional_output','condition':'AI_Level_Raw >= 80','outputs':['Q_Digital_1']}])
    result=validate_semantic_output(value,io,intents_catalog,safety_rules)
    assert any('CONTROL_MEASUREMENT' in e for e in result['errors']),result


def test_finite_control_needs_measurement_even_if_map_has_none(intents_catalog,safety_rules):
    io=mapped();io['variables']=[v for v in io['variables'] if not v['name'].startswith('AI_')]
    for entry in io['variables']:
        if entry.get('analog_config'):entry['analog_config']['confirmed']=True
    value=semantic('Llena hasta el 80 % y cierra la válvula.',[{'type':'analog_output','output':'AO_Fill_Command','value':50,'unit':'%'}])
    result=validate_semantic_output(value,io,intents_catalog,safety_rules)
    assert any('CONTROL_MEASUREMENT' in e for e in result['errors']),result


def test_alarm_creation_does_not_request_new_controller(intents_catalog,safety_rules):
    value=semantic('Supervisa el PID existente y crea una alarma cuando el nivel supere el 80 %.',[request()])
    result=validate_semantic_output(value,mapped(),intents_catalog,safety_rules)
    assert any('CONTROL_STRATEGY' in e for e in result['errors']),result


def test_correct_sensor_condition_can_stop_same_analog_actuator(intents_catalog,safety_rules):
    io=mapped()
    for entry in io['variables']:
        if entry.get('analog_config'):entry['analog_config']['confirmed']=True
    value=semantic('Llena hasta el 80 % y cierra la válvula.',[
        {'type':'analog_output','output':'AO_Fill_Command','value':50,'unit':'%','condition':'AI_Level_Raw < 80'}])
    assert validate_semantic_output(value,io,intents_catalog,safety_rules)['is_valid']


@pytest.mark.parametrize('repeat',['hold_last','continuous'])
def test_finite_request_cannot_hold_or_repeat_filling(repeat,intents_catalog,safety_rules):
    io=mapped()
    for entry in io['variables']:
        if entry.get('analog_config'):entry['analog_config']['confirmed']=True
    steps=[{'outputs':['Q_Digital_1'],'advance_on':'AI_Level_Raw >= 80'}]
    if repeat=='continuous':steps.append({'outputs':[],'duration':'T#1s'})
    value=semantic('Al pulsar marcha, llena hasta el 80 % y apaga la bomba.',[
        {'type':'timed_sequence','start_input':'I_Digital_1','stop_input':'I_Digital_2',
         'repeat':repeat,'steps':steps}])
    result=validate_semantic_output(value,io,intents_catalog,safety_rules)
    assert any('CONTROL_STRATEGY' in e for e in result['errors']),result


def test_independent_requested_pilot_does_not_need_level_cutoff(intents_catalog,safety_rules):
    io=mapped()
    for entry in io['variables']:
        if entry.get('analog_config'):entry['analog_config']['confirmed']=True
    value=semantic('Llena hasta el 80 % y cierra la válvula. Enciende el piloto mientras marcha esté pulsada.',[
        {'type':'analog_output','output':'AO_Fill_Command','value':50,'unit':'%','condition':'AI_Level_Raw < 80'},
        {'type':'conditional_output','condition':'I_Digital_1','outputs':['Q_Digital_1']}])
    assert validate_semantic_output(value,io,intents_catalog,safety_rules)['is_valid']


def test_normal_schema_retry_receives_format_error(monkeypatch):
    calls=[]
    value=semantic('Llena hasta el 80 % y detén la bomba.',[])
    value.pop('interaction_profile')
    def create(**kwargs):
        calls.append(kwargs)
        result={**value,'requested_control_behavior':'THRESHOLD'} if len(calls)==1 else value
        return SimpleNamespace(output_text=json.dumps(result),usage=None,id='offline')
    client=PLCInterpretationLLMClient(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    monkeypatch.setattr(client,'is_configured',lambda:True)
    client.config={**client.config,'max_retries':1}
    output,usage=client.interpret_command(value['command_text'],{'normal_mode_policy':'NORMAL'})
    assert output.command_text==value['command_text']
    assert usage.retries_used==1
    assert 'extra_forbidden' in str(calls[1]['input'])
    assert 'requested_control_behavior' not in SemanticOutput.model_fields


def test_normal_prompt_separates_context_from_response_schema():
    messages=PLCInterpretationLLMClient()._build_messages('x',{'normal_mode_policy':'NORMAL'})
    assert all(field in messages[0]['content'] for field in SemanticOutput.model_fields)
    assert 'solo metadatos' in messages[0]['content']
