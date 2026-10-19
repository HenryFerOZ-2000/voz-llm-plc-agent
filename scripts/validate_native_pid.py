"""Record a genuine Siemens/PLCSIM run. No offline or Python PID replacement."""
from __future__ import annotations
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pid_acceptance import evaluate_pid_samples,require_simulation_target
from pid_commissioning import PidCommissioningSession
from pid_package import native_download_project,validate_pid_manifest
from plcsim_runtime import get_plcsim_runtime_status
from plcsim_runtime_io import RuntimeIOSession,load_program_signals
from tia_openness import load_tia_config,resolve_download_target,download_program_to_plc


def recover_for_pretuning(session,sample):
    # End the deliberate overfill test before requesting native identification.
    # This protocol is restricted to the 0..100% tank, with SP=60 at this point.
    session.write('CmdStop',True);session.write('ManualValue',40);session.write('CmdManual',True)
    for _ in range(16):
        values=session.read()
        if values['PV']<20:break
        sample(10000,'pretuning_recovery')
    else:raise ValueError('PID_TUNING_PRECONDITIONS: el tanque no recupero un nivel menor a 20 %.')
    session.write('CmdReset',True)
    values=session.read()
    if values['Fault'] or not values['SensorValid']:
        raise ValueError('PID_TUNING_PRECONDITIONS: '+str(values))
    session.write('CmdStart',True)
    values=session.read()
    if abs(values['SP']-values['PV'])<=max(30,.5*abs(values['SP'])):
        raise ValueError('PID_TUNING_PRECONDITIONS: distancia insuficiente entre PV y SP.')
    return values


def run_validation(project_root,package_dir,mode=None):
    path=Path(package_dir)/'pid_infrastructure.json'
    try:manifest=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except ValueError:manifest={}
    if manifest.get('schema_version')==2:
        from pid_native_validation import run_map_pid_validation
        return run_map_pid_validation(project_root,package_dir)
    return run_validation_v1(project_root,package_dir,mode)


