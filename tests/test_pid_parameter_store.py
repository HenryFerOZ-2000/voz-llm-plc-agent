import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from test_native_pid_trial_bundle import current_package


def service():
    assert importlib.util.find_spec('pid_parameter_store'), 'Missing verified PID parameter persistence'
    return importlib.import_module('pid_parameter_store')


def values(package):
    b=json.loads((Path(package)/'pid_process_bindings.json').read_text())
    return {'Kp':2.0,'Ti':10.0,'Td':0.0,'ParametersConfirmed':True,'ControllerState':3,
            'TuningMode':0,'Fault':False,'SensorValid':True,'build_signature':b['build_signature']}


def test_parameter_states_require_real_confirmation_and_matching_identity(current_package):
    m=service();p=Path(current_package['package_dir']);live=values(p)
    assert m.inspect_parameter_state(p,live,None)['state']=='PENDING_SAVE'
    assert m.inspect_parameter_state(p,{**live,'ParametersConfirmed':False},None)['state']=='UNVERIFIED'
    assert m.inspect_parameter_state(p,{**live,'ControllerState':1},None)['state']=='TUNING'
    assert m.inspect_parameter_state(p,{**live,'build_signature':[0]*16},None)['state']=='INCOMPATIBLE'


@pytest.mark.parametrize('field,value',[('Kp',float('nan')),('Kp',0),('Ti',float('inf')),('Ti',0),('Td',-1)])
def test_invalid_gains_never_become_saved_state(current_package,field,value):
    m=service();p=Path(current_package['package_dir'])
    assert m.inspect_parameter_state(p,{**values(p),field:value},None)['state']=='UNVERIFIED'


def test_fresh_runtime_read_is_required_before_any_bridge_write(tmp_path,current_package,monkeypatch):
    m=service();p=Path(current_package['package_dir'])
    class Session:
        bindings=json.loads((p/'pid_process_bindings.json').read_text())
        context={'target_type':'PLCSIM_ADVANCED','connected':True,'cpu_state':'RUN','program_verified':False}
        def read(self):raise ValueError('PID_PROGRAM_MISMATCH')
    monkeypatch.setattr(m,'run_parameter_bridge',lambda *a,**k:pytest.fail('Stale program reached save bridge'))
    with pytest.raises(ValueError,match='PID_PROGRAM_MISMATCH'):
        m.save_verified_parameters(tmp_path,p,Session())


def test_fake_success_without_archive_and_reread_cannot_persist_record(tmp_path,current_package,monkeypatch):
    m=service();p=Path(current_package['package_dir'])
    template=tmp_path/'Normal.ap18';template.write_bytes(b'normal')
    class Session:
        bindings=json.loads((p/'pid_process_bindings.json').read_text())
        context={'target_type':'PLCSIM_ADVANCED','connected':True,'cpu_state':'RUN','program_verified':True}
        def read(self):return values(p)
    monkeypatch.setattr(m,'native_download_project',lambda *a:str(template))
    monkeypatch.setattr(m,'normal_project_path',lambda *a:str(template))
    monkeypatch.setattr(m,'run_parameter_bridge',lambda *a,**k:{'status':'PID_PARAMETERS_SAVED','project_saved':True})
    with pytest.raises(ValueError,match='PID_PARAMETER_SAVE'):
        m.save_verified_parameters(tmp_path,p,Session())
    assert not list((tmp_path/'runtime/pid/parameter_records').glob('*.json'))


