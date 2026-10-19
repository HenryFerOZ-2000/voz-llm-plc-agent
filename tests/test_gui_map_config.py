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

# The shared `app` fixture (one Tk root for the whole pytest session) lives in conftest.py.


def _stub_clarification_dialog(answer: str | None):
    """Same non-blocking stand-in used in test_gui_clarification.py."""

    class _StubClarificationDialog(gui.ctk.CTkToplevel):
        def __init__(self, parent, question):
            super().__init__(parent)
            self.result = answer
            self.withdraw()
            self.after(1, self.destroy)

    return _StubClarificationDialog


def _temp_map_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "metadata": {"map_id": "mapa_test_map_config", "name": "MAPA_TEST_MAP_CONFIG", "version": 1},
        "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_", "auxiliary": "R_"},
        "variables": [
            {
                "name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX16.0",
                "initial_value": "FALSE", "description": "", "state": "LOCKED", "llm_allowed": True
            },
            {
                "name": "I_Reset", "class": "input", "type": "BOOL", "location": "%IX16.3",
                "initial_value": "FALSE", "description": "", "state": "ASSIGNED", "llm_allowed": True
            },
            {
                "name": "Q_Alarm", "class": "output", "type": "BOOL", "location": "%QX8.1",
                "initial_value": "FALSE", "description": "", "state": "ASSIGNED", "llm_allowed": True
            },
            {
                "name": "Q_Free1", "class": "output", "type": "BOOL", "location": "%QX8.0",
                "initial_value": "FALSE", "description": "", "state": "FREE", "llm_allowed": True
            }
        ]
    }


@pytest.fixture
def temp_map(app, tmp_path, monkeypatch):
    """Redirects the GUI's active map to a throwaway file for this test only - never touches
    the real project map."""
    map_path = tmp_path / "mapa_test_map_config.json"
    map_path.write_text(json.dumps(_temp_map_payload(), indent=2), encoding="utf-8")
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
    yield map_path
    app.io_map_path = original_path
    # Ver test_autonomous_resource_resolution.py::temp_map - sin recargar io_variables/io_tree
    # desde el mapa real, el `app` compartido (session-scoped) queda apuntando al path correcto
    # pero mostrando el inventario pequeno de este test, y un save_io_map() posterior de otro
    # test sobreescribiria el mapa real con ese inventario obsoleto.
    app.io_variables = gui.load_io_map_variables(original_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    app.active_trial = None
    app.active_profile_id = None
    app.command_textbox.delete("1.0", "end")
    app.pending_semantic_output = None


def _base_output(command_text: str, proposals: list[dict[str, Any]], intent_id: str = "INT_UNKNOWN") -> dict[str, Any]:
    return {
        "intent_id": intent_id,
        "case_id": None,
        "command_text": command_text,
        "normalized_command": command_text.lower(),
        "parameters": {},
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": [],
        "unrecognized_terms": [],
        "operation_type": "MAP_CONFIG",
        "requested_io_assignments": [
            {"address_text": p["address"], "address": p["address"], "role_text": "", "functional_name_hint": p["proposed_name"]}
            for p in proposals
        ],
        "semantic_validation": {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "missing_parameters": [],
            "unauthorized_tags": [],
            "requires_clarification": False,
            "io_assignment_proposals": proposals
        }
    }


def _free_proposal(address: str, current_name: str, proposed_name: str) -> dict[str, Any]:
    return {
        "address": address, "proposed_name": proposed_name, "current_name": current_name,
        "current_state": "FREE", "conflict": False, "blocked": False, "requires_confirmation": False,
        "reason": f"Canal libre disponible en {address}."
    }


def _conflict_proposal(address: str, current_name: str, proposed_name: str) -> dict[str, Any]:
    return {
        "address": address, "proposed_name": proposed_name, "current_name": current_name,
        "current_state": "ASSIGNED", "conflict": True, "blocked": False, "requires_confirmation": True,
        "reason": f"La direccion {address} ya esta asignada a {current_name}. Cambio propuesto: {current_name} -> {proposed_name}."
    }


def _locked_proposal(address: str, current_name: str, proposed_name: str) -> dict[str, Any]:
    return {
        "address": address, "proposed_name": proposed_name, "current_name": current_name,
        "current_state": "LOCKED", "conflict": False, "blocked": True, "requires_confirmation": False,
        "reason": f"La variable {current_name} en {address} esta protegida (LOCKED) y no puede reasignarse."
    }


# ---------- Rule 1/6: FREE channel auto-applies, never asks ----------

def test_free_channel_auto_applies_without_confirmation(app, temp_map, monkeypatch):
    proposals = [_free_proposal("%QX8.0", "Q_Free1", "Q_Motor_1")]
    output = _base_output("Usa Q8.0 como salida del motor 1.", proposals)

    askyesno_calls = []
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: output)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: askyesno_calls.append((a, k)) or True)

    app.command_textbox.insert("1.0", output["command_text"])
    result = app.process_command()

    assert result is False  # pure config command, no logic to generate
    assert askyesno_calls == []  # never asked

    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    variable = next(v for v in saved["variables"] if v["location"] == "%QX8.0")
    assert variable["name"] == "Q_Motor_1"
    assert variable["state"] == "ASSIGNED"
    assert len(saved.get("history", [])) == 1


