"""Validate observed V18 capability reports, without interpreting a mock as a live test."""
from __future__ import annotations


def normalize_pid_probe(report: dict, period_ms: int=100) -> dict:
    caps=report.get('pid_capabilities',{})
    cpu=report.get('cpu',{})
    if report.get('status')!='PID_PROBE_PASSED' or caps.get('compile_errors')!=0:
        raise ValueError('PID_CONFIG_MISMATCH: la prueba real no compilo.')
    if not cpu.get('cpu_type_identifier') or not cpu.get('cpu_FirmwareVersion'):
        raise ValueError('PID_CONFIG_MISMATCH: CPU o firmware no verificado.')
    if caps.get('technology_type')!='PID_Compact' or caps.get('technology_version')!='2.3':
        raise ValueError('PID_UNSUPPORTED_VERSION')
    obs=[b for b in caps.get('after',{}).get('blocks',[]) if b.get('number')==30]
    if len(obs)!=1:
        raise ValueError('PID_CYCLIC_OB_UNVERIFIED: OB30 no verificado.')
    attrs=obs[0]['attributes']
    if attrs.get('SecondaryType')!='CyclicInterrupt' or int(attrs.get('CyclicTime',0))!=period_ms*1000:
        raise ValueError('PID_CYCLIC_OB_UNVERIFIED: tipo o periodo incorrecto.')
    return {'schema_version':1,'tia_version':'V18','technology_type':'PID_Compact','technology_version':'2.3',
        'cpu_type_identifier':cpu['cpu_type_identifier'],'cpu_firmware':cpu['cpu_FirmwareVersion'],
        'secondary_type':attrs['SecondaryType'],'cyclic_time_us':int(attrs['CyclicTime']),
        'priority':int(attrs['PriorityNumber']),'cyclic_time_settable':caps.get('cyclic_time_settable') is True,
        'parameter_names':sorted(caps['parameters']),'observed_at':report['timestamp'],
        'physical_download_executed':False}
