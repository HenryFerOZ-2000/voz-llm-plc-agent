import json
import subprocess


def test_map_runtime_guard_and_word_access_use_production_code(project_root,tmp_path):
    from trial_experiments import map_runtime_validation as service
    exe=service.build_map_bridge(project_root,tmp_path)
    request=tmp_path/'request.json';result=tmp_path/'result.json'
    request.write_text(json.dumps({'action':'self_test','result_path':str(result)}))
    run=subprocess.run([str(exe),str(request)],capture_output=True,text=True,timeout=25)
    assert run.returncode==0,run.stdout+run.stderr
    report=json.loads(result.read_text())
    assert report['checks']=={'word_big':True,'word_little':True,'negative':True,'word_input':True,
        'word_output_read':True,'word_output_write_denied':True,'word_type_mismatch':True,'word_address_mismatch':True,
        'physical_target_denied':True,'wrong_purpose_denied':True,'valid_target':True}


def test_map_steps_exercise_threshold_hysteresis_and_new_start():
    from trial_experiments.map_runtime_validation import validation_steps
    fill=validation_steps('fill_relocated')
    assert fill[-1]['expected']=={'AO_Fill_Command_A':0}
    assert any(s.get('id')=='held_start_after_stop' and s['expected']=={'AO_Fill_Command_A':0} for s in fill)
    hysteresis=validation_steps('hysteresis_relocated')
    assert any(s.get('id')=='retain_on_midrange' and s['expected']=={'Q_Tank_Main_Output':True} for s in hysteresis)
    assert any(s.get('id')=='retain_off_midrange' and s['expected']=={'Q_Tank_Main_Output':False} for s in hysteresis)
