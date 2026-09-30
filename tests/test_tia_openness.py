from __future__ import annotations

import json
from pathlib import Path

from tia_openness import _persist_tia_report, prepare_download_request, prepare_tia_request, save_tia_config


def test_prepare_tia_request_uses_authorized_tags(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    package_dir = project_root / "generated_code" / "SIEMENS" / "active" / "PKG_001"
    package_dir.mkdir(parents=True)
    (package_dir / "siemens_source.scl").write_text(
        'FUNCTION_BLOCK "PLC_PRG"\nEND_FUNCTION_BLOCK\n',
        encoding="utf-8"
    )
    (package_dir / "variables.json").write_text(
        json.dumps(
            [
                {"name": "I_Start", "class": "input", "location": "%IX0.0"},
                {"name": "Q_Motor_Enable", "class": "output", "location": "%QX0.0"},
                {"name": "M_RunLatch", "class": "internal", "location": ""}
            ]
        ),
        encoding="utf-8"
    )
    save_tia_config(
        {
            "project_path": "C:/TIA/Demo.ap18",
            "plc_name": "PLC_1",
            "attach_to_running": True,
            "with_user_interface": True,
            "create_plc_tags": True,
            "save_project_on_success": True,
            "compile_after_import": True
        },
        project_root
    )

    request_path, result_path, request = prepare_tia_request(package_dir, project_root)

    assert request_path.exists()
    assert result_path.name == "tia_compile_report.json"
    assert request["action"] == "import_compile"
    assert request["physical_download_allowed"] is False
    assert request["plc_name"] == "PLC_1"
    assert request["tags"] == [
        {"name": "I_Start", "data_type": "Bool", "address": "%I0.0"},
        {"name": "Q_Motor_Enable", "data_type": "Bool", "address": "%Q0.0"}
    ]


def test_tia_report_is_persisted_in_package_and_metadata(tmp_path: Path) -> None:
    siemens_root = tmp_path / "generated_code" / "SIEMENS"
    package_dir = siemens_root / "active" / "PKG_002"
    logs_dir = siemens_root / "logs"
    package_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)

    for file_name in (
        "verification.json",
        "project_manifest.json",
        "pou_manifest.json",
        "generation_metadata.json"
    ):
        (package_dir / file_name).write_text("{}", encoding="utf-8")

    metadata_path = logs_dir / "PKG_002_log.json"
    metadata_path.write_text(
        json.dumps(
            {
                "verification_result": {},
                "rendered_artifacts": {},
                "saved_paths": {}
            }
        ),
        encoding="utf-8"
    )
    report = {
        "status": "TIA_COMPILATION_PASSED",
        "error_count": 0,
        "warning_count": 0
    }

    _persist_tia_report(package_dir, report)

    verification = json.loads((package_dir / "verification.json").read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert verification["is_valid"] is True
    assert verification["compilation_status"] == "TIA_COMPILATION_PASSED"
    assert metadata["verification_result"]["is_compilable"] is True
    assert metadata["rendered_artifacts"]["tia_compile_report.json"] == report


def test_prepare_download_request_never_recompiles_or_reimports(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    package_dir = project_root / "generated_code" / "SIEMENS" / "active" / "PKG_003"
    package_dir.mkdir(parents=True)
    save_tia_config(
        {"project_path": "C:/TIA/Demo.ap18", "plc_name": "PLC_1"},
        project_root
    )

    request_path, result_path, request = prepare_download_request(package_dir, project_root)

    assert request_path.exists()
    assert request_path.name == "tia_download_request.json"
    assert result_path.name == "tia_download_report.json"
    assert request["action"] == "download"
    assert request["plc_name"] == "PLC_1"
    assert request["project_path"] == "C:/TIA/Demo.ap18"
    # La solicitud de descarga no lleva fuente SCL ni tags: no reimporta ni recompila,
    # solo referencia el proyecto/PLC ya configurados.
    assert "source_path" not in request
    assert "tags" not in request


def test_prepare_tia_request_includes_locked_tags_even_when_program_does_not_use_them(tmp_path: Path) -> None:
    """
    Section 5/18: LOCKED map entries (I_Start/I_Stop-style, part of the bench's fixed physical
    configuration) must stay in the desired tag set sent to TIA even when THIS SPECIFIC program's
    own variables.json never references them - otherwise the bridge's orphan-cleanup (section 7)
    would delete them from PLC_Agent_IO on any program that happens not to need them directly.
    A FREE channel with no functional purpose must never appear (section 19).
    """
    from plc_maps.registry import save_active_map_id
    from plc_maps.store import create_plc_map

    project_root = tmp_path / "project"
    map_path = create_plc_map(
        project_root,
        name="mapa_test",
        variables=[
            {"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX16.0", "state": "LOCKED"},
            {"name": "I_Stop", "class": "input", "type": "BOOL", "location": "%IX16.1", "state": "LOCKED"},
            {"name": "Q_Free1", "class": "output", "type": "BOOL", "location": "%QX8.5", "state": "FREE"}
        ]
    )
    save_active_map_id(project_root, map_path.stem)

    package_dir = project_root / "generated_code" / "SIEMENS" / "active" / "PKG_LOCKED"
    package_dir.mkdir(parents=True)
    (package_dir / "siemens_source.scl").write_text('FUNCTION_BLOCK "PLC_PRG"\nEND_FUNCTION_BLOCK\n', encoding="utf-8")
    (package_dir / "variables.json").write_text(
        json.dumps([{"name": "Q_Motor_1", "class": "output", "siemens_type": "Bool", "siemens_address": "%QX8.0"}]),
        encoding="utf-8"
    )
    save_tia_config({"project_path": "C:/TIA/Demo.ap18", "plc_name": "PLC_1"}, project_root)

    _, _, request = prepare_tia_request(package_dir, project_root)

    tag_names = {tag["name"] for tag in request["tags"]}
    assert tag_names == {"Q_Motor_1", "I_Start", "I_Stop"}
    tags_by_name = {tag["name"]: tag for tag in request["tags"]}
    assert tags_by_name["I_Start"]["address"] == "%I16.0"
    assert tags_by_name["I_Stop"]["address"] == "%I16.1"
    assert "Q_Free1" not in tag_names

def test_prepare_tia_request_never_leaks_a_previous_programs_tags_into_the_next(tmp_path: Path) -> None:
    """
    Section 29: each prepare_tia_request() call builds `tags` fresh from that specific package's
    own variables.json plus the active map's LOCKED entries - it must never accumulate or carry
    over tags from an earlier program's request. Program A uses Q_Motor/Q_Pilot_Run; program B
    (same active map, LOCKED I_Start/I_Stop) uses Q_Valve - B's request must contain ONLY
    I_Start, I_Stop, Q_Valve, never Q_Motor or Q_Pilot_Run.
    """
    from plc_maps.registry import save_active_map_id
    from plc_maps.store import create_plc_map

    project_root = tmp_path / "project"
    map_path = create_plc_map(
        project_root,
        name="mapa_test",
        variables=[
            {"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX16.0", "state": "LOCKED"},
            {"name": "I_Stop", "class": "input", "type": "BOOL", "location": "%IX16.1", "state": "LOCKED"}
        ]
    )
    save_active_map_id(project_root, map_path.stem)
    save_tia_config({"project_path": "C:/TIA/Demo.ap18", "plc_name": "PLC_1"}, project_root)

    package_a = project_root / "generated_code" / "SIEMENS" / "active" / "PKG_A"
    package_a.mkdir(parents=True)
    (package_a / "siemens_source.scl").write_text('FUNCTION_BLOCK "PLC_PRG"\nEND_FUNCTION_BLOCK\n', encoding="utf-8")
    (package_a / "variables.json").write_text(
        json.dumps([
            {"name": "Q_Motor", "class": "output", "siemens_type": "Bool", "siemens_address": "%QX8.0"},
            {"name": "Q_Pilot_Run", "class": "output", "siemens_type": "Bool", "siemens_address": "%QX8.1"}
        ]),
        encoding="utf-8"
    )
    _, _, request_a = prepare_tia_request(package_a, project_root)
    assert {tag["name"] for tag in request_a["tags"]} == {"I_Start", "I_Stop", "Q_Motor", "Q_Pilot_Run"}

    package_b = project_root / "generated_code" / "SIEMENS" / "active" / "PKG_B"
    package_b.mkdir(parents=True)
    (package_b / "siemens_source.scl").write_text('FUNCTION_BLOCK "PLC_PRG"\nEND_FUNCTION_BLOCK\n', encoding="utf-8")
    (package_b / "variables.json").write_text(
        json.dumps([{"name": "Q_Valve", "class": "output", "siemens_type": "Bool", "siemens_address": "%QX8.0"}]),
        encoding="utf-8"
    )
    _, _, request_b = prepare_tia_request(package_b, project_root)
    tag_names_b = {tag["name"] for tag in request_b["tags"]}
    assert tag_names_b == {"I_Start", "I_Stop", "Q_Valve"}
    assert "Q_Motor" not in tag_names_b
    assert "Q_Pilot_Run" not in tag_names_b
