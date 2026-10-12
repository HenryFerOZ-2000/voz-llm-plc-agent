"""
Construye el benchmark v3 (FORMAL) a partir del v2 (historico DEVELOPMENT), de forma reproducible.

Origen: auditorias metodologicas de ambiguedad D01-D20 (60 variantes) y P01-P12 (36 variantes) y las decisiones
humanas aprobadas (2026-10-12). Criterio unico: ALINEACION ENTRE ESPECIFICACION TEXTUAL Y GROUND TRUTH. Ningun
cambio altera el comportamiento funcional que evaluan los Oracles (test_sequence, invariantes, tiempos, cleanup,
roles y reglas de veredicto quedan identicos). La unica modificacion de un Oracle mas alla de metadata es la de
semantic_expectations de D03 (simetria con D04/D11), registrada por separado.

Pasos (se detiene ante cualquier discrepancia):
  1. Archiva el v2 VIVO, byte a byte, en data/experiment_benchmark/versions/benchmark_v2/ con manifest de hashes.
  2. Catalogo v3: textos de 16 casos (D05 D08 D13 D15 D17 D19 P01 P04 P05 P06 P07 P08 P09 P10 P11 P12),
     benchmark_version = 3 en los 32 casos (el hash canonico cambia en todos: lo registra cada ensayo).
  3. Sincroniza profiles.json y experiment_variants.json desde el catalogo.
  4. Oracles: nueva version de los 32 (source_definition -> v3; D03 ademas semantic_expectations), archivando la
     version previa en experiment_oracles/versions/. La nueva version queda DRAFT_REVIEWED con
     approval.technical_validation = PASSED y approval.human_formal_approval = PENDING: el script NUNCA firma una
     aprobacion humana (approved_by queda null). La aprobacion formal es una accion explicita del investigador
     (ventana REVISION DE ORACLES / oracle_review.approve_all_without_review_items con frase de confirmacion).
  5. Regenera informes (consistencia de variantes, validacion de Oracles, resumen, catalogo de comandos).
  6. experimental_design.json -> benchmark_version 3 (el diseno v2 queda en el archivo historico).
  7. Escribe docs/benchmark_v3_changelog.md.

Uso:  .venv/Scripts/python.exe scripts/build_benchmark_v3.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trial_experiments import benchmark_catalog as BC  # noqa: E402
from trial_experiments import oracle_review as OR  # noqa: E402
from trial_experiments import oracle_schema as S  # noqa: E402

HUMAN_APPROVAL_PENDING = "PENDING"  # nunca se escribe el nombre de una persona desde este script
DECISION_DATE = "2026-10-12"
ARCHIVE_DIR = ROOT / "data" / "experiment_benchmark" / "versions" / "benchmark_v2"
CATALOG = ROOT / "data" / "experiment_cases" / "canonical_cases.json"
DESIGN = ROOT / "data" / "experimental_design.json"
CHANGELOG = ROOT / "docs" / "benchmark_v3_changelog.md"

# Archivo historico v2: rutas relativas a la raiz del proyecto -> ruta dentro del archivo.
ARCHIVE_FILES = {
    "data/experiment_cases/canonical_cases.json": "canonical_cases.json",
    "data/plc_maps/experiment_variants.json": "experiment_variants.json",
    "data/plc_maps/profiles.json": "profiles.json",
    "data/experimental_design.json": "experimental_design.json",
    "data/variant_consistency_report.json": "variant_consistency_report.json",
    "data/oracle_validation_report.json": "oracle_validation_report.json",
    "data/system_capability_gaps.json": "system_capability_gaps.json",
    "docs/experiment_command_catalog.md": "docs/experiment_command_catalog.md",
    "docs/oracle_review_summary.md": "docs/oracle_review_summary.md",
}

# ---------------------------------------------------------------------------------------------
# Cambios de texto aprobados (auditorias D y P). "ambiguity": que ambiguedad elimina (taxonomia A-K).
# ---------------------------------------------------------------------------------------------

CHANGES: dict[str, dict[str, Any]] = {
    "D05": {
        "ambiguity": "E (MISSING_ACTOR_OR_RESOURCE): 'condicion de seguridad normal' y 'condicion de emergencia' podian leerse "
                     "como dos senales; el Oracle usa una unica senal logica de emergencia (SAFETY_TRIP).",
        "canonical": "Enciende un motor con Start solo si no hay una condición de emergencia activa. Si se activa la emergencia, "
                     "apaga el motor y bloquea el arranque mientras permanezca activa.",
        "V1": "Arranca el motor con Start únicamente si no hay emergencia activa; si se activa, apágalo y bloquea el arranque "
              "mientras siga activa.",
        "V2": "Quiero que el motor arranque con Start solo sin emergencia, y que una emergencia lo apague y no deje arrancarlo "
              "mientras dure.",
        "V3": "Mientras la condición de emergencia esté activa, el motor debe estar apagado y Start no puede arrancarlo; sin "
              "emergencia, Start enciende el motor.",
        "requirements": {"R1": "Sin emergencia activa, Start enciende el motor."},
    },
    "D08": {
        "ambiguity": "D/I: 'Al activar Start, enciende el motor' admitia leer que el motor solo funciona mientras se mantiene Start; "
                     "el Oracle (step_2) suelta Start a los 300 ms y exige el motor en marcha hasta los 10 s.",
        "canonical": "Al activar Start, enciende el motor, mantenlo en marcha aunque se suelte Start y apágalo automáticamente "
                     "después de 10 segundos de funcionamiento continuo.",
        "V1": "Enciende el motor con Start, que siga en marcha aunque se suelte el pulsador, y apágalo automáticamente tras 10 "
              "segundos de funcionamiento.",
        "V2": "Haz que el motor arranque con Start, siga funcionando aunque se suelte y se detenga solo tras 10 segundos.",
        "V3": "Cuando se active Start, mantén el motor funcionando 10 segundos, aunque se suelte el pulsador, y después apágalo.",
        "requirements": {"R2": "El motor sigue en marcha tras soltar Start y, a los 10 s de funcionamiento continuo, se apaga "
                               "automaticamente."},
    },
    "D13": {
        "ambiguity": "A/I (ACTION_VS_CONDITION, TEMPORAL): 'ante una orden de marcha, habilita... solo si' admitia comprobar la "
                     "alarma solo al dar la orden; el Oracle (step_2, INV_ALARM_VFD CRITICAL) exige un permisivo continuo.",
        "canonical": "Con una orden de marcha, habilita el variador solo mientras no exista una alarma activa; si la alarma aparece "
                     "con el variador habilitado, deshabilítalo.",
        "V1": "Habilita el variador con la orden de marcha únicamente mientras no haya alarma activa; si aparece una alarma, "
              "deshabilítalo.",
        "V2": "Quiero que el variador se habilite con la orden de marcha, pero nunca mientras exista una alarma activa, ni "
              "siquiera si ya estaba funcionando.",
        "V3": "Mientras haya una alarma activa el variador debe estar deshabilitado, aunque tenga orden de marcha; sin alarma, "
              "habilítalo con esa orden.",
        "requirements": {"R2": "Si aparece una alarma con el variador habilitado, el variador se deshabilita; con alarma activa "
                               "nunca esta habilitado."},
    },
    "D15": {
        "ambiguity": "H (MODE_AMBIGUITY): no decia si Manual es 'no Automatico' (un selector) o una entrada propia; el Oracle usa "
                     "un unico selector MODE_AUTO (C-D15-MODES).",
        "canonical": "El operador elige el modo del motor con un selector Manual/Automático: en Automático el motor sigue la orden "
                     "automática y en Manual sigue la orden manual; la orden del otro modo no tiene efecto.",
        "V1": "Con un selector Manual/Automático: en Automático, el motor obedece la orden automática; en Manual, la orden manual; "
              "la otra orden se ignora.",
        "V2": "Quiero un selector Manual/Automático: en Automático el motor responde a la orden automática y en Manual a la orden "
              "manual, sin que la otra orden haga nada.",
        "V3": "Según la posición del selector, Manual o Automático, el motor atiende la orden manual o la orden automática "
              "respectivamente, e ignora la del otro modo.",
    },
    "D17": {
        "ambiguity": "I/A (TEMPORAL): 'si no cambia de estado durante 5 segundos' admitia una ventana unica tras Start; el Oracle "
                     "(t4_timeout) cuenta los 5 s desde el ultimo cambio del sensor.",
        "canonical": "Al activar Start, supervisa un sensor: si pasan 5 segundos sin que cambie de estado, activa una alarma; cada "
                     "cambio del sensor vuelve a contar los 5 segundos.",
        "V1": "Tras activar Start, vigila el sensor y activa una alarma si transcurren 5 segundos sin ningún cambio; cada cambio "
              "reinicia la cuenta.",
        "V2": "Quiero que, después de dar Start, salte una alarma si el sensor pasa cinco segundos seguidos sin cambiar de estado.",
        "V3": "Con Start activado, si el sensor permanece sin cambios durante 5 segundos seguidos, activa la alarma.",
        "requirements": {"R3": "Si el sensor no cambia durante 5 s contados desde su ultimo cambio, se activa la alarma."},
    },
    "D19": {
        "ambiguity": "E (MISSING_ACTOR_OR_RESOURCE): no decia de donde sale el estado; el Oracle recibe marcha y falla como "
                     "senales del sistema (C-D19-INPUTS).",
        "canonical": "Controla tres pilotos según las señales de marcha y de falla del sistema: detenido, marcha y falla, "
                     "manteniendo activo únicamente el del estado actual.",
        "V1": "Con las señales de marcha y falla del sistema, controla tres pilotos (detenido, marcha y falla) y deja encendido "
              "solo el del estado actual.",
        "V2": "Quiero tres pilotos, detenido, marcha y falla, que según las señales de marcha y falla del sistema dejen encendido "
              "solo el que corresponde al estado actual.",
        "V3": "A partir de las señales de marcha y de falla, indica con tres pilotos si el sistema está detenido, en marcha o en "
              "falla; únicamente debe encenderse el del estado actual.",
    },
    "P01": {
        "ambiguity": "A/H: 'Habilita el modo automatico' admitia 'permitir que se pueda seleccionar'; el Oracle exige que el modo "
                     "pase a automatico solo al seleccionarlo (step_0/step_1).",
        "canonical": "El sistema de nivel debe pasar a modo automático solo cuando el operador seleccione Automático.",
        "V1": "Pasa el sistema de nivel a modo automático únicamente cuando el operador seleccione Automático.",
        "V2": "Quiero que el control de nivel entre en automático solo si el operador elige Automático.",
        "V3": "Solo al seleccionar el operador Automático debe el sistema de nivel ponerse en modo automático.",
        "variant_check": {"required_concepts": ["automatic", "nivel", "seleccion|elij|elig"], "numbers": []},
        "requirements": {"R1": "Al seleccionar Automatico, el sistema de nivel pasa a modo automatico.",
                         "R2": "Sin seleccionar Automatico, el sistema no pasa a modo automatico ('solo cuando')."},
    },
    "P04": {
        "ambiguity": "D (MISSING_LATCH_RESET_RULE): no decia que la alarma se desactiva al bajar del umbral; el Oracle (step_2) lo "
                     "exige (alarma no enclavada).",
        "canonical": "Activa la alarma de nivel alto mientras el nivel esté por encima del 90 % y desactívala cuando vuelva a 90 % "
                     "o menos.",
        "V1": "Mantén activa la alarma de nivel alto mientras el nivel supere el 90 % y apágala cuando baje a 90 % o menos.",
        "V2": "Quiero que la alarma de nivel alto suene mientras el nivel pase del noventa por ciento y se quite al volver a "
              "noventa o menos.",
        "V3": "Con el nivel por encima del 90 %, la alarma de nivel alto debe estar activa; a 90 % o menos, desactivada.",
        "requirements": {"R2": "Con el nivel en 90 % o menos no hay alarma de nivel alto (se desactiva al volver)."},
    },
    "P05": {
        "ambiguity": "D (+ I en V1): no decia que la alarma se desactiva al subir del umbral; V1 'cuando baje del 10 %' admitia una "
                     "lectura de flanco; el Oracle (step_2) exige alarma no enclavada.",
        "canonical": "Activa la alarma de nivel bajo mientras el nivel esté por debajo del 10 % y desactívala cuando vuelva a 10 % "
                     "o más.",
        "V1": "Mantén activa la alarma de nivel bajo mientras el nivel esté por debajo del 10 % y apágala cuando suba a 10 % o más.",
        "V2": "Quiero que la alarma de nivel bajo suene mientras el nivel sea inferior al diez por ciento y se quite al volver a "
              "diez o más.",
        "V3": "Con el nivel por debajo del 10 %, la alarma de nivel bajo debe estar activa; a 10 % o más, desactivada.",
        "requirements": {"R2": "Con el nivel en 10 % o mas no hay alarma de nivel bajo (se desactiva al volver)."},
    },
    "P06": {
        "ambiguity": "A/H/E: 'Habilita el PID unicamente cuando el sistema este en Automatico' admitia una orden de poner el "
                     "Automatico; el Oracle trata el modo como seleccion del operador (C-P06) y exige el PID deshabilitado en "
                     "Manual (pre_manual, step_2, INV_PID_ONLY_AUTO). Sin instrucciones negativas tipo 'no cambies el modo'.",
        "canonical": "El PID solo debe estar habilitado mientras el sistema se encuentre en modo Automático, que selecciona el "
                     "operador; en modo Manual debe permanecer deshabilitado.",
        "V1": "Mantén el PID habilitado únicamente mientras el operador tenga el sistema en Automático; en Manual, deshabilitado.",
        "V2": "Quiero que el PID solo funcione cuando el operador haya puesto el sistema en Automático, y que en Manual quede "
              "deshabilitado.",
        "V3": "Solo con el sistema en el modo Automático elegido por el operador puede estar habilitado el PID; en Manual debe "
              "estar deshabilitado.",
        "variant_check": {"required_concepts": ["\\bpid\\b", "automatic", "manual", "operador", "solo|unicamente|solamente"],
                          "numbers": []},
        "requirements": {"R2": "En Manual (fuera de Automatico) el PID esta deshabilitado."},
    },
    "P07": {
        "ambiguity": "J (HIDDEN_ORACLE_REQUIREMENT): el Oracle exige el PID habilitado en Automatico antes del disparo "
                     "(pre_enabled); el comando lo presuponia sin decirlo. Se completa el comando (no se relaja el Oracle).",
        "canonical": "Con el sistema en Automático el PID trabaja habilitado; si se activa una condición de emergencia, "
                     "deshabilita el PID de inmediato.",
        "V1": "En Automático el PID funciona habilitado, pero si se activa una emergencia, deshabilítalo inmediatamente.",
        "V2": "Quiero que el PID esté habilitado en Automático y que, si hay una emergencia, se deshabilite en el acto.",
        "V3": "Ante una condición de emergencia, el PID, que en Automático está habilitado, debe deshabilitarse de inmediato.",
        "variant_check": {"required_concepts": ["emergencia", "\\bpid\\b", "deshabilit", "automatic"], "numbers": []},
        "requirements_prepend": [{"id": "R0", "text": "En Automatico, sin emergencia, el PID esta habilitado.",
                                  "oracle_evidence": ["pre_enabled"]}],
    },
    "P08": {
        "ambiguity": "H (MODE_AMBIGUITY): no decia que Manual equivale a 'no Automatico'; el Oracle solo pone AUTO_MODE = falso "
                     "(pre_manual). V1 convertia el permiso en accion directa.",
        "canonical": "Cuando el sistema esté en modo Manual, es decir, siempre que no esté en Automático, la bomba debe encenderse "
                     "y apagarse solo con la orden manual del operador; el control automático no debe actuar sobre ella.",
        "V1": "Siempre que el sistema no esté en Automático, o sea en Manual, la orden manual del operador enciende y apaga la "
              "bomba, sin que actúe el control automático.",
        "V2": "Quiero que, mientras el sistema no esté en Automático, la bomba solo se encienda y apague con la orden manual del "
              "operador.",
        "V3": "Fuera del modo Automático, en Manual, la bomba debe seguir únicamente la orden manual del operador para encenderse "
              "o apagarse.",
    },
    "P09": {
        "ambiguity": "D (MISSING_LATCH_RESET_RULE): no decia que el fallo desaparece al volver al rango; el Oracle (step_2) lo exige.",
        "canonical": "Indica fallo del sensor mientras el nivel medido esté por debajo de 0 % o por encima de 100 %; cuando vuelva "
                     "a estar entre 0 % y 100 %, el fallo debe desaparecer.",
        "V1": "Señala fallo de sensor mientras el nivel medido esté fuera de 0 % a 100 % y quítalo cuando vuelva a ese rango.",
        "V2": "Quiero que se marque fallo del sensor mientras el nivel medido salga del rango de cero a cien por ciento, y que se "
              "quite al volver a él.",
        "V3": "Con el nivel medido por debajo de 0 % o por encima de 100 % debe haber fallo de sensor; dentro de ese rango, no.",
        "requirements": {"R3": "Con el nivel de nuevo dentro de 0-100 % no hay fallo de sensor (desaparece al volver)."},
    },
    "P10": {
        "ambiguity": "G/J: el Oracle exige que la alarma la provoque el fallo del sensor (pre_fault) y usa como 'rango valido' "
                     "0-100 % (C-P10, de P09); el comando presuponia la alarma y no daba el rango.",
        "canonical": "Activa una alarma cuando el nivel medido salga del rango de 0 % a 100 % por fallo del sensor. Mientras la "
                     "medición siga fuera de ese rango, el Reset no debe borrar la alarma; cuando vuelva al rango, el Reset sí "
                     "debe borrarla.",
        "V1": "Genera una alarma si el nivel medido sale de 0 % a 100 % por fallo del sensor; el Reset no la borra mientras siga "
              "fuera y sí cuando vuelva al rango.",
        "V2": "Quiero una alarma por fallo del sensor cuando la medición salga de cero a cien por ciento, que no se pueda resetear "
              "mientras dure y sí al volver al rango.",
        "V3": "Un nivel medido fuera de 0 % a 100 % debe activar la alarma de fallo del sensor; el Reset solo la borra cuando la "
              "medición vuelve a ese rango.",
        "variant_check": {"required_concepts": ["alarma", "fallo|falla", "sensor", "\\breset", "rango|valid"], "numbers": [0, 100]},
        "requirements_prepend": [{"id": "R0", "text": "Un nivel medido fuera de 0-100 % activa la alarma por fallo del sensor.",
                                  "oracle_evidence": ["pre_fault"]}],
    },
    "P11": {
        "ambiguity": "J (HIDDEN_ORACLE_REQUIREMENT): el Oracle exige la bomba en marcha con nivel normal antes del sobrellenado "
                     "(pre_normal); el comando no lo decia. Se completa el comando (no se relaja el Oracle).",
        "canonical": "En operación normal la bomba está en marcha; si el nivel alcanza o supera el 95 %, considéralo sobrellenado y "
                     "mantén la bomba apagada mientras dure esa condición.",
        "V1": "Con el nivel normal la bomba funciona; si el nivel llega o supera el 95 %, trátalo como sobrellenado y apaga la "
              "bomba mientras dure.",
        "V2": "Quiero que la bomba trabaje normalmente y que se apague mientras el nivel esté en el noventa y cinco por ciento o "
              "más, por sobrellenado.",
        "V3": "La bomba, en marcha en condiciones normales, debe quedar apagada mientras el nivel sea igual o superior al 95 % "
              "(sobrellenado).",
        "requirements_prepend": [{"id": "R0", "text": "En operacion normal (nivel por debajo de 95 %) la bomba esta en marcha.",
                                  "oracle_evidence": ["pre_normal"]}],
    },
    "P12": {
        "ambiguity": "F/G/C: 'condicion segura', 'rango permitido' y la recuperacion automatica solo estaban en aclaraciones del "
                     "catalogo; el Oracle exige PID deshabilitado y bomba apagada (step_2) y rehabilitacion sin Reset a 90 % o "
                     "menos (step_3).",
        "canonical": "En modo Automático, habilita el PID con un setpoint del 60 %. Si el nivel supera el 90 %, activa la alarma y "
                     "lleva el proceso a condición segura: PID deshabilitado y bomba apagada. Cuando el nivel vuelva a 90 % o "
                     "menos, el PID debe volver a habilitarse por sí solo, sin intervención del operador.",
        "V1": "En Automático, PID habilitado con setpoint del 60 %; por encima del 90 %, alarma y condición segura (PID "
              "deshabilitado y bomba apagada); al volver a 90 % o menos, el PID se rehabilita solo, sin que intervenga el operador.",
        "V2": "Quiero que en Automático el PID trabaje con un setpoint del sesenta por ciento; que por encima del noventa por ciento "
              "suene la alarma y se pare el PID y la bomba; y que, al volver a noventa o menos, el PID se reactive solo.",
        "V3": "Con el sistema en Automático y setpoint del 60 %, habilita el PID; un nivel mayor del 90 % activa la alarma, "
              "deshabilita el PID y apaga la bomba; al regresar a 90 % o menos, el PID vuelve a habilitarse automáticamente.",
        "variant_check": {"required_concepts": ["automatic", "\\bpid\\b", "setpoint", "alarma", "bomba", "habilit|reactiv"],
                          "numbers": [60, 90]},
        "requirements": {"R3": "Con el nivel en 90 % o menos, el PID vuelve a habilitarse por si solo (sin Reset ni intervencion)."},
    },
}

# Unificacion de nombres funcionales (metadata descriptiva del catalogo, no puntua): se alinean con las
# required_functions de los Oracles congelados. P06/P08 ya coinciden con su Oracle; su diferencia con los tipos de
# requisito del generador (enable_pid, manual_pump_limit) es de codigo y solo se reporta.
FUNCTION_NAMES = {
    "P03": ["reject_unsafe_setpoint"],
    "P07": ["safety_trip_disables_pid"],
    "P11": ["safe_overfill_stop"],
}

D03_ACCEPTED = ["INT_MOTOR_START_STOP", "INT_MOTOR_LATCH"]
D03_NOTE = ("Benchmark v3: se aceptan INT_MOTOR_START_STOP e INT_MOTOR_LATCH por simetria funcional con D04/D11 "
            "(misma memoria de marcha). Cambio SEMANTICO, no funcional: test_sequence identico.")
D20_DURATION_TEXT = "Duracion de ejecucion de 3 s, fijada por el comando canonico."


# ---------------------------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------------------------

def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _fail(message: str) -> None:
    raise SystemExit(f"ABORT: {message}")


# ---------------------------------------------------------------------------------------------
# 1. Archivo v2
# ---------------------------------------------------------------------------------------------

def archive_v2() -> dict[str, Any]:
    sources: dict[str, Path] = {relative: ROOT / relative for relative in ARCHIVE_FILES}
    for path in sorted((ROOT / "data" / "experiment_oracles").glob("*.json")):
        sources[f"data/experiment_oracles/{path.name}"] = path
    for path in sorted((ROOT / "data" / "experiment_oracles" / "versions").glob("*.json")):
        sources[f"data/experiment_oracles/versions/{path.name}"] = path
    targets = {relative: ARCHIVE_FILES.get(relative, relative.replace("data/", "", 1)) for relative in sources}
    manifest_path = ARCHIVE_DIR / "manifest.json"
    if manifest_path.exists():
        _fail(f"{manifest_path} ya existe: el benchmark v2 ya fue archivado (el script no se reejecuta sobre v3).")
    if json.loads(CATALOG.read_text(encoding="utf-8")).get("benchmark_version") != 2:
        _fail("el catalogo vivo no es benchmark v2.")
    files, raw = {}, {}
    for relative, source in sources.items():
        target = ARCHIVE_DIR / targets[relative]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)  # copia BYTE A BYTE
        if _raw_sha(target) != _raw_sha(source):
            _fail(f"la copia de {relative} no es identica.")
        files[targets[relative]] = BC.normalized_file_hash(target)
        raw[targets[relative]] = _raw_sha(target)
    manifest = {
        "benchmark_version": 2,
        "archived_at": datetime.now().isoformat(timespec="seconds"),
        "role": "HISTORICAL_DEVELOPMENT",
        "note": ("Benchmark v2 congelado tal como estaba ANTES del refinamiento v3 (auditorias de ambiguedad D01-D20 y "
                 "P01-P12). Sus ensayos son DEVELOPMENT_TRIAL / DEVELOPMENT_VALIDATION y no se mezclan con el benchmark v3 "
                 "(FORMAL). No editar: cada archivo esta verificado por hash."),
        "source_paths": {targets[relative]: relative for relative in sources},
        "files": files,
        "raw_sha256": raw,
    }
    _write_json(manifest_path, manifest)
    return manifest


# ---------------------------------------------------------------------------------------------
# 2-3. Catalogo v3 + profiles/variants
# ---------------------------------------------------------------------------------------------

def build_catalog(previous: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog = copy.deepcopy(previous)
    catalog["benchmark_version"] = 3
    catalog["methodology_note"] = previous["methodology_note"] + (
        " Benchmark v3 (FORMAL): refinado ANTES de los ensayos formales para hacer explicito, sin cambiar el comportamiento "
        "evaluado, lo que los Oracles congelados ya exigian (criterio: alineacion especificacion-ground truth). El v2 queda "
        "archivado como historico DEVELOPMENT en data/experiment_benchmark/versions/benchmark_v2/.")
    log: list[dict[str, Any]] = []
    for case in catalog["cases"]:
        old = copy.deepcopy(case)
        case["benchmark_version"] = 3
        change = CHANGES.get(case["case_id"])
        if change:
            case["canonical_command"] = change["canonical"]
            case["variants"] = {vid: change[vid] for vid in ("V1", "V2", "V3")}
            if "variant_check" in change:
                case["variant_check"] = change["variant_check"]
            for requirement in case["command_requirements"]:
                if requirement["id"] in (change.get("requirements") or {}):
                    requirement["text"] = change["requirements"][requirement["id"]]
            if change.get("requirements_prepend"):
                case["command_requirements"] = list(change["requirements_prepend"]) + case["command_requirements"]
        if case["case_id"] in FUNCTION_NAMES:
            case["canonical_semantics"]["signature"]["functions"] = FUNCTION_NAMES[case["case_id"]]
        log.append({"case_id": case["case_id"], "old": old, "new": copy.deepcopy(case), "text_changed": bool(change)})
    return catalog, log


# ---------------------------------------------------------------------------------------------
# 4. Oracles: nueva version (metadata v3; D03 ademas semantic_expectations)
# ---------------------------------------------------------------------------------------------

_FUNCTIONAL_KEYS = ("roles", "preconditions", "test_sequence", "invariants", "cleanup", "evaluation", "runtime_support",
                    "runtime_requirements", "resource_expectations")


def pending_human_approval(case_id: str, previous: dict[str, Any], draft: dict[str, Any], validated_at: str) -> dict[str, Any]:
    """Bloque approval de la nueva version: validacion TECNICA registrada, aprobacion HUMANA pendiente.

    Estado DRAFT_REVIEWED (el schema prohibe approved_by en borrador): approved_by/approved_at/hash = null. La revision
    asistida de la version previa (contenido funcional identico) se traslada a ai_review. approval no forma parte del
    hash, asi que el hash de contenido no cambia; se registra en technical_validation.content_hash.
    """
    approval = dict(draft["approval"])
    approval.update({"status": S.STATUS_DRAFT_REVIEWED, "approved_by": None, "approved_at": None, "hash": None})
    review = (previous.get("approval") or {}).get("ai_review")
    if review:
        carried = dict(review)
        carried.update({"carried_from_version": previous["approval"]["version"], "v3_alignment_verified": True,
                        "v3_verified_at": validated_at,
                        "notes": list(review.get("notes") or []) + [
                            "Benchmark v3: contenido funcional identico al revisado; solo cambian source_definition y textos de "
                            "convenciones. Alineacion v3 verificada por scripts/build_benchmark_v3.py (32/32, 0 requisitos ocultos)."]})
        approval["ai_review"] = carried
    approval["technical_validation"] = {
        "status": "PASSED",
        "validated_by": "scripts/build_benchmark_v3.py (validacion automatica; no es una aprobacion humana)",
        "validated_at": validated_at,
        "content_hash": S.compute_oracle_hash(draft),
        "checks": ["schema valido", "claves funcionales identicas a la version previa",
                   "source_definition.canonical_case_hash = hash canonico v3", "alineacion 32/32 sin requisitos ocultos",
                   "96/96 variantes consistentes"],
    }
    approval["human_formal_approval"] = HUMAN_APPROVAL_PENDING
    return approval


def new_oracle_versions(cases: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    report = []
    for case_id in BC.CASE_IDS:
        current = S.load_oracle(ROOT, case_id)
        S.verify_integrity(current)
        case = cases[case_id]
        draft = S.new_version(current)
        if "source_definition" not in draft:
            # D03 (Oracle piloto de la Fase 3A) nunca tuvo source_definition: en v3 todos referencian su hash canonico.
            draft["source_definition"] = {
                "catalog": "data/experiment_cases/canonical_cases.json",
                "case_title": case["title"],
                "original_requirement": case["original_requirement"],
                "legacy_reference_intent": case.get("reference_intent"),
            }
        source = draft["source_definition"]
        source["benchmark_version"] = 3
        source["canonical_command"] = case["canonical_command"]
        source["canonical_case_hash"] = BC.case_hash(case)
        for convention in draft.get("experimental_conventions") or []:
            if convention.get("id") == "CMD-CANONICAL":
                convention["text"] = f"COMANDO CANONICO (benchmark v3): {case['canonical_command']}"
            if case_id == "D20" and convention.get("id") == "C-D20-DURATION":
                convention["text"] = D20_DURATION_TEXT
        scope = "BENCHMARK_V3_METADATA"
        if case_id == "D03":
            draft["semantic_expectations"]["accepted_intents"] = list(D03_ACCEPTED)
            draft["semantic_expectations"]["notes"] = D03_NOTE
            scope = "BENCHMARK_V3_METADATA + SEMANTIC_EXPECTATIONS"
        for key in _FUNCTIONAL_KEYS:  # garantia: comportamiento funcional identico
            if draft.get(key) != current.get(key):
                _fail(f"{case_id}: la clave funcional {key} cambiaria.")
        draft["approval"].update({
            "change_scope": scope,
            "benchmark_version": 3,
            "change_note": ("Nueva version para benchmark v3 (FORMAL): source_definition (comando y hash canonico v3) y textos "
                            "de convenciones; test_sequence, invariantes, tiempos, cleanup, roles y reglas identicos."
                            + (" D03: accepted_intents ampliado (simetria D04/D11)." if case_id == "D03" else "")),
            "decision": f"Decisiones humanas aprobadas {DECISION_DATE} (auditorias de ambiguedad D01-D20 y P01-P12).",
            "generated_by": "Claude (asistido) a partir de las decisiones aprobadas por el investigador",
        })
        draft["approval"] = pending_human_approval(case_id, current, draft, datetime.now().isoformat(timespec="seconds"))
        S.supersede_frozen(ROOT, draft)  # la aprobacion formal NO se hace aqui: es una accion humana explicita
        report.append({"case_id": case_id, "previous_version": current["approval"]["version"],
                       "new_version": draft["approval"]["version"], "previous_hash": current["approval"]["hash"],
                       "new_hash": draft["approval"]["technical_validation"]["content_hash"], "scope": scope})
    return report


# ---------------------------------------------------------------------------------------------
# 6. Diseno experimental
# ---------------------------------------------------------------------------------------------

def update_design() -> None:
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    design["benchmark_version"] = 3
    design["description"] = design["description"].replace("benchmark v2", "benchmark v3")
    design["benchmark_history"] = {
        "DEVELOPMENT": {"benchmark_version": 2, "status": "HISTORICAL",
                        "archive": "data/experiment_benchmark/versions/benchmark_v2/",
                        "note": "Ensayos de desarrollo/validacion ejecutados con v2: se conservan y nunca se mezclan con FORMAL."},
        "FORMAL": {"benchmark_version": 3, "status": "CURRENT",
                   "changelog": "docs/benchmark_v3_changelog.md",
                   "note": "Refinado antes de cualquier ensayo FORMAL; comportamiento evaluado identico al de v2."},
    }
    text = json.dumps(design, indent=2, ensure_ascii=False)
    text = text.replace("de la variante V1/V2/V3 del benchmark v2", "de la variante V1/V2/V3 del benchmark vigente (v3)")
    DESIGN.write_text(text + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# 7. Changelog
# ---------------------------------------------------------------------------------------------

def write_changelog(log: list[dict[str, Any]], oracles: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    by_case = {entry["case_id"]: entry for entry in oracles}
    lines = [
        "# Benchmark v2 -> v3: registro de cambios",
        "",
        f"Generado por `scripts/build_benchmark_v3.py` el {datetime.now().isoformat(timespec='seconds')}.",
        "",
        "**El refinamiento se hizo ANTES de cualquier ensayo FORMAL.** El benchmark v2 queda archivado byte a byte en",
        "`data/experiment_benchmark/versions/benchmark_v2/` (manifest con hashes) como historico DEVELOPMENT; sus ensayos",
        "no se mezclan con los del v3.",
        "",
        "Criterio unico: alineacion entre la especificacion textual y el ground truth (Oracles congelados), segun las",
        "auditorias de ambiguedad D01-D20 (60 variantes) y P01-P12 (36 variantes) y las decisiones humanas aprobadas el",
        f"{DECISION_DATE}. Ningun cambio se justifica por el resultado de un modelo.",
        "",
        "- Comportamiento funcional cambiado: **NO** en los 32 casos.",
        "- Comportamiento de los Oracles cambiado: **NO** (test_sequence, invariantes, tiempos, cleanup, roles y reglas",
        "  identicos). Excepcion registrada: `semantic_expectations` de **D03** (cambio semantico, no funcional).",
        "- Los 32 casos pasan a `benchmark_version = 3`; como ese campo forma parte del hash canonico, los 32 Oracles",
        "  reciben una version nueva con `source_definition` actualizada (16 con cambio de texto, 16 solo metadata).",
        "",
        "## Decisiones humanas aplicadas",
        "",
        "1. D03: texto sin cambios; acepta `INT_MOTOR_START_STOP` e `INT_MOTOR_LATCH` (simetria funcional con D04/D11).",
        "2. Emergencia (D05, P07): senal logica de simulacion; no representa hardware; no se crea `I_Emergency` en el mapa fisico.",
        "3. Modo: convencion global `MODE_AUTO = TRUE` -> Automatico, `FALSE` -> Manual (un unico selector logico).",
        "4. Senales del arnes de prueba documentadas en Methods (`docs/experimental_interface_v3.md`), no en los comandos.",
        "5. Polaridad: entradas activas en ON, incluido Stop.",
        "6. D03/D04/D11 se conservan; forman una familia funcional para analisis secundario.",
        "7. P07 y P11: comandos completados; los Oracles no se relajan.",
        "8. P03: 0-100 % (benchmark/Oracle) es la fuente v3; la configuracion legacy 10-90 % queda pendiente de alineacion.",
        "9. D14: evaluacion formal con mapa de simulacion con recursos suficientes; el banco fisico no se modifica.",
        "",
        "## Cambios por caso",
        "",
    ]
    for entry in log:
        case_id, old, new = entry["case_id"], entry["old"], entry["new"]
        oracle = by_case[case_id]
        if not entry["text_changed"] and case_id not in FUNCTION_NAMES and case_id != "D03":
            continue
        lines += [f"### {case_id} - {new['title']}", ""]
        if entry["text_changed"]:
            lines += ["| | v2 | v3 |", "|---|---|---|", f"| Canonico | {old['canonical_command']} | {new['canonical_command']} |"]
            for vid in ("V1", "V2", "V3"):
                lines.append(f"| {vid} | {old['variants'][vid]} | {new['variants'][vid]} |")
            lines += ["", f"- **Ambiguedad eliminada:** {CHANGES[case_id]['ambiguity']}"]
        else:
            lines.append("- **Texto:** sin cambios.")
        if case_id in FUNCTION_NAMES:
            lines.append(f"- **Nombres funcionales (metadata):** {old['canonical_semantics']['signature']['functions']} -> "
                         f"{new['canonical_semantics']['signature']['functions']} (alineados con el Oracle; no puntuan).")
        if case_id == "D03":
            lines.append(f"- **semantic_expectations:** accepted_intents `['INT_MOTOR_START_STOP']` -> `{D03_ACCEPTED}` "
                         "(cambio semantico, no funcional).")
        lines += [
            "- **Comportamiento funcional cambiado:** NO.",
            f"- **Oracle:** v{oracle['previous_version']} -> v{oracle['new_version']} ({oracle['scope']}); comportamiento "
            "identico" + (" salvo semantic_expectations." if case_id == "D03" else "."),
            "- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado "
            "ya evaluaba).",
            "",
        ]
    unchanged = [e["case_id"] for e in log if not e["text_changed"] and e["case_id"] not in FUNCTION_NAMES and e["case_id"] != "D03"]
    lines += ["## Casos sin cambios de texto (solo benchmark_version y Oracle metadata)", "", ", ".join(unchanged), "",
              "## Oracles re-versionados", "",
              "Estado de las versiones v3: `DRAFT_REVIEWED` con `technical_validation = PASSED` y",
              "`human_formal_approval = PENDING` (`approved_by = null`). Este script nunca firma una aprobacion humana; la",
              "aprobacion formal la realiza el investigador de forma explicita (ventana REVISION DE ORACLES). Hasta entonces",
              "los guardas FORMAL (`oracles_32_frozen`, `oracles_frozen_hash`) bloquean los ensayos formales.", "",
              "| Caso | Version | Alcance | Hash de contenido |", "|---|---|---|---|"]
    for entry in oracles:
        lines.append(f"| {entry['case_id']} | v{entry['previous_version']} -> v{entry['new_version']} | {entry['scope']} | "
                     f"`{entry['new_hash'][:16]}` |")
    lines += ["", f"Archivo v2: {len(manifest['files'])} archivos verificados por hash.", ""]
    CHANGELOG.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# Main + verificacion
# ---------------------------------------------------------------------------------------------

def main() -> None:
    previous = json.loads(CATALOG.read_text(encoding="utf-8"))
    manifest = archive_v2()
    catalog, log = build_catalog(previous)
    _write_json(CATALOG, catalog)
    BC.sync_profiles(ROOT)
    BC.sync_variants_file(ROOT)
    cases = {case["case_id"]: case for case in catalog["cases"]}
    consistency = BC.build_variant_consistency_report(ROOT)
    if consistency["consistent_variants"] != 96:
        _fail(f"variantes inconsistentes: {consistency['cases_with_errors']}")
    oracles = new_oracle_versions(cases)
    BC.write_variant_consistency_report(ROOT)
    validation = OR.build_validation_report(ROOT)
    OR.write_validation_report(ROOT, validation)
    OR.write_summary_markdown(ROOT)
    OR.write_capability_gaps_report(ROOT)
    BC.write_command_catalog_markdown(ROOT)
    update_design()
    write_changelog(log, oracles, manifest)
    summary = validation["summary"]
    print(json.dumps({"consistent_variants": consistency["consistent_variants"], "oracles_aligned": summary["oracles_aligned"],
                      "hidden_oracle_requirements": summary["hidden_oracle_requirements"],
                      "benchmark_inconsistencies": summary["benchmark_inconsistencies"],
                      "oracles": [(o["case_id"], o["new_version"]) for o in oracles]}, ensure_ascii=False))
    if summary["oracles_aligned"] != 32 or summary["hidden_oracle_requirements"] or summary["benchmark_inconsistencies"]:
        _fail(f"validacion v3 incompleta: {summary}")


if __name__ == "__main__":
    main()
