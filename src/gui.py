from __future__ import annotations

import csv
import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any
import os
import socket

try:
    import winsound
except ImportError:  # pragma: no cover - Windows only
    winsound = None

try:
    import customtkinter as ctk
except ImportError as error:
    raise SystemExit(
        "CustomTkinter no esta instalado. Ejecute: pip install -r requirements.txt"
    ) from error

from gui_helpers import (
    ADVANCED_VARIABLE_DEFAULTS,
    ALLOWED_IO_CLASSES,
    ALLOWED_IO_TYPES,
    ALLOWED_SAFETY_LEVELS,
    IO_TREE_COLUMNS,
    append_history_row,
    console_message,
    format_json,
    get_status_colors,
    load_io_map_variables,
    load_rows_into_treeview,
    normalize_parser_mode_selection,
    normalize_platform_targets,
    normalize_variable_entry,
    platform_label,
    save_io_map_variables,
    treeview_rows,
    validate_io_map_variables
)
from env_manager import get_env_path, load_llm_env_settings, save_llm_env_settings
from io_allocator import (
    apply_assignments,
    block_map_config_message,
    find_variable_by_address,
    set_variable_state,
    validate_manual_rename
)
from logger import (
    append_test_record_to_docs,
    archive_generated_files,
    clear_generated_files,
    ensure_generated_dirs
)
from llm_client import PLCInterpretationLLMClient
from llm_parser import parse_command, resolve_parser_mode
from plc_maps import (
    GENERAL_PROFILE_LABEL,
    apply_profile_filter,
    check_case_compatibility,
    create_plc_map,
    delete_plc_map,
    ensure_plc_maps_library,
    format_validation_report,
    get_profile,
    list_plc_maps,
    load_plc_map,
    load_profiles,
    profile_readiness_summary,
    resolve_active_map_path,
    save_active_map_id,
    save_plc_map,
    validate_plc_variable_map
)
from plc_maps.tia_sync import import_tags_from_tia, sync_map_with_tia
from project_packager import generate_project_package
from semantic_validator import validate_semantic_output
from speech_recognizer import SpeechRecognizer
from tia_openness import (
    DOWNLOAD_PURPOSE_EXPERIMENT,
    DOWNLOAD_PURPOSE_NORMAL,
    TARGET_TYPE_PLCSIM,
    build_openness_bridge,
    diagnose_tia_openness,
    download_program_to_plc,
    load_tia_config,
    resolve_download_target,
    run_openness_bridge_diagnostic,
    save_tia_config,
    validate_package_with_tia
)
import plcsim_runtime
import plcsim_runtime_io
from plcsim_runtime import get_plcsim_runtime_status
from trial_experiments import benchmark_catalog, oracle_review, oracle_runner, oracle_schema, trial_io_map, trial_model
from trial_experiments.oracle_runner import run_oracle
from trial_experiments.oracle_schema import find_case_oracle
from trial_experiments import (
    CONDITIONS,
    ENVIRONMENT_LABELS,
    ENVIRONMENTS,
    ERROR_CODES,
    MASTER_LOG_FIELDS,
    NO_ERROR_LABEL,
    NOISE_LEVEL_LABELS,
    NOISE_LEVELS,
    PHYSICAL_RESULT_OPTIONS,
    build_experiment_label,
    compute_next_repetition,
    get_git_commit,
    get_variant_command,
    load_all_trials,
    load_variants_for_case,
    next_trial_id,
    record_trial_summary,
    save_metadata,
    trial_dir,
    update_observations,
    write_trial_files
)
from utils import get_project_root, load_json_file, sanitize_filename


ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")


GUI_INSTANCE_PORT = 49573
_GUI_INSTANCE_SOCKET: socket.socket | None = None


