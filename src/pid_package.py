"""Native package paths, readiness and transactional import metadata."""
from __future__ import annotations
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from process_signals import normalize_process_binding, validate_process_storage, process_db_descriptors, IDENTIFIER


def _project_cache_key(template: str, configuration_hash: str):
    path=Path(template).resolve()
    if not path.is_file():return None
    return hashlib.sha256((str(path).casefold()+':'+hashlib.sha256(path.read_bytes()).hexdigest()+':'+configuration_hash).encode()).hexdigest()


def remember_native_project(root: Path, report: dict):
    """Remember verified offline infrastructure across independently generated packages."""
    if report.get('status')!='TIA_COMPILATION_PASSED' or report.get('error_count')!=0:return
    candidate=Path(report.get('project_path','')).resolve()
    directory=(root/'runtime/pid').resolve()
    if not candidate.is_relative_to(directory) or not candidate.is_file():return
    key=_project_cache_key(report.get('template_project_path',''),str(report.get('configuration_hash','')))
    if not key:return
    path=directory/'compiled_projects.json'
    entries=json.loads(path.read_text()) if path.is_file() else {}
    entries[key]=str(candidate)
    temporary=path.with_name(uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(entries,indent=2),encoding='utf-8')
    os.replace(temporary,path)


def validate_pid_manifest(m):
    if (not isinstance(m,dict) or type(m.get('schema_version')) is not int or m['schema_version'] not in (1,2)
            or m.get('owner')!=f"VozLlmPlcAgent.NativePID.v{m['schema_version']}"):
        raise ValueError('PID_CONFIG_MISMATCH: manifiesto invalido.')
    loops=m.get('loops')
    if not isinstance(loops,list) or len(loops)!=1 or not isinstance(loops[0],dict):
        raise ValueError('PID_MULTIPLE_LOOPS: se requiere un lazo.')
    loop=loops[0]
    if type(loop.get('period_ms')) is not int or loop['period_ms']!=100:
        raise ValueError('PID_PERIOD: esta version verificada utiliza 100 ms.')
    if loop.get('technology_version')!='2.3': raise ValueError('PID_UNSUPPORTED_VERSION: requiere PID_Compact2.3.')
    names=loop.get('symbols',{})
    if not isinstance(names,dict) or set(names)!={'fb','db','controller','ob'} or any(
            not isinstance(n,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',n) for n in names.values()) or len(set(n.lower() for n in names.values()))!=4:
        raise ValueError('PID_BLOCK_CONFLICT: nombres de bloque invalidos.')
    if loop.get('direction') not in {'FILL','DRAIN'}:
        raise ValueError('PID_CONFIG_MISMATCH: modo/direccion ausente.')
    if not re.fullmatch('[a-f0-9]{64}',str(loop.get('configuration_hash',''))): raise ValueError('PID_CONFIG_MISMATCH: falta huella.')
    if m['schema_version']==1:
        if loop.get('mode') not in {'SIMULATION','PHYSICAL'}:
            raise ValueError('PID_CONFIG_MISMATCH: falta modo histórico.')
        if loop['mode']=='PHYSICAL' and any(loop.get(k,{}).get('confirmed') is not True for k in ('input_config','output_config')):
            raise ValueError('PID_CALIBRATION_REQUIRED')
    else:
        if 'mode' in loop or 'simulation' in loop:
            raise ValueError('PID_CONFIG_MISMATCH: v2 no admite modo/modelo.')
        connections=[]
        for key,role in [('input_binding','MEASUREMENT'),('output_binding','MANIPULATED')]:
            binding=loop.get(key)
            if not isinstance(binding,dict):raise ValueError('PID_CONFIG_MISMATCH: falta '+key)
            if binding.get('representation')=='HARDWARE_RAW':
                entry=dict(name=binding.get('name'),type='INT',location=binding.get('address'),
                           analog_config=binding.get('analog_config'),llm_allowed=binding.get('permission'),
                           **{'class':'input' if role=='MEASUREMENT' else 'output'})
            elif binding.get('representation')=='DB_ENGINEERING':
                config=dict(schema_version=1,role=binding.get('role'),quantity=binding.get('quantity'),
                            engineering_unit=binding.get('unit'),engineering_min=binding.get('engineering_min'),
                            engineering_max=binding.get('engineering_max'),storage=binding.get('storage'))
                field='validity_member' if role=='MEASUREMENT' else 'fault_value'
                config[field]=binding.get(field)
                entry=dict(name=binding.get('name'),type='REAL',location='',process_config=config,
                           llm_allowed=binding.get('permission'),**{'class':'internal'})
            else:raise ValueError('PID_CONFIG_MISMATCH: representación inválida.')
            if normalize_process_binding(entry,role)!=binding:
                raise ValueError('PID_CONFIG_MISMATCH: binding no coincide con su configuración: '+key)
            connections.append(binding)
        conflicts=validate_process_storage(connections)
        if conflicts:raise ValueError('; '.join(conflicts))
        groups=m.get('process_dbs')
        if not isinstance(groups,list):raise ValueError('PID_STORAGE_CONFLICT: falta process_dbs.')
        seen=set()
        for group in groups:
            if not isinstance(group,dict) or not IDENTIFIER.fullmatch(str(group.get('db',''))):
                raise ValueError('PID_STORAGE_CONFLICT: DB inválido.')
            db=group['db'].casefold()
            if db in seen or db in {n.casefold() for n in names.values()}:
                raise ValueError('PID_STORAGE_CONFLICT: nombre de DB repetido/ocupado.')
            seen.add(db);members=set()
            for member in group.get('members',[]):
                key=str(member.get('name','')).casefold()
                if not IDENTIFIER.fullmatch(str(member.get('name',''))) or key in members:
                    raise ValueError('PID_STORAGE_CONFLICT: miembro de DB duplicado o inválido.')
                members.add(key)
        expected=process_db_descriptors(connections,m['owner'])
        if groups!=expected:
            raise ValueError('PID_STORAGE_CONFLICT: DBs no coinciden con los bindings declarados.')
    return loop


def native_request(package_dir: Path,root: Path,template: str, *, in_place: bool = False):
    package_dir=package_dir.resolve()
    m=json.loads((package_dir/'pid_infrastructure.json').read_text(encoding='utf-8'))
    loop=validate_pid_manifest(m)
    filename=m.get('cyclic_ob_file')
    if not isinstance(filename,str) or filename!='pid_cyclic_ob.xml': raise ValueError('PID_PACKAGE_PATH: XML fuera del paquete.')
    xml=(package_dir/filename).resolve()
    if xml.parent!=package_dir or not xml.is_file():raise ValueError('PID_PACKAGE_PATH: XML ausente o enlace externo.')
    workspace=(root/'runtime/pid'/uuid.uuid4().hex[:8]).resolve()
    template_hash=hashlib.sha256(Path(template).read_bytes()).hexdigest() if Path(template).is_file() else None
    source_project=template
    cache=root/'runtime/pid/compiled_projects.json'
    if not in_place and cache.is_file():
        candidate=Path(json.loads(cache.read_text()).get(_project_cache_key(template,loop['configuration_hash']),template)).resolve()
        if candidate.is_relative_to((root/'runtime/pid').resolve()) and candidate.is_file():source_project=str(candidate)
    previous=package_dir/'tia_compile_report.json'
    if not in_place and previous.is_file():
        prior=json.loads(previous.read_text(encoding='utf-8'))
        candidate=Path(prior.get('project_path','')).resolve()
        if template_hash and (prior.get('template_project_sha256') or prior.get('request',{}).get('template_project_sha256'))==template_hash and prior.get('status')=='TIA_COMPILATION_PASSED' and prior.get('configuration_hash')==loop['configuration_hash'] and prior.get('template_project_path')==template and candidate.is_relative_to((root/'runtime/pid').resolve()) and candidate.is_file():
            source_project=str(candidate)
    request={'action':'native_pid_import_compile','pid_manifest':m,'pid_cyclic_ob_path':str(xml),
        'pid_cyclic_ob_sha256':hashlib.sha256(xml.read_bytes()).hexdigest(),
        'pid_source_sha256':hashlib.sha256((package_dir/'siemens_source.scl').read_bytes()).hexdigest(),
        'pid_development_directory':str(workspace),'template_project_path':template,'template_project_sha256':template_hash,'project_path':source_project,
        'attach_to_running':False,'with_user_interface':False,'physical_download_allowed':False}
    if in_place:
        request.update(pid_project_mode='NORMAL_PROJECT', project_path=template)
    if m['schema_version']==2:
        request['pid_manifest_sha256']=hashlib.sha256((package_dir/'pid_infrastructure.json').read_bytes()).hexdigest()
        request['pid_bindings_sha256']=hashlib.sha256((package_dir/'pid_process_bindings.json').read_bytes()).hexdigest()
    return request


def validate_experimental_pid_project(package_dir: Path, root: Path, context: dict) -> str:
    """An experimental attempt is not a Normal or cached development project."""
    import zipfile
    from trial_experiments import deferred_evaluator as DE, tia_workspace as TW
    try:
        package = Path(package_dir).resolve()
        workspace = Path(context['workspace_path']).resolve()
        entry = TW.load_registry(root)['workspaces'][context['workspace_id']]
        if (Path(entry['path']).resolve() != workspace or entry['trial_id'] != context['run_id']
                or workspace.parent != TW.workspace_root(root).resolve() or not package.is_relative_to(workspace)):
            raise ValueError('workspace no pertenece a esta ejecución')
        master = DE.load_master_config(root)['snapshot']
        master_path = Path(context['master_archive_path']).resolve()
        if (master_path != Path(master['archive_path']).resolve()
                or DE.sha256_file(master_path) != master['archive_sha256']
                or context['master_archive_sha256'] != master['archive_sha256']):
            raise ValueError('MASTER distinto')
        evidence = Path(context['evidence_archive_path'])
        if DE.sha256_file(evidence) != context['evidence_archive_sha256']:
            raise ValueError('archivo de evidencia alterado')
        with zipfile.ZipFile(evidence) as stored:
            if stored.testzip():
                raise ValueError('archivo de evidencia incompleto')
        report = context['report']
        project = Path(report['project_path']).resolve()
        loop = validate_pid_manifest(json.loads((package/'pid_infrastructure.json').read_text(encoding='utf-8')))
        attributes = report.get('pid_cyclic_ob',{}).get('attributes',{})
        if (report.get('status') != 'TIA_COMPILATION_PASSED' or report.get('error_count') != 0
                or report.get('pid_project_mode') != 'EXPERIMENT_COPY'
                or not project.is_relative_to((workspace/'p').resolve()) or not project.is_file()
                or report.get('configuration_hash') != loop['configuration_hash']
                or attributes.get('SecondaryType') != 'CyclicInterrupt'
                or str(attributes.get('CyclicTime')) != str(loop['period_ms']*1000)):
            raise ValueError('compilación, proyecto u OB no verificados')
        for filename, key in [('siemens_source.scl','pid_source_sha256'),('pid_cyclic_ob.xml','pid_cyclic_ob_sha256'),
                              ('pid_infrastructure.json','pid_manifest_sha256'),('pid_process_bindings.json','pid_bindings_sha256')]:
            if DE.sha256_file(package/filename) != report.get(key):
                raise ValueError('paquete diferente de la compilación: '+filename)
        return str(project)
    except (KeyError, ValueError, TypeError, OSError, zipfile.BadZipFile) as error:
        raise ValueError('PID_EXPERIMENT_CONTEXT: '+str(error)) from error


def native_download_project(package_dir: Path,root: Path,target_type: str):
    return _compiled_native_project(package_dir,root,target_type,require_current_parameters=True)


def native_parameter_project(package_dir: Path,root: Path):
    """Locate a verified PLCSIM package for read-only parameter verification.

    The separate download entry point still requires recompilation after every
    parameter change. All source, binding, project and OB guards apply here too.
    """
    return _compiled_native_project(package_dir,root,'PLCSIM_ADVANCED',require_current_parameters=False)


def _compiled_native_project(package_dir: Path,root: Path,target_type: str,*,require_current_parameters: bool):
    manifest=json.loads((package_dir/'pid_infrastructure.json').read_text(encoding='utf-8'))
    loop=validate_pid_manifest(manifest)
    report=json.loads((package_dir/'tia_compile_report.json').read_text(encoding='utf-8'))
    if require_current_parameters and report.get('parameter_update_requires_compile') is True:
        raise ValueError('PID_COMPILE_REQUIRED: regenere y compile después de guardar ajustes PID offline.')
    attrs=report.get('pid_cyclic_ob',{}).get('attributes',{})
    project=Path(report.get('project_path','')).resolve()
    if report.get('pid_project_mode') == 'NORMAL_PROJECT':
        import tia_projects
        normal = tia_projects.normal_project_path(root)
        tia_projects.assert_normal_not_master(root, normal)
        allowed_project = bool(normal) and project == Path(normal).resolve()
        allowed_project = allowed_project and project == Path(report.get('template_project_path', '')).resolve()
    else:
        allowed_project = report.get('pid_project_mode') in (None, 'ISOLATED_COPY') and project.is_relative_to((root/'runtime/pid').resolve())
    if (report.get('status')!='TIA_COMPILATION_PASSED' or report.get('error_count')!=0
            or report.get('configuration_hash')!=loop['configuration_hash'] or attrs.get('SecondaryType')!='CyclicInterrupt'
            or str(attrs.get('CyclicTime'))!=str(loop['period_ms']*1000)
            or not allowed_project or not project.is_file()):
        raise ValueError('PID_COMPILE_REQUIRED: no hay un proyecto compilado y verificado de este paquete.')
    for file,key in [('siemens_source.scl','pid_source_sha256'),('pid_cyclic_ob.xml','pid_cyclic_ob_sha256')]:
        expected=report.get(key) or report.get('request',{}).get(key)
        if not expected or hashlib.sha256((package_dir/file).read_bytes()).hexdigest()!=expected:
            raise ValueError('PID_COMPILE_REQUIRED: el paquete cambio desde la compilacion.')
    if manifest['schema_version']==2:
        for file,key in [('pid_infrastructure.json','pid_manifest_sha256'),('pid_process_bindings.json','pid_bindings_sha256')]:
            expected=report.get(key) or report.get('request',{}).get(key)
            if not expected or hashlib.sha256((package_dir/file).read_bytes()).hexdigest()!=expected:
                raise ValueError('PID_COMPILE_REQUIRED: conexiones cambiaron desde la compilación.')
        if target_type!='PLCSIM_ADVANCED':
            for binding in (loop['input_binding'],loop['output_binding']):
                if binding['representation']=='HARDWARE_RAW' and binding['analog_config'].get('confirmed') is not True:
                    raise ValueError('PID_CALIBRATION_REQUIRED: confirme '+binding['name']+' en el mapa antes de descargar a hardware.')
            cpu=report.get('cpu',{})
            if not cpu.get('cpu_type_identifier') or not cpu.get('cpu_FirmwareVersion') or report.get('pid_infrastructure_after',{}).get('technology_version')!='2.3':
                raise ValueError('PID_CPU_COMPATIBILITY_REQUIRED: CPU/firmware/PID no verificados en la copia compilada.')
    elif loop['mode']=='SIMULATION' and target_type!='PLCSIM_ADVANCED':
        raise ValueError('PID_SIMULATION_TARGET: un modelo simulado solo se descarga a PLCSIM.')
    return str(project)
