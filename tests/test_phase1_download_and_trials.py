"""
Fase 1 del nuevo Modo Experimentacion: descarga automatizada (TIA Openness DownloadProvider),
Start Module, comportamiento diferenciado Modo Normal / Modo Experimentacion y el nuevo modelo
de ensayo (trial.json, trial_id D12_V2_TEXT_001).

El bridge real (TIA Portal + PLCSIM Advanced) no se ejecuta aqui: la logica pura del bridge
(politica de DownloadConfiguration) se prueba con su accion `self_test`, y el pipeline de la GUI
con `download_program_to_plc` / `validate_package_with_tia` simulados. Los mapas reales nunca se
tocan (ver test final de hashes).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402
import tia_openness  # noqa: E402
from trial_experiments import trial_model  # noqa: E402
from utils import get_project_root  # noqa: E402

from test_execute_full_pipeline import (  # noqa: E402
    _RealThread,
    _base_semantic_output,
    _mock_package_result,
    temp_map,
    _tia_ready,
)

__all__ = ["temp_map", "_tia_ready"]

_REAL_MAPS = [
    get_project_root() / "data" / "plc_maps" / "mapa_banco_fisico.json",
    get_project_root() / "data" / "plc_maps" / "mapa_simulacion_completo.json",
]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_HASHES_AT_IMPORT = {str(path): _hash(path) for path in _REAL_MAPS}


class _SyncTiaThread:
    """Ejecuta sincronicamente los hilos TIA de gui.py (compilacion y descarga); cualquier otro
    hilo del proceso (p.ej. subprocess.Popen) recibe el threading.Thread real."""

    def __new__(cls, target=None, name=None, daemon=None, **kwargs):
        if name not in ("tia-openness", "tia-download", "plcsim-runtime", "oracle-runner"):
            return _RealThread(target=target, name=name, daemon=daemon, **kwargs)
        return super().__new__(cls)

    def __init__(self, target=None, name=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        if self._target:
            self._target()


def _successful_download(package_dir: Path, **overrides: Any) -> dict[str, Any]:
    report = {
        "status": "SUCCESS",
        "bridge_status": "TIA_DOWNLOAD_PASSED",
        "target_type": "PLCSIM_ADVANCED",
        "target_name": "PLCSIM Advanced",
        "download_success": True,
        "start_module_requested": True,
        "start_module_success": True,
        "cpu_run_requested": True,
        "cpu_run_confirmed": None,
        "warnings": [],
        "errors": [],
        "duration_ms": 1234,
        "success": True,
    }
    report.update(overrides)
    (package_dir / "tia_download_report.json").write_text(json.dumps(report), encoding="utf-8")
    return report


@pytest.fixture
def pipeline(app, temp_map, tmp_path, monkeypatch, _tia_ready):
    """Pipeline completo con parse/generacion/compilacion/descarga simulados y todo lo escrito en tmp."""
    monkeypatch.setattr(gui.threading, "Thread", _SyncTiaThread)
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)
    monkeypatch.setattr(gui, "trial_dir", lambda root, case_id, trial_id: tmp_path / "legacy" / case_id / trial_id)
    monkeypatch.setattr(trial_model, "get_results_experiments_dir", lambda root: tmp_path / "results" / "experiments")

    semantic_output = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_output)

    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "siemens_source.scl").write_text("(* scl *)", encoding="utf-8")
    (package_dir / "variables.json").write_text("[]", encoding="utf-8")
    state: dict[str, Any] = {"verification_valid": True, "compile_status": "TIA_COMPILATION_PASSED"}
    monkeypatch.setattr(
        gui, "generate_project_package",
        lambda **kwargs: _mock_package_result(package_dir, is_valid=state["verification_valid"])
    )

    def _fake_compile(package_dir_arg, project_root_arg):
        report = {
            "status": state["compile_status"],
            "result_path": str(package_dir_arg / "tia_compile_report.json"),
            "bridge_return_code": 0, "bridge_stdout": "", "bridge_stderr": ""
        }
        (package_dir_arg / "tia_compile_report.json").write_text(json.dumps(report), encoding="utf-8")
        return report

    monkeypatch.setattr(gui, "validate_package_with_tia", _fake_compile)

    download_calls: list[dict[str, Any]] = []

    def _fake_download(package_dir_arg, project_root_arg, purpose="normal"):
        download_calls.append({"package_dir": package_dir_arg, "purpose": purpose})
        return state.get("download_factory", _successful_download)(package_dir_arg)

    monkeypatch.setattr(gui, "download_program_to_plc", _fake_download)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    # Fase 3A: estas pruebas cubren Fase 1/2A (cierre PREPARED); el Oracle Runner se prueba
    # aparte (test_phase3a_oracle.py), asi que aqui ningun caso tiene Oracle.
    monkeypatch.setattr(gui, "find_case_oracle", lambda root, case_id: None)
    # Fase 2A: la lectura post-descarga de la Runtime API se simula (nunca el bridge real aqui).
    monkeypatch.setattr(gui, "get_plcsim_runtime_status", lambda root: {"status": "CONNECTED", "connected": True, "instance_name": "TESIS_PLC_SIM", "cpu_state": "RUN", "controller_ip": "192.168.0.1", "adapter_ip": "192.168.0.12", "network_match": True, "errors": [], "warnings": []})

    app.command_textbox.delete("1.0", "end")
    app.command_textbox.insert("1.0", "enciende la salida")
    yield {"app": app, "package_dir": package_dir, "download_calls": download_calls, "state": state, "tmp_path": tmp_path}
    app.work_mode_var.set("Normal")
    app.active_trial = None


def _run(app) -> bool:
    result = app.execute_full_pipeline()
    app._poll_tia_worker()
    if app._download_worker_active:
        app._poll_download_worker()
    return result


def _arm_experiment_trial(app) -> Path:
    app.work_mode_var.set("Experimentacion")
    app.active_trial = {
        "trial_id": "TRIAL_TEST", "case_id": "D12", "variant": "V2", "experiment_label": "C1_D12_V2_R01",
        "speaker_id": "P01", "noise_level": "none", "requires_voice": False, "state": "RUNNING"
    }
    app._reset_experiment_stages()
    app._create_new_trial_record(
        {"complexity": "alta"}, "D12", "V2", {"code": "C1", "requires_voice": False, "parser_mode": "llm"}
    )
    return Path(app.active_trial["new_trial"]["dir"])


# ---------- TEST 1 / 2 / 11: Modo Normal ----------

def test_normal_mode_execute_compiles_but_never_downloads(pipeline):
    app = pipeline["app"]
    assert _run(app) is True
    assert pipeline["download_calls"] == []
    assert app._last_compiled_package_dir == pipeline["package_dir"]


def test_normal_mode_load_button_downloads_exactly_once_the_current_package(pipeline):
    app = pipeline["app"]
    _run(app)
    app.load_program_to_plc()
    app._poll_download_worker()
    assert len(pipeline["download_calls"]) == 1
    assert pipeline["download_calls"][0]["package_dir"] == pipeline["package_dir"]
    assert pipeline["download_calls"][0]["purpose"] == tia_openness.DOWNLOAD_PURPOSE_NORMAL


def test_failed_last_execution_disables_load_button(pipeline):
    app = pipeline["app"]
    _run(app)
    assert app.download_plc_button.cget("state") == "normal"

    pipeline["state"]["compile_status"] = "TIA_COMPILATION_FAILED"
    _run(app)
    assert app._last_compiled_package_dir is None
    assert app.download_plc_button.cget("state") == "disabled"


# ---------- TEST 5 / 6: Modo Experimentacion ----------

def test_experiment_compile_success_auto_downloads_and_prepares_trial(pipeline):
    app = pipeline["app"]
    trial_directory = _arm_experiment_trial(app)

    _run(app)

    assert len(pipeline["download_calls"]) == 1
    assert pipeline["download_calls"][0]["purpose"] == tia_openness.DOWNLOAD_PURPOSE_EXPERIMENT
    record = trial_model.load_trial(trial_directory)
    assert record["trial_id"] == "D12_V2_TEXT_001"
    assert record["final_status"] == trial_model.FINAL_STATUS_PREPARED
    assert record["stages"]["compile_success"] is True
    assert record["stages"]["download_success"] is True
    assert record["stages"]["start_module_success"] is True
    assert record["functional"] is None and record["oracle"] is None
    assert record["stages"]["functional_success"] is None
    assert (trial_directory / "program.scl").exists()
    assert (trial_directory / "tia_download_report.json").exists()
    assert app.experiment_status_var.get().startswith("Ensayo preparado en PLCSIM Advanced.")


def test_experiment_compile_failure_never_downloads(pipeline):
    app = pipeline["app"]
    pipeline["state"]["compile_status"] = "TIA_COMPILATION_FAILED"
    trial_directory = _arm_experiment_trial(app)

    _run(app)

    assert pipeline["download_calls"] == []
    record = trial_model.load_trial(trial_directory)
    assert record["final_status"] == trial_model.FINAL_STATUS_FAIL
    assert record["stages"]["compile_success"] is False
    assert record["stages"]["download_success"] is None


def test_experiment_download_failure_is_infrastructure_error_not_prepared(pipeline):
    app = pipeline["app"]
    pipeline["state"]["download_factory"] = lambda package_dir: _successful_download(
        package_dir, status="EXPERIMENT_TARGET_NOT_SIMULATION", download_success=False,
        start_module_success=False, start_module_requested=False, success=False,
        errors=["La interfaz PG/PC resuelta no corresponde a PLCSIM."]
    )
    trial_directory = _arm_experiment_trial(app)

    _run(app)

    record = trial_model.load_trial(trial_directory)
    assert record["final_status"] == trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR
    assert record["stages"]["download_success"] is False


# ---------- TEST 7: destino experimental que no es simulacion ----------

def test_experiment_target_not_simulation_aborts_before_invoking_bridge(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    tia_openness.save_tia_config(
        {
            "project_path": "C:/TIA/Demo.ap18",
            "download_targets": {"experiment": {"target_type": "PHYSICAL_PLC", "target_name": "S7-1500 real"}}
        },
        project_root
    )

    def _must_not_run(*args, **kwargs):
        raise AssertionError("el bridge nunca debe invocarse para un destino experimental no simulado")

    monkeypatch.setattr(tia_openness, "diagnose_tia_openness", _must_not_run)
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    report = tia_openness.download_program_to_plc(package_dir, project_root, tia_openness.DOWNLOAD_PURPOSE_EXPERIMENT)

    assert report["status"] == "EXPERIMENT_TARGET_NOT_SIMULATION"
    assert report["download_success"] is False
    assert report["cpu_run_requested"] is False
    assert report["cpu_run_confirmed"] is None
    assert (package_dir / "tia_download_report.json").exists()


def test_download_request_carries_explicit_target_and_simulation_guard(tmp_path):
    project_root = tmp_path / "project"
    tia_openness.save_tia_config({"project_path": "C:/TIA/Demo.ap18"}, project_root)
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    _, _, experiment_request = tia_openness.prepare_download_request(
        package_dir, project_root, tia_openness.DOWNLOAD_PURPOSE_EXPERIMENT
    )
    assert experiment_request["require_simulation"] is True
    assert experiment_request["target_type"] == "PLCSIM_ADVANCED"
    assert experiment_request["start_modules"] is True
    assert experiment_request["download_scope"] == "SOFTWARE"

    _, _, normal_request = tia_openness.prepare_download_request(package_dir, project_root)
    assert normal_request["require_simulation"] is False


# ---------- TEST 3 / 4 / 8: politica de descarga ----------

def test_failed_download_never_reports_start_module_or_run():
    """TEST 4: si la descarga falla, Start Module y RUN nunca se reportan como exitosos."""
    raw = {
        "status": "TIA_DOWNLOAD_FAILED", "success": False,
        "start_module_requested": True, "start_module_success": True, "cpu_run_requested": True
    }
    target = tia_openness.resolve_download_target({}, "experiment")
    import time as _time
    from datetime import datetime as _dt
    report = tia_openness._finalize_download_report(raw, target, "experiment", _dt.now(), _time.perf_counter())
    assert report["download_success"] is False
    assert report["start_module_success"] is False
    assert report["cpu_run_requested"] is False
    assert report["cpu_run_confirmed"] is None
    assert report["status"] == "TIA_DOWNLOAD_FAILED"


def test_bridge_download_configuration_policy_self_test(tmp_path):
    """TEST 3 (StartModules -> StartModule) y TEST 8 (configuracion desconocida -> rechazo),
    ejecutados en el bridge compilado real, sin abrir TIA Portal."""
    build = tia_openness.build_openness_bridge(get_project_root())
    if not build.get("built"):
        pytest.skip(f"Bridge no compilable en este entorno: {build.get('errors')}")
    result_path = tmp_path / "self_test_result.json"
    request_path = tmp_path / "self_test_request.json"
    request_path.write_text(json.dumps({"action": "self_test", "result_path": str(result_path)}), encoding="utf-8")
    completed = subprocess.run([build["exe_path"], str(request_path)], capture_output=True, text=True, timeout=30, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr

    report = json.loads(result_path.read_text(encoding="utf-8-sig"))
    decisions = {check["decision"]: check for check in report["checks"] if "decision" in check}
    assert decisions["plcsim.start"]["allowed"] is True
    assert decisions["plcsim.start"]["selection"] == "StartModule"
    assert decisions["plcsim.unknown"]["allowed"] is False
    assert decisions["plcsim.password"]["allowed"] is False
    assert decisions["physical.reinit"]["allowed"] is False
    assert all(check["passed"] for check in report["checks"])


# ---------- TEST 9 / 10: nuevo modelo de ensayo ----------

def test_trial_id_is_built_from_case_variant_input_mode_and_number(tmp_path):
    assert trial_model.build_trial_id("D12", "V2", "TEXT", 1) == "D12_V2_TEXT_001"
    assert trial_model.build_trial_id("P03", "V1", "VOICE_NOISE", 17) == "P03_V1_VOICE_NOISE_017"
    with pytest.raises(ValueError):
        trial_model.build_trial_id("D12", "V2", "LLM", 1)
    with pytest.raises(ValueError):
        trial_model.build_trial_id("X99", "V2", "TEXT", 1)

    assert trial_model.next_trial_number(tmp_path, "D12", "V2", "TEXT") == 1
    (trial_model.trial_directory(tmp_path, "D12", "V2", "D12_V2_TEXT_001")).mkdir(parents=True)
    assert trial_model.next_trial_number(tmp_path, "D12", "V2", "TEXT") == 2
    assert trial_model.next_trial_number(tmp_path, "D12", "V2", "VOICE_CLEAN") == 1

    assert trial_model.input_mode_from_selection(False, "none") == "TEXT"
    assert trial_model.input_mode_from_selection(True, "none") == "VOICE_CLEAN"
    assert trial_model.input_mode_from_selection(True, "high") == "VOICE_NOISE"


def test_trial_json_serializes_future_fields_as_null(tmp_path):
    record = trial_model.new_trial_record("D12", "V2", "TEXT", 1, command_text="cmd", complexity="alta")
    directory = trial_model.trial_directory(tmp_path, "D12", "V2", record["trial_id"])
    trial_model.save_trial(directory, record)
    loaded = json.loads((directory / "trial.json").read_text(encoding="utf-8"))

    assert loaded["complexity"] == "HIGH"
    assert loaded["runtime"] is None and loaded["oracle"] is None
    assert loaded["functional"] is None and loaded["safety"] is None
    assert loaded["oracle_reference"] == {"oracle_id": None, "oracle_version": None, "oracle_hash": None}
    assert all(value is None for value in loaded["timing"].values())
    assert all(value is None for value in loaded["stages"].values())
    assert loaded["final_status"] is None
    assert "parser_mode" not in loaded["trial_id"]

    trial_model.update_trial(directory, {"stages": {"compile_success": True}})
    trial_model.finalize_trial(directory, trial_model.FINAL_STATUS_PREPARED)
    reloaded = trial_model.load_trial(directory)
    assert reloaded["stages"]["compile_success"] is True
    assert reloaded["stages"]["functional_success"] is None
    assert reloaded["final_status"] == "PREPARED"
    with pytest.raises(ValueError):
        trial_model.finalize_trial(directory, "PASSED_BY_GUESS")


# ---------- TEST 12: mapas reales intactos ----------

def test_real_maps_unchanged_by_this_module():
    for path in _REAL_MAPS:
        assert _hash(path) == _HASHES_AT_IMPORT[str(path)], f"{path.name} fue modificado durante los tests"
