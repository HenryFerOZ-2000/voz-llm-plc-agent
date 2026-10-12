from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from code_generator import generate_implementation_from_ir
from functional_requirements import compute_semantic_coverage
from ir_builder import build_project_ir
from project_packager import generate_project_package
from semantic_validator import validate_semantic_output
from verifier import verify_project_ir

PID_MAP = {
    "naming_convention": {},
    "variables": [
        {"name": "I_Emergency", "class": "input", "type": "BOOL", "location": "%IX1.0"},
        {"name": "I_Reset", "class": "input", "type": "BOOL", "location": "%IX1.1"},
        {"name": "Q_Pump_Enable", "class": "output", "type": "BOOL", "location": "%QX1.0"},
        {"name": "Q_Alarm", "class": "output", "type": "BOOL", "location": "%QX1.1"}
    ]
}


def _semantic_output(case_id: str, command_text: str, functional_requirements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "intent_id": "INT_PID_SUPERVISOR",
        "case_id": case_id,
        "command_text": command_text,
        "normalized_command": command_text.lower(),
        "parameters": {},
        "confidence": 0.95,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": [],
        "unrecognized_terms": [],
        "functional_requirements": functional_requirements
    }


def _build(case_id: str, command_text: str, functional_requirements: list[dict[str, Any]]):
    semantic_output = _semantic_output(case_id, command_text, functional_requirements)
    project_ir = build_project_ir(semantic_output, PID_MAP, "SIEMENS_SCL_V18")
    project_ir.pou.implementation_code = generate_implementation_from_ir(project_ir)
    return semantic_output, project_ir


# P01 --------------------------------------------------------------------------------------------

def test_p01_enables_automatic_mode() -> None:
    _, project_ir = _build("P01", "Habilita el modo automatico.", [{"type": "set_auto_mode"}])
    variable_names = {v.name for v in project_ir.pou.variables}
    assert {"Auto_Mode", "Manual_Mode"} <= variable_names
    assert "Auto_Mode := TRUE;" in project_ir.pou.implementation_code
    assert "Manual_Mode := FALSE;" in project_ir.pou.implementation_code
    assert verify_project_ir(project_ir)["is_valid"] is True


# P02 --------------------------------------------------------------------------------------------

def test_p02_valid_setpoint_assigns_level_sp(io_map: dict, intents_catalog: dict, safety_rules: dict) -> None:
    semantic_output = _semantic_output(
        "P02", "Establece el nivel del tanque en 60 %.", [{"type": "set_level_setpoint", "value": 60.0}]
    )
    validation = validate_semantic_output(semantic_output, PID_MAP, intents_catalog, safety_rules)
    assert validation["is_valid"] is True
    assert validation["requires_clarification"] is False

    project_ir = build_project_ir(semantic_output, PID_MAP, "SIEMENS_SCL_V18")
    project_ir.pou.implementation_code = generate_implementation_from_ir(project_ir)
    assert "Level_SP := 60.0;" in project_ir.pou.implementation_code
    variables_by_name = {v.name: v for v in project_ir.pou.variables}
    assert variables_by_name["Level_SP"].data_type == "REAL"
    assert verify_project_ir(project_ir)["is_valid"] is True


# P03 --------------------------------------------------------------------------------------------

def test_p03_out_of_range_setpoint_is_rejected_deterministically(intents_catalog: dict, safety_rules: dict) -> None:
    semantic_output = _semantic_output(
        "P03", "Pon el nivel al 150 %.", [{"type": "set_level_setpoint", "value": 150.0}]
    )
    validation = validate_semantic_output(semantic_output, PID_MAP, intents_catalog, safety_rules)
    assert validation["is_valid"] is False
    assert validation["requires_clarification"] is True

    # tambien debe rechazarse el paquete completo antes de generar/importar (nunca logica insegura)
    result = generate_project_package(
        {**semantic_output, "semantic_validation": validation}, "SIEMENS_SCL_V18", PID_MAP, intents_catalog, safety_rules
    )
    assert result["verification"]["is_valid"] is False


