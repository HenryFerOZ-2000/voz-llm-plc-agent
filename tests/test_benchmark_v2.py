"""
Benchmark experimental v2: comandos canonicos como fuente unica de verdad.

Comprueba el catalogo (32 casos, 96 variantes equivalentes), la sincronizacion de profiles.json y
experiment_variants.json, la alineacion Oracle <-> comando (sin requisitos ocultos ni omitidos), la
consistencia completa de D08, la preservacion de los Oracles congelados y del benchmark v1, y que la
GUI y los ensayos usan el catalogo nuevo. No toca PLCSIM ni los mapas reales.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402
from trial_experiments import benchmark_catalog as BC  # noqa: E402
from trial_experiments import oracle_schema as S  # noqa: E402
from trial_experiments import trial_model  # noqa: E402
from utils import get_project_root  # noqa: E402

from test_phase1_download_and_trials import _arm_experiment_trial, pipeline  # noqa: E402
from test_execute_full_pipeline import temp_map, _tia_ready  # noqa: E402

__all__ = ["pipeline", "temp_map", "_tia_ready"]

_ROOT = get_project_root()
_MAPS = [_ROOT / "data" / "plc_maps" / f"{n}.json" for n in
         ("mapa_banco_fisico", "mapa_simulacion_completo", "mapa_pid_simulacion", "mapa_pid_banco_fisico")]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_MAP_HASHES = {str(p): _hash(p) for p in _MAPS}
CATALOG = BC.load_catalog(_ROOT)
CASES = {case["case_id"]: case for case in CATALOG["cases"]}


def _oracles():
    return {case_id: S.load_oracle(_ROOT, case_id) for case_id in BC.CASE_IDS}


# 1-3 ------------------------------------------------------------------------------------------

def test_exactly_32_canonical_cases_d01_d20_p01_p12():
    assert CATALOG["benchmark_version"] == 2
    assert list(CASES) == [f"D{i:02d}" for i in range(1, 21)] + [f"P{i:02d}" for i in range(1, 13)]
    for case in CASES.values():
        for key in ("case_id", "title", "complexity", "original_requirement", "canonical_command", "canonical_semantics",
                    "benchmark_version", "command_requirements", "test_harness_setup"):
            assert key in case, (case["case_id"], key)
        assert case["canonical_semantics"]["signature"] and case["command_requirements"]


# 4-8 ------------------------------------------------------------------------------------------

def test_exactly_96_variants_three_per_case_all_distinct():
    assert sum(len(case["variants"]) for case in CASES.values()) == 96
    for case in CASES.values():
        assert list(case["variants"]) == ["V1", "V2", "V3"]
        assert len(set(case["variants"].values())) == 3


def test_no_variant_uses_physical_addresses_or_tag_names():
    for case in CASES.values():
        for text in [case["canonical_command"], *case["variants"].values()]:
            assert not re.search(r"%\s*[IQM]\s*[XBWD]?\s*\d", text), (case["case_id"], text)
            assert not re.search(r"\b[IQM]_[A-Za-z]", text), (case["case_id"], text)


def test_variant_numeric_values_and_concepts_match_canonical():
    report = BC.build_variant_consistency_report(_ROOT)
    assert report["total_variants"] == 96 and report["consistent_variants"] == 96, report["cases_with_errors"]
    for entry in report["cases"]:
        assert entry["same_numeric_values"] and entry["same_required_roles"] and entry["same_constraints"], entry["case_id"]
        for vid in ("V1", "V2", "V3"):
            assert entry[vid]["numbers"] == entry["canonical_check"]["numbers"], (entry["case_id"], vid)
    written = json.loads((_ROOT / "data" / "variant_consistency_report.json").read_text(encoding="utf-8"))
    assert written["consistent_variants"] == 96


def test_variant_checker_detects_a_changed_meaning():
    case = dict(CASES["D08"])
    assert BC.check_text(case, "Enciende el motor con Start y apágalo después de 15 segundos de funcionamiento.")["errors"]
    assert BC.check_text(case, "Enciende el motor y apágalo después de 10 segundos.")["errors"]  # falta Start
    assert not BC.check_text(case, case["canonical_command"])["errors"]


# 9 --------------------------------------------------------------------------------------------

def test_d08_is_consistent_everywhere():
    case = CASES["D08"]
    profile = next(p for p in json.loads((_ROOT / "data/plc_maps/profiles.json").read_text(encoding="utf-8"))["profiles"]
                   if p["case_id"] == "D08")
    variants = json.loads((_ROOT / "data/plc_maps/experiment_variants.json").read_text(encoding="utf-8"))["variants"]["D08"]
    oracle = S.load_oracle(_ROOT, "D08")
    texts = [case["canonical_command"], profile["description"], *[v["command"] for v in variants], *case["variants"].values(),
             oracle["source_definition"]["canonical_command"], oracle["description"]]
    for text in texts:
        normalized = BC.normalize(text)
        assert "start" in normalized and "10" in normalized, text
        assert not re.search(r"\bstop\b|presionar el paro|despues de presionar", normalized), text
    assert profile["reference_intent"] == "INT_AUTO_STOP_TIMER"
    assert case["canonical_semantics"]["signature"]["times"] == {"operation_duration_s": 10}
    assert oracle["test_sequence"][1]["measure_transition"]["nominal_ms"] == 10000
    assert "STOP" not in oracle["roles"]


# 10-12 ----------------------------------------------------------------------------------------

def test_profiles_and_variants_file_match_catalog_and_zero_inconsistencies():
    assert BC.benchmark_inconsistencies(_ROOT, _oracles()) == []
    profiles = {p["case_id"]: p for p in json.loads((_ROOT / "data/plc_maps/profiles.json").read_text(encoding="utf-8"))["profiles"]}
    for case_id, case in CASES.items():
        assert profiles[case_id]["description"] == case["canonical_command"]
        assert profiles[case_id]["name"] == f"{case_id} - {case['title']}"
        assert "allowed_variables" in profiles[case_id]  # metadata historica conservada


@pytest.mark.parametrize("case_id", BC.CASE_IDS)
def test_oracle_has_no_hidden_or_missing_requirements(case_id):
    alignment = BC.canonical_alignment(CASES[case_id], S.load_oracle(_ROOT, case_id))
    assert alignment["extra_oracle_requirements"] == [], alignment["extra_oracle_requirements"]
    assert alignment["missing_oracle_requirements"] == [], alignment["missing_oracle_requirements"]
    assert len(alignment["command_requirements_covered"]) == len(CASES[case_id]["command_requirements"])


def test_alignment_detects_hidden_and_missing_requirements():
    oracle = json.loads(json.dumps(S.load_oracle(_ROOT, "D11")))
    oracle["invariants"].append({"id": "INV_EXTRA", "type": "NEVER_TRUE", "roles": ["CONTACTOR"], "severity": "CRITICAL"})
    oracle["test_sequence"] = [s for s in oracle["test_sequence"] if s["id"] != "step_3"]
    alignment = BC.canonical_alignment(CASES["D11"], oracle)
    assert [e["oracle_item"] for e in alignment["extra_oracle_requirements"]] == ["INV_EXTRA"]
    assert [m["requirement"] for m in alignment["missing_oracle_requirements"]] == ["R3"]


def test_harness_setup_is_not_a_semantic_requirement():
    assert "RESET" not in S.load_oracle(_ROOT, "D09")["semantic_expectations"]["required_roles"]
    p07 = S.load_oracle(_ROOT, "P07")
    assert p07["roles"]["AUTO_MODE"].get("harness_only") and "AUTO_MODE" not in p07["semantic_expectations"]["required_roles"]
    assert CASES["D03"]["test_harness_setup"] and "motor apagado" in CASES["D03"]["test_harness_setup"][0]
    assert "apagado" not in BC.normalize(CASES["D03"]["canonical_command"])


# 13-14 ----------------------------------------------------------------------------------------

def test_frozen_oracles_untouched():
    d03 = S.load_oracle(_ROOT, "D03")
    assert d03["approval"]["status"] == "FROZEN" and d03["approval"]["version"] == 1
    assert d03["approval"]["hash"] == S.compute_oracle_hash(d03) == "b444a550d900d61ca67053bfa17cdec706e2149d9d78c0a3790ecf131aa1dc92"
    for case_id in ("D03", "D07", "D12"):
        v1 = json.loads((_ROOT / "data/experiment_oracles/versions" / f"{case_id}_v1.json").read_text(encoding="utf-8"))
        assert v1["approval"]["status"] == "FROZEN" and v1["approval"]["hash"] == S.compute_oracle_hash(v1)
    for case_id in ("D07", "D12"):  # v2 (borrador) coincide con el comando canonico
        oracle = S.load_oracle(_ROOT, case_id)
        assert oracle["approval"]["version"] == 2 and not S.is_formal(oracle)
        assert oracle["source_definition"]["canonical_case_hash"] == BC.case_hash(CASES[case_id])


def test_benchmark_v1_archived_with_hashes():
    base = _ROOT / "data" / "experiment_benchmark" / "versions" / "benchmark_v1"
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["benchmark_version"] == 1 and "DEVELOPMENT_TRIAL" in manifest["note"]
    for relative, digest in manifest["files"].items():
        assert _hash(base / relative) == digest, relative
    legacy = json.loads((base / "experiment_variants.json").read_text(encoding="utf-8"))["variants"]["D08"]
    assert any("paro" in BC.normalize(v["command"]) for v in legacy)  # el texto legacy queda como evidencia


# 15-16 ----------------------------------------------------------------------------------------

def test_gui_loads_variants_from_canonical_catalog(app):
    app.experiment_group_var.set("Discreto D01-D20")
    app._refresh_experiment_case_selector()
    name = f"D08 - {CASES['D08']['title']}"
    assert name in app._experiment_profiles_by_case
    app.experiment_case_var.set(name)
    app._on_experiment_case_changed()
    app.experiment_variant_var.set("V2")
    app._update_variant_command_preview()
    assert app._active_variant_command_text == CASES["D08"]["variants"]["V2"]
    app.active_profile_id = None


def test_new_trial_records_benchmark_version_and_hashes(pipeline):
    app = pipeline["app"]
    directory = _arm_experiment_trial(app)  # caso D12, variante V2
    record = trial_model.load_trial(directory)
    assert record["benchmark_version"] == 2
    assert record["canonical_case_hash"] == BC.case_hash(CASES["D12"])
    assert record["variant_hash"] == BC.variant_hash(CASES["D12"]["variants"]["V2"])
    legacy = trial_model.new_trial_record("D12", "V1", "TEXT", 1)
    assert legacy["benchmark_version"] is None  # ensayos sin benchmark_version = benchmark legacy (desarrollo)


# 17 -------------------------------------------------------------------------------------------

def test_real_maps_unchanged():
    for path in _MAPS:
        assert _hash(path) == _MAP_HASHES[str(path)]
