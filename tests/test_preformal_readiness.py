"""
Cierre pre-FORMAL (benchmark v3): conflictos de requisitos, catalogo/prompt, P03 0-100, SAFETY_TRIP simulado,
mapa experimental de simulacion, alias de requisitos, capacidades PID/discretas, composicion, evaluation_report y
auditoria de preparacion 32/32. Sin LLM, sin TIA, sin PLCSIM: el SCL generado se ejecuta en el simulador de
verificacion (scl_sim) contra los Oracles congelados.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from composition_check import analyze_composition
from functional_requirements import (
    FUNCTIONAL_REQUIREMENT_CONFLICTS,
    canonical_requirement_type,
    canonicalize_functional_requirements,
    compute_semantic_coverage,
    detect_functional_requirement_conflicts,
)
from trial_experiments import benchmark_catalog as BC
from trial_experiments import deferred_evaluator as DE
from trial_experiments import experiment_maps as EM
from trial_experiments import oracle_runner, oracle_schema
from trial_experiments import preformal_readiness as PR
from trial_experiments import reference_pipeline as RP
from trial_experiments.scl_sim import SclMachine, SclSimError, SimulatedPlcBridge, parse_program
from utils import get_project_root, load_json_file

from test_phase4a_deferred_evaluation import _FakeBridge, _evaluate, _generated_trial, _master, _project  # noqa: E402

_ROOT = get_project_root()
_MAPS = _ROOT / "data" / "plc_maps"
_PHYSICAL = _MAPS / "mapa_banco_fisico_base.json"
_SIMULATION = _MAPS / "mapa_experimental_simulacion.json"
_PROTECTED = [_PHYSICAL, _MAPS / "mapa_simulacion_completo.json", _ROOT / "data" / "experiment_cases" / "canonical_cases.json",
              *sorted((_ROOT / "data" / "experiment_oracles").glob("*.json"))]
_HASHES = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in _PROTECTED}
_REFS = PR.load_reference_interpretations(_ROOT)
_CASES = {case["case_id"]: case for case in BC.load_catalog(_ROOT)["cases"]}


def _ref(case_id: str, **overrides: Any) -> dict[str, Any]:
    result = RP.run_reference(_ROOT, case_id, {**json.loads(json.dumps(_REFS[case_id])), **overrides},
                              _CASES[case_id]["canonical_command"])
    assert not result["errors"], result.get("traceback")
    return result


# =============================================================================================
# Simulador SCL de verificacion
# =============================================================================================

_TIMERS = """
FUNCTION_BLOCK "PLC_PRG"
VERSION : 0.1
VAR_INPUT
   I_In : Bool := FALSE;
END_VAR
VAR_OUTPUT
   Q_Pulse : Bool := FALSE;
   Q_Delay : Bool := FALSE;
   Q_Count : Bool := FALSE;
END_VAR
VAR
   T_P {InstructionName := 'TP_TIME'; LibVersion := '1.0'} : TP_TIME;
   T_D {InstructionName := 'TON_TIME'; LibVersion := '1.0'} : TON_TIME;
   C_N {InstructionName := 'CTU_INT'; LibVersion := '1.0'} : CTU_INT;
   R_E {InstructionName := 'R_TRIG'; LibVersion := '1.0'} : R_TRIG;
   Level : Real;
