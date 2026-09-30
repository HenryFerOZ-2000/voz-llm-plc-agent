"""
Benchmark experimental v2: catalogo canonico unico de casos D01-D20 / P01-P12.

Fuente de verdad FUNCIONAL: data/experiment_cases/canonical_cases.json. Cada caso define el
requisito original, el comando canonico, su firma funcional, los requisitos del comando (con la
evidencia que los verifica en el Oracle), la preparacion del test harness (que NO es requisito del
comando) y las variantes V1/V2/V3.

profiles.json y experiment_variants.json se SINCRONIZAN desde este catalogo (sync_*), y los
Oracles se validan contra el (canonical_alignment): un Oracle no puede exigir comportamiento que el
comando no pidio (extra_oracle_requirements) ni omitir lo que pidio (missing_oracle_requirements).
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from utils import load_json_file

CATALOG_RELATIVE_PATH = Path("data") / "experiment_cases" / "canonical_cases.json"
VARIANT_REPORT_RELATIVE_PATH = Path("data") / "variant_consistency_report.json"
CASE_IDS = [f"D{i:02d}" for i in range(1, 21)] + [f"P{i:02d}" for i in range(1, 13)]
VARIANT_IDS = ("V1", "V2", "V3")

_PHYSICAL_ADDRESS = re.compile(r"%\s*[IQM]\s*[XBWD]?\s*\d", re.IGNORECASE)
_TAG_NAME = re.compile(r"\b[IQM]_[A-Za-z]\w*")
_NUMBER_WORDS = {
    "cero": 0, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "quinto": 5, "sesenta": 60, "noventa": 90, "cien": 100, "ciento": 100, "noventa y cinco": 95,
}


# ---------------------------------------------------------------------------------------------
# Carga y hashes
# ---------------------------------------------------------------------------------------------

def catalog_path(project_root: Path) -> Path:
    return project_root / CATALOG_RELATIVE_PATH


def load_catalog(project_root: Path) -> dict[str, Any]:
    path = catalog_path(project_root)
    if not path.exists():
        return {}
    payload = load_json_file(path)
    return payload if isinstance(payload, dict) else {}


def cases_by_id(project_root: Path) -> dict[str, dict[str, Any]]:
    return {case["case_id"]: case for case in load_catalog(project_root).get("cases", [])}


def get_case(project_root: Path, case_id: str) -> dict[str, Any] | None:
    return cases_by_id(project_root).get(case_id)


def _sha256(payload: Any) -> str:
    text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def case_hash(case: dict[str, Any]) -> str:
    """Hash de la definicion funcional del caso (sin las variantes, que tienen su propio hash)."""
    return _sha256({key: case.get(key) for key in (
        "case_id", "benchmark_version", "original_requirement", "canonical_command", "canonical_semantics",
        "command_requirements", "test_harness_setup")})


def normalized_file_hash(path: Path) -> str:
    """SHA-256 del contenido con saltos de linea normalizados a LF: identico en Windows (autocrlf) y en
    cualquier otro checkout. Se usa para verificar el archivo historico del benchmark."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def variant_hash(text: str) -> str:
    return _sha256(str(text).strip())


def variants_for_case(project_root: Path, case_id: str) -> list[dict[str, str]]:
    case = get_case(project_root, case_id)
    if not case:
        return []
    return [{"variant": vid, "command": case["variants"][vid]} for vid in VARIANT_IDS if vid in case.get("variants", {})]


def trial_benchmark_reference(project_root: Path, case_id: str, variant_id: str) -> dict[str, Any]:
    """Lo que cada ensayo guarda para saber exactamente que comando se uso (trial.json)."""
    case = get_case(project_root, case_id)
    if not case:
        return {"benchmark_version": None, "canonical_case_hash": None, "variant_id": variant_id, "variant_hash": None}
    command = case.get("variants", {}).get(variant_id)
    return {
        "benchmark_version": case.get("benchmark_version"),
        "canonical_case_hash": case_hash(case),
        "variant_id": variant_id,
        "variant_hash": variant_hash(command) if command else None,
        "canonical_command": case.get("canonical_command"),
    }


# ---------------------------------------------------------------------------------------------
# Equivalencia de variantes
# ---------------------------------------------------------------------------------------------

