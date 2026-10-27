from __future__ import annotations

from typing import Any

EXPERIMENT_FAMILIES = ["DISCRETE", "PID"]

# C0 fue eliminado del diseno del Modo Experimentacion. Esta taxonomia de 4 condiciones
# es especifica de la GUI y coexiste con la C0-C5 de docs/14_protocolo_evaluacion.md /
# src/evaluation_runner.py (harness batch independiente, no modificado por este modulo).
CONDITIONS: dict[str, dict[str, Any]] = {
    "C1": {
        "label": "C1 - LLM directo desde texto",
        "parser_mode": "llm",
        "requires_voice": False,
        "noise_locked_to": "none"
    },
    "C2": {
        "label": "C2 - Texto estructurado + LLM + verificacion",
        "parser_mode": "hybrid",
        "requires_voice": False,
        "noise_locked_to": "none"
    },
    "C3": {
        "label": "C3 - Voz + ASR + interpretacion + LLM + verificacion",
        "parser_mode": "hybrid",
        "requires_voice": True,
        "noise_locked_to": None
    },
    "C4": {
        "label": "C4 - Voz con ruido industrial simulado",
        "parser_mode": "hybrid",
        "requires_voice": True,
        "noise_locked_to": None,
        "noise_required": True
    }
}

NOISE_LEVELS = ["none", "medium", "high"]
NOISE_LEVEL_LABELS = {
    "none": "Sin ruido",
    "medium": "Ruido medio",
    "high": "Ruido alto"
}

ENVIRONMENTS = ["simulation", "hardware"]
ENVIRONMENT_LABELS = {
    "simulation": "Simulacion",
    "hardware": "Hardware"
}

ERROR_CODES: dict[str, str] = {
    "E1": "Voz",
    "E2": "Semantico",
    "E3": "Variable",
    "E4": "Sintaxis",
    "E5": "Compilacion",
    "E6": "Logico",
    "E7": "Seguridad",
    "E8": "Ejecucion",
    "E9": "Proceso",
    "E10": "Trazabilidad"
}
NO_ERROR_LABEL = "Ninguno"

PHYSICAL_RESULT_OPTIONS = ["Correcto", "Incorrecto", "No ejecutado"]

TRIAL_STATES = ["READY", "RUNNING", "AWAITING_MANUAL_RESULT", "COMPLETED", "CANCELLED", "ERROR"]

MASTER_LOG_FIELDS = [
    "trial_id", "experiment_label", "case_id", "condition", "variant", "repetition",
    "speaker_id", "noise_level", "compile_result", "execution_result", "safety_violation",
    "total_time", "error_type", "timestamp", "map_name", "profile_id"
]
