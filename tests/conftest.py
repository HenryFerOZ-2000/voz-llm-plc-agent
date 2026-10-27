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

REAL_BENCH_MAP_PATH = PROJECT_ROOT / "data" / "plc_maps" / "mapa_banco_fisico_base.json"
# Mapa working local de Modo Normal (ignorado por Git; puede no existir en un clon nuevo).
REAL_BENCH_WORKING_MAP_PATH = PROJECT_ROOT / "data" / "plc_maps" / "mapa_banco_fisico_working.json"


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
    guarded = (REAL_BENCH_MAP_PATH, REAL_BENCH_WORKING_MAP_PATH,
               PROJECT_ROOT / 'generated_code' / 'gui_history.json')
    before = {path: _hash_file(path) for path in guarded}
    yield
    for path in guarded:
        if before[path] is None and path.name != 'gui_history.json':
            continue  # el working se crea en la primera ejecucion de la app; crearlo no es modificarlo
        assert before[path] == _hash_file(path), (
            f"{path.relative_to(PROJECT_ROOT)} cambio durante la corrida de la suite - ningun test "
            "debe escribir sobre los mapas o el historial real (usar tmp_path o el patron `temp_map`). Restaure "
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
def app(tmp_path_factory):
    """
    Single shared Tk root for the WHOLE pytest session. Creating more than one customtkinter
    root (one per test module, say) in the same Windows process is unreliable - a second
    ctk.CTk() after the first is destroyed can crash Tcl init - so every GUI test module must
    reuse this one fixture instead of building its own.
    """
    import gui  # noqa: E402 - deferred import, needs SRC_DIR already on sys.path (see above)

    session_dir = tmp_path_factory.mktemp('gui_session')
    real_load = gui.VozLLMPLCGUI._load_history_state
    def load_isolated_history(instance):
        instance.generated_dir = session_dir / 'generated_code'
        instance.history_storage_path = session_dir / 'gui_history.json'
        gui.ensure_generated_dirs(instance.generated_dir)
        real_load(instance)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(gui.VozLLMPLCGUI, '_load_history_state', load_isolated_history)
        # Startup recovery must never reconcile the user's real batch in GUI tests.
        patch.setattr(gui.VozLLMPLCGUI, '_announce_open_text_batch', lambda self: None)
        instance = gui.VozLLMPLCGUI()
    instance.update_idletasks()
    yield instance
    instance.destroy()


@pytest.fixture(autouse=True)
def _isolated_gui_history(request, tmp_path, monkeypatch):
    """A GUI test neither imports user logs nor leaves history for the next test."""
    if 'app' not in request.fixturenames:
        return
    import gui
    instance = request.getfixturevalue('app')
    monkeypatch.setattr(instance, 'generated_dir', tmp_path / 'generated_code')
    monkeypatch.setattr(instance, 'history_storage_path', tmp_path / 'gui_history.json')
    for name, value in (('history_records', []), ('history_item_map', {}), ('history_record_keys', set())):
        monkeypatch.setattr(instance, name, value)
    gui.ensure_generated_dirs(instance.generated_dir)
    instance._clear_history_ui()


@pytest.fixture(autouse=True)
def _tia_archive_path_limit_for_tmp_paths(monkeypatch):
    """
    TIA V18 limita a 143 caracteres la ruta de Project.Archive. Las rutas de pytest (tmp_path) son
    mas largas y en las pruebas el bridge es simulado: el limite se relaja aqui y se prueba aparte
    (test_phase4a_master_snapshot.py::test_archive_path_limit_is_enforced_before_calling_tia).
    """
    from trial_experiments import deferred_evaluator

    monkeypatch.setattr(deferred_evaluator, "TIA_ARCHIVE_MAX_PATH", 10_000)


@pytest.fixture(autouse=True)
def _sufficient_memory_for_tia(monkeypatch):
    """
    El precheck de memoria (INSUFFICIENT_MEMORY_FOR_TIA) mide la maquina real; las pruebas usan un
    bridge simulado, asi que por defecto se simula memoria suficiente. El precheck se prueba aparte
    (test_phase4a_tia_stability.py) con mediciones controladas.
    """
    from trial_experiments import system_resources

    monkeypatch.setattr(system_resources, "measure_memory", lambda: {
        "available": True, "total_physical_mb": 16384, "available_physical_mb": 12000,
        "commit_limit_mb": 32768, "committed_mb": 8000, "commit_headroom_mb": 24768})