def test_setpoint_range_is_config_driven_not_hardcoded(monkeypatch) -> None:
    import semantic_validator
    from semantic_validator import _detect_unsafe_level_setpoints
    # Rango vigente (benchmark v3): 0-100 %, leido de config/pid_supervisor_config.json.
    assert semantic_validator._load_pid_supervisor_config()["level_setpoint"]["min"] == 0.0
    assert semantic_validator._load_pid_supervisor_config()["level_setpoint"]["max"] == 100.0
    assert _detect_unsafe_level_setpoints([{"type": "set_level_setpoint", "value": -5.0}])
    assert _detect_unsafe_level_setpoints([{"type": "set_level_setpoint", "value": 150.0}])
    assert not _detect_unsafe_level_setpoints([{"type": "set_level_setpoint", "value": 95.0}])
    assert not _detect_unsafe_level_setpoints([{"type": "set_level_setpoint", "value": 5.0}])
    # El limite viene SOLO de la configuracion: otro rango configurado cambia la decision; sin rango, no se inventa.
    monkeypatch.setattr(semantic_validator, "_load_pid_supervisor_config", lambda: {"level_setpoint": {"min": 10.0, "max": 90.0}})
    assert _detect_unsafe_level_setpoints([{"type": "set_level_setpoint", "value": 95.0}])
    monkeypatch.setattr(semantic_validator, "_load_pid_supervisor_config", lambda: {})
    assert not _detect_unsafe_level_setpoints([{"type": "set_level_setpoint", "value": 150.0}])


# P04 / P05 ----------------------------------------------------------------------------------------

def test_p04_high_level_alarm() -> None:
    _, project_ir = _build(
        "P04", "Activa una alarma si el nivel supera el 90 %.", [{"type": "high_level_alarm", "limit": 90.0}]
    )
    code = project_ir.pou.implementation_code
    assert "IF Level_PV > 90.0 THEN" in code
    assert "High_Level_Alarm := TRUE;" in code
    assert "Q_Alarm := TRUE;" in code
    assert verify_project_ir(project_ir)["is_valid"] is True


def test_p05_low_level_alarm() -> None:
    _, project_ir = _build(
        "P05", "Activa una alarma si el nivel baja del 10 %.", [{"type": "low_level_alarm", "limit": 10.0}]
    )
    code = project_ir.pou.implementation_code
    assert "IF Level_PV < 10.0 THEN" in code
    assert "Low_Level_Alarm := TRUE;" in code
    assert verify_project_ir(project_ir)["is_valid"] is True


# P06 --------------------------------------------------------------------------------------------

def test_p06_pid_enabled_only_in_automatic_mode() -> None:
    _, project_ir = _build(
        "P06", "Habilita el PID solamente cuando el sistema este en automatico.",
        [{"type": "set_auto_mode"}, {"type": "enable_pid"}]
    )
    code = project_ir.pou.implementation_code
    assert "PID_Enable := NOT I_Emergency AND Auto_Mode AND NOT Sensor_Fault AND NOT Safe_Stop;" in code
    assert verify_project_ir(project_ir)["is_valid"] is True


# P07 --------------------------------------------------------------------------------------------

def test_p07_emergency_disables_pid_and_pump() -> None:
    _, project_ir = _build("P07", "Desactiva el control PID si se activa la emergencia.", [{"type": "disable_pid"}])
    code = project_ir.pou.implementation_code
    # la prioridad de emergencia es el PRIMER bloque generado (incondicional, nunca debilitado)
    assert code.strip().splitlines()[1] == "IF I_Emergency THEN"
    emergency_block = code.split("END_IF;")[0]
    assert "PID_Enable := FALSE;" in emergency_block
    assert "Q_Pump_Enable := FALSE;" in emergency_block
    assert verify_project_ir(project_ir)["is_valid"] is True


# P08 --------------------------------------------------------------------------------------------

