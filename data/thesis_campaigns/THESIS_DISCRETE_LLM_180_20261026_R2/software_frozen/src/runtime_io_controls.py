"""Manual, program-bound PLCSIM controls; independent of the formal Oracle capabilities."""
from __future__ import annotations
import math
from typing import Any
import plcsim_runtime_io as rio

LIMITS={'INT':(-32768,32767),'WORD':(0,65535),'UINT':(0,65535),
        'DINT':(-2147483648,2147483647),'DWORD':(0,4294967295),'REAL':(-3.4028234e38,3.4028234e38)}

def signals(program:dict,direction:str)->list[dict]:
    return [s for s in program['signals'].values() if s['direction']==direction and (
        s['data_type']=='BOOL' and s['bit'] is not None or
        s['data_type'] in LIMITS and s['bit'] is None and
        s.get('size',rio.runtime_address(s['address'])['size'])==('W' if s['data_type'] in {'INT','WORD','UINT'} else 'D'))]

def scale(signal:dict)->dict:
    config=signal.get('analog_config')
    if isinstance(config,dict) and config.get('confirmed') is True:
        keys=('raw_min','raw_max','engineering_min','engineering_max')
        if all(isinstance(config.get(k),(int,float)) and not isinstance(config[k],bool) and math.isfinite(config[k]) for k in keys):
            if config['raw_min']<config['raw_max'] and config['engineering_min']<config['engineering_max']:
                return config
    lo,hi=LIMITS.get(signal['data_type'],(0,1))
    return {'raw_min':lo,'raw_max':hi,'engineering_min':lo,'engineering_max':hi,'engineering_unit':'RAW'}

def encode_value(signal:dict,value:Any)->Any:
    if signal['data_type']=='BOOL':
        if not isinstance(value,bool):raise rio.RuntimeIOError(rio.ERROR_TYPE_UNSUPPORTED,'BOOL requiere ON/OFF.')
        return value
    c=scale(signal)
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not c['engineering_min']<=value<=c['engineering_max']:
        raise rio.RuntimeIOError('PLCSIM_IO_VALUE_RANGE','Valor fuera del rango configurado o no numérico.')
    raw=c['raw_min']+(value-c['engineering_min'])*(c['raw_max']-c['raw_min'])/(c['engineering_max']-c['engineering_min'])
    if signal['data_type']!='REAL':raw=round(raw)
    lo,hi=LIMITS[signal['data_type']]
    if not lo<=raw<=hi:raise rio.RuntimeIOError('PLCSIM_IO_VALUE_RANGE','RAW fuera del tipo IEC.')
    return raw

def decode_value(signal:dict,raw:Any)->Any:
    if signal['data_type']=='BOOL' or raw is None:return raw
    c=scale(signal)
    return c['engineering_min']+(raw-c['raw_min'])*(c['engineering_max']-c['engineering_min'])/(c['raw_max']-c['raw_min'])

class ManualIOSession(rio.RuntimeIOSession):
    """Input stimuli in RUN; separate output-only manual test in STOP. No CPU state changes."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.originals={}

    def _signal(self,name,direction=None):
        signal=self.program['signals'].get(name)
        if signal is None or signal not in signals(self.program,signal.get('direction','')):
            raise rio.RuntimeIOError(rio.ERROR_TYPE_UNSUPPORTED,'Señal no compatible con el programa descargado.')
        if direction and signal['direction']!=direction:
            raise rio.RuntimeIOError(rio.ERROR_WRITE_NOT_ALLOWED,'Dirección de la señal incorrecta.')
        return signal

    def _manual(self,operation,signal,**extra):
        payload={**self._base_payload(),'purpose':'MANUAL_IO','operation':operation,
                 'signal':{**rio._bridge_signal(signal),'size':signal.get('size',rio.runtime_address(signal['address'])['size'])},
                 'expected_signals':[rio._bridge_signal(s) for direction in ('I','Q') for s in signals(self.program,direction)],**extra}
        raw=self._absorb(self._bridge('manual_io',payload))
        if raw['status']!='PLCSIM_IO_PASSED':
            raise rio.RuntimeIOError(raw['status'],'; '.join(raw.get('errors',[])) or 'Operación IO sin verificar.')
        return raw

    def read_signals(self,names):
        values=[]
        for name in names:
            signal=self._signal(name)
            raw=self._manual('read',signal)
            row=raw['reads'][-1]
            values.append({'name':name,'address':signal['address'],'value':row['value'],
                           'engineering_value':decode_value(signal,row['value']),'timestamp':row.get('timestamp')})
        return {'status':rio.SUCCESS,'values':values,'errors':[]}

    def _write(self,name,value,direction):
        signal=self._signal(name,direction)
        desired='RUN' if direction=='I' else 'STOP'
        report=self.runtime_report
        if self.target_type!='PLCSIM_ADVANCED' or not report.get('connected') or report.get('instance_name')!=self.config['instance_name']:
            raise rio.RuntimeIOError(rio.ERROR_WRITE_NOT_ALLOWED,'Solo la instancia PLCSIM seleccionada puede recibir estímulos.')
        if report.get('cpu_state')!=desired:
            raise rio.RuntimeIOError(rio.ERROR_WRITE_NOT_ALLOWED,f'Esta prueba requiere CPU en {desired}. Cambie su estado manualmente y vuelva a abrir la prueba.')
        value=encode_value(signal,value)
        if name not in self.originals:
            original=self.read_signals([name])['values'][0]['value']
            self.originals[name]={'signal':signal,'value':original}
            self.touched_inputs[name]=signal
        raw=self._manual('write',signal,value=value)
        entry=raw['writes'][-1]
        return {'status':rio.SUCCESS,'name':name,'address':signal['address'],'requested_value':value,
                'readback':entry['actual_readback'],'readback_tag':entry['readback_tag'],'match':entry['match']}

    def write_input(self,name,value):return self._write(name,value,'I')
    def write_output(self,name,value):return self._write(name,value,'Q')

    def restore_inputs(self):
        restored=[]
        for name,entry in list(self.originals.items()):
            try:
                self._manual('restore',entry['signal'],value=entry['value'])
                del self.originals[name];self.touched_inputs.pop(name,None);restored.append(name)
            except rio.RuntimeIOError as error:
                self.errors.append(str(error))
        ok=not self.originals
        self.cleanup={'performed':True,'success':ok,'inputs':[{'name':name,'restored':True} for name in restored]}
        return {'status':rio.SUCCESS if ok else rio.ERROR_CLEANUP_FAILED,'restored':restored,'pending':list(self.originals)}

    def build_report(self,*args,**kwargs):
        report=super().build_report(*args,**kwargs)
        report.update(input_bindings=signals(self.program,'I'),output_bindings=signals(self.program,'Q'),
                      cleanup_policy='restore_original_values',functional_success=None)
        return report
