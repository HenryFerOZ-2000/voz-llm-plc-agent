"""
Tests for the shape-normalization/repair layer (src/semantic_repair.py) added to close a real bug:
a compound command (N independent motors) could get an intent the LLM chose correctly, with every
tag it needed already present, but nested under a shape (a list of per-motor dicts, a
{output: trigger} dict) the chosen intent's fixed codegen template does not read - and got
rejected as "missing required parameters" even though the information was there, just shaped
differently. This module only fills recognized canonical keys from data unambiguously already
present - it never invents a tag, never fabricates a functional_requirement, and never touches a
key the caller already set directly.
"""
from __future__ import annotations

from typing import Any

from semantic_repair import repair_semantic_output, strip_unavailable_emergency_reference
from semantic_validator import INTENT_PARAMETER_RULES


def _base_output(intent_id: str, parameters: dict[str, Any], recognized_tags: list[str]) -> dict[str, Any]:
    return {
        "intent_id": intent_id,
        "case_id": None,
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
        "functional_requirements": []
    }


# ---------- 1. LLM output con schema alternativo pero semantica completa -> normaliza ----------

def test_motor_controls_list_shape_is_normalized_to_canonical_keys():
    """"motor_controls": [{"trigger_input":..., "motor_output":...}, ...] en vez de las claves
    planas - la informacion ya esta, solo anidada distinto."""
    semantic_output = _base_output(
        "INT_MOTOR_LATCH",
        {
            "process_enable_input": "I_Start",
            "stop_input": "I_Stop",
            "motor_controls": [
                {"trigger_input": "I_Start_Motor_1", "motor_output": "Q_Motor_1"},
                {"trigger_input": "I_Start_Motor_2", "motor_output": "Q_Motor_2"}
            ]
        },
        ["I_Start", "I_Stop", "I_Start_Motor_1", "I_Start_Motor_2", "Q_Motor_1", "Q_Motor_2"]
    )
    # INT_MOTOR_LATCH no tiene entrada en INTENT_PARAMETER_RULES, asi que se fuerza el chequeo
    # como si "trigger_input"/"motor_output"/"run_latch" fueran requeridos, igual que hace su
    # codegen real (_generate_motor_latch_body) - ver _INTENT_EXTRA_BASE_SLOTS.
    rules = dict(INTENT_PARAMETER_RULES)
    rules["INT_MOTOR_LATCH"] = {"required": ["trigger_input", "stop_input", "motor_output", "run_latch"]}
    repaired = repair_semantic_output(semantic_output, rules)
    assert repaired["parameters"]["trigger_input"] == "I_Start"
    assert repaired["parameters"]["motor_output"] == "Q_Motor_1"
    assert repaired["parameters"]["run_latch"] == "M_RunLatch"
    # el shape original se conserva (functional_requirements/otros consumidores pueden seguir
    # leyendolo) - solo se agregan las claves canonicas faltantes.
    assert "motor_controls" in repaired["parameters"]


def test_output_to_trigger_dict_shape_is_normalized():
    """"motor_start_inputs": {"Q_Motor_1": "I_Start_Motor_1", ...} - la clave es la salida, el
    valor es el disparador; ambos ya son tags IEC validos."""
    semantic_output = _base_output(
        "INT_MOTOR_START_STOP",
        {
            "process_start_input": "I_Start",
            "stop_input": "I_Stop",
            "emergency_input": "I_Emergency",
            "motor_start_inputs": {"Q_Motor_1": "I_Start_Motor_1", "Q_Motor_2": "I_Start_Motor_2"},
            "motor_outputs": ["Q_Motor_1", "Q_Motor_2"]
        },
        ["I_Start", "I_Stop", "I_Emergency", "I_Start_Motor_1", "I_Start_Motor_2", "Q_Motor_1", "Q_Motor_2"]
    )
    repaired = repair_semantic_output(semantic_output, INTENT_PARAMETER_RULES)
    assert repaired["parameters"]["trigger_input"] == "I_Start"
    assert repaired["parameters"]["motor_output"] == "Q_Motor_1"
    assert repaired["parameters"]["run_latch"] == "M_RunLatch"


