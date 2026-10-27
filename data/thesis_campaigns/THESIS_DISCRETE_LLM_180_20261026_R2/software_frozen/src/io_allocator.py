"""
Deterministic IO allocator: separates PHYSICAL CHANNEL (fixed, real hardware address) from
FUNCTIONAL ROLE (the name a program gives it). The LLM/parser never chooses or invents an
address - it only supplies raw text mentions ("Q8.1", "el motor 2"); every address
normalization, existence check, direction/type compatibility check, and FREE/ASSIGNED/LOCKED
priority decision happens here, in plain deterministic Python (see docs/23_io_allocator.md).

State machine per physical channel (stored as `state` on the map variable entry):
- FREE:     no function assigned yet: the allocator may claim it automatically.
- ASSIGNED: has a function, but can be reassigned with explicit human confirmation.
- LOCKED:   never renamed/reassigned automatically or by voice/text - only an explicit manual
            unlock action can change it. LOCKED does not mean "cannot be used": existing logic
            can still reference a LOCKED variable by its current name (section 17).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

STATE_FREE = "FREE"
STATE_ASSIGNED = "ASSIGNED"
STATE_LOCKED = "LOCKED"
VALID_STATES = (STATE_FREE, STATE_ASSIGNED, STATE_LOCKED)
# SEGURIDAD: el estado por defecto de una variable SIN campo `state` explicito es LOCKED, no
# ASSIGNED. Los mapas existentes (config/io_map.json, mapa_simulacion_completo.json,
# mapa_pid_simulacion.json - D01-D20/PID) se crearon ANTES de que existiera FREE/ASSIGNED/LOCKED y
# no tienen ese campo; si el default fuera ASSIGNED, CUALQUIER tag bien formado no reconocido
# (p.ej. un nombre que el LLM proponga para una funcion nueva) podria reasignar automaticamente
# I_Emergency o cualquier otro tag critico de esos mapas. Solo un mapa que declara `state`
# explicitamente (como mapa_banco_fisico.json) participa del allocator automatico; todo lo demas
# se trata como protegido por defecto.
DEFAULT_STATE = STATE_LOCKED

# Mismo patron que gui_helpers.validate_io_map_variables (duplicado a proposito: io_allocator no
# debe depender de gui_helpers, que importa tkinter - ver docs/23_io_allocator.md).
IEC_NAME_PATTERN = re.compile(r"^(?:AI|AO|[IQMTCFR])_[A-Za-z0-9_]+$")

_WORD_ADDRESS = re.compile(r"^%?\s*([IQ])\s*W\s*(\d+)$", re.IGNORECASE)
# "%QX8.1"/"QX8.1" (notacion Siemens con X, la que muestra el mapa) equivale a "%Q8.1".
_BIT_ADDRESS = re.compile(r"^%?\s*([IQ])\s*X?\s*(\d+)\s*\.\s*(\d+)$", re.IGNORECASE)
_SPANISH_BIT_ADDRESS = re.compile(r"^(entrada|salida)\s+(\d+)\s*\.\s*(\d+)$", re.IGNORECASE)

_ADDRESS_TOKEN = (
    r"%?\s*[IQ]\s*X?\s*\d+\s*\.\s*\d+"
    r"|%?\s*[IQ]\s*W\s*\d+"
    r"|entrada\s+\d+\s*\.\s*\d+"
    r"|salida\s+\d+\s*\.\s*\d+"
)
_PER_ADDRESS_PATTERN = re.compile(
    rf"({_ADDRESS_TOKEN})\s+(?:para|como)\s+(?:el\s+|la\s+)?([^.,;]+?)"
    rf"(?=\s+(?:y|e)\s+(?:{_ADDRESS_TOKEN})|[.,;]|$)",
    re.IGNORECASE
)
_CONFIG_TRIGGER = re.compile(r"\b(usa|configura|asigna)\b", re.IGNORECASE)

_ROLE_SYNONYMS = {
    "cambio de giro": "Reverse",
    "reversa": "Reverse",
    "reverso": "Reverse",
    "giro adelante": "Motor_Forward",
    "adelante": "Motor_Forward",
    "giro reverso": "Motor_Reverse",
    "arranque": "Start",
    "arrancar": "Start",
    "start": "Start",
    "inicio": "Start",
    "encendido": "Start",
    "marcha": "Start",
    "paro": "Stop",
    "stop": "Stop",
    "parar": "Stop",
    "detener": "Stop",
    "apagado": "Stop",
    "reinicio": "Reset",
    "reset": "Reset",
    "reiniciar": "Reset",
    # Pilotos: mismo vocabulario ya usado por FUNCTIONAL_REQUIREMENT_KEYWORDS
    # (run_pilot/stop_pilot/fault_pilot en functional_requirements.py) - un "piloto de marcha"
    # debe producir el mismo sufijo Pilot_Run que ya usan D01-D20/PID, no una traduccion literal.
    "piloto de marcha": "Pilot_Run",
    "luz de marcha": "Pilot_Run",
    "lampara de marcha": "Pilot_Run",
    "piloto de paro": "Pilot_Stop",
    "luz de paro": "Pilot_Stop",
    "piloto de falla": "Pilot_Fault",
    "luz de falla": "Pilot_Fault",
    "piloto de automatico": "Pilot_Auto",
    "piloto automatico": "Pilot_Auto",
    "piloto de manual": "Pilot_Manual",
    "piloto manual": "Pilot_Manual"
}


def normalize_address(raw: str) -> str | None:
    """
    Normalize a natural-language address mention ("Q8.1", "%Q8.1", "salida 8.1", "I16.2",
    "entrada 16.2", "IW0", "%IW0"...) to the project's canonical internal form
    (%QX8.1, %IX16.2, %IW0 - see SiemensSCLAdapter.to_siemens_address for the %IX->%I export
    step). Returns None for anything unrecognized - NEVER guesses a best-effort address.
    """
    if not raw:
        return None
    text = raw.strip()
    compact = text.replace(" ", "")

    match = _WORD_ADDRESS.match(compact)
    if match:
        letter, word = match.group(1).upper(), match.group(2)
        return f"%{letter}W{word}"

    match = _BIT_ADDRESS.match(compact)
    if match:
        letter, byte, bit = match.group(1).upper(), match.group(2), match.group(3)
        return f"%{letter}X{byte}.{bit}"

    match = _SPANISH_BIT_ADDRESS.match(text)
    if match:
        word, byte, bit = match.group(1).lower(), match.group(2), match.group(3)
        letter = "I" if word == "entrada" else "Q"
        return f"%{letter}X{byte}.{bit}"

    return None


_FILLER_VERB_PREFIX = re.compile(
    r"^(controlar|manejar|accionar|activar|encender|apagar|operar|mover|manipular)\s+"
    r"(el\s+|la\s+|los\s+|las\s+)?",
    re.IGNORECASE
)


def _normalize_role_phrase(role_text: str) -> str:
    """Strip pushbutton/entrada-salida prefixes and filler verbs, leaving the bare role phrase
    (e.g. "controlar el motor 2" -> "motor 2"). Shared by _slugify_role and the alias captured
    for future commands (see apply_assignments)."""
    normalized = role_text.strip().lower()
    normalized = re.sub(r"^(pulsante|pulsador|bot[oó]n)\s+de\s+(la\s+|el\s+)?", "", normalized)
    normalized = re.sub(r"^(entrada|salida)\s+(del|de la|de)?\s*", "", normalized)
    # "para controlar el motor 2" / "para accionar la valvula..." - un verbo de relleno antes del
    # rol real no debe terminar formando parte del nombre (bug real: antes "controlar el motor 2"
    # se convertia en Q_Controlar_El_Motor_2 en vez de Q_Motor_2).
    normalized = _FILLER_VERB_PREFIX.sub("", normalized)
    return normalized.strip()


def _slugify_role(role_text: str) -> str:
    normalized = _normalize_role_phrase(role_text)
    # Frases mas largas/especificas primero: "piloto de paro" debe ganar sobre el generico "paro".
    for phrase in sorted(_ROLE_SYNONYMS, key=len, reverse=True):
        if phrase in normalized:
            return _ROLE_SYNONYMS[phrase]
    # re.search (no re.match): "motor 2" puede no estar al inicio del texto restante.
    match = re.search(r"motor\s*n?[uú]?m?e?r?o?\s*(\d+)", normalized)
    if match:
        return f"Motor_{match.group(1)}"
    cleaned = re.sub(r"[^a-zA-Z0-9áéíóúñ ]", "", normalized).strip()
    words = [word.capitalize() for word in cleaned.split() if word]
    return "_".join(words) if words else "Aux"


_DIRECTION_PREFIXES = ("AI_", "AO_", "I_", "Q_", "M_", "T_", "C_", "R_")


def _strip_direction_prefix(name: str) -> str:
    for prefix in _DIRECTION_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _matchable_role_key(role_text: str) -> str | None:
    """
    Canonical key used ONLY to decide reuse-by-semantic-role (never to generate a brand-new name -
    that stays `_slugify_role`'s job, which deliberately matches by substring so "piloto de
    marcha"/"arranque motor 2" still produce a sensible new name). This matcher is intentionally
    STRICTER: a role phrase that carries its own qualifier (any digit, e.g. "motor 2") is a
    SPECIFIC role and must NEVER collapse onto a bare general role ("arranque"/"Start"), even
    though the general word appears inside it as a substring - "arranque motor 2" is not the same
    function as "arranque" alone. Only a phrase that reduces, in full, to exactly one recognized
    bare role counts as a match.
    """
    normalized = _normalize_role_phrase(role_text)
    if not normalized or re.search(r"\d", normalized):
        return None
    return _ROLE_SYNONYMS.get(normalized)


def _candidate_role_keys(variable: dict[str, Any]) -> set[str]:
    """Every matchable role key an EXISTING map variable is already known to represent: its own
    bare name (prefix stripped) plus any alias/semantic_role that reduces to a recognized bare
    role. A variable literally named `I_Start` always matches key "start" via its own name,
    independent of whatever aliases it may or may not have."""
    keys: set[str] = set()
    own_name = _strip_direction_prefix(str(variable.get("name", ""))).replace("_", " ").strip().lower()
    if own_name:
        keys.add(own_name)
    for alias in variable.get("aliases", []) or []:
        key = _matchable_role_key(str(alias))
        if key:
            keys.add(key.lower())
    semantic_role = variable.get("semantic_role")
    if semantic_role:
        key = _matchable_role_key(str(semantic_role))
        if key:
            keys.add(key.lower())
    return keys


def _find_role_match(
    io_map: dict[str, Any],
    role_key: str,
    direction: str,
    analog: bool,
    state: str,
    exclude_addresses: set[str] = frozenset()
) -> dict[str, Any] | None:
    """Deterministic lowest-address search (same determinism guarantee as
    `_compatible_free_or_assigned`) among variables of `state` whose own name/aliases/semantic_role
    already represent `role_key` - used to REUSE a LOCKED/ASSIGNED resource by function instead of
    creating a redundant new one (see docs/23_io_allocator.md, "reutilizacion semantica")."""
    candidates = [
        variable for variable in io_map.get("variables", [])
        if variable.get("state", DEFAULT_STATE) == state
        and variable.get("class") == direction
        and _is_analog_address(str(variable.get("location", ""))) == analog
        and variable.get("location") not in exclude_addresses
        and role_key in _candidate_role_keys(variable)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda variable: _address_sort_key(variable.get("location", "")))


# Palabras que solo dicen "es una salida/orden" y no identifican la FUNCION (Q_Motor_Enable ~ Q_Motor).
_GENERIC_ROLE_WORDS = {"enable", "enabled", "output", "out", "cmd", "command", "signal"}


def functional_role_key(text: str | None) -> str | None:
    """
    Clave de ROL funcional de un nombre o rol ("Q_Motor_Enable" -> "motor", "I_Level_High_Tank_1" ->
    "level high tank 1"): sin prefijo de direccion, sin acentos, sin palabras genericas. Los numeros se
    conservan (motor 1 != motor 2). None si no queda nada que identifique una funcion.
    """
    import unicodedata

    plain = unicodedata.normalize("NFKD", _strip_direction_prefix(str(text or ""))).encode("ascii", "ignore").decode("ascii")
    words = [w for w in re.split(r"[^a-z0-9]+", plain.lower()) if w and w not in _GENERIC_ROLE_WORDS]
    return " ".join(words) or None


def _role_reuse_candidate(
    io_map: dict[str, Any], requested_name: str, exclude_addresses: set[str]
) -> dict[str, Any] | None:
    """
    Recurso EXISTENTE (ASSIGNED/LOCKED, misma clase y tipo) que ya cumple la funcion pedida con otro nombre:
    por su nombre ("Q_Motor" para "Q_Motor_Enable") o por su semantic_role declarado. Solo si es UNICO: con
    varios candidatos no se adivina. Los alias no cuentan (historicamente se escribieron automaticamente).
    """
    key = functional_role_key(requested_name)
    if not key:
        return None
    direction, analog = _direction_of_name(requested_name), _is_analog_name(requested_name)
    candidates = [
        variable for variable in io_map.get("variables", [])
        if variable.get("state", DEFAULT_STATE) in (STATE_ASSIGNED, STATE_LOCKED)
        and variable.get("class") == direction
        and _is_analog_address(str(variable.get("location", ""))) == analog
        and variable.get("location") not in exclude_addresses
        and key in {functional_role_key(variable.get("name")), functional_role_key(variable.get("semantic_role"))}
    ]
    return candidates[0] if len(candidates) == 1 else None


def _is_analog_address(address: str) -> bool:
    return "W" in address.upper()


def _direction_letter(address: str) -> str:
    return address[1].upper()


def extract_io_assignment_requests(command_text: str) -> list[dict[str, Any]]:
    """
    ONLY source of `requested_io_assignments` (section 8/section 29.8): a plain regex scan for
    "<verbo de configuracion> ... <direccion> (para|como) <rol>" mentions. If the command has no
    usa/configura/asigna trigger, returns [] - normal PLC-logic commands never get reinterpreted
    as map changes. Text the regex cannot parse is simply not extracted (never silently turned
    into a guessed address) - the LLM plays no role in this extraction at all.
    """
    if not _CONFIG_TRIGGER.search(command_text or ""):
        return []

    requests: list[dict[str, Any]] = []
    for match in _PER_ADDRESS_PATTERN.finditer(command_text):
        address_text, role_text = match.group(1), match.group(2)
        address = normalize_address(address_text)
        if address is None:
            continue
        is_analog = _is_analog_address(address)
        letter = _direction_letter(address)
        prefix = ("AI_" if is_analog else "I_") if letter == "I" else ("AO_" if is_analog else "Q_")
        requests.append(
            {
                "address_text": address_text.strip(),
                "address": address,
                "role_text": role_text.strip(),
                "functional_name_hint": f"{prefix}{_slugify_role(role_text)}"
            }
        )
    return requests


_MULTI_MOTOR_COUNT = re.compile(r"(dos|tres|cuatro|cinco|\d+)\s+motor(?:es)?", re.IGNORECASE)
_INDEPENDENT_BUTTON_PHRASING = re.compile(
    r"pulsante.{0,30}independiente|independiente.{0,30}pulsante|"
    r"pulsante.{0,30}cada (?:motor|uno)|boton.{0,30}independiente",
    re.IGNORECASE
)
_WORD_TO_NUMBER = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}


def extract_implicit_multi_resource_requests(command_text: str) -> list[dict[str, Any]]:
    """
    Fallback determinista y DELIBERADAMENTE ACOTADO (seccion 42) para el patron concreto "N
    motores con un pulsante de arranque independiente para cada uno" cuando el comando NO da
    ninguna direccion explicita. No es NLU general: solo reconoce esta frase (conteo + "motor(es)"
    + "pulsante ... independiente"); cualquier otra redaccion no genera nada aqui y sigue el
    camino normal - nunca se inventa una direccion ni se asume una peticion que el texto no dice
    con claridad. El primer motor reutiliza la convencion I_Start/Q_Motor_1 (igual que si ya
    existieran esos nombres en el mapa); el resto usa I_Start_Motor_N/Q_Motor_N.
    """
    text = command_text or ""
    count_match = _MULTI_MOTOR_COUNT.search(text)
    if not count_match or not _INDEPENDENT_BUTTON_PHRASING.search(text):
        return []
    count_text = count_match.group(1).lower()
    count = _WORD_TO_NUMBER.get(count_text) or (int(count_text) if count_text.isdigit() else 0)
    if count < 2 or count > 8:
        return []

    requests: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        motor_name = "Q_Motor_1" if index == 1 else f"Q_Motor_{index}"
        start_name = "I_Start" if index == 1 else f"I_Start_Motor_{index}"
        requests.append({"functional_name_hint": start_name, "role_text": f"arranque motor {index}"})
        requests.append({"functional_name_hint": motor_name, "role_text": f"motor {index}"})
    return requests


def find_variable_by_address(io_map: dict[str, Any], address: str) -> dict[str, Any] | None:
    for variable in io_map.get("variables", []):
        if str(variable.get("location", "")).upper() == address.upper():
            return variable
    return None


def find_variable_by_name(io_map: dict[str, Any], name: str) -> dict[str, Any] | None:
    for variable in io_map.get("variables", []):
        if variable.get("name") == name:
            return variable
    return None


def _direction_of_name(name: str) -> str | None:
    if name.startswith(("I_", "AI_")):
        return "input"
    if name.startswith(("Q_", "AO_")):
        return "output"
    return None


def _is_analog_name(name: str) -> bool:
    return name.startswith(("AI_", "AO_"))


def validate_assignment_request(io_map: dict[str, Any], address: str, requested_name: str) -> dict[str, Any]:
    """
    Deterministic compatibility check for one (address, requested_name) pair (section 12):
    address must exist physically, direction (input/output) must match the name prefix, and
    digital/analog must match. Never falls back to a guess when the address is not in the map.
    """
    errors: list[str] = []
    variable = find_variable_by_address(io_map, address)
    if variable is None:
        errors.append(f"La direccion {address} no existe fisicamente en el mapa activo.")
        return {"valid": False, "errors": errors, "variable": None}

    requested_direction = _direction_of_name(requested_name)
    if requested_direction is None:
        errors.append(f"El nombre propuesto {requested_name} debe iniciar con I_, Q_, AI_ o AO_.")
        return {"valid": False, "errors": errors, "variable": variable}

    variable_direction = variable.get("class")
    if variable_direction != requested_direction:
        errors.append(
            f"La direccion {address} es de tipo {variable_direction}, incompatible con el rol "
            f"solicitado ({requested_direction})."
        )

    requested_analog = _is_analog_name(requested_name)
    variable_analog = _is_analog_address(address)
    if requested_analog != variable_analog:
        kind = "analogico" if requested_analog else "digital"
        errors.append(f"La direccion {address} no es compatible con un recurso {kind}.")

    return {"valid": not errors, "errors": errors, "variable": variable}


def validate_manual_rename(io_map: dict[str, Any], address: str, new_name: str) -> dict[str, Any]:
    """
    Full validation for a manual rename from the "Mapa I/O completo" editor (section 10): the
    variable must exist and NOT be LOCKED, the new name must be a valid IEC identifier with the
    correct prefix, direction/analog-digital must be compatible with the address, and the name
    must not already be in use by a DIFFERENT address. Returns
    {"valid": bool, "errors": [...], "variable": entry|None} - never applies anything itself.
    """
    variable = find_variable_by_address(io_map, address)
    if variable is None:
        return {"valid": False, "errors": [f"La direccion {address} no existe en el mapa activo."], "variable": None}

    errors: list[str] = []
    if variable.get("state", DEFAULT_STATE) == STATE_LOCKED:
        errors.append(
            f"{variable.get('name')} esta bloqueada (LOCKED). Desbloquee la variable manualmente antes de modificarla."
        )

    if not IEC_NAME_PATTERN.match(new_name or ""):
        errors.append(
            f"El nombre {new_name!r} no es un identificador IEC valido (debe iniciar con AI_/AO_/I_/Q_/M_/T_/C_/R_/F_)."
        )
    else:
        compat = validate_assignment_request(io_map, address, new_name)
        if not compat["valid"]:
            errors.extend(compat["errors"])
        for other in io_map.get("variables", []):
            if other.get("location") != address and other.get("name") == new_name:
                errors.append(f"El nombre {new_name} ya esta en uso en {other.get('location')}.")
                break

    return {"valid": not errors, "errors": errors, "variable": variable}


_ADDRESS_SORT_PATTERN = re.compile(r"^%[IQ][XW](\d+)(?:\.(\d+))?$", re.IGNORECASE)


def _address_sort_key(location: str) -> tuple[int, int]:
    match = _ADDRESS_SORT_PATTERN.match(str(location or "").upper())
    if not match:
        return (0, 0)
    byte, bit = match.groups()
    return (int(byte), int(bit) if bit else 0)


def _compatible_free_or_assigned(
    io_map: dict[str, Any],
    requested_name: str,
    state: str,
    exclude_addresses: set[str] = frozenset()
) -> dict[str, Any] | None:
    """
    Section 37 (determinismo): entre varios canales compatibles del mismo estado, siempre elige
    la direccion fisica mas baja - el mismo mapa inicial + el mismo comando deben producir SIEMPRE
    la misma asignacion, sin depender del orden en que las variables aparecen en el JSON.
    `exclude_addresses` deja fuera canales ya reclamados por OTRA peticion del mismo lote.
    """
    direction = _direction_of_name(requested_name)
    analog = _is_analog_name(requested_name)
    candidates = [
        variable for variable in io_map.get("variables", [])
        if variable.get("state", DEFAULT_STATE) == state
        and variable.get("class") == direction
        and _is_analog_address(str(variable.get("location", ""))) == analog
        and variable.get("location") not in exclude_addresses
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda variable: _address_sort_key(variable.get("location", "")))


def propose_assignment(
    io_map: dict[str, Any], requests: list[dict[str, Any]], *, reserved_names: set[str] | None = None
) -> list[dict[str, Any]]:
    """
    Core allocator (section 7/18): for each request, returns a proposal - it NEVER mutates the
    map. Priority when no explicit address is given: (1) reuse an existing variable that already
    has this exact name, (2) claim a compatible FREE channel, (3) offer to reassign a compatible
    ASSIGNED channel (conflict=True, still requires confirmation), (4) never touch LOCKED -
    if nothing else is available, the proposal comes back blocked.
    reserved_names protects channels already referenced by this program, even when FREE.
    """
    proposals: list[dict[str, Any]] = []
    reserved_by_address = {v["location"]: v["name"] for v in io_map.get("variables", [])
                           if v.get("name") in (reserved_names or set()) and v.get("location")}
    # Direcciones ya reclamadas por una peticion ANTERIOR en este mismo lote (seccion 8/20/41: dos
    # roles distintos sin direccion explicita, p. ej. "dos motores", nunca deben terminar
    # apuntando al mismo canal FREE/ASSIGNED solo porque ambos consultan el mismo mapa estatico).
    claimed_in_batch: set[str] = set()
    for request in requests:
        proposed_name = request.get("functional_name_hint") or request.get("proposed_name")
        if not proposed_name:
            # Some structured replies describe the same digital request as a
            # variable. Accept that spelling only with an explicit compatible
            # direction/type; it still goes through the normal channel guards.
            name=request.get('name')
            expected_prefix={'input':'I_','output':'Q_'}.get(request.get('class'))
            if (isinstance(name,str) and expected_prefix and name.startswith(expected_prefix)
                    and request.get('type')=='BOOL'):
                proposed_name=name
        if not isinstance(proposed_name, str) or not proposed_name.strip():
            proposals.append({'address': None, 'proposed_name': None, 'current_name': None,
                'current_state': None, 'conflict': False, 'blocked': True,
                'reason': 'IO_ASSIGNMENT_FORMAT: falta functional_name_hint o proposed_name con un nombre de variable valido.'})
            continue
        proposed_name = proposed_name.strip()
        address = request.get("address")
        if not address and request.get("address_text"):
            address = normalize_address(request["address_text"])

        if address:
            check = validate_assignment_request(io_map, address, proposed_name)
            if not check["valid"]:
                proposals.append(
                    {
                        "address": address,
                        "proposed_name": proposed_name,
                        "current_name": check["variable"].get("name") if check["variable"] else None,
                        "current_state": check["variable"].get("state") if check["variable"] else None,
                        "conflict": False,
                        "blocked": True,
                        "reason": "; ".join(check["errors"])
                    }
                )
                continue
            variable = check["variable"]
            state = variable.get("state", DEFAULT_STATE)
            if address in reserved_by_address and proposed_name != reserved_by_address[address]:
                proposals.append({
                    "address": address, "proposed_name": proposed_name,
                    "current_name": variable.get("name"), "current_state": state,
                    "conflict": True, "blocked": True,
                    "reason": (f"El programa ya utiliza {reserved_by_address[address]} en {address}; "
                               f"no se puede asignar ese mismo canal a {proposed_name}."),
                })
                continue
            if state == STATE_LOCKED:
                proposals.append(
                    {
                        "address": address,
                        "proposed_name": proposed_name,
                        "current_name": variable.get("name"),
                        "current_state": STATE_LOCKED,
                        "conflict": False,
                        "blocked": True,
                        "reason": (
                            f"La variable {variable.get('name')} en {address} esta protegida "
                            "(LOCKED) y no puede reasignarse."
                        )
                    }
                )
                continue
            # Un canal FREE puede llevar un nombre de canal generico (p. ej. "Q_Free1") que no
            # representa una asignacion real - solo cuenta como conflicto sobrescribir un nombre
            # de un canal que YA estaba ASSIGNED/LOCKED con una funcion real.
            conflict = state != STATE_FREE and variable.get("name") not in (None, "", proposed_name)
            reason = (
                f"La direccion {address} ya esta asignada a {variable.get('name')}. "
                f"Cambio propuesto: {variable.get('name')} -> {proposed_name}."
                if conflict else
                f"Canal {state.lower()} en {address}, se propone asignar {proposed_name}."
            )
            proposals.append(
                {
                    "address": address,
                    "proposed_name": proposed_name,
                    "current_name": variable.get("name"),
                    "current_state": state,
                    "conflict": conflict,
                    "blocked": False,
                    "reason": reason
                }
            )
            claimed_in_batch.add(address)
            continue

        # Sin direccion explicita: resolver por rol (section 7/18). Antes de buscar exacto/FREE,
        # comprobar si la FUNCION ya esta cubierta semanticamente por un recurso LOCKED o ASSIGNED
        # existente (seccion "reutilizacion semantica de variables LOCKED") - LOCKED no significa
        # "canal ocupado", significa "esta funcion ya tiene nombre fijo aqui"; si el rol solicitado
        # coincide, se reutiliza tal cual (nunca se renombra un LOCKED) en vez de crear un recurso
        # nuevo redundante. Solo aplica cuando hay `role_text` en LENGUAJE NATURAL explicito - NUNCA
        # se deriva de un nombre de tag ya propuesto (p. ej. "I_Start_Motor_1"), porque coincidiria
        # por subcadena con "Start" y colapsaria funciones genuinamente distintas (el motivo por el
        # que `_matchable_role_key` es mas estricto que `_slugify_role`: rechaza cualquier frase con
        # un digito, "arranque motor 2" nunca es igual a "arranque").
        role_text = request.get("role_text")
        request_role_key = _matchable_role_key(str(role_text)) if role_text else None
        if request_role_key:
            role_key_lower = request_role_key.lower()
            request_direction = _direction_of_name(proposed_name or "")
            request_analog = _is_analog_name(proposed_name or "")
            locked_role_match = _find_role_match(
                io_map, role_key_lower, request_direction, request_analog, STATE_LOCKED,
                exclude_addresses=claimed_in_batch
            )
            if locked_role_match is not None:
                proposals.append(
                    {
                        "address": locked_role_match.get("location"),
                        "proposed_name": locked_role_match.get("name"),
                        "current_name": locked_role_match.get("name"),
                        "current_state": STATE_LOCKED,
                        "conflict": False,
                        "blocked": False,
                        "reason": (
                            f"La funcion ya esta cubierta por {locked_role_match.get('name')} "
                            "(LOCKED) - se reutiliza tal cual, sin crear un recurso nuevo."
                        ),
                        "semantic_reuse": True,
                        "requested_name": proposed_name
                    }
                )
                claimed_in_batch.add(locked_role_match.get("location"))
                continue

            assigned_role_match = _find_role_match(
                io_map, role_key_lower, request_direction, request_analog, STATE_ASSIGNED,
                exclude_addresses=claimed_in_batch
            )
            if assigned_role_match is not None:
                proposals.append(
                    {
                        "address": assigned_role_match.get("location"),
                        "proposed_name": assigned_role_match.get("name"),
                        "current_name": assigned_role_match.get("name"),
                        "current_state": STATE_ASSIGNED,
                        "conflict": False,
                        "blocked": False,
                        "reason": (
                            f"La funcion ya esta cubierta por {assigned_role_match.get('name')} "
                            "(ASSIGNED) - se reutiliza tal cual, sin crear un recurso nuevo."
                        ),
                        "semantic_reuse": True,
                        "requested_name": proposed_name
                    }
                )
                claimed_in_batch.add(assigned_role_match.get("location"))
                continue

        existing = find_variable_by_name(io_map, proposed_name)
        # reuse_by_role (necesidad implicita de Modo Normal): el rol ya cubierto por otro nombre se reutiliza
        # tal cual (el programa se vincula a ESE simbolo; nunca se crea un recurso duplicado para la funcion).
        role_match = (_role_reuse_candidate(io_map, proposed_name, claimed_in_batch)
                      if request.get("reuse_by_role") and existing is None else None)
        if role_match is not None:
            proposals.append(
                {
                    "address": role_match.get("location"),
                    "proposed_name": role_match.get("name"),
                    "current_name": role_match.get("name"),
                    "current_state": role_match.get("state", DEFAULT_STATE),
                    "conflict": False,
                    "blocked": False,
                    "reason": (f"La funcion de {proposed_name} ya esta cubierta por {role_match.get('name')} "
                               f"({role_match.get('location')}) - se reutiliza, sin crear un recurso nuevo."),
                    "semantic_reuse": True,
                    "requested_name": proposed_name
                }
            )
            claimed_in_batch.add(role_match.get("location"))
            continue
        if existing is not None and existing.get("location") not in claimed_in_batch:
            proposals.append(
                {
                    "address": existing.get("location"),
                    "proposed_name": proposed_name,
                    "current_name": proposed_name,
                    "current_state": existing.get("state", DEFAULT_STATE),
                    "conflict": False,
                    "blocked": False,
                    "reason": "Ya existe esta asignacion, se reutiliza sin cambios."
                }
            )
            claimed_in_batch.add(existing.get("location"))
            continue

        free_candidate = _compatible_free_or_assigned(
            io_map, proposed_name, STATE_FREE, exclude_addresses=claimed_in_batch | set(reserved_by_address))
        if free_candidate is not None:
            proposals.append(
                {
                    "address": free_candidate.get("location"),
                    "proposed_name": proposed_name,
                    "current_name": free_candidate.get("name"),
                    "current_state": STATE_FREE,
                    "conflict": False,
                    "blocked": False,
                    "reason": f"Canal libre disponible en {free_candidate.get('location')}."
                }
            )
            claimed_in_batch.add(free_candidate.get("location"))
            continue

        # allow_reassign=False (necesidad implicita de Modo Normal): un canal ASSIGNED a otra funcion no se toma.
        assigned_candidate = (_compatible_free_or_assigned(io_map, proposed_name, STATE_ASSIGNED,
                                                         exclude_addresses=claimed_in_batch | set(reserved_by_address))
                              if request.get("allow_reassign", True) else None)
        if assigned_candidate is not None:
            proposals.append(
                {
                    "address": assigned_candidate.get("location"),
                    "proposed_name": proposed_name,
                    "current_name": assigned_candidate.get("name"),
                    "current_state": STATE_ASSIGNED,
                    "conflict": True,
                    "blocked": False,
                    "reason": (
                        f"No hay canal libre compatible. Se propone reasignar "
                        f"{assigned_candidate.get('name')} ({assigned_candidate.get('location')}) "
                        f"-> {proposed_name}."
                    )
                }
            )
            claimed_in_batch.add(assigned_candidate.get("location"))
            continue

        proposals.append(
            {
                "address": None,
                "proposed_name": proposed_name,
                "current_name": None,
                "current_state": None,
                "conflict": False,
                "blocked": True,
                "reason": (
                    f"No hay ningun canal compatible disponible para {proposed_name} "
                    "(todo esta LOCKED o incompatible)."
                )
            }
        )

    # Deduplicacion DENTRO del mismo lote (seccion 6/26/30 - "es BUG del allocator; resolver/
    # deduplicar antes de tocar el mapa"): dos requests distintos pidiendo el MISMO proposed_name
    # (p.ej. el mismo rol llega a la vez como referencia implicita de un parametro/recognized_tag
    # Y como una entrada explicita de requested_io_assignments) nunca deben resolver a dos canales
    # FREE distintos solo porque cada resolucion individual excluyo la direccion que la otra ya
    # reclamo via `claimed_in_batch` - eso es exactamente lo que producia el bug real
    # ("I_Start_Motor_2" duplicado en el mapa: %IX16.4 y %IX16.5 a la vez). Se colapsan en UNA
    # sola direccion (la primera resuelta en este lote), nunca se vuelve a consultar el allocator.
    # Si el MISMO nombre llega tambien con una direccion dicha por el usuario ("usa %QX1.5 para la bomba"),
    # esa direccion explicita es la que prevalece (nunca la del canal libre elegido para la mencion implicita).
    first_proposal_for_name: dict[str, dict[str, Any]] = {}
    for proposal, request in zip(proposals, requests):
        if not proposal["blocked"] and (request.get("address") or request.get("address_text")):
            first_proposal_for_name.setdefault(proposal["proposed_name"], proposal)
    for index, proposal in enumerate(proposals):
        if proposal["blocked"]:
            continue
        name = proposal["proposed_name"]
        canonical = first_proposal_for_name.get(name)
        if canonical is None:
            first_proposal_for_name[name] = proposal
            continue
        if proposal["address"] == canonical["address"]:
            continue
        proposals[index] = {**canonical, "duplicate_request_collapsed": True}

    for proposal, request in zip(proposals, requests):
        proposal["role_text"] = request.get("role_text", "")
        # Seccion 35/38: distingue una direccion que el USUARIO indico explicitamente de una que
        # el allocator resolvio por su cuenta a partir de un rol - determina el "source" del
        # historial (TEXT_EXPLICIT/VOICE_EXPLICIT vs AUTO_ALLOCATOR, ver apply_assignments).
        explicit_address = request.get("address") or request.get("address_text")
        proposal["address_was_explicit"] = bool(explicit_address)

    # Deteccion de nombre duplicado (seccion 6): dos direcciones distintas no pueden terminar con
    # el mismo nombre funcional activo a la vez. Se ignora si quien hoy tiene ese nombre esta
    # siendo renombrado a otra cosa en este MISMO lote (evita falsos positivos, p. ej. un
    # intercambio de roles entre dos canales en un solo comando).
    name_holders: dict[str, list[str]] = {}
    for variable in io_map.get("variables", []):
        name = variable.get("name")
        if name:
            name_holders.setdefault(name, []).append(variable.get("location"))
    vacating_addresses = {
        proposal["address"] for proposal in proposals
        if not proposal["blocked"] and proposal.get("current_name") != proposal.get("proposed_name")
    }
    for proposal in proposals:
        if proposal["blocked"]:
            continue
        other_holders = [
            location for location in name_holders.get(proposal["proposed_name"], [])
            if location != proposal["address"] and location not in vacating_addresses
        ]
        if other_holders:
            proposal["blocked"] = True
            proposal["conflict"] = False
            proposal["reason"] = (
                f"El nombre {proposal['proposed_name']} ya esta en uso en {other_holders[0]} - no "
                "puede haber dos direcciones activas con el mismo nombre funcional."
            )

    # `conflict`/`requires_confirmation` ya NO gatillan un dialogo en Modo Normal (seccion 22: cero
    # confirmaciones - MAP_CONFIG solo corre en Modo Normal, Experimentacion lo bloquea antes de
    # llegar aqui). Se conservan como metadata informativa/de trazabilidad y porque
    # `validate_manual_rename`/tests siguen distinguiendo "reuso sin cambio" de "reasignacion real".
    for proposal in proposals:
        proposal["requires_confirmation"] = proposal["conflict"] and not proposal["blocked"]
    return proposals


_CHANNEL_CLASSES = {
    ("input", False): ("DI", "entradas digitales"),
    ("output", False): ("DO", "salidas digitales"),
    ("input", True): ("AI", "entradas analogicas"),
    ("output", True): ("AO", "salidas analogicas"),
}


def capacity_gap(io_map: dict[str, Any], proposals: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Falta de HARDWARE (no una ambiguedad): por clase de canal, cuantos recursos NUEVOS pide el programa y
    cuantos canales FREE compatibles tiene el mapa. Solo cuenta lo que necesita un canal nuevo (las
    reutilizaciones por nombre/funcion no consumen canal). None si ninguna propuesta quedo bloqueada.
    """
    if not any(proposal.get("blocked") for proposal in proposals):
        return None
    needed: dict[tuple[str, bool], list[str]] = {}
    for proposal in proposals:
        name = str(proposal.get("proposed_name") or "")
        if proposal.get("blocked") or proposal.get("current_state") == STATE_FREE:
            direction = _direction_of_name(name)
            if direction:
                needed.setdefault((direction, _is_analog_name(name)), []).append(name)
    shortages = []
    for (direction, analog), names in needed.items():
        available = sum(1 for variable in io_map.get("variables", [])
                        if variable.get("state", DEFAULT_STATE) == STATE_FREE and variable.get("class") == direction
                        and _is_analog_address(str(variable.get("location", ""))) == analog)
        if available < len(names):
            code, label = _CHANNEL_CLASSES[(direction, analog)]
            required = (f"Se requiere 1 {code} compatible" if len(names) == 1
                        else f"Se requieren {len(names)} {code} compatibles")
            roles = ", ".join(functional_role_key(name) or name for name in names)
            shortages.append({"channel_class": code, "required": len(names), "available": available,
                              "resources": names,
                              "message": (f"No existen suficientes {label} disponibles para implementar el programa. "
                                          f"{required} y actualmente hay {available} "
                                          f"disponible{'s' if available != 1 else ''} (para: {roles}; {', '.join(names)}).")})
    blocked = [proposal.get("proposed_name") for proposal in proposals if proposal.get("blocked")]
    message = " ".join(item["message"] for item in shortages) or (
        "No hay canales fisicos compatibles disponibles para: " + ", ".join(str(name) for name in blocked) + ".")
    return {"code": "SYSTEM_CAPABILITY_GAP", "shortages": shortages, "blocked_resources": blocked, "message": message}


SOURCE_AUTO_ALLOCATOR = "AUTO_ALLOCATOR"
SOURCE_VOICE_EXPLICIT = "VOICE_EXPLICIT"
SOURCE_TEXT_EXPLICIT = "TEXT_EXPLICIT"
SOURCE_MANUAL_EDITOR = "MANUAL_EDITOR"
VALID_HISTORY_SOURCES = (SOURCE_AUTO_ALLOCATOR, SOURCE_VOICE_EXPLICIT, SOURCE_TEXT_EXPLICIT, SOURCE_MANUAL_EDITOR)


def _history_entry(address: str, old_name: str | None, new_name: str, old_state: str, new_state: str, source: str) -> dict[str, Any]:
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "address": address,
        "old_name": old_name,
        "new_name": new_name,
        "old_state": old_state,
        "new_state": new_state,
        "source": source
    }


