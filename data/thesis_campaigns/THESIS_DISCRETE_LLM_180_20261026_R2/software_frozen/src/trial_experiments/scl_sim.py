"""
Simulador SCL de verificacion (DEVELOPMENT): interpreta el subconjunto de SCL que genera este proyecto
(siemens_scl_adapter) y lo ejecuta ciclo a ciclo contra un Oracle, SIN TIA Portal ni PLCSIM.

No es un ensayo ni sustituye a PLCSIM: es la herramienta con la que la auditoria de preparacion
(preformal_readiness_audit) y los tests comprueban, de forma reproducible, que una capacidad del generador
existe y produce el comportamiento que el benchmark especifica. Un ensayo DEVELOPMENT/FORMAL sigue
ejecutandose siempre en TIA Portal + PLCSIM Advanced.

Subconjunto soportado (exactamente el que emite el generador):
  - FUNCTION_BLOCK con VAR_INPUT / VAR_OUTPUT / VAR (estaticas e instancias IEC), DATA_BLOCK de instancia y
    ORGANIZATION_BLOCK "Main" que cablea entradas/salidas a tags PLC;
  - sentencias: asignacion, IF/ELSIF/ELSE, CASE (etiquetas enteras, listas y rangos), llamadas a instancias;
  - expresiones: OR, XOR, AND/&, NOT, = <> < > <= >=, + - * / MOD, parentesis, TRUE/FALSE, numeros, T#...;
  - instancias IEC: TON/TP/TOF (_TIME), CTU (_INT), R_TRIG, F_TRIG (campos Q, ET, CV).

Memoria (misma convencion que el bridge real): entradas y salidas del FB son tags PLC (io["I_Start"]);
las estaticas viven en el DB de instancia (io["DB_PLC_PRG.Auto_Mode"]) y el arnes puede escribirlas entre
ciclos, como PLCSIM. Cualquier construccion fuera del subconjunto lanza SclSimError (nunca se adivina).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

DEFAULT_INSTANCE_DB = "DB_PLC_PRG"
DEFAULT_CYCLE_MS = 10.0
_KEYWORDS = {
    "IF", "THEN", "ELSIF", "ELSE", "END_IF", "CASE", "OF", "END_CASE", "AND", "OR", "XOR", "NOT", "MOD",
    "TRUE", "FALSE",
}
_IEC_TYPES = {
    "TON_TIME": "TON", "TON": "TON", "TP_TIME": "TP", "TP": "TP", "TOF_TIME": "TOF", "TOF": "TOF",
    "CTU_INT": "CTU", "CTU": "CTU", "R_TRIG": "R_TRIG", "F_TRIG": "F_TRIG",
}
_TIME_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s|d)", re.IGNORECASE)
_TIME_FACTORS = {"ms": 1.0, "s": 1000.0, "m": 60000.0, "h": 3600000.0, "d": 86400000.0}


class SclSimError(ValueError):
    """Construccion SCL fuera del subconjunto que genera el proyecto (o programa mal formado)."""


# ---------------------------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------------------------

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<time>(?:T|TIME)\#[0-9A-Za-z_.]+)
  | (?P<number>\d+\.\d+(?:[eE][+-]?\d+)?|\d+)
  | (?P<ident>\#?"[^"]+"|\#?[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>:=|=>|<>|<=|>=|\.\.|[=<>+\-*/(),;:.&\[\]])
    """,
    re.VERBOSE,
)


