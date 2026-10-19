import importlib
import json
from pathlib import Path

import pytest

from test_native_pid_trial_bundle import current_package, PROTOCOL, PROFILE
from trial_experiments import deferred_evaluator as DE, native_pid_protocol as NP


def test_declared_db_process_ports_never_become_physical_plc_tags(project_root,tmp_path,intents_catalog,safety_rules):
    import product_engine as engine
    from trial_experiments.development_validation import build_map_adaptation_cases
    case=next(c for c in build_map_adaptation_cases(project_root) if c['case_id']=='pid_db')
    semantic=engine.interpret_product_command(case['command_text'],io_map=case['io_map'],intents_catalog=intents_catalog,
        safety_rules=safety_rules,mode='llm',llm_response_text=case['semantic_response'])
    result=engine.generate_product_package(semantic,target_platform='SIEMENS_SCL_V18',io_map=case['io_map'],
        intents_catalog=intents_catalog,safety_rules=safety_rules,output_dir=tmp_path)
    variables=json.loads((Path(result['package_dir'])/'variables.json').read_text(encoding='utf-8'))
    ports=[v for v in variables if v.get('tia_scope')=='PROCESS_DB_PORT']
    assert len(ports)==3
    tags=DE.trial_tag_payload(variables,{})
    assert {t['name'] for t in tags}=={'I_Start_A','I_Stop_A','I_Emergency_A'}
    assert all(t['address'] for t in tags)


def test_native_staging_is_frozen_and_never_uses_normal_cache(tmp_path,current_package):
    assert hasattr(NP,'build_native_trial_request'), 'Missing isolated native staging'
    run=NP.create_native_validation_run(tmp_path,Path(current_package['package_dir']),PROTOCOL,PROFILE,tmp_path/'n')
    workspace=tmp_path/'tiaw/T0001'
    payload=NP.build_native_trial_request(run,workspace,NP.verify_native_run(run))
    assert Path(payload['source_path']).is_relative_to(workspace)
    assert Path(payload['source_path']).read_bytes()==(run/'program.scl').read_bytes()
    assert payload['native_pid']['pid_manifest']['schema_version']==2
    assert 'template_project_path' not in payload
    assert 'pid_project_mode' not in payload or payload['pid_project_mode']=='EXPERIMENT_COPY'
    assert (run/'program.scl').read_bytes()==Path(payload['source_path']).read_bytes()


def test_corrupt_native_bundle_never_stages(tmp_path,current_package):
    assert hasattr(NP,'build_native_trial_request')
    run=NP.create_native_validation_run(tmp_path,Path(current_package['package_dir']),PROTOCOL,PROFILE,tmp_path/'n')
    record=NP.verify_native_run(run)
    (run/'pid_cyclic_ob.xml').write_text('corrupt')
    target=tmp_path/'tiaw/T0001'
    with pytest.raises(ValueError,match='PID_BUNDLE_INTEGRITY'):
        NP.build_native_trial_request(run,target,record)
    assert not target.exists()


@pytest.mark.parametrize('change',[{'target_type':'PHYSICAL_PLC'},{'physical_download_allowed':True},
    {'purpose':'normal'},{'working_dir':'foreign'},{'master_archive_path':'foreign.zap18'}])
def test_isolated_boundary_rejects_unsafe_request_before_bridge(tmp_path,monkeypatch,change):
    assert hasattr(DE,'execute_isolated_trial_request'), 'Missing shared guarded experimental boundary'
    from test_phase4a_deferred_evaluation import _project, _master
    root=_project(tmp_path);master=_master(root)
    config=DE.load_master_config(root)
    workspace=root/'tiaw/T0001';workspace.mkdir(parents=True)
    request={'action':'evaluate_trial','target_type':'PLCSIM_ADVANCED','purpose':'experiment',
             'physical_download_allowed':False,'require_simulation':True,
             'master_archive_path':config['snapshot']['archive_path'],
             'working_dir':str(workspace/'p'),'trial_archive_dir':str(workspace),
             'handshake_dir':str(workspace),'download_after_archive':False}
    request.update(change)
    monkeypatch.setattr(DE,'run_bridge',lambda *a,**k:pytest.fail('Unsafe request reached bridge'))
    with pytest.raises(ValueError,match='EXPERIMENT_'):
        DE.execute_isolated_trial_request(root,request,workspace,lambda _: {'download':False})


