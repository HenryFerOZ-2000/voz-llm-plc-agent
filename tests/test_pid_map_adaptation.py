import copy
from control_strategy import control_consistency_errors
import pytest
from pathlib import Path
import product_engine as engine
from trial_experiments import development_validation as development


@pytest.mark.parametrize('case_id',['discrete_relocated','fill_relocated','hysteresis_relocated','pid_relocated','pid_db'])
def test_alternate_maps_use_shared_engine_without_source_mutation(case_id,project_root,tmp_path,intents_catalog,safety_rules):
    cases=development.build_map_adaptation_cases(project_root)
    case=next(c for c in cases if c['case_id']==case_id)
    source=case['io_map'];before=copy.deepcopy(source)
    semantic=engine.interpret_product_command(case['command_text'],io_map=source,intents_catalog=intents_catalog,
        safety_rules=safety_rules,mode='llm',llm_response_text=case['semantic_response'])
    proposals=(semantic.get('semantic_validation') or {}).get('io_assignment_proposals') or []
    semantic,working,_=engine.resolve_product_assignments(semantic,source,proposals,intents_catalog,safety_rules)
    result=engine.generate_product_package(semantic,target_platform='SIEMENS_SCL_V18',io_map=working,
        intents_catalog=intents_catalog,safety_rules=safety_rules,output_dir=tmp_path/'p')
    assert result['verification']['is_valid'],result['verification']
    assert source==before
    code=(Path(result['package_dir'])/'siemens_source.scl').read_text(encoding='utf-8')
    assert '%IW4' not in code and '%QW4' not in code
    if case_id=='pid_relocated':
        import json
        loop=json.loads((Path(result['package_dir'])/'pid_infrastructure.json').read_text())['loops'][0]
        assert loop['input_binding']['address']=='%IW64'
        assert loop['output_binding']['address']=='%QW64'
        assert loop['process_input']=='AI_Level_Raw_A'
    if case_id=='pid_db':
        assert 'DATA_BLOCK "DB_AlternateProcess"' in code
        assert 'INT_TO_REAL(' not in code


def test_discrete_level_switch_is_a_declared_measurement():
    semantic={'interaction_profile':'normal','command_text':'Llena el tanque hasta que el sensor de nivel alto se active y apaga la electroválvula.',
        'intent_id':'INT_UNKNOWN','functional_requirements':[{'type':'timed_sequence','start_input':'I_Start','stop_input':'I_Stop',
            'repeat':'once','steps':[{'outputs':['Q_Valve'],'advance_on':'I_LevelHigh'}]}]}
    source={'variables':[{'name':'I_LevelHigh','class':'input','type':'BOOL','location':'%IX32.2',
        'aliases':['sensor de nivel alto'],'llm_allowed':True},
        {'name':'Q_Valve','class':'output','type':'BOOL','location':'%QX24.0','aliases':['electrovalvula']}]}
    assert control_consistency_errors(semantic,source)==[]


def test_declared_supervisory_measurement_can_control_threshold():
    semantic={'interaction_profile':'normal','command_text':'Apaga la bomba cuando el nivel llegue al 95 %.',
        'intent_id':'INT_UNKNOWN','functional_requirements':[
            {'type':'conditional_output','condition':'Level_PV < 95','outputs':['Q_Pump']},
            {'type':'force_off','condition':'Level_PV >= 95','outputs':['Q_Pump']}]}
    source={'variables':[{'name':'Level_PV','class':'internal','type':'REAL','location':'','llm_allowed':True},
        {'name':'Q_Pump','class':'output','type':'BOOL','location':'%QX26.0','aliases':['bomba']}]}
    before=copy.deepcopy(source)
    assert control_consistency_errors(semantic,source)==[]
    assert source==before
    source['variables'].pop(0)
    assert any('CONTROL_MEASUREMENT_UNBOUND' in e for e in control_consistency_errors(semantic,source))


