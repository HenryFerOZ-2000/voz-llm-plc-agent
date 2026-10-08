"""
Lote automatico TEXT (benchmark v2: hasta 32 casos x V1-V3 = 96 ensayos), estrictamente SECUENCIAL.

El lote NO es un pipeline nuevo: cada ensayo se ejecuta con el MISMO flujo que EJECUTAR ENSAYO COMPLETO
(generacion en la GUI -> deferred_evaluator.evaluate_trial: copia fresca del MASTER, workspace tiaw/
propio, TIA, .zap18 verificado, PLCSIM, Runtime, Oracle). Este modulo solo decide QUE ensayo sigue y
que hacer con su resultado, y lo deja todo persistido:

  results/batches/<batch_id>/batch_manifest.json   estado del lote (se reescribe tras CADA paso)
                             batch_summary.json    una entrada por ensayo
                             batch_summary.csv     una fila por ensayo (columnas estables)

Reglas (docs/text_batch_execution.md):
  * FAIL experimental (Semantic/IR/Compilation/Functional/Safety -> FINAL FAIL) o REVIEW: se registra y
    el lote CONTINUA. Nunca se reintenta.
  * INFRASTRUCTURE_ERROR: se registra con toda su evidencia y el lote se PAUSA. Solo el usuario reintenta.
  * Caso cuyo Oracle requiere extension del Runtime (P01-P12 hoy): se genera (Semantic/IR son datos
    validos) y queda NOT_EVALUABLE (DEVELOPMENT); en FORMAL el lote no se permite.
  * Estado inconsistente al reanudar (ensayo interrumpido): PAUSA y reporte; nunca se deduce progreso
    por la existencia de carpetas.
  * Los estados de etapa salen SIEMPRE de deferred_evaluator.trial_stage_summary (fuente unica).
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from trial_experiments import benchmark_catalog as BC
from trial_experiments import deferred_evaluator as DE
from trial_experiments import experimental_design as ED
from trial_experiments import oracle_schema as S
from trial_experiments import trial_model

SCHEMA_VERSION = 1
BATCHES_DIRNAME = "batches"
MANIFEST_FILENAME = "batch_manifest.json"
SUMMARY_JSON = "batch_summary.json"
SUMMARY_CSV = "batch_summary.csv"
INPUT_MODE = trial_model.INPUT_MODE_TEXT
VARIANT_ORDER = ("V1", "V2", "V3")
BATCH_PHASES = (trial_model.PHASE_DEVELOPMENT, trial_model.PHASE_FORMAL)
PHASE_TAGS = {trial_model.PHASE_DEVELOPMENT: "DEV", trial_model.PHASE_FORMAL: "FORMAL"}

# Estados del lote
STATUS_CREATED = "CREATED"
STATUS_RUNNING = "RUNNING"
STATUS_PAUSED = "PAUSED"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"
OPEN_STATUSES = (STATUS_CREATED, STATUS_RUNNING, STATUS_PAUSED)

# Estados de cada entrada (celda caso x variante)
ENTRY_PENDING = "PENDING"
ENTRY_GENERATING = "GENERATING"
ENTRY_EVALUATING = "EVALUATING"
ENTRY_COMPLETED = "COMPLETED"                  # veredicto experimental persistido: PASS / FAIL / REVIEW
ENTRY_INFRASTRUCTURE = "INFRASTRUCTURE_ERROR"  # pausa; reintento solo explicito
ENTRY_NOT_EVALUABLE = "NOT_EVALUABLE"          # Oracle requiere extension del Runtime (generado, no evaluado)
ENTRY_INTERRUPTED = "INTERRUPTED"              # caida/cierre a mitad del ensayo: pausa y reporte
ENTRY_BLOCKED = "BLOCKED"                      # precheck del ensayo no superado (entorno): pausa
DONE_ENTRY_STATES = (ENTRY_COMPLETED, ENTRY_NOT_EVALUABLE)
ATTENTION_ENTRY_STATES = (ENTRY_INFRASTRUCTURE, ENTRY_INTERRUPTED, ENTRY_BLOCKED)

# Decisiones tras un ensayo
DECISION_CONTINUE = "CONTINUE"
DECISION_PAUSE = "PAUSE"
DECISION_COMPLETED = "COMPLETED"

# Motivos de pausa
PAUSE_USER = "USER_REQUEST"
PAUSE_INFRASTRUCTURE = "INFRASTRUCTURE_ERROR"
PAUSE_INTERRUPTED = "TRIAL_INTERRUPTED"
PAUSE_BLOCKED = "TRIAL_PRECHECK_BLOCKED"
PAUSE_ENVIRONMENT = "ENVIRONMENT_NOT_READY"
PAUSE_INCONSISTENT = "INCONSISTENT_STATE"

ERROR_PLAN_EMPTY = "BATCH_PLAN_EMPTY"
ERROR_UNKNOWN_CASE = "BATCH_UNKNOWN_CASE"
ERROR_UNKNOWN_VARIANT = "BATCH_UNKNOWN_VARIANT"
ERROR_FORMAL_GUARD = "BATCH_FORMAL_GUARD_FAILED"
ERROR_OPEN_BATCH = "BATCH_ALREADY_OPEN"

RUNTIME_EXTENSION_MARKER = "requiere extension del Runtime"

CSV_FIELDS = (
    "batch_id", "index", "trial_id", "case_id", "variant_id", "input_mode", "phase", "domain", "complexity",
    "benchmark_version", "canonical_case_hash", "variant_hash", "oracle_hash", "entry_status", "evaluable",
    "semantic", "io_allocation", "ir", "compilation", "tia_archive", "download", "runtime", "functional", "safety",
    "final_verdict", "failure_category", "clarification_requested", "semantic_ms", "generation_ms", "compile_ms",
    "runtime_ms", "evaluation_ms", "total_ms", "attempts", "trial_dir", "zap18_path", "zap18_hash", "started_at",
    "completed_at", "superseded_trial_ids",
    # Dimensiones separadas (booleanos crudos de trial.json; vacio = no evaluado). Se anaden al final:
    # las columnas anteriores no cambian. semantic_benchmark (columna de etapa) es la misma medida en PASS/FAIL.
    "semantic_benchmark", "semantic_pipeline_success", "semantic_benchmark_match", "functional_success", "safety_success",
    "infrastructure_status",
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------------------------

def case_ids_in_benchmark_order(project_root: Path) -> list[str]:
    """Orden oficial del benchmark (canonical_cases.json): D01..D20, P01..P12."""
    return [str(case["case_id"]) for case in BC.load_catalog(project_root)["cases"]]


def case_is_evaluable(project_root: Path, case_id: str) -> bool:
    return S.runtime_support(S.load_oracle(project_root, case_id)) == S.RUNTIME_EXECUTABLE_NOW


def build_plan(project_root: Path, case_ids: list[str] | None = None, variants: list[str] | tuple[str, ...] = VARIANT_ORDER) -> list[dict[str, Any]]:
    """
    Plan determinista caso-mayor: D01 V1, D01 V2, D01 V3, D02 V1, ... El orden de casos sale del benchmark
    oficial y el de variantes de VARIANT_ORDER, nunca del orden de la seleccion ni del sistema de archivos.
    """
    catalog_order = case_ids_in_benchmark_order(project_root)
    selected = set(catalog_order if case_ids is None else case_ids)
    unknown = sorted(selected - set(catalog_order))
    if unknown:
        raise ValueError(f"{ERROR_UNKNOWN_CASE}: {', '.join(unknown)}")
    unknown_variants = sorted(set(variants) - set(VARIANT_ORDER))
    if unknown_variants:
        raise ValueError(f"{ERROR_UNKNOWN_VARIANT}: {', '.join(unknown_variants)}")
    cases = BC.cases_by_id(project_root)
    plan: list[dict[str, Any]] = []
    for case_id in catalog_order:
        if case_id not in selected:
            continue
        evaluable = case_is_evaluable(project_root, case_id)
        for variant_id in VARIANT_ORDER:
            if variant_id not in variants:
                continue
            command = cases[case_id]["variants"][variant_id]
            plan.append({"index": len(plan), "case_id": case_id, "variant_id": variant_id, "input_mode": INPUT_MODE,
                         "reference_text": command, "variant_hash": BC.variant_hash(command), "evaluable": evaluable,
                         "status": ENTRY_PENDING, "trial_id": None, "trial_dir": None, "superseded": [],
                         "started_at": None, "completed_at": None, "result": None, "notes": []})
    if not plan:
        raise ValueError(f"{ERROR_PLAN_EMPTY}: la seleccion no produce ningun ensayo.")
    return plan


def parse_case_selection(project_root: Path, text: str | None, groups: list[str] | tuple[str, ...] = ("D", "P")) -> list[str]:
    """
    Casos del lote en orden del benchmark. Con texto ("D01-D03, P02"): solo esos (rangos del mismo
    grupo); sin texto: los grupos marcados (D = D01-D20, P = P01-P12).
    """
    order = case_ids_in_benchmark_order(project_root)
    tokens = [token for token in str(text or "").replace(";", ",").replace(" ", ",").split(",") if token.strip()]
    if not tokens:
        selected = [case_id for case_id in order if case_id[0] in groups]
        if not selected:
            raise ValueError(f"{ERROR_PLAN_EMPTY}: seleccione D01-D20 y/o P01-P12 o un rango.")
        return selected
    chosen: set[str] = set()
    for token in tokens:
        token = token.strip().upper()
        start, _, end = token.partition("-")
        end = end or start
        if start not in order or end not in order or start[0] != end[0] or order.index(start) > order.index(end):
            raise ValueError(f"{ERROR_UNKNOWN_CASE}: rango invalido {token!r}")
        chosen.update(order[order.index(start):order.index(end) + 1])
    return [case_id for case_id in order if case_id in chosen]


def entry_label(entry: dict[str, Any] | None) -> str:
    return "-" if not entry else f"{entry['case_id']} · {entry['variant_id']} · {entry['input_mode']}"


# ---------------------------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------------------------

def batches_root(project_root: Path) -> Path:
    return Path(project_root) / trial_model.RESULTS_DIRNAME / BATCHES_DIRNAME


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(temporary, path)  # nunca deja un manifiesto a medio escribir (cierre/caida)


def save_manifest(batch_dir: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _now()
    _refresh_progress(manifest)
    _write_json_atomic(Path(batch_dir) / MANIFEST_FILENAME, manifest)


def load_manifest(batch_dir: Path) -> dict[str, Any]:
    return json.loads((Path(batch_dir) / MANIFEST_FILENAME).read_text(encoding="utf-8"))


def batch_dir_for(project_root: Path, manifest: dict[str, Any]) -> Path:
    return batches_root(project_root) / manifest["batch_id"]


def list_batches(project_root: Path) -> list[dict[str, Any]]:
    root = batches_root(project_root)
    if not root.exists():
        return []
    manifests = []
    for path in sorted(root.glob(f"*/{MANIFEST_FILENAME}")):
        try:
            manifests.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(manifests, key=lambda m: m.get("created_at") or "")


def find_open_batch(project_root: Path) -> dict[str, Any] | None:
    """Lote CREATED/RUNNING/PAUSED mas reciente (un RUNNING tras un cierre se trata al reanudar)."""
    open_batches = [m for m in list_batches(project_root) if m.get("status") in OPEN_STATUSES]
    return open_batches[-1] if open_batches else None


def new_batch_id(project_root: Path, phase: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d")
    prefix = f"TEXT_{PHASE_TAGS[phase]}_{stamp}_"
    existing = {path.name for path in batches_root(project_root).glob(prefix + "*")} if batches_root(project_root).exists() else set()
    number = 1
    while f"{prefix}{number:03d}" in existing:
        number += 1
    return f"{prefix}{number:03d}"


def git_info(project_root: Path) -> dict[str, Any]:
    """Commit y estado del arbol (None si Git no esta disponible). Nunca modifica el repositorio."""
    def _git(*args: str) -> str | None:
        try:
            completed = subprocess.run(["git", *args], cwd=project_root, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        return completed.stdout if completed.returncode == 0 else None

    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain", "--untracked-files=no")
    return {"commit": commit.strip() if commit else None, "dirty": None if status is None else bool(status.strip()),
            "dirty_files": [line[3:] for line in (status or "").splitlines()][:20]}


def create_batch(
    project_root: Path,
    phase: str,
    case_ids: list[str] | None = None,
    variants: list[str] | tuple[str, ...] = VARIANT_ORDER,
    host_id: str | None = None,
    git: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    if phase not in BATCH_PHASES:
        raise ValueError(f"Fase de lote invalida: {phase!r} (esperado {BATCH_PHASES}).")
    if find_open_batch(project_root) is not None:
        raise ValueError(f"{ERROR_OPEN_BATCH}: ya existe un lote abierto; reanudelo o cancelelo primero.")
    plan = build_plan(project_root, case_ids, variants)
    batch_id = new_batch_id(project_root, phase, now)
    catalog = BC.load_catalog(project_root)
    git = git if git is not None else git_info(project_root)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "phase": phase,
        "trial_kind": trial_model.trial_kind_for_phase(phase),
        "input_mode": INPUT_MODE,
        "benchmark_version": catalog.get("benchmark_version"),
        "selection": {"case_ids": list(dict.fromkeys(e["case_id"] for e in plan)),
                      "variants": list(dict.fromkeys(e["variant_id"] for e in plan))},
        "created_at": _now(),
        "started_at": None,
        "completed_at": None,
        "status": STATUS_CREATED,
        "pause_requested": False,
        "pause_reason": None,
        "pause_detail": None,
        "git_commit": git.get("commit"),
        "git_dirty": git.get("dirty"),
        "host_id": host_id,
        "total_trials": len(plan),
        "ordered_trial_plan": plan,
        "events": [{"at": _now(), "event": "CREATED", "detail": f"{len(plan)} ensayos"}],
    }
    batch_dir = batches_root(project_root) / batch_id
    save_manifest(batch_dir, manifest)
    write_summaries(project_root, batch_dir, manifest)
    return batch_dir, manifest


def _event(manifest: dict[str, Any], event: str, detail: str = "") -> None:
    manifest.setdefault("events", []).append({"at": _now(), "event": event, "detail": detail})


def _refresh_progress(manifest: dict[str, Any]) -> None:
    plan = manifest.get("ordered_trial_plan") or []
    done = [e for e in plan if e["status"] in DONE_ENTRY_STATES]
    manifest["completed_trials"] = len(done)
    manifest["trial_ids"] = [e["trial_id"] for e in plan if e.get("trial_id")]
    current = next((e for e in plan if e["status"] not in DONE_ENTRY_STATES), None)
    manifest["current_index"] = current["index"] if current else None
    manifest["next_trial"] = None if current is None else {"index": current["index"], "case_id": current["case_id"],
                                                            "variant_id": current["variant_id"], "input_mode": current["input_mode"],
                                                            "status": current["status"]}
    manifest["results"] = {e["trial_id"]: (e.get("result") or {}).get("final_verdict") for e in plan if e.get("trial_id")}


# ---------------------------------------------------------------------------------------------
# Estado y transiciones
# ---------------------------------------------------------------------------------------------

def next_entry(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Primera entrada no terminada (en orden del plan). Nunca salta una que necesita atencion."""
    return next((e for e in manifest["ordered_trial_plan"] if e["status"] not in DONE_ENTRY_STATES), None)


