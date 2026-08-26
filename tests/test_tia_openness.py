from __future__ import annotations

import json
from pathlib import Path

from tia_openness import _persist_tia_report, prepare_tia_request, save_tia_config


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

