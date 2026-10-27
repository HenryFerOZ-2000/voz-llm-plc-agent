"""Native PID contract: process resources come from the map, never from bench addresses."""
from __future__ import annotations

import copy
import math
import re
from typing import Any

from analog_config import analog_configuration_report, is_analog_channel
from engineering_units import canonical_unit, convert_unit, quantity_label
from plc_ir import PLCPIDLoop, PLCPOU, PLCProjectIR, PLCTask, PLCVariable
from utils import build_io_map_index, get_project_root, load_json_file
from process_signals import normalize_process_binding, validate_process_storage


class PIDConfigurationError(ValueError):
    def __init__(self, code: str, message: str, path: str = 'functional_requirements', candidates: list | None = None):
        self.code, self.path, self.message, self.candidates = code, path, message, candidates or []
        super().__init__(f'{code}: {message}')


def has_native_pid(requirements: list[dict]) -> bool:
    return any(isinstance(r, dict) and r.get('type') == 'pid_control' for r in requirements or [])


def _number(value: Any, label: str) -> float:
    try:
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise PIDConfigurationError('PID_VALUE', f'{label} debe ser un número finito.')
    return float(value)


def _select_device(requested: Any, cls: str, index: dict) -> dict:
    def compatible(entry):
        if entry.get('llm_allowed', True) is False:
            return False
        process = entry.get('process_config')
        if isinstance(process, dict):
            return (process.get('role') == ('MEASUREMENT' if cls == 'input' else 'MANIPULATED')
                    and (quantity_label(str(process.get('quantity', ''))) == 'Nivel' if cls == 'input' else True))
        if not is_analog_channel(entry) or entry.get('class') != cls:
            return False
        cfg = entry.get('analog_config') or {}
        return (quantity_label(str(cfg.get('quantity', ''))) == 'Nivel' if cls == 'input'
                else cfg.get('device_kind') in {'PROPORTIONAL_VALVE', 'VARIABLE_SPEED_DRIVE', 'OTHER_ACTUATOR'})
    if requested:
        matches = [e for e in index.values() if compatible(e) and isinstance(requested, str) and
                   (e['name'].casefold() == requested.casefold() or requested.casefold() in
                    [str(a).casefold() for a in e.get('aliases', [])])]
        if len(matches) > 1:
            raise PIDConfigurationError('PID_DEVICE_AMBIGUOUS', f'El alias {requested!r} corresponde a varios dispositivos.',
                                        candidates=[e['name'] for e in matches])
        if not matches:
            raise PIDConfigurationError('PID_DEVICE', f'El dispositivo {requested!r} no existe, no está permitido o no es compatible.')
        return matches[0]
    candidates = [e for e in index.values() if compatible(e)]
    if len(candidates) > 1:
        raise PIDConfigurationError('PID_DEVICE_AMBIGUOUS',
            'Hay varios dispositivos compatibles. Indique qué sensor/proceso o actuador desea controlar.',
            candidates=[e['name'] for e in candidates])
    if candidates:
        return candidates[0]
    raise PIDConfigurationError('PID_DEVICE_MISSING', f'Falta {"una medición de nivel" if cls == "input" else "un mando proporcional"} permitido en el mapa (hardware o señal DB).')


def normalize_native_pid_command(semantic: dict) -> dict:
    result = copy.deepcopy(semantic)
    ignored = []
    for i, requirement in enumerate(result.get('functional_requirements') or []):
        if isinstance(requirement, dict) and requirement.get('type') == 'pid_control' and 'mode' in requirement:
            ignored.append({'path': f'functional_requirements[{i}].mode', 'value': requirement.pop('mode')})
    parameters = result.get('parameters')
    if isinstance(parameters, dict) and 'pid_mode' in parameters:
        ignored.append({'path': 'parameters.pid_mode', 'value': parameters.pop('pid_mode')})
    if ignored:
        result.setdefault('metadata', {}).setdefault('pid_legacy_fields_ignored', []).extend(ignored)
    return result


