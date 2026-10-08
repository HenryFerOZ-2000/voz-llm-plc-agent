"""
Fase 4A-DEFERRED: ejecucion automatizada de ensayos individuales con EVALUACION DIFERIDA.

  GENERAR ENSAYO (GUI): comando -> LLM -> semantica -> IOAllocator -> working map -> snapshot de E/S
      -> IR -> SCL -> verificaciones sin TIA -> artefactos + integrity_manifest.json. SE DETIENE.
  EVALUAR ENSAYO GUARDADO (GUI o CLI, misma funcion `evaluate_trial`):
      integridad -> precheck -> copia NUEVA del snapshot del TIA MASTER (Projects.Retrieve) ->
      PLC_Agent_IO -> program.scl congelado -> compilar -> guardar -> .zap18 del ensayo ->
      descarga a PLCSIM Advanced -> CPU RUN (Runtime API) -> Oracle -> veredicto.

La evaluacion NUNCA vuelve a ejecutar LLM, parser, IOAllocator, IR ni generador: solo usa los
artefactos congelados por hash. El TIA MASTER nunca se abre durante un ensayo: los ensayos parten
del snapshot .zap18 creado al VALIDAR MASTER, cuyo hash se verifica antes y despues.

CLI:
  python -m trial_experiments.deferred_evaluator <trial_dir> [--precheck] [--retry-reason "..."]
  python -m trial_experiments.deferred_evaluator --list | --next | --validate-master | --consolidate PHASE
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from trial_experiments import benchmark_catalog as BC
from trial_experiments import experimental_design as ED
from trial_experiments import oracle_schema as S
from trial_experiments import tia_classification as TC
from trial_experiments import system_resources as SR
from trial_experiments import tia_workspace as TW
from trial_experiments import trial_model

# ---------------------------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------------------------

MANIFEST_FILENAME = "integrity_manifest.json"
GENERATION_REPORT_FILENAME = "generation_report.json"
PROGRAM_FILENAME = "program.scl"
VARIABLES_FILENAME = "variables.json"
SNAPSHOT_FILENAME = "io_map_snapshot.json"
COMMAND_FILENAME = "command.txt"
SEMANTIC_FILENAME = "semantic_output.json"
FROZEN_ARTIFACTS = (COMMAND_FILENAME, SEMANTIC_FILENAME, VARIABLES_FILENAME, PROGRAM_FILENAME, SNAPSHOT_FILENAME)

EVALUATION_DIRNAME = "evaluation"
TIA_DIRNAME = "tia"
WORKING_PROJECT_DIRNAME = "working_project"
TIA_PROJECT_MANIFEST = "tia_project_manifest.json"
COMPILE_REPORT = "compile_report.json"
DOWNLOAD_REPORT = "download_report.json"
RUNTIME_REPORT = "runtime_report.json"
SOURCE_NAME_IN_TIA = "siemens_source.scl"

# Ciclo de vida (trial.json -> lifecycle_state). GENERADO y EVALUADO nunca se confunden.
STATE_GENERATED = "GENERATED"
STATE_EVALUATION_PENDING = "EVALUATION_PENDING"
STATE_TIA_PROJECT_PREPARED = "TIA_PROJECT_PREPARED"
STATE_COMPILED = "COMPILED"
STATE_TIA_ARCHIVED = "TIA_ARCHIVED"
STATE_DOWNLOADED = "DOWNLOADED"
STATE_RUNTIME_READY = "RUNTIME_READY"
STATE_EVALUATED = "EVALUATED"
STATE_INTEGRITY_FAILED = "INTEGRITY_FAILED"

GENERATION_SUCCESS = "SUCCESS"
GENERATION_FAILED = "FAILED"
EVALUATION_PENDING = "PENDING"
EVALUATION_COMPLETED = "COMPLETED"
EVALUATION_NOT_APPLICABLE = "NOT_APPLICABLE"
EVALUATION_INFRASTRUCTURE = "INFRASTRUCTURE_ERROR"
EVALUATION_INTEGRITY_FAILED = "INTEGRITY_FAILED"

ERROR_LEGACY = "LEGACY_TRIAL_UNSUPPORTED_FOR_DEFERRED_EVALUATION"
ERROR_INTEGRITY = "TRIAL_INTEGRITY_FAILED"
ERROR_MASTER_NOT_CONFIGURED = "TIA_MASTER_NOT_CONFIGURED"
ERROR_MASTER_NOT_VALIDATED = "TIA_MASTER_NOT_VALIDATED"
ERROR_MASTER_INTEGRITY = "MASTER_INTEGRITY_FAILED"
ERROR_MASTER_CHANGED = "MASTER_CHANGED_SINCE_VALIDATION"
ERROR_NOT_PENDING = "EVALUATION_NOT_PENDING"
ERROR_RETRY_REASON = "RETRY_REASON_REQUIRED"
ERROR_FORMAL = "FORMAL_EVALUATION_NOT_ALLOWED"

MASTER_DEVELOPMENT_READY = "DEVELOPMENT_READY"
MASTER_FORMAL_READY = "FORMAL_READY"
MASTER_INVALID = "INVALID"
WARNING_MASTER_LOGIC = "MASTER_CONTAINS_FUNCTIONAL_LOGIC"

# Bloques que el generador Siemens produce (siemens_scl_adapter: FB "<pou>", DB "DB_<pou>", OB "Main").
# Solo estos (y los declarados en el program.scl del ensayo) son APP_MANAGED: unicamente ellos se
# reemplazan/eliminan, y solo en la COPIA del ensayo. Nada mas del proyecto se toca nunca.
APP_MANAGED_BLOCK_NAMES = frozenset({"Main", "PLC_PRG", "DB_PLC_PRG"})
APP_MANAGED_TAG_TABLE = "PLC_Agent_IO"

MASTER_SNAPSHOT_DIR = Path("tia_master") / "snapshots"
# Archivos que TIA reescribe solo por abrir el proyecto: no forman parte de la huella del MASTER.
_MASTER_VOLATILE_DIRS = {"Logs", "TMP"}
_MASTER_VOLATILE_SUFFIXES = (".info", ".lck", ".tmp")
# Indice de busqueda que TIA V18 regenera al ABRIR el proyecto (observado en la validacion real:
# solo cambian IM/SearchIndex/* - segments_N, *.cfs, *.del). No es contenido del proyecto.
_MASTER_VOLATILE_PREFIXES = ("IM/SearchIndex/",)

DEFAULT_EVALUATION_TIMEOUT_S = 1800
_BLOCK_DECLARATION = re.compile(r'^\s*(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|TYPE)\s+"([^"]+)"', re.MULTILINE)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# GENERAR ENSAYO: cierre de la generacion + manifiesto de integridad
# ---------------------------------------------------------------------------------------------

def _present_audio_artifacts(trial_dir: Path) -> tuple[str, ...]:
    from trial_experiments import voice_protocol

    return tuple(name for name in voice_protocol.AUDIO_ARTIFACTS if (Path(trial_dir) / name).is_file())


def build_integrity_manifest(project_root: Path, trial_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    oracle = S.find_case_oracle(project_root, record["case_id"])
    oracle_ref = S.oracle_reference(oracle) if oracle else {"oracle_id": None, "oracle_version": None, "oracle_hash": None}
    return {
        "schema_version": 1,
        "trial_id": record["trial_id"],
        "generated_at": _now(),
        "benchmark_version": record.get("benchmark_version"),
        "case_id": record["case_id"],
        "variant_id": record.get("variant_id"),
        "input_mode": record.get("input_mode"),
        "trial_kind": record.get("trial_kind"),
        "experiment_phase": record.get("experiment_phase"),
        "canonical_case_hash": record.get("canonical_case_hash"),
        "variant_hash": record.get("variant_hash"),
        "oracle": {**oracle_ref, "oracle_status": (oracle or {}).get("approval", {}).get("status")},
        "reference_text_hash": record.get("reference_text_hash"),
        "effective_input_text_hash": record.get("effective_input_text_hash"),
        # Audio (VOICE_CLEAN / VOICE_NOISE): evidencia experimental congelada junto al resto.
        "files": {name: sha256_file(trial_dir / name) for name in FROZEN_ARTIFACTS + _present_audio_artifacts(trial_dir)},
    }


def finalize_generation(project_root: Path, trial_dir: Path, package_dir: Path | None) -> dict[str, Any]:
    """
    Cierra GENERAR ENSAYO: copia program.scl/variables.json del paquete, escribe
    generation_report.json e integrity_manifest.json y deja evaluation = PENDING. Si la generacion
    ya fallo (final_status fijado por el pipeline), solo registra generation = FAILED.
    """
    trial_dir = Path(trial_dir)
    record = trial_model.load_trial(trial_dir)
    if record.get("final_status"):
        return trial_model.update_trial(trial_dir, {
            "generation": {"status": GENERATION_FAILED, "completed_at": _now(), "failure_category": record.get("failure_category")},
            "evaluation": {"status": EVALUATION_NOT_APPLICABLE, "attempts": []},
        })
    errors: list[str] = []
    if package_dir is not None and Path(package_dir).exists():
        for source_name, target_name in (("siemens_source.scl", PROGRAM_FILENAME), ("variables.json", VARIABLES_FILENAME)):
            source = Path(package_dir) / source_name
            if source.exists():
                shutil.copyfile(source, trial_dir / target_name)
    missing = [name for name in FROZEN_ARTIFACTS if not (trial_dir / name).exists()]
    if missing:
        errors.append("Faltan artefactos congelables: " + ", ".join(missing))
        trial_model.update_trial(trial_dir, {"failure_stage": "generate"})
        trial_model.finalize_trial(trial_dir, trial_model.FINAL_STATUS_FAIL, errors)
        record = trial_model.load_trial(trial_dir)
        return trial_model.update_trial(trial_dir, {
            **ED.classify_trial(record),
            "generation": {"status": GENERATION_FAILED, "completed_at": _now(), "errors": errors},
            "evaluation": {"status": EVALUATION_NOT_APPLICABLE, "attempts": []},
        })
    generated_code_id = Path(package_dir).name if package_dir else None
    _write_json(trial_dir / GENERATION_REPORT_FILENAME, {
        "trial_id": record["trial_id"],
        "generated_at": _now(),
        "generated_code_id": generated_code_id,
        "package_dir": str(package_dir) if package_dir else None,
        "stages": record.get("stages"),
        "verification": record.get("verification"),
        "resource_check": record.get("resource_check"),
        "timing": record.get("timing"),
        "model": record.get("model"),
        "parser_mode": record.get("parser_mode"),
        "note": "Generacion sin TIA/PLCSIM/Oracle. La evaluacion se hace despues sobre estos artefactos congelados.",
    })
    manifest = build_integrity_manifest(project_root, trial_dir, record)
    _write_json(trial_dir / MANIFEST_FILENAME, manifest)
    return trial_model.update_trial(trial_dir, {
        "generated_code_id": generated_code_id,
        "lifecycle_state": STATE_EVALUATION_PENDING,
        "oracle_reference": {key: manifest["oracle"].get(key) for key in ("oracle_id", "oracle_version", "oracle_hash")},
        "generation": {"status": GENERATION_SUCCESS, "completed_at": manifest["generated_at"], "generated_code_id": generated_code_id},
        "evaluation": {"status": EVALUATION_PENDING, "attempt": 0, "attempts": [], "final_verdict": None},
    })


def verify_trial_integrity(trial_dir: Path) -> dict[str, Any]:
    """Recalcula los hashes congelados. Sin manifiesto -> LEGACY (nunca se generan hashes retroactivos)."""
    trial_dir = Path(trial_dir)
    path = trial_dir / MANIFEST_FILENAME
    if not path.exists():
        return {"ok": False, "code": ERROR_LEGACY, "errors": [f"{ERROR_LEGACY}: el ensayo no tiene {MANIFEST_FILENAME}."]}
    manifest = _read_json(path)
    errors = []
    for name, expected in (manifest.get("files") or {}).items():
        target = trial_dir / name
        actual = sha256_file(target) if target.exists() else None
        if actual != expected:
            errors.append(f"{ERROR_INTEGRITY}: {name} {'falta' if actual is None else 'cambio'} desde la generacion.")
    return {"ok": not errors, "code": ERROR_INTEGRITY if errors else None, "errors": errors, "manifest": manifest}


# ---------------------------------------------------------------------------------------------
# TIA MASTER
# ---------------------------------------------------------------------------------------------

def load_master_config(project_root: Path) -> dict[str, Any]:
    """tia.experiment_master (config/tia_projects.json): independiente del proyecto Normal."""
    import tia_projects

    return tia_projects.get_experiment_master(project_root)


def save_master_config(project_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    import tia_projects

    return tia_projects.save_experiment_master(project_root, config)


def select_master(project_root: Path, master_project_path: str | Path) -> dict[str, Any]:
    """SELECCIONAR MASTER: guarda la ruta; invalida cualquier validacion anterior. Nunca el proyecto Normal."""
    import tia_projects

    path = Path(master_project_path)
    if path.suffix.lower() != ".ap18" or not path.exists():
        raise ValueError(f"El MASTER debe ser un proyecto TIA V18 (.ap18) existente: {path}")
    tia_projects.assert_master_not_normal(project_root, path)
    config = {"path": str(path), "selected_at": _now(), "hash": None, "status": None, "validation": None, "snapshot": None}
    save_master_config(project_root, config)
    return config


def master_folder_manifest(master_project_path: str | Path) -> dict[str, str]:
    """SHA-256 por archivo del directorio del proyecto MASTER (sin logs/temporales de TIA)."""
    folder = Path(master_project_path).parent
    manifest: dict[str, str] = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        relative = path.relative_to(folder)
        key = str(relative).replace("\\", "/")
        if (relative.parts[0] in _MASTER_VOLATILE_DIRS or path.suffix.lower() in _MASTER_VOLATILE_SUFFIXES
                or key.startswith(_MASTER_VOLATILE_PREFIXES)):
            continue
        manifest[key] = sha256_file(path)
    return manifest


def manifest_fingerprint(manifest: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative, file_hash in sorted(manifest.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(file_hash.encode("ascii"))
    return digest.hexdigest()


def master_folder_fingerprint(master_project_path: str | Path) -> str:
    """Huella SHA-256 del directorio completo del proyecto MASTER (sin logs/temporales de TIA)."""
    return manifest_fingerprint(master_folder_manifest(master_project_path))


def manifest_changes(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    return {"added": sorted(set(after) - set(before)), "removed": sorted(set(before) - set(after)),
            "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k])}


def _is_s71500(type_identifier: str | None) -> bool:
    text = str(type_identifier or "").upper().replace(" ", "")
    return "6ES751" in text or "CPU15" in text


def assess_master(info: dict[str, Any]) -> dict[str, Any]:
    """Estado del MASTER a partir de lo que describio el bridge (sin TIA)."""
    errors: list[str] = []
    warnings: list[str] = []
    if info.get("plc_count") != 1:
        errors.append(f"El MASTER debe tener exactamente 1 PLC (tiene {info.get('plc_count')}).")
    if not _is_s71500(info.get("cpu_type_identifier")):
        errors.append(f"La CPU del MASTER no es S7-1500: {info.get('cpu_type_identifier')}.")
    addresses = [node.get("address") for interface in info.get("interfaces") or [] for node in interface.get("nodes") or []
                 if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", str(node.get("address") or ""))]
    if not addresses:
        errors.append("El MASTER no tiene ninguna interfaz con direccion IP configurada.")
    blocks = info.get("blocks") or []
    managed = [block["name"] for block in blocks if block.get("name") in APP_MANAGED_BLOCK_NAMES]
    unmanaged = [block["name"] for block in blocks if block.get("name") not in APP_MANAGED_BLOCK_NAMES]
    if unmanaged:
        warnings.append(f"{WARNING_MASTER_LOGIC}: bloques no administrados por la aplicacion: {', '.join(unmanaged)}.")
    if any(name != "Main" for name in managed):
        warnings.append("El MASTER contiene logica administrada de un programa anterior "
                        f"({', '.join(n for n in managed if n != 'Main')}); se reemplaza/elimina solo en la copia del ensayo.")
    # X1 = nodo que TIA nombra "X1" (no el nombre del DeviceItem: "DP interface_1" tambien es interface_1).
    x1_nodes = [node for interface in info.get("interfaces") or [] for node in interface.get("nodes") or []
                if str(node.get("name", "")).strip().upper() == "X1"]
    x1_ip = next((node.get("address") for node in x1_nodes if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", str(node.get("address") or ""))), None)
    # La validacion automatica nunca declara FORMAL_READY: como maximo DEVELOPMENT_READY e informa si
    # se cumplen los criterios formales. FORMAL_READY exigira una aprobacion explicita del investigador.
    if addresses and not x1_ip:
        # La descarga experimental usa la interfaz "1 X1" (config download_targets.experiment).
        errors.append("El MASTER no tiene una interfaz X1 con direccion IP (la descarga a PLCSIM usa X1).")
    formal_criteria = not errors and not unmanaged and bool(x1_ip)
    status = MASTER_INVALID if errors else MASTER_DEVELOPMENT_READY
    return {
        "master_status": status,
        "formal_ready_criteria_met": formal_criteria,
        "errors": errors,
        "warnings": warnings,
        "app_managed_blocks": managed,
        "unmanaged_blocks": unmanaged,
        "ip_addresses": addresses,
        "x1_interface_present": bool(x1_nodes),
        "x1_ip_address": x1_ip,
        "plc_agent_io": "PRESENT" if info.get("plc_agent_io_present") else "CREATABLE",
        "block_count": len(blocks),
    }


ZAP_EXTENSION = ".zap18"
# Limite real observado en TIA V18 (Project.Archive): "A maximum of 143 characters is allowed".
TIA_ARCHIVE_MAX_PATH = 143
ERROR_MASTER_ARCHIVE_PATH_TOO_LONG = "MASTER_ARCHIVE_PATH_TOO_LONG"
ERROR_MASTER_OPEN_FAILED = "MASTER_OPEN_FAILED"
ERROR_MASTER_SAVE_FAILED = "MASTER_SAVE_FAILED"
ERROR_MASTER_UNSAVED_CHANGES = "MASTER_UNSAVED_CHANGES"
ERROR_MASTER_ARCHIVE_FAILED = "MASTER_ARCHIVE_FAILED"
ERROR_MASTER_ARCHIVE_NOT_CREATED = "MASTER_ARCHIVE_NOT_CREATED"
ERROR_MASTER_ARCHIVE_EMPTY = "MASTER_ARCHIVE_EMPTY"
ERROR_MASTER_CHANGED_DURING_VALIDATION = "MASTER_CHANGED_DURING_VALIDATION"
_MASTER_BRIDGE_ERRORS = {ERROR_MASTER_OPEN_FAILED, ERROR_MASTER_SAVE_FAILED, ERROR_MASTER_UNSAVED_CHANGES,
                         ERROR_MASTER_ARCHIVE_FAILED, ERROR_MASTER_ARCHIVE_NOT_CREATED, ERROR_MASTER_ARCHIVE_EMPTY}


def master_snapshot_target(project_root: Path, master_path: str | Path, stamp: str | None = None) -> dict[str, str]:
    """
    Destino del snapshot. Project.Archive usa targetName LITERALMENTE como nombre del archivo: el
    nombre se construye explicito con .zap18 y la ruta esperada es exactamente directorio/targetName.
    El snapshot vive en la cache de la aplicacion (tia_master/snapshots), nunca en la carpeta del MASTER.
    """
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    directory = (Path(project_root) / MASTER_SNAPSHOT_DIR).resolve()
    # Nombre corto: TIA V18 limita las rutas a 143 caracteres, y el proyecto dentro del snapshot se llama
    # <targetName>.ap18, nombre que luego hereda cada Retrieve en el workspace del ensayo.
    compact = "".join(ch for ch in stamp if ch.isdigit())[-12:]
    target_name = f"M{compact}{ZAP_EXTENSION}"
    return {"directory": str(directory), "target_name": target_name, "expected_path": str(directory / target_name), "stamp": stamp}


def check_snapshot_file(path: str | Path | None, reported_sha256: str | None) -> tuple[str | None, str | None]:
    """(codigo_error, sha256). Un snapshot solo es valido si existe exactamente, pesa > 0 y su hash coincide."""
    if not path or not Path(path).is_file() or not str(path).lower().endswith(ZAP_EXTENSION):
        return ERROR_MASTER_ARCHIVE_NOT_CREATED, None
    if Path(path).stat().st_size <= 0:
        return ERROR_MASTER_ARCHIVE_EMPTY, None
    digest = sha256_file(Path(path))
    if reported_sha256 and digest != reported_sha256:
        return ERROR_MASTER_ARCHIVE_FAILED, digest
    return None, digest


def validate_master(project_root: Path, bridge: Callable[[dict[str, Any], Path], dict[str, Any]] | None = None) -> dict[str, Any]:
    """
    VALIDAR MASTER: abre el MASTER (V18), lo describe y crea su snapshot .zap18 (Project.Archive,
    Compressed, targetName explicito .zap18). Nunca guarda ni modifica el MASTER. Sin un .zap18
    verificado (existe, > 0 bytes, SHA-256) el MASTER queda INVALID: nunca DEVELOPMENT_READY.
    """
    import tia_projects

    config = load_master_config(project_root)
    master_path = config.get("path")
    if not master_path:
        raise ValueError(f"{ERROR_MASTER_NOT_CONFIGURED}: seleccione primero el proyecto TIA MASTER.")
    tia_projects.assert_master_not_normal(project_root, master_path)
    import tia_openness

    tia_config = tia_openness.load_tia_config(project_root)
    target = master_snapshot_target(project_root, master_path)
    if Path(target["directory"]).is_relative_to(Path(master_path).parent.resolve()):
        raise ValueError("El snapshot nunca puede guardarse dentro de la carpeta del MASTER.")
    if len(target["expected_path"]) > TIA_ARCHIVE_MAX_PATH:
        raise ValueError(f"{ERROR_MASTER_ARCHIVE_PATH_TOO_LONG}: {target['expected_path']} tiene {len(target['expected_path'])} "
                         f"caracteres (TIA V18 admite {TIA_ARCHIVE_MAX_PATH}). Mueva el proyecto a una ruta mas corta.")
    Path(target["directory"]).mkdir(parents=True, exist_ok=True)
    files_before = master_folder_manifest(master_path)
    fingerprint_before = manifest_fingerprint(files_before)
    request = {
        "action": "validate_master",
        "master_project_path": str(master_path),
        "archive_dir": target["directory"],
        "archive_name": target["target_name"],
        "plc_name": str(tia_config.get("plc_name", "")),
        "attach_to_running": bool(tia_config.get("attach_to_running", True)),
    }
    report = (bridge or run_bridge)(request, Path(target["directory"]) / f"validation_{target['stamp']}", project_root=project_root)
    files_after = master_folder_manifest(master_path)
    fingerprint_after = manifest_fingerprint(files_after)
    master_changes = manifest_changes(files_before, files_after)
    description = report.get("master") or {}

    errors: list[str] = []
    snapshot_hash = None
    bridge_status = str(report.get("status") or "")
    if bridge_status != "TIA_MASTER_VALIDATION_PASSED":
        code = bridge_status if bridge_status in _MASTER_BRIDGE_ERRORS else ERROR_MASTER_ARCHIVE_FAILED
        errors.append(f"{code}: " + " | ".join(str(e) for e in report.get("errors") or [bridge_status or "sin reporte"]))
    elif Path(str(report.get("archive_path") or "")).resolve() != Path(target["expected_path"]):
        errors.append(f"{ERROR_MASTER_ARCHIVE_NOT_CREATED}: TIA informo {report.get('archive_path')} y se esperaba {target['expected_path']}.")
    else:
        snapshot_error, snapshot_hash = check_snapshot_file(target["expected_path"], report.get("archive_sha256"))
        if snapshot_error:
            errors.append(f"{snapshot_error}: {target['expected_path']}")
            snapshot_hash = None
    if fingerprint_after != fingerprint_before:
        errors.append(f"{ERROR_MASTER_CHANGED_DURING_VALIDATION}: el contenido del MASTER cambio durante la validacion "
                      f"({master_changes}).")

    assessment = assess_master(description) if description else {"master_status": MASTER_INVALID, "errors": [], "warnings": []}
    passed = not errors and snapshot_hash is not None
    if not passed:
        assessment["master_status"] = MASTER_INVALID
    validation = {
        "validated_at": _now(),
        **assessment,
        "status": "VALID" if passed and assessment["master_status"] != MASTER_INVALID else "INVALID",
        "errors": errors + list(assessment.get("errors") or []),
        "warnings": list(assessment.get("warnings") or []) + list(report.get("warnings") or []),
        "tia_version": report.get("tia_version"),
        "master_project_version": report.get("master_project_version"),
        "project_name": description.get("project_name"),
        "internal_project_name": description.get("project_name"),
        "cpu_type_identifier": description.get("cpu_type_identifier"),
        "cpu_device_item": description.get("cpu_device_item"),
        "cpu_type_name": description.get("cpu_TypeName"),
        "cpu_order_number": description.get("cpu_OrderNumber"),
        "cpu_firmware": description.get("cpu_FirmwareVersion"),
        "plc_name": description.get("plc_name"),
        "interfaces": description.get("interfaces"),
        "blocks": description.get("blocks"),
        "master_folder_fingerprint": fingerprint_before,
        "master_folder_fingerprint_after": fingerprint_after,
        "master_folder_changes": master_changes,
        "bridge_status": bridge_status,
        "archive": {key: report.get(key) for key in (
            "archive_source_project", "archive_target_directory", "archive_target_name", "archive_expected_path", "archive_mode",
            "archive_actual_files_created", "archive_size_bytes", "archive_error", "archive_error_type", "archive_error_hint")},
    }
    config["validation"] = validation
    config["snapshot"] = {"archive_path": target["expected_path"], "archive_sha256": snapshot_hash, "created_at": validation["validated_at"],
                          "size_bytes": report.get("archive_size_bytes")} if passed else None
    config["hash"] = snapshot_hash if passed else None
    config["status"] = validation["master_status"]
    save_master_config(project_root, config)
    return config


def master_internal_project_name(config: dict[str, Any]) -> str | None:
    """Nombre interno real del proyecto MASTER, registrado por VALIDAR MASTER (no del nombre del snapshot)."""
    validation = config.get("validation") or {}
    return validation.get("internal_project_name") or validation.get("project_name")


def master_app_managed_blocks(config: dict[str, Any]) -> list[str]:
    return list(((config.get("validation") or {}).get("app_managed_blocks")) or [])


# ---------------------------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------------------------

def run_bridge(
    request: dict[str, Any],
    work_dir: Path,
    project_root: Path | None = None,
    timeout_s: int | None = None,
    on_archived: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Ejecuta el bridge Openness con `request`. Timeout o caida -> reporte de infraestructura.
    Con `on_archived` y request["handshake_dir"]: cuando el bridge escribe archived.json se llama a
    on_archived(info) (copia y verificacion de evidencia) y su decision se escribe en proceed.json.
    """
    import tia_openness

    root = project_root or Path.cwd()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    request_path = work_dir / f"tia_{request['action']}_request.json"
    result_path = work_dir / f"tia_{request['action']}_result.json"
    request = {**request, "result_path": str(result_path.resolve()), "created_at": _now(), "tia_version": "V18"}
    _write_json(request_path, request)
    build = tia_openness.build_openness_bridge(root)
    if not build.get("built"):
        return {"status": "BRIDGE_BUILD_FAILED", "errors": build.get("errors", [])}
    environment = os.environ.copy()
    environment["PATH"] = str(tia_openness.DEFAULT_PORTAL_ROOT / "Bin") + os.pathsep + environment.get("PATH", "")
    timeout = timeout_s or int(tia_openness.load_tia_config(root).get("deferred_timeout_seconds", DEFAULT_EVALUATION_TIMEOUT_S))
    handshake_dir = Path(request["handshake_dir"]) if request.get("handshake_dir") else None
    stdout_path, stderr_path = work_dir / "bridge_stdout.txt", work_dir / "bridge_stderr.txt"
    with stdout_path.open("w", encoding="utf-8", errors="replace") as out, stderr_path.open("w", encoding="utf-8", errors="replace") as err:
        process = subprocess.Popen([build["exe_path"], str(request_path)], stdout=out, stderr=err, env=environment)
        deadline = time.monotonic() + timeout
        handled = False
        while process.poll() is None:
            if handshake_dir is not None and on_archived is not None and not handled and (handshake_dir / TW.ARCHIVED_SIGNAL).exists():
                handled = True
                try:
                    decision = on_archived(_read_json(handshake_dir / TW.ARCHIVED_SIGNAL))
                except Exception as error:  # nunca descargar si la verificacion de evidencia fallo
                    decision = {"download": False, "reason": f"{TW.ERROR_ARCHIVE_COPY_FAILED}: {error}"}
                _write_json(handshake_dir / TW.PROCEED_SIGNAL, decision)
            if time.monotonic() > deadline:
                process.kill()
                return {"status": "TIA_BRIDGE_TIMEOUT", "errors": [f"El bridge TIA supero {timeout} s (proceso terminado)."],
                        "warnings": ["Puede quedar una instancia de TIA Portal sin interfaz abierta: cierrela antes del siguiente ensayo."]}
            time.sleep(0.5)
    report = _read_json(result_path) if result_path.exists() else {}
    if not report:
        report = {"status": "TIA_BRIDGE_CRASHED", "errors": [f"El bridge termino sin reporte (codigo {process.returncode})."]}
    report.update({"bridge_return_code": process.returncode,
                   "bridge_stderr": stderr_path.read_text(encoding="utf-8", errors="replace").strip()[-4000:]})
    return report


