from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from functional_requirements import (
    RESOURCE_SAFE_LITERAL,
    RESOURCE_TAG,
    ParameterResourceError,
    get_functional_requirement_tags,
    is_catalog_functional_requirement,
    resolve_parameter_resources,
)
from plc_ir import PLCProjectIR
from utils import build_io_map_index, flatten_io_map


TIME_LITERAL_PATTERN = re.compile(r"\bT#\d+(?:ms|s|m|h)\b", re.IGNORECASE)
PROGRAM_PATTERN = re.compile(r"^\s*PROGRAM\s+[A-Za-z_][A-Za-z0-9_]*", re.MULTILINE)
VAR_BLOCK_PATTERN = re.compile(r"\bVAR\b(.*?)\bEND_VAR\b", re.DOTALL | re.IGNORECASE)
DECLARATION_PATTERN = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:AT\s+(%[A-Za-z0-9.]+))?\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\:=\s*[^;]+)?;",
    re.MULTILINE
)
IDENTIFIER_PATTERN = re.compile(r"\b(?:[IQMTCRF]_[A-Za-z0-9_]+)\b")
LOCATION_PATTERN = re.compile(r"^%[IQM][A-Z]*\d+(?:\.\d+)?$", re.IGNORECASE)
STANDARD_DECLARATION_TYPES = {"BOOL", "INT", "REAL", "TON", "TP", "CTU", "R_TRIG", "F_TRIG"}
VALID_POU_TYPES = {"PROGRAM", "FUNCTION_BLOCK", "FUNCTION"}
FALLBACK_MARKERS = ("safe fallback", "fallback", "template_not_implemented", "intent_template_not_implemented")
INTENT_TOKEN_RULES = {
    "INT_TIMED_PULSE": ("T_Pulse5s", "Q_Aux_Output", "I_Start", "I_Emergency"),
    "INT_MOTOR_START_STOP": ("M_RunLatch", "I_Start", "I_Stop", "I_Emergency", "Q_Motor_Enable"),
    "INT_DELAYED_START": ("T_DelayStart", "Q_Motor_Enable", "I_Start", "I_Emergency"),
    "INT_DELAYED_STOP": ("T_StopDelay", "M_StopDelayActive", "Q_Motor_Enable", "I_Stop", "I_Emergency"),
    "INT_COUNTER_PULSES": ("C_PulseCount", "R_SensorPulse", "I_Sensor1")
}
REQUIRED_PACKAGE_FILES = {
    "full_program.st",
    "declarations.st",
    "implementation.st",
    "variables.json",
    "project_manifest.json",
    "pou_manifest.json",
    "task_config.json",
    "test_cases.json",
    "semantic_input.json",
    "semantic_validation.json",
    "generation_metadata.json",
    "retrieved_context.json",
    "verification.json"
}


def _normalize_target_platform(target_platform: str) -> str:
    normalized = (target_platform or "").strip().upper()
    if normalized in {"OPENPLC", "OPENPLC_ST"}:
        return "OPENPLC_ST"
    if normalized in {"SIEMENS", "SIEMENS_SCL", "SIEMENS_SCL_V18", "TIA", "TIA_V18"}:
        return "SIEMENS_SCL_V18"
    return "CODESYS_ST"


def _extract_declared_variables(st_code: str) -> dict[str, dict[str, str]]:
    declarations: dict[str, dict[str, str]] = {}
    for name, location, var_type in DECLARATION_PATTERN.findall(st_code):
        declarations[name] = {
            "location": location or "",
            "type": var_type
        }
    return declarations


def _extract_var_block(st_code: str) -> str:
    match = VAR_BLOCK_PATTERN.search(st_code)
    return match.group(1) if match else ""


def _extract_used_identifiers(st_code: str) -> set[str]:
    return set(IDENTIFIER_PATTERN.findall(st_code))


def _has_basic_st_structure(st_code: str) -> bool:
    return ":=" in st_code and ";" in st_code


def _contains_comments(st_code: str) -> bool:
    return "(*" in st_code and "*)" in st_code


