"""Exact user commands and real response regressions; no API calls."""
import copy,json
from pathlib import Path
import pytest
import product_engine as P
from io_allocator import propose_assignment
from schemas import SemanticOutput,LLMUsageMetadata
from trial_experiments.scl_sim import SclMachine

FIX=Path(__file__).parent/'fixtures/natural_commands'
def read(name):return json.loads((FIX/name).read_text(encoding='utf-8'))
def mapping(confirmed=False):
    value=read('prepared_map.json')
    if confirmed:
        for entry in value['variables']:
            if 'analog_config' in entry:entry['analog_config']['confirmed']=True
    return value
def interpret(value,intents_catalog,safety_rules,**kwargs):
    return P.interpret_product_command(value['command_text'],io_map=mapping(True),intents_catalog=intents_catalog,
        safety_rules=safety_rules,mode='llm',**kwargs)


@pytest.mark.parametrize('allocation_request',[{}, {'name':'Q_Test'}, {'functional_name_hint':None}, {'functional_name_hint':42}])
def test_incomplete_assignment_never_crashes(allocation_request):
    result=propose_assignment(mapping(),[allocation_request])
    assert len(result)==1
    assert result[0]['blocked'] or isinstance(result[0]['proposed_name'],str)


def test_real_hysteresis_response_returns_validation_instead_of_exception(intents_catalog,safety_rules):
    value=read('hysteresis_response.json')
    result=interpret(value,intents_catalog,safety_rules,llm_response_text=value)
    assert isinstance(result['semantic_validation']['is_valid'],bool)


def test_incomplete_model_sequence_is_corrected_before_generic_stage_question(intents_catalog,safety_rules):
    command=read('commands.json')['threshold']
    wrong=read('hysteresis_response.json')
    wrong.update(command_text=command,normalized_command=command.lower(),requested_io_assignments=[],
        recognized_tags=['I_Start','I_Stop','I_Emergency','AI_Level_Raw','Q_Traffic_Green'],
        functional_requirements=[{'type':'timed_sequence','start_input':'I_Start','stop_input':'I_Stop',
            'repeat':'once','steps':[]},{'type':'force_off','condition':'I_Emergency','outputs':['Q_Traffic_Green']}])
    good=copy.deepcopy(wrong)
    good['functional_requirements'][0]['steps']=[{'outputs':['Q_Traffic_Green'],'advance_on':'AI_Level_Raw >= 80','condition_unit':'%'}]
    class Client:
        def __init__(self):self.calls=[]
        def is_configured(self):return True
        def interpret_command(self,text,context):
            self.calls.append(copy.deepcopy(context))
            return SemanticOutput.model_validate(wrong if len(self.calls)==1 else good),LLMUsageMetadata(provider='offline')
    client=Client();result=interpret(wrong,intents_catalog,safety_rules,llm_client=client)
    assert len(client.calls)==2,result
    assert result['semantic_validation']['is_valid'],result['semantic_validation']
    assert not result['requires_clarification']


@pytest.mark.parametrize('stop_signal',['I_Stop','I_Emergency'])
def test_discrete_command_requires_fresh_start_after_stop(stop_signal,tmp_path,intents_catalog,safety_rules):
    value=read('discrete_response.json')
    result=interpret(value,intents_catalog,safety_rules,llm_response_text=value)
    package=P.generate_product_package(result,target_platform='SIEMENS_SCL_V18',io_map=mapping(True),
        intents_catalog=intents_catalog,safety_rules=safety_rules,output_dir=tmp_path/'packages')
    plc=SclMachine((Path(package['package_dir'])/'siemens_source.scl').read_text(encoding='utf-8'))
    io={'I_Start':False,'I_Stop':False,'I_Emergency':False};plc.initialize(io);plc.scan(io)
    output=value['parameters']['motor_output']
    io['I_Start']=True;plc.scan(io);assert io[output]
    io[stop_signal]=True;plc.scan(io);assert not io[output]
    io[stop_signal]=False;plc.scan(io)
    assert not io[output],'Releasing Stop/Emergency with Start held must not restart the output'
    io['I_Start']=False;plc.scan(io);io['I_Start']=True;plc.scan(io);assert io[output]


def process_case(name,tmp_path,catalog,rules):
    value=read(name+'_complete.json')
    result=interpret(value,catalog,rules,llm_response_text=value)
    result,working,_=P.resolve_product_assignments(result,mapping(True),result['semantic_validation'].get('io_assignment_proposals',[]),catalog,rules)
    package=P.generate_product_package(result,target_platform='SIEMENS_SCL_V18',io_map=working,
        intents_catalog=catalog,safety_rules=rules,output_dir=tmp_path/'packages')
    assert package['verification']['is_valid'],package['verification']
    plc=SclMachine((Path(package['package_dir'])/'siemens_source.scl').read_text(encoding='utf-8'))
    io={'I_Start':False,'I_Stop':False,'I_Emergency':False,'AI_Level_Raw':round(20*27648/100)}
    plc.initialize(io);plc.scan(io)
    return result,plc,io


