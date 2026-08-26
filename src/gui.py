from __future__ import annotations

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
    ALLOWED_IO_CLASSES,
    ALLOWED_IO_TYPES,
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
from project_packager import generate_project_package
from speech_recognizer import SpeechRecognizer
from tia_openness import (
    build_openness_bridge,
    diagnose_tia_openness,
    load_tia_config,
    run_openness_bridge_diagnostic,
    save_tia_config,
    validate_package_with_tia
)
from utils import get_project_root, load_json_file, sanitize_filename


ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")


GUI_INSTANCE_PORT = 49573
_GUI_INSTANCE_SOCKET: socket.socket | None = None


class VariableEditorDialog(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk, title: str, variable_data: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("520x430")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        data = variable_data or {}
        self.result: dict[str, str] | None = None

        self.name_var = tk.StringVar(value=data.get("name", ""))
        self.class_var = tk.StringVar(value=data.get("class", "internal"))
        self.type_var = tk.StringVar(value=data.get("type", "BOOL"))
        self.location_var = tk.StringVar(value=data.get("location", ""))
        self.initial_value_var = tk.StringVar(value=data.get("initial_value", ""))
        self.description_var = tk.StringVar(value=data.get("description", ""))

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
        helper.grid(row=7, column=0, columnspan=2, padx=20, pady=(6, 14), sticky="w")

        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=8, column=0, columnspan=2, padx=20, pady=(0, 20), sticky="ew")
        button_frame.grid_columnconfigure((0, 1), weight=1)

        cancel_button = ctk.CTkButton(button_frame, text="Cancelar", fg_color="#6B7280", hover_color="#4B5563", command=self._cancel)
        cancel_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        save_button = ctk.CTkButton(button_frame, text="Aceptar", command=self._confirm)
        save_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(50, self.focus_force)

    def _build_form_row(self, row_index: int, label_text: str, widget: ctk.CTkBaseClass) -> None:
        label = ctk.CTkLabel(self, text=label_text)
        label.grid(row=row_index, column=0, padx=(20, 12), pady=8, sticky="w")
        widget.grid(row=row_index, column=1, padx=(0, 20), pady=8, sticky="ew")

    def _confirm(self) -> None:
        self.result = normalize_variable_entry(
            {
                "name": self.name_var.get(),
                "class": self.class_var.get(),
                "type": self.type_var.get(),
                "location": self.location_var.get(),
                "initial_value": self.initial_value_var.get(),
                "description": self.description_var.get()
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


class VozLLMPLCGUI(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.project_root = get_project_root()
        self.config_dir = self.project_root / "config"
        self.docs_dir = self.project_root / "docs"
        self.generated_dir = self.project_root / "generated_code"
        self.history_storage_path = self.generated_dir / "gui_history.json"
        self.env_path = get_env_path(self.project_root)
        self.io_map_path = self.config_dir / "io_map.json"
        self.intents_catalog_path = self.config_dir / "intents_catalog.json"
        self.safety_rules_path = self.config_dir / "safety_rules.json"

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
        self.status_var = tk.StringVar(value="Listo")
        self.llm_status_var = tk.StringVar(value="LLM en modo demo local")
        self.save_voice_evidence_var = tk.BooleanVar(value=False)
        self.history_records: list[dict[str, Any]] = []
        self.history_item_map: dict[str, dict[str, Any]] = {}
        self.history_record_keys: set[str] = set()
        self.current_result_snapshot: dict[str, Any] | None = None
        self.pending_semantic_output: dict[str, Any] | None = None
        self.pending_runtime_config: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None = None
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
            "Historial"
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
            "Historial": "Historial"
        }
        self.active_result_tab = "Voz"
        self.result_tab_window_start = 0
        self.result_tab_window_size = 4
        self.result_tab_button_height = 32
        self.result_nav_button_width = 36

        self._build_theme_tokens()

        ensure_generated_dirs(self.generated_dir)
        self.io_variables = load_io_map_variables(self.io_map_path)

        self._configure_grid()
        self._configure_treeview_style()
        self._build_layout()
        self._bind_responsive_events()
        self._load_io_map_table()
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

        self.center_panel = ctk.CTkFrame(self, corner_radius=18)
        self.center_panel.grid(row=0, column=1, padx=10, pady=(18, 10), sticky="nsew")
        self.center_panel.grid_columnconfigure(0, weight=1)
        self.center_panel.grid_rowconfigure(2, weight=1)

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
        for column_index in range(2):
            tia_actions_frame.grid_columnconfigure(column_index, weight=1)

        self.configure_tia_button = ctk.CTkButton(
            tia_actions_frame,
            text="Configurar TIA V18",
            command=self.configure_tia_openness,
            font=self.button_font
        )
        self.configure_tia_button.grid(row=0, column=0, padx=(0, 4), pady=4, sticky="ew")

        self.diagnose_tia_button = ctk.CTkButton(
            tia_actions_frame,
            text="Diagnosticar Openness",
            command=self.diagnose_tia_connection,
            font=self.button_font
        )
        self.diagnose_tia_button.grid(row=0, column=1, padx=(4, 0), pady=4, sticky="ew")

        self.validate_tia_button = ctk.CTkButton(
            tia_actions_frame,
            text="Importar y compilar ultimo paquete Siemens",
            command=self.validate_latest_package_in_tia,
            font=self.button_font
        )
        self.validate_tia_button.grid(row=1, column=0, columnspan=2, pady=4, sticky="ew")

        action_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        action_frame.grid(row=8, column=0, padx=18, pady=(0, 8), sticky="ew")
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

        self.table_label = ctk.CTkLabel(self.left_panel, text="Mapa I/O autorizado", font=self.section_label_font)
        self.table_label.grid(row=9, column=0, padx=18, pady=(2, 6), sticky="w")

        self.io_tree_container = ctk.CTkFrame(self.left_panel, corner_radius=12)
        self.io_tree_container.grid(row=10, column=0, padx=18, pady=(0, 8), sticky="nsew")
        self.io_tree_container.grid_columnconfigure(0, weight=1)
        self.io_tree_container.grid_rowconfigure(0, weight=1)
        self.left_panel.grid_rowconfigure(10, weight=1, minsize=230)

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
        manage_frame.grid(row=11, column=0, padx=18, pady=(0, 8), sticky="ew")
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

        button_frame = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        button_frame.grid(row=6, column=0, padx=18, pady=(0, 14), sticky="ew")
        for column_index in range(2):
            button_frame.grid_columnconfigure(column_index, weight=1)

        self.command_buttons: list[ctk.CTkButton] = []
        self.process_button = ctk.CTkButton(button_frame, text="Procesar comando", height=40, command=self.process_command, font=self.button_font)
        self.process_button.grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.process_button)

        self.generate_button = ctk.CTkButton(button_frame, text="Generar paquete PLC", height=40, command=self.generate_package, font=self.button_font)
        self.generate_button.grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.generate_button)

        self.listen_button = ctk.CTkButton(button_frame, text="Escuchar comando", height=40, command=self.listen_command, font=self.button_font)
        self.listen_button.grid(row=1, column=0, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.listen_button)

        self.stop_voice_button = ctk.CTkButton(
            button_frame,
            text="Detener y transcribir",
            height=40,
            fg_color="#B45309",
            hover_color="#92400E",
            command=self.stop_listening,
            font=self.button_font
        )
        self.stop_voice_button.grid(row=1, column=1, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.stop_voice_button)

        self.replay_button = ctk.CTkButton(
            button_frame,
            text="Reproducir grabacion",
            height=40,
            command=self.play_recording,
            font=self.button_font
        )
        self.replay_button.grid(row=2, column=0, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.replay_button)

        self.transcribe_button = ctk.CTkButton(
            button_frame,
            text="Transcribir",
            height=40,
            command=self.transcribe_recording,
            font=self.button_font
        )
        self.transcribe_button.grid(row=2, column=1, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.transcribe_button)

        self.use_transcription_button = ctk.CTkButton(
            button_frame,
            text="Usar transcripcion",
            height=40,
            command=self.use_transcription,
            font=self.button_font
        )
        self.use_transcription_button.grid(row=3, column=0, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.use_transcription_button)

        self.discard_voice_button = ctk.CTkButton(
            button_frame,
            text="Descartar",
            height=40,
            fg_color="#7C2D12",
            hover_color="#9A3412",
            command=self.discard_transcription,
            font=self.button_font
        )
        self.discard_voice_button.grid(row=3, column=1, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.discard_voice_button)

        self.clear_command_button = ctk.CTkButton(
            button_frame,
            text="Limpiar comando",
            height=40,
            fg_color="#475569",
            hover_color="#334155",
            command=self.clear_command,
            font=self.button_font
        )
        self.clear_command_button.grid(row=4, column=0, columnspan=2, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(self.clear_command_button)

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
            "Se importara la fuente SCL en el proyecto TIA configurado, se crearan tags faltantes, "
            "se generaran bloques y se compilara. El proyecto solo se guardara si no hay errores.\n\n"
            f"Proyecto: {diagnostic.get('project_path')}\n"
            f"Paquete: {package_dir_text}\n\n"
            "No se descargara nada a un PLC fisico. ¿Desea continuar?"
        ):
            self._log("Importacion TIA Openness cancelada por el usuario.")
            return

        while not self._tia_worker_queue.empty():
            try:
                self._tia_worker_queue.get_nowait()
            except queue.Empty:
                break

        package_dir = Path(package_dir_text)
        self._tia_worker_active = True
        self.validate_tia_button.configure(state="disabled")
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
        if outcome == "error":
            self._set_status("Error")
            self._set_textbox_content(self.tia_openness_textbox, str(payload))
            self._log(f"Error TIA Openness: {payload}")
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

    def _collect_io_variables(self) -> list[dict[str, str]]:
        return [normalize_variable_entry(entry) for entry in treeview_rows(self.io_tree, IO_TREE_COLUMNS)]

    def _load_runtime_configuration(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        io_map = load_json_file(self.io_map_path)
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

    def _run_variable_dialog(self, title: str, variable_data: dict[str, str] | None = None) -> dict[str, str] | None:
        dialog = VariableEditorDialog(self, title, variable_data)
        self.wait_window(dialog)
        return dialog.result

    def open_io_map(self) -> None:
        try:
            self.io_variables = load_io_map_variables(self.io_map_path)
            self._load_io_map_table()
            self._log("Mapa I/O cargado desde config/io_map.json.")
            messagebox.showinfo("Mapa I/O", "Mapa I/O cargado correctamente.")
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"Error al abrir mapa I/O: {error}")
            messagebox.showerror("Mapa I/O", f"No se pudo abrir el mapa I/O.\n\n{error}")

    def save_io_map(self, show_success: bool = True) -> bool:
        variables = self._collect_io_variables()
        errors = validate_io_map_variables(variables)
        if errors:
            self._log("Validacion del mapa I/O rechazada.")
            messagebox.showerror("Mapa I/O", "\n".join(errors[:12]))
            return False

        try:
            save_io_map_variables(self.io_map_path, variables)
            self.io_variables = variables
            self._load_io_map_table()
            self._log("Mapa I/O guardado correctamente.")
            if show_success:
                messagebox.showinfo("Mapa I/O", "Mapa I/O guardado correctamente.")
            return True
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._log(f"Error al guardar mapa I/O: {error}")
            messagebox.showerror("Mapa I/O", f"No se pudo guardar el mapa I/O.\n\n{error}")
            return False

    def add_variable(self) -> None:
        result = self._run_variable_dialog("Agregar variable")
        if result is None:
            return
        self.io_tree.insert("", "end", values=[result[column] for column in IO_TREE_COLUMNS])
        self._log(f"Variable agregada en tabla: {result['name']}.")

    def edit_variable(self) -> None:
        item_id = self._selected_tree_item()
        selected_data = self._selected_tree_data()
        if item_id is None or selected_data is None:
            messagebox.showwarning("Editar variable", "Seleccione una variable para editar.")
            return

        result = self._run_variable_dialog("Editar variable", selected_data)
        if result is None:
            return

        self.io_tree.item(item_id, values=[result[column] for column in IO_TREE_COLUMNS])
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
        self._log(f"Variable eliminada de la tabla: {selected_data['name']}.")

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

    def process_command(self) -> None:
        command_text = self.command_textbox.get("1.0", "end").strip()
        if not command_text:
            self._set_status("Error")
            self._log("No se proceso el comando porque el cuadro de texto esta vacio.")
            messagebox.showwarning("Comando", "Escriba un comando industrial antes de procesar.")
            return

        if not self.save_io_map(show_success=False):
            self._set_status("Error")
            return

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
                self._log("La interpretacion requiere aclaracion antes de generar.")
                messagebox.showwarning(
                    "Aclaracion requerida",
                    semantic_output.get("clarification_question")
                    or "El comando requiere aclaracion antes de generar el paquete PLC."
                )
                self._set_status("Listo")
                return

            self._set_validation_banner("Interpretacion lista. Revise y confirme la generacion.", None)
            interpretation_snapshot = self._build_interpretation_snapshot(command_text, semantic_output)
            self._record_history(
                interpretation_snapshot,
                platform="Interpretacion",
                is_valid=semantic_output.get("semantic_validation", {}).get("is_valid", False)
            )
            self._log("Interpretacion completada. Lista para confirmacion.")
            self._set_status("Listo")
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._set_status("Error")
            self._set_validation_banner("Error durante el procesamiento.", False)
            self._log(f"Error durante el procesamiento: {error}")
            messagebox.showerror("Procesamiento", f"No se pudo procesar el comando.\n\n{error}")

    def generate_package(self) -> None:
        if self.pending_semantic_output is None or self.pending_runtime_config is None:
            messagebox.showwarning("Generacion", "Primero procese un comando valido.")
            return

        target_platforms = normalize_platform_targets(self.platform_var.get())
        confirmation = messagebox.askyesnocancel(
            "Confirmar generacion",
            "Revise la interpretacion antes de generar.\n\n"
            + self._build_confirmation_summary(self.pending_semantic_output, target_platforms)
            + "\n\nSi selecciona 'No' podra editar el comando. Si selecciona 'Cancelar' no se generara nada."
        )
        if confirmation is None:
            self._log("Generacion cancelada por el usuario.")
            return
        if confirmation is False:
            self._log("El usuario decidio editar el comando antes de generar.")
            return

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
            self._set_status("Listo")
        except Exception as error:  # pragma: no cover - GUI feedback path
            self._set_status("Error")
            self._set_validation_banner("Error durante la generacion.", False)
            self._log(f"Error durante la generacion: {error}")
            messagebox.showerror("Generacion", f"No se pudo generar el paquete PLC.\n\n{error}")

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