END_VAR
BEGIN
#T_P(IN := #I_In, PT := T#100ms);
#T_D(IN := #I_In, PT := T#50ms);
#R_E(CLK := #I_In);
#C_N(CU := #R_E.Q, R := FALSE, PV := 2);
#Q_Pulse := #T_P.Q;
#Q_Delay := #T_D.Q;
#Q_Count := #C_N.Q AND #Level >= 0.0;
END_FUNCTION_BLOCK
"""


def test_scl_simulator_iec_timer_counter_semantics():
    machine, io = SclMachine(_TIMERS), {}
    machine.initialize(io)
    io["I_In"] = True
    for _ in range(4):
        machine.scan(io, 10.0)
    assert io["Q_Pulse"] is True and io["Q_Delay"] is False  # TP en curso, TON aun sin cumplir 50 ms
    for _ in range(3):
        machine.scan(io, 10.0)
    assert io["Q_Delay"] is True
    for _ in range(5):
        machine.scan(io, 10.0)
    assert io["Q_Pulse"] is False  # el pulso TP dura exactamente PT aunque la entrada siga activa
    io["I_In"] = False
    machine.scan(io, 10.0)
    io["I_In"] = True
    machine.scan(io, 10.0)
    assert io["Q_Count"] is True  # dos flancos -> CTU alcanza PV=2
    assert io["DB_PLC_PRG.Level"] == 0.0  # estatica en el DB de instancia (accesible por el arnes)


def test_scl_simulator_rejects_constructs_outside_the_generated_subset():
    with pytest.raises(SclSimError):
        parse_program('FUNCTION_BLOCK "X"\nVAR_IN_OUT\n a : Bool;\nEND_VAR\nBEGIN\nEND_FUNCTION_BLOCK')
    with pytest.raises(SclSimError):
        SclMachine('FUNCTION_BLOCK "X"\nBEGIN\n#Ghost := TRUE;\nEND_FUNCTION_BLOCK').scan({}, 10.0)


_P06_DEV_004_SCL = """
FUNCTION_BLOCK "PLC_PRG"
VERSION : 0.1
VAR
   Auto_Mode : Bool;
   Manual_Mode : Bool;
   PID_Enable : Bool;
END_VAR
BEGIN
IF NOT FALSE THEN
    #Auto_Mode := TRUE;
    #Manual_Mode := FALSE;
END_IF;
IF NOT FALSE THEN
    #Auto_Mode := FALSE;
    #Manual_Mode := TRUE;
