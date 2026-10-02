from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from alias_resolver import build_alias_index
from io_allocator import extract_implicit_multi_resource_requests, extract_io_assignment_requests
from functional_requirements import (
    FUNCTIONAL_REQUIREMENT_KEYWORDS,
    PID_PROCESS_VARIABLES,
    compute_intent_covered_types,
    compute_semantic_coverage,
    detect_compositional_complexity,
    detect_functional_requirement_conflicts
)
from knowledge_retriever import retrieve_relevant_context
from llm_client import PLCInterpretationLLMClient
from llm_context_builder import build_llm_context
from semantic_parser import normalize_text, parse_command as parse_command_rule_based
from semantic_repair import repair_semantic_output, strip_unavailable_emergency_reference
from semantic_validator import INTENT_PARAMETER_RULES, validate_semantic_output
from utils import get_project_root, load_json_file


DEFAULT_LLM_SETTINGS = {
    "provider": "openai",
    "parser_mode": "llm",
    "model_from_env": "PLC_LLM_MODEL",
    "transcription_model_from_env": "PLC_TRANSCRIPTION_MODEL",
    "confidence_threshold": 0.85,
    "temperature": 0,
    "max_retries": 2,
    "request_timeout_seconds": 45,
    "allow_rule_fallback": True,
    "require_structured_output": True
}
SUPPORTED_PARSER_MODES = {"rule_based", "llm", "hybrid"}


def _normalize_parser_mode(mode: str | None) -> str:
    normalized = (mode or "").strip().lower()
    return normalized if normalized in SUPPORTED_PARSER_MODES else "rule_based"


def _merge_settings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = load_json_file(path)
    return payload if isinstance(payload, dict) else {}


def load_parser_settings(config_path: Path | None = None) -> dict[str, Any]:
    project_root = get_project_root()
    llm_config_path = config_path or (project_root / "config" / "llm_config.json")
    legacy_config_path = project_root / "config" / "parser_settings.json"

    settings = dict(DEFAULT_LLM_SETTINGS)
    settings = _merge_settings(settings, _load_json_if_exists(llm_config_path))

    legacy_settings = _load_json_if_exists(legacy_config_path)
    if "parser_mode" in legacy_settings and "parser_mode" not in settings:
        settings["parser_mode"] = legacy_settings["parser_mode"]
    legacy_llm = legacy_settings.get("llm")
    if isinstance(legacy_llm, dict):
        if "allow_fallback_to_rules" in legacy_llm:
            settings["allow_rule_fallback"] = bool(legacy_llm["allow_fallback_to_rules"])
        if "temperature" in legacy_llm:
            settings["temperature"] = legacy_llm["temperature"]
        if "provider" in legacy_llm:
            settings["provider"] = legacy_llm["provider"]

    return settings


def resolve_parser_mode(settings: dict[str, Any] | None = None) -> str:
    for environment_key in ("PARSER_MODE", "VOZ_LLM_PARSER_MODE"):
        environment_mode = os.getenv(environment_key)
        if environment_mode:
            return _normalize_parser_mode(environment_mode)

    payload = settings or load_parser_settings()
    return _normalize_parser_mode(payload.get("parser_mode"))


def _load_io_map() -> dict[str, Any]:
    return load_json_file(get_project_root() / "config" / "io_map.json")


def _load_intents_catalog() -> dict[str, Any]:
    return load_json_file(get_project_root() / "config" / "intents_catalog.json")


def _load_safety_rules() -> dict[str, Any]:
    return load_json_file(get_project_root() / "config" / "safety_rules.json")


def build_llm_prompt_payload(
    command_text: str,
    io_map: dict[str, Any] | None = None,
    intents_catalog: dict[str, Any] | None = None,
    safety_rules: dict[str, Any] | None = None
) -> dict[str, Any]:
    runtime_io_map = io_map or _load_io_map()
    runtime_intents_catalog = intents_catalog or _load_intents_catalog()
    runtime_safety_rules = safety_rules or _load_safety_rules()
    return build_llm_context(
        command_text=command_text,
        io_map=runtime_io_map,
        intents_catalog=runtime_intents_catalog,
        safety_rules=runtime_safety_rules
    )


