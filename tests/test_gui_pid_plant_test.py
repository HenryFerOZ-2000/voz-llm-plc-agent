import inspect
import threading
import time

from test_native_pid_generation import project


def test_no_pid_environment_selector_or_injection(app):
    import gui
    assert not hasattr(app, 'pid_mode_selector')
    assert 'pid_execution_mode' not in inspect.getsource(gui.VozLLMPLCGUI.process_command)


def test_open_panel_never_starts_model(app):
    from pid_commissioning import build_pid_process_bindings
    from pid_commissioning_view import PidCommissioningPanel
    calls=[]
    panel=PidCommissioningPanel(app,build_pid_process_bindings(project()),
        lambda *args:calls.append(args),lambda:calls.append('read'),
        on_test=lambda:calls.append('test'),on_cancel_test=lambda:calls.append('cancel'))
    try:
        app.update_idletasks()
        assert calls==[]
        panel.test_button.invoke()
        assert calls==['test']
        panel.show_test_status({'status':'FAILED','errors':['PID_PROGRAM_MISMATCH'],
                                'cleanup':{'cleanup_verified':False}})
        assert 'PID_PROGRAM_MISMATCH' in panel.test_status_var.get()
        assert 'False' in panel.test_status_var.get()
    finally:panel.destroy()


def test_test_job_background_cancel_and_single_owner(tmp_path):
    from pid_plant_test import PlantTestJob
    entered=threading.Event()
    owner=threading.get_ident()
    def provider(package,target,profile,cancel,report_dir):
        assert threading.get_ident()!=owner
        entered.set();cancel.wait(5)
        return {'status':'CANCELLED','cleanup':{'cleanup_verified':True}}
    job=PlantTestJob(provider=provider)
    before=time.monotonic()
    assert job.start(tmp_path,{}, {},tmp_path) is True
    assert time.monotonic()-before<.2 and entered.wait(1)
    assert job.start(tmp_path,{}, {},tmp_path) is False
    job.cancel();job.thread.join(1)
    assert job.poll()['cleanup']['cleanup_verified'] is True


