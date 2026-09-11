"""
Tests for the "zero unnecessary questions" autonomy pass: deterministic channel selection
(lowest address first), no address collision within one batch of role-based requests, the
implicit multi-motor fallback pattern, and the map-driven I_Emergency requirement fix.
"""
from __future__ import annotations

from io_allocator import extract_implicit_multi_resource_requests, propose_assignment
from semantic_validator import validate_semantic_output


def _variable(name, location, state, var_class="input", var_type="BOOL"):
    return {
        "name": name, "class": var_class, "type": var_type, "location": location,
        "initial_value": "FALSE", "description": "", "state": state, "llm_allowed": True
    }


def _bench_map():
    return {
        "variables": [
            _variable("I_Start", "%IX16.0", "LOCKED"),
            _variable("I_Stop", "%IX16.1", "LOCKED"),
            _variable("I_Reset", "%IX16.2", "ASSIGNED"),
            _variable("I_Free1", "%IX16.3", "FREE"),
            _variable("Q_Lamp", "%QX8.0", "ASSIGNED", var_class="output"),
            _variable("Q_Auxiliary", "%QX8.1", "ASSIGNED", var_class="output"),
            _variable("Q_Free1", "%QX8.2", "FREE", var_class="output"),
        ]
    }


# ---------- Section 37: determinism (lowest address first) ----------

def test_free_selection_picks_lowest_address_regardless_of_json_order():
    io_map = {
        "variables": [
            _variable("Q_Free_High", "%QX8.6", "FREE", var_class="output"),
            _variable("Q_Free_Low", "%QX8.2", "FREE", var_class="output"),
            _variable("Q_Free_Mid", "%QX8.4", "FREE", var_class="output"),
        ]
    }
    proposals = propose_assignment(io_map, [{"functional_name_hint": "Q_Motor_1"}])
    assert proposals[0]["address"] == "%QX8.2"


def test_same_map_and_command_always_produce_the_same_result():
    io_map = _bench_map()
    requests = [{"functional_name_hint": "Q_Motor_1"}, {"functional_name_hint": "Q_Motor_2"}]
    first = propose_assignment(io_map, requests)
    second = propose_assignment(io_map, requests)
    assert [(p["address"], p["proposed_name"]) for p in first] == [(p["address"], p["proposed_name"]) for p in second]


# ---------- Bug real encontrado en esta tarea: colision de direccion dentro de un mismo lote ----------

def test_two_role_requests_in_one_batch_never_collide_on_the_same_free_address():
    io_map = _bench_map()
    requests = [{"functional_name_hint": "Q_Motor_1"}, {"functional_name_hint": "Q_Motor_2"}]
    proposals = propose_assignment(io_map, requests)
    addresses = [p["address"] for p in proposals]
    assert len(set(addresses)) == len(addresses)  # nunca la misma direccion dos veces


def test_full_two_motor_scenario_prefers_free_before_reassigning_assigned():
    """
    Peticiones SIN direccion explicita (rol solamente): el allocator debe preferir un canal FREE
    antes que reasignar uno ya ASSIGNED (seccion 7, prioridad 4 antes que 5) - distinto del
    ejemplo de la seccion 41, que da direcciones EXPLICITAS y por tanto SI reasigna directamente
    lo que el usuario pidio (ver test_explicit_addresses_reassign_exactly_as_the_user_said).
    """
    io_map = _bench_map()
    requests = [
        {"functional_name_hint": "I_Start", "role_text": "arranque motor 1"},
        {"functional_name_hint": "I_Start_Motor_2", "role_text": "arranque motor 2"},
        {"functional_name_hint": "Q_Motor_1", "role_text": "motor 1"},
        {"functional_name_hint": "Q_Motor_2", "role_text": "motor 2"}
    ]
    proposals = propose_assignment(io_map, requests)
    by_name = {p["proposed_name"]: p["address"] for p in proposals}
    assert by_name["I_Start"] == "%IX16.0"           # LOCKED, reutilizado tal cual (exact match)
    assert by_name["I_Start_Motor_2"] == "%IX16.3"   # I_Free1 (FREE), preferido sobre I_Reset
    assert by_name["Q_Motor_1"] == "%QX8.2"          # Q_Free1 (FREE), preferido sobre Q_Lamp
    assert by_name["Q_Motor_2"] == "%QX8.0"          # sin FREE restante -> reasigna Q_Lamp (mas bajo)
    assert not any(p["blocked"] for p in proposals)


