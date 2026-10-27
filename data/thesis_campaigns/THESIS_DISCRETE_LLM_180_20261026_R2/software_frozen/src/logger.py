from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from utils import current_timestamp, ensure_directory, get_project_root, sanitize_filename

AUTO_TEST_MARKER = "<!-- AUTO-TEST-ROWS -->"
ROBUSTNESS_MARKER = "<!-- AUTO-ROBUSTNESS-ROWS -->"
# Registro de EJECUCIONES (runtime, local por PC, ignorado por Git). docs/07_registro_pruebas.md es
# documentacion curada y ya no recibe escrituras automaticas (docs/multi_pc_setup.md).
RUNTIME_LOG_DIRNAME = "runtime"
RUNTIME_LOG_FILENAME = "development_log.md"
RUNTIME_LOG_TITLE = "# Registro local de ejecuciones (runtime)\n\nGenerado automaticamente por la aplicacion; local por PC, no versionado.\n\n"
KEEP_FILE_NAME = ".gitkeep"

PLATFORM_DIRECTORY_MAP = {
    "OPENPLC_ST": "OPENPLC",
    "CODESYS_ST": "CODESYS",
    "SIEMENS_SCL_V18": "SIEMENS"
}

PLATFORM_ALIASES = {
    "OPENPLC": "OPENPLC_ST",
    "OPENPLC_ST": "OPENPLC_ST",
    "CODESYS": "CODESYS_ST",
    "CODESYS_ST": "CODESYS_ST",
    "CODESYS_ST_FULL": "CODESYS_ST",
    "CODESYS_ST_FRAGMENT": "CODESYS_ST",
    "SIEMENS": "SIEMENS_SCL_V18",
    "SIEMENS_SCL": "SIEMENS_SCL_V18",
    "SIEMENS_SCL_V18": "SIEMENS_SCL_V18",
    "TIA": "SIEMENS_SCL_V18",
    "TIA_V18": "SIEMENS_SCL_V18",
    "ALL": "ALL"
}


def _normalize_target_platform(target_platform: str | None) -> str:
    normalized = (target_platform or "").strip().upper()
    if not normalized:
        return "CODESYS_ST"
    return PLATFORM_ALIASES.get(normalized, "CODESYS_ST")


def _platforms_to_process(target_platform: str | None) -> list[str]:
    normalized = _normalize_target_platform(target_platform)
    if normalized == "ALL" or target_platform is None:
        return ["OPENPLC_ST", "CODESYS_ST", "SIEMENS_SCL_V18"]
    return [normalized]


def _touch_keep_file(directory: Path) -> None:
    keep_file = directory / KEEP_FILE_NAME
    try:
        keep_file.touch(exist_ok=True)
    except OSError:
        return


def ensure_generated_dirs(base_dir: Path | None = None) -> dict[str, Any]:
    generated_code_dir = (base_dir or (get_project_root() / "generated_code")).resolve()
    ensure_directory(generated_code_dir)

    platforms: dict[str, dict[str, Path]] = {}
    for platform_name, folder_name in PLATFORM_DIRECTORY_MAP.items():
        platform_root = ensure_directory(generated_code_dir / folder_name)
        active_dir = ensure_directory(platform_root / "active")
        logs_dir = ensure_directory(platform_root / "logs")
        archived_dir = ensure_directory(platform_root / "archived")

        _touch_keep_file(platform_root)
        _touch_keep_file(active_dir)
        _touch_keep_file(logs_dir)
        _touch_keep_file(archived_dir)

        platforms[platform_name] = {
            "platform_root": platform_root.resolve(),
            "active": active_dir.resolve(),
            "logs": logs_dir.resolve(),
            "archived": archived_dir.resolve()
        }

    return {
        "generated_code": generated_code_dir,
        "platforms": platforms
    }


