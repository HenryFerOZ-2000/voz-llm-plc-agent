from __future__ import annotations

from pathlib import Path
from typing import Any

from logger import (
    append_robustness_record_to_docs,
    append_test_record_to_docs,
    archive_generated_files,
    clear_generated_files,
    ensure_generated_dirs
)
from llm_parser import parse_command, resolve_parser_mode
from project_packager import generate_project_package
from tia_openness import (
    diagnose_tia_openness,
    run_openness_bridge_diagnostic,
    validate_package_with_tia
)
from utils import get_project_root, load_json_file, pretty_json


SUPPORTED_TARGET_PLATFORMS = ["SIEMENS_SCL_V18", "OPENPLC_ST", "CODESYS_ST"]


def _load_configuration(project_root: Path) -> tuple[dict, dict, dict]:
    config_dir = project_root / "config"
    io_map = load_json_file(config_dir / "io_map.json")
    intents_catalog = load_json_file(config_dir / "intents_catalog.json")
    safety_rules = load_json_file(config_dir / "safety_rules.json")
    return io_map, intents_catalog, safety_rules


def _load_test_commands(project_root: Path) -> list[dict[str, Any]]:
    tests_path = project_root / "tests" / "test_cases.json"
    raw_data = load_json_file(tests_path)

    if not isinstance(raw_data, list):
        raise ValueError("The tests/test_cases.json file must contain a JSON array.")

    commands: list[dict[str, Any]] = []
    for index, item in enumerate(raw_data, start=1):
        if isinstance(item, str):
            commands.append(
                {
                    "case_id": f"AUTO_{index:03d}",
                    "command": item,
                    "expected_intent": None
                }
            )
        elif isinstance(item, dict) and isinstance(item.get("command"), str):
            commands.append(
                {
                    "case_id": item.get("case_id", f"AUTO_{index:03d}"),
                    "command": item["command"],
                    "expected_intent": item.get("expected_intent")
                }
            )
        else:
            raise ValueError("Each test case must be a command string or an object with a 'command' field.")

    return commands


def _print_menu() -> None:
    print("\n=== voz_llm_plc_agent MVP ===")
    print("1. Probar comando manual")
    print("2. Ejecutar comandos de prueba desde tests/test_cases.json")
    print("3. Archivar codigos generados")
    print("4. Limpiar codigos generados")
    print("5. Diagnosticar TIA Openness V18")
    print("6. Importar y compilar ultimo paquete Siemens")
    print("7. Salir")


def _select_generation_platforms() -> list[str]:
    while True:
        print("\nSeleccione plataforma:")
        print("1. Siemens TIA V18")
        print("2. OpenPLC")
        print("3. CODESYS")
        print("4. Siemens + OpenPLC")
        print("5. Todas")
        option = input("Seleccione una opcion: ").strip()

        if option == "1":
            return ["SIEMENS_SCL_V18"]
        if option == "2":
            return ["OPENPLC_ST"]
        if option == "3":
            return ["CODESYS_ST"]
        if option == "4":
            return ["SIEMENS_SCL_V18", "OPENPLC_ST"]
        if option == "5":
            return SUPPORTED_TARGET_PLATFORMS.copy()

        print("Opcion no valida. Intente nuevamente.")


def _select_management_platform() -> str | None:
    while True:
        print("\nSeleccione que limpiar/archivar:")
        print("1. Siemens TIA V18")
        print("2. OpenPLC")
        print("3. CODESYS")
        print("4. Todas")
        option = input("Seleccione una opcion: ").strip()

        if option == "1":
            return "SIEMENS_SCL_V18"
        if option == "2":
            return "OPENPLC_ST"
        if option == "3":
            return "CODESYS_ST"
        if option == "4":
            return None

        print("Opcion no valida. Intente nuevamente.")


