"""
Semantica efectiva + separacion Semantic Pipeline / Semantic Benchmark / Functional.

Caso DEVELOPMENT D03_V2_TEXT_DEV_006: el LLM devolvio INT_MOTOR_LATCH sin trigger/stop/motor; el IR y el
generador rellenaron en silencio I_Start/I_Stop/Q_Motor_Enable, el snapshot quedo sin parameter_bindings
y el Oracle no pudo resolver START/STOP/MOTOR_MAIN (REVIEW sin ejecutar el Runtime), aunque el programa
implementaba D03 correctamente. Aqui se verifica, con el banco real (copia) y el mismo IOAllocator, que:
  * los recursos efectivos quedan explicitos y trazados ANTES del snapshot/IR/SCL;
  * el Oracle resuelve los roles y mide Functional/Safety aunque el intent no coincida;
  * el mismatch de intent queda registrado como discrepancia semantica, sin contaminar Functional.
Nada toca PLCSIM real, los Oracles ni el benchmark (hashes al final).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import code_generator
import effective_semantics as ES
import io_allocator
import llm_parser
from code_generator import FunctionalResourceUnresolvedError, generate_implementation_from_ir
from ir_builder import INTENT_RESOURCE_TABLE, OPTIONAL_PARAMETER_KEYS, build_project_ir
from platforms.siemens_scl_adapter import SiemensSCLAdapter
from semantic_validator import INTENT_PARAMETER_RULES
from trial_experiments import batch_runner as B
from trial_experiments import deferred_evaluator as DE
from trial_experiments import oracle_runner, oracle_schema, text_batch as TB, trial_io_map
from utils import get_project_root

from test_execute_full_pipeline import _base_semantic_output  # noqa: E402
from test_phase3b_oracles import _CONFIG, _RUN, _Sim, latch  # noqa: E402

_ROOT = get_project_root()
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)
_FROZEN = ("data/experiment_cases/canonical_cases.json", "data/experimental_design.json",
           "data/plc_maps/mapa_banco_fisico_base.json", "data/plc_maps/profiles.json", "data/plc_maps/experiment_variants.json")
_FROZEN_BEFORE = {name: B.file_hash(_ROOT / name) for name in _FROZEN}
_BASE_MAP = _ROOT / "data" / "plc_maps" / "mapa_banco_fisico_base.json"
_EXTERNAL = ("I_", "Q_", "AI_", "AO_")


def _catalog() -> tuple[dict[str, Any], dict[str, Any]]:
    return llm_parser._load_intents_catalog(), llm_parser._load_safety_rules()


def _llm_latch_without_parameters() -> dict[str, Any]:
    """Lo que devolvio el LLM en D03_V2_TEXT_DEV_006: intent LATCH, sin recursos."""
    payload = _base_semantic_output("INT_MOTOR_LATCH", {}, [])
    payload["command_text"] = "Quiero encender el motor con Start y que siga encendido aunque suelte el boton; con Stop se apaga."
    return payload


def _working_map(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    reference = trial_io_map.create_working_map(tmp_path / "trial", _BASE_MAP)
    return reference, Path(reference["working_map_path"])


def _experiment_pipeline(tmp_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Mismo orden que la GUI en Experimentacion: parser/repair/semantica efectiva -> IOAllocator
    (working map) -> revalidacion -> snapshot congelado -> IR -> SCL Siemens."""
    intents, safety = _catalog()
    reference, working_path = _working_map(tmp_path)
    working = trial_io_map.load_working_map(working_path)
    effective, validation = llm_parser._repair_and_validate(payload, working, intents, safety, ES.SOURCE_LLM)
    proposals = [p for p in validation.get("io_assignment_proposals") or [] if not p.get("blocked")]
    if proposals:
        trial_io_map.apply_proposals_to_working_map(working_path, proposals, "TEXT_EXPLICIT", trial_io_map.STATE_PREPARING)
    working = trial_io_map.load_working_map(working_path)
    effective["semantic_validation"] = llm_parser.validate_semantic_output(effective, working, intents, safety)
    frozen = trial_io_map.freeze_working_map(reference, effective, trial_io_map.STATE_PREPARING, "D03_V2_TEXT_DEV_TEST")
    snapshot = json.loads(Path(frozen["snapshot_path"]).read_text(encoding="utf-8"))
    project_ir = build_project_ir(effective, working, "SIEMENS_SCL")
    return {"semantic": effective, "validation": validation, "revalidation": effective["semantic_validation"],
            "proposals": proposals, "snapshot": snapshot, "snapshot_path": Path(frozen["snapshot_path"]),
            "ir": project_ir, "scl": SiemensSCLAdapter().render_full_program(project_ir), "working": working}


