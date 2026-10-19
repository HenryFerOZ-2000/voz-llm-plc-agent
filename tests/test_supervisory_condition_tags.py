import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src')]
from functional_resources import condition_identifiers
from schemas import SemanticOutput
import pytest

def test_known_pid_contract_names_can_appear_in_signal_expressions():
    assert condition_identifiers('Level_PV > 90')==['Level_PV']
    assert condition_identifiers('Auto_Mode AND NOT Sensor_Fault')==['Auto_Mode','Sensor_Fault']
    assert condition_identifiers('Level_PV >= 0 AND Level_PV <= 100')==['Level_PV']
    assert condition_identifiers('Level_Unknown > 90') is None
    assert condition_identifiers('Level_PV; Q_Pump := TRUE') is None

def test_semantic_model_accepts_declared_pid_contract_names_but_not_arbitrary_names():
    parsed=SemanticOutput(command_text='Alarma sobre 90 %',recognized_tags=['Level_PV','Q_Alarm'])
    assert parsed.recognized_tags==['Level_PV','Q_Alarm']
    with pytest.raises(ValueError,match='invalid PLC tag'):
        SemanticOutput(command_text='Alarma',recognized_tags=['Level_Unknown'])


def test_generic_comparison_declares_its_mapped_measurement_in_generated_fb(project_root,tmp_path,intents_catalog,safety_rules):
    import json
    from pathlib import Path
    import product_engine as engine
    from test_pid_supervisor import _semantic_output
    mapping=json.loads((project_root/'data/plc_maps/mapa_desarrollo_supervision_nivel.json').read_text(encoding='utf-8'))
    command='Activa la alarma de nivel alto mientras el nivel esté por encima del 90 %.'
    response=_semantic_output('P04',command,[{'type':'conditional_output','condition':'Level_PV > 90',
        'condition_unit':'%','outputs':['Q_High_Level_Alarm']}])
    response.update(intent_id='INT_UNKNOWN',case_id=None,recognized_tags=['Level_PV','Q_High_Level_Alarm'])
    semantic=engine.interpret_product_command(command,io_map=mapping,intents_catalog=intents_catalog,
        safety_rules=safety_rules,mode='llm',llm_response_text=response)
    proposals=semantic['semantic_validation']['io_assignment_proposals']
    semantic,mapping,_=engine.resolve_product_assignments(semantic,mapping,proposals,intents_catalog,safety_rules)
    result=engine.generate_product_package(semantic,target_platform='SIEMENS_SCL_V18',io_map=mapping,
        intents_catalog=intents_catalog,safety_rules=safety_rules,output_dir=tmp_path)
    package=Path(result['package_dir']);variables=json.loads((package/'variables.json').read_text(encoding='utf-8'))
    pv=[v for v in variables if v['name']=='Level_PV']
    assert len(pv)==1 and pv[0]['type']=='REAL' and pv[0]['source']=='plc_map'
    source=(package/'siemens_source.scl').read_text(encoding='utf-8')
    assert '#Level_PV > 90' in source