def _filename_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _build_package_base_name(
    semantic_output: dict[str, Any],
    timestamp: str,
    case_id: str | None = None
) -> str:
    safe_case_id = sanitize_filename(case_id or semantic_output.get("case_id")).upper()
    safe_intent = sanitize_filename(semantic_output.get("intent_id", "INT_UNKNOWN")).upper()
    return f"{timestamp}_{safe_case_id}_{safe_intent}"


def _resolve_unique_directory(parent_dir: Path, base_name: str) -> Path:
    candidate = parent_dir / base_name
    if not candidate.exists():
        return candidate

    suffix = 1
    while True:
        retry = parent_dir / f"{base_name}_{suffix:02d}"
        if not retry.exists():
            return retry
        suffix += 1


def _write_artifact_file(path: Path, payload: Any) -> None:
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_text(str(payload), encoding="utf-8")


def build_generation_record(
    semantic_output: dict[str, Any],
    verification_result: dict[str, Any],
    saved_paths: dict[str, str],
    target_platform: str,
    rendered_artifacts: dict[str, Any] | None = None,
    project_ir: dict[str, Any] | None = None,
    case_id: str | None = None
) -> dict[str, Any]:
    return {
        "timestamp": current_timestamp(),
        "command_text": semantic_output.get("command_text", ""),
        "case_id": case_id or semantic_output.get("case_id"),
        "intent_id": semantic_output.get("intent_id", "INT_UNKNOWN"),
        "parameters": semantic_output.get("parameters", {}),
        "target_platform": target_platform,
        "project_ir": project_ir or {},
        "rendered_artifacts": rendered_artifacts or {},
        "verification_result": verification_result,
        "saved_paths": saved_paths,
        "generation_status": verification_result.get("generation_status", "GENERATED"),
        "semantic_status": verification_result.get("semantic_status", "SEMANTIC_VALIDATED"),
        "verification_status": verification_result.get("verification_status", "STATICALLY_VERIFIED"),
        "compilation_status": verification_result.get("compilation_status", "COMPILATION_NOT_EXECUTED"),
        "simulation_status": verification_result.get("simulation_status", "SIMULATION_NOT_EXECUTED"),
        "physical_deployment_status": verification_result.get("physical_deployment_status", "HARDWARE_DEPLOYMENT_NOT_EXECUTED")
    }


def save_project_package(
    semantic_output: dict[str, Any],
    target_platform: str,
    rendered_artifacts: dict[str, Any],
    verification_result: dict[str, Any],
    output_dir: Path | None = None,
    case_id: str | None = None,
    project_ir: dict[str, Any] | None = None
) -> dict[str, str]:
    normalized_target = _normalize_target_platform(target_platform)
    generated_dirs = ensure_generated_dirs(output_dir)
    platform_dirs = generated_dirs["platforms"][normalized_target]

    timestamp = _filename_timestamp()
    base_name = _build_package_base_name(
        semantic_output=semantic_output,
        timestamp=timestamp,
        case_id=case_id
    )
    package_dir = _resolve_unique_directory(platform_dirs["active"], base_name)
    ensure_directory(package_dir)

    artifact_paths: dict[str, str] = {}
    for file_name, payload in rendered_artifacts.items():
        target_path = package_dir / file_name
        _write_artifact_file(target_path, payload)
        artifact_paths[file_name] = str(target_path)

    metadata_path = platform_dirs["logs"] / f"{package_dir.name}_log.json"
    saved_paths = {
        "platform_root": str(platform_dirs["platform_root"]),
        "active_dir": str(platform_dirs["active"]),
        "logs_dir": str(platform_dirs["logs"]),
        "package_dir": str(package_dir),
        "metadata_path": str(metadata_path)
    }
    saved_paths.update(artifact_paths)

    if "full_program.st" in artifact_paths:
        saved_paths["st_path"] = artifact_paths["full_program.st"]
        saved_paths["full_program_path"] = artifact_paths["full_program.st"]
    if "declarations.st" in artifact_paths:
        saved_paths["declarations_path"] = artifact_paths["declarations.st"]
    if "implementation.st" in artifact_paths:
        saved_paths["implementation_path"] = artifact_paths["implementation.st"]
        saved_paths["pou_path"] = artifact_paths["implementation.st"]
    if "variables.json" in artifact_paths:
        saved_paths["variables_path"] = artifact_paths["variables.json"]

    record = build_generation_record(
        semantic_output=semantic_output,
        verification_result=verification_result,
        saved_paths=saved_paths,
        target_platform=normalized_target,
        rendered_artifacts=rendered_artifacts,
        project_ir=project_ir,
        case_id=case_id
    )
    metadata_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return saved_paths


