"""
Congelacion del software para la evaluacion FORMAL (freeze manifest v2) y su validacion READ-ONLY.

El manifiesto (ruta fijada por el diseno experimental: formal_freeze.manifest) registra, con hashes REALES:
  - el contenido de todo archivo versionado que el sistema ejecuta o lee en tiempo de ejecucion (codigo, prompt,
    catalogos, esquema, base de conocimiento del LLM, configuracion versionada, bridges, benchmark, Oracles, mapas);
  - los parametros NO secretos de la configuracion local de TIA/PLCSIM y el modelo LLM configurado;
  - el TIA MASTER (snapshot .zap18, CPU, TIA, X1, huella de la carpeta, estado FORMAL_READY);
  - versiones de Python y de los paquetes que afectan al comportamiento;
  - la evidencia de cierre (suite, auditoria pre-FORMAL) como dato informativo.

validate_freeze() recalcula todo y devuelve las diferencias: codigo/prompt/Oracle/benchmark/mapa modificado, archivo
congelado ausente o nuevo, MASTER distinto, parametros de ejecucion distintos. experimental_design.
check_formal_trial_allowed la usa, de modo que todo punto de entrada FORMAL (precheck de entorno antes del LLM,
precheck de evaluacion antes de TIA, guardas del lote, preflight) ABORTA si el entorno no coincide.

Los hashes de texto se calculan con finales de linea normalizados (CRLF -> LF): el mismo commit da los mismos hashes
en cualquier checkout de Windows/Linux.
"""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

FREEZE_SCHEMA_VERSION = 2
FREEZE_ID = "FORMAL_V1"
# v1.1: estimulos de voz pareados clean/noisy. El manifiesto anade la seccion "audio" (config de audio, version de la
# mezcla, SNR objetivo y SHA-256 del ruido maestro industrial aprobado) y validate_freeze exige ese mismo master.
AUDIO_FILES = ("config/formal_audio_config.json", "src/trial_experiments/formal_audio.py", "src/trial_experiments/voice_protocol.py")
FROZEN_DIRS = ("src", "prompts", "schemas", "knowledge_base", "config", "data", "plcsim_runtime_bridge",
               "tia_openness_bridge", "scripts")
FROZEN_ROOT_FILES = ("requirements.txt", "requirements-transfer.txt", "Abrir_Voz_LLM_PLC_Agent.pyw",
                     "Abrir_Voz_LLM_PLC_Agent.bat")
