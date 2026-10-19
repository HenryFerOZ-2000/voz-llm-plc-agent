"""
MODO NORMAL — bindings del PROGRAMA vs configuracion fisica del banco.

El mapa mezcla dos cosas que aqui se separan:

  * configuracion FISICA persistente de cada canal (direccion, clase, tipo, unidad, rango, tipo de senal,
    sensor conectado, ...): describe el hardware cableado y NUNCA se borra al cambiar de programa;
  * BINDING LOGICO del programa actual: nombre funcional + estado + procedencia de la asignacion.

Estados:
  FREE      no lo usa el programa actual; disponible.
  ASSIGNED  lo usa el programa ACTUAL. Dentro de ese programa no se reasigna a otra funcion; al generar un
            PROGRAMA NUEVO, si su asignacion fue AUTOMATICA, vuelve al pool (en una copia de trabajo: el
            mapa real solo cambia con el commit del programa nuevo verificado).
  LOCKED    proteccion persistente entre programas: nunca se reasigna ni cambia de funcion.

Procedencia (`assignment_source`): AUTO (la eligio el IOAllocator) o MANUAL (direccion dicha por el usuario o
editor del mapa). `persistent: true` protege un canal como MANUAL. `owner_program_id` = programa que lo usa.
Un ASSIGNED sin procedencia registrada (mapas anteriores) se infiere del historial del mapa; sin historial se
trata como AUTO (no esta LOCKED ni reservado manualmente).
"""
from __future__ import annotations

import copy
import re
import unicodedata
from datetime import datetime
from typing import Any

STATE_FREE, STATE_ASSIGNED, STATE_LOCKED = "FREE", "ASSIGNED", "LOCKED"
SOURCE_AUTO, SOURCE_MANUAL = "AUTO", "MANUAL"
SCOPE_NEW = "NEW_PROGRAM"
SCOPE_EXTEND = "EXTEND_PROGRAM"
BINDING_FIELDS = ("assignment_source", "owner_program_id")
CURRENT_PROGRAM_KEY = "current_program"
# Fuentes del historial del mapa que significan "lo eligio el usuario". TEXT_EXPLICIT no cuenta: los flujos
# automaticos anteriores lo registraban tambien para asignaciones implicitas.
_MANUAL_HISTORY_SOURCES = {"MANUAL_EDITOR", "VOICE_EXPLICIT"}


def _fold(text: Any) -> str:
    plain = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", plain).split())


# Alcance del comando: un programa NUEVO es el defecto; solo una orden que AGREGA/MODIFICA explicitamente el
# programa existente lo extiende. Verbos de la operacion, nunca frases completas ni nombres de maquinas.
_NEW_PROGRAM_CUES = re.compile(r"\b(nuevo programa|programa nuevo|otro programa|desde cero|crea(r)? (un|el) programa|"
                               r"reemplaza(r)? el programa|borra(r)? el programa)\b")
_EXTEND_CUES = re.compile(r"^(y )?(ahora )?(tambien |ademas )?(anade|anadele|agrega|agregale|anadir|agregar|incluye|"
                          r"incorpora|suma)\b|\b(ademas|tambien)\b|\b(al|del|en el) programa (actual|existente|anterior)\b|"
                          r"\b(modifica|cambia|ajusta|quita|elimina|retira)\b.*\b(del|al|el|en el) programa\b")


def classify_program_scope(command_text: str, current_program: dict[str, Any] | None) -> tuple[str, str]:
    """(NEW_PROGRAM | EXTEND_PROGRAM, motivo). Sin programa actual siempre es NEW."""
    if not current_program:
        return SCOPE_NEW, "no hay programa actual"
    text = _fold(command_text)
    if _NEW_PROGRAM_CUES.search(text):
        return SCOPE_NEW, "el comando pide un programa nuevo"
    if _EXTEND_CUES.search(text):
        return SCOPE_EXTEND, "el comando agrega/modifica el programa actual"
    return SCOPE_NEW, "comando completo: genera un programa nuevo"


def assignment_source(variable: dict[str, Any], history: list[dict[str, Any]] | None = None) -> str:
    """Procedencia efectiva de un binding: LOCKED, MANUAL o AUTO."""
    if variable.get("state") == STATE_LOCKED:
        return STATE_LOCKED
    if variable.get("persistent") in (True, "true", "True", 1):
        return SOURCE_MANUAL
    recorded = str(variable.get("assignment_source") or "").upper()
    if recorded in (SOURCE_AUTO, SOURCE_MANUAL):
        return recorded
    for entry in reversed(history or []):
        if entry.get("address") == variable.get("location") and entry.get("new_name") == variable.get("name"):
            return SOURCE_MANUAL if entry.get("source") in _MANUAL_HISTORY_SOURCES else SOURCE_AUTO
    return SOURCE_AUTO


