import threading
import time

from test_native_pid_generation import project
from pid_commissioning import build_pid_process_bindings


def test_panel_requires_fresh_state_and_explicit_save(app):
    from pid_commissioning_view import PidCommissioningPanel
    calls=[]
    panel=PidCommissioningPanel(app,build_pid_process_bindings(project()),lambda *a:None,
        lambda:None,on_save=lambda:calls.append('save'),on_evaluate=lambda:calls.append('eval'))
    try:
        assert calls==[]
        assert panel.save_button.cget('state')=='disabled'
        import customtkinter as ctk
        start=next(w for w in panel.winfo_children() if isinstance(w,ctk.CTkButton) and w.cget('text')=='Marcha')
        assert start.cget('state')=='disabled'
        panel.show_values({'PV':40.,'ParametersConfirmed':True})
        assert start.cget('state')=='normal'
        panel.show_parameter_state({'state':'PENDING_SAVE','reason':'CPU verificada'})
        panel.save_button.invoke()
        assert calls==['save']
        panel.set_operation_state('SAVING')
        assert panel.save_button.cget('state')=='disabled'
        assert panel.evaluate_button.cget('state')=='disabled'
        panel.set_operation_state(None)
        panel.show_parameter_state({'state':'INCOMPATIBLE','reason':'PID_PROGRAM_MISMATCH'})
        assert panel.save_button.cget('state')=='disabled'
        assert 'PID_PROGRAM_MISMATCH' in panel.parameter_status_var.get()
    finally:panel.destroy()


def test_operation_job_serializes_cancel_and_errors():
    from pid_commissioning import PidOperationJob
    job=PidOperationJob();entered=threading.Event();owner=threading.get_ident()
    def work(cancel):
        assert threading.get_ident()!=owner
        entered.set();cancel.wait(3)
        return {'status':'CANCELLED'}
    assert job.start('SAVING',work) is True and entered.wait(1)
    assert job.start('EVALUATING',work) is False
    job.cancel();job.thread.join(1)
    assert job.poll()==('SAVING','ok',{'status':'CANCELLED'})
    assert job.active is False
    def failed(cancel):raise ValueError('provider failed')
    assert job.start('EVALUATING',failed)
    job.thread.join(1)
    assert job.poll()==('EVALUATING','error','provider failed')


def test_project_operation_blocks_generation_before_map_mutation(app,monkeypatch):
    import gui
    app._pid_project_operation='SAVING'
    messages=[]
    monkeypatch.setattr(gui.messagebox,'showwarning',lambda *a:messages.append(a))
    monkeypatch.setattr(app,'save_io_map',lambda **k:(_ for _ in ()).throw(AssertionError('Map touched')))
    previous=app.command_textbox.get('1.0','end')
    app.command_textbox.delete('1.0','end');app.command_textbox.insert('1.0','Enciende la salida con Start.')
    try:
        assert app.process_command() is False
        assert messages
    finally:
        app._pid_project_operation=None
        app.command_textbox.delete('1.0','end');app.command_textbox.insert('1.0',previous)


def test_project_operation_also_blocks_experimental_and_map_actions(app,monkeypatch,tmp_path):
    import gui
    app._pid_project_operation='EVALUATING'
    monkeypatch.setattr(gui.messagebox,'showwarning',lambda *a:None)
    monkeypatch.setattr(app,'_collect_io_variables',lambda:(_ for _ in ()).throw(AssertionError('Map sync began')))
    try:
        assert app._tia_busy() is True
        assert app._start_deferred_evaluation(tmp_path,None) is False
        app.sync_plc_map_with_tia()
    finally:app._pid_project_operation=None