FROZEN_SUFFIXES = (".py", ".cs", ".json", ".txt", ".md", ".pyw", ".bat", ".xml")
# Informes DERIVADOS que la aplicacion regenera (no se ejecutan ni definen la evaluacion): fuera del congelado.
DERIVED_EXCLUDED = {
    "data/preformal_readiness_report.json", "data/oracle_validation_report.json", "data/system_capability_gaps.json",
    "data/variant_consistency_report.json",
}
GROUPS = {
    "benchmark": ["data/experiment_cases/canonical_cases.json", "data/plc_maps/experiment_variants.json",
                  "data/plc_maps/profiles.json", "data/experimental_design.json",
                  "data/experiment_benchmark/versions/benchmark_v2/manifest.json"],
    "llm": ["prompts/llm_semantic_parser_prompt.txt", "config/intents_catalog.json", "schemas/semantic_output.schema.json",
            "config/llm_config.json", "config/parser_settings.json", "config/safety_rules.json", "src/llm_parser.py",
            "src/llm_client.py", "src/llm_context_builder.py", "src/semantic_validator.py", "src/semantic_repair.py",
            "src/effective_semantics.py", "src/knowledge_retriever.py"],
    "generation": ["src/functional_requirements.py", "src/functional_resources.py", "src/ir_builder.py", "src/plc_ir.py",
                   "src/code_generator.py", "src/verifier.py", "src/composition_check.py", "src/project_packager.py",
                   "src/platforms/siemens_scl_adapter.py", "src/io_allocator.py", "src/pid_control.py", "src/pid_scl.py",
                   "src/pid_package.py", "src/pid_tia_contract.py", "config/native_pid_defaults.json",
                   "config/native_pid_v18_capabilities.json", "config/native_pid_cyclic_ob.xml",
                   "src/process_signals.py", "config/native_pid_map_defaults.json"],
    "plant_test": ["src/pid_tank_model.py", "src/pid_plant_test.py", "src/pid_native_validation.py",
                   "src/pid_plant_io.py", "plcsim_runtime_bridge/PidPlantSession.cs", "config/pid_tank_test_profile.json"],
    "runtime": ["plcsim_runtime_bridge/Program.cs", "tia_openness_bridge/Program.cs", "src/plcsim_runtime.py",
                "src/plcsim_runtime_io.py", "src/tia_openness.py", "src/tia_projects.py",
                "src/trial_experiments/oracle_runner.py", "src/trial_experiments/process_variables.py",
                "src/trial_experiments/deferred_evaluator.py", "src/trial_experiments/oracle_schema.py",
                "tia_openness_bridge/PidControlSupport.cs", "src/pid_commissioning.py", "src/pid_commissioning_view.py",
                "src/pid_acceptance.py", "scripts/validate_native_pid.py"],
    "maps": ["data/plc_maps/mapa_banco_fisico_base.json", "data/plc_maps/mapa_experimental_simulacion.json",
             "config/experiment_maps.json"],
    "config": ["config/pid_supervisor_config.json"],
}
RUNTIME_SETTING_KEYS = {
    "tia_version": ("tia_version",),
    "timeout_seconds": ("timeout_seconds",),
    "create_plc_tags": ("create_plc_tags",),
    "compile_after_import": ("compile_after_import",),
    "download_target_experiment": ("download_targets", "experiment"),
    "plcsim_instance_name": ("plcsim_runtime", "instance_name"),
    "plcsim_adapter_match": ("plcsim_runtime", "windows_adapter_match"),
    "plcsim_io_settle_ms": ("plcsim_runtime", "io_settle_ms"),
    "plcsim_io_timeout_seconds": ("plcsim_runtime", "io_timeout_seconds"),
    "plcsim_timeout_seconds": ("plcsim_runtime", "timeout_seconds"),
    "tia_memory_preflight": ("tia_memory_preflight",),
}
PACKAGES = ("openai", "pydantic", "customtkinter", "python-dotenv", "sounddevice")
LLM_ENV_KEYS = ("PLC_LLM_MODEL", "PLC_TRANSCRIPTION_MODEL", "LLM_CONFIDENCE_THRESHOLD")


def normalized_sha256(path: Path) -> str:
    data = Path(path).read_bytes()
    if Path(path).suffix.lower() in FROZEN_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(project_root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=project_root, capture_output=True, text=True, check=True).stdout.strip()


def manifest_relative_path(project_root: Path) -> str:
    from trial_experiments import experimental_design as ED
    return str(ED.load_design(project_root)["formal_freeze"]["manifest"]).replace("\\", "/")


def frozen_files(project_root: Path) -> list[str]:
    """Archivos VERSIONADOS dentro del alcance congelado (excluye derivados y el propio manifiesto)."""
    tracked = _git(project_root, "ls-files", *FROZEN_DIRS, *FROZEN_ROOT_FILES).splitlines()
    excluded = DERIVED_EXCLUDED | {manifest_relative_path(project_root)}
    return sorted(path for path in tracked
                  if Path(path).suffix.lower() in FROZEN_SUFFIXES and path not in excluded
                  and not path.startswith("data/preformal_readiness") and (Path(project_root) / path).is_file())


def _pick(config: dict[str, Any], keys: tuple[str, ...]) -> Any:
    value: Any = config
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def runtime_settings(project_root: Path) -> dict[str, Any]:
    """Parametros NO secretos de la configuracion local TIA/PLCSIM (sin rutas del host)."""
    import tia_openness

    config = tia_openness.load_tia_config(project_root)
    return {name: _pick(config, keys) for name, keys in RUNTIME_SETTING_KEYS.items()}


