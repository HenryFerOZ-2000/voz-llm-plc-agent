"""Frozen, explicit tank acceptance contracts; independent from P01–P12 Oracles."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import uuid
from pathlib import Path

from pid_package import validate_pid_manifest
from pid_tank_model import TankModel
from product_engine import ENGINE_ID

PROTOCOL_ID = 'PID_TANK_LEVEL_V1'
PACKAGE_FILES = {'program.scl':'siemens_source.scl', 'variables.json':'variables.json',
    'generation_io_map.json':'generation_io_map.json', 'generation_metadata.json':'generation_metadata.json',
    'verification.json':'verification.json', 'pid_infrastructure.json':'pid_infrastructure.json',
    'pid_process_bindings.json':'pid_process_bindings.json', 'pid_cyclic_ob.xml':'pid_cyclic_ob.xml'}
FROZEN_FILES = frozenset(PACKAGE_FILES) | {'plant_profile.json', 'native_eval_protocol.json'}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _file(directory: Path, name: str) -> Path:
    path = directory/name
    if (name not in FROZEN_FILES or path.is_symlink() or not path.is_file()
            or path.resolve().parent != directory.resolve()):
        raise ValueError('PID_BUNDLE_INTEGRITY: archivo ausente o fuera del paquete: '+name)
    return path


def validate_native_protocol(protocol: dict, loop: dict, profile: dict) -> dict:
    p = copy.deepcopy(protocol)
    if (p.get('schema_version') != 1 or p.get('protocol_id') != PROTOCOL_ID
            or p.get('tuning_policy') not in {'REQUIRE_PRETUNE', 'REUSE_VERIFIED'}):
        raise ValueError('PID_PROTOCOL: versión, alcance o política no soportados.')
    if p['tuning_policy'] == 'REQUIRE_PRETUNE' and p.get('tuning_authorized') is not True:
        raise ValueError('PID_PROTOCOL: falta autorización explícita para presintonizar.')
    if loop.get('unit') != '%' or loop.get('direction') != 'FILL' or 'input_binding' not in loop:
        raise ValueError('PID_PROTOCOL: requiere lazo nativo v2 de nivel %, dirección FILL.')
    if p.get('setpoints') != [50,40,60]:
        raise ValueError('PID_PROTOCOL: las consignas de esta versión son 50/40/60 %.')
    for key, expected in [('tolerance',2),('hold_seconds',10),('deadline_seconds',300)]:
        value = p.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or value != expected:
            raise ValueError('PID_PROTOCOL: criterio incompatible: '+key)
    for key in ('period_s','duration_s'):
        value = profile.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
            raise ValueError('PID_PROTOCOL: perfil sin tiempo válido: '+key)
    if profile.get('direction','FILL') != 'FILL' or profile['period_s'] != 0.1 or profile['duration_s'] < 1300:
        raise ValueError('PID_PROTOCOL: modelo FILL de 100 ms y duración suficiente requerido.')
    try:
        TankModel(profile, loop['input_binding'], loop['output_binding'])
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError('PID_PROTOCOL: '+str(error)) from error
    if (loop['input_binding'].get('engineering_min'),loop['input_binding'].get('engineering_max')) != (0,100):
        raise ValueError('PID_PROTOCOL: esta versión requiere medición de 0–100 %.')
    return p


def freeze_native_evaluation(trial_dir: Path, package_dir: Path, protocol: dict, profile: dict) -> dict:
    destination, package = Path(trial_dir), Path(package_dir).resolve()
    manifest = _read(package/'pid_infrastructure.json')
    loop = validate_pid_manifest(manifest)
    normalized = validate_native_protocol(protocol, loop, profile)
    if _read(package/'verification.json').get('is_valid') is not True:
        raise ValueError('PID_BUNDLE_INTEGRITY: generación sin verificación válida.')
    identity = _read(package/'generation_metadata.json').get('product_engine')
    if identity != {'schema_version':1,'engine_id':ENGINE_ID}:
        raise ValueError('PID_BUNDLE_INTEGRITY: identidad del motor ausente.')
    sources = {}
    for target, source in PACKAGE_FILES.items():
        path = package/source
        if path.is_symlink() or not path.is_file() or path.resolve().parent != package:
            raise ValueError('PID_BUNDLE_INTEGRITY: archivo original inválido: '+source)
        sources[target] = path.read_bytes()
    destination.mkdir(parents=True, exist_ok=True)
    for target, content in sources.items():
        out = destination/target
        if out.is_symlink() or out.resolve().parent != destination.resolve():
            raise ValueError('PID_BUNDLE_INTEGRITY: destino externo.')
        out.write_bytes(content)
    _save(destination/'native_eval_protocol.json', normalized)
    _save(destination/'plant_profile.json', copy.deepcopy(profile))
    return {'schema_version':1, 'protocol_id':PROTOCOL_ID, 'protocol_file':'native_eval_protocol.json',
            'plant_profile_file':'plant_profile.json', 'configuration_hash':loop['configuration_hash'],
            'files':{name:_sha(_file(destination,name)) for name in sorted(FROZEN_FILES)}}


def create_native_validation_run(project_root: Path, package_dir: Path, protocol: dict,
                                 profile: dict, output_root: Path) -> Path:
    run_id = 'NPID_'+uuid.uuid4().hex[:12]
    directory = Path(output_root)/run_id
    if directory.exists():
        raise ValueError('PID_BUNDLE_INTEGRITY: ejecución ya existente.')
    native = freeze_native_evaluation(directory, package_dir, protocol, profile)
    record = {'schema_version':1, 'run_id':run_id, 'domain':'NATIVE_PID_DEVELOPMENT',
              'phase':'DEVELOPMENT_VALIDATION', 'native_evaluation':native,
              'product_engine':{'schema_version':1,'engine_id':ENGINE_ID},
              'files':native['files'], 'generation_package_reference':str(Path(package_dir).resolve()),
              'status':'GENERATED', 'evaluation':{'status':'PENDING','attempts':[]}}
    _save(directory/'native_run.json', record)
    verify_native_run(directory)
    return directory


def verify_native_run(run_dir: Path) -> dict:
    directory = Path(run_dir).resolve()
    try:
        record = _read(directory/'native_run.json')
        if (record.get('schema_version') != 1 or record.get('domain') != 'NATIVE_PID_DEVELOPMENT'
                or record.get('phase') != 'DEVELOPMENT_VALIDATION' or 'case_id' in record
                or record.get('product_engine') != {'schema_version':1,'engine_id':ENGINE_ID}
                or set(record.get('files',{})) != FROZEN_FILES):
            raise ValueError('registro o archivos incoherentes')
        for name, expected in record['files'].items():
            if _sha(_file(directory, name)) != expected:
                raise ValueError('hash distinto: '+name)
        if record['native_evaluation'].get('files') != record['files']:
            raise ValueError('inventarios de identidad distintos')
        manifest = _read(directory/'pid_infrastructure.json')
        loop = validate_pid_manifest(manifest)
        validate_native_protocol(_read(directory/'native_eval_protocol.json'), loop, _read(directory/'plant_profile.json'))
        bindings = _read(directory/'pid_process_bindings.json')
        if bindings.get('instance_db') != loop['symbols']['db'] or bindings.get('schema_version') != 2:
            raise ValueError('bindings de otra instancia o versión')
        if record['native_evaluation'].get('configuration_hash') != loop['configuration_hash']:
            raise ValueError('configuración del lazo distinta')
        if _read(directory/'verification.json').get('is_valid') is not True:
            raise ValueError('generación no verificada')
        return record
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
        raise ValueError('PID_BUNDLE_INTEGRITY: '+str(error)) from error


def build_native_trial_request(trial_dir: Path, workspace: Path, contract: dict) -> dict:
    directory, workspace = Path(trial_dir).resolve(), Path(workspace).resolve()
    record = verify_native_run(directory)
    if record != contract or workspace.is_relative_to(directory):
        raise ValueError('PID_BUNDLE_INTEGRITY: identidad o staging incompatible.')
    staging = workspace/'b'
    staging.mkdir(parents=True, exist_ok=False)
    for name in FROZEN_FILES:
        target = 'siemens_source.scl' if name == 'program.scl' else name
        (staging/target).write_bytes(_file(directory,name).read_bytes())
    native = {'pid_manifest':_read(staging/'pid_infrastructure.json'),
              'pid_manifest_path':str(staging/'pid_infrastructure.json'),
              'pid_bindings_path':str(staging/'pid_process_bindings.json'),
              'pid_cyclic_ob_path':str(staging/'pid_cyclic_ob.xml'),
              'pid_source_sha256':_sha(staging/'siemens_source.scl'),
              'pid_cyclic_ob_sha256':_sha(staging/'pid_cyclic_ob.xml'),
              'pid_manifest_sha256':_sha(staging/'pid_infrastructure.json'),
              'pid_bindings_sha256':_sha(staging/'pid_process_bindings.json')}
    return {'source_path':str(staging/'siemens_source.scl'), 'source_name':'siemens_source.scl',
            'native_pid':native, 'pid_project_mode':'EXPERIMENT_COPY', 'execution_package':str(staging)}


def evaluate_native_trial(project_root: Path, trial_dir: Path, *, cancel=None) -> dict:
    from pid_native_validation import run_map_pid_validation
    directory = Path(trial_dir)
    record = verify_native_run(directory)
    attempt = record['evaluation']['attempts'][-1]
    context_path = Path(attempt['context_path']).resolve()
    if not context_path.is_relative_to((directory/'evaluation').resolve()):
        raise ValueError('PID_BUNDLE_INTEGRITY: contexto fuera del ensayo.')
    context = _read(context_path)
    result = run_map_pid_validation(project_root, Path(context['execution_package']), download=False,
        cancel=cancel, profile=_read(directory/'plant_profile.json'),
        protocol=_read(directory/'native_eval_protocol.json'), report_dir=context_path.parent/'runtime',
        execution_context=context)
    _save(context_path.parent/'native_validation.json', result)
    return result
