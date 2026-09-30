"""
Fase 3B: herramientas de REVISION de los Oracles (no de ejecucion).

  - build_validation_report(): una entrada por Oracle (schema, hash, roles, secuencia, cleanup,
    runtime, review_items, capability gaps) -> oracle_validation_report.json;
  - build_summary_markdown(): resumen humano breve por caso -> docs/oracle_review_summary.md;
  - approve_all_without_review_items(): aprobacion MASIVA asistida, solo de Oracles en borrador,
    validos y sin review_items abiertos, con confirmacion explicita del investigador.

La aprobacion formal siempre la firma el investigador (approved_by); nunca una IA.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from trial_experiments import benchmark_catalog as BC
from trial_experiments import oracle_schema as S

EXPECTED_ORACLE_IDS = [f"D{i:02d}" for i in range(1, 21)] + [f"P{i:02d}" for i in range(1, 13)]
VALIDATION_REPORT_FILENAME = "oracle_validation_report.json"
CAPABILITY_GAPS_FILENAME = "system_capability_gaps.json"
SUMMARY_RELATIVE_PATH = Path("docs") / "oracle_review_summary.md"
MASS_APPROVAL_CONFIRMATION = "Confirmo que he revisado conceptualmente estos Oracles."


def list_oracle_ids(project_root: Path) -> list[str]:
    present = {path.stem for path in S.get_oracles_dir(project_root).glob("*.json")}
    return [case_id for case_id in EXPECTED_ORACLE_IDS if case_id in present] + sorted(present - set(EXPECTED_ORACLE_IDS))


def _load_raw(project_root: Path, case_id: str) -> dict[str, Any] | None:
    path = S.oracle_path(project_root, case_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _all_steps(oracle: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(section, step) for section in ("preconditions", "test_sequence", "cleanup") for step in oracle.get(section) or []]


def _check_roles_and_sequence(oracle: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """(errores de roles, errores de secuencia/cleanup, avisos)."""
    role_errors: list[str] = []
    sequence_errors: list[str] = []
    warnings: list[str] = []
    roles = oracle.get("roles") or {}
    used: set[str] = set()
    for _, step in _all_steps(oracle):
        used |= set(step.get("set") or {}) | set(step.get("expect") or {})
        for window in step.get("expect_timeline") or []:
            used |= set(window.get("expect") or {})
        if step.get("measure_transition"):
            used.add(step["measure_transition"]["role"])
    for invariant in oracle.get("invariants") or []:
        used |= set(invariant.get("roles") or [])
    for name, role in roles.items():
        if name not in used:
            role_errors.append(f"Rol {name} declarado pero nunca usado en pasos ni invariantes.")
        if role.get("kind") == "OUTPUT" and not any(
            name in (step.get("expect") or {}) or any(name in (w.get("expect") or {}) for w in step.get("expect_timeline") or [])
            for _, step in _all_steps(oracle)
        ) and not any(name in (inv.get("roles") or []) for inv in oracle.get("invariants") or []):
            warnings.append(f"Salida {name} nunca se evalua (solo aparece como no especificada).")
        for _, step in _all_steps(oracle):
            if role.get("kind") == "INPUT" and name in (step.get("expect") or {}):
                warnings.append(f"{step['id']} espera un valor de la ENTRADA {name} (normalmente se esperan salidas).")

    # Cleanup: toda entrada que la prueba pueda dejar activa/modificada vuelve a su valor neutro.
    touched: dict[str, tuple[Any, list[str]]] = {}
    for section, step in _all_steps(oracle):
        if section == "cleanup":
            continue
        for role, value in (step.get("set") or {}).items():
            if value is not False:
                touched[role] = (value, list(step.get("requires_roles") or []))
    cleaned = {role for _, step in [(s, st) for s, st in _all_steps(oracle) if s == "cleanup"] for role in (step.get("set") or {})}
    for role in sorted(touched):
        if role not in cleaned:
            sequence_errors.append(f"Cleanup no devuelve la entrada {role} a su estado neutro.")
    for _, step in [(s, st) for s, st in _all_steps(oracle) if s == "cleanup"]:
        for role, value in (step.get("set") or {}).items():
            if S.role_data_type(roles.get(role, {})) == "BOOL" and value is True and not step["id"].startswith("cleanup_reset") \
                    and role not in ("STOP", "RESET"):
                warnings.append(f"Cleanup deja {role}=TRUE en {step['id']}.")
    if not oracle.get("preconditions"):
        warnings.append("Sin precondiciones: el estado inicial depende del reinicio tras la descarga.")

    return role_errors, sequence_errors, warnings


def validate_one(project_root: Path, case_id: str) -> dict[str, Any]:
    oracle = _load_raw(project_root, case_id)
    if oracle is None:
        return {"case_id": case_id, "schema_valid": False, "errors": ["No se pudo leer el Oracle."], "warnings": [],
                "roles_valid": False, "sequence_valid": False, "review_items": [], "runtime_executable": False}
    schema_errors = S.validate_oracle(oracle)
    approval = oracle.get("approval") or {}
    hash_valid = approval.get("hash") == S.compute_oracle_hash(oracle) if S.is_formal(oracle) else approval.get("hash") is None
    role_errors, sequence_errors, warnings = _check_roles_and_sequence(oracle) if not schema_errors else ([], [], [])
    versions_dir = S.get_oracles_dir(project_root) / S.VERSIONS_DIRNAME
    open_items = S.open_review_items(oracle)
    errors = schema_errors + role_errors + sequence_errors + ([] if hash_valid else ["Hash de aprobacion invalido."])
    case = BC.get_case(project_root, case_id)
    alignment = BC.canonical_alignment(case, oracle) if case and not schema_errors else None
    if case is None:
        errors.append("El caso no existe en el catalogo canonico.")
    elif alignment and (alignment["extra_oracle_requirements"] or alignment["missing_oracle_requirements"]):
        errors.append("Oracle desalineado con el comando canonico (requisitos ocultos o no cubiertos).")
    return {
        "case_id": case_id,
        "title": oracle.get("title"),
        "complexity": oracle.get("complexity"),
        "version": approval.get("version"),
        "status": approval.get("status"),
        "hash": S.compute_oracle_hash(oracle),
        "schema_valid": not schema_errors,
        "hash_valid": hash_valid,
        "roles_valid": not schema_errors and not role_errors,
        "sequence_valid": not schema_errors and not sequence_errors,
        "runtime_support": S.runtime_support(oracle),
        "runtime_executable": S.runtime_support(oracle) == S.RUNTIME_EXECUTABLE_NOW,
        "runtime_requirements": S.derived_runtime_requirements(oracle),
        "review_items": [{"id": item.get("id"), "text": item.get("text")} for item in open_items],
        "resolved_review_items": [item.get("id") for item in oracle.get("review_items") or [] if item.get("status") != "OPEN"],
        "system_capability_gaps": oracle.get("system_capability_gaps") or [],
        "experimental_conventions": [item.get("id") for item in oracle.get("experimental_conventions") or []],
        "archived_versions": sorted(p.name for p in versions_dir.glob(f"{case_id}_v*.json")) if versions_dir.exists() else [],
        "ai_review": approval.get("ai_review"),
        "canonical_command": (case or {}).get("canonical_command"),
        "canonical_alignment": alignment,
        "warnings": warnings,
        "errors": errors,
    }


def build_validation_report(project_root: Path) -> dict[str, Any]:
    ids = list_oracle_ids(project_root)
    entries = [validate_one(project_root, case_id) for case_id in ids]
    discrete = [e for e in entries if e["case_id"].startswith("D")]
    pid = [e for e in entries if e["case_id"].startswith("P")]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "total_oracles": len(entries),
            "schema_valid": sum(1 for e in entries if e["schema_valid"]),
            "without_review_items": sum(1 for e in entries if not e["review_items"]),
            "with_review_items": sum(1 for e in entries if e["review_items"]),
            "open_review_items": sum(len(e["review_items"]) for e in entries),
            "executable_now": sum(1 for e in entries if e["runtime_executable"]),
            "discrete_executable": f"{sum(1 for e in discrete if e['runtime_executable'])}/{len(discrete)}",
            "pid_executable": f"{sum(1 for e in pid if e['runtime_executable'])}/{len(pid)}",
            "requires_runtime_extension": sum(1 for e in entries if not e["runtime_executable"]),
            "capability_gaps": sum(len(e["system_capability_gaps"]) for e in entries),
            "benchmark_version": BC.load_catalog(project_root).get("benchmark_version"),
            "benchmark_inconsistencies": len(BC.benchmark_inconsistencies(
                project_root, {e["case_id"]: _load_raw(project_root, e["case_id"]) for e in entries})),
            "oracles_aligned": sum(1 for e in entries if e["canonical_alignment"] and not e["canonical_alignment"]["extra_oracle_requirements"]
                                   and not e["canonical_alignment"]["missing_oracle_requirements"]),
            "hidden_oracle_requirements": sum(len((e["canonical_alignment"] or {}).get("extra_oracle_requirements", [])) for e in entries),
            "formal": sum(1 for e in entries if e["status"] in S.FORMAL_STATUSES),
            "ready_for_human_approval": [e["case_id"] for e in entries
                                         if e["status"] not in S.FORMAL_STATUSES and not e["review_items"] and not e["errors"]],
        },
        "expected_ids": EXPECTED_ORACLE_IDS,
        "missing_ids": [case_id for case_id in EXPECTED_ORACLE_IDS if case_id not in ids],
        "total": len(entries),
        "schema_valid": sum(1 for e in entries if e["schema_valid"]),
        "without_review_items": [e["case_id"] for e in entries if not e["review_items"]],
        "with_review_items": [e["case_id"] for e in entries if e["review_items"]],
        "executable_now": [e["case_id"] for e in entries if e["runtime_executable"]],
        "requires_runtime_extension": [e["case_id"] for e in entries if not e["runtime_executable"]],
        "system_capability_gaps": {e["case_id"]: e["system_capability_gaps"] for e in entries if e["system_capability_gaps"]},
        "oracles": entries,
    }


def build_capability_gaps_report(project_root: Path) -> dict[str, Any]:
    """Entrada para la siguiente fase de desarrollo del core (los gaps NO se corrigen aqui)."""
    report = build_validation_report(project_root)
    gaps = []
    for entry in report["oracles"]:
        for item in entry["system_capability_gaps"]:
            gaps.append({
                "case_id": entry["case_id"],
                "gap_id": item.get("id"),
                "expected_capability": item.get("expected_capability"),
                "current_behavior": item.get("current_behavior") or item.get("text"),
                "severity": item.get("severity", "HIGH"),
                "recommended_future_fix": item.get("recommended_future_fix"),
            })
    runtime = [{
        "case_id": entry["case_id"],
        "required": entry["runtime_requirements"],
        "current_behavior": "El Runtime I/O solo ejecuta BOOL de entradas/salidas fisicas; no REAL ni variables internas.",
        "severity": "HIGH",
        "recommended_future_fix": "Extender el bridge a REAL/INT y a lectura/escritura de variables internas bajo una politica de seguridad "
                                  "explicita (escribir Level_PV/Auto_Mode no es escribir una entrada fisica).",
    } for entry in report["oracles"] if not entry["runtime_executable"]]
    return {
        "generated_at": report["generated_at"],
        "note": "SYSTEM_CAPABILITY_GAP: el Oracle define la evaluacion; estos gaps describen lo que el generador actual no produce. "
                "No se corrigen en la fase de Oracles.",
        "total_generator_gaps": len(gaps),
        "by_severity": {level: sum(1 for g in gaps if g["severity"] == level) for level in ("HIGH", "MEDIUM", "LOW")},
        "generator_gaps": gaps,
        "runtime_gaps": runtime,
    }


def write_capability_gaps_report(project_root: Path, path: Path | None = None) -> Path:
    path = path or (S.get_oracles_dir(project_root).parent / CAPABILITY_GAPS_FILENAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_capability_gaps_report(project_root), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_validation_report(project_root: Path, report: dict[str, Any], path: Path | None = None) -> Path:
    path = path or (S.get_oracles_dir(project_root).parent / VALIDATION_REPORT_FILENAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------
# Resumen humano
# ---------------------------------------------------------------------------------------------

def _fmt_values(values: dict[str, Any]) -> str:
    parts = []
    for role, value in values.items():
        if isinstance(value, bool):
            parts.append(f"{role}={'ON' if value else 'OFF'}")
        elif isinstance(value, dict) and "approx" in value:
            parts.append(f"{role}~{value['approx']}")
        elif isinstance(value, dict):
            parts.append(f"{role} en [{value.get('min')}, {value.get('max')}]")
        else:
            parts.append(f"{role}={value}")
    return ", ".join(parts)


def _main_test(oracle: dict[str, Any]) -> list[str]:
    lines = []
    for step in oracle.get("test_sequence") or []:
        guard = f" (si existe {', '.join(step['requires_roles'])})" if step.get("requires_roles") else ""
        action = _fmt_values(step.get("set") or {}) or "espera"
        outcome = _fmt_values(step.get("expect") or {}) or ("no especificado: " + ", ".join(step.get("unspecified") or []) if step.get("unspecified") else "-")
        timeline = ""
        if step.get("measure_transition"):
            t = step["measure_transition"]
            timeline = f" [transicion {t['role']} a {t['nominal_ms']} ms, -{t['tolerance_ms']['early']}/+{t['tolerance_ms']['late']} ms]"
        lines.append(f"{action} -> {outcome}{timeline}{guard}")
    return lines


def build_summary_markdown(project_root: Path) -> str:
    report = build_validation_report(project_root)
    summary = report["summary"]
    out = [
        "# Revision de Oracles (D01-D20, P01-P12)",
        "",
        f"Generado: {report['generated_at']}. Fuente: `data/experiment_oracles/*.json` "
        "(la especificacion formal es el JSON; este resumen solo facilita la revision).",
        "",
        f"- Oracles: {summary['total_oracles']} · schema valid {summary['schema_valid']}/{summary['total_oracles']} · "
        f"review items abiertos {summary['open_review_items']} · discretos ejecutables {summary['discrete_executable']} · "
        f"PID ejecutables {summary['pid_executable']} · capability gaps {summary['capability_gaps']}",
        f"- Listos para aprobacion humana: {', '.join(summary['ready_for_human_approval']) or 'ninguno'}",
        f"- Sin review items abiertos: {len(report['without_review_items'])} - {', '.join(report['without_review_items'])}",
        f"- Con review items abiertos: {len(report['with_review_items'])} - {', '.join(report['with_review_items'])}",
        f"- Ejecutables hoy: {', '.join(report['executable_now'])}",
        f"- Requieren extension del Runtime: {', '.join(report['requires_runtime_extension'])}",
        "",
        "Estados: `DRAFT_REVIEWED` = revisado por IA (schema + revision semantica), SIN aprobacion formal. "
        "`FROZEN` = aprobado por el investigador.",
        "",
    ]
    for entry in report["oracles"]:
        oracle = _load_raw(project_root, entry["case_id"]) or {}
        roles = oracle.get("roles") or {}
        role_text = ", ".join(
            f"{name} ({role['kind'][0]}{'' if role.get('required', True) else ', opcional'}"
            f"{', ' + role.get('data_type') if role.get('data_type', 'BOOL') != 'BOOL' else ''})" for name, role in roles.items())
        critical = [f"{inv['id']}: {inv.get('description', inv['type'])}" for inv in oracle.get("invariants") or []
                    if inv.get("severity", "CRITICAL") == "CRITICAL"]
        out += [
            f"## {entry['case_id']} - {oracle.get('title', '').split(' - ', 1)[-1]}",
            "",
            f"- **Estado:** {entry['status']} v{entry['version']} · complejidad {entry['complexity']} · hash `{entry['hash'][:12]}`",
            f"- **Objetivo original:** {_original_requirement(oracle)}",
            f"- **Comando canonico:** {entry.get('canonical_command') or '-'}",
            f"- **Comportamiento evaluado:** {oracle.get('description')}",
            f"- **Roles:** {role_text}",
            "- **Prueba principal:**",
            *[f"  {i}. {line}" for i, line in enumerate(_main_test(oracle), 1)],
            f"- **Condicion de exito:** {(oracle.get('evaluation') or {}).get('functional_rule', '-')}",
            f"- **Invariante critica:** {'; '.join(critical) if critical else 'ninguna'}",
            f"- **Runtime:** {entry['runtime_support']} ({', '.join(entry['runtime_requirements'])})",
            "- **Convenciones experimentales (para hacerlo medible):**" + ("" if _conventions(oracle) else " ninguna"),
            *[f"  - {item['id']}: {item['text']}" for item in _conventions(oracle)],
            f"- **Review items:** " + ("ninguno abierto" if not entry["review_items"] else ""),
            *[f"  - {item['id']}: {item['text']}" for item in entry["review_items"]],
            *([f"- **SYSTEM_CAPABILITY_GAP ({g.get('severity', 'HIGH')}):** {g.get('current_behavior') or g.get('text')}"
               for g in entry["system_capability_gaps"]]),
            *([f"- **Aviso:** {w}" for w in entry["warnings"] if w.startswith("BENCHMARK_DATA_INCONSISTENCY")]),
            "",
        ]
    return "\n".join(out)


def _original_requirement(oracle: dict[str, Any]) -> str:
    """REQUISITO ORIGINAL (convencion REQ-ORIGINAL si existe; si no, la definicion oficial del caso)."""
    for item in oracle.get("experimental_conventions") or []:
        if item.get("id") == "REQ-ORIGINAL":
            return item["text"].replace("REQUISITO ORIGINAL: ", "")
    source = oracle.get("source_definition") or {}
    return source.get("official_definition") or source.get("description") or oracle.get("description", "-")


def _conventions(oracle: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in oracle.get("experimental_conventions") or [] if item.get("id") not in ("REQ-ORIGINAL", "CMD-CANONICAL")]


def write_summary_markdown(project_root: Path, path: Path | None = None) -> Path:
    path = path or (project_root / SUMMARY_RELATIVE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_summary_markdown(project_root), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------
# Aprobacion masiva asistida
# ---------------------------------------------------------------------------------------------

def approve_all_without_review_items(project_root: Path, approved_by: str, confirmation: str) -> dict[str, list[str]]:
    """
    Aprueba (FROZEN) todos los Oracles en borrador, validos y SIN review_items abiertos. Los que
    tienen review_items abiertos NUNCA se aprueban en masa (se aprueban uno a uno).
    """
    if confirmation != MASS_APPROVAL_CONFIRMATION:
        raise ValueError(f"Se requiere la confirmacion explicita: {MASS_APPROVAL_CONFIRMATION!r}")
    if not str(approved_by or "").strip():
        raise ValueError("approved_by es obligatorio.")
    outcome: dict[str, list[str]] = {"approved": [], "already_formal": [], "skipped_review_items": [], "invalid": []}
    for case_id in list_oracle_ids(project_root):
        entry = validate_one(project_root, case_id)
        if entry["status"] in S.FORMAL_STATUSES:
            outcome["already_formal"].append(case_id)
        elif entry["errors"]:
            outcome["invalid"].append(case_id)
        elif entry["review_items"]:
            outcome["skipped_review_items"].append(case_id)
        else:
            S.approve_oracle(project_root, case_id, approved_by)
            outcome["approved"].append(case_id)
    return outcome
