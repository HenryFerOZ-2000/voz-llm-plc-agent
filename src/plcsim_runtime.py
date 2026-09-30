"""
Fase 2A: lectura (SOLO LECTURA) del estado real de S7-PLCSIM Advanced V5 via Runtime API.

El bridge C# (plcsim_runtime_bridge/Program.cs) solo reporta hechos crudos: Runtime Manager,
instancias registradas, OperatingState/IPs de la instancia y el adaptador de Windows. Las
decisiones viven aqui, en funciones puras testeables:

  - codigo de estado (CONNECTED / PLCSIM_INSTANCE_NOT_FOUND / PLCSIM_INSTANCE_AMBIGUOUS / ...);
  - comprobacion informativa de subred (NETWORK_CONFIGURATION_MISMATCH) entre la IP que la
    Runtime API reporta para el controlador y la IP que Windows reporta para el adaptador
    PLCSIM. Nunca se corrige nada: ni IP, ni mascara, ni interfaz, ni mapping;
  - cpu_run_confirmed: True solo si Start Module fue solicitado Y OperatingState == RUN.
    Una descarga exitosa NUNCA implica RUN por si sola.

Tres fuentes de red distintas, que nunca se mezclan:
  1. download_configuration: lo configurado para DownloadProvider (config/tia_openness_config.json);
  2. runtime: lo que la instancia PLCSIM reporta (ControllerIPSuite4);
  3. windows: lo que Windows reporta del adaptador PLCSIM (System.Net.NetworkInformation).
La IP de X1 del PROYECTO TIA (project_plc_ip) no se lee en Fase 2A: Openness V18 solo la expone
como atributo dinamico de Node (GetAttribute("Address")), no verificable estaticamente.
"""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from utils import get_project_root, load_json_file

DEFAULT_RUNTIME_API_DLL = Path(
    r"C:\Program Files (x86)\Common Files\Siemens\PLCSIMADV\API\5.0\Siemens.Simatic.Simulation.Runtime.Api.x64.dll"
)
DEFAULT_COMPILER = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
DEFAULT_WEB_EXTENSIONS = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Web.Extensions.dll")
DEFAULT_INSTANCE_NAME = "TESIS_PLC_SIM"
DEFAULT_ADAPTER_MATCH = "PLCSIM Virtual Ethernet Adapter"
DEFAULT_TIMEOUT_SECONDS = 20
# Fase 2B: tiempo de asentamiento tras cada escritura (conservador; los tiempos del Oracle vendran
# despues) y tiempo maximo de una operacion de Runtime I/O.
DEFAULT_IO_SETTLE_MS = 500
DEFAULT_IO_TIMEOUT_SECONDS = 60

REPORT_FILENAME = "plcsim_runtime_report.json"

ACTION_STATUS = "status"
ACTION_RUNTIME_STATUS = "runtime_status"

STATUS_CONNECTED = "CONNECTED"
STATUS_INSTANCE_FOUND = "INSTANCE_FOUND"
STATUS_INSTANCE_NOT_FOUND = "PLCSIM_INSTANCE_NOT_FOUND"
STATUS_INSTANCE_AMBIGUOUS = "PLCSIM_INSTANCE_AMBIGUOUS"
STATUS_RUNTIME_UNAVAILABLE = "PLCSIM_RUNTIME_UNAVAILABLE"
STATUS_API_NOT_AVAILABLE = "PLCSIM_API_NOT_AVAILABLE"
STATUS_RUNTIME_TIMEOUT = "PLCSIM_RUNTIME_TIMEOUT"
STATUS_BRIDGE_BUILD_FAILED = "PLCSIM_BRIDGE_BUILD_FAILED"
STATUS_RUNTIME_ERROR = "PLCSIM_RUNTIME_ERROR"

NETWORK_MATCH = "MATCH"
NETWORK_MISMATCH = "NETWORK_CONFIGURATION_MISMATCH"
NETWORK_UNKNOWN = "UNKNOWN"

CPU_STATE_RUN = "RUN"

_BRIDGE_STATUS_MAP = {
    "PLCSIM_RUNTIME_PASSED": STATUS_CONNECTED,
    "PLCSIM_INSTANCE_NOT_FOUND": STATUS_INSTANCE_NOT_FOUND,
    "PLCSIM_INSTANCE_AMBIGUOUS": STATUS_INSTANCE_AMBIGUOUS,
    "PLCSIM_RUNTIME_UNAVAILABLE": STATUS_RUNTIME_UNAVAILABLE,
    "PLCSIM_API_NOT_AVAILABLE": STATUS_API_NOT_AVAILABLE,
}


