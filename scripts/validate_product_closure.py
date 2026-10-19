"""Explicit DEVELOPMENT validation entry point; delegates all product behavior."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    suite = sub.add_parser('p-suite')
    suite.add_argument('--phase', choices=['DEVELOPMENT'], default='DEVELOPMENT')
    mode = suite.add_mutually_exclusive_group()
    mode.add_argument('--generate-only', action='store_true')
    mode.add_argument('--evaluate', action='store_true')
    suite.add_argument('--credentials-env', type=Path)
    suite.add_argument('--map', dest='map_path', type=Path)
    maps=sub.add_parser('maps')
    maps.add_argument('--phase',choices=['DEVELOPMENT'],default='DEVELOPMENT')
    maps_mode=maps.add_mutually_exclusive_group()
    maps_mode.add_argument('--generate-only',action='store_true')
    maps_mode.add_argument('--evaluate',action='store_true')
    maps.add_argument('--output',type=Path,default=ROOT/'runtime/map_adaptation_rounds')
    args = parser.parse_args(argv)
    if args.action=='maps':
        from trial_experiments.map_validation import run_map_adaptation_round
        result=run_map_adaptation_round(ROOT,args.output,evaluate=args.evaluate)
        print(json.dumps({'round_id':result['round_id'],'status':result['status'],'entries':len(result['entries']),
            'evidence_dir':result['evidence_dir']}))
        return 0 if result['status'] in {'GENERATED','PASSED'} else 1
    if args.credentials_env:
        from dotenv import load_dotenv
        load_dotenv(args.credentials_env, override=False)
    from trial_experiments.development_validation import run_supervisory_round
    result = run_supervisory_round(ROOT, ROOT/'runtime/project_closure_rounds', evaluate=args.evaluate,map_path=args.map_path)
    print(json.dumps({'round_id': result['round_id'], 'status': result['status'], 'entries': len(result['entries'])}))
    return 0 if result['status'] == 'COMPLETED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
