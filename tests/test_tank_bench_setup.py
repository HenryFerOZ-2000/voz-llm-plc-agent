import copy
import hashlib
import json

import pytest


def bench():
    variables = []
    for area, cls, byte in [('I','input',16), ('Q','output',8)]:
        for bit in range(8):
            variables.append({'name':f'{area}_Digital_{bit}', 'type':'BOOL', 'class':cls,
                'location':f'%{area}X{byte}.{bit}', 'state':'LOCKED' if bit==0 else 'ASSIGNED', 'aliases':['keep']})
    for area, cls, prefix in [('I','input','AI'),('Q','output','AO')]:
        for word in (0,2,4,6):
            variables.append({'name':f'{prefix}_{area}W{word}', 'type':'INT', 'class':cls,
                'location':f'%{area}W{word}', 'state':'FREE','llm_allowed':False,'unit':'mA','extension':{'keep':1}})
    return {'schema_version':1,'metadata':{'map_id':'mapa_banco_fisico','version':8},
            'variables':variables,'history':[{'old':'keep'}], 'vendor_extension':{'keep':True}}


def test_only_selected_analog_channels_change():
    from tank_bench_setup import prepare_tank_bench
    original=bench(); before=copy.deepcopy(original); result=prepare_tank_bench(original)
    assert original==before
    assert len(result['variables'])==24
    changed=[(old,new) for old,new in zip(before['variables'],result['variables']) if old!=new]
    assert [new['location'] for old,new in changed]==['%IW4','%QW4']
    assert [new['name'] for old,new in changed]==['AI_Level_Raw','AO_Fill_Command']
    for old,new in changed:
        assert new['llm_allowed'] is True and new['state']=='ASSIGNED'
        assert new['analog_config']['confirmed'] is False
        assert new['analog_config']['configuration_basis']=='ASSUMED_FOR_TEST'
        assert new['analog_config']['engineering_unit']=='%'
        assert new['extension']==old['extension']


@pytest.mark.parametrize('change',[{'state':'LOCKED'},{'state':'ASSIGNED'}, {'analog_config':{'device_name':'existing'}}])
def test_assigned_or_configured_channel_is_not_overwritten(change):
    from tank_bench_setup import prepare_tank_bench
    original=bench(); original['variables'][18].update(change)
    with pytest.raises(ValueError,match='TANK_CHANNEL_CONFLICT'): prepare_tank_bench(original)


def test_preserves_unknown_metadata_and_history(tmp_path):
    from tank_bench_setup import save_tank_bench
    path=tmp_path/'map.json'; original=bench(); path.write_text(json.dumps(original),encoding='utf-8')
    report=save_tank_bench(path,hashlib.sha256(path.read_bytes()).hexdigest(),tmp_path/'backups')
    saved=json.loads(path.read_text(encoding='utf-8'))
    assert saved['vendor_extension']==original['vendor_extension']
    assert saved['history'][0]=={'old':'keep'}
    assert len(saved['history'])==3
    assert report['changed_addresses']==['%IW4','%QW4']
    assert saved['metadata']['version']==9


def test_concurrent_save_leaves_new_file_untouched(tmp_path):
    from tank_bench_setup import save_tank_bench
    path=tmp_path/'map.json'; path.write_text(json.dumps(bench()),encoding='utf-8')
    expected=hashlib.sha256(path.read_bytes()).hexdigest()
    changed=bench(); changed['vendor_extension']['external_edit']=True
    path.write_text(json.dumps(changed),encoding='utf-8'); before=path.read_bytes()
    with pytest.raises(ValueError,match='MAP_CHANGED'): save_tank_bench(path,expected,tmp_path/'backups')
    assert path.read_bytes()==before


def test_backup_contains_exact_previous_bytes(tmp_path):
    from tank_bench_setup import save_tank_bench
    path=tmp_path/'map.json'; before=json.dumps(bench(),indent=4).encode(); path.write_bytes(before)
    report=save_tank_bench(path,hashlib.sha256(before).hexdigest(),tmp_path/'backups')
    from pathlib import Path
    assert Path(report['backup_path']).read_bytes()==before


def test_wrong_map_identity_is_rejected():
    from tank_bench_setup import prepare_tank_bench
    original=bench(); original['metadata']['map_id']='other_bench'
    with pytest.raises(ValueError,match='TANK_MAP_ID'): prepare_tank_bench(original)
