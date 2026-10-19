from test_native_pid_generation import project


def test_open_and_close_panel_never_writes_or_reads(app):
    from pid_commissioning import build_pid_process_bindings
    from pid_commissioning_view import PidCommissioningPanel
    calls=[]
    panel=PidCommissioningPanel(app,build_pid_process_bindings(project()),lambda *args:calls.append(args),lambda:calls.append('read'))
    panel.grid(row=99,column=0);app.update_idletasks();panel.destroy()
    assert calls==[]


def test_controller_error_is_visible(app):
    from pid_commissioning import build_pid_process_bindings
    from pid_commissioning_view import PidCommissioningPanel
    panel=PidCommissioningPanel(app,build_pid_process_bindings(project()),lambda *a:None,lambda:None)
    try:
        panel.show_values({'PV':31.0,'CV':0.0,'ControllerState':0,'ControllerError':True,'ErrorBits':2048,'Fault':True})
        assert '2048' in panel.status_var.get() and 'True' in panel.status_var.get()
    finally:panel.destroy()
