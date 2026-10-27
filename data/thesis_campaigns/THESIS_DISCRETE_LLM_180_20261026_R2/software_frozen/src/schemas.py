from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from utils import get_project_root
from functional_requirements import PID_PROCESS_VARIABLES


TIME_LITERAL_PATTERN = re.compile(r"^T#\d+(?:ms|s|m|h)$", re.IGNORECASE)
# AI_/AO_ (entradas/salidas analogicas fisicas) se autorizan igual que I_/Q_ - ver
# docs/21_pid_supervisory_control.md y docs/22_banco_fisico_direcciones.md.
PLC_TAG_PATTERN = re.compile(r"^(?:AI|AO|[IQMTCFR])_[A-Za-z0-9_]+$")


class SemanticParameters(BaseModel):
    """Flexible parameter container for intent-specific semantic slots."""

    model_config = ConfigDict(extra="allow")


class ClarificationRequest(BaseModel):
    """Represents a clarification that must be resolved before generation."""

    model_config = ConfigDict(extra="forbid")

    command_text: str
    clarification_question: str
    ambiguities: list[str] = Field(default_factory=list)


class LLMUsageMetadata(BaseModel):
    """Sanitized LLM execution metadata without secrets."""

    model_config = ConfigDict(extra="forbid")

    provider: str = "openai"
    model: str | None = None
    request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: float | None = None
    retries_used: int = 0
    used_fallback: bool = False
    structured_output: bool = True
    error: str | None = None


class SemanticValidationResult(BaseModel):
    """Validation outcome after schema, io_map and safety checks."""

    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_parameters: list[str] = Field(default_factory=list)
    unauthorized_tags: list[str] = Field(default_factory=list)
    requires_clarification: bool = False
    # Pregunta FUNCIONAL derivada por el validador (p.ej. duracion faltante de una etapa de secuencia).
    clarification_question: str | None = None
    functional_requirement_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    io_assignment_proposals: list[dict[str, Any]] = Field(default_factory=list)


class SemanticOutput(BaseModel):
    """Strict top-level semantic representation used by the pipeline."""

    model_config = ConfigDict(extra="forbid")

    intent_id: str = "INT_UNKNOWN"
    case_id: str | None = None
    command_text: str
    normalized_command: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    ambiguities: list[str] = Field(default_factory=list)
    requires_clarification: bool = False
    clarification_question: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    recognized_tags: list[str] = Field(default_factory=list)
    unrecognized_terms: list[str] = Field(default_factory=list)
    functional_requirements: list[dict[str, Any]] = Field(default_factory=list)
    # MAP_CONFIG (section 10): "PROGRAM" (default) para logica PLC normal, "MAP_CONFIG" cuando el
    # comando pide (re)asignar un nombre funcional a un canal fisico. Este campo se RECALCULA
    # deterministicamente en semantic_validator - nunca se confia en lo que el LLM haya puesto,
    # ver docs/23_io_allocator.md.
    operation_type: str = "PROGRAM"
    requested_io_assignments: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return round(float(value), 2)

    @field_validator("recognized_tags")
    @classmethod
    def _validate_recognized_tags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if not PLC_TAG_PATTERN.match(value) and value not in PID_PROCESS_VARIABLES:
                raise ValueError(f"invalid PLC tag format: {value}")
            if value not in normalized:
                normalized.append(value)
        return normalized

    @field_validator("clarification_question")
    @classmethod
    def _validate_clarification_question(cls, value: str | None, info: Any) -> str | None:
        requires_clarification = info.data.get("requires_clarification", False)
        if requires_clarification and not value:
            raise ValueError("clarification_question is required when requires_clarification is true")
        return value


def get_semantic_schema_path() -> Path:
    return get_project_root() / "schemas" / "semantic_output.schema.json"


def load_semantic_schema(schema_path: Path | None = None) -> dict[str, Any]:
    path = schema_path or get_semantic_schema_path()
    return json.loads(path.read_text(encoding="utf-8"))


def validate_semantic_payload_structure(
    payload: dict[str, Any],
    schema: dict[str, Any] | None = None
) -> list[str]:
    """
    Lightweight JSON Schema validation for the fixed top-level contract.

    The project keeps the schema in JSON for traceability and uses this
    deterministic checker locally to avoid an extra runtime dependency.
    """
    runtime_schema = schema or load_semantic_schema()
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["The semantic payload must be a JSON object."]

    allowed_keys = set(runtime_schema.get("properties", {}))
    required_keys = set(runtime_schema.get("required", []))

    missing = sorted(required_keys.difference(payload))
    if missing:
        errors.append("Missing required semantic keys: " + ", ".join(missing))

    unexpected = sorted(set(payload).difference(allowed_keys))
    if unexpected:
        errors.append("Unexpected semantic keys: " + ", ".join(unexpected))

    intent_schema = runtime_schema.get("properties", {}).get("intent_id", {})
    allowed_intents = set(intent_schema.get("enum", []))
    intent_id = payload.get("intent_id")
    if intent_id is not None and allowed_intents and intent_id not in allowed_intents:
        errors.append(f"intent_id is not allowed by schema: {intent_id}")

    confidence = payload.get("confidence")
    if confidence is not None:
        try:
            confidence_value = float(confidence)
            if confidence_value < 0 or confidence_value > 1:
                errors.append("confidence must be between 0 and 1")
        except (TypeError, ValueError):
            errors.append("confidence must be numeric")

    if not isinstance(payload.get("parameters", {}), dict):
        errors.append("parameters must be an object")
    if not isinstance(payload.get("ambiguities", []), list):
        errors.append("ambiguities must be a list")
    if not isinstance(payload.get("requires_clarification", False), bool):
        errors.append("requires_clarification must be boolean")
    if not isinstance(payload.get("assumptions", []), list):
        errors.append("assumptions must be a list")
    if not isinstance(payload.get("recognized_tags", []), list):
        errors.append("recognized_tags must be a list")
    if not isinstance(payload.get("unrecognized_terms", []), list):
        errors.append("unrecognized_terms must be a list")

    recognized_schema = runtime_schema.get("properties", {}).get("recognized_tags", {})
    allowed_tags = set(recognized_schema.get("items", {}).get("enum", []))
    for tag in payload.get("recognized_tags", []):
        if allowed_tags and tag not in allowed_tags:
            errors.append(f"recognized_tags contains a tag outside the schema: {tag}")

    return errors


def validate_semantic_model(payload: dict[str, Any]) -> SemanticOutput:
    return SemanticOutput.model_validate(payload)


def semantic_model_to_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="python")


__all__ = [
    "ClarificationRequest",
    "LLMUsageMetadata",
    "PLC_TAG_PATTERN",
    "SemanticOutput",
    "SemanticParameters",
    "SemanticValidationResult",
    "TIME_LITERAL_PATTERN",
    "ValidationError",
    "get_semantic_schema_path",
    "load_semantic_schema",
    "semantic_model_to_dict",
    "validate_semantic_model",
    "validate_semantic_payload_structure"
]