@pytest.fixture
def d03(tmp_path):
    return _experiment_pipeline(tmp_path, _llm_latch_without_parameters())


def _oracle(case_id: str) -> dict[str, Any]:
    return oracle_schema.load_oracle(_ROOT, case_id)


def _run_oracle(case: dict[str, Any], logic, oracle_id: str = "D03") -> tuple[dict[str, Any], _Sim]:
    sim = _Sim(logic)
    result = oracle_runner.run_oracle(_oracle(oracle_id), case["snapshot_path"], dict(_RUN), "PLCSIM_ADVANCED",
                                      case["semantic"], _ROOT, bridge=sim, runtime_config=_CONFIG)
    return result, sim


# ---------------------------------------------------------------------------------------------
# 1-5: normalizacion con provenance (sin inventar)
# ---------------------------------------------------------------------------------------------

def test_latch_without_parameters_gets_traced_effective_resources(d03):
    semantic = d03["semantic"]
    assert semantic["intent_id"] == "INT_MOTOR_LATCH"  # nunca se cambia la interpretacion
    assert semantic["parameters"]["trigger_input"] == "I_Start"
    assert semantic["parameters"]["stop_input"] == "I_Stop"
    assert semantic["parameters"]["motor_output"] == "Q_Motor_Enable"
    assert semantic["parameters"]["emergency_input"] == "FALSE"
    provenance = semantic["parameter_provenance"]
    for key in ("trigger_input", "stop_input", "motor_output"):
        assert provenance[key]["source"] == ES.SOURCE_DEFAULT and provenance[key]["category"] == ES.CATEGORY_EXTERNAL
        assert provenance[key]["original_value"] is None and "INT_MOTOR_LATCH" in provenance[key]["reason"]
    # I_Start/I_Stop son LOCKED en el banco; Q_Motor_Enable no existe en el working map: lo resuelve el IOAllocator.
    assert provenance["trigger_input"]["resolution"] == ES.RESOLUTION_MAP_EXISTING and provenance["trigger_input"]["state"] == "LOCKED"
    assert provenance["motor_output"]["resolution"] == ES.RESOLUTION_IO_ALLOCATION
    # La emergencia la fijo semantic_repair (banco sin I_Emergency): REPAIR, literal seguro, nunca el LLM.
    assert provenance["emergency_input"]["source"] == ES.SOURCE_REPAIR and provenance["emergency_input"]["category"] == ES.CATEGORY_SAFE_LITERAL
    effective = semantic["effective_semantics"]
    assert effective["status"] == ES.STATUS_RESOLVED and effective["origin"] == ES.SOURCE_LLM
    assert effective["interpreted_parameters"] == {"emergency_input": "FALSE"}
    assert sorted(effective["defaulted_keys"]) == ["motor_output", "stop_input", "trigger_input"]
    assert effective["internal_technical_defaults"] == {"run_latch": "M_RunLatch"}
    assert ES.interpreted_parameters(semantic) == {"emergency_input": "FALSE"}


def test_effective_resources_are_allocated_by_the_same_io_allocator_without_ghost_tags(d03):
    names = {p["proposed_name"]: p for p in d03["proposals"]}
    assert set(names) == {"Q_Motor_Enable"}  # solo lo que no existia; I_Start/I_Stop LOCKED se reutilizan
    assert names["Q_Motor_Enable"]["address"].startswith("%QX")
    assert d03["revalidation"]["is_valid"] and not d03["revalidation"]["unauthorized_tags"]
    working_names = {v["name"] for v in d03["working"]["variables"]}
    assert "I_Emergency" not in working_names  # nunca se inventa una emergencia
    base_locations = {v["location"] for v in json.loads(_BASE_MAP.read_text(encoding="utf-8-sig"))["variables"] if v.get("location")}
    assert {v["location"] for v in d03["working"]["variables"] if v.get("location")} == base_locations  # sin canales fantasma


