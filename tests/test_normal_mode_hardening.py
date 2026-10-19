"""
MODO NORMAL endurecido — bateria de aceptacion (sin LLM real, sin TIA).

Cada caso parte de la respuesta ESTRUCTURADA que daria el interprete (inyectada: el LLM real no se llama) y
recorre la ruta de produccion completa: llm_parser.parse_with_mode (reparacion + semantica efectiva +
validacion, perfil Normal) -> IOAllocator -> IR -> SCL Siemens -> verificador. El comportamiento del SCL
generado se comprueba EN EL TIEMPO con el simulador SCL del proyecto (trial_experiments.scl_sim).

Matriz cubierta: marcha/paro, latch, timer, contador, alarma, reset, interlock, comparacion, histeresis,
secuencias de 2, 3 y >3 etapas, ciclo continuo, ciclo unico, branching por sensor, varias salidas a la vez,
semaforo, bomba/valvula, motor, recursos insuficientes, aclaracion real, aclaracion resuelta, contradiccion,
parafrasis (codificaciones equivalentes), asignacion automatica de E/S y variables internas.

Experimentacion/formal-v1.1 no se toca: sin perfil Normal la validacion y la asignacion son las de siempre.
"""
from __future__ import annotations

import copy
import inspect
import json
import re
from pathlib import Path
from typing import Any

import pytest

import functional_requirements as FR
import gui  # noqa: E402
import io_allocator
import llm_parser
import normal_interaction as NI
import semantic_validator
from code_generator import _generate_composed_program
from io_allocator import apply_assignments, propose_assignment
from project_packager import generate_project_package
from semantic_validator import validate_semantic_output
from trial_experiments.scl_sim import SclMachine
from utils import load_json_file

from test_execute_full_pipeline import temp_map, _tia_ready  # noqa: F401,E402
from test_experiment_working_io_map import _use_bench_copy  # noqa: E402
from test_normal_functional_composition import normal, _script  # noqa: F401,E402
from test_phase1_download_and_trials import pipeline  # noqa: F401,E402

_ROOT = Path(__file__).resolve().parents[1]
PUMP_VALVE = "Cuando se presione Start, enciende la bomba durante cinco segundos, luego apágala y enciende la válvula durante tres segundos."
PUMP_VALVE_PARAPHRASE = "Al pulsar marcha, activa la bomba 5 segundos; después detenla y abre la válvula 3 segundos."
_ADDRESS_WORDS = re.compile(r"%|\bQX|\bIX|direcci[oó]n|canal|\bQ\d|\bI\d", re.IGNORECASE)


# ---------------------------------------------------------------------------------------------
# Utilidades: mapa sintetico, interprete inyectado, generacion y simulacion
# ---------------------------------------------------------------------------------------------

def save_json_file(path: Path, data: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _channel(name: str, location: str, state: str) -> dict[str, Any]:
    analog = "W" in location
    return {"name": name, "class": "input" if location.startswith("%I") else "output", "type": "INT" if analog else "BOOL",
            "location": location, "initial_value": "0" if analog else "FALSE", "description": "", "aliases": [],
            "semantic_role": "", "llm_allowed": True, "safety_level": "normal", "unit": "", "min": None, "max": None,
            "comments": "", "state": state}


def _bench(outputs: dict[str, str] | None = None, inputs: dict[str, str] | None = None, free_do: int = 8, free_di: int = 6,
           free_ai: int = 2) -> dict[str, Any]:
    """Banco propio (nunca el mapa vivo): I_Start/I_Stop LOCKED, canales FREE y nombres existentes opcionales."""
    variables = [_channel("I_Start", "%IX0.0", "LOCKED"), _channel("I_Stop", "%IX0.1", "LOCKED")]
    used = {"%IX0.0", "%IX0.1"}
    for name, location in (inputs or {}).items():
        variables.append(_channel(name, location, "ASSIGNED"))
        used.add(location)
    for name, location in (outputs or {}).items():
        variables.append(_channel(name, location, "ASSIGNED"))
        used.add(location)
    free_inputs = [f"%IX1.{i}" for i in range(8)][:free_di]
    free_outputs = [f"%QX1.{i}" for i in range(8)][:free_do]
    variables += [_channel(f"I_Free_{i}", loc, "FREE") for i, loc in enumerate(free_inputs) if loc not in used]
    variables += [_channel(f"Q_Free_{i}", loc, "FREE") for i, loc in enumerate(free_outputs) if loc not in used]
    variables += [_channel(f"AI_IW{2 * i}", f"%IW{2 * i}", "FREE") for i in range(free_ai)]
    return {"schema_version": 1, "metadata": {"map_id": "test_normal_bench", "name": "TEST_NORMAL_BENCH", "version": 1},
            "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_"},
            "variables": variables, "history": []}


def _configs() -> tuple[dict, dict]:
    return load_json_file(_ROOT / "config" / "intents_catalog.json"), load_json_file(_ROOT / "config" / "safety_rules.json")


def _llm(command: str, requirements: list[dict[str, Any]], intent: str = "INT_UNKNOWN", parameters: dict | None = None,
         question: str | None = None, assumptions: list[str] | None = None) -> dict[str, Any]:
    """Respuesta estructurada del interprete (lo que devolveria el LLM)."""
    return {"intent_id": intent, "case_id": None, "command_text": command, "normalized_command": command.lower(),
            "parameters": dict(parameters or {}), "confidence": 0.95, "ambiguities": [],
            "requires_clarification": bool(question), "clarification_question": question,
            "assumptions": list(assumptions or []), "recognized_tags": [], "unrecognized_terms": [],
            "functional_requirements": copy.deepcopy(requirements)}


