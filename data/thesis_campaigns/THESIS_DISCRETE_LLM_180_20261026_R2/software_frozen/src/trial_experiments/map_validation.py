"""Additional DEVELOPMENT compatibility evidence using recorded product inputs."""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

import product_engine as engine
from trial_experiments.development_validation import build_map_adaptation_cases
from trial_experiments import deferred_evaluator as DE, tia_workspace as TW
from utils import load_json_file


def _save(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str),encoding='utf-8')


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_map_adaptation_round(root: Path,output: Path,*,evaluate: bool,cancel=None) -> dict:
    root=Path(root);run=Path(output)/('MAP_DEV_'+uuid.uuid4().hex[:10]);run.mkdir(parents=True,exist_ok=False)
    report={'round_id':run.name,'phase':'DEVELOPMENT_VALIDATION','method':'RECORDED_RESPONSE_COMPATIBILITY',
        'status':'RUNNING','evidence_dir':str(run),'entries':[]}
    catalog=load_json_file(root/'config/intents_catalog.json');safety=load_json_file(root/'config/safety_rules.json')
    for index,case in enumerate(build_map_adaptation_cases(root)):
        if cancel and cancel.is_set():report['status']='CANCELLED';break
        folder=run/str(index);folder.mkdir()
        entry={'case_id':case['case_id'],'evidence_dir':str(folder),'runtime':None,'generation':'FAILED','status':'FAILED'}
        try:
            _save(folder/'map.json',case['io_map']);_save(folder/'recorded_response.json',case['semantic_response'])
            (folder/'command.txt').write_text(case['command_text'],encoding='utf-8')
            semantic=engine.interpret_product_command(case['command_text'],io_map=case['io_map'],intents_catalog=catalog,
                safety_rules=safety,mode='llm',llm_response_text=case['semantic_response'])
            _save(folder/'semantic.json',semantic)
            proposals=(semantic.get('semantic_validation') or {}).get('io_assignment_proposals') or []
            if any(p.get('blocked') or p.get('conflict') for p in proposals):raise ValueError('MAP_IO_UNRESOLVED')
            semantic,working,_=engine.resolve_product_assignments(semantic,case['io_map'],proposals,catalog,safety)
            _save(folder/'resolved_map.json',working)
            if not engine.is_generatable_product(semantic):raise ValueError('MAP_SEMANTIC_INVALID')
            generated=engine.generate_product_package(semantic,target_platform='SIEMENS_SCL_V18',io_map=working,
                intents_catalog=catalog,safety_rules=safety,output_dir=folder/'g')
            if generated.get('verification',{}).get('is_valid') is not True:raise ValueError('MAP_GENERATION_INVALID')
            package=Path(generated['package_dir']);entry.update(generation='SUCCESS',package_dir=str(package),status='GENERATED')
            files={name:_sha(folder/name) for name in ('map.json','resolved_map.json','recorded_response.json','command.txt','semantic.json')}
            package_files={p.name:_sha(p) for p in package.iterdir() if p.is_file()}
            _save(folder/'manifest.json',{'method':report['method'],'case_id':case['case_id'],'files':files,'package_files':package_files})
            if evaluate:
                entry['runtime_attempted']=True
                runtime=evaluate_map_package(root,case,package,folder,cancel=cancel)
                entry.update(runtime=runtime,status='PASSED' if runtime.get('status')=='PASSED'
                    and runtime.get('cleanup_verified') is True else 'FAILED')
        except Exception as error:entry.update(status='FAILED',errors=[str(error)])
        report['entries'].append(entry);_save(run/'summary.json',report)
        print(case['case_id']+': '+entry['status'],flush=True)
        if (entry.get('runtime_attempted') and ((entry.get('runtime') or {}).get('cleanup_verified') is not True
                or (entry.get('runtime') or {}).get('master_unchanged') is False)):
            report.update(status='FAILED',halt_reason='UNVERIFIED_CLEANUP_OR_MASTER')
            break
    else:
        expected='PASSED' if evaluate else 'GENERATED'
        report['status']=expected if all(e['status']==expected for e in report['entries']) else 'FAILED'
    _save(run/'summary.json',report)
    return report