# ---------- Rule 3 (section 22 revision): ASSIGNED reassignment auto-applies, no confirmation ----------

def test_multiple_conflicts_reassign_automatically_without_asking(app, temp_map, monkeypatch):
    proposals = [
        _conflict_proposal("%QX8.1", "Q_Alarm", "Q_Motor_2"),
        _conflict_proposal("%IX16.3", "I_Reset", "I_Reverse")
    ]
    output = _base_output("Usa Q8.1 para motor 2 e I16.3 para reversa.", proposals)

    call_count = {"value": 0}
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: output)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: call_count.__setitem__("value", call_count["value"] + 1) or True)

    app.command_textbox.insert("1.0", output["command_text"])
    app.process_command()

    assert call_count["value"] == 0  # Modo Normal: cero confirmaciones, ni siquiera agrupadas

    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    names_by_address = {v["location"]: v["name"] for v in saved["variables"]}
    assert names_by_address["%QX8.1"] == "Q_Motor_2"
    assert names_by_address["%IX16.3"] == "I_Reverse"
    # Se registra en el historial con old_name/new_name, aunque no se haya preguntado nada.
    history = saved.get("history", [])
    assert any(h["old_name"] == "Q_Alarm" and h["new_name"] == "Q_Motor_2" for h in history)


# ---------- Rule 4: LOCKED is rejected but never blocks the rest ----------

def test_locked_is_rejected_but_free_channels_still_apply(app, temp_map, monkeypatch):
    proposals = [
        _locked_proposal("%IX16.0", "I_Start", "I_Reverse"),
        _free_proposal("%QX8.0", "Q_Free1", "Q_Motor_1")
    ]
    output = _base_output("Usa I16.0 para reversa y Q8.0 para motor 1.", proposals)

    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: output)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)

    app.command_textbox.insert("1.0", output["command_text"])
    app.process_command()

    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    names_by_address = {v["location"]: v["name"] for v in saved["variables"]}
    assert names_by_address["%IX16.0"] == "I_Start"  # rejected, unchanged
    assert names_by_address["%QX8.0"] == "Q_Motor_1"  # still applied


def test_only_locked_proposals_shows_error_and_changes_nothing(app, temp_map, monkeypatch):
    proposals = [_locked_proposal("%IX16.0", "I_Start", "I_Reverse")]
    output = _base_output("Usa I16.0 para reversa.", proposals)

    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: output)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)

    app.command_textbox.insert("1.0", output["command_text"])
    result = app.process_command()

    assert result is False
    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    variable = next(v for v in saved["variables"] if v["location"] == "%IX16.0")
    assert variable["name"] == "I_Start"
    assert saved.get("history", []) == []


# ---------- Rule 7: combined FREE + conflict + LOCKED in one command ----------

def test_combined_command_mixes_auto_apply_grouped_confirm_and_blocked(app, temp_map, monkeypatch):
    proposals = [
        _locked_proposal("%IX16.0", "I_Start", "I_Start"),      # already correct name, still LOCKED-protected path not hit
        _free_proposal("%QX8.0", "Q_Free1", "Q_Motor_1"),
        _conflict_proposal("%QX8.1", "Q_Alarm", "Q_Motor_2")
    ]
    output = _base_output(
        "Usa I16.0 como Start, Q8.0 para motor 1 y Q8.1 para motor 2.",
        proposals
    )

    ask_calls = {"value": 0}
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: output)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: ask_calls.__setitem__("value", ask_calls["value"] + 1) or True)

    app.command_textbox.insert("1.0", output["command_text"])
    app.process_command()

    assert ask_calls["value"] == 0  # cero confirmaciones en Modo Normal (seccion 22)
    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    names_by_address = {v["location"]: v["name"] for v in saved["variables"]}
    assert names_by_address["%QX8.0"] == "Q_Motor_1"
    assert names_by_address["%QX8.1"] == "Q_Motor_2"


