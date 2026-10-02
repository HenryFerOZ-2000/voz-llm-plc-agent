"""
MODO NORMAL — sin aclaraciones internas y con composicion funcional de requisitos.

  * el usuario nunca ve intenciones/INT_UNKNOWN/catalogo/schema/parser;
  * solo aclaraciones FUNCIONALES, de a una, estructuradas y sin repetir lo ya respondido;
  * comportamientos nuevos (p.ej. arranque estrella-triangulo) se componen con primitivas genericas
    (timed_sequence + never_together), sin intencion monolitica ni hardcode por frase;
  * Experimentacion conserva su comportamiento.
"""
from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

import gui  # noqa: E402
import llm_parser  # noqa: E402
import normal_interaction as NI  # noqa: E402
from code_generator import generate_implementation_from_ir  # noqa: E402
from ir_builder import build_project_ir  # noqa: E402
from io_allocator import apply_assignments  # noqa: E402
from project_packager import generate_project_package  # noqa: E402
from semantic_validator import validate_semantic_output  # noqa: E402
from trial_experiments import batch_runner as B  # noqa: E402
from utils import load_json_file  # noqa: E402

from test_phase1_download_and_trials import pipeline  # noqa: E402
from test_execute_full_pipeline import _base_semantic_output, temp_map, _tia_ready  # noqa: E402
from test_experiment_working_io_map import bench_map  # noqa: E402

__all__ = ["pipeline", "temp_map", "_tia_ready", "bench_map"]

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)
COMMAND = "Realiza un arranque estrella triangulo con pulsante de Start y Stop"
INTERNAL_QUESTION = ("El catálogo autorizado no contiene una intención ni parámetros capaces de representar la "
                     "secuencia completa. ¿Debe añadirse una intención autorizada específica?")
FUNCTIONAL_QUESTION = "¿Cuánto tiempo debe permanecer el motor conectado en estrella antes de cambiar a triángulo?"


def _sequence(duration: str | None) -> dict[str, Any]:
    first = {"outputs": ["Q_Main_Contactor", "Q_Star_Contactor"]}
    if duration:
        first["duration"] = duration
    return {"type": "timed_sequence", "start_input": "I_Start", "stop_input": "I_Stop",
            "steps": [first, {"outputs": ["Q_Main_Contactor", "Q_Delta_Contactor"]}]}


def _composed(duration: str | None = "T#2s") -> dict[str, Any]:
    output = _base_semantic_output("INT_UNKNOWN", {"emergency_input": "FALSE"},
                                   ["I_Start", "I_Stop", "Q_Main_Contactor", "Q_Star_Contactor", "Q_Delta_Contactor"])
    output["functional_requirements"] = [_sequence(duration),
                                         {"type": "never_together", "outputs": ["Q_Star_Contactor", "Q_Delta_Contactor"]}]
    return output


def _question(text: str) -> dict[str, Any]:
    output = _base_semantic_output("INT_UNKNOWN", {}, [])
    output.update({"requires_clarification": True, "clarification_question": text})
    output["semantic_validation"].update({"is_valid": False, "requires_clarification": True})
    return output


def _configs() -> tuple[dict, dict]:
    return load_json_file(_ROOT / "config" / "intents_catalog.json"), load_json_file(_ROOT / "config" / "safety_rules.json")


# ---------------------------------------------------------------------------------------------
# Composicion funcional (sin GUI)
# ---------------------------------------------------------------------------------------------

def test_star_delta_is_represented_by_generic_composition(bench_map, tmp_path):
    catalog, safety = _configs()
    io_map = load_json_file(bench_map)
    semantic = _composed("T#2s")
    validation = validate_semantic_output(semantic, io_map, catalog, safety)
    assert validation["is_valid"] is True and validation["errors"] == []  # INT_UNKNOWN + composicion = valido
    proposals = [p for p in validation["io_assignment_proposals"] if not p.get("blocked")]
    assert {p["proposed_name"] for p in proposals} == {"Q_Main_Contactor", "Q_Star_Contactor", "Q_Delta_Contactor"}
    updated = apply_assignments(copy.deepcopy(io_map), proposals, source="TEST")
    updated = updated[0] if isinstance(updated, tuple) else updated
    program = generate_implementation_from_ir(build_project_ir(semantic, updated, "SIEMENS_SCL_V18"))
    assert "I_Start" in program and "I_Stop" in program  # Start/Stop
    assert "PT := T#2s" in program  # el tiempo de estrella se incorpora
    assert "Q_Star_Contactor := (M_Seq1_S1)" in program and "Q_Delta_Contactor := (M_Seq1_S2)" in program
    assert "IF (Q_Star_Contactor AND Q_Delta_Contactor) THEN" in program  # invariante NEVER_TRUE_TOGETHER
    package = generate_project_package(semantic, "SIEMENS_SCL_V18", updated, catalog, safety, output_dir=tmp_path / "pkg")
    assert package["verification"]["is_valid"] is True  # generacion + verificador reales


