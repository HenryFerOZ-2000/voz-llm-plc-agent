from __future__ import annotations

from ir_builder import build_project_ir
from semantic_parser import parse_command


def test_ir_generation_contains_required_motor_variables(io_map: dict) -> None:
    semantic_output = parse_command("Haz que el motor se encienda con Start y se apague con Stop")
    project_ir = build_project_ir(semantic_output, io_map, "CODESYS_ST")
    variable_names = [variable.name for variable in project_ir.pou.variables]
    assert "I_Start" in variable_names
    assert "I_Stop" in variable_names
    assert "I_Emergency" in variable_names
    assert "Q_Motor_Enable" in variable_names
