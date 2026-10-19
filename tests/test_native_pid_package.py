import json
import pytest
from pathlib import Path
from test_native_pid_resolution import payload,request
from test_tank_bench_setup import bench
from tank_bench_setup import prepare_tank_bench
from project_packager import generate_project_package
from tia_openness import prepare_tia_request


def package(tmp_path,intents_catalog,safety_rules):
    result=generate_project_package(payload(request()),'SIEMENS_SCL_V18',prepare_tank_bench(bench()),
        intents_catalog,safety_rules,output_dir=tmp_path/'packages')
    assert result['verification']['is_valid'],result['verification']
    return Path(result['package_dir'])


def test_native_package_declares_infrastructure_and_request(tmp_path,intents_catalog,safety_rules):
    p=package(tmp_path,intents_catalog,safety_rules)
    assert (p/'pid_cyclic_ob.xml').is_file()
    manifest=json.loads((p/'pid_infrastructure.json').read_text(encoding='utf-8'))
    assert manifest['loops'][0]['symbols']['db']=='DB_PID_LevelLoop'
    _,_,r=prepare_tia_request(p)
    assert r['action']=='native_pid_import_compile' and r['pid_manifest']==manifest
    assert r['pid_project_mode']=='NORMAL_PROJECT' and r['physical_download_allowed'] is False


def test_manifest_cannot_escape_package_directory(tmp_path,intents_catalog,safety_rules):
    p=package(tmp_path,intents_catalog,safety_rules)
    path=p/'pid_infrastructure.json';m=json.loads(path.read_text(encoding='utf-8'));m['cyclic_ob_file']='../foreign.xml';path.write_text(json.dumps(m))
    with pytest.raises(ValueError,match='PID_PACKAGE_PATH'): prepare_tia_request(p)


def test_missing_technology_or_period_blocks_readiness(tmp_path,intents_catalog,safety_rules):
    from pid_package import validate_pid_manifest
    p=package(tmp_path,intents_catalog,safety_rules)
    m=json.loads((p/'pid_infrastructure.json').read_text(encoding='utf-8'));m['loops'][0]['period_ms']=0
    with pytest.raises(ValueError,match='PID_PERIOD'):validate_pid_manifest(m)
    m['loops'][0]['period_ms']=100;m['loops'][0]['technology_version']='9.9'
    with pytest.raises(ValueError,match='PID_UNSUPPORTED_VERSION'):validate_pid_manifest(m)


def test_non_pid_request_is_unchanged(tmp_path):
    p=tmp_path/'legacy';p.mkdir();(p/'siemens_source.scl').write_text('legacy');(p/'variables.json').write_text('[]')
    _,_,r=prepare_tia_request(p)
    assert r['action']=='import_compile' and 'pid_manifest' not in r


def test_malformed_symbol_is_a_diagnostic(tmp_path,intents_catalog,safety_rules):
    from pid_package import validate_pid_manifest
    p=package(tmp_path,intents_catalog,safety_rules)
    m=json.loads((p/'pid_infrastructure.json').read_text())
    m['loops'][0]['symbols']['db']=None
    with pytest.raises(ValueError,match='PID_BLOCK_CONFLICT'):validate_pid_manifest(m)


def test_native_validation_checks_bridge_freshness_even_if_exe_exists(tmp_path,monkeypatch):
    import tia_openness as tia
    (tmp_path/'pid_infrastructure.json').write_text('{}')
    monkeypatch.setattr(tia,'diagnose_tia_openness',lambda root:{'checks':{'bridge_built':True},'is_ready':True})
    monkeypatch.setattr(tia,'build_openness_bridge',lambda root:{'built':False,'errors':['stale source compile failed']})
    result=tia.validate_package_with_tia(tmp_path,tmp_path)
    assert result['status']=='BRIDGE_BUILD_FAILED'


def test_new_package_reuses_compatible_controller_project(tmp_path,intents_catalog,safety_rules):
    import pid_package as pid
    p=package(tmp_path,intents_catalog,safety_rules)
    root=tmp_path/'root'; template=tmp_path/'normal.ap18';template.write_bytes(b'template')
    compiled=root/'runtime/pid/previous/work.ap18';compiled.parent.mkdir(parents=True);compiled.write_bytes(b'learned controller')
    loop=json.loads((p/'pid_infrastructure.json').read_text())['loops'][0]
    report={'status':'TIA_COMPILATION_PASSED','error_count':0,'project_path':str(compiled),
        'template_project_path':str(template),'configuration_hash':loop['configuration_hash']}
    pid.remember_native_project(root,report)
    assert pid.native_request(p,root,str(template))['project_path']==str(compiled)
    template.write_bytes(b'changed hardware')
    assert pid.native_request(p,root,str(template))['project_path']==str(template)