def progress(manifest: dict[str, Any]) -> dict[str, Any]:
    plan = manifest["ordered_trial_plan"]
    verdicts = [(e.get("result") or {}).get("final_verdict") for e in plan if e["status"] in DONE_ENTRY_STATES + ATTENTION_ENTRY_STATES]
    return {
        "total": len(plan),
        "completed": sum(e["status"] in DONE_ENTRY_STATES for e in plan),
        "pass": verdicts.count(trial_model.FINAL_STATUS_PASS),
        "fail": verdicts.count(trial_model.FINAL_STATUS_FAIL),
        "review": verdicts.count(trial_model.FINAL_STATUS_REVIEW),
        "infrastructure_error": sum(e["status"] == ENTRY_INFRASTRUCTURE for e in plan),
        "not_evaluable": sum(e["status"] == ENTRY_NOT_EVALUABLE for e in plan),
        "interrupted": sum(e["status"] == ENTRY_INTERRUPTED for e in plan),
        "blocked": sum(e["status"] == ENTRY_BLOCKED for e in plan),
    }


def mark_started(manifest: dict[str, Any]) -> None:
    manifest["status"] = STATUS_RUNNING
    manifest["started_at"] = manifest.get("started_at") or _now()
    manifest["pause_requested"] = False
    manifest["pause_reason"] = manifest["pause_detail"] = None
    _event(manifest, "RUNNING")