def test_snapshot_freezes_parameter_bindings_and_provenance(d03):
    snapshot = d03["snapshot"]
    bindings = snapshot["parameter_bindings"]
    assert bindings["trigger_input"]["name"] == bindings["trigger_input"]["functional_name"] == "I_Start"
    assert bindings["trigger_input"]["address"] == "%IX16.0" and bindings["trigger_input"]["signal"] == "DI"
    assert bindings["stop_input"]["name"] == "I_Stop" and bindings["stop_input"]["address"] == "%IX16.1"
    assert bindings["motor_output"]["name"] == "Q_Motor_Enable" and bindings["motor_output"]["signal"] == "DO"
    assert {b["provenance"] for b in bindings.values()} == {ES.SOURCE_DEFAULT}
    assert "emergency_input" not in bindings  # FALSE no es un recurso fisico
    assert snapshot["parameter_provenance"]["motor_output"]["source"] == ES.SOURCE_DEFAULT
    assert snapshot["effective_semantics_status"] == ES.STATUS_RESOLVED
    assert {b["functional_name"] for b in snapshot["bindings"]} == {"I_Start", "I_Stop", "Q_Motor_Enable"}


def test_ir_and_scl_use_exactly_the_effective_resources(d03):
    external = {v.name for v in d03["ir"].pou.variables if v.name.startswith(_EXTERNAL)}
    assert external == {"I_Start", "I_Stop", "Q_Motor_Enable"}
    assert d03["ir"].metadata["parameters"]["trigger_input"] == "I_Start"
    scl = d03["scl"]
    for name in ("I_Start", "I_Stop", "Q_Motor_Enable"):
        assert f'"{name}"' in scl or name in scl
    referenced = {token for token in ("I_Emergency", "I_Reset", "Q_Alarm", "Q_Aux_Output", "I_Sensor1") if token in scl}
    assert referenced == set()  # ningun otro recurso externo aparece en el programa


def test_generator_never_introduces_a_hidden_external_default(d03):
    project_ir = copy.deepcopy(d03["ir"])
    del project_ir.metadata["parameters"]["motor_output"]
    project_ir.metadata["semantic_output"]["parameters"].pop("motor_output")
    with pytest.raises(FunctionalResourceUnresolvedError, match=code_generator.FUNCTIONAL_RESOURCE_UNRESOLVED):
        generate_implementation_from_ir(project_ir)
    # Sin semantica efectiva RESUELTA (ensayos/llamadas legacy) el comportamiento anterior no cambia.
    project_ir.metadata["semantic_output"]["effective_semantics"]["status"] = ES.STATUS_NOT_APPLICABLE
    assert "Q_Motor_Enable" in generate_implementation_from_ir(project_ir)


@pytest.mark.parametrize("intent_id", sorted(INTENT_RESOURCE_TABLE))
def test_generator_external_defaults_match_the_single_source_table(intent_id, monkeypatch):
    """Sin defaults duplicados divergentes: cada default externo de la plantilla es el del contrato del intent."""
    seen: list[tuple[str, Any]] = []
    original = code_generator._param

    def _spy(parameters, *keys, default):
        seen.append((keys[0], default))
        return original(parameters, *keys, default=default)

    monkeypatch.setattr(code_generator, "_param", _spy)
    code_generator.IMPLEMENTED_TEMPLATES[intent_id]({})
    table = dict(INTENT_RESOURCE_TABLE[intent_id])
    for key, default in seen:
        if isinstance(default, str) and default.startswith(_EXTERNAL):
            assert table.get(key) == default, (intent_id, key, default)


# ---------------------------------------------------------------------------------------------
# 10-15: Oracle (PLC simulado con reloj virtual, mismo harness que la validacion de los 32 Oracles)
# ---------------------------------------------------------------------------------------------