def resolve_pid_loops(requirements: list[dict], io_map: dict, target_platform: str) -> list[PLCPIDLoop]:
    requests = [r for r in requirements or [] if isinstance(r, dict) and r.get('type') == 'pid_control']
    if not requests:
        return []
    if target_platform.upper() not in {'SIEMENS_SCL_V18', 'SIEMENS', 'SIEMENS_SCL', 'TIA', 'TIA_V18'}:
        raise PIDConfigurationError('PID_TARGET', 'El PID nativo requiere Siemens TIA V18.')
    if len(requests) != 1:
        raise PIDConfigurationError('PID_MULTIPLE_LOOPS', 'Esta versión admite un lazo PID nativo por programa.')
    if any(r.get('type') != 'pid_control' for r in requirements):
        raise PIDConfigurationError('PID_COMPOSITION_UNSUPPORTED', 'La combinación solicitada con otro comportamiento todavía no está integrada; no se generará parcialmente.')
    req = requests[0]
    defaults = load_json_file(get_project_root() / 'config/native_pid_map_defaults.json')
    period = req.get('period_ms', defaults['period_ms'])
    if type(period) is not int or period != 100:
        raise PIDConfigurationError('PID_PERIOD', 'El lazo nativo verificado requiere un período de 100 ms.')
    direction = req.get('direction')
    if direction not in {'FILL', 'DRAIN'}:
        raise PIDConfigurationError('PID_DIRECTION', 'Indique si el actuador llena o vacía el proceso.')
    loop_id = req.get('loop_id', 'Loop1')
    if not isinstance(loop_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}', loop_id):
        raise PIDConfigurationError('PID_LOOP_ID', 'El identificador del lazo debe ser válido y tener hasta 40 caracteres.')
    index = build_io_map_index(io_map)
    sensor = _select_device(req.get('process_input'), 'input', index)
    actuator = _select_device(req.get('control_output'), 'output', index)
    input_cfg = normalize_process_binding(sensor, 'MEASUREMENT')
    output_cfg = normalize_process_binding(actuator, 'MANIPULATED')
    conflicts = validate_process_storage([input_cfg, output_cfg])
    if conflicts:
        raise PIDConfigurationError('PID_STORAGE_CONFLICT', '; '.join(conflicts))
    target_unit = input_cfg['unit']
    sp = _number(req.get('setpoint'), 'El setpoint')
    unit = req.get('unit', target_unit)
    if not isinstance(unit, str) or not unit.strip():
        raise PIDConfigurationError('PID_UNIT', 'Falta una unidad válida para el setpoint.')
    if canonical_unit(unit) != canonical_unit(target_unit):
        try:
            sp = convert_unit(sp, unit, target_unit)
        except ValueError as error:
            raise PIDConfigurationError('PID_UNIT', str(error)) from error
    if not input_cfg['engineering_min'] <= sp <= input_cfg['engineering_max']:
        raise PIDConfigurationError('PID_SETPOINT_RANGE', 'El setpoint está fuera del rango físico del sensor.')
    if output_cfg['unit'] != '%' or output_cfg['engineering_min'] != 0 or output_cfg['engineering_max'] != 100:
        raise PIDConfigurationError('PID_ACTUATOR_RANGE', 'El primer lazo nativo requiere mando del actuador 0–100 %.')
    resources = copy.deepcopy(req.get('resources') or {})
    allowed = {'start':'input', 'stop':'input', 'reset':'input', 'emergency':'input', 'auto':'input',
               'manual':'input', 'enable_output':'output', 'alarm_output':'output'}
    if not isinstance(resources, dict) or any(key not in allowed for key in resources):
        raise PIDConfigurationError('PID_RESOURCES', 'Las funciones digitales del lazo no son válidas.')
    for key, name in resources.items():
        entry = index.get(name) if isinstance(name, str) else None
        if entry is None:
            raise PIDConfigurationError('PID_DIGITAL_MISSING', f'Falta un canal digital para {key}: {name}.')
        if entry.get('llm_allowed', True) is False or entry.get('type') != 'BOOL' or entry.get('class') != allowed[key]:
            raise PIDConfigurationError('PID_DEVICE', f'{name}: dirección, tipo o permiso incompatible con {key}.')
        from io_allocator import functional_role_key
        declared=entry.get('semantic_role')
        role=functional_role_key(declared or name) or str(declared or '').lower()
        categories={
            'start':{'start','arranque','marcha'},'stop':{'stop','paro','parada'},
            'reset':{'reset','rearme'},'emergency':{'emergency','emergencia'},
            'auto':{'auto','automatico','automatic'},'manual':{'manual'},
            'alarm_output':{'alarm','alarma','fault','falla','error'},
            'enable_output':{'enable','habilitacion','motor','pump','bomba','valve','valvula','contactor'}}
        words=set(role.split())
        known=set().union(*categories.values())
        generic=bool(re.fullmatch(r'[IQ]_(?:Digital(?:_\d+)?|Free[_\d]*|Aux(?:_Output)?|Input[_\d]*|Output[_\d]*)',name,re.I))
        protected_output=allowed[key]=='output' and entry.get('state') in {'ASSIGNED','LOCKED'} and not generic
        if (declared or words & known or protected_output) and not (words & categories[key]):
            raise PIDConfigurationError('PID_RESOURCE_ROLE',f'{name}: función existente incompatible con {key}.')
    from io_allocator import normalize_address
    output_addresses=[normalize_address(str(index[n].get('location',''))) for k,n in resources.items() if allowed[k]=='output']
    if len(output_addresses)!=len(set(output_addresses)):
        raise PIDConfigurationError('PID_RESOURCE_CONFLICT','Dos funciones no pueden escribir la misma salida física.')
    policy = req.get('start_policy', 'EDGE' if 'start' in resources else 'OPERATOR')
    if policy not in {'EDGE', 'OPERATOR', 'CONTINUOUS_EXPLICIT'} or policy == 'EDGE' and 'start' not in resources:
        raise PIDConfigurationError('PID_START_POLICY', 'Falta definir una forma válida de habilitar el control.')
    controller = copy.deepcopy(defaults['controller'])
    controller['technology_version'] = defaults['technology_version']
    overfill = req.get('overfill_limit')
    if overfill is not None:
        overfill = _number(overfill, 'El límite de sobrellenado')
        try:
            overfill = convert_unit(overfill, unit, target_unit)
        except ValueError as error:
            raise PIDConfigurationError('PID_UNIT', str(error)) from error
        if not input_cfg['engineering_min'] < overfill <= input_cfg['engineering_max']:
            raise PIDConfigurationError('PID_OVERFILL_RANGE', 'El límite de sobrellenado no pertenece al rango del sensor.')
    symbols = {'fb':f'FB_PID_{loop_id}', 'db':f'DB_PID_{loop_id}', 'controller':f'PID_{loop_id}', 'ob':f'OB_PID_{loop_id}'}
    if {s.casefold() for s in symbols.values()} & {s.casefold() for s in index}:
        raise PIDConfigurationError('PID_SYMBOL_CONFLICT', 'Un nombre de bloque del lazo coincide con una variable del mapa.')
    if any(b.get('storage', {}).get('db', '').casefold() in {s.casefold() for s in symbols.values()} for b in (input_cfg, output_cfg)):
        raise PIDConfigurationError('PID_SYMBOL_CONFLICT', 'Un DB de proceso coincide con un bloque del controlador.')
    return [PLCPIDLoop(loop_id,sensor['name'],actuator['name'],
        sp,target_unit,direction,period,policy,resources,input_cfg,output_cfg,controller,overfill,symbols)]