def run_validation_v1(project_root,package_dir,mode):
    root,package=Path(project_root).resolve(),Path(package_dir).resolve()
    evidence_root=package/'native_pid_validation';evidence_root.mkdir(exist_ok=True)
    evidence=evidence_root/('run_'+uuid.uuid4().hex[:12]);evidence.mkdir()
    latest=evidence_root/'latest_run.json'
    latest.write_text(json.dumps({'status':'RUNNING','evidence':str(evidence)}),encoding='utf-8')
    def save(name,value):
        (evidence/(name+'.json')).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    stages={name:{'status':'PENDING','reason':'No ejecutado.'} for name in ('generation','structure','compilation','runtime','convergence','safety','tuning')}
    def flush():
        for name,value in stages.items():save(name,value)
    flush()
    session=None;io=None;outcome={}
    try:
        if mode!='SIMULATION':raise ValueError('PID_ACCEPTANCE_TARGET: modo SIMULATION requerido.')
        target=resolve_download_target(load_tia_config(root));require_simulation_target(target)
        manifest=json.loads((package/'pid_infrastructure.json').read_text(encoding='utf-8'));loop=validate_pid_manifest(manifest)
        if loop['mode']!='SIMULATION':raise ValueError('PID_ACCEPTANCE_TARGET: el paquete no contiene un modelo simulado.')
        if loop['unit']!='%' or loop['input_config']['engineering_min']!=0 or loop['input_config']['engineering_max']!=100:
            raise ValueError('PID_ACCEPTANCE_PROTOCOL: este protocolo requiere nivel de 0 a 100 %.')
        verification=json.loads((package/'verification.json').read_text(encoding='utf-8'))
        stages['generation']={'status':'PASSED' if verification.get('is_valid') else 'FAILED','verification':verification}
        if not verification.get('is_valid'):raise ValueError('PID_GENERATION: paquete no valido.')
        stages['structure']={'status':'PASSED','manifest':manifest}
        compiled_project=native_download_project(package,root,target['target_type'])
        stages['compilation']={'status':'PASSED','compiled_project':compiled_project,
                              'report':str(package/'tia_compile_report.json')}
        runtime=get_plcsim_runtime_status(root);stages['runtime']={'status':'PENDING','report':runtime};flush()
        if not runtime.get('connected'):
            outcome.update(status='PENDING',reason='Instancia PLCSIM no disponible.',evidence=str(evidence));return outcome
        download=download_program_to_plc(package,root)
        save('download',download)
        if not download.get('download_success'):raise ValueError('PID_DOWNLOAD: fallo la descarga a PLCSIM.')
        runtime=get_plcsim_runtime_status(root)
        if not runtime.get('connected') or runtime.get('cpu_state')!='RUN':raise ValueError('PID_RUNTIME: CPU no confirmada en RUN.')
        bindings=json.loads((package/'pid_process_bindings.json').read_text(encoding='utf-8'))
        program=load_program_signals(variables_path=package/'variables.json')
        io=RuntimeIOSession(program,target['target_type'],runtime,root,kind='native_pid_acceptance')
        context={'mode':'SIMULATION','target_type':target['target_type'],'connected':True,'cpu_state':'RUN',
                 'program_verified':True,'tuning_authorized':True}
        session=PidCommissioningSession(bindings,io,context)
        values=session.read();stages['runtime']={'status':'PASSED','report':runtime,'program_identity_verified':True,'initial':values};flush()
        origin=time.perf_counter();trace=[];sequence=0
        def sample(duration_ms=1000,phase='state'):
            nonlocal sequence
            session.read();io._guard_write();sequence+=1;started=time.perf_counter()-origin
            signals=[b for n,b in bindings['bindings'].items() if n in {'PV','CV','SP','Fault','FaultCode','SensorValid','ControllerState','ControllerError','Running','ErrorBits','Kp','Ti','Td'}]
            report=io._bridge('io_sequence',{'target_type':target['target_type'],'process_variables':True,
                'purpose':'NATIVE_PID_COMMISSIONING','steps':[{'op':'sample','id':phase,'duration_ms':duration_ms,'period_ms':100,'signals':signals}]})
            save(f'bridge_{sequence:03d}_{phase}',report)
            if report.get('status')!='PLCSIM_IO_PASSED':raise ValueError('PID_SAMPLE: '+'; '.join(report.get('errors',[])))
            rows=[]
            for item in report.get('samples',[]):
                v={k.rsplit('.',1)[-1]:value for k,value in item['values'].items()}
                row={'t_s':started+item['t_ms']/1000,'phase':phase,'pv':v.get('PV'),'cv':v.get('CV'),'sp':v.get('SP'),
                    'fault':v.get('Fault'),'sensor_valid':v.get('SensorValid'),'controller_error':v.get('ControllerError'),
                    'state':v.get('ControllerState'),'error_bits':v.get('ErrorBits'),'fault_code':v.get('FaultCode'),'running':v.get('Running'),
                    'kp':v.get('Kp'),'ti':v.get('Ti'),'td':v.get('Td')}
                rows.append(row);trace.append(row)
            save('trace',trace)
            return rows
        session.write('CmdStart',True)
        results=[]
        for sp in (50.0,40.0,60.0):
            session.write('SP',sp);phase_start=time.perf_counter()-origin;phase_rows=[]
            print(f'Consigna {sp}: ejecutando PID nativo...',flush=True)
            verdict={'status':'PENDING'}
            while verdict['status']=='PENDING':
                rows=sample(20000,'sp_'+str(int(sp)))
                phase_rows +=[{**row,'t_s':row['t_s']-phase_start} for row in rows]
                verdict=evaluate_pid_samples(phase_rows,sp)
                print(f'Consigna {sp}: {verdict["status"]}, PV={rows[-1]["pv"] if rows else None}',flush=True)
            verdict['native_execution_verified']=True;results.append(verdict)
            stages['convergence']={'status':'FAILED' if any(r['status']=='FAILED' for r in results) else 'PASSED' if len(results)==3 else 'PENDING',
                                   'setpoints':results};flush()
            if verdict['status']!='PASSED':raise ValueError('PID_CONVERGENCE: tiempo maximo agotado.')
        checks=[]
        session.write('CmdStop',True);v=session.read()
        checks.append({'case':'stop','passed':not v['Running'] and v['CV']==0})
        session.write('CmdStart',True,pulse=False)
        session.write('SimSensorFault',True);v=session.read()
        checks.append({'case':'sensor_fault','passed':v['Fault'] and v['CV']==0 and not v['Running']})
        session.write('SimSensorFault',False);session.write('CmdReset',True);sample(1000,'held_start')
        v=session.read();checks.append({'case':'held_start_after_reset','passed':not v['Running'] and v['CV']==0})
        session.write('CmdStart',False);session.write('CmdStart',True)
        emergency=loop['resources'].get('emergency')
        if emergency:
            io.write_input(emergency,True);v=session.read();checks.append({'case':'emergency','passed':v['Fault'] and v['CV']==0})
            io.write_input(emergency,False);session.write('CmdReset',True);session.write('CmdStart',True)
        try:session.write('SP',101);checks.append({'case':'setpoint_limit','passed':False})
        except ValueError:checks.append({'case':'setpoint_limit','passed':True})
        if loop['simulation'].get('overfill_limit') is not None:
            session.write('ManualValue',100);session.write('CmdManual',True)
            for _ in range(12):
                sample(10000,'overfill');v=session.read()
                if v['Fault']:break
            checks.append({'case':'overfill','passed':v['Fault'] and v['CV']==0})
            session.write('CmdManual',False)
        stages['safety']={'status':'PASSED' if all(c['passed'] for c in checks) else 'FAILED','checks':checks};flush()
        if stages['safety']['status']!='PASSED':raise ValueError('PID_SAFETY: una comprobacion no se cumplio.')
        # Request tuning explicitly and record Siemens state/errors; success is never inferred from compilation.
        save('pretuning_preconditions',recover_for_pretuning(session,sample))
        session.write('CmdPretune',True);entered=False
        tuning={'status':'PENDING','request':'PRETUNING','reason':'Esperando resultado Siemens.'}
        for _ in range(12):
            rows=sample(10000,'pretuning');entered=entered or any(r['state']==1 for r in rows)
            v=session.read()
            if v['ControllerError'] or v['Fault']:
                tuning={'status':'FAILED','request':'PRETUNING','error_bits':v['ErrorBits'],'state':v['ControllerState'],
                        'fault_code':v.get('FaultCode'),'fault_reason':v.get('FaultReason')};break
            if entered and v['ControllerState']==3:
                tuning={'status':'PASSED','request':'PRETUNING','observed_state_transition':[1,3],'values':v};break
        stages['tuning']=tuning;flush()
        outcome.update(status='PASSED' if all(s['status']=='PASSED' for s in stages.values()) else 'PARTIAL',
                stages={k:v['status'] for k,v in stages.items()},evidence=str(evidence));return outcome
    except Exception as error:
        save('execution_error',{'error':str(error),'type':type(error).__name__});flush()
        outcome.update(status='FAILED',reason=str(error),evidence=str(evidence));return outcome
    finally:
        if session:
            try:session.write('CmdStart',False);session.write('CmdStop',True)
            except Exception as error:
                save('cleanup_error',{'error':str(error)});outcome.update(status='FAILED',cleanup_error=str(error))
        if io:
            cleanup=io.restore_inputs();save('cleanup',cleanup)
            if cleanup.get('status')!='SUCCESS':outcome.update(status='FAILED',cleanup_error=cleanup)
        save('summary',outcome)
        flush()
        latest.write_text(json.dumps({'status':outcome.get('status','INTERRUPTED'),'evidence':str(evidence)}),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,required=True);parser.add_argument('--package-dir',type=Path,required=True)
    parser.add_argument('--mode',choices=['SIMULATION'],help='Solo para paquetes históricos v1; v2 usa el mapa IO.')
    args=parser.parse_args();result=run_validation(args.project_root,args.package_dir,args.mode)
    print(json.dumps(result,indent=2,ensure_ascii=False));sys.exit(0 if result['status']=='PASSED' else 2)
