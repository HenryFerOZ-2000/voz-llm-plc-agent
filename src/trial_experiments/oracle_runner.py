"""
Oracle Runner (Fase 3A, piloto D03/D07/D12).

Evalua el COMPORTAMIENTO del programa descargado en PLCSIM contra un Oracle aprobado:

  Oracle role -> parameter_bindings del io_map_snapshot.json del ensayo -> functional_name ->
  direccion fisica -> PLCSIM Runtime (bridge io_sequence, una unica llamada).

No re-ejecuta el IOAllocator, no toca mapas, no modifica el programa. El bridge solo escribe
entradas (InputArea.WriteBit) y mide todos los tiempos con un reloj monotono propio.

Separacion de resultados:
  - functional_success: expectativas de test_sequence (incluidas ventanas temporales);
  - safety_success: invariantes CRITICAL en TODAS las muestras;
  - verdict: PASS / FAIL / REVIEW / INFRASTRUCTURE_ERROR con precedencia
      INFRASTRUCTURE_ERROR > FAIL por seguridad > REVIEW > FAIL funcional > PASS.
    REVIEW nunca se convierte en FAIL: significa que el evaluador no puede decidir.

Tres dimensiones separadas (ninguna oculta a otra):
  - semantic_benchmark_match: la semantica coincide con la expectativa del Oracle (intent aceptado,
    no prohibido, roles, requisitos y parametros INTERPRETADOS; un default trazado nunca cuenta);
  - functional_success / safety_success: comportamiento medido en PLCSIM.
Un intent distinto NO impide la prueba funcional: si los roles se resuelven desde los bindings
congelados, la secuencia se ejecuta y functional/safety se miden igual. Solo roles no resolubles
(ausentes, ambiguos, tipo incorrecto) dejan el resultado en REVIEW sin ejecutar el Runtime.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import plcsim_runtime
import plcsim_runtime_io as rio
from effective_semantics import interpreted_parameters
from trial_experiments import oracle_schema, trial_model
from trial_experiments import process_variables as PV

VERDICT_PASS = trial_model.FINAL_STATUS_PASS
VERDICT_FAIL = trial_model.FINAL_STATUS_FAIL
VERDICT_REVIEW = trial_model.FINAL_STATUS_REVIEW
VERDICT_INFRA = trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR

TRIAL_KIND_FORMAL = "FORMAL_TRIAL"
TRIAL_KIND_DEVELOPMENT = "DEVELOPMENT_TRIAL"

ROLE_NOT_FOUND = "ORACLE_ROLE_NOT_FOUND"
ROLE_AMBIGUOUS = "ORACLE_ROLE_AMBIGUOUS"
ROLE_KIND_MISMATCH = "ORACLE_ROLE_KIND_MISMATCH"
ROLE_CONFLICT = "ORACLE_ROLE_CONFLICT"
PRECONDITION_FAILED = "ORACLE_PRECONDITION_FAILED"
RUNTIME_NOT_READY = "ORACLE_RUNTIME_NOT_READY"
SNAPSHOT_MISSING = "ORACLE_SNAPSHOT_MISSING"
SEMANTIC_MISMATCH = "ORACLE_SEMANTIC_MISMATCH"
SEMANTIC_NOT_EVALUABLE = "ORACLE_SEMANTIC_NOT_EVALUABLE"
NO_SAMPLES = "ORACLE_NO_SAMPLES_IN_WINDOW"
RUNTIME_EXTENSION_REQUIRED = "ORACLE_RUNTIME_EXTENSION_REQUIRED"
ROLE_BINDING_UNSUPPORTED = "ORACLE_ROLE_BINDING_UNSUPPORTED"
SEQUENCE_VALUE_TYPE_MISMATCH = "ORACLE_SEQUENCE_VALUE_TYPE_MISMATCH"
# Proposito que el bridge exige para escribir variables internas (Program.InternalWritePurpose).
PROCESS_VARIABLE_WRITE_PURPOSE = "EXPERIMENT_ORACLE"
# Readback de una escritura REAL (float32 en PLCSIM): muy por debajo de las tolerancias del Oracle (0.01).
REAL_WRITE_TOLERANCE = 0.001


# El programa bajo prueba reescribe una variable de proceso que el Oracle controla como ENTRADA (estimulo del
# arnes). La escritura de la infraestructura SI se completo (la API no fallo): es un fallo del DUT, nunca
# INFRASTRUCTURE_ERROR ni REVIEW -> Functional FAIL.
PROGRAM_OVERWRITES_HARNESS_INPUT = "PROGRAM_OVERWRITES_HARNESS_INPUT"


class OracleSequenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def runtime_capability_check(oracle: dict[str, Any], capabilities: tuple[str, ...] | list[str] | None = None) -> dict[str, Any]:
    """
    Ejecucion por capacidades. required = runtime_requirements declarados en el Oracle (congelado) +
    los derivados de sus roles; missing = los que el Runtime actual no soporta. runtime_support del
    Oracle se conserva tal cual como dato (nunca se modifica ni decide por si solo).
    """
    available = list(capabilities if capabilities is not None else rio.RUNTIME_CAPABILITIES)
    wanted = set(oracle.get("runtime_requirements") or []) | set(oracle_schema.derived_runtime_requirements(oracle))
    required = [item for item in oracle_schema.RUNTIME_REQUIREMENTS if item in wanted] + sorted(
        item for item in wanted if item not in oracle_schema.RUNTIME_REQUIREMENTS)
    missing = [item for item in required if item not in available]
    return {
        "declared_runtime_support": oracle_schema.runtime_support(oracle),
        "runtime_capabilities": available,
        "required_capabilities": required,
        "missing_capabilities": missing,
        "executable": not missing,
    }
SKIPPED_OPTIONAL = "OPTIONAL_ROLE_NOT_BOUND"

EVALUATION_REPORT_FILENAME = "evaluation_report.json"
ORACLE_TRACE_FILENAME = "oracle_trace.json"

_KIND_TO_SIGNAL = {"INPUT": "DI", "OUTPUT": "DO"}
_SEQUENCE_MARGIN_S = 30


# ---------------------------------------------------------------------------------------------
# Role resolver
# ---------------------------------------------------------------------------------------------

def _last_segment(path: str) -> str:
    return re.sub(r"\[\d+\]", "", str(path)).split(".")[-1]


def _path_matches(path: str, semantic_paths: list[str]) -> bool:
    return path in semantic_paths or _last_segment(path) in semantic_paths


def _resolve_process_variable_role(role_name: str, role: dict[str, Any], bindings: dict[str, dict[str, Any]],
                                   resolved: dict[str, dict[str, Any]], issues: list[dict[str, Any]]) -> None:
    """
    Rol PROCESS_VARIABLE: SOLO contra process_variable_bindings congelados (nunca program.scl ni un nombre
    adivinado). Candidatos = process_variables del rol presentes en los bindings. 0 -> NOT_FOUND,
    >1 -> AMBIGUOUS, tipo distinto -> KIND_MISMATCH.
    """
    candidates = [name for name in role.get("process_variables") or [] if name in bindings]
    expected_type = oracle_schema.role_data_type(role)
    matching = [name for name in candidates if bindings[name].get("data_type") == expected_type]
    if len(matching) == 1:
        binding = bindings[matching[0]]
        signal = PV.runtime_signal(binding)
        resolved[role_name] = {
            "role": role_name,
            "kind": role["kind"],
            "binding": PV.BINDING_PROCESS_VARIABLE,
            # Nombre logico (db.member): clave de las muestras y de las escrituras en la traza del bridge.
            "functional_name": signal["name"],
            "process_variable": binding["name"],
            "db": binding["db"],
            "member": binding["member"],
            "data_type": binding["data_type"],
            "address": None,
            # Solo los roles INPUT con binding PROCESS_VARIABLE son escribibles (test harness del Oracle).
            "writable": role["kind"] == "INPUT",
            "binding_source": binding.get("source"),
            "matched_paths": [binding["name"]],
        }
    elif len(matching) > 1:
        issues.append({"code": ROLE_AMBIGUOUS, "role": role_name, "candidates": sorted(matching),
                       "detail": f"{role_name}: varias variables de proceso {sorted(matching)} para {role.get('process_variables')}."})
    elif candidates:
        issues.append({"code": ROLE_KIND_MISMATCH, "role": role_name, "candidates": sorted(candidates),
                       "detail": f"{role_name} ({expected_type}) solo encontro variables de otro tipo: "
                                 f"{ {name: bindings[name].get('data_type') for name in candidates} }."})
    elif role.get("required", True):
        issues.append({"code": ROLE_NOT_FOUND, "role": role_name, "candidates": [],
                       "detail": f"{role_name}: ninguna variable de {role.get('process_variables')} esta en los "
                                 "process_variable_bindings congelados del ensayo."})


def resolve_roles(oracle: dict[str, Any], snapshot: dict[str, Any],
                  process_variable_bindings: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Resuelve cada rol del Oracle contra los bindings CONGELADOS del ensayo. Nunca adivina:
    0 candidatos -> NOT_FOUND, >1 -> AMBIGUOUS, tipo equivocado -> KIND_MISMATCH, dos roles en la
    misma senal -> CONFLICT. Cualquier incidencia deja el resultado en REVIEW.
    Roles IO -> parameter_bindings del snapshot; roles PROCESS_VARIABLE -> process_variable_bindings.
    """
    signal_by_name = {c.get("functional_name"): c.get("signal") for c in snapshot.get("channels", []) or []}
    address_by_name = {c.get("functional_name"): c.get("address") for c in snapshot.get("channels", []) or []}
    parameter_bindings = snapshot.get("parameter_bindings") or {}
    pv_bindings = (process_variable_bindings or {}).get("bindings") or {}
    resolved: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []

    for role_name, role in oracle["roles"].items():
        if oracle_schema.role_binding(role) == PV.BINDING_PROCESS_VARIABLE:
            _resolve_process_variable_role(role_name, role, pv_bindings, resolved, issues)
            continue
        if oracle_schema.role_binding(role) != "IO":
            # Variables internas del contrato PID: requieren lectura/escritura de tags internos
            # (extension del Runtime). No se resuelven contra los bindings fisicos del ensayo.
            if role.get("required", True):
                issues.append({"code": ROLE_BINDING_UNSUPPORTED, "role": role_name, "candidates": [],
                               "detail": f"{role_name}: binding {oracle_schema.role_binding(role)} no soportado por el Runtime actual."})
            continue
        candidates: dict[str, list[str]] = {}
        for path, binding in parameter_bindings.items():
            if _path_matches(path, role["semantic_paths"]):
                candidates.setdefault(binding.get("functional_name"), []).append(path)
        expected_signal = _KIND_TO_SIGNAL[role["kind"]]
        matching = {name: paths for name, paths in candidates.items() if signal_by_name.get(name) == expected_signal}
        wrong_kind = {name: paths for name, paths in candidates.items() if name not in matching}
        if len(matching) == 1:
            name, paths = next(iter(matching.items()))
            resolved[role_name] = {
                "role": role_name,
                "kind": role["kind"],
                "functional_name": name,
                "address": address_by_name.get(name),
                "matched_paths": sorted(paths),
            }
            continue
        if len(matching) > 1:
            issues.append({"code": ROLE_AMBIGUOUS, "role": role_name, "candidates": sorted(matching),
                           "detail": f"{role_name}: varios candidatos {sorted(matching)} para {role['semantic_paths']}."})
        elif wrong_kind:
            issues.append({"code": ROLE_KIND_MISMATCH, "role": role_name, "candidates": sorted(wrong_kind),
                           "detail": f"{role_name} ({role['kind']}) solo encontro senales de otro tipo: {sorted(wrong_kind)}."})
        elif role.get("required", True):
            issues.append({"code": ROLE_NOT_FOUND, "role": role_name, "candidates": [],
                           "detail": f"{role_name}: ninguna ruta de {role['semantic_paths']} aparece en los bindings del ensayo."})

    by_name: dict[str, list[str]] = {}
    for role_name, entry in resolved.items():
        by_name.setdefault(entry["functional_name"], []).append(role_name)
    for name, roles in by_name.items():
        if len(roles) > 1:
            issues.append({"code": ROLE_CONFLICT, "role": ",".join(sorted(roles)), "candidates": [name],
                           "detail": f"Los roles {sorted(roles)} resuelven a la misma senal {name}."})
    return {"status": "RESOLVED" if not issues else "REVIEW", "roles": resolved, "issues": issues}


