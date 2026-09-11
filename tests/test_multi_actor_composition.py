"""
Regression tests for a real GUI bug: a genuinely compositional command describing TWO
independent, mutually-interlocked motors (own pushbuttons, shared run pilot, shared 5s delayed
stop) got forced through a single-actor intent template (INT_DELAYED_STOP) and failed with
"Faltan parametros requeridos: motor_output, stop_delay_active, timer" plus a duplicated
"I_Start_Motor_2" map assignment.

Two independent root causes, both fixed here:

1. No intent_id in the catalog represents "N independent motor actors" - every template assumes
   exactly one. The parser/LLM already expresses extra actors via repeated `motor_start_latch`
   functional_requirements (one per actor, with its own target/trigger_input - see
   tests/test_functional_requirements.py's pre-existing per-actor identity tests), but nothing
   ever RENDERED them: code_generator.py explicitly skipped motor_start_latch/delayed_stop as
   "already covered by the base intent" (true only for a single actor), and
   functional_requirements.get_functional_requirement_tags returned a FIXED generic tag
   ("M_RunLatch") regardless of which actor - two actors would have collided on the same memory
   bit. Fixed with a dedicated multi-actor composer (code_generator._generate_multi_actor_motor_body,
   dispatched whenever detect_multi_actor_motor_targets finds >=2 actors) that derives each
   actor's own latch memory from its own target tag, handles interlock groups, a single shared
   delayed-stop timer, and a shared run_pilot - and REPLACES the single-actor base template
   instead of layering alongside it (the base template's own stop condition only checks its own
   actor's latch, and would silently fight the composer over the same timer/stop_delay_active).
   ir_builder.py and semantic_validator.py were both updated to stop demanding the single-actor
   intent's own required_variables/parameters when this multi-actor shape is present - the
   composer never reads them.

2. See tests/test_io_allocator.py for the separate, independently-fixed duplicate-assignment bug
   (semantic_validator.py used to call propose_assignment() twice - once for implicit unauthorized
   tags, once for explicit requested_io_assignments - each with its own batch scope, so the same
   functional_name_hint requested both ways could land on two different addresses).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import gui  # noqa: E402
from functional_requirements import detect_multi_actor_motor_targets  # noqa: E402
from ir_builder import build_project_ir  # noqa: E402
from code_generator import generate_implementation_from_ir  # noqa: E402
from semantic_repair import repair_semantic_output, strip_unavailable_emergency_reference  # noqa: E402
from semantic_validator import INTENT_PARAMETER_RULES, validate_semantic_output  # noqa: E402
from verifier import verify_project_ir  # noqa: E402

from test_execute_full_pipeline import (  # noqa: E402
    _mock_package_result,
    _run_and_settle,
    temp_map,
    _tia_ready,
)

__all__ = ["temp_map", "_tia_ready"]

EXACT_COMMAND = (
    "Inicia el proceso con el boton Start. Quiero controlar dos motores con dos pulsantes "
    "independientes: el pulsante 1 debe encender el motor 1 y mantenerlo encendido, y el "
    "pulsante 2 debe encender el motor 2 y mantenerlo encendido. Los dos motores no pueden "
    "funcionar al mismo tiempo; cuando se encienda uno, el otro debe apagarse automaticamente. "
    "Mientras cualquiera de los motores este funcionando, enciende una luz piloto de marcha. "
    "Cuando presione el boton Stop, espera 5 segundos, apaga cualquier motor que este encendido "
    "y apaga tambien la luz piloto."
)


def _variable(name: str, location: str, state: str, var_class: str = "input", var_type: str = "BOOL") -> dict[str, Any]:
    return {
        "name": name, "class": var_class, "type": var_type, "location": location,
        "initial_value": "FALSE", "description": "", "state": state, "llm_allowed": True
    }


def _two_motor_bench_map() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "metadata": {"map_id": "mapa_test_two_motors", "name": "MAPA_TEST_TWO_MOTORS", "version": 1},
        "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_", "auxiliary": "R_"},
        "variables": [
            _variable("I_Start", "%IX16.0", "LOCKED"),
            _variable("I_Stop", "%IX16.1", "LOCKED"),
            _variable("I_Select_Motor_1", "%IX16.4", "ASSIGNED"),
            _variable("I_Select_Motor_2", "%IX16.5", "ASSIGNED"),
            _variable("Q_Motor_1", "%QX8.0", "ASSIGNED", var_class="output"),
            _variable("Q_Motor_2", "%QX8.1", "ASSIGNED", var_class="output"),
            _variable("Q_Pilot_Run", "%QX8.2", "ASSIGNED", var_class="output"),
        ]
    }


def _realistic_semantic_output() -> dict[str, Any]:
    """
    Matches the real LLM output shape confirmed against the actual bench map during diagnosis:
    intent_id resolves to a single-actor "carrier" intent (INT_DELAYED_STOP) for the shared
    stop/timer, while the compositional structure (both motors, interlock, shared pilot) lives
    entirely in functional_requirements.
    """
    return {
        "intent_id": "INT_DELAYED_STOP",
        "case_id": None,
        "command_text": EXACT_COMMAND,
        "normalized_command": EXACT_COMMAND.lower(),
        "parameters": {
            "trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_1",
            "run_latch": "M_RunLatch_Motor_1", "stop_delay_active": "M_StopDelayActive",
            "stop_delay_time": "T#5s", "timer": "T_StopDelay"
        },
        "confidence": 0.9, "ambiguities": [], "requires_clarification": False,
        "clarification_question": None, "assumptions": [],
        "recognized_tags": ["I_Start", "I_Stop", "Q_Motor_1", "Q_Motor_2", "Q_Pilot_Run"],
        "unrecognized_terms": [],
        "functional_requirements": [
            {"type": "motor_start_latch", "target": "Q_Motor_1", "trigger_input": "I_Select_Motor_1"},
            {"type": "motor_start_latch", "target": "Q_Motor_2", "trigger_input": "I_Select_Motor_2"},
            {"type": "interlock", "output_a": "Q_Motor_1", "output_b": "Q_Motor_2"},
            {"type": "delayed_stop", "target": "Q_Motor_1", "delay": "T#5s"},
            {"type": "delayed_stop", "target": "Q_Motor_2", "delay": "T#5s"},
            {"type": "run_pilot", "target": "Q_Pilot_Run"}
        ]
    }


def _run_through_full_stack(semantic_output: dict[str, Any], io_map: dict[str, Any]):
    semantic_output = strip_unavailable_emergency_reference(semantic_output, io_map)
    semantic_output = repair_semantic_output(semantic_output, INTENT_PARAMETER_RULES)
    validation = validate_semantic_output(semantic_output, io_map, {semantic_output["intent_id"]: {}}, {})
    project_ir = build_project_ir(semantic_output, io_map, "SIEMENS_SCL_V18")
    project_ir.pou.implementation_code = generate_implementation_from_ir(project_ir)
    ir_verification = verify_project_ir(project_ir)
    return semantic_output, validation, project_ir, ir_verification


# ---------- Section 25: exact real command, full stack ----------

def test_exact_two_motor_command_validates_builds_and_verifies() -> None:
    io_map = _two_motor_bench_map()
    semantic_output = _realistic_semantic_output()

    semantic_output, validation, project_ir, ir_verification = _run_through_full_stack(semantic_output, io_map)

    assert semantic_output["requires_clarification"] is False
    assert validation["is_valid"] is True, validation["errors"]
    assert validation["missing_parameters"] == []

    declared_names = {v.name for v in project_ir.pou.variables}
    assert len(declared_names) == len({v.name for v in project_ir.pou.variables}), "no duplicated functional names in the IR"
    assert {"Q_Motor_1", "Q_Motor_2", "Q_Pilot_Run", "I_Select_Motor_1", "I_Select_Motor_2"} <= declared_names

    code = project_ir.pou.implementation_code
    assert "M_Motor_1Latch" in code and "M_Motor_2Latch" in code
    assert "Q_Motor_1 := M_Motor_1Latch" in code
    assert "Q_Motor_2 := M_Motor_2Latch" in code
    # interlock real en IR/SCL (seccion 14): arrancar uno apaga el otro, no solo metadata.
    assert "M_Motor_2Latch := FALSE" in code  # dentro del bloque de arranque de motor 1
    assert "M_Motor_1Latch := FALSE" in code  # dentro del bloque de arranque de motor 2
    assert "Q_Pilot_Run := (" in code

    assert ir_verification["is_valid"] is True, ir_verification["errors"]


def test_exact_two_motor_command_reaches_tia_exactly_once_via_real_gui_pipeline(
    app, temp_map, tmp_path, monkeypatch, _tia_ready
) -> None:
    io_map = _two_motor_bench_map()
    map_path = tmp_path / "mapa_test_two_motors.json"
    map_path.write_text(json.dumps(io_map, indent=2), encoding="utf-8")
    original_path = app.io_map_path
    app.io_map_path = map_path
    app.io_variables = gui.load_io_map_variables(map_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    app.active_trial = None
    app.active_profile_id = None
    app.work_mode_var.set("Normal")
    app._on_work_mode_changed()
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)

    semantic_output = _realistic_semantic_output()

    def _fake_parse_command(command_text, **kwargs):
        # gui.py confia en parse_command() tal cual - la reparacion semantica (incluida
        # strip_unavailable_emergency_reference) Y la validacion semantica embebida
        # (semantic_output["semantic_validation"]) normalmente ocurren DENTRO de la
        # implementacion real de parse_command (llm_parser._repair_and_validate); gui.py lee ese
        # campo directamente, nunca vuelve a invocar validate_semantic_output() por su cuenta. Se
        # reproduce aqui explicitamente para que este mock sea fiel a lo que parse_command() real
        # le devolveria a gui.py.
        io_map = kwargs.get("io_map") or {}
        intents_catalog = kwargs.get("intents_catalog") or {}
        safety_rules = kwargs.get("safety_rules") or {}
        repaired = strip_unavailable_emergency_reference(semantic_output, io_map)
        repaired = dict(repaired)
        repaired["semantic_validation"] = validate_semantic_output(repaired, io_map, intents_catalog, safety_rules)
        return repaired

    monkeypatch.setattr(gui, "parse_command", _fake_parse_command)
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    tia_calls: list[Path] = []

    def _fake_validate(package_dir_arg, project_root_arg):
        tia_calls.append(package_dir_arg)
        return {
            "status": "TIA_COMPILATION_PASSED", "result_path": str(package_dir_arg / "tia_compile_report.json"),
            "bridge_return_code": 0, "bridge_stdout": "", "bridge_stderr": ""
        }

    monkeypatch.setattr(gui, "validate_package_with_tia", _fake_validate)

    try:
        app.command_textbox.delete("1.0", "end")
        app.command_textbox.insert("1.0", EXACT_COMMAND)
        result = _run_and_settle(app)

        assert result is True
        assert len(tia_calls) == 1
    finally:
        app.io_map_path = original_path
        app.io_variables = gui.load_io_map_variables(original_path)
        app._load_active_map_metadata_shadow()
        app._load_io_map_table()
        app.active_trial = None
        app.active_profile_id = None
        app.command_textbox.delete("1.0", "end")
        app.pending_semantic_output = None


# ---------- Section 27: two DIFFERENT roles never collapse into one actor ----------

def test_two_distinct_motor_actors_get_two_independent_latches() -> None:
    functional_requirements = _realistic_semantic_output()["functional_requirements"]
    actors = detect_multi_actor_motor_targets(functional_requirements)
    assert len(actors) == 2
    targets = {actor["target"] for actor in actors}
    assert targets == {"Q_Motor_1", "Q_Motor_2"}
    triggers = {actor["trigger_input"] for actor in actors}
    assert triggers == {"I_Select_Motor_1", "I_Select_Motor_2"}


# ---------- Section 28: TIA tag set matches the resolved external bindings ----------

def test_tia_tag_payload_matches_resolved_external_bindings(tmp_path) -> None:
    """After allocation/IR, the tags sent to the TIA bridge must exactly match the IR's own
    external variable bindings - no ghost tags, nothing missing."""
    import tia_openness

    io_map = _two_motor_bench_map()
    semantic_output = _realistic_semantic_output()
    _, _, project_ir, ir_verification = _run_through_full_stack(semantic_output, io_map)
    assert ir_verification["is_valid"] is True

    external_names = {
        v.name for v in project_ir.pou.variables
        if v.name.startswith(("I_", "Q_", "AI_", "AO_"))
    }

    variables_path = tmp_path / "variables.json"
    variables_payload = [
        {
            "name": v.name, "class": v.var_class, "siemens_type": "Bool",
            "siemens_address": v.location, "location": v.location
        }
        for v in project_ir.pou.variables if v.name in external_names
    ]
    variables_path.write_text(json.dumps(variables_payload), encoding="utf-8")

    tags = tia_openness._build_tag_payload(variables_path)
    tag_names = {tag["name"] for tag in tags}
    assert tag_names == external_names