def evaluate_map_package(root,case,package,folder,*,cancel=None):
    manifest=load_json_file(folder/'manifest.json')
    if any(_sha(package/name)!=digest for name,digest in manifest['package_files'].items()):raise ValueError('MAP_PACKAGE_CHANGED')
    if (package/'pid_infrastructure.json').is_file():
        from trial_experiments.native_pid_protocol import create_native_validation_run
        protocol=load_json_file(root/'config/native_pid_evaluation_protocol.json')
        protocol['tuning_authorized']=True  # This explicit evaluation action includes the fixed test protocol.
        run=create_native_validation_run(root,package,protocol,load_json_file(root/'config/pid_tank_test_profile.json'),folder/'native')
        return DE.run_frozen_native_development(root,run,cancel=cancel)
    from trial_experiments.map_runtime_validation import run_map_steps
    import tia_openness
    master=DE.load_master_config(root);snapshot=master['snapshot']
    before=DE.master_folder_fingerprint(master['path'])
    entry=TW.allocate(root,folder.parent.name+'_'+case['case_id'],1,folder)
    workspace=Path(entry['path']);paths=TW.layout(workspace,entry['workspace_id'])
    shutil.copyfile(package/'siemens_source.scl',paths['source_path'])
    target=tia_openness.resolve_download_target(tia_openness.load_tia_config(root),'experiment')
    request={'action':'evaluate_trial','master_archive_path':snapshot['archive_path'],
        'working_dir':str(paths['retrieve_dir']),'trial_archive_dir':str(paths['archive_dir']),
        'trial_archive_name':str(paths['archive_name']),'source_path':str(paths['source_path']),
        'source_name':'siemens_source.scl','handshake_dir':str(workspace),
        'expected_project_name':DE.master_internal_project_name(master),'checkpoint_path':str(workspace/TW.CHECKPOINTS_FILENAME),
        'handshake_timeout_seconds':600,'plc_name':str(tia_openness.load_tia_config(root).get('plc_name','')),
        'with_user_interface':False,'tags':DE.trial_tag_payload(load_json_file(package/'variables.json'),{}),
        'delete_blocks':sorted(set(DE.master_app_managed_blocks(master))-set(DE.declared_blocks((package/'siemens_source.scl').read_text(encoding='utf-8')))),
        'download_after_archive':True,'purpose':'experiment','require_simulation':True,**target,'physical_download_allowed':False}
    copied={}
    def archived(info):
        if Path(info.get('archive_path','')).resolve()!=paths['archive_path'].resolve():return {'download':False,'reason':'WRONG_ARCHIVE'}
        copied.update(TW.copy_archive_to_evidence(paths['archive_path'],folder/'compiled.zap18',info.get('archive_sha256')))
        return {'download':bool(copied.get('copied_ok')) and not(cancel and cancel.is_set()),'reason':'MAP_EVIDENCE_CHECK'}
    raw=DE.execute_isolated_trial_request(root,request,workspace,archived)
    _save(folder/'compile_download.json',raw);_save(folder/'archive_copy.json',copied)
    TW.update_entry(root,entry['workspace_id'],state=TW.STATE_KEPT,evidence_copied_ok=bool(copied.get('copied_ok')),
        evidence_path=str(folder/'compiled.zap18'),keep_reason='Matriz de mapas: copia aislada conservada para inspección.')
    if (raw.get('status')!='TIA_COMPILATION_PASSED' or raw.get('error_count')!=0 or not copied.get('copied_ok')
            or (raw.get('download') or {}).get('status')!='TIA_DOWNLOAD_PASSED'):
        return {'status':'FAILED','cleanup_verified':False,'errors':raw.get('errors') or ['Compilación/archivo/descarga no verificados.']}
    runtime=run_map_steps(root,case,package,folder,cancel=cancel)
    runtime['master_unchanged']=DE.master_folder_fingerprint(master['path'])==before
    if not runtime['master_unchanged']:runtime['status']='FAILED'
    _save(folder/'runtime.json',runtime)
    # Keep the short workspace registered and archived for inspection, never reuse it.
    return runtime
