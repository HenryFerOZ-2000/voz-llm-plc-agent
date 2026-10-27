"""Trial integrity accepts nested evidence while rejecting paths outside the trial."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from trial_experiments import deferred_evaluator as DE


def _trial(tmp_path: Path, extra: dict[str, bytes] | None = None) -> Path:
    trial = tmp_path / 'trial'
    trial.mkdir()
    artifacts = {'program.scl': b'// discrete program\n', **(extra or {})}
    for name, data in artifacts.items():
        target = trial / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (trial / 'trial.json').write_text('{}', encoding='utf-8')
    (trial / DE.MANIFEST_FILENAME).write_text(json.dumps({'files': {
        name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()
    }}), encoding='utf-8')
    return trial


def _manifest_entry(trial: Path, name: str, content: bytes) -> None:
    path = trial / DE.MANIFEST_FILENAME
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['files'][name] = hashlib.sha256(content).hexdigest()
    path.write_text(json.dumps(manifest), encoding='utf-8')


@pytest.mark.parametrize('name', [
    'audio/reference.txt', 'audio/clean_audio.wav', 'audio/asr_result.json',
    'audio/noisy_audio.wav', 'audio/nested/evidence.json',
])
def test_valid_nested_evidence_is_accepted(tmp_path, name):
    trial = _trial(tmp_path, {name: b'frozen evidence'})
    result = DE.verify_trial_integrity(trial)
    assert result['ok'], result['errors']


@pytest.mark.parametrize('change', ['modified', 'missing'])
def test_nested_evidence_still_requires_original_hash(tmp_path, change):
    trial = _trial(tmp_path, {'audio/clean_audio.wav': b'frozen audio'})
    audio = trial / 'audio/clean_audio.wav'
    if change == 'modified':
        audio.write_bytes(b'different audio')
    else:
        audio.unlink()
    result = DE.verify_trial_integrity(trial)
    assert not result['ok']
    assert any('audio/clean_audio.wav' in error for error in result['errors'])
    assert all('ruta fuera' not in error for error in result['errors'])


def test_parent_traversal_is_rejected_even_when_hash_matches(tmp_path):
    trial = _trial(tmp_path)
    outside = tmp_path / 'outside.wav'
    outside.write_bytes(b'outside evidence')
    _manifest_entry(trial, '../outside.wav', outside.read_bytes())
    result = DE.verify_trial_integrity(trial)
    assert not result['ok']
    assert any('ruta fuera del ensayo' in error for error in result['errors'])


@pytest.mark.parametrize('inside', [False, True])
def test_absolute_manifest_path_is_rejected(tmp_path, inside):
    trial = _trial(tmp_path)
    target = trial / 'absolute.wav' if inside else tmp_path / 'outside.wav'
    target.write_bytes(b'absolute evidence')
    _manifest_entry(trial, str(target.resolve()), target.read_bytes())
    result = DE.verify_trial_integrity(trial)
    assert not result['ok']
    assert any('ruta fuera del ensayo' in error for error in result['errors'])


def test_symlink_to_external_evidence_is_rejected(tmp_path):
    trial = _trial(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'recording.wav').write_bytes(b'external audio')
    try:
        (trial / 'audio').symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f'Directory symlinks unavailable: {error}')
    _manifest_entry(trial, 'audio/recording.wav', b'external audio')
    result = DE.verify_trial_integrity(trial)
    assert not result['ok']
    assert any('ruta fuera del ensayo' in error for error in result['errors'])
