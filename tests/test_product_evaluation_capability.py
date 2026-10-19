"""Unsupported native evaluation is a capability gap, never a plant verdict."""
import json

import pytest

from trial_experiments import deferred_evaluator as DE, trial_model, text_batch as TB
from test_product_trial_contract import product_trial, contract_module
from test_phase4a_deferred_evaluation import _master, _FakeBridge, _evaluate

CODE = 'NATIVE_PID_EXPERIMENT_EVALUATION_UNSUPPORTED'


def native_trial(tmp_path, intents_catalog, safety_rules):
    return product_trial(tmp_path, native=True, intents_catalog=intents_catalog, safety_rules=safety_rules)


def test_native_precheck_aborts_before_bridge_or_runtime(tmp_path, intents_catalog, safety_rules):
    root, directory, _ = native_trial(tmp_path, intents_catalog, safety_rules)
    calls = []
    check = DE.precheck(root, directory)
    assert check.get('capability_gap', {}).get('code') == CODE, check
    def external(*a, **k):
        calls.append('external')
        pytest.fail('Unsupported native evaluation reached TIA/Runtime/Oracle')
    result = DE.evaluate_trial(root, directory, bridge=external, runtime_status_fn=external, oracle_fn=external, memory_fn=external)
    assert result['aborted'] and result['capability_gap']['code'] == CODE
    assert not calls and not (directory / 'evaluation').exists()


def test_native_guard_preserves_generation_without_functional_verdict(tmp_path, intents_catalog, safety_rules):
    root, directory, _ = native_trial(tmp_path, intents_catalog, safety_rules)
    DE.evaluate_trial(root, directory, log=lambda m: None)
    record = trial_model.load_trial(directory)
    assert record['generation']['status'] == 'SUCCESS'
    assert record['evaluation']['status'] == 'PENDING' and not record['evaluation']['attempts']
    assert record['evaluation']['final_verdict'] is None and not record.get('final_status')
    assert record['evaluation']['capability']['code'] == CODE
    assert DE.trial_stage_summary(record)['status'] == 'Evaluaci\u00f3n PID nativa pendiente de soporte'


def test_batch_records_capability_block_without_retry_or_pass(tmp_path, intents_catalog, safety_rules):
    root, directory, _ = native_trial(tmp_path, intents_catalog, safety_rules)
    batch_dir, manifest = TB.create_batch(root, trial_model.PHASE_DEVELOPMENT, ['D03'], ['V1'], git={'commit': 'test', 'dirty': False, 'dirty_files': []})
    [entry] = manifest['ordered_trial_plan']
    entry.update(trial_dir=str(directory), trial_id=trial_model.load_trial(directory)['trial_id'])
    check = DE.precheck(root, directory)
    decision = TB.record_precheck_block(root, batch_dir, manifest, entry, check['errors'])
    assert entry['status'] == TB.ENTRY_NOT_EVALUABLE and decision == TB.DECISION_COMPLETED
    record = trial_model.load_trial(directory)
    assert not record['evaluation']['attempts'] and record['evaluation']['capability']['code'] == CODE
    assert TB.outcome_for_record(record) == (TB.ENTRY_NOT_EVALUABLE, None)
    assert not record.get('final_status')


@pytest.mark.parametrize('remove', ['contract', 'native_manifest'])
def test_native_identity_cannot_be_removed_to_bypass_guard(tmp_path, intents_catalog, safety_rules, remove):
    root, directory, _ = native_trial(tmp_path, intents_catalog, safety_rules)
    (directory / ('product_contract.json' if remove == 'contract' else 'pid_infrastructure.json')).unlink()
    check = DE.precheck(root, directory)
    assert check.get('integrity_failed') and not check.get('capability_gap')


def test_supervisor_still_reaches_existing_evaluator(tmp_path):
    root, directory, package = product_trial(tmp_path)
    module = contract_module()
    contract = module.build_product_contract(trial_model.load_trial(directory), package)
    assert module.evaluation_capability(contract)['supported']
    assert module.evaluation_capability(None)['supported']
    _master(root)
    bridge = _FakeBridge()
    assert not _evaluate(root, directory, bridge).get('aborted')
    assert bridge.requests


def test_individual_native_generation_persists_pending_reason_before_dialog(tmp_path, intents_catalog, safety_rules):
    root, directory, _ = native_trial(tmp_path, intents_catalog, safety_rules)
    # No evaluate_trial call: the individual dialog disables Start at precheck.
    before=trial_model.load_trial(directory)
    assert before['evaluation'].get('capability',{}).get('code')==CODE
    assert DE.precheck(root,directory)['capability_gap']['code']==CODE
    reopened=trial_model.load_trial(directory)
    assert reopened==before
    assert DE.trial_stage_summary(reopened)['status']=='Evaluaci\u00f3n PID nativa pendiente de soporte'
    assert reopened['generation']['status']=='SUCCESS' and reopened['evaluation']['status']=='PENDING'
    assert not reopened['evaluation']['attempts'] and not reopened.get('final_status')
    assert not (directory/'evaluation').exists()
