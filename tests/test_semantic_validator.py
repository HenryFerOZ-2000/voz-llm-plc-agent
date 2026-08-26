from __future__ import annotations

from semantic_parser import parse_command
from semantic_validator import validate_semantic_output


def test_semantic_validator_accepts_valid_motor_start_stop(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    semantic_output = parse_command("Haz que el motor se encienda con Start y se apague con Stop")
    result = validate_semantic_output(semantic_output, io_map, intents_catalog, safety_rules)
    assert result["is_valid"] is True
    assert result["errors"] == []


def test_semantic_validator_rejects_unauthorized_tag(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    semantic_output = parse_command("Activa una salida")
    semantic_output["recognized_tags"] = ["Q_Bomba_Principal"]
    result = validate_semantic_output(semantic_output, io_map, intents_catalog, safety_rules)
    assert result["is_valid"] is False
    assert result["unauthorized_tags"] == ["Q_Bomba_Principal"]


def test_semantic_validator_rejects_llm_disallowed_tag(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    restricted_io_map = {
        "naming_convention": io_map.get("naming_convention", {}),
        "variables": [
            {**variable, "llm_allowed": False} if variable.get("name") == "I_Start" else variable
            for variable in io_map.get("variables", [])
        ]
    }
    semantic_output = parse_command("Haz que el motor se encienda con Start y se apague con Stop")
    result = validate_semantic_output(semantic_output, restricted_io_map, intents_catalog, safety_rules)
    assert result["is_valid"] is False
    assert any("llm_allowed=false" in error for error in result["errors"])
