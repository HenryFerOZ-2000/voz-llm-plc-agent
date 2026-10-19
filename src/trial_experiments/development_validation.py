"""Reproducible DEVELOPMENT clients of the product engine, never a second parser."""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from pathlib import Path

import product_engine as engine
from llm_client import PLCInterpretationLLMClient
from trial_experiments import benchmark_catalog as BC, deferred_evaluator as DE
from trial_experiments import experiment_maps, oracle_schema, trial_io_map as TIO, trial_model as TM
from utils import load_json_file


def _save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    temporary.replace(path)


def build_pid_supervisory_plan(project_root: Path) -> list[dict]:
    entries = []
    for case in (f'P{i:02d}' for i in range(1, 13)):
        for variant in BC.VARIANT_IDS:
            reference = BC.trial_benchmark_reference(project_root, case, variant)
            if not reference.get('canonical_command'):
                raise ValueError('DEVELOPMENT_BENCHMARK: variante ausente '+case+'/'+variant)
            entries.append({'case_id': case, **reference, 'command_text': reference['canonical_command']})
    return entries


def build_map_adaptation_cases(project_root: Path) -> list[dict]:
    """Recorded DEVELOPMENT inputs; this matrix makes no new live-LLM accuracy claim."""
    folder=Path(project_root)/'tests/fixtures/closure_maps'
    cases=load_json_file(folder/'cases.json')
    return [{**case,'io_map':load_json_file(folder/case['map_file'])} for case in cases]


class RecordingLLMClient(PLCInterpretationLLMClient):
    """Keep original API output, including malformed attempts, outside product prompts."""
    def __init__(self, evidence: Path, **kwargs):
        super().__init__(**kwargs)
        self.evidence, self.responses = evidence, []

    def _parse_semantic_response(self, response):
        self.responses.append({'response_id': getattr(response, 'id', None),
                               'output_text': getattr(response, 'output_text', '')})
        _save(self.evidence/'llm_responses.json', self.responses)
        return super()._parse_semantic_response(response)


