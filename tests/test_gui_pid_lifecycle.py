"""Real GUI callbacks with external TIA/runtime boundaries replaced by controlled jobs."""
import json
import gc
import threading
import time

import pytest


@pytest.fixture
def pid_panel(app, tmp_path, monkeypatch, intents_catalog, safety_rules):
    import gui
    import pid_plant_test as plant
    from test_native_pid_package import package
    from pid_commissioning_view import PidCommissioningPanel
    path = package(tmp_path, intents_catalog, safety_rules)
    (path/'tia_compile_report.json').write_text(json.dumps({'status':'TIA_COMPILATION_PASSED'}))
    (path/'tia_download_report.json').write_text(json.dumps({'download_success':True}))
    for flag in ('_tia_worker_active','_download_worker_active','_runtime_worker_active',
                 '_oracle_worker_active','_deferred_worker_active','_map_sync_worker_active'):
        monkeypatch.setattr(app, flag, False)
    monkeypatch.setattr(app, '_pid_project_operation', None, raising=False)
    monkeypatch.setattr(app, '_application_close_pending', False, raising=False)
    monkeypatch.setattr(app, '_pid_shutdown_error', None, raising=False)
    monkeypatch.setattr(app, '_io_program_context', {'package_dir':path})
    monkeypatch.setattr(app, '_last_runtime_report', {'connected':True,'cpu_state':'RUN','instance_name':'TEST_ONLY'})
    monkeypatch.setattr(app, '_io_test_target_type', lambda:'PLCSIM_ADVANCED')
    monkeypatch.setattr(gui.messagebox, 'showwarning', lambda *a:None)
    external = threading.Event()
    def unexpected_model(*a, **k):
        external.set();raise AssertionError('Competing model started')
    monkeypatch.setattr(plant,'run_tank_test',unexpected_model)
    app.work_mode_var.set('Normal')
    app.open_pid_commissioning()
    window = app._pid_commissioning_window
    panel = next(w for w in window.winfo_children() if isinstance(w, PidCommissioningPanel))
    panel.show_values({'PV':40.,'ParametersConfirmed':True})
    panel.show_parameter_state({'state':'PENDING_SAVE'})
    yield panel, window, external
    # Finish production callbacks before removing the test's external dependencies.
    closer = getattr(app, '_pid_close_request', None)
    if closer and window.winfo_exists(): closer()
    deadline = time.monotonic()+2
    while window.winfo_exists() and time.monotonic()<deadline:
        app.update(); time.sleep(.01)
    if window.winfo_exists(): window.destroy()
    app._pid_commissioning_window = None
    gc.collect()  # Tk variables must be finalized on the owning UI thread.


@pytest.mark.parametrize('flag', ['_tia_worker_active','_download_worker_active','_deferred_worker_active','_map_sync_worker_active'])
@pytest.mark.parametrize('action', ['read','write','save','evaluate','model'])
def test_open_pid_panel_rechecks_shared_busy_state(pid_panel, app, monkeypatch, flag, action):
    import pid_commissioning as commissioning
    import pid_parameter_store as store
    import pid_plant_test as plant
    from trial_experiments import native_pid_protocol as protocol
    panel, _, external = pid_panel
    def reached(*a, **k): external.set(); raise AssertionError('Competing PID operation started')
    monkeypatch.setattr(commissioning.PidCommissioningSession,'read',reached)
    monkeypatch.setattr(commissioning.PidCommissioningSession,'write',reached)
    # save_verified_parameters was captured when the panel opened: its first external action is read().
    monkeypatch.setattr(protocol,'create_native_validation_run',reached)
    monkeypatch.setattr(plant,'run_tank_test',reached)
    panel.tuning_var.set(True)
    monkeypatch.setattr(app,flag,True)
    if action=='read': panel.on_read()
    elif action=='write': panel.on_write('CmdStart',True,False)
    elif action=='save': panel.on_save()
    elif action=='evaluate': panel.on_evaluate()
    else: panel.test_button.invoke()
    assert external.wait(.05) is False
    assert app._pid_project_operation is None


def test_main_close_waits_for_pid_cleanup(pid_panel, app, monkeypatch):
    from trial_experiments import native_pid_protocol as protocol, deferred_evaluator
    panel, window, _ = pid_panel
    entered, cancelled, release, finished = [threading.Event() for _ in range(4)]
    monkeypatch.setattr(protocol,'create_native_validation_run',lambda *a:app.project_root/'runtime/TEST_ONLY')
    def evaluation(*a, cancel):
        entered.set(); cancel.wait(3); cancelled.set(); release.wait(3)
        finished.set()
        return {'status':'FAILED','reason':'PID_TEST_CANCELLED','cleanup_verified':True}
    monkeypatch.setattr(deferred_evaluator,'run_frozen_native_development',evaluation)
    destroyed=[]
    monkeypatch.setattr(app,'destroy',lambda:destroyed.append(finished.is_set()))
    panel.tuning_var.set(True);panel.on_evaluate()
    assert entered.wait(1), {key:value for key,value in vars(app).items() if 'active' in key or 'operation' in key or 'close_pending' in key}
    try:
        app._on_close()
        assert cancelled.wait(1)
        assert destroyed==[], 'The main window must survive until cleanup completes'
        assert window.winfo_exists()
    finally:
        release.set()
    deadline=time.monotonic()+2
    while not destroyed and time.monotonic()<deadline:
        app.update();time.sleep(.01)
    assert destroyed==[True]


def test_main_close_keeps_failed_cleanup_visible(pid_panel, app, monkeypatch):
    from trial_experiments import native_pid_protocol as protocol, deferred_evaluator
    panel, window, _ = pid_panel
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(protocol,'create_native_validation_run',lambda *a:app.project_root/'runtime/TEST_ONLY')
    def evaluation(*a, cancel):
        entered.set();cancel.wait(3);release.wait(3)
        return {'status':'FAILED','cleanup_verified':False}
    monkeypatch.setattr(deferred_evaluator,'run_frozen_native_development',evaluation)
    destroyed=[]
    monkeypatch.setattr(app,'destroy',lambda:destroyed.append(True))
    panel.tuning_var.set(True);panel.on_evaluate();assert entered.wait(1)
    app._on_close();release.set()
    deadline=time.monotonic()+2
    while getattr(app,'_application_close_pending',False) and time.monotonic()<deadline:
        app.update();time.sleep(.01)
    assert destroyed==[] and window.winfo_exists()
    assert 'FAILED' in panel.test_status_var.get()
    assert app._application_close_pending is False


def test_model_result_retains_ownership_until_cleanup_report_is_consumed(tmp_path):
    from pid_plant_test import PlantTestJob
    job=PlantTestJob(provider=lambda *a:{'status':'FAILED','cleanup':{'cleanup_verified':False}})
    assert job.start(tmp_path,{}, {},tmp_path)
    job.thread.join(1)
    assert job.active is True
    assert job.start(tmp_path,{}, {},tmp_path) is False
    assert job.poll()['cleanup']['cleanup_verified'] is False
    assert job.active is False
