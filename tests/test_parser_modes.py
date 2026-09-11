from __future__ import annotations

import pytest

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


def test_hybrid_mode_does_not_ask_for_clarification_on_a_bare_intent_id_mismatch(
    monkeypatch, io_map: dict, intents_catalog: dict, safety_rules: dict
) -> None:
    """
    Antes: rules=INT_MOTOR_START_STOP vs LLM=INT_DELAYED_START para el mismo comando forzaba
    requires_clarification=True solo por tener intent_id distinto. Eso ya no debe ocurrir - ambas
    interpretaciones son validas y no se contradicen funcionalmente (ningun functional_requirement
    en conflicto), asi que el hibrido debe resolver automaticamente comparando cobertura, sin
    preguntar.
    """
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
    assert result["requires_clarification"] is False
    assert result["intent_id"] != "INT_UNKNOWN"


def test_hybrid_mode_still_asks_for_clarification_on_a_real_functional_contradiction(
    monkeypatch, io_map: dict, intents_catalog: dict, safety_rules: dict
) -> None:
    """Una contradiccion REAL (mismo tipo de functional_requirement, parametros incompatibles -
    aqui inyectada a mano en la respuesta LLM para simular que reglas y LLM piden comportamientos
    opuestos) SI debe seguir generando una aclaracion."""
    monkeypatch.setenv("LLM_CONFIDENCE_THRESHOLD", "0.99")
    llm_response = {
        "intent_id": "INT_MOTOR_START_STOP",
        "case_id": None,
        "command_text": "Haz que el motor se encienda con Start y se apague con Stop",
        "normalized_command": "haz que el motor se enciende con start y se stop con stop",
        "parameters": {
            "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
            "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch"
        },
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"],
        "unrecognized_terms": [],
        "functional_requirements": [{"type": "delayed_start", "delay": "T#8s"}]
    }
    monkeypatch.setattr(
        "llm_parser.parse_command_rule_based",
        lambda command_text, alias_index=None: {
            "intent_id": "INT_MOTOR_START_STOP",
            "case_id": None,
            "command_text": command_text,
            "normalized_command": command_text.lower(),
            "parameters": {
                "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
                "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch"
            },
            "confidence": 0.95,
            "ambiguities": [],
            "requires_clarification": False,
            "clarification_question": None,
            "assumptions": [],
            "recognized_tags": ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"],
            "unrecognized_terms": [],
            "functional_requirements": [{"type": "delayed_start", "delay": "T#3s"}]
        }
    )
    result = parse_command(
        "Haz que el motor se encienda con Start y se apague con Stop",
        mode="hybrid",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules,
        llm_response_text=llm_response
    )
    assert result["requires_clarification"] is True
    assert result["intent_id"] == "INT_UNKNOWN"


def test_hybrid_mode_merges_complementary_functional_requirements(
    monkeypatch, io_map: dict, intents_catalog: dict, safety_rules: dict
) -> None:
    """Reglas detecta run_pilot, LLM detecta stop_pilot - ningun tipo se repite (sin
    contradiccion), asi que el resultado final debe traer AMBOS requisitos fusionados."""
    monkeypatch.setenv("LLM_CONFIDENCE_THRESHOLD", "0.99")
    monkeypatch.setattr(
        "llm_parser.parse_command_rule_based",
        lambda command_text, alias_index=None: {
            "intent_id": "INT_MOTOR_START_STOP",
            "case_id": None,
            "command_text": command_text,
            "normalized_command": command_text.lower(),
            "parameters": {
                "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
                "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch"
            },
            "confidence": 0.9,
            "ambiguities": [],
            "requires_clarification": False,
            "clarification_question": None,
            "assumptions": [],
            "recognized_tags": ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"],
            "unrecognized_terms": [],
            "functional_requirements": [{"type": "run_pilot"}]
        }
    )
    llm_response = {
        "intent_id": "INT_MOTOR_START_STOP",
        "case_id": None,
        "command_text": "Haz que el motor se encienda con Start y se apague con Stop",
        "normalized_command": "haz que el motor se enciende con start y se stop con stop",
        "parameters": {
            "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
            "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch"
        },
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"],
        "unrecognized_terms": [],
        "functional_requirements": [{"type": "stop_pilot"}]
    }
    result = parse_command(
        "Haz que el motor se encienda con Start y se apague con Stop",
        mode="hybrid",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules,
        llm_response_text=llm_response
    )
    assert result["requires_clarification"] is False
    types_present = {req["type"] for req in result.get("functional_requirements", [])}
    assert {"run_pilot", "stop_pilot"}.issubset(types_present)


