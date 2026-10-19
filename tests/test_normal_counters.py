"""
MODO NORMAL — contadores IEC CTU con salidas EXPLICITAS.

TIA Portal V18 rechazaba "#C_PulseCount.Q" ("Tag #C_PulseCount.Q not defined"): una instancia CTU_INT no tiene el
miembro Q (su salida se llama QU; Q es el nombre del PARAMETRO de la instruccion). Comprobado en TIA V18: ".QU"/".CV"
y la llamada con salidas "CTU(..., Q => done, CV => valor)" compilan; ".Q" no. El Modo Normal modela el contador como

    instancia C_<id> (CTU)  CU / R / PV  ->  Q => M_<id>_Done (BOOL), CV => M_<id>_CV (INT)

y la logica usa M_<id>_Done / M_<id>_CV, nunca miembros de la instancia. El verificador lo exige antes de TIA.
Experimentacion/formal-v1.1 conserva su plantilla congelada (los fallos historicos D09/D10 son resultados).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from code_generator import generate_implementation_from_ir
from ir_builder import build_project_ir
from plc_ir import PLCFunctionBlockInstance  # noqa: F401
from verifier import instance_member_errors, verify_project_ir

import llm_parser
from test_normal_mode_hardening import _Plc, _bench, _configs, _interpret, _llm, _program, _seq

INVALID_COUNTER_MEMBER = re.compile(r"#?C_[A-Za-z0-9_]+\.(Q|QU|CV)\b")
def _plc(result: dict[str, Any]) -> _Plc:
    return _Plc(result["scl"])  # _Plc traduce las salidas de llamada para el simulador congelado


def _counter_value(plc: _Plc, name: str) -> int:
    return int(plc.io.get(plc.machine.static_key(name), 0))


def _catalog_counter(tmp_path: Path, preset: int, output: str, reset: str | None = None,
                     command: str = "Cuenta cada pieza detectada y activa una salida al llegar a 5.") -> dict[str, Any]:
    parameters = {"pulse_input": "I_Piece_Sensor", "output": output, "preset": preset}
    if reset:
        parameters["reset_input"] = reset
    return _program(command, [], tmp_path, intent="INT_COUNTER_PULSES", parameters=parameters)


def _assert_explicit_counter(scl: str, instance: str = "C_PulseCount") -> None:
    assert not INVALID_COUNTER_MEMBER.search(scl), "acceso a miembro de un CTU (TIA V18 no tiene .Q)"
    declarations = scl[scl.index("VAR"):scl.index("BEGIN")]
    base = instance[2:]
    assert f"{instance} {{InstructionName := 'CTU_INT'; LibVersion := '1.0'}} : CTU_INT;" in declarations
    assert f"M_{base}_Done : Bool;" in declarations and f"M_{base}_CV : Int;" in declarations  # tipos explicitos
    assert f"Q => #M_{base}_Done, CV => #M_{base}_CV);" in scl


# ---------------------------------------------------------------------------------------------
# CTU1-CTU3: contador de catalogo (lo que elige el interprete para "cuenta ... y activa ...")
# ---------------------------------------------------------------------------------------------

def test_CTU1_count_pieces_and_activate_an_output_at_five(tmp_path):
    result = _catalog_counter(tmp_path, 5, "Q_Done_Lamp", reset="I_Reset")
    _assert_explicit_counter(result["scl"])
    assert result["package"]["verification"]["is_valid"] is True
    internal = {v["name"]: v["data_type"] for v in result["ir"]["pou"]["variables"]}
    assert (internal["C_PulseCount"], internal["M_PulseCount_Done"], internal["M_PulseCount_CV"]) == ("CTU", "BOOL", "INT")
    plc = _plc(result)
    for count in range(1, 5):
        plc.press("I_Piece_Sensor")
        assert not plc.on("Q_Done_Lamp") and _counter_value(plc, "M_PulseCount_CV") == count  # CV valido
    plc.press("I_Piece_Sensor")
    assert plc.on("Q_Done_Lamp") and _counter_value(plc, "M_PulseCount_CV") == 5  # Q valido


def test_CTU2_count_ten_pulses_and_activate_an_alarm(tmp_path):
    result = _catalog_counter(tmp_path, 10, "Q_Alarm", command="Cuenta 10 pulsos y activa una alarma.")
    _assert_explicit_counter(result["scl"])
    assert "PV := 10" in result["scl"] and "#Q_Alarm := #M_PulseCount_Done" in result["scl"]  # alarma <- done
    plc = _plc(result)
    for _ in range(9):
        plc.press("I_Piece_Sensor")
    assert not plc.on("Q_Alarm")
    plc.press("I_Piece_Sensor")
    assert plc.on("Q_Alarm")


def test_CTU3_reset_input_is_wired_to_R(tmp_path):
    result = _catalog_counter(tmp_path, 3, "Q_Done_Lamp", reset="I_Reset",
                              command="Cuenta piezas y reinicia el contador con Reset.")
    assert re.search(r"#C_PulseCount\(CU := #R_SensorPulse\.Q, R := #I_Reset OR FALSE, PV := 3,", result["scl"])
    plc = _plc(result)
    for _ in range(3):
        plc.press("I_Piece_Sensor")
    assert plc.on("Q_Done_Lamp")
    plc.press("I_Reset")
    assert not plc.on("Q_Done_Lamp") and _counter_value(plc, "M_PulseCount_CV") == 0
    plc.press("I_Piece_Sensor")
    assert _counter_value(plc, "M_PulseCount_CV") == 1  # vuelve a contar desde cero


# ---------------------------------------------------------------------------------------------
# CTU4-CTU5: contador componible (programa compuesto y dentro de una secuencia)
# ---------------------------------------------------------------------------------------------

def test_CTU4_counter_composed_with_other_logic(tmp_path):
    requirements = [{"type": "pulse_counter", "name": "Pieces", "count_input": "I_Piece_Sensor", "preset": 4,
                     "reset": "I_Reset", "outputs": ["Q_Box_Full"]},
                    {"type": "conditional_output", "condition": "I_Presence", "outputs": ["Q_Lamp"]}]
    result = _program("Cuenta 4 piezas para llenar la caja y mantén la lámpara encendida mientras haya presencia.",
                      requirements, tmp_path)
    _assert_explicit_counter(result["scl"], "C_Pieces")
    plc = _plc(result)
    plc.set(I_Presence=True)
    for _ in range(4):
        plc.press("I_Piece_Sensor")
    assert plc.on("Q_Box_Full", "Q_Lamp") == {"Q_Box_Full", "Q_Lamp"}
    plc.press("I_Reset")
    assert plc.on("Q_Box_Full", "Q_Lamp") == {"Q_Lamp"}


def test_CTU5_counter_inside_a_sequence_is_supported(tmp_path):
    requirements = [
        _seq([{"outputs": ["Q_Conveyor"], "advance_on": "M_Pieces_Done"}, {"outputs": ["Q_Packer"], "duration": "T#2s"}],
             start_input="I_Start", stop_input="I_Stop", repeat="once"),
        {"type": "pulse_counter", "name": "Pieces", "count_input": "I_Piece_Sensor", "preset": 3, "reset": "NOT M_Seq1_S1"},
    ]
    semantic = _interpret("x", _llm("x", requirements), _bench())
    assert not any("COMPOSITION_NOT_SUPPORTED" in e for e in semantic["semantic_validation"]["errors"])
    result = _program("Al pulsar Start mueve la cinta hasta contar 3 piezas y luego empaca 2 segundos.", requirements, tmp_path)
    _assert_explicit_counter(result["scl"], "C_Pieces")
    plc = _plc(result)
    plc.press("I_Piece_Sensor")  # fuera de la etapa de conteo: el contador esta en reinicio
    plc.press("I_Start")
    assert plc.on("Q_Conveyor", "Q_Packer") == {"Q_Conveyor"}
    for _ in range(3):
        plc.press("I_Piece_Sensor")
    plc.run(20)
    assert plc.on("Q_Conveyor", "Q_Packer") == {"Q_Packer"}
    plc.run(2100)
    assert plc.on("Q_Conveyor", "Q_Packer") == set()
    plc.press("I_Start")  # nuevo ciclo: el contador empezo de cero al volver a la etapa 1
    plc.press("I_Piece_Sensor")
    assert plc.on("Q_Conveyor", "Q_Packer") == {"Q_Conveyor"}


@pytest.mark.parametrize("counter, expected", [
    ({"type": "pulse_counter", "name": "Pieces", "count_input": "I_Piece_Sensor", "reset": "I_Reset"}, "hasta qué cantidad"),
    ({"type": "pulse_counter", "name": "Pieces", "count_input": "I_Piece_Sensor", "preset": 5, "outputs": ["Q_Alarm"]},
     "reiniciarse el contador"),
])
def test_incomplete_counter_asks_a_useful_question(counter, expected):
    question = _interpret("x", _llm("x", [counter]), _bench())["semantic_validation"]["clarification_question"]
    assert expected in question


# ---------------------------------------------------------------------------------------------
# CTU6: ningun acceso invalido a miembros; el verificador lo detecta antes de TIA
# ---------------------------------------------------------------------------------------------

def test_CTU6_verifier_rejects_member_access_that_tia_would_reject(tmp_path):
    result = _catalog_counter(tmp_path, 5, "Q_Done_Lamp", reset="I_Reset")
    semantic = result["semantic"]
    project_ir = build_project_ir(semantic, result["map"], "SIEMENS_SCL_V18")
    project_ir.pou.implementation_code = generate_implementation_from_ir(project_ir)
    assert instance_member_errors(project_ir) == []
    project_ir.pou.implementation_code += "Q_Done_Lamp := C_PulseCount.Q;\nQ_Done_Lamp := M_PulseCount_CV.Q;\n"
    errors = verify_project_ir(project_ir)["errors"]
    assert any(e.startswith("INVALID_INSTANCE_MEMBER: C_PulseCount.Q") and "CTU" in e for e in errors)
    assert any(e.startswith("INVALID_INSTANCE_MEMBER: M_PulseCount_CV.Q") and "no una instancia" in e for e in errors)


def test_CTU6_timer_and_edge_members_remain_valid(tmp_path):
    result = _program("Activa la salida 5 s.", [_seq([{"outputs": ["Q_Out"], "duration": "T#5s"}], start_input="I_Start")],
                      tmp_path)
    assert result["package"]["verification"]["is_valid"] is True  # T_x.Q de TON es portable


def test_formal_counter_template_is_frozen_without_the_normal_profile():
    """Sin perfil Normal (Experimentacion/formal-v1.1) la plantilla congelada no cambia: el fallo historico es un resultado."""
    catalog, safety = _configs()
    semantic = llm_parser._normalize_semantic_output(
        _llm("x", [], intent="INT_COUNTER_PULSES", parameters={"pulse_input": "I_Sensor1", "output": "Q_Alarm", "preset": 5,
                                                              "emergency_input": "FALSE"}), "x")
    io_map = _bench(inputs={"I_Sensor1": "%IX0.4"}, outputs={"Q_Alarm": "%QX0.3"})
    code = generate_implementation_from_ir(build_project_ir(semantic, io_map, "SIEMENS_SCL_V18"))
    assert "C_PulseCount.Q" in code and "Q =>" not in code