def test_explicit_addresses_reassign_exactly_as_the_user_said():
    """Seccion 41: cuando el usuario da la direccion EXPLICITA, el allocator la honra tal cual
    (reasignando si hace falta) - no la sustituye por un canal FREE distinto."""
    io_map = _bench_map()
    requests = [
        {"address": "%IX16.2", "functional_name_hint": "I_Start_Motor_2"},
        {"address": "%QX8.0", "functional_name_hint": "Q_Motor_1"},
        {"address": "%QX8.1", "functional_name_hint": "Q_Motor_2"}
    ]
    proposals = propose_assignment(io_map, requests)
    by_name = {p["proposed_name"]: p["address"] for p in proposals}
    assert by_name["I_Start_Motor_2"] == "%IX16.2"
    assert by_name["Q_Motor_1"] == "%QX8.0"
    assert by_name["Q_Motor_2"] == "%QX8.1"
    assert not any(p["blocked"] for p in proposals)


# ---------- Section 42: patron implicito "N motores con pulsante independiente cada uno" ----------

def test_implicit_two_motor_pattern_is_recognized():
    text = "Quiero controlar dos motores con un pulsante de arranque independiente para cada uno."
    requests = extract_implicit_multi_resource_requests(text)
    hints = [r["functional_name_hint"] for r in requests]
    assert hints == ["I_Start", "Q_Motor_1", "I_Start_Motor_2", "Q_Motor_2"]


def test_implicit_pattern_matches_worked_example_end_to_end():
    io_map = _bench_map()
    text = (
        "Quiero controlar dos motores con un pulsante de arranque independiente para cada uno. "
        "Cuando arranque el motor 2 debe apagarse el motor 1."
    )
    requests = extract_implicit_multi_resource_requests(text)
    proposals = propose_assignment(io_map, requests)
    by_name = {p["proposed_name"]: p["address"] for p in proposals}
    assert by_name["I_Start"] == "%IX16.0"
    assert by_name["I_Start_Motor_2"] == "%IX16.3"  # FREE preferido sobre I_Reset (ASSIGNED)
    assert by_name["Q_Motor_1"] == "%QX8.2"         # FREE preferido sobre Q_Lamp (ASSIGNED)
    assert by_name["Q_Motor_2"] == "%QX8.0"         # sin FREE restante -> reasigna el mas bajo
    assert not any(p["blocked"] for p in proposals)


def test_implicit_pattern_does_not_fire_on_unrelated_text():
    assert extract_implicit_multi_resource_requests("Enciende la luz de la sala.") == []
    assert extract_implicit_multi_resource_requests("Quiero dos motores.") == []  # sin "pulsante independiente"


def test_implicit_pattern_ignores_unreasonable_counts():
    assert extract_implicit_multi_resource_requests(
        "Quiero controlar cien motores con un pulsante independiente para cada uno."
    ) == []


# ---------- Section 4: no exigir I_Emergency si no existe fisicamente en el mapa ----------

def _map_without_emergency():
    return {
        "variables": [
            _variable("I_Start", "%IX16.0", "LOCKED"),
            _variable("I_Stop", "%IX16.1", "LOCKED"),
            _variable("Q_Motor_1", "%QX8.0", "ASSIGNED", var_class="output"),
        ]
    }


def _map_with_emergency():
    payload = _map_without_emergency()
    payload["variables"].append(_variable("I_Emergency", "%IX16.5", "LOCKED"))
    return payload


def test_motor_command_does_not_require_emergency_when_bench_has_none():
    io_map = _map_without_emergency()
    semantic_output = {
        "intent_id": "INT_MOTOR_LATCH",
        "case_id": None,
        "command_text": "arranca el motor con start",
        "normalized_command": "arranca el motor con start",
        "parameters": {"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_1", "run_latch": "M_RunLatch"},
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start", "I_Stop", "Q_Motor_1"],
        "unrecognized_terms": []
    }
    result = validate_semantic_output(semantic_output, io_map, {"INT_MOTOR_LATCH": {}}, {})
    assert not any("I_Emergency" in error for error in result["errors"])


def test_motor_command_still_requires_emergency_when_bench_has_it():
    """No regresion: si el mapa SI tiene I_Emergency (banco D01-D20), la exigencia se mantiene."""
    io_map = _map_with_emergency()
    semantic_output = {
        "intent_id": "INT_MOTOR_LATCH",
        "case_id": None,
        "command_text": "arranca el motor con start",
        "normalized_command": "arranca el motor con start",
        "parameters": {"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_1", "run_latch": "M_RunLatch"},
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start", "I_Stop", "Q_Motor_1"],
        "unrecognized_terms": []
    }
    result = validate_semantic_output(semantic_output, io_map, {"INT_MOTOR_LATCH": {}}, {})
    assert any("I_Emergency" in error for error in result["errors"])
