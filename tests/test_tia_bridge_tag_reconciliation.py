"""
Regression tests for a real production bug: TIA Openness aborted import/compile entirely with
"Authorized tag conflict for I_Start. Existing: Bool %I0.0; requested: Bool %I16.0" whenever the
TIA project's PLC tag for a LOCKED map resource (I_Start/I_Stop/...) was at a stale address left
over from an earlier project configuration, even though the ACTIVE map
(data/plc_maps/mapa_banco_fisico.json) is the single source of truth and should have won.

Root cause: tia_openness_bridge/Program.cs::EnsureTags treated ANY existing-tag mismatch (address
OR type) as a hard, unconditional error - it never attempted to reconcile TIA's tag with the
requested one. Fixed by giving EnsureTags an actual reconciliation policy (section 3 of the
request): same name+type+different address -> update PlcTag.LogicalAddress in place (confirmed via
reflection against Siemens.Engineering.dll that PlcTag exposes a public LogicalAddress setter, so
Delete+Create is never needed for this case); name absent -> create; incompatible type -> hard
error, never silently converted; requested address already occupied by a DIFFERENT tag name inside
the app's own PLC_Agent_IO table -> the stale occupant is deleted first (never two active tags on
the same address). Failures during this stage now surface as a distinct "TIA_TAG_SYNC_ERROR"
status (via a new TagSynchronizationException type) instead of a generic "TIA_OPENNESS_ERROR", so
Python/gui.py can tell tag reconciliation apart from a later import/compile failure.

These tests exercise:
  1. The real compiled bridge exe's "self_test" action (Program.cs::RunSelfTest) - deterministic
     NormalizeAddress assertions (%IX16.0 == %I16.0, %I0.0 != %I16.0, ...) that run WITHOUT
     opening TIA Portal, using the exact same build/run infrastructure as production (no new C#
     test framework introduced - there was none before, and none is added now). Skipped if the
     Siemens Openness compiler/DLLs are not present on this machine.
  2. Python/GUI-level handling of a mocked "TIA_TAG_SYNC_ERROR" report: the pipeline must treat it
     as a real failure (never silently pass), never advance last_successful_tia_package, and the
     status string must reach the console log so the failure stage is visible.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402
from tia_openness import build_openness_bridge  # noqa: E402
from utils import get_project_root  # noqa: E402

from test_execute_full_pipeline import (  # noqa: E402
    _base_semantic_output,
    _mock_package_result,
    _run_and_settle,
    temp_map,
    _tia_ready,
)

__all__ = ["temp_map", "_tia_ready"]


# ---------- Section 18/21.7: real bridge self-test (NormalizeAddress), no TIA connection --------

def test_bridge_normalize_address_self_test(tmp_path: Path) -> None:
    project_root = get_project_root()
    build_result = build_openness_bridge(project_root)
    if not build_result.get("built"):
        pytest.skip(f"TIA Openness bridge could not be built in this environment: {build_result.get('errors')}")

    exe_path = Path(build_result["exe_path"])
    request_path = tmp_path / "self_test_request.json"
    result_path = tmp_path / "self_test_result.json"
    request_path.write_text(
        json.dumps({"action": "self_test", "result_path": str(result_path)}),
        encoding="utf-8"
    )

    completed = subprocess.run(
        [str(exe_path), str(request_path)],
        capture_output=True, text=True, timeout=30, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    report = json.loads(result_path.read_text(encoding="utf-8"))
    assert report["status"] == "SELF_TEST_PASSED", report.get("errors")
    address_checks = {
        (check["left"], check["right"]): check for check in report["checks"] if "left" in check
    }
    assert address_checks[("%IX16.0", "%I16.0")]["actual_equal"] is True
    assert address_checks[("%QX8.0", "%Q8.0")]["actual_equal"] is True
    assert address_checks[("%MX0.3", "%M0.3")]["actual_equal"] is True
    assert address_checks[("%I0.0", "%I16.0")]["actual_equal"] is False
    assert address_checks[("%Q8.0", "%Q8.1")]["actual_equal"] is False

    # Seccion 26/16/27: PlanTagReconciliation (huerfanas, LOCKED persistentes, programa A -> B).
    plan_checks = {check["bucket"]: check for check in report["checks"] if "bucket" in check}
    assert plan_checks["section26.delete"]["actual"] == ["B", "C"]
    assert plan_checks["section26.create"]["actual"] == ["D"]
    assert plan_checks["section16.delete"]["actual"] == ["Q_Motor", "Q_Pilot_Run"]
    assert plan_checks["section27.delete"]["actual"] == ["Q_OldMotor"]
    assert set(plan_checks["section27.keep"]["actual"]) == {"I_Start", "I_Stop"}

    assert all(check["passed"] for check in report["checks"])


# ---------- Section 19: mocked bridge reports at the Python/GUI level ----------------------------

def test_tag_sync_error_report_is_treated_as_a_real_failure(
    app, temp_map, tmp_path, monkeypatch, _tia_ready
) -> None:
    semantic_output = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_output)
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    package_dir = tmp_path / "package"
    package_dir.mkdir()
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: _mock_package_result(package_dir))

    def _fake_validate(package_dir_arg, project_root_arg):
        return {
            "status": "TIA_TAG_SYNC_ERROR",
            "result_path": str(package_dir_arg / "tia_compile_report.json"),
            "bridge_return_code": 1,
            "bridge_stdout": "",
            "bridge_stderr": (
                "[TIA TAGS] I_Start existing=%I0.0 requested=%I16.0\n"
                "Two requested tags target the same address %I16.0: I_Start and I_Old."
            ),
            "errors": ["Two requested tags target the same address %I16.0: I_Start and I_Old."]
        }

    monkeypatch.setattr(gui, "validate_package_with_tia", _fake_validate)

    app.command_textbox.insert("1.0", "enciende la salida")
    result = _run_and_settle(app)

    # execute_full_pipeline() devuelve True en cuanto logra ENTREGAR el paquete a TIA (arranca el
    # worker de fondo con exito) - el resultado de la compilacion/sincronizacion en si misma llega
    # despues, de forma asincrona, via _poll_tia_worker (ya drenado aqui por _run_and_settle). El
    # indicador real de exito/fallo de TIA es _last_compiled_package_dir y el log, no este valor.
    assert result is True
    assert app._tia_worker_active is False, "el lock debe liberarse igual aunque la sincronizacion de tags falle"
    assert app._last_compiled_package_dir is None, "un TIA_TAG_SYNC_ERROR nunca debe habilitar la descarga al PLC"
    console_text = app.console_textbox.get("1.0", "end")
    assert "TIA_TAG_SYNC_ERROR" in console_text, "el status especifico debe llegar al log, no un generico"


def test_tag_sync_success_status_still_requires_compilation_passed(
    app, temp_map, tmp_path, monkeypatch, _tia_ready
) -> None:
    """
    A report where tag sync succeeded but compilation itself still failed (a later stage) must
    NOT be confused with TAG_SYNC_ERROR - status strings stay distinct per stage (section 17).
    """
    semantic_output = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_output)
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    package_dir = tmp_path / "package"
    package_dir.mkdir()
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: _mock_package_result(package_dir))

    def _fake_validate(package_dir_arg, project_root_arg):
        return {
            "status": "TIA_COMPILATION_FAILED",
            "result_path": str(package_dir_arg / "tia_compile_report.json"),
            "bridge_return_code": 1,
            "bridge_stdout": "",
            "bridge_stderr": "",
            "tags": {"table": "PLC_Agent_IO", "requested": 2, "created": 0, "updated": 1, "existing": 1}
        }

    monkeypatch.setattr(gui, "validate_package_with_tia", _fake_validate)

    app.command_textbox.insert("1.0", "enciende la salida")
    result = _run_and_settle(app)

    assert result is True  # ver comentario equivalente arriba: True = "se entrego a TIA"
    assert app._tia_worker_active is False
    assert app._last_compiled_package_dir is None, "TIA_COMPILATION_FAILED nunca debe habilitar la descarga al PLC"