def declared_blocks(program_scl: str) -> list[str]:
    return [match.group(2) for match in _BLOCK_DECLARATION.finditer(program_scl)]


def trial_tag_payload(variables: list[dict[str, Any]], snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """PLC_Agent_IO deseado: externas del programa congelado + canales LOCKED del snapshot congelado."""
    from platforms.siemens_scl_adapter import SIEMENS_TYPE_MAP

    def _address(raw: Any) -> str:
        return str(raw or "").replace("%IX", "%I").replace("%QX", "%Q").replace("%MX", "%M")

    tags: dict[str, dict[str, str]] = {}
    for variable in variables or []:
        if isinstance(variable, dict) and variable.get("class") in ("input", "output"):
            name = str(variable.get("name"))
            tags[name] = {"name": name, "data_type": str(variable.get("siemens_type") or SIEMENS_TYPE_MAP.get(str(variable.get("type", "BOOL")).upper(), "Bool")),
                          "address": _address(variable.get("siemens_address") or variable.get("location"))}
    for channel in snapshot.get("channels") or []:
        if str(channel.get("state", "")).upper() == "LOCKED" and channel.get("functional_name"):
            name = str(channel["functional_name"])
            tags.setdefault(name, {"name": name, "data_type": SIEMENS_TYPE_MAP.get(str(channel.get("data_type") or "BOOL").upper(), "Bool"),
                                   "address": _address(channel.get("address"))})
    return list(tags.values())


# ---------------------------------------------------------------------------------------------
# Precheck
# ---------------------------------------------------------------------------------------------

def environment_precheck(project_root: Path, phase: str) -> dict[str, Any]:
    """
    Comprobaciones de ENTORNO que no dependen del ensayo (MASTER validado e integro, rutas cortas
    para TIA, destino solo PLCSIM, FORMAL congelado). EJECUTAR ENSAYO COMPLETO las ejecuta ANTES de
    capturar audio o llamar al LLM, para no gastar un ensayo en un entorno que no puede evaluarlo.
    """
    import tia_openness
    import tia_projects

    errors: list[str] = []
    trial_kind = trial_model.trial_kind_for_phase(phase)
    if trial_kind == trial_model.TRIAL_KIND_FORMAL:
        allowed, reasons = ED.check_formal_trial_allowed(project_root)
        if not allowed:
            errors.extend(reasons)
    config = load_master_config(project_root)
    validation = config.get("validation") or {}
    snapshot = config.get("snapshot") or {}
    path_validation = None
    if not config.get("path"):
        errors.append(f"{ERROR_MASTER_NOT_CONFIGURED}: configure el TIA MASTER (Configurar TIA).")
    elif validation.get("status") != "VALID" or not snapshot.get("archive_path"):
        errors.append(f"{ERROR_MASTER_NOT_VALIDATED}: pulse VALIDAR MASTER.")
    else:
        archive = Path(snapshot["archive_path"])
        if not archive.exists() or sha256_file(archive) != snapshot.get("archive_sha256"):
            errors.append(f"{ERROR_MASTER_INTEGRITY}: el snapshot del MASTER falta o cambio.")
        else:
            path_validation = TW.validate_paths(TW.workspace_root(project_root) / TW.format_id(0), TW.format_id(0),
                                                master_internal_project_name(config), TIA_ARCHIVE_MAX_PATH)
            errors.extend(path_validation["errors"])
        try:
            tia_projects.assert_master_not_normal(project_root, config["path"])
        except tia_projects.TiaProjectGuardError as error:
            errors.append(str(error))
        if Path(config["path"]).exists() and master_folder_fingerprint(config["path"]) != validation.get("master_folder_fingerprint_after"):
            errors.append(f"{ERROR_MASTER_CHANGED}: el proyecto MASTER cambio desde la validacion; valide de nuevo.")
        if trial_kind == trial_model.TRIAL_KIND_FORMAL and validation.get("master_status") != MASTER_FORMAL_READY:
            errors.append(f"{ERROR_FORMAL}: un FORMAL_TRIAL exige un MASTER FORMAL_READY.")
    target = tia_openness.resolve_download_target(tia_openness.load_tia_config(project_root), tia_openness.DOWNLOAD_PURPOSE_EXPERIMENT)
    if target.get("target_type") != "PLCSIM_ADVANCED" or ED.load_design(project_root)["architecture"].get("physical_download") != "forbidden":
        errors.append("PHYSICAL_DOWNLOAD_FORBIDDEN: el destino experimental debe ser PLCSIM_ADVANCED.")
    # Memoria: no se inicia un ensayo completo (ni audio ni LLM) si TIA no va a poder abrirse.
    memory = SR.memory_preflight(project_root)
    errors.extend(memory["errors"])
    return {"ok": not errors, "errors": errors, "warnings": list(validation.get("warnings") or []), "path_validation": path_validation,
            "memory": memory}


def precheck(project_root: Path, trial_dir: Path, retry_reason: str | None = None) -> dict[str, Any]:
    """Todo lo que se verifica ANTES de abrir TIA. Cualquier fallo -> ABORT."""
    trial_dir = Path(trial_dir)
    errors: list[str] = []
    warnings: list[str] = []
    record = trial_model.load_trial(trial_dir)
    integrity = verify_trial_integrity(trial_dir)
    if not integrity["ok"]:
        return {"ok": False, "integrity_failed": integrity["code"] == ERROR_INTEGRITY, "legacy": integrity["code"] == ERROR_LEGACY,
                "errors": integrity["errors"], "warnings": [], "record": record}
    manifest = integrity["manifest"]
    generation = record.get("generation") or {}
    evaluation = record.get("evaluation") or {}
    if generation.get("status") != GENERATION_SUCCESS:
        errors.append("La generacion del ensayo no termino con SUCCESS.")
    last = (evaluation.get("attempts") or [{}])[-1] if evaluation.get("attempts") else {}
    if evaluation.get("status") == EVALUATION_PENDING:
        pass
    elif evaluation.get("status") == EVALUATION_INFRASTRUCTURE and last.get("final_status") == trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR:
        if not (retry_reason and retry_reason.strip()):
            errors.append(f"{ERROR_RETRY_REASON}: el reintento tecnico exige retry_reason explicito.")
    else:
        errors.append(f"{ERROR_NOT_PENDING}: evaluacion en estado {evaluation.get('status')} (solo PENDING o reintento de INFRASTRUCTURE_ERROR).")

    # Benchmark / Oracle congelados
    case = BC.get_case(project_root, manifest["case_id"]) or {}
    if BC.load_catalog(project_root).get("benchmark_version") != manifest.get("benchmark_version"):
        errors.append("benchmark_version actual distinta de la del ensayo.")
    if case and BC.case_hash(case) != manifest.get("canonical_case_hash"):
        errors.append("canonical_case_hash actual distinto del congelado en el ensayo.")
    variant_text = (case.get("variants") or {}).get(manifest.get("variant_id"))
    if variant_text is None or BC.variant_hash(variant_text) != manifest.get("variant_hash"):
        errors.append("variant_hash actual distinto del congelado en el ensayo.")
    try:
        oracle = S.load_oracle(project_root, manifest["case_id"])
        reference = S.oracle_reference(oracle)
        if oracle["approval"]["status"] != "FROZEN":
            errors.append(f"El Oracle {manifest['case_id']} no esta FROZEN.")
        if reference["oracle_hash"] != (manifest.get("oracle") or {}).get("oracle_hash"):
            errors.append("El hash del Oracle no coincide con el congelado al generar el ensayo.")
        if S.runtime_support(oracle) != S.RUNTIME_EXECUTABLE_NOW:
            errors.append(f"El Oracle {manifest['case_id']} requiere extension del Runtime (no evaluable hoy).")
    except S.OracleError as error:
        errors.append(f"Oracle no disponible: {error}")

    # Formal
    if record.get("trial_kind") == trial_model.TRIAL_KIND_FORMAL:
        allowed, reasons = ED.check_formal_trial_allowed(project_root)
        if not allowed:
            errors.extend(reasons)

    # MASTER
    config = load_master_config(project_root)
    validation = config.get("validation") or {}
    snapshot = config.get("snapshot") or {}
    if not config.get("path"):
        errors.append(f"{ERROR_MASTER_NOT_CONFIGURED}: configure el TIA MASTER (Configurar TIA).")
    elif validation.get("status") != "VALID" or not snapshot.get("archive_path"):
        errors.append(f"{ERROR_MASTER_NOT_VALIDATED}: pulse VALIDAR MASTER.")
    else:
        archive = Path(snapshot["archive_path"])
        if not archive.exists() or sha256_file(archive) != snapshot.get("archive_sha256"):
            errors.append(f"{ERROR_MASTER_INTEGRITY}: el snapshot del MASTER falta o cambio.")
        import tia_projects

        try:
            tia_projects.assert_master_not_normal(project_root, config["path"])
        except tia_projects.TiaProjectGuardError as error:
            errors.append(str(error))
        if Path(config["path"]).exists() and master_folder_fingerprint(config["path"]) != validation.get("master_folder_fingerprint_after"):
            errors.append(f"{ERROR_MASTER_CHANGED}: el proyecto MASTER cambio desde la validacion; valide de nuevo.")
        if record.get("trial_kind") == trial_model.TRIAL_KIND_FORMAL and validation.get("master_status") != MASTER_FORMAL_READY:
            errors.append(f"{ERROR_FORMAL}: un FORMAL_TRIAL exige un MASTER FORMAL_READY.")
        warnings.extend(validation.get("warnings") or [])

    # Separacion de proyectos: la copia del ensayo nunca vive dentro del proyecto Normal ni del MASTER,
    # y la plantilla es siempre el snapshot del MASTER (nunca un ensayo anterior).
    import tia_projects

    normal_path = tia_projects.normal_project_path(project_root)
    resolved_trial = trial_dir.resolve()
    for label, project in (("Normal", normal_path), ("MASTER", config.get("path"))):
        if project and resolved_trial.is_relative_to(Path(project).parent.resolve()):
            errors.append(f"PROJECT_GUARD: el ensayo esta dentro de la carpeta del proyecto {label}.")
    snapshot_path = (config.get("snapshot") or {}).get("archive_path")
    if snapshot_path and Path(snapshot_path).resolve().is_relative_to(trial_model.get_results_experiments_dir(project_root).parent.resolve()):
        errors.append("TEMPLATE_GUARD: el snapshot del MASTER no puede ser un artefacto de otro ensayo.")

    # Rutas que vera TIA (workspace corto): se validan con un ID de la misma longitud que el real.
    path_validation = None
    if snapshot_path and Path(snapshot_path).exists():
        path_validation = TW.validate_paths(TW.workspace_root(project_root) / TW.format_id(0), TW.format_id(0),
                                            master_internal_project_name(config), TIA_ARCHIVE_MAX_PATH)
        errors.extend(path_validation["errors"])

    # Destino (dos capas)
    import tia_openness

    target = tia_openness.resolve_download_target(tia_openness.load_tia_config(project_root), tia_openness.DOWNLOAD_PURPOSE_EXPERIMENT)
    architecture = ED.load_design(project_root)["architecture"]
    if target.get("target_type") != "PLCSIM_ADVANCED" or architecture.get("physical_download") != "forbidden":
        errors.append("PHYSICAL_DOWNLOAD_FORBIDDEN: el destino experimental debe ser PLCSIM_ADVANCED.")
    return {"ok": not errors, "integrity_failed": False, "legacy": False, "errors": errors, "warnings": warnings,
            "record": record, "manifest": manifest, "master": config, "path_validation": path_validation}


def check_plcsim(runtime_report: dict[str, Any], instance_name: str) -> list[str]:
    errors = []
    if not runtime_report.get("connected") or runtime_report.get("instance_name") != instance_name:
        errors.append(f"PLCSIM_NOT_READY: instancia {instance_name} no conectada ({runtime_report.get('status')}).")
    if not _is_s71500(runtime_report.get("cpu_type")):
        errors.append(f"PLCSIM_CPU_NOT_S71500: {runtime_report.get('cpu_type')}.")
    if runtime_report.get("network_match") is not True:
        errors.append(f"PLCSIM_NETWORK_MISMATCH: {runtime_report.get('network_status')}.")
    return errors


# ---------------------------------------------------------------------------------------------
# EVALUAR ENSAYO GUARDADO
# ---------------------------------------------------------------------------------------------

MEMORY_PREFLIGHT_REPORT = "memory_preflight.json"
CLEANUP_REPORT = "workspace_cleanup.json"
DIAGNOSTICS_DIRNAME = "diagnostics"
ERROR_PERSISTENCE_VERIFICATION = "TRIAL_PERSISTENCE_VERIFICATION_FAILED"

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret|authorization)\b(\s*[=:]\s*)(\S+)"),
)


