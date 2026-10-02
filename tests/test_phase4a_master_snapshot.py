"""
Snapshot del TIA MASTER (correccion tras la validacion real): Project.Archive usa targetName
LITERALMENTE como nombre del archivo, asi que el nombre debe llevar .zap18 explicito y la ruta
esperada es exactamente directorio/targetName. Sin un .zap18 verificado el MASTER es INVALID.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import tia_projects  # noqa: E402
from trial_experiments import deferred_evaluator as DE  # noqa: E402

from test_phase4a_deferred_evaluation import _project  # noqa: E402

_DESCRIPTION = {"project_name": "S71500_MASTER", "plc_count": 1, "plc_name": "PLC_1",
                "cpu_type_identifier": "OrderNumber:6ES7 516-3AN02-0AB0/V2.9", "plc_agent_io_present": False,
                "interfaces": [{"device_item": "PROFINET interface_1", "nodes": [{"name": "X1", "address": "192.168.0.1"}]},
                               {"device_item": "DP interface_1", "nodes": [{"name": "X3", "address": "2"}]}],
                "blocks": [{"name": "Main", "type": "OB"}, {"name": "Demo", "type": "FB"}]}


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = _project(tmp_path)
    normal_dir = root / "tia_projects" / "S71500_Prueba"
    normal_dir.mkdir(parents=True)
    normal = normal_dir / "S71500_Prueba.ap18"
    normal.write_bytes(b"normal-project")
    tia_projects.set_normal_project(root, normal)
    master_dir = root / "tia_projects" / "S71500_MASTER"
    master_dir.mkdir(parents=True)
    master = master_dir / "S71500_MASTER.ap18"
    master.write_bytes(b"master-project")
    (master_dir / "System").mkdir()
    (master_dir / "System" / "x.bin").write_bytes(b"sys")
    DE.select_master(root, master)
    return root, normal, master


class _Bridge:
    """Simula validate_master del bridge con distintos comportamientos de Project.Archive."""

    def __init__(self, mode: str = "OK") -> None:
        self.mode = mode
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request, work_dir, project_root=None):
        self.requests.append(request)
        directory = Path(request["archive_dir"])
        assert directory.is_dir(), "el directorio del snapshot existe antes de archivar"
        expected = directory / request["archive_name"]
        report: dict[str, Any] = {"tia_version": "V18", "master": _DESCRIPTION, "errors": [], "warnings": [],
                                  "archive_target_directory": str(directory), "archive_target_name": request["archive_name"],
                                  "archive_expected_path": str(expected), "archive_mode": "Compressed"}
        if self.mode == "OK":
            expected.write_bytes(b"PK\x03\x04snapshot")
            return {**report, "status": "TIA_MASTER_VALIDATION_PASSED", "archive_path": str(expected),
                    "archive_sha256": DE.sha256_file(expected), "archive_size_bytes": expected.stat().st_size}
        if self.mode == "LIKE_REAL_TIA_WITHOUT_EXTENSION":
            # Lo que hizo TIA real con un targetName sin extension: archivo con el nombre literal.
            created = directory / Path(request["archive_name"]).stem
            created.write_bytes(b"PK\x03\x04snapshot")
            return {**report, "status": "TIA_MASTER_VALIDATION_PASSED", "archive_path": str(created),
                    "archive_sha256": DE.sha256_file(created)}
        if self.mode == "MISSING":
            return {**report, "status": "TIA_MASTER_VALIDATION_PASSED", "archive_path": str(expected), "archive_sha256": "0" * 64}
        if self.mode == "EMPTY":
            expected.write_bytes(b"")
            return {**report, "status": "TIA_MASTER_VALIDATION_PASSED", "archive_path": str(expected),
                    "archive_sha256": DE.sha256_file(expected)}
        if self.mode == "UNSAVED":
            return {**report, "status": "MASTER_UNSAVED_CHANGES", "errors": ["El MASTER tiene cambios sin guardar"]}
        if self.mode == "ARCHIVE_EXCEPTION":
            return {**report, "status": "MASTER_ARCHIVE_FAILED", "errors": ["MASTER_ARCHIVE_FAILED: rechazado"],
                    "archive_error_type": "Siemens.Engineering.EngineeringTargetInvocationException",
                    "archive_error_hint": "TIA rechazo el archivado (p.ej. cambios sin guardar en el proyecto abierto)."}
        if self.mode == "OPEN_FAILED":
            return {"status": "MASTER_OPEN_FAILED", "tia_version": "V18", "errors": ["no se pudo abrir"], "warnings": []}
        if self.mode == "TOUCH_MASTER":
            (Path(request["master_project_path"]).parent / "System" / "x.bin").write_bytes(b"changed")
            expected.write_bytes(b"PK\x03\x04snapshot")
            return {**report, "status": "TIA_MASTER_VALIDATION_PASSED", "archive_path": str(expected),
                    "archive_sha256": DE.sha256_file(expected)}
        raise AssertionError(self.mode)


def test_target_name_is_explicit_zap18_and_matches_expected_path(tmp_path):
    root, _, master = _setup(tmp_path)
    target = DE.master_snapshot_target(root, master, stamp="20261001_120000")
    assert target["target_name"] == "M261001120000.zap18"  # nombre corto: el proyecto interno hereda este nombre
    assert Path(target["expected_path"]) == Path(target["directory"]) / target["target_name"]
    assert not Path(target["directory"]).is_relative_to(master.parent)  # nunca dentro del MASTER
    bridge = _Bridge("OK")
    DE.validate_master(root, bridge=bridge)
    request = bridge.requests[0]
    assert request["archive_name"].endswith(".zap18") and Path(request["archive_dir"]).is_dir()


def test_valid_snapshot_is_hashed_and_master_development_ready(tmp_path):
    root, normal, master = _setup(tmp_path)
    normal_bytes, fingerprint = normal.read_bytes(), DE.master_folder_fingerprint(master)
    config = DE.validate_master(root, bridge=_Bridge("OK"))
    validation = config["validation"]
    assert validation["status"] == "VALID" and config["status"] == DE.MASTER_DEVELOPMENT_READY  # bloque Demo no administrado
    assert config["hash"] == config["snapshot"]["archive_sha256"] == DE.sha256_file(Path(config["snapshot"]["archive_path"]))
    assert config["snapshot"]["archive_path"].endswith(".zap18")
    assert validation["cpu_type_identifier"].startswith("OrderNumber:6ES7 516") and validation["ip_addresses"] == ["192.168.0.1"]
    assert validation["x1_interface_present"] is True and validation["plc_agent_io"] == "CREATABLE"
    assert validation["archive"]["archive_mode"] == "Compressed"
    assert normal.read_bytes() == normal_bytes and DE.master_folder_fingerprint(master) == fingerprint


def _assert_invalid(config: dict[str, Any], code: str) -> None:
    validation = config["validation"]
    assert validation["status"] == "INVALID" and config["status"] == DE.MASTER_INVALID
    assert config["snapshot"] is None and config["hash"] is None
    assert any(code in error for error in validation["errors"]), validation["errors"]


def test_real_tia_behaviour_without_extension_is_reported_not_masked(tmp_path):
    root, _, _ = _setup(tmp_path)
    config = DE.validate_master(root, bridge=_Bridge("LIKE_REAL_TIA_WITHOUT_EXTENSION"))
    _assert_invalid(config, DE.ERROR_MASTER_ARCHIVE_NOT_CREATED)
    # La descripcion del MASTER no se pierde aunque falle el archivado.
    assert config["validation"]["cpu_type_identifier"] and config["validation"]["ip_addresses"] == ["192.168.0.1"]


def test_missing_snapshot_is_invalid(tmp_path):
    root, _, _ = _setup(tmp_path)
    _assert_invalid(DE.validate_master(root, bridge=_Bridge("MISSING")), DE.ERROR_MASTER_ARCHIVE_NOT_CREATED)


def test_empty_snapshot_is_invalid(tmp_path):
    root, _, _ = _setup(tmp_path)
    _assert_invalid(DE.validate_master(root, bridge=_Bridge("EMPTY")), DE.ERROR_MASTER_ARCHIVE_EMPTY)


def test_bridge_error_codes_are_distinguished(tmp_path):
    root, _, _ = _setup(tmp_path)
    _assert_invalid(DE.validate_master(root, bridge=_Bridge("UNSAVED")), DE.ERROR_MASTER_UNSAVED_CHANGES)
    config = DE.validate_master(root, bridge=_Bridge("ARCHIVE_EXCEPTION"))
    _assert_invalid(config, DE.ERROR_MASTER_ARCHIVE_FAILED)
    assert config["validation"]["archive"]["archive_error_type"].endswith("EngineeringTargetInvocationException")
    _assert_invalid(DE.validate_master(root, bridge=_Bridge("OPEN_FAILED")), DE.ERROR_MASTER_OPEN_FAILED)


def test_master_change_during_validation_is_invalid(tmp_path):
    root, _, _ = _setup(tmp_path)
    _assert_invalid(DE.validate_master(root, bridge=_Bridge("TOUCH_MASTER")), DE.ERROR_MASTER_CHANGED_DURING_VALIDATION)


def test_no_development_ready_without_zap18_even_with_valid_cpu(tmp_path):
    root, _, _ = _setup(tmp_path)
    for mode in ("MISSING", "EMPTY", "LIKE_REAL_TIA_WITHOUT_EXTENSION", "ARCHIVE_EXCEPTION"):
        config = DE.validate_master(root, bridge=_Bridge(mode))
        assert config["status"] == DE.MASTER_INVALID, mode


def test_snapshot_check_helper():
    assert DE.check_snapshot_file(None, None) == (DE.ERROR_MASTER_ARCHIVE_NOT_CREATED, None)


def test_archive_path_limit_is_enforced_before_calling_tia(tmp_path, monkeypatch):
    import pytest

    root, _, master = _setup(tmp_path)
    monkeypatch.setattr(DE, "TIA_ARCHIVE_MAX_PATH", 143)  # limite real de TIA V18
    target = DE.master_snapshot_target(root, master)
    bridge = _Bridge("OK")
    if len(target["expected_path"]) > 143:
        with pytest.raises(ValueError, match=DE.ERROR_MASTER_ARCHIVE_PATH_TOO_LONG):
            DE.validate_master(root, bridge=bridge)
        assert bridge.requests == []  # nunca se llama a TIA con una ruta que va a rechazar
    real = DE.master_snapshot_target(Path(r"D:\Documentos\Automatizacion para la Industria 4.0\TESIS\Software\voz_llm_plc_agent"),
                                     "S71500_MASTER.ap18", stamp="20261001_124544")
    assert len(real["expected_path"]) <= 143  # la ruta real del proyecto cabe con el nombre corto


def test_tia_search_index_is_not_master_content(tmp_path):
    root, _, master = _setup(tmp_path)
    before = DE.master_folder_fingerprint(master)
    index = master.parent / "IM" / "SearchIndex"
    index.mkdir(parents=True)
    (index / "segments_2g").write_bytes(b"lucene")
    assert DE.master_folder_fingerprint(master) == before  # TIA regenera el indice al abrir
    (master.parent / "System" / "x.bin").write_bytes(b"cambio real")
    assert DE.master_folder_fingerprint(master) != before


def test_ip_list_only_contains_ipv4():
    info = {**_DESCRIPTION, "interfaces": [{"device_item": "PROFINET interface_1", "nodes": [{"address": "192.168.0.1"}]},
                                           {"device_item": "DP interface_1", "nodes": [{"address": "2"}]}]}
    assert DE.assess_master(info)["ip_addresses"] == ["192.168.0.1"]


def test_x1_is_detected_by_node_name_and_auto_validation_never_formal():
    info = {**_DESCRIPTION, "blocks": []}
    result = DE.assess_master(info)
    assert result["x1_interface_present"] is True and result["x1_ip_address"] == "192.168.0.1"
    assert result["master_status"] == DE.MASTER_DEVELOPMENT_READY and result["formal_ready_criteria_met"] is True
    no_x1 = DE.assess_master({**info, "interfaces": [{"device_item": "DP interface_1", "nodes": [{"name": "X3", "address": "2"}]}]})
    assert no_x1["x1_interface_present"] is False and no_x1["master_status"] == DE.MASTER_INVALID


def test_master_without_x1_ip_is_invalid():
    info = {**_DESCRIPTION, "interfaces": [{"device_item": "PROFINET interface_2", "nodes": [{"name": "X2", "address": "192.168.1.1"}]}]}
    result = DE.assess_master(info)
    assert result["master_status"] == DE.MASTER_INVALID and any("X1" in error for error in result["errors"])
