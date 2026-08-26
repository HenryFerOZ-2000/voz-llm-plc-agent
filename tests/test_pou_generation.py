from __future__ import annotations

from code_generator import generate_implementation_from_ir
from ir_builder import build_project_ir
from semantic_parser import parse_command


def test_pou_generation_keeps_emergency_logic(io_map: dict) -> None:
    semantic_output = parse_command("Haz que el motor se encienda con Start y se apague con Stop")
    project_ir = build_project_ir(semantic_output, io_map, "CODESYS_ST")
    implementation = generate_implementation_from_ir(project_ir)
    assert "I_Emergency" in implementation
    assert "Q_Motor_Enable" in implementation
    assert "(*" in implementation
