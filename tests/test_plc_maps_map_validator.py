from __future__ import annotations

import pytest

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


@pytest.mark.parametrize("digital,analog", [("%IX0.0", "%IW0"), ("%IX1.7", "%IW0"),
                                            ("%QX0.0", "%QW0"), ("%QX1.7", "%QW0")])
def test_analog_word_cannot_overlap_digital_channel(digital, analog):
    is_input = digital.startswith("%I")
    variables = [
        _variable(name="I_Start" if is_input else "Q_Run", location=digital,
                  **{"class": "input" if is_input else "output"}),
        _variable(name="AI_Level" if is_input else "AO_Command", location=analog, type="INT",
                  llm_allowed=False, **{"class": "input" if is_input else "output"}),
    ]
    result = validate_plc_variable_map({"variables": variables})
    assert not result["is_valid"]
    assert any("solapamiento" in e.lower() and digital in e and analog in e for e in result["errors"])


def test_adjacent_analog_words_and_separate_input_output_areas_are_valid():
    variables = [
        _variable(name="AI_Level", location="%IW0", type="INT"),
        _variable(name="AI_Flow", location="%IW2", type="INT"),
        _variable(name="AO_Command", location="%QW0", type="INT", **{"class": "output"}),
        _variable(name="I_Start", location="%IX16.0"),
        _variable(name="Q_Run", location="%QX8.0", **{"class": "output"}),
    ]
    assert validate_plc_variable_map({"variables": variables})["is_valid"]


def test_shifted_analog_words_cannot_overlap():
    variables = [_variable(name="AI_Level", location="%IW0", type="INT"),
                 _variable(name="AI_Flow", location="%IW1", type="INT")]
    result = validate_plc_variable_map({"variables": variables})
    assert not result["is_valid"]
    assert any("solapamiento" in e.lower() for e in result["errors"])
