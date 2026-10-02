"""
Workspace TIA de ruta corta para la evaluacion diferida (Fase 4A-DEFERRED-PATHS).

TIA Portal V18 rechaza rutas de mas de 143 caracteres (mensaje real de Project.Archive). Las rutas de
resultados de la tesis son mucho mas largas, asi que se separan:

  A) WORKSPACE TIA CORTO:  <tiaw_root>/T0001/           (lo UNICO que ve TIA)
       p/              destino de Projects.Retrieve (copia nueva del snapshot MASTER)
       s.scl           copia verificada del program.scl congelado (fuente que importa TIA)
       T0001.zap18     Project.Archive del proyecto del ensayo
       archived.json / proceed.json   handshake: Python copia y verifica el .zap18 ANTES de la descarga
  B) EVIDENCIA DEL ENSAYO: <trial_dir>/evaluation/attempt_NNN/tia/<trial_id>.zap18 (+ manifest)

El ID corto (T0001, T0002, ...) es independiente del trial_id y nunca se reutiliza (registro
persistente <tiaw_root>/_workspaces.json, que sobrevive a la limpieza de los workspaces).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

# Limite real observado en TIA V18: "The specified path ... is too long. A maximum of 143 characters is allowed."
TIA_PATH_LIMIT = 143
DEFAULT_WORKSPACE_DIRNAME = "tiaw"
REGISTRY_FILENAME = "_workspaces.json"
RETRIEVE_DIRNAME = "p"
SOURCE_FILENAME = "s.scl"
ARCHIVED_SIGNAL = "archived.json"
CHECKPOINTS_FILENAME = "tia_checkpoints.log"
PROCEED_SIGNAL = "proceed.json"

ERROR_PATH_TOO_LONG = "TIA_PATH_TOO_LONG"
ERROR_ARCHIVE_COPY_FAILED = "TIA_ARCHIVE_COPY_FAILED"
ERROR_ARCHIVE_INTEGRITY_FAILED = "TIA_ARCHIVE_INTEGRITY_FAILED"

STATE_ACTIVE = "ACTIVE"
STATE_EVIDENCE_COPIED = "EVIDENCE_COPIED"
STATE_KEPT = "KEPT"
STATE_CLEANED = "CLEANED"

_WINDOWS_LONG_PATH_THRESHOLD = 240


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------------------------
# Filesystem (solo Python): soporte de rutas largas de Windows. TIA nunca recibe estas rutas.
# ---------------------------------------------------------------------------------------------

def fs_path(path: str | Path) -> str:
    """Ruta apta para el filesystem de Python en Windows (prefijo \\\\?\\ si la ruta es larga)."""
    absolute = os.path.abspath(str(path))
    if os.name == "nt" and len(absolute) >= _WINDOWS_LONG_PATH_THRESHOLD and not absolute.startswith("\\\\?\\"):
        return "\\\\?\\" + absolute
    return absolute


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(fs_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_size(path: str | Path) -> int:
    return os.path.getsize(fs_path(path))


# ---------------------------------------------------------------------------------------------
# Raiz, registro e IDs cortos
# ---------------------------------------------------------------------------------------------

def workspace_root(project_root: Path) -> Path:
    """<project_root>/tiaw por defecto; configurable con deferred_workspace_root (tia_openness_config.json)."""
    import tia_openness

    configured = str(tia_openness.load_tia_config(project_root).get("deferred_workspace_root") or "").strip()
    return Path(configured) if configured else Path(project_root) / DEFAULT_WORKSPACE_DIRNAME


def _registry_path(project_root: Path) -> Path:
    return workspace_root(project_root) / REGISTRY_FILENAME


def load_registry(project_root: Path) -> dict[str, Any]:
    path = _registry_path(project_root)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema_version": 1, "last_id": 0, "workspaces": {}}


def _save_registry(project_root: Path, registry: dict[str, Any]) -> None:
    path = _registry_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def format_id(number: int) -> str:
    return f"T{number:04d}"


def allocate(project_root: Path, trial_id: str, attempt: int, trial_dir: Path) -> dict[str, Any]:
    """Nuevo workspace vacio con ID corto nunca usado. Nunca reutiliza el de un ensayo anterior."""
    registry = load_registry(project_root)
    number = int(registry.get("last_id", 0)) + 1
    while (workspace_root(project_root) / format_id(number)).exists() or format_id(number) in registry["workspaces"]:
        number += 1
    workspace_id = format_id(number)
    path = workspace_root(project_root) / workspace_id
    path.mkdir(parents=True, exist_ok=False)
    registry["last_id"] = number
    registry["workspaces"][workspace_id] = {
        "workspace_id": workspace_id, "path": str(path), "trial_id": trial_id, "attempt": attempt,
        "trial_dir": str(trial_dir), "state": STATE_ACTIVE, "created_at": _now(),
    }
    _save_registry(project_root, registry)
    return registry["workspaces"][workspace_id]


def update_entry(project_root: Path, workspace_id: str, **fields: Any) -> dict[str, Any]:
    registry = load_registry(project_root)
    entry = registry["workspaces"].setdefault(workspace_id, {"workspace_id": workspace_id})
    entry.update(fields)
    entry["updated_at"] = _now()
    _save_registry(project_root, registry)
    return entry


def layout(workspace_path: Path, workspace_id: str) -> dict[str, Path]:
    workspace_path = Path(workspace_path)
    return {
        "workspace": workspace_path,
        "retrieve_dir": workspace_path / RETRIEVE_DIRNAME,
        "source_path": workspace_path / SOURCE_FILENAME,
        "archive_dir": workspace_path,
        "archive_name": Path(f"{workspace_id}.zap18"),
        "archive_path": workspace_path / f"{workspace_id}.zap18",
        "archived_signal": workspace_path / ARCHIVED_SIGNAL,
        "proceed_signal": workspace_path / PROCEED_SIGNAL,
    }


# ---------------------------------------------------------------------------------------------
# Validacion de rutas ANTES de llamar a TIA
# ---------------------------------------------------------------------------------------------

def snapshot_contents(snapshot_path: str | Path) -> dict[str, Any]:
    """Nombre del proyecto dentro del .zap18 (ZIP) y entrada interna mas larga."""
    with zipfile.ZipFile(fs_path(snapshot_path)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
    project_files = [name for name in names if name.lower().endswith(".ap18") and "/" not in name]
    if not project_files:
        raise ValueError(f"El snapshot no contiene un proyecto .ap18 en su raiz: {snapshot_path}")
    return {"project_file": project_files[0], "longest_entry": max(names, key=len) if names else ""}


ERROR_INTERNAL_NAME_UNKNOWN = "MASTER_INTERNAL_PROJECT_NAME_UNKNOWN"


def validate_paths(workspace_path: Path, workspace_id: str, internal_project_name: str | None,
                   limit: int = TIA_PATH_LIMIT) -> dict[str, Any]:
    """
    Longitud de cada ruta que recibira TIA. Para Retrieve se usa el NOMBRE INTERNO REAL del proyecto
    (registrado al VALIDAR MASTER; el Retrieve real creo p/S71500_MASTER/S71500_MASTER.ap18), en el
    peor caso con subcarpeta. Nunca se infiere del nombre del snapshot.
    """
    paths = layout(workspace_path, workspace_id)
    retrieve_dir = os.path.abspath(str(paths["retrieve_dir"]))
    if not internal_project_name:
        return {"ok": False, "limit": limit, "checks": [], "max_path_length": None, "retrieve_path_length": None,
                "retrieve_path_length_without_subfolder": None, "archive_path_length": None, "source_path_length": None,
                "internal_project_name": None,
                "errors": [f"{ERROR_INTERNAL_NAME_UNKNOWN}: el MASTER no tiene nombre interno registrado; pulse VALIDAR MASTER."]}
    project_file = f"{internal_project_name}.ap18"
    without_subfolder = os.path.join(retrieve_dir, project_file)
    with_subfolder = os.path.join(retrieve_dir, internal_project_name, project_file)
    checks = [
        {"operation": "retrieve_target_dir", "path": retrieve_dir},
        {"operation": "retrieve_project_file", "path": with_subfolder, "note": "peor caso (subcarpeta con el nombre del proyecto)",
         "path_without_subfolder": without_subfolder},
        {"operation": "import_source", "path": os.path.abspath(str(paths["source_path"]))},
        {"operation": "archive", "path": os.path.abspath(str(paths["archive_path"]))},
    ]
    for check in checks:
        check["path_length"] = len(check["path"])
        check["limit"] = limit
        check["ok"] = check["path_length"] <= limit
    by_operation = {check["operation"]: check for check in checks}
    return {
        "ok": all(check["ok"] for check in checks),
        "limit": limit,
        "retrieve_path_length": by_operation["retrieve_project_file"]["path_length"],
        "retrieve_path_length_without_subfolder": len(without_subfolder),
        "archive_path_length": by_operation["archive"]["path_length"],
        "source_path_length": by_operation["import_source"]["path_length"],
        "max_path_length": max(check["path_length"] for check in checks),
        "internal_project_name": internal_project_name,
        "checks": checks,
        "errors": [f"{ERROR_PATH_TOO_LONG}: {check['operation']} {check['path']} ({check['path_length']} > {limit})"
                   for check in checks if not check["ok"]],
    }


# ---------------------------------------------------------------------------------------------
# Copia verificada del .zap18 a la evidencia del ensayo
# ---------------------------------------------------------------------------------------------

def copy_archive_to_evidence(workspace_archive: Path, evidence_path: Path, reported_sha256: str | None = None) -> dict[str, Any]:
    """Copia el .zap18 del workspace a la carpeta del ensayo y exige hash identico y tamano > 0."""
    result: dict[str, Any] = {"workspace_path": str(workspace_archive), "evidence_path": str(evidence_path),
                              "workspace_hash": None, "evidence_hash": None, "copied_ok": False, "error": None}
    try:
        if not os.path.isfile(fs_path(workspace_archive)) or file_size(workspace_archive) <= 0:
            result["error"] = f"{ERROR_ARCHIVE_INTEGRITY_FAILED}: el .zap18 del workspace no existe o esta vacio."
            return result
        result["workspace_hash"] = sha256(workspace_archive)
        if reported_sha256 and result["workspace_hash"] != reported_sha256:
            result["error"] = f"{ERROR_ARCHIVE_INTEGRITY_FAILED}: el .zap18 del workspace no coincide con el hash informado por TIA."
            return result
        os.makedirs(fs_path(Path(evidence_path).parent), exist_ok=True)
        if os.path.exists(fs_path(evidence_path)):
            result["error"] = f"{ERROR_ARCHIVE_COPY_FAILED}: la evidencia ya existe (nunca se sobrescribe)."
            return result
        shutil.copyfile(fs_path(workspace_archive), fs_path(evidence_path))
    except OSError as error:
        result["error"] = f"{ERROR_ARCHIVE_COPY_FAILED}: {error}"
        return result
    result["evidence_hash"] = sha256(evidence_path)
    result["evidence_size_bytes"] = file_size(evidence_path)
    if result["evidence_hash"] != result["workspace_hash"] or result["evidence_size_bytes"] <= 0:
        result["error"] = f"{ERROR_ARCHIVE_INTEGRITY_FAILED}: la copia del .zap18 no es identica al original del workspace."
        return result
    result["copied_ok"] = True
    result["copied_at"] = _now()
    return result


# ---------------------------------------------------------------------------------------------
# Checkpoints persistentes del bridge (sobreviven a una caida de TIA)
# ---------------------------------------------------------------------------------------------

def parse_checkpoints(path: str | Path) -> dict[str, Any]:
    """
    Lee tia_checkpoints.log (timestamp TAB checkpoint TAB detalle). Devuelve la ultima operacion
    COMPLETADA, la primera FALLIDA y una operacion INICIADA que nunca termino (caida a mitad).
    """
    entries: list[dict[str, str]] = []
    if Path(path).is_file():
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split("\t", 2)
            if len(parts) >= 2:
                entries.append({"at": parts[0], "checkpoint": parts[1], "detail": parts[2] if len(parts) > 2 else ""})
    started = {}
    for entry in entries:
        name = entry["checkpoint"]
        for suffix in ("_started", "_completed", "_failed"):
            if name.endswith(suffix):
                operation = name[: -len(suffix)]
                if suffix == "_started":
                    started[operation] = entry
                else:
                    started.pop(operation, None)
    completed = [e["checkpoint"] for e in entries if e["checkpoint"].endswith("_completed")]
    failed = [e for e in entries if e["checkpoint"].endswith("_failed")]
    return {
        "entries": entries,
        "last_completed": completed[-1] if completed else None,
        "first_failed": failed[0]["checkpoint"] if failed else None,
        "first_failed_detail": failed[0]["detail"] if failed else None,
        "unfinished": [f"{operation}_started" for operation in started],
    }


# ---------------------------------------------------------------------------------------------
# Limpieza
# ---------------------------------------------------------------------------------------------

def remove_workspace(project_root: Path, workspace_id: str) -> bool:
    """Borra un workspace SOLO si su evidencia quedo copiada y verificada (estado EVIDENCE_COPIED/KEPT)."""
    entry = load_registry(project_root)["workspaces"].get(workspace_id) or {}
    if entry.get("state") not in (STATE_EVIDENCE_COPIED, STATE_KEPT) or not entry.get("evidence_copied_ok"):
        return False
    path = workspace_root(project_root) / workspace_id
    if path.exists():
        shutil.rmtree(fs_path(path))
    update_entry(project_root, workspace_id, state=STATE_CLEANED, cleaned_at=_now())
    return True


def cleanup_workspaces(project_root: Path, include_kept: bool = False) -> dict[str, Any]:
    """
    Limpieza manual. Borra los workspaces con evidencia verificada (y los KEPT si include_kept).
    Nunca borra ACTIVE ni carpetas huerfanas: estas solo se informan para revision manual.
    """
    registry = load_registry(project_root)
    removed, kept, orphans = [], [], []
    for workspace_id, entry in sorted(registry["workspaces"].items()):
        state = entry.get("state")
        if state == STATE_EVIDENCE_COPIED or (include_kept and state == STATE_KEPT and entry.get("evidence_copied_ok")):
            if remove_workspace(project_root, workspace_id):
                removed.append(workspace_id)
        elif state in (STATE_ACTIVE, STATE_KEPT):
            kept.append({"workspace_id": workspace_id, "state": state, "reason": entry.get("keep_reason")})
    root = workspace_root(project_root)
    if root.exists():
        for child in root.iterdir():
            if child.is_dir() and child.name not in registry["workspaces"]:
                orphans.append(str(child))
    return {"removed": removed, "kept": kept, "orphans": orphans}
