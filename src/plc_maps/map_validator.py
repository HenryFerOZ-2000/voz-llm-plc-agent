from __future__ import annotations

from typing import Any

from gui_helpers import ALLOWED_SAFETY_LEVELS, normalize_variable_entry, validate_io_map_variables

NUMERIC_TYPES = {"INT"}
ALWAYS_CRITICAL_TAGS = {"I_Emergency"}


def validate_plc_variable_map(map_payload: dict[str, Any], safety_rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deep-validate a PLCVariableMap payload. Returns {errors, warnings, is_valid}."""
    variables = map_payload.get("variables", [])
    errors = list(validate_io_map_variables(variables))
    warnings: list[str] = []

    normalized = [normalize_variable_entry(entry) for entry in variables]
    critical_tags = set(ALWAYS_CRITICAL_TAGS)
    if safety_rules:
        critical_tags.update(safety_rules.get("critical_outputs", []))

    locations: dict[str, list[str]] = {}
    for entry in normalized:
        location = entry.get("location", "")
        if location:
            locations.setdefault(location, []).append(entry["name"])

    for location, names in locations.items():
        if len(set(names)) > 1:
            errors.append(f"Direccion duplicada {location} asignada a: {', '.join(sorted(set(names)))}.")

    for entry in normalized:
        name = entry["name"]
        if not name:
            continue

        safety_level = entry.get("safety_level", "normal")
        if safety_level not in ALLOWED_SAFETY_LEVELS:
            errors.append(f"{name}: safety_level '{safety_level}' no es valido.")

        if name in critical_tags and safety_level != "critical":
            warnings.append(f"{name} es una senal critica del proyecto pero no tiene safety_level=critical.")

        min_value = entry.get("min")
        max_value = entry.get("max")
        if min_value is not None and max_value is not None and min_value >= max_value:
            errors.append(f"{name}: min ({min_value}) debe ser menor que max ({max_value}).")

        unit = entry.get("unit", "")
        if unit and entry.get("type") not in NUMERIC_TYPES:
            warnings.append(f"{name}: tiene unit '{unit}' pero su tipo '{entry.get('type')}' no es numerico.")

    return {"errors": errors, "warnings": warnings, "is_valid": len(errors) == 0}


def format_validation_report(result: dict[str, Any], variable_count: int) -> str:
    if result["is_valid"] and not result["warnings"]:
        return f"Mapa valido.\n\n{variable_count} variables analizadas.\n0 errores.\n0 advertencias."

    lines = [f"{variable_count} variables analizadas."]
    lines.append(f"{len(result['errors'])} errores.")
    lines.append(f"{len(result['warnings'])} advertencias.")
    if result["errors"]:
        lines.append("\nERRORES:")
        lines.extend(f"- {message}" for message in result["errors"][:12])
    if result["warnings"]:
        lines.append("\nADVERTENCIAS:")
        lines.extend(f"- {message}" for message in result["warnings"][:12])
    return "\n".join(lines)