def test_repair_never_overwrites_a_key_the_caller_already_set():
    semantic_output = _base_output(
        "INT_MOTOR_START_STOP",
        {
            "trigger_input": "I_Start_Explicit", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
            "motor_output": "Q_Explicit", "run_latch": "M_RunLatch",
            "motor_controls": [{"trigger_input": "I_Other", "motor_output": "Q_Other"}]
        },
        []
    )
    repaired = repair_semantic_output(semantic_output, INTENT_PARAMETER_RULES)
    # nada faltaba - no se toca absolutamente nada, ni siquiera para "mejorar" con el shape extra.
    assert repaired is semantic_output


def test_repair_does_nothing_when_information_is_genuinely_absent():
    """
    Seccion 5 del pedido: no confundir "shape distinto" con "informacion ausente" - si no hay
    ningun actor/trigger reconocible en ninguna parte de `parameters`, el repair NUNCA inventa un
    tag para trigger_input/motor_output y esos siguen faltando (la validacion normal los seguira
    reportando). `run_latch` es la unica excepcion legitima: no es informacion "ausente", es
    siempre el mismo recurso interno fijo (M_RunLatch) sin importar el resto del comando.
    """
    semantic_output = _base_output(
        "INT_MOTOR_START_STOP",
        {"stop_input": "I_Stop", "emergency_input": "I_Emergency"},
        ["I_Stop", "I_Emergency"]
    )
    repaired = repair_semantic_output(semantic_output, INTENT_PARAMETER_RULES)
    assert "trigger_input" not in repaired["parameters"]
    assert "motor_output" not in repaired["parameters"]
    assert repaired["parameters"]["run_latch"] == "M_RunLatch"


def test_repair_is_idempotent():
    semantic_output = _base_output(
        "INT_MOTOR_START_STOP",
        {
            "process_start_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
            "motor_start_inputs": {"Q_Motor_1": "I_Start_Motor_1"}
        },
        []
    )
    once = repair_semantic_output(semantic_output, INTENT_PARAMETER_RULES)
    twice = repair_semantic_output(once, INTENT_PARAMETER_RULES)
    assert twice is once


# ---------- 2. Tres motores no falla por trigger_input/motor_output/run_latch ----------

def test_three_motor_alternate_shape_no_longer_missing_base_parameters():
    semantic_output = _base_output(
        "INT_MOTOR_START_STOP",
        {
            "process_start_input": "I_Start",
            "motor_start_inputs": {
                "Q_Motor_1": "I_Start_Motor_1", "Q_Motor_2": "I_Start_Motor_2", "Q_Motor_3": "I_Start_Motor_3"
            },
            "stop_input": "I_Stop",
            "emergency_input": "I_Emergency",
            "motor_outputs": ["Q_Motor_1", "Q_Motor_2", "Q_Motor_3"]
        },
        []
    )
    repaired = repair_semantic_output(semantic_output, INTENT_PARAMETER_RULES)
    required = set(INTENT_PARAMETER_RULES["INT_MOTOR_START_STOP"]["required"])
    missing = required - set(repaired["parameters"])
    assert missing == set()


# ---------- INT_MUTUAL_INTERLOCK: contactor_a/contactor_b desde actor records ----------

def test_mutual_interlock_contactor_slots_filled_from_actor_records():
    """INT_MUTUAL_INTERLOCK no tiene entrada "required" en INTENT_PARAMETER_RULES (su codegen
    solo aplica un default silencioso) - por eso sus slots base se listan explicitamente en
    _INTENT_EXTRA_BASE_SLOTS, para no dejar que ese default silencioso genere logica incorrecta
    sin que nadie lo note."""
    semantic_output = _base_output(
        "INT_MUTUAL_INTERLOCK",
        {
            "motor_controls": [
                {"trigger_input": "I_Start_Motor_1", "motor_output": "Q_Motor_1"},
                {"trigger_input": "I_Start_Motor_2", "motor_output": "Q_Motor_2"}
            ]
        },
        []
    )
    repaired = repair_semantic_output(semantic_output, INTENT_PARAMETER_RULES)
    assert repaired["parameters"]["contactor_a"] == "Q_Motor_1"
    assert repaired["parameters"]["contactor_b"] == "Q_Motor_2"
    assert repaired["parameters"]["trigger_input"] == "I_Start_Motor_1"


