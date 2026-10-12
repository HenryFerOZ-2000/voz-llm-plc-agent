"""
Fase 2B: Runtime I/O BOOL con PLCSIM Advanced (infraestructura, NO Oracle).

pytest NUNCA toca el Runtime real: las operaciones pasan por un bridge simulado (_FakePlcsim) que
reproduce el formato de reporte del bridge C# y la memoria de PLCSIM (imagen de entradas/salidas
+ un enclavamiento Start/Stop). La logica pura del bridge C# se prueba con su accion self_test
(sin PLCSIM). Las senales salen siempre de un io_map_snapshot.json real generado con
trial_io_map sobre una COPIA del mapa del banco; los mapas reales no se tocan (test de hashes).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402
import io_allocator  # noqa: E402
import plcsim_runtime  # noqa: E402
import plcsim_runtime_io as rio  # noqa: E402
from trial_experiments import trial_io_map  # noqa: E402
from utils import get_project_root  # noqa: E402

_MAPS_DIR = get_project_root() / "data" / "plc_maps"
_REAL_MAPS = [
    _MAPS_DIR / "mapa_banco_fisico_base.json",
    _MAPS_DIR / "mapa_simulacion_completo.json",
    _MAPS_DIR / "mapa_pid_simulacion.json",
    _MAPS_DIR / "mapa_pid_banco_fisico.json",
]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_HASHES_AT_IMPORT = {str(path): _hash(path) for path in _REAL_MAPS}

_CONFIG = {
    "instance_name": "TESIS_PLC_SIM", "io_settle_ms": 0, "io_timeout_seconds": 5,
    "api_dll_path": "x", "windows_adapter_match": "x", "timeout_seconds": 5,
}
_RUN = {"connected": True, "instance_name": "TESIS_PLC_SIM", "cpu_state": "RUN", "status": "CONNECTED"}


# ---------- snapshot real del ensayo (Start/Stop + un analogico) ----------

@pytest.fixture
def snapshot_path(tmp_path) -> Path:
    base = tmp_path / "mapa_banco_fisico.json"
    base.write_bytes((_MAPS_DIR / "mapa_banco_fisico_base.json").read_bytes())
    reference = trial_io_map.create_working_map(tmp_path / "D03_V1_TEXT_001", base)
    working = trial_io_map.load_working_map(Path(reference["working_map_path"]))
    requests = io_allocator.extract_io_assignment_requests("Usa Q8.0 para el motor") + [
        {"functional_name_hint": "I_Start", "role_text": "arranque"},
        {"functional_name_hint": "I_Stop", "role_text": "paro"},
    ]
    proposals = [p for p in io_allocator.propose_assignment(working, requests) if not p.get("blocked")]
    trial_io_map.apply_proposals_to_working_map(Path(reference["working_map_path"]), proposals, "TEXT_EXPLICIT", "PREPARING")
    semantic_output = {
        "intent_id": "INT_MOTOR_START_STOP",
        "parameters": {"start_input": "I_Start", "stop_input": "I_Stop", "output": "Q_Motor", "level": "AI_IW0"},
    }
    frozen = trial_io_map.freeze_working_map(reference, semantic_output, "PREPARING", "D03_V1_TEXT_001")
    return Path(frozen["snapshot_path"])


@pytest.fixture
def program(snapshot_path) -> dict[str, Any]:
    return rio.load_program_signals(snapshot_path)


class _FakePlcsim:
    """Bridge simulado: memoria de bits + tags del programa + enclavamiento Q = (Q or Start) and not Stop."""

    def __init__(self, program: dict[str, Any], cpu_state: str = "RUN", stuck: dict[str, bool] | None = None,
                 cleanup_fails: bool = False, status_override: str | None = None) -> None:
        self.bits: dict[tuple[str, int, int], bool] = {}
        self.program = program
        self.cpu_state = cpu_state
        self.stuck = stuck or {}
        self.cleanup_fails = cleanup_fails
        self.status_override = status_override
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _key(self, signal):
        return (signal["area"], signal["offset"], signal["bit"])

    def _scan(self):
        signals = self.program["signals"]
        start, stop, motor = (self.bits.get(self._key(signals[n]), False) for n in ("I_Start", "I_Stop", "Q_Motor"))
        self.bits[self._key(signals["Q_Motor"])] = (motor or start) and not stop

    def _write(self, signal, value, report, label):
        effective = self.stuck.get(signal["name"], value)
        self.bits[self._key(signal)] = effective
        self._scan()
        entry = {"label": label, "name": signal["name"], "address": signal["address"], "requested_value": value,
                 "actual_readback": effective, "readback_tag": effective, "match": effective == value,
                 "readback_timestamp": "t"}
        report["writes"].append(entry)
        if effective != value:
            report["status"] = rio.ERROR_READBACK_MISMATCH
            report["errors"].append(f"{signal['name']}: mismatch")
            return False
        return True

    def _read(self, signal, report, label):
        value = self.bits.get(self._key(signal), False)
        entry = {"label": label, "name": signal["name"], "address": signal["address"], "value": value,
                 "value_by_tag": value, "source": "address", "timestamp": "t"}
        report["reads"].append(entry)
        report["observations"].append(entry)
        return True

    def _cleanup(self, names, report):
        inputs = []
        for name in names:
            signal = self.program["signals"][name]
            if not self.cleanup_fails:
                self.bits[self._key(signal)] = False
            restored = not self.bits.get(self._key(signal), False)
            inputs.append({"name": name, "address": signal["address"], "readback": not restored, "restored": restored})
        ok = all(item["restored"] for item in inputs)
        report["cleanup"] = {"performed": True, "success": ok, "inputs": inputs, "timestamp": "t"}
        if not ok:
            report["errors"].append("PLCSIM_IO_CLEANUP_FAILED")
            if report["status"] == "PLCSIM_IO_PASSED":
                report["status"] = rio.ERROR_CLEANUP_FAILED

    def __call__(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((action, payload))
        report = {"status": "PLCSIM_IO_PASSED", "cpu_state": self.cpu_state, "writes": [], "reads": [],
                  "observations": [], "errors": [], "warnings": []}
        if self.status_override:
            return {**report, "status": self.status_override, "errors": [self.status_override]}
        written: list[str] = []
        if action == "write_input":
            if not self._write(payload["signal"], payload["value"], report, "write"):
                self._cleanup([payload["signal"]["name"]], report)
        elif action == "read_signal":
            for signal in payload["signals"]:
                self._read(signal, report, "read")
        elif action == "restore_inputs":
            report["status"] = "PLCSIM_IO_PASSED"
            self._cleanup([s["name"] for s in payload["signals"]], report)
        elif action == "io_sequence":
            for index, step in enumerate(payload["steps"], 1):
                ok = (self._write(step["signal"], step["value"], report, f"step{index}")
                      if step["op"] == "write" else self._read(step["signal"], report, f"step{index}"))
                if step["op"] == "write" and step["signal"]["name"] not in written:
                    written.append(step["signal"]["name"])
                if not ok:
                    break
            self._cleanup(written, report)
        return report


def _session(program, bridge, target="PLCSIM_ADVANCED", runtime=None):
    return rio.RuntimeIOSession(program, target, runtime or dict(_RUN), Path("."), runtime_config=_CONFIG, bridge=bridge)


# ---------- 1-3: seguridad de escritura ----------

def test_write_blocked_when_target_is_not_plcsim(program):
    bridge = _FakePlcsim(program)
    with pytest.raises(rio.RuntimeIOError) as error:
        _session(program, bridge, target="PHYSICAL_PLC").write_input("I_Start", True)
    assert error.value.code == rio.ERROR_WRITE_NOT_ALLOWED
    assert bridge.calls == [], "nunca se invoca el bridge si el destino no es PLCSIM"


def test_write_blocked_when_runtime_disconnected(program):
    bridge = _FakePlcsim(program)
    runtime = {"connected": False, "status": "PLCSIM_RUNTIME_UNAVAILABLE", "cpu_state": None}
    with pytest.raises(rio.RuntimeIOError) as error:
        _session(program, bridge, runtime=runtime).write_input("I_Start", True)
    assert error.value.code == rio.ERROR_WRITE_NOT_ALLOWED and bridge.calls == []


def test_write_blocked_when_cpu_not_run(program):
    bridge = _FakePlcsim(program)
    with pytest.raises(rio.RuntimeIOError) as error:
        _session(program, bridge, runtime={**_RUN, "cpu_state": "STOP"}).write_input("I_Start", True)
    assert error.value.code == rio.ERROR_CPU_NOT_RUN and bridge.calls == []
    wrong_instance = {**_RUN, "instance_name": "OTRA"}
    assert rio.check_write_allowed("PLCSIM_ADVANCED", wrong_instance, "TESIS_PLC_SIM")[0] == rio.ERROR_WRITE_NOT_ALLOWED


# ---------- 4-8: entradas/salidas BOOL ----------

def test_output_can_never_be_written(program):
    bridge = _FakePlcsim(program)
    with pytest.raises(rio.RuntimeIOError) as error:
        _session(program, bridge).write_input("Q_Motor", True)
    assert error.value.code == rio.ERROR_WRITE_NOT_ALLOWED and bridge.calls == []


def test_bool_input_write_with_correct_readback(program):
    bridge = _FakePlcsim(program)
    result = _session(program, bridge).write_input("I_Start", True)
    assert result["status"] == rio.SUCCESS
    assert result["requested_value"] is True and result["readback"] is True and result["match"] is True
    action, payload = bridge.calls[0]
    assert action == "write_input" and payload["target_type"] == "PLCSIM_ADVANCED"
    assert payload["signal"] == {"name": "I_Start", "address": "%I16.0", "area": "Input", "offset": 16, "bit": 0, "data_type": "BOOL"}


def test_readback_mismatch_fails_and_restores_input(program):
    bridge = _FakePlcsim(program, stuck={"I_Stop": False})
    session = _session(program, bridge)
    result = session.write_input("I_Stop", True)
    assert result["status"] == rio.ERROR_READBACK_MISMATCH
    assert result["match"] is False and result["readback"] is False
    assert session.cleanup["performed"] is True and session.cleanup["success"] is True


def test_bool_output_can_be_read(program):
    bridge = _FakePlcsim(program)
    session = _session(program, bridge)
    session.write_input("I_Start", True)
    result = session.read_signals(["Q_Motor"])
    assert result["status"] == rio.SUCCESS
    assert result["values"] == [{"name": "Q_Motor", "address": "%Q8.0", "value": True, "source": "address", "timestamp": "t"}]


# ---------- 9-11: resolucion de senales ----------

def test_unknown_signal_fails(program):
    with pytest.raises(rio.RuntimeIOError) as error:
        rio.resolve_signal(program, "I_No_Existe", for_write=False)
    assert error.value.code == rio.ERROR_SIGNAL_NOT_FOUND


def test_signal_outside_current_program_fails(program):
    # I_Free16_7 existe en el inventario del banco, pero no pertenece al programa del ensayo.
    assert "I_Free16_7" in program["inventory"]
    with pytest.raises(rio.RuntimeIOError) as error:
        rio.resolve_signal(program, "I_Free16_7", for_write=True)
    assert error.value.code == rio.ERROR_SIGNAL_NOT_IN_PROGRAM


def test_unsupported_type_fails(program):
    with pytest.raises(rio.RuntimeIOError) as error:
        rio.resolve_signal(program, "AI_IW0", for_write=False)
    assert error.value.code == rio.ERROR_TYPE_UNSUPPORTED
    assert "AI_IW0" not in [s["name"] for s in rio.bool_inputs(program)]


# ---------- 12-13: cleanup ----------

def test_cleanup_returns_inputs_to_false(program):
    bridge = _FakePlcsim(program)
    session = _session(program, bridge)
    session.write_input("I_Start", True)
    session.write_input("I_Stop", True)
    assert set(session.touched_inputs) == {"I_Start", "I_Stop"}
    result = session.restore_inputs()
    assert result["status"] == rio.SUCCESS and set(result["restored"]) == {"I_Start", "I_Stop"}
    assert session.touched_inputs == {}
    signals = program["signals"]
    assert not bridge.bits[("Input", 16, 0)] and not bridge.bits[("Input", 16, 1)]
    assert session.cleanup["success"] is True
    assert signals["I_Start"]["address"] == "%I16.0"


def test_cleanup_failure_is_reported_not_hidden(program):
    bridge = _FakePlcsim(program, cleanup_fails=True)
    session = _session(program, bridge)
    session.write_input("I_Start", True)
    result = session.restore_inputs()
    assert result["status"] == rio.ERROR_CLEANUP_FAILED and result["pending"] == ["I_Start"]
    report = session.build_report()
    assert report["runtime_io_test"] == rio.FAIL
    assert report["pending_inputs_not_restored"] == ["I_Start"]
    assert any(rio.ERROR_CLEANUP_FAILED in error for error in report["errors"])


# ---------- 14-16: bindings y direcciones ----------

def test_bindings_come_from_the_trial_snapshot(program, snapshot_path):
    assert program["source"] == "snapshot" and program["path"] == str(snapshot_path)
    assert program["trial_id"] == "D03_V1_TEXT_001"
    assert {s["name"] for s in rio.bool_inputs(program)} == {"I_Start", "I_Stop"}
    assert {s["name"] for s in rio.bool_outputs(program)} == {"Q_Motor"}
    assert program["signals"]["Q_Motor"]["roles"] == ["output"]
    binding = program["parameter_bindings"]["start_input"]  # campos originales intactos (+ campos aditivos)
    assert {key: binding[key] for key in ("functional_name", "address")} == {"functional_name": "I_Start", "address": "%IX16.0"}
    # Sin snapshot ni variables.json no hay programa: nunca se inventan senales.
    with pytest.raises(rio.RuntimeIOError) as error:
        rio.load_program_signals(None, None)
    assert error.value.code == rio.ERROR_NO_PROGRAM


def test_address_normalization_inputs():
    for text in ("%IX16.0", "%I16.0", "I16.0", "%ix16.0"):
        location = rio.runtime_address(text)
        assert (location["area"], location["offset"], location["bit"]) == ("Input", 16, 0)
        assert location["address"] == "%I16.0" and location["address_x"] == "%IX16.0"
    assert rio.runtime_address("%IW0")["bit"] is None
    with pytest.raises(rio.RuntimeIOError):
        rio.runtime_address("%IX16.8")


def test_address_normalization_outputs():
    for text in ("%QX8.0", "%Q8.0", "Q8.0"):
        location = rio.runtime_address(text)
        assert (location["area"], location["offset"], location["bit"]) == ("Output", 8, 0)
        assert location["address"] == "%Q8.0" and location["address_x"] == "%QX8.0"


# ---------- 17: reporte + smoke test ----------

def test_smoke_test_sequence_and_serializable_report(program, tmp_path):
    bridge = _FakePlcsim(program)
    report = rio.run_runtime_io_smoke_test(
        program, "PLCSIM_ADVANCED", dict(_RUN), Path("."), tmp_path, bridge=bridge, runtime_config=_CONFIG
    )
    assert report["runtime_io_test"] == rio.SUCCESS
    assert report["roles"] == {"start": "I_Start", "stop": "I_Stop", "output": "Q_Motor"}
    assert report["output_sequence"] == [True, True, False]  # Start -> ON, suelta Start -> sigue ON, Stop -> OFF
    assert report["functional_success"] is None
    assert report["cleanup"]["success"] is True
    assert {entry["name"] for entry in report["cleanup"]["inputs"]} == {"I_Start", "I_Stop"}
    assert [call[0] for call in bridge.calls] == ["io_sequence"]
    loaded = json.loads((tmp_path / rio.REPORT_FILENAME).read_text(encoding="utf-8"))
    for key in ("instance", "cpu_state", "program_source", "input_bindings", "output_bindings", "writes",
                "readbacks", "observations", "cleanup", "warnings", "errors", "duration_ms", "started_at"):
        assert key in loaded
    section = rio.trial_runtime_io_section(report)
    assert section["bool_input_write_supported"] is True and section["bool_read_supported"] is True


def test_io_timeout_triggers_separate_restore(program):
    bridge = _FakePlcsim(program, status_override="PLCSIM_RUNTIME_TIMEOUT")
    session = _session(program, bridge)
    result = session.write_input("I_Start", True)
    assert result["status"] == rio.ERROR_IO_TIMEOUT
    assert [call[0] for call in bridge.calls] == ["write_input", "restore_inputs"]


# ---------- 18-19: GUI ----------

@pytest.fixture
def gui_io(app, program, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, message, **k: warnings.append(message))
    monkeypatch.setattr(app, "_load_io_program", lambda: program)
    yield app, warnings
    if app._io_test_window is not None:
        app._io_test_window.destroy()
        app._io_test_window = None


def test_gui_io_test_disabled_when_target_is_not_simulation(gui_io, monkeypatch):
    app, warnings = gui_io
    monkeypatch.setattr(app, "_io_test_target_type", lambda: "PHYSICAL_PLC")
    app._open_runtime_io_window_if_allowed(dict(_RUN))
    assert app._io_test_window is None
    assert warnings and rio.ERROR_WRITE_NOT_ALLOWED in warnings[-1]


def test_gui_io_test_disabled_when_cpu_stop(gui_io, monkeypatch):
    app, warnings = gui_io
    monkeypatch.setattr(app, "_io_test_target_type", lambda: "PLCSIM_ADVANCED")
    app._open_runtime_io_window_if_allowed({**_RUN, "cpu_state": "STOP"})
    assert app._io_test_window is None
    assert warnings and rio.ERROR_CPU_NOT_RUN in warnings[-1]


def test_gui_io_test_disabled_without_program(app, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, message, **k: warnings.append(message))
    app._io_program_context = None
    monkeypatch.setattr(app, "_io_test_target_type", lambda: "PLCSIM_ADVANCED")
    app._open_runtime_io_window_if_allowed(dict(_RUN))
    assert app._io_test_window is None and rio.ERROR_NO_PROGRAM in warnings[-1]


def test_gui_io_window_lists_only_program_bool_signals(gui_io, monkeypatch, tmp_path):
    app, warnings = gui_io
    monkeypatch.setattr(app, "_io_test_target_type", lambda: "PLCSIM_ADVANCED")
    app._io_program_context = {"trial_dir": None, "package_dir": tmp_path}
    app._open_runtime_io_window_if_allowed(dict(_RUN))
    window = app._io_test_window
    assert window is not None and warnings == []
    assert sorted(window.input_menu.cget("values")) == ["I_Start", "I_Stop"]
    assert list(window.output_menu.cget("values")) == ["Q_Motor"]


# ---------- Bridge C#: logica pura y solo-escritura-de-entradas ----------

def test_bridge_only_write_is_input_area_writebit():
    source = (get_project_root() / "plcsim_runtime_bridge" / "Program.cs").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("//") and "///" not in line)
    # Escrituras sobre objetos de la Runtime API (instancia o areas de I/O); Console/File no cuentan.
    write_calls = [line.strip() for line in code.splitlines() if re.search(r"(instance|Area)\.Write", line)]
    # Entradas fisicas: InputArea.WriteBit. Variables internas (P01-P12): SOLO WriteBool/WriteFloat por nombre
    # resuelto, dentro de WriteVariable.
    internal = ("instance.WriteFloat(signal.ApiName,", "instance.WriteBool(signal.ApiName,")
    assert write_calls and all("instance.InputArea.WriteBit(" in line or line.startswith(internal) for line in write_calls), write_calls
    for forbidden in ("OutputArea.Write", "MarkerArea.Write", "WriteBytes(", "WriteByte(", "WriteSignals(", "SetIPSuite("):
        assert forbidden not in code
    body = code[code.index("private static void WriteVariable("):]
    body = body[:body.index("\n        }\n") + 10]
    assert sum(line.strip().startswith(internal) for line in body.splitlines()) == 2  # solo dentro de WriteVariable
    # WriteVariable solo se llama tras verificar la escritura (SetMany) o al restaurar lo ya escrito.
    callers = [line.strip() for line in code.splitlines() if "WriteVariable(instance," in line]
    assert callers == ["WriteVariable(instance, write.Key, write.Value);", "WriteVariable(instance, signal, target);"], callers


def test_bridge_self_test_signal_rules():
    if not plcsim_runtime.DEFAULT_RUNTIME_API_DLL.exists():
        pytest.skip("Runtime API de PLCSIM Advanced no instalada en este entorno.")
    raw = plcsim_runtime.run_runtime_bridge("self_test", get_project_root())
    if raw.get("status") == "PLCSIM_BRIDGE_BUILD_FAILED":
        pytest.skip(f"Bridge no compilable: {raw.get('errors')}")
    checks = {check["check"]: check for check in raw["checks"]}
    assert raw["status"] == "PLCSIM_RUNTIME_SELF_TEST_PASSED"
    assert checks["signal.write_output_denied"]["actual"] == "PLCSIM_IO_WRITE_NOT_ALLOWED"
    assert checks["signal.not_in_program"]["actual"] == "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM"
    assert checks["signal.address_mismatch"]["actual"] == "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM"
    assert checks["signal.type_runtime_int"]["actual"] == "PLCSIM_SIGNAL_TYPE_UNSUPPORTED"
    assert checks["signal.write_input_ok"]["actual"] == "OK"


# ---------- 20: mapas reales intactos ----------

def test_real_maps_unchanged_by_this_module():
    for path in _REAL_MAPS:
        assert _hash(path) == _HASHES_AT_IMPORT[str(path)], f"{path.name} fue modificado durante los tests"
