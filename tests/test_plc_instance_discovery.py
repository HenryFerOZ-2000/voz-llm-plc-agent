import pytest
import plcsim_runtime as module


def test_duplicate_names_require_matching_identity():
    instances=[{'instance_id':1,'instance_name':'Banco'},{'instance_id':2,'instance_name':'Banco'}]
    with pytest.raises(ValueError):module.resolve_instance(instances,{'instance_name':'Banco'})
    assert module.resolve_instance(instances,{'instance_id':2,'instance_name':'Banco'})['instance_id']==2
    with pytest.raises(ValueError):module.resolve_instance(instances,{'instance_id':2,'instance_name':'Otro'})


@pytest.mark.parametrize('instances,target',[
    ([],{'instance_name':'Banco'}),
    ([{'instance_id':1,'instance_name':'TESIS_PLC_SIM'}],{'instance_name':'Otro'}),
    ([{'instance_id':1,'instance_name':'Banco'}],{'instance_name':'Banco','instance_id':2}),
    ([{'instance_id':1,'instance_name':'Banco'}],{}),
])
def test_absent_selection_never_falls_back(instances,target):
    with pytest.raises(ValueError):module.resolve_instance(instances,target)


def test_list_keeps_unknown_address_unknown(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'run_runtime_bridge',lambda *a,**k:{'status':'PLCSIM_INSTANCES_PASSED','instances':[{'instance_id':2,'instance_name':'Banco','read_errors':['IP unavailable']}],'errors':[]})
    report=module.list_plcsim_instances(tmp_path)
    assert report['instances'][0].get('target_address') is None
    assert report['instances'][0]['instance_name']=='Banco'


def test_preview_does_not_persist_or_use_default_instance(tmp_path,monkeypatch):
    seen=[]
    monkeypatch.setattr(module,'_load_tia_config',lambda r:{'plcsim_runtime':{'instance_name':'TESIS_PLC_SIM'}})
    monkeypatch.setattr(module,'run_runtime_bridge',lambda a,r,c:seen.append(c) or {'status':'PLCSIM_INSTANCE_NOT_FOUND','errors':[]})
    monkeypatch.setattr(module,'write_runtime_report',lambda *a:pytest.fail('Preview persisted global state'))
    target={'instance_name':'Banco','instance_id':2,'target_address':'192.168.0.2'}
    report=module.get_plcsim_runtime_status(tmp_path,target=target)
    assert seen[0]['instance_name']=='Banco'
    assert seen[0]['instance_id']==2
    assert report['target_identity']
