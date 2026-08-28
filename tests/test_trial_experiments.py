from __future__ import annotations

from pathlib import Path

from trial_experiments import (
    build_experiment_label,
    compute_next_repetition,
    get_git_commit,
    get_variant_command,
    load_all_trials,
    load_metadata,
    load_variants_for_case,
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


def test_compute_next_repetition_starts_at_one_with_no_saved_trials(tmp_path: Path) -> None:
    first = compute_next_repetition(tmp_path, "C1", "D01", "V1")
    second = compute_next_repetition(tmp_path, "C1", "D01", "V1")
    assert first == 1
    assert second == 1  # a pure preview must never advance anything by itself


def test_compute_next_repetition_derives_from_saved_trials_only(tmp_path: Path) -> None:
    record_trial_summary(tmp_path, {"trial_id": "TRIAL_000001", "condition": "C1", "case_id": "D01", "variant": "V1", "repetition": 1})
    assert compute_next_repetition(tmp_path, "C1", "D01", "V1") == 2

    record_trial_summary(tmp_path, {"trial_id": "TRIAL_000002", "condition": "C1", "case_id": "D01", "variant": "V1", "repetition": 2})
    assert compute_next_repetition(tmp_path, "C1", "D01", "V1") == 3

    # a different variant or condition must have its own independent count
    assert compute_next_repetition(tmp_path, "C1", "D01", "V2") == 1
    assert compute_next_repetition(tmp_path, "C3", "D01", "V1") == 1


def test_compute_next_repetition_ignores_trials_never_saved(tmp_path: Path) -> None:
    # a trial that was started but abandoned (never reached record_trial_summary) must not
    # consume a repetition slot - only what was actually saved counts.
    trial_dir(tmp_path, "D01", "TRIAL_000001").mkdir(parents=True)
    assert compute_next_repetition(tmp_path, "C1", "D01", "V1") == 1


def test_build_experiment_label_matches_required_format() -> None:
    assert build_experiment_label("C1", "D01", "V1", 1) == "C1_D01_V1_R01"
    assert build_experiment_label("C3", "D05", "V2", 2) == "C3_D05_V2_R02"
    assert build_experiment_label("C4", "D12", "V3", 1) == "C4_D12_V3_R01"
    assert build_experiment_label("C2", "D20", "V1", 123) == "C2_D20_V1_R123"


def test_variants_are_loaded_from_json_not_hardcoded(project_root: Path) -> None:
    variants = load_variants_for_case(project_root, "D03")
    assert [entry["variant"] for entry in variants] == ["V1", "V2", "V3"]
    assert get_variant_command(project_root, "D03", "V2") == "Haz que el motor se encienda con Start y se apague con Stop."


def test_all_twenty_cases_have_at_least_three_variants(project_root: Path) -> None:
    for index in range(1, 21):
        case_id = f"D{index:02d}"
        variants = load_variants_for_case(project_root, case_id)
        assert len(variants) >= 3, f"{case_id} tiene menos de 3 variantes"


def test_get_variant_command_returns_empty_for_unknown_variant(project_root: Path) -> None:
    assert get_variant_command(project_root, "D03", "V9") == ""
