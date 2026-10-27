from __future__ import annotations

from pathlib import Path

from utils import load_json_file

VARIANTS_FILENAME = "experiment_variants.json"


def get_variants_path(project_root: Path) -> Path:
    return project_root / "data" / "plc_maps" / VARIANTS_FILENAME


def _catalog_variants(project_root: Path) -> dict[str, list[dict[str, str]]]:
    """Benchmark v2: la fuente de verdad de los comandos es el catalogo canonico."""
    from trial_experiments.benchmark_catalog import VARIANT_IDS, load_catalog

    catalog = load_catalog(project_root)
    return {
        case["case_id"]: [{"variant": vid, "command": case["variants"][vid]} for vid in VARIANT_IDS if vid in case.get("variants", {})]
        for case in catalog.get("cases", [])
    }


def load_all_variants(project_root: Path) -> dict[str, list[dict[str, str]]]:
    catalog = _catalog_variants(project_root)
    if catalog:
        return catalog
    # Compatibilidad: sin catalogo canonico se usa el archivo legacy (derivado del catalogo en v2).
    path = get_variants_path(project_root)
    if not path.exists():
        return {}
    try:
        payload = load_json_file(path)
    except (FileNotFoundError, ValueError):
        return {}
    variants = payload.get("variants", {}) if isinstance(payload, dict) else {}
    return variants if isinstance(variants, dict) else {}


def load_variants_for_case(project_root: Path, case_id: str) -> list[dict[str, str]]:
    return load_all_variants(project_root).get(case_id, [])


def get_variant_command(project_root: Path, case_id: str, variant: str) -> str:
    for entry in load_variants_for_case(project_root, case_id):
        if entry.get("variant") == variant:
            return str(entry.get("command", ""))
    return ""
