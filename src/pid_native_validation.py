"""Explicit online acceptance protocol for v2 controllers and an external tank provider."""
from __future__ import annotations

import json
import math
import threading
import time
import uuid
from pathlib import Path

from pid_acceptance import evaluate_pid_samples, require_simulation_target
from pid_commissioning import PidCommissioningSession
from pid_package import native_download_project, validate_pid_manifest, validate_experimental_pid_project
from pid_plant_test import PlantTestControl, fault_injection_status, run_tank_test, _save
from plcsim_runtime import get_plcsim_runtime_status
from plcsim_runtime_io import RuntimeIOSession, load_program_signals
from tia_openness import load_tia_config, resolve_download_target, download_program_to_plc

STAGES=('preflight','runtime','manual','tuning','convergence','safety','cleanup')


def overfill_stimulus(limit,high):
    if limit is None:return None
    if not math.isfinite(limit) or limit>high:
        raise ValueError('PID_OVERFILL: umbral declarado fuera del rango ensayable.')
    return (limit+high)/2


def summarize_required_checks(checks: list[dict]) -> dict:
    mandatory={'stop','sensor_fault','held_start_after_reset','setpoint_limit'}
    names=[item.get('case') for item in checks]
    applicable=[c for c in checks if c.get('required',True)]
    not_applicable=[c['case'] for c in checks if c.get('required') is False and c.get('status')=='NOT_APPLICABLE']
    passed=(mandatory.issubset(names) and len(names)==len(set(names)) and bool(applicable)
            and all(c.get('passed') is True for c in applicable)
            and all(c.get('passed') is True or c.get('case') in not_applicable for c in checks))
    return {'status':'PASSED' if passed else 'FAILED','checks':checks,
            'required_count':len(applicable),'not_applicable':not_applicable}


def enter_verified_automatic(session, initial: dict) -> None:
    if initial.get('ParametersConfirmed') is not True:
        raise ValueError('PID_PARAMETERS_UNVERIFIED: ajuste no confirmado.')
    session.write('CmdManual',False)


def finalize_native_verdict(stages: dict, provider: dict, *, execution_failed: bool=False) -> dict:
    native=provider.get('native_execution_verified') is True
    passed=all(stages.get(name,{}).get('status')=='PASSED' for name in STAGES)
    cleaned=provider.get('cleanup',{}).get('cleanup_verified') is True
    finished=provider.get('status') in {'CANCELLED','FINISHED'} and not provider.get('errors')
    return {'status':'PASSED' if passed and native and cleaned and finished and not execution_failed else 'FAILED',
            'native_execution_verified':native,'cleanup_verified':cleaned}


class _TraceReader:
    def __init__(self, root):
        self.root=root
        self.file=None
        self.evidence=None
        self.rows=[]

    def read(self):
        if self.file is None:
            pointer=self.root/'latest_run.json'
            if not pointer.exists():return []
            self.evidence=Path(json.loads(pointer.read_text(encoding='utf-8'))['evidence'])
            if not self.evidence.resolve().is_relative_to(self.root.resolve()):raise ValueError('PID_TRACE_PATH')
            path=self.evidence/'trace.jsonl'
            if not path.exists():return []
            self.file=path.open(encoding='utf-8')
        result=[]
        while True:
            position=self.file.tell();line=self.file.readline()
            if not line:break
            if not line.endswith('\n'):
                self.file.seek(position);break
            result.append(json.loads(line))
        self.rows.extend(result)
        return result

    def close(self):
        if self.file:self.file.close()


