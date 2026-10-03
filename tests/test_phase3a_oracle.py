"""
Fase 3A: Oracle schema + Oracle Runner piloto (D03, D07, D12) y VALIDACION DEL INSTRUMENTO.

Nada de esto toca PLCSIM real: el bridge se sustituye por _SimPlc, un PLC simulado con reloj
virtual que ejecuta las operaciones set/sample de io_sequence con el mismo formato de reporte que el
bridge C#, y que corre ciclo a ciclo (10 ms) una logica de programa. Con programas CORRECTOS e
INCORRECTOS se comprueba que el instrumento distingue PASS / FAIL / REVIEW / INFRASTRUCTURE_ERROR
(controles positivos y negativos: validan el evaluador, no son resultados de la tesis).

Los snapshots se generan con trial_io_map sobre una COPIA del mapa del banco; los Oracles se
aprueban sobre COPIAS temporales; los mapas reales no se tocan (test final de hashes).
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402
import io_allocator  # noqa: E402
from trial_experiments import oracle_runner, oracle_schema, trial_io_map, trial_model  # noqa: E402
from utils import get_project_root  # noqa: E402

from test_phase1_download_and_trials import _arm_experiment_trial, _run, pipeline  # noqa: E402
from test_execute_full_pipeline import temp_map, _tia_ready  # noqa: E402

__all__ = ["pipeline", "temp_map", "_tia_ready"]

_ROOT = get_project_root()
_MAPS_DIR = _ROOT / "data" / "plc_maps"
_REAL_MAPS = [
    _MAPS_DIR / "mapa_banco_fisico_base.json",
    _MAPS_DIR / "mapa_simulacion_completo.json",
    _MAPS_DIR / "mapa_pid_simulacion.json",
    _MAPS_DIR / "mapa_pid_banco_fisico.json",
]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_HASHES_AT_IMPORT = {str(path): _hash(path) for path in _REAL_MAPS}
_ORACLES_DIR = _ROOT / "data" / "experiment_oracles"
_ORACLE_HASHES_AT_IMPORT = {str(p.relative_to(_ORACLES_DIR)): _hash(p) for p in _ORACLES_DIR.rglob("*.json")}

_CONFIG = {"instance_name": "TESIS_PLC_SIM", "io_settle_ms": 0, "io_timeout_seconds": 5,
           "api_dll_path": "x", "windows_adapter_match": "x", "timeout_seconds": 5}
_RUN = {"connected": True, "instance_name": "TESIS_PLC_SIM", "cpu_state": "RUN", "status": "CONNECTED"}


def _oracle(case_id: str) -> dict[str, Any]:
    """Piloto de la Fase 3A tal como se evaluo aqui: la version HISTORICA v1 (versions/), vuelta a
    borrador en memoria. Asi estas pruebas no dependen de que el investigador ya la haya aprobado
    ni de las versiones posteriores (Fase 3B: D07/D12 v2)."""
    pilot = json.loads((_ORACLES_DIR / "versions" / f"{case_id}_v1.json").read_text(encoding="utf-8"))
    pilot["approval"] = {**pilot["approval"], "status": "DRAFT", "approved_by": None, "approved_at": None, "hash": None}
    for item in pilot.get("review_items") or []:
        item["status"] = "OPEN"
        item.pop("acknowledged_by", None)
        item.pop("acknowledged_at", None)
    oracle_schema.assert_valid(pilot)
    return pilot


# ---------------------------------------------------------------------------------------------
# Snapshots reales del ensayo (trial_io_map sobre copia del banco)
# ---------------------------------------------------------------------------------------------

_CASES = {
    "D03": {
        "hints": [("I_Start", "arranque"), ("I_Stop", "paro"), ("Q_Motor_Enable", "motor")],
        "parameters": {"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable",
                       "run_latch": "M_RunLatch", "emergency_input": "FALSE"},
        "intent": "INT_MOTOR_START_STOP",
    },
    "D07": {
        "hints": [("I_Start", "arranque"), ("I_Stop", "paro"), ("Q_Motor_Enable", "motor")],
        "parameters": {"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable",
                       "delay_time": "T#3s", "emergency_input": "FALSE"},
        "intent": "INT_DELAYED_START",
    },
    "D12": {
        "hints": [("I_Start", "arranque"), ("I_Stop", "paro"), ("Q_Contactor_A", "contactor a"), ("Q_Contactor_B", "contactor b")],
        "parameters": {"trigger_input": "I_Start", "stop_input": "I_Stop", "contactor_a": "Q_Contactor_A",
                       "contactor_b": "Q_Contactor_B", "emergency_input": "FALSE"},
        "intent": "INT_MUTUAL_INTERLOCK",
    },
}


def _semantic(case_id: str, **parameter_overrides: Any) -> dict[str, Any]:
    case = _CASES[case_id]
    return {"intent_id": case["intent"], "parameters": {**case["parameters"], **parameter_overrides}}


def _make_snapshot(tmp_path: Path, case_id: str, semantic_output: dict[str, Any] | None = None,
                   extra_hints: list[tuple[str, str]] | None = None) -> Path:
    base = tmp_path / f"base_{case_id}.json"
    base.write_bytes((_MAPS_DIR / "mapa_banco_fisico_base.json").read_bytes())
    reference = trial_io_map.create_working_map(tmp_path / f"{case_id}_V1_TEXT_001", base)
    working = trial_io_map.load_working_map(Path(reference["working_map_path"]))
    requests = [{"functional_name_hint": name, "role_text": role} for name, role in _CASES[case_id]["hints"] + (extra_hints or [])]
    proposals = [p for p in io_allocator.propose_assignment(working, requests) if not p.get("blocked")]
    trial_io_map.apply_proposals_to_working_map(Path(reference["working_map_path"]), proposals, "TEXT_EXPLICIT", "PREPARING")
    frozen = trial_io_map.freeze_working_map(reference, semantic_output or _semantic(case_id), "PREPARING", f"{case_id}_V1_TEXT_001")
    return Path(frozen["snapshot_path"])


# ---------------------------------------------------------------------------------------------
# PLC simulado (reloj virtual, ciclo 10 ms) con el formato de reporte del bridge io_sequence
# ---------------------------------------------------------------------------------------------

Logic = Callable[[dict[str, bool], dict[str, Any], float], None]


class _SimPlc:
    CYCLE_MS = 10.0

    def __init__(self, logic: Logic, initial: dict[str, bool] | None = None, status_override: str | None = None,
                 cleanup_fails: bool = False) -> None:
        self.logic = logic
        self.io: dict[str, bool] = dict(initial or {})
        self.state: dict[str, Any] = {}
        self.t = 0.0
        self.status_override = status_override
        self.cleanup_fails = cleanup_fails
        self.calls: list[str] = []

    def _advance(self, until: float) -> None:
        while self.t + self.CYCLE_MS <= until:
            self.t += self.CYCLE_MS
            self.logic(self.io, self.state, self.CYCLE_MS)
        self.t = max(self.t, until)

    def __call__(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(action)
        report = {"status": "PLCSIM_IO_PASSED", "cpu_state": "RUN", "events": [], "samples": [], "writes": [],
                  "reads": [], "observations": [], "errors": [], "warnings": []}
        if self.status_override:
            return {**report, "status": self.status_override, "errors": [self.status_override]}
        written: list[str] = []
        for step in payload["steps"]:
            if step["op"] == "set":
                start = self.t
                entries = []
                for write in step["writes"]:
                    name = write["signal"]["name"]
                    self.io[name] = write["value"]
                    written.append(name)
                    entries.append({"name": name, "requested_value": write["value"], "actual_readback": write["value"],
                                    "readback_tag": write["value"], "match": True})
                report["events"].append({"type": "set", "id": step["id"], "phase": step["phase"], "t_ms": start,
                                         "t_done_ms": start + 0.5, "timestamp": "2026-09-28T18:00:00.000", "writes": entries})
                self.t += 0.5
            elif step["op"] == "sample":
                start, count = self.t, 0
                while True:
                    target = start + count * step["period_ms"]
                    target = min(target, start + step["duration_ms"])
                    self._advance(target)
                    values = {s["name"]: bool(self.io.get(s["name"], False)) for s in step["signals"]}
                    report["samples"].append({"id": step["id"], "phase": step["phase"], "t_ms": self.t, "values": values})
                    count += 1
                    if self.t - start >= step["duration_ms"]:
                        break
                require = step.get("require")
                if require and any(values.get(name) != value for name, value in require.items()):
                    report["status"] = "PLCSIM_SEQUENCE_REQUIREMENT_FAILED"
                    report["errors"].append(f"Requisito no cumplido en {step['id']}")
                    report["failed_step"] = step["id"]
                    break
        restored = []
        for name in dict.fromkeys(written):
            # cleanup_fails simula una entrada que se queda atascada en ON pese a la escritura a OFF.
            self.io[name] = bool(self.cleanup_fails)
            restored.append({"name": name, "restored": not self.io[name]})
        report["cleanup"] = {"performed": bool(written), "success": all(r["restored"] for r in restored), "inputs": restored}
        if not report["cleanup"]["success"] and report["status"] == "PLCSIM_IO_PASSED":
            report["status"] = "PLCSIM_IO_CLEANUP_FAILED"
        report["sequence_duration_ms"] = self.t
        return report


# Programas (logica por ciclo). Correctos = plantillas reales; incorrectos = defectos inyectados.

def _d03_ok(io, st, dt):
    io["Q_Motor_Enable"] = (io.get("Q_Motor_Enable", False) or io.get("I_Start", False)) and not io.get("I_Stop", False)


def _d03_stop_ignored(io, st, dt):
    io["Q_Motor_Enable"] = io.get("Q_Motor_Enable", False) or io.get("I_Start", False)


def _ton(delay_ms):
    def logic(io, st, dt):
        running = io.get("I_Start", False) and not io.get("I_Stop", False)
        st["elapsed"] = st.get("elapsed", 0.0) + dt if running else 0.0
        io["Q_Motor_Enable"] = running and st["elapsed"] >= delay_ms
    return logic


def _d12_ok(io, st, dt):
    if io.get("I_Start", False):
        io["Q_Contactor_A"] = not io.get("Q_Contactor_B", False)
    elif io.get("I_Stop", False):
        io["Q_Contactor_B"] = not io.get("Q_Contactor_A", False)


def _d12_no_interlock(io, st, dt):
    if io.get("I_Start", False):
        io["Q_Contactor_A"] = True
    if io.get("I_Stop", False):
        io["Q_Contactor_B"] = True


def _run_case(tmp_path, case_id, logic, semantic=None, snapshot=None, initial=None, runtime=None, sim=None, oracle=None):
    snapshot = snapshot or _make_snapshot(tmp_path, case_id, semantic)
    sim = sim or _SimPlc(logic, initial)
    result = oracle_runner.run_oracle(
        oracle or _oracle(case_id), snapshot, runtime or dict(_RUN), "PLCSIM_ADVANCED",
        semantic or _semantic(case_id), _ROOT, bridge=sim, runtime_config=_CONFIG,
    )
    return result, sim


# ---------- 1-5: schema, hash, aprobacion ----------

def test_pilot_oracles_are_valid_and_use_roles_not_addresses():
    for case_id in ("D03", "D07", "D12"):
        oracle = _oracle(case_id)
        assert oracle_schema.validate_oracle(oracle) == []
        assert oracle["approval"]["status"] in oracle_schema.APPROVAL_STATUSES
        assert "%I" not in json.dumps(oracle) and "%Q" not in json.dumps(oracle)


def test_invalid_oracle_is_rejected():
    oracle = copy.deepcopy(_oracle("D03"))
    del oracle["test_sequence"]
    assert any("test_sequence" in error for error in oracle_schema.validate_oracle(oracle))

    physical = copy.deepcopy(_oracle("D03"))
    physical["roles"]["START"]["description"] = "Pulsador en %I16.0"
    assert any("direcciones fisicas" in error for error in oracle_schema.validate_oracle(physical))

    writes_output = copy.deepcopy(_oracle("D03"))
    writes_output["test_sequence"][0]["set"] = {"MOTOR_MAIN": True}
    assert any("solo puede escribir roles INPUT" in error for error in oracle_schema.validate_oracle(writes_output))

    unknown_role = copy.deepcopy(_oracle("D12"))
    unknown_role["invariants"][0]["roles"] = ["CONTACTOR_A", "CONTACTOR_Z"]
    assert oracle_schema.validate_oracle(unknown_role)
    with pytest.raises(oracle_schema.OracleError) as error:
        oracle_schema.assert_valid(unknown_role)
    assert error.value.code == oracle_schema.ERROR_SCHEMA_INVALID


def test_oracle_hash_is_stable_and_excludes_approval():
    oracle = _oracle("D07")
    reordered = json.loads(json.dumps(oracle, sort_keys=True))
    assert oracle_schema.compute_oracle_hash(oracle) == oracle_schema.compute_oracle_hash(reordered)
    approved = copy.deepcopy(oracle)
    approved["approval"].update({"status": "FROZEN", "approved_by": "X", "approved_at": "2026-01-01T00:00:00", "hash": "h"})
    assert oracle_schema.compute_oracle_hash(approved) == oracle_schema.compute_oracle_hash(oracle)
    changed = copy.deepcopy(oracle)
    changed["test_sequence"][0]["wait_ms"] = 4600
    assert oracle_schema.compute_oracle_hash(changed) != oracle_schema.compute_oracle_hash(oracle)


def test_draft_oracle_only_runs_as_development_trial(tmp_path):
    result, _ = _run_case(tmp_path, "D03", _d03_ok)
    assert _oracle("D03")["approval"]["status"] == "DRAFT"
    # Diseno v2: el Oracle solo informa si es formal; el tipo de ensayo lo decide la fase de la sesion.
    assert result["oracle_formal"] is False and "trial_kind" not in result
    assert result["oracle_reference"]["oracle_status"] == "DRAFT"


@pytest.fixture
def oracle_copy_root(tmp_path) -> Path:
    """Copia temporal con los pilotos v1 en BORRADOR (nunca se aprueba nada en el repositorio)."""
    root = tmp_path / "project"
    target = root / "data" / "experiment_oracles"
    target.mkdir(parents=True)
    for case_id in ("D03", "D07", "D12"):
        (target / f"{case_id}.json").write_text(json.dumps(_oracle(case_id), indent=2), encoding="utf-8")
    return root


def test_frozen_oracle_is_immutable_and_versioned(oracle_copy_root):
    root = oracle_copy_root
    with pytest.raises(oracle_schema.OracleError) as open_items:
        oracle_schema.approve_oracle(root, "D12", "INV01")
    assert open_items.value.code == "ORACLE_REVIEW_ITEMS_OPEN" and len(open_items.value.details) == 3

    frozen = oracle_schema.approve_oracle(root, "D12", "INV01", acknowledge_review_items=True)
    assert frozen["approval"]["status"] == "FROZEN" and frozen["approval"]["hash"] == oracle_schema.compute_oracle_hash(frozen)
    assert frozen["approval"]["approved_by"] == "INV01" and frozen["approval"]["approved_at"]
    assert not oracle_schema.open_review_items(frozen)
    assert (root / "data" / "experiment_oracles" / "versions" / "D12_v1.json").exists()
    assert oracle_schema.load_oracle(root, "D12")["approval"]["status"] == "FROZEN"

    edited = copy.deepcopy(frozen)
    edited["test_sequence"][0]["wait_ms"] = 900
    with pytest.raises(oracle_schema.OracleError) as blocked:
        oracle_schema.save_oracle(root, edited)
    assert blocked.value.code == oracle_schema.ERROR_FROZEN
    with pytest.raises(oracle_schema.OracleError):
        oracle_schema.approve_oracle(root, "D12", "INV02", acknowledge_review_items=True)

    # Edicion por fuera de la herramienta: el hash aprobado ya no coincide -> integridad rota.
    path = root / "data" / "experiment_oracles" / "D12.json"
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["test_sequence"][0]["wait_ms"] = 900
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(oracle_schema.OracleError) as integrity:
        oracle_schema.load_oracle(root, "D12")
    assert integrity.value.code == oracle_schema.ERROR_INTEGRITY

    draft_v2 = oracle_schema.new_version(frozen)
    assert draft_v2["approval"]["version"] == 2 and draft_v2["approval"]["status"] == "DRAFT"
    assert draft_v2["approval"]["previous_hash"] == frozen["approval"]["hash"]


def test_formal_trial_requires_approved_oracle(oracle_copy_root, tmp_path):
    frozen = oracle_schema.approve_oracle(oracle_copy_root, "D03", "INV01")
    result, _ = _run_case(tmp_path, "D03", _d03_ok, oracle=frozen)
    assert result["oracle_formal"] is True and "trial_kind" not in result
    assert result["oracle_reference"]["oracle_hash"] == frozen["approval"]["hash"]
    assert result["verdict"] == "PASS"


# ---------- 6-8: role resolver ----------

def test_d03_roles_resolve_from_frozen_snapshot_bindings(tmp_path):
    snapshot = json.loads(_make_snapshot(tmp_path, "D03").read_text(encoding="utf-8"))
    resolution = oracle_runner.resolve_roles(_oracle("D03"), snapshot)
    assert resolution["status"] == "RESOLVED" and resolution["issues"] == []
    roles = {role: entry["functional_name"] for role, entry in resolution["roles"].items()}
    assert roles == {"START": "I_Start", "STOP": "I_Stop", "MOTOR_MAIN": "Q_Motor_Enable"}
    assert resolution["roles"]["START"]["matched_paths"] == ["trigger_input"]
    assert resolution["roles"]["MOTOR_MAIN"]["address"].startswith("%QX8.")


def test_missing_role_is_review_never_fail(tmp_path):
    semantic = _semantic("D03")
    del semantic["parameters"]["stop_input"]
    result, sim = _run_case(tmp_path, "D03", _d03_ok, semantic=semantic)
    assert result["verdict"] == "REVIEW" and result["verdict_reason"] == oracle_runner.ROLE_NOT_FOUND
    assert result["functional"]["success"] is None and sim.calls == []


def test_ambiguous_role_is_review(tmp_path):
    semantic = _semantic("D03", output="Q_Pilot_Run")
    snapshot = _make_snapshot(tmp_path, "D03", semantic, extra_hints=[("Q_Pilot_Run", "piloto")])
    result, sim = _run_case(tmp_path, "D03", _d03_ok, semantic=semantic, snapshot=snapshot)
    assert result["verdict"] == "REVIEW" and result["verdict_reason"] == oracle_runner.ROLE_AMBIGUOUS
    issue = result["roles"]["issues"][0]
    assert issue["role"] == "MOTOR_MAIN" and sorted(issue["candidates"]) == ["Q_Motor_Enable", "Q_Pilot_Run"]
    assert sim.calls == [], "con un rol ambiguo nunca se ejecuta la secuencia"


# ---------- 9-10: precondiciones ----------

def test_precondition_success_clears_latched_state(tmp_path):
    # Control: el motor venia ENCLAVADO de una prueba anterior; STOP lo apaga en la precondicion.
    result, _ = _run_case(tmp_path, "D03", _d03_ok, initial={"Q_Motor_Enable": True})
    assert result["preconditions"]["success"] is True
    assert result["verdict"] == "PASS"


def test_precondition_failure_is_review_and_stops_the_test(tmp_path):
    # D12 legacy no tiene apagado: si A ya estaba activo, el estado inicial no puede establecerse.
    result, _ = _run_case(tmp_path, "D12", _d12_ok, initial={"Q_Contactor_A": True})
    assert result["verdict"] == "REVIEW" and result["verdict_reason"] == oracle_runner.PRECONDITION_FAILED
    assert result["preconditions"]["success"] is False
    assert result["functional"]["success"] is None
    assert all(not step["executed"] for step in result["steps"] if step["phase"] == "test")


# ---------- 11-17: controles positivos / negativos del instrumento ----------

def test_control_positive_d03_correct_program_passes(tmp_path):
    result, _ = _run_case(tmp_path, "D03", _d03_ok)
    assert result["verdict"] == "PASS"
    assert result["functional"] == {**result["functional"], "success": True, "passed_checks": 4, "total_checks": 4, "pass_rate": 1.0}
    assert result["safety"]["success"] is True and result["semantic"]["success"] is True
    step_1 = next(step for step in result["steps"] if step["step_id"] == "step_1")
    assert step_1["actual_outputs"] == {"START": True, "STOP": False, "MOTOR_MAIN": True}
    assert step_1["inputs_applied"]["START"]["match"] is True and step_1["started_at"] and step_1["completed_at"]


def test_control_negative_a_stop_does_not_stop_motor_fails(tmp_path):
    result, _ = _run_case(tmp_path, "D03", _d03_stop_ignored)
    assert result["verdict"] == "FAIL" and result["verdict_reason"] in ("FUNCTIONAL_FAILURE",)
    assert result["functional"]["success"] is False
    failed = {check["step_id"] for check in result["functional"]["failed_checks"]}
    assert "step_3" in failed


def test_control_positive_d07_delay_within_tolerance_passes(tmp_path):
    result, _ = _run_case(tmp_path, "D07", _ton(3000))
    assert result["verdict"] == "PASS", result["errors"]
    transition = next(c for s in result["steps"] for c in s["checks"] if c["type"] == "transition")
    assert 2700 <= transition["actual_observation_time"] <= 3700
    assert abs(transition["actual_observation_time"] - 3000) <= 60
    timeline = [c for s in result["steps"] for c in s["checks"] if c["type"] == "timeline"]
    assert len(timeline) == 2 and all(c["passed"] and c["samples_in_window"] > 5 for c in timeline)


def test_control_negative_b_d07_starts_before_delay_fails(tmp_path):
    result, _ = _run_case(tmp_path, "D07", _ton(1000))
    assert result["verdict"] == "FAIL" and result["functional"]["success"] is False
    early = next(c for c in result["functional"]["failed_checks"] if c["type"] == "timeline")
    assert early["expected"] is False and early["actual"] is True and early["actual_observation_time"] < 2700
    transition = next(c for c in result["functional"]["failed_checks"] if c["type"] == "transition")
    assert transition["actual_observation_time"] < 1100


def test_d07_semantic_delay_mismatch_with_correct_behaviour_is_review(tmp_path):
    assert oracle_runner.parse_duration_ms("T#3s") == 3000
    assert oracle_runner.parse_duration_ms("T#1m30s") == 90000
    assert oracle_runner.parse_duration_ms("3000ms") == 3000
    assert oracle_runner.parse_duration_ms(3) is None and oracle_runner.parse_duration_ms("tres") is None
    result, _ = _run_case(tmp_path, "D07", _ton(3000), semantic=_semantic("D07", delay_time="T#5s"))
    assert result["functional"]["success"] is True
    assert result["semantic"]["success"] is False
    assert result["verdict"] == "REVIEW" and result["verdict_reason"] == oracle_runner.SEMANTIC_MISMATCH


def test_control_positive_d12_interlock_passes(tmp_path):
    result, _ = _run_case(tmp_path, "D12", _d12_ok)
    assert result["verdict"] == "PASS", result["errors"]
    assert result["safety"]["success"] is True and result["safety"]["violations"] == []
    assert result["safety"]["samples_checked"] > 40
    roles = {role: entry["functional_name"] for role, entry in result["roles"]["roles"].items()}
    assert roles == {"COMMAND_A": "I_Start", "COMMAND_B": "I_Stop", "CONTACTOR_A": "Q_Contactor_A", "CONTACTOR_B": "Q_Contactor_B"}


def test_control_negative_c_d12_both_contactors_fail_with_safety_violation(tmp_path):
    result, _ = _run_case(tmp_path, "D12", _d12_no_interlock)
    assert result["verdict"] == "FAIL" and result["verdict_reason"] == "SAFETY_VIOLATION"
    # functional y safety separados: step_1 (unica expectativa evaluable) pasa, la seguridad no.
    assert result["functional"]["success"] is True and result["functional"]["passed_checks"] == 2
    assert result["safety"]["success"] is False and result["safety"]["critical_violations"] > 0
    violation = result["safety"]["violations"][0]
    assert violation["invariant_id"] == "INV_AB_EXCLUSIVE" and violation["step_id"] == "step_2"
    assert violation["values"] == {"CONTACTOR_A": True, "CONTACTOR_B": True}
    assert violation["signals"] == {"CONTACTOR_A": "Q_Contactor_A", "CONTACTOR_B": "Q_Contactor_B"}
    assert violation["t_ms"] is not None


def test_control_negative_d_ambiguous_signal_is_review_not_fail(tmp_path):
    semantic = _semantic("D12", command_a="I_Reset_A")
    snapshot = _make_snapshot(tmp_path, "D12", semantic, extra_hints=[("I_Reset_A", "orden a")])
    result, _ = _run_case(tmp_path, "D12", _d12_ok, semantic=semantic, snapshot=snapshot)
    assert result["verdict"] == "REVIEW" and result["verdict_reason"] == oracle_runner.ROLE_AMBIGUOUS
    assert oracle_runner.decide_final_status(True, True, True, result["verdict"]) == "REVIEW"


def test_control_negative_e_runtime_unavailable_is_infrastructure_error(tmp_path):
    result, sim = _run_case(tmp_path, "D03", _d03_ok, sim=_SimPlc(_d03_ok, status_override="PLCSIM_RUNTIME_UNAVAILABLE"))
    assert result["verdict"] == "INFRASTRUCTURE_ERROR" and result["verdict_reason"] == "PLCSIM_RUNTIME_UNAVAILABLE"
    assert result["functional"]["success"] is None

    disconnected, sim2 = _run_case(tmp_path, "D03", _d03_ok, runtime={"connected": False, "status": "PLCSIM_RUNTIME_UNAVAILABLE"})
    assert disconnected["verdict"] == "INFRASTRUCTURE_ERROR" and disconnected["verdict_reason"] == oracle_runner.RUNTIME_NOT_READY
    assert sim2.calls == []
    stopped, _ = _run_case(tmp_path, "D03", _d03_ok, runtime={**_RUN, "cpu_state": "STOP"})
    assert stopped["verdict"] == "INFRASTRUCTURE_ERROR"


# ---------- 18-21: cleanup, REVIEW vs FAIL, reporte ----------

def test_cleanup_leaves_all_oracle_inputs_off(tmp_path):
    result, sim = _run_case(tmp_path, "D12", _d12_ok)
    assert result["cleanup"]["performed"] is True and result["cleanup"]["success"] is True
    assert sim.io["I_Start"] is False and sim.io["I_Stop"] is False
    failing, _ = _run_case(tmp_path, "D03", _d03_ok, sim=_SimPlc(_d03_ok, cleanup_fails=True))
    assert failing["cleanup"]["success"] is False
    assert any("PLCSIM_IO_CLEANUP_FAILED" in error for error in failing["errors"])


def test_review_is_never_counted_as_fail():
    semantic = {"success": True}
    ok = {"success": True}
    assert oracle_runner.decide_verdict(None, [oracle_runner.ROLE_AMBIGUOUS], semantic, {"success": None}, {"success": None})[0] == "REVIEW"
    assert oracle_runner.decide_verdict(None, [], semantic, ok, ok)[0] == "PASS"
    assert oracle_runner.decide_verdict(None, [], semantic, {"success": False}, ok)[0] == "FAIL"
    assert oracle_runner.decide_verdict(None, [], semantic, ok, {"success": False})[0] == "FAIL"
    assert oracle_runner.decide_verdict("PLCSIM_RUNTIME_UNAVAILABLE", [], semantic, ok, {"success": False})[0] == "INFRASTRUCTURE_ERROR"
    assert oracle_runner.decide_final_status(False, None, None, None) == "FAIL"
    assert oracle_runner.decide_final_status(True, False, None, None) == "INFRASTRUCTURE_ERROR"
    assert oracle_runner.decide_final_status(True, True, True, "REVIEW") == "REVIEW"


def test_evaluation_report_is_serializable_with_manual_audit_schema(tmp_path):
    result, _ = _run_case(tmp_path, "D03", _d03_ok)
    record = trial_model.new_trial_record("D03", "V1", "TEXT", 1)
    record["stages"].update({"compile_success": True, "download_success": True})
    report = oracle_runner.build_evaluation_report(record, result, "PASS")
    artifacts = oracle_runner.write_oracle_artifacts(tmp_path / "trial", result, report)
    loaded = json.loads(Path(artifacts["evaluation_report"]).read_text(encoding="utf-8"))
    for key in ("trial_id", "oracle", "semantic", "compile", "download", "runtime", "functional", "safety",
                "final_status", "steps", "errors", "timings", "manual_audit"):
        assert key in loaded
    assert loaded["manual_audit"] == {"selected": False, "reviewer": None, "automated_result": None,
                                      "manual_result": None, "agreement": None, "notes": None}
    trace = json.loads(Path(artifacts["oracle_trace"]).read_text(encoding="utf-8"))
    assert trace["samples"] and trace["events"]


# ---------- 22-23: GUI / trial.json ----------

def test_trial_records_oracle_hash_and_separate_functional_safety(pipeline, tmp_path, monkeypatch):
    app = pipeline["app"]
    oracle = _oracle("D12")
    precomputed, _ = _run_case(tmp_path, "D12", _d12_no_interlock)
    monkeypatch.setattr(gui, "find_case_oracle", lambda root, case_id: oracle if case_id == "D12" else None)
    monkeypatch.setattr(gui, "run_oracle", lambda *args, **kwargs: precomputed)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    trial_directory = _arm_experiment_trial(app)

    _run(app)

    record = trial_model.load_trial(trial_directory)
    assert record["oracle_reference"]["oracle_id"] == "D12"
    assert record["oracle_reference"]["oracle_hash"] == oracle_schema.compute_oracle_hash(oracle)
    assert record["oracle_reference"]["oracle_version"] == 1
    assert record["trial_kind"] == trial_model.TRIAL_KIND_DEVELOPMENT  # fase de desarrollo (Oracle FROZEN no lo cambia)
    assert record["experiment_phase"] == trial_model.PHASE_DEVELOPMENT
    assert record["functional"]["success"] is True and record["safety"]["success"] is False
    assert record["stages"]["functional_success"] is True and record["stages"]["safety_success"] is False
    assert record["final_status"] == "FAIL"
    assert (trial_directory / "evaluation_report.json").exists() and (trial_directory / "oracle_trace.json").exists()
    assert app._experiment_stage_states["Safety"] == "fail" and app._experiment_stage_states["Functional"] == "ok"


def test_trial_with_oracle_but_cpu_not_run_is_infrastructure_error(pipeline, monkeypatch):
    app = pipeline["app"]
    monkeypatch.setattr(gui, "find_case_oracle", lambda root, case_id: _oracle("D12"))
    monkeypatch.setattr(gui, "get_plcsim_runtime_status", lambda root: {"status": "CONNECTED", "connected": True,
                        "instance_name": "TESIS_PLC_SIM", "cpu_state": "STOP", "errors": [], "warnings": []})
    monkeypatch.setattr(gui, "run_oracle", lambda *a, **k: pytest.fail("no debe ejecutarse el Oracle sin RUN"))
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    trial_directory = _arm_experiment_trial(app)
    _run(app)
    record = trial_model.load_trial(trial_directory)
    assert record["final_status"] == "INFRASTRUCTURE_ERROR"
    assert record["oracle_reference"]["oracle_id"] == "D12"


def test_gui_oracle_status_line_shows_version_and_state(app, monkeypatch):
    monkeypatch.setattr(gui, "find_case_oracle", lambda root, case_id: _oracle(case_id) if case_id == "D07" else None)
    monkeypatch.setattr(app, "_selected_case_id", lambda: "D07")
    app._refresh_oracle_status()
    assert app.oracle_status_var.get().startswith("Oracle: D07 v1 · DRAFT")
    assert "2 punto(s) REVIEW" in app.oracle_status_var.get()
    monkeypatch.setattr(app, "_selected_case_id", lambda: "D99")
    app._refresh_oracle_status()
    assert "sin Oracle" in app.oracle_status_var.get()


# ---------- 24: mapas reales y Oracles del repositorio intactos ----------

def test_real_maps_and_repository_oracles_unchanged():
    for path in _REAL_MAPS:
        assert _hash(path) == _HASHES_AT_IMPORT[str(path)], f"{path.name} fue modificado durante los tests"
    current = {str(p.relative_to(_ORACLES_DIR)): _hash(p) for p in _ORACLES_DIR.rglob("*.json")}
    assert current == _ORACLE_HASHES_AT_IMPORT, "los tests no deben crear/modificar Oracles del repositorio"
