from __future__ import annotations

from llm_parser import parse_command


def test_rule_based_mode_stays_local(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    result = parse_command(
        "Haz que el motor se encienda con Start y se apague con Stop",
        mode="rule_based",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules
    )
    assert result["parser_mode_used"] == "rule_based"
    assert result["intent_id"] == "INT_MOTOR_START_STOP"


def test_hybrid_mode_falls_back_to_rules_when_llm_is_not_configured(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    result = parse_command(
        "Haz que el motor se encienda con Start y se apague con Stop",
        mode="hybrid",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules
    )
    assert result["parser_mode_requested"] == "hybrid"
    assert result["parser_mode_used"] == "rule_based"


def test_hybrid_mode_requests_clarification_on_critical_disagreement(monkeypatch, io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    monkeypatch.setenv("LLM_CONFIDENCE_THRESHOLD", "0.99")
    llm_response = {
        "intent_id": "INT_DELAYED_START",
        "case_id": None,
        "command_text": "Haz que el motor se encienda con Start y se apague con Stop",
        "normalized_command": "haz que el motor se enciende con start y se stop con stop",
        "parameters": {
            "trigger_input": "I_Start",
            "stop_input": "I_Stop",
            "emergency_input": "I_Emergency",
            "motor_output": "Q_Motor_Enable",
            "delay_time": "T#4s",
            "timer": "T_DelayStart"
        },
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable", "T_DelayStart"],
        "unrecognized_terms": []
    }
    result = parse_command(
        "Haz que el motor se encienda con Start y se apague con Stop",
        mode="hybrid",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules,
        llm_response_text=llm_response
    )
    assert result["intent_id"] == "INT_UNKNOWN"
    assert result["requires_clarification"] is True