def save_generated_artifacts(
    plc_artifact: dict[str, Any],
    semantic_output: dict[str, Any],
    verification_result: dict[str, Any],
    output_dir: Path | None = None,
    case_id: str | None = None
) -> dict[str, str]:
    rendered_artifacts = {
        "full_program.st": plc_artifact.get("full_program", ""),
        "declarations.st": plc_artifact.get("declarations_code", ""),
        "implementation.st": plc_artifact.get("implementation_code", ""),
        "variables.json": plc_artifact.get("variables_table", []),
        "project_manifest.json": {
            "platform": plc_artifact.get("target_platform", "CODESYS_ST"),
            "project_name": plc_artifact.get("program_name", "PLC_PRG"),
            "pou_name": plc_artifact.get("program_name", "PLC_PRG"),
            "pou_type": "PROGRAM",
            "language": "ST",
            "task_name": "MainTask",
            "task_interval": "T#100ms",
            "task_priority": 1,
            "generated_files": [
                "full_program.st",
                "declarations.st",
                "implementation.st",
                "variables.json",
                "project_manifest.json",
                "pou_manifest.json",
                "task_config.json",
                "test_cases.json",
                "semantic_input.json",
                "semantic_validation.json",
                "generation_metadata.json",
                "retrieved_context.json",
                "verification.json"
            ],
            "case_id": case_id or semantic_output.get("case_id"),
            "intent_id": semantic_output.get("intent_id", "INT_UNKNOWN"),
            "generation_status": "GENERATED",
            "semantic_status": "SEMANTIC_VALIDATED",
            "verification_status": "STATICALLY_VERIFIED",
            "compilation_status": "COMPILATION_NOT_EXECUTED",
            "simulation_status": "SIMULATION_NOT_EXECUTED",
            "physical_deployment_status": "HARDWARE_DEPLOYMENT_NOT_EXECUTED"
        },
        "pou_manifest.json": {
            "name": plc_artifact.get("program_name", "PLC_PRG"),
            "type": "PROGRAM",
            "language": "ST",
            "variables": plc_artifact.get("variables_table", []),
            "function_blocks": [],
            "implementation_file": "implementation.st",
            "declarations_file": "declarations.st",
            "full_program_file": "full_program.st",
            "generation_status": "GENERATED",
            "compilation_status": "COMPILATION_NOT_EXECUTED",
            "simulation_status": "SIMULATION_NOT_EXECUTED",
            "physical_deployment_status": "HARDWARE_DEPLOYMENT_NOT_EXECUTED"
        },
        "task_config.json": {
            "resource_name": "Res0",
            "task_name": "MainTask",
            "interval": "T#100ms",
            "priority": 1,
            "pou_instance": plc_artifact.get("program_name", "PLC_PRG")
        },
        "test_cases.json": [],
        "semantic_input.json": semantic_output,
        "semantic_validation.json": {
            "is_valid": verification_result.get("is_valid", False),
            "errors": verification_result.get("errors", []),
            "warnings": verification_result.get("warnings", [])
        },
        "generation_metadata.json": {
            "legacy_entry_point": True,
            "generated_at": current_timestamp(),
            "target_platform": plc_artifact.get("target_platform", "CODESYS_ST")
        },
        "retrieved_context.json": [],
        "verification.json": verification_result
    }

    return save_project_package(
        semantic_output=semantic_output,
        target_platform=plc_artifact.get("target_platform", "CODESYS_ST"),
        rendered_artifacts=rendered_artifacts,
        verification_result=verification_result,
        output_dir=output_dir,
        case_id=case_id
    )


