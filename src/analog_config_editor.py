"""Per-device analog configuration form, shared by both map editors."""
from __future__ import annotations

import copy
import math
import tkinter as tk
from typing import Any

import customtkinter as ctk

from analog_config import FIELD_LABELS, NUMERIC_FIELDS, SIGNAL_RANGES, analog_configuration_report
from engineering_units import QUANTITY_UNITS, canonical_unit, compatible_unit, convert_unit, quantity_label


SIGNAL_LABELS = {"PENDING": "Pendiente", "0-10V": "0–10 V", "-10-10V": "−10–10 V",
                 "0-20mA": "0–20 mA", "4-20mA": "4–20 mA",
                 "CUSTOM_V": "Voltaje personalizado (V)", "CUSTOM_MA": "Corriente personalizada (mA)"}
FAULT_LABELS = {"PENDING": "Pendiente", "INHIBIT_CONTROL": "Inhibir control",
                "SUBSTITUTE_VALUE": "Sustituir valor de entrada", "SAFE_VALUE": "Aplicar valor seguro"}
DEVICE_LABELS = {"PENDING": "Pendiente", "SENSOR": "Sensor", "PROPORTIONAL_VALVE": "Válvula proporcional",
                 "VARIABLE_SPEED_DRIVE": "Variador de velocidad", "OTHER_ACTUATOR": "Otro actuador", "OTHER": "Otro dispositivo"}


