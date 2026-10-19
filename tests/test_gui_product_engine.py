import copy
import json
from pathlib import Path

import pytest
import gui
import product_engine as P
from test_product_engine import Client
from test_normal_control_strategy import mapped,semantic
from test_native_pid_resolution import request
from test_phase1_download_and_trials import pipeline,_arm_experiment_trial
from test_execute_full_pipeline import temp_map,_tia_ready

REAL_ENTRY=gui.parse_command


def configure(app,monkeypatch,value,catalog,rules):
    client=Client(value)
    monkeypatch.setattr(gui,'parse_command',REAL_ENTRY)
    monkeypatch.setattr(app,'_load_runtime_configuration',lambda:(copy.deepcopy(mapped()),catalog,rules))
    monkeypatch.setattr(app,'save_io_map',lambda **kw:True)
    monkeypatch.setattr(app,'_refresh_llm_client_status',lambda **kw:{'llm_configured':True})
    monkeypatch.setattr(app,'_refresh_experiment_status',lambda:None)
    app.parser_mode_var.set('LLM');app.llm_client=client
    app.command_textbox.delete('1.0','end');app.command_textbox.insert('1.0',value['command_text'])
    return client


def simple():
    return semantic('Activa la salida mientras marcha está pulsada.',[
        {'type':'conditional_output','condition':'I_Digital_1','outputs':['Q_Digital_1']}])


def test_normal_and_experiment_share_product_request(pipeline,monkeypatch,intents_catalog,safety_rules):
    app=pipeline['app'];client=configure(app,monkeypatch,simple(),intents_catalog,safety_rules)
    contexts=[]
    for mode in ['Normal','Experimentacion']:
        app.work_mode_var.set(mode)
        assert app.process_command(),app.pending_semantic_output
        assert app.pending_semantic_output['product_engine']['engine_id']==P.ENGINE_ID
        contexts.append(client.contexts[-1])
    assert contexts[0]==contexts[1]


def test_experiment_accepts_valid_composition_with_unknown_intent(pipeline,monkeypatch,intents_catalog,safety_rules):
    app=pipeline['app'];configure(app,monkeypatch,simple(),intents_catalog,safety_rules)
    app.work_mode_var.set('Experimentacion')
    assert app.process_command()
    assert app.pending_semantic_output['intent_id']=='INT_UNKNOWN'


@pytest.mark.parametrize('command',[
    'Llena hasta el 80 % y detén la bomba.',
    'Regula con PID el nivel al 50 % usando una bomba de velocidad variable.',
])
def test_both_modes_reject_unbound_measurement_and_wrong_actuator(command,pipeline,monkeypatch,intents_catalog,safety_rules):
    app=pipeline['app'];value=semantic(command,[request()]);configure(app,monkeypatch,value,intents_catalog,safety_rules)
    validations=[]
    monkeypatch.setattr(app,'_resolve_semantic_ambiguity',lambda *a:False)
    for mode in ['Normal','Experimentacion']:
        app.work_mode_var.set(mode)
        assert app.process_command() is False
        validations.append(app.pending_semantic_output['semantic_validation']['errors'])
    assert validations[0]==validations[1] and any('CONTROL_' in e for e in validations[0])


def test_trial_clarification_stays_unanswered(pipeline,monkeypatch,intents_catalog,safety_rules):
    app=pipeline['app'];directory=_arm_experiment_trial(app)
    value=simple();value.update(requires_clarification=True,clarification_question='¿Cuándo debe comenzar?')
    client=configure(app,monkeypatch,value,intents_catalog,safety_rules)
    dialogs=[]
    with app._unattended_interactions(dialogs):assert app.process_command() is False
    record=json.loads((directory/'trial.json').read_text())
    assert record['clarification_requested'] and not record['clarification_answered']
    assert len(client.contexts)==1


def test_normal_keeps_explicit_extension_context(pipeline,monkeypatch,intents_catalog,safety_rules):
    app=pipeline['app'];client=configure(app,monkeypatch,simple(),intents_catalog,safety_rules)
    app.work_mode_var.set('Normal')
    prior={'command_text':'Programa previo','intent_id':'INT_UNKNOWN','parameters':{},'functional_requirements':[]}
    def scope(text,io):
        app._normal_program_context={'scope':'EXTEND_PROGRAM','llm_context':prior,'working_map':io}
        return io
    monkeypatch.setattr(app,'_prepare_program_scope',scope)
    assert app.process_command()
    assert client.contexts[0]['current_program']==prior


def test_trial_allocation_never_commits_user_map(pipeline,monkeypatch,tmp_path):
    app=pipeline['app'];directory=_arm_experiment_trial(app)
    source=tmp_path/'scenario.json';source.write_text(json.dumps(mapped()))
    original=source.read_bytes()
    monkeypatch.setattr(app,'_experiment_base_map_source',lambda:(source,None))
    assert app._prepare_trial_working_map()
    reference=app.active_trial['new_trial']['io_map']
    assert reference.get('map_policy')==P.MAP_POLICY
    assert json.loads((directory/'trial.json').read_text())['io_map']['map_policy']==P.MAP_POLICY
    working=json.loads(Path(reference['working_map_path']).read_text())
    assert any(v['name']=='AI_Level_Raw' for v in working['variables'])
    assert source.read_bytes()==original
