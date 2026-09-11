"""
Regression tests for a real bug found in production, reproduced with the exact reported command:

  "Enciende un motor con el pulsante de start, y que este se apague 3 segundos despues de
  presionar el pulsante de stop"  (-> INT_DELAYED_STOP, real bench map, no I_Emergency)

Root cause (traced precisely, not patched blindly - see the diagnosis given to the user before
implementing): `semantic_repair.strip_unavailable_emergency_reference` only substituted "FALSE"
for parameter VALUES literally equal to "I_Emergency" - it never handled the case where the LLM
correctly followed the prompt instruction and OMITTED `emergency_input` from `parameters`
entirely. An ABSENT key triggers the EXACT SAME hardcoded fallback
(`parameters.get("emergency_input", "I_Emergency")`) in `ir_builder.py::get_required_variables_for_intent`
(all ~19 entries in its `parameter_overrides` dict use this key/default pair) and in every one of
`code_generator.py`'s per-intent codegen templates - reintroducing "I_Emergency" into
PLCProjectIR.pou.variables/implementation_code even though the semantic layer had already "solved"
the problem. Fixed by also filling `parameters["emergency_input"] = "FALSE"` whenever the key is
missing, not only when it holds the literal value "I_Emergency".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import llm_parser
from code_generator import generate_implementation_from_ir
from ir_builder import build_project_ir
from project_packager import generate_project_package
from semantic_repair import repair_semantic_output, strip_unavailable_emergency_reference
from semantic_validator import INTENT_PARAMETER_RULES, validate_semantic_output
from verifier import verify_project_ir


def _variable(name: str, location: str, state: str, var_class: str = "input", var_type: str = "BOOL") -> dict[str, Any]:
    return {
        "name": name, "class": var_class, "type": var_type, "location": location,
        "initial_value": "FALSE", "description": "", "state": state, "llm_allowed": True
    }


def _map_without_emergency() -> dict[str, Any]:
    return {
        "variables": [
            _variable("I_Start", "%IX0.0", "LOCKED"),
            _variable("I_Stop", "%IX0.1", "LOCKED"),
            _variable("I_Reset", "%IX0.2", "ASSIGNED"),
            _variable("Q_Motor_Enable", "%QX0.0", "ASSIGNED", var_class="output"),
            _variable("Q_Alarm", "%QX0.1", "ASSIGNED", var_class="output"),
            _variable("Q_Pilot_Run", "%QX0.2", "ASSIGNED", var_class="output"),
            _variable("Q_Pilot_Fault", "%QX0.3", "ASSIGNED", var_class="output"),
            _variable("Q_Aux_Output", "%QX0.4", "ASSIGNED", var_class="output"),
            _variable("Q_Contactor_A", "%QX0.5", "ASSIGNED", var_class="output"),
            _variable("Q_Contactor_B", "%QX0.6", "ASSIGNED", var_class="output"),
            _variable("I_Sensor1", "%IX0.3", "ASSIGNED"),
        ]
    }


def _map_with_emergency() -> dict[str, Any]:
    variables = _map_without_emergency()["variables"] + [_variable("I_Emergency", "%IX0.7", "LOCKED")]
    return {"variables": variables}


def _base_output(intent_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent_id": intent_id,
        "case_id": None,
        "command_text": "comando de prueba",
        "normalized_command": "comando de prueba",
        "parameters": parameters,
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": [],
        "unrecognized_terms": [],
        "functional_requirements": []
    }


def _serialize_ir(project_ir) -> str:
    """
    Serializa todo EXCEPTO `safety_rules` - ese campo es el texto de politica general del proyecto
    (config/safety_rules.json, "I_Emergency tiene prioridad absoluta sobre salidas criticas..."),
    identico para cualquier comando/mapa y sin relacion con que tags referencia ESTE programa en
    particular; incluirlo generaria falsos positivos. `pou` (variables + implementation_code),
    `task`, `test_cases` y `metadata` (incluye required_variables/authorized_variables/
    functional_requirements/semantic_output) son las partes que realmente importan para esta
    regresion (seccion 10 del pedido: expressions/operations/metadata/requirements).
    """
    payload = project_ir.to_dict()
    payload.pop("safety_rules", None)
    return json.dumps(payload, default=str)


def _run_through_repair_and_build(intent_id: str, parameters: dict[str, Any], io_map: dict[str, Any]):
    semantic_output = _base_output(intent_id, parameters)
    semantic_output = strip_unavailable_emergency_reference(semantic_output, io_map)
    semantic_output = repair_semantic_output(semantic_output, INTENT_PARAMETER_RULES)
    validation = validate_semantic_output(semantic_output, io_map, {intent_id: {}}, {})
    project_ir = build_project_ir(semantic_output, io_map, "SIEMENS_SCL_V18")
    project_ir.pou.implementation_code = generate_implementation_from_ir(project_ir)
    ir_verification = verify_project_ir(project_ir)
    return semantic_output, validation, project_ir, ir_verification


# ---------- Section 8: regresion exacta del comando real (INT_DELAYED_STOP) ----------

def test_delayed_stop_real_command_no_i_emergency_anywhere(tmp_path: Path):
    io_map = _map_without_emergency()
    parameters = {
        "trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable",
        "run_latch": "M_RunLatch", "stop_delay_active": "M_StopDelayActive",
        "stop_delay_time": "T#3s", "timer": "T_StopDelay"
        # emergency_input DELIBERADAMENTE ausente - shape real que devolvio el LLM.
    }
    semantic_output, validation, project_ir, ir_verification = _run_through_repair_and_build(
        "INT_DELAYED_STOP", parameters, io_map
    )

    assert semantic_output["parameters"]["emergency_input"] == "FALSE"
    assert validation["is_valid"] is True

    declared_names = {v.name for v in project_ir.pou.variables}
    expected = {"I_Start", "I_Stop", "Q_Motor_Enable", "M_RunLatch", "M_StopDelayActive", "T_StopDelay"}
    assert expected <= declared_names
    assert "I_Emergency" not in declared_names
    assert "I_Emergency" not in project_ir.pou.implementation_code
    assert "I_Emergency" not in _serialize_ir(project_ir)

    assert ir_verification["is_valid"] is True, ir_verification["errors"]

    package_result = generate_project_package(
        semantic_output, "SIEMENS_SCL_V18", io_map, {"INT_DELAYED_STOP": {}}, {}, output_dir=tmp_path
    )
    assert package_result["verification"]["is_valid"] is True


def test_delayed_stop_with_i_emergency_in_map_still_uses_it(tmp_path: Path):
    """Caso positivo (seccion 7): no se elimino el soporte de emergencia, solo se condiciono."""
    io_map = _map_with_emergency()
    parameters = {
        "trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable",
        "run_latch": "M_RunLatch", "stop_delay_active": "M_StopDelayActive",
        "stop_delay_time": "T#3s", "timer": "T_StopDelay"
    }
    semantic_output, validation, project_ir, ir_verification = _run_through_repair_and_build(
        "INT_DELAYED_STOP", parameters, io_map
    )
    assert semantic_output["parameters"].get("emergency_input") in (None, "I_Emergency")
    declared_names = {v.name for v in project_ir.pou.variables}
    assert "I_Emergency" in declared_names
    assert "I_Emergency" in project_ir.pou.implementation_code
    assert ir_verification["is_valid"] is True, ir_verification["errors"]


# ---------- Section 9/10: revisar otros intents que historicamente usaban emergencia ----------

_REPRESENTATIVE_INTENTS = [
    ("INT_MOTOR_START_STOP", {
        "trigger_input": "I_Start", "stop_input": "I_Stop", "reset_input": "I_Reset",
        "motor_output": "Q_Motor_Enable", "alarm_output": "Q_Alarm", "run_indicator": "Q_Pilot_Run",
        "fault_indicator": "Q_Pilot_Fault", "run_latch": "M_RunLatch", "fault_latch": "M_FaultLatch"
    }),
    ("INT_MOTOR_LATCH", {
        "trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable",
        "run_latch": "M_RunLatch"
    }),
    ("INT_DELAYED_START", {
        "trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable",
        "timer": "T_DelayStart", "delay_time": "T#3s"
    }),
    ("INT_DELAYED_STOP", {
        "trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable",
        "run_latch": "M_RunLatch", "stop_delay_active": "M_StopDelayActive",
        "stop_delay_time": "T#3s", "timer": "T_StopDelay"
    }),
    ("INT_MUTUAL_INTERLOCK", {
        "trigger_input": "I_Start", "stop_input": "I_Stop",
        "contactor_a": "Q_Contactor_A", "contactor_b": "Q_Contactor_B"
    }),
    ("INT_TIMED_PULSE", {
        "trigger_input": "I_Start", "output": "Q_Aux_Output", "duration": "T#5s", "timer": "T_Pulse5s"
    }),
    ("INT_DIRECT_OUTPUT", {
        "trigger_input": "I_Start", "output": "Q_Aux_Output"
    }),
    ("INT_AUTO_STOP_TIMER", {
        "trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable",
        "run_latch": "M_RunLatch", "timer": "T_OperationLimit", "operation_time": "T#10s"
    }),
]


@pytest.mark.parametrize("intent_id,parameters", _REPRESENTATIVE_INTENTS)
def test_intent_without_i_emergency_in_map_never_references_it(intent_id: str, parameters: dict[str, Any]) -> None:
    io_map = _map_without_emergency()
    semantic_output, validation, project_ir, ir_verification = _run_through_repair_and_build(
        intent_id, dict(parameters), io_map
    )
    assert semantic_output["parameters"]["emergency_input"] == "FALSE"
    declared_names = {v.name for v in project_ir.pou.variables}
    assert "I_Emergency" not in declared_names
    assert "I_Emergency" not in project_ir.pou.implementation_code
    assert "I_Emergency" not in _serialize_ir(project_ir)
    assert ir_verification["is_valid"] is True, (intent_id, ir_verification["errors"])


@pytest.mark.parametrize("intent_id,parameters", _REPRESENTATIVE_INTENTS)
def test_intent_with_i_emergency_in_map_can_still_use_it(intent_id: str, parameters: dict[str, Any]) -> None:
    io_map = _map_with_emergency()
    semantic_output, validation, project_ir, ir_verification = _run_through_repair_and_build(
        intent_id, dict(parameters), io_map
    )
    declared_names = {v.name for v in project_ir.pou.variables}
    assert "I_Emergency" in declared_names
    assert ir_verification["is_valid"] is True, (intent_id, ir_verification["errors"])
