"""
Diseno experimental formal v2 (fuente de verdad: data/experimental_design.json).

  - una sola arquitectura evaluada; parser_mode es metadata tecnica, nunca un factor;
  - factores: DOMAIN x COMPLEXITY x VARIANT x INPUT_MODE x CASE;
  - modalidades formales: TEXT, VOICE_CLEAN, VOICE_NOISE;
  - matriz formal: 32 casos x 3 variantes x 3 modalidades = 288 FORMAL_TRIALS;
  - baseline de desarrollo: D01-D20 x V1-V3 x TEXT = 60 DEVELOPMENT_TRIALS;
  - FORMAL_TRIAL solo con un software_freeze_manifest valido (hoy no existe: nada es formal).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from trial_experiments import benchmark_catalog as BC
from trial_experiments import oracle_schema as S

DESIGN_RELATIVE_PATH = Path("data") / "experimental_design.json"

TRIAL_KIND_DEVELOPMENT = "DEVELOPMENT_TRIAL"
TRIAL_KIND_FORMAL = "FORMAL_TRIAL"
PHASE_BASELINE = "BASELINE"
PHASE_DEVELOPMENT = "DEVELOPMENT_VALIDATION"
PHASE_FORMAL = "FORMAL"

DOMAIN_DISCRETE = "DISCRETE"
DOMAIN_PID = "PID_SUPERVISOR"

# Taxonomia de fallos (Parte J).
SUCCESS = "SUCCESS"
SEMANTIC_FAILURE = "SEMANTIC_FAILURE"
IO_ALLOCATION_FAILURE = "IO_ALLOCATION_FAILURE"
IR_FAILURE = "IR_FAILURE"
CODEGEN_FAILURE = "CODEGEN_FAILURE"
VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
COMPILE_FAILURE = "COMPILE_FAILURE"
DOWNLOAD_FAILURE = "DOWNLOAD_FAILURE"
RUNTIME_FAILURE = "RUNTIME_FAILURE"
FUNCTIONAL_FAILURE = "FUNCTIONAL_FAILURE"
SAFETY_FAILURE = "SAFETY_FAILURE"
INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
ASR_FAILURE = "ASR_FAILURE"
REVIEW = "REVIEW"
INFRASTRUCTURE_CATEGORIES = (DOWNLOAD_FAILURE, RUNTIME_FAILURE, INFRASTRUCTURE_ERROR)

ERROR_FORMAL_NOT_ALLOWED = "FORMAL_TRIAL_NOT_ALLOWED"


# ---------------------------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------------------------

def design_path(project_root: Path) -> Path:
    return project_root / DESIGN_RELATIVE_PATH


def load_design(project_root: Path) -> dict[str, Any]:
    return json.loads(design_path(project_root).read_text(encoding="utf-8"))


def formal_input_modes(project_root: Path) -> list[str]:
    return [mode["id"] for mode in load_design(project_root)["formal_input_modes"]]


def input_mode_spec(project_root: Path, mode_id: str) -> dict[str, Any]:
    for mode in load_design(project_root)["formal_input_modes"]:
        if mode["id"] == mode_id:
            return mode
    raise ValueError(f"Modalidad de entrada desconocida: {mode_id!r}")


def architecture_parser_mode(project_root: Path) -> str:
    return str(load_design(project_root)["architecture"]["parser_mode"])


def domain_for_case(case_id: str) -> str:
    return DOMAIN_PID if str(case_id).startswith("P") else DOMAIN_DISCRETE


def trial_kind_for_phase(phase: str) -> str:
    return TRIAL_KIND_FORMAL if phase == PHASE_FORMAL else TRIAL_KIND_DEVELOPMENT


def results_dir_for_phase(project_root: Path, phase: str) -> Path:
    return project_root / load_design(project_root)["phase_results_dirs"][phase]


# ---------------------------------------------------------------------------------------------
# Matrices
# ---------------------------------------------------------------------------------------------

def _cell(case: dict[str, Any], variant: str, mode: str, kind: str, phase: str) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "variant": variant,
        "input_mode": mode,
        "domain": domain_for_case(case["case_id"]),
        "complexity": case["complexity"],
        "trial_kind": kind,
        "experiment_phase": phase,
    }


def formal_design_matrix(project_root: Path) -> list[dict[str, Any]]:
    """32 casos x 3 variantes x 3 modalidades (orden estable: caso, variante, modalidad)."""
    design = load_design(project_root)
    modes = [m["id"] for m in design["formal_input_modes"]]
    return [_cell(case, variant, mode, TRIAL_KIND_FORMAL, PHASE_FORMAL)
            for case in BC.load_catalog(project_root)["cases"]
            for variant in design["formal_variants"]
            for mode in modes]


def baseline_matrix(project_root: Path) -> list[dict[str, Any]]:
    """Baseline de desarrollo: D01-D20 x V1-V3 x TEXT (sin PID)."""
    baseline = load_design(project_root)["baseline"]
    return [_cell(case, variant, mode, baseline["trial_kind"], baseline["experiment_phase"])
            for case in BC.load_catalog(project_root)["cases"] if domain_for_case(case["case_id"]) == baseline["domain"]
            for variant in baseline["variants"]
            for mode in baseline["input_modes"]]


def validate_formal_matrix(matrix: list[dict[str, Any]]) -> list[str]:
    errors = []
    if len(matrix) != 288:
        errors.append(f"La matriz formal tiene {len(matrix)} ensayos (esperado 288).")
    per_case: dict[str, set] = {}
    for cell in matrix:
        per_case.setdefault(cell["case_id"], set()).add((cell["variant"], cell["input_mode"]))
    for case_id, cells in per_case.items():
        if len(cells) != 9:
            errors.append(f"{case_id} tiene {len(cells)} combinaciones (esperado 3 variantes x 3 modalidades = 9).")
    if len(per_case) != 32:
        errors.append(f"La matriz formal cubre {len(per_case)} casos (esperado 32).")
    return errors


# ---------------------------------------------------------------------------------------------
# Congelacion del software y guard de FORMAL_TRIAL (Parte X)
# ---------------------------------------------------------------------------------------------

def freeze_manifest_path(project_root: Path) -> Path:
    return project_root / load_design(project_root)["formal_freeze"]["manifest"]


def current_integrity_fingerprint(project_root: Path) -> dict[str, Any]:
    catalog_bytes = BC.catalog_path(project_root).read_bytes().replace(b"\r\n", b"\n")
    oracle_hashes = {}
    for case_id in BC.CASE_IDS:
        oracle = S.load_oracle(project_root, case_id)
        oracle_hashes[case_id] = {"version": oracle["approval"]["version"], "hash": S.compute_oracle_hash(oracle),
                                  "status": oracle["approval"]["status"]}
    return {
        "benchmark_version": BC.load_catalog(project_root).get("benchmark_version"),
        "canonical_catalog_hash": hashlib.sha256(catalog_bytes).hexdigest(),
        "oracles": oracle_hashes,
    }


def check_formal_trial_allowed(project_root: Path) -> tuple[bool, list[str]]:
    """FORMAL_TRIAL requiere un manifiesto de congelacion cuyos hashes coincidan con el estado actual."""
    path = freeze_manifest_path(project_root)
    if not path.exists():
        return False, [f"{ERROR_FORMAL_NOT_ALLOWED}: no existe {path.name} (el software aun no esta congelado)."]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    current = current_integrity_fingerprint(project_root)
    reasons = []
    if manifest.get("status") != "FROZEN":
        reasons.append(f"{ERROR_FORMAL_NOT_ALLOWED}: el manifiesto no esta en estado FROZEN.")
    for key in ("benchmark_version", "canonical_catalog_hash"):
        if manifest.get(key) != current[key]:
            reasons.append(f"{ERROR_FORMAL_NOT_ALLOWED}: {key} no coincide con el manifiesto.")
    for case_id, entry in current["oracles"].items():
        frozen = (manifest.get("oracles") or {}).get(case_id) or {}
        if frozen.get("hash") != entry["hash"] or entry["status"] != "FROZEN":
            reasons.append(f"{ERROR_FORMAL_NOT_ALLOWED}: Oracle {case_id} no coincide con el manifiesto o no esta FROZEN.")
    return not reasons, reasons


# ---------------------------------------------------------------------------------------------
# Clasificacion de resultados (Parte J) y filtro de estadisticas formales (Parte F)
# ---------------------------------------------------------------------------------------------

def classify_trial(record: dict[str, Any]) -> dict[str, Any]:
    """Categoria de fallo a partir del trial.json. INFRASTRUCTURE_ERROR nunca es un FAIL funcional."""
    final = record.get("final_status")
    stages = record.get("stages") or {}
    errors = " ".join(str(e) for e in record.get("errors") or [])
    stage = record.get("failure_stage")
    category = None
    if final == "PASS":
        category = SUCCESS
    elif final == "REVIEW":
        category = REVIEW
    elif final == "INFRASTRUCTURE_ERROR":
        if stages.get("download_success") is False:
            category = DOWNLOAD_FAILURE
        elif stages.get("runtime_connection_success") is False or "ORACLE_RUNTIME_NOT_READY" in errors:
            category = RUNTIME_FAILURE
        else:
            category = INFRASTRUCTURE_ERROR
    elif final == "FAIL":
        if stage == "generate":
            category = CODEGEN_FAILURE
        elif stage == "resource_binding":
            # El programa usa recursos sin binding real (ghost / tipo / LOCKED): fallo de IR/codegen.
            category = IR_FAILURE
        elif stage == "asr":
            # El ASR proceso un audio valido pero no devolvio texto: fallo del componente de voz.
            category = ASR_FAILURE
        elif stage == "io_allocation":
            category = IO_ALLOCATION_FAILURE
        elif (record.get("io_map") or {}).get("error") or "EXPERIMENT_IO_" in errors:
            category = IO_ALLOCATION_FAILURE
        elif stages.get("semantic_success") is False:
            category = SEMANTIC_FAILURE
        elif stages.get("verification_success") is False:
            category = VERIFICATION_FAILURE
        elif stages.get("compile_success") is False:
            category = COMPILE_FAILURE
        elif stages.get("safety_success") is False:
            category = SAFETY_FAILURE
        elif stages.get("functional_success") is False:
            category = FUNCTIONAL_FAILURE
        else:
            category = FUNCTIONAL_FAILURE if "FUNCTIONAL" in errors else SEMANTIC_FAILURE
    infrastructure = category in INFRASTRUCTURE_CATEGORIES
    return {
        "failure_category": category,
        "infrastructure_error": infrastructure,
        "system_failure": category not in (SUCCESS, REVIEW, None) and not infrastructure,
    }


def formal_statistics_records(records: list[dict[str, Any]], benchmark_version: int = 2) -> list[dict[str, Any]]:
    """Solo FORMAL_TRIAL de la fase FORMAL del benchmark vigente entran en las estadisticas formales."""
    return [r for r in records if r.get("trial_kind") == TRIAL_KIND_FORMAL and r.get("experiment_phase") == PHASE_FORMAL
            and r.get("benchmark_version") == benchmark_version]
