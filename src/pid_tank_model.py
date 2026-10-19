"""Demonstration tank dynamics; this is a plant model, never a PID implementation."""
from __future__ import annotations
import math


class TankModel:
    def __init__(self, profile: dict, input_binding: dict, output_binding: dict):
        if profile.get('schema_version') != 1 or profile.get('model') != 'TANK':
            raise ValueError('PID_MODEL_PROFILE: requiere perfil TANK versión 1.')
        self.low, self.high = (input_binding[k] for k in ('engineering_min', 'engineering_max'))
        if not all(type(v) in (int,float) and math.isfinite(v) for v in (self.low,self.high)) or self.low>=self.high:
            raise ValueError('PID_MODEL_RANGE: rango de medición finito requerido.')
        if output_binding['unit']!='%' or (output_binding['engineering_min'],output_binding['engineering_max'])!=(0,100):
            raise ValueError('PID_MODEL_OUTPUT: requiere mando proporcional 0–100 %.')
        self.span=self.high-self.low
        for key in ('initial_percent','fill_percent_per_s','drain_percent_per_s'):
            value=profile.get(key)
            if type(value) not in (int,float) or not math.isfinite(value) or value<0:
                raise ValueError('PID_MODEL_PROFILE: valor inválido: '+key)
        if profile['initial_percent']>100:
            raise ValueError('PID_MODEL_PROFILE: nivel inicial fuera de 0–100 %.')
        self.direction=profile.get('direction','FILL')
        if self.direction not in {'FILL','DRAIN'}:
            raise ValueError('PID_MODEL_DIRECTION: requiere FILL o DRAIN.')
        self.fill=self.span*profile['fill_percent_per_s']/100
        self.drain=self.span*profile['drain_percent_per_s']/100
        self.level=self.low+self.span*profile['initial_percent']/100

    def step(self, command_percent: float, dt_s: float) -> float:
        if (type(command_percent) not in (int,float) or not math.isfinite(command_percent) or not 0<=command_percent<=100
                or type(dt_s) not in (int,float) or not math.isfinite(dt_s) or dt_s<0):
            raise ValueError('PID_MODEL_VALUE: mando 0–100 % y dt finito no negativo requeridos.')
        net=self.fill*command_percent/100-self.drain
        if self.direction=='DRAIN':net=-net
        self.level=max(self.low,min(self.high,self.level+net*dt_s))
        return self.level