def _base_unknown_output(command_text: str) -> dict[str, Any]:
    return {
        "intent_id": "INT_UNKNOWN",
        "case_id": None,
        "command_text": command_text,
        "normalized_command": normalize_text(command_text),
        "parameters": {},
        "confidence": 0.0,
        "ambiguities": ["No se pudo determinar una intencion segura."],
        "requires_clarification": True,
        "clarification_question": "Aclare la accion industrial requerida, las variables involucradas y el tiempo si aplica.",
        "assumptions": [],
        "recognized_tags": [],
        "unrecognized_terms": [],
        "functional_requirements": []
    }


def _normalize_semantic_output(payload: dict[str, Any] | None, command_text: str) -> dict[str, Any]:
    base = _base_unknown_output(command_text)
    if not isinstance(payload, dict):
        return base

    normalized = dict(base)
    normalized.update(payload)
    normalized["command_text"] = command_text
    normalized["normalized_command"] = str(payload.get("normalized_command", normalize_text(command_text)))
    normalized["parameters"] = payload.get("parameters", {}) if isinstance(payload.get("parameters", {}), dict) else {}
    normalized["ambiguities"] = payload.get("ambiguities", []) if isinstance(payload.get("ambiguities", []), list) else []
    normalized["assumptions"] = payload.get("assumptions", []) if isinstance(payload.get("assumptions", []), list) else []
    normalized["recognized_tags"] = payload.get("recognized_tags", []) if isinstance(payload.get("recognized_tags", []), list) else []
    normalized["unrecognized_terms"] = payload.get("unrecognized_terms", []) if isinstance(payload.get("unrecognized_terms", []), list) else []
    normalized["requires_clarification"] = bool(payload.get("requires_clarification", False))
    normalized["clarification_question"] = payload.get("clarification_question")
    normalized["functional_requirements"] = (
        payload.get("functional_requirements", []) if isinstance(payload.get("functional_requirements", []), list) else []
    )

    try:
        normalized["confidence"] = round(float(payload.get("confidence", 0.0)), 2)
    except (TypeError, ValueError):
        normalized["confidence"] = 0.0
    normalized["confidence"] = max(0.0, min(1.0, normalized["confidence"]))
    return normalized


def _attach_rule_based_functional_requirements(
    result: dict[str, Any],
    command_text: str,
    intents_catalog: dict[str, Any]
) -> dict[str, Any]:
    """
    Gives the rule-based/hybrid path the same composability the LLM path gets: detects known
    functional_requirement keywords in the command and attaches the ones the chosen intent does
    not already cover by itself. Reuses the SAME catalog the LLM prompt and the coverage checker
    use - no separate semantic model, per section 14 of the request.
    """
    if result.get("functional_requirements"):
        return result
    normalized_command = str(result.get("normalized_command") or command_text).lower()
    is_pid_context = result.get("intent_id") == "INT_PID_SUPERVISOR"
    detected_types = {
        req_type
        for req_type, keywords in FUNCTIONAL_REQUIREMENT_KEYWORDS.items()
        if (req_type in PID_PROCESS_VARIABLES) == is_pid_context
        and any(keyword in normalized_command for keyword in keywords)
    }
    if not detected_types:
        return result
    intent_definition = intents_catalog.get(result.get("intent_id", ""), {}) if isinstance(intents_catalog, dict) else {}
    covered_by_intent = compute_intent_covered_types(intent_definition) if isinstance(intent_definition, dict) else set()
    additional_types = sorted(detected_types - covered_by_intent)
    if not additional_types:
        return result
    updated = dict(result)
    updated["functional_requirements"] = [{"type": req_type} for req_type in additional_types]
    return updated