def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def extract_numbers(text: str) -> set[int]:
    normalized = normalize(text).replace("por ciento", " % ")  # 'por ciento' es la unidad, no el numero 100
    numbers = {int(value) for value in re.findall(r"\d+", normalized)}
    if "noventa y cinco" in normalized:
        numbers.add(95)
        normalized = normalized.replace("noventa y cinco", " ")
    for word, value in _NUMBER_WORDS.items():
        if " " not in word and re.search(rf"\b{word}\b", normalized):
            numbers.add(value)
    return numbers


def check_text(case: dict[str, Any], text: str) -> dict[str, Any]:
    check = case.get("variant_check") or {}
    normalized = normalize(text)
    missing_concepts = [pattern for pattern in check.get("required_concepts", []) if not re.search(pattern, normalized)]
    numbers = extract_numbers(text)
    expected = set(check.get("numbers", []))
    errors, warnings = [], []
    if missing_concepts:
        errors.append(f"Faltan conceptos obligatorios: {missing_concepts}")
    if numbers != expected:
        errors.append(f"Valores numericos {sorted(numbers)} distintos de los canonicos {sorted(expected)}")
    if _PHYSICAL_ADDRESS.search(text):
        errors.append("Contiene una direccion fisica explicita.")
    if _TAG_NAME.search(text):
        warnings.append("Contiene nombres de tag (I_/Q_...): no aptos para voz.")
    return {"missing_concepts": missing_concepts, "numbers": sorted(numbers), "errors": errors, "warnings": warnings}


def variant_consistency(case: dict[str, Any]) -> dict[str, Any]:
    canonical = check_text(case, case["canonical_command"])
    entry: dict[str, Any] = {
        "case_id": case["case_id"],
        "canonical_command": case["canonical_command"],
        "canonical_signature": case["canonical_semantics"]["signature"],
        "canonical_check": canonical,
        "errors": [f"canonico: {e}" for e in canonical["errors"]],
        "warnings": [f"canonico: {w}" for w in canonical["warnings"]],
    }
    consistent = 0
    variants = case.get("variants", {})
    for vid in VARIANT_IDS:
        text = variants.get(vid)
        if text is None:
            entry["errors"].append(f"{vid} no existe.")
            continue
        result = check_text(case, text)
        entry[vid] = {"command": text, "variant_hash": variant_hash(text), **result, "consistent": not result["errors"]}
        entry["errors"] += [f"{vid}: {e}" for e in result["errors"]]
        entry["warnings"] += [f"{vid}: {w}" for w in result["warnings"]]
        consistent += int(not result["errors"])
    same_numbers = all(entry.get(v, {}).get("numbers") == canonical["numbers"] for v in VARIANT_IDS)
    same_concepts = all(not entry.get(v, {}).get("missing_concepts") for v in VARIANT_IDS)
    distinct = len({variants.get(v) for v in VARIANT_IDS}) == len(VARIANT_IDS)
    if not distinct:
        entry["errors"].append("Hay variantes con el mismo texto.")
    entry.update({
        "same_required_roles": same_concepts,
        "same_numeric_values": same_numbers,
        "same_constraints": same_concepts,
        "same_expected_behavior": same_concepts and same_numbers and not entry["errors"],
        "consistent_variants": consistent,
        "method": "Comprobacion lexica: conceptos obligatorios (roles/restricciones) y valores numericos identicos al comando "
                  "canonico; la equivalencia semantica fina la revisa el investigador.",
    })
    return entry


def build_variant_consistency_report(project_root: Path) -> dict[str, Any]:
    catalog = load_catalog(project_root)
    entries = [variant_consistency(case) for case in catalog.get("cases", [])]
    total = sum(len(case.get("variants", {})) for case in catalog.get("cases", []))
    return {
        "benchmark_version": catalog.get("benchmark_version"),
        "total_cases": len(entries),
        "total_variants": total,
        "consistent_variants": sum(e["consistent_variants"] for e in entries),
        "cases_with_errors": [e["case_id"] for e in entries if e["errors"]],
        "cases": entries,
    }


def write_variant_consistency_report(project_root: Path) -> Path:
    path = project_root / VARIANT_REPORT_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_variant_consistency_report(project_root), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------
# Alineacion Oracle <-> comando canonico
# ---------------------------------------------------------------------------------------------

