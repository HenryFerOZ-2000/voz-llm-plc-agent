"""Conservative Normal-mode checks between requested behavior and selected architecture.

These checks recognize explicit control constraints; unspecified language remains the
interpreter's responsibility. They never allocate hardware or invent a control law.
"""
from __future__ import annotations

import re
from functional_requirements import (
    fold_text, FUNCTIONAL_REQUIREMENT_PROCESS_VARIABLES, conditional_outputs,
    latches, timed_sequence_steps, timed_sequence_repeat,
)
from utils import build_io_map_index

_NO_PID = (r'\b(?:sin|no)(?:\s+(?:uses?|utilices?|emplees?|crees?|quiero|deseo|usar|utilizar|emplear|crear))?'
           r'(?:\s+(?:usar|utilizar|crear))?\s+(?:(?:el|un|ese|ningun)\s+)?(?:control(?:ador)?\s+)?(?:pid|pi)\b')


def _process_thresholds(text: str) -> set[str]:
    """Process limits, excluding durations and actor/variable identifiers."""
    values=set()
    for match in re.finditer(r'(?<![a-z_\d])\d+(?:[.,]\d+)?',text):
        tail=text[match.end():]
        if re.match(r'\s*(?:ms|s|segundos?|seg|minutos?|min|horas?|h)\b',tail):
            continue
        prefix=text[max(0,match.start()-45):match.start()]
        unit=re.match(r'\s*(?:%|por\s+ciento|cm\b|mm\b|m\b|bar\b|litros?\b)',tail)
        comparison=re.search(r'(?:debajo|encima|inferior|superior|menor|mayor|baj\w*|super\w*|lleg\w*|alcanz\w*|hasta|[<>])[^\d]{0,25}$',prefix)
        if unit or comparison:
            values.add(match.group().replace(',','.'))
    return values

def requested_control(command: str) -> str:
    text=fold_text(command)
    pid=bool(re.search(r'\b(?:pid|pi)\b',text))
    no_pid=bool(re.search(_NO_PID,text))
    creation=bool(re.search(
        r'\b(?:crea\w*|genera\w*|implement\w*|programa\w*)\s+'
        r'(?:(?:un|el|nuevo|otro|control|de)\s+){0,3}(?:pid|pi|controlador|lazo)\b'
        r'|\b(?:pid|controlador|lazo)\s+nuevo\b',text))
    # "existing template/tank" does not mean "existing controller".
    existing=bool(re.search(r'\b(?:pid|controlador|lazo)\s+(?:ya\s+)?(?:existente|instalado|configurado|creado)\b',text))
    supervise=bool(re.search(r'(?<!no )\bsupervis\w*\b',text))
    if pid and (existing or supervise) and not creation and not no_pid:
        return 'SUPERVISION'
    continuous=bool(re.search(r'\b(?:manten\w*|manteng\w*|regul\w*|controla\w*|control\s+(?:de\s+)?(?:nivel|pid)|crea\w*|implement\w*)\b',text))
    if pid and not no_pid:
        parameter_only=bool(re.search(r'\b(?:habilit\w*|deshabilit\w*|activa\w*|desactiva\w*|consigna|setpoint|diagnostic\w*)\b',text))
        return 'SUPERVISION' if parameter_only and not continuous and not creation else 'CONTINUOUS'
    analog=bool(re.search(r'%|por\s+ciento|\b(?:nivel|level|temperatura|presion|caudal|litros?|cm|bar)\b',text))
    numbers=_process_thresholds(text)
    on=bool(re.search(r'\b(?:enciend\w*|encend\w*|arranc\w*|activ\w*|abr[ei]\w*)\b',text))
    off=bool(re.search(r'\b(?:apag\w*|deten\w*|deteng\w*|par[ae]\w*|cierr\w*)\b',text))
    comparison=bool(re.search(r'\b(?:debajo|encima|inferior|superior|baj\w*|super\w*|lleg\w*|alcanz\w*)\b|[<>]',text))
    if analog and on and off and comparison and len(set(numbers))>=2 and (not pid or no_pid):
        return 'HYSTERESIS'
    limit=bool(re.search(r'\b(?:hasta|alcanz\w*|lleg\w*)\b',text))
    process=bool(re.search(r'\b(?:llen\w*|vaci\w*|tanque|bomba|valvula|nivel|level)\b',text))
    if analog and process and off and limit and numbers and (not pid or no_pid):
        return 'THRESHOLD'
    if continuous and process and analog and not no_pid:
        return 'CONTINUOUS'
    return 'UNSPECIFIED'