def llm_settings(project_root: Path) -> dict[str, Any]:
    """Modelo/parametros de llamada: llm_config.json (versionado) + variables de entorno NO secretas."""
    from dotenv import dotenv_values

    env = {**dotenv_values(Path(project_root) / ".env"), **{k: os.environ[k] for k in LLM_ENV_KEYS if k in os.environ}}
    config = json.loads((Path(project_root) / "config" / "llm_config.json").read_text(encoding="utf-8"))
    return {
        "provider": config.get("provider"),
        "parser_mode": config.get("parser_mode"),
        "model": env.get("PLC_LLM_MODEL"),
        "transcription_model": env.get("PLC_TRANSCRIPTION_MODEL"),
        "confidence_threshold": env.get("LLM_CONFIDENCE_THRESHOLD") or config.get("confidence_threshold"),
        "temperature": config.get("temperature"),
        "max_retries": config.get("max_retries"),
        "require_structured_output": config.get("require_structured_output"),
        "allow_rule_fallback": config.get("allow_rule_fallback"),
        "seed": None,  # la API usada no fija semilla: el determinismo se limita a temperature = 0
    }


def master_state(project_root: Path) -> dict[str, Any]:
    from trial_experiments import deferred_evaluator as DE

    config = DE.load_master_config(project_root)
    validation = config.get("validation") or {}
    snapshot = config.get("snapshot") or {}
    archive = Path(snapshot.get("archive_path") or "")
    return {
        "master_status": validation.get("master_status"),
        "validation_status": validation.get("status"),
        "snapshot_sha256": snapshot.get("archive_sha256"),
        "snapshot_file_sha256": raw_sha256(archive) if archive.is_file() else None,
        "snapshot_size_bytes": snapshot.get("size_bytes"),
        "folder_fingerprint": validation.get("master_folder_fingerprint_after"),
        "folder_fingerprint_now": DE.master_folder_fingerprint(config["path"]) if config.get("path") and Path(config["path"]).exists() else None,
        "project_name": validation.get("project_name"),
        "tia_version": validation.get("tia_version"),
        "cpu_type_name": validation.get("cpu_type_name"),
        "cpu_order_number": validation.get("cpu_order_number"),
        "cpu_firmware": validation.get("cpu_firmware"),
        "x1_ip_address": validation.get("x1_ip_address"),
        "unmanaged_blocks": validation.get("unmanaged_blocks"),
        "blocks": [block.get("name") for block in validation.get("blocks") or []],
        "formal_ready": config.get("formal_ready"),
    }


def environment_versions() -> dict[str, Any]:
    versions = {}
    for package in PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return {"python": platform.python_version(), "packages": versions}


def oracle_states(project_root: Path) -> dict[str, Any]:
    from trial_experiments import benchmark_catalog as BC
    from trial_experiments import oracle_schema as S

    states = {}
    for case_id in BC.CASE_IDS:
        oracle = S.load_oracle(project_root, case_id)
        approval = oracle["approval"]
        states[case_id] = {"version": approval["version"], "hash": S.compute_oracle_hash(oracle), "status": approval["status"],
                           "technical_validation": (approval.get("technical_validation") or {}).get("status"),
                           "human_formal_approval": approval.get("human_formal_approval"),
                           "approved_by": approval.get("approved_by"), "approved_at": approval.get("approved_at")}
    return states


def audio_state(project_root: Path) -> dict[str, Any]:
    """Estimulos de voz pareados: parametros congelados de la mezcla y el ruido maestro FORMAL (aprobado y presente)."""
    from trial_experiments import formal_audio as FA

    config = FA.load_config(project_root)
    master = FA.noise_master_status(project_root, "FORMAL", config)
    return {
        "audio_freeze_id": config["freeze_id"],
        "target_snr_db": config["target_snr_db"],
        "snr_tolerance_db": config["snr_tolerance_db"],
        "mixing_algorithm_version": config["mixing_algorithm_version"],
        "active_speech_method": config["active_speech_method"]["id"],
        "noise_offset_salt": config["noise_offset"]["salt"],
        "audio_config_hashes": {path: normalized_sha256(Path(project_root) / path) for path in AUDIO_FILES},
        "industrial_noise_master_sha256": master["sha256"] if master["ready"] else None,
        "industrial_noise_master_approved_by": config["noise_master"].get("approved_by"),
        "industrial_noise_master_ready": master["ready"],
    }


