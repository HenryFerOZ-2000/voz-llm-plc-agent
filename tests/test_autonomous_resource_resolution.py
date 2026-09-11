"""
Regression tests for the "zero unnecessary questions" fix (section 9-18 of the task): a
well-formed but not-yet-authorized physical tag (I_/Q_/AI_/AO_) that the LLM proposes for a
genuinely new function must be resolved automatically by IOAllocator - never rejected outright,
and never forcing requires_clarification just because the exact tag name did not already exist in
the map. Also covers the critical safety fix found while implementing this: a map with no
explicit `state` field (all pre-existing D01-D20/PID maps) must default every variable to LOCKED,
never ASSIGNED, so this new auto-resolution can never silently cannibalize a safety-critical tag
like I_Emergency in a map that predates the FREE/ASSIGNED/LOCKED feature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402
from io_allocator import DEFAULT_STATE, STATE_LOCKED  # noqa: E402
from semantic_validator import validate_semantic_output  # noqa: E402


def _variable(name, location, state=None, var_class="input", var_type="BOOL"):
    entry = {
        "name": name, "class": var_class, "type": var_type, "location": location,
        "initial_value": "FALSE", "description": "", "llm_allowed": True
    }
    if state is not None:
        entry["state"] = state
    return entry


def _stateful_bench_map() -> dict[str, Any]:
    """Mapa de la seccion 15: state EXPLICITO en todas las variables (mapa "moderno")."""
    return {
        "variables": [
            _variable("I_Start", "%IX16.0", STATE_LOCKED),
            _variable("I_Stop", "%IX16.1", STATE_LOCKED),
            _variable("I_Old_1", "%IX16.2", "ASSIGNED"),
            _variable("I_Old_2", "%IX16.3", "ASSIGNED"),
            _variable("Q_Contactor_A", "%QX8.0", "ASSIGNED", var_class="output"),
            _variable("Q_Contactor_B", "%QX8.1", "ASSIGNED", var_class="output"),
        ]
    }


# ---------- Section 0: safety fix - legacy maps without `state` default to LOCKED ----------

def test_default_state_is_locked_not_assigned():
    assert DEFAULT_STATE == STATE_LOCKED


def test_legacy_map_without_state_field_never_auto_reassigns_i_emergency():
    """Mapa "legado" (como mapa_simulacion_completo.json/config/io_map.json): SIN campo `state`
    en ninguna variable. Un tag nuevo bien formado NO debe poder reasignar I_Emergency ni ningun
    otro tag existente - todo se trata como LOCKED por defecto."""
    legacy_map = {
        "variables": [
            _variable("I_Emergency", "%IX0.2"),  # sin "state" - simula un mapa D01-D20 real
            _variable("Q_Alarm", "%QX0.1", var_class="output")
        ]
    }
    semantic_output = {
        "intent_id": "INT_DIRECT_OUTPUT",
        "case_id": None,
        "command_text": "activa una salida nueva",
        "normalized_command": "activa una salida nueva",
        "parameters": {"trigger_input": "I_Emergency", "emergency_input": "I_Emergency", "output": "Q_NewThing"},
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["Q_NewThing"],
        "unrecognized_terms": []
    }
    result = validate_semantic_output(semantic_output, legacy_map, {"INT_DIRECT_OUTPUT": {}}, {})
    # Q_NewThing NO se resuelve (unico output existente, Q_Alarm, esta LOCKED por defecto) ->
    # sigue siendo un tag no autorizado, y jamas se toca I_Emergency ni Q_Alarm.
    assert "Q_NewThing" in result["unauthorized_tags"]
    assert result["is_valid"] is False


# ---------- Sections 3/13/14: the exact reported scenario resolves automatically ----------

def test_well_formed_new_tags_resolve_without_clarification():
    io_map = _stateful_bench_map()
    semantic_output = {
        "intent_id": "INT_MUTUAL_INTERLOCK",
        "case_id": None,
        "command_text": "dos motores independientes con enclavamiento",
        "normalized_command": "dos motores independientes con enclavamiento",
        "parameters": {
            "trigger_input": "I_Start_Motor_1", "stop_input": "I_Start_Motor_2",
            "contactor_a": "Q_Motor_1", "contactor_b": "Q_Motor_2"
        },
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start_Motor_1", "I_Start_Motor_2", "Q_Motor_1", "Q_Motor_2"],
        "unrecognized_terms": []
    }
    result = validate_semantic_output(semantic_output, io_map, {"INT_MUTUAL_INTERLOCK": {}}, {})
    assert result["unauthorized_tags"] == []
    assert result["is_valid"] is True
    assert result["requires_clarification"] is False
    resolved_names = {p["proposed_name"] for p in result["io_assignment_proposals"]}
    assert resolved_names == {"I_Start_Motor_1", "I_Start_Motor_2", "Q_Motor_1", "Q_Motor_2"}


def test_section_16_insufficient_resources_is_a_clear_error_not_a_question():
    """Solo 2 DO existen (ambas ASSIGNED, reasignables), pero se piden 3."""
    io_map = {
        "variables": [
            _variable("I_Start", "%IX16.0", STATE_LOCKED),
            _variable("Q_Contactor_A", "%QX8.0", "ASSIGNED", var_class="output"),
            _variable("Q_Contactor_B", "%QX8.1", "ASSIGNED", var_class="output"),
        ]
    }
    semantic_output = {
        "intent_id": "INT_UNKNOWN",
        "case_id": None,
        "command_text": "necesito tres motores",
        "normalized_command": "necesito tres motores",
        "parameters": {},
        "confidence": 0.5,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["Q_Motor_1", "Q_Motor_2", "Q_Motor_3"],
        "unrecognized_terms": []
    }
    result = validate_semantic_output(semantic_output, io_map, {}, {})
    assert result["is_valid"] is False
    assert result["requires_clarification"] is False  # error claro, no una pregunta
    assert any("Q_Motor_3" in error or "canal fisico" in error.lower() for error in result["errors"])


# ---------- GUI end-to-end: exact command from the bug report ----------

REPORTED_COMMAND = (
    "Quiero encender mi proceso con un pulsante de inicio, cuando el proceso esté iniciado se "
    "puede presionar el pulsante 1 o el pulsante 2, para encender el motor 1 o el motor 2 "
    "respectivamente, los motores no pueden encenderse al mismo tiempo, si se enciende uno se "
    "apaga el otro y viceversa, además, todo el proceso se apagará con el botón de paro."
)


@pytest.fixture
def temp_map(app, tmp_path, monkeypatch):
    payload = {
        "schema_version": 1,
        "metadata": {"map_id": "mapa_test_autonomy", "name": "MAPA_TEST_AUTONOMY", "version": 1},
        "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_", "auxiliary": "R_"},
        "variables": [
            _variable("I_Start", "%IX16.0", STATE_LOCKED),
            _variable("I_Stop", "%IX16.1", STATE_LOCKED),
            _variable("I_Old_1", "%IX16.2", "ASSIGNED"),
            _variable("I_Old_2", "%IX16.3", "ASSIGNED"),
            _variable("Q_Contactor_A", "%QX8.0", "ASSIGNED", var_class="output"),
            _variable("Q_Contactor_B", "%QX8.1", "ASSIGNED", var_class="output"),
        ]
    }
    map_path = tmp_path / "mapa_test_autonomy.json"
    map_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    original_path = app.io_map_path
    app.io_map_path = map_path
    app.io_variables = gui.load_io_map_variables(map_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    app.active_trial = None
    app.active_profile_id = None
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    yield map_path
    app.io_map_path = original_path
    # Sin esto, el `app` compartido (session-scoped) queda con io_tree/io_variables reflejando
    # el mapa pequeno de este test mientras io_map_path ya apunta de vuelta al mapa real - un
    # test NO relacionado que despues llame a save_io_map() (via self._collect_io_variables(),
    # que lee del treeview) sobreescribiria el mapa real con ese inventario reducido y obsoleto.
    app.io_variables = gui.load_io_map_variables(original_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    app.active_trial = None
    app.active_profile_id = None
    app.command_textbox.delete("1.0", "end")
    app.pending_semantic_output = None


def _simulated_llm_output_for_reported_command(io_map: dict[str, Any]) -> dict[str, Any]:
    """
    Lo que el LLM DEBE producir siguiendo el prompt corregido - nunca se llama al LLM real en
    este test (convencion establecida), se simula su salida bien formada. `semantic_validation` se
    calcula con la funcion REAL (no se duplica a mano) para que el test siga siendo fiel al
    comportamiento real de validate_semantic_output.
    """
    payload = {
        "intent_id": "INT_MUTUAL_INTERLOCK",
        "case_id": None,
        "command_text": REPORTED_COMMAND,
        "normalized_command": REPORTED_COMMAND.lower(),
        "parameters": {
            "trigger_input": "I_Start_Motor_1",
            "stop_input": "I_Start_Motor_2",
            "contactor_a": "Q_Motor_1",
            "contactor_b": "Q_Motor_2"
        },
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start_Motor_1", "I_Start_Motor_2", "Q_Motor_1", "Q_Motor_2"],
        "unrecognized_terms": []
    }
    payload["semantic_validation"] = validate_semantic_output(payload, io_map, {"INT_MUTUAL_INTERLOCK": {}}, {})
    return payload


def _current_io_map(map_path: Path) -> dict[str, Any]:
    return json.loads(map_path.read_text(encoding="utf-8"))


def test_reported_command_no_longer_asks_for_clarification(app, temp_map, monkeypatch):
    monkeypatch.setattr(
        gui, "parse_command",
        lambda command_text, **kwargs: _simulated_llm_output_for_reported_command(_current_io_map(temp_map))
    )

    def _dialog_should_not_open(*args, **kwargs):
        raise AssertionError("ClarificationDialog no debe abrirse para este comando - los recursos se resuelven solos.")

    monkeypatch.setattr(gui, "ClarificationDialog", _dialog_should_not_open)

    app.command_textbox.insert("1.0", REPORTED_COMMAND)
    result = app.process_command()

    assert result is True
    assert app.pending_semantic_output["intent_id"] == "INT_MUTUAL_INTERLOCK"
    assert app.pending_semantic_output["semantic_validation"]["is_valid"] is True
    assert app.pending_semantic_output["semantic_validation"]["requires_clarification"] is False


def test_reported_command_resolves_two_distinct_motor_outputs_and_inputs(app, temp_map, monkeypatch):
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: _simulated_llm_output_for_reported_command(_current_io_map(temp_map)))

    app.command_textbox.insert("1.0", REPORTED_COMMAND)
    app.process_command()

    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    names_by_address = {v["location"]: v["name"] for v in saved["variables"]}
    # I_Start/I_Stop bloqueados: exactamente iguales.
    assert names_by_address["%IX16.0"] == "I_Start"
    assert names_by_address["%IX16.1"] == "I_Stop"
    # Dos entradas de seleccion distintas, dos salidas de motor distintas.
    assert names_by_address["%IX16.2"] == "I_Start_Motor_1"
    assert names_by_address["%IX16.3"] == "I_Start_Motor_2"
    assert names_by_address["%QX8.0"] == "Q_Motor_1"
    assert names_by_address["%QX8.1"] == "Q_Motor_2"
    all_names = list(names_by_address.values())
    assert len(set(all_names)) == len(all_names)  # sin nombres duplicados


def test_reported_command_never_touches_locked_start_stop(app, temp_map, monkeypatch):
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: _simulated_llm_output_for_reported_command(_current_io_map(temp_map)))

    app.command_textbox.insert("1.0", REPORTED_COMMAND)
    app.process_command()

    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    start = next(v for v in saved["variables"] if v["location"] == "%IX16.0")
    stop = next(v for v in saved["variables"] if v["location"] == "%IX16.1")
    assert start["name"] == "I_Start" and start["state"] == "LOCKED"
    assert stop["name"] == "I_Stop" and stop["state"] == "LOCKED"