def _strip_comments(text: str) -> str:
    text = re.sub(r"\(\*.*?\*\)", " ", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", " ", text)


def parse_time_ms(literal: str) -> float:
    body = literal.split("#", 1)[1].replace("_", "")
    parts = _TIME_PART.findall(body)
    if not parts or "".join(f"{value}{unit}" for value, unit in parts).lower() != body.lower():
        raise SclSimError(f"Literal TIME no soportado: {literal}")
    return sum(float(value) * _TIME_FACTORS[unit.lower()] for value, unit in parts)


@dataclass
class _Tok:
    kind: str
    value: str

    @property
    def upper(self) -> str:
        return self.value.upper()


def _tokenize(text: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match:
            raise SclSimError(f"Caracter no soportado en SCL: {text[position:position + 20]!r}")
        position = match.end()
        kind = match.lastgroup
        if kind == "ws":
            continue
        value = match.group(kind)
        if kind == "ident" and value.upper() in _KEYWORDS:
            kind = "kw"
        tokens.append(_Tok(kind, value))
    tokens.append(_Tok("eof", ""))
    return tokens


def _clean_name(raw: str) -> str:
    return raw.lstrip("#").strip('"')


# ---------------------------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------------------------

@dataclass
class Program:
    name: str
    inputs: dict[str, str]
    outputs: dict[str, str]
    statics: dict[str, str]
    initial: dict[str, Any]
    instances: dict[str, str]
    body: list[tuple]
    wiring: dict[str, str] = field(default_factory=dict)


class _Parser:
    def __init__(self, tokens: list[_Tok]) -> None:
        self.tokens, self.index = tokens, 0

    def peek(self, offset: int = 0) -> _Tok:
        return self.tokens[min(self.index + offset, len(self.tokens) - 1)]

    def take(self) -> _Tok:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def expect(self, value: str) -> _Tok:
        token = self.take()
        if token.upper != value.upper():
            raise SclSimError(f"Se esperaba {value!r} y llego {token.value!r}")
        return token

    def at(self, *values: str) -> bool:
        return self.peek().upper in {value.upper() for value in values}

    # --- sentencias -----------------------------------------------------------------------------
    def statements(self, *terminators: str) -> list[tuple]:
        body: list[tuple] = []
        while not self.at(*terminators):
            if self.peek().kind == "eof":
                raise SclSimError(f"Fin inesperado; se esperaba {terminators}")
            statement = self.statement()
            if statement is not None:
                body.append(statement)
        return body

    def statement(self) -> tuple | None:
        token = self.peek()
        if token.value == ";":
            self.take()
            return None
        if token.upper == "IF":
            return self.if_statement()
        if token.upper == "CASE":
            return self.case_statement()
        if token.kind != "ident":
            raise SclSimError(f"Sentencia no soportada: {token.value!r}")
        target = self.reference()
        if self.peek().value == ":=":
            self.take()
            value = self.expression()
            self.expect(";")
            return ("assign", target, value)
        if self.peek().value == "(":
            self.take()
            arguments: dict[str, tuple] = {}
            while self.peek().value != ")":
                name = _clean_name(self.take().value)
                operator = self.take().value
                if operator != ":=":
                    raise SclSimError(f"Parametro de salida en llamada no soportado: {name} {operator}")
                arguments[name] = self.expression()
                if self.peek().value == ",":
                    self.take()
            self.expect(")")
            self.expect(";")
            return ("call", target[0], arguments)
        raise SclSimError(f"Sentencia no soportada tras {target}")

    def reference(self) -> tuple[str, str | None]:
        name = _clean_name(self.take().value)
        member = None
        if self.peek().value == "." and self.peek(1).kind == "ident":
            self.take()
            member = _clean_name(self.take().value)
        return (name, member)

    def if_statement(self) -> tuple:
        self.expect("IF")
        branches = []
        condition = self.expression()
        self.expect("THEN")
        branches.append((condition, self.statements("ELSIF", "ELSE", "END_IF")))
        otherwise: list[tuple] = []
        while self.at("ELSIF"):
            self.take()
            condition = self.expression()
            self.expect("THEN")
            branches.append((condition, self.statements("ELSIF", "ELSE", "END_IF")))
        if self.at("ELSE"):
            self.take()
            otherwise = self.statements("END_IF")
        self.expect("END_IF")
        if self.peek().value == ";":
            self.take()
        return ("if", branches, otherwise)

    def case_statement(self) -> tuple:
        self.expect("CASE")
        selector = self.expression()
        self.expect("OF")
        branches: list[tuple[list[tuple[int, int]], list[tuple]]] = []
        otherwise: list[tuple] = []
        while not self.at("END_CASE", "ELSE"):
            labels = [self.case_label()]
            while self.peek().value == ",":
                self.take()
                labels.append(self.case_label())
            self.expect(":")
            body: list[tuple] = []
            while not self.at("END_CASE", "ELSE") and not self._label_ahead():
                statement = self.statement()
                if statement is not None:
                    body.append(statement)
            branches.append((labels, body))
        if self.at("ELSE"):
            self.take()
            otherwise = self.statements("END_CASE")
        self.expect("END_CASE")
        if self.peek().value == ";":
            self.take()
        return ("case", selector, branches, otherwise)

    def _label_ahead(self) -> bool:
        offset = 0
        if self.peek().value == "-":
            offset = 1
        if self.peek(offset).kind != "number":
            return False
        follower = self.peek(offset + 1).value
        return follower in {":", ",", ".."}

    def case_label(self) -> tuple[int, int]:
        low = self._signed_int()
        high = low
        if self.peek().value == "..":
            self.take()
            high = self._signed_int()
        return (low, high)

    def _signed_int(self) -> int:
        sign = -1 if self.peek().value == "-" else 1
        if sign < 0:
            self.take()
        token = self.take()
        if token.kind != "number":
            raise SclSimError(f"Etiqueta CASE no entera: {token.value!r}")
        return sign * int(float(token.value))

    # --- expresiones (precedencia IEC 61131-3) --------------------------------------------------
    def expression(self) -> tuple:
        return self._binary(("OR",), self._xor)

    def _xor(self) -> tuple:
        return self._binary(("XOR",), self._and)

    def _and(self) -> tuple:
        return self._binary(("AND", "&"), self._equality)

    def _equality(self) -> tuple:
        return self._binary(("=", "<>"), self._relational)

    def _relational(self) -> tuple:
        return self._binary(("<", ">", "<=", ">="), self._additive)

    def _additive(self) -> tuple:
        return self._binary(("+", "-"), self._multiplicative)

    def _multiplicative(self) -> tuple:
        return self._binary(("*", "/", "MOD"), self._unary)

    def _binary(self, operators: tuple[str, ...], operand: Callable[[], tuple]) -> tuple:
        left = operand()
        while self.peek().upper in operators:
            operator = self.take().upper
            operator = "AND" if operator == "&" else operator
            left = ("bin", operator, left, operand())
        return left

    def _unary(self) -> tuple:
        if self.at("NOT"):
            self.take()
            return ("not", self._unary())
        if self.peek().value == "-":
            self.take()
            return ("neg", self._unary())
        return self._primary()

    def _primary(self) -> tuple:
        token = self.take()
        if token.value == "(":
            inner = self.expression()
            self.expect(")")
            return inner
        if token.upper in {"TRUE", "FALSE"}:
            return ("const", token.upper == "TRUE")
        if token.kind == "number":
            return ("const", float(token.value) if "." in token.value or "e" in token.value.lower() else int(token.value))
        if token.kind == "time":
            return ("const", parse_time_ms(token.value))
        if token.kind == "ident":
            name = _clean_name(token.value)
            if self.peek().value == "(" and name.upper() in {"INT_TO_REAL", "REAL_TO_INT"}:
                self.take()
                argument = self.expression()
                self.expect(")")
                return ("conversion", name.upper(), argument)
            if self.peek().value == "." and self.peek(1).kind == "ident":
                self.take()
                return ("member", name, _clean_name(self.take().value))
            return ("var", name)
        raise SclSimError(f"Expresion no soportada en {token.value!r}")


def _declarations(section: str) -> list[tuple[str, str, str | None]]:
    rows = []
    section = re.sub(r"\{[^}]*\}", " ", section)  # atributos {InstructionName := ...; ...} contienen ';'
    for line in section.split(";"):
        line = line.strip()
        if not line:
            continue
        match = re.match(r'^"?([A-Za-z_][A-Za-z0-9_]*)"?\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?::=\s*(.+))?$', line)
        if not match:
            raise SclSimError(f"Declaracion no soportada: {line!r}")
        rows.append((match.group(1), match.group(2), match.group(3)))
    return rows


def _initial(data_type: str, literal: str | None) -> Any:
    upper = data_type.upper()
    if literal is not None:
        text = literal.strip()
        if text.upper() in {"TRUE", "FALSE"}:
            return text.upper() == "TRUE"
        if text.upper().startswith(("T#", "TIME#")):
            return parse_time_ms(text)
        return float(text) if upper in {"REAL", "LREAL"} or "." in text else int(text)
    if upper == "BOOL":
        return False
    if upper in {"REAL", "LREAL"}:
        return 0.0
    return 0


def parse_program(source: str) -> Program:
    text = _strip_comments(source)
    fb = re.search(r'FUNCTION_BLOCK\s+"([^"]+)"(.*?)END_FUNCTION_BLOCK', text, flags=re.DOTALL)
    if not fb:
        raise SclSimError("No hay FUNCTION_BLOCK en el programa.")
    name, fb_text = fb.group(1), fb.group(2)
    begin = re.search(r"\bBEGIN\b", fb_text)
    if not begin:
        raise SclSimError("El FUNCTION_BLOCK no tiene BEGIN.")
    header, body_text = fb_text[:begin.start()], fb_text[begin.end():]
    inputs: dict[str, str] = {}
    outputs: dict[str, str] = {}
    statics: dict[str, str] = {}
    instances: dict[str, str] = {}
    initial: dict[str, Any] = {}
    for kind, section in re.findall(r"\b(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR)\b(.*?)\bEND_VAR\b", header, flags=re.DOTALL):
        if kind in {"VAR_IN_OUT", "VAR_TEMP"}:
            raise SclSimError(f"Seccion {kind} no soportada por el simulador.")
        for var_name, data_type, literal in _declarations(section):
            iec = _IEC_TYPES.get(data_type.upper())
            if iec:
                instances[var_name] = iec
                continue
            target = {"VAR_INPUT": inputs, "VAR_OUTPUT": outputs, "VAR": statics}[kind]
            target[var_name] = data_type
            initial[var_name] = _initial(data_type, literal)
    body = _Parser(_tokenize(body_text)).statements("")
    wiring: dict[str, str] = {}
    main = re.search(r'ORGANIZATION_BLOCK\s+"Main".*?BEGIN(.*?)END_ORGANIZATION_BLOCK', text, flags=re.DOTALL)
    if main:
        for formal, _operator, actual in re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\s*(:=|=>)\s*"([^"]+)"', main.group(1)):
            wiring[formal] = actual
    for formal in list(inputs) + list(outputs):
        wiring.setdefault(formal, formal)
    return Program(name, inputs, outputs, statics, initial, instances, body, wiring)


