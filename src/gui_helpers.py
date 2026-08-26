from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import Any

from utils import iter_io_map_entries, load_json_file


ALLOWED_IO_CLASSES = ["input", "output", "internal", "timer", "counter", "auxiliary"]
ALLOWED_IO_TYPES = ["BOOL", "INT", "TON", "TP", "CTU", "R_TRIG", "F_TRIG"]
LOCATION_PATTERN = re.compile(r"^%[IQM][A-Z]*\d+(?:\.\d+)?$", re.IGNORECASE)
IO_TREE_COLUMNS = ("name", "class", "type", "location", "initial_value", "description")
PLATFORM_UI_TO_TARGETS = {
    "Siemens + OpenPLC": ["SIEMENS_SCL_V18", "OPENPLC_ST"],
    "Siemens TIA V18": ["SIEMENS_SCL_V18"],
    "OpenPLC": ["OPENPLC_ST"],
    "CODESYS": ["CODESYS_ST"],
    "Ambas": ["OPENPLC_ST", "CODESYS_ST"],
    "Todas": ["SIEMENS_SCL_V18", "OPENPLC_ST", "CODESYS_ST"]
}
PARSER_UI_TO_MODE = {
    "Reglas": "rule_based",
    "LLM": "llm",
    "Hibrido": "hybrid"
}
DEFAULT_NAMING_CONVENTION = {
    "inputs": "I_",
    "outputs": "Q_",
    "internal_memory": "M_",
    "timers": "T_",
    "counters": "C_",
    "auxiliary": "R_"
}
STATUS_COLORS = {
    "Listo": {"fg": "#DDEFE1", "text": "#184E2A"},
    "Escuchando": {"fg": "#FFF1C9", "text": "#7A5100"},
    "Transcribiendo": {"fg": "#D9F0FF", "text": "#0D4F78"},
    "Procesando": {"fg": "#E1DDF8", "text": "#47336F"},
    "Error": {"fg": "#FFD8D8", "text": "#8A1F1F"}
}


def format_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def timestamp_for_console() -> str:
    return datetime.now().strftime("%H:%M:%S")


def console_message(message: str) -> str:
    return f"[{timestamp_for_console()}] {message}"


def get_status_colors(status: str) -> dict[str, str]:
    return STATUS_COLORS.get(status, STATUS_COLORS["Listo"])


def normalize_platform_targets(selection: str) -> list[str]:
    # OpenPLC y CODESYS quedan aislados de la GUI (ver docs/08_decisiones_tecnicas.md);
    # el mapa se conserva completo para una reintegracion futura sin perder codigo.
    return PLATFORM_UI_TO_TARGETS.get(selection, ["SIEMENS_SCL_V18"])


def platform_label(target_platform: str) -> str:
    if target_platform in {"OPENPLC_ST", "OpenPLC"}:
        return "OpenPLC"
    if target_platform in {"CODESYS_ST", "CODESYS"}:
        return "CODESYS"
    if target_platform in {"SIEMENS_SCL_V18", "SIEMENS", "TIA_V18"}:
        return "Siemens TIA V18"
    return target_platform


def normalize_parser_mode_selection(selection: str) -> str:
    return PARSER_UI_TO_MODE.get(selection, "rule_based")


def load_io_map_variables(io_map_path: Path) -> list[dict[str, str]]:
    io_map = load_json_file(io_map_path)
    entries: list[dict[str, str]] = []

    for entry in iter_io_map_entries(io_map):
        entries.append(normalize_variable_entry(entry))

    return entries


def normalize_variable_entry(entry: dict[str, Any]) -> dict[str, str]:
    return {
        "name": str(entry.get("name", "")).strip(),
        "class": str(entry.get("class", "internal")).strip().lower(),
        "type": str(entry.get("type", "BOOL")).strip().upper(),
        "location": str(entry.get("location", "")).strip(),
        "initial_value": str(entry.get("initial_value", "")).strip(),
        "description": str(entry.get("description", "")).strip()
    }


def validate_io_map_variables(variables: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    seen_names: set[str] = set()

    for index, raw_entry in enumerate(variables, start=1):
        entry = normalize_variable_entry(raw_entry)
        name = entry["name"]
        var_class = entry["class"]
        var_type = entry["type"]
        location = entry["location"]

        if not name:
            errors.append(f"Fila {index}: el campo name es obligatorio.")
            continue

        if not re.match(r"^[IQMTCFR]_[A-Za-z0-9_]+$", name):
            errors.append(f"Fila {index}: el nombre {name} no cumple la convención autorizada.")

        if name in seen_names:
            errors.append(f"Fila {index}: el nombre {name} está repetido.")
        seen_names.add(name)

        if var_class not in ALLOWED_IO_CLASSES:
            errors.append(f"Fila {index}: la clase {var_class} no está permitida.")

        if var_type not in ALLOWED_IO_TYPES:
            errors.append(f"Fila {index}: el tipo {var_type} no está permitido.")

        if location:
            if not LOCATION_PATTERN.match(location):
                errors.append(f"Fila {index}: la ubicación {location} no tiene formato válido.")
            if name.startswith("I_") and not location.upper().startswith("%IX"):
                errors.append(f"Fila {index}: las entradas deben usar ubicaciones %IX.")
            if name.startswith("Q_") and not location.upper().startswith("%QX"):
                errors.append(f"Fila {index}: las salidas deben usar ubicaciones %QX.")
        elif var_class in {"input", "output"}:
            errors.append(f"Fila {index}: la variable {name} requiere una ubicación física.")

        if var_type in {"TON", "TP", "CTU", "R_TRIG", "F_TRIG"} and entry["initial_value"]:
            errors.append(f"Fila {index}: el tipo {var_type} no debe tener initial_value.")

    return errors


def save_io_map_variables(io_map_path: Path, variables: list[dict[str, str]]) -> None:
    existing_payload = load_json_file(io_map_path)
    payload = {
        "naming_convention": existing_payload.get("naming_convention", DEFAULT_NAMING_CONVENTION),
        "variables": [normalize_variable_entry(entry) for entry in variables]
    }
    io_map_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_rows_into_treeview(
    treeview: ttk.Treeview,
    rows: list[dict[str, Any]],
    columns: tuple[str, ...]
) -> None:
    treeview.delete(*treeview.get_children())
    for row in rows:
        values = [str(row.get(column, "")) for column in columns]
        treeview.insert("", "end", values=values)


def treeview_rows(treeview: ttk.Treeview, columns: tuple[str, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item_id in treeview.get_children():
        values = treeview.item(item_id, "values")
        rows.append({column: str(values[index]).strip() for index, column in enumerate(columns)})
    return rows


def append_history_row(
    treeview: ttk.Treeview,
    timestamp: str,
    command_text: str,
    intent_id: str,
    platform: str,
    is_valid: bool
) -> str:
    return treeview.insert(
        "",
        0,
        values=(
            timestamp,
            command_text,
            intent_id,
            platform_label(platform),
            "Válido" if is_valid else "Inválido"
        )
    )
