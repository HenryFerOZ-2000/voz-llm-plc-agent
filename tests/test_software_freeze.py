"""
Congelacion FORMAL v1: el manifiesto v2 detecta codigo/prompt/Oracle/benchmark/mapa modificado, archivos nuevos o
ausentes, MASTER incorrecto y configuracion de ejecucion distinta; todo punto de entrada FORMAL lo valida antes del LLM
o de TIA. Los estados dependientes de la PC (MASTER, configuracion TIA local, modelo LLM) se fijan con monkeypatch.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trial_experiments import deferred_evaluator as DE
from trial_experiments import experimental_design as ED
from trial_experiments import software_freeze as SF
from utils import get_project_root

from test_phase4a_deferred_evaluation import _master, _project  # noqa: E402

_ROOT = get_project_root()
_MASTER = {"master_status": "FORMAL_READY", "validation_status": "VALID", "snapshot_sha256": "a" * 64,
           "snapshot_file_sha256": "a" * 64, "snapshot_size_bytes": 1, "folder_fingerprint": "f" * 64,
           "folder_fingerprint_now": "f" * 64, "project_name": "S71500_MASTER", "tia_version": "V18",
           "cpu_type_name": "CPU 1516-3 PN/DP", "cpu_order_number": "6ES7 516-3AN01-0AB0", "cpu_firmware": "V2.6",
           "x1_ip_address": "192.168.0.1", "unmanaged_blocks": [], "blocks": [], "formal_ready": {"approved_by": "INV"}}
_RUNTIME = {"plcsim_instance_name": "TESIS_PLC_SIM", "plcsim_io_settle_ms": 500}
_LLM = {"provider": "openai", "parser_mode": "llm", "model": "m", "transcription_model": "t", "temperature": 0,
        "require_structured_output": True}


@pytest.fixture
def pinned(monkeypatch):
    state = {"master": dict(_MASTER), "runtime": dict(_RUNTIME), "llm": dict(_LLM)}
    monkeypatch.setattr(SF, "master_state", lambda root: dict(state["master"]))
    monkeypatch.setattr(SF, "runtime_settings", lambda root: dict(state["runtime"]))
    monkeypatch.setattr(SF, "llm_settings", lambda root: dict(state["llm"]))
    return state


def _manifest():
    return SF.build_manifest(_ROOT, {"passed": 1, "failed": 0, "skipped": 0}, {"evaluable": 32, "total": 32, "blockers": 0},
                             "formal-v1.0", ["x"])


def test_manifest_covers_code_prompt_oracles_benchmark_maps_and_validates(pinned):
    manifest = _manifest()
    assert manifest["schema_version"] == 2 and manifest["oracle_count"] == 32 and manifest["status"] == "FROZEN"
    for path in ("src/code_generator.py", "prompts/llm_semantic_parser_prompt.txt", "data/experiment_oracles/P06.json",
                 "data/experiment_cases/canonical_cases.json", "data/plc_maps/mapa_banco_fisico_base.json",
                 "plcsim_runtime_bridge/Program.cs", "knowledge_base/plc_safety_rules.md", "src/composition_check.py"):
        assert path in manifest["files"], path
    assert not any(path.startswith(("docs/", "tests/")) for path in manifest["files"])
    assert manifest["prompt_hash"] == manifest["files"]["prompts/llm_semantic_parser_prompt.txt"]
    assert SF.validate_freeze(_ROOT, manifest)["ok"]


@pytest.mark.parametrize("path", ["src/code_generator.py", "prompts/llm_semantic_parser_prompt.txt",
                                  "data/experiment_oracles/D05.json", "data/experiment_cases/canonical_cases.json",
                                  "data/plc_maps/mapa_experimental_simulacion.json"])
def test_any_frozen_content_change_is_detected(pinned, path):
    manifest = _manifest()
    manifest["files"][path] = "0" * 64  # equivalente a que el archivo actual ya no coincida con lo congelado
    assert f"FROZEN_FILE_MODIFIED: {path}" in SF.validate_freeze(_ROOT, manifest)["errors"]


def test_added_or_missing_frozen_files_are_detected(pinned):
    manifest = _manifest()
    removed = manifest["files"].pop("src/verifier.py")
    assert "UNFROZEN_FILE_ADDED: src/verifier.py" in SF.validate_freeze(_ROOT, manifest)["errors"]
    manifest["files"]["src/verifier.py"] = removed
    manifest["files"]["src/ghost_module.py"] = "0" * 64
    assert "FROZEN_FILE_MISSING: src/ghost_module.py" in SF.validate_freeze(_ROOT, manifest)["errors"]


def test_oracle_state_and_master_and_runtime_mismatches_are_detected(pinned):
    manifest = _manifest()
    manifest["oracles"]["P07"]["hash"] = "0" * 64
    pinned["master"]["snapshot_file_sha256"] = "b" * 64
    pinned["runtime"]["plcsim_io_settle_ms"] = 0
    pinned["llm"]["model"] = "other"
    errors = SF.validate_freeze(_ROOT, manifest)["errors"]
    assert "ORACLE_MISMATCH: P07" in errors
    assert any(e.startswith("MASTER_MISMATCH") for e in errors)
    assert any(e.startswith("RUNTIME_SETTINGS_MISMATCH") for e in errors)
    assert "LLM_SETTINGS_MISMATCH: model" in errors
    pinned["master"]["master_status"] = "DEVELOPMENT_READY"
    assert "MASTER_NOT_FORMAL_READY" in SF.validate_freeze(_ROOT, _manifest())["errors"]


def test_formal_entry_points_abort_when_the_environment_does_not_match(pinned, tmp_path, monkeypatch):
    manifest = _manifest()
    path = tmp_path / "software_freeze_manifest.json"
    monkeypatch.setattr(ED, "freeze_manifest_path", lambda root: path)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert ED.check_formal_trial_allowed(_ROOT) == (True, [])
    manifest["files"]["src/llm_parser.py"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    allowed, reasons = ED.check_formal_trial_allowed(_ROOT)
    assert not allowed and any("FROZEN_FILE_MODIFIED: src/llm_parser.py" in r for r in reasons)


def test_master_with_residual_blocks_is_never_formal_ready(tmp_path):
    root = _project(tmp_path)
    _master(root)  # contiene PLC_PRG / DB_PLC_PRG de un programa anterior
    with pytest.raises(ValueError, match="bloques residuales"):
        DE.declare_master_formal_ready(root, "INV_TEST")


def test_master_formal_ready_requires_explicit_approval_and_intact_master(tmp_path):
    root = _project(tmp_path)
    _master(root, managed=("Main",))  # MASTER de prueba validado, sin bloques residuales
    with pytest.raises(ValueError):
        DE.declare_master_formal_ready(root, "")
    config = DE.declare_master_formal_ready(root, "INV_TEST", ["evidencia"])
    assert config["status"] == "FORMAL_READY" and config["validation"]["master_status"] == "FORMAL_READY"
    assert config["formal_ready"]["approved_by"] == "INV_TEST" and config["formal_ready"]["master_hash"] == config["hash"]
    (Path(config["path"]).parent / "extra.bin").write_bytes(b"changed")  # el MASTER cambia despues de validar
    with pytest.raises(ValueError):
        DE.declare_master_formal_ready(root, "INV_TEST")


def test_repository_freeze_manifest_matches_the_frozen_content_when_present():
    """Tras la congelacion, el contenido versionado congelado debe coincidir con el manifiesto (cambios = nuevo freeze)."""
    manifest = SF.load_manifest(_ROOT)
    if manifest is None:
        pytest.skip("todavia no hay manifiesto de congelacion")
    current = set(SF.frozen_files(_ROOT))
    assert current == set(manifest["files"])
    assert {path: SF.normalized_sha256(_ROOT / path) for path in current} == manifest["files"]
    assert all(entry["status"] == "FROZEN" and entry["human_formal_approval"] == "APPROVED"
               for entry in manifest["oracles"].values())
