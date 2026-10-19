import pytest


def samples(seconds=10,pv=50):
    return [{'t_s':i/10,'pv':pv,'cv':40,'fault':False,'sensor_valid':True} for i in range(seconds*10+1)]


def test_convergence_requires_ten_continuous_seconds():
    from pid_acceptance import evaluate_pid_samples
    assert evaluate_pid_samples(samples(9),50)['status']=='PENDING'
    assert evaluate_pid_samples(samples(10),50)['status']=='PASSED'


def test_overshoot_or_missing_samples_do_not_count_as_success():
    from pid_acceptance import evaluate_pid_samples
    data=samples(10);data[50]['pv']=54
    assert evaluate_pid_samples(data,50)['status']=='PENDING'
    data=samples(10);del data[40:65]
    assert evaluate_pid_samples(data,50)['status']=='PENDING'
    data=samples(10);data[50]['sensor_valid']=False
    assert evaluate_pid_samples(data,50)['status']=='PENDING'


def test_timeout_is_a_failed_execution():
    from pid_acceptance import evaluate_pid_samples
    assert evaluate_pid_samples(samples(300,pv=40),50)['status']=='FAILED'


def test_no_native_run_is_reported_pending():
    from pid_acceptance import evaluate_pid_samples
    result=evaluate_pid_samples([],50)
    assert result['status']=='PENDING' and result['native_execution_verified'] is False


def test_acceptance_refuses_physical_target():
    from pid_acceptance import require_simulation_target
    with pytest.raises(ValueError,match='PID_ACCEPTANCE_TARGET'):require_simulation_target({'target_type':'PHYSICAL_PLC'})


def test_map_setup_has_no_digital_side_effects():
    from test_tank_bench_setup import bench
    from tank_bench_setup import prepare_tank_bench
    before=bench();after=prepare_tank_bench(before)
    assert before['variables'][:16]==after['variables'][:16]


def test_validation_reruns_preserve_each_attempt(tmp_path):
    import importlib.util,json
    from utils import get_project_root
    spec=importlib.util.spec_from_file_location('pid_validation_test',get_project_root()/'scripts/validate_native_pid.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    package=tmp_path/'package';package.mkdir()
    first=module.run_validation(tmp_path,package,'PHYSICAL')
    second=module.run_validation(tmp_path,package,'PHYSICAL')
    assert first['evidence']!=second['evidence']
    from pathlib import Path
    assert (Path(first['evidence'])/'execution_error.json').is_file()
    assert (Path(second['evidence'])/'execution_error.json').is_file()
    latest=json.loads((package/'native_pid_validation/latest_run.json').read_text())
    assert latest['evidence']==second['evidence'] and latest['status']=='FAILED'


def test_pretuning_recovers_from_overfill_before_reset_and_start():
    import importlib.util
    from utils import get_project_root
    spec=importlib.util.spec_from_file_location('pid_recovery_test',get_project_root()/'scripts/validate_native_pid.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    events=[]
    class Session:
        pv=95.0
        fault=True
        def write(self,name,value):
            events.append((name,value,self.pv))
            if name=='CmdReset':self.fault=False
        def read(self):
            return {'PV':self.pv,'SP':60.0,'Fault':self.fault,'SensorValid':True}
    session=Session()
    def sample(*args):session.pv-=8
    values=module.recover_for_pretuning(session,sample)
    assert values['PV']<20 and not values['Fault']
    assert events[:3]==[('CmdStop',True,95.0),('ManualValue',40,95.0),('CmdManual',True,95.0)]
    assert all(pv<20 for name,value,pv in events if name in {'CmdReset','CmdStart'})
