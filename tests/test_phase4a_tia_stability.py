"""
Fase 4A-TIA-STABILITY: precheck de memoria antes de abrir TIA y evaluacion sin la descripcion
completa de la copia (causa del OutOfMemoryException real en D03_V1_TEXT_DEV_002 / T0001).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from trial_experiments import batch_runner as B  # noqa: E402
from trial_experiments import deferred_evaluator as DE  # noqa: E402
from trial_experiments import system_resources as SR  # noqa: E402
from trial_experiments import tia_workspace as TW  # noqa: E402

from test_phase4a_deferred_evaluation import _FakeBridge, _generated_trial, _master, _oracle_pass, _project, _runtime  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)
_BRIDGE = (_ROOT / "tia_openness_bridge" / "Program.cs").read_text(encoding="utf-8")


def _memory(physical_mb: int, headroom_mb: int):
    return lambda: {"available": True, "total_physical_mb": 16384, "available_physical_mb": physical_mb,
                    "commit_limit_mb": 24000, "committed_mb": 24000 - headroom_mb, "commit_headroom_mb": headroom_mb}


def _evaluate(root, trial_dir, bridge, memory):
    return DE.evaluate_trial(root, trial_dir, None, bridge=bridge, runtime_status_fn=_runtime, oracle_fn=_oracle_pass,
                             log=lambda _m: None, memory_fn=memory)


def _method(name: str) -> str:
    start = _BRIDGE.index(f"private static Dictionary<string, object> {name}(")
    following = re.search(r"\n        (private|public|internal) static ", _BRIDGE[start + 10:])
    return _BRIDGE[start: start + 10 + following.start()] if following else _BRIDGE[start:]


# ---------- precheck de memoria ----------

def test_insufficient_commit_headroom_blocks_before_tia(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    bridge = _FakeBridge()
    result = _evaluate(root, trial_dir, bridge, _memory(physical_mb=12000, headroom_mb=7000))
    assert bridge.requests == [] and result["tia_session_opened"] is False and result["tia_workspace_id"] is None
    assert result["final_status"] == "INFRASTRUCTURE_ERROR" and result["error_code"] == SR.ERROR_INSUFFICIENT_MEMORY
    assert not (root / "tiaw").exists() or not list((root / "tiaw").glob("T*"))  # ni siquiera se creo workspace
    record = json.loads((trial_dir / "trial.json").read_text(encoding="utf-8"))
    assert record["failure_category"] == "INFRASTRUCTURE_ERROR" and record["evaluation"]["status"] == DE.EVALUATION_INFRASTRUCTURE
    assert record["stages"]["functional_success"] is None  # no consume evaluacion funcional


def test_insufficient_physical_ram_blocks_before_tia(tmp_path):
    root = _project(tmp_path)
    _master(root)
    bridge = _FakeBridge()
    result = _evaluate(root, _generated_trial(root), bridge, _memory(physical_mb=2000, headroom_mb=20000))
    assert bridge.requests == [] and any("RAM fisica" in error for error in result["errors"])


def test_memory_metrics_are_recorded_in_the_attempt(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    result = _evaluate(root, trial_dir, _FakeBridge(), _memory(physical_mb=1000, headroom_mb=1000))
    report = json.loads((trial_dir / "evaluation" / "attempt_001" / DE.MEMORY_PREFLIGHT_REPORT).read_text(encoding="utf-8"))
    for key in ("available_physical_mb", "committed_mb", "commit_limit_mb", "commit_headroom_mb"):
        assert key in report["metrics"] and key in result["memory"]
    assert report["settings"] == {"enabled": True, "min_available_physical_gb": 4, "min_commit_headroom_gb": 8}


def test_sufficient_memory_continues_and_is_recorded(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    result = _evaluate(root, trial_dir, _FakeBridge(), _memory(physical_mb=6000, headroom_mb=10000))
    assert result["final_status"] == "PASS" and result["memory"]["commit_headroom_mb"] == 10000
    manifest = json.loads((trial_dir / "evaluation" / "attempt_001" / "tia" / DE.TIA_PROJECT_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["memory_preflight"]["ok"] is True


def test_preflight_thresholds_are_configurable(tmp_path):
    root = _project(tmp_path)
    config_path = root / "config" / "tia_openness_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["tia_memory_preflight"] = {"enabled": True, "min_available_physical_gb": 1, "min_commit_headroom_gb": 2}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    assert SR.memory_preflight(root, _memory(1500, 3000))["ok"] is True
    config["tia_memory_preflight"]["enabled"] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")
    assert SR.memory_preflight(root, _memory(10, 10))["ok"] is True
    real = json.loads((_ROOT / "config" / "tia_openness_config.json").read_text(encoding="utf-8"))["tia_memory_preflight"]
    assert real == {"enabled": True, "min_available_physical_gb": 4, "min_commit_headroom_gb": 8}


def test_environment_precheck_blocks_complete_trial_on_low_memory(tmp_path, monkeypatch):
    root = _project(tmp_path)
    _master(root)
    monkeypatch.setattr(SR, "measure_memory", _memory(1000, 1000))
    check = DE.environment_precheck(root, "DEVELOPMENT_VALIDATION")
    assert not check["ok"] and any(SR.ERROR_INSUFFICIENT_MEMORY in error for error in check["errors"])


def test_real_memory_measurement_has_the_expected_shape():
    real = SR.read_memory_status()  # medicion real de esta maquina (el precheck usa measure_memory)
    if real.get("available"):
        assert abs(real["commit_headroom_mb"] - (real["commit_limit_mb"] - real["committed_mb"])) <= 1  # truncado a MB
        assert real["available_physical_mb"] <= real["total_physical_mb"]


# ---------- lecturas Openness durante la evaluacion ----------

def test_deferred_evaluation_never_runs_the_full_describe():
    evaluate = _method("ExecuteEvaluateTrial")
    for forbidden in ("DescribePlcProject", "DescribeInterfaces", "CollectInterfaces", "CollectBlocks", "NodeType"):
        assert forbidden not in evaluate, forbidden
    assert "minimal_identity_started" in evaluate and "expected_project_name" in evaluate
    assert "ListBlockNames" in evaluate


def test_master_validation_still_runs_the_full_describe():
    assert "DescribePlcProject(project, requestedPlcName)" in _method("ExecuteValidateMaster")
    describe = _BRIDGE[_BRIDGE.index("private static Dictionary<string, object> DescribePlcProject("):]
    assert "DescribeInterfaces(project)" in describe[:2500]  # VALIDAR MASTER sigue describiendo CPU/X1/IP/bloques


def test_all_persistent_checkpoints_are_kept():
    evaluate = _method("ExecuteEvaluateTrial")
    for name in ("tia_start", "retrieve", "minimal_identity", "tags", "managed_blocks", "import", "compile", "save", "archive",
                 "handshake", "download"):
        assert f'Checkpoint("{name}_started"' in evaluate, name
    assert '"retrieve_master_copy"' in evaluate and 'stage = "minimal_identity"' in evaluate  # etapas separadas


def test_evaluation_passes_expected_identity_and_uses_frozen_master_metadata(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    bridge = _FakeBridge()
    _evaluate(root, trial_dir, bridge, _memory(8000, 20000))
    assert bridge.requests[0]["expected_project_name"] == "MASTER"
    manifest = json.loads((trial_dir / "evaluation" / "attempt_001" / "tia" / DE.TIA_PROJECT_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["tia"]["cpu"].startswith("OrderNumber:6ES7 516") and "VALIDAR MASTER" in manifest["tia"]["source"]


# ---------- evidencia real del fallo ----------

def test_real_d03_attempt_001_evidence_is_untouched():
    attempt = _ROOT / "results" / "development_validation_v2" / "D03" / "V1" / "D03_V1_TEXT_DEV_002" / "evaluation" / "attempt_001"
    if not attempt.exists():
        return
    assert TW.sha256(attempt / "compile_report.json") == "8d9e59122ff01ba3bfd0c0eabc5551db04f4f550e6bd97e0d7cdf28c19be26ac"
    assert TW.sha256(attempt / "tia" / "tia_project_manifest.json") == "37ac52c55da421232b0352eb815629b331a94a3dfad31c032ecb13f033dcd2ae"


def test_maps_oracles_and_benchmark_unchanged():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
