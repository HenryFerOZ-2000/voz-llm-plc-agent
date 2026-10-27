"""Bounded physical-image checks for the additional virtual map matrix only."""
from pathlib import Path
import json
import subprocess

import plcsim_runtime
from plcsim_runtime_io import runtime_address


def build_map_bridge(root: Path,output: Path) -> Path:
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    exe=output/'MapValidation.exe'
    sources=[Path(root)/'plcsim_runtime_bridge'/n for n in ('Program.cs','PidPlantSession.cs','ManualIO.cs','MapValidation.cs')]
    inputs=[*sources,plcsim_runtime.DEFAULT_RUNTIME_API_DLL]
    if exe.is_file() and exe.stat().st_mtime>=max(p.stat().st_mtime for p in inputs):return exe
    run=subprocess.run([str(plcsim_runtime.DEFAULT_COMPILER),'/nologo','/platform:x64','/target:exe',
        '/main:VozLlmPlcAgent.PlcsimRuntimeBridge.MapValidation',f'/out:{exe}',
        f'/reference:{plcsim_runtime.DEFAULT_RUNTIME_API_DLL}',f'/reference:{plcsim_runtime.DEFAULT_WEB_EXTENSIONS}',
        *map(str,sources)],capture_output=True,text=True,timeout=120)
    if run.returncode:raise RuntimeError(run.stdout+run.stderr)
    return exe


def validation_steps(case):
    def step(id,values=None,expected=None):return {'id':id,'values':values or {},'expected':expected or {},'settle_ms':200}
    start,stop,emergency='I_Start_A','I_Stop_A','I_Emergency_A'
    initial={start:False,stop:False,emergency:False}
    if case=='discrete_relocated':
        q='Q_Traffic_Green_A'
        return [step('initial',initial,{q:False}),step('start',{start:True},{q:True}),step('latched',{start:False},{q:True}),
            step('stop',{stop:True},{q:False}),step('held_start_after_stop',{start:True},{q:False}),
            step('release_stop',{stop:False},{q:False}),step('release_start',{start:False},{q:False}),
            step('restart',{start:True},{q:True}),step('emergency',{emergency:True},{q:False}),
            step('emergency_released_held_start',{emergency:False},{q:False}),step('final_stop',{start:False,stop:True},{q:False})]
    pv='AI_Level_Raw_A'
    if case=='fill_relocated':
        q='AO_Fill_Command_A'
        return [step('initial',{**initial,pv:5529},{q:0}),step('start',{start:True},{q:27648}),
            step('fill',{start:False},{q:27648}),step('limit',{pv:24884},{q:0}),step('no_auto_restart',{pv:5529},{q:0}),
            step('restart',{start:True},{q:27648}),step('stop',{stop:True},{q:0}),
            step('held_start_after_stop',{stop:False},{q:0}),step('release_start',{start:False},{q:0}),
            step('restart_again',{start:True},{q:27648}),step('emergency',{emergency:True},{q:0}),
            step('final_stop',{start:False,stop:True},{q:0})]
    if case=='hysteresis_relocated':
        q='Q_Tank_Main_Output'
        return [step('initial',{**initial,pv:13824},{q:False}),step('start',{start:True},{q:False}),
            step('low',{start:False,pv:5529},{q:True}),step('retain_on_midrange',{pv:13824},{q:True}),
            step('high',{pv:24884},{q:False}),step('retain_off_midrange',{pv:13824},{q:False}),
            step('low_again',{pv:5529},{q:True}),step('stop',{stop:True},{q:False}),
            step('final_stop',{start:False},{q:False})]
    raise ValueError('MAP_RUNTIME_CASE_UNSUPPORTED: '+str(case))


def run_map_steps(root,case,package,folder,*,cancel=None):
    if cancel and cancel.is_set():return {'status':'CANCELLED','cleanup_verified':False}
    variables=json.loads((Path(package)/'variables.json').read_text(encoding='utf-8'))
    steps=validation_steps(case['case_id'])
    needed={name for s in steps for name in [*s['values'],*s['expected']]}
    signals=[]
    for name in sorted(needed):
        matches=[v for v in variables if v['name']==name]
        if len(matches)!=1:raise ValueError('MAP_RUNTIME_BINDING_MISSING: '+name)
        variable=matches[0];address=runtime_address(variable['location'])
        if variable['type'] not in {'BOOL','INT'} or address['size'] not in {'X','W'}:
            raise ValueError('MAP_RUNTIME_BINDING_UNSUPPORTED: '+name)
        signals.append({'name':name,'area':address['area'],'offset':address['offset'],
            'bit':address['bit'],'data_type':variable['type'],'address':address['address']})
    config=plcsim_runtime.load_runtime_config(plcsim_runtime._load_tia_config(root))
    request={'action':'validate','target_type':'PLCSIM_ADVANCED','purpose':'MAP_ADAPTATION_DEVELOPMENT',
        'instance_name':config['instance_name'],'signals':signals,'steps':steps,'result_path':str(Path(folder)/'map_runtime.json')}
    request_path=Path(folder)/'map_runtime_request.json';request_path.write_text(json.dumps(request,indent=2),encoding='utf-8')
    exe=build_map_bridge(root,Path(root)/'runtime/map_validation_bridge')
    run=subprocess.run([str(exe),str(request_path)],capture_output=True,text=True,timeout=60)
    report=json.loads(Path(request['result_path']).read_text(encoding='utf-8'))
    report['bridge_return_code']=run.returncode
    return report
