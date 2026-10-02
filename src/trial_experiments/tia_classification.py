"""
Clasificacion COMPILE vs INFRASTRUCTURE de un resultado de TIA Openness (Fase 4A-DEFERRED).

Regla: COMPILE_FAILURE solo si TIA siguio operativo Y el compilador (o la generacion de bloques
desde la fuente) devolvio errores atribuibles al programa generado. Todo lo que delata una caida
o indisponibilidad de TIA/Openness/bridge/PLCSIM es INFRASTRUCTURE_ERROR y nunca cuenta como
fallo del sistema evaluado.
"""
from __future__ import annotations

from typing import Any

COMPILE_PASSED = "COMPILE_PASSED"
COMPILE_FAILURE = "COMPILE_FAILURE"
INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"

# Estados del bridge que significan "TIA respondio y el programa no compila".
_PROGRAM_FAILURE_STATUSES = {"TIA_COMPILATION_FAILED"}

# Excepciones de Openness atribuibles a la FUENTE generada (sintaxis/semantica SCL al generar
# bloques): TIA sigue operativo. Cualquier otra excepcion es infraestructura.
_PROGRAM_EXCEPTION_TYPES = ("EngineeringTargetInvocationException",)
_PROGRAM_EXCEPTION_STAGES = {"generate_blocks"}

# Huellas de caida/indisponibilidad (en tipo de excepcion o mensaje).
INFRASTRUCTURE_MARKERS = (
    "NonRecoverableException",
    "EngineeringObjectDisposedException",
    "EngineeringRuntimeException",
    "EngineeringSecurityException",
    "COMException",
    "RemotingException",
    "RPC server",
    "connection",
    "Connection",
    "process has exited",
    "TiaPortal process",
    "timed out",
    "timeout",
    "Timeout",
    "OutOfMemory",
    "paging file",
)

# Estados que ni siquiera llegaron a compilar por falta de entorno.
_INFRASTRUCTURE_STATUSES = {
    "TIA_NOT_READY", "BRIDGE_BUILD_FAILED", "TIA_BRIDGE_TIMEOUT", "TIA_BRIDGE_CRASHED", "TIA_PROJECT_RETRIEVE_FAILED",
    "TIA_TAG_SYNC_ERROR_INFRA",
}


def _text(report: dict[str, Any]) -> str:
    parts = [str(report.get("exception") or ""), str(report.get("exception_type") or "")]
    parts.extend(str(error) for error in report.get("errors") or [])
    return " ".join(parts)


def classify_tia_compile(report: dict[str, Any] | None) -> dict[str, Any]:
    """
    Devuelve {category, reason, tia_operational}. category en COMPILE_PASSED / COMPILE_FAILURE /
    INFRASTRUCTURE_ERROR. Un reporte vacio (bridge muerto sin escribir resultado) es infraestructura.
    """
    if not report:
        return {"category": INFRASTRUCTURE_ERROR, "reason": "TIA_BRIDGE_NO_REPORT", "tia_operational": False}
    status = str(report.get("status") or "")
    text = _text(report)
    if status == "TIA_COMPILATION_PASSED":
        return {"category": COMPILE_PASSED, "reason": status, "tia_operational": True}
    if status in _INFRASTRUCTURE_STATUSES:
        return {"category": INFRASTRUCTURE_ERROR, "reason": status, "tia_operational": False}
    if status in _PROGRAM_FAILURE_STATUSES:
        error_count = report.get("error_count")
        if isinstance(error_count, int) and error_count > 0:
            return {"category": COMPILE_FAILURE, "reason": f"{status} ({error_count} errores del compilador)", "tia_operational": True}
        return {"category": INFRASTRUCTURE_ERROR, "reason": f"{status} sin errores del compilador", "tia_operational": False}
    if any(marker in text for marker in INFRASTRUCTURE_MARKERS):
        marker = next(marker for marker in INFRASTRUCTURE_MARKERS if marker in text)
        return {"category": INFRASTRUCTURE_ERROR, "reason": f"{status or 'TIA_OPENNESS_ERROR'}: {marker}", "tia_operational": False}
    if (any(kind in text for kind in _PROGRAM_EXCEPTION_TYPES)
            and str(report.get("failed_stage") or "") in _PROGRAM_EXCEPTION_STAGES):
        return {"category": COMPILE_FAILURE, "reason": "La fuente generada no pudo convertirse en bloques (TIA operativo).",
                "tia_operational": True}
    # Excepcion desconocida: sin evidencia de que TIA siguiera operativo -> infraestructura.
    return {"category": INFRASTRUCTURE_ERROR, "reason": f"{status or 'UNKNOWN'}: excepcion no atribuible al programa",
            "tia_operational": False}
