import copy
import re
import pytest
from test_native_pid_resolution import payload,request
from test_tank_bench_setup import bench
from tank_bench_setup import prepare_tank_bench
from ir_builder import build_project_ir
from code_generator import generate_implementation_from_ir
from platforms.siemens_scl_adapter import SiemensSCLAdapter


def project(**kwargs):
    source=prepare_tank_bench(bench())
    if kwargs.get('mode')=='PHYSICAL':
        for v in source['variables']:
            if 'analog_config' in v: v['analog_config']['confirmed']=True
    p=build_project_ir(payload(request(**kwargs)),source,'SIEMENS_SCL_V18')
    p.pou.implementation_code=generate_implementation_from_ir(p)
    return p


def test_pid_uses_resolved_tags_and_single_scaling():
    p=project(mode='PHYSICAL')
    code=p.pou.implementation_code
    assert code.count('INT_TO_REAL(AI_Level_Raw)')==1
    assert code.count('REAL_TO_INT(')==1
    assert 'Input := PV' in code and 'Output => CV' in code


def test_controller_called_once_per_period_and_no_ob1_call():
    p=project(); source=SiemensSCLAdapter().render_full_program(p)
    assert source.count('"PID_LevelLoop"(')==1
    assert 'ORGANIZATION_BLOCK "Main"' not in source
    assert p.task.interval=='T#100ms'


def test_fault_forces_safe_output_same_scan():
    code=project(mode='PHYSICAL').pou.implementation_code
    assert code.index('Output => CV') < code.index('\nIF ControllerError THEN') < code.index('M_AO_Fill_Command_EU := CV;')
    assert 'IF NOT Running OR Fault THEN' in code


def test_held_start_after_recovery_does_not_restart():
    from trial_experiments.scl_sim import SclMachine
    p=project(resources={'start':'I_Digital_0','emergency':'I_Digital_1'})
    # Only supervision/model are executed here. No replacement PID is simulated.
    source=SiemensSCLAdapter().render_full_program(p)
    source=re.sub(r'\(\* NATIVE_PID_BEGIN \*\).*?\(\* NATIVE_PID_END \*\)',
                  'ControllerError := FALSE; CV := 40.0;',source,flags=re.S)
    machine=SclMachine(source,instance_db=p.pid_loops[0].symbols['db']); io={};machine.initialize(io)
    key=machine.static_key
    machine.scan(io)
    io['I_Digital_0']=True;machine.scan(io)
    assert io[key('Running')]
    io['I_Digital_1']=True;machine.scan(io)
    assert io[key('Fault')] and not io[key('Running')]
    io['I_Digital_1']=False;io[key('CmdReset')]=True;machine.scan(io)
    assert not io[key('Fault')] and not io[key('Running')]
    machine.scan(io);assert not io[key('Running')]
    io['I_Digital_0']=False;machine.scan(io)
    io['I_Digital_0']=True;machine.scan(io)
    assert io[key('Running')]


def test_legacy_mode_flag_still_uses_mapped_hardware_without_model():
    code=project().pou.implementation_code
    assert 'SimLevel' not in code and 'SimSensorFault' not in code
    assert 'M_AO_Fill_Command_EU := CV;' in code
    assert 'INT_TO_REAL(AI_Level_Raw)' in code


def test_unsupported_pid_call_is_not_offline_pass():
    from composition_check import analyze_composition
    result=analyze_composition(SiemensSCLAdapter().render_full_program(project()))
    assert result['analyzed'] is False and result['native_execution_status']=='PENDING'


def test_renamed_loop_has_no_tank_symbol_dependency():
    p=project(loop_id='OtroLazo')
    source=SiemensSCLAdapter().render_full_program(p)
    assert '"PID_OtroLazo"(' in source and 'LevelLoop' not in source