def run_map_pid_validation(project_root: Path, package_dir: Path, *, download: bool=True,
                           cancel: threading.Event | None=None, profile: dict | None=None,
                           protocol: dict | None=None, report_dir: Path | None=None,
                           execution_context: dict | None=None) -> dict:
    root,package=Path(project_root).resolve(),Path(package_dir).resolve()
    evidence_root=Path(report_dir) if report_dir is not None else root/'runtime/pid_native_validation_v2'
    evidence=evidence_root/('run_'+uuid.uuid4().hex[:12])
    evidence.mkdir(parents=True)
    stages={name:{'status':'PENDING'} for name in STAGES}
    outcome={'status':'RUNNING','evidence':str(evidence),'package_dir':str(package),'native_execution_verified':False}
    stop_provider=threading.Event()
    external_cancel=cancel or threading.Event()
    provider_result={}
    worker=None;session=None;io=None
    control=PlantTestControl()
    reader=_TraceReader(evidence/'plant')

    def flush():
        _save(evidence/'stages.json',stages)
        _save(evidence/'summary.json',outcome)
        _save(evidence_root/'latest_run.json',{'evidence':str(evidence),'status':outcome['status']})

    def collect():
        rows=reader.read()
        if protocol and protocol.get('tuning_policy')=='REUSE_VERIFIED' and any(row.get('state') in (1,2) for row in rows):
            raise ValueError('PID_UNEXPECTED_TUNING: no se autorizó otra sintonización.')
        if external_cancel.is_set():raise ValueError('PID_TEST_CANCELLED')
        if worker and not worker.is_alive() and provider_result.get('status')=='FAILED':
            raise ValueError('PID_MODEL_FAILED: '+str(provider_result.get('errors')))
        return rows

    def wait_for(predicate,seconds,description):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            for row in collect():
                if predicate(row):return row
            external_cancel.wait(.05)
        raise ValueError('PID_TEST_TIMEOUT: '+description)

    def read_values():
        return session.read()

    def assert_safe(row,safe):
        return (row.get('running') is False and row.get('cv') is not None and abs(row['cv']-safe)<.05
                and abs(row['command_percent']-safe)<.05)

    flush()
    try:
        target=resolve_download_target(load_tia_config(root),'experiment' if execution_context is not None else 'normal')
        require_simulation_target(target)
        manifest=json.loads((package/'pid_infrastructure.json').read_text(encoding='utf-8'))
        loop=validate_pid_manifest(manifest)
        if manifest['schema_version']!=2:raise ValueError('PID_ACCEPTANCE_PROTOCOL: requiere paquete v2.')
        if profile is None:
            profile=json.loads((root/'config/pid_tank_test_profile.json').read_text(encoding='utf-8'))
        if protocol is not None:
            from trial_experiments.native_pid_protocol import validate_native_protocol
            protocol=validate_native_protocol(protocol,loop,profile)
        if execution_context is not None:
            if download:raise ValueError('PID_EXPERIMENT_CONTEXT: la descarga pertenece al handshake experimental.')
            validate_experimental_pid_project(package,root,execution_context)
        else:
            native_download_project(package,root,'PLCSIM_ADVANCED')
        verification=json.loads((package/'verification.json').read_text(encoding='utf-8'))
        if not verification.get('is_valid'):raise ValueError('PID_GENERATION: paquete inválido.')
        stages['preflight']={'status':'PASSED','manifest':manifest,'verification':verification}
        runtime_options={'target':target} if execution_context is None and target.get('instance_id') is not None else {}
        runtime=get_plcsim_runtime_status(root,**runtime_options)
        if not runtime.get('connected'):raise ValueError('PID_RUNTIME: instancia PLCSIM no disponible.')
        if download:
            from plc_targets import load_normal_target
            result=download_program_to_plc(package,root,expected_target=load_normal_target(root)) if runtime_options else download_program_to_plc(package,root)
            _save(evidence/'download.json',result)
            if not result.get('download_success'):raise ValueError('PID_DOWNLOAD: '+str(result.get('errors')))
        runtime=get_plcsim_runtime_status(root,**runtime_options)
        if not runtime.get('connected') or runtime.get('cpu_state')!='RUN':raise ValueError('PID_RUNTIME: CPU no confirmada en RUN.')
        bindings=json.loads((package/'pid_process_bindings.json').read_text(encoding='utf-8'))
        program=load_program_signals(variables_path=package/'variables.json')
        program['native_pid_identity']={'db':bindings['instance_db'],'build_signature':bindings['build_signature']}
        io_options={}
        if runtime_options:
            from plcsim_runtime import load_runtime_config
            selected_config=load_runtime_config(load_tia_config(root))
            selected_config.update({key:target[key] for key in ('instance_name','instance_id') if key in target})
            io_options['runtime_config']=selected_config
        io=RuntimeIOSession(program,'PLCSIM_ADVANCED',runtime,root,kind='native_pid_map_acceptance',**io_options)
        context={'target_type':'PLCSIM_ADVANCED','connected':True,'cpu_state':'RUN',
                 'program_verified':False,'tuning_authorized':True}
        session=PidCommissioningSession(bindings,io,context)
        initial=read_values()  # Actual 16-word identity before starting any provider.
        if protocol and protocol['tuning_policy']=='REUSE_VERIFIED' and initial.get('ParametersConfirmed') is not True:
            raise ValueError('PID_PARAMETERS_UNVERIFIED: no hay ajuste confirmado para reutilizar.')
        stages['runtime']={'status':'PASSED','runtime':runtime,'initial':initial,'program_identity_verified':True}
        model_target={'target_type':'PLCSIM_ADVANCED','instance_name':runtime['instance_name'],**({'instance_id':runtime['instance_id']} if runtime.get('instance_id') is not None else {})}
        if execution_context is not None:model_target['native_execution_context']=execution_context
        def provider():
            provider_result.update(run_tank_test(package,model_target,profile,stop_provider,evidence/'plant',control=control))
        worker=threading.Thread(target=provider,daemon=True);worker.start()
        wait_for(lambda r:r.get('sensor_valid') is True,30,'medición válida del proveedor')
        resources=loop.get('resources',{})
        mapped_inputs=[n for key,n in resources.items() if key in {'start','stop','reset','emergency','auto','manual'}]
        if mapped_inputs:
            observed=io.read_signals(mapped_inputs)
            _save(evidence/'initial_digital_inputs.json',observed)
            if observed.get('status')!='SUCCESS' or any(item['value'] is not False for item in observed['values']):
                raise ValueError('PID_TEST_PRECONDITIONS: libere los mandos digitales en PLCSIM antes del protocolo automático.')
        low,high=(loop['input_binding'][k] for k in ('engineering_min','engineering_max'));span=high-low
        safe=loop['output_binding'].get('analog_config',loop['output_binding'])['fault_value']
        control.set_phase('manual')
        session.write('CmdStop',True);session.write('CmdStart',False)
        session.write('ManualValue',40.0);session.write('CmdManual',True)
        session.write('CmdReset',True);session.write('CmdStart',True)
        manual=wait_for(lambda r:r.get('running') is True and not r.get('fault') and abs(r['command_percent']-40)<.05,10,'mando manual real del mapa')
        stages['manual']={'status':'PASSED','sample':manual};flush()
        if protocol and protocol['tuning_policy']=='REUSE_VERIFIED':
            enter_verified_automatic(session,initial)
            stages['tuning']={'status':'PASSED','policy':'REUSE_VERIFIED','new_tuning_requested':False,'initial':initial}
        else:
            control.set_phase('pretuning')
            session.write('SP',low+.5*span)
            _save(evidence/'pretuning_preconditions.json',read_values())
            session.write('CmdPretune',True)
            entered=False;tuning_end=time.monotonic()+300
            while time.monotonic()<tuning_end:
                for row in collect():
                    if row.get('phase')!='pretuning':continue
                    entered=entered or row.get('state')==1
                    if row.get('fault') or row.get('controller_error'):
                        stages['tuning']={'status':'FAILED','sample':row,'entered_pretuning':entered}
                        raise ValueError('PID_NATIVE_TUNING_FAILED: '+str(row))
                    if entered and row.get('state')==3 and row.get('parameters_confirmed') is True:
                        stages['tuning']={'status':'PASSED','observed_state_transition':[1,3],'sample':row};break
                if stages['tuning']['status']=='PASSED':break
                external_cancel.wait(.05)
            if stages['tuning']['status']!='PASSED':raise ValueError('PID_NATIVE_TUNING_TIMEOUT: Siemens no terminó en 300 s.')
        flush();setpoints=[]
        for percentage in (50,40,60):
            sp=low+span*percentage/100
            phase='sp_'+str(percentage);control.set_phase(phase)
            origin=time.monotonic();session.write('SP',sp)
            print('PID nativo: consigna '+str(sp)+' '+loop['unit'],flush=True)
            samples=[];verdict={'status':'PENDING'}
            while verdict['status']=='PENDING' and time.monotonic()-origin<=301:
                rows=collect()
                samples.extend({**row,'t_s':row['monotonic_s']-origin} for row in rows if row['monotonic_s']>=origin)
                verdict=evaluate_pid_samples(samples,sp,tolerance=.02*span,hold_seconds=10,deadline_seconds=300)
                if verdict['status']=='PENDING':external_cancel.wait(.1)
            if verdict['status']!='PASSED':
                stages['convergence']={'status':'FAILED','setpoints':setpoints,'last':verdict}
                raise ValueError('PID_CONVERGENCE: no mantuvo ±2 puntos durante 10 s antes de 300 s.')
            verdict['native_execution_verified']=True;setpoints.append(verdict)
            stages['convergence']={'status':'PASSED' if len(setpoints)==3 else 'PENDING','setpoints':setpoints};flush()
        checks=[]
        def record(name,passed,**details):
            checks.append(dict(case=name,passed=bool(passed),**details))
            stages['safety']={'status':'PENDING','checks':checks};flush()
        control.set_phase('stop');session.write('CmdStop',True)
        stopped=wait_for(lambda r:assert_safe(r,safe),5,'Stop prioritario')
        record('stop',True,sample=stopped)
        # Hold Start across sensor fault and Reset: recovery must not create a new edge.
        control.set_phase('sensor_fault');session.write('CmdStart',True,pulse=False)
        injection=fault_injection_status(loop['input_binding'])
        if injection['status']!='AVAILABLE':
            record('sensor_fault',False,status='UNSUPPORTED',reason=injection['reason'])
            raise ValueError('PID_SENSOR_INJECTION_UNSUPPORTED')
        control.set_sensor_fault(True)
        failed=wait_for(lambda r:r.get('fault_code')==2 and assert_safe(r,safe),5,'fallo de sensor')
        record('sensor_fault',True,sample=failed,injection=injection)
        control.set_sensor_fault(False);wait_for(lambda r:r.get('sensor_valid') is True,5,'recuperación del sensor')
        control.set_phase('held_start_reset');session.write('CmdReset',True)
        rows=[];until=time.monotonic()+.6
        while time.monotonic()<until:
            rows.extend(collect());external_cancel.wait(.05)
        record('held_start_after_reset',bool(rows) and all(assert_safe(r,safe) for r in rows))
        session.write('CmdStart',False);session.write('CmdStart',True)
        emergency=resources.get('emergency')
        if not emergency:
            record('emergency',False,status='NOT_APPLICABLE',required=False,reason='El comando no declara emergencia.')
        else:
            control.set_phase('emergency');read_values()
            changed=io.write_input(emergency,True)
            if changed.get('status')!='SUCCESS':raise ValueError('PID_EMERGENCY_INPUT: '+str(changed))
            row=wait_for(lambda r:r.get('fault_code')==1 and assert_safe(r,safe),5,'emergencia')
            record('emergency',True,sample=row)
            read_values();restored=io.write_input(emergency,False)
            if restored.get('status')!='SUCCESS':raise ValueError('PID_EMERGENCY_RESTORE: '+str(restored))
            session.write('CmdReset',True);session.write('CmdStart',True)
        control.set_phase('setpoint_limit')
        try:
            session.write('SP',high+.01*span)
        except ValueError as error:
            record('setpoint_limit','PID_WRITE_RANGE' in str(error),reason=str(error),scope='application_guard')
        else:record('setpoint_limit',False)
        limit=loop.get('overfill_limit')
        stimulus=overfill_stimulus(limit,high)
        if stimulus is None:
            record('overfill',False,status='NOT_APPLICABLE',required=False,reason='No hay umbral de sobrellenado declarado.')
        else:
            control.set_phase('overfill');control.set_measurement_override(stimulus)
            row=wait_for(lambda r:r.get('fault_code')==5 and assert_safe(r,safe),5,'sobrellenado')
            record('overfill',True,sample=row)
            control.set_measurement_override(None)
        stages['safety']=summarize_required_checks(checks)
        _save(evidence/'final_native_values.json',read_values())
    except Exception as error:
        outcome.update(status='FAILED',reason=str(error))
        _save(evidence/'execution_error.json',{'error':str(error),'type':type(error).__name__})
    finally:
        # Any stale-program failure leaves digital inputs untouched; the provider guards its own cleanup too.
        digital_cleanup={'status':'SUCCESS','restored':[]}
        if io and io.touched_inputs:
            try:
                read_values()
                digital_cleanup=io.restore_inputs()
            except Exception as error:
                digital_cleanup={'status':'FAILED','error':str(error)}
        stop_provider.set()
        if worker:worker.join(timeout=20)
        if worker and worker.is_alive():
            provider_result.update(status='FAILED',errors=['PID_PROVIDER_CLOSE_TIMEOUT'],cleanup={'cleanup_verified':False})
        reader.close()
        stages['cleanup']={'status':'PASSED' if provider_result.get('cleanup',{}).get('cleanup_verified') and digital_cleanup['status']=='SUCCESS' else 'FAILED',
                           'digital_inputs':digital_cleanup,'provider':provider_result.get('cleanup',{})}
        if external_cancel.is_set():
            outcome.update(status='FAILED',reason='PID_TEST_CANCELLED')
        outcome.update(finalize_native_verdict(stages,provider_result,execution_failed=outcome['status']=='FAILED'))
        outcome['stages']={key:value['status'] for key,value in stages.items()}
        outcome['provider_evidence']=provider_result.get('evidence')
        _save(evidence/'provider_result.json',provider_result)
        flush()
    return outcome
