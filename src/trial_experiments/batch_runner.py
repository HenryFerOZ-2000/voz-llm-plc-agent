"""
Batch runner del baseline de desarrollo v2 (Fase 4A.1): D01-D20 x V1-V3 x TEXT = 60 ensayos.

Que hace:
  - preflight (entorno real + integridad) con ABORT ante cualquier duda;
  - cola persistente y reanudable (results/development_baseline_v2/baseline_queue.json): nunca
    repite un ensayo completado, persiste tras CADA ensayo y continua tras un FAIL funcional;
  - ejecuta cada ensayo con el MISMO pipeline de la GUI (EJECUTAR ENSAYO), sin atajos: el comando
    es el texto canonico de la variante y el LLM recibe exactamente lo que recibiria un usuario;
  - dos capas de seguridad: target PLCSIM_ADVANCED (config + guard en tiempo de descarga) y
    physical_download = forbidden (diseno experimental);
  - reintento solo tecnico: INFRASTRUCTURE_ERROR con --retry-infrastructure y retry_reason
    explicitos; cada intento es un ensayo nuevo (trial_id nuevo), nunca sobrescribe el anterior;
  - reportes: baseline_trials.csv, baseline_summary.json/.md, baseline_failures.json y
    data/capability_gap_baseline_validation.json (los gaps NO se corrigen aqui).

Que NO hace: ensayos PID (P01-P12 siguen REQUIRES_RUNTIME_EXTENSION), FORMAL_TRIAL, paralelismo,
reintentos de fallos semanticos/compilacion/funcionales/seguridad, ni cambios del core.
"""
from __future__ import annotations

import argparse
import csv
import json
import socket
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from trial_experiments import benchmark_catalog as BC
from trial_experiments import experimental_design as ED
from trial_experiments import oracle_review
from trial_experiments import oracle_schema as S
from trial_experiments import trial_model

QUEUE_FILENAME = "baseline_queue.json"
PREFLIGHT_FILENAME = "baseline_preflight.json"
TRIALS_CSV = "baseline_trials.csv"
SUMMARY_JSON = "baseline_summary.json"
SUMMARY_MD = "baseline_summary.md"
FAILURES_JSON = "baseline_failures.json"
GAP_VALIDATION_RELATIVE = Path("data") / "capability_gap_baseline_validation.json"

MAP_FILES = (
    "data/plc_maps/mapa_banco_fisico_base.json",
    "data/plc_maps/mapa_simulacion_completo.json",
    "data/plc_maps/mapa_pid_simulacion.json",
    "data/plc_maps/mapa_pid_banco_fisico.json",
)
PROTECTED_FILES = MAP_FILES + (
    "data/experiment_cases/canonical_cases.json",
    "data/plc_maps/experiment_variants.json",
    "data/plc_maps/profiles.json",
    "data/experimental_design.json",
)

ENTRY_PENDING = "PENDING"
ENTRY_COMPLETED = "COMPLETED"
ENTRY_INFRASTRUCTURE = "INFRASTRUCTURE_ERROR"

DEFAULT_TRIAL_TIMEOUT_S = 900
MAX_CONSECUTIVE_INFRA = 2
BATCH_SPEAKER_ID = "TEXT_BATCH"

ERROR_PHYSICAL_FORBIDDEN = "PHYSICAL_DOWNLOAD_FORBIDDEN"
ERROR_TRIAL_TIMEOUT = "BATCH_TRIAL_TIMEOUT"
ERROR_ABORTED_WITHOUT_STATUS = "BATCH_PIPELINE_ABORTED_WITHOUT_STATUS"
ERROR_START_FAILED = "BATCH_TRIAL_NOT_STARTED"

# Violaciones del guard de descarga detectadas dentro del hilo de descarga de la GUI (alli la
# excepcion la absorbe el pipeline como fallo de descarga); el runner las revisa tras cada ensayo.
GUARD_VIOLATIONS: list[str] = []


class BatchAbort(RuntimeError):
    """Condicion que obliga a detener el batch (nunca se oculta ni se reintenta sola)."""


class BatchTrialTimeout(BatchAbort):
    """El ensayo quedo colgado: se registra como intento INFRASTRUCTURE_ERROR y luego se detiene el batch."""

    def __init__(self, message: str, directory: Path) -> None:
        super().__init__(message)
        self.directory = directory


# ---------------------------------------------------------------------------------------------
# Integridad (antes / despues / tras cada ensayo)
# ---------------------------------------------------------------------------------------------

def file_hash(path: Path) -> str | None:
    return BC.normalized_file_hash(path) if path.exists() else None


