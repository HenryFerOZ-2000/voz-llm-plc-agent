import pytest
from test_native_pid_generation import project


def bindings(**kw):
    from pid_commissioning import build_pid_process_bindings
    return build_pid_process_bindings(project(**kw))


def context(**kw):
    return {'mode':'SIMULATION','target_type':'PLCSIM_ADVANCED','connected':True,'cpu_state':'RUN',
            'program_verified':True,'sensor_valid':True,'fault':False,'running':True,'tuning_authorized':True,**kw}


def test_only_declared_pid_members_are_writable():
    from pid_commissioning import validate_commissioning_write
    b=bindings(loop_id='Otro')
    assert b['instance_db']=='DB_PID_Otro'
    assert validate_commissioning_write(b,'SP',60,context())['value']==60
    for name in ('ErrorBits','PV','ControllerState','PID_Probe.Mode','Unknown'):
        with pytest.raises(ValueError,match='PID_WRITE'):validate_commissioning_write(b,name,True,context())


def test_setpoint_is_checked_in_map_units():
    from pid_commissioning import validate_commissioning_write
    for value in (-1,101,float('nan'),True):
        with pytest.raises(ValueError):validate_commissioning_write(bindings(),'SP',value,context())


def test_v2_write_does_not_require_environment_or_calibration():
    from pid_commissioning import validate_commissioning_write
    b=bindings()
    c=context()
    c.pop('mode')
    assert b['calibration_confirmed'] is False
    assert validate_commissioning_write(b,'SP',60,c)['value']==60
    with pytest.raises(ValueError,match='PID_WRITE'):
        validate_commissioning_write(b,'SP',60,{**c,'target_type':'PHYSICAL_PLC'})


def test_tuning_requires_explicit_request_and_permissives():
    from pid_commissioning import validate_commissioning_write
    for flags in ({'tuning_authorized':False},{'sensor_valid':False},{'fault':True},{'program_verified':False}):
        with pytest.raises(ValueError):validate_commissioning_write(bindings(),'CmdPretune',True,context(**flags))
    assert validate_commissioning_write(bindings(),'CmdPretune',True,context())['pulse']


def test_generation_preserves_pending_calibration_for_download_gate():
    from pid_commissioning import validate_generation_mode
    from tank_bench_setup import prepare_tank_bench
    from test_tank_bench_setup import bench
    from test_native_pid_resolution import payload,request
    loop=validate_generation_mode(payload(request(mode='PHYSICAL')),prepare_tank_bench(bench()),'PHYSICAL')[0]
    assert loop.input_binding['analog_config']['confirmed'] is False


def test_map_connections_are_required_before_generation():
    from pid_commissioning import validate_generation_mode
    from test_native_pid_resolution import payload,request
    with pytest.raises(ValueError,match='PID_DEVICE_MISSING'): validate_generation_mode(payload(request(mode=None)),{'variables':[]},'')


