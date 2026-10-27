from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from plc_maps.schema import new_map_payload
from utils import ensure_directory, load_json_file, sanitize_filename


PLC_MAPS_DIRNAME = "plc_maps"
MAP_FILE_SUFFIX = ".json"
RESERVED_STEMS = {"_active_map"}
MAX_HISTORY_ENTRIES = 500

# Mapa BASE vs WORKING (dos PCs, docs/multi_pc_setup.md):
#   <id>_base.json     versionado, estable: hardware/direcciones de referencia. Nunca se lista ni se
#                      edita desde la GUI; Experimentacion lo usa como fuente congelada.
#   <id>_working.json  local por PC (ignorado por Git): lo que lista/selecciona/escribe la aplicacion
#                      (Modo Normal, IOAllocator, MAP_CONFIG). Si no existe se inicializa desde el base.
BASE_SUFFIX = "_base"
WORKING_SUFFIX = "_working"
LEGACY_BACKUP_SUFFIX = ".pre_working.bak"


def get_plc_maps_dir(project_root: Path) -> Path:
    return project_root / "data" / PLC_MAPS_DIRNAME


def is_base_map_path(path: Path) -> bool:
    return Path(path).stem.endswith(BASE_SUFFIX)


def is_working_map_path(path: Path) -> bool:
    return Path(path).stem.endswith(WORKING_SUFFIX)


def working_path_for_base(base_path: Path) -> Path:
    base_path = Path(base_path)
    return base_path.with_name(base_path.stem[: -len(BASE_SUFFIX)] + WORKING_SUFFIX + MAP_FILE_SUFFIX)


