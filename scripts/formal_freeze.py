"""
Congelacion FORMAL del software (manifiesto v2) y su validacion.

Uso:
  .venv/Scripts/python.exe scripts/formal_freeze.py validate
      READ-ONLY: el entorno actual coincide con el manifiesto (codigo, prompt, Oracles, benchmark, mapas,
      configuracion de ejecucion, MASTER FORMAL_READY, entorno). Salida 0 si coincide, 1 si no.

  .venv/Scripts/python.exe scripts/formal_freeze.py declare-master --approved-by "Nombre" [--evidence TEXTO ...]
      Declara el TIA MASTER FORMAL_READY (aprobacion humana explicita; solo metadata local de config/tia_projects.json).

  .venv/Scripts/python.exe scripts/formal_freeze.py build --suite-passed N --suite-failed 0 --suite-skipped N --tag formal-v1.0
      Escribe el manifiesto (ruta del diseno experimental) con hashes reales del commit actual. Exige git limpio en el
      alcance congelado, suite sin fallos, auditoria pre-FORMAL 32/32 y MASTER FORMAL_READY.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trial_experiments import deferred_evaluator as DE  # noqa: E402
from trial_experiments import preformal_readiness as PR  # noqa: E402
from trial_experiments import software_freeze as SF  # noqa: E402

KNOWN_LIMITATIONS = [
    "D15 may allocate legacy optional inputs that are not used by generated logic "
    "(INT_MANUAL_AUTO_MODE contract keeps manual_input/trigger_input/stop_input defaults; KNOWN_NON_BLOCKING_LIMITATION).",
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    declare = sub.add_parser("declare-master")
    declare.add_argument("--approved-by", required=True)
    declare.add_argument("--evidence", nargs="*", default=[])
    build = sub.add_parser("build")
    build.add_argument("--suite-passed", type=int, required=True)
    build.add_argument("--suite-failed", type=int, required=True)
    build.add_argument("--suite-skipped", type=int, required=True)
    build.add_argument("--tag", default="formal-v1.0")
    args = parser.parse_args(argv)

    if args.command == "validate":
        result = SF.validate_freeze(ROOT)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1
    if args.command == "declare-master":
        config = DE.declare_master_formal_ready(ROOT, args.approved_by, args.evidence)
        print(json.dumps({"status": config["status"], "formal_ready": config["formal_ready"]}, indent=2, ensure_ascii=False))
        return 0
    if args.suite_failed != 0:
        print("La suite tiene fallos: no se congela.")
        return 1
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *SF.FROZEN_DIRS, *SF.FROZEN_ROOT_FILES], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        print("Hay cambios sin commit en el alcance congelado:\n" + dirty)
        return 1
    if SF.master_state(ROOT)["master_status"] != DE.MASTER_FORMAL_READY:
        print("El MASTER no esta FORMAL_READY.")
        return 1
    audit = PR.run_audit(ROOT)
    if not audit["all_evaluable"]:
        print(f"Auditoria pre-FORMAL incompleta: {audit['not_evaluable']}")
        return 1
    readiness = {"evaluable": audit["evaluable"], "total": audit["total"], "blockers": len(audit["not_evaluable"]),
                 "simulation_map_cases": audit["simulation_map_cases"], "generated_at": audit["generated_at"]}
    suite = {"passed": args.suite_passed, "failed": args.suite_failed, "skipped": args.suite_skipped}
    manifest = SF.build_manifest(ROOT, suite, readiness, args.tag, KNOWN_LIMITATIONS)
    path = ROOT / SF.manifest_relative_path(ROOT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    check = SF.validate_freeze(ROOT)
    print(json.dumps({"manifest": str(path), "git_commit": manifest["git_commit"], "files": manifest["file_count"],
                      "validation": check}, indent=2, ensure_ascii=False))
    return 0 if check["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