class _Client:
    def is_configured(self) -> bool:
        return True

    def interpret_command(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("el test nunca llama al LLM real")


def _interpret(command: str, llm: dict[str, Any], io_map: dict[str, Any], history: list[dict[str, str]] | None = None):
    catalog, safety = _configs()
    # parse_command: el MISMO punto de entrada que la GUI (incluye la extraccion de asignaciones explicitas).
    return llm_parser.parse_command(command, mode="llm", io_map=io_map, intents_catalog=catalog, safety_rules=safety,
                                      llm_client=_Client(), llm_response_text=copy.deepcopy(llm),
                                      interaction_profile="normal", clarification_history=history)


def _generate(semantic: dict[str, Any], io_map: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    """IOAllocator (aplica lo no bloqueado) -> revalidacion -> IR -> SCL Siemens -> verificador."""
    catalog, safety = _configs()
    validation = semantic["semantic_validation"]
    assert validation["is_valid"], validation
    proposals = [p for p in validation["io_assignment_proposals"] if not p.get("blocked")]
    updated = apply_assignments(copy.deepcopy(io_map), proposals, source="TEST")[0] if proposals else io_map
    semantic = {**semantic, "semantic_validation": validate_semantic_output(semantic, updated, catalog, safety)}
    assert semantic["semantic_validation"]["is_valid"], semantic["semantic_validation"]
    package = generate_project_package(semantic, "SIEMENS_SCL_V18", updated, catalog, safety, output_dir=tmp_path / "pkg")
    assert package["verification"]["is_valid"], package["verification"]["errors"]
    scl = (Path(package.get("package_dir") or tmp_path / "pkg") / "siemens_source.scl").read_text(encoding="utf-8")
    return {"package": package, "map": updated, "scl": scl, "proposals": proposals,
            "ir": package.get("project_ir") or {}}


def _program(command: str, requirements: list[dict[str, Any]], tmp_path: Path, io_map: dict[str, Any] | None = None,
             **llm_kwargs: Any) -> dict[str, Any]:
    io_map = io_map or _bench()
    semantic = _interpret(command, _llm(command, requirements, **llm_kwargs), io_map)
    validation = semantic["semantic_validation"]
    assert not validation["requires_clarification"], validation["clarification_question"]
    return {**_generate(semantic, io_map, tmp_path), "semantic": semantic}


_CALL_WITH_OUTPUTS = re.compile(r"^(?P<indent>\s*)(?P<target>#?[A-Za-z_]\w*)\((?P<args>.*)\);\s*$")
_OUTPUT_BINDING = re.compile(r",\s*(?P<formal>[A-Za-z_]\w*)\s*=>\s*(?P<actual>#?[A-Za-z_]\w*)")


def _simulable(scl: str) -> str:
    """
    El simulador SCL del proyecto (congelado con formal-v1.1) no acepta salidas en llamadas ("Q => x"), validas en TIA
    V18 e IEC. Para simular, cada llamada con salidas se reescribe a su equivalente IEC exacto: llamada + copia de las
    salidas de la instancia ("CTU(..., Q => a)" -> "CTU(...); a := CTU.Q;").
    """
    lines = []
    for line in scl.splitlines():
        match = _CALL_WITH_OUTPUTS.match(line)
        bindings = _OUTPUT_BINDING.findall(match.group("args")) if match else []
        if not bindings:
            lines.append(line)
            continue
        indent, target = match.group("indent"), match.group("target")
        lines.append(f"{indent}{target}({_OUTPUT_BINDING.sub('', match.group('args'))});")
        lines.extend(f"{indent}{actual} := {target}.{formal};" for formal, actual in bindings)
    return "\n".join(lines)


class _Plc:
    """PLC simulado sobre el SCL generado: entradas por tag, tiempo en ms, ciclo de 10 ms."""

    def __init__(self, scl: str) -> None:
        self.machine = SclMachine(_simulable(scl))
        self.io: dict[str, Any] = {}
        self.machine.initialize(self.io)
        self.history: list[dict[str, Any]] = []

    def set(self, **values: Any) -> None:
        self.io.update(values)

    def run(self, ms: float, watch: tuple[str, ...] = ()) -> None:
        for _ in range(int(round(ms / 10))):
            self.machine.scan(self.io, 10)
            if watch:
                self.history.append({tag: bool(self.io.get(tag)) for tag in watch})

    def press(self, tag: str, ms: float = 50) -> None:
        self.set(**{tag: True})
        self.run(ms)
        self.set(**{tag: False})
        self.run(10)

    def on(self, *tags: str) -> set[str]:
        return {tag for tag in tags if self.io.get(tag)}


def _trace(scl: str, outputs: tuple[str, ...], start: str = "I_Start") -> list[tuple[int, frozenset]]:
    """Firma temporal (cada 500 ms durante 12 s) de una secuencia disparada por `start`."""
    plc = _Plc(scl)
    plc.run(200)
    plc.press(start)
    samples = []
    for t in range(0, 12000, 500):
        samples.append((t, frozenset(i for i, tag in enumerate(outputs) if plc.io.get(tag))))
        plc.run(500)
    return samples


def _seq(steps: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    return {"type": "timed_sequence", **fields, "steps": steps}


# ---------------------------------------------------------------------------------------------
# CASO A / B: el comando reportado y su parafrasis
# ---------------------------------------------------------------------------------------------

# Respuesta EXACTA del interprete en la ejecucion reportada (2026-10-15 12:23): etapa final vacia = "todo apagado".
INCIDENT_REQUIREMENTS = [
    _seq([{"outputs": ["Q_Pump_Enable"], "duration": "T#5s"}, {"outputs": ["Q_Valve_Enable"], "duration": "T#3s"},
          {"outputs": []}], start_input="I_Start"),
    {"type": "never_together", "outputs": ["Q_Pump_Enable", "Q_Valve_Enable"]},
]


def test_A_reported_command_needs_no_clarification_and_reaches_scl(tmp_path):
    result = _program(PUMP_VALVE, INCIDENT_REQUIREMENTS, tmp_path)
    semantic, validation = result["semantic"], result["semantic"]["semantic_validation"]
    assert validation["requires_clarification"] is False and validation["clarification_question"] is None
    assert semantic["intent_id"] == "INT_UNKNOWN" and validation["is_valid"]  # programa compuesto: no es un error
    sequence = FR.detect_timed_sequences(semantic["functional_requirements"])[0]
    assert sequence["start_input"] == "I_Start"
    assert [(s["outputs"], s["duration"]) for s in FR.timed_sequence_steps(sequence)] == [
        (["Q_Pump_Enable"], "T#5s"), (["Q_Valve_Enable"], "T#3s")]
    assert FR.timed_sequence_repeat(sequence) == ("once", "INFERRED")
    # IOAllocator: reutiliza I_Start y asigna las DO libres mas bajas, deterministicamente
    assert {(p["proposed_name"], p["address"]) for p in result["proposals"]} == {
        ("Q_Pump_Enable", "%QX1.0"), ("Q_Valve_Enable", "%QX1.1")}
    internal = {v["name"] for v in result["ir"]["metadata"]["generated_internal_variables"]}
    assert {"M_Seq1_S1", "M_Seq1_S2", "T_Seq1_S1", "T_Seq1_S2", "M_Seq1_StartPrev"} <= internal

    plc = _Plc(result["scl"])
    plc.run(500)
    assert plc.on("Q_Pump_Enable", "Q_Valve_Enable") == set()  # estado inicial seguro, sin autoarranque
    plc.press("I_Start")
    assert plc.on("Q_Pump_Enable", "Q_Valve_Enable") == {"Q_Pump_Enable"}
    plc.run(4800)
    assert plc.on("Q_Pump_Enable", "Q_Valve_Enable") == {"Q_Pump_Enable"}
    plc.run(300)
    assert plc.on("Q_Pump_Enable", "Q_Valve_Enable") == {"Q_Valve_Enable"}
    plc.run(3100)
    assert plc.on("Q_Pump_Enable", "Q_Valve_Enable") == set()  # FIN: todo apagado
    plc.run(10000)
    assert plc.on("Q_Pump_Enable", "Q_Valve_Enable") == set()  # y permanece en reposo


def test_A_start_held_down_never_restarts_and_stop_has_priority(tmp_path):
    result = _program(PUMP_VALVE, [_seq(INCIDENT_REQUIREMENTS[0]["steps"], start_input="I_Start", stop_input="I_Stop"),
                                   INCIDENT_REQUIREMENTS[1]], tmp_path)
    plc = _Plc(result["scl"])
    plc.set(I_Start=True)
    plc.run(9000)  # pulsador mantenido durante toda la secuencia y despues
    assert plc.on("Q_Pump_Enable", "Q_Valve_Enable") == set()  # no hay rearranque automatico
    plc.set(I_Start=False)
    plc.run(100)
    plc.press("I_Start")
    assert plc.on("Q_Pump_Enable") == {"Q_Pump_Enable"}
    plc.set(I_Stop=True)
    plc.run(20)
    assert plc.on("Q_Pump_Enable", "Q_Valve_Enable") == set()  # Stop prioritario
    plc.set(I_Start=True)
    plc.run(100)
    assert plc.on("Q_Pump_Enable", "Q_Valve_Enable") == set()  # Start no gana mientras Stop esta activo


@pytest.mark.parametrize("encoding", ["final_duration", "explicit_once", "actions_on_off"])
def test_B_paraphrase_and_equivalent_encodings_give_identical_plc_behavior(tmp_path, encoding):
    """La parafrasis puede llegar con otros nombres y otra forma equivalente: el comportamiento es el mismo."""
    reference = _program(PUMP_VALVE, INCIDENT_REQUIREMENTS, tmp_path / "ref")
    if encoding == "final_duration":
        sequence = _seq([{"outputs": ["Q_Pump"], "duration": "T#5s"}, {"outputs": ["Q_Valve"], "duration": "3s"}],
                        start_input="I_Start")
    elif encoding == "explicit_once":
        sequence = _seq([{"outputs": ["Q_Pump"], "duration": "T#5s"}, {"outputs": ["Q_Valve"], "duration": "T#3s"}],
                        start_input="I_Start", repeat="single_cycle")
    else:
        sequence = _seq([{"actions": [{"output": "Q_Pump", "state": True}, {"output": "Q_Valve", "state": False}], "duration": "T#5s"},
                         {"actions": [{"output": "Q_Pump", "state": "OFF"}, {"output": "Q_Valve", "state": "ON"}], "duration": "T#3s"}],
                        start_input="I_Start")
    paraphrase = _program(PUMP_VALVE_PARAPHRASE, [sequence], tmp_path / "para")
    assert _trace(reference["scl"], ("Q_Pump_Enable", "Q_Valve_Enable")) == _trace(paraphrase["scl"], ("Q_Pump", "Q_Valve"))


# ---------------------------------------------------------------------------------------------
# CASO C / E: aclaracion real, util y resuelta (sin bucles)
# ---------------------------------------------------------------------------------------------

UNDERSPECIFIED = [_seq([{"outputs": ["Q_Pump"]}, {"outputs": ["Q_Valve"]}])]


def test_C_underspecified_sequence_asks_one_useful_functional_question():
    semantic = _interpret("Haz una secuencia con la bomba y la válvula.", _llm("x", UNDERSPECIFIED), _bench())
    validation = semantic["semantic_validation"]
    question = validation["clarification_question"]
    assert validation["requires_clarification"] is True and validation["is_valid"] is False
    assert "iniciar la secuencia" in question and question.count("?") == 1  # UNA pregunta: primero el disparo
    assert not NI.is_internal_message(question) and not _ADDRESS_WORDS.search(question)
    # con el disparo ya indicado, la siguiente pregunta es el tiempo de la etapa 1 (no se repite la anterior)
    answered = _interpret("x", _llm("x", [_seq(UNDERSPECIFIED[0]["steps"], start_input="I_Start")]), _bench())
    follow_up = answered["semantic_validation"]["clarification_question"]
    assert "etapa 1" in follow_up and "Pump" in follow_up and "Cuánto tiempo" in follow_up


def test_E_parser_integrates_an_already_answered_question_with_one_corrective_pass(monkeypatch):
    history = [{"question": "¿Cuánto tiempo debe permanecer activa la etapa 1 (Pump) antes de pasar a la siguiente (Valve)?",
                "answer": "5 segundos"}]
    repeated = _llm("x", [_seq([{"outputs": ["Q_Pump"]}, {"outputs": ["Q_Valve"], "duration": "T#3s"}], start_input="I_Start")])
    complete = _llm("x", [_seq([{"outputs": ["Q_Pump"], "duration": "T#5s"}, {"outputs": ["Q_Valve"], "duration": "T#3s"}],
                               start_input="I_Start")])
    calls: list[dict[str, Any]] = []

    def _invoke(command_text, llm_client, context, llm_response_text):
        calls.append(dict(context))
        response = repeated if len(calls) == 1 else complete
        return llm_parser._normalize_semantic_output(copy.deepcopy(response), command_text), {}

    monkeypatch.setattr(llm_parser, "_invoke_llm", _invoke)
    catalog, safety = _configs()
    result = llm_parser.parse_with_mode("x", mode="llm", io_map=_bench(), intents_catalog=catalog, safety_rules=safety,
                                        llm_client=_Client(), interaction_profile="normal", clarification_history=history)
    assert len(calls) == 2 and "5 segundos" in calls[1]["correction_note"]  # la respuesta se integra explicitamente
    assert result["semantic_validation"]["is_valid"] and not result["semantic_validation"]["requires_clarification"]


def test_E_a_question_repeated_twice_never_loops(monkeypatch):
    history = [{"question": "¿Cuánto tiempo debe permanecer activa la etapa 1 (Pump) antes de pasar a la siguiente (Valve)?",
                "answer": "no sé"}]
    repeated = _llm("x", [_seq([{"outputs": ["Q_Pump"]}, {"outputs": ["Q_Valve"], "duration": "T#3s"}], start_input="I_Start")])
    calls: list[int] = []

    def _invoke(command_text, llm_client, context, llm_response_text):
        calls.append(1)
        return llm_parser._normalize_semantic_output(copy.deepcopy(repeated), command_text), {}

    monkeypatch.setattr(llm_parser, "_invoke_llm", _invoke)
    catalog, safety = _configs()
    result = llm_parser.parse_with_mode("x", mode="llm", io_map=_bench(), intents_catalog=catalog, safety_rules=safety,
                                        llm_client=_Client(), interaction_profile="normal", clarification_history=history)
    assert len(calls) == 2  # una sola pasada correctiva, nunca un bucle
    assert NI.classify_clarification(result["clarification_question"], history)["action"] == "repeated"


def test_E_gui_answered_clarification_is_resolved_and_processing_continues(normal, monkeypatch, tmp_path):
    app, state = normal["app"], normal["state"]
    bench = tmp_path / "bench.json"
    save_json_file(bench, _bench())
    _use_bench_copy(app, bench)
    io_map = load_json_file(bench)
    missing = _interpret(PUMP_VALVE, _llm(PUMP_VALVE, [_seq([{"outputs": ["Q_Pump"]}, {"outputs": ["Q_Valve"], "duration": "T#3s"}],
                                                          start_input="I_Start")]), io_map)
    complete = _interpret(PUMP_VALVE, _llm(PUMP_VALVE, [_seq([{"outputs": ["Q_Pump"], "duration": "T#5s"},
                                                              {"outputs": ["Q_Valve"], "duration": "T#3s"}], start_input="I_Start")]), io_map)
    logs: list[str] = []
    monkeypatch.setattr(app, "_log", lambda message, *a, **k: logs.append(str(message)))
    state["answers"] = ["5 segundos"]
    _script(monkeypatch, state, [missing, complete])
    assert app.process_command() is True
    assert len(state["dialogs"]) == 1 and "etapa 1" in state["dialogs"][0]
    assert state["calls"][1]["clarification_history"] == [{"question": state["dialogs"][0], "answer": "5 segundos"}]
    assert any(line.startswith("[NORMAL_CLARIFICATION_REQUIRED]") for line in logs)
    assert any(line.startswith("[NORMAL_CLARIFICATION_RESOLVED]") and "5 segundos" in line for line in logs)
    assert any(line.startswith("[NORMAL_IO_PROVISIONAL]") and "Q_Pump@%QX1.0" in line for line in logs)


# ---------------------------------------------------------------------------------------------
# CASO D / F / G / H: recursos fisicos y variables internas
# ---------------------------------------------------------------------------------------------

def test_D_insufficient_outputs_is_a_capability_gap_not_a_question():
    io_map = _bench(outputs={"Q_Motor_Enable": "%QX1.1", "Q_Alarm": "%QX1.2"}, free_do=1)
    semantic = _interpret(PUMP_VALVE, _llm(PUMP_VALVE, INCIDENT_REQUIREMENTS), io_map)
    validation = semantic["semantic_validation"]
    gap = validation["capability_gap"]
    assert validation["requires_clarification"] is False and validation["clarification_question"] is None
    assert validation["is_valid"] is False and gap["code"] == "SYSTEM_CAPABILITY_GAP"
    assert gap["shortages"] == [{"channel_class": "DO", "required": 2, "available": 1,
                                 "resources": ["Q_Pump_Enable", "Q_Valve_Enable"], "message": gap["message"]}]
    assert "Se requieren 2 DO compatibles y actualmente hay 1 disponible" in gap["message"]
    # un canal ASSIGNED a otra funcion nunca se toma para cubrir la falta
    assert all(p["address"] not in ("%QX1.1", "%QX1.2") for p in validation["io_assignment_proposals"])


def test_D_gui_reports_the_gap_without_dialog_and_without_touching_the_map(normal, monkeypatch, tmp_path):
    app, state = normal["app"], normal["state"]
    bench = tmp_path / "bench.json"
    save_json_file(bench, _bench(outputs={"Q_Motor_Enable": "%QX1.1"}, free_do=1))
    _use_bench_copy(app, bench)
    before = [(v["name"], v["location"], v["state"]) for v in load_json_file(bench)["variables"]]
    semantic = _interpret(PUMP_VALVE, _llm(PUMP_VALVE, INCIDENT_REQUIREMENTS), load_json_file(bench))
    logs: list[str] = []
    monkeypatch.setattr(app, "_log", lambda message, *a, **k: logs.append(str(message)))
    _script(monkeypatch, state, [semantic])
    assert app.process_command() is False
    assert state["dialogs"] == []  # nunca "¿que salida desea usar?"
    assert any("SYSTEM_CAPABILITY_GAP" in m and "Se requieren 2 DO" in m for m in state["errors"])
    assert any(line.startswith("[NORMAL_CAPABILITY_GAP]") for line in logs)
    assert [(v["name"], v["location"], v["state"]) for v in load_json_file(bench)["variables"]] == before  # sin asignacion parcial


def test_D_semantics_are_clarified_before_reporting_missing_hardware():
    semantic = _interpret("x", _llm("x", UNDERSPECIFIED), _bench(free_do=0))
    validation = semantic["semantic_validation"]
    assert validation["capability_gap"] and validation["requires_clarification"]  # la GUI pregunta primero


def test_F_existing_compatible_variables_are_reused(tmp_path):
    io_map = _bench(outputs={"Q_Pump": "%QX0.3", "Q_Valve": "%QX0.5"})
    result = _program(PUMP_VALVE, [_seq([{"outputs": ["Q_Pump"], "duration": "T#5s"}, {"outputs": ["Q_Valve"], "duration": "T#3s"}],
                                        start_input="I_Start")], tmp_path, io_map=io_map)
    assert result["proposals"] == []  # nada que asignar: todo existe con ese nombre
    located = {v["name"]: v["location"] for v in result["map"]["variables"]}
    assert (located["I_Start"], located["Q_Pump"], located["Q_Valve"]) == ("%IX0.0", "%QX0.3", "%QX0.5")


def test_G_missing_outputs_get_free_channels_deterministically_and_assigned_ones_are_respected():
    io_map = _bench(outputs={"Q_Motor_Enable": "%QX1.0"})  # el canal mas bajo esta ASSIGNED a otra funcion
    first = _interpret(PUMP_VALVE, _llm(PUMP_VALVE, INCIDENT_REQUIREMENTS), io_map)
    second = _interpret(PUMP_VALVE, _llm(PUMP_VALVE, INCIDENT_REQUIREMENTS), copy.deepcopy(io_map))
    allocation = [(p["proposed_name"], p["address"], p["current_state"]) for p in first["semantic_validation"]["io_assignment_proposals"]]
    assert allocation == [("Q_Pump_Enable", "%QX1.1", "FREE"), ("Q_Valve_Enable", "%QX1.2", "FREE")]
    assert allocation == [(p["proposed_name"], p["address"], p["current_state"])
                          for p in second["semantic_validation"]["io_assignment_proposals"]]


def test_H_internal_resources_are_generated_without_physical_addresses(tmp_path):
    result = _program(PUMP_VALVE, INCIDENT_REQUIREMENTS, tmp_path)
    variables = result["ir"]["pou"]["variables"]
    internal = [v for v in variables if v["name"].startswith(("M_", "T_"))]
    assert internal and all(not v.get("location") for v in internal)
    assert {v["name"] for v in internal} >= {"M_Seq1_S1", "T_Seq1_S1", "M_Seq1_StartPrev"}
    mapped = {v["name"] for v in result["map"]["variables"]}
    assert not any(name.startswith(("M_Seq", "T_Seq")) for name in mapped)  # nunca consumen E/S ni entran al mapa


# ---------------------------------------------------------------------------------------------
# CASO I: comandos simples anteriores (catalogo) siguen funcionando en Modo Normal
# ---------------------------------------------------------------------------------------------

def test_I_start_stop_motor_still_generates(tmp_path):
    result = _program("Enciende el motor con Start y apágalo con Stop.", [], tmp_path, intent="INT_MOTOR_START_STOP",
                      parameters={"trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable"})
    plc = _Plc(result["scl"])
    plc.press("I_Start")
    assert plc.on("Q_Motor_Enable")
    plc.press("I_Stop")
    assert not plc.on("Q_Motor_Enable")


def test_I_timed_auto_stop_still_generates(tmp_path):
    result = _program("Enciende el motor con Start y apágalo automáticamente después de 10 segundos.", [], tmp_path,
                      intent="INT_AUTO_STOP_TIMER",
                      parameters={"trigger_input": "I_Start", "motor_output": "Q_Motor_Enable", "operation_time": "T#10s"})
    assert "T#10s" in result["scl"]
    plc = _Plc(result["scl"])
    plc.press("I_Start")
    assert plc.on("Q_Motor_Enable")
    plc.run(10100)
    assert not plc.on("Q_Motor_Enable")


def test_I_alarm_set_by_fault_and_cleared_by_reset(tmp_path):
    result = _program("Activa una alarma cuando se presione fallo y apágala con Reset.",
                      [{"type": "latch", "set": "I_Fault", "reset": "I_Reset", "outputs": ["Q_Alarm"]}], tmp_path)
    plc = _Plc(result["scl"])
    plc.press("I_Fault")
    plc.run(1000)
    assert plc.on("Q_Alarm")  # enclavada
    plc.press("I_Reset")
    assert not plc.on("Q_Alarm")
    plc.set(I_Fault=True, I_Reset=True)
    plc.run(50)
    assert not plc.on("Q_Alarm")  # reset prioritario


def test_latch_without_reset_asks_how_to_release_it():
    semantic = _interpret("x", _llm("x", [{"type": "latch", "set": "I_Fault", "outputs": ["Q_Alarm"]}]), _bench())
    question = semantic["semantic_validation"]["clarification_question"]
    assert "desactivarse" in question and not _ADDRESS_WORDS.search(question)


# ---------------------------------------------------------------------------------------------
# Semaforos S1-S5 (misma arquitectura que cualquier otra secuencia)
# ---------------------------------------------------------------------------------------------

LIGHTS = ("Q_Green", "Q_Yellow", "Q_Red")
_EXCLUSIVE = {"type": "never_together", "outputs": list(LIGHTS)}


def _lights(durations: tuple[str, str, str], **fields: Any) -> list[dict[str, Any]]:
    return [_seq([{"outputs": [light], "duration": d} for light, d in zip(LIGHTS, durations)], **fields), _EXCLUSIVE]


def _phase(plc: _Plc) -> set[str]:
    return plc.on(*LIGHTS)


def test_S1_continuous_cycle_without_trigger(tmp_path):
    result = _program("Enciende verde durante 10 segundos, luego amarillo durante 3 segundos y después rojo durante 10 "
                      "segundos. Repite la secuencia continuamente.", _lights(("T#10s", "T#3s", "T#10s"), repeat="continuous"),
                      tmp_path)
    inferences = result["semantic"]["semantic_validation"]["inferences"]
    assert {"field": "secuencia 1.trigger", "value": "AUTO", "provenance": "INFERRED"}.items() <= next(
        i for i in inferences if i["field"] == "secuencia 1.trigger").items()
    assert len([p for p in result["proposals"] if p["address"].startswith("%QX")]) == 3
    plc = _Plc(result["scl"])
    plc.run(100, watch=LIGHTS)
    assert _phase(plc) == {"Q_Green"}
    plc.run(10000, watch=LIGHTS)
    assert _phase(plc) == {"Q_Yellow"}
    plc.run(3000, watch=LIGHTS)
    assert _phase(plc) == {"Q_Red"}
    plc.run(10000, watch=LIGHTS)
    assert _phase(plc) == {"Q_Green"}  # vuelve a la etapa 1
    plc.run(46000, watch=LIGHTS)  # dos ciclos mas
    assert all(sum(sample.values()) == 1 for sample in plc.history)  # nunca dos colores a la vez, nunca apagado


def test_S2_start_triggered_cycle_returns_to_green(tmp_path):
    result = _program("Cuando pulse Start, pon el semáforo en verde 8 segundos, luego amarillo 2 segundos y rojo 10 "
                      "segundos. Después vuelve a verde.", _lights(("T#8s", "T#2s", "T#10s"), start_input="I_Start",
                                                                   repeat="continuous"), tmp_path)
    plc = _Plc(result["scl"])
    plc.run(2000)
    assert _phase(plc) == set()  # sin disparo no arranca
    plc.press("I_Start")
    assert _phase(plc) == {"Q_Green"}
    plc.run(8000)
    assert _phase(plc) == {"Q_Yellow"}
    plc.run(2000)
    assert _phase(plc) == {"Q_Red"}
    plc.run(10000)
    assert _phase(plc) == {"Q_Green"}


def test_S3_traffic_light_without_times_asks_about_durations_not_addresses():
    semantic = _interpret("Controla el semáforo por tiempo.",
                          _llm("x", [_seq([{"outputs": [light]} for light in LIGHTS], repeat="continuous"), _EXCLUSIVE]), _bench())
    question = semantic["semantic_validation"]["clarification_question"]
    assert semantic["semantic_validation"]["requires_clarification"] is True
    assert "Cuánto tiempo" in question and not _ADDRESS_WORDS.search(question)


def test_S4_inferred_units_are_recorded_and_need_no_clarification(tmp_path):
    result = _program("Haz un semáforo normal: verde 10 segundos, amarillo 3 y rojo 10.",
                      _lights(("T#10s", "T#3s", "T#10s"), repeat="continuous"), tmp_path,
                      assumptions=["INFERRED: '3' y '10' sin unidad se interpretan en segundos por el contexto temporal."])
    assert any(a.startswith("INFERRED") for a in result["semantic"]["assumptions"])
    provenance = {i["field"]: i["provenance"] for i in result["semantic"]["semantic_validation"]["inferences"]}
    assert provenance["secuencia 1.trigger"] == "INFERRED" and "secuencia 1.repeat" not in provenance  # repeat fue explicito


def test_S5_single_run_ends_with_everything_off(tmp_path):
    result = _program("Verde 10 segundos, amarillo 3 segundos, rojo 10 segundos, pero no repitas.",
                      _lights(("T#10s", "T#3s", "T#10s"), start_input="I_Start", repeat="once"), tmp_path)
    plc = _Plc(result["scl"])
    plc.press("I_Start")
    plc.run(23200)
    assert _phase(plc) == set()
    plc.run(30000)
    assert _phase(plc) == set()  # una sola ejecucion; estado final seguro


def test_several_exclusive_pairs_are_independent_instances_not_conflicts(tmp_path):
    """Varios never_together/secuencias en un mismo programa: antes provocaban TypeError en la deteccion de conflictos."""
    requirements = [_seq([{"outputs": [light], "duration": "T#2s"} for light in LIGHTS], repeat="continuous"),
                    {"type": "never_together", "outputs": ["Q_Green", "Q_Yellow"]},
                    {"type": "never_together", "outputs": ["Q_Yellow", "Q_Red"]},
                    {"type": "never_together", "outputs": ["Q_Green", "Q_Red"]}]
    result = _program("x", requirements, tmp_path)
    assert result["semantic"]["semantic_validation"]["functional_requirement_conflicts"] == []


def test_contradiction_is_reported_not_guessed():
    contradictory = [_seq([{"outputs": ["Q_Red", "Q_Green"], "duration": "T#5s"}], start_input="I_Start"),
                     {"type": "never_together", "outputs": ["Q_Red", "Q_Green"]}]
    semantic = _interpret("Enciende rojo y verde al mismo tiempo y asegúrate de que nunca estén encendidos simultáneamente.",
                          _llm("x", contradictory), _bench())
    validation = semantic["semantic_validation"]
    assert validation["requires_clarification"] is True and validation["is_valid"] is False
    assert "contradictorio" in validation["clarification_question"] and "Q_Red" in validation["clarification_question"]
    assert any(c["type"] == "never_together_violation" for c in validation["functional_requirement_conflicts"])


# ---------------------------------------------------------------------------------------------
# Generalizacion G1-G9, branching y secuencias de N etapas
# ---------------------------------------------------------------------------------------------

def test_G1_staggered_start_holds_until_stop(tmp_path):
    result = _program("Al pulsar Start enciende Motor A. Cinco segundos después enciende Motor B. Al pulsar Stop apaga ambos.",
                      [_seq([{"outputs": ["Q_Motor_A"], "duration": "T#5s"}, {"outputs": ["Q_Motor_A", "Q_Motor_B"]}],
                            start_input="I_Start", stop_input="I_Stop")], tmp_path)
    plc = _Plc(result["scl"])
    plc.press("I_Start")
    assert plc.on("Q_Motor_A", "Q_Motor_B") == {"Q_Motor_A"}
    plc.run(5100)
    assert plc.on("Q_Motor_A", "Q_Motor_B") == {"Q_Motor_A", "Q_Motor_B"}  # varias salidas a la vez
    plc.run(60000)
    assert plc.on("Q_Motor_A", "Q_Motor_B") == {"Q_Motor_A", "Q_Motor_B"}  # hold_last
    plc.press("I_Stop")
    assert plc.on("Q_Motor_A", "Q_Motor_B") == set()


def test_hold_last_without_any_stop_asks_how_to_stop():
    semantic = _interpret("x", _llm("x", [_seq([{"outputs": ["Q_Motor_A"], "duration": "T#5s"}, {"outputs": ["Q_Motor_B"]}],
                                               start_input="I_Start")]), _bench())
    question = semantic["semantic_validation"]["clarification_question"]
    assert "indefinidamente" in question and "detenerse" in question


def test_G2_piece_counter_activates_alarm_at_preset(tmp_path):
    result = _program("Cuenta las piezas detectadas por el sensor y activa una alarma cuando lleguen a 20.", [], tmp_path,
                      intent="INT_COUNTER_PULSES", parameters={"pulse_input": "I_Piece_Sensor", "output": "Q_Alarm", "preset": 20},
                      io_map=_bench(inputs={"I_Piece_Sensor": "%IX0.6"}))
    plc = _Plc(result["scl"])
    for _ in range(19):
        plc.press("I_Piece_Sensor")
    assert not plc.on("Q_Alarm")
    plc.press("I_Piece_Sensor")
    assert plc.on("Q_Alarm")


def test_G3_and_condition_pulses_a_valve(tmp_path):
    result = _program("Si Sensor_A y Sensor_B están activos, abre la válvula durante 4 segundos.",
                      [{"type": "conditional_output", "condition": "I_Sensor_A AND I_Sensor_B", "outputs": ["Q_Valve"],
                        "duration": "T#4s"}], tmp_path)
    plc = _Plc(result["scl"])
    plc.set(I_Sensor_A=True)
    plc.run(500)
    assert not plc.on("Q_Valve")  # AND: falta B
    plc.set(I_Sensor_B=True)
    plc.run(100)
    assert plc.on("Q_Valve")
    plc.run(4000)
    assert not plc.on("Q_Valve")  # pulso de 4 s aunque la condicion siga activa


def test_G4_high_level_forces_pump_off_immediately_and_ends_the_sequence(tmp_path):
    result = _program("Al pulsar Start enciende la bomba 30 segundos. Si se activa nivel alto apaga inmediatamente la bomba "
                      "aunque el temporizador no haya terminado.",
                      [_seq([{"outputs": ["Q_Pump"], "duration": "T#30s"}], start_input="I_Start"),
                       {"type": "force_off", "condition": "I_Level_High", "outputs": ["Q_Pump"]}], tmp_path)
    plc = _Plc(result["scl"])
    plc.press("I_Start")
    plc.run(3000)
    plc.set(I_Level_High=True)
    plc.run(20)
    assert not plc.on("Q_Pump")
    plc.set(I_Level_High=False)
    plc.run(5000)
    assert not plc.on("Q_Pump")  # no se re-energiza sola al despejarse la condicion


def test_G5_alternates_two_pumps_while_auto_mode_is_active(tmp_path):
    result = _program("Alterna dos bombas cada 30 segundos mientras esté activo el modo automático.",
                      [_seq([{"outputs": ["Q_Pump_1"], "duration": "T#30s"}, {"outputs": ["Q_Pump_2"], "duration": "T#30s"}],
                            mode_condition="I_Mode_Auto", repeat="continuous"),
                       {"type": "never_together", "outputs": ["Q_Pump_1", "Q_Pump_2"]}], tmp_path,
                      io_map=_bench(inputs={"I_Mode_Auto": "%IX0.2"}))
    plc = _Plc(result["scl"])
    plc.run(1000)
    assert plc.on("Q_Pump_1", "Q_Pump_2") == set()
    plc.set(I_Mode_Auto=True)
    plc.run(100)
    assert plc.on("Q_Pump_1", "Q_Pump_2") == {"Q_Pump_1"}
    plc.run(30000)
    assert plc.on("Q_Pump_1", "Q_Pump_2") == {"Q_Pump_2"}
    plc.run(30000)
    assert plc.on("Q_Pump_1", "Q_Pump_2") == {"Q_Pump_1"}
    plc.set(I_Mode_Auto=False)
    plc.run(20)
    assert plc.on("Q_Pump_1", "Q_Pump_2") == set()


def test_G6_each_piece_triggers_one_cylinder_stroke(tmp_path):
    result = _program("Cuando llegue una pieza, activa el cilindro 2 segundos, retíralo y espera la siguiente pieza.",
                      [_seq([{"outputs": ["Q_Cylinder"], "duration": "T#2s"}], start_input="I_Piece_Sensor", repeat="once")],
                      tmp_path, io_map=_bench(inputs={"I_Piece_Sensor": "%IX0.6"}))
    plc = _Plc(result["scl"])
    plc.set(I_Piece_Sensor=True)
    plc.run(100)
    assert plc.on("Q_Cylinder")
    plc.run(5000)
    assert not plc.on("Q_Cylinder")  # pieza aun presente: un solo golpe
    plc.set(I_Piece_Sensor=False)
    plc.run(100)
    plc.press("I_Piece_Sensor")
    assert plc.on("Q_Cylinder")  # la siguiente pieza dispara otro


def test_G7_and_more_than_three_steps_end_with_everything_off(tmp_path):
    outputs = ("Q_Pump", "Q_Valve", "Q_Motor", "Q_Mixer", "Q_Heater")
    steps = [{"outputs": [o], "duration": d} for o, d in zip(outputs, ("T#5s", "T#3s", "T#8s", "T#1s", "T#2s"))]
    result = _program("Al pulsar Start ejecuta: bomba 5 s, válvula 3 s, motor 8 s, mezclador 1 s, calentador 2 s y al "
                      "terminar apaga todo.", [_seq(steps, start_input="I_Start"), {"outputs": []}][:1], tmp_path)
    plc = _Plc(result["scl"])
    plc.press("I_Start")
    for output, ms in zip(outputs, (5000, 3000, 8000, 1000, 2000)):
        assert plc.on(*outputs) == {output}
        plc.run(ms)
    plc.run(50)
    assert plc.on(*outputs) == set()


def test_G8_lamp_follows_presence_sensor(tmp_path):
    result = _program("Mientras el sensor de presencia esté activo mantén encendida la lámpara.",
                      [{"type": "conditional_output", "condition": "I_Presence", "outputs": ["Q_Lamp"]}], tmp_path)
    plc = _Plc(result["scl"])
    plc.set(I_Presence=True)
    plc.run(30)
    assert plc.on("Q_Lamp")
    plc.run(60000)
    assert plc.on("Q_Lamp")
    plc.set(I_Presence=False)
    plc.run(30)
    assert not plc.on("Q_Lamp")


def test_G9_hysteresis_alarm_is_not_a_simple_comparison(tmp_path):
    result = _program("Activa la alarma si temperatura > 80 y apágala cuando temperatura < 70.",
                      [{"type": "hysteresis_switch", "input": "AI_Temperature", "output": "Q_Alarm", "on_above": 80,
                        "off_below": 70}], tmp_path)
    assert ("AI_Temperature", "%IW0") in {(p["proposed_name"], p["address"]) for p in result["proposals"]}  # AI libre
    plc = _Plc(result["scl"])
    for value, expected in ((75, False), (81, True), (75, True), (71, True), (69, False), (75, False)):
        plc.set(AI_Temperature=value)
        plc.run(20)
        assert bool(plc.on("Q_Alarm")) is expected, value


def test_inverted_hysteresis_is_a_contradiction():
    semantic = _interpret("x", _llm("x", [{"type": "hysteresis_switch", "input": "AI_Temperature", "output": "Q_Alarm",
                                            "on_above": 70, "off_below": 80}]), _bench())
    assert "contradictorio" in semantic["semantic_validation"]["clarification_question"]


def test_comparison_condition_is_supported(tmp_path):
    result = _program("Enciende el ventilador mientras la temperatura sea mayor que 50.",
                      [{"type": "conditional_output", "condition": "AI_Temperature > 50", "outputs": ["Q_Fan"]}], tmp_path)
    plc = _Plc(result["scl"])
    plc.set(AI_Temperature=40)
    plc.run(20)
    assert not plc.on("Q_Fan")
    plc.set(AI_Temperature=55)
    plc.run(20)
    assert plc.on("Q_Fan")


BRANCHING = [_seq([{"outputs": ["Q_Pump"], "duration": "T#15s", "advance_on": "I_Level_High",
                    "timeout_alarm_output": "Q_Alarm"}], start_input="I_Start", repeat="once")]


def test_branching_by_sensor_success_path(tmp_path):
    result = _program("Cuando presione Start, enciende la bomba. Si después de 15 segundos no se activa el sensor de nivel "
                      "alto, detén la bomba y activa una alarma. Si el sensor se activa antes, apaga la bomba sin activar la "
                      "alarma.", BRANCHING, tmp_path)
    plc = _Plc(result["scl"])
    plc.press("I_Start")
    plc.run(5000)
    assert plc.on("Q_Pump", "Q_Alarm") == {"Q_Pump"}
    plc.set(I_Level_High=True)
    plc.run(20)
    assert plc.on("Q_Pump", "Q_Alarm") == set()
    plc.run(20000)
    assert plc.on("Q_Pump", "Q_Alarm") == set()


def test_branching_by_sensor_timeout_path_latches_alarm_until_next_start(tmp_path):
    result = _program("x", BRANCHING, tmp_path)
    plc = _Plc(result["scl"])
    plc.press("I_Start")
    plc.run(15100)
    assert plc.on("Q_Pump", "Q_Alarm") == {"Q_Alarm"}  # falla: bomba detenida y alarma
    plc.run(30000)
    assert plc.on("Q_Alarm") == {"Q_Alarm"}  # enclavada
    plc.press("I_Start")
    assert plc.on("Q_Pump", "Q_Alarm") == {"Q_Pump"}  # un nuevo arranque la reconoce
    inferences = result["semantic"]["semantic_validation"]["inferences"]
    assert any(i["field"] == "secuencia 1.final_state" and i["provenance"] == "DEFAULT" for i in inferences)


def test_waiting_step_advances_on_a_condition(tmp_path):
    result = _program("Al pulsar Start abre la válvula hasta que se active el nivel alto, luego enciende el mezclador 5 s.",
                      [_seq([{"outputs": ["Q_Valve"], "advance_on": "I_Level_High"}, {"outputs": ["Q_Mixer"], "duration": "T#5s"}],
                            start_input="I_Start")], tmp_path)
    plc = _Plc(result["scl"])
    plc.press("I_Start")
    plc.run(60000)
    assert plc.on("Q_Valve", "Q_Mixer") == {"Q_Valve"}  # espera la condicion, sin tiempo limite
    plc.set(I_Level_High=True)
    plc.run(20)
    assert plc.on("Q_Valve", "Q_Mixer") == {"Q_Mixer"}
    plc.run(5100)
    assert plc.on("Q_Valve", "Q_Mixer") == set()


def test_expression_inside_a_single_signal_parameter_is_caught_at_validation():
    """Respuesta real del LLM para G3: la expresion en trigger_input fallaba despues, en la IR."""
    live = _llm("x", [], intent="INT_TIMED_PULSE", parameters={"trigger_input": "I_Sensor_A AND I_Sensor_B",
                                                                "output": "Q_Valve_Open", "duration": "T#4s"})
    validation = _interpret("x", live, _bench())["semantic_validation"]
    assert validation["is_valid"] is False
    assert any(e.startswith("PARAMETER_EXPRESSION_NOT_SUPPORTED") and "trigger_input" in e for e in validation["errors"])


def test_invalid_normal_interpretation_gets_one_corrective_pass(monkeypatch):
    invalid = _llm("x", [], intent="INT_TIMED_PULSE", parameters={"trigger_input": "I_Sensor_A AND I_Sensor_B",
                                                                   "output": "Q_Valve", "duration": "T#4s"})
    fixed = _llm("x", [{"type": "conditional_output", "condition": "I_Sensor_A AND I_Sensor_B", "outputs": ["Q_Valve"],
                        "duration": "T#4s"}])
    calls: list[dict[str, Any]] = []

    def _invoke(command_text, llm_client, context, llm_response_text):
        calls.append(dict(context))
        return llm_parser._normalize_semantic_output(copy.deepcopy(invalid if len(calls) == 1 else fixed), command_text), {}

    monkeypatch.setattr(llm_parser, "_invoke_llm", _invoke)
    catalog, safety = _configs()
    result = llm_parser.parse_with_mode("x", mode="llm", io_map=_bench(), intents_catalog=catalog, safety_rules=safety,
                                        llm_client=_Client(), interaction_profile="normal")
    assert len(calls) == 2 and "PARAMETER_EXPRESSION_NOT_SUPPORTED" in calls[1]["correction_note"]
    assert result["semantic_validation"]["is_valid"] is True


def test_live_g1_catalog_interpretation_behaves_as_requested(tmp_path):
    """Interpretacion REAL del LLM para G1 (intencion de catalogo): A al pulsar, B a los 5 s, Stop apaga ambos."""
    result = _program("Al pulsar Start enciende Motor A. Cinco segundos después enciende Motor B. Al pulsar Stop apaga ambos.",
                      [], tmp_path, intent="INT_SEQUENCE_THREE_STEPS",
                      parameters={"trigger_input": "I_Start", "stop_input": "I_Stop", "main_output": "Q_Motor_A",
                                  "aux_output": "Q_Motor_B", "step_memory": "M_Motor_AB_Sequence", "timer": "T_Motor_B_Delay",
                                  "delay_time": "T#5s", "emergency_input": "FALSE"})
    plc = _Plc(result["scl"])
    plc.press("I_Start")
    assert plc.on("Q_Motor_A", "Q_Motor_B") == {"Q_Motor_A"}
    plc.run(5100)
    assert plc.on("Q_Motor_A", "Q_Motor_B") == {"Q_Motor_A", "Q_Motor_B"}
    plc.press("I_Stop")
    assert plc.on("Q_Motor_A", "Q_Motor_B") == set()


def test_free_text_condition_is_rejected_early_in_normal_mode():
    semantic = _interpret("x", _llm("x", [{"type": "conditional_output", "condition": "cuando haga calor",
                                            "outputs": ["Q_Fan"]}]), _bench())
    assert any("condicion no interpretable" in e for e in semantic["semantic_validation"]["errors"])


# ---------------------------------------------------------------------------------------------
# Logs, generalidad (sin hardcode) y aislamiento de Experimentacion / formal-v1.1
# ---------------------------------------------------------------------------------------------

def test_normal_trace_lines_are_distinguishable():
    assert NI.trace("NORMAL_IO_COMMIT", assigned="Q_Pump@%QX1.0", empty="") == "[NORMAL_IO_COMMIT] assigned=Q_Pump@%QX1.0"
    for event in ("NORMAL_SEMANTIC_PARSE", "NORMAL_CLARIFICATION_REQUIRED", "NORMAL_CLARIFICATION_RESOLVED",
                  "NORMAL_RESOURCE_REQUIREMENTS", "NORMAL_IO_PROVISIONAL", "NORMAL_IO_COMMIT", "NORMAL_IO_ROLLBACK",
                  "NORMAL_MAP_CONFIG_EXPLICIT", "NORMAL_GENERATION", "NORMAL_DOWNLOAD", "NORMAL_INTERNAL_RESOURCES", "NORMAL_IR_BUILT",
                  "NORMAL_CAPABILITY_GAP"):
        assert event in NI.NORMAL_LOG_EVENTS


def test_new_sequence_logic_has_no_domain_or_phrase_hardcode():
    sources = [inspect.getsource(obj) for obj in (
        FR.timed_sequence_steps, FR.timed_sequence_repeat, FR.timed_sequence_missing_data, FR.timed_sequence_inferences,
        FR.composition_conflicts, FR.composition_missing_data, FR.conditional_outputs, FR.hysteresis_switches,
        FR.force_offs, FR.latches, io_allocator.capacity_gap, _generate_composed_program, semantic_validator.describe_sequence_gap)]
    sources.append(NI.NORMAL_MODE_POLICY)
    for source in sources:
        code = "\n".join(line.split("#", 1)[0] for line in source.splitlines()).lower()
        for word in ("bomba", "valvula", "válvula", "semaforo", "semáforo", "verde", "amarillo", "rojo", "pump", "valve",
                     "traffic", "green", "yellow", "estrella", "triangulo", "star_delta"):
            assert word not in code, word
    catalog, _ = _configs()
    assert not [intent for intent in catalog if re.search(r"SEMAFORO|TRAFFIC|PUMP_VALVE", intent)]


def test_without_normal_profile_allocation_and_validation_are_unchanged():
    """Experimentacion (sin perfil Normal) conserva la reasignacion ASSIGNED y no recibe capability_gap."""
    io_map = _bench(outputs={"Q_Motor_Enable": "%QX1.0"}, free_do=2)  # 1 FREE (%QX1.1) + 1 ASSIGNED
    proposals = propose_assignment(io_map, [{"functional_name_hint": "Q_Pump"}, {"functional_name_hint": "Q_Valve"}])
    assert [p["blocked"] for p in proposals] == [False, False] and proposals[1]["current_state"] == "ASSIGNED"
    semantic = llm_parser._normalize_semantic_output(_llm("x", INCIDENT_REQUIREMENTS), "x")
    catalog, safety = _configs()
    validation = validate_semantic_output(semantic, io_map, catalog, safety)
    assert "capability_gap" not in validation


def test_formal_llm_context_never_receives_the_normal_policy(monkeypatch):
    contexts: list[dict[str, Any]] = []

    def _invoke(command_text, llm_client, context, llm_response_text):
        contexts.append(dict(context))
        return llm_parser._normalize_semantic_output(_llm("x", INCIDENT_REQUIREMENTS), command_text), {}

    monkeypatch.setattr(llm_parser, "_invoke_llm", _invoke)
    llm_parser.parse_with_mode(PUMP_VALVE, mode="llm", io_map=_bench(), llm_client=_Client())
    assert "normal_mode_policy" not in contexts[0] and "clarification_history" not in contexts[0]
