import copy
from pathlib import Path

import pytest

import pid_native_validation as native
from test_native_pid_trial_bundle import current_package, PROTOCOL, PROFILE


def required_checks():
    return [{'case':name,'required':True,'passed':True}
            for name in ('stop','sensor_fault','held_start_after_reset','setpoint_limit')]


def test_undeclared_optional_checks_are_not_false_failures():
    assert hasattr(native,'summarize_required_checks'), 'Missing applicability-aware checks'
    checks=required_checks()+[{'case':name,'required':False,'passed':False,'status':'NOT_APPLICABLE'}
                             for name in ('emergency','overfill')]
    result=native.summarize_required_checks(checks)
    assert result['status']=='PASSED'
    assert result['required_count']==4
    assert result['not_applicable']==['emergency','overfill']


@pytest.mark.parametrize('changes',[[],[{'case':'emergency','required':True,'passed':False,'status':'NOT_APPLICABLE'}],
    [{'case':'overfill','required':True,'passed':False,'status':'FAILED'}]])
def test_required_check_missing_or_failed_prevents_pass(changes):
    assert hasattr(native,'summarize_required_checks')
    checks=[] if not changes else required_checks()+changes
    assert native.summarize_required_checks(checks)['status']=='FAILED'


def test_frozen_protocol_is_validated_before_compiled_project_or_runtime(tmp_path,current_package,monkeypatch):
    monkeypatch.setattr(native,'load_tia_config',lambda _: {'download_targets':{'normal':{'target_type':'PLCSIM_ADVANCED'}}})
    monkeypatch.setattr(native,'native_download_project',lambda *a:pytest.fail('Compile path consulted before invalid protocol rejection'))
    result=native.run_map_pid_validation(tmp_path,Path(current_package['package_dir']),download=False,
        profile=PROFILE,protocol={**PROTOCOL,'tolerance':0})
    assert result['status']=='FAILED'
    assert 'PID_PROTOCOL' in result['reason']


def test_experimental_protocol_never_redownloads_via_normal_route(tmp_path,current_package,monkeypatch):
    monkeypatch.setattr(native,'load_tia_config',lambda _: {'download_targets':{'normal':{'target_type':'PLCSIM_ADVANCED'}}})
    monkeypatch.setattr(native,'download_program_to_plc',lambda *a:pytest.fail('Normal route attempted'))
    result=native.run_map_pid_validation(tmp_path,Path(current_package['package_dir']),download=True,
        profile=PROFILE,protocol=PROTOCOL,execution_context={'workspace_id':'T0001'})
    assert result['status']=='FAILED'
    assert 'PID_EXPERIMENT_CONTEXT' in result['reason']


def test_reuse_enters_automatic_without_requesting_new_tuning():
    assert hasattr(native,'enter_verified_automatic'), 'Missing verified automatic transition'
    class Session:
        def __init__(self):self.writes=[]
        def write(self,name,value):self.writes.append((name,value))
    session=Session()
    native.enter_verified_automatic(session,{'ParametersConfirmed':True})
    assert session.writes==[('CmdManual',False)]
    with pytest.raises(ValueError,match='PID_PARAMETERS_UNVERIFIED'):
        native.enter_verified_automatic(session,{'ParametersConfirmed':False})


def test_declared_overfill_at_sensor_high_limit_is_still_required():
    assert hasattr(native,'overfill_stimulus')
    assert native.overfill_stimulus(None,100) is None
    assert native.overfill_stimulus(95,100)==97.5
    assert native.overfill_stimulus(100,100)==100
    with pytest.raises(ValueError,match='PID_OVERFILL'):
        native.overfill_stimulus(101,100)


def test_standalone_native_evaluation_uses_frozen_inputs_and_separate_verdict(tmp_path,current_package,monkeypatch):
    import json,zipfile
    import plcsim_runtime
    from trial_experiments import deferred_evaluator as DE, native_pid_protocol as NP, oracle_runner
    from test_phase4a_deferred_evaluation import _project,_master
    assert hasattr(DE,'run_frozen_native_development'), 'Missing integrated standalone native evaluator'
    root=_project(tmp_path/'root');_master(root)
    run=NP.create_native_validation_run(root,Path(current_package['package_dir']),PROTOCOL,PROFILE,tmp_path/'n')
    monkeypatch.setattr(DE,'environment_precheck',lambda *a:{'ok':True})
    monkeypatch.setattr(plcsim_runtime,'get_plcsim_runtime_status',lambda *a:{'connected':True,'cpu_state':'RUN','instance_name':'TESIS_PLC_SIM'})
    monkeypatch.setattr(oracle_runner,'run_oracle',lambda *a:pytest.fail('Canonical Oracle cannot become dynamic native verdict'))
    def bridge(request,workspace,project_root=None,on_archived=None):
        assert request['purpose']=='experiment' and request['physical_download_allowed'] is False
        project=Path(request['working_dir'])/'MASTER/MASTER.ap18'
        project.parent.mkdir(parents=True);project.write_bytes(b'compiled')
        archive=Path(request['trial_archive_dir'])/request['trial_archive_name']
        with zipfile.ZipFile(archive,'w') as stored:stored.writestr('MASTER.ap18',b'compiled')
        decision=on_archived({'archive_path':str(archive),'archive_sha256':DE.sha256_file(archive)})
        assert decision['download'] is True
        loop=request['native_pid']['pid_manifest']['loops'][0]
        return {**request['native_pid'],'status':'TIA_COMPILATION_PASSED','error_count':0,
            'project_path':str(project),'working_project_path':str(project),'pid_project_mode':'EXPERIMENT_COPY',
            'configuration_hash':loop['configuration_hash'],'download':{'status':'TIA_DOWNLOAD_PASSED','success':True},
            'archive_status':'CREATED','pid_cyclic_ob':{'attributes':{'SecondaryType':'CyclicInterrupt','CyclicTime':'100000'}}}
    monkeypatch.setattr(DE,'run_bridge',bridge)
    def validate(project_root,package_dir,**kwargs):
        assert kwargs['download'] is False
        assert kwargs['profile']==PROFILE and kwargs['protocol']==PROTOCOL
        assert kwargs['execution_context']['run_id']==run.name
        return {'status':'PASSED','native_execution_verified':True,'cleanup_verified':True}
    monkeypatch.setattr(native,'run_map_pid_validation',validate)
    result=DE.run_frozen_native_development(root,run)
    assert result['status']=='PASSED'
    record=json.loads((run/'native_run.json').read_text())
    assert 'case_id' not in record and 'oracle' not in record
    assert record['native_validation']['status']=='PASSED'
    assert NP.verify_native_run(run)['domain']=='NATIVE_PID_DEVELOPMENT'
