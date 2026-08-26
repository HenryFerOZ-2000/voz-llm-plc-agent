from __future__ import annotations

from ir_builder import build_project_ir
from platforms.openplc_adapter import OpenPLCAdapter
from semantic_parser import parse_command


def test_openplc_adapter_renders_physical_locations(io_map: dict) -> None:
    semantic_output = parse_command("Haz que el motor se encienda con Start y se apague con Stop")
    project_ir = build_project_ir(semantic_output, io_map, "OPENPLC_ST")
    declarations = OpenPLCAdapter().render_declarations(project_ir)
    assert "AT %IX0.0" in declarations
    assert "AT %QX0.0" in declarations
    assert declarations.splitlines().count("VAR") == 2


def test_openplc_adapter_closes_program(io_map: dict) -> None:
    semantic_output = parse_command("Haz que el motor se encienda con Start y se apague con Stop")
    project_ir = build_project_ir(semantic_output, io_map, "OPENPLC_ST")
    full_program = OpenPLCAdapter().render_full_program(project_ir)
    assert full_program.rstrip().endswith("END_PROGRAM")
