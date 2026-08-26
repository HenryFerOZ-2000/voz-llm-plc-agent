from gui_helpers import normalize_variable_entry


def test_normalize_variable_entry_includes_advanced_fields_with_defaults() -> None:
    entry = normalize_variable_entry({"name": "I_Start", "class": "input", "type": "BOOL"})
    assert entry["aliases"] == []
    assert entry["semantic_role"] == ""
    assert entry["llm_allowed"] is True
    assert entry["safety_level"] == "normal"
    assert entry["min"] is None
    assert entry["max"] is None


def test_normalize_variable_entry_overrides_existing_advanced_fields() -> None:
    entry = normalize_variable_entry(
        {
            "name": "I_Emergency",
            "class": "input",
            "type": "BOOL",
            "aliases": ["paro de emergencia", "emergencia"],
            "semantic_role": "emergency_stop",
            "llm_allowed": False,
            "safety_level": "critical",
            "min": "0",
            "max": "10"
        }
    )
    assert entry["aliases"] == ["paro de emergencia", "emergencia"]
    assert entry["semantic_role"] == "emergency_stop"
    assert entry["llm_allowed"] is False
    assert entry["safety_level"] == "critical"
    assert entry["min"] == 0.0
    assert entry["max"] == 10.0


def test_normalize_variable_entry_parses_comma_separated_aliases_string() -> None:
    entry = normalize_variable_entry({"name": "I_Start", "aliases": "pulsador verde, boton de arranque"})
    assert entry["aliases"] == ["pulsador verde", "boton de arranque"]