END_IF;
#PID_Enable := NOT FALSE AND #Auto_Mode;
END_FUNCTION_BLOCK
"""


def test_simulated_bridge_classifies_harness_overwrite_like_plcsim():
    """Mismo SCL que P06_V1_TEXT_DEV_004: el programa reescribe Auto_Mode -> PROGRAM_OVERWRITES_HARNESS_INPUT."""
    bridge = SimulatedPlcBridge(_P06_DEV_004_SCL)
    signal = {"kind": "PROCESS_VARIABLE", "name": "DB_PLC_PRG.Auto_Mode", "db": "DB_PLC_PRG", "member": "Auto_Mode",
              "data_type": "BOOL", "writable": True}
    raw = bridge("io_sequence", {"steps": [{"op": "set", "id": "s", "phase": "test", "writes": [{"signal": signal, "value": True}]}]})
    overwrite = raw["harness_input_overwrites"][0]
    assert overwrite["classification"] == "PROGRAM_OVERWRITES_HARNESS_INPUT" and overwrite["observed_after_cycle"] is False


# =============================================================================================
# Fase 1: conflictos internos de requisitos funcionales
# =============================================================================================

def test_declarative_conflict_table_detects_opposite_mode_orders():
    requirements = [{"type": "set_auto_mode"}, {"type": "enable_pid"}, {"type": "set_manual_mode"}, {"type": "disable_pid"}]
    conflicts = detect_functional_requirement_conflicts(requirements, {})
    assert [c["types"] for c in conflicts] == [["set_auto_mode", "set_manual_mode"]]
    assert conflicts[0]["type"] == "INCOMPATIBLE_REQUIREMENTS" and "Auto_Mode := TRUE" in conflicts[0]["reason"]
    # Con una entrada de seleccion del operador las dos ordenes forman un selector coherente.
    assert detect_functional_requirement_conflicts(requirements, {"auto_input": "I_Mode_Auto"}) == []
    # enable_pid + disable_pid componen (la deshabilitacion es la prioridad de seguridad), no es conflicto.
    assert detect_functional_requirement_conflicts([{"type": "enable_pid"}, {"type": "disable_pid"}], {}) == []
    assert all(set(rule["types"]) and rule["reason"] for rule in FUNCTIONAL_REQUIREMENT_CONFLICTS)


def test_p06_dev_004_interpretation_stops_at_semantics_before_ir():
    """La interpretacion real de P06_V1_TEXT_DEV_004 ya no llega a IR/SCL: conflicto estructurado + aclaracion."""
    interpretation = {**_REFS["P06"], "functional_requirements": [
        {"type": "set_auto_mode"}, {"type": "enable_pid"}, {"type": "set_manual_mode"}, {"type": "disable_pid"}]}
    result = RP.run_reference(_ROOT, "P06", interpretation, _CASES["P06"]["variants"]["V1"])
    assert result["stages"]["semantic"]["success"] is False and "generation" not in result["stages"]
    detail = result["stages"]["semantic"]["detail"]
    assert detail["conflicts"][0]["types"] == ["set_auto_mode", "set_manual_mode"] and detail["question"]
    assert result["semantic_output"]["requires_clarification"] is True


# =============================================================================================
# Fase 2: catalogo semantico / prompt / heuristicas (ACCION frente a CONDICION)
# =============================================================================================

_PROMPT = (_ROOT / "prompts" / "llm_semantic_parser_prompt.txt").read_text(encoding="utf-8")


def test_prompt_documents_action_vs_condition_without_benchmark_content():
    assert "ACCIÓN frente a CONDICIÓN" in _PROMPT
    for req_type in ("set_auto_mode", "set_manual_mode", "enable_pid", "reject_unsafe_setpoint", "enable_pump", "manual_pump_enable"):
        assert f"`{req_type}`" in _PROMPT, req_type
    assert "NO implica cambiar el modo de operación" in _PROMPT
    import re
    assert not re.search(r"\b[DP]\d{2}\b", _PROMPT)  # sin IDs de casos del benchmark
    texts = [text for case in _CASES.values() for text in [case["canonical_command"], *case["variants"].values()]]
    assert not any(text in _PROMPT for text in texts)  # ningun comando ni variante del benchmark


def test_intent_descriptions_sent_to_the_llm_carry_no_case_ids():
    import re
    from llm_context_builder import _summarize_intents
    summaries = _summarize_intents(load_json_file(_ROOT / "config" / "intents_catalog.json"))
    assert not any(re.search(r"\b[DP]\d{2}\b", entry["description"]) for entry in summaries)
    by_intent = {entry["intent_id"]: entry for entry in summaries}
    assert {"auto_input", "manual_pump_input"} <= set(by_intent["INT_PID_SUPERVISOR"]["expected_parameters"])
    assert {"request_a", "request_b"} <= set(by_intent["INT_MUTUAL_INTERLOCK"]["expected_parameters"])
    assert all(entry["expected_parameters"] for entry in summaries)  # todo intent comunica su interfaz


def test_keyword_heuristics_never_suggest_wrong_requirements_on_benchmark_texts():
    """La segunda pasada por cobertura no debe empujar al LLM hacia requisitos que el comando no pide."""
    catalog = load_json_file(_ROOT / "config" / "intents_catalog.json")
    hints = {}
    for case_id, case in _CASES.items():
        for label, text in [("C", case["canonical_command"]), *case["variants"].items()]:
            coverage = compute_semantic_coverage(text, _REFS[case_id]["intent_id"], _REFS[case_id]["functional_requirements"], catalog)
            if not coverage["complete"]:
                hints[(case_id, label)] = coverage["missing_types"]
    # Unica sugerencia: P12 V3 dice literalmente "deshabilita el PID" (disable_pid compone con la condicion segura).
    assert hints == {("P12", "V3"): ["disable_pid"]}


def test_mode_keywords_are_actions_not_conditions():
    catalog = load_json_file(_ROOT / "config" / "intents_catalog.json")
    condition = compute_semantic_coverage("El PID solo debe estar habilitado en modo Automático; en modo Manual, deshabilitado.",
                                          "INT_PID_SUPERVISOR", [{"type": "enable_pid"}], catalog)
    assert condition["complete"]
    action = compute_semantic_coverage("Pasa a modo automático el sistema.", "INT_PID_SUPERVISOR", [], catalog)
    assert "set_auto_mode" in action["missing_types"]


def test_rule_requirements_are_attached_by_type_domain_and_merges_are_revalidated():
    import llm_parser
    attached = llm_parser._attach_rule_based_functional_requirements(
        {"intent_id": "INT_MANUAL_AUTO_MODE", "functional_requirements": [], "normalized_command": "habilita el pid en modo manual"},
        "x", load_json_file(_ROOT / "config" / "intents_catalog.json"))
    assert not any(llm_parser._is_pid_requirement_type(r["type"]) for r in attached.get("functional_requirements") or [])
    merged = llm_parser._merge_functional_requirements([{"type": "enable_pid"}], [{"type": "run_pilot"}, {"type": "set_manual_mode"}],
                                                       "INT_PID_SUPERVISOR")
    assert [r["type"] for r in merged] == ["enable_pid", "set_manual_mode"]  # nunca un tipo discreto en un intent PID


def test_injected_response_never_triggers_a_networked_retry(monkeypatch):
    """Con respuesta inyectada (tests, auditoria) la cobertura incompleta no llama al LLM real."""
    import llm_parser
    from llm_parser import parse_with_mode

    monkeypatch.setattr(llm_parser, "compute_semantic_coverage", lambda **kwargs: {
        "detected_types": ["low_level_alarm"], "covered_by_intent": [], "explicit_types": [], "missing_types": ["low_level_alarm"],
        "complete": False})

    class _Forbidden:
        def is_configured(self):
            return True

        def interpret_command(self, *args, **kwargs):
            raise AssertionError("llamada al LLM real")

    response = {**_REFS["P04"], "functional_requirements": []}
    result = parse_with_mode("Activa la alarma de nivel alto si el nivel supera el 90 %.", mode="llm",
                             io_map=load_json_file(_PHYSICAL), llm_client=_Forbidden(), llm_response_text=response)
    assert "sin segunda pasada" in str(result.get("reason_for_retry"))


def test_reference_pipeline_forbids_llm_calls():
    with pytest.raises(RP.LLMCallForbidden):
        RP._NoLLMClient().interpret_command("x", {})


# =============================================================================================
# Fase 3: P03 0-100 % desde la configuracion
# =============================================================================================

def test_p03_setpoint_range_comes_from_config_and_matches_benchmark():
    config = load_json_file(_ROOT / "config" / "pid_supervisor_config.json")["level_setpoint"]
    assert (config["min"], config["max"]) == (0.0, 100.0)
    oracle = oracle_schema.load_oracle(_ROOT, "P03")
    invariant = next(i for i in oracle["invariants"] if i["type"] == "IN_RANGE")
    assert (invariant["min"], invariant["max"]) == (config["min"], config["max"])
    program = _ref("P03")["program_scl"]
    assert "IF #Level_SP_Command >= 0.0 AND #Level_SP_Command <= 100.0 THEN" in program


# =============================================================================================
# Fases 4-5: SAFETY_TRIP simulado y mapa experimental de simulacion
# =============================================================================================

def test_physical_map_has_no_emergency_and_simulation_map_declares_the_harness_signal():
    physical = load_json_file(_PHYSICAL)
    assert not any(v["name"] == "I_Emergency" for v in physical["variables"])
    simulation = load_json_file(_SIMULATION)
    metadata = simulation["metadata"]
    assert metadata["simulation_only"] is True and metadata["harness_signals"] == {"SAFETY_TRIP": "I_Emergency"}
    emergency = next(v for v in simulation["variables"] if v["name"] == "I_Emergency")
    assert emergency["state"] == "LOCKED" and "SIMULADO" in emergency["description"]


def test_simulation_map_has_unique_addresses_disjoint_from_the_bench():
    simulation = load_json_file(_SIMULATION)["variables"]
    locations = [v["location"] for v in simulation]
    names = [v["name"] for v in simulation]
    assert len(locations) == len(set(locations)) and len(names) == len(set(names))
    physical = {v["location"] for v in load_json_file(_PHYSICAL)["variables"]}
    assert not set(locations) & physical
    capabilities = EM.map_capabilities(load_json_file(_SIMULATION))
    assert capabilities["digital_inputs"] >= 16 and capabilities["digital_outputs"] >= 16


def test_map_selection_is_deterministic_and_capability_based():
    selections = {case_id: EM.select_experiment_map(_ROOT, oracle_schema.load_oracle(_ROOT, case_id)) for case_id in BC.CASE_IDS}
    simulated = sorted(case_id for case_id, selection in selections.items() if selection["simulation_only"])
    # Solo los casos cuyo Oracle exige la senal restringida SAFETY_TRIP salen del banco fisico.
    assert simulated == sorted(case_id for case_id in BC.CASE_IDS
                               if "SAFETY_TRIP" in EM.oracle_requirements(oracle_schema.load_oracle(_ROOT, case_id),
                                                                          EM.load_policy(_ROOT))["restricted_signals"])
    assert simulated == ["D05", "P07"]
    again = EM.select_experiment_map(_ROOT, oracle_schema.load_oracle(_ROOT, "D05"))
    assert again["map_hash"] == selections["D05"]["map_hash"] and again["map_id"] == "mapa_experimental_simulacion"
    d14 = selections["D14"]
    assert d14["map_id"] == "mapa_banco_fisico" and d14["requirements"] == {"digital_inputs": 3, "digital_outputs": 3,
                                                                              "restricted_signals": []}


def test_map_selection_fails_explicitly_when_no_map_covers_the_case():
    oracle = json.loads(json.dumps(oracle_schema.load_oracle(_ROOT, "D14")))
    for index in range(40):
        oracle["roles"][f"EXTRA_{index}"] = {"kind": "OUTPUT", "semantic_paths": [f"extra_{index}"]}
    selection = EM.select_experiment_map(_ROOT, oracle)
    assert selection["path"] is None and selection["error"] == EM.ERROR_NO_MAP and len(selection["rejected"]) == 2


def test_d05_reaches_ir_on_the_simulation_map_and_keeps_the_safety_invariant():
    result = _ref("D05")
    assert result["map"]["map_id"] == "mapa_experimental_simulacion" and result["map"]["simulation_only"] is True
    assert result["stages"]["generation"]["success"] and result["verdict"] == "PASS"
    assert result["safety_violations"] == []
    params = result["semantic_output"]["parameters"]
    assert params["emergency_input"] == "I_Emergency" and params["trigger_input"] == "I_Start"


def test_p07_resolves_safety_trip_role_on_simulation_map():
    result = _ref("P07")
    assert result["map"]["map_id"] == "mapa_experimental_simulacion"
    assert result["roles"] == "RESOLVED" and result["verdict"] == "PASS"
    assert result["semantic_output"]["parameters"]["emergency_input"] == "I_Emergency"


def test_no_ghost_emergency_on_the_physical_bench():
    """En el banco fisico una emergencia nunca se convierte en entrada: queda el literal seguro FALSE."""
    result = _ref("P06", parameters={"emergency_input": "I_Emergency"})
    assert result["map"]["map_id"] == "mapa_banco_fisico"
    assert result["semantic_output"]["parameters"]["emergency_input"] == "FALSE"
    assert "I_Emergency" not in result["program_scl"]


def test_gui_freezes_the_selected_experiment_map(app, monkeypatch):
    monkeypatch.setattr(app, "active_trial", {"case_id": "D05"})
    path, selection = app._experiment_base_map_source()
    assert Path(path).name == "mapa_experimental_simulacion.json" and selection["simulation_only"] is True
    evidence = EM.selection_evidence(selection)
    assert {"map_id", "map_hash", "source", "simulation_only"} <= set(evidence)
    monkeypatch.setattr(app, "active_trial", {"case_id": "D14"})
    path, selection = app._experiment_base_map_source()
    assert Path(path).name == "mapa_banco_fisico_base.json" and selection["simulation_only"] is False


# =============================================================================================
# Fase 6: alias / nombres canonicos
# =============================================================================================

def test_requirement_aliases_map_to_one_canonical_taxonomy():
    assert canonical_requirement_type("manual_pump_limit") == "manual_pump_enable"
    assert canonical_requirement_type("enable_pid_in_auto") == "enable_pid"
    canonical = canonicalize_functional_requirements([{"type": "manual_pump_limit"}, {"type": "enable_pid"}])
    assert canonical[0] == {"type": "manual_pump_enable", "type_alias": "manual_pump_limit"} and canonical[1]["type"] == "enable_pid"


def test_oracle_semantic_check_accepts_the_canonical_name_of_an_alias():
    oracle = oracle_schema.load_oracle(_ROOT, "P06")
    roles = {"roles": {role: {"matched_paths": []} for role in oracle["semantic_expectations"]["required_roles"]}}
    semantic = {"intent_id": "INT_PID_SUPERVISOR", "parameters": {}, "functional_requirements": [{"type": "enable_pid_in_auto"}]}
    result = oracle_runner.evaluate_semantics(oracle, semantic, roles)
    check = next(c for c in result["checks"] if c["check"] == "functional_requirement:enable_pid")
    assert check["passed"] is True


# =============================================================================================
# Fase 7: capacidades generales (PID + discretas) - SCL y comportamiento
# =============================================================================================

def test_p01_mode_follows_operator_selection_never_unconditional():
    program = _ref("P01")["program_scl"]
    assert "#Auto_Mode := #I_Mode_Auto AND NOT FALSE;" in program and "#Auto_Mode := TRUE" not in program


def test_p08_manual_pump_follows_only_the_manual_order():
    result = _ref("P08")
    assert "IF NOT #Auto_Mode THEN" in result["program_scl"] and "#I_Manual_Pump_Command" in result["program_scl"]
    assert result["verdict"] == "PASS"


def test_p10_alarm_reset_only_after_fault_clears():
    program = _ref("P10")["program_scl"]
    reset = next(line for line in program.splitlines() if line.startswith("IF #I_Reset"))
    assert reset.endswith("AND NOT #Sensor_Fault THEN")
    assert "    #Q_Alarm := TRUE;" in program  # la falla de sensor enclava la alarma


def test_p11_and_p12_safe_condition_lasts_only_while_the_condition_persists():
    p11 = _ref("P11")
    assert "IF #Level_PV >= 95.0 THEN" in p11["program_scl"] and "#Q_Pump_Enable := NOT FALSE AND NOT #Safe_Stop;" in p11["program_scl"]
    p12 = _ref("P12")
    assert "IF #Level_PV > 90.0 THEN" in p12["program_scl"] and "95.0" not in p12["program_scl"]
    assert p12["verdict"] == "PASS"  # recuperacion automatica sin Reset


@pytest.mark.parametrize("case_id", ["D12", "D13", "D14", "D15", "D16", "D17", "D19", "D20"])
def test_discrete_capabilities_match_the_frozen_definitions(case_id):
    result = _ref(case_id)
    assert result["verdict"] == "PASS", (result["verdict_reason"], result.get("functional_failed_checks"))


def test_timed_cases_hit_the_nominal_timing_window():
    for case_id in ("D07", "D16", "D17", "D20"):
        for check in _ref(case_id)["timing_checks"]:
            assert check["passed"] and abs(check["measured_ms"] - check["window_ms"]["nominal_ms"]) <= 100, (case_id, check)


def test_legacy_interlock_orders_are_aliases_of_the_requests():
    from ir_builder import get_required_variables_for_intent
    required = get_required_variables_for_intent("INT_MUTUAL_INTERLOCK", {"trigger_input": "I_Start", "stop_input": "I_Stop",
                                                                         "contactor_a": "Q_A", "contactor_b": "Q_B"})
    assert "I_Request_A" not in required and {"I_Start", "I_Stop"} <= set(required)


# =============================================================================================
# Fase 8: validacion de composicion
# =============================================================================================

def test_composition_rejects_contradictory_unconditional_writes():
    report = analyze_composition(_P06_DEV_004_SCL)
    assert report["valid"] is False
    assert {c["variable"] for c in report["conflicts"]} == {"Auto_Mode", "Manual_Mode"}
    assert [w["unconditional"] for w in report["writers"]["Auto_Mode"]] == [True, True]


def test_composition_accepts_unconditional_write_plus_conditional_priority_forcing():
    report = analyze_composition(_ref("P12")["program_scl"])
    assert report["valid"] is True
    pid_writers = report["writers"]["PID_Enable"]
    assert sum(w["unconditional"] for w in pid_writers) == 1 and any(not w["unconditional"] for w in pid_writers)


def test_reference_packages_record_a_clean_composition_report():
    result = _ref("P11")
    assert result["stages"]["generation"]["success"]
    assert all(analyze_composition(_ref(case_id)["program_scl"])["valid"] for case_id in ("D05", "P08", "P10"))


# =============================================================================================
# Fase 9: evaluation_report completo
# =============================================================================================

def test_evaluation_report_carries_compile_download_runtime_and_stage_summary(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    result = _evaluate(root, trial_dir, _FakeBridge())
    assert result["final_status"] == "PASS"
    report = json.loads((trial_dir / "evaluation" / "attempt_001" / "evaluation_report.json").read_text(encoding="utf-8"))
    record = json.loads((trial_dir / "trial.json").read_text(encoding="utf-8"))
    assert report["compile"]["success"] is True and report["compile"]["status"] == record["compile"]["status"]
    assert report["download"]["success"] is True and report["download"]["status"] == record["download"]["status"]
    assert report["runtime"] == record["runtime"] and report["runtime"]["cpu_state"] == "RUN"
    summary = report["stage_summary"]
    assert summary == {key: value for key, value in DE.trial_stage_summary(record).items() if key != "voice"}
    for key in ("semantic", "semantic_benchmark", "io_allocation", "ir", "compilation", "tia_archive", "download", "runtime",
                "functional", "safety", "final_verdict"):
        assert key in summary, key
    assert summary["compilation"] == "PASS" and summary["final_verdict"] == "PASS"


# =============================================================================================
# Fase 10: auditoria de preparacion
# =============================================================================================

def test_preformal_readiness_audit_32_of_32_evaluable():
    report = PR.run_audit(_ROOT)
    assert report["total"] == 32 and report["all_evaluable"], report["not_evaluable"]
    assert report["simulation_map_cases"] == ["D05", "P07"]
    for case in report["cases"]:
        assert set(case["checks"]) == set(PR.CHECK_KEYS)
    assert "32/32 EVALUABLE" in PR.render_markdown(report)


def test_audit_reports_a_missing_capability_as_not_evaluable():
    broken = {**_REFS["D14"], "intent_id": "INT_UNKNOWN"}
    case = PR.audit_case(_ROOT, "D14", broken)
    assert case["evaluable"] is False and "semantic_capability" in case["known_gaps"]


# =============================================================================================
# Invariantes de proteccion
# =============================================================================================

def test_benchmark_oracles_and_maps_untouched():
    for path in _PROTECTED:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == _HASHES[str(path)], path


# =============================================================================================
# Requisitos implicitos (D07 / D09 / D10): el parser nunca debe expresar recursos que el comando no pide
# =============================================================================================

def _run_params(case_id: str, parameters: dict[str, Any], intent_id: str | None = None) -> dict[str, Any]:
    interpretation = {**json.loads(json.dumps(_REFS[case_id])), "parameters": parameters}
    if intent_id:
        interpretation["intent_id"] = intent_id
    return RP.run_reference(_ROOT, case_id, interpretation, _CASES[case_id]["canonical_command"])


def test_a_d07_is_valid_without_stop_input():
    result = _run_params("D07", {"trigger_input": "I_Start", "motor_output": "Q_Motor_Enable", "delay_time": "T#3s"})
    assert result["stages"]["semantic"]["success"] and result["verdict"] == "PASS"
    assert "I_Stop" not in result["program_scl"]  # no se inventa ni se asigna ningun Stop


def test_b_d07_uses_an_explicit_stop():
    result = _run_params("D07", {"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable",
                                 "delay_time": "T#3s"})
    assert result["verdict"] == "PASS" and "AND NOT #I_Stop" in result["program_scl"]


def test_c_d09_is_valid_without_reset_input():
    result = _run_params("D09", {"pulse_input": "I_Sensor1", "output": "Q_Aux_Output", "preset": 5})
    assert result["stages"]["semantic"]["success"] and result["verdict"] == "PASS"
    assert "I_Reset" not in result["program_scl"]


def test_d_d10_still_requires_reset():
    # Por su funcion (rol RESET del Oracle): sin Reset el ensayo no puede pasar.
    without = _run_params("D10", {"pulse_input": "I_Sensor1", "output": "Q_Aux_Output", "preset": 5})
    assert without["verdict"] == "REVIEW" and without["verdict_reason"] == "ORACLE_ROLE_NOT_FOUND"
    # Por contrato: el intent cuya funcion es el reinicio lo exige al parser.
    counter_reset = _run_params("D10", {"pulse_input": "I_Sensor1", "output": "Q_Aux_Output"}, intent_id="INT_COUNTER_RESET")
    assert "Faltan parametros requeridos: reset_input" in counter_reset["stages"]["semantic"]["detail"]["errors"]
    assert _run_params("D10", _REFS["D10"]["parameters"])["verdict"] == "PASS"


def test_e_no_hidden_requirement_in_any_case():
    """Sin recursos que ningun rol del Oracle usa y sin nombres tecnicos internos, los 32 casos siguen validos y PASS."""
    for case_id in BC.CASE_IDS:
        oracle = oracle_schema.load_oracle(_ROOT, case_id)
        paths = {path for role in oracle["roles"].values() for path in role.get("semantic_paths") or []}
        minimal = {key: value for key, value in _REFS[case_id]["parameters"].items()
                   if not (isinstance(value, str) and value[:2] in ("M_", "T_", "C_", "R_"))
                   and not (isinstance(value, str) and value[:2] in ("I_", "Q_") and key not in paths)}
        result = _run_params(case_id, minimal)
        assert result["verdict"] == "PASS", (case_id, result["stages"].get("semantic"), result.get("verdict_reason"))


def test_f_readiness_still_32_of_32_with_minimal_interpretations():
    assert all(not any(isinstance(v, str) and v[:2] in ("T_", "C_") for v in ref["parameters"].values()) for ref in _REFS.values())
    assert "stop_input" not in _REFS["D07"]["parameters"] and "reset_input" not in _REFS["D09"]["parameters"]
    assert PR.run_audit(_ROOT, ["D01", "D07", "D09", "D10"])["all_evaluable"]


def test_32_oracles_frozen_with_technical_validation_and_human_approval():
    for case_id in BC.CASE_IDS:
        oracle = oracle_schema.load_oracle(_ROOT, case_id)
        approval = oracle["approval"]
        assert approval["status"] == "FROZEN" and approval["approved_by"] == "Henry Ochoa", case_id
        assert approval["technical_validation"]["status"] == "PASSED" and approval["human_formal_approval"] == "APPROVED", case_id
        assert approval["approved_at"] > approval["technical_validation"]["validated_at"], case_id
        assert approval["hash"] == oracle_schema.compute_oracle_hash(oracle) == approval["technical_validation"]["content_hash"]
        archived = json.loads((_ROOT / "data" / "experiment_oracles" / "versions" / f"{case_id}_v{approval['version']}.json")
                              .read_text(encoding="utf-8"))
        assert archived["approval"] == approval  # la copia inmutable lleva el mismo bloque de aprobacion


def test_human_approval_marker_never_signs_an_unapproved_oracle(tmp_path):
    import shutil
    shutil.copytree(_ROOT / "data" / "experiment_oracles", tmp_path / "data" / "experiment_oracles")
    path = tmp_path / "data" / "experiment_oracles" / "D01.json"
    oracle = json.loads(path.read_text(encoding="utf-8"))
    oracle["approval"].update({"status": "DRAFT_REVIEWED", "approved_by": None, "approved_at": None, "hash": None,
                               "human_formal_approval": "PENDING"})
    path.write_text(json.dumps(oracle), encoding="utf-8")
    with pytest.raises(oracle_schema.OracleError):
        oracle_schema.record_human_approval_marker(tmp_path, "D01")
