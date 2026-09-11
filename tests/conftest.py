from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from utils import load_json_file  # noqa: E402

REAL_BENCH_MAP_PATH = PROJECT_ROOT / "data" / "plc_maps" / "mapa_banco_fisico.json"


def _hash_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="session", autouse=True)
def _real_bench_map_untouched_guard():
    """
    Backstop automatico (seccion "separar parse de persistencia" / "tests aislados"): ningun test
    de esta suite debe escribir sobre el mapa fisico real del proyecto - parser, validator y
    allocator son puros (nunca mutan el mapa que reciben; `apply_assignments`/`propose_assignment`
    siempre devuelven una copia nueva); la persistencia ocurre solo en gui.py, y todo test que la
    ejercita usa tmp_path/el patron `temp_map` ya establecido (nunca el mapa real). Hashea el
    archivo antes de la sesion completa y vuelve a hashearlo al final - si algo lo toco, la suite
    entera falla aqui con un mensaje claro, sin depender de que cada test se acuerde de revisarlo
    por su cuenta.
    """
    before = _hash_file(REAL_BENCH_MAP_PATH)
    yield
    after = _hash_file(REAL_BENCH_MAP_PATH)
    assert before == after, (
        "data/plc_maps/mapa_banco_fisico.json cambio durante la corrida de la suite - ningun test "
        "debe escribir sobre el mapa fisico real (usar tmp_path o el patron `temp_map`). Restaure "
        "el archivo desde un estado conocido antes de continuar."
    )


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