# ---------------------------------------------------------------------------------------------
# Interprete
# ---------------------------------------------------------------------------------------------

class _Instance:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.fields: dict[str, Any] = {"Q": False, "ET": 0.0, "CV": 0}
        self.prev = False
        self.running = False

    def call(self, args: dict[str, Any], dt: float) -> None:
        f = self.fields
        if self.kind in {"R_TRIG", "F_TRIG"}:
            clk = bool(args.get("CLK", False))
            f["Q"] = (clk and not self.prev) if self.kind == "R_TRIG" else (self.prev and not clk)
            self.prev = clk
            return
        if self.kind == "CTU":
            cu, reset, preset = bool(args.get("CU", False)), bool(args.get("R", False)), int(args.get("PV", 0) or 0)
            if reset:
                f["CV"] = 0
            elif cu and not self.prev and f["CV"] < 32767:
                f["CV"] += 1
            self.prev = cu
            f["Q"] = f["CV"] >= preset
            return
        enable, preset = bool(args.get("IN", False)), float(args.get("PT", 0.0) or 0.0)
        if self.kind == "TON":
            f["ET"] = min(f["ET"] + dt, preset) if enable else 0.0
            f["Q"] = enable and f["ET"] >= preset
        elif self.kind == "TOF":
            if enable:
                f["ET"], f["Q"] = 0.0, True
            elif f["Q"]:
                f["ET"] = min(f["ET"] + dt, preset)
                f["Q"] = f["ET"] < preset
        elif self.kind == "TP":
            if enable and not self.prev and not self.running:
                self.running, f["ET"] = True, 0.0
            if self.running:
                f["ET"] = min(f["ET"] + dt, preset)
                if f["ET"] >= preset:
                    self.running = False
            elif not enable:
                f["ET"] = 0.0
            f["Q"] = self.running
        self.prev = enable


