"""New product evidence is immutable; historical trials remain historical."""
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from trial_experiments import deferred_evaluator as DE, trial_model
from test_phase4a_deferred_evaluation import _project, _generated_trial, _master, _FakeBridge, _evaluate, no_regeneration
from test_native_pid_package import package as native_package
from product_engine import ENGINE_ID, MAP_POLICY


def contract_module():
    assert importlib.util.find_spec('trial_experiments.product_contract'), 'Missing product evidence contract'
    return importlib.import_module('trial_experiments.product_contract')


def product_trial(tmp_path, *, case_id='D03', native=False, intents_catalog=None, safety_rules=None):
    root = _project(tmp_path)
    directory = _generated_trial(root, case_id)
    package = tmp_path / 'product_package'
    package.mkdir()
    if native:
        package = native_package(tmp_path, intents_catalog, safety_rules)
    else:
        (package / 'siemens_source.scl').write_bytes((directory / 'program.scl').read_bytes())
        (package / 'variables.json').write_bytes((directory / 'variables.json').read_bytes())
    identity = {'schema_version': 1, 'engine_id': ENGINE_ID}
    (package / 'generation_metadata.json').write_text(json.dumps({'product_engine': identity}), encoding='utf-8')
    trial_model.update_trial(directory, {'product_engine': identity, 'io_map': {'map_policy': MAP_POLICY}})
    DE.finalize_generation(root, directory, package)
    return root, directory, package


def test_new_trial_freezes_product_identity(tmp_path):
    root, directory, package = product_trial(tmp_path)
    assert (directory / 'product_contract.json').is_file(), 'New generation lacks product identity'
    c = contract_module().build_product_contract(trial_model.load_trial(directory), package)
    assert c['schema_version'] == 1 and c['engine_id'] == ENGINE_ID
    assert c['map_policy'] == MAP_POLICY and c['package_kind'] == 'DISCRETE_OR_SUPERVISORY'
    assert c['interaction_policy'] == 'INTERACTIVE_CLARIFICATION'
    record = trial_model.load_trial(directory)
    record['batch_id'] = 'BATCH'
    assert contract_module().build_product_contract(record, package)['interaction_policy'] == 'UNANSWERED_CLARIFICATION'
    assert DE.verify_trial_integrity(directory)['ok']


@pytest.mark.parametrize('change', ['tamper', 'remove', 'erase_record_identity'])
def test_contract_tampering_fails_integrity(tmp_path, change):
    _, directory, _ = product_trial(tmp_path)
    path = directory / 'product_contract.json'
    if change == 'remove':
        path.unlink(missing_ok=True)
    elif change == 'tamper':
        path.write_text('{}')
    else:
        path.unlink(missing_ok=True)
        record = trial_model.load_trial(directory)
        record.pop('product_engine', None)
        trial_model.save_trial(directory, record)
    assert not DE.verify_trial_integrity(directory)['ok']


def test_supervisor_is_not_native_by_case_name(tmp_path):
    _, directory, _ = product_trial(tmp_path, case_id='P01')
    assert json.loads((directory / 'product_contract.json').read_text())['package_kind'] == 'DISCRETE_OR_SUPERVISORY'


def test_native_identity_freezes_manifests(tmp_path, intents_catalog, safety_rules):
    _, directory, _ = product_trial(tmp_path, native=True, intents_catalog=intents_catalog, safety_rules=safety_rules)
    c = json.loads((directory / 'product_contract.json').read_text())
    assert c['package_kind'] == 'NATIVE_PID'
    assert {'pid_infrastructure.json', 'pid_process_bindings.json', 'pid_cyclic_ob.xml'} <= set(c['files'])
    assert DE.verify_trial_integrity(directory)['ok']
    (directory / 'pid_process_bindings.json').unlink()
    assert not DE.verify_trial_integrity(directory)['ok']


def test_native_source_without_manifest_is_not_discrete(tmp_path):
    module = contract_module()
    _, directory, package = product_trial(tmp_path)
    (package / 'siemens_source.scl').write_text('VAR\n ctl : PID_Compact;\nEND_VAR')
    with pytest.raises(ValueError, match='PRODUCT_CONTRACT'):
        module.build_product_contract(trial_model.load_trial(directory), package)


def test_legacy_trial_reads_without_backfill(tmp_path):
    root = _project(tmp_path)
    directory = _generated_trial(root)
    before = {p.name: DE.sha256_file(p) for p in directory.iterdir() if p.is_file()}
    assert DE.verify_trial_integrity(directory)['ok']
    assert not (directory / 'product_contract.json').exists()
    assert 'product_engine' not in trial_model.load_trial(directory)
    assert before == {p.name: DE.sha256_file(p) for p in directory.iterdir() if p.is_file()}


def test_saved_trial_evaluation_never_reinterprets(tmp_path, no_regeneration, monkeypatch):
    import product_engine
    root, directory, _ = product_trial(tmp_path)
    for name in ('interpret_product_command', 'resolve_product_assignments', 'generate_product_package'):
        monkeypatch.setattr(product_engine, name, lambda *a, **k: pytest.fail('Saved evaluation regenerated product'))
    _master(root)
    bridge = _FakeBridge()
    result = _evaluate(root, directory, bridge)
    assert not result.get('aborted'), result
    assert bridge.requests
