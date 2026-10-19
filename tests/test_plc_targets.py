import copy
import json
import pytest
import plc_targets as targets


def candidate():
    return {'target_type':'PLCSIM_ADVANCED','target_name':'Banco',
        'configuration_mode':'PN/IE','pc_interface':'Virtual','pc_interface_number':1,
        'target_interface':'1 X1','target_address':'192.168.0.1',
        'instance_name':'Banco','instance_id':7,'project_path':'C:/Normal.ap18'}


def test_identity_tracks_endpoint_not_caption():
    a=candidate()
    assert targets.target_identity(a)==targets.target_identity({**a,'target_name':'Otra etiqueta'})
    for field,value in [('target_address','192.168.0.2'),('pc_interface','Ethernet'),
        ('instance_id',8),('project_path','C:/Other.ap18')]:
        assert targets.target_identity(a)!=targets.target_identity({**a,field:value})


@pytest.mark.parametrize('address',['999.0.0.1','0.0.0.0','224.0.0.1','255.255.255.255','localhost','::1'])
def test_invalid_address_is_rejected(address):
    with pytest.raises(ValueError):targets.normalize_target({**candidate(),'target_address':address})


def root_config(tmp_path):
    p=tmp_path/'config/tia_openness_config.json';p.parent.mkdir()
    data={'project_path':'C:/Normal.ap18','custom':{'keep':1},
        'download_targets':{'normal':{'target_type':'PLCSIM_ADVANCED','target_name':'Old'},
            'experiment':{'target_type':'PLCSIM_ADVANCED','target_name':'MASTER'}},
        'plcsim_runtime':{'instance_name':'Old','timeout_seconds':20}}
    p.write_text(json.dumps(data));return p,data


def test_save_updates_normal_and_runtime_preserving_other_settings(tmp_path):
    p,before=root_config(tmp_path)
    targets.save_normal_target(tmp_path,candidate(),targets.read_target_revision(tmp_path))
    after=json.loads(p.read_text())
    assert after['download_targets']['normal']['target_address']=='192.168.0.1'
    assert after['download_targets']['normal']['instance_name']=='Banco'
    assert after['download_targets']['normal']['instance_id']==7
    assert after['plcsim_runtime']==before['plcsim_runtime']
    assert after['download_targets']['experiment']==before['download_targets']['experiment']
    assert after['custom']=={'keep':1} and after['plcsim_runtime']['timeout_seconds']==20


def test_stale_revision_and_failed_replace_preserve_file(tmp_path,monkeypatch):
    p,data=root_config(tmp_path);revision=targets.read_target_revision(tmp_path)
    p.write_text(json.dumps({**data,'custom':'user edit'}));before=p.read_bytes()
    with pytest.raises(ValueError):targets.save_normal_target(tmp_path,candidate(),revision)
    assert p.read_bytes()==before
    revision=targets.read_target_revision(tmp_path)
    def fail(*args):raise OSError('disk unavailable')
    monkeypatch.setattr(targets.os,'replace',fail)
    with pytest.raises(OSError):targets.save_normal_target(tmp_path,candidate(),revision)
    assert p.read_bytes()==before


def test_legacy_target_load_preserves_path_without_adding_address(tmp_path):
    p,data=root_config(tmp_path)
    loaded=targets.load_normal_target(tmp_path)
    assert loaded['target_name']=='Old' and not loaded.get('target_address')
    assert json.loads(p.read_text())==data


def test_new_virtual_target_requires_address_and_identity(tmp_path):
    root_config(tmp_path)
    for change in ({'target_address':''},{'instance_name':''}):
        with pytest.raises(ValueError):
            targets.save_normal_target(tmp_path,{**candidate(),**change},targets.read_target_revision(tmp_path))
