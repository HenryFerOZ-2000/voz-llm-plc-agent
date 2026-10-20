"""Campaign scope must not change the benchmark or the development PID path."""
import json
from pathlib import Path
import shutil

import pytest

from trial_experiments import experimental_design as ED
from trial_experiments import formal_audio as FA
from trial_experiments import text_batch as TB

ROOT = Path(__file__).resolve().parents[1]
CASES = [f'D{i:02}' for i in range(1, 21)]


@pytest.fixture
def scoped(tmp_path):
    for name in ('data', 'config'):
        shutil.copytree(ROOT / name, tmp_path / name)
    path = tmp_path / 'data/experimental_design.json'
    design = json.loads(path.read_text(encoding='utf-8'))
    design['formal_campaign'] = {'id': 'THESIS_DISCRETE_V2', 'case_ids': CASES}
    design['formal_trial_count'] = 180
    path.write_text(json.dumps(design), encoding='utf-8')
    return tmp_path


def test_formal_matrix_is_180_discrete_cells_without_changing_catalog(scoped):
    matrix = ED.formal_design_matrix(scoped)
    assert len(matrix) == 180
    assert {c['case_id'] for c in matrix} == set(CASES)
    assert ED.validate_formal_matrix(matrix, scoped) == []
    from trial_experiments.benchmark_catalog import load_catalog
    assert len(load_catalog(scoped)['cases']) == 32


def test_matrix_rejects_missing_duplicate_and_wrong_modality(scoped):
    matrix = ED.formal_design_matrix(scoped)
    assert ED.validate_formal_matrix(matrix[:-1], scoped)
    matrix[-1] = dict(matrix[-2])
    assert ED.validate_formal_matrix(matrix, scoped)
    matrix = ED.formal_design_matrix(scoped)
    matrix[-1]['input_mode'] = 'UNKNOWN'
    assert ED.validate_formal_matrix(matrix, scoped)


def test_formal_batch_defaults_to_discrete_and_rejects_pid_before_creation(scoped):
    _, batch = TB.create_batch(scoped, 'FORMAL', git={'commit':'test','dirty':False})
    assert batch['total_trials'] == 60
    assert batch['campaign_id'] == 'THESIS_DISCRETE_V2'
    assert batch['selection']['case_ids'] == CASES
    # A separate destination ensures failure is caused by scope, not an open batch.
    shutil.rmtree(scoped / 'results')
    with pytest.raises(ValueError, match='FORMAL_CASE_OUT_OF_SCOPE'):
        TB.create_batch(scoped, 'FORMAL', ['P01'], git={'commit':'test','dirty':False})
    assert not list((scoped / 'results').glob('batches/*/batch_manifest.json'))


def test_development_still_allows_pid(scoped):
    _, batch = TB.create_batch(scoped, 'DEVELOPMENT_VALIDATION', ['P01'], git={})
    assert batch['total_trials'] == 3
    assert not batch.get('campaign_id')


def test_formal_audio_requires_60_pairs_development_keeps_full_catalog(scoped):
    assert len(FA.load_corpus(scoped, 'FORMAL')['cells']) == 60
    assert len(FA.load_corpus(scoped, 'DEVELOPMENT_VALIDATION')['cells']) == 96
    assert FA.noise_batch_preflight(scoped, 'FORMAL')['total'] == 60


def test_statistics_can_exclude_old_freezes_and_pid():
    base = {'trial_kind':'FORMAL_TRIAL','experiment_phase':'FORMAL','benchmark_version':3}
    records = [{**base,'campaign_id':c,'case_id':case} for c,case in
               [(None,'D01'),('THESIS_DISCRETE_V2','D01'),('ARTICLE','P01')]]
    assert ED.formal_statistics_records(records, campaign_id='THESIS_DISCRETE_V2') == [records[1]]
    assert ED.formal_statistics_records(records) == records


def test_legacy_design_retains_288_cells(scoped):
    path = scoped / 'data/experimental_design.json'
    design = json.loads(path.read_text(encoding='utf-8'))
    design.pop('formal_campaign')
    design['formal_trial_count'] = 288
    path.write_text(json.dumps(design), encoding='utf-8')
    assert len(ED.formal_design_matrix(scoped)) == 288
    assert ED.validate_formal_matrix(ED.formal_design_matrix(scoped), scoped) == []


def test_old_formal_batch_cannot_resume_under_new_campaign(scoped):
    _, batch = TB.create_batch(scoped, 'FORMAL', ['D01'], git={})
    assert TB.reconcile(scoped, batch) == []
    batch.pop('campaign_id')
    assert any('CAMPAIGN_MISMATCH' in error for error in TB.reconcile(scoped, batch))


def test_existing_audio_corpus_from_another_freeze_is_not_relabelled(scoped):
    corpus = FA.load_corpus(scoped, 'FORMAL')
    corpus['formal_freeze_id'] = 'OLD_FREEZE'
    FA.save_corpus(scoped, 'FORMAL', corpus)
    with pytest.raises(FA.FormalAudioError, match='CORPUS_IDENTITY'):
        FA.load_corpus(scoped, 'FORMAL')


def test_retry_does_not_mutate_or_schedule_a_historical_formal_batch(scoped):
    import copy
    from types import SimpleNamespace
    from gui import VozLLMPLCGUI
    _, batch = TB.create_batch(scoped, 'FORMAL', ['D01'], git={})
    batch['status'] = TB.STATUS_PAUSED
    batch['ordered_trial_plan'][0]['status'] = TB.ENTRY_INTERRUPTED
    batch.pop('campaign_id')
    before = copy.deepcopy(batch)
    calls = []
    app = SimpleNamespace(project_root=scoped, _load_open_text_batch=lambda: batch,
                          _batch_save=lambda: calls.append('saved'), after=lambda *a: calls.append('scheduled'))
    result = VozLLMPLCGUI.retry_text_batch_trial(app, 'technical retry')
    assert not result['ok'] and 'CAMPAIGN_MISMATCH' in str(result['errors'])
    assert batch == before and calls == []


def test_readiness_does_not_trust_audio_counters_when_files_are_invalid(scoped, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location('thesis_campaign_check', ROOT/'scripts/thesis_campaign.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.SF, 'validate_freeze', lambda root: {'ok':True,'errors':[]})
    monkeypatch.setattr(module.PR, 'run_audit', lambda *a: {'all_evaluable':True})
    monkeypatch.setattr(module.DE, 'environment_precheck', lambda *a: {'ok':True,'errors':[]})
    monkeypatch.setattr(module.FA, 'noise_master_status', lambda *a: {'ready':True})
    monkeypatch.setattr(module.FA, 'corpus_summary', lambda *a: {'noise_pairs_ready':60,'clean_trials':60})
    monkeypatch.setattr(module.FA, 'noise_batch_preflight', lambda *a: {'ok':False,'errors':['missing WAV']})
    report = module.inspect_campaign(scoped)
    assert report['noise_phase_ready'] is False


@pytest.mark.parametrize('cases', [['D01','D01'], ['D99'], []])
def test_invalid_campaign_fails_closed(scoped, cases):
    path = scoped / 'data/experimental_design.json'
    design = json.loads(path.read_text(encoding='utf-8'))
    design['formal_campaign']['case_ids'] = cases
    path.write_text(json.dumps(design), encoding='utf-8')
    with pytest.raises(ValueError, match='FORMAL_CAMPAIGN_INVALID'):
        ED.formal_design_matrix(scoped)
