"""
Recursos de requisito funcional DEPENDIENTES DE PARAMETROS (FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS).

Bug real (P06_V1_TEXT_DEV_001): "El requisito funcional 'enable_pid' no se propago a la IR: falta la variable
I_Emergency". P06 no pide emergencia (benchmark y Oracle FROZEN); el generador compone un interlock incidental
PID_Enable := NOT <emergency_input> AND ..., y la semantica efectiva dejo emergency_input = FALSE (SAFE_LITERAL,
banco sin I_Emergency). IR y SCL usaban el literal; solo el verificador exigia el tag fijo del contrato.

Ahora requisito, IR, generador y verificador resuelven el recurso con los MISMOS parametros efectivos: literal
seguro -> sin variable PLC; tag valido -> ese tag; parametro ausente -> el contrato; valor invalido -> error
estructurado. Requisitos cuya esencia es la emergencia (emergency_priority) y el rol SAFETY_TRIP de P07 no cambian.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from code_generator import generate_implementation_from_ir
from functional_requirements import (
    ERROR_INVALID_PARAMETER_RESOURCE,
    FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS,
    FUNCTIONAL_REQUIREMENT_TAGS,
    RESOURCE_CONTRACT_DEFAULT,
    RESOURCE_SAFE_LITERAL,
    RESOURCE_TAG,
    ParameterResourceError,
    get_functional_requirement_tags,
    resolve_parameter_resources,
)
from ir_builder import build_project_ir
from trial_experiments import oracle_runner, oracle_schema
from utils import get_project_root
from verifier import verify_project_ir

_ROOT = get_project_root()
_BASE_MAP = json.loads((_ROOT / "data" / "plc_maps" / "mapa_banco_fisico_base.json").read_text(encoding="utf-8"))
_ENABLE_PID = {"type": "enable_pid"}
_REPAIR_SAFE_LITERAL = {"source": "REPAIR", "original_value": None, "category": "SAFE_LITERAL",
                        "reason": "valor fijado por semantic_repair (normalizacion de forma o banco sin emergencia)"}


def _bench_with(*extra: dict[str, Any]) -> dict[str, Any]:
    io_map = copy.deepcopy(_BASE_MAP)
    io_map["variables"].extend(extra)
    return io_map


def _p06_semantic(emergency: str | None = "FALSE", requirements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """semantic_output equivalente al congelado de P06_V1_TEXT_DEV_001 (LLM: set_auto_mode + enable_pid)."""
    parameters = {"reset_input": "I_Reset", "alarm_output": "Q_Alarm", "pump_output": "Q_Pump_Enable"}
    provenance: dict[str, Any] = {}
    if emergency is not None:
        parameters["emergency_input"] = emergency
        if emergency == "FALSE":
            provenance["emergency_input"] = dict(_REPAIR_SAFE_LITERAL)
    return {"intent_id": "INT_PID_SUPERVISOR", "case_id": "P06",
            "command_text": "Habilita el PID unicamente cuando el sistema este en modo Automatico.",
            "parameters": parameters, "parameter_provenance": provenance,
            "functional_requirements": requirements if requirements is not None else [{"type": "set_auto_mode"}, {"type": "enable_pid"}],
            "recognized_tags": [], "requires_clarification": False}


def _build(semantic_output: dict[str, Any], io_map: dict[str, Any]):
    project_ir = build_project_ir(semantic_output, io_map, "SIEMENS_SCL_V18")
    project_ir.pou.implementation_code = generate_implementation_from_ir(project_ir)
    return project_ir


# A. enable_pid + emergency_input FALSE -> no exige I_Emergency
def test_a_safe_literal_requires_no_plc_variable():
    assert get_functional_requirement_tags(_ENABLE_PID, {"emergency_input": "FALSE"}) == []
    [resource] = resolve_parameter_resources(_ENABLE_PID, {"emergency_input": "false"})
    assert (resource["resolution"], resource["value"], resource["tag"]) == (RESOURCE_SAFE_LITERAL, "FALSE", None)


# B. enable_pid + emergency_input I_Emergency -> obligatorio
def test_b_real_emergency_tag_stays_mandatory():
    assert get_functional_requirement_tags(_ENABLE_PID, {"emergency_input": "I_Emergency"}) == ["I_Emergency"]
    io_map = _bench_with({"name": "I_Emergency", "class": "input", "type": "BOOL", "location": "%IX16.7"})
    io_map["variables"] = [v for v in io_map["variables"] if v["location"] != "%IX16.7" or v["name"] == "I_Emergency"]
    project_ir = _build(_p06_semantic("I_Emergency"), io_map)
    assert "I_Emergency" in [v.name for v in project_ir.pou.variables] and "I_Emergency" in project_ir.pou.implementation_code
    assert verify_project_ir(project_ir)["is_valid"] is True
    project_ir.pou.variables = [v for v in project_ir.pou.variables if v.name != "I_Emergency"]
    errors = verify_project_ir(project_ir)["errors"]
    assert "El requisito funcional 'enable_pid' no se propago a la IR: falta la variable I_Emergency." in errors


# C. enable_pid + otro tag valido -> ese tag, nunca el I_Emergency fijo
def test_c_other_valid_tag_replaces_the_contract_default():
    assert get_functional_requirement_tags(_ENABLE_PID, {"emergency_input": "I_Safety_Stop"}) == ["I_Safety_Stop"]
    io_map = _bench_with()
    io_map["variables"] = [dict(v, name="I_Safety_Stop") if v["location"] == "%IX16.7" else v for v in io_map["variables"]]
    project_ir = _build(_p06_semantic("I_Safety_Stop"), io_map)
    names = [v.name for v in project_ir.pou.variables]
    assert "I_Safety_Stop" in names and "I_Emergency" not in names
    assert "NOT I_Safety_Stop AND Auto_Mode" in project_ir.pou.implementation_code
    assert verify_project_ir(project_ir)["is_valid"] is True


def test_c_missing_parameter_uses_only_the_contract_and_invalid_value_is_structured():
    assert get_functional_requirement_tags(_ENABLE_PID) == ["I_Emergency"]  # sin parametros: contrato
    [resource] = resolve_parameter_resources(_ENABLE_PID, {})
    assert (resource["resolution"], resource["tag"]) == (RESOURCE_CONTRACT_DEFAULT, "I_Emergency")
    with pytest.raises(ParameterResourceError) as raised:
        get_functional_requirement_tags(_ENABLE_PID, {"emergency_input": "emergencia del tablero"})
    assert raised.value.code == ERROR_INVALID_PARAMETER_RESOURCE and raised.value.parameter == "emergency_input"


# D. SAFE_LITERAL con procedencia -> valido y registrado (nunca se convierte en tag)
def test_d_safe_literal_provenance_is_recorded_in_the_ir():
    project_ir = _build(_p06_semantic("FALSE"), _bench_with())
    [resource] = project_ir.metadata["functional_requirement_parameter_resources"]
    assert resource["type"] == "enable_pid" and resource["resolution"] == RESOURCE_SAFE_LITERAL
    assert resource["provenance"]["category"] == "SAFE_LITERAL" and resource["provenance"]["source"] == "REPAIR"
    assert "FALSE" not in [v.name for v in project_ir.pou.variables]


# E. emergency_priority -> sin cambios (tag fijo, su esencia es la emergencia)
def test_e_emergency_priority_is_unchanged():
    assert "emergency_priority" not in FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS
    assert FUNCTIONAL_REQUIREMENT_TAGS["emergency_priority"] == ["I_Emergency"]
    assert get_functional_requirement_tags({"type": "emergency_priority"}, {"emergency_input": "FALSE"}) == ["I_Emergency"]
    assert FUNCTIONAL_REQUIREMENT_TAGS["enable_pid"] == ["I_Emergency"]  # el contrato declarado tampoco cambia


# F. P07: SAFETY_TRIP ausente -> sigue REVIEW (el FALSE de enable_pid no elimina su necesidad)
def test_f_p07_still_needs_safety_trip():
    oracle = oracle_schema.load_oracle(_ROOT, "P07")
    assert oracle["roles"]["SAFETY_TRIP"]["semantic_paths"] == ["safety_trip", "safety_trip_input", "emergency_input"]
    pv = {"bindings": {name: {"name": name, "db": "DB_PLC_PRG", "member": name, "data_type": "BOOL"} for name in ("Auto_Mode", "PID_Enable")}}
    missing = oracle_runner.resolve_roles(oracle, {"channels": [], "parameter_bindings": {}}, pv)
    assert missing["status"] == "REVIEW"
    assert [(i["role"], i["code"]) for i in missing["issues"]] == [("SAFETY_TRIP", oracle_runner.ROLE_NOT_FOUND)]
    # Con un binding fisico real de disparo, el mismo rol si se resuelve (el mecanismo no se relajo).
    snapshot = {"channels": [{"functional_name": "I_Safety_Trip", "signal": "DI", "address": "%IX16.7"}],
                "parameter_bindings": {"safety_trip": {"functional_name": "I_Safety_Trip", "address": "%IX16.7"}}}
    assert oracle_runner.resolve_roles(oracle, snapshot, pv)["status"] == "RESOLVED"


# G. P06 llega a IR/SCL sin I_Emergency y la verificacion pasa
def test_g_p06_reaches_ir_and_scl_without_i_emergency():
    project_ir = _build(_p06_semantic("FALSE"), _bench_with())
    assert project_ir.metadata["functional_requirement_tags"] == []
    assert "I_Emergency" not in [v.name for v in project_ir.pou.variables]
    assert "I_Emergency" not in project_ir.pou.implementation_code
    assert "PID_Enable := NOT FALSE AND Auto_Mode AND NOT Sensor_Fault AND NOT Safe_Stop;" in project_ir.pou.implementation_code
    assert verify_project_ir(project_ir) == {"is_valid": True, "errors": [], "warnings": []}


# H. P06 conserva set_auto_mode tal como lo produjo el LLM (no se corrige aqui)
def test_h_p06_keeps_set_auto_mode_from_the_llm():
    project_ir = _build(_p06_semantic("FALSE"), _bench_with())
    assert [r["type"] for r in project_ir.metadata["functional_requirements"]] == ["set_auto_mode", "enable_pid"]
    assert "IF NOT FALSE THEN\n    Auto_Mode := TRUE;" in project_ir.pou.implementation_code


# I. Requisito, IR, generador y verificador usan la misma resolucion
@pytest.mark.parametrize("emergency,expected_tag,in_code", [("FALSE", None, "NOT FALSE AND"), ("I_Safety_Stop", "I_Safety_Stop", "NOT I_Safety_Stop AND")])
def test_i_one_resolution_for_requirement_ir_generator_and_verifier(emergency, expected_tag, in_code):
    io_map = _bench_with()
    if expected_tag:
        io_map["variables"] = [dict(v, name=expected_tag) if v["location"] == "%IX16.7" else v for v in io_map["variables"]]
    project_ir = _build(_p06_semantic(emergency), io_map)
    [resource] = project_ir.metadata["functional_requirement_parameter_resources"]
    assert resource["tag"] == expected_tag
    assert project_ir.metadata["functional_requirement_tags"] == ([expected_tag] if expected_tag else [])
    assert in_code in project_ir.pou.implementation_code
    assert verify_project_ir(project_ir)["is_valid"] is True


# J. Sin ghost tags: un literal seguro nunca reaparece como tag en la logica generada
def test_j_no_ghost_tag_when_the_parameter_is_a_safe_literal():
    project_ir = _build(_p06_semantic("FALSE"), _bench_with())
    project_ir.pou.implementation_code += "\nPID_Enable := PID_Enable AND NOT I_Emergency;\n"
    errors = verify_project_ir(project_ir)["errors"]
    assert any("usa I_Emergency aunque la semantica efectiva fijo emergency_input = FALSE" in e for e in errors)


def test_j_resolved_tag_must_be_used_by_the_generated_logic():
    io_map = _bench_with()
    io_map["variables"] = [dict(v, name="I_Safety_Stop") if v["location"] == "%IX16.7" else v for v in io_map["variables"]]
    project_ir = _build(_p06_semantic("I_Safety_Stop"), io_map)
    project_ir.pou.implementation_code = project_ir.pou.implementation_code.replace("I_Safety_Stop", "FALSE")
    assert any("resolvio emergency_input = I_Safety_Stop" in e for e in verify_project_ir(project_ir)["errors"])
