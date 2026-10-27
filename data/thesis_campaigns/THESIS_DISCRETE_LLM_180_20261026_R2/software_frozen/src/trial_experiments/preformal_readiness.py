"""
Auditoria de preparacion pre-FORMAL (READ-ONLY: sin LLM, sin TIA, sin PLCSIM, sin escribir ensayos).

Para cada caso D01-D20 / P01-P12 del benchmark vigente responde si es EVALUABLE: si el experimento puede
ejecutarse completo y un FAIL sera atribuible al sistema bajo prueba, no a una capacidad inexistente conocida.
"Evaluable" NO significa que vaya a dar PASS con el LLM.

Comprobaciones por caso (todas con codigo de produccion; ver reference_pipeline):
  - oracle_frozen            Oracle FROZEN con hash integro;
  - semantic_capability      la interpretacion de referencia (data/preformal/reference_interpretations.json, nunca
                             enviada al LLM) pasa reparacion + semantica efectiva + validacion: intent con plantilla y
                             requisitos del catalogo, sin conflictos;
  - functional_requirements  todos los requisitos de la interpretacion son de catalogo y tienen generacion;
  - map_resources            config/experiment_maps.json selecciona un mapa con recursos suficientes (y cual);
  - generation               IR + SCL Siemens + verificador + validacion de composicion (lo que se importaria en TIA);
  - oracle_roles             todos los roles del Oracle se resuelven contra el snapshot/variables del programa;
  - runtime_capabilities     el Runtime actual cubre las capacidades que exige el Oracle;
  - reference_behavior       el SCL generado, simulado contra el Oracle congelado (scl_sim), da PASS: la capacidad
                             existe y produce el comportamiento especificado.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from trial_experiments import benchmark_catalog as BC
from trial_experiments import oracle_schema
from trial_experiments import reference_pipeline as RP

REFERENCE_INTERPRETATIONS = Path("data") / "preformal" / "reference_interpretations.json"
REPORT_JSON = Path("data") / "preformal_readiness_report.json"
REPORT_MD = Path("docs") / "preformal_readiness_report.md"
CHECK_KEYS = ("oracle_frozen", "semantic_capability", "functional_requirements", "map_resources", "generation",
              "oracle_roles", "runtime_capabilities", "reference_behavior")


def load_reference_interpretations(project_root: Path) -> dict[str, Any]:
    return json.loads((Path(project_root) / REFERENCE_INTERPRETATIONS).read_text(encoding="utf-8"))["interpretations"]


def _stage_ok(result: dict[str, Any], name: str) -> bool | None:
    stage = (result.get("stages") or {}).get(name)
    return None if stage is None else bool(stage.get("success"))


def audit_case(project_root: Path, case_id: str, interpretation: dict[str, Any] | None) -> dict[str, Any]:
    from functional_requirements import CLASS_CATALOG, canonical_requirement_type, classify_functional_requirement

    project_root = Path(project_root)
    case = BC.get_case(project_root, case_id)
    checks: dict[str, dict[str, Any]] = {}
    try:
        oracle = oracle_schema.load_oracle(project_root, case_id)
        frozen = oracle_schema.is_formal(oracle) and oracle["approval"].get("hash") == oracle_schema.compute_oracle_hash(oracle)
        checks["oracle_frozen"] = {"ok": frozen, "detail": f"{oracle['approval']['status']} v{oracle['approval']['version']}"}
    except Exception as error:  # noqa: BLE001
        checks["oracle_frozen"] = {"ok": False, "detail": str(error)}
    if interpretation is None:
        for key in CHECK_KEYS[1:]:
            checks[key] = {"ok": False, "detail": "sin interpretacion de referencia"}
        return _summarize(case_id, case, checks, None)

    requirements = interpretation.get("functional_requirements") or []
    unsupported = [r.get("type") for r in requirements
                   if classify_functional_requirement({**r, "type": canonical_requirement_type(r.get("type"))}) != CLASS_CATALOG]
    checks["functional_requirements"] = {"ok": not unsupported,
                                         "detail": {"types": [r.get("type") for r in requirements], "unsupported": unsupported}}
    result = RP.run_reference(project_root, case_id, interpretation, case["canonical_command"])
    stages = result.get("stages") or {}
    checks["map_resources"] = {"ok": _stage_ok(result, "map_selection") is True, "detail": result.get("map")}
    checks["semantic_capability"] = {"ok": _stage_ok(result, "semantic") is True,
                                     "detail": (stages.get("semantic") or {}).get("detail")}
    generation_ok = _stage_ok(result, "generation") is True and _stage_ok(result, "io_allocation") is True
    checks["generation"] = {"ok": generation_ok, "detail": (stages.get("generation") or {}).get("detail") or result.get("errors")}
    checks["oracle_roles"] = {"ok": result.get("roles") == "RESOLVED", "detail": result.get("role_issues") or result.get("roles")}
    checks["runtime_capabilities"] = {"ok": _stage_ok(result, "runtime_capabilities") is True,
                                      "detail": (stages.get("runtime_capabilities") or {}).get("detail")}
    checks["reference_behavior"] = {"ok": result.get("verdict") == "PASS",
                                    "detail": {"verdict": result.get("verdict"), "reason": result.get("verdict_reason"),
                                               "failed_checks": result.get("functional_failed_checks"),
                                               "safety_violations": result.get("safety_violations"),
                                               "timing": result.get("timing_checks")}}
    return _summarize(case_id, case, checks, result)


def _summarize(case_id: str, case: dict[str, Any], checks: dict[str, dict[str, Any]], result: dict[str, Any] | None) -> dict[str, Any]:
    failed = [key for key in CHECK_KEYS if not (checks.get(key) or {}).get("ok")]
    return {
        "case_id": case_id,
        "title": case.get("title"),
        "evaluable": not failed,
        "known_gaps": failed,
        "map": (result or {}).get("map"),
        "checks": checks,
        "errors": (result or {}).get("errors") or [],
    }


def run_audit(project_root: Path, case_ids: list[str] | None = None) -> dict[str, Any]:
    project_root = Path(project_root)
    references = load_reference_interpretations(project_root)
    catalog = BC.load_catalog(project_root)
    cases = [audit_case(project_root, case_id, references.get(case_id)) for case_id in (case_ids or BC.CASE_IDS)]
    evaluable = sum(1 for case in cases if case["evaluable"])
    return {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "benchmark_version": catalog.get("benchmark_version"),
        "mode": "READ_ONLY (sin LLM, sin TIA, sin PLCSIM; SCL generado simulado contra los Oracles congelados)",
        "evaluable": evaluable,
        "total": len(cases),
        "all_evaluable": evaluable == len(cases),
        "not_evaluable": [case["case_id"] for case in cases if not case["evaluable"]],
        "simulation_map_cases": [case["case_id"] for case in cases if (case.get("map") or {}).get("simulation_only")],
        "cases": cases,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Auditoria de preparacion pre-FORMAL",
        "",
        f"Generado: {report['generated_at']} · benchmark v{report['benchmark_version']} · {report['mode']}.",
        "",
        "Evaluable = el experimento puede ejecutarse completo y un FAIL sera atribuible al sistema bajo prueba (no a una "
        "capacidad inexistente conocida). NO significa que el LLM vaya a obtener PASS.",
        "",
        f"**Resultado: {report['evaluable']}/{report['total']} EVALUABLE**"
        + ("" if report["all_evaluable"] else f" · NO evaluables: {', '.join(report['not_evaluable'])}"),
        "",
        "| Caso | Evaluable | Mapa | Semantica | Requisitos | Recursos | Generacion | Roles | Runtime | Referencia | Gaps |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    mark = {True: "si", False: "NO", None: "-"}
    for case in report["cases"]:
        checks = case["checks"]
        map_id = (case.get("map") or {}).get("map_id") or "-"
        lines.append("| " + " | ".join([
            case["case_id"], "SI" if case["evaluable"] else "NO", map_id,
            *[mark[(checks.get(key) or {}).get("ok")] for key in ("semantic_capability", "functional_requirements", "map_resources",
                                                                 "generation", "oracle_roles", "runtime_capabilities",
                                                                 "reference_behavior")],
            ", ".join(case["known_gaps"]) or "-"]) + " |")
    lines += ["", "Casos con mapa de simulacion (solo PLCSIM): " + (", ".join(report["simulation_map_cases"]) or "ninguno"), ""]
    return "\n".join(lines)


def write_report(project_root: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    project_root = Path(project_root)
    json_path, md_path = project_root / REPORT_JSON, project_root / REPORT_MD
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


__all__ = ["run_audit", "audit_case", "render_markdown", "write_report", "load_reference_interpretations", "CHECK_KEYS"]