def save_generation_artifacts(
    command_text: str,
    semantic_output: dict[str, Any],
    st_code: str,
    verification_result: dict[str, Any],
    output_dir: Path,
    target_platform: str = "CODESYS_ST",
    case_id: str | None = None
) -> dict[str, str]:
    semantic_payload = dict(semantic_output)
    semantic_payload.setdefault("command_text", command_text)
    if case_id is not None:
        semantic_payload["case_id"] = case_id

    plc_artifact = {
        "target_platform": _normalize_target_platform(target_platform),
        "program_name": "PLC_PRG",
        "case_id": case_id or semantic_payload.get("case_id"),
        "intent_id": semantic_payload.get("intent_id", "INT_UNKNOWN"),
        "variables_table": [],
        "declarations_code": "",
        "implementation_code": st_code,
        "full_program": st_code
    }
    return save_generated_artifacts(
        plc_artifact=plc_artifact,
        semantic_output=semantic_payload,
        verification_result=verification_result,
        output_dir=output_dir,
        case_id=case_id
    )


def _resolve_unique_archive_path(archived_dir: Path, archive_name: str) -> Path:
    archive_path = archived_dir / archive_name
    if not archive_path.exists():
        return archive_path

    suffix = 1
    while True:
        candidate = archived_dir / f"{archive_name}_{suffix:02d}"
        if not candidate.exists():
            return candidate
        suffix += 1


def _resolve_move_target(destination_dir: Path, target_name: str) -> Path:
    target_path = destination_dir / target_name
    if not target_path.exists():
        return target_path

    original = Path(target_name)
    suffix = 1
    while True:
        candidate = destination_dir / f"{original.stem}_{suffix:02d}{original.suffix}"
        if not candidate.exists():
            return candidate
        suffix += 1


def _iter_log_files(directory: Path) -> list[Path]:
    return [
        path for path in sorted(directory.iterdir())
        if path.is_file() and path.name != KEEP_FILE_NAME and path.suffix.lower() == ".json"
    ]


def _iter_package_dirs(directory: Path) -> list[Path]:
    return [
        path for path in sorted(directory.iterdir())
        if path.is_dir()
    ]


def _iter_active_files(directory: Path) -> list[Path]:
    return [
        path for path in sorted(directory.iterdir())
        if path.is_file() and path.name != KEEP_FILE_NAME
    ]


def _archive_single_platform(platform_dirs: dict[str, Path]) -> dict[str, Any]:
    archive_name = f"{_filename_timestamp()}_archive"
    archive_dir = _resolve_unique_archive_path(platform_dirs["archived"], archive_name)
    ensure_directory(archive_dir)
    archive_logs_dir = ensure_directory(archive_dir / "logs")

    package_dirs = _iter_package_dirs(platform_dirs["active"])
    loose_files = _iter_active_files(platform_dirs["active"])
    log_files = _iter_log_files(platform_dirs["logs"])

    for package_dir in package_dirs:
        destination = _resolve_move_target(archive_dir, package_dir.name)
        shutil.move(str(package_dir), str(destination))

    for loose_file in loose_files:
        destination = _resolve_move_target(archive_dir, loose_file.name)
        shutil.move(str(loose_file), str(destination))

    for log_file in log_files:
        destination = _resolve_move_target(archive_logs_dir, log_file.name)
        shutil.move(str(log_file), str(destination))

    moved_packages = len(package_dirs) + len(loose_files)
    return {
        "archived": True,
        "archive_path": str(archive_dir),
        "package_dirs_moved": moved_packages,
        "log_files_moved": len(log_files),
        "st_files_moved": moved_packages
    }