def test_missing_star_time_produces_one_functional_question(bench_map):
    catalog, safety = _configs()
    validation = validate_semantic_output(_composed(duration=None), load_json_file(bench_map), catalog, safety)
    question = validation["clarification_question"]
    assert validation["requires_clarification"] is True and validation["is_valid"] is False
    assert "Cuánto tiempo" in question and "etapa 1" in question and question.count("?") == 1  # una sola pregunta
    assert not NI.is_internal_message(question)


def test_stages_are_exclusive_and_the_last_one_holds(bench_map):
    catalog, safety = _configs()
    program = generate_implementation_from_ir(build_project_ir(
        {**_composed("T#5s"), "recognized_tags": []}, _allocated_map(bench_map), "SIEMENS_SCL_V18"))
    assert program.count("PT := ") == 1  # solo la etapa 1 tiene temporizador; la ultima se mantiene
    assert "ELSIF I_Start AND NOT (M_Seq1_S1 OR M_Seq1_S2) THEN" in program


def _allocated_map(bench_map: Path) -> dict[str, Any]:
    catalog, safety = _configs()
    io_map = load_json_file(bench_map)
    validation = validate_semantic_output(_composed(), io_map, catalog, safety)
    updated = apply_assignments(copy.deepcopy(io_map), [p for p in validation["io_assignment_proposals"] if not p.get("blocked")],
                                source="TEST")
    return updated[0] if isinstance(updated, tuple) else updated


def test_no_phrase_or_case_hardcode_in_the_new_logic():
    for name in ("functional_requirements.py", "normal_interaction.py", "code_generator.py", "ir_builder.py",
                 "semantic_validator.py", "llm_parser.py"):
        code = "\n".join(line.split("#", 1)[0] for line in (_ROOT / "src" / name).read_text(encoding="utf-8").splitlines())
        for forbidden in ("estrella", "triangulo", "triángulo", "star_delta", "INT_STAR_DELTA"):
            assert forbidden not in code.lower(), (name, forbidden)
        assert not re.search(r"""["'](D(0[1-9]|1\d|20)|P(0[1-9]|1[0-2]))["']""", code), name
    catalog, _ = _configs()
    assert "INT_STAR_DELTA" not in catalog  # no se agrego una intencion monolitica


# ---------------------------------------------------------------------------------------------
# Politica de aclaraciones
# ---------------------------------------------------------------------------------------------

def test_internal_messages_are_classified_and_never_asked():
    for text in (INTERNAL_QUESTION, "¿Desea cambiar parser mode?", "¿Confirma el schema?", "INT_UNKNOWN: aclare",
                 "¿Desea añadir una nueva intención?"):
        assert NI.classify_clarification(text, [])["action"] == "capability_gap", text
    assert NI.classify_clarification(FUNCTIONAL_QUESTION, [])["action"] == "ask"
    assert NI.classify_clarification(FUNCTIONAL_QUESTION, [{"question": FUNCTIONAL_QUESTION, "answer": "2 s"}])["action"] == "repeated"
    shown, internal = NI.user_facing_errors(["La intencion no tiene plantilla implementada: INT_UNKNOWN", "Recurso sin canal fisico"])
    assert shown == ["Recurso sin canal fisico"] and len(internal) == 1


