"""
Trial-scoped working I/O map (Modo Experimentacion).

Cada ensayo parte del MISMO mapa base, trabaja sobre una copia propia (working_io_map.json en
el directorio del ensayo), resuelve sus I/O con el MISMO IOAllocator que Modo Normal
(io_allocator.propose_assignment / apply_assignments, sin logica paralela), congela los bindings
en io_map_snapshot.json antes de IR/SCL y descarta la copia al terminar. El mapa base (el mapa
activo de Modo Normal) nunca se escribe por efecto de un ensayo.

Mapa base = inventario fisico del mapa activo, normalizado:
  - LOCKED se conserva tal cual (direccion, nombre, descripcion, aliases);
  - ASSIGNED y FREE vuelven a FREE con el nombre generico del canal (I_Free16_6, Q_Free8_3,
    AI_IW0, AO_QW0) y sin aliases: nunca se heredan residuos de asignaciones dinamicas previas;
  - variables internas (sin direccion fisica) no LOCKED se descartan.

Politica de mutacion por FASE (no por "hay un ensayo activo"):
  lifecycle_state in {CREATED, PREPARING}  -> el pipeline automatico puede asignar/reasignar;
  lifecycle_state >= IO_RESOLVED            -> EXPERIMENT_IO_FROZEN.
La edicion MANUAL del mapa sigue bloqueada durante el ensayo (io_allocator.block_map_config_message).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from io_allocator import DEFAULT_STATE, STATE_FREE, STATE_LOCKED, VALID_STATES, apply_assignments

WORKING_MAP_FILENAME = "working_io_map.json"
SNAPSHOT_FILENAME = "io_map_snapshot.json"
SNAPSHOT_SCHEMA_VERSION = 1

# Ciclo de vida interno del ensayo. Coexiste con final_status (PREPARED/PASS/FAIL/...) del
# trial model: lifecycle_state dice en que fase esta; final_status como termino.
STATE_CREATED = "CREATED"
STATE_PREPARING = "PREPARING"
STATE_IO_RESOLVED = "IO_RESOLVED"
STATE_COMPILED = "COMPILED"
STATE_DOWNLOADED = "DOWNLOADED"
STATE_RUNTIME_READY = "RUNTIME_READY"
STATE_TESTING = "TESTING"
STATE_PASS = "PASS"
STATE_FAIL = "FAIL"
STATE_REVIEW = "REVIEW"
STATE_INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
LIFECYCLE_STATES = (
    STATE_CREATED, STATE_PREPARING, STATE_IO_RESOLVED, STATE_COMPILED, STATE_DOWNLOADED,
    STATE_RUNTIME_READY, STATE_TESTING, STATE_PASS, STATE_FAIL, STATE_REVIEW, STATE_INFRASTRUCTURE_ERROR,
)
MUTATION_ALLOWED_STATES = frozenset({STATE_CREATED, STATE_PREPARING})

ERROR_BASE_UNAVAILABLE = "EXPERIMENT_IO_BASE_UNAVAILABLE"
ERROR_ALLOCATION_FAILED = "EXPERIMENT_IO_ALLOCATION_FAILED"
ERROR_FROZEN = "EXPERIMENT_IO_FROZEN"
ERROR_SNAPSHOT_FAILED = "EXPERIMENT_IO_SNAPSHOT_FAILED"

_PHYSICAL_PATTERN = re.compile(r"^%(I|Q)(X|W)(\d+)(?:\.(\d+))?$", re.IGNORECASE)


class ExperimentIOError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.detail = message


# ---------------------------------------------------------------------------------------------
# Mapa base
# ---------------------------------------------------------------------------------------------

def physical_signal(location: Any) -> str | None:
    """DI / DO / AI / AO para una direccion fisica; None si no es un canal fisico."""
    match = _PHYSICAL_PATTERN.match(str(location or "").strip())
    if not match:
        return None
    direction, size = match.group(1).upper(), match.group(2).upper()
    if size == "X":
        return "DI" if direction == "I" else "DO"
    return "AI" if direction == "I" else "AO"


def free_channel_name(location: str) -> str:
    """Nombre generico de un canal libre, misma convencion que mapa_banco_fisico.json."""
    match = _PHYSICAL_PATTERN.match(location.strip())
    if not match:
        raise ValueError(f"Direccion fisica invalida: {location!r}")
    direction, size, byte, bit = match.group(1).upper(), match.group(2).upper(), match.group(3), match.group(4)
    if size == "X":
        return f"{direction}_Free{byte}_{bit}"
    return f"{'AI' if direction == 'I' else 'AO'}_{direction}W{byte}"


def _state_of(variable: dict[str, Any]) -> str:
    state = variable.get("state")
    return state if state in VALID_STATES else DEFAULT_STATE


def build_experiment_base_map(source_map: dict[str, Any], source_map_id: str) -> dict[str, Any]:
    """Funcion pura: inventario fisico del mapa activo con las asignaciones dinamicas limpiadas."""
    variables: list[dict[str, Any]] = []
    for original in source_map.get("variables", []) or []:
        variable = copy.deepcopy(original)
        location = str(variable.get("location") or "")
        state = _state_of(variable)
        if physical_signal(location) is None:
            if state == STATE_LOCKED:
                variable["state"] = STATE_LOCKED
                variables.append(variable)
            continue
        if state == STATE_LOCKED:
            variable["state"] = STATE_LOCKED
        else:
            variable["name"] = free_channel_name(location)
            variable["state"] = STATE_FREE
            variable["description"] = ""
            variable["comments"] = ""
            variable["aliases"] = []
        variables.append(variable)

    metadata = dict(source_map.get("metadata") or {})
    metadata.update({
        "map_id": f"{source_map_id}__experiment_base",
        "name": f"Base experimental de {source_map_id}",
        "base_of_map_id": source_map_id,
        "dirty": False,
    })
    return {
        "schema_version": source_map.get("schema_version", 1),
        "metadata": metadata,
        "naming_convention": source_map.get("naming_convention", {}),
        "variables": variables,
        "history": [],
    }


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(temporary, path)


def _physical_locations(io_map: dict[str, Any]) -> list[str]:
    return sorted(
        str(variable.get("location")) for variable in io_map.get("variables", []) if physical_signal(variable.get("location"))
    )


def create_working_map(trial_dir: Path, source_map_path: Path) -> dict[str, Any]:
    """Crea working_io_map.json a partir del mapa base. Devuelve la referencia para trial.json."""
    try:
        raw_bytes = Path(source_map_path).read_bytes()
        source_map = json.loads(raw_bytes.decode("utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ExperimentIOError(ERROR_BASE_UNAVAILABLE, f"No se pudo leer el mapa base {source_map_path}: {error}") from error
    if not isinstance(source_map, dict):
        raise ExperimentIOError(ERROR_BASE_UNAVAILABLE, f"El mapa base {source_map_path} no es un objeto JSON.")

    source_map_id = str((source_map.get("metadata") or {}).get("map_id") or Path(source_map_path).stem)
    base_map = build_experiment_base_map(source_map, source_map_id)
    channels = _physical_locations(base_map)
    if not channels:
        raise ExperimentIOError(ERROR_BASE_UNAVAILABLE, f"El mapa base {source_map_id} no tiene canales fisicos.")

    working_path = Path(trial_dir) / WORKING_MAP_FILENAME
    _write_json_atomic(working_path, base_map)
    return {
        "base_map_id": source_map_id,
        "base_map_path": str(source_map_path),
        "base_source_hash": hashlib.sha256(raw_bytes).hexdigest(),
        "base_map_hash": _canonical_hash(base_map["variables"]),
        "physical_channel_count": len(channels),
        "working_map_path": str(working_path),
        "snapshot_path": None,
        "frozen": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "resolved_at": None,
        "error": None,
    }


# ---------------------------------------------------------------------------------------------
# Mutacion (solo en PREPARING) - mismo IOAllocator que Modo Normal
# ---------------------------------------------------------------------------------------------

def mutation_allowed(lifecycle_state: str | None) -> bool:
    return (lifecycle_state or STATE_CREATED) in MUTATION_ALLOWED_STATES


def assert_mutation_allowed(lifecycle_state: str | None) -> None:
    if not mutation_allowed(lifecycle_state):
        raise ExperimentIOError(
            ERROR_FROZEN,
            f"Las I/O del ensayo ya estan congeladas (estado {lifecycle_state}); no se admiten nuevas asignaciones.",
        )


def load_working_map(working_map_path: Path) -> dict[str, Any]:
    payload = json.loads(Path(working_map_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("working_io_map.json no es un objeto JSON.")
    return payload


def apply_proposals_to_working_map(
    working_map_path: Path,
    proposals: list[dict[str, Any]],
    source: str,
    lifecycle_state: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Transaccional: candidato = apply_assignments(working, proposals) (funcion pura) -> validacion
    -> escritura atomica. Cualquier fallo deja working_io_map.json exactamente como estaba.
    """
    assert_mutation_allowed(lifecycle_state)
    working = load_working_map(working_map_path)
    try:
        candidate, history_entries = apply_assignments(working, proposals, source=source)
    except ValueError as error:
        raise ExperimentIOError(ERROR_ALLOCATION_FAILED, str(error)) from error

    if _physical_locations(candidate) != _physical_locations(working):
        raise ExperimentIOError(
            ERROR_ALLOCATION_FAILED,
            "La asignacion alteraria el inventario fisico del banco (canales nuevos o eliminados).",
        )
    known = {str(variable.get("location")) for variable in working.get("variables", [])}
    unknown = sorted({str(p.get("address")) for p in proposals if p.get("address") and str(p.get("address")) not in known})
    if unknown:
        raise ExperimentIOError(ERROR_ALLOCATION_FAILED, "Direcciones inexistentes en el banco: " + ", ".join(unknown))

    candidate["history"] = list(working.get("history", [])) + list(history_entries)
    _write_json_atomic(Path(working_map_path), candidate)
    return candidate, history_entries


