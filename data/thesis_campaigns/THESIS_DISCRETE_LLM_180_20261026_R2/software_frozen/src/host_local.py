"""
Identificador OPCIONAL de la PC (config/host_local.json, ignorado por Git): solo etiqueta la
trazabilidad local (p. ej. quien inicializo un mapa working). Nunca usa el hostname real ni datos
personales; si el archivo no existe, la aplicacion funciona igual (host_id = None).

    {"host_id": "DEV_PC"}
"""
from __future__ import annotations

import json
from pathlib import Path

HOST_LOCAL_RELATIVE = Path("config") / "host_local.json"


def host_local_path(project_root: Path) -> Path:
    return Path(project_root) / HOST_LOCAL_RELATIVE


def load_host_id(project_root: Path) -> str | None:
    path = host_local_path(project_root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    host_id = str((payload or {}).get("host_id") or "").strip() if isinstance(payload, dict) else ""
    return host_id or None
