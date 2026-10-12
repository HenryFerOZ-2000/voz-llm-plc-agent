"""
Auditoria READ-ONLY de preparacion pre-FORMAL (sin LLM, sin TIA, sin PLCSIM).

Uso:
  .venv/Scripts/python.exe scripts/preformal_readiness_audit.py            # 32 casos, escribe los informes
  .venv/Scripts/python.exe scripts/preformal_readiness_audit.py D05 P07    # subconjunto, solo consola

Escribe data/preformal_readiness_report.json y docs/preformal_readiness_report.md (solo con los 32 casos).
Codigo de salida 0 si todos los casos auditados son EVALUABLES; 1 si alguno no lo es.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trial_experiments import preformal_readiness as PR  # noqa: E402


def main(argv: list[str]) -> int:
    case_ids = [arg.upper() for arg in argv] or None
    report = PR.run_audit(ROOT, case_ids)
    for case in report["cases"]:
        print(f"{case['case_id']}  {'EVALUABLE' if case['evaluable'] else 'NO EVALUABLE'}  "
              f"map={(case.get('map') or {}).get('map_id')}  gaps={case['known_gaps'] or '-'}")
    print(f"\n{report['evaluable']}/{report['total']} EVALUABLE")
    if case_ids is None:
        json_path, md_path = PR.write_report(ROOT, report)
        print(f"Informes: {json_path} | {md_path}")
    return 0 if report["all_evaluable"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
