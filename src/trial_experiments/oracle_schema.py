"""
Oracle de comportamiento (Fase 3A/3B): schema versionado, validacion, hash y aprobacion.

Un Oracle NO es codigo PLC de referencia: describe COMPORTAMIENTO en terminos de ROLES
funcionales (START, STOP, MOTOR_MAIN...), nunca de direcciones fisicas. El Oracle Runner resuelve
cada rol contra los bindings congelados del ensayo (io_map_snapshot.json).

Ciclo de vida:
  DRAFT            borrador (posiblemente asistido por IA);
  DRAFT_REVIEWED   borrador que paso la revision asistida (schema + revision semantica por IA);
                   sigue SIN aprobacion formal;
  APPROVED/FROZEN  aprobado por el investigador. No se modifica: los cambios crean una version
                   nueva (supersede_frozen conserva la anterior en versions/).

El hash SHA-256 se calcula sobre el contenido normalizado SIN el bloque `approval`: aprobar (o
anotar la revision asistida, que vive en approval.ai_review) no cambia el hash; cualquier edicion
del comportamiento si lo cambia.

Fase 3B (retrocompatible: un Oracle 3A congelado conserva su hash):
  - runtime_support (EXECUTABLE_NOW / REQUIRES_RUNTIME_EXTENSION) y runtime_requirements;
  - roles con data_type (BOOL/INT/WORD/REAL) y binding IO (semantic_paths sobre los bindings
    del ensayo) o PROCESS_VARIABLE (variables funcionales del contrato PID, p.ej. Level_SP);
  - pasos opcionales (requires_roles), time_reference a un paso anterior, expectativas numericas
    ({approx, tolerance} o {min, max});
  - invariantes IMPLIES e IN_RANGE y grace_ms;
  - experimental_conventions y source_definition para trazabilidad.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "oracle-1.0"

STATUS_DRAFT = "DRAFT"
STATUS_DRAFT_REVIEWED = "DRAFT_REVIEWED"
STATUS_APPROVED = "APPROVED"
STATUS_FROZEN = "FROZEN"
APPROVAL_STATUSES = (STATUS_DRAFT, STATUS_DRAFT_REVIEWED, STATUS_APPROVED, STATUS_FROZEN)
FORMAL_STATUSES = (STATUS_APPROVED, STATUS_FROZEN)
DRAFT_STATUSES = (STATUS_DRAFT, STATUS_DRAFT_REVIEWED)

ROLE_KINDS = ("INPUT", "OUTPUT")
ROLE_BINDINGS = ("IO", "PROCESS_VARIABLE")
DATA_TYPES = ("BOOL", "INT", "WORD", "REAL")
NUMERIC_TYPES = ("INT", "WORD", "REAL")
COMPLEXITIES = ("LOW", "MEDIUM", "HIGH")
INVARIANT_TYPES = (
    "NEVER_TRUE_TOGETHER", "NEVER_TRUE", "ALWAYS_EQUAL", "IMPLIES", "IN_RANGE", "AT_MOST_ONE", "EXACTLY_ONE", "FORBIDDEN_WHEN"
)
# CRITICAL = invariante de SEGURIDAD (safety_success); MAJOR = invariante FUNCIONAL (functional_success).
SEVERITIES = ("CRITICAL", "MAJOR")

RUNTIME_EXECUTABLE_NOW = "EXECUTABLE_NOW"
RUNTIME_REQUIRES_EXTENSION = "REQUIRES_RUNTIME_EXTENSION"
RUNTIME_SUPPORT = (RUNTIME_EXECUTABLE_NOW, RUNTIME_REQUIRES_EXTENSION)
RUNTIME_REQUIREMENTS = ("BOOL", "INT", "WORD", "REAL", "INTERNAL_TAG_READ", "INTERNAL_TAG_WRITE")

ORACLES_DIRNAME = "experiment_oracles"
VERSIONS_DIRNAME = "versions"

ERROR_SCHEMA_INVALID = "ORACLE_SCHEMA_INVALID"
ERROR_NOT_FOUND = "ORACLE_NOT_FOUND"
ERROR_FROZEN = "ORACLE_FROZEN"
ERROR_INTEGRITY = "ORACLE_INTEGRITY_FAILED"

_PHYSICAL_ADDRESS = re.compile(r"%[IQM][XBWD]?\d+", re.IGNORECASE)
_ROLE_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class OracleError(RuntimeError):
    def __init__(self, code: str, message: str, details: list[str] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.detail = message
        self.details = list(details or [])


# ---------------------------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------------------------

def get_oracles_dir(project_root: Path) -> Path:
    return project_root / "data" / ORACLES_DIRNAME


def oracle_path(project_root: Path, oracle_id: str) -> Path:
    return get_oracles_dir(project_root) / f"{oracle_id}.json"


# ---------------------------------------------------------------------------------------------
# Hash
# ---------------------------------------------------------------------------------------------

def normalized_content(oracle: dict[str, Any]) -> dict[str, Any]:
    """Contenido que define el comportamiento: todo excepto el bloque de aprobacion."""
    return {key: value for key, value in oracle.items() if key != "approval"}


def compute_oracle_hash(oracle: dict[str, Any]) -> str:
    canonical = json.dumps(normalized_content(oracle), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------
# Helpers de roles
# ---------------------------------------------------------------------------------------------

def role_data_type(role: dict[str, Any]) -> str:
    return str(role.get("data_type") or "BOOL")


def role_binding(role: dict[str, Any]) -> str:
    return str(role.get("binding") or "IO")


def runtime_support(oracle: dict[str, Any]) -> str:
    """Declarado en el Oracle; los Oracles 3A (sin el campo) eran todos BOOL/IO ejecutables."""
    return str(oracle.get("runtime_support") or RUNTIME_EXECUTABLE_NOW)


def derived_runtime_requirements(oracle: dict[str, Any]) -> list[str]:
    """Lo que el Runtime necesita realmente para ejecutar el Oracle (derivado de sus roles)."""
    needed: set[str] = set()
    for role in (oracle.get("roles") or {}).values():
        needed.add(role_data_type(role))
        if role_binding(role) == "PROCESS_VARIABLE":
            needed.add("INTERNAL_TAG_READ")
            if role.get("kind") == "INPUT":
                needed.add("INTERNAL_TAG_WRITE")
    return [item for item in RUNTIME_REQUIREMENTS if item in needed]


def is_bool_io_only(oracle: dict[str, Any]) -> bool:
    return all(
        role_data_type(role) == "BOOL" and role_binding(role) == "IO"
        for role in (oracle.get("roles") or {}).values()
    )


# ---------------------------------------------------------------------------------------------
# Validacion
# ---------------------------------------------------------------------------------------------

def _strings(value: Any, path: str = "$"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_value(role: dict[str, Any], value: Any, for_expect: bool) -> bool:
    if role_data_type(role) == "BOOL":
        return isinstance(value, bool)
    if _is_number(value):
        return True
    if for_expect and isinstance(value, dict):
        if "approx" in value:
            return _is_number(value["approx"]) and _is_number(value.get("tolerance", 0))
        if "min" in value or "max" in value:
            return all(_is_number(value[key]) for key in ("min", "max") if key in value)
    return False


def _validate_steps(steps: Any, section: str, roles: dict[str, Any], errors: list[str], all_ids: set[str]) -> None:
    """all_ids: ids de TODO el Oracle (sin duplicados). time_reference solo a pasos anteriores de
    la MISMA seccion."""
    if not isinstance(steps, list):
        errors.append(f"{section} debe ser una lista.")
        return
    known_ids: set[str] = set()
    for index, step in enumerate(steps):
        where = f"{section}[{index}]"
        if not isinstance(step, dict):
            errors.append(f"{where} debe ser un objeto.")
            continue
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id:
            errors.append(f"{where}.id es obligatorio.")
        elif step_id in all_ids:
            errors.append(f"{where}.id duplicado: {step_id}.")
        for role, value in (step.get("set") or {}).items():
            if role not in roles:
                errors.append(f"{where}.set usa un rol desconocido: {role}.")
                continue
            if roles[role].get("kind") != "INPUT":
                errors.append(f"{where}.set solo puede escribir roles INPUT ({role} es {roles[role].get('kind')}).")
            if not _valid_value(roles[role], value, for_expect=False):
                errors.append(f"{where}.set.{role}: valor {value!r} no valido para {role_data_type(roles[role])}.")
        for role, value in (step.get("expect") or {}).items():
            if role not in roles:
                errors.append(f"{where}.expect usa un rol desconocido: {role}.")
            elif not _valid_value(roles[role], value, for_expect=True):
                errors.append(f"{where}.expect.{role}: valor {value!r} no valido para {role_data_type(roles[role])}.")
        wait_ms = step.get("wait_ms", 0)
        if not isinstance(wait_ms, int) or wait_ms < 0 or wait_ms > 60000:
            errors.append(f"{where}.wait_ms debe ser un entero entre 0 y 60000.")
            wait_ms = 0
        reference = step.get("time_reference")
        if reference is not None and reference not in known_ids:
            errors.append(f"{where}.time_reference debe apuntar a un paso ANTERIOR de la misma seccion ({reference}).")
        offset = 0
        if reference is not None:
            offset = sum(int(s.get("wait_ms", 0)) for s in _steps_between(steps, reference, step_id))
        for w_index, window in enumerate(step.get("expect_timeline") or []):
            w_where = f"{where}.expect_timeline[{w_index}]"
            start, end = window.get("from_ms"), window.get("to_ms")
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
                errors.append(f"{w_where}: from_ms/to_ms invalidos.")
            elif end > offset + int(wait_ms):
                errors.append(f"{w_where}: to_ms ({end}) supera el final del paso ({offset + int(wait_ms)} ms desde la referencia).")
            for role, value in (window.get("expect") or {}).items():
                if role not in roles or not _valid_value(roles[role], value, for_expect=True):
                    errors.append(f"{w_where}.expect invalido para {role}.")
        transition = step.get("measure_transition")
        if transition is not None:
            if transition.get("role") not in roles:
                errors.append(f"{where}.measure_transition.role desconocido.")
            tolerance = transition.get("tolerance_ms") or {}
            if not isinstance(transition.get("nominal_ms"), int) or not all(
                isinstance(tolerance.get(key), int) and tolerance.get(key) >= 0 for key in ("early", "late")
            ):
                errors.append(f"{where}.measure_transition requiere nominal_ms y tolerance_ms.early/late enteros.")
        for role in step.get("unspecified") or []:
            if role not in roles:
                errors.append(f"{where}.unspecified usa un rol desconocido: {role}.")
        for role in step.get("requires_roles") or []:
            if role not in roles:
                errors.append(f"{where}.requires_roles usa un rol desconocido: {role}.")
            elif roles[role].get("required", True):
                errors.append(f"{where}.requires_roles solo tiene sentido con roles opcionales ({role} es obligatorio).")
        used = set(step.get("set") or {}) | set(step.get("expect") or {})
        for window in step.get("expect_timeline") or []:
            used |= set(window.get("expect") or {})
        optional_used = [r for r in used if r in roles and not roles[r].get("required", True)]
        missing_guard = [r for r in optional_used if r not in (step.get("requires_roles") or [])]
        if missing_guard:
            errors.append(f"{where} usa roles opcionales {missing_guard} sin declararlos en requires_roles.")
        if isinstance(step_id, str) and step_id:
            known_ids.add(step_id)
            all_ids.add(step_id)


def _steps_between(steps: list[dict[str, Any]], reference: str, current: str | None) -> list[dict[str, Any]]:
    """Pasos desde `reference` (incluido) hasta `current` (excluido): tiempo transcurrido."""
    collected: list[dict[str, Any]] = []
    active = False
    for step in steps:
        if step.get("id") == reference:
            active = True
        if step.get("id") == current:
            break
        if active:
            collected.append(step)
    return collected


def validate_oracle(oracle: Any) -> list[str]:
    """Lista de errores (vacia = valido)."""
    errors: list[str] = []
    if not isinstance(oracle, dict):
        return ["El Oracle debe ser un objeto JSON."]
    for key in ("schema_version", "oracle_id", "case_id", "title", "description", "complexity", "approval",
                "semantic_expectations", "roles", "resource_expectations", "preconditions", "test_sequence",
                "invariants", "cleanup", "evaluation"):
        if key not in oracle:
            errors.append(f"Falta el campo obligatorio: {key}.")
    if errors:
        return errors
    if oracle["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version {oracle['schema_version']!r} no soportado (esperado {SCHEMA_VERSION}).")
    if not re.match(r"^[DP]\d{2}$", str(oracle["case_id"])):
        errors.append("case_id debe ser Dxx o Pxx.")
    if oracle["oracle_id"] != oracle["case_id"]:
        errors.append("oracle_id debe coincidir con case_id.")
    if oracle["complexity"] not in COMPLEXITIES:
        errors.append(f"complexity debe ser uno de {COMPLEXITIES}.")

    approval = oracle["approval"]
    if not isinstance(approval, dict) or approval.get("status") not in APPROVAL_STATUSES:
        errors.append(f"approval.status debe ser uno de {APPROVAL_STATUSES}.")
    elif not isinstance(approval.get("version"), int) or approval["version"] < 1:
        errors.append("approval.version debe ser un entero >= 1.")
    elif approval["status"] in FORMAL_STATUSES and not (approval.get("hash") and approval.get("approved_at")):
        errors.append("Un Oracle aprobado requiere approval.hash y approval.approved_at.")
    elif approval["status"] in DRAFT_STATUSES and approval.get("approved_by"):
        errors.append("Un Oracle en borrador no puede tener approved_by (la aprobacion formal es del investigador).")

    support = oracle.get("runtime_support", RUNTIME_EXECUTABLE_NOW)
    if support not in RUNTIME_SUPPORT:
        errors.append(f"runtime_support debe ser uno de {RUNTIME_SUPPORT}.")
    requirements = oracle.get("runtime_requirements")
    if requirements is not None and (not isinstance(requirements, list) or any(r not in RUNTIME_REQUIREMENTS for r in requirements)):
        errors.append(f"runtime_requirements debe ser una lista de {RUNTIME_REQUIREMENTS}.")

    roles = oracle["roles"]
    if not isinstance(roles, dict) or not roles:
        errors.append("roles debe ser un objeto no vacio.")
        roles = {}
    for name, role in roles.items():
        if not _ROLE_NAME.match(name):
            errors.append(f"Nombre de rol invalido: {name} (MAYUSCULAS_CON_GUIONES).")
        if not isinstance(role, dict) or role.get("kind") not in ROLE_KINDS:
            errors.append(f"roles.{name}.kind debe ser INPUT u OUTPUT.")
            continue
        if role_data_type(role) not in DATA_TYPES:
            errors.append(f"roles.{name}.data_type debe ser uno de {DATA_TYPES}.")
        binding = role_binding(role)
        if binding not in ROLE_BINDINGS:
            errors.append(f"roles.{name}.binding debe ser uno de {ROLE_BINDINGS}.")
        elif binding == "IO":
            paths = role.get("semantic_paths")
            if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
                errors.append(f"roles.{name}.semantic_paths debe ser una lista no vacia de rutas.")
        else:
            names = role.get("process_variables")
            if not isinstance(names, list) or not names or not all(isinstance(p, str) and p for p in names):
                errors.append(f"roles.{name}.process_variables debe ser una lista no vacia (binding PROCESS_VARIABLE).")

    derived = derived_runtime_requirements(oracle)
    if support == RUNTIME_EXECUTABLE_NOW and not is_bool_io_only(oracle):
        errors.append("runtime_support=EXECUTABLE_NOW pero el Oracle usa roles no BOOL o variables internas: "
                      f"requiere {derived} (marcar REQUIRES_RUNTIME_EXTENSION).")
    if requirements is not None and sorted(requirements) != sorted(derived):
        errors.append(f"runtime_requirements {requirements} no coincide con lo que exigen los roles {derived}.")

    for required in (oracle["semantic_expectations"] or {}).get("required_roles", []):
        if required not in roles:
            errors.append(f"semantic_expectations.required_roles usa un rol desconocido: {required}.")

    all_ids: set[str] = set()
    for section in ("preconditions", "test_sequence", "cleanup"):
        _validate_steps(oracle[section], section, roles, errors, all_ids)
    if isinstance(oracle["test_sequence"], list) and not oracle["test_sequence"]:
        errors.append("test_sequence no puede estar vacia.")

    if not isinstance(oracle["invariants"], list):
        errors.append("invariants debe ser una lista.")
    else:
        for index, invariant in enumerate(oracle["invariants"]):
            where = f"invariants[{index}]"
            kind = invariant.get("type")
            if kind not in INVARIANT_TYPES:
                errors.append(f"{where}.type debe ser uno de {INVARIANT_TYPES}.")
            if invariant.get("severity", "CRITICAL") not in SEVERITIES:
                errors.append(f"{where}.severity debe ser uno de {SEVERITIES}.")
            invariant_roles = invariant.get("roles") or []
            for role in invariant_roles:
                if role not in roles:
                    errors.append(f"{where}.roles usa un rol desconocido: {role}.")
            if kind == "IMPLIES" and len(invariant_roles) != 2:
                errors.append(f"{where}: IMPLIES necesita exactamente 2 roles [si, entonces].")
            if kind == "IN_RANGE":
                if len(invariant_roles) != 1 or not all(_is_number(invariant.get(k)) for k in ("min", "max")):
                    errors.append(f"{where}: IN_RANGE necesita 1 rol numerico y min/max.")
            if kind in ("NEVER_TRUE_TOGETHER", "NEVER_TRUE", "ALWAYS_EQUAL", "IMPLIES", "AT_MOST_ONE", "EXACTLY_ONE",
                        "FORBIDDEN_WHEN") and any(
                role in roles and role_data_type(roles[role]) != "BOOL" for role in invariant_roles
            ):
                errors.append(f"{where}: {kind} solo admite roles BOOL.")
            if kind in ("AT_MOST_ONE", "EXACTLY_ONE") and len(invariant_roles) < 2:
                errors.append(f"{where}: {kind} necesita al menos 2 roles.")
            if kind == "FORBIDDEN_WHEN":
                when = invariant.get("when") or {}
                if when.get("role") not in roles:
                    errors.append(f"{where}.when.role desconocido.")
                elif role_data_type(roles[when["role"]]) == "BOOL":
                    if not isinstance(when.get("equals"), bool):
                        errors.append(f"{where}.when: un rol BOOL requiere 'equals' booleano.")
                elif not any(_is_number(when.get(k)) for k in ("min", "max")):
                    errors.append(f"{where}.when: un rol numerico requiere 'min' y/o 'max'.")
            grace = invariant.get("grace_ms", 0)
            if not isinstance(grace, int) or grace < 0 or grace > 2000:
                errors.append(f"{where}.grace_ms debe ser un entero entre 0 y 2000.")
            if not invariant.get("id"):
                errors.append(f"{where}.id es obligatorio.")

    sampling = (oracle["evaluation"] or {}).get("sample_period_ms", 50)
    if not isinstance(sampling, int) or sampling < 10 or sampling > 1000:
        errors.append("evaluation.sample_period_ms debe estar entre 10 y 1000.")

    for path, text in _strings(normalized_content(oracle)):
        if _PHYSICAL_ADDRESS.search(text):
            errors.append(f"{path}: el Oracle no puede contener direcciones fisicas ({text!r}); use roles.")
    return errors


def assert_valid(oracle: Any) -> None:
    errors = validate_oracle(oracle)
    if errors:
        raise OracleError(ERROR_SCHEMA_INVALID, "Oracle invalido.", errors)


# ---------------------------------------------------------------------------------------------
# Carga / aprobacion / versiones
# ---------------------------------------------------------------------------------------------

def is_formal(oracle: dict[str, Any]) -> bool:
    return (oracle.get("approval") or {}).get("status") in FORMAL_STATUSES


def open_review_items(oracle: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in oracle.get("review_items") or [] if item.get("status", "OPEN") == "OPEN"]


def verify_integrity(oracle: dict[str, Any]) -> None:
    """Un Oracle aprobado debe conservar exactamente el contenido que se aprobo."""
    approval = oracle.get("approval") or {}
    if approval.get("status") in FORMAL_STATUSES and approval.get("hash") != compute_oracle_hash(oracle):
        raise OracleError(ERROR_INTEGRITY, f"El contenido del Oracle {oracle.get('oracle_id')} no coincide con el hash aprobado.")


def load_oracle(project_root: Path, oracle_id: str) -> dict[str, Any]:
    path = oracle_path(project_root, oracle_id)
    if not path.exists():
        raise OracleError(ERROR_NOT_FOUND, f"No existe el Oracle {oracle_id} ({path}).")
    oracle = json.loads(path.read_text(encoding="utf-8"))
    assert_valid(oracle)
    verify_integrity(oracle)
    return oracle


def find_case_oracle(project_root: Path, case_id: str | None) -> dict[str, Any] | None:
    """Oracle del caso si existe (None si el caso aun no tiene Oracle: el ensayo queda PREPARED)."""
    if not case_id or not oracle_path(project_root, case_id).exists():
        return None
    return load_oracle(project_root, case_id)


def _write(path: Path, oracle: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(oracle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def save_oracle(project_root: Path, oracle: dict[str, Any]) -> Path:
    """Guarda un Oracle en borrador. Nunca sobrescribe uno aprobado/congelado con contenido distinto
    (para eso: supersede_frozen, que conserva la version congelada en versions/)."""
    assert_valid(oracle)
    path = oracle_path(project_root, oracle["oracle_id"])
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if is_formal(existing) and compute_oracle_hash(existing) != compute_oracle_hash(oracle):
            raise OracleError(ERROR_FROZEN, f"El Oracle {oracle['oracle_id']} esta congelado; cree una version nueva.")
        if is_formal(existing) and not is_formal(oracle):
            raise OracleError(ERROR_FROZEN, f"El Oracle {oracle['oracle_id']} esta congelado; no puede volver a DRAFT.")
    _write(path, oracle)
    return path


def approve_oracle(
    project_root: Path,
    oracle_id: str,
    approved_by: str,
    acknowledge_review_items: bool = False,
    status: str = STATUS_FROZEN,
) -> dict[str, Any]:
    """DRAFT/DRAFT_REVIEWED -> FROZEN (o APPROVED): fija approved_by/approved_at/hash y guarda una
    copia inmutable en versions/. Solo el investigador aprueba: approved_by es obligatorio."""
    if status not in FORMAL_STATUSES:
        raise ValueError(f"Estado de aprobacion invalido: {status}")
    if not str(approved_by or "").strip():
        raise ValueError("approved_by es obligatorio.")
    path = oracle_path(project_root, oracle_id)
    if not path.exists():
        raise OracleError(ERROR_NOT_FOUND, f"No existe el Oracle {oracle_id}.")
    oracle = json.loads(path.read_text(encoding="utf-8"))
    assert_valid(oracle)
    if is_formal(oracle):
        raise OracleError(ERROR_FROZEN, f"El Oracle {oracle_id} ya esta {oracle['approval']['status']} (v{oracle['approval']['version']}).")
    pending = open_review_items(oracle)
    if pending and not acknowledge_review_items:
        raise OracleError(
            "ORACLE_REVIEW_ITEMS_OPEN",
            f"El Oracle {oracle_id} tiene {len(pending)} punto(s) REVIEW_REQUIRED sin confirmar.",
            [item.get("text", "") for item in pending],
        )
    approved_at = datetime.now().isoformat(timespec="seconds")
    for item in pending:
        item["status"] = "ACKNOWLEDGED"
        item["acknowledged_by"] = approved_by
        item["acknowledged_at"] = approved_at
    oracle["approval"] = {
        **oracle["approval"],
        "status": status,
        "approved_by": approved_by.strip(),
        "approved_at": approved_at,
        "hash": compute_oracle_hash(oracle),
    }
    if "human_formal_approval" in oracle["approval"]:  # marcador de la validacion tecnica previa: ya no esta pendiente
        oracle["approval"]["human_formal_approval"] = "APPROVED"
    assert_valid(oracle)
    _write(path, oracle)
    version = oracle["approval"]["version"]
    _write(get_oracles_dir(project_root) / VERSIONS_DIRNAME / f"{oracle_id}_v{version}.json", oracle)
    return oracle


def supersede_frozen(project_root: Path, draft: dict[str, Any]) -> Path:
    """
    Publica la version N+1 (borrador) de un Oracle congelado SIN perder la version N: exige que
    versions/{id}_vN.json exista e identica a la congelada (la crea si falta) y solo entonces
    reemplaza el Oracle vigente. Nunca edita silenciosamente una version congelada.
    """
    assert_valid(draft)
    path = oracle_path(project_root, draft["oracle_id"])
    if not path.exists():
        raise OracleError(ERROR_NOT_FOUND, f"No existe el Oracle {draft['oracle_id']}.")
    current = json.loads(path.read_text(encoding="utf-8"))
    if not is_formal(current):
        raise OracleError(ERROR_FROZEN, f"{draft['oracle_id']} no esta congelado: edite el borrador con save_oracle.")
    verify_integrity(current)
    old_version = int(current["approval"]["version"])
    if int(draft["approval"]["version"]) != old_version + 1 or is_formal(draft):
        raise OracleError(ERROR_FROZEN, f"La nueva version debe ser un borrador v{old_version + 1}.")
    if draft["approval"].get("previous_hash") != current["approval"]["hash"]:
        raise OracleError(ERROR_FROZEN, "previous_hash de la nueva version no coincide con la version congelada.")
    archived = get_oracles_dir(project_root) / VERSIONS_DIRNAME / f"{draft['oracle_id']}_v{old_version}.json"
    if archived.exists():
        stored = json.loads(archived.read_text(encoding="utf-8"))
        if compute_oracle_hash(stored) != current["approval"]["hash"]:
            raise OracleError(ERROR_INTEGRITY, f"{archived.name} no coincide con la version congelada vigente.")
    else:
        _write(archived, current)
    _write(path, draft)
    return path


def mark_ai_reviewed(oracle: dict[str, Any], notes: list[str] | None = None) -> dict[str, Any]:
    """Revision ASISTIDA (no aprobacion): DRAFT -> DRAFT_REVIEWED con approval.ai_review. No toca el
    contenido (el hash no cambia) y nunca rellena approved_by."""
    if is_formal(oracle):
        raise OracleError(ERROR_FROZEN, f"{oracle.get('oracle_id')} ya esta aprobado.")
    assert_valid(oracle)
    reviewed = copy.deepcopy(oracle)
    reviewed["approval"]["status"] = STATUS_DRAFT_REVIEWED
    reviewed["approval"]["ai_review"] = {
        "generated": True,
        "schema_validated": True,
        "semantic_reviewed": True,
        "second_pass_reviewed": True,
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "notes": list(notes or []),
    }
    return reviewed


def new_version(oracle: dict[str, Any]) -> dict[str, Any]:
    """Copia DRAFT con version+1 para cambios futuros de un Oracle congelado."""
    draft = copy.deepcopy(oracle)
    draft["approval"] = {
        "status": STATUS_DRAFT,
        "approved_by": None,
        "approved_at": None,
        "version": int(oracle["approval"]["version"]) + 1,
        "hash": None,
        "previous_hash": oracle["approval"].get("hash"),
    }
    return draft


def oracle_reference(oracle: dict[str, Any]) -> dict[str, Any]:
    """oracle_reference de trial.json: que especificacion exacta evaluo el ensayo."""
    approval = oracle.get("approval") or {}
    return {
        "oracle_id": oracle.get("oracle_id"),
        "oracle_version": approval.get("version"),
        "oracle_hash": compute_oracle_hash(oracle),
        "oracle_status": approval.get("status"),
    }