def test_hybrid_mode_selects_the_higher_coverage_interpretation(
    monkeypatch, io_map: dict, intents_catalog: dict, safety_rules: dict
) -> None:
    """Si las reglas tienen MENOS cobertura (menos tags/requisitos, sin pasar su propia
    validacion) que el LLM, se debe usar el resultado del LLM - no al reves."""
    monkeypatch.setenv("LLM_CONFIDENCE_THRESHOLD", "0.99")
    monkeypatch.setattr(
        "llm_parser.parse_command_rule_based",
        lambda command_text, alias_index=None: {
            "intent_id": "INT_UNKNOWN",
            "case_id": None,
            "command_text": command_text,
            "normalized_command": command_text.lower(),
            "parameters": {},
            "confidence": 0.2,
            "ambiguities": [],
            "requires_clarification": False,
            "clarification_question": None,
            "assumptions": [],
            "recognized_tags": [],
            "unrecognized_terms": []
        }
    )
    llm_response = {
        "intent_id": "INT_MOTOR_START_STOP",
        "case_id": None,
        "command_text": "Haz que el motor se encienda con Start y se apague con Stop",
        "normalized_command": "haz que el motor se enciende con start y se stop con stop",
        "parameters": {
            "trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency",
            "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch"
        },
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"],
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
    assert result["requires_clarification"] is False
    assert result["intent_id"] == "INT_MOTOR_START_STOP"
    assert result["parser_mode_used"] == "llm"


# ---------- Compositional complexity forces LLM consultation even with high rule confidence ----------

REPORTED_COMPOSITIONAL_COMMAND = (
    "Quiero encender mi proceso con un pulsante de inicio. Cuando el proceso esté iniciado, se "
    "puede presionar el pulsante 1 o el pulsante 2 para encender el motor 1 o el motor 2 "
    "respectivamente. Los motores no pueden encenderse al mismo tiempo; si se enciende uno, se "
    "apaga el otro y viceversa. Todo el proceso se apagará con el botón de paro."
)


def _variable(name, location, state, var_class="input", var_type="BOOL"):
    return {
        "name": name, "class": var_class, "type": var_type, "location": location,
        "initial_value": "FALSE", "description": "", "state": state, "llm_allowed": True
    }


def _bench_map_with_free_capacity() -> dict:
    """
    Mapa "moderno" (state explicito) con canales FREE disponibles para que el IOAllocator pueda
    resolver los tags nuevos que propone el LLM (I_Start_Motor_1/2, Q_Motor_1/2). El fixture
    `io_map` compartido (config/io_map.json) no sirve para este caso: no tiene campo `state` en
    ninguna variable, asi que DEFAULT_STATE=LOCKED las trata todas como bloqueadas y ninguna
    puede recibir un tag nuevo - eso hacia fallar la resolucion del LLM (is_valid=False) y el
    hibrido terminaba prefiriendo reglas, dando la falsa impresion de que should_consult_llm no
    detectaba la composicionalidad (si la detectaba; el LLM SI era consultado).

    Sin I_Emergency, igual que el banco fisico real (paro de emergencia cableado externo al PLC,
    seccion 15/16 de una tarea anterior) - nunca se crea automaticamente.
    """
    return {
        "variables": [
            _variable("I_Start", "%IX0.0", "LOCKED"),
            _variable("I_Stop", "%IX0.1", "LOCKED"),
            _variable("Q_Motor_Enable", "%QX0.0", "ASSIGNED", var_class="output"),
            _variable("I_Free_1", "%IX0.3", "FREE"),
            _variable("I_Free_2", "%IX0.4", "FREE"),
            _variable("Q_Free_1", "%QX0.1", "FREE", var_class="output"),
            _variable("Q_Free_2", "%QX0.2", "FREE", var_class="output"),
        ]
    }


def test_compositional_command_forces_llm_consultation_despite_high_rule_confidence(
    monkeypatch, intents_catalog: dict, safety_rules: dict
) -> None:
    """
    Reproduce el hallazgo pendiente: reglas produce una interpretacion simple con confianza alta
    y coverage "completo" (segun el catalogo de keywords), pero el texto tiene estructura
    composicional real (motor 1/motor 2, "respectivamente", "al mismo tiempo", "viceversa",
    apagado cruzado). detect_compositional_complexity debe forzar la consulta al LLM de todas
    formas, y el resultado final no debe pedir aclaracion.
    """
    io_map = _bench_map_with_free_capacity()
    monkeypatch.setenv("LLM_CONFIDENCE_THRESHOLD", "0.5")  # aun con umbral bajo, debe consultar
    monkeypatch.setattr(
        "llm_parser.parse_command_rule_based",
        lambda command_text, alias_index=None: {
            "intent_id": "INT_MOTOR_START_STOP",
            "case_id": None,
            "command_text": command_text,
            "normalized_command": command_text.lower(),
            "parameters": {
                "trigger_input": "I_Start", "stop_input": "I_Stop",
                "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch"
            },
            "confidence": 0.95,
            "ambiguities": [],
            "requires_clarification": False,
            "clarification_question": None,
            "assumptions": [],
            "recognized_tags": ["I_Start", "I_Stop", "Q_Motor_Enable"],
            "unrecognized_terms": []
        }
    )
    llm_response = {
        "intent_id": "INT_MUTUAL_INTERLOCK",
        "case_id": None,
        "command_text": REPORTED_COMPOSITIONAL_COMMAND,
        "normalized_command": REPORTED_COMPOSITIONAL_COMMAND.lower(),
        "parameters": {
            "trigger_input": "I_Start_Motor_1",
            "stop_input": "I_Start_Motor_2",
            "contactor_a": "Q_Motor_1",
            "contactor_b": "Q_Motor_2"
        },
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start", "I_Stop", "I_Start_Motor_1", "I_Start_Motor_2", "Q_Motor_1", "Q_Motor_2"],
        "unrecognized_terms": []
    }
    result = parse_command(
        REPORTED_COMPOSITIONAL_COMMAND,
        mode="hybrid",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules,
        llm_response_text=llm_response
    )

    # El LLM SI fue consultado (el resultado final es el que provino de la respuesta LLM inline,
    # no el de reglas) - se comprueba por el intent_id y los tags resueltos, exclusivos del LLM.
    assert result["parser_mode_used"] == "llm"
    assert result["llm_result"] != {}
    assert result["intent_id"] == "INT_MUTUAL_INTERLOCK"
    assert result["requires_clarification"] is False

    tags = set(result.get("recognized_tags", []))
    parameters = result.get("parameters", {})
    # Representa: inicio/paro general, pulsante motor 1, pulsante motor 2, motor 1, motor 2.
    assert "I_Start" in tags and "I_Stop" in tags
    assert "I_Start_Motor_1" in tags and "I_Start_Motor_2" in tags
    assert "Q_Motor_1" in tags and "Q_Motor_2" in tags
    # Exclusion mutua / interlock: INT_MUTUAL_INTERLOCK con contactor_a/contactor_b distintos.
    assert parameters.get("contactor_a") == "Q_Motor_1"
    assert parameters.get("contactor_b") == "Q_Motor_2"
    assert parameters.get("contactor_a") != parameters.get("contactor_b")


@pytest.mark.parametrize("command_text", [
    "Enciende el motor con el pulsador de arranque y apagalo con el de paro.",
    "Arranca un motor con Start y detenlo con Stop.",
])
def test_simple_commands_do_not_trigger_compositional_complexity(
    command_text, monkeypatch, io_map: dict, intents_catalog: dict, safety_rules: dict
) -> None:
    """
    Regresion inversa: comandos simples deben seguir resolviendose por reglas, rapido, sin
    consultar al LLM - detect_compositional_complexity no debe generar falsos positivos.
    ("Enciende una lampara con un pulsante." se descarto como caso: el parser por reglas ya lo
    manda a INT_UNKNOWN/requires_clarification por no reconocer "lampara" como equipo valido -
    eso ya consultaba al LLM por razones preexistentes, ajenas a la señal composicional nueva.)
    """
    result = parse_command(
        command_text,
        mode="hybrid",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules
    )
    assert result["parser_mode_used"] == "rule_based"