def integrity_snapshot(project_root: Path) -> dict[str, Any]:
    oracles = {}
    for case_id in BC.CASE_IDS:
        oracle = S.load_oracle(project_root, case_id)
        approval = oracle.get("approval") or {}
        oracles[case_id] = {
            "status": approval.get("status"),
            "version": approval.get("version"),
            "stored_hash": approval.get("hash"),
            "computed_hash": S.compute_oracle_hash(oracle),
        }
    return {
        "files": {relative: file_hash(project_root / relative) for relative in PROTECTED_FILES},
        "oracles": oracles,
    }


def integrity_differences(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    differences = [f"{relative} cambio" for relative, digest in before["files"].items() if after["files"].get(relative) != digest]
    for case_id, entry in before["oracles"].items():
        if after["oracles"].get(case_id) != entry:
            differences.append(f"Oracle {case_id} cambio")
    return differences


# ---------------------------------------------------------------------------------------------
# Guards de seguridad (dos capas)
# ---------------------------------------------------------------------------------------------

def experiment_download_target(project_root: Path) -> dict[str, Any]:
    import tia_openness  # diferido: modulo del core, solo lectura de config

    return tia_openness.resolve_download_target(tia_openness.load_tia_config(project_root), tia_openness.DOWNLOAD_PURPOSE_EXPERIMENT)


def assert_plcsim_only(project_root: Path) -> None:
    """Capa 1: config de descarga experimental = PLCSIM_ADVANCED. Capa 2: diseno physical_download=forbidden."""
    target = experiment_download_target(project_root)
    if target.get("target_type") != "PLCSIM_ADVANCED":
        raise BatchAbort(f"{ERROR_PHYSICAL_FORBIDDEN}: destino experimental {target.get('target_type')!r} (solo PLCSIM_ADVANCED).")
    architecture = ED.load_design(project_root)["architecture"]
    if architecture.get("target_type") != "PLCSIM_ADVANCED" or architecture.get("physical_download") != "forbidden":
        raise BatchAbort(f"{ERROR_PHYSICAL_FORBIDDEN}: el diseno experimental no fija PLCSIM_ADVANCED / physical_download=forbidden.")


def guarded_download(real_download: Callable[..., dict[str, Any]], project_root: Path) -> Callable[..., dict[str, Any]]:
    """Envuelve download_program_to_plc: re-verifica el destino JUSTO antes de cada descarga."""
    import tia_openness

    def _download(package_dir: Path, root: Path | None = None, purpose: str = tia_openness.DOWNLOAD_PURPOSE_NORMAL):
        try:
            if purpose != tia_openness.DOWNLOAD_PURPOSE_EXPERIMENT:
                raise BatchAbort(f"{ERROR_PHYSICAL_FORBIDDEN}: el batch solo descarga con purpose=experiment (recibido {purpose!r}).")
            assert_plcsim_only(project_root)
        except BatchAbort as error:
            GUARD_VIOLATIONS.append(str(error))
            raise
        return real_download(package_dir, root, purpose)

    return _download


# ---------------------------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------------------------

def _check(checks: list[dict[str, Any]], check_id: str, ok: bool, detail: str = "") -> bool:
    checks.append({"id": check_id, "ok": bool(ok), "detail": detail})
    return bool(ok)


def gui_instance_running() -> bool:
    """Una GUI abierta compartiria TIA/PLCSIM con el batch: se exige cerrarla."""
    import gui  # noqa: F401 - solo para el puerto

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", gui.GUI_INSTANCE_PORT))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def preflight(
    project_root: Path,
    live: bool = True,
    runtime_status_fn: Callable[[Path], dict[str, Any]] | None = None,
    tia_diagnostic_fn: Callable[[Path], dict[str, Any]] | None = None,
    llm_health_fn: Callable[[], dict[str, Any]] | None = None,
    gui_running_fn: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Todas las comprobaciones deben pasar; cualquier duda -> ready=False (ABORT)."""
    checks: list[dict[str, Any]] = []

    # -- diseno y benchmark
    design = ED.load_design(project_root)
    matrix = ED.baseline_matrix(project_root)
    _check(checks, "design_baseline_60", len(matrix) == 60 and design["baseline"]["trial_count"] == 60,
           f"{len(matrix)} ensayos en la matriz baseline")
    _check(checks, "design_baseline_scope", {c["case_id"] for c in matrix} == {f"D{i:02d}" for i in range(1, 21)}
           and {c["input_mode"] for c in matrix} == {"TEXT"} and {c["variant"] for c in matrix} == {"V1", "V2", "V3"},
           "D01-D20 x V1-V3 x TEXT")
    formal_errors = ED.validate_formal_matrix(ED.formal_design_matrix(project_root))
    _check(checks, "design_formal_288", not formal_errors, "; ".join(formal_errors) or "288")
    catalog = BC.load_catalog(project_root)
    _check(checks, "benchmark_version_2", catalog.get("benchmark_version") == 2, str(catalog.get("benchmark_version")))
    _check(checks, "benchmark_32_cases", len(catalog["cases"]) == 32, str(len(catalog["cases"])))
    consistency = BC.build_variant_consistency_report(project_root)
    _check(checks, "variants_96_consistent",
           consistency["total_variants"] == 96 and consistency["consistent_variants"] == 96 and not consistency["cases_with_errors"],
           f"{consistency['consistent_variants']}/{consistency['total_variants']}")

    # -- Oracles
    report = oracle_review.build_validation_report(project_root)
    summary = report["summary"]
    _check(checks, "oracles_32_frozen", summary.get("formal") == 32, f"{summary.get('formal')}/32 APPROVED/FROZEN")
    integrity = integrity_snapshot(project_root)
    frozen = [c for c, e in integrity["oracles"].items() if e["status"] == "FROZEN" and e["stored_hash"] == e["computed_hash"]]
    _check(checks, "oracles_hash_intact", len(frozen) == 32, f"{len(frozen)}/32 FROZEN con hash integro")
    _check(checks, "benchmark_inconsistencies_0", summary.get("benchmark_inconsistencies") == 0,
           str(summary.get("benchmark_inconsistencies")))
    _check(checks, "hidden_oracle_requirements_0", summary.get("hidden_oracle_requirements") == 0,
           str(summary.get("hidden_oracle_requirements")))
    from trial_experiments import oracle_runner

    # Ejecucion por CAPACIDADES (misma decision que el precheck y el Oracle Runner), no por runtime_support.
    not_executable = [c["case_id"] for c in matrix
                      if not oracle_runner.runtime_capability_check(S.load_oracle(project_root, c["case_id"]))["executable"]]
    _check(checks, "d01_d20_runtime_executable", not not_executable, ", ".join(sorted(set(not_executable))) or "20/20")

    # -- mapas
    missing_maps = [m for m in MAP_FILES if not (project_root / m).exists()]
    _check(checks, "maps_present", not missing_maps, ", ".join(missing_maps) or "4 mapas base")

    # -- seguridad (dos capas)
    try:
        assert_plcsim_only(project_root)
        _check(checks, "target_plcsim_only", True, "download_targets.experiment=PLCSIM_ADVANCED; physical_download=forbidden")
    except BatchAbort as error:
        _check(checks, "target_plcsim_only", False, str(error))
    _check(checks, "formal_not_allowed", not ED.check_formal_trial_allowed(project_root)[0],
           "software sin congelar: el baseline solo produce DEVELOPMENT_TRIAL")

    runtime: dict[str, Any] = {}
    if live:
        import tia_openness
        import plcsim_runtime
        from llm_client import PLCInterpretationLLMClient

        # El batch usa el pipeline INMEDIATO (compila en el proyecto Normal): desde la Fase 4A-DEFERRED
        # solo se permite con legacy_immediate_experiment_pipeline=true (herramienta secundaria).
        legacy = bool(tia_openness.load_tia_config(project_root).get("legacy_immediate_experiment_pipeline", False))
        _check(checks, "legacy_immediate_pipeline_enabled", legacy,
               "habilitado" if legacy else "deshabilitado: use GENERAR ENSAYO / EVALUAR ENSAYO GUARDADO (deferred_evaluator)")
        running = (gui_running_fn or gui_instance_running)()
        _check(checks, "gui_instance_closed", not running, "cerrar la GUI antes del batch" if running else "sin GUI abierta")

        diagnostic = (tia_diagnostic_fn or tia_openness.diagnose_tia_openness)(project_root)
        _check(checks, "tia_openness_ready", bool(diagnostic.get("is_ready")),
               "; ".join(diagnostic.get("warnings", [])) or diagnostic.get("project_path", ""))
        _check(checks, "tia_project_s71500", str(diagnostic.get("project_path", "")).endswith(".ap18"), diagnostic.get("project_path", ""))

        runtime = (runtime_status_fn or plcsim_runtime.get_plcsim_runtime_status)(project_root)
        config = plcsim_runtime.load_runtime_config(plcsim_runtime._load_tia_config(project_root))
        _check(checks, "plcsim_instance_connected", bool(runtime.get("connected")) and runtime.get("instance_name") == config["instance_name"],
               f"{runtime.get('status')} / {runtime.get('instance_name')}")
        cpu_type = str(runtime.get("cpu_type") or "")
        _check(checks, "plcsim_cpu_s71500", "1500" in cpu_type or "1516" in cpu_type or cpu_type.upper().startswith("CPU15"),
               cpu_type or "cpu_type no informado")
        _check(checks, "plcsim_network_match", runtime.get("network_match") is True, str(runtime.get("network_status")))

        health = (llm_health_fn or (lambda: PLCInterpretationLLMClient().health_check()))()
        # Nunca se registra la clave: solo si el cliente LLM del producto esta configurado.
        _check(checks, "llm_configured", bool(health.get("llm_configured")) and bool(health.get("model_configured")),
               f"provider={health.get('provider')} model_configured={health.get('model_configured')}")

    ready = all(check["ok"] for check in checks)
    return {
        "ready": ready,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "live": live,
        "checks": checks,
        "failed_checks": [check["id"] for check in checks if not check["ok"]],
        "integrity": integrity,
        "runtime": {k: runtime.get(k) for k in ("status", "instance_name", "cpu_state", "cpu_type", "controller_ip", "network_match")} if runtime else None,
    }


# ---------------------------------------------------------------------------------------------
# Cola persistente
# ---------------------------------------------------------------------------------------------

def baseline_dir(project_root: Path) -> Path:
    return trial_model.get_phase_results_dir(project_root, trial_model.PHASE_BASELINE)


def entry_id(cell: dict[str, Any]) -> str:
    return f"{cell['case_id']}_{cell['variant']}_{cell['input_mode']}"


def build_queue(project_root: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "baseline_id": ED.load_design(project_root)["baseline"]["id"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "entries": [{**cell, "entry_id": entry_id(cell), "status": ENTRY_PENDING, "attempts": []}
                    for cell in ED.baseline_matrix(project_root)],
    }


def queue_path(project_root: Path) -> Path:
    return baseline_dir(project_root) / QUEUE_FILENAME


def load_queue(project_root: Path) -> dict[str, Any]:
    path = queue_path(project_root)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    queue = build_queue(project_root)
    save_queue(project_root, queue)
    return queue


def save_queue(project_root: Path, queue: dict[str, Any]) -> None:
    path = queue_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def runnable_entries(queue: dict[str, Any], retry_infrastructure: bool = False) -> list[dict[str, Any]]:
    """PENDING siempre; INFRASTRUCTURE_ERROR solo con reintento tecnico explicito. COMPLETED nunca."""
    allowed = {ENTRY_PENDING} | ({ENTRY_INFRASTRUCTURE} if retry_infrastructure else set())
    return [entry for entry in queue["entries"] if entry["status"] in allowed]


def record_attempt(entry: dict[str, Any], record: dict[str, Any], trial_dir: Path | None, retry_reason: str | None) -> dict[str, Any]:
    classification = ED.classify_trial(record) if record.get("final_status") else {
        "failure_category": ED.INFRASTRUCTURE_ERROR, "infrastructure_error": True, "system_failure": False}
    attempt = {
        "attempt": len(entry["attempts"]) + 1,
        "trial_id": record.get("trial_id"),
        "trial_dir": str(trial_dir) if trial_dir else None,
        "final_status": record.get("final_status"),
        "failure_category": classification["failure_category"],
        "retry_reason": retry_reason,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    entry["attempts"].append(attempt)
    entry["status"] = ENTRY_INFRASTRUCTURE if classification["infrastructure_error"] else ENTRY_COMPLETED
    return attempt


# ---------------------------------------------------------------------------------------------
# Driver de la GUI (mismo pipeline que EJECUTAR ENSAYO)
# ---------------------------------------------------------------------------------------------

class _NoAnswerClarification:
    """Protocolo del baseline: nadie responde aclaraciones (queda clarification_requested)."""

    def __init__(self, _parent: Any, question: str) -> None:
        self.question = question
        self.result = None


class GuiTrialDriver:
    def __init__(self, project_root: Path, app: Any = None, log: Callable[[str], None] = print) -> None:
        import gui

        self.gui = gui
        self.project_root = project_root
        self.log = log
        self.dialogs: list[dict[str, str]] = []
        self._install_patches()
        self.app = app or gui.VozLLMPLCGUI()
        self.app.wait_window = lambda *args, **kwargs: None

    def _install_patches(self) -> None:
        gui = self.gui

        def _record(kind: str) -> Callable[..., Any]:
            def _dialog(title: str = "", message: str = "", *args: Any, **kwargs: Any) -> Any:
                self.dialogs.append({"kind": kind, "title": str(title), "message": str(message)[:500]})
                return False if kind in ("askyesno", "askokcancel") else None
            return _dialog

        for kind in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
            setattr(gui.messagebox, kind, _record(kind))
        gui.ClarificationDialog = _NoAnswerClarification
        gui.download_program_to_plc = guarded_download(gui.download_program_to_plc, self.project_root)
        # El registro de pruebas en docs/ no forma parte del experimento.
        gui.append_test_record_to_docs = lambda **kwargs: None

    def _workers_busy(self) -> bool:
        return any(bool(getattr(self.app, flag, False)) for flag in (
            "_tia_worker_active", "_download_worker_active", "_runtime_worker_active", "_oracle_worker_active", "_voice_worker_active"))

    def _pump(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.05)

    def configure(self, case_id: str, variant: str) -> str:
        app = self.app
        app.work_mode_var.set("Experimentacion")
        app._on_work_mode_changed()
        app.experiment_group_var.set("Discreto D01-D20")
        app._refresh_experiment_case_selector()
        label = next((name for name, profile in app._experiment_profiles_by_case.items() if profile.get("case_id") == case_id), None)
        if label is None:
            raise BatchAbort(f"No existe el perfil experimental de {case_id}.")
        app.experiment_case_var.set(label)
        app._on_experiment_case_changed()
        app.experiment_variant_var.set(variant)
        app._on_experiment_variant_changed()
        app.experiment_input_mode_var.set(self.gui.INPUT_MODE_LABELS[trial_model.INPUT_MODE_TEXT])
        app._on_experiment_input_mode_changed()
        app.experiment_phase_var.set(self.gui.EXPERIMENT_PHASE_LABELS[trial_model.PHASE_BASELINE])
        app.experiment_speaker_var.set(BATCH_SPEAKER_ID)
        app._use_variant_command()
        command_text = app.command_textbox.get("1.0", "end").strip()
        expected = BC.get_case(self.project_root, case_id)["variants"][variant]
        if command_text != expected:
            raise BatchAbort(f"El comando cargado para {case_id} {variant} no coincide con el catalogo canonico.")
        return command_text

    def run(self, case_id: str, variant: str, timeout_s: float = DEFAULT_TRIAL_TIMEOUT_S) -> tuple[dict[str, Any], Path | None]:
        if self._workers_busy():
            raise BatchAbort("Hay operaciones TIA/PLCSIM en curso antes de iniciar el ensayo.")
        self.configure(case_id, variant)
        self.dialogs.clear()
        app = self.app
        if not app.start_trial():
            directory = Path(app.active_trial["new_trial"]["dir"]) if (app.active_trial or {}).get("new_trial") else None
            record = trial_model.load_trial(directory) if directory else {}
            if directory and not record.get("final_status"):
                trial_model.finalize_trial(directory, trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR, [ERROR_START_FAILED])
                record = trial_model.load_trial(directory)
            return record or {"trial_id": None, "final_status": None, "errors": [ERROR_START_FAILED]}, directory
        directory = Path(app.active_trial["new_trial"]["dir"])
        app.execute_full_pipeline()
        deadline = time.monotonic() + timeout_s
        idle_since: float | None = None
        while time.monotonic() < deadline:
            app.update()
            record = trial_model.load_trial(directory)
            if record.get("final_status") and not self._workers_busy():
                self._pump(0.5)  # deja terminar los callbacks after() pendientes
                break
            if app.active_trial is None and not self._workers_busy() and not record.get("final_status"):
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since > 5:
                    trial_model.finalize_trial(directory, trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR,
                                               [ERROR_ABORTED_WITHOUT_STATUS] + [d["message"] for d in self.dialogs][:3])
                    break
            else:
                idle_since = None
            time.sleep(0.05)
        else:
            trial_model.finalize_trial(directory, trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR, [ERROR_TRIAL_TIMEOUT])
            trial_model.update_trial(directory, ED.classify_trial(trial_model.load_trial(directory)))
            raise BatchTrialTimeout(f"{ERROR_TRIAL_TIMEOUT}: {directory.name} supero {timeout_s:.0f} s (worker colgado).", directory)
        record = trial_model.load_trial(directory)
        classification = ED.classify_trial(record)
        trial_model.update_trial(directory, {**classification, "batch_dialogs": self.dialogs[:10]})
        app.active_trial = None
        return trial_model.load_trial(directory), directory


# ---------------------------------------------------------------------------------------------
# Ejecucion
# ---------------------------------------------------------------------------------------------

def run_baseline(
    project_root: Path,
    max_trials: int | None = None,
    retry_infrastructure: bool = False,
    retry_reason: str | None = None,
    driver: GuiTrialDriver | None = None,
    skip_live_preflight: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    if retry_infrastructure and not (retry_reason and retry_reason.strip()):
        raise BatchAbort("El reintento tecnico exige --retry-reason explicito.")
    check = preflight(project_root, live=not skip_live_preflight)
    out_dir = baseline_dir(project_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / PREFLIGHT_FILENAME).write_text(json.dumps(check, indent=2, ensure_ascii=False), encoding="utf-8")
    if not check["ready"]:
        raise BatchAbort("Preflight fallido: " + ", ".join(check["failed_checks"]))

    before = check["integrity"]
    queue = load_queue(project_root)
    pending = runnable_entries(queue, retry_infrastructure)
    if max_trials is not None:
        pending = pending[:max_trials]
    driver = driver or GuiTrialDriver(project_root, log=log)
    executed, consecutive_infra = 0, 0
    stop_reason = None
    for entry in pending:
        is_retry = entry["status"] == ENTRY_INFRASTRUCTURE
        log(f"[BATCH] {entry['entry_id']} (intento {len(entry['attempts']) + 1})")
        try:
            record, directory = driver.run(entry["case_id"], entry["variant"])
        except BatchTrialTimeout as error:
            # El intento colgado queda registrado (nunca huerfano fuera de la cola) y el batch se detiene.
            record_attempt(entry, trial_model.load_trial(error.directory), error.directory, retry_reason if is_retry else None)
            save_queue(project_root, queue)
            executed += 1
            stop_reason = str(error)
            break
        except BatchAbort as error:
            stop_reason = str(error)
            break
        if directory is not None:
            trial_model.update_trial(directory, {
                "attempt": len(entry["attempts"]) + 1,
                "retry_reason": retry_reason if is_retry else None,
                "batch_entry_id": entry["entry_id"],
            })
            record = trial_model.load_trial(directory)
        attempt = record_attempt(entry, record, directory, retry_reason if is_retry else None)
        queue["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_queue(project_root, queue)
        executed += 1
        log(f"[BATCH] {attempt['trial_id']}: {attempt['final_status']} ({attempt['failure_category']})")

        if GUARD_VIOLATIONS:
            stop_reason = "; ".join(GUARD_VIOLATIONS)
            break
        differences = integrity_differences(before, integrity_snapshot(project_root))
        if differences:
            stop_reason = "INTEGRITY_CHANGED: " + "; ".join(differences)
            break
        if (record.get("oracle") or {}).get("cleanup_success") is False:
            stop_reason = "PLCSIM_IO_CLEANUP_FAILED: entradas no restauradas; el siguiente ensayo quedaria contaminado."
            break
        consecutive_infra = consecutive_infra + 1 if entry["status"] == ENTRY_INFRASTRUCTURE else 0
        if consecutive_infra >= MAX_CONSECUTIVE_INFRA:
            stop_reason = f"{consecutive_infra} INFRASTRUCTURE_ERROR consecutivos: se detiene el batch para revisar el entorno."
            break
    outputs = write_outputs(project_root, queue)
    return {"executed": executed, "stop_reason": stop_reason, "outputs": outputs,
            "remaining": len(runnable_entries(queue)), "integrity_after": integrity_differences(before, integrity_snapshot(project_root))}


# ---------------------------------------------------------------------------------------------
# Reportes
# ---------------------------------------------------------------------------------------------

CSV_FIELDS = (
    "trial_id", "attempt", "retry_reason", "case_id", "variant", "input_mode", "domain", "complexity", "logic_family",
    "trial_kind", "experiment_phase", "benchmark_version", "canonical_case_hash", "variant_hash",
    "oracle_id", "oracle_version", "oracle_hash", "reference_command_text", "command_text",
    "semantic_success", "clarification_requested", "verification_success", "compile_success", "download_success",
    "runtime_connection_success", "functional_success", "safety_success", "final_status", "failure_category",
    "infrastructure_error", "semantic_ms", "generation_ms", "compile_ms", "download_ms", "runtime_ms", "oracle_ms",
    "total_ms", "parser_mode", "model_provider", "model", "git_commit", "trial_dir", "errors",
)


def _trial_row(record: dict[str, Any], attempt: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    stages = record.get("stages") or {}
    timing = record.get("timing") or {}
    oracle = record.get("oracle_reference") or {}
    classification = ED.classify_trial(record) if record.get("final_status") else {
        "failure_category": ED.INFRASTRUCTURE_ERROR, "infrastructure_error": True}
    return {
        "trial_id": record.get("trial_id") or attempt.get("trial_id"),
        "attempt": attempt.get("attempt"),
        "retry_reason": attempt.get("retry_reason"),
        "case_id": case["case_id"],
        "variant": record.get("variant_id"),
        "input_mode": record.get("input_mode"),
        "domain": record.get("domain"),
        "complexity": case.get("complexity"),
        "logic_family": case.get("reference_intent"),
        "trial_kind": record.get("trial_kind"),
        "experiment_phase": record.get("experiment_phase"),
        "benchmark_version": record.get("benchmark_version"),
        "canonical_case_hash": record.get("canonical_case_hash"),
        "variant_hash": record.get("variant_hash"),
        "oracle_id": oracle.get("oracle_id"),
        "oracle_version": oracle.get("oracle_version"),
        "oracle_hash": oracle.get("oracle_hash"),
        "reference_command_text": record.get("reference_command_text"),
        "command_text": record.get("command_text"),
        "semantic_success": stages.get("semantic_success"),
        "clarification_requested": record.get("clarification_requested"),
        "verification_success": stages.get("verification_success"),
        "compile_success": stages.get("compile_success"),
        "download_success": stages.get("download_success"),
        "runtime_connection_success": stages.get("runtime_connection_success"),
        "functional_success": stages.get("functional_success"),
        "safety_success": stages.get("safety_success"),
        "final_status": record.get("final_status"),
        "failure_category": classification["failure_category"],
        "infrastructure_error": classification["infrastructure_error"],
        **{key: timing.get(key) for key in ("semantic_ms", "generation_ms", "compile_ms", "download_ms", "runtime_ms", "oracle_ms", "total_ms")},
        "parser_mode": record.get("parser_mode"),
        "model_provider": (record.get("model") or {}).get("provider"),
        "model": (record.get("model") or {}).get("model"),
        "git_commit": record.get("git_commit"),
        "trial_dir": attempt.get("trial_dir"),
        "errors": " | ".join(str(e) for e in (record.get("errors") or [])[:3]),
    }


def collect_rows(project_root: Path, queue: dict[str, Any]) -> list[dict[str, Any]]:
    cases = BC.cases_by_id(project_root)
    rows = []
    for entry in queue["entries"]:
        for attempt in entry["attempts"]:
            directory = Path(attempt["trial_dir"]) if attempt.get("trial_dir") else None
            record = trial_model.load_trial(directory) if directory else {}
            rows.append(_trial_row(record, attempt, cases[entry["case_id"]]))
    return rows


def _rate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    evaluated = [row for row in rows if row.get(key) is not None]
    passed = sum(1 for row in evaluated if row[key] is True)
    return {"passed": passed, "evaluated": len(evaluated), "rate": round(passed / len(evaluated), 4) if evaluated else None}


def _group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if not row["infrastructure_error"]]
    latencies = [row["total_ms"] for row in valid if isinstance(row.get("total_ms"), (int, float))]
    return {
        "trials": len(rows),
        "valid_trials": len(valid),
        "infrastructure_errors": len(rows) - len(valid),
        "final_status": dict(Counter(row["final_status"] for row in rows)),
        "failure_category": dict(Counter(row["failure_category"] for row in rows)),
        "semantic_success": _rate(valid, "semantic_success"),
        "compile_success": _rate(valid, "compile_success"),
        "functional_success": _rate(valid, "functional_success"),
        "safety_violations": sum(1 for row in valid if row.get("safety_success") is False),
        "pass": sum(1 for row in valid if row["final_status"] == "PASS"),
        "clarifications": sum(1 for row in rows if row.get("clarification_requested")),
        "total_ms_median": statistics.median(latencies) if latencies else None,
        "total_ms_mean": round(statistics.mean(latencies), 1) if latencies else None,
    }


def build_summary(project_root: Path, queue: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    final_rows = []
    for entry in queue["entries"]:  # ultimo intento de cada celda (los anteriores quedan en el CSV)
        attempts = [row for row in rows if row["case_id"] == entry["case_id"] and row["variant"] == entry["variant"]]
        if attempts:
            final_rows.append(attempts[-1])

    def by(key: str) -> dict[str, Any]:
        return {value: _group_summary([row for row in final_rows if row.get(key) == value])
                for value in sorted({str(row.get(key)) for row in final_rows})}

    return {
        "baseline_id": queue.get("baseline_id"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "note": "DEVELOPMENT_TRIAL / BASELINE: fotografia del sistema actual. Excluido de las estadisticas formales.",
        "planned_trials": len(queue["entries"]),
        "executed_cells": len(final_rows),
        "total_attempts": len(rows),
        "pending_cells": sum(1 for entry in queue["entries"] if entry["status"] == ENTRY_PENDING),
        "overall": _group_summary(final_rows),
        "by_case": by("case_id"),
        "by_variant": by("variant"),
        "by_complexity": by("complexity"),
        "by_logic_family": by("logic_family"),
    }


def build_summary_markdown(summary: dict[str, Any]) -> str:
    overall = summary["overall"]

    def pct(block: dict[str, Any]) -> str:
        return "-" if block["rate"] is None else f"{block['passed']}/{block['evaluated']} ({block['rate'] * 100:.1f} %)"

    lines = [
        "# Baseline de desarrollo v2 (D01-D20 x V1-V3 x TEXT)",
        "",
        f"> {summary['note']}",
        "",
        f"- Generado: {summary['generated_at']}",
        f"- Celdas planificadas: {summary['planned_trials']} · ejecutadas: {summary['executed_cells']} · pendientes: {summary['pending_cells']} · intentos totales: {summary['total_attempts']}",
        f"- Validos (sin infraestructura): {overall['valid_trials']} · INFRASTRUCTURE_ERROR: {overall['infrastructure_errors']}",
        f"- Semantic Success: {pct(overall['semantic_success'])}",
        f"- Compilation Success: {pct(overall['compile_success'])}",
        f"- Functional Success: {pct(overall['functional_success'])}",
        f"- Safety violations: {overall['safety_violations']}",
        f"- PASS: {overall['pass']} · aclaraciones solicitadas: {overall['clarifications']}",
        f"- Latencia extremo a extremo (mediana): {overall['total_ms_median']} ms",
        "",
        "## Por caso",
        "",
        "| Caso | Ensayos | PASS | Categorias |",
        "|---|---|---|---|",
    ]
    for case_id, block in summary["by_case"].items():
        lines.append(f"| {case_id} | {block['trials']} | {block['pass']} | {', '.join(f'{k}: {v}' for k, v in block['failure_category'].items())} |")
    for title, key in (("Por variante", "by_variant"), ("Por complejidad", "by_complexity"), ("Por familia logica", "by_logic_family")):
        lines += ["", f"## {title}", "", "| Grupo | Ensayos | PASS | Functional | Semantic |", "|---|---|---|---|---|"]
        for group, block in summary[key].items():
            lines.append(f"| {group} | {block['trials']} | {block['pass']} | {pct(block['functional_success'])} | {pct(block['semantic_success'])} |")
    return "\n".join(lines) + "\n"


def build_gap_validation(project_root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = json.loads((project_root / "data" / "system_capability_gaps.json").read_text(encoding="utf-8"))
    predicted = {gap["case_id"]: gap for gap in gaps.get("generator_gaps", [])}
    cases = []
    for case_id in [f"D{i:02d}" for i in range(1, 21)]:
        case_rows = [row for row in rows if row["case_id"] == case_id]
        valid = [row for row in case_rows if not row["infrastructure_error"] and row["final_status"] in ("PASS", "FAIL")]
        failures = [row for row in valid if row["final_status"] == "FAIL"]
        if not valid:
            status = "inconclusive"
        elif case_id in predicted:
            status = "confirmed" if len(failures) == len(valid) else ("partially_confirmed" if failures else "not_confirmed")
        else:
            status = "no_gap_predicted" if not failures else "unexpected_failure"
        stages = Counter(row["failure_category"] for row in failures)
        cases.append({
            "case_id": case_id,
            "static_gap_predicted": case_id in predicted,
            "gap_id": (predicted.get(case_id) or {}).get("gap_id"),
            "real_trials": len(case_rows),
            "valid_trials": len(valid),
            "status": status,
            "failure_stage": stages.most_common(1)[0][0] if stages else None,
            "failure_stages": dict(stages),
            "evidence_trial_ids": [row["trial_id"] for row in case_rows],
            "notes": "; ".join(sorted({row["errors"] for row in failures if row.get("errors")}))[:600] or None,
        })
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "note": "Validacion REAL de los SYSTEM_CAPABILITY_GAP del generador con el baseline D (TEXT). Los gaps NO se corrigen en esta fase.",
        "summary": dict(Counter(case["status"] for case in cases)),
        "cases": cases,
    }


def write_outputs(project_root: Path, queue: dict[str, Any]) -> dict[str, str]:
    out_dir = baseline_dir(project_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = collect_rows(project_root, queue)
    with (out_dir / TRIALS_CSV).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = build_summary(project_root, queue, rows)
    (out_dir / SUMMARY_JSON).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / SUMMARY_MD).write_text(build_summary_markdown(summary), encoding="utf-8")
    failures = [row for row in rows if row["final_status"] != "PASS"]
    (out_dir / FAILURES_JSON).write_text(json.dumps(failures, indent=2, ensure_ascii=False), encoding="utf-8")
    gap_path = project_root / GAP_VALIDATION_RELATIVE
    if rows:
        gap_path.write_text(json.dumps(build_gap_validation(project_root, rows), indent=2, ensure_ascii=False), encoding="utf-8")
    return {"csv": str(out_dir / TRIALS_CSV), "summary_json": str(out_dir / SUMMARY_JSON), "summary_md": str(out_dir / SUMMARY_MD),
            "failures": str(out_dir / FAILURES_JSON), "gap_validation": str(gap_path) if rows else None}


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Baseline de desarrollo v2 (D01-D20 x V1-V3 x TEXT)")
    parser.add_argument("--preflight", action="store_true", help="Solo comprobar el entorno (no ejecuta ensayos).")
    parser.add_argument("--run", action="store_true", help="Ejecutar/reanudar la cola.")
    parser.add_argument("--report", action="store_true", help="Regenerar los reportes desde la cola.")
    parser.add_argument("--max", type=int, default=None, help="Maximo de ensayos en esta sesion.")
    parser.add_argument("--retry-infrastructure", action="store_true", help="Reintento tecnico de INFRASTRUCTURE_ERROR.")
    parser.add_argument("--retry-reason", default=None)
    args = parser.parse_args(argv)

    from utils import get_project_root

    root = get_project_root()
    if args.preflight:
        result = preflight(root)
        print(json.dumps({k: v for k, v in result.items() if k != "integrity"}, indent=2, ensure_ascii=False))
        return 0 if result["ready"] else 2
    if args.report:
        print(json.dumps(write_outputs(root, load_queue(root)), indent=2, ensure_ascii=False))
        return 0
    if args.run:
        try:
            result = run_baseline(root, max_trials=args.max, retry_infrastructure=args.retry_infrastructure, retry_reason=args.retry_reason)
        except BatchAbort as error:
            print(f"[BATCH] ABORT: {error}")
            return 2
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if not result["stop_reason"] else 3
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
