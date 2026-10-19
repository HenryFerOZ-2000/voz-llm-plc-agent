import json
import runpy
import threading

import pytest

from test_native_pid_package import package
from test_pid_manifest_v2 import compiled_package


def test_v2_validation_refuses_physical_destination(tmp_path, intents_catalog, safety_rules, monkeypatch):
    import pid_native_validation as module
    path=package(tmp_path,intents_catalog,safety_rules)
    compiled_package(path,tmp_path)
    monkeypatch.setattr(module,'load_tia_config',lambda *_: {'download_targets':{'normal':{'target_type':'PHYSICAL_PLC'}}})
    monkeypatch.setattr(module,'download_program_to_plc',lambda *_a,**_k:pytest.fail('Physical download attempted'))
    result=module.run_map_pid_validation(tmp_path,path)
    assert result['status']=='FAILED' and 'PID_ACCEPTANCE_TARGET' in result['reason']
    assert result['native_execution_verified'] is False


def test_acceptance_requires_all_stages_native_proof_and_cleanup():
    from pid_native_validation import finalize_native_verdict
    stages={name:{'status':'PASSED'} for name in ('preflight','runtime','manual','tuning','convergence','safety','cleanup')}
    provider={'status':'CANCELLED','errors':[],'native_execution_verified':True,'cleanup':{'cleanup_verified':True}}
    assert finalize_native_verdict(stages,provider)['status']=='PASSED'
    provider['native_execution_verified']=False
    assert finalize_native_verdict(stages,provider)['status']!='PASSED'
    provider['native_execution_verified']=True
    provider['cleanup']['cleanup_verified']=False
    assert finalize_native_verdict(stages,provider)['status']!='PASSED'
    provider['cleanup']['cleanup_verified']=True
    stages['safety']['status']='UNSUPPORTED'
    assert finalize_native_verdict(stages,provider)['status']!='PASSED'


@pytest.mark.parametrize('status,errors', [('FAILED',[]),('CANCELLED',['late runtime failure']),('RUNNING',[])])
def test_late_provider_failure_cannot_be_pass(status,errors):
    from pid_native_validation import finalize_native_verdict, STAGES
    stages={name:{'status':'PASSED'} for name in STAGES}
    provider={'status':status,'errors':errors,'native_execution_verified':True,'cleanup':{'cleanup_verified':True}}
    assert finalize_native_verdict(stages,provider)['status']=='FAILED'


def test_coordinator_failure_is_irreversible():
    from pid_native_validation import finalize_native_verdict,STAGES
    stages={name:{'status':'PASSED'} for name in STAGES}
    provider={'status':'CANCELLED','errors':[],'native_execution_verified':True,'cleanup':{'cleanup_verified':True}}
    assert finalize_native_verdict(stages,provider,execution_failed=True)['status']=='FAILED'


def test_script_routes_v2_without_mode(tmp_path, intents_catalog, safety_rules, monkeypatch, project_root):
    import pid_native_validation as module
    path=package(tmp_path,intents_catalog,safety_rules)
    monkeypatch.setattr(module,'run_map_pid_validation',lambda root,package:{'status':'PENDING','package':str(package)})
    script=runpy.run_path(str(project_root/'scripts/validate_native_pid.py'))
    result=script['run_validation'](tmp_path,path)
    assert result=={'status':'PENDING','package':str(path)}