# ---------------------------------------------------------------------------------------------
# Semantica
# ---------------------------------------------------------------------------------------------

_IEC_DURATION = re.compile(r"^(?:T|TIME)#(.+)$", re.IGNORECASE)
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s|d)", re.IGNORECASE)
_UNIT_MS = {"ms": 1, "s": 1000, "m": 60000, "h": 3600000, "d": 86400000}


def parse_duration_ms(value: Any) -> int | None:
    """'T#3s', 'T#3000MS', 'T#1m30s', '3s', '2500ms' -> milisegundos. Numeros sin unidad -> None
    (no se adivina si son segundos o milisegundos)."""
    if not isinstance(value, str):
        return None
    text = value.strip().replace("_", "")
    match = _IEC_DURATION.match(text)
    body = (match.group(1) if match else text).lower()
    parts = _DURATION_PART.findall(body)
    if not parts or "".join(number + unit for number, unit in parts) != body:
        return None
    return int(round(sum(float(number) * _UNIT_MS[unit.lower()] for number, unit in parts)))


def evaluate_semantics(oracle: dict[str, Any], semantic_output: dict[str, Any] | None, role_resolution: dict[str, Any]) -> dict[str, Any]:
    expectations = oracle.get("semantic_expectations") or {}
    if not semantic_output:
        return {"evaluable": False, "success": None, "checks": [], "warnings": ["Sin semantic_output del ensayo."]}
    intent = semantic_output.get("intent_id")
    # Solo lo que la interpretacion expreso (LLM/reglas/repair): los recursos completados por la
    # semantica efectiva (DEFAULT) no son evidencia semantica del comando.
    parameters = interpreted_parameters(semantic_output)
    provenance = semantic_output.get("parameter_provenance") or {}
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []

    accepted = expectations.get("accepted_intents") or []
    if accepted:
        checks.append({"check": "intent_accepted", "expected": accepted, "actual": intent, "passed": intent in accepted})
    forbidden = expectations.get("forbidden_intents") or []
    if forbidden:
        checks.append({"check": "intent_not_forbidden", "expected": f"no {forbidden}", "actual": intent, "passed": intent not in forbidden})
    for role in expectations.get("required_roles") or []:
        entry = role_resolution["roles"].get(role) or {}
        sources = sorted({(provenance.get(_root_key(path)) or {}).get("source") or "PARSER" for path in entry.get("matched_paths") or []})
        checks.append({"check": f"role:{role}", "expected": "resuelto", "actual": entry.get("functional_name"),
                       "passed": role in role_resolution["roles"], "provenance": sources})
        if entry and sources and all(source == "DEFAULT" for source in sources):
            warnings.append(f"Rol {role} resuelto por un recurso completado por la semantica efectiva (DEFAULT, trazado).")
    present_types = {str(r.get("type")) for r in semantic_output.get("functional_requirements") or [] if isinstance(r, dict)}
    for requirement in expectations.get("required_functional_requirements") or []:
        checks.append({"check": f"functional_requirement:{requirement}", "expected": requirement,
                       "actual": sorted(present_types), "passed": requirement in present_types})
    for key, spec in (expectations.get("required_parameters") or {}).items():
        raw = parameters.get(key)
        if raw is None:
            if spec.get("if_missing") == "NOT_EVALUABLE":
                warnings.append(f"Parametro {key} no explicitado por el LLM: no evaluable (se verifica funcionalmente).")
                checks.append({"check": f"parameter:{key}", "expected": spec, "actual": None, "passed": None})
                continue
            checks.append({"check": f"parameter:{key}", "expected": spec, "actual": None, "passed": False})
            continue
        if spec.get("type") == "DURATION":
            actual_ms = parse_duration_ms(raw)
            if actual_ms is None:
                warnings.append(f"Parametro {key}={raw!r} no interpretable como duracion: no evaluable.")
                checks.append({"check": f"parameter:{key}", "expected": spec, "actual": raw, "passed": None})
            else:
                ok = abs(actual_ms - int(spec["value_ms"])) <= int(spec.get("tolerance_ms", 0))
                checks.append({"check": f"parameter:{key}", "expected": spec["value_ms"], "actual": actual_ms, "passed": ok})
        elif spec.get("type") == "INTEGER":
            try:
                actual_int = int(str(raw).strip())
            except ValueError:
                actual_int = None
            if actual_int is None:
                warnings.append(f"Parametro {key}={raw!r} no interpretable como entero: no evaluable.")
                checks.append({"check": f"parameter:{key}", "expected": spec, "actual": raw, "passed": None})
            else:
                checks.append({"check": f"parameter:{key}", "expected": spec["value"], "actual": actual_int,
                               "passed": actual_int == int(spec["value"])})
        else:
            checks.append({"check": f"parameter:{key}", "expected": spec.get("value"), "actual": raw, "passed": raw == spec.get("value")})
    evaluable = [check for check in checks if check["passed"] is not None]
    intent_check = next((check for check in checks if check["check"] == "intent_accepted"), None)
    return {
        "evaluable": bool(evaluable),
        "success": all(check["passed"] for check in evaluable) if evaluable else None,
        "intent_id": intent,
        "intent_expected": accepted,
        "intent_match": intent_check["passed"] if intent_check else None,
        "failed_checks": [check["check"] for check in evaluable if not check["passed"]],
        "checks": checks,
        "warnings": warnings,
    }


