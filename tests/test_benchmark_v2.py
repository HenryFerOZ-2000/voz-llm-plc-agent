"""
Benchmark experimental v2 como HISTORICO DEVELOPMENT (archivo inmutable).

Desde el benchmark v3 (FORMAL), el v2 vive en data/experiment_benchmark/versions/benchmark_v2/, copiado byte a byte
con manifest de hashes. Este modulo comprueba que ese archivo se conserva intacto y que, por si mismo, sigue siendo
coherente (32 casos, 96 variantes equivalentes, Oracles alineados sin requisitos ocultos ni omitidos, D08 consistente,
D03 v1 congelado), ademas de la preservacion del benchmark v1. El catalogo VIVO (v3) se prueba en test_benchmark_v3.py.
No toca PLCSIM ni los mapas reales.
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

from trial_experiments import benchmark_catalog as BC  # noqa: E402
from trial_experiments import oracle_schema as S  # noqa: E402
from utils import get_project_root  # noqa: E402

_ROOT = get_project_root()
_ARCHIVE = _ROOT / "data" / "experiment_benchmark" / "versions" / "benchmark_v2"
_MAPS = [_ROOT / "data" / "plc_maps" / f"{n}.json" for n in
         ("mapa_banco_fisico_base", "mapa_simulacion_completo", "mapa_pid_simulacion", "mapa_pid_banco_fisico")]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


_MAP_HASHES = {str(p): _hash(p) for p in _MAPS}
MANIFEST = _json(_ARCHIVE / "manifest.json")
CATALOG = _json(_ARCHIVE / "canonical_cases.json")
CASES = {case["case_id"]: case for case in CATALOG["cases"]}


def _oracle(case_id: str) -> dict:
    return _json(_ARCHIVE / "experiment_oracles" / f"{case_id}.json")


# Archivo inmutable -----------------------------------------------------------------------------

def test_v2_archive_bytes_are_intact():
    assert MANIFEST["benchmark_version"] == 2 and MANIFEST["role"] == "HISTORICAL_DEVELOPMENT"
    assert "DEVELOPMENT" in MANIFEST["note"] and "v3" in MANIFEST["note"]
    assert set(MANIFEST["files"]) == set(MANIFEST["raw_sha256"]) == set(MANIFEST["source_paths"])
    for relative, digest in MANIFEST["raw_sha256"].items():
        assert _hash(_ARCHIVE / relative) == digest, relative  # bytes exactos
        assert BC.normalized_file_hash(_ARCHIVE / relative) == MANIFEST["files"][relative], relative
    for required in ("canonical_cases.json", "experiment_variants.json", "profiles.json", "experimental_design.json",
                     "variant_consistency_report.json", "oracle_validation_report.json", "experiment_oracles/D03.json",
                     "experiment_oracles/versions/D03_v1.json"):
        assert required in MANIFEST["files"], required
    assert len([r for r in MANIFEST["files"] if r.startswith("experiment_oracles/") and r.count("/") == 1]) == 32


# 1-3 ------------------------------------------------------------------------------------------

def test_exactly_32_canonical_cases_d01_d20_p01_p12():
    assert CATALOG["benchmark_version"] == 2
    assert list(CASES) == [f"D{i:02d}" for i in range(1, 21)] + [f"P{i:02d}" for i in range(1, 13)]
    for case in CASES.values():
        for key in ("case_id", "title", "complexity", "original_requirement", "canonical_command", "canonical_semantics",
                    "benchmark_version", "command_requirements", "test_harness_setup"):
            assert key in case, (case["case_id"], key)
        assert case["benchmark_version"] == 2
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
    for case in CASES.values():
        entry = BC.variant_consistency(case)
        assert not entry["errors"], (case["case_id"], entry["errors"])
        assert entry["same_numeric_values"] and entry["same_required_roles"] and entry["same_constraints"], case["case_id"]
    report = _json(_ARCHIVE / "variant_consistency_report.json")
    assert report["benchmark_version"] == 2 and report["consistent_variants"] == 96


def test_variant_checker_detects_a_changed_meaning():
    case = dict(CASES["D08"])
    assert BC.check_text(case, "Enciende el motor con Start y apágalo después de 15 segundos de funcionamiento.")["errors"]
    assert BC.check_text(case, "Enciende el motor y apágalo después de 10 segundos.")["errors"]  # falta Start
    assert not BC.check_text(case, case["canonical_command"])["errors"]


# 9 --------------------------------------------------------------------------------------------

def test_d08_is_consistent_everywhere():
    case = CASES["D08"]
    profile = next(p for p in _json(_ARCHIVE / "profiles.json")["profiles"] if p["case_id"] == "D08")
    variants = _json(_ARCHIVE / "experiment_variants.json")["variants"]["D08"]
    oracle = _oracle("D08")
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

def test_archived_profiles_and_variants_match_archived_catalog():
    profiles = {p["case_id"]: p for p in _json(_ARCHIVE / "profiles.json")["profiles"]}
    variants = _json(_ARCHIVE / "experiment_variants.json")["variants"]
    for case_id, case in CASES.items():
        assert profiles[case_id]["description"] == case["canonical_command"]
        assert profiles[case_id]["name"] == f"{case_id} - {case['title']}"
        assert {e["variant"]: e["command"] for e in variants[case_id]} == case["variants"]
        oracle = _oracle(case_id)
        if oracle.get("source_definition"):
            assert oracle["source_definition"]["canonical_case_hash"] == BC.case_hash(case), case_id


@pytest.mark.parametrize("case_id", BC.CASE_IDS)
def test_oracle_has_no_hidden_or_missing_requirements(case_id):
    alignment = BC.canonical_alignment(CASES[case_id], _oracle(case_id))
    assert alignment["extra_oracle_requirements"] == [], alignment["extra_oracle_requirements"]
    assert alignment["missing_oracle_requirements"] == [], alignment["missing_oracle_requirements"]
    assert len(alignment["command_requirements_covered"]) == len(CASES[case_id]["command_requirements"])


def test_alignment_detects_hidden_and_missing_requirements():
    oracle = json.loads(json.dumps(_oracle("D11")))
    oracle["invariants"].append({"id": "INV_EXTRA", "type": "NEVER_TRUE", "roles": ["CONTACTOR"], "severity": "CRITICAL"})
    oracle["test_sequence"] = [s for s in oracle["test_sequence"] if s["id"] != "step_3"]
    alignment = BC.canonical_alignment(CASES["D11"], oracle)
    assert [e["oracle_item"] for e in alignment["extra_oracle_requirements"]] == ["INV_EXTRA"]
    assert [m["requirement"] for m in alignment["missing_oracle_requirements"]] == ["R3"]


def test_harness_setup_is_not_a_semantic_requirement():
    assert "RESET" not in _oracle("D09")["semantic_expectations"]["required_roles"]
    p07 = _oracle("P07")
    assert p07["roles"]["AUTO_MODE"].get("harness_only") and "AUTO_MODE" not in p07["semantic_expectations"]["required_roles"]
    assert CASES["D03"]["test_harness_setup"] and "motor apagado" in CASES["D03"]["test_harness_setup"][0]
    assert "apagado" not in BC.normalize(CASES["D03"]["canonical_command"])


# 13-14 ----------------------------------------------------------------------------------------

def test_frozen_oracles_untouched():
    d03 = _oracle("D03")
    assert d03["approval"]["status"] == "FROZEN" and d03["approval"]["version"] == 1
    assert d03["approval"]["hash"] == S.compute_oracle_hash(d03) == "b444a550d900d61ca67053bfa17cdec706e2149d9d78c0a3790ecf131aa1dc92"
    assert d03["semantic_expectations"]["accepted_intents"] == ["INT_MOTOR_START_STOP"]  # v2: solo START_STOP
    for case_id in ("D03", "D07", "D12"):
        v1 = _json(_ROOT / "data/experiment_oracles/versions" / f"{case_id}_v1.json")
        assert v1["approval"]["status"] == "FROZEN" and v1["approval"]["hash"] == S.compute_oracle_hash(v1)
    for case_id in ("D07", "D12"):  # v2 del Oracle = la vigente en el benchmark v2
        oracle = _oracle(case_id)
        assert oracle["approval"]["version"] == 2
        assert oracle["source_definition"]["canonical_case_hash"] == BC.case_hash(CASES[case_id])
        assert oracle["approval"]["hash"] == S.compute_oracle_hash(oracle)
        assert (_ROOT / "data/experiment_oracles/versions" / f"{case_id}_v2.json").exists()


def test_benchmark_v1_archived_with_hashes():
    base = _ROOT / "data" / "experiment_benchmark" / "versions" / "benchmark_v1"
    manifest = _json(base / "manifest.json")
    assert manifest["benchmark_version"] == 1 and "DEVELOPMENT_TRIAL" in manifest["note"]
    for relative, digest in manifest["files"].items():
        assert BC.normalized_file_hash(base / relative) == digest, relative
    legacy = _json(base / "experiment_variants.json")["variants"]["D08"]
    assert any("paro" in BC.normalize(v["command"]) for v in legacy)  # el texto legacy queda como evidencia


# 17 -------------------------------------------------------------------------------------------

def test_real_maps_unchanged():
    for path in _MAPS:
        assert _hash(path) == _MAP_HASHES[str(path)]
