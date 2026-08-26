from __future__ import annotations

from pathlib import Path

import pytest

from openplc_validator import discover_openplc_compiler
from project_packager import generate_project_package
from semantic_parser import parse_command
from semantic_validator import validate_semantic_output


COMMAND = (
    "Enciende un motor con el pulsante de encendido, que haga en bucle "
    "3 segundos encendido, 3 segundos apagado, y que solo se apague "
    "con el pulsante de paro"
)


def test_cyclic_motor_command_is_recognized_with_both_times() -> None:
    result = parse_command(COMMAND)

    assert result["intent_id"] == "INT_CYCLIC_MOTOR"
    assert result["requires_clarification"] is False
    assert result["parameters"]["trigger_input"] == "I_Start"
    assert result["parameters"]["stop_input"] == "I_Stop"
    assert result["parameters"]["on_time"] == "T#3s"
    assert result["parameters"]["off_time"] == "T#3s"


def test_cyclic_motor_semantics_use_only_authorized_tags(
    io_map: dict,
    intents_catalog: dict,
    safety_rules: dict,
) -> None:
    result = parse_command(COMMAND)
    validation = validate_semantic_output(result, io_map, intents_catalog, safety_rules)

    assert validation["is_valid"] is True
    assert validation["unauthorized_tags"] == []


def test_cyclic_motor_openplc_package_compiles_and_simulates(
    tmp_path: Path,
    io_map: dict,
    intents_catalog: dict,
    safety_rules: dict,
) -> None:
    compiler = discover_openplc_compiler()
    if not compiler["available"]:
        pytest.skip("OpenPLC/MatIEC compiler is not installed in this environment.")

    semantic_output = parse_command(COMMAND)
    semantic_output["case_id"] = "D19"
    result = generate_project_package(
        semantic_output=semantic_output,
        target_platform="OPENPLC_ST",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules,
        output_dir=tmp_path / "generated",
    )

    verification = result["verification"]
    assert verification["is_valid"] is True
    assert verification["compilation_status"] == "COMPILATION_PASSED"
    assert verification["simulation_status"] == "SIMULATION_PASSED"
    assert verification["openplc_validation"]["simulation"]["tests_passed"] == 5
    assert verification["openplc_validation"]["simulation"]["tests_failed"] == 0
