from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from code_generator import generate_implementation_from_ir
from functional_requirements import (
    compute_semantic_coverage,
    detect_functional_requirement_conflicts,
    merge_interlock_requirements,
    normalize_interlock_requirement
)
from ir_builder import build_project_ir
from llm_parser import parse_with_mode
from project_packager import generate_project_package
from schemas import LLMUsageMetadata, validate_semantic_model
from semantic_validator import validate_semantic_output
from verifier import verify_project_ir


REAL_COMMAND = (
    "Enciende un motor con un pulsante de inicio, que este se mantenga encendido junto con una "
    "luz piloto, quiero un pulsante de paro, y cuando presione paro el motor se detendra a los 3 "
    "segundos y se encendera la luz de paro."
)


def _minimal_map(io_map: dict, names: set[str]) -> dict:
    return {
        "naming_convention": io_map.get("naming_convention", {}),
        "variables": [v for v in io_map.get("variables", []) if v.get("name") in names]
    }


def _map_with_pilot_stop(io_map: dict, names: set[str]) -> dict:
    """config/io_map.json has no Q_Pilot_Stop; append one matching the real project's shape
    (data/plc_maps/mapa_simulacion_completo.json) instead of depending on that file directly."""
    base = _minimal_map(io_map, names)
    if "Q_Pilot_Stop" in names:
        base["variables"].append(
            {
                "name": "Q_Pilot_Stop", "class": "output", "type": "BOOL", "location": "%QX0.7",
                "initial_value": "FALSE", "description": "Piloto luminoso de detenido."
            }
        )
    return base


def _semantic_output(intent_id: str, parameters: dict, recognized_tags: list[str], functional_requirements=None) -> dict:
    return {
        "intent_id": intent_id,
        "case_id": "TEST",
        "command_text": "comando de prueba",
        "normalized_command": "comando de prueba",
        "parameters": parameters,
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": recognized_tags,
        "unrecognized_terms": [],
        "functional_requirements": functional_requirements or []
    }


DELAYED_STOP_PARAMS = {
    "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
    "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch",
    "stop_delay_active": "M_StopDelayActive", "timer": "T_StopDelay", "stop_delay_time": "T#3s"
}
DELAYED_STOP_BASE_TAGS = {"I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"}


# A. comando simple sigue funcionando (sin functional_requirements) -----------------------------

def test_simple_command_without_functional_requirements_still_works(io_map: dict) -> None:
    minimal_map = _minimal_map(io_map, {"I_Start", "I_Stop", "I_Emergency", "I_Reset", "Q_Motor_Enable", "Q_Alarm", "Q_Pilot_Run", "Q_Pilot_Fault"})
    semantic_output = _semantic_output(
        "INT_MOTOR_START_STOP",
        {"trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency", "reset_input": "I_Reset", "motor_output": "Q_Motor_Enable"},
        ["I_Start", "I_Stop", "I_Emergency", "I_Reset", "Q_Motor_Enable"]
    )
    project_ir = build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")
    assert project_ir.metadata["functional_requirements"] == []
    code = generate_implementation_from_ir(project_ir)
    # INT_MOTOR_START_STOP ya trae Q_Pilot_Run en su propia plantilla; lo que debe estar AUSENTE
    # es el bloque compositivo de functional_requirements (no se pidio ninguno).
    assert "Requisitos funcionales adicionales" not in code


# B. delayed stop simple -------------------------------------------------------------------------

def test_delayed_stop_simple_without_extras(io_map: dict) -> None:
    minimal_map = _minimal_map(io_map, DELAYED_STOP_BASE_TAGS)
    semantic_output = _semantic_output("INT_DELAYED_STOP", DELAYED_STOP_PARAMS, list(DELAYED_STOP_BASE_TAGS))
    project_ir = build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")
    variable_names = {v.name for v in project_ir.pou.variables}
    assert {"M_RunLatch", "M_StopDelayActive", "T_StopDelay"} <= variable_names


# C. delayed stop + run pilot ---------------------------------------------------------------------

def test_delayed_stop_plus_run_pilot(io_map: dict) -> None:
    names = DELAYED_STOP_BASE_TAGS | {"Q_Pilot_Run"}
    minimal_map = _minimal_map(io_map, names)
    semantic_output = _semantic_output(
        "INT_DELAYED_STOP", DELAYED_STOP_PARAMS, list(DELAYED_STOP_BASE_TAGS),
        functional_requirements=[{"type": "run_pilot"}]
    )
    project_ir = build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")
    variable_names = {v.name for v in project_ir.pou.variables}
    assert "Q_Pilot_Run" in variable_names
    code = generate_implementation_from_ir(project_ir)
    assert "Q_Pilot_Run := Q_Motor_Enable AND NOT I_Emergency;" in code


