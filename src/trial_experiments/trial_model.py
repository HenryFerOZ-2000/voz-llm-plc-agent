"""
Nuevo modelo de ensayo experimental (Fase 1).

Reemplaza progresivamente al modelo legacy (TRIAL_000NNN + experiment_label con condicion
C1-C4, ver trial_store.py) sin eliminarlo. Disenado desde ya para que las fases futuras (Runtime
API, Oracle Runner, Functional/Safety Success, ficha automatica, exportacion CSV/XLSX/tablas)
solo tengan que RELLENAR campos que hoy quedan en null, nunca renombrar identificadores ni
cambiar el formato:

  - trial_id oficial: <case>_<variant>_<input_mode>_<NNN>  (p.ej. D12_V2_TEXT_001). No incluye
    el modo de parser (rules/llm/hybrid): la arquitectura de la tesis es LLM; los otros modos
    siguen existiendo en el software solo para depuracion.
  - estados por etapa separados (nunca un unico success booleano);
  - final_status en {PREPARED, PASS, FAIL, REVIEW, INFRASTRUCTURE_ERROR}. En Fase 1 un ensayo
    que llega a PLCSIM queda PREPARED; PASS solo existira con el Oracle Runner.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

TRIAL_SCHEMA_VERSION = 1

INPUT_MODE_TEXT = "TEXT"
INPUT_MODE_VOICE_CLEAN = "VOICE_CLEAN"
INPUT_MODE_VOICE_NOISE = "VOICE_NOISE"
INPUT_MODES = (INPUT_MODE_TEXT, INPUT_MODE_VOICE_CLEAN, INPUT_MODE_VOICE_NOISE)

FINAL_STATUS_PREPARED = "PREPARED"
FINAL_STATUS_PASS = "PASS"
FINAL_STATUS_FAIL = "FAIL"
FINAL_STATUS_REVIEW = "REVIEW"
FINAL_STATUS_INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
FINAL_STATUSES = (
    FINAL_STATUS_PREPARED,
    FINAL_STATUS_PASS,
    FINAL_STATUS_FAIL,
    FINAL_STATUS_REVIEW,
    FINAL_STATUS_INFRASTRUCTURE_ERROR
)

# Etapas evaluadas hoy (Fase 1) y etapas futuras, siempre presentes en trial.json como null
# hasta que se evaluen de verdad - nunca se marcan como exitosas por adelantado.
PHASE1_STAGES = ("semantic_success", "verification_success", "compile_success", "download_success", "start_module_success")
FUTURE_STAGES = ("runtime_connection_success", "functional_success", "safety_success")

COMPLEXITY_MAP = {"baja": "LOW", "media": "MEDIUM", "alta": "HIGH", "low": "LOW", "medium": "MEDIUM", "high": "HIGH"}

RESULTS_DIRNAME = "results"
EXPERIMENTS_DIRNAME = "experiments"
TRIAL_FILENAME = "trial.json"

# Diseno experimental v2 (data/experimental_design.json): el tipo de ensayo lo decide la FASE de
# la sesion, nunca el estado del Oracle. FORMAL_TRIAL exige ademas el software congelado.
TRIAL_KIND_DEVELOPMENT = "DEVELOPMENT_TRIAL"
TRIAL_KIND_FORMAL = "FORMAL_TRIAL"
PHASE_BASELINE = "BASELINE"
PHASE_DEVELOPMENT = "DEVELOPMENT_VALIDATION"
PHASE_FORMAL = "FORMAL"
EXPERIMENT_PHASES = (PHASE_BASELINE, PHASE_DEVELOPMENT, PHASE_FORMAL)
PHASE_DIRNAMES = {
    PHASE_BASELINE: "development_baseline_v2",
    PHASE_DEVELOPMENT: "development_validation_v2",
    PHASE_FORMAL: EXPERIMENTS_DIRNAME,
}

_CASE_PATTERN = re.compile(r"^[DP]\d{2}$")
_VARIANT_PATTERN = re.compile(r"^V\d+$")


def normalize_complexity(raw: Any) -> str | None:
    if raw is None:
        return None
    return COMPLEXITY_MAP.get(str(raw).strip().lower())


def input_mode_from_selection(requires_voice: bool, noise_level: str) -> str:
    """Traduce la seleccion actual de la GUI (voz si/no + nivel de ruido) al input_mode oficial."""
    if not requires_voice:
        return INPUT_MODE_TEXT
    return INPUT_MODE_VOICE_CLEAN if str(noise_level or "none") == "none" else INPUT_MODE_VOICE_NOISE


def trial_kind_for_phase(phase: str) -> str:
    if phase not in EXPERIMENT_PHASES:
        raise ValueError(f"experiment_phase invalida: {phase!r} (esperado uno de {EXPERIMENT_PHASES}).")
    return TRIAL_KIND_FORMAL if phase == PHASE_FORMAL else TRIAL_KIND_DEVELOPMENT


def build_trial_id(case_id: str, variant_id: str, input_mode: str, trial_number: int, development: bool = False) -> str:
    if not _CASE_PATTERN.match(case_id or ""):
        raise ValueError(f"case_id invalido: {case_id!r} (esperado D01-D20 o P01-P12).")
    if not _VARIANT_PATTERN.match(variant_id or ""):
        raise ValueError(f"variant_id invalido: {variant_id!r} (esperado V1, V2, ...).")
    if input_mode not in INPUT_MODES:
        raise ValueError(f"input_mode invalido: {input_mode!r} (esperado uno de {INPUT_MODES}).")
    if trial_number < 1:
        raise ValueError("trial_number debe ser >= 1.")
    # Nunca incluye el modo de parser (RULES/LLM/HYBRID). DEV marca los ensayos de desarrollo.
    return f"{case_id}_{variant_id}_{input_mode}_{'DEV_' if development else ''}{trial_number:03d}"


def get_results_experiments_dir(project_root: Path) -> Path:
    return project_root / RESULTS_DIRNAME / EXPERIMENTS_DIRNAME


def get_phase_results_dir(project_root: Path, phase: str = PHASE_FORMAL) -> Path:
    """results/experiments (FORMAL) o results/development_*_v2 (desarrollo): nunca se mezclan."""
    trial_kind_for_phase(phase)
    return get_results_experiments_dir(project_root).parent / PHASE_DIRNAMES[phase]


def trial_directory(project_root: Path, case_id: str, variant_id: str, trial_id: str, phase: str = PHASE_FORMAL) -> Path:
    return get_phase_results_dir(project_root, phase) / case_id / variant_id / trial_id


def next_trial_number(project_root: Path, case_id: str, variant_id: str, input_mode: str, phase: str = PHASE_FORMAL) -> int:
    """Siguiente numero a partir de los directorios ya existentes (nunca un contador aparte)."""
    variant_dir = get_phase_results_dir(project_root, phase) / case_id / variant_id
    development = trial_kind_for_phase(phase) == TRIAL_KIND_DEVELOPMENT
    prefix = f"{case_id}_{variant_id}_{input_mode}_{'DEV_' if development else ''}"
    numbers = [0]
    if variant_dir.exists():
        for child in variant_dir.iterdir():
            if child.is_dir() and child.name.startswith(prefix):
                suffix = child.name[len(prefix):]
                if suffix.isdigit():
                    numbers.append(int(suffix))
    return max(numbers) + 1


def new_trial_record(
    case_id: str,
    variant_id: str,
    input_mode: str,
    trial_number: int,
    command_text: str = "",
    complexity: str | None = None,
    extra: dict[str, Any] | None = None,
    phase: str = PHASE_FORMAL
) -> dict[str, Any]:
    trial_kind = trial_kind_for_phase(phase)
    trial_id = build_trial_id(case_id, variant_id, input_mode, trial_number, development=trial_kind == TRIAL_KIND_DEVELOPMENT)
    record: dict[str, Any] = {
        "schema_version": TRIAL_SCHEMA_VERSION,
        "trial_id": trial_id,
        "case_id": case_id,
        "variant_id": variant_id,
        "input_mode": input_mode,
        "trial_number": trial_number,
        "experiment_family": "PID" if case_id.startswith("P") else "DISCRETE",
        "domain": "PID_SUPERVISOR" if case_id.startswith("P") else "DISCRETE",
        "complexity": normalize_complexity(complexity),
        "command_text": command_text,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "semantic": {},
        "io": {},
        "verification": {},
        "compile": {},
        "download": {},
        # Working I/O map del ensayo (trial_io_map.py): referencia al mapa base, a la copia de
        # trabajo (descartada al terminar) y al snapshot congelado que usan IR/SCL/TIA/Runtime.
        "io_map": {
            "base_map_id": None,
            "base_source_hash": None,
            "base_map_hash": None,
            "physical_channel_count": None,
            "working_map_path": None,
            "snapshot_path": None,
            "frozen": False,
            "created_at": None,
            "resolved_at": None,
            "bound_channels": None,
            "discarded": None,
            "error": None
        },
        # Fase interna (CREATED -> PREPARING -> IO_RESOLVED -> COMPILED -> DOWNLOADED ->
        # RUNTIME_READY ...). Coexiste con final_status; decide si el mapa del ensayo es mutable.
        "lifecycle_state": "CREATED",
        # Diseno v2: lo decide la fase de la sesion (BASELINE / DEVELOPMENT_VALIDATION -> DEVELOPMENT_TRIAL;
        # FORMAL -> FORMAL_TRIAL, solo con software_freeze_manifest valido). Nunca el Oracle.
        "trial_kind": trial_kind,
        "experiment_phase": phase,
        "attempt": 1,
        "retry_reason": None,
        "reference_command_text": None,
        "generated_code_id": None,
        # Metadata tecnica (no es factor experimental ni forma parte del trial_id).
        "parser_mode": None,
        "model": {"provider": None, "model": None},
        # Voz (VOICE_CLEAN / VOICE_NOISE); en TEXT quedan null. Protocolo de ruido pendiente.
        "asr": {"audio_reference": None, "asr_transcript": None, "wer": None, "noise_profile": None, "snr_db": None},
        "clarification_requested": False,
        "failure_category": None,
        "failure_stage": None,
        "infrastructure_error": None,
        "final_verdict": None,
        "git_commit": None,
        # Benchmark v2: que comando exacto se uso (los ensayos sin benchmark_version son del
        # benchmark legacy v1 y cuentan como DEVELOPMENT_TRIAL).
        "benchmark_version": None,
        "canonical_case_hash": None,
        "variant_hash": None,
        "runtime": None,
        # Diagnostico de infraestructura Runtime I/O (Fase 2B); nunca una metrica cientifica.
        "runtime_io": None,
        "oracle": None,
        "oracle_reference": {"oracle_id": None, "oracle_version": None, "oracle_hash": None},
        "functional": None,
        "safety": None,
        "stages": {name: None for name in PHASE1_STAGES + FUTURE_STAGES},
        "timing": {
            "generation_ms": None,
            "compile_ms": None,
            "download_ms": None,
            "functional_test_ms": None,
            "end_to_end_ms": None,
            "semantic_ms": None,
            "runtime_ms": None,
            "oracle_ms": None,
            "total_ms": None
        },
        "errors": [],
        "final_status": None,
        "completed_at": None
    }
    if extra:
        record.update(extra)
    return record


# os.replace sobre trial.json puede fallar un instante en Windows si otro hilo/proceso lo esta leyendo.
_REPLACE_RETRY_DELAYS_S = (0.05, 0.2, 0.5, 1.0)


def save_trial(directory: Path, record: dict[str, Any]) -> Path:
    """Escritura ATOMICA (temporal + os.replace): nunca deja un trial.json a medio escribir."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / TRIAL_FILENAME
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    for delay in _REPLACE_RETRY_DELAYS_S + (None,):
        try:
            os.replace(temporary, path)
            return path
        except PermissionError:
            if delay is None:
                raise
            time.sleep(delay)
    return path


