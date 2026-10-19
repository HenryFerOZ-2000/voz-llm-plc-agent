"""Frozen product identity, separate from historical benchmark semantics."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

CONTRACT_FILE = 'product_contract.json'
NATIVE_FILES = ('pid_infrastructure.json', 'pid_process_bindings.json', 'pid_cyclic_ob.xml')
IDENTITY_FILE = 'generation_metadata.json'
KINDS = {'DISCRETE_OR_SUPERVISORY', 'NATIVE_PID'}
NATIVE_EVALUATION_UNSUPPORTED = 'NATIVE_PID_EXPERIMENT_EVALUATION_UNSUPPORTED'
NATIVE_PENDING_LABEL = 'Evaluaci\u00f3n PID nativa pendiente de soporte'


def evaluation_capability(contract: dict | None) -> dict:
    if contract is not None and contract.get('package_kind') not in KINDS:
        _fail('tipo de paquete desconocido.')
    if contract and contract['package_kind'] == 'NATIVE_PID':
        return {'supported': False, 'code': NATIVE_EVALUATION_UNSUPPORTED, 'reason': NATIVE_PENDING_LABEL}
    return {'supported': True, 'code': None, 'reason': None}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _fail(message):
    raise ValueError('PRODUCT_CONTRACT: ' + message)


def _native_source(path):
    # Native declaration, not a case name, comment or historical supervisor.
    text = Path(path).read_text(encoding='utf-8')
    if '(* NATIVE_PID_BEGIN *)' in text:
        return True
    text = re.sub(r'/\*.*?\*/|\(\*.*?\*\)|//[^\n]*', '', text, flags=re.S)
    return bool(re.search(r':\s*"?PID_Compact"?\b', text, re.I))


def build_product_contract(record: dict, package_dir: Path) -> dict:
    from product_engine import ENGINE_ID, MAP_POLICY
    from pid_package import validate_pid_manifest

    package_dir = Path(package_dir)
    metadata = _read(package_dir / IDENTITY_FILE)
    identity = metadata.get('product_engine')
    if identity != record.get('product_engine') or identity != {'schema_version': 1, 'engine_id': ENGINE_ID}:
        _fail('identidad del paquete y del ensayo ausente o distinta.')
    if (record.get('io_map') or {}).get('map_policy') != MAP_POLICY:
        _fail('falta la politica del mapa declarado.')
    present = [name for name in NATIVE_FILES if (package_dir / name).is_file()]
    native = _native_source(package_dir / 'siemens_source.scl')
    if bool(present) != native or (present and len(present) != len(NATIVE_FILES)):
        _fail('infraestructura PID nativa incompleta o incoherente con la fuente.')
    if native:
        manifest = _read(package_dir / NATIVE_FILES[0])
        loop = validate_pid_manifest(manifest)
        if manifest.get('cyclic_ob_file') != NATIVE_FILES[2]:
            _fail('XML ciclico fuera del contrato.')
        bindings = _read(package_dir / NATIVE_FILES[1])
        if not isinstance(bindings, dict) or bindings.get('instance_db') != loop['symbols']['db']:
            _fail('bindings PID ausentes.')
        source = (package_dir / 'siemens_source.scl').read_text(encoding='utf-8')
        if not re.search(r'"' + re.escape(loop['symbols']['controller']) + r'"\s*\(', source):
            _fail('la fuente no llama al controlador declarado.')
    return {
        'schema_version': 1, 'engine_id': identity['engine_id'], 'map_policy': MAP_POLICY,
        'interaction_policy': 'UNANSWERED_CLARIFICATION' if record.get('batch_id') else 'INTERACTIVE_CLARIFICATION',
        'package_kind': 'NATIVE_PID' if native else 'DISCRETE_OR_SUPERVISORY',
        'files': {name: _hash(package_dir / name) for name in (IDENTITY_FILE, *present)},
    }


def freeze_product_contract(trial_dir: Path, package_dir: Path | None, record: dict, *,
                            native_protocol: dict | None = None, plant_profile: dict | None = None) -> dict:
    """No retroactive identity. Only new product generation creates a contract."""
    trial_dir = Path(trial_dir)
    package = Path(package_dir) if package_dir is not None else None
    metadata = _read(package / IDENTITY_FILE) if package and (package / IDENTITY_FILE).is_file() else {}
    if not record.get('product_engine') and not metadata.get('product_engine'):
        if _native_source(trial_dir / 'program.scl') or (package and any((package / n).exists() for n in NATIVE_FILES)):
            _fail('paquete nativo sin identidad del producto.')
        return {}
    if package is None:
        _fail('falta el paquete original de la nueva generacion.')
    contract = build_product_contract(record, package)
    if native_protocol is not None or plant_profile is not None:
        if contract['package_kind'] != 'NATIVE_PID' or native_protocol is None or plant_profile is None:
            _fail('el protocolo requiere paquete nativo y perfil completo.')
        from trial_experiments.native_pid_protocol import freeze_native_evaluation
        native = freeze_native_evaluation(trial_dir, package, native_protocol, plant_profile)
        contract.update(schema_version=2, native_evaluation=native)
        contract['files'] = native['files']
    for name in contract['files']:
        if contract['schema_version'] == 1:
            shutil.copyfile(package / name, trial_dir / name)
    (trial_dir / CONTRACT_FILE).write_text(json.dumps(contract, indent=2, ensure_ascii=False), encoding='utf-8')
    return contract


def verify_product_contract(trial_dir: Path, record: dict, manifest: dict) -> dict | None:
    """Validate existing evidence only, without filling missing identity fields."""
    trial_dir = Path(trial_dir)
    files = manifest.get('files') or {}
    path = trial_dir / CONTRACT_FILE
    required = bool(record.get('product_engine') or manifest.get('product_engine') or CONTRACT_FILE in files or path.exists())
    native_evidence = any((trial_dir / name).exists() for name in NATIVE_FILES) or _native_source(trial_dir / 'program.scl')
    if not required:
        if native_evidence:
            _fail('evidencia nativa sin contrato.')
        return None
    if not path.is_file() or CONTRACT_FILE not in files:
        _fail('falta el contrato congelado o su hash.')
    c = _read(path)
    from product_engine import ENGINE_ID, MAP_POLICY
    identity = {'schema_version': 1, 'engine_id': ENGINE_ID}
    if (c.get('schema_version') not in (1,2) or c.get('engine_id') != ENGINE_ID or c.get('map_policy') != MAP_POLICY
            or c.get('package_kind') not in KINDS or record.get('product_engine') != identity
            or manifest.get('product_engine') != identity or (record.get('io_map') or {}).get('map_policy') != MAP_POLICY):
        _fail('identidad o version incoherente.')
    policy = 'UNANSWERED_CLARIFICATION' if record.get('batch_id') else 'INTERACTIVE_CLARIFICATION'
    if c.get('interaction_policy') != policy:
        _fail('politica de interaccion incoherente.')
    expected_files = {IDENTITY_FILE} | (set(NATIVE_FILES) if c['package_kind'] == 'NATIVE_PID' else set())
    if c['schema_version'] == 2:
        from trial_experiments.native_pid_protocol import FROZEN_FILES, validate_native_protocol, PROTOCOL_ID
        from pid_package import validate_pid_manifest
        native = c.get('native_evaluation') or {}
        if (c['package_kind'] != 'NATIVE_PID' or native.get('protocol_id') != PROTOCOL_ID
                or native.get('files') != c.get('files')):
            _fail('contrato nativo v2 incompleto.')
        expected_files = set(FROZEN_FILES)
        try:
            loop = validate_pid_manifest(_read(trial_dir/'pid_infrastructure.json'))
            validate_native_protocol(_read(trial_dir/'native_eval_protocol.json'),loop,_read(trial_dir/'plant_profile.json'))
            if native.get('configuration_hash') != loop['configuration_hash']:
                _fail('configuración nativa distinta.')
        except (ValueError, KeyError, TypeError, OSError) as error:
            _fail(str(error))
    if not isinstance(c.get('files'), dict) or set(c['files']) != expected_files:
        _fail('lista incompleta de artefactos de identidad.')
    if native_evidence != (c['package_kind'] == 'NATIVE_PID'):
        _fail('tipo del paquete no coincide con sus artefactos.')
    for name, expected in c['files'].items():
        target = trial_dir / name
        if (name not in files or files[name] != expected or not target.is_file() or target.is_symlink()
                or target.resolve().parent != trial_dir.resolve() or _hash(target) != expected):
            _fail('artefacto de identidad ausente o cambiado: ' + name)
    if _read(trial_dir / IDENTITY_FILE).get('product_engine') != identity:
        _fail('metadata del generador incoherente.')
    return c
