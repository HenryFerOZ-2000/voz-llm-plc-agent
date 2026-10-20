"""
Respaldo de resultados experimentales (tras cada lote de voz y al cerrar cada sesion FORMAL).

Copia results/formal_audio, results/experiments y results/batches a un destino externo y escribe
backup_manifest.json con el SHA-256 de cada archivo copiado (incluidos los WAV del corpus pareado).
Nunca borra ni modifica el origen; un destino ya existente no se sobrescribe.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

BACKUP_SOURCES = ("results/formal_audio", "results/formal_audio_discrete_v2", "results/experiments", "results/batches")
BACKUP_MANIFEST = "backup_manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_results(project_root: Path, destination: Path, label: str | None = None,
                   sources: tuple[str, ...] = BACKUP_SOURCES, now: datetime | None = None) -> dict[str, Any]:
    """Copia las fuentes existentes a destination/<label|marca de tiempo>/ y devuelve el manifiesto de hashes."""
    project_root = Path(project_root)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    target = Path(destination) / (label or f"results_backup_{stamp}")
    if target.exists():
        raise FileExistsError(f"{target} ya existe: un respaldo nunca se sobrescribe.")
    files: list[dict[str, Any]] = []
    copied_sources: list[str] = []
    for source in sources:
        origin = project_root / source
        if not origin.is_dir():
            continue
        copied_sources.append(source)
        for path in sorted(p for p in origin.rglob("*") if p.is_file()):
            relative = path.relative_to(project_root)
            copy = target / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copy)
            digest = _sha256(copy)
            if digest != _sha256(path):
                raise OSError(f"copia no identica: {relative}")
            files.append({"path": relative.as_posix(), "sha256": digest, "bytes": copy.stat().st_size})
    manifest = {"schema_version": 1, "created_at": (now or datetime.now()).isoformat(timespec="seconds"),
                "project_root": str(project_root), "sources": copied_sources, "file_count": len(files),
                "audio_files": sum(1 for f in files if f["path"].lower().endswith(".wav")),
                "zap18_files": sum(1 for f in files if f["path"].lower().endswith(".zap18")), "files": files}
    target.mkdir(parents=True, exist_ok=True)
    (target / BACKUP_MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"target": str(target), **manifest}


def verify_backup(target: Path) -> dict[str, Any]:
    """Recalcula los hashes del respaldo contra su manifiesto (READ-ONLY)."""
    target = Path(target)
    manifest = json.loads((target / BACKUP_MANIFEST).read_text(encoding="utf-8"))
    errors = [f"{f['path']}: {'falta' if not (target / f['path']).is_file() else 'hash distinto'}"
              for f in manifest["files"]
              if not (target / f["path"]).is_file() or _sha256(target / f["path"]) != f["sha256"]]
    return {"ok": not errors, "errors": errors, "file_count": manifest["file_count"]}
