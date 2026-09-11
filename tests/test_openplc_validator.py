from __future__ import annotations

from pathlib import Path

import pytest

from openplc_validator import discover_openplc_compiler
from project_packager import generate_project_package
from semantic_parser import parse_command


@pytest.mark.parametrize(
    ("case_id", "command", "expected_intent", "expected_tests"),
    [
        ("D01", "Activa una salida durante 5 segundos cuando presione Start", "INT_TIMED_PULSE", 3),
        # D03 nunca pide reset/alarma: reset_input/alarm_output/run_indicator/fault_indicator son
        # OPCIONALES para INT_MOTOR_START_STOP (ver ir_builder.OPTIONAL_PARAMETER_KEYS) y ya no se
        # agregan por defecto solo porque el mapa activo los tenga disponibles - por eso el caso
        # MSS_04 (que probaba exclusivamente el reset) se omite y el conteo baja de 5 a 4.
        ("D03", "Haz que el motor se encienda con Start y se apague con Stop", "INT_MOTOR_START_STOP", 4),
        ("D05", "El paro de emergencia debe apagar el motor siempre", "INT_EMERGENCY_PRIORITY", 1),
        ("D07", "Arranca el motor despues de un retardo de 3 segundos", "INT_DELAYED_START", 3),
        ("D09", "Cuenta 5 pulsos del sensor y activa la alarma", "INT_COUNTER_PULSES", 3),
    ],
)
def test_representative_openplc_packages_compile_and_run_functional_tests(
    tmp_path: Path,
    io_map: dict,
    intents_catalog: dict,
    safety_rules: dict,
    case_id: str,
    command: str,
    expected_intent: str,
    expected_tests: int,
) -> None:
    compiler = discover_openplc_compiler()
    if not compiler["available"]:
        pytest.skip("OpenPLC/MatIEC compiler is not installed in this environment.")

    semantic_output = parse_command(command)
    semantic_output["case_id"] = case_id
    assert semantic_output["intent_id"] == expected_intent
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
    assert verification["is_fully_validated"] is True
    assert verification["openplc_validation"]["simulation"]["tests_passed"] == expected_tests
    assert verification["openplc_validation"]["simulation"]["tests_failed"] == 0
    assert Path(result["artifacts"]["openplc_compilation.json"]).exists()
    assert Path(result["artifacts"]["openplc_simulation.json"]).exists()
