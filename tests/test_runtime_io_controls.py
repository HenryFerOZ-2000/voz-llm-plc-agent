import copy,json
from pathlib import Path
import pytest
import plcsim_runtime_io as rio
import plcsim_runtime
from test_phase2b_runtime_io import _CONFIG,_RUN

def program(tmp_path):
    rows=[{'name':'I_Start','class':'input','location':'%IX16.0','type':'BOOL'},
          {'name':'AI_Level','class':'input','location':'%IW64','type':'INT'},
          {'name':'AO_Valve','class':'output','location':'%QW72','type':'INT'}]
    path=tmp_path/'variables.json';path.write_text(json.dumps(rows))
    config={'confirmed':True,'raw_min':0,'raw_max':27648,'engineering_min':0,'engineering_max':100,'engineering_unit':'%'}
    (tmp_path/'generation_io_map.json').write_text(json.dumps({'variables':[{**r,'analog_config':config} for r in rows if r['type']=='INT']}))
    return rio.load_program_signals(variables_path=path)

def test_numeric_controls_use_frozen_package_scaling_and_addresses(tmp_path):
    from runtime_io_controls import signals,encode_value,decode_value
    data=program(tmp_path)
    level=next(s for s in signals(data,'I') if s['name']=='AI_Level')
    assert level['offset']==64
    assert encode_value(level,50)==13824
    assert decode_value(level,13824)==50
    assert [s['name'] for s in signals(data,'Q')]==['AO_Valve']

@pytest.mark.parametrize('value',[-1,101,True,float('nan'),float('inf')])
def test_invalid_engineering_values_are_rejected(tmp_path,value):
    from runtime_io_controls import encode_value
    with pytest.raises(rio.RuntimeIOError):encode_value(program(tmp_path)['signals']['AI_Level'],value)

def test_mapping_with_a_different_address_cannot_supply_scale(tmp_path):
    from runtime_io_controls import encode_value
    data=program(tmp_path)
    path=tmp_path/'generation_io_map.json';mapping=json.loads(path.read_text());mapping['variables'][0]['location']='%IW4';path.write_text(json.dumps(mapping))
    loaded=rio.load_program_signals(variables_path=tmp_path/'variables.json')
    assert 'analog_config' not in loaded['signals']['AI_Level']

def test_manual_output_command_is_denied_while_program_is_running(tmp_path):
    from runtime_io_controls import ManualIOSession
    calls=[]
    session=ManualIOSession(program(tmp_path),'PLCSIM_ADVANCED',dict(_RUN),runtime_config=_CONFIG,bridge=lambda *a:calls.append(a))
    with pytest.raises(rio.RuntimeIOError,match='STOP'):session.write_output('AO_Valve',50)
    assert not calls

def test_manual_control_never_writes_a_physical_plc(tmp_path):
    from runtime_io_controls import ManualIOSession
    session=ManualIOSession(program(tmp_path),'PHYSICAL_PLC',{**_RUN,'cpu_state':'STOP'},runtime_config=_CONFIG,bridge=lambda *a:pytest.fail('physical access'))
    with pytest.raises(rio.RuntimeIOError):session.write_output('AO_Valve',50)

def test_manual_bridge_transport_contract():
    raw=plcsim_runtime.run_runtime_bridge('manual_io_self_test',Path(__file__).resolve().parents[1])
    assert raw['status']=='PLCSIM_MANUAL_IO_SELF_TEST_PASSED',raw
    assert len(raw['checks'])>=8
    assert all(item['passed'] for item in raw['checks'])

def test_visible_io_access_and_numeric_controls(app,tmp_path):
    import gui
    assert app.io_test_button.winfo_manager()=='grid'
    app._io_program_context={'purpose':'normal'}
    window=gui.RuntimeIOTestWindow(app,program(tmp_path),'PLCSIM_ADVANCED',dict(_RUN),tmp_path,None)
    try:
        assert 'AI_Level' in window.input_menu.cget('values')
        assert 'AO_Valve' in window.output_menu.cget('values')
        window.input_var.set('AI_Level');window.select_input('AI_Level')
        assert window.input_slider.cget('from_')==0
        assert window.input_slider.cget('to')==100
        assert window.output_slider.cget('state')=='disabled'
    finally:window.destroy()

