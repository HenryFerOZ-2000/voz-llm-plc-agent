"""
Recursos funcionales identificables, nombrables y asignables ANTES de IR/codegen (Modo Normal).

Regresion de la incidencia real DVL-001 (docs/development_validation_log.md): un comando Manual/Automatico
complejo fallaba en Generacion con "Se solicito una variable funcional sin nombre." porque un
comportamiento fuera del catalogo (functional_requirements[3].type = "sensor_timeout_alarm") se
trataba como variable ad-hoc {"name", "type"}. Sin TIA: semantica -> IOAllocator -> IR -> SCL -> verificador.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

import llm_parser  # noqa: E402
from code_generator import CompositionNotSupportedError, generate_implementation_from_ir  # noqa: E402
from functional_requirements import CLASS_CATALOG, CLASS_UNSUPPORTED, CLASS_VARIABLE, classify_functional_requirement  # noqa: E402
from functional_resources import (  # noqa: E402
    FUNCTIONAL_REQUIREMENT_UNSUPPORTED,
    FUNCTIONAL_RESOURCE_UNRESOLVED,
    FunctionalResourceError,
    canonical_functional_tag,
    resolve_functional_resources,
)
from io_allocator import apply_assignments  # noqa: E402
from ir_builder import build_project_ir  # noqa: E402
from project_packager import generate_project_package  # noqa: E402
from semantic_validator import validate_semantic_output  # noqa: E402
from trial_experiments import batch_runner as B  # noqa: E402
from utils import load_json_file  # noqa: E402

from test_execute_full_pipeline import _base_semantic_output  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)
_INCIDENT = json.loads((Path(__file__).parent / "fixtures" / "normal_incident_manual_auto_sequence.json").read_text(encoding="utf-8"))
_ARTIFICIAL = re.compile(r"^(?:[IQM]_)?(?:Variable|Var|Output|Input|Signal|Tag|Resource)_?\d+$", re.IGNORECASE)


def _configs() -> tuple[dict, dict]:
    return load_json_file(_ROOT / "config" / "intents_catalog.json"), load_json_file(_ROOT / "config" / "safety_rules.json")


def _free_map() -> dict[str, Any]:
    """Banco de prueba propio (8 DI + 8 DO FREE): independiente del mapa vivo del usuario."""
    def channel(kind: str, index: int) -> dict[str, Any]:
        prefix, area = ("I", "%IX") if kind == "input" else ("Q", "%QX")
        return {"name": f"{prefix}_Free_{index}", "class": kind, "type": "BOOL", "location": f"{area}4.{index}",
                "initial_value": "FALSE", "description": "", "aliases": [], "semantic_role": "", "llm_allowed": True,
                "safety_level": "normal", "unit": "", "min": None, "max": None, "comments": "", "state": "FREE"}
    return {"schema_version": 1, "metadata": {"map_id": "test_free_bench", "name": "TEST_FREE_BENCH", "version": 1},
            "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_"},
            "variables": [channel(kind, i) for kind in ("input", "output") for i in range(8)], "history": []}


def _allocate(semantic: dict[str, Any], io_map: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    catalog, safety = _configs()
    validation = validate_semantic_output(semantic, io_map, catalog, safety)
    proposals = [p for p in validation["io_assignment_proposals"] if not p.get("blocked")]
    updated = apply_assignments(copy.deepcopy(io_map), proposals, source="TEST") if proposals else io_map
    return validation, (updated[0] if isinstance(updated, tuple) else updated)


class _NoNetworkClient:
    def __getattr__(self, name):
        raise AssertionError("el test no debe llamar al LLM real")


def _incident_semantic_output(io_map: dict[str, Any]) -> dict[str, Any]:
    """Ruta real del parser (repair + validacion, perfil Normal + historial de aclaracion) con la respuesta EXACTA del LLM."""
    catalog, safety = _configs()
    return llm_parser.parse_command(
        _INCIDENT["command_text"], mode="llm", io_map=io_map, intents_catalog=catalog, safety_rules=safety,
        llm_client=_NoNetworkClient(), llm_response_text=copy.deepcopy(_INCIDENT["llm_response"]),
        interaction_profile="normal", clarification_history=_INCIDENT["clarification_history"])


# ---------------------------------------------------------------------------------------------
# Regresion de la incidencia real (DVL-001)
# ---------------------------------------------------------------------------------------------

def test_incident_requirement_was_misrouted_as_an_unnamed_variable_and_now_is_a_composable_primitive():
    requirements = _INCIDENT["llm_response"]["functional_requirements"]
    culprit = requirements[3]
    assert culprit["type"] == "sensor_timeout_alarm" and "name" not in culprit
    assert classify_functional_requirement(culprit) == CLASS_CATALOG
    assert all(classify_functional_requirement(r) == CLASS_CATALOG for r in requirements)
    assert resolve_functional_resources(requirements)["errors"] == []


def test_incident_command_generates_valid_scl_without_tia(tmp_path):
    catalog, safety = _configs()
    semantic = _incident_semantic_output(_free_map())
    # Representacion semantica valida y perfil Normal registrado (habilita la validacion temprana).
    assert semantic["interaction_profile"] == "normal"
    assert semantic["semantic_validation"]["is_valid"] is True, semantic["semantic_validation"]["errors"]
    assert [item["answer"] for item in _INCIDENT["clarification_history"]][0].startswith("Mandos mantenidos")
    commands = next(r for r in semantic["functional_requirements"] if r["type"] == "manual_mode")["commands"]
    assert {c["behavior"] for c in commands} == {"maintained"}

    # Todos los recursos tienen nombre y el IOAllocator los resuelve a canales reales.
    validation, io_map = _allocate(semantic, _free_map())
    external = {"I_Mode_Manual", "I_Mode_Auto", "I_Start", "I_Stop", "I_Reset", "I_Piece_Sensor",
                "I_Manual_Conveyor_Command", "I_Manual_Pump_Command", "Q_Conveyor_Enable", "Q_Pump_Enable", "Q_Alarm"}
    allocated = {p["proposed_name"]: p for p in validation["io_assignment_proposals"] if not p.get("blocked")}
    assert external <= set(allocated), external - set(allocated)
    assert all(not p.get("blocked") for p in validation["io_assignment_proposals"])

    # IR + SCL + verificador reales.
    project_ir = build_project_ir(semantic, io_map, "SIEMENS_SCL_V18")
    names = [v.name for v in project_ir.pou.variables]
    assert all(names) and len(names) == len(set(names))
    package = generate_project_package(semantic, "SIEMENS_SCL_V18", io_map, catalog, safety, output_dir=tmp_path / "pkg")
    assert package["verification"]["is_valid"] is True, package["verification"]["errors"]
    scl = Path(package["artifacts"]["package_dir"], "siemens_source.scl").read_text(encoding="utf-8")
    for expected in (
        "#M_AutoMode := #I_Mode_Auto AND NOT #I_Mode_Manual;",            # modos excluyentes
        "#M_ManualMode := #I_Mode_Manual AND NOT #I_Mode_Auto;",
        "OR NOT (#M_AutoMode) THEN",                                    # la secuencia solo vive en Automatico
        "#T_Seq1_S1(IN := #M_Seq1_S1, PT := T#3s);",                    # 3 s antes de la bomba
        "(#M_ManualMode AND #I_Manual_Conveyor_Command)",               # orden manual mantenida
        "(#M_ManualMode AND #I_Manual_Pump_Command AND (#Q_Conveyor_Enable))",  # bomba solo con banda
        "#T_Wd1(IN := #M_Wd1_Armed, PT := T#5s);",                      # supervision del sensor
        "IF #M_Wd1_Fault AND #M_Wd1_Recovered AND #I_Reset THEN",       # alarma: falla desaparecida + Reset
        "#Q_Alarm := #M_Wd1_Fault;",
    ):
        assert expected in scl, expected
    # Stop detiene ambos actuadores; la falla los detiene en cualquier modo.
    for output in ("#Q_Conveyor_Enable", "#Q_Pump_Enable"):
        line = next(line for line in scl.splitlines() if line.startswith(f"{output} :="))
        assert "NOT (#I_Stop)" in line and "NOT #M_Wd1_Fault" in line


def test_incident_program_has_no_ghost_resources():
    semantic = _incident_semantic_output(_free_map())
    _, io_map = _allocate(semantic, _free_map())
    project_ir = build_project_ir(semantic, io_map, "SIEMENS_SCL_V18")
    code = generate_implementation_from_ir(project_ir)
    used = set(re.findall(r"\b(?:AI|AO|[IQMTCFR])_[A-Za-z0-9_]+", code))
    declared = {v.name for v in project_ir.pou.variables}
    assert used <= declared                     # nada usado sin declarar
    assert declared <= used, declared - used    # nada declarado sin uso (ningun recurso fantasma)
    assert not any(_ARTIFICIAL.match(name) for name in declared)


# ---------------------------------------------------------------------------------------------
# Naming canonico generico (role / actor / kind -> tag)
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("role", "actor", "kind", "expected"), [
    ("MANUAL_MIXER_COMMAND", None, "input", "I_Manual_Mixer_Command"),
    ("MIXER_OUTPUT", None, "output", "Q_Mixer"),
    ("OUTPUT", "heater", "output", "Q_Heater"),
    ("COMMAND", "motor 2", "input", "I_Motor_2_Command"),
    ("FAULT_ALARM", None, "output", "Q_Fault_Alarm"),
    ("presence_sensor", None, "input", "I_Presence_Sensor"),
])
def test_canonical_tag_follows_project_naming(role, actor, kind, expected):
    assert canonical_functional_tag(role, actor, kind) == expected


def test_canonical_tag_never_invents_names():
    assert canonical_functional_tag(None, None, "output") is None      # ni rol ni actor
    assert canonical_functional_tag("OUTPUT", None, "output") is None  # el rol solo repite la direccion
    assert canonical_functional_tag("MIXER", None, None) is None       # direccion desconocida


def test_nested_output_without_name_gets_canonical_name_from_role_and_actor():
    requirements = [{"type": "timed_sequence", "start_input": "I_Start", "stop_input": "I_Stop",
                     "steps": [{"outputs": [{"role": "OUTPUT", "actor": "mixer"}], "duration": "T#4s"},
                               {"outputs": [{"role": "MIXER_OUTPUT"}, {"role": "HEATER_OUTPUT"}]}]}]
    resolution = resolve_functional_resources(requirements)
    assert resolution["errors"] == []
    steps = resolution["requirements"][0]["steps"]
    assert steps[0]["outputs"] == ["Q_Mixer"] and steps[1]["outputs"] == ["Q_Mixer", "Q_Heater"]
    assert resolution["derived"][0]["path"] == "functional_requirements[0].steps[0].outputs[0]"


def test_nested_input_without_name_uses_field_direction():
    requirements = [{"type": "timed_sequence", "start_input": {"role": "START_COMMAND"}, "stop_input": "I_Stop",
                     "steps": [{"outputs": ["Q_Mixer"]}]},
                    {"type": "manual_mode", "mode_input": "I_Mode_Manual",
                     "commands": [{"input": {"role": "COMMAND", "actor": "mixer"}, "output": "Q_Mixer", "behavior": "maintained"}]}]
    resolution = resolve_functional_resources(requirements)
    assert resolution["errors"] == []
    assert resolution["requirements"][0]["start_input"] == "I_Start_Command"
    assert resolution["requirements"][1]["commands"][0]["input"] == "I_Mixer_Command"


def test_resource_without_role_or_actor_is_a_structured_error_before_ir():
    requirements = [{"type": "timed_sequence", "start_input": "I_Start", "stop_input": "I_Stop",
                     "steps": [{"outputs": [{"kind": "output"}], "duration": "T#2s"}, {"outputs": ["Q_Mixer"]}]}]
    resolution = resolve_functional_resources(requirements)
    [error] = resolution["errors"]
    assert error["code"] == FUNCTIONAL_RESOURCE_UNRESOLVED
    assert error["path"] == "functional_requirements[0].steps[0].outputs[0]"
    assert resolution["derived"] == []  # no se invento ningun nombre
    semantic = _base_semantic_output("INT_UNKNOWN", {"emergency_input": "FALSE"}, ["I_Start", "I_Stop"])
    semantic["functional_requirements"] = requirements
    with pytest.raises(FunctionalResourceError) as raised:
        build_project_ir(semantic, _free_map(), "SIEMENS_SCL_V18")
    assert FUNCTIONAL_RESOURCE_UNRESOLVED in str(raised.value) and "sin nombre." not in str(raised.value)
    catalog, safety = _configs()
    validation = validate_semantic_output(semantic, _free_map(), catalog, safety)
    assert validation["is_valid"] is False
    assert validation["functional_resource_errors"][0]["path"] == "functional_requirements[0].steps[0].outputs[0]"


def test_requirement_without_type_or_name_is_unresolved():
    resolution = resolve_functional_resources([{"outputs": ["Q_Mixer"]}])
    assert [(e["code"], e["path"]) for e in resolution["errors"]] == [(FUNCTIONAL_RESOURCE_UNRESOLVED, "functional_requirements[0]")]


def test_unknown_behavior_is_unsupported_not_an_unnamed_variable():
    requirement = {"type": "valve_dance", "outputs": ["Q_Mixer"]}
    assert classify_functional_requirement(requirement) == CLASS_UNSUPPORTED
    assert classify_functional_requirement({"name": "Level_SP", "type": "REAL"}) == CLASS_VARIABLE
    [error] = resolve_functional_resources([requirement])["errors"]
    assert error["code"] == FUNCTIONAL_REQUIREMENT_UNSUPPORTED and error["path"] == "functional_requirements[0].type"
    semantic = _base_semantic_output("INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Mixer"}, [])
    semantic["functional_requirements"] = [requirement]
    with pytest.raises(FunctionalResourceError, match=FUNCTIONAL_REQUIREMENT_UNSUPPORTED):
        build_project_ir(semantic, _free_map(), "SIEMENS_SCL_V18")


def test_names_do_not_collide_and_same_type_actors_get_distinct_names():
    requirements = [{"type": "manual_mode", "mode_input": "I_Mode_Manual", "commands": [
        {"input": {"role": "COMMAND", "actor": f"motor {i}"}, "output": {"role": "OUTPUT", "actor": f"motor {i}"},
         "behavior": "maintained"} for i in (1, 2, 3)]}]
    resolution = resolve_functional_resources(requirements)
    names = [d["name"] for d in resolution["derived"]]
    assert resolution["errors"] == [] and len(names) == len(set(names)) == 6
    assert {"I_Motor_1_Command", "I_Motor_2_Command", "Q_Motor_1", "Q_Motor_2", "Q_Motor_3"} <= set(names)
    assert not any(_ARTIFICIAL.match(name) for name in names)


def test_derived_names_reach_the_io_allocator_and_the_scl():
    semantic = _base_semantic_output("INT_UNKNOWN", {"emergency_input": "FALSE"}, [])
    semantic["interaction_profile"] = "normal"
    semantic["functional_requirements"] = [
        {"type": "timed_sequence", "start_input": "I_Start", "stop_input": "I_Stop",
         "steps": [{"outputs": [{"role": "OUTPUT", "actor": "mixer"}], "duration": "T#4s"}, {"outputs": [{"role": "HEATER_OUTPUT"}]}]}]
    validation, io_map = _allocate(semantic, _free_map())
    assert validation["is_valid"] is True, validation["errors"]
    assert {"Q_Mixer", "Q_Heater"} <= {p["proposed_name"] for p in validation["io_assignment_proposals"]}
    code = generate_implementation_from_ir(build_project_ir(semantic, io_map, "SIEMENS_SCL_V18"))
    assert "Q_Mixer := (M_Seq1_S1)" in code and "Q_Heater := (M_Seq1_S2)" in code


# ---------------------------------------------------------------------------------------------
# Composicion: nada se descarta en silencio
# ---------------------------------------------------------------------------------------------

def _sequence_with(extra: dict[str, Any]) -> dict[str, Any]:
    semantic = _base_semantic_output("INT_UNKNOWN", {"emergency_input": "FALSE"}, [])
    semantic["interaction_profile"] = "normal"
    semantic["functional_requirements"] = [
        {"type": "timed_sequence", "start_input": "I_Start", "stop_input": "I_Stop",
         "steps": [{"outputs": ["Q_Mixer"], "duration": "T#2s"}, {"outputs": ["Q_Heater"]}]}, extra]
    return semantic


def test_unsupported_behavior_inside_a_composition_is_rejected_not_dropped():
    semantic = _sequence_with({"type": "run_pilot"})
    catalog, safety = _configs()
    validation = validate_semantic_output(semantic, _free_map(), catalog, safety)
    assert validation["is_valid"] is False
    assert any("COMPOSITION_NOT_SUPPORTED" in e and "functional_requirements[1]" in e for e in validation["errors"])
    _, io_map = _allocate(_sequence_with({"type": "never_together", "outputs": ["Q_Mixer", "Q_Heater"]}), _free_map())
    with pytest.raises(CompositionNotSupportedError):
        generate_implementation_from_ir(build_project_ir(semantic, io_map, "SIEMENS_SCL_V18"))


def test_watchdog_without_reset_is_rejected():
    semantic = _sequence_with({"type": "sensor_timeout_alarm", "sensor_input": "I_Level_Switch", "timeout": "T#5s",
                               "affected_outputs": ["Q_Mixer"], "alarm_output": "Q_Fault_Lamp"})
    _, io_map = _allocate(semantic, _free_map())
    with pytest.raises(CompositionNotSupportedError, match="reset_behavior"):
        generate_implementation_from_ir(build_project_ir(semantic, io_map, "SIEMENS_SCL_V18"))


def test_free_text_conditions_are_never_emitted_as_code():
    semantic = _sequence_with({"type": "never_together", "outputs": ["Q_Mixer", "Q_Heater"]})
    semantic["functional_requirements"][0]["mode_condition"] = "solo si el operador lo permite"
    _, io_map = _allocate(_sequence_with({"type": "never_together", "outputs": ["Q_Mixer", "Q_Heater"]}), _free_map())
    with pytest.raises(CompositionNotSupportedError, match="condicion"):
        generate_implementation_from_ir(build_project_ir(semantic, io_map, "SIEMENS_SCL_V18"))


def test_plain_sequence_output_is_unchanged_by_the_extended_composer():
    semantic = _sequence_with({"type": "never_together", "outputs": ["Q_Mixer", "Q_Heater"]})
    _, io_map = _allocate(semantic, _free_map())
    code = generate_implementation_from_ir(build_project_ir(semantic, io_map, "SIEMENS_SCL_V18"))
    for absent in ("M_AutoMode", "M_ManualMode", "M_Wd", "T_Wd", "contribucion", "Alarma"):
        assert absent not in code
    assert "Q_Mixer := (M_Seq1_S1) AND NOT FALSE;" in code


# ---------------------------------------------------------------------------------------------
# Experimentacion congelada y sin hardcode
# ---------------------------------------------------------------------------------------------

def test_experimentation_validation_does_not_run_the_new_early_checks():
    # Sin perfil Normal y sin composicion: misma validacion que antes (el fallo, si lo hay, sigue en IR).
    semantic = _base_semantic_output("INT_DIRECT_OUTPUT", {"trigger_input": "I_Free_0", "output": "Q_Free_0"}, [])
    semantic["functional_requirements"] = [{"type": "valve_dance"}]
    catalog, safety = _configs()
    validation = validate_semantic_output(semantic, _free_map(), catalog, safety)
    assert "functional_resource_errors" not in validation
    assert not any(code in e for e in validation["errors"] for code in (FUNCTIONAL_REQUIREMENT_UNSUPPORTED, FUNCTIONAL_RESOURCE_UNRESOLVED))


def test_experimentation_parse_is_not_marked_with_the_normal_profile():
    catalog, safety = _configs()
    result = llm_parser.parse_command(
        _INCIDENT["command_text"], mode="llm", io_map=_free_map(), intents_catalog=catalog, safety_rules=safety,
        llm_client=_NoNetworkClient(), llm_response_text=copy.deepcopy(_INCIDENT["llm_response"]))
    assert "interaction_profile" not in result


def _section(name: str, start: str, end: str | None = None) -> str:
    text = (_ROOT / "src" / name).read_text(encoding="utf-8")
    text = text[text.index(start):text.index(end) if end else None]
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def test_no_machine_or_phrase_hardcode_in_the_new_logic():
    sections = [
        _section("functional_resources.py", '"""'),
        _section("functional_requirements.py", "IEC_DATA_TYPES =", "def compute_intent_covered_types"),
        _section("code_generator.py", "class CompositionNotSupportedError", "def generate_implementation_from_ir"),
    ]
    for code in sections:
        for forbidden in ("banda", "bomba", "conveyor", "pump", "transportadora", "piece_sensor", "estrella", "star_delta"):
            assert not re.search(rf"(?<![a-z]){forbidden}(?![a-z])", code.lower()), forbidden
        assert not re.search(r"""["'](D(0[1-9]|1\d|20)|P(0[1-9]|1[0-2]))["']""", code)


def test_experimentation_artifacts_unchanged():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
