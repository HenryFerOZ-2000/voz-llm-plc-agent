"""
Precheck de memoria antes de abrir una sesion TIA (Fase 4A-TIA-STABILITY).

Fallo real (D03_V1_TEXT_DEV_002 / T0001): System.OutOfMemoryException DENTRO de TIA Portal V18
con la memoria comprometida casi en el limite. Antes de crear una sesion Openness se mide:

  available_physical  -> RAM fisica disponible
  committed / commit_limit / commit_headroom (= commit_limit - committed)

Si no alcanza los minimos configurados (tia_openness_config.json -> tia_memory_preflight), la
evaluacion se detiene como INFRASTRUCTURE_ERROR (INSUFFICIENT_MEMORY_FOR_TIA) sin abrir TIA.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any

ERROR_INSUFFICIENT_MEMORY = "INSUFFICIENT_MEMORY_FOR_TIA"
CONFIG_KEY = "tia_memory_preflight"
# Defaults de DEVELOPMENT: configurables en tia_openness_config.json -> tia_memory_preflight.
DEFAULT_PREFLIGHT = {"enabled": True, "min_available_physical_gb": 4, "min_commit_headroom_gb": 8}
_MB = 1024 * 1024


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def measure_memory() -> dict[str, Any]:
    """Medicion usada por el precheck (las pruebas la sustituyen por valores controlados)."""
    return read_memory_status()


def read_memory_status() -> dict[str, Any]:
    """GlobalMemoryStatusEx: ullTotalPageFile = limite de commit; ullAvailPageFile = margen de commit."""
    if os.name != "nt":
        return {"available": False, "error": "solo Windows"}
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {"available": False, "error": "GlobalMemoryStatusEx fallo"}
    return {
        "available": True,
        "total_physical_mb": int(status.ullTotalPhys // _MB),
        "available_physical_mb": int(status.ullAvailPhys // _MB),
        "commit_limit_mb": int(status.ullTotalPageFile // _MB),
        "committed_mb": int((status.ullTotalPageFile - status.ullAvailPageFile) // _MB),
        "commit_headroom_mb": int(status.ullAvailPageFile // _MB),
    }


def preflight_settings(project_root: Path) -> dict[str, Any]:
    import tia_openness

    configured = tia_openness.load_tia_config(project_root).get(CONFIG_KEY) or {}
    return {**DEFAULT_PREFLIGHT, **(configured if isinstance(configured, dict) else {})}


def memory_preflight(project_root: Path, measure=None) -> dict[str, Any]:
    """Devuelve {ok, error_code, errors, metrics, settings}. Medicion imposible -> no bloquea, se registra."""
    settings = preflight_settings(project_root)
    metrics = (measure or measure_memory)()
    result = {"ok": True, "error_code": None, "errors": [], "metrics": metrics, "settings": settings}
    if not settings.get("enabled", True):
        result["skipped"] = "disabled"
        return result
    if not metrics.get("available"):
        result["warning"] = f"No se pudo medir la memoria: {metrics.get('error')}"
        return result
    min_physical = float(settings["min_available_physical_gb"]) * 1024
    min_headroom = float(settings["min_commit_headroom_gb"]) * 1024
    if metrics["available_physical_mb"] < min_physical:
        result["errors"].append(f"{ERROR_INSUFFICIENT_MEMORY}: RAM fisica disponible {metrics['available_physical_mb']} MB "
                                f"< {int(min_physical)} MB")
    if metrics["commit_headroom_mb"] < min_headroom:
        result["errors"].append(f"{ERROR_INSUFFICIENT_MEMORY}: margen de commit {metrics['commit_headroom_mb']} MB "
                                f"< {int(min_headroom)} MB (comprometido {metrics['committed_mb']} / limite {metrics['commit_limit_mb']} MB)")
    if result["errors"]:
        result.update({"ok": False, "error_code": ERROR_INSUFFICIENT_MEMORY})
    return result