# D. delayed stop + run pilot + stop pilot (el comando real de regresion, a nivel IR) -------------

def test_delayed_stop_plus_run_and_stop_pilot(io_map: dict) -> None:
    names = DELAYED_STOP_BASE_TAGS | {"Q_Pilot_Run", "Q_Pilot_Stop"}
    full_map = _map_with_pilot_stop(io_map, names)
    semantic_output = _semantic_output(
        "INT_DELAYED_STOP", DELAYED_STOP_PARAMS, list(DELAYED_STOP_BASE_TAGS),
        functional_requirements=[{"type": "run_pilot"}, {"type": "stop_pilot"}]
    )
    project_ir = build_project_ir(semantic_output, full_map, "SIEMENS_SCL_V18")
    variable_names = {v.name for v in project_ir.pou.variables}
    assert {"Q_Pilot_Run", "Q_Pilot_Stop", "M_RunLatch", "M_StopDelayActive", "T_StopDelay"} <= variable_names
    code = generate_implementation_from_ir(project_ir)
    assert "Q_Pilot_Run :=" in code
    assert "Q_Pilot_Stop :=" in code
    # nada se perdio en silencio: los 3 comportamientos (latch+delay del intent, +2 pilotos) estan
    assert "T_StopDelay" in code and "M_StopDelayActive" in code


# E. start latch + pilot sobre OTRO intent base (no solo INT_DELAYED_STOP) ------------------------

def test_motor_latch_plus_run_pilot(io_map: dict) -> None:
    names = {"I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable", "Q_Pilot_Run"}
    minimal_map = _minimal_map(io_map, names)
    semantic_output = _semantic_output(
        "INT_MOTOR_LATCH",
        {"trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency", "motor_output": "Q_Motor_Enable"},
        ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"],
        functional_requirements=[{"type": "run_pilot"}]
    )
    project_ir = build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")
    assert "Q_Pilot_Run" in {v.name for v in project_ir.pou.variables}
    assert "Q_Pilot_Run :=" in generate_implementation_from_ir(project_ir)


# F. emergency + motor: emergency_priority no rompe nada (I_Emergency ya requerido en general) ----

def test_emergency_priority_type_is_recognized_and_harmless(io_map: dict) -> None:
    minimal_map = _minimal_map(io_map, DELAYED_STOP_BASE_TAGS)
    semantic_output = _semantic_output(
        "INT_DELAYED_STOP", DELAYED_STOP_PARAMS, list(DELAYED_STOP_BASE_TAGS),
        functional_requirements=[{"type": "emergency_priority"}]
    )
    project_ir = build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")
    assert "I_Emergency" in {v.name for v in project_ir.pou.variables}


# G. interlock + piloto ----------------------------------------------------------------------------

def test_interlock_plus_pilot(io_map: dict) -> None:
    names = {"I_Start", "I_Stop", "I_Emergency", "Q_Contactor_A", "Q_Contactor_B", "Q_Pilot_Run"}
    minimal_map = _minimal_map(io_map, names)
    semantic_output = _semantic_output(
        "INT_MUTUAL_INTERLOCK",
        {"trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency"},
        ["I_Start", "I_Stop", "I_Emergency"],
        functional_requirements=[
            {"type": "interlock", "output_a": "Q_Contactor_A", "output_b": "Q_Contactor_B"},
            {"type": "run_pilot"}
        ]
    )
    project_ir = build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")
    code = generate_implementation_from_ir(project_ir)
    assert "Q_Contactor_A := NOT Q_Contactor_B;" in code
    assert "Q_Pilot_Run :=" in code


# H. recurso interno autogenerado (delayed_stop como ADD-ON de un intent que no lo trae) ----------

def test_delayed_stop_as_add_on_autogenerates_internal_resources(io_map: dict) -> None:
    names = {"I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"}
    minimal_map = _minimal_map(io_map, names)
    semantic_output = _semantic_output(
        "INT_MOTOR_LATCH",
        {"trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency", "motor_output": "Q_Motor_Enable"},
        list(names),
        functional_requirements=[{"type": "delayed_stop", "delay": "T#3s"}]
    )
    project_ir = build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")
    generated_names = {v["name"] for v in project_ir.metadata["generated_internal_variables"]}
    assert {"M_StopDelayActive", "T_StopDelay"} <= generated_names
    # nunca se pidio autorizacion: el mapa base no tenia estos internos y no hizo falta agregarlos
    assert {v.get("name") for v in minimal_map["variables"]} == names


