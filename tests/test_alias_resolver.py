from __future__ import annotations

from alias_resolver import build_alias_index, filter_llm_allowed_entries
from semantic_parser import extract_tags, normalize_text, parse_command

CUSTOM_ALIAS = "palanca esmeralda"


def _io_map_with_alias(io_map: dict, tag_name: str, alias: str) -> dict:
    return {
        "naming_convention": io_map.get("naming_convention", {}),
        "variables": [
            {**variable, "aliases": [alias]} if variable.get("name") == tag_name else variable
            for variable in io_map.get("variables", [])
        ]
    }


def test_build_alias_index_maps_normalized_alias_to_canonical_tag(io_map: dict) -> None:
    aliased_map = _io_map_with_alias(io_map, "I_Start", CUSTOM_ALIAS)
    alias_index = build_alias_index(aliased_map)
    assert alias_index.get(normalize_text(CUSTOM_ALIAS)) == "I_Start"


def test_extract_tags_resolves_natural_language_alias(io_map: dict) -> None:
    aliased_map = _io_map_with_alias(io_map, "I_Start", CUSTOM_ALIAS)
    alias_index = build_alias_index(aliased_map)
    tags = extract_tags(f"Activa el sistema usando la {CUSTOM_ALIAS}", alias_index=alias_index)
    assert tags.get("start") == "I_Start"


def test_extract_tags_without_alias_index_is_unaffected() -> None:
    tags = extract_tags(f"Activa el sistema usando la {CUSTOM_ALIAS}")
    assert "start" not in tags


def test_parse_command_accepts_alias_index_and_stays_backward_compatible(io_map: dict) -> None:
    aliased_map = _io_map_with_alias(io_map, "I_Start", CUSTOM_ALIAS)
    alias_index = build_alias_index(aliased_map)
    result = parse_command(f"Activa el motor con la {CUSTOM_ALIAS} y detenlo con Stop", alias_index=alias_index)
    assert "I_Start" in result["recognized_tags"]


def test_filter_llm_allowed_entries_excludes_disallowed_variables(io_map: dict) -> None:
    restricted_map = {
        "naming_convention": io_map.get("naming_convention", {}),
        "variables": [
            {**variable, "llm_allowed": False} if variable.get("name") == "I_Maintenance" else variable
            for variable in io_map.get("variables", [])
        ]
    }
    filtered = filter_llm_allowed_entries(restricted_map)
    names = {entry["name"] for entry in filtered["variables"]}
    assert "I_Maintenance" not in names
    assert "I_Start" in names
