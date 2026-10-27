"""Cancelable external tank provider with per-attempt evidence and no automatic start/tuning."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import queue
import threading
import time
import uuid
from pathlib import Path

from pid_plant_io import PidPlantIOSession
from pid_tank_model import TankModel


class PlantTestJob:
    """One cancellable provider per owner, with results consumed on the UI thread."""
    def __init__(self, provider=None):
        self.provider=provider or run_tank_test
        self.thread=None
        self.cancel_event=threading.Event()
        self.results=queue.Queue()
        self._result_pending=False

    @property
    def active(self):
        return self._result_pending

    def start(self, package_dir, target, profile, report_dir):
        if self.active:return False
        self._result_pending=True
        self.cancel_event=threading.Event()
        args=(Path(package_dir),copy.deepcopy(target),copy.deepcopy(profile),self.cancel_event,Path(report_dir))
        def work():
            try:report=self.provider(*args)
            except Exception as error:
                report={'status':'FAILED','errors':[str(error)],'cleanup':{'cleanup_verified':False}}
            self.results.put(report)
        self.thread=threading.Thread(target=work,daemon=True)
        self.thread.start()
        return True

    def cancel(self):
        self.cancel_event.set()

    def poll(self):
        try:
            result=self.results.get_nowait()
            self._result_pending=False
            return result
        except queue.Empty:return None


def fault_injection_status(binding: dict) -> dict:
    if binding['representation']=='DB_ENGINEERING' and binding.get('validity_member'):
        return {'status':'AVAILABLE','quality_member':binding['validity_member']}
    config=binding.get('analog_config',{})
    for raw in (config.get('raw_min',-32768)-1,config.get('raw_max',32767)+1):
        if -32768<=raw<=32767:
            return {'status':'AVAILABLE','raw':raw}
    return {'status':'UNSUPPORTED','reason':'No hay raw de fallo INT16 representable ni calidad declarada.'}


class PlantTestControl:
    """Explicit test stimuli go through the mapped measurement, never private controller state."""
    def __init__(self):
        self.lock=threading.Lock()
        self.fault=False
        self.override=None
        self.phase='model_provider'

    def set_sensor_fault(self, enabled: bool):
        if type(enabled) is not bool:raise ValueError('PID_TEST_CONTROL: requiere BOOL.')
        with self.lock:self.fault=enabled

    def set_measurement_override(self, value: float | None):
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value)):
            raise ValueError('PID_TEST_CONTROL: medición finita requerida.')
        with self.lock:self.override=value

    def set_phase(self, phase: str):
        with self.lock:self.phase=str(phase)

    def read(self):
        with self.lock:return self.fault,self.override,self.phase


def _save(path: Path, data: dict):
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    temporary.replace(path)


def run_tank_test(package_dir: Path, target: dict, profile: dict, cancel: threading.Event,
                  report_dir: Path, *, control: PlantTestControl | None=None) -> dict:
    package_dir,report_dir=Path(package_dir),Path(report_dir)
    evidence=report_dir/('run_'+uuid.uuid4().hex[:12])
    evidence.mkdir(parents=True)
    profile=copy.deepcopy(profile)
    report={'status':'PREPARING','evidence':str(evidence),'errors':[],'native_execution_verified':False,
            'sample_count':0,'cleanup':{'cleanup_verified':False},'artifact_hashes':{}}
    session=None
    control=control or PlantTestControl()
    try:
        manifest=json.loads((package_dir/'pid_infrastructure.json').read_text(encoding='utf-8'))
        loop=manifest['loops'][0]
        profile['direction']=loop['direction']
        report['model_profile_sha256']=hashlib.sha256(json.dumps(profile,sort_keys=True,allow_nan=False).encode()).hexdigest()
        report['model_profile']=profile
        for filename in ('siemens_source.scl','pid_cyclic_ob.xml','pid_infrastructure.json','pid_process_bindings.json'):
            report['artifact_hashes'][filename]=hashlib.sha256((package_dir/filename).read_bytes()).hexdigest()
        _save(evidence/'model_profile.json',profile)
        _save(evidence/'bindings.json',dict(input_binding=loop['input_binding'],output_binding=loop['output_binding']))
        _save(report_dir/'latest_run.json',{'evidence':str(evidence),'status':'PREPARING'})
        _save(evidence/'summary.json',report)
        if cancel.is_set():
            report.update(status='CANCELLED',cleanup={'cleanup_verified':True,'not_started':True})
            return report
        period,duration=profile.get('period_s'),profile.get('duration_s')
        if type(period) not in (int,float) or not math.isfinite(period) or period!=.1:
            raise ValueError('PID_MODEL_PERIOD: el proveedor verificado utiliza 100 ms.')
        if type(duration) not in (int,float) or not math.isfinite(duration) or not .1<=duration<=3500:
            raise ValueError('PID_MODEL_DURATION: plazo finito entre 0.1 y 3500 s requerido.')
        model=TankModel(profile,loop['input_binding'],loop['output_binding'])
        session=PidPlantIOSession(package_dir,target,evidence/'io',max(5.0,duration+5))
        started=session.start()
        session.probe_input_word()
        origin=previous=time.monotonic()
        next_tick=origin
        command=0.0
        native=started.get('native_execution_verified') is True
        report.update(status='RUNNING',word_probe=session.report.get('word_probe'))
        last_flush=origin
        with (evidence/'trace.jsonl').open('w',encoding='utf-8') as trace:
            while not cancel.is_set() and time.monotonic()-origin<duration:
                now=time.monotonic()
                dt=now-previous if report['sample_count'] else 0.0
                provided=model.step(command,dt)
                fault,override,phase=control.read()
                if fault and fault_injection_status(loop['input_binding'])['status']=='UNSUPPORTED':
                    raise ValueError('PID_SENSOR_INJECTION_UNSUPPORTED: '+fault_injection_status(loop['input_binding'])['reason'])
                measured=provided if override is None else override
                response=session.exchange(measured,not fault)
                command=response['command_percent']
                native=native and response.get('native_execution_verified') is True
                diag=response.get('diagnostics',{})
                row={'t_s':now-origin,'monotonic_s':now,'dt_s':dt,'jitter_s':now-next_tick,
                     'missed_samples':max(0,int((now-next_tick)/period)), 'phase':phase,
                     'provided_level':provided,'measurement_requested':measured,'measurement_override':override,
                     'measurement_raw':response.get('measurement_raw'),'quality':response.get('quality',not fault),
                     'command_raw':response.get('command_raw'),'command_percent':command,
                     'pv':diag.get('PV'),'cv':diag.get('CV'),'sp':diag.get('SP'),
                     'running':diag.get('Running'),'fault':diag.get('Fault'),'sensor_valid':diag.get('SensorValid'),
                     'controller_error':diag.get('ControllerError'),'state':diag.get('ControllerState'),
                     'error_bits':diag.get('ErrorBits'),'fault_code':diag.get('FaultCode'),
                     'parameters_confirmed':diag.get('ParametersConfirmed'),'kp':diag.get('Kp'),'ti':diag.get('Ti'),'td':diag.get('Td')}
                trace.write(json.dumps(row,allow_nan=False)+'\n');trace.flush()
                report.update(sample_count=report['sample_count']+1,last_sample=row,native_execution_verified=native)
                if now-last_flush>=.5:
                    _save(evidence/'summary.json',report);last_flush=now
                previous=now
                next_tick+=period
                if time.monotonic()>next_tick+period:
                    next_tick+=int((time.monotonic()-next_tick)/period)*period
                if cancel.wait(max(0,next_tick-time.monotonic())):break
        report['status']='CANCELLED' if cancel.is_set() else 'FINISHED'
        # Provider completion proves transport/dynamics execution, never control acceptance.
        return report
    except Exception as error:
        report.update(status='FAILED')
        report['errors'].append(str(error))
        return report
    finally:
        if session:
            report['cleanup']=session.close()
            if not report['cleanup'].get('cleanup_verified'):
                report['status']='FAILED'
                report['errors'].append('PID_MODEL_CLEANUP_FAILED: parada/restauración no verificadas.')
        _save(evidence/'summary.json',report)
        _save(report_dir/'latest_run.json',{'evidence':str(evidence),'status':report['status']})
