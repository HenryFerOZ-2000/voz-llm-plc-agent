import copy
import json
import subprocess
from pathlib import Path
import pytest
import gui
import plc_targets as targets
import plcsim_runtime as runtime
import tia_openness as tia
from test_plc_targets import root_config,candidate
from test_pid_normal_project import normal_root


def test_normal_selection_preserves_experimental_runtime_configuration(tmp_path):
    path,before=root_config(tmp_path)
    targets.save_normal_target(tmp_path,candidate(),targets.read_target_revision(tmp_path))
    after=json.loads(path.read_text())
    assert after['plcsim_runtime']==before['plcsim_runtime']
    assert after['download_targets']['normal']['instance_id']==7


def test_experiment_refresh_does_not_read_normal_physical_target(app,monkeypatch):
    monkeypatch.setattr(targets,'load_normal_target',lambda r:{'target_type':'PHYSICAL_PLC'})
    calls=[]
    monkeypatch.setattr(gui,'get_plcsim_runtime_status',lambda root:calls.append(root) or {'connected':False,'status':'PLCSIM_INSTANCE_NOT_FOUND','errors':[]})
    from test_execute_full_pipeline import _SyncThread
    monkeypatch.setattr(gui.threading,'Thread',_SyncThread)
    app.work_mode_var.set('Experimentacion')
    try:
        app._start_runtime_refresh('experiment regression')
        assert calls
    finally:app.work_mode_var.set('Normal')


def test_download_rejects_configuration_changed_during_diagnosis(tmp_path,monkeypatch):
    root,project=normal_root(tmp_path)
    config=tia.load_tia_config(root)
    config['download_targets']={'normal':{'target_type':'PLCSIM_ADVANCED','target_address':'192.168.0.1','pc_interface':'PLCSIM','target_interface':'1 X1'}}
    tia.save_tia_config(config,root);captured=targets.load_normal_target(root)
    package=tmp_path/'package';package.mkdir()
    def diagnose(root):
        updated=copy.deepcopy(config);updated['download_targets']['normal']['target_address']='192.168.0.2'
        tia.save_tia_config(updated,root)
        return {'is_ready':True,'checks':{'bridge_built':True},'bridge_exe_path':'never.exe'}
    monkeypatch.setattr(tia,'diagnose_tia_openness',diagnose)
    monkeypatch.setattr(tia,'_run_openness_process',lambda *a:pytest.fail('Changed target downloaded'))
    report=tia.download_program_to_plc(package,root,expected_target=captured)
    assert report['executed'] is False and report['status']=='TIA_TARGET_CHANGED'


def test_runtime_identity_policy_resolves_id_and_rejects_reuse(tmp_path):
    root=Path(__file__).resolve().parents[1]
    built=runtime.build_runtime_bridge(root);assert built['built'],built
    code=tmp_path/'IdentityProbe.cs';exe=tmp_path/'probe.exe'
    code.write_text('''using System;using System.Reflection;using System.Collections.Generic;
class Probe {static int Main(string[] args){
var t=Assembly.LoadFrom(args[0]).GetType("VozLlmPlcAgent.PlcsimRuntimeBridge.Program");
var m=t.GetMethod("SelectInstanceIdentity",BindingFlags.Static|BindingFlags.NonPublic);if(m==null)return 7;
var names=new string[]{"Banco","Banco"};var ids=new int[]{1,2};
var result=(List<int>)m.Invoke(null,new object[]{names,ids,"Banco",(int?)2});if(result.Count!=1||result[0]!=1)return 1;
result=(List<int>)m.Invoke(null,new object[]{names,ids,"Banco",(int?)3});if(result.Count!=0)return 2;
result=(List<int>)m.Invoke(null,new object[]{names,ids,"Otro",(int?)2});if(result.Count!=0)return 3;
return 0;}}''')
    compiled=subprocess.run([str(tia.DEFAULT_COMPILER),'/nologo',f'/out:{exe}',str(code)],capture_output=True,text=True)
    assert compiled.returncode==0,compiled.stdout
    run=subprocess.run([str(exe),built['exe_path']],capture_output=True,text=True)
    assert run.returncode==0,run.stdout+run.stderr


def test_manual_confirmation_exposes_actual_endpoint(app,tmp_path,monkeypatch):
    (tmp_path/'tia_compile_report.json').write_text(json.dumps({'status':'TIA_COMPILATION_PASSED'}))
    monkeypatch.setattr(app,'_last_compiled_package_dir',tmp_path)
    monkeypatch.setattr(gui,'load_tia_config',lambda root:{'project_path':'template.ap18','download_targets':{'normal':{'target_type':'PHYSICAL_PLC','target_name':'Banco','target_address':'192.168.0.22','pc_interface':'Ethernet_A','target_interface':'1 X1'}}})
    messages=[];monkeypatch.setattr(gui.messagebox,'askyesno',lambda title,text:messages.append(text) or False)
    app.load_program_to_plc()
    assert '192.168.0.22' in messages[0] and 'Ethernet_A' in messages[0]


def test_compile_path_does_not_use_download_target_state(tmp_path,monkeypatch):
    import subprocess
    root,project=normal_root(tmp_path);package=tmp_path/'package';package.mkdir()
    request=package/'request.json';result=package/'tia_compile_report.json'
    request.write_text('{}')
    monkeypatch.setattr(tia,'diagnose_tia_openness',lambda root:{'is_ready':True,'checks':{'bridge_built':True},'bridge_exe_path':'fake.exe'})
    monkeypatch.setattr(tia,'prepare_tia_request',lambda *a:(request,result,{'action':'import_compile'}))
    def run(*a):
        result.write_text(json.dumps({'status':'TIA_COMPILATION_PASSED'}))
        return subprocess.CompletedProcess([],0,'',''),False
    monkeypatch.setattr(tia,'_run_openness_process',run)
    assert tia.validate_package_with_tia(package,root)['status']=='TIA_COMPILATION_PASSED'
