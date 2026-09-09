from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402

# The shared `app` fixture (one Tk root for the whole pytest session) lives in conftest.py.


@pytest.fixture(autouse=True)
def _reset_state(app, monkeypatch):
    app.work_mode_var.set("Normal")
    app._on_work_mode_changed()
    app.command_textbox.delete("1.0", "end")
    app.pending_semantic_output = None
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    yield


def _stub_dialog(answer: str | None):
    """
    A ClarificationDialog stand-in that never blocks: it must still EXIST when
    self.wait_window(dialog) registers its wait (tkwait window needs a live window path), so it
    schedules its own destruction on the next event-loop tick instead of destroying synchronously.
    """

    class _StubClarificationDialog(gui.ctk.CTkToplevel):
        def __init__(self, parent, question):
            super().__init__(parent)
            self.result = answer
            self.withdraw()
            self.after(1, self.destroy)

    return _StubClarificationDialog


AMBIGUOUS_OUTPUT = {
    "intent_id": "INT_UNKNOWN",
    "command_text": "",
    "parameters": {},
    "recognized_tags": [],
    "confidence": 0.4,
    "ambiguities": ["requisito compuesto no representado por un unico intent"],
    "requires_clarification": True,
    "clarification_question": "¿Autoriza dividir el requerimiento en paro retardado y pilotos?",
    "unrecognized_terms": [],
    "semantic_validation": {
        "is_valid": False,
        "errors": [],
        "warnings": [],
        "missing_parameters": [],
        "unauthorized_tags": [],
        "requires_clarification": True
    }
}

RESOLVED_OUTPUT = {
    "intent_id": "INT_DELAYED_STOP",
    "command_text": "",
    "parameters": {
        "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
        "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch",
        "stop_delay_active": "M_StopDelayActive", "timer": "T_StopDelay"
    },
    "recognized_tags": ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"],
    "confidence": 0.97,
    "ambiguities": [],
    "requires_clarification": False,
    "clarification_question": None,
    "unrecognized_terms": [],
    "semantic_validation": {
        "is_valid": True,
        "errors": [],
        "warnings": [],
        "missing_parameters": [],
        "unauthorized_tags": [],
        "requires_clarification": False
    }
}

PHYSICAL_MISSING_OUTPUT = {
    "intent_id": "INT_DIRECT_OUTPUT",
    "command_text": "",
    "parameters": {"trigger_input": "I_DoorSensor"},
    "recognized_tags": ["I_DoorSensor"],
    "confidence": 0.9,
    "ambiguities": [],
    "requires_clarification": False,
    "clarification_question": None,
    "unrecognized_terms": [],
    "semantic_validation": {
        "is_valid": False,
        "errors": ["no autorizado"],
        "warnings": [],
        "missing_parameters": [],
        "unauthorized_tags": ["I_DoorSensor"],
        "requires_clarification": False
    }
}


def test_accepting_clarification_reprocesses_and_resolves_int_unknown(app, monkeypatch) -> None:
    """Aceptar no debe dejar INT_UNKNOWN sin hacer nada: debe reprocesar y continuar."""
    calls = {"count": 0}

    def fake_parse_command(command_text, **kwargs):
        calls["count"] += 1
        return dict(AMBIGUOUS_OUTPUT) if calls["count"] == 1 else dict(RESOLVED_OUTPUT)

    monkeypatch.setattr(gui, "parse_command", fake_parse_command)
    monkeypatch.setattr(gui, "ClarificationDialog", _stub_dialog("Si, autorizo el paro retardado."))

    app.command_textbox.insert("1.0", "Enciende un motor con un pulsante de inicio...")
    result = app.process_command()

    assert calls["count"] == 2
    assert result is True
    assert app.pending_semantic_output["intent_id"] == "INT_DELAYED_STOP"
    assert app.pending_semantic_output["semantic_validation"]["is_valid"] is True
    # la respuesta del usuario quedo registrada en el comando reprocesado
    assert "Respuesta del usuario: Si, autorizo el paro retardado." in app.command_textbox.get("1.0", "end")


def test_cancelling_clarification_stops_the_pipeline(app, monkeypatch) -> None:
    calls = {"count": 0}

    def fake_parse_command(command_text, **kwargs):
        calls["count"] += 1
        return dict(AMBIGUOUS_OUTPUT)

    monkeypatch.setattr(gui, "parse_command", fake_parse_command)
    monkeypatch.setattr(gui, "ClarificationDialog", _stub_dialog(None))

    app.command_textbox.insert("1.0", "un comando ambiguo cualquiera")
    result = app.process_command()

    assert calls["count"] == 1  # nunca se reproceso
    assert result is False


def test_physical_resource_missing_still_shows_informational_message_not_dialog(app, monkeypatch) -> None:
    """Un recurso fisico externo inexistente NO debe abrir el dialogo de aclaracion interactivo."""
    dialog_opened = {"value": False}

    def fake_parse_command(command_text, **kwargs):
        return dict(PHYSICAL_MISSING_OUTPUT)

    def _should_not_be_called(*args, **kwargs):
        dialog_opened["value"] = True
        raise AssertionError("ClarificationDialog no debe abrirse para un recurso fisico faltante")

    monkeypatch.setattr(gui, "parse_command", fake_parse_command)
    monkeypatch.setattr(gui, "ClarificationDialog", _should_not_be_called)

    app.command_textbox.insert("1.0", "activa la salida cuando se abra la puerta")
    result = app.process_command()

    assert result is False
    assert dialog_opened["value"] is False