def begin_entry(manifest: dict[str, Any], entry: dict[str, Any], trial_dir: Path, trial_id: str) -> None:
    """La generacion del ensayo ya creo su carpeta: se fija ANTES de seguir (sobrevive a una caida)."""
    entry.update({"status": ENTRY_GENERATING, "trial_id": trial_id, "trial_dir": str(trial_dir), "started_at": entry.get("started_at") or _now()})
    _event(manifest, "TRIAL_STARTED", f"{entry_label(entry)} -> {trial_id}")


def mark_evaluating(manifest: dict[str, Any], entry: dict[str, Any]) -> None:
    entry["status"] = ENTRY_EVALUATING
    _event(manifest, "TRIAL_EVALUATING", entry["trial_id"])


def request_pause(manifest: dict[str, Any]) -> None:
    """PAUSAR DESPUES DEL ENSAYO ACTUAL: nunca interrumpe TIA; se aplica al terminar el ensayo en curso."""
    manifest["pause_requested"] = True
    _event(manifest, "PAUSE_REQUESTED")


def pause(manifest: dict[str, Any], reason: str, detail: str = "") -> None:
    manifest.update({"status": STATUS_PAUSED, "pause_requested": False, "pause_reason": reason, "pause_detail": detail})
    _event(manifest, "PAUSED", f"{reason}: {detail}".strip(": "))


