"""
Dos proyectos TIA independientes (Fase 4A-DEFERRED, 6B/6C/6D).

  tia.normal_project     -> proyecto de TRABAJO del Modo Normal. Se importa, sincroniza, compila y
                            (con CARGAR PROGRAMA AL PLC) se descarga. Puede modificarse.
  tia.experiment_master  -> PLANTILLA de Experimentacion. Nunca se modifica: cada evaluacion parte
                            de una copia nueva de su snapshot .zap18.

Persistencia: config/tia_projects.json
  {"tia": {"normal_project":    {"path", "validation", "selected_at"},
           "experiment_master": {"path", "hash", "validation", "status", "snapshot", "selected_at"}}}

`tia_openness_config.json -> project_path` se conserva SOLO como espejo del proyecto Normal para los
consumidores existentes del bridge (lo escribe set_normal_project; nunca el MASTER).

Guards: el Modo Normal nunca usa el MASTER; el MASTER nunca puede ser el proyecto Normal.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

CONFIG_RELATIVE = Path("config") / "tia_projects.json"
NORMAL = "normal_project"
MASTER = "experiment_master"

ERROR_NORMAL_IS_MASTER = "NORMAL_PROJECT_IS_EXPERIMENT_MASTER"
ERROR_MASTER_IS_NORMAL = "EXPERIMENT_MASTER_IS_NORMAL_PROJECT"


class TiaProjectGuardError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def config_path(project_root: Path) -> Path:
    return Path(project_root) / CONFIG_RELATIVE


def load(project_root: Path) -> dict[str, Any]:
    path = config_path(project_root)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    tia = data.setdefault("tia", {})
    tia.setdefault(NORMAL, {})
    tia.setdefault(MASTER, {})
    return data


def save(project_root: Path, data: dict[str, Any]) -> Path:
    path = config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def _same_path(first: Any, second: Any) -> bool:
    if not first or not second:
        return False
    try:
        return Path(first).resolve() == Path(second).resolve()
    except OSError:
        return str(first).lower() == str(second).lower()


def _same_project_folder(first: Any, second: Any) -> bool:
    """Dos .ap18 en la misma carpeta son el mismo proyecto TIA (comparten System/, XRef/, ...)."""
    if not first or not second:
        return False
    return _same_path(Path(first).parent, Path(second).parent)


# ---------------------------------------------------------------------------------------------
# Proyecto Normal
# ---------------------------------------------------------------------------------------------

def get_normal_project(project_root: Path) -> dict[str, Any]:
    """tia.normal_project; si aun no existe, el project_path historico (fuente explicita y marcada)."""
    normal = dict(load(project_root)["tia"][NORMAL])
    if not normal.get("path"):
        import tia_openness

        legacy = str(tia_openness.load_tia_config(project_root).get("project_path", "")).strip()
        if legacy:
            normal.update({"path": legacy, "source": "legacy_tia_openness_config.project_path"})
    return normal


def normal_project_path(project_root: Path) -> str:
    return str(get_normal_project(project_root).get("path") or "")


def set_normal_project(project_root: Path, path: str | Path, plc_name: str | None = None,
                       extra_tia_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Seleccionar el proyecto Normal. Nunca puede ser el MASTER experimental."""
    import tia_openness

    master_path = get_experiment_master(project_root).get("path")
    if _same_path(path, master_path) or _same_project_folder(path, master_path):
        raise TiaProjectGuardError(ERROR_NORMAL_IS_MASTER, f"{path} es el TIA MASTER de Experimentacion.")
    data = load(project_root)
    data["tia"][NORMAL] = {"path": str(path), "validation": None, "selected_at": datetime.now().isoformat(timespec="seconds")}
    save(project_root, data)
    config = tia_openness.load_tia_config(project_root)
    config.update(extra_tia_config or {})
    config["project_path"] = str(path)  # espejo para los consumidores existentes del bridge
    if plc_name is not None:
        config["plc_name"] = plc_name
    tia_openness.save_tia_config(config, project_root)
    return data["tia"][NORMAL]


def validate_normal_project(project_root: Path) -> dict[str, Any]:
    """Validar (sin abrir TIA): archivo .ap18 existente, Openness listo y que no sea el MASTER."""
    import tia_openness

    path = normal_project_path(project_root)
    diagnostic = tia_openness.diagnose_tia_openness(project_root)
    errors = list(diagnostic.get("warnings") or [])
    if not path or not path.lower().endswith(".ap18") or not Path(path).exists():
        errors.append(f"El proyecto Normal no es un .ap18 existente: {path or '(vacio)'}")
    master_path = get_experiment_master(project_root).get("path")
    if _same_path(path, master_path) or _same_project_folder(path, master_path):
        errors.append(f"{ERROR_NORMAL_IS_MASTER}: el proyecto Normal coincide con el TIA MASTER.")
    validation = {"validated_at": datetime.now().isoformat(timespec="seconds"),
                  "status": "VALID" if not errors and diagnostic.get("is_ready") else "INVALID",
                  "openness_ready": bool(diagnostic.get("is_ready")), "errors": errors}
    data = load(project_root)
    data["tia"][NORMAL] = {**get_normal_project(project_root), "validation": validation}
    data["tia"][NORMAL].pop("source", None)
    save(project_root, data)
    return data["tia"][NORMAL]


def assert_normal_not_master(project_root: Path, path: str | Path | None = None) -> None:
    """Guard: el Modo Normal NUNCA usa el MASTER experimental."""
    path = path or normal_project_path(project_root)
    master_path = get_experiment_master(project_root).get("path")
    if _same_path(path, master_path) or _same_project_folder(path, master_path):
        raise TiaProjectGuardError(ERROR_NORMAL_IS_MASTER, f"el Modo Normal no puede usar el TIA MASTER ({path}).")


# ---------------------------------------------------------------------------------------------
# MASTER experimental
# ---------------------------------------------------------------------------------------------

def get_experiment_master(project_root: Path) -> dict[str, Any]:
    return dict(load(project_root)["tia"][MASTER])


def save_experiment_master(project_root: Path, master: dict[str, Any]) -> dict[str, Any]:
    data = load(project_root)
    data["tia"][MASTER] = master
    save(project_root, data)
    return master


def assert_master_not_normal(project_root: Path, master_path: str | Path) -> None:
    normal = normal_project_path(project_root)
    if _same_path(master_path, normal) or _same_project_folder(master_path, normal):
        raise TiaProjectGuardError(ERROR_MASTER_IS_NORMAL, f"{master_path} es el proyecto del Modo Normal; use un proyecto MASTER distinto.")
