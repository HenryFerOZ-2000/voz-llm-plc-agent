from __future__ import annotations

from llm_context_builder import build_llm_context


def test_context_builder_includes_safe_authorized_context(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    context = build_llm_context(
        command_text="Activa una salida por 5 segundos",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules
    )
    assert "authorized_intents" in context
    assert "authorized_io_map" in context
    assert "authorized_tags" in context
    assert "I_Start" in context["authorized_tags"]
    assert any(item["intent_id"] == "INT_TIMED_PULSE" for item in context["authorized_intents"])
