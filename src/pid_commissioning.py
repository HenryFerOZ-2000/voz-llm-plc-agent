"""Declared native PID controls and runtime access, separate from frozen P01-P12."""
from __future__ import annotations
import math
import queue
import threading
from pid_control import resolve_pid_loops

WRITABLE_BOOL={'CmdStart','CmdStop','CmdReset','CmdManual','CmdPretune','CmdFinetune','SimSensorFault'}
READ_TYPES={'PV':'REAL','CV':'REAL','SP':'REAL','Running':'BOOL','Fault':'BOOL','SensorValid':'BOOL',
            'ControllerError':'BOOL','ControllerState':'INT','ErrorBits':'DWORD','ParametersConfirmed':'BOOL','TuningMode':'INT'}
READ_TYPES.update({f'Build{i:02d}':'INT' for i in range(16)})
READ_TYPES.update(Kp='REAL',Ti='REAL',Td='REAL')
READ_TYPES['FaultCode']='INT'
FAULT_REASONS={0:'Sin fallo',1:'Emergencia',2:'Sensor no valido',3:'Consigna fuera de rango',
    4:'Selectores Auto/Manual en conflicto',5:'Limite de sobrellenado',6:'Fallo del bloque PID Siemens',7:'Mando PID no valido'}


class PidOperationJob:
    """A single owner retains its operation until the UI consumes the final result."""
    def __init__(self):
        self.thread=None;self.operation=None
        self.cancel_event=threading.Event();self.results=queue.Queue()

    @property
    def active(self):return self.operation is not None

    def start(self,operation,work):
        if self.active:return False
        self.operation=operation;self.cancel_event=threading.Event()
        def worker():
            try:self.results.put((operation,'ok',work(self.cancel_event)))
            except Exception as error:self.results.put((operation,'error',str(error)))
        self.thread=threading.Thread(target=worker,daemon=True);self.thread.start()
        return True

    def cancel(self):self.cancel_event.set()

    def poll(self):
        try:result=self.results.get_nowait()
        except queue.Empty:return None
        self.operation=None
        return result
PULSES={'CmdStart','CmdStop','CmdReset','CmdPretune','CmdFinetune'}


def validate_generation_mode(semantic,io_map,mode):
    return resolve_pid_loops(semantic.get('functional_requirements') or [],io_map,'SIEMENS_SCL_V18')


def build_pid_process_bindings(project):
    project=project.to_dict() if hasattr(project,'to_dict') else project
    loops=project.get('pid_loops',[])
    if len(loops)!=1:raise ValueError('PID_BINDINGS: se requiere un lazo nativo.')
    loop=loops[0];db=loop['symbols']['db']
    declared={v['name']:v['data_type'] for v in project['pou']['variables'] if v['source']=='generated_pid'}
    legacy='mode' in loop
    writable_bool=WRITABLE_BOOL if legacy else WRITABLE_BOOL-{'SimSensorFault'}
    fields={**READ_TYPES,**{n:'BOOL' for n in writable_bool},'ManualValue':'REAL'}
    bindings={}
    for name,typ in fields.items():
        if declared.get(name)!=typ:raise ValueError('PID_BINDINGS: miembro ausente o incompatible: '+name)
        writable=name in writable_bool or name in {'SP','ManualValue'}
        bindings[name]={'kind':'NATIVE_PID_VARIABLE','name':db+'.'+name,'db':db,'member':name,'data_type':typ,'writable':writable}
    result={'schema_version':1 if legacy else 2,'instance_db':db,'unit':loop['unit'],
        'build_signature':list(project['metadata']['pid_build_signature']),
        'controller':loop['controller'],'period_ms':loop['period_ms'],'bindings':bindings}
    if legacy:
        result.update(mode=loop['mode'],engineering_min=loop['input_config']['engineering_min'],
                      engineering_max=loop['input_config']['engineering_max'],
                      calibration_confirmed=all(loop[k].get('confirmed') is True for k in ('input_config','output_config')))
    else:
        result.update(input_binding=loop['input_binding'],output_binding=loop['output_binding'],
                      engineering_min=loop['input_binding']['engineering_min'],engineering_max=loop['input_binding']['engineering_max'],
                      calibration_confirmed=all(b.get('analog_config',{}).get('confirmed') is True
                          for b in (loop['input_binding'],loop['output_binding']) if b['representation']=='HARDWARE_RAW'))
    return result


