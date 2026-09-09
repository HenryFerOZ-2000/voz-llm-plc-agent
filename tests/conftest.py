from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from utils import load_json_file  # noqa: E402


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def io_map(project_root: Path) -> dict:
    return load_json_file(project_root / "config" / "io_map.json")


@pytest.fixture
def intents_catalog(project_root: Path) -> dict:
    return load_json_file(project_root / "config" / "intents_catalog.json")


@pytest.fixture
def safety_rules(project_root: Path) -> dict:
    return load_json_file(project_root / "config" / "safety_rules.json")


@pytest.fixture(scope="session")
def app():
    """
    Single shared Tk root for the WHOLE pytest session. Creating more than one customtkinter
    root (one per test module, say) in the same Windows process is unreliable - a second
    ctk.CTk() after the first is destroyed can crash Tcl init - so every GUI test module must
    reuse this one fixture instead of building its own.
    """
    import gui  # noqa: E402 - deferred import, needs SRC_DIR already on sys.path (see above)

    instance = gui.VozLLMPLCGUI()
    instance.update_idletasks()
    yield instance
    instance.destroy()
