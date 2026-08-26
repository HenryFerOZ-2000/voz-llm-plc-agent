from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

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


def _build_tag_payload(variables_path: Path) -> list[dict[str, str]]:
    variables = load_json_file(variables_path)
    if not isinstance(variables, list):
        return []
    tags: list[dict[str, str]] = []
    for variable in variables:
        if not isinstance(variable, dict) or variable.get("class") not in {"input", "output"}:
            continue
        address = str(variable.get("siemens_address") or variable.get("location") or "")
        address = address.replace("%IX", "%I").replace("%QX", "%Q").replace("%MX", "%M")
        tags.append(
            {
                "name": str(variable.get("name", "")),
                "data_type": str(variable.get("siemens_type") or "Bool"),
                "address": address
            }
        )
    return tags


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
        "tags": _build_tag_payload(variables_path),
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
