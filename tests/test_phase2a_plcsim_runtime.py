"""
Fase 2A: integracion de SOLO LECTURA con S7-PLCSIM Advanced V5 (Runtime API).

Las decisiones (estado, red, cpu_run_confirmed, trial.runtime) se prueban como funciones puras
sobre reportes crudos del bridge; la GUI con get_plcsim_runtime_status simulado. El bridge C#
real solo se ejecuta en su accion `self_test` (logica pura, sin PLCSIM). Los mapas reales nunca
se tocan (test final de hashes).
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
import plcsim_runtime  # noqa: E402
from trial_experiments import trial_model  # noqa: E402
from utils import get_project_root  # noqa: E402

from test_phase1_download_and_trials import (  # noqa: E402
    _arm_experiment_trial,
    _run,
    pipeline,
)
from test_execute_full_pipeline import temp_map, _tia_ready  # noqa: E402

__all__ = ["pipeline", "temp_map", "_tia_ready"]

_REAL_MAPS = [
    get_project_root() / "data" / "plc_maps" / "mapa_banco_fisico_base.json",
    get_project_root() / "data" / "plc_maps" / "mapa_simulacion_completo.json",
]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_HASHES_AT_IMPORT = {str(path): _hash(path) for path in _REAL_MAPS}

_TIA_CONFIG = {
    "download_targets": {
        "normal": {
            "target_type": "PLCSIM_ADVANCED",
            "target_name": "PLCSIM Advanced - TESIS_PLC_SIM",
            "configuration_mode": "PN/IE",
            "pc_interface": "Siemens PLCSIM Virtual Ethernet Adapter",
            "target_interface": "1 X1",
        }
    },
    "plcsim_runtime": {"instance_name": "TESIS_PLC_SIM"},
}

_ADAPTER = {
    "match_pattern": "PLCSIM Virtual Ethernet Adapter", "found": True, "ambiguous": False,
    "name": "Ethernet 3", "description": "Siemens PLCSIM Virtual Ethernet Adapter",
    "operational_status": "Up", "ip": "192.168.0.12", "subnet_mask": "255.255.255.0",
}


def _raw(state: str = "Run", suites: list[dict[str, Any]] | None = None, adapter: dict[str, Any] | None = None,
         status: str = "PLCSIM_RUNTIME_PASSED", **extra: Any) -> dict[str, Any]:
    raw = {
        "status": status,
        "instance_found": True,
        "registered_instances": [{"id": 0, "name": "TESIS_PLC_SIM"}],
        "windows_adapter": dict(_ADAPTER if adapter is None else adapter),
        "instance": {
            "id": 0, "name": "TESIS_PLC_SIM", "operating_state": state, "cpu_type": "CPU1516",
            "controller_name": "PLC_1", "controller_short_designation": "CPU 1516-3 PN/DP",
            "communication_interface": "TCPIP", "read_errors": [],
            "ip_suites": suites if suites is not None else [
                {"index": 0, "ip": "192.168.0.1", "subnet_mask": "255.255.255.0", "default_gateway": "192.168.0.1"},
                {"index": 1, "ip": "192.168.1.1", "subnet_mask": "255.255.255.0", "default_gateway": "192.168.1.1"},
            ],
        },
        "errors": [], "warnings": [],
    }
    raw.update(extra)
    return raw


def _evaluate(raw: dict[str, Any]) -> dict[str, Any]:
    return plcsim_runtime.evaluate_runtime_report(raw, _TIA_CONFIG)


# ---------- 1-3: deteccion de la instancia ----------

def test_unique_instance_is_connected():
    report = _evaluate(_raw())
    assert report["status"] == plcsim_runtime.STATUS_CONNECTED
    assert report["connected"] is True
    assert report["instance_name"] == "TESIS_PLC_SIM"
    assert report["cpu_type"] == "CPU1516"


def test_absent_instance_reports_not_found_and_lists_found_instances():
    raw = {
        "status": "PLCSIM_INSTANCE_NOT_FOUND", "instance_found": False,
        "registered_instances": [{"id": 0, "name": "Otra_Instancia"}],
        "windows_adapter": _ADAPTER,
        "errors": ["Instancia 'TESIS_PLC_SIM' no encontrada. Instancias registradas: Otra_Instancia."],
    }
    report = _evaluate(raw)
    assert report["status"] == "PLCSIM_INSTANCE_NOT_FOUND"
    assert report["connected"] is False and report["cpu_state"] is None
    log = "\n".join(plcsim_runtime.format_log_lines(report))
    assert "Otra_Instancia" in log and "[PLCSIM RUNTIME]" in log


def test_duplicate_instance_is_ambiguous_never_connected():
    raw = {
        "status": "PLCSIM_INSTANCE_AMBIGUOUS", "instance_found": False,
        "registered_instances": [{"id": 0, "name": "TESIS_PLC_SIM"}, {"id": 1, "name": "tesis_plc_sim"}],
        "errors": ["Hay 2 instancias llamadas 'TESIS_PLC_SIM'."],
    }
    report = _evaluate(raw)
    assert report["status"] == "PLCSIM_INSTANCE_AMBIGUOUS"
    assert report["connected"] is False
    assert report["cpu_run"] is False


# ---------- 4-6: estado de la CPU y cpu_run_confirmed ----------

def test_run_state_confirms_run_only_when_start_was_requested():
    report = _evaluate(_raw("Run"))
    assert report["cpu_state"] == "RUN" and report["cpu_run"] is True
    assert plcsim_runtime.is_cpu_run_confirmed({"cpu_run_requested": True}, report) is True
    assert plcsim_runtime.is_cpu_run_confirmed({"cpu_run_requested": False}, report) is False


def test_stop_state_never_confirms_run_even_after_successful_download():
    report = _evaluate(_raw("Stop"))
    assert report["connected"] is True
    assert report["cpu_state"] == "STOP" and report["cpu_run"] is False
    download = {"download_success": True, "start_module_success": True, "cpu_run_requested": True}
    assert plcsim_runtime.is_cpu_run_confirmed(download, report) is False


@pytest.mark.parametrize("status", ["PLCSIM_RUNTIME_UNAVAILABLE", "PLCSIM_RUNTIME_TIMEOUT", "PLCSIM_API_NOT_AVAILABLE"])
def test_disconnected_runtime_leaves_cpu_state_unknown(status):
    report = _evaluate({"status": status, "errors": ["sin Runtime Manager"]})
    assert report["connected"] is False
    assert report["cpu_state"] is None and report["cpu_run"] is False
    assert plcsim_runtime.is_cpu_run_confirmed({"cpu_run_requested": True}, report) is None


# ---------- 7-8: red (informativa, nunca se modifica) ----------

def test_same_subnet_matches_and_reports_the_matching_controller_ip():
    report = _evaluate(_raw())
    assert report["network_match"] is True
    assert report["network_status"] == "MATCH"
    assert report["controller_ip"] == "192.168.0.1"
    assert report["adapter_ip"] == "192.168.0.12"


def test_different_subnet_is_informational_mismatch():
    adapter = dict(_ADAPTER, ip="10.0.0.5", subnet_mask="255.255.255.0")
    report = _evaluate(_raw(adapter=adapter))
    assert report["network_match"] is False
    assert report["network_status"] == plcsim_runtime.NETWORK_MISMATCH
    assert any(plcsim_runtime.NETWORK_MISMATCH in warning for warning in report["warnings"])
    # Informativo: la conexion y el estado de la CPU no cambian.
    assert report["connected"] is True and report["cpu_state"] == "RUN"
    # Adaptador sin IP -> no se puede comprobar (nunca se asume).
    unknown = _evaluate(_raw(adapter={"found": False}))
    assert unknown["network_match"] is None and unknown["network_status"] == "UNKNOWN"


# ---------- 9: serializacion del reporte ----------

def test_runtime_report_serializes_with_three_separate_network_sources(tmp_path):
    report = _evaluate(_raw())
    path = plcsim_runtime.write_runtime_report(tmp_path, report)
    assert path.name == "plcsim_runtime_report.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    sources = loaded["network_sources"]
    assert sources["download_configuration"]["target_interface"] == "1 X1"
    assert sources["runtime"]["ip_suites"][0]["ip"] == "192.168.0.1"
    assert sources["windows"]["ip"] == "192.168.0.12"
    assert sources["project"]["project_plc_ip"] is None
    assert loaded["cpu_state"] == "RUN" and loaded["connected"] is True


# ---------- 10-11: GUI ----------

def test_gui_shows_configured_target_without_claiming_connection(app):
    app._runtime_worker_active = False
    app.plc_runtime_var.set("Runtime: NO VERIFICADO")
    app.plc_cpu_var.set("CPU: -")
    app._render_configured_target()
    assert app.plc_config_var.get().startswith("Configurado:")
    assert not app.plc_runtime_var.get().startswith("Runtime: CONECTADO")
    assert "RUN" not in app.plc_cpu_var.get()


@pytest.fixture
def simulated_normal_target(monkeypatch):
    # These assertions concern PLCSIM; the operator's current destination may be a physical PLC.
    target = {**_TIA_CONFIG['download_targets']['normal'], 'instance_name':'TESIS_PLC_SIM',
              'target_address':'192.168.0.1'}
    monkeypatch.setattr(gui.plc_targets, 'load_normal_target', lambda root: dict(target))


def test_gui_shows_run_only_when_runtime_confirms(app, monkeypatch, simulated_normal_target):
    monkeypatch.setattr(gui.threading, "Thread", _SyncThread)
    reports = iter([
        _evaluate({"status": "PLCSIM_RUNTIME_UNAVAILABLE", "errors": ["x"]}),
        _evaluate(_raw("Stop")),
        _evaluate(_raw("Run")),
    ])
    monkeypatch.setattr(gui, "get_plcsim_runtime_status", lambda root: next(reports))

    app.refresh_plc_runtime_status()
    assert app.plc_runtime_var.get().startswith("Runtime: NO CONECTADO")
    assert "RUN" not in app.plc_cpu_var.get()

    app.refresh_plc_runtime_status()
    assert app.plc_runtime_var.get().startswith("Runtime: CONECTADO")
    assert app.plc_cpu_var.get().startswith("CPU: STOP")

    app.refresh_plc_runtime_status()
    assert app.plc_cpu_var.get().startswith("CPU: RUN")
    assert "misma subred" in app.plc_network_var.get()
    assert app.refresh_runtime_button.cget("state") == "normal"


def test_normal_download_auto_refreshes_runtime_and_fills_cpu_run_confirmed(pipeline, monkeypatch, simulated_normal_target):
    app = pipeline["app"]
    calls: list[int] = []

    def _status(root):
        calls.append(1)
        return _evaluate(_raw("Run"))

    monkeypatch.setattr(gui, "get_plcsim_runtime_status", _status)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    _run(app)
    assert calls == []  # compilar en Modo Normal nunca consulta ni descarga
    app.load_program_to_plc()
    app._poll_download_worker()
    assert calls == [1]
    download_report = json.loads((pipeline["package_dir"] / "tia_download_report.json").read_text(encoding="utf-8"))
    assert download_report["cpu_run_confirmed"] is True
    assert download_report["cpu_run_confirmed_source"] == "PLCSIM_RUNTIME_API"
    assert (pipeline["package_dir"] / "plcsim_runtime_report.json").exists()


# ---------- 12-14: trial.json ----------

def test_experiment_fills_trial_runtime_and_keeps_functional_null_and_prepared(pipeline, monkeypatch):
    app = pipeline["app"]
    monkeypatch.setattr(gui, "get_plcsim_runtime_status", lambda root: _evaluate(_raw("Run")))
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    trial_directory = _arm_experiment_trial(app)

    _run(app)

    record = trial_model.load_trial(trial_directory)
    assert record["runtime"] == {
        "connected": True, "instance_name": "TESIS_PLC_SIM", "cpu_state": "RUN",
        "controller_ip": "192.168.0.1", "adapter_ip": "192.168.0.12", "network_match": True,
    }
    assert record["download"]["cpu_run_confirmed"] is True
    assert record["stages"]["runtime_connection_success"] is True
    assert record["functional"] is None and record["safety"] is None and record["oracle"] is None
    assert record["stages"]["functional_success"] is None and record["stages"]["safety_success"] is None
    assert record["final_status"] == trial_model.FINAL_STATUS_PREPARED
    assert (trial_directory / "plcsim_runtime_report.json").exists()


@pytest.mark.parametrize("runtime_raw", [
    {"status": "PLCSIM_RUNTIME_UNAVAILABLE", "errors": ["sin PLCSIM"]},
    "STOP",
])
def test_experiment_stays_prepared_never_pass_when_runtime_not_run(pipeline, monkeypatch, runtime_raw):
    app = pipeline["app"]
    raw = _raw("Stop") if runtime_raw == "STOP" else runtime_raw
    monkeypatch.setattr(gui, "get_plcsim_runtime_status", lambda root: _evaluate(raw))
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    trial_directory = _arm_experiment_trial(app)

    _run(app)

    record = trial_model.load_trial(trial_directory)
    assert record["final_status"] == trial_model.FINAL_STATUS_PREPARED
    assert record["download"]["cpu_run_confirmed"] in (False, None)
    assert record["runtime"]["cpu_state"] != "RUN"
    assert record["functional"] is None


# ---------- Bridge: solo lectura + self-test ----------

_FORBIDDEN_CALLS = (
    "RegisterInstance(", "RegisterCustomInstance(", "PowerOn(", "PowerOff(", ".Run(", ".Stop(",
    "MemoryReset(", "SetIPSuite(", "SetNetInterfaceMapping(", "SetNetInterfaceBindings(",
    "NetworkMode =", ".Write(", "WriteSignals(", "UnregisterInstance(", "OperatingMode =",
    "WriteInt", "WriteUInt", "WriteDouble(", "WriteString(", "WriteChar(", "WriteWChar(",
)


def test_bridge_source_never_calls_write_or_control_apis():
    source = (get_project_root() / "plcsim_runtime_bridge" / "Program.cs").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("//") and "///" not in line)
    offenders = [call for call in _FORBIDDEN_CALLS if call in code]
    assert offenders == [], f"El bridge nunca controla la CPU ni escribe por nombre salvo variables internas BOOL/REAL: {offenders}"
    # P01-P12: la UNICA escritura por nombre es WriteBool/WriteFloat de una variable interna ya resuelta.
    by_name = [line.strip() for line in code.splitlines() if "WriteBool(" in line or "WriteFloat(" in line]
    assert by_name == ["instance.WriteFloat(signal.ApiName, (float)Convert.ToDouble(value));",
                       "instance.WriteBool(signal.ApiName, Convert.ToBoolean(value));"], by_name


def test_bridge_self_test_pure_logic():
    if not plcsim_runtime.DEFAULT_RUNTIME_API_DLL.exists():
        pytest.skip("Runtime API de PLCSIM Advanced no instalada en este entorno.")
    raw = plcsim_runtime.run_runtime_bridge("self_test", get_project_root())
    if raw.get("status") == "PLCSIM_BRIDGE_BUILD_FAILED":
        pytest.skip(f"Bridge no compilable: {raw.get('errors')}")
    checks = {check["check"]: check for check in raw["checks"]}
    assert raw["status"] == "PLCSIM_RUNTIME_SELF_TEST_PASSED"
    assert checks["instance.unique"]["actual"] == "1"
    assert checks["instance.absent"]["actual"] == ""
    assert checks["instance.duplicate"]["actual"] == "0,1"
    assert checks["instance.no_partial_match"]["actual"] == ""
    assert all(check["passed"] for check in raw["checks"])


# ---------- 15: mapas reales intactos ----------

def test_real_maps_unchanged_by_this_module():
    for path in _REAL_MAPS:
        assert _hash(path) == _HASHES_AT_IMPORT[str(path)], f"{path.name} fue modificado durante los tests"


class _SyncThread:
    """Ejecuta sincronicamente el hilo 'plcsim-runtime' de gui.py."""

    def __init__(self, target=None, name=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        if self._target:
            self._target()
