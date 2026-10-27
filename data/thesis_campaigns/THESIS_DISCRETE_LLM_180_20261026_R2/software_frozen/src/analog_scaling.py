"""Deterministic analog calibration at the existing IR/code-generation boundary."""
from __future__ import annotations

import copy
import math
import re
import struct
from decimal import Decimal
from typing import Any

from analog_config import analog_configuration_report, is_analog_channel
from engineering_units import canonical_unit, convert_unit


CONDITION_FIELDS = {'condition', 'mode_condition', 'run_condition', 'enable_condition', 'start_condition',
                    'advance_on', 'transition_condition', 'until', 'set', 'reset', 'count_condition'}


def _condition_entries(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from _condition_entries(item)
    elif isinstance(value, dict):
        unit = value.get('condition_unit', value.get('unit') if value.get('type') == 'conditional_output' else None)
        for key, item in value.items():
            if key in CONDITION_FIELDS and isinstance(item, str) and unit is not None:
                yield value, key, unit
            yield from _condition_entries(item)


def _real(value: float) -> float:
    try:
        result = struct.unpack('f', struct.pack('f', value))[0]
    except (OverflowError, struct.error):
        result = float('inf')
    if not math.isfinite(result):
        raise ValueError('ANALOG_REAL_RANGE: la calibración excede el tipo REAL del PLC.')
    return result


def _confirmed(entry: dict[str, Any]) -> dict[str, Any]:
    report = analog_configuration_report(entry)
    if not report['ready']:
        detail = '; '.join(report['errors']) or ', '.join(report['missing_fields']) or 'falta confirmar la calibración'
        raise ValueError(f"ANALOG_CONFIGURATION_REQUIRED: {entry['name']}: {detail}.")
    config = copy.deepcopy(entry['analog_config'])
    lo, hi = _real(config['engineering_min']), _real(config['engineering_max'])
    if lo >= hi or _real(hi - lo) <= 0:
        raise ValueError(f"ANALOG_REAL_RANGE: {entry['name']}: límites físicos indistinguibles en REAL.")
    config.update(engineering_min=lo, engineering_max=hi)
    if config.get('fault_value') is not None:
        config['fault_value'] = _real(config['fault_value'])
    return config


def _in_unit(value: Any, unit: Any, config: dict[str, Any]) -> float:
    try:
        finite = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError('ANALOG_COMMAND_VALUE: el valor debe ser un número finito.')
    target = config['engineering_unit']
    if unit is not None:
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError('ANALOG_UNIT: falta una unidad válida.')
        if canonical_unit(unit) != canonical_unit(target):
            try:
                value = convert_unit(value, unit, target)
            except ValueError as error:
                raise ValueError(f'ANALOG_UNIT: {unit!r} no se puede convertir a {target!r}.') from error
    value = _real(value)
    if not config['engineering_min'] <= value <= config['engineering_max']:
        raise ValueError(f'ANALOG_COMMAND_RANGE: {value} fuera de {config["engineering_min"]}–{config["engineering_max"]} {target}.')
    return _real(value)


def prepare_analog_bindings(requirements: list[dict[str, Any]], io_index: dict[str, dict[str, Any]],
                            used_names: list[str], reserved_names: set[str]) -> tuple[list[dict], list[dict]]:
    """Only used, explicitly configured channels opt into scaling; legacy raw logic is unchanged."""
    requirements = copy.deepcopy(requirements)
    from functional_resources import condition_identifiers
    # One sequence owns each numeric output across its mutually exclusive stages.
    # Independent sequences or standalone commands must not compete for that output.
    numeric_commands = []
    owners = {}
    numeric_hysteresis_indexes = set()
    for index, requirement in enumerate(requirements):
        if requirement.get('type') == 'analog_output':
            numeric_commands.append((requirement, ('command', index)))
        elif requirement.get('type') == 'hysteresis_switch' and (
                is_analog_channel(io_index.get(requirement.get('output'), {}))
                or any(key in requirement for key in ('on_value', 'off_value', 'output_unit'))):
            if not isinstance(requirement.get('output_unit'), str) or not requirement['output_unit'].strip():
                raise ValueError('ANALOG_UNIT: la histéresis numérica requiere output_unit.')
            numeric_hysteresis_indexes.add(index)
            for field in ('on_value', 'off_value'):
                command = {'output': requirement.get('output'), 'value': requirement.get(field),
                           'unit': requirement['output_unit']}
                numeric_commands.append((command, ('hysteresis', index, field)))
        elif requirement.get('type') == 'timed_sequence':
            for step in requirement.get('steps') or []:
                commands = step.get('analog_outputs', []) if isinstance(step, dict) else []
                if not isinstance(commands, list) or any(not isinstance(command, dict) for command in commands):
                    raise ValueError('ANALOG_COMMAND_VALUE: analog_outputs requiere órdenes numéricas por etapa.')
                stage_outputs = set()
                for command in commands:
                    name = command.get('output')
                    if isinstance(name, str) and name in stage_outputs:
                        raise ValueError(f'ANALOG_MULTIPLE_WRITERS: {name}: órdenes duplicadas en una etapa.')
                    if isinstance(name, str):
                        stage_outputs.add(name)
                    numeric_commands.append((command, ('sequence', index)))
    for command, owner in numeric_commands:
        target = command.get('output')
        if not isinstance(target, str) or not re.fullmatch(r'(?:AO|Q)_[A-Za-z0-9_]+', target):
            raise ValueError('ANALOG_COMMAND_VALUE: falta identificar la salida analógica.')
        if command.get('value') is None:
            raise ValueError(f'ANALOG_COMMAND_VALUE: {target}: falta el valor numérico.')
        owner = owner[:2]
        if target in owners and owners[target] != owner:
            raise ValueError(f'ANALOG_MULTIPLE_WRITERS: {target}: use un solo propietario por salida.')
        owners[target] = owner
    for requirement in requirements:
        if requirement.get('type') == 'analog_output':
            target = requirement.get('output')
            if not isinstance(target, str) or not re.fullmatch(r'(?:AO|Q)_[A-Za-z0-9_]+', target):
                raise ValueError('ANALOG_COMMAND_VALUE: falta identificar la salida analógica.')
            if requirement.get('value') is None:
                raise ValueError(f'ANALOG_COMMAND_VALUE: {target}: falta el valor numérico.')
            if 'condition' in requirement and (not isinstance(requirement['condition'], str)
                    or not requirement['condition'].strip() or condition_identifiers(requirement['condition']) is None):
                raise ValueError(f'ANALOG_COMMAND_CONDITION: {target}: condición no válida.')
    explicit = {str(command.get('output', '')) for command, _ in numeric_commands}
    explicit.update(str(r.get('input', r.get('analog_input', ''))) for r in requirements
                    if r.get('type') == 'hysteresis_switch' and r.get('unit') is not None)
    for container, key, _unit in _condition_entries(requirements):
        explicit.update(name for name in (condition_identifiers(container[key]) or [])
                        if is_analog_channel(io_index.get(name, {})) or name.startswith(('AI_', 'AO_')))
    bindings = []
    allocated = set(reserved_names)
    for name in dict.fromkeys(used_names):
        entry = io_index.get(name)
        if entry is None:
            continue  # the existing resource resolver handles missing physical resources
        if name not in explicit and 'analog_config' not in entry:
            continue
        if not is_analog_channel(entry):
            raise ValueError(f'ANALOG_CHANNEL_TYPE: {name} requiere AI/AO INT con dirección %IW/%QW.')
        config = _confirmed(entry)
        engineering, valid = f'M_{name}_EU', f'M_{name}_Valid'
        if len(engineering) > 100 or allocated.intersection((engineering, valid)):
            raise ValueError(f'ANALOG_VARIABLE_COLLISION: {name}: nombres auxiliares ocupados o demasiado largos.')
        raw = f'M_{name}_RawCommand'
        if entry['class'] == 'output' and (len(raw) > 100 or raw in allocated):
            raise ValueError(f'ANALOG_VARIABLE_COLLISION: {name}: auxiliar raw ocupado o demasiado largo.')
        allocated.update((engineering, valid, raw))
        bindings.append({'name': name, 'direction': entry['class'], 'location': entry['location'],
                         'engineering_variable': engineering, 'valid_variable': valid, 'raw_variable': raw, 'config': config})
    by_name = {binding['name']: binding for binding in bindings}
    for container, key, unit in _condition_entries(requirements):
        for name, binding in by_name.items():
            number = r'(-?\d+(?:\.\d+)?)'
            tag = rf'\b{re.escape(name)}\b'
            operator = r'(<=|>=|<>|<|>|=)'
            def right(match):
                value = _in_unit(float(match.group(2)), unit, binding['config'])
                return f'{name} {match.group(1)} {format(Decimal(str(value)), "f")}'
            def left(match):
                value = _in_unit(float(match.group(1)), unit, binding['config'])
                return f'{format(Decimal(str(value)), "f")} {match.group(2)} {name}'
            text = re.sub(tag + r'\s*' + operator + r'\s*' + number, right, container[key])
            container[key] = re.sub(number + r'\s*' + operator + r'\s*' + tag, left, text)
    seen_outputs = set()
    for requirement, _owner in numeric_commands:
        name = str(requirement.get('output', ''))
        binding = by_name.get(name)
        if binding is None:
            if name in io_index:
                raise ValueError(f'ANALOG_CONFIGURATION_REQUIRED: {name}: configure la salida analógica.')
            continue
        if binding['direction'] != 'output':
            raise ValueError(f'ANALOG_CHANNEL_TYPE: {name} no es una salida analógica.')
        seen_outputs.add(name)
        requirement['value'] = _in_unit(requirement.get('value'), requirement.get('unit'), binding['config'])
        requirement['unit'] = binding['config']['engineering_unit']
        if _owner[0] == 'hysteresis':
            parent = requirements[_owner[1]]
            # Keep the two commands distinct; neither may fall back to a BOOL.
            field = _owner[2]
            parent[field] = requirement['value']
            parent['output_unit'] = requirement['unit']
    for requirement in requirements:
        if requirement.get('type') == 'hysteresis_switch':
            name = str(requirement.get('input', requirement.get('analog_input', '')))
            if name in by_name:
                if by_name[name]['direction'] != 'input':
                    raise ValueError(f'ANALOG_CHANNEL_TYPE: {name} no es una entrada analógica.')
                for key in ('on_above', 'off_below', 'on_below', 'off_above'):
                    if requirement.get(key) is not None:
                        requirement[key] = _in_unit(requirement[key], requirement.get('unit'), by_name[name]['config'])
                requirement['unit'] = by_name[name]['config']['engineering_unit']
    for binding in bindings:
        _check_input_comparisons(requirements, binding['name'], io_index)
        if binding['direction'] == 'output':
            if binding['name'] not in seen_outputs:
                raise ValueError(f"ANALOG_OUTPUT_COMMAND_REQUIRED: {binding['name']}: indique una orden numérica y su unidad.")
            for requirement_index, requirement in enumerate(requirements):
                # force_off is a safety override, rendered with the configured numeric safe value.
                check = copy.deepcopy(requirement)
                if check.get('type') == 'timed_sequence':
                    for step in check.get('steps') or []:
                        if isinstance(step, dict):
                            step.pop('analog_outputs', None)
                numeric_hysteresis = requirement_index in numeric_hysteresis_indexes
                if check.get('type') not in {'analog_output', 'force_off', 'emergency_priority'} and not numeric_hysteresis and _mentions_output(check, binding['name']):
                    raise ValueError(f"ANALOG_OUTPUT_COMMAND_REQUIRED: {binding['name']}: una salida analógica no admite órdenes booleanas.")
    return bindings, requirements


def _check_input_comparisons(value: Any, name: str, io_index: dict) -> None:
    if isinstance(value, list):
        for item in value:
            _check_input_comparisons(item, name, io_index)
    elif isinstance(value, dict):
        for key, item in value.items():
            message = f'ANALOG_INPUT_COMPARISON_REQUIRED: {name}: compare con un valor numérico en unidades físicas.'
            if (key.endswith('input') or key == 'input') and item == name and value.get('type') != 'hysteresis_switch':
                raise ValueError(message)
            if key in CONDITION_FIELDS and isinstance(item, str):
                for match in re.finditer(rf'\b{re.escape(name)}\b', item):
                    before, after = item[:match.start()].rstrip(), item[match.end():].lstrip()
                    operand = r'(-?\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*)'
                    right = re.match(r'(?:<=|>=|<>|<|>|=)\s*' + operand, after)
                    left = re.search(operand + r'\s*(?:<=|>=|<>|<|>|=)$', before)
                    other = (right or left)
                    if other is None:
                        raise ValueError(message)
                    other = other.group(1)
                    if not re.fullmatch(r'-?\d+(?:\.\d+)?', other):
                        entry = io_index.get(other, {})
                        if entry.get('type') not in {'REAL', 'INT'}:
                            raise ValueError(message)
                        config = entry.get('analog_config')
                        own = io_index[name]['analog_config']
                        if isinstance(config, dict) and canonical_unit(config.get('engineering_unit', '')) != canonical_unit(own['engineering_unit']):
                            raise ValueError(f'ANALOG_UNIT: {name} y {other} requieren unidades físicas iguales en esta comparación.')
            _check_input_comparisons(item, name, io_index)


def _mentions_output(value: Any, name: str) -> bool:
    if isinstance(value, list):
        return any(_mentions_output(item, name) for item in value)
    if isinstance(value, dict):
        return any((key in {'output', 'outputs', 'target', 'affected_outputs', 'output_a', 'output_b'} and
                    (item == name or isinstance(item, list) and name in item)) or _mentions_output(item, name)
                   for key, item in value.items())
    return False


def real_literal(value: float) -> str:
    text = repr(float(value))
    return text if '.' in text or 'e' in text.lower() else text + '.0'


def apply_analog_scaling(project_ir: Any, body: str) -> str:
    bindings = project_ir.metadata.get('analog_bindings', [])
    if not bindings:
        return body
    prefix, suffix, inhibit = [], [], []
    for binding in bindings:
        name, eu, valid, config = (binding[key] for key in ('name', 'engineering_variable', 'valid_variable', 'config'))
        body = re.sub(rf'\b{re.escape(name)}\b', eu, body)
        low, high = real_literal(config['engineering_min']), real_literal(config['engineering_max'])
        rlow, rhigh = int(config['raw_min']), int(config['raw_max'])
        espan, rspan = real_literal(config['engineering_max'] - config['engineering_min']), real_literal(rhigh - rlow)
        if binding['direction'] == 'input':
            prefix += [f'(* Escalamiento de {name}: raw a unidades físicas; validez por rango nominal *)',
                       f'{valid} := ({name} >= {rlow}) AND ({name} <= {rhigh});',
                       f'IF {valid} THEN',
                       f'    {eu} := ((INT_TO_REAL({name}) - {real_literal(rlow)}) / {rspan}) * {espan} + {low};',
                       'ELSE', f'    {eu} := {real_literal(config.get("fault_value") if config["fault_action"] == "SUBSTITUTE_VALUE" else config["engineering_min"])};',
                       'END_IF;']
            if config['fault_action'] == 'INHIBIT_CONTROL':
                inhibit.append(f'NOT {valid}')
        else:
            safe = real_literal(config['fault_value'])
            # Comparison conjunction also rejects NaN; infinity is out of range.
            suffix += [f'(* Escalamiento de {name}: unidades físicas a raw INT *)',
                       f'{valid} := ({eu} >= {low}) AND ({eu} <= {high});',
                       f'IF NOT {valid} THEN', f'    {eu} := {safe};', 'END_IF;',
                       f"{binding['raw_variable']} := (({eu} - {low}) / {espan}) * {rspan} + {real_literal(rlow)};",
                       f"IF {binding['raw_variable']} <= {real_literal(rlow)} THEN", f'    {name} := {rlow};',
                       f"ELSIF {binding['raw_variable']} >= {real_literal(rhigh)} THEN", f'    {name} := {rhigh};',
                       'ELSE', f"    {name} := REAL_TO_INT({binding['raw_variable']});", 'END_IF;']
    if inhibit:
        suffix = [f"IF {' OR '.join(inhibit)} THEN", *[
            f"    {v.name} := FALSE;" for v in project_ir.pou.variables if v.var_class == 'output' and v.data_type == 'BOOL'
            and not getattr(project_ir,'pid_loops',[])],
            *[f"    {b['engineering_variable']} := {real_literal(b['config']['fault_value'])};" for b in bindings if b['direction'] == 'output'],
            *(['    PID_Enable := FALSE;'] if any(v.name == 'PID_Enable' for v in project_ir.pou.variables) else []),
            'END_IF;', *suffix]
    return '\n'.join(prefix) + '\n' + body.rstrip() + '\n' + '\n'.join(suffix) + '\n'
