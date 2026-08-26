from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from llm_parser import parse_command
from metrics import (
    calculate_average_generation_time,
    calculate_clarification_rate,
    calculate_command_success_rate,
    calculate_compilation_success_rate,
    calculate_fallback_rate,
    calculate_full_validation_rate,
    calculate_intent_accuracy,
    calculate_package_validation_rate,
    calculate_rule_llm_agreement,
    calculate_safety_violation_rate,
    calculate_semantic_validation_rate,
    calculate_simulation_success_rate,
    calculate_slot_accuracy
)
from project_packager import generate_project_package
from utils import current_timestamp, get_project_root, load_json_file


CONDITION_TO_MODE = {
    "C1_LLM_DIRECT": "llm",
    "C2_STRUCTURED_RULES": "rule_based",
    "C3_HYBRID": "hybrid",
    "C4_HYBRID_VOICE": "hybrid",
    "C5_HYBRID_VOICE_NOISE": "hybrid"
}


class EvaluationRunner:
    """Experimental harness for thesis trials without modifying core generation."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or get_project_root()
        self.results_dir = self.project_root / "experimental_results"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.trials_jsonl = self.results_dir / "trials.jsonl"
        self.trials_csv = self.results_dir / "trials.csv"

    def _load_runtime_configuration(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        config_dir = self.project_root / "config"
        return (
            load_json_file(config_dir / "io_map.json"),
            load_json_file(config_dir / "intents_catalog.json"),
            load_json_file(config_dir / "safety_rules.json")
        )

    def _load_test_cases(self) -> list[dict[str, Any]]:
        payload = load_json_file(self.project_root / "tests" / "test_cases.json")
        return payload if isinstance(payload, list) else []

    def run_condition(
        self,
        condition: str,
        *,
        target_platform: str = "CODESYS_ST",
        max_cases: int | None = None
    ) -> list[dict[str, Any]]:
        io_map, intents_catalog, safety_rules = self._load_runtime_configuration()
        test_cases = self._load_test_cases()
        selected_cases = test_cases[:max_cases] if max_cases is not None else test_cases
        trials: list[dict[str, Any]] = []

        for index, test_case in enumerate(selected_cases, start=1):
            trial_id = f"{condition}_{index:03d}"
            command_text = test_case.get("command", "")
            expected_intent = test_case.get("expected_intent")
            started_at = time.perf_counter()

            if condition == "C0_MANUAL":
                trial = {
                    "trial_id": trial_id,
                    "case_id": test_case.get("case_id"),
                    "condition": condition,
                    "command_text": command_text,
                    "transcript": None,
                    "expected_intent": expected_intent,
                    "detected_intent": None,
                    "intent_correct": None,
                    "slot_accuracy": None,
                    "confidence": None,
                    "parser_used": "manual",
                    "semantic_valid": None,
                    "package_valid": None,
                    "generation_time_ms": None,
                    "total_time_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "errors": ["Registro manual requerido."],
                    "warnings": [],
                    "platform": target_platform,
                    "files": [],
                    "model": None,
                    "token_usage": None,
                    "safety_violation": None,
                    "compilation_status": "COMPILATION_NOT_EXECUTED",
                    "simulation_status": "SIMULATION_NOT_EXECUTED",
                    "fully_validated": None,
                    "simulation_tests_passed": None,
                    "simulation_tests_failed": None,
                    "compiler_engine": None,
                    "requires_clarification": None,
                    "rule_llm_agreement": None
                }
                trials.append(trial)
                continue

            parse_started = time.perf_counter()
            semantic_output = parse_command(
                command_text,
                mode=CONDITION_TO_MODE.get(condition, "hybrid"),
                io_map=io_map,
                intents_catalog=intents_catalog,
                safety_rules=safety_rules
            )
            generation_started = time.perf_counter()
            package_result = generate_project_package(
                semantic_output=semantic_output,
                target_platform=target_platform,
                io_map=io_map,
                intents_catalog=intents_catalog,
                safety_rules=safety_rules
            )
            generation_time_ms = round((time.perf_counter() - generation_started) * 1000, 2)
            total_time_ms = round((time.perf_counter() - started_at) * 1000, 2)
            verification = package_result.get("verification", {})
            openplc_validation = verification.get("openplc_validation", {})
            compilation = openplc_validation.get("compilation", {})
            simulation = openplc_validation.get("simulation", {})

            trial = {
                "trial_id": trial_id,
                "case_id": test_case.get("case_id"),
                "condition": condition,
                "command_text": command_text,
                "transcript": semantic_output.get("command_text") if condition.startswith("C4") else None,
                "expected_intent": expected_intent,
                "detected_intent": semantic_output.get("intent_id"),
                "intent_correct": expected_intent == semantic_output.get("intent_id") if expected_intent else None,
                "slot_accuracy": 1.0 if verification.get("is_valid") else 0.0,
                "confidence": semantic_output.get("confidence"),
                "parser_used": semantic_output.get("parser_mode_used", semantic_output.get("parser_mode")),
                "semantic_valid": semantic_output.get("semantic_validation", {}).get("is_valid"),
                "package_valid": verification.get("is_valid"),
                "generation_time_ms": generation_time_ms,
                "total_time_ms": total_time_ms,
                "errors": verification.get("errors", []),
                "warnings": verification.get("warnings", []),
                "platform": target_platform,
                "files": sorted((package_result.get("artifacts") or {}).keys()),
                "model": semantic_output.get("llm_usage", {}).get("model"),
                "token_usage": semantic_output.get("llm_usage", {}).get("total_tokens"),
                "safety_violation": bool(verification.get("errors")),
                "compilation_status": verification.get("compilation_status", "COMPILATION_NOT_EXECUTED"),
                "simulation_status": verification.get("simulation_status", "SIMULATION_NOT_EXECUTED"),
                "fully_validated": verification.get("is_fully_validated"),
                "simulation_tests_passed": simulation.get("tests_passed"),
                "simulation_tests_failed": simulation.get("tests_failed"),
                "compiler_engine": compilation.get("engine"),
                "requires_clarification": semantic_output.get("requires_clarification"),
                "rule_llm_agreement": semantic_output.get("agreement")
            }
            trials.append(trial)

        self._write_trials(trials)
        return trials

    def _write_trials(self, trials: list[dict[str, Any]]) -> None:
        with self.trials_jsonl.open("a", encoding="utf-8") as jsonl_file:
            for trial in trials:
                jsonl_file.write(json.dumps(trial, ensure_ascii=False) + "\n")

        fieldnames = [
            "trial_id",
            "case_id",
            "condition",
            "command_text",
            "transcript",
            "expected_intent",
            "detected_intent",
            "intent_correct",
            "slot_accuracy",
            "confidence",
            "parser_used",
            "semantic_valid",
            "package_valid",
            "generation_time_ms",
            "total_time_ms",
            "errors",
            "warnings",
            "platform",
            "files",
            "model",
            "token_usage",
            "safety_violation",
            "compilation_status",
            "simulation_status",
            "fully_validated",
            "simulation_tests_passed",
            "simulation_tests_failed",
            "compiler_engine",
            "requires_clarification",
            "rule_llm_agreement"
        ]
        file_exists = self.trials_csv.exists()
        with self.trials_csv.open("a", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            for trial in trials:
                row = dict(trial)
                row["errors"] = " | ".join(row.get("errors", []))
                row["warnings"] = " | ".join(row.get("warnings", []))
                row["files"] = " | ".join(row.get("files", []))
                writer.writerow(row)

    def summarize(self) -> dict[str, Any]:
        if not self.trials_jsonl.exists():
            return {}
        trials = [
            json.loads(line)
            for line in self.trials_jsonl.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return {
            "trial_count": len(trials),
            "intent_accuracy": calculate_intent_accuracy(trials),
            "slot_accuracy": calculate_slot_accuracy(trials),
            "command_success_rate": calculate_command_success_rate(trials),
            "semantic_validation_rate": calculate_semantic_validation_rate(trials),
            "package_validation_rate": calculate_package_validation_rate(trials),
            "compilation_success_rate": calculate_compilation_success_rate(trials),
            "simulation_success_rate": calculate_simulation_success_rate(trials),
            "full_validation_rate": calculate_full_validation_rate(trials),
            "average_generation_time_ms": calculate_average_generation_time(trials),
            "fallback_rate": calculate_fallback_rate(trials),
            "clarification_rate": calculate_clarification_rate(trials),
            "rule_llm_agreement": calculate_rule_llm_agreement(trials),
            "safety_violation_rate": calculate_safety_violation_rate(trials),
            "generated_at": current_timestamp()
        }