def _evaluative_ids(oracle: dict[str, Any]) -> list[str]:
    """Pasos de test con expectativas y todas las invariantes: lo que el Oracle EXIGE."""
    ids = [step["id"] for step in oracle.get("test_sequence") or []
           if step.get("expect") or step.get("expect_timeline") or step.get("measure_transition")]
    return ids + [invariant["id"] for invariant in oracle.get("invariants") or []]


def canonical_alignment(case: dict[str, Any], oracle: dict[str, Any]) -> dict[str, Any]:
    all_ids = {step["id"] for section in ("preconditions", "test_sequence", "cleanup") for step in oracle.get(section) or []}
    all_ids |= {invariant["id"] for invariant in oracle.get("invariants") or []}
    evidence = set()
    covered, missing = [], []
    for requirement in case.get("command_requirements", []):
        ids = requirement.get("oracle_evidence") or []
        absent = [i for i in ids if i not in all_ids]
        if not ids or absent:
            missing.append({"requirement": requirement["id"], "text": requirement["text"], "absent_evidence": absent})
        else:
            covered.append({"requirement": requirement["id"], "text": requirement["text"], "evidence": ids})
        evidence |= set(ids)
    extra = [{"oracle_item": item, "reason": "El Oracle lo exige pero ningun requisito del comando lo justifica."}
             for item in _evaluative_ids(oracle) if item not in evidence]

    harness = set(case["canonical_semantics"].get("harness_roles", []))
    canonical_roles = set(case["canonical_semantics"]["roles"])
    oracle_roles = {name for name, role in (oracle.get("roles") or {}).items() if name not in harness}
    for role in sorted(oracle_roles - canonical_roles):
        extra.append({"oracle_item": f"role:{role}", "reason": "Rol del Oracle que el comando no menciona."})
    for role in sorted(canonical_roles - oracle_roles):
        missing.append({"requirement": f"role:{role}", "text": "Rol del comando que el Oracle no usa.", "absent_evidence": []})

    nominal = {step["measure_transition"]["nominal_ms"] for step in oracle.get("test_sequence") or [] if step.get("measure_transition")}
    for name, seconds in (case["canonical_semantics"]["signature"].get("times") or {}).items():
        if int(seconds * 1000) not in nominal:
            missing.append({"requirement": f"time:{name}", "text": f"{seconds} s no se mide en el Oracle.", "absent_evidence": []})
    return {"command_requirements_covered": covered, "extra_oracle_requirements": extra, "missing_oracle_requirements": missing}


# ---------------------------------------------------------------------------------------------
# Sincronizacion y consistencia de los archivos derivados
# ---------------------------------------------------------------------------------------------

def profile_text(case: dict[str, Any]) -> dict[str, Any]:
    return {"name": f"{case['case_id']} - {case['title']}", "description": case["canonical_command"],
            "reference_intent": case.get("reference_intent")}