class AnalogConfigurationPanel(ctk.CTkScrollableFrame):
    CUSTOM_CHOICE = "Personalizada…"
    PENDING_CHOICE = "Pendiente"

    def __init__(self, parent, data: dict[str, Any]) -> None:
        super().__init__(parent, fg_color="transparent")
        self.original = copy.deepcopy(data.get("analog_config")) if isinstance(data.get("analog_config"), dict) else {}
        self.channel_class = data.get("class", "input")
        self.compatible = False
        self.enabled_var = tk.BooleanVar(self, value="analog_config" in data)
        self.variables = {}
        for field in FIELD_LABELS:
            default = "PENDING" if field in {"signal_type", "fault_action"} else ""
            value = self.original.get(field, default)
            self.variables[field] = tk.StringVar(self, value="" if value is None else str(value))
        self.variables["confirmed"] = tk.BooleanVar(self, value=self.original.get("confirmed") is True)
        self.variables["device_kind"] = tk.StringVar(self, value=self.original.get("device_kind", "PENDING"))
        self.signal_label_var = tk.StringVar(self)
        self.fault_label_var = tk.StringVar(self)
        self.device_label_var = tk.StringVar(self)
        self.quantity_choice_var = tk.StringVar(self)
        self.unit_choice_var = tk.StringVar(self)
        self.unit_notice_var = tk.StringVar(self)
        self._previous_quantity = self.variables["quantity"].get()
        self._previous_unit = self.variables["engineering_unit"].get()
        self._quantity_custom_mode = bool(self._previous_quantity and quantity_label(self._previous_quantity) is None)
        initial_units = QUANTITY_UNITS.get(quantity_label(self._previous_quantity), ())
        self._unit_custom_mode = bool(self._previous_unit and canonical_unit(self._previous_unit) not in initial_units)
        self.status_var = tk.StringVar(self)
        self.grid_columnconfigure(1, weight=1)
        self.widgets = []
        ctk.CTkCheckBox(self, text="Configurar señal y escalado de este canal", variable=self.enabled_var,
                       command=self._changed).grid(row=0, column=0, columnspan=2, padx=8, pady=10, sticky="w")
        self.explanation = ctk.CTkLabel(self, text="", wraplength=510, justify="left")
        self.explanation.grid(row=1, column=0, columnspan=2, padx=8, pady=6, sticky="w")

        def row(index, label, widget, controls=None):
            ctk.CTkLabel(self, text=label).grid(row=index, column=0, padx=(8, 14), pady=6, sticky="w")
            widget.grid(row=index, column=1, padx=(0, 8), pady=6, sticky="ew")
            self.widgets.extend(controls if controls is not None else [widget])

        device_frame = ctk.CTkFrame(self, fg_color="transparent")
        device_frame.grid_columnconfigure(0, weight=1)
        self.device_menu = ctk.CTkOptionMenu(device_frame, variable=self.device_label_var,
                                            values=list(DEVICE_LABELS.values()), command=self._on_device_selected)
        self.device_menu.grid(row=0, column=0, sticky="ew")
        device_name = ctk.CTkEntry(device_frame, textvariable=self.variables["device_name"], placeholder_text="Nombre / modelo del dispositivo")
        device_name.grid(row=1, column=0, pady=(4, 0), sticky="ew")
        row(2, "Dispositivo", device_frame, [self.device_menu, device_name])
        quantity_frame = ctk.CTkFrame(self, fg_color="transparent")
        quantity_frame.grid_columnconfigure(0, weight=1)
        self.quantity_menu = ctk.CTkOptionMenu(quantity_frame, variable=self.quantity_choice_var,
                                              values=[self.PENDING_CHOICE, *QUANTITY_UNITS, self.CUSTOM_CHOICE],
                                              command=self._on_quantity_selected)
        self.quantity_menu.grid(row=0, column=0, sticky="ew")
        self.quantity_entry = ctk.CTkEntry(quantity_frame, textvariable=self.variables["quantity"], placeholder_text="Magnitud personalizada")
        self.quantity_entry.grid(row=1, column=0, pady=(4, 0), sticky="ew")
        row(3, "Magnitud física", quantity_frame, [self.quantity_menu, self.quantity_entry])
        row(4, "Señal eléctrica", ctk.CTkOptionMenu(self, variable=self.signal_label_var,
                                                 values=list(SIGNAL_LABELS.values()), command=self._on_signal_changed))
        for index, (field, label) in enumerate([
            ("electrical_min", "Mínimo eléctrico (V o mA)"), ("electrical_max", "Máximo eléctrico (V o mA)"),
            ("raw_min", "Mínimo raw del PLC"), ("raw_max", "Máximo raw del PLC"),
            ("engineering_min", "Mínimo físico"), ("engineering_max", "Máximo físico"),
            ("engineering_unit", "Unidad física"),
        ], start=5):
            if field == "engineering_unit":
                unit_frame = ctk.CTkFrame(self, fg_color="transparent")
                unit_frame.grid_columnconfigure(0, weight=1)
                self.unit_menu = ctk.CTkOptionMenu(unit_frame, variable=self.unit_choice_var,
                                                  values=[self.PENDING_CHOICE, self.CUSTOM_CHOICE], command=self._on_unit_selected)
                self.unit_menu.grid(row=0, column=0, sticky="ew")
                self.unit_entry = ctk.CTkEntry(unit_frame, textvariable=self.variables[field], placeholder_text="Unidad personalizada")
                self.unit_entry.grid(row=1, column=0, pady=(4, 0), sticky="ew")
                row(index, label, unit_frame, [self.unit_menu, self.unit_entry])
            else:
                row(index, label, ctk.CTkEntry(self, textvariable=self.variables[field]))
        self.fault_menu = ctk.CTkOptionMenu(self, variable=self.fault_label_var,
                                           values=list(FAULT_LABELS.values()), command=self._on_fault_changed)
        row(13, "Ante señal inválida", self.fault_menu)
        self.fault_entry = ctk.CTkEntry(self, textvariable=self.variables["fault_value"])
        row(14, "Valor ante fallo (unidad física)", self.fault_entry)
        self.confirm_check = ctk.CTkCheckBox(self, text="Confirmo señal y rangos con TIA y el dispositivo",
                                           variable=self.variables["confirmed"], command=self._refresh)
        self.confirm_check.grid(row=15, column=0, columnspan=2, padx=8, pady=12, sticky="w")
        self.widgets.append(self.confirm_check)
        ctk.CTkLabel(self, textvariable=self.status_var, wraplength=510, justify="left").grid(
            row=16, column=0, columnspan=2, padx=8, pady=10, sticky="w")
        ctk.CTkLabel(self, text="Al generar se usan los rangos confirmados para el escalado y las acciones ante fallo. El bloque PID se configura en una etapa posterior.",
                     wraplength=510, justify="left", text_color="#556272").grid(
            row=17, column=0, columnspan=2, padx=8, pady=10, sticky="w")
        self.unit_notice_label = ctk.CTkLabel(self, textvariable=self.unit_notice_var, wraplength=510, justify="left")
        self.unit_notice_label.grid(row=12, column=0, columnspan=2, padx=8, pady=8, sticky="w")
        for field, variable in self.variables.items():
            if field != "confirmed":
                variable.trace_add("write", self._changed)
        self.variables["quantity"].trace_add("write", self._quantity_changed)
        self.variables["engineering_unit"].trace_add("write", self._unit_changed)

    def set_channel(self, cls: str, compatible: bool) -> None:
        self.channel_class, self.compatible = cls, compatible
        actions = ("PENDING", "SAFE_VALUE") if cls == "output" else ("PENDING", "INHIBIT_CONTROL", "SUBSTITUTE_VALUE")
        self.fault_menu.configure(values=[FAULT_LABELS[action] for action in actions])
        devices = ("PENDING", "PROPORTIONAL_VALVE", "VARIABLE_SPEED_DRIVE", "OTHER_ACTUATOR", "OTHER") if cls == "output" else ("PENDING", "SENSOR", "OTHER")
        self.device_menu.configure(values=[DEVICE_LABELS[kind] for kind in devices])
        self.explanation.configure(text=(
            "Separe el rango eléctrico del sensor, los valores raw del módulo y la magnitud física. Los rangos raw deben obtenerse de la plantilla TIA; no se rellenan automáticamente."
            if compatible else "Esta configuración solo corresponde a canales analógicos INT (%IW / %QW). Desactívela si cambia la variable a una clase digital o interna."))
        self._refresh()

    def _changed(self, *_args) -> None:
        self.variables["confirmed"].set(False)
        self._refresh()

    def _on_device_selected(self, selection: str) -> None:
        kind = next((key for key, label in DEVICE_LABELS.items() if label == selection), selection)
        self.variables["device_kind"].set(kind)

    def _on_quantity_selected(self, selection: str) -> None:
        self._quantity_custom_mode = selection == self.CUSTOM_CHOICE
        value = "" if selection in {self.CUSTOM_CHOICE, self.PENDING_CHOICE} else selection
        self.variables["quantity"].set(value)
        self._refresh()

    def _on_unit_selected(self, selection: str) -> None:
        self._unit_custom_mode = selection == self.CUSTOM_CHOICE
        value = "" if selection in {self.CUSTOM_CHOICE, self.PENDING_CHOICE} else selection
        self.variables["engineering_unit"].set(value)
        self._refresh()

    def _clear_physical_values(self) -> None:
        for field in ("engineering_min", "engineering_max", "fault_value"):
            self.variables[field].set("")

    def _quantity_changed(self, *_args) -> None:
        previous, current = self._previous_quantity, self.variables["quantity"].get()
        self._previous_quantity = current
        previous_key = quantity_label(previous) or previous.strip()
        current_key = quantity_label(current) or current.strip()
        if previous.strip() and previous_key != current_key:
            self._clear_physical_values()
            if not current.strip() or not compatible_unit(current, self.variables["engineering_unit"].get()):
                self.variables["engineering_unit"].set("")
            self.unit_notice_var.set("Magnitud modificada: introduzca nuevamente el rango físico y el valor ante fallo.")
        self._refresh()

    def _unit_changed(self, *_args) -> None:
        previous, current = self._previous_unit, self.variables["engineering_unit"].get()
        self._previous_unit = current
        if previous.strip() and canonical_unit(previous) != canonical_unit(current):
            try:
                quantity = self.variables["quantity"].get()
                if quantity_label(quantity) is None or not compatible_unit(quantity, previous) or not compatible_unit(quantity, current):
                    raise ValueError
                converted = {}
                for field in ("engineering_min", "engineering_max", "fault_value"):
                    value = self.variables[field].get().strip()
                    converted[field] = format(convert_unit(float(value), previous, current), ".15g") if value else ""
                for field, value in converted.items():
                    self.variables[field].set(value)
                self.unit_notice_var.set(f"Conversión {previous} → {current}: se actualizaron límites y valor ante fallo. Confirme los datos de nuevo.")
            except (ValueError, OverflowError):
                self._clear_physical_values()
                self.unit_notice_var.set("Cambio de unidad sin conversión directa: introduzca nuevamente los límites físicos y el valor ante fallo.")
        self._refresh()

    def _refresh_choices(self) -> None:
        self.unit_notice_label.grid() if self.unit_notice_var.get() else self.unit_notice_label.grid_remove()
        quantity = self.variables["quantity"].get()
        label = quantity_label(quantity)
        custom_quantity = self._quantity_custom_mode or bool(quantity.strip() and label is None)
        self.quantity_choice_var.set(self.CUSTOM_CHOICE if custom_quantity else label or self.PENDING_CHOICE)
        self.quantity_entry.grid() if custom_quantity else self.quantity_entry.grid_remove()
        units = QUANTITY_UNITS.get(label, ())
        self.unit_menu.configure(values=[self.PENDING_CHOICE, *units, self.CUSTOM_CHOICE])
        unit = self.variables["engineering_unit"].get()
        custom_unit = self._unit_custom_mode or bool(unit.strip() and canonical_unit(unit) not in units)
        self.unit_choice_var.set(self.CUSTOM_CHOICE if custom_unit else canonical_unit(unit) or self.PENDING_CHOICE)
        self.unit_entry.grid() if custom_unit else self.unit_entry.grid_remove()
        kind = self.variables["device_kind"].get()
        self.device_label_var.set(DEVICE_LABELS.get(kind, kind))

    def _on_signal_changed(self, selection: str) -> None:
        signal = next((key for key, label in SIGNAL_LABELS.items() if label == selection), selection)
        self.variables["signal_type"].set(signal)
        preset = SIGNAL_RANGES.get(signal)
        for field, number in zip(("electrical_min", "electrical_max"), preset or (None, None)):
            self.variables[field].set("" if number is None else str(number))

    def _on_fault_changed(self, selection: str) -> None:
        action = next((key for key, label in FAULT_LABELS.items() if label == selection), selection)
        self.variables["fault_action"].set(action)
        if action not in {"SUBSTITUTE_VALUE", "SAFE_VALUE"}:
            self.variables["fault_value"].set("")

    def read_configuration(self) -> dict[str, Any] | None:
        if not self.enabled_var.get():
            return None
        config = {**self.original, "schema_version": self.original.get("schema_version", 1)}
        for field, variable in self.variables.items():
            if field == "device_kind" and variable.get() == "PENDING" and field not in self.original:
                continue  # preserve the exact optional schema of previously saved maps
            value = variable.get()
            if field in NUMERIC_FIELDS:
                if not value.strip():
                    value = None
                else:
                    try:
                        number = float(value)
                        if not math.isfinite(number):
                            raise ValueError
                        value = int(number) if field.startswith("raw_") and number.is_integer() else number
                    except ValueError:
                        raise ValueError(f"Configuración analógica: {FIELD_LABELS[field]} debe ser un número finito.") from None
            elif isinstance(value, str):
                value = value.strip()
            config[field] = value
        return config

    def _refresh(self) -> None:
        self._refresh_choices()
        enabled = self.enabled_var.get() and self.compatible
        for widget in self.widgets:
            widget.configure(state="normal" if enabled else "disabled")
        action = self.variables["fault_action"].get()
        self.fault_entry.configure(state="normal" if enabled and action in {"SUBSTITUTE_VALUE", "SAFE_VALUE"} else "disabled")
        signal = self.variables["signal_type"].get()
        self.signal_label_var.set(SIGNAL_LABELS.get(signal, signal))
        self.fault_label_var.set(FAULT_LABELS.get(action, action))
        try:
            config = self.read_configuration()
            entry = {"name": "Canal", "class": self.channel_class, "type": "INT",
                     "location": "%QW0" if self.channel_class == "output" else "%IW0"}
            if config is None:
                self.status_var.set("Sin configuración analógica. Los mapas existentes conservan su funcionamiento.")
                return
            report = analog_configuration_report({**entry, "analog_config": config})
            if report["errors"]:
                self.status_var.set(report["errors"][0])
            elif report["ready"] and self.compatible:
                self.status_var.set("Configuración completa y confirmada para la futura generación del control.")
            elif report["missing_fields"]:
                self.status_var.set("Pendiente: " + ", ".join(FIELD_LABELS[field] for field in report["missing_fields"]))
            else:
                self.status_var.set("Datos completos. Falta confirmar su correspondencia con el módulo y el dispositivo.")
        except ValueError as error:
            self.status_var.set(str(error))
