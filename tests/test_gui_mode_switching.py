from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402

# The shared `app` fixture (one Tk root for the whole pytest session) lives in conftest.py.


@pytest.fixture(autouse=True)
def _reset_work_mode(app):
    app.work_mode_var.set("Normal")
    app._on_work_mode_changed()
    yield


def _select_case(app, case_id: str) -> str:
    name = next(name for name, p in app._experiment_profiles_by_case.items() if p.get("case_id") == case_id)
    app.experiment_case_var.set(name)
    app._on_experiment_case_changed()
    return name


def test_normal_mode_always_uses_general_profile(app) -> None:
    assert app.work_mode_var.get() == "Normal"
    assert app.active_profile_id is None


def test_experimentacion_d01_activates_matching_profile(app) -> None:
    app.work_mode_var.set("Experimentacion")
    app._on_work_mode_changed()
    _select_case(app, "D01")
    assert app.active_profile_id == "D01"


def test_switching_case_changes_filter_without_touching_map_file(app) -> None:
    map_path = app.io_map_path
    before = map_path.read_bytes()

    app.work_mode_var.set("Experimentacion")
    app._on_work_mode_changed()
    _select_case(app, "D01")
    assert app.active_profile_id == "D01"

    _select_case(app, "D03")
    assert app.active_profile_id == "D03"

    after = map_path.read_bytes()
    assert before == after


def test_returning_to_normal_clears_experimental_profile(app) -> None:
    app.work_mode_var.set("Experimentacion")
    app._on_work_mode_changed()
    _select_case(app, "D03")
    assert app.active_profile_id == "D03"

    app.work_mode_var.set("Normal")
    app._on_work_mode_changed()
    assert app.active_profile_id is None


def test_profile_selector_is_never_manually_editable(app) -> None:
    assert app.profile_selector.cget("state") == "disabled"

    app.work_mode_var.set("Experimentacion")
    app._on_work_mode_changed()
    assert app.profile_selector.cget("state") == "disabled"

    app.work_mode_var.set("Normal")
    app._on_work_mode_changed()
    assert app.profile_selector.cget("state") == "disabled"


def test_variants_of_same_case_share_the_same_profile(app) -> None:
    app.work_mode_var.set("Experimentacion")
    app._on_work_mode_changed()
    _select_case(app, "D03")
    profile_id_v1 = app.active_profile_id

    app.experiment_variant_var.set("V2")
    app._on_experiment_variant_changed()
    profile_id_v2 = app.active_profile_id

    assert profile_id_v1 == profile_id_v2 == "D03"


def test_experiment_case_selector_populated_without_activating_profile_at_startup(app) -> None:
    """
    Regression test: _refresh_experiment_case_selector() also runs once during __init__ to
    populate the (hidden) case dropdown. It must NOT call _on_experiment_case_changed() while
    the app is still in Normal mode, or a fresh app would silently start with a Dxx profile
    active (the exact bug this task fixes).
    """
    assert app.work_mode_var.get() == "Normal"
    assert len(app._experiment_profiles_by_case) > 0
    app._refresh_experiment_case_selector()
    assert app.active_profile_id is None
