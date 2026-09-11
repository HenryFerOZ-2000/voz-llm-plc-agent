"""
Regression tests for a real, architectural bug: physical external resources (I_Reset, Q_Alarm,
Q_Pilot_Run, Q_Pilot_Fault, ...) were being required/declared/generated for INT_MOTOR_START_STOP
even when the command never asked for reset/alarm/pilot behavior, purely because THREE independent
layers each hardcoded a physical-tag default for an OPTIONAL feature key whenever it was absent
from `parameters`:

  1. semantic_parser._build_motor_start_stop_parameters (rule-based fallback): always set
     reset_input/alarm_output/run_indicator/fault_indicator to "I_Reset"/"Q_Alarm"/"Q_Pilot_Run"/
     "Q_Pilot_Fault" via tags.get(key, default), even when `extract_tags` correctly left those
     keys absent from `tags` (i.e. the command text never mentioned reset/alarm/pilot).
  2. ir_builder.get_required_variables_for_intent: parameters.get("reset_input", "I_Reset") etc.
     unconditionally added these to `required_variables`, regardless of what the parser produced -
     even a perfectly minimal LLM output without those keys would still get them re-injected here.
  3. code_generator._generate_motor_start_stop_body: the same _param(..., default="I_Reset")
     pattern spliced the literal tag into the generated SCL text unconditionally.

Exactly the same class of bug already fixed once for I_Emergency (see
test_emergency_absent_key_regression.py) - this time for reset/alarm/pilot indicators, fixed at
the ROOT (all three layers, not a narrow "if I_Reset not in map: strip it" patch) via a single
`OPTIONAL_PARAMETER_KEYS` registry (ir_builder.py): a key listed there is only ever added to
`parameters`/`required_variables`/generated SCL if it is ACTUALLY PRESENT - never backfilled with
a historical physical-tag default. Absent optional keys make the whole feature branch disappear
(reset clause, alarm assignment, pilot assignments) rather than being neutralized to FALSE - FALSE
is reserved for boolean SAFETY inputs like emergency_input (a separate, already-existing
mechanism), not for arbitrary optional outputs/inputs.

Reported real-world trigger (exact command): "Enciende un motor con el boton Start y apagalo con
el boton Stop." against a bench map with I_Start/I_Stop LOCKED and no I_Reset/Q_Alarm/Q_Pilot_Run/
Q_Pilot_Fault at all -> used to fail with "Recurso externo no autorizado/no existente en el mapa
PLC: I_Reset".
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
from code_generator import generate_implementation_from_ir  # noqa: E402
from ir_builder import OPTIONAL_PARAMETER_KEYS, build_project_ir, get_required_variables_for_intent  # noqa: E402
from semantic_parser import extract_tags, parse_command as rule_based_parse_command  # noqa: E402
from semantic_repair import repair_semantic_output, strip_unavailable_emergency_reference  # noqa: E402
from semantic_validator import INTENT_PARAMETER_RULES, validate_semantic_output  # noqa: E402
from verifier import verify_project_ir  # noqa: E402

from test_execute_full_pipeline import (  # noqa: E402
    _run_and_settle,
    _tia_ready,
)

__all__ = ["_tia_ready"]

_REAL_GUI_PARSE_COMMAND = gui.parse_command


_GHOST_TAG_NAMES = (
    "I_Reset", "I_Emergency", "Q_Alarm", "Q_Pilot_Run", "Q_Pilot_Fault", "Q_Pilot_Stop",
    "I_Mode_Auto", "I_Mode_Manual"
)


def _variable(name: str, location: str, state: str, var_class: str = "input", var_type: str = "BOOL") -> dict[str, Any]:
    return {
        "name": name, "class": var_class, "type": var_type, "location": location,
        "initial_value": "FALSE", "description": "", "state": state, "llm_allowed": True
    }


def _minimal_bench_map() -> dict[str, Any]:
    """
    Section 17's exact "caso base obligatorio": I_Start/I_Stop LOCKED, a handful of other free
    DI/DO available, and DELIBERATELY none of I_Reset/I_Emergency/Q_Alarm/Q_Pilot_Run/
    Q_Pilot_Fault/I_Mode_Auto/I_Mode_Manual - so any of those appearing anywhere downstream is a
    genuine ghost tag, not a coincidental map match.
    """
    return {
        "schema_version": 1,
        "metadata": {"map_id": "mapa_test_optional_resources", "name": "MAPA_TEST_OPTIONAL", "version": 1},
        "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_", "auxiliary": "R_"},
        "variables": [
            _variable("I_Start", "%IX16.0", "LOCKED"),
            _variable("I_Stop", "%IX16.1", "LOCKED"),
            _variable("I_Sensor1", "%IX16.2", "FREE"),
            _variable("Q_Free1", "%QX8.0", "FREE", var_class="output"),
            _variable("Q_Free2", "%QX8.1", "FREE", var_class="output"),
            _variable("Q_Free3", "%QX8.2", "FREE", var_class="output"),
        ]
    }


def _map_with_reset_and_alarm() -> dict[str, Any]:
    variables = _minimal_bench_map()["variables"] + [
        _variable("I_Reset", "%IX16.4", "LOCKED"),
        _variable("Q_Alarm", "%QX8.3", "ASSIGNED", var_class="output")
    ]
    return {
        "schema_version": 1,
        "metadata": {"map_id": "mapa_test_optional_resources_full", "name": "MAPA_TEST_OPTIONAL_FULL", "version": 1},
        "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_", "auxiliary": "R_"},
        "variables": variables
    }


def _serialize_ir(project_ir) -> str:
    """
    Same exclusion as test_emergency_absent_key_regression.py (safety_rules carries general
    project-policy prose unrelated to what THIS program references), plus
    metadata.authorized_variables: that field intentionally lists the FULL set of tags the active
    map authorizes (build_io_map_index(io_map).keys() | declared variable names) for audit
    purposes - it is the map's inventory, not "tags this program uses". A map that happens to
    physically HAVE I_Reset/Q_Alarm (test_no_ghost_tags_for_minimal_motor_command_regardless_of_map_contents)
    legitimately lists them there even when this program never references them anywhere else.
    """
    payload = project_ir.to_dict()
    payload.pop("safety_rules", None)
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("authorized_variables", None)
        nested_semantic_output = metadata.get("semantic_output")
        if isinstance(nested_semantic_output, dict):
            # "assumptions" es prosa descriptiva (p.ej. "Se agrega I_Emergency por seguridad
            # industrial obligatoria.", generada por semantic_parser incluso en bancos sin
            # I_Emergency fisico) - no es una referencia funcional real en variables/expresiones,
            # asi que no participa del invariante "ningun ghost tag en la IR".
            nested_semantic_output.pop("assumptions", None)
    return json.dumps(payload, default=str)


# ---------- Section 39 diagnosis, reproduced as a direct unit check on the rule-based parser ----

def test_rule_based_parser_omits_optional_keys_when_not_mentioned() -> None:
    tags = extract_tags("Enciende un motor con el boton Start y apagalo con el boton Stop.")
    assert "reset" not in tags
    assert "alarm" not in tags
    assert "pilot_run" not in tags
    assert "pilot_fault" not in tags

    semantic_output = rule_based_parse_command("Enciende un motor con el boton Start y apagalo con el boton Stop.")
    assert semantic_output["intent_id"] == "INT_MOTOR_START_STOP"
    parameters = semantic_output["parameters"]
    for optional_key in OPTIONAL_PARAMETER_KEYS["INT_MOTOR_START_STOP"]:
        assert optional_key not in parameters, f"{optional_key} no fue solicitado y no debe aparecer"


def test_rule_based_parser_includes_reset_when_explicitly_requested() -> None:
    semantic_output = rule_based_parse_command(
        "Enciende el motor con Start, apagalo con Stop y usa un pulsante Reset para restablecer la falla."
    )
    assert semantic_output["parameters"]["reset_input"] == "I_Reset"
    assert "alarm_output" not in semantic_output["parameters"]


# ---------- Section 13/15: get_required_variables_for_intent / build_project_ir direct checks ---

def test_required_variables_omit_optional_tags_when_absent_from_parameters() -> None:
    parameters = {
        "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
        "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch", "fault_latch": "M_FaultLatch"
    }
    required = get_required_variables_for_intent("INT_MOTOR_START_STOP", parameters)
    for optional_key_default in ("I_Reset", "Q_Alarm", "Q_Pilot_Run", "Q_Pilot_Fault"):
        assert optional_key_default not in required
    assert {"I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable", "M_RunLatch", "M_FaultLatch"} <= set(required)


def test_required_variables_include_reset_only_when_present() -> None:
    parameters = {
        "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
        "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch", "fault_latch": "M_FaultLatch",
        "reset_input": "I_Reset"
    }
    required = get_required_variables_for_intent("INT_MOTOR_START_STOP", parameters)
    assert "I_Reset" in required
    assert "Q_Alarm" not in required


# ---------- Section 35: end-to-end, exact reported command, no ghost tags anywhere ---------------

def _run_through_full_stack(semantic_output: dict[str, Any], io_map: dict[str, Any]):
    # semantic_parser.parse_command() (the bare rule-based parser, used directly in these tests to
    # isolate the fix from llm_parser's wrapper) does not set this key at all - llm_parser.
    # parse_command's _repair_and_validate normally backfills it before validate_semantic_output
    # ever sees the payload. Same normalization, applied explicitly here.
    semantic_output.setdefault("functional_requirements", [])
    semantic_output = strip_unavailable_emergency_reference(semantic_output, io_map)
    semantic_output = repair_semantic_output(semantic_output, INTENT_PARAMETER_RULES)
    validation = validate_semantic_output(semantic_output, io_map, {semantic_output["intent_id"]: {}}, {})
    project_ir = build_project_ir(semantic_output, io_map, "SIEMENS_SCL_V18")
    project_ir.pou.implementation_code = generate_implementation_from_ir(project_ir)
    ir_verification = verify_project_ir(project_ir)
    return semantic_output, validation, project_ir, ir_verification


def test_minimal_start_stop_command_never_requires_optional_tags() -> None:
    """
    Section 17's exact caso base: the reported command against a map that only has I_Start/I_Stop
    LOCKED plus free channels for Q_Motor_Enable to be auto-allocated into. Uses the REAL
    rule-based parser output directly (parameters already omit the optional keys per the fix
    above) to isolate this test from the map's implicit-unauthorized-tag/IOAllocator step (that
    full end-to-end path, including auto-allocation, is exercised separately below through the
    GUI harness).
    """
    io_map = _minimal_bench_map()
    semantic_output = rule_based_parse_command("Enciende un motor con el boton Start y apagalo con el boton Stop.")
    # Q_Motor_Enable no esta autorizado todavia en este mapa minimo - se resuelve exactamente como
    # lo haria gui.py._handle_map_config_command, reutilizando el mismo IOAllocator.
    io_map["variables"].append(_variable("Q_Motor_Enable", "%QX8.0", "ASSIGNED", var_class="output"))
    io_map["variables"] = [v for v in io_map["variables"] if v["name"] != "Q_Free1"]

    semantic_output, validation, project_ir, ir_verification = _run_through_full_stack(semantic_output, io_map)

    assert validation["is_valid"] is True, validation["errors"]
    declared_names = {v.name for v in project_ir.pou.variables}
    for ghost in _GHOST_TAG_NAMES:
        assert ghost not in declared_names, f"{ghost} es un ghost tag: nunca fue solicitado"
        assert ghost not in project_ir.pou.implementation_code
        assert ghost not in _serialize_ir(project_ir)
    assert {"I_Start", "I_Stop", "Q_Motor_Enable", "M_RunLatch", "M_FaultLatch"} <= declared_names
    assert ir_verification["is_valid"] is True, ir_verification["errors"]


def test_minimal_start_stop_reaches_tia_exactly_once_via_real_gui_pipeline(
    app, tmp_path, monkeypatch, _tia_ready
) -> None:
    """
    Full end-to-end through the real GUI orchestration (process_command -> generate_package ->
    validate_latest_package_in_tia), exercising the REAL implicit-unauthorized-tag IOAllocator
    path (Q_Motor_Enable auto-resolved to a FREE channel with zero user interaction, section 3/8/
    17/18) - not a hand-authored io_map. Forces mode="rule_based" so parsing stays deterministic
    and offline; everything after parsing (repair, validation, allocation, IR, SCL, verification)
    is real and unmocked. Only the TIA bridge call is mocked.
    """
    map_path = tmp_path / "mapa_test_optional_resources.json"
    map_path.write_text(json.dumps(_minimal_bench_map(), indent=2), encoding="utf-8")
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

    def _forced_rule_based_parse(command_text, **kwargs):
        kwargs["mode"] = "rule_based"
        return _REAL_GUI_PARSE_COMMAND(command_text, **kwargs)

    monkeypatch.setattr(gui, "parse_command", _forced_rule_based_parse)

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
        app.command_textbox.insert("1.0", "Enciende un motor con el boton Start y apagalo con el boton Stop.")
        result = _run_and_settle(app)

        assert result is True
        assert len(tia_calls) == 1

        saved_map = json.loads(map_path.read_text(encoding="utf-8"))
        names = {v["name"] for v in saved_map["variables"]}
        assert "Q_Motor_Enable" in names, "el IOAllocator debio asignar Q_Motor_Enable automaticamente"
        for ghost in ("I_Reset", "Q_Alarm", "Q_Pilot_Run", "Q_Pilot_Fault"):
            assert ghost not in names, f"{ghost} nunca fue solicitado: no debio crearse en el mapa"
        # Los 24 canales del banco no se truncan: el mapa temporal empezo con 6 variables (I_Start,
        # I_Stop, I_Sensor1, Q_Free1..3 -> 6), reasignar uno existente (Q_Free1 -> Q_Motor_Enable)
        # no debe cambiar el TOTAL de canales fisicos.
        assert len(saved_map["variables"]) == 6
    finally:
        app.io_map_path = original_path
        app.io_variables = gui.load_io_map_variables(original_path)
        app._load_active_map_metadata_shadow()
        app._load_io_map_table()
        app.active_trial = None
        app.active_profile_id = None
        app.command_textbox.delete("1.0", "end")
        app.pending_semantic_output = None


# ---------- Section 36: caso Reset explicito -------------------------------------------------

def test_command_with_explicit_reset_request_resolves_and_uses_it() -> None:
    io_map = _minimal_bench_map()
    io_map["variables"].append(_variable("Q_Motor_Enable", "%QX8.0", "ASSIGNED", var_class="output"))
    io_map["variables"] = [v for v in io_map["variables"] if v["name"] != "Q_Free1"]
    # El Reset se agrega ya resuelto (como lo dejaria el IOAllocator despues de MAP_CONFIG) para
    # aislar este test del flujo de asignacion, que ya se prueba end-to-end arriba.
    io_map["variables"].append(_variable("I_Reset", "%IX16.4", "ASSIGNED"))
    io_map["variables"] = [v for v in io_map["variables"] if v["name"] != "Q_Free2"]

    semantic_output = rule_based_parse_command(
        "Enciende el motor con Start, apagalo con Stop y usa un pulsante Reset para restablecer la falla."
    )
    assert semantic_output["parameters"]["reset_input"] == "I_Reset"

    semantic_output, validation, project_ir, ir_verification = _run_through_full_stack(semantic_output, io_map)

    assert validation["is_valid"] is True, validation["errors"]
    declared_names = {v.name for v in project_ir.pou.variables}
    assert "I_Reset" in declared_names
    assert "I_Reset" in project_ir.pou.implementation_code
    assert "(* Reset manual de falla" in project_ir.pou.implementation_code
    for ghost in ("Q_Alarm", "Q_Pilot_Run", "Q_Pilot_Fault"):
        assert ghost not in declared_names
    assert ir_verification["is_valid"] is True, ir_verification["errors"]


# ---------- Section 30/31: regresion parametrizada "no ghost tags" -------------------------------

_MINIMAL_MOTOR_START_STOP_PARAMETERS = {
    "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
    "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch", "fault_latch": "M_FaultLatch"
}


@pytest.mark.parametrize("map_factory", [_minimal_bench_map, _map_with_reset_and_alarm])
def test_no_ghost_tags_for_minimal_motor_command_regardless_of_map_contents(map_factory) -> None:
    """
    Section 32's invariant, directly: whether or not the active map HAS I_Reset/Q_Alarm available
    (map_with_reset_and_alarm), a command that never asked for those features must never reference
    them - having the hardware available is not the same as the command requesting it.
    """
    io_map = map_factory()
    io_map["variables"].append(_variable("Q_Motor_Enable", "%QX8.0", "ASSIGNED", var_class="output"))
    io_map["variables"] = [v for v in io_map["variables"] if v["name"] != "Q_Free1"]

    semantic_output = {
        "intent_id": "INT_MOTOR_START_STOP", "case_id": None,
        "command_text": "comando de prueba", "normalized_command": "comando de prueba",
        "parameters": dict(_MINIMAL_MOTOR_START_STOP_PARAMETERS),
        "confidence": 0.9, "ambiguities": [], "requires_clarification": False,
        "clarification_question": None, "assumptions": [],
        "recognized_tags": ["I_Start", "I_Stop", "Q_Motor_Enable"],
        "unrecognized_terms": [], "functional_requirements": []
    }
    semantic_output, validation, project_ir, ir_verification = _run_through_full_stack(semantic_output, io_map)

    assert validation["is_valid"] is True, validation["errors"]
    declared_names = {v.name for v in project_ir.pou.variables}
    for ghost in ("I_Reset", "Q_Alarm", "Q_Pilot_Run", "Q_Pilot_Fault"):
        assert ghost not in declared_names
        assert ghost not in project_ir.pou.implementation_code
        assert ghost not in _serialize_ir(project_ir)
    assert ir_verification["is_valid"] is True, ir_verification["errors"]
