from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from llm_client import PLCInterpretationLLMClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostico local de integracion OpenAI para voz_llm_plc_agent.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Realiza una prueba real contra la API usando el modelo configurado."
    )
    args = parser.parse_args()

    client = PLCInterpretationLLMClient()
    payload = client.connectivity_check() if args.live else client.health_check()
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