def cancel(manifest: dict[str, Any], detail: str = "") -> None:
    """DETENER LOTE: el lote queda cerrado (los ensayos ya hechos se conservan; nada se borra)."""
    manifest.update({"status": STATUS_CANCELLED, "pause_requested": False, "completed_at": _now()})
    _event(manifest, "CANCELLED", detail)


def _complete_if_done(manifest: dict[str, Any]) -> bool:
    if next_entry(manifest) is None:
        manifest.update({"status": STATUS_COMPLETED, "completed_at": _now()})
        _event(manifest, "COMPLETED")
        return True
    return False


def _final_of(record: dict[str, Any]) -> str | None:
    final = (record.get("evaluation") or {}).get("final_verdict") or record.get("final_verdict") or record.get("final_status")
    return None if final in (None, "", trial_model.FINAL_STATUS_PREPARED) else str(final)


def outcome_for_record(record: dict[str, Any]) -> tuple[str, str | None]:
    """
    (estado de entrada, motivo de pausa) a partir del registro PERSISTIDO del ensayo:
      PASS / FAIL / REVIEW            -> COMPLETED, continuar (dato experimental; nunca se reintenta)
      INFRASTRUCTURE_ERROR            -> pausa
      sin veredicto (no termino)      -> INTERRUPTED, pausa
    """
    final = _final_of(record)
    if final == trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR:
        return ENTRY_INFRASTRUCTURE, PAUSE_INFRASTRUCTURE
    if final in (trial_model.FINAL_STATUS_PASS, trial_model.FINAL_STATUS_FAIL, trial_model.FINAL_STATUS_REVIEW):
        return ENTRY_COMPLETED, None
    return ENTRY_INTERRUPTED, PAUSE_INTERRUPTED