def sync_profiles(project_root: Path) -> Path:
    """Nombre/descripcion/intent de profiles.json desde el catalogo. allowed_variables se conserva como
    metadata historica (el sistema experimental v2 NO lo usa como restriccion)."""
    path = project_root / "data" / "plc_maps" / "profiles.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    catalog = cases_by_id(project_root)
    for profile in payload.get("profiles", []):
        case = catalog.get(profile.get("case_id"))
        if case:
            profile.update(profile_text(case))
            profile["benchmark_version"] = case.get("benchmark_version")
            profile["canonical_source"] = str(CATALOG_RELATIVE_PATH).replace("\\", "/")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def sync_variants_file(project_root: Path) -> Path:
    """experiment_variants.json (formato legacy, lo siguen leyendo herramientas antiguas) desde el catalogo."""
    catalog = load_catalog(project_root)
    payload = {
        "schema_version": 2,
        "benchmark_version": catalog.get("benchmark_version"),
        "generated_from": str(CATALOG_RELATIVE_PATH).replace("\\", "/"),
        "note": "Archivo DERIVADO: no editar a mano; la fuente de verdad es el catalogo canonico.",
        "variants": {case["case_id"]: [{"variant": vid, "command": case["variants"][vid]} for vid in VARIANT_IDS]
                     for case in catalog.get("cases", [])},
    }
    path = project_root / "data" / "plc_maps" / "experiment_variants.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def benchmark_inconsistencies(project_root: Path, oracles: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Discrepancias entre catalogo y perfiles, variantes y Oracles (objetivo: ninguna)."""
    issues: list[dict[str, Any]] = []
    catalog = cases_by_id(project_root)
    profiles_path = project_root / "data" / "plc_maps" / "profiles.json"
    profiles = {p["case_id"]: p for p in json.loads(profiles_path.read_text(encoding="utf-8")).get("profiles", [])} \
        if profiles_path.exists() else {}
    variants_path = project_root / "data" / "plc_maps" / "experiment_variants.json"
    variants = json.loads(variants_path.read_text(encoding="utf-8")).get("variants", {}) if variants_path.exists() else {}
    for case_id in CASE_IDS:
        case = catalog.get(case_id)
        if case is None:
            issues.append({"case_id": case_id, "source": "catalog", "issue": "Caso ausente del catalogo canonico."})
            continue
        profile = profiles.get(case_id)
        expected = profile_text(case)
        if profile is None or any(profile.get(k) != v for k, v in expected.items()):
            issues.append({"case_id": case_id, "source": "profiles.json", "issue": "Nombre/descripcion/intent distintos del catalogo."})
        file_variants = {e.get("variant"): e.get("command") for e in variants.get(case_id, [])}
        if file_variants != dict(case["variants"]):
            issues.append({"case_id": case_id, "source": "experiment_variants.json", "issue": "Variantes distintas del catalogo."})
        oracle = (oracles or {}).get(case_id)
        if oracle is not None:
            source = oracle.get("source_definition") or {}
            frozen_v1 = (oracle.get("approval") or {}).get("status") in ("FROZEN", "APPROVED") and not source
            if not frozen_v1 and source.get("canonical_case_hash") != case_hash(case):
                issues.append({"case_id": case_id, "source": "oracle", "issue": "El Oracle no referencia el hash canonico vigente."})
    return issues


# ---------------------------------------------------------------------------------------------
# Documentacion: docs/experiment_command_catalog.md
# ---------------------------------------------------------------------------------------------

COMMAND_CATALOG_DOC = Path("docs") / "experiment_command_catalog.md"


def build_command_catalog_markdown(project_root: Path) -> str:
    catalog = load_catalog(project_root)
    cases = catalog.get("cases", [])
    lines = [
        f"# Catalogo de comandos experimentales (benchmark v{catalog.get('benchmark_version')})",
        "",
        f"Fuente de verdad: `{str(CATALOG_RELATIVE_PATH).replace(chr(92), '/')}`. `profiles.json` y `experiment_variants.json` se "
        "generan desde este catalogo; los Oracles se validan contra el.",
        "",
        "> **Nota metodologica.** " + str(catalog.get("methodology_note", "")),
        "",
        "Separacion de responsabilidades: los **requisitos del comando** (lo que el usuario pide y el PLC debe cumplir) estan separados "
        "de la **preparacion del test harness** (acciones del runner para empezar la prueba en un estado reproducible, que no son "
        "requisito del comando).",
        "",
        "| ID | Objetivo original | Comando canonico | Complejidad |",
        "|---|---|---|---|",
    ]
    for case in cases:
        lines.append(f"| {case['case_id']} | {case['original_requirement']} | {case['canonical_command']} | {case['complexity']} |")
    lines.append("")
    for case in cases:
        lines += [f"## {case['case_id']} - {case['title']}", "",
                  f"**Comando canonico:** {case['canonical_command']}", ""]
        lines += [f"- **{vid}:** {case['variants'][vid]}" for vid in VARIANT_IDS]
        lines += ["", "Requisitos del comando:"]
        lines += [f"- {r['id']}: {r['text']}" for r in case.get("command_requirements", [])]
        if case.get("test_harness_setup"):
            lines += ["", "Preparacion del test harness (no es requisito del comando):"]
            lines += [f"- {item}" for item in case["test_harness_setup"]]
        if case["canonical_semantics"].get("clarifications"):
            lines += ["", "Aclaraciones:"]
            lines += [f"- {item}" for item in case["canonical_semantics"]["clarifications"]]
        lines.append("")
    return "\n".join(lines)


def write_command_catalog_markdown(project_root: Path) -> Path:
    path = project_root / COMMAND_CATALOG_DOC
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_command_catalog_markdown(project_root), encoding="utf-8")
    return path