def test_production_bridge_experimental_target_checks(tmp_path):
    import subprocess
    from tia_openness import build_openness_bridge
    from utils import get_project_root
    built=build_openness_bridge(get_project_root())
    assert built['built'], built
    request=tmp_path/'request.json'; result=tmp_path/'result.json'
    request.write_text(json.dumps({'action':'self_test','result_path':str(result)}))
    process=subprocess.run([built['exe_path'],str(request)],capture_output=True,text=True,timeout=30)
    assert process.returncode==0, process.stdout+process.stderr
    checks={c['native_experimental_case']:c for c in json.loads(result.read_text())['checks'] if 'native_experimental_case' in c}
    assert set(checks)=={'virtual_allowed','physical_rejected','wrong_purpose_rejected','physical_flag_rejected'}
    assert all(c['passed'] for c in checks.values())


def test_experimental_execution_context_requires_owned_workspace_and_verified_archive(tmp_path,current_package):
    import pid_package as pid
    import hashlib
    import zipfile
    from trial_experiments import tia_workspace as TW
    from test_phase4a_deferred_evaluation import _project, _master
    assert hasattr(pid,'validate_experimental_pid_project'), 'Missing experimental compile-context verification'
    root=_project(tmp_path/'root');_master(root)
    run=NP.create_native_validation_run(root,Path(current_package['package_dir']),PROTOCOL,PROFILE,tmp_path/'n')
    entry=TW.allocate(root,run.name,1,run);workspace=Path(entry['path'])
    payload=NP.build_native_trial_request(run,workspace,NP.verify_native_run(run))
    package=Path(payload['execution_package'])
    project=workspace/'p/MASTER/MASTER.ap18';project.parent.mkdir(parents=True);project.write_bytes(b'compiled')
    archive=run/'attempt.zap18'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('MASTER.ap18',b'compiled')
    manifest=json.loads((package/'pid_infrastructure.json').read_text())
    report={**payload['native_pid'],'status':'TIA_COMPILATION_PASSED','error_count':0,'project_path':str(project),
            'pid_project_mode':'EXPERIMENT_COPY','configuration_hash':manifest['loops'][0]['configuration_hash'],
            'pid_cyclic_ob':{'attributes':{'SecondaryType':'CyclicInterrupt','CyclicTime':'100000'}}}
    master=DE.load_master_config(root)['snapshot']
    context={'workspace_id':entry['workspace_id'],'workspace_path':str(workspace),'run_id':run.name,
             'master_archive_path':master['archive_path'],'master_archive_sha256':master['archive_sha256'],
             'evidence_archive_path':str(archive),'evidence_archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
             'report':report}
    assert pid.validate_experimental_pid_project(package,root,context)==str(project.resolve())
    (package/'tia_compile_report.json').write_text(json.dumps(report))
    with pytest.raises(ValueError,match='PID_COMPILE_REQUIRED'):
        pid.native_download_project(package,root,'PLCSIM_ADVANCED')
    context['run_id']='a different run'
    with pytest.raises(ValueError,match='PID_EXPERIMENT_CONTEXT'):
        pid.validate_experimental_pid_project(package,root,context)


def test_external_provider_uses_experimental_context_before_bridge(tmp_path,current_package,monkeypatch):
    import pid_plant_io as plant
    assert hasattr(plant,'validate_experimental_pid_project'), 'Provider cannot validate experimental package yet'
    monkeypatch.setattr(plant,'native_download_project',lambda *a:pytest.fail('Normal project route used'))
    def validate(package,root,context):
        assert context=={'attempt':'explicit'}
        raise ValueError('EXPERIMENT_CONTEXT_CHECKED')
    monkeypatch.setattr(plant,'validate_experimental_pid_project',validate)
    session=plant.PidPlantIOSession(Path(current_package['package_dir']),
        {'target_type':'PLCSIM_ADVANCED','instance_name':'TESIS_PLC_SIM',
         'native_execution_context':{'attempt':'explicit'}},tmp_path/'transport',30)
    with pytest.raises(ValueError,match='EXPERIMENT_CONTEXT_CHECKED'):
        session.start()
