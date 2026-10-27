"""Guided editor for the variable kinds supported by the PLC generation pipeline."""
from __future__ import annotations

import math
import re
import tkinter as tk
from typing import Any

import customtkinter as ctk

from gui_helpers import ALLOWED_SAFETY_LEVELS, normalize_variable_entry
from plc_maps.map_validator import validate_plc_variable_map
from analog_config_editor import AnalogConfigurationPanel
from process_signal_editor import ProcessSignalConfigurationPanel

# label: (storage class, allowed types, name prefix, canonical address pattern, example)
KINDS = {
    "Entrada digital (DI)": ("input", ["BOOL"], "I_", r"%IX\d+\.[0-7]", "I16.0"),
    "Salida digital (DO)": ("output", ["BOOL"], "Q_", r"%QX\d+\.[0-7]", "Q8.0"),
    "Entrada analógica (AI)": ("input", ["INT"], "AI_", r"%IW\d+", "IW0"),
    "Salida analógica (AO)": ("output", ["INT"], "AO_", r"%QW\d+", "QW0"),
    "Memoria interna": ("internal", ["BOOL", "INT"], "M_", r"%M(?:X\d+\.[0-7]|W\d+)", ""),
    "Señal de proceso en DB": ("internal", ["REAL"], "M_", "", ""),
    "Temporizador": ("timer", ["TON", "TP"], "T_", "", ""),
    "Contador": ("counter", ["CTU"], "C_", "", ""),
    "Detector de flanco": ("auxiliary", ["R_TRIG", "F_TRIG"], "R_", "", ""),
}


def variable_kind(data: dict[str, Any]) -> str:
    for label, (cls, types, _prefix, _pattern, _example) in KINDS.items():
        if data.get("class") == cls and data.get("type") in types:
            return label
    return "Entrada digital (DI)"


def canonical_address(raw: str) -> str:
    address = raw.strip().upper()
    if not address:
        return ""
    if not address.startswith("%"):
        address = "%" + address
    return re.sub(r"^%([IQM])(\d+\.[0-7])$", r"%\1X\2", address)


class VariableEditorDialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, variable_data: dict[str, Any] | None = None,
                 *, other_variables: list[dict[str, Any]] | None = None) -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("650x650")
        self.minsize(590, 480)
        self.transient(parent)
        self.grab_set()
        self.original = dict(variable_data or {})
        self.other_variables = list(other_variables or [])
        data = self.original
        self.result: dict[str, Any] | None = None
        kind = variable_kind(data)
        cls, types, prefix, _, _ = KINDS[kind]
        self.kind_var = tk.StringVar(self, value=kind)
        self.class_var = tk.StringVar(self, value=data.get("class", cls))
        self.name_var = tk.StringVar(self, value=data.get("name", prefix))
        self.type_var = tk.StringVar(self, value=data.get("type", types[0]))
        self.location_var = tk.StringVar(self, value=data.get("location", ""))
        default_initial = "FALSE" if self.type_var.get() == "BOOL" else "0" if self.type_var.get() == "INT" else ""
        self.initial_value_var = tk.StringVar(self, value=data.get("initial_value", default_initial))
        self.description_var = tk.StringVar(self, value=data.get("description", ""))
        aliases = data.get("aliases", [])
        self.aliases_var = tk.StringVar(self, value=", ".join(aliases) if isinstance(aliases, list) else aliases)
        self.semantic_role_var = tk.StringVar(self, value=data.get("semantic_role", ""))
        self.llm_allowed_var = tk.BooleanVar(self, value=data.get("llm_allowed", True))
        self.safety_level_var = tk.StringVar(self, value=data.get("safety_level", "normal"))
        self.unit_var = tk.StringVar(self, value=data.get("unit", "") or "")
        self.min_var = tk.StringVar(self, value="" if data.get("min") is None else str(data["min"]))
        self.max_var = tk.StringVar(self, value="" if data.get("max") is None else str(data["max"]))
        self.comments_var = tk.StringVar(self, value=data.get("comments", ""))
        self.existing_state = data.get("state", "ASSIGNED")
        self.error_var = tk.StringVar(self)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=20, weight="bold")).grid(
            row=0, column=0, padx=20, pady=(16, 8), sticky="w")
        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=1, column=0, padx=16, sticky="nsew")
        basic = ctk.CTkScrollableFrame(self.tabs.add("Variable"), fg_color="transparent")
        advanced = ctk.CTkScrollableFrame(self.tabs.add("Avanzado"), fg_color="transparent")
        for frame in (basic, advanced):
            frame.pack(fill="both", expand=True)
            frame.grid_columnconfigure(1, weight=1)
        self.analog_panel = AnalogConfigurationPanel(self.tabs.add("Analógica"), data)
        self.analog_panel.pack(fill="both", expand=True)
        self.process_panel = ProcessSignalConfigurationPanel(self.tabs.add("Proceso DB"), data)
        self.process_panel.pack(fill="both", expand=True)

        def row(frame, index, label, widget):
            ctk.CTkLabel(frame, text=label).grid(row=index, column=0, padx=(8, 14), pady=8, sticky="w")
            widget.grid(row=index, column=1, padx=(0, 8), pady=8, sticky="ew")

        row(basic, 0, "Clase de variable", ctk.CTkOptionMenu(
            basic, variable=self.kind_var, values=list(KINDS), command=self._on_kind_changed))
        row(basic, 1, "Nombre", ctk.CTkEntry(basic, textvariable=self.name_var))
        self.type_menu = ctk.CTkOptionMenu(basic, variable=self.type_var, values=types, command=self._on_type_changed)
        row(basic, 2, "Tipo de dato", self.type_menu)
        self.location_entry = ctk.CTkEntry(basic, textvariable=self.location_var)
        row(basic, 3, "Dirección", self.location_entry)
        self.address_hint = ctk.CTkLabel(basic, text="", wraplength=510, justify="left", text_color="#556272")
        self.address_hint.grid(row=4, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="w")
        self.initial_entry = ctk.CTkEntry(basic, textvariable=self.initial_value_var)
        row(basic, 5, "Valor inicial", self.initial_entry)
        row(basic, 6, "Descripción", ctk.CTkEntry(basic, textvariable=self.description_var))
        ctk.CTkLabel(basic, text=f"Estado: {self.existing_state}. Se cambia con Bloquear / Desbloquear / Marcar libre.",
                     wraplength=510, justify="left").grid(row=7, column=0, columnspan=2, padx=8, pady=8, sticky="w")
        for index, (label, variable) in enumerate([
            ("Alias (separados por coma)", self.aliases_var), ("Rol semántico", self.semantic_role_var),
            ("Unidad", self.unit_var), ("Mínimo", self.min_var), ("Máximo", self.max_var),
            ("Comentarios", self.comments_var),
        ]):
            row(advanced, index, label, ctk.CTkEntry(advanced, textvariable=variable))
        row(advanced, 6, "Disponible para el LLM", ctk.CTkCheckBox(advanced, text="", variable=self.llm_allowed_var))
        row(advanced, 7, "Nivel de seguridad", ctk.CTkOptionMenu(
            advanced, variable=self.safety_level_var, values=ALLOWED_SAFETY_LEVELS))
        ctk.CTkLabel(self, textvariable=self.error_var, text_color="#9A2424", wraplength=590,
                     justify="left").grid(row=2, column=0, padx=20, pady=6, sticky="ew")
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=20, pady=(0, 16), sticky="e")
        ctk.CTkButton(footer, text="Cancelar", command=self._cancel, fg_color="#64748B").pack(side="left", padx=6)
        ctk.CTkButton(footer, text="Aceptar variable", command=self._confirm).pack(side="left", padx=6)
        self._update_controls()
        self.location_var.trace_add("write", self._analog_binding_changed)
        self.class_var.trace_add("write", self._analog_binding_changed)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.after(50, self.focus_force)

    def _on_kind_changed(self, kind: str) -> None:
        previous_prefix = KINDS[self.kind_var.get()][2]
        # OptionMenu changes its variable before calling the command; infer old prefix from the name.
        name = self.name_var.get()
        for _, _, prefix, _, _ in KINDS.values():
            if name.startswith(prefix):
                previous_prefix = prefix
                break
        self.kind_var.set(kind)
        cls, types, prefix, _, _ = KINDS[kind]
        self.class_var.set(cls)
        self.type_menu.configure(values=types)
        self.type_var.set(types[0])
        if name.startswith(previous_prefix):
            self.name_var.set(prefix + name[len(previous_prefix):])
        self.location_var.set("")
        self.initial_value_var.set("FALSE" if types[0] == "BOOL" else "0" if types[0] == "INT" else "")
        self._update_controls()

    def _analog_binding_changed(self, *_args) -> None:
        self.analog_panel.variables["confirmed"].set(False)
        self.analog_panel._refresh()

    def _on_type_changed(self, _value: str) -> None:
        if self.kind_var.get() == "Detector de flanco":
            name = self.name_var.get()
            if name.startswith(("R_", "F_")):
                self.name_var.set(("F_" if self.type_var.get() == "F_TRIG" else "R_") + name[2:])
        if self.initial_value_var.get() in {"", "FALSE", "0"}:
            self.initial_value_var.set("FALSE" if self.type_var.get() == "BOOL" else "0" if self.type_var.get() == "INT" else "")

    def _update_controls(self) -> None:
        cls, _, prefix, pattern, example = KINDS[self.kind_var.get()]
        hint = (f"Ejemplo: {example} (también admite %{example}). Nombre: {prefix}..."
                if example else f"Sin dirección física obligatoria. Nombre: {prefix}...")
        self.address_hint.configure(text=hint)
        self.location_entry.configure(state="normal" if pattern else "disabled")
        self.initial_entry.configure(state="normal" if cls in {"input", "output", "internal"} else "disabled")
        self.analog_panel.set_channel(cls, cls in {"input", "output"} and self.type_var.get() == "INT")
        self.process_panel.set_active(self.kind_var.get() == "Señal de proceso en DB")

    def _confirm(self) -> None:
        errors = []
        for label, value in (("Mínimo", self.min_var.get()), ("Máximo", self.max_var.get())):
            if value.strip():
                try:
                    if not math.isfinite(float(value)):
                        raise ValueError
                except ValueError:
                    errors.append(f"{label}: introduzca un número finito.")
        fields = {key: getattr(self, key + "_var").get() for key in (
            "name", "class", "type", "location", "initial_value", "description", "aliases", "semantic_role",
            "llm_allowed", "safety_level", "unit", "min", "max", "comments")}
        fields["location"] = canonical_address(fields["location"])
        entry = {**self.original, **normalize_variable_entry({**fields, "state": self.existing_state})}
        try:
            config = self.analog_panel.read_configuration()
        except ValueError as error:
            self.error_var.set(str(error))
            return
        if config is not None:
            entry["analog_config"] = config
        else:
            entry.pop("analog_config", None)
        if self.kind_var.get() == "Señal de proceso en DB":
            try:
                entry['process_config'] = self.process_panel.get_config()
            except ValueError as error:
                self.error_var.set(str(error))
                return
        else:
            entry.pop('process_config', None)
        cls, types, prefix, pattern, _ = KINDS[self.kind_var.get()]
        prefixes = ("R_", "F_") if cls == "auxiliary" else (prefix,)
        if entry["class"] != cls or entry["type"] not in types or not entry["name"].startswith(prefixes):
            errors.append(f"La clase seleccionada requiere tipo {' / '.join(types)} y nombre {prefix}...")
        address = entry["location"]
        if address and (not pattern or not re.fullmatch(pattern, address)):
            errors.append("Dirección incompatible con la clase seleccionada; use el formato del ejemplo (bits 0 a 7).")
        if cls == "internal" and address:
            expected = r"%MX\d+\.[0-7]" if entry["type"] == "BOOL" else r"%MW\d+"
            if not re.fullmatch(expected, address):
                errors.append("La memoria BOOL usa Mbyte.bit; la memoria INT usa MWbyte.")
        initial = entry["initial_value"]
        if initial and entry["type"] == "BOOL" and initial.upper() not in {"TRUE", "FALSE", "0", "1"}:
            errors.append("Valor inicial BOOL: TRUE o FALSE.")
        if initial and entry["type"] == "INT":
            if not re.fullmatch(r"[+-]?\d+", initial) or not -32768 <= int(initial) <= 32767:
                errors.append("Valor inicial INT: entero entre -32768 y 32767.")
        if initial and entry["type"] == "REAL":
            try:
                if not math.isfinite(float(initial)):
                    raise ValueError
            except ValueError:
                errors.append('Valor inicial REAL: número finito.')
        errors.extend(validate_plc_variable_map({"variables": [*self.other_variables, entry]})["errors"])
        if errors:
            self.error_var.set("\n".join(errors[:3]))
            return
        self.result = entry
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()
