"""
Fase 3B-CLOSE: cierre de los 15 review_items con las decisiones del investigador.

Pruebas especificas de cada decision (D05, D06, D08, D10, D13, D14, D15, D16, D19, D20, P03, P07,
P08, P10, P11) mas los totales del benchmark (32 validos, 0 review_items, hashes). Reutiliza el PLC
simulado de test_phase3b_oracles: nada toca PLCSIM real ni los Oracles/mapas del repositorio.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trial_experiments import oracle_review, oracle_schema  # noqa: E402
from utils import get_project_root  # noqa: E402

import test_phase3b_oracles as T  # noqa: E402

_ROOT = get_project_root()
_ORACLES_DIR = _ROOT / "data" / "experiment_oracles"
_MAPS = [_ROOT / "data" / "plc_maps" / f"{n}.json" for n in
         ("mapa_banco_fisico", "mapa_simulacion_completo", "mapa_pid_simulacion", "mapa_pid_banco_fisico")]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_MAP_HASHES = {str(p): _hash(p) for p in _MAPS}
_ORACLE_HASHES = {str(p.relative_to(_ORACLES_DIR)): _hash(p) for p in _ORACLES_DIR.rglob("*.json")}


def _oracle(case_id):
    return oracle_schema.load_oracle(_ROOT, case_id)


def _conventions(case_id):
    return {item["id"]: item["text"] for item in _oracle(case_id).get("experimental_conventions") or []}


def _resolved(case_id):
    return {item["id"]: item for item in _oracle(case_id)["review_items"]}


# =============================================================================================
# Totales
# =============================================================================================

def test_32_schema_valid_and_zero_open_review_items():
    report = oracle_review.build_validation_report(_ROOT)
    summary = report["summary"]
    assert summary["total_oracles"] == 32 and summary["schema_valid"] == 32
    assert summary["open_review_items"] == 0 and summary["with_review_items"] == 0
    assert summary["discrete_executable"] == "20/20" and summary["pid_executable"] == "0/12"
    for entry in report["oracles"]:
        assert entry["errors"] == [], entry["case_id"]
        assert all(item["status"] == "RESOLVED" and item.get("resolution") for item in _oracle(entry["case_id"])["review_items"])


def test_hashes_valid_d03_untouched_and_no_ai_approval():
    d03 = _oracle("D03")
    assert d03["approval"]["status"] == "FROZEN" and d03["approval"]["approved_by"] == "Henry"
    assert d03["approval"]["hash"] == oracle_schema.compute_oracle_hash(d03) == \
        "b444a550d900d61ca67053bfa17cdec706e2149d9d78c0a3790ecf131aa1dc92"
    pending = set()
    for case_id in oracle_review.EXPECTED_ORACLE_IDS:
        oracle = _oracle(case_id)
        approval = oracle["approval"]
        if case_id == "D03":
            continue
        assert approval["ai_review"]["semantic_reviewed"] is True  # la revision asistida queda registrada
        if oracle_schema.is_formal(oracle):
            # Aprobacion formal: siempre humana (nunca una IA) y con hash integro.
            assert approval["approved_by"] and not any(n in approval["approved_by"].lower() for n in ("claude", "chatgpt", "ia"))
            assert approval["hash"] == oracle_schema.compute_oracle_hash(oracle)
        else:
            assert approval["status"] == "DRAFT_REVIEWED" and approval["approved_by"] is None
            pending.add(case_id)
    assert set(oracle_review.build_validation_report(_ROOT)["summary"]["ready_for_human_approval"]) == pending


def test_every_closed_case_separates_original_requirement_from_conventions():
    for case_id in ("D05", "D06", "D08", "D10", "D13", "D14", "D15", "D16", "D19", "D20", "P03", "P07", "P08", "P10", "P11"):
        conventions = _conventions(case_id)
        assert conventions["REQ-ORIGINAL"].startswith("REQUISITO ORIGINAL:"), case_id
        assert len(conventions) >= 2, case_id


# =============================================================================================
# Decisiones por caso (estructura del Oracle + comportamiento en el PLC simulado)
# =============================================================================================

def test_d05_safety_trip_overrides_start(tmp_path):
    oracle = _oracle("D05")
    assert set(oracle["roles"]) == {"START_REQUEST", "SAFETY_TRIP", "MOTOR_MAIN"}
    assert "E-stop" in _conventions("D05")["C-D05-TRIP"] and "I_Emergency" in _conventions("D05")["C-D05-TRIP"]
    invariant = oracle["invariants"][0]
    assert invariant["type"] == "NEVER_TRUE_TOGETHER" and invariant["roles"] == ["SAFETY_TRIP", "MOTOR_MAIN"]
    assert invariant["severity"] == "CRITICAL"
    ok, _ = T._run(tmp_path, "D05", T.d05_close_ok)
    assert ok["verdict"] == "PASS"
    ignored, _ = T._run(tmp_path, "D05", T._d05_trip_ignored)
    assert ignored["verdict"] == "FAIL" and ignored["safety"]["success"] is False


def test_d06_only_alarm_activation_no_reset_required(tmp_path):
    oracle = _oracle("D06")
    assert set(oracle["roles"]) == {"START_REQUEST", "SAFETY_OK", "ALARM"}
    assert "RESET" not in json.dumps(oracle["roles"]) and "borrado de alarma" in _resolved("D06")["D06-R1"]["resolution"]
    ok, _ = T._run(tmp_path, "D06", T.d06_close_ok)  # alarma que NUNCA se borra: valido para D06
    assert ok["verdict"] == "PASS"
    missing, _ = T._run(tmp_path, "D06", T._d06_close_no_alarm)
    assert missing["verdict"] == "FAIL"


def test_d08_is_continuous_operation_timeout(tmp_path):
    oracle = _oracle("D08")
    assert set(oracle["roles"]) == {"START", "MOTOR_MAIN"}
    assert oracle["source_definition"]["canonical_command"].startswith("Al activar Start, enciende el motor")
    assert "official_definition" not in oracle["source_definition"]
    assert oracle["semantic_expectations"]["accepted_intents"] == ["INT_AUTO_STOP_TIMER"]
    assert "INT_DELAYED_STOP" in oracle["semantic_expectations"]["forbidden_intents"]
    transition = oracle["test_sequence"][1]["measure_transition"]
    assert transition["nominal_ms"] == 10000 and transition["tolerance_ms"] == {"early": 500, "late": 1000}
    assert "no metrologica" in _conventions("D08")["C-D08-TOLERANCE"]
    ok, _ = T._run(tmp_path, "D08", T.pulse_timeout(10000))
    assert ok["verdict"] == "PASS"
    measured = next(c for s in ok["steps"] for c in s["checks"] if c["type"] == "transition")["actual_observation_time"]
    assert 9500 <= measured <= 11000
    held_only, _ = T._run(tmp_path, "D08", T.pulse_timeout(10000, level_only=True))
    assert held_only["verdict"] == "FAIL"
    assert oracle["system_capability_gaps"] == []


def test_d10_counts_before_reset(tmp_path):
    oracle = _oracle("D10")
    ids = [s["id"] for s in oracle["test_sequence"]]
    assert ids.index("a5_on") < ids.index("reset_on")
    a5 = next(s for s in oracle["test_sequence"] if s["id"] == "a5_off")
    assert a5["expect"] == {"COUNT_OUTPUT": True}
    assert "extension del contador de D09" in _resolved("D10")["D10-R1"]["resolution"]
    ok, _ = T._run(tmp_path, "D10", T.counter(5))
    assert ok["verdict"] == "PASS"
    masked, _ = T._run(tmp_path, "D10", T._d10_reset_output_only)
    assert masked["verdict"] == "FAIL"
    never_counts, _ = T._run(tmp_path, "D10", lambda io, st, dt: io.__setitem__("Q_Aux_Output", False))
    assert never_counts["verdict"] == "FAIL"  # sin estado contado previo, el reset no se da por bueno


def test_d13_alarm_is_an_input_condition(tmp_path):
    oracle = _oracle("D13")
    assert oracle["roles"]["ALARM_ACTIVE"]["kind"] == "INPUT"
    assert "alarm_output" not in oracle["roles"]["ALARM_ACTIVE"]["semantic_paths"]
    assert oracle["invariants"][0]["roles"] == ["ALARM_ACTIVE", "VFD_ENABLE"]
    ok, _ = T._run(tmp_path, "D13", T.d13_ok)
    assert ok["verdict"] == "PASS"
    ignored, _ = T._run(tmp_path, "D13", T._d13_alarm_ignored)
    assert ignored["verdict"] == "FAIL" and ignored["safety"]["success"] is False


def test_d14_one_hot(tmp_path):
    oracle = _oracle("D14")
    assert oracle["invariants"][0]["type"] == "AT_MOST_ONE"
    assert oracle["invariants"][0]["roles"] == ["SPEED_LOW", "SPEED_MEDIUM", "SPEED_HIGH"]
    ok, _ = T._run(tmp_path, "D14", T.d14_ok)
    assert ok["verdict"] == "PASS"

    def two_speeds(io, st, dt):
        io["Q_Speed_Low"] = io.get("I_Speed_Low", False)
        io["Q_Speed_Medium"] = io.get("I_Speed_Medium", False)
        io["Q_Speed_High"] = io.get("I_Speed_High", False)
    result, _ = T._run(tmp_path, "D14", two_speeds)  # dos comandos -> dos salidas: viola one-hot
    assert result["verdict"] == "FAIL" and result["functional"]["major_invariant_violations"] > 0


def test_d15_distinguishes_manual_auto_and_trivial_copy_fails(tmp_path):
    oracle = _oracle("D15")
    assert set(oracle["roles"]) == {"MODE_AUTO", "MANUAL_COMMAND", "AUTO_COMMAND", "MOTOR_MAIN"}
    ok, _ = T._run(tmp_path, "D15", T.d15_close_ok)
    assert ok["verdict"] == "PASS"
    for source in ("I_Manual_Cmd", "I_Auto_Cmd"):
        copy, _ = T._run(tmp_path, "D15", lambda io, st, dt, s=source: io.__setitem__("Q_Motor_Enable", io.get(s, False)))
        assert copy["verdict"] == "FAIL", source
    ignored, _ = T._run(tmp_path, "D15", T._d15_mode_ignored)
    assert ignored["verdict"] == "FAIL"


def test_d16_waits_3_seconds(tmp_path):
    step = _oracle("D16")["test_sequence"][1]
    assert step["measure_transition"]["role"] == "AUX_OUTPUT" and step["measure_transition"]["nominal_ms"] == 3000
    assert "CONVENCION" in _conventions("D16")["C-D16-WAIT"]
    ok, _ = T._run(tmp_path, "D16", T.d16_v2_ok)
    assert ok["verdict"] == "PASS"
    immediate, _ = T._run(tmp_path, "D16", T._d16_aux_immediate)
    assert immediate["verdict"] == "FAIL"


def test_d19_exactly_one_pilot(tmp_path):
    oracle = _oracle("D19")
    assert oracle["invariants"][0]["type"] == "EXACTLY_ONE"
    t3 = next(s for s in oracle["test_sequence"] if s["id"] == "t3_fault_running")
    assert "expect" not in t3  # benchmark v2: marcha+falla simultaneas no definen el estado actual (solo la invariante)
    ok, _ = T._run(tmp_path, "D19", T.d19_close_ok)
    assert ok["verdict"] == "PASS"
    wrong, _ = T._run(tmp_path, "D19", T._d19_two_pilots)
    assert wrong["verdict"] == "FAIL"


def test_d20_minimal_cycle_and_reset(tmp_path):
    oracle = _oracle("D20")
    assert set(oracle["roles"]) == {"START", "RESET", "RUN_OUTPUT", "COMPLETE_STATE"}
    assert "ALARM" not in oracle["roles"] and "3 s" in _conventions("D20")["C-D20-DURATION"]
    ok, _ = T._run(tmp_path, "D20", T.d20_close_ok)
    assert ok["verdict"] == "PASS"
    no_reset, _ = T._run(tmp_path, "D20", T._d20_reset_ignored)
    assert no_reset["verdict"] == "FAIL"


def test_p03_rejects_150_and_keeps_60():
    oracle = _oracle("P03")
    assert oracle["preconditions"][0]["set"] == {"LEVEL_SP_COMMAND": 60.0}
    assert oracle["test_sequence"][0]["set"] == {"LEVEL_SP_COMMAND": 150.0}
    assert oracle["test_sequence"][0]["expect"]["LEVEL_SP"]["approx"] == 60.0
    assert oracle["runtime_support"] == "REQUIRES_RUNTIME_EXTENSION"
    assert T._pid_evaluate("P03", T._pid_ok())[0] == "PASS"
    verdict, _, safety = T._pid_evaluate("P03", T._pid_ok(clamp=False))
    assert verdict == "FAIL" and safety["success"] is False


def test_p07_safety_trip_disables_pid():
    oracle = _oracle("P07")
    assert oracle["preconditions"][0]["expect"] == {"PID_ENABLE": True}
    assert oracle["invariants"][0]["roles"] == ["SAFETY_TRIP", "PID_ENABLE"]
    assert T._pid_evaluate("P07", T._pid_ok())[0] == "PASS"
    verdict, _, safety = T._pid_evaluate("P07", lambda io, st, dt: io.__setitem__("PID_Enable", io.get("Auto_Mode", False)))
    assert verdict == "FAIL" and safety["success"] is False


def test_p08_manual_pump_command():
    oracle = _oracle("P08")
    assert set(oracle["roles"]) == {"AUTO_MODE", "MANUAL_PUMP_COMMAND", "PUMP_ENABLE"}
    assert "ON/OFF" in _conventions("P08")["C-P08"]
    assert T._pid_evaluate("P08", T._pid_ok(), initial={"Auto_Mode": False, "I_Manual_Pump": False})[0] == "PASS"
    verdict, functional, _ = T._pid_evaluate("P08", lambda io, st, dt: io.__setitem__("Q_Pump_Enable", False))
    assert verdict == "FAIL" and functional["success"] is False


def test_p10_reset_blocked_while_fault_present():
    oracle = _oracle("P10")
    assert oracle["preconditions"][0]["set"]["LEVEL_PV"] == 150.0
    assert oracle["preconditions"][0]["expect"] == {"SENSOR_FAULT": True, "ALARM": True}
    assert T._pid_evaluate("P10", T._pid_ok())[0] == "PASS"
    verdict, functional, _ = T._pid_evaluate("P10", T._pid_ok(reset_needs_no_fault=False))
    assert verdict == "FAIL" and functional["success"] is False


def test_p11_overfill_stop():
    oracle = _oracle("P11")
    assert "HIGH_LEVEL_TRIP" not in oracle["roles"]
    invariant = oracle["invariants"][0]
    assert invariant["type"] == "FORBIDDEN_WHEN" and invariant["when"] == {"role": "LEVEL_PV", "min": 95.0}
    assert oracle["preconditions"][0]["expect"] == {"PUMP_ENABLE": True}
    assert T._pid_evaluate("P11", T._pid_ok())[0] == "PASS"
    verdict, _, safety = T._pid_evaluate("P11", T._pid_ok(pump_stops_on_overfill=False))
    assert verdict == "FAIL" and safety["violations"][0]["invariant_id"] == "INV_OVERFILL_PUMP"


def test_capability_gaps_report_is_structured():
    report = oracle_review.build_capability_gaps_report(_ROOT)
    cases = {gap["case_id"] for gap in report["generator_gaps"]}
    assert {"D01", "D05", "D10", "D12", "D13", "D14", "D16", "D19", "D20"} <= cases
    for gap in report["generator_gaps"]:
        assert gap["expected_capability"] and gap["current_behavior"] and gap["recommended_future_fix"]
        assert gap["severity"] in ("HIGH", "MEDIUM", "LOW")
    assert {g["case_id"] for g in report["runtime_gaps"]} == {f"P{i:02d}" for i in range(1, 13)}


def test_maps_and_oracles_unchanged():
    for path in _MAPS:
        assert _hash(path) == _MAP_HASHES[str(path)]
    assert {str(p.relative_to(_ORACLES_DIR)): _hash(p) for p in _ORACLES_DIR.rglob("*.json")} == _ORACLE_HASHES
