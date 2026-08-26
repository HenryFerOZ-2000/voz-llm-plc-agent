from __future__ import annotations

from schemas import validate_semantic_model, validate_semantic_payload_structure
from semantic_parser import parse_command


def test_rule_based_output_matches_semantic_schema() -> None:
    payload = parse_command("Haz que el motor se encienda con Start y se apague con Stop")
    assert validate_semantic_payload_structure(payload) == []
    model = validate_semantic_model(payload)
    assert model.intent_id == "INT_MOTOR_START_STOP"
    assert model.command_text
