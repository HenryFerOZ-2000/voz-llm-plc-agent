"""
Fase 2B: Runtime I/O BOOL con S7-PLCSIM Advanced V5 (infraestructura, NO Oracle).

Que hace:
  - resuelve las senales del PROGRAMA ACTUAL desde io_map_snapshot.json del ensayo
    (bindings / parameter_bindings) o, sin ensayo, desde variables.json del paquete descargado;
  - escribe ENTRADAS BOOL y lee entradas/salidas BOOL en PLCSIM a traves del bridge
    (plcsim_runtime_bridge, acciones read_signal / write_input / io_sequence / restore_inputs);
  - readback obligatorio tras cada escritura y cleanup (entradas a FALSE, verificado).

Que NO hace: evaluar Functional/Safety Success, PASS/FAIL, secuencias temporizadas generales,
analogicos/PID, ni tocar mapas (working map, snapshot, base, fisico). Solo lee bindings.

Estrategia nombre/direccion (verificada contra la Runtime API V5 real):
  - acceso PRINCIPAL por direccion (IIOArea.ReadBit / InputArea.WriteBit con byte/bit del
    snapshot): es la memoria real de la imagen de proceso y no depende de simbolos;
  - el NOMBRE es verificacion obligatoria: el tag debe existir en el programa CARGADO en PLCSIM
    (TagInfos tras UpdateTagList) con la misma area/byte/bit; si no, el programa en PLCSIM no es
    el del ensayo (PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM). Tambien es el segundo canal de readback
    (ReadBool). Nunca se escribe por nombre (sin fallback de escritura).

Seguridad: toda escritura exige target PLCSIM_ADVANCED + Runtime conectado + instancia configurada
+ CPU RUN (comprobado aqui con el ultimo estado y de nuevo en el bridge en el momento de escribir).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import plcsim_runtime
from utils import get_project_root, load_json_file

TARGET_TYPE_PLCSIM = "PLCSIM_ADVANCED"

SUCCESS = "SUCCESS"
FAIL = "FAIL"

ERROR_WRITE_NOT_ALLOWED = "PLCSIM_IO_WRITE_NOT_ALLOWED"
ERROR_SIGNAL_NOT_FOUND = "PLCSIM_SIGNAL_NOT_FOUND"
ERROR_SIGNAL_NOT_IN_PROGRAM = "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM"
ERROR_TYPE_UNSUPPORTED = "PLCSIM_SIGNAL_TYPE_UNSUPPORTED"
ERROR_INPUT_WRITE_FAILED = "PLCSIM_INPUT_WRITE_FAILED"
ERROR_READBACK_MISMATCH = "PLCSIM_INPUT_READBACK_MISMATCH"
ERROR_OUTPUT_READ_FAILED = "PLCSIM_OUTPUT_READ_FAILED"
ERROR_CPU_NOT_RUN = "PLCSIM_CPU_NOT_RUN"
ERROR_CLEANUP_FAILED = "PLCSIM_IO_CLEANUP_FAILED"
ERROR_IO_TIMEOUT = "PLCSIM_RUNTIME_IO_TIMEOUT"
ERROR_NO_PROGRAM = "PLCSIM_IO_NO_PROGRAM"

REPORT_FILENAME = "plcsim_io_test_report.json"

SUPPORTED_DATA_TYPES = ("BOOL",)  # E/S fisicas: solo BOOL (Fase 2B). AI/AO/WORD/INT fuera de alcance.
# Capacidades del Runtime ACTUAL (vocabulario oracle_schema.RUNTIME_REQUIREMENTS) para la ejecucion por
# capacidades del Oracle Runner: E/S fisicas BOOL + variables internas (estaticas de DB) BOOL/REAL por
# nombre, leidas y escritas (solo roles INPUT PROCESS_VARIABLE, solo PLCSIM, solo durante el Oracle).
# INT/WORD no estan soportados: un Oracle que los requiera sigue en REVIEW (RUNTIME_EXTENSION_REQUIRED).
RUNTIME_CAPABILITIES = ("BOOL", "REAL", "INTERNAL_TAG_READ", "INTERNAL_TAG_WRITE")

_ADDRESS_PATTERN = re.compile(r"^%?\s*([IQ])\s*(X|B|W|D)?\s*(\d+)(?:\.(\d+))?$", re.IGNORECASE)


class RuntimeIOError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.detail = message


# ---------------------------------------------------------------------------------------------
# Direcciones: UNICA funcion de adaptacion Siemens <-> Runtime API
# ---------------------------------------------------------------------------------------------

def runtime_address(address: str) -> dict[str, Any]:
    """
    %IX16.0 == %I16.0 == I16.0  -> {area: Input,  offset: 16, bit: 0, size: X, address: %I16.0}
    %QX8.0  == %Q8.0            -> {area: Output, offset: 8,  bit: 0, size: X, address: %Q8.0}
    %IW0                        -> {area: Input,  offset: 0,  bit: None, size: W} (no BOOL)
    La Runtime API V5 no acepta texto: una direccion es area + byte (+ bit).
    """
    match = _ADDRESS_PATTERN.match(str(address or "").strip())
    if not match:
        raise RuntimeIOError(ERROR_SIGNAL_NOT_FOUND, f"Direccion no reconocida: {address!r}")
    letter, size, byte, bit = match.group(1).upper(), (match.group(2) or "").upper(), int(match.group(3)), match.group(4)
    if bit is not None:
        if size not in ("", "X"):
            raise RuntimeIOError(ERROR_SIGNAL_NOT_FOUND, f"Direccion invalida: {address!r}")
        bit_value = int(bit)
        if bit_value > 7:
            raise RuntimeIOError(ERROR_SIGNAL_NOT_FOUND, f"Bit fuera de rango en {address!r}")
        size = "X"
    else:
        bit_value = None
        if size in ("", "X"):
            raise RuntimeIOError(ERROR_SIGNAL_NOT_FOUND, f"Direccion de bit sin numero de bit: {address!r}")
    canonical = f"%{letter}{byte}.{bit_value}" if size == "X" else f"%{letter}{size}{byte}"
    return {
        "area": "Input" if letter == "I" else "Output",
        "direction": letter,
        "offset": byte,
        "bit": bit_value,
        "size": size,
        "address": canonical,
        "address_x": f"%{letter}X{byte}.{bit_value}" if size == "X" else canonical,
    }


def _signal(name: str, address: str, data_type: str, roles: list[str] | None = None) -> dict[str, Any]:
    location = runtime_address(address)
    return {
        "name": name,
        "address": location["address"],
        "address_x": location["address_x"],
        "area": location["area"],
        "direction": location["direction"],
        "offset": location["offset"],
        "bit": location["bit"],
        "size": location["size"],
        "data_type": str(data_type or "").upper(),
        "roles": list(roles or []),
    }


# ---------------------------------------------------------------------------------------------
# Senales del programa actual (fuente de verdad: snapshot del ensayo)
# ---------------------------------------------------------------------------------------------

def load_program_signals(snapshot_path: Path | None = None, variables_path: Path | None = None) -> dict[str, Any]:
    """
    Senales BOOL externas del programa cargado. Preferencia: io_map_snapshot.json del ensayo
    (bindings + parameter_bindings); si no hay ensayo, variables.json del paquete descargado.
    `inventory` = todo el inventario conocido (para distinguir "no existe" de "no es del programa").
    """
    if snapshot_path is not None and Path(snapshot_path).exists():
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        bound: dict[str, dict[str, Any]] = {}
        for binding in snapshot.get("bindings", []) or []:
            bound[binding["functional_name"]] = _signal(
                binding["functional_name"], binding["address"], binding.get("data_type"), binding.get("roles")
            )
        inventory = {
            channel["functional_name"]: channel.get("address")
            for channel in snapshot.get("channels", []) or [] if channel.get("functional_name")
        }
        result = {
            "source": "snapshot",
            "path": str(snapshot_path),
            "trial_id": snapshot.get("trial_id"),
            "signals": bound,
            "parameter_bindings": dict(snapshot.get("parameter_bindings") or {}),
            "inventory": inventory,
        }
        _attach_frozen_scales(result, Path(variables_path).parent if variables_path else None)
        return result
    if variables_path is not None and Path(variables_path).exists():
        payload = load_json_file(Path(variables_path))
        signals: dict[str, dict[str, Any]] = {}
        for variable in payload if isinstance(payload, list) else []:
            location = str(variable.get("location") or variable.get("siemens_address") or "")
            if variable.get("class") not in ("input", "output") or not location.startswith(("%I", "%Q")):
                continue
            try:
                signals[variable["name"]] = _signal(variable["name"], location, variable.get("type"))
            except RuntimeIOError:
                continue
        result = {
            "source": "variables",
            "path": str(variables_path),
            "trial_id": None,
            "signals": signals,
            "parameter_bindings": {},
            "inventory": {name: signal["address"] for name, signal in signals.items()},
        }
        _attach_frozen_scales(result, Path(variables_path).parent)
        return result
    raise RuntimeIOError(ERROR_NO_PROGRAM, "No hay snapshot de ensayo ni variables.json del programa descargado.")


def _attach_frozen_scales(program: dict, package: Path | None) -> None:
    """Only the downloaded package supplies scales; never consult the live map."""
    if package is None or not (package / 'generation_io_map.json').is_file():
        return
    payload = load_json_file(package / 'generation_io_map.json')
    for row in payload.get('variables', []):
        signal = program['signals'].get(row.get('name'))
        if signal is None or row.get('type') != signal['data_type']:
            continue
        try:
            same = runtime_address(row.get('location'))['address'] == signal['address']
        except RuntimeIOError:
            continue
        if same and isinstance(row.get('analog_config'), dict):
            import copy
            signal['analog_config'] = copy.deepcopy(row['analog_config'])


def bool_inputs(program: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in program["signals"].values() if s["direction"] == "I" and s["data_type"] in SUPPORTED_DATA_TYPES and s["bit"] is not None]


def bool_outputs(program: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in program["signals"].values() if s["direction"] == "Q" and s["data_type"] in SUPPORTED_DATA_TYPES and s["bit"] is not None]


def resolve_signal(program: dict[str, Any], name: str, for_write: bool) -> dict[str, Any]:
    """name -> senal del programa actual, o RuntimeIOError con el codigo exacto."""
    signal = program["signals"].get(name)
    if signal is None:
        if name in program.get("inventory", {}):
            raise RuntimeIOError(ERROR_SIGNAL_NOT_IN_PROGRAM, f"{name} existe en el mapa pero no pertenece al programa actual.")
        raise RuntimeIOError(ERROR_SIGNAL_NOT_FOUND, f"{name} no existe en el programa ni en el mapa del ensayo.")
    if for_write and signal["direction"] != "I":
        raise RuntimeIOError(ERROR_WRITE_NOT_ALLOWED, f"{name} ({signal['address']}) no es una entrada: las salidas solo se leen.")
    if signal["data_type"] not in SUPPORTED_DATA_TYPES or signal["bit"] is None:
        raise RuntimeIOError(ERROR_TYPE_UNSUPPORTED, f"{name} es {signal['data_type'] or '?'}: en esta fase solo BOOL.")
    return signal


# ---------------------------------------------------------------------------------------------
# Guardas de seguridad
# ---------------------------------------------------------------------------------------------

def check_write_allowed(target_type: str | None, runtime_report: dict[str, Any] | None, expected_instance: str) -> tuple[str, str] | None:
    """None si se puede escribir; si no (codigo, motivo). Sin fallback de ningun tipo."""
    if target_type != TARGET_TYPE_PLCSIM:
        return ERROR_WRITE_NOT_ALLOWED, f"El destino configurado es {target_type or '?'}; solo se escribe en {TARGET_TYPE_PLCSIM}."
    report = runtime_report or {}
    if not report.get("connected"):
        return ERROR_WRITE_NOT_ALLOWED, f"Runtime no conectado ({report.get('status') or 'sin verificar'})."
    if report.get("instance_name") != expected_instance:
        return ERROR_WRITE_NOT_ALLOWED, f"Instancia {report.get('instance_name')!r} distinta de la configurada {expected_instance!r}."
    if report.get("cpu_state") != plcsim_runtime.CPU_STATE_RUN:
        return ERROR_CPU_NOT_RUN, f"CPU en {report.get('cpu_state') or '?'}: solo se escribe con la CPU en RUN."
    return None


def io_test_availability(
    target_type: str | None, runtime_report: dict[str, Any] | None, expected_instance: str, program: dict[str, Any] | None,
    allow_manual_stop: bool = False
) -> tuple[bool, str]:
    """Para la GUI: la ventana PRUEBA DE I/O solo se habilita si todo esto se cumple."""
    blocked = check_write_allowed(target_type, runtime_report, expected_instance)
    if blocked and not (allow_manual_stop and blocked[0] == ERROR_CPU_NOT_RUN and (runtime_report or {}).get('cpu_state') == 'STOP'):
        return False, f"{blocked[0]}: {blocked[1]}"
    if not program or not program.get("signals"):
        return False, f"{ERROR_NO_PROGRAM}: no hay snapshot/programa valido del que tomar las senales."
    from runtime_io_controls import signals
    if not signals(program, 'I') and not signals(program, 'Q'):
        return False, f"{ERROR_TYPE_UNSUPPORTED}: el programa no tiene E/S compatibles."
    return True, ""


# ---------------------------------------------------------------------------------------------
# Sesion de Runtime I/O
# ---------------------------------------------------------------------------------------------

def _bridge_signal(signal: dict[str, Any]) -> dict[str, Any]:
    return {key: signal[key] for key in ("name", "address", "area", "offset", "bit", "data_type")}


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


class RuntimeIOSession:
    """
    Operaciones BOOL sobre PLCSIM para un programa concreto. Registra todo (writes, readbacks,
    reads, cleanup) para plcsim_io_test_report.json. `bridge` es inyectable para pruebas: pytest
    nunca toca el Runtime real.
    """

    def __init__(
        self,
        program: dict[str, Any],
        target_type: str | None,
        runtime_report: dict[str, Any] | None,
        project_root: Path | None = None,
        runtime_config: dict[str, Any] | None = None,
        bridge: Any = None,
        kind: str = "manual_io_test",
    ) -> None:
        self.root = project_root or get_project_root()
        self.config = runtime_config or plcsim_runtime.load_runtime_config(plcsim_runtime._load_tia_config(self.root))
        self.program = program
        self.target_type = target_type
        self.runtime_report = runtime_report or {}
        self._bridge = bridge or self._call_bridge
        self.kind = kind
        self.started_at = _now()
        self._started_perf = time.perf_counter()
        self.writes: list[dict[str, Any]] = []
        self.reads: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []
        self.cleanup: dict[str, Any] = {"performed": False, "success": None, "inputs": []}
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.touched_inputs: dict[str, dict[str, Any]] = {}
        self.status: str | None = None

    # -- bridge ------------------------------------------------------------------------------

    def _call_bridge(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        return plcsim_runtime.run_runtime_bridge(
            action, self.root, self.config, extra=payload, timeout_seconds=self.config["io_timeout_seconds"]
        )

    def _base_payload(self) -> dict[str, Any]:
        payload={"target_type": self.target_type, "settle_ms": self.config["io_settle_ms"]}
        if self.program.get('native_pid_identity'):
            payload['native_pid_identity']=self.program['native_pid_identity']
        return payload

    def _guard_write(self) -> None:
        blocked = check_write_allowed(self.target_type, self.runtime_report, self.config["instance_name"])
        if blocked:
            code = blocked[0]
            raise RuntimeIOError(ERROR_WRITE_NOT_ALLOWED if code != ERROR_CPU_NOT_RUN else ERROR_CPU_NOT_RUN, blocked[1])

    def _absorb(self, raw: dict[str, Any], expected_ok: str = "PLCSIM_IO_PASSED") -> dict[str, Any]:
        status = str(raw.get("status", ""))
        if status == "PLCSIM_RUNTIME_TIMEOUT":
            status = ERROR_IO_TIMEOUT
        self.writes.extend(raw.get("writes", []) or [])
        self.reads.extend(raw.get("reads", []) or [])
        self.observations.extend(raw.get("observations", []) or [])
        self.warnings.extend(str(item) for item in raw.get("warnings", []) or [])
        if raw.get("cpu_state"):
            self.runtime_report = {**self.runtime_report, "cpu_state": raw["cpu_state"]}
        cleanup = raw.get("cleanup")
        if isinstance(cleanup, dict) and cleanup.get("performed"):
            self.cleanup = {
                "performed": True,
                "success": bool(cleanup.get("success")),
                "inputs": list(cleanup.get("inputs", [])),
                "timestamp": cleanup.get("timestamp"),
            }
            if cleanup.get("success"):
                for entry in cleanup.get("inputs", []):
                    self.touched_inputs.pop(entry.get("name"), None)
        if status != expected_ok:
            self.errors.extend(str(item) for item in raw.get("errors", []) or [])
        return {**raw, "status": status}

    # -- operaciones -------------------------------------------------------------------------

    def write_input(self, name: str, value: bool) -> dict[str, Any]:
        """Escribe una ENTRADA BOOL con readback obligatorio (requested / actual / match)."""
        signal = resolve_signal(self.program, name, for_write=True)
        self._guard_write()
        payload = {**self._base_payload(), "signal": _bridge_signal(signal), "value": bool(value)}
        self.touched_inputs[name] = signal
        raw = self._absorb(self._bridge("write_input", payload))
        entry = next((item for item in reversed(raw.get("writes", []) or []) if item.get("name") == name), {})
        if raw["status"] == ERROR_IO_TIMEOUT:
            self.restore_inputs()
        if raw["status"] == "PLCSIM_IO_PASSED" and not value:
            self.touched_inputs.pop(name, None)
        return {
            "status": SUCCESS if raw["status"] == "PLCSIM_IO_PASSED" else raw["status"],
            "name": name,
            "address": signal["address"],
            "requested_value": bool(value),
            "readback": entry.get("actual_readback"),
            "readback_tag": entry.get("readback_tag"),
            "match": bool(entry.get("match")),
            "timestamp": entry.get("readback_timestamp") or _now(),
            "errors": list(raw.get("errors", []) or []),
        }

    def read_signals(self, names: list[str]) -> dict[str, Any]:
        """Lee entradas/salidas BOOL (por direccion, verificado por tag)."""
        signals = [resolve_signal(self.program, name, for_write=False) for name in names]
        raw = self._absorb(self._bridge("read_signal", {"signals": [_bridge_signal(s) for s in signals]}))
        values = {item.get("name"): item for item in raw.get("reads", []) or []}
        return {
            "status": SUCCESS if raw["status"] == "PLCSIM_IO_PASSED" else raw["status"],
            "values": [
                {
                    "name": signal["name"],
                    "address": signal["address"],
                    "value": values.get(signal["name"], {}).get("value"),
                    "source": "address",
                    "timestamp": values.get(signal["name"], {}).get("timestamp"),
                }
                for signal in signals
            ],
            "errors": list(raw.get("errors", []) or []),
        }

    def restore_inputs(self) -> dict[str, Any]:
        """Cleanup: toda entrada tocada vuelve a FALSE y se verifica. Un fallo nunca se oculta."""
        if not self.touched_inputs:
            return {"status": SUCCESS, "restored": []}
        signals = [_bridge_signal(signal) for signal in self.touched_inputs.values()]
        names = [signal["name"] for signal in signals]
        payload = {**self._base_payload(), "signals": signals}
        raw = self._bridge("restore_inputs", payload)
        raw = self._absorb(raw)
        if raw["status"] != "PLCSIM_IO_PASSED":
            self.cleanup = {**self.cleanup, "performed": True, "success": False}
            if not any(ERROR_CLEANUP_FAILED in error for error in self.errors):
                self.errors.append(f"{ERROR_CLEANUP_FAILED}: no se pudo restaurar {', '.join(names)} ({raw['status']}).")
            return {"status": ERROR_CLEANUP_FAILED, "restored": [], "pending": names}
        return {"status": SUCCESS, "restored": names}

    # -- reporte -----------------------------------------------------------------------------

    def build_report(self, status: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        final = status or self.status or (SUCCESS if not self.errors else FAIL)
        if self.cleanup.get("performed") and self.cleanup.get("success") is False:
            final = FAIL
        return {
            "kind": self.kind,
            "runtime_io_test": final,
            "instance": self.config["instance_name"],
            "target_type": self.target_type,
            "cpu_state": self.runtime_report.get("cpu_state"),
            "program_source": {
                "source": self.program.get("source"),
                "path": self.program.get("path"),
                "trial_id": self.program.get("trial_id"),
            },
            "input_bindings": bool_inputs(self.program),
            "output_bindings": bool_outputs(self.program),
            "settle_ms": self.config["io_settle_ms"],
            "writes": self.writes,
            "readbacks": [
                {key: item.get(key) for key in ("name", "address", "requested_value", "actual_readback", "readback_tag", "match", "readback_timestamp")}
                for item in self.writes
            ],
            "reads": self.reads,
            "observations": self.observations,
            "cleanup": self.cleanup,
            "pending_inputs_not_restored": sorted(self.touched_inputs),
            "warnings": self.warnings,
            "errors": self.errors,
            "started_at": self.started_at,
            "completed_at": _now(),
            "duration_ms": int(round((time.perf_counter() - self._started_perf) * 1000)),
            **(extra or {}),
        }


def write_io_report(directory: Path, report: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / REPORT_FILENAME
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------
# Smoke test tecnico (NUNCA automatico): Start/Stop con enclavamiento
# ---------------------------------------------------------------------------------------------

def _role_signal(program: dict[str, Any], keywords: tuple[str, ...], direction: str) -> str | None:
    candidates = {
        binding["functional_name"]
        for path, binding in program.get("parameter_bindings", {}).items()
        if any(keyword in path.lower() for keyword in keywords)
        and program["signals"].get(binding["functional_name"], {}).get("direction") == direction
    }
    if len(candidates) == 1:
        return next(iter(candidates))
    named = [s["name"] for s in program["signals"].values() if s["direction"] == direction and any(k in s["name"].lower() for k in keywords)]
    return named[0] if len(named) == 1 else None


def resolve_smoke_roles(program: dict[str, Any], start: str | None = None, stop: str | None = None, output: str | None = None) -> dict[str, str]:
    """start/stop/output desde los roles del snapshot (o nombres explicitos). Nunca direcciones fijas."""
    roles = {
        "start": start or _role_signal(program, ("start",), "I"),
        "stop": stop or _role_signal(program, ("stop",), "I"),
        "output": output or _role_signal(program, ("output", "motor"), "Q"),
    }
    if roles["output"] is None:
        outputs = bool_outputs(program)
        roles["output"] = outputs[0]["name"] if len(outputs) == 1 else None
    missing = [role for role, name in roles.items() if not name]
    if missing:
        raise RuntimeIOError(ERROR_SIGNAL_NOT_FOUND, "No se pudieron resolver los roles: " + ", ".join(missing))
    return roles  # type: ignore[return-value]


def smoke_test_steps(program: dict[str, Any], roles: dict[str, str]) -> list[dict[str, Any]]:
    """Pasos 1-12 de la seccion 13 (el 13, cleanup, lo hace el bridge en su finally)."""
    start = _bridge_signal(resolve_signal(program, roles["start"], for_write=True))
    stop = _bridge_signal(resolve_signal(program, roles["stop"], for_write=True))
    output = _bridge_signal(resolve_signal(program, roles["output"], for_write=False))
    return [
        {"op": "write", "signal": start, "value": False},   # 1
        {"op": "write", "signal": stop, "value": False},    # 2
        {"op": "write", "signal": start, "value": True},    # 3 + 4 (settle) + readback
        {"op": "read", "signal": start},                    # 5
        {"op": "read", "signal": output},                   # 6
        {"op": "write", "signal": start, "value": False},   # 7 + 8
        {"op": "read", "signal": output},                   # 9
        {"op": "write", "signal": stop, "value": True},     # 10 + 11
        {"op": "read", "signal": output},                   # 12
    ]


def run_runtime_io_smoke_test(
    program: dict[str, Any],
    target_type: str | None,
    runtime_report: dict[str, Any] | None,
    project_root: Path | None = None,
    report_dir: Path | None = None,
    roles: dict[str, str] | None = None,
    bridge: Any = None,
    runtime_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Prueba tecnica Start/Stop. Solo registra observaciones: runtime_io_test = SUCCESS si todas las
    escrituras, readbacks, lecturas y el cleanup funcionaron. NO evalua Functional Success.
    """
    session = RuntimeIOSession(
        program, target_type, runtime_report, project_root, runtime_config=runtime_config, bridge=bridge, kind="runtime_io_smoke_test"
    )
    resolved: dict[str, str] = {}
    try:
        resolved = roles or resolve_smoke_roles(program)
        steps = smoke_test_steps(program, resolved)
        session._guard_write()
        for step in steps:
            if step["op"] == "write":
                session.touched_inputs[step["signal"]["name"]] = program["signals"][step["signal"]["name"]]
        raw = session._absorb(session._bridge("io_sequence", {**session._base_payload(), "steps": steps}))
        session.status = SUCCESS if raw["status"] == "PLCSIM_IO_PASSED" else FAIL
        if raw["status"] == ERROR_IO_TIMEOUT:
            session.restore_inputs()
    except RuntimeIOError as error:
        session.errors.append(str(error))
        session.status = FAIL
    output_name = resolved.get("output")
    output_values = [item.get("value") for item in session.observations if item.get("name") == output_name]
    report = session.build_report(extra={
        "roles": resolved,
        "output_sequence": output_values,
        "functional_success": None,  # Fase 2B: nunca se evalua aqui
    })
    if report_dir is not None:
        report["report_path"] = str(write_io_report(Path(report_dir), report))
    return report


def trial_runtime_io_section(report: dict[str, Any]) -> dict[str, Any]:
    """Diagnostico de infraestructura para trial.json (NO es una metrica cientifica)."""
    writes_ok = any(item.get("match") and isinstance(item.get('requested_value'), bool)
                    for item in report.get("writes", []))
    reads_ok = any(isinstance(item.get("value"), bool) for item in report.get("reads", []))
    return {
        "bool_input_write_supported": writes_ok,
        "bool_read_supported": reads_ok,
        "last_test_kind": report.get("kind"),
        "last_test_status": report.get("runtime_io_test"),
        "last_test_report": report.get("report_path"),
        "last_test_at": report.get("completed_at"),
    }
