"""Persist fresh, identity-bound native PID parameters through verified TIA saves."""
from __future__ import annotations

import hashlib
import json
import math
import uuid
import zipfile
from pathlib import Path

from pid_package import native_download_project, native_parameter_project, validate_pid_manifest
from tia_projects import normal_project_path

TOLERANCE = 0.0001


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _identity(package):
    manifest=_read(package/'pid_infrastructure.json');loop=validate_pid_manifest(manifest)
    bindings=_read(package/'pid_process_bindings.json')
    return {'configuration_hash':loop['configuration_hash'],'build_signature':bindings['build_signature'],
            'source_sha256':_sha(package/'siemens_source.scl'),'controller':loop['symbols']['controller']}


def _parameters(values):
    result={key:values.get(key) for key in ('Kp','Ti','Td')}
    if (any(type(v) not in (int,float) or not math.isfinite(v) for v in result.values())
            or result['Kp']<=0 or result['Ti']<=0 or result['Td']<0):
        raise ValueError('PID_PARAMETER_SAVE: parámetros finitos y válidos requeridos.')
    return result


def inspect_parameter_state(package_dir: Path, live_values: dict, saved_record: dict | None) -> dict:
    identity=_identity(Path(package_dir))
    if live_values.get('build_signature') != identity['build_signature']:
        return {'state':'INCOMPATIBLE','reason':'El programa leído no coincide con el paquete.'}
    if live_values.get('ControllerState') in (1,2) or live_values.get('TuningMode') in (1,2):
        return {'state':'TUNING','reason':'Sintonización en curso.'}
    try:parameters=_parameters(live_values)
    except ValueError as error:return {'state':'UNVERIFIED','reason':str(error)}
    if live_values.get('ParametersConfirmed') is not True or live_values.get('Fault') is True:
        return {'state':'UNVERIFIED','reason':'El controlador aún no confirma ajustes válidos.'}
    if saved_record:
        if saved_record.get('identity') != identity:
            return {'state':'INCOMPATIBLE','reason':'Los ajustes guardados pertenecen a otra configuración.'}
        saved=saved_record.get('parameters') or {}
        evidence_valid=False
        try:
            archive=Path(saved_record['backup_path'])
            report_path=Path(saved_record['report_path']);report=_read(report_path)
            after=_parameters(report['parameters_after'])
            evidence_valid=(_sha(archive)==saved_record['backup_sha256']
                and _sha(report_path)==saved_record['report_sha256']
                and report.get('status')=='PID_PARAMETERS_SAVED'
                and report.get('parameters_verified') is True and report.get('project_saved') is True
                and report.get('configuration_hash')==identity['configuration_hash']
                and Path(report['project_path']).resolve()==Path(saved_record['project_path']).resolve()
                and Path(report['backup_path']).resolve()==archive.resolve()
                and report['backup_sha256']==saved_record['backup_sha256']
                and all(type(saved.get(k)) in (int,float) and abs(saved[k]-v)<=TOLERANCE for k,v in after.items()))
            if evidence_valid:
                with zipfile.ZipFile(archive) as stored:evidence_valid=stored.testzip() is None
        except (OSError,ValueError,KeyError,zipfile.BadZipFile):pass
        if (evidence_valid and saved_record.get('verified') is True and all(type(saved.get(k)) in (int,float)
                and math.isfinite(saved[k]) and abs(saved[k]-v)<=TOLERANCE for k,v in parameters.items())):
            return {'state':'SAVED_VERIFIED','reason':'Ajustes actuales coinciden con el guardado verificado.'}
    return {'state':'PENDING_SAVE','reason':'Ajustes confirmados en CPU; falta guardarlos en el proyecto.'}


def run_parameter_bridge(request: dict, work_dir: Path, project_root: Path) -> dict:
    from trial_experiments.deferred_evaluator import run_bridge
    return run_bridge(request,work_dir,project_root=project_root,timeout_s=300)


def load_saved_parameters(project_root: Path, package_dir: Path) -> dict | None:
    root,package=Path(project_root),Path(package_dir)
    project=normal_project_path(root)
    if not project:return None
    identity=_identity(package)
    key=hashlib.sha256((str(Path(project).resolve()).casefold()+identity['configuration_hash']).encode()).hexdigest()[:24]
    path=root/'runtime/pid/parameter_records'/(key+'.json')
    return _read(path) if path.is_file() else None


