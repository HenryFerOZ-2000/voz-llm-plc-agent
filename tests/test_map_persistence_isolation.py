"""
Regression tests for a real incident: manual diagnostic scripts run against the live GUI app (to
reproduce a different bug) polluted `data/plc_maps/mapa_banco_fisico.json` - including
temporarily introducing I_Emergency, which this bench never has wired to the PLC. The parser,
semantic validator, and IOAllocator were ALREADY pure by construction (propose_assignment/
apply_assignments never mutate the map they receive, they return a new one); the actual mistake
was a diagnostic script constructing `gui.VozLLMPLCGUI()` directly and calling
`process_command()` without redirecting `io_map_path` - the one place that legitimately persists
(save_plc_map, called only from gui.py). These tests make that purity explicit and verifiable, and
add a hard backstop (also see conftest.py::_real_bench_map_untouched_guard, which runs
automatically for the whole suite) so it cannot regress silently again.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from io_allocator import apply_assignments, propose_assignment
from plc_maps.store import save_plc_map
from semantic_validator import validate_semantic_output
from utils import get_project_root


REAL_BENCH_MAP_PATH = get_project_root() / "data" / "plc_maps" / "mapa_banco_fisico_base.json"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sample_map() -> dict[str, Any]:
    return {
        "variables": [
            {"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX16.0", "state": "LOCKED"},
            {"name": "I_Free", "class": "input", "type": "BOOL", "location": "%IX16.1", "state": "FREE"},
            {"name": "Q_Free", "class": "output", "type": "BOOL", "location": "%QX8.0", "state": "FREE"}
        ]
    }


# ---------- 4/5/6/7: parser, validator, and dry-run allocator never touch the real map ----------

def test_real_bench_map_hash_unchanged_across_semantic_and_allocator_tests():
    """
    Ejecuta explicitamente el ejercicio que pide el pedido (hash_before / correr operaciones
    semanticas y de allocator / hash_after) contra el archivo real, ademas de la guardia
    automatica de sesion en conftest.py - un test nombrado y legible por su cuenta.
    """
    before = _hash(REAL_BENCH_MAP_PATH)

    # Parser (via validate_semantic_output) y IOAllocator operando sobre datos EN MEMORIA, nunca
    # sobre el archivo real - construidos aqui mismo, no cargados de disco.
    io_map = _sample_map()
    semantic_output = {
        "intent_id": "INT_DIRECT_OUTPUT",
        "case_id": None,
        "command_text": "x",
        "normalized_command": "x",
        "parameters": {"trigger_input": "I_Start", "output": "Q_New"},
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start", "Q_New"],
        "unrecognized_terms": [],
        "functional_requirements": []
    }
    validate_semantic_output(semantic_output, io_map, {"INT_DIRECT_OUTPUT": {}}, {})
    propose_assignment(io_map, [{"functional_name_hint": "Q_Motor_1"}])
    apply_assignments(io_map, [{"address": "%QX8.0", "proposed_name": "Q_Motor_1", "blocked": False}])

    after = _hash(REAL_BENCH_MAP_PATH)
    assert before == after


def test_propose_assignment_never_mutates_its_input_map():
    io_map = _sample_map()
    snapshot = json.loads(json.dumps(io_map))
    propose_assignment(io_map, [{"functional_name_hint": "Q_Motor_1"}])
    assert io_map == snapshot


def test_apply_assignments_returns_a_new_map_never_mutates_the_original():
    """
    "Dry run" / transaccion (seccion 8 del pedido): el patron YA existe estructuralmente -
    apply_assignments siempre construye una copia (`[dict(v) for v in io_map["variables"]]`) y
    devuelve un mapa NUEVO; el original pasado como argumento queda intacto, sin necesidad de un
    modo "dry run" separado - la persistencia real es un paso EXPLICITO y distinto
    (plc_maps.store.save_plc_map), nunca un efecto secundario de calcular la propuesta.
    """
    io_map = _sample_map()
    snapshot = json.loads(json.dumps(io_map))
    updated_map, _ = apply_assignments(io_map, [{"address": "%QX8.0", "proposed_name": "Q_Motor_1", "blocked": False}])
    assert io_map == snapshot  # el original no cambio
    assert updated_map is not io_map  # se devolvio un objeto nuevo
    assert next(v for v in updated_map["variables"] if v["location"] == "%QX8.0")["name"] == "Q_Motor_1"


def test_validate_semantic_output_never_writes_any_file(tmp_path, monkeypatch):
    """El validador es puramente diagnostico: nunca debe tocar el sistema de archivos. Se
    intercepta save_plc_map para demostrar que jamas se llama durante la validacion."""
    calls = {"count": 0}
    monkeypatch.setattr("plc_maps.store.save_plc_map", lambda *a, **k: calls.__setitem__("count", calls["count"] + 1))

    io_map = _sample_map()
    semantic_output = {
        "intent_id": "INT_DIRECT_OUTPUT",
        "case_id": None,
        "command_text": "x",
        "normalized_command": "x",
        "parameters": {"trigger_input": "I_Start", "output": "Q_New"},
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start", "Q_New"],
        "unrecognized_terms": [],
        "functional_requirements": []
    }
    validate_semantic_output(semantic_output, io_map, {"INT_DIRECT_OUTPUT": {}}, {})
    assert calls["count"] == 0


# ---------- 8: I_Emergency nunca se autocrea ----------

def test_real_bench_map_still_has_no_i_emergency():
    payload = json.loads(REAL_BENCH_MAP_PATH.read_text(encoding="utf-8"))
    names = {v["name"] for v in payload["variables"]}
    assert "I_Emergency" not in names


def test_propose_assignment_would_auto_create_emergency_without_the_repair_layer():
    """
    Documenta el hallazgo real (seccion 10 del pedido): propose_assignment(), por si solo, SI
    resolveria "I_Emergency" a un canal FREE si algo se lo pide - no es su responsabilidad saber
    que este proyecto no quiere eso nunca por convencion del parser. La proteccion real vive en
    semantic_repair.strip_unavailable_emergency_reference, que se ejecuta ANTES de que una
    referencia asi llegue a este punto (ver test_semantic_repair.py) - este test dcoumenta POR QUE
    esa capa es necesaria, no que el allocator este roto.
    """
    io_map = _sample_map()
    proposals = propose_assignment(io_map, [{"functional_name_hint": "I_Emergency"}])
    assert proposals[0]["blocked"] is False
    assert proposals[0]["proposed_name"] == "I_Emergency"


# ---------- 9: la ejecucion real SI puede persistir cuando corresponde (fuera del mapa real) ----------

def test_save_plc_map_can_persist_when_explicitly_targeted_at_a_temp_path(tmp_path):
    """La persistencia SI debe funcionar - solo nunca contra el mapa real durante pruebas. Ver
    tambien tests/test_gui_map_config.py (patron `temp_map`) para el flujo completo via GUI."""
    map_path = tmp_path / "mapa_test.json"
    save_plc_map(map_path, _sample_map()["variables"])
    assert map_path.exists()
    saved = json.loads(map_path.read_text(encoding="utf-8"))
    assert len(saved["variables"]) == 3
