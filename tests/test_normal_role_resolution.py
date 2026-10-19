"""
MODO NORMAL — ROL FUNCIONAL != TAG FISICO.

El Modo Normal no depende de que el mapa contenga literalmente los nombres canonicos del contrato
(Q_Motor_Enable, Q_Alarm, I_Reset...): primero se resuelve el ROL (MOTOR_ENABLE -> salida digital) y el
IOAllocator decide: (1) el mismo nombre existe -> se reutiliza; (2) la funcion ya esta cubierta por otro nombre
(por nombre de rol o semantic_role) -> se VINCULA a ese simbolo; (3) DO libre -> se asigna; (4) nada -> falta de
hardware (SYSTEM_CAPABILITY_GAP), nunca FUNCTIONAL_RESOURCE_UNRESOLVED por un nombre. El simbolo resuelto se usa
igual en semantica efectiva, IR, SCL y verificacion.

Experimentacion/formal-v1.1 (sin perfil Normal) conserva sus contratos de nombres congelados.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

import llm_parser
from io_allocator import functional_role_key
from ir_builder import build_project_ir, required_external_resources
from semantic_validator import validate_semantic_output
from utils import load_json_file

from test_normal_mode_hardening import _Plc, _bench, _configs, _generate, _interpret, _llm

COMMAND = "Enciende el motor con Start y apágalo con Stop."
MOTOR = {"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable"}


def _motor_semantic(io_map: dict[str, Any], parameters: dict[str, Any] | None = None, intent: str = "INT_MOTOR_START_STOP"):
    return _interpret(COMMAND, _llm(COMMAND, [], intent=intent, parameters=parameters or MOTOR), io_map)


def _with_role(io_map: dict[str, Any], name: str, role: str) -> dict[str, Any]:
    next(v for v in io_map["variables"] if v["name"] == name)["semantic_role"] = role
    return io_map


def _behaves_as_start_stop(scl: str, output: str) -> None:
    plc = _Plc(scl)
    plc.press("I_Start")
    assert plc.on(output)
    plc.press("I_Stop")
    assert not plc.on(output)


def test_role_keys_ignore_generic_words_but_keep_actor_numbers():
    assert functional_role_key("Q_Motor_Enable") == functional_role_key("Q_Motor") == "motor"
    assert functional_role_key("Q_Motor_1") == "motor 1" != functional_role_key("Q_Motor_2")
    assert functional_role_key("I_Level_High_Tank_1") == "level high tank 1"


def test_R1_existing_canonical_name_is_reused(tmp_path):
    io_map = _bench(outputs={"Q_Motor_Enable": "%QX0.4"})
    semantic = _motor_semantic(io_map)
    assert semantic["semantic_validation"]["io_assignment_proposals"] == []
    result = _generate(semantic, io_map, tmp_path)
    _behaves_as_start_stop(result["scl"], "Q_Motor_Enable")


def test_R2_missing_canonical_name_takes_a_free_digital_output(tmp_path):
    io_map = _bench()
    semantic = _motor_semantic(io_map)
    proposals = semantic["semantic_validation"]["io_assignment_proposals"]
    assert [(p["proposed_name"], p["address"], p["current_state"]) for p in proposals] == [("Q_Motor_Enable", "%QX1.0", "FREE")]
    result = _generate(semantic, io_map, tmp_path)  # sin FUNCTIONAL_RESOURCE_UNRESOLVED
    assert {v["name"]: v["location"] for v in result["map"]["variables"]}["Q_Motor_Enable"] == "%QX1.0"
    _behaves_as_start_stop(result["scl"], "Q_Motor_Enable")


@pytest.mark.parametrize("existing, role", [("Q_Motor", ""), ("Q_Conveyor", "motor")])
def test_R3_function_already_covered_by_another_name_is_reused_without_duplicate(tmp_path, existing, role):
    io_map = _bench(outputs={existing: "%QX0.6"})
    if role:
        _with_role(io_map, existing, role)
    semantic = _motor_semantic(io_map)
    validation = semantic["semantic_validation"]
    assert semantic["resource_bindings"] == {"Q_Motor_Enable": existing}
    assert validation["io_assignment_proposals"] == [] and validation["is_valid"]  # ningun canal nuevo
    result = _generate(semantic, io_map, tmp_path)
    names = [v["name"] for v in result["map"]["variables"]]
    assert "Q_Motor_Enable" not in names and names.count(existing) == 1  # sin duplicado
    _behaves_as_start_stop(result["scl"], existing)


def test_R4_no_digital_output_is_a_capability_gap_for_the_motor_role():
    validation = _motor_semantic(_bench(free_do=0))["semantic_validation"]
    gap = validation["capability_gap"]
    assert validation["requires_clarification"] is False
    assert "Se requiere 1 DO compatible y actualmente hay 0 disponibles" in gap["message"] and "para: motor" in gap["message"]
    assert not any("FUNCTIONAL_RESOURCE_UNRESOLVED" in e for e in validation["errors"])


def test_R5_the_resolved_symbol_is_used_by_every_later_stage(tmp_path):
    io_map = _bench(outputs={"Q_Conveyor": "%QX0.6"})
    _with_role(io_map, "Q_Conveyor", "motor")
    semantic = _motor_semantic(io_map)
    effective = semantic["effective_semantics"]["interpreted_parameters"]
    assert semantic["parameters"]["motor_output"] == effective["motor_output"] == "Q_Conveyor"
    result = _generate(semantic, io_map, tmp_path)
    ir_names = {v["name"] for v in result["ir"]["pou"]["variables"]}
    assert "Q_Conveyor" in ir_names and "Q_Motor_Enable" not in ir_names
    assert "Q_Conveyor" in result["scl"] and "Q_Motor_Enable" not in result["scl"]
    assert result["package"]["verification"]["is_valid"] is True


def test_contract_default_never_named_by_the_interpreter_is_still_resolved(tmp_path):
    """La IR completa un recurso con el default del contrato (motor_output -> Q_Motor_Enable). Antes el validador no lo
    veia: aprobaba y la IR fallaba con FUNCTIONAL_RESOURCE_UNRESOLVED (el error reportado)."""
    without_output = {"trigger_input": "I_Start", "emergency_input": "FALSE", "operation_time": "T#10s"}
    catalog, safety = _configs()
    raw = _llm("x", [], intent="INT_AUTO_STOP_TIMER", parameters=without_output)
    assert "Q_Motor_Enable" in required_external_resources(raw, _bench())  # la IR lo exigira
    frozen = validate_semantic_output(raw, _bench(), catalog, safety)  # sin perfil Normal: comportamiento congelado
    assert frozen["is_valid"] and frozen["io_assignment_proposals"] == []
    with pytest.raises(ValueError, match="FUNCTIONAL_RESOURCE_UNRESOLVED: .*Q_Motor_Enable"):
        build_project_ir(raw, _bench(), "SIEMENS_SCL_V18")

    # Modo Normal, DO libre: se asigna.
    free = _interpret("x", raw, _bench())
    assert ("Q_Motor_Enable", "%QX1.0") in {(p["proposed_name"], p["address"]) for p in free["semantic_validation"]["io_assignment_proposals"]}
    _generate(free, _bench(), tmp_path / "free")
    # Modo Normal, el motor ya existe con otro nombre: el default se materializa como parametro y se vincula.
    covered_map = _bench(outputs={"Q_Motor": "%QX0.5"})
    covered = _interpret("x", raw, covered_map)
    assert covered["parameters"]["motor_output"] == "Q_Motor" and covered["resource_bindings"] == {"Q_Motor_Enable": "Q_Motor"}
    assert "Q_Motor_Enable" not in _generate(covered, covered_map, tmp_path / "covered")["scl"]


def test_rule_based_or_fallback_results_also_get_normal_resource_resolution():
    """Con el LLM caido (fallback por reglas) o en modo reglas, el resultado tambien es Modo Normal."""
    catalog, safety = _configs()
    io_map = _bench(outputs={"Q_Motor": "%QX0.5"})
    result = llm_parser.parse_command(COMMAND, mode="rule_based", io_map=io_map, intents_catalog=catalog, safety_rules=safety,
                                      interaction_profile="normal")
    assert result["interaction_profile"] == "normal"
    assert result["parameters"]["motor_output"] == "Q_Motor" and result["semantic_validation"]["is_valid"]


def test_fixed_catalog_tags_are_allocated_by_name_never_silently_rebound(tmp_path):
    """run_pilot exige el tag FIJO Q_Pilot_Run: no puede re-vincularse a otro nombre (la IR seguiria exigiendolo)."""
    io_map = _bench(outputs={"Q_Pilot": "%QX0.7"})
    semantic = _interpret("x", _llm("x", [{"type": "run_pilot"}], intent="INT_MOTOR_START_STOP", parameters=MOTOR), io_map)
    assert "Q_Pilot_Run" not in (semantic.get("resource_bindings") or {})
    assert "Q_Pilot_Run" in {p["proposed_name"] for p in semantic["semantic_validation"]["io_assignment_proposals"]}
    _generate(semantic, io_map, tmp_path)


def test_ambiguous_role_match_is_never_guessed():
    io_map = _bench(outputs={"Q_Motor": "%QX0.5", "Q_Conveyor": "%QX0.6"})
    _with_role(io_map, "Q_Conveyor", "motor")  # dos salidas cubren "motor": no se elige ninguna por intuicion
    semantic = _motor_semantic(io_map)
    assert not semantic.get("resource_bindings")
    assert [p["current_state"] for p in semantic["semantic_validation"]["io_assignment_proposals"]] == ["FREE"]


def test_numbered_actors_are_never_collapsed_onto_one_output(tmp_path):
    io_map = _bench(outputs={"Q_Motor": "%QX0.5"})
    requirements = [{"type": "motor_start_latch", "target": "Q_Motor_1", "trigger_input": "I_Start_Motor_1"},
                    {"type": "motor_start_latch", "target": "Q_Motor_2", "trigger_input": "I_Start_Motor_2"}]
    semantic = _interpret("x", _llm("x", requirements, intent="INT_UNKNOWN", parameters={"stop_input": "I_Stop"}), io_map)
    assert not semantic.get("resource_bindings")
    assigned = {p["proposed_name"]: p["address"] for p in semantic["semantic_validation"]["io_assignment_proposals"]}
    assert assigned["Q_Motor_1"] != assigned["Q_Motor_2"] and "%QX0.5" not in assigned.values()


def test_formal_profile_keeps_frozen_name_contracts():
    """Sin perfil Normal (Experimentacion/formal): ni reutilizacion por rol ni re-vinculacion de nombres."""
    catalog, safety = _configs()
    io_map = _bench(outputs={"Q_Motor": "%QX0.5"})
    semantic = llm_parser._normalize_semantic_output(_llm(COMMAND, [], intent="INT_MOTOR_START_STOP", parameters=MOTOR), COMMAND)
    validation = validate_semantic_output(semantic, io_map, catalog, safety)
    assert "resource_bindings" not in validation
    assert [p["proposed_name"] for p in validation["io_assignment_proposals"]] == ["Q_Motor_Enable"]
