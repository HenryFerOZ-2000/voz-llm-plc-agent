import copy
import json
import pytest

import product_engine as P
from trial_experiments import trial_io_map as T
from test_normal_control_strategy import mapped
from test_process_signals import db_entry


def prepare(value,**kwargs):
    assert hasattr(P,'prepare_product_map'),'Product map preparation missing'
    return P.prepare_product_map(value,**kwargs)


def scenario():
    value=mapped()
    for v in value['variables']:
        if v['name']=='AI_Level_Raw':v.update(name='AI_Reservoir',location='%IW40',aliases=['nivel del depósito'])
        if v['name']=='AO_Fill_Command':v.update(name='AO_Inlet',location='%QW40',aliases=['válvula del depósito'])
    value['variables'].append(db_entry())
    value['vendor_extension']={'preserve':True}
    return value


def test_product_map_preserves_analog_and_db_devices():
    value=scenario();before=copy.deepcopy(value)
    result=prepare(value)
    assert value==before
    for v in [v for v in value['variables'] if v['type'] != 'BOOL' or not v.get('location', '').startswith(('%IX', '%QX'))]:
        assert next(x for x in result['io_map']['variables'] if x['name']==v['name'])==v


def test_product_map_retains_unknown_ownership():
    value=scenario();result=prepare(value,previous_program_id='old')
    assert 'AI_Reservoir' in result['retained_unknown']
    assert 'AI_Reservoir' not in {v['name'] for v in result['released']}
    assert all(v['name'] not in result['retained_unknown'] for v in result['released'])


def test_product_map_recycles_digital_bindings_but_keeps_manual_reservations():
    value=mapped();value['metadata']['current_program']={'program_id':'old'}
    for name,source,owner in [('Q_Digital_1','AUTO','old'),('Q_Digital_2','AUTO','other'),('Q_Digital_3','MANUAL','old')]:
        next(v for v in value['variables'] if v['name']==name).update(assignment_source=source,owner_program_id=owner)
    result=prepare(value)
    assert {r['name'] for r in result['released']} >= {'Q_Digital_1', 'Q_Digital_2'}
    assert 'Q_Digital_3' not in {r['name'] for r in result['released']}
    assert next(v for v in result['io_map']['variables'] if v['name']=='Q_Digital_1')['state']=='FREE'
    assert prepare(value,scope='EXTEND_PROGRAM')['io_map']==value
    with pytest.raises(ValueError):prepare(value,scope='other')


def test_product_working_map_allows_db_only_scenario(tmp_path):
    value={'metadata':{'map_id':'process'},'variables':[db_entry()]}
    source=tmp_path/'source.json';source.write_text(json.dumps(value))
    reference=T.create_working_map(tmp_path/'trial',source,map_policy=P.MAP_POLICY)
    assert reference['physical_channel_count']==0
    assert T.load_working_map(reference['working_map_path'])['variables']==value['variables']
    with pytest.raises(T.ExperimentIOError):T.create_working_map(tmp_path/'legacy',source)


def test_product_map_policy_is_recorded_and_frozen(tmp_path):
    value=scenario();source=tmp_path/'source.json';source.write_text(json.dumps(value))
    reference=T.create_working_map(tmp_path/'trial',source,map_policy=P.MAP_POLICY)
    assert reference['map_policy']==P.MAP_POLICY
    working=T.load_working_map(reference['working_map_path'])
    snapshot=T.build_snapshot(working,{},reference,'trial')
    assert snapshot['map_policy']==P.MAP_POLICY
    assert snapshot['declared_variables']==working['variables']
    assert source.read_text()==json.dumps(value)
    with pytest.raises(ValueError):T.create_working_map(tmp_path/'bad',source,map_policy='unknown')


def test_legacy_map_cleaning_remains_explicitly_available(tmp_path):
    prepare(mapped())
    value=scenario();source=tmp_path/'source.json';source.write_text(json.dumps(value))
    reference=T.create_working_map(tmp_path/'trial',source,map_policy='LEGACY_CLEARED_V1')
    working=T.load_working_map(reference['working_map_path'])
    assert not any(v['name']=='M_Level' for v in working['variables'])
    assert next(v for v in working['variables'] if v['location']=='%IW40')['aliases']==[]


def test_normal_commit_does_not_turn_declared_devices_into_releasable_bindings(tmp_path):
    """Exercise the actual Normal commit, then prepare the next program."""
    import hashlib
    from types import SimpleNamespace
    import gui
    from test_normal_control_strategy import semantic
    from test_native_pid_resolution import request

    value=scenario()
    for v in value['variables']:
        if v['name'] in {'AI_Reservoir','AO_Inlet'}:
            v.pop('assignment_source',None);v.pop('owner_program_id',None)
    path=tmp_path/'user_map.json';path.write_text(json.dumps(value),encoding='utf-8')
    working=prepare(value)['io_map']
    loop=request();loop.update(process_input='AI_Reservoir',control_output='AO_Inlet')
    app=SimpleNamespace(
        io_map_path=path,_file_sha256=lambda p:hashlib.sha256(p.read_bytes()).hexdigest(),
        _program_metadata_allowed=lambda:True,
        pending_semantic_output=semantic('Controla el nivel con PID.',[loop]),
        _normal_program_context={'scope':'NEW_PROGRAM','current_program':None},
        _log=lambda m:None,_load_active_map_metadata_shadow=lambda:None,_load_io_map_table=lambda:None,
        _persist_generated_functional_variables=lambda v:None,
        _pending_map_transaction={'map_path':path,'base_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'map':working,'history_entries':[],'proposals':[]})
    assert gui.VozLLMPLCGUI._commit_pending_map_transaction(app)
    committed=json.loads(path.read_text(encoding='utf-8'))
    subsequent=prepare(committed)
    assert not {'AI_Reservoir','AO_Inlet'} & {v['name'] for v in subsequent['released']}
    for name in ['AI_Reservoir','AO_Inlet']:
        device=next(v for v in committed['variables'] if v['name']==name)
        assert not device.get('assignment_source') and not device.get('owner_program_id')


def test_strict_commit_transfers_only_owned_or_new_allocations():
    import normal_program_bindings as PB
    value=scenario()
    vars={v['name']:v for v in value['variables']}
    vars['Q_Digital_1'].update(assignment_source='AUTO',owner_program_id='prior')
    vars['Q_Digital_2'].update(state='ASSIGNED')
    vars['Q_Digital_3'].update(assignment_source='AUTO',owner_program_id='other')
    stamped=PB.stamp_program_bindings(value,['Q_Digital_1','Q_Digital_2','Q_Digital_3','AO_Inlet'],'next',
        strict_owner=True,previous_program_id='prior',newly_assigned_names={'Q_Digital_2'})
    result={v['name']:v for v in stamped['variables']}
    assert result['Q_Digital_1']['owner_program_id']=='next'
    assert result['Q_Digital_2']['owner_program_id']=='next' and result['Q_Digital_2']['assignment_source']=='AUTO'
    assert result['Q_Digital_3']==vars['Q_Digital_3']
    assert result['AO_Inlet']==vars['AO_Inlet'] and value['variables'][-1]==stamped['variables'][-1]
