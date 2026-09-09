from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from code_generator import TemplateNotImplementedError, generate_implementation_from_ir
from ir_builder import INTENT_TEMPLATE_NOT_IMPLEMENTED, build_project_ir
from logger import save_project_package
from openplc_validator import (
    COMPILATION_FAILED,
    COMPILATION_REPORT,
    COMPILATION_TIMEOUT,
    SIMULATION_FAILED,
    SIMULATION_REPORT,
    validate_openplc_package
)
from platforms import CodesysAdapter, OpenPLCAdapter, SiemensSCLAdapter
from semantic_validator import validate_semantic_output
from utils import get_project_root, load_json_file
from verifier import verify_generated_package, verify_project_ir


def _normalize_target_platform(target_platform: str) -> str:
    normalized = (target_platform or "").strip().upper()
    if normalized in {"OPENPLC", "OPENPLC_ST"}:
        return "OPENPLC_ST"
    if normalized in {"SIEMENS", "SIEMENS_SCL", "SIEMENS_SCL_V18", "TIA", "TIA_V18"}:
        return "SIEMENS_SCL_V18"
    return "CODESYS_ST"


def _select_adapter(target_platform: str) -> OpenPLCAdapter | CodesysAdapter | SiemensSCLAdapter:
    normalized = _normalize_target_platform(target_platform)
    if normalized == "OPENPLC_ST":
        return OpenPLCAdapter()
    if normalized == "SIEMENS_SCL_V18":
        return SiemensSCLAdapter()
    return CodesysAdapter(use_physical_locations=False)


def _load_intents_catalog() -> dict[str, Any]:
    return load_json_file(get_project_root() / "config" / "intents_catalog.json")


def _load_safety_rules() -> dict[str, Any]:
    return load_json_file(get_project_root() / "config" / "safety_rules.json")


def _status_payload(verification_ok: bool | None = None) -> dict[str, str]:
    verification_status = "STATICALLY_VERIFIED"
    if verification_ok is False:
        verification_status = "STATIC_VERIFICATION_FAILED"
    return {
        "generation_status": "GENERATED",
        "semantic_status": "SEMANTIC_VALIDATED",
        "verification_status": verification_status,
        "compilation_status": "COMPILATION_NOT_EXECUTED",
        "simulation_status": "SIMULATION_NOT_EXECUTED",
        "physical_deployment_status": "HARDWARE_DEPLOYMENT_NOT_EXECUTED",
        "automatic_deployment_policy": "NOT_ALLOWED_AUTOMATICALLY"
    }