# ---------------------------------------------------------------------------------------------
# Freeze + snapshot
# ---------------------------------------------------------------------------------------------

def _collect_strings(value: Any, sink: set[str]) -> None:
    if isinstance(value, str):
        sink.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_strings(item, sink)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_strings(item, sink)


def _parameter_roles(parameters: Any, prefix: str = "") -> list[tuple[str, str]]:
    """(ruta_del_parametro, valor) para cada string dentro de semantic_output.parameters."""
    pairs: list[tuple[str, str]] = []
    if isinstance(parameters, dict):
        for key, value in parameters.items():
            pairs.extend(_parameter_roles(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(parameters, (list, tuple)):
        for index, value in enumerate(parameters):
            pairs.extend(_parameter_roles(value, f"{prefix}[{index}]"))
    elif isinstance(parameters, str):
        pairs.append((prefix, parameters))
    return pairs


def build_snapshot(
    working_map: dict[str, Any],
    semantic_output: dict[str, Any] | None,
    io_map_ref: dict[str, Any],
    trial_id: str | None,
) -> dict[str, Any]:
    """
    Evidencia congelada: los canales fisicos completos + los bindings activos del ensayo.
    Pensado para que un Oracle futuro resuelva role -> functional_name -> physical_address sin
    hardcodear direcciones (parameter_bindings / bindings[].roles).
    """
    semantic_output = semantic_output or {}
    referenced: set[str] = set()
    _collect_strings(semantic_output.get("parameters"), referenced)
    _collect_strings(semantic_output.get("functional_requirements"), referenced)
    for proposal in (semantic_output.get("semantic_validation") or {}).get("io_assignment_proposals", []) or []:
        if proposal.get("proposed_name"):
            referenced.add(str(proposal["proposed_name"]))

    roles_by_name: dict[str, list[str]] = {}
    for path, value in _parameter_roles(semantic_output.get("parameters")):
        roles_by_name.setdefault(value, []).append(path)

    channels: list[dict[str, Any]] = []
    internal: list[dict[str, Any]] = []
    for variable in working_map.get("variables", []) or []:
        location = str(variable.get("location") or "")
        signal = physical_signal(location)
        name = variable.get("name")
        if signal is None:
            internal.append({key: variable.get(key) for key in ("name", "class", "type", "location", "state", "description")})
            continue
        channels.append({
            "address": location,
            "signal": signal,
            "data_type": variable.get("type"),
            "var_class": variable.get("class"),
            "state": _state_of(variable),
            "functional_name": name,
            "description": variable.get("description", ""),
            "aliases": list(variable.get("aliases") or []),
            "bound": name in referenced,
        })

    bindings = [
        {
            "functional_name": channel["functional_name"],
            "address": channel["address"],
            "signal": channel["signal"],
            "data_type": channel["data_type"],
            "state": channel["state"],
            "roles": roles_by_name.get(channel["functional_name"], []),
            "aliases": channel["aliases"],
        }
        for channel in channels if channel["bound"]
    ]
    channel_by_name = {channel["functional_name"]: channel for channel in channels}
    provenance = semantic_output.get("parameter_provenance") or {}
    # Rol semantico -> recurso fisico congelado. Incluye los recursos completados por la semantica
    # efectiva (provenance DEFAULT): el Oracle resuelve START/STOP/MOTOR_MAIN desde aqui, nunca leyendo
    # program.scl. signal/data_type permiten roles analogicos (AI/AO, REAL/INT/WORD) sin rediseno.
    parameter_bindings = {
        path: {
            "functional_name": value,
            "name": value,
            "address": channel_by_name[value]["address"],
            "signal": channel_by_name[value]["signal"],
            "data_type": channel_by_name[value]["data_type"],
            "state": channel_by_name[value]["state"],
            "provenance": (provenance.get(path.split(".")[0].split("[")[0]) or {}).get("source"),
        }
        for path, value in _parameter_roles(semantic_output.get("parameters"))
        if value in channel_by_name
    }
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "trial_id": trial_id,
        "base_map_id": io_map_ref.get("base_map_id"),
        "base_source_hash": io_map_ref.get("base_source_hash"),
        "base_map_hash": io_map_ref.get("base_map_hash"),
        "frozen_at": datetime.now().isoformat(timespec="seconds"),
        "intent_id": semantic_output.get("intent_id"),
        "physical_channel_count": len(channels),
        "channels": channels,
        "bindings": bindings,
        "parameter_bindings": parameter_bindings,
        "parameter_provenance": provenance,
        "effective_semantics_status": (semantic_output.get("effective_semantics") or {}).get("status"),
        "internal_variables": internal,
        "generated_internal_variables": [],
        "allocation_history": list(working_map.get("history", []) or []),
    }


def freeze_working_map(
    io_map_ref: dict[str, Any],
    semantic_output: dict[str, Any] | None,
    lifecycle_state: str | None,
    trial_id: str | None = None,
) -> dict[str, Any]:
    """Congela los bindings: escribe io_map_snapshot.json y devuelve la referencia actualizada."""
    if not mutation_allowed(lifecycle_state):
        raise ExperimentIOError(ERROR_FROZEN, f"Las I/O del ensayo ya estaban congeladas (estado {lifecycle_state}).")
    working_path = Path(io_map_ref["working_map_path"])
    try:
        working = load_working_map(working_path)
        snapshot = build_snapshot(working, semantic_output, io_map_ref, trial_id)
        snapshot_path = working_path.with_name(SNAPSHOT_FILENAME)
        _write_json_atomic(snapshot_path, snapshot)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ExperimentIOError(ERROR_SNAPSHOT_FAILED, f"No se pudo generar {SNAPSHOT_FILENAME}: {error}") from error
    return {
        **io_map_ref,
        "snapshot_path": str(snapshot_path),
        "frozen": True,
        "resolved_at": snapshot["frozen_at"],
        "bound_channels": len(snapshot["bindings"]),
    }


def record_generated_internal_variables(io_map_ref: dict[str, Any], variables: list[dict[str, Any]]) -> list[str]:
    """
    Variables internas auto-generadas por el IR (p.ej. un setpoint) tras el freeze: se registran
    como evidencia en el snapshot. Nunca tocan canales ni bindings, ni el mapa base.
    """
    snapshot_path = io_map_ref.get("snapshot_path")
    if not snapshot_path or not variables:
        return []
    path = Path(snapshot_path)
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    existing = {item.get("name") for item in snapshot.get("generated_internal_variables", [])}
    added: list[str] = []
    for variable in variables:
        name = variable.get("name")
        if not name or name in existing:
            continue
        snapshot.setdefault("generated_internal_variables", []).append({
            "name": name,
            "var_class": variable.get("var_class"),
            "data_type": variable.get("data_type"),
            "location": variable.get("location") or "",
            "description": variable.get("description", ""),
        })
        existing.add(name)
        added.append(name)
    if added:
        _write_json_atomic(path, snapshot)
    return added


def discard_working_map(io_map_ref: dict[str, Any] | None) -> bool:
    """Fin del ensayo: se elimina working_io_map.json (el snapshot queda como evidencia)."""
    if not io_map_ref or not io_map_ref.get("working_map_path"):
        return False
    path = Path(io_map_ref["working_map_path"])
    if path.exists():
        path.unlink()
        return True
    return False


def trial_record_reference(io_map_ref: dict[str, Any]) -> dict[str, Any]:
    """Seccion io_map de trial.json (sin rutas absolutas innecesarias fuera de lo pedido)."""
    return {
        key: io_map_ref.get(key)
        for key in (
            "base_map_id", "base_source_hash", "base_map_hash", "physical_channel_count",
            "working_map_path", "snapshot_path", "frozen", "created_at", "resolved_at",
            "bound_channels", "discarded", "error",
        )
    }