def generate_development_case(project_root: Path, entry: dict, run_dir: Path, *,
                              llm_client=None, llm_response_text=None, map_path: Path | None = None) -> dict:
    root = Path(project_root); run_dir = Path(run_dir)
    case, variant, command = entry['case_id'], entry['variant_id'], entry['command_text']
    number = TM.next_trial_number(root, case, variant, 'TEXT', TM.PHASE_DEVELOPMENT)
    record = TM.new_trial_record(case, variant, 'TEXT', number, command_text=command,
        phase=TM.PHASE_DEVELOPMENT, extra={
            **BC.trial_benchmark_reference(root, case, variant), 'round_id': run_dir.name,
            'batch_id': run_dir.name, 'interaction_policy': 'UNANSWERED_CLARIFICATION',
            'parser_mode': 'llm', 'reference_command_text': command,
            'reference_text_hash': hashlib.sha256(command.encode()).hexdigest(),
            'effective_input_text_hash': hashlib.sha256(command.encode()).hexdigest(),
            'product_engine': {'schema_version': 1, 'engine_id': engine.ENGINE_ID}})
    directory = TM.trial_directory(root, case, variant, record['trial_id'], TM.PHASE_DEVELOPMENT)
    TM.save_trial(directory, record)
    (directory/'command.txt').write_text(command, encoding='utf-8')
    package = None; reference = None; started = time.perf_counter()
    try:
        # Only map capacity selection sees the Oracle; no Oracle object reaches the engine.
        if map_path is None:
            selection = experiment_maps.select_experiment_map(root, oracle_schema.load_oracle(root, case))
        else:
            chosen=Path(map_path).resolve();declared=load_json_file(chosen)
            metadata=declared.get('metadata') or {}
            selection={'path':str(chosen),'map_id':metadata.get('map_id',chosen.stem),
                'map_hash':experiment_maps.canonical_map_hash(declared),'source':'EXPLICIT_DEVELOPMENT_MAP',
                'simulation_only':metadata.get('simulation_only',False),
                'harness_signals':metadata.get('harness_signals',{}),'reason':'Mapa elegido explícitamente antes de interpretar.'}
        if not selection.get('path'):
            raise ValueError(selection.get('reason', 'DEVELOPMENT_MAP_MISSING'))
        reference = TIO.create_working_map(directory, Path(selection['path']), map_policy=engine.MAP_POLICY)
        TM.update_trial(directory, {'experiment_map': experiment_maps.selection_evidence(selection),
                                    'io_map': reference, 'lifecycle_state': 'PREPARING'})
        working = TIO.load_working_map(Path(reference['working_map_path']))
        catalog = load_json_file(root/'config/intents_catalog.json')
        safety = load_json_file(root/'config/safety_rules.json')
        client = llm_client
        if client is None and llm_response_text is None:
            client = RecordingLLMClient(directory, config_path=root/'config/llm_config.json',
                                         prompt_path=root/'prompts/llm_semantic_parser_prompt.txt')
        semantic = engine.interpret_product_command(command, io_map=working, intents_catalog=catalog,
            safety_rules=safety, mode='llm', llm_client=client, llm_response_text=llm_response_text)
        _save(directory/'semantic_original.json', semantic)
        if llm_response_text is not None:
            _save(directory/'llm_responses.json', [{'source': 'provided_response', 'response': llm_response_text}])
        validation = semantic.get('semantic_validation') or {}
        proposals = validation.get('io_assignment_proposals') or []
        if proposals and not semantic.get('requires_clarification') and not validation.get('requires_clarification'):
            if any(p.get('blocked') for p in proposals):
                raise ValueError('DEVELOPMENT_IO: propuesta bloqueada')
            TIO.apply_proposals_to_working_map(Path(reference['working_map_path']), proposals,
                                              source='TEXT_EXPLICIT', lifecycle_state='PREPARING')
            semantic, working, _ = engine.resolve_product_assignments(semantic, working, proposals, catalog, safety)
            _save(Path(reference['working_map_path']), working)
        _save(directory/'semantic_output.json', semantic)
        valid = engine.is_generatable_product(semantic)
        TM.update_trial(directory, {'semantic': semantic, 'clarification_requested': bool(
            semantic.get('requires_clarification') or (semantic.get('semantic_validation') or {}).get('requires_clarification')),
            'stages': {'semantic_success': valid, 'io_allocation_success': valid},
            'model': {'provider': getattr(client, 'provider', 'inline'), 'model': getattr(client, 'model_name', None)},
            'timing': {'semantic_ms': round((time.perf_counter()-started)*1000)}})
        if not valid:
            TM.update_trial(directory, {'failure_stage': 'semantic', 'failure_category': 'SEMANTIC_FAILURE'})
            TM.finalize_trial(directory, TM.FINAL_STATUS_FAIL,
                              list((semantic.get('semantic_validation') or {}).get('errors') or ['Aclaración sin respuesta o semántica inválida.']))
        else:
            reference = TIO.freeze_working_map(reference, semantic, lifecycle_state='PREPARING', trial_id=record['trial_id'])
            TM.update_trial(directory, {'io_map': reference, 'lifecycle_state': 'IO_RESOLVED'})
            result = engine.generate_product_package(semantic, target_platform='SIEMENS_SCL_V18', io_map=working,
                intents_catalog=catalog, safety_rules=safety, output_dir=run_dir/'g'/f'{case}_{variant}')
            package = Path(result['package_dir']) if result.get('package_dir') else None
            verification = result.get('verification') or {}
            TM.update_trial(directory, {'verification': verification, 'stages': {'ir_success': verification.get('is_valid') is True}})
            if package:
                TM.copy_package_artifacts(directory, package)
                variables = json.loads((package/'variables.json').read_text(encoding='utf-8'))
                TIO.record_generated_internal_variables(reference, variables)
            if not verification.get('is_valid'):
                TM.update_trial(directory, {'failure_stage': 'generate', 'failure_category': 'VERIFICATION_FAILURE'})
                TM.finalize_trial(directory, TM.FINAL_STATUS_FAIL, verification.get('errors') or ['Verificación rechazada.'])
        DE.finalize_generation(root, directory, package)
    except Exception as error:
        TM.update_trial(directory, {'failure_stage': 'generation', 'failure_category': 'GENERATION_EXCEPTION'})
        TM.finalize_trial(directory, TM.FINAL_STATUS_FAIL, [str(error)])
        DE.finalize_generation(root, directory, None)
    finally:
        if reference:
            TIO.discard_working_map(reference)
    record = TM.load_trial(directory)
    contract = load_json_file(directory/'product_contract.json') if (directory/'product_contract.json').is_file() else {}
    return {'trial_dir': directory, 'trial_id': record['trial_id'], 'case_id': case, 'variant_id': variant,
            'package_dir': package, 'generation': record.get('generation'), 'package_kind': contract.get('package_kind'),
            'final_status': record.get('final_status'), 'errors': record.get('errors')}


def run_supervisory_round(project_root: Path, output_root: Path, *, evaluate: bool,
                          cancel: threading.Event | None = None, map_path: Path | None = None) -> dict:
    root = Path(project_root); round_id = 'PID_DEV_'+uuid.uuid4().hex[:12]
    run_dir = Path(output_root)/round_id; run_dir.mkdir(parents=True, exist_ok=False)
    report = {'round_id': round_id, 'phase': TM.PHASE_DEVELOPMENT, 'status': 'RUNNING', 'entries': []}
    _save(run_dir/'summary.json', report)
    for entry in build_pid_supervisory_plan(root):
        if cancel and cancel.is_set():
            report['status'] = 'CANCELLED'; break
        result = generate_development_case(root, entry, run_dir, map_path=map_path)
        directory = result['trial_dir']
        if evaluate and result.get('generation', {}).get('status') == 'SUCCESS':
            result['evaluation'] = DE.evaluate_trial(root, directory)
        report['entries'].append(result)
        _save(run_dir/'summary.json', report)
        print(f"{entry['case_id']} {entry['variant_id']}: {result['generation']['status']} {result.get('package_kind') or ''}", flush=True)
        if TM.load_trial(directory).get('final_status') == TM.FINAL_STATUS_INFRASTRUCTURE_ERROR:
            report['status'] = 'PAUSED_INFRASTRUCTURE'; break
    else:
        report['status'] = 'COMPLETED'
    _save(run_dir/'summary.json', report)
    return report
