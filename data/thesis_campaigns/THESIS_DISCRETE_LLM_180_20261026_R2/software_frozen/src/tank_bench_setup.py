"""Prepare two existing analog devices; never allocate or reserve digital channels."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from plc_maps.map_validator import validate_plc_variable_map


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=-5))).isoformat(timespec='seconds')


def prepare_tank_bench(io_map: dict) -> dict:
    if (io_map.get('metadata') or {}).get('map_id') != 'mapa_banco_fisico':
        raise ValueError('TANK_MAP_ID: seleccione el banco físico S7-1500 esperado.')
    result = copy.deepcopy(io_map)
    selected = [('%IW4', 'AI_Level_Raw', 'input', 'SENSOR', 'Nivel', 'Transmisor de nivel'),
                ('%QW4', 'AO_Fill_Command', 'output', 'PROPORTIONAL_VALVE', 'Apertura', 'Válvula proporcional de llenado')]
    names = {v.get('name') for v in result.get('variables', [])}
    for address, name, cls, device, quantity, label in selected:
        matches = [v for v in result['variables'] if v.get('location') == address]
        if len(matches) != 1:
            raise ValueError(f'TANK_CHANNEL_CONFLICT: {address}: canal ausente o duplicado.')
        entry = matches[0]
        if (entry.get('state') != 'FREE' or 'analog_config' in entry or entry.get('type') != 'INT'
                or entry.get('class') != cls or (name in names and entry.get('name') != name)):
            raise ValueError(f'TANK_CHANNEL_CONFLICT: {address}: tiene una función/configuración existente o tipo incompatible.')
        result.setdefault('history', []).append({'timestamp': _now(), 'address': address,
            'old_name':entry['name'], 'new_name':name, 'old_state':entry['state'], 'new_state':'ASSIGNED',
            'source':'MANUAL_EDITOR', 'reason':'Preparación de dispositivo de tanque solicitada por el investigador.'})
        entry.update(name=name, state='ASSIGNED', llm_allowed=True, assignment_source='MANUAL_EDITOR',
                     semantic_role='LEVEL_SENSOR' if cls=='input' else 'FILL_VALVE', description=label,
                     analog_config={'schema_version':1, 'confirmed':False, 'configuration_basis':'ASSUMED_FOR_TEST',
                        'device_kind':device, 'device_name':label, 'quantity':quantity, 'signal_type':'4-20mA',
                        'electrical_min':4.0, 'electrical_max':20.0, 'raw_min':0, 'raw_max':27648,
                        'engineering_min':0.0, 'engineering_max':100.0, 'engineering_unit':'%',
                        'fault_action':'INHIBIT_CONTROL' if cls=='input' else 'SAFE_VALUE',
                        'fault_value':None if cls=='input' else 0.0})
    result['metadata'].update(updated_at=_now(), version=int(result['metadata'].get('version', 1))+1,
        tank_setup={'configuration_basis':'ASSUMED_FOR_TEST', 'hardware_confirmed':False,
                    'prepared_addresses':['%IW4','%QW4']})
    report = validate_plc_variable_map(result)
    if not report['is_valid']:
        raise ValueError('TANK_MAP_INVALID: '+'; '.join(report['errors']))
    return result


def save_tank_bench(path: Path, expected_sha256: str, backup_root: Path) -> dict:
    path, backup_root = Path(path), Path(backup_root)
    before = path.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    if digest != expected_sha256:
        raise ValueError('MAP_CHANGED: el mapa cambió; vuelva a cargarlo antes de preparar los dispositivos.')
    candidate = prepare_tank_bench(json.loads(before.decode('utf-8-sig')))
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f'{path.stem}_{uuid.uuid4().hex}.json'
    with backup.open('xb') as handle:
        handle.write(before)
    if hashlib.sha256(backup.read_bytes()).hexdigest() != digest:
        raise OSError('TANK_BACKUP_FAILED: no coincide la copia del mapa.')
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix=path.name+'.', suffix='.tmp',
                                         dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            json.dump(candidate, handle, ensure_ascii=False, indent=2)
            handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        # External editors do not share a lock: detects changes up to this check, not an OS compare-and-swap.
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('MAP_CHANGED: otra ventana guardó el mapa; no se aplicó la propuesta.')
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return {'map_path':str(path), 'backup_path':str(backup), 'before_sha256':digest,
            'after_sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'changed_addresses':['%IW4','%QW4']}