def archive_generated_files(
    target_platform: str | None = None,
    output_dir: Path | None = None
) -> dict[str, Any]:
    generated_dirs = ensure_generated_dirs(output_dir)
    platform_results: dict[str, Any] = {}
    archive_paths: dict[str, str] = {}
    package_total = 0
    log_total = 0

    for platform_name in _platforms_to_process(target_platform):
        result = _archive_single_platform(generated_dirs["platforms"][platform_name])
        platform_results[platform_name] = result
        archive_paths[platform_name] = result["archive_path"]
        package_total += result["package_dirs_moved"]
        log_total += result["log_files_moved"]

    response: dict[str, Any] = {
        "archived": True,
        "target_platform": _normalize_target_platform(target_platform) if target_platform else "ALL",
        "archive_paths": archive_paths,
        "package_dirs_moved": package_total,
        "log_files_moved": log_total,
        "st_files_moved": package_total,
        "platform_results": platform_results
    }

    if len(archive_paths) == 1:
        response["archive_path"] = next(iter(archive_paths.values()))

    return response


def _clear_single_platform(platform_dirs: dict[str, Path]) -> dict[str, Any]:
    package_dirs = _iter_package_dirs(platform_dirs["active"])
    loose_files = _iter_active_files(platform_dirs["active"])
    log_files = _iter_log_files(platform_dirs["logs"])
    errors: list[str] = []
    package_dirs_deleted = 0
    log_files_deleted = 0

    for package_dir in package_dirs:
        try:
            shutil.rmtree(package_dir)
            package_dirs_deleted += 1
        except OSError as error:
            errors.append(f"{package_dir.name}: {error}")

    for loose_file in loose_files:
        try:
            loose_file.unlink()
            package_dirs_deleted += 1
        except OSError as error:
            errors.append(f"{loose_file.name}: {error}")

    for log_file in log_files:
        try:
            log_file.unlink()
            log_files_deleted += 1
        except OSError as error:
            errors.append(f"{log_file.name}: {error}")

    return {
        "cleared": True,
        "package_dirs_deleted": package_dirs_deleted,
        "active_files_deleted": package_dirs_deleted,
        "log_files_deleted": log_files_deleted,
        "errors": errors
    }


def clear_generated_files(
    confirm: bool = False,
    target_platform: str | None = None,
    output_dir: Path | None = None
) -> dict[str, Any]:
    if not confirm:
        return {
            "cleared": False,
            "message": "Confirmacion requerida"
        }

    generated_dirs = ensure_generated_dirs(output_dir)
    platform_results: dict[str, Any] = {}
    package_total = 0
    log_total = 0
    errors: list[str] = []

    for platform_name in _platforms_to_process(target_platform):
        result = _clear_single_platform(generated_dirs["platforms"][platform_name])
        platform_results[platform_name] = result
        package_total += result["package_dirs_deleted"]
        log_total += result["log_files_deleted"]
        errors.extend(result["errors"])

    return {
        "cleared": True,
        "target_platform": _normalize_target_platform(target_platform) if target_platform else "ALL",
        "package_dirs_deleted": package_total,
        "active_files_deleted": package_total,
        "log_files_deleted": log_total,
        "errors": errors,
        "platform_results": platform_results
    }


def _generation_mode_label(target_platform: str) -> str:
    return _normalize_target_platform(target_platform)


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ").strip()


def runtime_log_path(docs_dir: Path) -> Path:
    """<proyecto>/runtime/development_log.md (docs_dir es <proyecto>/docs en todos los llamadores)."""
    return Path(docs_dir).parent / RUNTIME_LOG_DIRNAME / RUNTIME_LOG_FILENAME


