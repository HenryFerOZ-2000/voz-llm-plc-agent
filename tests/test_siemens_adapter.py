from __future__ import annotations

from pathlib import Path

from code_generator import generate_implementation_from_ir
from ir_builder import build_project_ir
from platforms.siemens_scl_adapter import SiemensSCLAdapter
from project_packager import generate_project_package
from semantic_parser import parse_command


def test_siemens_adapter_renders_tia_v18_source(io_map: dict) -> None:
    semantic_output = parse_command("Arranca el motor despues de un retardo de 3 segundos")
    project_ir = build_project_ir(semantic_output, io_map, "SIEMENS_SCL_V18")
    project_ir.pou.implementation_code = generate_implementation_from_ir(project_ir)
    adapter = SiemensSCLAdapter()

    source = adapter.render_full_program(project_ir)

    assert 'FUNCTION_BLOCK "PLC_PRG"' in source
    assert 'DATA_BLOCK "DB_PLC_PRG"' in source
    assert 'ORGANIZATION_BLOCK "Main"' in source
    assert "TON_TIME" in source
    assert "#I_Emergency" in source
    assert 'I_Start := "I_Start"' in source
    assert 'Q_Motor_Enable => "Q_Motor_Enable"' in source
    assert adapter.to_siemens_address("%IX0.0") == "%I0.0"
    assert adapter.to_siemens_address("%QX0.0") == "%Q0.0"


def test_siemens_package_contains_external_source(
    tmp_path: Path,
    io_map: dict,
    intents_catalog: dict,
    safety_rules: dict
) -> None:
    semantic_output = parse_command("Haz que el motor se encienda con Start y se apague con Stop")
    package_result = generate_project_package(
        semantic_output=semantic_output,
        target_platform="SIEMENS_SCL_V18",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules,
        output_dir=tmp_path / "generated"
    )

    assert package_result["target_platform"] == "SIEMENS_SCL_V18"
    assert package_result["verification"]["is_valid"] is True
    assert Path(package_result["artifacts"]["siemens_source.scl"]).exists()
    assert Path(package_result["artifacts"]["tia_import_manifest.json"]).exists()
