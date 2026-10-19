"""
Tests for the deterministic IOAllocator: FREE/ASSIGNED/LOCKED state machine, address
normalization, regex-only extraction of map-configuration requests, allocation priority, and
persistence/history. Covers section 28's 20 required scenarios.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from io_allocator import (
    STATE_ASSIGNED,
    STATE_FREE,
    STATE_LOCKED,
    apply_assignments,
    block_map_config_message,
    extract_io_assignment_requests,
    normalize_address,
    propose_assignment,
    set_variable_state,
    undo_last_map_change,
    validate_assignment_request,
    validate_manual_rename
)
from ir_builder import build_project_ir
from plc_maps.store import get_map_history, save_plc_map


def _variable(name, location, state, var_class="input", var_type="BOOL"):
    return {
        "name": name, "class": var_class, "type": var_type, "location": location,
        "initial_value": "FALSE", "description": "", "state": state, "llm_allowed": True
    }


def _sample_map():
    return {
        "variables": [
            _variable("I_Start", "%IX16.0", STATE_LOCKED),
            _variable("I_Stop", "%IX16.1", STATE_LOCKED),
            _variable("I_Reset", "%IX16.3", STATE_ASSIGNED),
            _variable("I_Free1", "%IX16.2", STATE_FREE),
            _variable("Q_Alarm", "%QX8.1", STATE_ASSIGNED, var_class="output"),
            _variable("Q_Free1", "%QX8.0", STATE_FREE, var_class="output"),
            _variable("Q_Free2", "%QX8.2", STATE_FREE, var_class="output"),
        ]
    }


def test_named_digital_assignment_uses_compatible_free_channel_without_mutating_map():
    import copy
    source=_sample_map();before=copy.deepcopy(source)
    result=propose_assignment(source,[{'name':'Q_Sensor_Alarm','class':'output','type':'BOOL'}])
    assert len(result)==1 and result[0]['blocked'] is False
    assert result[0]['proposed_name']=='Q_Sensor_Alarm' and result[0]['address']=='%QX8.0'
    assert source==before


@pytest.mark.parametrize('assignment',[
    {'name':'Q_Sensor_Alarm','class':'input','type':'BOOL'},
    {'name':'Q_Sensor_Alarm','class':'output','type':'REAL'},
    {'name':'Level_PV','class':'internal','type':'REAL'},
])
def test_named_assignment_cannot_change_resource_kind_or_allocate_analog_as_bool(assignment):
    result=propose_assignment(_sample_map(),[assignment])
    assert result[0]['blocked'] is True and result[0]['address'] is None


# ---------- 6. Address normalization ----------

@pytest.mark.parametrize("raw,expected", [
    ("Q8.1", "%QX8.1"),
    ("%Q8.1", "%QX8.1"),
    ("salida 8.1", "%QX8.1"),
    ("I16.2", "%IX16.2"),
    ("entrada 16.2", "%IX16.2"),
    ("%I16.2", "%IX16.2"),
    ("IW0", "%IW0"),
    ("%IW0", "%IW0"),
    ("qw4", "%QW4"),
])
def test_normalize_address_recognized_forms(raw, expected):
    assert normalize_address(raw) == expected


def test_normalize_address_unrecognized_returns_none():
    assert normalize_address("no es una direccion") is None
    assert normalize_address("") is None


# ---------- 7/8. Validation: direction/type compatibility, nonexistent address ----------

def test_validate_assignment_request_rejects_output_role_on_input_address():
    io_map = _sample_map()
    result = validate_assignment_request(io_map, "%IX16.0", "Q_Something")
    assert result["valid"] is False
    assert any("incompatible" in error for error in result["errors"])


def test_validate_assignment_request_rejects_nonexistent_address():
    io_map = _sample_map()
    result = validate_assignment_request(io_map, "%IX20.0", "I_Whatever")
    assert result["valid"] is False
    assert "no existe" in result["errors"][0]


def test_validate_assignment_request_accepts_compatible_pair():
    io_map = _sample_map()
    result = validate_assignment_request(io_map, "%IX16.2", "I_Reverse")
    assert result["valid"] is True


# ---------- 1/2/3. FREE / ASSIGNED / LOCKED proposal behavior (explicit address) ----------

def test_free_channel_can_be_proposed_and_applied():
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"address": "%QX8.0", "functional_name_hint": "Q_Motor_1"}])
    assert proposals[0]["blocked"] is False
    assert proposals[0]["conflict"] is False
    updated_map, history = apply_assignments(io_map, proposals)
    variable = next(v for v in updated_map["variables"] if v["location"] == "%QX8.0")
    assert variable["name"] == "Q_Motor_1"
    assert variable["state"] == STATE_ASSIGNED
    assert len(history) == 1
    assert history[0]["old_name"] == "Q_Free1"
    assert history[0]["new_name"] == "Q_Motor_1"


def test_assigned_channel_proposal_flags_conflict_and_requires_confirmation():
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"address": "%QX8.1", "functional_name_hint": "Q_Motor_2"}])
    assert proposals[0]["blocked"] is False
    assert proposals[0]["conflict"] is True
    assert "Q_Alarm" in proposals[0]["reason"]


def test_locked_channel_is_blocked_and_never_applied():
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"address": "%IX16.0", "functional_name_hint": "I_Reverse"}])
    assert proposals[0]["blocked"] is True
    assert "protegida" in proposals[0]["reason"]
    with pytest.raises(ValueError):
        apply_assignments(io_map, proposals)


def test_apply_assignments_refuses_locked_even_if_proposal_not_rechecked():
    io_map = _sample_map()
    # Proposal built by hand, bypassing propose_assignment's own LOCKED guard.
    forged_proposal = {"address": "%IX16.0", "proposed_name": "I_Reverse", "blocked": False}
    with pytest.raises(ValueError, match="LOCKED"):
        apply_assignments(io_map, [forged_proposal])


# ---------- 4. LOCKED can still be used in logic ----------

def test_locked_variable_still_resolves_in_build_project_ir():
    io_map = _sample_map()
    semantic_output = {
        "intent_id": "INT_DIRECT_OUTPUT",
        "case_id": "T_LOCKED",
        "command_text": "test",
        "parameters": {"trigger_input": "I_Start", "emergency_input": "I_Stop", "output": "Q_Free1"}
    }
    project_ir = build_project_ir(semantic_output, io_map, target_platform="SIEMENS_SCL_V18")
    names = {v.name for v in project_ir.pou.variables}
    assert "I_Start" in names  # I_Start is LOCKED but still usable by name


# ---------- 5/20. Physical address never changes ----------

def test_apply_assignments_never_changes_location():
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"address": "%QX8.0", "functional_name_hint": "Q_Motor_1"}])
    updated_map, _ = apply_assignments(io_map, proposals)
    original_locations = {v["name"]: v["location"] for v in io_map["variables"]}
    for variable in updated_map["variables"]:
        # every entry keeps a location among the original set of physical locations
        assert variable["location"] in original_locations.values()


def test_set_variable_state_never_touches_location_or_name():
    io_map = _sample_map()
    updated = set_variable_state(io_map, "I_Reset", STATE_LOCKED)
    variable = next(v for v in updated["variables"] if v["name"] == "I_Reset")
    assert variable["location"] == "%IX16.3"
    assert variable["state"] == STATE_LOCKED


def test_set_variable_state_rejects_unknown_variable():
    with pytest.raises(ValueError):
        set_variable_state(_sample_map(), "I_DoesNotExist", STATE_LOCKED)


def test_set_variable_state_rejects_invalid_state():
    with pytest.raises(ValueError):
        set_variable_state(_sample_map(), "I_Reset", "MAYBE")


# ---------- 9/10/11. Extraction: config-only, combined, two-motor commands ----------

def test_pure_logic_command_yields_no_assignment_requests():
    assert extract_io_assignment_requests("Enciende el motor con Start y detenlo con Stop.") == []


def test_config_only_command_extracts_one_request():
    requests = extract_io_assignment_requests("Configura Q8.1 como salida del motor 2.")
    assert len(requests) == 1
    assert requests[0]["address"] == "%QX8.1"
    assert requests[0]["functional_name_hint"] == "Q_Motor_2"


def test_two_motor_command_extracts_both_addresses():
    requests = extract_io_assignment_requests("Configura Q8.0 como motor 1 y Q8.1 como motor 2.")
    assert len(requests) == 2
    assert requests[0]["address"] == "%QX8.0"
    assert requests[0]["functional_name_hint"] == "Q_Motor_1"
    assert requests[1]["address"] == "%QX8.1"
    assert requests[1]["functional_name_hint"] == "Q_Motor_2"


def test_combined_command_only_extracts_the_configuration_clause():
    text = (
        "Usa Q8.0 para el motor 1 y Q8.1 para el motor 2. "
        "Enciende el motor 1 con Start y cuando arranque el motor 2 apaga el motor 1."
    )
    requests = extract_io_assignment_requests(text)
    assert len(requests) == 2
    assert {r["address"] for r in requests} == {"%QX8.0", "%QX8.1"}
    # The logic sentence never turns into a spurious third request.
    assert all(r["role_text"] in ("motor 1", "motor 2") for r in requests)


def test_start_stop_with_e_conjunction():
    requests = extract_io_assignment_requests("Usa I16.0 para Start e I16.1 para Stop.")
    assert len(requests) == 2
    assert requests[0]["functional_name_hint"] == "I_Start"
    assert requests[1]["functional_name_hint"] == "I_Stop"


def test_reverse_pushbutton_phrasing():
    requests = extract_io_assignment_requests("Asigna I16.2 como pulsante de cambio de giro.")
    assert len(requests) == 1
    assert requests[0]["functional_name_hint"] == "I_Reverse"


# ---------- 12/13/14/15. Allocator priority ----------

def test_allocator_reuses_existing_exact_name_first():
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"functional_name_hint": "I_Reset"}])
    assert proposals[0]["conflict"] is False
    assert proposals[0]["current_name"] == "I_Reset"
    assert proposals[0]["reason"].startswith("Ya existe")


def test_allocator_uses_free_channel_when_no_existing_name():
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"functional_name_hint": "I_Reverse"}])
    assert proposals[0]["blocked"] is False
    assert proposals[0]["current_state"] == STATE_FREE


def test_allocator_offers_assigned_reassignment_when_no_free_channel():
    io_map = _sample_map()
    # Free up every FREE input so only ASSIGNED/LOCKED inputs remain.
    io_map["variables"] = [v for v in io_map["variables"] if not (v["class"] == "input" and v["state"] == STATE_FREE)]
    proposals = propose_assignment(io_map, [{"functional_name_hint": "I_NewRole"}])
    assert proposals[0]["blocked"] is False
    assert proposals[0]["conflict"] is True
    assert proposals[0]["current_name"] == "I_Reset"


def test_allocator_never_touches_locked_when_resolving_by_role():
    io_map = _sample_map()
    # Only LOCKED inputs remain.
    io_map["variables"] = [v for v in io_map["variables"] if not (v["class"] == "input" and v["state"] != STATE_LOCKED)]
    proposals = propose_assignment(io_map, [{"functional_name_hint": "I_NewRole"}])
    assert proposals[0]["blocked"] is True
    assert "LOCKED" in proposals[0]["reason"] or "compatible" in proposals[0]["reason"]


def test_reversible_motor_example_uses_free_channels(tmp_path):
    io_map = _sample_map()
    requests = extract_io_assignment_requests(
        "Usa I16.2 para reversa, Q8.0 para giro adelante y Q8.1 para giro reverso."
    )
    proposals = propose_assignment(io_map, requests)
    assert all(not p["blocked"] for p in proposals)
    updated_map, _ = apply_assignments(io_map, proposals)
    names_by_address = {v["location"]: v["name"] for v in updated_map["variables"]}
    assert names_by_address["%IX16.2"] == "I_Reverse"
    assert names_by_address["%QX8.0"] == "Q_Motor_Forward"


# ---------- 16. Persistence across "restart" ----------

def test_assignments_and_history_persist_after_save_and_reload(tmp_path):
    map_path = tmp_path / "mapa_test.json"
    save_plc_map(map_path, _sample_map()["variables"])
    io_map = json.loads(map_path.read_text(encoding="utf-8"))

    proposals = propose_assignment(io_map, [{"address": "%QX8.0", "functional_name_hint": "Q_Motor_1"}])
    updated_map, history = apply_assignments(io_map, proposals)
    save_plc_map(map_path, updated_map["variables"], history_entries=history)

    reloaded = json.loads(map_path.read_text(encoding="utf-8"))
    variable = next(v for v in reloaded["variables"] if v["location"] == "%QX8.0")
    assert variable["name"] == "Q_Motor_1"
    assert variable["state"] == STATE_ASSIGNED
    assert len(reloaded["history"]) == 1
    assert reloaded["history"][0]["new_name"] == "Q_Motor_1"
    assert get_map_history(map_path)[0]["new_name"] == "Q_Motor_1"


def test_undo_last_map_change_reverts_name_and_state(tmp_path):
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"address": "%QX8.0", "functional_name_hint": "Q_Motor_1"}])
    updated_map, history = apply_assignments(io_map, proposals)
    reverted_map, undone_entry = undo_last_map_change(updated_map, history)
    variable = next(v for v in reverted_map["variables"] if v["location"] == "%QX8.0")
    assert variable["name"] == "Q_Free1"
    assert variable["state"] == STATE_FREE
    assert undone_entry["new_name"] == "Q_Motor_1"


def test_undo_with_empty_history_is_a_noop():
    io_map = _sample_map()
    reverted_map, undone_entry = undo_last_map_change(io_map, [])
    assert reverted_map == io_map
    assert undone_entry is None


# ---------- 17. Experimental-mode blocking ----------

def test_map_config_blocked_message_when_trial_active():
    message = block_map_config_message(active_trial={"trial_id": "T1"}, active_profile_id=None)
    assert message is not None
    assert "ensayo experimental" in message


def test_map_config_blocked_message_when_profile_selected():
    message = block_map_config_message(active_trial=None, active_profile_id="D01")
    assert message is not None


def test_map_config_allowed_in_normal_mode():
    assert block_map_config_message(active_trial=None, active_profile_id=None) is None


# ---------- Politica de confirmaciones: requires_confirmation ----------

def test_free_channel_never_requires_confirmation():
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"address": "%QX8.0", "functional_name_hint": "Q_Motor_1"}])
    assert proposals[0]["requires_confirmation"] is False


def test_reusing_exact_same_name_never_requires_confirmation():
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"address": "%IX16.3", "functional_name_hint": "I_Reset"}])
    assert proposals[0]["conflict"] is False
    assert proposals[0]["requires_confirmation"] is False


def test_assigned_to_different_name_requires_confirmation():
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"address": "%QX8.1", "functional_name_hint": "Q_Motor_2"}])
    assert proposals[0]["requires_confirmation"] is True


def test_locked_never_requires_confirmation_it_is_just_blocked():
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"address": "%IX16.0", "functional_name_hint": "I_Reverse"}])
    assert proposals[0]["blocked"] is True
    assert proposals[0]["requires_confirmation"] is False


# ---------- Bug real: verbos de relleno rompian el slug ("controlar el motor 2") ----------

def test_natural_phrasing_with_filler_verb_still_produces_clean_motor_name():
    requests = extract_io_assignment_requests("Usa la salida Q8.1 para controlar el motor 2.")
    assert requests[0]["functional_name_hint"] == "Q_Motor_2"


def test_pilot_run_synonym_matches_project_convention():
    requests = extract_io_assignment_requests("Usa Q8.2 como piloto de marcha.")
    assert requests[0]["functional_name_hint"] == "Q_Pilot_Run"


def test_pilot_stop_does_not_collide_with_generic_stop_synonym():
    requests = extract_io_assignment_requests("Usa Q8.3 como piloto de paro.")
    assert requests[0]["functional_name_hint"] == "Q_Pilot_Stop"


# ---------- Duplicados: una direccion no puede terminar con el nombre de otra ----------

def test_propose_assignment_blocks_duplicate_name_at_another_address():
    io_map = _sample_map()  # Q_Alarm ya existe en %QX8.1
    proposals = propose_assignment(io_map, [{"address": "%QX8.0", "functional_name_hint": "Q_Alarm"}])
    assert proposals[0]["blocked"] is True
    assert "ya esta en uso" in proposals[0]["reason"]


def test_propose_assignment_allows_swap_within_same_batch():
    io_map = _sample_map()
    proposals = propose_assignment(
        io_map,
        [
            {"address": "%QX8.0", "functional_name_hint": "Q_Alarm"},
            {"address": "%QX8.1", "functional_name_hint": "Q_Free1"}
        ]
    )
    assert all(not p["blocked"] for p in proposals)


# ---------- Alias: un renombrado debe quedar resoluble por comandos futuros ----------

def test_apply_assignments_adds_role_text_as_alias():
    io_map = _sample_map()
    requests = extract_io_assignment_requests("Usa Q8.0 para el motor 1.")
    proposals = propose_assignment(io_map, requests)
    updated_map, _ = apply_assignments(io_map, proposals)
    variable = next(v for v in updated_map["variables"] if v["location"] == "%QX8.0")
    assert "motor 1" in variable.get("aliases", [])


# ---------- validate_manual_rename (editor "Mapa I/O completo") ----------

def test_manual_rename_valid_case():
    io_map = _sample_map()
    result = validate_manual_rename(io_map, "%QX8.0", "Q_Motor_1")
    assert result["valid"] is True


def test_manual_rename_rejects_locked():
    io_map = _sample_map()
    result = validate_manual_rename(io_map, "%IX16.0", "I_Reverse")
    assert result["valid"] is False
    assert any("bloqueada" in error for error in result["errors"])


def test_manual_rename_rejects_bad_prefix():
    io_map = _sample_map()
    result = validate_manual_rename(io_map, "%QX8.0", "MotorTwo")
    assert result["valid"] is False


def test_manual_rename_rejects_wrong_direction():
    io_map = _sample_map()
    result = validate_manual_rename(io_map, "%QX8.0", "I_Something")
    assert result["valid"] is False


def test_manual_rename_rejects_duplicate():
    io_map = _sample_map()
    result = validate_manual_rename(io_map, "%QX8.0", "Q_Alarm")
    assert result["valid"] is False
    assert any("ya esta en uso" in error for error in result["errors"])


# ---------- Reutilizacion semantica de variables LOCKED/ASSIGNED (no solo string equality) -----

@pytest.mark.parametrize("role_text,expected_reused_name", [
    ("boton de inicio", "I_Start"),
    ("pulsante de inicio", "I_Start"),
    ("pulsador de arranque", "I_Start"),
    ("arranque", "I_Start"),
    ("start", "I_Start"),
    ("boton de paro", "I_Stop"),
    ("pulsante de paro", "I_Stop"),
    ("stop", "I_Stop"),
    ("detener", "I_Stop"),
])
def test_locked_reused_by_semantic_role_not_literal_name(role_text, expected_reused_name):
    """Caso A del pedido: LOCKED significa "esta funcion esta fija aqui", no "canal ocupado" - si
    la funcion solicitada coincide semanticamente (distintas redacciones de la misma idea), se
    reutiliza el recurso LOCKED existente tal cual, sin crear un recurso nuevo redundante."""
    io_map = _sample_map()
    proposals = propose_assignment(
        io_map, [{"functional_name_hint": f"I_Something_{role_text}", "role_text": role_text}]
    )
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["blocked"] is False
    assert proposal["proposed_name"] == expected_reused_name
    assert proposal["current_name"] == expected_reused_name
    assert proposal["current_state"] == STATE_LOCKED
    assert proposal.get("semantic_reuse") is True


def test_locked_semantic_reuse_never_creates_a_new_channel():
    io_map = _sample_map()
    before_count = len(io_map["variables"])
    proposals = propose_assignment(
        io_map, [{"functional_name_hint": "I_Boton_Inicio", "role_text": "boton de inicio"}]
    )
    updated_map, _ = apply_assignments(io_map, proposals)
    assert len(updated_map["variables"]) == before_count
    # I_Start sigue exactamente igual - LOCKED nunca se renombra.
    start = next(v for v in updated_map["variables"] if v["location"] == "%IX16.0")
    assert start["name"] == "I_Start"
    assert start["state"] == STATE_LOCKED


def test_qualified_role_with_a_number_never_collapses_onto_a_general_locked_resource():
    """Caso B/C del pedido: "arranque motor 2" NO es la misma funcion que "arranque" general,
    aunque contenga esa palabra como subcadena - debe permanecer distinta y recibir un canal
    propio, nunca reutilizar I_Start."""
    io_map = _sample_map()
    proposals = propose_assignment(
        io_map, [{"functional_name_hint": "I_Start_Motor_2", "role_text": "arranque motor 2"}]
    )
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.get("semantic_reuse") is None
    assert proposal["proposed_name"] == "I_Start_Motor_2"
    assert proposal["current_state"] == STATE_FREE
    assert proposal["address"] != "%IX16.0"  # nunca I_Start


def test_bare_tag_name_hint_without_role_text_never_semantically_matched():
    """La coincidencia semantica SOLO se intenta con role_text en lenguaje natural explicito -
    nunca se deriva de un nombre de tag ya propuesto (p. ej. "I_Start_Motor_1" no debe coincidir
    con "Start" solo porque la subcadena aparece en el nombre)."""
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"functional_name_hint": "I_Start_Motor_1"}])
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.get("semantic_reuse") is None
    assert proposal["current_state"] == STATE_FREE


def test_assigned_reused_by_semantic_role_before_creating_a_new_resource():
    """Regla de decision del pedido: 1) LOCKED, 2) ASSIGNED, 3) solo si ninguno coincide, FREE."""
    io_map = _sample_map()
    # I_Reset (ASSIGNED) ya representa "reinicio" - una peticion equivalente debe reutilizarlo en
    # vez de reclamar el canal FREE disponible.
    for variable in io_map["variables"]:
        if variable["name"] == "I_Reset":
            variable["aliases"] = ["reinicio"]
    proposals = propose_assignment(
        io_map, [{"functional_name_hint": "I_Boton_Reinicio", "role_text": "boton de reinicio"}]
    )
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["proposed_name"] == "I_Reset"
    assert proposal["current_state"] == STATE_ASSIGNED
    assert proposal.get("semantic_reuse") is True


# ---------- Regression: batch deduplication for the SAME functional_name (real bug) ----------
# I_Start_Motor_2 was found duplicated at two different addresses in the real bench map after a
# command referenced the same role both implicitly (a parameter/recognized_tag value) and
# explicitly (a requested_io_assignments entry) in a single semantic_validator.py call that used
# to invoke propose_assignment() TWICE, each with its own independent claimed_in_batch - neither
# call could see what the other had already proposed. Fixed by (1) merging implicit+explicit
# requests into a single propose_assignment() call (semantic_validator.py) and (2) an explicit
# in-batch deduplication pass inside propose_assignment() itself so even two requests submitted
# together for the same name never resolve to two different free channels.

def test_same_functional_name_requested_twice_in_one_batch_collapses_to_one_address():
    io_map = _sample_map()
    requests = [
        {"functional_name_hint": "I_Start_Motor_2"},
        {"functional_name_hint": "I_Start_Motor_2"}
    ]
    proposals = propose_assignment(io_map, requests)
    assert len(proposals) == 2
    assert all(not p["blocked"] for p in proposals)
    addresses = {p["address"] for p in proposals}
    assert len(addresses) == 1, f"el mismo nombre funcional no debe resolver a dos direcciones: {proposals}"
    assert proposals[1].get("duplicate_request_collapsed") is True


def test_two_different_roles_still_get_two_distinct_addresses():
    """I_Start_Motor_1 e I_Start_Motor_2 son roles DISTINTOS - deben recibir dos DI distintas,
    la deduplicacion nunca debe colapsar nombres genuinamente diferentes."""
    io_map = _sample_map()
    requests = [
        {"functional_name_hint": "I_Start_Motor_1"},
        {"functional_name_hint": "I_Start_Motor_2"}
    ]
    proposals = propose_assignment(io_map, requests)
    assert len(proposals) == 2
    assert all(not p["blocked"] for p in proposals)
    names = [p["proposed_name"] for p in proposals]
    addresses = [p["address"] for p in proposals]
    assert names[0] != names[1]
    assert addresses[0] != addresses[1]
    assert not any(p.get("duplicate_request_collapsed") for p in proposals)


def test_apply_assignments_refuses_a_batch_that_would_duplicate_a_name():
    """Ultima linea de defensa transaccional (seccion 9): si un llamador construye
    confirmed_proposals a mano (sin pasar por propose_assignment) y el resultado violaria la
    invariante de nombre unico, apply_assignments debe rechazar TODO el lote antes de persistir -
    nunca dejar el mapa parcialmente corrupto."""
    io_map = _sample_map()
    bad_proposals = [
        {"address": "%IX16.2", "proposed_name": "I_Duplicated", "blocked": False, "address_was_explicit": True},
        {"address": "%QX8.0", "proposed_name": "I_Duplicated", "blocked": False, "address_was_explicit": True}
    ]
    with pytest.raises(ValueError, match="duplicados"):
        apply_assignments(io_map, bad_proposals)
    # El mapa original nunca se muta (apply_assignments trabaja sobre una copia) y la excepcion
    # se lanza ANTES de devolver nada.
    names = [v["name"] for v in io_map["variables"]]
    assert names.count("I_Duplicated") == 0


def test_real_world_two_motor_command_never_duplicates_the_second_start_button(tmp_path):
    """
    Reproduccion directa del bug real reportado: un comando que menciona el boton de arranque del
    motor 2 tanto de forma implicita (referenciado en functional_requirements/parameters) como
    explicita (una entrada de requested_io_assignments con el mismo functional_name_hint) no debe
    terminar con "I_Start_Motor_2" en dos direcciones activas.
    """
    io_map = _sample_map()
    implicit_like = [{"functional_name_hint": "I_Start_Motor_2", "role_text": "arranque motor 2"}]
    explicit_like = [{"functional_name_hint": "I_Start_Motor_2", "role_text": "arranque motor 2"}]
    combined_requests = implicit_like + explicit_like

    proposals = propose_assignment(io_map, combined_requests)
    to_apply = [p for p in proposals if not p["blocked"]]
    updated_map, history_entries = apply_assignments(io_map, to_apply)

    names = [v["name"] for v in updated_map["variables"]]
    assert names.count("I_Start_Motor_2") == 1