def test_oracle_resolves_roles_and_runs_functional_despite_intent_mismatch(d03):
    result, sim = _run_oracle(d03, latch("I_Start", "I_Stop", "Q_Motor_Enable"))
    roles = result["roles"]["roles"]
    assert result["roles"]["status"] == "RESOLVED"
    assert {role: entry["functional_name"] for role, entry in roles.items()} == {
        "START": "I_Start", "STOP": "I_Stop", "MOTOR_MAIN": "Q_Motor_Enable"}
    assert sim.calls == ["io_sequence"]  # el Runtime SI se ejecuto
    # Comportamiento correcto: Start ON, soltar Start mantiene, Stop apaga -> Functional PASS.
    assert result["functional"]["evaluated"] and result["functional"]["success"] is True
    assert result["safety"]["success"] is True
    # La discrepancia semantica queda registrada como tal (no como Functional REVIEW).
    semantic = result["semantic"]
    assert semantic["success"] is False and semantic["intent_match"] is False
    assert semantic["intent_id"] == "INT_MOTOR_LATCH" and semantic["intent_expected"] == ["INT_MOTOR_START_STOP"]
    assert semantic["failed_checks"] == ["intent_accepted"]
    assert all(c["passed"] for c in semantic["checks"] if c["check"].startswith("role:"))
    assert any("DEFAULT" in w for w in semantic["warnings"])
    # Veredicto global: politica vigente sin cambios (PASS exige semantica, final_rule del Oracle FROZEN).
    assert (result["verdict"], result["verdict_reason"]) == ("REVIEW", oracle_runner.SEMANTIC_MISMATCH)
    patch = oracle_runner.trial_patch(result)
    assert patch["stages"] == {"functional_success": True, "safety_success": True, "semantic_benchmark_match": False}
    assert patch["semantic_benchmark"]["intent_match"] is False


def test_incorrect_behavior_is_functional_fail_even_with_a_semantic_mismatch(d03):
    def no_memory(io, st, dt):  # el motor sigue al pulsador: sin memoria de marcha
        io["Q_Motor_Enable"] = io.get("I_Start", False) and not io.get("I_Stop", False)

    result, _ = _run_oracle(d03, no_memory)
    assert result["functional"]["success"] is False and result["semantic"]["success"] is False
    assert (result["verdict"], result["verdict_reason"]) == ("FAIL", "FUNCTIONAL_FAILURE")  # nunca REVIEW por el intent


def test_semantic_match_and_correct_behavior_still_pass(tmp_path):
    payload = _base_semantic_output("INT_MOTOR_START_STOP", {"trigger_input": "I_Start", "stop_input": "I_Stop",
                                                             "motor_output": "Q_Motor_Enable", "run_latch": "M_RunLatch"},
                                    ["I_Start", "I_Stop", "Q_Motor_Enable"])
    case = _experiment_pipeline(tmp_path, payload)
    assert {k: v["source"] for k, v in case["semantic"]["parameter_provenance"].items()}["trigger_input"] == ES.SOURCE_LLM
    result, _ = _run_oracle(case, latch("I_Start", "I_Stop", "Q_Motor_Enable"))
    assert result["semantic"]["success"] is True and result["functional"]["success"] is True
    assert result["verdict"] == "PASS"


def test_unresolvable_roles_still_produce_review_without_runtime(d03):
    snapshot = copy.deepcopy(d03["snapshot"])
    snapshot["parameter_bindings"] = {}
    path = d03["snapshot_path"].with_name("snapshot_sin_roles.json")
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    sim = _Sim(latch("I_Start", "I_Stop", "Q_Motor_Enable"))
    result = oracle_runner.run_oracle(_oracle("D03"), path, dict(_RUN), "PLCSIM_ADVANCED", d03["semantic"], _ROOT,
                                      bridge=sim, runtime_config=_CONFIG)
    assert result["verdict"] == "REVIEW" and result["verdict_reason"] == oracle_runner.ROLE_NOT_FOUND and sim.calls == []
    ambiguous = copy.deepcopy(d03["snapshot"])
    ambiguous["parameter_bindings"]["start_input"] = {**ambiguous["parameter_bindings"]["stop_input"]}
    path.write_text(json.dumps(ambiguous), encoding="utf-8")
    result = oracle_runner.run_oracle(_oracle("D03"), path, dict(_RUN), "PLCSIM_ADVANCED", d03["semantic"], _ROOT,
                                      bridge=sim, runtime_config=_CONFIG)
    assert result["verdict"] == "REVIEW" and result["verdict_reason"] in (oracle_runner.ROLE_AMBIGUOUS, oracle_runner.ROLE_CONFLICT)


