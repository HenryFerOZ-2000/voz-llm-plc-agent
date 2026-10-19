from __future__ import annotations

import copy

import pytest

from gui_helpers import load_io_map_variables, normalize_variable_entry
from plc_maps.map_validator import validate_plc_variable_map
from plc_maps.store import save_plc_map
from analog_config import analog_configuration_report


def configured_channel(output=False):
    return {
        "name": "AO_Valve" if output else "AI_Level", "class": "output" if output else "input",
        "type": "INT", "location": "%QW4" if output else "%IW4", "state": "ASSIGNED",
        "unit": "mA", "analog_config": {
            "schema_version": 1, "confirmed": True, "device_name": "Valve" if output else "Level transmitter",
            "quantity": "Opening" if output else "Level", "signal_type": "4-20mA",
            "electrical_min": 4.0, "electrical_max": 20.0,
            "raw_min": 0, "raw_max": 27648, "engineering_min": 0.0, "engineering_max": 100.0,
            "engineering_unit": "%", "fault_action": "SAFE_VALUE" if output else "INHIBIT_CONTROL",
            "fault_value": 0.0 if output else None,
        },
    }


@pytest.mark.parametrize("field,value", [
    ("raw_max", 0), ("raw_max", 40000), ("raw_min", 0.5),
    ("engineering_max", 0), ("engineering_min", float("nan")),
    ("electrical_min", 0), ("signal_type", "unknown"),
    ("fault_action", "IGNORE"), ("confirmed", "true"), ("schema_version", 99),
])
def test_map_rejects_invalid_analog_configuration(field, value):
    entry = configured_channel()
    entry["analog_config"][field] = value
    result = validate_plc_variable_map({"variables": [entry]})
    assert not result["is_valid"]
    assert result["errors"] and all("AI_Level" in error for error in result["errors"])


def test_confirmed_configuration_requires_all_physical_details():
    entry = configured_channel()
    entry["analog_config"]["raw_max"] = None
    result = validate_plc_variable_map({"variables": [entry]})
    assert not result["is_valid"]


def test_pending_configuration_can_be_saved_without_inventing_hardware_ranges():
    entry = configured_channel()
    entry["analog_config"].update(confirmed=False, raw_min=None, raw_max=None)
    result = validate_plc_variable_map({"variables": [entry]})
    assert result["is_valid"]
    assert any("pendiente" in warning.lower() for warning in result["warnings"])


def test_valid_input_and_output_are_accepted_and_preserved(tmp_path):
    path = tmp_path / "map.json"
    variables = [configured_channel(), configured_channel(output=True)]
    assert validate_plc_variable_map({"variables": variables})["is_valid"]
    save_plc_map(path, variables)
    loaded = load_io_map_variables(path)
    assert [v["analog_config"] for v in loaded] == [v["analog_config"] for v in variables]
    loaded[0]["analog_config"]["raw_max"] = 1
    assert variables[0]["analog_config"]["raw_max"] == 27648


def test_normalization_does_not_alias_or_remove_analog_configuration():
    original = configured_channel()
    normalized = normalize_variable_entry(original)
    assert normalized["analog_config"] == original["analog_config"]
    normalized["analog_config"]["device_name"] = "Changed"
    assert original["analog_config"]["device_name"] != "Changed"


@pytest.mark.parametrize("action,value", [("SAFE_VALUE", None), ("SAFE_VALUE", -1), ("SAFE_VALUE", 101),
                                         ("INHIBIT_CONTROL", None)])
def test_output_requires_a_safe_value_within_its_physical_range(action, value):
    entry = configured_channel(output=True)
    entry["analog_config"].update(fault_action=action, fault_value=value)
    assert not validate_plc_variable_map({"variables": [entry]})["is_valid"]


def test_input_substitution_requires_a_valid_physical_value():
    entry = configured_channel()
    entry["analog_config"].update(fault_action="SUBSTITUTE_VALUE", fault_value=150)
    assert not validate_plc_variable_map({"variables": [entry]})["is_valid"]


def test_analog_configuration_is_rejected_on_digital_channel():
    entry = configured_channel()
    entry.update(name="I_Level", type="BOOL", location="%IX16.0")
    assert not validate_plc_variable_map({"variables": [entry]})["is_valid"]


def test_legacy_maps_remain_valid_and_unchanged():
    entry = configured_channel()
    del entry["analog_config"]
    before = copy.deepcopy(entry)
    assert validate_plc_variable_map({"variables": [entry]})["is_valid"]
    assert entry == before
    assert "analog_config" not in normalize_variable_entry(entry)


def test_unconfirmed_but_incoherent_ranges_are_still_rejected():
    entry = configured_channel()
    entry["analog_config"].update(confirmed=False, raw_min=100, raw_max=0)
    assert not validate_plc_variable_map({"variables": [entry]})["is_valid"]


def test_changing_program_preserves_channel_configuration():
    import normal_program_bindings as bindings
    entry = configured_channel()
    entry["assignment_source"] = "AUTO"
    working, _ = bindings.release_auto_bindings({"variables": [entry]})
    assert working["variables"][0]["state"] == "FREE"
    assert working["variables"][0]["analog_config"] == entry["analog_config"]


@pytest.mark.parametrize("confirmed", [True, False])
def test_readiness_requires_explicit_confirmation(confirmed):
    entry = configured_channel()
    entry["analog_config"]["confirmed"] = confirmed
    report = analog_configuration_report(entry)
    assert not report["errors"]
    assert report["ready"] is confirmed


def test_missing_configuration_never_claims_readiness():
    entry = configured_channel()
    del entry["analog_config"]
    assert not analog_configuration_report(entry)["ready"]


def test_bipolar_raw_and_physical_ranges_are_allowed():
    entry = configured_channel()
    entry["analog_config"].update(signal_type="-10-10V", electrical_min=-10.0, electrical_max=10.0,
                                 raw_min=-27648, raw_max=27648, engineering_min=-50, engineering_max=150)
    assert analog_configuration_report(entry)["ready"]
