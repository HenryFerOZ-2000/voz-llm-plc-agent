"""
Fase 4A-DEFERRED-PATHS: TIA solo ve rutas cortas (tiaw/Tnnnn, limite real de 143 caracteres); la
evidencia permanente (.zap18 verificado por hash) queda en la carpeta del ensayo.
"""
from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

import tia_projects  # noqa: E402
from trial_experiments import deferred_evaluator as DE  # noqa: E402
from trial_experiments import tia_workspace as TW  # noqa: E402
from trial_experiments import trial_model  # noqa: E402

from test_phase4a_deferred_evaluation import _FakeBridge, _evaluate, _generated_trial, _master, _project  # noqa: E402

_REAL_ROOT = Path(__file__).resolve().parents[1]


def _snapshot(tmp_path: Path, name: str = "M261001125037.zap18") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zap:
        zap.writestr(name + ".ap18", b"p")
        zap.writestr("AdditionalFiles/PLCM/plcmArchive.pma15_0", b"x")
    return path


# ---------- IDs cortos y workspaces independientes ----------

def test_short_ids_are_never_reused_and_independent_of_trial_id(tmp_path):
    root = _project(tmp_path)
    first = TW.allocate(root, "D03_V1_TEXT_DEV_001", 1, tmp_path / "t1")
    second = TW.allocate(root, "D03_V1_TEXT_DEV_001", 2, tmp_path / "t1")
    assert (first["workspace_id"], second["workspace_id"]) == ("T0001", "T0002")
    assert "D03" not in first["path"] and Path(first["path"]).parent == root / "tiaw"
    TW.update_entry(root, "T0001", state=TW.STATE_EVIDENCE_COPIED, evidence_copied_ok=True)
    assert TW.remove_workspace(root, "T0001") and not Path(first["path"]).exists()
    third = TW.allocate(root, "D03_V2_TEXT_DEV_001", 1, tmp_path / "t2")
    assert third["workspace_id"] == "T0003"  # nunca se reutiliza un ID, ni tras la limpieza
    assert TW.load_registry(root)["workspaces"]["T0001"]["state"] == TW.STATE_CLEANED


def test_tia_paths_fit_the_real_limit_for_the_real_project_root(tmp_path):
    workspace = _REAL_ROOT / "tiaw" / "T0001"
    # Nombre INTERNO real del MASTER (el Retrieve real creo p/S71500_MASTER/S71500_MASTER.ap18).
    validation = TW.validate_paths(workspace, "T0001", "S71500_MASTER", TW.TIA_PATH_LIMIT)
    assert validation["ok"], validation["errors"]
    assert validation["retrieve_path_length"] <= 143 and validation["archive_path_length"] <= 143
    assert validation["source_path_length"] <= 143 and validation["max_path_length"] <= 143
    retrieve = next(c for c in validation["checks"] if c["operation"] == "retrieve_project_file")
    assert retrieve["path"].endswith("p\\S71500_MASTER\\S71500_MASTER.ap18") and "subcarpeta" in retrieve["note"]
    long_name = TW.validate_paths(workspace, "T0001", "S71500_MASTER_PROYECTO_EXPERIMENTAL_LARGO", TW.TIA_PATH_LIMIT)
    assert not long_name["ok"] and any(TW.ERROR_PATH_TOO_LONG in error for error in long_name["errors"])


def test_path_validation_uses_the_registered_internal_name_never_the_snapshot_name(tmp_path):
    root = _project(tmp_path)
    config = _master(root)
    assert DE.master_internal_project_name(config) == config["validation"]["internal_project_name"] == "MASTER"
    check = DE.precheck(root, _generated_trial(root))
    assert check["path_validation"]["internal_project_name"] == "MASTER"
    retrieve = next(c for c in check["path_validation"]["checks"] if c["operation"] == "retrieve_project_file")
    assert retrieve["path"].endswith("MASTER.ap18") and Path(config["snapshot"]["archive_path"]).name not in retrieve["path"]
    unknown = TW.validate_paths(tmp_path / "T0001", "T0001", None)
    assert not unknown["ok"] and TW.ERROR_INTERNAL_NAME_UNKNOWN in unknown["errors"][0]


