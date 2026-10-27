"""
Seleccion DETERMINISTA del mapa base de un ensayo experimental (config/experiment_maps.json).

La decision se deriva SOLO de los roles IO del Oracle congelado del caso (nunca de su case_id):
  - entradas/salidas digitales que el ensayo necesita como minimo (un canal por rol IO);
  - senales RESTRINGIDAS (p.ej. SAFETY_TRIP): solo las aporta un canal declarado explicitamente en
    metadata.harness_signals del mapa, nunca un canal FREE cualquiera.
Se recorren los mapas por prioridad y se elige el primero que cubre todo. El banco fisico es el
preferido; el mapa de simulacion solo entra cuando el banco no puede representar el caso. La seleccion
(map_id, map_hash, source, simulation_only, motivo) queda congelada como evidencia del ensayo.

map_hash: SHA-256 del JSON canonico (independiente de finales de linea y de la PC).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from trial_experiments.trial_io_map import build_experiment_base_map, physical_signal

POLICY_RELATIVE_PATH = Path("config") / "experiment_maps.json"
SOURCE = "config/experiment_maps.json"
ERROR_NO_MAP = "EXPERIMENT_MAP_UNAVAILABLE"


def load_policy(project_root: Path) -> dict[str, Any]:
    return json.loads((Path(project_root) / POLICY_RELATIVE_PATH).read_text(encoding="utf-8"))


def canonical_map_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def oracle_requirements(oracle: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Necesidades de E/S del ensayo segun los roles IO del Oracle."""
    restricted = policy.get("restricted_signals") or {}
    inputs = outputs = 0
    signals: set[str] = set()
    for role in (oracle.get("roles") or {}).values():
        if role.get("binding", "IO") != "IO":
            continue
        paths = set(role.get("semantic_paths") or [])
        if role.get("kind") == "INPUT":
            inputs += 1
        else:
            outputs += 1
        for name, spec in restricted.items():
            if paths & set(spec.get("semantic_paths") or []):
                signals.add(name)
    return {"digital_inputs": inputs, "digital_outputs": outputs, "restricted_signals": sorted(signals)}


def map_capabilities(source_map: dict[str, Any]) -> dict[str, Any]:
    """Capacidad del mapa como base experimental (inventario fisico, sin residuos de asignaciones)."""
    metadata = source_map.get("metadata") or {}
    base = build_experiment_base_map(source_map, str(metadata.get("map_id") or "map"))
    names = {str(variable.get("name")) for variable in base["variables"]}
    counts = {"DI": 0, "DO": 0}
    for variable in base["variables"]:
        signal = physical_signal(variable.get("location"))
        if signal in counts:
            counts[signal] += 1
    harness = {name: tag for name, tag in (metadata.get("harness_signals") or {}).items() if tag in names}
    return {"digital_inputs": counts["DI"], "digital_outputs": counts["DO"], "restricted_signals": sorted(harness),
            "simulation_only": bool(metadata.get("simulation_only", False)), "harness_signals": harness}


def select_experiment_map(project_root: Path, oracle: dict[str, Any]) -> dict[str, Any]:
    project_root = Path(project_root)
    policy = load_policy(project_root)
    needs = oracle_requirements(oracle, policy)
    rejected: list[dict[str, Any]] = []
    for entry in sorted(policy.get("maps") or [], key=lambda item: item.get("priority", 99)):
        path = project_root / entry["path"]
        source_map = json.loads(path.read_text(encoding="utf-8-sig"))
        capabilities = map_capabilities(source_map)
        missing = []
        if capabilities["digital_inputs"] < needs["digital_inputs"]:
            missing.append(f"entradas digitales {capabilities['digital_inputs']} < {needs['digital_inputs']}")
        if capabilities["digital_outputs"] < needs["digital_outputs"]:
            missing.append(f"salidas digitales {capabilities['digital_outputs']} < {needs['digital_outputs']}")
        lacking = sorted(set(needs["restricted_signals"]) - set(capabilities["restricted_signals"]))
        if lacking:
            missing.append("senales restringidas no disponibles: " + ", ".join(lacking))
        if missing:
            rejected.append({"map_id": entry["map_id"], "missing": missing})
            continue
        return {
            "map_id": entry["map_id"],
            "path": str(path),
            "map_hash": canonical_map_hash(source_map),
            "source": SOURCE,
            "simulation_only": capabilities["simulation_only"],
            "harness_signals": capabilities["harness_signals"],
            "requirements": needs,
            "rejected": rejected,
            "reason": (f"primer mapa por prioridad que cubre {needs}"
                       + (f"; descartados: {rejected}" if rejected else "")),
        }
    return {"map_id": None, "path": None, "map_hash": None, "source": SOURCE, "simulation_only": None,
            "requirements": needs, "rejected": rejected, "error": ERROR_NO_MAP,
            "reason": f"Ningun mapa experimental cubre {needs}: {rejected}"}


def selection_evidence(selection: dict[str, Any]) -> dict[str, Any]:
    """Seccion experiment_map de trial.json (congelada al preparar el ensayo)."""
    return {key: selection.get(key) for key in ("map_id", "map_hash", "source", "simulation_only", "harness_signals",
                                                "requirements", "reason")}


__all__ = ["select_experiment_map", "selection_evidence", "oracle_requirements", "map_capabilities",
           "canonical_map_hash", "ERROR_NO_MAP"]
