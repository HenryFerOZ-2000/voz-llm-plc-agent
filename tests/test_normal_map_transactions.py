"""
MODO NORMAL — el mapa PLC solo cambia con un programa generado y verificado (asignacion transaccional).

Regla: SEMANTICA -> VALIDACION -> REQUISITOS DE RECURSOS -> ASIGNACION PROVISIONAL (copia en memoria) -> IR -> SCL ->
VERIFICACION -> COMMIT del mapa. Cualquier fallo antes del commit (INT_UNKNOWN, aclaracion, falta de hardware,
generacion/verificacion fallida) deja el mapa EXACTAMENTE como estaba. Un rol funcional (tanque, valvula, sensor)
con nombre nuevo es un requisito de recurso del programa, nunca MAP_CONFIG; solo una direccion dicha por el usuario
("usa %QX8.1 para ...") es configuracion explicita del mapa.

Experimentacion no usa este flujo (working map congelado del ensayo).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import gui  # noqa: E402
import normal_interaction as NI
import project_packager
from trial_experiments.scl_sim import SclMachine  # noqa: F401
from utils import load_json_file

from test_execute_full_pipeline import temp_map, _tia_ready  # noqa: F401,E402
from test_experiment_working_io_map import _use_bench_copy  # noqa: E402
from test_normal_functional_composition import normal, _script  # noqa: F401,E402
from test_normal_mode_hardening import _bench, _interpret, _llm, _Plc, _program, _seq, save_json_file  # noqa: E402
from test_phase1_download_and_trials import pipeline  # noqa: F401,E402

TWO_TANKS = ("Cuando presione Start, comienza a llenar el tanque 1. Cuando el sensor de nivel alto del tanque 1 se "
             "active, detén su llenado y comienza el vaciado del tanque 1 mientras llenas el tanque 2. Cuando el sensor "
             "de nivel alto del tanque 2 se active, finaliza el proceso. Stop debe detener todo inmediatamente.")
TANK_OUTPUTS = ("Q_Fill_Valve_Tank_1", "Q_Drain_Valve_Tank_1", "Q_Fill_Valve_Tank_2")
TWO_TANK_REQUIREMENTS = [_seq([
    {"outputs": ["Q_Fill_Valve_Tank_1"], "advance_on": "I_Level_High_Tank_1"},
    {"outputs": ["Q_Drain_Valve_Tank_1", "Q_Fill_Valve_Tank_2"], "advance_on": "I_Level_High_Tank_2"},
], start_input="I_Start", stop_input="I_Stop", repeat="once")]


def _identity(path: Path) -> list[tuple[Any, ...]]:
    """Lo que define el mapa fisico: direccion, nombre y estado de cada canal (+ historial de cambios)."""
    data = load_json_file(Path(path))
    return [(v.get("location"), v.get("name"), v.get("state")) for v in data["variables"]] + [("history", len(data.get("history") or []))]


@pytest.fixture
def bench(normal, tmp_path):
    """Banco propio con canales FREE como mapa activo de la GUI (nunca el mapa vivo del usuario)."""
    path = tmp_path / "bench.json"
    save_json_file(path, _bench())
    _use_bench_copy(normal["app"], path)
    normal["app"].save_io_map(show_success=False)  # la tabla de la GUI ya normalizada en el archivo
    return path


@pytest.fixture
def logs(normal, monkeypatch):
    lines: list[str] = []
    original = normal["app"]._log
    monkeypatch.setattr(normal["app"], "_log", lambda message, *a, **k: (lines.append(str(message)), original(message))[1])
    return lines


def _events(lines: list[str], event: str) -> list[str]:
    return [line for line in lines if line.startswith(f"[{event}]")]


def _real_generation(monkeypatch, tmp_path: Path) -> list[dict[str, Any]]:
    """Generacion REAL (IR + SCL + verificador) en tmp; el resto del pipeline sigue simulado por el fixture."""
    real = project_packager.generate_project_package
    produced: list[dict[str, Any]] = []
    monkeypatch.setattr(gui, "generate_project_package",
                        lambda **kwargs: produced.append(real(**{**kwargs, "output_dir": tmp_path / "generated"})) or produced[-1])
    return produced


# ---------------------------------------------------------------------------------------------
# 12 / 17: comando de dos tanques -> logica PLC (no MAP_CONFIG); commit solo con el programa verificado
# ---------------------------------------------------------------------------------------------

def test_two_tank_command_is_program_logic_not_map_config():
    semantic = _interpret(TWO_TANKS, _llm(TWO_TANKS, TWO_TANK_REQUIREMENTS), _bench())
    operation = NI.classify_map_operation(semantic)
    assert operation["kind"] == NI.MAP_OPERATION_PROGRAM and operation["has_logic"]
    assert operation["explicit"] == [] and len(operation["implicit"]) == 5  # 2 sensores + 3 valvulas: requisitos
    assert semantic["semantic_validation"]["requires_clarification"] is False


def test_two_tank_sequence_behaviour_with_global_stop(tmp_path):
    result = _program(TWO_TANKS, TWO_TANK_REQUIREMENTS, tmp_path)
    plc = _Plc(result["scl"])
    plc.press("I_Start")
    assert plc.on(*TANK_OUTPUTS) == {"Q_Fill_Valve_Tank_1"}
    plc.run(30000)
    assert plc.on(*TANK_OUTPUTS) == {"Q_Fill_Valve_Tank_1"}  # espera el nivel alto, sin tiempo
    plc.set(I_Level_High_Tank_1=True)
    plc.run(20)
    assert plc.on(*TANK_OUTPUTS) == {"Q_Drain_Valve_Tank_1", "Q_Fill_Valve_Tank_2"}  # acciones simultaneas
    plc.set(I_Level_High_Tank_2=True)
    plc.run(20)
    assert plc.on(*TANK_OUTPUTS) == set()  # fin del proceso: todo apagado
    plc.set(I_Level_High_Tank_1=False, I_Level_High_Tank_2=False)
    plc.press("I_Start")
    plc.run(100)
    plc.set(I_Level_High_Tank_1=True)
    plc.run(20)
    plc.press("I_Stop")
    assert plc.on(*TANK_OUTPUTS) == set()  # Stop global prioritario en cualquier etapa


def test_successful_operation_commits_and_map_matches_program(normal, bench, logs, monkeypatch, tmp_path):
    app, state = normal["app"], normal["state"]
    before = _identity(bench)
    semantic = _interpret(TWO_TANKS, _llm(TWO_TANKS, TWO_TANK_REQUIREMENTS), load_json_file(bench))
    _script(monkeypatch, state, [semantic])
    produced = _real_generation(monkeypatch, tmp_path)

    assert app.process_command() is True
    assert _identity(bench) == before  # tras la semantica: solo asignacion PROVISIONAL
    assert _events(logs, "NORMAL_IO_PROVISIONAL") and not _events(logs, "NORMAL_IO_COMMIT")
    assert not any("no incluia logica PLC adicional" in m for m in state["infos"])

    assert app.generate_package() is True
    committed = load_json_file(bench)
    by_name = {v["name"]: v for v in committed["variables"]}
    assert all(name in by_name for name in (*TANK_OUTPUTS, "I_Level_High_Tank_1", "I_Level_High_Tank_2"))
    assert len(committed["history"]) == 5 and _events(logs, "NORMAL_IO_COMMIT")
    # Mapa <-> programa: cada E/S externa del programa generado esta en el mapa con la MISMA direccion.
    variables = json.loads((Path(produced[-1]["package_dir"]) / "variables.json").read_text(encoding="utf-8"))
    external = [v for v in variables if str(v.get("name", "")).startswith(("I_", "Q_", "AI_", "AO_"))]
    assert external and all(by_name[v["name"]]["location"] == v["location"] for v in external)
    assert {row["name"] for row in app._collect_io_variables()} >= set(TANK_OUTPUTS)  # tabla de la GUI al dia


# ---------------------------------------------------------------------------------------------
# 13 / 9: semantica fallida (INT_UNKNOWN) -> ningun efecto persistente
# ---------------------------------------------------------------------------------------------

def test_int_unknown_never_changes_the_map(normal, bench, logs, monkeypatch):
    app, state = normal["app"], normal["state"]
    before = _identity(bench)
    # Reproduce la ejecucion real (12:57): INT_UNKNOWN + requisitos no generables + tags nuevos con propuestas.
    unknown = _llm(TWO_TANKS, [{"type": "motor_start_latch", "target": "Q_Fill_Valve_Tank_1"},
                               {"type": "motor_start_latch", "target": "Q_Drain_Valve_Tank_1"}],
                   parameters={"trigger_input": "I_Start", "tank_1_fill_output": "Q_Fill_Valve_Tank_1",
                               "tank_1_drain_output": "Q_Drain_Valve_Tank_1"})
    semantic = _interpret(TWO_TANKS, unknown, load_json_file(bench))
    assert semantic["intent_id"] == "INT_UNKNOWN" and semantic["semantic_validation"]["io_assignment_proposals"]
    _script(monkeypatch, state, [semantic])

    assert app.process_command() is False
    assert _identity(bench) == before
    assert app._pending_map_transaction is None
    assert not any("no incluia logica PLC adicional" in m for m in state["infos"] + state["errors"])


def test_requires_clarification_with_proposals_does_not_touch_the_map(normal, bench, logs, monkeypatch):
    """El caso real: requires_clarification=True con tags nuevos -> antes se escribia el mapa y luego se preguntaba."""
    app, state = normal["app"], normal["state"]
    before = _identity(bench)
    asking = _llm(TWO_TANKS, [], intent="INT_UNKNOWN", parameters={"tank_2_fill_output": "Q_Fill_Valve_Tank_2"},
                  question="¿El llenado del tanque 2 empieza junto con el vaciado del tanque 1?")
    semantic = _interpret(TWO_TANKS, asking, load_json_file(bench))
    assert semantic["semantic_validation"]["io_assignment_proposals"]  # habia propuestas...
    _script(monkeypatch, state, [semantic])
    state["answers"] = []  # el usuario cancela
    assert app.process_command() is False
    assert len(state["dialogs"]) == 1
    assert _identity(bench) == before  # ...pero ninguna se persistio


# ---------------------------------------------------------------------------------------------
# 14 / 10: aclaracion -> ningun recurso hasta tener semantica completa
# ---------------------------------------------------------------------------------------------

def test_clarification_keeps_map_intact_until_semantics_are_complete(normal, bench, logs, monkeypatch, tmp_path):
    app, state = normal["app"], normal["state"]
    before = _identity(bench)
    ambiguous = _interpret("Haz el proceso de dos tanques.",
                           _llm("x", [_seq([{"outputs": ["Q_Fill_Valve_Tank_1"]}, {"outputs": ["Q_Fill_Valve_Tank_2"]}])]),
                           load_json_file(bench))
    complete = _interpret(TWO_TANKS, _llm(TWO_TANKS, TWO_TANK_REQUIREMENTS), load_json_file(bench))
    assert ambiguous["semantic_validation"]["requires_clarification"] is True
    map_during_question: list[Any] = []

    class _Dialog:
        def __init__(self, parent, question):
            state["dialogs"].append(question)
            map_during_question.append(_identity(bench))
            self.result = "Con Start llena el tanque 1 hasta su nivel alto; luego vacía el 1 y llena el 2 hasta su nivel alto."

    monkeypatch.setattr(gui, "ClarificationDialog", _Dialog)
    _script(monkeypatch, state, [ambiguous, complete])
    _real_generation(monkeypatch, tmp_path)

    assert app.process_command() is True
    assert map_during_question == [before]  # mientras se pregunta, el mapa no se toca
    assert _identity(bench) == before  # tras responder: solo provisional
    rollbacks_before_answer = [line for line in logs if "NORMAL_IO_PROVISIONAL" in line]
    assert len(rollbacks_before_answer) == 1  # la asignacion empezo DESPUES de la respuesta
    assert app.generate_package() is True
    assert _identity(bench) != before  # recien ahora se confirma


# ---------------------------------------------------------------------------------------------
# 15: recursos insuficientes -> SYSTEM_CAPABILITY_GAP sin reasignacion parcial
# ---------------------------------------------------------------------------------------------

def test_insufficient_outputs_leave_no_partial_assignment(normal, monkeypatch, tmp_path, logs):
    app, state = normal["app"], normal["state"]
    path = tmp_path / "small.json"
    save_json_file(path, _bench(free_do=2))  # 3 valvulas necesarias, 2 DO libres
    _use_bench_copy(app, path)
    app.save_io_map(show_success=False)
    before = _identity(path)
    semantic = _interpret(TWO_TANKS, _llm(TWO_TANKS, TWO_TANK_REQUIREMENTS), load_json_file(path))
    assert semantic["semantic_validation"]["capability_gap"]["shortages"][0]["required"] == 3
    _script(monkeypatch, state, [semantic])
    assert app.process_command() is False
    assert _identity(path) == before and app._pending_map_transaction is None
    assert any("SYSTEM_CAPABILITY_GAP" in m for m in state["errors"]) and state["dialogs"] == []


# ---------------------------------------------------------------------------------------------
# 16: generacion/verificacion fallida -> rollback
# ---------------------------------------------------------------------------------------------

def test_failed_verification_rolls_back_the_provisional_assignment(normal, bench, logs, monkeypatch):
    app, state, pipeline_state = normal["app"], normal["state"], normal["pipeline"]["state"]
    before = _identity(bench)
    _script(monkeypatch, state, [_interpret(TWO_TANKS, _llm(TWO_TANKS, TWO_TANK_REQUIREMENTS), load_json_file(bench))])
    pipeline_state["verification_valid"] = False
    assert app.process_command() is True
    assert app.generate_package() is False
    assert _identity(bench) == before and app._pending_map_transaction is None
    assert _events(logs, "NORMAL_IO_ROLLBACK") and not _events(logs, "NORMAL_IO_COMMIT")
    assert NI.ROLLBACK_MESSAGE in state["errors"]  # "No se aplicaron cambios al mapa debido a un error..."
    assert not any("Configuracion de mapa aplicada" in line or "Configuración de mapa aplicada" in line for line in logs)


def test_generation_exception_rolls_back(normal, bench, logs, monkeypatch):
    app, state = normal["app"], normal["state"]
    before = _identity(bench)
    _script(monkeypatch, state, [_interpret(TWO_TANKS, _llm(TWO_TANKS, TWO_TANK_REQUIREMENTS), load_json_file(bench))])

    def _boom(**kwargs):
        raise RuntimeError("fallo simulado del generador SCL")

    monkeypatch.setattr(gui, "generate_project_package", _boom)
    assert app.process_command() is True
    assert app.generate_package() is False
    assert _identity(bench) == before and _events(logs, "NORMAL_IO_ROLLBACK")


def test_full_pipeline_failure_after_semantics_leaves_map_intact(normal, bench, monkeypatch):
    """EJECUTAR COMANDO completo: semantica OK + asignacion provisional OK + verificacion FAIL -> sin cambios ni TIA."""
    app, state, pipeline_state = normal["app"], normal["state"], normal["pipeline"]["state"]
    before = _identity(bench)
    _script(monkeypatch, state, [_interpret(TWO_TANKS, _llm(TWO_TANKS, TWO_TANK_REQUIREMENTS), load_json_file(bench))])
    pipeline_state["verification_valid"] = False
    app.execute_full_pipeline()
    assert _identity(bench) == before


def test_new_command_discards_an_unconsumed_provisional_assignment(normal, bench, logs, monkeypatch):
    app, state = normal["app"], normal["state"]
    before = _identity(bench)
    semantic = _interpret(TWO_TANKS, _llm(TWO_TANKS, TWO_TANK_REQUIREMENTS), load_json_file(bench))
    _script(monkeypatch, state, [semantic, semantic])
    assert app.process_command() is True and app._pending_map_transaction is not None
    assert app.process_command() is True  # otro comando antes de generar
    assert any("comando nuevo" in line for line in _events(logs, "NORMAL_IO_ROLLBACK"))
    assert _identity(bench) == before


def test_map_changed_during_operation_is_never_overwritten(normal, bench, logs, monkeypatch, tmp_path):
    app, state = normal["app"], normal["state"]
    _script(monkeypatch, state, [_interpret(TWO_TANKS, _llm(TWO_TANKS, TWO_TANK_REQUIREMENTS), load_json_file(bench))])
    _real_generation(monkeypatch, tmp_path)
    assert app.process_command() is True
    edited = load_json_file(bench)
    edited["variables"][0]["description"] = "editado por el usuario mientras se generaba"
    save_json_file(bench, edited)
    concurrent = _identity(bench)
    assert app.generate_package() is False
    assert _identity(bench) == concurrent  # la edicion del usuario se conserva; la asignacion no se aplica
    assert any("cambio durante la operacion" in line for line in _events(logs, "NORMAL_IO_ROLLBACK"))


# ---------------------------------------------------------------------------------------------
# 6 / 7: configuracion explicita (inmediata) y comando mixto (transaccional)
# ---------------------------------------------------------------------------------------------

def test_explicit_address_assignment_without_logic_is_applied_immediately(normal, bench, logs, monkeypatch):
    app, state = normal["app"], normal["state"]
    command = "Usa %QX1.3 para la bomba principal."
    explicit = _llm(command, [])
    semantic = _interpret(command, explicit, load_json_file(bench))
    assert semantic["operation_type"] == "MAP_CONFIG"
    assert NI.classify_map_operation(semantic)["kind"] == NI.MAP_OPERATION_CONFIG
    _script(monkeypatch, state, [semantic])
    assert app.process_command() is False  # no hay programa que generar
    located = {v["location"]: v["name"] for v in load_json_file(bench)["variables"]}
    assert located["%QX1.3"].startswith("Q_") and located["%QX1.3"] != "Q_Free_3"
    assert _events(logs, "NORMAL_MAP_CONFIG_EXPLICIT")
    assert any("Configuración de mapa aplicada." in m for m in state["infos"])


def test_mixed_explicit_config_and_logic_is_committed_only_with_the_program(normal, bench, logs, monkeypatch, tmp_path):
    app, state = normal["app"], normal["state"]
    command = "Usa %QX1.5 para la bomba. Cuando presione Start enciende la bomba 5 segundos."
    mixed = _llm(command, [_seq([{"outputs": ["Q_Bomba"], "duration": "T#5s"}], start_input="I_Start")])
    semantic = _interpret(command, mixed, load_json_file(bench))
    operation = NI.classify_map_operation(semantic)
    assert operation["kind"] == NI.MAP_OPERATION_PROGRAM and operation["explicit"]  # mixto: no se pierde la logica
    before = _identity(bench)
    _script(monkeypatch, state, [semantic])
    _real_generation(monkeypatch, tmp_path)
    assert app.process_command() is True
    assert _identity(bench) == before
    assert app.generate_package() is True
    located = {v["location"]: v["name"] for v in load_json_file(bench)["variables"]}
    assert located["%QX1.5"] == semantic["semantic_validation"]["io_assignment_proposals"][0]["proposed_name"]


def test_role_words_alone_never_make_a_map_config_command():
    for command, requirements in (
        ("Enciende la bomba cuando presione Start.", [_seq([{"outputs": ["Q_Pump"], "duration": "T#5s"}], start_input="I_Start")]),
        ("Llena el tanque 1 y después abre la válvula de vaciado.",
         [_seq([{"outputs": ["Q_Fill_Valve_Tank_1"], "advance_on": "I_Level_High_Tank_1"},
                {"outputs": ["Q_Drain_Valve_Tank_1"], "duration": "T#10s"}], start_input="I_Start")]),
    ):
        semantic = _interpret(command, _llm(command, requirements), _bench())
        assert semantic.get("operation_type") != "MAP_CONFIG"
        assert NI.classify_map_operation(semantic)["kind"] == NI.MAP_OPERATION_PROGRAM


def test_experimentation_never_uses_the_normal_transaction(pipeline):
    app = pipeline["app"]
    app.work_mode_var.set("Experimentacion")
    try:
        assert app._normal_map_transactions_apply() is False
    finally:
        app.work_mode_var.set("Normal")
    assert app._normal_map_transactions_apply() is True


def test_explicit_address_wins_over_the_implicit_mention_of_the_same_name():
    """Antes la mencion implicita (canal libre mas bajo) pisaba la direccion dicha por el usuario."""
    command = "Usa %QX1.5 para la bomba. Cuando presione Start enciende la bomba 5 segundos."
    semantic = _interpret(command, _llm(command, [_seq([{"outputs": ["Q_Bomba"], "duration": "T#5s"}], start_input="I_Start")]),
                          _bench())
    assert {(p["proposed_name"], p["address"]) for p in semantic["semantic_validation"]["io_assignment_proposals"]} == {
        ("Q_Bomba", "%QX1.5")}


def test_pure_config_stays_config_when_the_interpreter_also_recognizes_the_tag():
    command = "Usa %QX1.3 para la bomba principal."
    llm = _llm(command, [])
    llm["recognized_tags"] = ["Q_Bomba_Principal"]
    semantic = _interpret(command, llm, _bench())
    assert NI.classify_map_operation(semantic)["kind"] == NI.MAP_OPERATION_CONFIG
