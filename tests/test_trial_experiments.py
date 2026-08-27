from __future__ import annotations

from pathlib import Path

from trial_experiments import (
    get_git_commit,
    load_all_trials,
    load_metadata,
    next_trial_id,
    record_trial_summary,
    save_metadata,
    trial_dir,
    update_observations,
    write_trial_files
)


def test_next_trial_id_increments_and_persists_across_reload(tmp_path: Path) -> None:
    first = next_trial_id(tmp_path)
    second = next_trial_id(tmp_path)
    assert first == "TRIAL_000001"
    assert second == "TRIAL_000002"

    # simulate reopening the app: a fresh call must continue from the persisted counter
    third = next_trial_id(tmp_path)
    assert third == "TRIAL_000003"


def test_write_trial_files_skips_empty_content(tmp_path: Path) -> None:
    directory = trial_dir(tmp_path, "D03", "TRIAL_000001")
    write_trial_files(directory, {"command.txt": "Arranca el motor", "transcript.txt": "", "empty.txt": "   "})
    assert (directory / "command.txt").exists()
    assert not (directory / "transcript.txt").exists()
    assert not (directory / "empty.txt").exists()


def test_save_metadata_merges_without_losing_earlier_fields(tmp_path: Path) -> None:
    directory = trial_dir(tmp_path, "D03", "TRIAL_000001")
    save_metadata(directory, {"trial_id": "TRIAL_000001", "state": "RUNNING", "command_text": "Arranca"})
    save_metadata(directory, {"state": "AWAITING_MANUAL_RESULT", "compile_result": "OK"})

    metadata = load_metadata(directory)
    assert metadata["trial_id"] == "TRIAL_000001"
    assert metadata["command_text"] == "Arranca"
    assert metadata["state"] == "AWAITING_MANUAL_RESULT"
    assert metadata["compile_result"] == "OK"


def test_update_observations_does_not_touch_metadata(tmp_path: Path) -> None:
    directory = trial_dir(tmp_path, "D03", "TRIAL_000001")
    save_metadata(directory, {"trial_id": "TRIAL_000001", "command_text": "Arranca"})
    update_observations(directory, {"physical_result": "Correcto", "safety_violation": "No"})

    metadata = load_metadata(directory)
    assert metadata["command_text"] == "Arranca"
    observations_path = directory / "observations.json"
    assert observations_path.exists()

    # editing observations later must not touch metadata.json
    update_observations(directory, {"physical_result": "Incorrecto", "safety_violation": "No"})
    metadata_after = load_metadata(directory)
    assert metadata_after["command_text"] == "Arranca"


def test_record_trial_summary_upserts_by_trial_id(tmp_path: Path) -> None:
    record_trial_summary(tmp_path, {"trial_id": "TRIAL_000001", "case_id": "D03", "compile_result": "OK"})
    record_trial_summary(tmp_path, {"trial_id": "TRIAL_000002", "case_id": "D05", "compile_result": "FAIL"})
    record_trial_summary(tmp_path, {"trial_id": "TRIAL_000001", "case_id": "D03", "compile_result": "OK", "error_type": "Ninguno"})

    trials = load_all_trials(tmp_path)
    assert len(trials) == 2
    trial_1 = next(t for t in trials if t["trial_id"] == "TRIAL_000001")
    assert trial_1["error_type"] == "Ninguno"

    csv_path = tmp_path / "experiments" / "experimental_results.csv"
    assert csv_path.exists()
    csv_lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 3  # header + 2 rows, no duplicate


def test_get_git_commit_never_raises_without_repo(tmp_path: Path) -> None:
    commit = get_git_commit(tmp_path)
    assert commit is None or isinstance(commit, str)