def test_p08_manual_mode_never_removes_safety_conditions() -> None:
    # manual_pump_limit es el nombre historico (alias) de manual_pump_enable: en Manual (= no Automatico) la bomba
    # sigue SOLO la orden manual del operador, siempre subordinada a la emergencia.
    semantic_output = _semantic_output("P08", "Permite operar la bomba en modo manual de forma limitada.",
                                       [{"type": "set_manual_mode"}, {"type": "manual_pump_limit"}])
    semantic_output["parameters"] = {"manual_pump_input": "I_Manual_Pump_Command"}
    pid_map = {"variables": PID_MAP["variables"] + [
        {"name": "I_Manual_Pump_Command", "class": "input", "type": "BOOL", "location": "%IX1.2"}]}
    project_ir = build_project_ir(semantic_output, pid_map, "SIEMENS_SCL_V18")
    project_ir.pou.implementation_code = generate_implementation_from_ir(project_ir)
    code = project_ir.pou.implementation_code
    assert "IF NOT Auto_Mode THEN" in code
    assert "Q_Pump_Enable := I_Manual_Pump_Command AND NOT I_Emergency" in code
    assert verify_project_ir(project_ir)["is_valid"] is True


# P09 --------------------------------------------------------------------------------------------

def test_p09_sensor_fault_detected_and_disables_pid() -> None:
    _, project_ir = _build(
        "P09", "Detecta un fallo de sensor si el valor de nivel esta fuera de rango.",
        [{"type": "sensor_range_fault"}, {"type": "enable_pid"}]
    )
    code = project_ir.pou.implementation_code
    assert "IF Level_PV < 0.0 OR Level_PV > 100.0 THEN" in code
    assert "Sensor_Fault := TRUE;" in code
    assert "NOT Sensor_Fault" in code  # participa en la formula de PID_Enable
    assert verify_project_ir(project_ir)["is_valid"] is True


# P10 --------------------------------------------------------------------------------------------

def test_p10_reset_only_when_no_fault_is_active() -> None:
    _, project_ir = _build(
        "P10", "Permite el reset de la alarma solo cuando la condicion de fallo haya desaparecido.",
        [{"type": "high_level_alarm"}, {"type": "low_level_alarm"}, {"type": "sensor_range_fault"}, {"type": "conditional_alarm_reset"}]
    )
    code = project_ir.pou.implementation_code
    assert "IF I_Reset AND NOT High_Level_Alarm AND NOT Low_Level_Alarm AND NOT Sensor_Fault THEN" in code
    assert verify_project_ir(project_ir)["is_valid"] is True


# P11 --------------------------------------------------------------------------------------------

def test_p11_overfill_triggers_safe_stop() -> None:
    _, project_ir = _build(
        "P11", "Detén de forma segura la bomba y genera una alarma si el tanque alcanza un nivel de sobrellenado.",
        [{"type": "safe_overfill_stop", "limit": 95.0}]
    )
    code = project_ir.pou.implementation_code
    assert "IF Level_PV >= 95.0 THEN" in code
    assert "Safe_Stop := TRUE;" in code
    assert "Q_Pump_Enable := FALSE;" in code
    assert "Q_Alarm := TRUE;" in code
    assert verify_project_ir(project_ir)["is_valid"] is True


# P12 (composicion completa) ------------------------------------------------------------------------

def test_p12_full_composition(io_map: dict, intents_catalog: dict, safety_rules: dict, tmp_path: Path) -> None:
    functional_requirements = [
        {"type": "set_auto_mode"},
        {"type": "set_level_setpoint", "value": 60.0},
        {"type": "enable_pid"},
        {"type": "high_level_alarm", "limit": 90.0},
        {"type": "safe_overfill_stop", "limit": 95.0},
        {"type": "conditional_alarm_reset"}
    ]
    semantic_output = _semantic_output(
        "P12",
        "Activa el modo automatico, establece el setpoint en 60 %, habilita el PID, genera alarma "
        "si el nivel supera el 90 % y detén todo de forma segura ante sobrellenado, permitiendo "
        "reset solo cuando la falla desaparezca.",
        functional_requirements
    )
    validation = validate_semantic_output(semantic_output, PID_MAP, intents_catalog, safety_rules)
    assert validation["is_valid"] is True

    result = generate_project_package(
        semantic_output, "SIEMENS_SCL_V18", PID_MAP, intents_catalog, safety_rules, output_dir=tmp_path
    )
    assert result["verification"]["is_valid"] is True
    package_dir = Path(result["package_dir"])
    scl = (package_dir / "siemens_source.scl").read_text(encoding="utf-8")
    for expected in ("Auto_Mode", "Level_SP", "PID_Enable", "High_Level_Alarm", "Safe_Stop"):
        assert expected in scl
    assert "PID_Compact" not in scl  # nunca redisena/instancia el bloque PID


