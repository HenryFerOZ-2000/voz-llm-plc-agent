import copy
import json
import re
import pytest
from xml.etree import ElementTree as ET

from code_generator import generate_implementation_from_ir
from ir_builder import build_project_ir
from pid_scl import build_pid_infrastructure, render_pid_cyclic_ob
from platforms.siemens_scl_adapter import SiemensSCLAdapter
from tank_bench_setup import prepare_tank_bench
from test_native_pid_resolution import payload, request
from test_process_signals import db_entry
from test_tank_bench_setup import bench
from utils import get_project_root


def artifacts(source, **req):
    project = build_project_ir(payload(request(**req)), source, 'SIEMENS_SCL_V18')
    project.pou.implementation_code = generate_implementation_from_ir(project)
    return project, SiemensSCLAdapter().render_full_program(project)


def test_quality_port_collision_ignores_capitalization():
    source={'variables':[db_entry(),db_entry('M_Level_quality','MANIPULATED','Fill')]}
    with pytest.raises(ValueError,match='PID_SYMBOL_CONFLICT'):
        artifacts(source)


def test_identical_sources_across_destinations():
    outputs = []
    for target, old_mode in [('PLCSIM_ADVANCED', 'SIMULATION'), ('PHYSICAL', 'PHYSICAL')]:
        semantic = payload(request(mode=old_mode))
        semantic['parameters'].update(pid_mode=old_mode)
        semantic['deployment_target'] = target
        project = build_project_ir(semantic, prepare_tank_bench(bench()), 'SIEMENS_SCL_V18')
        project.pou.implementation_code = generate_implementation_from_ir(project)
        caps = json.loads((get_project_root()/'config/native_pid_v18_capabilities.json').read_text())
        outputs.append((SiemensSCLAdapter().render_full_program(project), render_pid_cyclic_ob(project, caps),
                        build_pid_infrastructure(project)))
    assert outputs[0] == outputs[1]


def test_model_profile_is_excluded_but_scale_changes_controller_identity(tmp_path,monkeypatch):
    import shutil
    import pid_scl
    root=get_project_root()
    for filename in ('src/pid_scl.py','src/code_generator.py','src/analog_scaling.py',
                     'src/platforms/siemens_scl_adapter.py','src/process_signals.py',
                     'config/native_pid_map_defaults.json','config/native_pid_cyclic_ob.xml'):
        target=tmp_path/filename;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(root/filename,target)
    monkeypatch.setattr(pid_scl,'get_project_root',lambda:tmp_path)
    source=prepare_tank_bench(bench())
    original,code=artifacts(source)
    profile=tmp_path/'config/pid_tank_test_profile.json'
    profile.write_text(json.dumps({'initial_level_percent':70,'fill_percent_span_per_s':1}))
    changed_profile,other_code=artifacts(source)
    assert other_code==code
    assert build_pid_infrastructure(changed_profile)==build_pid_infrastructure(original)
    source['variables'][18]['analog_config']['engineering_max']=200
    scaled,scaled_code=artifacts(source)
    assert scaled_code!=code
    assert scaled.metadata['pid_build_signature']!=original.metadata['pid_build_signature']


def test_relocated_hardware_is_read_scaled_and_written():
    source = prepare_tank_bench(bench())
    source['variables'][18].update(name='AI_Actual', location='%IW120')
    source['variables'][22].update(name='AO_Actual', location='%QW220')
    project, code = artifacts(source)
    assert project.pid_loops[0].input_binding['address'] == '%IW120'
    assert project.pid_loops[0].output_binding['address'] == '%QW220'
    assert code.count('INT_TO_REAL(#AI_Actual)') == 1
    assert code.count('REAL_TO_INT(') == 1
    assert 'SimLevel' not in code and 'SimSensorFault' not in code


def test_db_quality_and_no_electrical_scaling():
    project, code = artifacts({'variables': [db_entry(), db_entry('M_Fill', 'MANIPULATED', 'FillCommand')]})
    manifest = build_pid_infrastructure(project)
    assert manifest['schema_version'] == 2
    assert len(manifest['process_dbs']) == 1
    assert {m['name']: m['data_type'] for m in manifest['process_dbs'][0]['members']} == {
        'Level': 'REAL', 'LevelValid': 'BOOL', 'FillCommand': 'REAL'}
    assert 'INT_TO_REAL' not in code and 'REAL_TO_INT' not in code
    assert 'M_Level_Quality' in code
    assert code.index('DATA_BLOCK "DB_TankProcess"') < code.index('FUNCTION_BLOCK "FB_PID_LevelLoop"')
    caps = json.loads((get_project_root()/'config/native_pid_v18_capabilities.json').read_text())
    xml = render_pid_cyclic_ob(project, caps)
    assert 'Name="DB_TankProcess"' in xml and 'Name="LevelValid"' in xml
    ns = {'s': 'http://www.siemens.com/automation/Openness/SW/NetworkSource/StructuredText/v3'}
    symbols = ET.fromstring(xml).findall('.//s:Symbol', ns)
    db_symbols = [s for s in symbols if s[0].get('Name') == 'DB_TankProcess']
    assert len(db_symbols) == 3
    assert all([c.tag.rsplit('}', 1)[-1] for c in s] == ['Component', 'Token', 'Component']
               and s[1].get('Text') == '.' for s in db_symbols)


def test_single_pid_call_and_latched_diagnostics():
    from test_native_pid_generation import supervisor
    machine, io, key = supervisor(resources={'alarm_output': 'Q_Digital_0'})
    io[key('CmdStart')] = True
    machine.scan(io)
    io['AI_Level_Raw'] = -1
    machine.scan(io)
    assert io[key('Fault')] and io['Q_Digital_0'] and io['AO_Fill_Command'] == 0
    io['AI_Level_Raw'] = 13824
    machine.scan(io)
    assert io[key('FaultCode')] == 2 and not io[key('Running')]


def test_no_demo_or_implicit_auto():
    project, code = artifacts(prepare_tank_bench(bench()))
    loop = project.pid_loops[0].to_dict()
    assert 'mode' not in loop and 'simulation' not in loop
    assert loop['controller'] == {'status': 'UNTUNED', 'technology_version': '2.3'}
    fields = {v.name: v.initial_value for v in project.pou.variables}
    assert fields['ParametersConfirmed'] == 'FALSE' and fields['ManualValue'] == '0.0'
    assert code.count('"PID_LevelLoop"(') == 1


def test_complete_package_exports_v2_commissioning_descriptors():
    project, _ = artifacts(prepare_tank_bench(bench()))
    extras = SiemensSCLAdapter().render_extra_artifacts(project)
    bindings = extras['pid_process_bindings.json']
    assert bindings['schema_version'] == 2 and 'mode' not in bindings
    assert 'SimSensorFault' not in bindings['bindings']
    assert bindings['input_binding']['address'] == '%IW4'
    assert bindings['calibration_confirmed'] is False
