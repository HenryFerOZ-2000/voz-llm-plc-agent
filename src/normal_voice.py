"""
MODO NORMAL — flujo automatico por voz (producto, no Experimentacion).

  CAPTURAR Y EJECUTAR POR VOZ -> audio -> ASR -> transcripcion en el cuadro de comando ->
  (sin otro clic) mismo pipeline Normal (semantica, IOAllocator, IR, SCL, verificador,
  PLC_Agent_IO, proyecto TIA NORMAL, compilacion) -> descarga automatica al destino Normal.

Configuracion persistente en config/normal_voice.json:
  normal_voice.auto_execute  (true)  ejecutar el pipeline al terminar la transcripcion
  normal_voice.auto_download (true)  descargar automaticamente si todo pasa

Solo usa tia.normal_project (via el pipeline Normal existente). Nunca el TIA MASTER experimental,
tiaw/, Oracles ni el benchmark.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_RELATIVE = Path("config") / "normal_voice.json"
DEFAULTS = {"auto_execute": True, "auto_download": True}

STAGES = ("Captura", "Transcripcion", "Semantica", "I/O", "Generacion", "Verificacion", "Compilacion", "Descarga")
FINAL_LOADED = "PROGRAMA CARGADO"


def config_path(project_root: Path) -> Path:
    return Path(project_root) / CONFIG_RELATIVE


def load_config(project_root: Path) -> dict[str, Any]:
    path = config_path(project_root)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    section = data.get("normal_voice") if isinstance(data.get("normal_voice"), dict) else {}
    return {**DEFAULTS, **{k: bool(v) for k, v in section.items() if k in DEFAULTS}}


def save_config(project_root: Path, **values: bool) -> dict[str, Any]:
    config = {**load_config(project_root), **{k: bool(v) for k, v in values.items() if k in DEFAULTS}}
    path = config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"normal_voice": config}, indent=2, ensure_ascii=False), encoding="utf-8")
    return config


SOURCE_VOICE = "voice"
SOURCE_TEXT = "text"


def new_flow(project_root: Path, source: str = SOURCE_VOICE) -> dict[str, Any]:
    """
    Estado de UNA ejecucion Normal con descarga encadenada (se descarta al terminar).
      voice -> CAPTURAR Y EJECUTAR POR VOZ (auto_download segun configuracion)
      text  -> EJECUTAR Y CARGAR AL PLC (siempre descarga si todo pasa)
    Ambos usan el MISMO pipeline Normal (execute_full_pipeline); solo cambian estos flags.
    """
    config = load_config(project_root)
    stages = {name: "pending" for name in STAGES}
    if source == SOURCE_TEXT:
        stages["Captura"] = stages["Transcripcion"] = "skipped"
    return {"active": True, "source": source,
            "auto_execute": True if source == SOURCE_TEXT else config["auto_execute"],
            "auto_download": True if source == SOURCE_TEXT else config["auto_download"],
            "stages": stages, "clarification_requested": False, "clarification_pending": False,
            "failed_stage": None, "final": None, "transcript": None}


def download_allowed(flow: dict[str, Any] | None, compile_passed: bool) -> tuple[bool, str]:
    """
    La descarga encadenada solo ocurre si: ejecucion con descarga activa (voz o EJECUTAR Y CARGAR),
    auto_download, sin aclaracion PENDIENTE, semantica/I-O/generacion/verificacion OK y compilacion
    TIA aprobada. (El destino Normal valido y la confirmacion de PLC fisico se comprueban en la GUI.)
    """
    if not flow or not flow.get("active"):
        return False, "no es una ejecucion con descarga encadenada"
    if not flow.get("auto_download"):
        return False, "descarga automatica desactivada"
    if flow.get("clarification_pending"):
        # Solo una aclaracion PENDIENTE bloquea; una aclaracion respondida y reprocesada no.
        return False, "hay una aclaracion pendiente: no se descarga"
    for stage in ("Semantica", "I/O", "Generacion", "Verificacion"):
        if flow["stages"].get(stage) != "ok":
            return False, f"etapa {stage} no aprobada"
    if not compile_passed:
        return False, "compilacion TIA no aprobada"
    return True, "ok"


def stage_text(flow: dict[str, Any] | None) -> str:
    if not flow:
        return ""
    marks = {"ok": "✓", "fail": "✗", "running": "…", "pending": "·", "skipped": "-"}
    line = "  ".join(f"{marks.get(state, '·')} {name}" for name, state in flow["stages"].items())
    if flow.get("final"):
        line += f"\n{flow['final']}"
    return line