def test_trial_id_never_appears_in_any_path_given_to_tia(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    bridge = _FakeBridge()
    _evaluate(root, trial_dir, bridge)
    request = bridge.requests[0]
    for key in ("working_dir", "trial_archive_dir", "trial_archive_name", "source_path", "handshake_dir", "master_archive_path"):
        assert trial_dir.name not in str(request[key]), key
        assert "results" not in Path(str(request[key])).parts, key


def test_path_too_long_aborts_before_calling_the_bridge(tmp_path, monkeypatch):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    monkeypatch.setattr(DE, "TIA_ARCHIVE_MAX_PATH", 20)
    bridge = _FakeBridge()
    result = _evaluate(root, trial_dir, bridge)
    assert result["aborted"] and bridge.requests == []
    assert any(TW.ERROR_PATH_TOO_LONG in error for error in result["errors"])
    check = result["path_validation"]["checks"][0]
    assert {"operation", "path", "path_length", "limit"} <= set(check)
    assert not (root / "tiaw").exists() or not any((root / "tiaw").glob("T*"))  # ni siquiera se creo workspace


def test_each_trial_gets_its_own_fresh_workspace(tmp_path):
    root = _project(tmp_path)
    _master(root)
    a, b = _generated_trial(root, "D03", "V1"), _generated_trial(root, "D03", "V2")
    bridge = _FakeBridge()
    _evaluate(root, a, bridge)
    _evaluate(root, b, bridge)
    first, second = bridge.requests
    assert Path(first["working_dir"]).parent.name == "T0001" and Path(second["working_dir"]).parent.name == "T0002"
    assert first["master_archive_path"] == second["master_archive_path"]  # siempre desde el snapshot MASTER
    assert not Path(second["working_dir"]).is_relative_to(Path(first["working_dir"]).parent)


# ---------- copia verificada del .zap18 ----------

def test_archive_is_copied_to_evidence_before_download(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    seen: dict[str, Any] = {}

    class _OrderBridge(_FakeBridge):
        def __call__(self, request, work_dir, project_root=None, on_archived=None):
            def _watch(info):
                decision = on_archived(info)
                evidence = trial_dir / "evaluation" / "attempt_001" / "tia" / f"{trial_dir.name}.zap18"
                seen["evidence_exists_at_decision"] = evidence.exists()
                seen["decision"] = decision
                return decision
            return super().__call__(request, work_dir, project_root, on_archived=_watch)

    result = _evaluate(root, trial_dir, _OrderBridge())
    assert result["final_status"] == "PASS" and result["evidence_copied_ok"] is True
    assert seen["evidence_exists_at_decision"] is True and seen["decision"] == {"download": True, "reason": "EVIDENCE_VERIFIED"}
    manifest = json.loads((trial_dir / "evaluation" / "attempt_001" / "tia" / DE.TIA_PROJECT_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["archive"]["workspace_hash"] == manifest["archive"]["evidence_hash"]


def test_corrupted_archive_is_detected_and_never_reaches_oracle(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    bridge = _FakeBridge("CORRUPT_AFTER_ARCHIVE")
    result = _evaluate(root, trial_dir, bridge)
    assert result["final_status"] == "INFRASTRUCTURE_ERROR" and result["evidence_copied_ok"] is False
    assert bridge.decisions[0]["download"] is False and TW.ERROR_ARCHIVE_INTEGRITY_FAILED in bridge.decisions[0]["reason"]
    assert result["download_success"] is not True and result["oracle_verdict"] is None
    assert not (trial_dir / "evaluation" / "attempt_001" / "oracle_trace.json").exists()
    assert (root / "tiaw" / "T0001").exists()  # se conserva para diagnostico
    entry = TW.load_registry(root)["workspaces"]["T0001"]
    assert entry["state"] == TW.STATE_KEPT and entry["keep_reason"]


def test_copy_verification_detects_a_corrupt_copy(tmp_path, monkeypatch):
    source = tmp_path / "T0001.zap18"
    source.write_bytes(b"zap-content")
    good = TW.copy_archive_to_evidence(source, tmp_path / "ev" / "ok.zap18", TW.sha256(source))
    assert good["copied_ok"] and good["workspace_hash"] == good["evidence_hash"]
    monkeypatch.setattr(TW.shutil, "copyfile", lambda src, dst: Path(dst).write_bytes(b"other"))
    bad = TW.copy_archive_to_evidence(source, tmp_path / "ev" / "bad.zap18", TW.sha256(source))
    assert not bad["copied_ok"] and TW.ERROR_ARCHIVE_INTEGRITY_FAILED in bad["error"]
    empty = tmp_path / "empty.zap18"
    empty.write_bytes(b"")
    assert TW.ERROR_ARCHIVE_INTEGRITY_FAILED in TW.copy_archive_to_evidence(empty, tmp_path / "ev" / "e.zap18")["error"]


def test_long_evidence_paths_are_handled_by_the_filesystem_layer(tmp_path):
    deep = tmp_path / ("x" * 60) / ("y" * 60) / ("z" * 60) / ("w" * 40)
    source = tmp_path / "T0001.zap18"
    source.write_bytes(b"zap")
    result = TW.copy_archive_to_evidence(source, deep / "D03_V1_TEXT_DEV_001.zap18")
    assert result["copied_ok"], result
    if os.name == "nt" and len(str(deep)) >= 240:
        assert TW.fs_path(deep).startswith("\\\\?\\")


# ---------- limpieza ----------

def test_cleanup_only_after_verified_evidence_and_infra_keeps_diagnostics(tmp_path):
    root = _project(tmp_path)
    _master(root)
    ok_trial, infra_trial = _generated_trial(root, "D03", "V1"), _generated_trial(root, "D03", "V2")
    ok = _evaluate(root, ok_trial, _FakeBridge())
    infra = _evaluate(root, infra_trial, _FakeBridge("NON_RECOVERABLE"))
    assert ok["tia_workspace_cleaned"] is True and not (root / "tiaw" / ok["tia_workspace_id"]).exists()
    assert infra["tia_workspace_cleaned"] is False and Path(infra["tia_workspace_path"]).exists()
    registry = TW.load_registry(root)["workspaces"]
    assert registry[infra["tia_workspace_id"]]["state"] == TW.STATE_KEPT
    assert TW.remove_workspace(root, infra["tia_workspace_id"]) is False  # sin evidencia verificada: nunca se borra
    active = TW.allocate(root, "D03_V3_TEXT_DEV_001", 1, root / "x")
    assert TW.remove_workspace(root, active["workspace_id"]) is False  # nunca un workspace ACTIVO
    report = TW.cleanup_workspaces(root)
    assert report["removed"] == [] and {k["workspace_id"] for k in report["kept"]} == {infra["tia_workspace_id"], active["workspace_id"]}
    (root / "tiaw" / "huerfano").mkdir()
    assert any(path.endswith("huerfano") for path in TW.cleanup_workspaces(root)["orphans"])


def test_master_and_normal_project_unchanged_by_workspace_evaluation(tmp_path):
    root = _project(tmp_path)
    normal_dir = root / "tia_projects" / "NORMAL"
    normal_dir.mkdir(parents=True)
    normal = normal_dir / "NORMAL.ap18"
    normal.write_bytes(b"normal")
    tia_projects.set_normal_project(root, normal)
    config = _master(root)
    fingerprint = DE.master_folder_fingerprint(config["path"])
    snapshot_hash = DE.sha256_file(Path(config["snapshot"]["archive_path"]))
    _evaluate(root, _generated_trial(root), _FakeBridge())
    assert normal.read_bytes() == b"normal"
    assert DE.master_folder_fingerprint(config["path"]) == fingerprint
    assert DE.sha256_file(Path(config["snapshot"]["archive_path"])) == snapshot_hash


# ---------- handshake real de run_bridge (bridge simulado como proceso) ----------

_FAKE_BRIDGE_SCRIPT = r'''
import json, sys, time, pathlib
request = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
ws = pathlib.Path(request["handshake_dir"])
archive = ws / "T0001.zap18"
archive.write_bytes(b"zap")
(ws / "archived.json").write_text(json.dumps({"archive_path": str(archive), "archive_sha256": "abc"}), encoding="utf-8")
deadline = time.time() + 20
decision = None
while time.time() < deadline:
    path = ws / "proceed.json"
    if path.exists():
        decision = json.loads(path.read_text(encoding="utf-8"))
        break
    time.sleep(0.2)
pathlib.Path(request["result_path"]).write_text(json.dumps({"status": "TIA_COMPILATION_PASSED", "handshake": decision,
    "download": {"status": "TIA_DOWNLOAD_PASSED"} if decision and decision.get("download") else None}), encoding="utf-8")
'''


def test_run_bridge_handshake_waits_for_python_decision(tmp_path, monkeypatch):
    import tia_openness

    script = tmp_path / "fake_bridge.py"
    script.write_text(_FAKE_BRIDGE_SCRIPT, encoding="utf-8")
    wrapper = tmp_path / "fake_bridge.cmd"
    wrapper.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    monkeypatch.setattr(tia_openness, "build_openness_bridge", lambda root: {"built": True, "exe_path": str(wrapper)})
    workspace = tmp_path / "tiaw" / "T0001"
    workspace.mkdir(parents=True)
    calls: list[dict[str, Any]] = []

    def _on_archived(info):
        calls.append(info)
        return {"download": True, "reason": "EVIDENCE_VERIFIED"}

    report = DE.run_bridge({"action": "evaluate_trial", "handshake_dir": str(workspace)}, workspace,
                           project_root=_project(tmp_path), timeout_s=60, on_archived=_on_archived)
    assert calls and calls[0]["archive_path"].endswith("T0001.zap18")
    assert report["handshake"] == {"download": True, "reason": "EVIDENCE_VERIFIED"}
    assert report["download"]["status"] == "TIA_DOWNLOAD_PASSED"
    assert (workspace / "bridge_stdout.txt").exists()


# ---------- checkpoints persistentes del bridge ----------

def test_checkpoints_reconstruct_a_crash_in_the_middle_of_an_operation(tmp_path):
    # Secuencia real de D03_V1_TEXT_DEV_002: TIA se cayo (OutOfMemory) DURANTE la descripcion de la copia.
    log = tmp_path / TW.CHECKPOINTS_FILENAME
    log.write_text("\n".join([
        "2026-10-01T16:37:02.100\ttia_start_started\tWithoutUserInterface",
        "2026-10-01T16:37:05.200\ttia_start_completed\t",
        "2026-10-01T16:37:05.300\tretrieve_started\tM.zap18 -> p",
        "2026-10-01T16:37:23.400\tretrieve_completed\tp\S71500_MASTER\S71500_MASTER.ap18 (131 chars)",
        "2026-10-01T16:37:23.500\tdescribe_started\t",
        "2026-10-01T16:38:17.600\tdescribe_copy_failed\tSiemens.Engineering.NonRecoverableException: Unexpected exception",
        "2026-10-01T16:38:17.700\tsave_started\t",
        "2026-10-01T16:38:17.800\tsave_or_archive_failed\tEngineeringObjectDisposedException",
    ]) + "\n", encoding="utf-8")
    parsed = TW.parse_checkpoints(log)
    assert parsed["last_completed"] == "retrieve_completed"
    assert parsed["first_failed"] == "describe_copy_failed" and "NonRecoverableException" in parsed["first_failed_detail"]
    assert set(parsed["unfinished"]) == {"describe_started", "save_started"}
    assert TW.parse_checkpoints(tmp_path / "no_existe.log")["last_completed"] is None


def test_evaluation_keeps_bridge_checkpoints_as_evidence(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)

    class _CheckpointBridge(_FakeBridge):
        def __call__(self, request, work_dir, project_root=None, on_archived=None):
            path = Path(request["checkpoint_path"])
            assert path.parent.name.startswith("T") and len(str(path)) <= DE.TIA_ARCHIVE_MAX_PATH
            with path.open("a", encoding="utf-8") as log:
                for name in ("retrieve_started", "retrieve_completed", "tags_started", "tags_completed", "import_started",
                             "import_completed", "compile_started", "compile_completed", "save_started", "save_completed",
                             "archive_started", "archive_completed"):
                    log.write(f"2026-10-01T10:00:00.000\t{name}\t\n")
            return super().__call__(request, work_dir, project_root, on_archived=on_archived)

    result = _evaluate(root, trial_dir, _CheckpointBridge())
    attempt = trial_dir / "evaluation" / "attempt_001"
    assert (attempt / TW.CHECKPOINTS_FILENAME).is_file()  # evidencia permanente, independiente de tiaw/
    report = json.loads((attempt / DE.COMPILE_REPORT).read_text(encoding="utf-8"))
    assert report["checkpoints"]["last_completed"] == "archive_completed" and report["checkpoints"]["first_failed"] is None
    assert result["tia_last_completed_checkpoint"] == "archive_completed"
