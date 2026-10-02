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


def _temp_map_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "metadata": {"map_id": "mapa_test_clarification", "name": "MAPA_TEST_CLARIFICATION", "version": 1},
        "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_", "auxiliary": "R_"},
        "variables": [
            {"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0", "initial_value": "FALSE", "description": "", "state": "LOCKED", "llm_allowed": True},
            {"name": "I_Stop", "class": "input", "type": "BOOL", "location": "%IX0.1", "initial_value": "FALSE", "description": "", "state": "LOCKED", "llm_allowed": True},
            {"name": "I_Emergency", "class": "input", "type": "BOOL", "location": "%IX0.2", "initial_value": "FALSE", "description": "", "state": "ASSIGNED", "llm_allowed": True},
            {"name": "Q_Motor_Enable", "class": "output", "type": "BOOL", "location": "%QX0.0", "initial_value": "FALSE", "description": "", "state": "ASSIGNED", "llm_allowed": True},
            {"name": "M_RunLatch", "class": "internal", "type": "BOOL", "location": "", "initial_value": "FALSE", "description": "", "state": "ASSIGNED", "llm_allowed": True},
            {"name": "M_StopDelayActive", "class": "internal", "type": "BOOL", "location": "", "initial_value": "FALSE", "description": "", "state": "ASSIGNED", "llm_allowed": True},
            {"name": "T_StopDelay", "class": "timer", "type": "TON", "location": "", "initial_value": "", "description": "", "state": "ASSIGNED", "llm_allowed": True}
        ]
    }


