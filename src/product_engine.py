"""Product semantics shared by interactive programming and controlled trials.

No trial, Oracle, transport or UI policy enters this module. Callers own persistence.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from functional_requirements import has_composable_program
from io_allocator import apply_assignments
from ir_builder import required_external_resources
from llm_parser import parse_command, bind_semantic_resources
from pid_control import has_native_pid
from project_packager import generate_project_package
from semantic_validator import validate_semantic_output

ENGINE_ID = 'PRODUCT_SHARED_V1'
MAP_POLICY = 'PRODUCT_DECLARED_V1'


def prepare_product_map(io_map: dict, *, scope: str = 'NEW_PROGRAM',
                        previous_program_id: str | None = None) -> dict:
    from normal_program_bindings import release_auto_bindings, SCOPE_NEW, SCOPE_EXTEND
    if scope not in {SCOPE_NEW, SCOPE_EXTEND}:
        raise ValueError('Unknown product program scope: '+str(scope))
    previous_program_id = previous_program_id or ((io_map.get('metadata') or {}).get('current_program') or {}).get('program_id')
    working, released = (release_auto_bindings(io_map, strict_owner=True, owner_program_id=previous_program_id)
                         if scope == SCOPE_NEW else (copy.deepcopy(io_map), []))
    unknown = [v['name'] for v in io_map.get('variables', []) if v.get('state') == 'ASSIGNED' and
               not (v.get('assignment_source') and v.get('owner_program_id'))]
    return {'io_map': working, 'released': released, 'retained_unknown': unknown}


def interpret_product_command(command_text: str, *, io_map: dict, intents_catalog: dict,
                              safety_rules: dict, mode: str | None = None, llm_client: Any = None,
                              llm_response_text: str | dict | None = None,
                              clarification_history: list[dict] | None = None,
                              program_context: dict | None = None) -> dict:
    result = parse_command(command_text, mode=mode, io_map=io_map, intents_catalog=intents_catalog,
        safety_rules=safety_rules, llm_client=llm_client, llm_response_text=llm_response_text,
        interaction_profile='normal', clarification_history=clarification_history, program_context=program_context)
    return {**result, 'product_engine': {'schema_version': 1, 'engine_id': ENGINE_ID}}


def resolve_product_assignments(semantic_output: dict, io_map: dict, proposals: list[dict],
                                intents_catalog: dict, safety_rules: dict) -> tuple[dict, dict, list[dict]]:
    if any(proposal.get('blocked') for proposal in proposals):
        raise ValueError('Product assignment blocked: no se aplican propuestas bloqueadas.')
    working, history = apply_assignments(copy.deepcopy(io_map), proposals, source='TEXT_EXPLICIT')
    result = copy.deepcopy(semantic_output)
    result['semantic_validation'] = validate_semantic_output(result, working, intents_catalog, safety_rules)
    result = bind_semantic_resources(result, working, intents_catalog, safety_rules)
    names = {v['name'] for v in working.get('variables', [])}
    missing = [name for name in required_external_resources(result, working) if name not in names]
    if missing:
        validation = result['semantic_validation']
        result['semantic_validation'] = {**validation, 'is_valid': False,
            'errors': list(validation.get('errors', [])) + ['Asignacion I/O incompleta: '+', '.join(missing)]}
    return result, working, history


def is_generatable_product(semantic_output: dict) -> bool:
    if not (semantic_output.get('semantic_validation') or {}).get('is_valid'):
        return False
    requirements = semantic_output.get('functional_requirements') or []
    return (semantic_output.get('intent_id') not in (None, 'INT_UNKNOWN') or
            has_composable_program(requirements) or has_native_pid(requirements))


def generate_product_package(semantic_output: dict, *, target_platform: str, io_map: dict,
                             intents_catalog: dict, safety_rules: dict,
                             transcription_payload: dict | None = None, output_dir: Path | None = None) -> dict:
    from plc_maps.map_validator import physical_address_errors
    address_errors=physical_address_errors(io_map.get('variables') or [])
    if address_errors:
        raise ValueError('PRODUCT_MAP_INVALID: '+'; '.join(address_errors))
    payload = {**semantic_output, 'interaction_profile': 'normal',
               'product_engine': {'schema_version': 1, 'engine_id': ENGINE_ID}}
    result = generate_project_package(payload, target_platform, io_map, intents_catalog, safety_rules,
                                      transcription_payload, output_dir)
    if result.get('package_dir'):
        (Path(result['package_dir'])/'generation_io_map.json').write_text(
            json.dumps(io_map, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return result