def test_d04_accepts_latch_so_the_same_program_matches_there(d03):
    result, _ = _run_oracle(d03, latch("I_Start", "I_Stop", "Q_Motor_Enable"), oracle_id="D04")
    assert result["semantic"]["intent_match"] is True and result["functional"]["success"] is True
    assert result["verdict"] == "PASS"


# ---------------------------------------------------------------------------------------------
# Reglas generales de la normalizacion
# ---------------------------------------------------------------------------------------------

def _map(*variables: tuple[str, str, str]) -> dict[str, Any]:
    return {"variables": [{"name": n, "location": loc, "state": st, "type": "BOOL",
                           "class": "input" if loc.startswith("%I") else "output", "llm_allowed": True}
                          for n, loc, st in variables]}


def test_two_candidates_are_never_guessed():
    duplicated = _map(("I_Start", "%IX0.0", "LOCKED"), ("I_Start", "%IX0.1", "ASSIGNED"), ("I_Stop", "%IX0.2", "LOCKED"))
    result = ES.normalize_effective_semantics({"intent_id": "INT_MOTOR_LATCH", "parameters": {"emergency_input": "FALSE"}}, duplicated)
    assert "trigger_input" not in result["parameters"]
    assert result["effective_semantics"]["status"] == ES.STATUS_UNRESOLVED
    assert [e["code"] for e in result["effective_semantics"]["errors"]] == [ES.ERROR_AMBIGUOUS]
    conflict = ES.normalize_effective_semantics(
        {"intent_id": "INT_MOTOR_LATCH", "parameters": {"stop_input": "I_Start", "emergency_input": "FALSE"}},
        _map(("I_Start", "%IX0.0", "LOCKED")))
    assert "trigger_input" not in conflict["parameters"]  # I_Start ya es el Stop: no se reutiliza para Start
    assert conflict["effective_semantics"]["errors"][0]["code"] == ES.ERROR_AMBIGUOUS
    kind = ES.normalize_effective_semantics({"intent_id": "INT_MOTOR_LATCH", "parameters": {}}, _map(("I_Start", "%QX0.0", "ASSIGNED")))
    assert any(e["code"] == ES.ERROR_KIND_MISMATCH for e in kind["effective_semantics"]["errors"])


def test_ambiguity_fails_validation_before_any_allocation():
    intents, safety = _catalog()
    io_map = _map(("I_Start", "%IX0.0", "LOCKED"), ("I_Start", "%IX0.1", "ASSIGNED"), ("I_Stop", "%IX0.2", "LOCKED"),
                  ("Q_Motor_Enable", "%QX0.0", "ASSIGNED"))
    effective, validation = llm_parser._repair_and_validate(_llm_latch_without_parameters(), io_map, intents, safety, ES.SOURCE_LLM)
    assert not validation["is_valid"] and any(ES.ERROR_AMBIGUOUS in e for e in validation["errors"])


def test_never_invents_an_emergency_and_reuses_an_existing_one():
    without = ES.normalize_effective_semantics({"intent_id": "INT_MOTOR_LATCH", "parameters": {}},
                                               _map(("I_Start", "%IX0.0", "LOCKED"), ("I_Stop", "%IX0.1", "LOCKED")))
    assert without["parameters"]["emergency_input"] == "FALSE"
    assert without["parameter_provenance"]["emergency_input"]["category"] == ES.CATEGORY_SAFE_LITERAL
    wired = ES.normalize_effective_semantics({"intent_id": "INT_MOTOR_LATCH", "parameters": {}},
                                             _map(("I_Emergency", "%IX0.7", "LOCKED"), ("I_Start", "%IX0.0", "LOCKED")))
    assert wired["parameters"]["emergency_input"] == "I_Emergency"
    assert wired["parameter_provenance"]["emergency_input"]["resolution"] == ES.RESOLUTION_MAP_EXISTING


