from __future__ import annotations

from plc_maps.map_validator import validate_plc_variable_map


def _variable(**overrides: object) -> dict:
    base = {
        "name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX0.0",
        "initial_value": "FALSE", "description": "", "aliases": [], "semantic_role": "",
        "llm_allowed": True, "safety_level": "normal", "unit": "", "min": None, "max": None,
        "comments": ""
    }
    base.update(overrides)
    return base


def test_validate_plc_variable_map_accepts_clean_map(safety_rules: dict) -> None:
    variables = [
        _variable(name="I_Start", location="%IX0.0"),
        _variable(name="I_Stop", location="%IX0.1")
    ]
    result = validate_plc_variable_map({"variables": variables}, safety_rules)
    assert result["is_valid"] is True
    assert result["errors"] == []


def test_validate_plc_variable_map_flags_duplicate_address(safety_rules: dict) -> None:
    variables = [
        _variable(name="I_Start", location="%IX0.0"),
        _variable(name="I_Stop", location="%IX0.0")
    ]
    result = validate_plc_variable_map({"variables": variables}, safety_rules)
    assert result["is_valid"] is False
    assert any("Direccion duplicada" in error for error in result["errors"])


def test_validate_plc_variable_map_flags_invalid_safety_level(safety_rules: dict) -> None:
    variables = [_variable(safety_level="urgentisimo")]
    result = validate_plc_variable_map({"variables": variables}, safety_rules)
    assert result["is_valid"] is False


def test_validate_plc_variable_map_flags_incoherent_min_max(safety_rules: dict) -> None:
    variables = [_variable(name="M_Level", class_="internal", type="INT", location="", min=10, max=5)]
    variables[0]["class"] = "internal"
    result = validate_plc_variable_map({"variables": variables}, safety_rules)
    assert result["is_valid"] is False
    assert any("min" in error and "max" in error for error in result["errors"])


def test_validate_plc_variable_map_warns_uncritical_emergency(safety_rules: dict) -> None:
    variables = [_variable(name="I_Emergency", location="%IX0.2", safety_level="normal")]
    result = validate_plc_variable_map({"variables": variables}, safety_rules)
    assert result["is_valid"] is True
    assert any("I_Emergency" in warning for warning in result["warnings"])
