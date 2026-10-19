"""Engineering quantity catalog and conversions; electrical/raw ranges are independent."""
from __future__ import annotations

import math
import unicodedata


QUANTITY_UNITS = {
    "Nivel": ("%", "mm", "cm", "m", "in", "ft"),
    "Distancia": ("mm", "cm", "m", "in", "ft"),
    "Volumen": ("mL", "L", "m³"),
    "Caudal": ("mL/min", "L/min", "L/h", "m³/h", "m³/s"),
    "Presión": ("Pa", "kPa", "MPa", "bar", "mbar", "psi"),
    "Temperatura": ("°C", "°F", "K"),
    "Apertura": ("%",),
    "Velocidad de giro": ("rpm",),
    "Frecuencia": ("Hz", "kHz"),
    "Voltaje": ("mV", "V"),
    "Corriente": ("µA", "mA", "A"),
    "Masa": ("g", "kg", "t"),
    "Fuerza": ("N", "kN"),
    "Potencia": ("W", "kW"),
}


def _fold(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)).strip().casefold()


_QUANTITY_ALIASES = {_fold(label): label for label in QUANTITY_UNITS}
_QUANTITY_ALIASES.update(dict(zip(
    ("level", "distance", "length", "longitud", "volume", "flow", "flujo", "pressure", "temperature",
     "opening", "apertura de valvula", "rotational_speed", "rotational speed", "frequency", "voltage", "tension",
     "current", "mass", "force", "power"),
    ("Nivel", "Distancia", "Distancia", "Distancia", "Volumen", "Caudal", "Caudal", "Presión", "Temperatura",
     "Apertura", "Apertura", "Velocidad de giro", "Velocidad de giro", "Frecuencia", "Voltaje", "Voltaje",
     "Corriente", "Masa", "Fuerza", "Potencia"),
)))
_UNIT_ALIASES = {"m3": "m³", "m3/h": "m³/h", "m3/s": "m³/s", "uA": "µA", "μA": "µA",
                 "degC": "°C", "degF": "°F", "percent": "%", "porcentaje": "%", "RPM": "rpm"}

# family, scale, offset: base_value = value * scale + offset.
_UNITS = {
    "%": ("percentage", 1.0, 0.0),
    "mm": ("length", .001, 0.0), "cm": ("length", .01, 0.0), "m": ("length", 1.0, 0.0),
    "in": ("length", .0254, 0.0), "ft": ("length", .3048, 0.0),
    "mL": ("volume", .000001, 0.0), "L": ("volume", .001, 0.0), "m³": ("volume", 1.0, 0.0),
    "mL/min": ("flow", .000001 / 60, 0.0), "L/min": ("flow", .001 / 60, 0.0),
    "L/h": ("flow", .001 / 3600, 0.0), "m³/h": ("flow", 1 / 3600, 0.0), "m³/s": ("flow", 1.0, 0.0),
    "Pa": ("pressure", 1.0, 0.0), "kPa": ("pressure", 1000.0, 0.0), "MPa": ("pressure", 1e6, 0.0),
    "bar": ("pressure", 1e5, 0.0), "mbar": ("pressure", 100.0, 0.0),
    "psi": ("pressure", .45359237 * 9.80665 / .0254 ** 2, 0.0),
    "°C": ("temperature", 1.0, 273.15), "°F": ("temperature", 5 / 9, 273.15 - 32 * 5 / 9),
    "K": ("temperature", 1.0, 0.0), "rpm": ("rotation", 1.0, 0.0),
    "Hz": ("frequency", 1.0, 0.0), "kHz": ("frequency", 1000.0, 0.0),
    "mV": ("voltage", .001, 0.0), "V": ("voltage", 1.0, 0.0),
    "µA": ("current", .000001, 0.0), "mA": ("current", .001, 0.0), "A": ("current", 1.0, 0.0),
    "g": ("mass", .001, 0.0), "kg": ("mass", 1.0, 0.0), "t": ("mass", 1000.0, 0.0),
    "N": ("force", 1.0, 0.0), "kN": ("force", 1000.0, 0.0),
    "W": ("power", 1.0, 0.0), "kW": ("power", 1000.0, 0.0),
}


def quantity_label(value: str) -> str | None:
    return _QUANTITY_ALIASES.get(_fold(value))


def canonical_unit(value: str) -> str:
    value = value.strip()
    return _UNIT_ALIASES.get(value, value)


def compatible_unit(quantity: str, unit: str) -> bool:
    label, unit = quantity_label(quantity), canonical_unit(unit)
    # Unlisted quantities/units are extensible custom metadata, never inferred conversions.
    return label is None or unit not in _UNITS or unit in QUANTITY_UNITS[label]


def convert_unit(value: float, source: str, target: str) -> float:
    source, target = canonical_unit(source), canonical_unit(target)
    if source not in _UNITS or target not in _UNITS or _UNITS[source][0] != _UNITS[target][0]:
        raise ValueError("Las unidades requieren una calibración nueva; no tienen conversión directa.")
    _, source_scale, source_offset = _UNITS[source]
    _, target_scale, target_offset = _UNITS[target]
    converted = (value * source_scale + source_offset - target_offset) / target_scale
    if not math.isfinite(value) or not math.isfinite(converted):
        raise ValueError("La conversión debe producir valores finitos.")
    return converted