class VariableEditorDialog(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk, title: str, variable_data: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("560x780")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        data = variable_data or {}
        self.result: dict[str, Any] | None = None

        self.name_var = tk.StringVar(value=data.get("name", ""))
        self.class_var = tk.StringVar(value=data.get("class", "internal"))
        self.type_var = tk.StringVar(value=data.get("type", "BOOL"))
        self.location_var = tk.StringVar(value=data.get("location", ""))
        self.initial_value_var = tk.StringVar(value=data.get("initial_value", ""))
        self.description_var = tk.StringVar(value=data.get("description", ""))
        self.aliases_var = tk.StringVar(value=", ".join(data.get("aliases", [])))
        self.semantic_role_var = tk.StringVar(value=data.get("semantic_role", ""))
        self.llm_allowed_var = tk.BooleanVar(value=bool(data.get("llm_allowed", True)))
        self.safety_level_var = tk.StringVar(value=data.get("safety_level", "normal"))
        self.unit_var = tk.StringVar(value=str(data.get("unit", "") or ""))
        self.min_var = tk.StringVar(value="" if data.get("min") is None else str(data.get("min")))
        self.max_var = tk.StringVar(value="" if data.get("max") is None else str(data.get("max")))
        self.comments_var = tk.StringVar(value=data.get("comments", ""))
        # El estado FREE/ASSIGNED/LOCKED NO se edita aqui a proposito (docs/23_io_allocator.md):
        # solo los botones dedicados [Bloquear]/[Desbloquear] lo cambian, para que editar otro
        # campo (p. ej. la descripcion) nunca reinicie/pierda silenciosamente un LOCKED existente.
        self.existing_state = data.get("state", "ASSIGNED")

        self.grid_columnconfigure(1, weight=1)

        header = ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=20, weight="bold"))
        header.grid(row=0, column=0, columnspan=2, padx=20, pady=(18, 4), sticky="w")

        state_label = ctk.CTkLabel(
            self,
            text=f"Estado: {self.existing_state} (usar [Bloquear]/[Desbloquear] en el panel para cambiarlo)",
            text_color="#556272"
        )
        state_label.grid(row=0, column=0, columnspan=2, padx=20, pady=(44, 8), sticky="w")

        self._build_form_row(1, "Name", ctk.CTkEntry(self, textvariable=self.name_var))
        self._build_form_row(
            2,
            "Class",
            ctk.CTkOptionMenu(self, variable=self.class_var, values=ALLOWED_IO_CLASSES)
        )
        self._build_form_row(
            3,
            "Type",
            ctk.CTkOptionMenu(self, variable=self.type_var, values=ALLOWED_IO_TYPES)
        )
        self._build_form_row(4, "Location", ctk.CTkEntry(self, textvariable=self.location_var))
        self._build_form_row(5, "Initial value", ctk.CTkEntry(self, textvariable=self.initial_value_var))
        self._build_form_row(6, "Description", ctk.CTkEntry(self, textvariable=self.description_var))

        helper = ctk.CTkLabel(
            self,
            text="Use %IX... para entradas, %QX... para salidas y deje vacio para memorias o bloques.",
            text_color="#556272",
            justify="left",
            wraplength=450
        )
        helper.grid(row=7, column=0, columnspan=2, padx=20, pady=(6, 10), sticky="w")

        advanced_label = ctk.CTkLabel(self, text="Avanzado (mapa maestro)", font=ctk.CTkFont(size=14, weight="bold"))
        advanced_label.grid(row=8, column=0, columnspan=2, padx=20, pady=(4, 6), sticky="w")

        self._build_form_row(9, "Aliases (separados por coma)", ctk.CTkEntry(self, textvariable=self.aliases_var))
        self._build_form_row(10, "Rol semantico", ctk.CTkEntry(self, textvariable=self.semantic_role_var))
        self._build_form_row(
            11,
            "Permitido para LLM",
            ctk.CTkCheckBox(self, text="", variable=self.llm_allowed_var)
        )
        self._build_form_row(
            12,
            "Nivel de seguridad",
            ctk.CTkOptionMenu(self, variable=self.safety_level_var, values=ALLOWED_SAFETY_LEVELS)
        )
        self._build_form_row(13, "Unidad", ctk.CTkEntry(self, textvariable=self.unit_var))
        self._build_form_row(14, "Minimo", ctk.CTkEntry(self, textvariable=self.min_var))
        self._build_form_row(15, "Maximo", ctk.CTkEntry(self, textvariable=self.max_var))
        self._build_form_row(16, "Comentarios", ctk.CTkEntry(self, textvariable=self.comments_var))

        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=17, column=0, columnspan=2, padx=20, pady=(10, 20), sticky="ew")
        button_frame.grid_columnconfigure((0, 1), weight=1)

        cancel_button = ctk.CTkButton(button_frame, text="Cancelar", fg_color="#6B7280", hover_color="#4B5563", command=self._cancel)
        cancel_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        save_button = ctk.CTkButton(button_frame, text="Aceptar", command=self._confirm)
        save_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(50, self.focus_force)

    def _build_form_row(self, row_index: int, label_text: str, widget: ctk.CTkBaseClass) -> None:
        label = ctk.CTkLabel(self, text=label_text)
        label.grid(row=row_index, column=0, padx=(20, 12), pady=6, sticky="w")
        widget.grid(row=row_index, column=1, padx=(0, 20), pady=6, sticky="ew")

    def _confirm(self) -> None:
        self.result = normalize_variable_entry(
            {
                "name": self.name_var.get(),
                "class": self.class_var.get(),
                "type": self.type_var.get(),
                "location": self.location_var.get(),
                "initial_value": self.initial_value_var.get(),
                "description": self.description_var.get(),
                "aliases": self.aliases_var.get(),
                "semantic_role": self.semantic_role_var.get(),
                "llm_allowed": self.llm_allowed_var.get(),
                "safety_level": self.safety_level_var.get(),
                "unit": self.unit_var.get(),
                "min": self.min_var.get(),
                "max": self.max_var.get(),
                "comments": self.comments_var.get(),
                "state": self.existing_state
            }
        )
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class FullIOMapWindow(ctk.CTkToplevel):
    """
    Ventana independiente "Mapa I/O completo" (secciones 7-10 y 25): muestra TODOS los canales
    del mapa activo (no solo los que caben en la tabla pequena del panel izquierdo), con
    Direccion/Nombre/Tipo/Clase/Estado/Descripcion. La direccion fisica nunca es editable aqui.
    Cada accion (renombrar/bloquear/desbloquear/marcar libre) valida con io_allocator y persiste
    de inmediato con save_plc_map - nunca queda solo en memoria esperando un "Guardar" separado,
    que es precisamente el problema reportado (el nombre "no cambiaba realmente"). [Guardar] y
    [Guardar como...] reutilizan los metodos ya existentes de la app (save_io_map/save_plc_map_as).
    """

    COLUMNS = ("address", "name", "type", "class_label", "state", "description")
    HEADERS = {
        "address": "Direccion", "name": "Nombre funcional", "type": "Tipo",
        "class_label": "Clase", "state": "Estado", "description": "Descripcion"
    }

    def __init__(self, parent: "VozLLMPLCGUI") -> None:
        super().__init__(parent)
        self.app = parent
        self.io_map: dict[str, Any] = {}
        self.transient(parent)
        self.geometry("920x580")

        self.read_only_message = block_map_config_message(parent.active_trial, parent.active_profile_id)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(self, text="Mapa I/O completo", font=ctk.CTkFont(size=20, weight="bold"))
        header.grid(row=0, column=0, padx=20, pady=(16, 4), sticky="w")

        if self.read_only_message:
            warning = ctk.CTkLabel(self, text=self.read_only_message, text_color="#8A1F1F")
            warning.grid(row=0, column=0, padx=20, pady=(46, 4), sticky="w")

        tree_container = ctk.CTkFrame(self, corner_radius=12)
        tree_container.grid(row=1, column=0, padx=20, pady=(4, 8), sticky="nsew")
        tree_container.grid_columnconfigure(0, weight=1)
        tree_container.grid_rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(tree_container, columns=self.COLUMNS, show="headings", height=18)
        self.tree.grid(row=0, column=0, sticky="nsew")
        for column in self.COLUMNS:
            self.tree.heading(column, text=self.HEADERS[column])
            width = 220 if column == "description" else 130
            self.tree.column(column, width=width, minwidth=70, stretch=True)
        scroll_y = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        scroll_y.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll_y.set)

        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=2, column=0, padx=20, pady=(0, 18), sticky="ew")
        for index in range(6):
            button_frame.grid_columnconfigure(index, weight=1)

        actions = [
            ("Editar nombre", self.edit_name),
            ("Bloquear", self.lock_selected),
            ("Desbloquear", self.unlock_selected),
            ("Marcar libre", self.mark_free_selected),
            ("Guardar", self.save),
            ("Guardar como...", self.save_as)
        ]
        self.action_buttons: list[ctk.CTkButton] = []
        for index, (text, command) in enumerate(actions):
            button = ctk.CTkButton(button_frame, text=text, command=command, font=self.app.button_font)
            button.grid(row=0, column=index, padx=4, sticky="ew")
            self.action_buttons.append(button)

        if self.read_only_message:
            for button in self.action_buttons[:4]:  # Guardar/Guardar como siguen disponibles (solo lectura de asignaciones)
                button.configure(state="disabled")

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._reload()
        self.after(50, self.focus_force)

    def _class_label(self, variable: dict[str, Any]) -> str:
        location = str(variable.get("location", "")).upper()
        is_analog = "W" in location
        variable_class = variable.get("class")
        if variable_class == "input":
            return "AI" if is_analog else "DI"
        if variable_class == "output":
            return "AO" if is_analog else "DO"
        return variable_class or ""

    def _reload(self) -> None:
        previous_selection = self._selected_address()
        try:
            self.io_map = load_json_file(self.app.io_map_path)
        except (FileNotFoundError, ValueError) as error:
            messagebox.showerror("Mapa I/O completo", f"No se pudo leer el mapa activo.\n\n{error}")
            self.io_map = {"variables": []}
        self.title(f"Mapa I/O - {self.app.active_map_var.get() or self.app.io_map_path.stem}")
        self.tree.delete(*self.tree.get_children())
        for variable in self.io_map.get("variables", []):
            state = variable.get("state", "ASSIGNED")
            # Un canal FREE no tiene todavia un rol funcional real (seccion 12): el nombre interno
            # (necesario para indexar/autorizar el recurso) se oculta y se muestra "-" en su lugar.
            name_display = "—" if state == "FREE" else variable.get("name", "")
            self.tree.insert(
                "", "end", iid=variable.get("location"),
                values=(
                    variable.get("location", ""), name_display, variable.get("type", ""),
                    self._class_label(variable), state, variable.get("description", "")
                )
            )
        # Reinsertar borra la seleccion (los iids son las direcciones, estables entre recargas) -
        # sin esto, tras UNA accion el usuario tendria que volver a seleccionar la fila cada vez.
        if previous_selection and self.tree.exists(previous_selection):
            self.tree.selection_set(previous_selection)
            self.tree.focus(previous_selection)

    def _selected_address(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _refresh_everything(self) -> None:
        self._reload()
        self.app.io_variables = load_io_map_variables(self.app.io_map_path)
        self.app._load_active_map_metadata_shadow()
        self.app._load_io_map_table()

    def edit_name(self) -> None:
        if self.read_only_message:
            messagebox.showwarning("Mapa I/O completo", self.read_only_message)
            return
        address = self._selected_address()
        if address is None:
            messagebox.showwarning("Editar nombre", "Seleccione un canal.")
            return
        variable = find_variable_by_address(self.io_map, address)
        if variable is None:
            return
        if variable.get("state") == "LOCKED":
            messagebox.showwarning(
                "Editar nombre",
                "Este canal esta bloqueado. Desbloqueelo manualmente antes de modificarlo."
            )
            return

        new_name = simpledialog.askstring(
            "Editar nombre",
            f"Nuevo nombre funcional para {address} (actual: {variable.get('name') or '—'}):",
            initialvalue="" if variable.get("state") == "FREE" else variable.get("name", ""),
            parent=self
        )
        if not new_name or not new_name.strip():
            return
        new_name = new_name.strip()

        result = validate_manual_rename(self.io_map, address, new_name)
        if not result["valid"]:
            messagebox.showerror("Editar nombre", "\n".join(result["errors"]))
            return

        proposal = {"address": address, "proposed_name": new_name, "blocked": False}
        try:
            updated_map, history_entries = apply_assignments(self.io_map, [proposal], source="MANUAL_EDITOR")
            save_plc_map(self.app.io_map_path, updated_map["variables"], history_entries=history_entries)
        except ValueError as error:
            messagebox.showerror("Editar nombre", str(error))
            return

        self._refresh_everything()
        self.app._log(f"Mapa I/O completo: {address} renombrado a {new_name}.")

    def _apply_state_change(self, new_state: str, guard_locked: bool = False) -> None:
        if self.read_only_message:
            messagebox.showwarning("Mapa I/O completo", self.read_only_message)
            return
        address = self._selected_address()
        if address is None:
            messagebox.showwarning("Mapa I/O completo", "Seleccione un canal.")
            return
        variable = find_variable_by_address(self.io_map, address)
        if variable is None:
            return
        if guard_locked and variable.get("state") == "LOCKED":
            messagebox.showwarning(
                "Mapa I/O completo",
                f"{variable.get('name')} esta bloqueada (LOCKED). Desbloqueela primero."
            )
            return
        try:
            updated_map = set_variable_state(self.io_map, variable.get("name"), new_state)
            save_plc_map(self.app.io_map_path, updated_map["variables"])
        except ValueError as error:
            messagebox.showerror("Mapa I/O completo", str(error))
            return
        self._refresh_everything()

    def lock_selected(self) -> None:
        self._apply_state_change("LOCKED")

    def unlock_selected(self) -> None:
        self._apply_state_change("ASSIGNED")

    def mark_free_selected(self) -> None:
        self._apply_state_change("FREE", guard_locked=True)

    def save(self) -> None:
        if self.app.save_io_map(show_success=False):
            self._reload()
            messagebox.showinfo("Mapa I/O completo", "Mapa guardado correctamente.")

    def save_as(self) -> None:
        self.app.save_plc_map_as()
        self._refresh_everything()


class LLMConfigDialog(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk, initial_settings: dict[str, str]) -> None:
        super().__init__(parent)
        self.title("Configurar API LLM")
        self.geometry("640x470")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result: dict[str, str] | None = None

        self.api_key_var = tk.StringVar(value=initial_settings.get("OPENAI_API_KEY", ""))
        self.model_var = tk.StringVar(value=initial_settings.get("PLC_LLM_MODEL", ""))
        self.transcription_model_var = tk.StringVar(value=initial_settings.get("PLC_TRANSCRIPTION_MODEL", ""))
        self.enable_llm_var = tk.BooleanVar(value=initial_settings.get("ENABLE_LLM", "true").strip().lower() == "true")
        self.enable_voice_var = tk.BooleanVar(value=initial_settings.get("ENABLE_VOICE", "true").strip().lower() == "true")
        self.parser_mode_var = tk.StringVar(value=initial_settings.get("PARSER_MODE", "llm"))
        self.threshold_var = tk.StringVar(value=initial_settings.get("LLM_CONFIDENCE_THRESHOLD", "0.85"))

        self.grid_columnconfigure(1, weight=1)

        header = ctk.CTkLabel(self, text="Configuracion OpenAI / LLM", font=ctk.CTkFont(size=21, weight="bold"))
        header.grid(row=0, column=0, columnspan=2, padx=20, pady=(18, 10), sticky="w")

        self._build_form_row(1, "OPENAI_API_KEY", ctk.CTkEntry(self, textvariable=self.api_key_var, show="*"))
        self._build_form_row(2, "PLC_LLM_MODEL", ctk.CTkEntry(self, textvariable=self.model_var))
        self._build_form_row(3, "PLC_TRANSCRIPTION_MODEL", ctk.CTkEntry(self, textvariable=self.transcription_model_var))
        self._build_form_row(
            4,
            "PARSER_MODE",
            ctk.CTkOptionMenu(self, variable=self.parser_mode_var, values=["rule_based", "llm", "hybrid"])
        )
        self._build_form_row(5, "LLM_CONFIDENCE_THRESHOLD", ctk.CTkEntry(self, textvariable=self.threshold_var))

        flags_frame = ctk.CTkFrame(self, fg_color="transparent")
        flags_frame.grid(row=6, column=0, columnspan=2, padx=20, pady=(8, 4), sticky="ew")
        flags_frame.grid_columnconfigure((0, 1), weight=1)

        enable_llm_checkbox = ctk.CTkCheckBox(
            flags_frame,
            text="Habilitar parser LLM",
            variable=self.enable_llm_var
        )
        enable_llm_checkbox.grid(row=0, column=0, padx=(0, 10), pady=4, sticky="w")

        enable_voice_checkbox = ctk.CTkCheckBox(
            flags_frame,
            text="Habilitar transcripcion de voz",
            variable=self.enable_voice_var
        )
        enable_voice_checkbox.grid(row=0, column=1, pady=4, sticky="w")

        helper = ctk.CTkLabel(
            self,
            text=(
                "El LLM solo interpreta el comando y produce JSON semantico. "
                "La generacion del POU sigue siendo local y controlada."
            ),
            text_color="#556272",
            justify="left",
            wraplength=560
        )
        helper.grid(row=7, column=0, columnspan=2, padx=20, pady=(6, 16), sticky="w")

        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=8, column=0, columnspan=2, padx=20, pady=(0, 20), sticky="ew")
        button_frame.grid_columnconfigure((0, 1), weight=1)

        cancel_button = ctk.CTkButton(
            button_frame,
            text="Cancelar",
            fg_color="#6B7280",
            hover_color="#4B5563",
            command=self._cancel
        )
        cancel_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        save_button = ctk.CTkButton(button_frame, text="Guardar configuracion", command=self._confirm)
        save_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(50, self.focus_force)

    def _build_form_row(self, row_index: int, label_text: str, widget: ctk.CTkBaseClass) -> None:
        label = ctk.CTkLabel(self, text=label_text)
        label.grid(row=row_index, column=0, padx=(20, 12), pady=8, sticky="w")
        widget.grid(row=row_index, column=1, padx=(0, 20), pady=8, sticky="ew")

    def _confirm(self) -> None:
        self.result = {
            "OPENAI_API_KEY": self.api_key_var.get().strip(),
            "PLC_LLM_MODEL": self.model_var.get().strip(),
            "PLC_TRANSCRIPTION_MODEL": self.transcription_model_var.get().strip(),
            "PARSER_MODE": self.parser_mode_var.get().strip() or "llm",
            "LLM_CONFIDENCE_THRESHOLD": self.threshold_var.get().strip() or "0.85",
            "ENABLE_LLM": "true" if self.enable_llm_var.get() else "false",
            "ENABLE_VOICE": "true" if self.enable_voice_var.get() else "false"
        }
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class ClarificationDialog(ctk.CTkToplevel):
    """
    Pide al usuario una respuesta REAL a una ambiguedad semantica genuina (SEMANTIC_AMBIGUITY):
    nunca se usa para recursos internos (se autogeneran) ni para recursos fisicos no autorizados
    (esos usan su propio mensaje informativo, sin dialogo de respuesta). Un "Aceptar" vacio no
    cuenta como respuesta - hay que escribir algo o usar los atajos Si/No.
    """

    def __init__(self, parent: ctk.CTk, question: str) -> None:
        super().__init__(parent)
        self.title("Aclaracion requerida")
        self.geometry("520x320")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result: str | None = None

        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(self, text="El comando requiere una aclaracion", font=ctk.CTkFont(size=17, weight="bold"))
        header.grid(row=0, column=0, padx=20, pady=(18, 6), sticky="w")

        question_label = ctk.CTkLabel(
            self, text=question, justify="left", anchor="w", wraplength=470
        )
        question_label.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="ew")

        self.answer_var = tk.StringVar(value="")
        answer_entry = ctk.CTkEntry(
            self, textvariable=self.answer_var,
            placeholder_text="Escriba su respuesta o aclaracion aqui..."
        )
        answer_entry.grid(row=2, column=0, padx=20, pady=(0, 8), sticky="ew")

        quick_frame = ctk.CTkFrame(self, fg_color="transparent")
        quick_frame.grid(row=3, column=0, padx=20, pady=(0, 12), sticky="ew")
        quick_frame.grid_columnconfigure((0, 1), weight=1)
        si_button = ctk.CTkButton(quick_frame, text="Si", command=lambda: self.answer_var.set("Si"))
        si_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        no_button = ctk.CTkButton(quick_frame, text="No", command=lambda: self.answer_var.set("No"))
        no_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")

        helper = ctk.CTkLabel(
            self,
            text=(
                "La respuesta se usara para reprocesar el comando (no autoriza recursos "
                "fisicos nuevos; para eso use Modo Normal o cambie de caso experimental)."
            ),
            text_color="#556272",
            justify="left",
            wraplength=470
        )
        helper.grid(row=4, column=0, padx=20, pady=(0, 10), sticky="ew")

        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=5, column=0, padx=20, pady=(0, 20), sticky="ew")
        button_frame.grid_columnconfigure((0, 1), weight=1)

        cancel_button = ctk.CTkButton(
            button_frame, text="Cancelar", fg_color="#6B7280", hover_color="#4B5563", command=self._cancel
        )
        cancel_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        confirm_button = ctk.CTkButton(button_frame, text="Usar esta respuesta", command=self._confirm)
        confirm_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(50, self.focus_force)

    def _confirm(self) -> None:
        answer = self.answer_var.get().strip()
        if not answer:
            messagebox.showwarning("Aclaracion requerida", "Escriba una respuesta o use Si/No antes de continuar.")
            return
        self.result = answer
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class OracleReviewWindow(ctk.CTkToplevel):
    """
    Fase 3B - REVISION DE ORACLES: tabla de los 32 Oracles para la aprobacion formal del
    investigador. Nunca edita un Oracle; solo muestra, aprueba uno a uno o aprueba en masa los que
    no tienen review_items abiertos (con confirmacion explicita).
    """

    COLUMNS = ("caso", "titulo", "complejidad", "runtime", "review", "validacion", "estado")

    def __init__(self, app: "VozLLMPLCGUI") -> None:
        super().__init__(app)
        self.app = app
        self.title("Revision de Oracles")
        self.geometry("1100x620")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.summary_var = tk.StringVar(value="")
        ctk.CTkLabel(self, textvariable=self.summary_var, justify="left", anchor="w").grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")

        container = ctk.CTkFrame(self)
        container.grid(row=1, column=0, padx=14, pady=4, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(container, columns=self.COLUMNS, show="headings", selectmode="browse")
        headings = {"caso": ("Caso", 60), "titulo": ("Titulo", 420), "complejidad": ("Complejidad", 90), "runtime": ("Runtime", 200),
                    "review": ("Review items", 90), "validacion": ("Validacion", 90), "estado": ("Estado", 150)}
        for column, (label, width) in headings.items():
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, padx=14, pady=(6, 14), sticky="ew")
        buttons.grid_columnconfigure((0, 1, 2, 3), weight=1)
        ctk.CTkButton(buttons, text="VER RESUMEN", command=self.show_summary).grid(row=0, column=0, padx=4, sticky="ew")
        ctk.CTkButton(buttons, text="VER DETALLE", command=self.show_detail).grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkButton(buttons, text="APROBAR", command=self.approve_selected).grid(row=0, column=2, padx=4, sticky="ew")
        ctk.CTkButton(buttons, text="APROBAR TODOS SIN REVIEW_ITEMS", command=self.approve_all_clean).grid(row=0, column=3, padx=4, sticky="ew")
        self.refresh()

    def refresh(self) -> None:
        report = oracle_review.build_validation_report(self.app.project_root)
        self.report = report
        for item in self.tree.get_children():
            self.tree.delete(item)
        for entry in report["oracles"]:
            validation = "OK" if not entry["errors"] else f"{len(entry['errors'])} error(es)"
            self.tree.insert("", "end", iid=entry["case_id"], values=(
                entry["case_id"], entry.get("title") or "", entry.get("complexity") or "",
                entry["runtime_support"], len(entry["review_items"]), validation, f"{entry['status']} v{entry['version']}"))
        summary = report["summary"]
        total = summary["total_oracles"]
        self.summary_var.set(
            f"{summary['schema_valid']} / {total} schema valid   ·   {summary['without_review_items']} / {total} sin review_items   ·   "
            f"{summary['discrete_executable'].replace('/', ' / ')} discretos ejecutables   ·   "
            f"{summary['pid_executable'].replace('/', ' / ')} PID ejecutables actualmente   ·   "
            f"{summary['formal']} aprobados   ·   {len(summary['ready_for_human_approval'])} listos para aprobacion"
            + (f"   ·   FALTAN: {', '.join(report['missing_ids'])}" if report["missing_ids"] else "")
        )

    def _selected(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Revision de Oracles", "Seleccione un Oracle de la tabla.", parent=self)
            return None
        return selection[0]

    def show_summary(self) -> None:
        window = ctk.CTkToplevel(self)
        window.title("Resumen de Oracles")
        window.geometry("900x700")
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(0, weight=1)
        textbox = ctk.CTkTextbox(window, wrap="word")
        textbox.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")
        textbox.insert("1.0", oracle_review.build_summary_markdown(self.app.project_root))
        textbox.configure(state="disabled")

    def show_detail(self) -> None:
        case_id = self._selected()
        if case_id:
            try:
                OracleViewerWindow(self.app, oracle_schema.load_oracle(self.app.project_root, case_id))
            except oracle_schema.OracleError as error:
                messagebox.showerror("Revision de Oracles", f"{error.code}: {error.detail}", parent=self)

    def approve_selected(self) -> None:
        case_id = self._selected()
        if case_id and self.app.approve_oracle_interactive(case_id, parent=self):
            self._after_approval()

    def approve_all_clean(self) -> None:
        report = oracle_review.build_validation_report(self.app.project_root)
        candidates = [e["case_id"] for e in report["oracles"]
                      if e["status"] not in oracle_schema.FORMAL_STATUSES and not e["review_items"] and not e["errors"]]
        if not candidates:
            messagebox.showinfo("Revision de Oracles", "No hay Oracles en borrador sin review_items abiertos.", parent=self)
            return
        if not messagebox.askyesno(
            "Aprobacion masiva",
            f"Se aprobaran y CONGELARAN {len(candidates)} Oracles sin review_items abiertos:\n{', '.join(candidates)}\n\n"
            f"\"{oracle_review.MASS_APPROVAL_CONFIRMATION}\"\n\n¿Confirma esta declaracion?", parent=self
        ):
            return
        reviewer = simpledialog.askstring("Aprobacion masiva", "Identificador del investigador que aprueba:", parent=self)
        if not reviewer or not reviewer.strip():
            return
        try:
            outcome = oracle_review.approve_all_without_review_items(
                self.app.project_root, reviewer, oracle_review.MASS_APPROVAL_CONFIRMATION)
        except (oracle_schema.OracleError, ValueError) as error:
            messagebox.showerror("Aprobacion masiva", str(error), parent=self)
            return
        self.app._log(f"[ORACLE] Aprobacion masiva por {reviewer}: {', '.join(outcome['approved'])}")
        messagebox.showinfo(
            "Aprobacion masiva",
            f"Aprobados: {', '.join(outcome['approved']) or '-'}\n"
            f"Con review_items (no aprobados): {', '.join(outcome['skipped_review_items']) or '-'}", parent=self)
        self._after_approval()

    def _after_approval(self) -> None:
        oracle_review.write_validation_report(self.app.project_root, oracle_review.build_validation_report(self.app.project_root))
        oracle_review.write_summary_markdown(self.app.project_root)
        oracle_review.write_capability_gaps_report(self.app.project_root)
        self.refresh()
        self.app._refresh_oracle_status()


class OracleViewerWindow(ctk.CTkToplevel):
    """VER ORACLE: contenido, hash y puntos REVIEW_REQUIRED. Solo lectura: la GUI nunca edita Oracles."""

    def __init__(self, app: "VozLLMPLCGUI", oracle: dict[str, Any]) -> None:
        super().__init__(app)
        approval = oracle.get("approval") or {}
        self.title(f"Oracle {oracle.get('oracle_id')} v{approval.get('version')} - {approval.get('status')}")
        self.geometry("760x640")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        pending = oracle_schema.open_review_items(oracle)
        header = (
            f"{oracle.get('title')}\n"
            f"Estado: {approval.get('status')}   ·   Version: {approval.get('version')}   ·   "
            f"Hash: {oracle_schema.compute_oracle_hash(oracle)[:16]}...\n"
            f"Aprobado por: {approval.get('approved_by') or '-'}   ·   {approval.get('approved_at') or '-'}\n"
            + (f"Puntos REVIEW_REQUIRED abiertos: {len(pending)}" if pending else "Sin puntos REVIEW_REQUIRED abiertos.")
        )
        ctk.CTkLabel(self, text=header, justify="left", anchor="w").grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")
        textbox = ctk.CTkTextbox(self, wrap="none")
        textbox.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")
        textbox.insert("1.0", json.dumps(oracle, indent=2, ensure_ascii=False))
        textbox.configure(state="disabled")


class RuntimeIOTestWindow(ctk.CTkToplevel):
    """
    Fase 2B - PRUEBA DE I/O (herramienta tecnica, NO Oracle). Escribe ENTRADAS BOOL y lee
    salidas BOOL del programa actual en PLCSIM Advanced, con readback y restauracion de entradas.
    Solo se abre si target == PLCSIM_ADVANCED, Runtime conectado, CPU RUN y hay programa valido.
    """

    def __init__(
        self,
        app: "VozLLMPLCGUI",
        program: dict[str, Any],
        target_type: str,
        runtime_report: dict[str, Any],
        report_dir: Path,
        trial_directory: Path | None
    ) -> None:
        super().__init__(app)
        self.app = app
        self.program = program
        self.target_type = target_type
        self.report_dir = report_dir
        self.trial_directory = trial_directory
        self.session = plcsim_runtime_io.RuntimeIOSession(program, target_type, runtime_report, app.project_root)
        self._queue: queue.Queue = queue.Queue()
        self._busy = False
        self._closing = False
        self._last_smoke_report: dict[str, Any] | None = None

        self.title("Prueba de I/O - PLCSIM Advanced")
        self.geometry("520x560")
        self.grid_columnconfigure(0, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.close)

        source = program.get("source")
        source_text = f"snapshot del ensayo {program.get('trial_id')}" if source == "snapshot" else "variables.json del programa descargado"
        header = (
            "MODO SIMULACIÓN\n"
            f"{self.session.config['instance_name']}   ·   CPU {runtime_report.get('cpu_state')}\n"
            f"Señales: {source_text}"
        )
        ctk.CTkLabel(self, text=header, justify="left", font=app.button_font).grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")

        inputs = [signal["name"] for signal in plcsim_runtime_io.bool_inputs(program)]
        outputs = [signal["name"] for signal in plcsim_runtime_io.bool_outputs(program)]

        input_frame = ctk.CTkFrame(self, corner_radius=10)
        input_frame.grid(row=1, column=0, padx=16, pady=6, sticky="ew")
        input_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(input_frame, text="Entrada").grid(row=0, column=0, padx=10, pady=8, sticky="w")
        self.input_var = tk.StringVar(value=inputs[0] if inputs else "")
        self.input_menu = ctk.CTkOptionMenu(input_frame, variable=self.input_var, values=inputs or ["(sin entradas BOOL)"])
        self.input_menu.grid(row=0, column=1, padx=10, pady=8, sticky="ew")
        ctk.CTkLabel(input_frame, text="Valor").grid(row=1, column=0, padx=10, pady=4, sticky="w")
        self.value_var = tk.StringVar(value="OFF")
        ctk.CTkSegmentedButton(input_frame, values=["OFF", "ON"], variable=self.value_var).grid(row=1, column=1, padx=10, pady=4, sticky="w")
        self.write_button = ctk.CTkButton(input_frame, text="ESCRIBIR", command=self.write_input)
        self.write_button.grid(row=2, column=0, columnspan=2, padx=10, pady=6, sticky="ew")
        self.readback_var = tk.StringVar(value="Readback: -")
        ctk.CTkLabel(input_frame, textvariable=self.readback_var).grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
        if not inputs:
            self.write_button.configure(state="disabled")

        output_frame = ctk.CTkFrame(self, corner_radius=10)
        output_frame.grid(row=2, column=0, padx=16, pady=6, sticky="ew")
        output_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(output_frame, text="Salida").grid(row=0, column=0, padx=10, pady=8, sticky="w")
        self.output_var = tk.StringVar(value=outputs[0] if outputs else "")
        self.output_menu = ctk.CTkOptionMenu(output_frame, variable=self.output_var, values=outputs or ["(sin salidas BOOL)"])
        self.output_menu.grid(row=0, column=1, padx=10, pady=8, sticky="ew")
        self.read_button = ctk.CTkButton(output_frame, text="LEER", command=self.read_output)
        self.read_button.grid(row=1, column=0, columnspan=2, padx=10, pady=6, sticky="ew")
        self.output_value_var = tk.StringVar(value="Valor observado: -")
        ctk.CTkLabel(output_frame, textvariable=self.output_value_var).grid(row=2, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
        if not outputs:
            self.read_button.configure(state="disabled")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, padx=16, pady=6, sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)
        self.restore_button = ctk.CTkButton(actions, text="RESTAURAR ENTRADAS", command=self.restore_inputs)
        self.restore_button.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.smoke_button = ctk.CTkButton(actions, text="PRUEBA START/STOP", command=self.run_smoke_test)
        self.smoke_button.grid(row=0, column=1, padx=(4, 0), sticky="ew")

        self.status_var = tk.StringVar(value="Listo. Las entradas escritas se restauran a OFF al cerrar.")
        ctk.CTkLabel(self, textvariable=self.status_var, wraplength=480, justify="left").grid(row=4, column=0, padx=16, pady=(6, 14), sticky="w")
        self._buttons = [self.write_button, self.read_button, self.restore_button, self.smoke_button]
        self._inputs_available = bool(inputs)
        self._outputs_available = bool(outputs)

    # -- ejecucion en segundo plano (hilo "plcsim-io") -------------------------------------

    def _run(self, description: str, work: Any, on_done: Any) -> None:
        if self._busy:
            return
        self._busy = True
        for button in self._buttons:
            button.configure(state="disabled")
        self.status_var.set(description + "...")

        def _worker() -> None:
            try:
                self._queue.put(("ok", work()))
            except plcsim_runtime_io.RuntimeIOError as error:
                self._queue.put(("io_error", error))
            except Exception as error:  # pragma: no cover - proceso externo
                self._queue.put(("error", error))

        threading.Thread(target=_worker, name="plcsim-io", daemon=True).start()
        self._poll(on_done)

    def _poll(self, on_done: Any) -> None:
        try:
            outcome, payload = self._queue.get_nowait()
        except queue.Empty:
            self.after(150, lambda: self._poll(on_done))
            return
        self._busy = False
        self.write_button.configure(state="normal" if self._inputs_available else "disabled")
        self.read_button.configure(state="normal" if self._outputs_available else "disabled")
        self.restore_button.configure(state="normal")
        self.smoke_button.configure(state="normal")
        if outcome == "ok":
            on_done(payload)
        else:
            code = getattr(payload, "code", "PLCSIM_RUNTIME_ERROR")
            self.status_var.set(f"{code}: {getattr(payload, 'detail', payload)}")
            self.app._log(f"[PLCSIM IO] {code}: {getattr(payload, 'detail', payload)}")
            if self._closing:
                self._finish_close()

    @staticmethod
    def _on_off(value: Any) -> str:
        return "?" if value is None else ("ON" if value else "OFF")

    # -- acciones --------------------------------------------------------------------------

    def write_input(self) -> None:
        name, value = self.input_var.get(), self.value_var.get() == "ON"
        self.app._log(f"[PLCSIM IO] Escribir {name} = {self._on_off(value)}")

        def _done(result: dict[str, Any]) -> None:
            self.readback_var.set(
                f"Readback {result['name']} ({result['address']}): {self._on_off(result.get('readback'))}"
                f"   ·   pedido {self._on_off(result['requested_value'])}   ·   {'OK' if result['match'] else 'NO COINCIDE'}"
            )
            self.status_var.set(result["status"] if result["status"] != plcsim_runtime_io.SUCCESS else "Escritura verificada.")
            self.app._log(f"[PLCSIM IO] {name}: readback {self._on_off(result.get('readback'))} match={result['match']} ({result['status']})")

        self._run(f"Escribiendo {name}", lambda: self.session.write_input(name, value), _done)

    def read_output(self) -> None:
        name = self.output_var.get()

        def _done(result: dict[str, Any]) -> None:
            value = result["values"][0].get("value") if result["values"] else None
            self.output_value_var.set(f"Valor observado {name}: {self._on_off(value)}")
            self.status_var.set(result["status"] if result["status"] != plcsim_runtime_io.SUCCESS else "Lectura correcta.")
            self.app._log(f"[PLCSIM IO] Leer {name} = {self._on_off(value)} ({result['status']})")

        self._run(f"Leyendo {name}", lambda: self.session.read_signals([name]), _done)

    def restore_inputs(self) -> None:
        def _done(result: dict[str, Any]) -> None:
            if result["status"] == plcsim_runtime_io.SUCCESS:
                self.status_var.set("Entradas restauradas a OFF: " + (", ".join(result["restored"]) or "(ninguna pendiente)"))
            else:
                self.status_var.set(f"{plcsim_runtime_io.ERROR_CLEANUP_FAILED}: pendientes {', '.join(result.get('pending', []))}")
                messagebox.showerror("Prueba de I/O", f"{plcsim_runtime_io.ERROR_CLEANUP_FAILED}\n\nNo se pudieron restaurar: {', '.join(result.get('pending', []))}", parent=self)
            self.app._log(f"[PLCSIM IO] Restaurar entradas: {result['status']}")
            if self._closing:
                self._finish_close()

        self._run("Restaurando entradas", self.session.restore_inputs, _done)

    def run_smoke_test(self) -> None:
        if not messagebox.askyesno(
            "Prueba START/STOP",
            "Se escribiran entradas en PLCSIM Advanced (Start, Stop) y se leera la salida.\n"
            "Al terminar todas las entradas vuelven a OFF.\n\n¿Continuar?",
            parent=self
        ):
            return

        def _work() -> dict[str, Any]:
            return plcsim_runtime_io.run_runtime_io_smoke_test(
                self.program, self.target_type, self.session.runtime_report, self.app.project_root, report_dir=self.report_dir
            )

        def _done(report: dict[str, Any]) -> None:
            self._last_smoke_report = report
            sequence = " → ".join(self._on_off(value) for value in report.get("output_sequence", []))
            self.status_var.set(
                f"runtime_io_test = {report['runtime_io_test']}   ·   {report.get('roles', {}).get('output')}: {sequence}\n"
                f"Reporte: {report.get('report_path', '-')}"
            )
            self.app._log(f"[PLCSIM IO] Prueba START/STOP: {report['runtime_io_test']} (salida {sequence})")
            self.app._record_runtime_io_report(self.trial_directory, report)

        self._run("Prueba START/STOP", _work, _done)

    def close(self) -> None:
        if self._busy:
            return
        self._closing = True
        if self.session.touched_inputs:
            self.restore_inputs()
            return
        self._finish_close()

    def _finish_close(self) -> None:
        if self.session.writes or self.session.reads:
            report = self.session.build_report()
            report["report_path"] = str(plcsim_runtime_io.write_io_report(self.report_dir, report))
            self.app._record_runtime_io_report(self.trial_directory, report)
        self.app._io_test_window = None
        self.destroy()


class VozLLMPLCGUI(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.project_root = get_project_root()
        self.config_dir = self.project_root / "config"
        self.docs_dir = self.project_root / "docs"
        self.generated_dir = self.project_root / "generated_code"
        self.history_storage_path = self.generated_dir / "gui_history.json"
        self.env_path = get_env_path(self.project_root)
        self.intents_catalog_path = self.config_dir / "intents_catalog.json"
        self.safety_rules_path = self.config_dir / "safety_rules.json"

        try:
            startup_safety_rules = load_json_file(self.safety_rules_path)
        except (FileNotFoundError, ValueError):
            startup_safety_rules = {}
        self.plc_maps_dir = ensure_plc_maps_library(self.project_root, startup_safety_rules)
        self.io_map_path = resolve_active_map_path(self.project_root)
        self.io_variable_metadata: dict[str, dict[str, Any]] = {}
        self._map_summaries_by_name: dict[str, dict[str, Any]] = {}
        self._profiles_by_name: dict[str, dict[str, Any]] = {}
        self.active_map_dirty = False
        self.map_sync_status_var = tk.StringVar(value="Mapa PLC: -")

        self.title("Voz-LLM-PLC Agent")
        self.min_window_width = 1440
        self.min_window_height = 860
        self.minsize(self.min_window_width, self.min_window_height)
        self.geometry("1600x940")

        resolved_start_mode = resolve_parser_mode()
        parser_ui_map = {
            "rule_based": "Reglas",
            "llm": "LLM",
            "hybrid": "Hibrido"
        }
        # OpenPLC y CODESYS quedan aislados de la GUI (ver docs/08_decisiones_tecnicas.md).
        # El backend y los adaptadores permanecen intactos para una reintegracion futura.
        self.platform_var = tk.StringVar(value="Siemens TIA V18")
        self.parser_mode_var = tk.StringVar(value=parser_ui_map.get(resolved_start_mode, "LLM"))
        self.active_map_var = tk.StringVar(value="")
        self.active_profile_var = tk.StringVar(value=GENERAL_PROFILE_LABEL)
        self.active_profile_id: str | None = None
        self.profile_status_var = tk.StringVar(value="")

        self.work_mode_var = tk.StringVar(value="Normal")
        self.active_trial: dict[str, Any] | None = None
        self._experiment_profiles_by_case: dict[str, dict[str, Any]] = {}
        self.experiment_group_var = tk.StringVar(value="Discreto D01-D20")
        self.experiment_case_var = tk.StringVar(value="")
        self.experiment_condition_var = tk.StringVar(value=CONDITIONS["C1"]["label"])
        self.experiment_variant_var = tk.StringVar(value="V1")
        self.experiment_speaker_var = tk.StringVar(value="P01")
        self.experiment_noise_var = tk.StringVar(value=NOISE_LEVEL_LABELS["none"])
        self.experiment_environment_var = tk.StringVar(value=ENVIRONMENT_LABELS["simulation"])
        self.experiment_status_var = tk.StringVar(value="")
        self.experiment_stage_var = tk.StringVar(value="")
        self._experiment_stage_states: dict[str, str] = {}
        self.experiment_next_label_var = tk.StringVar(value="")
        self.experiment_variant_command_var = tk.StringVar(value="")
        self._active_variant_command_text: str = ""
        self._last_experiment_condition_code: str | None = None
        self.manual_result_var = tk.StringVar(value=PHYSICAL_RESULT_OPTIONS[0])
        self.manual_safety_var = tk.StringVar(value="No")
        self.manual_error_var = tk.StringVar(value=NO_ERROR_LABEL)
        self.manual_observations_var = tk.StringVar(value="")
        self._map_sync_worker_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._map_sync_worker_active = False
        self.status_var = tk.StringVar(value="Listo")
        self.llm_status_var = tk.StringVar(value="LLM en modo demo local")
        self.save_voice_evidence_var = tk.BooleanVar(value=False)
        self.history_records: list[dict[str, Any]] = []
        self.history_item_map: dict[str, dict[str, Any]] = {}
        self.history_record_keys: set[str] = set()
        self.current_result_snapshot: dict[str, Any] | None = None
        self.pending_semantic_output: dict[str, Any] | None = None
        self.pending_runtime_config: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None = None
        # Resumen de la ultima configuracion automatica de mapa (seccion 14) para un comando MIXTO
        # (mapa + logica): no se muestra en un messagebox intermedio que detenga el flujo - se
        # registra en consola y se reserva para incorporarse al dialogo de confirmacion de
        # generate_package(), el siguiente punto de confirmacion humana natural en el pipeline.
        self._last_map_config_summary: str | None = None
        # Solo "CARGAR PROGRAMA AL PLC" queda habilitado mientras esto apunte al paquete de la
        # ULTIMA compilacion Siemens aprobada; cualquier nuevo comando procesado lo invalida.
        self._last_compiled_package_dir: Path | None = None
        # Distinto de `_last_compiled_package_dir`: ese se limpia en CADA fallo (correctamente -
        # es el guardian de 'CARGAR PROGRAMA AL PLC', que nunca debe ofrecer descargar un programa
        # viejo tras un intento fallido). Este campo es solo informativo/de reporte: conserva el
        # ultimo paquete que SI compilo con exito en TIA, sin importar cuantos comandos fallidos
        # vengan despues (comando A compila, B falla -> last_successful_tia_package sigue siendo A).
        self._last_successful_tia_package_dir: Path | None = None
        self._download_worker_active = False
        self._download_worker_queue: queue.Queue = queue.Queue()
        # Proposito de la descarga en curso (normal = boton CARGAR, experiment = auto-descarga
        # del ensayo a PLCSIM) y el paquete EXACTO que se esta descargando.
        self._download_purpose: str = DOWNLOAD_PURPOSE_NORMAL
        self._download_package_dir: Path | None = None
        self._compile_started_perf: float | None = None
        # Fase 2A - PLCSIM Advanced Runtime API (solo lectura). CONFIGURADO (download_targets)
        # y CONECTADO (Runtime API) se muestran por separado; RUN solo si la API lo confirma.
        self._runtime_worker_active = False
        self._runtime_worker_queue: queue.Queue = queue.Queue()
        self._runtime_callbacks: list[Any] = []
        self._last_runtime_report: dict[str, Any] | None = None
        # Fase 2B: programa realmente descargado a PLCSIM (snapshot del ensayo o variables.json)
        # del que la PRUEBA DE I/O toma sus senales, y la ventana abierta (si la hay).
        self._io_program_context: dict[str, Any] | None = None
        self._io_test_window: RuntimeIOTestWindow | None = None
        # Fase 3A: Oracle Runner (hilo 'oracle-runner') y estado del Oracle del caso seleccionado.
        self._oracle_worker_active = False
        self._oracle_worker_queue: queue.Queue = queue.Queue()
        self._oracle_run_context: dict[str, Any] | None = None
        self.oracle_status_var = tk.StringVar(value="Oracle: -")
        # Indicador simple de I/O del ensayo: Asignando... -> Resueltas -> Congeladas / Error.
        self._experiment_io_text = ""
        self.plc_config_var = tk.StringVar(value="Configurado: -")
        self.plc_runtime_var = tk.StringVar(value="Runtime: NO VERIFICADO")
        self.plc_cpu_var = tk.StringVar(value="CPU: -")
        self.plc_network_var = tk.StringVar(value="Red: -")
        self.voice_audio_path: Path | None = None
        self.voice_transcription: dict[str, Any] | None = None
        self._voice_worker_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._voice_worker_active = False
        self._voice_device_index_by_label: dict[str, int | None] = {}
        self._voice_level_poll_job: str | None = None
        self._tia_worker_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._tia_worker_active = False
        self._responsive_job: str | None = None
        self.llm_client = PLCInterpretationLLMClient()
        self.speech_recognizer = SpeechRecognizer(
            llm_client=self.llm_client,
            save_evidence=self.save_voice_evidence_var.get()
        )
        # "Proyecto OpenPLC" y "Proyecto CODESYS" quedan fuera de la ventana de
        # resultados visible mientras el enfoque es TIA Openness (ver
        # docs/08_decisiones_tecnicas.md). Sus textboxes se siguen creando, solo
        # que sobre un contenedor oculto, para no tocar el codigo que ya escribe
        # en ellos y poder reintegrarlos agregandolos de nuevo a esta lista.
        self.result_tab_names = [
            "Voz",
            "Interpretacion",
            "Comparacion reglas/LLM",
            "Parametros",
            "Representacion intermedia",
            "POU",
            "Tarea",
            "Proyecto Siemens",
            "TIA Openness",
            "Casos de prueba",
            "Verificacion",
            "Archivos",
            "Historial",
            "Historial experimental"
        ]
        self.result_tab_labels = {
            "Voz": "Voz",
            "Interpretacion": "Intencion",
            "Comparacion reglas/LLM": "Reglas/LLM",
            "Parametros": "Parametros",
            "Representacion intermedia": "IR",
            "POU": "POU",
            "Tarea": "Tarea",
            "Proyecto OpenPLC": "OpenPLC",
            "Proyecto CODESYS": "CODESYS",
            "Proyecto Siemens": "Siemens",
            "TIA Openness": "Openness",
            "Casos de prueba": "Pruebas",
            "Verificacion": "Verificacion",
            "Archivos": "Archivos",
            "Historial": "Historial",
            "Historial experimental": "Experimentos"
        }
        self.active_result_tab = "Voz"
        self.result_tab_window_start = 0
        self.result_tab_window_size = 4
        self.result_tab_button_height = 32
        self.result_nav_button_width = 36

        self._build_theme_tokens()

        ensure_generated_dirs(self.generated_dir)
        self.io_variables = load_io_map_variables(self.io_map_path)
        self._load_active_map_metadata_shadow()

        self._configure_grid()
        self._configure_treeview_style()
        self._build_layout()
        self._bind_responsive_events()
        self._load_io_map_table()
        self._refresh_map_selector_values()
        self._refresh_profile_selector_values()
        self._refresh_experiment_case_selector()
        self._refresh_experiment_history_tab()
        self._clear_results()
        self._load_history_state()
        self._refresh_llm_client_status()
        self._refresh_input_devices()
        self._refresh_voice_button_states()
        self._set_status("Listo")
        self._log("Interfaz grafica inicializada.")
        self._log(f"Modo parser actual: {resolve_parser_mode()}.")
        self._log(f"Archivo de configuracion LLM: {self.env_path}")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._apply_responsive_layout)

    def _build_theme_tokens(self) -> None:
        self.panel_title_font = ctk.CTkFont(family="Segoe UI", size=24, weight="bold")
        self.section_label_font = ctk.CTkFont(family="Segoe UI", size=14, weight="bold")
        self.body_font = ctk.CTkFont(family="Segoe UI", size=12)
        self.button_font = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        self.tab_font = ctk.CTkFont(family="Segoe UI", size=11, weight="bold")
        self.text_font = ctk.CTkFont(family="Consolas", size=12)
        self.console_font = ctk.CTkFont(family="Consolas", size=12)
        self.banner_font = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        self.status_font = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")

    def _configure_grid(self) -> None:
        self.grid_columnconfigure(0, weight=6, minsize=500)
        self.grid_columnconfigure(1, weight=6, minsize=460)
        self.grid_columnconfigure(2, weight=8, minsize=540)
        self.grid_rowconfigure(0, weight=8)
        self.grid_rowconfigure(1, weight=2, minsize=180)

    def _configure_treeview_style(self) -> None:
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", rowheight=30, font=("Segoe UI", 11))
        style.configure("Treeview.Heading", font=("Segoe UI", 11, "bold"))

    def _bind_responsive_events(self) -> None:
        self.bind("<Configure>", self._on_window_configure)

    def _on_window_configure(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._responsive_job is not None:
            self.after_cancel(self._responsive_job)
        self._responsive_job = self.after(80, self._apply_responsive_layout)

    def _apply_responsive_layout(self) -> None:
        self._responsive_job = None
        width = max(self.winfo_width(), self.min_window_width)

        if width >= 1820:
            metrics = {
                "main_weights": (6, 6, 8),
                "main_minsizes": (500, 470, 560),
                "panel_title": 27,
                "section_label": 15,
                "body": 13,
                "button": 13,
                "tab": 11,
                "text": 12,
                "button_height": 34,
                "tab_height": 30,
                "tree_rowheight": 26,
                "console_height": 155,
                "status_width": 118,
                "io_table_minsize": 215,
                "command_box_minsize": 165,
                "results_box_minsize": 255,
                "visible_result_tabs": 5
            }
        elif width >= 1600:
            metrics = {
                "main_weights": (6, 6, 8),
                "main_minsizes": (490, 460, 540),
                "panel_title": 25,
                "section_label": 14,
                "body": 12,
                "button": 12,
                "tab": 10,
                "text": 12,
                "button_height": 32,
                "tab_height": 29,
                "tree_rowheight": 24,
                "console_height": 150,
                "status_width": 110,
                "io_table_minsize": 205,
                "command_box_minsize": 155,
                "results_box_minsize": 240,
                "visible_result_tabs": 4
            }
        else:
            metrics = {
                "main_weights": (6, 5, 7),
                "main_minsizes": (480, 430, 520),
                "panel_title": 23,
                "section_label": 13,
                "body": 11,
                "button": 11,
                "tab": 10,
                "text": 11,
                "button_height": 30,
                "tab_height": 30,
                "tree_rowheight": 22,
                "console_height": 140,
                "status_width": 102,
                "io_table_minsize": 190,
                "command_box_minsize": 145,
                "results_box_minsize": 220,
                "visible_result_tabs": 4
            }

        self.grid_columnconfigure(0, weight=metrics["main_weights"][0], minsize=metrics["main_minsizes"][0])
        self.grid_columnconfigure(1, weight=metrics["main_weights"][1], minsize=metrics["main_minsizes"][1])
        self.grid_columnconfigure(2, weight=metrics["main_weights"][2], minsize=metrics["main_minsizes"][2])
        self.left_panel.grid_rowconfigure(9, weight=1, minsize=metrics["io_table_minsize"])
        self.center_panel.grid_rowconfigure(2, weight=1, minsize=metrics["command_box_minsize"])
        self.right_panel.grid_rowconfigure(3, weight=1, minsize=metrics["results_box_minsize"])
        self.result_tab_window_size = metrics["visible_result_tabs"]
        self.result_tab_button_height = metrics["button_height"]
        self.result_nav_button_width = max(metrics["button_height"] + 4, 36)

        self.panel_title_font.configure(size=metrics["panel_title"])
        self.section_label_font.configure(size=metrics["section_label"])
        self.body_font.configure(size=metrics["body"])
        self.button_font.configure(size=metrics["button"])
        self.tab_font.configure(size=metrics["tab"])
        self.text_font.configure(size=metrics["text"])
        self.console_font.configure(size=metrics["text"])
        self.banner_font.configure(size=metrics["body"])
        self.status_font.configure(size=metrics["body"])

        for label in (self.left_title_label, self.center_title_label, self.right_title_label, self.console_title_label):
            label.configure(font=self.panel_title_font)

        for label in (self.platform_label_widget, self.parser_label_widget, self.table_label, self.status_label):
            label.configure(font=self.section_label_font)

        self.platform_selector.configure(height=metrics["button_height"], font=self.body_font, dropdown_font=self.body_font)
        self.parser_selector.configure(height=metrics["button_height"], font=self.body_font, dropdown_font=self.body_font)
        self.llm_status_banner.configure(font=self.body_font)
        self.status_badge.configure(font=self.status_font, width=metrics["status_width"])
        self.validation_banner.configure(font=self.banner_font)
        self.export_selector.configure(height=metrics["button_height"], font=self.body_font, dropdown_font=self.body_font)

        for button in self.llm_action_buttons + self.left_action_buttons + self.management_buttons + self.command_buttons + [
            self.export_txt_button,
            self.export_bundle_button,
            self.view_history_button
        ]:
            button.configure(height=metrics["button_height"], font=self.button_font)

        self.command_textbox.configure(font=self.text_font)
        self.console_textbox.configure(font=self.console_font, height=metrics["console_height"])

        for textbox in self.result_textboxes:
            textbox.configure(font=self.text_font)

        self.results_tabs.configure(segmented_button_font=self.tab_font)
        self.results_prev_button.configure(width=self.result_nav_button_width, height=metrics["button_height"], font=self.button_font)
        self.results_next_button.configure(width=self.result_nav_button_width, height=metrics["button_height"], font=self.button_font)
        self.results_nav_status_label.configure(font=self.body_font)
        self._hide_default_results_tab_bar()
        self._refresh_results_navigation()

        style = ttk.Style()
        style.configure("Treeview", rowheight=metrics["tree_rowheight"], font=("Segoe UI", max(metrics["body"] - 2, 11)))
        style.configure("Treeview.Heading", font=("Segoe UI", max(metrics["body"] - 1, 11), "bold"))

        self._update_tree_columns()

    def _update_tree_columns(self) -> None:
        left_panel_width = max(self.left_panel.winfo_width(), 520)
        usable_width = max(left_panel_width - 80, 560)
        column_widths = {
            "name": max(int(usable_width * 0.14), 95),
            "class": max(int(usable_width * 0.11), 80),
            "type": max(int(usable_width * 0.10), 78),
            "location": max(int(usable_width * 0.14), 92),
            "initial_value": max(int(usable_width * 0.13), 95),
            "description": max(int(usable_width * 0.24), 150),
            "state": max(int(usable_width * 0.10), 80)
        }

        for column in IO_TREE_COLUMNS:
            self.io_tree.column(column, width=column_widths[column], minwidth=70, stretch=True)

        history_width = max(self.right_panel.winfo_width(), 520) - 90
        history_columns = {
            "fecha": max(int(history_width * 0.18), 120),
            "comando": max(int(history_width * 0.38), 200),
            "intencion": max(int(history_width * 0.18), 130),
            "plataforma": max(int(history_width * 0.14), 100),
            "validacion": max(int(history_width * 0.12), 90)
        }
        for column, width in history_columns.items():
            self.history_tree.column(column, width=width, minwidth=85, stretch=True)

    def _build_layout(self) -> None:
        self.left_panel = ctk.CTkScrollableFrame(
            self,
            corner_radius=18,
            orientation="vertical"
        )
        self.left_panel.grid(row=0, column=0, padx=(18, 10), pady=(18, 10), sticky="nsew")
        self.left_panel.grid_columnconfigure(0, weight=1)

        self.center_panel = ctk.CTkScrollableFrame(
            self,
            corner_radius=18,
            orientation="vertical"
        )
        self.center_panel.grid(row=0, column=1, padx=10, pady=(18, 10), sticky="nsew")
        self.center_panel.grid_columnconfigure(0, weight=1)

        self.right_panel = ctk.CTkFrame(self, corner_radius=18)
        self.right_panel.grid(row=0, column=2, padx=(10, 18), pady=(18, 10), sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(3, weight=1)

        self.console_panel = ctk.CTkFrame(self, corner_radius=18)
        self.console_panel.grid(row=1, column=0, columnspan=3, padx=18, pady=(0, 18), sticky="nsew")
        self.console_panel.grid_columnconfigure(0, weight=1)
        self.console_panel.grid_rowconfigure(1, weight=1)

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()
        self._build_console_panel()

    def _build_left_panel(self) -> None:
        self.left_title_label = ctk.CTkLabel(self.left_panel, text="Configuracion", font=self.panel_title_font)
        self.left_title_label.grid(row=0, column=0, padx=18, pady=(18, 12), sticky="w")

        self.platform_label_widget = ctk.CTkLabel(self.left_panel, text="Plataforma objetivo", font=self.section_label_font)
        self.platform_label_widget.grid(row=1, column=0, padx=18, pady=(0, 8), sticky="w")

        self.platform_selector = ctk.CTkOptionMenu(
            self.left_panel,
            variable=self.platform_var,
            values=["Siemens TIA V18"],
            state="disabled",
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.platform_selector.grid(row=2, column=0, padx=18, pady=(0, 10), sticky="ew")

        self.parser_label_widget = ctk.CTkLabel(self.left_panel, text="Modo de parser", font=self.section_label_font)
        self.parser_label_widget.grid(row=3, column=0, padx=18, pady=(0, 8), sticky="w")

        self.parser_selector = ctk.CTkOptionMenu(
            self.left_panel,
            variable=self.parser_mode_var,
            values=["Reglas", "LLM", "Hibrido"],
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.parser_selector.grid(row=4, column=0, padx=18, pady=(0, 10), sticky="ew")

        self.llm_status_banner = ctk.CTkLabel(
            self.left_panel,
            textvariable=self.llm_status_var,
            corner_radius=12,
            padx=12,
            pady=8,
            anchor="w",
            font=self.body_font
        )
        self.llm_status_banner.grid(row=5, column=0, padx=18, pady=(0, 10), sticky="ew")

        llm_actions_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        llm_actions_frame.grid(row=6, column=0, padx=18, pady=(0, 10), sticky="ew")
        llm_actions_frame.grid_columnconfigure(0, weight=1)
        llm_actions_frame.grid_columnconfigure(1, weight=1)

        self.llm_action_buttons: list[ctk.CTkButton] = []
        configure_llm_button = ctk.CTkButton(
            llm_actions_frame,
            text="Configurar API LLM",
            command=self.configure_llm_api,
            font=self.button_font
        )
        configure_llm_button.grid(row=0, column=0, padx=(0, 4), pady=0, sticky="ew")
        self.llm_action_buttons.append(configure_llm_button)

        test_llm_button = ctk.CTkButton(
            llm_actions_frame,
            text="Probar conexion",
            command=self.test_llm_connection,
            font=self.button_font
        )
        test_llm_button.grid(row=0, column=1, padx=(4, 0), pady=0, sticky="ew")
        self.llm_action_buttons.append(test_llm_button)

        tia_actions_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        tia_actions_frame.grid(row=7, column=0, padx=18, pady=(0, 8), sticky="ew")
        tia_actions_frame.grid_columnconfigure(0, weight=1)

        self.configure_tia_button = ctk.CTkButton(
            tia_actions_frame,
            text="Configurar TIA V18",
            command=self.configure_tia_openness,
            font=self.button_font
        )
        self.configure_tia_button.grid(row=0, column=0, sticky="ew")
        self._build_plc_connection_panel(tia_actions_frame)
        # "Diagnosticar Openness" e "Importar y compilar ultimo paquete Siemens" viven ahora
        # en Herramientas avanzadas (panel central) para no duplicar el flujo operativo.

        map_library_frame = ctk.CTkFrame(self.left_panel, corner_radius=12)
        map_library_frame.grid(row=8, column=0, padx=18, pady=(0, 8), sticky="ew")
        map_library_frame.grid_columnconfigure(0, weight=1)
        map_library_frame.grid_columnconfigure(1, weight=1)

        map_library_label = ctk.CTkLabel(map_library_frame, text="Mapa PLC activo", font=self.section_label_font)
        map_library_label.grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 4), sticky="w")

        self.map_selector = ctk.CTkOptionMenu(
            map_library_frame,
            variable=self.active_map_var,
            values=[""],
            command=self.on_active_map_selected,
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.map_selector.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")

        self.map_sync_status_label = ctk.CTkLabel(
            map_library_frame,
            textvariable=self.map_sync_status_var,
            anchor="w",
            font=self.body_font
        )
        self.map_sync_status_label.grid(row=2, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")

        map_crud_frame = ctk.CTkFrame(map_library_frame, fg_color="transparent")
        map_crud_frame.grid(row=3, column=0, columnspan=2, padx=8, pady=(0, 4), sticky="ew")
        map_crud_frame.grid_columnconfigure(0, weight=1)
        map_crud_frame.grid_columnconfigure(1, weight=1)

        self.new_map_button = ctk.CTkButton(map_crud_frame, text="Nuevo mapa", command=self.new_plc_map, font=self.button_font)
        self.new_map_button.grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        self.save_map_as_button = ctk.CTkButton(map_crud_frame, text="Guardar como...", command=self.save_plc_map_as, font=self.button_font)
        self.save_map_as_button.grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        self.delete_map_button = ctk.CTkButton(
            map_crud_frame,
            text="Eliminar mapa",
            fg_color="#C2410C",
            hover_color="#9A3412",
            command=self.delete_plc_map_active,
            font=self.button_font
        )
        self.delete_map_button.grid(row=1, column=0, padx=4, pady=2, sticky="ew")
        self.validate_map_button = ctk.CTkButton(map_crud_frame, text="Validar mapa", command=self.validate_plc_map, font=self.button_font)
        self.validate_map_button.grid(row=1, column=1, padx=4, pady=2, sticky="ew")

        map_tia_frame = ctk.CTkFrame(map_library_frame, fg_color="transparent")
        map_tia_frame.grid(row=4, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="ew")
        map_tia_frame.grid_columnconfigure(0, weight=1)
        map_tia_frame.grid_columnconfigure(1, weight=1)

        self.sync_map_button = ctk.CTkButton(map_tia_frame, text="Sincronizar con TIA", command=self.sync_plc_map_with_tia, font=self.button_font)
        self.sync_map_button.grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        self.import_map_button = ctk.CTkButton(map_tia_frame, text="Importar desde TIA", command=self.import_plc_map_from_tia, font=self.button_font)
        self.import_map_button.grid(row=0, column=1, padx=4, pady=2, sticky="ew")

        self.profile_selector_label = ctk.CTkLabel(map_library_frame, text="Contexto (Modo Normal)", font=self.section_label_font)
        self.profile_selector_label.grid(row=5, column=0, columnspan=2, padx=12, pady=(4, 4), sticky="w")

        self.profile_selector = ctk.CTkOptionMenu(
            map_library_frame,
            variable=self.active_profile_var,
            values=[GENERAL_PROFILE_LABEL],
            command=self.on_profile_selected,
            state="disabled",
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.profile_selector.grid(row=6, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")
        # El perfil ya no se elige manualmente: Normal siempre usa GENERAL, Experimentacion
        # lo resuelve automaticamente desde el caso Dxx seleccionado (_on_experiment_case_changed).

        self.profile_status_label = ctk.CTkLabel(
            map_library_frame,
            textvariable=self.profile_status_var,
            anchor="w",
            justify="left",
            font=self.body_font
        )
        self.profile_status_label.grid(row=7, column=0, columnspan=2, padx=12, pady=(0, 10), sticky="ew")

        action_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        action_frame.grid(row=9, column=0, padx=18, pady=(0, 8), sticky="ew")
        action_frame.grid_columnconfigure(0, weight=1)
        action_frame.grid_columnconfigure(1, weight=1)

        self.left_action_buttons: list[ctk.CTkButton] = []
        paired_buttons = [
            ("Abrir mapa I/O", self.open_io_map),
            ("Guardar mapa I/O", self.save_io_map),
            ("Agregar variable", self.add_variable),
            ("Editar variable", self.edit_variable),
            ("Bloquear variable", self.lock_selected_variable),
            ("Desbloquear variable", self.unlock_selected_variable)
        ]
        for index, (text, callback) in enumerate(paired_buttons):
            button = ctk.CTkButton(action_frame, text=text, command=callback, font=self.button_font)
            button.grid(row=index // 2, column=index % 2, padx=4, pady=4, sticky="ew")
            self.left_action_buttons.append(button)

        full_width_buttons = [
            ("Eliminar variable", self.delete_variable),
            ("Marcar como libre", self.mark_selected_variable_free)
        ]
        for offset, (text, callback) in enumerate(full_width_buttons):
            button = ctk.CTkButton(action_frame, text=text, command=callback, font=self.button_font)
            button.grid(row=3 + offset, column=0, columnspan=2, padx=4, pady=4, sticky="ew")
            self.left_action_buttons.append(button)

        self.open_full_map_button = ctk.CTkButton(
            action_frame,
            text="ABRIR MAPA I/O COMPLETO",
            command=self.open_full_io_map_window,
            font=self.button_font,
            fg_color="#1D4ED8",
            hover_color="#1E40AF"
        )
        self.open_full_map_button.grid(row=5, column=0, columnspan=2, padx=4, pady=(2, 4), sticky="ew")
        self.left_action_buttons.append(self.open_full_map_button)

        self.table_label = ctk.CTkLabel(self.left_panel, text="Mapa maestro PLC", font=self.section_label_font)
        self.table_label.grid(row=10, column=0, padx=18, pady=(2, 6), sticky="w")

        self.io_tree_container = ctk.CTkFrame(self.left_panel, corner_radius=12)
        self.io_tree_container.grid(row=11, column=0, padx=18, pady=(0, 8), sticky="nsew")
        self.io_tree_container.grid_columnconfigure(0, weight=1)
        self.io_tree_container.grid_rowconfigure(0, weight=1)
        self.left_panel.grid_rowconfigure(11, weight=1, minsize=230)

        self.io_tree = ttk.Treeview(self.io_tree_container, columns=IO_TREE_COLUMNS, show="headings", height=10)
        self.io_tree.grid(row=0, column=0, sticky="nsew")

        for column in IO_TREE_COLUMNS:
            self.io_tree.heading(column, text=column)
            width = 110 if column != "description" else 180
            self.io_tree.column(column, width=width, minwidth=70, stretch=True)

        tree_scroll_y = ttk.Scrollbar(self.io_tree_container, orient="vertical", command=self.io_tree.yview)
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x = ttk.Scrollbar(self.io_tree_container, orient="horizontal", command=self.io_tree.xview)
        tree_scroll_x.grid(row=1, column=0, sticky="ew")
        self.io_tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        manage_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        manage_frame.grid(row=12, column=0, padx=18, pady=(0, 8), sticky="ew")
        manage_frame.grid_columnconfigure(0, weight=1)
        manage_frame.grid_columnconfigure(1, weight=1)

        self.management_buttons: list[ctk.CTkButton] = []
        archive_button = ctk.CTkButton(manage_frame, text="Archivar codigos", command=self.archive_codes, font=self.button_font)
        archive_button.grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        self.management_buttons.append(archive_button)

        clear_button = ctk.CTkButton(
            manage_frame,
            text="Limpiar codigos",
            fg_color="#C2410C",
            hover_color="#9A3412",
            command=self.clear_codes,
            font=self.button_font
        )
        clear_button.grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        self.management_buttons.append(clear_button)

    def _build_center_panel(self) -> None:
        self.center_title_label = ctk.CTkLabel(self.center_panel, text="Comando industrial", font=self.panel_title_font)
        self.center_title_label.grid(row=0, column=0, padx=18, pady=(18, 12), sticky="w")

        status_frame = ctk.CTkFrame(self.center_panel)
        status_frame.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")
        status_frame.grid_columnconfigure(1, weight=1)

        self.status_label = ctk.CTkLabel(status_frame, text="Estado", font=self.section_label_font)
        self.status_label.grid(row=0, column=0, padx=(16, 10), pady=14, sticky="w")

        self.status_badge = ctk.CTkLabel(status_frame, textvariable=self.status_var, corner_radius=18, padx=14, pady=7, font=self.status_font)
        self.status_badge.grid(row=0, column=1, padx=(0, 14), pady=12, sticky="w")

        self.command_textbox = ctk.CTkTextbox(self.center_panel, corner_radius=16, wrap="word", font=self.text_font)
        self.command_textbox.grid(row=2, column=0, padx=18, pady=(0, 10), sticky="nsew")

        voice_options = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        voice_options.grid(row=3, column=0, padx=18, pady=(0, 8), sticky="ew")
        voice_options.grid_columnconfigure(0, weight=1)
        self.save_voice_checkbox = ctk.CTkCheckBox(
            voice_options,
            text="Guardar evidencia de voz",
            variable=self.save_voice_evidence_var,
            font=self.body_font,
            command=self._refresh_voice_settings
        )
        self.save_voice_checkbox.grid(row=0, column=0, sticky="w")

        voice_device_frame = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        voice_device_frame.grid(row=4, column=0, padx=18, pady=(0, 8), sticky="ew")
        voice_device_frame.grid_columnconfigure(0, weight=1)

        self.voice_device_var = tk.StringVar(value="Microfono predeterminado del sistema")
        self.voice_device_selector = ctk.CTkOptionMenu(
            voice_device_frame,
            variable=self.voice_device_var,
            values=["Microfono predeterminado del sistema"],
            command=self._on_voice_device_selected,
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.voice_device_selector.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.refresh_devices_button = ctk.CTkButton(
            voice_device_frame,
            text="Actualizar microfonos",
            width=170,
            command=self._refresh_input_devices,
            font=self.button_font
        )
        self.refresh_devices_button.grid(row=0, column=1, sticky="e")

        voice_level_frame = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        voice_level_frame.grid(row=5, column=0, padx=18, pady=(0, 10), sticky="ew")
        voice_level_frame.grid_columnconfigure(0, weight=1)

        self.voice_level_label = ctk.CTkLabel(
            voice_level_frame,
            text="Microfono en reposo.",
            font=self.body_font,
            anchor="w"
        )
        self.voice_level_label.grid(row=0, column=0, sticky="ew")

        self.voice_level_bar = ctk.CTkProgressBar(voice_level_frame)
        self.voice_level_bar.grid(row=1, column=0, pady=(4, 0), sticky="ew")
        self.voice_level_bar.set(0.0)

        primary_controls_frame = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        primary_controls_frame.grid(row=6, column=0, padx=18, pady=(0, 8), sticky="ew")
        for column_index in range(2):
            primary_controls_frame.grid_columnconfigure(column_index, weight=1)

        self.command_buttons: list[ctk.CTkButton] = []

        self.listen_button = ctk.CTkButton(
            primary_controls_frame, text="\U0001F399 Grabar comando", height=40,
            command=self.listen_command, font=self.button_font
        )
        self.listen_button.grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.listen_button)

        self.stop_voice_button = ctk.CTkButton(
            primary_controls_frame,
            text="■ Detener y transcribir",
            height=40,
            fg_color="#B45309",
            hover_color="#92400E",
            command=self.stop_listening,
            font=self.button_font
        )
        self.stop_voice_button.grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.stop_voice_button)

        self.execute_command_button = ctk.CTkButton(
            primary_controls_frame,
            text="EJECUTAR COMANDO",
            height=46,
            fg_color="#0F766E",
            hover_color="#115E59",
            command=self.execute_full_pipeline,
            font=ctk.CTkFont(size=15, weight="bold")
        )
        self.execute_command_button.grid(row=1, column=0, columnspan=2, padx=6, pady=(2, 6), sticky="ew")
        self.command_buttons.append(self.execute_command_button)

        self.download_plc_button = ctk.CTkButton(
            primary_controls_frame,
            text="CARGAR PROGRAMA AL PLC",
            height=42,
            fg_color="#B91C1C",
            hover_color="#991B1B",
            state="disabled",
            command=self.load_program_to_plc,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.download_plc_button.grid(row=2, column=0, columnspan=2, padx=6, pady=(0, 6), sticky="ew")
        self.command_buttons.append(self.download_plc_button)

        advanced_toggle_frame = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        advanced_toggle_frame.grid(row=7, column=0, padx=18, pady=(0, 4), sticky="ew")
        advanced_toggle_frame.grid_columnconfigure(0, weight=1)

        self.advanced_tools_toggle_button = ctk.CTkButton(
            advanced_toggle_frame,
            text="Herramientas avanzadas ▾",
            height=30,
            fg_color="transparent",
            border_width=1,
            text_color=("#334155", "#E2E8F0"),
            command=self._toggle_advanced_tools,
            font=self.body_font
        )
        self.advanced_tools_toggle_button.grid(row=0, column=0, sticky="ew")

        self.advanced_tools_frame = ctk.CTkFrame(self.center_panel, corner_radius=12)
        self.advanced_tools_frame.grid_columnconfigure(0, weight=1)
        self.advanced_tools_frame.grid_columnconfigure(1, weight=1)

        advanced_tools_label = ctk.CTkLabel(
            self.advanced_tools_frame, text="Herramientas avanzadas (depuracion)", font=self.section_label_font
        )
        advanced_tools_label.grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 4), sticky="w")

        self.process_button = ctk.CTkButton(self.advanced_tools_frame, text="Procesar comando", height=36, command=self.process_command, font=self.button_font)
        self.process_button.grid(row=1, column=0, padx=6, pady=4, sticky="ew")
        self.command_buttons.append(self.process_button)

        self.generate_button = ctk.CTkButton(self.advanced_tools_frame, text="Generar paquete PLC", height=36, command=self.generate_package, font=self.button_font)
        self.generate_button.grid(row=1, column=1, padx=6, pady=4, sticky="ew")
        self.command_buttons.append(self.generate_button)

        self.replay_button = ctk.CTkButton(
            self.advanced_tools_frame,
            text="Reproducir grabacion",
            height=36,
            command=self.play_recording,
            font=self.button_font
        )
        self.replay_button.grid(row=2, column=0, padx=6, pady=4, sticky="ew")
        self.command_buttons.append(self.replay_button)

        self.transcribe_button = ctk.CTkButton(
            self.advanced_tools_frame,
            text="Transcribir",
            height=36,
            command=self.transcribe_recording,
            font=self.button_font
        )
        self.transcribe_button.grid(row=2, column=1, padx=6, pady=4, sticky="ew")
        self.command_buttons.append(self.transcribe_button)

        self.use_transcription_button = ctk.CTkButton(
            self.advanced_tools_frame,
            text="Usar transcripcion",
            height=36,
            command=self.use_transcription,
            font=self.button_font
        )
        self.use_transcription_button.grid(row=3, column=0, padx=6, pady=4, sticky="ew")
        self.command_buttons.append(self.use_transcription_button)

        self.discard_voice_button = ctk.CTkButton(
            self.advanced_tools_frame,
            text="Descartar",
            height=36,
            fg_color="#7C2D12",
            hover_color="#9A3412",
            command=self.discard_transcription,
            font=self.button_font
        )
        self.discard_voice_button.grid(row=3, column=1, padx=6, pady=4, sticky="ew")
        self.command_buttons.append(self.discard_voice_button)

        self.clear_command_button = ctk.CTkButton(
            self.advanced_tools_frame,
            text="Limpiar comando",
            height=36,
            fg_color="#475569",
            hover_color="#334155",
            command=self.clear_command,
            font=self.button_font
        )
        self.clear_command_button.grid(row=4, column=0, columnspan=2, padx=6, pady=4, sticky="ew")
        self.command_buttons.append(self.clear_command_button)

        self.diagnose_tia_button = ctk.CTkButton(
            self.advanced_tools_frame,
            text="Diagnosticar Openness",
            height=36,
            command=self.diagnose_tia_connection,
            font=self.button_font
        )
        self.diagnose_tia_button.grid(row=5, column=0, columnspan=2, padx=6, pady=4, sticky="ew")

        self.validate_tia_button = ctk.CTkButton(
            self.advanced_tools_frame,
            text="Importar y compilar ultimo paquete Siemens",
            height=36,
            command=self.validate_latest_package_in_tia,
            font=self.button_font
        )
        self.validate_tia_button.grid(row=6, column=0, columnspan=2, padx=6, pady=(4, 10), sticky="ew")

        self.advanced_tools_frame.grid(row=8, column=0, padx=18, pady=(0, 8), sticky="ew")
        self.advanced_tools_frame.grid_remove()

        work_mode_frame = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        work_mode_frame.grid(row=9, column=0, padx=18, pady=(4, 6), sticky="ew")
        work_mode_frame.grid_columnconfigure(1, weight=1)

        work_mode_label = ctk.CTkLabel(work_mode_frame, text="Modo de trabajo", font=self.section_label_font)
        work_mode_label.grid(row=0, column=0, padx=(0, 10), sticky="w")

        self.work_mode_selector = ctk.CTkOptionMenu(
            work_mode_frame,
            variable=self.work_mode_var,
            values=["Normal", "Experimentacion"],
            command=self._on_work_mode_changed,
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.work_mode_selector.grid(row=0, column=1, sticky="ew")

        self._build_experiment_controls(row=10)
        self._build_manual_result_controls(row=11)

    def _toggle_advanced_tools(self) -> None:
        if self.advanced_tools_frame.winfo_ismapped():
            self.advanced_tools_frame.grid_remove()
            self.advanced_tools_toggle_button.configure(text="Herramientas avanzadas ▾")
        else:
            self.advanced_tools_frame.grid()
            self.advanced_tools_toggle_button.configure(text="Herramientas avanzadas ▴")

    def _build_experiment_controls(self, row: int) -> None:
        frame = ctk.CTkFrame(self.center_panel, corner_radius=12)
        self.experiment_controls_frame = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

        title = ctk.CTkLabel(frame, text="EXPERIMENTACION", font=ctk.CTkFont(size=16, weight="bold"))
        title.grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 8), sticky="w")

        group_label = ctk.CTkLabel(frame, text="Grupo de pruebas", font=self.body_font)
        group_label.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="w")
        self.experiment_group_selector = ctk.CTkOptionMenu(
            frame,
            variable=self.experiment_group_var,
            values=["Discreto D01-D20", "PID P01-P12"],
            command=self._on_experiment_group_changed,
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.experiment_group_selector.grid(row=2, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")

        case_label = ctk.CTkLabel(frame, text="Caso experimental", font=self.body_font)
        case_label.grid(row=3, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="w")
        self.experiment_case_selector = ctk.CTkOptionMenu(
            frame,
            variable=self.experiment_case_var,
            values=[""],
            command=self._on_experiment_case_changed,
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.experiment_case_selector.grid(row=4, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")

        variant_label = ctk.CTkLabel(frame, text="Variante linguistica", font=self.body_font)
        variant_label.grid(row=5, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="w")
        self.experiment_variant_selector = ctk.CTkOptionMenu(
            frame,
            variable=self.experiment_variant_var,
            values=["V1"],
            command=self._on_experiment_variant_changed,
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.experiment_variant_selector.grid(row=6, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")

        command_ref_label = ctk.CTkLabel(frame, text="Comando de referencia", font=self.body_font)
        command_ref_label.grid(row=7, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="w")

        self.experiment_variant_command_box = ctk.CTkFrame(
            frame, corner_radius=8, border_width=1, border_color="#CBD5E1", fg_color="#F1F5F9"
        )
        self.experiment_variant_command_box.grid_columnconfigure(0, weight=1)
        self.experiment_variant_command_label = ctk.CTkLabel(
            self.experiment_variant_command_box,
            textvariable=self.experiment_variant_command_var,
            anchor="w",
            justify="left",
            wraplength=340,
            font=self.body_font,
            text_color="#0F172A"
        )
        self.experiment_variant_command_label.grid(row=0, column=0, padx=10, pady=8, sticky="ew")
        self.experiment_variant_command_box.grid(row=8, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")

        self.use_variant_command_button = ctk.CTkButton(
            frame, text="Usar este comando", height=28, command=self._use_variant_command, font=self.button_font
        )
        self.use_variant_command_button.grid(row=9, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")

        condition_label = ctk.CTkLabel(frame, text="Condicion experimental", font=self.body_font)
        condition_label.grid(row=10, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="w")
        self.experiment_condition_selector = ctk.CTkOptionMenu(
            frame,
            variable=self.experiment_condition_var,
            values=[data["label"] for data in CONDITIONS.values()],
            command=self._on_experiment_condition_changed,
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.experiment_condition_selector.grid(row=11, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")

        speaker_label = ctk.CTkLabel(frame, text="Participante (speaker_id)", font=self.body_font)
        speaker_label.grid(row=12, column=0, padx=(12, 4), pady=(0, 2), sticky="w")
        noise_label = ctk.CTkLabel(frame, text="Ruido", font=self.body_font)
        noise_label.grid(row=12, column=1, padx=(4, 12), pady=(0, 2), sticky="w")

        self.experiment_speaker_entry = ctk.CTkEntry(frame, textvariable=self.experiment_speaker_var, font=self.body_font)
        self.experiment_speaker_entry.grid(row=13, column=0, padx=(12, 4), pady=(0, 6), sticky="ew")

        self.experiment_noise_selector = ctk.CTkOptionMenu(
            frame,
            variable=self.experiment_noise_var,
            values=[NOISE_LEVEL_LABELS[level] for level in NOISE_LEVELS],
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.experiment_noise_selector.grid(row=13, column=1, padx=(4, 12), pady=(0, 6), sticky="ew")

        environment_label = ctk.CTkLabel(frame, text="Entorno", font=self.body_font)
        environment_label.grid(row=14, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="w")
        self.experiment_environment_selector = ctk.CTkOptionMenu(
            frame,
            variable=self.experiment_environment_var,
            values=[ENVIRONMENT_LABELS[env] for env in ENVIRONMENTS],
            command=self._on_experiment_environment_changed,
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.experiment_environment_selector.grid(row=15, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")

        self.experiment_next_label_label = ctk.CTkLabel(
            frame,
            textvariable=self.experiment_next_label_var,
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.experiment_next_label_label.grid(row=16, column=0, columnspan=2, padx=12, pady=(0, 4), sticky="ew")

        self.experiment_status_label = ctk.CTkLabel(
            frame,
            textvariable=self.experiment_status_var,
            anchor="w",
            justify="left",
            font=self.body_font
        )
        self.experiment_status_label.grid(row=17, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")

        self.experiment_stage_label = ctk.CTkLabel(
            frame,
            textvariable=self.experiment_stage_var,
            anchor="w",
            justify="left",
            font=self.body_font
        )
        self.experiment_stage_label.grid(row=18, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")
        self._reset_experiment_stages()

        self.start_trial_button = ctk.CTkButton(
            frame, text="EJECUTAR ENSAYO", height=42,
            fg_color="#0F766E", hover_color="#115E59",
            command=self.run_experiment_trial, font=ctk.CTkFont(size=14, weight="bold")
        )
        self.oracle_status_label = ctk.CTkLabel(
            frame, textvariable=self.oracle_status_var, anchor="w", justify="left", font=self.body_font
        )
        self.oracle_status_label.grid(row=19, column=0, columnspan=2, padx=12, pady=(0, 4), sticky="ew")
        self.view_oracle_button = ctk.CTkButton(frame, text="VER ORACLE", command=self.view_case_oracle, font=self.button_font)
        self.view_oracle_button.grid(row=20, column=0, padx=(12, 4), pady=(0, 8), sticky="ew")
        self.approve_oracle_button = ctk.CTkButton(frame, text="APROBAR ORACLE", command=self.approve_case_oracle, font=self.button_font)
        self.approve_oracle_button.grid(row=20, column=1, padx=(4, 12), pady=(0, 8), sticky="ew")
        self.review_oracles_button = ctk.CTkButton(
            frame, text="REVISION DE ORACLES", command=self.open_oracle_review, font=self.button_font
        )
        self.review_oracles_button.grid(row=21, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")
        self.start_trial_button.grid(row=22, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew")

        frame.grid(row=row, column=0, padx=18, pady=(0, 8), sticky="ew")
        frame.grid_remove()

    def _build_manual_result_controls(self, row: int) -> None:
        frame = ctk.CTkFrame(self.center_panel, corner_radius=12)
        self.manual_result_frame = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

        title = ctk.CTkLabel(frame, text="Resultado del ensayo", font=ctk.CTkFont(size=15, weight="bold"))
        title.grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 6), sticky="w")

        result_label = ctk.CTkLabel(frame, text="Resultado fisico", font=self.body_font)
        result_label.grid(row=1, column=0, padx=(12, 4), pady=(0, 2), sticky="w")
        safety_label = ctk.CTkLabel(frame, text="Violacion de seguridad", font=self.body_font)
        safety_label.grid(row=1, column=1, padx=(4, 12), pady=(0, 2), sticky="w")

        self.manual_result_selector = ctk.CTkOptionMenu(
            frame, variable=self.manual_result_var, values=PHYSICAL_RESULT_OPTIONS, font=self.body_font, dropdown_font=self.body_font
        )
        self.manual_result_selector.grid(row=2, column=0, padx=(12, 4), pady=(0, 6), sticky="ew")

        self.manual_safety_selector = ctk.CTkOptionMenu(
            frame, variable=self.manual_safety_var, values=["No", "Si"], font=self.body_font, dropdown_font=self.body_font
        )
        self.manual_safety_selector.grid(row=2, column=1, padx=(4, 12), pady=(0, 6), sticky="ew")

        error_label = ctk.CTkLabel(frame, text="Tipo de error", font=self.body_font)
        error_label.grid(row=3, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="w")
        self.manual_error_selector = ctk.CTkOptionMenu(
            frame,
            variable=self.manual_error_var,
            values=[NO_ERROR_LABEL] + [f"{code} - {label}" for code, label in ERROR_CODES.items()],
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.manual_error_selector.grid(row=4, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")

        observations_label = ctk.CTkLabel(frame, text="Observaciones", font=self.body_font)
        observations_label.grid(row=5, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="w")
        self.manual_observations_entry = ctk.CTkEntry(frame, textvariable=self.manual_observations_var, font=self.body_font)
        self.manual_observations_entry.grid(row=6, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")

        self.save_manual_result_button = ctk.CTkButton(
            frame, text="Guardar resultado", height=38, command=self.save_manual_result, font=self.button_font
        )
        self.save_manual_result_button.grid(row=7, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew")

        frame.grid(row=row, column=0, padx=18, pady=(0, 12), sticky="ew")
        frame.grid_remove()

    def _build_right_panel(self) -> None:
        self.right_title_label = ctk.CTkLabel(self.right_panel, text="Resultados", font=self.panel_title_font)
        self.right_title_label.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="w")

        self.validation_banner = ctk.CTkLabel(
            self.right_panel,
            text="Sin ejecucion reciente.",
            corner_radius=14,
            padx=12,
            pady=10,
            anchor="w",
            font=self.banner_font
        )
        self.validation_banner.grid(row=1, column=0, padx=18, pady=(0, 12), sticky="ew")

        self.results_nav_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.results_nav_frame.grid(row=2, column=0, padx=18, pady=(0, 10), sticky="ew")
        self.results_nav_frame.grid_columnconfigure(1, weight=1)

        self.results_prev_button = ctk.CTkButton(
            self.results_nav_frame,
            text="<",
            width=self.result_nav_button_width,
            command=lambda: self._scroll_results_tabs(-1),
            font=self.button_font
        )
        self.results_prev_button.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.results_tab_strip = ctk.CTkFrame(self.results_nav_frame, fg_color="transparent")
        self.results_tab_strip.grid(row=0, column=1, sticky="ew")

        self.results_nav_status_label = ctk.CTkLabel(
            self.results_nav_frame,
            text="1-4 de 13",
            font=self.body_font,
            text_color="#475569",
            anchor="center"
        )
        self.results_nav_status_label.grid(row=0, column=2, padx=8, sticky="e")

        self.results_next_button = ctk.CTkButton(
            self.results_nav_frame,
            text=">",
            width=self.result_nav_button_width,
            command=lambda: self._scroll_results_tabs(1),
            font=self.button_font
        )
        self.results_next_button.grid(row=0, column=3, sticky="e")

        self.results_tabs = ctk.CTkTabview(self.right_panel, corner_radius=16, anchor="w", segmented_button_font=self.tab_font)
        self.results_tabs.grid(row=3, column=0, padx=18, pady=(0, 18), sticky="nsew")

        for tab_name in self.result_tab_names:
            self.results_tabs.add(tab_name)

        self.voice_textbox = self._create_readonly_textbox(self.results_tabs.tab("Voz"))
        self.intent_textbox = self._create_readonly_textbox(self.results_tabs.tab("Interpretacion"))
        self.comparison_textbox = self._create_readonly_textbox(self.results_tabs.tab("Comparacion reglas/LLM"))
        self.parameters_textbox = self._create_readonly_textbox(self.results_tabs.tab("Parametros"))
        self.ir_textbox = self._create_readonly_textbox(self.results_tabs.tab("Representacion intermedia"))
        self.pou_textbox = self._create_readonly_textbox(self.results_tabs.tab("POU"))
        self.task_textbox = self._create_readonly_textbox(self.results_tabs.tab("Tarea"))

        # Contenedor oculto (nunca empaquetado) para las pestanas de OpenPLC y
        # CODESYS aisladas de la vista. Conserva self.openplc_textbox y
        # self.codesys_textbox funcionales para el resto del codigo existente.
        self._hidden_platform_tabs = ctk.CTkFrame(self)
        openplc_hidden_tab = ctk.CTkFrame(self._hidden_platform_tabs)
        codesys_hidden_tab = ctk.CTkFrame(self._hidden_platform_tabs)
        self.openplc_textbox = self._create_readonly_textbox(openplc_hidden_tab)
        self.codesys_textbox = self._create_readonly_textbox(codesys_hidden_tab)

        self.siemens_textbox = self._create_readonly_textbox(self.results_tabs.tab("Proyecto Siemens"))
        self.tia_openness_textbox = self._create_readonly_textbox(self.results_tabs.tab("TIA Openness"))
        self.test_cases_textbox = self._create_readonly_textbox(self.results_tabs.tab("Casos de prueba"))
        self.verification_textbox = self._create_readonly_textbox(self.results_tabs.tab("Verificacion"))

        files_tab = self.results_tabs.tab("Archivos")
        files_tab.grid_columnconfigure(0, weight=1)
        files_tab.grid_rowconfigure(1, weight=1)

        files_toolbar = ctk.CTkFrame(files_tab, fg_color="transparent")
        files_toolbar.grid(row=0, column=0, padx=8, pady=(8, 0), sticky="ew")
        files_toolbar.grid_columnconfigure(0, weight=1)
        files_toolbar.grid_columnconfigure(1, weight=0)
        files_toolbar.grid_columnconfigure(2, weight=0)

        self.export_option_var = tk.StringVar(value="Resumen completo")
        self.export_selector = ctk.CTkOptionMenu(
            files_toolbar,
            variable=self.export_option_var,
            values=["Resumen completo"],
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.export_selector.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="ew")

        self.export_txt_button = ctk.CTkButton(
            files_toolbar,
            text="Exportar TXT",
            command=self.export_selected_result_to_txt,
            font=self.button_font
        )
        self.export_txt_button.grid(row=0, column=1, padx=(0, 8), pady=0, sticky="ew")

        self.export_bundle_button = ctk.CTkButton(
            files_toolbar,
            text="Resumen TXT",
            command=self.export_full_bundle_to_txt,
            font=self.button_font
        )
        self.export_bundle_button.grid(row=0, column=2, pady=0, sticky="ew")

        self.files_textbox = self._create_readonly_textbox(files_tab)
        self.files_textbox.grid(row=1, column=0, padx=8, pady=8, sticky="nsew")
        self.result_textboxes = [
            self.voice_textbox,
            self.intent_textbox,
            self.comparison_textbox,
            self.parameters_textbox,
            self.ir_textbox,
            self.pou_textbox,
            self.task_textbox,
            self.openplc_textbox,
            self.codesys_textbox,
            self.siemens_textbox,
            self.tia_openness_textbox,
            self.test_cases_textbox,
            self.verification_textbox,
            self.files_textbox
        ]

        history_tab = self.results_tabs.tab("Historial")
        history_tab.grid_columnconfigure(0, weight=1)
        history_tab.grid_rowconfigure(1, weight=1)

        history_toolbar = ctk.CTkFrame(history_tab, fg_color="transparent")
        history_toolbar.grid(row=0, column=0, padx=8, pady=(8, 0), sticky="ew")
        history_toolbar.grid_columnconfigure(0, weight=1)
        history_toolbar.grid_columnconfigure(1, weight=0)

        history_hint = ctk.CTkLabel(
            history_toolbar,
            text="Seleccione una fila para recargar ese resultado completo.",
            font=self.body_font,
            text_color="#4B5563",
            anchor="w"
        )
        history_hint.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.view_history_button = ctk.CTkButton(
            history_toolbar,
            text="Ver seleccion",
            command=self.restore_selected_history_item,
            font=self.button_font
        )
        self.view_history_button.grid(row=0, column=1, sticky="e")

        history_container = ctk.CTkFrame(history_tab)
        history_container.grid(row=1, column=0, padx=8, pady=8, sticky="nsew")
        history_container.grid_columnconfigure(0, weight=1)
        history_container.grid_rowconfigure(0, weight=1)

        history_columns = ("fecha", "comando", "intencion", "plataforma", "validacion")
        self.history_tree = ttk.Treeview(history_container, columns=history_columns, show="headings", height=12)
        self.history_tree.grid(row=0, column=0, sticky="nsew")

        for column in history_columns:
            self.history_tree.heading(column, text=column)
            width = 150 if column != "comando" else 260
            self.history_tree.column(column, width=width, minwidth=90, stretch=True)

        history_scroll = ttk.Scrollbar(history_container, orient="vertical", command=self.history_tree.yview)
        history_scroll.grid(row=0, column=1, sticky="ns")
        self.history_tree.configure(yscrollcommand=history_scroll.set)
        self.history_tree.bind("<<TreeviewSelect>>", self._on_history_tree_selected)
        self.history_tree.bind("<Double-1>", self._on_history_tree_double_click)

        experiment_tab = self.results_tabs.tab("Historial experimental")
        experiment_tab.grid_columnconfigure(0, weight=1)
        experiment_tab.grid_rowconfigure(1, weight=1)

        experiment_toolbar = ctk.CTkFrame(experiment_tab, fg_color="transparent")
        experiment_toolbar.grid(row=0, column=0, padx=8, pady=(8, 0), sticky="ew")
        experiment_toolbar.grid_columnconfigure(0, weight=1)

        experiment_hint = ctk.CTkLabel(
            experiment_toolbar,
            text="Doble clic en un ensayo para ver su detalle. Solo consulta y trazabilidad.",
            font=self.body_font,
            text_color="#4B5563",
            anchor="w"
        )
        experiment_hint.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.export_experiment_button = ctk.CTkButton(
            experiment_toolbar,
            text="Exportar resultados",
            command=self.export_experiment_results,
            font=self.button_font
        )
        self.export_experiment_button.grid(row=0, column=1, sticky="e")

        experiment_container = ctk.CTkFrame(experiment_tab)
        experiment_container.grid(row=1, column=0, padx=8, pady=8, sticky="nsew")
        experiment_container.grid_columnconfigure(0, weight=1)
        experiment_container.grid_rowconfigure(0, weight=1)

        experiment_columns = ("trial", "etiqueta", "compila", "ejecucion", "tiempo", "error")
        self.experiment_history_tree = ttk.Treeview(experiment_container, columns=experiment_columns, show="headings", height=12)
        self.experiment_history_tree.grid(row=0, column=0, sticky="nsew")

        experiment_headings = {
            "trial": "Trial", "etiqueta": "Etiqueta", "compila": "Compila",
            "ejecucion": "Ejecucion", "tiempo": "Tiempo", "error": "Error"
        }
        for column in experiment_columns:
            self.experiment_history_tree.heading(column, text=experiment_headings[column])
            width = 150 if column == "etiqueta" else 110
            self.experiment_history_tree.column(column, width=width, minwidth=70, stretch=True)

        experiment_scroll = ttk.Scrollbar(experiment_container, orient="vertical", command=self.experiment_history_tree.yview)
        experiment_scroll.grid(row=0, column=1, sticky="ns")
        self.experiment_history_tree.configure(yscrollcommand=experiment_scroll.set)
        self.experiment_history_tree.bind("<Double-1>", self._on_experiment_history_double_click)

        self._hide_default_results_tab_bar()
        self._refresh_results_navigation()

    def _hide_default_results_tab_bar(self) -> None:
        self.results_tabs._segmented_button.grid_forget()
        self.results_tabs._outer_spacing = 3
        self.results_tabs._outer_button_overhang = 0
        self.results_tabs._button_height = 1
        self.results_tabs._configure_grid()
        self.results_tabs._set_grid_canvas()
        if self.active_result_tab in self.result_tab_names:
            self.results_tabs.set(self.active_result_tab)

    def _scroll_results_tabs(self, direction: int) -> None:
        max_start = max(0, len(self.result_tab_names) - self.result_tab_window_size)
        new_start = min(max(self.result_tab_window_start + direction, 0), max_start)
        if new_start == self.result_tab_window_start:
            return
        self.result_tab_window_start = new_start
        self._refresh_results_navigation()

    def _select_results_tab(self, tab_name: str) -> None:
        if tab_name not in self.result_tab_names:
            return
        self.active_result_tab = tab_name
        self._ensure_active_result_tab_visible()
        self.results_tabs.set(tab_name)
        self._refresh_results_navigation()

    def _clamp_result_tab_window(self) -> None:
        max_start = max(0, len(self.result_tab_names) - self.result_tab_window_size)
        self.result_tab_window_start = min(max(self.result_tab_window_start, 0), max_start)

    def _ensure_active_result_tab_visible(self) -> None:
        active_index = self.result_tab_names.index(self.active_result_tab)
        max_start = max(0, len(self.result_tab_names) - self.result_tab_window_size)
        if active_index < self.result_tab_window_start:
            self.result_tab_window_start = active_index
        elif active_index >= self.result_tab_window_start + self.result_tab_window_size:
            self.result_tab_window_start = active_index - self.result_tab_window_size + 1
        self.result_tab_window_start = min(max(self.result_tab_window_start, 0), max_start)

    def _refresh_results_navigation(self) -> None:
        self._clamp_result_tab_window()

        for child in self.results_tab_strip.winfo_children():
            child.destroy()

        visible_tabs = self.result_tab_names[
            self.result_tab_window_start:self.result_tab_window_start + self.result_tab_window_size
        ]
        for column_index, tab_name in enumerate(visible_tabs):
            self.results_tab_strip.grid_columnconfigure(column_index, weight=1)
            is_active = tab_name == self.active_result_tab
            tab_button = ctk.CTkButton(
                self.results_tab_strip,
                text=self.result_tab_labels.get(tab_name, tab_name),
                height=self.result_tab_button_height,
                font=self.tab_font,
                corner_radius=14,
                fg_color="#10B981" if is_active else "#94A3B8",
                hover_color="#059669" if is_active else "#7B8794",
                text_color="#FFFFFF",
                command=lambda selected=tab_name: self._select_results_tab(selected)
            )
            tab_button.grid(row=0, column=column_index, padx=4, pady=0, sticky="ew")

        start_display = self.result_tab_window_start + 1
        end_display = self.result_tab_window_start + len(visible_tabs)
        self.results_nav_status_label.configure(text=f"{start_display}-{end_display} de {len(self.result_tab_names)}")

        prev_state = "normal" if self.result_tab_window_start > 0 else "disabled"
        next_state = (
            "normal"
            if self.result_tab_window_start + self.result_tab_window_size < len(self.result_tab_names)
            else "disabled"
        )
        self.results_prev_button.configure(state=prev_state)
        self.results_next_button.configure(state=next_state)

    def _build_console_panel(self) -> None:
        self.console_title_label = ctk.CTkLabel(self.console_panel, text="Consola del sistema", font=self.panel_title_font)
        self.console_title_label.grid(row=0, column=0, padx=18, pady=(16, 10), sticky="w")

        self.console_textbox = ctk.CTkTextbox(self.console_panel, height=180, corner_radius=16, wrap="word", font=self.console_font)
        self.console_textbox.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="nsew")
        self.console_textbox.configure(state="disabled")

    def _create_readonly_textbox(self, parent: ctk.CTkBaseClass) -> ctk.CTkTextbox:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        textbox = ctk.CTkTextbox(parent, corner_radius=12, wrap="word", font=self.text_font)
        textbox.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        textbox.configure(state="disabled")
        return textbox

    def _set_textbox_content(self, textbox: ctk.CTkTextbox, content: str) -> None:
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", content)
        textbox.configure(state="disabled")

    def _set_status(self, status: str) -> None:
        self.status_var.set(status)
        colors = get_status_colors(status)
        self.status_badge.configure(fg_color=colors["fg"], text_color=colors["text"])

    def _set_validation_banner(self, text: str, valid: bool | None) -> None:
        if valid is True:
            self.validation_banner.configure(text=text, fg_color="#DCFCE7", text_color="#166534")
        elif valid is False:
            self.validation_banner.configure(text=text, fg_color="#FEE2E2", text_color="#991B1B")
        else:
            self.validation_banner.configure(text=text, fg_color="#E2E8F0", text_color="#334155")

    def _refresh_llm_client_status(self, *, announce: bool = False) -> dict[str, Any]:
        self.llm_client = PLCInterpretationLLMClient()
        self.speech_recognizer.llm_client = self.llm_client
        health = self.llm_client.health_check()

        if health.get("llm_configured"):
            status_text = "LLM activo"
            fg_color = "#DCFCE7"
            text_color = "#166534"
        elif health.get("sdk_available"):
            status_text = "LLM en modo demo local"
            fg_color = "#FEF3C7"
            text_color = "#92400E"
        else:
            status_text = "SDK OpenAI no instalado"
            fg_color = "#FEE2E2"
            text_color = "#991B1B"

        if health.get("transcription_configured"):
            status_text += " + voz"

        self.llm_status_var.set(status_text)
        self.llm_status_banner.configure(fg_color=fg_color, text_color=text_color)

        if announce:
            self._log(
                "Estado LLM actualizado: "
                f"llm_configured={health.get('llm_configured')}, "
                f"transcription_configured={health.get('transcription_configured')}, "
                f"model={bool(self.llm_client.model_name)}"
            )

        return health

    def _refresh_voice_settings(self) -> None:
        self.speech_recognizer.save_evidence = self.save_voice_evidence_var.get()

    def _refresh_input_devices(self) -> None:
        default_label = "Microfono predeterminado del sistema"
        devices = self.speech_recognizer.list_input_devices()

        self._voice_device_index_by_label = {default_label: None}
        labels = [default_label]
        for device in devices:
            label = f"{device['name']} (#{device['index']})"
            self._voice_device_index_by_label[label] = device["index"]
            labels.append(label)

        self.voice_device_selector.configure(values=labels)
        current_index = self.speech_recognizer.input_device_index
        matching_label = next(
            (label for label, index in self._voice_device_index_by_label.items() if index == current_index),
            default_label
        )
        self.voice_device_var.set(matching_label)
        self._log(f"Microfonos detectados: {len(devices)}.")

    def _on_voice_device_selected(self, selected_label: str) -> None:
        device_index = self._voice_device_index_by_label.get(selected_label)
        try:
            self.speech_recognizer.set_input_device(device_index)
            self._log(f"Microfono seleccionado: {selected_label}.")
        except RuntimeError as error:
            messagebox.showwarning("Voz", str(error))
            self._refresh_input_devices()

    def _reset_voice_level_indicator(self) -> None:
        self.voice_level_bar.set(0.0)
        self.voice_level_label.configure(text="Microfono en reposo.")

    def _poll_recording_state(self) -> None:
        self._voice_level_poll_job = None
        if not self.speech_recognizer.is_recording():
            return

        if self.speech_recognizer.was_auto_stopped():
            max_seconds = self.speech_recognizer.max_recording_seconds
            self._log(f"Grabacion detenida automaticamente al alcanzar el limite de {max_seconds:.0f}s.")
            self.stop_listening()
            return

        level = self.speech_recognizer.get_current_level()
        elapsed = self.speech_recognizer.recording_elapsed_seconds() or 0.0
        max_seconds = self.speech_recognizer.max_recording_seconds
        ratio = min(1.0, level["peak"] / 32767) if level["peak"] else 0.0
        self.voice_level_bar.set(ratio)
        self.voice_level_label.configure(
            text=f"Grabando... {elapsed:.0f}s / {max_seconds:.0f}s  (nivel pico: {level['peak']})"
        )
        self._voice_level_poll_job = self.after(150, self._poll_recording_state)

    def _refresh_voice_button_states(self) -> None:
        is_recording = self.speech_recognizer.is_recording()
        is_busy = self._voice_worker_active
        has_audio = bool(self.voice_audio_path and self.voice_audio_path.exists())
        has_transcript = bool((self.voice_transcription or {}).get("transcript", "").strip())

        self.listen_button.configure(state="disabled" if is_recording or is_busy else "normal")
        self.stop_voice_button.configure(state="normal" if is_recording else "disabled")
        media_state = "normal" if has_audio and not is_recording and not is_busy else "disabled"
        self.replay_button.configure(state=media_state)
        self.transcribe_button.configure(state=media_state)
        self.use_transcription_button.configure(
            state="normal" if has_transcript and not is_recording and not is_busy else "disabled"
        )
        self.discard_voice_button.configure(
            state="normal" if (has_audio or self.voice_transcription) and not is_recording and not is_busy else "disabled"
        )
        command_state = "disabled" if is_recording or is_busy else "normal"
        self.process_button.configure(state=command_state)
        self.generate_button.configure(state=command_state)
        self.clear_command_button.configure(state=command_state)
        self.execute_command_button.configure(state=command_state)

    def configure_llm_api(self) -> None:
        dialog = LLMConfigDialog(self, load_llm_env_settings(self.env_path))
        self.wait_window(dialog)

        if dialog.result is None:
            self._log("La configuracion LLM no fue modificada.")
            return

        try:
            save_llm_env_settings(dialog.result, self.env_path)
            self._refresh_llm_client_status(announce=True)
            parser_mode = dialog.result.get("PARSER_MODE", "llm").strip().lower()
            parser_ui_map = {
                "rule_based": "Reglas",
                "llm": "LLM",
                "hybrid": "Hibrido"
            }
            self.parser_mode_var.set(parser_ui_map.get(parser_mode, "LLM"))
            self._log(f"Configuracion LLM guardada en {self.env_path}.")
            messagebox.showinfo(
                "Configuracion LLM",
                "La configuracion OpenAI fue guardada correctamente.\n\n"
                f"Archivo: {self.env_path}"
            )
        except Exception as error:  # pragma: no cover - local file path
            self._log(f"No se pudo guardar la configuracion LLM: {error}")
            messagebox.showerror(
                "Configuracion LLM",
                f"No se pudo guardar la configuracion.\n\n{error}"
            )

    def test_llm_connection(self) -> None:
        health = self._refresh_llm_client_status(announce=False)
        if not health.get("llm_configured"):
            messagebox.showwarning(
                "Conexion LLM",
                "La API LLM aun no esta configurada.\n\n"
                "Complete OPENAI_API_KEY y PLC_LLM_MODEL desde 'Configurar API LLM'."
            )
            return

        self._log("Ejecutando prueba de conexion LLM...")
        diagnostics = self.llm_client.connectivity_check()
        self._refresh_llm_client_status(announce=False)
        self._log(
            "Diagnostico LLM completado: "
            f"live_connection={diagnostics.get('live_connection')}, "
            f"error={diagnostics.get('error')}"
        )
        messagebox.showinfo("Diagnostico LLM", format_json(diagnostics))

    def configure_tia_openness(self) -> None:
        current_config = load_tia_config(self.project_root)
        current_project = str(current_config.get("project_path", "")).strip()
        initial_dir = str(Path(current_project).parent) if current_project else str(self.project_root)
        project_path = filedialog.askopenfilename(
            title="Seleccione un proyecto TIA Portal V18",
            initialdir=initial_dir,
            filetypes=[("Proyecto TIA Portal V18", "*.ap18"), ("Todos los archivos", "*.*")]
        )
        if not project_path:
            self._log("La configuracion TIA Openness no fue modificada.")
            return

        plc_name = simpledialog.askstring(
            "TIA Portal V18",
            "Nombre del software PLC dentro del proyecto (opcional).\n"
            "Deje vacio para usar la primera CPU encontrada:",
            initialvalue=str(current_config.get("plc_name", "")),
            parent=self
        )
        if plc_name is None:
            return

        current_config.update(
            {
                "tia_version": "V18",
                "project_path": project_path,
                "plc_name": plc_name.strip(),
                "attach_to_running": True,
                "with_user_interface": True,
                "create_plc_tags": True,
                "save_project_on_success": True,
                "compile_after_import": True
            }
        )
        save_tia_config(current_config, self.project_root)
        diagnostic = diagnose_tia_openness(self.project_root)
        self._set_textbox_content(self.tia_openness_textbox, format_json(diagnostic))
        self._select_results_tab("TIA Openness")
        self._log(f"Proyecto TIA V18 configurado: {project_path}")
        messagebox.showinfo(
            "TIA Portal V18",
            "Configuracion guardada. La importacion solo se ejecutara despues de una confirmacion explicita."
        )

    def diagnose_tia_connection(self) -> None:
        build_result = build_openness_bridge(self.project_root)
        diagnostic = diagnose_tia_openness(self.project_root)
        runtime_diagnostic = run_openness_bridge_diagnostic(self.project_root)
        payload = {
            "diagnostic": diagnostic,
            "bridge_build": build_result,
            "bridge_runtime": runtime_diagnostic
        }
        self._set_textbox_content(self.tia_openness_textbox, format_json(payload))
        self._select_results_tab("TIA Openness")
        self._log(
            "Diagnostico TIA Openness: "
            f"installed={diagnostic.get('is_installed')}, ready={diagnostic.get('is_ready')}."
        )
        if diagnostic.get("is_ready"):
            messagebox.showinfo("TIA Openness", "TIA Portal Openness V18 esta listo para importar y compilar.")
        else:
            messagebox.showwarning(
                "TIA Openness",
                "La integracion aun requiere configuracion. Revise la pestana TIA Openness.\n\n"
                + "\n".join(diagnostic.get("warnings", []))
            )

    def validate_latest_package_in_tia(self) -> None:
        if self._tia_worker_active:
            messagebox.showwarning("TIA Openness", "Ya existe una operacion TIA en curso.")
            return
        snapshot = self.current_result_snapshot or {}
        saved_paths = snapshot.get("combined_files", {}).get("SIEMENS_SCL_V18", {})
        package_dir_text = saved_paths.get("package_dir") if isinstance(saved_paths, dict) else None
        if not package_dir_text:
            messagebox.showwarning(
                "TIA Openness",
                "Primero genere un paquete con un comando o intencion valida."
            )
            return

        diagnostic = diagnose_tia_openness(self.project_root)
        if not diagnostic.get("is_ready"):
            self._set_textbox_content(self.tia_openness_textbox, format_json(diagnostic))
            self._select_results_tab("TIA Openness")
            messagebox.showwarning(
                "TIA Openness",
                "TIA Openness aun no esta listo. Revise el diagnostico y la configuracion del proyecto."
            )
            return

        # EJECUTAR COMANDO debe continuar automaticamente hasta TIA/compilacion sin ningun dialogo
        # de confirmacion intermedio (decision explicita del usuario - reemplaza la politica previa
        # de "confirmar antes de importar a TIA"). CARGAR PROGRAMA AL PLC sigue siendo manual e
        # independiente - esto nunca descarga nada a un PLC fisico, solo importa/compila en el
        # proyecto TIA configurado.
        self._log(
            "Iniciando TIA Openness sin confirmacion interactiva (Modo Normal, pipeline automatico). "
            f"Proyecto TIA: {diagnostic.get('project_path')} | Mapa: {self.active_map_var.get()} | "
            f"Paquete: {package_dir_text}"
        )
        self._log("[PIPELINE] Starting TIA Openness")
        self._log(f"[PIPELINE] Opening project: {diagnostic.get('project_path')}")

        while not self._tia_worker_queue.empty():
            try:
                self._tia_worker_queue.get_nowait()
            except queue.Empty:
                break

        package_dir = Path(package_dir_text)
        self._tia_worker_active = True
        self.validate_tia_button.configure(state="disabled")
        self.execute_command_button.configure(state="disabled")
        self.start_trial_button.configure(state="disabled")
        self._set_status("Procesando")
        self._set_textbox_content(
            self.tia_openness_textbox,
            "Conectando con TIA Portal V18 mediante Openness. Esta operacion puede tardar varios minutos..."
        )
        self._select_results_tab("TIA Openness")
        self._log("Iniciando importacion y compilacion en TIA Portal V18.")

        def _worker() -> None:
            try:
                result = validate_package_with_tia(package_dir, self.project_root)
                self._tia_worker_queue.put(("success", result))
            except Exception as error:  # pragma: no cover - external Siemens process
                self._tia_worker_queue.put(("error", str(error)))

        self._compile_started_perf = time.perf_counter()
        if self.active_trial:
            self._set_experiment_stage("Compilacion", "running")
        threading.Thread(target=_worker, name="tia-openness", daemon=True).start()
        self.after(250, self._poll_tia_worker)

    def _poll_tia_worker(self) -> None:
        try:
            outcome, payload = self._tia_worker_queue.get_nowait()
        except queue.Empty:
            if self._tia_worker_active:
                self.after(250, self._poll_tia_worker)
            return

        self._tia_worker_active = False
        self.validate_tia_button.configure(state="normal")
        self.execute_command_button.configure(state="normal")
        self.start_trial_button.configure(state="normal")
        if outcome == "error":
            self._invalidate_download_readiness()
            self._set_status("Error")
            self._set_textbox_content(self.tia_openness_textbox, str(payload))
            self._log(f"Error TIA Openness: {payload}")
            self._log(f"[PIPELINE] FAILED at stage: TIA Openness (exception) - {payload}")
            if self.active_trial:
                directory = trial_dir(self.project_root, self.active_trial["case_id"], self.active_trial["trial_id"])
                save_metadata(directory, {"tia_compile_status": "ERROR", "tia_error": str(payload)})
                self._log(f"Ensayo {self.active_trial['trial_id']}: fallo TIA Openness registrado como evidencia.")
                self._update_new_trial({"compile": {"status": "ERROR", "error": str(payload)}, "stages": {"compile_success": False}})
                self._set_experiment_stage("Compilacion", "fail")
                self._finalize_new_trial(trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR, [f"TIA Openness: {payload}"])
            messagebox.showerror("TIA Openness", f"No se pudo completar la operacion.\n\n{payload}")
            return

        report = payload
        passed = report.get("status") == "TIA_COMPILATION_PASSED"
        report_text = format_json(report)
        self._set_textbox_content(self.tia_openness_textbox, report_text)
        self._log(f"[PIPELINE] Compile report: {report.get('result_path', '(sin result_path)')}")
        if passed:
            self._log("[PIPELINE] Completed")
        else:
            # Seccion 8: nunca dejar solo "Verificacion completada" en un fallo de Openness -
            # exponer executable, codigo de salida, stdout y stderr exactos.
            self._log(
                "[PIPELINE] FAILED at stage: TIA Openness (compile) - status="
                f"{report.get('status')} return_code={report.get('bridge_return_code')}\n"
                f"stdout: {report.get('bridge_stdout', '')}\n"
                f"stderr: {report.get('bridge_stderr', '')}"
            )
        if self.current_result_snapshot is not None:
            self._apply_tia_report_to_snapshot(self.current_result_snapshot, report)
            self._refresh_export_options(self.current_result_snapshot)

        result_path = str(report.get("result_path", ""))
        chain_experiment_download = False
        if self.active_trial:
            directory = trial_dir(self.project_root, self.active_trial["case_id"], self.active_trial["trial_id"])
            save_metadata(directory, {"tia_compile_status": report.get("status", ""), "tia_result_path": result_path})
            self._log(f"Ensayo {self.active_trial['trial_id']}: resultado TIA registrado ({report.get('status')}).")
            compile_ms = (
                int(round((time.perf_counter() - self._compile_started_perf) * 1000))
                if self._compile_started_perf is not None else None
            )
            self._update_new_trial({
                "compile": {
                    "status": report.get("status"),
                    "error_count": report.get("error_count"),
                    "warning_count": report.get("warning_count"),
                    "result_path": result_path,
                    "tag_reconciliation": report.get("tag_reconciliation")
                },
                "stages": {"compile_success": passed},
                "timing": {"compile_ms": compile_ms}
            })
            self._set_experiment_stage("Compilacion", "ok" if passed else "fail")
            if passed:
                self._set_trial_lifecycle(trial_io_map.STATE_COMPILED)
                self._log("[EXPERIMENT] TIA compile passed")
                # Modo Experimentacion (Fase 1): compilacion aprobada -> descarga automatica a
                # PLCSIM Advanced + Start Module. En Modo Normal nunca se descarga automaticamente.
                chain_experiment_download = bool(result_path) and self.work_mode_var.get() == "Experimentacion"
            else:
                for stage in ("Descarga", "CPU Start"):
                    self._set_experiment_stage(stage, "skipped")
                new_dir = self._new_trial_dir()
                if new_dir is not None and result_path:
                    trial_model.copy_package_artifacts(new_dir, Path(result_path).parent)
                self._finalize_new_trial(trial_model.FINAL_STATUS_FAIL, [f"Compilacion TIA: {report.get('status')}"])
        report_package_dir = str(Path(result_path).parent) if result_path else ""
        history_updated = False
        for history_record in self.history_records:
            snapshot = history_record.get("snapshot", {})
            siemens_paths = snapshot.get("combined_files", {}).get("SIEMENS_SCL_V18", {})
            package_dir = str(siemens_paths.get("package_dir", ""))
            if report_package_dir and package_dir == report_package_dir:
                self._apply_tia_report_to_snapshot(snapshot, report)
                history_record["is_valid"] = passed
                history_updated = True
        if history_updated:
            self._save_history_state()

        if passed and report_package_dir:
            self._last_compiled_package_dir = Path(report_package_dir)
            self._last_successful_tia_package_dir = Path(report_package_dir)
            self.download_plc_button.configure(state="normal")
            self._log(f"'CARGAR PROGRAMA AL PLC' habilitado para {report_package_dir}.")
        else:
            self._invalidate_download_readiness()
            if self._last_successful_tia_package_dir is not None:
                self._log(
                    "Ultimo programa compilado con exito sin cambios: "
                    f"{self._last_successful_tia_package_dir}."
                )

        self._set_status("Listo" if passed else "Error")
        self._set_validation_banner(
            "Compilacion TIA Portal V18 aprobada." if passed else "TIA Portal reporto errores de compilacion.",
            passed
        )
        self._log(f"TIA Openness finalizo con estado {report.get('status')}.")
        if chain_experiment_download:
            self._start_download(Path(report_package_dir), DOWNLOAD_PURPOSE_EXPERIMENT)
            return
        if passed:
            messagebox.showinfo("TIA Openness", "Los bloques fueron importados y compilados correctamente.")
        else:
            messagebox.showwarning("TIA Openness", "La operacion termino con incidencias. Revise el reporte.")

    def load_program_to_plc(self) -> None:
        """
        Descarga UNICAMENTE el programa ya compilado (nunca configuracion de hardware) al PLC
        configurado en el proyecto TIA actual. No reprocesa el comando, no vuelve a llamar al
        LLM, no reconstruye IR/SCL ni reimporta - solo invoca DownloadProvider.Download sobre el
        paquete que ya paso la ultima compilacion aprobada (self._last_compiled_package_dir).
        """
        if self._download_worker_active or self._tia_worker_active:
            messagebox.showwarning("Cargar programa al PLC", "Ya existe una operacion TIA en curso.")
            return
        if self._last_compiled_package_dir is None:
            messagebox.showwarning(
                "Cargar programa al PLC",
                "No hay una compilacion Siemens vigente y aprobada. Genere y compile el programa antes de descargar."
            )
            return

        package_dir = self._last_compiled_package_dir
        compile_report_path = package_dir / "tia_compile_report.json"
        compile_status = ""
        compile_timestamp = ""
        if compile_report_path.exists():
            try:
                compile_report = load_json_file(compile_report_path)
                compile_status = str(compile_report.get("status", ""))
                compile_timestamp = str(compile_report.get("timestamp", ""))
            except (FileNotFoundError, ValueError):
                pass
        if compile_status != "TIA_COMPILATION_PASSED":
            self._invalidate_download_readiness()
            messagebox.showwarning(
                "Cargar programa al PLC",
                "No hay una compilacion Siemens vigente y aprobada. Genere y compile el programa antes de descargar."
            )
            return

        tia_config = load_tia_config(self.project_root)
        project_path = str(tia_config.get("project_path", "")) or "(no configurado)"
        plc_name = str(tia_config.get("plc_name", "")).strip() or "(unico en el proyecto)"
        target = resolve_download_target(tia_config, DOWNLOAD_PURPOSE_NORMAL)
        is_simulation = target["target_type"] == TARGET_TYPE_PLCSIM
        target_warning = (
            "Destino: simulador PLCSIM Advanced (no afecta hardware fisico)."
            if is_simulation else
            "ATENCION: el destino configurado es un PLC FISICO real. La CPU puede detenerse "
            "durante la descarga."
        )

        confirmed = messagebox.askyesno(
            "Confirmar descarga al PLC",
            "Se descargara el programa compilado de ESTA ejecucion y se arrancara la CPU (Start Module).\n\n"
            f"Proyecto TIA: {project_path}\n"
            f"CPU/dispositivo configurado: {plc_name}\n"
            f"Destino: {target.get('target_name', '')} ({target['target_type']})\n"
            f"Alcance: {target['download_scope']}\n"
            f"Paquete: {package_dir}\n"
            f"Ultimo resultado de compilacion: {compile_status}\n"
            f"Timestamp de compilacion: {compile_timestamp}\n\n"
            f"{target_warning}\n"
            "No se modifica la configuracion de red.\n\n"
            "¿Desea continuar?"
        )
        if not confirmed:
            self._log("Descarga al PLC cancelada por el usuario.")
            return

        self._start_download(package_dir, DOWNLOAD_PURPOSE_NORMAL)

    def _start_download(self, package_dir: Path, purpose: str) -> None:
        """Lanza la descarga del paquete EXACTO indicado (nunca 'el ultimo directorio')."""
        while not self._download_worker_queue.empty():
            try:
                self._download_worker_queue.get_nowait()
            except queue.Empty:
                break

        self._download_worker_active = True
        self._download_purpose = purpose
        self._download_package_dir = package_dir
        self.download_plc_button.configure(state="disabled")
        self.execute_command_button.configure(state="disabled")
        self.start_trial_button.configure(state="disabled")
        self.validate_tia_button.configure(state="disabled")
        self._set_status("Procesando")
        self._set_textbox_content(
            self.tia_openness_textbox,
            "Descargando el programa compilado mediante TIA Portal V18 Openness (DownloadProvider). "
            "Esta operacion puede tardar varios minutos..."
        )
        self._select_results_tab("TIA Openness")
        if purpose == DOWNLOAD_PURPOSE_EXPERIMENT:
            self._set_experiment_stage("Descarga", "running")
            self._log("[TIA DOWNLOAD] Target validation (experimento: solo PLCSIM Advanced)")
        self._log(f"[TIA DOWNLOAD] Starting - paquete {package_dir}")

        def _worker() -> None:
            try:
                result = download_program_to_plc(package_dir, self.project_root, purpose)
                self._download_worker_queue.put(("success", result))
            except Exception as error:  # pragma: no cover - external Siemens process
                self._download_worker_queue.put(("error", str(error)))

        threading.Thread(target=_worker, name="tia-download", daemon=True).start()
        self.after(250, self._poll_download_worker)

    def _poll_download_worker(self) -> None:
        try:
            outcome, payload = self._download_worker_queue.get_nowait()
        except queue.Empty:
            if self._download_worker_active:
                self.after(250, self._poll_download_worker)
            return

        self._download_worker_active = False
        self.execute_command_button.configure(state="normal")
        self.start_trial_button.configure(state="normal")
        self.validate_tia_button.configure(state="normal")
        # El estado de "compilacion vigente" no cambia por intentar descargar: si sigue siendo
        # el mismo paquete (no se proceso un comando nuevo mientras tanto), el boton se reactiva
        # para permitir reintentar sin tener que recompilar.
        self.download_plc_button.configure(state="normal" if self._last_compiled_package_dir else "disabled")
        purpose = self._download_purpose

        if outcome == "error":
            self._set_status("Error")
            self._log(f"[TIA DOWNLOAD] FAILED (excepcion): {payload}")
            if purpose == DOWNLOAD_PURPOSE_EXPERIMENT:
                self._complete_experiment_download(
                    {"status": "DOWNLOAD_EXCEPTION", "download_success": False, "start_module_success": False, "errors": [str(payload)]}
                )
                return
            messagebox.showerror("Cargar programa al PLC", f"No se pudo cargar el programa al PLC.\n\n{payload}")
            return

        report = payload
        self._set_textbox_content(self.tia_openness_textbox, format_json(report))
        success = bool(report.get("download_success", report.get("success")))
        status = str(report.get("status", ""))
        self._set_status("Listo" if success else "Error")
        self._log(f"[TIA DOWNLOAD] {'Completed' if success else 'FAILED'} - estado {status}")

        if purpose == DOWNLOAD_PURPOSE_EXPERIMENT:
            self._complete_experiment_download(report)
            return

        if success:
            self._remember_io_program(None)
            self._start_runtime_refresh("post-descarga", package_dir=self._download_package_dir)
            start_text = {True: "Start Module solicitado (CPU en RUN solicitado).", False: "Start Module fallo.", None: "TIA no presento Start Module (la CPU no se detuvo)."}
            messagebox.showinfo(
                "Cargar programa al PLC",
                "Programa cargado correctamente.\n\n"
                f"Destino: {report.get('target_name', '')} ({report.get('target_type', '')})\n"
                f"Dispositivo: {report.get('device_item_name', '')}\n"
                f"{start_text.get(report.get('start_module_success'), '')}\n"
                f"Duracion: {report.get('duration_ms', '')} ms\n"
                f"Resultado: {status}"
            )
        else:
            errors = report.get("errors", [])
            detail = "\n".join(str(item) for item in errors) if errors else "Revise el reporte tecnico en la pestana TIA Openness."
            messagebox.showerror("Cargar programa al PLC", f"No se pudo cargar el programa al PLC ({status}).\n\n" + detail)

    def _complete_experiment_download(self, report: dict[str, Any]) -> None:
        """Cierre del ensayo en Fase 1: PREPARED si llego a PLCSIM y arranco; si no, error de infraestructura."""
        download_ok = bool(report.get("download_success"))
        start_success = report.get("start_module_success")
        self._update_new_trial({
            "download": {
                key: report.get(key)
                for key in (
                    "status", "bridge_status", "target_type", "target_name", "pc_interface_name",
                    "target_interface_name", "download_scope", "download_success", "start_module_requested",
                    "start_module_success", "cpu_run_requested", "cpu_run_confirmed", "download_configurations",
                    "warnings", "errors", "started_at", "completed_at", "duration_ms"
                )
            },
            "stages": {"download_success": download_ok, "start_module_success": start_success},
            "timing": {"download_ms": report.get("duration_ms")}
        })
        new_dir = self._new_trial_dir()
        if new_dir is not None:
            trial_model.copy_package_artifacts(new_dir, self._download_package_dir)

        self._set_experiment_stage("Descarga", "ok" if download_ok else "fail")
        if download_ok:
            self._set_trial_lifecycle(trial_io_map.STATE_DOWNLOADED)
            self._remember_io_program(self._new_trial_dir())
        if start_success is True:
            self._set_experiment_stage("CPU Start", "ok")
        elif start_success is None and download_ok:
            self._set_experiment_stage("CPU Start", "skipped")
        else:
            self._set_experiment_stage("CPU Start", "fail")

        if self.active_trial:
            legacy_dir = trial_dir(self.project_root, self.active_trial["case_id"], self.active_trial["trial_id"])
            save_metadata(legacy_dir, {"tia_download_status": report.get("status", "")})

        if download_ok and start_success is not False:
            # Fase 2A: antes de cerrar como PREPARED se lee el estado REAL de la CPU (Runtime
            # API, solo lectura). El resultado es informativo: PREPARED no depende de el.
            self._set_experiment_stage("Runtime", "running")
            self._start_runtime_refresh(
                "post-descarga (ensayo)",
                package_dir=self._download_package_dir,
                on_done=lambda runtime_report, download_report=report: self._complete_experiment_runtime(
                    download_report, runtime_report
                )
            )
        else:
            errors = [str(item) for item in report.get("errors", []) or []]
            self._finalize_new_trial(
                trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR,
                [f"Descarga: {report.get('status')}"] + errors
            )
            self.experiment_status_var.set(f"Ensayo no preparado: {report.get('status')}.")
            messagebox.showerror(
                "Ejecutar ensayo",
                f"El ensayo no pudo prepararse en PLCSIM Advanced ({report.get('status')}).\n\n" + "\n".join(errors)
            )

    def _complete_experiment_runtime(self, download_report: dict[str, Any], runtime_report: dict[str, Any]) -> None:
        """Rellena trial.runtime / cpu_run_confirmed y cierra el ensayo como PREPARED (Fase 2A)."""
        confirmed = plcsim_runtime.is_cpu_run_confirmed(download_report, runtime_report)
        connected = bool(runtime_report.get("connected"))
        self._update_new_trial({
            "runtime": plcsim_runtime.trial_runtime_section(runtime_report),
            "download": {"cpu_run_confirmed": confirmed},
            "stages": {"runtime_connection_success": connected}
        })
        new_dir = self._new_trial_dir()
        if new_dir is not None:
            plcsim_runtime.write_runtime_report(new_dir, runtime_report)
            trial_model.copy_package_artifacts(new_dir, self._download_package_dir)
        cpu_run = connected and runtime_report.get("cpu_state") == plcsim_runtime.CPU_STATE_RUN
        self._set_experiment_stage("Runtime", "ok" if cpu_run else "fail")
        if cpu_run and confirmed:
            self._set_trial_lifecycle(trial_io_map.STATE_RUNTIME_READY)

        oracle, oracle_error = self._case_oracle_for_active_trial()
        if oracle is not None or oracle_error is not None:
            self._run_or_close_with_oracle(oracle, oracle_error, download_report, runtime_report, cpu_run)
            return

        self._finalize_new_trial(trial_model.FINAL_STATUS_PREPARED)
        cpu_text = runtime_report.get("cpu_state") if connected else f"no verificado ({runtime_report.get('status')})"
        self.experiment_status_var.set(f"Ensayo preparado en PLCSIM Advanced. CPU: {cpu_text}.")
        self._log("[EXPERIMENT] Ensayo preparado en PLCSIM Advanced.")
        messagebox.showinfo("Ejecutar ensayo", f"Ensayo preparado en PLCSIM Advanced.\n\nCPU (Runtime API): {cpu_text}")

    # ------------------------------------------------------------------------------------------
    # Fase 3A - Oracle Runner (D03/D07/D12 piloto)
    # ------------------------------------------------------------------------------------------

    def _selected_case_id(self) -> str | None:
        profile = self._experiment_profiles_by_case.get(self.experiment_case_var.get()) or {}
        return profile.get("case_id") or None

    def _refresh_oracle_status(self) -> None:
        case_id = self._selected_case_id()
        if not case_id:
            self.oracle_status_var.set("Oracle: -")
            return
        try:
            oracle = find_case_oracle(self.project_root, case_id)
        except oracle_schema.OracleError as error:
            self.oracle_status_var.set(f"Oracle {case_id}: ERROR ({error.code})")
            return
        if oracle is None:
            self.oracle_status_var.set(f"Oracle: {case_id} sin Oracle (el ensayo termina en PREPARED)")
            return
        approval = oracle["approval"]
        pending = oracle_schema.open_review_items(oracle)
        label = "APROBADO" if oracle_schema.is_formal(oracle) else f"{approval['status']} (solo ensayo de desarrollo)"
        extra = f" · {len(pending)} punto(s) REVIEW abiertos" if pending else ""
        self.oracle_status_var.set(f"Oracle: {case_id} v{approval['version']} · {label}{extra}")

    def view_case_oracle(self) -> None:
        case_id = self._selected_case_id()
        try:
            oracle = find_case_oracle(self.project_root, case_id)
        except oracle_schema.OracleError as error:
            messagebox.showerror("Oracle", f"{error.code}: {error.detail}\n\n" + "\n".join(error.details[:10]))
            return
        if oracle is None:
            messagebox.showinfo("Oracle", f"El caso {case_id or '-'} todavia no tiene Oracle.")
            return
        OracleViewerWindow(self, oracle)

    def open_oracle_review(self) -> None:
        OracleReviewWindow(self)

    def approve_case_oracle(self) -> None:
        self.approve_oracle_interactive(self._selected_case_id())

    def approve_oracle_interactive(self, case_id: str | None, parent: Any = None) -> bool:
        """Aprobacion formal (FROZEN) de UN Oracle, firmada por el investigador."""
        parent = parent or self
        if self._oracle_worker_active:
            messagebox.showwarning("Aprobar Oracle", "Hay un Oracle ejecutandose; espere a que termine.", parent=parent)
            return False
        try:
            oracle = find_case_oracle(self.project_root, case_id)
        except oracle_schema.OracleError as error:
            messagebox.showerror("Aprobar Oracle", f"{error.code}: {error.detail}", parent=parent)
            return False
        if oracle is None:
            messagebox.showinfo("Aprobar Oracle", f"El caso {case_id or '-'} todavia no tiene Oracle.", parent=parent)
            return False
        if oracle_schema.is_formal(oracle):
            messagebox.showinfo(
                "Aprobar Oracle",
                f"El Oracle {case_id} v{oracle['approval']['version']} ya esta {oracle['approval']['status']}.\n"
                "Para cambiarlo hay que crear una version nueva.", parent=parent
            )
            return False
        pending = oracle_schema.open_review_items(oracle)
        review_text = ("\n\nPuntos REVIEW_REQUIRED que quedaran confirmados:\n" + "\n".join(f"- {item['text']}" for item in pending)) if pending else ""
        if not messagebox.askyesno(
            "Aprobar Oracle",
            f"Aprobar y CONGELAR el Oracle {case_id} v{oracle['approval']['version']}?\n"
            "Despues no podra modificarse (solo crear una version nueva)." + review_text, parent=parent
        ):
            return False
        reviewer = simpledialog.askstring("Aprobar Oracle", "Identificador del investigador que aprueba:", parent=parent)
        if not reviewer or not reviewer.strip():
            return False
        try:
            approved = oracle_schema.approve_oracle(self.project_root, case_id, reviewer, acknowledge_review_items=True)
        except (oracle_schema.OracleError, ValueError) as error:
            messagebox.showerror("Aprobar Oracle", str(error), parent=parent)
            return False
        self._log(
            f"[ORACLE] {case_id} v{approved['approval']['version']} {approved['approval']['status']} por {reviewer} "
            f"(hash {approved['approval']['hash'][:16]}...)"
        )
        self._refresh_oracle_status()
        return True

    def _case_oracle_for_active_trial(self) -> tuple[dict[str, Any] | None, str | None]:
        case_id = (self.active_trial or {}).get("case_id")
        try:
            return find_case_oracle(self.project_root, case_id), None
        except oracle_schema.OracleError as error:
            return None, f"{error.code}: {error.detail}"

    def _run_or_close_with_oracle(
        self,
        oracle: dict[str, Any] | None,
        oracle_error: str | None,
        download_report: dict[str, Any],
        runtime_report: dict[str, Any],
        cpu_run: bool
    ) -> None:
        if oracle_error is not None:
            self._set_experiment_stage("Oracle", "fail")
            self._log(f"[ORACLE] {oracle_error}")
            self._close_trial_with_oracle_status(trial_model.FINAL_STATUS_REVIEW, [oracle_error])
            return
        if not cpu_run:
            self._set_experiment_stage("Oracle", "skipped")
            reason = f"{oracle_runner.RUNTIME_NOT_READY}: CPU no confirmada en RUN ({runtime_report.get('status')}, {runtime_report.get('cpu_state')})."
            self._log(f"[ORACLE] {reason}")
            self._update_new_trial({"oracle_reference": oracle_schema.oracle_reference(oracle)})
            self._close_trial_with_oracle_status(trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR, [reason])
            return
        self._start_oracle_run(oracle, runtime_report)

    def _start_oracle_run(self, oracle: dict[str, Any], runtime_report: dict[str, Any]) -> None:
        new_dir = self._new_trial_dir()
        snapshot_path = new_dir / trial_io_map.SNAPSHOT_FILENAME if new_dir else None
        semantic_path = new_dir / "semantic_output.json" if new_dir else None
        semantic_output = load_json_file(semantic_path) if semantic_path and semantic_path.exists() else None
        target_type = str(resolve_download_target(load_tia_config(self.project_root), DOWNLOAD_PURPOSE_EXPERIMENT).get("target_type") or "")
        kind = oracle_runner.TRIAL_KIND_FORMAL if oracle_schema.is_formal(oracle) else oracle_runner.TRIAL_KIND_DEVELOPMENT
        self._oracle_run_context = {"trial_directory": new_dir, "oracle_id": oracle["oracle_id"]}
        self._oracle_worker_active = True
        self._set_trial_lifecycle(trial_io_map.STATE_TESTING)
        self._set_experiment_stage("Oracle", "running")
        self.experiment_status_var.set(f"Oracle {oracle['oracle_id']} en ejecucion ({kind})...")
        self._log(
            f"[ORACLE] {oracle['oracle_id']} v{oracle['approval']['version']} {oracle['approval']['status']} -> {kind}"
        )

        def _worker() -> None:
            try:
                result = run_oracle(oracle, snapshot_path, runtime_report, target_type, semantic_output, self.project_root)
                self._oracle_worker_queue.put(("success", result))
            except Exception as error:  # pragma: no cover - proceso externo
                self._oracle_worker_queue.put(("error", str(error)))

        threading.Thread(target=_worker, name="oracle-runner", daemon=True).start()
        self._poll_oracle_worker()

    def _poll_oracle_worker(self) -> None:
        try:
            outcome, payload = self._oracle_worker_queue.get_nowait()
        except queue.Empty:
            if self._oracle_worker_active:
                self.after(250, self._poll_oracle_worker)
            return
        self._oracle_worker_active = False
        if outcome == "error":
            self._set_experiment_stage("Oracle", "fail")
            self._log(f"[ORACLE] Excepcion del Oracle Runner: {payload}")
            self._close_trial_with_oracle_status(trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR, [f"ORACLE_RUNNER_EXCEPTION: {payload}"])
            return
        self._complete_oracle_run(payload)

    def _complete_oracle_run(self, result: dict[str, Any]) -> None:
        new_dir = self._new_trial_dir()
        record = trial_model.load_trial(new_dir) if new_dir else {}
        stages = record.get("stages") or {}
        final_status = oracle_runner.decide_final_status(
            stages.get("compile_success"), stages.get("download_success"), True, result.get("verdict")
        )
        artifacts: dict[str, str] = {}
        if new_dir is not None:
            report = oracle_runner.build_evaluation_report(record, result, final_status)
            artifacts = oracle_runner.write_oracle_artifacts(new_dir, result, report)
        self._update_new_trial(oracle_runner.trial_patch(result, artifacts))

        roles_ok = not (result.get("roles") or {}).get("issues")
        self._set_experiment_stage("Oracle", "ok" if roles_ok and result.get("verdict") != trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR else "fail")
        stage_state = {True: "ok", False: "fail", None: "skipped"}
        self._set_experiment_stage("Functional", stage_state[(result.get("functional") or {}).get("success")])
        self._set_experiment_stage("Safety", stage_state[(result.get("safety") or {}).get("success")])
        functional = result.get("functional") or {}
        safety = result.get("safety") or {}
        for line in (
            f"[ORACLE] Roles: " + ", ".join(f"{role}->{entry['functional_name']}" for role, entry in (result.get("roles") or {}).get("roles", {}).items()),
            f"[ORACLE] Functional: {functional.get('passed_checks')}/{functional.get('total_checks')} -> {functional.get('success')}",
            f"[ORACLE] Safety: {safety.get('critical_violations')} violaciones criticas -> {safety.get('success')}",
            f"[ORACLE] Veredicto: {result.get('verdict')} ({result.get('verdict_reason')}) -> final {final_status}",
        ):
            self._log(line)
        errors = [] if final_status == trial_model.FINAL_STATUS_PASS else list(result.get("errors") or [])[:20]
        self._close_trial_with_oracle_status(final_status, errors, result)

    def _close_trial_with_oracle_status(self, final_status: str, errors: list[str], result: dict[str, Any] | None = None) -> None:
        self._finalize_new_trial(final_status, errors or None)
        result = result or {}
        functional = result.get("functional") or {}
        safety = result.get("safety") or {}
        kind = result.get("trial_kind") or "-"
        summary = (
            f"Ensayo {final_status} · funcional {functional.get('passed_checks', '-')}/{functional.get('total_checks', '-')} · "
            f"seguridad {'OK' if safety.get('success') else ('VIOLACION' if safety.get('success') is False else '-')} · {kind}"
        )
        self.experiment_status_var.set(summary)
        self._log(f"[EXPERIMENT] {summary}")
        details = "\n".join(errors[:8])
        messagebox.showinfo("Ejecutar ensayo", summary + (f"\n\n{details}" if details else ""))

    # ------------------------------------------------------------------------------------------
    # Fase 2A - Conexion PLC / Simulacion (PLCSIM Advanced Runtime API, solo lectura)
    # ------------------------------------------------------------------------------------------

    def _build_plc_connection_panel(self, parent: ctk.CTkFrame) -> None:
        panel = ctk.CTkFrame(parent, corner_radius=12)
        panel.grid(row=1, column=0, pady=(8, 0), sticky="ew")
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(panel, text="Conexión PLC / Simulación", font=self.button_font).grid(
            row=0, column=0, padx=12, pady=(10, 2), sticky="w"
        )
        for row, variable in enumerate(
            (self.plc_config_var, self.plc_runtime_var, self.plc_cpu_var, self.plc_network_var), start=1
        ):
            ctk.CTkLabel(panel, textvariable=variable, font=self.body_font, anchor="w", justify="left", wraplength=260).grid(
                row=row, column=0, padx=12, pady=0, sticky="ew"
            )
        self.refresh_runtime_button = ctk.CTkButton(
            panel, text="ACTUALIZAR ESTADO", command=self.refresh_plc_runtime_status, font=self.button_font
        )
        self.refresh_runtime_button.grid(row=5, column=0, padx=12, pady=(6, 4), sticky="ew")
        self.io_test_button = ctk.CTkButton(
            panel, text="PRUEBA DE I/O", command=self.open_runtime_io_test, font=self.button_font
        )
        self.io_test_button.grid(row=6, column=0, padx=12, pady=(0, 10), sticky="ew")
        self._render_configured_target()

    def _render_configured_target(self) -> None:
        """Lo CONFIGURADO para la descarga (nunca implica conexion)."""
        try:
            target = resolve_download_target(load_tia_config(self.project_root), DOWNLOAD_PURPOSE_NORMAL)
        except Exception:  # pragma: no cover - configuracion ilegible
            target = {}
        interface = target.get("target_interface") or "?"
        self.plc_config_var.set(f"Configurado: {target.get('target_name') or '-'} · {interface}")

    def refresh_plc_runtime_status(self) -> None:
        self._start_runtime_refresh("manual")

    def _start_runtime_refresh(self, reason: str, package_dir: Path | None = None, on_done: Any = None) -> None:
        """Lectura no bloqueante (hilo 'plcsim-runtime'); nunca hay polling continuo."""
        self._runtime_callbacks.append((package_dir, on_done))
        if self._runtime_worker_active:
            return
        self._runtime_worker_active = True
        self.refresh_runtime_button.configure(state="disabled")
        self.plc_runtime_var.set("Runtime: consultando...")
        self._log(f"[PLCSIM RUNTIME] Consultando estado ({reason})")

        def _worker() -> None:
            try:
                self._runtime_worker_queue.put(("success", get_plcsim_runtime_status(self.project_root)))
            except Exception as error:  # pragma: no cover - proceso externo
                self._runtime_worker_queue.put(("error", str(error)))

        threading.Thread(target=_worker, name="plcsim-runtime", daemon=True).start()
        self._poll_runtime_worker()

    def _poll_runtime_worker(self) -> None:
        try:
            outcome, payload = self._runtime_worker_queue.get_nowait()
        except queue.Empty:
            if self._runtime_worker_active:
                self.after(250, self._poll_runtime_worker)
            return

        self._runtime_worker_active = False
        self.refresh_runtime_button.configure(state="normal")
        if outcome == "error":
            report = plcsim_runtime.evaluate_runtime_report(
                {"status": plcsim_runtime.STATUS_RUNTIME_ERROR, "errors": [str(payload)]},
                load_tia_config(self.project_root)
            )
        else:
            report = payload
        self._last_runtime_report = report
        self._render_runtime_report(report)
        for line in plcsim_runtime.format_log_lines(report):
            self._log(line)

        callbacks, self._runtime_callbacks = self._runtime_callbacks, []
        for package_dir, on_done in callbacks:
            if package_dir is not None:
                plcsim_runtime.write_runtime_report(package_dir, report)
                confirmed = plcsim_runtime.apply_runtime_confirmation(package_dir, report)
                self._log(f"[PLCSIM RUNTIME] cpu_run_confirmed = {confirmed}")
            if on_done is not None:
                on_done(report)

    # ------------------------------------------------------------------------------------------
    # Fase 2B - PRUEBA DE I/O (Runtime I/O BOOL, herramienta tecnica)
    # ------------------------------------------------------------------------------------------

    def _remember_io_program(self, trial_directory: Path | None) -> None:
        """El programa que ACABA de descargarse a PLCSIM es la unica fuente de senales de la prueba."""
        snapshot = None
        if trial_directory is not None and (trial_directory / trial_io_map.SNAPSHOT_FILENAME).exists():
            snapshot = trial_directory / trial_io_map.SNAPSHOT_FILENAME
        self._io_program_context = {
            "snapshot_path": snapshot,
            "package_dir": self._download_package_dir,
            "trial_dir": trial_directory,
            "purpose": self._download_purpose
        }

    def _load_io_program(self) -> dict[str, Any]:
        context = self._io_program_context or {}
        package_dir = context.get("package_dir")
        return plcsim_runtime_io.load_program_signals(
            context.get("snapshot_path"), Path(package_dir) / "variables.json" if package_dir else None
        )

    def _io_test_target_type(self) -> str:
        purpose = (self._io_program_context or {}).get("purpose") or DOWNLOAD_PURPOSE_NORMAL
        return str(resolve_download_target(load_tia_config(self.project_root), purpose).get("target_type") or "")

    def _io_test_blocked_reason(self, runtime_report: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
        program = None
        try:
            program = self._load_io_program()
        except plcsim_runtime_io.RuntimeIOError:
            program = None
        instance = plcsim_runtime.load_runtime_config(load_tia_config(self.project_root))["instance_name"]
        allowed, reason = plcsim_runtime_io.io_test_availability(self._io_test_target_type(), runtime_report, instance, program)
        return (program, None) if allowed else (program, reason)

    def open_runtime_io_test(self) -> None:
        """Refresca el estado REAL de PLCSIM y solo entonces decide si se puede abrir la prueba."""
        if self._io_test_window is not None:
            self._io_test_window.focus()
            return
        self._start_runtime_refresh("prueba de I/O", on_done=self._open_runtime_io_window_if_allowed)

    def _open_runtime_io_window_if_allowed(self, runtime_report: dict[str, Any]) -> None:
        program, reason = self._io_test_blocked_reason(runtime_report)
        if reason:
            self._log(f"[PLCSIM IO] Prueba de I/O no disponible: {reason}")
            messagebox.showwarning("Prueba de I/O", f"La prueba de I/O no esta disponible.\n\n{reason}")
            return
        context = self._io_program_context or {}
        trial_directory = context.get("trial_dir")
        report_dir = Path(trial_directory or context.get("package_dir") or (self.project_root / "plcsim_runtime_bridge"))
        self._io_test_window = RuntimeIOTestWindow(
            self, program, self._io_test_target_type(), runtime_report, report_dir, trial_directory
        )

    def _record_runtime_io_report(self, trial_directory: Path | None, report: dict[str, Any]) -> None:
        """Diagnostico de infraestructura en trial.json (runtime_io); nunca functional/PASS."""
        if trial_directory is None:
            return
        try:
            trial_model.update_trial(Path(trial_directory), {"runtime_io": plcsim_runtime_io.trial_runtime_io_section(report)})
        except (OSError, ValueError) as error:  # pragma: no cover - GUI feedback path
            self._log(f"[PLCSIM IO] No se pudo registrar runtime_io en trial.json: {error}")

    def _render_runtime_report(self, report: dict[str, Any]) -> None:
        self._render_configured_target()
        if report.get("connected"):
            self.plc_runtime_var.set(f"Runtime: CONECTADO · {report.get('instance_name')}")
            # RUN / STOP / ... es exactamente lo que reporta la Runtime API (OperatingState).
            detail = " · ".join(
                str(item) for item in (report.get("controller_name"), report.get("controller_short_designation")) if item
            )
            self.plc_cpu_var.set(f"CPU: {report.get('cpu_state') or '?'}" + (f" ({detail})" if detail else ""))
            match_text = {True: "misma subred", False: "SUBRED DISTINTA", None: "sin comprobar"}[report.get("network_match")]
            self.plc_network_var.set(
                f"Red: PLC {report.get('controller_ip') or '?'} · PC {report.get('adapter_ip') or '?'} · {match_text}"
            )
        else:
            self.plc_runtime_var.set(f"Runtime: NO CONECTADO ({report.get('status')})")
            self.plc_cpu_var.set("CPU: no verificado")
            adapter_ip = report.get("adapter_ip")
            self.plc_network_var.set(f"Red: PC {adapter_ip}" if adapter_ip else "Red: -")

    def _apply_tia_report_to_snapshot(
        self,
        snapshot: dict[str, Any],
        report: dict[str, Any]
    ) -> None:
        passed = report.get("status") == "TIA_COMPILATION_PASSED"
        snapshot["tia_openness_text"] = format_json(report)

        combined_files = snapshot.setdefault("combined_files", {})
        saved_paths = combined_files.setdefault("SIEMENS_SCL_V18", {})
        result_path = str(report.get("result_path", ""))
        if result_path:
            saved_paths["tia_compile_report.json"] = result_path

        combined_results = snapshot.setdefault("combined_results", {})
        platform_result = combined_results.get("SIEMENS_SCL_V18", {})
        package_result = platform_result.get("package_result", {})
        rendered_files = package_result.get("rendered_files", {})
        if isinstance(rendered_files, dict):
            rendered_files["tia_compile_report.json"] = report

        combined_verification = snapshot.setdefault("combined_verification", {})
        verification = combined_verification.get("SIEMENS_SCL_V18", {})
        if isinstance(verification, dict):
            verification.update(
                {
                    "tia_openness": report,
                    "tia_openness_status": report.get("status"),
                    "compilation_status": report.get("status"),
                    "is_compilable": passed,
                    "is_valid": passed
                }
            )

        snapshot["verification_text"] = format_json(combined_verification)
        snapshot["files_text"] = self._build_files_summary(combined_files)
        snapshot["validation_ok"] = passed
        snapshot["validation_text"] = (
            "Compilacion TIA Portal V18 aprobada."
            if passed else
            "TIA Portal reporto errores de compilacion."
        )
        snapshot["export_contents"] = self._build_export_contents(
            command_text=snapshot.get("command_text", ""),
            semantic_output=snapshot.get("semantic_output", {}),
            combined_results=combined_results,
            snapshot=snapshot
        )

    def _build_voice_text(self) -> str:
        payload = {
            "audio_file": str(self.voice_audio_path) if self.voice_audio_path else None,
            "transcription": self.voice_transcription or {},
            "save_evidence": self.save_voice_evidence_var.get(),
            "recording": self.speech_recognizer.is_recording(),
            "transcribing": self._voice_worker_active,
            "recording_available": self.speech_recognizer.is_recording_available(),
            "input_device": self.speech_recognizer.get_input_device_info(),
            "available_input_devices": len(self.speech_recognizer.list_input_devices()),
            "max_recording_seconds": self.speech_recognizer.max_recording_seconds,
            "recording_elapsed_seconds": self.speech_recognizer.recording_elapsed_seconds(),
            "auto_stopped": self.speech_recognizer.was_auto_stopped(),
            "silence_rms_threshold": self.speech_recognizer.silence_rms_threshold,
            "transcription_configured": self.speech_recognizer.llm_client.is_transcription_configured(),
            "transcription_language": self.speech_recognizer.transcription_language,
            "transcription_model": self.speech_recognizer.llm_client.get_transcription_model(),
            "transcription_timeout_seconds": self.speech_recognizer.transcription_timeout_seconds,
            "transcription_max_retries": self.speech_recognizer.transcription_max_retries
        }
        return format_json(payload)

    def _build_comparison_text(self, semantic_output: dict[str, Any]) -> str:
        comparison_payload = {
            "parser_mode_requested": semantic_output.get("parser_mode_requested"),
            "parser_mode_used": semantic_output.get("parser_mode_used"),
            "agreement": semantic_output.get("agreement"),
            "decision_reason": semantic_output.get("decision_reason"),
            "rule_result": semantic_output.get("rule_result", {}),
            "llm_result": semantic_output.get("llm_result", {}),
            "llm_usage": semantic_output.get("llm_usage", {})
        }
        return format_json(comparison_payload)

    def _build_confirmation_summary(self, semantic_output: dict[str, Any], target_platforms: list[str]) -> str:
        parameters = semantic_output.get("parameters", {})
        output_tags = sorted(
            value for value in parameters.values()
            if isinstance(value, str) and value.startswith("Q_")
        )
        time_values = {
            key: value for key, value in parameters.items()
            if isinstance(value, str) and value.startswith("T#")
        }
        safety_rules = (self.pending_runtime_config or ({}, {}, {}))[2] if self.pending_runtime_config else {}
        summary = {
            "command_text": semantic_output.get("command_text"),
            "transcript": (self.voice_transcription or {}).get("transcript"),
            "intent_id": semantic_output.get("intent_id"),
            "parameters": parameters,
            "recognized_tags": semantic_output.get("recognized_tags", []),
            "time_values": time_values,
            "affected_outputs": output_tags,
            "ambiguities": semantic_output.get("ambiguities", []),
            "semantic_validation": semantic_output.get("semantic_validation", {}),
            "priority_rules": safety_rules.get("priority_rules", []),
            "platforms": target_platforms
        }
        return format_json(summary)

    def _log(self, message: str) -> None:
        self.console_textbox.configure(state="normal")
        self.console_textbox.insert("end", console_message(message) + "\n")
        self.console_textbox.see("end")
        self.console_textbox.configure(state="disabled")

    def _build_platform_log_text(
        self,
        command_text: str,
        semantic_output: dict[str, Any],
        platform: str,
        platform_result: dict[str, Any]
    ) -> str:
        package_result = platform_result.get("package_result", {})
        verification = platform_result.get("verification", {})
        saved_paths = platform_result.get("saved_paths", {})
        log_payload = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "command_text": command_text,
            "semantic_output": semantic_output,
            "target_platform": platform,
            "project_ir": package_result.get("project_ir", {}),
            "rendered_files": package_result.get("rendered_files", {}),
            "verification_result": verification,
            "saved_paths": saved_paths
        }
        return format_json(log_payload)

    def _build_platform_project_text(self, platform_result: dict[str, Any]) -> str:
        package_result = platform_result.get("package_result", {})
        rendered_files = package_result.get("rendered_files", {})
        saved_paths = platform_result.get("saved_paths", {})
        sections = [
            "=== RESUMEN DEL PAQUETE ===",
            format_json(
                {
                    "package_dir": package_result.get("package_dir", saved_paths.get("package_dir")),
                    "target_platform": package_result.get("target_platform"),
                    "artifacts": saved_paths
                }
            )
        ]

        for file_name in (
            "project_manifest.json",
            "pou_manifest.json",
            "task_config.json",
            "full_program.st",
            "siemens_source.scl",
            "tia_import_manifest.json",
            "tia_compile_report.json"
        ):
            if file_name not in rendered_files:
                continue
            payload = rendered_files[file_name]
            content = payload if isinstance(payload, str) else format_json(payload)
            sections.extend([f"=== {file_name} ===", content])

        return "\n\n".join(sections)

    def _build_files_summary(self, combined_files: dict[str, Any]) -> str:
        sections: list[str] = []
        key_labels = [
            ("package_dir", "Directorio del paquete"),
            ("pou_path", "POU principal"),
            ("implementation_path", "POU implementacion"),
            ("declarations_path", "Declaraciones"),
            ("full_program_path", "Programa completo ST"),
            ("siemens_source.scl", "Fuente Siemens SCL"),
            ("tia_compile_report.json", "Reporte de compilacion TIA"),
            ("pou_manifest.json", "Manifest POU"),
            ("metadata_path", "Log de generacion")
        ]

        for platform in ("SIEMENS_SCL_V18", "OPENPLC_ST", "CODESYS_ST"):
            saved_paths = combined_files.get(platform)
            if not saved_paths:
                continue

            sections.append(f"=== {platform_label(platform)} ===")
            for key, label in key_labels:
                value = saved_paths.get(key)
                if value:
                    sections.append(f"{label}: {value}")
            sections.append("")

        if not sections:
            return "Sin archivos generados."

        sections.append("=== DETALLE JSON ===")
        sections.append(format_json(combined_files))
        return "\n".join(sections)

    def _build_interpretation_snapshot(
        self,
        command_text: str,
        semantic_output: dict[str, Any]
    ) -> dict[str, Any]:
        semantic_validation = semantic_output.get("semantic_validation", {})
        validation_ok = semantic_validation.get("is_valid", False)
        snapshot = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "command_text": command_text,
            "semantic_output": {**semantic_output, "command_text": command_text},
            "voice_text": self._build_voice_text(),
            "intent_text": self._format_intention_text({**semantic_output, "command_text": command_text}),
            "comparison_text": self._build_comparison_text(semantic_output),
            "parameters_text": format_json(semantic_output.get("parameters", {})),
            "ir_text": "Aun no se genero representacion intermedia.",
            "pou_text": "Aun no se genero POU.",
            "task_text": "Aun no se genero tarea PLC.",
            "variables_text": "Aun no se genero tabla de variables.",
            "openplc_text": "No generado para esta interpretacion.",
            "codesys_text": "No generado para esta interpretacion.",
            "siemens_text": "No generado para esta interpretacion.",
            "tia_openness_text": format_json(diagnose_tia_openness(self.project_root)),
            "test_cases_text": "No se generaron casos de prueba en esta etapa.",
            "verification_text": format_json(semantic_validation),
            "files_text": "Aun no se guardaron archivos.",
            "combined_results": {},
            "combined_verification": semantic_validation,
            "combined_files": {},
            "validation_ok": validation_ok,
            "validation_text": (
                "Interpretacion procesada. Aun no se genero paquete PLC."
                if validation_ok else
                "La interpretacion requiere revision."
            ),
            "preferred_platform": "Interpretacion"
        }
        snapshot["export_contents"] = {
            "Resumen completo": self._build_full_bundle_text(snapshot),
            "Voz": snapshot["voice_text"],
            "Intencion": snapshot["intent_text"],
            "Comparacion reglas/LLM": snapshot["comparison_text"],
            "Parametros": snapshot["parameters_text"],
            "Verificacion": snapshot["verification_text"]
        }
        return snapshot

    def _make_json_safe(self, payload: Any) -> Any:
        return json.loads(json.dumps(payload, ensure_ascii=False, default=str))

    def _build_history_record_key(self, history_record: dict[str, Any]) -> str:
        history_id = str(history_record.get("history_id", "")).strip()
        if history_id:
            return history_id

        snapshot = history_record.get("snapshot", {})
        semantic_output = snapshot.get("semantic_output", {}) if isinstance(snapshot, dict) else {}
        return (
            f"legacy::{history_record.get('timestamp', '')}::"
            f"{history_record.get('platform', '')}::"
            f"{semantic_output.get('intent_id', history_record.get('intent_id', 'INT_UNKNOWN'))}::"
            f"{history_record.get('command_text', '')}"
        )

    def _append_history_record_to_ui(self, history_record: dict[str, Any]) -> None:
        item_id = append_history_row(
            self.history_tree,
            history_record["timestamp"],
            history_record["command_text"],
            history_record["intent_id"],
            history_record["platform"],
            history_record["is_valid"]
        )
        self.history_item_map[item_id] = history_record["snapshot"]

    def _store_history_record(self, history_record: dict[str, Any], persist: bool = True) -> bool:
        normalized_record = self._make_json_safe(history_record)
        if not isinstance(normalized_record.get("snapshot"), dict):
            return False

        history_key = self._build_history_record_key(normalized_record)
        normalized_record["history_id"] = history_key
        if history_key in self.history_record_keys:
            return False

        self.history_record_keys.add(history_key)
        self.history_records.append(normalized_record)
        self._append_history_record_to_ui(normalized_record)

        if persist:
            self._save_history_state()

        return True

    def _save_history_state(self) -> bool:
        payload = {
            "version": 1,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "records": self.history_records
        }
        try:
            self.history_storage_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            return True
        except OSError as error:  # pragma: no cover - local filesystem path
            self._log(f"No se pudo guardar el historial persistente: {error}")
            return False

    def _clear_history_ui(self) -> None:
        self.history_tree.delete(*self.history_tree.get_children())
        self.history_records = []
        self.history_item_map = {}
        self.history_record_keys = set()

    def _history_records_from_file(self) -> list[dict[str, Any]]:
        if not self.history_storage_path.exists():
            return []

        payload = json.loads(self.history_storage_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [entry for entry in payload if isinstance(entry, dict)]
        if isinstance(payload, dict):
            records = payload.get("records", [])
            if isinstance(records, list):
                return [entry for entry in records if isinstance(entry, dict)]
        return []

    def _import_history_from_metadata_logs(self) -> int:
        imported_count = 0
        log_directories = [
            self.generated_dir / "SIEMENS" / "logs",
            self.generated_dir / "OPENPLC" / "logs",
            self.generated_dir / "CODESYS" / "logs"
        ]

        for logs_dir in log_directories:
            if not logs_dir.exists():
                continue

            for metadata_path in sorted(logs_dir.glob("*.json")):
                try:
                    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue

                if not isinstance(payload, dict):
                    continue

                semantic_output = {
                    "intent_id": payload.get("intent_id", "INT_UNKNOWN"),
                    "case_id": payload.get("case_id"),
                    "command_text": payload.get("command_text", ""),
                    "parameters": payload.get("parameters", {}),
                    "confidence": 1.0,
                    "parser_mode_requested": None,
                    "parser_mode_used": None
                }
                target_platform = payload.get("target_platform", "CODESYS_ST")
                verification_result = payload.get("verification_result", {})
                rendered_artifacts = payload.get("rendered_artifacts", {})
                project_ir = payload.get("project_ir", {})
                saved_paths = payload.get("saved_paths", {})

                platform_wrapper = {
                    "package_result": {
                        "package_dir": saved_paths.get("package_dir"),
                        "target_platform": target_platform,
                        "project_ir": project_ir,
                        "rendered_files": rendered_artifacts
                    },
                    "verification": verification_result,
                    "saved_paths": saved_paths
                }
                snapshot = {
                    "timestamp": str(payload.get("timestamp", "")),
                    "command_text": payload.get("command_text", ""),
                    "semantic_output": semantic_output,
                    "voice_text": "Registro restaurado desde metadata historica.",
                    "intent_text": self._format_intention_text(semantic_output),
                    "comparison_text": "Comparacion no disponible en registros historicos importados.",
                    "parameters_text": format_json(payload.get("parameters", {})),
                    "ir_text": format_json(project_ir),
                    "pou_text": format_json(project_ir.get("pou", {})),
                    "task_text": format_json(project_ir.get("task", {})),
                    "variables_text": format_json(project_ir.get("pou", {}).get("variables", [])),
                    "openplc_text": (
                        self._build_platform_project_text(platform_wrapper)
                        if target_platform == "OPENPLC_ST" else
                        "No generado para esta ejecucion."
                    ),
                    "codesys_text": (
                        self._build_platform_project_text(platform_wrapper)
                        if target_platform == "CODESYS_ST" else
                        "No generado para esta ejecucion."
                    ),
                    "siemens_text": (
                        self._build_platform_project_text(platform_wrapper)
                        if target_platform == "SIEMENS_SCL_V18" else
                        "No generado para esta ejecucion."
                    ),
                    "tia_openness_text": format_json(
                        rendered_artifacts.get("tia_compile_report.json", {})
                    ),
                    "test_cases_text": format_json(rendered_artifacts.get("test_cases.json", [])),
                    "verification_text": format_json(verification_result),
                    "files_text": self._build_files_summary({target_platform: saved_paths}),
                    "combined_results": {target_platform: platform_wrapper},
                    "combined_verification": {target_platform: verification_result},
                    "combined_files": {target_platform: saved_paths},
                    "validation_ok": verification_result.get("is_valid", False),
                    "validation_text": (
                        "Registro historico restaurado desde metadata."
                        if verification_result.get("is_valid", False) else
                        "Registro historico restaurado con incidencias de verificacion."
                    ),
                    "preferred_platform": target_platform
                }
                snapshot["export_contents"] = self._build_export_contents(
                    command_text=snapshot["command_text"],
                    semantic_output=semantic_output,
                    combined_results={target_platform: platform_wrapper},
                    snapshot=snapshot
                )

                imported = self._store_history_record(
                    {
                        "history_id": f"log::{metadata_path.resolve()}",
                        "timestamp": snapshot["timestamp"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "command_text": snapshot["command_text"],
                        "intent_id": semantic_output.get("intent_id", "INT_UNKNOWN"),
                        "platform": target_platform,
                        "is_valid": verification_result.get("is_valid", False),
                        "snapshot": snapshot
                    },
                    persist=False
                )
                if imported:
                    imported_count += 1

        return imported_count

    def _load_history_state(self) -> None:
        self._clear_history_ui()
        loaded_count = 0

        try:
            file_records = self._history_records_from_file()
            for history_record in file_records:
                if self._store_history_record(history_record, persist=False):
                    loaded_count += 1

            imported_count = self._import_history_from_metadata_logs()
            if imported_count or file_records:
                self._save_history_state()

            if loaded_count or imported_count:
                self._log(
                    f"Historial cargado: {loaded_count} persistidos, {imported_count} importados desde logs."
                )
        except Exception as error:  # pragma: no cover - GUI startup path
            self._log(f"No se pudo restaurar el historial persistente: {error}")

    def _build_full_bundle_text(self, snapshot: dict[str, Any]) -> str:
        return "\n\n".join(
            [
                "=== VOZ ===",
                snapshot.get("voice_text", ""),
                "=== INTENCION ===",
                snapshot.get("intent_text", ""),
                "=== COMPARACION REGLAS LLM ===",
                snapshot.get("comparison_text", ""),
                "=== PARAMETROS ===",
                snapshot.get("parameters_text", ""),
                "=== REPRESENTACION INTERMEDIA ===",
                snapshot.get("ir_text", ""),
                "=== POU ===",
                snapshot.get("pou_text", ""),
                "=== TAREA ===",
                snapshot.get("task_text", ""),
                # OpenPLC y CODESYS quedan fuera del resumen exportado mientras el
                # enfoque es TIA Openness (ver docs/08_decisiones_tecnicas.md); los
                # textos siguen guardados en el snapshot para una reintegracion facil.
                "=== PROYECTO SIEMENS TIA V18 ===",
                snapshot.get("siemens_text", ""),
                "=== TIA OPENNESS ===",
                snapshot.get("tia_openness_text", ""),
                "=== CASOS DE PRUEBA ===",
                snapshot.get("test_cases_text", ""),
                "=== VERIFICACION ===",
                snapshot.get("verification_text", ""),
                "=== ARCHIVOS ===",
                snapshot.get("files_text", "")
            ]
        )

    def _build_export_contents(
        self,
        command_text: str,
        semantic_output: dict[str, Any],
        combined_results: dict[str, dict[str, Any]],
        snapshot: dict[str, Any]
    ) -> dict[str, str]:
        export_contents = {
            "Resumen completo": self._build_full_bundle_text(snapshot),
            "Voz": snapshot.get("voice_text", ""),
            "Intencion": snapshot.get("intent_text", ""),
            "Comparacion reglas/LLM": snapshot.get("comparison_text", ""),
            "Parametros": snapshot.get("parameters_text", ""),
            "Representacion intermedia": snapshot.get("ir_text", ""),
            "POU": snapshot.get("pou_text", ""),
            "Tarea": snapshot.get("task_text", ""),
            "Casos de prueba": snapshot.get("test_cases_text", ""),
            "Verificacion": snapshot.get("verification_text", ""),
            "Rutas de archivos": snapshot.get("files_text", "")
        }

        for platform in ("SIEMENS_SCL_V18", "OPENPLC_ST", "CODESYS_ST"):
            platform_result = combined_results.get(platform)
            if not platform_result:
                continue

            platform_name = platform_label(platform)
            package_result = platform_result.get("package_result", {})
            rendered_files = package_result.get("rendered_files", {})
            export_contents[f"{platform_name} paquete"] = self._build_platform_project_text(platform_result)
            for file_name, payload in rendered_files.items():
                content = payload if isinstance(payload, str) else format_json(payload)
                export_contents[f"{platform_name} {file_name}"] = content
            export_contents[f"{platform_name} log"] = self._build_platform_log_text(
                command_text=command_text,
                semantic_output=semantic_output,
                platform=platform,
                platform_result=platform_result
            )

        return export_contents

    def _build_result_snapshot(
        self,
        command_text: str,
        semantic_output: dict[str, Any],
        combined_results: dict[str, dict[str, Any]],
        combined_verification: dict[str, Any],
        combined_files: dict[str, Any],
        preferred_platform: str | None = None
    ) -> dict[str, Any]:
        first_result = next(iter(combined_results.values()))
        first_project_ir = first_result.get("package_result", {}).get("project_ir", {})
        variables_table = first_project_ir.get("pou", {}).get("variables", [])
        test_cases = first_project_ir.get("test_cases", [])
        all_valid = all(result["verification"]["is_valid"] for result in combined_results.values())
        validation_text = (
            "Proyecto PLC valido para la plataforma seleccionada."
            if all_valid else
            "CODIGO/PROYECTO NO VALIDO PARA SIMULACION"
        )

        snapshot = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "command_text": command_text,
            "semantic_output": {**semantic_output, "command_text": command_text},
            "voice_text": self._build_voice_text(),
            "intent_text": self._format_intention_text({**semantic_output, "command_text": command_text}),
            "comparison_text": self._build_comparison_text(semantic_output),
            "parameters_text": format_json(semantic_output.get("parameters", {})),
            "ir_text": format_json(first_project_ir),
            "pou_text": format_json(first_project_ir.get("pou", {})),
            "task_text": format_json(first_project_ir.get("task", {})),
            "variables_text": format_json(variables_table),
            "openplc_text": (
                self._build_platform_project_text(combined_results["OPENPLC_ST"])
                if "OPENPLC_ST" in combined_results else
                "No generado para esta ejecucion."
            ),
            "codesys_text": (
                self._build_platform_project_text(combined_results["CODESYS_ST"])
                if "CODESYS_ST" in combined_results else
                "No generado para esta ejecucion."
            ),
            "siemens_text": (
                self._build_platform_project_text(combined_results["SIEMENS_SCL_V18"])
                if "SIEMENS_SCL_V18" in combined_results else
                "No generado para esta ejecucion."
            ),
            "tia_openness_text": format_json(diagnose_tia_openness(self.project_root)),
            "test_cases_text": format_json(test_cases),
            "verification_text": format_json(combined_verification),
            "files_text": self._build_files_summary(combined_files),
            "combined_results": combined_results,
            "combined_verification": combined_verification,
            "combined_files": combined_files,
            "validation_ok": all_valid,
            "validation_text": validation_text,
            "preferred_platform": preferred_platform or next(iter(combined_results))
        }
        snapshot["export_contents"] = self._build_export_contents(
            command_text=command_text,
            semantic_output={**semantic_output, "command_text": command_text},
            combined_results=combined_results,
            snapshot=snapshot
        )
        return snapshot

    def _build_unknown_snapshot(
        self,
        command_text: str,
        semantic_output: dict[str, Any],
        verification_payload: dict[str, Any]
    ) -> dict[str, Any]:
        snapshot = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "command_text": command_text,
            "semantic_output": {**semantic_output, "command_text": command_text},
            "voice_text": self._build_voice_text(),
            "intent_text": self._format_intention_text({**semantic_output, "command_text": command_text}),
            "comparison_text": self._build_comparison_text(semantic_output),
            "parameters_text": format_json(semantic_output.get("parameters", {})),
            "ir_text": "No se construyo una representacion intermedia para INT_UNKNOWN.",
            "pou_text": "No se genero POU para INT_UNKNOWN.",
            "task_text": "No se genero tarea para INT_UNKNOWN.",
            "variables_text": "Sin tabla de variables para una intencion desconocida.",
            "openplc_text": "No se genera proyecto OpenPLC para INT_UNKNOWN.",
            "codesys_text": "No se genera proyecto CODESYS para INT_UNKNOWN.",
            "siemens_text": "No se genera proyecto Siemens para INT_UNKNOWN.",
            "tia_openness_text": "No se ejecuta TIA Openness para INT_UNKNOWN.",
            "test_cases_text": "No se generaron casos de prueba.",
            "verification_text": format_json(verification_payload),
            "files_text": "No se guardaron archivos.",
            "combined_results": {},
            "combined_verification": verification_payload,
            "combined_files": {},
            "validation_ok": False,
            "validation_text": "Se requiere aclaracion del comando.",
            "preferred_platform": "Interpretacion"
        }
        snapshot["export_contents"] = {
            "Resumen completo": self._build_full_bundle_text(snapshot),
            "Voz": snapshot["voice_text"],
            "Intencion": snapshot["intent_text"],
            "Comparacion reglas/LLM": snapshot["comparison_text"],
            "Parametros": snapshot["parameters_text"],
            "Verificacion": snapshot["verification_text"]
        }
        return snapshot

    def _refresh_export_options(self, snapshot: dict[str, Any] | None) -> None:
        values = list((snapshot or {}).get("export_contents", {}).keys()) or ["Resumen completo"]
        self.export_selector.configure(values=values)
        self.export_option_var.set(values[0])

    def _restore_snapshot(self, snapshot: dict[str, Any], focus_tab: bool = True) -> None:
        self.current_result_snapshot = snapshot
        self.command_textbox.delete("1.0", "end")
        self.command_textbox.insert("1.0", snapshot.get("command_text", ""))

        self._set_textbox_content(self.voice_textbox, snapshot.get("voice_text", self._build_voice_text()))
        self._set_textbox_content(self.intent_textbox, snapshot.get("intent_text", "Sin resultados."))
        self._set_textbox_content(self.comparison_textbox, snapshot.get("comparison_text", "Sin comparacion disponible."))
        self._set_textbox_content(self.parameters_textbox, snapshot.get("parameters_text", "Sin resultados."))
        self._set_textbox_content(self.ir_textbox, snapshot.get("ir_text", "Sin resultados."))
        self._set_textbox_content(self.pou_textbox, snapshot.get("pou_text", "Sin resultados."))
        self._set_textbox_content(self.task_textbox, snapshot.get("task_text", "Sin resultados."))
        self._set_textbox_content(self.openplc_textbox, snapshot.get("openplc_text", "No generado para esta ejecucion."))
        self._set_textbox_content(self.codesys_textbox, snapshot.get("codesys_text", "No generado para esta ejecucion."))
        self._set_textbox_content(self.siemens_textbox, snapshot.get("siemens_text", "No generado para esta ejecucion."))
        self._set_textbox_content(self.tia_openness_textbox, snapshot.get("tia_openness_text", "Sin ejecucion TIA."))
        self._set_textbox_content(self.test_cases_textbox, snapshot.get("test_cases_text", "Sin resultados."))
        self._set_textbox_content(self.verification_textbox, snapshot.get("verification_text", "Sin resultados."))
        self._set_textbox_content(self.files_textbox, snapshot.get("files_text", "Sin archivos generados."))
        self._set_validation_banner(snapshot.get("validation_text", "Sin ejecucion reciente."), snapshot.get("validation_ok"))
        self._refresh_export_options(snapshot)

        if focus_tab:
            preferred_platform = snapshot.get("preferred_platform")
            if preferred_platform == "OPENPLC_ST":
                self._select_results_tab("Proyecto OpenPLC")
            elif preferred_platform == "CODESYS_ST":
                self._select_results_tab("Proyecto CODESYS")
            elif preferred_platform == "SIEMENS_SCL_V18":
                self._select_results_tab("Proyecto Siemens")
            elif preferred_platform == "TIA_OPENNESS":
                self._select_results_tab("TIA Openness")
            else:
                self._select_results_tab("Interpretacion")

    def _selected_history_item(self) -> str | None:
        selection = self.history_tree.selection()
        return selection[0] if selection else None

    def _selected_history_snapshot(self) -> dict[str, Any] | None:
        item_id = self._selected_history_item()
        if item_id is None:
            return None
        return self.history_item_map.get(item_id)

    def _on_history_tree_selected(self, _event: tk.Event) -> None:
        self.restore_selected_history_item(show_warning=False)

    def _on_history_tree_double_click(self, _event: tk.Event) -> None:
        self.restore_selected_history_item(show_warning=False)

    def restore_selected_history_item(self, show_warning: bool = True) -> None:
        snapshot = self._selected_history_snapshot()
        if snapshot is None:
            if show_warning:
                messagebox.showwarning("Historial", "Seleccione un elemento del historial.")
            return

        self._restore_snapshot(snapshot)
        self._log("Resultado restaurado desde el historial.")

    def _export_text_content(self, content_name: str, content_text: str) -> None:
        if not content_text.strip():
            messagebox.showwarning("Exportar TXT", "No hay contenido disponible para exportar.")
            return

        snapshot = self.current_result_snapshot or {}
        command_text = snapshot.get("command_text", "resultado")
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_name = sanitize_filename(content_name).lower()
        safe_command = sanitize_filename(command_text)[:40].lower()
        default_name = f"{timestamp}_{safe_command}_{safe_name}.txt"

        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="Guardar como TXT",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Archivo de texto", "*.txt"), ("Todos los archivos", "*.*")]
        )
        if not file_path:
            return

        Path(file_path).write_text(content_text, encoding="utf-8")
        self._log(f"Archivo TXT exportado: {file_path}")
        messagebox.showinfo("Exportar TXT", f"Archivo guardado correctamente.\n\n{file_path}")

    def export_selected_result_to_txt(self) -> None:
        snapshot = self.current_result_snapshot
        if snapshot is None:
            messagebox.showwarning("Exportar TXT", "No existe un resultado cargado para exportar.")
            return

        selected_option = self.export_option_var.get()
        content = snapshot.get("export_contents", {}).get(selected_option, "")
        self._export_text_content(selected_option, content)

    def export_full_bundle_to_txt(self) -> None:
        snapshot = self.current_result_snapshot
        if snapshot is None:
            messagebox.showwarning("Exportar TXT", "No existe un resultado cargado para exportar.")
            return

        self._export_text_content("Resumen completo", self._build_full_bundle_text(snapshot))

    def _load_io_map_table(self) -> None:
        load_rows_into_treeview(self.io_tree, self.io_variables, IO_TREE_COLUMNS)

    def _collect_io_variables(self) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for entry in treeview_rows(self.io_tree, IO_TREE_COLUMNS):
            advanced = self.io_variable_metadata.get(entry.get("name", ""), {})
            merged.append(normalize_variable_entry({**entry, **advanced}))
        return merged

    def _load_active_map_metadata_shadow(self) -> None:
        """Populate the advanced-fields shadow dict from the raw active map file."""
        self.io_variable_metadata = {}
        try:
            raw_payload = load_json_file(self.io_map_path)
        except (FileNotFoundError, ValueError):
            return
        for entry in raw_payload.get("variables", []):
            name = entry.get("name")
            if not name:
                continue
            self.io_variable_metadata[name] = {
                field: entry.get(field, default) for field, default in ADVANCED_VARIABLE_DEFAULTS.items()
            }

    def _refresh_map_selector_values(self) -> None:
        summaries = list_plc_maps(self.project_root)
        self._map_summaries_by_name = {summary["name"]: summary for summary in summaries}
        names = list(self._map_summaries_by_name) or [""]
        self.map_selector.configure(values=names)
        current_name = next(
            (summary["name"] for summary in summaries if summary["path"] == self.io_map_path),
            names[0]
        )
        self.active_map_var.set(current_name)
        current_summary = self._map_summaries_by_name.get(current_name, {})
        self._refresh_map_sync_status(current_summary.get("sync_status", "unknown"))
        self._refresh_profile_status()
        if hasattr(self, "experiment_status_var"):
            self._refresh_experiment_status()

    def _refresh_profile_selector_values(self) -> None:
        profiles = load_profiles(self.project_root)
        self._profiles_by_name = {profile["name"]: profile for profile in profiles}
        names = [GENERAL_PROFILE_LABEL] + list(self._profiles_by_name)
        self.profile_selector.configure(values=names)
        current_name = next(
            (profile["name"] for profile in profiles if profile["profile_id"] == self.active_profile_id),
            GENERAL_PROFILE_LABEL
        )
        self.active_profile_var.set(current_name)
        self._refresh_profile_status()

    def _refresh_profile_status(self) -> None:
        map_variable_count = len(self.io_variables)
        if self.active_profile_id is None:
            self.profile_status_var.set(f"Perfil: {GENERAL_PROFILE_LABEL}\nVariables mapa: {map_variable_count}")
            return

        profile = get_profile(self.project_root, self.active_profile_id)
        if profile is None:
            self.profile_status_var.set(f"Perfil: {self.active_profile_id} (no encontrado)")
            return

        readiness = profile_readiness_summary(self.project_root, profile)
        simulation_text = "Simulation: " + (
            "✓ Ready" if readiness["simulation_ready"]
            else f"⚠ Faltan {len(readiness['missing_simulation_variables'])} variables"
        )
        hardware_text = "Hardware: " + (
            "✓ Ready" if readiness["hardware_ready"]
            else f"⚠ Faltan {len(readiness['missing_hardware_variables'])} variables"
        )
        self.profile_status_var.set(
            f"Perfil: {profile['name']}\n"
            f"Variables mapa: {map_variable_count}   Variables perfil: {len(profile.get('allowed_variables', []))}\n"
            f"{simulation_text}\n{hardware_text}"
        )

    def on_profile_selected(self, _choice: str | None = None) -> None:
        selected_name = self.active_profile_var.get()
        if selected_name == GENERAL_PROFILE_LABEL:
            self.active_profile_id = None
        else:
            profile = self._profiles_by_name.get(selected_name)
            self.active_profile_id = profile["profile_id"] if profile else None
        self._refresh_profile_status()
        self._log(f"Perfil de prueba activo: {selected_name}.")

    def _refresh_map_sync_status(self, last_known_status: str = "unknown") -> None:
        map_name = self.active_map_var.get() or "-"
        variable_count = len(self.io_variables)
        if self.active_map_dirty:
            status_text = "TIA: ⚠ Cambios pendientes"
        elif last_known_status == "synced":
            status_text = "TIA: ✓ Sincronizado"
        elif last_known_status == "error":
            status_text = "TIA: ✕ Error de sincronizacion"
        else:
            status_text = "TIA: ⚠ Cambios pendientes"
        self.map_sync_status_var.set(f"Mapa PLC: {map_name}\n{variable_count} variables\n{status_text}")

    def _mark_active_map_dirty(self) -> None:
        self.active_map_dirty = True
        self._refresh_map_sync_status()

    def _persist_generated_functional_variables(self, generated_functional_variables: list[dict[str, Any]]) -> None:
        """Add newly auto-created functional variables (e.g. a setpoint) to the active map and save it."""
        if not generated_functional_variables:
            return
        trial_info = self._trial_io()
        if trial_info is not None:
            # Ensayo: las variables internas generadas se registran como evidencia en el snapshot
            # congelado; el mapa base de Modo Normal no se modifica.
            try:
                added = trial_io_map.record_generated_internal_variables(trial_info["io_map"], generated_functional_variables)
                if added:
                    self._log("[EXPERIMENT IO] Variables internas generadas registradas en el snapshot: " + ", ".join(added))
            except (OSError, ValueError) as error:  # pragma: no cover - GUI feedback path
                self._log(f"[EXPERIMENT IO] No se pudieron registrar las variables internas generadas: {error}")
            return

        existing_names = {row["name"] for row in self._collect_io_variables()}
        added_labels: list[str] = []
        for variable in generated_functional_variables:
            name = variable.get("name", "")
            if not name or name in existing_names:
                continue
            entry = normalize_variable_entry(
                {
                    "name": name,
                    "class": variable.get("var_class", "internal"),
                    "type": variable.get("data_type", "BOOL"),
                    "location": variable.get("location") or "",
                    "initial_value": variable.get("initial_value") or "",
                    "description": variable.get("description", "")
                }
            )
            self.io_tree.insert("", "end", values=[entry[column] for column in IO_TREE_COLUMNS])
            self.io_variable_metadata[name] = {field: entry[field] for field in ADVANCED_VARIABLE_DEFAULTS}
            existing_names.add(name)
            added_labels.append(f"{name} ({entry['type']})")

        if not added_labels:
            return
        try:
            save_plc_map(self.io_map_path, self._collect_io_variables())
            self.io_variables = self._collect_io_variables()
            self._refresh_map_selector_values()
            self._log("Variables funcionales nuevas persistidas en el mapa activo: " + ", ".join(added_labels) + ".")
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo persistir la variable funcional nueva en el mapa activo: {error}")

    def _load_runtime_configuration(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        trial_info = self._trial_io()
        if trial_info is not None:
            # Ensayo experimental: el working map del ensayo (inventario fisico completo, mismo
            # IOAllocator que Modo Normal). El filtro allowed_variables del perfil es la politica
            # legacy de "mapa congelado" y no se aplica: impedia usar canales FREE.
            io_map = trial_io_map.load_working_map(Path(trial_info["io_map"]["working_map_path"]))
        else:
            io_map = load_json_file(self.io_map_path)
            active_profile = get_profile(self.project_root, self.active_profile_id) if self.active_profile_id else None
            io_map = apply_profile_filter(io_map, active_profile)
        intents_catalog = load_json_file(self.intents_catalog_path)
        safety_rules = load_json_file(self.safety_rules_path)
        return io_map, intents_catalog, safety_rules

    def _current_platform_argument(self) -> str | None:
        targets = normalize_platform_targets(self.platform_var.get())
        if len(targets) != 1:
            return None
        return targets[0]

    def _selected_tree_item(self) -> str | None:
        selection = self.io_tree.selection()
        return selection[0] if selection else None

    def _selected_tree_data(self) -> dict[str, str] | None:
        item_id = self._selected_tree_item()
        if item_id is None:
            return None
        values = self.io_tree.item(item_id, "values")
        return {column: str(values[index]) for index, column in enumerate(IO_TREE_COLUMNS)}

    def _run_variable_dialog(self, title: str, variable_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
        dialog = VariableEditorDialog(self, title, variable_data)
        self.wait_window(dialog)
        return dialog.result

    def open_full_io_map_window(self) -> None:
        """[ABRIR MAPA I/O COMPLETO] (seccion 7): ventana independiente con TODOS los canales del
        mapa activo, no solo los que caben en la tabla del panel izquierdo."""
        FullIOMapWindow(self)

    def open_io_map(self) -> None:
        try:
            self.io_variables = load_io_map_variables(self.io_map_path)
            self._load_active_map_metadata_shadow()
            self._load_io_map_table()
            self._log(f"Mapa PLC cargado desde {self.io_map_path.name}.")
            self._refresh_map_sync_status()
            messagebox.showinfo("Mapa PLC", "Mapa PLC cargado correctamente.")
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"Error al abrir el mapa PLC: {error}")
            messagebox.showerror("Mapa PLC", f"No se pudo abrir el mapa PLC.\n\n{error}")

    def save_io_map(self, show_success: bool = True) -> bool:
        variables = self._collect_io_variables()
        errors = validate_io_map_variables(variables)
        if errors:
            self._log("Validacion del mapa PLC rechazada.")
            messagebox.showerror("Mapa PLC", "\n".join(errors[:12]))
            return False

        try:
            save_plc_map(self.io_map_path, variables, metadata_patch={"dirty": False})
            self.io_variables = variables
            self._load_io_map_table()
            self.active_map_dirty = False
            self._refresh_map_selector_values()
            self._log("Mapa PLC guardado correctamente.")
            if show_success:
                messagebox.showinfo("Mapa PLC", "Mapa PLC guardado correctamente.")
            return True
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"Error al guardar el mapa PLC: {error}")
            messagebox.showerror("Mapa PLC", f"No se pudo guardar el mapa PLC.\n\n{error}")
            return False

    def add_variable(self) -> None:
        result = self._run_variable_dialog("Agregar variable")
        if result is None:
            return
        self.io_tree.insert("", "end", values=[result[column] for column in IO_TREE_COLUMNS])
        self.io_variable_metadata[result["name"]] = {field: result[field] for field in ADVANCED_VARIABLE_DEFAULTS}
        self._mark_active_map_dirty()
        self._log(f"Variable agregada en tabla: {result['name']}.")

    def edit_variable(self) -> None:
        item_id = self._selected_tree_item()
        selected_data = self._selected_tree_data()
        if item_id is None or selected_data is None:
            messagebox.showwarning("Editar variable", "Seleccione una variable para editar.")
            return

        merged_data = {**selected_data, **self.io_variable_metadata.get(selected_data["name"], {})}
        result = self._run_variable_dialog("Editar variable", merged_data)
        if result is None:
            return

        self.io_tree.item(item_id, values=[result[column] for column in IO_TREE_COLUMNS])
        if selected_data["name"] != result["name"]:
            self.io_variable_metadata.pop(selected_data["name"], None)
        self.io_variable_metadata[result["name"]] = {field: result[field] for field in ADVANCED_VARIABLE_DEFAULTS}
        self._mark_active_map_dirty()
        self._log(f"Variable editada en tabla: {result['name']}.")

    def delete_variable(self) -> None:
        item_id = self._selected_tree_item()
        selected_data = self._selected_tree_data()
        if item_id is None or selected_data is None:
            messagebox.showwarning("Eliminar variable", "Seleccione una variable para eliminar.")
            return

        if not messagebox.askyesno("Eliminar variable", f"Confirma eliminar {selected_data['name']}?"):
            return

        self.io_tree.delete(item_id)
        self.io_variable_metadata.pop(selected_data["name"], None)
        self._mark_active_map_dirty()
        self._log(f"Variable eliminada de la tabla: {selected_data['name']}.")

    def _set_selected_variable_state(self, dialog_title: str, new_state: str) -> None:
        """
        Shared implementation for [Bloquear]/[Desbloquear]/[Marcar como libre] (section 4/5):
        changes ONLY `state` on the selected row - never the physical `location` or the `name`.
        Requires the same explicit row selection as edit/delete, never a silent bulk change.
        """
        item_id = self._selected_tree_item()
        selected_data = self._selected_tree_data()
        if item_id is None or selected_data is None:
            messagebox.showwarning(dialog_title, "Seleccione una variable.")
            return

        name = selected_data["name"]
        current = dict(self.io_variable_metadata.get(name, {}))
        current["state"] = new_state
        self.io_variable_metadata[name] = current

        row_values = list(self.io_tree.item(item_id, "values"))
        state_index = IO_TREE_COLUMNS.index("state")
        row_values[state_index] = new_state
        self.io_tree.item(item_id, values=row_values)

        self._mark_active_map_dirty()
        self._log(f"{name}: estado cambiado a {new_state} (pendiente de guardar).")

    def lock_selected_variable(self) -> None:
        self._set_selected_variable_state("Bloquear variable", "LOCKED")

    def unlock_selected_variable(self) -> None:
        self._set_selected_variable_state("Desbloquear variable", "ASSIGNED")

    def mark_selected_variable_free(self) -> None:
        item_id = self._selected_tree_item()
        selected_data = self._selected_tree_data()
        if item_id is not None and selected_data is not None:
            current_state = self.io_variable_metadata.get(selected_data["name"], {}).get("state")
            if current_state == "LOCKED":
                messagebox.showwarning(
                    "Marcar como libre",
                    f"{selected_data['name']} esta protegida (LOCKED). Desbloquee primero."
                )
                return
        self._set_selected_variable_state("Marcar como libre", "FREE")

    def _confirm_discard_unsaved_map_changes(self) -> bool:
        if not self.active_map_dirty:
            return True
        return messagebox.askyesno(
            "Cambios sin guardar",
            "El mapa activo tiene cambios sin guardar. ¿Desea continuar de todas formas y descartarlos?"
        )

    def on_active_map_selected(self, _choice: str | None = None) -> None:
        selected_name = self.active_map_var.get()
        summary = self._map_summaries_by_name.get(selected_name)
        if summary is None or summary["path"] == self.io_map_path:
            return
        if not self._confirm_discard_unsaved_map_changes():
            self._refresh_map_selector_values()
            return

        save_active_map_id(self.project_root, summary["map_id"])
        self.io_map_path = summary["path"]
        self.active_map_dirty = False
        self.open_io_map()
        self._refresh_map_selector_values()

    def new_plc_map(self) -> None:
        name = simpledialog.askstring("Nuevo mapa PLC", "Nombre del nuevo mapa:", parent=self)
        if not name:
            return
        description = simpledialog.askstring("Nuevo mapa PLC", "Descripcion (opcional):", parent=self) or ""
        try:
            path = create_plc_map(self.project_root, name=name, description=description)
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"Error al crear el mapa PLC: {error}")
            messagebox.showerror("Mapa PLC", f"No se pudo crear el mapa.\n\n{error}")
            return

        summaries = list_plc_maps(self.project_root)
        map_id = next((summary["map_id"] for summary in summaries if summary["path"] == path), path.stem)
        save_active_map_id(self.project_root, map_id)
        self.io_map_path = path
        self.active_map_dirty = False
        self.open_io_map()
        self._refresh_map_selector_values()
        self._log(f"Mapa PLC creado: {name}.")

    def save_plc_map_as(self) -> None:
        name = simpledialog.askstring("Guardar mapa como", "Nombre del nuevo mapa:", parent=self)
        if not name:
            return
        variables = self._collect_io_variables()
        errors = validate_io_map_variables(variables)
        if errors:
            messagebox.showerror("Mapa PLC", "\n".join(errors[:12]))
            return

        try:
            path = create_plc_map(self.project_root, name=name, variables=variables)
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"Error al guardar el mapa como {name}: {error}")
            messagebox.showerror("Mapa PLC", f"No se pudo guardar el mapa.\n\n{error}")
            return

        summaries = list_plc_maps(self.project_root)
        map_id = next((summary["map_id"] for summary in summaries if summary["path"] == path), path.stem)
        save_active_map_id(self.project_root, map_id)
        self.io_map_path = path
        self.active_map_dirty = False
        self.open_io_map()
        self._refresh_map_selector_values()
        self._log(f"Mapa PLC guardado como: {name}.")

    def delete_plc_map_active(self) -> None:
        summaries = list_plc_maps(self.project_root)
        if len(summaries) <= 1:
            messagebox.showwarning("Mapa PLC", "No se puede eliminar el unico mapa disponible.")
            return
        current_name = self.active_map_var.get()
        if not messagebox.askyesno("Eliminar mapa", f"¿Confirma eliminar el mapa '{current_name}'? Esta accion no se puede deshacer."):
            return

        delete_plc_map(self.io_map_path)
        self._log(f"Mapa PLC eliminado: {current_name}.")
        remaining = [summary for summary in summaries if summary["path"] != self.io_map_path]
        fallback = remaining[0]
        save_active_map_id(self.project_root, fallback["map_id"])
        self.io_map_path = fallback["path"]
        self.active_map_dirty = False
        self.open_io_map()
        self._refresh_map_selector_values()

    def validate_plc_map(self) -> None:
        try:
            safety_rules = load_json_file(self.safety_rules_path)
        except (FileNotFoundError, ValueError):
            safety_rules = {}
        variables = self._collect_io_variables()
        result = validate_plc_variable_map({"variables": variables}, safety_rules)
        report_text = format_validation_report(result, len(variables))
        self._log("Validacion de mapa PLC ejecutada.")
        if result["is_valid"]:
            messagebox.showinfo("Validar mapa", report_text)
        else:
            messagebox.showerror("Validar mapa", report_text)

    def sync_plc_map_with_tia(self) -> None:
        if self._map_sync_worker_active or self._tia_worker_active:
            messagebox.showwarning("Sincronizar con TIA", "Ya existe una operacion TIA en curso.")
            return

        try:
            safety_rules = load_json_file(self.safety_rules_path)
        except (FileNotFoundError, ValueError):
            safety_rules = {}
        variables = self._collect_io_variables()
        validation = validate_plc_variable_map({"variables": variables}, safety_rules)
        if not validation["is_valid"]:
            messagebox.showerror("Sincronizar con TIA", format_validation_report(validation, len(variables)))
            return

        diagnostic = diagnose_tia_openness(self.project_root)
        if not diagnostic.get("is_ready"):
            messagebox.showwarning(
                "Sincronizar con TIA",
                "TIA Openness aun no esta listo. Revise el diagnostico y la configuracion del proyecto."
            )
            return

        if not messagebox.askyesno(
            "Confirmar sincronizacion",
            "Se crearan/actualizaran tags en TIA Portal a partir del mapa activo. Nunca se eliminan tags "
            "existentes automaticamente; las diferencias se reportan.\n\n"
            f"Proyecto: {diagnostic.get('project_path')}\n\nNo se descargara nada a un PLC fisico. ¿Continuar?"
        ):
            return

        map_payload = {"variables": variables}
        self._map_sync_worker_active = True
        self.sync_map_button.configure(state="disabled")
        self._log("Iniciando sincronizacion del mapa PLC con TIA Portal.")

        def _worker() -> None:
            try:
                result = sync_map_with_tia(map_payload, self.project_root)
                self._map_sync_worker_queue.put(("sync_success", result))
            except Exception as error:  # pragma: no cover - external Siemens process
                self._map_sync_worker_queue.put(("sync_error", str(error)))

        threading.Thread(target=_worker, name="tia-map-sync", daemon=True).start()
        self.after(250, self._poll_map_sync_worker)

    def import_plc_map_from_tia(self) -> None:
        if self._map_sync_worker_active or self._tia_worker_active:
            messagebox.showwarning("Importar desde TIA", "Ya existe una operacion TIA en curso.")
            return

        diagnostic = diagnose_tia_openness(self.project_root)
        if not diagnostic.get("is_ready"):
            messagebox.showwarning(
                "Importar desde TIA",
                "TIA Openness aun no esta listo. Revise el diagnostico y la configuracion del proyecto."
            )
            return

        if not messagebox.askyesno(
            "Confirmar importacion",
            "Se leeran las tablas de tags del proyecto TIA configurado y se fusionaran con el mapa activo, "
            "preservando aliases/rol semantico/permisos ya definidos localmente.\n\n"
            f"Proyecto: {diagnostic.get('project_path')}\n\n¿Continuar?"
        ):
            return

        map_payload = {"variables": self._collect_io_variables()}
        self._map_sync_worker_active = True
        self.import_map_button.configure(state="disabled")
        self._log("Iniciando importacion de tags desde TIA Portal.")

        def _worker() -> None:
            try:
                result = import_tags_from_tia(map_payload, self.project_root)
                self._map_sync_worker_queue.put(("import_success", result))
            except Exception as error:  # pragma: no cover - external Siemens process
                self._map_sync_worker_queue.put(("import_error", str(error)))

        threading.Thread(target=_worker, name="tia-map-import", daemon=True).start()
        self.after(250, self._poll_map_sync_worker)

    def _poll_map_sync_worker(self) -> None:
        try:
            outcome, payload = self._map_sync_worker_queue.get_nowait()
        except queue.Empty:
            if self._map_sync_worker_active:
                self.after(250, self._poll_map_sync_worker)
            return

        self._map_sync_worker_active = False
        self.sync_map_button.configure(state="normal")
        self.import_map_button.configure(state="normal")

        if outcome in {"sync_error", "import_error"}:
            self._log(f"Error de operacion TIA sobre el mapa PLC: {payload}")
            messagebox.showerror("Mapa PLC / TIA", f"No se pudo completar la operacion.\n\n{payload}")
            return

        if outcome == "sync_success":
            report = payload
            conflicts = report.get("conflicts", [])
            passed = report.get("status") == "TIA_SYNC_PASSED"
            sync_status = "synced" if passed else "error"
            try:
                save_plc_map(self.io_map_path, self._collect_io_variables(), metadata_patch={"sync_status": sync_status, "dirty": False})
                self.active_map_dirty = False
            except Exception as error:  # pragma: no cover - GUI feedback path
                self._log(f"No se pudo persistir el estado de sincronizacion: {error}")
            self._refresh_map_selector_values()
            self._log(f"Sincronizacion con TIA finalizada: {report.get('status')}.")
            messagebox.showinfo("Sincronizar con TIA", format_json(report) if conflicts else "Sincronizacion completada sin conflictos.\n\n" + format_json(report))
            return

        if outcome == "import_success":
            result = payload
            report = result.get("report", {})
            if report.get("status") != "TIA_READ_TAGS_PASSED":
                self._log(f"Importacion desde TIA no se pudo completar: {report.get('status')}.")
                messagebox.showerror("Importar desde TIA", format_json(report))
                return

            merged_variables = result["merged_map"]["variables"]
            load_rows_into_treeview(self.io_tree, [normalize_variable_entry(v) for v in merged_variables], IO_TREE_COLUMNS)
            self.io_variable_metadata = {
                v["name"]: {field: v.get(field, default) for field, default in ADVANCED_VARIABLE_DEFAULTS.items()}
                for v in merged_variables
            }
            self.io_variables = [normalize_variable_entry(v) for v in merged_variables]
            self._mark_active_map_dirty()
            self._log(
                f"Importacion desde TIA completada: {result['new_count']} nuevas, "
                f"{result['refreshed_count']} actualizadas. Revise y guarde el mapa."
            )
            messagebox.showinfo(
                "Importar desde TIA",
                f"{result['new_count']} variables nuevas y {result['refreshed_count']} actualizadas.\n\n"
                "Revise la tabla y use 'Guardar mapa I/O' para persistir los cambios."
            )

    def listen_command(self) -> None:
        self._refresh_voice_settings()
        if self._voice_worker_active:
            messagebox.showwarning("Voz", "Espere a que termine la transcripcion actual.")
            return
        if not self.speech_recognizer.is_recording_available():
            device_error = self.speech_recognizer.get_input_device_info().get("error")
            self._log("Grabacion de voz no disponible en este entorno.")
            messagebox.showwarning(
                "Voz",
                "La captura de audio requiere sounddevice y un microfono disponible."
                + (f"\n\nDetalle: {device_error}" if device_error else "")
            )
            return

        try:
            self.speech_recognizer.discard_audio(self.voice_audio_path)
            self.voice_audio_path = None
            self.voice_transcription = None
            recording_info = self.speech_recognizer.start_recording()
            self._set_status("Escuchando")
            self._set_textbox_content(self.voice_textbox, self._build_voice_text())
            device_name = recording_info.get("input_device", {}).get("name", "Microfono predeterminado")
            self._log(f"Grabacion de voz iniciada con {device_name}.")
            if self._voice_level_poll_job is None:
                self._voice_level_poll_job = self.after(150, self._poll_recording_state)
        except Exception as error:  # pragma: no cover - local microphone path
            self._set_status("Error")
            self._log(f"No fue posible iniciar la grabacion: {error}")
            messagebox.showerror("Voz", f"No fue posible iniciar la grabacion.\n\n{error}")
            self._reset_voice_level_indicator()
        finally:
            self._refresh_voice_button_states()

    def stop_listening(self) -> None:
        if not self.speech_recognizer.is_recording():
            messagebox.showwarning("Voz", "No existe una grabacion en curso.")
            self._refresh_voice_button_states()
            return
        try:
            self.voice_audio_path = self.speech_recognizer.stop_recording()
            self._reset_voice_level_indicator()
            self._log(f"Grabacion detenida: {self.voice_audio_path}.")
            self._set_status("Transcribiendo")
            self._set_textbox_content(self.voice_textbox, self._build_voice_text())
            self._start_voice_transcription()
        except Exception as error:  # pragma: no cover - local microphone path
            self._reset_voice_level_indicator()
            self._set_status("Error")
            self._log(f"Error al detener o transcribir la grabacion: {error}")
            messagebox.showerror("Voz", f"No fue posible completar la grabacion.\n\n{error}")
        finally:
            self._refresh_voice_button_states()

    def _start_voice_transcription(self) -> None:
        if self.voice_audio_path is None or not self.voice_audio_path.exists():
            messagebox.showwarning("Transcribir", "No existe una grabacion disponible.")
            return
        if self._voice_worker_active:
            messagebox.showwarning("Transcribir", "Ya existe una transcripcion en curso.")
            return

        while not self._voice_worker_queue.empty():
            try:
                self._voice_worker_queue.get_nowait()
            except queue.Empty:
                break

        audio_path = self.voice_audio_path
        self._voice_worker_active = True
        self._set_status("Transcribiendo")
        self._set_textbox_content(self.voice_textbox, self._build_voice_text())
        self._refresh_voice_button_states()

        def _worker() -> None:
            try:
                result = self.speech_recognizer.transcribe_audio(audio_path)
                self._voice_worker_queue.put(("success", result))
            except Exception as error:  # pragma: no cover - external API and audio path
                self._voice_worker_queue.put(("error", str(error)))

        threading.Thread(target=_worker, name="voice-transcription", daemon=True).start()
        self.after(100, self._poll_voice_worker)

    def _poll_voice_worker(self) -> None:
        try:
            outcome, payload = self._voice_worker_queue.get_nowait()
        except queue.Empty:
            if self._voice_worker_active:
                self.after(100, self._poll_voice_worker)
            return

        self._voice_worker_active = False
        if outcome == "error":
            self._set_status("Error")
            self._log(f"Error de transcripcion: {payload}")
            messagebox.showerror("Transcribir", f"No se pudo transcribir el audio.\n\n{payload}")
        else:
            self.voice_transcription = payload
            transcript = str(payload.get("transcript", "")).strip()
            error_message = payload.get("error")
            if transcript:
                self.command_textbox.delete("1.0", "end")
                self.command_textbox.insert("1.0", transcript)
                self._set_status("Voz lista")
                self._log(f"Comando de voz transcrito para revision: {transcript}")
            else:
                self._set_status("Error")
                self._log(f"No se obtuvo texto de la grabacion: {error_message or 'voz no inteligible'}")
                messagebox.showwarning(
                    "Transcripcion",
                    error_message or "No se detecto voz inteligible. Intente nuevamente hablando mas cerca del microfono."
                )

        self._set_textbox_content(self.voice_textbox, self._build_voice_text())
        self._select_results_tab("Voz")
        self._refresh_voice_button_states()

    def transcribe_recording(self) -> None:
        if self.voice_audio_path is None:
            messagebox.showwarning("Transcribir", "No existe una grabacion disponible.")
            return
        self._start_voice_transcription()

    def use_transcription(self) -> None:
        transcript = (self.voice_transcription or {}).get("transcript", "").strip()
        if not transcript:
            messagebox.showwarning("Transcripcion", "No hay transcripcion disponible para usar.")
            return
        self.command_textbox.delete("1.0", "end")
        self.command_textbox.insert("1.0", transcript)
        self._set_status("Voz lista")
        self._log("La transcripcion fue copiada al comando editable.")

    def discard_transcription(self) -> None:
        self.speech_recognizer.discard_audio(self.voice_audio_path)
        self.voice_audio_path = None
        self.voice_transcription = None
        self._reset_voice_level_indicator()
        self._set_textbox_content(self.voice_textbox, self._build_voice_text())
        self._set_status("Listo")
        self._refresh_voice_button_states()
        self._log("La grabacion temporal y su transcripcion fueron descartadas.")

    def play_recording(self) -> None:
        if self.voice_audio_path is None or not self.voice_audio_path.exists():
            messagebox.showwarning("Reproducir", "No existe una grabacion disponible.")
            return
        if winsound is None:
            messagebox.showinfo("Reproducir", "La reproduccion local solo esta disponible en Windows.")
            return
        try:
            winsound.PlaySound(str(self.voice_audio_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            self._log("Reproduccion de audio iniciada.")
        except Exception as error:  # pragma: no cover - local audio device
            self._log(f"No fue posible reproducir el audio: {error}")
            messagebox.showerror("Reproducir", f"No fue posible reproducir el audio.\n\n{error}")

    def clear_command(self) -> None:
        self.speech_recognizer.cancel_recording()
        self.speech_recognizer.discard_audio(self.voice_audio_path)
        self._reset_voice_level_indicator()
        self.command_textbox.delete("1.0", "end")
        self.voice_audio_path = None
        self.voice_transcription = None
        self._clear_results()
        self._set_status("Listo")
        self._refresh_voice_button_states()
        self._log("Comando y resultados visuales limpiados.")

    def _on_close(self) -> None:
        if self._voice_level_poll_job is not None:
            try:
                self.after_cancel(self._voice_level_poll_job)
            except Exception:
                pass
            self._voice_level_poll_job = None
        self.speech_recognizer.cancel_recording()
        if not self.save_voice_evidence_var.get():
            self.speech_recognizer.discard_audio(self.voice_audio_path)
        self.destroy()

    def _clear_results(self) -> None:
        self.current_result_snapshot = None
        self.pending_semantic_output = None
        self._set_textbox_content(self.intent_textbox, "Sin resultados.")
        self._set_textbox_content(self.voice_textbox, self._build_voice_text())
        self._set_textbox_content(self.comparison_textbox, "Sin comparacion disponible.")
        self._set_textbox_content(self.parameters_textbox, "Sin resultados.")
        self._set_textbox_content(self.ir_textbox, "Sin resultados.")
        self._set_textbox_content(self.pou_textbox, "Sin resultados.")
        self._set_textbox_content(self.task_textbox, "Sin resultados.")
        self._set_textbox_content(self.openplc_textbox, "No generado para esta ejecucion.")
        self._set_textbox_content(self.codesys_textbox, "No generado para esta ejecucion.")
        self._set_textbox_content(self.siemens_textbox, "No generado para esta ejecucion.")
        self._set_textbox_content(self.tia_openness_textbox, "Sin ejecucion TIA.")
        self._set_textbox_content(self.test_cases_textbox, "Sin resultados.")
        self._set_textbox_content(self.verification_textbox, "Sin resultados.")
        self._set_textbox_content(self.files_textbox, "Sin archivos generados.")
        self._set_validation_banner("Sin ejecucion reciente.", None)
        self._refresh_export_options(None)
        self._select_results_tab("Voz")

    # ------------------------------------------------------------------
    # Modo Experimentacion
    # ------------------------------------------------------------------

    def _on_work_mode_changed(self, _choice: str | None = None) -> None:
        """
        El perfil activo es siempre automatico, nunca una eleccion manual del usuario:
        Normal -> GENERAL (sin filtro, mapa PLC completo); Experimentacion -> perfil del
        caso Dxx seleccionado. El selector "Perfil de prueba" del panel izquierdo queda
        deshabilitado en ambos modos (es solo informativo) para que nadie termine
        generando codigo en Modo Normal con un perfil experimental activo por accidente.
        """
        if self.work_mode_var.get() == "Experimentacion":
            self.profile_selector_label.configure(text="Perfil de prueba (automatico - Modo Experimentacion)")
            self.experiment_controls_frame.grid()
            self._refresh_experiment_case_selector()
            self._on_experiment_condition_changed()
        else:
            self.experiment_controls_frame.grid_remove()
            self.manual_result_frame.grid_remove()
            self.profile_selector_label.configure(text="Contexto (Modo Normal)")
            self.active_profile_id = None
            self._refresh_profile_selector_values()
        self._log(f"Modo de trabajo: {self.work_mode_var.get()}.")

    def _on_experiment_group_changed(self, _choice: str | None = None) -> None:
        if self.experiment_group_var.get().startswith("PID"):
            self._maybe_recommend_pid_map()
        self._refresh_experiment_case_selector()

    def _maybe_recommend_pid_map(self) -> None:
        """
        Seccion 27: preferir MAPA_PID_SIMULACION al entrar al grupo PID, pero nunca cambiar el
        mapa activo en silencio (podria descartar trabajo del usuario). Si el mapa activo no
        tiene los recursos PID, se avisa y se ofrece el cambio explicitamente.
        """
        current_names = {variable.get("name") for variable in self.io_variables}
        if "Q_Pump_Enable" in current_names:
            return
        pid_map_summary = self._map_summaries_by_name.get("MAPA_PID_SIMULACION")
        if pid_map_summary is None:
            messagebox.showwarning(
                "Grupo de pruebas PID",
                "El mapa activo no contiene los recursos requeridos para Pxx y no se encontro "
                "MAPA_PID_SIMULACION en la biblioteca de mapas."
            )
            return
        if pid_map_summary["path"] == self.io_map_path:
            return
        if messagebox.askyesno(
            "Grupo de pruebas PID",
            "El mapa activo no contiene los recursos requeridos para Pxx.\n\n"
            "¿Desea cambiar el mapa activo a MAPA_PID_SIMULACION?"
        ):
            self.active_map_var.set("MAPA_PID_SIMULACION")
            self.on_active_map_selected()

    def _refresh_experiment_case_selector(self) -> None:
        case_prefix = "P" if self.experiment_group_var.get().startswith("PID") else "D"
        profiles = [p for p in load_profiles(self.project_root) if str(p.get("case_id", "")).startswith(case_prefix)]
        self._experiment_profiles_by_case = {profile["name"]: profile for profile in profiles}
        names = list(self._experiment_profiles_by_case)
        if not names:
            self.experiment_case_selector.configure(values=[""])
            self.experiment_case_var.set("")
            self.experiment_status_var.set("No hay perfiles experimentales disponibles.")
            return
        self.experiment_case_selector.configure(values=names)
        if self.experiment_case_var.get() not in self._experiment_profiles_by_case:
            self.experiment_case_var.set(names[0])
        # Solo activar el perfil del caso (active_profile_id) cuando realmente estamos en
        # Modo Experimentacion - de lo contrario esta llamada (tambien usada para poblar el
        # selector al iniciar la app) dejaria un perfil Dxx activo mientras el modo es Normal.
        if self.work_mode_var.get() == "Experimentacion":
            self._on_experiment_case_changed()

    def _on_experiment_case_changed(self, _choice: str | None = None) -> None:
        profile = self._experiment_profiles_by_case.get(self.experiment_case_var.get())
        if profile is None:
            return

        # El caso experimental determina automaticamente el perfil asociado: el usuario
        # ya no elige un perfil por separado en Modo Experimentacion.
        self.active_profile_id = profile.get("profile_id")
        self.active_profile_var.set(profile["name"])
        self._refresh_profile_status()
        # La compatibilidad mostrada corresponde a la ultima interpretacion; al cambiar de
        # caso ya no es valida hasta procesar un comando nuevo contra el caso actual.
        self.pending_semantic_output = None

        case_id = profile.get("case_id", "")
        variants = load_variants_for_case(self.project_root, case_id)
        variant_names = [entry["variant"] for entry in variants] or ["V1"]
        self.experiment_variant_selector.configure(values=variant_names)
        if self.experiment_variant_var.get() not in variant_names:
            self.experiment_variant_var.set(variant_names[0])
        self._update_variant_command_preview()
        self._refresh_experiment_status()

    def _update_variant_command_preview(self) -> None:
        profile = self._experiment_profiles_by_case.get(self.experiment_case_var.get())
        case_id = profile.get("case_id", "") if profile else ""
        variant = self.experiment_variant_var.get()
        command_text = get_variant_command(self.project_root, case_id, variant) if case_id else ""
        self._active_variant_command_text = command_text
        if command_text:
            self.experiment_variant_command_var.set(f'"{command_text}"')
        else:
            self.experiment_variant_command_var.set("(sin texto de referencia para esta variante)")

    def _use_variant_command(self) -> None:
        if not self._active_variant_command_text:
            return
        self.command_textbox.delete("1.0", "end")
        self.command_textbox.insert("1.0", self._active_variant_command_text)

    def _on_experiment_condition_changed(self, _choice: str | None = None) -> None:
        condition = self._selected_condition()
        if condition["noise_locked_to"] is not None:
            self.experiment_noise_var.set(NOISE_LEVEL_LABELS[condition["noise_locked_to"]])
            self.experiment_noise_selector.configure(state="disabled")
        else:
            self.experiment_noise_selector.configure(state="normal")
            if condition["code"] == "C3" and self._last_experiment_condition_code != "C3":
                # C3 arranca "sin ruido" por defecto, pero queda editable de inmediato.
                self.experiment_noise_var.set(NOISE_LEVEL_LABELS["none"])
            if condition.get("noise_required") and self._selected_noise_level() == "none":
                self.experiment_noise_var.set(NOISE_LEVEL_LABELS["medium"])
        self._last_experiment_condition_code = condition["code"]
        self._refresh_experiment_status()

    def _on_experiment_environment_changed(self, _choice: str | None = None) -> None:
        self._refresh_experiment_status()

    def _on_experiment_variant_changed(self, _choice: str | None = None) -> None:
        self._update_variant_command_preview()
        self._refresh_experiment_status()

    def _selected_condition(self) -> dict[str, Any]:
        label = self.experiment_condition_var.get()
        for code, data in CONDITIONS.items():
            if data["label"] == label:
                return {**data, "code": code}
        return {**CONDITIONS["C1"], "code": "C1"}

    def _selected_noise_level(self) -> str:
        label = self.experiment_noise_var.get()
        for level, level_label in NOISE_LEVEL_LABELS.items():
            if level_label == label:
                return level
        return "none"

    def _selected_environment(self) -> str:
        label = self.experiment_environment_var.get()
        for environment, environment_label in ENVIRONMENT_LABELS.items():
            if environment_label == label:
                return environment
        return "simulation"

    def _refresh_experiment_status(self) -> None:
        profile = self._experiment_profiles_by_case.get(self.experiment_case_var.get())
        if profile is None:
            self.experiment_status_var.set("No hay perfiles experimentales disponibles.")
            self.experiment_next_label_var.set("")
            self.start_trial_button.configure(state="disabled")
            return

        readiness = profile_readiness_summary(self.project_root, profile)
        environment = self._selected_environment()
        allowed_variables = profile.get("allowed_variables", [])
        lines = [
            f"Perfil asociado: {profile['profile_id']}",
            f"Variables habilitadas: {len(allowed_variables)}   (mapa: {len(self.io_variables)})",
        ]
        if self.pending_semantic_output is not None:
            compatibility = check_case_compatibility(self.pending_semantic_output, profile)
            if compatibility["compatible"]:
                lines.append("Compatibilidad: ✓ Compatible")
            else:
                lines.append(
                    "Compatibilidad: ⚠ Recursos no autorizados: " + ", ".join(compatibility["missing_external"])
                )
        lines.extend([
            "Simulacion: " + ("✓ Ready" if readiness["simulation_ready"] else f"⚠ Faltan {len(readiness['missing_simulation_variables'])} variables"),
            "Hardware: " + ("✓ Ready" if readiness["hardware_ready"] else "⚠ No listo")
        ])
        if not readiness["hardware_ready"] and readiness["missing_hardware_variables"]:
            lines.append("Faltan: " + ", ".join(readiness["missing_hardware_variables"]))

        if environment == "hardware" and not readiness["hardware_ready"]:
            lines.append("(Nombres del perfil legacy ausentes: se asignaran dinamicamente en el ensayo.)")
        self.experiment_status_var.set("\n".join(lines))
        self.start_trial_button.configure(state="normal")

        condition_code = self._selected_condition()["code"]
        case_id = profile.get("case_id", "")
        variant = self.experiment_variant_var.get()
        next_repetition = compute_next_repetition(self.project_root, condition_code, case_id, variant)
        next_label = build_experiment_label(condition_code, case_id, variant, next_repetition)
        self.experiment_next_label_var.set(f"Proximo ensayo: {next_label}")
        self._refresh_oracle_status()

    EXPERIMENT_STAGES = (
        "Semantica", "I/O", "Generacion", "Verificacion", "Compilacion", "Descarga", "CPU Start", "Runtime",
        "Oracle", "Functional", "Safety"
    )
    _STAGE_SYMBOLS = {"pending": "·", "running": "…", "ok": "✓", "fail": "✗", "skipped": "—"}

    def _reset_experiment_stages(self) -> None:
        self._experiment_stage_states = {stage: "pending" for stage in self.EXPERIMENT_STAGES}
        self._experiment_io_text = ""
        self._render_experiment_stages()

    def _set_experiment_io(self, text: str) -> None:
        self._experiment_io_text = text
        self._render_experiment_stages()

    def _set_experiment_stage(self, stage: str, state: str) -> None:
        self._experiment_stage_states[stage] = state
        self._render_experiment_stages()

    def _render_experiment_stages(self) -> None:
        stages_text = "   ".join(
            f"{self._STAGE_SYMBOLS.get(self._experiment_stage_states.get(stage, 'pending'), '·')} {stage}"
            for stage in self.EXPERIMENT_STAGES
        )
        io_text = getattr(self, "_experiment_io_text", "")
        self.experiment_stage_var.set(stages_text + (f"\nI/O: {io_text}" if io_text else ""))

    def _new_trial_dir(self) -> Path | None:
        info = (self.active_trial or {}).get("new_trial")
        return Path(info["dir"]) if info else None

    def _update_new_trial(self, patch: dict[str, Any]) -> None:
        directory = self._new_trial_dir()
        if directory is None:
            return
        try:
            trial_model.update_trial(directory, patch)
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo actualizar trial.json: {error}")

    def _finalize_new_trial(self, final_status: str, errors: list[str] | None = None) -> None:
        directory = self._new_trial_dir()
        if directory is None:
            return
        try:
            started_perf = self.active_trial.get("new_trial", {}).get("started_perf")
            if started_perf is not None:
                trial_model.update_trial(
                    directory, {"timing": {"end_to_end_ms": int(round((time.perf_counter() - started_perf) * 1000))}}
                )
            self._discard_trial_working_map(final_status)
            trial_model.finalize_trial(directory, final_status, errors)
            self._log(f"[EXPERIMENT] Status -> {final_status}")
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo cerrar trial.json: {error}")

    # ------------------------------------------------------------------------------------------
    # Trial-scoped working I/O map (trial_experiments/trial_io_map.py)
    # ------------------------------------------------------------------------------------------

    def _trial_io(self) -> dict[str, Any] | None:
        """Info del ensayo nuevo si tiene working map vigente (no descartado); si no, None."""
        info = (self.active_trial or {}).get("new_trial") or {}
        reference = info.get("io_map")
        if not reference or reference.get("discarded"):
            return None
        return info

    def _set_trial_lifecycle(self, state: str) -> None:
        info = (self.active_trial or {}).get("new_trial")
        if not info:
            return
        info["lifecycle_state"] = state
        self._update_new_trial({"lifecycle_state": state})

    def _prepare_trial_working_map(self) -> bool:
        """Copia el mapa base (inventario fisico del mapa activo, sin residuos) al ensayo."""
        info = (self.active_trial or {}).get("new_trial")
        if not info:
            return True
        try:
            reference = trial_io_map.create_working_map(Path(info["dir"]), self.io_map_path)
        except trial_io_map.ExperimentIOError as error:
            self._log(f"[EXPERIMENT IO] {error}")
            self._update_new_trial({"io_map": {"error": error.code}})
            self._finalize_new_trial(trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR, [str(error)])
            self._cancel_active_trial(error.code)
            messagebox.showerror("Ejecutar ensayo", f"No se pudo preparar el mapa del ensayo.\n\n{error.detail}")
            return False
        info["io_map"] = reference
        info["lifecycle_state"] = trial_io_map.STATE_PREPARING
        self._update_new_trial({
            "io_map": trial_io_map.trial_record_reference(reference),
            "lifecycle_state": trial_io_map.STATE_PREPARING
        })
        self._log(
            f"[EXPERIMENT IO] Working map creado desde {reference['base_map_id']} "
            f"({reference['physical_channel_count']} canales fisicos)."
        )
        return True

    def _freeze_trial_io(self, semantic_output: dict[str, Any]) -> bool:
        """Freeze de bindings + io_map_snapshot.json, antes de IR/SCL/TIA. True si no aplica."""
        info = self._trial_io()
        if info is None:
            return True
        try:
            reference = trial_io_map.freeze_working_map(
                info["io_map"], semantic_output, info.get("lifecycle_state"), info.get("trial_id")
            )
        except trial_io_map.ExperimentIOError as error:
            self._log(f"[EXPERIMENT IO] {error}")
            self._fail_trial_io(error.code, error.detail)
            messagebox.showerror("Ejecutar ensayo", error.detail)
            return False
        info["io_map"] = reference
        info["lifecycle_state"] = trial_io_map.STATE_IO_RESOLVED
        self._update_new_trial({
            "io_map": trial_io_map.trial_record_reference(reference),
            "lifecycle_state": trial_io_map.STATE_IO_RESOLVED
        })
        self._set_experiment_io("Congeladas")
        self._log(
            f"[EXPERIMENT IO] I/O congeladas: {reference.get('bound_channels')} canales ligados -> "
            f"{trial_io_map.SNAPSHOT_FILENAME}"
        )
        return True

    def _fail_trial_io(self, code: str | None, detail: str) -> None:
        """Cierra el ensayo por un fallo de I/O: nunca compila ni descarga despues de esto."""
        if not self.active_trial:
            return
        trial_id = self.active_trial.get("trial_id", "")
        self._set_experiment_stage("I/O", "fail")
        self._set_experiment_io("Error")
        if code:
            self._update_new_trial({"io_map": {"error": code}})
        final_status = (
            trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR
            if code == trial_io_map.ERROR_SNAPSHOT_FAILED
            else trial_model.FINAL_STATUS_FAIL
        )
        self._finalize_new_trial(final_status, [f"{code}: {detail}" if code else detail])
        try:
            directory = trial_dir(self.project_root, self.active_trial["case_id"], trial_id)
            save_metadata(directory, {"state": "ERROR", "timestamp_end": datetime.now().isoformat(timespec="seconds")})
            self._finalize_trial_summary(compile_result="N/A", execution_result="", error_type="E3")
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo registrar el fallo de I/O del ensayo: {error}")
        finally:
            self._log(f"[EXPERIMENT IO] Ensayo {trial_id} detenido: {code or 'SIN_LOGICA'} - {detail}")
            self.active_trial = None

    def _discard_trial_working_map(self, final_status: str | None) -> None:
        info = (self.active_trial or {}).get("new_trial") or {}
        reference = info.get("io_map")
        if not reference or reference.get("discarded"):
            return
        trial_io_map.discard_working_map(reference)
        reference["discarded"] = True
        patch: dict[str, Any] = {"io_map": {"discarded": True}}
        if final_status in trial_io_map.LIFECYCLE_STATES:
            info["lifecycle_state"] = final_status
            patch["lifecycle_state"] = final_status
        self._update_new_trial(patch)

    def _create_new_trial_record(self, profile: dict[str, Any], case_id: str, variant: str, condition: dict[str, Any]) -> None:
        """Nuevo modelo de ensayo (Fase 1) en paralelo al registro legacy TRIAL_000NNN."""
        try:
            input_mode = trial_model.input_mode_from_selection(
                bool(condition.get("requires_voice")), self._selected_noise_level()
            )
            number = trial_model.next_trial_number(self.project_root, case_id, variant, input_mode)
            record = trial_model.new_trial_record(
                case_id,
                variant,
                input_mode,
                number,
                complexity=profile.get("complexity"),
                extra={
                    "legacy_trial_id": self.active_trial.get("trial_id"),
                    "legacy_experiment_label": self.active_trial.get("experiment_label"),
                    "legacy_condition": condition.get("code"),
                    "parser_mode": condition.get("parser_mode"),
                    "speaker_id": self.active_trial.get("speaker_id"),
                    "noise_level": self.active_trial.get("noise_level"),
                    "map_name": self.active_trial.get("map_name"),
                    "profile_id": self.active_trial.get("profile_id"),
                    "reference_command_text": self.active_trial.get("reference_command_text"),
                    "git_commit": self.active_trial.get("git_commit"),
                    **{key: value for key, value in benchmark_catalog.trial_benchmark_reference(self.project_root, case_id, variant).items()
                       if key in ("benchmark_version", "canonical_case_hash", "variant_hash")}
                }
            )
            directory = trial_model.trial_directory(self.project_root, case_id, variant, record["trial_id"])
            trial_model.save_trial(directory, record)
            self.active_trial["new_trial"] = {
                "trial_id": record["trial_id"],
                "dir": str(directory),
                "started_perf": time.perf_counter()
            }
            self._log(f"[EXPERIMENT] Trial: {record['trial_id']}")
            self._log("[EXPERIMENT] Generation started")
        except (ValueError, OSError) as error:
            self._log(f"No se pudo crear el registro de ensayo nuevo (trial.json): {error}")

    def start_trial(self) -> bool:
        """Arma un nuevo ensayo (trial_id + metadata inicial) sin ejecutar el pipeline todavia."""
        profile = self._experiment_profiles_by_case.get(self.experiment_case_var.get())
        if profile is None:
            messagebox.showwarning("Ejecutar ensayo", "Seleccione un caso valido.")
            return False
        speaker_id = self.experiment_speaker_var.get().strip()
        if not speaker_id:
            messagebox.showwarning("Ejecutar ensayo", "Indique un identificador de participante anonimo (ej. P01).")
            return False

        condition = self._selected_condition()
        environment = self._selected_environment()
        readiness = profile_readiness_summary(self.project_root, profile)
        if environment == "hardware" and not readiness["hardware_ready"]:
            # Legacy (perfiles D01-D20 con mapa congelado): los nombres de allowed_variables ya no
            # tienen que existir de antemano - el ensayo los resuelve dinamicamente con el
            # IOAllocator sobre su working map. Solo informativo.
            self._log(
                f"[EXPERIMENT IO] Perfil legacy {profile['profile_id']}: nombres no presentes en el mapa "
                f"({', '.join(readiness['missing_hardware_variables'])}); se asignaran dinamicamente."
            )

        trial_id = next_trial_id(self.project_root)
        case_id = profile.get("case_id", "")
        variant = self.experiment_variant_var.get()
        repetition = compute_next_repetition(self.project_root, condition["code"], case_id, variant)
        experiment_label = build_experiment_label(condition["code"], case_id, variant, repetition)
        active_map_summary = self._map_summaries_by_name.get(self.active_map_var.get(), {})

        self.active_trial = {
            "trial_id": trial_id,
            "experiment_label": experiment_label,
            "repetition": repetition,
            "case_id": case_id,
            "experiment_family": "PID" if case_id.startswith("P") else "DISCRETE",
            "condition": condition["code"],
            "variant": variant,
            "reference_command_text": self._active_variant_command_text,
            "speaker_id": speaker_id,
            "noise_level": self._selected_noise_level(),
            "environment": environment,
            "timestamp_start": datetime.now().isoformat(timespec="seconds"),
            "map_name": self.active_map_var.get(),
            "map_version": active_map_summary.get("version", ""),
            "profile_id": profile.get("profile_id", ""),
            "parser_mode": condition["parser_mode"],
            "requires_voice": condition["requires_voice"],
            "git_commit": get_git_commit(self.project_root),
            "state": "RUNNING"
        }

        parser_ui_map = {"llm": "LLM", "rule_based": "Reglas", "hybrid": "Hibrido"}
        self.parser_mode_var.set(parser_ui_map.get(condition["parser_mode"], "Hibrido"))

        directory = trial_dir(self.project_root, case_id, trial_id)
        save_metadata(directory, self.active_trial)
        self._reset_experiment_stages()
        self._create_new_trial_record(profile, case_id, variant, condition)
        if not self._prepare_trial_working_map():
            return False

        self.manual_result_frame.grid_remove()
        self.experiment_status_var.set(f"Ensayo {trial_id} ({experiment_label}) creado.")
        self.experiment_next_label_var.set(f"Ensayo activo: {experiment_label}")
        self._log(f"Ensayo {trial_id} iniciado: {experiment_label} / {speaker_id}.")
        return True

    def run_experiment_trial(self) -> None:
        """Boton EJECUTAR ENSAYO: arma el ensayo y corre el mismo pipeline automatico que EJECUTAR COMANDO."""
        if not self.start_trial():
            return
        self.execute_full_pipeline()

    def _compute_total_time(self, start_iso: str | None, end_iso: str | None) -> float:
        if not start_iso or not end_iso:
            return 0.0
        try:
            return round((datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)).total_seconds(), 3)
        except ValueError:
            return 0.0

    def _finalize_trial_summary(self, compile_result: str, execution_result: str, error_type: str) -> None:
        if not self.active_trial:
            return
        summary_row = {
            "trial_id": self.active_trial.get("trial_id", ""),
            "experiment_label": self.active_trial.get("experiment_label", ""),
            "case_id": self.active_trial.get("case_id", ""),
            "condition": self.active_trial.get("condition", ""),
            "variant": self.active_trial.get("variant", ""),
            "repetition": self.active_trial.get("repetition", ""),
            "speaker_id": self.active_trial.get("speaker_id", ""),
            "noise_level": self.active_trial.get("noise_level", ""),
            "compile_result": compile_result,
            "execution_result": execution_result,
            "safety_violation": self.active_trial.get("safety_violation", ""),
            "total_time": self.active_trial.get("total_time", ""),
            "error_type": error_type,
            "timestamp": self.active_trial.get("timestamp_start", ""),
            "map_name": self.active_trial.get("map_name", ""),
            "profile_id": self.active_trial.get("profile_id", "")
        }
        record_trial_summary(self.project_root, summary_row)
        self._refresh_experiment_history_tab()

    def _cancel_active_trial(self, reason: str) -> None:
        if not self.active_trial:
            return
        trial_id = self.active_trial.get("trial_id", "")
        try:
            self._discard_trial_working_map(None)
            directory = trial_dir(self.project_root, self.active_trial["case_id"], trial_id)
            save_metadata(directory, {"state": "CANCELLED", "timestamp_end": datetime.now().isoformat(timespec="seconds")})
            self._finalize_trial_summary(compile_result="N/A", execution_result="", error_type=NO_ERROR_LABEL)
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo registrar la cancelacion del ensayo: {error}")
        finally:
            self._log(f"Ensayo {trial_id} cancelado: {reason}")
            self.active_trial = None
            self.manual_result_frame.grid_remove()

    def _capture_trial_parse_result(self, command_text: str, semantic_output: dict[str, Any]) -> None:
        if not self.active_trial:
            return
        try:
            transcript = str(self.voice_transcription.get("transcript", "")) if self.voice_transcription else ""
            self.active_trial["command_text"] = command_text
            self.active_trial["transcript"] = transcript
            directory = trial_dir(self.project_root, self.active_trial["case_id"], self.active_trial["trial_id"])
            write_trial_files(directory, {"command.txt": command_text, "transcript.txt": transcript})
            save_metadata(directory, {
                "command_text": command_text,
                "transcript": transcript,
                "semantic_output": semantic_output,
                "state": "RUNNING"
            })
            self._log(f"Ensayo {self.active_trial['trial_id']}: interpretacion capturada.")

            semantic_validation = semantic_output.get("semantic_validation", {}) or {}
            semantic_ok = bool(semantic_validation.get("is_valid"))
            self._update_new_trial({
                "command_text": command_text,
                "transcript": transcript or None,
                "semantic": {
                    "intent_id": semantic_output.get("intent_id"),
                    "parameters": semantic_output.get("parameters", {}),
                    "functional_requirements": semantic_output.get("functional_requirements", []),
                    "requires_clarification": bool(semantic_output.get("requires_clarification")),
                    "parser_mode_used": semantic_output.get("parser_mode_used"),
                    "semantic_validation": semantic_validation
                },
                "io": {"io_assignment_proposals": semantic_validation.get("io_assignment_proposals", [])},
                "stages": {"semantic_success": semantic_ok}
            })
            new_dir = self._new_trial_dir()
            if new_dir is not None:
                trial_model.write_text_artifact(new_dir, "command.txt", command_text)
                trial_model.write_json_artifact(new_dir, "semantic_output.json", semantic_output)
            self._set_experiment_stage("Semantica", "ok" if semantic_ok else "fail")
            self._set_experiment_stage("I/O", "ok" if semantic_ok else "skipped")
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo registrar la interpretacion del ensayo: {error}")

    def _capture_trial_parse_failure(
        self, command_text: str, semantic_output: dict[str, Any], error_code: str = "E2"
    ) -> None:
        if not self.active_trial:
            return
        trial_id = self.active_trial.get("trial_id", "")
        try:
            self._update_new_trial({"command_text": command_text, "stages": {"semantic_success": False}})
            self._set_experiment_stage("Semantica", "fail")
            self._finalize_new_trial(trial_model.FINAL_STATUS_FAIL, [f"Interpretacion no valida ({error_code})."])
            directory = trial_dir(self.project_root, self.active_trial["case_id"], trial_id)
            write_trial_files(directory, {"command.txt": command_text})
            save_metadata(directory, {
                "command_text": command_text,
                "semantic_output": semantic_output,
                "state": "ERROR",
                "timestamp_end": datetime.now().isoformat(timespec="seconds")
            })
            self._finalize_trial_summary(compile_result="N/A", execution_result="", error_type=error_code)
            self._log(f"Ensayo {trial_id} registrado con fallo de interpretacion ({error_code} - {ERROR_CODES.get(error_code, '')}).")
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo registrar el fallo de interpretacion del ensayo: {error}")
        finally:
            self.active_trial = None

    def _capture_trial_generation_result(self, combined_results: dict[str, dict[str, Any]]) -> None:
        if not self.active_trial:
            return
        try:
            target_platform = "SIEMENS_SCL_V18" if "SIEMENS_SCL_V18" in combined_results else next(iter(combined_results), None)
            result_entry = combined_results.get(target_platform, {}) if target_platform else {}
            verification = result_entry.get("verification", {})
            saved_paths = result_entry.get("saved_paths") or {}
            package_result = result_entry.get("package_result", {})

            is_valid = bool(verification.get("is_valid"))
            compile_result = "OK" if is_valid else "FAIL"
            errors = verification.get("errors", [])
            warnings = verification.get("warnings", [])

            self.active_trial.update({
                "platform": target_platform,
                "compile_result": compile_result,
                "state": "AWAITING_MANUAL_RESULT"
            })
            directory = trial_dir(self.project_root, self.active_trial["case_id"], self.active_trial["trial_id"])
            save_metadata(directory, {
                "platform": target_platform,
                "compile_result": compile_result,
                "compile_errors": errors,
                "compile_warnings": warnings,
                "package_dir": saved_paths.get("package_dir", ""),
                "project_ir_metadata": package_result.get("project_ir", {}).get("metadata", {}),
                "state": "AWAITING_MANUAL_RESULT",
                "timestamp_end": datetime.now().isoformat(timespec="seconds")
            })

            started_perf = self.active_trial.get("new_trial", {}).get("started_perf")
            generation_ms = int(round((time.perf_counter() - started_perf) * 1000)) if started_perf is not None else None
            self._update_new_trial({
                "verification": {
                    "is_valid": is_valid,
                    "errors": errors,
                    "warnings": warnings,
                    "package_dir": saved_paths.get("package_dir", "")
                },
                "stages": {"verification_success": is_valid},
                "timing": {"generation_ms": generation_ms}
            })
            self._set_experiment_stage("Generacion", "ok")
            self._set_experiment_stage("Verificacion", "ok" if is_valid else "fail")
            if is_valid:
                self._log("[EXPERIMENT] Verification passed")
            else:
                # Sin verificacion no hay compilacion ni descarga (execute_full_pipeline se detiene).
                for stage in ("Compilacion", "Descarga", "CPU Start"):
                    self._set_experiment_stage(stage, "skipped")
                self._finalize_new_trial(trial_model.FINAL_STATUS_FAIL, [str(error) for error in errors] or ["Verificacion fallida."])

            self.manual_result_var.set(PHYSICAL_RESULT_OPTIONS[0])
            self.manual_safety_var.set("No")
            self.manual_error_var.set(NO_ERROR_LABEL)
            self.manual_observations_var.set("")
            self.manual_result_frame.grid()
            self.experiment_status_var.set(
                f"Ensayo {self.active_trial['trial_id']} generado ({compile_result}). "
                "Complete el resultado abajo y presione 'Guardar resultado'."
            )
            self._log(f"Ensayo {self.active_trial['trial_id']}: generacion capturada ({compile_result}).")
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo registrar el resultado de generacion del ensayo: {error}")

    def _capture_trial_exception(self, error_text: str, stage: str) -> None:
        if not self.active_trial:
            return
        trial_id = self.active_trial.get("trial_id", "")
        try:
            self._finalize_new_trial(trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR, [f"{stage}: {error_text}"])
            directory = trial_dir(self.project_root, self.active_trial["case_id"], trial_id)
            save_metadata(directory, {
                "state": "ERROR",
                "compile_errors": [error_text],
                "timestamp_end": datetime.now().isoformat(timespec="seconds")
            })
            error_code = "E1" if stage == "parse" and self.active_trial.get("requires_voice") else "E9"
            self._finalize_trial_summary(compile_result="ERROR", execution_result="", error_type=error_code)
            self._log(f"Ensayo {trial_id} registrado con error ({stage}): {error_text}")
        except Exception as inner_error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo registrar la excepcion del ensayo: {inner_error}")
        finally:
            self.active_trial = None
            self.manual_result_frame.grid_remove()

    def save_manual_result(self) -> None:
        if not self.active_trial:
            messagebox.showwarning("Guardar resultado", "No hay un ensayo en curso.")
            return
        try:
            error_label = self.manual_error_var.get()
            error_code = NO_ERROR_LABEL if error_label == NO_ERROR_LABEL else error_label.split(" - ")[0]
            observations = {
                "physical_result": self.manual_result_var.get(),
                "safety_violation": self.manual_safety_var.get(),
                "error_type": error_code,
                "observations": self.manual_observations_var.get().strip()
            }
            directory = trial_dir(self.project_root, self.active_trial["case_id"], self.active_trial["trial_id"])
            update_observations(directory, observations)

            timestamp_end = self.active_trial.get("timestamp_end") or datetime.now().isoformat(timespec="seconds")
            total_time = self._compute_total_time(self.active_trial.get("timestamp_start"), timestamp_end)
            self.active_trial.update({"timestamp_end": timestamp_end, "total_time": total_time, "state": "COMPLETED", **observations})
            save_metadata(directory, {"state": "COMPLETED", "timestamp_end": timestamp_end, "total_time": total_time})
            self._finalize_trial_summary(
                compile_result=self.active_trial.get("compile_result", ""),
                execution_result=observations["physical_result"],
                error_type=observations["error_type"]
            )
            trial_id = self.active_trial["trial_id"]
            self._log(f"Ensayo {trial_id} completado y guardado.")
            messagebox.showinfo("Guardar resultado", f"Ensayo {trial_id} guardado correctamente.")
            self.active_trial = None
            self.manual_result_frame.grid_remove()
            self.experiment_status_var.set("Ensayo guardado. Puede iniciar uno nuevo.")
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo guardar el resultado manual del ensayo: {error}")
            messagebox.showerror("Guardar resultado", f"No se pudo guardar el resultado.\n\n{error}")

    def _refresh_experiment_history_tab(self) -> None:
        if not hasattr(self, "experiment_history_tree"):
            return
        self.experiment_history_tree.delete(*self.experiment_history_tree.get_children())
        for row in load_all_trials(self.project_root):
            self.experiment_history_tree.insert("", "end", values=(
                row.get("trial_id", ""), row.get("experiment_label", ""),
                row.get("compile_result", ""), row.get("execution_result", ""),
                row.get("total_time", ""), row.get("error_type", "")
            ))

    def _on_experiment_history_double_click(self, _event: Any = None) -> None:
        selection = self.experiment_history_tree.selection()
        if not selection:
            return
        values = self.experiment_history_tree.item(selection[0], "values")
        trial_id = values[0] if values else None
        trial = next((row for row in load_all_trials(self.project_root) if row.get("trial_id") == trial_id), None)
        if trial is None:
            return
        messagebox.showinfo(f"Ensayo {trial_id}", format_json(trial))

    def export_experiment_results(self) -> None:
        trials = load_all_trials(self.project_root)
        if not trials:
            messagebox.showwarning("Exportar resultados", "No hay ensayos registrados todavia.")
            return
        file_path = filedialog.asksaveasfilename(
            title="Exportar resultados experimentales",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("JSON", "*.json")]
        )
        if not file_path:
            return
        try:
            target = Path(file_path)
            if target.suffix.lower() == ".json":
                target.write_text(json.dumps(trials, indent=2, ensure_ascii=False), encoding="utf-8")
            else:
                with target.open("w", encoding="utf-8", newline="") as csv_file:
                    writer = csv.DictWriter(csv_file, fieldnames=MASTER_LOG_FIELDS)
                    writer.writeheader()
                    for row in trials:
                        writer.writerow({field: row.get(field, "") for field in MASTER_LOG_FIELDS})
            self._log(f"Resultados experimentales exportados a {target}.")
            messagebox.showinfo("Exportar resultados", f"Exportado correctamente a:\n{target}")
        except OSError as error:
            self._log(f"No se pudo exportar resultados experimentales: {error}")
            messagebox.showerror("Exportar resultados", f"No se pudo exportar.\n\n{error}")

    def _run_pipeline_precheck(self, command_text: str) -> tuple[bool, str]:
        """Verificaciones rapidas y sin efectos secundarios antes de correr el pipeline completo."""
        if not command_text:
            return False, "Escriba o dicte un comando antes de ejecutar."

        if self.active_profile_id is not None and get_profile(self.project_root, self.active_profile_id) is None:
            return False, f"El perfil activo '{self.active_profile_id}' ya no existe. Seleccione otro mapa o caso."

        tia_config = load_tia_config(self.project_root)
        if not str(tia_config.get("project_path", "")).strip():
            return False, "No hay un proyecto TIA configurado. Use 'Configurar TIA V18'."

        build_openness_bridge(self.project_root)
        diagnostic = diagnose_tia_openness(self.project_root)
        if not diagnostic.get("is_ready"):
            details = "\n".join(diagnostic.get("warnings", [])) or "Revise la configuracion de TIA Openness."
            return False, "TIA Portal Openness no esta disponible.\n\n" + details

        return True, ""

    def execute_full_pipeline(self) -> bool:
        """
        Orquesta el pipeline completo reutilizando los metodos existentes, sin duplicar
        su logica: pre-check -> process_command() -> generate_package() -> validate_latest_package_in_tia().
        Usado tanto por 'EJECUTAR COMANDO' (Modo Normal) como por 'EJECUTAR ENSAYO' (Modo
        Experimentacion, donde self.active_trial ya fue armado por start_trial()).
        """
        if self._tia_worker_active:
            messagebox.showwarning("Ejecutar comando", "Ya existe una operacion TIA en curso.")
            return False
        if self._voice_worker_active:
            messagebox.showwarning("Ejecutar comando", "Espere a que termine la transcripcion de voz.")
            return False

        # Deshabilitar el boton durante TODO el pipeline, no solo la fase TIA (que ya se
        # autogestiona en validate_latest_package_in_tia()/_poll_tia_worker) - cierra la ventana
        # en la que un doble clic durante process_command()/generate_package() (fases sincronas,
        # potencialmente de varios segundos por llamadas LLM reales) podria reencolar el mismo
        # comando antes de que _tia_worker_active exista siquiera. Solo lo reactivamos aqui si la
        # operacion TIA nunca llego a arrancar - si arranco, _poll_tia_worker es quien la libera.
        self.execute_command_button.configure(state="disabled")
        self.start_trial_button.configure(state="disabled")
        tia_started = False
        try:
            command_text = self.command_textbox.get("1.0", "end").strip()
            precheck_ok, precheck_message = self._run_pipeline_precheck(command_text)
            if not precheck_ok:
                self._set_status("Error")
                self._log(f"Ejecucion detenida en verificacion previa: {precheck_message}")
                if self.active_trial:
                    self._cancel_active_trial(f"Verificacion previa fallida: {precheck_message}")
                messagebox.showwarning("Ejecutar comando", precheck_message)
                return False

            if not self.process_command():
                return False
            if not self.generate_package():
                return False
            self.validate_latest_package_in_tia()
            tia_started = self._tia_worker_active
            return True
        finally:
            if not tia_started:
                self.execute_command_button.configure(state="normal")
                self.start_trial_button.configure(state="normal")

    def _show_experimental_incompatibility(self, profile: dict[str, Any] | None, unauthorized_tags: list[str]) -> None:
        """
        El comando pidio recursos fisicos (I_/Q_) que el perfil del caso experimental activo
        no autoriza. Esto NUNCA debe ofrecer ampliar el mapa o el perfil automaticamente -
        es una senal de que el comando no corresponde al caso, no un problema de configuracion.
        """
        profile = profile or {}
        allowed_external = profile.get("allowed_variables", [])
        messagebox.showwarning(
            "Incompatibilidad experimental",
            "El comando no corresponde completamente al caso experimental seleccionado.\n\n"
            f"Caso activo: {profile.get('name', self.experiment_case_var.get())}\n\n"
            "Recursos fisicos autorizados:\n" + (", ".join(allowed_external) or "(ninguno)") + "\n\n"
            "Recursos fisicos solicitados por el comando:\n" + ", ".join(unauthorized_tags) + "\n\n"
            "Opciones:\n"
            "- Reformule el comando para que corresponda a este caso.\n"
            "- Seleccione otro caso experimental.\n"
            "- Utilice Modo Normal si necesita programacion libre."
        )

    def _show_normal_missing_variable(self, unauthorized_tags: list[str]) -> None:
        """En Modo Normal no hay protocolo Dxx: si falta la variable, sí puede ofrecerse editar el mapa."""
        messagebox.showwarning(
            "Recurso fisico no encontrado",
            "El comando solicita un recurso fisico que no existe en el mapa PLC activo.\n\n"
            "Variable(s) solicitada(s):\n" + ", ".join(unauthorized_tags) + "\n\n"
            f"No existe en: {self.active_map_var.get()}\n\n"
            "Opciones:\n"
            "- Agregue la variable en el panel izquierdo ('Agregar variable').\n"
            "- Seleccione otro mapa PLC.\n"
            "- Cancele y reformule el comando."
        )

    def _show_validation_errors(self, semantic_output: dict[str, Any]) -> None:
        """
        `is_valid=False` sin una ambiguedad real que preguntar (ver process_command, seccion "unica
        fuente de verdad"): tipicamente el intent elegido quedo con parametros faltantes o
        estructuralmente incompatibles con su plantilla (p. ej. un comando de N actores que el LLM
        interpreto con una forma de parametros que INT_MOTOR_START_STOP/INT_MUTUAL_INTERLOCK no
        pueden consumir). Esto es un ERROR, no una pregunta - se muestran los errores reales de
        semantic_validation en vez de abrir ClarificationDialog con una pregunta vacia/generica.
        """
        errors = list(semantic_output.get("semantic_validation", {}).get("errors", []))
        detail = "\n".join(f"- {error}" for error in errors) if errors else (
            "No se especifico un motivo de validacion (revise Parametros/Verificacion en el panel derecho)."
        )
        messagebox.showerror(
            "Interpretacion no valida",
            "La interpretacion no se puede generar tal como quedo estructurada "
            f"(intent: {semantic_output.get('intent_id', 'INT_UNKNOWN')}).\n\n"
            f"{detail}\n\n"
            "Reformule el comando o simplifiquelo (por ejemplo, describiendo los actores de uno en "
            "uno) e intente de nuevo."
        )

    def _invalidate_download_readiness(self) -> None:
        """
        'CARGAR PROGRAMA AL PLC' solo puede estar habilitado mientras represente la ULTIMA
        compilacion Siemens aprobada. Cualquier comando nuevo procesado, o una compilacion que
        falla, invalida ese estado para no arriesgar descargar un programa anterior.
        """
        if self._last_compiled_package_dir is not None or self.download_plc_button.cget("state") != "disabled":
            self._log("'CARGAR PROGRAMA AL PLC' deshabilitado: no hay una compilacion vigente.")
        self._last_compiled_package_dir = None
        self.download_plc_button.configure(state="disabled")

    def _resolve_semantic_ambiguity(self, command_text: str, semantic_output: dict[str, Any]) -> bool:
        """
        Handles a genuine SEMANTIC_AMBIGUITY (requires_clarification=True / INT_UNKNOWN with no
        unauthorized_tags - internal resources never reach here, see the classification in
        process_command's failure branch). "Aceptar" must be a REAL answer, not a dismissed
        MessageBox: opens ClarificationDialog, and only if the user actually answers does it
        append the Q&A to the command and reprocess (recursively re-enters process_command, so
        EJECUTAR COMANDO/EJECUTAR ENSAYO continue automatically once the ambiguity resolves).
        Cancelling is the real "give up" path and closes any active trial with the evidence.
        """
        # Guardia defensiva secundaria (seccion 7 del pedido): si algun otro llamador futuro
        # invoca esto sin una pregunta real, no se abre un dialogo con texto de relleno generico -
        # eso es exactamente lo que producia la "caja vacia" reportada. La correccion real vive en
        # process_command (unica fuente de verdad: requires_clarification + pregunta no vacia antes
        # de siquiera llegar aqui); esto es solo un ultimo resguardo, no el arreglo principal.
        clarification_question = semantic_output.get("clarification_question")
        if not clarification_question or not str(clarification_question).strip():
            self._log(
                "_resolve_semantic_ambiguity invocado sin clarification_question real - no se abre "
                "un dialogo vacio; tratando como error de validacion."
            )
            self._show_validation_errors(semantic_output)
            return False

        question = str(clarification_question)
        dialog = ClarificationDialog(self, question)
        self.wait_window(dialog)
        answer = dialog.result

        if not answer:
            self._log("Aclaracion cancelada por el usuario; el comando no se reprocesa.")
            if self.active_trial:
                self._capture_trial_parse_failure(command_text, semantic_output)
            return False

        self._log(f"Aclaracion registrada por el usuario: {answer!r}. Reprocesando el comando.")
        augmented_command = (
            f"{command_text}\n\n"
            f"Aclaracion solicitada: {question}\n"
            f"Respuesta del usuario: {answer}"
        )
        self.command_textbox.delete("1.0", "end")
        self.command_textbox.insert("1.0", augmented_command)
        return self.process_command()

    def _handle_map_config_command(
        self,
        semantic_output: dict[str, Any],
        io_map: dict[str, Any],
        intents_catalog: dict[str, Any],
        safety_rules: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        MAP_CONFIG branch (sections 6-9, 14-16, 23): a command that mentions "Usa Q8.1 para el
        motor 2" style address+role assignments. Every proposal here already came from
        io_allocator.propose_assignment (via semantic_validator) against the REAL active map -
        this method only shows it to the user and applies it on confirmation; it never computes
        or guesses an address itself. Returns None to stop process_command right here (blocked,
        rejected, or a pure-configuration command with no logic to generate), or the
        semantic_output (re-validated against the now-updated map) to let process_command
        continue into its normal intent/logic flow for a combined command (section 14).
        """
        trial_info = self._trial_io()
        if trial_info is None:
            # Sin working map de ensayo: politica legacy (Modo Normal con un perfil Dxx/Pxx
            # seleccionado = "mapa congelado"). Durante un ensayo con working map, la asignacion
            # AUTOMATICA del pipeline nunca pasa por aqui: se rige por la fase del ensayo.
            block_message = block_map_config_message(self.active_trial, self.active_profile_id)
            if block_message:
                self._log("MAP_CONFIG rechazado: ensayo/perfil experimental activo.")
                messagebox.showwarning("Configuracion de mapa", block_message)
                return None
        else:
            try:
                trial_io_map.assert_mutation_allowed(trial_info.get("lifecycle_state"))
            except trial_io_map.ExperimentIOError as error:
                self._fail_trial_io(error.code, error.detail)
                messagebox.showerror("Configuracion de mapa", error.detail)
                return None

        proposals = semantic_output.get("semantic_validation", {}).get("io_assignment_proposals", [])
        if not proposals:
            self._log("MAP_CONFIG detectado pero sin propuestas validas (revise el mapa activo).")
            if trial_info is not None:
                self._fail_trial_io(trial_io_map.ERROR_ALLOCATION_FAILED, "Sin propuestas de asignacion validas.")
            messagebox.showwarning(
                "Configuracion de mapa",
                "No se pudo generar una propuesta de asignacion valida para este comando."
            )
            return None

        # Politica de cero confirmaciones en Modo Normal (seccion 22): MAP_CONFIG ya esta
        # restringido a Modo Normal (Experimentacion se bloquea arriba), asi que TODO lo que no
        # este bloqueado se aplica directo - FREE, "ya es ese nombre", y tambien reasignar un
        # ASSIGNED con un rol distinto. Nunca se pregunta; se informa despues (seccion 23).
        blocked = [proposal for proposal in proposals if proposal.get("blocked")]
        to_apply = [proposal for proposal in proposals if not proposal.get("blocked")]

        if not to_apply:
            reasons = "\n".join(f"- {proposal.get('reason')}" for proposal in blocked)
            if trial_info is not None:
                self._fail_trial_io(trial_io_map.ERROR_ALLOCATION_FAILED, reasons or "Ninguna asignacion aplicable.")
            if blocked:
                messagebox.showerror("Configuracion de mapa", f"No se aplico ninguna asignacion:\n\n{reasons}")
            self._log("MAP_CONFIG: no se aplico ninguna asignacion.")
            return None

        if trial_info is not None:
            # Ensayo: MISMO apply_assignments que Modo Normal, sobre el working map del ensayo,
            # de forma transaccional (trial_io_map). El mapa base no se toca.
            try:
                trial_io_map.apply_proposals_to_working_map(
                    Path(trial_info["io_map"]["working_map_path"]),
                    to_apply,
                    "TEXT_EXPLICIT",
                    trial_info.get("lifecycle_state")
                )
            except trial_io_map.ExperimentIOError as error:
                self._log(f"[EXPERIMENT IO] {error}")
                self._fail_trial_io(error.code, error.detail)
                messagebox.showerror("Configuracion de mapa", f"No se pudo aplicar la asignacion.\n\n{error.detail}")
                return None
            self._set_experiment_io("Resueltas")
        try:
            # CRITICO: el parche SIEMPRE se aplica sobre el inventario fisico COMPLETO, leido de
            # nuevo directamente del archivo - nunca sobre `io_map` (el parametro recibido), que
            # puede venir filtrado por perfil (apply_profile_filter, en _load_runtime_configuration)
            # si hay un active_profile_id activo. Guardar ese `io_map` filtrado de vuelta al disco
            # borraria permanentemente todo canal fisico fuera de allowed_variables del perfil - el
            # bug reportado (el "Mapa I/O completo" mostraba solo los canales usados). El filtro de
            # perfil es correcto para INTERPRETAR/VALIDAR que puede referenciar un comando; nunca
            # debe ser la base de una escritura al mapa real.
            if trial_info is None:
                full_io_map = load_json_file(self.io_map_path)
                updated_map, history_entries = apply_assignments(full_io_map, to_apply, source="TEXT_EXPLICIT")
                save_plc_map(self.io_map_path, updated_map["variables"], history_entries=history_entries)
        except ValueError as error:
            messagebox.showerror("Configuracion de mapa", f"No se pudo aplicar la asignacion.\n\n{error}")
            self._log(f"MAP_CONFIG fallo al aplicar: {error}")
            return None

        if trial_info is None:
            self.io_variables = load_io_map_variables(self.io_map_path)
            self._load_active_map_metadata_shadow()
            self._load_io_map_table()

        # Resumen compacto seccion 23: separa lo que ya era exactamente ese nombre (conservado,
        # sin cambio real) de lo que efectivamente cambio de nombre (reasignado).
        kept = [p for p in to_apply if p.get("current_name") == p.get("proposed_name")]
        reassigned = [p for p in to_apply if p.get("current_name") != p.get("proposed_name")]
        summary_parts = ["CONFIGURACION AUTOMATICA"]
        if kept:
            summary_parts.append("\nConservados:\n" + "\n".join(f"{p['address']} -> {p['proposed_name']}" for p in kept))
        if reassigned:
            summary_parts.append(
                "\nReasignados:\n" + "\n".join(
                    f"{p['address']}: {p.get('current_name') or '—'} -> {p['proposed_name']}" for p in reassigned
                )
            )
        summary_text = "\n".join(summary_parts)
        summary_lines = [f"{proposal.get('address')} -> {proposal.get('proposed_name')}" for proposal in to_apply]
        if blocked:
            summary_text += "\n\nRechazadas (protegidas):\n" + "\n".join(
                f"- {proposal.get('reason')}" for proposal in blocked
            )
        self._log("MAP_CONFIG aplicado. " + "; ".join(summary_lines))

        io_map, intents_catalog, safety_rules = self._load_runtime_configuration()
        self.pending_runtime_config = (io_map, intents_catalog, safety_rules)
        semantic_output = dict(semantic_output)
        semantic_output["semantic_validation"] = validate_semantic_output(
            semantic_output, io_map, intents_catalog, safety_rules
        )

        # Seccion 11: "no hay mas logica que generar" NO es lo mismo que "intent_id quedo
        # INT_UNKNOWN". Un comando compuesto real (p.ej. un enclavamiento de N motores que no
        # coincide con ningun intent_id fijo del catalogo) puede legitimamente resolver a
        # INT_UNKNOWN y aun asi traer functional_requirements con contenido logico real - en ese
        # caso el pipeline debe continuar (seccion 6 de una tarea anterior: reusar
        # functional_requirements en vez de forzar un intent_id especifico). Solo se trata como
        # "puramente configuracion, sin logica" cuando AMBOS son verdad: intent_id sigue
        # INT_UNKNOWN y no hay ningun functional_requirement adjunto.
        has_logic_content = bool(semantic_output.get("functional_requirements")) or semantic_output.get(
            "intent_id"
        ) not in (None, "INT_UNKNOWN")

        if not has_logic_content:
            # Comando exclusivamente de configuracion (seccion 11, ejemplo "Usa Q8.1 como salida
            # del motor 2."): este SI es el resultado final visible para el usuario, se muestra
            # ahora.
            summary_text += "\n\n(El comando no incluia logica PLC adicional; no se genero ningun programa.)"
            self._last_map_config_summary = None
            if trial_info is not None:
                self._fail_trial_io(None, "El comando solo configura I/O; no hay logica PLC que ensayar.")
            messagebox.showinfo("Configuracion de mapa", summary_text)
            return None

        # Comando MIXTO (mapa + logica, seccion 11/13/14): la configuracion automatica es UNA
        # ETAPA del pipeline, no su fin - no se detiene el flujo con un messagebox aqui. Se
        # registra en consola/historial y se reserva el resumen para el dialogo de confirmacion de
        # generate_package(), que sigue siendo el unico punto de confirmacion humana antes de
        # generar codigo (esa confirmacion no se elimina ni se salta).
        self._log("MAP_CONFIG aplicado automaticamente (comando mixto, continua con la logica): " + summary_text.replace("\n", " | "))
        self._last_map_config_summary = summary_text
        return semantic_output

    def process_command(self) -> bool:
        command_text = self.command_textbox.get("1.0", "end").strip()
        if not command_text:
            self._set_status("Error")
            self._log("No se proceso el comando porque el cuadro de texto esta vacio.")
            messagebox.showwarning("Comando", "Escriba un comando industrial antes de procesar.")
            return False

        self._invalidate_download_readiness()
        # Un resumen de MAP_CONFIG solo es valido para el comando que lo genero - nunca debe
        # sobrevivir y aparecer en el dialogo de confirmacion de un comando siguiente que no toco
        # el mapa.
        self._last_map_config_summary = None

        # Durante un ensayo el pipeline trabaja sobre el working map del ensayo: guardar la tabla
        # de la GUI aqui reescribiria el mapa base (updated_at incluido) por efecto del ensayo.
        if self._trial_io() is None and not self.save_io_map(show_success=False):
            self._set_status("Error")
            return False
        if self._trial_io() is not None:
            self._set_experiment_io("Asignando...")

        self._set_status("Procesando")
        self._log("Comando recibido.")

        try:
            requested_mode = normalize_parser_mode_selection(self.parser_mode_var.get())
            health = self._refresh_llm_client_status(announce=False)
            if requested_mode == "llm" and not health.get("llm_configured"):
                self._log("Modo LLM solicitado sin credenciales completas. Se aplicara fallback local seguro.")
            elif requested_mode == "hybrid" and not health.get("llm_configured"):
                self._log("Modo hibrido activo sin API lista. El flujo usara reglas hasta que configure OpenAI.")

            io_map, intents_catalog, safety_rules = self._load_runtime_configuration()
            self.pending_runtime_config = (io_map, intents_catalog, safety_rules)
            semantic_output = parse_command(
                command_text,
                io_map=io_map,
                intents_catalog=intents_catalog,
                safety_rules=safety_rules,
                mode=requested_mode,
                llm_client=self.llm_client
            )
            self._log("Intencion detectada.")
            self._log("Parametros extraidos.")

            self._set_textbox_content(self.intent_textbox, self._format_intention_text(semantic_output))
            self._set_textbox_content(self.voice_textbox, self._build_voice_text())
            self._set_textbox_content(self.comparison_textbox, self._build_comparison_text(semantic_output))
            self._set_textbox_content(self.parameters_textbox, format_json(semantic_output.get("parameters", {})))
            self._set_textbox_content(self.verification_textbox, format_json(semantic_output.get("semantic_validation", {})))
            self.pending_semantic_output = semantic_output

            if self.work_mode_var.get() == "Experimentacion":
                self._refresh_experiment_status()

            has_map_proposals = bool(semantic_output.get("semantic_validation", {}).get("io_assignment_proposals"))
            map_config_continued = False
            if semantic_output.get("operation_type") == "MAP_CONFIG" or has_map_proposals:
                # has_map_proposals cubre el caso implicito (seccion 11/12): un tag no autorizado
                # pero bien formado que el IOAllocator ya resolvio dentro de validate_semantic_output
                # (nunca paso por extract_io_assignment_requests, asi que operation_type solo no
                # alcanza para detectarlo).
                proceed_with_logic = self._handle_map_config_command(semantic_output, io_map, intents_catalog, safety_rules)
                if proceed_with_logic is None:
                    self._set_status("Listo")
                    return False
                semantic_output = proceed_with_logic
                self.pending_semantic_output = semantic_output
                map_config_continued = True

            # Seccion 11: un comando compuesto real puede no coincidir con ningun intent_id fijo
            # del catalogo y por eso resolver a INT_UNKNOWN, aun trayendo functional_requirements
            # con contenido logico real que _handle_map_config_command ya considero suficiente
            # para continuar (has_logic_content). Bloquear aqui SOLO por "intent_id volvio
            # INT_UNKNOWN" deshacia esa decision y detenia el pipeline otra vez. Fuera del flujo
            # MAP_CONFIG, intent_id == INT_UNKNOWN sigue significando exactamente lo mismo que
            # siempre (no se entendio el comando, se pide aclaracion) - sin cambios ahi.
            intent_missing = semantic_output.get("intent_id") == "INT_UNKNOWN" and not map_config_continued
            is_valid_now = semantic_output.get("semantic_validation", {}).get("is_valid", False)
            if intent_missing or not is_valid_now:
                unknown_payload = {
                    "is_valid": False,
                    "errors": list(semantic_output.get("semantic_validation", {}).get("errors", [])),
                    "warnings": list(semantic_output.get("semantic_validation", {}).get("warnings", []))
                    + ["Se requiere aclaracion del comando antes de generar codigo."]
                }
                snapshot = self._build_unknown_snapshot(command_text, semantic_output, unknown_payload)
                self._restore_snapshot(snapshot)
                self._record_history(snapshot, platform="Sin plataforma", is_valid=False)

                unauthorized_tags = list(semantic_output.get("semantic_validation", {}).get("unauthorized_tags", []))
                # Unica fuente de verdad para abrir el dialogo de aclaracion (seccion 5 del pedido):
                # requires_clarification debe ser True Y traer una pregunta real y no vacia. Un
                # semantic_output final con requires_clarification=False (el caso reportado:
                # is_valid=False solo porque el intent elegido - p.ej. INT_MOTOR_START_STOP - quedo
                # con parametros faltantes/estructuralmente incompatibles, no porque el comando sea
                # ambiguo) NUNCA debe llegar a ClarificationDialog - eso es un ERROR DE VALIDACION,
                # no una pregunta que el usuario pueda responder, y por eso la caja aparecia vacia
                # (clarification_question siempre fue None; el dialogo solo rellenaba un texto
                # generico de relleno). Se muestran los errores reales en su lugar.
                clarification_question = semantic_output.get("clarification_question")
                has_real_question = bool(
                    semantic_output.get("requires_clarification")
                    and clarification_question
                    and str(clarification_question).strip()
                )
                if unauthorized_tags and self.work_mode_var.get() == "Experimentacion":
                    profile = self._experiment_profiles_by_case.get(self.experiment_case_var.get())
                    self._log("El comando solicita recursos fisicos no autorizados por el caso experimental.")
                    if self.active_trial:
                        self._capture_trial_parse_failure(command_text, semantic_output, error_code="E3")
                    self._show_experimental_incompatibility(profile, unauthorized_tags)
                elif unauthorized_tags and self.work_mode_var.get() == "Normal":
                    self._log("El comando solicita un recurso fisico inexistente en el mapa activo.")
                    if self.active_trial:
                        self._capture_trial_parse_failure(command_text, semantic_output, error_code="E3")
                    self._show_normal_missing_variable(unauthorized_tags)
                elif has_real_question:
                    self._log("La interpretacion requiere aclaracion antes de generar (SEMANTIC_AMBIGUITY).")
                    self._set_status("Listo")
                    return self._resolve_semantic_ambiguity(command_text, semantic_output)
                else:
                    self._log("La interpretacion no es valida para generar codigo (error de validacion, no una ambiguedad).")
                    if self.active_trial:
                        self._capture_trial_parse_failure(command_text, semantic_output, error_code="E3")
                    self._show_validation_errors(semantic_output)
                self._set_status("Listo")
                return False

            self._set_validation_banner("Interpretacion lista.", None)
            interpretation_snapshot = self._build_interpretation_snapshot(command_text, semantic_output)
            self._record_history(
                interpretation_snapshot,
                platform="Interpretacion",
                is_valid=semantic_output.get("semantic_validation", {}).get("is_valid", False)
            )
            self._log("Interpretacion completada.")
            self._log("[PIPELINE] Semantic OK")
            self._log("[PIPELINE] IO allocation OK")
            if self.active_trial:
                self._capture_trial_parse_result(command_text, semantic_output)
            if not self._freeze_trial_io(semantic_output):
                self._set_status("Error")
                return False
            self._set_status("Listo")
            return True
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._set_status("Error")
            self._set_validation_banner("Error durante el procesamiento.", False)
            self._log(f"Error durante el procesamiento: {error}")
            if self.active_trial:
                self._capture_trial_exception(str(error), stage="parse")
            messagebox.showerror("Procesamiento", f"No se pudo procesar el comando.\n\n{error}")
            return False

    def generate_package(self) -> bool:
        if self.pending_semantic_output is None or self.pending_runtime_config is None:
            messagebox.showwarning("Generacion", "Primero procese un comando valido.")
            return False

        target_platforms = normalize_platform_targets(self.platform_var.get())
        # EJECUTAR COMANDO debe continuar automaticamente hasta TIA/compilacion sin ningun dialogo
        # de confirmacion intermedio (decision explicita del usuario - reemplaza la politica previa
        # de "confirmar antes de generar"). El resumen de interpretacion (y el de MAP_CONFIG si
        # aplico, seccion 14) se registra en consola en vez de bloquear con un messagebox.
        map_config_prefix = ""
        if self._last_map_config_summary:
            map_config_prefix = self._last_map_config_summary + "\n\n"
        self._log(
            "Generando sin confirmacion interactiva (Modo Normal, pipeline automatico):\n"
            + map_config_prefix
            + self._build_confirmation_summary(self.pending_semantic_output, target_platforms)
        )

        io_map, intents_catalog, safety_rules = self.pending_runtime_config
        command_text = self.pending_semantic_output.get("command_text", self.command_textbox.get("1.0", "end").strip())
        combined_verification: dict[str, Any] = {}
        combined_files: dict[str, Any] = {}
        combined_results: dict[str, dict[str, Any]] = {}

        self._set_status("Procesando")
        try:
            for target_platform in target_platforms:
                package_result = generate_project_package(
                    semantic_output={**self.pending_semantic_output, "command_text": command_text},
                    target_platform=target_platform,
                    io_map=io_map,
                    intents_catalog=intents_catalog,
                    safety_rules=safety_rules,
                    transcription_payload=self.voice_transcription
                )
                verification = package_result["verification"]
                saved_paths = package_result.get("artifacts") or None
                self._log("[PIPELINE] IR built")
                if target_platform == "SIEMENS_SCL_V18":
                    self._log("[PIPELINE] Siemens SCL generated")
                self._log(
                    "[PIPELINE] Verification passed" if verification.get("is_valid")
                    else "[PIPELINE] Verification FAILED: " + "; ".join(verification.get("errors", []))
                )
                append_test_record_to_docs(
                    docs_dir=self.docs_dir,
                    command_text=command_text,
                    semantic_output={**self.pending_semantic_output, "command_text": command_text},
                    verification_result=verification,
                    saved_paths=saved_paths,
                    target_platform=target_platform
                )

                combined_results[target_platform] = {
                    "package_result": package_result,
                    "verification": verification,
                    "saved_paths": saved_paths
                }
                combined_verification[target_platform] = verification
                combined_files[target_platform] = saved_paths or {}
                self._log(f"Paquete {platform_label(target_platform)} generado.")
                generated_functional = package_result.get("project_ir", {}).get("metadata", {}).get(
                    "generated_functional_variables", []
                )
                self._persist_generated_functional_variables(generated_functional)
                if target_platform == "OPENPLC_ST":
                    self._log(
                        "Compilacion OpenPLC: "
                        + verification.get("compilation_status", "COMPILATION_NOT_EXECUTED")
                    )
                    self._log(
                        "Simulacion funcional OpenPLC: "
                        + verification.get("simulation_status", "SIMULATION_NOT_EXECUTED")
                    )
                if saved_paths:
                    package_dir = saved_paths.get("package_dir")
                    implementation_path = saved_paths.get("pou_path") or saved_paths.get("implementation_path")
                    full_program_path = saved_paths.get("full_program_path") or saved_paths.get("st_path")
                    if package_dir:
                        self._log(f"Directorio {platform_label(target_platform)}: {package_dir}")
                    if implementation_path:
                        self._log(f"POU principal {platform_label(target_platform)}: {implementation_path}")
                    if full_program_path and full_program_path != implementation_path:
                        self._log(f"Programa ST completo {platform_label(target_platform)}: {full_program_path}")

            for target_platform, platform_result in combined_results.items():
                snapshot = self._build_result_snapshot(
                    command_text=command_text,
                    semantic_output=self.pending_semantic_output,
                    combined_results=combined_results,
                    combined_verification=combined_verification,
                    combined_files=combined_files,
                    preferred_platform=target_platform
                )
                self._record_history(
                    snapshot,
                    platform=target_platform,
                    is_valid=platform_result["verification"]["is_valid"]
                )

            self._render_generation_results(
                command_text,
                self.pending_semantic_output,
                combined_results,
                combined_verification,
                combined_files
            )
            all_valid = all(result["verification"]["is_valid"] for result in combined_results.values())
            # Seccion 12: un mensaje generico ("Verificacion completada.") suena a exito incluso
            # cuando fallo - ya se emitio "[PIPELINE] Verification passed/FAILED" por plataforma
            # mas arriba; este es el resumen final, inequivoco, de TODAS las plataformas juntas.
            if all_valid:
                self._log("Verificacion completada correctamente.")
            else:
                self._log("Verificacion fallida.")
            if self.active_trial:
                self._capture_trial_generation_result(combined_results)
            self._set_status("Listo")
            return all_valid
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._set_status("Error")
            self._set_validation_banner("Error durante la generacion.", False)
            self._log(f"Error durante la generacion: {error}")
            if self.active_trial:
                self._capture_trial_exception(str(error), stage="generate")
            messagebox.showerror("Generacion", f"No se pudo generar el paquete PLC.\n\n{error}")
            return False

    def _format_intention_text(self, semantic_output: dict[str, Any]) -> str:
        return (
            f"intent_id: {semantic_output.get('intent_id', 'INT_UNKNOWN')}\n"
            f"confidence: {semantic_output.get('confidence', 0.0)}\n"
            f"case_id: {semantic_output.get('case_id')}\n"
            f"command_text: {semantic_output.get('command_text', self.command_textbox.get('1.0', 'end').strip())}\n"
            f"parser_mode_requested: {semantic_output.get('parser_mode_requested')}\n"
            f"parser_mode_used: {semantic_output.get('parser_mode_used', semantic_output.get('parser_mode'))}\n"
            f"requires_clarification: {semantic_output.get('requires_clarification', False)}\n"
            f"clarification_question: {semantic_output.get('clarification_question')}\n"
        )

    def _render_generation_results(
        self,
        command_text: str,
        semantic_output: dict[str, Any],
        combined_results: dict[str, dict[str, Any]],
        combined_verification: dict[str, Any],
        combined_files: dict[str, Any]
    ) -> None:
        snapshot = self._build_result_snapshot(
            command_text=command_text,
            semantic_output=semantic_output,
            combined_results=combined_results,
            combined_verification=combined_verification,
            combined_files=combined_files
        )
        self._restore_snapshot(snapshot)

    def _record_history(self, snapshot: dict[str, Any], platform: str, is_valid: bool) -> None:
        combined_files = snapshot.get("combined_files", {}) if isinstance(snapshot, dict) else {}
        saved_paths = combined_files.get(platform, {}) if isinstance(combined_files, dict) else {}
        metadata_path = saved_paths.get("metadata_path") if isinstance(saved_paths, dict) else None
        history_record = {
            "history_id": (f"log::{metadata_path}" if metadata_path else (
                f"ui::{datetime.now().isoformat(timespec='microseconds')}::"
                f"{platform}::{snapshot.get('semantic_output', {}).get('intent_id', 'INT_UNKNOWN')}"
            )),
            "timestamp": snapshot.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "command_text": snapshot.get("command_text", ""),
            "intent_id": snapshot.get("semantic_output", {}).get("intent_id", "INT_UNKNOWN"),
            "platform": platform,
            "is_valid": is_valid,
            "snapshot": snapshot
        }
        self._store_history_record(history_record)

    def archive_codes(self) -> None:
        target_platform = self._current_platform_argument()
        try:
            result = archive_generated_files(target_platform=target_platform, output_dir=self.generated_dir)
            summary = format_json(result)
            self._set_textbox_content(self.files_textbox, summary)
            self._log("Archivos archivados.")
            messagebox.showinfo("Archivado", summary)
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"Error al archivar archivos: {error}")
            messagebox.showerror("Archivado", f"No se pudo archivar.\n\n{error}")

    def clear_codes(self) -> None:
        if not messagebox.askyesno(
            "Limpiar codigos",
            "Se eliminaran los archivos activos y logs de la plataforma seleccionada.\n\nDesea continuar?"
        ):
            self._log("Limpieza cancelada por el usuario.")
            return

        target_platform = self._current_platform_argument()
        try:
            result = clear_generated_files(confirm=True, target_platform=target_platform, output_dir=self.generated_dir)
            summary = format_json(result)
            self._set_textbox_content(self.files_textbox, summary)
            self._log("Limpieza completada.")
            messagebox.showinfo("Limpieza", summary)
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"Error al limpiar archivos: {error}")
            messagebox.showerror("Limpieza", f"No se pudo limpiar.\n\n{error}")


def main() -> None:
    global _GUI_INSTANCE_SOCKET

    instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        try:
            instance_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        except OSError:
            pass

    try:
        instance_socket.bind(("127.0.0.1", GUI_INSTANCE_PORT))
        instance_socket.listen(1)
    except OSError:
        instance_socket.close()
        duplicate_root = tk.Tk()
        duplicate_root.withdraw()
        duplicate_root.after(
            50,
            lambda: messagebox.showinfo(
                "Voz-LLM-PLC Agent",
                "La interfaz ya se encuentra abierta.\n\nUse la ventana existente para continuar."
            )
        )
        duplicate_root.after(250, duplicate_root.destroy)
        duplicate_root.mainloop()
        return

    _GUI_INSTANCE_SOCKET = instance_socket

    try:
        app = VozLLMPLCGUI()
        app.mainloop()
    finally:
        if _GUI_INSTANCE_SOCKET is not None:
            _GUI_INSTANCE_SOCKET.close()
            _GUI_INSTANCE_SOCKET = None


if __name__ == "__main__":
    main()
