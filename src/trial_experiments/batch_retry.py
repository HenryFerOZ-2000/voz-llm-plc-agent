"""Bounded technical retries, enabled only by the policy frozen in a new batch."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

POLICY_PATH = Path('config/batch_retry.json')
DEFAULT_POLICY = {'enabled': False, 'max_retries': 2, 'backoff_ms': [5000, 15000]}
_BLOCKED = ('authentication', 'invalid_api_key', 'incorrect api key', '401', '403', 'permissiondenied',
            'insufficient_quota', 'quota exceeded', 'billing', 'trial_integrity', 'campaign_mismatch',
            'software_freeze', 'hash mismatch', 'insufficient_memory_for_tia', 'master cambió', 'master changed')


def load_policy(root: Path) -> dict[str, Any]:
    path = Path(root) / POLICY_PATH
    policy = json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(DEFAULT_POLICY)
    count, delays = policy.get('max_retries'), policy.get('backoff_ms')
    if (type(policy.get('enabled')) is not bool or type(count) is not int or not 0 <= count <= 2
            or not isinstance(delays, list) or len(delays) != 2
            or any(type(d) is not int or not 0 < d <= 60000 for d in delays)):
        raise ValueError('BATCH_RETRY_POLICY_INVALID: enabled booleano, max_retries 0..2 y dos esperas de 1..60000 ms.')
    return {'enabled': policy['enabled'], 'max_retries': count, 'backoff_ms': list(delays)}


def reserve(manifest: dict[str, Any], record: dict[str, Any]) -> dict[str, Any] | None:
    """Reserve once before scheduling; no historical manifest is implicitly opted in."""
    policy = manifest.get('automatic_retry_policy') or {}
    if (not policy.get('enabled') or manifest.get('status') != 'PAUSED'
            or manifest.get('pause_reason') != 'INFRASTRUCTURE_ERROR'
            or manifest.get('automatic_retry_pending') or manifest.get('pause_requested')
            or manifest.get('stop_requested')):
        return None
    entry = next((e for e in manifest['ordered_trial_plan']
                  if e['status'] not in ('COMPLETED', 'NOT_EVALUABLE')), None)
    final = (record.get('evaluation') or {}).get('final_verdict') or record.get('final_verdict') or record.get('final_status')
    if entry is None or entry['status'] != 'INFRASTRUCTURE_ERROR' or final != 'INFRASTRUCTURE_ERROR':
        return None
    # Only inspect persisted diagnostic strings; never store or log this serialization.
    evaluation = record.get('evaluation') or {}
    last = (evaluation.get('attempts') or [{}])[-1]
    diagnostic = json.dumps([node.get(key) for node in
                             (record, evaluation, last, record.get('generation') or {}, record.get('voice') or {})
                             for key in ('errors', 'error', 'error_code', 'exception_type')],
                            ensure_ascii=False, default=str).lower()
    if any(marker in diagnostic for marker in _BLOCKED):
        return None
    history = entry.get('automatic_retries') or []
    if len(history) >= policy.get('max_retries', 0):
        return None
    number = len(history) + 1
    reason = f"AUTO_INFRA_RETRY {number}/{policy['max_retries']}: {record.get('failure_category') or 'INFRASTRUCTURE_ERROR'}; origen {entry['trial_id']}"
    reservation = {'index': entry['index'], 'trial_id': entry['trial_id'], 'number': number,
                   'delay_ms': policy['backoff_ms'][number - 1], 'reason': reason,
                   'scheduled_at': datetime.now().isoformat(timespec='seconds')}
    entry['automatic_retries'] = history + [dict(reservation)]
    manifest['automatic_retry_pending'] = reservation
    manifest.setdefault('events', []).append({'at': reservation['scheduled_at'], 'event': 'AUTO_RETRY_SCHEDULED',
                                              'detail': reason})
    return reservation
