from __future__ import annotations

import pytest

from analog_config import analog_configuration_report
from test_analog_configuration import configured_channel
from engineering_units import convert_unit


@pytest.mark.parametrize("quantity,unit", [("Nivel", "bar"), ("Presión", "cm"), ("Temperatura", "%"),
                                          ("Caudal", "L"), ("Apertura", "rpm")])
def test_known_magnitude_rejects_incompatible_unit(quantity, unit):
    entry = configured_channel()
    entry["analog_config"].update(quantity=quantity, engineering_unit=unit)
    assert analog_configuration_report(entry)["errors"]


def test_custom_magnitude_and_unit_remain_supported():
    entry = configured_channel()
    entry["analog_config"].update(quantity="Conductividad", engineering_unit="mS/cm")
    assert analog_configuration_report(entry)["ready"]


@pytest.mark.parametrize("kind", ["PROPORTIONAL_VALVE", "VARIABLE_SPEED_DRIVE"])
def test_sensor_input_rejects_output_device_category(kind):
    entry = configured_channel()
    entry["analog_config"]["device_kind"] = kind
    assert analog_configuration_report(entry)["errors"]


def test_output_rejects_sensor_category():
    entry = configured_channel(output=True)
    entry["analog_config"]["device_kind"] = "SENSOR"
    assert analog_configuration_report(entry)["errors"]


@pytest.mark.parametrize("value,source,target,expected", [
    (200, "cm", "m", 2), (1, "m³", "L", 1000), (60, "L/min", "m³/h", 3.6),
    (1, "bar", "kPa", 100), (1, "psi", "Pa", 6894.757293168),
    (0, "°C", "°F", 32), (212, "°F", "°C", 100), (0, "°C", "K", 273.15),
    (1000, "mA", "A", 1), (1, "m3/h", "L/h", 1000),
])
def test_physical_unit_conversions(value, source, target, expected):
    assert convert_unit(value, source, target) == pytest.approx(expected)


@pytest.mark.parametrize("source,target", [("%", "cm"), ("L", "m"), ("gal", "L"), ("rpm", "Hz")])
def test_no_conversion_is_invented_for_calibration_or_unknown_units(source, target):
    with pytest.raises(ValueError):
        convert_unit(100, source, target)
