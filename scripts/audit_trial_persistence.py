"""
Auditoria READ-ONLY de ensayos evaluados cuyo resultado no llego a trial.json
(src/trial_experiments/persistence_audit.py).

    .venv\\Scripts\\python.exe scripts\\audit_trial_persistence.py D03_V1_TEXT_DEV_001 D03_V2_TEXT_DEV_001
    .venv\\Scripts\\python.exe scripts\\audit_trial_persistence.py --trial-dir <carpeta> --json

No escribe nada, no llama al LLM, no genera SCL, no abre TIA/PLCSIM y no vuelve a ejecutar el Oracle.
Codigo de salida: 0 si todos los ensayos son RECONSTRUCTIBLE o ALREADY_PERSISTED; 2 en otro caso.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trial_experiments import persistence_audit  # noqa: E402

if __name__ == "__main__":
    sys.exit(persistence_audit.main(["--project-root", str(ROOT), *sys.argv[1:]]))