def _sync_clarification_from_validation(result: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    """
    A functional_requirement conflict can force semantic_validation.requires_clarification=True
    without the parser output itself ever having set clarification_question (section 12: real
    conflict -> clarification). Mirror that decision into the top-level result so the GUI's
    clarification dialog has a real question to show, not the generic fallback text.
    """
    if not validation.get("requires_clarification") or result.get("clarification_question"):
        return result
    if validation.get("clarification_question") and not validation.get("functional_requirement_conflicts"):
        # Dato funcional faltante detectado de forma determinista (p.ej. duracion de una etapa).
        updated = dict(result)
        updated["requires_clarification"] = True
        updated["clarification_question"] = validation["clarification_question"]
        return updated
    conflicts = validation.get("functional_requirement_conflicts") or []
    if not conflicts:
        return result
    summary = "; ".join(str(conflict.get("reason", "")) for conflict in conflicts)
    updated = dict(result)
    updated["requires_clarification"] = True
    updated["clarification_question"] = (
        f"Se detecto un conflicto entre requisitos funcionales: {summary} Indique cual valor debe aplicarse."
    )
    return updated


def _validate_result(
    payload: dict[str, Any],
    io_map: dict[str, Any],
    intents_catalog: dict[str, Any],
    safety_rules: dict[str, Any]
) -> dict[str, Any]:
    return validate_semantic_output(
        semantic_output=payload,
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules
    )


def _repair_and_validate(
    payload: dict[str, Any],
    io_map: dict[str, Any],
    intents_catalog: dict[str, Any],
    safety_rules: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Shape-normalization pass (see semantic_repair.py) BEFORE validation: a compound-command
    interpretation the LLM/rules already understood correctly, but expressed under a different
    parameter shape than the chosen intent's fixed template, must not be rejected as "missing
    required parameters" - it gets repaired first, then validated as usual. Also strips any
    I_Emergency reference the parser added by convention when the active map has no such tag
    (section "banco sin paro de emergencia cableado al PLC") - otherwise the two-level validation
    below would auto-resolve it to a real FREE channel nobody asked for. Returns (possibly-repaired
    payload, its validation) so callers keep using the SAME repaired object downstream (IR building
    reads semantic_output["parameters"] directly), never the pre-repair one.
    """
    payload = strip_unavailable_emergency_reference(payload, io_map)
    repaired = repair_semantic_output(payload, INTENT_PARAMETER_RULES)
    validation = _validate_result(repaired, io_map, intents_catalog, safety_rules)
    return repaired, validation


def _agreement(rule_result: dict[str, Any] | None, llm_result: dict[str, Any] | None) -> bool:
    if not rule_result or not llm_result:
        return False
    return (
        rule_result.get("intent_id") == llm_result.get("intent_id")
        and set(rule_result.get("recognized_tags", [])) == set(llm_result.get("recognized_tags", []))
    )


def _result_richness_score(result: dict[str, Any] | None, validation: dict[str, Any] | None) -> float:
    """
    Metrica deliberadamente simple y determinista (no una IA de verdad) para comparar cuanto
    representa cada interpretacion: paso su propia validacion, tiene una intencion resuelta,
    cuantos tags reconoce, cuantos requisitos funcionales declara. Se usa para decidir CUAL de
    reglas/LLM usar cuando ambas son coherentes pero distintas - nunca para inventar contenido.
    """
    if not result:
        return -1.0
    score = 0.0
    if result.get("intent_id") not in (None, "INT_UNKNOWN"):
        score += 1.0
    score += len(result.get("recognized_tags", []) or [])
    score += len(result.get("functional_requirements", []) or [])
    if validation and validation.get("is_valid"):
        score += 2.0
    if result.get("requires_clarification"):
        score -= 1.0
    return score


def _merge_functional_requirements(
    primary: list[dict[str, Any]], secondary: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Incorpora requisitos funcionales coherentes que SOLO la interpretacion secundaria detecto
    (nunca sustituye los de la primaria, nunca duplica un `type` ya presente).
    """
    primary_types = {str(requirement.get("type", "")) for requirement in primary}
    merged = list(primary)
    for requirement in secondary:
        if str(requirement.get("type", "")) not in primary_types:
            merged.append(requirement)
    return merged


def _detect_functional_contradiction(
    rule_result: dict[str, Any] | None, llm_result: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """
    Una diferencia de `intent_id` NUNCA es, por si sola, una contradiccion real - eso se resuelve
    comparando cobertura (_result_richness_score), no preguntando. Una contradiccion REAL es que
    ambas interpretaciones pidan el MISMO tipo de requisito funcional con parametros incompatibles
    (p. ej. las reglas detectan `set_manual_mode` y el LLM `set_auto_mode` sobre el mismo comando -
    literalmente pedir dos comportamientos opuestos). Reutiliza
    detect_functional_requirement_conflicts, ya usado para esto mismo dentro de una sola
    interpretacion - aqui simplemente se combinan ambas listas antes de aplicarlo.
    """
    if not rule_result or not llm_result:
        return []
    combined = list(rule_result.get("functional_requirements", []) or []) + list(
        llm_result.get("functional_requirements", []) or []
    )
    return detect_functional_requirement_conflicts(combined)


def _annotate_result(
    selected_result: dict[str, Any],
    *,
    requested_mode: str,
    used_mode: str,
    rule_result: dict[str, Any] | None,
    llm_result: dict[str, Any] | None,
    decision_reason: str,
    llm_usage: dict[str, Any] | None,
    semantic_validation: dict[str, Any],
    retrieved_context: list[dict[str, Any]] | None,
    semantic_coverage: dict[str, Any] | None = None,
    first_pass_interpretation: dict[str, Any] | None = None,
    second_pass_interpretation: dict[str, Any] | None = None,
    reason_for_retry: str | None = None
) -> dict[str, Any]:
    payload = dict(selected_result)
    payload["parser_mode_requested"] = requested_mode
    payload["parser_mode_used"] = used_mode
    payload["rule_result"] = rule_result or {}
    payload["llm_result"] = llm_result or {}
    payload["agreement"] = _agreement(rule_result, llm_result)
    payload["decision_reason"] = decision_reason
    payload["llm_usage"] = llm_usage or {}
    payload["semantic_validation"] = semantic_validation
    payload["retrieved_context"] = retrieved_context or []
    payload["parser_mode"] = used_mode
    payload["semantic_coverage"] = semantic_coverage or {}
    payload["first_pass_interpretation"] = first_pass_interpretation
    payload["second_pass_interpretation"] = second_pass_interpretation
    payload["reason_for_retry"] = reason_for_retry
    payload["parser_metadata"] = {
        "requested_mode": requested_mode,
        "decision_reason": decision_reason,
        "agreement": payload["agreement"],
        "retrieved_context_count": len(retrieved_context or [])
    }
    return payload


def _fallback_to_rules(
    command_text: str,
    requested_mode: str,
    reason: str,
    io_map: dict[str, Any],
    intents_catalog: dict[str, Any],
    safety_rules: dict[str, Any]
) -> dict[str, Any]:
    rule_result = _normalize_semantic_output(
        parse_command_rule_based(command_text, alias_index=build_alias_index(io_map)), command_text
    )
    rule_result, semantic_validation = _repair_and_validate(rule_result, io_map, intents_catalog, safety_rules)
    return _annotate_result(
        rule_result,
        requested_mode=requested_mode,
        used_mode="rule_based",
        rule_result=rule_result,
        llm_result=None,
        decision_reason=reason,
        llm_usage={},
        semantic_validation=semantic_validation,
        retrieved_context=[]
    )


def _invoke_llm(
    command_text: str,
    llm_client: PLCInterpretationLLMClient,
    context: dict[str, Any],
    llm_response_text: str | dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if llm_response_text is not None:
        if isinstance(llm_response_text, str):
            payload = json.loads(llm_response_text)
        else:
            payload = llm_response_text
        return _normalize_semantic_output(payload, command_text), {"provider": "inline", "structured_output": False}

    semantic_model, usage = llm_client.interpret_command(command_text, context)
    output = semantic_model.model_dump(mode="python")
    usage_payload = usage.model_dump(mode="python")
    return _normalize_semantic_output(output, command_text), usage_payload


def parse_with_mode(
    command_text: str,
    mode: str = "llm",
    io_map: dict[str, Any] | None = None,
    intents_catalog: dict[str, Any] | None = None,
    safety_rules: dict[str, Any] | None = None,
    llm_client: PLCInterpretationLLMClient | None = None,
    llm_response_text: str | dict[str, Any] | None = None,
    interaction_profile: str | None = None,
    clarification_history: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """
    interaction_profile="normal" (solo Modo Normal): agrega la politica de composicion funcional y el
    historial ESTRUCTURADO de aclaraciones al contexto del LLM. Sin perfil, el comportamiento es
    exactamente el anterior (Experimentacion queda congelada).
    """
    settings = load_parser_settings()
    requested_mode = _normalize_parser_mode(mode or resolve_parser_mode(settings))
    runtime_io_map = io_map or _load_io_map()
    runtime_intents_catalog = intents_catalog or _load_intents_catalog()
    runtime_safety_rules = safety_rules or _load_safety_rules()
    threshold = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", settings.get("confidence_threshold", 0.85)))
    allow_rule_fallback = bool(settings.get("allow_rule_fallback", True))

    rule_text = command_text
    if interaction_profile == "normal" and clarification_history:
        from normal_interaction import rule_parser_text

        rule_text = rule_parser_text(command_text, clarification_history)
    rule_result = _normalize_semantic_output(
        parse_command_rule_based(rule_text, alias_index=build_alias_index(runtime_io_map)), command_text
    )
    rule_result = _attach_rule_based_functional_requirements(rule_result, command_text, runtime_intents_catalog)
    rule_result, rule_validation = _repair_and_validate(rule_result, runtime_io_map, runtime_intents_catalog, runtime_safety_rules)
    rule_result = _sync_clarification_from_validation(rule_result, rule_validation)

    if requested_mode == "rule_based":
        return _annotate_result(
            rule_result,
            requested_mode=requested_mode,
            used_mode="rule_based",
            rule_result=rule_result,
            llm_result=None,
            decision_reason="Modo RULE_BASED solicitado por configuracion o usuario.",
            llm_usage={},
            semantic_validation=rule_validation,
            retrieved_context=[]
        )

    runtime_llm_client = llm_client or PLCInterpretationLLMClient()
    llm_available = bool(llm_response_text is not None or runtime_llm_client.is_configured())

    if requested_mode == "llm" and not llm_available:
        if allow_rule_fallback:
            return _fallback_to_rules(
                command_text=command_text,
                requested_mode=requested_mode,
                reason="LLM no configurado. Se usa parser por reglas como fallback permitido.",
                io_map=runtime_io_map,
                intents_catalog=runtime_intents_catalog,
                safety_rules=runtime_safety_rules
            )
        unknown = _base_unknown_output(command_text)
        semantic_validation = _validate_result(unknown, runtime_io_map, runtime_intents_catalog, runtime_safety_rules)
        return _annotate_result(
            unknown,
            requested_mode=requested_mode,
            used_mode="llm",
            rule_result=rule_result,
            llm_result=None,
            decision_reason="LLM solicitado pero no configurado y sin fallback habilitado.",
            llm_usage={},
            semantic_validation=semantic_validation,
            retrieved_context=[]
        )

    rule_coverage = compute_semantic_coverage(
        command_text=command_text,
        intent_id=rule_result.get("intent_id", "INT_UNKNOWN"),
        functional_requirements=rule_result.get("functional_requirements", []),
        intents_catalog=runtime_intents_catalog
    )

    compositional_complexity = detect_compositional_complexity(command_text)

    should_consult_llm = requested_mode == "llm"
    if requested_mode == "hybrid":
        should_consult_llm = bool(
            rule_result.get("confidence", 0.0) < threshold
            or rule_result.get("intent_id") == "INT_UNKNOWN"
            or rule_result.get("requires_clarification", False)
            or bool(rule_result.get("ambiguities"))
            or not rule_validation.get("is_valid", False)
            # Las reglas pueden estar seguras del intent principal y aun asi omitir requisitos
            # compuestos (pilotos, delays adicionales, etc.) - eso tambien amerita consultar al
            # LLM, aunque la confianza por reglas ya superara el umbral (seccion 14).
            or not rule_coverage["complete"]
            # Senales ESTRUCTURALES (multiples entidades numeradas, "respectivamente",
            # "viceversa", exclusion mutua/"al mismo tiempo", apagado cruzado uno/otro, varias
            # condiciones "cuando") indican un comando composicional que compute_semantic_coverage
            # no detecta porque no coincide con ninguna frase exacta de su catalogo de keywords -
            # aunque la confianza de reglas sea alta, esto tambien amerita consultar al LLM.
            or compositional_complexity["is_compositional"]
        )

    if requested_mode == "hybrid" and not should_consult_llm:
        return _annotate_result(
            rule_result,
            requested_mode=requested_mode,
            used_mode="rule_based",
            rule_result=rule_result,
            llm_result=None,
            decision_reason="El parser por reglas supero el umbral de confianza y no presento ambiguedades.",
            llm_usage={},
            semantic_validation=rule_validation,
            retrieved_context=[],
            semantic_coverage=rule_coverage
        )

    if not llm_available:
        return _fallback_to_rules(
            command_text=command_text,
            requested_mode=requested_mode,
            reason="No hay cliente LLM operativo. Se mantiene el modo demo local con parser por reglas.",
            io_map=runtime_io_map,
            intents_catalog=runtime_intents_catalog,
            safety_rules=runtime_safety_rules
        )

    retrieved_context = retrieve_relevant_context(
        command_text=command_text,
        intent_id=rule_result.get("intent_id"),
        platform=None
    )
    llm_context = build_llm_prompt_payload(
        command_text=command_text,
        io_map=runtime_io_map,
        intents_catalog=runtime_intents_catalog,
        safety_rules=runtime_safety_rules
    )
    llm_context["retrieved_context"] = retrieved_context
    if interaction_profile == "normal":
        from normal_interaction import NORMAL_MODE_POLICY

        llm_context["normal_mode_policy"] = NORMAL_MODE_POLICY
        if clarification_history:
            llm_context["original_command"] = command_text
            llm_context["clarification_history"] = [
                {"clarification_question": item.get("question"), "clarification_answer": item.get("answer")}
                for item in clarification_history
            ]

    try:
        llm_result, llm_usage = _invoke_llm(
            command_text=command_text,
            llm_client=runtime_llm_client,
            context=llm_context,
            llm_response_text=llm_response_text
        )
    except Exception as error:
        if allow_rule_fallback:
            return _fallback_to_rules(
                command_text=command_text,
                requested_mode=requested_mode,
                reason=f"Fallo el parser LLM y se usa fallback por reglas: {error}",
                io_map=runtime_io_map,
                intents_catalog=runtime_intents_catalog,
                safety_rules=runtime_safety_rules
            )
        raise

    if interaction_profile == "normal":
        # Marca de perfil (fuera del contrato semantico): habilita la validacion temprana de
        # recursos funcionales solo en Modo Normal.
        llm_result = {**llm_result, "interaction_profile": "normal"}
    llm_result, llm_validation = _repair_and_validate(llm_result, runtime_io_map, runtime_intents_catalog, runtime_safety_rules)
    llm_result = _sync_clarification_from_validation(llm_result, llm_validation)

    first_pass_result = dict(llm_result)
    second_pass_result: dict[str, Any] | None = None
    reason_for_retry: str | None = None
    coverage = compute_semantic_coverage(
        command_text=command_text,
        intent_id=llm_result.get("intent_id", "INT_UNKNOWN"),
        functional_requirements=llm_result.get("functional_requirements", []),
        intents_catalog=runtime_intents_catalog
    )

    if not coverage["complete"]:
        # Segunda pasada, como maximo una: no hay reintento de un reintento, para no crear
        # un bucle. Si la segunda pasada tampoco mejora, se conserva la primera y sigue su curso
        # normal (llegara a clarification/fallback por las reglas ya existentes mas abajo).
        reason_for_retry = "semantic_coverage_incomplete: " + ", ".join(coverage["missing_types"])
        retry_context = dict(llm_context)
        retry_context["correction_note"] = (
            "La interpretacion anterior omitio estos requisitos detectados en el comando: "
            + ", ".join(coverage["missing_types"])
            + ". Reestructura el resultado incluyendo TODOS los requisitos funcionales explicitos "
            "del comando usando el campo functional_requirements (no inventes una intencion nueva)."
        )
        try:
            retry_result, retry_usage = _invoke_llm(
                command_text=command_text,
                llm_client=runtime_llm_client,
                context=retry_context,
                llm_response_text=None
            )
            if interaction_profile == "normal":
                retry_result = {**retry_result, "interaction_profile": "normal"}
            retry_result, retry_validation = _repair_and_validate(retry_result, runtime_io_map, runtime_intents_catalog, runtime_safety_rules)
            second_pass_result = retry_result
            retry_result = _sync_clarification_from_validation(retry_result, retry_validation)
            retry_coverage = compute_semantic_coverage(
                command_text=command_text,
                intent_id=retry_result.get("intent_id", "INT_UNKNOWN"),
                functional_requirements=retry_result.get("functional_requirements", []),
                intents_catalog=runtime_intents_catalog
            )
            if retry_coverage["complete"] or retry_validation.get("is_valid", False):
                llm_result, llm_usage, llm_validation, coverage = retry_result, retry_usage, retry_validation, retry_coverage
        except Exception:
            pass  # se conserva la primera pasada; el flujo normal de abajo decide que hacer con ella

    if requested_mode == "llm":
        return _annotate_result(
            llm_result,
            requested_mode=requested_mode,
            used_mode="llm",
            rule_result=rule_result,
            llm_result=llm_result,
            decision_reason="Modo LLM solicitado y respuesta semantica estructurada obtenida.",
            llm_usage=llm_usage,
            semantic_validation=llm_validation,
            retrieved_context=retrieved_context,
            semantic_coverage=coverage,
            first_pass_interpretation=first_pass_result,
            second_pass_interpretation=second_pass_result,
            reason_for_retry=reason_for_retry
        )

    functional_contradictions = _detect_functional_contradiction(rule_result, llm_result)
    if functional_contradictions:
        # Contradiccion funcional REAL (mismo tipo de requisito, parametros incompatibles - p.ej.
        # una interpretacion pide set_auto_mode y la otra set_manual_mode para el mismo comando).
        # Esto SI amerita aclaracion. Una simple diferencia de intent_id NUNCA la amerita por si
        # sola (bug reportado) - eso se resuelve mas abajo comparando cobertura, sin preguntar.
        clarification_output = dict(llm_result)
        clarification_output["intent_id"] = "INT_UNKNOWN"
        clarification_output["confidence"] = 0.0
        clarification_output["requires_clarification"] = True
        conflict_summary = "; ".join(conflict["reason"] for conflict in functional_contradictions)
        clarification_output["clarification_question"] = (
            "Se detecto una contradiccion funcional real entre la interpretacion por reglas y la "
            f"del LLM: {conflict_summary} Indique cual comportamiento debe aplicarse."
        )
        clarification_output["ambiguities"] = list(dict.fromkeys(
            list(clarification_output.get("ambiguities", [])) + [conflict_summary]
        ))
        clarification_validation = _validate_result(
            clarification_output,
            runtime_io_map,
            runtime_intents_catalog,
            runtime_safety_rules
        )
        return _annotate_result(
            clarification_output,
            requested_mode=requested_mode,
            used_mode="hybrid",
            rule_result=rule_result,
            llm_result=llm_result,
            decision_reason=(
                "Contradiccion funcional real entre reglas y LLM (mismo requisito, parametros "
                "incompatibles); se solicita aclaracion."
            ),
            llm_usage=llm_usage,
            semantic_validation=clarification_validation,
            retrieved_context=retrieved_context,
            semantic_coverage=coverage,
            first_pass_interpretation=first_pass_result,
            second_pass_interpretation=second_pass_result,
            reason_for_retry=reason_for_retry
        )

    # Sin contradiccion real: nunca se pregunta solo por un intent_id distinto. Se compara
    # cobertura semantica (_result_richness_score) y se elige automaticamente el resultado mas
    # completo, fusionando los requisitos funcionales coherentes que la otra interpretacion haya
    # detectado de mas (seccion 6: "si uno detecta requisitos adicionales coherentes, incorporarlos").
    rule_score = _result_richness_score(rule_result, rule_validation)
    llm_score = _result_richness_score(llm_result, llm_validation)

    if llm_validation.get("is_valid", False) and (llm_score >= rule_score or not rule_validation.get("is_valid", False)):
        merged_result = dict(llm_result)
        merged_result["functional_requirements"] = _merge_functional_requirements(
            llm_result.get("functional_requirements", []) or [], rule_result.get("functional_requirements", []) or []
        )
        return _annotate_result(
            merged_result,
            requested_mode=requested_mode,
            used_mode="llm",
            rule_result=rule_result,
            llm_result=llm_result,
            decision_reason=(
                "El parser hibrido comparo cobertura semantica entre reglas y LLM (sin "
                "contradiccion real) y uso la interpretacion LLM por tener cobertura igual o "
                "mayor, fusionando requisitos funcionales adicionales coherentes de reglas."
            ),
            llm_usage=llm_usage,
            semantic_validation=llm_validation,
            retrieved_context=retrieved_context,
            semantic_coverage=coverage,
            first_pass_interpretation=first_pass_result,
            second_pass_interpretation=second_pass_result,
            reason_for_retry=reason_for_retry
        )

    if allow_rule_fallback and rule_validation.get("is_valid", False):
        merged_result = dict(rule_result)
        merged_result["functional_requirements"] = _merge_functional_requirements(
            rule_result.get("functional_requirements", []) or [], llm_result.get("functional_requirements", []) or []
        )
        return _annotate_result(
            merged_result,
            requested_mode=requested_mode,
            used_mode="rule_based",
            rule_result=rule_result,
            llm_result=llm_result,
            decision_reason=(
                "El parser hibrido comparo cobertura semantica: las reglas tuvieron cobertura "
                "igual o mayor (o la salida LLM no paso validacion), fusionando requisitos "
                "funcionales adicionales coherentes detectados por el LLM."
            ),
            llm_usage=llm_usage,
            semantic_validation=rule_validation,
            retrieved_context=retrieved_context,
            semantic_coverage=coverage,
            first_pass_interpretation=first_pass_result,
            second_pass_interpretation=second_pass_result,
            reason_for_retry=reason_for_retry
        )

    return _annotate_result(
        llm_result,
        requested_mode=requested_mode,
        used_mode="llm",
        rule_result=rule_result,
        llm_result=llm_result,
        decision_reason="La salida LLM fue obtenida pero requiere aclaracion o correccion antes de continuar.",
        llm_usage=llm_usage,
        semantic_validation=llm_validation,
        retrieved_context=retrieved_context,
        semantic_coverage=coverage,
        first_pass_interpretation=first_pass_result,
        second_pass_interpretation=second_pass_result,
        reason_for_retry=reason_for_retry
    )


def parse_command_with_llm(
    command_text: str,
    io_map: dict[str, Any] | None = None,
    intents_catalog: dict[str, Any] | None = None,
    safety_rules: dict[str, Any] | None = None,
    llm_client: PLCInterpretationLLMClient | None = None,
    llm_response_text: str | dict[str, Any] | None = None
) -> dict[str, Any]:
    result = parse_with_mode(
        command_text=command_text,
        mode="llm",
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules,
        llm_client=llm_client,
        llm_response_text=llm_response_text
    )
    return _attach_io_assignment_requests(result, command_text, io_map, intents_catalog, safety_rules)


def _attach_io_assignment_requests(
    payload: dict[str, Any],
    command_text: str,
    io_map: dict[str, Any] | None,
    intents_catalog: dict[str, Any] | None,
    safety_rules: dict[str, Any] | None
) -> dict[str, Any]:
    """
    MAP_CONFIG post-processing (section 8/29.8): detects address<->role mentions with a plain
    regex scan (io_allocator.extract_io_assignment_requests) - never with the LLM. Runs after the
    normal rule/LLM/hybrid interpretation regardless of parser mode, so "Usa Q8.1 para el motor 2"
    is classified the same way whether C1/C2/C3 is active. If no EXPLICIT address is mentioned,
    falls back to extract_implicit_multi_resource_requests (a narrow, deterministic pattern for
    "N motores con un pulsante independiente para cada uno" - section 42), which resolves roles by
    NAME only (IOAllocator still decides the physical channel, never a guess). If neither finds
    anything, the payload is returned unchanged (normal PLC-logic commands never go through this).
    """
    requests = extract_io_assignment_requests(command_text)
    if not requests:
        requests = extract_implicit_multi_resource_requests(command_text)
    if not requests:
        return payload
    updated = dict(payload)
    updated["requested_io_assignments"] = requests
    updated["operation_type"] = "MAP_CONFIG"
    updated["semantic_validation"] = validate_semantic_output(
        semantic_output=updated,
        io_map=io_map or {},
        intents_catalog=intents_catalog or {},
        safety_rules=safety_rules or {}
    )
    return updated


def parse_command(
    command_text: str,
    mode: str | None = None,
    io_map: dict[str, Any] | None = None,
    intents_catalog: dict[str, Any] | None = None,
    safety_rules: dict[str, Any] | None = None,
    llm_client: PLCInterpretationLLMClient | None = None,
    llm_response_text: str | dict[str, Any] | None = None,
    interaction_profile: str | None = None,
    clarification_history: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    settings = load_parser_settings()
    resolved_mode = _normalize_parser_mode(mode or resolve_parser_mode(settings))
    result = parse_with_mode(
        command_text=command_text,
        mode=resolved_mode,
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules,
        llm_client=llm_client,
        llm_response_text=llm_response_text,
        interaction_profile=interaction_profile,
        clarification_history=clarification_history
    )
    return _attach_io_assignment_requests(result, command_text, io_map, intents_catalog, safety_rules)