def _redact(text: str) -> str:
    """Nunca se persisten secretos: claves conocidas del entorno y patrones tipicos (sk-..., api_key=...)."""
    text = str(text)
    for name, value in os.environ.items():
        if value and len(value) >= 8 and any(word in name.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            text = text.replace(value, "***")
    text = _SECRET_PATTERNS[0].sub("***", text)
    return _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)


def record_unexpected_error(trial_dir: Path, error: BaseException, phase: str, attempt: int | None = None,
                            trial_id: str | None = None, annotate_trial: bool = True) -> str | None:
    """
    Evidencia de diagnostico de una excepcion inesperada (evaluacion o worker de la GUI):
    <trial_dir>/evaluation/diagnostics/<stamp>_<fase>.json con tipo, mensaje, fase, trial_id, intento,
    timestamp y traceback (sin secretos). Con annotate_trial anade evaluation.last_unexpected_error en
    trial.json SIN tocar status/veredicto. Nunca lanza; devuelve la ruta o None.
    """
    try:
        trial_dir = Path(trial_dir)
        if not (trial_dir / trial_model.TRIAL_FILENAME).is_file():
            return None
        record = trial_model.load_trial(trial_dir)
        evaluation = record.get("evaluation") or {}
        now = datetime.now()
        payload = {
            "trial_id": trial_id or record.get("trial_id"),
            "attempt": attempt if attempt is not None else evaluation.get("attempt"),
            "phase": phase,
            "timestamp": now.isoformat(timespec="milliseconds"),
            "exception_type": type(error).__name__,
            "exception_message": _redact(str(error)),
            "traceback": _redact("".join(traceback.format_exception(type(error), error, error.__traceback__))),
            "evaluation_status_at_error": evaluation.get("status"),
            "final_verdict_at_error": record.get("final_verdict"),
        }
        safe_phase = re.sub(r"[^A-Za-z0-9_]+", "_", phase)[:40]
        path = trial_dir / EVALUATION_DIRNAME / DIAGNOSTICS_DIRNAME / f"{now.strftime('%Y%m%d_%H%M%S_%f')}_{safe_phase}.json"
        _write_json(path, payload)
        if annotate_trial:
            trial_model.update_trial(trial_dir, {"evaluation": {"last_unexpected_error": {
                key: payload[key] for key in ("phase", "attempt", "timestamp", "exception_type", "exception_message")} | {
                "diagnostic_path": str(path)}}})
        return str(path)
    except Exception:  # noqa: BLE001 - el diagnostico nunca puede empeorar el fallo original
        return None