def release_auto_bindings(io_map: dict[str, Any], *, strict_owner: bool = False,
                          owner_program_id: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    COPIA de trabajo para un programa NUEVO: los ASSIGNED automaticos del programa anterior vuelven a FREE
    (conservan su ultimo nombre y TODA su configuracion fisica). LOCKED, MANUAL y persistent no se tocan.
    Devuelve (mapa_de_trabajo, canales_liberados). El mapa recibido no se modifica.
    """
    working = copy.deepcopy(io_map)
    history = list(io_map.get("history") or [])
    released = []
    for variable in working.get("variables", []):
        if variable.get("state") != STATE_ASSIGNED or not variable.get("location"):
            continue
        if assignment_source(variable, history) != SOURCE_AUTO:
            continue
        if strict_owner and (not owner_program_id or variable.get('assignment_source') != SOURCE_AUTO or
                             variable.get('owner_program_id') != owner_program_id):
            continue
        released.append({"address": variable.get("location"), "name": variable.get("name"),
                         "owner_program_id": variable.get("owner_program_id")})
        variable["state"] = STATE_FREE
        for field in BINDING_FIELDS:
            variable.pop(field, None)
    return working, released


def stamp_program_bindings(io_map: dict[str, Any], used_names: list[str], program_id: str,
                           manual_names: set[str] | None = None, *, strict_owner: bool = False,
                           previous_program_id: str | None = None,
                           newly_assigned_names: set[str] | None = None) -> dict[str, Any]:
    """
    Tras el commit de un programa verificado: cada canal FISICO que el programa usa queda ASSIGNED (LOCKED sigue
    LOCKED) con su procedencia y el programa propietario. Solo cambian campos de binding, nunca los fisicos.
    En modo estricto solo se estampa una asignacion nueva o AUTO del propietario anterior comprobado;
    utilizar un dispositivo ya declarado no convierte su canal en propiedad del programa.
    """
    stamped = copy.deepcopy(io_map)
    used, manual = set(used_names), set(manual_names or ())
    newly_assigned = set(newly_assigned_names or ())
    history = list(io_map.get("history") or [])
    for variable in stamped.get("variables", []):
        if variable.get("name") not in used or not variable.get("location"):
            continue
        if strict_owner:
            if variable.get('state') == STATE_LOCKED or variable.get('persistent') in (True, 'true', 'True', 1):
                continue
            allocated = variable['name'] in newly_assigned
            owned = (previous_program_id and variable.get('assignment_source') == SOURCE_AUTO and
                     variable.get('owner_program_id') == previous_program_id)
            if not allocated and not owned:
                # Using an installed device does not grant ownership of its channel.
                continue
        previous = assignment_source(variable, history) if variable.get("state") != STATE_FREE else SOURCE_AUTO
        if variable.get("state") != STATE_LOCKED:
            variable["state"] = STATE_ASSIGNED
            variable["assignment_source"] = SOURCE_MANUAL if (variable.get("name") in manual or previous == SOURCE_MANUAL) \
                else SOURCE_AUTO
        variable["owner_program_id"] = program_id
    return stamped


def new_program_id(now: datetime | None = None) -> str:
    return "PRG_" + (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")


def program_record(program_id: str, scope: str, semantic_output: dict[str, Any], used_names: list[str],
                   now: datetime | None = None) -> dict[str, Any]:
    """Resumen del programa ACTUAL (metadata del mapa): base para extenderlo con un comando posterior."""
    return {"program_id": program_id, "scope": scope, "command_text": semantic_output.get("command_text"),
            "intent_id": semantic_output.get("intent_id"), "parameters": dict(semantic_output.get("parameters") or {}),
            "functional_requirements": copy.deepcopy(semantic_output.get("functional_requirements") or []),
            "resources": list(used_names), "committed_at": (now or datetime.now()).isoformat(timespec="seconds")}


def llm_program_context(record: dict[str, Any]) -> dict[str, Any]:
    """Lo que el interprete necesita para EXTENDER el programa actual (nunca direcciones fisicas)."""
    return {"command_text": record.get("command_text"), "intent_id": record.get("intent_id"),
            "parameters": record.get("parameters") or {}, "functional_requirements": record.get("functional_requirements") or []}


EXTEND_POLICY = (
    "AMPLIACION DEL PROGRAMA ACTUAL: 'current_program' es el programa que ya esta en el PLC. El comando lo modifica o "
    "amplia: devuelve el programa COMPLETO resultante (todo lo existente que el comando no cambia + el cambio pedido), "
    "reutilizando EXACTAMENTE los mismos nombres de recursos del programa actual. Nunca elimines comportamiento que "
    "el comando no pide quitar.")
