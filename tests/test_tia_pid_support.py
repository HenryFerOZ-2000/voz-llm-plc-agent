"""Runs production C# decisions; these tests do not assert a live TIA/PLC run."""
import json
import subprocess
from pathlib import Path

from tia_openness import build_openness_bridge
from utils import get_project_root
import copy
import pytest


def test_real_bridge_pid_contract_self_test(tmp_path):
    built=build_openness_bridge(get_project_root())
    assert built['built'],built
    request=tmp_path/'request.json'; result=tmp_path/'result.json'
    request.write_text(json.dumps({'action':'self_test','result_path':str(result)}))
    run=subprocess.run([built['exe_path'],str(request)],capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr
    report=json.loads(result.read_text())
    checks={c['pid_case']:c for c in report['checks'] if 'pid_case' in c}
    assert set(checks)=={'malformed','zero_period','duplicate_blocks','preserve_parameters','foreign_block','config_migration',
        'download_period','download_ob_type','v2_missing_bindings','v2_rejects_mode','v2_db_member_collision',
        'v2_untuned_new','v2_verified_parameters','v1_demo_not_verified'}
    assert all(c['passed'] for c in checks.values())


@pytest.mark.parametrize('key,value',[('SecondaryType','ProgramCycle'),('CyclicTime','200000')])
def test_wrong_live_ob_report_is_rejected(key,value):
    from pid_tia_contract import normalize_pid_probe
    fixture=json.loads((get_project_root()/'tests/fixtures/native_pid_v18_capabilities.json').read_text())
    report={'status':'PID_PROBE_PASSED','timestamp':fixture['observed_at'],
        'cpu':{'cpu_type_identifier':fixture['cpu_type_identifier'],'cpu_FirmwareVersion':fixture['cpu_firmware']},
        'pid_capabilities':{'compile_errors':0,'technology_type':'PID_Compact','technology_version':'2.3',
            'parameters':{},'after':{'blocks':[{'number':30,'attributes':{'SecondaryType':'CyclicInterrupt','CyclicTime':'100000','PriorityNumber':'13'}}]}}}
    report['pid_capabilities']['after']['blocks'][0]['attributes'][key]=value
    with pytest.raises(ValueError,match='PID_CYCLIC_OB_UNVERIFIED'): normalize_pid_probe(report)