def _unknown_result(command_text: str, semantic_output: dict[str, Any], target_platform: str) -> dict[str, Any]:
    semantic_validation = semantic_output.get("semantic_validation", {})
    verification_result = {
        "is_valid": False,
        "errors": list(semantic_validation.get("errors", []))
        + ["La intencion no fue reconocida y no se genero un paquete PLC."],
        "warnings": list(semantic_validation.get("warnings", []))
    }
    return {
        "command_text": command_text,
        "semantic_output": semantic_output,
        "package_result": None,
        "verification_result": verification_result,
        "saved_paths": None,
        "target_platform": target_platform
    }


def _process_command_for_platform(
    command_text: str,
    semantic_output: dict[str, Any],
    io_map: dict[str, Any],
    intents_catalog: dict[str, Any],
    safety_rules: dict[str, Any],
    docs_dir: Path,
    target_platform: str,
    case_id: str | None = None
) -> dict[str, Any]:
    semantic_payload = dict(semantic_output)
    semantic_payload["command_text"] = command_text
    if case_id is not None:
        semantic_payload["case_id"] = case_id

    semantic_validation = semantic_payload.get("semantic_validation", {})

    if semantic_payload.get("intent_id") == "INT_UNKNOWN" or not semantic_validation.get("is_valid", True):
        result = _unknown_result(command_text, semantic_payload, target_platform)
        append_test_record_to_docs(
            docs_dir=docs_dir,
            command_text=command_text,
            semantic_output=semantic_payload,
            verification_result=result["verification_result"],
            saved_paths=None,
            target_platform=target_platform
        )
        return result

    package_result = generate_project_package(
        semantic_output=semantic_payload,
        target_platform=target_platform,
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules
    )
    verification_result = package_result["verification"]
    saved_paths = package_result.get("artifacts") or None
    append_test_record_to_docs(
        docs_dir=docs_dir,
        command_text=command_text,
        semantic_output=semantic_payload,
        verification_result=verification_result,
        saved_paths=saved_paths,
        target_platform=target_platform
    )
    return {
        "command_text": command_text,
        "semantic_output": semantic_payload,
        "package_result": package_result,
        "verification_result": verification_result,
        "saved_paths": saved_paths,
        "target_platform": target_platform
    }