def _after_entry(manifest: dict[str, Any], pause_reason: str | None, detail: str) -> str:
    if pause_reason:
        pause(manifest, pause_reason, detail)
        return DECISION_PAUSE
    if _complete_if_done(manifest):
        return DECISION_COMPLETED
    if manifest.get("pause_requested"):
        pause(manifest, PAUSE_USER, "pausa solicitada; el ensayo en curso termino y se persistio")
        return DECISION_PAUSE
    return DECISION_CONTINUE


def record_trial_result(project_root: Path, batch_dir: Path, manifest: dict[str, Any], entry: dict[str, Any]) -> str:
    """Ensayo TERMINADO (generacion fallida o evaluacion finalizada): registra, persiste y decide."""
    record = trial_model.load_trial(Path(entry["trial_dir"]))
    status, pause_reason = outcome_for_record(record)
    entry["status"] = status
    entry["completed_at"] = _now()
    entry["result"] = trial_row(project_root, record, entry, manifest)
    _event(manifest, "TRIAL_FINISHED", f"{entry['trial_id']}: {entry['result']['final_verdict']} ({status})")
    decision = _after_entry(manifest, pause_reason, f"{entry_label(entry)} · {entry['trial_id']}")
    save_manifest(batch_dir, manifest)
    write_summaries(project_root, batch_dir, manifest)
    return decision


def record_precheck_block(project_root: Path, batch_dir: Path, manifest: dict[str, Any], entry: dict[str, Any], errors: list[str]) -> str:
    """El precheck de evaluacion (el mismo del dialogo individual) no se supero."""
    record = trial_model.load_trial(Path(entry["trial_dir"]))
    not_evaluable = bool(errors) and all(RUNTIME_EXTENSION_MARKER in error for error in errors)
    entry["status"] = ENTRY_NOT_EVALUABLE if not_evaluable else ENTRY_BLOCKED
    entry["completed_at"] = _now() if not_evaluable else None
    entry["notes"] = list(entry.get("notes") or []) + [f"precheck: {error}" for error in errors[:5]]
    entry["result"] = trial_row(project_root, record, entry, manifest)
    _event(manifest, "TRIAL_NOT_EVALUABLE" if not_evaluable else "TRIAL_BLOCKED", f"{entry['trial_id']}: {'; '.join(errors[:3])}")
    decision = _after_entry(manifest, None if not_evaluable else PAUSE_BLOCKED, "; ".join(errors[:3]))
    save_manifest(batch_dir, manifest)
    write_summaries(project_root, batch_dir, manifest)
    return decision


