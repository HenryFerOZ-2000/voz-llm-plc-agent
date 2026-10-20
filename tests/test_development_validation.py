import importlib
import importlib.util
import json
import shutil

import pytest

from test_pid_supervisor import _semantic_output
from trial_experiments import benchmark_catalog as BC, trial_model


def service():
    assert importlib.util.find_spec('trial_experiments.development_validation'), 'Development runner is missing'
    return importlib.import_module('trial_experiments.development_validation')


@pytest.fixture
def isolated_project(tmp_path, project_root):
    for name in ('config', 'data'):
        shutil.copytree(project_root/name, tmp_path/name)
    return tmp_path


def test_pid_round_uses_exact_36_canonical_variants(project_root):
    entries = service().build_pid_supervisory_plan(project_root)
    assert [(e['case_id'], e['variant_id']) for e in entries] == [
        (f'P{i:02d}', v) for i in range(1, 13) for v in ('V1', 'V2', 'V3')]
    for entry in entries:
        reference = BC.trial_benchmark_reference(project_root, entry['case_id'], entry['variant_id'])
        assert entry['command_text'] == reference['canonical_command']
        assert entry['variant_hash'] == reference['variant_hash']


def test_generate_supervisor_preserves_map_and_freezes_product_identity(isolated_project):
    module = service()
    entry = next(e for e in module.build_pid_supervisory_plan(isolated_project) if e['case_id']=='P02')
    before = {p.name: p.read_bytes() for p in (isolated_project/'data/plc_maps').glob('*.json')}
    response = _semantic_output('P02', entry['command_text'], [{'type':'set_level_setpoint','value':60.0}])
    result = module.generate_development_case(isolated_project, entry, isolated_project/'round', llm_response_text=response)
    directory = result['trial_dir']
    record = trial_model.load_trial(directory)
    assert record['experiment_phase'] == trial_model.PHASE_DEVELOPMENT
    assert record['product_engine']['engine_id'] == 'PRODUCT_SHARED_V1'
    assert record['io_map']['map_policy'] == 'PRODUCT_DECLARED_V2'
    assert record['io_map']['frozen'] is True
    assert record['generation']['status'] == 'SUCCESS'
    contract = json.loads((directory/'product_contract.json').read_text(encoding='utf-8'))
    assert contract['package_kind'] == 'DISCRETE_OR_SUPERVISORY'
    assert contract['interaction_policy'] == 'UNANSWERED_CLARIFICATION'
    assert (directory/'program.scl').is_file()
    assert {p.name:p.read_bytes() for p in (isolated_project/'data/plc_maps').glob('*.json')} == before


def test_clarification_is_recorded_without_answer_or_generated_program(isolated_project):
    module = service(); entry = module.build_pid_supervisory_plan(isolated_project)[0]
    response = _semantic_output('P01', entry['command_text'], [])
    response.update(intent_id='INT_UNKNOWN',requires_clarification=True,
                    clarification_question='¿Qué selector debe habilitar el modo automático?')
    result = module.generate_development_case(isolated_project, entry, isolated_project/'round', llm_response_text=response)
    record = trial_model.load_trial(result['trial_dir'])
    assert record['generation']['status'] == 'FAILED'
    assert record['final_status'] != 'PASS'
    assert not (result['trial_dir']/'program.scl').exists()
    assert record['interaction_policy'] == 'UNANSWERED_CLARIFICATION'


def test_each_round_has_unique_identity_and_formal_is_rejected(isolated_project, monkeypatch):
    module=service()
    monkeypatch.setattr(module, 'build_pid_supervisory_plan', lambda _: [])
    first=module.run_supervisory_round(isolated_project, isolated_project/'runs', evaluate=False)
    second=module.run_supervisory_round(isolated_project, isolated_project/'runs', evaluate=False)
    assert first['round_id'] != second['round_id']
    assert first['phase'] == second['phase'] == trial_model.PHASE_DEVELOPMENT
    assert first['entries'] == second['entries'] == []


def test_explicit_supervisory_map_declares_injected_measurement(isolated_project):
    module=service()
    entry=next(e for e in module.build_pid_supervisory_plan(isolated_project) if e['case_id']=='P04')
    mapping=isolated_project/'data/plc_maps/mapa_desarrollo_supervision_nivel.json'
    before=mapping.read_bytes()
    response=_semantic_output('P04',entry['command_text'],[{'type':'high_level_alarm','threshold':90.0,'alarm_output':'Q_Alarm'}])
    result=module.generate_development_case(isolated_project,entry,isolated_project/'r',llm_response_text=response,map_path=mapping)
    record=trial_model.load_trial(result['trial_dir'])
    assert record['generation']['status']=='SUCCESS',record.get('errors')
    assert record['experiment_map']['simulation_only'] is True
    assert record['experiment_map']['map_id']=='mapa_desarrollo_supervision_nivel'
    assert mapping.read_bytes()==before