class SclMachine:
    """Ejecuta el FB ciclo a ciclo sobre `io` (tags PLC + estaticas DB.<miembro>)."""

    def __init__(self, program: Program | str, instance_db: str = DEFAULT_INSTANCE_DB) -> None:
        self.program = parse_program(program) if isinstance(program, str) else program
        self.instance_db = instance_db
        self.locals: dict[str, Any] = {}
        self.instances = {name: _Instance(kind) for name, kind in self.program.instances.items()}
        self.dt = DEFAULT_CYCLE_MS

    def static_key(self, name: str) -> str:
        return f"{self.instance_db}.{name}"

    def initialize(self, io: dict[str, Any]) -> None:
        for name in self.program.statics:
            io.setdefault(self.static_key(name), self.program.initial[name])
        for name in self.program.outputs:
            self.locals[name] = self.program.initial[name]
            io.setdefault(self.program.wiring[name], self.program.initial[name])
        for name in self.program.inputs:
            io.setdefault(self.program.wiring[name], self.program.initial[name])

    def scan(self, io: dict[str, Any], dt: float = DEFAULT_CYCLE_MS) -> None:
        self.dt = dt
        for name in self.program.inputs:
            self.locals[name] = io.get(self.program.wiring[name], self.program.initial[name])
        self._run(self.program.body, io)
        for name in self.program.outputs:
            io[self.program.wiring[name]] = self.locals[name]

    # --- ejecucion -------------------------------------------------------------------------------
    def _run(self, body: list[tuple], io: dict[str, Any]) -> None:
        for statement in body:
            kind = statement[0]
            if kind == "assign":
                (name, member), value = statement[1], self._eval(statement[2], io)
                if member is not None:
                    raise SclSimError(f"Asignacion a miembro de instancia no soportada: {name}.{member}")
                self._store(name, value, io)
            elif kind == "call":
                instance = self.instances.get(statement[1])
                if instance is None:
                    raise SclSimError(f"Llamada a {statement[1]} sin instancia IEC declarada.")
                instance.call({key: self._eval(expr, io) for key, expr in statement[2].items()}, self.dt)
            elif kind == "if":
                for condition, branch in statement[1]:
                    if self._truth(self._eval(condition, io)):
                        self._run(branch, io)
                        break
                else:
                    self._run(statement[2], io)
            elif kind == "case":
                selector = int(self._eval(statement[1], io))
                for labels, branch in statement[2]:
                    if any(low <= selector <= high for low, high in labels):
                        self._run(branch, io)
                        break
                else:
                    self._run(statement[3], io)

    @staticmethod
    def _truth(value: Any) -> bool:
        if not isinstance(value, bool):
            raise SclSimError(f"Condicion no booleana: {value!r}")
        return value

    def _store(self, name: str, value: Any, io: dict[str, Any]) -> None:
        if name in self.program.outputs or name in self.program.inputs:
            self.locals[name] = self._coerce(name, value)
        elif name in self.program.statics:
            io[self.static_key(name)] = self._coerce(name, value)
        else:
            raise SclSimError(f"Asignacion a variable no declarada: {name}")

    def _coerce(self, name: str, value: Any) -> Any:
        data_type = (self.program.inputs.get(name) or self.program.outputs.get(name) or self.program.statics.get(name) or "").upper()
        if data_type in {"REAL", "LREAL"} and isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return value

    def _load(self, name: str, io: dict[str, Any]) -> Any:
        if name in self.locals:
            return self.locals[name]
        if name in self.program.statics:
            return io.get(self.static_key(name), self.program.initial[name])
        raise SclSimError(f"Variable no declarada: {name}")

    def _eval(self, node: tuple, io: dict[str, Any]) -> Any:
        kind = node[0]
        if kind == "conversion":
            value = self._eval(node[2], io)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SclSimError(f"Conversión numérica inválida: {value!r}")
            if node[1] == "INT_TO_REAL":
                return float(value)
            converted = round(value)
            if not -32768 <= converted <= 32767:
                raise SclSimError(f"REAL_TO_INT fuera de rango: {value!r}")
            return converted
        if kind == "const":
            return node[1]
        if kind == "var":
            return self._load(node[1], io)
        if kind == "member":
            instance = self.instances.get(node[1])
            if instance is None or node[2] not in instance.fields:
                raise SclSimError(f"Miembro no soportado: {node[1]}.{node[2]}")
            return instance.fields[node[2]]
        if kind == "not":
            value = self._eval(node[1], io)
            if not isinstance(value, bool):
                raise SclSimError("NOT sobre un valor no booleano.")
            return not value
        if kind == "neg":
            return -self._eval(node[1], io)
        operator, left, right = node[1], self._eval(node[2], io), self._eval(node[3], io)
        if operator in {"AND", "OR", "XOR"}:
            if not (isinstance(left, bool) and isinstance(right, bool)):
                raise SclSimError(f"{operator} con operandos no booleanos.")
            return {"AND": left and right, "OR": left or right, "XOR": left != right}[operator]
        if operator == "=":
            return left == right
        if operator == "<>":
            return left != right
        if operator == "<":
            return left < right
        if operator == ">":
            return left > right
        if operator == "<=":
            return left <= right
        if operator == ">=":
            return left >= right
        if operator == "+":
            return left + right
        if operator == "-":
            return left - right
        if operator == "*":
            return left * right
        if operator == "/":
            return left / right if isinstance(left, float) or isinstance(right, float) else int(left / right)
        if operator == "MOD":
            return left % right
        raise SclSimError(f"Operador no soportado: {operator}")