def _measurement_controls_actuation(requirements: list[dict], measurements: set[str],
                                   mapped_actuators: set[str]) -> bool:
    """Check stop/gating links per actuator, not incidental sensor use in an alarm.

    This is a structural consistency check, not a proof of arbitrary expressions.
    Internal latches may relay a measurement-dependent stop to an output condition.
    A later timed step may run after the measured transition of the same sequence.
    """
    if not measurements:
        return False

    def tokens(expression):
        return {token.casefold() for token in re.findall(r'[A-Za-z_][A-Za-z0-9_]*',str(expression or ''))}

    links=[]
    actuation=set()
    process_targets=set()
    for requirement in requirements:
        kind=requirement.get('type')
        if kind=='analog_output':
            targets=[requirement.get('output')]
            condition=requirement.get('condition')
        elif kind=='conditional_output':
            normalized=conditional_outputs([requirement])[0]
            targets=normalized['outputs'];condition=normalized['condition']
        elif kind=='latch':
            normalized=latches([requirement])[0]
            targets=normalized['outputs'];condition=normalized['reset']
        elif kind=='timed_sequence':
            steps=timed_sequence_steps(requirement)
            from functional_requirements import sequence_step_outputs
            targets=[output for step in steps for output in sequence_step_outputs(step)]
            condition=' '.join(str(step['advance_on'] or '') for step in steps)
        elif kind=='force_off':
            targets=requirement.get('outputs') or [requirement.get('output')]
            condition=requirement.get('condition')
        else:
            continue
        targets={str(target).casefold() for target in targets if target}
        if kind!='force_off':
            actuation.update(targets)
            if kind in {'analog_output','timed_sequence','latch'}:
                process_targets.update(targets)
        links.append((targets,tokens(condition)))
    dependent=set(measurements)
    for _ in range(len(links)):
        previous=len(dependent)
        for targets,references in links:
            if dependent & references:
                dependent.update(targets)
        if len(dependent)==previous:
            break
    # Independent indicators may follow a button instead of the process measurement.
    # Prefer explicit process primitives and mapped actuators; when neither is known,
    # conservatively require feedback for all remaining output conditions.
    process_targets.update(actuation & mapped_actuators)
    required=process_targets or actuation
    return bool(required) and required <= dependent