def load_trial(directory: Path) -> dict[str, Any]:
    path = directory / TRIAL_FILENAME
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def update_trial(directory: Path, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge 1 nivel: los dicts de seccion (stages, timing, semantic, ...) se fusionan, no se pisan."""
    record = merge_patch(load_trial(directory), patch)
    save_trial(directory, record)
    return record


def merge_patch(record: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge 1 nivel en memoria (misma regla que update_trial), para persistir varios cambios en UNA escritura."""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(record.get(key), dict):
            record[key] = {**record[key], **value}
        else:
            record[key] = value
    return record


def finalize_trial(directory: Path, final_status: str, errors: list[str] | None = None) -> dict[str, Any]:
    if final_status not in FINAL_STATUSES:
        raise ValueError(f"final_status invalido: {final_status!r}")
    record = load_trial(directory)
    record["final_status"] = final_status
    record["completed_at"] = datetime.now().isoformat(timespec="seconds")
    if errors:
        record["errors"] = list(record.get("errors", [])) + [str(error) for error in errors]
    save_trial(directory, record)
    return record


def copy_package_artifacts(directory: Path, package_dir: Path | None) -> list[str]:
    """
    Copia al directorio del ensayo la evidencia tecnica del paquete (seccion 14). Solo lo que
    existe; nunca inventa archivos vacios. siemens_source.scl se guarda como program.scl.
    """
    copied: list[str] = []
    if package_dir is None or not package_dir.exists():
        return copied
    directory.mkdir(parents=True, exist_ok=True)
    for source_name, target_name in (
        ("variables.json", "variables.json"),
        ("siemens_source.scl", "program.scl"),
        ("tia_compile_report.json", "tia_compile_report.json"),
        ("tia_download_report.json", "tia_download_report.json")
    ):
        source = package_dir / source_name
        if source.exists():
            shutil.copyfile(source, directory / target_name)
            copied.append(target_name)
    return copied


def write_text_artifact(directory: Path, filename: str, content: str) -> None:
    if content is None or not str(content).strip():
        return
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(str(content), encoding="utf-8")


def write_json_artifact(directory: Path, filename: str, payload: Any) -> None:
    if payload is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
