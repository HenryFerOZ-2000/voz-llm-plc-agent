import copy
import importlib
import importlib.util
import json
import shutil

import pytest

from product_engine import generate_product_package
from tank_bench_setup import prepare_tank_bench
from test_native_pid_resolution import payload, request
from test_tank_bench_setup import bench


PROTOCOL = {'schema_version':1, 'protocol_id':'PID_TANK_LEVEL_V1', 'tuning_policy':'REQUIRE_PRETUNE',
            'setpoints':[50,40,60], 'tolerance':2, 'hold_seconds':10, 'deadline_seconds':300,
            'tuning_authorized':True}
PROFILE = {'schema_version':1,'model':'TANK','initial_percent':20,'fill_percent_per_s':2,
           'drain_percent_per_s':0.8,'period_s':0.1,'duration_s':1800}


def module():
    assert importlib.util.find_spec('trial_experiments.native_pid_protocol'), 'Missing native evaluation bundle service'
    return importlib.import_module('trial_experiments.native_pid_protocol')


@pytest.fixture
def current_package(tmp_path, intents_catalog, safety_rules):
    result=generate_product_package(payload(request()),target_platform='SIEMENS_SCL_V18',
        io_map=prepare_tank_bench(bench()),intents_catalog=intents_catalog,safety_rules=safety_rules,
        output_dir=tmp_path/'p')
    assert result['verification']['is_valid']
    return result


def test_native_generation_freezes_actual_source_map(current_package):
    from pathlib import Path
    path=Path(current_package['package_dir'])/'generation_io_map.json'
    assert path.is_file(), 'Native package must preserve the actual generation map'
    source=json.loads(path.read_text(encoding='utf-8'))
    assert any(v['name']=='AI_Level_Raw' for v in source['variables'])


def test_standalone_bundle_survives_deleted_generation_directory(tmp_path, current_package):
    from pathlib import Path
    service=module(); package=Path(current_package['package_dir'])
    run=service.create_native_validation_run(tmp_path,package,PROTOCOL,PROFILE,tmp_path/'n')
    assert package.resolve().is_relative_to(tmp_path.resolve())
    shutil.rmtree(package)
    verified=service.verify_native_run(run)
    assert verified['domain']=='NATIVE_PID_DEVELOPMENT'
    assert verified['phase']=='DEVELOPMENT_VALIDATION'
    assert verified['native_evaluation']['protocol_id']=='PID_TANK_LEVEL_V1'
    assert 'case_id' not in verified


@pytest.mark.parametrize('filename',['program.scl','variables.json','generation_io_map.json',
    'pid_infrastructure.json','pid_process_bindings.json','pid_cyclic_ob.xml','plant_profile.json',
    'native_eval_protocol.json','verification.json','generation_metadata.json'])
def test_native_bundle_tamper_is_rejected_before_execution(tmp_path,current_package,filename):
    from pathlib import Path
    service=module()
    run=service.create_native_validation_run(tmp_path,Path(current_package['package_dir']),PROTOCOL,PROFILE,tmp_path/'n')
    with (run/filename).open('ab') as handle:handle.write(b' ')
    with pytest.raises(ValueError,match='PID_BUNDLE_INTEGRITY'):
        service.verify_native_run(run)


@pytest.mark.parametrize('changes',[{'tolerance':float('nan')},{'hold_seconds':0},
    {'setpoints':[50,101]},{'tuning_policy':'INVENT_GAINS'},{'tuning_authorized':False}])
def test_invalid_protocol_cannot_enable_runtime(current_package,changes):
    service=module(); loop=current_package['project_ir']['pid_loops'][0]
    with pytest.raises(ValueError,match='PID_PROTOCOL'):
        service.validate_native_protocol({**PROTOCOL,**changes},loop,PROFILE)


def test_bundle_paths_cannot_escape_run(tmp_path,current_package):
    from pathlib import Path
    service=module()
    run=service.create_native_validation_run(tmp_path,Path(current_package['package_dir']),PROTOCOL,PROFILE,tmp_path/'n')
    path=run/'native_run.json'; record=json.loads(path.read_text())
    record['files']['../foreign.json']='a'*64
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='PID_BUNDLE_INTEGRITY'):
        service.verify_native_run(run)


def test_canonical_trial_can_freeze_v2_without_upgrading_old_contracts(tmp_path,intents_catalog,safety_rules):
    from test_product_trial_contract import product_trial
    from trial_experiments import deferred_evaluator as DE
    root,directory,package=product_trial(tmp_path,native=True,intents_catalog=intents_catalog,safety_rules=safety_rules)
    old=json.loads((directory/'product_contract.json').read_text())
    assert old['schema_version']==1
    (package/'generation_io_map.json').write_text(json.dumps(prepare_tank_bench(bench())))
    DE.finalize_generation(root,directory,package,native_protocol=PROTOCOL,plant_profile=PROFILE)
    current=json.loads((directory/'product_contract.json').read_text())
    assert current['schema_version']==2
    assert current['native_evaluation']['protocol_id']=='PID_TANK_LEVEL_V1'
    assert DE.verify_trial_integrity(directory)['ok']
    (directory/'plant_profile.json').write_text('{}')
    assert not DE.verify_trial_integrity(directory)['ok']
