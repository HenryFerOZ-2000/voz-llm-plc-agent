import queue
import pytest
import gui
import plc_targets


def test_cancel_keeps_configuration_bytes(app,tmp_path):
    from plc_target_dialog import PlcTargetDialog
    before=list(tmp_path.iterdir())
    dialog=PlcTargetDialog(app,{'target_type':'PLCSIM_ADVANCED'},{});dialog.cancel()
    assert dialog.result is None and list(tmp_path.iterdir())==before


def test_old_target_result_is_not_rendered(app,monkeypatch):
    monkeypatch.setattr(app,'_runtime_worker_active',True)
    monkeypatch.setattr(app,'_runtime_callbacks',[])
    monkeypatch.setattr(app,'_current_target_identity',lambda:'B')
    monkeypatch.setattr(app,'_runtime_query_identity','A',raising=False)
    monkeypatch.setattr(app,'_render_runtime_report',lambda r:pytest.fail('Stale RUN rendered'))
    q=queue.Queue();q.put(('success',{'connected':True,'cpu_state':'RUN'}))
    monkeypatch.setattr(app,'_runtime_worker_queue',q)
    app._poll_runtime_worker()
    assert app._runtime_worker_active is False


@pytest.mark.parametrize('flag',['_tia_worker_active','_download_worker_active','_voice_worker_active','_map_sync_worker_active','_oracle_worker_active','_deferred_worker_active'])
def test_target_cannot_change_during_operation(app,monkeypatch,flag):
    monkeypatch.setattr(app,flag,True)
    assert app._target_operation_busy()


def test_target_cannot_change_during_capture(app,monkeypatch):
    monkeypatch.setattr(app.speech_recognizer,'is_recording',lambda:True)
    assert app._target_operation_busy()


def test_physical_status_never_queries_plcsim(app,monkeypatch):
    monkeypatch.setattr(plc_targets,'load_normal_target',lambda r:{'target_type':'PHYSICAL_PLC','target_address':'192.168.0.2'})
    monkeypatch.setattr(gui,'get_plcsim_runtime_status',lambda *a,**k:pytest.fail('Physical target polled PLCSIM'))
    app._start_runtime_refresh('test')
    assert 'sin verificar' in app.plc_cpu_var.get().lower()
    assert 'RUN' not in app.plc_cpu_var.get()


def test_discovery_does_not_select_first_and_closed_result_is_ignored(app):
    from plc_target_dialog import PlcTargetDialog
    dialog=PlcTargetDialog(app,{'target_type':'PLCSIM_ADVANCED'},{});
    dialog.events.put(('instances',{'instances':[{'instance_id':1,'instance_name':'A'},{'instance_id':2,'instance_name':'B'}]}))
    dialog.events.put(('connections',{'connections':[{'mode':'PN/IE','pc_interface':'PLCSIM','number':1,'target_interfaces':['1 X1']}]}))
    dialog.poll()
    assert dialog.instance_box.current()==-1 and dialog.route_box.current()==-1
    dialog.cancel();dialog.events.put(('instances',{'instances':[]}));dialog.poll()
    assert dialog.result is None


def test_save_error_preserves_availability(app,monkeypatch):
    old=app._last_compiled_package_dir
    monkeypatch.setattr(app,'_target_operation_busy',lambda:False)
    monkeypatch.setattr(app,'wait_window',lambda d:None)
    monkeypatch.setattr(gui,'PlcTargetDialog',lambda *a:type('Dialog',(),{'result':{'target_type':'PHYSICAL_PLC'}})())
    monkeypatch.setattr(plc_targets,'save_normal_target',lambda *a:(_ for _ in ()).throw(OSError('disk unavailable')))
    errors=[];monkeypatch.setattr(gui.messagebox,'showerror',lambda *a:errors.append(a))
    app.work_mode_var.set('Normal');app.select_normal_plc_target()
    assert errors and app._last_compiled_package_dir==old and not app._target_selector_open
