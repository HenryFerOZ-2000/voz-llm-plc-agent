"""Behavior regressions from the single final closure review; no live PLC access."""
import ast
import inspect
import threading
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('name', ['I_Start_Position', 'I_Start'])
def test_declared_position_sensor_is_level_sensitive(name, tmp_path):
    from test_normal_mode_hardening import _bench, _program, _Plc
    source = _bench(outputs={'Q_Alarm': '%QX2.0'}, inputs={'I_Reset': '%IX2.1'})
    if name != 'I_Start':
        from test_normal_mode_hardening import _channel
        source['variables'].append(_channel(name, '%IX2.0', 'ASSIGNED'))
    # The explicit device meaning must override a misleading operator-facing name.
    next(v for v in source['variables'] if v['name'] == name)['semantic_role'] = 'POSITION_SENSOR'
    result = _program('Activa y enclava la alarma cuando el sensor de posicion este activo; Reset la apaga.',
        [{'type': 'latch', 'set': name, 'reset': 'I_Reset', 'output': 'Q_Alarm'}], tmp_path, source)
    plc = _Plc(result['scl'])
    plc.io.update({name: True, 'I_Reset': False})
    plc.run(100)
    assert plc.io['Q_Alarm'] is True


def test_cancellation_during_final_provider_join_cannot_pass(tmp_path):
    import pid_native_validation as native
    # Exercise the production finally block after all stages have genuinely passed.
    # The external cancellation occurs at the provider boundary, during cleanup.
    function = ast.parse(inspect.getsource(native.run_map_pid_validation)).body[0]
    final = next(node for node in function.body if isinstance(node, ast.Try)).finalbody
    cancel = threading.Event()
    class Provider:
        def join(self, timeout): cancel.set()
        def is_alive(self): return False
    outcome = {'status': 'RUNNING'}
    stages = {name: {'status': 'PASSED'} for name in native.STAGES}
    environment = {**vars(native), 'io': None, 'session': None, 'worker': Provider(),
        'stop_provider': threading.Event(), 'external_cancel': cancel,
        'provider_result': {'status': 'CANCELLED', 'errors': [], 'native_execution_verified': True,
                            'cleanup': {'cleanup_verified': True}},
        'reader': SimpleNamespace(close=lambda: None), 'stages': stages, 'outcome': outcome,
        'evidence': tmp_path, 'flush': lambda: None}
    exec(compile(ast.fix_missing_locations(ast.Module(body=final, type_ignores=[])), '<native-finally>', 'exec'), environment)
    assert outcome['cleanup_verified'] is True
    assert outcome['status'] != 'PASSED'
    assert outcome['reason'] == 'PID_TEST_CANCELLED'
