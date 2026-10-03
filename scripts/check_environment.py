"""
Diagnostico READ-ONLY del entorno de una PC (docs/multi_pc_setup.md).

    .venv\\Scripts\\python.exe scripts\\check_environment.py

No escribe, no crea ni modifica nada: ni mapas (no llama a list_plc_maps, que inicializa el working),
ni configuracion, ni TIA/PLCSIM (solo comprueba que los archivos de instalacion existen). Nunca
imprime el valor de la clave OpenAI. Codigo de salida: 0 sin FAIL, 1 con algun FAIL.
"""
from __future__ import annotations

import importlib.metadata as metadata
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

OK, WARN, FAIL = "OK", "WARN", "FAIL"
EXPECTED_CASES = 32
EXPECTED_ORACLES = 32
MAIN_PACKAGES = ("customtkinter", "openai", "python-dotenv", "pydantic", "sounddevice", "pytest")
results: list[tuple[str, str, str]] = []


def check(name: str, status: str, detail: str = "") -> None:
    results.append((status, name, detail))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def pinned_versions() -> dict[str, str]:
    path = ROOT / "requirements-transfer.txt"
    pins = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "==" in line and not line.lstrip().startswith("#"):
                name, version = line.strip().split("==", 1)
                pins[name.lower().replace("_", "-")] = version
    return pins


def check_python() -> None:
    version = ".".join(map(str, sys.version_info[:3]))
    check("Python", OK if sys.version_info[:2] == (3, 13) else WARN, f"{version} (desarrollo: 3.13.x)")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    venv_here = Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()
    check("venv", OK if in_venv and venv_here else WARN,
          f"{sys.prefix}" + ("" if venv_here else "  (no es .venv del proyecto)"))


def check_packages() -> None:
    pins = pinned_versions()
    for package in MAIN_PACKAGES:
        try:
            installed = metadata.version(package)
        except metadata.PackageNotFoundError:
            check(f"paquete {package}", FAIL, "no instalado (pip install -r requirements-transfer.txt)")
            continue
        expected = pins.get(package.lower())
        status = OK if not expected or expected == installed else WARN
        check(f"paquete {package}", status, installed + (f" (fijado {expected})" if expected and expected != installed else ""))


def check_benchmark() -> None:
    path = ROOT / "data" / "experiment_cases" / "canonical_cases.json"
    if not path.exists():
        check("benchmark", FAIL, f"falta {path.relative_to(ROOT)}")
        return
    payload = read_json(path)
    cases = payload.get("cases") or []
    variants = sum(len(case.get("variants") or []) for case in cases)
    check("benchmark", OK if len(cases) == EXPECTED_CASES else FAIL,
          f"{payload.get('benchmark_version')}: {len(cases)} casos, {variants} variantes")


def check_oracles() -> None:
    from trial_experiments.oracle_schema import compute_oracle_hash

    files = sorted((ROOT / "data" / "experiment_oracles").glob("*.json"))
    frozen, bad_hash = 0, []
    for path in files:
        oracle = read_json(path)
        approval = oracle.get("approval") or {}
        frozen += approval.get("status") == "FROZEN"
        if approval.get("hash") != compute_oracle_hash(oracle):
            bad_hash.append(path.stem)
    status = OK if len(files) == EXPECTED_ORACLES and frozen == EXPECTED_ORACLES and not bad_hash else FAIL
    check("Oracles", status, f"{len(files)} archivos, {frozen} FROZEN" + (f", hash distinto: {bad_hash}" if bad_hash else ", hashes OK"))


def check_design() -> None:
    path = ROOT / "data" / "experimental_design.json"
    if not path.exists():
        check("diseno experimental", FAIL, "falta data/experimental_design.json")
        return
    design = read_json(path)
    modes = [mode.get("id") for mode in design.get("formal_input_modes") or []]
    check("diseno experimental", OK if modes else FAIL,
          f"v{design.get('design_version')} benchmark {design.get('benchmark_version')}, modalidades {modes}")


def check_maps() -> None:
    maps_dir = ROOT / "data" / "plc_maps"
    base = maps_dir / "mapa_banco_fisico_base.json"
    working = maps_dir / "mapa_banco_fisico_working.json"
    if base.exists():
        variables = read_json(base).get("variables") or []
        check("mapa base (versionado)", OK, f"{base.name}: {len(variables)} canales")
    else:
        check("mapa base (versionado)", FAIL, f"falta {base.name}")
    if working.exists():
        info = (read_json(working).get("metadata") or {}).get("working_copy") or {}
        check("mapa working (local)", OK, f"inicializado desde {info.get('initialized_from')} el {info.get('initialized_at')}")
    else:
        check("mapa working (local)", WARN, "aun no existe: la aplicacion lo crea desde el base al abrirse")
    pointer = maps_dir / "_active_map.json"
    active = read_json(pointer).get("active_map_id") if pointer.exists() else None
    check("mapa activo", OK if active else WARN, active or "sin puntero (la aplicacion elige uno al abrirse)")


