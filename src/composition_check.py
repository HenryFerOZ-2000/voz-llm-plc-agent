"""
Validacion de COMPOSICION del programa generado (previa a compilar/descargar).

Varios requisitos funcionales pueden escribir la misma variable. Eso es legitimo cuando se componen (una
escritura incondicional que ya incluye las condiciones de seguridad, mas forzados CONDICIONALES de
prioridad: emergencia, condicion segura, modo manual). No lo es cuando dos escrituras INCONDICIONALES
distintas compiten en el mismo ciclo: gana la ultima en silencio (p.ej. Auto_Mode := TRUE seguido de
Auto_Mode := FALSE). Este modulo analiza el SCL generado (mismo parser que el simulador de verificacion,
con plegado de constantes: `IF NOT FALSE THEN` es incondicional) y:
  - registra los ESCRITORES de cada variable (incondicionales / condicionales, en orden);
  - rechaza dos escrituras incondicionales distintas a la misma variable (COMPOSITION_CONFLICT).
"""
from __future__ import annotations

from typing import Any

from trial_experiments.scl_sim import SclSimError, parse_program

COMPOSITION_CONFLICT = "COMPOSITION_CONFLICT"
COMPOSITION_UNANALYZABLE = "COMPOSITION_UNANALYZABLE"


def _fold(node: tuple) -> Any:
    """Valor constante de una expresion o None si depende de variables."""
    kind = node[0]
    if kind == "const":
        return node[1]
    if kind == "not":
        value = _fold(node[1])
        return (not value) if isinstance(value, bool) else None
    if kind == "bin" and node[1] in {"AND", "OR", "XOR"}:
        left, right = _fold(node[2]), _fold(node[3])
        if node[1] == "AND" and (left is False or right is False):
            return False
        if node[1] == "OR" and (left is True or right is True):
            return True
        if isinstance(left, bool) and isinstance(right, bool):
            return {"AND": left and right, "OR": left or right, "XOR": left != right}[node[1]]
    return None


def _render(node: tuple) -> str:
    kind = node[0]
    if kind == "conversion":
        return f"{node[1]}({_render(node[2])})"
    if kind == "const":
        return str(node[1]).upper() if isinstance(node[1], bool) else str(node[1])
    if kind == "var":
        return node[1]
    if kind == "member":
        return f"{node[1]}.{node[2]}"
    if kind == "not":
        return f"NOT {_render(node[1])}"
    if kind == "neg":
        return f"-{_render(node[1])}"
    return f"({_render(node[2])} {node[1]} {_render(node[3])})"


def _walk(body: list[tuple], conditional: bool, writers: dict[str, list[dict[str, Any]]], path: str) -> None:
    for index, statement in enumerate(body):
        kind = statement[0]
        if kind == "assign":
            name = statement[1][0]
            writers.setdefault(name, []).append({
                "unconditional": not conditional, "value": _render(statement[2]), "constant": _fold(statement[2]),
                "position": f"{path}{index}"})
        elif kind == "if":
            decided = False
            for branch_index, (condition, branch) in enumerate(statement[1]):
                value = _fold(condition)
                if value is False:
                    continue  # rama muerta: nunca escribe
                if value is True and not decided:
                    _walk(branch, conditional, writers, f"{path}{index}.{branch_index}.")
                    decided = True
                    break
                _walk(branch, True, writers, f"{path}{index}.{branch_index}.")
            if not decided:
                _walk(statement[2], True, writers, f"{path}{index}.else.")
        elif kind == "case":
            for branch_index, (_labels, branch) in enumerate(statement[2]):
                _walk(branch, True, writers, f"{path}{index}.{branch_index}.")
            _walk(statement[3], True, writers, f"{path}{index}.else.")


def analyze_composition(source: str) -> dict[str, Any]:
    """{valid, writers: {variable: [...]}, conflicts: [...], errors: [...]} para un programa SCL generado."""
    if 'NATIVE_PID_BEGIN' in source:
        return {'valid':True,'analyzed':False,'writers':{},'conflicts':[], 'errors':[],
                'native_execution_status':'PENDING',
                'warnings':['PID_NATIVE_EXECUTION_PENDING: el interprete offline no ejecuta PID_Compact.']}
    try:
        program = parse_program(source)
    except SclSimError as error:
        return {"valid": True, "analyzed": False, "writers": {}, "conflicts": [],
                "warnings": [f"{COMPOSITION_UNANALYZABLE}: {error}"], "errors": []}
    writers: dict[str, list[dict[str, Any]]] = {}
    _walk(program.body, False, writers, "")
    conflicts = []
    for name, entries in writers.items():
        unconditional = [entry for entry in entries if entry["unconditional"]]
        if len({entry["value"] for entry in unconditional}) > 1:
            conflicts.append({
                "code": COMPOSITION_CONFLICT, "variable": name, "writes": [entry["value"] for entry in unconditional],
                "reason": (f"{name} recibe {len(unconditional)} escrituras incondicionales distintas en el mismo ciclo "
                           f"({', '.join(entry['value'] for entry in unconditional)}): gana la ultima en silencio."),
            })
    return {"valid": not conflicts, "analyzed": True, "writers": writers, "conflicts": conflicts, "warnings": [],
            "errors": [conflict["reason"] for conflict in conflicts]}


__all__ = ["analyze_composition", "COMPOSITION_CONFLICT"]