@pytest.mark.parametrize('defect',['missing','blocked','ambiguous','overlap','scale','units'])
def test_incompatible_native_map_is_rejected(defect,project_root,tmp_path,intents_catalog,safety_rules):
    case=next(c for c in development.build_map_adaptation_cases(project_root) if c['case_id']=='pid_relocated')
    source=copy.deepcopy(case['io_map']);response=copy.deepcopy(case['semantic_response'])
    sensor=next(v for v in source['variables'] if v['name']=='AI_Level_Raw_A')
    valve=next(v for v in source['variables'] if v['name']=='AO_Fill_Command_A')
    if defect=='missing':source['variables'].remove(valve)
    if defect=='blocked':valve['llm_allowed']=False
    if defect=='ambiguous':
        other=copy.deepcopy(valve);other.update(name='AO_AnotherFill',location='%QW100');source['variables'].append(other)
        for r in response['functional_requirements']:
            if r.get('type')=='pid_control':r.pop('control_output',None)
    if defect=='overlap':
        start=next(v for v in source['variables'] if v['name']=='I_Start_A');start['location']='%IX64.0'
    if defect=='scale':sensor['analog_config']['raw_max']=sensor['analog_config']['raw_min']
    if defect=='units':sensor['analog_config']['engineering_unit']='bar'
    before=copy.deepcopy(source)
    semantic=engine.interpret_product_command(case['command_text'],io_map=source,intents_catalog=intents_catalog,
        safety_rules=safety_rules,mode='llm',llm_response_text=response)
    validation=semantic.get('semantic_validation') or {}
    if validation.get('is_valid') is True and not semantic.get('requires_clarification'):
        try:
            result=engine.generate_product_package(semantic,target_platform='SIEMENS_SCL_V18',io_map=source,
                intents_catalog=intents_catalog,safety_rules=safety_rules,output_dir=tmp_path/'p')
        except ValueError:pass
        else:assert not result['verification']['is_valid'],(defect,result['verification'])
    assert source==before


def test_blocked_supervisory_measurement_cannot_be_used():
    semantic={'interaction_profile':'normal','intent_id':'INT_PID_SUPERVISOR','command_text':'Activa la alarma si el nivel supera 90 %.',
        'functional_requirements':[{'type':'high_level_alarm','threshold':90.,'alarm_output':'Q_Alarm'}]}
    source={'variables':[{'name':'Level_PV','class':'internal','type':'REAL','location':'','llm_allowed':False}]}
    assert any('CONTROL_MEASUREMENT_UNBOUND' in e for e in control_consistency_errors(semantic,source))


@pytest.mark.parametrize('stop_signal',['I_Stop_A','I_Emergency_A'])
def test_renamed_start_needs_a_new_press_after_stop_in_finite_fill(stop_signal,project_root,tmp_path,intents_catalog,safety_rules):
    from trial_experiments.scl_sim import SclMachine
    case=next(c for c in development.build_map_adaptation_cases(project_root) if c['case_id']=='fill_relocated')
    semantic=engine.interpret_product_command(case['command_text'],io_map=case['io_map'],intents_catalog=intents_catalog,
        safety_rules=safety_rules,mode='llm',llm_response_text=case['semantic_response'])
    semantic,working,_=engine.resolve_product_assignments(semantic,case['io_map'],
        semantic['semantic_validation'].get('io_assignment_proposals',[]),intents_catalog,safety_rules)
    generated=engine.generate_product_package(semantic,target_platform='SIEMENS_SCL_V18',io_map=working,
        intents_catalog=intents_catalog,safety_rules=safety_rules,output_dir=tmp_path)
    plc=SclMachine((Path(generated['package_dir'])/'siemens_source.scl').read_text(encoding='utf-8'))
    io={'I_Start_A':False,'I_Stop_A':False,'I_Emergency_A':False,'AI_Level_Raw_A':5529}
    plc.initialize(io);plc.scan(io)
    io['I_Start_A']=True;plc.scan(io);assert io['AO_Fill_Command_A']==27648
    io[stop_signal]=True;plc.scan(io);assert io['AO_Fill_Command_A']==0
    io[stop_signal]=False;plc.scan(io)
    assert io['AO_Fill_Command_A']==0,'A renamed Start must not restart while held after Stop/Emergency'
    io['I_Start_A']=False;plc.scan(io);io['I_Start_A']=True;plc.scan(io)
    assert io['AO_Fill_Command_A']==27648