def test_llm_context_gets_policy_and_structured_history_only_in_normal(monkeypatch):
    contexts: list[dict[str, Any]] = []

    def _fake_invoke(command_text, llm_client, context, llm_response_text):
        contexts.append(dict(context))
        return llm_parser._normalize_semantic_output(_composed(), command_text), {}

    monkeypatch.setattr(llm_parser, "_invoke_llm", _fake_invoke)

    class _Client:
        def is_configured(self):
            return True

    history = [{"question": FUNCTIONAL_QUESTION, "answer": "2 segundos"}]
    llm_parser.parse_with_mode(COMMAND, mode="llm", llm_client=_Client(), interaction_profile="normal",
                               clarification_history=history)
    llm_parser.parse_with_mode(COMMAND, mode="llm", llm_client=_Client())
    normal, experiment = contexts[0], contexts[-1]
    assert "POLITICA DE MODO NORMAL" in normal["normal_mode_policy"] and "timed_sequence" in normal["normal_mode_policy"]
    assert normal["original_command"] == COMMAND
    assert normal["clarification_history"] == [{"clarification_question": FUNCTIONAL_QUESTION, "clarification_answer": "2 segundos"}]
    assert "normal_mode_policy" not in experiment and "clarification_history" not in experiment  # sin perfil: igual que antes


# ---------------------------------------------------------------------------------------------
# GUI (Modo Normal)
# ---------------------------------------------------------------------------------------------

@pytest.fixture
def normal(pipeline, monkeypatch):
    app = pipeline["app"]
    state: dict[str, Any] = {"calls": [], "dialogs": [], "infos": [], "errors": [], "answers": []}
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda t, m="", **k: state["infos"].append(m))
    monkeypatch.setattr(gui.messagebox, "showerror", lambda t, m="", **k: state["errors"].append(m))
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda t, m="", **k: state["errors"].append(m))

    class _Dialog:
        def __init__(self, parent, question):
            state["dialogs"].append(question)
            self.result = state["answers"].pop(0) if state["answers"] else None

    monkeypatch.setattr(gui, "ClarificationDialog", _Dialog)
    monkeypatch.setattr(app, "wait_window", lambda *a, **k: None)
    app.work_mode_var.set("Normal")
    app.command_textbox.delete("1.0", "end")
    app.command_textbox.insert("1.0", COMMAND)
    yield {"app": app, "state": state, "pipeline": pipeline}
    app._normal_clarification_state = None


def _script(monkeypatch, state, responses):
    def _parse(command_text, **kwargs):
        state["calls"].append({"command_text": command_text, **kwargs})
        return responses.pop(0)(kwargs) if callable(responses[0]) else responses.pop(0)
    monkeypatch.setattr(gui, "parse_command", _parse)


def test_internal_clarification_is_never_shown_to_the_user(normal, monkeypatch):
    app, state = normal["app"], normal["state"]
    _script(monkeypatch, state, [_question(INTERNAL_QUESTION)])
    assert app.process_command() is False
    assert state["dialogs"] == []  # no se abre el dialogo de aclaracion
    assert state["infos"] == [NI.PRODUCT_CAPABILITY_GAP_MESSAGE]
    for text in state["infos"] + state["errors"]:
        assert not NI.is_internal_message(text) and "INT_" not in text and "catálogo" not in text.lower()


def test_functional_clarification_is_shown_answered_and_reprocessed_structured(normal, monkeypatch):
    app, state = normal["app"], normal["state"]
    state["answers"] = ["2 segundos"]
    _script(monkeypatch, state, [_question(FUNCTIONAL_QUESTION), _composed("T#2s")])
    assert app.process_command() is True
    assert state["dialogs"] == [FUNCTIONAL_QUESTION]
    first, second = state["calls"]
    assert first["interaction_profile"] == "normal" and "clarification_history" not in first
    assert second["command_text"] == COMMAND  # comando ORIGINAL, sin concatenar texto libre
    assert second["clarification_history"] == [{"question": FUNCTIONAL_QUESTION, "answer": "2 segundos"}]
    assert app.command_textbox.get("1.0", "end").strip() != COMMAND + "\n\nAclaracion"


def test_already_answered_question_is_not_asked_again(normal, monkeypatch):
    app, state = normal["app"], normal["state"]
    state["answers"] = ["2 segundos", "otra vez"]
    _script(monkeypatch, state, [_question(FUNCTIONAL_QUESTION), _question(FUNCTIONAL_QUESTION)])
    assert app.process_command() is False
    assert state["dialogs"] == [FUNCTIONAL_QUESTION]  # una sola vez
    assert state["infos"] == [NI.PRODUCT_CAPABILITY_GAP_MESSAGE]