def test_hysteresis_stop_does_not_restart_with_start_held(tmp_path,intents_catalog,safety_rules):
    result,plc,io=process_case('hysteresis',tmp_path,intents_catalog,safety_rules)
    output=next(r['output'] for r in result['functional_requirements'] if r['type']=='hysteresis_switch')
    io['I_Start']=True;plc.scan(io);assert io[output]
    io['I_Stop']=True;plc.scan(io);assert not io[output]
    io['I_Stop']=False;plc.scan(io);assert not io[output]
    io['I_Start']=False;plc.scan(io);io['I_Start']=True;plc.scan(io);assert io[output]


def test_hysteresis_does_not_resume_stale_state_in_middle_band(tmp_path,intents_catalog,safety_rules):
    result,plc,io=process_case('hysteresis',tmp_path,intents_catalog,safety_rules)
    output=next(r['output'] for r in result['functional_requirements'] if r['type']=='hysteresis_switch')
    io['I_Start']=True;plc.scan(io);assert io[output]
    io['I_Start']=False;plc.scan(io)
    io['I_Stop']=True;plc.scan(io);assert not io[output]
    io.update(I_Stop=False,AI_Level_Raw=round(50*27648/100));plc.scan(io)
    io['I_Start']=True;plc.scan(io)
    assert not io[output],'A cleared controller starts OFF inside the hysteresis band'


def test_threshold_waits_for_new_start_after_reaching_limit(tmp_path,intents_catalog,safety_rules):
    result,plc,io=process_case('threshold_answered',tmp_path,intents_catalog,safety_rules)
    output=next(r['output'] for r in result['functional_requirements'] if r['type']=='analog_output')
    io['I_Start']=True;plc.scan(io);assert io[output]>0
    io['AI_Level_Raw']=round(85*27648/100);plc.scan(io);assert io[output]==0
    io['AI_Level_Raw']=round(50*27648/100);plc.scan(io)
    assert io[output]==0,'Falling level must not restart a completed finite cycle with Start held'


@pytest.mark.parametrize('condition',['NOT I_Start','I_Start OR I_Reset','I_Start AND I_Reset'])
def test_arbitrary_latch_conditions_are_not_rewritten_as_start_pulses(condition,intents_catalog,safety_rules):
    from ir_builder import build_project_ir
    from code_generator import generate_implementation_from_ir
    semantic={'intent_id':'INT_UNKNOWN','parameters':{},'interaction_profile':'normal',
        'command_text':'Enclavamiento con condición explícita.',
        'functional_requirements':[{'type':'latch','set':condition,'reset':'I_Stop','outputs':['Q_Traffic_Green']}]}
    project=build_project_ir(semantic,mapping(True),'SIEMENS_SCL_V18')
    body=generate_implementation_from_ir(project)
    assert f'ELSIF {condition} THEN' in body,body


@pytest.mark.parametrize('composed',[True,False])
def test_start_memory_never_reuses_user_map_variable(composed):
    from ir_builder import build_project_ir
    value=read('discrete_response.json')
    value['interaction_profile']='normal'
    if composed:
        value.update(intent_id='INT_UNKNOWN',parameters={},functional_requirements=[
            {'type':'latch','set':'I_Start','reset':'I_Stop','outputs':['Q_Traffic_Green']}])
    name='M_ProductStart1_StartPrevious' if composed else value['parameters']['run_latch']+'_StartPrevious'
    io_map=mapping(True)
    io_map['variables'].append({'name':name,'type':'REAL','class':'internal','initial_value':'0.0','location':''})
    with pytest.raises(ValueError,match='START_SYMBOL_CONFLICT'):
        build_project_ir(value,io_map,'SIEMENS_SCL_V18')


def test_empty_set_uses_effective_set_condition():
    from ir_builder import build_project_ir
    from code_generator import generate_implementation_from_ir
    semantic={'intent_id':'INT_UNKNOWN','parameters':{},'interaction_profile':'normal',
        'command_text':'Enclavamiento con Start y Stop.',
        'functional_requirements':[{'type':'latch','set':'','set_condition':'(I_Start)',
            'reset':'I_Stop','outputs':['Q_Traffic_Green']}]}
    project=build_project_ir(semantic,mapping(True),'SIEMENS_SCL_V18')
    body=generate_implementation_from_ir(project)
    assert 'ELSIF M_ProductStart1_StartPulse THEN' in body,body


def test_start_memory_never_collides_with_explicit_variable_case_insensitively():
    from ir_builder import build_project_ir
    semantic={'intent_id':'INT_UNKNOWN','parameters':{},'interaction_profile':'normal',
        'command_text':'Enclavamiento con Start y Stop.',
        'functional_requirements':[{'type':'latch','set':'I_Start','reset':'I_Stop','outputs':['Q_Traffic_Green']},
            {'name':'M_ProductStart1_startPrevious','type':'REAL'}]}
    with pytest.raises(ValueError,match='START_SYMBOL_CONFLICT'):
        build_project_ir(semantic,mapping(True),'SIEMENS_SCL_V18')
