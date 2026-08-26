from __future__ import annotations

from pathlib import Path

from project_packager import generate_project_package
from semantic_parser import parse_command


def test_project_package_contains_semantic_artifacts(tmp_path, io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    semantic_output = parse_command("Haz que el motor se encienda con Start y se apague con Stop")
    package_result = generate_project_package(
        semantic_output=semantic_output,
        target_platform="CODESYS_ST",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules,
        output_dir=tmp_path / "generated"
    )
    assert package_result["verification"]["is_valid"] is True
    artifacts = package_result["artifacts"]
    assert Path(artifacts["semantic_input.json"]).exists()
    assert Path(artifacts["semantic_validation.json"]).exists()
    assert Path(artifacts["generation_metadata.json"]).exists()