@pytest.mark.parametrize('verification_only',[False,True])
def test_verified_archive_and_reread_are_saved_and_reusable(tmp_path,current_package,monkeypatch,verification_only):
    import zipfile,hashlib
    m=service();p=Path(current_package['package_dir'])
    from test_pid_manifest_v2 import compiled_package
    compiled_package(p,tmp_path)
    template=tmp_path/'Normal.ap18';template.write_bytes(b'normal')
    class Session:
        bindings=json.loads((p/'pid_process_bindings.json').read_text())
        context={'target_type':'PLCSIM_ADVANCED','connected':True,'cpu_state':'RUN','program_verified':True}
        def read(self):return values(p)
    monkeypatch.setattr(m,'native_download_project',lambda *a:str(template))
    monkeypatch.setattr(m,'native_parameter_project',lambda *a:str(template))
    monkeypatch.setattr(m,'normal_project_path',lambda *a:str(template))
    def bridge(request,work_dir,project_root):
        assert request.get('verification_only',False) is verification_only
        path=work_dir/'BeforeParameters.zap18'
        with zipfile.ZipFile(path,'w') as stored:stored.writestr('Normal.ap18',b'normal')
        return {'status':'PID_PARAMETERS_SAVED','project_saved':True,'parameters_verified':True,
            'save_method':'TIA_MANUAL_UPLOAD_VERIFIED' if verification_only else 'OPENNESS_WRITE_VERIFIED',
            'project_path':str(template),'configuration_hash':request['configuration_hash'],
            'parameters_after':request['parameters'],'backup_path':str(path),
            'backup_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    monkeypatch.setattr(m,'run_parameter_bridge',bridge)
    result=m.save_verified_parameters(tmp_path,p,Session(),verification_only=verification_only)
    assert result['status']=='SAVED_VERIFIED'
    assert Path(result['record_path']).is_file()
    from pid_package import native_download_project
    with pytest.raises(ValueError,match='PID_COMPILE_REQUIRED'):
        native_download_project(p,tmp_path,'PLCSIM_ADVANCED')
    assert m.inspect_parameter_state(p,values(p),result['record'])['state']=='SAVED_VERIFIED'
    assert m.inspect_parameter_state(p,{**values(p),'Kp':3.0},result['record'])['state']=='PENDING_SAVE'
    report_path=Path(result['record']['report_path']);original=report_path.read_bytes()
    changed=json.loads(original);changed['parameters_after']['Kp']=7.0
    report_path.write_text(json.dumps(changed))
    assert m.inspect_parameter_state(p,values(p),result['record'])['state']!='SAVED_VERIFIED'
    report_path.write_bytes(original)
    Path(result['record']['backup_path']).write_bytes(b'corrupt archive')
    assert m.inspect_parameter_state(p,values(p),result['record'])['state']!='SAVED_VERIFIED'


def test_production_csharp_parameter_guards(tmp_path,project_root):
    import shutil,subprocess
    from tia_openness import build_openness_bridge
    # A compile probe may be using the normal bridge binary. Compile the exact
    # production sources into a disposable test root without replacing that EXE.
    build_root=tmp_path/'b';sources=build_root/'tia_openness_bridge';sources.mkdir(parents=True)
    for name in ('Program.cs','PidControlSupport.cs','ConnectionTargetSupport.cs'):
        shutil.copy2(project_root/'tia_openness_bridge'/name,sources/name)
    built=build_openness_bridge(build_root)
    assert built['built'],built
    request=tmp_path/'r.json';report=tmp_path/'s.json'
    request.write_text(json.dumps({'action':'self_test','result_path':str(report)}))
    result=subprocess.run([built['exe_path'],str(request)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    checks={c['pid_parameter_case']:c for c in json.loads(report.read_text())['checks'] if 'pid_parameter_case' in c}
    assert set(checks)=={'valid','saved_status','serialized_real','nan','zero_gain','zero_ti','negative_td','overflow','signature_matches','signature_mismatch',
        'uploaded_match','uploaded_mismatch','uploaded_unconfirmed','uploaded_invalid'}
    assert all(c['passed'] for c in checks.values())


def test_unverified_save_cannot_reuse_the_previous_compilation(tmp_path,current_package,monkeypatch):
    m=service();p=Path(current_package['package_dir'])
    from test_pid_manifest_v2 import compiled_package
    compiled_package(p,tmp_path)
    template=tmp_path/'Normal.ap18';template.write_bytes(b'normal')
    class Session:
        bindings=json.loads((p/'pid_process_bindings.json').read_text())
        context={'target_type':'PLCSIM_ADVANCED','connected':True,'cpu_state':'RUN','program_verified':True}
        def read(self):return values(p)
    monkeypatch.setattr(m,'native_download_project',lambda *a:str(template))
    monkeypatch.setattr(m,'normal_project_path',lambda *a:str(template))
    def bridge(*args):
        assert json.loads((p/'tia_compile_report.json').read_text())['parameter_update_requires_compile'] is True
        return {'status':'PID_PARAMETERS_SAVED','project_saved':True,'parameters_verified':True,
            'parameters_after':{'Kp':2.,'Ti':10.,'Td':0.}}
    monkeypatch.setattr(m,'run_parameter_bridge',bridge)
    with pytest.raises(ValueError,match='PID_PARAMETER_SAVE'):
        m.save_verified_parameters(tmp_path,p,Session())
    assert json.loads((p/'tia_compile_report.json').read_text())['parameter_update_requires_compile'] is True
