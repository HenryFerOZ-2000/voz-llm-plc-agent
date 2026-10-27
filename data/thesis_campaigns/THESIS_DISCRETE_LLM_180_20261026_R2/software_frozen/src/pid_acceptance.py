"""Numerical acceptance of recorded samples. The evaluator never proves native execution."""
from __future__ import annotations
import math


def require_simulation_target(target):
    if target.get('target_type')!='PLCSIM_ADVANCED':
        raise ValueError('PID_ACCEPTANCE_TARGET: la validacion automatica solo acepta PLCSIM_ADVANCED.')


def evaluate_pid_samples(samples, setpoint, tolerance=2.0, hold_seconds=10.0, deadline_seconds=300.0):
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (setpoint,tolerance,hold_seconds,deadline_seconds)) or min(tolerance,hold_seconds,deadline_seconds)<=0:
        raise ValueError('PID_ACCEPTANCE_CRITERIA: criterios finitos y positivos requeridos.')
    stable_since=None;previous=None;last=0.0;reason='Sin ejecucion nativa registrada.'
    for sample in samples:
        t,pv=sample.get('t_s'),sample.get('pv')
        if type(t) not in (int,float) or not math.isfinite(t) or t<0:
            stable_since=None;previous=None;reason='Tiempo de muestra invalido.';continue
        if previous is not None and (t<=previous or t-previous>.5):stable_since=None
        previous=t;last=max(last,t)
        if t>deadline_seconds:break
        valid=(type(pv) in (int,float) and math.isfinite(pv) and sample.get('sensor_valid') is True
            and sample.get('fault') is False and sample.get('controller_error',False) is False
            and abs(pv-setpoint)<=tolerance)
        if not valid:stable_since=None;reason='El lazo no mantiene la banda de aceptacion.';continue
        if stable_since is None:stable_since=t
        if t-stable_since>=hold_seconds-1e-8:
            return {'status':'PASSED','data_criteria_satisfied':True,'native_execution_verified':False,
                'settled_at_s':t,'stable_since_s':stable_since,'setpoint':setpoint,'tolerance':tolerance,
                'hold_seconds':hold_seconds,'deadline_seconds':deadline_seconds}
    return {'status':'FAILED' if last>=deadline_seconds else 'PENDING','data_criteria_satisfied':False,
        'native_execution_verified':False,'reason':'Tiempo maximo agotado.' if last>=deadline_seconds else reason,
        'last_sample_s':last,'setpoint':setpoint,'tolerance':tolerance,'hold_seconds':hold_seconds,'deadline_seconds':deadline_seconds}
