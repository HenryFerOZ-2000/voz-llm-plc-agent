from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from plc_maps.registry import resolve_active_map_path
from platforms.siemens_scl_adapter import SIEMENS_TYPE_MAP
from utils import get_project_root, load_json_file


TIA_PLATFORM = "SIEMENS_SCL_V18"
DEFAULT_API_DLL = Path(
    r"C:\Program Files\Siemens\Automation\Portal V18\PublicAPI\V18\Siemens.Engineering.dll"
)
DEFAULT_COMPILER = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
DEFAULT_WEB_EXTENSIONS = Path(
    r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Web.Extensions.dll"
)
DEFAULT_PORTAL_ROOT = Path(r"C:\Program Files\Siemens\Automation\Portal V18")


def get_tia_config_path(project_root: Path | None = None) -> Path:
    root = project_root or get_project_root()
    return root / "config" / "tia_openness_config.json"


def load_tia_config(project_root: Path | None = None) -> dict[str, Any]:
    config_path = get_tia_config_path(project_root)
    if not config_path.exists():
        return {}
    payload = load_json_file(config_path)
    return payload if isinstance(payload, dict) else {}


def save_tia_config(config: dict[str, Any], project_root: Path | None = None) -> Path:
    config_path = get_tia_config_path(project_root)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return config_path


def _bridge_paths(project_root: Path | None = None) -> dict[str, Path]:
    root = project_root or get_project_root()
    bridge_root = root / "tia_openness_bridge"
    bin_dir = bridge_root / "bin"
    return {
        "root": bridge_root,
        "source": bridge_root / "Program.cs",
        "bin": bin_dir,
        "exe": bin_dir / "TiaOpennessBridge.exe"
    }


