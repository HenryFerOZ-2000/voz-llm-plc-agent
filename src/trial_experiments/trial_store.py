from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from trial_experiments.constants import MASTER_LOG_FIELDS
from utils import ensure_directory, load_json_file

EXPERIMENTS_DIRNAME = "experiments"
AUTOMATED_DIRNAME = "automated"
COUNTER_FILENAME = ".trial_counter.json"
MASTER_CSV_FILENAME = "experimental_results.csv"
MASTER_JSON_FILENAME = "experimental_results.json"


def get_experiments_dir(project_root: Path) -> Path:
    return project_root / EXPERIMENTS_DIRNAME


def ensure_experiments_dir(project_root: Path) -> Path:
    return ensure_directory(get_experiments_dir(project_root))


def _counter_path(project_root: Path) -> Path:
    return get_experiments_dir(project_root) / COUNTER_FILENAME


def next_trial_id(project_root: Path) -> str:
    """Persistent, never-reused trial id (TRIAL_000001, TRIAL_000002, ...)."""
    ensure_experiments_dir(project_root)
    counter_path = _counter_path(project_root)
    last_id = 0
    if counter_path.exists():
        try:
            payload = load_json_file(counter_path)
            last_id = int(payload.get("last_id", 0)) if isinstance(payload, dict) else 0
        except (FileNotFoundError, ValueError):
            last_id = 0
    next_id = last_id + 1
    counter_path.write_text(json.dumps({"last_id": next_id}, indent=2), encoding="utf-8")
    return f"TRIAL_{next_id:06d}"


def compute_next_repetition(project_root: Path, condition: str, case_id: str, variant: str) -> int:
    """
    Next repetition number for this condition+case_id+variant combo, derived entirely from
    already-saved trial records (experimental_results.json) - never a separate counter file
    that could drift if a trial is abandoned, cancelled, or the file gets edited by hand.
    Safe to call repeatedly as a preview: it never mutates anything.
    """
    matching_repetitions = [
        int(trial.get("repetition", 0))
        for trial in load_all_trials(project_root)
        if trial.get("condition") == condition and trial.get("case_id") == case_id and trial.get("variant") == variant
    ]
    return max(matching_repetitions, default=0) + 1


def build_experiment_label(condition: str, case_id: str, variant: str, repetition: int) -> str:
    return f"{condition}_{case_id}_{variant}_R{repetition:02d}"


def trial_dir(project_root: Path, case_id: str, trial_id: str) -> Path:
    return get_experiments_dir(project_root) / AUTOMATED_DIRNAME / case_id / trial_id


def write_trial_files(directory: Path, files: dict[str, str]) -> None:
    """Write only the files that have real (non-empty) content."""
    for filename, content in files.items():
        if content is None:
            continue
        if isinstance(content, str) and not content.strip():
            continue
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_text(content, encoding="utf-8")


def save_metadata(directory: Path, metadata_patch: dict[str, Any]) -> None:
    """Merge-write metadata.json: preserves fields already recorded earlier in the trial."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "metadata.json"
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = load_json_file(path)
        except (FileNotFoundError, ValueError):
            existing = {}
    existing.update(metadata_patch)
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


def load_metadata(directory: Path) -> dict[str, Any]:
    path = directory / "metadata.json"
    if not path.exists():
        return {}
    try:
        return load_json_file(path)
    except (FileNotFoundError, ValueError):
        return {}


def update_observations(directory: Path, observations: dict[str, Any]) -> None:
    """Manual post-trial fields, kept separate from metadata.json so re-editing them
    never touches the original technical evidence."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "observations.json"
    path.write_text(json.dumps(observations, indent=2, ensure_ascii=False), encoding="utf-8")


def load_all_trials(project_root: Path) -> list[dict[str, Any]]:
    """Full summary log for the experimental history view / export."""
    json_path = get_experiments_dir(project_root) / MASTER_JSON_FILENAME
    if not json_path.exists():
        return []
    try:
        payload = load_json_file(json_path)
    except (FileNotFoundError, ValueError):
        return []
    return payload if isinstance(payload, list) else []


def record_trial_summary(project_root: Path, summary_row: dict[str, Any]) -> None:
    """
    Upsert one trial's summary row into the master log (by trial_id) and rewrite
    experimental_results.{json,csv}. Never duplicates a row: re-saving observations
    for an already-logged trial updates its row in place instead of appending a copy.
    """
    ensure_experiments_dir(project_root)
    trial_id = summary_row.get("trial_id")
    rows = load_all_trials(project_root)
    replaced = False
    for index, existing_row in enumerate(rows):
        if existing_row.get("trial_id") == trial_id:
            rows[index] = summary_row
            replaced = True
            break
    if not replaced:
        rows.append(summary_row)

    experiments_dir = get_experiments_dir(project_root)
    json_path = experiments_dir / MASTER_JSON_FILENAME
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_path = experiments_dir / MASTER_CSV_FILENAME
    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=MASTER_LOG_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MASTER_LOG_FIELDS})
