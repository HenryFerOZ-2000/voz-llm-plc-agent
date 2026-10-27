from __future__ import annotations

import contextlib
import csv
import copy
import hashlib
import json
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable
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
from io_variable_editor import VariableEditorDialog
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
from llm_parser import resolve_parser_mode
from product_engine import interpret_product_command as parse_command
import product_engine
from plc_maps import (
    GENERAL_PROFILE_LABEL,
    apply_profile_filter,
    check_case_compatibility,
    create_plc_map,
    delete_plc_map,
    ensure_plc_maps_library,
    experiment_reference_map_path,
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
from plc_maps.store import is_working_map_path
from plc_maps.tia_sync import import_tags_from_tia, sync_map_with_tia
from product_engine import generate_product_package as generate_project_package
from semantic_validator import validate_semantic_output
from speech_recognizer import SpeechRecognizer
from tia_openness import (
    tia_compile_summary,
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
import normal_interaction
import normal_program_bindings as program_bindings
from functional_requirements import has_composable_program
import normal_voice
import plcsim_runtime
import plc_targets
from plc_target_dialog import PlcTargetDialog
import plcsim_runtime_io
import tia_projects
from plcsim_runtime import get_plcsim_runtime_status
from trial_experiments import benchmark_catalog, oracle_review, oracle_runner, oracle_schema, trial_io_map, trial_model
from trial_experiments import deferred_evaluator, experimental_design, resource_policy, tia_classification
from trial_experiments import experiment_maps, formal_audio, text_batch, voice_protocol
from host_local import load_host_id
from trial_experiments.oracle_runner import run_oracle
from trial_experiments.oracle_schema import find_case_oracle
from trial_experiments import (
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

# Diseno experimental v2 (data/experimental_design.json): la modalidad de entrada es el factor;
# Rules/LLM/Hybrid y las condiciones C1-C4 quedan fuera del flujo formal (legacy DEPRECATED).
INPUT_MODE_LABELS = {
    trial_model.INPUT_MODE_TEXT: "TEXT - Texto",
    trial_model.INPUT_MODE_VOICE_CLEAN: "VOICE_CLEAN - Voz limpia",
    trial_model.INPUT_MODE_VOICE_NOISE: "VOICE_NOISE - Voz con ruido",
}
NORMAL_VOICE_BUTTON_TEXT = "🎙 CAPTURAR Y EJECUTAR POR VOZ\nCaptura, compila y carga si está marcado"
EXPERIMENT_PHASE_LABELS = {
    trial_model.PHASE_BASELINE: "BASELINE (desarrollo)",
    trial_model.PHASE_DEVELOPMENT: "DEVELOPMENT_VALIDATION (desarrollo)",
    trial_model.PHASE_FORMAL: "FORMAL (requiere software congelado)",
}
# Palabras que delatan un fallo del servicio externo (API LLM / red), no del sistema evaluado.
_EXTERNAL_SERVICE_ERROR_MARKERS = (
    "timeout", "timed out", "connection", "connect", "network", "rate limit", "ratelimit", "429", "502", "503",
    "504", "service unavailable", "apiconnectionerror", "apitimeouterror", "authentication", "401", "ssl",
)
_GUI_INSTANCE_SOCKET: socket.socket | None = None


class FullIOMapWindow(ctk.CTkToplevel):
    """Complete map editor; accepted changes are validated and persisted immediately."""

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
        self.geometry("960x700")
        self.minsize(820, 600)

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
        scroll_x = ttk.Scrollbar(tree_container, orient="horizontal", command=self.tree.xview)
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=scroll_x.set)
        self.tree.bind("<Double-1>", self._edit_on_double_click)
        self.empty_hint = ctk.CTkLabel(tree_container, text="Mapa vacío. Pulse Nueva variable para agregar su primer canal.")

        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=2, column=0, padx=20, pady=(0, 18), sticky="ew")
        for index in range(5):
            button_frame.grid_columnconfigure(index, weight=1)

        actions = [
            ("Nueva variable", self.add_variable),
            ("Editar variable", self.edit_variable),
            ("Duplicar", self.duplicate_variable),
            ("Eliminar", self.delete_variable),
            ("Editar nombre", self.edit_name),
            ("Bloquear", self.lock_selected),
            ("Desbloquear", self.unlock_selected),
            ("Marcar libre", self.mark_free_selected),
            ("Guardar", self.save),
            ("Guardar como...", self.save_as)
        ]
        self.action_buttons: list[ctk.CTkButton] = []
        for index, (text, command) in enumerate(actions):
            button = ctk.CTkButton(button_frame, text=text, command=command, font=self.app.button_font, width=110)
            button.grid(row=index // 5, column=index % 5, padx=4, pady=4, sticky="ew")
            self.action_buttons.append(button)

        library=ctk.CTkFrame(self,fg_color='transparent');library.grid(row=3,column=0,padx=20,pady=(0,12),sticky='ew')
        library.grid_columnconfigure((0,1,2),weight=1)
        for index,(label,callback) in enumerate((('Nuevo mapa',self.app.new_plc_map),('Abrir archivo…',self.app.open_map_file),('Eliminar mapa',self.app.delete_plc_map_active),('Validar mapa',self.app.validate_plc_map),('Sincronizar con TIA',self.app.sync_plc_map_with_tia),('Importar desde TIA',self.app.import_plc_map_from_tia))):
            button=ctk.CTkButton(library,text=label,command=lambda cb=callback:self._library_action(cb),font=self.app.button_font)
            button.grid(row=index//3,column=index%3,padx=4,pady=4,sticky='ew')
            if self.read_only_message:button.configure(state='disabled')
        self.app._full_map_windows=getattr(self.app,'_full_map_windows',set())
        self.app._full_map_windows.add(self)
        self.bind('<Destroy>',lambda event:self.app._full_map_windows.discard(self) if event.widget is self else None,add='+')
        if self.read_only_message:
            for button in self.action_buttons[:-2]:
                button.configure(state="disabled")

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._reload()
        self.after(50, self.focus_force)

    def _library_action(self,callback) -> None:
        if not self._can_mutate():return
        callback()
        self._refresh_everything()

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
        self.loaded_path = self.app.io_map_path
        self._load_failed = False
        try:
            self.loaded_bytes = self.loaded_path.read_bytes()
            self.io_map = json.loads(self.loaded_bytes)
        except (OSError, ValueError) as error:
            messagebox.showerror("Mapa I/O completo", f"No se pudo leer el mapa activo.\n\n{error}")
            self.io_map = {"variables": []}
            self._load_failed = True
        if self.app.active_map_dirty and not self._load_failed:
            self.io_map['variables']=self.app._collect_io_variables()
        self.title(f"Mapa I/O - {self.app.active_map_var.get() or self.app.io_map_path.stem}")
        self.tree.delete(*self.tree.get_children())
        for variable in self.io_map.get("variables", []):
            state = variable.get("state", "ASSIGNED")
            # Un canal FREE no tiene todavia un rol funcional real (seccion 12): el nombre interno
            # (necesario para indexar/autorizar el recurso) se oculta y se muestra "-" en su lugar.
            name_display = "—" if state == "FREE" else variable.get("name", "")
            self.tree.insert(
                "", "end", iid=self.app._variable_key(variable),
                values=(
                    variable.get("location", ""), name_display, variable.get("type", ""),
                    self._class_label(variable), state, variable.get("description", "")
                )
            )
        if self.io_map.get("variables"):
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.5, anchor="center")
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
        if self.app.active_map_dirty:return
        self.app.io_variables = load_io_map_variables(self.app.io_map_path)
        self.app._load_active_map_metadata_shadow()
        self.app._load_io_map_table()
        self.app._refresh_map_sync_status()

    def _edit_on_double_click(self, event) -> None:
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.edit_variable()

    def _can_mutate(self) -> bool:
        message = block_map_config_message(self.app.active_trial, self.app.active_profile_id)
        if message or self.read_only_message:
            messagebox.showwarning("Mapa I/O completo", message or self.read_only_message, parent=self)
            return False
        if self._load_failed:
            messagebox.showerror("Mapa I/O completo", "No se pudo leer el mapa. Vuelva a abrirlo antes de editar.", parent=self)
            return False
        if self.app.active_map_dirty:
            messagebox.showwarning("Mapa I/O completo", "Guarde primero los cambios pendientes del panel principal con Guardar.", parent=self)
            return False
        try:
            stale = self.app.io_map_path != self.loaded_path or self.loaded_path.read_bytes() != self.loaded_bytes
        except OSError as error:
            messagebox.showerror("Mapa I/O completo", str(error), parent=self)
            return False
        if stale:
            self._refresh_everything()
            messagebox.showwarning("Mapa I/O completo", "El mapa cambió. Se actualizó la tabla; seleccione nuevamente la variable.", parent=self)
            return False
        return True

    def _selected_variable(self, *, allow_locked: bool = False) -> dict[str, Any] | None:
        key = self._selected_address()
        variable = next((v for v in self.io_map.get("variables", []) if self.app._variable_key(v) == key), None)
        if variable is None:
            messagebox.showwarning("Mapa I/O completo", "Seleccione una variable.", parent=self)
        elif not allow_locked and variable.get("state") == "LOCKED":
            messagebox.showwarning("Mapa I/O completo", "Esta variable está bloqueada. Desbloquéela antes de modificarla.", parent=self)
            return None
        return variable

    def _persist_variables(self, variables: list[dict[str, Any]], selection: dict[str, Any] | None = None,
                           *, history_entries: list[dict[str, Any]] | None = None) -> bool:
        if not self._can_mutate():
            return False
        validation = validate_plc_variable_map({**self.io_map, "variables": variables})
        if validation["errors"]:
            messagebox.showerror("Mapa I/O completo", "\n".join(validation["errors"][:6]), parent=self)
            return False
        try:
            save_plc_map(self.loaded_path, variables, metadata_patch={"dirty": False}, history_entries=history_entries)
        except (OSError, ValueError) as error:
            messagebox.showerror("Mapa I/O completo", f"No se pudo guardar el mapa.\n\n{error}", parent=self)
            return False
        self.app._rollback_pending_map_transaction("edicion manual del mapa")
        self.app._invalidate_download_readiness()
        self._refresh_everything()
        if selection:
            key = self.app._variable_key(selection)
            if self.tree.exists(key):
                self.tree.selection_set(key)
                self.tree.see(key)
        self.app._log("Mapa I/O completo: cambios validados y guardados.")
        return True

    def _edit_entry(self, original: dict[str, Any] | None = None, *, duplicate: bool = False) -> None:
        data = copy.deepcopy(original) if original else None
        if duplicate and data:
            data["name"] += "_Copia"
            data["location"] = ""
            data["state"] = "ASSIGNED"
            data["aliases"] = []
        others = [v for v in self.io_map.get("variables", []) if duplicate or v is not original]
        title = "Duplicar variable" if duplicate else "Editar variable" if original else "Nueva variable"
        dialog = VariableEditorDialog(self, title, data, other_variables=others)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        entry = dialog.result
        for field in program_bindings.BINDING_FIELDS:
            entry.pop(field, None)
        if entry.get("state") == "ASSIGNED":
            entry["assignment_source"] = program_bindings.SOURCE_MANUAL
        variables = [entry if v is original and not duplicate else v for v in self.io_map.get("variables", [])]
        if original is None or duplicate:
            variables.append(entry)
        self._persist_variables(variables, selection=entry)

    def add_variable(self) -> None:
        if self._can_mutate():
            self._edit_entry()

    def edit_variable(self) -> None:
        if self._can_mutate():
            variable = self._selected_variable()
            if variable is not None:
                self._edit_entry(variable)

    def duplicate_variable(self) -> None:
        if self._can_mutate():
            variable = self._selected_variable(allow_locked=True)
            if variable is not None:
                self._edit_entry(variable, duplicate=True)

    def delete_variable(self) -> None:
        if not self._can_mutate():
            return
        variable = self._selected_variable()
        if variable is not None and messagebox.askyesno(
            "Eliminar variable", f"¿Eliminar {variable['name']} ({variable.get('location') or 'interna'}) del mapa?",
            parent=self
        ):
            self._persist_variables([v for v in self.io_map["variables"] if v is not variable])

    def edit_name(self) -> None:
        if not self._can_mutate():
            return
        address = self._selected_address()
        if address is None:
            messagebox.showwarning("Editar nombre", "Seleccione un canal.")
            return
        variable = find_variable_by_address(self.io_map, address)
        if variable is None:
            # Internal variables have a name-based row key rather than a physical address.
            self.edit_variable()
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
            if not self._persist_variables(updated_map["variables"], history_entries=history_entries):
                return
        except ValueError as error:
            messagebox.showerror("Editar nombre", str(error))
            return

        self.app._log(f"Mapa I/O completo: {address} renombrado a {new_name}.")

    def _apply_state_change(self, new_state: str, guard_locked: bool = False) -> None:
        if not self._can_mutate():
            return
        address = self._selected_address()
        if address is None:
            messagebox.showwarning("Mapa I/O completo", "Seleccione un canal.")
            return
        variable = self._selected_variable(allow_locked=not guard_locked)
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
            for entry in updated_map["variables"]:
                if entry.get("name") == variable.get("name"):
                    for field in program_bindings.BINDING_FIELDS:
                        entry.pop(field, None)
                    if new_state == "ASSIGNED":
                        entry["assignment_source"] = program_bindings.SOURCE_MANUAL
            self._persist_variables(updated_map["variables"])
        except ValueError as error:
            messagebox.showerror("Mapa I/O completo", str(error))
            return

    def lock_selected(self) -> None:
        self._apply_state_change("LOCKED")

    def unlock_selected(self) -> None:
        self._apply_state_change("ASSIGNED")

    def mark_free_selected(self) -> None:
        self._apply_state_change("FREE", guard_locked=True)

    def save(self) -> None:
        try:
            stale = self.loaded_path != self.app.io_map_path or self.loaded_path.read_bytes() != self.loaded_bytes
        except OSError as error:
            messagebox.showerror("Mapa I/O completo", str(error), parent=self)
            return
        if stale:
            if not self.app.active_map_dirty:
                self._refresh_everything()
            messagebox.showwarning("Mapa I/O completo", "El mapa cambió. Vuelva a abrirlo antes de guardar cambios pendientes.", parent=self)
            return
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



def master_info_lines(config: dict[str, Any]) -> list[str]:
    """Texto del panel TIA MASTER (Configurar TIA)."""
    validation = config.get("validation") or {}
    snapshot = config.get("snapshot") or {}
    if not config.get("path"):
        return ["Sin TIA MASTER seleccionado."]
    lines = [
        f"Ruta: {config.get('path')}",
        f"Nombre: {validation.get('project_name') or '-'}",
        f"TIA version: {validation.get('tia_version') or '-'}",
        f"CPU detectada: {validation.get('cpu_device_item') or '-'} (software PLC: {validation.get('plc_name') or '-'})",
        f"Modelo CPU: {validation.get('cpu_type_name') or '(TypeName no disponible via Openness)'}",
        f"Referencia / firmware: {validation.get('cpu_order_number') or validation.get('cpu_type_identifier') or '-'}"
        f" / {validation.get('cpu_firmware') or '-'}",
        f"Interfaz X1: {'SI' if validation.get('x1_interface_present') else ('-' if not validation else 'NO')}",
        f"IP (X1): {validation.get('x1_ip_address') or '-'}   (todas: {', '.join(validation.get('ip_addresses') or []) or '-'})",
        f"PLC_Agent_IO: {validation.get('plc_agent_io') or '-'}",
        f"Estado de validacion: {validation.get('status') or 'SIN VALIDAR'}",
        f"Status: {validation.get('master_status') or 'INVALID'}"
        f"{'   (criterios FORMAL cumplidos; FORMAL_READY requiere aprobacion explicita)' if validation.get('formal_ready_criteria_met') else ''}",
        f"Bloques en el MASTER: {validation.get('block_count', '-')}",
        f"Hash SHA-256 (snapshot): {snapshot.get('archive_sha256') or '-'}",
        f"Fecha de validacion: {validation.get('validated_at') or '-'}",
        f"Snapshot: {(config.get('snapshot') or {}).get('archive_path') or (validation.get('archive') or {}).get('archive_expected_path') or '-'}",
    ]
    actual = (validation.get("archive") or {}).get("archive_actual_files_created")
    if actual is not None and not config.get("snapshot"):
        lines.append(f"Archivos creados realmente por Archive: {', '.join(actual) or '(ninguno)'}")
    for message in (validation.get("errors") or []) + (validation.get("warnings") or []):
        lines.append(f"! {message}")
    return lines


def normal_project_lines(normal: dict[str, Any]) -> list[str]:
    validation = normal.get("validation") or {}
    lines = [f"Ruta: {normal.get('path') or '(no configurado)'}",
             f"Estado: {validation.get('status') or 'SIN VALIDAR'}",
             f"Openness listo: {validation.get('openness_ready') if validation else '-'}",
             f"Fecha de validacion: {validation.get('validated_at') or '-'}"]
    if normal.get("source"):
        lines.append(f"(origen: {normal['source']})")
    return lines + [f"! {error}" for error in validation.get("errors") or []]


class TiaConfigDialog(ctk.CTkToplevel):
    """
    Configurar TIA V18 con DOS proyectos independientes:
      PROYECTO TIA - MODO NORMAL     (tia.normal_project: se importa/compila/descarga; puede modificarse)
      TIA MASTER - EXPERIMENTACION   (tia.experiment_master: plantilla inmutable; se copia por ensayo)
    Seleccionar o validar uno nunca cambia el otro.
    """

    def __init__(self, app: "VozLLMPLCGUI") -> None:
        super().__init__(app)
        self.app = app
        self.title("Configurar TIA V18")
        self.geometry("780x720")
        self.grid_columnconfigure(0, weight=1)
        self._worker: threading.Thread | None = None
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()

        # --- A) PROYECTO TIA - MODO NORMAL
        ctk.CTkLabel(self, text="PROYECTO TIA — MODO NORMAL", font=app.section_label_font).grid(
            row=0, column=0, padx=16, pady=(14, 2), sticky="w")
        normal_row = ctk.CTkFrame(self, fg_color="transparent")
        normal_row.grid(row=1, column=0, padx=16, sticky="ew")
        normal_row.grid_columnconfigure(0, weight=1)
        self.normal_path_var = tk.StringVar(value=tia_projects.normal_project_path(app.project_root))
        ctk.CTkEntry(normal_row, textvariable=self.normal_path_var, state="readonly", font=app.body_font).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(normal_row, text="Seleccionar", width=110, command=self.select_normal, font=app.button_font).grid(row=0, column=1, padx=(6, 0))
        ctk.CTkButton(normal_row, text="Validar", width=90, command=self.validate_normal, font=app.button_font).grid(row=0, column=2, padx=(6, 0))
        self.normal_box = ctk.CTkTextbox(self, height=110, font=app.body_font)
        self.normal_box.grid(row=2, column=0, padx=16, pady=(6, 14), sticky="ew")

        # --- B) TIA MASTER - EXPERIMENTACION
        ctk.CTkLabel(self, text="TIA MASTER — EXPERIMENTACIÓN", font=app.section_label_font).grid(
            row=3, column=0, padx=16, pady=(4, 2), sticky="w")
        path_row = ctk.CTkFrame(self, fg_color="transparent")
        path_row.grid(row=4, column=0, padx=16, sticky="ew")
        path_row.grid_columnconfigure(0, weight=1)
        self.master_path_var = tk.StringVar(value=deferred_evaluator.load_master_config(app.project_root).get("path", ""))
        ctk.CTkEntry(path_row, textvariable=self.master_path_var, state="readonly", font=app.body_font).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(path_row, text="Seleccionar Master", width=150, command=self.select_master, font=app.button_font).grid(
            row=0, column=1, padx=(6, 0))
        self.validate_button = ctk.CTkButton(path_row, text="Validar Master", width=130, command=self.validate_master, font=app.button_font)
        self.validate_button.grid(row=0, column=2, padx=(6, 0))
        self.info_box = ctk.CTkTextbox(self, height=300, font=app.body_font)
        self.info_box.grid(row=5, column=0, padx=16, pady=(6, 14), sticky="nsew")
        self.grid_rowconfigure(5, weight=1)
        self.refresh_info()

    def select_normal(self) -> None:
        self.app.configure_tia_openness()
        self.refresh_info()

    def validate_normal(self) -> None:
        normal = tia_projects.validate_normal_project(self.app.project_root)
        self.app._log(f"[TIA NORMAL] {(normal.get('validation') or {}).get('status')}: {normal.get('path')}")
        self.refresh_info()

    def refresh_info(self) -> None:
        self.normal_path_var.set(tia_projects.normal_project_path(self.app.project_root))
        self.master_path_var.set(deferred_evaluator.load_master_config(self.app.project_root).get("path", ""))
        for box, lines in ((self.normal_box, normal_project_lines(tia_projects.get_normal_project(self.app.project_root))),
                           (self.info_box, master_info_lines(deferred_evaluator.load_master_config(self.app.project_root)))):
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", "\n".join(lines))
            box.configure(state="disabled")

    def select_master(self, path: str | None = None) -> None:
        current = self.master_path_var.get().strip()
        chosen = path or filedialog.askopenfilename(
            title="Seleccione el proyecto TIA MASTER (V18)",
            initialdir=str(Path(current).parent) if current else str(self.app.project_root),
            filetypes=[("Proyecto TIA Portal V18", "*.ap18")], parent=self,
        )
        if not chosen:
            return
        try:
            deferred_evaluator.select_master(self.app.project_root, chosen)
        except ValueError as error:
            messagebox.showwarning("TIA MASTER", str(error), parent=self)
            return
        self.app._log(f"[TIA MASTER] Seleccionado: {chosen} (pendiente de VALIDAR MASTER)")
        self.refresh_info()

    def validate_master(self) -> None:
        if self._worker is not None or self.app._tia_busy():
            messagebox.showwarning("TIA MASTER", "Hay otra operacion TIA en curso.", parent=self)
            return
        self.validate_button.configure(state="disabled")
        self.app._log("[TIA MASTER] Validando MASTER (TIA Openness)...")

        def _worker() -> None:
            try:
                self._queue.put(("ok", deferred_evaluator.validate_master(self.app.project_root)))
            except Exception as error:  # pragma: no cover - feedback de GUI
                self._queue.put(("error", str(error)))

        self._worker = threading.Thread(target=_worker, name="tia-master", daemon=True)
        self._worker.start()
        self.after(500, self._poll)

    def _poll(self) -> None:
        try:
            outcome, payload = self._queue.get_nowait()
        except queue.Empty:
            self.after(500, self._poll)
            return
        self._worker = None
        self.validate_button.configure(state="normal")
        self.refresh_info()
        if outcome == "error":
            self.app._log(f"[TIA MASTER] Error: {payload}")
            messagebox.showerror("TIA MASTER", str(payload), parent=self)
            return
        validation = payload.get("validation") or {}
        self.app._log(f"[TIA MASTER] {validation.get('status')} / {validation.get('master_status')}")


class DeferredEvaluationDialog(ctk.CTkToplevel):
    """EVALUAR ENSAYO GUARDADO: resumen previo, INICIAR EVALUACION y tabla de veredicto."""

    def __init__(self, app: "VozLLMPLCGUI", trial_dir: Path, retry: bool = False, autostart: bool = False) -> None:
        super().__init__(app)
        self.app = app
        self.trial_dir = Path(trial_dir)
        self.retry = retry
        self.title(("Ejecutar ensayo completo" if autostart else "Evaluar ensayo guardado") + (" (reintento tecnico)" if retry else ""))
        self.geometry("720x620")
        self.grid_columnconfigure(0, weight=1)
        self.summary_box = ctk.CTkTextbox(self, height=230, font=app.body_font)
        self.summary_box.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="ew")
        row = 1
        self.retry_reason_var = tk.StringVar(value="")
        if retry:
            ctk.CTkLabel(self, text="Motivo del reintento (obligatorio, solo INFRASTRUCTURE_ERROR):", font=app.body_font).grid(
                row=row, column=0, padx=16, sticky="w")
            ctk.CTkEntry(self, textvariable=self.retry_reason_var, font=app.body_font).grid(row=row + 1, column=0, padx=16, sticky="ew")
            row += 2
        self.start_button = ctk.CTkButton(self, text="INICIAR EVALUACION", height=40, fg_color="#0F766E", hover_color="#115E59",
                                          command=self.start, font=ctk.CTkFont(size=14, weight="bold"))
        self.start_button.grid(row=row, column=0, padx=16, pady=8, sticky="ew")
        self.result_box = ctk.CTkTextbox(self, height=230, font=ctk.CTkFont(family="Consolas", size=13))
        self.result_box.grid(row=row + 1, column=0, padx=16, pady=(0, 8), sticky="nsew")
        self.grid_rowconfigure(row + 1, weight=1)
        ctk.CTkButton(self, text="VER DETALLE", command=lambda: app.show_trial_detail(self.trial_dir), font=app.button_font).grid(
            row=row + 2, column=0, padx=16, pady=(0, 14), sticky="w")
        self._fill(self.summary_box, deferred_evaluator.evaluation_summary_lines(app.project_root, self.trial_dir))
        check = deferred_evaluator.precheck(app.project_root, self.trial_dir, "reintento" if retry else None)
        if not check["ok"]:
            self._fill(self.result_box, ["PRECHECK: ABORT"] + check["errors"])
            self.start_button.configure(state="disabled")
        else:
            self._fill(self.result_box, ["PRECHECK: OK"] + [f"! {w}" for w in check["warnings"]])
            if autostart:
                # EJECUTAR ENSAYO COMPLETO: la evaluacion sigue sola tras la generacion (un clic = un ensayo).
                self.after(100, self.start)

    @staticmethod
    def _fill(box: ctk.CTkTextbox, lines: list[str]) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", "\n".join(lines))
        box.configure(state="disabled")

    def start(self) -> None:
        reason = self.retry_reason_var.get().strip() if self.retry else None
        if self.retry and not reason:
            messagebox.showwarning("Reintentar evaluacion", "Indique el motivo del reintento tecnico.", parent=self)
            return
        self.start_button.configure(state="disabled")
        self._fill(self.result_box, ["Evaluando... (TIA Portal -> .zap18 -> PLCSIM -> Oracle)"])
        self.app._start_deferred_evaluation(self.trial_dir, reason, self)

    def show_result(self, outcome: str, payload: Any) -> None:
        if outcome == "error" or (isinstance(payload, dict) and payload.get("aborted")):
            errors = payload.get("errors") if isinstance(payload, dict) else [str(payload)]
            self._fill(self.result_box, ["EVALUACION NO REALIZADA"] + list(errors or []))
            return
        record = trial_model.load_trial(self.trial_dir)
        # El resumen superior se lleno al abrir el dialogo ("PENDIENTE DE EVALUACION"): se recalcula ahora
        # desde lo persistido para no dejar un estado visual obsoleto.
        self._fill(self.summary_box, deferred_evaluator.evaluation_summary_lines(self.app.project_root, self.trial_dir))
        header = f"{record.get('case_id')} · {record.get('variant_id')} · {record.get('input_mode')}"
        self._fill(self.result_box, [header, ""] + [f"{label:<20}{value}" for label, value in deferred_evaluator.verdict_table(record)]
                   + [""] + [f"! {error}" for error in (payload.get("errors") or [])]
                   + ["", "El siguiente ensayo NO se inicia automaticamente."])


class TextBatchDialog(ctk.CTkToplevel):
    """
    EJECUTAR LOTE TEXT / VOICE_CLEAN / VOICE_NOISE: seleccion (fase, casos, variantes) y progreso del lote abierto.
    Un solo motor de lotes (text_batch); la modalidad la fija el boton que abre el dialogo (o el lote abierto).
    """

    PHASES = {"DEVELOPMENT": trial_model.PHASE_DEVELOPMENT, "FORMAL": trial_model.PHASE_FORMAL}
    MODE_NOTES = {
        trial_model.INPUT_MODE_TEXT: "Modalidad: TEXT (automatico)",
        trial_model.INPUT_MODE_VOICE_CLEAN: "Modalidad: VOICE_CLEAN (asistido: una locucion humana por celda; el par noisy "
                                            "se congela antes del ASR)",
        trial_model.INPUT_MODE_VOICE_NOISE: "Modalidad: VOICE_NOISE (automatico: estimulos noisy congelados; nunca usa el microfono)",
    }

    def __init__(self, app: "VozLLMPLCGUI", input_mode: str = trial_model.INPUT_MODE_TEXT) -> None:
        super().__init__(app)
        self.app = app
        self.input_mode = input_mode
        self.title(f"Lote {input_mode}")
        self.geometry("760x760")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        setup = ctk.CTkFrame(self)
        setup.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="ew")
        setup.grid_columnconfigure((0, 1, 2), weight=1, uniform="batch_setup")
        self.setup_frame = setup
        ctk.CTkLabel(setup, text="Fase", font=app.section_label_font).grid(row=0, column=0, padx=10, pady=(8, 2), sticky="w")
        self.phase_var = tk.StringVar(value="DEVELOPMENT")
        ctk.CTkSegmentedButton(setup, values=list(self.PHASES), variable=self.phase_var, command=lambda _v: self._update_total(),
                               font=app.button_font).grid(row=1, column=0, columnspan=3, padx=10, pady=(0, 8), sticky="ew")
        ctk.CTkLabel(setup, text="Casos", font=app.section_label_font).grid(row=2, column=0, padx=10, pady=(4, 2), sticky="w")
        self.d_var, self.p_var = tk.BooleanVar(value=True), tk.BooleanVar(value=False)
        ctk.CTkCheckBox(setup, text="D01-D20", variable=self.d_var, command=self._update_total, font=app.body_font).grid(
            row=3, column=0, padx=10, sticky="w")
        ctk.CTkCheckBox(setup, text="P01-P12", variable=self.p_var, command=self._update_total, font=app.body_font).grid(
            row=3, column=1, padx=10, sticky="w")
        self.range_var = tk.StringVar(value="")
        self.range_var.trace_add("write", lambda *_a: self._update_total())
        ctk.CTkLabel(setup, text="Rango opcional (p. ej. D01-D03, P02):", font=app.body_font).grid(
            row=4, column=0, columnspan=3, padx=10, pady=(8, 0), sticky="w")
        ctk.CTkEntry(setup, textvariable=self.range_var, font=app.body_font).grid(row=5, column=0, columnspan=3, padx=10, sticky="ew")
        ctk.CTkLabel(setup, text="Variantes", font=app.section_label_font).grid(row=6, column=0, padx=10, pady=(8, 2), sticky="w")
        self.variant_vars = {variant: tk.BooleanVar(value=True) for variant in text_batch.VARIANT_ORDER}
        for column, (variant, var) in enumerate(self.variant_vars.items()):
            ctk.CTkCheckBox(setup, text=variant, variable=var, command=self._update_total, font=app.body_font).grid(
                row=7, column=column, padx=10, sticky="w")
        ctk.CTkLabel(setup, text=self.MODE_NOTES[input_mode], font=app.body_font, wraplength=640, justify="left").grid(
            row=8, column=0, columnspan=3, padx=10, pady=(8, 0), sticky="w")
        self.total_var = tk.StringVar(value="")
        ctk.CTkLabel(setup, textvariable=self.total_var, font=app.section_label_font, justify="left", wraplength=640).grid(
            row=9, column=0, columnspan=3, padx=10, pady=(4, 4), sticky="w")
        self.start_button = ctk.CTkButton(setup, text="INICIAR LOTE", height=40, fg_color="#0F766E", hover_color="#115E59",
                                          command=self.start, font=ctk.CTkFont(size=14, weight="bold"))
        self.start_button.grid(row=10, column=0, columnspan=3, padx=10, pady=(4, 10), sticky="ew")

        self.progress_box = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=13))
        self.progress_box.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="nsew")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, padx=16, pady=(0, 14), sticky="ew")
        buttons.grid_columnconfigure((0, 1), weight=1, uniform="batch_buttons")
        self.resume_button = ctk.CTkButton(buttons, text="REANUDAR", command=self.resume, font=app.button_font)
        self.resume_button.grid(row=0, column=0, padx=(0, 4), pady=3, sticky="ew")
        self.pause_button = ctk.CTkButton(buttons, text="PAUSAR DESPUES DEL ENSAYO ACTUAL", command=self.app.request_text_batch_pause,
                                          font=app.button_font)
        self.pause_button.grid(row=0, column=1, padx=(4, 0), pady=3, sticky="ew")
        self.retry_button = ctk.CTkButton(buttons, text="REINTENTAR ESTE ENSAYO", command=self.retry, font=app.button_font)
        self.retry_button.grid(row=1, column=0, padx=(0, 4), pady=3, sticky="ew")
        self.stop_button = ctk.CTkButton(buttons, text="DETENER LOTE", fg_color="#B91C1C", hover_color="#991B1B",
                                         command=self.stop, font=app.button_font)
        self.stop_button.grid(row=1, column=1, padx=(4, 0), pady=3, sticky="ew")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._update_total()
        self.refresh()
        self.after(1000, self._tick)

    def selection(self) -> tuple[str, list[str], list[str]]:
        groups = (["D"] if self.d_var.get() else []) + (["P"] if self.p_var.get() else [])
        case_ids = text_batch.parse_case_selection(self.app.project_root, self.range_var.get(), groups)
        variants = [variant for variant, var in self.variant_vars.items() if var.get()]
        phase = self.PHASES[self.phase_var.get()]
        if phase == trial_model.PHASE_FORMAL:
            experimental_design.require_formal_cases(self.app.project_root, case_ids)
        return phase, case_ids, variants

    def _update_total(self) -> None:
        try:
            phase, case_ids, variants = self.selection()
            plan = text_batch.build_plan(self.app.project_root, case_ids, variants, self.input_mode)
        except ValueError as error:
            self.total_var.set(f"Seleccion invalida: {error}")
            return
        not_evaluable = sorted({entry["case_id"] for entry in plan if not entry["evaluable"]})
        text = f"Total de ensayos: {len(plan)}"
        if not_evaluable:
            text += (f"\n{len(not_evaluable)} caso(s) ({not_evaluable[0]}...{not_evaluable[-1]}): el Oracle requiere extension del "
                     "Runtime; se generan pero no se evaluan" + (" - FORMAL no lo permite." if phase == trial_model.PHASE_FORMAL else "."))
        if self.input_mode != trial_model.INPUT_MODE_TEXT:
            try:
                summary = formal_audio.corpus_summary(self.app.project_root, phase)
                text += (f"\nCorpus {phase}: clean grabados {summary['recorded_clean']}/{summary['total']} · pares listos "
                         f"{summary['noise_pairs_ready']}/{summary['total']} · SNR {formal_audio.load_config(self.app.project_root)['target_snr_db']} dB")
            except (OSError, ValueError, KeyError) as error:
                text += f"\nCorpus de audio no legible: {error}"
        self.total_var.set(text)

    def start(self) -> None:
        title = f"Lote {self.input_mode}"
        try:
            phase, case_ids, variants = self.selection()
        except ValueError as error:
            messagebox.showwarning(title, str(error), parent=self)
            return
        if phase == trial_model.PHASE_FORMAL and not messagebox.askyesno(
                f"{title} FORMAL", "Los resultados FORMAL son oficiales. ¿Iniciar el lote FORMAL?", parent=self):
            return
        result = self.app.start_text_batch(phase, case_ids, variants, self.input_mode)
        if not result["ok"] and not result.get("paused"):
            messagebox.showwarning(title, "No se inicia el lote:\n\n" + "\n".join(result["errors"][:10]), parent=self)
        self.refresh()

    def resume(self) -> None:
        result = self.app.resume_text_batch()
        if not result["ok"]:
            messagebox.showwarning("Lote TEXT", "El lote sigue pausado:\n\n" + "\n".join(result["errors"][:6]), parent=self)
        self.refresh()

    def retry(self) -> None:
        reason = simpledialog.askstring("Reintentar ensayo", "Motivo del reintento (obligatorio):", parent=self)
        if not reason:
            return
        result = self.app.retry_text_batch_trial(reason)
        if not result["ok"]:
            messagebox.showwarning("Lote TEXT", "\n".join(result["errors"]), parent=self)
        self.refresh()

    def stop(self) -> None:
        manifest = self.app._text_batch_manifest()
        if manifest and messagebox.askyesno(
                "Detener lote", "El lote se cerrara (los ensayos hechos se conservan). Si hay un ensayo en curso, "
                "se detiene al terminarlo. ¿Continuar?", parent=self):
            self.app.stop_text_batch()
        self.refresh()

    def refresh(self) -> None:
        manifest = self.app._text_batch_manifest()
        status = (manifest or {}).get("status")
        open_batch = status in text_batch.OPEN_STATUSES
        running = status == text_batch.STATUS_RUNNING
        waiting_retry = bool((manifest or {}).get('automatic_retry_pending'))
        paused = status in (text_batch.STATUS_PAUSED, text_batch.STATUS_CREATED)
        attention = paused and any(e["status"] in text_batch.ATTENTION_ENTRY_STATES for e in manifest["ordered_trial_plan"])
        for widget in self.setup_frame.winfo_children():
            try:
                widget.configure(state="disabled" if open_batch else "normal")
            except (tk.TclError, ValueError):
                pass
        self.resume_button.configure(state="normal" if paused and not attention and not waiting_retry else "disabled")
        self.retry_button.configure(state="normal" if attention and not waiting_retry else "disabled")
        self.pause_button.configure(state="normal" if (running or waiting_retry) and not manifest.get("pause_requested") else "disabled")
        self.stop_button.configure(state="normal" if open_batch else "disabled")
        lines = self.app.text_batch_progress_lines()
        if paused and not running and open_batch and status == text_batch.STATUS_PAUSED:
            lines = ([f"LOTE {manifest.get('input_mode') or 'TEXT'} INCOMPLETO"] if not attention else []) + lines
        self.progress_box.configure(state="normal")
        self.progress_box.delete("1.0", "end")
        self.progress_box.insert("1.0", "\n".join(lines))
        self.progress_box.configure(state="disabled")

    def _tick(self) -> None:
        try:
            if self.winfo_exists():
                if self.app._text_batch_running():
                    self.refresh()
                self.after(1000, self._tick)
        except tk.TclError:
            pass

    def _close(self) -> None:
        self.app._text_batch_dialog = None
        self.destroy()