def save_verified_parameters(project_root: Path, package_dir: Path, session, *, cancel=None, verification_only=False) -> dict:
    root,package=Path(project_root),Path(package_dir)
    fresh=session.read()  # Revalidates the loaded 16-word signature before any project operation.
    context=session.context
    bindings=_read(package/'pid_process_bindings.json')
    if (context.get('target_type')!='PLCSIM_ADVANCED' or context.get('connected') is not True
            or context.get('cpu_state')!='RUN' or context.get('program_verified') is not True
            or session.bindings.get('build_signature')!=bindings['build_signature']):
        raise ValueError('PID_PARAMETER_SAVE: programa/destino no verificados.')
    live={**fresh,'build_signature':bindings['build_signature']}
    state=inspect_parameter_state(package,live,None)
    if state['state'] not in {'PENDING_SAVE','SAVED_VERIFIED'}:
        raise ValueError('PID_PARAMETER_SAVE: '+state['reason'])
    if cancel and cancel.is_set():return {'status':'CANCELLED'}
    project=Path(native_parameter_project(package,root) if verification_only
                 else native_download_project(package,root,'PLCSIM_ADVANCED')).resolve()
    normal=normal_project_path(root)
    if not normal or project!=Path(normal).resolve():
        raise ValueError('PID_PARAMETER_SAVE: solo el proyecto Normal configurado.')
    identity=_identity(package);parameters=_parameters(live)
    folder=root/'runtime/pid/parameter_saves'/uuid.uuid4().hex[:12]
    folder.mkdir(parents=True,exist_ok=False)
    from tia_openness import _normal_program_state_path
    request={'action':'native_pid_save_parameters','project_path':str(project),
        'pid_manifest':_read(package/'pid_infrastructure.json'),'pid_manifest_path':str((package/'pid_infrastructure.json').resolve()),
        'source_path':str((package/'siemens_source.scl').resolve()),
        'pid_source_sha256':identity['source_sha256'],'pid_manifest_sha256':_sha(package/'pid_infrastructure.json'),
        'pid_bindings_path':str((package/'pid_process_bindings.json').resolve()),
        'pid_bindings_sha256':_sha(package/'pid_process_bindings.json'),
        'normal_program_state_path':_normal_program_state_path(root,str(project)),
        'normal_program_backup_directory':str((folder/'before').resolve()),
        'configuration_hash':identity['configuration_hash'],'build_signature':identity['build_signature'],
        'parameters':parameters,'parameter_save_directory':str(folder.resolve()),
        'verification_only':verification_only,
        'attach_to_running':True,'with_user_interface':False,'physical_download_allowed':False}
    # Once TIA may change the offline project, its previous compilation cannot be
    # reused, even if a timeout or missing evidence prevents confirming the save.
    compile_path=package/'tia_compile_report.json'
    if compile_path.is_file():
        compiled=_read(compile_path);compiled['parameter_update_requires_compile']=True
        temporary_compile=compile_path.with_suffix('.tmp')
        temporary_compile.write_text(json.dumps(compiled,indent=2),encoding='utf-8')
        temporary_compile.replace(compile_path)
    report=run_parameter_bridge(request,folder,root)
    (folder/'save_report.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    try:
        archive=Path(report['backup_path']).resolve()
        after=_parameters(report['parameters_after'])
        if (report.get('status')!='PID_PARAMETERS_SAVED' or report.get('project_saved') is not True
                or report.get('parameters_verified') is not True
                or verification_only and report.get('save_method')!='TIA_MANUAL_UPLOAD_VERIFIED'
                or Path(report.get('project_path','')).resolve()!=project
                or report.get('configuration_hash')!=identity['configuration_hash']
                or not archive.is_relative_to(folder.resolve()) or _sha(archive)!=report.get('backup_sha256')
                or any(abs(after[k]-v)>TOLERANCE for k,v in parameters.items()) or _identity(package)!=identity):
            raise ValueError('identidad, archivo o parámetros no confirmados')
        with zipfile.ZipFile(archive) as stored:
            if stored.testzip():raise ValueError('archivo de respaldo incompleto')
    except (KeyError,TypeError,ValueError,OSError,zipfile.BadZipFile) as error:
        raise ValueError('PID_PARAMETER_SAVE: '+str(error)) from error
    record={'schema_version':1,'verified':True,'identity':identity,'parameters':after,
            'project_path':str(project),'backup_path':str(archive),'backup_sha256':report['backup_sha256'],
            'report_path':str(folder/'save_report.json'),'report_sha256':_sha(folder/'save_report.json')}
    key=hashlib.sha256((str(project).casefold()+identity['configuration_hash']).encode()).hexdigest()[:24]
    path=root/'runtime/pid/parameter_records'/(key+'.json');path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    temporary.replace(path)
    return {'status':'SAVED_VERIFIED','record':record,'record_path':str(path)}