# Cobertura semantica no marca P01-P12 como incompleta cuando los functional_requirements ya
# representan el comando (regresion del mecanismo de coberura para el dominio PID). --------------

def test_pid_coverage_recognizes_explicit_requirements(intents_catalog: dict) -> None:
    coverage = compute_semantic_coverage(
        command_text="Establece el nivel del tanque en 60 %.",
        intent_id="INT_PID_SUPERVISOR",
        functional_requirements=[{"type": "set_level_setpoint", "value": 60.0}],
        intents_catalog=intents_catalog
    )
    assert coverage["complete"] is True


# Variantes linguisticas V1/V2/V3 (seccion 34): al menos P02, P07, P11, P12. ------------------------

@pytest.fixture
def experiment_variants(project_root: Path) -> dict[str, Any]:
    payload = json.loads((project_root / "data" / "plc_maps" / "experiment_variants.json").read_text(encoding="utf-8"))
    return payload["variants"]


@pytest.mark.parametrize("case_id", ["P02", "P07", "P11", "P12"])
def test_pid_case_has_at_least_three_distinct_variants(experiment_variants: dict[str, Any], case_id: str) -> None:
    variants = experiment_variants[case_id]
    assert len(variants) >= 3
    commands = {entry["command"] for entry in variants}
    assert len(commands) == len(variants)  # cada variante expresa el comando de forma distinta


def test_all_twelve_pid_cases_have_variants(experiment_variants: dict[str, Any]) -> None:
    for index in range(1, 13):
        case_id = f"P{index:02d}"
        assert case_id in experiment_variants
        assert len(experiment_variants[case_id]) >= 3, f"{case_id} tiene menos de 3 variantes"


# Regresion de mapas/perfiles PID -------------------------------------------------------------------

def test_all_twelve_pid_profiles_exist(project_root: Path) -> None:
    from plc_maps.profiles import load_profiles
    profiles = {p["profile_id"]: p for p in load_profiles(project_root)}
    for index in range(1, 13):
        case_id = f"P{index:02d}"
        assert case_id in profiles, f"falta el perfil {case_id}"
        assert profiles[case_id]["case_id"] == case_id


def test_pid_readiness_uses_pid_maps_not_discrete_maps(project_root: Path) -> None:
    from plc_maps.profiles import get_profile, profile_readiness_summary
    profile = get_profile(project_root, "P11")
    readiness = profile_readiness_summary(project_root, profile)
    assert readiness["simulation_ready"] is True  # MAPA_PID_SIMULACION ya tiene Q_Pump_Enable/Q_Alarm
    assert readiness["hardware_ready"] is False  # banco fisico PID aun no confirmado (seccion 9)


def test_discrete_profile_readiness_is_unaffected_by_pid_maps(project_root: Path) -> None:
    """
    Confirma que agregar los mapas PID no rompio la seleccion de par de mapas D->discreto para
    D01 (_readiness_map_names). simulation_ready se comprueba contra MAPA_SIMULACION_COMPLETO
    (estable, no lo edita la GUI en uso normal); hardware_ready se comprueba con compute_readiness
    contra un snapshot congelado en vez del archivo mapa_banco_fisico.json real - ese archivo es
    mutable por diseno (el usuario lo reconfigura desde la GUI) y ya cambio de contenido durante
    esta sesion de trabajo, asi que no es una fuente estable para una aserción de regresion.
    """
    from plc_maps.profiles import compute_readiness, get_profile, profile_readiness_summary
    profile = get_profile(project_root, "D01")
    readiness = profile_readiness_summary(project_root, profile)
    assert readiness["simulation_ready"] is True

    d01_hardware_snapshot = {
        "I_Start", "I_Stop", "I_Emergency", "I_Reset", "I_Sensor1", "I_Mode_Manual", "I_Mode_Auto",
        "I_Maintenance", "Q_Motor_Enable", "Q_Alarm", "Q_Pilot_Run", "Q_Pilot_Fault", "Q_Aux_Output",
        "Q_Contactor_A", "Q_Contactor_B", "Q_Pilot_Stop"
    }
    hardware_ready, _ = compute_readiness(profile.get("allowed_variables", []), d01_hardware_snapshot)
    assert hardware_ready is True
