"""Prepare the existing S7-1500 level transmitter and proportional valve with a verified backup."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tank_bench_setup import save_tank_bench


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--backup-root', type=Path, default=ROOT/'runtime/map_backups/tank_setup')
    args = parser.parse_args()
    result = save_tank_bench(args.map, args.expected_sha256, args.backup_root)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