# ---------- Rule 8: final summary always shown ----------

def test_final_summary_shown_after_apply(app, temp_map, monkeypatch):
    proposals = [_free_proposal("%QX8.0", "Q_Free1", "Q_Motor_1")]
    output = _base_output("Usa Q8.0 para motor 1.", proposals)

    summaries = []
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: output)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda title, message, *a, **k: summaries.append(message))

    app.command_textbox.insert("1.0", output["command_text"])
    app.process_command()

    assert len(summaries) == 1
    assert "Configuración de mapa aplicada." in summaries[0]  # mensaje solo tras aplicar
    assert "%QX8.0" in summaries[0] and "Q_Motor_1" in summaries[0]


# ---------- Experimental blocking (still applies under the new policy) ----------

def test_map_config_blocked_during_active_trial(app, temp_map, monkeypatch):
    proposals = [_free_proposal("%QX8.0", "Q_Free1", "Q_Motor_1")]
    output = _base_output("Usa Q8.0 para motor 1.", proposals)
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: output)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    app.active_trial = {"trial_id": "T01"}

    app.command_textbox.insert("1.0", output["command_text"])
    result = app.process_command()

    assert result is False
    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    variable = next(v for v in saved["variables"] if v["location"] == "%QX8.0")
    assert variable["name"] == "Q_Free1"
    assert saved.get("history", []) == []


# ---------- Combined command continues into logic after applying ----------

def test_combined_command_applies_map_then_continues_with_logic(app, temp_map, monkeypatch):
    proposals = [_free_proposal("%QX8.0", "Q_Free1", "Q_Motor_1")]
    combined_output = _base_output(
        "Usa Q8.0 para motor 1. Enciende el motor 1 con Start.", proposals, intent_id="INT_DIRECT_OUTPUT"
    )
    combined_output["parameters"] = {"trigger_input": "I_Start", "emergency_input": "I_Start", "output": "Q_Motor_1"}
    # Before applying the map, Q_Motor_1 does not exist yet - the first-pass validation reflects that.
    combined_output["semantic_validation"]["is_valid"] = False
    combined_output["semantic_validation"]["errors"] = ["Recurso externo no autorizado/no existente en el mapa PLC: Q_Motor_1"]
    combined_output["semantic_validation"]["unauthorized_tags"] = ["Q_Motor_1"]

    showinfo_calls = []
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: combined_output)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda title, message, *a, **k: showinfo_calls.append(message))

    app.command_textbox.insert("1.0", combined_output["command_text"])
    result = app.process_command()

    # After applying the assignment, Q_Motor_1 exists - re-validation should now succeed and
    # process_command should continue into (and complete) its normal intent flow.
    assert result is True
    assert app.pending_semantic_output["intent_id"] == "INT_DIRECT_OUTPUT"
    assert app.pending_semantic_output["semantic_validation"]["is_valid"] is True
    # Seccion 14: la configuracion automatica de mapa es UNA ETAPA del pipeline, no debe detener
    # el flujo con un messagebox intermedio propio - el resumen se reserva para el dialogo de
    # confirmar generacion (ver test_map_config_summary_appears_in_generate_confirmation_dialog).
    assert showinfo_calls == []
    assert app._last_map_config_summary is not None
    assert "Q_Motor_1" in app._last_map_config_summary


# ---------- Section 11: INT_UNKNOWN + functional_requirements ya no se confunde con "sin logica" ----------