def test_locked_channels_are_never_taken_for_a_default_resource():
    intents, safety = _catalog()
    all_locked = _map(("I_Start", "%IX0.0", "LOCKED"), ("I_Stop", "%IX0.1", "LOCKED"), ("Q_Lamp", "%QX0.0", "LOCKED"))
    effective, validation = llm_parser._repair_and_validate(_llm_latch_without_parameters(), all_locked, intents, safety, ES.SOURCE_LLM)
    proposals = validation.get("io_assignment_proposals") or []
    assert proposals and all(p.get("blocked") for p in proposals)  # nunca roba un canal LOCKED
    assert not validation["is_valid"]


def test_assigned_channel_with_the_name_is_reused_and_free_channels_are_untouched():
    io_map = _map(("I_Start", "%IX0.0", "LOCKED"), ("I_Stop", "%IX0.1", "LOCKED"), ("Q_Motor_Enable", "%QX0.0", "ASSIGNED"),
                  ("Q_Free0_1", "%QX0.1", "FREE"))
    result = ES.normalize_effective_semantics({"intent_id": "INT_MOTOR_LATCH", "parameters": {}}, io_map)
    assert result["parameter_provenance"]["motor_output"]["resolution"] == ES.RESOLUTION_MAP_EXISTING
    assert result["parameter_provenance"]["motor_output"]["address"] == "%QX0.0"


def test_optional_and_parser_required_keys_are_never_filled():
    io_map = _map(("I_Start", "%IX0.0", "LOCKED"), ("I_Stop", "%IX0.1", "LOCKED"), ("I_Reset", "%IX0.2", "ASSIGNED"),
                  ("Q_Alarm", "%QX0.1", "ASSIGNED"), ("Q_Motor_Enable", "%QX0.0", "ASSIGNED"))
    result = ES.normalize_effective_semantics(
        {"intent_id": "INT_MOTOR_START_STOP", "parameters": {}}, io_map,
        parser_required_keys=tuple(INTENT_PARAMETER_RULES["INT_MOTOR_START_STOP"]["required"]))
    for key in OPTIONAL_PARAMETER_KEYS["INT_MOTOR_START_STOP"]:
        assert key not in result["parameters"]  # reset/alarma/pilotos solo si el comando los pidio
    for key in ("trigger_input", "stop_input", "motor_output"):
        assert key not in result["parameters"]  # el parser DEBE expresarlos: su ausencia sigue siendo un error
    intents, safety = _catalog()
    _, validation = llm_parser._repair_and_validate(
        _base_semantic_output("INT_MOTOR_START_STOP", {}, []), io_map, intents, safety, ES.SOURCE_LLM)
    assert any("Faltan parametros requeridos" in e for e in validation["errors"])


def test_composite_programs_are_not_normalized():
    # Forma real del multi-actor (functional_requirements.detect_multi_actor_motor_targets).
    requirements = [{"type": "motor_start_latch", "target": "Q_Motor_1", "trigger_input": "I_Start_M1"},
                    {"type": "motor_start_latch", "target": "Q_Motor_2", "trigger_input": "I_Start_M2"}]
    result = ES.normalize_effective_semantics(
        {"intent_id": "INT_MOTOR_LATCH", "parameters": {}, "functional_requirements": requirements}, _map(("I_Start", "%IX0.0", "LOCKED")))
    assert result["effective_semantics"]["status"] == ES.STATUS_NOT_APPLICABLE and result["parameters"] == {}
    unknown = ES.normalize_effective_semantics({"intent_id": "INT_UNKNOWN", "parameters": {}}, {"variables": []})
    assert unknown["effective_semantics"]["status"] == ES.STATUS_NOT_APPLICABLE


def test_value_defaults_are_traced_but_never_counted_as_interpreted():
    result = ES.normalize_effective_semantics({"intent_id": "INT_AUTO_STOP_TIMER", "parameters": {}},
                                              _map(("I_Start", "%IX0.0", "LOCKED"), ("I_Stop", "%IX0.1", "LOCKED")))
    assert result["effective_semantics"]["functional_value_defaults"] == {"operation_time": "T#10s"}
    assert "operation_time" not in result["parameters"]  # solo trazado
    assert "trigger_input" not in ES.interpreted_parameters(result)


def test_legacy_outputs_without_provenance_keep_every_parameter_as_interpreted():
    legacy = {"intent_id": "INT_MOTOR_START_STOP", "parameters": {"trigger_input": "I_Start", "duration": "T#3s"}}
    assert ES.interpreted_parameters(legacy) == legacy["parameters"]


