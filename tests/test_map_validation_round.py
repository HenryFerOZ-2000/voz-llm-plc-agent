import importlib
import json
from pathlib import Path


def test_map_round_freezes_real_packages_without_running_tia(project_root,tmp_path,monkeypatch):
    from trial_experiments import development_validation as development
    before={p.name:p.read_bytes() for p in (project_root/'tests/fixtures/closure_maps').glob('*.json')}
    service=importlib.import_module('trial_experiments.map_validation')
    monkeypatch.setattr(service,'evaluate_map_package',lambda *a,**k:(_ for _ in ()).throw(AssertionError('TIA called')))
    result=service.run_map_adaptation_round(project_root,tmp_path,evaluate=False)
    assert result['status']=='GENERATED' and len(result['entries'])==5
    assert {e['case_id'] for e in result['entries']}=={c['case_id'] for c in development.build_map_adaptation_cases(project_root)}
    for entry in result['entries']:
        assert entry['generation']=='SUCCESS'
        folder=Path(entry['evidence_dir'])
        frozen=json.loads((folder/'map.json').read_text(encoding='utf-8'))
        assert any(v['name'].endswith('_A') for v in frozen['variables'])
        assert (folder/'manifest.json').is_file() and entry['runtime'] is None
        assert (folder/'resolved_map.json').is_file()
    assert {p.name:p.read_bytes() for p in (project_root/'tests/fixtures/closure_maps').glob('*.json')}==before


def test_unverified_cleanup_cannot_be_a_pass(project_root,tmp_path,monkeypatch):
    service=importlib.import_module('trial_experiments.map_validation')
    from trial_experiments import development_validation as development
    case=development.build_map_adaptation_cases(project_root)[0]
    monkeypatch.setattr(service,'build_map_adaptation_cases',lambda root:[case])
    monkeypatch.setattr(service,'evaluate_map_package',lambda *a,**k:{'status':'PASSED','cleanup_verified':False})
    result=service.run_map_adaptation_round(project_root,tmp_path,evaluate=True)
    assert result['status']=='FAILED' and result['entries'][0]['status']=='FAILED'


def test_runtime_exception_is_reported_as_failed_after_successful_generation(project_root,tmp_path,monkeypatch):
    service=importlib.import_module('trial_experiments.map_validation')
    from trial_experiments import development_validation as development
    case=development.build_map_adaptation_cases(project_root)[0]
    monkeypatch.setattr(service,'build_map_adaptation_cases',lambda root:[case])
    def failed(*a,**k):raise RuntimeError('Runtime bridge timed out')
    monkeypatch.setattr(service,'evaluate_map_package',failed)
    result=service.run_map_adaptation_round(project_root,tmp_path,evaluate=True)
    entry=result['entries'][0]
    assert entry['generation']=='SUCCESS' and entry['status']=='FAILED'
    assert entry['errors']==['Runtime bridge timed out']


def test_matrix_stops_before_next_download_when_cleanup_is_unverified(project_root,tmp_path,monkeypatch):
    service=importlib.import_module('trial_experiments.map_validation')
    cases=service.build_map_adaptation_cases(project_root)[:2]
    monkeypatch.setattr(service,'build_map_adaptation_cases',lambda root:cases)
    calls=[]
    def unsafe(root,case,*a,**k):
        calls.append(case['case_id']);return {'status':'FAILED','cleanup_verified':False}
    monkeypatch.setattr(service,'evaluate_map_package',unsafe)
    result=service.run_map_adaptation_round(project_root,tmp_path,evaluate=True)
    assert calls==['discrete_relocated'] and len(result['entries'])==1
    assert result['status']=='FAILED'


def test_map_cli_can_generate_without_credentials_or_network(tmp_path,project_root):
    import subprocess,sys
    run=subprocess.run([sys.executable,str(project_root/'scripts/validate_product_closure.py'),
        'maps','--phase','DEVELOPMENT','--generate-only','--output',str(tmp_path)],capture_output=True,text=True,timeout=40)
    assert run.returncode==0,run.stdout+run.stderr
    report=json.loads(run.stdout.strip().splitlines()[-1])
    assert report['status']=='GENERATED' and report['entries']==5