def test_validator_derived_functional_question_reaches_the_user(normal, monkeypatch, bench_map):
    from test_experiment_working_io_map import _use_bench_copy

    app, state = normal["app"], normal["state"]
    _use_bench_copy(app, bench_map)  # banco real (copia): recursos suficientes para la composicion
    catalog, safety = _configs()
    missing = _composed(duration=None)
    missing["semantic_validation"] = validate_semantic_output(missing, load_json_file(app.io_map_path), catalog, safety)
    state["answers"] = ["2 segundos"]
    _script(monkeypatch, state, [missing, _composed("T#2s")])
    assert app.process_command() is True
    assert len(state["dialogs"]) == 1 and "etapa 1" in state["dialogs"][0]


def test_internal_validation_errors_are_logged_not_shown(normal, monkeypatch):
    app, state = normal["app"], normal["state"]
    invalid = _base_semantic_output("INT_UNKNOWN", {}, [])
    invalid["semantic_validation"].update({"is_valid": False, "errors": ["La intencion no tiene plantilla implementada: INT_UNKNOWN"]})
    _script(monkeypatch, state, [invalid])
    assert app.process_command() is False
    assert state["infos"] == [NI.PRODUCT_CAPABILITY_GAP_MESSAGE] and state["errors"] == []


def test_composed_int_unknown_proceeds_to_generation_in_normal_mode(normal, monkeypatch):
    app, state, pipeline = normal["app"], normal["state"], normal["pipeline"]
    composed = _composed("T#2s")
    _script(monkeypatch, state, [composed])
    assert app.process_command() is True  # INT_UNKNOWN + composicion valida no se bloquea


def test_experimentation_parse_call_is_unchanged(pipeline, monkeypatch):
    app = pipeline["app"]
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(gui, "parse_command", lambda text, **kwargs: calls.append(kwargs) or _composed())
    app.work_mode_var.set("Experimentacion")
    try:
        app.command_textbox.delete("1.0", "end")
        app.command_textbox.insert("1.0", COMMAND)
        app.process_command()
    finally:
        app.work_mode_var.set("Normal")
    assert calls and "interaction_profile" not in calls[0] and "clarification_history" not in calls[0]


def test_voice_normal_uses_the_same_semantic_pipeline(normal, monkeypatch):
    app, state = normal["app"], normal["state"]
    _script(monkeypatch, state, [_composed("T#2s"), _composed("T#2s")])
    app.process_command()  # texto
    text_kwargs = {k: v for k, v in state["calls"][0].items() if k != "command_text"}
    from test_normal_voice_auto_flow import TRANSCRIPT  # noqa: F401  (misma ruta: execute_full_pipeline -> process_command)
    app._normal_voice_flow = {"active": True}
    try:
        app.process_command()  # mismo metodo que usa el flujo por voz tras la transcripcion
    finally:
        app._normal_voice_flow = None
    voice_kwargs = {k: v for k, v in state["calls"][1].items() if k != "command_text"}
    assert sorted(text_kwargs) == sorted(voice_kwargs) and voice_kwargs["interaction_profile"] == "normal"


def test_resolved_clarification_in_voice_flow_does_not_block_download(normal, monkeypatch):
    import normal_voice

    app, state = normal["app"], normal["state"]
    state["answers"] = ["2 segundos"]
    _script(monkeypatch, state, [_question(FUNCTIONAL_QUESTION), _composed("T#2s")])
    app._normal_voice_flow = normal_voice.new_flow(_ROOT)
    try:
        assert app.process_command() is True
        flow = app._normal_voice_flow
        for stage in ("Semantica", "I/O", "Generacion", "Verificacion"):
            flow["stages"][stage] = "ok"
        allowed, reason = normal_voice.download_allowed(flow, True)
        # Aclaracion RESUELTA: queda registrada, pero no impide la descarga encadenada.
        assert flow["clarification_requested"] is True and flow["clarification_pending"] is False and allowed is True
    finally:
        app._normal_voice_flow = None


def test_experimentation_artifacts_unchanged():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
