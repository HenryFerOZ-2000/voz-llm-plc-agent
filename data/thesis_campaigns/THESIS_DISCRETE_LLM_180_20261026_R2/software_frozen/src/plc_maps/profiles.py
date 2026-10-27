from __future__ import annotations

from pathlib import Path
from typing import Any

from ir_builder import EXTERNAL_PREFIXES
from plc_maps.store import get_plc_maps_dir, list_plc_maps, load_plc_map
from utils import build_io_map_index, load_json_file

PROFILES_FILENAME = "profiles.json"
SIMULATION_MAP_NAME = "MAPA_SIMULACION_COMPLETO"
HARDWARE_MAP_NAME = "MAPA_BANCO_FISICO"
PID_SIMULATION_MAP_NAME = "MAPA_PID_SIMULACION"
PID_HARDWARE_MAP_NAME = "MAPA_PID_BANCO_FISICO"
GENERAL_PROFILE_LABEL = "GENERAL / SIN FILTRO"


def _readiness_map_names(profile: dict[str, Any]) -> tuple[str, str]:
    """
    D01-D20 keep checking readiness against the discrete maps; P01-P12 check against the PID
    maps instead - decided purely from the case_id prefix, never mixed in the same profile.
    """
    case_id = str(profile.get("case_id", ""))
    if case_id.startswith("P"):
        return PID_SIMULATION_MAP_NAME, PID_HARDWARE_MAP_NAME
    return SIMULATION_MAP_NAME, HARDWARE_MAP_NAME


def get_profiles_path(project_root: Path) -> Path:
    return get_plc_maps_dir(project_root) / PROFILES_FILENAME


def load_profiles(project_root: Path) -> list[dict[str, Any]]:
    path = get_profiles_path(project_root)
    if not path.exists():
        return []
    try:
        payload = load_json_file(path)
    except (FileNotFoundError, ValueError):
        return []
    profiles = payload.get("profiles", []) if isinstance(payload, dict) else []
    return profiles if isinstance(profiles, list) else []


def get_profile(project_root: Path, profile_id: str) -> dict[str, Any] | None:
    for profile in load_profiles(project_root):
        if profile.get("profile_id") == profile_id:
            return profile
    return None


def _find_map_variable_names(project_root: Path, map_name: str) -> set[str] | None:
    """Return the variable-name set of the library map with this display name, or None if absent."""
    for summary in list_plc_maps(project_root):
        if summary.get("name") == map_name:
            payload = load_plc_map(summary["path"])
            return set(build_io_map_index(payload))
    return None


def compute_readiness(allowed_variables: list[str], map_variable_names: set[str]) -> tuple[bool, list[str]]:
    """Pure check: which allowed_variables are absent from map_variable_names."""
    missing = [name for name in allowed_variables if name not in map_variable_names]
    return len(missing) == 0, missing


def profile_readiness_summary(project_root: Path, profile: dict[str, Any]) -> dict[str, Any]:
    """Compute simulation_ready/hardware_ready dynamically against the current library maps."""
    allowed_variables = profile.get("allowed_variables", [])
    simulation_map_name, hardware_map_name = _readiness_map_names(profile)

    simulation_names = _find_map_variable_names(project_root, simulation_map_name)
    if simulation_names is None:
        simulation_ready, missing_simulation = False, [f"{simulation_map_name} no encontrado en la biblioteca."]
    else:
        simulation_ready, missing_simulation = compute_readiness(allowed_variables, simulation_names)

    hardware_names = _find_map_variable_names(project_root, hardware_map_name)
    if hardware_names is None:
        hardware_ready, missing_hardware = False, [f"{hardware_map_name} no encontrado en la biblioteca."]
    else:
        hardware_ready, missing_hardware = compute_readiness(allowed_variables, hardware_names)

    return {
        "simulation_ready": simulation_ready,
        "missing_simulation_variables": missing_simulation,
        "hardware_ready": hardware_ready,
        "missing_hardware_variables": missing_hardware
    }


def check_case_compatibility(semantic_output: dict[str, Any], profile: dict[str, Any] | None) -> dict[str, Any]:
    """
    Compara los recursos externos (I_/Q_) que el comando interpretado requiere contra los
    autorizados por el perfil experimental activo. Reutiliza semantic_validation.unauthorized_tags,
    que ya excluye recursos internos (M_/T_/C_/R_/F_) - esos siempre puede generarlos ir_builder
    sin importar el perfil, asi que nunca cuentan como incompatibilidad experimental.
    """
    if profile is None:
        return {"compatible": True, "missing_external": []}
    unauthorized = list((semantic_output.get("semantic_validation") or {}).get("unauthorized_tags", []))
    return {"compatible": not unauthorized, "missing_external": unauthorized}


def apply_profile_filter(io_map: dict[str, Any], profile: dict[str, Any] | None) -> dict[str, Any]:
    """
    Restrict the external (I_/Q_) variables of io_map to the profile's allowed_variables.
    Internal resources (M_/T_/C_/R_/F_) are never filtered - ir_builder can still auto-generate
    them regardless of the active profile. profile=None returns io_map unchanged.
    """
    if profile is None:
        return io_map

    allowed_external = set(profile.get("allowed_variables", []))
    variables = io_map.get("variables", [])
    filtered_variables = [
        variable for variable in variables
        if not str(variable.get("name", "")).startswith(EXTERNAL_PREFIXES)
        or variable.get("name") in allowed_external
    ]
    return {**io_map, "variables": filtered_variables}