def validate_commissioning_write(bindings,name,value,execution_context):
    c=execution_context;b=bindings['bindings'].get(name)
    if not b or not b['writable']:raise ValueError('PID_WRITE: miembro no escribible.')
    if c.get('target_type')!='PLCSIM_ADVANCED' or not c.get('connected') or c.get('cpu_state')!='RUN' or not c.get('program_verified'):
        raise ValueError('PID_WRITE: se necesita programa descargado verificado, instancia PLCSIM y CPU RUN.')
    if bindings.get('schema_version')==1:
        if c.get('mode')!=bindings['mode']:raise ValueError('PID_WRITE: modo distinto del programa generado.')
        if bindings['mode']=='PHYSICAL' and not bindings['calibration_confirmed']:raise ValueError('PID_CALIBRATION_REQUIRED')
    if b['data_type']=='BOOL':
        if type(value) is not bool:raise ValueError('PID_WRITE_TYPE: se requiere BOOL.')
    else:
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('PID_WRITE_TYPE: valor finito requerido.')
        lo,hi=(bindings['engineering_min'],bindings['engineering_max']) if name=='SP' else (0,100)
        if not lo<=value<=hi:raise ValueError('PID_WRITE_RANGE: valor fuera del rango del mapa.')
    if name=='SimSensorFault' and bindings.get('mode')!='SIMULATION':raise ValueError('PID_WRITE: fallo simulado solo en paquete histórico de simulación.')
    if name in {'CmdPretune','CmdFinetune'} and value:
        if not c.get('tuning_authorized') or not c.get('sensor_valid') or c.get('fault') or not c.get('running'):
            raise ValueError('PID_TUNING: requiere autorizacion explicita, marcha, sensor valido y ausencia de falla.')
    if name=='CmdStart' and value and (not c.get('sensor_valid') or c.get('fault')):
        raise ValueError('PID_START: revise el sensor y rearme la falla.')
    return {'signal':dict(b),'value':value,'pulse':name in PULSES and value is True}


class PidCommissioningSession:
    def __init__(self,bindings,io_session,context):
        self.bindings,self.io_session,self.context=bindings,io_session,context

    def _identity(self):
        if self.bindings.get('schema_version')!=2:return {}
        return {'native_pid_identity':{'db':self.bindings['instance_db'],
                                      'build_signature':list(self.bindings['build_signature'])}}

    def read(self):
        signals=[b for b in self.bindings['bindings'].values() if b['member'] in READ_TYPES]
        report=self.io_session._bridge('io_sequence',{'steps':[{'op':'sample','id':'pid_read','duration_ms':0,'signals':signals}],
            'process_variables':True,'purpose':'NATIVE_PID_COMMISSIONING',
            'target_type':self.context['target_type']})
        if report.get('status')!='PLCSIM_IO_PASSED':raise ValueError('PID_READ: '+'; '.join(report.get('errors',[])))
        samples=report.get('samples') or []
        values={name.rsplit('.',1)[-1]:value for name,value in (samples[-1].get('values',{}) if samples else {}).items()}
        if [values.get(f'Build{i:02d}') for i in range(16)]!=self.bindings['build_signature']:
            self.context['program_verified']=False
            raise ValueError('PID_PROGRAM_MISMATCH: la huella del programa cargado difiere del paquete.')
        self.context['program_verified']=True
        self.context.update(sensor_valid=values.get('SensorValid') is True,fault=values.get('Fault') is True,running=values.get('Running') is True)
        result={name:value for name,value in values.items() if not name.startswith('Build')}
        if 'FaultCode' in result:result['FaultReason']=FAULT_REASONS.get(result['FaultCode'],'Fallo desconocido')
        return result

    def write(self,name,value,*,pulse=True):
        # Refresh permissives immediately before each write; never rely on a stale UI display.
        self.read()
        operation=validate_commissioning_write(self.bindings,name,value,self.context)
        self.io_session._guard_write()
        writes=[{'signal':operation['signal'],'value':value}]
        if name in {'CmdPretune','CmdFinetune'} and value is True:
            # Transition directly from software manual to the requested tuning
            # mode; an intermediate automatic scan can saturate the output.
            writes.insert(0,{'signal':self.bindings['bindings']['CmdManual'],'value':False})
        if name=='CmdStart' and value is True:
            writes.insert(0,{'signal':self.bindings['bindings']['CmdStop'],'value':False})
        steps=[{'id':'command','op':'set','writes':writes}]
        if operation['pulse'] and pulse:
            steps +=[{'id':'hold','op':'sample','duration_ms':max(300,self.bindings['period_ms']*3),'period_ms':100,
                     'signals':[self.bindings['bindings']['Running']]},
                    {'id':'release','op':'set','writes':[{'signal':operation['signal'],'value':False}]}]
        if name in PULSES and (value is False or pulse):
            steps +=[{'id':'release_seen','op':'sample','duration_ms':self.bindings['period_ms']*2,'period_ms':100,
                     'signals':[self.bindings['bindings']['Running']]}]
        report=self.io_session._bridge('io_sequence',{'steps':steps,'process_variables':True,'purpose':'NATIVE_PID_COMMISSIONING',
            'target_type':self.context['target_type'],'settle_ms':20,**self._identity()})
        if report.get('status')!='PLCSIM_IO_PASSED':raise ValueError('PID_WRITE: '+'; '.join(report.get('errors',[])))
        return self.read()