def check_local_config() -> None:
    from host_local import load_host_id

    env_path = ROOT / ".env"
    if env_path.exists():
        has_key = any(line.strip().startswith("OPENAI_API_KEY=") and line.split("=", 1)[1].strip()
                      for line in env_path.read_text(encoding="utf-8").splitlines())
        check(".env", OK if has_key else WARN, "OPENAI_API_KEY presente (valor no mostrado)" if has_key else "sin OPENAI_API_KEY")
    else:
        check(".env", WARN, "no existe: copiar .env.example a .env y poner la clave")
    host_id = load_host_id(ROOT)
    check("host_local", OK if host_id else WARN, host_id or "sin config/host_local.json (opcional)")
    for name in ("tia_openness_config.json", "tia_projects.json"):
        path = ROOT / "config" / name
        check(f"config/{name}", OK if path.exists() else WARN,
              "presente (local)" if path.exists() else f"falta: copiar config/{name.replace('.json', '.example.json')} y configurar desde la GUI")


def check_tia_projects() -> None:
    path = ROOT / "config" / "tia_projects.json"
    tia = (read_json(path).get("tia") or {}) if path.exists() else {}
    normal = tia.get("normal_project") or {}
    master = tia.get("experiment_master") or {}
    normal_path = str(normal.get("path") or "")
    if not normal_path:
        check("proyecto TIA Normal", WARN, "no seleccionado (Configurar TIA V18 en la GUI)")
    else:
        check("proyecto TIA Normal", OK if Path(normal_path).exists() else FAIL,
              normal_path if Path(normal_path).exists() else f"seleccionado pero no existe: {normal_path}")
    master_path = str(master.get("path") or "")
    if not master_path:
        check("TIA MASTER", WARN, "no seleccionado (solo necesario para Experimentacion)")
    else:
        exists = Path(master_path).exists()
        snapshot = str((master.get("snapshot") or {}).get("archive_path") or "")
        detail = f"estado {master.get('status')}; snapshot {'presente' if snapshot and Path(snapshot).exists() else 'ausente'}"
        # DEVELOPMENT_READY / FORMAL_READY (trial_experiments.deferred_evaluator); INVALID o sin validar = WARN.
        check("TIA MASTER", OK if exists and master.get("status") in ("DEVELOPMENT_READY", "FORMAL_READY") else WARN,
              detail if exists else f"seleccionado pero no existe: {master_path}")


def check_siemens() -> None:
    from plcsim_runtime import DEFAULT_RUNTIME_API_DLL
    from tia_openness import DEFAULT_API_DLL, DEFAULT_COMPILER

    config_path = ROOT / "config" / "tia_openness_config.json"
    config = read_json(config_path) if config_path.exists() else {}
    openness = Path(config.get("api_dll_path") or DEFAULT_API_DLL)
    runtime = Path((config.get("plcsim_runtime") or {}).get("api_dll_path") or DEFAULT_RUNTIME_API_DLL)
    check("TIA Openness V18", OK if openness.exists() else WARN, str(openness))
    check("PLCSIM Advanced Runtime API", OK if runtime.exists() else WARN, str(runtime))
    check(".NET csc.exe", OK if DEFAULT_COMPILER.exists() else WARN, str(DEFAULT_COMPILER))
    check("bridges compilados", OK if any((ROOT / "tia_openness_bridge" / "bin").glob("*.exe")) else WARN,
          "tia_openness_bridge/bin (se compilan solos la primera vez que se usa TIA)")


def main() -> int:
    for step in (check_python, check_packages, check_benchmark, check_oracles, check_design, check_maps,
                 check_local_config, check_tia_projects, check_siemens):
        try:
            step()
        except Exception as error:  # noqa: BLE001 - un fallo de diagnostico no debe ocultar los demas
            check(step.__name__, FAIL, f"{type(error).__name__}: {error}")
    width = max(len(name) for _, name, _ in results)
    print(f"Proyecto: {ROOT}")
    for status, name, detail in results:
        print(f"[{status:4}] {name:<{width}}  {detail}")
    counts = {s: sum(1 for r in results if r[0] == s) for s in (OK, WARN, FAIL)}
    print(f"\nResumen: {counts[OK]} OK, {counts[WARN]} WARN, {counts[FAIL]} FAIL")
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
