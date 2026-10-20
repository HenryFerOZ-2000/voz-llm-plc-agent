"""The discrete batch must recycle program bindings without changing the channel inventory."""
import copy
import json
from pathlib import Path

import pytest

from io_allocator import propose_assignment
from product_engine import prepare_product_map
from normal_program_bindings import stamp_program_bindings

ROOT = Path(__file__).resolve().parents[1]


def bank():
    return json.loads((ROOT / 'data/plc_maps/mapa_banco_fisico_base.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', ['Q_Aux_Output', 'Q_Lamp', 'I_Input_Active', 'I_Safety_Condition'])
def test_new_discrete_program_can_allocate_on_the_legacy_assigned_bank(name):
    source = bank()
    original = copy.deepcopy(source)
    prepared = prepare_product_map(source)
    proposal = propose_assignment(prepared['io_map'], [{'functional_name_hint': name, 'allow_reassign': False}])[0]
    assert not proposal['blocked'], proposal
    assert proposal['current_state'] == 'FREE'
    assert source == original
    before = {v['location']: v for v in source['variables'] if v.get('location')}
    after = {v['location']: v for v in prepared['io_map']['variables'] if v.get('location')}
    assert before.keys() == after.keys()
    for address, variable in after.items():
        assert {k: v for k, v in variable.items() if k not in {'state', 'assignment_source', 'owner_program_id'}} == {
            k: v for k, v in before[address].items() if k not in {'state', 'assignment_source', 'owner_program_id'}}


def test_new_program_recycles_stale_auto_owner_but_extension_keeps_it():
    source = bank()
    output = next(v for v in source['variables'] if v['name'] == 'Q_Conveyor_Enable')
    output.update(assignment_source='AUTO', owner_program_id='older_program')
    prepared = prepare_product_map(source, previous_program_id='different_previous_program')
    assert next(v for v in prepared['io_map']['variables'] if v['location'] == output['location'])['state'] == 'FREE'
    assert prepare_product_map(source, scope='EXTEND_PROGRAM')['io_map'] == source


@pytest.mark.parametrize('protection', [{'state': 'LOCKED'}, {'assignment_source': 'MANUAL'}, {'persistent': True}])
def test_explicit_reservations_survive_new_program(protection):
    source = bank()
    output = next(v for v in source['variables'] if v['name'] == 'Q_Conveyor_Enable')
    output.update(protection)
    prepared = prepare_product_map(source)
    assert next(v for v in prepared['io_map']['variables'] if v['location'] == output['location']) == output


def test_legacy_manual_history_is_preserved_and_not_reported_as_released():
    source = bank()
    source['history'].append({'address': '%QX8.0', 'new_name': 'Q_Conveyor_Enable', 'source': 'MANUAL_EDITOR'})
    prepared = prepare_product_map(source)
    assert '%QX8.0' not in {r['address'] for r in prepared['released']}


def test_commit_claims_recycled_digital_names_even_without_an_allocation_proposal():
    prepared = prepare_product_map(bank())['io_map']
    used = ['I_Mode_Auto', 'Q_Conveyor_Enable']
    assert all(v['state'] == 'FREE' for v in prepared['variables'] if v['name'] in used)
    committed = stamp_program_bindings(prepared, used, 'NEW_PROGRAM', strict_owner=True,
                                       newly_assigned_names=set())
    for variable in committed['variables']:
        if variable['name'] in used:
            assert variable['state'] == 'ASSIGNED'
            assert variable['assignment_source'] == 'AUTO'
            assert variable['owner_program_id'] == 'NEW_PROGRAM'
    extension = prepare_product_map(committed, scope='EXTEND_PROGRAM')['io_map']
    assert extension == committed
    next_signal = propose_assignment(extension, [{'functional_name_hint': 'Q_Another_Output', 'allow_reassign': False}],
                                     reserved_names=set(used))[0]
    assert next_signal['address'] != '%QX8.0'
    assert all(v['state'] == 'FREE' for v in prepared['variables'] if v['name'] in used)


def test_normal_gui_commit_records_reused_legacy_channel_ownership(tmp_path):
    import hashlib
    from types import SimpleNamespace
    import gui

    source = bank()
    path = tmp_path / 'map.json'
    path.write_text(json.dumps(source), encoding='utf-8')
    value = {'intent_id': 'INT_UNKNOWN', 'command_text': 'Use the declared input and output.', 'parameters': {},
             'functional_requirements': [{'type': 'conditional_output', 'condition': 'I_Mode_Auto',
                                          'outputs': ['Q_Conveyor_Enable']}]}
    app = SimpleNamespace(
        io_map_path=path, _file_sha256=lambda p: hashlib.sha256(p.read_bytes()).hexdigest(),
        _program_metadata_allowed=lambda: True, pending_semantic_output=value,
        _normal_program_context={'scope': 'NEW_PROGRAM', 'current_program': None},
        _log=lambda m: None, _load_active_map_metadata_shadow=lambda: None, _load_io_map_table=lambda: None,
        _persist_generated_functional_variables=lambda v: None,
        _pending_map_transaction={'map_path': path, 'base_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'map': prepare_product_map(source)['io_map'], 'history_entries': [], 'proposals': []})
    assert gui.VozLLMPLCGUI._commit_pending_map_transaction(app)
    committed = json.loads(path.read_text(encoding='utf-8'))
    owner = committed['metadata']['current_program']['program_id']
    for variable in committed['variables']:
        if variable['name'] in {'I_Mode_Auto', 'Q_Conveyor_Enable'}:
            assert variable['state'] == 'ASSIGNED'
            assert variable['assignment_source'] == 'AUTO' and variable['owner_program_id'] == owner
