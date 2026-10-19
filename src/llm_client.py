from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from llm_context_builder import build_llm_context
from schemas import LLMUsageMetadata, SemanticOutput, validate_semantic_model
from utils import get_project_root, load_json_file

try:
    from openai import APITimeoutError, APIConnectionError, OpenAI
except ImportError:  # pragma: no cover - exercised indirectly in demo mode
    APITimeoutError = TimeoutError
    APIConnectionError = ConnectionError
    OpenAI = None


def _env_flag(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


class PLCInterpretationLLMClient:
    """Safe wrapper around the OpenAI SDK for semantic interpretation only."""

    def __init__(
        self,
        config_path: Path | None = None,
        prompt_path: Path | None = None,
        client: Any | None = None
    ) -> None:
        load_dotenv()
        self.project_root = get_project_root()
        self.config_path = config_path or (self.project_root / "config" / "llm_config.json")
        self.prompt_path = prompt_path or (self.project_root / "prompts" / "llm_semantic_parser_prompt.txt")
        self.config = self._load_config()
        self.provider = str(self.config.get("provider", "openai"))
        self.enable_llm = _env_flag("ENABLE_LLM", True)
        self.enable_voice = _env_flag("ENABLE_VOICE", True)
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model_env_name = str(self.config.get("model_from_env", "PLC_LLM_MODEL"))
        self.transcription_model_env_name = str(self.config.get("transcription_model_from_env", "PLC_TRANSCRIPTION_MODEL"))
        self.model_name = os.getenv(self.model_env_name, "").strip()
        self.transcription_model = os.getenv(self.transcription_model_env_name, "").strip()
        self._client = client

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {
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
        payload = load_json_file(self.config_path)
        return payload if isinstance(payload, dict) else {}

    def _prompt_text(self) -> str:
        if not self.prompt_path.exists():
            return (
                "Convierte comandos industriales en JSON semántico estructurado. "
                "No inventes tags ni generes código."
            )
        return self.prompt_path.read_text(encoding="utf-8").strip()

    def _client_instance(self) -> Any:
        if self._client is not None:
            return self._client
        if OpenAI is None:
            raise RuntimeError("El SDK openai no está instalado.")
        self._client = OpenAI(api_key=self.api_key or None, timeout=self.config.get("request_timeout_seconds", 45))
        return self._client

    def is_configured(self) -> bool:
        return bool(self.enable_llm and self.api_key and self.model_name and self.provider == "openai" and OpenAI is not None)

    def is_transcription_configured(self) -> bool:
        return bool(self.enable_voice and self.api_key and self.transcription_model and self.provider == "openai" and OpenAI is not None)

    def get_transcription_model(self) -> str | None:
        return self.transcription_model or None

    def get_openai_client(self) -> Any:
        if not self.is_configured() and not self.is_transcription_configured():
            raise RuntimeError("No existe configuración activa para OpenAI.")
        return self._client_instance()

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "sdk_available": OpenAI is not None,
            "enable_llm": self.enable_llm,
            "enable_voice": self.enable_voice,
            "llm_configured": self.is_configured(),
            "transcription_configured": self.is_transcription_configured(),
            "model_env_name": self.model_env_name,
            "model_configured": bool(self.model_name),
            "transcription_model_env_name": self.transcription_model_env_name,
            "transcription_model_configured": bool(self.transcription_model)
        }

    def connectivity_check(self) -> dict[str, Any]:
        health = self.health_check()
        response_payload = dict(health)
        response_payload.update(
            {
                "live_connection": False,
                "request_id": None,
                "latency_ms": None,
                "error": None
            }
        )

        if not self.is_configured():
            response_payload["error"] = (
                "El cliente LLM no esta configurado. Defina OPENAI_API_KEY y PLC_LLM_MODEL."
            )
            return response_payload

        started_at = time.perf_counter()
        try:
            client = self._client_instance()
            response = client.responses.create(
                model=self.model_name,
                input="Responde solo OK",
                max_output_tokens=16
            )
            response_payload["live_connection"] = True
            response_payload["request_id"] = getattr(response, "id", None)
            response_payload["latency_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
        except Exception as error:  # pragma: no cover - depends on external API access
            response_payload["error"] = str(error)

        return response_payload

    def _build_messages(self, command_text: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        system_prompt = self._prompt_text()
        # Normal is an explicit profile. Its composition/control rules must have
        # instruction priority over the historical closed-catalog prompt.
        policy = context.get('normal_mode_policy')
        if isinstance(policy, str) and policy:
            system_prompt += '\n\nREGLAS PRIORITARIAS DEL PERFIL NORMAL:\n' + policy
            system_prompt += (
                '\nCONTRATO DE RESPUESTA: devuelve solo el objeto semantico. Sus unicos campos superiores permitidos son: '
                + ', '.join(SemanticOutput.model_fields)
                + '. Los campos de context (incluido requested_control_behavior) son solo metadatos de entrada; '
                'no los copies como campos nuevos de la respuesta. No generes codigo ni modifiques el esquema.'
            )
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "command_text": command_text,
                        "context": context
                    },
                    ensure_ascii=False,
                    indent=2
                )
            }
        ]

    @staticmethod
    def _extract_json_object(raw_text: str) -> str:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if "\n" in cleaned:
                cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0].strip()

        start_index = cleaned.find("{")
        end_index = cleaned.rfind("}")
        if start_index == -1 or end_index == -1 or end_index <= start_index:
            raise ValueError("La respuesta del modelo no contiene un objeto JSON valido.")
        return cleaned[start_index:end_index + 1]

    def _parse_semantic_response(self, response: Any) -> SemanticOutput:
        raw_text = getattr(response, "output_text", "") or ""
        if not raw_text:
            raise RuntimeError("El modelo no devolvio contenido interpretable.")

        payload = json.loads(self._extract_json_object(raw_text))
        return validate_semantic_model(payload)

    def interpret_command(
        self,
        command_text: str,
        context: dict[str, Any]
    ) -> tuple[SemanticOutput, LLMUsageMetadata]:
        if not self.is_configured():
            raise RuntimeError(
                "El cliente LLM no está configurado. Defina OPENAI_API_KEY y la variable de modelo indicada."
            )

        retries = int(self.config.get("max_retries", 2))
        timeout_seconds = int(self.config.get("request_timeout_seconds", 45))
        last_error: str | None = None
        request_context = dict(context)

        for attempt in range(retries + 1):
            started_at = time.perf_counter()
            try:
                client = self._client_instance()
                response = client.responses.create(
                    model=self.model_name,
                    input=self._build_messages(command_text, request_context),
                    timeout=timeout_seconds
                )
                latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
                usage = getattr(response, "usage", None)
                usage_payload = LLMUsageMetadata(
                    provider=self.provider,
                    model=self.model_name,
                    request_id=getattr(response, "id", None),
                    prompt_tokens=getattr(usage, "input_tokens", None),
                    completion_tokens=getattr(usage, "output_tokens", None),
                    total_tokens=getattr(usage, "total_tokens", None),
                    latency_ms=latency_ms,
                    retries_used=attempt,
                    used_fallback=False,
                    structured_output=bool(self.config.get("require_structured_output", True)),
                    error=None
                )
                parsed_output = self._parse_semantic_response(response)
                return parsed_output, usage_payload
            except (APITimeoutError, APIConnectionError, RuntimeError, ValueError, json.JSONDecodeError) as error:
                last_error = str(error)
                if attempt >= retries:
                    break
                if context.get('normal_mode_policy') and isinstance(error, ValueError):
                    # Keep strict validation. Correct the representation on the bounded
                    # retry instead of repeating an identical malformed response request.
                    request_context['response_format_correction'] = (
                        'La respuesta anterior incumplio el contrato JSON semantico: '
                        + last_error[:2000]
                        + '. Devuelve el mismo comportamiento solicitado con los campos permitidos, '
                        'sin copiar metadatos del contexto ni agregar claves superiores.'
                    )

        raise RuntimeError(f"No fue posible interpretar el comando con el LLM: {last_error}")


def build_runtime_llm_context(
    command_text: str,
    io_map: dict[str, Any],
    intents_catalog: dict[str, Any],
    safety_rules: dict[str, Any]
) -> dict[str, Any]:
    return build_llm_context(
        command_text=command_text,
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules
    )