def test_same_package_cannot_reuse_old_hardware_template(tmp_path,intents_catalog,safety_rules):
    import pid_package as pid
    p=package(tmp_path,intents_catalog,safety_rules)
    template=tmp_path/'normal.ap18';template.write_bytes(b'new hardware')
    compiled=tmp_path/'runtime/pid/prior/work.ap18';compiled.parent.mkdir(parents=True);compiled.write_bytes(b'old hardware')
    loop=json.loads((p/'pid_infrastructure.json').read_text())['loops'][0]
    (p/'tia_compile_report.json').write_text(json.dumps({'status':'TIA_COMPILATION_PASSED','project_path':str(compiled),
        'template_project_path':str(template),'template_project_sha256':'old fingerprint','configuration_hash':loop['configuration_hash']}))
    assert pid.native_request(p,tmp_path,str(template))['project_path']==str(template)


def test_native_download_carries_requirements_for_live_recheck(tmp_path,intents_catalog,safety_rules,monkeypatch):
    import tia_openness as tia
    p=package(tmp_path,intents_catalog,safety_rules)
    monkeypatch.setattr('pid_package.native_download_project',lambda *args:'verified.ap18')
    (p/'tia_compile_report.json').write_text(json.dumps({'pid_project_mode':'ISOLATED_COPY'}))
    _,_,r=tia.prepare_download_request(p)
    assert r['pid_manifest']==json.loads((p/'pid_infrastructure.json').read_text(encoding='utf-8'))


def test_native_download_also_rebuilds_a_stale_bridge(tmp_path,monkeypatch):
    import tia_openness as tia
    (tmp_path/'pid_infrastructure.json').write_text('{}')
    monkeypatch.setattr(tia,'diagnose_tia_openness',lambda root:{'checks':{'bridge_built':True},'is_ready':True})
    monkeypatch.setattr(tia,'build_openness_bridge',lambda root:{'built':False,'errors':['stale compile failed']})
    assert tia.download_program_to_plc(tmp_path,tmp_path)['status']=='BRIDGE_BUILD_FAILED'


@pytest.mark.parametrize('operation',['compile','download'])
def test_native_timeout_uses_file_logs_and_reports_failure(tmp_path,monkeypatch,operation):
    import subprocess
    import tia_openness as tia
    (tmp_path/'pid_infrastructure.json').write_text('{}')
    diagnostic={'checks':{'bridge_built':True},'is_ready':True,'bridge_exe_path':'bridge.exe'}
    monkeypatch.setattr(tia,'diagnose_tia_openness',lambda root:diagnostic)
    monkeypatch.setattr(tia,'build_openness_bridge',lambda root:{'built':True})
    result_path=tmp_path/('tia_compile_report.json' if operation=='compile' else 'tia_download_report.json')
    result_path.write_text(json.dumps({'status':'TIA_COMPILATION_PASSED','download_success':True}))
    request={'action':'native_pid_import_compile' if operation=='compile' else 'download'}
    monkeypatch.setattr(tia,'prepare_tia_request' if operation=='compile' else 'prepare_download_request',
        lambda *args:(tmp_path/'request.json',result_path,request))
    def expired(command,**kwargs):
        assert not kwargs.get('capture_output'), 'TIA descendants can inherit pipes and prevent timeout completion'
        assert hasattr(kwargs['stdout'],'write') and hasattr(kwargs['stderr'],'write')
        raise subprocess.TimeoutExpired(command,kwargs['timeout'])
    monkeypatch.setattr(tia.subprocess,'run',expired)
    invoke=tia.validate_package_with_tia if operation=='compile' else tia.download_program_to_plc
    result=invoke(tmp_path,tmp_path)
    assert result['status']=='TIA_OPENNESS_TIMEOUT' and result['executed']
    assert result.get('download_success',False) is False
    assert result['bridge_return_code'] is None and result['bridge_timed_out']
    assert json.loads(result_path.read_text())['status']=='TIA_OPENNESS_TIMEOUT'


def test_reimport_preserves_learned_parameters_and_rejects_foreign_blocks(tmp_path):
    # Production C# decision tests. Live two-import evidence is recorded separately.
    from test_tia_pid_support import test_real_bridge_pid_contract_self_test
    test_real_bridge_pid_contract_self_test(tmp_path)
