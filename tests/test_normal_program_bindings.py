"""
MODO NORMAL — ASSIGNED = ocupado por el PROGRAMA ACTUAL; LOCKED = protegido entre programas; FREE = disponible.

  * PROGRAMA NUEVO: en una copia de trabajo, los ASSIGNED AUTOMATICOS del programa anterior vuelven al pool;
    LOCKED / MANUAL / persistent y TODA la configuracion fisica (senal, sensor, rango, unidad) se conservan.
    Solo el commit del programa nuevo verificado cambia el mapa; si falla, programa y mapa anteriores intactos.
  * AMPLIACION ("Añade una alarma..."): se conservan las asignaciones existentes; el interprete recibe el
    programa actual y devuelve el programa completo; solo se asignan los recursos nuevos.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import gui  # noqa: E402
import normal_program_bindings as PB
from utils import load_json_file

from test_execute_full_pipeline import temp_map, _tia_ready  # noqa: F401,E402
from test_experiment_working_io_map import _use_bench_copy  # noqa: E402
from test_normal_functional_composition import normal, _script  # noqa: F401,E402
from test_normal_map_transactions import _real_generation  # noqa: E402
from test_normal_mode_hardening import _channel, _interpret, _llm, _seq, save_json_file  # noqa: E402
from test_phase1_download_and_trials import pipeline  # noqa: F401,E402

PILOTS = ("Q_Pilot_1", "Q_Pilot_2", "Q_Pilot_3")
NEW_PROGRAM = "Realiza una secuencia con tres luces piloto."
PILOT_SEQUENCE = [_seq([{"outputs": [p], "duration": "T#2s"} for p in PILOTS], repeat="continuous")]
PUMP_PROGRAM = "Cuando presione Start enciende la bomba 5 segundos."
PUMP_SEQUENCE = [_seq([{"outputs": ["Q_Pump"], "duration": "T#5s"}], start_input="I_Start")]


def _variable(name: str, location: str, state: str, **extra: Any) -> dict[str, Any]:
    return {**_channel(name, location, state), **extra}


def _program_map(*outputs: dict[str, Any], free_do: tuple[str, ...] = ("%QX8.1", "%QX8.2"), extra: list | None = None,
                 current_program: dict[str, Any] | None = None) -> dict[str, Any]:
    variables = [_variable("I_Start", "%IX16.0", "LOCKED"), _variable("I_Stop", "%IX16.1", "LOCKED"),
                 _variable("I_Free_2", "%IX16.2", "FREE"), _variable("I_Free_3", "%IX16.3", "FREE"), *outputs,
                 *[_variable(f"Q_Free_{loc[-1]}", loc, "FREE") for loc in free_do], *(extra or [])]
    metadata = {"map_id": "test_program_bench", "name": "TEST", "version": 1}
    if current_program:
        metadata[PB.CURRENT_PROGRAM_KEY] = current_program
    return {"schema_version": 1, "metadata": metadata,
            "naming_convention": {"inputs": "I_", "outputs": "Q_"}, "variables": variables, "history": []}


PROGRAM_A = {"program_id": "PRG_A", "scope": PB.SCOPE_NEW, "command_text": PUMP_PROGRAM, "intent_id": "INT_UNKNOWN",
             "parameters": {"emergency_input": "FALSE"}, "functional_requirements": PUMP_SEQUENCE, "resources": ["I_Start", "Q_Pump"]}


def _install(app, tmp_path: Path, io_map: dict[str, Any], working: bool = True) -> Path:
    path = tmp_path / ("bench_working.json" if working else "bench_base.json")
    save_json_file(path, io_map)
    _use_bench_copy(app, path)
    return path


def _by_location(path: Path) -> dict[str, dict[str, Any]]:
    return {v["location"]: v for v in load_json_file(path)["variables"]}


def _run(normal, monkeypatch, tmp_path, command: str, requirements: list[dict[str, Any]], generate: bool = True):
    """process_command (+ generate_package) con el interprete inyectado sobre el mapa que la GUI le entrega."""
    app, state = normal["app"], normal["state"]
    seen: dict[str, Any] = {}

    def _respond(kwargs):
        seen.update(kwargs)
        return _interpret(command, _llm(command, requirements), kwargs["io_map"])

    _script(monkeypatch, state, [_respond])
    app.command_textbox.delete("1.0", "end")
    app.command_textbox.insert("1.0", command)
    _real_generation(monkeypatch, tmp_path / "generated")
    processed = app.process_command()
    generated = app.generate_package() if processed and generate else None
    return processed, generated, seen


# ---------------------------------------------------------------------------------------------
# Reglas puras
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command, scope", [
    ("Ahora añade una alarma cuando se active el sensor.", PB.SCOPE_EXTEND),
    ("También enciende la lámpara cuando se active el sensor.", PB.SCOPE_EXTEND),
    ("Agrega al programa actual un piloto de marcha.", PB.SCOPE_EXTEND),
    ("Realiza una secuencia con tres luces piloto.", PB.SCOPE_NEW),
    ("Crea un nuevo programa de semáforo con verde 10 s.", PB.SCOPE_NEW),
    ("Enciende el motor con Start y apágalo con Stop.", PB.SCOPE_NEW),
])
def test_program_scope_is_new_by_default_and_extend_only_when_asked(command, scope):
    assert PB.classify_program_scope(command, PROGRAM_A)[0] == scope
    assert PB.classify_program_scope(command, None)[0] == PB.SCOPE_NEW  # sin programa actual: siempre nuevo


def test_assignment_source_of_legacy_bindings_is_inferred_safely():
    history = [{"address": "%QX8.0", "new_name": "Q_Pump", "source": "MANUAL_EDITOR"},
               {"address": "%QX8.1", "new_name": "Q_Valve", "source": "AUTO_ALLOCATOR"}]
    assert PB.assignment_source(_variable("Q_Pump", "%QX8.0", "ASSIGNED"), history) == PB.SOURCE_MANUAL
    assert PB.assignment_source(_variable("Q_Valve", "%QX8.1", "ASSIGNED"), history) == PB.SOURCE_AUTO
    assert PB.assignment_source(_variable("Q_Old", "%QX8.2", "ASSIGNED"), []) == PB.SOURCE_AUTO  # sin rastro: no reservado
    assert PB.assignment_source(_variable("Q_Old", "%QX8.2", "ASSIGNED", persistent=True), []) == PB.SOURCE_MANUAL
    assert PB.assignment_source(_variable("Q_Lock", "%QX8.3", "LOCKED"), []) == PB.STATE_LOCKED


def test_release_keeps_physical_configuration_and_never_touches_the_input_map():
    io_map = _program_map(_variable("Q_Pump", "%QX8.0", "ASSIGNED", assignment_source="AUTO", owner_program_id="PRG_A"),
                          extra=[_variable("AI_Level", "%IW4", "ASSIGNED", assignment_source="AUTO", signal_type="4-20mA",
                                           sensor="LEVEL", engineering_range=[0, 100], unit="%")])
    snapshot = json.dumps(io_map, sort_keys=True)
    working, released = PB.release_auto_bindings(io_map)
    assert json.dumps(io_map, sort_keys=True) == snapshot  # copia de trabajo, nunca el mapa original
    level = next(v for v in working["variables"] if v["location"] == "%IW4")
    assert level["state"] == "FREE" and "owner_program_id" not in level
    assert (level["signal_type"], level["sensor"], level["engineering_range"], level["unit"]) == ("4-20mA", "LEVEL", [0, 100], "%")
    assert {r["address"] for r in released} == {"%QX8.0", "%IW4"}


# ---------------------------------------------------------------------------------------------
# NEW1 / NEW2: programa nuevo recicla AUTO, respeta LOCKED y MANUAL
# ---------------------------------------------------------------------------------------------

def test_NEW1_auto_binding_of_the_previous_program_can_be_recycled(normal, monkeypatch, tmp_path):
    path = _install(normal["app"], tmp_path, _program_map(
        _variable("Q_Pump", "%QX8.0", "ASSIGNED", assignment_source="AUTO", owner_program_id="PRG_A"), current_program=PROGRAM_A))
    processed, generated, _ = _run(normal, monkeypatch, tmp_path, NEW_PROGRAM, PILOT_SEQUENCE)
    assert processed and generated
    channels = _by_location(path)
    assert [channels[a]["name"] for a in ("%QX8.0", "%QX8.1", "%QX8.2")] == list(PILOTS)  # %QX8.0 reciclado
    assert all(channels[a]["state"] == "ASSIGNED" and channels[a]["assignment_source"] == "AUTO" for a in ("%QX8.0", "%QX8.1", "%QX8.2"))
    current = load_json_file(path)["metadata"][PB.CURRENT_PROGRAM_KEY]
    assert current["scope"] == PB.SCOPE_NEW and current["program_id"] != "PRG_A"
    assert {channels[a]["owner_program_id"] for a in ("%QX8.0", "%QX8.1", "%QX8.2")} == {current["program_id"]}


@pytest.mark.parametrize("protection", [{"state": "LOCKED"}, {"state": "ASSIGNED", "assignment_source": "MANUAL"},
                                        {"state": "ASSIGNED", "persistent": True}])
def test_NEW2_locked_manual_or_persistent_channel_stays_reserved(normal, monkeypatch, tmp_path, protection):
    state = protection.pop("state")
    path = _install(normal["app"], tmp_path, _program_map(_variable("Q_Pump", "%QX8.0", state, **protection),
                                                          free_do=("%QX8.1", "%QX8.2", "%QX8.3"), current_program=PROGRAM_A))
    processed, generated, _ = _run(normal, monkeypatch, tmp_path, NEW_PROGRAM, PILOT_SEQUENCE)
    assert processed and generated
    channels = _by_location(path)
    assert channels["%QX8.0"]["name"] == "Q_Pump" and channels["%QX8.0"]["state"] == state  # reservado
    assert [channels[a]["name"] for a in ("%QX8.1", "%QX8.2", "%QX8.3")] == list(PILOTS)


def test_NEW2_reserved_channel_is_not_used_even_when_hardware_is_short(normal, monkeypatch, tmp_path):
    path = _install(normal["app"], tmp_path, _program_map(_variable("Q_Pump", "%QX8.0", "LOCKED"), current_program=PROGRAM_A))
    before = _by_location(path)
    processed, _, _ = _run(normal, monkeypatch, tmp_path, NEW_PROGRAM, PILOT_SEQUENCE)
    assert processed is False  # 3 DO necesarias, 2 libres: falta de hardware
    assert any("SYSTEM_CAPABILITY_GAP" in m for m in normal["state"]["errors"])
    assert _by_location(path) == before


# ---------------------------------------------------------------------------------------------
# NEW3: ampliar el programa actual conserva sus asignaciones
# ---------------------------------------------------------------------------------------------

def test_NEW3_extension_keeps_existing_bindings_and_adds_only_the_new_resource(normal, monkeypatch, tmp_path):
    path = _install(normal["app"], tmp_path, _program_map(
        _variable("Q_Pump", "%QX8.0", "ASSIGNED", assignment_source="AUTO", owner_program_id="PRG_A"), current_program=PROGRAM_A))
    command = "Ahora añade una alarma cuando se active el sensor."
    combined = PUMP_SEQUENCE + [{"type": "conditional_output", "condition": "I_Sensor", "outputs": ["Q_Alarm"]}]
    processed, generated, seen = _run(normal, monkeypatch, tmp_path, command, combined)
    assert processed and generated
    assert seen["program_context"]["functional_requirements"] == PUMP_SEQUENCE  # el interprete recibe el programa actual
    channels = _by_location(path)
    assert channels["%QX8.0"]["name"] == "Q_Pump" and channels["%QX8.0"]["state"] == "ASSIGNED"  # se conserva
    assert channels["%QX8.1"]["name"] == "Q_Alarm"  # solo el recurso nuevo toma otra DO
    assert load_json_file(path)["metadata"][PB.CURRENT_PROGRAM_KEY]["scope"] == PB.SCOPE_EXTEND


def test_extension_parsed_by_rules_is_refused_instead_of_dropping_the_current_program(normal, monkeypatch, tmp_path):
    app, state = normal["app"], normal["state"]
    path = _install(app, tmp_path, _program_map(
        _variable("Q_Pump", "%QX8.0", "ASSIGNED", assignment_source="AUTO"), current_program=PROGRAM_A))
    before = _by_location(path)
    rules_result = {**_interpret("x", _llm("x", [{"type": "conditional_output", "condition": "I_Sensor", "outputs": ["Q_Alarm"]}]),
                                 load_json_file(path)), "parser_mode_used": "rule_based"}
    _script(monkeypatch, state, [rules_result])
    app.command_textbox.delete("1.0", "end")
    app.command_textbox.insert("1.0", "Añade una alarma cuando se active el sensor.")
    assert app.process_command() is False
    assert _by_location(path) == before


# ---------------------------------------------------------------------------------------------
# NEW4: un programa nuevo que falla no toca nada
# ---------------------------------------------------------------------------------------------

def test_NEW4_failed_new_program_keeps_previous_program_and_map_exactly(normal, monkeypatch, tmp_path):
    path = _install(normal["app"], tmp_path, _program_map(
        _variable("Q_Pump", "%QX8.0", "ASSIGNED", assignment_source="AUTO", owner_program_id="PRG_A"), current_program=PROGRAM_A))
    normal["app"].save_io_map(show_success=False)
    before = load_json_file(path)

    def _boom(**kwargs):
        raise RuntimeError("fallo simulado en IR/SCL")

    processed, _, _ = _run(normal, monkeypatch, tmp_path, NEW_PROGRAM, PILOT_SEQUENCE, generate=False)
    assert processed is True
    monkeypatch.setattr(gui, "generate_project_package", _boom)
    assert normal["app"].generate_package() is False
    after = load_json_file(path)
    assert after["variables"] == before["variables"] and after["history"] == before["history"]
    assert after["metadata"][PB.CURRENT_PROGRAM_KEY] == PROGRAM_A  # el programa anterior sigue siendo el actual


# ---------------------------------------------------------------------------------------------
# NEW5: la configuracion fisica sobrevive a programas nuevos y al guardado de la tabla
# ---------------------------------------------------------------------------------------------

def test_NEW5_physical_analog_configuration_survives_a_new_program(normal, monkeypatch, tmp_path):
    level = _variable("AI_Level", "%IW4", "ASSIGNED", assignment_source="AUTO", owner_program_id="PRG_A",
                      signal_type="4-20mA", sensor="LEVEL", engineering_range=[0, 100], unit="%")
    path = _install(normal["app"], tmp_path, _program_map(
        _variable("Q_Pump", "%QX8.0", "ASSIGNED", assignment_source="AUTO"), free_do=("%QX8.1", "%QX8.2", "%QX8.3"),
        extra=[level], current_program=PROGRAM_A))
    processed, generated, _ = _run(normal, monkeypatch, tmp_path, NEW_PROGRAM, PILOT_SEQUENCE)
    assert processed and generated
    analog = _by_location(path)["%IW4"]
    assert (analog["signal_type"], analog["sensor"], analog["engineering_range"], analog["unit"]) == ("4-20mA", "LEVEL", [0, 100], "%")
    assert analog["state"] == "FREE" and analog["name"] == "AI_Level"  # binding liberado; el hardware se conserva


def test_physical_fields_outside_the_table_survive_saving_the_gui_table(normal, tmp_path):
    level = _variable("AI_Level", "%IW4", "ASSIGNED", signal_type="4-20mA", sensor="LEVEL", engineering_range=[0, 100])
    path = _install(normal["app"], tmp_path, _program_map(extra=[level]))
    assert normal["app"].save_io_map(show_success=False)  # lo que hace cada comando al empezar
    analog = _by_location(path)["%IW4"]
    assert (analog["signal_type"], analog["sensor"], analog["engineering_range"]) == ("4-20mA", "LEVEL", [0, 100])


# ---------------------------------------------------------------------------------------------
# Procedencia MANUAL de las decisiones del usuario y mapas versionados
# ---------------------------------------------------------------------------------------------

def test_user_edits_are_recorded_as_manual_and_survive_saving(normal, tmp_path):
    app = normal["app"]
    path = _install(app, tmp_path, _program_map(_variable("Q_Pump", "%QX8.0", "ASSIGNED")))
    app._mark_manual_binding({"name": "Q_Pump", "location": "%QX8.0"}, "ASSIGNED")
    assert app.save_io_map(show_success=False)
    assert _by_location(path)["%QX8.0"]["assignment_source"] == "MANUAL"
    app._mark_manual_binding({"name": "Q_Pump", "location": "%QX8.0"}, "FREE")
    assert app.save_io_map(show_success=False)
    assert "assignment_source" not in _by_location(path)["%QX8.0"]


def test_explicit_address_configuration_is_manual(normal, monkeypatch, tmp_path):
    app, state = normal["app"], normal["state"]
    path = _install(app, tmp_path, _program_map(free_do=("%QX8.1", "%QX8.2", "%QX8.3")))
    command = "Usa %QX8.3 para la bomba principal."
    _script(monkeypatch, state, [lambda kwargs: _interpret(command, _llm(command, []), kwargs["io_map"])])
    app.command_textbox.delete("1.0", "end")
    app.command_textbox.insert("1.0", command)
    app.process_command()
    channel = _by_location(path)["%QX8.3"]
    assert channel["state"] == "ASSIGNED" and channel["assignment_source"] == "MANUAL"


def test_versioned_maps_never_receive_program_metadata(normal, monkeypatch, tmp_path):
    path = _install(normal["app"], tmp_path, _program_map(free_do=("%QX8.1", "%QX8.2", "%QX8.3")), working=False)
    processed, generated, _ = _run(normal, monkeypatch, tmp_path, NEW_PROGRAM, PILOT_SEQUENCE)
    assert processed and generated
    payload = load_json_file(path)
    assert PB.CURRENT_PROGRAM_KEY not in payload["metadata"]
    assert not any("owner_program_id" in v for v in payload["variables"])
