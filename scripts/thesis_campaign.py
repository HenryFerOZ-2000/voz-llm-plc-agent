"""Read-only campaign preflight. --write-report exports preparation evidence, never trials."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from trial_experiments import experimental_design as ED
from trial_experiments import deferred_evaluator as DE
from trial_experiments import formal_audio as FA
from trial_experiments import preformal_readiness as PR
from trial_experiments import software_freeze as SF
from trial_experiments import text_batch as TB


def inspect_campaign(root: Path, *, check_runtime: bool = False) -> dict:
    design = ED.load_design(root)
    cases = ED.formal_case_ids(root)
    matrix = ED.formal_design_matrix(root)
    freeze = SF.validate_freeze(root)
    audit = PR.run_audit(root, cases)
    environment = DE.environment_precheck(root, ED.PHASE_FORMAL)
    master = FA.noise_master_status(root, ED.PHASE_FORMAL)
    corpus = FA.corpus_summary(root, ED.PHASE_FORMAL)
    noise_preflight = FA.noise_batch_preflight(root, ED.PHASE_FORMAL)
    open_batch = TB.find_open_batch(root)
    errors = ED.validate_formal_matrix(matrix, root) + freeze['errors'] + environment['errors']
    if not audit['all_evaluable']:
        errors.append('Hay casos discretos no evaluables en la auditoría local.')
    if not master['ready']:
        errors.append(master.get('error') or 'Ruido maestro no disponible.')
    if open_batch:
        errors.append(f"Hay un lote abierto: {open_batch['batch_id']}; reanudarlo o detenerlo desde la GUI.")
    runtime = None
    if check_runtime:
        import plcsim_runtime
        runtime = plcsim_runtime.get_plcsim_runtime_status(root)
        if not runtime.get('connected'):
            errors.append('Iniciar la instancia PLCSIM Advanced configurada antes de ejecutar los ensayos.')
    recorded = []
    base = ED.results_dir_for_phase(root, ED.PHASE_FORMAL)
    for path in sorted(base.glob('*/*/*/trial.json')):
        recorded.append(json.loads(path.read_text(encoding='utf-8')))
    current = ED.formal_statistics_records(recorded, campaign_id=design['formal_campaign']['id'])
    return {'campaign': design['formal_campaign'], 'ready': not errors, 'errors': errors,
            'matrix': matrix, 'modality_counts': {m: sum(c['input_mode']==m for c in matrix)
                                                for m in ED.formal_input_modes(root)},
            'freeze': freeze, 'preformal_audit': audit, 'environment': environment,
            'noise_master_ready': master['ready'], 'audio_corpus': corpus,
            'noise_phase_ready': noise_preflight['ok'],
            'noise_preflight': noise_preflight,
            'runtime': runtime, 'current_campaign_trials': len(current),
            'historical_formal_trials': len(recorded)-len(current),
            'no_llm_calls': True, 'no_download': True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-runtime', action='store_true')
    parser.add_argument('--write-report', action='store_true')
    args = parser.parse_args()
    report = inspect_campaign(ROOT, check_runtime=args.check_runtime)
    if args.write_report:
        out = ROOT / 'runtime/thesis_discrete_v3'
        out.mkdir(parents=True, exist_ok=True)
        (out/'readiness.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
        with (out/'planned_trials.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(report['matrix'][0]))
            writer.writeheader()
            writer.writerows(report['matrix'])
    print(json.dumps({k:v for k,v in report.items() if k not in
                      ('matrix','preformal_audit','environment','runtime')},indent=2,ensure_ascii=False,default=str))
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