def supersede_for_new_trial(manifest: dict[str, Any], entry: dict[str, Any], reason: str) -> dict[str, Any]:
    """
    Reintento a nivel de ENSAYO (generacion caida o ensayo interrumpido): el ensayo anterior se conserva
    intacto y se enlaza; la celda vuelve a PENDING y generara un ensayo NUEVO (repeat_of_trial_id).
    """
    previous = {"trial_id": entry.get("trial_id"), "trial_dir": entry.get("trial_dir"), "status": entry.get("status"),
                "reason": reason, "at": _now()}
    entry["superseded"] = list(entry.get("superseded") or []) + [previous]
    entry.update({"status": ENTRY_PENDING, "trial_id": None, "trial_dir": None, "result": None, "started_at": None, "completed_at": None})
    _event(manifest, "TRIAL_SUPERSEDED", f"{previous['trial_id']}: {reason}")
    return previous


def reconcile(project_root: Path, manifest: dict[str, Any]) -> list[str]:
    """
    Al REANUDAR (p.ej. tras cerrar la GUI o una caida): contrasta cada entrada en curso con el registro
    persistido de su ensayo. Lo que ya termino se registra; lo que quedo a medias se marca INTERRUPTED.
    Devuelve las inconsistencias encontradas (si hay alguna, el lote debe quedar PAUSADO).
    """
    issues: list[str] = []
    for entry in manifest["ordered_trial_plan"]:
        if entry["status"] not in (ENTRY_GENERATING, ENTRY_EVALUATING):
            continue
        directory = Path(entry["trial_dir"]) if entry.get("trial_dir") else None
        if directory is None or not (directory / trial_model.TRIAL_FILENAME).exists():
            entry["status"] = ENTRY_INTERRUPTED
            issues.append(f"{entry_label(entry)}: el ensayo {entry.get('trial_id')} no tiene trial.json")
            continue
        record = trial_model.load_trial(directory)
        generation = (record.get("generation") or {}).get("status")
        evaluation = (record.get("evaluation") or {}).get("status")
        if _final_of(record) is not None and evaluation != "RUNNING":
            status, _ = outcome_for_record(record)
            entry.update({"status": status, "completed_at": record.get("completed_at") or _now(),
                          "result": trial_row(project_root, record, entry, manifest)})
            if status != ENTRY_COMPLETED:
                issues.append(f"{entry_label(entry)}: {entry['trial_id']} termino con {status}")
            continue
        if generation == DE.GENERATION_SUCCESS and evaluation == DE.EVALUATION_PENDING:
            entry["status"] = ENTRY_EVALUATING  # generado y sin evaluar: se evalua ese MISMO ensayo al reanudar
            entry.setdefault("notes", []).append("reanudacion: evaluacion pendiente del mismo ensayo")
            continue
        entry["status"] = ENTRY_INTERRUPTED
        issues.append(f"{entry_label(entry)}: {entry['trial_id']} quedo a medias (generacion={generation}, evaluacion={evaluation})")
    return issues


# ---------------------------------------------------------------------------------------------
# Resumen por ensayo (fuente: trial.json + trial_stage_summary)
# ---------------------------------------------------------------------------------------------

