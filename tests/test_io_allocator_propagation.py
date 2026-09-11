"""
Prueba critica (seccion 23): un renombrado por voz/texto debe propagarse REALMENTE, hasta el
codigo generado - no solo quedar en memoria. Parte de %QX8.1 -> Q_Auxiliary (ASSIGNED), ejecuta
"Usa Q8.1 para controlar el motor 2." (frase natural real, con un verbo de relleno antes del
rol - la que exponia el bug original), y verifica cada eslabon: propuesta -> aplicar -> guardar
-> releer desde JSON -> PLCProjectIR -> variables.json -> SCL. Q_Auxiliary no debe volver a
aparecer para ese canal en ningun punto posterior.
"""
from __future__ import annotations

import json
from pathlib import Path

from io_allocator import apply_assignments, extract_io_assignment_requests, propose_assignment
from ir_builder import build_project_ir
from plc_maps.store import save_plc_map, load_plc_map
from project_packager import generate_project_package
from utils import get_project_root, load_json_file


def _starting_map() -> dict:
    return {
        "schema_version": 1,
        "metadata": {"map_id": "mapa_test_propagation", "name": "MAPA_TEST_PROPAGATION", "version": 1},
        "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_", "auxiliary": "R_"},
        "variables": [
            {
                "name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX16.0",
                "initial_value": "FALSE", "description": "", "state": "LOCKED", "llm_allowed": True
            },
            {
                "name": "I_Emergency", "class": "input", "type": "BOOL", "location": "%IX16.2",
                "initial_value": "FALSE", "description": "", "state": "LOCKED", "llm_allowed": True
            },
            {
                "name": "Q_Auxiliary", "class": "output", "type": "BOOL", "location": "%QX8.1",
                "initial_value": "FALSE", "description": "", "state": "ASSIGNED", "llm_allowed": True
            }
        ]
    }


def test_critical_rename_propagates_to_disk_ir_and_scl(tmp_path):
    map_path = tmp_path / "mapa_test_propagation.json"
    save_plc_map(map_path, _starting_map()["variables"])

    # A) el parser (regex determinista) detecta requested_io_assignments
    requests = extract_io_assignment_requests("Usa Q8.1 para controlar el motor 2.")
    assert requests
    assert requests[0]["address"] == "%QX8.1"

    io_map = load_plc_map(map_path)

    # B) el IOAllocator genera %Q8.1 -> Q_Motor_2 (no un nombre corrupto por el verbo de relleno)
    proposals = propose_assignment(io_map, requests)
    assert proposals[0]["proposed_name"] == "Q_Motor_2"
    assert proposals[0]["address"] == "%QX8.1"
    assert proposals[0]["blocked"] is False

    # C) se actualiza el objeto del mapa en memoria
    updated_map, history_entries = apply_assignments(io_map, proposals, source="text")
    updated_variable = next(v for v in updated_map["variables"] if v["location"] == "%QX8.1")
    assert updated_variable["name"] == "Q_Motor_2"
    assert updated_variable["state"] == "ASSIGNED"

    # D) se guarda realmente el cambio en el JSON
    save_plc_map(map_path, updated_map["variables"], history_entries=history_entries)
    reloaded = json.loads(map_path.read_text(encoding="utf-8"))
    reloaded_variable = next(v for v in reloaded["variables"] if v["location"] == "%QX8.1")
    assert reloaded_variable["name"] == "Q_Motor_2"
    assert reloaded["history"][0]["new_name"] == "Q_Motor_2"
    assert reloaded["history"][0]["old_name"] == "Q_Auxiliary"

    # Recargar de nuevo desde JSON (simula "cerrar y volver a abrir") - el nombre persiste.
    reloaded_map = load_plc_map(map_path)
    assert next(v for v in reloaded_map["variables"] if v["location"] == "%QX8.1")["name"] == "Q_Motor_2"

    # F) el nuevo nombre llega al PLCProjectIR (usando el mapa YA actualizado)
    semantic_output = {
        "intent_id": "INT_DIRECT_OUTPUT",
        "case_id": "T_PROPAGATION",
        "command_text": "enciende la salida con Start",
        "normalized_command": "enciende la salida con start",
        "parameters": {"trigger_input": "I_Start", "emergency_input": "I_Emergency", "output": "Q_Motor_2"},
        "confidence": 0.95,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": ["I_Start", "I_Emergency", "Q_Motor_2"],
        "unrecognized_terms": []
    }
    project_ir = build_project_ir(semantic_output, reloaded_map, target_platform="SIEMENS_SCL_V18")
    variable_names = {v.name for v in project_ir.pou.variables}
    assert "Q_Motor_2" in variable_names
    assert "Q_Auxiliary" not in variable_names  # el nombre viejo no sigue usandose para este rol

    # G) el nuevo nombre llega al SCL y a variables.json (paquete Siemens completo)
    result = generate_project_package(
        semantic_output=semantic_output,
        target_platform="SIEMENS_SCL_V18",
        io_map=reloaded_map,
        output_dir=tmp_path / "package"
    )
    assert result["verification"]["is_valid"] is True
    scl_text = result["rendered_files"]["siemens_source.scl"]
    assert "Q_Motor_2" in scl_text
    assert "Q_Auxiliary" not in scl_text

    variables_table = result["rendered_files"]["variables.json"]
    variable_names_in_table = {row["name"] for row in variables_table}
    assert "Q_Motor_2" in variable_names_in_table
    assert "Q_Auxiliary" not in variable_names_in_table
