"""A selector-only request must not inherit the motor template's physical actions."""
import json
from pathlib import Path

from effective_semantics import normalize_effective_semantics
from ir_builder import build_project_ir, required_external_resources
from code_generator import generate_implementation_from_ir
from platforms.siemens_scl_adapter import SiemensSCLAdapter
from trial_experiments.scl_sim import SclMachine


def raw():
    return json.loads((Path(__file__).parent/'fixtures/mode_selection_only_response.json').read_text(encoding='utf-8'))


def bench():
    return {'variables':[
        {'name':'I_Mode_Auto','class':'input','type':'BOOL','location':'%IX2.0'},
        {'name':'I_Emergency','class':'input','type':'BOOL','location':'%IX2.1'}]}


def test_selector_only_requires_no_motor_start_stop_or_second_selector():
    semantic=normalize_effective_semantics(raw(),bench(),origin='LLM')
    assert set(required_external_resources(semantic,bench()))=={'I_Mode_Auto','I_Emergency'}
    assert not ({'motor_output','trigger_input','stop_input','manual_input'} & set(semantic['parameters']))


def test_selector_only_emits_no_physical_output_and_follows_one_selector():
    semantic=normalize_effective_semantics(raw(),bench(),origin='LLM')
    project=build_project_ir(semantic,bench(),'SIEMENS_SCL_V18')
    project.pou.implementation_code=generate_implementation_from_ir(project)
    assert not any(v.var_class=='output' for v in project.pou.variables)
    # The real adapter and cycle interpreter exercise the actual generated program.
    # Rendering directly avoids allocating unrelated I/O to satisfy the legacy motor template.
    adapter=SiemensSCLAdapter()
    source=adapter.render_full_program(project)
    machine=SclMachine(source);io={};machine.initialize(io)
    for selected,emergency,expected in [(False,False,False),(True,False,True),(False,False,False),(True,True,False)]:
        io.update(I_Mode_Auto=selected,I_Emergency=emergency,I_Start=True,I_Mode_Manual=True)
        machine.scan(io)
        assert io['DB_PLC_PRG.M_AutoMode'] is expected
        assert io['DB_PLC_PRG.M_ManualMode'] is (not expected)
        assert 'Q_Motor_Enable' not in io


def test_explicit_actuator_command_keeps_the_existing_motor_contract():
    payload=raw();payload['parameters'].update(motor_output='Q_Motor_Enable',manual_command_input='I_Manual_Command')
    payload['functional_requirements'][1]['commands']=[{'input':'I_Manual_Command','output':'Q_Motor_Enable'}]
    semantic=normalize_effective_semantics(payload,bench(),origin='LLM')
    assert 'Q_Motor_Enable' in required_external_resources(semantic,bench())


def test_selector_marker_cannot_override_an_actuator_request():
    payload=raw();payload['parameters'].update(motor_output='Q_Motor_Enable',_mode_selection_only=True)
    semantic=normalize_effective_semantics(payload,bench(),origin='LLM')
    assert semantic['parameters'].get('_mode_selection_only') is not True


def test_legacy_mode_template_is_preserved_without_selector_only_operation():
    payload=raw();payload.pop('operation_type')
    semantic=normalize_effective_semantics(payload,bench(),origin='LLM')
    assert 'Q_Motor_Enable' in required_external_resources(semantic,bench())


def test_shared_product_interprets_and_packages_the_recorded_response(tmp_path, intents_catalog, safety_rules):
    from product_engine import interpret_product_command,generate_product_package
    payload=raw();source=bench()
    parsed=interpret_product_command(payload['command_text'],io_map=source,intents_catalog=intents_catalog,
        safety_rules=safety_rules,mode='llm',llm_response_text=payload)
    assert parsed['semantic_validation']['is_valid'],parsed['semantic_validation']
    result=generate_product_package(parsed,target_platform='SIEMENS_SCL_V18',io_map=source,
        intents_catalog=intents_catalog,safety_rules=safety_rules,output_dir=tmp_path)
    assert result['verification']['is_valid'],result['verification']
    variables=json.loads((Path(result['package_dir'])/'variables.json').read_text(encoding='utf-8'))
    assert not any(v.get('class')=='output' for v in variables)


def test_selector_and_internal_memories_use_the_given_names():
    payload=raw();payload['parameters'].update(auto_input='I_Selector_A',auto_mode_memory='M_Auto_A',manual_mode_memory='M_Manual_A')
    for requirement in payload['functional_requirements']:requirement['mode_input']='I_Selector_A'
    source=bench();source['variables'][0]['name']='I_Selector_A'
    semantic=normalize_effective_semantics(payload,source,origin='LLM')
    assert set(required_external_resources(semantic,source))=={'I_Selector_A','I_Emergency'}
    project=build_project_ir(semantic,source,'SIEMENS_SCL_V18')
    project.pou.implementation_code=generate_implementation_from_ir(project)
    assert 'M_Auto_A := I_Selector_A' in project.pou.implementation_code
    assert 'M_Manual_A := NOT M_Auto_A' in project.pou.implementation_code


def test_request_with_manual_actuation_does_not_become_selector_only():
    payload=raw();payload['functional_requirements'][1]['commands']=[{'input':'I_Manual','output':'Q_Pump','behavior':'maintained'}]
    payload['parameters'].update(manual_command_input='I_Manual',motor_output='Q_Pump')
    semantic=normalize_effective_semantics(payload,bench(),origin='LLM')
    assert semantic['parameters'].get('_mode_selection_only') is not True


def test_missing_selector_parameter_never_falls_back_to_motor_defaults():
    payload=raw();payload['parameters'].pop('auto_input')
    semantic=normalize_effective_semantics(payload,bench(),origin='LLM')
    assert semantic['effective_semantics']['status']=='UNRESOLVED'
    assert not {'motor_output','trigger_input','stop_input'} & set(semantic['parameters'])


def test_two_selector_form_is_rejected_before_motor_defaults():
    payload=raw();payload['parameters']['manual_input']='I_Manual_Selector'
    payload['functional_requirements'][1]['mode_input']='I_Manual_Selector'
    semantic=normalize_effective_semantics(payload,bench(),origin='LLM')
    assert semantic['effective_semantics']['status']=='UNRESOLVED'
    assert not {'motor_output','trigger_input','stop_input'} & set(semantic['parameters'])


def test_incomplete_selector_is_blocked_by_shared_product_before_generation(intents_catalog,safety_rules):
    from product_engine import interpret_product_command,is_generatable_product
    payload=raw();payload['parameters'].pop('auto_input')
    parsed=interpret_product_command(payload['command_text'],io_map=bench(),intents_catalog=intents_catalog,
        safety_rules=safety_rules,mode='llm',llm_response_text=payload)
    assert not is_generatable_product(parsed)
    assert parsed['semantic_validation']['is_valid'] is False
