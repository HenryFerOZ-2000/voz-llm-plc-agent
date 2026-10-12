"""
Readback de variables internas INPUT: fallo de infraestructura vs. sobrescritura del estimulo por el DUT.

Problema: P06 (Oracle FROZEN) fija Auto_Mode = FALSE como estimulo del arnes (rol INPUT PROCESS_VARIABLE); el
programa generado (el LLM anadio set_auto_mode) ejecuta Auto_Mode := TRUE en cada ciclo. El bridge escribia y
releia de inmediato: si el ciclo ya habia corrido, PLCSIM_INPUT_READBACK_MISMATCH -> INFRASTRUCTURE_ERROR, aunque
la infraestructura SI escribio. Ahora:
  - la API falla al escribir                       -> INFRASTRUCTURE_ERROR (sin cambios);
  - escritura OK + el PLC cambia el valor despues   -> PROGRAM_OVERWRITES_HARNESS_INPUT -> Functional FAIL;
    evidencia: readback confirmado tras io_settle_ms (bridge) o muestra posterior de la traza (runner);
  - E/S fisicas: la politica de infraestructura no cambia; las variables OUTPUT nunca se escriben.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pytest

from trial_experiments import oracle_runner, oracle_schema
from trial_experiments import process_variables as PV
from utils import get_project_root

from test_process_variable_runtime import _PILOTS, _pilot_trial, _variables  # noqa: E402

_ROOT = get_project_root()
_ORACLES_DIR = _ROOT / "data" / "experiment_oracles"
_ORACLE_HASHES = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(_ORACLES_DIR.glob("*.json"))}
_CONFIG = {"instance_name": "TESIS_PLC_SIM", "io_settle_ms": 0, "io_timeout_seconds": 5,
           "api_dll_path": "x", "windows_adapter_match": "x", "timeout_seconds": 5}
_RUN = {"connected": True, "instance_name": "TESIS_PLC_SIM", "cpu_state": "RUN", "status": "CONNECTED"}
_STAMP = datetime(2026, 10, 12, 12, 0, 0).isoformat()


class _ScanPlcsim:
    """
    PLCSIM con ciclo de programa y el contrato del bridge para variables internas:
      readback="before_cycle": el readback inmediato ocurre antes del siguiente ciclo (ve lo escrito);
      readback="after_cycle":  el ciclo ya corrio; ante discrepancia el bridge observa de nuevo tras
                               io_settle_ms y clasifica PROGRAM_OVERWRITES_HARNESS_INPUT;
      fail_write=True:         la llamada WriteBool/WriteFloat lanza excepcion (fallo real de la API);
      physical_mismatch=True:  readback de una entrada FISICA distinto (politica de infraestructura).
    """

    def __init__(self, scan: Callable[[dict[str, Any]], None], statics: dict[str, Any], readback: str = "after_cycle",
                 fail_write: bool = False, physical_mismatch: bool = False) -> None:
        self.scan, self.state, self.readback = scan, dict(statics), readback
        self.fail_write, self.physical_mismatch = fail_write, physical_mismatch
        self.calls: list[dict[str, Any]] = []

    def __call__(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        if self.physical_mismatch:
            return {"status": "PLCSIM_INPUT_READBACK_MISMATCH", "errors": ["I_Start: se pidio True y se leyo False."],
                    "events": [], "samples": []}
        events, samples, overwrites, t = [], [], [], 0.0
        status, errors, failed = "PLCSIM_IO_PASSED", [], None
        for step in payload["steps"]:
            if step["op"] == "set":
                entries = []
                for write in step["writes"]:
                    signal = write["signal"]
                    assert signal.get("writable"), "una variable OUTPUT nunca se escribe"
                    if self.fail_write:
                        return {"status": "PLCSIM_INPUT_WRITE_FAILED", "errors": [f"{signal['name']}: escritura fallo (Error)."],
                                "events": events, "samples": samples}
                    member = signal["member"]
                    self.state[member] = float(write["value"]) if signal["data_type"] == "REAL" else write["value"]
                    if self.readback == "after_cycle":
                        self.scan(self.state)
                    entry = {"name": signal["name"], "runtime_name": f'"{signal["db"]}".{member}', "kind": "PROCESS_VARIABLE",
                             "data_type": signal["data_type"], "requested_value": write["value"], "write_call_success": True,
                             "write_timestamp": _STAMP, "initial_readback": self.state[member], "classification": "CONFIRMED"}
                    if self.state[member] != write["value"]:
                        self.scan(self.state)
                        entry.update({"observed_after_cycle": self.state[member], "observed_after_cycle_timestamp": _STAMP,
                                      "observed_wait_ms": 0, "classification": "PROGRAM_OVERWRITES_HARNESS_INPUT",
                                      "observed_equals_original": False})
                        overwrites.append({**entry, "step_id": step["id"]})
                    entries.append(entry)
                events.append({"type": "set", "id": step["id"], "phase": step["phase"], "t_ms": t, "t_done_ms": t,
                               "timestamp": _STAMP, "writes": entries})
                continue
            last = {}
            for _ in range(max(1, int(step["duration_ms"]) // int(step["period_ms"])) + 1):
                self.scan(self.state)
                last = {s["name"]: self.state.get(s.get("member", s["name"])) for s in step["signals"]}
                samples.append({"id": step["id"], "phase": step["phase"], "t_ms": t, "values": last})
                t += step["period_ms"]
            if any(not oracle_runner.value_matches(v, last.get(k)) for k, v in (step.get("require") or {}).items()):
                status, failed = "PLCSIM_SEQUENCE_REQUIREMENT_FAILED", step["id"]
                errors.append(f"Requisito no cumplido en {step['id']}")
                break
        raw = {"status": status, "errors": errors, "failed_step": failed, "events": events, "samples": samples,
               "cleanup": {"performed": True, "success": True, "inputs": [], "process_variables": []}, "cpu_state": "RUN"}
        if overwrites:
            raw["harness_input_overwrites"] = overwrites
        return raw


def _run(case_id: str, tmp_path: Path, sim: _ScanPlcsim, semantic_output: dict[str, Any], trial: Path):
    return oracle_runner.run_oracle(oracle_schema.load_oracle(_ROOT, case_id), trial / "io_map_snapshot.json", dict(_RUN),
                                    "PLCSIM_ADVANCED", semantic_output, _ROOT, bridge=sim, runtime_config=_CONFIG)


def _p06_set_auto_mode_scan(state: dict[str, Any]) -> None:
    # Mismo SCL que el generador para set_auto_mode + enable_pid (emergencia = FALSE).
    state.update(Auto_Mode=True, Manual_Mode=False)
    state["PID_Enable"] = state["Auto_Mode"] and not state["Sensor_Fault"] and not state["Safe_Stop"]


# A. La API falla al escribir -> INFRASTRUCTURE_ERROR (sin cambios)
def test_a_api_write_failure_is_infrastructure(tmp_path):
    trial, semantic, statics, _ = _pilot_trial(tmp_path, "P04")
    result = _run("P04", tmp_path, _ScanPlcsim(_PILOTS["P04"]["logic"], statics, fail_write=True), semantic, trial)
    assert result["verdict"] == "INFRASTRUCTURE_ERROR" and result["verdict_reason"] == "PLCSIM_INPUT_WRITE_FAILED"


# B. Escritura OK y el valor permanece -> continua normalmente
@pytest.mark.parametrize("readback", ["before_cycle", "after_cycle"])
def test_b_write_ok_and_value_holds_continues_normally(tmp_path, readback):
    trial, semantic, statics, _ = _pilot_trial(tmp_path, "P06")
    result = _run("P06", tmp_path, _ScanPlcsim(_PILOTS["P06"]["logic"], statics, readback=readback), semantic, trial)
    assert result["verdict"] == "PASS" and result["harness_input_overwrites"] == []


# C/E. BOOL INPUT reescrita por el PLC -> PROGRAM_OVERWRITES_HARNESS_INPUT -> Functional FAIL (nunca INFRA/REVIEW)
@pytest.mark.parametrize("readback,evidence", [("after_cycle", "BRIDGE_READBACK_AFTER_CYCLE"), ("before_cycle", "TRACE_SAMPLE_AFTER_WRITE")])
def test_c_e_bool_input_overwritten_by_the_program_is_functional_fail(tmp_path, readback, evidence):
    trial, semantic, statics, _ = _pilot_trial(tmp_path, "P06")
    result = _run("P06", tmp_path, _ScanPlcsim(_p06_set_auto_mode_scan, statics, readback=readback), semantic, trial)
    assert result["verdict"] == "FAIL" and result["verdict_reason"] == oracle_runner.PROGRAM_OVERWRITES_HARNESS_INPUT
    assert result["functional"]["success"] is False and result["functional"]["evaluated"] is True
    [overwrite] = [o for o in result["harness_input_overwrites"] if o["step_id"] == "pre_manual"]
    assert (overwrite["role"], overwrite["variable"], overwrite["data_type"]) == ("AUTO_MODE", "Auto_Mode", "BOOL")
    assert (overwrite["written_value"], overwrite["observed_value"], overwrite["evidence"]) == (False, True, evidence)
    assert result["preconditions"]["success"] is False
    assert result["preconditions"]["failed_because"] == oracle_runner.PROGRAM_OVERWRITES_HARNESS_INPUT
    assert result["safety"]["evaluated"] is True  # Safety se sigue evaluando con las muestras tomadas


# D. REAL INPUT reescrita -> mismo criterio
def test_d_real_input_overwritten_is_functional_fail(tmp_path):
    trial, semantic, statics, _ = _pilot_trial(tmp_path, "P04")

    def scan(state):  # el programa fija el nivel (no deberia): el estimulo 95 % nunca se mantiene
        state["Level_PV"] = 50.0
        state["High_Level_Alarm"] = state["Level_PV"] > 90.0

    result = _run("P04", tmp_path, _ScanPlcsim(scan, statics), semantic, trial)
    assert result["verdict"] == "FAIL" and result["verdict_reason"] == oracle_runner.PROGRAM_OVERWRITES_HARNESS_INPUT
    overwrite = next(o for o in result["harness_input_overwrites"] if o["step_id"] == "step_1")
    assert (overwrite["data_type"], overwrite["written_value"], overwrite["observed_value"]) == ("REAL", 95.0, 50.0)


def test_d_real_float32_readback_within_tolerance_is_not_an_overwrite():
    roles = {"LEVEL_PV": {"role": "LEVEL_PV", "functional_name": "DB_PLC_PRG.Level_PV", "binding": "PROCESS_VARIABLE",
                          "writable": True, "data_type": "REAL", "process_variable": "Level_PV"}}
    raw = {"events": [{"type": "set", "id": "s1", "t_done_ms": 0.0, "timestamp": _STAMP,
                       "writes": [{"name": "DB_PLC_PRG.Level_PV", "requested_value": 89.0}]}],
           "samples": [{"id": "s1", "t_ms": 50.0, "values": {"DB_PLC_PRG.Level_PV": 89.0000004}}]}
    assert oracle_runner.detect_harness_input_overwrites(roles, raw) == []


# F. Una variable OUTPUT nunca se escribe (solo se lee)
def test_f_output_process_variable_is_never_written(tmp_path):
    trial, semantic, statics, _ = _pilot_trial(tmp_path, "P06")
    sim = _ScanPlcsim(_PILOTS["P06"]["logic"], statics)  # el simulador falla si se escribe algo no escribible
    _run("P06", tmp_path, sim, semantic, trial)
    written = {w["signal"]["name"] for step in sim.calls[0]["steps"] if step["op"] == "set" for w in step["writes"]}
    assert written == {"DB_PLC_PRG.Auto_Mode"}  # PID_ENABLE (OUTPUT) nunca


# G. E/S fisicas: un readback fisico distinto sigue siendo infraestructura; nunca se reclasifica
def test_g_physical_input_readback_mismatch_keeps_infrastructure_policy(tmp_path):
    trial, semantic, statics, _ = _pilot_trial(tmp_path, "P04")
    result = _run("P04", tmp_path, _ScanPlcsim(_PILOTS["P04"]["logic"], statics, physical_mismatch=True), semantic, trial)
    assert result["verdict"] == "INFRASTRUCTURE_ERROR" and result["verdict_reason"] == "PLCSIM_INPUT_READBACK_MISMATCH"
    roles = {"START": {"role": "START", "functional_name": "I_Start", "address": "%IX16.0"}}  # rol IO fisico
    raw = {"harness_input_overwrites": [{"name": "I_Start", "requested_value": True, "observed_after_cycle": False, "step_id": "s"}],
           "events": [{"type": "set", "id": "s", "t_done_ms": 0.0, "writes": [{"name": "I_Start", "requested_value": True}]}],
           "samples": [{"id": "s", "t_ms": 1.0, "values": {"I_Start": False}}]}
    assert oracle_runner.detect_harness_input_overwrites(roles, raw) == []


def test_g_bridge_keeps_physical_readback_as_infrastructure_and_separates_internal_evidence():
    source = (_ROOT / "plcsim_runtime_bridge" / "Program.cs").read_text(encoding="utf-8")
    assert 'report["status"] = "PLCSIM_INPUT_READBACK_MISMATCH";' in source  # E/S fisicas: politica intacta
    assert 'report["status"] = "PLCSIM_INPUT_WRITE_FAILED";' in source       # excepcion de la API: infraestructura
    for marker in ('{ "write_call_success", true }', '"initial_readback"', 'entry["observed_after_cycle"]',
                   '"PROGRAM_OVERWRITES_HARNESS_INPUT"', '"AMBIGUOUS_TRANSIENT"', 'entry["observed_equals_original"]',
                   "Thread.Sleep(settleMs);"):
        assert marker in source, marker


# H. P06 con set_auto_mode (programa REAL del generador): Functional FAIL, no INFRA
def test_h_p06_with_set_auto_mode_is_a_real_functional_failure(tmp_path):
    semantic, rows, code = _variables("P06", "Habilita el PID unicamente cuando el sistema este en modo Automatico.",
                                      [{"type": "set_auto_mode"}, {"type": "enable_pid"}])
    assert "Auto_Mode := TRUE;" in code  # lo que produjo el LLM se conserva: no se corrige aqui
    trial = tmp_path / "P06_set_auto"
    trial.mkdir()
    (trial / "variables.json").write_text(json.dumps(rows), encoding="utf-8")
    (trial / "io_map_snapshot.json").write_text(json.dumps({"channels": [], "bindings": [], "parameter_bindings": {}}), encoding="utf-8")
    PV.freeze_process_variable_bindings(trial, trial / "variables.json")
    statics = {row["name"]: (0.0 if row["type"] == "REAL" else False) for row in rows if row.get("tia_scope", "").startswith("FB_STATIC")}
    result = _run("P06", tmp_path, _ScanPlcsim(_p06_set_auto_mode_scan, statics), semantic, trial)
    assert result["verdict"] == "FAIL" and result["verdict_reason"] == oracle_runner.PROGRAM_OVERWRITES_HARNESS_INPUT
    assert result["verdict"] != "INFRASTRUCTURE_ERROR" and oracle_runner.PRECONDITION_FAILED not in result["verdict_reason"]


# I. La evidencia (valores, tiempos, nombre Runtime, tipo) queda persistida en el evaluation_report
def test_i_overwrite_evidence_is_persisted_in_the_evaluation_report(tmp_path):
    trial, semantic, statics, _ = _pilot_trial(tmp_path, "P06")
    result = _run("P06", tmp_path, _ScanPlcsim(_p06_set_auto_mode_scan, statics), semantic, trial)
    report = oracle_runner.build_evaluation_report({"trial_id": "P06_X", "case_id": "P06"}, result, "FAIL")
    [overwrite] = [o for o in report["harness_input_overwrites"] if o["step_id"] == "pre_manual"]
    for key in ("variable", "written_value", "observed_value", "write_timestamp", "read_timestamp", "runtime_name", "data_type"):
        assert overwrite.get(key) is not None, key
    assert overwrite["runtime_name"] == '"DB_PLC_PRG".Auto_Mode'
    assert any(c.get("code") == oracle_runner.PROGRAM_OVERWRITES_HARNESS_INPUT for c in report["functional"]["failed_checks"])


# J. Ningun Oracle / benchmark cambia
def test_j_no_oracle_or_benchmark_changes():
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(_ORACLES_DIR.glob("*.json"))} == _ORACLE_HASHES
    oracle_schema.verify_integrity(oracle_schema.load_oracle(_ROOT, "P06"))