def build_pid_project_ir(semantic: dict, io_map: dict, target: str, project_name: str | None = None) -> PLCProjectIR:
    semantic = normalize_native_pid_command(semantic)
    requirements = semantic.get('functional_requirements') or []
    loops = resolve_pid_loops(requirements, io_map, target)
    loop = loops[0]
    index = build_io_map_index(io_map)
    names = list(dict.fromkeys([n for n in [loop.process_input,loop.control_output,*loop.resources.values()] if n]))
    variables = [PLCVariable(n,index[n]['type'],index[n]['class'],index[n].get('location'),None,
                             index[n].get('description',''),'plc_map',False) for n in names]
    db_access = {}
    for binding in (loop.input_binding, loop.output_binding):
        if binding['representation'] == 'DB_ENGINEERING':
            variable = next(v for v in variables if v.name == binding['name'])
            variable.var_class = 'input' if binding['role'] == 'MEASUREMENT' else 'output'
            variable.source = 'plc_map_process'
            db_access[variable.name] = binding['storage']
            if binding['role'] == 'MEASUREMENT':
                quality = variable.name + '_Quality'
                if quality.casefold() in {name.casefold() for name in index}:
                    raise PIDConfigurationError('PID_SYMBOL_CONFLICT', f'{quality}: nombre de calidad ocupado.')
                variables.append(PLCVariable(quality,'BOOL','input',None,'FALSE','Calidad de proceso','generated_pid',False))
                db_access[quality] = {**binding['storage'], 'member': binding['validity_member']}
    pou = PLCPOU(loop.symbols['fb'],'PROGRAM','ST',variables=variables,
                 comments=['Lazo PID nativo; recursos resueltos desde el mapa.'])
    metadata = {'semantic_output':copy.deepcopy(semantic), 'parameters':copy.deepcopy(semantic.get('parameters') or {}),
        'required_variables':names, 'authorized_variables':sorted(index), 'missing_variables':[],
        'generated_internal_variables':[], 'generated_functional_variables':[],
        'functional_requirements':copy.deepcopy(requirements), 'native_pid':True, 'pid_db_access':db_access}
    metadata.update(semantic.get('metadata') or {})
    project = PLCProjectIR(project_name or f'PID_{loop.loop_id}','SIEMENS_SCL_V18',str(semantic.get('case_id') or 'NOCASE'),
        str(semantic.get('intent_id','INT_UNKNOWN')),semantic.get('command_text',''),pou,
        PLCTask(loop.symbols['ob'],f'T#{loop.period_ms}ms',13,pou.name),
        test_cases=[{'test_id':'PID_START_STOP','description':'Comprobar arranque, parada y valor seguro.'}],
        metadata=metadata,pid_loops=loops)
    from pid_scl import prepare_pid_variables
    prepare_pid_variables(project,index)
    return project