def _current_token_has_openness_group() -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["whoami", "/groups", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
            check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "siemens tia openness" in result.stdout.lower()


def diagnose_tia_openness(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or get_project_root()
    config = load_tia_config(root)
    api_dll = Path(config.get("api_dll_path") or DEFAULT_API_DLL)
    bridge = _bridge_paths(root)
    project_path_text = str(config.get("project_path", "")).strip()
    project_path = Path(project_path_text) if project_path_text else None
    compiler = DEFAULT_COMPILER

    checks = {
        "windows": os.name == "nt",
        "tia_portal_v18_api": api_dll.exists(),
        "csharp_compiler": compiler.exists(),
        "bridge_source": bridge["source"].exists(),
        "bridge_built": bridge["exe"].exists(),
        "openness_group_in_current_session": _current_token_has_openness_group(),
        "project_configured": project_path is not None,
        "project_exists": bool(project_path and project_path.exists())
    }
    warnings: list[str] = []
    if not checks["openness_group_in_current_session"]:
        warnings.append(
            "El usuario actual no pertenece al grupo Siemens TIA Openness en esta sesion. "
            "Agreguelo como administrador y cierre sesion antes de ejecutar la integracion."
        )
    if not checks["project_configured"]:
        warnings.append("Seleccione un proyecto .ap18 con una CPU desde la configuracion TIA.")
    elif not checks["project_exists"]:
        warnings.append(f"No existe el proyecto TIA configurado: {project_path}")

    return {
        "is_installed": checks["tia_portal_v18_api"],
        "is_ready": all(
            checks[key]
            for key in (
                "windows",
                "tia_portal_v18_api",
                "csharp_compiler",
                "bridge_source",
                "bridge_built",
                "openness_group_in_current_session",
                "project_configured",
                "project_exists"
            )
        ),
        "tia_version": "V18",
        "api_dll_path": str(api_dll),
        "bridge_exe_path": str(bridge["exe"]),
        "project_path": str(project_path) if project_path else "",
        "plc_name": config.get("plc_name", ""),
        "checks": checks,
        "warnings": warnings
    }


def build_openness_bridge(
    project_root: Path | None = None,
    force: bool = False
) -> dict[str, Any]:
    root = project_root or get_project_root()
    config = load_tia_config(root)
    api_dll = Path(config.get("api_dll_path") or DEFAULT_API_DLL)
    bridge = _bridge_paths(root)
    bridge["bin"].mkdir(parents=True, exist_ok=True)

    references = [
        api_dll,
        DEFAULT_PORTAL_ROOT / "PublicAPI" / "V18" / "Siemens.Engineering.Hmi.dll",
        DEFAULT_PORTAL_ROOT / "Bin" / "PublicAPI" / "Siemens.Engineering.Contract.dll",
        DEFAULT_PORTAL_ROOT / "Bin" / "PublicAPI" / "Siemens.Engineering.ClientAdapter.Interfaces.dll",
        DEFAULT_WEB_EXTENSIONS
    ]
    missing = [str(path) for path in [DEFAULT_COMPILER, bridge["source"], *references] if not path.exists()]
    if missing:
        return {
            "built": False,
            "exe_path": str(bridge["exe"]),
            "errors": ["Faltan dependencias: " + ", ".join(missing)],
            "stdout": "",
            "stderr": ""
        }

    build_inputs = [bridge["source"], *references]
    if (
        not force
        and bridge["exe"].exists()
        and bridge["exe"].stat().st_mtime >= max(path.stat().st_mtime for path in build_inputs)
    ):
        return {
            "built": True,
            "reused": True,
            "exe_path": str(bridge["exe"]),
            "return_code": 0,
            "errors": [],
            "stdout": "Puente existente actualizado; no fue necesario recompilar.",
            "stderr": ""
        }

    command = [
        str(DEFAULT_COMPILER),
        "/nologo",
        "/target:exe",
        "/platform:x64",
        "/optimize+",
        f"/out:{bridge['exe']}",
        *[f"/reference:{path}" for path in references],
        str(bridge["source"])
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
        check=False
    )
    built = result.returncode == 0 and bridge["exe"].exists()
    if built:
        shutil.copy2(api_dll, bridge["bin"] / api_dll.name)
        hmi_dll = references[1]
        shutil.copy2(hmi_dll, bridge["bin"] / hmi_dll.name)
    return {
        "built": built,
        "reused": False,
        "exe_path": str(bridge["exe"]),
        "return_code": result.returncode,
        "errors": [] if built else ["No se pudo compilar el puente TIA Openness."],
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip()
    }


def run_openness_bridge_diagnostic(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or get_project_root()
    bridge = _bridge_paths(root)
    if not bridge["exe"].exists():
        build_result = build_openness_bridge(root)
        if not build_result.get("built"):
            return {
                "executed": False,
                "status": "BRIDGE_BUILD_FAILED",
                "build": build_result
            }

    environment = os.environ.copy()
    portal_bin = str(DEFAULT_PORTAL_ROOT / "Bin")
    environment["PATH"] = portal_bin + os.pathsep + environment.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="tia_diag_") as temp_dir:
        request_path = Path(temp_dir) / "request.json"
        result_path = Path(temp_dir) / "result.json"
        request_path.write_text(
            json.dumps(
                {
                    "action": "diagnose",
                    "result_path": str(result_path)
                },
                indent=2
            ),
            encoding="utf-8"
        )
        result = subprocess.run(
            [str(bridge["exe"]), str(request_path)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
            check=False,
            env=environment
        )
        report = load_json_file(result_path) if result_path.exists() else {}

    if not isinstance(report, dict):
        report = {}
    report.update(
        {
            "executed": True,
            "bridge_return_code": result.returncode,
            "bridge_stdout": result.stdout.strip(),
            "bridge_stderr": result.stderr.strip()
        }
    )
    return report


def _normalize_siemens_address(raw_address: str) -> str:
    return str(raw_address or "").replace("%IX", "%I").replace("%QX", "%Q").replace("%MX", "%M")


def _load_locked_persistent_tags(project_root: Path) -> list[dict[str, str]]:
    """
    LOCKED entries in the active map represent the bench's fixed, physical configuration
    (I_Start/I_Stop-style pushbuttons wired once) - they must stay in PLC_Agent_IO across
    programs even when a specific program doesn't reference them directly, so the orphan-cleanup
    in EnsureTags (section 5/18/27) never deletes them. Reads the active map directly (not any
    per-package variables.json, which only ever lists the CURRENT program's own IR variables) -
    returns [] on any map-loading problem rather than failing the whole TIA request over this.
    """
    try:
        map_path = resolve_active_map_path(project_root)
        io_map = load_json_file(map_path)
    except (FileNotFoundError, ValueError, OSError):
        return []
    if not isinstance(io_map, dict):
        return []
    tags: list[dict[str, str]] = []
    for variable in io_map.get("variables", []):
        if not isinstance(variable, dict) or variable.get("state") != "LOCKED":
            continue
        if variable.get("class") not in {"input", "output"}:
            continue
        name = str(variable.get("name") or "").strip()
        address = _normalize_siemens_address(str(variable.get("location") or ""))
        if not name or not address:
            continue
        iec_type = str(variable.get("type") or "BOOL").upper()
        tags.append(
            {
                "name": name,
                "data_type": SIEMENS_TYPE_MAP.get(iec_type, "Bool"),
                "address": address
            }
        )
    return tags


def _build_tag_payload(variables_path: Path, project_root: Path | None = None) -> list[dict[str, str]]:
    """
    Section 3/4: the DESIRED PLC tag set sent to Openness for reconciliation - every external
    tag the current program's IR actually declares (class input/output; internal M_/T_/C_/R_/F_
    variables are filtered out here, they never reach PLC_Agent_IO - section 20), PLUS any
    LOCKED map entry with a functional name, which persists across programs regardless of
    whether this specific program references it (section 5/18). A FREE channel with no
    functional_name never appears in `variables` (the IR never declares it), so it is never sent
    here either (section 19) - EnsureTags on the bridge side then deletes anything already in
    PLC_Agent_IO that is not in this set (orphans of a previous program).
    """
    variables = load_json_file(variables_path)
    if not isinstance(variables, list):
        variables = []
    tags_by_name: dict[str, dict[str, str]] = {}
    for variable in variables:
        if not isinstance(variable, dict) or variable.get("class") not in {"input", "output"}:
            continue
        name = str(variable.get("name", ""))
        address = str(variable.get("siemens_address") or variable.get("location") or "")
        address = _normalize_siemens_address(address)
        tags_by_name[name] = {
            "name": name,
            "data_type": str(variable.get("siemens_type") or "Bool"),
            "address": address
        }

    root = project_root or get_project_root()
    for locked_tag in _load_locked_persistent_tags(root):
        tags_by_name.setdefault(locked_tag["name"], locked_tag)

    return list(tags_by_name.values())


def prepare_tia_request(
    package_dir: Path,
    project_root: Path | None = None
) -> tuple[Path, Path, dict[str, Any]]:
    root = project_root or get_project_root()
    config = load_tia_config(root)
    source_path = package_dir / "siemens_source.scl"
    variables_path = package_dir / "variables.json"
    if not source_path.exists():
        raise FileNotFoundError(f"No existe la fuente Siemens: {source_path}")
    if not variables_path.exists():
        raise FileNotFoundError(f"No existe la tabla de variables: {variables_path}")

    request_path = package_dir / "tia_openness_request.json"
    result_path = package_dir / "tia_compile_report.json"
    request = {
        "action": "import_compile",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "tia_version": "V18",
        "project_path": str(config.get("project_path", "")),
        "plc_name": str(config.get("plc_name", "")),
        "source_path": str(source_path.resolve()),
        "source_name": source_path.name,
        "result_path": str(result_path.resolve()),
        "attach_to_running": bool(config.get("attach_to_running", True)),
        "with_user_interface": bool(config.get("with_user_interface", True)),
        "create_plc_tags": bool(config.get("create_plc_tags", True)),
        "save_project_on_success": bool(config.get("save_project_on_success", True)),
        "compile_after_import": bool(config.get("compile_after_import", True)),
        "tags": _build_tag_payload(variables_path, project_root=root),
        "physical_download_allowed": False
    }
    request_path.write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
    return request_path, result_path, request


def validate_package_with_tia(
    package_dir: Path,
    project_root: Path | None = None
) -> dict[str, Any]:
    root = project_root or get_project_root()
    diagnostic = diagnose_tia_openness(root)
    if not diagnostic["checks"].get("bridge_built"):
        build_result = build_openness_bridge(root)
        if not build_result.get("built"):
            return {
                "executed": False,
                "status": "BRIDGE_BUILD_FAILED",
                "diagnostic": diagnostic,
                "build": build_result,
                "errors": build_result.get("errors", [])
            }
        diagnostic = diagnose_tia_openness(root)

    if not diagnostic.get("is_ready"):
        return {
            "executed": False,
            "status": "TIA_NOT_READY",
            "diagnostic": diagnostic,
            "errors": diagnostic.get("warnings", [])
        }

    request_path, result_path, request = prepare_tia_request(package_dir, root)
    timeout_seconds = int(load_tia_config(root).get("timeout_seconds", 300))
    environment = os.environ.copy()
    portal_bin = str(DEFAULT_PORTAL_ROOT / "Bin")
    environment["PATH"] = portal_bin + os.pathsep + environment.get("PATH", "")
    result = subprocess.run(
        [diagnostic["bridge_exe_path"], str(request_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout_seconds,
        check=False,
        env=environment
    )
    report: dict[str, Any] = {}
    if result_path.exists():
        payload = load_json_file(result_path)
        if isinstance(payload, dict):
            report = payload
    report.update(
        {
            "executed": True,
            "bridge_return_code": result.returncode,
            "bridge_stdout": result.stdout.strip(),
            "bridge_stderr": result.stderr.strip(),
            "request_path": str(request_path),
            "result_path": str(result_path),
            "request": request
        }
    )
    result_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _persist_tia_report(package_dir, report)
    return report


TARGET_TYPE_PLCSIM = "PLCSIM_ADVANCED"
TARGET_TYPE_PHYSICAL = "PHYSICAL_PLC"
DOWNLOAD_PURPOSE_NORMAL = "normal"
DOWNLOAD_PURPOSE_EXPERIMENT = "experiment"
DOWNLOAD_SCOPES = ("SOFTWARE", "HARDWARE_AND_SOFTWARE")

# Destino por defecto si config/tia_openness_config.json no define "download_targets": PLCSIM
# Advanced, solo software, Start Module automatico. pc_interface/target_interface vacios = el
# bridge elige la UNICA interfaz PG/PC cuyo nombre contiene "PLCSIM" (o aborta si hay 0 o >1).
# La red (IP, mascara, adaptadores) nunca se modifica: se reutiliza la del proyecto TIA.
DEFAULT_DOWNLOAD_TARGET: dict[str, Any] = {
    "target_type": TARGET_TYPE_PLCSIM,
    "target_name": "PLCSIM Advanced",
    "configuration_mode": "",
    "pc_interface": "",
    "target_interface": "",
    "download_scope": "SOFTWARE",
    "start_modules": True
}


def resolve_download_target(config: dict[str, Any], purpose: str = DOWNLOAD_PURPOSE_NORMAL) -> dict[str, Any]:
    """download_targets.<purpose> de la config TIA, completado con DEFAULT_DOWNLOAD_TARGET."""
    targets = config.get("download_targets") if isinstance(config.get("download_targets"), dict) else {}
    raw = targets.get(purpose) if isinstance(targets.get(purpose), dict) else {}
    target = {**DEFAULT_DOWNLOAD_TARGET, **raw}
    target["target_type"] = str(target.get("target_type") or TARGET_TYPE_PLCSIM).strip().upper()
    scope = str(target.get("download_scope") or "SOFTWARE").strip().upper()
    target["download_scope"] = scope if scope in DOWNLOAD_SCOPES else "SOFTWARE"
    target["start_modules"] = bool(target.get("start_modules", True))
    return target


def prepare_download_request(
    package_dir: Path,
    project_root: Path | None = None,
    purpose: str = DOWNLOAD_PURPOSE_NORMAL
) -> tuple[Path, Path, dict[str, Any]]:
    root = project_root or get_project_root()
    config = load_tia_config(root)
    target = resolve_download_target(config, purpose)

    request_path = package_dir / "tia_download_request.json"
    result_path = package_dir / "tia_download_report.json"
    request = {
        "action": "download",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "tia_version": "V18",
        "project_path": str(config.get("project_path", "")),
        "plc_name": str(config.get("plc_name", "")),
        "result_path": str(result_path.resolve()),
        "attach_to_running": bool(config.get("attach_to_running", True)),
        "with_user_interface": bool(config.get("with_user_interface", True)),
        "purpose": purpose,
        "require_simulation": purpose == DOWNLOAD_PURPOSE_EXPERIMENT,
        "target_type": target["target_type"],
        "target_name": str(target.get("target_name", "")),
        "configuration_mode": str(target.get("configuration_mode", "")),
        "pc_interface": str(target.get("pc_interface", "")),
        "target_interface": str(target.get("target_interface", "")),
        "download_scope": target["download_scope"],
        "start_modules": target["start_modules"]
    }
    request_path.write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
    return request_path, result_path, request


def _finalize_download_report(
    raw: dict[str, Any],
    target: dict[str, Any],
    purpose: str,
    started_at: datetime,
    started_perf: float
) -> dict[str, Any]:
    """
    Normaliza el reporte al schema de tia_download_report.json (seccion 9): estados SEPARADOS
    (download_success / start_module_success / cpu_run_requested) y cpu_run_confirmed siempre
    null hasta que exista lectura real del estado de la CPU (Runtime API, fase posterior).
    """
    completed_at = datetime.now()
    bridge_status = str(raw.get("status", "TIA_DOWNLOAD_FAILED"))
    download_success = bridge_status == "TIA_DOWNLOAD_PASSED" and bool(raw.get("success", True))
    report = dict(raw)
    report.update(
        {
            "status": "SUCCESS" if download_success else bridge_status,
            "bridge_status": bridge_status,
            "purpose": purpose,
            "target_type": raw.get("target_type", target["target_type"]),
            "target_name": raw.get("target_name") or target.get("target_name", ""),
            "download_success": download_success,
            "start_module_requested": bool(raw.get("start_module_requested", False)),
            "start_module_success": raw.get("start_module_success") if download_success else False,
            "cpu_run_requested": bool(raw.get("cpu_run_requested", False)) and download_success,
            "cpu_run_confirmed": None,
            "warnings": list(raw.get("warnings", []) or []),
            "errors": list(raw.get("errors", []) or []),
            "started_at": started_at.isoformat(timespec="seconds"),
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "duration_ms": int(round((time.perf_counter() - started_perf) * 1000)),
            "success": download_success
        }
    )
    return report


def download_program_to_plc(
    package_dir: Path,
    project_root: Path | None = None,
    purpose: str = DOWNLOAD_PURPOSE_NORMAL
) -> dict[str, Any]:
    """
    Downloads the already-compiled program of THIS package to the configured download target
    (config download_targets.<purpose>), with explicit DownloadConfiguration handling and Start
    Module in the bridge. Never recompiles, never touches network settings. purpose="experiment"
    only ever accepts a PLCSIM_ADVANCED target: anything else aborts with
    EXPERIMENT_TARGET_NOT_SIMULATION before the bridge is even invoked (and the bridge re-checks
    the PC interface it actually resolved).
    """
    root = project_root or get_project_root()
    started_at = datetime.now()
    started_perf = time.perf_counter()
    target = resolve_download_target(load_tia_config(root), purpose)
    result_path = package_dir / "tia_download_report.json"

    def _early(status: str, errors: list[str], extra: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = {"executed": False, "success": False, "status": status, "errors": errors, **(extra or {})}
        report = _finalize_download_report(raw, target, purpose, started_at, started_perf)
        package_dir.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return report

    if purpose == DOWNLOAD_PURPOSE_EXPERIMENT and target["target_type"] != TARGET_TYPE_PLCSIM:
        return _early(
            "EXPERIMENT_TARGET_NOT_SIMULATION",
            [f"El destino experimental configurado es {target['target_type']}; solo se admite {TARGET_TYPE_PLCSIM}."]
        )

    diagnostic = diagnose_tia_openness(root)
    if not diagnostic["checks"].get("bridge_built"):
        build_result = build_openness_bridge(root)
        if not build_result.get("built"):
            return _early("BRIDGE_BUILD_FAILED", list(build_result.get("errors", [])), {"build": build_result})
        diagnostic = diagnose_tia_openness(root)

    if not diagnostic.get("is_ready"):
        return _early("TIA_NOT_READY", list(diagnostic.get("warnings", [])), {"diagnostic": diagnostic})

    request_path, result_path, request = prepare_download_request(package_dir, root, purpose)
    timeout_seconds = int(load_tia_config(root).get("timeout_seconds", 300))
    environment = os.environ.copy()
    portal_bin = str(DEFAULT_PORTAL_ROOT / "Bin")
    environment["PATH"] = portal_bin + os.pathsep + environment.get("PATH", "")
    result = subprocess.run(
        [diagnostic["bridge_exe_path"], str(request_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout_seconds,
        check=False,
        env=environment
    )
    raw: dict[str, Any] = {}
    if result_path.exists():
        payload = load_json_file(result_path)
        if isinstance(payload, dict):
            raw = payload
    raw.update(
        {
            "executed": True,
            "bridge_return_code": result.returncode,
            "bridge_stdout": result.stdout.strip(),
            "bridge_stderr": result.stderr.strip(),
            "request_path": str(request_path),
            "result_path": str(result_path),
            "compile_report": str(package_dir / "tia_compile_report.json")
        }
    )
    report = _finalize_download_report(raw, target, purpose, started_at, started_perf)
    result_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _persist_tia_report(package_dir: Path, report: dict[str, Any]) -> None:
    status = str(report.get("status", "TIA_OPENNESS_UNKNOWN"))
    passed = status == "TIA_COMPILATION_PASSED"
    for file_name in ("verification.json", "project_manifest.json", "pou_manifest.json", "generation_metadata.json"):
        path = package_dir / file_name
        if not path.exists():
            continue
        payload = load_json_file(path)
        if not isinstance(payload, dict):
            continue
        payload["tia_openness"] = report
        payload["tia_openness_status"] = status
        payload["compilation_status"] = status
        payload["is_compilable"] = passed
        if file_name == "verification.json":
            payload["is_valid"] = passed
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    metadata_path = package_dir.parent.parent / "logs" / f"{package_dir.name}_log.json"
    if not metadata_path.exists():
        return

    metadata = load_json_file(metadata_path)
    if not isinstance(metadata, dict):
        return

    verification = metadata.setdefault("verification_result", {})
    if isinstance(verification, dict):
        verification.update(
            {
                "tia_openness": report,
                "tia_openness_status": status,
                "compilation_status": status,
                "is_compilable": passed,
                "is_valid": passed
            }
        )
    rendered_artifacts = metadata.setdefault("rendered_artifacts", {})
    if isinstance(rendered_artifacts, dict):
        rendered_artifacts["tia_compile_report.json"] = report
    saved_paths = metadata.setdefault("saved_paths", {})
    if isinstance(saved_paths, dict):
        saved_paths["tia_compile_report.json"] = str(package_dir / "tia_compile_report.json")
    metadata["compilation_status"] = status
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
