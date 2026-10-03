"""
Fase 4A-DEFERRED: GENERAR ENSAYO (sin TIA/PLCSIM/Oracle) + EVALUAR ENSAYO GUARDADO (artefactos
congelados por hash, copia nueva del snapshot MASTER, .zap18 por ensayo, PLCSIM, Oracle).

TIA/PLCSIM reales nunca se ejecutan aqui: el bridge, la Runtime API y el Oracle se sustituyen por
dobles que registran lo que reciben. Todo se escribe en copias temporales del proyecto.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest

import gui  # noqa: E402
from trial_experiments import batch_runner as B  # noqa: E402
from trial_experiments import benchmark_catalog as BC  # noqa: E402
from trial_experiments import deferred_evaluator as DE  # noqa: E402
from trial_experiments import tia_classification as TC  # noqa: E402
from trial_experiments import trial_io_map, trial_model  # noqa: E402

from test_phase1_download_and_trials import _run, pipeline  # noqa: E402
from test_execute_full_pipeline import _base_semantic_output, temp_map, _tia_ready  # noqa: E402
from test_experiment_working_io_map import _allocating_parse, _use_bench_copy, bench_map  # noqa: E402

__all__ = ["pipeline", "temp_map", "_tia_ready", "bench_map"]

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)
_SCL = '''FUNCTION_BLOCK "PLC_PRG"
VAR_INPUT
END_VAR
BEGIN
END_FUNCTION_BLOCK

DATA_BLOCK "DB_PLC_PRG"
"PLC_PRG"
BEGIN
END_DATA_BLOCK

ORGANIZATION_BLOCK "Main"
BEGIN
   "DB_PLC_PRG"();
END_ORGANIZATION_BLOCK
'''


# ---------------------------------------------------------------------------------------------
# Proyecto temporal + ensayo generado + MASTER
# ---------------------------------------------------------------------------------------------

def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    for relative in ("data/experiment_oracles", "data/experiment_cases", "data/plc_maps", "config"):
        shutil.copytree(_ROOT / relative, root / relative)
    for relative in ("data/experimental_design.json", "data/system_capability_gaps.json"):
        shutil.copyfile(_ROOT / relative, root / relative)
    # Cada proyecto temporal arranca SIN la seleccion real de proyectos TIA (Normal/MASTER) del usuario.
    (root / "config" / "tia_projects.json").unlink(missing_ok=True)
    return root


def _generated_trial(root: Path, case_id: str = "D03", variant: str = "V1") -> Path:
    """Ensayo GENERADO como lo deja GENERAR ENSAYO (sin pasar por TIA)."""
    phase = trial_model.PHASE_BASELINE
    number = trial_model.next_trial_number(root, case_id, variant, "TEXT", phase)
    reference = BC.trial_benchmark_reference(root, case_id, variant)
    record = trial_model.new_trial_record(
        case_id, variant, "TEXT", number, command_text=reference.get("command_text", ""), complexity="LOW", phase=phase,
        extra={key: reference.get(key) for key in ("benchmark_version", "canonical_case_hash", "variant_hash")})
    directory = trial_model.trial_directory(root, case_id, variant, record["trial_id"], phase)
    trial_model.save_trial(directory, record)
    io_ref = trial_io_map.create_working_map(directory, root / "data" / "plc_maps" / "mapa_banco_fisico_base.json")
    semantic = _base_semantic_output("INT_MOTOR_START_STOP", {"start_input": "I_Start", "stop_input": "I_Stop",
                                                              "motor_output": "Q_Motor"}, ["I_Start", "I_Stop", "Q_Motor"])
    frozen = trial_io_map.freeze_working_map(io_ref, semantic, trial_io_map.STATE_PREPARING, record["trial_id"])
    trial_io_map.discard_working_map(frozen)
    (directory / DE.COMMAND_FILENAME).write_text(BC.get_case(root, case_id)["variants"][variant], encoding="utf-8")
    (directory / DE.SEMANTIC_FILENAME).write_text(json.dumps(semantic), encoding="utf-8")
    trial_model.update_trial(directory, {"stages": {"semantic_success": True, "verification_success": True},
                                         "io_map": trial_io_map.trial_record_reference(frozen)})
    package = directory.parent / f"pkg_{record['trial_id']}"
    package.mkdir()
    (package / "siemens_source.scl").write_text(_SCL, encoding="utf-8")
    (package / "variables.json").write_text(json.dumps([
        {"name": "I_Start", "type": "BOOL", "class": "input", "location": "%IX16.0", "siemens_type": "Bool", "siemens_address": "%I16.0"},
        {"name": "Q_Motor", "type": "BOOL", "class": "output", "location": "%QX8.0", "siemens_type": "Bool", "siemens_address": "%Q8.0"},
    ]), encoding="utf-8")
    DE.finalize_generation(root, directory, package)
    return directory


def _master(root: Path, managed: tuple[str, ...] = ("Main", "PLC_PRG", "DB_PLC_PRG"), unmanaged: tuple[str, ...] = ()) -> dict[str, Any]:
    folder = root / "tia_projects" / "MASTER"
    folder.mkdir(parents=True)
    (folder / "MASTER.ap18").write_bytes(b"ap18-master")
    (folder / "System").mkdir()
    (folder / "System" / "data.bin").write_bytes(b"system")
    DE.select_master(root, folder / "MASTER.ap18")

    def _bridge(request, work_dir, project_root=None):
        assert request["archive_name"].endswith(".zap18")
        archive = Path(request["archive_dir"]) / request["archive_name"]
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w") as zap:  # mismo layout que TIA V18: <targetName>.ap18 en la raiz
            zap.writestr(request["archive_name"] + ".ap18", b"master-project")
            zap.writestr("System/PEData.plf", b"system")
        blocks = [{"name": name, "type": "OB" if name == "Main" else "FB"} for name in managed + unmanaged]
        return {"status": "TIA_MASTER_VALIDATION_PASSED", "tia_version": "V18", "archive_path": str(archive),
                "archive_sha256": DE.sha256_file(archive), "archive_size_bytes": archive.stat().st_size,
                "master": {"project_name": "MASTER", "plc_count": 1, "plc_name": "PLC_1",
                           "cpu_type_identifier": "OrderNumber:6ES7 516-3AN02-0AB0/V2.9", "plc_agent_io_present": True,
                           "interfaces": [{"device_item": "PROFINET interface_1", "nodes": [{"name": "X1", "address": "192.168.0.1"}]}],
                           "blocks": blocks}}
    return DE.validate_master(root, bridge=_bridge)


class _FakeBridge:
    """Simula evaluate_trial del bridge y registra cada request."""

    def __init__(self, outcome: str = "PASS") -> None:
        self.outcome = outcome
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request, work_dir, project_root=None, on_archived=None):
        self.requests.append(request)
        self.decisions: list[dict[str, Any]] = getattr(self, "decisions", [])
        assert request["action"] == "evaluate_trial"
        for key in ("working_dir", "trial_archive_dir", "source_path", "master_archive_path", "handshake_dir"):
            assert len(request[key]) <= DE.TIA_ARCHIVE_MAX_PATH, key  # TIA solo ve rutas cortas
        working = Path(request["working_dir"])
        assert not working.exists(), "cada evaluacion parte de una copia NUEVA (nunca de un ensayo anterior)"
        working.mkdir(parents=True)
        (working / "copy.ap18").write_bytes(Path(request["master_archive_path"]).read_bytes())
        report: dict[str, Any] = {"tia_version": "V18", "working_project_path": str(working / "copy.ap18"),
                                  "imported_source_sha256": DE.sha256_file(Path(request["source_path"])),
                                  "removed_managed_blocks": [], "errors": []}
        if self.outcome == "NON_RECOVERABLE":
            report.update({"status": "TIA_OPENNESS_ERROR", "failed_stage": "generate_blocks",
                           "exception_type": "Siemens.Engineering.NonRecoverableException",
                           "exception": "Siemens.Engineering.NonRecoverableException: Unexpected exception",
                           "archive_status": "NOT_CREATED", "archive_error": "TIA no disponible"})
            return report
        if self.outcome == "CRASH":
            return {"status": "TIA_BRIDGE_CRASHED", "errors": ["El bridge termino sin reporte (codigo -1073741819)."]}
        compiled = self.outcome != "COMPILE_FAIL"
        report.update({"status": "TIA_COMPILATION_PASSED" if compiled else "TIA_COMPILATION_FAILED",
                       "error_count": 0 if compiled else 2, "warning_count": 0})
        assert request["trial_archive_name"].endswith(".zap18")
        archive = Path(request["trial_archive_dir"]) / request["trial_archive_name"]
        archive.write_bytes(b"trial-project-" + request["trial_archive_name"].encode())
        report.update({"archive_status": "CREATED", "archive_path": str(archive), "archive_sha256": DE.sha256_file(archive)})
        if self.outcome == "CORRUPT_AFTER_ARCHIVE":
            archive.write_bytes(b"corrupted")  # el .zap18 cambia entre Archive y la copia
        if compiled and request["download_after_archive"]:
            decision = on_archived({"archive_path": report["archive_path"], "archive_sha256": report["archive_sha256"]}) if on_archived else {"download": True}
            self.decisions.append(decision)
            if decision.get("download"):
                report["download"] = {"status": "TIA_DOWNLOAD_PASSED", "success": True, "target_type": "PLCSIM_ADVANCED",
                                      "start_module_requested": True, "start_module_success": True, "cpu_run_requested": True}
        return report


def _runtime(root):
    return {"status": "CONNECTED", "connected": True, "instance_name": "TESIS_PLC_SIM", "cpu_state": "RUN",
            "cpu_type": "CPU1516", "network_match": True, "network_status": "MATCH", "duration_ms": 120}


def _oracle_pass(oracle, snapshot_path, runtime_report, target_type, semantic_output=None, project_root=None, **kwargs):
    assert Path(snapshot_path).name == DE.SNAPSHOT_FILENAME  # el Oracle usa el snapshot congelado del ensayo
    return {"verdict": "PASS", "verdict_reason": "ALL_CHECKS_PASSED", "oracle_formal": True,
            "oracle_reference": {"oracle_id": oracle["oracle_id"]}, "roles": {"roles": {}, "issues": []},
            "functional": {"evaluated": True, "success": True, "passed_checks": 3, "total_checks": 3, "pass_rate": 1.0},
            "safety": {"evaluated": True, "success": True, "invariants_defined": 1, "critical_violations": 0, "samples_checked": 10},
            "preconditions": {"success": True}, "cleanup": {"performed": True, "success": True}, "duration_ms": 900,
            "trace": {"events": [], "samples": []}, "steps": [], "errors": [], "warnings": []}


@pytest.fixture
def no_regeneration(monkeypatch):
    """La evaluacion nunca puede volver a interpretar/asignar/generar."""
    import code_generator
    import io_allocator
    import llm_parser
    import semantic_parser

    def _boom(*args, **kwargs):
        raise AssertionError("La evaluacion diferida no debe volver a interpretar/asignar/generar.")

    for module, name in ((semantic_parser, "parse_command"), (llm_parser, "parse_with_llm"),
                         (io_allocator, "propose_assignment"), (code_generator, "generate_code")):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, _boom)


def _evaluate(root: Path, trial_dir: Path, bridge: _FakeBridge, retry_reason: str | None = None) -> dict[str, Any]:
    return DE.evaluate_trial(root, trial_dir, retry_reason, bridge=bridge, runtime_status_fn=_runtime,
                             oracle_fn=_oracle_pass, log=lambda _m: None)


# ---------------------------------------------------------------------------------------------
# GENERAR ENSAYO (GUI real, pipeline simulado)
# ---------------------------------------------------------------------------------------------

def test_generate_trial_never_opens_tia_plcsim_or_oracle(pipeline, bench_map, monkeypatch):
    app = pipeline["app"]
    _use_bench_copy(app, bench_map)
    calls: list[str] = []
    monkeypatch.setattr(gui, "validate_package_with_tia", lambda *a, **k: calls.append("tia") or {})
    monkeypatch.setattr(gui, "get_plcsim_runtime_status", lambda *a, **k: calls.append("plcsim") or {})
    monkeypatch.setattr(gui, "run_oracle", lambda *a, **k: calls.append("oracle") or {})
    monkeypatch.setattr(gui, "next_trial_id", lambda root: "TRIAL_TEST")
    monkeypatch.setattr(gui, "record_trial_summary", lambda *a, **k: None)
    parse, _ = _allocating_parse([{"functional_name_hint": "Q_Motor", "role_text": "motor"}],
                                 {"trigger_input": "I_Start", "output": "Q_Motor"}, ["I_Start", "Q_Motor"])
    monkeypatch.setattr(gui, "parse_command", parse)
    app.work_mode_var.set("Experimentacion")
    app._on_work_mode_changed()
    label = next(name for name, profile in app._experiment_profiles_by_case.items() if profile.get("case_id") == "D12")
    app.experiment_case_var.set(label)
    app._on_experiment_case_changed()
    app.experiment_variant_var.set("V2")
    app._on_experiment_variant_changed()

    trial_dir = app.generate_experiment_trial()

    assert calls == [] and pipeline["download_calls"] == []
    record = trial_model.load_trial(trial_dir)
    assert record["generation"]["status"] == DE.GENERATION_SUCCESS
    assert record["evaluation"]["status"] == DE.EVALUATION_PENDING
    assert record["lifecycle_state"] == DE.STATE_EVALUATION_PENDING and record["final_status"] is None
    assert record["trial_kind"] == "DEVELOPMENT_TRIAL" and "_DEV_" in record["trial_id"]
    manifest = json.loads((trial_dir / DE.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    for name in DE.FROZEN_ARTIFACTS:
        assert manifest["files"][name] == DE.sha256_file(trial_dir / name)
    assert manifest["oracle"]["oracle_hash"] and manifest["canonical_case_hash"] and manifest["variant_hash"]
    assert (trial_dir / DE.GENERATION_REPORT_FILENAME).exists() and not (trial_dir / "working_io_map.json").exists()
    assert app.active_trial is None
    app.work_mode_var.set("Normal")
    app._on_work_mode_changed()


# ---------------------------------------------------------------------------------------------
# Integridad
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("artifact", [DE.PROGRAM_FILENAME, DE.SNAPSHOT_FILENAME])
def test_changed_artifact_blocks_evaluation_without_opening_tia(tmp_path, artifact):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    with (trial_dir / artifact).open("a", encoding="utf-8") as handle:
        handle.write("\n// modificado")
    bridge = _FakeBridge()
    result = _evaluate(root, trial_dir, bridge)
    assert result["aborted"] and result["integrity_failed"]
    assert bridge.requests == []
    record = trial_model.load_trial(trial_dir)
    assert record["evaluation"]["status"] == DE.EVALUATION_INTEGRITY_FAILED
    assert record["lifecycle_state"] == DE.STATE_INTEGRITY_FAILED


def test_legacy_trial_without_manifest_is_unsupported(tmp_path):
    root = _project(tmp_path)
    trial_dir = _generated_trial(root)
    (trial_dir / DE.MANIFEST_FILENAME).unlink()
    check = DE.verify_trial_integrity(trial_dir)
    assert not check["ok"] and check["code"] == DE.ERROR_LEGACY
    assert not (trial_dir / DE.MANIFEST_FILENAME).exists()  # nunca se generan hashes retroactivos


# ---------------------------------------------------------------------------------------------
# Evaluacion completa (bridge/PLCSIM/Oracle simulados)
# ---------------------------------------------------------------------------------------------

def test_full_evaluation_uses_frozen_artifacts_and_fresh_master_copy(tmp_path, no_regeneration):
    root = _project(tmp_path)
    config = _master(root)
    master_hash = config["snapshot"]["archive_sha256"]
    fingerprint = DE.master_folder_fingerprint(config["path"])
    trial_dir = _generated_trial(root)
    bridge = _FakeBridge()

    result = _evaluate(root, trial_dir, bridge)

    assert result["final_status"] == "PASS" and result["evaluation_status"] == DE.EVALUATION_COMPLETED
    request = bridge.requests[0]
    # TIA importa la copia verificada del program.scl congelado dentro del workspace corto.
    assert Path(request["source_path"]).parent.parent == (root / "tiaw").resolve()
    assert DE.sha256_file(trial_dir / DE.PROGRAM_FILENAME) == json.loads(
        (trial_dir / DE.MANIFEST_FILENAME).read_text(encoding="utf-8"))["files"][DE.PROGRAM_FILENAME]
    assert Path(request["master_archive_path"]) == Path(config["snapshot"]["archive_path"]).resolve()
    assert request["require_simulation"] is True and request["target_type"] == "PLCSIM_ADVANCED"
    assert request["delete_blocks"] == []  # PLC_PRG/DB/Main los redefine el program.scl del ensayo
    assert {tag["name"] for tag in request["tags"]} >= {"I_Start", "Q_Motor", "I_Stop"}  # I_Stop: LOCKED del snapshot
    attempt = trial_dir / "evaluation" / "attempt_001"
    for name in (DE.COMPILE_REPORT, DE.DOWNLOAD_REPORT, DE.RUNTIME_REPORT, "evaluation_report.json", "oracle_trace.json"):
        assert (attempt / name).exists(), name
    manifest = json.loads((attempt / "tia" / DE.TIA_PROJECT_MANIFEST).read_text(encoding="utf-8"))
    evidence = attempt / "tia" / f"{trial_dir.name}.zap18"
    assert manifest["archive"]["copied_ok"] is True and Path(manifest["archive"]["evidence_path"]) == evidence
    assert manifest["archive"]["evidence_hash"] == manifest["archive"]["workspace_hash"] == DE.sha256_file(evidence)
    assert Path(manifest["archive"]["workspace_path"]).name == "T0001.zap18"  # nombre corto dentro del workspace
    assert manifest["tia_workspace_id"] == "T0001" and manifest["attempt_number"] == 1
    assert manifest["master_snapshot_hash"] == manifest["master"]["master_hash_after"] == master_hash
    assert manifest["generated_scl_hash"] == manifest["imported_scl_hash"]
    assert manifest["path_validation"]["max_path_length"] <= manifest["path_validation"]["limit"]
    assert not (root / "tiaw" / "T0001").exists()  # workspace limpiado tras evidencia verificada
    record = trial_model.load_trial(trial_dir)
    assert record["final_status"] == "PASS" and record["failure_category"] == "SUCCESS"
    assert record["generation"]["status"] == DE.GENERATION_SUCCESS and record["evaluation"]["final_verdict"] == "PASS"
    assert dict(DE.verdict_table(record))["TIA Archive"] == "PASS" and dict(DE.verdict_table(record))["FINAL"] == "PASS"
    # MASTER inmutable
    assert DE.sha256_file(Path(config["snapshot"]["archive_path"])) == master_hash
    assert DE.master_folder_fingerprint(config["path"]) == fingerprint
    # Una evaluacion completada no se repite
    again = _evaluate(root, trial_dir, bridge)
    assert again["aborted"] and len(bridge.requests) == 1


def test_trial_a_is_never_the_base_of_trial_b(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_a, trial_b = _generated_trial(root, "D03", "V1"), _generated_trial(root, "D03", "V2")
    bridge = _FakeBridge()
    _evaluate(root, trial_a, bridge)
    _evaluate(root, trial_b, bridge)
    first, second = bridge.requests
    assert first["master_archive_path"] == second["master_archive_path"]  # ambos parten del MASTER
    assert Path(first["working_dir"]).parent.name == "T0001" and Path(second["working_dir"]).parent.name == "T0002"
    assert first["trial_archive_dir"] != second["trial_archive_dir"] and first["working_dir"] != second["working_dir"]


def test_real_compile_failure_keeps_evidence_and_never_downloads(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    result = _evaluate(root, trial_dir, _FakeBridge("COMPILE_FAIL"))
    assert result["final_status"] == "FAIL" and result["failure_category"] == "COMPILE_FAILURE"
    assert result["tia_archive"] == "CREATED" and result["download_success"] is None
    attempt = trial_dir / "evaluation" / "attempt_001"
    assert (attempt / DE.COMPILE_REPORT).exists() and not (attempt / DE.DOWNLOAD_REPORT).exists()
    assert (attempt / "tia" / f"{trial_dir.name}.zap18").exists()
    # Un fallo del sistema nunca se reintenta.
    assert DE.precheck(root, trial_dir, "reintento")["ok"] is False


def test_non_recoverable_tia_is_infrastructure_and_retry_keeps_history(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    first = _evaluate(root, trial_dir, _FakeBridge("NON_RECOVERABLE"))
    assert first["final_status"] == "INFRASTRUCTURE_ERROR" and first["failure_category"] == "INFRASTRUCTURE_ERROR"
    assert first["tia_archive"] == "NOT_CREATED"
    record = trial_model.load_trial(trial_dir)
    assert record["tia_archive"]["status"] == "NOT_CREATED" and record["tia_archive"]["reason"]
    assert record["stages"]["compile_success"] is None  # nunca un COMPILE_FAILURE
    no_reason = _evaluate(root, trial_dir, _FakeBridge())
    assert no_reason["aborted"] and any(DE.ERROR_RETRY_REASON in e for e in no_reason["errors"])
    second = _evaluate(root, trial_dir, _FakeBridge(), retry_reason="TIA reiniciado tras falta de memoria")
    assert second["attempt"] == 2 and second["final_status"] == "PASS"
    attempts = trial_model.load_trial(trial_dir)["evaluation"]["attempts"]
    assert [a["attempt"] for a in attempts] == [1, 2] and attempts[0]["final_status"] == "INFRASTRUCTURE_ERROR"
    assert attempts[1]["retry_reason"] == "TIA reiniciado tras falta de memoria"
    assert (trial_dir / "evaluation" / "attempt_001" / DE.COMPILE_REPORT).exists()  # intento 1 intacto


def test_tia_process_death_is_infrastructure(tmp_path):
    root = _project(tmp_path)
    _master(root)
    trial_dir = _generated_trial(root)
    result = _evaluate(root, trial_dir, _FakeBridge("CRASH"))
    assert result["final_status"] == "INFRASTRUCTURE_ERROR" and result["evaluation_status"] == DE.EVALUATION_INFRASTRUCTURE


# ---------------------------------------------------------------------------------------------
# Clasificacion COMPILE vs INFRASTRUCTURE
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("report, expected", [
    ({"status": "TIA_COMPILATION_PASSED"}, TC.COMPILE_PASSED),
    ({"status": "TIA_COMPILATION_FAILED", "error_count": 3}, TC.COMPILE_FAILURE),
    ({"status": "TIA_COMPILATION_FAILED"}, TC.INFRASTRUCTURE_ERROR),
    ({"status": "TIA_OPENNESS_ERROR", "errors": ["Siemens.Engineering.NonRecoverableException: Unexpected exception"]},
     TC.INFRASTRUCTURE_ERROR),
    ({"status": "TIA_OPENNESS_ERROR", "exception_type": "Siemens.Engineering.EngineeringTargetInvocationException",
      "failed_stage": "generate_blocks"}, TC.COMPILE_FAILURE),
    ({"status": "TIA_OPENNESS_ERROR", "exception_type": "Siemens.Engineering.EngineeringTargetInvocationException",
      "failed_stage": "retrieve_master_copy"}, TC.INFRASTRUCTURE_ERROR),
    ({"status": "TIA_BRIDGE_TIMEOUT"}, TC.INFRASTRUCTURE_ERROR),
    ({"status": "TIA_BRIDGE_CRASHED"}, TC.INFRASTRUCTURE_ERROR),
    ({}, TC.INFRASTRUCTURE_ERROR),
    ({"status": "TIA_OPENNESS_ERROR", "errors": ["System.Runtime.InteropServices.COMException"]}, TC.INFRASTRUCTURE_ERROR),
])
def test_compile_vs_infrastructure_classification(report, expected):
    assert TC.classify_tia_compile(report)["category"] == expected


def test_immediate_pipeline_tia_crash_is_infrastructure_not_compile(pipeline):
    from test_phase1_download_and_trials import _arm_experiment_trial

    app = pipeline["app"]
    pipeline["state"]["compile_status"] = "TIA_OPENNESS_ERROR"
    trial_directory = _arm_experiment_trial(app)
    _run(app)
    record = trial_model.load_trial(trial_directory)
    assert record["final_status"] == "INFRASTRUCTURE_ERROR" and record["failure_category"] == "INFRASTRUCTURE_ERROR"
    assert record["stages"]["compile_success"] is None and pipeline["download_calls"] == []


# ---------------------------------------------------------------------------------------------
# MASTER
# ---------------------------------------------------------------------------------------------

def test_master_selection_validation_and_status(tmp_path):
    root = _project(tmp_path)
    with pytest.raises(ValueError):
        DE.select_master(root, tmp_path / "no_existe.ap18")
    config = _master(root)
    validation = config["validation"]
    # La validacion automatica nunca declara FORMAL_READY (requiere aprobacion explicita futura).
    assert validation["status"] == "VALID" and validation["master_status"] == DE.MASTER_DEVELOPMENT_READY
    assert validation["formal_ready_criteria_met"] is True
    assert validation["ip_addresses"] == ["192.168.0.1"] and validation["x1_interface_present"] is True
    assert DE.load_master_config(root)["snapshot"]["archive_sha256"] == DE.sha256_file(Path(config["snapshot"]["archive_path"]))
    assert validation["master_folder_fingerprint"] == validation["master_folder_fingerprint_after"]

    dev = DE.assess_master({"plc_count": 1, "cpu_type_identifier": "OrderNumber:6ES7 516-3AN02-0AB0",
                            "interfaces": [{"nodes": [{"name": "X1", "address": "192.168.0.1"}]}],
                            "blocks": [{"name": "Main"}, {"name": "Demo_Logic"}]})
    assert dev["master_status"] == DE.MASTER_DEVELOPMENT_READY and dev["unmanaged_blocks"] == ["Demo_Logic"]
    assert any(DE.WARNING_MASTER_LOGIC in w for w in dev["warnings"])
    bad = DE.assess_master({"plc_count": 1, "cpu_type_identifier": "OrderNumber:6ES7 214-1AG40-0XB0", "interfaces": []})
    assert bad["master_status"] == DE.MASTER_INVALID


def test_master_changes_block_evaluation(tmp_path):
    root = _project(tmp_path)
    config = _master(root)
    trial_dir = _generated_trial(root)
    (Path(config["path"]).parent / "System" / "data.bin").write_bytes(b"changed")
    check = DE.precheck(root, trial_dir)
    assert not check["ok"] and any(DE.ERROR_MASTER_CHANGED in e for e in check["errors"])
    (Path(config["path"]).parent / "System" / "data.bin").write_bytes(b"system")
    Path(config["snapshot"]["archive_path"]).write_bytes(b"tampered")
    check = DE.precheck(root, trial_dir)
    assert not check["ok"] and any(DE.ERROR_MASTER_INTEGRITY in e for e in check["errors"])


def test_unvalidated_master_or_physical_target_aborts(tmp_path):
    root = _project(tmp_path)
    trial_dir = _generated_trial(root)
    assert any(DE.ERROR_MASTER_NOT_CONFIGURED in e for e in DE.precheck(root, trial_dir)["errors"])
    _master(root)
    config_path = root / "config" / "tia_openness_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["download_targets"]["experiment"]["target_type"] = "PHYSICAL_PLC"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    bridge = _FakeBridge()
    result = _evaluate(root, trial_dir, bridge)
    assert result["aborted"] and bridge.requests == []


def test_app_managed_blocks_only(tmp_path):
    assert DE.declared_blocks(_SCL) == ["PLC_PRG", "DB_PLC_PRG", "Main"]
    root = _project(tmp_path)
    _master(root, managed=("Main", "PLC_PRG", "DB_PLC_PRG"), unmanaged=("Demo_Logic",))
    trial_dir = _generated_trial(root)
    (trial_dir / DE.PROGRAM_FILENAME).read_text(encoding="utf-8")
    bridge = _FakeBridge()
    _evaluate(root, trial_dir, bridge)
    assert "Demo_Logic" not in bridge.requests[0]["delete_blocks"]  # nunca se borra logica no administrada


# ---------------------------------------------------------------------------------------------
# GUI: siguiente pendiente nunca autoarranca
# ---------------------------------------------------------------------------------------------

def test_evaluate_next_pending_only_opens_summary(app, tmp_path, monkeypatch):
    root = _project(tmp_path)
    first, second = _generated_trial(root, "D03", "V1"), _generated_trial(root, "D03", "V2")
    monkeypatch.setattr(app, "project_root", root)
    monkeypatch.setattr(trial_model, "get_results_experiments_dir", lambda r: root / "results" / "experiments")
    opened: list[Path] = []

    class _Dialog:
        def __init__(self, parent, trial_dir, retry=False, autostart=False):
            opened.append(Path(trial_dir))

        def transient(self, parent):
            pass

    started: list[Any] = []
    monkeypatch.setattr(gui, "DeferredEvaluationDialog", _Dialog)
    monkeypatch.setattr(DE, "evaluate_trial", lambda *a, **k: started.append(a) or {})
    app.evaluate_next_pending()
    assert opened == [first] and started == []
    # Al terminar una evaluacion, la GUI no encadena la siguiente.
    app._deferred_queue.put(("ok", {"aborted": False, "final_status": "PASS", "failure_category": "SUCCESS"}))
    monkeypatch.setattr(app, "_deferred_dialog", None)
    app._poll_deferred_evaluation()
    assert opened == [first] and started == []
    assert DE.next_pending(root)["trial_dir"] in (str(first), str(second))


# ---------------------------------------------------------------------------------------------
# Consolidacion / batch / efectos secundarios
# ---------------------------------------------------------------------------------------------

def test_consolidation_from_evaluated_trials(tmp_path):
    root = _project(tmp_path)
    _master(root)
    _evaluate(root, _generated_trial(root, "D03", "V1"), _FakeBridge())
    _evaluate(root, _generated_trial(root, "D03", "V2"), _FakeBridge("COMPILE_FAIL"))
    _generated_trial(root, "D03", "V3")  # pendiente: no entra
    outputs = DE.consolidate(root, trial_model.PHASE_BASELINE)
    assert outputs["rows"] == "2"
    summary = json.loads(Path(outputs["summary_json"]).read_text(encoding="utf-8"))
    assert summary["overall"]["pass"] == 1
    failures = json.loads(Path(outputs["failures"]).read_text(encoding="utf-8"))
    assert [row["failure_category"] for row in failures] == ["COMPILE_FAILURE"]


def test_batch_timeout_is_recorded_as_attempt(tmp_path):
    root = _project(tmp_path)

    class _TimeoutDriver:
        def run(self, case_id, variant):
            phase = trial_model.PHASE_BASELINE
            record = trial_model.new_trial_record(case_id, variant, "TEXT", 1, phase=phase)
            directory = trial_model.trial_directory(root, case_id, variant, record["trial_id"], phase)
            trial_model.save_trial(directory, record)
            trial_model.finalize_trial(directory, "INFRASTRUCTURE_ERROR", [B.ERROR_TRIAL_TIMEOUT])
            raise B.BatchTrialTimeout("timeout", directory)

    result = B.run_baseline(root, driver=_TimeoutDriver(), skip_live_preflight=True, log=lambda _m: None)
    entry = B.load_queue(root)["entries"][0]
    assert result["executed"] == 1 and "timeout" in result["stop_reason"]
    assert entry["status"] == B.ENTRY_INFRASTRUCTURE and len(entry["attempts"]) == 1


def test_maps_oracles_and_benchmark_untouched():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