# ---------------------------------------------------------------------------------------------
# Bridge simulado (mismo contrato io_sequence que plcsim_runtime_io / el bridge C#)
# ---------------------------------------------------------------------------------------------

class SimulatedPlcBridge:
    """
    Sustituto offline del bridge PLCSIM para oracle_runner.run_oracle(bridge=...): escribe estimulos entre
    ciclos, muestrea, comprueba `require` de precondiciones y restaura entradas al final. Para variables de
    proceso INPUT reproduce el readback del bridge real: si el programa cambia el valor escrito en el ciclo
    siguiente, la escritura queda clasificada PROGRAM_OVERWRITES_HARNESS_INPUT.
    """

    def __init__(self, program: Program | str, cycle_ms: float = DEFAULT_CYCLE_MS, instance_db: str = DEFAULT_INSTANCE_DB,
                 initial_io: dict[str, Any] | None = None) -> None:
        self.machine = SclMachine(program, instance_db)
        self.cycle_ms = float(cycle_ms)
        self.io: dict[str, Any] = dict(initial_io or {})
        self.machine.initialize(self.io)
        self.t = 0.0
        self.calls: list[dict[str, Any]] = []
        self._stamp = datetime(2026, 1, 1, 12, 0, 0)

    def _advance(self, until: float) -> None:
        while self.t + self.cycle_ms <= until + 1e-9:
            self.t += self.cycle_ms
            self.machine.scan(self.io, self.cycle_ms)
        self.t = max(self.t, until)

    def _timestamp(self) -> str:
        return (self._stamp + timedelta(milliseconds=self.t)).isoformat(timespec="milliseconds")

    @staticmethod
    def _key(signal: dict[str, Any]) -> str:
        return str(signal["name"])

    def __call__(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        if self.t == 0.0:
            self._advance(self.cycle_ms * 3)  # el programa ya lleva ciclos ejecutandose al empezar el Oracle
        events: list[dict[str, Any]] = []
        samples: list[dict[str, Any]] = []
        overwrites: list[dict[str, Any]] = []
        written: dict[str, dict[str, Any]] = {}
        status, errors, failed = "PLCSIM_IO_PASSED", [], None
        for step in payload.get("steps") or []:
            if step["op"] == "set":
                self.t += 0.5  # la escritura ocurre siempre despues de la ultima muestra del paso anterior
                entries = []
                for write in step["writes"]:
                    signal, value = write["signal"], write["value"]
                    key = self._key(signal)
                    if signal.get("data_type") == "REAL" and not isinstance(value, bool):
                        value = float(value)
                    self.io[key] = value
                    written[key] = signal
                    entry = {"name": key, "requested_value": write["value"], "write_call_success": True,
                             "write_timestamp": self._timestamp(), "initial_readback": value, "actual_readback": value,
                             "match": True, "classification": "CONFIRMED"}
                    if signal.get("kind") == "PROCESS_VARIABLE":
                        entry.update({"kind": "PROCESS_VARIABLE", "runtime_name": key, "data_type": signal.get("data_type")})
                    entries.append(entry)
                events.append({"type": "set", "id": step["id"], "phase": step["phase"], "t_ms": self.t,
                               "t_done_ms": self.t, "timestamp": self._timestamp(), "writes": entries})
                # Readback tras un ciclo: el bridge real detecta asi que el programa sobrescribe el estimulo.
                self._advance(self.t + self.cycle_ms)
                for entry, write in zip(entries, step["writes"]):
                    if entry.get("kind") != "PROCESS_VARIABLE":
                        continue
                    observed = self.io.get(entry["name"])
                    if observed != entry["initial_readback"]:
                        entry.update({"actual_readback": observed, "match": False, "observed_after_cycle": observed,
                                      "observed_after_cycle_timestamp": self._timestamp(), "observed_wait_ms": self.cycle_ms,
                                      "classification": "PROGRAM_OVERWRITES_HARNESS_INPUT",
                                      "observed_equals_original": False})
                        overwrites.append({**entry, "step_id": step["id"]})
                continue
            start, count = self.t, 0
            values: dict[str, Any] = {}
            while True:
                self._advance(min(start + count * step["period_ms"], start + step["duration_ms"]))
                values = {s["name"]: self.io.get(self._key(s), False) for s in step["signals"]}
                samples.append({"id": step["id"], "phase": step["phase"], "t_ms": self.t, "values": values})
                count += 1
                if self.t - start >= step["duration_ms"]:
                    break
            require = step.get("require")
            if require and any(not _value_matches(expected, values.get(name)) for name, expected in require.items()):
                status, failed = "PLCSIM_SEQUENCE_REQUIREMENT_FAILED", step["id"]
                errors.append(f"Requisito de precondicion no cumplido en {step['id']}.")
                break
        restored = []
        for key, signal in written.items():
            if signal.get("kind") == "PROCESS_VARIABLE":
                if "restore_value" in signal:
                    self.io[key] = signal["restore_value"]
                    restored.append(key)
            elif isinstance(self.io.get(key), bool):
                self.io[key] = False
                restored.append(key)
        report = {"status": status, "cpu_state": "RUN", "events": events, "samples": samples, "errors": errors,
                  "warnings": [], "failed_step": failed,
                  "cleanup": {"performed": bool(written), "success": True, "inputs": restored, "process_variables": []}}
        if overwrites:
            report["harness_input_overwrites"] = overwrites
        return report


def _value_matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        if actual is None or isinstance(actual, bool):
            return False
        if "approx" in expected:
            return abs(float(actual) - float(expected["approx"])) <= float(expected.get("tolerance", 0.0))
        return float(expected.get("min", float("-inf"))) <= float(actual) <= float(expected.get("max", float("inf")))
    return actual == expected


__all__ = ["SclSimError", "SclMachine", "SimulatedPlcBridge", "parse_program", "parse_time_ms", "Program"]