def validate_native_pid_semantics(semantic: dict, io_map: dict, initial_errors: list[str]) -> dict:
    errors, clarification = list(initial_errors), None
    proposals, bindings = [], {}
    requirements = copy.deepcopy(semantic.get('functional_requirements') or [])
    try:
        # Digital needs use the same allocator as the rest of Normal mode; analog devices stay configured resources.
        from io_allocator import propose_assignment, apply_assignments
        index = build_io_map_index(io_map)
        for req in requirements:
            if req.get('type')=='pid_control' and not isinstance(req.get('resources',{}),dict):
                raise PIDConfigurationError('PID_RESOURCES','Las funciones digitales del lazo deben ser un objeto.')
        referenced = {name for req in requirements if req.get('type')=='pid_control'
                      for name in (req.get('resources') or {}).values() if isinstance(name,str)}
        missing = [name for req in requirements if req.get('type')=='pid_control'
                   for name in (req.get('resources') or {}).values() if isinstance(name,str) and name not in index]
        if missing:
            proposals = propose_assignment(io_map,[{'functional_name_hint':n,'allow_reassign':False,'reuse_by_role':True}
                                                   for n in dict.fromkeys(missing)],reserved_names=referenced & set(index))
            if any(p.get('blocked') for p in proposals):
                raise PIDConfigurationError('PID_DIGITAL_MISSING','No hay un canal digital compatible disponible para el comando.')
            provisional = apply_assignments(io_map,proposals,source='PID_VALIDATION')[0]
            bindings = {p['requested_name']:p['proposed_name'] for p in proposals if p.get('semantic_reuse')}
            for req in requirements:
                if req.get('type')=='pid_control':
                    req['resources']={k:bindings.get(v,v) for k,v in (req.get('resources') or {}).items()}
        else:
            provisional = io_map
        resolve_pid_loops(requirements,provisional,'SIEMENS_SCL_V18')
    except (PIDConfigurationError, ValueError, TypeError) as error:
        if isinstance(error,PIDConfigurationError) and error.code in {'PID_DEVICE_AMBIGUOUS','PID_DIRECTION'}:
            clarification=error.message
        else:
            errors.append(str(error))
    return {'is_valid':not errors and not clarification and not semantic.get('requires_clarification',False),
        'errors':errors,'warnings':[],'missing_parameters':[],'unauthorized_tags':[],
        'requires_clarification':bool(clarification) or bool(semantic.get('requires_clarification',False)),
        'clarification_question':clarification or semantic.get('clarification_question'),
        'functional_requirement_conflicts':[],'io_assignment_proposals':proposals,'resource_bindings':bindings}
