import copy
import json
import subprocess
from pathlib import Path

import pytest

import pid_package
import tia_openness as tia
from test_native_pid_package import package
from test_pid_manifest_v2 import compiled_package


def normal_root(tmp_path):
    root = tmp_path / 'root'
    template = root / 'tia_projects/Normal/Normal.ap18'
    template.parent.mkdir(parents=True)
    template.write_bytes(b'normal hardware')
    tia.save_tia_config({'project_path': str(template), 'attach_to_running': True, 'with_user_interface': True}, root)
    return root, template


def test_normal_pid_uses_configured_project_even_when_an_isolated_copy_is_cached(tmp_path, intents_catalog, safety_rules):
    path = package(tmp_path, intents_catalog, safety_rules)
    root, template = normal_root(tmp_path)
    compiled = compiled_package(path, root)
    report = json.loads((path/'tia_compile_report.json').read_text())
    report['template_project_path'] = str(template)
    pid_package.remember_native_project(root, report)
    _, _, request = tia.prepare_tia_request(path, root)
    assert Path(request['project_path']).resolve() == template.resolve()
    assert request['pid_project_mode'] == 'NORMAL_PROJECT'
    assert request['attach_to_running'] is True
    assert request['with_user_interface'] is True
    assert request['project_path'] != str(compiled)


def normal_compile_report(path, root, template):
    compiled_package(path, root)
    report = json.loads((path/'tia_compile_report.json').read_text())
    report.update(project_path=str(template), template_project_path=str(template), pid_project_mode='NORMAL_PROJECT')
    (path/'tia_compile_report.json').write_text(json.dumps(report))
    return report


def test_normal_pid_download_uses_the_same_open_project(tmp_path, intents_catalog, safety_rules):
    path = package(tmp_path, intents_catalog, safety_rules)
    root, template = normal_root(tmp_path)
    normal_compile_report(path, root, template)
    assert Path(pid_package.native_download_project(path, root, 'PLCSIM_ADVANCED')) == template
    _, _, request = tia.prepare_download_request(path, root)
    assert Path(request['project_path']) == template
    assert request['attach_to_running'] is True
    assert request['pid_project_mode'] == 'NORMAL_PROJECT'
    assert request['target_type'] == 'PLCSIM_ADVANCED'
    assert request['require_simulation'] is True
    _, _, compile_request = tia.prepare_tia_request(path, root)
    assert request['normal_program_state_path'] == compile_request['normal_program_state_path']


@pytest.mark.parametrize('change', ['project', 'configured_project', 'mode', 'package'])
def test_normal_pid_download_rejects_stale_or_foreign_projects(tmp_path, intents_catalog, safety_rules, change):
    path = package(tmp_path, intents_catalog, safety_rules)
    root, template = normal_root(tmp_path)
    report = normal_compile_report(path, root, template)
    other = root/'foreign.ap18'; other.write_bytes(b'foreign')
    if change == 'project': report['project_path'] = str(other)
    if change == 'configured_project': tia.save_tia_config({'project_path': str(other)}, root)
    if change == 'mode': report.pop('pid_project_mode')
    if change == 'package': (path/'siemens_source.scl').write_text('changed')
    (path/'tia_compile_report.json').write_text(json.dumps(report))
    with pytest.raises(ValueError, match='PID_COMPILE_REQUIRED'):
        pid_package.native_download_project(path, root, 'PLCSIM_ADVANCED')


def test_pid_and_discrete_share_only_their_own_normal_project_record(tmp_path, intents_catalog, safety_rules):
    path = package(tmp_path, intents_catalog, safety_rules)
    root, template = normal_root(tmp_path)
    _, _, pid = tia.prepare_tia_request(path, root)
    discrete = tmp_path/'discrete';discrete.mkdir()
    (discrete/'siemens_source.scl').write_text('PROGRAM PLC_PRG END_PROGRAM')
    (discrete/'variables.json').write_text('[]')
    _, _, normal = tia.prepare_tia_request(discrete, root)
    assert pid['normal_program_state_path'] == normal['normal_program_state_path']
    assert pid['normal_save_before_backup'] is True
    assert normal['normal_save_before_backup'] is True
    assert Path(pid['normal_program_backup_directory']).is_relative_to(root.resolve()/'runtime/backups')
    other = root/'Other.ap18';other.write_bytes(b'other hardware')
    tia.save_tia_config({'project_path':str(other)}, root)
    _, _, changed = tia.prepare_tia_request(path, root)
    assert changed['normal_program_state_path'] != pid['normal_program_state_path']


def test_compiling_in_normal_project_does_not_enter_the_isolated_project_cache(tmp_path, intents_catalog, safety_rules):
    path = package(tmp_path, intents_catalog, safety_rules)
    root, template = normal_root(tmp_path)
    report = normal_compile_report(path, root, template)
    pid_package.remember_native_project(root, report)
    assert not (root/'runtime/pid/compiled_projects.json').exists()


def test_bridge_verifies_owned_program_before_retiring_it(tmp_path):
    from utils import get_project_root
    built=tia.build_openness_bridge(get_project_root())
    assert built['built'],built
    request, result=tmp_path/'request.json',tmp_path/'result.json'
    request.write_text(json.dumps({'action':'self_test','result_path':str(result)}))
    run=subprocess.run([built['exe_path'],str(request)],capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr
    cases=[c for c in json.loads(result.read_text())['checks'] if 'normal_pid_case' in c]
    assert {c['normal_pid_case'] for c in cases} == {
        'owned_program','modified_block','extra_block','changed_controller','wrong_project','changed_manifest',
        'changed_ob_period','changed_layout','compiler_timestamps','pending_record','stale_pending_record',
        'foreign_discrete_collision'}
    assert all(c['passed'] for c in cases), cases