def _verify_persisted(trial_dir: Path, trial_id: str, attempt_number: int, final_status: str) -> list[str]:
    """Relee trial.json: el resultado debe estar completo y coherente antes de cualquier mantenimiento."""
    record = trial_model.load_trial(Path(trial_dir))
    evaluation = record.get("evaluation") or {}
    attempts = evaluation.get("attempts") or []
    last = attempts[-1] if attempts else {}
    problems = []
    if record.get("trial_id") != trial_id:
        problems.append(f"trial_id {record.get('trial_id')} != {trial_id}")
    if record.get("final_verdict") != final_status or evaluation.get("final_verdict") != final_status:
        problems.append(f"final_verdict {record.get('final_verdict')}/{evaluation.get('final_verdict')} != {final_status}")
    if evaluation.get("status") in (None, "RUNNING") or evaluation.get("attempt") != attempt_number:
        problems.append(f"evaluation status={evaluation.get('status')} attempt={evaluation.get('attempt')}")
    if len(attempts) != attempt_number or last.get("attempt") != attempt_number or last.get("final_status") != final_status:
        problems.append(f"attempts={len(attempts)} ultimo={last.get('attempt')}/{last.get('final_status')}")
    return problems


def _persist_cleanup_outcome(trial_dir: Path, attempt_number: int, cleanup: dict[str, Any]) -> None:
    """Solo actualiza workspace_cleanup / tia_workspace_cleaned del intento: nunca el veredicto."""
    record = trial_model.load_trial(Path(trial_dir))
    attempts = (record.get("evaluation") or {}).get("attempts") or []
    target = next((a for a in reversed(attempts) if isinstance(a, dict) and a.get("attempt") == attempt_number), None)
    if target is None:
        return
    target["workspace_cleanup"] = cleanup
    target["tia_workspace_cleaned"] = cleanup.get("status") == TW.CLEANUP_CLEANED
    trial_model.save_trial(Path(trial_dir), record)


