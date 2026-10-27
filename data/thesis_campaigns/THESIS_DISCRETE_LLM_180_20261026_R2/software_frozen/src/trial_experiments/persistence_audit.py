"""
Auditoria READ-ONLY de ensayos cuya evaluacion termino (Oracle + evaluation_report.json) pero cuyo
resultado NO llego a trial.json (p.ej. una excepcion de limpieza del workspace TIA antes de persistir:
evaluation.status = RUNNING, attempts = [], final_verdict = null).

Esta herramienta:
  * NUNCA escribe, mueve ni borra nada (ni trial.json, ni evidencias, ni workspaces, ni el registro tiaw/);
  * NUNCA genera SCL, llama al LLM, abre TIA/PLCSIM ni vuelve a ejecutar el Oracle;
  * solo lee las evidencias del intento y dice si el resultado ORIGINAL puede reconstruirse, mostrando
    (sin aplicarlo) el registro que se reconstruiria.

Uso (desde la raiz del proyecto):
  python scripts/audit_trial_persistence.py D03_V1_TEXT_DEV_001 D03_V2_TEXT_DEV_001
  python scripts/audit_trial_persistence.py --trial-dir <carpeta_del_ensayo> [--json]

La reparacion (aplicar el registro reconstruido) NO forma parte de esta herramienta: exige una
autorizacion explicita aparte, respaldo previo de trial.json y registro de cada cambio
(docs/deferred_trial_workflow.md, "Recuperacion de persistencia").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from trial_experiments import deferred_evaluator as DE
from trial_experiments import oracle_runner
from trial_experiments import tia_workspace as TW
from trial_experiments import trial_model

AUDIT_SCHEMA_VERSION = 1

VERDICT_RECONSTRUCTIBLE = "RECONSTRUCTIBLE"          # evidencia completa y coherente: el veredicto original es recuperable
VERDICT_ALREADY_PERSISTED = "ALREADY_PERSISTED"      # trial.json ya tiene el resultado de ese intento: nada que recuperar
VERDICT_NOT_RECONSTRUCTIBLE = "NOT_RECONSTRUCTIBLE"  # falta o no cuadra alguna evidencia obligatoria
VERDICT_NO_ORPHAN_ATTEMPT = "NO_ORPHAN_ATTEMPT"      # no hay intento en disco sin registrar

_ATTEMPT_DIR = re.compile(r"^attempt_(\d{3})$")
_EXPERIMENTAL_VERDICTS = (trial_model.FINAL_STATUS_PASS, trial_model.FINAL_STATUS_FAIL, trial_model.FINAL_STATUS_REVIEW,
                          trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(TW.fs_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> tuple[Any, str | None]:
    """(contenido, error). Nunca lanza: un JSON ilegible es un hallazgo, no un fallo de la auditoria."""
    if not Path(path).is_file():
        return None, "falta"
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except (OSError, ValueError) as error:
        return None, f"ilegible: {error}"


def find_trial_dirs(project_root: Path, trial_id: str) -> list[Path]:
    """Carpetas results/<fase>/<caso>/<variante>/<trial_id> (solo lectura)."""
    results = Path(project_root) / trial_model.RESULTS_DIRNAME
    if not results.is_dir():
        return []
    return sorted(path.parent for path in results.glob(f"*/*/*/{trial_id}/{trial_model.TRIAL_FILENAME}"))


def _attempt_dirs(trial_dir: Path) -> dict[int, Path]:
    base = Path(trial_dir) / DE.EVALUATION_DIRNAME
    found: dict[int, Path] = {}
    if base.is_dir():
        for child in base.iterdir():
            match = _ATTEMPT_DIR.match(child.name)
            if child.is_dir() and match:
                found[int(match.group(1))] = child
    return dict(sorted(found.items()))


class _Checks:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, check_id: str, ok: bool | None, detail: str = "", required: bool = True) -> bool | None:
        self.items.append({"id": check_id, "ok": ok, "required": required, "detail": detail})
        return ok

    @property
    def failed_required(self) -> list[str]:
        return [item["id"] for item in self.items if item["required"] and item["ok"] is not True]


def audit_attempt(project_root: Path, trial_dir: Path, record: dict[str, Any], manifest: dict[str, Any] | None,
                  attempt_number: int, attempt_dir: Path) -> dict[str, Any]:
    """Verifica la evidencia de UN intento y, si es coherente, devuelve el resultado original reconstruido."""
    checks = _Checks()
    trial_id = record.get("trial_id")
    report, report_error = _read(attempt_dir / oracle_runner.EVALUATION_REPORT_FILENAME)
    checks.add("evaluation_report_present", report is not None, report_error or str(attempt_dir / oracle_runner.EVALUATION_REPORT_FILENAME))
    report = report or {}
    checks.add("evaluation_report_trial_id", report.get("trial_id") == trial_id, f"{report.get('trial_id')} vs {trial_id}")
    for key in ("case_id", "variant_id", "input_mode"):
        checks.add(f"evaluation_report_{key}", report.get(key) == record.get(key), f"{report.get(key)} vs {record.get(key)}")
    final_status = report.get("final_status")
    checks.add("evaluation_report_final_status", final_status in _EXPERIMENTAL_VERDICTS, str(final_status))
    oracle_verdict = report.get("oracle_verdict")
    checks.add("oracle_verdict_present", oracle_verdict is not None, str(oracle_verdict))
    trace_present = (attempt_dir / oracle_runner.ORACLE_TRACE_FILENAME).is_file()
    checks.add("oracle_trace_present", trace_present, oracle_runner.ORACLE_TRACE_FILENAME)

    oracle_ref = (manifest or {}).get("oracle") or {}
    report_oracle = report.get("oracle") or {}
    if report_oracle.get("oracle_hash") is not None:
        checks.add("oracle_hash_matches_generation", report_oracle.get("oracle_hash") == oracle_ref.get("oracle_hash"),
                   f"{report_oracle.get('oracle_hash')} vs {oracle_ref.get('oracle_hash')}")
    else:
        checks.add("oracle_hash_matches_generation", None, "el informe no registra oracle_hash (no verificable)", required=False)

    tia_manifest, tia_error = _read(attempt_dir / DE.TIA_DIRNAME / DE.TIA_PROJECT_MANIFEST)
    checks.add("tia_project_manifest_present", tia_manifest is not None, tia_error or "")
    tia_manifest = tia_manifest or {}
    checks.add("tia_manifest_trial_id", tia_manifest.get("trial_id") == trial_id, f"{tia_manifest.get('trial_id')} vs {trial_id}")
    checks.add("tia_manifest_attempt", tia_manifest.get("attempt_number") == attempt_number,
               f"{tia_manifest.get('attempt_number')} vs {attempt_number}")
    program_hash = ((manifest or {}).get("files") or {}).get(DE.PROGRAM_FILENAME)
    checks.add("generated_scl_hash_matches_manifest", tia_manifest.get("generated_scl_hash") == program_hash,
               f"{tia_manifest.get('generated_scl_hash')} vs {program_hash}")
    checks.add("imported_scl_hash_matches_manifest", tia_manifest.get("imported_scl_hash") == program_hash,
               f"{tia_manifest.get('imported_scl_hash')} vs {program_hash}")

    archive = tia_manifest.get("archive") or {}
    zap_path = attempt_dir / DE.TIA_DIRNAME / f"{trial_id}{DE.ZAP_EXTENSION}"
    zap_hash = _sha256(zap_path) if zap_path.is_file() else None
    checks.add("zap18_present", zap_hash is not None, str(zap_path))
    checks.add("zap18_hash_matches_manifest", zap_hash is not None and zap_hash == archive.get("evidence_hash") == archive.get("workspace_hash"),
               f"{zap_hash} vs {archive.get('evidence_hash')}")

    master = tia_manifest.get("master") or {}
    master_intact = (master.get("master_hash_after") == tia_manifest.get("master_snapshot_hash")
                     and master.get("master_folder_fingerprint") == master.get("master_folder_fingerprint_after"))
    checks.add("master_intact_during_attempt", master_intact, "snapshot y carpeta del MASTER sin cambios")

    compile_report, compile_error = _read(attempt_dir / DE.COMPILE_REPORT)
    checks.add("compile_report_present", compile_report is not None, compile_error or "")
    compile_category = (tia_manifest.get("compile_classification") or {}).get("category")
    download_report, download_error = _read(attempt_dir / DE.DOWNLOAD_REPORT)
    runtime_report, runtime_error = _read(attempt_dir / DE.RUNTIME_REPORT)
    download_ok = bool((download_report or {}).get("download_success")) if download_report is not None else None
    cpu_run = (bool((runtime_report or {}).get("connected")) and (runtime_report or {}).get("cpu_state") == "RUN") if runtime_report is not None else None
    # Un veredicto del Oracle exige compilacion, descarga y CPU en RUN: si falta alguna, el informe no cuadra.
    checks.add("download_report_success", download_ok is True, download_error or str(download_ok))
    checks.add("runtime_cpu_run", cpu_run is True, runtime_error or str(cpu_run))

    evaluation = record.get("evaluation") or {}
    workspace_id = tia_manifest.get("tia_workspace_id")
    checks.add("workspace_id_matches_trial_record", workspace_id is not None and workspace_id == evaluation.get("tia_workspace_id"),
               f"{workspace_id} vs {evaluation.get('tia_workspace_id')}")
    registry_entry = (TW.load_registry(project_root)["workspaces"].get(workspace_id) or {}) if workspace_id else {}
    registry_ok = (registry_entry.get("trial_id") == trial_id and registry_entry.get("attempt") == attempt_number) if registry_entry else None
    checks.add("workspace_registry_identity", registry_ok,
               f"registro: trial_id={registry_entry.get('trial_id')} attempt={registry_entry.get('attempt')} "
               f"state={registry_entry.get('state')} (informativo: puede pertenecer a otra PC)", required=False)
    workspace_path = Path(str((tia_manifest.get("workspace") or {}).get("path") or ""))

    reconstructible = not checks.failed_required
    reconstructed = None
    if reconstructible:
        reconstructed = {
            "final_verdict": final_status,
            "oracle_verdict": oracle_verdict,
            "oracle_verdict_reason": report.get("oracle_verdict_reason"),
            "attempt_summary": {
                "attempt": attempt_number,
                "attempt_dir": str(attempt_dir),
                "tia_workspace_id": workspace_id,
                "tia_workspace_path": str(workspace_path) if str(workspace_path) not in ("", ".") else None,
                "tia_workspace_cleaned": False,
                "started_at": evaluation.get("started_at"),
                "completed_at": None,  # no se persistio: nunca se inventa
                "final_status": final_status,
                "compile": compile_category,
                "tia_archive": "CREATED",
                "evidence_copied_ok": True,
                "download_success": download_ok,
                "cpu_run": cpu_run,
                "oracle_verdict": oracle_verdict,
                "master_intact": master_intact,
                "workspace_cleanup": {"status": "FAILED", "error_type": None, "error_message": "no registrado (incidente historico)",
                                      "workspace_path": str(workspace_path) if str(workspace_path) not in ("", ".") else None,
                                      "timestamp": None},
                "recovered_from_evidence": True,
            },
            "timing": {"compile_ms": (compile_report or {}).get("duration_ms"), "runtime_ms": (runtime_report or {}).get("duration_ms"),
                       "oracle_ms": (report.get("timings") or {}).get("oracle_ms"), "evaluation_ms": None},
            "evidence": {"evaluation_report": str(attempt_dir / oracle_runner.EVALUATION_REPORT_FILENAME),
                         "evaluation_report_sha256": _sha256(attempt_dir / oracle_runner.EVALUATION_REPORT_FILENAME),
                         "zap18_path": str(zap_path), "zap18_hash": zap_hash},
            "missing_fields": ["completed_at", "evaluation_ms", "workspace_cleanup.error_type"],
        }
    return {"attempt": attempt_number, "attempt_dir": str(attempt_dir), "checks": checks.items,
            "failed_required": checks.failed_required, "reconstructible": reconstructible, "reconstructed": reconstructed}


def audit_trial(project_root: Path, trial_dir: Path) -> dict[str, Any]:
    """Auditoria completa de un ensayo (solo lectura)."""
    trial_dir = Path(trial_dir)
    record, record_error = _read(trial_dir / trial_model.TRIAL_FILENAME)
    result: dict[str, Any] = {"audit_schema_version": AUDIT_SCHEMA_VERSION, "trial_dir": str(trial_dir), "read_only": True}
    if not isinstance(record, dict):
        return {**result, "verdict": VERDICT_NOT_RECONSTRUCTIBLE, "errors": [f"trial.json {record_error or 'invalido'}"]}
    identity = _Checks()
    trial_id = record.get("trial_id")
    identity.add("trial_id_matches_folder", trial_id == trial_dir.name, f"{trial_id} vs {trial_dir.name}")
    identity.add("case_variant_match_path", (record.get("case_id"), record.get("variant_id")) == (trial_dir.parent.parent.name, trial_dir.parent.name),
                 f"{record.get('case_id')}/{record.get('variant_id')} vs {trial_dir.parent.parent.name}/{trial_dir.parent.name}")
    integrity = DE.verify_trial_integrity(trial_dir)  # solo lee y recalcula hashes
    identity.add("frozen_artifacts_integrity", integrity["ok"], "; ".join(integrity["errors"]) or "hashes congelados OK")
    evaluation = record.get("evaluation") or {}
    persisted = list(evaluation.get("attempts") or [])
    on_disk = _attempt_dirs(trial_dir)
    orphans = {number: path for number, path in on_disk.items() if number > len(persisted)}
    result.update({
        "trial_id": trial_id,
        "case_id": record.get("case_id"),
        "variant_id": record.get("variant_id"),
        "persisted_state": {"evaluation_status": evaluation.get("status"), "attempts_persisted": len(persisted),
                            "final_verdict": record.get("final_verdict"), "final_status": record.get("final_status"),
                            "lifecycle_state": record.get("lifecycle_state")},
        "attempt_dirs_on_disk": [path.name for path in on_disk.values()],
        "orphan_attempts": [path.name for path in orphans.values()],
        "identity_checks": identity.items,
    })
    if identity.failed_required:
        return {**result, "verdict": VERDICT_NOT_RECONSTRUCTIBLE, "errors": identity.failed_required}
    if not orphans:
        verdict = VERDICT_ALREADY_PERSISTED if record.get("final_verdict") or evaluation.get("final_verdict") else VERDICT_NO_ORPHAN_ATTEMPT
        return {**result, "verdict": verdict}
    expected = len(persisted) + 1
    if sorted(orphans) != list(range(expected, expected + len(orphans))):
        return {**result, "verdict": VERDICT_NOT_RECONSTRUCTIBLE, "errors": [f"intentos sin registrar no consecutivos: {sorted(orphans)}"]}
    audits = [audit_attempt(Path(project_root), trial_dir, record, integrity.get("manifest"), number, path) for number, path in orphans.items()]
    result["attempt_audits"] = audits
    # Solo el ULTIMO intento sin registrar puede ser el resultado vigente; los anteriores se conservan como historia.
    last = audits[-1]
    result["verdict"] = VERDICT_RECONSTRUCTIBLE if (evaluation.get("status") == "RUNNING" and last["reconstructible"]) else VERDICT_NOT_RECONSTRUCTIBLE
    if evaluation.get("status") != "RUNNING":
        result["errors"] = [f"evaluation.status={evaluation.get('status')} (se esperaba RUNNING para un resultado no persistido)"]
    return result


def summary_lines(audit: dict[str, Any]) -> list[str]:
    lines = [f"== {audit.get('trial_id') or audit['trial_dir']}: {audit['verdict']}",
             f"   persistido: {audit.get('persisted_state')}",
             f"   intentos en disco: {audit.get('attempt_dirs_on_disk')}  sin registrar: {audit.get('orphan_attempts')}"]
    for check in audit.get("identity_checks") or []:
        lines.append(f"   [{'OK' if check['ok'] else ('--' if check['ok'] is None else 'FAIL')}] {check['id']}: {check['detail']}")
    for attempt in audit.get("attempt_audits") or []:
        lines.append(f"   -- {Path(attempt['attempt_dir']).name}: {'RECONSTRUCTIBLE' if attempt['reconstructible'] else 'NO RECONSTRUCTIBLE'}")
        for check in attempt["checks"]:
            mark = "OK" if check["ok"] else ("--" if check["ok"] is None else ("FAIL" if check["required"] else "WARN"))
            lines.append(f"      [{mark}] {check['id']}: {check['detail']}")
        if attempt["reconstructed"]:
            lines.append(f"      veredicto Oracle original: {attempt['reconstructed']['oracle_verdict']} -> "
                         f"FINAL {attempt['reconstructed']['final_verdict']}")
    for error in audit.get("errors") or []:
        lines.append(f"   ! {error}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auditoria READ-ONLY de persistencia de ensayos evaluados")
    parser.add_argument("trial_ids", nargs="*", help="trial_id a buscar bajo results/ (p.ej. D03_V1_TEXT_DEV_001).")
    parser.add_argument("--trial-dir", action="append", default=[], help="Carpeta del ensayo (repetible).")
    parser.add_argument("--project-root", default=None, help="Raiz del proyecto (por defecto, la del repositorio).")
    parser.add_argument("--json", action="store_true", help="Salida JSON completa (incluye el registro reconstruido).")
    args = parser.parse_args(argv)
    root = Path(args.project_root) if args.project_root else Path(__file__).resolve().parents[2]
    targets: list[Path] = [Path(path) for path in args.trial_dir]
    missing: list[str] = []
    for trial_id in args.trial_ids:
        found = find_trial_dirs(root, trial_id)
        targets.extend(found)
        if not found:
            missing.append(trial_id)
    if not targets and not missing:
        parser.print_help()
        return 1
    audits = [audit_trial(root, target) for target in targets]
    if args.json:
        print(json.dumps({"audits": audits, "not_found": missing}, indent=2, ensure_ascii=False, default=str))
    else:
        for audit in audits:
            print("\n".join(summary_lines(audit)))
        for trial_id in missing:
            print(f"== {trial_id}: NO ENCONTRADO bajo {root / trial_model.RESULTS_DIRNAME}")
    return 0 if audits and all(a["verdict"] in (VERDICT_RECONSTRUCTIBLE, VERDICT_ALREADY_PERSISTED) for a in audits) and not missing else 2


if __name__ == "__main__":
    sys.exit(main())