def test_configured_writer_conflict_is_rejected():
    from pid_control import resolve_pid_loops
    with pytest.raises(ValueError,match='PID_COMPOSITION_UNSUPPORTED'):
        resolve_pid_loops([request(),{'type':'analog_output','output':'AO_Fill_Command','value':20}],prepare_tank_bench(bench()),'SIEMENS_SCL_V18')


def test_cyclic_xml_derives_from_ob_export_and_contains_one_instance_call():
    import json
    from xml.etree import ElementTree as ET
    from pid_scl import render_pid_cyclic_ob
    from utils import get_project_root
    p=project()
    caps=json.loads((get_project_root()/'tests/fixtures/native_pid_v18_capabilities.json').read_text())
    root=ET.fromstring(render_pid_cyclic_ob(p,caps))
    assert root.findtext('SW.Blocks.OB/AttributeList/SecondaryType')=='CyclicInterrupt'
    assert root.findtext('SW.Blocks.OB/AttributeList/Number')=='30'
    ns={'s':'http://www.siemens.com/automation/Openness/SW/NetworkSource/StructuredText/v3'}
    calls=root.findall('.//s:CallInfo',ns)
    assert len(calls)==1 and calls[0].get('Name')=='FB_PID_LevelLoop'


def test_invalid_physical_sensor_keeps_requested_fault_alarm_on():
    p=project(mode='PHYSICAL',resources={'alarm_output':'Q_Digital_0'})
    code=p.pou.implementation_code
    assert 'Q_Digital_0 := Fault;' in code
    assert 'Q_Digital_0 := FALSE;' not in code


def test_stop_cancels_tuning_and_requires_new_request():
    from trial_experiments.scl_sim import SclMachine
    p=project();source=SiemensSCLAdapter().render_full_program(p)
    source=re.sub(r'\(\* NATIVE_PID_BEGIN \*\).*?\(\* NATIVE_PID_END \*\)',
                  'ControllerError := FALSE; CV := 40.0;',source,flags=re.S)
    machine=SclMachine(source,instance_db=p.pid_loops[0].symbols['db']);io={};machine.initialize(io);k=machine.static_key
    machine.scan(io);io[k('CmdStart')]=True;machine.scan(io)
    io[k('CmdPretune')]=True;machine.scan(io);assert io[k('TuningMode')]==1
    io[k('CmdStop')]=True;machine.scan(io);assert io[k('TuningMode')]==0 and not io[k('Running')]
    io[k('CmdStop')]=False;machine.scan(io);assert not io[k('Running')]
    io[k('CmdStart')]=False;machine.scan(io);io[k('CmdStart')]=True;machine.scan(io)
    assert io[k('Running')] and io[k('TuningMode')]==0


def test_untuned_physical_controller_starts_in_manual_zero_until_explicit_tuning():
    from trial_experiments.scl_sim import SclMachine
    p=project(mode='PHYSICAL');source=SiemensSCLAdapter().render_full_program(p)
    source=re.sub(r'\(\* NATIVE_PID_BEGIN \*\).*?\(\* NATIVE_PID_END \*\)',
                  'ControllerError := FALSE; CV := ManualValue;',source,flags=re.S)
    m=SclMachine(source,instance_db=p.pid_loops[0].symbols['db']);io={'AI_Level_Raw':13824};m.initialize(io);k=m.static_key
    m.scan(io);io[k('CmdStart')]=True;m.scan(io)
    assert io[k('Running')] and io[k('RequestedMode')]==4 and io['AO_Fill_Command']==0
    io[k('CmdPretune')]=True;m.scan(io)
    assert io[k('RequestedMode')]==1 and not io[k('ParametersConfirmed')]


def supervisor(**kwargs):
    from trial_experiments.scl_sim import SclMachine
    p=project(**kwargs);source=SiemensSCLAdapter().render_full_program(p)
    source=re.sub(r'\(\* NATIVE_PID_BEGIN \*\).*?\(\* NATIVE_PID_END \*\)',
                  'ControllerError := FALSE; CV := 80.0;',source,flags=re.S)
    m=SclMachine(source,instance_db=p.pid_loops[0].symbols['db']);io={};m.initialize(io);m.scan(io)
    return m,io,m.static_key


