"""
Corpus de audio pareado clean/noisy (FORMAL v1.1).

Uso:
  .venv/Scripts/python.exe scripts/formal_audio.py status [--phase FORMAL|DEVELOPMENT]
      READ-ONLY: ruido maestro, conteos del corpus y preflight del lote VOICE_NOISE (PAIRS READY X / 96).

  .venv/Scripts/python.exe scripts/formal_audio.py verify [--phase FORMAL|DEVELOPMENT]
      READ-ONLY: integridad de todas las celdas grabadas (hashes, manifiestos, SNR, clipping, regeneracion byte a byte).

  .venv/Scripts/python.exe scripts/formal_audio.py approve-master --approved-by "Nombre" --provenance "TEXTO" [--license "TEXTO"]
      Aprobacion HUMANA del ruido maestro formal_assets/audio/industrial_noise_master.wav (WAV PCM16 mono 16 kHz, >= 60 s,
      sin voz inteligible). Registra su SHA-256 en config/formal_audio_config.json (versionado).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trial_experiments import formal_audio as FA  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "verify"):
        sub.add_parser(name).add_argument("--phase", default="FORMAL", choices=("FORMAL", "DEVELOPMENT"))
    approve = sub.add_parser("approve-master")
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--provenance", required=True)
    approve.add_argument("--license", default="")
    args = parser.parse_args(argv)
    if args.command == "approve-master":
        master = FA.approve_noise_master(ROOT, args.approved_by, args.provenance, args.license)
        print(json.dumps(master, indent=2, ensure_ascii=False))
        return 0
    if args.command == "status":
        master = FA.noise_master_status(ROOT, args.phase)
        preflight = FA.noise_batch_preflight(ROOT, args.phase)
        print(json.dumps({"phase": args.phase, "AUDIO_NOISE_MASTER_READY": "YES" if master["ready"] else "NO", "master": master,
                          "corpus": FA.corpus_summary(ROOT, args.phase),
                          "noise_batch_preflight": f"PAIRS READY: {preflight['pairs_ready']} / {preflight['total']}"},
                         indent=2, ensure_ascii=False))
        return 0
    failures = {}
    for key, cell in FA.load_corpus(ROOT, args.phase)["cells"].items():
        if cell["state"] != FA.STATE_NOT_RECORDED:
            check = FA.verify_cell(ROOT, args.phase, cell["case_id"], cell["variant"])
            if not check["ok"]:
                failures[key] = check["errors"]
    print(json.dumps({"phase": args.phase, "integrity": "PASS" if not failures else "FAIL", "failures": failures}, indent=2, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
