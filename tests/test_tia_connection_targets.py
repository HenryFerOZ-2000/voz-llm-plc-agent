import json
import subprocess
from pathlib import Path
import pytest
import tia_openness as tia
from test_pid_normal_project import normal_root
from utils import get_project_root


def test_explicit_endpoint_reaches_download_request(tmp_path):
    root,project=normal_root(tmp_path)
    config=tia.load_tia_config(root)
    config['download_targets']={'normal':{'target_type':'PHYSICAL_PLC','target_name':'Banco secundario',
        'target_address':'192.168.0.2','pc_interface':'Ethernet','pc_interface_number':2,'target_interface':'1 X1'}}
    tia.save_tia_config(config,root)
    package=tmp_path/'package';package.mkdir()
    _,_,request=tia.prepare_download_request(package,root)
    assert request['target_address']=='192.168.0.2'
    assert request['pc_interface_number']==2 and request['target_name']=='Banco secundario'
    assert request['purpose']=='normal'


def test_invalid_explicit_address_does_not_create_request(tmp_path):
    root,_=normal_root(tmp_path);config=tia.load_tia_config(root)
    config['download_targets']={'normal':{'target_address':'999.1.1.1'}};tia.save_tia_config(config,root)
    package=tmp_path/'package';package.mkdir()
    with pytest.raises(ValueError):tia.prepare_download_request(package,root)
    assert not (package/'tia_download_request.json').exists()


def test_v18_connection_policy_uses_number_and_rejects_ambiguity(tmp_path):
    root=get_project_root();exe=tmp_path/'probe.exe'
    result=subprocess.run([str(tia.DEFAULT_COMPILER),'/nologo','/target:exe',f'/out:{exe}',
        str(root/'tia_openness_bridge/ConnectionTargetSupport.cs'),str(root/'tests/fixtures/ConnectionTargetPolicyProbe.cs')],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr
