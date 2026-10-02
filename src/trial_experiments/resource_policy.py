"""
Politica de recursos de los ensayos (Fase 4A.0b).

Benchmark v2: `profiles.json -> allowed_variables` es METADATA HISTORICA, nunca una whitelist.
Un ensayo es valido en recursos si:
  1. los recursos requeridos salen de la interpretacion semantica;
  2. el IOAllocator los resuelve sobre el working_io_map del ensayo (si no -> UNRESOLVED_RESOURCE);
  3. cada recurso externo del programa generado (variables.json) tiene binding real en el
     working map congelado (io_map_snapshot.json): mismo nombre y misma direccion (si no ->
     GHOST_RESOURCE);
  4. el tipo/direccion es compatible con el canal (INPUT en %I, OUTPUT en %Q, BOOL en canal
     digital, analogico en canal analogico) (si no -> TYPE_INCOMPATIBLE);
  5. ningun canal LOCKED fue renombrado/reasignado durante el ensayo (si no -> LOCKED_VIOLATION).

Ninguna regla depende de case_id ni de listas por caso. La whitelist por perfil solo existe para
el benchmark legacy v1 (`legacy_profile_whitelist_applies`), aislada para evitar usos accidentales.
"""
from __future__ import annotations

from typing import Any

from trial_experiments.trial_io_map import physical_signal

LEGACY_WHITELIST_BENCHMARK_VERSIONS = frozenset({1})

POLICY_WORKING_MAP_BINDING = "WORKING_MAP_BINDING"
POLICY_LEGACY_PROFILE_WHITELIST = "LEGACY_PROFILE_WHITELIST"

ERROR_UNRESOLVED_RESOURCE = "EXPERIMENT_IO_UNRESOLVED_RESOURCE"
ERROR_GHOST_RESOURCE = "EXPERIMENT_IO_GHOST_RESOURCE"
ERROR_TYPE_INCOMPATIBLE = "EXPERIMENT_IO_TYPE_INCOMPATIBLE"
ERROR_LOCKED_VIOLATION = "EXPERIMENT_IO_LOCKED_VIOLATION"

# Etapa del fallo (trial.json -> failure_stage) para la taxonomia de experimental_design.
STAGE_IO_ALLOCATION = "io_allocation"
STAGE_RESOURCE_BINDING = "resource_binding"

_DIGITAL_SIGNALS = {"DI", "DO"}
_INPUT_SIGNALS = {"DI", "AI"}
_OUTPUT_SIGNALS = {"DO", "AO"}


def legacy_profile_whitelist_applies(benchmark_version: Any) -> bool:
    """Solo el benchmark legacy v1 usa allowed_variables como whitelist. v2+: nunca."""
    try:
        return int(benchmark_version) in LEGACY_WHITELIST_BENCHMARK_VERSIONS
    except (TypeError, ValueError):
        return False


def resource_policy(benchmark_version: Any) -> str:
    return POLICY_LEGACY_PROFILE_WHITELIST if legacy_profile_whitelist_applies(benchmark_version) else POLICY_WORKING_MAP_BINDING


def _normalize_address(address: Any) -> str:
    return str(address or "").strip().upper().replace(" ", "")


def _is_external(variable: dict[str, Any]) -> bool:
    return physical_signal(variable.get("location")) is not None or str(variable.get("class", "")).lower() in ("input", "output")


def _type_compatible(variable: dict[str, Any], channel: dict[str, Any]) -> str | None:
    signal = channel.get("signal")
    var_class = str(variable.get("class", "")).lower()
    if var_class == "input" and signal not in _INPUT_SIGNALS:
        return f"{variable.get('name')} es INPUT pero el canal {channel.get('address')} es {signal}."
    if var_class == "output" and signal not in _OUTPUT_SIGNALS:
        return f"{variable.get('name')} es OUTPUT pero el canal {channel.get('address')} es {signal}."
    is_bool = str(variable.get("type", "")).upper() == "BOOL"
    if is_bool != (signal in _DIGITAL_SIGNALS):
        return f"{variable.get('name')} es {variable.get('type')} pero el canal {channel.get('address')} es {signal}."
    channel_type = str(channel.get("data_type") or "").upper()
    if channel_type and str(variable.get("type", "")).upper() != channel_type:
        return f"{variable.get('name')} es {variable.get('type')} pero el canal {channel.get('address')} es {channel_type}."
    return None


def locked_violations(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Un canal LOCKED nunca cambia de nombre ni deja de estar LOCKED durante el ensayo."""
    violations = []
    for entry in snapshot.get("allocation_history", []) or []:
        if str(entry.get("old_state", "")).upper() == "LOCKED" and (
            entry.get("old_name") != entry.get("new_name") or str(entry.get("new_state", "")).upper() != "LOCKED"
        ):
            violations.append({
                "code": ERROR_LOCKED_VIOLATION,
                "name": str(entry.get("old_name")),
                "detail": f"El canal LOCKED {entry.get('address')} ({entry.get('old_name')}) fue modificado a {entry.get('new_name')}.",
            })
    return violations


def unresolved_resources(semantic_output: dict[str, Any] | None) -> list[dict[str, str]]:
    """Recursos fisicos pedidos por la interpretacion que el IOAllocator no pudo resolver."""
    validation = (semantic_output or {}).get("semantic_validation") or {}
    issues = [{"code": ERROR_UNRESOLVED_RESOURCE, "name": str(tag),
               "detail": f"{tag} no tiene binding en el working_io_map del ensayo."}
              for tag in validation.get("unauthorized_tags", []) or []]
    for proposal in validation.get("io_assignment_proposals", []) or []:
        if proposal.get("blocked"):
            issues.append({"code": ERROR_UNRESOLVED_RESOURCE, "name": str(proposal.get("proposed_name") or proposal.get("functional_name_hint")),
                           "detail": str(proposal.get("reason") or "propuesta de asignacion bloqueada")})
    return issues


def verify_program_resources(variables: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    """
    Verifica el programa generado contra el working map congelado del ensayo. No usa case_id ni
    allowed_variables: solo bindings reales, direcciones, tipos y estados LOCKED.
    """
    channels_by_name = {channel.get("functional_name"): channel for channel in snapshot.get("channels", []) or []}
    errors: list[dict[str, str]] = []
    warnings: list[str] = []
    checked: list[str] = []
    for variable in variables or []:
        if not isinstance(variable, dict) or not _is_external(variable):
            continue
        name = str(variable.get("name"))
        checked.append(name)
        channel = channels_by_name.get(name)
        if channel is None:
            errors.append({"code": ERROR_GHOST_RESOURCE, "name": name,
                           "detail": f"{name} ({variable.get('location')}) no existe en el working_io_map del ensayo."})
            continue
        if _normalize_address(channel.get("address")) != _normalize_address(variable.get("location")):
            errors.append({"code": ERROR_GHOST_RESOURCE, "name": name,
                           "detail": f"{name} usa {variable.get('location')} pero su binding real es {channel.get('address')}."})
            continue
        incompatible = _type_compatible(variable, channel)
        if incompatible:
            errors.append({"code": ERROR_TYPE_INCOMPATIBLE, "name": name, "detail": incompatible})
        if not channel.get("bound"):
            warnings.append(f"{name} existe en el working map pero no fue referenciado por la interpretacion.")
    errors.extend(locked_violations(snapshot))
    return {
        "policy": POLICY_WORKING_MAP_BINDING,
        "success": not errors,
        "checked_external_resources": checked,
        "errors": errors,
        "warnings": warnings,
    }