def test_runtime_native_types_are_scoped_and_read_only(tmp_path):
    import json,subprocess
    from plcsim_runtime import build_runtime_bridge
    built=build_runtime_bridge();assert built['built'],built
    request=tmp_path/'request.json';out=tmp_path/'report.json'
    request.write_text(json.dumps({'action':'self_test','result_path':str(out)}))
    run=subprocess.run([built['exe_path'],str(request)],capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr
    report=json.loads(out.read_text(encoding='utf-8'))
    assert 'native.int_read' in json.dumps(report)
    assert 'native.diagnostic_write_denied' in json.dumps(report)


def test_parser_ignores_legacy_pid_mode_without_changing_frozen_contract(intents_catalog,safety_rules):
    from llm_parser import parse_command
    from tank_bench_setup import prepare_tank_bench
    from test_tank_bench_setup import bench
    from test_native_pid_resolution import payload,request
    result=parse_command('Controla el nivel con PID al 50 %',mode='llm',interaction_profile='normal',pid_execution_mode='SIMULATION',
        io_map=prepare_tank_bench(bench()),intents_catalog=intents_catalog,safety_rules=safety_rules,
        llm_response_text=payload(request(mode=None)))
    assert result['semantic_validation']['is_valid'],result['semantic_validation']
    assert 'pid_mode' not in result['parameters']


def test_runtime_rejects_a_stale_program_even_when_db_name_matches():
    from pid_commissioning import PidCommissioningSession
    class IO:
        def _bridge(self,*args):
            return {'status':'PLCSIM_IO_PASSED','reads':[{'name':'DB_PID_LevelLoop.Build00','value':123}]}
    with pytest.raises(ValueError,match='PID_PROGRAM_MISMATCH'):
        PidCommissioningSession(bindings(),IO(),context()).read()


def test_commissioning_reads_the_typed_sample_contract():
    from pid_commissioning import PidCommissioningSession
    b=bindings();values={'DB_PID_LevelLoop.'+f'Build{i:02d}':v for i,v in enumerate(b['build_signature'])}
    values.update({'DB_PID_LevelLoop.PV':42.5,'DB_PID_LevelLoop.CV':40.0,
        'DB_PID_LevelLoop.ControllerState':3,'DB_PID_LevelLoop.ErrorBits':0,
        'DB_PID_LevelLoop.SensorValid':True,'DB_PID_LevelLoop.Fault':False,'DB_PID_LevelLoop.Running':True})
    class IO:
        def _bridge(self,action,payload):
            if action!='io_sequence':return {'status':'PLCSIM_IO_ADDRESS_UNSUPPORTED','errors':["area '' no soportada"]}
            return {'status':'PLCSIM_IO_PASSED','samples':[{'t_ms':0,'values':values}]}
    c=context();actual=PidCommissioningSession(b,IO(),c).read()
    assert actual['PV']==42.5 and actual['ControllerState']==3 and actual['ErrorBits']==0 and c['program_verified']


def test_hybrid_does_not_add_legacy_writers_to_a_native_pid():
    from llm_parser import _merge_functional_requirements
    primary=[{'type':'pid_control','loop_id':'LevelLoop'}]
    assert _merge_functional_requirements(primary,[{'type':'activate_output','output':'AO_Fill_Command'}],'INT_UNKNOWN')==primary


@pytest.mark.parametrize('command',['CmdPretune','CmdFinetune'])
def test_tuning_leaves_software_manual_in_the_same_write_group(command):
    from pid_commissioning import PidCommissioningSession
    b=bindings();db=b['instance_db']
    values={db+'.'+f'Build{i:02d}':v for i,v in enumerate(b['build_signature'])}
    values.update({db+'.SensorValid':True,db+'.Fault':False,db+'.Running':True})
    calls=[]
    class IO:
        def _guard_write(self):pass
        def _bridge(self,action,payload):
            calls.append(payload)
            return {'status':'PLCSIM_IO_PASSED','samples':[{'values':values}]}
    PidCommissioningSession(b,IO(),context()).write(command,True)
    request=next(p for p in calls if p['steps'][0].get('op')=='set')
    writes=request['steps'][0]['writes']
    assert [(w['signal']['member'],w['value']) for w in writes]==[('CmdManual',False),(command,True)]


def test_v2_write_carries_loaded_identity_to_native_write_boundary():
    from pid_commissioning import PidCommissioningSession
    b=bindings();calls=[]
    values={b['instance_db']+'.'+f'Build{i:02d}':v for i,v in enumerate(b['build_signature'])}
    class IO:
        def _guard_write(self):pass
        def _bridge(self,action,payload):
            calls.append(payload)
            return {'status':'PLCSIM_IO_PASSED','samples':[{'values':values}]}
    PidCommissioningSession(b,IO(),context()).write('CmdStop',True)
    request=next(p for p in calls if p['steps'][0].get('op')=='set')
    assert request['native_pid_identity']=={'db':b['instance_db'],'build_signature':b['build_signature']}
