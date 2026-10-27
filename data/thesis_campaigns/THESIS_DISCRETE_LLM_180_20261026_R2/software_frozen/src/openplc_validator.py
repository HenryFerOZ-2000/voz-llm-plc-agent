from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


COMPILATION_REPORT = "openplc_compilation.json"
SIMULATION_REPORT = "openplc_simulation.json"
COMPILATION_PASSED = "COMPILATION_PASSED"
COMPILATION_FAILED = "COMPILATION_FAILED"
COMPILER_NOT_AVAILABLE = "COMPILER_NOT_AVAILABLE"
COMPILATION_TIMEOUT = "COMPILATION_TIMEOUT"
SIMULATION_PASSED = "SIMULATION_PASSED"
SIMULATION_FAILED = "SIMULATION_FAILED"
SIMULATION_NOT_EXECUTED = "SIMULATION_NOT_EXECUTED"
SIMULATION_TOOL_NOT_AVAILABLE = "SIMULATION_TOOL_NOT_AVAILABLE"
SIMULATION_UNSUPPORTED = "SIMULATION_UNSUPPORTED"

_IEC_TIME_PATTERN = re.compile(r"^T#(\d+)(ms|s|m|h)$", re.IGNORECASE)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _trim_output(value: str, limit: int = 30_000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n... output truncated ..."


def _run_version_command(executable: Path, engine: str) -> str:
    arguments = [str(executable), "--version" if engine == "STRUCPP" else "-v"]
    try:
        completed = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"

    output = (completed.stdout or completed.stderr).strip()
    return output.splitlines()[0] if output else "unknown"


def _compiler_candidate(path: Path, source: str) -> dict[str, Any] | None:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return None

    executable_name = resolved.name.lower()
    if "strucpp" in executable_name:
        engine = "STRUCPP"
    elif "iec2c" in executable_name:
        engine = "MATIEC"
    else:
        return None

    return {
        "available": True,
        "engine": engine,
        "path": str(resolved),
        "source": source,
        "version": _run_version_command(resolved, engine),
    }


def discover_openplc_compiler(explicit_path: str | Path | None = None) -> dict[str, Any]:
    """Find an OpenPLC-compatible ST compiler without relying on one fixed installation."""
    candidates: list[tuple[Path, str]] = []

    if explicit_path:
        candidates.append((Path(explicit_path), "explicit"))

    env_path = os.getenv("OPENPLC_COMPILER_PATH", "").strip()
    if env_path:
        candidates.append((Path(env_path), "OPENPLC_COMPILER_PATH"))

    for executable_name in ("strucpp", "strucpp.exe", "iec2c", "iec2c.exe"):
        located = shutil.which(executable_name)
        if located:
            candidates.append((Path(located), "PATH"))

    project_tools = Path(__file__).resolve().parents[1] / "tools"
    home = Path.home()
    candidates.extend(
        [
            (project_tools / "strucpp" / ("strucpp.exe" if os.name == "nt" else "strucpp"), "project_tools"),
            (home / "OpenPLC_Editor" / "matiec" / ("iec2c.exe" if os.name == "nt" else "iec2c"), "OpenPLC_Editor"),
            (
                home
                / "OpenPLC_Editor"
                / "editor"
                / "arduino"
                / "bin"
                / ("iec2c.exe" if os.name == "nt" else "iec2c"),
                "OpenPLC_Editor_Arduino",
            ),
        ]
    )

    seen: set[str] = set()
    for path, source in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        candidate = _compiler_candidate(path, source)
        if candidate:
            return candidate

    return {
        "available": False,
        "engine": None,
        "path": None,
        "source": None,
        "version": None,
    }


def discover_c_compiler(openplc_compiler: dict[str, Any] | None = None) -> dict[str, Any]:
    candidates: list[tuple[Path, str]] = []
    env_path = os.getenv("OPENPLC_GCC_PATH", "").strip()
    if env_path:
        candidates.append((Path(env_path), "OPENPLC_GCC_PATH"))

    for executable_name in ("gcc", "gcc.exe"):
        located = shutil.which(executable_name)
        if located:
            candidates.append((Path(located), "PATH"))

    if openplc_compiler and openplc_compiler.get("path"):
        compiler_path = Path(str(openplc_compiler["path"]))
        editor_root = compiler_path.parent.parent
        candidates.append(
            (editor_root / "mingw" / "bin" / ("gcc.exe" if os.name == "nt" else "gcc"), "OpenPLC_Editor")
        )

    for path, source in candidates:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            continue
        try:
            completed = subprocess.run(
                [str(resolved), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            version = (completed.stdout or completed.stderr).splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            version = "unknown"
        return {"available": True, "path": str(resolved), "source": source, "version": version}

    return {"available": False, "path": None, "source": None, "version": None}


def _matiec_command(compiler: Path, source: Path, build_dir: Path) -> tuple[list[str], Path]:
    library_dir = compiler.parent / "lib"
    command = [str(compiler), "-f", "-l", "-p"]
    if library_dir.is_dir():
        command.extend(["-I", str(library_dir)])
    command.extend(["-T", str(build_dir), str(source)])
    return command, library_dir


def _strucpp_command(compiler: Path, source: Path, build_dir: Path) -> tuple[list[str], Path]:
    output_path = build_dir / "plc_program.cpp"
    return [str(compiler), str(source), "-o", str(output_path)], compiler.parent / "runtime" / "include"


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def compile_openplc_package(
    package_dir: str | Path,
    *,
    compiler_path: str | Path | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    package_path = Path(package_dir).resolve()
    source_path = package_path / "full_program.st"
    report_path = package_path / COMPILATION_REPORT
    started_at = _now()

    if not source_path.is_file():
        result = {
            "is_compiled": False,
            "status": COMPILATION_FAILED,
            "engine": None,
            "compiler": {},
            "source_path": str(source_path),
            "build_dir": None,
            "started_at": started_at,
            "finished_at": _now(),
            "duration_ms": 0.0,
            "exit_code": None,
            "command": [],
            "stdout": "",
            "stderr": "",
            "generated_files": [],
            "errors": ["No existe full_program.st en el paquete OpenPLC."],
            "warnings": [],
        }
        if package_path.is_dir():
            _write_report(report_path, result)
        return result

    compiler = discover_openplc_compiler(compiler_path)
    if not compiler["available"]:
        result = {
            "is_compiled": False,
            "status": COMPILER_NOT_AVAILABLE,
            "engine": None,
            "compiler": compiler,
            "source_path": str(source_path),
            "build_dir": None,
            "started_at": started_at,
            "finished_at": _now(),
            "duration_ms": 0.0,
            "exit_code": None,
            "command": [],
            "stdout": "",
            "stderr": "",
            "generated_files": [],
            "errors": [],
            "warnings": [
                "No se encontro un compilador OpenPLC. Configure OPENPLC_COMPILER_PATH o instale OpenPLC Editor."
            ],
        }
        _write_report(report_path, result)
        return result

    build_dir = package_path / "openplc_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    executable = Path(str(compiler["path"]))
    if compiler["engine"] == "STRUCPP":
        command, library_dir = _strucpp_command(executable, source_path, build_dir)
    else:
        command, library_dir = _matiec_command(executable, source_path, build_dir)

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=build_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        stdout = _trim_output(completed.stdout)
        stderr = _trim_output(completed.stderr)
        status = COMPILATION_PASSED if completed.returncode == 0 else COMPILATION_FAILED
        errors = [] if completed.returncode == 0 else [
            line.strip() for line in stderr.splitlines() if line.strip()
        ]
        if not errors and completed.returncode != 0:
            errors = [f"El compilador OpenPLC termino con codigo {completed.returncode}."]
        exit_code: int | None = completed.returncode
    except subprocess.TimeoutExpired as error:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        stdout = _trim_output((error.stdout or "") if isinstance(error.stdout, str) else "")
        stderr = _trim_output((error.stderr or "") if isinstance(error.stderr, str) else "")
        status = COMPILATION_TIMEOUT
        errors = [f"La compilacion excedio el limite de {timeout_seconds} segundos."]
        exit_code = None
    except OSError as error:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        stdout = ""
        stderr = str(error)
        status = COMPILATION_FAILED
        errors = [f"No fue posible ejecutar el compilador OpenPLC: {error}"]
        exit_code = None

    generated_files = sorted(
        str(path.relative_to(package_path))
        for path in build_dir.rglob("*")
        if path.is_file()
    )
    result = {
        "is_compiled": status == COMPILATION_PASSED,
        "status": status,
        "engine": compiler["engine"],
        "compiler": compiler,
        "compiler_library_dir": str(library_dir) if library_dir.is_dir() else None,
        "source_path": str(source_path),
        "build_dir": str(build_dir),
        "started_at": started_at,
        "finished_at": _now(),
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "generated_files": generated_files,
        "errors": errors,
        "warnings": [],
    }
    _write_report(report_path, result)
    return result


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _c_identifier(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", value).upper()
    if not normalized or normalized[0].isdigit():
        normalized = f"V_{normalized}"
    return normalized


def _location_identifier(location: str) -> str:
    return "__" + re.sub(r"[^A-Za-z0-9]", "_", location.lstrip("%")).upper()


def _time_to_nanoseconds(value: str) -> int | None:
    match = _IEC_TIME_PATTERN.match(value.strip())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    multipliers = {"ms": 1_000_000, "s": 1_000_000_000, "m": 60_000_000_000, "h": 3_600_000_000_000}
    return amount * multipliers[unit]


def _c_bool(value: Any) -> str:
    return "TRUE" if bool(value) else "FALSE"


def _variable_expression(variable: dict[str, Any]) -> str:
    name = _c_identifier(str(variable.get("name", "")))
    if variable.get("location"):
        return f"sim_{name}"
    return f"plc.{name}.value"


def _render_harness(
    variables: list[dict[str, Any]],
    test_cases: list[dict[str, Any]],
    program_name: str,
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    variable_index = {str(item.get("name")): item for item in variables if item.get("name")}
    located = [item for item in variables if item.get("location")]
    unsupported_located = [
        str(item.get("name")) for item in located if str(item.get("type", "")).upper() != "BOOL"
    ]
    if unsupported_located:
        warnings.append("La simulacion automatica solo soporta I/O ubicadas de tipo BOOL: " + ", ".join(unsupported_located))

    lines = [
        "#include <stdio.h>",
        "#include <string.h>",
        '#include "POUS.h"',
        "TIME __CURRENT_TIME = {0, 0};",
        "",
    ]

    for variable in located:
        if str(variable.get("type", "")).upper() != "BOOL":
            continue
        c_name = _c_identifier(str(variable["name"]))
        location_name = _location_identifier(str(variable["location"]))
        lines.append(f"BOOL sim_{c_name} = FALSE;")
        lines.append(f"BOOL *{location_name} = &sim_{c_name};")

    lines.extend(
        [
            "",
            '#include "POUS.c"',
            "",
            f"static {program_name} plc;",
            "",
            "static void advance_time_ns(long long nanoseconds) {",
            "    long long total = (long long)__CURRENT_TIME.tv_nsec + nanoseconds;",
            "    __CURRENT_TIME.tv_sec += (int32_t)(total / 1000000000LL);",
            "    __CURRENT_TIME.tv_nsec = (int32_t)(total % 1000000000LL);",
            "}",
            "",
            "static void run_scan(void) {",
            f"    {program_name}_body__(&plc);",
            "}",
            "",
            "static void reset_program(void) {",
            "    memset(&plc, 0, sizeof(plc));",
            "    __CURRENT_TIME.tv_sec = 0;",
            "    __CURRENT_TIME.tv_nsec = 0;",
        ]
    )
    for variable in located:
        if str(variable.get("type", "")).upper() == "BOOL":
            lines.append(f"    sim_{_c_identifier(str(variable['name']))} = FALSE;")
    lines.extend([f"    {program_name}_init__(&plc, FALSE);", "}", ""])

    lines.append("int main(void) {")
    lines.append("    int failed = 0;")

    for case_index, test_case in enumerate(test_cases, start=1):
        test_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(test_case.get("test_id", f"TEST_{case_index}")))
        unsupported_reasons: list[str] = []
        lines.append("    reset_program();")

        initial_state = test_case.get("initial_state", {})
        if isinstance(initial_state, dict):
            for tag, value in initial_state.items():
                variable = variable_index.get(str(tag))
                if not variable or str(variable.get("type", "")).upper() != "BOOL":
                    unsupported_reasons.append(f"estado inicial no soportado: {tag}")
                    continue
                lines.append(f"    {_variable_expression(variable)} = {_c_bool(value)};")

        sequence = test_case.get("input_sequence", [])
        if isinstance(sequence, list):
            for action in sequence:
                if not isinstance(action, dict):
                    unsupported_reasons.append("accion de entrada no estructurada")
                    continue
                if "wait" in action:
                    nanoseconds = _time_to_nanoseconds(str(action["wait"]))
                    if nanoseconds is None:
                        unsupported_reasons.append(f"tiempo no soportado: {action['wait']}")
                    else:
                        lines.append(f"    advance_time_ns({nanoseconds}LL);")
                        lines.append("    run_scan();")
                    continue

                action_requires_scan = False
                for tag, value in action.items():
                    variable = variable_index.get(str(tag))
                    if not variable or str(variable.get("type", "")).upper() != "BOOL":
                        unsupported_reasons.append(f"entrada no soportada: {tag}")
                        continue
                    expression = _variable_expression(variable)
                    if value == "rising_edge":
                        lines.append(f"    {expression} = FALSE;")
                        lines.append("    run_scan();")
                        lines.append(f"    {expression} = TRUE;")
                        lines.append("    run_scan();")
                        lines.append(f"    {expression} = FALSE;")
                        lines.append("    run_scan();")
                    else:
                        lines.append(f"    {expression} = {_c_bool(value)};")
                        action_requires_scan = True
                if action_requires_scan:
                    lines.append("    run_scan();")

        expected = test_case.get("expected_outputs", {})
        checks: list[str] = []
        if isinstance(expected, dict):
            for tag, value in expected.items():
                variable = variable_index.get(str(tag))
                if not variable or str(variable.get("type", "")).upper() != "BOOL":
                    unsupported_reasons.append(f"salida esperada no soportada: {tag}")
                    continue
                expression = _variable_expression(variable)
                checks.append(f"({expression} == {_c_bool(value)})")

        if unsupported_reasons or not checks:
            message = "; ".join(unsupported_reasons) or "sin salidas esperadas comprobables"
            escaped = message.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'    printf("TEST|{test_id}|UNSUPPORTED|{escaped}\\n");')
        else:
            condition = " && ".join(checks)
            lines.append(f"    if ({condition}) {{")
            lines.append(f'        printf("TEST|{test_id}|PASS|\\n");')
            lines.append("    } else {")
            lines.append(f'        printf("TEST|{test_id}|FAIL|Salida distinta a la esperada\\n");')
            lines.append("        failed += 1;")
            lines.append("    }")

    lines.extend(["    return failed == 0 ? 0 : 1;", "}", ""])
    return "\n".join(lines), warnings


def _parse_simulation_output(stdout: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for line in stdout.splitlines():
        if not line.startswith("TEST|"):
            continue
        _, test_id, status, message = (line.split("|", 3) + [""] * 4)[:4]
        results.append({"test_id": test_id, "status": status, "message": message})
    return results


def simulate_openplc_package(
    package_dir: str | Path,
    compilation_result: dict[str, Any],
    *,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    package_path = Path(package_dir).resolve()
    report_path = package_path / SIMULATION_REPORT
    started_at = _now()

    if compilation_result.get("status") != COMPILATION_PASSED:
        result = {
            "is_simulated": False,
            "status": SIMULATION_NOT_EXECUTED,
            "engine": "MATIEC_GENERATED_C_HARNESS",
            "started_at": started_at,
            "finished_at": _now(),
            "duration_ms": 0.0,
            "test_results": [],
            "errors": [],
            "warnings": ["La simulacion no se ejecuto porque la compilacion OpenPLC no fue aprobada."],
        }
        _write_report(report_path, result)
        return result

    if compilation_result.get("engine") != "MATIEC":
        result = {
            "is_simulated": False,
            "status": SIMULATION_UNSUPPORTED,
            "engine": compilation_result.get("engine"),
            "started_at": started_at,
            "finished_at": _now(),
            "duration_ms": 0.0,
            "test_results": [],
            "errors": [],
            "warnings": ["La simulacion automatica actual requiere artefactos C generados por MatIEC."],
        }
        _write_report(report_path, result)
        return result

    c_compiler = discover_c_compiler(compilation_result.get("compiler"))
    if not c_compiler["available"]:
        result = {
            "is_simulated": False,
            "status": SIMULATION_TOOL_NOT_AVAILABLE,
            "engine": "MATIEC_GENERATED_C_HARNESS",
            "c_compiler": c_compiler,
            "started_at": started_at,
            "finished_at": _now(),
            "duration_ms": 0.0,
            "test_results": [],
            "errors": [],
            "warnings": ["No se encontro GCC para construir el ejecutable de simulacion."],
        }
        _write_report(report_path, result)
        return result

    build_dir = Path(str(compilation_result["build_dir"]))
    required_c_files = [build_dir / "POUS.c", build_dir / "POUS.h"]
    if any(not path.is_file() for path in required_c_files):
        result = {
            "is_simulated": False,
            "status": SIMULATION_UNSUPPORTED,
            "engine": "MATIEC_GENERATED_C_HARNESS",
            "c_compiler": c_compiler,
            "started_at": started_at,
            "finished_at": _now(),
            "duration_ms": 0.0,
            "test_results": [],
            "errors": [],
            "warnings": ["MatIEC no genero POUS.c y POUS.h; no se puede construir el simulador."],
        }
        _write_report(report_path, result)
        return result

    variables = _load_json(package_path / "variables.json", [])
    test_cases = _load_json(package_path / "test_cases.json", [])
    pou_manifest = _load_json(package_path / "pou_manifest.json", {})
    if not isinstance(variables, list) or not isinstance(test_cases, list) or not test_cases:
        result = {
            "is_simulated": False,
            "status": SIMULATION_UNSUPPORTED,
            "engine": "MATIEC_GENERATED_C_HARNESS",
            "c_compiler": c_compiler,
            "started_at": started_at,
            "finished_at": _now(),
            "duration_ms": 0.0,
            "test_results": [],
            "errors": [],
            "warnings": ["El paquete no contiene variables o casos de prueba ejecutables."],
        }
        _write_report(report_path, result)
        return result

    program_name = _c_identifier(str(pou_manifest.get("name", "PLC_PRG")))
    harness_source, harness_warnings = _render_harness(variables, test_cases, program_name)
    harness_path = build_dir / "simulation_harness.c"
    executable_path = build_dir / ("simulation_harness.exe" if sys.platform.startswith("win") else "simulation_harness")
    harness_path.write_text(harness_source, encoding="utf-8")

    compiler_path = Path(str(compilation_result["compiler"]["path"]))
    matiec_c_library = compiler_path.parent / "lib" / "C"
    compile_command = [
        str(c_compiler["path"]),
        "-std=c99",
        "-I",
        str(build_dir),
        "-I",
        str(matiec_c_library),
        str(harness_path),
        "-o",
        str(executable_path),
        "-lm",
    ]

    started = time.perf_counter()
    try:
        build = subprocess.run(
            compile_command,
            cwd=build_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        if build.returncode != 0:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            result = {
                "is_simulated": False,
                "status": SIMULATION_FAILED,
                "engine": "MATIEC_GENERATED_C_HARNESS",
                "c_compiler": c_compiler,
                "started_at": started_at,
                "finished_at": _now(),
                "duration_ms": duration_ms,
                "compile_command": compile_command,
                "compile_exit_code": build.returncode,
                "stdout": _trim_output(build.stdout),
                "stderr": _trim_output(build.stderr),
                "test_results": [],
                "errors": [line for line in build.stderr.splitlines() if line.strip()]
                or ["No fue posible construir el ejecutable de simulacion."],
                "warnings": harness_warnings,
            }
            _write_report(report_path, result)
            return result

        run = subprocess.run(
            [str(executable_path)],
            cwd=build_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        test_results = _parse_simulation_output(run.stdout)
        supported_results = [item for item in test_results if item["status"] != "UNSUPPORTED"]
        passed = bool(supported_results) and run.returncode == 0 and all(
            item["status"] == "PASS" for item in supported_results
        )
        status = SIMULATION_PASSED if passed else SIMULATION_FAILED
        errors = [] if passed else [
            f"{item['test_id']}: {item['message'] or 'prueba funcional fallida'}"
            for item in test_results
            if item["status"] == "FAIL"
        ]
        if not supported_results:
            status = SIMULATION_UNSUPPORTED
            errors = []
        result = {
            "is_simulated": status == SIMULATION_PASSED,
            "status": status,
            "engine": "MATIEC_GENERATED_C_HARNESS",
            "scope": "Pruebas funcionales sobre C generado por MatIEC; no equivale a despliegue en hardware.",
            "c_compiler": c_compiler,
            "started_at": started_at,
            "finished_at": _now(),
            "duration_ms": duration_ms,
            "compile_command": compile_command,
            "compile_exit_code": build.returncode,
            "run_exit_code": run.returncode,
            "executable_path": str(executable_path),
            "stdout": _trim_output(run.stdout),
            "stderr": _trim_output(run.stderr),
            "test_results": test_results,
            "tests_passed": sum(1 for item in test_results if item["status"] == "PASS"),
            "tests_failed": sum(1 for item in test_results if item["status"] == "FAIL"),
            "tests_unsupported": sum(1 for item in test_results if item["status"] == "UNSUPPORTED"),
            "errors": errors,
            "warnings": harness_warnings,
        }
    except (OSError, subprocess.TimeoutExpired) as error:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        result = {
            "is_simulated": False,
            "status": SIMULATION_FAILED,
            "engine": "MATIEC_GENERATED_C_HARNESS",
            "c_compiler": c_compiler,
            "started_at": started_at,
            "finished_at": _now(),
            "duration_ms": duration_ms,
            "compile_command": compile_command,
            "test_results": [],
            "errors": [f"No fue posible ejecutar la simulacion: {error}"],
            "warnings": harness_warnings,
        }

    _write_report(report_path, result)
    return result


def validate_openplc_package(
    package_dir: str | Path,
    *,
    compiler_path: str | Path | None = None,
    run_simulation: bool = True,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    compilation = compile_openplc_package(
        package_dir,
        compiler_path=compiler_path,
        timeout_seconds=timeout_seconds,
    )
    simulation = (
        simulate_openplc_package(package_dir, compilation, timeout_seconds=timeout_seconds)
        if run_simulation
        else {
            "is_simulated": False,
            "status": SIMULATION_NOT_EXECUTED,
            "engine": None,
            "test_results": [],
            "errors": [],
            "warnings": ["La simulacion automatica fue deshabilitada."],
        }
    )
    return {
        "compilation": compilation,
        "simulation": simulation,
        "compilation_status": compilation["status"],
        "simulation_status": simulation["status"],
        "is_compiled": compilation.get("is_compiled", False),
        "is_simulated": simulation.get("is_simulated", False),
        "is_fully_validated": compilation.get("is_compiled", False)
        and simulation.get("is_simulated", False),
    }