def build_manifest(project_root: Path, suite: dict[str, Any], readiness: dict[str, Any], git_tag: str,
                   known_limitations: list[str], freeze_id: str = FREEZE_ID, parent_freeze: str | None = None,
                   freeze_reason: str | None = None, include_audio: bool = False) -> dict[str, Any]:
    from trial_experiments import experimental_design as ED

    project_root = Path(project_root)
    files = {path: normalized_sha256(project_root / path) for path in frozen_files(project_root)}
    fingerprint = ED.current_integrity_fingerprint(project_root)
    groups = {name: {path: files[path] for path in paths if path in files} for name, paths in GROUPS.items()}
    missing_group_files = sorted(path for paths in GROUPS.values() for path in paths if path not in files)
    if missing_group_files:
        raise ValueError(f"Archivos de grupo fuera del alcance congelado: {missing_group_files}")
    oracles = oracle_states(project_root)
    audio = audio_state(project_root) if include_audio else None
    if audio is not None and not audio["industrial_noise_master_ready"]:
        raise ValueError("AUDIO_NOISE_MASTER_NOT_READY: no se congela v1.1 sin el ruido maestro aprobado y presente.")
    return {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "freeze_id": freeze_id,
        "parent_freeze": parent_freeze,
        "freeze_reason": freeze_reason,
        **({'campaign': {**ED.campaign_reference(project_root, ED.PHASE_FORMAL),
                         'case_ids': ED.formal_case_ids(project_root),
                         'planned_trials': len(ED.formal_design_matrix(project_root))}}
           if ED.load_design(project_root).get('formal_campaign') else {}),
        **({"audio": audio} if audio is not None else {}),
        "status": "FROZEN",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": _git(project_root, "rev-parse", "HEAD"),
        "git_branch": _git(project_root, "branch", "--show-current"),
        "git_tag": git_tag,
        "git_note": ("git_commit = commit con TODO el software congelado; el tag apunta al commit del freeze, que solo "
                     "agrega este manifiesto y documentacion (fuera del alcance congelado)."),
        # Compatibilidad con experimental_design.check_formal_trial_allowed (v1).
        "benchmark_version": fingerprint["benchmark_version"],
        "canonical_catalog_hash": fingerprint["canonical_catalog_hash"],
        "oracles": oracles,
        "oracle_count": len(oracles),
        "benchmark_hashes": groups["benchmark"],
        "oracle_hashes": {case_id: entry["hash"] for case_id, entry in oracles.items()},
        "prompt_hash": files["prompts/llm_semantic_parser_prompt.txt"],
        "llm_hashes": groups["llm"],
        "llm_settings": llm_settings(project_root),
        "generator_hashes": groups["generation"],
        "runtime_hashes": groups["runtime"],
        "map_hashes": groups["maps"],
        "config_hashes": groups["config"],
        "runtime_settings": runtime_settings(project_root),
        "master": {key: value for key, value in master_state(project_root).items() if key != "folder_fingerprint_now"},
        "master_hash": master_state(project_root)["snapshot_sha256"],
        "environment": environment_versions(),
        "files": files,
        "file_count": len(files),
        "suite": suite,
        "preformal_readiness": readiness,
        "known_non_blocking_limitations": known_limitations,
        "hash_method": "SHA-256 del contenido con CRLF normalizado a LF para archivos de texto",
    }