def test_auto_manual_conflict_latches_fault_and_requires_reset_new_start():
    m,io,k=supervisor(resources={'auto':'I_Digital_4','manual':'I_Digital_5'})
    io['I_Digital_4']=True;io['I_Digital_5']=True;io[k('CmdStart')]=True;m.scan(io)
    assert io[k('Fault')] and not io[k('Running')] and io[k('CV')]==0
    io['I_Digital_5']=False;m.scan(io);assert io[k('Fault')]
    io[k('CmdReset')]=True;m.scan(io);assert not io[k('Running')]
    io[k('CmdStart')]=False;m.scan(io);io[k('CmdStart')]=True;m.scan(io);assert io[k('Running')]


def test_manual_interrupt_cancels_tuning_until_new_request():
    m,io,k=supervisor();io[k('CmdStart')]=True;m.scan(io)
    io[k('CmdPretune')]=True;m.scan(io);assert io[k('TuningMode')]==1
    io[k('CmdManual')]=True;m.scan(io);assert io[k('TuningMode')]==0
    io[k('CmdManual')]=False;m.scan(io);assert io[k('RequestedMode')]==4


def test_digital_indications_follow_the_controller_on_every_destination():
    m,io,k=supervisor(resources={'enable_output':'Q_Digital_0','alarm_output':'Q_Digital_1'})
    io[k('CmdStart')]=True;m.scan(io);assert io[k('Running')] and io['Q_Digital_0'] is True
    io['AI_Level_Raw']=-1;m.scan(io);assert io[k('Fault')] and io['Q_Digital_1'] is True


def test_runtime_identity_changes_with_generator_logic(monkeypatch):
    import pid_scl
    first=project().metadata['pid_build_signature']
    monkeypatch.setattr(pid_scl,'pid_implementation_identity',lambda:'changed generator',raising=False)
    assert project().metadata['pid_build_signature']!=first


def test_pid_error_diagnostic_survives_native_reset_until_operator_ack():
    from trial_experiments.scl_sim import SclMachine
    p=project();source=SiemensSCLAdapter().render_full_program(p)
    source=re.sub(r'\(\* NATIVE_PID_BEGIN \*\).*?\(\* NATIVE_PID_END \*\)',
        'ControllerError := CmdManual; IF CmdManual THEN CurrentErrorBits := 512; ELSE CurrentErrorBits := 0; END_IF; CV := 80.0;',source,flags=re.S)
    m=SclMachine(source,instance_db=p.pid_loops[0].symbols['db']);io={};m.initialize(io);k=m.static_key
    m.scan(io);io[k('CmdStart')]=True;m.scan(io);io[k('CmdManual')]=True;m.scan(io)
    io[k('CmdManual')]=False;m.scan(io);m.scan(io)
    assert io[k('Fault')] and io[k('ErrorBits')]==512 and io[k('FaultCode')]==6 and io[k('CV')]==0
    io[k('CmdStart')]=False;io[k('CmdReset')]=True;m.scan(io)
    assert not io[k('Fault')] and io[k('ErrorBits')]==0 and io[k('FaultCode')]==0


def test_native_secondary_error_does_not_hide_emergency_reason():
    from trial_experiments.scl_sim import SclMachine
    p=project(resources={'emergency':'I_Digital_1'});source=SiemensSCLAdapter().render_full_program(p)
    source=re.sub(r'\(\* NATIVE_PID_BEGIN \*\).*?\(\* NATIVE_PID_END \*\)',
        'ControllerError := TRUE; CurrentErrorBits := 512; CV := 80.0;',source,flags=re.S)
    m=SclMachine(source,instance_db=p.pid_loops[0].symbols['db']);io={'I_Digital_1':True};m.initialize(io);m.scan(io)
    assert io[m.static_key('FaultCode')]==1 and io[m.static_key('ErrorBits')]==512
