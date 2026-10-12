"""
Benchmark experimental v3 (FORMAL), construido por scripts/build_benchmark_v3.py a partir del v2 (historico DEVELOPMENT).

Comprueba: 32 casos y 96 variantes consistentes; los 16 textos aprobados exactamente; casos sin cambio de texto
identicos al v2; hashes canonicos y Oracles re-versionados (32/32 alineados, sin requisitos ocultos); Oracles
funcionalmente IDENTICOS al v2 salvo metadata y la semantica de D03; P07/P11 con sus precondiciones explicitas; P03 en
0-100 %; diseno experimental apuntando a v3 sin destruir el v2; mapas fisico y de simulacion intactos y separados.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402,F401
from trial_experiments import benchmark_catalog as BC  # noqa: E402
from trial_experiments import experimental_design as ED  # noqa: E402
from trial_experiments import oracle_review as OR  # noqa: E402
from trial_experiments import oracle_schema as S  # noqa: E402
from trial_experiments import trial_model  # noqa: E402
from utils import get_project_root  # noqa: E402

from test_phase1_download_and_trials import _arm_experiment_trial, pipeline  # noqa: E402
from test_execute_full_pipeline import temp_map, _tia_ready  # noqa: E402

__all__ = ["pipeline", "temp_map", "_tia_ready"]

_ROOT = get_project_root()
_ARCHIVE = _ROOT / "data" / "experiment_benchmark" / "versions" / "benchmark_v2"
_SPEC = importlib.util.spec_from_file_location("build_benchmark_v3", _ROOT / "scripts" / "build_benchmark_v3.py")
BUILD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(BUILD)

CHANGED = ["D05", "D08", "D13", "D15", "D17", "D19", "P01", "P04", "P05", "P06", "P07", "P08", "P09", "P10", "P11", "P12"]
_FUNCTIONAL = ("roles", "preconditions", "test_sequence", "invariants", "cleanup", "evaluation", "runtime_support",
               "runtime_requirements", "resource_expectations", "review_items")


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


CATALOG = BC.load_catalog(_ROOT)
CASES = {case["case_id"]: case for case in CATALOG["cases"]}
V2 = {case["case_id"]: case for case in _json(_ARCHIVE / "canonical_cases.json")["cases"]}


def _v2_oracle(case_id: str) -> dict:
    return _json(_ARCHIVE / "experiment_oracles" / f"{case_id}.json")


# Estructura y consistencia ---------------------------------------------------------------------

def test_v3_has_32_cases_all_at_version_3():
    assert CATALOG["benchmark_version"] == 3
    assert list(CASES) == [f"D{i:02d}" for i in range(1, 21)] + [f"P{i:02d}" for i in range(1, 13)]
    assert all(case["benchmark_version"] == 3 for case in CASES.values())
    assert "v3" in CATALOG["methodology_note"] and "ANTES de los ensayos formales" in CATALOG["methodology_note"]


def test_v3_has_96_distinct_consistent_variants():
    assert sum(len(c["variants"]) for c in CASES.values()) == 96
    assert all(list(c["variants"]) == ["V1", "V2", "V3"] and len(set(c["variants"].values())) == 3 for c in CASES.values())
    report = BC.build_variant_consistency_report(_ROOT)
    assert report["benchmark_version"] == 3 and report["consistent_variants"] == 96 and not report["cases_with_errors"]
    for entry in report["cases"]:
        assert entry["same_numeric_values"] and entry["same_required_roles"] and entry["same_constraints"], entry["case_id"]
    assert _json(_ROOT / "data" / "variant_consistency_report.json")["consistent_variants"] == 96


def test_no_v3_text_uses_addresses_or_internal_tag_names():
    for case in CASES.values():
        for text in [case["canonical_command"], *case["variants"].values()]:
            assert not re.search(r"%\s*[IQM]\s*[XBWD]?\s*\d", text), (case["case_id"], text)
            assert not re.search(r"\b[IQM]_[A-Za-z]|Level_PV|Auto_Mode|PID_Enable|MODE_AUTO", text), (case["case_id"], text)


# Textos ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("case_id", CHANGED)
def test_approved_v3_texts_exactly(case_id):
    change = BUILD.CHANGES[case_id]
    assert CASES[case_id]["canonical_command"] == change["canonical"]
    assert CASES[case_id]["variants"] == {vid: change[vid] for vid in ("V1", "V2", "V3")}
    assert CASES[case_id]["canonical_command"] != V2[case_id]["canonical_command"]


def test_exactly_16_cases_change_text_and_the_rest_keep_v2_text():
    assert sorted(BUILD.CHANGES) == sorted(CHANGED)
    for case_id, case in CASES.items():
        same = case["canonical_command"] == V2[case_id]["canonical_command"] and case["variants"] == V2[case_id]["variants"]
        assert same is (case_id not in CHANGED), case_id


def test_p07_and_p11_commands_state_their_preconditions():
    p07, p11 = CASES["P07"], CASES["P11"]
    for text in [p07["canonical_command"], *p07["variants"].values()]:
        normalized = BC.normalize(text)
        assert "automatic" in normalized and "habilit" in normalized and "emergencia" in normalized, text
    assert p07["command_requirements"][0] == {"id": "R0", "text": "En Automatico, sin emergencia, el PID esta habilitado.",
                                              "oracle_evidence": ["pre_enabled"]}
    for text in [p11["canonical_command"], *p11["variants"].values()]:
        normalized = BC.normalize(text)
        assert re.search(r"normal", normalized) and re.search(r"marcha|funciona|trabaje", normalized), text
    assert p11["command_requirements"][0]["oracle_evidence"] == ["pre_normal"]
    # Los Oracles NO se relajan: las precondiciones siguen exigiendo lo mismo que en v2.
    assert S.load_oracle(_ROOT, "P07")["preconditions"] == _v2_oracle("P07")["preconditions"]
    assert S.load_oracle(_ROOT, "P11")["preconditions"] == _v2_oracle("P11")["preconditions"]


def test_p03_stays_0_100_and_unchanged():
    p03 = CASES["P03"]
    assert p03["canonical_command"] == V2["P03"]["canonical_command"] and p03["variants"] == V2["P03"]["variants"]
    assert p03["variant_check"]["numbers"] == [0, 100]
    invariant = next(i for i in S.load_oracle(_ROOT, "P03")["invariants"] if i["id"] == "INV_SP_RANGE")
    assert (invariant["min"], invariant["max"]) == (0.0, 100.0)


def test_functional_names_unified_with_oracles_in_metadata_only():
    for case_id, names in BUILD.FUNCTION_NAMES.items():
        assert CASES[case_id]["canonical_semantics"]["signature"]["functions"] == names
        assert names == S.load_oracle(_ROOT, case_id)["semantic_expectations"]["required_functions"]


# Hashes, Oracles y alineacion ------------------------------------------------------------------

@pytest.mark.parametrize("case_id", BC.CASE_IDS)
def test_oracle_is_a_new_frozen_version_referencing_the_v3_hash(case_id):
    oracle, previous = S.load_oracle(_ROOT, case_id), _v2_oracle(case_id)
    approval = oracle["approval"]
    assert approval["status"] == "FROZEN" and approval["hash"] == S.compute_oracle_hash(oracle)
    assert approval["version"] == previous["approval"]["version"] + 1
    assert approval["previous_hash"] == previous["approval"]["hash"]
    assert approval["approved_by"] == "Henry Ochoa" and approval["benchmark_version"] == 3
    archived = _json(_ROOT / "data" / "experiment_oracles" / "versions" / f"{case_id}_v{previous['approval']['version']}.json")
    assert S.compute_oracle_hash(archived) == previous["approval"]["hash"]  # la version previa sigue intacta
    source = oracle["source_definition"]
    assert source["benchmark_version"] == 3 and source["canonical_case_hash"] == BC.case_hash(CASES[case_id])
    assert source["canonical_command"] == CASES[case_id]["canonical_command"]


@pytest.mark.parametrize("case_id", BC.CASE_IDS)
def test_oracles_are_functionally_identical_to_v2(case_id):
    oracle, previous = S.load_oracle(_ROOT, case_id), _v2_oracle(case_id)
    for key in _FUNCTIONAL:
        assert oracle.get(key) == previous.get(key), (case_id, key)
    differing = {k for k in set(oracle) | set(previous) if oracle.get(k) != previous.get(k)}
    allowed = {"approval", "source_definition", "experimental_conventions"} | ({"semantic_expectations"} if case_id == "D03" else set())
    assert differing <= allowed, (case_id, differing - allowed)
    changed_conventions = {a["id"] for a, b in zip(previous.get("experimental_conventions") or [], oracle.get("experimental_conventions") or [])
                           if a != b}
    assert changed_conventions <= {"CMD-CANONICAL", "C-D20-DURATION"}, (case_id, changed_conventions)
    if case_id != "D03":
        assert oracle["semantic_expectations"] == previous["semantic_expectations"]


def test_d03_accepts_both_intents_with_identical_behavior():
    d03, v1 = S.load_oracle(_ROOT, "D03"), _v2_oracle("D03")
    assert d03["semantic_expectations"]["accepted_intents"] == ["INT_MOTOR_START_STOP", "INT_MOTOR_LATCH"]
    assert v1["semantic_expectations"]["accepted_intents"] == ["INT_MOTOR_START_STOP"]
    assert d03["semantic_expectations"]["forbidden_intents"] == v1["semantic_expectations"]["forbidden_intents"]
    assert "simetria funcional con D04/D11" in d03["semantic_expectations"]["notes"]
    assert d03["approval"]["change_scope"] == "BENCHMARK_V3_METADATA + SEMANTIC_EXPECTATIONS"
    assert CASES["D03"]["canonical_command"] == V2["D03"]["canonical_command"]
    for case_id in ("D04", "D11"):  # misma familia funcional
        assert set(S.load_oracle(_ROOT, case_id)["semantic_expectations"]["accepted_intents"]) == {"INT_MOTOR_START_STOP", "INT_MOTOR_LATCH"}


def test_v3_validation_32_aligned_no_hidden_requirements_no_inconsistencies():
    report = OR.build_validation_report(_ROOT)
    summary = report["summary"]
    assert summary["oracles_aligned"] == 32 and summary["hidden_oracle_requirements"] == 0
    assert summary["benchmark_inconsistencies"] == 0 and summary["schema_valid"] == 32
    assert summary["benchmark_version"] == 3
    assert BC.benchmark_inconsistencies(_ROOT, {c: S.load_oracle(_ROOT, c) for c in BC.CASE_IDS}) == []
    assert _json(_ROOT / "data" / "oracle_validation_report.json")["summary"]["oracles_aligned"] == 32


def test_obsolete_convention_text_cleaned():
    d20 = S.load_oracle(_ROOT, "D20")
    text = next(c["text"] for c in d20["experimental_conventions"] if c["id"] == "C-D20-DURATION")
    assert "no fija" not in text and "3 s" in text
    for case_id in BC.CASE_IDS:
        for convention in S.load_oracle(_ROOT, case_id).get("experimental_conventions") or []:
            if convention["id"] == "CMD-CANONICAL":
                assert convention["text"].startswith("COMANDO CANONICO (benchmark v3):"), case_id


# Diseno, documentacion y mapas -----------------------------------------------------------------

def test_experimental_design_points_formal_to_v3_and_keeps_v2_history():
    design = ED.load_design(_ROOT)
    assert design["benchmark_version"] == 3 and ED.FORMAL_BENCHMARK_VERSION == 3
    assert design["benchmark_history"]["DEVELOPMENT"]["benchmark_version"] == 2
    assert design["benchmark_history"]["FORMAL"]["benchmark_version"] == 3
    assert _json(_ARCHIVE / "experimental_design.json")["benchmark_version"] == 2  # el diseno anterior no se destruye


def test_changelog_and_interface_documentation():
    changelog = (_ROOT / "docs" / "benchmark_v3_changelog.md").read_text(encoding="utf-8")
    assert "ANTES de cualquier ensayo FORMAL" in changelog
    for case_id in CHANGED + ["D03"]:
        assert f"### {case_id} " in changelog, case_id
    interface = (_ROOT / "docs" / "experimental_interface_v3.md").read_text(encoding="utf-8")
    for needle in ("activas en ON", "incluido Stop", "MODE_AUTO = TRUE", "MODE_AUTO = FALSE", "SAFETY_TRIP",
                   "PROCESS_VARIABLE", "mapa_banco_fisico_base.json", "D14"):
        assert needle in interface, needle
    assert "0 % - 100 %" in (_ROOT / "docs" / "p03_setpoint_range_alignment.md").read_text(encoding="utf-8")


def test_physical_map_intact_and_simulation_maps_separate():
    base = _json(_ROOT / "data" / "plc_maps" / "mapa_banco_fisico_base.json")
    names = {v["name"] for v in base["variables"]}
    assert len(base["variables"]) == 24 and "I_Emergency" not in names  # sin hardware de emergencia inventado
    assert not any(n.startswith("Q_Speed") for n in names)
    simulation = {v["name"] for v in _json(_ROOT / "data" / "plc_maps" / "mapa_simulacion_completo.json")["variables"]}
    assert {"I_Emergency", "I_Speed_Low", "I_Speed_Medium", "I_Speed_High"} <= simulation  # disparo simulado separado
    assert not names & {"I_Speed_Low", "I_Speed_Medium", "I_Speed_High"}


def test_v2_archive_hashes_unchanged_by_v3():
    manifest = _json(_ARCHIVE / "manifest.json")
    for relative, digest in manifest["raw_sha256"].items():
        assert hashlib.sha256((_ARCHIVE / relative).read_bytes()).hexdigest() == digest, relative


# Ensayos nuevos ---------------------------------------------------------------------------------

def test_new_trial_records_benchmark_v3_and_hashes(pipeline):
    app = pipeline["app"]
    directory = _arm_experiment_trial(app)  # caso D12, variante V2
    record = trial_model.load_trial(directory)
    assert record["benchmark_version"] == 3
    assert record["canonical_case_hash"] == BC.case_hash(CASES["D12"])
    assert record["variant_hash"] == BC.variant_hash(CASES["D12"]["variants"]["V2"])


def test_gui_loads_v3_variants_from_canonical_catalog(app):
    app.experiment_group_var.set("Discreto D01-D20")
    app._refresh_experiment_case_selector()
    name = f"D08 - {CASES['D08']['title']}"
    assert name in app._experiment_profiles_by_case
    app.experiment_case_var.set(name)
    app._on_experiment_case_changed()
    app.experiment_variant_var.set("V2")
    app._update_variant_command_preview()
    assert app._active_variant_command_text == CASES["D08"]["variants"]["V2"] == BUILD.CHANGES["D08"]["V2"]
    app.active_profile_id = None
