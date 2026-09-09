from __future__ import annotations

import csv
import json
import queue
import threading
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
from speech_recognizer import SpeechRecognizer
from tia_openness import (
    build_openness_bridge,
    diagnose_tia_openness,
    download_program_to_plc,
    load_tia_config,
    run_openness_bridge_diagnostic,
    save_tia_config,
    validate_package_with_tia
)
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

        self.grid_columnconfigure(1, weight=1)

        header = ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=20, weight="bold"))
        header.grid(row=0, column=0, columnspan=2, padx=20, pady=(18, 12), sticky="w")

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
                "comments": self.comments_var.get()
            }
        )
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


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
        self.parser_mode_var = tk.StringVar(value=initial_settings.get("PARSER_MODE", "hybrid"))
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
            "PARSER_MODE": self.parser_mode_var.get().strip() or "hybrid",
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
        self.parser_mode_var = tk.StringVar(value=parser_ui_map.get(resolved_start_mode, "Hibrido"))
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
        # Solo "CARGAR PROGRAMA AL PLC" queda habilitado mientras esto apunte al paquete de la
        # ULTIMA compilacion Siemens aprobada; cualquier nuevo comando procesado lo invalida.
        self._last_compiled_package_dir: Path | None = None
        self._download_worker_active = False
        self._download_worker_queue: queue.Queue = queue.Queue()
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
            "description": max(int(usable_width * 0.28), 170)
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
        buttons = [
            ("Abrir mapa I/O", self.open_io_map),
            ("Guardar mapa I/O", self.save_io_map),
            ("Agregar variable", self.add_variable),
            ("Editar variable", self.edit_variable),
            ("Eliminar variable", self.delete_variable)
        ]
        for index, (text, callback) in enumerate(buttons):
            button = ctk.CTkButton(action_frame, text=text, command=callback, font=self.button_font)
            if index == len(buttons) - 1:
                button.grid(row=2, column=0, columnspan=2, padx=4, pady=4, sticky="ew")
            else:
                button.grid(row=index // 2, column=index % 2, padx=4, pady=4, sticky="ew")
            self.left_action_buttons.append(button)

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
            values=["Discreto D01-D20", "PID P01-P12 - pendiente"],
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

        self.start_trial_button = ctk.CTkButton(
            frame, text="EJECUTAR ENSAYO", height=42,
            fg_color="#0F766E", hover_color="#115E59",
            command=self.run_experiment_trial, font=ctk.CTkFont(size=14, weight="bold")
        )
        self.start_trial_button.grid(row=18, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew")

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
            parser_mode = dialog.result.get("PARSER_MODE", "hybrid").strip().lower()
            parser_ui_map = {
                "rule_based": "Reglas",
                "llm": "LLM",
                "hybrid": "Hibrido"
            }
            self.parser_mode_var.set(parser_ui_map.get(parser_mode, "Hibrido"))
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

        if not messagebox.askyesno(
            "Confirmar TIA Openness",
            "Codigo generado y verificado.\n\n"
            f"Proyecto TIA: {diagnostic.get('project_path')}\n"
            f"Mapa: {self.active_map_var.get()}\n"
            f"Paquete: {package_dir_text}\n\n"
            "Se importara la fuente SCL en el proyecto TIA configurado, se crearan tags faltantes, "
            "se generaran bloques y se compilara. El proyecto solo se guardara si no hay errores. "
            "No se descargara nada a un PLC fisico.\n\n¿Desea importar y compilar?"
        ):
            self._log("Importacion TIA Openness cancelada por el usuario.")
            if self.active_trial:
                self._cancel_active_trial("Importacion a TIA cancelada por el usuario en la confirmacion.")
            return

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
            if self.active_trial:
                directory = trial_dir(self.project_root, self.active_trial["case_id"], self.active_trial["trial_id"])
                save_metadata(directory, {"tia_compile_status": "ERROR", "tia_error": str(payload)})
                self._log(f"Ensayo {self.active_trial['trial_id']}: fallo TIA Openness registrado como evidencia.")
            messagebox.showerror("TIA Openness", f"No se pudo completar la operacion.\n\n{payload}")
            return

        report = payload
        passed = report.get("status") == "TIA_COMPILATION_PASSED"
        report_text = format_json(report)
        self._set_textbox_content(self.tia_openness_textbox, report_text)
        if self.current_result_snapshot is not None:
            self._apply_tia_report_to_snapshot(self.current_result_snapshot, report)
            self._refresh_export_options(self.current_result_snapshot)

        result_path = str(report.get("result_path", ""))
        if self.active_trial:
            directory = trial_dir(self.project_root, self.active_trial["case_id"], self.active_trial["trial_id"])
            save_metadata(directory, {"tia_compile_status": report.get("status", ""), "tia_result_path": result_path})
            self._log(f"Ensayo {self.active_trial['trial_id']}: resultado TIA registrado ({report.get('status')}).")
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
            self.download_plc_button.configure(state="normal")
            self._log(f"'CARGAR PROGRAMA AL PLC' habilitado para {report_package_dir}.")
        else:
            self._invalidate_download_readiness()

        self._set_status("Listo" if passed else "Error")
        self._set_validation_banner(
            "Compilacion TIA Portal V18 aprobada." if passed else "TIA Portal reporto errores de compilacion.",
            passed
        )
        self._log(f"TIA Openness finalizo con estado {report.get('status')}.")
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

        confirmed = messagebox.askyesno(
            "Confirmar descarga al PLC",
            "Se descargara el programa compilado al PLC configurado en el proyecto TIA actual.\n\n"
            f"Proyecto TIA: {project_path}\n"
            f"CPU/dispositivo configurado: {plc_name}\n"
            f"Ultimo resultado de compilacion: {compile_status}\n"
            f"Timestamp de compilacion: {compile_timestamp}\n\n"
            "Esta accion afecta hardware fisico real. Solo se descarga el programa (software); "
            "no se modifica la configuracion de hardware ni se fuerza RUN/STOP mas alla de lo "
            "que TIA Portal Openness requiera internamente.\n\n"
            "¿Desea continuar?"
        )
        if not confirmed:
            self._log("Descarga al PLC cancelada por el usuario.")
            return

        while not self._download_worker_queue.empty():
            try:
                self._download_worker_queue.get_nowait()
            except queue.Empty:
                break

        self._download_worker_active = True
        self.download_plc_button.configure(state="disabled")
        self.execute_command_button.configure(state="disabled")
        self.start_trial_button.configure(state="disabled")
        self.validate_tia_button.configure(state="disabled")
        self._set_status("Procesando")
        self._set_textbox_content(
            self.tia_openness_textbox,
            "Descargando el programa compilado al PLC mediante TIA Portal V18 Openness. "
            "Esta operacion puede tardar varios minutos..."
        )
        self._select_results_tab("TIA Openness")
        self._log(f"Iniciando descarga al PLC del paquete {package_dir}.")

        def _worker() -> None:
            try:
                result = download_program_to_plc(package_dir, self.project_root)
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

        if outcome == "error":
            self._set_status("Error")
            self._log(f"Error al cargar el programa al PLC: {payload}")
            messagebox.showerror("Cargar programa al PLC", f"No se pudo cargar el programa al PLC.\n\n{payload}")
            return

        report = payload
        self._set_textbox_content(self.tia_openness_textbox, format_json(report))
        success = bool(report.get("success"))
        status = str(report.get("status", ""))
        self._set_status("Listo" if success else "Error")
        self._log(f"Descarga al PLC finalizada con estado {status}.")

        if success:
            messagebox.showinfo(
                "Cargar programa al PLC",
                "Programa cargado correctamente al PLC.\n\n"
                f"Dispositivo: {report.get('device_item_name', '')}\n"
                f"Fecha/hora: {report.get('timestamp', '')}\n"
                f"Resultado: {status}"
            )
        else:
            errors = report.get("errors", [])
            detail = "\n".join(str(item) for item in errors) if errors else "Revise el reporte tecnico en la pestana TIA Openness."
            messagebox.showerror("Cargar programa al PLC", "No se pudo cargar el programa al PLC.\n\n" + detail)

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
            messagebox.showinfo(
                "Grupo de pruebas",
                "El grupo PID (P01-P12) todavia no esta disponible. Se mantiene el grupo Discreto D01-D20."
            )
            self.experiment_group_var.set("Discreto D01-D20")
            return
        self._refresh_experiment_case_selector()

    def _refresh_experiment_case_selector(self) -> None:
        profiles = load_profiles(self.project_root)
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

        blocked = environment == "hardware" and not readiness["hardware_ready"]
        if blocked:
            lines.append(f"{profile['name']} no esta listo para hardware.")
        self.experiment_status_var.set("\n".join(lines))
        self.start_trial_button.configure(state="disabled" if blocked else "normal")

        condition_code = self._selected_condition()["code"]
        case_id = profile.get("case_id", "")
        variant = self.experiment_variant_var.get()
        next_repetition = compute_next_repetition(self.project_root, condition_code, case_id, variant)
        next_label = build_experiment_label(condition_code, case_id, variant, next_repetition)
        self.experiment_next_label_var.set(f"Proximo ensayo: {next_label}")

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
            messagebox.showwarning(
                "Ejecutar ensayo",
                f"{profile['name']} no esta listo para hardware.\n\nFaltan: "
                + ", ".join(readiness["missing_hardware_variables"])
            )
            return False

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
            "experiment_family": "DISCRETE",
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
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"No se pudo registrar la interpretacion del ensayo: {error}")

    def _capture_trial_parse_failure(
        self, command_text: str, semantic_output: dict[str, Any], error_code: str = "E2"
    ) -> None:
        if not self.active_trial:
            return
        trial_id = self.active_trial.get("trial_id", "")
        try:
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
        return True

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
        question = str(
            semantic_output.get("clarification_question")
            or "El comando requiere aclaracion antes de generar el paquete PLC."
        )
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

    def process_command(self) -> bool:
        command_text = self.command_textbox.get("1.0", "end").strip()
        if not command_text:
            self._set_status("Error")
            self._log("No se proceso el comando porque el cuadro de texto esta vacio.")
            messagebox.showwarning("Comando", "Escriba un comando industrial antes de procesar.")
            return False

        self._invalidate_download_readiness()

        if not self.save_io_map(show_success=False):
            self._set_status("Error")
            return False

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

            if semantic_output.get("intent_id") == "INT_UNKNOWN" or not semantic_output.get("semantic_validation", {}).get("is_valid", False):
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
                else:
                    self._log("La interpretacion requiere aclaracion antes de generar (SEMANTIC_AMBIGUITY).")
                    self._set_status("Listo")
                    return self._resolve_semantic_ambiguity(command_text, semantic_output)
                self._set_status("Listo")
                return False

            self._set_validation_banner("Interpretacion lista. Revise y confirme la generacion.", None)
            interpretation_snapshot = self._build_interpretation_snapshot(command_text, semantic_output)
            self._record_history(
                interpretation_snapshot,
                platform="Interpretacion",
                is_valid=semantic_output.get("semantic_validation", {}).get("is_valid", False)
            )
            self._log("Interpretacion completada. Lista para confirmacion.")
            if self.active_trial:
                self._capture_trial_parse_result(command_text, semantic_output)
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
        confirmation = messagebox.askyesnocancel(
            "Confirmar generacion",
            "Revise la interpretacion antes de generar.\n\n"
            + self._build_confirmation_summary(self.pending_semantic_output, target_platforms)
            + "\n\nSi selecciona 'No' podra editar el comando. Si selecciona 'Cancelar' no se generara nada."
        )
        if confirmation is None:
            self._log("Generacion cancelada por el usuario.")
            if self.active_trial:
                self._cancel_active_trial("Generacion cancelada por el usuario en la confirmacion.")
            return False
        if confirmation is False:
            self._log("El usuario decidio editar el comando antes de generar.")
            return False

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
            self._log("Verificacion completada.")
            if self.active_trial:
                self._capture_trial_generation_result(combined_results)
            self._set_status("Listo")
            return all(result["verification"]["is_valid"] for result in combined_results.values())
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