class CleanBatchCellDialog(ctk.CTkToplevel):
    """
    Lote VOICE_CLEAN asistido: una celda sin locucion. Muestra progreso X/N, caso, variante, el comando EXACTO y los
    estados (audio clean, par noisy, ensayo). GRABAR Y EJECUTAR -> DETENER Y EJECUTAR: el WAV se congela (clean + noisy)
    y el ensayo arranca solo. PAUSAR LOTE: no graba nada y el lote queda pausado (sin resultado experimental).
    """

    def __init__(self, app: "VozLLMPLCGUI", entry: dict[str, Any], manifest: dict[str, Any], audio_state: str,
                 pair_state: str) -> None:
        super().__init__(app)
        self.app = app
        self.result: dict[str, Any] | None = None
        self._device: dict[str, Any] = app.speech_recognizer.get_input_device_info()
        self.title(f"Lote VOICE_CLEAN · {entry['index'] + 1} / {manifest['total_trials']}")
        self.geometry("720x420")
        self.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(self, text=f"{entry['index'] + 1} / {manifest['total_trials']}  ·  {entry['case_id']}  ·  {entry['variant_id']}  "
                                f"·  {manifest['phase']}", font=app.section_label_font).grid(
            row=0, column=0, columnspan=2, padx=16, pady=(14, 4), sticky="w")
        ctk.CTkLabel(self, text="Lea en voz alta exactamente este comando:", font=app.body_font).grid(
            row=1, column=0, columnspan=2, padx=16, sticky="w")
        ctk.CTkLabel(self, text=f'"{entry["reference_text"]}"', wraplength=660, justify="left",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=2, column=0, columnspan=2, padx=16, pady=10, sticky="w")
        ctk.CTkLabel(self, text=f"AUDIO CLEAN: {audio_state}   ·   AUDIO NOISE PAIR: {pair_state}   ·   ENSAYO: {entry['status']}",
                     font=app.body_font).grid(row=3, column=0, columnspan=2, padx=16, sticky="w")
        self.status_var = tk.StringVar(value=f"Microfono: {self._device.get('name') or self._device.get('error') or '-'}")
        ctk.CTkLabel(self, textvariable=self.status_var, font=app.body_font).grid(row=4, column=0, columnspan=2, padx=16, pady=(6, 0), sticky="w")
        self.record_button = ctk.CTkButton(self, text="GRABAR Y EJECUTAR", height=40, fg_color="#0F766E", hover_color="#115E59",
                                           command=self.toggle, font=ctk.CTkFont(size=14, weight="bold"))
        self.record_button.grid(row=5, column=0, padx=(16, 4), pady=16, sticky="ew")
        self.pause_button = ctk.CTkButton(self, text="PAUSAR LOTE", command=self.pause, font=app.button_font)
        self.pause_button.grid(row=5, column=1, padx=(4, 16), pady=16, sticky="ew")
        self.protocol("WM_DELETE_WINDOW", self.pause)

    def toggle(self) -> None:
        recognizer = self.app.speech_recognizer
        if not recognizer.is_recording():
            try:
                recognizer.start_recording()
            except RuntimeError as error:
                self.status_var.set(f"No se pudo grabar: {error}")
                return
            self._recorded_at = datetime.now().isoformat(timespec="seconds")
            self.record_button.configure(text="DETENER Y EJECUTAR")
            self.pause_button.configure(state="disabled")
            self._tick()
            return
        try:
            path = recognizer.stop_recording()
        except RuntimeError as error:
            path = None
            self.status_var.set(f"Grabacion sin audio: {error}")
        if not path:
            # Sin audio no hay ensayo: se puede volver a grabar (no se congelo nada).
            self.record_button.configure(text="GRABAR Y EJECUTAR")
            self.pause_button.configure(state="normal")
            return
        self.result = {"path": str(path), "device": self._device, "sample_rate": recognizer.sample_rate,
                       "channels": recognizer.channels, "recorded_at": getattr(self, "_recorded_at", None)}
        self.destroy()

    def _tick(self) -> None:
        recognizer = self.app.speech_recognizer
        if not recognizer.is_recording():
            return
        self.status_var.set(f"Grabando... {recognizer.recording_elapsed_seconds()} s · nivel {recognizer.get_current_level().get('peak')}")
        self.after(200, self._tick)

    def pause(self) -> None:
        if self.app.speech_recognizer.is_recording():
            return  # iniciada la grabacion solo se puede DETENER Y EJECUTAR
        self.result = None
        self.destroy()


class AudioCorpusDialog(ctk.CTkToplevel):
    """FORMAL AUDIO CORPUS: estado de las 96 celdas, master de ruido, integridad, reproduccion y metadatos (solo lectura)."""

    def __init__(self, app: "VozLLMPLCGUI", phase: str = trial_model.PHASE_FORMAL) -> None:
        super().__init__(app)
        self.app = app
        self.phase = phase
        self.title(f"Corpus de audio {phase}")
        self.geometry("860x720")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.summary_var = tk.StringVar(value="")
        ctk.CTkLabel(self, textvariable=self.summary_var, font=ctk.CTkFont(family="Consolas", size=13), justify="left", anchor="w").grid(
            row=0, column=0, padx=16, pady=(14, 8), sticky="ew")
        table = ctk.CTkFrame(self, fg_color="transparent")
        table.grid(row=1, column=0, padx=16, sticky="nsew")
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=("cell", "state", "clean", "noisy", "snr", "uses"), show="headings", selectmode="browse")
        for column, heading, width in (("cell", "Celda", 90), ("state", "Estado", 170), ("clean", "Clean SHA", 120),
                                       ("noisy", "Noisy SHA", 120), ("snr", "SNR medido", 90), ("uses", "Ensayos", 220)):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns")
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, padx=16, pady=12, sticky="ew")
        buttons.grid_columnconfigure((0, 1, 2, 3), weight=1)
        for column, (text, command) in enumerate((("REPRODUCIR CLEAN", lambda: self.play(formal_audio.CLEAN_FILENAME)),
                                                  ("REPRODUCIR NOISY", lambda: self.play(formal_audio.NOISE_FILENAME)),
                                                  ("VER METADATOS", self.show_metadata), ("VERIFICAR INTEGRIDAD", self.verify_all))):
            ctk.CTkButton(buttons, text=text, command=command, font=app.button_font).grid(row=0, column=column, padx=4, sticky="ew")
        self.integrity = "-"
        self.refresh()

    def refresh(self) -> None:
        root = self.app.project_root
        summary = formal_audio.corpus_summary(root, self.phase)
        master = formal_audio.noise_master_status(root, self.phase)
        config = formal_audio.load_config(root)
        total = summary["total"]
        self.summary_var.set("\n".join([
            f"FORMAL AUDIO CORPUS ({self.phase})",
            f"Recorded clean:          {summary['recorded_clean']} / {total}",
            f"Noise pairs ready:       {summary['noise_pairs_ready']} / {total}",
            f"Clean trials completed:  {summary['clean_trials']} / {total}",
            f"Noise trials completed:  {summary['noise_trials']} / {total}",
            f"SNR target:              {config['target_snr_db']} dB (tolerancia {config['snr_tolerance_db']} dB)",
            f"Noise master:            " + (f"READY {master['sha256'][:12]} [{master['source']}]" if master["ready"] else "MISSING"),
            f"Integrity:               {self.integrity}"]))
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for key, cell in formal_audio.load_corpus(root, self.phase)["cells"].items():
            uses = ", ".join(f"{u['condition'].replace('VOICE_', '')}:{u['trial_id']}" for u in cell["uses"])
            self.tree.insert("", "end", iid=key, values=(key, cell["state"], (cell.get("clean_sha256") or "-")[:12],
                                                         (cell.get("noisy_sha256") or "-")[:12], cell.get("measured_snr_db", "-"), uses))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])  # refrescar (p.ej. tras VERIFICAR INTEGRIDAD) no pierde la celda elegida

    def _selected(self) -> tuple[str, str] | None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Corpus de audio", "Seleccione una celda.", parent=self)
            return None
        case_id, variant = selection[0].split("_")
        return case_id, variant

    def play(self, filename: str) -> None:
        cell = self._selected()
        if cell is None:
            return
        path = formal_audio.cell_dir(self.app.project_root, self.phase, *cell) / filename
        if not path.is_file():
            messagebox.showinfo("Corpus de audio", f"No existe {filename} para {cell[0]} {cell[1]}.", parent=self)
            return
        try:  # reproduccion de solo lectura (stdlib de Windows); nunca modifica el WAV
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except (ImportError, RuntimeError) as error:
            messagebox.showwarning("Corpus de audio", f"No se pudo reproducir: {error}", parent=self)

    def show_metadata(self) -> None:
        cell = self._selected()
        if cell is None:
            return
        path = formal_audio.cell_dir(self.app.project_root, self.phase, *cell) / formal_audio.CELL_MANIFEST
        text = path.read_text(encoding="utf-8") if path.is_file() else "Celda sin grabar."
        window = ctk.CTkToplevel(self)
        window.title(f"{cell[0]} {cell[1]} · {formal_audio.CELL_MANIFEST}")
        window.geometry("720x620")
        box = ctk.CTkTextbox(window, font=ctk.CTkFont(family="Consolas", size=12))
        box.pack(fill="both", expand=True, padx=10, pady=10)
        box.insert("1.0", text)
        box.configure(state="disabled")

    def verify_all(self) -> None:
        failures = []
        for key, cell in formal_audio.load_corpus(self.app.project_root, self.phase)["cells"].items():
            if cell["state"] != formal_audio.STATE_NOT_RECORDED:
                check = formal_audio.verify_cell(self.app.project_root, self.phase, cell["case_id"], cell["variant"])
                if not check["ok"]:
                    failures.append(f"{key}: {'; '.join(check['errors'])}")
        self.integrity = "PASS" if not failures else f"FAIL ({len(failures)})"
        self.refresh()
        if failures:
            messagebox.showwarning("Integridad del corpus", "\n".join(failures[:15]), parent=self)


class VoiceCaptureDialog(ctk.CTkToplevel):
    """
    Captura de voz de un ensayo: muestra caso, variante y la FRASE DE REFERENCIA. GRABAR / DETENER /
    CANCELAR ANTES DEL ENSAYO. Devuelve el WAV RAW (sin procesar) para el protocolo; cancelar antes de
    grabar no crea ningun resultado experimental.
    """

    def __init__(self, app: "VozLLMPLCGUI", case_id: str, variant_id: str, reference_text: str) -> None:
        super().__init__(app)
        self.app = app
        self.result: dict[str, Any] | None = None
        self._device: dict[str, Any] = app.speech_recognizer.get_input_device_info()
        self.title("Captura de voz del ensayo")
        self.geometry("680x360")
        self.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkLabel(self, text=f"{case_id} · {variant_id}", font=app.section_label_font).grid(
            row=0, column=0, columnspan=3, padx=16, pady=(14, 4), sticky="w")
        ctk.CTkLabel(self, text="Lea en voz alta exactamente esta frase:", font=app.body_font).grid(
            row=1, column=0, columnspan=3, padx=16, sticky="w")
        ctk.CTkLabel(self, text=f'"{reference_text}"', wraplength=620, justify="left",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=2, column=0, columnspan=3, padx=16, pady=10, sticky="w")
        self.status_var = tk.StringVar(value=f"Microfono: {self._device.get('name') or self._device.get('error') or '-'}")
        ctk.CTkLabel(self, textvariable=self.status_var, font=app.body_font).grid(row=3, column=0, columnspan=3, padx=16, sticky="w")
        self.record_button = ctk.CTkButton(self, text="GRABAR", command=self.record, font=app.button_font)
        self.record_button.grid(row=4, column=0, padx=(16, 4), pady=16, sticky="ew")
        self.stop_button = ctk.CTkButton(self, text="DETENER", command=self.stop, state="disabled", font=app.button_font)
        self.stop_button.grid(row=4, column=1, padx=4, pady=16, sticky="ew")
        self.cancel_button = ctk.CTkButton(self, text="CANCELAR ANTES DEL ENSAYO", command=self.cancel, font=app.button_font)
        self.cancel_button.grid(row=4, column=2, padx=(4, 16), pady=16, sticky="ew")
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    def record(self) -> None:
        try:
            self.app.speech_recognizer.start_recording()
        except RuntimeError as error:
            # Fallo del hardware de captura: sin audio no hay ensayo (se informa, no se clasifica como ASR).
            self.status_var.set(f"No se pudo grabar: {error}")
            return
        self._recorded_at = datetime.now().isoformat(timespec="seconds")
        self.record_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self._tick()

    def _tick(self) -> None:
        if not self.app.speech_recognizer.is_recording():
            return
        level = self.app.speech_recognizer.get_current_level()
        self.status_var.set(f"Grabando... {self.app.speech_recognizer.recording_elapsed_seconds()} s · nivel {level.get('peak')}")
        self.after(200, self._tick)

    def stop(self) -> None:
        try:
            path = self.app.speech_recognizer.stop_recording()
        except RuntimeError as error:
            path = None
            self.status_var.set(f"Grabacion sin audio: {error}")
        settings = self.app.speech_recognizer
        self.result = {"path": str(path) if path else None, "device": self._device, "sample_rate": settings.sample_rate,
                       "channels": settings.channels, "recorded_at": getattr(self, "_recorded_at", None)}
        self.destroy()

    def cancel(self) -> None:
        if self.app.speech_recognizer.is_recording():
            return  # una vez iniciada la grabacion solo se puede DETENER (el intento queda registrado)
        self.result = None
        self.destroy()

class PhysicalDownloadConfirmDialog(ctk.CTkToplevel):
    """Confirmacion obligatoria antes de una descarga automatica a un PLC FISICO."""

    def __init__(self, app: "VozLLMPLCGUI", info: dict[str, str]) -> None:
        super().__init__(app)
        self.result = False
        self.title("Programa listo para descargar al PLC físico")
        self.geometry("560x300")
        self.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(self, text="Programa listo para descargar al PLC físico", font=app.section_label_font).grid(
            row=0, column=0, columnspan=2, padx=16, pady=(16, 8), sticky="w")
        details = "\n".join([f"Destino: {info.get('destino')}", f"CPU: {info.get('cpu')}", f"IP: {info.get('ip')}",
                             f"Proyecto TIA Normal: {info.get('proyecto')}", "",
                             "La CPU puede detenerse durante la descarga."])
        ctk.CTkLabel(self, text=details, justify="left", anchor="w", font=app.body_font).grid(
            row=1, column=0, columnspan=2, padx=16, sticky="ew")
        ctk.CTkButton(self, text="CONFIRMAR DESCARGA", fg_color="#B91C1C", hover_color="#991B1B",
                      command=self._confirm, font=app.button_font).grid(row=2, column=0, padx=(16, 6), pady=16, sticky="ew")
        ctk.CTkButton(self, text="CANCELAR", command=self.destroy, font=app.button_font).grid(
            row=2, column=1, padx=(6, 16), pady=16, sticky="ew")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _confirm(self) -> None:
        self.result = True
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


