"""Regressions for the captured 30/80 % valve command, through generated SCL."""
import copy
import json
from pathlib import Path
import pytest
from test_analog_sequence import bench, build as build_sequence

FIX=Path(__file__).parent/'fixtures/natural_commands/hysteresis_analog_incident.json'

def response():
    return json.loads(FIX.read_text(encoding='utf-8'))

def build(value=None, io_map=None):
    return build_sequence(value or response(),io_map or bench())

def test_captured_command_is_numeric_hysteresis_without_pid():
    ir,plc,io=build()
    assert not ir.pid_loops
    assert io['AO_Fill_Command']==0
    io['I_Start']=True;plc.scan(io)
    assert io['AO_Fill_Command']==27648
    io['I_Start']=False
    io['AI_Level_Raw']=13824;plc.scan(io)
    assert io['AO_Fill_Command']==27648
    io['AI_Level_Raw']=23501;plc.scan(io)
    assert io['AO_Fill_Command']==0
    io['AI_Level_Raw']=13824;plc.scan(io)
    assert io['AO_Fill_Command']==0
    io['AI_Level_Raw']=5530;plc.scan(io)
    assert io['AO_Fill_Command']==27648

@pytest.mark.parametrize('stop',['I_Stop','I_Emergency'])
def test_disabled_control_never_fills_and_needs_a_new_start(stop):
    _,plc,io=build()
    for _ in range(3):plc.scan(io)
    assert io['AO_Fill_Command']==0
    io['I_Start']=True;plc.scan(io)
    io['I_Start']=False;plc.scan(io)
    io[stop]=True;plc.scan(io)
    assert io['AO_Fill_Command']==0
    io[stop]=False
    for _ in range(3):plc.scan(io)
    assert io['AO_Fill_Command']==0
    io['I_Start']=True;plc.scan(io)
    assert io['AO_Fill_Command']==27648

@pytest.mark.parametrize('field,value',[('on_value',None),('off_value',None),('on_value',True),('off_value',float('nan')),('on_value',101),('output_unit','m')])
def test_numeric_hysteresis_rejects_missing_or_invalid_command(field,value):
    data=response();data['functional_requirements'][1][field]=value
    with pytest.raises(ValueError,match='ANALOG_'):build(data)

def test_numeric_hysteresis_cannot_compete_with_another_output_owner():
    data=response();data['functional_requirements'].append({'type':'analog_output','output':'AO_Fill_Command','value':50,'unit':'%'})
    with pytest.raises(ValueError,match='ANALOG_MULTIPLE_WRITERS'):build(data)

def test_analog_hysteresis_preserves_calibration_guard():
    with pytest.raises(ValueError,match='ANALOG_CONFIGURATION_REQUIRED'):build(io_map=bench(False))

def test_disable_uses_configured_safe_value_instead_of_the_operating_off_value():
    data=response();data['functional_requirements'][1]['off_value']=20
    _,plc,io=build(data)
    assert io['AO_Fill_Command']==0
    io['I_Start']=True;plc.scan(io)
    io['AI_Level_Raw']=23501;plc.scan(io)
    assert io['AO_Fill_Command']==5530
    io['I_Stop']=True;plc.scan(io)
    assert io['AO_Fill_Command']==0

def test_held_start_cannot_restart_after_stop_is_released():
    _,plc,io=build()
    io['I_Start']=True;plc.scan(io)
    io['I_Stop']=True;plc.scan(io)
    io['I_Stop']=False;plc.scan(io)
    assert io['AO_Fill_Command']==0
    io['I_Start']=False;plc.scan(io)
    io['I_Start']=True;plc.scan(io)
    assert io['AO_Fill_Command']==27648

def test_physical_enable_condition_is_declared_without_a_separate_latch():
    data=response();data['functional_requirements']=[data['functional_requirements'][1]]
    data['functional_requirements'][0]['enable_condition']='I_Start'
    _,plc,io=build(data)
    assert io['AO_Fill_Command']==0
    io['I_Start']=True;plc.scan(io)
    assert io['AO_Fill_Command']==27648
    io['I_Start']=False;plc.scan(io)
    assert io['AO_Fill_Command']==0