def control_consistency_errors(semantic: dict, io_map: dict) -> list[str]:
    if semantic.get('interaction_profile')!='normal':
        return []
    requirements=[r for r in semantic.get('functional_requirements') or [] if isinstance(r,dict)]
    types={r.get('type') for r in requirements}
    kind=requested_control(str(semantic.get('command_text','')))
    native='pid_control' in types
    supervisor=semantic.get('intent_id')=='INT_PID_SUPERVISOR' or bool(types & set(FUNCTIONAL_REQUIREMENT_PROCESS_VARIABLES))
    errors=[]
    if re.search(_NO_PID,fold_text(str(semantic.get('command_text','')))) and (native or supervisor):
        errors.append('CONTROL_STRATEGY_MISMATCH: el comando excluye expresamente el uso de PID.')
    if kind in {'THRESHOLD','HYSTERESIS'} and (native or supervisor):
        errors.append('CONTROL_STRATEGY_MISMATCH: el comando pide conmutacion por limites, no crear ni supervisar un PID. Use comparaciones, etapas o histeresis conectadas al sensor del mapa.')
    if kind=='HYSTERESIS' and not native and not supervisor and types and 'hysteresis_switch' not in types:
        errors.append('CONTROL_STRATEGY_MISMATCH: dos limites de encendido/apagado requieren memoria de histeresis, no una comparacion simple.')
    # An existing controller may be supervised explicitly. New continuous regulation
    # cannot be represented by merely creating unconnected Level_SP/PID_Enable flags.
    explicit_pid=bool(re.search(r'\b(?:pid|pi)\b',fold_text(str(semantic.get('command_text','')))))
    if kind=='CONTINUOUS' and types and (supervisor or explicit_pid) and not native:
        errors.append('CONTROL_STRATEGY_MISMATCH: se solicita crear regulacion continua; la supervision de un PID existente no crea el lazo. Use pid_control con las conexiones del mapa.')
    if kind=='SUPERVISION' and native:
        errors.append('CONTROL_STRATEGY_MISMATCH: se solicita supervisar un controlador existente, no crear o reemplazar el lazo PID.')
    index=build_io_map_index(io_map)
    if kind=='THRESHOLD' and types and not native and not supervisor:
        measurements={name.casefold() for name,v in index.items() if
            (v.get('class')=='input' and v.get('type','').upper() in {'INT','WORD','REAL','DINT'}) or
            (v.get('process_config') or {}).get('role')=='MEASUREMENT' or
            # Existing supervisory contract: the map explicitly declares the externally
            # supplied REAL in DB_PLC_PRG. Never invent this input from the command.
            (name=='Level_PV' and v.get('class')=='internal' and v.get('type')=='REAL'
                and v.get('llm_allowed',True) is True)}
        actuator_words=r'\b(?:bomba\w*|pump\w*|valvula\w*|valve\w*)\b'
        mapped_actuators={name.casefold() for name,v in index.items() if v.get('class')=='output' and (
            (v.get('process_config') or {}).get('role')=='ACTUATOR' or
            re.search(actuator_words,fold_text(' '.join([name.replace('_',' '),*v.get('aliases',[])]))))}
        if not _measurement_controls_actuation(requirements,measurements,mapped_actuators):
            errors.append('CONTROL_MEASUREMENT_UNBOUND: la operacion hasta un limite necesita una condicion de parada/transicion que lea la medicion del mapa; una orden fija no implementa el limite.')
        if any(r.get('type')=='timed_sequence' and timed_sequence_repeat(r)[0]!='once' for r in requirements):
            errors.append('CONTROL_STRATEGY_MISMATCH: una operacion finita debe terminar en reposo; no mantener la ultima etapa ni repetir automaticamente.')
        if 'hysteresis_switch' in types:
            errors.append('CONTROL_STRATEGY_MISMATCH: no agregar un segundo umbral ni repeticion a una operacion finita.')
    if supervisor and not native:
        needs_pv=any('Level_PV' in FUNCTIONAL_REQUIREMENT_PROCESS_VARIABLES.get(t,[]) for t in types)
        measured=index.get('Level_PV') or {}
        if needs_pv and (measured.get('type')!='REAL' or measured.get('llm_allowed',True) is not True):
            errors.append('CONTROL_MEASUREMENT_UNBOUND: la supervision necesita Level_PV declarado, autorizado y de tipo REAL en el mapa. No crear una lectura interna constante en sustitucion del sensor.')
    actuator_targets = []
    for requirement in requirements:
        if requirement.get('type') == 'pid_control':
            actuator_targets.append(requirement.get('control_output'))
        elif requirement.get('type') == 'analog_output' or (requirement.get('type') == 'hysteresis_switch' and 'on_value' in requirement):
            actuator_targets.append(requirement.get('output'))
        elif requirement.get('type') == 'timed_sequence':
            for step in timed_sequence_steps(requirement):
                commands = step.get('analog_outputs')
                if isinstance(commands, list):
                    actuator_targets.extend(command.get('output') for command in commands if isinstance(command, dict))
    if actuator_targets:
        text=fold_text(str(semantic.get('command_text','')))
        text=re.sub(r'\b(?:sin|no\s+(?:uses?|utilices?|emplees?))\s+(?:la\s+|una\s+)?(?:bomba|valvula)\b','',text)
        pump=bool(re.search(r'\b(?:bomba\w*|pump\w*)\b',text))
        valve=bool(re.search(r'\b(?:valvula\w*|valve\w*)\b',text))
        for target in actuator_targets:
            candidates=[v for v in index.values() if target.casefold() in
                        [str(v.get('name','')).casefold(),*[str(a).casefold() for a in v.get('aliases',[])]]] if isinstance(target,str) else [v for v in index.values() if v.get('class')=='output' and v.get('llm_allowed',True) and isinstance(v.get('analog_config'),dict)]
            if len(candidates)!=1: continue  # Native map resolution diagnoses missing/ambiguous targets.
            device=(candidates[0].get('analog_config') or {}).get('device_kind')
            if pump and not valve and device=='PROPORTIONAL_VALVE':
                errors.append('CONTROL_ACTUATOR_MISMATCH: se pidio una bomba pero se eligio una valvula proporcional. Conserve el actuador solicitado o informe el recurso faltante.')
            if valve and not pump and device=='VARIABLE_SPEED_DRIVE':
                errors.append('CONTROL_ACTUATOR_MISMATCH: se pidio una valvula pero se eligio un variador/bomba. Conserve el actuador solicitado o informe el recurso faltante.')
    return errors


def clarify_control_failure(semantic: dict, validation: dict) -> tuple[dict,dict]:
    if semantic.get('interaction_profile')!='normal' or not any(str(e).startswith('CONTROL_') for e in validation.get('errors',[])):
        return semantic,validation
    question=semantic.get('clarification_question') or (
        'No pude obtener un programa que conserve el comportamiento solicitado. '
        'Indica como debe iniciar el proceso, cuando debe detenerse y si debe repetir o mantener un valor continuo.')
    return ({**semantic,'requires_clarification':True,'clarification_question':question},
            {**validation,'is_valid':False,'requires_clarification':True,'clarification_question':question})
