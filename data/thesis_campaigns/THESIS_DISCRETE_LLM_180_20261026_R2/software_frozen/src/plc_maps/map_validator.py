from __future__ import annotations

import re
from typing import Any

from gui_helpers import ALLOWED_SAFETY_LEVELS, normalize_variable_entry, validate_io_map_variables
from analog_config import analog_configuration_report
from process_signals import normalize_process_binding, process_configuration_report, validate_process_storage

NUMERIC_TYPES = {"INT", "REAL"}
ALWAYS_CRITICAL_TAGS = {"I_Emergency"}


def _address_span(location: str) -> tuple[str, int, int] | None:
    """Physical bit interval; input, output and memory are independent address areas."""
    match = re.fullmatch(r"%([IQM])(X|B|W|D)?(\d+)(?:\.([0-7]))?", location.upper())
    if not match:
        return None
    area, width, byte, bit = match.groups()
    start = int(byte) * 8
    if bit is not None and width in (None, "X"):
        start += int(bit)
        return area, start, start + 1
    if bit is None and width in {"B", "W", "D"}:
        return area, start, start + {"B": 8, "W": 16, "D": 32}[width]
    return None


def physical_address_errors(variables: list[dict]) -> list[str]:
    """Shared physical memory checks, independent of GUI naming conventions."""
    errors=[];locations={};spans=[]
    for entry in variables:
        location=str(entry.get('location') or '').upper()
        if not location:continue
        name=str(entry.get('name',''))
        for other in locations.get(location,[]):
            if other!=name:errors.append(f'Direccion duplicada {location}: {other}, {name}.')
        locations.setdefault(location,[]).append(name)
        span=_address_span(location)
        if span is None:continue
        for other_name,other_location,previous in spans:
            if location==other_location:continue
            if span[0]==previous[0] and span[1]<previous[2] and previous[1]<span[2]:
                errors.append(f'Solapamiento de direcciones: {other_name} ({other_location}) y {name} ({location}).')
        spans.append((name,location,span))
    return errors


def validate_plc_variable_map(map_payload: dict[str, Any], safety_rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deep-validate a PLCVariableMap payload. Returns {errors, warnings, is_valid}."""
    variables = map_payload.get("variables", [])
    errors = list(validate_io_map_variables(variables))
    warnings: list[str] = []

    normalized = [normalize_variable_entry(entry) for entry in variables]
    for entry in normalized:
        warnings.extend(analog_configuration_report(entry)["warnings"])
    process_bindings = []
    for entry in normalized:
        if 'process_config' in entry and process_configuration_report(entry)['is_valid']:
            # Storage consistency is required even for devices unavailable to the LLM.
            candidate = dict(entry, llm_allowed=True)
            try:
                process_bindings.append(normalize_process_binding(candidate, entry['process_config']['role']))
            except ValueError as error:
                errors.append(str(error))
    errors.extend(validate_process_storage(process_bindings))
    critical_tags = set(ALWAYS_CRITICAL_TAGS)
    if safety_rules:
        critical_tags.update(safety_rules.get("critical_outputs", []))

    errors.extend(physical_address_errors(normalized))

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