def _is_fallback_or_unimplemented(implementation_code: str) -> bool:
    normalized = implementation_code.lower()
    if any(marker in normalized for marker in FALLBACK_MARKERS):
        return True

    lines = [line.strip() for line in implementation_code.splitlines() if line.strip() and not line.strip().startswith("(*")]
    if len(lines) == 1 and lines[0] == "Q_Aux_Output := FALSE;":
        return True

    return False


def _has_safe_contactor_logic(st_code: str) -> bool:
    both_forced_off = (
        re.search(r"Q_Contactor_A\s*:=\s*FALSE;", st_code)
        and re.search(r"Q_Contactor_B\s*:=\s*FALSE;", st_code)
    )
    explicit_interlock = (
        re.search(r"Q_Contactor_A\s*:=.*NOT\s+Q_Contactor_B", st_code, re.DOTALL)
        and re.search(r"Q_Contactor_B\s*:=.*NOT\s+Q_Contactor_A", st_code, re.DOTALL)
    )
    return bool(both_forced_off or explicit_interlock)


def verify_code(
    st_code: str,
    io_map: dict[str, Any],
    safety_rules: dict[str, Any],
    target_platform: str = "CODESYS_ST",
    declarations_code: str | None = None,
    implementation_code: str | None = None,
    intent_id: str | None = None
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    implementation = implementation_code or st_code
    declarations = declarations_code or st_code

    if not st_code.strip():
        return {
            "is_valid": False,
            "errors": ["No ST code was provided for verification."],
            "warnings": []
        }

    normalized_target = _normalize_target_platform(target_platform)
    declared_variables = _extract_declared_variables(declarations)
    declared_names = set(declared_variables)
    used_identifiers = _extract_used_identifiers(implementation)
    io_index = build_io_map_index(io_map)
    authorized_tags = flatten_io_map(io_map)

    if _is_fallback_or_unimplemented(implementation):
        errors.append("La implementacion corresponde a un fallback o a una plantilla no implementada.")

    if not PROGRAM_PATTERN.search(st_code):
        errors.append("El programa completo debe incluir una seccion PROGRAM.")
    if "VAR" not in st_code:
        errors.append("El programa completo debe incluir una seccion VAR.")
    if "END_VAR" not in st_code:
        errors.append("El programa completo debe incluir END_VAR.")
    if not _extract_var_block(st_code).strip():
        errors.append("La seccion VAR no contiene declaraciones.")

    if not _has_basic_st_structure(implementation):
        errors.append("El codigo no presenta una estructura basica valida de Structured Text.")
    if not _contains_comments(implementation):
        errors.append("La logica generada debe incluir comentarios en formato ST.")
    if "IF " in implementation and "END_IF;" not in implementation:
        errors.append("La estructura IF del codigo ST parece incompleta.")

    undeclared_used = sorted(identifier for identifier in used_identifiers if identifier not in declared_names)
    if undeclared_used:
        errors.append(
            "Las siguientes variables se usan en la implementacion pero no estan declaradas: "
            + ", ".join(undeclared_used)
        )

    unauthorized_used = sorted(identifier for identifier in used_identifiers if identifier not in authorized_tags)
    if unauthorized_used:
        errors.append("Se detectaron variables usadas fuera del io_map autorizado: " + ", ".join(unauthorized_used))

    unauthorized_declared = sorted(name for name in declared_names if name not in authorized_tags)
    if unauthorized_declared:
        errors.append("Se declararon variables fuera del io_map autorizado: " + ", ".join(unauthorized_declared))

    invalid_declaration_types = sorted(
        f"{name}:{data['type']}"
        for name, data in declared_variables.items()
        if data["type"].upper() not in STANDARD_DECLARATION_TYPES
    )
    if invalid_declaration_types:
        errors.append("Se detectaron tipos de declaracion no soportados: " + ", ".join(invalid_declaration_types))

    # Igual que en verify_project_ir: solo exigir el token I_Emergency si el banco activo
    # realmente lo tiene fisicamente (io_index) - de lo contrario semantic_repair ya lo sustituyo
    # por el literal "FALSE" en la implementacion, correctamente.
    if (
        "I_Emergency" in io_index
        and ("Q_Motor_Enable" in implementation or "Q_Aux_Output" in implementation)
        and "I_Emergency" not in implementation
    ):
        errors.append("Toda logica que controle motor o salida auxiliar debe considerar I_Emergency.")

    if any(data["type"].upper() in {"TON", "TP"} for data in declared_variables.values()) and "PT := T#" not in st_code:
        errors.append("Los temporizadores deben usar un literal TIME valido con PT := T#...")

    for name, data in declared_variables.items():
        location = data["location"]
        if location and not LOCATION_PATTERN.match(location):
            errors.append(f"La direccion fisica de {name} no tiene un formato valido: {location}")

    if normalized_target == "OPENPLC_ST":
        wrong_input_locations = [
            name for name, data in declared_variables.items()
            if name.startswith("I_") and data["location"] and not data["location"].upper().startswith("%IX")
        ]
        wrong_output_locations = [
            name for name, data in declared_variables.items()
            if name.startswith("Q_") and data["location"] and not data["location"].upper().startswith("%QX")
        ]
        if wrong_input_locations or wrong_output_locations:
            errors.append("OpenPLC_ST solo permite ubicaciones %IX para entradas y %QX para salidas.")
    else:
        if re.search(r"\bAT\s+%[IQM]", declarations, re.IGNORECASE):
            warnings.append("CODESYS_ST puede omitir AT para facilitar simulacion manual.")

    if "Q_Contactor_A" in implementation and "Q_Contactor_B" in implementation and not _has_safe_contactor_logic(implementation):
        errors.append(
            "La logica de enclavamiento mutuo no evita claramente la activacion simultanea "
            "de Q_Contactor_A y Q_Contactor_B."
        )

    if intent_id in INTENT_TOKEN_RULES:
        expected_tokens = INTENT_TOKEN_RULES[intent_id]
        if "I_Emergency" not in io_index:
            # Banco sin paro de emergencia cableado al PLC: el token esperado para este intent no
            # puede exigirse literalmente si el recurso fisico no existe - la logica generada
            # correctamente lo sustituyo por "FALSE" (ver semantic_repair.py).
            expected_tokens = tuple(token for token in expected_tokens if token != "I_Emergency")
        missing_tokens = [token for token in expected_tokens if token not in implementation]
        if missing_tokens:
            errors.append(
                "La implementacion no cumple los elementos minimos esperados para "
                f"{intent_id}: {', '.join(missing_tokens)}"
            )

    if len(io_index) != len(set(io_index)):
        errors.append("Se detectaron nombres duplicados en el mapa I/O.")

    validation_requirements = safety_rules.get("validation_requirements", [])
    if any("test cases" in str(requirement).lower() for requirement in validation_requirements):
        warnings.append("Asegure que este caso quede registrado tambien como prueba funcional basica.")

    return {
        "is_valid": not errors,
        "errors": errors,
        "warnings": warnings
    }


def _effective_parameters(project_ir: PLCProjectIR) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Parametros efectivos congelados de la IR (la MISMA fuente que code_generator) y su procedencia."""
    metadata = project_ir.metadata or {}
    semantic_output = metadata.get("semantic_output") if isinstance(metadata.get("semantic_output"), dict) else {}
    parameters = semantic_output.get("parameters")
    if not isinstance(parameters, dict):
        parameters = metadata.get("parameters") if isinstance(metadata.get("parameters"), dict) else {}
    provenance = semantic_output.get("parameter_provenance")
    return parameters, provenance if isinstance(provenance, dict) else None


# Miembros de instancia IEC validos en TODAS las plataformas destino (TIA V18, OpenPLC, CODESYS). Un CTU no tiene
# salida "alcanzado" portable (TIA: QU, IEC: Q): se usa la salida EXPLICITA de su llamada (Q => ...), nunca un miembro.
PORTABLE_INSTANCE_MEMBERS = {"TON": {"Q", "ET"}, "TP": {"Q", "ET"}, "CTU": {"CV"}, "R_TRIG": {"Q"}, "F_TRIG": {"Q"}}
INSTANCE_MEMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_#])#?([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)")
INVALID_INSTANCE_MEMBER = "INVALID_INSTANCE_MEMBER"


def instance_member_errors(project_ir: PLCProjectIR) -> list[str]:
    """
    Antes de TIA: todo acceso "<x>.<miembro>" debe ser sobre una INSTANCIA IEC declarada y a un miembro que esa
    instancia expone en todas las plataformas. Un acceso a un miembro de una variable simple, o a "C_x.Q" de un CTU
    ("Tag #C_x.Q not defined" en TIA V18), es un error de generacion nuestro, no algo que deba descubrir TIA.
    """
    types = {variable.name: variable.data_type for variable in project_ir.pou.variables}
    errors = []
    for owner, member in sorted(set(INSTANCE_MEMBER_PATTERN.findall(project_ir.pou.implementation_code or ""))):
        if owner not in types:
            continue  # identificadores no declarados ya se informan aparte
        allowed = PORTABLE_INSTANCE_MEMBERS.get(types[owner])
        if allowed is None:
            errors.append(f"{INVALID_INSTANCE_MEMBER}: {owner}.{member} - {owner} es {types[owner]}, no una instancia IEC "
                          "con miembros.")
        elif member not in allowed:
            errors.append(f"{INVALID_INSTANCE_MEMBER}: {owner}.{member} - una instancia {types[owner]} no expone '{member}' "
                          f"en todas las plataformas (validos: {', '.join(sorted(allowed))}); use la salida explicita de "
                          "la llamada (p.ej. Q => <variable BOOL>).")
    return errors


def verify_project_ir(project_ir: PLCProjectIR) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if project_ir.pou is None:
        errors.append("La representacion intermedia no contiene una POU.")
        return {"is_valid": False, "errors": errors, "warnings": warnings}

    if project_ir.pou.pou_type not in VALID_POU_TYPES:
        errors.append(f"El tipo de POU no es valido: {project_ir.pou.pou_type}")

    if project_ir.pou.language != "ST":
        errors.append("La representacion intermedia debe usar lenguaje ST.")

    if project_ir.task.pou_name != project_ir.pou.name:
        errors.append("La tarea principal no esta asociada a la POU PLC_PRG.")

    variable_names = [variable.name for variable in project_ir.pou.variables]
    folded_names=[name.casefold() for name in variable_names]
    duplicate_variables = sorted({name for name in variable_names if folded_names.count(name.casefold()) > 1})
    if duplicate_variables:
        errors.append("La POU contiene variables duplicadas: " + ", ".join(duplicate_variables))

    declared_names = set(variable_names)
    used_identifiers = _extract_used_identifiers(project_ir.pou.implementation_code)
    undeclared_identifiers = sorted(identifier for identifier in used_identifiers if identifier not in declared_names)
    if undeclared_identifiers:
        errors.append("La IR usa variables no declaradas: " + ", ".join(undeclared_identifiers))

    authorized_variables = set(project_ir.metadata.get("authorized_variables", []))
    unauthorized_declared = sorted(name for name in declared_names if authorized_variables and name not in authorized_variables)
    if unauthorized_declared:
        errors.append("La IR declara variables fuera del io_map autorizado: " + ", ".join(unauthorized_declared))

    if _is_fallback_or_unimplemented(project_ir.pou.implementation_code):
        errors.append("La implementacion de la IR es un fallback o plantilla no implementada.")

    # Ningun functional_requirement puede desaparecer en silencio entre el semantic_output y la
    # IR: si el catalogo dice que "run_pilot" implica Q_Pilot_Run, esa variable debe estar
    # declarada. Si falta, es un error de propagacion, no un exito silencioso (seccion 7).
    # Los recursos que dependen de un parametro (FUNCTIONAL_REQUIREMENT_PARAMETER_TAGS) se resuelven con
    # los MISMOS parametros efectivos congelados que uso el generador (semantic_output.parameters), nunca
    # con una lista estatica ciega: un literal seguro (emergency_input = FALSE) no exige variable PLC.
    effective_parameters, effective_provenance = _effective_parameters(project_ir)
    tags_required_by_requirements: set[str] = set()
    pending_resource_checks: list[tuple[str, dict[str, Any]]] = []
    for requirement in project_ir.metadata.get("functional_requirements", []) or []:
        if not is_catalog_functional_requirement(requirement):
            continue
        requirement_type = requirement.get("type", "")
        try:
            required_tags = get_functional_requirement_tags(requirement, effective_parameters, effective_provenance)
            parameter_resources = resolve_parameter_resources(requirement, effective_parameters, effective_provenance)
        except ParameterResourceError as error:
            errors.append(str(error))
            continue
        tags_required_by_requirements.update(required_tags)
        pending_resource_checks.extend((requirement_type, resource) for resource in parameter_resources)
        for tag in required_tags:
            if tag not in declared_names:
                errors.append(
                    f"El requisito funcional '{requirement_type}' no se propago a la IR: "
                    f"falta la variable {tag}."
                )
    # Recursos realmente usados por IR/SCL == semantica efectiva: un recurso resuelto a literal no puede
    # reaparecer como tag (ghost) salvo que OTRO requisito lo exija por si mismo, y un tag resuelto debe
    # usarse en la logica generada.
    for requirement_type, resource in pending_resource_checks:
        default = resource["contract_default"]
        ghost = default not in tags_required_by_requirements and (default in used_identifiers or default in declared_names)
        if resource["resolution"] == RESOURCE_SAFE_LITERAL and ghost:
            errors.append(
                f"El requisito funcional '{requirement_type}' usa {default} aunque la semantica efectiva fijo "
                f"{resource['parameter']} = {resource['value']} (literal seguro, sin recurso fisico)."
            )
        elif resource["resolution"] == RESOURCE_TAG and resource["tag"] not in used_identifiers:
            errors.append(
                f"El requisito funcional '{requirement_type}' resolvio {resource['parameter']} = {resource['tag']}, "
                "pero la logica generada no lo usa."
            )

    # Banco sin paro de emergencia cableado al PLC (regla definitiva - ver semantic_repair.py):
    # esta exigencia solo aplica si I_Emergency es un recurso fisico realmente disponible en el
    # mapa activo (reflejado en authorized_variables, via io_index). Si no lo es,
    # semantic_repair.strip_unavailable_emergency_reference ya sustituyo la referencia por el
    # literal booleano "FALSE" en la logica generada - exigir aqui el TOKEN LITERAL "I_Emergency"
    # de todas formas repetiria exactamente el bug ya corregido (generacion exitosa, verificacion
    # fallando igual por un requisito que contradice el banco real).
    critical_outputs = {"Q_Motor_Enable", "Q_Aux_Output", "Q_Contactor_A", "Q_Contactor_B"}
    bench_has_emergency = "I_Emergency" in authorized_variables
    if (
        bench_has_emergency
        and used_identifiers.intersection(critical_outputs)
        and "I_Emergency" not in project_ir.pou.implementation_code
    ):
        errors.append("Toda logica de salidas criticas debe incluir la senal I_Emergency.")

    for variable in project_ir.pou.variables:
        if variable.location and not LOCATION_PATTERN.match(variable.location):
            errors.append(f"La ubicacion de {variable.name} no tiene formato valido: {variable.location}")
        if variable.data_type not in STANDARD_DECLARATION_TYPES and not (
                project_ir.pid_loops and variable.source=='generated_pid' and variable.name in {'ErrorBits','CurrentErrorBits'} and variable.data_type=='DWORD'):
            errors.append(f"Tipo de variable no soportado en IR: {variable.name}:{variable.data_type}")

    timer_variables = [variable for variable in project_ir.pou.variables if variable.data_type in {"TON", "TP"}]
    if timer_variables and not TIME_LITERAL_PATTERN.search(project_ir.pou.implementation_code):
        errors.append("La IR declara temporizadores pero no usa literales TIME validos.")

    invalid_standard_blocks = [
        variable.name
        for variable in project_ir.pou.variables
        if variable.is_standard_block and variable.data_type not in {"TON", "TP", "CTU", "R_TRIG", "F_TRIG"}
    ]
    if invalid_standard_blocks:
        errors.append("Se declararon bloques estandar no soportados: " + ", ".join(invalid_standard_blocks))

    if {"Q_Contactor_A", "Q_Contactor_B"}.issubset(used_identifiers) and not _has_safe_contactor_logic(project_ir.pou.implementation_code):
        errors.append("La IR no garantiza enclavamiento mutuo seguro entre Q_Contactor_A y Q_Contactor_B.")

    if ((project_ir.metadata or {}).get("semantic_output") or {}).get("interaction_profile") == "normal":
        errors.extend(instance_member_errors(project_ir))

    if not project_ir.test_cases:
        errors.append("La representacion intermedia debe incluir test cases basicos.")

    if not project_ir.safety_rules:
        warnings.append("La IR no incluye reglas de seguridad serializadas.")

    if not project_ir.metadata.get("required_variables"):
        warnings.append("La IR no registra explicitamente las variables requeridas por la intencion.")

    return {
        "is_valid": not errors,
        "errors": errors,
        "warnings": warnings
    }


def _read_json_file(path: Path) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except OSError as error:
        return None, str(error)
    except json.JSONDecodeError as error:
        return None, f"JSON invalido en {path.name}: {error}"


def verify_generated_package(package_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not package_dir.exists() or not package_dir.is_dir():
        return {
            "is_valid": False,
            "errors": [f"La carpeta del paquete no existe: {package_dir}"],
            "warnings": []
        }

    existing_files = {path.name for path in package_dir.iterdir() if path.is_file()}
    missing_files = sorted(REQUIRED_PACKAGE_FILES.difference(existing_files))
    if missing_files:
        errors.append("Faltan archivos obligatorios del paquete: " + ", ".join(missing_files))

    project_manifest: dict[str, Any] | None = None
    pou_manifest: dict[str, Any] | None = None
    task_config: dict[str, Any] | None = None
    test_cases: list[Any] | dict[str, Any] | None = None
    verification_payload: dict[str, Any] | list[Any] | None = None

    for json_name in (
        "project_manifest.json",
        "pou_manifest.json",
        "task_config.json",
        "test_cases.json",
        "semantic_input.json",
        "semantic_validation.json",
        "generation_metadata.json",
        "retrieved_context.json",
        "verification.json",
        "variables.json"
    ):
        json_path = package_dir / json_name
        if not json_path.exists():
            continue
        payload, error = _read_json_file(json_path)
        if error:
            errors.append(error)
            continue

        if json_name == "project_manifest.json" and isinstance(payload, dict):
            project_manifest = payload
        elif json_name == "pou_manifest.json" and isinstance(payload, dict):
            pou_manifest = payload
        elif json_name == "task_config.json" and isinstance(payload, dict):
            task_config = payload
        elif json_name == "test_cases.json":
            test_cases = payload
        elif json_name == "verification.json":
            verification_payload = payload

    if project_manifest and pou_manifest:
        if project_manifest.get("pou_name") != pou_manifest.get("name"):
            errors.append("El project_manifest y el pou_manifest no coinciden en el nombre de la POU.")
        if project_manifest.get("language") != pou_manifest.get("language"):
            errors.append("El lenguaje declarado en los manifiestos no es consistente.")

    if task_config and pou_manifest:
        if task_config.get("pou_instance") != pou_manifest.get("name"):
            errors.append("La tarea no apunta a la POU declarada en el manifiesto.")

    if isinstance(test_cases, list) and not test_cases:
        errors.append("El paquete debe incluir al menos un caso de prueba.")
    elif test_cases is None:
        warnings.append("No fue posible validar el contenido de test_cases.json.")

    if isinstance(verification_payload, dict) and "is_valid" not in verification_payload:
        warnings.append("verification.json no incluye el campo is_valid.")

    expected_status_keys = (
        "generation_status",
        "compilation_status",
        "simulation_status",
        "physical_deployment_status"
    )
    if isinstance(project_manifest, dict):
        missing_status = [key for key in expected_status_keys if key not in project_manifest]
        if missing_status:
            errors.append("project_manifest.json no incluye estados obligatorios: " + ", ".join(missing_status))

    if isinstance(pou_manifest, dict):
        missing_pou_status = [key for key in expected_status_keys if key not in pou_manifest]
        if missing_pou_status:
            errors.append("pou_manifest.json no incluye estados obligatorios: " + ", ".join(missing_pou_status))

    return {
        "is_valid": not errors,
        "errors": errors,
        "warnings": warnings
    }