def _record_memory_abort(project_root: Path, trial_dir: Path, record: dict[str, Any], attempts: list[dict[str, Any]],
                         attempt_number: int, attempt_dir: Path, retry_reason: str | None, memory: dict[str, Any],
                         log: Callable[[str], None]) -> dict[str, Any]:
    """Intento registrado como INFRASTRUCTURE_ERROR (INSUFFICIENT_MEMORY_FOR_TIA): sin workspace ni TIA."""
    now = _now()
    summary = {
        "attempt": attempt_number, "attempt_dir": str(attempt_dir), "tia_workspace_id": None, "tia_workspace_path": None,
        "tia_workspace_cleaned": False, "started_at": now, "completed_at": now,
        "retry_reason": retry_reason if attempt_number > 1 else None, "final_status": trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR,
        "compile": None, "tia_archive": "NOT_CREATED", "evidence_copied_ok": False, "download_success": None, "cpu_run": None,
        "oracle_verdict": None, "master_intact": True, "tia_session_opened": False, "error_code": memory["error_code"],
        "memory": memory["metrics"], "errors": list(memory["errors"]),
    }
    record = trial_model.load_trial(trial_dir)
    record.update({"final_status": trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR, "completed_at": now, "errors": list(memory["errors"]),
                   "lifecycle_state": STATE_EVALUATED, "failure_stage": "memory_preflight"})
    record.update(ED.classify_trial(record))
    record["final_verdict"] = trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR
    record["evaluation"] = {**(record.get("evaluation") or {}), "status": EVALUATION_INFRASTRUCTURE, "attempt": attempt_number,
                            "started_at": now, "completed_at": now, "final_verdict": trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR,
                            "tia_workspace_id": None, "attempts": attempts + [summary]}
    trial_model.save_trial(trial_dir, record)
    log(f"[DEFERRED] {record['trial_id']}: {memory['error_code']} (TIA no se abrio)")
    return {"aborted": False, **summary, "failure_category": record.get("failure_category"),
            "evaluation_status": EVALUATION_INFRASTRUCTURE}


def _attempt_dir(trial_dir: Path, attempt: int) -> Path:
    return Path(trial_dir) / EVALUATION_DIRNAME / f"attempt_{attempt:03d}"