def load_manifest(project_root: Path) -> dict[str, Any] | None:
    path = Path(project_root) / manifest_relative_path(project_root)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def validate_freeze(project_root: Path, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """READ-ONLY: el entorno actual coincide con el manifiesto. Nunca escribe nada."""
    project_root = Path(project_root)
    manifest = manifest if manifest is not None else load_manifest(project_root)
    errors: list[str] = []
    if manifest is None:
        return {"ok": False, "errors": ["FREEZE_MANIFEST_MISSING: no existe el manifiesto de congelacion."], "checked": {}}
    if manifest.get("status") != "FROZEN" or manifest.get("schema_version") != FREEZE_SCHEMA_VERSION:
        errors.append("FREEZE_MANIFEST_INVALID: estado o version de esquema inesperados.")
    frozen = manifest.get("files") or {}
    current_paths = set(frozen_files(project_root))
    for path in sorted(set(frozen) - current_paths):
        errors.append(f"FROZEN_FILE_MISSING: {path}")
    for path in sorted(current_paths - set(frozen)):
        errors.append(f"UNFROZEN_FILE_ADDED: {path}")
    for path in sorted(set(frozen) & current_paths):
        if normalized_sha256(project_root / path) != frozen[path]:
            errors.append(f"FROZEN_FILE_MODIFIED: {path}")
    current_oracles = oracle_states(project_root)
    for case_id, entry in (manifest.get("oracles") or {}).items():
        now = current_oracles.get(case_id) or {}
        if now.get("hash") != entry.get("hash") or now.get("status") != "FROZEN" or now.get("human_formal_approval") != "APPROVED":
            errors.append(f"ORACLE_MISMATCH: {case_id}")
    if runtime_settings(project_root) != manifest.get("runtime_settings"):
        errors.append("RUNTIME_SETTINGS_MISMATCH: la configuracion TIA/PLCSIM difiere del manifiesto.")
    llm_now, llm_frozen = llm_settings(project_root), manifest.get("llm_settings") or {}
    for key in ("provider", "model", "transcription_model", "temperature", "parser_mode", "require_structured_output"):
        if str(llm_now.get(key)) != str(llm_frozen.get(key)):
            errors.append(f"LLM_SETTINGS_MISMATCH: {key}")
    master_now, master_frozen = master_state(project_root), manifest.get("master") or {}
    if master_now["master_status"] != "FORMAL_READY":
        errors.append("MASTER_NOT_FORMAL_READY")
    for key in ("snapshot_sha256", "folder_fingerprint", "cpu_order_number", "cpu_firmware", "tia_version", "x1_ip_address"):
        if master_now.get(key) != master_frozen.get(key):
            errors.append(f"MASTER_MISMATCH: {key}")
    if master_now["snapshot_file_sha256"] != master_frozen.get("snapshot_sha256"):
        errors.append("MASTER_MISMATCH: el archivo .zap18 del snapshot falta o cambio.")
    if master_now["folder_fingerprint_now"] != master_frozen.get("folder_fingerprint"):
        errors.append("MASTER_MISMATCH: el proyecto MASTER cambio desde la congelacion.")
    if manifest.get("audio"):
        audio_now, audio_frozen = audio_state(project_root), manifest["audio"]
        if not audio_now["industrial_noise_master_ready"] or                 audio_now["industrial_noise_master_sha256"] != audio_frozen.get("industrial_noise_master_sha256"):
            errors.append("AUDIO_NOISE_MASTER_MISMATCH: el ruido maestro falta, no esta aprobado o difiere del congelado.")
        for key in ("target_snr_db", "snr_tolerance_db", "mixing_algorithm_version", "active_speech_method", "noise_offset_salt",
                    "audio_config_hashes"):
            if audio_now.get(key) != audio_frozen.get(key):
                errors.append(f"AUDIO_SETTINGS_MISMATCH: {key}")
    environment = environment_versions()
    frozen_environment = manifest.get("environment") or {}
    if environment["python"].rsplit(".", 1)[0] != str(frozen_environment.get("python", "")).rsplit(".", 1)[0]:
        errors.append("ENVIRONMENT_MISMATCH: version de Python")
    for package, version in (frozen_environment.get("packages") or {}).items():
        if environment["packages"].get(package) != version:
            errors.append(f"ENVIRONMENT_MISMATCH: {package} {environment['packages'].get(package)} != {version}")
    return {"ok": not errors, "errors": errors,
            "checked": {"files": len(frozen), "oracles": len(manifest.get("oracles") or {}), "freeze_id": manifest.get("freeze_id"),
                        "git_commit": manifest.get("git_commit")}}


__all__ = ["build_manifest", "validate_freeze", "audio_state", "load_manifest", "frozen_files", "normalized_sha256", "FREEZE_SCHEMA_VERSION"]
