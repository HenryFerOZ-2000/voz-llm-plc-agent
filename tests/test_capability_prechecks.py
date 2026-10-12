"""
Una sola decision de ejecutabilidad en todo el sistema: oracle_runner.runtime_capability_check.

El precheck de evaluacion (deferred_evaluator.precheck), el plan del lote TEXT (text_batch.case_is_evaluable /
build_plan) y el preflight del lote baseline (batch_runner.preflight) deciden por check["executable"], no por el
runtime_support congelado del Oracle (que se conserva como declared_runtime_support). Antes de esta correccion el
runner ya ejecutaba P02, pero el precheck lo abortaba con la regla legacy runtime_support != EXECUTABLE_NOW.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import plcsim_runtime_io as rio
from trial_experiments import batch_runner as B
from trial_experiments import deferred_evaluator as DE
from trial_experiments import oracle_schema
from trial_experiments import text_batch as TB
from utils import get_project_root

from test_phase4a_deferred_evaluation import _generated_trial, _master, _project  # noqa: E402

_ROOT = get_project_root()
_FROZEN = sorted([*(_ROOT / "data" / "experiment_oracles").glob("*.json"), _ROOT / "data" / "experiment_cases" / "canonical_cases.json",
                  _ROOT / "data" / "experimental_design.json"])
_HASHES = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in _FROZEN}


def _trial(tmp_path: Path, case_id: str) -> tuple[Path, Path]:
    root = _project(tmp_path)
    _master(root)
    return root, _generated_trial(root, case_id, "V1")


def _runtime_errors(check: dict) -> list[str]:
    return [error for error in check["errors"] if TB.RUNTIME_EXTENSION_MARKER in error]


# A. P02 REQUIRES_RUNTIME_EXTENSION + capacidades completas -> evaluable en todas las rutas
def test_a_p02_with_full_capabilities_passes_precheck_and_is_planned_as_evaluable(tmp_path):
    root, trial = _trial(tmp_path, "P02")
    assert oracle_schema.load_oracle(root, "P02")["runtime_support"] == "REQUIRES_RUNTIME_EXTENSION"
    check = DE.precheck(root, trial)
    assert check["ok"] is True, check["errors"]
    capabilities = check["runtime_capability_check"]
    assert capabilities["executable"] is True and capabilities["missing_capabilities"] == []
    assert capabilities["declared_runtime_support"] == "REQUIRES_RUNTIME_EXTENSION"  # conservado como dato
    assert TB.case_is_evaluable(root, "P02") is True
    [entry] = TB.build_plan(root, ["P02"], ["V1"])
    assert entry["evaluable"] is True


# B. P02 sin REAL -> el precheck bloquea e informa la capacidad que falta
def test_b_p02_without_real_is_blocked_with_missing_capabilities(tmp_path, monkeypatch):
    root, trial = _trial(tmp_path, "P02")
    monkeypatch.setattr(rio, "RUNTIME_CAPABILITIES", ("BOOL", "INTERNAL_TAG_READ"))
    check = DE.precheck(root, trial)
    assert check["ok"] is False
    assert check["runtime_capability_check"]["missing_capabilities"] == ["REAL"]
    [error] = _runtime_errors(check)
    assert "REAL" in error and "P02" in error


# C. Caso D ejecutable: comportamiento sin cambios (solo BOOL, tambien con un Runtime solo BOOL)
@pytest.mark.parametrize("capabilities", [rio.RUNTIME_CAPABILITIES, ("BOOL",)])
def test_c_discrete_case_is_unchanged(tmp_path, monkeypatch, capabilities):
    monkeypatch.setattr(rio, "RUNTIME_CAPABILITIES", capabilities)
    root, trial = _trial(tmp_path, "D03")
    check = DE.precheck(root, trial)
    assert check["ok"] is True, check["errors"]
    assert check["runtime_capability_check"]["required_capabilities"] == ["BOOL"]
    assert check["runtime_capability_check"]["declared_runtime_support"] == "EXECUTABLE_NOW"
    assert TB.case_is_evaluable(root, "D03") is True
    assert all(entry["evaluable"] for entry in TB.build_plan(root, ["D01", "D02", "D03"]))


def test_c_baseline_preflight_decides_by_capabilities_for_d01_d20(monkeypatch):
    def runtime_check(preflight):
        return next(c for c in preflight["checks"] if c["id"] == "d01_d20_runtime_executable")

    assert runtime_check(B.preflight(_ROOT, live=False))["ok"] is True
    monkeypatch.setattr(rio, "RUNTIME_CAPABILITIES", ("BOOL",))
    assert runtime_check(B.preflight(_ROOT, live=False))["ok"] is True  # D01-D20 solo necesitan BOOL
    monkeypatch.setattr(rio, "RUNTIME_CAPABILITIES", ())
    blocked = runtime_check(B.preflight(_ROOT, live=False))
    assert blocked["ok"] is False and "D01" in blocked["detail"]


# D. Caso P con capacidades incompletas -> NOT_EVALUABLE (misma convencion que antes)
def test_d_pid_case_with_incomplete_capabilities_is_not_evaluable(tmp_path, monkeypatch):
    root, trial = _trial(tmp_path, "P04")
    monkeypatch.setattr(rio, "RUNTIME_CAPABILITIES", ("BOOL", "REAL", "INTERNAL_TAG_READ"))  # sin escritura interna
    assert TB.case_is_evaluable(root, "P04") is False
    assert all(not entry["evaluable"] for entry in TB.build_plan(root, ["P04"]))
    check = DE.precheck(root, trial)
    assert check["ok"] is False and check["runtime_capability_check"]["missing_capabilities"] == ["INTERNAL_TAG_WRITE"]
    # record_precheck_block clasifica NOT_EVALUABLE (no BLOCKED) cuando TODOS los errores son de capacidades.
    assert check["errors"] and all(TB.RUNTIME_EXTENSION_MARKER in error for error in check["errors"])


@pytest.mark.parametrize("case_id", [f"P{i:02d}" for i in range(1, 13)])
def test_every_pid_case_is_evaluable_with_the_current_runtime(case_id):
    assert TB.case_is_evaluable(_ROOT, case_id) is True


# E. Ningun Oracle / benchmark / diseno cambia
def test_e_no_oracle_benchmark_or_design_changes():
    assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in _FROZEN} == _HASHES
    for case_id in ("P02", "P04", "D03"):
        oracle_schema.verify_integrity(oracle_schema.load_oracle(_ROOT, case_id))