# I. recurso fisico inexistente ---------------------------------------------------------------------

def test_stop_pilot_missing_from_map_raises_instead_of_inventing(io_map: dict) -> None:
    minimal_map = _minimal_map(io_map, DELAYED_STOP_BASE_TAGS)  # sin Q_Pilot_Stop
    semantic_output = _semantic_output(
        "INT_DELAYED_STOP", DELAYED_STOP_PARAMS, list(DELAYED_STOP_BASE_TAGS),
        functional_requirements=[{"type": "stop_pilot"}]
    )
    with pytest.raises(ValueError, match="Q_Pilot_Stop"):
        build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")


# J. conflicto real genera clarification -------------------------------------------------------------

def test_conflicting_delayed_stop_delays_trigger_clarification(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    semantic_output = _semantic_output(
        "INT_DELAYED_STOP", DELAYED_STOP_PARAMS, list(DELAYED_STOP_BASE_TAGS),
        functional_requirements=[
            {"type": "delayed_stop", "delay": "T#3s"},
            {"type": "delayed_stop", "delay": "T#10s"}
        ]
    )
    result = validate_semantic_output(semantic_output, io_map, intents_catalog, safety_rules)
    assert result["requires_clarification"] is True
    assert result["functional_requirement_conflicts"]
    assert result["is_valid"] is False


# K. comando compuesto sin conflicto NO genera clarification -----------------------------------------

def test_composed_command_without_conflict_does_not_require_clarification(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    semantic_output = _semantic_output(
        "INT_DELAYED_STOP", DELAYED_STOP_PARAMS, list(DELAYED_STOP_BASE_TAGS),
        functional_requirements=[{"type": "run_pilot"}, {"type": "stop_pilot"}]
    )
    result = validate_semantic_output(semantic_output, io_map, intents_catalog, safety_rules)
    assert result["functional_requirement_conflicts"] == []
    assert result["requires_clarification"] is False


def test_duplicate_identical_requirement_is_not_a_conflict() -> None:
    conflicts = detect_functional_requirement_conflicts([{"type": "run_pilot"}, {"type": "run_pilot"}])
    assert conflicts == []


# L. normalizacion/fusion de interlock: orden de participantes, N-vias, conflicto real -------------

def _interlock(output_a: str, output_b: str, max_active: int | None = None) -> dict[str, Any]:
    entry = {"type": "interlock", "output_a": output_a, "output_b": output_b}
    if max_active is not None:
        entry["max_active"] = max_active
    return entry


def test_interlock_participant_order_is_not_a_conflict() -> None:
    """Caso 1: interlock(A,B) e interlock(B,A) son la MISMA exclusion mutua."""
    conflicts = detect_functional_requirement_conflicts(
        [_interlock("Q_Motor_1", "Q_Motor_2"), _interlock("Q_Motor_2", "Q_Motor_1")]
    )
    assert conflicts == []


def test_interlock_pairs_forming_n_way_exclusion_is_not_a_conflict() -> None:
    """Caso 2: los 3 pares posibles entre A/B/C representan una exclusion mutua de 3, no 3
    requisitos contradictorios entre si."""
    conflicts = detect_functional_requirement_conflicts([
        _interlock("Q_Motor_1", "Q_Motor_2"),
        _interlock("Q_Motor_1", "Q_Motor_3"),
        _interlock("Q_Motor_2", "Q_Motor_3")
    ])
    assert conflicts == []


def test_three_motor_command_does_not_require_clarification(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    """Caso 3: "Solo un motor puede estar encendido a la vez" para 3 motores nunca debe pedir
    aclaracion solo por traer 3 requisitos 'interlock' pareados entre si."""
    minimal_map = _minimal_map(io_map, {"I_Start", "I_Stop", "I_Emergency"})
    for name, location in (("Q_Motor_1", "%QX0.0"), ("Q_Motor_2", "%QX0.1"), ("Q_Motor_3", "%QX0.2")):
        minimal_map["variables"].append(
            {"name": name, "class": "output", "type": "BOOL", "location": location, "initial_value": "FALSE", "description": ""}
        )
    semantic_output = _semantic_output(
        "INT_UNKNOWN", {}, ["Q_Motor_1", "Q_Motor_2", "Q_Motor_3"],
        functional_requirements=[
            _interlock("Q_Motor_1", "Q_Motor_2"),
            _interlock("Q_Motor_1", "Q_Motor_3"),
            _interlock("Q_Motor_2", "Q_Motor_3")
        ]
    )
    result = validate_semantic_output(semantic_output, minimal_map, intents_catalog, safety_rules)
    assert result["requires_clarification"] is False
    assert result["functional_requirement_conflicts"] == []


def test_interlock_merge_deduplicates_identical_pairs() -> None:
    """Caso 4: duplicados identicos se deduplican, no se mantienen dos veces."""
    merged = merge_interlock_requirements([_interlock("Q_Motor_1", "Q_Motor_2"), _interlock("Q_Motor_1", "Q_Motor_2")])
    assert merged == [{"type": "mutual_interlock", "participants": ["Q_Motor_1", "Q_Motor_2"], "max_active": 1}]


def test_interlock_real_conflict_same_participants_different_max_active() -> None:
    """Ejemplo de conflicto real del pedido: mismos participantes, max_active distinto SI debe
    detectarse."""
    conflicts = detect_functional_requirement_conflicts([
        _interlock("Q_Motor_1", "Q_Motor_2", max_active=1),
        _interlock("Q_Motor_1", "Q_Motor_2", max_active=2)
    ])
    assert len(conflicts) == 1
    assert "max_active" in conflicts[0]["reason"]


def test_interlock_incomplete_pair_set_is_not_merged_into_a_wider_exclusion() -> None:
    """Solo A-B y A-C dados (nunca B-C): NO es un grafo completo, no debe fusionarse en una
    exclusion de 3 - eso prohibiria B+C simultaneos cuando el comando nunca lo dijo."""
    merged = merge_interlock_requirements([_interlock("A", "B"), _interlock("A", "C")])
    assert {"type": "mutual_interlock", "participants": ["A", "B"], "max_active": 1} in merged
    assert {"type": "mutual_interlock", "participants": ["A", "C"], "max_active": 1} in merged
    assert not any(len(entry["participants"]) == 3 for entry in merged)


def test_normalize_interlock_requirement_is_order_independent() -> None:
    assert normalize_interlock_requirement({"type": "interlock", "output_a": "A", "output_b": "B"}) == \
        normalize_interlock_requirement({"type": "interlock", "output_a": "B", "output_b": "A"})


# M. identidad del requisito (type + target): mismo type + parametros distintos NO es conflicto
# automatico si los targets (actores) son distintos - solo lo es cuando el target COINCIDE. -------

def _latch(target: str, enabled: bool | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": "motor_start_latch", "target": target}
    if enabled is not None:
        entry["enabled"] = enabled
    return entry


def _delayed_stop_for(target: str, delay: str) -> dict[str, Any]:
    return {"type": "delayed_stop", "target": target, "delay": delay}


def _run_pilot_for(target: str) -> dict[str, Any]:
    return {"type": "run_pilot", "target": target}


def test_motor_start_latch_for_two_distinct_motors_is_not_a_conflict() -> None:
    conflicts = detect_functional_requirement_conflicts([_latch("motor_1"), _latch("motor_2")])
    assert conflicts == []


def test_motor_start_latch_for_three_distinct_motors_is_not_a_conflict() -> None:
    conflicts = detect_functional_requirement_conflicts([_latch("motor_1"), _latch("motor_2"), _latch("motor_3")])
    assert conflicts == []


def test_motor_start_latch_same_target_different_params_is_a_real_conflict() -> None:
    conflicts = detect_functional_requirement_conflicts([_latch("motor_1", enabled=True), _latch("motor_1", enabled=False)])
    assert len(conflicts) == 1
    assert conflicts[0]["target"] == "motor_1"


def test_delayed_stop_for_distinct_motors_with_distinct_delays_is_not_a_conflict() -> None:
    """delayed_stop(motor_1, 3s) + delayed_stop(motor_2, 5s): retardos distintos para motores
    distintos, no una contradiccion sobre el mismo motor."""
    conflicts = detect_functional_requirement_conflicts(
        [_delayed_stop_for("motor_1", "T#3s"), _delayed_stop_for("motor_2", "T#5s")]
    )
    assert conflicts == []


def test_delayed_stop_same_motor_different_delay_is_a_real_conflict() -> None:
    conflicts = detect_functional_requirement_conflicts(
        [_delayed_stop_for("motor_1", "T#3s"), _delayed_stop_for("motor_1", "T#5s")]
    )
    assert len(conflicts) == 1
    assert conflicts[0]["target"] == "motor_1"


def test_run_pilot_for_distinct_motors_is_not_a_conflict() -> None:
    conflicts = detect_functional_requirement_conflicts([_run_pilot_for("motor_1"), _run_pilot_for("motor_2")])
    assert conflicts == []


def test_legacy_requirements_without_any_target_field_keep_old_behavior() -> None:
    """Compatibilidad hacia atras: un tipo GLOBAL/SINGLETON (o una interpretacion vieja sin
    `target`) que nunca declaro esa nocion sigue comparandose exactamente como antes - identico
    -> duplicado inofensivo, distinto -> conflicto real."""
    assert detect_functional_requirement_conflicts([{"type": "motor_start_latch"}, {"type": "motor_start_latch"}]) == []
    conflicts = detect_functional_requirement_conflicts(
        [{"type": "delayed_stop", "delay": "T#3s"}, {"type": "delayed_stop", "delay": "T#10s"}]
    )
    assert len(conflicts) == 1


def test_three_motor_command_with_latch_and_interlock_does_not_require_clarification(
    io_map: dict, intents_catalog: dict, safety_rules: dict
) -> None:
    """Caso 7 / criterio de exito: un programa de 3 motores con enclavamiento propio por motor
    (motor_start_latch por actor) MAS la exclusion mutua entre los tres (interlock) nunca debe
    pedir aclaracion."""
    minimal_map = _minimal_map(io_map, {"I_Start", "I_Stop", "I_Emergency"})
    for name, location in (("Q_Motor_1", "%QX0.0"), ("Q_Motor_2", "%QX0.1"), ("Q_Motor_3", "%QX0.2")):
        minimal_map["variables"].append(
            {"name": name, "class": "output", "type": "BOOL", "location": location, "initial_value": "FALSE", "description": ""}
        )
    semantic_output = _semantic_output(
        "INT_UNKNOWN", {}, ["Q_Motor_1", "Q_Motor_2", "Q_Motor_3"],
        functional_requirements=[
            _latch("Q_Motor_1"), _latch("Q_Motor_2"), _latch("Q_Motor_3"),
            _interlock("Q_Motor_1", "Q_Motor_2"), _interlock("Q_Motor_1", "Q_Motor_3"), _interlock("Q_Motor_2", "Q_Motor_3")
        ]
    )
    result = validate_semantic_output(semantic_output, minimal_map, intents_catalog, safety_rules)
    assert result["requires_clarification"] is False
    assert result["functional_requirement_conflicts"] == []


def test_valid_three_motor_interpretation_pipeline_continues_through_ir_scl_and_verification(
    io_map: dict, intents_catalog: dict, safety_rules: dict, tmp_path: Path
) -> None:
    """
    Criterio critico (seccion 9 del pedido sobre el bug de SEMANTIC_AMBIGUITY): no basta con que
    desaparezca la ventana de aclaracion - para una interpretacion realmente valida (parametros que
    SI coinciden con la plantilla de su intent, mas los 3 motores representados via
    functional_requirements) el pipeline debe continuar de verdad hasta IR -> SCL -> verificacion,
    no solo evitar el dialogo.
    """
    minimal_map = _minimal_map(io_map, {"I_Start", "I_Stop", "I_Emergency"})
    for name, location in (("Q_Motor_1", "%QX0.0"), ("Q_Motor_2", "%QX0.1"), ("Q_Motor_3", "%QX0.2")):
        minimal_map["variables"].append(
            {"name": name, "class": "output", "type": "BOOL", "location": location, "initial_value": "FALSE", "description": ""}
        )
    semantic_output = _semantic_output(
        "INT_MUTUAL_INTERLOCK",
        {
            "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
            "contactor_a": "Q_Motor_1", "contactor_b": "Q_Motor_2"
        },
        ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_1", "Q_Motor_2", "Q_Motor_3"],
        functional_requirements=[
            _latch("Q_Motor_1"), _latch("Q_Motor_2"), _latch("Q_Motor_3"),
            _interlock("Q_Motor_1", "Q_Motor_2"), _interlock("Q_Motor_1", "Q_Motor_3"), _interlock("Q_Motor_2", "Q_Motor_3")
        ]
    )
    validation = validate_semantic_output(semantic_output, minimal_map, intents_catalog, safety_rules)
    assert validation["is_valid"] is True
    assert validation["requires_clarification"] is False

    result = generate_project_package(
        semantic_output, "SIEMENS_SCL_V18", minimal_map, intents_catalog, safety_rules, output_dir=tmp_path
    )
    assert result["verification"]["is_valid"] is True
    ir_variable_names = {v["name"] for v in result["project_ir"]["pou"]["variables"]}
    # Cada motor_start_latch con `target` propio recibe su PROPIA memoria de enclavamiento
    # (M_Motor_XLatch), no una "M_RunLatch" generica compartida entre los tres actores - eso
    # colapsaria el estado independiente de cada motor en un solo bit (bug real corregido:
    # ir_builder/functional_requirements.get_functional_requirement_tags ahora deriva el nombre
    # del `target` de cada instancia).
    assert {
        "Q_Motor_1", "Q_Motor_2", "Q_Motor_3", "M_Motor_1Latch", "M_Motor_2Latch", "M_Motor_3Latch"
    } <= ir_variable_names
    assert "M_RunLatch" not in ir_variable_names


# Section 6: compute_semantic_coverage ----------------------------------------------------------------

def test_coverage_flags_missing_type_not_silently_dropped(intents_catalog: dict) -> None:
    coverage = compute_semantic_coverage(
        command_text=REAL_COMMAND, intent_id="INT_DELAYED_STOP",
        functional_requirements=[], intents_catalog=intents_catalog
    )
    assert coverage["complete"] is False
    assert "run_pilot" in coverage["missing_types"]
    assert "stop_pilot" in coverage["missing_types"]
    # delayed_stop y motor_start_latch SI los cubre INT_DELAYED_STOP por si mismo
    assert "delayed_stop" in coverage["covered_by_intent"]
    assert "motor_start_latch" in coverage["covered_by_intent"]


def test_coverage_complete_when_requirements_declared_explicitly(intents_catalog: dict) -> None:
    coverage = compute_semantic_coverage(
        command_text=REAL_COMMAND, intent_id="INT_DELAYED_STOP",
        functional_requirements=[{"type": "run_pilot"}, {"type": "stop_pilot"}],
        intents_catalog=intents_catalog
    )
    assert coverage["complete"] is True


# Fake LLM client for deterministic, offline retry tests (L, M, N) ------------------------------------

class _FakeLLMClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = payloads
        self.call_count = 0

    def is_configured(self) -> bool:
        return True

    def interpret_command(self, command_text: str, context: dict[str, Any]):
        payload = self._payloads[min(self.call_count, len(self._payloads) - 1)]
        self.call_count += 1
        model = validate_semantic_model({**payload, "command_text": command_text})
        usage = LLMUsageMetadata(provider="fake", model="fake-model")
        return model, usage


def _incomplete_first_pass() -> dict[str, Any]:
    return {
        "intent_id": "INT_DELAYED_STOP", "case_id": None, "normalized_command": REAL_COMMAND.lower(),
        "parameters": DELAYED_STOP_PARAMS, "confidence": 0.95, "ambiguities": [],
        "requires_clarification": False, "clarification_question": None, "assumptions": [],
        "recognized_tags": list(DELAYED_STOP_BASE_TAGS), "unrecognized_terms": [],
        "functional_requirements": []  # omite run_pilot/stop_pilot -> cobertura incompleta
    }


def _complete_second_pass() -> dict[str, Any]:
    payload = _incomplete_first_pass()
    payload["functional_requirements"] = [{"type": "run_pilot"}, {"type": "stop_pilot"}]
    payload["recognized_tags"] = list(DELAYED_STOP_BASE_TAGS) + ["Q_Pilot_Run", "Q_Pilot_Stop"]
    return payload


# L + M. cobertura incompleta dispara segunda pasada, y si esta la resuelve, el resultado la usa ------

def test_incomplete_coverage_triggers_one_retry_that_resolves(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    full_map = _map_with_pilot_stop(io_map, DELAYED_STOP_BASE_TAGS | {"Q_Pilot_Run", "Q_Pilot_Stop"})
    fake_client = _FakeLLMClient([_incomplete_first_pass(), _complete_second_pass()])

    result = parse_with_mode(
        REAL_COMMAND, mode="llm", io_map=full_map, intents_catalog=intents_catalog,
        safety_rules=safety_rules, llm_client=fake_client
    )

    assert fake_client.call_count == 2  # una sola segunda pasada, no un bucle
    assert result["reason_for_retry"] is not None and "semantic_coverage_incomplete" in result["reason_for_retry"]
    assert result["first_pass_interpretation"]["functional_requirements"] == []
    assert result["second_pass_interpretation"]["functional_requirements"] != []
    assert {r["type"] for r in result["functional_requirements"]} == {"run_pilot", "stop_pilot"}
    assert result["intent_id"] != "INT_UNKNOWN"
    assert result["semantic_validation"]["is_valid"] is True
    assert result["requires_clarification"] is False


# N. segunda pasada tambien incompleta: no reintenta una tercera vez, se conserva la primera --------

def test_second_pass_also_incomplete_does_not_loop_and_keeps_first_pass(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    minimal_map = _minimal_map(io_map, DELAYED_STOP_BASE_TAGS)
    fake_client = _FakeLLMClient([_incomplete_first_pass(), _incomplete_first_pass()])

    result = parse_with_mode(
        REAL_COMMAND, mode="llm", io_map=minimal_map, intents_catalog=intents_catalog,
        safety_rules=safety_rules, llm_client=fake_client
    )

    assert fake_client.call_count == 2  # exactamente un reintento, nunca un tercero
    assert result["reason_for_retry"] is not None
    assert result["intent_id"] == "INT_DELAYED_STOP"  # se conserva la primera pasada (valida en si misma)
    assert result["functional_requirements"] == []


# O. el comando real de regresion: no se pierden requisitos silenciosamente (verificado a nivel IR) --

def test_real_command_full_pipeline_with_injected_complete_interpretation(io_map: dict) -> None:
    """
    Regresion del bug original: con una interpretacion COMPLETA (como la que ahora produce el
    prompt actualizado / una segunda pasada exitosa), el comando real termina en IR + SCL con
    los 3 comportamientos representados, sin recurrir al LLM real en el test.
    """
    full_map = _map_with_pilot_stop(io_map, DELAYED_STOP_BASE_TAGS | {"Q_Pilot_Run", "Q_Pilot_Stop"})
    semantic_output = {**_complete_second_pass(), "command_text": REAL_COMMAND, "case_id": None}

    project_ir = build_project_ir(semantic_output, full_map, "SIEMENS_SCL_V18")
    code = generate_implementation_from_ir(project_ir)

    assert project_ir.intent_id == "INT_DELAYED_STOP"
    assert "T_StopDelay" in code
    assert "Q_Pilot_Run :=" in code
    assert "Q_Pilot_Stop :=" in code


# Seccion 8 (integracion completa): semantic_output -> generate_project_package -> siemens_source.scl
# Verifica el paquete Siemens REAL (FB interface + llamada OB), no solo la IR/el cuerpo ST. -----------

def test_real_command_full_package_propagates_pilots_to_fb_interface_and_ob_call(
    io_map: dict, intents_catalog: dict, safety_rules: dict, tmp_path: Path
) -> None:
    full_map = _map_with_pilot_stop(io_map, DELAYED_STOP_BASE_TAGS | {"Q_Pilot_Run", "Q_Pilot_Stop"})
    semantic_output = {**_complete_second_pass(), "command_text": REAL_COMMAND, "case_id": None}

    result = generate_project_package(
        semantic_output, "SIEMENS_SCL_V18", full_map, intents_catalog, safety_rules, output_dir=tmp_path
    )
    assert result["verification"]["is_valid"] is True

    package_dir = Path(result["package_dir"])
    scl = (package_dir / "siemens_source.scl").read_text(encoding="utf-8")
    variables = {v["name"] for v in json.loads((package_dir / "variables.json").read_text(encoding="utf-8"))}

    # 1. semantic_output.functional_requirements
    assert {r["type"] for r in semantic_output["functional_requirements"]} == {"run_pilot", "stop_pilot"}
    # 2. PLCProjectIR variables
    project_ir_dict = result["project_ir"]
    ir_variable_names = {v["name"] for v in project_ir_dict["pou"]["variables"]}
    assert {"Q_Pilot_Run", "Q_Pilot_Stop", "T_StopDelay"} <= ir_variable_names
    # 3. variables.json
    assert {"Q_Pilot_Run", "Q_Pilot_Stop"} <= variables
    # 4. VAR_OUTPUT del FB generado (no en VAR interno, y no como VAR_INPUT)
    var_output_block = scl.split("VAR_OUTPUT")[1].split("END_VAR")[0]
    assert "Q_Pilot_Run" in var_output_block
    assert "Q_Pilot_Stop" in var_output_block
    internal_var_match = re.search(r"\nVAR\n(.*?)\nEND_VAR", scl, re.DOTALL)
    assert internal_var_match is not None
    var_internal_block = internal_var_match.group(1)
    assert "T_StopDelay" in var_internal_block and "M_RunLatch" in var_internal_block
    assert "Q_Pilot_Run" not in var_internal_block and "Q_Pilot_Stop" not in var_internal_block
    # 5. llamada de instancia desde el OB
    ob_call = scl.split("ORGANIZATION_BLOCK")[1]
    assert 'Q_Pilot_Run => "Q_Pilot_Run"' in ob_call
    assert 'Q_Pilot_Stop => "Q_Pilot_Stop"' in ob_call
    # los recursos internos NUNCA aparecen como conexion fisica en la llamada del OB (seccion 3)
    assert "M_RunLatch" not in ob_call
    assert "M_StopDelayActive" not in ob_call
    assert "T_StopDelay" not in ob_call

    # generate_project_package ya corre verify_project_ir internamente (ir_verification) y su
    # resultado se combina en result["verification"] - confirmado is_valid=True arriba, lo que ya
    # ejercita la salvaguarda de la seccion 7 (test_verifier_flags_... la prueba de forma aislada).


def test_missing_physical_pilot_fails_before_generation_not_after(
    io_map: dict, intents_catalog: dict, safety_rules: dict, tmp_path: Path
) -> None:
    """
    Negativo obligatorio (seccion 8): si Q_Pilot_Stop no existe en el mapa, debe fallar ANTES de
    generar/importar - nunca inventarlo ni producir un paquete incompleto en silencio.
    Aqui Q_Pilot_Stop esta en recognized_tags (como lo pondria un LLM real), asi que lo atrapa
    validate_semantic_output (capa 1: unauthorized_tags) antes de siquiera llegar a build_project_ir.
    """
    map_without_stop_pilot = _minimal_map(io_map, DELAYED_STOP_BASE_TAGS | {"Q_Pilot_Run"})
    semantic_output = {**_complete_second_pass(), "command_text": REAL_COMMAND, "case_id": None}

    result = generate_project_package(
        semantic_output, "SIEMENS_SCL_V18", map_without_stop_pilot, intents_catalog, safety_rules,
        output_dir=tmp_path
    )
    assert result["verification"]["is_valid"] is False
    assert any("Q_Pilot_Stop" in error for error in result["verification"]["errors"])
    # nada debe haberse escrito a disco: la falla ocurrio antes de guardar el paquete
    assert not any(tmp_path.rglob("siemens_source.scl"))


def test_missing_physical_pilot_not_caught_by_recognized_tags_still_blocked_by_ir_builder(io_map: dict) -> None:
    """
    Segunda capa de la misma regla: si por alguna razon Q_Pilot_Stop NO llega a estar en
    recognized_tags (p.ej. un parser por reglas incompleto) pero SI en functional_requirements,
    build_project_ir es quien lo bloquea - nunca se inventa el recurso fisico.
    """
    minimal_map = _minimal_map(io_map, DELAYED_STOP_BASE_TAGS | {"Q_Pilot_Run"})  # sin Q_Pilot_Stop
    semantic_output = _semantic_output(
        "INT_DELAYED_STOP", DELAYED_STOP_PARAMS, list(DELAYED_STOP_BASE_TAGS) + ["Q_Pilot_Run"],
        functional_requirements=[{"type": "run_pilot"}, {"type": "stop_pilot"}]
    )
    with pytest.raises(ValueError, match="Q_Pilot_Stop"):
        build_project_ir(semantic_output, minimal_map, "SIEMENS_SCL_V18")


def test_verifier_flags_functional_requirement_that_never_reached_the_ir() -> None:
    """
    Reproduce artificialmente una perdida de propagacion (construyendo una IR a mano en vez de
    usando build_project_ir) para confirmar que verify_project_ir la detecta como error, no como
    exito silencioso - esta es la salvaguarda pedida en la seccion 7.
    """
    from plc_ir import PLCPOU, PLCProjectIR, PLCTask, PLCVariable

    def _var(name: str, var_class: str) -> PLCVariable:
        return PLCVariable(
            name=name, data_type="BOOL", var_class=var_class, location=None,
            initial_value=None, description="", source="plc_map", is_standard_block=False
        )

    pou = PLCPOU(
        name="PLC_PRG", pou_type="PROGRAM", language="ST",
        variables=[
            _var("I_Start", "input"),
            _var("Q_Motor_Enable", "output")
            # Q_Pilot_Run "se perdio" deliberadamente para este test
        ],
        function_blocks=[], implementation_code="Q_Motor_Enable := I_Start;",
        comments=[]
    )
    project_ir = PLCProjectIR(
        project_name="TEST", target_platform="SIEMENS_SCL_V18", case_id="TEST", intent_id="INT_DIRECT_OUTPUT",
        command_text="test", pou=pou, task=PLCTask(name="MainTask", interval="T#100ms", priority=1, pou_name="PLC_PRG"),
        safety_rules=[], test_cases=[{"case": "basic"}],
        metadata={
            "required_variables": ["I_Start", "Q_Motor_Enable"],
            "authorized_variables": ["I_Start", "Q_Motor_Enable", "Q_Pilot_Run"],
            "functional_requirements": [{"type": "run_pilot"}]
        }
    )
    result = verify_project_ir(project_ir)
    assert result["is_valid"] is False
    assert any("run_pilot" in error and "Q_Pilot_Run" in error for error in result["errors"])
