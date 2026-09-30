"""
Fase 3B: los 32 Oracles (D01-D20, P01-P12), su revision asistida y la validacion del instrumento.

1. Inventario: exactamente 32, ids completos, schema valido, sin direcciones fisicas, hashes,
   versiones congeladas intactas (D03 v1, D07 v1, D12 v1), D07/D12 v2, estados de revision.
2. SEGUNDA PASADA ejecutable: para cada Oracle ejecutable hoy, un programa CORRECTO segun la
   definicion del caso (no la plantilla del generador) debe dar PASS en un PLC simulado con reloj
   virtual; para cada FAMILIA funcional, un programa defectuoso debe ser rechazado. Asi se valida
   que el Oracle ni exige de mas (el correcto pasa) ni deja pasar errores claros.
3. PID: no ejecutable hoy (REQUIRES_RUNTIME_EXTENSION -> REVIEW sin tocar el bridge); su logica de
   evaluacion se valida igualmente con trazas simuladas (controles positivos y negativos).
4. Herramientas de revision: reporte de validacion, resumen humano, aprobacion masiva bloqueada
   con review_items abiertos.

Nada toca PLCSIM real ni los Oracles/mapas del repositorio (tests de hashes al final).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import io_allocator  # noqa: E402
from trial_experiments import oracle_review, oracle_runner, oracle_schema, trial_io_map  # noqa: E402
from utils import get_project_root  # noqa: E402

_ROOT = get_project_root()
_MAPS_DIR = _ROOT / "data" / "plc_maps"
_ORACLES_DIR = _ROOT / "data" / "experiment_oracles"
_REAL_MAPS = [_MAPS_DIR / f"{name}.json" for name in
              ("mapa_banco_fisico", "mapa_simulacion_completo", "mapa_pid_simulacion", "mapa_pid_banco_fisico")]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_MAP_HASHES = {str(p): _hash(p) for p in _REAL_MAPS}
_ORACLE_HASHES = {str(p.relative_to(_ORACLES_DIR)): _hash(p) for p in _ORACLES_DIR.rglob("*.json")}
_EXPECTED_IDS = [f"D{i:02d}" for i in range(1, 21)] + [f"P{i:02d}" for i in range(1, 13)]
_CONFIG = {"instance_name": "TESIS_PLC_SIM", "io_settle_ms": 0, "io_timeout_seconds": 5,
           "api_dll_path": "x", "windows_adapter_match": "x", "timeout_seconds": 5}
_RUN = {"connected": True, "instance_name": "TESIS_PLC_SIM", "cpu_state": "RUN", "status": "CONNECTED"}


def _oracle(case_id: str) -> dict[str, Any]:
    return oracle_schema.load_oracle(_ROOT, case_id)


# =============================================================================================
# 1. Inventario y versiones
# =============================================================================================

def test_exactly_32_oracles_with_complete_unique_ids():
    files = sorted(p.stem for p in _ORACLES_DIR.glob("*.json"))
    assert files == sorted(_EXPECTED_IDS)
    ids = [_oracle(case_id)["oracle_id"] for case_id in files]
    assert len(ids) == len(set(ids)) == 32


@pytest.mark.parametrize("case_id", _EXPECTED_IDS)
def test_every_oracle_is_schema_valid_without_physical_addresses(case_id):
    oracle = _oracle(case_id)
    assert oracle_schema.validate_oracle(oracle) == []
    text = json.dumps(oracle_schema.normalized_content(oracle))
    assert not re.search(r"%[IQM][XBWD]?\d", text, re.IGNORECASE)
    if oracle_schema.is_formal(oracle):
        assert oracle["approval"]["hash"] == oracle_schema.compute_oracle_hash(oracle)
    else:
        assert oracle["approval"]["approved_by"] is None and oracle["approval"]["hash"] is None
        assert oracle["approval"]["status"] == oracle_schema.STATUS_DRAFT_REVIEWED
        review = oracle["approval"]["ai_review"]
        assert review["generated"] and review["schema_validated"] and review["semantic_reviewed"] and review["reviewed_at"]


@pytest.mark.parametrize("case_id", _EXPECTED_IDS)
def test_runtime_requirements_are_correctly_marked(case_id):
    oracle = _oracle(case_id)
    support = oracle_schema.runtime_support(oracle)
    if case_id.startswith("P"):
        assert support == oracle_schema.RUNTIME_REQUIRES_EXTENSION
        assert {"REAL", "INTERNAL_TAG_READ"} & set(oracle_schema.derived_runtime_requirements(oracle))
    else:
        assert support == oracle_schema.RUNTIME_EXECUTABLE_NOW
        assert oracle_schema.derived_runtime_requirements(oracle) == ["BOOL"]
    if "runtime_requirements" in oracle:
        assert oracle["runtime_requirements"] == oracle_schema.derived_runtime_requirements(oracle)


def test_frozen_versions_are_preserved_and_d03_unchanged():
    d03 = _oracle("D03")
    assert d03["approval"]["status"] == "FROZEN" and d03["approval"]["version"] == 1
    assert d03["approval"]["hash"] == "b444a550d900d61ca67053bfa17cdec706e2149d9d78c0a3790ecf131aa1dc92"
    for case_id in ("D03", "D07", "D12"):
        v1 = json.loads((_ORACLES_DIR / "versions" / f"{case_id}_v1.json").read_text(encoding="utf-8"))
        assert v1["approval"]["status"] == "FROZEN" and v1["approval"]["version"] == 1
        assert v1["approval"]["hash"] == oracle_schema.compute_oracle_hash(v1)


def test_d07_v2_redefinition():
    d07 = _oracle("D07")
    v1 = json.loads((_ORACLES_DIR / "versions" / "D07_v1.json").read_text(encoding="utf-8"))
    assert d07["approval"]["version"] == 2 and d07["approval"]["previous_hash"] == v1["approval"]["hash"]
    assert set(d07["roles"]) == {"START", "MOTOR_MAIN"}
    assert [s["id"] for s in d07["test_sequence"]] == ["step_1"]
    step = d07["test_sequence"][0]
    assert step["set"] == {"START": True} and step["wait_ms"] == 4500
    assert [(w["from_ms"], w["to_ms"], w["expect"]["MOTOR_MAIN"]) for w in step["expect_timeline"]] == [(0, 2700, False), (3700, 4500, True)]
    assert step["measure_transition"]["nominal_ms"] == 3000 and step["measure_transition"]["tolerance_ms"] == {"early": 300, "late": 700}
    assert d07["cleanup"][0]["set"] == {"START": False}
    assert {item["id"]: item["status"] for item in d07["review_items"]} == {"D07-R1": "RESOLVED", "D07-R2": "RESOLVED"}
    assert not oracle_schema.open_review_items(d07)


def test_d12_v2_redefinition():
    d12 = _oracle("D12")
    v1 = json.loads((_ORACLES_DIR / "versions" / "D12_v1.json").read_text(encoding="utf-8"))
    assert d12["approval"]["version"] == 2 and d12["approval"]["previous_hash"] == v1["approval"]["hash"]
    assert set(d12["roles"]) == {"REQUEST_A", "REQUEST_B", "CONTACTOR_A", "CONTACTOR_B"}
    for role in ("REQUEST_A", "REQUEST_B"):
        assert "trigger_input" not in d12["roles"][role]["semantic_paths"] and "stop_input" not in d12["roles"][role]["semantic_paths"]
    tests = {s["id"]: s for s in d12["test_sequence"]}
    assert tests["test_1"]["expect"] == {"CONTACTOR_A": True, "CONTACTOR_B": False}
    assert tests["test_2"]["expect"] == {"CONTACTOR_A": False, "CONTACTOR_B": True}
    assert tests["test_3"]["expect"] == {"CONTACTOR_A": False, "CONTACTOR_B": False}
    assert "expect" not in tests["test_4"] and set(tests["test_4"]["unspecified"]) == {"CONTACTOR_A", "CONTACTOR_B"}
    assert d12["invariants"][0]["type"] == "NEVER_TRUE_TOGETHER" and d12["invariants"][0]["severity"] == "CRITICAL"
    assert all(item["status"] == "RESOLVED" for item in d12["review_items"])


def test_frozen_oracle_is_immutable(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(_ORACLES_DIR, root / "data" / "experiment_oracles")
    shutil.copytree(_ROOT / "data" / "experiment_cases", root / "data" / "experiment_cases")  # catalogo canonico (alineacion)
    d03 = oracle_schema.load_oracle(root, "D03")
    edited = json.loads(json.dumps(d03))
    edited["test_sequence"][0]["wait_ms"] = 900
    with pytest.raises(oracle_schema.OracleError) as error:
        oracle_schema.save_oracle(root, edited)
    assert error.value.code == oracle_schema.ERROR_FROZEN
    # Una nueva version solo se publica con previous_hash correcto y conservando la anterior.
    wrong = oracle_schema.new_version(d03)
    wrong["approval"]["previous_hash"] = "x"
    with pytest.raises(oracle_schema.OracleError):
        oracle_schema.supersede_frozen(root, wrong)


# =============================================================================================
# 2. PLC simulado con reloj virtual (valores BOOL y numericos)
# =============================================================================================

class _Sim:
    CYCLE_MS = 10.0

    def __init__(self, logic, initial=None):
        self.logic, self.io, self.state, self.t, self.calls = logic, dict(initial or {}), {}, 0.0, []

    def _advance(self, until):
        while self.t + self.CYCLE_MS <= until:
            self.t += self.CYCLE_MS
            self.logic(self.io, self.state, self.CYCLE_MS)
        self.t = max(self.t, until)

    def __call__(self, action, payload):
        self.calls.append(action)
        if self.t == 0.0:
            # En el PLC real el programa ya lleva ciclos ejecutandose cuando empieza el Oracle.
            self._advance(self.CYCLE_MS)
        report = {"status": "PLCSIM_IO_PASSED", "cpu_state": "RUN", "events": [], "samples": [], "errors": [], "warnings": []}
        written = []
        for step in payload["steps"]:
            if step["op"] == "set":
                for write in step["writes"]:
                    self.io[write["signal"]["name"]] = write["value"]
                    written.append(write["signal"]["name"])
                report["events"].append({"type": "set", "id": step["id"], "phase": step["phase"], "t_ms": self.t,
                                         "t_done_ms": self.t + 0.5, "timestamp": "2026-09-29T12:00:00.000",
                                         "writes": [{"name": w["signal"]["name"], "match": True} for w in step["writes"]]})
                self.t += 0.5
            else:
                start, count = self.t, 0
                while True:
                    self._advance(min(start + count * step["period_ms"], start + step["duration_ms"]))
                    values = {s["name"]: self.io.get(s["name"], False) for s in step["signals"]}
                    report["samples"].append({"id": step["id"], "phase": step["phase"], "t_ms": self.t, "values": values})
                    count += 1
                    if self.t - start >= step["duration_ms"]:
                        break
                require = step.get("require")
                if require and any(not oracle_runner.value_matches(v, values.get(k)) for k, v in require.items()):
                    report["status"] = "PLCSIM_SEQUENCE_REQUIREMENT_FAILED"
                    report["failed_step"] = step["id"]
                    break
        for name in dict.fromkeys(written):
            if isinstance(self.io.get(name), bool):
                self.io[name] = False
        report["cleanup"] = {"performed": bool(written), "success": True, "inputs": []}
        return report


# --- snapshot real del ensayo para cada caso (IOAllocator real sobre copia del banco) ---------

_CASES: dict[str, dict[str, Any]] = {
    "D01": {"names": ["I_Start", "Q_Aux_Output"], "params": {"trigger_input": "I_Start", "output": "Q_Aux_Output", "duration": "T#5s"},
            "intent": "INT_TIMED_PULSE"},
    "D02": {"names": ["I_Sensor1", "Q_Pilot_Run"], "params": {"trigger_input": "I_Sensor1", "output": "Q_Pilot_Run"}, "intent": "INT_DIRECT_OUTPUT"},
    "D03": {"names": ["I_Start", "I_Stop", "Q_Motor_Enable"],
            "params": {"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable"}, "intent": "INT_MOTOR_START_STOP"},
    "D04": {"names": ["I_Start", "I_Stop", "Q_Motor_Enable"],
            "params": {"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable"}, "intent": "INT_MOTOR_LATCH"},
    "D05": {"names": ["I_Emergency", "I_Start", "Q_Motor_Enable"],
            "params": {"emergency_input": "I_Emergency", "trigger_input": "I_Start", "motor_output": "Q_Motor_Enable"},
            "intent": "INT_EMERGENCY_PRIORITY"},
    "D06": {"names": ["I_Start", "I_Sensor1", "I_Reset", "Q_Motor_Enable", "Q_Alarm"],
            "params": {"trigger_input": "I_Start", "safety_input": "I_Sensor1", "reset_input": "I_Reset",
                       "motor_output": "Q_Motor_Enable", "alarm_output": "Q_Alarm"}, "intent": "INT_SAFE_START_ALARM"},
    "D07": {"names": ["I_Start", "Q_Motor_Enable"],
            "params": {"trigger_input": "I_Start", "motor_output": "Q_Motor_Enable", "delay_time": "T#3s"}, "intent": "INT_DELAYED_START"},
    "D08": {"names": ["I_Start", "I_Stop", "Q_Motor_Enable"],
            "params": {"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable", "stop_delay_time": "T#10s"},
            "intent": "INT_DELAYED_STOP"},
    "D09": {"names": ["I_Sensor1", "I_Reset", "Q_Aux_Output"],
            "params": {"pulse_input": "I_Sensor1", "reset_input": "I_Reset", "output": "Q_Aux_Output", "preset": 5},
            "intent": "INT_COUNTER_PULSES"},
    "D10": {"names": ["I_Reset", "I_Sensor1", "Q_Aux_Output"],
            "params": {"reset_input": "I_Reset", "pulse_input": "I_Sensor1", "output": "Q_Aux_Output"}, "intent": "INT_COUNTER_RESET"},
    "D11": {"names": ["I_Start", "I_Stop", "I_Emergency", "Q_Contactor_A"],
            "params": {"trigger_input": "I_Start", "stop_input": "I_Stop", "emergency_input": "I_Emergency", "motor_output": "Q_Contactor_A"},
            "intent": "INT_MOTOR_START_STOP"},
    "D12": {"names": ["I_Request_A", "I_Request_B", "Q_Contactor_A", "Q_Contactor_B"],
            "params": {"request_a": "I_Request_A", "request_b": "I_Request_B", "contactor_a": "Q_Contactor_A", "contactor_b": "Q_Contactor_B"},
            "intent": "INT_MUTUAL_INTERLOCK"},
    "D13": {"names": ["I_Start", "I_Alarm", "Q_Motor_Enable"],
            "params": {"trigger_input": "I_Start", "alarm_input": "I_Alarm", "motor_output": "Q_Motor_Enable"}, "intent": "INT_VFD_ENABLE_NO_ALARM"},
    "D14": {"names": ["I_Speed_Low", "I_Speed_Medium", "I_Speed_High", "Q_Speed_Low", "Q_Speed_Medium", "Q_Speed_High"],
            "params": {"speed_low_input": "I_Speed_Low", "speed_medium_input": "I_Speed_Medium", "speed_high_input": "I_Speed_High",
                       "speed_low_output": "Q_Speed_Low", "speed_medium_output": "Q_Speed_Medium", "speed_high_output": "Q_Speed_High"},
            "intent": None},
    "D15": {"names": ["I_Mode_Manual", "I_Mode_Auto", "I_Start", "I_Stop", "Q_Motor_Enable"],
            "params": {"manual_input": "I_Mode_Manual", "auto_input": "I_Mode_Auto", "trigger_input": "I_Start", "stop_input": "I_Stop",
                       "motor_output": "Q_Motor_Enable"}, "intent": "INT_MANUAL_AUTO_MODE"},
    "D16": {"names": ["I_Start", "I_Reset", "Q_Aux_Output"],
            "params": {"trigger_input": "I_Start", "reset_input": "I_Reset", "output": "Q_Aux_Output"}, "intent": "INT_SEQUENCE_THREE_STEPS"},
    "D17": {"names": ["I_Start", "I_Sensor1", "Q_Alarm"],
            "params": {"trigger_input": "I_Start", "sensor_input": "I_Sensor1", "alarm_output": "Q_Alarm", "timeout": "T#5s"},
            "intent": "INT_SENSOR_TIMEOUT_ALARM"},
    "D18": {"names": ["I_Maintenance", "I_Start", "Q_Motor_Enable"],
            "params": {"maintenance_input": "I_Maintenance", "trigger_input": "I_Start", "motor_output": "Q_Motor_Enable"},
            "intent": "INT_MAINTENANCE_BLOCK"},
    "D19": {"names": ["I_Start", "I_Stop", "I_Fault", "Q_Pilot_Stop", "Q_Pilot_Run", "Q_Pilot_Fault"],
            "params": {"trigger_input": "I_Start", "stop_input": "I_Stop", "fault_input": "I_Fault", "stop_indicator": "Q_Pilot_Stop",
                       "run_indicator": "Q_Pilot_Run", "fault_indicator": "Q_Pilot_Fault"}, "intent": None},
    "D20": {"names": ["I_Mode_Auto", "I_Start", "I_Stop", "I_Reset", "I_Emergency", "Q_Motor_Enable", "Q_Aux_Output", "Q_Alarm"],
            "params": {"auto_input": "I_Mode_Auto", "trigger_input": "I_Start", "stop_input": "I_Stop", "reset_input": "I_Reset",
                       "emergency_input": "I_Emergency", "motor_output": "Q_Motor_Enable", "aux_output": "Q_Aux_Output",
                       "alarm_output": "Q_Alarm"}, "intent": "INT_AUTO_CYCLE"},
}


# Fase 3B-CLOSE: senales de los casos redefinidos por las decisiones del investigador.
_CASES.update({
    "D05": {"names": ["I_Start", "I_Safety_Trip", "Q_Motor_Enable"],
            "params": {"trigger_input": "I_Start", "safety_trip": "I_Safety_Trip", "motor_output": "Q_Motor_Enable"},
            "intent": "INT_EMERGENCY_PRIORITY"},
    "D06": {"names": ["I_Start", "I_Sensor1", "Q_Alarm"],
            "params": {"trigger_input": "I_Start", "safety_input": "I_Sensor1", "alarm_output": "Q_Alarm"}, "intent": "INT_SAFE_START_ALARM"},
    "D08": {"names": ["I_Start", "Q_Motor_Enable"],
            "params": {"trigger_input": "I_Start", "motor_output": "Q_Motor_Enable", "operation_time": "T#10s"}, "intent": "INT_AUTO_STOP_TIMER"},
    "D15": {"names": ["I_Mode_Auto", "I_Manual_Cmd", "I_Auto_Cmd", "Q_Motor_Enable"],
            "params": {"mode_auto": "I_Mode_Auto", "manual_command": "I_Manual_Cmd", "auto_command": "I_Auto_Cmd",
                       "motor_output": "Q_Motor_Enable"}, "intent": "INT_MANUAL_AUTO_MODE"},
    "D16": {"names": ["I_Start", "Q_Motor_Enable", "Q_Aux_Output"],
            "params": {"trigger_input": "I_Start", "main_output": "Q_Motor_Enable", "aux_output": "Q_Aux_Output"},
            "intent": "INT_SEQUENCE_THREE_STEPS"},
    "D19": {"names": ["I_Run_State", "I_Fault", "Q_Pilot_Stop", "Q_Pilot_Run", "Q_Pilot_Fault"],
            "params": {"run_state": "I_Run_State", "fault_active": "I_Fault", "stop_indicator": "Q_Pilot_Stop",
                       "run_indicator": "Q_Pilot_Run", "fault_indicator": "Q_Pilot_Fault"}, "intent": None},
    "D20": {"names": ["I_Start", "I_Reset", "Q_Run", "Q_Complete"],
            "params": {"trigger_input": "I_Start", "reset_input": "I_Reset", "run_output": "Q_Run", "complete_output": "Q_Complete"},
            "intent": "INT_AUTO_CYCLE"},
})


def _snapshot(tmp_path: Path, case_id: str, params: dict[str, Any] | None = None, names: list[str] | None = None) -> Path:
    case = _CASES[case_id]
    params = params if params is not None else case["params"]
    base = tmp_path / f"base_{case_id}.json"
    if not base.exists():
        base.write_bytes((_MAPS_DIR / "mapa_banco_fisico.json").read_bytes())
    directory = tmp_path / f"{case_id}_{len(list(tmp_path.glob(case_id + '_*')))}"
    reference = trial_io_map.create_working_map(directory, base)
    working = trial_io_map.load_working_map(Path(reference["working_map_path"]))
    requests = [{"functional_name_hint": name, "role_text": name.lower()} for name in (names or case["names"])]
    proposals = [p for p in io_allocator.propose_assignment(working, requests) if not p.get("blocked")]
    trial_io_map.apply_proposals_to_working_map(Path(reference["working_map_path"]), proposals, "TEXT_EXPLICIT", "PREPARING")
    semantic = {"intent_id": case["intent"], "parameters": params}
    frozen = trial_io_map.freeze_working_map(reference, semantic, "PREPARING", f"{case_id}_TEST")
    return Path(frozen["snapshot_path"])


def _run(tmp_path, case_id, logic, params=None, names=None, initial=None, oracle=None):
    case = _CASES[case_id]
    params = params if params is not None else case["params"]
    snapshot = _snapshot(tmp_path, case_id, params, names)
    sim = _Sim(logic, initial)
    result = oracle_runner.run_oracle(oracle or _oracle(case_id), snapshot, dict(_RUN), "PLCSIM_ADVANCED",
                                      {"intent_id": case["intent"], "parameters": params}, _ROOT, bridge=sim, runtime_config=_CONFIG)
    return result, sim


# --- programas CORRECTOS segun la definicion de cada caso -----------------------------------

def _edge(io, st, name):
    rising = io.get(name, False) and not st.get("_prev_" + name, False)
    st["_prev_" + name] = io.get(name, False)
    return rising


def d01_ok(io, st, dt):  # pulso TP de 5 s al presionar
    if _edge(io, st, "I_Start"):
        st["left"] = 5000.0
    st["left"] = max(0.0, st.get("left", 0.0) - dt)
    io["Q_Aux_Output"] = st["left"] > 0 or (io.get("I_Start", False) and st.get("left", 0) > 0)


def d02_ok(io, st, dt):
    io["Q_Pilot_Run"] = io.get("I_Sensor1", False)


def latch(start, stop, out):
    def logic(io, st, dt):
        if io.get(stop, False):
            st["run"] = False
        elif io.get(start, False):
            st["run"] = True
        io[out] = st.get("run", False)
    return logic


def d05_ok(io, st, dt):
    if io.get("I_Emergency", False):
        st["run"] = False
    elif io.get("I_Start", False):
        st["run"] = True
    io["Q_Motor_Enable"] = st.get("run", False) and not io.get("I_Emergency", False)


def d06_ok(io, st, dt):
    if io.get("I_Reset", False):
        io["Q_Alarm"] = False
    if io.get("I_Start", False):
        if io.get("I_Sensor1", False):
            io["Q_Motor_Enable"], io["Q_Alarm"] = True, False
        else:
            io["Q_Alarm"] = True
    io.setdefault("Q_Motor_Enable", False)
    io.setdefault("Q_Alarm", False)


def ton(delay):
    def logic(io, st, dt):
        st["e"] = st.get("e", 0.0) + dt if io.get("I_Start", False) else 0.0
        io["Q_Motor_Enable"] = io.get("I_Start", False) and st["e"] >= delay
    return logic


def delayed_stop(delay):
    def logic(io, st, dt):
        if io.get("I_Start", False):
            st["run"], st["timing"] = True, None
        elif _edge(io, st, "I_Stop") and st.get("run"):
            st["timing"] = 0.0
        if st.get("timing") is not None:
            st["timing"] += dt
            if st["timing"] >= delay:
                st["run"], st["timing"] = False, None
        io["Q_Motor_Enable"] = st.get("run", False)
    return logic


def counter(preset, output="Q_Aux_Output", honour_reset=True):
    def logic(io, st, dt):
        if honour_reset and io.get("I_Reset", False):
            st["cv"] = 0
        if _edge(io, st, "I_Sensor1"):
            st["cv"] = st.get("cv", 0) + 1
        io[output] = st.get("cv", 0) >= preset
    return logic


def d11_ok(io, st, dt):
    if io.get("I_Emergency", False) or io.get("I_Stop", False):
        st["run"] = False
    elif io.get("I_Start", False):
        st["run"] = True
    io["Q_Contactor_A"] = st.get("run", False) and not io.get("I_Emergency", False)


def d12_ok(io, st, dt):
    io["Q_Contactor_A"] = io.get("I_Request_A", False) and not io.get("Q_Contactor_B", False)
    io["Q_Contactor_B"] = io.get("I_Request_B", False) and not io["Q_Contactor_A"]


def d13_ok(io, st, dt):
    io["Q_Motor_Enable"] = io.get("I_Start", False) and not io.get("I_Alarm", False)


def d14_ok(io, st, dt):
    high, med, low = (io.get(n, False) for n in ("I_Speed_High", "I_Speed_Medium", "I_Speed_Low"))
    io["Q_Speed_High"] = high
    io["Q_Speed_Medium"] = med and not high
    io["Q_Speed_Low"] = low and not med and not high


def d15_ok(io, st, dt):
    mode_ok = io.get("I_Mode_Manual", False) != io.get("I_Mode_Auto", False)
    if io.get("I_Stop", False):
        st["run"] = False
    elif io.get("I_Start", False) and mode_ok:
        st["run"] = True
    io["Q_Motor_Enable"] = st.get("run", False)


def d16_ok(io, st, dt):  # inicio -> espera 2 s -> salida auxiliar; reset reinicia
    if io.get("I_Reset", False):
        st["step"], st["t"] = 0, 0.0
    elif _edge(io, st, "I_Start") and st.get("step", 0) == 0:
        st["step"], st["t"] = 1, 0.0
    if st.get("step") == 1:
        st["t"] += dt
        if st["t"] >= 2000:
            st["step"] = 2
    io["Q_Aux_Output"] = st.get("step") == 2


def d17_ok(io, st, dt):
    if io.get("I_Sensor1", False) != st.get("last"):
        st["last"], st["e"] = io.get("I_Sensor1", False), 0.0
    else:
        st["e"] = st.get("e", 0.0) + dt
    io["Q_Alarm"] = st["e"] >= 5000


def d18_ok(io, st, dt):
    io["Q_Motor_Enable"] = io.get("I_Start", False) and not io.get("I_Maintenance", False)


def d19_ok(io, st, dt):
    if io.get("I_Stop", False):
        st["run"] = False
    elif io.get("I_Start", False):
        st["run"] = True
    fault = io.get("I_Fault", False)
    io["Q_Pilot_Run"] = st.get("run", False) and not fault
    io["Q_Pilot_Stop"] = not st.get("run", False) and not fault
    io["Q_Pilot_Fault"] = fault


def d20_ok(io, st, dt):
    if io.get("I_Emergency", False):
        st["phase"], io["Q_Alarm"] = 0, True
    elif io.get("I_Stop", False) or io.get("I_Reset", False):
        st["phase"] = 0
        if io.get("I_Reset", False):
            io["Q_Alarm"] = False
    elif io.get("I_Mode_Auto", False) and _edge(io, st, "I_Start") and st.get("phase", 0) == 0:
        st["phase"] = 1
    io["Q_Motor_Enable"] = st.get("phase", 0) == 1
    io["Q_Aux_Output"] = False
    io.setdefault("Q_Alarm", False)


_CORRECT: dict[str, Callable] = {
    "D01": d01_ok, "D02": d02_ok, "D03": latch("I_Start", "I_Stop", "Q_Motor_Enable"), "D04": latch("I_Start", "I_Stop", "Q_Motor_Enable"),
    "D05": d05_ok, "D06": d06_ok, "D07": ton(3000), "D08": delayed_stop(10000), "D09": counter(5), "D10": counter(5), "D11": d11_ok,
    "D12": d12_ok, "D13": d13_ok, "D14": d14_ok, "D15": d15_ok, "D16": d16_ok, "D17": d17_ok, "D18": d18_ok, "D19": d19_ok, "D20": d20_ok,
}


# --- Fase 3B-CLOSE: programas correctos segun las definiciones cerradas ------------------

def d05_close_ok(io, st, dt):  # SAFETY_TRIP => NOT MOTOR; START_REQUEST arranca
    if io.get("I_Safety_Trip", False):
        st["run"] = False
    elif io.get("I_Start", False):
        st["run"] = True
    io["Q_Motor_Enable"] = st.get("run", False) and not io.get("I_Safety_Trip", False)


def d06_close_ok(io, st, dt):  # alarma al intentar arrancar sin seguridad (se mantiene)
    if io.get("I_Start", False) and not io.get("I_Sensor1", False):
        st["alarm"] = True
    io["Q_Alarm"] = st.get("alarm", False)


def continuous_timeout(limit, rearm_on_level=False):  # paro tras `limit` ms de operacion continua
    def logic(io, st, dt):
        start = io.get("I_Start", False)
        rising = _edge(io, st, "I_Start")
        if rising or (rearm_on_level and start and not st.get("run")):
            st["run"], st["t"] = True, 0.0
        if not start:
            st["run"] = False
        if st.get("run"):
            st["t"] += dt
            if st["t"] >= limit:
                st["run"] = False
        io["Q_Motor_Enable"] = st.get("run", False)
    return logic


def d15_close_ok(io, st, dt):
    io["Q_Motor_Enable"] = io.get("I_Auto_Cmd", False) if io.get("I_Mode_Auto", False) else io.get("I_Manual_Cmd", False)


def d16_close_ok(io, st, dt):  # START -> principal; auxiliar tras 3 s
    st["t"] = st.get("t", 0.0) + dt if io.get("I_Start", False) else 0.0
    io["Q_Motor_Enable"] = io.get("I_Start", False)
    io["Q_Aux_Output"] = st["t"] >= 3000


def d19_close_ok(io, st, dt):  # FAULT > RUN > STOPPED
    fault, run = io.get("I_Fault", False), io.get("I_Run_State", False)
    io["Q_Pilot_Fault"] = fault
    io["Q_Pilot_Run"] = run and not fault
    io["Q_Pilot_Stop"] = not run and not fault


def d20_close_ok(io, st, dt):  # IDLE -> RUNNING (3 s) -> COMPLETE; RESET -> IDLE
    if io.get("I_Reset", False):
        st["state"] = "IDLE"
    elif _edge(io, st, "I_Start") and st.get("state", "IDLE") == "IDLE":
        st["state"], st["t"] = "RUNNING", 0.0
    if st.get("state") == "RUNNING":
        st["t"] += dt
        if st["t"] >= 3000:
            st["state"] = "COMPLETE"
    io["Q_Run"] = st.get("state") == "RUNNING"
    io["Q_Complete"] = st.get("state") == "COMPLETE"


_CORRECT.update({
    "D05": d05_close_ok, "D06": d06_close_ok, "D08": continuous_timeout(10000), "D15": d15_close_ok,
    "D16": d16_close_ok, "D19": d19_close_ok, "D20": d20_close_ok,
})


# --- Benchmark v2: 'al activar/recibir Start' = evento (pulso); D17 supervisa tras Start -------

def pulse_timeout(limit, level_only=False):
    """Motor arrancado por FLANCO de Start que se apaga tras `limit` ms de funcionamiento continuo.
    level_only=True: defecto (el motor solo marcha mientras Start esta pulsado)."""
    def logic(io, st, dt):
        start = io.get("I_Start", False)
        if _edge(io, st, "I_Start"):
            st["run"], st["t"] = True, 0.0
        if level_only and not start:
            st["run"] = False
        if st.get("run"):
            st["t"] += dt
            if st["t"] >= limit:
                st["run"] = False
        io["Q_Motor_Enable"] = st.get("run", False)
    return logic


def d16_v2_ok(io, st, dt):  # flanco de Start -> principal; auxiliar 3 s despues
    if _edge(io, st, "I_Start"):
        st["active"], st["t"] = True, 0.0
    if st.get("active"):
        st["t"] += dt
    io["Q_Motor_Enable"] = st.get("active", False)
    io["Q_Aux_Output"] = st.get("active", False) and st["t"] >= 3000


def d17_v2_ok(io, st, dt):  # supervision solo tras Start
    if io.get("I_Start", False):
        st["supervising"] = True
    if io.get("I_Sensor1", False) != st.get("last") or not st.get("supervising"):
        st["last"], st["e"] = io.get("I_Sensor1", False), 0.0
    else:
        st["e"] += dt
    io["Q_Alarm"] = st.get("supervising", False) and st["e"] >= 5000


_CORRECT.update({"D08": pulse_timeout(10000), "D16": d16_v2_ok, "D17": d17_v2_ok})


@pytest.mark.parametrize("case_id", sorted(_CORRECT))
def test_second_pass_correct_program_passes_every_executable_oracle(tmp_path, case_id):
    """El Oracle no exige de mas: un programa que cumple la definicion del caso obtiene PASS."""
    result, _ = _run(tmp_path, case_id, _CORRECT[case_id])
    assert result["verdict"] == "PASS", (result["verdict_reason"], result["errors"][:5],
                                        [c for c in result["functional"].get("failed_checks", [])][:3])
    assert result["functional"]["success"] is True and result["safety"]["success"] is True
    assert result["functional"]["total_checks"] > 0


def test_optional_roles_are_skipped_when_not_bound(tmp_path):
    """D09 sin RESET y D11 sin emergencia: los pasos opcionales se omiten y el correcto sigue pasando."""
    params = {k: v for k, v in _CASES["D09"]["params"].items() if k != "reset_input"}
    result, _ = _run(tmp_path, "D09", counter(5), params=params, names=["I_Sensor1", "Q_Aux_Output"])
    assert result["verdict"] == "PASS"
    assert {s["step_id"] for s in result["steps"] if s.get("skipped")} >= {"pre_reset_on", "pre_reset_off"}


# --- controles NEGATIVOS por familia funcional ----------------------------------------------

def _no_latch(io, st, dt):
    io["Q_Motor_Enable"] = io.get("I_Start", False) and not io.get("I_Stop", False)


def _d02_inverted(io, st, dt):
    io["Q_Pilot_Run"] = not io.get("I_Sensor1", False)


def _d12_no_interlock(io, st, dt):
    io["Q_Contactor_A"] = io.get("I_Request_A", False)
    io["Q_Contactor_B"] = io.get("I_Request_B", False)


def _d17_inverted(io, st, dt):
    d17_ok(io, st, dt)
    io["Q_Alarm"] = not io["Q_Alarm"]


def _d18_ignores_maintenance(io, st, dt):
    io["Q_Motor_Enable"] = io.get("I_Start", False)


def _d16_always_on(io, st, dt):
    io["Q_Aux_Output"] = True


def _d06_no_alarm(io, st, dt):
    d06_ok(io, st, dt)
    io["Q_Alarm"] = False


def _d05_ignores_emergency(io, st, dt):
    latch("I_Start", "I_Emergency_never", "Q_Motor_Enable")(io, st, dt)


def _d20_stop_ignored(io, st, dt):
    stop = io.pop("I_Stop", False)
    d20_ok(io, st, dt)
    io["I_Stop"] = stop


def _template_timed_pulse(io, st, dt):  # plantilla actual: TON, no TP (GAP-D01)
    st["e"] = st.get("e", 0.0) + dt if io.get("I_Start", False) else 0.0
    io["Q_Aux_Output"] = st["e"] >= 5000


def _d05_trip_ignored(io, st, dt):
    if io.get("I_Start", False):
        st["run"] = True
    io["Q_Motor_Enable"] = st.get("run", False)


def _d06_close_no_alarm(io, st, dt):
    io["Q_Alarm"] = False


def _d15_mode_ignored(io, st, dt):
    io["Q_Motor_Enable"] = io.get("I_Manual_Cmd", False) or io.get("I_Auto_Cmd", False)


def _d16_aux_immediate(io, st, dt):
    io["Q_Motor_Enable"] = io["Q_Aux_Output"] = io.get("I_Start", False)


def _d19_two_pilots(io, st, dt):  # la falla no apaga el piloto de marcha: dos pilotos activos
    fault, run = io.get("I_Fault", False), io.get("I_Run_State", False)
    io["Q_Pilot_Run"] = run
    io["Q_Pilot_Fault"] = fault
    io["Q_Pilot_Stop"] = not run and not fault


def _d19_run_over_fault(io, st, dt):
    fault, run = io.get("I_Fault", False), io.get("I_Run_State", False)
    io["Q_Pilot_Run"] = run
    io["Q_Pilot_Fault"] = fault and not run
    io["Q_Pilot_Stop"] = not run and not fault


def _d20_reset_ignored(io, st, dt):
    reset = io.pop("I_Reset", False)
    d20_close_ok(io, st, dt)
    io["I_Reset"] = reset


def _d13_alarm_ignored(io, st, dt):
    io["Q_Motor_Enable"] = io.get("I_Start", False)


def _d10_reset_output_only(io, st, dt):  # el reset apaga la salida pero no pone el conteo a cero
    if io.get("I_Reset", False):
        st["masked"] = True
    if _edge(io, st, "I_Sensor1"):
        st["cv"], st["masked"] = st.get("cv", 0) + 1, False
    io["Q_Aux_Output"] = st.get("cv", 0) >= 5 and not st.get("masked", False)


_NEGATIVES = [
    ("simple_output", "D02", _d02_inverted, "FAIL"),
    ("latch", "D04", _no_latch, "FAIL"),
    ("timer_wrong_duration", "D07", ton(1000), "FAIL"),
    ("timer_wrong_limit", "D08", pulse_timeout(5000), "FAIL"),
    ("timer_runs_only_while_start_held", "D08", pulse_timeout(10000, level_only=True), "FAIL"),
    ("supervision_without_start", "D17", d17_ok, "FAIL"),
    ("timer_ton_instead_of_pulse", "D01", _template_timed_pulse, "FAIL"),
    ("counter_wrong_preset", "D09", counter(3), "FAIL"),
    ("counter_reset_ignored", "D10", counter(5, honour_reset=False), "FAIL"),
    ("counter_reset_only_masks_output", "D10", _d10_reset_output_only, "FAIL"),
    ("interlock_absent", "D12", _d12_no_interlock, "FAIL"),
    ("alarm_inverted", "D17", _d17_inverted, "FAIL"),
    ("alarm_missing", "D06", _d06_close_no_alarm, "FAIL"),
    ("safety_trip_ignored", "D05", _d05_trip_ignored, "FAIL"),
    ("alarm_condition_ignored", "D13", _d13_alarm_ignored, "FAIL"),
    ("mode_ignored_maintenance", "D18", _d18_ignores_maintenance, "FAIL"),
    ("mode_ignored_manual_auto", "D15", _d15_mode_ignored, "FAIL"),
    ("sequence_aux_without_wait", "D16", _d16_aux_immediate, "FAIL"),
    ("two_pilots_at_once", "D19", _d19_two_pilots, "FAIL"),
    ("cycle_reset_ignored", "D20", _d20_reset_ignored, "FAIL"),
]


@pytest.mark.parametrize("family,case_id,logic,expected", _NEGATIVES, ids=[n[0] for n in _NEGATIVES])
def test_negative_control_per_family_is_rejected(tmp_path, family, case_id, logic, expected):
    result, _ = _run(tmp_path, case_id, logic)
    assert result["verdict"] == expected, (family, result["verdict"], result["verdict_reason"])
    assert result["verdict"] != "PASS"


def test_interlock_negative_is_a_safety_violation(tmp_path):
    result, _ = _run(tmp_path, "D12", _d12_no_interlock)
    assert result["safety"]["success"] is False and result["verdict_reason"] == "SAFETY_VIOLATION"
    assert result["safety"]["violations"][0]["step_id"] == "test_4"


def test_legacy_d12_template_roles_are_not_accepted_as_requests(tmp_path):
    """El Oracle v2 no se adapta a la plantilla: trigger_input/stop_input no son REQUEST_A/B (REVIEW, no PASS)."""
    params = {"trigger_input": "I_Start", "stop_input": "I_Stop", "contactor_a": "Q_Contactor_A", "contactor_b": "Q_Contactor_B"}
    result, sim = _run(tmp_path, "D12", d12_ok, params=params, names=["I_Start", "I_Stop", "Q_Contactor_A", "Q_Contactor_B"])
    assert result["verdict"] == "REVIEW" and result["verdict_reason"] == oracle_runner.ROLE_NOT_FOUND
    assert sim.calls == []


# =============================================================================================
# 3. PID: bloqueado en Runtime, evaluacion validada con trazas simuladas
# =============================================================================================

def test_pid_oracles_never_run_without_runtime_extension(tmp_path):
    def must_not_run(*args, **kwargs):
        raise AssertionError("el bridge no debe invocarse para un Oracle REQUIRES_RUNTIME_EXTENSION")
    for case_id in (f"P{i:02d}" for i in range(1, 13)):
        result = oracle_runner.run_oracle(_oracle(case_id), None, dict(_RUN), "PLCSIM_ADVANCED", None, _ROOT,
                                          bridge=must_not_run, runtime_config=_CONFIG)
        assert result["verdict"] == "REVIEW" and result["verdict_reason"] == oracle_runner.RUNTIME_EXTENSION_REQUIRED
        assert result["functional"]["success"] is None


def _pid_evaluate(case_id: str, logic, initial=None) -> tuple[str, dict, dict]:
    """Ejecuta la secuencia del Oracle PID en el simulador (sin gate de Runtime) y la evalua."""
    oracle = _oracle(case_id)
    roles = {}
    program = {"signals": {}}
    for role_name, role in oracle["roles"].items():
        name = role["process_variables"][0] if role.get("binding") == "PROCESS_VARIABLE" else {
            "emergency_input": "I_Emergency", "reset_input": "I_Reset", "pump_output": "Q_Pump_Enable",
            "alarm_output": "Q_Alarm", "safety_trip": "I_Safety_Trip", "manual_pump_command": "I_Manual_Pump",
            "auto_select": "I_Auto_Select"}[role["semantic_paths"][0]]
        roles[role_name] = {"role": role_name, "functional_name": name}
        program["signals"][name] = {"name": name, "address": "-", "area": "Input", "offset": 0, "bit": 0, "data_type": role.get("data_type", "BOOL")}
    plan = oracle_runner.compile_sequence(oracle, roles, program)
    raw = _Sim(logic, initial)("io_sequence", {"steps": plan["steps"]})
    evaluation = oracle_runner.evaluate_trace(oracle, roles, raw)
    verdict, _ = oracle_runner.decide_verdict(None, [], {"success": True}, evaluation["functional"], evaluation["safety"])
    return verdict, evaluation["functional"], evaluation["safety"]


def _pid_ok(high_limit=90.0, honour_auto=True, clamp=True, sensor_alarm=True, reset_needs_no_fault=True, pump_stops_on_overfill=True,
            safe_above=None, auto_needs_select=True):
    """Supervisor PID de referencia segun los Oracles cerrados (logica supervisora, no el PID)."""
    def logic(io, st, dt):
        pv = float(io.get("Level_PV", 50.0))
        trip = io.get("I_Emergency", False) or io.get("I_Safety_Trip", False)
        if "I_Auto_Select" in io:  # P01: el modo automatico sigue la seleccion
            io["Auto_Mode"] = io["I_Auto_Select"] if auto_needs_select else True
        io.setdefault("Auto_Mode", True)
        io["Sensor_Fault"] = pv < 0.0 or pv > 100.0
        io["High_Level_Alarm"] = pv > high_limit
        io["Low_Level_Alarm"] = pv < 10.0
        overfill = pv >= 95.0
        faults = io["High_Level_Alarm"] or io["Low_Level_Alarm"] or io["Sensor_Fault"] or overfill
        if io["High_Level_Alarm"] or io["Low_Level_Alarm"] or overfill or (sensor_alarm and io["Sensor_Fault"]):
            io["Q_Alarm"] = True
        if overfill:
            io["Safe_Stop"] = True
        io.setdefault("Safe_Stop", False)
        io.setdefault("Q_Alarm", False)
        if io.get("I_Reset", False) and (not faults or not reset_needs_no_fault):
            io["Q_Alarm"], io["Safe_Stop"] = False, False
        command = io.get("Level_SP_Command")
        if command is None:
            io["Level_SP"] = 60.0
        elif not clamp or 0.0 <= float(command) <= 100.0:
            io["Level_SP"] = float(command)
        auto_ok = io.get("Auto_Mode", False) if honour_auto else True
        safe = safe_above is not None and pv > safe_above  # P12: condicion segura por encima del umbral (sin memoria)
        io["PID_Enable"] = auto_ok and not trip and not io["Sensor_Fault"] and not io["Safe_Stop"] and not safe
        blocked = trip or io["Sensor_Fault"] or (io["Safe_Stop"] and pump_stops_on_overfill) or safe
        if "I_Manual_Pump" in io and not io.get("Auto_Mode", False):
            io["Q_Pump_Enable"] = io["I_Manual_Pump"] and not blocked
        else:
            io["Q_Pump_Enable"] = not blocked
    return logic


_PID_MODELS = {"P12": dict(safe_above=90.0)}


@pytest.mark.parametrize("case_id", ["P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10", "P11", "P12"])
def test_pid_positive_control_evaluates_as_pass(case_id):
    initial = {"Auto_Mode": case_id != "P06"}
    if case_id == "P01":
        initial["I_Auto_Select"] = False
    verdict, functional, safety = _pid_evaluate(case_id, _pid_ok(**_PID_MODELS.get(case_id, {})), initial=initial)
    assert verdict == "PASS", (functional.get("failed_checks"), safety.get("violations"))


def test_pid_negative_controls_are_rejected():
    verdict, functional, safety = _pid_evaluate("P03", _pid_ok(clamp=False))
    assert verdict == "FAIL" and safety["success"] is False  # setpoint de 150 % aceptado
    verdict, _, safety = _pid_evaluate("P06", _pid_ok(honour_auto=False), initial={"Auto_Mode": False})
    assert verdict == "FAIL" and any(v["invariant_id"] == "INV_PID_ONLY_AUTO" for v in safety["violations"])
    verdict, functional, _ = _pid_evaluate("P04", _pid_ok(high_limit=99.0))
    assert verdict == "FAIL" and functional["success"] is False  # alarma alta que no salta
    verdict, functional, _ = _pid_evaluate("P10", _pid_ok(reset_needs_no_fault=False))
    assert verdict == "FAIL" and functional["success"] is False  # reset borra la alarma con la falla presente
    verdict, _, safety = _pid_evaluate("P11", _pid_ok(pump_stops_on_overfill=False))
    assert verdict == "FAIL" and any(v["invariant_id"] == "INV_OVERFILL_PUMP" for v in safety["violations"])
    verdict, functional, _ = _pid_evaluate("P01", _pid_ok(auto_needs_select=False), initial={"I_Auto_Select": False})
    assert verdict == "FAIL" and functional["success"] is False  # automatico sin seleccion
    verdict, functional, _ = _pid_evaluate("P12", _pid_ok())  # sin condicion segura a > 90 %
    assert verdict == "FAIL" and functional["success"] is False


# =============================================================================================
# 4. Herramientas de revision
# =============================================================================================

def test_validation_report_has_one_entry_per_oracle(tmp_path):
    report = oracle_review.build_validation_report(_ROOT)
    assert [entry["case_id"] for entry in report["oracles"]] == _EXPECTED_IDS
    for entry in report["oracles"]:
        assert entry["schema_valid"] and entry["roles_valid"] and entry["sequence_valid"], entry
        assert entry["runtime_support"] in (oracle_schema.RUNTIME_EXECUTABLE_NOW, oracle_schema.RUNTIME_REQUIRES_EXTENSION)
        assert isinstance(entry["review_items"], list) and "warnings" in entry and entry["errors"] == []
    path = oracle_review.write_validation_report(_ROOT, report, tmp_path / "oracle_validation_report.json")
    assert len(json.loads(path.read_text(encoding="utf-8"))["oracles"]) == 32


def test_summary_markdown_has_32_sections():
    text = oracle_review.build_summary_markdown(_ROOT)
    assert len(re.findall(r"^## [DP]\d{2} ", text, flags=re.MULTILINE)) == 32
    for label in ("Objetivo", "Roles", "Prueba principal", "Condicion de exito", "Invariante critica", "Runtime", "Review items"):
        assert label in text


def test_mass_approval_skips_oracles_with_open_review_items(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(_ORACLES_DIR, root / "data" / "experiment_oracles")
    shutil.copytree(_ROOT / "data" / "experiment_cases", root / "data" / "experiment_cases")  # catalogo canonico (alineacion)
    with pytest.raises(ValueError):
        oracle_review.approve_all_without_review_items(root, "INV01", confirmation="ok")
    outcome = oracle_review.approve_all_without_review_items(root, "INV01", confirmation=oracle_review.MASS_APPROVAL_CONFIRMATION)
    approved = set(outcome["approved"])
    pending = {case_id for case_id in _EXPECTED_IDS
               if oracle_schema.open_review_items(oracle_schema.load_oracle(_ROOT, case_id))}
    assert approved and not (approved & pending)
    assert set(outcome["skipped_review_items"]) == pending
    for case_id in approved:
        oracle = oracle_schema.load_oracle(root, case_id)
        assert oracle["approval"]["status"] == "FROZEN" and oracle["approval"]["approved_by"] == "INV01"
        assert (root / "data" / "experiment_oracles" / "versions" / f"{case_id}_v{oracle['approval']['version']}.json").exists()
    for case_id in pending:
        assert not oracle_schema.is_formal(oracle_schema.load_oracle(root, case_id))
    assert "D03" not in approved  # ya estaba congelado


def test_repository_maps_and_oracles_unchanged_by_tests():
    for path in _REAL_MAPS:
        assert _hash(path) == _MAP_HASHES[str(path)]
    assert {str(p.relative_to(_ORACLES_DIR)): _hash(p) for p in _ORACLES_DIR.rglob("*.json")} == _ORACLE_HASHES


# Excepciones conocidas y documentadas del barrido de programas triviales.
_TRIVIAL_ACCEPTED = {
    ("D02", "mirror_I_Sensor1"),  # es exactamente el programa correcto ('piloto = sensor')
}


@pytest.mark.parametrize("case_id", sorted(_CORRECT))
def test_trivial_programs_do_not_pass(tmp_path, case_id):
    """Segunda pasada, pregunta 7: programas triviales (todo OFF/ON, salidas que copian o enclavan
    una entrada) no deben superar un Oracle ejecutable salvo excepciones documentadas."""
    outs = [n for n in _CASES[case_id]["names"] if n.startswith("Q_")]
    ins = [n for n in _CASES[case_id]["names"] if n.startswith("I_")]
    programs = {
        "all_off": lambda io, st, dt: [io.__setitem__(n, False) for n in outs],
        "all_on": lambda io, st, dt: [io.__setitem__(n, True) for n in outs],
    }
    for source in ins:
        programs[f"mirror_{source}"] = (lambda s: lambda io, st, dt: [io.__setitem__(n, bool(io.get(s, False))) for n in outs])(source)
        programs[f"latch_{source}"] = (lambda s: lambda io, st, dt: [io.__setitem__(n, bool(io.get(n, False)) or bool(io.get(s, False)))
                                                                     for n in outs])(source)
    passing = []
    for label, logic in programs.items():
        result, _ = _run(tmp_path, case_id, logic)
        if result["verdict"] == "PASS":
            passing.append((case_id, label))
    assert set(passing) <= _TRIVIAL_ACCEPTED, passing


def test_gui_oracle_review_window_lists_32_and_mass_approval_is_guarded(app, tmp_path, monkeypatch):
    """REVISION DE ORACLES sobre una COPIA: 32 filas; la aprobacion masiva solo congela los que no
    tienen review_items abiertos y registra al investigador como aprobador."""
    import gui
    root = tmp_path / "project"
    shutil.copytree(_ORACLES_DIR, root / "data" / "experiment_oracles")
    shutil.copytree(_ROOT / "data" / "experiment_cases", root / "data" / "experiment_cases")  # catalogo canonico (alineacion)
    monkeypatch.setattr(app, "project_root", root)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: "INV01")
    monkeypatch.setattr(app, "_refresh_oracle_status", lambda: None)
    window = gui.OracleReviewWindow(app)
    try:
        assert len(window.tree.get_children()) == 32
        assert window.tree.set("D03", "estado") == "FROZEN v1"
        window.approve_all_clean()
        with_items = {e["case_id"] for e in window.report["oracles"] if e["review_items"]}
        for case_id in window.tree.get_children():
            oracle = oracle_schema.load_oracle(root, case_id)
            if case_id in with_items:
                assert not oracle_schema.is_formal(oracle)
            else:
                assert oracle["approval"]["status"] == "FROZEN"
                assert case_id == "D03" or oracle["approval"]["approved_by"] == "INV01"
        assert (root / "docs" / "oracle_review_summary.md").exists()
    finally:
        window.destroy()