@pytest.fixture(autouse=True)
def _reset_state(app, tmp_path, monkeypatch):
    # Redirige el mapa activo a una copia temporal (patron `temp_map` ya establecido en el resto
    # de la suite - ver test_gui_map_config.py, test_io_inventory_preserved.py, etc.): estos tests
    # llaman a app.process_command(), cuyo primer paso ya guarda el mapa activo
    # (save_io_map) - sin redirigir, eso escribe de verdad sobre el mapa fisico real del proyecto,
    # incluso cuando el contenido termina siendo identico (seccion "separar parse de
    # persistencia").
    map_path = tmp_path / "mapa_test_clarification.json"
    map_path.write_text(json.dumps(_temp_map_payload(), indent=2), encoding="utf-8")
    original_path = app.io_map_path
    app.io_map_path = map_path
    app.io_variables = gui.load_io_map_variables(map_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    app.work_mode_var.set("Normal")
    app._on_work_mode_changed()
    app.command_textbox.delete("1.0", "end")
    app.pending_semantic_output = None
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    yield
    app.io_map_path = original_path
    # Ver test_autonomous_resource_resolution.py::temp_map - recargar io_variables/io_tree desde
    # el mapa real tras restaurar el path, para que el `app` de sesion compartida no quede
    # mostrando el inventario pequeno de este archivo mientras el path ya apunta de vuelta al real.
    app.io_variables = gui.load_io_map_variables(original_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()


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

STRUCTURAL_VALIDATION_ERROR_OUTPUT = {
    # Caso real reportado: intent resuelto con confianza, requires_clarification=False y
    # clarification_question=None, pero is_valid=False porque los parametros que trae no
    # coinciden con lo que esa plantilla necesita (p. ej. un LLM que interpreto un comando de
    # varios motores con una forma de parametros que INT_MOTOR_START_STOP no puede consumir). Esto
    # es un ERROR DE VALIDACION, no una ambiguedad - nunca debe abrir ClarificationDialog.
    "intent_id": "INT_MOTOR_START_STOP",
    "command_text": "",
    "parameters": {"process_start_input": "I_Start", "motor_outputs": ["Q_Motor_1", "Q_Motor_2", "Q_Motor_3"]},
    "recognized_tags": ["I_Start", "Q_Motor_1", "Q_Motor_2", "Q_Motor_3"],
    "confidence": 0.94,
    "ambiguities": [],
    "requires_clarification": False,
    "clarification_question": None,
    "unrecognized_terms": [],
    "semantic_validation": {
        "is_valid": False,
        "errors": ["Faltan parametros requeridos: trigger_input, motor_output, run_latch"],
        "warnings": [],
        "missing_parameters": ["trigger_input", "motor_output", "run_latch"],
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
    calls = {"count": 0, "received": []}

    def fake_parse_command(command_text, **kwargs):
        calls["count"] += 1
        calls["received"].append({"command_text": command_text, **kwargs})
        return dict(AMBIGUOUS_OUTPUT) if calls["count"] == 1 else dict(RESOLVED_OUTPUT)

    monkeypatch.setattr(gui, "parse_command", fake_parse_command)
    monkeypatch.setattr(gui, "ClarificationDialog", _stub_dialog("Si, autorizo el paro retardado."))

    app.command_textbox.insert("1.0", "Enciende un motor con un pulsante de inicio...")
    result = app.process_command()

    assert calls["count"] == 2
    assert result is True
    assert app.pending_semantic_output["intent_id"] == "INT_DELAYED_STOP"
    assert app.pending_semantic_output["semantic_validation"]["is_valid"] is True
    # Modo Normal: la respuesta se incorpora de forma ESTRUCTURADA (comando original + {pregunta, respuesta}),
    # nunca concatenada como texto libre en el comando.
    reprocessed = calls["received"][1]
    assert reprocessed["command_text"] == "Enciende un motor con un pulsante de inicio..."
    assert reprocessed["clarification_history"][0]["answer"] == "Si, autorizo el paro retardado."
    assert "Respuesta del usuario" not in app.command_textbox.get("1.0", "end")


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


# ---------- Regresion: is_valid=False sin requires_clarification real NUNCA abre el dialogo ----------

def test_structural_validation_error_without_real_question_never_opens_clarification_dialog(app, monkeypatch) -> None:
    """
    Bug reportado: la interpretacion final tenia requires_clarification=False y
    clarification_question=None, pero is_valid=False (parametros estructuralmente incompatibles
    con la plantilla del intent elegido) - el pipeline abria igual ClarificationDialog con una
    pregunta de relleno generica (la caja se veia "vacia"). Unica fuente de verdad: sin
    requires_clarification=True + pregunta real, jamas se abre el dialogo - se muestran los
    errores de validacion reales en su lugar.
    """
    dialog_opened = {"value": False}
    error_messages: list[str] = []

    def fake_parse_command(command_text, **kwargs):
        return dict(STRUCTURAL_VALIDATION_ERROR_OUTPUT)

    def _should_not_be_called(*args, **kwargs):
        dialog_opened["value"] = True
        raise AssertionError("ClarificationDialog no debe abrirse para un error de validacion estructural")

    monkeypatch.setattr(gui, "parse_command", fake_parse_command)
    monkeypatch.setattr(gui, "ClarificationDialog", _should_not_be_called)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, message, *a, **k: error_messages.append(message))

    app.command_textbox.insert("1.0", "comando con tres motores independientes")
    result = app.process_command()

    assert result is False
    assert dialog_opened["value"] is False
    assert len(error_messages) == 1
    assert "trigger_input" in error_messages[0]


def test_resolve_semantic_ambiguity_refuses_to_open_dialog_without_a_real_question(app, monkeypatch) -> None:
    """Guardia defensiva secundaria: aunque algo llame _resolve_semantic_ambiguity directamente
    con un semantic_output sin clarification_question real, no debe abrir un dialogo vacio."""
    dialog_opened = {"value": False}

    def _should_not_be_called(*args, **kwargs):
        dialog_opened["value"] = True
        raise AssertionError("ClarificationDialog no debe abrirse sin clarification_question real")

    monkeypatch.setattr(gui, "ClarificationDialog", _should_not_be_called)

    result = app._resolve_semantic_ambiguity("comando de prueba", dict(STRUCTURAL_VALIDATION_ERROR_OUTPUT))

    assert result is False
    assert dialog_opened["value"] is False


def test_real_ambiguity_with_a_question_still_opens_the_dialog(app, monkeypatch) -> None:
    """Regresion inversa: no romper el caso legitimo - requires_clarification=True con una
    pregunta real SI debe seguir abriendo ClarificationDialog."""
    dialog_calls: list[str] = []

    def fake_parse_command(command_text, **kwargs):
        return dict(AMBIGUOUS_OUTPUT)

    def _stub(parent, question):
        dialog_calls.append(question)
        return _stub_dialog(None)(parent, question)

    monkeypatch.setattr(gui, "parse_command", fake_parse_command)
    monkeypatch.setattr(gui, "ClarificationDialog", _stub)

    app.command_textbox.insert("1.0", "un comando genuinamente ambiguo")
    app.process_command()

    assert len(dialog_calls) == 1
    assert dialog_calls[0] == AMBIGUOUS_OUTPUT["clarification_question"]
