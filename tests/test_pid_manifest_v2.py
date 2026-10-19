import copy
import hashlib
import json

import pytest

from pid_package import native_download_project, native_request, validate_pid_manifest
from test_native_pid_package import package
from test_pid_map_driven_generation import artifacts
from test_process_signals import db_entry
from pid_scl import build_pid_infrastructure


def v1_manifest():
    return {'schema_version': 1, 'owner': 'VozLlmPlcAgent.NativePID.v1', 'loops': [{
        'period_ms': 100, 'technology_version': '2.3', 'mode': 'SIMULATION', 'direction': 'FILL',
        'configuration_hash': 'a'*64, 'symbols': {'fb': 'FB_PID_Old', 'db': 'DB_PID_Old',
        'controller': 'PID_Old', 'ob': 'OB_PID_Old'}, 'input_config': {'confirmed': False},
        'output_config': {'confirmed': False}}]}


def compiled_package(path, root):
    manifest = json.loads((path/'pid_infrastructure.json').read_text())
    project = root/'runtime/pid/staging/work.ap18'
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_bytes(b'offline compiled project fixture')
    report = {'status': 'TIA_COMPILATION_PASSED', 'error_count': 0, 'project_path': str(project),
              'configuration_hash': manifest['loops'][0]['configuration_hash'],
              'pid_cyclic_ob': {'attributes': {'SecondaryType': 'CyclicInterrupt', 'CyclicTime': '100000'}},
              'cpu': {'cpu_type_identifier': 'CPU 1516-3 PN/DP', 'cpu_FirmwareVersion': 'V2.6'},
              'pid_infrastructure_after': {'technology_version': '2.3'}}
    for filename, key in [('siemens_source.scl', 'pid_source_sha256'), ('pid_cyclic_ob.xml', 'pid_cyclic_ob_sha256'),
                          ('pid_infrastructure.json', 'pid_manifest_sha256'), ('pid_process_bindings.json', 'pid_bindings_sha256')]:
        report[key] = hashlib.sha256((path/filename).read_bytes()).hexdigest()
    (path/'tia_compile_report.json').write_text(json.dumps(report))
    return project


def test_v1_restrictions_survive_v2_support():
    manifest = v1_manifest()
    assert validate_pid_manifest(manifest)['mode'] == 'SIMULATION'
    manifest['loops'][0].pop('mode')
    with pytest.raises(ValueError, match='PID_CONFIG_MISMATCH'):
        validate_pid_manifest(manifest)


def test_v2_assumed_ranges_compile_but_physical_download_denied(tmp_path, intents_catalog, safety_rules):
    path = package(tmp_path, intents_catalog, safety_rules)
    manifest = json.loads((path/'pid_infrastructure.json').read_text())
    before = copy.deepcopy(manifest)
    assert validate_pid_manifest(manifest)['input_binding']['analog_config']['confirmed'] is False
    project = compiled_package(path, tmp_path)
    assert native_download_project(path, tmp_path, 'PLCSIM_ADVANCED') == str(project)
    with pytest.raises(ValueError, match='PID_CALIBRATION_REQUIRED'):
        native_download_project(path, tmp_path, 'PHYSICAL')
    assert manifest == before


def test_foreign_db_and_case_collision_fail_before_import():
    p, _ = artifacts({'variables': [db_entry(), db_entry('M_Fill', 'MANIPULATED', 'FillCommand')]})
    manifest = build_pid_infrastructure(p)
    assert validate_pid_manifest(manifest)['input_binding']['storage']['db'] == 'DB_TankProcess'
    manifest['process_dbs'][0]['members'][1]['name'] = 'level'
    with pytest.raises(ValueError, match='PID_STORAGE_CONFLICT'):
        validate_pid_manifest(manifest)


def test_verified_offline_parameters_preserved_demo_not_promoted(tmp_path, intents_catalog, safety_rules):
    from pid_package import remember_native_project
    path = package(tmp_path, intents_catalog, safety_rules)
    template = tmp_path/'template.ap18'
    template.write_bytes(b'original hardware')
    project = compiled_package(path, tmp_path)
    old = json.loads((path/'tia_compile_report.json').read_text())
    old.update(template_project_path=str(template), configuration_hash='a'*64)
    remember_native_project(tmp_path, old)
    assert native_request(path, tmp_path, str(template))['project_path'] == str(template)


def test_compiled_package_rejects_changed_descriptors(tmp_path, intents_catalog, safety_rules):
    path = package(tmp_path, intents_catalog, safety_rules)
    compiled_package(path, tmp_path)
    bindings = path/'pid_process_bindings.json'
    bindings.write_text(bindings.read_text()+' ')
    with pytest.raises(ValueError, match='PID_COMPILE_REQUIRED'):
        native_download_project(path, tmp_path, 'PLCSIM_ADVANCED')


def test_parameter_verification_can_retry_without_authorizing_stale_download(tmp_path,intents_catalog,safety_rules):
    import pid_package
    path=package(tmp_path,intents_catalog,safety_rules);project=compiled_package(path,tmp_path)
    report=json.loads((path/'tia_compile_report.json').read_text())
    report['parameter_update_requires_compile']=True
    (path/'tia_compile_report.json').write_text(json.dumps(report))
    with pytest.raises(ValueError,match='PID_COMPILE_REQUIRED'):
        native_download_project(path,tmp_path,'PLCSIM_ADVANCED')
    assert pid_package.native_parameter_project(path,tmp_path)==str(project)
    (path/'pid_process_bindings.json').write_text('{}')
    with pytest.raises(ValueError,match='PID_COMPILE_REQUIRED'):
        pid_package.native_parameter_project(path,tmp_path)


def test_db_ports_are_not_physical_tags(tmp_path):
    from platforms.siemens_scl_adapter import SiemensSCLAdapter
    from tia_openness import _build_tag_payload
    project, _ = artifacts({'variables': [db_entry(), db_entry('M_Fill', 'MANIPULATED', 'FillCommand')]})
    rows = SiemensSCLAdapter().render_variables_table(project)
    path = tmp_path/'variables.json'
    path.write_text(json.dumps(rows))
    tags = _build_tag_payload(path, tmp_path)
    assert not {t['name'] for t in tags} & {'M_Level', 'M_Fill', 'M_Level_Quality'}
    assert next(r for r in rows if r['name'] == 'M_Level')['tia_scope'] == 'PROCESS_DB_PORT'