def _process_command_for_targets(
    command_text: str,
    io_map: dict[str, Any],
    intents_catalog: dict[str, Any],
    safety_rules: dict[str, Any],
    docs_dir: Path,
    target_platforms: list[str],
    case_id: str | None = None,
    semantic_output: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    parsed_output = semantic_output or parse_command(
        command_text,
        io_map=io_map,
        intents_catalog=intents_catalog,
        safety_rules=safety_rules
    )
    results: list[dict[str, Any]] = []

    for target_platform in target_platforms:
        results.append(
            _process_command_for_platform(
                command_text=command_text,
                semantic_output=parsed_output,
                io_map=io_map,
                intents_catalog=intents_catalog,
                safety_rules=safety_rules,
                docs_dir=docs_dir,
                target_platform=target_platform,
                case_id=case_id
            )
        )

    return results


def _print_command_result(result: dict[str, Any]) -> None:
    print(f"\nPlataforma generada: {result['target_platform']}")
    print(f"Comando original: {result['command_text']}")

    semantic_output = result["semantic_output"]
    print("\nIntencion detectada:")
    print(pretty_json(semantic_output))

    semantic_validation = semantic_output.get("semantic_validation")
    if semantic_validation:
        print("\nValidacion semantica:")
        print(pretty_json(semantic_validation))

    package_result = result.get("package_result")
    if package_result:
        project_ir = package_result["project_ir"]
        print("\nRepresentacion intermedia:")
        print(pretty_json(project_ir))

        print("\nPOU:")
        print(pretty_json(project_ir.get("pou", {})))

        print("\nTask:")
        print(pretty_json(project_ir.get("task", {})))

        print("\nCodigo ST completo:")
        print(package_result["rendered_files"].get("full_program.st", ""))
    else:
        print("\nNo se genero paquete PLC para este caso.")

    print("\nResultado de verificacion:")
    print(pretty_json(result["verification_result"]))

    if not result["verification_result"].get("is_valid", False):
        print("\nCODIGO/PROYECTO NO VALIDO PARA SIMULACION")

    if result["saved_paths"] is not None:
        print("\nArchivos generados:")
        print(pretty_json(result["saved_paths"]))
    else:
        print("\nNo se guardaron archivos para este caso.")


def _print_archive_summary(result: dict[str, Any]) -> None:
    print(f"\nPlataforma solicitada: {result.get('target_platform', 'ALL')}")
    print(f"Paquetes movidos: {result.get('package_dirs_moved', 0)}")
    print(f"Logs movidos: {result.get('log_files_moved', 0)}")

    for platform_name, platform_result in result.get("platform_results", {}).items():
        print(f"{platform_name}: {platform_result.get('archive_path', '-')}")


def _print_clear_summary(result: dict[str, Any]) -> None:
    if not result.get("cleared", False):
        print(result.get("message", "Confirmacion requerida"))
        return

    print(f"\nPlataforma solicitada: {result.get('target_platform', 'ALL')}")
    print(f"Paquetes eliminados: {result.get('package_dirs_deleted', 0)}")
    print(f"Logs eliminados: {result.get('log_files_deleted', 0)}")
    print("Errores: " + ("; ".join(result.get("errors", [])) or "-"))


def main() -> None:
    project_root = get_project_root()
    try:
        io_map, intents_catalog, safety_rules = _load_configuration(project_root)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error loading configuration: {error}")
        return

    generated_dirs = ensure_generated_dirs(project_root / "generated_code")
    docs_dir = project_root / "docs"

    print("Proyecto cargado correctamente.")
    print(f"Intenciones catalogadas: {len(intents_catalog)}")
    print("Plataformas soportadas: SIEMENS_SCL_V18, OPENPLC_ST, CODESYS_ST")
    print(f"Modo parser actual: {resolve_parser_mode()}")

    while True:
        _print_menu()
        option = input("Seleccione una opcion: ").strip()

        if option == "1":
            target_platforms = _select_generation_platforms()
            command_text = input("\nEscriba el comando industrial: ").strip()
            if not command_text:
                print("Debe ingresar un comando no vacio.")
                continue

            results = _process_command_for_targets(
                command_text=command_text,
                io_map=io_map,
                intents_catalog=intents_catalog,
                safety_rules=safety_rules,
                docs_dir=docs_dir,
                target_platforms=target_platforms
            )
            for result in results:
                _print_command_result(result)

        elif option == "2":
            target_platforms = _select_generation_platforms()
            try:
                test_cases = _load_test_commands(project_root)
            except (FileNotFoundError, ValueError) as error:
                print(f"Error loading test cases: {error}")
                continue

            total_commands = len(test_cases)
            expected_count = 0
            correct_intent_count = 0
            valid_results = 0
            invalid_results = 0
            openplc_packages_generated = 0
            codesys_packages_generated = 0
            siemens_packages_generated = 0
            errors: list[str] = []

            print(f"\nProcesando {total_commands} comandos de prueba...")
            print("Plataformas objetivo: " + ", ".join(target_platforms))

            for index, test_case in enumerate(test_cases, start=1):
                command_text = test_case["command"]
                expected_intent = test_case.get("expected_intent")
                semantic_output = parse_command(
                    command_text,
                    io_map=io_map,
                    intents_catalog=intents_catalog,
                    safety_rules=safety_rules
                )
                detected_intent = semantic_output.get("intent_id", "INT_UNKNOWN")

                if expected_intent:
                    expected_count += 1
                    is_correct = detected_intent == expected_intent
                    if is_correct:
                        correct_intent_count += 1
                else:
                    is_correct = None

                results = _process_command_for_targets(
                    command_text=command_text,
                    io_map=io_map,
                    intents_catalog=intents_catalog,
                    safety_rules=safety_rules,
                    docs_dir=docs_dir,
                    target_platforms=target_platforms,
                    case_id=test_case.get("case_id"),
                    semantic_output=semantic_output
                )

                platform_statuses: list[str] = []
                first_generated_path: str | None = None
                for result in results:
                    target_platform = result["target_platform"]
                    is_valid = result["verification_result"]["is_valid"]
                    status = "VALIDO" if is_valid else "INVALIDO"
                    platform_statuses.append(f"{target_platform}:{status}")
                    if is_valid:
                        valid_results += 1
                    else:
                        invalid_results += 1
                        for error_message in result["verification_result"].get("errors", []):
                            errors.append(f"{test_case['case_id']} {target_platform}: {error_message}")

                    if result["saved_paths"] is not None:
                        first_generated_path = first_generated_path or result["saved_paths"].get("package_dir")
                        if target_platform == "OPENPLC_ST":
                            openplc_packages_generated += 1
                        elif target_platform == "CODESYS_ST":
                            codesys_packages_generated += 1
                        elif target_platform == "SIEMENS_SCL_V18":
                            siemens_packages_generated += 1

                observations = (
                    f"Plataformas: {', '.join(target_platforms)}. "
                    f"Estados: {', '.join(platform_statuses)}."
                )
                append_robustness_record_to_docs(
                    docs_dir=docs_dir,
                    command_text=command_text,
                    expected_intent=expected_intent,
                    detected_intent=detected_intent,
                    is_correct=is_correct,
                    st_path=first_generated_path,
                    observations=observations
                )

                intent_status = "INT_OK" if is_correct else "INT_FAIL" if is_correct is False else "INT_NA"
                print(
                    f"[{index}/{total_commands}] {test_case['case_id']} | "
                    f"{intent_status} | "
                    f"{detected_intent}"
                    + (f" / {expected_intent}" if expected_intent else "")
                    + f" | {', '.join(platform_statuses)} | {command_text}"
                )

            print("\nResumen de pruebas:")
            print(f"Total de comandos: {total_commands}")
            print(f"Intenciones correctas: {correct_intent_count}")
            print(f"Resultados validos: {valid_results}")
            print(f"Resultados invalidos: {invalid_results}")
            print(f"Paquetes OpenPLC generados: {openplc_packages_generated}")
            print(f"Paquetes CODESYS generados: {codesys_packages_generated}")
            print(f"Paquetes Siemens generados: {siemens_packages_generated}")
            print("Errores: " + ("; ".join(errors[:10]) if errors else "-"))

        elif option == "3":
            selected_platform = _select_management_platform()
            archive_result = archive_generated_files(
                target_platform=selected_platform,
                output_dir=generated_dirs["generated_code"]
            )
            _print_archive_summary(archive_result)

        elif option == "4":
            selected_platform = _select_management_platform()
            confirmation = input("Escriba BORRAR para confirmar: ").strip()
            if confirmation != "BORRAR":
                print("Limpieza cancelada.")
                continue

            clear_result = clear_generated_files(
                confirm=True,
                target_platform=selected_platform,
                output_dir=generated_dirs["generated_code"]
            )
            _print_clear_summary(clear_result)

        elif option == "5":
            print(
                pretty_json(
                    {
                        "diagnostic": diagnose_tia_openness(project_root),
                        "bridge_runtime": run_openness_bridge_diagnostic(project_root)
                    }
                )
            )

        elif option == "6":
            active_dir = generated_dirs["platforms"]["SIEMENS_SCL_V18"]["active"]
            packages = sorted(
                (path for path in active_dir.iterdir() if path.is_dir()),
                key=lambda path: path.stat().st_mtime,
                reverse=True
            )
            if not packages:
                print("No existe un paquete Siemens activo. Genere uno primero.")
                continue
            confirmation = input(
                f"Se importara y compilara {packages[0].name}. Escriba IMPORTAR para confirmar: "
            ).strip()
            if confirmation != "IMPORTAR":
                print("Importacion TIA cancelada.")
                continue
            print(pretty_json(validate_package_with_tia(packages[0], project_root)))

        elif option == "7":
            print("Saliendo del programa.")
            break

        else:
            print("Opcion no valida. Intente nuevamente.")


if __name__ == "__main__":
    main()