# ---------------------------------------------------------------------------------------------
# Presentacion: trial_stage_summary / batch CSV / historicos
# ---------------------------------------------------------------------------------------------

def _record(stages: dict[str, Any], final: str | None, **extra: Any) -> dict[str, Any]:
    return {"trial_id": "D03_V2_TEXT_DEV_007", "case_id": "D03", "variant_id": "V2", "input_mode": "TEXT",
            "stages": stages, "final_status": final, "final_verdict": final,
            "evaluation": {"status": "COMPLETED", "final_verdict": final, "attempts": [{}]},
            "download": {"cpu_run_confirmed": True}, "oracle": {"verdict": final}, **extra}


def test_stage_summary_keeps_semantic_pipeline_benchmark_and_functional_apart():
    record = _record({"semantic_success": True, "semantic_benchmark_match": False, "functional_success": True,
                      "safety_success": True}, "REVIEW")
    summary = DE.trial_stage_summary(record)
    assert (summary["semantic"], summary["semantic_benchmark"], summary["functional"], summary["safety"]) == ("PASS", "FAIL", "PASS", "PASS")
    assert summary["final_verdict"] == "REVIEW" and summary["infrastructure_status"] == "OK"
    assert dict(DE.verdict_table(record))["Semantic Benchmark"] == "FAIL"


def test_batch_row_exports_every_dimension(tmp_path):
    record = _record({"semantic_success": True, "semantic_benchmark_match": False, "functional_success": True,
                      "safety_success": True}, "REVIEW")
    entry = {"index": 0, "status": TB.ENTRY_COMPLETED, "trial_dir": str(tmp_path), "evaluable": True}
    row = TB.trial_row(tmp_path, record, entry, {"batch_id": "TEXT_DEV_X"})
    assert {k: row[k] for k in ("semantic_pipeline_success", "semantic_benchmark_match", "functional_success", "safety_success",
                                "infrastructure_status", "final_verdict")} == {
        "semantic_pipeline_success": True, "semantic_benchmark_match": False, "functional_success": True,
        "safety_success": True, "infrastructure_status": "OK", "final_verdict": "REVIEW"}
    assert row["semantic"] == "PASS" and row["semantic_benchmark"] == "FAIL" and row["functional"] == "PASS"
    # Columnas nuevas AL FINAL: las anteriores conservan nombre y posicion.
    assert TB.CSV_FIELDS[-8:-2] == ("semantic_benchmark", "semantic_pipeline_success", "semantic_benchmark_match",
                                    "functional_success", "safety_success", "infrastructure_status")
    assert TB.CSV_FIELDS[-2:] == ("archive_attempt_count", "archive_recovered_after_retry")  # reintentos de Archive, al final
    assert TB.CSV_FIELDS[TB.CSV_FIELDS.index("superseded_trial_ids") + 1] == "semantic_benchmark"


def test_historical_records_are_never_reinterpreted():
    """D03_V2_TEXT_DEV_006: REVIEW por ORACLE_ROLE_NOT_FOUND, sin semantic_benchmark_match persistido."""
    historic = _record({"semantic_success": True, "functional_success": None, "safety_success": None}, "REVIEW",
                       oracle={"verdict": "REVIEW", "verdict_reason": "ORACLE_ROLE_NOT_FOUND"})
    before = copy.deepcopy(historic)
    summary = DE.trial_stage_summary(historic)
    assert summary["final_verdict"] == "REVIEW" and summary["functional"] == "REVIEW" and summary["semantic_benchmark"] == "-"
    assert historic == before  # la presentacion nunca reescribe el registro


def test_real_historical_trials_on_disk_still_summarize_without_changes():
    paths = sorted((_ROOT / "results").glob("development_*/*/*/*/trial.json"))[:30]
    for path in paths:
        raw = path.read_bytes()
        record = json.loads(raw.decode("utf-8"))
        summary = DE.trial_stage_summary(record)
        assert summary["semantic_benchmark"] in ("-", "PASS", "FAIL")
        assert path.read_bytes() == raw


def test_frozen_artifacts_unchanged():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
    assert {name: B.file_hash(_ROOT / name) for name in _FROZEN} == _FROZEN_BEFORE
