import copy
import json
import pytest


def policy():
    return {'enabled': True, 'max_retries': 2, 'backoff_ms': [5000, 15000]}


def manifest():
    return {'status': 'PAUSED', 'pause_reason': 'INFRASTRUCTURE_ERROR', 'automatic_retry_policy': policy(),
            'ordered_trial_plan': [{'index': 0, 'case_id': 'D05', 'variant_id': 'V1', 'status': 'INFRASTRUCTURE_ERROR',
                                    'trial_id': 'trial_1', 'trial_dir': 'example',
                                    'result': {'final_verdict': 'INFRASTRUCTURE_ERROR'}}]}


def test_retry_budget_is_per_command_persistent_and_records_both_reasons():
    from trial_experiments import batch_retry as R
    m = manifest()
    record = {'final_status': 'INFRASTRUCTURE_ERROR', 'failure_category': 'RUNTIME_FAILURE'}
    first = R.reserve(m, record)
    assert first['delay_ms'] == 5000 and first['number'] == 1
    assert R.reserve(m, record) is None  # no duplicate timer
    m = json.loads(json.dumps(m))  # reservation and budget survive serialization
    m.pop('automatic_retry_pending')
    second = R.reserve(m, record)
    assert second['delay_ms'] == 15000 and second['number'] == 2
    m.pop('automatic_retry_pending')
    assert R.reserve(m, record) is None
    history = m['ordered_trial_plan'][0]['automatic_retries']
    assert len(history) == 2 and all(x['trial_id'] == 'trial_1' and x['reason'] for x in history)


@pytest.mark.parametrize('final', ['PASS', 'FAIL', 'REVIEW', None])
def test_never_retries_an_experimental_or_unfinished_result(final):
    from trial_experiments import batch_retry as R
    m = manifest(); before = copy.deepcopy(m)
    assert R.reserve(m, {'final_status': final}) is None
    assert m == before


@pytest.mark.parametrize('error', ['401 AuthenticationError', 'insufficient_quota', 'TRIAL_INTEGRITY_FAILED',
                                  'CAMPAIGN_MISMATCH', 'INSUFFICIENT_MEMORY_FOR_TIA', 'MASTER cambió durante el ensayo'])
def test_permanent_and_integrity_errors_require_attention(error):
    from trial_experiments import batch_retry as R
    m = manifest()
    assert R.reserve(m, {'final_status': 'INFRASTRUCTURE_ERROR', 'errors': [error]}) is None


@pytest.mark.parametrize('field,value', [('pause_requested', True), ('stop_requested', True),
                                        ('status', 'CANCELLED'), ('pause_reason', 'USER_REQUEST')])
def test_pause_or_stop_prevents_scheduling(field, value):
    from trial_experiments import batch_retry as R
    m = manifest(); m[field] = value
    assert R.reserve(m, {'final_status': 'INFRASTRUCTURE_ERROR'}) is None


def test_policy_is_opt_in_and_validated_before_a_new_batch(tmp_path):
    from trial_experiments import batch_retry as R
    assert R.load_policy(tmp_path)['enabled'] is False
    p = tmp_path/'config/batch_retry.json'; p.parent.mkdir(); p.write_text(json.dumps(policy()), encoding='utf-8')
    assert R.load_policy(tmp_path) == policy()
    p.write_text(json.dumps({**policy(), 'max_retries': -1}), encoding='utf-8')
    with pytest.raises(ValueError): R.load_policy(tmp_path)


def test_historical_manifests_do_not_inherit_the_current_setting():
    from trial_experiments import batch_retry as R
    m = manifest(); m.pop('automatic_retry_policy')
    assert R.reserve(m, {'final_status': 'INFRASTRUCTURE_ERROR'}) is None


def test_policy_is_frozen_when_creating_the_batch(tmp_path):
    from trial_experiments import text_batch as TB, trial_model
    from test_phase4a_deferred_evaluation import _project
    root = _project(tmp_path)
    p = root/'config/batch_retry.json'; p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(policy()), encoding='utf-8')
    directory, m = TB.create_batch(root, trial_model.PHASE_DEVELOPMENT, ['D01'], ['V1'], git={'commit': 'abc'})
    p.write_text(json.dumps({**policy(), 'enabled': False}), encoding='utf-8')
    assert TB.load_manifest(directory)['automatic_retry_policy'] == policy()


def test_hashes_and_command_content_cannot_be_misread_as_authentication_errors():
    from trial_experiments import batch_retry as R
    m = manifest()
    assert R.reserve(m, {'final_status': 'INFRASTRUCTURE_ERROR', 'audio_sha256': '401403',
                         'reference_text': 'authentication', 'errors': ['Connection error']}) is not None
