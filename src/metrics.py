from __future__ import annotations

from statistics import mean
from typing import Any


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def calculate_intent_accuracy(trials: list[dict[str, Any]]) -> float:
    eligible = [trial for trial in trials if trial.get("expected_intent")]
    correct = sum(1 for trial in eligible if trial.get("intent_correct") is True)
    return _safe_ratio(correct, len(eligible))


def calculate_slot_accuracy(trials: list[dict[str, Any]]) -> float:
    values = [float(trial.get("slot_accuracy", 0.0)) for trial in trials if trial.get("slot_accuracy") is not None]
    return round(mean(values), 4) if values else 0.0


def calculate_command_success_rate(trials: list[dict[str, Any]]) -> float:
    success = sum(1 for trial in trials if trial.get("package_valid") is True)
    return _safe_ratio(success, len(trials))


def calculate_semantic_validation_rate(trials: list[dict[str, Any]]) -> float:
    success = sum(1 for trial in trials if trial.get("semantic_valid") is True)
    return _safe_ratio(success, len(trials))


def calculate_package_validation_rate(trials: list[dict[str, Any]]) -> float:
    success = sum(1 for trial in trials if trial.get("package_valid") is True)
    return _safe_ratio(success, len(trials))


def calculate_compilation_success_rate(trials: list[dict[str, Any]]) -> float:
    eligible = [trial for trial in trials if trial.get("compilation_status") != "COMPILATION_NOT_EXECUTED"]
    success = sum(1 for trial in eligible if trial.get("compilation_status") == "COMPILATION_PASSED")
    return _safe_ratio(success, len(eligible))


def calculate_simulation_success_rate(trials: list[dict[str, Any]]) -> float:
    eligible = [trial for trial in trials if trial.get("simulation_status") != "SIMULATION_NOT_EXECUTED"]
    success = sum(1 for trial in eligible if trial.get("simulation_status") == "SIMULATION_PASSED")
    return _safe_ratio(success, len(eligible))


def calculate_full_validation_rate(trials: list[dict[str, Any]]) -> float:
    eligible = [trial for trial in trials if trial.get("fully_validated") is not None]
    success = sum(1 for trial in eligible if trial.get("fully_validated") is True)
    return _safe_ratio(success, len(eligible))


def calculate_average_generation_time(trials: list[dict[str, Any]]) -> float:
    values = [float(trial.get("generation_time_ms", 0.0)) for trial in trials if trial.get("generation_time_ms") is not None]
    return round(mean(values), 2) if values else 0.0


def calculate_fallback_rate(trials: list[dict[str, Any]]) -> float:
    fallback_trials = sum(1 for trial in trials if trial.get("parser_used") == "rule_based" and trial.get("condition") in {"C1_LLM_DIRECT", "C3_HYBRID", "C4_HYBRID_VOICE"})
    return _safe_ratio(fallback_trials, len(trials))


def calculate_clarification_rate(trials: list[dict[str, Any]]) -> float:
    clarification_trials = sum(1 for trial in trials if trial.get("requires_clarification") is True)
    return _safe_ratio(clarification_trials, len(trials))


def calculate_rule_llm_agreement(trials: list[dict[str, Any]]) -> float:
    relevant = [trial for trial in trials if trial.get("rule_llm_agreement") is not None]
    agreement = sum(1 for trial in relevant if trial.get("rule_llm_agreement") is True)
    return _safe_ratio(agreement, len(relevant))


def calculate_safety_violation_rate(trials: list[dict[str, Any]]) -> float:
    violations = sum(1 for trial in trials if trial.get("safety_violation") is True)
    return _safe_ratio(violations, len(trials))
