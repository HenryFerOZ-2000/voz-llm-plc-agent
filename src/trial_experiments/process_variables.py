"""
Variables de proceso (P01-P12): estaticas del DB de instancia del programa generado (Level_PV, Level_SP,
Auto_Mode, PID_Enable, alarmas, Sensor_Fault, Safe_Stop), NO E/S fisicas ni AI/AO.

process_variable_bindings: estructura CONGELADA por ensayo (process_variable_bindings.json, en el
integrity_manifest) que dice que variables de proceso existen en el programa y como acceder a ellas en
Runtime. Se deriva SOLO de:
  - variables.json congelado del ensayo (lo que el generador declaro realmente), y
  - el contrato del intent (functional_requirements.PID_PROCESS_VARIABLES: nombre y tipo IEC).
Nunca se lee program.scl ni el Oracle para construirla, y nunca se adivina: una variable entra solo si
esta en variables.json como estatica generada (FB_STATIC*) Y en el contrato con el MISMO tipo.

El nombre Runtime NO se fija aqui: su formato en PLCSIM (p.ej. con o sin comillas en el DB) se resuelve
en el bridge contra TagInfos del programa cargado (db + member) y queda como evidencia en la traza.

Las variables se manejan en unidades de ingenieria (REAL en %), sin escalado RAW ni AI/AO.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from functional_requirements import PID_PROCESS_VARIABLES

PROCESS_VARIABLE_BINDINGS_FILENAME = "process_variable_bindings.json"
BINDING_PROCESS_VARIABLE = "PROCESS_VARIABLE"
SOURCE_INTENT_CONTRACT = "INTENT_CONTRACT"
# Fuente cuando un ensayo anterior no congelo el archivo: se deriva, con la MISMA regla, del variables.json
# congelado (verificado por hash en el integrity_manifest). Queda trazado como tal.
SOURCE_DERIVED_FROM_FROZEN_VARIABLES = "DERIVED_FROM_FROZEN_VARIABLES"
RUNTIME_NAME_DISCOVERED_AT_EXECUTION = "DISCOVERED_AT_EXECUTION"
# siemens_scl_adapter: FB "PLC_PRG" con DB de instancia "DB_<pou>" (DE.APP_MANAGED_BLOCK_NAMES).
DEFAULT_INSTANCE_DB = "DB_PLC_PRG"
SUPPORTED_DATA_TYPES = ("BOOL", "REAL")
_STATIC_SCOPES = ("FB_STATIC", "FB_STATIC_PERSISTENT")


def build_process_variable_bindings(variables: list[dict[str, Any]], instance_db: str = DEFAULT_INSTANCE_DB,
                                    source: str = SOURCE_INTENT_CONTRACT) -> dict[str, Any]:
    """{schema_version, instance_db, source, bindings: {name: binding}, excluded: [...]} (nombres = contrato)."""
    bindings: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    for row in variables or []:
        name = str(row.get("name") or "")
        if name not in PID_PROCESS_VARIABLES:
            continue
        declared = str(row.get("type") or "").upper()
        contract = PID_PROCESS_VARIABLES[name].upper()
        scope = str(row.get("tia_scope") or "")
        reason = None
        if scope not in _STATIC_SCOPES:
            reason = f"tia_scope {scope or '?'} no es una estatica del DB de instancia"
        elif declared != contract:
            reason = f"tipo declarado {declared or '?'} distinto del contrato {contract}"
        elif contract not in SUPPORTED_DATA_TYPES:
            reason = f"tipo {contract} fuera de alcance (BOOL/REAL)"
        if reason:
            excluded.append({"name": name, "reason": reason})
            continue
        bindings[name] = {
            "name": name,
            "db": instance_db,
            "member": name,
            "runtime_name": None,
            "runtime_name_resolution": RUNTIME_NAME_DISCOVERED_AT_EXECUTION,
            "data_type": contract,
            "binding": BINDING_PROCESS_VARIABLE,
            "tia_scope": scope,
            "source": source,
        }
    return {"schema_version": 1, "instance_db": instance_db, "source": source, "bindings": bindings, "excluded": excluded}


def freeze_process_variable_bindings(trial_dir: Path, variables_path: Path) -> Path | None:
    """GENERAR ENSAYO: escribe el archivo congelado solo si el programa declara variables de proceso."""
    variables = json.loads(Path(variables_path).read_text(encoding="utf-8"))
    payload = build_process_variable_bindings(variables)
    if not payload["bindings"]:
        return None
    target = Path(trial_dir) / PROCESS_VARIABLE_BINDINGS_FILENAME
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def load_process_variable_bindings(trial_dir: Path, variables_path: Path | None = None) -> dict[str, Any]:
    """Congelado del ensayo; ensayos anteriores: derivado (misma regla) del variables.json congelado."""
    frozen = Path(trial_dir) / PROCESS_VARIABLE_BINDINGS_FILENAME
    if frozen.is_file():
        return json.loads(frozen.read_text(encoding="utf-8"))
    variables_path = Path(variables_path) if variables_path else Path(trial_dir) / "variables.json"
    if not variables_path.is_file():
        return {"schema_version": 1, "instance_db": DEFAULT_INSTANCE_DB, "source": None, "bindings": {}, "excluded": []}
    variables = json.loads(variables_path.read_text(encoding="utf-8"))
    return build_process_variable_bindings(variables, source=SOURCE_DERIVED_FROM_FROZEN_VARIABLES)


def runtime_signal(binding: dict[str, Any], writable: bool = False, restore_value: Any = None) -> dict[str, Any]:
    """Senal para el bridge: el nombre logico (db.member) identifica la muestra; el bridge resuelve el Runtime."""
    signal = {
        "kind": BINDING_PROCESS_VARIABLE,
        "name": f"{binding['db']}.{binding['member']}",
        "db": binding["db"],
        "member": binding["member"],
        "data_type": binding["data_type"],
        "writable": bool(writable),
    }
    if restore_value is not None:
        signal["restore_value"] = restore_value
    return signal
