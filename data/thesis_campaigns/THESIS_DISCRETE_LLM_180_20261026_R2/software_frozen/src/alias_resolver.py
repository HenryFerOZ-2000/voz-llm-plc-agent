from __future__ import annotations

from typing import Any

from utils import build_io_map_index


def build_alias_index(io_map: dict[str, Any]) -> dict[str, str]:
    """Map every normalized alias phrase (plus each tag's own name) to its canonical tag."""
    from semantic_parser import normalize_text

    alias_index: dict[str, str] = {}
    for name, entry in build_io_map_index(io_map).items():
        aliases = entry.get("aliases", [])
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            normalized_alias = normalize_text(str(alias))
            if normalized_alias:
                alias_index[normalized_alias] = name
    return alias_index


def filter_llm_allowed_entries(io_map: dict[str, Any]) -> dict[str, Any]:
    """Return an io_map-shaped dict containing only variables with llm_allowed != False."""
    from utils import iter_io_map_entries

    allowed_variables = [
        entry for entry in iter_io_map_entries(io_map)
        if entry.get("llm_allowed", True) is not False
    ]
    return {**io_map, "variables": allowed_variables}
