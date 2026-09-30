"""
Trial-scoped working I/O map (Modo Experimentacion).

Cada ensayo parte del mismo mapa base (inventario fisico del mapa activo, sin residuos de
asignaciones dinamicas), resuelve sus I/O con el MISMO IOAllocator que Modo Normal sobre una copia
propia, congela los bindings en io_map_snapshot.json y descarta la copia al terminar. Todo se
prueba sobre copias temporales del mapa real del banco: los mapas reales nunca se escriben (test
final de hashes).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402
import io_allocator  # noqa: E402
from trial_experiments import trial_io_map, trial_model  # noqa: E402
from utils import get_project_root  # noqa: E402

from test_phase1_download_and_trials import _arm_experiment_trial, _run, pipeline  # noqa: E402
from test_execute_full_pipeline import _base_semantic_output, temp_map, _tia_ready  # noqa: E402

__all__ = ["pipeline", "temp_map", "_tia_ready"]

_MAPS_DIR = get_project_root() / "data" / "plc_maps"
_REAL_MAPS = [
    _MAPS_DIR / "mapa_banco_fisico.json",
    _MAPS_DIR / "mapa_simulacion_completo.json",
    _MAPS_DIR / "mapa_pid_simulacion.json",
    _MAPS_DIR / "mapa_pid_banco_fisico.json",
]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_HASHES_AT_IMPORT = {str(path): _hash(path) for path in _REAL_MAPS}


@pytest.fixture
def bench_map(tmp_path) -> Path:
    """Copia temporal del mapa REAL del banco (con sus residuos ASSIGNED de Modo Normal)."""
    path = tmp_path / "base" / "mapa_banco_fisico.json"
    path.parent.mkdir(parents=True)
    path.write_bytes((_MAPS_DIR / "mapa_banco_fisico.json").read_bytes())
    return path


def _new_trial(tmp_path: Path, bench_map: Path, name: str = "D12_V2_TEXT_001") -> dict[str, Any]:
    return trial_io_map.create_working_map(tmp_path / "trials" / name, bench_map)


def _working(reference: dict[str, Any]) -> dict[str, Any]:
    return trial_io_map.load_working_map(Path(reference["working_map_path"]))


def _allocate(reference: dict[str, Any], requests: list[dict[str, Any]], state: str = trial_io_map.STATE_PREPARING):
    proposals = io_allocator.propose_assignment(_working(reference), requests)
    applicable = [proposal for proposal in proposals if not proposal.get("blocked")]
    trial_io_map.apply_proposals_to_working_map(Path(reference["working_map_path"]), applicable, "TEXT_EXPLICIT", state)
    return proposals


def _by_address(io_map: dict[str, Any], address: str) -> dict[str, Any]:
    return next(variable for variable in io_map["variables"] if variable.get("location") == address)


# ---------- Mapa base ----------

def test_base_map_keeps_locked_and_clears_dynamic_residues(tmp_path, bench_map):
    reference = _new_trial(tmp_path, bench_map)
    working = _working(reference)
    assert reference["physical_channel_count"] == 24
    assert _by_address(working, "%IX16.0")["name"] == "I_Start" and _by_address(working, "%IX16.0")["state"] == "LOCKED"
    assert _by_address(working, "%IX16.1")["name"] == "I_Stop" and _by_address(working, "%IX16.1")["state"] == "LOCKED"
    # Residuos ASSIGNED de Modo Normal (I_Piece_Sensor, Q_Motor_1...) no pasan al ensayo.
    assert _by_address(working, "%IX16.6")["name"] == "I_Free16_6" and _by_address(working, "%IX16.6")["state"] == "FREE"
    assert _by_address(working, "%QX8.0")["name"] == "Q_Free8_0"
    assert _by_address(working, "%IW0")["name"] == "AI_IW0" and _by_address(working, "%QW6")["name"] == "AO_QW6"
    assert not any(variable.get("aliases") for variable in working["variables"] if variable["state"] == "FREE")
    assert working["history"] == []


def test_missing_base_map_is_base_unavailable(tmp_path):
    with pytest.raises(trial_io_map.ExperimentIOError) as error:
        trial_io_map.create_working_map(tmp_path / "trial", tmp_path / "no_existe.json")
    assert error.value.code == trial_io_map.ERROR_BASE_UNAVAILABLE


# ---------- 1-6: mismo IOAllocator que Modo Normal, durante PREPARING ----------

def test_automatic_allocation_allowed_during_preparing_uses_free(tmp_path, bench_map):
    reference = _new_trial(tmp_path, bench_map)
    proposals = _allocate(reference, [{"functional_name_hint": "Q_Motor", "role_text": "motor"}])
    assert proposals[0]["blocked"] is False
    motor = next(variable for variable in _working(reference)["variables"] if variable["name"] == "Q_Motor")
    assert motor["location"].startswith("%QX8.") and motor["state"] == "ASSIGNED"
    assert _working(reference)["history"], "la asignacion queda en el historial del working map"


def test_reassign_assigned_channel_during_preparing(tmp_path, bench_map):
    reference = _new_trial(tmp_path, bench_map)
    _allocate(reference, io_allocator.extract_io_assignment_requests("Usa Q8.0 para el motor"))
    assert _by_address(_working(reference), "%QX8.0")["name"] == "Q_Motor"

    _allocate(reference, io_allocator.extract_io_assignment_requests("Usa Q8.0 para la bomba"))
    channel = _by_address(_working(reference), "%QX8.0")
    assert channel["name"] == "Q_Bomba" and channel["state"] == "ASSIGNED"


def test_reuses_compatible_locked_without_renaming(tmp_path, bench_map):
    reference = _new_trial(tmp_path, bench_map)
    proposals = _allocate(reference, [{"functional_name_hint": "I_Start", "role_text": "arranque"}])
    assert proposals[0]["address"] == "%IX16.0" and proposals[0]["blocked"] is False
    start = _by_address(_working(reference), "%IX16.0")
    assert start["name"] == "I_Start" and start["state"] == "LOCKED"


def test_explicit_address_works_in_experiment(tmp_path, bench_map):
    reference = _new_trial(tmp_path, bench_map)
    _allocate(reference, io_allocator.extract_io_assignment_requests("Usa Q8.1 para el motor 2"))
    channel = _by_address(_working(reference), "%QX8.1")
    assert channel["name"] == "Q_Motor_2" and channel["state"] == "ASSIGNED"


def test_never_invents_a_physical_resource(tmp_path, bench_map):
    reference = _new_trial(tmp_path, bench_map)
    before = Path(reference["working_map_path"]).read_bytes()

    proposals = io_allocator.propose_assignment(
        _working(reference), io_allocator.extract_io_assignment_requests("Usa Q9.5 para el motor 9")
    )
    assert proposals and all(proposal["blocked"] for proposal in proposals)

    forged = [{"address": "%QX9.5", "proposed_name": "Q_Motor_9", "blocked": False}]
    with pytest.raises(trial_io_map.ExperimentIOError) as error:
        trial_io_map.apply_proposals_to_working_map(
            Path(reference["working_map_path"]), forged, "TEXT_EXPLICIT", trial_io_map.STATE_PREPARING
        )
    assert error.value.code == trial_io_map.ERROR_ALLOCATION_FAILED
    assert Path(reference["working_map_path"]).read_bytes() == before
    assert len(_working(reference)["variables"]) == 24


# ---------- 7-8: base intacto e independencia entre ensayos ----------

def test_base_map_never_changes_during_a_full_trial_cycle(tmp_path, bench_map):
    base_hash = _hash(bench_map)
    reference = _new_trial(tmp_path, bench_map)
    _allocate(reference, io_allocator.extract_io_assignment_requests("Usa Q8.0 para el motor"))
    frozen = trial_io_map.freeze_working_map(reference, {"parameters": {"output": "Q_Motor"}}, trial_io_map.STATE_PREPARING)
    trial_io_map.discard_working_map(frozen)
    assert _hash(bench_map) == base_hash


def test_trial_a_does_not_contaminate_trial_b(tmp_path, bench_map):
    trial_a = _new_trial(tmp_path, bench_map, "D12_V2_TEXT_001")
    _allocate(trial_a, io_allocator.extract_io_assignment_requests("Usa Q8.0 para el motor"))
    assert _by_address(_working(trial_a), "%QX8.0")["name"] == "Q_Motor"
    frozen_a = trial_io_map.freeze_working_map(trial_a, {"parameters": {"output": "Q_Motor"}}, trial_io_map.STATE_PREPARING)
    trial_io_map.discard_working_map(frozen_a)
    assert not Path(trial_a["working_map_path"]).exists()

    trial_b = _new_trial(tmp_path, bench_map, "D13_V1_TEXT_001")
    names_b = {variable["name"] for variable in _working(trial_b)["variables"]}
    assert "Q_Motor" not in names_b
    assert _by_address(_working(trial_b), "%QX8.0")["name"] == "Q_Free8_0"
    assert trial_b["base_map_hash"] == trial_a["base_map_hash"]


# ---------- 9-10: snapshot y freeze ----------

def test_snapshot_contains_full_physical_inventory_and_active_bindings(tmp_path, bench_map):
    reference = _new_trial(tmp_path, bench_map)
    _allocate(reference, io_allocator.extract_io_assignment_requests("Usa Q8.3 para el motor"))
    semantic_output = {"intent_id": "INT_DIRECT_OUTPUT", "parameters": {"trigger_input": "I_Start", "output": "Q_Motor"}}
    frozen = trial_io_map.freeze_working_map(reference, semantic_output, trial_io_map.STATE_PREPARING, "D12_V2_TEXT_001")

    snapshot = json.loads(Path(frozen["snapshot_path"]).read_text(encoding="utf-8"))
    assert snapshot["physical_channel_count"] == 24 and len(snapshot["channels"]) == 24
    assert {"address", "signal", "data_type", "state", "functional_name", "description"} <= set(snapshot["channels"][0])
    assert {channel["signal"] for channel in snapshot["channels"]} == {"DI", "DO", "AI", "AO"}
    bound = {binding["functional_name"]: binding for binding in snapshot["bindings"]}
    assert bound["Q_Motor"]["address"] == "%QX8.3" and bound["Q_Motor"]["roles"] == ["output"]
    assert bound["I_Start"]["address"] == "%IX16.0"
    # role -> functional_name -> physical_address (para el Oracle futuro)
    assert snapshot["parameter_bindings"]["output"] == {"functional_name": "Q_Motor", "address": "%QX8.3"}
    assert snapshot["base_map_id"] == "mapa_banco_fisico" and snapshot["trial_id"] == "D12_V2_TEXT_001"
    assert frozen["frozen"] is True and frozen["resolved_at"]


def test_freeze_blocks_any_later_mutation(tmp_path, bench_map):
    reference = _new_trial(tmp_path, bench_map)
    frozen = trial_io_map.freeze_working_map(reference, {}, trial_io_map.STATE_PREPARING)
    before = Path(frozen["working_map_path"]).read_bytes()
    for state in (trial_io_map.STATE_IO_RESOLVED, trial_io_map.STATE_COMPILED, trial_io_map.STATE_DOWNLOADED):
        with pytest.raises(trial_io_map.ExperimentIOError) as error:
            _allocate(frozen, io_allocator.extract_io_assignment_requests("Usa Q8.0 para el motor"), state=state)
        assert error.value.code == trial_io_map.ERROR_FROZEN
    with pytest.raises(trial_io_map.ExperimentIOError):
        trial_io_map.freeze_working_map(frozen, {}, trial_io_map.STATE_IO_RESOLVED)
    assert Path(frozen["working_map_path"]).read_bytes() == before


# ---------- 11-12: manual vs automatico ----------

def test_manual_edit_stays_blocked_during_trial_but_phase_policy_allows_allocator():
    # Edicion manual (IOMapWindow / MAP_CONFIG legacy): sigue bloqueada con el mensaje de siempre.
    message = io_allocator.block_map_config_message({"trial_id": "T1"}, None)
    assert message == "La reasignacion de I/O no esta permitida durante un ensayo experimental activo."
    # Pipeline automatico del ensayo: se rige por la fase, no por "hay un ensayo activo".
    assert trial_io_map.mutation_allowed(trial_io_map.STATE_PREPARING) is True
    assert trial_io_map.mutation_allowed(trial_io_map.STATE_IO_RESOLVED) is False


def _allocating_parse(requests: list[dict[str, Any]], parameters: dict[str, Any], tags: list[str]):
    """parse_command simulado que usa el IOAllocator REAL contra el io_map que le pasa la GUI."""
    seen: list[dict[str, Any]] = []

    def _parse(command_text, **kwargs):
        io_map = kwargs["io_map"]
        seen.append(io_map)
        output = _base_semantic_output("INT_DIRECT_OUTPUT", parameters, tags)
        output["semantic_validation"]["io_assignment_proposals"] = io_allocator.propose_assignment(io_map, requests)
        return output

    return _parse, seen


def _use_bench_copy(app, bench_map: Path) -> None:
    app.io_map_path = bench_map
    app.io_variables = gui.load_io_map_variables(bench_map)
    # La tabla de la GUI debe reflejar el mapa activo: Modo Normal la guarda en cada comando.
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()


def test_gui_experiment_allocates_freezes_and_prepares_without_legacy_block(pipeline, bench_map, monkeypatch):
    app = pipeline["app"]
    _use_bench_copy(app, bench_map)
    base_hash = _hash(bench_map)
    warnings: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, message, **k: warnings.append(message))
    monkeypatch.setattr(gui, "record_trial_summary", lambda *a, **k: None)
    parse, seen = _allocating_parse(
        [{"functional_name_hint": "Q_Motor", "role_text": "motor"}],
        {"trigger_input": "I_Start", "output": "Q_Motor"}, ["I_Start", "Q_Motor"]
    )
    monkeypatch.setattr(gui, "parse_command", parse)

    trial_directory = _arm_experiment_trial(app)
    assert app._prepare_trial_working_map() is True
    _run(app)

    assert not any("ensayo experimental activo" in message for message in warnings)
    # El parser/allocator vio el inventario completo del working map (24 canales, sin filtro legacy).
    assert len([v for v in seen[0]["variables"] if trial_io_map.physical_signal(v.get("location"))]) == 24
    record = trial_model.load_trial(trial_directory)
    assert record["io_map"]["frozen"] is True and record["io_map"]["base_map_id"] == "mapa_banco_fisico"
    assert record["io_map"]["discarded"] is True
    assert Path(record["io_map"]["snapshot_path"]) == trial_directory / "io_map_snapshot.json"
    snapshot = json.loads((trial_directory / "io_map_snapshot.json").read_text(encoding="utf-8"))
    assert any(binding["functional_name"] == "Q_Motor" for binding in snapshot["bindings"])
    assert not (trial_directory / "working_io_map.json").exists()
    assert record["final_status"] == trial_model.FINAL_STATUS_PREPARED
    assert record["lifecycle_state"] == trial_io_map.STATE_RUNTIME_READY
    assert len(pipeline["download_calls"]) == 1
    assert _hash(bench_map) == base_hash, "el mapa base no debe cambiar por efecto del ensayo"


def test_gui_allocation_failure_stops_before_compile_and_leaves_no_partial_map(pipeline, bench_map, monkeypatch):
    app = pipeline["app"]
    _use_bench_copy(app, bench_map)
    base_hash = _hash(bench_map)
    monkeypatch.setattr(gui, "record_trial_summary", lambda *a, **k: None)
    compile_calls: list[Any] = []
    monkeypatch.setattr(gui, "validate_package_with_tia", lambda *a, **k: compile_calls.append(a) or {})
    parse, _ = _allocating_parse(
        io_allocator.extract_io_assignment_requests("Usa Q9.5 para el motor 9"),
        {"output": "Q_Motor_9"}, ["Q_Motor_9"]
    )
    monkeypatch.setattr(gui, "parse_command", parse)

    trial_directory = _arm_experiment_trial(app)
    app._prepare_trial_working_map()
    assert _run(app) is False

    record = trial_model.load_trial(trial_directory)
    assert record["final_status"] == trial_model.FINAL_STATUS_FAIL
    assert record["io_map"]["error"] == trial_io_map.ERROR_ALLOCATION_FAILED
    assert record["io_map"]["frozen"] is False
    assert not (trial_directory / "io_map_snapshot.json").exists()
    assert not (trial_directory / "working_io_map.json").exists()
    assert compile_calls == [] and pipeline["download_calls"] == []
    assert app.active_trial is None
    assert _hash(bench_map) == base_hash


def test_new_trial_record_has_io_map_reference_and_lifecycle(tmp_path):
    record = trial_model.new_trial_record("D12", "V2", "TEXT", 1)
    assert record["lifecycle_state"] == "CREATED"
    assert record["io_map"]["snapshot_path"] is None and record["io_map"]["frozen"] is False
    assert record["runtime"] is None and record["functional"] is None


def test_start_trial_creates_trial_scoped_working_map(pipeline, bench_map, monkeypatch):
    app = pipeline["app"]
    _use_bench_copy(app, bench_map)
    monkeypatch.setattr(gui, "record_trial_summary", lambda *a, **k: None)
    monkeypatch.setattr(gui, "next_trial_id", lambda root: "TRIAL_TEST")  # contador legacy real intacto
    app.work_mode_var.set("Experimentacion")
    app._on_work_mode_changed()
    case_label = next(iter(app._experiment_profiles_by_case))
    app.experiment_case_var.set(case_label)
    app.experiment_speaker_var.set("P01")

    assert app.start_trial() is True

    info = app.active_trial["new_trial"]
    working_path = Path(info["io_map"]["working_map_path"])
    assert working_path.parent == Path(info["dir"]) and working_path.name == "working_io_map.json"
    assert info["lifecycle_state"] == trial_io_map.STATE_PREPARING
    record = trial_model.load_trial(Path(info["dir"]))
    assert record["lifecycle_state"] == "PREPARING"
    assert record["io_map"]["physical_channel_count"] == 24
    app._cancel_active_trial("fin del test")
    assert not working_path.exists()


# ---------- 16: Modo Normal no cambia ----------

def test_normal_mode_still_persists_assignments_on_the_active_map(pipeline, bench_map, monkeypatch):
    app = pipeline["app"]
    _use_bench_copy(app, bench_map)
    parse, seen = _allocating_parse(
        io_allocator.extract_io_assignment_requests("Usa Q8.7 para el motor 7"),
        {"trigger_input": "I_Start", "output": "Q_Motor_7"}, ["I_Start", "Q_Motor_7"]
    )
    monkeypatch.setattr(gui, "parse_command", parse)
    assert app.work_mode_var.get() == "Normal" and app.active_trial is None

    _run(app)

    active_map = json.loads(bench_map.read_text(encoding="utf-8"))
    assert _by_address(active_map, "%QX8.7")["name"] == "Q_Motor_7"
    assert app._trial_io() is None
    assert pipeline["download_calls"] == []


# ---------- 15: mapas reales intactos ----------

def test_real_maps_unchanged_by_this_module():
    for path in _REAL_MAPS:
        assert _hash(path) == _HASHES_AT_IMPORT[str(path)], f"{path.name} fue modificado durante los tests"
