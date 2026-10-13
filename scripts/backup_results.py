"""
Respaldo de resultados (corpus de audio pareado, ensayos y lotes) con manifiesto de hashes.

Uso:
  .venv/Scripts/python.exe scripts/backup_results.py backup --dest E:/respaldo_tesis [--label NOMBRE]
  .venv/Scripts/python.exe scripts/backup_results.py verify --target E:/respaldo_tesis/results_backup_YYYYMMDD_HHMMSS
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trial_experiments import results_backup as RB  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--dest", required=True)
    backup.add_argument("--label")
    verify = sub.add_parser("verify")
    verify.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    if args.command == "backup":
        result = RB.backup_results(ROOT, Path(args.dest), args.label)
        print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2, ensure_ascii=False))
        return 0
    result = RB.verify_backup(Path(args.target))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
