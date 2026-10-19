"""Optional per-channel analog metadata, independent of GUI and map-package imports."""
from __future__ import annotations

import math
import re
from typing import Any
from engineering_units import compatible_unit


SIGNAL_RANGES = {
    "0-10V": (0.0, 10.0), "-10-10V": (-10.0, 10.0),
    "0-20mA": (0.0, 20.0), "4-20mA": (4.0, 20.0),
    "CUSTOM_V": None, "CUSTOM_MA": None,
}
NUMERIC_FIELDS = ("electrical_min", "electrical_max", "raw_min", "raw_max",
                  "engineering_min", "engineering_max", "fault_value")
FIELD_LABELS = {
    "device_name": "dispositivo", "quantity": "magnitud", "signal_type": "señal eléctrica",
    "electrical_min": "mínimo eléctrico", "electrical_max": "máximo eléctrico",
    "raw_min": "mínimo raw", "raw_max": "máximo raw", "engineering_min": "mínimo físico",
    "engineering_max": "máximo físico", "engineering_unit": "unidad física",
    "fault_action": "acción ante señal inválida", "fault_value": "valor ante fallo",
}


def is_analog_channel(entry: dict[str, Any]) -> bool:
    cls = entry.get("class")
    area = "I" if cls == "input" else "Q" if cls == "output" else ""
    return bool(area and entry.get("type") == "INT" and re.fullmatch(
        rf"%{area}W\d+", str(entry.get("location", "")).upper()))


def _finite_number(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def analog_configuration_report(entry: dict[str, Any]) -> dict[str, Any]:
    """Legacy absence is allowed; READY means complete and explicitly confirmed metadata only."""
    result: dict[str, Any] = {"errors": [], "warnings": [], "missing_fields": [], "ready": False}
    if "analog_config" not in entry:
        return result
    errors, warnings, missing = result["errors"], result["warnings"], result["missing_fields"]
    prefix = f"{entry.get('name', 'Canal')}: configuración analógica"
    config = entry["analog_config"]
    if not isinstance(config, dict):
        errors.append(f"{prefix}: debe ser un objeto.")
        return result
    if not is_analog_channel(entry):
        errors.append(f"{prefix}: requiere un canal AI/AO INT con dirección %IW/%QW compatible.")
    if type(config.get("schema_version", 1)) is not int or config.get("schema_version", 1) != 1:
        errors.append(f"{prefix}: versión no admitida.")
    if type(config.get("confirmed", False)) is not bool:
        errors.append(f"{prefix}: confirmed debe ser booleano.")

    required = ["device_name", "quantity", "signal_type", "electrical_min", "electrical_max", "raw_min", "raw_max",
                "engineering_min", "engineering_max", "engineering_unit", "fault_action"]
    for field in ("device_name", "quantity", "engineering_unit"):
        value = config.get(field)
        if value is not None and not isinstance(value, str):
            errors.append(f"{prefix}: {FIELD_LABELS[field]} debe ser texto.")
    quantity, unit = config.get("quantity"), config.get("engineering_unit")
    if isinstance(quantity, str) and isinstance(unit, str) and not compatible_unit(quantity, unit):
        errors.append(f"{prefix}: unidad física {unit!r} incompatible con la magnitud {quantity!r}.")
    device_kind = config.get("device_kind", "PENDING")
    allowed_devices = {"PENDING", "OTHER", "PROPORTIONAL_VALVE", "VARIABLE_SPEED_DRIVE", "OTHER_ACTUATOR"} if entry.get("class") == "output" else {"PENDING", "OTHER", "SENSOR"}
    if not isinstance(device_kind, str) or device_kind not in allowed_devices:
        errors.append(f"{prefix}: tipo de dispositivo incompatible con la dirección del canal.")

    valid_numbers = {}
    for field in NUMERIC_FIELDS:
        value = config.get(field)
        if value is None:
            continue
        if not _finite_number(value):
            errors.append(f"{prefix}: {FIELD_LABELS[field]} debe ser un número finito.")
            continue
        if field.startswith("raw_") and (value != int(value) or not -32768 <= value <= 32767):
            errors.append(f"{prefix}: {FIELD_LABELS[field]} debe ser un entero INT entre -32768 y 32767.")
            continue
        valid_numbers[field] = value
    for domain in ("electrical", "raw", "engineering"):
        low, high = domain + "_min", domain + "_max"
        if low in valid_numbers and high in valid_numbers and valid_numbers[low] >= valid_numbers[high]:
            errors.append(f"{prefix}: {FIELD_LABELS[low]} debe ser menor que {FIELD_LABELS[high]}.")

    signal = config.get("signal_type", "PENDING")
    if not isinstance(signal, str) or signal not in {"PENDING", *SIGNAL_RANGES}:
        errors.append(f"{prefix}: tipo de señal no admitido.")
    elif signal in SIGNAL_RANGES and SIGNAL_RANGES[signal] is not None:
        expected = SIGNAL_RANGES[signal]
        for field, number in zip(("electrical_min", "electrical_max"), expected):
            if field in valid_numbers and valid_numbers[field] != number:
                errors.append(f"{prefix}: {FIELD_LABELS[field]} no coincide con la señal {signal} seleccionada.")

    action = config.get("fault_action", "PENDING")
    actions = {"PENDING", "SAFE_VALUE"} if entry.get("class") == "output" else {
        "PENDING", "INHIBIT_CONTROL", "SUBSTITUTE_VALUE"}
    if not isinstance(action, str) or action not in actions:
        errors.append(f"{prefix}: acción ante fallo incompatible con la dirección del canal.")
    if action in ("SAFE_VALUE", "SUBSTITUTE_VALUE"):
        required.append("fault_value")
    fault = valid_numbers.get("fault_value")
    if fault is not None:
        if ("engineering_min" in valid_numbers and fault < valid_numbers["engineering_min"] or
                "engineering_max" in valid_numbers and fault > valid_numbers["engineering_max"]):
            errors.append(f"{prefix}: valor ante fallo fuera del rango físico.")

    for field in required:
        value = config.get(field)
        if value is None or isinstance(value, str) and (not value.strip() or value == "PENDING"):
            missing.append(field)
    if config.get("confirmed") is True and missing:
        errors.append(f"{prefix}: no se puede confirmar; faltan " + ", ".join(FIELD_LABELS[field] for field in missing) + ".")
    elif not config.get("confirmed", False):
        warnings.append(f"{prefix}: pendiente de completar/confirmar; no habilita escalado ni PID real.")
    result["ready"] = not errors and not missing and config.get("confirmed") is True
    return result
