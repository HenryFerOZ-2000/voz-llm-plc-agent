"""Persistent, explicitly scoped PLCSIM transport for an external plant provider."""
from __future__ import annotations

import json
import math
import queue
import subprocess
import threading
import time
from pathlib import Path

import plcsim_runtime
from pid_package import native_download_project, validate_pid_manifest, validate_experimental_pid_project
from utils import get_project_root

RESPONSE_TIMEOUT_S = 5.0


def validate_plant_binding(binding: dict, role: str, manifest: dict) -> None:
    key = 'input_binding' if role == 'MEASUREMENT' else 'output_binding'
    if role not in {'MEASUREMENT', 'MANIPULATED'} or binding != manifest['loops'][0].get(key):
        raise ValueError('PID_PLANT_BINDING: señal ajena a la conexión compilada.')
    validate_pid_manifest(manifest)
    if binding['role'] != role or binding.get('permission') is not True:
        raise ValueError('PID_PLANT_BINDING: rol/permiso inválido.')


class PidPlantIOSession:
    def __init__(self, package_dir: Path, target: dict, report_dir: Path, deadline_s: float):
        self.package_dir, self.target, self.report_dir = Path(package_dir), dict(target), Path(report_dir)
        if type(deadline_s) not in (int, float) or not math.isfinite(deadline_s) or not 1 <= deadline_s <= 3600:
            raise ValueError('PID_PLANT_DEADLINE: plazo entre 1 y 3600 s requerido.')
        self.deadline_s = deadline_s
        self.process = None
        self.responses = queue.Queue()
        self.sequence = 0
        self.probe_passed = False
        self.failed = False
        self.closed = False
        self.report = {'status': 'PENDING', 'errors': [], 'cleanup_verified': False, 'inputs_restored': False}
        self.stderr = None

    def __enter__(self):
        try:
            self.start()
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *_args):
        self.close()

    def _save(self):
        self.report_dir.mkdir(parents=True, exist_ok=True)
        (self.report_dir/'session_report.json').write_text(json.dumps(self.report, indent=2, allow_nan=False), encoding='utf-8')

    def _error(self, message):
        self.failed = True
        self.report['errors'].append(str(message))
        self._save()
        return ValueError(str(message))

    def start(self) -> dict:
        if self.process is not None or self.closed:
            raise ValueError('PID_PLANT_SESSION: sesión ya iniciada/cerrada.')
        if self.target.get('target_type') != 'PLCSIM_ADVANCED' or not str(self.target.get('instance_name') or '').strip():
            raise ValueError('PID_PLANT_TARGET: requiere una instancia PLCSIM_ADVANCED explícita.')
        root = get_project_root()
        if self.target.get('native_execution_context') is not None:
            validate_experimental_pid_project(self.package_dir,root,self.target['native_execution_context'])
        else:
            native_download_project(self.package_dir, root, 'PLCSIM_ADVANCED')
        self.manifest = json.loads((self.package_dir/'pid_infrastructure.json').read_text(encoding='utf-8'))
        if self.manifest['schema_version'] != 2:
            raise ValueError('PID_PLANT_PACKAGE: el proveedor externo requiere paquete v2.')
        loop = validate_pid_manifest(self.manifest)
        self.input_binding, self.output_binding = loop['input_binding'], loop['output_binding']
        for binding, role in [(self.input_binding, 'MEASUREMENT'), (self.output_binding, 'MANIPULATED')]:
            validate_plant_binding(binding, role, self.manifest)
        self.bindings = json.loads((self.package_dir/'pid_process_bindings.json').read_text(encoding='utf-8'))
        if (self.bindings.get('schema_version') != 2 or self.bindings.get('input_binding') != self.input_binding
                or self.bindings.get('output_binding') != self.output_binding
                or self.bindings.get('instance_db') != loop['symbols']['db']):
            raise ValueError('PID_PLANT_BINDING: descriptores no coinciden con el controlador.')
        self.report_dir.mkdir(parents=True, exist_ok=True)
        request = dict(action='pid_plant_session', purpose='NATIVE_PID_PLANT_TEST',
                       target_type='PLCSIM_ADVANCED', instance_name=self.target['instance_name'],
                       compiled_package_verified=True, manifest=self.manifest, bindings=self.bindings,
                       deadline_s=self.deadline_s, result_path=str((self.report_dir/'bridge_result.json').resolve()),
                       api_dll_path=self.target.get('api_dll_path', str(plcsim_runtime.DEFAULT_RUNTIME_API_DLL)))
        if self.target.get('instance_id') is not None:request['instance_id']=self.target['instance_id']
        request_path = self.report_dir/'session_request.json'
        request_path.write_text(json.dumps(request, indent=2, allow_nan=False), encoding='utf-8')
        build = plcsim_runtime.build_runtime_bridge(root, api_dll=Path(request['api_dll_path']))
        if not build.get('built'):
            raise self._error('PID_PLANT_BUILD: ' + str(build))
        self.stderr = (self.report_dir/'bridge_stderr.log').open('w', encoding='utf-8')
        self.started_at = time.monotonic()
        try:
            self.process = subprocess.Popen([build['exe_path'], str(request_path)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.stderr, text=True, encoding='utf-8', bufsize=1,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception:
            self.stderr.close()
            raise
        self.reader = threading.Thread(target=self._read_responses, daemon=True)
        self.reader.start()
        response = self._receive(0)
        if response.get('status') != 'PID_PLANT_READY':
            raise self._error('PID_PLANT_START: ' + str(response))
        self.report.update(status='RUNNING', started=response, process_id=self.process.pid)
        self._save()
        return response

    def _read_responses(self):
        try:
            for line in self.process.stdout:
                try:
                    self.responses.put(json.loads(line))
                except ValueError:
                    self.responses.put({'status': 'PID_PLANT_PROTOCOL', 'errors': [line[:200]]})
        finally:
            self.responses.put(None)

    def _receive(self, expected_id):
        until = time.monotonic() + RESPONSE_TIMEOUT_S
        while True:
            try:
                response = self.responses.get(timeout=max(.001, until-time.monotonic()))
            except queue.Empty:
                raise self._error('PID_PLANT_TIMEOUT: no respondió el proveedor runtime.')
            if response is None:
                raise self._error('PID_PLANT_EOF: el puente cerró sin responder.')
            if response.get('status') == 'PID_PLANT_PROTOCOL':
                raise self._error(str(response))
            if response.get('id') == expected_id:
                return response
            if time.monotonic() >= until:
                raise self._error('PID_PLANT_TIMEOUT: respuestas fuera de secuencia.')

    def _request(self, op, **data):
        if not self.process or self.closed:
            raise ValueError('PID_PLANT_SESSION: sesión no disponible.')
        if op != 'close' and time.monotonic()-self.started_at > self.deadline_s:
            raise self._error('PID_PLANT_TIMEOUT: plazo del ensayo agotado.')
        self.sequence += 1
        try:
            self.process.stdin.write(json.dumps(dict(id=self.sequence, op=op, **data), allow_nan=False)+'\n')
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            raise self._error('PID_PLANT_EOF: no se puede enviar la operación.')
        response = self._receive(self.sequence)
        if response.get('status') not in {'PID_WORD_PROBE_PASSED', 'PID_PLANT_SAMPLE', 'PID_PLANT_CLOSED', 'PID_WORD_PROBE_NOT_REQUIRED'}:
            raise self._error(response.get('status', 'PID_PLANT_PROTOCOL')+': '+str(response.get('errors', [])))
        return response

    def probe_input_word(self) -> dict:
        response = self._request('probe_input_word')
        if self.input_binding['representation'] == 'DB_ENGINEERING':
            self.probe_passed = response.get('status') == 'PID_WORD_PROBE_NOT_REQUIRED'
        else:
            samples = response.get('samples', [])
            self.probe_passed = (response.get('byte_order') in {'big', 'little'} and response.get('restored') is True
                and [s.get('requested') for s in samples] == [0, 13824, 27648]
                and all(s.get('address') == s['requested'] == s.get('symbol') for s in samples))
        self.report['word_probe'] = response
        self._save()
        if not self.probe_passed:
            raise self._error('PID_WORD_PROBE_FAILED: lectura por dirección/símbolo o restauración incorrecta.')
        return response

    def exchange(self, measurement: float, valid: bool) -> dict:
        if not self.probe_passed:
            raise ValueError('PID_WORD_PROBE_REQUIRED: compruebe primero el transporte de la medición.')
        if self.failed:
            raise ValueError('PID_PLANT_SESSION: la sesión falló; solo admite cierre.')
        if type(measurement) not in (int, float) or not math.isfinite(measurement) or type(valid) is not bool:
            raise ValueError('PID_PLANT_VALUE: requiere medición finita y calidad BOOL.')
        data = dict(measurement=float(measurement), valid=valid)
        if self.input_binding['representation'] == 'HARDWARE_RAW':
            b = self.input_binding
            config = b['analog_config']
            if valid:
                raw = round((measurement-b['engineering_min'])/(b['engineering_max']-b['engineering_min'])*
                            (config['raw_max']-config['raw_min'])+config['raw_min'])
            else:
                candidates = [config['raw_min']-1, config['raw_max']+1]
                raw = next((n for n in candidates if -32768 <= n <= 32767), None)
                if raw is None:
                    raise ValueError('PID_SENSOR_INJECTION_UNSUPPORTED: no existe raw de fallo INT16 representable.')
            if not -32768 <= raw <= 32767:
                raise ValueError('PID_PLANT_VALUE: medición fuera de la representación INT16.')
            data['measurement_raw'] = raw
        return self._request('exchange', **data)

    def close(self) -> dict:
        if self.closed:
            return self.report
        try:
            response = self._request('close') if self.process else {}
            self.report.update(response)
            if response.get('cleanup_verified') is not True:
                self.report['errors'].append('PID_PLANT_CLEANUP_FAILED: parada/restauración no verificadas.')
        except Exception as error:
            self.report['errors'].append(str(error))
            self.report.update(cleanup_verified=False, inputs_restored=False, stop_verified=False)
        finally:
            if self.process:
                try:
                    self.process.wait(timeout=RESPONSE_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    self.process.terminate()  # Only this session's helper, never TIA or PLCSIM.
                    self.process.wait(timeout=RESPONSE_TIMEOUT_S)
                    self.report['errors'].append('PID_PLANT_CLEANUP_FAILED: el proceso no confirmó su salida.')
                    self.report.update(cleanup_verified=False, inputs_restored=False)
                for stream in (self.process.stdin, self.process.stdout):
                    try:
                        stream.close()
                    except OSError as error:
                        self.report['errors'].append('PID_PLANT_PIPE_CLOSE: '+str(error))
            if self.stderr:
                self.stderr.close()
            self.closed = True
            self.report['status'] = 'CLOSED' if not self.report['errors'] and self.report.get('cleanup_verified') else 'FAILED'
            self._save()
        return self.report
