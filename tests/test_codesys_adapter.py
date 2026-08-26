from __future__ import annotations

from ir_builder import build_project_ir
from platforms.codesys_adapter import CodesysAdapter
from semantic_parser import parse_command


def test_codesys_adapter_omits_locations_by_default(io_map: dict) -> None:
    semantic_output = parse_command("Haz que el motor se encienda con Start y se apague con Stop")
    project_ir = build_project_ir(semantic_output, io_map, "CODESYS_ST")
    declarations = CodesysAdapter(use_physical_locations=False).render_declarations(project_ir)
    assert "AT %IX0.0" not in declarations
    assert "PROGRAM PLC_PRG" in declarations