def apply_assignments(
    io_map: dict[str, Any],
    confirmed_proposals: list[dict[str, Any]],
    source: str = SOURCE_TEXT_EXPLICIT
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Pure function: returns (NEW io_map, history_entries) with the confirmed (human-approved)
    proposals applied. Refuses (raises ValueError) if any target is LOCKED and the proposal would
    actually RENAME it - confirmation from a stale proposal can never silently override a lock
    that happened in between. A LOCKED target is still allowed through when `proposed_name`
    already equals its current name (a semantic-reuse proposal from `propose_assignment`'s
    LOCKED-role-match step: "this function is already covered here, use it as-is") - LOCKED means
    the name/address are fixed, not that the entry can never appear in an applied batch; nothing
    is actually renamed in that case, it is a no-op besides recording the role phrase as a new
    alias for future commands. `source` (one of VALID_HISTORY_SOURCES, section 35) is the DEFAULT
    recorded for each entry; a proposal from propose_assignment() that was resolved purely by role
    (`address_was_explicit=False`, no address given by the user) is recorded as
    SOURCE_AUTO_ALLOCATOR regardless of `source`, so the history always shows who actually chose
    the channel - the user (explicit address) or the allocator (role-only resolution).
    """
    variables = [dict(variable) for variable in io_map.get("variables", [])]
    by_address = {variable.get("location"): variable for variable in variables}
    history_entries: list[dict[str, Any]] = []

    for proposal in confirmed_proposals:
        if proposal.get("blocked"):
            raise ValueError(f"No se puede aplicar una propuesta bloqueada: {proposal.get('reason')}")
        address = proposal.get("address")
        variable = by_address.get(address)
        if variable is None:
            raise ValueError(f"La direccion {address} no existe en el mapa activo.")
        old_state = variable.get("state", DEFAULT_STATE)
        if old_state == STATE_LOCKED and proposal["proposed_name"] != variable.get("name"):
            raise ValueError(f"La variable en {address} esta LOCKED y no puede reasignarse.")
        old_name = variable.get("name")
        new_name = proposal["proposed_name"]
        new_state = STATE_ASSIGNED if old_state == STATE_FREE else old_state
        variable["name"] = new_name
        variable["state"] = new_state

        # El nombre funcional nuevo es lo que un comando FUTURO va a decir ("enciende el motor
        # 2") - sin esto, el parser basado en reglas (alias_resolver.build_alias_index) no tiene
        # forma de saber que "motor 2" ahora es Q_Motor_2. Se guarda la frase de rol ya
        # normalizada (sin verbos de relleno) como alias, sumada a las que ya existieran.
        role_text = proposal.get("role_text")
        if role_text:
            role_phrase = _normalize_role_phrase(role_text)
            existing_aliases = list(variable.get("aliases") or [])
            if role_phrase and role_phrase not in existing_aliases:
                existing_aliases.append(role_phrase)
            variable["aliases"] = existing_aliases

        if old_name != new_name or old_state != new_state:
            entry_source = SOURCE_AUTO_ALLOCATOR if proposal.get("address_was_explicit") is False else source
            history_entries.append(_history_entry(address, old_name, new_name, old_state, new_state, entry_source))

    # Invariante final, transaccional (seccion 8-B/9): un functional_name activo nunca puede
    # terminar en mas de una direccion. propose_assignment() ya deduplica/bloquea esto antes de
    # llegar aqui, pero apply_assignments() es la ULTIMA linea de defensa antes de persistir - se
    # verifica el resultado COMPLETO (no solo los proposals de esta llamada) porque un llamador
    # que construya `confirmed_proposals` por su cuenta (sin pasar por propose_assignment) podria
    # saltarse esa proteccion. Si el resultado violaria la invariante, se rechaza el lote entero
    # ANTES de devolver nada - nunca se persiste un mapa parcialmente corrupto.
    name_to_addresses: dict[str, list[str]] = {}
    for variable in variables:
        name = variable.get("name")
        if name:
            name_to_addresses.setdefault(name, []).append(variable.get("location"))
    duplicated = {name: locations for name, locations in name_to_addresses.items() if len(locations) > 1}
    if duplicated:
        details = "; ".join(f"{name} en {', '.join(locations)}" for name, locations in duplicated.items())
        raise ValueError(
            "El lote de asignaciones produciria nombres funcionales duplicados en direcciones "
            f"distintas: {details}. No se modifico el mapa."
        )

    return {**io_map, "variables": variables}, history_entries


def undo_last_map_change(io_map: dict[str, Any], history: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """
    Simple single-step undo (section 27): reverts the LAST history entry only (name and state at
    that address back to old_name/old_state). Returns (new io_map, the reverted entry) or
    (io_map unchanged, None) if there is no history to undo.
    """
    if not history:
        return io_map, None
    last_entry = history[-1]
    variables = [dict(variable) for variable in io_map.get("variables", [])]
    for variable in variables:
        if variable.get("location") == last_entry.get("address"):
            variable["name"] = last_entry.get("old_name")
            variable["state"] = last_entry.get("old_state", DEFAULT_STATE)
            break
    return {**io_map, "variables": variables}, last_entry


def block_map_config_message(active_trial: dict[str, Any] | None, active_profile_id: str | None) -> str | None:
    """
    Section 23: MAP_CONFIG is intended for Modo Normal only. Returns the exact warning message
    to show if a reassignment must be blocked right now (a trial is running, or an experimental
    Dxx/Pxx profile is selected - the "mapa congelado" case), else None.
    """
    if active_trial is not None or active_profile_id is not None:
        return "La reasignacion de I/O no esta permitida durante un ensayo experimental activo."
    return None


def set_variable_state(io_map: dict[str, Any], name: str, new_state: str) -> dict[str, Any]:
    """Pure function: lock/unlock/mark-free a variable by name (section 4/5), never touches its
    physical location or its name - only `state`."""
    if new_state not in VALID_STATES:
        raise ValueError(f"Estado invalido: {new_state}. Debe ser uno de {VALID_STATES}.")
    variables = [dict(variable) for variable in io_map.get("variables", [])]
    found = False
    for variable in variables:
        if variable.get("name") == name:
            variable["state"] = new_state
            found = True
    if not found:
        raise ValueError(f"La variable {name} no existe en el mapa activo.")
    return {**io_map, "variables": variables}


__all__ = [
    "STATE_FREE",
    "STATE_ASSIGNED",
    "STATE_LOCKED",
    "VALID_STATES",
    "DEFAULT_STATE",
    "IEC_NAME_PATTERN",
    "normalize_address",
    "extract_io_assignment_requests",
    "extract_implicit_multi_resource_requests",
    "find_variable_by_address",
    "find_variable_by_name",
    "validate_manual_rename",
    "validate_assignment_request",
    "propose_assignment",
    "apply_assignments",
    "undo_last_map_change",
    "set_variable_state",
    "block_map_config_message",
    "SOURCE_AUTO_ALLOCATOR",
    "SOURCE_VOICE_EXPLICIT",
    "SOURCE_TEXT_EXPLICIT",
    "SOURCE_MANUAL_EDITOR",
    "VALID_HISTORY_SOURCES"
]