def base_path_for(path: Path) -> Path | None:
    """Mapa base versionado del que deriva `path` (working), o None si `path` no tiene base."""
    path = Path(path)
    if is_base_map_path(path):
        return path
    if is_working_map_path(path):
        candidate = path.with_name(path.stem[: -len(WORKING_SUFFIX)] + BASE_SUFFIX + MAP_FILE_SUFFIX)
        return candidate if candidate.exists() else None
    return None


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_working_maps(project_root: Path) -> list[dict[str, Any]]:
    """
    Crea <id>_working.json para cada <id>_base.json que todavia no lo tenga (PC nueva o primera
    ejecucion tras la separacion base/working). Fuente:
      1. el mapa legacy <id>.json si existe (conserva las asignaciones reales de esa PC; despues se
         renombra a <id>.json.pre_working.bak para que no quede duplicado en la lista);
      2. si no, una copia exacta del base.
    Registra la trazabilidad en metadata.working_copy (origen, hash del origen, fecha, host_id
    opcional). Nunca modifica el base. Devuelve las inicializaciones realizadas.
    """
    from host_local import load_host_id  # import diferido: modulo de configuracion local opcional

    maps_dir = get_plc_maps_dir(project_root)
    created: list[dict[str, Any]] = []
    if not maps_dir.exists():
        return created
    for base_path in sorted(maps_dir.glob(f"*{BASE_SUFFIX}{MAP_FILE_SUFFIX}")):
        working_path = working_path_for_base(base_path)
        if working_path.exists():
            continue
        legacy_path = base_path.with_name(base_path.stem[: -len(BASE_SUFFIX)] + MAP_FILE_SUFFIX)
        source_path = legacy_path if legacy_path.exists() else base_path
        try:
            payload = load_json_file(source_path)
        except (FileNotFoundError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        record = {
            "initialized_from": f"data/{PLC_MAPS_DIRNAME}/{source_path.name}",
            "initialized_from_kind": "legacy_local_map" if source_path == legacy_path else "base_map",
            "source_sha256": _file_sha256(source_path),
            "base_map": f"data/{PLC_MAPS_DIRNAME}/{base_path.name}",
            "base_sha256": _file_sha256(base_path),
            "initialized_at": datetime.now().isoformat(timespec="seconds"),
            "host_id": load_host_id(project_root),
        }
        metadata = dict(payload.get("metadata") or {})
        metadata["working_copy"] = record
        payload["metadata"] = metadata
        working_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        if source_path == legacy_path:
            legacy_path.replace(legacy_path.with_name(legacy_path.name + LEGACY_BACKUP_SUFFIX))
        created.append({"working": working_path, **record})
    return created


def _map_files(maps_dir: Path) -> list[Path]:
    if not maps_dir.exists():
        return []
    return sorted(
        path for path in maps_dir.glob(f"*{MAP_FILE_SUFFIX}")
        if path.stem not in RESERVED_STEMS and not is_base_map_path(path)
    )


def list_plc_maps(project_root: Path) -> list[dict[str, Any]]:
    """Return lightweight summaries (metadata only) for every saved map (working maps, never bases)."""
    ensure_working_maps(project_root)
    summaries: list[dict[str, Any]] = []
    for path in _map_files(get_plc_maps_dir(project_root)):
        try:
            payload = load_json_file(path)
        except (FileNotFoundError, ValueError):
            continue
        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        summaries.append(
            {
                "path": path,
                "map_id": metadata.get("map_id", path.stem),
                "name": metadata.get("name", path.stem),
                "version": metadata.get("version", 1),
                "variable_count": len(payload.get("variables", [])) if isinstance(payload, dict) else 0,
                "sync_status": metadata.get("sync_status", "unknown"),
                "dirty": bool(metadata.get("dirty", False))
            }
        )
    return summaries


def load_plc_map(path: Path) -> dict[str, Any]:
    return load_json_file(path)


def _map_path_for_id(project_root: Path, map_id: str) -> Path:
    safe_stem = sanitize_filename(map_id).lower() or "mapa"
    return get_plc_maps_dir(project_root) / f"{safe_stem}{MAP_FILE_SUFFIX}"


def create_plc_map(
    project_root: Path,
    name: str,
    description: str = "",
    target_platform: str = "SIEMENS_SCL_V18",
    variables: list[dict[str, Any]] | None = None
) -> Path:
    maps_dir = ensure_directory(get_plc_maps_dir(project_root))
    map_id = re.sub(r"\s+", "_", name.strip()) or f"mapa_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    path = _map_path_for_id(project_root, map_id)
    suffix = 2
    while path.exists():
        path = _map_path_for_id(project_root, f"{map_id}_{suffix}")
        suffix += 1

    payload = new_map_payload(map_id=path.stem, name=name.strip() or path.stem, description=description, target_platform=target_platform)
    if variables is not None:
        payload["variables"] = variables

    maps_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_plc_map(
    path: Path,
    variables: list[dict[str, Any]],
    metadata_patch: dict[str, Any] | None = None,
    history_entries: list[dict[str, Any]] | None = None
) -> None:
    """
    Persist a map file, preserving/patching its metadata block. `history_entries` (section 26:
    timestamp/address/old_name/new_name/old_state/new_state/source) are APPENDED to the map's
    existing `history` list, never replacing it - this is the single write chokepoint so it is
    the one place a full trail of map changes can be kept, capped at MAX_HISTORY_ENTRIES.
    """
    existing_payload: dict[str, Any] = {}
    if path.exists():
        try:
            existing_payload = load_json_file(path)
        except (FileNotFoundError, ValueError):
            existing_payload = {}

    metadata = dict(existing_payload.get("metadata") or new_map_payload(path.stem, path.stem)["metadata"])
    metadata["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if metadata_patch:
        metadata.update(metadata_patch)

    history = list(existing_payload.get("history", []))
    if history_entries:
        history.extend(history_entries)
        history = history[-MAX_HISTORY_ENTRIES:]

    payload = {
        "schema_version": existing_payload.get("schema_version", 1),
        "metadata": metadata,
        "naming_convention": existing_payload.get("naming_convention", new_map_payload(path.stem, path.stem)["naming_convention"]),
        "variables": variables,
        "history": history
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def get_map_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = load_json_file(path)
    except (FileNotFoundError, ValueError):
        return []
    return list(payload.get("history", []))


def delete_plc_map(path: Path) -> None:
    if path.exists():
        path.unlink()