# ---------------------------------------------------------------------------------------------
# Configuracion y bridge
# ---------------------------------------------------------------------------------------------

def load_runtime_config(tia_config: dict[str, Any] | None) -> dict[str, Any]:
    """
    Seccion "plcsim_runtime" de config/tia_openness_config.json con valores por defecto. El patron
    del adaptador de Windows cae en el pc_interface de download_targets.normal si no se indica.
    """
    tia_config = tia_config or {}
    section = tia_config.get("plcsim_runtime") or {}
    normal_target = (tia_config.get("download_targets") or {}).get("normal") or {}
    return {
        "api_dll_path": str(section.get("api_dll_path") or DEFAULT_RUNTIME_API_DLL),
        "instance_name": str(section.get("instance_name") or DEFAULT_INSTANCE_NAME),
        "windows_adapter_match": str(
            section.get("windows_adapter_match") or normal_target.get("pc_interface") or DEFAULT_ADAPTER_MATCH
        ),
        "timeout_seconds": int(section.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
        "io_settle_ms": int(section.get("io_settle_ms") if section.get("io_settle_ms") is not None else DEFAULT_IO_SETTLE_MS),
        "io_timeout_seconds": int(section.get("io_timeout_seconds") or DEFAULT_IO_TIMEOUT_SECONDS),
    }


def download_configuration_summary(tia_config: dict[str, Any] | None, purpose: str = "normal") -> dict[str, Any]:
    """Fuente 1 (lo CONFIGURADO): nunca implica conexion."""
    target = ((tia_config or {}).get("download_targets") or {}).get(purpose) or {}
    return {
        "target_type": target.get("target_type"),
        "target_name": target.get("target_name"),
        "configuration_mode": target.get("configuration_mode"),
        "pc_interface": target.get("pc_interface"),
        "target_interface": target.get("target_interface"),
    }


def _bridge_paths(project_root: Path) -> dict[str, Path]:
    bridge_root = project_root / "plcsim_runtime_bridge"
    return {
        "root": bridge_root,
        "source": bridge_root / "Program.cs",
        "bin": bridge_root / "bin",
        "exe": bridge_root / "bin" / "PlcsimRuntimeBridge.exe",
    }


def build_runtime_bridge(project_root: Path | None = None, force: bool = False, api_dll: Path | None = None) -> dict[str, Any]:
    """csc x64 + referencia a la Runtime API instalada. La DLL NO se copia a bin/: el bridge la
    carga en tiempo de ejecucion desde su ruta instalada (AssemblyResolve)."""
    root = project_root or get_project_root()
    bridge = _bridge_paths(root)
    api_dll = Path(api_dll or DEFAULT_RUNTIME_API_DLL)
    references = [api_dll, DEFAULT_WEB_EXTENSIONS]
    missing = [str(path) for path in (DEFAULT_COMPILER, bridge["source"], *references) if not path.exists()]
    if missing:
        return {"built": False, "exe_path": str(bridge["exe"]), "errors": ["Faltan dependencias: " + ", ".join(missing)]}

    inputs = [bridge["source"], *references]
    if not force and bridge["exe"].exists() and bridge["exe"].stat().st_mtime >= max(p.stat().st_mtime for p in inputs):
        return {"built": True, "reused": True, "exe_path": str(bridge["exe"]), "errors": []}

    bridge["bin"].mkdir(parents=True, exist_ok=True)
    command = [
        str(DEFAULT_COMPILER), "/nologo", "/target:exe", "/platform:x64", "/optimize+",
        f"/out:{bridge['exe']}", *[f"/reference:{path}" for path in references], str(bridge["source"]),
    ]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=120, check=False)
    built = result.returncode == 0 and bridge["exe"].exists()
    # Si una compilacion anterior dejo una copia de la DLL junto al exe, se elimina para que
    # siempre se cargue la instalada.
    stale_copy = bridge["bin"] / api_dll.name
    if built and stale_copy.exists():
        stale_copy.unlink()
    return {
        "built": built,
        "reused": False,
        "exe_path": str(bridge["exe"]),
        "return_code": result.returncode,
        "errors": [] if built else ["No se pudo compilar el puente PLCSIM Runtime."],
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def run_runtime_bridge(
    action: str,
    project_root: Path | None = None,
    runtime_config: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Ejecuta el bridge y devuelve su reporte crudo (o un reporte sintetico si no pudo correr).
    `extra` anade campos al request (acciones de Runtime I/O de la Fase 2B)."""
    root = project_root or get_project_root()
    runtime_config = runtime_config or load_runtime_config(_load_tia_config(root))
    build = build_runtime_bridge(root, api_dll=Path(runtime_config["api_dll_path"]))
    if not build.get("built"):
        return {"status": "PLCSIM_BRIDGE_BUILD_FAILED", "errors": list(build.get("errors", [])), "build": build}

    work_dir = _bridge_paths(root)["root"]
    request_path = work_dir / "runtime_request.json"
    result_path = work_dir / "runtime_result.json"
    request = {
        "action": action,
        "result_path": str(result_path),
        "api_dll_path": runtime_config["api_dll_path"],
        "instance_name": runtime_config["instance_name"],
        "windows_adapter_match": runtime_config["windows_adapter_match"],
        **(extra or {}),
    }
    request_path.write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
    if result_path.exists():
        result_path.unlink()
    try:
        completed = subprocess.run(
            [build["exe_path"], str(request_path)],
            capture_output=True, text=True, errors="replace",
            timeout=timeout_seconds or runtime_config["timeout_seconds"], check=False, env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "PLCSIM_RUNTIME_TIMEOUT",
            "errors": [f"La Runtime API no respondio en {timeout_seconds or runtime_config['timeout_seconds']} s."],
        }
    raw: dict[str, Any] = {}
    if result_path.exists():
        payload = load_json_file(result_path)
        if isinstance(payload, dict):
            raw = payload
    if not raw:
        raw = {"status": STATUS_RUNTIME_ERROR, "errors": ["El bridge PLCSIM Runtime no produjo resultado."]}
    raw["bridge_return_code"] = completed.returncode
    raw["bridge_stderr"] = completed.stderr.strip()
    return raw


def _load_tia_config(project_root: Path) -> dict[str, Any]:
    path = project_root / "config" / "tia_openness_config.json"
    if not path.exists():
        return {}
    payload = load_json_file(path)
    return payload if isinstance(payload, dict) else {}


# ---------------------------------------------------------------------------------------------
# Decisiones (puras)
# ---------------------------------------------------------------------------------------------

def _network(ip: str | None, mask: str | None) -> ipaddress.IPv4Network | None:
    try:
        if not ip or not mask or ip == "0.0.0.0" or mask == "0.0.0.0":
            return None
        return ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
    except ValueError:
        return None


def evaluate_network(ip_suites: list[dict[str, Any]] | None, adapter: dict[str, Any] | None) -> dict[str, Any]:
    """
    Comprobacion INFORMATIVA: alguna IP que la Runtime API reporta para el controlador cae en la
    subred del adaptador PLCSIM de Windows (misma red con la mascara del adaptador y, si el
    controlador reporta mascara, la misma mascara). Nunca modifica nada.
    """
    adapter = adapter or {}
    adapter_ip = adapter.get("ip")
    adapter_mask = adapter.get("subnet_mask")
    adapter_net = _network(adapter_ip, adapter_mask)
    suites = [suite for suite in (ip_suites or []) if suite.get("ip") and suite.get("ip") != "0.0.0.0"]
    result = {
        "network_match": None,
        "network_status": NETWORK_UNKNOWN,
        "controller_ip": suites[0]["ip"] if suites else None,
        "controller_subnet_mask": suites[0].get("subnet_mask") if suites else None,
        "controller_ip_index": suites[0].get("index") if suites else None,
        "adapter_ip": adapter_ip,
        "adapter_subnet_mask": adapter_mask,
        "detail": "",
    }
    if adapter_net is None:
        result["detail"] = "Windows no reporta IPv4/mascara para el adaptador PLCSIM."
        return result
    if not suites:
        result["detail"] = "La Runtime API no reporta IP para el controlador."
        return result

    for suite in suites:
        controller_mask = suite.get("subnet_mask")
        same_mask = not controller_mask or controller_mask == "0.0.0.0" or controller_mask == adapter_mask
        if same_mask and ipaddress.IPv4Address(suite["ip"]) in adapter_net:
            result.update({
                "network_match": True,
                "network_status": NETWORK_MATCH,
                "controller_ip": suite["ip"],
                "controller_subnet_mask": controller_mask,
                "controller_ip_index": suite.get("index"),
                "detail": f"Controlador {suite['ip']} y adaptador {adapter_ip} en la misma subred {adapter_net}.",
            })
            return result
    listed = ", ".join(f"{s['ip']}/{s.get('subnet_mask')}" for s in suites)
    result.update({
        "network_match": False,
        "network_status": NETWORK_MISMATCH,
        "detail": f"Ninguna IP del controlador ({listed}) esta en la subred del adaptador {adapter_ip}/{adapter_mask}.",
    })
    return result


def normalize_cpu_state(raw_state: Any) -> str | None:
    """EOperatingState de la API ("Run", "Stop", "Off", ...) -> mayusculas; None si no se leyo."""
    if raw_state is None or str(raw_state).strip() == "":
        return None
    return str(raw_state).strip().upper()


def evaluate_runtime_report(
    raw: dict[str, Any],
    tia_config: dict[str, Any] | None = None,
    runtime_config: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """Reporte final plcsim_runtime_report.json a partir del reporte crudo del bridge."""
    runtime_config = runtime_config or load_runtime_config(tia_config)
    bridge_status = str(raw.get("status", ""))
    status = _BRIDGE_STATUS_MAP.get(bridge_status, bridge_status or STATUS_RUNTIME_ERROR)
    instance = raw.get("instance") if isinstance(raw.get("instance"), dict) else None
    if status == STATUS_CONNECTED and instance is None:
        # Accion "status": la instancia existe pero no se abrio -> no hay estado de CPU.
        status = STATUS_INSTANCE_FOUND
    connected = status == STATUS_CONNECTED
    cpu_state = normalize_cpu_state(instance.get("operating_state")) if connected else None
    adapter = raw.get("windows_adapter") if isinstance(raw.get("windows_adapter"), dict) else {}
    network = evaluate_network((instance or {}).get("ip_suites"), adapter)

    warnings = [str(item) for item in raw.get("warnings", []) or []]
    if network["network_status"] == NETWORK_MISMATCH:
        warnings.append(f"{NETWORK_MISMATCH}: {network['detail']}")
    if adapter.get("ambiguous"):
        warnings.append("Mas de un adaptador de Windows coincide con el patron configurado; no se compara subred.")
    if instance and instance.get("read_errors"):
        warnings.extend(f"Lectura parcial: {item}" for item in instance["read_errors"])

    return {
        "status": status,
        "bridge_status": bridge_status,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "duration_ms": duration_ms,
        "connected": connected,
        "instance_name": runtime_config["instance_name"],
        "instance_found": bool(raw.get("instance_found")),
        "registered_instances": list(raw.get("registered_instances") or []),
        "cpu_state": cpu_state,
        "cpu_run": connected and cpu_state == CPU_STATE_RUN,
        "cpu_type": (instance or {}).get("cpu_type"),
        "controller_name": (instance or {}).get("controller_name"),
        "controller_short_designation": (instance or {}).get("controller_short_designation"),
        "communication_interface": (instance or {}).get("communication_interface"),
        "controller_ip": network["controller_ip"],
        "controller_subnet_mask": network["controller_subnet_mask"],
        "adapter_ip": network["adapter_ip"],
        "adapter_subnet_mask": network["adapter_subnet_mask"],
        "network_match": network["network_match"],
        "network_status": network["network_status"],
        "network_detail": network["detail"],
        "network_sources": {
            "download_configuration": download_configuration_summary(tia_config),
            "runtime": {
                "ip_suites": list((instance or {}).get("ip_suites") or []),
                "note": "Indices de ControllerIPSuite4; la API V5 no indica si corresponden a X1 o X2.",
            },
            "windows": {
                key: adapter.get(key)
                for key in ("match_pattern", "found", "ambiguous", "name", "description", "operational_status", "ip", "subnet_mask")
            },
            "project": {
                "project_plc_ip": None,
                "project_subnet_mask": None,
                "status": "NOT_READ_PHASE_2A",
                "note": "Openness V18 solo expone la IP del nodo X1 como atributo dinamico (Node.GetAttribute), no verificado.",
            },
        },
        "api": raw.get("api"),
        "errors": [str(item) for item in raw.get("errors", []) or []],
        "warnings": warnings,
    }


def is_cpu_run_confirmed(download_report: dict[str, Any] | None, runtime_report: dict[str, Any] | None) -> bool | None:
    """
    True solo si Start Module fue solicitado Y la Runtime API confirma OperatingState == RUN.
    None si la Runtime API no pudo verificarlo (no conectada): nunca se infiere RUN de una descarga.
    """
    if not runtime_report or not runtime_report.get("connected"):
        return None
    requested = bool((download_report or {}).get("cpu_run_requested"))
    return requested and runtime_report.get("cpu_state") == CPU_STATE_RUN


def trial_runtime_section(runtime_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "connected": bool(runtime_report.get("connected")),
        "instance_name": runtime_report.get("instance_name"),
        "cpu_state": runtime_report.get("cpu_state"),
        "controller_ip": runtime_report.get("controller_ip"),
        "adapter_ip": runtime_report.get("adapter_ip"),
        "network_match": runtime_report.get("network_match"),
    }


def format_log_lines(runtime_report: dict[str, Any]) -> list[str]:
    prefix = "[PLCSIM RUNTIME]"
    lines = [f"{prefix} Estado: {runtime_report.get('status')}"]
    if runtime_report.get("connected"):
        lines.append(f"{prefix} Instancia: {runtime_report.get('instance_name')} ({runtime_report.get('cpu_type')})")
        lines.append(f"{prefix} OperatingState: {runtime_report.get('cpu_state')}")
        lines.append(
            f"{prefix} Red: PLC {runtime_report.get('controller_ip')} | PC {runtime_report.get('adapter_ip')} "
            f"-> {runtime_report.get('network_status')}"
        )
    elif runtime_report.get("status") == STATUS_INSTANCE_NOT_FOUND:
        names = ", ".join(str(item.get("name")) for item in runtime_report.get("registered_instances", [])) or "(ninguna)"
        lines.append(f"{prefix} Instancia '{runtime_report.get('instance_name')}' no encontrada. Registradas: {names}")
    for error in runtime_report.get("errors", []):
        lines.append(f"{prefix} ERROR: {error}")
    for warning in runtime_report.get("warnings", []):
        lines.append(f"{prefix} AVISO: {warning}")
    return lines


def write_runtime_report(directory: Path, runtime_report: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / REPORT_FILENAME
    path.write_text(json.dumps(runtime_report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def apply_runtime_confirmation(package_dir: Path | None, runtime_report: dict[str, Any]) -> bool | None:
    """Completa cpu_run_confirmed en tia_download_report.json del paquete (evidencia coherente)."""
    if package_dir is None:
        return None
    path = package_dir / "tia_download_report.json"
    download_report = load_json_file(path) if path.exists() else None
    if not isinstance(download_report, dict):
        return None
    confirmed = is_cpu_run_confirmed(download_report, runtime_report)
    download_report["cpu_run_confirmed"] = confirmed
    download_report["cpu_run_confirmed_source"] = "PLCSIM_RUNTIME_API" if confirmed is not None else None
    download_report["runtime_cpu_state"] = runtime_report.get("cpu_state")
    path.write_text(json.dumps(download_report, indent=2, ensure_ascii=False), encoding="utf-8")
    return confirmed


def get_plcsim_runtime_status(project_root: Path | None = None, action: str = ACTION_RUNTIME_STATUS) -> dict[str, Any]:
    """Punto de entrada (bloqueante: la GUI lo llama desde un hilo de trabajo)."""
    root = project_root or get_project_root()
    tia_config = _load_tia_config(root)
    runtime_config = load_runtime_config(tia_config)
    started = time.perf_counter()
    raw = run_runtime_bridge(action, root, runtime_config)
    duration_ms = int(round((time.perf_counter() - started) * 1000))
    report = evaluate_runtime_report(raw, tia_config, runtime_config, duration_ms)
    write_runtime_report(_bridge_paths(root)["root"], report)
    return report


__all__ = [
    "ACTION_RUNTIME_STATUS",
    "ACTION_STATUS",
    "NETWORK_MISMATCH",
    "STATUS_CONNECTED",
    "apply_runtime_confirmation",
    "build_runtime_bridge",
    "evaluate_network",
    "evaluate_runtime_report",
    "format_log_lines",
    "get_plcsim_runtime_status",
    "is_cpu_run_confirmed",
    "load_runtime_config",
    "trial_runtime_section",
    "write_runtime_report",
]

