import copy
import importlib
import importlib.util
import json
from pathlib import Path

import pytest
from schemas import SemanticOutput, LLMUsageMetadata
from test_normal_control_strategy import mapped, semantic
from test_native_pid_resolution import request
from semantic_validator import validate_semantic_output
from llm_parser import parse_command


def engine():
    assert importlib.util.find_spec('product_engine'), 'Shared product entry is missing'
    return importlib.import_module('product_engine')


class Client:
    def __init__(self,value): self.value=value;self.contexts=[]
    def is_configured(self): return True
    def interpret_command(self,text,context):
        self.contexts.append(copy.deepcopy(context))
        if isinstance(self.value,Exception):raise self.value
        return SemanticOutput.model_validate({k:v for k,v in self.value.items() if k in SemanticOutput.model_fields}),LLMUsageMetadata(provider='offline')


def invoke(api,value,catalog,rules,**kwargs):
    return api.interpret_product_command(value['command_text'],io_map=mapped(),intents_catalog=catalog,
                                        safety_rules=rules,mode='llm',**kwargs)


def test_product_request_uses_current_normal_policy(intents_catalog,safety_rules):
    api=engine();value=semantic('Mantén el nivel al 50 % mediante PID con la válvula proporcional.',[request()])
    client=Client(value)
    result=invoke(api,value,intents_catalog,safety_rules,llm_client=client)
    assert result['interaction_profile']=='normal'
    assert result['product_engine']=={'schema_version':1,'engine_id':api.ENGINE_ID}
    assert result['semantic_validation']['is_valid']
    assert client.contexts[0]['normal_mode_policy']
    assert client.contexts[0]['requested_control_behavior']=='CONTINUOUS'


@pytest.mark.parametrize('fallback',[False,True])
def test_product_retry_and_rule_fallback_keep_control_constraints(fallback,intents_catalog,safety_rules,monkeypatch):
    import llm_parser
    settings=llm_parser.load_parser_settings()
    # Exercise both policies explicitly; the application default disables fallback.
    monkeypatch.setattr(llm_parser,'load_parser_settings',lambda config_path=None:{**settings,'allow_rule_fallback':fallback})
    api=engine();value=semantic('Sin PID, llena hasta el 80 % y detén la bomba.',[request()])
    client=Client(RuntimeError('offline failure') if fallback else value)
    result=invoke(api,value,intents_catalog,safety_rules,llm_client=client)
    assert result['interaction_profile']=='normal'
    assert not result['semantic_validation']['is_valid']
    if not fallback:assert any('CONTROL_STRATEGY' in e for e in result['semantic_validation']['errors'])


def test_product_bindings_survive_provisional_allocation(intents_catalog,safety_rules):
    api=engine();io=mapped()
    next(v for v in io['variables'] if v['name']=='Q_Digital_2')['state']='FREE'
    original=copy.deepcopy(io)
    value=semantic('Con marcha activa la salida.',[{'type':'conditional_output','condition':'I_Digital_1','outputs':['Q_New']}])
    value['semantic_validation']=validate_semantic_output(value,io,intents_catalog,safety_rules)
    proposals=value['semantic_validation']['io_assignment_proposals']
    assert proposals
    bound,working,history=api.resolve_product_assignments(value,io,proposals,intents_catalog,safety_rules)
    assert bound['semantic_validation']['is_valid'],bound
    assert any(v['name']=='Q_New' for v in working['variables'])
    assert io==original and history
    with pytest.raises(ValueError,match='blocked|bloquead'):
        api.resolve_product_assignments(value,io,[{'blocked':True}],intents_catalog,safety_rules)


def test_product_composition_acceptance_requires_valid_logic():
    api=engine();value=semantic('Activa salida.',[{'type':'conditional_output','condition':'I_Digital_1','outputs':['Q_Digital_1']}])
    value['semantic_validation']={'is_valid':True}
    assert api.is_generatable_product(value)
    assert not api.is_generatable_product({**value,'functional_requirements':[]})
    assert not api.is_generatable_product({**value,'semantic_validation':{'is_valid':False}})


def test_product_metadata_never_enters_llm_response_schema(intents_catalog,safety_rules):
    api=engine();value=semantic('Mantén el nivel al 50 % mediante PID.',[request()]);client=Client(value)
    invoke(api,value,intents_catalog,safety_rules,llm_client=client)
    assert 'product_engine' not in SemanticOutput.model_fields
    assert 'product_engine' not in client.contexts[0]
    assert not {'oracle','semantic_expectations','variant_id','work_mode','experiment_phase'} & client.contexts[0].keys()


def test_legacy_parser_contract_is_unchanged(intents_catalog,safety_rules):
    engine();value=semantic('Establece la consigna en 50 %.',[{'type':'set_level_setpoint','value':50}],'INT_PID_SUPERVISOR')
    value.pop('interaction_profile')
    result=parse_command(value['command_text'],mode='llm',io_map=mapped(),intents_catalog=intents_catalog,
                         safety_rules=safety_rules,llm_response_text=value)
    assert result['semantic_validation']['is_valid']
    assert 'product_engine' not in result and result.get('interaction_profile')!='normal'


def test_product_generated_metadata_records_engine(tmp_path,intents_catalog,safety_rules):
    api=engine();value=semantic('Mantén el nivel al 50 % mediante PID.',[request()])
    parsed=invoke(api,value,intents_catalog,safety_rules,llm_response_text=value)
    result=api.generate_product_package(parsed,target_platform='SIEMENS_SCL_V18',io_map=mapped(),
        intents_catalog=intents_catalog,safety_rules=safety_rules,output_dir=tmp_path)
    assert result['verification']['is_valid'],result['verification']
    metadata=json.loads((Path(result['package_dir'])/'generation_metadata.json').read_text())
    assert metadata['product_engine']['engine_id']==api.ENGINE_ID
