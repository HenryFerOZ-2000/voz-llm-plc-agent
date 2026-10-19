"""Explicit map-owned process connections, independent of execution destination."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import struct

from analog_config import analog_configuration_report, is_analog_channel
from engineering_units import canonical_unit, compatible_unit

IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}\Z')
ROLES = {'MEASUREMENT', 'MANIPULATED'}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def process_configuration_report(entry: dict) -> dict:
    errors = []
    report = {'errors': errors, 'warnings': [], 'is_valid': True}
    if 'process_config' not in entry:
        return report
    prefix = f"{entry.get('name', 'Señal')}: process_config"

    def error(field, reason):
        errors.append(f'{prefix}.{field}: {reason}.')

    config = entry['process_config']
    if not isinstance(config, dict):
        error('', 'debe ser un objeto')
    else:
        if entry.get('class') != 'internal' or entry.get('type') != 'REAL' or entry.get('location'):
            error('storage', 'requiere señal internal REAL sin dirección física')
        if 'analog_config' in entry:
            error('storage', 'no admite también analog_config')
        if type(config.get('schema_version')) is not int or config['schema_version'] != 1:
            error('schema_version', 'requiere versión 1')
        role = config.get('role')
        if not isinstance(role, str) or role not in ROLES:
            error('role', 'requiere MEASUREMENT o MANIPULATED')
        for field in ('quantity', 'engineering_unit'):
            if not isinstance(config.get(field), str) or not config[field].strip():
                error(field, 'texto obligatorio')
        if isinstance(config.get('quantity'), str) and isinstance(config.get('engineering_unit'), str):
            if not compatible_unit(config['quantity'], config['engineering_unit']):
                error('engineering_unit', 'incompatible con quantity')
        for field in ('engineering_min', 'engineering_max'):
            if not _finite(config.get(field)):
                error(field, 'requiere número finito')
        low, high = config.get('engineering_min'), config.get('engineering_max')
        if _finite(low) and _finite(high) and low >= high:
            error('engineering_min', 'debe ser menor que engineering_max')
        storage = config.get('storage')
        if not isinstance(storage, dict):
            error('storage', 'requiere un objeto')
            storage = {}
        if storage.get('kind') != 'GENERATED_DB':
            error('storage.kind', 'solo admite GENERATED_DB')
        for field in ('db', 'member'):
            value = storage.get(field)
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                error('storage.' + field, 'identificador Siemens inválido')
        if role == 'MEASUREMENT':
            valid = config.get('validity_member')
            if not isinstance(valid, str) or not IDENTIFIER.fullmatch(valid):
                error('validity_member', 'identificador BOOL obligatorio, inicialmente FALSE')
            elif valid.casefold() == str(storage.get('member')).casefold():
                error('validity_member', 'debe ser distinto del miembro REAL')
        elif role == 'MANIPULATED':
            fault = config.get('fault_value')
            if not _finite(fault) or _finite(low) and fault < low or _finite(high) and fault > high:
                error('fault_value', 'requiere número finito dentro del rango')
    report['is_valid'] = not errors
    return report


def normalize_process_binding(entry: dict, role: str) -> dict:
    if role not in ROLES:
        raise ValueError('PID_DEVICE: role inválido.')
    name = entry.get('name', '?')
    if entry.get('llm_allowed', True) is not True:
        raise ValueError(f'PID_DEVICE_PERMISSION: {name} no está autorizado.')
    if 'process_config' in entry:
        report = process_configuration_report(entry)
        if report['errors']:
            raise ValueError('PID_PROCESS_CONFIG: ' + '; '.join(report['errors']))
        config = copy.deepcopy(entry['process_config'])
        if config['role'] != role:
            raise ValueError(f'PID_DEVICE: {name} no tiene role={role}.')
        binding = {'representation': 'DB_ENGINEERING', 'data_type': 'REAL', 'storage': config['storage']}
        key = 'validity_member' if role == 'MEASUREMENT' else 'fault_value'
        binding[key] = config[key]
        provenance = 'MAP_PROCESS_CONFIG'
    else:
        expected = 'input' if role == 'MEASUREMENT' else 'output'
        if not is_analog_channel(entry) or entry.get('class') != expected:
            raise ValueError(f'PID_DEVICE: {name} requiere canal analógico {expected} o process_config.')
        report = analog_configuration_report(entry)
        if 'analog_config' not in entry or report['errors'] or report['missing_fields']:
            detail = '; '.join(report['errors'] + report['missing_fields']) or 'analog_config'
            raise ValueError(f'PID_CALIBRATION_INCOMPLETE: {name}: {detail}.')
        config = copy.deepcopy(entry['analog_config'])
        binding = {'representation': 'HARDWARE_RAW', 'data_type': 'INT',
                   'address': entry['location'].upper(), 'analog_config': config}
        provenance = config.get('configuration_basis', config.get('provenance', config.get('source', 'MAP_ANALOG_CONFIG')))
    try:
        low, high = (struct.unpack('f', struct.pack('f', config[k]))[0] for k in ('engineering_min', 'engineering_max'))
        span = struct.unpack('f', struct.pack('f', high-low))[0]
        valid_range = math.isfinite(low) and math.isfinite(high) and math.isfinite(span) and low < high
    except (OverflowError, struct.error):
        valid_range = False
    if not valid_range:
        raise ValueError(f'PID_REAL_RANGE: {name}: engineering_min/max no forman un rango REAL finito y distinguible.')
    binding.update(schema_version=1, name=name, role=role, quantity=config['quantity'],
                   unit=canonical_unit(config['engineering_unit']), engineering_min=config['engineering_min'],
                   engineering_max=config['engineering_max'], permission=True, provenance=provenance)
    return binding


def validate_process_storage(bindings: list[dict]) -> list[str]:
    """Reject aliases/quality sharing storage, even with different capitalization."""
    seen, errors, db_names = {}, [], {}
    for binding in bindings:
        if binding.get('representation') != 'DB_ENGINEERING':
            continue
        storage = binding['storage']
        db_key=storage['db'].casefold()
        if db_key in db_names and db_names[db_key]!=storage['db']:
            errors.append(f"PID_STORAGE_CONFLICT: {storage['db']}: use la misma escritura del DB {db_names[db_key]}.")
        db_names[db_key]=storage['db']
        for member in [storage['member']] + ([binding['validity_member']] if binding['role'] == 'MEASUREMENT' else []):
            path = storage['db'] + '.' + member
            key = path.casefold()
            if key in seen:
                errors.append(f'PID_STORAGE_CONFLICT: {path} ya declarado por {seen[key]}.')
            seen[key] = binding['name']
    return errors


def process_db_descriptors(bindings: list[dict], owner: str) -> list[dict]:
    """One canonical owned DB inventory for generation and package validation."""
    errors=validate_process_storage(bindings)
    if errors:raise ValueError('; '.join(errors))
    groups = {}
    for binding in bindings:
        if binding['representation'] != 'DB_ENGINEERING':
            continue
        storage = binding['storage']
        group = groups.setdefault(storage['db'].casefold(), {'db': storage['db'], 'owner': owner, 'members': []})
        group['members'].append({'name': storage['member'], 'data_type': 'REAL',
            'initial': 0.0 if binding['role'] == 'MEASUREMENT' else binding['fault_value'], 'role': binding['role']})
        if binding['role'] == 'MEASUREMENT':
            group['members'].append({'name': binding['validity_member'], 'data_type': 'BOOL', 'initial': False, 'role': 'QUALITY'})
    for group in groups.values():
        group['configuration_hash'] = hashlib.sha256(json.dumps(group, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return list(groups.values())
