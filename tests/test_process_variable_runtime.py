"""
Fase 1 P01-P12: Runtime de variables internas (estaticas de DB_PLC_PRG) + roles PROCESS_VARIABLE del Oracle.

P01-P12 no usan AI/AO: el Oracle (FROZEN, sin cambios) inyecta Level_PV (REAL, % de ingenieria) y lee
Level_SP / PID_Enable / alarmas / Sensor_Fault como variables internas. Aqui se prueba:
  1. el bridge C# real (accion self_test, sin PLCSIM): verificacion pura, resolucion del nombre Runtime
     (formato descubierto con/sin comillas, nunca asumido), readback REAL con tolerancia, requisitos;
  2. process_variable_bindings: derivados SOLO de variables.json (lo que el generador declaro) + contrato;
  3. resolucion de roles PROCESS_VARIABLE (encontrado / ausente / ambiguo / tipo), sin adivinar;
  4. ejecucion por capacidades (REQUIRES_RUNTIME_EXTENSION ejecutable si el Runtime cubre los requisitos);
  5. pilotos simulados P02/P04/P05/P06/P09: programa REAL del generador -> bindings -> Oracle FROZEN ->
     PLCSIM simulado con el contrato del bridge (proposito, solo roles INPUT escribibles, readback,
     restauracion al valor del cleanup del Oracle).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pytest

import plcsim_runtime
import plcsim_runtime_io as rio
from platforms.siemens_scl_adapter import SiemensSCLAdapter
from trial_experiments import deferred_evaluator as DE
from trial_experiments import oracle_runner, oracle_schema
from trial_experiments import process_variables as PV
from utils import get_project_root

from test_pid_supervisor import _build  # noqa: E402

_ROOT = get_project_root()
_ORACLES_DIR = _ROOT / "data" / "experiment_oracles"
_CONFIG = {"instance_name": "TESIS_PLC_SIM", "io_settle_ms": 0, "io_timeout_seconds": 5,
           "api_dll_path": "x", "windows_adapter_match": "x", "timeout_seconds": 5}
_RUN = {"connected": True, "instance_name": "TESIS_PLC_SIM", "cpu_state": "RUN", "status": "CONNECTED"}
_ORACLE_HASHES = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(_ORACLES_DIR.glob("P*.json"))}


def _oracle(case_id: str) -> dict[str, Any]:
    return oracle_schema.load_oracle(_ROOT, case_id)


# =============================================================================================
# 1. Bridge C# real (self_test, sin PLCSIM)
# =============================================================================================

@pytest.fixture(scope="module")
def bridge_checks() -> dict[str, dict[str, Any]]:
    if not plcsim_runtime.DEFAULT_RUNTIME_API_DLL.exists():
        pytest.skip("Runtime API de PLCSIM Advanced no instalada en este entorno.")
    raw = plcsim_runtime.run_runtime_bridge("self_test", _ROOT)
    if raw.get("status") == "PLCSIM_BRIDGE_BUILD_FAILED":
        pytest.skip(f"Bridge no compilable: {raw.get('errors')}")
    assert raw["status"] == "PLCSIM_RUNTIME_SELF_TEST_PASSED", [c for c in raw["checks"] if not c["passed"]]
    return {check["check"]: check for check in raw["checks"]}


def test_bridge_db_discovery_rules_for_real_and_bool(bridge_checks):
    assert bridge_checks["pv.read_real_ok"]["actual"] == "OK"
    assert bridge_checks["pv.read_bool_ok"]["actual"] == "OK"
    assert bridge_checks["pv.not_in_program"]["actual"] == "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM"
    assert bridge_checks["pv.not_a_db_tag"]["actual"] == "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM"
    assert bridge_checks["pv.type_mismatch"]["actual"] == "PLCSIM_SIGNAL_TYPE_UNSUPPORTED"
    assert bridge_checks["pv.unsupported_type"]["actual"] == "PLCSIM_SIGNAL_TYPE_UNSUPPORTED"


def test_bridge_runtime_name_is_resolved_never_assumed(bridge_checks):
    assert bridge_checks["pv.resolve_quoted_runtime_name"]["actual"] == '"DB_PLC_PRG".Level_PV'
    assert bridge_checks["pv.resolve_plain_runtime_name"]["actual"] == "DB_PLC_PRG.Level_PV"
    assert bridge_checks["pv.resolve_missing_member"]["actual"] == "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM"
    assert bridge_checks["pv.resolve_never_other_db"]["actual"] == "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM"
    assert bridge_checks["pv.resolve_ambiguous"]["actual"] == "PLCSIM_SIGNAL_AMBIGUOUS"


def test_bridge_internal_write_policy(bridge_checks):
    assert bridge_checks["pv.write_real_ok"]["actual"] == "OK"
    assert bridge_checks["pv.write_not_writable"]["actual"] == "PLCSIM_IO_WRITE_NOT_ALLOWED"  # rol de salida
    assert bridge_checks["pv.write_without_oracle_purpose"]["actual"] == "PLCSIM_IO_WRITE_NOT_ALLOWED"


def test_bridge_write_readback_tolerance_and_requirements(bridge_checks):
    assert bridge_checks["pv.readback_real_within_tolerance"]["actual"] == "TRUE"  # float32 60.0004
    assert bridge_checks["pv.readback_real_outside_tolerance"]["actual"] == "FALSE"
    assert bridge_checks["pv.readback_bool"]["actual"] == "TRUE"
    assert bridge_checks["require.approx"]["actual"] == "TRUE"
    assert bridge_checks["require.approx_out"]["actual"] == "FALSE"
    assert bridge_checks["require.range"]["actual"] == "TRUE"


def test_bridge_uses_only_verified_runtime_api_by_name():
    source = (_ROOT / "plcsim_runtime_bridge" / "Program.cs").read_text(encoding="utf-8")
    for call in ("instance.ReadFloat(signal.ApiName)", "instance.ReadBool(signal.ApiName)",
                 "instance.WriteFloat(signal.ApiName,", "instance.WriteBool(signal.ApiName,",
                 "ETagListDetails.IODB", "instance.TagInfos"):
        assert call in source, call
    assert '"discover_tags"' in source


# =============================================================================================
# 2. process_variable_bindings
# =============================================================================================

def _variables(case_id: str, command: str, requirements: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    semantic_output, project_ir = _build(case_id, command, requirements)
    return semantic_output, SiemensSCLAdapter().render_variables_table(project_ir), project_ir.pou.implementation_code


def test_bindings_come_from_generated_variables_and_contract():
    _, rows, _ = _variables("P04", "Activa una alarma de nivel alto cuando el nivel supere el 90 %.",
                            [{"type": "high_level_alarm", "limit": 90.0}])
    payload = PV.build_process_variable_bindings(rows)
    bindings = payload["bindings"]
    assert set(bindings) == {"Level_PV", "High_Level_Alarm"}  # E/S fisicas (I_/Q_) nunca entran
    assert bindings["Level_PV"] == {
        "name": "Level_PV", "db": "DB_PLC_PRG", "member": "Level_PV", "runtime_name": None,
        "runtime_name_resolution": PV.RUNTIME_NAME_DISCOVERED_AT_EXECUTION, "data_type": "REAL",
        "binding": "PROCESS_VARIABLE", "tia_scope": "FB_STATIC_PERSISTENT", "source": PV.SOURCE_INTENT_CONTRACT}
    assert bindings["High_Level_Alarm"]["data_type"] == "BOOL"


def test_bindings_never_guess_wrong_scope_or_type():
    rows = [
        {"name": "Level_PV", "type": "BOOL", "class": "internal", "tia_scope": "FB_STATIC_PERSISTENT"},  # tipo != contrato
        {"name": "Level_SP", "type": "REAL", "class": "output", "tia_scope": "PLC_TAG"},  # no es estatica
        {"name": "M_RunLatch", "type": "BOOL", "class": "internal", "tia_scope": "FB_STATIC"},  # no es del contrato
        {"name": "PID_Enable", "type": "BOOL", "class": "internal", "tia_scope": "FB_STATIC_PERSISTENT"},
    ]
    payload = PV.build_process_variable_bindings(rows)
    assert set(payload["bindings"]) == {"PID_Enable"}
    assert {item["name"] for item in payload["excluded"]} == {"Level_PV", "Level_SP"}


def test_bindings_are_frozen_with_the_trial_and_only_for_pid_programs(tmp_path):
    _, rows, _ = _variables("P02", "Cambia el setpoint del nivel al 60 %.", [{"type": "set_level_setpoint", "value": 60.0}])
    (tmp_path / "variables.json").write_text(json.dumps(rows), encoding="utf-8")
    frozen = PV.freeze_process_variable_bindings(tmp_path, tmp_path / "variables.json")
    assert frozen and frozen.name == PV.PROCESS_VARIABLE_BINDINGS_FILENAME
    assert DE._present_process_variable_artifacts(tmp_path) == (PV.PROCESS_VARIABLE_BINDINGS_FILENAME,)
    assert PV.load_process_variable_bindings(tmp_path)["source"] == PV.SOURCE_INTENT_CONTRACT
    discrete = tmp_path / "discrete"
    discrete.mkdir()
    (discrete / "variables.json").write_text(json.dumps([{"name": "I_Start", "type": "BOOL", "tia_scope": "PLC_TAG"}]), encoding="utf-8")
    assert PV.freeze_process_variable_bindings(discrete, discrete / "variables.json") is None  # D01-D20: sin archivo
    assert DE._present_process_variable_artifacts(discrete) == ()


def test_legacy_trial_derives_bindings_from_frozen_variables_with_traced_source(tmp_path):
    _, rows, _ = _variables("P09", "Detecta un fallo del sensor.", [{"type": "sensor_range_fault"}])
    (tmp_path / "variables.json").write_text(json.dumps(rows), encoding="utf-8")
    payload = PV.load_process_variable_bindings(tmp_path)
    assert payload["source"] == PV.SOURCE_DERIVED_FROM_FROZEN_VARIABLES and "Sensor_Fault" in payload["bindings"]


# =============================================================================================
# 3. Roles PROCESS_VARIABLE
# =============================================================================================

def _pv(name: str, data_type: str) -> dict[str, Any]:
    return {"name": name, "db": "DB_PLC_PRG", "member": name, "data_type": data_type, "binding": "PROCESS_VARIABLE",
            "source": PV.SOURCE_INTENT_CONTRACT}


def test_process_variable_roles_resolve_only_against_frozen_bindings():
    oracle = _oracle("P04")
    resolution = oracle_runner.resolve_roles(oracle, {"channels": [], "parameter_bindings": {}},
                                             {"bindings": {"Level_PV": _pv("Level_PV", "REAL"),
                                                           "High_Level_Alarm": _pv("High_Level_Alarm", "BOOL")}})
    assert resolution["status"] == "RESOLVED"
    level = resolution["roles"]["LEVEL_PV"]
    assert (level["functional_name"], level["data_type"], level["writable"]) == ("DB_PLC_PRG.Level_PV", "REAL", True)
    assert resolution["roles"]["HIGH_LEVEL_ALARM"]["writable"] is False  # OUTPUT: solo lectura


def test_missing_process_variable_is_review_never_guessed():
    resolution = oracle_runner.resolve_roles(_oracle("P04"), {"channels": []}, {"bindings": {"Level_PV": _pv("Level_PV", "REAL")}})
    assert resolution["status"] == "REVIEW"
    assert [issue["code"] for issue in resolution["issues"]] == [oracle_runner.ROLE_NOT_FOUND]
    assert resolution["issues"][0]["role"] == "HIGH_LEVEL_ALARM"


def test_ambiguous_and_wrong_type_process_variables_are_review():
    oracle = _oracle("P03")  # LEVEL_SP_COMMAND acepta Level_SP_Command o Level_SP_Request
    both = {"Level_SP_Command": _pv("Level_SP_Command", "REAL"), "Level_SP_Request": _pv("Level_SP_Request", "REAL"),
            "Level_SP": _pv("Level_SP", "REAL")}
    issues = oracle_runner.resolve_roles(oracle, {"channels": []}, {"bindings": both})["issues"]
    assert [(i["role"], i["code"]) for i in issues] == [("LEVEL_SP_COMMAND", oracle_runner.ROLE_AMBIGUOUS)]
    wrong = oracle_runner.resolve_roles(_oracle("P02"), {"channels": []}, {"bindings": {"Level_SP": _pv("Level_SP", "BOOL")}})
    assert wrong["issues"][0]["code"] == oracle_runner.ROLE_KIND_MISMATCH


# =============================================================================================
# 4. Ejecucion por capacidades
# =============================================================================================

@pytest.mark.parametrize("case_id", [f"P{i:02d}" for i in range(1, 13)])
def test_requires_runtime_extension_is_executable_when_capabilities_exist(case_id):
    oracle = _oracle(case_id)
    assert oracle["runtime_support"] == "REQUIRES_RUNTIME_EXTENSION"  # el Oracle congelado no cambia
    check = oracle_runner.runtime_capability_check(oracle)
    assert check["executable"] is True and check["missing_capabilities"] == []
    assert set(oracle["runtime_requirements"]) <= set(check["required_capabilities"]) <= set(rio.RUNTIME_CAPABILITIES)
    assert check["declared_runtime_support"] == "REQUIRES_RUNTIME_EXTENSION"


def test_missing_capability_keeps_review():
    oracle = dict(_oracle("P04"), runtime_requirements=["BOOL", "REAL", "INT"])
    check = oracle_runner.runtime_capability_check(oracle)
    assert check["executable"] is False and check["missing_capabilities"] == ["INT"]
    bool_only = oracle_runner.runtime_capability_check(_oracle("P04"), ("BOOL",))
    assert bool_only["missing_capabilities"] == ["REAL", "INTERNAL_TAG_READ", "INTERNAL_TAG_WRITE"]


def test_discrete_oracles_are_unaffected_by_capability_execution():
    check = oracle_runner.runtime_capability_check(_oracle("D03"))
    assert check["executable"] is True and check["required_capabilities"] == ["BOOL"]


# =============================================================================================
# 5. PLCSIM simulado con el contrato del bridge + pilotos P02/P04/P05/P06/P09
# =============================================================================================

class _PlcsimPV:
    """
    io_sequence con el contrato del bridge real: escritura interna solo con purpose EXPERIMENT_ORACLE,
    target PLCSIM y senal writable; readback (REAL con tolerancia); muestras tipadas por nombre logico;
    restauracion final al restore_value (cleanup del Oracle) o al valor original; nombre Runtime resuelto
    en formato con comillas ("DB_PLC_PRG".X) para ejercitar la resolucion.
    """

    def __init__(self, logic: Callable[[dict[str, Any]], None], statics: dict[str, Any]) -> None:
        self.logic = logic
        self.state = dict(statics)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert action == "io_sequence"
        self.calls.append(payload)
        if payload.get("target_type") != "PLCSIM_ADVANCED":
            return {"status": "PLCSIM_IO_WRITE_NOT_ALLOWED", "errors": ["no PLCSIM"]}
        events: list[dict[str, Any]] = []
        samples: list[dict[str, Any]] = []
        written: dict[str, tuple[dict[str, Any], Any]] = {}
        resolved: dict[str, str] = {}
        t = 0.0
        status, errors, failed = "PLCSIM_IO_PASSED", [], None
        stamp = datetime(2026, 10, 12, 10, 0, 0).isoformat()

        def member(signal: dict[str, Any]) -> str:
            if signal.get("kind") == "PROCESS_VARIABLE":
                resolved[signal["name"]] = f'"{signal["db"]}".{signal["member"]}'
                return signal["member"]
            return signal["name"]

        for step in payload["steps"]:
            if step["op"] == "set":
                entries = []
                for write in step["writes"]:
                    signal = write["signal"]
                    if signal.get("kind") == "PROCESS_VARIABLE" and not (
                            signal.get("writable") and payload.get("purpose") == oracle_runner.PROCESS_VARIABLE_WRITE_PURPOSE):
                        return {"status": "PLCSIM_IO_WRITE_NOT_ALLOWED", "errors": [f"{signal['name']} no escribible"]}
                    key = member(signal)
                    if signal.get("kind") == "PROCESS_VARIABLE" and signal["name"] not in written:
                        written[signal["name"]] = (signal, self.state.get(key))
                    self.state[key] = float(write["value"]) if signal.get("data_type") == "REAL" else write["value"]
                    self.logic(self.state)
                    entries.append({"name": signal["name"], "requested_value": write["value"], "actual_readback": self.state[key],
                                    "match": True})
                events.append({"type": "set", "id": step["id"], "phase": step["phase"], "t_ms": t, "t_done_ms": t,
                               "timestamp": stamp, "writes": entries})
                continue
            count = max(1, int(step["duration_ms"]) // int(step["period_ms"])) + 1
            last: dict[str, Any] = {}
            for _ in range(count):
                self.logic(self.state)
                last = {signal["name"]: self.state.get(member(signal)) for signal in step["signals"]}
                samples.append({"id": step["id"], "phase": step["phase"], "t_ms": t, "values": last})
                t += step["period_ms"]
            for name, expected in (step.get("require") or {}).items():
                if not oracle_runner.value_matches(expected, last.get(name)):
                    status, failed = "PLCSIM_SEQUENCE_REQUIREMENT_FAILED", step["id"]
                    errors.append(f"Requisito no cumplido en {step['id']}: {name}")
            if failed:
                break
        restored = []
        for name, (signal, original) in written.items():
            target = signal["restore_value"] if "restore_value" in signal else original
            self.state[signal["member"]] = target
            restored.append({"name": name, "runtime_name": resolved[name], "original_value": original, "restore_value": target,
                             "restore_source": "ORACLE_CLEANUP" if "restore_value" in signal else "ORIGINAL_VALUE",
                             "readback": self.state[signal["member"]], "restored": True})
        return {"status": status, "errors": errors, "failed_step": failed, "events": events, "samples": samples,
                "cleanup": {"performed": True, "success": True, "inputs": [], "process_variables": restored},
                "resolved_process_variables": resolved, "cpu_state": "RUN", "sequence_duration_ms": t}


# Logica de cada piloto = la del SCL generado (se comprueba la linea clave contra el generador real).
_PILOTS: dict[str, dict[str, Any]] = {
    "P02": {"command": "Cambia el setpoint del nivel al 60 %.", "requirements": [{"type": "set_level_setpoint", "value": 60.0}],
            "line": "Level_SP := 60.0;", "logic": lambda s: s.update(Level_SP=60.0)},
    "P04": {"command": "Activa una alarma de nivel alto cuando el nivel supere el 90 %.",
            "requirements": [{"type": "high_level_alarm", "limit": 90.0}], "line": "IF Level_PV > 90.0 THEN",
            "logic": lambda s: s.update(High_Level_Alarm=s["Level_PV"] > 90.0)},
    "P05": {"command": "Activa una alarma de nivel bajo cuando el nivel sea inferior al 10 %.",
            "requirements": [{"type": "low_level_alarm", "limit": 10.0}], "line": "IF Level_PV < 10.0 THEN",
            "logic": lambda s: s.update(Low_Level_Alarm=s["Level_PV"] < 10.0)},
    "P06": {"command": "Habilita el PID unicamente cuando el sistema este en modo Automatico.",
            "requirements": [{"type": "enable_pid"}], "line": "AND Auto_Mode AND NOT Sensor_Fault AND NOT Safe_Stop;",
            "logic": lambda s: s.update(PID_Enable=s["Auto_Mode"] and not s["Sensor_Fault"] and not s["Safe_Stop"])},
    "P09": {"command": "Detecta un fallo del sensor si el nivel medido esta fuera del rango de 0 % a 100 %.",
            "requirements": [{"type": "sensor_range_fault"}], "line": "IF Level_PV < 0.0 OR Level_PV > 100.0 THEN",
            "logic": lambda s: s.update(Sensor_Fault=s["Level_PV"] < 0.0 or s["Level_PV"] > 100.0)},
}


def _pilot_trial(tmp_path: Path, case_id: str) -> tuple[Path, dict[str, Any], dict[str, Any], str]:
    pilot = _PILOTS[case_id]
    semantic_output, rows, code = _variables(case_id, pilot["command"], pilot["requirements"])
    trial = tmp_path / case_id
    trial.mkdir()
    (trial / "variables.json").write_text(json.dumps(rows), encoding="utf-8")
    (trial / "io_map_snapshot.json").write_text(json.dumps({"channels": [], "bindings": [], "parameter_bindings": {}}), encoding="utf-8")
    PV.freeze_process_variable_bindings(trial, trial / "variables.json")
    statics = {row["name"]: (0.0 if row["type"] == "REAL" else False) for row in rows if row.get("tia_scope", "").startswith("FB_STATIC")}
    return trial, semantic_output, statics, code


def _run(trial: Path, case_id: str, semantic_output: dict[str, Any], sim: _PlcsimPV, target: str = "PLCSIM_ADVANCED"):
    return oracle_runner.run_oracle(_oracle(case_id), trial / "io_map_snapshot.json", dict(_RUN), target, semantic_output,
                                    _ROOT, bridge=sim, runtime_config=_CONFIG)


@pytest.mark.parametrize("case_id", ["P02", "P04", "P05", "P06", "P09"])
def test_pilot_is_functionally_evaluable_and_passes_with_generated_logic(tmp_path, case_id):
    trial, semantic_output, statics, code = _pilot_trial(tmp_path, case_id)
    assert _PILOTS[case_id]["line"] in code  # la logica simulada es la del SCL generado
    sim = _PlcsimPV(_PILOTS[case_id]["logic"], statics)
    result = _run(trial, case_id, semantic_output, sim)
    assert result["verdict"] == "PASS", (result["verdict_reason"], result["errors"], result["functional"].get("failed_checks"))
    assert result["functional"]["success"] is True and result["functional"]["total_checks"] >= 1
    assert result["safety"]["success"] is True
    assert result["runtime_capability_check"]["executable"] is True
    assert result["process_variable_bindings"]["source"] == PV.SOURCE_INTENT_CONTRACT
    payload = sim.calls[0]
    writes = [w["signal"] for step in payload["steps"] if step["op"] == "set" for w in step["writes"]]
    assert all(s["kind"] == "PROCESS_VARIABLE" and s["writable"] for s in writes)  # solo roles INPUT
    if writes:
        assert payload["purpose"] == oracle_runner.PROCESS_VARIABLE_WRITE_PURPOSE and payload["process_variables"] is True
        assert result["sequence"]["resolved_process_variables"]  # evidencia del nombre Runtime usado


def test_real_approx_tolerance_and_bool_expectations(tmp_path):
    trial, semantic_output, statics, _ = _pilot_trial(tmp_path, "P02")
    near = _run(trial, "P02", semantic_output, _PlcsimPV(lambda s: s.update(Level_SP=60.004), statics))
    assert near["verdict"] == "PASS"  # +-0.01 del Oracle
    off = _run(trial, "P02", semantic_output, _PlcsimPV(lambda s: s.update(Level_SP=60.5), statics))
    assert off["verdict"] == "FAIL" and off["functional"]["failed_checks"][0]["role"] == "LEVEL_SP"


def test_real_range_values_drive_bool_alarm_and_negative_control_fails(tmp_path):
    trial, semantic_output, statics, _ = _pilot_trial(tmp_path, "P04")
    wrong_limit = _run(trial, "P04", semantic_output, _PlcsimPV(lambda s: s.update(High_Level_Alarm=s["Level_PV"] > 99.0), statics))
    assert wrong_limit["verdict"] == "FAIL" and wrong_limit["functional"]["success"] is False
    assert oracle_runner.value_matches({"min": 0.0, "max": 100.0}, 50.0) and not oracle_runner.value_matches({"min": 0.0, "max": 100.0}, 150.0)


def test_p06_invariant_detects_pid_enabled_outside_auto(tmp_path):
    trial, semantic_output, statics, _ = _pilot_trial(tmp_path, "P06")
    result = _run(trial, "P06", semantic_output, _PlcsimPV(lambda s: s.update(PID_Enable=True), statics))
    assert result["verdict"] == "FAIL" and any(v["invariant_id"] == "INV_PID_ONLY_AUTO" for v in result["safety"]["violations"])


def test_cleanup_restores_the_oracle_value_never_a_default(tmp_path):
    trial, semantic_output, statics, _ = _pilot_trial(tmp_path, "P09")
    sim = _PlcsimPV(_PILOTS["P09"]["logic"], statics)
    result = _run(trial, "P09", semantic_output, sim)
    restored = {entry["name"]: entry for entry in result["cleanup"]["process_variables"]}
    level = restored["DB_PLC_PRG.Level_PV"]
    assert level["restore_value"] == 50.0 and level["restore_source"] == "ORACLE_CLEANUP"  # cleanup_level del Oracle
    assert sim.state["Level_PV"] == 50.0 and result["cleanup"]["success"] is True
    signal = next(w["signal"] for step in sim.calls[0]["steps"] if step["op"] == "set" for w in step["writes"])
    assert signal["restore_value"] == 50.0


def test_output_process_variable_is_never_written(tmp_path):
    trial, semantic_output, statics, _ = _pilot_trial(tmp_path, "P04")
    sim = _PlcsimPV(_PILOTS["P04"]["logic"], statics)
    _run(trial, "P04", semantic_output, sim)
    watched = {s["name"]: s for s in next(step for step in sim.calls[0]["steps"] if step["op"] == "sample")["signals"]}
    assert watched["DB_PLC_PRG.High_Level_Alarm"]["writable"] is False and "restore_value" not in watched["DB_PLC_PRG.High_Level_Alarm"]
    with pytest.raises(oracle_runner.OracleSequenceError):
        oracle = json.loads(json.dumps(_oracle("P04")))
        oracle["test_sequence"][0]["set"] = {"HIGH_LEVEL_ALARM": True}  # copia en memoria: nunca el archivo FROZEN
        roles = oracle_runner.resolve_roles(oracle, {"channels": []}, PV.load_process_variable_bindings(trial))["roles"]
        oracle_runner.compile_sequence(oracle, roles, {"signals": {}}, PV.load_process_variable_bindings(trial))


def test_physical_target_is_rejected_before_touching_the_runtime(tmp_path):
    trial, semantic_output, statics, _ = _pilot_trial(tmp_path, "P04")
    sim = _PlcsimPV(_PILOTS["P04"]["logic"], statics)
    result = _run(trial, "P04", semantic_output, sim, target="PHYSICAL_PLC")
    assert result["verdict"] == "INFRASTRUCTURE_ERROR" and result["verdict_reason"] == oracle_runner.RUNTIME_NOT_READY
    assert sim.calls == []  # nunca se llama al bridge con un PLC fisico


def test_runtime_capabilities_declare_no_analog_or_raw_scaling():
    assert rio.RUNTIME_CAPABILITIES == ("BOOL", "REAL", "INTERNAL_TAG_READ", "INTERNAL_TAG_WRITE")
    assert rio.SUPPORTED_DATA_TYPES == ("BOOL",)  # E/S fisicas: solo BOOL, sin AI/AO ni 0-27648


def test_frozen_oracles_are_not_modified():
    assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(_ORACLES_DIR.glob("P*.json"))} == _ORACLE_HASHES
    for case_id in _PILOTS:
        oracle_schema.verify_integrity(_oracle(case_id))
