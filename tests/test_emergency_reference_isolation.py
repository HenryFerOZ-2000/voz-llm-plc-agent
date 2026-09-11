"""
Regression tests for a real bug found after the previous fix: `strip_unavailable_emergency_reference`
removed I_Emergency from `parameters`/`recognized_tags`, but `ir_builder.py::get_required_variables_for_intent`
independently defaults EVERY intent's `emergency_input` to the literal string "I_Emergency" via
`parameters.get("emergency_input", "I_Emergency")` - deleting the key just re-triggered that same
default, so "I_Emergency" reappeared in `required_variables` and generation failed with "Recurso
externo no autorizado/no existente en el mapa PLC: I_Emergency" even on a bench with no such tag.

Root cause traced to THREE independent sources that all needed to agree:
1. semantic_validator.py's two-level validation (recognized_tags) - already fixed previously.
2. ir_builder.py::get_required_variables_for_intent's ~20 `parameters.get("emergency_input",
   "I_Emergency")` defaults, used directly in code_generator.py's SCL templates - the string
   "I_Emergency" is now replaced with the IEC boolean literal "FALSE" (a key PRESENT with value
   "FALSE" beats the default; "FALSE" doesn't match any external/internal tag prefix, so it is
   silently excluded from both required-variable checks and stays a semantically correct no-op in
   every boolean SCL expression it appears in: "AND NOT FALSE", "IF FALSE THEN", "X OR FALSE").
3. `functional_requirements` entries of type "emergency_priority" - resolve to the FIXED tag list
   ["I_Emergency"] with no parameter to substitute into, so the entry itself is dropped instead
   (unless the command's own intent_id is INT_EMERGENCY_PRIORITY - genuinely asking for emergency
   logic on a bench with none wired is a real error to surface, not silently discard).

`ir_builder.py::build_project_ir` also gained an unconditional defense-in-depth filter dropping
"I_Emergency" from required_variables whenever it is not in the active map's io_index, regardless
of which of the above paths a given semantic_output came through.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import llm_parser
from ir_builder import build_project_ir
from project_packager import generate_project_package
from verifier import verify_project_ir


def _variable(name: str, location: str, state: str, var_class: str = "input") -> dict[str, Any]:
    return {
        "name": name, "class": var_class, "type": "BOOL", "location": location,
        "initial_value": "FALSE", "description": "", "state": state, "llm_allowed": True
    }


def _map_without_emergency() -> dict[str, Any]:
    return {
        "variables": [
            _variable("I_Start", "%IX16.0", "LOCKED"),
            _variable("I_Stop", "%IX16.1", "LOCKED"),
            _variable("Q_Motor_1", "%QX8.0", "ASSIGNED", var_class="output"),
            _variable("Q_Motor_2", "%QX8.1", "ASSIGNED", var_class="output"),
        ]
    }


def _map_with_emergency() -> dict[str, Any]:
    variables = _map_without_emergency()["variables"] + [_variable("I_Emergency", "%IX16.7", "LOCKED")]
    return {"variables": variables}


_INTENTS_CATALOG = {
    "INT_MUTUAL_INTERLOCK": {
        "description": "x",
        "required_inputs": ["I_Start", "I_Stop", "I_Emergency"],
        "required_outputs": ["Q_Contactor_A", "Q_Contactor_B"],
        "required_internal": []
    }
}


def _llm_response(with_functional_requirement: bool = True) -> dict[str, Any]:
    return {
        "intent_id": "INT_MUTUAL_INTERLOCK",
        "case_id": None,
        "command_text": (
            "Enciende dos motores con sus pulsantes, solo uno a la vez y Stop apaga todo."
        ),
        "normalized_command": "dos motores",
        "parameters": {
            "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
            "contactor_a": "Q_Motor_1", "contactor_b": "Q_Motor_2"
        },
        "confidence": 0.95,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_1", "Q_Motor_2"],
        "unrecognized_terms": [],
        "functional_requirements": [{"type": "emergency_priority"}] if with_functional_requirement else []
    }


# ---------- Caso de prueba exacto (seccion 8): mapa sin I_Emergency ----------

def test_1_semantic_output_final_has_no_i_emergency():
    io_map = _map_without_emergency()
    result = llm_parser.parse_command(
        "comando", mode="llm", io_map=io_map, intents_catalog=_INTENTS_CATALOG, safety_rules={},
        llm_response_text=_llm_response()
    )
    assert "I_Emergency" not in result["recognized_tags"]
    assert "I_Emergency" not in result["parameters"].values()
    assert not any(req.get("type") == "emergency_priority" for req in result["functional_requirements"])
    assert result["semantic_validation"]["is_valid"] is True
    assert result["semantic_validation"]["errors"] == []


def test_2_required_variables_has_no_i_emergency():
    io_map = _map_without_emergency()
    result = llm_parser.parse_command(
        "comando", mode="llm", io_map=io_map, intents_catalog=_INTENTS_CATALOG, safety_rules={},
        llm_response_text=_llm_response()
    )
    project_ir = build_project_ir(result, io_map, "SIEMENS_SCL_V18")
    assert "I_Emergency" not in project_ir.metadata["required_variables"]


def test_3_ir_variables_has_no_i_emergency():
    io_map = _map_without_emergency()
    result = llm_parser.parse_command(
        "comando", mode="llm", io_map=io_map, intents_catalog=_INTENTS_CATALOG, safety_rules={},
        llm_response_text=_llm_response()
    )
    project_ir = build_project_ir(result, io_map, "SIEMENS_SCL_V18")
    ir_variable_names = {v.name for v in project_ir.pou.variables}
    assert "I_Emergency" not in ir_variable_names


def test_4_generated_scl_has_no_i_emergency_reference(tmp_path: Path):
    io_map = _map_without_emergency()
    result = llm_parser.parse_command(
        "comando", mode="llm", io_map=io_map, intents_catalog=_INTENTS_CATALOG, safety_rules={},
        llm_response_text=_llm_response()
    )
    package_result = generate_project_package(
        result, "SIEMENS_SCL_V18", io_map, _INTENTS_CATALOG, {}, output_dir=tmp_path
    )
    scl_text = (Path(package_result["package_dir"]) / "siemens_source.scl").read_text(encoding="utf-8")
    assert "I_Emergency" not in scl_text
    # el enclavamiento sigue siendo SCL valido - la rama de emergencia queda como "IF FALSE THEN"
    # (nunca se dispara), no se elimina la estructura del template.
    assert "IF FALSE THEN" in scl_text


def test_5_verifier_does_not_fail_for_emergency(tmp_path: Path):
    io_map = _map_without_emergency()
    result = llm_parser.parse_command(
        "comando", mode="llm", io_map=io_map, intents_catalog=_INTENTS_CATALOG, safety_rules={},
        llm_response_text=_llm_response()
    )
    project_ir = build_project_ir(result, io_map, "SIEMENS_SCL_V18")
    verification = verify_project_ir(project_ir)
    assert verification["is_valid"] is True
    assert not any("I_Emergency" in error for error in verification["errors"])


def test_generation_succeeds_end_to_end_without_i_emergency(tmp_path: Path):
    """Criterio de exito (seccion 11): semantic -> allocator -> IR -> SCL -> verifier sin ninguna
    referencia a I_Emergency, y sin lanzar la excepcion original del bug reportado."""
    io_map = _map_without_emergency()
    result = llm_parser.parse_command(
        "comando", mode="llm", io_map=io_map, intents_catalog=_INTENTS_CATALOG, safety_rules={},
        llm_response_text=_llm_response()
    )
    package_result = generate_project_package(
        result, "SIEMENS_SCL_V18", io_map, _INTENTS_CATALOG, {}, output_dir=tmp_path
    )
    assert package_result["verification"]["is_valid"] is True


# ---------- Caso positivo (seccion 9): mapa CON I_Emergency ----------

def test_6_map_with_i_emergency_can_still_use_it(tmp_path: Path):
    io_map = _map_with_emergency()
    result = llm_parser.parse_command(
        "comando", mode="llm", io_map=io_map, intents_catalog=_INTENTS_CATALOG, safety_rules={},
        llm_response_text=_llm_response()
    )
    assert result["parameters"]["emergency_input"] == "I_Emergency"
    assert any(req.get("type") == "emergency_priority" for req in result["functional_requirements"])

    package_result = generate_project_package(
        result, "SIEMENS_SCL_V18", io_map, _INTENTS_CATALOG, {}, output_dir=tmp_path
    )
    assert package_result["verification"]["is_valid"] is True
    scl_text = (Path(package_result["package_dir"]) / "siemens_source.scl").read_text(encoding="utf-8")
    assert "I_Emergency" in scl_text
    assert "IF FALSE THEN" not in scl_text


# ---------- ir_builder-level defense in depth (independiente del repair layer) ----------

def test_build_project_ir_drops_i_emergency_from_required_variables_even_if_still_referenced():
    """
    Seccion 5/7 del pedido: get_required_variables_for_intent en si mismo sigue devolviendo
    "I_Emergency" por su default hardcodeado si `parameters["emergency_input"]` esta AUSENTE (no
    reparado) - build_project_ir debe filtrarlo igual, como red de seguridad independiente del
    repair layer, para cualquier semantic_output que no haya pasado por parse_command.
    """
    io_map = _map_without_emergency()
    semantic_output = {
        "intent_id": "INT_MUTUAL_INTERLOCK",
        "case_id": None,
        "command_text": "x",
        "parameters": {
            "trigger_input": "I_Start", "stop_input": "I_Stop",
            "contactor_a": "Q_Motor_1", "contactor_b": "Q_Motor_2"
        },
        "recognized_tags": ["I_Start", "I_Stop", "Q_Motor_1", "Q_Motor_2"],
        "functional_requirements": []
    }
    # sin pasar por semantic_repair: emergency_input directamente ausente, el default interno de
    # get_required_variables_for_intent volveria a proponer "I_Emergency".
    project_ir = build_project_ir(semantic_output, io_map, "SIEMENS_SCL_V18")
    assert "I_Emergency" not in project_ir.metadata["required_variables"]
