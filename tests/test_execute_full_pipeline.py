"""
Regression tests for a real bug: EJECUTAR COMANDO (execute_full_pipeline) stopped silently after
"Verificacion completada" and never reached TIA Openness/compilation, even though
execute_full_pipeline() was ALREADY correctly wired as process_command() -> generate_package() ->
validate_latest_package_in_tia() (no premature return was ever added there). The real cause: an
earlier fix (semantic_repair.py, "banco sin I_Emergency") correctly stopped generating a literal
"I_Emergency" reference in SCL for a bench without that physical tag - but verifier.py still
UNCONDITIONALLY required the literal token "I_Emergency" to appear in generated code for several
intents (INTENT_TOKEN_RULES, the "critical outputs" check in verify_project_ir, and the
"motor/aux output must consider I_Emergency" check in verify_code), regardless of whether the
bench actually has it. That made verification.is_valid=False silently (no exception, no
messagebox - just a value generate_package() checks before returning True), so
generate_package() returned False and execute_full_pipeline() stopped there without ever calling
validate_latest_package_in_tia(). Fixed by making all three checks conditional on I_Emergency
being physically present.

Separately, per explicit user confirmation, the two human-confirmation dialogs that used to sit
between process_command()/generate_package() and between generate_package()/TIA import
(messagebox.askyesnocancel "Confirmar generacion", messagebox.askyesno "Confirmar TIA Openness")
were removed so EJECUTAR COMANDO can run the full pipeline (including TIA import/compile) with a
single click and no further interaction - "CARGAR PROGRAMA AL PLC" remains the only separate,
manual, physical-download step.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gui  # noqa: E402
from semantic_repair import strip_unavailable_emergency_reference  # noqa: E402


def _temp_map_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "metadata": {"map_id": "mapa_test_pipeline", "name": "MAPA_TEST_PIPELINE", "version": 1},
        "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_", "auxiliary": "R_"},
        "variables": [
            {"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX16.0", "initial_value": "FALSE", "description": "", "state": "LOCKED", "llm_allowed": True},
            {"name": "Q_Free1", "class": "output", "type": "BOOL", "location": "%QX8.0", "initial_value": "FALSE", "description": "", "state": "FREE", "llm_allowed": True},
            {"name": "Q_Motor_1", "class": "output", "type": "BOOL", "location": "%QX8.1", "initial_value": "FALSE", "description": "", "state": "ASSIGNED", "llm_allowed": True}
        ]
    }


@pytest.fixture
def temp_map(app, tmp_path, monkeypatch):
    map_path = tmp_path / "mapa_test_pipeline.json"
    map_path.write_text(json.dumps(_temp_map_payload(), indent=2), encoding="utf-8")
    original_path = app.io_map_path
    app.io_map_path = map_path
    app.io_variables = gui.load_io_map_variables(map_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    app.active_trial = None
    app.active_profile_id = None
    app.work_mode_var.set("Normal")
    app._on_work_mode_changed()
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    yield map_path
    app.io_map_path = original_path
    app.io_variables = gui.load_io_map_variables(original_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    app.active_trial = None
    app.active_profile_id = None
    app.command_textbox.delete("1.0", "end")
    app.pending_semantic_output = None


_RealThread = gui.threading.Thread


class _SyncThread:
    """
    Stand-in for threading.Thread that runs the target synchronously - the real
    validate_latest_package_in_tia() dispatches the TIA bridge call on a background thread and
    polls via self.after(), which would make tests depend on the Tk event loop's timing. Running
    the target immediately keeps these tests deterministic.

    IMPORTANT: `threading` is one shared module-level object - patching `gui.threading.Thread`
    replaces `Thread` for EVERY caller in the process, not just gui.py's. A test that exercises
    the REAL (unmocked) generate_project_package() can indirectly hit stdlib `subprocess.Popen`
    machinery, which also constructs its own `threading.Thread` internally (e.g. to read a
    captured pipe) - handing IT this fake class breaks with an unrelated, confusing
    `Popen._readerthread() missing ... arguments` error that has nothing to do with TIA. Only the
    exact call gui.py makes (`threading.Thread(target=..., name="tia-openness", daemon=True)`) is
    intercepted here; every other caller gets the real `threading.Thread` untouched.
    """

    def __new__(cls, target=None, name=None, daemon=None, **kwargs):
        if name != "tia-openness":
            return _RealThread(target=target, name=name, daemon=daemon, **kwargs)
        return super().__new__(cls)

    def __init__(self, target=None, name=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        if self._target:
            self._target()


def _base_semantic_output(intent_id: str, parameters: dict, recognized_tags: list[str]) -> dict[str, Any]:
    return {
        "intent_id": intent_id,
        "case_id": None,
        "command_text": "comando de prueba",
        "normalized_command": "comando de prueba",
        "parameters": parameters,
        "confidence": 0.95,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": recognized_tags,
        "unrecognized_terms": [],
        "functional_requirements": [],
        "semantic_validation": {
            "is_valid": True, "errors": [], "warnings": [], "missing_parameters": [],
            "unauthorized_tags": [], "requires_clarification": False
        }
    }


def _mock_package_result(package_dir: Path, is_valid: bool = True) -> dict[str, Any]:
    return {
        "verification": {"is_valid": is_valid, "errors": [] if is_valid else ["fallo simulado"], "warnings": []},
        "artifacts": {"package_dir": str(package_dir), "pou_path": str(package_dir / "implementation.st")},
        "project_ir": {"metadata": {"generated_functional_variables": []}},
        "rendered_files": {}
    }


@pytest.fixture
def _tia_ready(monkeypatch, tmp_path):
    """Mocks TIA as configured and ready, and swaps threading.Thread for a synchronous stand-in -
    the real Openness bridge/TIA Portal is never invoked."""
    monkeypatch.setattr(gui, "load_tia_config", lambda project_root: {"project_path": str(tmp_path / "fake_project.ap18")})
    monkeypatch.setattr(gui, "build_openness_bridge", lambda project_root: {"built": True})
    monkeypatch.setattr(
        gui, "diagnose_tia_openness",
        lambda project_root: {"is_ready": True, "project_path": str(tmp_path / "fake_project.ap18"), "warnings": []}
    )
    monkeypatch.setattr(gui.threading, "Thread", _SyncThread)


def _run_and_settle(app):
    """Runs execute_full_pipeline() then drains the (already-populated, thanks to _SyncThread)
    TIA worker queue exactly once, mirroring what self.after(250, self._poll_tia_worker) would do."""
    result = app.execute_full_pipeline()
    app._poll_tia_worker()
    return result


# ---------- Section 11: exito completo -> TIA callback llamado exactamente 1 vez ----------

def test_full_success_calls_tia_bridge_exactly_once(app, temp_map, tmp_path, monkeypatch, _tia_ready):
    semantic_output = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_output)
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    package_dir = tmp_path / "package"
    package_dir.mkdir()
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: _mock_package_result(package_dir))

    tia_calls: list[Path] = []

    def _fake_validate(package_dir_arg, project_root_arg):
        tia_calls.append(package_dir_arg)
        return {"status": "TIA_COMPILATION_PASSED", "result_path": str(package_dir / "tia_compile_report.json"), "bridge_return_code": 0, "bridge_stdout": "", "bridge_stderr": ""}

    monkeypatch.setattr(gui, "validate_package_with_tia", _fake_validate)

    app.command_textbox.insert("1.0", "enciende la salida")
    result = _run_and_settle(app)

    assert result is True
    assert len(tia_calls) == 1
    assert tia_calls[0] == package_dir


# ---------- Section 12: comando compuesto (MAP_CONFIG + logica) -> TIA callback == 1 ----------

def test_map_config_plus_logic_reaches_tia_exactly_once(app, temp_map, tmp_path, monkeypatch, _tia_ready):
    proposals = [{
        "address": "%QX8.0", "proposed_name": "Q_Motor_2", "current_name": "Q_Free1",
        "current_state": "FREE", "conflict": False, "blocked": False, "requires_confirmation": False,
        "reason": "Canal libre disponible en %QX8.0."
    }]
    semantic_output = {
        "intent_id": "INT_DIRECT_OUTPUT",
        "case_id": None,
        "command_text": "Usa Q8.0 para motor 2. Enciende el motor 2 con Start.",
        "normalized_command": "usa q8.0 para motor 2. enciende el motor 2 con start.",
        "parameters": {"trigger_input": "I_Start", "output": "Q_Motor_2"},
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": [],
        "unrecognized_terms": [],
        "operation_type": "MAP_CONFIG",
        "requested_io_assignments": [{"address_text": "Q8.0", "address": "%QX8.0", "role_text": "motor 2", "functional_name_hint": "Q_Motor_2"}],
        "functional_requirements": [],
        "semantic_validation": {
            "is_valid": False,
            "errors": ["Recurso externo no autorizado/no existente en el mapa PLC: Q_Motor_2"],
            "warnings": [], "missing_parameters": [], "unauthorized_tags": ["Q_Motor_2"],
            "requires_clarification": False, "io_assignment_proposals": proposals
        }
    }
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_output)
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    package_dir = tmp_path / "package_mixed"
    package_dir.mkdir()
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: _mock_package_result(package_dir))

    tia_calls: list[Path] = []
    monkeypatch.setattr(
        gui, "validate_package_with_tia",
        lambda package_dir_arg, project_root_arg: (
            tia_calls.append(package_dir_arg),
            {"status": "TIA_COMPILATION_PASSED", "result_path": str(package_dir / "tia_compile_report.json"), "bridge_return_code": 0, "bridge_stdout": "", "bridge_stderr": ""}
        )[1]
    )

    app.command_textbox.insert("1.0", semantic_output["command_text"])
    result = _run_and_settle(app)

    # ni MAP_CONFIG ni verification detuvieron el pipeline antes de tiempo.
    assert result is True
    assert len(tia_calls) == 1
    # el mapa SI se actualizo (Q_Motor_2 quedo asignado en el mapa temporal, no el real).
    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    names_by_address = {v["location"]: v["name"] for v in saved["variables"]}
    assert names_by_address["%QX8.0"] == "Q_Motor_2"


# ---------- Section 13: MAP_CONFIG puro -> actualiza mapa, termina, NUNCA llama TIA ----------

def test_pure_map_config_command_never_calls_tia(app, temp_map, tmp_path, monkeypatch, _tia_ready):
    proposals = [{
        "address": "%QX8.0", "proposed_name": "Q_Motor_2", "current_name": "Q_Free1",
        "current_state": "FREE", "conflict": False, "blocked": False, "requires_confirmation": False,
        "reason": "Canal libre disponible en %QX8.0."
    }]
    semantic_output = {
        "intent_id": "INT_UNKNOWN",
        "case_id": None,
        "command_text": "Usa Q8.0 para motor 2.",
        "normalized_command": "usa q8.0 para motor 2.",
        "parameters": {},
        "confidence": 0.9,
        "ambiguities": [],
        "requires_clarification": False,
        "clarification_question": None,
        "assumptions": [],
        "recognized_tags": [],
        "unrecognized_terms": [],
        "operation_type": "MAP_CONFIG",
        "requested_io_assignments": [{"address_text": "Q8.0", "address": "%QX8.0", "role_text": "motor 2", "functional_name_hint": "Q_Motor_2"}],
        "functional_requirements": [],
        "semantic_validation": {
            "is_valid": True, "errors": [], "warnings": [], "missing_parameters": [],
            "unauthorized_tags": [], "requires_clarification": False, "io_assignment_proposals": proposals
        }
    }
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_output)

    tia_calls: list[Path] = []
    monkeypatch.setattr(gui, "validate_package_with_tia", lambda *a, **k: tia_calls.append(a) or {})
    generate_calls = {"count": 0}
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: generate_calls.__setitem__("count", generate_calls["count"] + 1) or _mock_package_result(tmp_path))

    app.command_textbox.insert("1.0", semantic_output["command_text"])
    result = _run_and_settle(app)

    assert result is False  # pure config: nada que generar
    assert generate_calls["count"] == 0
    assert tia_calls == []
    saved = json.loads(temp_map.read_text(encoding="utf-8"))
    names_by_address = {v["location"]: v["name"] for v in saved["variables"]}
    assert names_by_address["%QX8.0"] == "Q_Motor_2"


# ---------- Section 14: verification -> TIA solo si pasa ----------

def test_verification_failure_never_calls_tia(app, temp_map, tmp_path, monkeypatch, _tia_ready):
    semantic_output = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_output)
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    package_dir = tmp_path / "package_invalid"
    package_dir.mkdir()
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: _mock_package_result(package_dir, is_valid=False))

    tia_calls: list[Path] = []
    monkeypatch.setattr(gui, "validate_package_with_tia", lambda *a, **k: tia_calls.append(a) or {})

    app.command_textbox.insert("1.0", "enciende la salida")
    result = _run_and_settle(app)

    assert result is False
    assert tia_calls == []


def test_verification_success_calls_tia(app, temp_map, tmp_path, monkeypatch, _tia_ready):
    """Contraparte directa del test anterior - mismo escenario, verification.is_valid=True."""
    semantic_output = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_output)
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    package_dir = tmp_path / "package_valid"
    package_dir.mkdir()
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: _mock_package_result(package_dir, is_valid=True))

    tia_calls: list[Path] = []
    monkeypatch.setattr(
        gui, "validate_package_with_tia",
        lambda package_dir_arg, project_root_arg: (
            tia_calls.append(package_dir_arg),
            {"status": "TIA_COMPILATION_PASSED", "result_path": str(package_dir / "tia_compile_report.json"), "bridge_return_code": 0, "bridge_stdout": "", "bridge_stderr": ""}
        )[1]
    )

    app.command_textbox.insert("1.0", "enciende la salida")
    result = _run_and_settle(app)

    assert result is True
    assert len(tia_calls) == 1


# ---------- Sin dialogos de confirmacion en ningun punto del pipeline automatico ----------

def test_no_confirmation_dialogs_anywhere_in_the_automatic_pipeline(app, temp_map, tmp_path, monkeypatch, _tia_ready):
    semantic_output = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_output)
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    package_dir = tmp_path / "package_no_dialog"
    package_dir.mkdir()
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: _mock_package_result(package_dir))
    monkeypatch.setattr(
        gui, "validate_package_with_tia",
        lambda package_dir_arg, project_root_arg: {
            "status": "TIA_COMPILATION_PASSED", "result_path": str(package_dir / "tia_compile_report.json"),
            "bridge_return_code": 0, "bridge_stdout": "", "bridge_stderr": ""
        }
    )

    def _fail_askyesnocancel(*a, **k):
        raise AssertionError("no debe abrirse askyesnocancel en el pipeline automatico")

    def _fail_askyesno(*a, **k):
        raise AssertionError("no debe abrirse askyesno en el pipeline automatico")

    monkeypatch.setattr(gui.messagebox, "askyesnocancel", _fail_askyesnocancel)
    monkeypatch.setattr(gui.messagebox, "askyesno", _fail_askyesno)

    app.command_textbox.insert("1.0", "enciende la salida")
    result = _run_and_settle(app)

    assert result is True


# ---------- Section 14: end-to-end REAL (sin mockear generate_project_package) con el comando ----
# ---------- exacto reportado (INT_DELAYED_STOP, mapa sin I_Emergency) -------------------------

def _delayed_stop_map_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "metadata": {"map_id": "mapa_test_delayed_stop", "name": "MAPA_TEST_DELAYED_STOP", "version": 1},
        "naming_convention": {"inputs": "I_", "outputs": "Q_", "internal_memory": "M_", "timers": "T_", "counters": "C_", "auxiliary": "R_"},
        "variables": [
            {"name": "I_Start", "class": "input", "type": "BOOL", "location": "%IX16.0", "initial_value": "FALSE", "description": "", "state": "LOCKED", "llm_allowed": True},
            {"name": "I_Stop", "class": "input", "type": "BOOL", "location": "%IX16.1", "initial_value": "FALSE", "description": "", "state": "LOCKED", "llm_allowed": True},
            {"name": "Q_Motor_Enable", "class": "output", "type": "BOOL", "location": "%QX8.0", "initial_value": "FALSE", "description": "", "state": "ASSIGNED", "llm_allowed": True}
            # Deliberadamente SIN I_Emergency - el banco fisico real no lo tiene.
        ]
    }


@pytest.fixture
def delayed_stop_map(app, tmp_path, monkeypatch):
    map_path = tmp_path / "mapa_test_delayed_stop.json"
    map_path.write_text(json.dumps(_delayed_stop_map_payload(), indent=2), encoding="utf-8")
    original_path = app.io_map_path
    app.io_map_path = map_path
    app.io_variables = gui.load_io_map_variables(map_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    app.active_trial = None
    app.active_profile_id = None
    app.work_mode_var.set("Normal")
    app._on_work_mode_changed()
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    yield map_path
    app.io_map_path = original_path
    app.io_variables = gui.load_io_map_variables(original_path)
    app._load_active_map_metadata_shadow()
    app._load_io_map_table()
    app.active_trial = None
    app.active_profile_id = None
    app.command_textbox.delete("1.0", "end")
    app.pending_semantic_output = None


def test_real_delayed_stop_command_without_i_emergency_reaches_tia_exactly_once(
    app, delayed_stop_map, tmp_path, monkeypatch, _tia_ready
) -> None:
    """
    Regresion end-to-end del comando exacto reportado - NO mockea generate_project_package, para
    ejercitar la reparacion semantica + IR + codegen + verifier reales de punta a punta, tal como
    ocurre desde la GUI real: "Enciende un motor con el pulsante de start, y que este se apague 3
    segundos despues de presionar el pulsante de stop" (INT_DELAYED_STOP), contra un mapa sin
    I_Emergency. Antes de la correccion esto fallaba con "La IR usa variables no declaradas:
    I_Emergency" y nunca llegaba a llamar a TIA.
    """
    semantic_output = _base_semantic_output(
        "INT_DELAYED_STOP",
        {
            "trigger_input": "I_Start", "stop_input": "I_Stop", "motor_output": "Q_Motor_Enable",
            "run_latch": "M_RunLatch", "stop_delay_active": "M_StopDelayActive",
            "stop_delay_time": "T#3s", "timer": "T_StopDelay"
            # emergency_input DELIBERADAMENTE ausente - shape real que devolvio el LLM reportado.
        },
        ["I_Start", "I_Stop", "Q_Motor_Enable", "M_RunLatch", "M_StopDelayActive", "T_StopDelay"]
    )

    def _fake_parse_command(command_text, **kwargs):
        # gui.py confia en el resultado de parse_command() tal cual, sin reparar nada por su
        # cuenta - la reparacion semantica (incluida strip_unavailable_emergency_reference) ocurre
        # DENTRO de la implementacion real de parse_command (llm_parser._repair_and_validate, en
        # cada uno de sus caminos: reglas/LLM/retry/fallback). Mockear gui.parse_command completo
        # sin aplicar esa reparacion simularia un comportamiento que parse_command nunca tiene en
        # produccion - por eso se reproduce aqui explicitamente contra el mismo io_map que gui.py
        # le pasa de verdad.
        io_map = kwargs.get("io_map") or {}
        return strip_unavailable_emergency_reference(semantic_output, io_map)

    monkeypatch.setattr(gui, "parse_command", _fake_parse_command)
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    tia_calls: list[Path] = []

    def _fake_validate(package_dir_arg, project_root_arg):
        tia_calls.append(package_dir_arg)
        return {
            "status": "TIA_COMPILATION_PASSED", "result_path": str(package_dir_arg / "tia_compile_report.json"),
            "bridge_return_code": 0, "bridge_stdout": "", "bridge_stderr": ""
        }

    monkeypatch.setattr(gui, "validate_package_with_tia", _fake_validate)

    app.command_textbox.insert(
        "1.0",
        "Enciende un motor con el pulsante de start, y que este se apague 3 segundos despues de presionar el pulsante de stop"
    )
    result = _run_and_settle(app)

    assert result is True
    assert len(tia_calls) == 1