# ---------- I_Emergency: nunca autocrearla, nunca exigirla si el banco no la tiene ----------

def _map_without_emergency() -> dict[str, Any]:
    return {"variables": [{"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX16.0"}]}


def _map_with_emergency() -> dict[str, Any]:
    return {"variables": [{"name": "I_Emergency", "class": "input", "type": "BOOL", "location": "%IX16.2"}]}


def test_emergency_reference_stripped_when_bench_has_no_i_emergency():
    """
    "emergency_input" queda PRESENTE con el valor "FALSE" (nunca se BORRA la clave) - borrarla
    reactivaria el default hardcodeado "I_Emergency" en ir_builder.py::get_required_variables_for_intent
    (`parameters.get("emergency_input", "I_Emergency")`), que es exactamente el bug real que este
    modulo debe evitar: I_Emergency reapareciendo en required_variables/SCL despues de la
    "reparacion". "FALSE" es el literal booleano IEC correcto para "sin senal fisica que probar".
    """
    semantic_output = _base_output(
        "INT_MOTOR_START_STOP",
        {"trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency", "motor_output": "Q_Motor_1"},
        ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_1"]
    )
    repaired = strip_unavailable_emergency_reference(semantic_output, _map_without_emergency())
    assert repaired["parameters"]["emergency_input"] == "FALSE"
    assert "I_Emergency" not in repaired["recognized_tags"]
    assert repaired["parameters"]["trigger_input"] == "I_Start"  # el resto queda intacto


def test_emergency_reference_untouched_when_bench_has_i_emergency():
    semantic_output = _base_output(
        "INT_MOTOR_START_STOP",
        {"trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency", "motor_output": "Q_Motor_1"},
        ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_1"]
    )
    repaired = strip_unavailable_emergency_reference(semantic_output, _map_with_emergency())
    assert repaired is semantic_output  # no-op: el banco si tiene I_Emergency


def test_emergency_input_absent_entirely_is_also_filled_with_false():
    """
    Bug real encontrado en produccion: cuando el LLM sigue correctamente la instruccion del
    prompt de OMITIR emergency_input por completo (en vez de incluir el valor "I_Emergency"),
    "emergency_input" nunca aparecia en `parameters` - no habia ningun valor "I_Emergency" que
    sustituir, asi que la version anterior de esta funcion no hacia nada. Pero
    ir_builder.get_required_variables_for_intent Y cada template de code_generator.py leen
    `parameters.get("emergency_input", "I_Emergency")` - una clave AUSENTE dispara exactamente el
    mismo default hardcodeado que un valor "I_Emergency" explicito. Por eso una clave ausente debe
    tratarse igual: se rellena con "FALSE".
    """
    semantic_output = _base_output(
        "INT_MOTOR_START_STOP",
        {"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_1"},
        ["I_Start", "I_Stop", "Q_Motor_1"]
    )
    repaired = strip_unavailable_emergency_reference(semantic_output, _map_without_emergency())
    assert repaired is not semantic_output
    assert repaired["parameters"]["emergency_input"] == "FALSE"
    assert repaired["parameters"]["trigger_input"] == "I_Start"  # el resto queda intacto


def test_emergency_input_absent_stays_absent_when_bench_has_i_emergency():
    semantic_output = _base_output(
        "INT_MOTOR_START_STOP",
        {"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_1"},
        ["I_Start", "I_Stop", "Q_Motor_1"]
    )
    repaired = strip_unavailable_emergency_reference(semantic_output, _map_with_emergency())
    assert repaired is semantic_output
    assert "emergency_input" not in repaired["parameters"]
