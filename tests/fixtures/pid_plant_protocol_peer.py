"""IPC peer for transport tests only; never represents a Siemens runtime."""
import json
import os
import sys
import time

mode = os.environ.get('PID_IO_TEST_SCENARIO', 'ok')

def reply(value):
    print(json.dumps(value), flush=True)

reply({'id': 0, 'status': 'PID_PLANT_READY', 'peer_pid': os.getpid(), 'snapshot': {'measurement': 11}})
for line in sys.stdin:
    message = json.loads(line)
    response = {'id': message['id'], 'peer_pid': os.getpid()}
    if message['op'] == 'probe_input_word':
        response.update(status='PID_WORD_PROBE_PASSED', byte_order='big', restored=True,
            samples=[dict(requested=n, address=n, symbol=54 if mode == 'bad_probe' and n == 13824 else n)
                     for n in (0, 13824, 27648)])
    elif message['op'] == 'exchange':
        if mode == 'eof':
            sys.exit(0)
        if mode == 'timeout':
            time.sleep(5)
        if mode == 'changed':
            response.update(status='PID_PROGRAM_MISMATCH', errors=['loaded Build signature changed'])
        else:
            response.update(status='PID_PLANT_SAMPLE', command_percent=40.0, command_raw=11059,
                            measurement_raw=message.get('measurement_raw'), measurement=message.get('measurement'),
                            diagnostics={'Running': False, 'Fault': False})
    elif message['op'] == 'close':
        response.update(status='PID_PLANT_CLOSED', cleanup_verified=mode != 'changed',
                        stop_verified=mode != 'changed', inputs_restored=mode != 'changed')
        reply(response)
        break
    reply(response)