from runtime_io_view import RuntimeIOTestWindow


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
        self.experiment_input_mode_var = tk.StringVar(value=INPUT_MODE_LABELS[trial_model.INPUT_MODE_TEXT])
        self.experiment_phase_var = tk.StringVar(value=EXPERIMENT_PHASE_LABELS[trial_model.PHASE_DEVELOPMENT])
        self.experiment_variant_var = tk.StringVar(value="V1")
        self.experiment_speaker_var = tk.StringVar(value="S01")
        self.experiment_noise_var = tk.StringVar(value=NOISE_LEVEL_LABELS["none"])
        self.experiment_environment_var = tk.StringVar(value=ENVIRONMENT_LABELS["simulation"])
        self.experiment_status_var = tk.StringVar(value="")
        self.experiment_stage_var = tk.StringVar(value="")
        self._experiment_stage_states: dict[str, str] = {}
        self.experiment_next_label_var = tk.StringVar(value="")
        self.experiment_variant_command_var = tk.StringVar(value="")
        self._active_variant_command_text: str = ""
        self._last_experiment_input_mode: str | None = None
        self._deferred_worker_active = False
        self._deferred_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._deferred_dialog: Any = None
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
        # MODO NORMAL: ejecucion automatica por voz en curso (None si no hay).
        self._normal_voice_flow: dict[str, Any] | None = None
        # MODO NORMAL: aclaraciones ESTRUCTURADAS del comando en curso (original + preguntas/respuestas).
        self._normal_clarification_state: dict[str, Any] | None = None
        # MODO NORMAL: asignacion PROVISIONAL de recursos del comando en curso. Solo se escribe en el mapa
        # (commit) cuando el programa se genero y verifico; cualquier fallo anterior la descarta (rollback).
        self._pending_map_transaction: dict[str, Any] | None = None
        # Alcance del comando Normal en curso (programa nuevo/ampliacion) y su copia de trabajo del mapa.
        self._normal_program_context: dict[str, Any] | None = None
        self._reprocessing_clarification = False
        self._pipeline_stage: str | None = None
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
        self.after(600, self._announce_open_text_batch)

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
        self.grid_columnconfigure(0, weight=6, minsize=500, uniform="main_panels")
        self.grid_columnconfigure(1, weight=6, minsize=460, uniform="main_panels")
        self.grid_columnconfigure(2, weight=8, minsize=540, uniform="main_panels")
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
                "visible_result_tabs": 4
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
                "visible_result_tabs": 3
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
                "visible_result_tabs": 3
            }

        self.grid_columnconfigure(0, weight=metrics["main_weights"][0], minsize=metrics["main_minsizes"][0], uniform="main_panels")
        self.grid_columnconfigure(1, weight=metrics["main_weights"][1], minsize=metrics["main_minsizes"][1], uniform="main_panels")
        self.grid_columnconfigure(2, weight=metrics["main_weights"][2], minsize=metrics["main_minsizes"][2], uniform="main_panels")
        self.left_panel.grid_rowconfigure(9, weight=0, minsize=0)
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

        self.platform_selector.configure(height=metrics["button_height"], font=self.body_font)
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
        for button in self.tall_command_buttons:
            button.configure(height=metrics["button_height"] + 18)

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

        self.platform_selector=ctk.CTkLabel(self.left_panel,textvariable=self.platform_var,font=self.body_font)
        self.platform_selector.grid(row=2,column=0,padx=18,pady=(0,8),sticky='w')
        self._preferences_window=ctk.CTkToplevel(self)
        self._preferences_window.title('Preferencias');self._preferences_window.geometry('560x340')
        self._preferences_window.grid_columnconfigure(0,weight=1);self._preferences_window.withdraw()
        self._preferences_window.protocol('WM_DELETE_WINDOW',self._preferences_window.withdraw)
        self.parser_label_widget = ctk.CTkLabel(self._preferences_window, text="Modo de parser", font=self.section_label_font)
        self.parser_label_widget.grid(row=3, column=0, padx=18, pady=(0, 8), sticky="w")

        self.parser_selector = ctk.CTkOptionMenu(
            self._preferences_window,
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

        llm_actions_frame = ctk.CTkFrame(self._preferences_window, fg_color="transparent")
        llm_actions_frame.grid(row=6, column=0, padx=18, pady=(0, 10), sticky="ew")
        ctk.CTkButton(self.left_panel,text='Preferencias',command=self.open_preferences,font=self.button_font).grid(row=6,column=0,padx=18,pady=(0,8),sticky='ew')
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
            self._preferences_window,
            text="Configurar TIA V18",
            command=self.open_tia_config_dialog,
            font=self.button_font
        )
        self.configure_tia_button.grid(row=7, column=0, padx=18,pady=8,sticky="ew")
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

        map_tia_frame.grid_columnconfigure(0, weight=1)
        map_tia_frame.grid_columnconfigure(1, weight=1)

        self.sync_map_button = ctk.CTkButton(map_tia_frame, text="Sincronizar con TIA", command=self.sync_plc_map_with_tia, font=self.button_font)
        self.sync_map_button.grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        self.import_map_button = ctk.CTkButton(map_tia_frame, text="Importar desde TIA", command=self.import_plc_map_from_tia, font=self.button_font)
        self.import_map_button.grid(row=0, column=1, padx=4, pady=2, sticky="ew")

        self.profile_selector_label = ctk.CTkLabel(map_library_frame, text="Contexto (Modo Normal)", font=self.section_label_font)


        self.profile_selector = ctk.CTkOptionMenu(
            map_library_frame,
            variable=self.active_profile_var,
            values=[GENERAL_PROFILE_LABEL],
            command=self.on_profile_selected,
            state="disabled",
            font=self.body_font,
            dropdown_font=self.body_font
        )

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

        self.table_label = ctk.CTkLabel(self.left_panel, text="Dispositivos y escalas: editar en el mapa completo", font=self.section_label_font)
        self.table_label.grid(row=10, column=0, padx=18, pady=(2, 6), sticky="w")

        self.io_tree_container = ctk.CTkFrame(self.left_panel, corner_radius=12)

        self.io_tree_container.grid_columnconfigure(0, weight=1)
        self.io_tree_container.grid_rowconfigure(0, weight=1)
        self.left_panel.grid_rowconfigure(11, weight=0, minsize=0)

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

        self.management_buttons=[]

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

        self.advanced_tools_frame = ctk.CTkFrame(self.center_panel, corner_radius=12)
        self.advanced_tools_frame.grid_columnconfigure((0,1),weight=1)
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

        voice_device_frame = ctk.CTkFrame(self.advanced_tools_frame, fg_color="transparent")
        voice_device_frame.grid(row=9, column=0, columnspan=2,padx=12, pady=(0, 8), sticky="ew")
        voice_device_frame.grid_columnconfigure(0, weight=1)

        self.voice_device_var = tk.StringVar(value="Microfono predeterminado del sistema")
        self.voice_device_selector = ctk.CTkOptionMenu(
            voice_device_frame,
            variable=self.voice_device_var,
            values=["Microfono predeterminado del sistema"],
            command=self._on_voice_device_selected,
            font=self.body_font,
            dropdown_font=self.body_font,
            dynamic_resizing=False
        )
        self.voice_device_selector.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.refresh_devices_button = ctk.CTkButton(
            voice_device_frame,
            text="↻ Actualizar",
            width=110,
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
        # Columnas iguales (uniform): los textos largos van en filas completas para no recortarse.
        for column_index in range(2):
            primary_controls_frame.grid_columnconfigure(column_index, weight=1, uniform="primary_controls")

        self.command_buttons: list[ctk.CTkButton] = []
        # Botones con texto en dos lineas: el layout responsivo les da mas altura.
        self.tall_command_buttons: list[ctk.CTkButton] = []

        self.listen_button = ctk.CTkButton(
            self.advanced_tools_frame, text="\U0001F399 Grabar comando", height=40,
            command=self.listen_command, font=self.button_font
        )
        self.listen_button.grid(row=8, column=0, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.listen_button)

        self.stop_voice_button = ctk.CTkButton(
            self.advanced_tools_frame,
            text="■ Detener y transcribir",
            height=40,
            fg_color="#B45309",
            hover_color="#92400E",
            command=self.stop_listening,
            font=self.button_font
        )
        self.stop_voice_button.grid(row=8, column=1, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.stop_voice_button)

        self.execute_command_button = ctk.CTkButton(
            primary_controls_frame,
            text="GENERAR Y COMPILAR",
            height=46,
            fg_color="#0F766E",
            hover_color="#115E59",
            command=self.execute_full_pipeline,
            font=ctk.CTkFont(size=15, weight="bold")
        )
        self.execute_command_button.grid(row=1, column=0, columnspan=2, padx=6, pady=(2, 6), sticky="ew")
        self.command_buttons.append(self.execute_command_button)
        self.tall_command_buttons.append(self.execute_command_button)
        # Mismo pipeline que EJECUTAR COMANDO; solo agrega la descarga encadenada si todo pasa.
        self.execute_and_load_button = ctk.CTkButton(
            primary_controls_frame, text="EJECUTAR Y CARGAR AL PLC\nGenerar, compilar y cargar", height=46,
            fg_color="#B45309", hover_color="#92400E", command=self.execute_and_load_to_plc,
            font=ctk.CTkFont(size=14, weight="bold"))
        self.execute_and_load_button.grid(row=2, column=0, columnspan=2, padx=6, pady=(0, 6), sticky="ew")
        self.command_buttons.append(self.execute_and_load_button)
        self.tall_command_buttons.append(self.execute_and_load_button)

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
        self.download_plc_button.grid(row=3, column=0, columnspan=2, padx=6, pady=(0, 6), sticky="ew")
        self.command_buttons.append(self.download_plc_button)

        # MODO NORMAL: flujo automatico por voz (captura -> ASR -> pipeline Normal -> compilar -> cargar).
        self.normal_voice_button = ctk.CTkButton(
            primary_controls_frame, text=NORMAL_VOICE_BUTTON_TEXT, height=50,
            fg_color="#1D4ED8", hover_color="#1E40AF", command=self.capture_and_execute_by_voice,
            font=ctk.CTkFont(size=14, weight="bold"))
        self.normal_voice_button.grid(row=4, column=0, columnspan=2, padx=6, pady=(4, 4), sticky="ew")
        self.normal_voice_cancel_button = ctk.CTkButton(
            primary_controls_frame, text="Cancelar captura", height=30, state="disabled",
            fg_color="#64748B", hover_color="#475569",
            command=self.cancel_normal_voice_capture, font=self.button_font)
        self.normal_voice_cancel_button.grid(row=5, column=0, columnspan=2, padx=6, pady=(0, 6), sticky="ew")
        self.normal_voice_cancel_button.grid_remove()
        voice_config = normal_voice.load_config(self.project_root)
        self.normal_voice_auto_download_var = tk.BooleanVar(value=voice_config["auto_download"])
        self.normal_voice_auto_download_check = ctk.CTkCheckBox(
            primary_controls_frame, text="Cargar al PLC automáticamente tras la voz",
            variable=self.normal_voice_auto_download_var, command=self._on_normal_voice_auto_download_changed,
            font=self.body_font)
        self.normal_voice_auto_download_check.grid(row=6, column=0, columnspan=2, padx=6, pady=(0, 2), sticky="w")
        self.normal_voice_target_var = tk.StringVar(value="")
        ctk.CTkLabel(primary_controls_frame, textvariable=self.normal_voice_target_var, anchor="w", justify="left",
                     wraplength=340, font=self.body_font).grid(
            row=7, column=0, columnspan=2, padx=6, sticky="ew")
        self.normal_voice_stage_var = tk.StringVar(value="")
        ctk.CTkLabel(primary_controls_frame, textvariable=self.normal_voice_stage_var, anchor="w", justify="left",
                     font=self.body_font).grid(row=8, column=0, columnspan=2, padx=6, pady=(0, 6), sticky="ew")
        self._refresh_normal_voice_target()

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

        manage_frame = ctk.CTkFrame(self.advanced_tools_frame, fg_color="transparent")
        manage_frame.grid(row=12, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")
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

        ctk.CTkButton(self.advanced_tools_frame,text='Prueba de I/O',command=self.open_runtime_io_test,font=self.button_font).grid(row=13,column=0,padx=6,pady=4,sticky='ew')
        ctk.CTkButton(self.advanced_tools_frame,text='Puesta en marcha PID',command=self.open_pid_commissioning,font=self.button_font).grid(row=13,column=1,padx=6,pady=4,sticky='ew')
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

        # Diseno v2: Modalidad (factor) + Fase (DEVELOPMENT/FORMAL). Sin selector Rules/LLM/Hybrid ni C1-C4.
        # Filas completas: las etiquetas de fase son largas y se recortaban en media columna.
        design_frame = ctk.CTkFrame(frame, fg_color="transparent")
        design_frame.grid(row=10, column=0, columnspan=2, padx=12, pady=0, sticky="ew")
        design_frame.grid_columnconfigure(0, weight=1)
        input_mode_label = ctk.CTkLabel(design_frame, text="Modalidad de entrada", font=self.body_font)
        input_mode_label.grid(row=0, column=0, pady=(0, 2), sticky="w")
        phase_label = ctk.CTkLabel(design_frame, text="Fase experimental", font=self.body_font)
        phase_label.grid(row=2, column=0, pady=(0, 2), sticky="w")
        self.experiment_input_mode_selector = ctk.CTkOptionMenu(
            design_frame,
            variable=self.experiment_input_mode_var,
            values=list(INPUT_MODE_LABELS.values()),
            command=self._on_experiment_input_mode_changed,
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.experiment_input_mode_selector.grid(row=1, column=0, pady=(0, 6), sticky="ew")
        self.experiment_phase_selector = ctk.CTkOptionMenu(
            design_frame,
            variable=self.experiment_phase_var,
            values=list(EXPERIMENT_PHASE_LABELS.values()),
            command=lambda _choice=None: self._refresh_experiment_status(),
            font=self.body_font,
            dropdown_font=self.body_font
        )
        self.experiment_phase_selector.grid(row=3, column=0, pady=(0, 6), sticky="ew")

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
            justify="left",
            wraplength=340,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.experiment_next_label_label.grid(row=16, column=0, columnspan=2, padx=12, pady=(0, 4), sticky="ew")

        self.experiment_status_label = ctk.CTkLabel(
            frame,
            textvariable=self.experiment_status_var,
            anchor="w",
            justify="left",
            wraplength=340,
            font=self.body_font
        )
        self.experiment_status_label.grid(row=17, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")

        self.experiment_stage_label = ctk.CTkLabel(
            frame,
            textvariable=self.experiment_stage_var,
            anchor="w",
            justify="left",
            wraplength=340,
            font=self.body_font
        )
        self.experiment_stage_label.grid(row=18, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")
        self._reset_experiment_stages()

        # Fase 4A-DEFERRED: el flujo principal GENERA el ensayo y se detiene (sin TIA/PLCSIM/Oracle);
        # la evaluacion se lanza despues, ensayo por ensayo, desde "Ensayos generados".
        self.start_trial_button = ctk.CTkButton(
            frame, text="GENERAR ENSAYO", height=42,
            fg_color="#0F766E", hover_color="#115E59",
            command=self.generate_experiment_trial, font=ctk.CTkFont(size=14, weight="bold")
        )
        self.oracle_status_label = ctk.CTkLabel(
            frame, textvariable=self.oracle_status_var, anchor="w", justify="left", wraplength=340, font=self.body_font
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
        # Panel de voz (depende de la modalidad): TEXT sin controles de audio.
        self.voice_panel = ctk.CTkFrame(frame, corner_radius=8)
        self.voice_panel.grid(row=22, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")
        self.voice_panel.grid_columnconfigure((0, 1), weight=1)
        self.voice_panel_var = tk.StringVar(value="")
        ctk.CTkLabel(self.voice_panel, textvariable=self.voice_panel_var, anchor="w", justify="left", font=self.body_font).grid(
            row=0, column=0, columnspan=2, padx=8, pady=(6, 4), sticky="ew")
        self.capture_voice_button = ctk.CTkButton(self.voice_panel, text="CAPTURAR VOZ", command=self.run_complete_trial, font=self.button_font)
        self.noise_profile_button = ctk.CTkButton(self.voice_panel, text="Perfil de ruido (DEV)...", command=self.select_dev_noise_profile, font=self.button_font)
        self.snr_button = ctk.CTkButton(self.voice_panel, text="SNR (DEV)...", command=self.select_dev_snr, font=self.button_font)

        self.start_trial_button.configure(text="EJECUTAR ENSAYO COMPLETO", command=self.run_complete_trial)
        self.start_trial_button.grid(row=23, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")
        # Fila 24: EJECUTAR LOTE TEXT (uno por uno, mismo flujo) y GENERAR SOLO, apilados.
        batch_actions = ctk.CTkFrame(frame, fg_color="transparent")
        batch_actions.grid(row=24, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew")
        batch_actions.grid_columnconfigure(0, weight=1)
        self.text_batch_button = ctk.CTkButton(batch_actions, text="EJECUTAR LOTE TEXT", height=36, fg_color="#1D4ED8",
                                               hover_color="#1E40AF", command=self.open_text_batch_dialog,
                                               font=ctk.CTkFont(size=13, weight="bold"))
        self.text_batch_button.grid(row=0, column=0, pady=(0, 6), sticky="ew")
        self.voice_clean_batch_button = ctk.CTkButton(
            batch_actions, text="EJECUTAR LOTE VOICE_CLEAN", height=36, fg_color="#7C3AED", hover_color="#6D28D9",
            command=lambda: self.open_text_batch_dialog(trial_model.INPUT_MODE_VOICE_CLEAN), font=ctk.CTkFont(size=13, weight="bold"))
        self.voice_clean_batch_button.grid(row=1, column=0, pady=(0, 6), sticky="ew")
        self.voice_noise_batch_button = ctk.CTkButton(
            batch_actions, text="EJECUTAR LOTE VOICE_NOISE", height=36, fg_color="#B45309", hover_color="#92400E",
            command=lambda: self.open_text_batch_dialog(trial_model.INPUT_MODE_VOICE_NOISE), font=ctk.CTkFont(size=13, weight="bold"))
        self.voice_noise_batch_button.grid(row=2, column=0, pady=(0, 6), sticky="ew")
        self.audio_corpus_button = ctk.CTkButton(batch_actions, text="FORMAL AUDIO CORPUS", command=self.open_audio_corpus_dialog,
                                                 font=self.button_font)
        self.audio_corpus_button.grid(row=3, column=0, pady=(0, 6), sticky="ew")
        self.generate_only_button = ctk.CTkButton(batch_actions, text="GENERAR SOLO (DEVELOPMENT/DEBUG)", command=self.generate_experiment_trial,
                                                  font=self.button_font)


        ctk.CTkLabel(frame, text="Ensayos generados", font=self.section_label_font).grid(
            row=25, column=0, columnspan=2, padx=12, pady=(4, 2), sticky="w")
        trials_container = ctk.CTkFrame(frame, fg_color="transparent")
        trials_container.grid(row=26, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew")
        trials_container.grid_columnconfigure(0, weight=1)
        self.generated_trials_tree = ttk.Treeview(
            trials_container, columns=("trial_id", "case", "variant", "generation", "evaluation", "verdict"),
            show="headings", height=6, selectmode="browse")
        for column, heading, width in (("trial_id", "ID", 170), ("case", "Caso", 50), ("variant", "Var", 40),
                                       ("generation", "Generacion", 95), ("evaluation", "Evaluacion", 150), ("verdict", "Veredicto", 120)):
            self.generated_trials_tree.heading(column, text=heading)
            self.generated_trials_tree.column(column, width=width, minwidth=width, anchor="w", stretch=False)
        self.generated_trials_tree.grid(row=0, column=0, sticky="ew")
        # Columnas mas anchas que el panel: desplazamiento horizontal en lugar de recortar Evaluacion/Veredicto.
        trials_xscroll = ttk.Scrollbar(trials_container, orient="horizontal", command=self.generated_trials_tree.xview)
        self.generated_trials_tree.configure(xscrollcommand=trials_xscroll.set)
        trials_xscroll.grid(row=1, column=0, sticky="ew")
        self._generated_trial_dirs: dict[str, str] = {}
        trial_actions = ctk.CTkFrame(frame, fg_color="transparent")
        trial_actions.grid(row=27, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew")
        trial_actions.grid_columnconfigure((0, 1), weight=1, uniform="trial_actions")
        self.view_trial_button = ctk.CTkButton(trial_actions, text="VER", command=self.view_generated_trial, font=self.button_font)
        self.view_trial_button.grid(row=0, column=0, padx=(0, 4), pady=(0, 6), sticky="ew")
        self.refresh_trials_button = ctk.CTkButton(trial_actions, text="ACTUALIZAR LISTA", command=self._refresh_generated_trials, font=self.button_font)
        self.refresh_trials_button.grid(row=0, column=1, padx=(4, 0), pady=(0, 6), sticky="ew")
        self.evaluate_saved_button = ctk.CTkButton(trial_actions, text="EVALUAR ENSAYO GUARDADO", command=self.evaluate_saved_trial, font=self.button_font)
        self.evaluate_saved_button.grid(row=1, column=0, columnspan=2, pady=(0, 6), sticky="ew")
        self.evaluate_next_button = ctk.CTkButton(trial_actions, text="EVALUAR SIGUIENTE PENDIENTE", command=self.evaluate_next_pending, font=self.button_font)
        self.evaluate_next_button.grid(row=2, column=0, columnspan=2, pady=(0, 6), sticky="ew")
        self.retry_evaluation_button = ctk.CTkButton(trial_actions, text="REINTENTAR EVALUACION", command=self.retry_trial_evaluation, font=self.button_font)
        self.retry_evaluation_button.grid(row=3, column=0, columnspan=2, sticky="ew")

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
        # Limpia columnas de una ventana anterior mas ancha; las visibles comparten el ancho por igual.
        for column_index in range(len(self.result_tab_names)):
            self.results_tab_strip.grid_columnconfigure(column_index, weight=0, uniform="")
        for column_index, tab_name in enumerate(visible_tabs):
            self.results_tab_strip.grid_columnconfigure(column_index, weight=1, uniform="result_tabs")
            is_active = tab_name == self.active_result_tab
            tab_button = ctk.CTkButton(
                self.results_tab_strip,
                text=self.result_tab_labels.get(tab_name, tab_name),
                width=60,
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
            name = str(device["name"])
            if len(name) > 30:  # nombres largos de Windows: se acortan para que quepan en el selector
                name = name[:29].rstrip() + "…"
            label = f"{name} (#{device['index']})"
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
        current_project = tia_projects.normal_project_path(self.project_root)
        initial_dir = str(Path(current_project).parent) if current_project else str(self.project_root)
        project_path = filedialog.askopenfilename(
            title="Seleccione el proyecto TIA Portal V18 del MODO NORMAL",
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

        try:
            # tia.normal_project (independiente del TIA MASTER experimental; nunca puede ser el MASTER).
            tia_projects.set_normal_project(self.project_root, project_path, plc_name.strip(), extra_tia_config={
                "tia_version": "V18",
                "attach_to_running": True,
                "with_user_interface": True,
                "create_plc_tags": True,
                "save_project_on_success": True,
                "compile_after_import": True
            })
        except tia_projects.TiaProjectGuardError as error:
            self._log(str(error))
            messagebox.showwarning("TIA Portal V18", str(error))
            return
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

    def _legacy_immediate_experiment_allowed(self) -> bool:
        """El pipeline inmediato de Experimentacion (compila en el proyecto Normal) solo con permiso explicito."""
        return bool(load_tia_config(self.project_root).get("legacy_immediate_experiment_pipeline", False))

    def _experiment_touches_normal_project(self) -> bool:
        return self.work_mode_var.get() == "Experimentacion" and not self._legacy_immediate_experiment_allowed()

    def validate_latest_package_in_tia(self) -> None:
        if getattr(self,'_pid_project_operation',None):
            messagebox.showwarning('PID','Espere a que termine la operación PID.');return
        if self._experiment_touches_normal_project():
            # Guard 6D: Experimentacion NUNCA modifica el proyecto Normal. Los ensayos se evaluan sobre
            # una copia del TIA MASTER (EVALUAR ENSAYO GUARDADO).
            message = ("EXPERIMENT_MODE_NEVER_MODIFIES_NORMAL_PROJECT: en Experimentacion use GENERAR ENSAYO y "
                       "EVALUAR ENSAYO GUARDADO (copia del TIA MASTER).")
            self._log(message)
            if self.active_trial:
                self._cancel_active_trial(message)
            messagebox.showwarning("TIA Openness", message)
            return
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
        self._compile_target_identity=self._current_target_identity()
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
            self._fail_normal_voice("Compilacion", str(payload))
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
            # COMPILE_FAILURE solo si TIA siguio operativo y el compilador rechazo el programa; una
            # caida de TIA/Openness (p.ej. NonRecoverableException) es INFRASTRUCTURE_ERROR.
            compile_class = tia_classification.classify_tia_compile(report)
            compile_infrastructure = compile_class["category"] == tia_classification.INFRASTRUCTURE_ERROR
            self._update_new_trial({
                "compile": {
                    "status": report.get("status"),
                    "error_count": report.get("error_count"),
                    "warning_count": report.get("warning_count"),
                    "result_path": result_path,
                    "tag_reconciliation": report.get("tag_reconciliation"),
                    "classification": compile_class
                },
                "stages": {"compile_success": None if compile_infrastructure else passed},
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
                self._finalize_new_trial(
                    trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR if compile_infrastructure else trial_model.FINAL_STATUS_FAIL,
                    [f"Compilacion TIA: {report.get('status')} ({compile_class['reason']})"]
                )
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
            self._compiled_target_identity=getattr(self,"_compile_target_identity",None)
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
            tia_compile_summary(report),
            passed
        )
        self._log(f"TIA Openness finalizo con estado {report.get('status')}.")
        if chain_experiment_download:
            self._start_download(Path(report_package_dir), DOWNLOAD_PURPOSE_EXPERIMENT)
            return
        if self._normal_voice_flow is not None and self.work_mode_var.get() == "Normal":
            if self._continue_normal_voice_after_compile(passed, report_package_dir, report):
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
        if getattr(self,'_pid_project_operation',None):
            messagebox.showwarning('PID','Espere a que termine la operación PID.');return
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
            f"Dirección: {target.get('target_address') or 'ruta heredada'} · PG/PC: {target.get('pc_interface') or 'automática'} · Puerto: {target.get('target_interface') or 'único'}\n"
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
        captured_target=plc_targets.load_normal_target(self.project_root) if purpose==DOWNLOAD_PURPOSE_NORMAL else None
        if purpose==DOWNLOAD_PURPOSE_NORMAL:
            current=plc_targets.target_identity(captured_target)
            expected=getattr(self,'_compiled_target_identity',None)
            flow_expected=(self._normal_voice_flow or {}).get('target_identity')
            if (expected is not None and expected!=current) or (flow_expected is not None and flow_expected!=current):
                self._invalidate_download_readiness()
                if self._normal_voice_flow:self._fail_normal_voice('Descarga','El destino cambió; vuelva a compilar.')
                messagebox.showwarning('Destino PLC','El destino cambió desde la compilación; vuelva a compilar.');return
        if getattr(self,'_pid_project_operation',None):
            messagebox.showwarning('PID','Espere a que termine la operación PID.');return
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
                result=download_program_to_plc(package_dir,self.project_root,purpose,expected_target=captured_target) if captured_target is not None else download_program_to_plc(package_dir,self.project_root,purpose)
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
        if purpose == DOWNLOAD_PURPOSE_NORMAL:
            status = payload.get("status") if isinstance(payload, dict) else payload
            self._log(normal_interaction.trace("NORMAL_DOWNLOAD", outcome=outcome, status=status))

        if outcome == "error":
            self._set_status("Error")
            self._log(f"[TIA DOWNLOAD] FAILED (excepcion): {payload}")
            if purpose == DOWNLOAD_PURPOSE_EXPERIMENT:
                self._complete_experiment_download(
                    {"status": "DOWNLOAD_EXCEPTION", "download_success": False, "start_module_success": False, "errors": [str(payload)]}
                )
                return
            self._fail_normal_voice("Descarga", str(payload))
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

        if self._normal_voice_flow is not None:
            self._set_normal_voice_stage("Descarga", "ok" if success else "fail")
            if success:
                self._finish_normal_voice(normal_voice.FINAL_LOADED)
            else:
                self._fail_normal_voice("Descarga", status)
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
            "stages": {"runtime_connection_success": connected},
            "timing": {"runtime_ms": runtime_report.get("duration_ms")}
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
        kind = (self.active_trial or {}).get("trial_kind") or "-"
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

        self.io_test_button.grid(row=6,column=0,padx=12,pady=(0,6),sticky='ew')

        self.select_target_button=ctk.CTkButton(panel,text='SELECCIONAR PLC',command=self.select_normal_plc_target,font=self.button_font)
        self.select_target_button.grid(row=7,column=0,padx=12,pady=(0,10),sticky='ew')
        self.pid_commissioning_button=ctk.CTkButton(panel,text='Puesta en marcha PID',command=self.open_pid_commissioning,font=self.button_font)
        self.pid_commissioning_button.grid(row=8,column=0,padx=12,pady=(0,10),sticky='ew')
        self.pid_commissioning_button.grid_remove()
        self._render_configured_target()

    def _current_target_identity(self) -> str:
        return plc_targets.target_identity(plc_targets.load_normal_target(self.project_root))

    def _normal_runtime_config(self) -> dict:
        config=plcsim_runtime.load_runtime_config(load_tia_config(self.project_root))
        target=plc_targets.load_normal_target(self.project_root)
        config.update({key:target[key] for key in ('instance_name','instance_id') if key in target})
        if 'instance_id' not in target:config.pop('instance_id',None)
        return config

    def _current_runtime_identity(self) -> str:
        if self.work_mode_var.get()=='Normal':return self._current_target_identity()
        config=load_tia_config(self.project_root);runtime=plcsim_runtime.load_runtime_config(config)
        target=resolve_download_target(config,DOWNLOAD_PURPOSE_EXPERIMENT)
        return plc_targets.target_identity({**target,**{key:runtime[key] for key in ('instance_name','instance_id') if key in runtime}})

    def _target_operation_busy(self) -> bool:
        return bool(self._tia_busy() or self._voice_worker_active or self._normal_voice_flow
                    or getattr(self,'_pipeline_running',False) or getattr(self,'_map_sync_worker_active',False)
                    or self.speech_recognizer.is_recording() or self._io_test_window is not None
                    or (getattr(self,'_pid_commissioning_window',None) is not None
                        and self._pid_commissioning_window.winfo_exists()))

    def select_normal_plc_target(self) -> None:
        if self.work_mode_var.get()!='Normal' or self._target_operation_busy():
            messagebox.showwarning('Destino PLC','Use Modo Normal y espere a que terminen las operaciones de voz, TIA, I/O o PID.');return
        if getattr(self,'_target_selector_open',False):return
        self._target_selector_open=True
        try:
            revision=plc_targets.read_target_revision(self.project_root)
            dialog=PlcTargetDialog(self,plc_targets.load_normal_target(self.project_root),revision)
            self.wait_window(dialog)
            if dialog.result is None:return
            if self._target_operation_busy():raise ValueError('Hay una operación en curso; no se cambió el destino.')
            plc_targets.save_normal_target(self.project_root,dialog.result,revision)
            self._invalidate_download_readiness()
            self._last_runtime_report=None;self._io_program_context=None
            self.plc_runtime_var.set('Estado: NO VERIFICADO');self.plc_cpu_var.set('CPU: sin verificar');self.plc_network_var.set('Red: sin verificar')
            self._render_configured_target();self._refresh_normal_voice_target()
        except Exception as error:messagebox.showerror('Destino PLC',str(error))
        finally:self._target_selector_open=False

    def refresh_selected_target_status(self) -> None:
        self.refresh_plc_runtime_status()

    def _render_configured_target(self) -> None:
        """Configuration is separate from verified runtime state."""
        try:
            target=plc_targets.load_normal_target(self.project_root)
            text=(f"Configurado: {target.get('target_name') or '-'} · {target.get('target_address') or 'ruta heredada'} · {target.get('target_interface') or '?'}"
                  +f"\nProyecto: {Path(target.get('project_path') or '-').name} · CPU esperada: {target.get('plc_name') or 'única en plantilla'}")
        except Exception as error:text=f'Destino no disponible: {error}'
        self.plc_config_var.set(text)
        package=(self._io_program_context or {}).get('package_dir')
        if package and (Path(package)/'pid_process_bindings.json').is_file() and self.work_mode_var.get()=='Normal':
            self.pid_commissioning_button.grid()
        else:self.pid_commissioning_button.grid_remove()

    def refresh_plc_runtime_status(self) -> None:
        self._start_runtime_refresh("manual")

    def _start_runtime_refresh(self, reason: str, package_dir: Path | None = None, on_done: Any = None) -> None:
        """Lectura no bloqueante (hilo 'plcsim-runtime'); nunca hay polling continuo."""
        normal=self.work_mode_var.get()=='Normal'
        target=plc_targets.load_normal_target(self.project_root) if normal else resolve_download_target(load_tia_config(self.project_root),DOWNLOAD_PURPOSE_EXPERIMENT)
        if target['target_type']!='PLCSIM_ADVANCED':
            self._last_runtime_report=None
            self.plc_runtime_var.set('PLC físico: configurado; conexión sin verificar')
            self.plc_cpu_var.set('CPU: identidad y estado sin verificar')
            self.plc_network_var.set('Dirección configurada: '+str(target.get('target_address') or '-'))
            if on_done:on_done({'connected':False,'status':'PHYSICAL_NOT_VERIFIED','cpu_state':None})
            return
        self._runtime_callbacks.append((package_dir, on_done))
        if self._runtime_worker_active:
            return
        self._runtime_query_identity=self._current_runtime_identity()
        self._runtime_worker_active = True
        self.refresh_runtime_button.configure(state="disabled")
        self.plc_runtime_var.set("Runtime: consultando...")
        self._log(f"[PLCSIM RUNTIME] Consultando estado ({reason})")

        def _worker() -> None:
            try:
                report=get_plcsim_runtime_status(self.project_root,target=target) if normal and target.get('instance_id') is not None else get_plcsim_runtime_status(self.project_root)
                self._runtime_worker_queue.put(('success',report))
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
        if getattr(self,'_runtime_query_identity',None)!=self._current_runtime_identity():
            self._runtime_callbacks=[]
            self._log('[PLC] Resultado de un destino anterior descartado.')
            return
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

    def open_pid_commissioning(self) -> None:
        from pid_commissioning import PidCommissioningSession,PidOperationJob
        from pid_commissioning_view import PidCommissioningPanel
        from pid_plant_test import PlantTestJob
        from pid_parameter_store import inspect_parameter_state,load_saved_parameters,save_verified_parameters
        if self._tia_busy() or getattr(self,'_map_sync_worker_active',False):
            messagebox.showwarning('PID','Espere a que termine la operación en curso.');return
        previous=getattr(self,'_pid_commissioning_window',None)
        if previous is not None and previous.winfo_exists():
            previous.focus();return
        package=(self._io_program_context or {}).get('package_dir')
        if self.work_mode_var.get()!='Normal' or not package or not (Path(package)/'pid_process_bindings.json').is_file():
            messagebox.showinfo('PID','Primero genere, compile y cargue un programa PID nativo en modo Normal.');return
        package=Path(package)
        bindings=load_json_file(package/'pid_process_bindings.json')
        download=load_json_file(package/'tia_download_report.json')
        compiled=load_json_file(package/'tia_compile_report.json')
        verified=download.get('download_success',download.get('success')) is True and compiled.get('status')=='TIA_COMPILATION_PASSED'
        target=self._io_test_target_type()
        context={'mode':bindings.get('mode'),'target_type':target,'connected':bool((self._last_runtime_report or {}).get('connected')),
            'cpu_state':(self._last_runtime_report or {}).get('cpu_state'),'program_verified':verified,'tuning_authorized':False}
        io=plcsim_runtime_io.RuntimeIOSession({'source':'native_pid','signals':{},'inventory':{}},target,self._last_runtime_report,self.project_root,runtime_config=self._normal_runtime_config(),kind='native_pid')
        session=PidCommissioningSession(bindings,io,context)
        window=ctk.CTkToplevel(self);window.title('Puesta en marcha PID');window.geometry('740x960')
        self._pid_commissioning_window=window
        results=queue.Queue();busy=False;closing=False
        job=PlantTestJob();operation=PidOperationJob()
        can_test=(bindings.get('schema_version')==2 and target=='PLCSIM_ADVANCED' and verified
                  and context['connected'] and context['cpu_state']=='RUN')
        def submit(name=None,value=None,authorize=False):
            nonlocal busy
            if busy or closing or operation.active or self._tia_busy(allow_pid_model=True) or getattr(self,'_map_sync_worker_active',False):return
            busy=True;context['tuning_authorized']=authorize
            self._pid_project_operation='READING' if name is None else 'WRITING'
            def worker():
                try:
                    values=session.read() if name is None else session.write(name,value)
                    state=inspect_parameter_state(package,{**values,'build_signature':bindings['build_signature']},load_saved_parameters(self.project_root,package))
                    results.put(('ok',{'values':values,'state':state}))
                except Exception as error:results.put(('error',str(error)))
            threading.Thread(target=worker,daemon=True).start()
        def start_operation(kind,work):
            if closing or busy or job.active or operation.active or not can_test or self._tia_busy() or getattr(self,'_map_sync_worker_active',False):return
            if operation.start(kind,work):
                self._pid_project_operation=kind
                panel.set_operation_state(kind)
                panel.show_test_status({'status':'Verificando ajustes guardados en TIA...' if kind=='SAVING' else 'Evaluación aislada en curso; sustituye el programa de PLCSIM.'})
        def save_parameters():
            start_operation('SAVING',lambda cancel:save_verified_parameters(self.project_root,package,session,cancel=cancel,verification_only=True))
        def evaluate_parameters():
            from trial_experiments import native_pid_protocol as protocol_service,deferred_evaluator
            protocol=load_json_file(self.project_root/'config/native_pid_evaluation_protocol.json')
            if protocol['tuning_policy']=='REQUIRE_PRETUNE' and not panel.tuning_var.get():
                panel.show_test_status({'status':'Autorice la sintonización para ejecutar el protocolo de tanque 50/40/60 %.'});return
            protocol['tuning_authorized']=panel.tuning_var.get()
            def work(cancel):
                profile=load_json_file(self.project_root/'config/pid_tank_test_profile.json')
                run=protocol_service.create_native_validation_run(self.project_root,package,protocol,profile,
                    self.project_root/'runtime/native_pid_evaluations')
                result=deferred_evaluator.run_frozen_native_development(self.project_root,run,cancel=cancel)
                return {**result,'evidence':str(run)}
            start_operation('EVALUATING',work)
        def start_test():
            if closing or busy or operation.active or not can_test or self._tia_busy() or getattr(self,'_map_sync_worker_active',False):return
            try:
                profile=load_json_file(self.project_root/'config/pid_tank_test_profile.json')
                test_target={'target_type':target,'instance_name':(self._last_runtime_report or {}).get('instance_name'),**({'instance_id':self._last_runtime_report['instance_id']} if (self._last_runtime_report or {}).get('instance_id') is not None else {})}
                if not test_target['instance_name']:raise ValueError('Instancia PLCSIM no identificada.')
                if job.start(package,test_target,profile,self.project_root/'runtime/pid_plant_tests'):
                    self._pid_project_operation='MODEL'
                    panel.show_test_status({'status':'Modelo externo iniciado; rearme y use Marcha para iniciar el PID.'})
                    panel.test_button.configure(state='disabled')
            except Exception as error:panel.show_test_status({'status':'FAILED','errors':[str(error)]})
        def cancel_test():
            job.cancel();operation.cancel()
            panel.show_test_status({'status':'Deteniendo modelo y verificando restauracion...'})
        panel=PidCommissioningPanel(window,bindings,submit,lambda:submit(),
            on_test=start_test if can_test else None,on_cancel_test=cancel_test if can_test else None,
            on_save=save_parameters if can_test else None,on_evaluate=evaluate_parameters if can_test else None)
        panel.pack(fill='both',expand=True,padx=12,pady=12)
        def destroy_panel():
            self._pid_commissioning_window=None
            self._pid_close_request=None
            window.destroy()
        def keep_cleanup_failure_visible(reason):
            nonlocal closing
            if closing:self._pid_shutdown_error=reason
            closing=False
        def close():
            nonlocal closing
            closing=True;job.cancel();operation.cancel()
            if job.active or busy or operation.active:
                panel.show_test_status({'status':'Cerrando; esperando parada y restauracion verificadas...'})
            else:
                destroy_panel()
        self._pid_close_request=close
        window.protocol('WM_DELETE_WINDOW',close)
        self.bind('<Destroy>',lambda event:(job.cancel(),operation.cancel()) if event.widget is self else None,add='+')
        def poll():
            nonlocal busy,closing
            if not window.winfo_exists():return
            try:
                outcome,value=results.get_nowait();busy=False
                self._pid_project_operation='MODEL' if job.active else None
                if outcome=='ok':
                    panel.show_values(value['values']);panel.show_parameter_state(value['state'])
                else:
                    panel.status_var.set(value)
                    panel.invalidate_runtime()
                    panel.show_parameter_state({'state':'UNVERIFIED','reason':value})
            except queue.Empty:pass
            completed=operation.poll()
            if completed:
                kind,outcome,value=completed
                self._pid_project_operation=None;panel.set_operation_state(None)
                if outcome=='error':
                    panel.show_test_status({'status':'FAILED','errors':[value]})
                    panel.show_parameter_state({'state':'UNVERIFIED','reason':value})
                    keep_cleanup_failure_visible(value)
                elif kind=='SAVING':
                    if value['status']=='SAVED_VERIFIED':self._invalidate_download_readiness()
                    panel.show_parameter_state({'state':value['status'],'reason':'Guardado verificado en TIA. Regenere y compile antes de descargar.' if value['status']=='SAVED_VERIFIED' else value.get('reason','Operación cancelada; ajustes sin verificar.')})
                    panel.show_test_status({'status':value['status'],'evidence':value.get('record_path')})
                else:
                    panel.show_test_status(value)
                    panel.show_parameter_state({'state':'UNVERIFIED','reason':'La evaluación usó una copia experimental. Lea de nuevo la CPU.'})
                    if value.get('cleanup_verified') is not True:keep_cleanup_failure_visible('La evaluación no verificó la parada y restauración.')
            report=job.poll()
            if report:
                self._pid_project_operation=None
                panel.show_test_status(report)
                if report.get('cleanup',{}).get('cleanup_verified') is not True:
                    keep_cleanup_failure_visible('El modelo no verificó la parada y restauración.')
                    panel.test_button.configure(state='disabled')
                elif can_test:panel.test_button.configure(state='normal')
            if closing and not job.active and not busy and not operation.active:
                destroy_panel();return
            window.after(100,poll)
        window.after(100,poll)

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
        instance=(self._normal_runtime_config() if (self._io_program_context or {}).get('purpose',DOWNLOAD_PURPOSE_NORMAL)==DOWNLOAD_PURPOSE_NORMAL else plcsim_runtime.load_runtime_config(load_tia_config(self.project_root)))['instance_name']
        allowed, reason = plcsim_runtime_io.io_test_availability(self._io_test_target_type(), runtime_report, instance, program, allow_manual_stop=True)
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
        if self.work_mode_var.get()=='Normal' and plc_targets.load_normal_target(self.project_root)['target_type']!='PLCSIM_ADVANCED':
            self.plc_runtime_var.set('PLC físico: conexión sin verificar');self.plc_cpu_var.set('CPU: sin verificar');return
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
        snapshot["validation_text"] = tia_compile_summary(report)
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
        extras_by_key = getattr(self, "io_variable_extras", {})
        for entry in treeview_rows(self.io_tree, IO_TREE_COLUMNS):
            advanced = self.io_variable_metadata.get(entry.get("name", ""), {})
            normalized = normalize_variable_entry({**entry, **advanced})
            # Campos fuera de la tabla (configuracion fisica del canal: senal, sensor, rango...; binding del programa):
            # se conservan por direccion fisica, nunca se pierden al guardar la tabla.
            extras = extras_by_key.get(self._variable_key(normalized), {})
            merged.append({**normalized, **{key: value for key, value in extras.items() if key not in normalized}})
        return merged

    @staticmethod
    def _variable_key(entry: dict[str, Any]) -> str:
        return str(entry.get("location") or "") or f"name:{entry.get('name', '')}"

    def _mark_manual_binding(self, entry: dict[str, Any], state: str, *, update_configuration: bool = False) -> None:
        """Cambio hecho por el USUARIO en el editor: ASSIGNED queda MANUAL (se conserva entre programas); FREE sin binding."""
        if not hasattr(self, "io_variable_extras"):
            self.io_variable_extras = {}
        extras = self.io_variable_extras.setdefault(self._variable_key(entry), {})
        if update_configuration:
            extras.pop("analog_config", None)
            extras.update(copy.deepcopy({key: value for key, value in entry.items()
                                        if key not in IO_TREE_COLUMNS and key not in ADVANCED_VARIABLE_DEFAULTS}))
        for field in program_bindings.BINDING_FIELDS:
            extras.pop(field, None)
        if state == "ASSIGNED":
            extras["assignment_source"] = program_bindings.SOURCE_MANUAL

    def _load_active_map_metadata_shadow(self) -> None:
        """Populate the advanced-fields shadow dict from the raw active map file."""
        self.io_variable_metadata = {}
        self.io_variable_extras = {}
        try:
            raw_payload = load_json_file(self.io_map_path)
        except (FileNotFoundError, ValueError):
            return
        for entry in raw_payload.get("variables", []):
            name = entry.get("name")
            if not name:
                continue
            extras = {key: value for key, value in entry.items()
                      if key not in IO_TREE_COLUMNS and key not in ADVANCED_VARIABLE_DEFAULTS}
            if extras:
                self.io_variable_extras[self._variable_key(entry)] = extras
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

    def _benchmark_version(self) -> Any:
        """Version del benchmark vigente (la del ensayo activo si existe; si no, la del catalogo)."""
        version = (self.active_trial or {}).get("benchmark_version")
        if version is not None:
            return version
        try:
            return benchmark_catalog.load_catalog(self.project_root).get("benchmark_version")
        except (OSError, ValueError):
            return None

    def _load_runtime_configuration(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        trial_info = self._trial_io()
        if trial_info is not None:
            # Ensayo experimental: el working map del ensayo (inventario fisico completo, mismo
            # IOAllocator que Modo Normal). El filtro allowed_variables del perfil es la politica
            # legacy de "mapa congelado" y no se aplica: impedia usar canales FREE.
            io_map = trial_io_map.load_working_map(Path(trial_info["io_map"]["working_map_path"]))
        else:
            io_map = load_json_file(self.io_map_path)
            # Benchmark v2: allowed_variables es metadata historica, nunca una whitelist. El filtro
            # por perfil solo sobrevive, aislado, para el benchmark legacy v1.
            if resource_policy.legacy_profile_whitelist_applies(self._benchmark_version()):
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
        others = [entry for entry in self._collect_io_variables()
                  if variable_data is None or entry["name"] != variable_data.get("name")]
        dialog = VariableEditorDialog(self, title, variable_data, other_variables=others)
        self.wait_window(dialog)
        return dialog.result

    def open_full_io_map_window(self) -> None:
        """[ABRIR MAPA I/O COMPLETO] (seccion 7): ventana independiente con TODOS los canales del
        mapa activo, no solo los que caben en la tabla del panel izquierdo."""
        FullIOMapWindow(self)

    def open_map_file(self) -> None:
        if block_map_config_message(self.active_trial,self.active_profile_id) or self._target_operation_busy():
            messagebox.showwarning('Mapa PLC','Termine la operación o el ensayo antes de cambiar el mapa.');return
        if not self._confirm_discard_unsaved_map_changes():return
        selected=filedialog.askopenfilename(title='Importar mapa PLC',filetypes=[('Mapa JSON','*.json')],parent=self)
        if not selected:return
        try:
            payload=load_plc_map(Path(selected))
            validation=validate_plc_variable_map(payload)
            if validation['errors']:raise ValueError('\n'.join(validation['errors'][:8]))
            metadata=payload.get('metadata') or {}
            path=create_plc_map(self.project_root,name=metadata.get('name') or Path(selected).stem,
                                description=metadata.get('description',''),variables=copy.deepcopy(payload['variables']))
            copied=load_plc_map(path)
            copied_metadata={**metadata,**copied['metadata']}
            copied={**payload,**copied,'metadata':copied_metadata}
            path.write_text(json.dumps(copied,ensure_ascii=False,indent=2),encoding='utf-8')
            save_active_map_id(self.project_root,path.stem)
        except (OSError,ValueError,TypeError,KeyError) as error:
            messagebox.showerror('Mapa PLC',str(error));return
        self.io_map_path=path;self.active_map_dirty=False
        self._invalidate_download_readiness();self.open_io_map();self._refresh_map_selector_values()

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
        self._mark_manual_binding(result, result.get("state", "ASSIGNED"), update_configuration=True)
        self._mark_active_map_dirty()
        self._log(f"Variable agregada en tabla: {result['name']}.")

    def edit_variable(self) -> None:
        item_id = self._selected_tree_item()
        selected_data = self._selected_tree_data()
        if item_id is None or selected_data is None:
            messagebox.showwarning("Editar variable", "Seleccione una variable para editar.")
            return

        old_key = self._variable_key(selected_data)
        merged_data = {**selected_data, **self.io_variable_metadata.get(selected_data["name"], {}),
                       **copy.deepcopy(self.io_variable_extras.get(old_key, {}))}
        result = self._run_variable_dialog("Editar variable", merged_data)
        if result is None:
            return

        self.io_tree.item(item_id, values=[result[column] for column in IO_TREE_COLUMNS])
        if selected_data["name"] != result["name"]:
            self.io_variable_metadata.pop(selected_data["name"], None)
        self.io_variable_metadata[result["name"]] = {field: result[field] for field in ADVANCED_VARIABLE_DEFAULTS}
        new_key = self._variable_key(result)
        if new_key != old_key:
            self.io_variable_extras[new_key] = self.io_variable_extras.pop(old_key, {})
        self._mark_manual_binding(result, result.get("state", "ASSIGNED"), update_configuration=True)
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
        self._mark_manual_binding(selected_data, new_state)

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
        if self._map_sync_worker_active or self._tia_busy():
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
        if self._map_sync_worker_active or self._tia_busy():
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
            for window in list(getattr(self,'_full_map_windows',())):
                if window.winfo_exists():window._reload()
            self._log(
                f"Importacion desde TIA completada: {result['new_count']} nuevas, "
                f"{result['refreshed_count']} actualizadas. Revise y guarde el mapa."
            )
            messagebox.showinfo(
                "Importar desde TIA",
                f"{result['new_count']} variables nuevas y {result['refreshed_count']} actualizadas.\n\n"
                "Revise el mapa completo y pulse Guardar para persistir los cambios."
            )

    # ------------------------------------------------------------------------------------------
    # MODO NORMAL: CAPTURAR Y EJECUTAR POR VOZ (producto; no es Experimentacion)
    # ------------------------------------------------------------------------------------------

    def _refresh_normal_voice_target(self) -> None:
        try:
            target = resolve_download_target(load_tia_config(self.project_root), DOWNLOAD_PURPOSE_NORMAL)
            if self._normal_voice_flow is not None:self._normal_voice_flow["target_identity"]=self._current_target_identity()
            physical = target["target_type"] != TARGET_TYPE_PLCSIM
            self.normal_voice_target_var.set(
                f"Destino Normal: {target.get('target_name', '')} ({target['target_type']})"
                + ("  ⚠ PLC FISICO" if physical else "")
                + f" · Proyecto: {Path(tia_projects.normal_project_path(self.project_root) or '-').name}")
        except Exception as error:  # pragma: no cover - feedback de GUI
            self.normal_voice_target_var.set(f"Destino Normal: no disponible ({error})")

    def _on_normal_voice_auto_download_changed(self) -> None:
        normal_voice.save_config(self.project_root, auto_download=bool(self.normal_voice_auto_download_var.get()))

    def _set_normal_voice_stage(self, stage: str, state: str) -> None:
        if self._normal_voice_flow is None:
            return
        self._normal_voice_flow["stages"][stage] = state
        self.normal_voice_stage_var.set(normal_voice.stage_text(self._normal_voice_flow))

    def _fail_normal_voice(self, stage: str, detail: str) -> None:
        if self._normal_voice_flow is None:
            return
        self._set_normal_voice_stage(stage, "fail")
        self._normal_voice_flow["failed_stage"] = stage
        self._finish_normal_voice(f"FALLO en {stage}: {detail} — no se descargo nada.")

    def _finish_normal_voice(self, final: str) -> None:
        if self._normal_voice_flow is None:
            return
        self._normal_voice_flow["final"] = final
        self._normal_voice_flow["active"] = False
        self.normal_voice_stage_var.set(normal_voice.stage_text(self._normal_voice_flow))
        self._log(f"[NORMAL] {final}")
        self.last_normal_voice_result = dict(self._normal_voice_flow)
        self._normal_voice_flow = None
        self.normal_voice_button.configure(text=NORMAL_VOICE_BUTTON_TEXT)
        self.normal_voice_cancel_button.configure(state="disabled")
        self.normal_voice_cancel_button.grid_remove()

    def capture_and_execute_by_voice(self) -> None:
        """1er clic: empieza a grabar. 2o clic (DETENER Y EJECUTAR): transcribe y ejecuta todo sin mas clics."""
        if self.work_mode_var.get() != "Normal":
            messagebox.showwarning("Voz", "CAPTURAR Y EJECUTAR POR VOZ pertenece al Modo Normal.")
            return
        if self.speech_recognizer.is_recording() and self._normal_voice_flow is not None:
            self._set_normal_voice_stage("Captura", "ok")
            self._set_normal_voice_stage("Transcripcion", "running")
            self.normal_voice_cancel_button.configure(state="disabled")
            self.normal_voice_cancel_button.grid_remove()
            self.stop_listening()
            return
        if self._tia_worker_active or self._download_worker_active or self._voice_worker_active:
            messagebox.showwarning("Voz", "Espere a que termine la operacion en curso.")
            return
        self._normal_voice_flow = normal_voice.new_flow(self.project_root)
        self._refresh_normal_voice_target()
        self._set_normal_voice_stage("Captura", "running")
        self.listen_command()
        if not self.speech_recognizer.is_recording():
            self._fail_normal_voice("Captura", "no se pudo iniciar la grabacion")
            return
        self.normal_voice_button.configure(text="■ DETENER Y EJECUTAR")
        self.normal_voice_cancel_button.configure(state="normal")
        self.normal_voice_cancel_button.grid()

    def cancel_normal_voice_capture(self) -> None:
        """Cancelar ANTES de enviar: se descarta la grabacion y no se ejecuta nada."""
        if self._normal_voice_flow is None:
            return
        if self.speech_recognizer.is_recording():
            self.speech_recognizer.cancel_recording()
            self._reset_voice_level_indicator()
        self._set_normal_voice_stage("Captura", "skipped")
        self._finish_normal_voice("Captura cancelada por el usuario: no se ejecuto nada.")
        self._set_status("Listo")
        self._refresh_voice_button_states()

    def _run_normal_voice_pipeline(self) -> None:
        """Transcripcion lista: ejecuta el pipeline Normal EXISTENTE (EJECUTAR COMANDO) sin otro clic."""
        flow = self._normal_voice_flow
        if flow is None:
            return
        if not flow["auto_execute"]:
            self._finish_normal_voice("Transcripcion lista (ejecucion automatica desactivada).")
            return
        for stage in ("Semantica", "I/O"):
            self._set_normal_voice_stage(stage, "running")
        started = self.execute_full_pipeline()
        flow = self._normal_voice_flow
        if flow is None:
            return
        if not started:
            reached = self._pipeline_stage
            if reached in ("precheck", "semantic"):
                failed = "I/O" if self._last_semantic_failure_is_io() else "Semantica"
                if flow.get("clarification_pending"):
                    detail = "aclaracion sin responder"
                else:
                    detail = "interpretacion/validacion no superada"
                if reached == "precheck":
                    failed, detail = "Semantica", "verificacion previa (proyecto TIA Normal/Openness) no superada"
                self._fail_normal_voice(failed, detail)
            else:
                self._set_normal_voice_stage("Semantica", "ok")
                self._set_normal_voice_stage("I/O", "ok")
                failed = "Verificacion" if reached == "verification" else "Generacion"
                if failed == "Verificacion":
                    self._set_normal_voice_stage("Generacion", "ok")
                self._fail_normal_voice(failed, "el programa no supero la etapa")
            return
        for stage in ("Semantica", "I/O", "Generacion", "Verificacion"):
            self._set_normal_voice_stage(stage, "ok")
        self._set_normal_voice_stage("Compilacion", "running")

    def _last_semantic_failure_is_io(self) -> bool:
        validation = ((self.pending_semantic_output or {}).get("semantic_validation") or {})
        return bool(validation.get("unauthorized_tags"))

    def _continue_normal_voice_after_compile(self, passed: bool, package_dir: str, report: dict[str, Any]) -> bool:
        """Compilacion terminada en una ejecucion por voz: descarga automatica solo si todo paso."""
        flow = self._normal_voice_flow
        for stage in ("Semantica", "I/O", "Generacion", "Verificacion"):
            if flow["stages"][stage] != "fail":
                self._set_normal_voice_stage(stage, "ok")
        self._set_normal_voice_stage("Compilacion", "ok" if passed else "fail")
        if not passed:
            self._fail_normal_voice("Compilacion", str(report.get("status")))
            return False
        allowed, reason = normal_voice.download_allowed(flow, passed)
        if not allowed or not package_dir:
            self._set_normal_voice_stage("Descarga", "skipped")
            self._finish_normal_voice(f"PROGRAMA COMPILADO — sin descarga automatica: {reason}.")
            return False
        try:
            tia_projects.assert_normal_not_master(self.project_root)  # nunca el MASTER experimental
        except tia_projects.TiaProjectGuardError as error:
            self._fail_normal_voice("Descarga", str(error))
            return False
        target = resolve_download_target(load_tia_config(self.project_root), DOWNLOAD_PURPOSE_NORMAL)
        if target["target_type"] != TARGET_TYPE_PLCSIM:
            if target.get('target_address') and flow.get('source')!=normal_voice.SOURCE_TEXT:
                self._set_normal_voice_stage('Descarga','skipped')
                self._finish_normal_voice('PLC físico sin identidad verificada: use CARGAR PROGRAMA AL PLC y confirme el destino.');return False
            # PLC FISICO: never without explicit confirmation.
            if not self._confirm_physical_download(self._physical_download_info(target)):
                self._set_normal_voice_stage("Descarga", "skipped")
                self._finish_normal_voice("Descarga al PLC fisico cancelada: la compilacion sigue vigente "
                                          "(CARGAR PROGRAMA AL PLC).")
                return False
        self._set_normal_voice_stage("Descarga", "running")
        self._log(f"[NORMAL] Compilacion aprobada: descarga automatica al destino Normal ({target['target_type']}).")
        self._start_download(Path(package_dir), DOWNLOAD_PURPOSE_NORMAL)
        return True

    def _physical_download_info(self, target: dict[str, Any]) -> dict[str, str]:
        """Destino/CPU/IP del proyecto NORMAL si estan disponibles (nunca del MASTER experimental)."""
        config = load_tia_config(self.project_root)
        return {
            "destino": f"{target.get('target_name') or '-'} ({target['target_type']})",
            "cpu": str(config.get("plc_name") or "") or "(unica en el proyecto)",
            "ip": str(target.get("target_address") or target.get("target_ip") or target.get("ip_address") or config.get("plc_ip") or "") or "no disponible",
            "proyecto": Path(tia_projects.normal_project_path(self.project_root) or "-").name,
        }

    def _confirm_physical_download(self, info: dict[str, str]) -> bool:
        dialog = PhysicalDownloadConfirmDialog(self, info)
        dialog.transient(self)
        self.wait_window(dialog)
        return bool(dialog.result)

    def execute_and_load_to_plc(self) -> None:
        """
        EJECUTAR Y CARGAR AL PLC: EXACTAMENTE el pipeline de EJECUTAR COMANDO (execute_full_pipeline);
        si todo pasa (semantica, aclaraciones resueltas, I/O, IR, verificador, compilacion, destino
        Normal valido) encadena la misma descarga que CARGAR PROGRAMA AL PLC.
        """
        if self.work_mode_var.get() != "Normal":
            messagebox.showwarning("Ejecutar y cargar", "EJECUTAR Y CARGAR AL PLC pertenece al Modo Normal.")
            return
        if self._tia_worker_active or self._download_worker_active or self._voice_worker_active or self._normal_voice_flow:
            messagebox.showwarning("Ejecutar y cargar", "Espere a que termine la operacion en curso.")
            return
        self._normal_voice_flow = normal_voice.new_flow(self.project_root, source=normal_voice.SOURCE_TEXT)
        self._refresh_normal_voice_target()
        self.normal_voice_stage_var.set(normal_voice.stage_text(self._normal_voice_flow))
        self._run_normal_voice_pipeline()


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
            self._fail_normal_voice("Transcripcion", str(payload))
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
                if self._normal_voice_flow is not None:
                    self._normal_voice_flow["transcript"] = transcript
                    self._set_normal_voice_stage("Transcripcion", "ok")
                    self.after(10, self._run_normal_voice_pipeline)
            else:
                self._set_status("Error")
                self._log(f"No se obtuvo texto de la grabacion: {error_message or 'voz no inteligible'}")
                self._fail_normal_voice("Transcripcion", error_message or "voz no inteligible")
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
        if getattr(self,'_application_close_pending',False):return
        self._application_close_pending=True
        self._pid_shutdown_error=None
        self._io_shutdown_error=None
        close_pid=getattr(self,'_pid_close_request',None)
        if close_pid:close_pid()
        self._finish_close_after_pid()

    def _finish_close_after_pid(self) -> None:
        io_error=getattr(self,'_io_shutdown_error',None)
        if io_error:
            self._application_close_pending=False
            messagebox.showwarning('Prueba de I/O',f'No se cerró la aplicación: {io_error}')
            return
        io_window=getattr(self,'_io_test_window',None)
        if io_window is not None and io_window.winfo_exists():
            if not io_window._busy and not io_window._closing:io_window.close()
            self.after(100,self._finish_close_after_pid)
            return
        error=getattr(self,'_pid_shutdown_error',None)
        if error:
            self._application_close_pending=False
            messagebox.showwarning('PID',f'No se cerró la aplicación: {error} Revise la evidencia en la ventana PID.')
            return
        window=getattr(self,'_pid_commissioning_window',None)
        if (window is not None and window.winfo_exists()) or getattr(self,'_pid_project_operation',None):
            self.after(100,self._finish_close_after_pid)
            return
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
            self._on_experiment_input_mode_changed()
            self._refresh_generated_trials()
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

    def _on_experiment_input_mode_changed(self, _choice: str | None = None) -> None:
        """TEXT y VOICE_CLEAN fijan 'sin ruido'; VOICE_NOISE exige un nivel de ruido (protocolo pendiente)."""
        input_mode = self._selected_input_mode()
        if input_mode == trial_model.INPUT_MODE_VOICE_NOISE:
            self.experiment_noise_selector.configure(state="normal")
            if self._selected_noise_level() == "none":
                self.experiment_noise_var.set(NOISE_LEVEL_LABELS["medium"])
        else:
            self.experiment_noise_var.set(NOISE_LEVEL_LABELS["none"])
            self.experiment_noise_selector.configure(state="disabled")
        self._last_experiment_input_mode = input_mode
        self._refresh_experiment_status()
        self._refresh_voice_panel()

    def _on_experiment_environment_changed(self, _choice: str | None = None) -> None:
        self._refresh_experiment_status()

    def _on_experiment_variant_changed(self, _choice: str | None = None) -> None:
        self._update_variant_command_preview()
        self._refresh_experiment_status()

    def _selected_input_mode(self) -> str:
        label = self.experiment_input_mode_var.get()
        for mode, mode_label in INPUT_MODE_LABELS.items():
            if mode_label == label or mode == label:
                return mode
        return trial_model.INPUT_MODE_TEXT

    def _selected_phase(self) -> str:
        label = self.experiment_phase_var.get()
        for phase, phase_label in EXPERIMENT_PHASE_LABELS.items():
            if phase_label == label or phase == label:
                return phase
        return trial_model.PHASE_DEVELOPMENT

    def _selected_condition(self) -> dict[str, Any]:
        """
        Compatibilidad con el registro legacy: la 'condicion' es ahora la modalidad de entrada. El
        modo de parser es el de la arquitectura evaluada (metadata tecnica, nunca un factor).
        """
        input_mode = self._selected_input_mode()
        try:
            parser_mode = experimental_design.architecture_parser_mode(self.project_root)
        except (OSError, ValueError, KeyError):
            parser_mode = "llm"
        return {
            "code": input_mode,
            "input_mode": input_mode,
            "parser_mode": parser_mode,
            "requires_voice": input_mode != trial_model.INPUT_MODE_TEXT,
        }

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
        legacy_whitelist = resource_policy.legacy_profile_whitelist_applies(self._benchmark_version())
        lines = [
            f"Perfil asociado: {profile['profile_id']}",
            (f"Variables habilitadas: {len(allowed_variables)}   (mapa: {len(self.io_variables)})" if legacy_whitelist
             else f"Recursos: working_io_map completo ({len(self.io_variables)} variables); allowed_variables = metadata historica"),
        ]
        if self.pending_semantic_output is not None and legacy_whitelist:
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

        case_id = profile.get("case_id", "")
        variant = self.experiment_variant_var.get()
        input_mode = self._selected_input_mode()
        phase = self._selected_phase()
        try:
            number = trial_model.next_trial_number(self.project_root, case_id, variant, input_mode, phase)
            next_id = trial_model.build_trial_id(
                case_id, variant, input_mode, number,
                development=trial_model.trial_kind_for_phase(phase) == trial_model.TRIAL_KIND_DEVELOPMENT
            )
        except ValueError:
            next_id = "-"
        benchmark_version = benchmark_catalog.load_catalog(self.project_root).get("benchmark_version")
        self.experiment_next_label_var.set(
            f"Proximo ensayo: {next_id}\nBenchmark v{benchmark_version} · {trial_model.trial_kind_for_phase(phase)} · {phase}"
        )
        self._refresh_oracle_status()
        self._refresh_voice_panel()

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

    # Etapa del panel -> clave de deferred_evaluator.trial_stage_summary (fuente unica persistida).
    _SUMMARY_STAGE_KEYS = {"Semantica": "semantic", "I/O": "io_allocation", "Generacion": "ir", "Verificacion": "ir",
                           "Compilacion": "compilation", "Descarga": "download", "CPU Start": "cpu_start",
                           "Runtime": "runtime", "Oracle": "oracle", "Functional": "functional", "Safety": "safety"}
    _SUMMARY_VALUE_STATES = {"PASS": "ok", "FAIL": "fail", "INFRA": "fail", "INFRASTRUCTURE_ERROR": "fail", "REVIEW": "pending",
                             deferred_evaluator.STAGE_NOT_RUN: "skipped"}

    def _apply_trial_summary_to_stages(self, trial_dir: Path) -> dict[str, Any] | None:
        """Sincroniza la linea de etapas con el registro persistido del ensayo (tras evaluar o al verlo)."""
        try:
            summary = deferred_evaluator.trial_stage_summary(trial_model.load_trial(Path(trial_dir)))
        except (OSError, ValueError):
            return None
        for stage, key in self._SUMMARY_STAGE_KEYS.items():
            self._experiment_stage_states[stage] = self._SUMMARY_VALUE_STATES.get(summary[key], "pending")
        self._render_experiment_stages()
        return summary

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
                elapsed_ms = int(round((time.perf_counter() - started_perf) * 1000))
                trial_model.update_trial(directory, {"timing": {"end_to_end_ms": elapsed_ms, "total_ms": elapsed_ms}})
            self._discard_trial_working_map(final_status)
            record = trial_model.finalize_trial(directory, final_status, errors)
            classification = experimental_design.classify_trial(record)
            trial_model.update_trial(directory, {**classification, "final_verdict": final_status})
            self._log(f"[EXPERIMENT] Status -> {final_status} ({classification['failure_category']})")
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
        """
        Copia el mapa base (inventario fisico, sin residuos) al ensayo. La fuente es el mapa BASE
        versionado (<id>_base.json), nunca el working local de Modo Normal de esta PC.
        """
        info = (self.active_trial or {}).get("new_trial")
        if not info:
            return True
        source_path, selection = self._experiment_base_map_source()
        if selection is not None and not selection.get("path"):
            self._log(f"[EXPERIMENT IO] {selection.get('reason')}")
            self._update_new_trial({"experiment_map": experiment_maps.selection_evidence(selection),
                                    "io_map": {"error": experiment_maps.ERROR_NO_MAP}})
            self._finalize_new_trial(trial_model.FINAL_STATUS_FAIL, [str(selection.get("reason"))])
            self._cancel_active_trial(experiment_maps.ERROR_NO_MAP)
            messagebox.showerror("Ejecutar ensayo", f"Ningun mapa experimental cubre este caso.\n\n{selection.get('reason')}")
            return False
        try:
            reference = trial_io_map.create_working_map(Path(info["dir"]), source_path, map_policy=product_engine.MAP_POLICY)
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
            "lifecycle_state": trial_io_map.STATE_PREPARING,
            **({"experiment_map": experiment_maps.selection_evidence(selection)} if selection is not None else {}),
        })
        if selection is not None:
            self._log(f"[EXPERIMENT IO] Mapa experimental: {selection['map_id']} (simulation_only={selection['simulation_only']}; "
                      f"{selection['reason']})")
        self._log(
            f"[EXPERIMENT IO] Working map creado desde {reference['base_map_id']} "
            f"({reference['physical_channel_count']} canales fisicos)."
        )
        return True

    def _experiment_base_map_source(self) -> tuple[Path, dict[str, Any] | None]:
        """
        Mapa base del ensayo: seleccion DETERMINISTA por capacidad (config/experiment_maps.json) a partir de los roles
        del Oracle congelado del caso. Sin Oracle (casos legacy) se conserva el mapa base del mapa activo.
        """
        case_id = (self.active_trial or {}).get("case_id")
        try:
            oracle = oracle_schema.find_case_oracle(self.project_root, case_id)
        except Exception:  # noqa: BLE001 - un Oracle invalido lo bloquea el precheck; aqui no se decide nada
            oracle = None
        if oracle is None:
            return experiment_reference_map_path(self.io_map_path), None
        selection = experiment_maps.select_experiment_map(self.project_root, oracle)
        return (Path(selection["path"]) if selection.get("path") else experiment_reference_map_path(self.io_map_path)), selection

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
            input_mode = condition.get("input_mode") or trial_model.input_mode_from_selection(
                bool(condition.get("requires_voice")), self._selected_noise_level()
            )
            phase = self.active_trial.get("experiment_phase") or trial_model.PHASE_DEVELOPMENT
            number = trial_model.next_trial_number(self.project_root, case_id, variant, input_mode, phase)
            llm = getattr(self, "llm_client", None)
            record = trial_model.new_trial_record(
                case_id,
                variant,
                input_mode,
                number,
                complexity=profile.get("complexity"),
                extra={
                    **experimental_design.campaign_reference(self.project_root, phase),
                    "legacy_trial_id": self.active_trial.get("trial_id"),
                    "legacy_experiment_label": self.active_trial.get("experiment_label"),
                    "parser_mode": condition.get("parser_mode"),
                    "model": {"provider": getattr(llm, "provider", None), "model": getattr(llm, "model_name", None)},
                    "speaker_id": self.active_trial.get("speaker_id"),
                    "noise_level": self.active_trial.get("noise_level"),
                    "map_name": self.active_trial.get("map_name"),
                    "profile_id": self.active_trial.get("profile_id"),
                    "reference_command_text": self.active_trial.get("reference_command_text"),
                    "git_commit": self.active_trial.get("git_commit"),
                    **{key: value for key, value in benchmark_catalog.trial_benchmark_reference(self.project_root, case_id, variant).items()
                       if key in ("benchmark_version", "canonical_case_hash", "variant_hash")}
                },
                phase=phase
            )
            directory = trial_model.trial_directory(self.project_root, case_id, variant, record["trial_id"], phase)
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
        phase = self._selected_phase()
        if phase == trial_model.PHASE_FORMAL:
            # Guard de congelacion: sin software_freeze_manifest valido no existe FORMAL_TRIAL.
            try:
                experimental_design.require_formal_cases(self.project_root, [profile.get('case_id', '')])
            except ValueError as error:
                messagebox.showwarning('Ejecutar ensayo', str(error))
                return False
            allowed, reasons = experimental_design.check_formal_trial_allowed(self.project_root)
            if not allowed:
                self._log("[EXPERIMENT] " + " | ".join(reasons))
                messagebox.showwarning("Ejecutar ensayo", "Fase FORMAL bloqueada:\n\n" + "\n".join(reasons[:5]))
                return False
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
        # Registro legacy (experiments/): la "condicion" de la etiqueta es ahora la modalidad.
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
            "input_mode": condition["input_mode"],
            "experiment_phase": phase,
            "trial_kind": trial_model.trial_kind_for_phase(phase),
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
        self.parser_mode_var.set(parser_ui_map.get(condition["parser_mode"], "LLM"))

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

    # ------------------------------------------------------------------------------------------
    # Fase 4A-DEFERRED: GENERAR ENSAYO / EVALUAR ENSAYO GUARDADO
    # ------------------------------------------------------------------------------------------

    def _tia_busy(self, *, allow_pid_model: bool=False) -> bool:
        return bool(self._tia_worker_active or self._download_worker_active or self._runtime_worker_active
                    or self._oracle_worker_active or self._deferred_worker_active
                    or getattr(self,'_io_test_window',None) is not None
                    or (getattr(self,'_pid_project_operation',None)
                        and not (allow_pid_model and self._pid_project_operation=='MODEL')))

    def open_preferences(self) -> None:
        self._preferences_window.deiconify();self._preferences_window.lift();self._preferences_window.focus()

    def open_tia_config_dialog(self) -> TiaConfigDialog:
        dialog = TiaConfigDialog(self)
        dialog.transient(self)
        return dialog

    def generate_experiment_trial(self) -> Path | None:
        """
        GENERAR ENSAYO: comando -> LLM -> semantica -> IOAllocator -> working map -> snapshot -> IR ->
        SCL -> verificaciones sin TIA -> artefactos + integrity_manifest.json. NO abre TIA, no
        descarga, no ejecuta PLCSIM ni Oracle. Devuelve la carpeta del ensayo.
        """
        if self._tia_busy() or self._voice_worker_active:
            messagebox.showwarning("Generar ensayo", "Espere a que termine la operacion en curso.")
            return None
        if self._selected_phase() == trial_model.PHASE_FORMAL:
            messagebox.showwarning("Generar solo", "GENERAR SOLO es DEVELOPMENT/DEBUG: un FORMAL_TRIAL se ejecuta con EJECUTAR ENSAYO COMPLETO.")
            return None
        if self._selected_input_mode() == trial_model.INPUT_MODE_TEXT:
            self._use_variant_command()  # TEXT: siempre el texto exacto de la variante del benchmark
        command_text = self.command_textbox.get("1.0", "end").strip()
        if not command_text:
            messagebox.showwarning("Generar ensayo", "No hay comando para el ensayo.")
            return None
        if not self.start_trial():
            return None
        info = (self.active_trial or {}).get("new_trial") or {}
        new_dir = Path(info["dir"]) if info.get("dir") else None
        legacy = dict(self.active_trial or {})
        self.start_trial_button.configure(state="disabled")
        try:
            ok = self.process_command() and self.generate_package()
            package_dir = (self.active_trial or {}).get("package_dir")
            if self.active_trial:
                self._discard_trial_working_map(None)  # el snapshot congelado queda como evidencia
            if new_dir is None:
                return None
            record = deferred_evaluator.finalize_generation(self.project_root, new_dir, Path(package_dir) if ok and package_dir else None)
            generation = (record.get("generation") or {}).get("status")
            if legacy.get("trial_id") and self.active_trial:
                # Registro legacy paralelo (experiments/): el ensayo queda GENERADO, sin resultado manual.
                save_metadata(trial_dir(self.project_root, legacy["case_id"], legacy["trial_id"]),
                              {"state": "GENERATED", "new_trial_id": record.get("trial_id")})
            self.experiment_status_var.set(
                f"Ensayo {record.get('trial_id')}: generacion {generation} · evaluacion {(record.get('evaluation') or {}).get('status')}")
            self._log(f"[EXPERIMENT] {record.get('trial_id')} GENERADO ({generation}); evaluacion pendiente. TIA no se abrio.")
            return new_dir
        finally:
            self.active_trial = None
            self.manual_result_frame.grid_remove()
            self.start_trial_button.configure(state="normal")
            self._refresh_generated_trials()

    def _refresh_generated_trials(self) -> None:
        tree = getattr(self, "generated_trials_tree", None)
        if tree is None:
            return
        tree.delete(*tree.get_children())
        self._generated_trial_dirs = {}
        try:
            rows = deferred_evaluator.list_trials(self.project_root)
        except (OSError, ValueError) as error:  # pragma: no cover - feedback de GUI
            self._log(f"No se pudo listar los ensayos: {error}")
            return
        for row in sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True):
            item = tree.insert("", "end", values=(row["trial_id"], row["case_id"], row["variant_id"], row["generation"],
                                                  row["evaluation"] or "-", row["verdict"] or "-"))
            self._generated_trial_dirs[item] = row["trial_dir"]

    def _selected_generated_trial_dir(self) -> Path | None:
        selection = self.generated_trials_tree.selection()
        if not selection:
            return None
        return Path(self._generated_trial_dirs[selection[0]])

    def view_generated_trial(self) -> None:
        trial_dir = self._selected_generated_trial_dir()
        if trial_dir is None:
            messagebox.showinfo("Ver ensayo", "Seleccione un ensayo de la lista.")
            return
        record = trial_model.load_trial(trial_dir)
        lines = deferred_evaluator.evaluation_summary_lines(self.project_root, trial_dir) + [""] + [
            f"{label}: {value}" for label, value in deferred_evaluator.verdict_table(record)] + ["", f"Carpeta: {trial_dir}"]
        messagebox.showinfo("Ver ensayo", "\n".join(lines))

    def evaluate_saved_trial(self, trial_dir: Path | None = None) -> Any:
        """EVALUAR ENSAYO GUARDADO: abre el resumen; la evaluacion empieza solo con INICIAR EVALUACION."""
        trial_dir = trial_dir or self._selected_generated_trial_dir()
        if trial_dir is None:
            chosen = filedialog.askdirectory(title="Seleccione la carpeta del ensayo generado", initialdir=str(self.project_root / "results"))
            if not chosen:
                return None
            trial_dir = Path(chosen)
        if not (Path(trial_dir) / trial_model.TRIAL_FILENAME).exists():
            messagebox.showwarning("Evaluar ensayo", "La carpeta no contiene trial.json.")
            return None
        return self._open_deferred_dialog(Path(trial_dir), retry=False)

    def evaluate_next_pending(self) -> Any:
        """Localiza el siguiente GENERADO pendiente y abre su resumen. Nunca inicia la evaluacion solo."""
        pending = deferred_evaluator.next_pending(self.project_root)
        if pending is None:
            messagebox.showinfo("Evaluar siguiente pendiente", "No hay ensayos generados pendientes de evaluacion.")
            return None
        return self._open_deferred_dialog(Path(pending["trial_dir"]), retry=False)

    def retry_trial_evaluation(self) -> Any:
        trial_dir = self._selected_generated_trial_dir()
        if trial_dir is None:
            messagebox.showinfo("Reintentar evaluacion", "Seleccione un ensayo con INFRASTRUCTURE_ERROR.")
            return None
        evaluation = trial_model.load_trial(trial_dir).get("evaluation") or {}
        if evaluation.get("status") != deferred_evaluator.EVALUATION_INFRASTRUCTURE:
            messagebox.showwarning("Reintentar evaluacion", "Solo se reintentan evaluaciones con INFRASTRUCTURE_ERROR.")
            return None
        return self._open_deferred_dialog(trial_dir, retry=True)

    def _open_deferred_dialog(self, trial_dir: Path, retry: bool, autostart: bool = False) -> Any:
        if self._tia_busy():
            messagebox.showwarning("Evaluar ensayo", "Ya hay una operacion TIA/PLCSIM en curso.")
            return None
        dialog = DeferredEvaluationDialog(self, trial_dir, retry=retry, autostart=autostart)
        dialog.transient(self)
        self._deferred_dialog = dialog
        return dialog

    def _start_deferred_evaluation(self, trial_dir: Path, retry_reason: str | None, dialog: Any = None) -> bool:
        if self._tia_busy():
            messagebox.showwarning("Evaluar ensayo", "Ya hay una operacion TIA/PLCSIM en curso.")
            return False
        self._deferred_worker_active = True
        self._deferred_dialog = dialog
        self._deferred_trial_dir = Path(trial_dir)
        self._log(f"[DEFERRED] Evaluando {Path(trial_dir).name}...")

        def _worker() -> None:
            try:
                result = deferred_evaluator.evaluate_trial(self.project_root, Path(trial_dir), retry_reason, log=lambda m: None)
                self._deferred_queue.put(("ok", result))
            except Exception as error:  # pragma: no cover - feedback de GUI
                # Diagnostico persistido (tipo, fase, intento, traceback sin secretos): evaluate_trial ya lo
                # registra si el fallo ocurrio dentro de la evaluacion; si no, se registra aqui.
                diagnostic = getattr(error, "diagnostic_path", None) or deferred_evaluator.record_unexpected_error(
                    Path(trial_dir), error, "gui_deferred_worker")
                self._deferred_queue.put(("error", f"{type(error).__name__}: {error}"
                                          + (f" (diagnostico: {diagnostic})" if diagnostic else "")))

        threading.Thread(target=_worker, name="deferred-eval", daemon=True).start()
        self.after(500, self._poll_deferred_evaluation)
        return True

    def _poll_deferred_evaluation(self) -> None:
        try:
            outcome, payload = self._deferred_queue.get_nowait()
        except queue.Empty:
            self.after(500, self._poll_deferred_evaluation)
            return
        self._deferred_worker_active = False
        if outcome == "ok" and not payload.get("aborted"):
            self._log(f"[DEFERRED] {payload.get('final_status')} ({payload.get('failure_category')})")
        else:
            self._log(f"[DEFERRED] Evaluacion no realizada: {payload if outcome == 'error' else payload.get('errors')}")
        if self._deferred_dialog is not None:
            try:
                self._deferred_dialog.show_result(outcome, payload)
            except tk.TclError:  # pragma: no cover - dialogo cerrado
                pass
        if getattr(self, "_deferred_trial_dir", None) is not None:
            self._apply_trial_summary_to_stages(self._deferred_trial_dir)
        self._refresh_generated_trials()
        batch_dir = getattr(self, "_batch_evaluating_dir", None)
        if batch_dir is not None and Path(batch_dir) == getattr(self, "_deferred_trial_dir", None):
            self._batch_evaluating_dir = None
            self.after(0, self._batch_on_evaluation_finished)
        # Intencional: NUNCA se encadena la evaluacion del siguiente pendiente (control de recursos).


    # ------------------------------------------------------------------------------------------
    # Fase 4A-FINAL: EJECUTAR ENSAYO COMPLETO (un clic = un ensayo) + protocolo de voz
    # ------------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------------
    # LOTE TEXT (trial_experiments.text_batch): uno por uno, con el MISMO flujo de EJECUTAR ENSAYO
    # COMPLETO. Maquina de estados sobre el bucle de Tk: el ensayo N+1 solo se programa desde el
    # callback de fin del ensayo N, despues de persistir su resultado (nunca dos ensayos ni dos TIA).
    # ------------------------------------------------------------------------------------------

    BATCH_SPEAKER_ID = "TEXT_BATCH"
    BATCH_STEP_DELAY_MS = 1500

    def _text_batch_running(self) -> bool:
        state = getattr(self, "_text_batch", None)
        return bool(state) and (state["manifest"].get("status") == text_batch.STATUS_RUNNING
                                or bool(state["manifest"].get("automatic_retry_pending")))

    def _text_batch_manifest(self) -> dict[str, Any] | None:
        state = getattr(self, "_text_batch", None)
        return state["manifest"] if state else None

    def _batch_save(self) -> None:
        state = self._text_batch
        text_batch.save_manifest(state["dir"], state["manifest"])
        text_batch.write_summaries(self.project_root, state["dir"], state["manifest"])
        self._refresh_text_batch_dialog()

    def _load_open_text_batch(self) -> dict[str, Any] | None:
        """Lote abierto persistido (tras cerrar la GUI o una caida). Nunca se reanuda solo."""
        state = getattr(self, "_text_batch", None)
        if state and state["manifest"].get("status") in text_batch.OPEN_STATUSES:
            return state["manifest"]
        self._text_batch = None
        manifest = text_batch.find_open_batch(self.project_root)
        if manifest is not None:
            self._text_batch = {"dir": text_batch.batch_dir_for(self.project_root, manifest), "manifest": manifest, "dialogs": []}
            if manifest.pop('automatic_retry_pending', None):
                # El cierre de la aplicación cancela la programación, sin reiniciar su presupuesto.
                manifest['pause_detail'] = 'Reintento automático cancelado al cerrar la aplicación; reanudación manual requerida.'
                self._batch_save()
            if manifest["status"] == text_batch.STATUS_RUNNING:
                issues = text_batch.reconcile(self.project_root, manifest)
                text_batch.pause(manifest, text_batch.PAUSE_INCONSISTENT if issues else text_batch.PAUSE_USER,
                                 "; ".join(issues) or "Lote recuperado al reabrir la aplicacion; reanudacion explicita requerida.")
                self._batch_save()
        return manifest

    def start_text_batch(self, phase: str, case_ids: list[str] | None, variants: list[str],
                         input_mode: str = trial_model.INPUT_MODE_TEXT) -> dict[str, Any]:
        """
        Crea y arranca un lote (TEXT / VOICE_CLEAN / VOICE_NOISE). FORMAL solo si TODAS las guardas pasan.
        VOICE_NOISE: si falta UNA pareja integra de las celdas planificadas (FORMAL: las 96) no se empieza (antes del ASR).
        """
        if self._text_batch_running() or self._tia_busy() or self._voice_worker_active:
            return {"ok": False, "errors": ["Hay una operacion o un lote en curso."]}
        if self._load_open_text_batch() is not None:
            return {"ok": False, "errors": [f"{text_batch.ERROR_OPEN_BATCH}: reanude o cancele el lote abierto."]}
        try:
            if phase == trial_model.PHASE_FORMAL:
                case_ids = experimental_design.formal_case_ids(self.project_root) if case_ids is None else case_ids
                experimental_design.require_formal_cases(self.project_root, case_ids)
            plan = text_batch.build_plan(self.project_root, case_ids, variants, input_mode)
        except ValueError as error:
            return {"ok": False, "errors": [str(error)]}
        if input_mode == trial_model.INPUT_MODE_VOICE_NOISE:
            pairs = formal_audio.noise_batch_preflight(self.project_root, phase, [(e["case_id"], e["variant_id"]) for e in plan])
            if not pairs["ok"]:
                return {"ok": False, "errors": [f"PAIRS READY: {pairs['pairs_ready']} / {pairs['total']}"] + pairs["errors"]
                        + [f"{formal_audio.ERROR_PAIR_MISSING}: {m}" for m in pairs["missing"]], "pairs": pairs}
        elif input_mode == trial_model.INPUT_MODE_VOICE_CLEAN:
            master = formal_audio.noise_master_status(self.project_root, phase)
            if not master["ready"]:
                return {"ok": False, "errors": [master["error"]]}
        git = text_batch.git_info(self.project_root)
        if phase == trial_model.PHASE_FORMAL:
            guards = text_batch.formal_guards(self.project_root, plan, git=git,
                                              runtime_status_fn=lambda root: plcsim_runtime.get_plcsim_runtime_status(root))
            if not guards["ok"]:
                return {"ok": False, "errors": [f"{text_batch.ERROR_FORMAL_GUARD}: {c['id']}: {c['detail']}" for c in guards["checks"] if not c["ok"]],
                        "guards": guards}
        try:
            batch_dir, manifest = text_batch.create_batch(self.project_root, phase, case_ids, variants,
                                                          host_id=load_host_id(self.project_root), git=git, input_mode=input_mode)
        except ValueError as error:
            return {'ok': False, 'errors': [str(error)]}
        self._text_batch = {"dir": batch_dir, "manifest": manifest, "dialogs": []}
        self._log(f"[BATCH] {manifest['batch_id']}: {manifest['total_trials']} ensayos {input_mode} ({phase}).")
        return self.resume_text_batch()

    def resume_text_batch(self) -> dict[str, Any]:
        """REANUDAR: contrasta el manifiesto con los trial.json; ante inconsistencias queda PAUSADO."""
        manifest = self._load_open_text_batch()
        if manifest is None:
            return {"ok": False, "errors": ["No hay lote abierto."]}
        if manifest.get('automatic_retry_pending'):
            return {'ok': False, 'errors': ['Hay un reintento automático programado; puede pausarlo o detenerlo.']}
        if self._tia_busy() or self._voice_worker_active:
            return {"ok": False, "errors": ["Hay una operacion TIA/PLCSIM en curso."]}
        issues = text_batch.reconcile(self.project_root, manifest)
        attention = [e for e in manifest["ordered_trial_plan"] if e["status"] in text_batch.ATTENTION_ENTRY_STATES]
        if issues or attention:
            detail = "; ".join(issues) or "; ".join(f"{text_batch.entry_label(e)}: {e['status']}" for e in attention)
            text_batch.pause(manifest, text_batch.PAUSE_INCONSISTENT if issues else manifest.get("pause_reason") or text_batch.PAUSE_INFRASTRUCTURE, detail)
            self._batch_save()
            return {"ok": False, "errors": [detail], "paused": True}
        text_batch.mark_started(manifest)
        self._batch_save()
        self.after(0, self._batch_run_next)
        return {"ok": True, "errors": []}

    def request_text_batch_pause(self) -> None:
        """PAUSAR DESPUES DEL ENSAYO ACTUAL: nunca interrumpe TIA."""
        manifest = self._text_batch_manifest()
        if manifest and manifest.get('automatic_retry_pending'):
            self._cancel_batch_automatic_retry('Pausa solicitada durante la espera.')
            text_batch.pause(manifest, text_batch.PAUSE_USER, 'Reintento automático cancelado por el usuario.')
            self._batch_save()
            return
        if manifest and manifest["status"] == text_batch.STATUS_RUNNING:
            text_batch.request_pause(manifest)
            self._batch_save()
            self._log("[BATCH] Pausa solicitada: se aplicara al terminar el ensayo actual.")

    def stop_text_batch(self) -> None:
        """DETENER LOTE: si hay un ensayo en curso, se detiene de forma segura al terminarlo."""
        manifest = self._text_batch_manifest()
        if not manifest:
            return
        if manifest.get('automatic_retry_pending'):
            self._cancel_batch_automatic_retry('Lote detenido por el usuario.')
        if manifest["status"] == text_batch.STATUS_RUNNING:
            manifest["stop_requested"] = True
            text_batch.request_pause(manifest)
            self._batch_save()
            self._log("[BATCH] Detencion solicitada: se aplicara al terminar el ensayo actual.")
            return
        text_batch.cancel(manifest, "detenido por el usuario")
        self._batch_save()
        self._log(f"[BATCH] {manifest['batch_id']} detenido.")

    def retry_text_batch_trial(self, reason: str) -> dict[str, Any]:
        """
        REINTENTAR ESTE ENSAYO (manual o motivo automático persistido). Política de deferred_evaluator:
          INFRASTRUCTURE_ERROR de la evaluacion -> nuevo intento del MISMO ensayo (attempt_002, motivo);
          precheck bloqueado (ensayo generado, evaluacion PENDING) -> se evalua ese MISMO ensayo;
          generacion caida / ensayo interrumpido -> ensayo NUEVO para la celda (el anterior se conserva).
        """
        manifest = self._load_open_text_batch()
        if manifest is None or manifest["status"] != text_batch.STATUS_PAUSED:
            return {"ok": False, "errors": ["El lote no esta pausado."]}
        if self._tia_busy() or self._voice_worker_active or self.active_trial is not None:
            return {'ok': False, 'errors': ['Hay una operación en curso; el reintento permanece pausado.']}
        campaign_errors = text_batch.campaign_errors(self.project_root, manifest)
        if campaign_errors:
            return {'ok': False, 'errors': campaign_errors}
        if not (reason or "").strip():
            return {"ok": False, "errors": [f"{deferred_evaluator.ERROR_RETRY_REASON}: indique el motivo del reintento."]}
        entry = text_batch.next_entry(manifest)
        if entry is None or entry["status"] not in text_batch.ATTENTION_ENTRY_STATES:
            return {"ok": False, "errors": ["No hay un ensayo pendiente de reintento: use REANUDAR."]}
        self._cancel_batch_automatic_retry('Reintento solicitado.')
        record = trial_model.load_trial(Path(entry["trial_dir"])) if entry.get("trial_dir") and \
            (Path(entry["trial_dir"]) / trial_model.TRIAL_FILENAME).exists() else {}
        generation = (record.get("generation") or {}).get("status")
        evaluation = (record.get("evaluation") or {}).get("status")
        retry_reason = None
        if entry["status"] == text_batch.ENTRY_INFRASTRUCTURE and generation == deferred_evaluator.GENERATION_SUCCESS \
                and evaluation == deferred_evaluator.EVALUATION_INFRASTRUCTURE:
            entry["status"], retry_reason = text_batch.ENTRY_EVALUATING, reason.strip()
        elif entry["status"] == text_batch.ENTRY_BLOCKED and evaluation == deferred_evaluator.EVALUATION_PENDING:
            entry["status"] = text_batch.ENTRY_EVALUATING
        else:
            text_batch.supersede_for_new_trial(manifest, entry, reason.strip())
            entry["retry_reason"] = reason.strip()
        text_batch.mark_started(manifest)
        self._batch_save()
        self.after(0, lambda: self._batch_run_next(retry_reason))
        return {"ok": True, "errors": []}

    def _configure_experiment_selection(self, entry: dict[str, Any], phase: str) -> None:
        """Fija los selectores de la GUI que lee EJECUTAR ENSAYO COMPLETO (mismo camino que un clic)."""
        if self.work_mode_var.get() != "Experimentacion":
            self.work_mode_var.set("Experimentacion")
            self._on_work_mode_changed()
        group = "PID P01-P12" if entry["case_id"].startswith("P") else "Discreto D01-D20"
        if self.experiment_group_var.get() != group:
            self.experiment_group_var.set(group)
            self._refresh_experiment_case_selector()  # sin cambiar el mapa activo en silencio
        label = next((name for name, profile in self._experiment_profiles_by_case.items() if profile.get("case_id") == entry["case_id"]), None)
        if label is None:
            raise RuntimeError(f"No existe el perfil experimental de {entry['case_id']}.")
        self.experiment_case_var.set(label)
        self._on_experiment_case_changed()
        self.experiment_variant_var.set(entry["variant_id"])
        self._on_experiment_variant_changed()
        self.experiment_input_mode_var.set(INPUT_MODE_LABELS[entry.get("input_mode") or trial_model.INPUT_MODE_TEXT])
        self._on_experiment_input_mode_changed()
        self.experiment_phase_var.set(EXPERIMENT_PHASE_LABELS[phase])
        if not self.experiment_speaker_var.get().strip():
            self.experiment_speaker_var.set(self.BATCH_SPEAKER_ID)
        if self._active_variant_command_text != entry["reference_text"]:
            raise RuntimeError(f"El comando cargado para {text_batch.entry_label(entry)} no coincide con el benchmark.")

    @contextlib.contextmanager
    def _unattended_interactions(self, dialogs: list[dict[str, str]]) -> Any:
        """
        Lote desatendido: ningun dialogo bloquea. Los mensajes se registran (y se guardan en el ensayo);
        las confirmaciones responden NO y las aclaraciones quedan SIN responder (protocolo del lote:
        nadie responde; el ensayo registra clarification_requested).
        """
        module = sys.modules[__name__]
        originals = {name: getattr(messagebox, name) for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel")}
        original_ask = simpledialog.askstring
        original_dialog = module.ClarificationDialog
        original_wait = self.wait_window

        def _record(kind: str) -> Callable[..., Any]:
            def _dialog(title: str = "", message: str = "", *args: Any, **kwargs: Any) -> Any:
                dialogs.append({"kind": kind, "title": str(title), "message": str(message)[:500]})
                self._log(f"[BATCH] {kind}: {title}: {str(message)[:200]}")
                return False if kind.startswith("ask") else None
            return _dialog

        class _NoAnswer:
            def __init__(self, _parent: Any, question: str) -> None:
                dialogs.append({"kind": "clarification", "title": "Aclaracion (sin respuesta en lote)", "message": str(question)[:500]})
                self.result = None

        try:
            for name in originals:
                setattr(messagebox, name, _record(name))
            simpledialog.askstring = lambda *a, **k: None
            module.ClarificationDialog = _NoAnswer
            self.wait_window = lambda *a, **k: None
            yield dialogs
        finally:
            for name, function in originals.items():
                setattr(messagebox, name, function)
            simpledialog.askstring = original_ask
            module.ClarificationDialog = original_dialog
            self.wait_window = original_wait

    def _batch_run_next(self, retry_reason: str | None = None) -> None:
        state = getattr(self, "_text_batch", None)
        if not state:
            return
        manifest, batch_dir = state["manifest"], state["dir"]
        if manifest["status"] != text_batch.STATUS_RUNNING:
            return
        campaign_errors = text_batch.campaign_errors(self.project_root, manifest)
        if campaign_errors:
            text_batch.pause(manifest, text_batch.PAUSE_INCONSISTENT, '; '.join(campaign_errors))
            self._batch_save()
            return
        if self._tia_busy() or self._voice_worker_active or self.active_trial is not None:
            self.after(1000, lambda: self._batch_run_next(retry_reason))  # nunca se solapa con otra operacion
            return
        if manifest.get("pause_requested"):
            self._batch_finish_pause()
            return
        entry = text_batch.next_entry(manifest)
        if entry is None:
            self._batch_apply_decision(text_batch.DECISION_COMPLETED if text_batch._complete_if_done(manifest) else text_batch.DECISION_PAUSE)
            return
        state["current_index"] = entry["index"]
        if entry["status"] == text_batch.ENTRY_EVALUATING and entry.get("trial_dir"):
            self._batch_evaluate(entry, retry_reason)  # reanudacion: se evalua el MISMO ensayo ya generado
            return
        if entry["status"] != text_batch.ENTRY_PENDING:
            text_batch.pause(manifest, text_batch.PAUSE_INCONSISTENT, f"{text_batch.entry_label(entry)} en estado {entry['status']}")
            self._batch_save()
            return
        environment = deferred_evaluator.environment_precheck(self.project_root, manifest["phase"])
        if not environment["ok"]:
            # El entorno no puede evaluar: no se gasta un ensayo (ni LLM) - pausa antes de generar.
            text_batch.pause(manifest, text_batch.PAUSE_ENVIRONMENT, "; ".join(environment["errors"][:4]))
            self._batch_save()
            self._log(f"[BATCH] Pausado: entorno no listo: {'; '.join(environment['errors'][:3])}")
            return
        try:
            self._configure_experiment_selection(entry, manifest["phase"])
        except RuntimeError as error:
            text_batch.pause(manifest, text_batch.PAUSE_INCONSISTENT, str(error))
            self._batch_save()
            return
        dialogs: list[dict[str, str]] = []
        repeat_reason = entry.get("retry_reason") or f"Lote {manifest['batch_id']}"
        batch_trial = {"batch_id": manifest["batch_id"], "index": entry["index"], "repeat_reason": repeat_reason,
                       "on_started": lambda directory: self._batch_on_started(entry, directory),
                       "on_generated": lambda directory, generation: self._batch_on_generated(entry, directory, generation, dialogs),
                       "notify": lambda title, text: dialogs.append({"kind": "precheck", "title": title, "message": text[:500]})}
        if entry.get("input_mode") == trial_model.INPUT_MODE_VOICE_CLEAN:
            capture = self._batch_clean_capture(entry, manifest)
            if capture is False:
                return  # pausado por el operador antes de grabar: sin resultado experimental
            if capture is not None:
                batch_trial["capture"] = capture
        self._log(f"[BATCH] {manifest['batch_id']} · {entry['index'] + 1}/{manifest['total_trials']} · {text_batch.entry_label(entry)}")
        self._refresh_text_batch_dialog()
        with self._unattended_interactions(dialogs):
            new_dir = self.run_complete_trial(batch_trial=batch_trial)
        if new_dir is None:
            # El flujo individual rechazo el ensayo antes de crearlo (mismo criterio que un clic).
            if entry["status"] == text_batch.ENTRY_GENERATING and entry.get("trial_dir"):
                return  # ya creado: on_generated decide
            text_batch.pause(manifest, text_batch.PAUSE_ENVIRONMENT,
                             "; ".join(d["message"] for d in dialogs[:3]) or "el ensayo no pudo iniciarse")
            self._batch_save()

    def _batch_clean_capture(self, entry: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any] | None | bool:
        """
        Celda VOICE_CLEAN: si ya tiene locucion congelada (p.ej. reintento por INFRASTRUCTURE_ERROR) se reutiliza el MISMO
        WAV y no se pide nada (None). Si no, dialogo asistido: devuelve la captura, o False si el operador pausa el lote.
        """
        corpus = formal_audio.load_corpus(self.project_root, manifest["phase"])
        cell = formal_audio.cell_entry(corpus, entry["case_id"], entry["variant_id"])
        if cell["state"] != formal_audio.STATE_NOT_RECORDED:
            return None
        dialog = CleanBatchCellDialog(self, entry, manifest, "NOT RECORDED", "NOT READY")
        self.wait_window(dialog)
        if dialog.result is None:
            text_batch.pause(manifest, text_batch.PAUSE_USER, f"{text_batch.entry_label(entry)}: pausado antes de grabar")
            self._batch_save()
            self._refresh_text_batch_dialog()
            return False
        return dialog.result

    def _batch_on_started(self, entry: dict[str, Any], trial_dir: Path) -> None:
        trial_id = Path(trial_dir).name
        text_batch.begin_entry(self._text_batch["manifest"], entry, Path(trial_dir), trial_id)
        self._batch_save()

    def _batch_on_generated(self, entry: dict[str, Any], trial_dir: Path, generation: str | None, dialogs: list[dict[str, str]]) -> None:
        if dialogs:
            trial_model.update_trial(Path(trial_dir), {"batch_dialogs": dialogs[:10]})
        if generation == deferred_evaluator.GENERATION_SUCCESS:
            self._batch_evaluate(entry)
            return
        # Generacion terminada sin paquete (p.ej. Semantic/IR FAIL): resultado experimental del ensayo.
        state = self._text_batch
        self._batch_apply_decision(text_batch.record_trial_result(self.project_root, state["dir"], state["manifest"], entry))

    def _batch_evaluate(self, entry: dict[str, Any], retry_reason: str | None = None) -> None:
        state = self._text_batch
        manifest, batch_dir = state["manifest"], state["dir"]
        trial_dir = Path(entry["trial_dir"])
        check = deferred_evaluator.precheck(self.project_root, trial_dir, retry_reason)  # el mismo del dialogo individual
        if not check["ok"]:
            self._batch_apply_decision(text_batch.record_precheck_block(self.project_root, batch_dir, manifest, entry, check["errors"]))
            return
        text_batch.mark_evaluating(manifest, entry)
        self._batch_save()
        self._batch_evaluating_dir = trial_dir
        if not self._start_deferred_evaluation(trial_dir, retry_reason, None):
            self._batch_evaluating_dir = None
            entry["status"] = text_batch.ENTRY_BLOCKED
            text_batch.pause(manifest, text_batch.PAUSE_BLOCKED, "no se pudo iniciar la evaluacion (operacion TIA en curso)")
            self._batch_save()

    def _batch_on_evaluation_finished(self) -> None:
        state = getattr(self, "_text_batch", None)
        if not state:
            return
        manifest = state["manifest"]
        entry = next((e for e in manifest["ordered_trial_plan"] if e["index"] == state.get("current_index")), None)
        if entry is None:
            return
        self._batch_apply_decision(text_batch.record_trial_result(self.project_root, state["dir"], manifest, entry))

    def _batch_finish_pause(self) -> None:
        manifest = self._text_batch["manifest"]
        if manifest.pop("stop_requested", False):
            text_batch.cancel(manifest, "detenido por el usuario tras el ensayo actual")
        else:
            text_batch.pause(manifest, text_batch.PAUSE_USER, "pausa solicitada por el usuario")
        self._batch_save()

    def _batch_apply_decision(self, decision: str) -> None:
        manifest = self._text_batch["manifest"]
        if decision == text_batch.DECISION_PAUSE and manifest.pop("stop_requested", False):
            text_batch.cancel(manifest, "detenido por el usuario tras el ensayo actual")
        self._batch_save()
        self._log(f"[BATCH] {manifest['batch_id']}: {decision} · {manifest['status']}"
                  + (f" ({manifest.get('pause_reason')}: {manifest.get('pause_detail')})" if manifest["status"] == text_batch.STATUS_PAUSED else ""))
        if decision == text_batch.DECISION_CONTINUE and manifest["status"] == text_batch.STATUS_RUNNING:
            self.after(self.BATCH_STEP_DELAY_MS, self._batch_run_next)
        elif decision == text_batch.DECISION_PAUSE:
            self._schedule_batch_automatic_retry()

    def _cancel_batch_automatic_retry(self, detail: str) -> None:
        state = getattr(self, '_text_batch', None)
        if not state:
            return
        timer = state.pop('retry_after_id', None)
        if timer is not None:
            self.after_cancel(timer)
        pending = state['manifest'].pop('automatic_retry_pending', None)
        if pending:
            text_batch._event(state['manifest'], 'AUTO_RETRY_CANCELLED', detail)

    def _schedule_batch_automatic_retry(self) -> None:
        from trial_experiments import batch_retry
        state = self._text_batch
        manifest = state['manifest']
        entry = text_batch.next_entry(manifest)
        if entry is None or not entry.get('trial_dir'):
            return
        try:
            record = trial_model.load_trial(Path(entry['trial_dir']))
        except (OSError, ValueError):
            return  # falta evidencia: nunca inferir que es un fallo recuperable
        pending = batch_retry.reserve(manifest, record)
        if pending is None:
            return
        self._batch_save()  # persistir motivo y presupuesto ANTES del temporizador
        self._log(f"[BATCH] {pending['reason']}; espera {pending['delay_ms'] / 1000:g} s.")

        def retry() -> None:
            if getattr(self, '_text_batch', None) is not state:
                return
            state.pop('retry_after_id', None)
            if manifest.get('automatic_retry_pending') != pending:
                return
            manifest.pop('automatic_retry_pending')
            self._batch_save()
            current = text_batch.next_entry(manifest)
            if (manifest['status'] != text_batch.STATUS_PAUSED
                    or manifest.get('pause_reason') != text_batch.PAUSE_INFRASTRUCTURE
                    or manifest.get('pause_requested') or manifest.get('stop_requested')
                    or current is None or current['index'] != pending['index']
                    or current.get('trial_id') != pending['trial_id']):
                return
            outcome = self.retry_text_batch_trial(pending['reason'])
            if not outcome['ok']:
                self._log('[BATCH] Reintento automático no iniciado; lote pausado: ' + '; '.join(outcome['errors']))

        state['retry_after_id'] = self.after(pending['delay_ms'], retry)

    def open_text_batch_dialog(self, input_mode: str = trial_model.INPUT_MODE_TEXT) -> "TextBatchDialog":
        dialog = getattr(self, "_text_batch_dialog", None)
        open_manifest = self._load_open_text_batch()
        if open_manifest is not None:
            input_mode = open_manifest.get("input_mode") or trial_model.INPUT_MODE_TEXT  # un solo lote abierto a la vez
        if dialog is not None:
            try:
                if dialog.input_mode == input_mode:
                    dialog.lift()
                    dialog.refresh()
                    return dialog
                dialog.destroy()
            except tk.TclError:
                pass
        self._text_batch_dialog = TextBatchDialog(self, input_mode)
        return self._text_batch_dialog

    def open_audio_corpus_dialog(self) -> "AudioCorpusDialog":
        return AudioCorpusDialog(self, self._selected_phase())

    def _announce_open_text_batch(self) -> None:
        """Al abrir la aplicacion: un lote incompleto se anuncia (nunca se reanuda solo)."""
        try:
            manifest = self._load_open_text_batch()
        except (OSError, ValueError):
            return
        self._refresh_text_batch_button()
        if manifest is not None:
            entry = text_batch.next_entry(manifest)
            self._log(f"[BATCH] LOTE TEXT INCOMPLETO {manifest['batch_id']}: {manifest.get('completed_trials', 0)} / "
                      f"{manifest['total_trials']} completados; siguiente {text_batch.entry_label(entry)}. "
                      f"Use EJECUTAR LOTE {manifest.get('input_mode') or 'TEXT'}.")

    def _refresh_text_batch_button(self) -> None:
        manifest = self._text_batch_manifest()
        open_mode = (manifest.get("input_mode") or trial_model.INPUT_MODE_TEXT) \
            if manifest and manifest.get("status") in text_batch.OPEN_STATUSES else None
        for mode, attribute in ((trial_model.INPUT_MODE_TEXT, "text_batch_button"), (trial_model.INPUT_MODE_VOICE_CLEAN, "voice_clean_batch_button"),
                                (trial_model.INPUT_MODE_VOICE_NOISE, "voice_noise_batch_button")):
            button = getattr(self, attribute, None)
            if button is None:
                continue
            if open_mode == mode:
                button.configure(text=f"LOTE {mode} ({manifest.get('completed_trials', 0)}/{manifest['total_trials']}) · {manifest['status']}")
            else:
                button.configure(text=f"EJECUTAR LOTE {mode}")

    def _refresh_text_batch_dialog(self) -> None:
        self._refresh_text_batch_button()
        dialog = getattr(self, "_text_batch_dialog", None)
        if dialog is not None:
            try:
                dialog.refresh()
            except tk.TclError:
                self._text_batch_dialog = None

    def text_batch_progress_lines(self) -> list[str]:
        """Progreso del lote; las etapas del ensayo actual salen de trial_stage_summary (fuente unica)."""
        manifest = self._text_batch_manifest()
        if not manifest:
            return ["No hay lote abierto."]
        state = text_batch.progress(manifest)
        entry = text_batch.next_entry(manifest)
        mode = manifest.get("input_mode") or trial_model.INPUT_MODE_TEXT
        title = {text_batch.STATUS_RUNNING: f"LOTE {mode} EN CURSO", text_batch.STATUS_CREATED: f"LOTE {mode} CREADO"}.get(manifest["status"])
        if manifest["status"] == text_batch.STATUS_PAUSED:
            title = ("LOTE PAUSADO POR INFRASTRUCTURE_ERROR" if manifest.get("pause_reason") == text_batch.PAUSE_INFRASTRUCTURE
                     else f"LOTE {mode} PAUSADO")
        if manifest["status"] in (text_batch.STATUS_COMPLETED, text_batch.STATUS_CANCELLED):
            return text_batch.final_report_lines(manifest)
        lines = [title or manifest["status"], f"{manifest['batch_id']} · {manifest['phase']}", "",
                 f"Completados: {state['completed']} / {state['total']}  ·  PASS {state['pass']} · FAIL {state['fail']} · "
                 f"REVIEW {state['review']} · INFRA {state['infrastructure_error']} · No evaluables {state['not_evaluable']}"]
        if manifest.get("started_at"):
            elapsed = int((datetime.now() - datetime.fromisoformat(manifest["started_at"])).total_seconds())
            lines.append(f"Tiempo del lote: {elapsed // 3600:d}h {elapsed % 3600 // 60:02d}m {elapsed % 60:02d}s")
        if manifest["status"] == text_batch.STATUS_PAUSED:
            lines += ["", f"Motivo: {manifest.get('pause_reason')}", f"Detalle: {manifest.get('pause_detail') or '-'}"]
        pending_retry = manifest.get('automatic_retry_pending')
        if pending_retry:
            lines += [f"Reintento automático {pending_retry['number']}: espera {pending_retry['delay_ms'] / 1000:g} s.",
                      'Puede pausar o detener el lote durante la espera.']
        if entry is not None:
            lines += ["", f"Ensayo actual: {entry['index'] + 1} / {manifest['total_trials']}", f"{text_batch.entry_label(entry)}  [{entry['status']}]",
                      f"Trial: {entry.get('trial_id') or '-'}"]
            if mode != trial_model.INPUT_MODE_TEXT:
                try:
                    lines += [f"Comando: {entry.get('reference_text') or '-'}"] + self._cell_audio_lines(
                        manifest["phase"], entry["case_id"], entry["variant_id"], mode)
                except (OSError, ValueError, KeyError) as error:
                    lines.append(f"Corpus de audio no legible: {error}")
            if entry.get("started_at") and entry["status"] in (text_batch.ENTRY_GENERATING, text_batch.ENTRY_EVALUATING):
                seconds = int((datetime.now() - datetime.fromisoformat(entry["started_at"])).total_seconds())
                lines.append(f"Tiempo del ensayo: {seconds // 60:d}m {seconds % 60:02d}s")
            if entry.get("trial_dir") and (Path(entry["trial_dir"]) / trial_model.TRIAL_FILENAME).exists():
                lines += [""] + [f"{label:<16}{value}" for label, value in
                                 deferred_evaluator.verdict_table(trial_model.load_trial(Path(entry["trial_dir"])))]
        return lines

    def _experiment_asr(self, audio_path: Path) -> dict[str, Any]:
        """ASR del producto sobre el audio de la modalidad; la validez tecnica ya la decidio el protocolo."""
        return self.speech_recognizer.transcribe_audio(Path(audio_path), enforce_quality_checks=False)

    def _capture_voice(self, case_id: str, variant_id: str, reference_text: str) -> dict[str, Any] | None:
        dialog = VoiceCaptureDialog(self, case_id, variant_id, reference_text)
        dialog.transient(self)
        self.wait_window(dialog)
        return dialog.result

    def _repeat_info(self, case_id: str, variant_id: str, input_mode: str, phase: str,
                     batch_reason: str | None = None) -> dict[str, Any] | None:
        """Repetir una celda nunca borra el resultado anterior: exige motivo y enlaza el ensayo previo."""
        previous = [row for row in deferred_evaluator.list_trials(self.project_root, (phase,))
                    if row["case_id"] == case_id and row["variant_id"] == variant_id and row["input_mode"] == input_mode]
        campaign = experimental_design.campaign_reference(self.project_root, phase)
        if campaign:
            previous = [row for row in previous if row.get('campaign_id') == campaign['campaign_id']]
        if not previous:
            return {}
        last = sorted(previous, key=lambda r: (r.get("created_at") or "", r["trial_id"]))[-1]
        if batch_reason:  # lote TEXT: el motivo lo aporta el lote (desatendido)
            return {"repeat_of_trial_id": last["trial_id"], "repeat_reason": batch_reason}
        reason = simpledialog.askstring(
            "Repetir ensayo",
            f"Ya existe {len(previous)} ensayo(s) para {case_id} {variant_id} {input_mode} ({last['trial_id']}).\n"
            "El anterior se conserva. Motivo de la repeticion:", parent=self)
        if not reason or not reason.strip():
            return None
        return {"repeat_of_trial_id": last["trial_id"], "repeat_reason": reason.strip()}

    def run_complete_trial(self, batch_trial: dict[str, Any] | None = None) -> Path | None:
        """
        EJECUTAR ENSAYO COMPLETO: entrada (TEXT / VOICE_CLEAN / VOICE_NOISE) -> MISMO pipeline ->
        generacion -> copia del MASTER -> TIA -> Archive .zap18 verificado -> PLCSIM -> Oracle.
        Un clic = un ensayo; nunca inicia el siguiente.

        `batch_trial` (solo LOTE TEXT, docs/text_batch_execution.md): el MISMO flujo, con tres diferencias
        de interaccion: el motivo de repeticion lo aporta el lote, el lote recibe el ensayo creado
        (on_started) y, en lugar de abrir el dialogo individual, recibe el fin de la generacion
        (on_generated) para lanzar la MISMA evaluacion diferida.
        """
        if batch_trial is None and self._text_batch_running():
            messagebox.showwarning("Ejecutar ensayo completo", "Hay un LOTE TEXT en curso: pauselo o detengalo primero.")
            return None
        if self._tia_busy() or self._voice_worker_active:
            messagebox.showwarning("Ejecutar ensayo completo", "Espere a que termine la operacion en curso.")
            return None
        profile = self._experiment_profiles_by_case.get(self.experiment_case_var.get())
        if profile is None:
            messagebox.showwarning("Ejecutar ensayo completo", "Seleccione un caso valido.")
            return None
        phase, input_mode = self._selected_phase(), self._selected_input_mode()
        case_id, variant_id = profile.get("case_id", ""), self.experiment_variant_var.get()
        if phase == trial_model.PHASE_FORMAL:
            try:
                experimental_design.require_formal_cases(self.project_root, [case_id])
            except ValueError as error:
                messagebox.showwarning('Ejecutar ensayo completo', str(error))
                return None
        environment = deferred_evaluator.environment_precheck(self.project_root, phase)
        if not environment["ok"]:
            messagebox.showwarning("Ejecutar ensayo completo", "No se inicia el ensayo:\n\n" + "\n".join(environment["errors"][:8]))
            return None
        reference_text = benchmark_catalog.get_case(self.project_root, case_id)["variants"][variant_id]
        speaker_id = self.experiment_speaker_var.get().strip()
        capture = None
        stimulus: dict[str, Any] | None = None
        if input_mode != trial_model.INPUT_MODE_TEXT:
            speaker_error = voice_protocol.validate_speaker_id(speaker_id)
            if speaker_error:
                messagebox.showwarning("Ejecutar ensayo completo", speaker_error)
                return None
            # Estimulo PAREADO del corpus de audio (una locucion por celda; VOICE_NOISE nunca graba).
            stimulus = self._corpus_stimulus(phase, case_id, variant_id, input_mode, reference_text, speaker_id, batch_trial)
            if stimulus is None:
                return None
        repeat = self._repeat_info(case_id, variant_id, input_mode, phase,
                                   batch_reason=(batch_trial or {}).get("repeat_reason"))
        if repeat is None:
            return None

        self.command_textbox.delete("1.0", "end")
        self.command_textbox.insert("1.0", reference_text)
        if not self.start_trial():
            self._discard_capture(capture)
            return None
        info = (self.active_trial or {}).get("new_trial") or {}
        new_dir = Path(info["dir"]) if info.get("dir") else None
        started_perf = info.get("started_perf")
        if batch_trial is not None and new_dir is not None:
            batch_trial["on_started"](new_dir)  # el lote persiste el ensayo ANTES del LLM (sobrevive a una caida)
        self.start_trial_button.configure(state="disabled")
        try:
            patch: dict[str, Any] = {"trial_flow": "COMPLETE", "reference_text": reference_text,
                                     **({"batch_id": batch_trial["batch_id"], "batch_index": batch_trial["index"]} if batch_trial else {}),
                                     "reference_text_hash": voice_protocol.sha256_text(reference_text),
                                     "speaker_id": speaker_id if input_mode != trial_model.INPUT_MODE_TEXT else None, **repeat}
            if input_mode == trial_model.INPUT_MODE_TEXT:
                effective = reference_text
            else:
                self._log(f"[VOICE] {input_mode}: audio congelado -> ASR (sin correccion humana)")
                result = voice_protocol.prepare_voice_input(self.project_root, new_dir, input_mode, reference_text,
                                                            self._experiment_asr, stimulus=stimulus)
                voice = result["voice"]
                patch.update({key: voice.get(key) for key in (
                    "audio_condition", "audio_source_path", "audio_sha256", "paired_audio_sha256", "audio_source_clean_sha256",
                    "audio_manifest_sha256", "target_snr_db", "measured_snr_db")})
                patch.update({"voice": voice, "asr": {"audio_reference": voice.get("asr_audio") or voice_protocol.CLEAN_AUDIO_FILENAME,
                                                      "asr_transcript": voice.get("asr_transcript_raw"), "wer": voice.get("wer"),
                                                      "noise_profile": voice.get("noise_profile_id"), "snr_db": voice.get("snr_db")},
                              "paired_clean_trial_id": voice.get("paired_clean_trial_id"),
                              "paired_clean_audio_hash": voice.get("paired_clean_audio_hash")})
                if not result["ok"]:
                    failure = result["failure"]
                    patch["failure_stage"] = failure["stage"]
                    self._update_new_trial(patch)
                    self._finalize_new_trial(trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR if failure["infrastructure"]
                                             else trial_model.FINAL_STATUS_FAIL, [failure["error"]])
                    deferred_evaluator.finalize_generation(self.project_root, new_dir, None)
                    self._log(f"[VOICE] {failure['error']}")
                    if batch_trial is not None:
                        self.after(0, lambda: batch_trial["on_generated"](new_dir, deferred_evaluator.GENERATION_FAILED))
                    else:
                        self.show_trial_detail(new_dir)
                    return new_dir
                effective = result["effective_input_text"]
                self._log(f"[VOICE] Transcripcion congelada: {effective!r} · WER {voice.get('wer')}")
            patch.update({"input_text": effective, "effective_input_text": effective,
                          "effective_input_text_hash": voice_protocol.sha256_text(effective)})
            self._update_new_trial(patch)
            self.command_textbox.delete("1.0", "end")
            self.command_textbox.insert("1.0", effective)  # el MISMO pipeline para las tres modalidades

            ok = self.process_command() and self.generate_package()
            package_dir = (self.active_trial or {}).get("package_dir")
            if self.active_trial:
                self._discard_trial_working_map(None)
            if started_perf is not None:
                self._update_new_trial({"timing": {"generation_total_ms": int(round((time.perf_counter() - started_perf) * 1000))}})
            record = deferred_evaluator.finalize_generation(self.project_root, new_dir, Path(package_dir) if ok and package_dir else None)
            generation = (record.get("generation") or {}).get("status")
            self._log(f"[EXPERIMENT] {record.get('trial_id')}: generacion {generation}")
            if batch_trial is not None:
                # Lote: la evaluacion (la misma) la lanza el lote despues de cerrar este ensayo (finally).
                self.after(0, lambda: batch_trial["on_generated"](new_dir, generation))
            elif generation == deferred_evaluator.GENERATION_SUCCESS:
                self.active_trial = None
                self._open_deferred_dialog(new_dir, retry=False, autostart=True)
            else:
                self.show_trial_detail(new_dir)
            return new_dir
        finally:
            self._discard_capture(capture)
            self.active_trial = None
            self.manual_result_frame.grid_remove()
            self.start_trial_button.configure(state="normal")
            self._refresh_generated_trials()
            self._refresh_voice_panel()

    def _corpus_stimulus(self, phase: str, case_id: str, variant_id: str, input_mode: str, reference_text: str,
                         speaker_id: str, batch_trial: dict[str, Any] | None) -> dict[str, Any] | None:
        """
        VOICE_CLEAN: si la celda no tiene locucion, se graba UNA vez y se congela clean + noisy (antes del ASR); si ya existe
        (incluido un reintento) se reutiliza EXACTAMENTE el mismo WAV, nunca se regraba. VOICE_NOISE: nunca abre el
        microfono; exige la pareja congelada e integra (si falta, se aborta antes del ASR/LLM).
        """
        notify = (batch_trial or {}).get("notify") or (lambda title, text: messagebox.showwarning(title, text))
        try:
            if input_mode == trial_model.INPUT_MODE_VOICE_CLEAN:
                entry = formal_audio.cell_entry(formal_audio.load_corpus(self.project_root, phase), case_id, variant_id)
                if entry["state"] == formal_audio.STATE_NOT_RECORDED:
                    capture = (batch_trial or {}).get("capture") or self._capture_voice(case_id, variant_id, reference_text)
                    if capture is None or not capture.get("path"):
                        return None  # cancelado antes de grabar: no hay resultado experimental
                    try:
                        formal_audio.register_capture(self.project_root, phase, case_id, variant_id, Path(capture["path"]),
                                                      speaker_id, capture)
                    finally:
                        self._discard_capture(capture)
                    self._log(f"[AUDIO] {case_id} {variant_id}: clean y par noisy congelados (antes del ASR).")
                condition = formal_audio.CONDITION_CLEAN
            else:
                condition = formal_audio.CONDITION_NOISE
            return {**formal_audio.stimulus(self.project_root, phase, case_id, variant_id, condition), "phase": phase}
        except formal_audio.FormalAudioError as error:
            notify("Estimulo de voz", f"PRECHECK ABORT ({input_mode} {case_id} {variant_id}): {error}")
            self._log(f"[AUDIO] PRECHECK ABORT: {error}")
            return None

    def _discard_capture(self, capture: dict[str, Any] | None) -> None:
        """La grabacion temporal se descarta SOLO despues de copiarse a la evidencia del ensayo."""
        if capture and capture.get("path"):
            self.speech_recognizer.discard_audio(Path(capture["path"]))

    def show_trial_detail(self, trial_dir: Path) -> None:
        record = trial_model.load_trial(Path(trial_dir))
        lines = [f"{record.get('case_id')} · {record.get('variant_id')} · {record.get('input_mode')}",
                 f"Estado: {deferred_evaluator.trial_status_label(record)}", ""]
        lines += [f"{label}: {value}" for label, value in deferred_evaluator.verdict_table(record)]
        voice = record.get("voice") or {}
        if voice:
            lines += ["", f"Referencia: {voice.get('reference_text')}",
                      f"Transcripcion ASR (congelada, solo lectura): {voice.get('asr_transcript_raw')}",
                      f"S/D/I: {voice.get('substitutions')}/{voice.get('deletions')}/{voice.get('insertions')} · "
                      f"latencia ASR {voice.get('asr_latency_ms')} ms"]
        lines += ["", f"Errores: {' | '.join(record.get('errors') or []) or '-'}", f"Carpeta: {trial_dir}"]
        messagebox.showinfo("Detalle del ensayo", "\n".join(lines))

    def _refresh_voice_panel(self) -> None:
        panel = getattr(self, "voice_panel", None)
        if panel is None:
            return
        input_mode, phase = self._selected_input_mode(), self._selected_phase()
        for widget in (self.capture_voice_button, self.noise_profile_button, self.snr_button):
            widget.grid_remove()
        if input_mode == trial_model.INPUT_MODE_TEXT:
            panel.grid_remove()  # TEXT: sin controles de audio
            return
        panel.grid()
        profile = self._experiment_profiles_by_case.get(self.experiment_case_var.get()) or {}
        case_id, variant_id = profile.get("case_id", ""), self.experiment_variant_var.get()
        lines = [f"Speaker (pseudonimo): {self.experiment_speaker_var.get().strip() or '-'}"]
        if input_mode == trial_model.INPUT_MODE_VOICE_CLEAN:
            device = self.speech_recognizer.get_input_device_info()
            lines.insert(0, f"Microfono: {device.get('name') or device.get('error') or '-'}")
        try:
            lines += self._cell_audio_lines(phase, case_id, variant_id, input_mode) if case_id else []
        except (OSError, ValueError, KeyError) as error:
            lines.append(f"Corpus de audio no legible: {error}")
        if input_mode == trial_model.INPUT_MODE_VOICE_CLEAN:
            lines.append("Celda sin grabar: al ejecutar se graba UNA vez y se congela clean + noisy antes del ASR.")
            self.capture_voice_button.grid(row=1, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="ew")
        else:
            # VOICE_NOISE nunca graba: usa el par noisy congelado del MISMO clean (sin boton de grabar).
            lines.append("VOICE_NOISE: sin grabacion; estimulo noisy congelado de la celda.")
            if phase != trial_model.PHASE_FORMAL:
                self.noise_profile_button.grid(row=1, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="ew")
        self.voice_panel_var.set("\n".join(lines))

    def _cell_audio_lines(self, phase: str, case_id: str, variant_id: str, input_mode: str) -> list[str]:
        """Estado del estimulo pareado de la celda (corpus de audio): fuente unica para panel de voz y lotes."""
        corpus = formal_audio.load_corpus(self.project_root, phase)
        cell = formal_audio.cell_entry(corpus, case_id, variant_id)
        state = cell["state"]
        snr = formal_audio.load_config(self.project_root)["target_snr_db"]
        master = formal_audio.noise_master_status(self.project_root, phase)
        clean = {formal_audio.STATE_NOT_RECORDED: "NOT RECORDED", formal_audio.STATE_CLEAN_READY: "READY",
                 formal_audio.STATE_PAIR_READY: "READY"}.get(state, "USED")
        pair = "READY" if state in (formal_audio.STATE_PAIR_READY, *formal_audio.USED_STATES) else "NOT READY"
        lines = [f"AUDIO NOISE MASTER: {'READY' if master['ready'] else 'MISSING'}"]
        if input_mode == trial_model.INPUT_MODE_VOICE_CLEAN:
            lines += [f"AUDIO CLEAN: {clean}", f"AUDIO NOISE PAIR: {pair}", f"SNR: {snr} dB"]
        else:
            source = f"{case_id}_{variant_id} {cell['clean_sha256'][:12]}" if cell.get("clean_sha256") else "NO DISPONIBLE (AUDIO_PAIR_MISSING)"
            lines += [f"SOURCE CLEAN: {source}", f"AUDIO NOISE PAIR: {pair}", f"SNR: {snr} dB"
                      + (f" (medido {cell['measured_snr_db']} dB)" if cell.get("measured_snr_db") is not None else "")]
        return lines

    def select_dev_noise_profile(self) -> None:
        if self._selected_phase() == trial_model.PHASE_FORMAL:
            return
        chosen = filedialog.askopenfilename(title="Perfil de ruido (WAV PCM16 mono, mismo sample rate)", filetypes=[("WAV", "*.wav")])
        if chosen:
            current = voice_protocol.load_dev_config(self.project_root)
            voice_protocol.save_dev_config(self.project_root, chosen, current.get("snr_db"))
            self._refresh_voice_panel()

    def select_dev_snr(self) -> None:
        if self._selected_phase() == trial_model.PHASE_FORMAL:
            return
        current = voice_protocol.load_dev_config(self.project_root)
        value = simpledialog.askfloat("SNR (DEVELOPMENT)", "SNR en dB para VOICE_NOISE de desarrollo:", parent=self,
                                      initialvalue=current.get("snr_db"))
        if value is not None:
            voice_protocol.save_dev_config(self.project_root, current.get("noise_profile_path"), value)
            self._refresh_voice_panel()


    def run_experiment_trial(self) -> None:
        """
        Pipeline inmediato legacy (compila/descarga desde el proyecto Normal). Solo con
        legacy_immediate_experiment_pipeline=true: por defecto Experimentacion usa GENERAR/EVALUAR.
        """
        if self._experiment_touches_normal_project():
            messagebox.showwarning("Ejecutar ensayo", "EXPERIMENT_MODE_NEVER_MODIFIES_NORMAL_PROJECT: use GENERAR ENSAYO.")
            return
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
            started_perf = self.active_trial.get("new_trial", {}).get("started_perf")
            self._update_new_trial({
                "command_text": command_text,
                "transcript": transcript or None,
                **({'product_engine': semantic_output['product_engine']} if semantic_output.get('product_engine') else {}),
                "timing": {"semantic_ms": int(round((time.perf_counter() - started_perf) * 1000)) if started_perf is not None else None},
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
        self, command_text: str, semantic_output: dict[str, Any], error_code: str = "E2", failure_stage: str = "parse"
    ) -> None:
        if not self.active_trial:
            return
        trial_id = self.active_trial.get("trial_id", "")
        try:
            started_perf = self.active_trial.get("new_trial", {}).get("started_perf")
            self._update_new_trial({
                "command_text": command_text,
                "stages": {"semantic_success": False},
                **({'product_engine': semantic_output['product_engine']} if semantic_output.get('product_engine') else {}),
                "failure_stage": failure_stage,
                "timing": {"semantic_ms": int(round((time.perf_counter() - started_perf) * 1000)) if started_perf is not None else None},
            })
            new_dir = self._new_trial_dir()
            if new_dir is not None:
                trial_model.write_json_artifact(new_dir, "semantic_output.json", semantic_output)
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

    def _verify_trial_program_resources(self, package_dir: Any) -> dict[str, Any] | None:
        """
        Benchmark v2: cada recurso externo del programa debe tener binding real en el working map
        congelado (sin ghost resources, tipos compatibles, LOCKED intactos). None si no aplica.
        """
        info = (self.active_trial or {}).get("new_trial") or {}
        snapshot_path = (info.get("io_map") or {}).get("snapshot_path")
        variables_path = Path(package_dir) / "variables.json" if package_dir else None
        if not snapshot_path or variables_path is None or not variables_path.exists() or not Path(snapshot_path).exists():
            return None
        return resource_policy.verify_program_resources(
            load_json_file(variables_path), json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        )

    def _capture_trial_generation_result(self, combined_results: dict[str, dict[str, Any]]) -> bool | None:
        """False si el ensayo quedo cerrado aqui (verificacion o bindings): no se compila."""
        if not self.active_trial:
            return None
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
                "state": "AWAITING_MANUAL_RESULT",
                "package_dir": saved_paths.get("package_dir")
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
            resource_check = self._verify_trial_program_resources(saved_paths.get("package_dir")) if is_valid else None
            if resource_check is not None:
                self._update_new_trial({"resource_check": resource_check})
                if not resource_check["success"]:
                    is_valid = False
                    errors = [f"{item['code']}: {item['detail']}" for item in resource_check["errors"]]
                    self._update_new_trial({"failure_stage": resource_policy.STAGE_RESOURCE_BINDING})
                    self._log("[EXPERIMENT IO] Programa con recursos sin binding real: " + "; ".join(errors))
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
            return is_valid
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo registrar el resultado de generacion del ensayo: {error}")
            return None

    def _capture_trial_exception(self, error_text: str, stage: str) -> None:
        if not self.active_trial:
            return
        trial_id = self.active_trial.get("trial_id", "")
        try:
            # Taxonomia v2: una excepcion de generacion es CODEGEN_FAILURE (fallo del sistema); una de
            # interpretacion solo es INFRASTRUCTURE_ERROR si delata al servicio externo (API/red).
            external = any(marker in str(error_text).lower() for marker in _EXTERNAL_SERVICE_ERROR_MARKERS)
            final_status = (
                trial_model.FINAL_STATUS_INFRASTRUCTURE_ERROR
                if stage == "parse" and external
                else trial_model.FINAL_STATUS_FAIL
            )
            patch: dict[str, Any] = {"failure_stage": stage}
            if stage == "parse" and not external:
                patch["stages"] = {"semantic_success": False}
            self._update_new_trial(patch)
            self._finalize_new_trial(final_status, [f"{stage}: {error_text}"])
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
        self._pipeline_running=True
        self.execute_command_button.configure(state="disabled")
        self.start_trial_button.configure(state="disabled")
        tia_started = False
        try:
            command_text = self.command_textbox.get("1.0", "end").strip()
            self._pipeline_stage = "precheck"
            precheck_ok, precheck_message = self._run_pipeline_precheck(command_text)
            if not precheck_ok:
                self._set_status("Error")
                self._log(f"Ejecucion detenida en verificacion previa: {precheck_message}")
                if self.active_trial:
                    self._cancel_active_trial(f"Verificacion previa fallida: {precheck_message}")
                messagebox.showwarning("Ejecutar comando", precheck_message)
                return False

            self._pipeline_stage = "semantic"
            if not self.process_command():
                return False
            self._pipeline_stage = "generation"
            if not self.generate_package():
                return False
            self._pipeline_stage = "compile"
            self.validate_latest_package_in_tia()
            tia_started = self._tia_worker_active
            return True
        finally:
            self._pipeline_running=False
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

    def _normal_map_transactions_apply(self) -> bool:
        """Transacciones de mapa: solo Modo Normal sin ensayo (Experimentacion usa su working map congelado)."""
        return self.work_mode_var.get() == "Normal" and self.active_trial is None and self._trial_io() is None

    @staticmethod
    def _file_sha256(path: Path) -> str | None:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None

    def _prepare_provisional_allocation(
        self, semantic_output: dict[str, Any], intents_catalog: dict[str, Any], safety_rules: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Aplica las propuestas del IOAllocator a una COPIA del mapa (nunca al archivo ni a la tabla de la GUI) y
        revalida contra ella; la puerta semantica de process_command juzga ese resultado y, si falla, la descarta.
        Esa copia alimenta IR/SCL; el mapa real cambia solo en el commit, con el programa verificado.
        """
        proposals = [p for p in (semantic_output.get("semantic_validation") or {}).get("io_assignment_proposals") or []
                     if not p.get("blocked")]
        if not proposals:
            return semantic_output
        block_message = block_map_config_message(self.active_trial, self.active_profile_id)
        if block_message:
            self._log("Asignacion de recursos rechazada: perfil experimental activo.")
            messagebox.showwarning("Configuracion de mapa", block_message)
            return None
        base_map = self._program_base_map()  # inventario COMPLETO (con los AUTO liberados si es un programa nuevo)
        try:
            semantic_output, provisional_map, history_entries = product_engine.resolve_product_assignments(
                semantic_output, base_map, proposals, intents_catalog, safety_rules)
        except ValueError as error:
            self._log(normal_interaction.trace("NORMAL_IO_ROLLBACK", reason=str(error)))
            messagebox.showerror("Recursos del programa", f"No se pudieron asignar los recursos.\n\n{error}")
            return None
        revalidated = semantic_output['semantic_validation']
        if not revalidated.get("is_valid", False):
            return semantic_output  # no aceptar nuevas propuestas como si ya estuvieran aplicadas
        self._open_map_transaction(provisional_map, history_entries, proposals, intents_catalog, safety_rules)
        self.pending_semantic_output = semantic_output
        self._last_map_config_summary = ("Asignacion provisional de recursos (se aplica al mapa solo si el programa se genera):"
                                         + "".join(f"\n{p.get('address')} -> {p.get('proposed_name')}" for p in proposals))
        self._log(normal_interaction.trace("NORMAL_IO_PROVISIONAL", status="Asignacion provisional de recursos",
                                           assignments=", ".join(f"{p.get('proposed_name')}@{p.get('address')} "
                                                                 f"({(p.get('current_state') or '').lower()})" for p in proposals)))
        return semantic_output

    def _program_metadata_allowed(self) -> bool:
        """Bindings/registro de programa solo en mapas WORKING locales (nunca en un mapa versionado/congelado)."""
        return is_working_map_path(Path(self.io_map_path))

    def _prepare_program_scope(self, command_text: str, io_map: dict[str, Any]) -> dict[str, Any]:
        """
        NUEVO programa: copia de trabajo con los ASSIGNED automaticos del programa anterior devueltos al pool
        (LOCKED/MANUAL/persistent y toda la configuracion fisica se conservan). AMPLIACION: el mapa tal cual y el
        programa actual como contexto del interprete. Nada se escribe hasta el commit.
        """
        current = (load_json_file(self.io_map_path).get("metadata") or {}).get(program_bindings.CURRENT_PROGRAM_KEY) \
            if Path(self.io_map_path).is_file() else None
        scope, reason = program_bindings.classify_program_scope(command_text, current)
        context: dict[str, Any] = {"scope": scope, "current_program": current, "released": [], "working_map": None,
                                   "llm_context": program_bindings.llm_program_context(current)
                                   if scope == program_bindings.SCOPE_EXTEND else None}
        working = io_map
        if scope == program_bindings.SCOPE_NEW:
            prepared = product_engine.prepare_product_map(io_map, scope=scope,
                previous_program_id=(current or {}).get('program_id'))
            working, context['released'] = prepared['io_map'], prepared['released']
        context["working_map"] = working
        self._normal_program_context = context
        self._log(normal_interaction.trace("NORMAL_PROGRAM_SCOPE", scope=scope, reason=reason,
                                           current_program=(current or {}).get("program_id"),
                                           released=", ".join(f"{r['address']}:{r['name']}" for r in context["released"])))
        return working

    def _program_base_map(self) -> dict[str, Any]:
        """Base de la asignacion: la copia de trabajo del alcance del programa (o el mapa completo del archivo)."""
        context = self._normal_program_context or {}
        if context.get("working_map") is not None:
            return copy.deepcopy(context["working_map"])
        return load_json_file(self.io_map_path)

    def _open_map_transaction(self, provisional_map: dict[str, Any], history_entries: list[dict[str, Any]],
                              proposals: list[dict[str, Any]], intents_catalog: dict[str, Any],
                              safety_rules: dict[str, Any]) -> None:
        self._pending_map_transaction = {
            "map_path": Path(self.io_map_path), "base_sha256": self._file_sha256(self.io_map_path),
            "map": provisional_map, "history_entries": history_entries, "proposals": proposals,
            "releases_previous": bool((self._normal_program_context or {}).get("released"))}
        self.pending_runtime_config = (provisional_map, intents_catalog, safety_rules)

    def _commit_pending_map_transaction(self) -> bool:
        """Programa generado y verificado: escribe la asignacion provisional en el mapa (si nadie lo cambio entretanto)."""
        transaction, self._pending_map_transaction = self._pending_map_transaction, None
        if transaction is None:
            return True
        if Path(transaction["map_path"]) != Path(self.io_map_path) or \
                self._file_sha256(transaction["map_path"]) != transaction["base_sha256"]:
            self._log(normal_interaction.trace("NORMAL_IO_ROLLBACK", reason="el mapa activo cambio durante la operacion"))
            messagebox.showwarning("Recursos del programa", "El mapa PLC cambió durante la operación; no se aplicaron "
                                   "las asignaciones. Repita el comando para generar un programa coherente con el mapa.")
            return False
        committed_map, metadata_patch = transaction["map"], None
        if self._program_metadata_allowed():
            from ir_builder import required_external_resources

            semantic = self.pending_semantic_output or {}
            used = required_external_resources(semantic, committed_map)
            manual = {p.get("proposed_name") for p in transaction["proposals"] if p.get("address_was_explicit")}
            context = self._normal_program_context or {}
            program_id = program_bindings.new_program_id()
            committed_map = program_bindings.stamp_program_bindings(committed_map, used, program_id, manual,
                strict_owner=True, previous_program_id=(context.get('current_program') or {}).get('program_id'),
                newly_assigned_names={p.get('proposed_name') for p in transaction['proposals']})
            metadata_patch = {program_bindings.CURRENT_PROGRAM_KEY: program_bindings.program_record(
                program_id, context.get("scope") or program_bindings.SCOPE_NEW, semantic, used)}
            self._log(normal_interaction.trace("NORMAL_PROGRAM_COMMIT", program_id=program_id, scope=context.get("scope"),
                                               resources=", ".join(used),
                                               released=", ".join(f"{r['address']}:{r['name']}" for r in context.get("released") or [])))
        save_plc_map(transaction["map_path"], committed_map["variables"], metadata_patch=metadata_patch,
                     history_entries=transaction["history_entries"])
        self.io_variables = load_io_map_variables(self.io_map_path)
        self._load_active_map_metadata_shadow()
        self._load_io_map_table()
        self._log(normal_interaction.trace("NORMAL_IO_COMMIT", status="Configuracion de mapa aplicada",
                                           assignments=", ".join(f"{p.get('proposed_name')}@{p.get('address')}"
                                                                 for p in transaction["proposals"])))
        self._persist_generated_functional_variables(transaction.get("functional_variables") or [])
        return True

    def _rollback_pending_map_transaction(self, reason: str, notify: bool = False) -> None:
        """Descarta la asignacion provisional: el mapa real nunca se toco (no hay nada que deshacer en disco)."""
        transaction, self._pending_map_transaction = getattr(self, "_pending_map_transaction", None), None
        if transaction is None:
            return
        self._log(normal_interaction.trace("NORMAL_IO_ROLLBACK", reason=reason, discarded=", ".join(
            f"{p.get('proposed_name')}@{p.get('address')}" for p in transaction["proposals"]),
            program_kept="programa y mapa anteriores intactos"))
        if notify and transaction["proposals"] or notify and transaction.get("releases_previous"):
            self._log(normal_interaction.ROLLBACK_MESSAGE)
            messagebox.showwarning("Mapa PLC", normal_interaction.ROLLBACK_MESSAGE)

    def _trace_normal_interpretation(self, semantic_output: dict[str, Any]) -> None:
        """Trazas NORMAL_* tras interpretar: semantica, inferencias, E/S requeridas y aclaracion resuelta."""
        validation = semantic_output.get("semantic_validation") or {}
        self._log(normal_interaction.trace("NORMAL_SEMANTIC_PARSE", **normal_interaction.semantic_trace_fields(semantic_output)))
        for inference in validation.get("inferences") or []:
            self._log(normal_interaction.trace("NORMAL_INFERENCES", **inference))
        for requested, resolved in (semantic_output.get("resource_bindings") or {}).items():
            self._log(normal_interaction.trace("NORMAL_RESOURCE_BINDING", role=requested, resolved_symbol=resolved,
                                               reason="funcion ya cubierta en el mapa: se reutiliza"))
        for assumption in semantic_output.get("assumptions") or []:
            if str(assumption).upper().startswith("INFERRED"):
                self._log(normal_interaction.trace("NORMAL_INFERENCES", provenance="INFERRED", reason=assumption))
        proposals = validation.get("io_assignment_proposals") or []
        if proposals:
            self._log(normal_interaction.trace(
                "NORMAL_RESOURCE_REQUIREMENTS",
                resolved=", ".join(f"{p.get('proposed_name')}->{p.get('address')}" for p in proposals if not p.get("blocked")),
                blocked=", ".join(str(p.get("proposed_name")) for p in proposals if p.get("blocked"))))
        # Las respuestas se marcan resueltas en el estado (los registros {question, answer} que recibe el
        # parser no se alteran) cuando la reinterpretacion ya no repite la pregunta.
        state = self._normal_clarification_state or {}
        history = state.get("history") or []
        resolved = state.setdefault("resolved", []) if state else []
        pending = [index for index in range(len(history)) if index not in resolved]
        question = semantic_output.get("clarification_question") or validation.get("clarification_question")
        if pending and not (question and normal_interaction.already_answered(question, [history[i] for i in pending])):
            for index in pending:
                resolved.append(index)
                self._log(normal_interaction.trace("NORMAL_CLARIFICATION_RESOLVED", question=history[index].get("question"),
                                                   answer=history[index].get("answer")))

    def _trace_normal_ir(self, project_ir: dict[str, Any]) -> None:
        metadata = project_ir.get("metadata") or {}
        internal = [variable.get("name") for variable in metadata.get("generated_internal_variables") or []]
        self._log(normal_interaction.trace("NORMAL_IR_BUILT", variables=len((project_ir.get("pou") or {}).get("variables") or []),
                                           test_cases=len(project_ir.get("test_cases") or [])))
        self._log(normal_interaction.trace("NORMAL_INTERNAL_RESOURCES", generated=", ".join(internal) or "ninguno",
                                           physical_address="ninguna (variables internas)"))

    def _report_normal_capability_gap(self, command_text: str, semantic_output: dict[str, Any], gap: dict[str, Any]) -> None:
        """Falta de hardware: el comando es valido pero el mapa no tiene canales compatibles. Nunca pregunta canales."""
        self._log(normal_interaction.trace("NORMAL_CAPABILITY_GAP", message=gap.get("message"),
                                           blocked=", ".join(str(n) for n in gap.get("blocked_resources") or [])))
        snapshot = self._build_unknown_snapshot(command_text, semantic_output, {
            "is_valid": False, "errors": [gap.get("message")], "warnings": []})
        self._restore_snapshot(snapshot)
        self._record_history(snapshot, platform="Sin plataforma", is_valid=False)
        self._set_status("Listo")
        messagebox.showwarning("Recursos de hardware insuficientes", normal_interaction.capability_gap_message(gap))

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
        if self.work_mode_var.get() == "Normal":
            shown, internal = normal_interaction.user_facing_errors(errors)
            for message in internal:
                self._log(f"[NORMAL] {normal_interaction.SYSTEM_CAPABILITY_GAP}: {message}")
            if not shown:
                messagebox.showinfo("Comando", normal_interaction.PRODUCT_CAPABILITY_GAP_MESSAGE)
                return
            messagebox.showerror("Comando", "No se pudo generar el programa:\n\n" + "\n".join(f"- {e}" for e in shown))
            return
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
        self._compiled_target_identity=None
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
        normal_mode = self.work_mode_var.get() == "Normal" and self.active_trial is None
        if normal_mode:
            state = self._normal_clarification_state or normal_interaction.new_state(command_text)
            self._normal_clarification_state = state
            decision = normal_interaction.classify_clarification(question, state["history"])
            self._log(normal_interaction.trace(
                "NORMAL_CLARIFICATION_REPEATED" if decision["action"] == "repeated" else "NORMAL_CLARIFICATION_REQUIRED",
                action=decision["action"], question=question))
            if decision["action"] != "ask":
                # Nunca se muestra al usuario una pregunta interna (catalogo/intencion/schema) ni se
                # repite una ya respondida: log de diagnostico + mensaje de producto.
                self._log(f"[NORMAL] {decision['reason']}")
                if self._normal_voice_flow is not None:
                    self._normal_voice_flow["clarification_requested"] = True
                    self._normal_voice_flow["clarification_pending"] = True  # no resuelta
                messagebox.showinfo("Comando", normal_interaction.PRODUCT_CAPABILITY_GAP_MESSAGE)
                return False
        if self._normal_voice_flow is not None:
            # Ejecucion Normal con descarga encadenada: el flujo se PAUSA antes de TIA/Descarga mientras
            # la aclaracion esta pendiente; una aclaracion respondida no impide la descarga posterior.
            self._normal_voice_flow["clarification_requested"] = True
            self._normal_voice_flow["clarification_pending"] = True
            self._set_normal_voice_stage("Semantica", "running")
        if self.active_trial:
            # Metrica secundaria (tasa de aclaracion): se registra siempre, se responda o no.
            self._update_new_trial({"clarification_requested": True, "clarification_question": question})
        dialog = ClarificationDialog(self, question)
        self.wait_window(dialog)
        answer = dialog.result
        if self.active_trial:
            self._update_new_trial({"clarification_answered": bool(answer)})
        if answer and self._normal_voice_flow is not None:
            self._normal_voice_flow["clarification_pending"] = False

        if not answer:
            self._log("Aclaracion cancelada por el usuario; el comando no se reprocesa.")
            if self.active_trial:
                self._capture_trial_parse_failure(command_text, semantic_output)
            return False

        self._log(f"Aclaracion registrada por el usuario: {answer!r}. Reprocesando el comando.")
        if normal_mode:
            # Aclaracion ESTRUCTURADA: se conserva el comando original y se agrega {pregunta, respuesta};
            # el comando NO se concatena con texto libre.
            state = self._normal_clarification_state
            state["history"].append({"question": question, "answer": str(answer).strip()})
            self.command_textbox.delete("1.0", "end")
            self.command_textbox.insert("1.0", state["original_command"])
            self._reprocessing_clarification = True
            try:
                return self.process_command()
            finally:
                self._reprocessing_clarification = False
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
                semantic_output, candidate, _ = product_engine.resolve_product_assignments(
                    semantic_output, io_map, to_apply, intents_catalog, safety_rules)
                if not semantic_output['semantic_validation'].get('is_valid'):
                    return semantic_output
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
                if self._program_metadata_allowed():
                    explicit = {p.get("address") for p in to_apply if p.get("address_was_explicit", True)}
                    for entry in updated_map["variables"]:
                        if entry.get("location") in explicit and entry.get("state") == "ASSIGNED":
                            entry["assignment_source"] = program_bindings.SOURCE_MANUAL
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
        summary_parts = ["Configuración de mapa aplicada." if trial_info is None else "CONFIGURACION AUTOMATICA"]
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
        if self.work_mode_var.get() == "Normal" and trial_info is None:
            self._log(normal_interaction.trace(
                "NORMAL_IO_COMMIT",
                reused=", ".join(f"{p['proposed_name']}@{p['address']}" for p in kept),
                assigned=", ".join(f"{p['proposed_name']}@{p['address']} ({(p.get('current_state') or '').lower()})"
                                   for p in reassigned)))

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
        if getattr(self,'_pid_project_operation',None):
            messagebox.showwarning('PID','Espere a que termine la operación PID antes de generar otro programa.')
            return False
        command_text = self.command_textbox.get("1.0", "end").strip()
        if not command_text:
            self._set_status("Error")
            self._log("No se proceso el comando porque el cuadro de texto esta vacio.")
            messagebox.showwarning("Comando", "Escriba un comando industrial antes de procesar.")
            return False

        self._invalidate_download_readiness()
        self._rollback_pending_map_transaction("comando nuevo")
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
            if self._normal_map_transactions_apply():
                io_map = self._prepare_program_scope(command_text, io_map)
            self.pending_runtime_config = (io_map, intents_catalog, safety_rules)
            normal_kwargs: dict[str, Any] = {}
            if self.work_mode_var.get() == "Normal":
                # Interaction history belongs to Normal; semantics are shared by both modes.
                if not self._reprocessing_clarification:
                    self._normal_clarification_state = normal_interaction.new_state(command_text)
                history = (self._normal_clarification_state or {}).get("history") or []
                if history:
                    normal_kwargs["clarification_history"] = list(history)
                program_context = (self._normal_program_context or {}).get("llm_context")
                if program_context:
                    normal_kwargs["program_context"] = program_context
            semantic_output = parse_command(
                command_text,
                io_map=io_map,
                intents_catalog=intents_catalog,
                safety_rules=safety_rules,
                mode=requested_mode,
                llm_client=self.llm_client,
                **normal_kwargs
            )
            self._log("Intencion detectada.")
            self._log("Parametros extraidos.")
            if self.work_mode_var.get() == "Normal":
                self._trace_normal_interpretation(semantic_output)
                scope = (self._normal_program_context or {}).get("scope")
                if scope == program_bindings.SCOPE_EXTEND and semantic_output.get("parser_mode_used") == "rule_based":
                    # Ampliar exige combinar el programa actual con el cambio: el parser por reglas no puede hacerlo.
                    self._log(normal_interaction.trace("NORMAL_PROGRAM_SCOPE", scope=scope, error="interprete por reglas"))
                    messagebox.showwarning("Comando", "Para modificar el programa actual se necesita el intérprete LLM. "
                                                      "Revise la conexión o describa el programa completo.")
                    self._set_status("Listo")
                    return False
                if scope == program_bindings.SCOPE_EXTEND:
                    from ir_builder import required_external_resources

                    kept = set(required_external_resources(semantic_output, io_map))
                    dropped = [name for name in ((self._normal_program_context or {}).get("current_program") or {}).get(
                        "resources") or [] if name not in kept]
                    if dropped:  # una ampliacion no deberia dejar de usar recursos del programa actual
                        self._log(normal_interaction.trace("NORMAL_PROGRAM_SCOPE", scope=scope,
                                                           warning="el programa ampliado ya no usa: " + ", ".join(dropped)))

            self._set_textbox_content(self.intent_textbox, self._format_intention_text(semantic_output))
            self._set_textbox_content(self.voice_textbox, self._build_voice_text())
            self._set_textbox_content(self.comparison_textbox, self._build_comparison_text(semantic_output))
            self._set_textbox_content(self.parameters_textbox, format_json(semantic_output.get("parameters", {})))
            self._set_textbox_content(self.verification_textbox, format_json(semantic_output.get("semantic_validation", {})))
            self.pending_semantic_output = semantic_output

            if self.work_mode_var.get() == "Experimentacion":
                self._refresh_experiment_status()

            hardware_gap = (semantic_output.get("semantic_validation") or {}).get("capability_gap")
            if self.work_mode_var.get() == "Normal" and hardware_gap and self.active_trial is None:
                question = semantic_output.get("clarification_question") or (
                    semantic_output.get("semantic_validation") or {}).get("clarification_question")
                if question and str(question).strip():
                    # La semantica incompleta se aclara primero (los recursos dependen de ella).
                    self._set_status("Listo")
                    return self._resolve_semantic_ambiguity(command_text, {**semantic_output, "clarification_question": question})
                self._report_normal_capability_gap(command_text, semantic_output, hardware_gap)
                return False

            has_map_proposals = bool(semantic_output.get("semantic_validation", {}).get("io_assignment_proposals"))
            map_config_continued = False
            normal_transactional = self._normal_map_transactions_apply()
            if normal_transactional:
                # Modo Normal: los roles funcionales con nombre nuevo son REQUISITOS del programa, no una
                # configuracion del mapa. Nada se escribe en el mapa antes de una semantica valida.
                operation = normal_interaction.classify_map_operation(semantic_output)
                self._log(normal_interaction.trace("NORMAL_RESOURCE_REQUIREMENTS", operation=operation["kind"],
                                                   **normal_interaction.resource_requirement_fields(semantic_output)))
                if operation["kind"] == normal_interaction.MAP_OPERATION_CONFIG:
                    self._log(normal_interaction.trace("NORMAL_MAP_CONFIG_EXPLICIT", assignments=", ".join(
                        f"{p.get('address')}->{p.get('proposed_name')}" for p in operation["explicit"])))
                    self._handle_map_config_command(semantic_output, io_map, intents_catalog, safety_rules)
                    self._set_status("Listo")
                    return False  # configuracion pura: no hay programa que generar
                # Asignacion PROVISIONAL en memoria (si no hay una aclaracion pendiente): la validacion se juzga
                # contra ella, igual que antes contra el mapa ya escrito, pero sin tocar el archivo ni la tabla.
                if has_map_proposals and not (semantic_output.get("requires_clarification") or (
                        semantic_output.get("semantic_validation") or {}).get("requires_clarification")):
                    semantic_output = self._prepare_provisional_allocation(semantic_output, intents_catalog, safety_rules)
                    if semantic_output is None:
                        self._set_status("Listo")
                        return False
                # Mismo criterio que antes para continuar con INT_UNKNOWN + requisitos con contenido logico.
                map_config_continued = has_map_proposals and operation["has_logic"]
            elif semantic_output.get("operation_type") == "MAP_CONFIG" or has_map_proposals:
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
            composable = product_engine.is_generatable_product(semantic_output)
            intent_missing = semantic_output.get("intent_id") == "INT_UNKNOWN" and not map_config_continued and not composable
            is_valid_now = semantic_output.get("semantic_validation", {}).get("is_valid", False)
            if intent_missing or not is_valid_now:
                # Semantica no valida / aclaracion / INT_UNKNOWN: ningun efecto persistente (se descarta lo provisional).
                self._rollback_pending_map_transaction("interpretacion no valida o aclaracion pendiente")
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
                requires_question = bool(semantic_output.get("requires_clarification"))
                if self.work_mode_var.get() == "Normal" and not clarification_question:
                    # Pregunta funcional derivada por el validador (p.ej. duracion de una etapa).
                    validation_now = semantic_output.get("semantic_validation", {}) or {}
                    clarification_question = validation_now.get("clarification_question")
                    requires_question = requires_question or bool(validation_now.get("requires_clarification"))
                has_real_question = bool(
                    requires_question
                    and clarification_question
                    and str(clarification_question).strip()
                )
                legacy_whitelist = resource_policy.legacy_profile_whitelist_applies(self._benchmark_version())
                if unauthorized_tags and self.work_mode_var.get() == "Experimentacion" and not legacy_whitelist:
                    # Benchmark v2: un recurso sin binding en el working_io_map es un fallo de
                    # asignacion de E/S, nunca "no autorizado por el caso" (allowed_variables no aplica).
                    self._log("Recursos fisicos sin binding en el working_io_map: " + ", ".join(unauthorized_tags))
                    if self.active_trial:
                        issues = resource_policy.unresolved_resources(semantic_output)
                        self._update_new_trial({
                            "io_map": {"error": resource_policy.ERROR_UNRESOLVED_RESOURCE},
                            "resource_check": {"policy": resource_policy.POLICY_WORKING_MAP_BINDING, "success": False, "errors": issues},
                        })
                        self._capture_trial_parse_failure(
                            command_text, semantic_output, error_code="E3", failure_stage=resource_policy.STAGE_IO_ALLOCATION
                        )
                    self._show_validation_errors(semantic_output)
                elif unauthorized_tags and self.work_mode_var.get() == "Experimentacion":
                    # Legacy benchmark v1 (aislado): whitelist por perfil.
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
                    if clarification_question and not semantic_output.get("clarification_question"):
                        semantic_output = {**semantic_output, "clarification_question": clarification_question}
                    return self._resolve_semantic_ambiguity(command_text, semantic_output)
                else:
                    self._log("La interpretacion no es valida para generar codigo (error de validacion, no una ambiguedad).")
                    if self.active_trial:
                        self._capture_trial_parse_failure(command_text, semantic_output, error_code="E3")
                    self._show_validation_errors(semantic_output)
                self._set_status("Listo")
                return False

            if normal_transactional and self._pending_map_transaction is None:
                self._open_map_transaction(self._program_base_map(), [], [], intents_catalog, safety_rules)
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
                if self.work_mode_var.get() == "Normal":
                    self._trace_normal_ir(package_result.get("project_ir") or {})
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
                if self._pending_map_transaction is not None:
                    self._pending_map_transaction.setdefault("functional_variables", []).extend(generated_functional)
                else:
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
            if self._pipeline_stage == "generation":
                self._pipeline_stage = "verification"  # el paquete se genero; lo que sigue es la verificacion
            if all_valid:
                self._log("Verificacion completada correctamente.")
            else:
                self._log("Verificacion fallida.")
            if self.active_trial:
                if self._capture_trial_generation_result(combined_results) is False:
                    all_valid = False
            if self.work_mode_var.get() == "Normal" and self.active_trial is None:
                self._log(normal_interaction.trace("NORMAL_GENERATION", verified=all_valid,
                                                   platforms=", ".join(combined_results)))
                if all_valid:
                    all_valid = self._commit_pending_map_transaction()
                else:
                    self._rollback_pending_map_transaction("la verificacion del programa fallo", notify=True)
            self._set_status("Listo")
            return all_valid
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._rollback_pending_map_transaction(f"error durante la generacion: {error}", notify=True)
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