def trial_row(project_root: Path, record: dict[str, Any], entry: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Una fila por ensayo. Valores ausentes -> None (nunca se inventan)."""
    summary = DE.trial_stage_summary(record)
    stages = record.get("stages") or {}
    timing = record.get("timing") or {}
    archive = record.get("tia_archive") or {}
    evaluation = record.get("evaluation") or {}
    return {
        "batch_id": manifest.get("batch_id"),
        "index": entry.get("index"),
        "trial_id": record.get("trial_id") or entry.get("trial_id"),
        "case_id": record.get("case_id") or entry.get("case_id"),
        "variant_id": record.get("variant_id") or entry.get("variant_id"),
        "input_mode": record.get("input_mode") or entry.get("input_mode"),
        "phase": record.get("experiment_phase"),
        "domain": record.get("domain"),
        "complexity": record.get("complexity"),
        "benchmark_version": record.get("benchmark_version"),
        "canonical_case_hash": record.get("canonical_case_hash"),
        "variant_hash": record.get("variant_hash"),
        "oracle_hash": (record.get("oracle_reference") or {}).get("oracle_hash"),
        "entry_status": entry.get("status"),
        "evaluable": entry.get("evaluable"),
        **{key: summary[key] for key in DE.STAGE_KEYS},
        "failure_category": record.get("failure_category"),
        "clarification_requested": record.get("clarification_requested"),
        "semantic_ms": timing.get("semantic_ms"),
        "generation_ms": timing.get("generation_total_ms", timing.get("generation_ms")),
        "compile_ms": timing.get("compile_ms"),
        "runtime_ms": timing.get("runtime_ms"),
        "evaluation_ms": timing.get("evaluation_ms"),
        "total_ms": timing.get("total_ms"),
        "attempts": len(evaluation.get("attempts") or []),
        "trial_dir": entry.get("trial_dir"),
        "zap18_path": archive.get("zap18_path"),
        "zap18_hash": archive.get("zap18_hash"),
        "started_at": entry.get("started_at") or record.get("created_at"),
        "completed_at": record.get("completed_at"),
        "superseded_trial_ids": [s.get("trial_id") for s in entry.get("superseded") or [] if s.get("trial_id")],
        "semantic_pipeline_success": stages.get("semantic_success"),
        "semantic_benchmark_match": stages.get("semantic_benchmark_match"),
        "functional_success": stages.get("functional_success"),
        "safety_success": stages.get("safety_success"),
        "infrastructure_status": summary["infrastructure_status"],
    }


def summary_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry["result"] for entry in manifest["ordered_trial_plan"] if entry.get("result")]


def batch_totals(manifest: dict[str, Any]) -> dict[str, Any]:
    """Conteos del lote: cada denominador sale de las filas registradas (nunca se asume)."""
    rows = summary_rows(manifest)

    def _count(key: str, value: str) -> int:
        return sum(row.get(key) == value for row in rows)

    return {
        "trials_planned": manifest.get("total_trials"),
        "trials_recorded": len(rows),
        "final": {verdict: _count("final_verdict", verdict) for verdict in
                  (trial_model.FINAL_STATUS_PASS, trial_model.FINAL_STATUS_FAIL, trial_model.FINAL_STATUS_REVIEW,
                   trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR)},
        "not_evaluable": sum(row.get("entry_status") == ENTRY_NOT_EVALUABLE for row in rows),
        "stages": {key: {"PASS": _count(key, "PASS"), "FAIL": _count(key, "FAIL"), "recorded": sum(row.get(key) not in (None, "-") for row in rows)}
                   for key in DE.STAGE_KEYS if key != "final_verdict"},
        "safety_violations": _count("safety", "FAIL"),
    }


def write_summaries(project_root: Path, batch_dir: Path, manifest: dict[str, Any]) -> dict[str, str]:
    batch_dir = Path(batch_dir)
    rows = summary_rows(manifest)
    started, completed = manifest.get("started_at"), manifest.get("completed_at")
    duration = None
    if started and completed:
        duration = int((datetime.fromisoformat(completed) - datetime.fromisoformat(started)).total_seconds())
    payload = {"batch_id": manifest["batch_id"], "phase": manifest["phase"], "input_mode": manifest["input_mode"],
               "benchmark_version": manifest.get("benchmark_version"), "status": manifest["status"],
               "git_commit": manifest.get("git_commit"), "host_id": manifest.get("host_id"),
               "started_at": started, "completed_at": completed, "duration_s": duration,
               "progress": progress(manifest), "totals": batch_totals(manifest), "trials": rows}
    _write_json_atomic(batch_dir / SUMMARY_JSON, payload)
    temporary = batch_dir / (SUMMARY_CSV + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ("" if row.get(key) is None else ";".join(row[key]) if isinstance(row.get(key), list) else row.get(key))
                             for key in CSV_FIELDS})
    os.replace(temporary, batch_dir / SUMMARY_CSV)
    return {"json": str(batch_dir / SUMMARY_JSON), "csv": str(batch_dir / SUMMARY_CSV)}


def final_report_lines(manifest: dict[str, Any]) -> list[str]:
    totals = batch_totals(manifest)
    state = progress(manifest)
    stages = totals["stages"]
    started, completed = manifest.get("started_at"), manifest.get("completed_at")
    duration = "-"
    if started and completed:
        seconds = int((datetime.fromisoformat(completed) - datetime.fromisoformat(started)).total_seconds())
        duration = f"{seconds // 3600:d}h {seconds % 3600 // 60:02d}m {seconds % 60:02d}s"
    title = {STATUS_COMPLETED: "LOTE TEXT COMPLETADO", STATUS_CANCELLED: "LOTE TEXT DETENIDO",
             STATUS_PAUSED: "LOTE TEXT PAUSADO"}.get(manifest["status"], f"LOTE TEXT {manifest['status']}")
    return [
        title, f"{manifest['batch_id']} · {manifest['phase']}", "",
        f"{totals['trials_recorded']} / {totals['trials_planned']} registrados ({state['completed']} terminados)", "",
        f"Final PASS: {totals['final']['PASS']}", f"Final FAIL: {totals['final']['FAIL']}",
        f"Final REVIEW: {totals['final']['REVIEW']}", f"Infrastructure errors: {totals['final']['INFRASTRUCTURE_ERROR']}",
        f"No evaluables (Runtime): {totals['not_evaluable']}", "",
        f"Semantic PASS: {stages['semantic']['PASS']} / {stages['semantic']['recorded']}",
        f"Semantic benchmark match: {stages['semantic_benchmark']['PASS']} / {stages['semantic_benchmark']['recorded']}",
        f"Compilation PASS: {stages['compilation']['PASS']} / {stages['compilation']['recorded']}",
        f"Functional PASS: {stages['functional']['PASS']} / {stages['functional']['recorded']}",
        f"Safety violations: {totals['safety_violations']} / {stages['safety']['recorded']}", "",
        f"Duracion total: {duration}",
    ]


# ---------------------------------------------------------------------------------------------
# Guardas
# ---------------------------------------------------------------------------------------------

def formal_guards(
    project_root: Path,
    plan: list[dict[str, Any]],
    git: dict[str, Any] | None = None,
    runtime_status_fn: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Antes de un lote FORMAL (nada se inicia si algo falla): software congelado, benchmark integro,
    32 Oracles FROZEN con hash, diseno valido, MASTER FORMAL_READY con snapshot, PLCSIM listo, memoria,
    arbol Git limpio con commit registrado, variantes TEXT del benchmark y casos evaluables.
    """
    from trial_experiments import batch_runner

    checks: list[dict[str, Any]] = []

    def _check(check_id: str, ok: bool, detail: str = "") -> None:
        checks.append({"id": check_id, "ok": bool(ok), "detail": detail})

    allowed, reasons = ED.check_formal_trial_allowed(project_root)
    _check("software_frozen", allowed, "; ".join(reasons) or "software_freeze_manifest valido")
    catalog = BC.load_catalog(project_root)
    consistency = BC.build_variant_consistency_report(project_root)
    _check("benchmark_integrity", catalog.get("benchmark_version") == 2 and len(catalog["cases"]) == 32
           and consistency["consistent_variants"] == consistency["total_variants"] == 96,
           f"v{catalog.get('benchmark_version')}, {len(catalog['cases'])} casos, {consistency['consistent_variants']}/96 variantes")
    oracles = batch_runner.integrity_snapshot(project_root)["oracles"]
    frozen = [c for c, e in oracles.items() if e["status"] == "FROZEN" and e["stored_hash"] == e["computed_hash"]]
    _check("oracles_frozen_hash", len(frozen) == 32, f"{len(frozen)}/32 FROZEN con hash integro")
    design_errors = ED.validate_formal_matrix(ED.formal_design_matrix(project_root))
    _check("experimental_design", not design_errors, "; ".join(design_errors) or "matriz formal valida")
    environment = DE.environment_precheck(project_root, trial_model.PHASE_FORMAL)
    _check("environment_master_plcsim_memory", environment["ok"], "; ".join(environment["errors"][:4]) or "MASTER FORMAL_READY, snapshot, PLCSIM, memoria")
    if runtime_status_fn is not None:
        runtime = runtime_status_fn(project_root)
        _check("plcsim_ready", bool(runtime.get("connected")) and runtime.get("cpu_state") is not None,
               f"{runtime.get('status')} / {runtime.get('instance_name')}")
    git = git if git is not None else git_info(project_root)
    _check("git_clean", git.get("dirty") is False and bool(git.get("commit")),
           f"commit {git.get('commit')}" + (f"; cambios sin commit: {', '.join(git.get('dirty_files') or [])}" if git.get("dirty") else "")
           if git.get("commit") else "Git no disponible")
    cases = BC.cases_by_id(project_root)
    mismatched = [entry_label(e) for e in plan if cases[e["case_id"]]["variants"][e["variant_id"]] != e["reference_text"]
                  or BC.variant_hash(e["reference_text"]) != e["variant_hash"]]
    _check("text_variants_from_benchmark", not mismatched, ", ".join(mismatched) or f"{len(plan)} comandos del benchmark congelado")
    not_evaluable = sorted({e["case_id"] for e in plan if not e["evaluable"]})
    _check("cases_evaluable", not not_evaluable,
           (f"{', '.join(not_evaluable)}: el Oracle requiere extension del Runtime" if not_evaluable else "todos evaluables"))
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "failed": [c["id"] for c in checks if not c["ok"]],
            "git": git, "checked_at": _now()}
