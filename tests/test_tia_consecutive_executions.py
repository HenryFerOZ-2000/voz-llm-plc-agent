"""
Regression tests for consecutive EJECUTAR COMANDO executions against TIA Openness (session
continua: comando A -> TIA importa/compila -> comando B -> TIA reemplaza/compila, sin reiniciar
la app ni TIA Portal).

Diagnostico previo a estos tests (ver conversacion): el lock `self._tia_worker_active` y la
determinacion del "paquete activo" (`self.current_result_snapshot`, poblado en cada
generate_package() y leido explicitamente por validate_latest_package_in_tia() - nunca se busca
"el ultimo paquete del directorio") ya estaban correctamente implementados e IDENTICOS a la
version estable original (`git show HEAD:src/gui.py` no difiere en esas secciones; `tia_openness.py`
y `tia_openness_bridge/Program.cs` no tienen ningun diff frente al commit inicial). El bridge C#
tambien ya reemplaza (Find por nombre -> Delete -> CreateFromFile) en vez de duplicar, usando un
`source_name` ("siemens_source.scl") y un `pou_name` ("PLC_PRG") fijos en todo el codigo - por eso
un segundo comando SIEMPRE sobrescribe el bloque del primero en TIA, nunca lo duplica.

El unico cambio funcional introducido junto con estos tests es que execute_full_pipeline() ahora
deshabilita el boton EJECUTAR COMANDO durante TODO el pipeline (no solo la fase TIA), cerrando la
ventana en la que un click durante process_command()/generate_package() podria reencolar el mismo
comando antes de que exista siquiera un lock TIA activo.
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

from test_execute_full_pipeline import (  # noqa: E402
    _base_semantic_output,
    _mock_package_result,
    _run_and_settle,
    _SyncThread,
    temp_map,
    _tia_ready,
)

__all__ = ["temp_map", "_tia_ready"]


def _set_command_text(app, text: str) -> None:
    app.command_textbox.delete("1.0", "end")
    app.command_textbox.insert("1.0", text)


# ---------- Section 21: dos ejecuciones consecutivas, ambas exitosas ----------

def test_two_consecutive_successful_commands_each_use_their_own_package(
    app, temp_map, tmp_path, monkeypatch, _tia_ready
) -> None:
    semantic_a = _base_semantic_output(
        "INT_MOTOR_LATCH",
        {"trigger_input": "I_Start", "stop_input": "I_Start", "motor_output": "Q_Motor_1", "run_latch": "M_RunLatch"},
        ["I_Start", "Q_Motor_1"]
    )
    semantic_b = _base_semantic_output(
        "INT_DELAYED_STOP",
        {
            "trigger_input": "I_Start", "stop_input": "I_Start", "motor_output": "Q_Motor_1",
            "run_latch": "M_RunLatch", "stop_delay_active": "M_StopDelayActive",
            "stop_delay_time": "T#3s", "timer": "T_StopDelay"
        },
        ["I_Start", "Q_Motor_1"]
    )
    semantic_outputs = [semantic_a, semantic_b]
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_outputs.pop(0))
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    package_a = tmp_path / "package_a"
    package_b = tmp_path / "package_b"
    package_a.mkdir()
    package_b.mkdir()
    package_dirs = [package_a, package_b]
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: _mock_package_result(package_dirs.pop(0)))

    tia_calls: list[Path] = []

    def _fake_validate(package_dir_arg, project_root_arg):
        tia_calls.append(package_dir_arg)
        return {
            "status": "TIA_COMPILATION_PASSED", "result_path": str(package_dir_arg / "tia_compile_report.json"),
            "bridge_return_code": 0, "bridge_stdout": "", "bridge_stderr": ""
        }

    monkeypatch.setattr(gui, "validate_package_with_tia", _fake_validate)

    # --- Comando A ---
    _set_command_text(app, "Enciende un motor con Start.")
    result_a = _run_and_settle(app)
    assert result_a is True
    assert len(tia_calls) == 1
    assert tia_calls[0] == package_a
    assert app._tia_worker_active is False
    assert app._last_compiled_package_dir == package_a
    assert app._last_successful_tia_package_dir == package_a
    assert app.execute_command_button.cget("state") == "normal"

    # --- Comando B: no debe aparecer "operacion TIA en curso" porque A ya libero el lock ---
    _set_command_text(app, "Enciende un motor con Start y apagalo 3 segundos despues de Start.")
    result_b = _run_and_settle(app)
    assert result_b is True
    assert len(tia_calls) == 2
    assert tia_calls[1] == package_b
    assert tia_calls[1] != package_a
    assert app._tia_worker_active is False
    assert app._last_compiled_package_dir == package_b
    assert app._last_successful_tia_package_dir == package_b


# ---------- Section 22: A compila, B falla en TIA -> A sigue siendo el ultimo valido ----------

def test_failed_second_command_keeps_first_as_last_successful_and_allows_a_third(
    app, temp_map, tmp_path, monkeypatch, _tia_ready
) -> None:
    semantic_a = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    semantic_b = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    semantic_c = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    semantic_outputs = [semantic_a, semantic_b, semantic_c]
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_outputs.pop(0))
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    package_a = tmp_path / "package_a"
    package_b = tmp_path / "package_b"
    package_c = tmp_path / "package_c"
    for directory in (package_a, package_b, package_c):
        directory.mkdir()
    package_dirs = [package_a, package_b, package_c]
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: _mock_package_result(package_dirs.pop(0)))

    tia_calls: list[Path] = []

    def _fake_validate(package_dir_arg, project_root_arg):
        tia_calls.append(package_dir_arg)
        if package_dir_arg == package_b:
            return {
                "status": "TIA_COMPILATION_FAILED", "result_path": str(package_dir_arg / "tia_compile_report.json"),
                "bridge_return_code": 1, "bridge_stdout": "", "bridge_stderr": "error simulado de compilacion"
            }
        return {
            "status": "TIA_COMPILATION_PASSED", "result_path": str(package_dir_arg / "tia_compile_report.json"),
            "bridge_return_code": 0, "bridge_stdout": "", "bridge_stderr": ""
        }

    monkeypatch.setattr(gui, "validate_package_with_tia", _fake_validate)

    _set_command_text(app, "comando A")
    assert _run_and_settle(app) is True
    assert app._last_compiled_package_dir == package_a

    _set_command_text(app, "comando B")
    result_b = _run_and_settle(app)
    # generate_package()/execute_full_pipeline() reportan True porque la verificacion previa a TIA
    # paso - lo que falla es la compilacion EN TIA. `_last_compiled_package_dir` (guardian de
    # 'CARGAR PROGRAMA AL PLC') SI se limpia con cualquier fallo, deliberadamente - nunca debe
    # ofrecer descargar un programa viejo tras un intento fallido. `_last_successful_tia_package_dir`
    # es el campo informativo que debe seguir siendo A.
    assert app._tia_worker_active is False
    assert app._last_compiled_package_dir is None, "un fallo debe invalidar la descarga al PLC"
    assert app._last_successful_tia_package_dir == package_a, (
        "B fallo en TIA: A debe seguir siendo el ultimo programa compilado con exito"
    )

    # --- Comando C: el lock debe seguir liberado y permitir una tercera ejecucion normal ---
    _set_command_text(app, "comando C")
    result_c = _run_and_settle(app)
    assert result_c is True
    assert len(tia_calls) == 3
    assert app._tia_worker_active is False
    assert app._last_compiled_package_dir == package_c
    assert app._last_successful_tia_package_dir == package_c


# ---------- Section 23: el bridge lanza una excepcion -> el lock se libera igual ----------

def test_bridge_exception_releases_lock_and_allows_next_command(
    app, temp_map, tmp_path, monkeypatch, _tia_ready
) -> None:
    semantic_a = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    semantic_b = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    semantic_outputs = [semantic_a, semantic_b]
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_outputs.pop(0))
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    package_a = tmp_path / "package_a"
    package_b = tmp_path / "package_b"
    package_a.mkdir()
    package_b.mkdir()
    package_dirs = [package_a, package_b]
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: _mock_package_result(package_dirs.pop(0)))

    call_count = {"n": 0}

    def _raising_validate(package_dir_arg, project_root_arg):
        call_count["n"] += 1
        raise RuntimeError("el bridge C# se cayo (simulado)")

    monkeypatch.setattr(gui, "validate_package_with_tia", _raising_validate)

    _set_command_text(app, "comando A")
    result_a = _run_and_settle(app)
    assert result_a is True  # execute_full_pipeline() ya inicio TIA cuando la excepcion ocurre
    assert call_count["n"] == 1
    assert app._tia_worker_active is False, "una excepcion del bridge nunca debe dejar el lock colgado"
    assert app.execute_command_button.cget("state") == "normal"

    # --- Un segundo comando, ahora exitoso, debe poder ejecutarse sin "operacion TIA en curso" ---
    def _fake_validate(package_dir_arg, project_root_arg):
        return {
            "status": "TIA_COMPILATION_PASSED", "result_path": str(package_dir_arg / "tia_compile_report.json"),
            "bridge_return_code": 0, "bridge_stdout": "", "bridge_stderr": ""
        }

    monkeypatch.setattr(gui, "validate_package_with_tia", _fake_validate)
    _set_command_text(app, "comando B")
    result_b = _run_and_settle(app)
    assert result_b is True
    assert app._tia_worker_active is False
    assert app._last_compiled_package_dir == package_b
    assert app._last_successful_tia_package_dir == package_b


# ---------- Section 24: B llega mientras A "sigue realmente ejecutandose" ----------

def test_second_command_while_first_still_running_is_rejected_not_lost(
    app, temp_map, tmp_path, monkeypatch, _tia_ready
) -> None:
    """
    Simula que el worker de A todavia no puso resultado en la cola (A sigue realmente
    ejecutandose) cuando el usuario pulsa EJECUTAR COMANDO para B: no debe lanzarse un segundo
    bridge, el texto de B no se borra (nada se "pierde"), y en cuanto A termina (se drena su
    resultado real de la cola) el sistema queda listo para B sin residuos del lock.
    """
    semantic_a = _base_semantic_output(
        "INT_DIRECT_OUTPUT", {"trigger_input": "I_Start", "output": "Q_Motor_1"}, ["I_Start", "Q_Motor_1"]
    )
    monkeypatch.setattr(gui, "parse_command", lambda command_text, **kwargs: semantic_a)
    monkeypatch.setattr(gui, "append_test_record_to_docs", lambda **kwargs: None)

    package_a = tmp_path / "package_a"
    package_a.mkdir()
    monkeypatch.setattr(gui, "generate_project_package", lambda **kwargs: _mock_package_result(package_a))

    tia_calls: list[Path] = []

    def _fake_validate(package_dir_arg, project_root_arg):
        tia_calls.append(package_dir_arg)
        return {
            "status": "TIA_COMPILATION_PASSED", "result_path": str(package_dir_arg / "tia_compile_report.json"),
            "bridge_return_code": 0, "bridge_stdout": "", "bridge_stderr": ""
        }

    # A queda "realmente ejecutandose": usamos el _SyncThread real (ya instalado por _tia_ready)
    # para procesar y arrancar A, pero SIN drenar la cola todavia (no llamamos _poll_tia_worker).
    monkeypatch.setattr(gui, "validate_package_with_tia", _fake_validate)
    _set_command_text(app, "comando A")
    result_a = app.execute_full_pipeline()
    assert result_a is True
    # _SyncThread ejecuta el worker de forma sincrona, asi que para esta prueba forzamos el lock a
    # True de nuevo despues de que A ya puso su resultado en la cola, simulando la ventana real en
    # la que el bridge de A sigue corriendo (el resultado aun no fue drenado por _poll_tia_worker).
    assert app._tia_worker_active is True  # _SyncThread deja el resultado en cola sin drenar aun

    # --- B llega mientras A "sigue en curso" ---
    command_b_text = "comando B mientras A sigue ocupado"
    _set_command_text(app, command_b_text)
    result_b = app.execute_full_pipeline()
    assert result_b is False
    assert len(tia_calls) == 1, "no debe lanzarse un segundo bridge mientras A sigue activo"
    assert app.command_textbox.get("1.0", "end").strip() == command_b_text, (
        "el comando B no debe perderse: sigue en el cuadro de texto, listo para reintentar"
    )

    # --- A termina de verdad (se drena su resultado real) -> el sistema queda listo para B ---
    app._poll_tia_worker()
    assert app._tia_worker_active is False
    assert app.execute_command_button.cget("state") == "normal"

    # --- Ahora B puede ejecutarse normalmente ---
    result_b_retry = _run_and_settle(app)
    assert result_b_retry is True
    assert len(tia_calls) == 2