def _root_key(path: str) -> str:
    return re.split(r"[.\[]", str(path))[0]


def evaluate_resources(oracle: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    expectations = oracle.get("resource_expectations") or {}
    bindings = snapshot.get("bindings") or []
    inputs = [b["functional_name"] for b in bindings if b.get("signal") in ("DI", "AI")]
    outputs = [b["functional_name"] for b in bindings if b.get("signal") in ("DO", "AO")]
    warnings = []
    if expectations.get("expected_bound_inputs") is not None and len(inputs) > expectations["expected_bound_inputs"]:
        warnings.append(f"Entradas ligadas {inputs} superan las esperadas ({expectations['expected_bound_inputs']}).")
    if expectations.get("expected_bound_outputs") is not None and len(outputs) > expectations["expected_bound_outputs"]:
        warnings.append(f"Salidas ligadas {outputs} superan las esperadas ({expectations['expected_bound_outputs']}).")
    return {"policy": expectations.get("policy", "ADVISORY"), "bound_inputs": inputs, "bound_outputs": outputs, "warnings": warnings}


# ---------------------------------------------------------------------------------------------
# Secuencia -> io_sequence (una sola llamada al bridge)
# ---------------------------------------------------------------------------------------------

def _bridge_signal(program: dict[str, Any], name: str) -> dict[str, Any]:
    signal = program["signals"][name]
    return {key: signal[key] for key in ("name", "address", "area", "offset", "bit", "data_type")}


def _cleanup_restore_values(oracle: dict[str, Any]) -> dict[str, Any]:
    """Valor de restauracion de cada rol = el ULTIMO que fija el cleanup del Oracle (nunca FALSE/0 por defecto)."""
    restore: dict[str, Any] = {}
    for step in oracle.get("cleanup") or []:
        restore.update(step.get("set") or {})
    return restore


def _role_signal(entry: dict[str, Any], program: dict[str, Any], pv_bindings: dict[str, dict[str, Any]],
                 restore: dict[str, Any]) -> dict[str, Any]:
    if entry.get("binding") == PV.BINDING_PROCESS_VARIABLE:
        binding = pv_bindings[entry["process_variable"]]
        return PV.runtime_signal(binding, writable=entry.get("writable", False),
                                 restore_value=restore.get(entry["role"]) if entry.get("writable") else None)
    return _bridge_signal(program, entry["functional_name"])


def _check_value_type(role: str, entry: dict[str, Any], signal: dict[str, Any], value: Any, step_id: str) -> None:
    data_type = str(entry.get("data_type") or signal.get("data_type") or "BOOL").upper()
    ok = isinstance(value, bool) if data_type == "BOOL" else (isinstance(value, (int, float)) and not isinstance(value, bool))
    if not ok:
        raise OracleSequenceError(SEQUENCE_VALUE_TYPE_MISMATCH, f"{step_id}: {role} es {data_type} y el Oracle fija {value!r}.")
    if entry.get("binding") == PV.BINDING_PROCESS_VARIABLE and not entry.get("writable"):
        raise OracleSequenceError(rio.ERROR_WRITE_NOT_ALLOWED, f"{step_id}: {role} es una variable de SALIDA; solo se leen.")


def compile_sequence(oracle: dict[str, Any], roles: dict[str, dict[str, Any]], program: dict[str, Any],
                     process_variable_bindings: dict[str, Any] | None = None) -> dict[str, Any]:
    period = int((oracle.get("evaluation") or {}).get("sample_period_ms", 50))
    pv_bindings = (process_variable_bindings or {}).get("bindings") or {}
    restore = _cleanup_restore_values(oracle)
    signals = {role: _role_signal(entry, program, pv_bindings, restore) for role, entry in roles.items()}
    watched = list(signals.values())
    steps: list[dict[str, Any]] = []
    planned_ms = 0
    skipped: list[str] = []
    for phase, section in (("precondition", "preconditions"), ("test", "test_sequence"), ("cleanup", "cleanup")):
        for step in oracle.get(section) or []:
            if any(role not in roles for role in step.get("requires_roles") or []):
                skipped.append(step["id"])
                continue
            if step.get("set"):
                for role, value in step["set"].items():
                    _check_value_type(role, roles[role], signals[role], value, step["id"])
                steps.append({
                    "op": "set", "id": step["id"], "phase": phase,
                    "writes": [{"signal": signals[role], "value": value} for role, value in step["set"].items()],
                })
            wait_ms = int(step.get("wait_ms", 0))
            sample: dict[str, Any] = {
                "op": "sample", "id": step["id"], "phase": phase, "duration_ms": wait_ms,
                "period_ms": period, "signals": watched,
            }
            if phase == "precondition" and step.get("expect"):
                sample["require"] = {roles[role]["functional_name"]: value for role, value in step["expect"].items()}
            steps.append(sample)
            planned_ms += wait_ms
    return {"steps": steps, "planned_ms": planned_ms, "sample_period_ms": period, "watched": [s["name"] for s in watched],
            "skipped_steps": skipped,
            "process_variables": any(s.get("kind") == PV.BINDING_PROCESS_VARIABLE for s in watched)}


# ---------------------------------------------------------------------------------------------
# Evaluacion funcional y de seguridad (pura, sobre la traza del bridge)
# ---------------------------------------------------------------------------------------------

def _wall_clock(event: dict[str, Any] | None, t_ms: float | None) -> str | None:
    if not event or t_ms is None or not event.get("timestamp"):
        return None
    try:
        base = datetime.fromisoformat(str(event["timestamp"])[:26])
    except ValueError:
        return None
    return (base + timedelta(milliseconds=float(t_ms) - float(event.get("t_ms", 0.0)))).isoformat(timespec="milliseconds")


def value_matches(expected: Any, actual: Any) -> bool:
    """BOOL: igualdad. Numerico: exacto (1e-6), {approx, tolerance} o {min, max}."""
    if actual is None:
        return False
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(expected, bool) and actual is expected
    if isinstance(expected, dict):
        if "approx" in expected:
            return abs(float(actual) - float(expected["approx"])) <= float(expected.get("tolerance", 0.0))
        return float(expected.get("min", float("-inf"))) <= float(actual) <= float(expected.get("max", float("inf")))
    return abs(float(actual) - float(expected)) <= 1e-6


def _role_values(values: dict[str, Any], roles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {role: values.get(entry["functional_name"]) for role, entry in roles.items()}


def evaluate_trace(oracle: dict[str, Any], roles: dict[str, dict[str, Any]], raw: dict[str, Any]) -> dict[str, Any]:
    events = {event.get("id"): event for event in raw.get("events", []) or [] if event.get("type") == "set"}
    samples_by_step: dict[str, list[dict[str, Any]]] = {}
    for sample in raw.get("samples", []) or []:
        samples_by_step.setdefault(sample.get("id"), []).append(sample)
    steps_out: list[dict[str, Any]] = []
    precondition_checks: list[dict[str, Any]] = []
    functional_checks: list[dict[str, Any]] = []
    executed_ids = set(samples_by_step) | set(events)

    for phase, section in (("precondition", "preconditions"), ("test", "test_sequence"), ("cleanup", "cleanup")):
        for step in oracle.get(section) or []:
            step_id = step["id"]
            event = events.get(step_id)
            samples = samples_by_step.get(step_id, [])
            if any(role not in roles for role in step.get("requires_roles") or []):
                steps_out.append({"step_id": step_id, "phase": phase, "executed": False, "skipped": SKIPPED_OPTIONAL,
                                  "passed": None, "checks": [], "errors": []})
                continue
            if step_id not in executed_ids:
                steps_out.append({"step_id": step_id, "phase": phase, "executed": False, "passed": None, "checks": [], "errors": []})
                continue
            reference = events.get(step.get("time_reference")) if step.get("time_reference") else None
            own_t0 = event["t_done_ms"] if event else (samples[0]["t_ms"] if samples else 0.0)
            t0 = reference["t_done_ms"] if reference else own_t0
            last = samples[-1] if samples else None
            checks: list[dict[str, Any]] = []
            errors: list[str] = []
            for role, expected in (step.get("expect") or {}).items():
                actual = last["values"].get(roles[role]["functional_name"]) if last else None
                checks.append({
                    "type": "expect", "step_id": step_id, "role": role, "expected": expected, "actual": actual,
                    "t_ms": round(last["t_ms"] - t0, 1) if last else None, "passed": value_matches(expected, actual),
                })
            for window in step.get("expect_timeline") or []:
                inside = [s for s in samples if window["from_ms"] <= s["t_ms"] - t0 <= window["to_ms"]]
                for role, expected in window["expect"].items():
                    name = roles[role]["functional_name"]
                    violations = [s for s in inside if not value_matches(expected, s["values"].get(name))]
                    passed = bool(inside) and not violations
                    check = {
                        "type": "timeline", "step_id": step_id, "role": role, "expected": expected,
                        "expected_time": {"from_ms": window["from_ms"], "to_ms": window["to_ms"]},
                        "samples_in_window": len(inside), "passed": passed,
                        "actual_observation_time": round(violations[0]["t_ms"] - t0, 1) if violations else (
                            round(inside[-1]["t_ms"] - t0, 1) if inside else None),
                        "actual": violations[0]["values"].get(name) if violations else (expected if inside else None),
                    }
                    if not inside:
                        check["error"] = NO_SAMPLES
                        errors.append(f"{NO_SAMPLES}: {step_id} [{window['from_ms']}, {window['to_ms']}] ms")
                    checks.append(check)
            transition = step.get("measure_transition")
            if transition:
                name = roles[transition["role"]]["functional_name"]
                # Transicion = FLANCO: primera muestra con el valor `to` DESPUES de haber observado el
                # valor opuesto (desde t0). Si la senal ya estaba en `to` al empezar, eso no es una
                # transicion (evita medir ~0 ms cuando la salida tarda un ciclo en reaccionar).
                first, seen_opposite = None, False
                for candidate in (s for s in samples if s["t_ms"] >= t0):
                    if value_matches(transition["to"], candidate["values"].get(name)):
                        if seen_opposite:
                            first = candidate
                            break
                    else:
                        seen_opposite = True
                measured = round(first["t_ms"] - t0, 1) if first else None
                low = transition["nominal_ms"] - transition["tolerance_ms"]["early"]
                high = transition["nominal_ms"] + transition["tolerance_ms"]["late"]
                checks.append({
                    "type": "transition", "step_id": step_id, "role": transition["role"], "expected": transition["to"],
                    "expected_time": {"nominal_ms": transition["nominal_ms"], "from_ms": low, "to_ms": high},
                    "actual_observation_time": measured, "tolerance": transition["tolerance_ms"],
                    "passed": measured is not None and low <= measured <= high,
                    "sample_period_ms": raw.get("sample_period_ms"),
                })
            inputs_applied = {
                role: next((w for w in (event or {}).get("writes", []) if w.get("name") == roles[role]["functional_name"]), None)
                for role in (step.get("set") or {})
            }
            evaluated = [check for check in checks if check.get("passed") is not None]
            step_result = {
                "step_id": step_id,
                "phase": phase,
                "executed": True,
                "description": step.get("description"),
                "started_at": (event or {}).get("timestamp"),
                "completed_at": _wall_clock(event, last["t_ms"]) if last else None,
                "t_start_ms": round(t0, 1),
                "t_end_ms": round(last["t_ms"], 1) if last else None,
                "inputs_applied": inputs_applied,
                "expected_outputs": dict(step.get("expect") or {}),
                "actual_outputs": _role_values(last["values"], roles) if last else {},
                "unspecified": list(step.get("unspecified") or []),
                "checks": checks,
                "passed": all(check["passed"] for check in evaluated) if evaluated else None,
                "errors": errors,
                "samples": len(samples),
            }
            steps_out.append(step_result)
            if phase == "precondition":
                precondition_checks.extend(checks)
            elif phase == "test":
                functional_checks.extend(checks)

    passed_checks = sum(1 for check in functional_checks if check["passed"])
    total_checks = len(functional_checks)
    test_steps = [s for s in steps_out if s["phase"] == "test" and not s.get("skipped")]
    all_test_executed = bool(test_steps) and all(s["executed"] for s in test_steps)
    functional = {
        "evaluated": all_test_executed and total_checks > 0,
        "success": (passed_checks == total_checks) if (all_test_executed and total_checks > 0) else None,
        "passed_checks": passed_checks,
        "total_checks": total_checks,
        "pass_rate": round(passed_checks / total_checks, 4) if total_checks else None,
        "failed_checks": [check for check in functional_checks if not check["passed"]],
    }
    safety = evaluate_invariants(oracle, roles, raw)
    major = [v for v in safety["violations"] if v["severity"] == "MAJOR"]
    functional["major_invariant_violations"] = len(major)
    if major and functional["success"] is True:
        functional["success"] = False
        functional["failed_checks"] = functional["failed_checks"] + [
            {"type": "invariant", "invariant_id": major[0]["invariant_id"], "step_id": major[0]["step_id"],
             "t_ms": major[0]["t_ms"], "values": major[0]["values"], "passed": False}]
    return {
        "steps": steps_out,
        "preconditions": {
            "success": all(check["passed"] for check in precondition_checks) if precondition_checks else True,
            "checks": precondition_checks,
        },
        "functional": functional,
        "safety": safety,
    }


def _harness_value_holds(written: Any, observed: Any, data_type: str) -> bool:
    if observed is None:
        return True  # sin observacion de esa senal no hay evidencia de sobrescritura
    if str(data_type).upper() == "REAL":
        return isinstance(observed, (int, float)) and not isinstance(observed, bool) and abs(float(observed) - float(written)) <= REAL_WRITE_TOLERANCE
    return observed is written


def detect_harness_input_overwrites(roles: dict[str, dict[str, Any]], raw: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Sobrescrituras de ESTIMULOS del arnes (roles INPUT PROCESS_VARIABLE escribibles) por el programa bajo prueba.
    Dos fuentes de evidencia, ambas con escritura de API completada (write_call_success):
      - el bridge: readback distinto confirmado tras io_settle_ms (classification PROGRAM_OVERWRITES_HARNESS_INPUT);
      - la traza: tras escribir v, una muestra posterior (antes de la siguiente escritura de esa variable)
        observa otro valor -> el PLC lo cambio en un ciclo posterior al readback inmediato.
    Una entrada por (variable, paso de escritura): la primera observacion discrepante. Solo para variables
    internas: las E/S fisicas siguen la politica de infraestructura del bridge.
    """
    writable = {entry["functional_name"]: (role, entry) for role, entry in roles.items()
                if entry.get("binding") == PV.BINDING_PROCESS_VARIABLE and entry.get("writable")}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for item in raw.get("harness_input_overwrites") or []:
        name = item.get("name")
        if name not in writable:
            continue
        role, entry = writable[name]
        found[(name, str(item.get("step_id")))] = {
            "role": role, "variable": entry.get("process_variable"), "name": name, "runtime_name": item.get("runtime_name"),
            "data_type": entry.get("data_type"), "written_value": item.get("requested_value"),
            "observed_value": item.get("observed_after_cycle"), "initial_readback": item.get("initial_readback"),
            "step_id": item.get("step_id"), "write_timestamp": item.get("write_timestamp"),
            "read_timestamp": item.get("observed_after_cycle_timestamp"), "evidence": "BRIDGE_READBACK_AFTER_CYCLE",
            "observed_equals_original": item.get("observed_equals_original"),
        }
    timeline: list[tuple[float, int, dict[str, Any]]] = []
    for event in raw.get("events", []) or []:
        if event.get("type") == "set":
            timeline.append((float(event.get("t_done_ms", event.get("t_ms", 0.0))), 0, event))
    for sample in raw.get("samples", []) or []:
        timeline.append((float(sample.get("t_ms", 0.0)), 1, sample))
    timeline.sort(key=lambda item: (item[0], item[1]))
    current: dict[str, tuple[Any, dict[str, Any], dict[str, Any]]] = {}
    for t_ms, kind, item in timeline:
        if kind == 0:
            for write in item.get("writes", []) or []:
                if write.get("name") in writable:
                    current[write["name"]] = (write.get("requested_value"), item, write)
            continue
        for name, (value, event, write) in current.items():
            key = (name, str(event.get("id")))
            if key in found:
                continue
            role, entry = writable[name]
            observed = (item.get("values") or {}).get(name)
            if not _harness_value_holds(value, observed, entry.get("data_type") or "BOOL"):
                found[key] = {
                    "role": role, "variable": entry.get("process_variable"), "name": name,
                    "runtime_name": write.get("runtime_name"), "data_type": entry.get("data_type"),
                    "written_value": value, "observed_value": observed, "initial_readback": write.get("initial_readback"),
                    "step_id": event.get("id"), "write_timestamp": write.get("write_timestamp") or event.get("timestamp"),
                    "read_timestamp": _wall_clock(event, t_ms), "write_t_ms": event.get("t_done_ms"), "read_t_ms": round(t_ms, 1),
                    "sample_step_id": item.get("id"), "evidence": "TRACE_SAMPLE_AFTER_WRITE",
                }
    return list(found.values())


def evaluate_invariants(oracle: dict[str, Any], roles: dict[str, dict[str, Any]], raw: dict[str, Any]) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    samples = raw.get("samples", []) or []
    invariants = oracle.get("invariants") or []
    set_times = [event["t_done_ms"] for event in raw.get("events", []) or [] if event.get("type") == "set"]
    for invariant in invariants:
        names = {role: roles[role]["functional_name"] for role in invariant.get("roles", []) if role in roles}
        if len(names) != len(invariant.get("roles", [])):
            continue  # rol opcional no ligado: la invariante no aplica a este programa
        when = invariant.get("when") or {}
        when_name = roles[when["role"]]["functional_name"] if when.get("role") in roles else None
        if invariant["type"] == "FORBIDDEN_WHEN" and when_name is None:
            continue
        grace = float(invariant.get("grace_ms", 0))
        for sample in samples:
            # grace_ms: tolerancia de propagacion tras cambiar entradas (un ciclo de PLC), para no
            # confundir la latencia entrada->salida con una violacion.
            if grace and any(0 <= sample["t_ms"] - t <= grace for t in set_times):
                continue
            values = {role: sample["values"].get(name) for role, name in names.items()}
            kind = invariant["type"]
            ordered = [values[role] for role in invariant.get("roles", [])]
            violated = (
                (kind == "NEVER_TRUE_TOGETHER" and all(value is True for value in values.values()))
                or (kind == "NEVER_TRUE" and any(value is True for value in values.values()))
                or (kind == "ALWAYS_EQUAL" and len(set(values.values())) > 1)
                or (kind == "IMPLIES" and ordered[0] is True and ordered[1] is not True)
                or (kind == "IN_RANGE" and ordered[0] is not None
                    and not (float(invariant["min"]) <= float(ordered[0]) <= float(invariant["max"])))
                or (kind == "AT_MOST_ONE" and sum(1 for value in ordered if value is True) > 1)
                or (kind == "EXACTLY_ONE" and sum(1 for value in ordered if value is True) != 1)
                or (kind == "FORBIDDEN_WHEN" and _condition_holds(when, sample["values"].get(when_name))
                    and any(value is True for value in ordered))
            )
            if violated and kind == "FORBIDDEN_WHEN":
                values = {**values, when["role"]: sample["values"].get(when_name)}
            if violated:
                violations.append({
                    "invariant_id": invariant["id"], "severity": invariant.get("severity", "CRITICAL"),
                    "type": kind, "step_id": sample.get("id"), "phase": sample.get("phase"),
                    "t_ms": round(sample["t_ms"], 1), "signals": names, "values": values,
                })
    critical = [v for v in violations if v["severity"] == "CRITICAL"]
    major = [v for v in violations if v["severity"] == "MAJOR"]
    return {
        "evaluated": bool(samples),
        "success": (not critical) if samples else None,
        "invariants_defined": len(invariants),
        "samples_checked": len(samples),
        "violations": violations,
        "critical_violations": len(critical),
        "major_violations": len(major),
    }


def _condition_holds(when: dict[str, Any], actual: Any) -> bool:
    if actual is None:
        return False
    if "equals" in when:
        return actual is when["equals"]
    if isinstance(actual, bool):
        return False
    return float(when.get("min", float("-inf"))) <= float(actual) <= float(when.get("max", float("inf")))


# ---------------------------------------------------------------------------------------------
# Veredicto
# ---------------------------------------------------------------------------------------------

def decide_verdict(
    infrastructure_error: str | None,
    review_codes: list[str],
    semantic: dict[str, Any],
    functional: dict[str, Any],
    safety: dict[str, Any],
) -> tuple[str, str]:
    """Precedencia: INFRA > FAIL por seguridad > REVIEW > FAIL funcional > (semantica) > PASS."""
    if infrastructure_error:
        return VERDICT_INFRA, infrastructure_error
    if safety.get("success") is False:
        return VERDICT_FAIL, "SAFETY_VIOLATION"
    if review_codes:
        return VERDICT_REVIEW, review_codes[0]
    if functional.get("success") is False:
        return VERDICT_FAIL, "FUNCTIONAL_FAILURE"
    if functional.get("success") is not True or safety.get("success") is not True:
        return VERDICT_REVIEW, "ORACLE_NOT_FULLY_EVALUATED"
    if semantic.get("success") is False:
        return VERDICT_REVIEW, SEMANTIC_MISMATCH
    if semantic.get("success") is None:
        return VERDICT_REVIEW, SEMANTIC_NOT_EVALUABLE
    return VERDICT_PASS, "ALL_CHECKS_PASSED"


def decide_final_status(
    compile_success: bool | None, download_success: bool | None, runtime_ready: bool | None, oracle_verdict: str | None
) -> str:
    """Estado final del ensayo con Oracle (las etapas previas mandan si fallaron)."""
    if compile_success is False:
        return VERDICT_FAIL
    if download_success is False or runtime_ready is False:
        return VERDICT_INFRA
    return oracle_verdict or VERDICT_REVIEW


# ---------------------------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------------------------

def _empty(evaluated: bool = False) -> dict[str, Any]:
    return {"evaluated": evaluated, "success": None}


def run_oracle(
    oracle: dict[str, Any],
    snapshot_path: Path | None,
    runtime_report: dict[str, Any] | None,
    target_type: str | None,
    semantic_output: dict[str, Any] | None = None,
    project_root: Path | None = None,
    bridge: Any = None,
    runtime_config: dict[str, Any] | None = None,
    process_variable_bindings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="milliseconds")
    started = time.perf_counter()
    result: dict[str, Any] = {
        "oracle_reference": oracle_schema.oracle_reference(oracle),
        # El estado del Oracle ya no decide el tipo de ensayo (lo decide la fase de la sesion).
        "oracle_formal": oracle_schema.is_formal(oracle),
        "roles": {"status": None, "roles": {}, "issues": []},
        "semantic": _empty(),
        "resources": {},
        "preconditions": {"success": None, "checks": []},
        "steps": [],
        "functional": _empty(),
        "safety": _empty(),
        "sequence": {},
        "cleanup": {"performed": False, "success": None},
        "errors": [],
        "warnings": [],
        "started_at": started_at,
    }

    def _finish(verdict: str, reason: str) -> dict[str, Any]:
        result["verdict"] = verdict
        result["verdict_reason"] = reason
        result["completed_at"] = datetime.now().isoformat(timespec="milliseconds")
        result["duration_ms"] = int(round((time.perf_counter() - started) * 1000))
        return result

    try:
        oracle_schema.assert_valid(oracle)
        oracle_schema.verify_integrity(oracle)
    except oracle_schema.OracleError as error:
        result["errors"].append(str(error))
        result["errors"].extend(error.details)
        return _finish(VERDICT_REVIEW, error.code)

    # Ejecucion por CAPACIDADES: runtime_support del Oracle congelado describe el Runtime de cuando se
    # congelo; lo que decide es si el Runtime ACTUAL cubre todos sus requisitos (declarados + derivados).
    capabilities = runtime_capability_check(oracle)
    result["runtime_capability_check"] = capabilities
    if not capabilities["executable"]:
        result["errors"].append(
            f"{RUNTIME_EXTENSION_REQUIRED}: el Oracle necesita {capabilities['required_capabilities']}; "
            f"el Runtime actual no soporta {capabilities['missing_capabilities']}. No se emite PASS/FAIL."
        )
        return _finish(VERDICT_REVIEW, RUNTIME_EXTENSION_REQUIRED)

    if snapshot_path is None or not Path(snapshot_path).exists():
        result["errors"].append(f"{SNAPSHOT_MISSING}: el ensayo no tiene io_map_snapshot.json.")
        return _finish(VERDICT_REVIEW, SNAPSHOT_MISSING)
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    program = rio.load_program_signals(Path(snapshot_path))
    if process_variable_bindings is None:
        process_variable_bindings = PV.load_process_variable_bindings(Path(snapshot_path).parent)
    result["process_variable_bindings"] = {"source": process_variable_bindings.get("source"),
                                           "instance_db": process_variable_bindings.get("instance_db"),
                                           "names": sorted(process_variable_bindings.get("bindings") or {})}

    resolution = resolve_roles(oracle, snapshot, process_variable_bindings)
    result["roles"] = resolution
    result["semantic"] = evaluate_semantics(oracle, semantic_output, resolution)
    result["warnings"].extend(result["semantic"].get("warnings", []))
    result["resources"] = evaluate_resources(oracle, snapshot)
    result["warnings"].extend(result["resources"]["warnings"])
    if resolution["issues"]:
        result["errors"].extend(issue["detail"] for issue in resolution["issues"])
        return _finish(VERDICT_REVIEW, resolution["issues"][0]["code"])

    config = runtime_config or plcsim_runtime.load_runtime_config(plcsim_runtime._load_tia_config(project_root or Path(".")))
    blocked = rio.check_write_allowed(target_type, runtime_report, config["instance_name"])
    if blocked:
        result["errors"].append(f"{RUNTIME_NOT_READY}: {blocked[0]}: {blocked[1]}")
        return _finish(VERDICT_INFRA, RUNTIME_NOT_READY)

    try:
        plan = compile_sequence(oracle, resolution["roles"], program, process_variable_bindings)
    except OracleSequenceError as error:
        result["errors"].append(str(error))
        return _finish(VERDICT_REVIEW, error.code)
    result["sequence"] = {key: plan[key] for key in ("planned_ms", "sample_period_ms", "watched", "skipped_steps")}
    payload = {"target_type": target_type, "settle_ms": config["io_settle_ms"], "steps": plan["steps"]}
    if plan["process_variables"]:
        # Escritura interna: el bridge la acepta solo con este proposito, target PLCSIM y CPU en RUN.
        payload.update({"process_variables": True, "purpose": PROCESS_VARIABLE_WRITE_PURPOSE,
                        "real_tolerance": REAL_WRITE_TOLERANCE})
    timeout = int(plan["planned_ms"] / 1000) + _SEQUENCE_MARGIN_S
    if bridge is None:
        raw = plcsim_runtime.run_runtime_bridge("io_sequence", project_root, config, extra=payload, timeout_seconds=timeout)
    else:
        raw = bridge("io_sequence", payload)
    raw.setdefault("sample_period_ms", plan["sample_period_ms"])
    result["trace"] = {"events": raw.get("events", []), "samples": raw.get("samples", [])}
    result["sequence"].update({
        "bridge_status": raw.get("status"), "failed_step": raw.get("failed_step"),
        "sequence_duration_ms": raw.get("sequence_duration_ms"), "cpu_state": raw.get("cpu_state"),
    })
    cleanup = raw.get("cleanup") or {}
    result["cleanup"] = {"performed": bool(cleanup.get("performed")), "success": cleanup.get("success"),
                         "inputs": cleanup.get("inputs", []), "process_variables": cleanup.get("process_variables", [])}
    if raw.get("resolved_process_variables"):
        # Evidencia: nombre Runtime REAL usado en PLCSIM para cada variable interna (formato descubierto).
        result["sequence"]["resolved_process_variables"] = raw["resolved_process_variables"]
    status = str(raw.get("status", ""))

    if status not in ("PLCSIM_IO_PASSED", "PLCSIM_SEQUENCE_REQUIREMENT_FAILED", "PLCSIM_IO_CLEANUP_FAILED"):
        result["errors"].extend(str(item) for item in raw.get("errors", []) or [])
        code = "PLCSIM_RUNTIME_IO_TIMEOUT" if status == "PLCSIM_RUNTIME_TIMEOUT" else (status or "PLCSIM_RUNTIME_ERROR")
        evaluation = evaluate_trace(oracle, resolution["roles"], raw)
        result["steps"] = evaluation["steps"]
        result["safety"] = evaluation["safety"]
        return _finish(VERDICT_INFRA, code)

    evaluation = evaluate_trace(oracle, resolution["roles"], raw)
    result["steps"] = evaluation["steps"]
    result["preconditions"] = evaluation["preconditions"]
    result["functional"] = evaluation["functional"]
    result["safety"] = evaluation["safety"]
    # Estimulo del arnes (variable interna INPUT) reescrito por el programa: fallo del DUT, no infraestructura.
    overwrites = detect_harness_input_overwrites(resolution["roles"], raw)
    result["harness_input_overwrites"] = overwrites
    review: list[str] = []
    if status == "PLCSIM_SEQUENCE_REQUIREMENT_FAILED":
        result["preconditions"]["success"] = False
        result["errors"].extend(str(item) for item in raw.get("errors", []) or [])
        if overwrites:
            # La precondicion no se pudo mantener PORQUE el DUT reescribe su entrada: Functional FAIL, no REVIEW.
            result["preconditions"]["failed_because"] = PROGRAM_OVERWRITES_HARNESS_INPUT
        else:
            result["functional"] = {**result["functional"], "evaluated": False, "success": None}
            review.append(PRECONDITION_FAILED)
    if overwrites:
        checks = [{"type": "harness_input_overwrite", "code": PROGRAM_OVERWRITES_HARNESS_INPUT, "passed": False, **item}
                  for item in overwrites]
        result["functional"] = {**result["functional"], "evaluated": True, "success": False,
                                "failed_checks": list(result["functional"].get("failed_checks") or []) + checks,
                                "harness_input_overwrites": len(overwrites)}
        result["errors"].extend(
            f"{PROGRAM_OVERWRITES_HARNESS_INPUT}: {item['role']} ({item['name']}) escrito {item['written_value']!r}, "
            f"observado {item['observed_value']!r} en {item['step_id']}." for item in overwrites)
    if status == "PLCSIM_IO_CLEANUP_FAILED" or cleanup.get("success") is False:
        result["errors"].append("PLCSIM_IO_CLEANUP_FAILED: alguna entrada o variable interna no volvio a su valor de restauracion.")
    for step in result["steps"]:
        result["errors"].extend(step["errors"])
    if any(check.get("error") == NO_SAMPLES for check in result["functional"].get("failed_checks", [])):
        review.append(NO_SAMPLES)
    verdict, reason = decide_verdict(None, review, result["semantic"], result["functional"], result["safety"])
    if overwrites and verdict == VERDICT_FAIL and reason == "FUNCTIONAL_FAILURE":
        reason = PROGRAM_OVERWRITES_HARNESS_INPUT  # Safety (mayor severidad) conserva su propio motivo
    return _finish(verdict, reason)


# ---------------------------------------------------------------------------------------------
# evaluation_report.json (fuente de la futura ficha)
# ---------------------------------------------------------------------------------------------

def build_evaluation_report(trial_record: dict[str, Any], oracle_result: dict[str, Any], final_status: str) -> dict[str, Any]:
    stages = trial_record.get("stages") or {}
    return {
        "report_schema_version": 1,
        "trial_id": trial_record.get("trial_id"),
        "case_id": trial_record.get("case_id"),
        "variant_id": trial_record.get("variant_id"),
        "input_mode": trial_record.get("input_mode"),
        "trial_kind": trial_record.get("trial_kind"),
        "experiment_phase": trial_record.get("experiment_phase"),
        "benchmark": {key: trial_record.get(key) for key in ("benchmark_version", "canonical_case_hash", "variant_hash")},
        "oracle": oracle_result.get("oracle_reference"),
        "semantic": {
            "stage_success": stages.get("semantic_success"),
            # semantic_pipeline_success: interpretacion estructuralmente valida que permitio continuar;
            # semantic_benchmark_match: coincidencia con la expectativa semantica del Oracle.
            "pipeline_success": stages.get("semantic_success"),
            "benchmark_match": (oracle_result.get("semantic") or {}).get("success"),
            "intent_expected": (oracle_result.get("semantic") or {}).get("intent_expected"),
            "intent_match": (oracle_result.get("semantic") or {}).get("intent_match"),
            "oracle_evaluation": oracle_result.get("semantic"),
            "intent_id": (trial_record.get("semantic") or {}).get("intent_id"),
        },
        "roles": oracle_result.get("roles"),
        "resources": oracle_result.get("resources"),
        "compile": {"success": stages.get("compile_success"), **{k: (trial_record.get("compile") or {}).get(k) for k in ("status", "error_count", "warning_count")}},
        "download": {"success": stages.get("download_success"), **{k: (trial_record.get("download") or {}).get(k) for k in ("status", "target_type", "start_module_success", "cpu_run_confirmed")}},
        "runtime": trial_record.get("runtime"),
        "preconditions": oracle_result.get("preconditions"),
        "functional": oracle_result.get("functional"),
        "safety": oracle_result.get("safety"),
        # Evidencia de estimulos del arnes reescritos por el DUT (variable, valores, tiempos, nombre Runtime).
        "harness_input_overwrites": oracle_result.get("harness_input_overwrites") or [],
        "oracle_verdict": oracle_result.get("verdict"),
        "oracle_verdict_reason": oracle_result.get("verdict_reason"),
        "final_status": final_status,
        "steps": oracle_result.get("steps"),
        "cleanup": oracle_result.get("cleanup"),
        "sequence": oracle_result.get("sequence"),
        "errors": list(trial_record.get("errors") or []) + list(oracle_result.get("errors") or []),
        "warnings": oracle_result.get("warnings"),
        "timings": {**(trial_record.get("timing") or {}), "oracle_ms": oracle_result.get("duration_ms")},
        "manual_audit": {
            "selected": False,
            "reviewer": None,
            "automated_result": None,
            "manual_result": None,
            "agreement": None,
            "notes": None,
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def write_oracle_artifacts(trial_directory: Path, oracle_result: dict[str, Any], report: dict[str, Any]) -> dict[str, str]:
    trial_directory.mkdir(parents=True, exist_ok=True)
    report_path = trial_directory / EVALUATION_REPORT_FILENAME
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    trace_path = trial_directory / ORACLE_TRACE_FILENAME
    trace_path.write_text(json.dumps(oracle_result.get("trace", {}), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return {"evaluation_report": str(report_path), "oracle_trace": str(trace_path)}


def trial_patch(oracle_result: dict[str, Any], artifacts: dict[str, str] | None = None) -> dict[str, Any]:
    """Campos de trial.json que rellena el Oracle Runner (functional/safety separados)."""
    functional = {k: oracle_result["functional"].get(k) for k in ("evaluated", "success", "passed_checks", "total_checks", "pass_rate")}
    safety = {k: oracle_result["safety"].get(k) for k in ("evaluated", "success", "invariants_defined", "critical_violations", "samples_checked")}
    semantic = oracle_result.get("semantic") or {}
    return {
        # Coincidencia con la expectativa semantica del benchmark: dimension propia, nunca Functional.
        "semantic_benchmark": {
            "match": semantic.get("success"),
            "intent_actual": semantic.get("intent_id"),
            "intent_expected": semantic.get("intent_expected"),
            "intent_match": semantic.get("intent_match"),
            "failed_checks": semantic.get("failed_checks") or [],
        },
        "oracle_reference": oracle_result.get("oracle_reference"),
        "oracle": {
            "verdict": oracle_result.get("verdict"),
            "verdict_reason": oracle_result.get("verdict_reason"),
            "roles": {role: entry["functional_name"] for role, entry in (oracle_result.get("roles") or {}).get("roles", {}).items()},
            "role_issues": [issue["code"] for issue in (oracle_result.get("roles") or {}).get("issues", [])],
            "preconditions_success": (oracle_result.get("preconditions") or {}).get("success"),
            "cleanup_success": (oracle_result.get("cleanup") or {}).get("success"),
            "duration_ms": oracle_result.get("duration_ms"),
            **(artifacts or {}),
        },
        "functional": functional,
        "safety": safety,
        "stages": {"functional_success": functional["success"], "safety_success": safety["success"],
                   "semantic_benchmark_match": semantic.get("success")},
        "timing": {"functional_test_ms": oracle_result.get("duration_ms"), "oracle_ms": oracle_result.get("duration_ms")},
    }