def test_open_io_panel_blocks_generation_and_target_changes(app,tmp_path):
    import gui
    window=gui.RuntimeIOTestWindow(app,program(tmp_path),'PLCSIM_ADVANCED',dict(_RUN),tmp_path,None)
    app._io_test_window=window
    try:
        assert app._tia_busy()
        assert app._target_operation_busy()
    finally:app._io_test_window=None;window.destroy()

def test_shutdown_requests_io_cleanup_before_destroying_application(app,monkeypatch):
    calls=[]
    class Window:
        _busy=False;_closing=False
        def winfo_exists(self):return True
        def close(self):calls.append('restore');self._closing=True
    app._io_test_window=Window()
    monkeypatch.setattr(app,'destroy',lambda:calls.append('destroy'))
    monkeypatch.setattr(app,'after',lambda *a:None)
    try:
        app._on_close()
        assert calls==['restore']
    finally:app._io_test_window=None;app._application_close_pending=False

class MemoryBridge:
    """Transport fixture with real session/conversion code on the client side."""
    def __init__(self):self.values={'AI_Level':7000,'AO_Valve':0,'I_Start':False};self.calls=[];self.fail_restore=False
    def __call__(self,action,payload):
        self.calls.append(copy.deepcopy(payload));s=payload['signal'];op=payload['operation'];name=s['name']
        raw={'status':'PLCSIM_IO_PASSED','writes':[],'reads':[],'errors':[]}
        if op=='read':raw['reads']=[{'name':name,'value':self.values[name]}]
        elif op=='restore' and self.fail_restore:return {**raw,'status':'PLCSIM_IO_WRITE_NOT_ALLOWED','errors':['lost CPU state']}
        else:
            self.values[name]=payload['value']
            raw['writes']=[{'name':name,'actual_readback':payload['value'],'readback_tag':payload['value'],'match':True}]
        return raw

def test_numeric_session_sends_raw_then_restores_original_not_zero(tmp_path):
    from runtime_io_controls import ManualIOSession
    bridge=MemoryBridge();session=ManualIOSession(program(tmp_path),'PLCSIM_ADVANCED',dict(_RUN),runtime_config=_CONFIG,bridge=bridge)
    assert session.write_input('AI_Level',50)['readback']==13824
    assert bridge.values['AI_Level']==13824
    assert session.restore_inputs()['status']==rio.SUCCESS
    assert bridge.values['AI_Level']==7000
    assert not session.originals
    assert len(bridge.calls[-1]['expected_signals'])==3

def test_failed_cleanup_retains_pending_original_for_retry(tmp_path):
    from runtime_io_controls import ManualIOSession
    bridge=MemoryBridge();session=ManualIOSession(program(tmp_path),'PLCSIM_ADVANCED',dict(_RUN),runtime_config=_CONFIG,bridge=bridge)
    session.write_input('AI_Level',50);bridge.fail_restore=True
    assert session.restore_inputs()['status']==rio.ERROR_CLEANUP_FAILED
    assert session.originals['AI_Level']['value']==7000
    assert session.build_report()['runtime_io_test']==rio.FAIL
    bridge.fail_restore=False
    assert session.restore_inputs()['status']==rio.SUCCESS
    assert bridge.values['AI_Level']==7000

def test_output_manual_mode_uses_numeric_command_and_restoration_in_stop(tmp_path):
    from runtime_io_controls import ManualIOSession
    bridge=MemoryBridge();session=ManualIOSession(program(tmp_path),'PLCSIM_ADVANCED',{**_RUN,'cpu_state':'STOP'},runtime_config=_CONFIG,bridge=bridge)
    session.write_output('AO_Valve',50)
    assert bridge.values['AO_Valve']==13824
    assert session.restore_inputs()['status']==rio.SUCCESS
    assert bridge.values['AO_Valve']==0

def test_numeric_manual_observations_do_not_claim_bool_or_oracle_capabilities():
    section=rio.trial_runtime_io_section({'writes':[{'match':True,'requested_value':13824}],
                                         'reads':[{'value':13824}]})
    assert section['bool_input_write_supported'] is False
    assert section['bool_read_supported'] is False
    assert rio.RUNTIME_CAPABILITIES==('BOOL','REAL','INTERNAL_TAG_READ','INTERNAL_TAG_WRITE')
