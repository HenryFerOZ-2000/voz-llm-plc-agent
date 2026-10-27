"""
Pipeline de REFERENCIA sin LLM, sin TIA y sin PLCSIM (auditoria de preparacion pre-FORMAL).

Ejecuta, para una interpretacion semantica dada (la respuesta que daria un parser correcto), las MISMAS
funciones de produccion que encadena GENERAR ENSAYO en la GUI:

  seleccion del mapa experimental (experiment_maps)  ->  working map del ensayo (trial_io_map)
  ->  llm_parser.parse_with_mode(llm_response_text=...)  (reparacion, semantica efectiva, validacion)
  ->  asignaciones del IOAllocator sobre el working map + revalidacion  ->  io_map_snapshot congelado
  ->  project_packager.generate_project_package (IR, SCL Siemens, verificador)
  ->  process_variable_bindings  ->  oracle_runner.run_oracle con el simulador SCL (scl_sim).

Sirve para responder, antes de FORMAL, si cada caso es EVALUABLE: si el sistema tiene la capacidad de
interpretar/generar/evaluar lo que el benchmark congelado especifica. No es un ensayo: no se registra como
trial, no se mezcla con resultados DEVELOPMENT/FORMAL y nunca llama al LLM.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import traceback
from pathlib import Path
from typing import Any

from trial_experiments import experiment_maps, oracle_runner, oracle_schema
from trial_experiments import process_variables as PV
from trial_experiments import trial_io_map
from trial_experiments.scl_sim import SclSimError, SimulatedPlcBridge

SIEMENS_TARGET = "SIEMENS_SCL_V18"
_RUNTIME = {"connected": True, "instance_name": "REFERENCE_SIM", "cpu_state": "RUN", "status": "CONNECTED"}
_RUNTIME_CONFIG = {"instance_name": "REFERENCE_SIM", "io_settle_ms": 0, "io_timeout_seconds": 5, "api_dll_path": "-",
                   "windows_adapter_match": "-", "timeout_seconds": 5}


class LLMCallForbidden(RuntimeError):
    """La auditoria de referencia nunca llama al LLM: cualquier intento es un error explicito."""


class _NoLLMClient:
    def is_configured(self) -> bool:
        return False

    def interpret_command(self, *args: Any, **kwargs: Any) -> Any:
        raise LLMCallForbidden("reference_pipeline: llamada al LLM prohibida (auditoria sin LLM).")


def _stage(result: dict[str, Any], name: str, success: bool | None, detail: Any = None) -> None:
    result["stages"][name] = {"success": success, "detail": detail}


def run_reference(project_root: Path, case_id: str, interpretation: dict[str, Any], command_text: str,
                  work_dir: Path | None = None) -> dict[str, Any]:
    """Resultado por etapa + veredicto del Oracle sobre el SCL generado (simulado)."""
    from llm_parser import parse_with_mode
    from project_packager import generate_project_package
    from semantic_validator import validate_semantic_output
    from utils import load_json_file

    project_root = Path(project_root)
    owned = work_dir is None
    work = Path(tempfile.mkdtemp(prefix=f"ref_{case_id}_")) if owned else Path(work_dir)
    result: dict[str, Any] = {"case_id": case_id, "stages": {}, "verdict": None, "verdict_reason": None, "errors": []}
    try:
        oracle = oracle_schema.load_oracle(project_root, case_id)
        selection = experiment_maps.select_experiment_map(project_root, oracle)
        result["map"] = {key: selection.get(key) for key in ("map_id", "map_hash", "source", "simulation_only", "reason")}
        if not selection.get("path"):
            _stage(result, "map_selection", False, selection.get("reason"))
            return result
        _stage(result, "map_selection", True, selection["map_id"])

        io_ref = trial_io_map.create_working_map(work, Path(selection["path"]))
        working_path = Path(io_ref["working_map_path"])
        intents_catalog = load_json_file(project_root / "config" / "intents_catalog.json")
        safety_rules = load_json_file(project_root / "config" / "safety_rules.json")

        semantic = parse_with_mode(command_text, mode="llm", io_map=trial_io_map.load_working_map(working_path),
                                   intents_catalog=intents_catalog, safety_rules=safety_rules,
                                   llm_client=_NoLLMClient(),
                                   llm_response_text=json.loads(json.dumps(interpretation)))
        proposals = (semantic.get("semantic_validation") or {}).get("io_assignment_proposals") or []
        to_apply = [proposal for proposal in proposals if not proposal.get("blocked")]
        if to_apply:
            trial_io_map.apply_proposals_to_working_map(working_path, to_apply, "TEXT_EXPLICIT", trial_io_map.STATE_PREPARING)
            semantic = dict(semantic)
            semantic["semantic_validation"] = validate_semantic_output(
                semantic, trial_io_map.load_working_map(working_path), intents_catalog, safety_rules)
        result["semantic_output"] = semantic
        validation = semantic.get("semantic_validation") or {}
        semantic_ok = bool(validation.get("is_valid")) and semantic.get("intent_id") not in (None, "INT_UNKNOWN")
        _stage(result, "semantic", semantic_ok, {"errors": validation.get("errors"), "conflicts":
                                                validation.get("functional_requirement_conflicts"),
                                                "question": validation.get("clarification_question")})
        if not semantic_ok:
            return result

        frozen = trial_io_map.freeze_working_map(io_ref, semantic, trial_io_map.STATE_PREPARING, f"REF_{case_id}")
        _stage(result, "io_allocation", True, frozen.get("bound_channels"))

        package = generate_project_package(semantic, SIEMENS_TARGET, trial_io_map.load_working_map(working_path),
                                           intents_catalog=intents_catalog, safety_rules=safety_rules,
                                           output_dir=work / "package")
        verification = package.get("verification") or {}
        package_dir = Path(package.get("package_dir") or work / "package")
        source = package_dir / "siemens_source.scl"
        result["program_scl"] = source.read_text(encoding="utf-8") if source.is_file() else None
        _stage(result, "generation", bool(verification.get("is_valid")) and source.is_file(),
               {"errors": verification.get("errors"), "warnings": verification.get("warnings")})
        if not result["stages"]["generation"]["success"]:
            return result

        pv_bindings = PV.build_process_variable_bindings(json.loads((package_dir / "variables.json").read_text(encoding="utf-8")))
        capabilities = oracle_runner.runtime_capability_check(oracle)
        _stage(result, "runtime_capabilities", bool(capabilities.get("executable")), capabilities)
        if not capabilities.get("executable"):
            return result
        try:
            bridge = SimulatedPlcBridge(result["program_scl"])
        except SclSimError as error:
            _stage(result, "simulation", False, str(error))
            return result
        oracle_result = oracle_runner.run_oracle(
            oracle, Path(frozen["snapshot_path"]), dict(_RUNTIME), "PLCSIM_ADVANCED", semantic, project_root,
            bridge=bridge, runtime_config=dict(_RUNTIME_CONFIG), process_variable_bindings=pv_bindings)
        result["verdict"] = oracle_result.get("verdict")
        result["verdict_reason"] = oracle_result.get("verdict_reason")
        result["roles"] = (oracle_result.get("roles") or {}).get("status")
        result["role_issues"] = (oracle_result.get("roles") or {}).get("issues")
        result["functional_failed_checks"] = (oracle_result.get("functional") or {}).get("failed_checks")
        result["safety_violations"] = (oracle_result.get("safety") or {}).get("violations")
        result["timing_checks"] = [
            {"step_id": check.get("step_id"), "role": check.get("role"), "measured_ms": check.get("actual_observation_time"),
             "window_ms": check.get("expected_time"), "passed": check.get("passed")}
            for step in oracle_result.get("steps") or [] for check in step.get("checks") or [] if check.get("type") == "transition"]
        result["semantic_checks"] = (oracle_result.get("semantic") or {}).get("failed_checks")
        _stage(result, "oracle", result["verdict"] == "PASS", result["verdict_reason"])
        return result
    except Exception as error:  # la auditoria nunca se interrumpe por un caso: se registra el fallo
        result["errors"].append(f"{type(error).__name__}: {error}")
        result["traceback"] = traceback.format_exc(limit=8)
        return result
    finally:
        if owned:
            shutil.rmtree(work, ignore_errors=True)


__all__ = ["run_reference", "SIEMENS_TARGET"]
