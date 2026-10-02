"""
Recursos funcionales de functional_requirements: identificables, nombrables y asignables ANTES de IR/codegen.

Todo recurso que llega a la IR debe tener: rol funcional, direccion (kind), nombre funcional
canonico, tipo de dato y - si es externo - canal fisico (este ultimo lo pone SIEMPRE el
IOAllocator, nunca el LLM).

  * Un recurso escrito como tag ("Q_Motor_Enable") se conserva tal cual.
  * Un recurso escrito como referencia {"role", "actor", "kind"} sin nombre recibe un nombre
    canonico DETERMINISTA (canonical_functional_tag) con la convencion de prefijos del proyecto.
  * Si no hay rol ni actor, o no se puede saber si es entrada o salida: NO se inventa un nombre
    (nada de Variable1/Output1) -> error estructurado FUNCTIONAL_RESOURCE_UNRESOLVED con la ruta.
  * Un requisito cuyo `type` no es una primitiva del catalogo ni una variable funcional
    ({"name", "type": IEC}) -> FUNCTIONAL_REQUIREMENT_UNSUPPORTED (antes caia, sin diagnostico, en
    el canal de variables ad-hoc y fallaba al final con "variable funcional sin nombre").

Generico: no conoce maquinas, actores ni frases concretas.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

from functional_requirements import (
    classify_functional_requirement,
    CLASS_UNSUPPORTED,
)

FUNCTIONAL_RESOURCE_UNRESOLVED = "FUNCTIONAL_RESOURCE_UNRESOLVED"
FUNCTIONAL_REQUIREMENT_UNSUPPORTED = "FUNCTIONAL_REQUIREMENT_UNSUPPORTED"

# Convencion de nombres del proyecto (naming_convention de los mapas PLC).
KIND_PREFIXES: dict[str, str] = {"input": "I_", "output": "Q_", "memory": "M_", "timer": "T_", "counter": "C_"}
_KIND_ALIASES: dict[str, str] = {
    "input": "input", "in": "input", "di": "input", "i": "input", "entrada": "input",
    "output": "output", "out": "output", "do": "output", "q": "output", "salida": "output",
    "memory": "memory", "m": "memory", "memoria": "memory",
    "timer": "timer", "t": "timer", "temporizador": "timer",
    "counter": "counter", "c": "counter", "contador": "counter",
}
# Palabras que solo repiten la direccion ("MIXER_OUTPUT" -> Q_Mixer): se omiten del nombre.
_KIND_WORDS: dict[str, set[str]] = {
    "input": {"INPUT", "IN", "ENTRADA", "SIGNAL", "SENAL"},
    "output": {"OUTPUT", "OUT", "SALIDA"},
    "memory": {"MEMORY", "MEMORIA", "FLAG"},
    "timer": {"TIMER", "TEMPORIZADOR"},
    "counter": {"COUNTER", "CONTADOR"},
}
_REFERENCE_NAME_KEYS = ("name", "tag")
_REFERENCE_KEYS = {"name", "tag", "role", "actor", "kind", "direction", "data_type", "description"}
_CONDITION_KEYS = ("mode_condition", "enable_condition", "start_condition")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TAG = re.compile(r"^(?:AI|AO|[IQMTCFR])_[A-Za-z0-9_]+$")
_EXPRESSION_KEYWORDS = {"AND", "OR", "NOT", "XOR", "TRUE", "FALSE"}


def _ascii_tokens(text: Any) -> list[str]:
    plain = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return [token for token in re.split(r"[^A-Za-z0-9]+", plain.upper()) if token]


def normalize_kind(value: Any) -> str | None:
    return _KIND_ALIASES.get(str(value or "").strip().lower())


def kind_from_field(key: str | None) -> str | None:
    """Direccion implicita por el nombre del campo: *_input(s) -> input, *_output(s) -> output."""
    lowered = str(key or "").lower()
    if lowered.endswith(("input", "inputs")):
        return "input"
    if lowered.endswith(("output", "outputs")):
        return "output"
    return None


def is_resource_field(key: str | None) -> bool:
    return kind_from_field(key) is not None


def canonical_functional_tag(role: Any = None, actor: Any = None, kind: Any = None) -> str | None:
    """
    role / actor / kind -> tag funcional canonico, o None si no se puede derivar sin inventar.

      ("MANUAL_MIXER_COMMAND", None, "input") -> "I_Manual_Mixer_Command"
      ("OUTPUT", "heater", "output")         -> "Q_Heater"
      ("COMMAND", "motor 2", "input")        -> "I_Motor_2_Command"
    """
    normalized_kind = normalize_kind(kind)
    if normalized_kind is None:
        return None
    redundant = _KIND_WORDS[normalized_kind]
    role_tokens = [t for t in _ascii_tokens(role) if t not in redundant]
    actor_tokens = [t for t in _ascii_tokens(actor) if t not in redundant]
    if not role_tokens and not actor_tokens:
        return None
    # El actor encabeza el nombre salvo que el rol ya lo nombre ("MANUAL_MIXER_COMMAND" + "mixer").
    tokens = role_tokens if all(t in role_tokens for t in actor_tokens) else actor_tokens + role_tokens
    deduplicated: list[str] = []
    for token in tokens:
        if not deduplicated or deduplicated[-1] != token:
            deduplicated.append(token)
    name = KIND_PREFIXES[normalized_kind] + "_".join(t.capitalize() if not t.isdigit() else t for t in deduplicated)
    return name if _TAG.match(name) else None


def condition_identifiers(expression: Any) -> list[str] | None:
    """
    Tags de una condicion booleana simple ("I_Start AND M_AutoMode"). None si la expresion usa algo
    que no sea tags, AND/OR/NOT/XOR/TRUE/FALSE o parentesis (nunca se ejecuta texto libre).
    """
    text = str(expression or "").strip()
    if not text:
        return []
    if re.sub(r"[A-Za-z0-9_()\s]", "", text):
        return None
    tags: list[str] = []
    for identifier in _IDENTIFIER.findall(text):
        if identifier.upper() in _EXPRESSION_KEYWORDS:
            continue
        if not _TAG.match(identifier):
            return None
        if identifier not in tags:
            tags.append(identifier)
    return tags


def _error(code: str, path: str, requirement_type: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "path": path, "requirement_type": requirement_type, "message": f"{code}: {message} ({path})",
            **{key: value for key, value in details.items() if value not in (None, "")}}


class _Resolver:
    def __init__(self) -> None:
        self.errors: list[dict[str, Any]] = []
        self.derived: list[dict[str, Any]] = []
        self.referenced_tags: list[str] = []

    def _remember(self, tag: str) -> None:
        if tag not in self.referenced_tags:
            self.referenced_tags.append(tag)

    def reference(self, value: Any, path: str, field_kind: str | None, requirement_type: str) -> Any:
        """Un valor en un campo de recurso: tag (string) o referencia {role, actor, kind}."""
        if isinstance(value, str):
            tag = value.strip()
            if not tag:
                self.errors.append(_error(FUNCTIONAL_RESOURCE_UNRESOLVED, path, requirement_type,
                                          "recurso funcional vacio: no se puede identificar", kind=field_kind))
                return value
            if _TAG.match(tag):
                self._remember(tag)
            return tag
        if not isinstance(value, dict):
            return value
        explicit = next((str(value[key]).strip() for key in _REFERENCE_NAME_KEYS if str(value.get(key) or "").strip()), "")
        if explicit:
            if _TAG.match(explicit):
                self._remember(explicit)
            return explicit
        role, actor = value.get("role"), value.get("actor")
        kind = normalize_kind(value.get("kind") or value.get("direction")) or field_kind
        name = canonical_functional_tag(role, actor, kind)
        if name is None:
            self.errors.append(_error(
                FUNCTIONAL_RESOURCE_UNRESOLVED, path, requirement_type,
                "recurso funcional sin nombre que no se puede identificar sin inventarlo "
                f"(role={role!r}, actor={actor!r}, kind={kind!r})", role=role, actor=actor, kind=kind))
            return value
        self.derived.append({"path": path, "name": name, "role": role, "actor": actor, "kind": kind,
                             "requirement_type": requirement_type})
        self._remember(name)
        return name

    def walk(self, value: Any, path: str, requirement_type: str, field_kind: str | None = None) -> Any:
        if field_kind is not None:
            if isinstance(value, list):
                return [self.reference(item, f"{path}[{i}]", field_kind, requirement_type) for i, item in enumerate(value)]
            return self.reference(value, path, field_kind, requirement_type)
        if isinstance(value, list):
            return [self.walk(item, f"{path}[{i}]", requirement_type) for i, item in enumerate(value)]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                child_path = f"{path}.{key}"
                if key in _CONDITION_KEYS and isinstance(item, str):
                    tags = condition_identifiers(item)
                    for tag in tags or []:
                        self._remember(tag)
                    result[key] = item
                    continue
                result[key] = self.walk(item, child_path, requirement_type, kind_from_field(key))
            return result
        return value


def resolve_functional_resources(functional_requirements: Any, base_path: str = "functional_requirements") -> dict[str, Any]:
    """
    Normaliza y valida los recursos de functional_requirements (recorrido recursivo: steps[].outputs,
    commands[].input/output, affected_outputs, ...). Devuelve:
      requirements    copia con cada referencia sin nombre reemplazada por su tag canonico;
      errors          errores estructurados {code, path, requirement_type, message, ...};
      derived         nombres derivados {path, name, role, actor, kind};
      referenced_tags tags I_/Q_/M_/... referenciados (incluidas condiciones simples).
    """
    resolver = _Resolver()
    normalized: list[Any] = []
    for index, requirement in enumerate(functional_requirements or []):
        path = f"{base_path}[{index}]"
        if not isinstance(requirement, dict):
            resolver.errors.append(_error(FUNCTIONAL_RESOURCE_UNRESOLVED, path, "",
                                          "requisito funcional que no es un objeto"))
            normalized.append(requirement)
            continue
        requirement_type = str(requirement.get("type") or "").strip()
        if not requirement_type and not str(requirement.get("name") or "").strip():
            resolver.errors.append(_error(FUNCTIONAL_RESOURCE_UNRESOLVED, path, "",
                                          "requisito funcional sin tipo ni nombre: no se puede identificar"))
            normalized.append(requirement)
            continue
        if classify_functional_requirement(requirement) == CLASS_UNSUPPORTED:
            resolver.errors.append(_error(
                FUNCTIONAL_REQUIREMENT_UNSUPPORTED, f"{path}.type", requirement_type,
                f"el comportamiento '{requirement_type}' no es una primitiva funcional soportada y no es una variable"))
            normalized.append(requirement)
            continue
        normalized.append(resolver.walk(copy.deepcopy(requirement), path, requirement_type))
    return {"requirements": normalized, "errors": resolver.errors, "derived": resolver.derived,
            "referenced_tags": resolver.referenced_tags}


class FunctionalResourceError(ValueError):
    """Recursos funcionales no identificables/nombrables: se detiene ANTES de construir la IR."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__("; ".join(error["message"] for error in errors))