def test_intent_unknown_with_functional_requirements_is_not_misreported_as_pure_config(app, temp_map, monkeypatch):
    """
    Limite real detectado durante esta correccion: la generacion de codigo (ir_builder/
    code_generator) sigue siendo estrictamente por plantilla de intent_id - un intent_id que no
    esta en el catalogo (incluido INT_UNKNOWN) NUNCA tiene plantilla, sin importar cuantos
    functional_requirements traiga. Eso significa que un comando genuinamente nuevo que no
    coincide con NINGUN intent_id del catalogo (p. ej. un enclavamiento de 3 motores - seccion 13)
    todavia no puede completar la generacion; esa es una limitacion aparte (generalizar la
    generacion a partir de functional_requirements en vez de solo por intent_id con plantilla fija)
    que esta correccion NO implementa. Lo que SI corrige esta seccion: ese caso ya NO se reporta
    con el mensaje enganoso "el comando no incluia logica PLC adicional" (que asumia
    intent_id==INT_UNKNOWN siempre significa "sin logica") - la configuracion de mapa se aplica
    igual (sin messagebox intermedio) y el pipeline se detiene mas adelante, en el punto correcto,
    con el motivo real (sin plantilla implementada), no con una afirmacion falsa de "sin logica".
    """
    proposals = [_free_proposal("%QX8.0", "Q_Free1", "Q_Motor_1")]
    combined_output = _base_output(
        "Usa Q8.0 para motor 1. Cuando arranque motor 1, enciende el piloto.", proposals, intent_id="INT_UNKNOWN"
    )
    combined_output["parameters"] = {}
    combined_output["functional_requirements"] = [{"type": "run_pilot"}]
    combined_output["semantic_validation"]["is_valid"] = False
    combined_output["semantic_validation"]["errors"] = ["Recurso externo no autorizado/no existente en el mapa PLC: Q_Motor_1"]
    combined_output["semantic_validation"]["unauthorized_tags"] = ["Q_Motor_1"]

    info_messages = []
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: combined_output)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda title, message, *a, **k: info_messages.append(message))
    monkeypatch.setattr(gui, "ClarificationDialog", _stub_clarification_dialog(None))

    before = json.loads(temp_map.read_text(encoding="utf-8"))
    app.command_textbox.insert("1.0", combined_output["command_text"])
    app.process_command()

    # Regla de Modo Normal transaccional: un INT_UNKNOWN que no puede generarse NO deja efectos persistentes
    # (antes el canal quedaba reasignado en el mapa sin programa). El mensaje enganoso "sin logica adicional"
    # tampoco aparece: el comando tiene logica, solo que no es generable.
    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    identity = lambda io_map: [(v["location"], v["name"], v["state"]) for v in io_map["variables"]]  # noqa: E731
    assert identity(saved) == identity(before)
    assert app._pending_map_transaction is None
    assert not any("no incluia logica PLC adicional" in message for message in info_messages)


def test_map_config_summary_is_logged_before_automatic_generation(app, temp_map, monkeypatch):
    """
    generate_package() ya no muestra un dialogo de confirmacion (EJECUTAR COMANDO debe continuar
    automaticamente hasta TIA/compilacion sin pulsar nada mas) - el resumen de MAP_CONFIG que antes
    se mostraba en ese dialogo ahora se registra en consola justo antes de generar, sin bloquear.
    """
    proposals = [_free_proposal("%QX8.0", "Q_Free1", "Q_Motor_1")]
    combined_output = _base_output(
        "Usa Q8.0 para motor 1. Enciende el motor 1 con Start.", proposals, intent_id="INT_DIRECT_OUTPUT"
    )
    combined_output["parameters"] = {"trigger_input": "I_Start", "emergency_input": "I_Start", "output": "Q_Motor_1"}
    combined_output["semantic_validation"]["is_valid"] = False
    combined_output["semantic_validation"]["errors"] = ["Recurso externo no autorizado/no existente en el mapa PLC: Q_Motor_1"]
    combined_output["semantic_validation"]["unauthorized_tags"] = ["Q_Motor_1"]

    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: combined_output)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)

    app.command_textbox.insert("1.0", combined_output["command_text"])
    app.process_command()

    logged_messages = []
    original_log = app._log
    monkeypatch.setattr(app, "_log", lambda message: (logged_messages.append(message), original_log(message))[1])

    # No debe existir NINGUN dialogo de confirmacion bloqueante en generate_package().
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("generate_package() no debe abrir ningun dialogo de confirmacion")
    monkeypatch.setattr(gui.messagebox, "askyesnocancel", _fail_if_called)

    app.generate_package()

    summary_logged = [message for message in logged_messages if "Asignacion provisional de recursos" in message]
    assert len(summary_logged) == 1
    assert "Q_Motor_1" in summary_logged[0]