def _env_flag(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _render_package_artifacts(
    adapter: OpenPLCAdapter | CodesysAdapter | SiemensSCLAdapter,
    project_ir: Any,
    semantic_output: dict[str, Any],
    semantic_validation: dict[str, Any],
    generation_metadata: dict[str, Any],
    retrieved_context: list[dict[str, Any]]
) -> dict[str, Any]:
    project_manifest = adapter.render_project_manifest(project_ir)
    project_manifest.update(_status_payload(verification_ok=None))
    project_manifest["generated_files"] = [
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
    ]

    pou_manifest = adapter.render_pou_manifest(project_ir)
    pou_manifest.update(_status_payload(verification_ok=None))
    pou_manifest["task_binding"] = project_ir.task.name

    artifacts = {
        "full_program.st": adapter.render_full_program(project_ir),
        "declarations.st": adapter.render_declarations(project_ir),
        "implementation.st": adapter.render_implementation(project_ir),
        "variables.json": adapter.render_variables_table(project_ir),
        "project_manifest.json": project_manifest,
        "pou_manifest.json": pou_manifest,
        "task_config.json": adapter.render_task_configuration(project_ir),
        "test_cases.json": adapter.render_test_cases(project_ir),
        "semantic_input.json": semantic_output,
        "semantic_validation.json": semantic_validation,
        "generation_metadata.json": generation_metadata,
        "retrieved_context.json": retrieved_context
    }
    artifacts.update(adapter.render_extra_artifacts(project_ir))
    project_manifest["generated_files"] = list(artifacts) + ["verification.json"]
    return artifacts


def _combine_verification(
    generation_errors: list[str],
    semantic_validation: dict[str, Any],
    ir_verification: dict[str, Any],
    package_verification: dict[str, Any]
) -> dict[str, Any]:
    errors = list(generation_errors)
    errors.extend(semantic_validation.get("errors", []))
    errors.extend(ir_verification.get("errors", []))
    errors.extend(package_verification.get("errors", []))

    warnings = list(semantic_validation.get("warnings", []))
    warnings.extend(ir_verification.get("warnings", []))
    warnings.extend(package_verification.get("warnings", []))

    return {
        "is_valid": not errors,
        "semantic_validation": semantic_validation,
        "generation_errors": generation_errors,
        "ir_verification": ir_verification,
        "package_verification": package_verification,
        "errors": errors,
        "warnings": warnings,
        **_status_payload(verification_ok=not errors)
    }


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_final_verification(saved_paths: dict[str, str], verification_result: dict[str, Any]) -> None:
    verification_path = saved_paths.get("verification.json")
    if verification_path:
        _write_json_file(Path(verification_path), verification_result)

    for manifest_name in ("project_manifest.json", "pou_manifest.json", "generation_metadata.json"):
        manifest_path = saved_paths.get(manifest_name)
        if not manifest_path:
            continue
        path = Path(manifest_path)
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.update(_status_payload(verification_ok=verification_result.get("is_valid", False)))
            for status_key in (
                "generation_status",
                "semantic_status",
                "verification_status",
                "compilation_status",
                "simulation_status",
                "physical_deployment_status",
                "automatic_deployment_policy"
            ):
                if status_key in verification_result:
                    payload[status_key] = verification_result[status_key]
            payload["is_fully_validated"] = verification_result.get("is_fully_validated", False)
            generated_files = payload.get("generated_files")
            if isinstance(generated_files, list):
                for report_name in (COMPILATION_REPORT, SIMULATION_REPORT):
                    if report_name in saved_paths and report_name not in generated_files:
                        generated_files.append(report_name)
            _write_json_file(path, payload)

    metadata_path = saved_paths.get("metadata_path")
    if not metadata_path:
        return

    metadata_file = Path(metadata_path)
    if not metadata_file.exists():
        return

    payload = json.loads(metadata_file.read_text(encoding="utf-8"))
    payload["verification_result"] = verification_result
    payload.update(_status_payload(verification_ok=verification_result.get("is_valid", False)))
    for status_key in (
        "generation_status",
        "semantic_status",
        "verification_status",
        "compilation_status",
        "simulation_status",
        "physical_deployment_status",
        "automatic_deployment_policy"
    ):
        if status_key in verification_result:
            payload[status_key] = verification_result[status_key]
    if isinstance(payload.get("saved_paths"), dict):
        payload["saved_paths"].update(saved_paths)
    payload["is_fully_validated"] = verification_result.get("is_fully_validated", False)
    _write_json_file(metadata_file, payload)


def _merge_openplc_validation(
    verification_result: dict[str, Any],
    openplc_validation: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(verification_result)
    errors = list(merged.get("errors", []))
    warnings = list(merged.get("warnings", []))
    compilation = openplc_validation["compilation"]
    simulation = openplc_validation["simulation"]

    if compilation.get("status") in {COMPILATION_FAILED, COMPILATION_TIMEOUT}:
        errors.extend(f"OpenPLC: {message}" for message in compilation.get("errors", []))
    else:
        warnings.extend(f"OpenPLC: {message}" for message in compilation.get("warnings", []))

    if simulation.get("status") == SIMULATION_FAILED:
        errors.extend(f"Simulacion OpenPLC: {message}" for message in simulation.get("errors", []))
    else:
        warnings.extend(f"Simulacion OpenPLC: {message}" for message in simulation.get("warnings", []))

    merged.update(
        {
            "is_valid": not errors,
            "is_fully_validated": not errors and openplc_validation.get("is_fully_validated", False),
            "is_compilable": openplc_validation.get("is_compiled", False),
            "is_functionally_validated": openplc_validation.get("is_simulated", False),
            "compilation_status": openplc_validation["compilation_status"],
            "simulation_status": openplc_validation["simulation_status"],
            "openplc_validation": openplc_validation,
            "errors": errors,
            "warnings": warnings
        }
    )
    return merged


def _build_generation_metadata(
    semantic_output: dict[str, Any],
    semantic_validation: dict[str, Any],
    target_platform: str,
    retrieved_context: list[dict[str, Any]],
    transcription_payload: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target_platform": target_platform,
        "parser_mode_requested": semantic_output.get("parser_mode_requested"),
        "parser_mode_used": semantic_output.get("parser_mode_used", semantic_output.get("parser_mode")),
        "decision_reason": semantic_output.get("decision_reason"),
        "llm_usage": semantic_output.get("llm_usage", {}),
        "agreement": semantic_output.get("agreement"),
        "semantic_validation": semantic_validation,
        "retrieved_context_count": len(retrieved_context),
        "transcription": transcription_payload or {},
        "generation_mode": "CONTROLLED_DETERMINISTIC_POU",
        **_status_payload(verification_ok=None)
    }


def _aborted_result(
    semantic_output: dict[str, Any],
    target_platform: str,
    semantic_validation: dict[str, Any]
) -> dict[str, Any]:
    verification = {
        "is_valid": False,
        "errors": list(semantic_validation.get("errors", []))
        + ["La generacion del paquete PLC fue cancelada por validacion semantica."],
        "warnings": list(semantic_validation.get("warnings", [])),
        "semantic_validation": semantic_validation,
        "generation_status": "ABORTED",
        "semantic_status": "SEMANTIC_VALIDATION_FAILED",
        "verification_status": "NOT_EXECUTED",
        "compilation_status": "COMPILATION_NOT_EXECUTED",
        "simulation_status": "SIMULATION_NOT_EXECUTED",
        "physical_deployment_status": "HARDWARE_DEPLOYMENT_NOT_EXECUTED"
    }
    return {
        "target_platform": target_platform,
        "project_ir": {},
        "package_dir": "",
        "artifacts": {},
        "verification": verification,
        "rendered_files": {},
        "semantic_validation": semantic_validation,
        "semantic_output": semantic_output
    }


def generate_project_package(
    semantic_output: dict[str, Any],
    target_platform: str,
    io_map: dict[str, Any],
    intents_catalog: dict[str, Any] | None = None,
    safety_rules: dict[str, Any] | None = None,
    transcription_payload: dict[str, Any] | None = None,
    output_dir: Path | None = None
) -> dict[str, Any]:
    normalized_target = _normalize_target_platform(target_platform)
    runtime_intents_catalog = intents_catalog or _load_intents_catalog()
    runtime_safety_rules = safety_rules or _load_safety_rules()
    semantic_validation = validate_semantic_output(
        semantic_output=semantic_output,
        io_map=io_map,
        intents_catalog=runtime_intents_catalog,
        safety_rules=runtime_safety_rules
    )

    if not semantic_validation.get("is_valid", False):
        return _aborted_result(semantic_output, normalized_target, semantic_validation)

    retrieved_context = semantic_output.get("retrieved_context", [])
    if not isinstance(retrieved_context, list):
        retrieved_context = []

    project_ir = build_project_ir(
        semantic_output=semantic_output,
        io_map=io_map,
        target_platform=normalized_target,
        functional_requirements=semantic_output.get("functional_requirements", [])
    )

    generation_errors: list[str] = []
    try:
        project_ir.pou.implementation_code = generate_implementation_from_ir(project_ir)
    except TemplateNotImplementedError as error:
        generation_errors.append(str(error))
        project_ir.pou.implementation_code = (
            f"(* {INTENT_TEMPLATE_NOT_IMPLEMENTED}: {project_ir.intent_id} *)\n"
            "(* No existe una plantilla funcional para esta intencion. *)\n"
        )

    ir_verification = verify_project_ir(project_ir)
    generation_metadata = _build_generation_metadata(
        semantic_output=semantic_output,
        semantic_validation=semantic_validation,
        target_platform=normalized_target,
        retrieved_context=retrieved_context,
        transcription_payload=transcription_payload
    )

    adapter = _select_adapter(normalized_target)
    rendered_files = _render_package_artifacts(
        adapter=adapter,
        project_ir=project_ir,
        semantic_output=semantic_output,
        semantic_validation=semantic_validation,
        generation_metadata=generation_metadata,
        retrieved_context=retrieved_context
    )

    preliminary_verification = _combine_verification(
        generation_errors=generation_errors,
        semantic_validation=semantic_validation,
        ir_verification=ir_verification,
        package_verification={"is_valid": True, "errors": [], "warnings": []}
    )
    rendered_files["verification.json"] = preliminary_verification

    saved_paths = save_project_package(
        semantic_output=semantic_output,
        target_platform=normalized_target,
        rendered_artifacts=rendered_files,
        verification_result=preliminary_verification,
        output_dir=output_dir,
        project_ir=project_ir.to_dict()
    )

    package_dir = Path(saved_paths["package_dir"])
    package_verification = verify_generated_package(package_dir)
    verification_result = _combine_verification(
        generation_errors=generation_errors,
        semantic_validation=semantic_validation,
        ir_verification=ir_verification,
        package_verification=package_verification
    )

    if normalized_target == "OPENPLC_ST" and _env_flag("OPENPLC_AUTO_VALIDATE", default=True):
        openplc_validation = validate_openplc_package(
            package_dir,
            run_simulation=_env_flag("OPENPLC_RUN_SIMULATION", default=True)
        )
        verification_result = _merge_openplc_validation(verification_result, openplc_validation)
        for report_name in (COMPILATION_REPORT, SIMULATION_REPORT):
            report_path = package_dir / report_name
            if report_path.exists():
                saved_paths[report_name] = str(report_path)
                rendered_files[report_name] = json.loads(report_path.read_text(encoding="utf-8"))

    _write_final_verification(saved_paths, verification_result)
    rendered_files["verification.json"] = verification_result

    return {
        "target_platform": normalized_target,
        "project_ir": project_ir.to_dict(),
        "package_dir": str(package_dir),
        "artifacts": saved_paths,
        "verification": verification_result,
        "rendered_files": rendered_files,
        "semantic_validation": semantic_validation,
        "semantic_output": semantic_output
    }