def archive_attempts_trace(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Traza de Project.Archive tal como la reporto el bridge (politica de reintento ante la carrera de TIA con
    IM/SearchIndex). Bridges anteriores (sin el campo) -> attempt_count None, nunca se inventan intentos.
    """
    attempts = [dict(item) for item in raw.get("archive_attempts") or [] if isinstance(item, dict)]
    count = raw.get("archive_attempt_count")
    return {
        "attempt_count": count if isinstance(count, int) else (len(attempts) or None),
        "max_attempts": raw.get("archive_max_attempts"),
        "settle_ms": raw.get("archive_settle_ms"),
        "retry_backoff_ms": raw.get("archive_retry_backoff_ms"),
        "recovered_after_retry": bool(raw.get("archive_recovered_after_retry")),
        "attempts": attempts,
    }


def evaluate_trial(
    project_root: Path,
    trial_dir: Path,
    retry_reason: str | None = None,
    bridge: Callable[..., dict[str, Any]] | None = None,
    runtime_status_fn: Callable[[Path], dict[str, Any]] | None = None,
    oracle_fn: Callable[..., dict[str, Any]] | None = None,
    log: Callable[[str], None] = print,
    memory_fn: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Evalua un ensayo GENERADO sin volver a interpretar/generar nada. TIA solo ve el workspace corto
    tiaw/<Tnnnn>; la evidencia (.zap18 verificado por hash) queda en la carpeta del ensayo.

    Orden: veredicto -> evidencias -> trial.json (atomico, verificado) -> registro del workspace ->
    limpieza. La limpieza es mantenimiento: si falla, el workspace queda KEPT y el veredicto no cambia.
    Una excepcion inesperada ANTES de persistir el veredicto deja diagnostico y se propaga (el ensayo
    sigue sin veredicto: nunca se inventa uno).
    """
    context: dict[str, Any] = {"phase": "precheck", "attempt": None, "trial_id": None, "workspace_id": None,
                               "verdict_persisted": False}
    try:
        return _evaluate_trial(project_root, trial_dir, retry_reason, bridge, runtime_status_fn, oracle_fn, log, memory_fn, context)
    except Exception as error:
        path = record_unexpected_error(Path(trial_dir), error, context["phase"], context["attempt"], context["trial_id"],
                                       annotate_trial=not context["verdict_persisted"])
        if context["workspace_id"] and not context["verdict_persisted"]:
            try:  # workspace conservado para diagnostico (nunca se limpia un ensayo sin veredicto)
                TW.update_entry(Path(project_root), context["workspace_id"], state=TW.STATE_KEPT,
                                keep_reason=f"UNEXPECTED_ERROR en {context['phase']}: {type(error).__name__}", diagnostic_path=path)
            except Exception:  # noqa: BLE001
                pass
        try:
            error.diagnostic_path = path  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        raise


def _evaluate_trial(
    project_root: Path,
    trial_dir: Path,
    retry_reason: str | None,
    bridge: Callable[..., dict[str, Any]] | None,
    runtime_status_fn: Callable[[Path], dict[str, Any]] | None,
    oracle_fn: Callable[..., dict[str, Any]] | None,
    log: Callable[[str], None],
    memory_fn: Callable[[], dict[str, Any]] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    import plcsim_runtime
    import tia_openness
    from trial_experiments import oracle_runner

    project_root = Path(project_root)
    trial_dir = Path(trial_dir)
    check = precheck(project_root, trial_dir, retry_reason)
    if not check["ok"]:
        if check.get("integrity_failed"):
            trial_model.update_trial(trial_dir, {
                "lifecycle_state": STATE_INTEGRITY_FAILED,
                "evaluation": {"status": EVALUATION_INTEGRITY_FAILED, "integrity_errors": check["errors"], "checked_at": _now()},
            })
        log("[DEFERRED] ABORT: " + " | ".join(check["errors"]))
        return {"aborted": True, "errors": check["errors"], "integrity_failed": check.get("integrity_failed"),
                "legacy": check.get("legacy"), "path_validation": check.get("path_validation")}

    record, manifest, master = check["record"], check["manifest"], check["master"]
    evaluation = record.get("evaluation") or {}
    attempts = list(evaluation.get("attempts") or [])
    attempt_number = len(attempts) + 1
    context.update({"phase": "attempt_setup", "attempt": attempt_number, "trial_id": record.get("trial_id")})
    attempt_dir = _attempt_dir(trial_dir, attempt_number)
    if attempt_dir.exists():
        raise RuntimeError(f"{attempt_dir} ya existe: un intento nunca se sobrescribe.")
    evidence_dir = attempt_dir / TIA_DIRNAME
    evidence_dir.mkdir(parents=True)
    master_archive = Path(master["snapshot"]["archive_path"])

    # Precheck de memoria ANTES de crear workspace o sesion Openness (OOM real dentro de TIA en T0001).
    memory = SR.memory_preflight(project_root, memory_fn)
    _write_json(attempt_dir / MEMORY_PREFLIGHT_REPORT, {**memory, "measured_at": _now()})
    if not memory["ok"]:
        return _record_memory_abort(project_root, trial_dir, record, attempts, attempt_number, attempt_dir, retry_reason, memory, log)

    # Workspace corto NUEVO (ID nunca reutilizado). Es lo unico que recibe TIA.
    context["phase"] = "workspace_allocation"
    workspace = TW.allocate(project_root, record["trial_id"], attempt_number, trial_dir)
    workspace_id, workspace_path = workspace["workspace_id"], Path(workspace["path"])
    context["workspace_id"] = workspace_id
    paths = TW.layout(workspace_path, workspace_id)
    path_validation = TW.validate_paths(workspace_path, workspace_id, master_internal_project_name(master), TIA_ARCHIVE_MAX_PATH)
    started_at, started = _now(), time.perf_counter()
    trial_model.update_trial(trial_dir, {"evaluation": {"status": "RUNNING", "attempt": attempt_number, "started_at": started_at,
                                                         "tia_workspace_id": workspace_id}})
    log(f"[DEFERRED] {record['trial_id']}: intento {attempt_number} en workspace {workspace_id}")

    tia_config = tia_openness.load_tia_config(project_root)
    runtime_config = plcsim_runtime.load_runtime_config(plcsim_runtime._load_tia_config(project_root))
    status_fn = runtime_status_fn or plcsim_runtime.get_plcsim_runtime_status
    errors: list[str] = list(path_validation["errors"])

    # Guards: la evaluacion solo parte del snapshot del MASTER (nunca de otro ensayo) y nunca escribe
    # dentro del proyecto Normal ni del MASTER.
    import tia_projects

    normal_path = tia_projects.normal_project_path(project_root)
    results_root = trial_model.get_results_experiments_dir(project_root).parent.resolve()
    if master_archive.resolve().is_relative_to(results_root):
        raise RuntimeError("TEMPLATE_GUARD: la plantilla de un ensayo nunca puede ser otro ensayo.")
    for protected in [Path(master["path"]).parent.resolve()] + ([Path(normal_path).parent.resolve()] if normal_path else []):
        if workspace_path.resolve().is_relative_to(protected) or evidence_dir.resolve().is_relative_to(protected):
            raise RuntimeError(f"PROJECT_GUARD: el ensayo no puede trabajar dentro de {protected}.")

    master_hash_before = sha256_file(master_archive)
    master_fingerprint_before = master_folder_fingerprint(master["path"])
    pre_runtime = status_fn(project_root)
    plcsim_errors = check_plcsim(pre_runtime, runtime_config["instance_name"])
    if plcsim_errors:
        errors.extend(plcsim_errors)
        log("[DEFERRED] PLCSIM no listo: se compila y archiva, pero no se descarga.")

    # Fuente que importa TIA: copia del program.scl congelado dentro del workspace, verificada por hash.
    shutil.copyfile(TW.fs_path(trial_dir / PROGRAM_FILENAME), TW.fs_path(paths["source_path"]))
    source_ok = sha256_file(paths["source_path"]) == manifest["files"][PROGRAM_FILENAME]
    if not source_ok:
        errors.append(f"{ERROR_INTEGRITY}: la copia de program.scl en el workspace no coincide con el hash congelado.")

    program_text = (trial_dir / PROGRAM_FILENAME).read_text(encoding="utf-8")
    declared = declared_blocks(program_text)
    delete_blocks = sorted(set(master_app_managed_blocks(master)) - set(declared))
    target = tia_openness.resolve_download_target(tia_config, tia_openness.DOWNLOAD_PURPOSE_EXPERIMENT)
    evidence_archive = evidence_dir / f"{record['trial_id']}{ZAP_EXTENSION}"
    copy_state: dict[str, Any] = {}

    def _on_archived(info: dict[str, Any]) -> dict[str, Any]:
        """Bridge archivo el proyecto: copiar + verificar la evidencia ANTES de permitir la descarga."""
        if Path(str(info.get("archive_path") or "")).resolve() != paths["archive_path"].resolve():
            copy_state.update({"copied_ok": False, "error": f"{TW.ERROR_ARCHIVE_INTEGRITY_FAILED}: TIA archivo en {info.get('archive_path')}."})
        else:
            copy_state.update(TW.copy_archive_to_evidence(paths["archive_path"], evidence_archive, info.get("archive_sha256")))
        allowed = bool(copy_state.get("copied_ok")) and not plcsim_errors
        return {"download": allowed, "reason": "EVIDENCE_VERIFIED" if allowed else (copy_state.get("error") or "PLCSIM_NOT_READY")}

    request = {
        "action": "evaluate_trial",
        "master_archive_path": str(master_archive.resolve()),
        "working_dir": str(paths["retrieve_dir"].resolve()),
        "trial_archive_dir": str(paths["archive_dir"].resolve()),
        "trial_archive_name": str(paths["archive_name"]),
        "source_path": str(paths["source_path"].resolve()),
        "source_name": SOURCE_NAME_IN_TIA,
        "handshake_dir": str(workspace_path.resolve()),
        "expected_project_name": master_internal_project_name(master),
        "checkpoint_path": str((workspace_path / TW.CHECKPOINTS_FILENAME).resolve()),
        "handshake_timeout_seconds": int(tia_config.get("deferred_handshake_timeout_seconds", 600)),
        "plc_name": str(tia_config.get("plc_name", "")),
        "with_user_interface": bool(tia_config.get("deferred_with_user_interface", False)),
        "tags": trial_tag_payload(_read_json(trial_dir / VARIABLES_FILENAME), _read_json(trial_dir / SNAPSHOT_FILENAME)),
        "delete_blocks": delete_blocks,
        "download_after_archive": not plcsim_errors,
        "purpose": tia_openness.DOWNLOAD_PURPOSE_EXPERIMENT,
        "require_simulation": True,
        "target_type": target["target_type"],
        "target_name": str(target.get("target_name", "")),
        "configuration_mode": str(target.get("configuration_mode", "")),
        "pc_interface": str(target.get("pc_interface", "")),
        "target_interface": str(target.get("target_interface", "")),
        "download_scope": target["download_scope"],
        "start_modules": target["start_modules"],
        "physical_download_allowed": False,
    }
    tia_ms = 0
    context["phase"] = "tia_bridge"
    if path_validation["ok"] and source_ok:
        tia_started = time.perf_counter()
        raw = (bridge or run_bridge)(request, workspace_path, project_root=project_root, on_archived=_on_archived)
        tia_ms = int(round((time.perf_counter() - tia_started) * 1000))
    else:
        raw = {"status": "TIA_NOT_CALLED", "errors": list(errors)}
    download_raw = raw.pop("download", None)
    context["phase"] = "tia_evidence"
    # Checkpoints persistentes del bridge: se copian a la evidencia aunque TIA se haya caido.
    checkpoints_source = workspace_path / TW.CHECKPOINTS_FILENAME
    checkpoints = TW.parse_checkpoints(checkpoints_source)
    if checkpoints_source.is_file():
        shutil.copyfile(TW.fs_path(checkpoints_source), TW.fs_path(attempt_dir / TW.CHECKPOINTS_FILENAME))
    raw["checkpoints"] = {key: checkpoints[key] for key in ("last_completed", "first_failed", "first_failed_detail", "unfinished")}
    archive_trace = archive_attempts_trace(raw)
    _write_json(attempt_dir / COMPILE_REPORT, {**raw, "archive": archive_trace, "duration_ms": tia_ms})

    compile_class = TC.classify_tia_compile(raw)
    if raw.get("status") == "TIA_NOT_CALLED":
        compile_class = {"category": TC.INFRASTRUCTURE_ERROR, "reason": "; ".join(errors) or "TIA no invocado", "tia_operational": None}
    compile_infra = compile_class["category"] == TC.INFRASTRUCTURE_ERROR
    compile_ok = compile_class["category"] == TC.COMPILE_PASSED
    imported_hash = raw.get("imported_source_sha256")
    if imported_hash and imported_hash != manifest["files"][PROGRAM_FILENAME]:
        errors.append(f"{ERROR_INTEGRITY}: TIA importo un program.scl distinto del congelado.")
        compile_ok = False

    # .zap18: si el handshake no lo copio (p.ej. no compilo), se copia y verifica ahora.
    archive_created = raw.get("archive_status") == "CREATED" and Path(str(raw.get("archive_path") or "")).resolve() == paths["archive_path"].resolve()
    if archive_created and not copy_state:
        copy_state.update(TW.copy_archive_to_evidence(paths["archive_path"], evidence_archive, raw.get("archive_sha256")))
    evidence_ok = bool(copy_state.get("copied_ok"))
    if copy_state.get("error"):
        errors.append(copy_state["error"])
    archive_status = "CREATED" if (archive_created and evidence_ok) else "NOT_CREATED"
    archive_reason = None if archive_status == "CREATED" else (
        copy_state.get("error") or raw.get("archive_error") or ("INFRASTRUCTURE_ERROR" if compile_infra else "ARCHIVE_NOT_AVAILABLE"))

    context["phase"] = "download_runtime"
    download_report = None
    download_ok = None
    if download_raw is not None:
        started_dl = datetime.now()
        download_report = tia_openness._finalize_download_report(download_raw, target, tia_openness.DOWNLOAD_PURPOSE_EXPERIMENT, started_dl, time.perf_counter())
        _write_json(attempt_dir / DOWNLOAD_REPORT, download_report)
        download_ok = bool(download_report.get("download_success"))
    elif compile_ok and not plcsim_errors and archive_status == "CREATED":
        download_ok = False  # archivo y evidencia OK pero no hubo descarga (handshake o caida del bridge)
    # Sin .zap18 verificado el bridge nunca llama a Download: download_ok queda None (NOT_RUN), nunca False.

    runtime_report = None
    cpu_run = None
    oracle_result = None
    if download_ok and evidence_ok:
        runtime_report = status_fn(project_root)
        _write_json(attempt_dir / RUNTIME_REPORT, runtime_report)
        cpu_run = bool(runtime_report.get("connected")) and runtime_report.get("cpu_state") == plcsim_runtime.CPU_STATE_RUN
        if cpu_run:
            context["phase"] = "oracle"
            oracle = S.load_oracle(project_root, manifest["case_id"])
            run = oracle_fn or oracle_runner.run_oracle
            oracle_result = run(oracle, trial_dir / SNAPSHOT_FILENAME, runtime_report, "PLCSIM_ADVANCED",
                                _read_json(trial_dir / SEMANTIC_FILENAME), project_root)

    # Veredicto (misma precedencia que el pipeline inmediato).
    context["phase"] = "verdict"
    source_mismatch = any(ERROR_INTEGRITY in error for error in errors)
    evidence_failed = archive_created and not evidence_ok
    if compile_infra or source_mismatch or evidence_failed:
        # Caida de TIA, fuente distinta o evidencia .zap18 no verificada: nunca es un fallo del sistema evaluado.
        final_status = trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR
    elif compile_class["category"] == TC.COMPILE_FAILURE:
        final_status = trial_model.FINAL_STATUS_FAIL
    elif plcsim_errors or not download_ok or not cpu_run:
        final_status = trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR
    else:
        final_status = oracle_runner.decide_final_status(True, True, True, (oracle_result or {}).get("verdict"))

    master_hash_after = sha256_file(master_archive) if master_archive.exists() else None
    master_fingerprint_after = master_folder_fingerprint(master["path"])
    master_intact = master_hash_after == master_hash_before == master["snapshot"]["archive_sha256"] and master_fingerprint_after == master_fingerprint_before
    if not master_intact:
        errors.append(f"{ERROR_MASTER_INTEGRITY}: el MASTER o su snapshot cambiaron durante la evaluacion.")

    context["phase"] = "evidence_manifest"
    tia_manifest = {
        "trial_id": record["trial_id"],
        "attempt_number": attempt_number,
        "tia_workspace_id": workspace_id,
        "master_snapshot_path": str(master_archive),
        "master_snapshot_hash": master_hash_before,
        "workspace": {"path": str(workspace_path), "retrieved_project": raw.get("working_project_path"),
                      "retrieve_dir": str(paths["retrieve_dir"]), "created_at": workspace["created_at"]},
        "path_validation": {key: path_validation[key] for key in (
            "retrieve_path_length", "retrieve_path_length_without_subfolder", "archive_path_length", "source_path_length",
            "max_path_length", "limit", "checks")},
        "generated_scl_hash": manifest["files"][PROGRAM_FILENAME],
        "imported_scl_hash": imported_hash,
        "variables_hash": manifest["files"][VARIABLES_FILENAME],
        "io_snapshot_hash": manifest["files"][SNAPSHOT_FILENAME],
        "compile_status": raw.get("status"),
        "compile_classification": compile_class,
        "archive": {"workspace_path": str(paths["archive_path"]), "workspace_hash": copy_state.get("workspace_hash"),
                    "evidence_path": str(evidence_archive), "evidence_hash": copy_state.get("evidence_hash"),
                    "copied_ok": evidence_ok, "error": copy_state.get("error") or (None if archive_created else archive_reason),
                    **archive_trace},
        "handshake": raw.get("handshake"),
        "checkpoints": raw.get("checkpoints"),
        "master": {"path": master.get("path"), "master_hash_after": master_hash_after,
                   "master_folder_fingerprint": master_fingerprint_before, "master_folder_fingerprint_after": master_fingerprint_after,
                   "validation_status": (master.get("validation") or {}).get("master_status")},
        "tia": {"version": raw.get("tia_version"), "copy_identity": raw.get("copy_identity"),
                "source": "metadata congelada de VALIDAR MASTER (la evaluacion no describe la copia)",
                "cpu": (master.get("validation") or {}).get("cpu_type_identifier"),
                "cpu_type_name": (master.get("validation") or {}).get("cpu_type_name"),
                "x1_ip_address": (master.get("validation") or {}).get("x1_ip_address")},
        "memory_preflight": memory,
        "managed_blocks": {"declared_in_program": declared, "removed_from_copy": raw.get("removed_managed_blocks"),
                           "unmanaged_blocks_in_copy": [b["name"] for b in raw.get("blocks_after_compile") or []
                                                        if b.get("name") not in APP_MANAGED_BLOCK_NAMES and b.get("name") not in declared]},
    }
    _write_json(evidence_dir / TIA_PROJECT_MANIFEST, tia_manifest)

    context["phase"] = "oracle_artifacts"
    if oracle_result is not None:
        record_now = trial_model.load_trial(trial_dir)
        report = oracle_runner.build_evaluation_report(record_now, oracle_result, final_status)
        oracle_runner.write_oracle_artifacts(attempt_dir, oracle_result, report)

    # Decision de limpieza (se EJECUTA solo despues de persistir y verificar el veredicto): solo con evidencia
    # copiada y verificada, manifiesto escrito, sesion TIA cerrada (el bridge termino) y estado final.
    # Con INFRASTRUCTURE_ERROR o sin evidencia se conserva el workspace para diagnostico.
    keep_all = bool(tia_config.get("deferred_keep_workspaces", False))
    infra = final_status == trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR
    cleanup_planned = evidence_ok and not infra and not keep_all
    keep_reason = None
    if not evidence_ok:
        keep_reason = "evidencia .zap18 no copiada/verificada"
    elif infra:
        keep_reason = "INFRASTRUCTURE_ERROR: workspace conservado para diagnostico"
    workspace_cleanup: dict[str, Any] = {
        "status": TW.CLEANUP_PENDING if cleanup_planned else TW.CLEANUP_SKIPPED,
        "workspace_id": workspace_id, "workspace_path": str(workspace_path), "timestamp": None,
        "reason": None if cleanup_planned else (keep_reason or "deferred_keep_workspaces"),
        "error_code": None, "error_type": None, "error_message": None,
    }

    completed_at = _now()
    attempt_summary = {
        "attempt": attempt_number,
        "attempt_dir": str(attempt_dir),
        "tia_workspace_id": workspace_id,
        "tia_workspace_path": str(workspace_path),
        "tia_workspace_cleaned": False,
        "started_at": started_at,
        "completed_at": completed_at,
        "retry_reason": retry_reason if attempt_number > 1 else None,
        "final_status": final_status,
        "compile": compile_class["category"],
        "tia_archive": archive_status,
        "archive_attempt_count": archive_trace["attempt_count"],
        "archive_recovered_after_retry": archive_trace["recovered_after_retry"],
        "evidence_copied_ok": evidence_ok,
        "download_success": download_ok,
        "cpu_run": cpu_run,
        "oracle_verdict": (oracle_result or {}).get("verdict"),
        "master_intact": master_intact,
        "max_tia_path_length": path_validation["max_path_length"],
        "memory": memory["metrics"],
        "tia_last_completed_checkpoint": checkpoints["last_completed"],
        "tia_first_failed_checkpoint": checkpoints["first_failed"],
        "errors": errors + list(raw.get("errors") or [])[:5],
        "workspace_cleanup": workspace_cleanup,
    }
    stages = {
        "compile_success": None if compile_infra else bool(compile_ok),
        "download_success": download_ok,
        "start_module_success": (download_report or {}).get("start_module_success"),
        "runtime_connection_success": None if runtime_report is None else bool(runtime_report.get("connected")),
    }
    patch: dict[str, Any] = {
        "compile": {"status": raw.get("status"), "error_count": raw.get("error_count"), "warning_count": raw.get("warning_count"),
                    "classification": compile_class, "result_path": str(attempt_dir / COMPILE_REPORT)},
        "download": {"status": (download_report or {}).get("status"), "target_type": target["target_type"],
                     "start_module_success": (download_report or {}).get("start_module_success"), "cpu_run_confirmed": cpu_run},
        "stages": stages,
        "timing": {"compile_ms": tia_ms, "runtime_ms": (runtime_report or {}).get("duration_ms"),
                   "oracle_ms": (oracle_result or {}).get("duration_ms"), "evaluation_ms": int(round((time.perf_counter() - started) * 1000))},
        "tia_archive": {"status": archive_status, "reason": archive_reason, "zap18_path": str(evidence_archive) if evidence_ok else None,
                        "zap18_hash": copy_state.get("evidence_hash") if evidence_ok else None, "tia_workspace_id": workspace_id,
                        "attempt_count": archive_trace["attempt_count"],
                        "recovered_after_retry": archive_trace["recovered_after_retry"]},
        "lifecycle_state": STATE_EVALUATED,
    }
    if runtime_report is not None:
        patch["runtime"] = plcsim_runtime.trial_runtime_section(runtime_report)
    if oracle_result is not None:
        # Fusion POR SECCION (como trial_model.update_trial): un patch.update() plano reemplazaba
        # "stages"/"timing" enteros y perdia compile_success, download_success, compile_ms...
        oracle_patch = oracle_runner.trial_patch(oracle_result, {"evaluation_report": str(attempt_dir / oracle_runner.EVALUATION_REPORT_FILENAME)})
        for key, value in oracle_patch.items():
            patch[key] = {**patch[key], **value} if isinstance(value, dict) and isinstance(patch.get(key), dict) else value

    # 1) RESULTADO DEFINITIVO: patch + veredicto + intentos + timing en UNA escritura atomica de trial.json.
    context["phase"] = "persist_result"
    record = trial_model.merge_patch(trial_model.load_trial(trial_dir), patch)
    record["final_status"] = final_status
    record["completed_at"] = completed_at
    record["errors"] = list(attempt_summary["errors"])
    timing = record.setdefault("timing", {})
    if timing.get("generation_total_ms") is not None and timing.get("evaluation_ms") is not None:
        timing["total_ms"] = timing["generation_total_ms"] + timing["evaluation_ms"]
        timing["end_to_end_ms"] = timing["total_ms"]
    classification = ED.classify_trial(record)
    status = EVALUATION_INFRASTRUCTURE if classification["infrastructure_error"] else EVALUATION_COMPLETED
    if not master_intact:
        status = ERROR_MASTER_INTEGRITY
    record.update(classification)
    record["final_verdict"] = final_status
    record["evaluation"] = {**(record.get("evaluation") or {}), "status": status, "attempt": attempt_number,
                            "started_at": started_at, "completed_at": completed_at, "final_verdict": final_status,
                            "tia_workspace_id": workspace_id, "attempts": attempts + [attempt_summary]}
    trial_model.save_trial(trial_dir, record)

    # 2) Verificacion: sin un trial.json coherente no se hace ningun mantenimiento (el workspace se conserva).
    context["phase"] = "verify_persistence"
    problems = _verify_persisted(trial_dir, record["trial_id"], attempt_number, final_status)
    if problems:
        raise RuntimeError(f"{ERROR_PERSISTENCE_VERIFICATION}: " + "; ".join(problems))
    context["verdict_persisted"] = True
    log(f"[DEFERRED] {record['trial_id']}: {final_status} ({classification['failure_category']}) workspace {workspace_id}")

    # 3) Mantenimiento (nunca lanza ni altera el veredicto): registro del workspace y limpieza.
    context["phase"] = "workspace_registry"
    try:
        TW.update_entry(project_root, workspace_id, state=TW.STATE_KEPT if keep_reason else TW.STATE_EVIDENCE_COPIED,
                        evidence_copied_ok=evidence_ok, final_status=final_status, evidence_path=str(evidence_archive),
                        **({"keep_reason": keep_reason} if keep_reason else {}))
    except Exception as error:  # noqa: BLE001 - sin registro coherente no se borra nada
        workspace_cleanup = {**workspace_cleanup, "error_code": "WORKSPACE_REGISTRY_UPDATE_FAILED", "error_type": type(error).__name__,
                             "error_message": str(error), "timestamp": _now()}
        if cleanup_planned:
            cleanup_planned = False
            workspace_cleanup["status"] = TW.CLEANUP_FAILED
    if cleanup_planned:
        context["phase"] = "workspace_cleanup"
        protected = [Path(master["path"]).parent, master_archive.parent, Path(trial_dir)]
        if normal_path:
            protected.append(Path(normal_path).parent)
        try:
            outcome = TW.remove_workspace_safe(project_root, workspace_id, expected_trial_id=record["trial_id"],
                                               expected_attempt=attempt_number, protected=protected)
        except Exception as error:  # noqa: BLE001 - remove_workspace_safe no deberia lanzar; si lo hace, se conserva
            outcome = TW._failure(workspace_id, workspace_path, TW.ERROR_WORKSPACE_REMOVE_FAILED, error)
            TW._record_outcome(project_root, workspace_id, outcome)
        workspace_cleanup = {**workspace_cleanup, **{key: value for key, value in outcome.items() if key != "traceback"}}
        try:
            _write_json(attempt_dir / CLEANUP_REPORT, {"trial_id": record["trial_id"], "attempt": attempt_number,
                                                       "final_verdict": final_status, **outcome})
        except Exception:  # noqa: BLE001
            pass
        if outcome["status"] != TW.CLEANUP_CLEANED:
            log(f"[DEFERRED] {record['trial_id']}: limpieza del workspace {workspace_id} {outcome['status']} "
                f"({outcome.get('error_type')}: {outcome.get('error_message')}); workspace conservado (KEPT). Veredicto {final_status} intacto.")
    if workspace_cleanup["status"] != TW.CLEANUP_SKIPPED or workspace_cleanup.get("error_code"):
        context["phase"] = "cleanup_record"
        try:
            _persist_cleanup_outcome(trial_dir, attempt_number, workspace_cleanup)
        except Exception as error:  # noqa: BLE001
            record_unexpected_error(trial_dir, error, "cleanup_record", attempt_number, record["trial_id"], annotate_trial=False)
    attempt_summary.update({"workspace_cleanup": workspace_cleanup,
                            "tia_workspace_cleaned": workspace_cleanup.get("status") == TW.CLEANUP_CLEANED})
    return {"aborted": False, **attempt_summary, "failure_category": classification["failure_category"], "evaluation_status": status}


# ---------------------------------------------------------------------------------------------
# Presentacion (GUI): resumen previo y tabla de veredicto
# ---------------------------------------------------------------------------------------------

def _pass_fail(value: Any) -> str:
    return "PASS" if value is True else ("FAIL" if value is False else "-")


# "semantic" = semantic_pipeline_success (interpretacion valida que permitio continuar);
# "semantic_benchmark" = semantic_benchmark_match (coincide con la expectativa del Oracle). Son
# dimensiones distintas de "functional" (comportamiento medido en PLCSIM): ninguna oculta a otra.
STAGE_KEYS = ("semantic", "semantic_benchmark", "io_allocation", "ir", "compilation", "tia_archive", "download", "runtime",
              "functional", "safety", "final_verdict")
STAGE_LABELS = {"semantic": "Semantic", "semantic_benchmark": "Semantic Benchmark", "io_allocation": "I/O Allocation", "ir": "IR", "compilation": "Compilation",
                "tia_archive": "TIA Archive", "download": "Download", "runtime": "Runtime", "functional": "Functional",
                "safety": "Safety", "final_verdict": "FINAL"}
STATUS_PENDING_LABEL = "PENDIENTE DE EVALUACION"
STAGE_NOT_RUN = "NOT_RUN"  # etapa no ejecutada en una evaluacion terminada (distinto de FAIL y de "-" pendiente)


def _last_attempt(record: dict[str, Any]) -> dict[str, Any]:
    attempts = (record.get("evaluation") or {}).get("attempts") or []
    return attempts[-1] if attempts and isinstance(attempts[-1], dict) else {}


def _compilation_value(record: dict[str, Any]) -> str:
    """
    Evidencia REAL de compilacion: stages.compile_success; si no esta (ensayos evaluados antes de la
    correccion de la fusion de stages), la clasificacion persistida del reporte de compilacion de TIA
    (compile.classification / ultimo intento). Nunca se deduce de Archive ni de Runtime.
    """
    value = (record.get("stages") or {}).get("compile_success")
    if value is not None:
        return _pass_fail(value)
    attempt = _last_attempt(record)
    category = ((record.get("compile") or {}).get("classification") or {}).get("category") or attempt.get("compile")
    if category == TC.INFRASTRUCTURE_ERROR:
        return "INFRA"
    if category == TC.COMPILE_FAILURE:
        return "FAIL"
    if category == TC.COMPILE_PASSED:
        # Igual que la evaluacion: si TIA importo un program.scl distinto del congelado, no cuenta como PASS.
        source_mismatch = any(ERROR_INTEGRITY in str(error) for error in (attempt.get("errors") or record.get("errors") or []))
        return "FAIL" if source_mismatch else "PASS"
    return "-"


def _download_value(record: dict[str, Any]) -> str:
    """Evidencia REAL de descarga: stages.download_success o el download_success del bridge en el ultimo intento."""
    value = (record.get("stages") or {}).get("download_success")
    if value is None:
        value = _last_attempt(record).get("download_success")
    return _pass_fail(value if isinstance(value, bool) else None)


def _final_verdict(record: dict[str, Any]) -> str | None:
    final = (record.get("evaluation") or {}).get("final_verdict") or record.get("final_verdict") or record.get("final_status")
    return None if final in (None, "", trial_model.FINAL_STATUS_PREPARED) else str(final)


def trial_status_label(record: dict[str, Any]) -> str:
    """Estado del ensayo para encabezados y listas, siempre desde lo persistido (nunca un estado visual previo)."""
    evaluation = record.get("evaluation") or {}
    status = evaluation.get("status")
    if status in (ERROR_MASTER_INTEGRITY, EVALUATION_INTEGRITY_FAILED):
        return str(status)
    final = _final_verdict(record)
    if final == trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR:
        return trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR
    if final:
        return f"{final} / COMPLETADO"
    if status == EVALUATION_PENDING:
        return STATUS_PENDING_LABEL
    return str(status or "LEGACY")


def trial_stage_summary(record: dict[str, Any]) -> dict[str, Any]:
    """
    FUENTE UNICA del estado de un ensayo (detalle, encabezado, lista principal y futuro lote): lee solo el
    registro persistido (trial.json). Claves: semantic, io_allocation, ir, compilation, tia_archive,
    download, runtime, functional, safety, final_verdict ("PASS"/"FAIL"/"INFRA"/"REVIEW"/"-"/...),
    mas status (encabezado) y voice (filas de voz o []).
    """
    stages = record.get("stages") or {}
    oracle = record.get("oracle") or {}
    io_failed = record.get("failure_stage") == "io_allocation" or bool((record.get("io_map") or {}).get("error"))
    ir_failed = record.get("failure_stage") in ("resource_binding", "generate")
    functional = stages.get("functional_success")
    voice_rows: list[tuple[str, str]] = []
    if str(record.get("input_mode", "")).startswith("VOICE"):
        voice = record.get("voice") or {}
        wer = voice.get("wer")
        voice_rows = [("Voice Capture", _pass_fail(voice.get("audio_capture_success"))),
                      ("ASR", _pass_fail(voice.get("asr_success"))),
                      ("WER", "-" if wer is None else f"{wer:.3f}")]
    # Etapas posteriores a Archive: con una evaluacion TIA terminada, la COLA de etapas sin evidencia (ninguna
    # posterior se ejecuto) es NOT_RUN (p.ej. Archive FAIL -> Download NOT_RUN), nunca FAIL. Un hueco entre etapas
    # ejecutadas sigue "-" (desconocido, nunca se deduce); sin evaluacion todo sigue "-" (pendiente).
    evaluated = bool((record.get("evaluation") or {}).get("attempts")) and _final_verdict(record) is not None
    archive_not_created = (record.get("tia_archive") or {}).get("status") == "NOT_CREATED"
    tail = {
        # El bridge solo descarga con .zap18 CREATED: Archive NOT_CREATED sin reporte de descarga es NOT_RUN
        # (tambien en ensayos antiguos que persistieron download_success=False por omision).
        "download": "-" if evaluated and archive_not_created and not (record.get("download") or {}).get("status")
        else _download_value(record),
        "runtime": _pass_fail((record.get("download") or {}).get("cpu_run_confirmed")),
        "functional": "REVIEW" if oracle.get("verdict") == "REVIEW" and functional is None else _pass_fail(functional),
        "safety": _pass_fail(stages.get("safety_success")),
    }
    if evaluated:
        for key in reversed(tuple(tail)):
            if tail[key] != "-":
                break
            tail[key] = STAGE_NOT_RUN

    return {
        "semantic": _pass_fail(stages.get("semantic_success")),
        # Solo lo persistido por el Oracle: ensayos anteriores (sin el campo) muestran "-", nunca se recalcula.
        "semantic_benchmark": _pass_fail(stages.get("semantic_benchmark_match")),
        "io_allocation": "FAIL" if io_failed else ("PASS" if (record.get("io_map") or {}).get("frozen") else "-"),
        "ir": "FAIL" if ir_failed else _pass_fail(stages.get("verification_success")),
        "compilation": _compilation_value(record),
        "tia_archive": {"CREATED": "PASS", "NOT_CREATED": "FAIL"}.get((record.get("tia_archive") or {}).get("status"), "-"),
        **tail,
        "archive_attempt_count": (record.get("tia_archive") or {}).get("attempt_count"),
        "archive_recovered_after_retry": (record.get("tia_archive") or {}).get("recovered_after_retry"),
        "final_verdict": str((record.get("evaluation") or {}).get("final_verdict") or record.get("final_status") or "PENDIENTE"),
        "status": trial_status_label(record),
        "voice": voice_rows,
        # Auxiliares para la linea de progreso de la GUI (evidencia propia, no deducida de otras etapas).
        "cpu_start": _pass_fail(stages.get("start_module_success") if stages.get("start_module_success") is not None
                                else (record.get("download") or {}).get("start_module_success")),
        "oracle": str(oracle.get("verdict") or "-"),
        "infrastructure_status": infrastructure_status(record),
    }


def infrastructure_status(record: dict[str, Any]) -> str:
    """INFRASTRUCTURE_ERROR / OK (evaluacion terminada sin fallo de infraestructura) / '-' (sin evaluar)."""
    final = _final_verdict(record)
    if final == trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR or record.get("infrastructure_error") is True:
        return trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR
    return "OK" if final else "-"


def verdict_table(record: dict[str, Any]) -> list[tuple[str, str]]:
    summary = trial_stage_summary(record)
    return list(summary["voice"]) + [(STAGE_LABELS[key], summary[key]) for key in STAGE_KEYS]


def evaluation_summary_lines(project_root: Path, trial_dir: Path) -> list[str]:
    record = trial_model.load_trial(Path(trial_dir))
    integrity = verify_trial_integrity(Path(trial_dir))
    manifest = integrity.get("manifest") or {}
    master = load_master_config(project_root)
    validation = master.get("validation") or {}
    oracle = manifest.get("oracle") or {}
    command = (Path(trial_dir) / COMMAND_FILENAME).read_text(encoding="utf-8").strip() if (Path(trial_dir) / COMMAND_FILENAME).exists() else ""
    return [
        f"Trial: {record.get('trial_id')}",
        f"Caso: {record.get('case_id')}",
        f"Variante: {record.get('variant_id')}",
        f"Modalidad: {record.get('input_mode')}",
        f"Comando: {command}",
        f"Benchmark: v{manifest.get('benchmark_version', record.get('benchmark_version'))}",
        f"Oracle: {oracle.get('oracle_id')} v{oracle.get('oracle_version')} · {oracle.get('oracle_status')}",
        f"MASTER: {master.get('path') or '(no configurado)'} · {validation.get('master_status') or 'SIN VALIDAR'}",
        f"Integrity: {'OK' if integrity['ok'] else ' | '.join(integrity['errors'])}",
        f"Estado: {trial_status_label(record)}",
    ]


# ---------------------------------------------------------------------------------------------
# Listado / siguiente pendiente / consolidacion
# ---------------------------------------------------------------------------------------------

def list_trials(project_root: Path, phases: tuple[str, ...] = (trial_model.PHASE_BASELINE, trial_model.PHASE_DEVELOPMENT)) -> list[dict[str, Any]]:
    rows = []
    for phase in phases:
        base = trial_model.get_phase_results_dir(project_root, phase)
        if not base.exists():
            continue
        for path in sorted(base.glob("*/*/*/trial.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            generation = record.get("generation") or {}
            evaluation = record.get("evaluation") or {}
            rows.append({
                "trial_id": record.get("trial_id"),
                "trial_dir": str(path.parent),
                "case_id": record.get("case_id"),
                "variant_id": record.get("variant_id"),
                "input_mode": record.get("input_mode"),
                "phase": record.get("experiment_phase"),
                "created_at": record.get("created_at"),
                "generation": generation.get("status") or "LEGACY",
                "evaluation": evaluation.get("status") or ("LEGACY" if not generation else None),
                "verdict": evaluation.get("final_verdict") or record.get("final_status"),
                "deferred": (path.parent / MANIFEST_FILENAME).exists(),
                # Misma fuente que el detalle (verdict_table) y que el futuro lote.
                "summary": trial_stage_summary(record),
            })
    return rows


def next_pending(project_root: Path) -> dict[str, Any] | None:
    """Siguiente ensayo GENERADO pendiente. Solo lo localiza: nunca inicia su evaluacion."""
    pending = [row for row in list_trials(project_root) if row["evaluation"] == EVALUATION_PENDING and row["deferred"]]
    return sorted(pending, key=lambda row: (row["created_at"] or "", row["trial_id"]))[0] if pending else None


def consolidate(project_root: Path, phase: str = trial_model.PHASE_BASELINE, out_dir: Path | None = None) -> dict[str, str]:
    """baseline_trials.csv / summary .json/.md / failures.json desde trial.json (sin estadistica formal)."""
    import csv

    from trial_experiments import batch_runner as B

    out_dir = Path(out_dir or trial_model.get_phase_results_dir(project_root, phase))
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = BC.cases_by_id(project_root)
    rows, queue_entries = [], []
    for item in list_trials(project_root, (phase,)):
        record = trial_model.load_trial(Path(item["trial_dir"]))
        if not record.get("final_status") or record.get("case_id") not in cases:
            continue
        attempt = {"attempt": (record.get("evaluation") or {}).get("attempt") or record.get("attempt"),
                   "retry_reason": record.get("retry_reason"), "trial_dir": item["trial_dir"], "trial_id": record.get("trial_id")}
        rows.append(B._trial_row(record, attempt, cases[record["case_id"]]))
        queue_entries.append({"case_id": record["case_id"], "variant": record.get("variant_id"), "status": "COMPLETED"})
    with (out_dir / B.TRIALS_CSV).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=B.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = B.build_summary(project_root, {"baseline_id": f"DEFERRED_{phase}", "entries": queue_entries}, rows)
    _write_json(out_dir / B.SUMMARY_JSON, summary)
    (out_dir / B.SUMMARY_MD).write_text(B.build_summary_markdown(summary), encoding="utf-8")
    _write_json(out_dir / B.FAILURES_JSON, [row for row in rows if row["final_status"] != "PASS"])
    return {"csv": str(out_dir / B.TRIALS_CSV), "summary_json": str(out_dir / B.SUMMARY_JSON),
            "summary_md": str(out_dir / B.SUMMARY_MD), "failures": str(out_dir / B.FAILURES_JSON), "rows": str(len(rows))}


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluacion diferida de ensayos generados")
    parser.add_argument("trial_dir", nargs="?", help="Carpeta del ensayo generado.")
    parser.add_argument("--precheck", action="store_true", help="Solo verificar (no abre TIA).")
    parser.add_argument("--retry-reason", default=None, help="Reintento tecnico de un INFRASTRUCTURE_ERROR.")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--next", action="store_true", help="Muestra el siguiente pendiente (no lo evalua).")
    parser.add_argument("--validate-master", action="store_true")
    parser.add_argument("--consolidate", default=None, metavar="PHASE")
    parser.add_argument("--cleanup-workspaces", action="store_true", help="Borra workspaces tiaw/ con evidencia verificada.")
    parser.add_argument("--include-kept", action="store_true", help="Con --cleanup-workspaces: incluye los conservados (INFRA).")
    args = parser.parse_args(argv)

    from utils import get_project_root

    root = get_project_root()
    if args.list:
        for row in list_trials(root):
            print(f"{row['trial_id']:<28} {row['generation']:<8} {str(row['evaluation']):<22} {row['verdict']}")
        return 0
    if args.next:
        print(json.dumps(next_pending(root), indent=2, ensure_ascii=False))
        return 0
    if args.validate_master:
        config = validate_master(root)
        print(json.dumps({k: v for k, v in (config.get("validation") or {}).items() if k not in ("blocks", "interfaces")}, indent=2, ensure_ascii=False))
        return 0 if (config.get("validation") or {}).get("status") == "VALID" else 2
    if args.cleanup_workspaces:
        print(json.dumps(TW.cleanup_workspaces(root, include_kept=args.include_kept), indent=2, ensure_ascii=False))
        return 0
    if args.consolidate:
        print(json.dumps(consolidate(root, args.consolidate), indent=2, ensure_ascii=False))
        return 0
    if not args.trial_dir:
        parser.print_help()
        return 1
    if args.precheck:
        result = precheck(root, Path(args.trial_dir), args.retry_reason)
        print(json.dumps({"ok": result["ok"], "errors": result["errors"], "warnings": result["warnings"]}, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 2
    result = evaluate_trial(root, Path(args.trial_dir), args.retry_reason)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if not result.get("aborted") else 2


if __name__ == "__main__":
    sys.exit(main())