def append_test_record_to_docs(
    docs_dir: Path,
    command_text: str,
    semantic_output: dict[str, Any],
    verification_result: dict[str, Any],
    saved_paths: dict[str, str] | None,
    target_platform: str = "CODESYS_ST"
) -> Path:
    registry_path = runtime_log_path(docs_dir)
    ensure_directory(registry_path.parent)

    if registry_path.exists():
        content = registry_path.read_text(encoding="utf-8")
    else:
        content = (
            RUNTIME_LOG_TITLE
            + "## Registros automaticos del sistema\n\n"
            "| fecha | comando probado | intencion detectada | tipo de salida | plataforma | paquete o archivo generado | verificacion valida si/no | errores | observaciones |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            f"{AUTO_TEST_MARKER}\n"
        )

    timestamp = current_timestamp()
    intent_id = semantic_output.get("intent_id", "INT_UNKNOWN")
    generated_path = "No generado"
    if saved_paths:
        generated_path = saved_paths.get("package_dir") or saved_paths.get("st_path", "No generado")
    generation_mode = _generation_mode_label(target_platform)
    is_valid = "Si" if verification_result.get("is_valid", False) else "No"
    errors = "; ".join(verification_result.get("errors", [])) or "-"
    warnings = "; ".join(verification_result.get("warnings", [])) or "-"

    row = (
        f"| {_escape_markdown_cell(timestamp)} "
        f"| {_escape_markdown_cell(command_text)} "
        f"| {_escape_markdown_cell(str(intent_id))} "
        f"| {_escape_markdown_cell('Paquete PLC')} "
        f"| {_escape_markdown_cell(generation_mode)} "
        f"| {_escape_markdown_cell(generated_path)} "
        f"| {_escape_markdown_cell(is_valid)} "
        f"| {_escape_markdown_cell(errors)} "
        f"| {_escape_markdown_cell(warnings)} |\n"
    )

    if AUTO_TEST_MARKER in content:
        updated_content = content.replace(AUTO_TEST_MARKER, f"{row}{AUTO_TEST_MARKER}")
    else:
        if not content.endswith("\n"):
            content += "\n"
        updated_content = content + (
            "\n## Registros automaticos del sistema\n\n"
            "| fecha | comando probado | intencion detectada | tipo de salida | plataforma | paquete o archivo generado | verificacion valida si/no | errores | observaciones |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            f"{row}"
        )

    registry_path.write_text(updated_content, encoding="utf-8")
    return registry_path


def append_robustness_record_to_docs(
    docs_dir: Path,
    command_text: str,
    expected_intent: str | None,
    detected_intent: str,
    is_correct: bool | None,
    st_path: str | None,
    observations: str
) -> Path:
    registry_path = runtime_log_path(docs_dir)
    ensure_directory(registry_path.parent)

    if registry_path.exists():
        content = registry_path.read_text(encoding="utf-8")
    else:
        content = RUNTIME_LOG_TITLE

    row = (
        f"| {_escape_markdown_cell(current_timestamp())} "
        f"| {_escape_markdown_cell(command_text)} "
        f"| {_escape_markdown_cell(expected_intent or 'N/A')} "
        f"| {_escape_markdown_cell(detected_intent)} "
        f"| {_escape_markdown_cell('Si' if is_correct else 'No' if is_correct is False else 'N/A')} "
        f"| {_escape_markdown_cell(st_path or 'No generado')} "
        f"| {_escape_markdown_cell(observations or '-')} |\n"
    )

    if ROBUSTNESS_MARKER in content:
        updated_content = content.replace(ROBUSTNESS_MARKER, f"{row}{ROBUSTNESS_MARKER}")
    else:
        if not content.endswith("\n"):
            content += "\n"
        updated_content = content + (
            "\n## Pruebas de robustez linguistica\n\n"
            "| fecha | comando | expected_intent | detected_intent | correcto | codigo generado | observaciones |\n"
            "|---|---|---|---|---|---|---|\n"
            f"{row}{ROBUSTNESS_MARKER}\n"
        )

    registry_path.write_text(updated_content, encoding="utf-8")
    return registry_path
