from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, ttk

from .application.controllers import BemController, OptimizationController, PreviewController, RunAllController, WorkflowController
from .domain.auto_enclosure import derive_auto_enclosure
from .domain.bem_specs import (
    BEM_FIELD_SECTIONS,
    BEM_GUIDED_ALWAYS_VISIBLE_KEYS,
    BEM_GUIDED_CONTROLLER_KEYS,
    BEM_GUIDED_FIELD_SECTIONS,
)
from .domain.config_core import (
    build_guided_field_states,
    build_field_hint,
    default_global_state,
    default_horn_state,
    load_global_state,
    load_horn_state,
    normalize_branch_locked_horn_state,
    normalize_inline_block,
    read_text_file,
    render_global_text,
    render_horn_text,
    sanitize_ath_state,
)
from .domain.design_recipe import DesignRecipe
from .domain.optimizer_specs import (
    OPTIMIZER_CONSTRAINT_FIELDS,
    OPTIMIZER_OBJECTIVE_FIELDS,
    OPTIMIZER_STUDY_FIELDS,
    default_optimizer_state,
)
from .domain.specs import (
    APP_TITLE,
    ATH_GLOBAL_CONFIG,
    ACCENT,
    ACCENT_SOFT,
    BG,
    BORDER,
    BUTTON_ACTIVE,
    BUTTON_BG,
    BUTTON_TEXT,
    CARD,
    CARD_ALT,
    FIELD_SECTIONS,
    GUIDED_ALWAYS_VISIBLE_KEYS,
    GUIDED_CONTROLLER_KEYS,
    GUIDED_FIELD_SECTIONS,
    INPUT_BG,
    MUTED,
    QUICK_FIELD_SECTIONS,
    ROOT_DIR,
    TEXT,
    FieldSpec,
)
from .infrastructure.bem_bridge import BemLaunch
from .infrastructure.bem_mesh import guess_latest_mesh_file
from .infrastructure.bem_state import (
    build_bem_guided_field_states,
    build_bem_runtime_settings,
    default_bem_state,
    sanitize_bem_state,
)
from .infrastructure.preview_core import (
    build_preview_command,
    compute_output_directory,
    describe_group_source,
    iter_output_search_directories,
)
from .presentation.bem_plot import draw_placeholder as draw_bem_placeholder
from .presentation.opengl_preview import OpenGLPreviewHost, probe_vtk_opengl
from .presentation.preview_renderer import PreviewRenderer
from .presentation.widgets import ScrollableFrame
from .self_test import run_self_test
from .tools.check_layering import check_layering, format_layering_report

GUI_BUILD_ID = "pythonGATH / ATH GUI 中文版 2026-03-19"
UI_FONT_CANDIDATES = (
    "Microsoft JhengHei UI",
    "Microsoft JhengHei",
    "微軟正黑體",
    "Noto Sans TC",
    "Noto Sans CJK TC",
    "PingFang TC",
    "Heiti TC",
    "Segoe UI",
)


class AthConfigStudio(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_TITLE} | {GUI_BUILD_ID}")
        self.geometry("1320x920")
        self.minsize(1080, 760)
        self.configure(background=BG)

        self.global_widgets: dict[str, dict[str, object]] = {}
        self.horn_widgets: dict[str, dict[str, object]] = {}
        self.quick_widgets: dict[str, dict[str, object]] = {}
        self.base_design_widgets: dict[str, dict[str, object]] = {}
        self.guided_widgets: dict[str, dict[str, object]] = {}
        self.guided_bem_widgets: dict[str, dict[str, object]] = {}
        self.bem_widgets: dict[str, dict[str, object]] = {}
        self.optimizer_widgets: dict[str, dict[str, object]] = {}
        self.current_horn_path = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就緒。")
        self.ath_process: subprocess.Popen[bytes] | None = None
        self.bem_launch: BemLaunch | None = None
        self.last_generated_preview_file: Path | None = None
        self.preview_geometry: dict[str, object] | None = None
        self.preview_request_id = 0
        self.preview_path_var = tk.StringVar(value="尚未載入任何輸出預覽。")
        self.preview_meta_var = tk.StringVar(value="請先執行 ATH，或從目前專案輸出目錄載入 .geo / .msh / .stl。")
        self.preview_group_var = tk.StringVar(value="分群摘要：尚未偵測。")
        self.build_var = tk.StringVar(value=GUI_BUILD_ID)
        self.project_root_var = tk.StringVar(value=str(ROOT_DIR))
        self.python_var = tk.StringVar(value=sys.executable)
        self.current_cfg_var = tk.StringVar(value="尚未開啟號角設定檔。")
        self.output_dir_var = tk.StringVar(value="尚未解析。")
        self.preview_status_var = tk.StringVar(value="預覽狀態：未載入")
        self.mesh_status_var = tk.StringVar(value="BEM 網格：未指定")
        self.group_status_var = tk.StringVar(value="分群狀態：尚未檢查")
        self.bem_status_var = tk.StringVar(value="閒置")
        self.bem_progress_var = tk.StringVar(value="BEM 進度：閒置")
        self.bem_result_path_var = tk.StringVar(value="尚未執行任何 BEM 工作。")
        self.bem_plot_caption_var = tk.StringVar(value="執行 BEM 後將在此顯示指向性極座標圖。")
        self.bem_plot_mode_var = tk.StringVar(value="Smooth Display")
        self.bem_plot_log_x_var = tk.BooleanVar(value=True)
        self.preview_view_var = tk.StringVar(value="視角：yaw 32°, pitch -18°, zoom 1.00x")
        self.status_card_collapsed = tk.BooleanVar(value=False)
        self.status_card_toggle_var = tk.StringVar(value="收合")
        self.status_card_summary_var = tk.StringVar(value="")
        self.run_all_stage_var = tk.StringVar(value="idle")
        self.run_all_status_var = tk.StringVar(value="Workflow idle.")
        self.run_all_workspace_var = tk.StringVar(value="Workspace: (none)")
        self.optimizer_status_var = tk.StringVar(value="Study idle.")
        self.optimizer_trial_var = tk.StringVar(value="Trial: 0 / 0")
        self.optimizer_best_score_var = tk.StringVar(value="Best score: (none)")
        self.optimizer_study_dir_var = tk.StringVar(value="Study dir: (none)")
        self.bem_last_result_dir: Path | None = None
        self.bem_last_log_path: Path | None = None
        self.bem_polar_rows: list[dict[str, float]] = []
        self.optimizer_log_text: tk.Text | None = None
        self.optimizer_best_text: tk.Text | None = None
        self.base_design_summary_text: tk.Text | None = None
        self.build_verify_bem_text: tk.Text | None = None
        self.verification_summary_text: tk.Text | None = None
        self.optimize_base_conditions_text: tk.Text | None = None
        self.optimize_constraints_text: tk.Text | None = None
        self.optimize_search_space_text: tk.Text | None = None
        self.results_overview_text: tk.Text | None = None
        self.opengl_preview: OpenGLPreviewHost | None = None
        self.preview_backend_var = tk.StringVar(value="預覽後端：Canvas")
        self.preview_yaw_deg = 32.0
        self.preview_pitch_deg = -18.0
        self.preview_zoom = 1.0
        self.preview_drag_origin: tuple[int, int] | None = None
        self.preview_drag_angles: tuple[float, float] | None = None
        self.preview_sensitivity_var = tk.DoubleVar(value=1.0)
        self.preview_sensitivity_label_var = tk.StringVar(value="互動靈敏度 1.00x")
        self.preview_show_normals_var = tk.BooleanVar(value=True)
        self._suspend_dependency_refresh = False
        self._dependency_trace_tokens: list[tuple[tk.Variable, str]] = []
        self._suspend_quick_sync = False
        self._quick_dirty = False
        self._quick_trace_tokens: list[tuple[tk.Variable, str]] = []
        self._context_trace_tokens: list[tuple[tk.Variable, str]] = []
        self._context_refresh_after_id: str | None = None
        self._active_controls_tab_id = ""
        self._bem_progress_running = False
        self._bem_progress_phase = "BEM 進度：閒置"
        self._bem_progress_started_at = 0.0
        self._bem_progress_after_id: str | None = None
        self.bem_progress_bar: ttk.Progressbar | None = None
        self.font_family = self._resolve_ui_font_family()
        self._configure_fonts()
        self.preview_controller = PreviewController(self)
        self.bem_controller = BemController(self)
        self.workflow_controller = WorkflowController(self)
        self.run_all_controller = RunAllController(self)
        self.optimization_controller = OptimizationController(self)
        self.preview_renderer = PreviewRenderer(self)

        self._configure_style()
        self._build_shell()
        self.load_global_config(startup=True)
        self.new_horn_config(startup=True)

    def _resolve_ui_font_family(self) -> str:
        """Pick a Chinese-friendly UI font available on the current system."""
        available = set(tkfont.families(self))
        for family in UI_FONT_CANDIDATES:
            if family in available:
                return family
        return "TkDefaultFont"

    def _configure_fonts(self) -> None:
        """Configure shared named fonts so Chinese labels and text stay legible."""
        self.fonts = {
            "body": tkfont.Font(self, name="AthUiBodyFont", family=self.font_family, size=10),
            "hint": tkfont.Font(self, name="AthUiHintFont", family=self.font_family, size=10),
            "label": tkfont.Font(self, name="AthUiLabelFont", family=self.font_family, size=10),
            "heading": tkfont.Font(self, name="AthUiHeadingFont", family=self.font_family, size=11, weight="bold"),
            "title": tkfont.Font(self, name="AthUiTitleFont", family=self.font_family, size=20, weight="bold"),
            "tab": tkfont.Font(self, name="AthUiTabFont", family=self.font_family, size=10, weight="bold"),
            "canvas": tkfont.Font(self, name="AthUiCanvasFont", family=self.font_family, size=10),
            "canvas_small": tkfont.Font(self, name="AthUiCanvasSmallFont", family=self.font_family, size=9),
        }
        self.option_add("*Font", "AthUiBodyFont")
        self.option_add("*Text.Font", "AthUiBodyFont")
        self.option_add("*Entry.Font", "AthUiBodyFont")
        self.option_add("*Listbox.Font", "AthUiBodyFont")

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.tk_setPalette(
            background=BG,
            foreground=TEXT,
            activeBackground=BUTTON_ACTIVE,
            activeForeground=TEXT,
            highlightColor=ACCENT,
            selectBackground=ACCENT,
            selectForeground="#081018",
        )

        style.configure("App.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Card.TLabelframe", background=CARD, borderwidth=1, relief="solid")
        style.configure("Card.TLabelframe.Label", background=CARD, foreground=ACCENT, font="AthUiHeadingFont")
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font="AthUiTitleFont")
        style.configure("Body.TLabel", background=BG, foreground=TEXT, font="AthUiBodyFont")
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font="AthUiHintFont")
        style.configure("CardLabel.TLabel", background=CARD, foreground=TEXT, font="AthUiLabelFont")
        style.configure("Hint.TLabel", background=CARD, foreground=MUTED, font="AthUiHintFont")
        style.configure("TLabel", background=BG, foreground=TEXT, font="AthUiBodyFont")
        style.configure(
            "TEntry",
            font="AthUiBodyFont",
            fieldbackground=INPUT_BG,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            insertcolor=TEXT,
        )
        style.map(
            "TEntry",
            fieldbackground=[("disabled", "#0a1320")],
            foreground=[("disabled", MUTED)],
        )
        style.configure(
            "TCombobox",
            font="AthUiBodyFont",
            fieldbackground=INPUT_BG,
            background=INPUT_BG,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("disabled", "#0a1320"), ("readonly", INPUT_BG)],
            background=[("readonly", INPUT_BG)],
            foreground=[("disabled", MUTED), ("readonly", TEXT)],
            selectbackground=[("readonly", ACCENT)],
            selectforeground=[("readonly", "#081018")],
        )
        style.configure("TCheckbutton", background=CARD, foreground=TEXT, font="AthUiBodyFont")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 10), font="AthUiTabFont")
        style.map(
            "TNotebook.Tab",
            background=[("selected", CARD), ("active", ACCENT_SOFT), ("!selected", CARD_ALT)],
            foreground=[("selected", TEXT), ("!selected", MUTED)],
        )
        style.configure("Accent.TButton", font="AthUiBodyFont", padding=(12, 8), background=ACCENT, foreground="#081018", bordercolor=ACCENT)
        style.map("Accent.TButton", background=[("active", "#59dac8"), ("pressed", "#2fb8a5")], foreground=[("disabled", MUTED)])
        style.configure("Tool.TButton", font="AthUiBodyFont", padding=(10, 7), background=BUTTON_BG, foreground=BUTTON_TEXT, bordercolor=BORDER)
        style.map("Tool.TButton", background=[("active", BUTTON_ACTIVE), ("pressed", "#355174")], foreground=[("disabled", MUTED)])
        style.configure(
            "Compact.Tool.TButton",
            font="AthUiHintFont",
            padding=(7, 3),
            background=BUTTON_BG,
            foreground=BUTTON_TEXT,
            bordercolor=BORDER,
        )
        style.map("Compact.Tool.TButton", background=[("active", BUTTON_ACTIVE), ("pressed", "#355174")], foreground=[("disabled", MUTED)])
        style.configure(
            "Compact.Accent.TButton",
            font="AthUiHintFont",
            padding=(8, 3),
            background=ACCENT,
            foreground="#081018",
            bordercolor=ACCENT,
        )
        style.map(
            "Compact.Accent.TButton",
            background=[("active", "#59dac8"), ("pressed", "#2fb8a5")],
            foreground=[("disabled", MUTED)],
        )
        style.configure("Vertical.TScrollbar", background=CARD_ALT, troughcolor=BG, bordercolor=BG, arrowcolor=TEXT)

    def _make_dark_text(self, parent: tk.Misc, *, height: int, wrap: str) -> tk.Text:
        return tk.Text(
            parent,
            height=height,
            wrap=wrap,
            font="AthUiBodyFont",
            background=INPUT_BG,
            foreground=TEXT,
            insertbackground=TEXT,
            selectbackground=ACCENT,
            selectforeground="#081018",
            padx=8,
            pady=6,
            spacing1=2,
            spacing2=3,
            spacing3=2,
            relief="flat",
            borderwidth=1,
        )

    def _build_shell(self) -> None:
        root = ttk.Frame(self, style="App.TFrame", padding=18)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        header = ttk.Frame(root, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)
        title_bar = ttk.Frame(header, style="App.TFrame")
        title_bar.grid(row=0, column=0, sticky="ew")
        title_bar.columnconfigure(1, weight=1)
        ttk.Label(title_bar, text=APP_TITLE, style="Title.TLabel").grid(row=0, column=0, sticky="w")

        quick_actions = ttk.Frame(title_bar, style="App.TFrame")
        quick_actions.grid(row=0, column=1, sticky="w", padx=(12, 0), pady=(2, 0))
        ttk.Button(quick_actions, text="新增", style="Compact.Tool.TButton", command=self.new_horn_config).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(quick_actions, text="開啟", style="Compact.Tool.TButton", command=self.open_horn_config).grid(row=0, column=1, padx=(0, 4))
        ttk.Button(quick_actions, text="儲存", style="Compact.Tool.TButton", command=self.save_horn_config).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(quick_actions, text="另存", style="Compact.Tool.TButton", command=self.save_horn_config_as).grid(row=0, column=3, padx=(0, 4))
        ttk.Button(quick_actions, text="Auto ENC", style="Compact.Tool.TButton", command=self.apply_auto_enclosure).grid(row=0, column=4, padx=(0, 4))
        ttk.Button(quick_actions, text="執行 ATH", style="Compact.Accent.TButton", command=self.run_ath).grid(row=0, column=5, padx=(2, 4))
        ttk.Button(quick_actions, text="Run All", style="Compact.Accent.TButton", command=self.run_all_from_current_mode).grid(row=0, column=6, padx=(0, 0))

        subtitle_bar = ttk.Frame(header, style="App.TFrame")
        subtitle_bar.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        subtitle_bar.columnconfigure(2, weight=1)
        ttk.Label(
            subtitle_bar,
            text="ATH 4.8.2 表單式設定編輯器，整合幾何預覽、BEM 網格檢查與結果追蹤。",
            style="Muted.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(subtitle_bar, text="目前號角檔：", style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 4))
        ttk.Label(subtitle_bar, textvariable=self.current_horn_path, style="Muted.TLabel").grid(row=0, column=2, sticky="ew")
        self._build_status_panel(header)

        work_area = ttk.Panedwindow(root, orient="horizontal")
        work_area.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        controls_host = ttk.Frame(work_area, style="App.TFrame")
        controls_host.columnconfigure(0, weight=1)
        controls_host.rowconfigure(0, weight=1)
        workspace_host = ttk.Frame(work_area, style="App.TFrame")
        workspace_host.columnconfigure(0, weight=1)
        workspace_host.rowconfigure(0, weight=1)
        self.workspace_host = workspace_host

        work_area.add(controls_host, weight=4)
        work_area.add(workspace_host, weight=5)

        self.notebook = ttk.Notebook(controls_host)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.control_tabs: dict[str, ttk.Frame] = {}
        self.tab_bodies: dict[str, ttk.Frame] = {}
        tab_titles = {
            "QuickStart": "Base Design",
            "BEM": "Build / Verify",
            "Optimize": "Optimize",
            "Guided": "Results",
            "Advanced": "Advanced",
        }
        for tab_name in ("QuickStart", "BEM", "Optimize", "Guided", "Advanced"):
            scroll = ScrollableFrame(self.notebook)
            self.notebook.add(scroll, text=tab_titles[tab_name])
            self.control_tabs[tab_name] = scroll
            self.tab_bodies[tab_name] = scroll.inner
        self.notebook.bind("<<NotebookTabChanged>>", self._on_controls_tab_changed)

        self.workspace_notebook = ttk.Notebook(workspace_host)
        self.workspace_notebook.grid(row=0, column=0, sticky="nsew")
        self.workspace_tabs: dict[str, ttk.Frame] = {}
        workspace_titles = {
            "Geometry3D": "3D 幾何",
            "Polar": "指向性",
            "MeshInfo": "網格摘要",
            "Summary": "BEM 摘要",
            "Study": "最佳化",
            "TextPreview": "設定文字",
        }
        for key in ("Geometry3D", "Polar", "MeshInfo", "Summary", "Study", "TextPreview"):
            frame = ttk.Frame(self.workspace_notebook, style="App.TFrame")
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            self.workspace_notebook.add(frame, text=workspace_titles[key])
            self.workspace_tabs[key] = frame

        self._build_sections()
        self.notebook.select(self.control_tabs["QuickStart"])
        self._active_controls_tab_id = str(self.control_tabs["QuickStart"])

        footer = ttk.Frame(root, style="App.TFrame", padding=(0, 8, 0, 0))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")

    def _build_status_panel(self, parent: ttk.Frame) -> None:
        """Build a compact top-right runtime status card to preserve preview area."""
        card = ttk.LabelFrame(parent, text="狀態", style="Card.TLabelframe", padding=10)
        card.grid(row=0, column=1, rowspan=2, sticky="ne", padx=(16, 0))
        card.columnconfigure(0, weight=1)
        self.status_card_frame = card

        header = ttk.Frame(card, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            textvariable=self.status_card_summary_var,
            style="Hint.TLabel",
            justify="left",
            wraplength=250,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            header,
            textvariable=self.status_card_toggle_var,
            style="Tool.TButton",
            command=self._toggle_status_card,
            width=6,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))

        progress_frame = ttk.Frame(card, style="Card.TFrame")
        progress_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        progress_frame.columnconfigure(0, weight=1)
        ttk.Label(
            progress_frame,
            textvariable=self.bem_progress_var,
            style="Hint.TLabel",
            justify="left",
            wraplength=280,
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.bem_progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate", length=260)
        self.bem_progress_bar.grid(row=1, column=0, sticky="ew")

        details = ttk.Frame(card, style="Card.TFrame")
        details.grid(row=2, column=0, sticky="ew")
        details.columnconfigure(1, weight=1)
        self.status_card_details = details

        labels = [
            ("預覽", self.preview_status_var),
            ("分群", self.group_status_var),
            ("BEM", self.bem_status_var),
            ("OPT", self.optimizer_status_var),
            ("網格", self.mesh_status_var),
        ]
        for row, (label, variable) in enumerate(labels):
            ttk.Label(details, text=f"{label}：", style="CardLabel.TLabel").grid(
                row=row,
                column=0,
                sticky="nw",
                padx=(0, 8),
                pady=(0, 4),
            )
            ttk.Label(
                details,
                textvariable=variable,
                style="Hint.TLabel",
                justify="left",
                wraplength=280,
            ).grid(row=row, column=1, sticky="nw", pady=(0, 4))
        self._refresh_status_card_summary()
        self._set_status_card_collapsed(False)

    def _refresh_status_card_summary(self) -> None:
        preview = self.preview_status_var.get().replace("預覽狀態：", "").strip()
        bem = self.bem_status_var.get().strip()
        optimizer = self.optimizer_status_var.get().strip()
        group = self.group_status_var.get().replace("分群狀態：", "").strip()
        self.status_card_summary_var.set(f"預覽 {preview} | BEM {bem} | OPT {optimizer} | 分群 {group}")
        self._request_context_refresh()

    def _format_elapsed_text(self, elapsed_sec: float) -> str:
        total_sec = max(0, int(elapsed_sec))
        hours, remainder = divmod(total_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _refresh_bem_progress_text(self) -> None:
        if self._bem_progress_running:
            elapsed = self._format_elapsed_text(time.monotonic() - self._bem_progress_started_at)
            self.bem_progress_var.set(f"{self._bem_progress_phase} | 已耗時 {elapsed}")
            return
        self.bem_progress_var.set(self._bem_progress_phase)

    def _schedule_bem_progress_tick(self) -> None:
        if not self._bem_progress_running:
            self._bem_progress_after_id = None
            return
        self._refresh_bem_progress_text()
        self._bem_progress_after_id = self.after(1000, self._schedule_bem_progress_tick)

    def start_bem_progress(self, phase: str) -> None:
        self._bem_progress_phase = str(phase).strip() or "BEM 求解中"
        self._bem_progress_started_at = time.monotonic()
        self._bem_progress_running = True
        if self._bem_progress_after_id is not None:
            self.after_cancel(self._bem_progress_after_id)
            self._bem_progress_after_id = None
        if self.bem_progress_bar is not None:
            self.bem_progress_bar.configure(mode="indeterminate")
            self.bem_progress_bar.start(12)
        self._refresh_bem_progress_text()
        self._schedule_bem_progress_tick()

    def update_bem_progress(self, phase: str) -> None:
        self._bem_progress_phase = str(phase).strip() or self._bem_progress_phase
        self._refresh_bem_progress_text()

    def stop_bem_progress(self, phase: str = "BEM 進度：閒置") -> None:
        self._bem_progress_running = False
        self._bem_progress_phase = str(phase).strip() or "BEM 進度：閒置"
        if self._bem_progress_after_id is not None:
            self.after_cancel(self._bem_progress_after_id)
            self._bem_progress_after_id = None
        if self.bem_progress_bar is not None:
            self.bem_progress_bar.stop()
        self._refresh_bem_progress_text()

    def _set_status_card_collapsed(self, collapsed: bool) -> None:
        self.status_card_collapsed.set(collapsed)
        if collapsed:
            self.status_card_details.grid_remove()
            self.status_card_toggle_var.set("展開")
        else:
            self.status_card_details.grid()
            self.status_card_toggle_var.set("收合")

    def _toggle_status_card(self) -> None:
        self._set_status_card_collapsed(not self.status_card_collapsed.get())

    def _build_advanced_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)

        intro = ttk.LabelFrame(target, text="Advanced / Expert Controls", style="Card.TLabelframe", padding=14)
        intro.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=(
                "這裡集中保留完整原始欄位，方便進階細調與相容既有流程。"
                "日常設計建議先從 Base Design 進入；Build / Verify 與 Optimize 都會讀取目前這份正式狀態。"
            ),
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w")

        row = 1
        for section_name, description, fields in FIELD_SECTIONS:
            card = ttk.LabelFrame(target, text=section_name, style="Card.TLabelframe", padding=14)
            card.grid(row=row, column=0, sticky="ew", padx=14, pady=(14, 0))
            card.columnconfigure(1, weight=1)
            ttk.Label(
                card,
                text=description,
                style="Hint.TLabel",
                justify="left",
                wraplength=720,
            ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
            self._populate_card(card, fields, self.global_widgets if section_name == "Global" else self.horn_widgets, start_row=1)
            row += 1

        advanced_hint = ttk.LabelFrame(target, text="進階區說明", style="Card.TLabelframe", padding=14)
        advanced_hint.grid(row=row, column=0, sticky="ew", padx=14, pady=(14, 18))
        advanced_hint.columnconfigure(0, weight=1)
        ttk.Label(
            advanced_hint,
            text=(
                "右側工作區維持 3D 幾何、指向性、網格摘要、BEM 摘要、最佳化與設定文字預覽。"
                "左側 Advanced 則保留完整原始欄位，避免主要操作頁被低頻參數淹沒。"
            ),
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w")

    def _build_sections(self) -> None:
        for body in self.tab_bodies.values():
            body.columnconfigure(0, weight=1)

        self._build_advanced_panel(self.tab_bodies["Advanced"])
        self._build_quick_start_panel(self.tab_bodies["QuickStart"])
        self._build_bem_panel(self.tab_bodies["BEM"])
        self._build_optimizer_panel(self.tab_bodies["Optimize"])
        self._build_results_panel(self.tab_bodies["Guided"])

        self._build_preview_panel(self.workspace_tabs["Geometry3D"])
        self._build_polar_panel(self.workspace_tabs["Polar"])
        self._build_mesh_info_panel(self.workspace_tabs["MeshInfo"])
        self._build_bem_summary_panel(self.workspace_tabs["Summary"])
        self._build_optimizer_workspace_panel(self.workspace_tabs["Study"])

        preview_card = ttk.LabelFrame(
            self.workspace_tabs["TextPreview"],
            text="號角設定文字預覽",
            style="Card.TLabelframe",
            padding=14,
        )
        preview_card.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 18))
        preview_card.columnconfigure(0, weight=1)
        preview_card.rowconfigure(1, weight=1)
        ttk.Button(preview_card, text="更新文字預覽", style="Tool.TButton", command=self.refresh_preview).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.preview_text = self._make_dark_text(preview_card, height=22, wrap="none")
        self.preview_text.grid(row=1, column=0, sticky="nsew")
        self.preview_text.configure(state="disabled")
        self._bind_dependency_traces()
        self._bind_quick_traces()
        self._bind_context_traces()
        self.refresh_dependency_states()
        self._request_context_refresh()

    def _build_quick_start_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)

        intro = ttk.LabelFrame(target, text="Base Design", style="Card.TLabelframe", padding=14)
        intro.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=(
                "這裡不再只是 quick-start 縮寫表單，而是目前專案的正式基準設計頁。"
                "這一頁的目前設計，就是後續 Build / Verify / Optimize 使用的基準條件。"
            ),
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w")

        summary_card = ttk.LabelFrame(target, text="Current Base Design", style="Card.TLabelframe", padding=14)
        summary_card.grid(row=1, column=0, sticky="ew", padx=14, pady=(14, 0))
        summary_card.columnconfigure(0, weight=1)
        ttk.Label(
            summary_card,
            text=(
                "Source of truth: 目前 GUI 的正式 horn + BEM state。"
                " `collect_design_recipe()` 會從這些欄位組出 DesignRecipe，並供 Generate / BEM / Optimize 共用。"
            ),
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.base_design_summary_text = self._make_dark_text(summary_card, height=12, wrap="word")
        self.base_design_summary_text.grid(row=1, column=0, sticky="ew")
        self.base_design_summary_text.configure(state="disabled")

        common_fields = tuple(field for _title, _description, fields in QUICK_FIELD_SECTIONS[:2] for field in fields)
        common_card = ttk.LabelFrame(target, text="Common Geometry", style="Card.TLabelframe", padding=14)
        common_card.grid(row=2, column=0, sticky="ew", padx=14, pady=(14, 0))
        common_card.columnconfigure(1, weight=1)
        ttk.Label(
            common_card,
            text="挑出最常改、最常確認的幾何欄位，直接綁到正式 horn state；更完整的原始欄位仍保留在 Advanced。",
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self._populate_card(common_card, common_fields, self.base_design_widgets, start_row=1, shared_widget_map=self.horn_widgets)

        action_card = ttk.LabelFrame(target, text="Recipe Actions", style="Card.TLabelframe", padding=14)
        action_card.grid(row=3, column=0, sticky="ew", padx=14, pady=(14, 18))
        action_card.columnconfigure(3, weight=1)
        ttk.Button(action_card, text="Save Recipe", style="Tool.TButton", command=self.save_design_recipe).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(action_card, text="Load Recipe", style="Tool.TButton", command=self.load_design_recipe).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(action_card, text="Apply Sample", style="Tool.TButton", command=self.apply_sample_design).grid(row=0, column=2, padx=(0, 8))
        ttk.Label(
            action_card,
            text="Recipe actions 會讀寫目前的正式設計狀態，不會建立另一份獨立 quick-state。",
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))

    def _build_guided_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)

        intro = ttk.LabelFrame(target, text="Guided Setup", style="Card.TLabelframe", padding=14)
        intro.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text="依目前設計模式只顯示相關參數；完整參數仍可在其他分頁調整。"
                 "切換模式時不會直接清掉原本輸入，只有儲存/預覽/執行前才會套用 sanitize。"
                 "下方也包含 BEM automation 的獨立執行設定，這些欄位不會寫進 ATH cfg。",
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w")

        row = 1
        for title, description, fields in GUIDED_FIELD_SECTIONS:
            card = ttk.LabelFrame(target, text=title, style="Card.TLabelframe", padding=14)
            card.grid(row=row, column=0, sticky="ew", padx=14, pady=(14, 0))
            card.columnconfigure(1, weight=1)
            ttk.Label(
                card,
                text=description,
                style="Hint.TLabel",
                justify="left",
                wraplength=720,
            ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
            self._populate_card(card, fields, self.guided_widgets, start_row=1, shared_widget_map=self.horn_widgets)
            row += 1

        for title, description, fields in BEM_GUIDED_FIELD_SECTIONS:
            card = ttk.LabelFrame(target, text=title, style="Card.TLabelframe", padding=14)
            card.grid(row=row, column=0, sticky="ew", padx=14, pady=(14, 0))
            card.columnconfigure(1, weight=1)
            ttk.Label(
                card,
                text=description,
                style="Hint.TLabel",
                justify="left",
                wraplength=720,
            ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
            self._populate_card(card, fields, self.guided_bem_widgets, start_row=1, shared_widget_map=self.bem_widgets)
            row += 1

    def _build_preview_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)
        target.rowconfigure(0, weight=1)

        preview_card = ttk.LabelFrame(
            target,
            text="內嵌幾何預覽（.geo / .msh / .stl）",
            style="Card.TLabelframe",
            padding=14,
        )
        preview_card.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 18))
        preview_card.columnconfigure(0, weight=1)
        preview_card.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(preview_card, style="Card.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(8, weight=1)
        ttk.Button(toolbar, text="載入最新輸出", style="Tool.TButton", command=self.load_latest_output_preview).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="外部開啟", style="Tool.TButton", command=self.open_current_preview_external).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(toolbar, text="重設視角", style="Tool.TButton", command=self._reset_preview_view).grid(row=0, column=2, padx=(0, 8))
        ttk.Label(toolbar, textvariable=self.preview_view_var, style="Hint.TLabel").grid(row=0, column=3, padx=(0, 12), sticky="w")
        ttk.Label(toolbar, textvariable=self.preview_backend_var, style="Hint.TLabel").grid(row=0, column=4, padx=(0, 12), sticky="w")
        ttk.Label(toolbar, textvariable=self.preview_sensitivity_label_var, style="Hint.TLabel").grid(row=0, column=5, padx=(0, 6), sticky="w")
        ttk.Scale(
            toolbar,
            from_=0.3,
            to=2.5,
            orient="horizontal",
            variable=self.preview_sensitivity_var,
            command=self._on_preview_sensitivity_change,
            length=150,
        ).grid(row=0, column=6, padx=(0, 10), sticky="w")
        ttk.Checkbutton(
            toolbar,
            text="顯示分群法向",
            variable=self.preview_show_normals_var,
            command=self._on_preview_normals_toggle,
        ).grid(row=0, column=7, padx=(0, 10), sticky="w")
        ttk.Label(toolbar, textvariable=self.preview_path_var, style="Hint.TLabel").grid(row=0, column=8, sticky="e")

        info = ttk.Frame(preview_card, style="Card.TFrame")
        info.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        info.columnconfigure(0, weight=1)
        ttk.Label(
            info,
            textvariable=self.preview_meta_var,
            style="Hint.TLabel",
            justify="left",
            wraplength=1040,
        ).grid(row=0, column=0, sticky="w")

        preview_viewport = ttk.Frame(preview_card, style="Card.TFrame")
        preview_viewport.grid(row=2, column=0, sticky="nsew")
        preview_viewport.columnconfigure(0, weight=1)
        preview_viewport.rowconfigure(0, weight=1)

        self.opengl_preview = OpenGLPreviewHost(preview_viewport)
        self.embedded_preview_canvas: tk.Canvas | None = None
        if self.opengl_preview.available:
            self.preview_backend_var.set("預覽後端：OpenGL (VTK)")
            self.preview_view_var.set("視角：由 OpenGL 視窗滑鼠控制（拖曳旋轉 / 滾輪縮放）")
        else:
            self.preview_backend_var.set(f"預覽後端：Canvas fallback（{self.opengl_preview.message}）")
            self.embedded_preview_canvas = tk.Canvas(
                preview_viewport,
                background=INPUT_BG,
                highlightthickness=1,
                highlightbackground=BORDER,
                relief="flat",
            )
            self.embedded_preview_canvas.grid(row=0, column=0, sticky="nsew")
            self.embedded_preview_canvas.bind("<Configure>", self._redraw_embedded_preview)
            self.embedded_preview_canvas.bind("<ButtonPress-1>", self._start_preview_drag)
            self.embedded_preview_canvas.bind("<B1-Motion>", self._drag_preview_view)
            self.embedded_preview_canvas.bind("<ButtonRelease-1>", self._end_preview_drag)
            self.embedded_preview_canvas.bind("<Double-Button-1>", self._reset_preview_view)
            self.embedded_preview_canvas.bind("<MouseWheel>", self._zoom_preview_view)
            self.embedded_preview_canvas.bind("<Button-4>", self._zoom_preview_view)
            self.embedded_preview_canvas.bind("<Button-5>", self._zoom_preview_view)
        self._apply_preview_sensitivity()
        ttk.Label(
            preview_card,
            textvariable=self.preview_group_var,
            style="Hint.TLabel",
            justify="left",
            wraplength=1040,
        ).grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.after(50, lambda: self._draw_preview_placeholder("請執行 ATH，或載入最新輸出以在此顯示幾何。"))

    def _build_bem_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)
        intro = ttk.LabelFrame(target, text="Build / Verify", style="Card.TLabelframe", padding=14)
        intro.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text="先確認目前 Base Design 能生成且能求解，再拿去做 Optimize。這一頁把 ATH 生成、mesh 檢查、BEM 執行與驗證摘要整合成一條流程。",
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w")

        generation_fields = tuple(
            spec
            for _section_name, _description, fields in FIELD_SECTIONS
            for spec in fields
            if spec.key in {
                "Mesh.Quadrants",
                "Mesh.AngularSegments",
                "Mesh.LengthSegments",
                "Mesh.ThroatResolution",
                "Mesh.MouthResolution",
                "Output.STL",
                "Output.MSH",
                "Output.ABECProject",
            }
        )

        generation_card = ttk.LabelFrame(target, text="ATH Generation", style="Card.TLabelframe", padding=14)
        generation_card.grid(row=1, column=0, sticky="ew", padx=14, pady=(14, 0))
        generation_card.columnconfigure(1, weight=1)
        ttk.Label(
            generation_card,
            text="從目前 Base Design 產生 ATH cfg / mesh 輸出。這裡先確認當前檔案、輸出路徑與生成相關設定。",
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        toolbar = ttk.Frame(generation_card, style="Card.TFrame")
        toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        toolbar.columnconfigure(5, weight=1)
        ttk.Button(toolbar, text="儲存 ATH cfg", style="Tool.TButton", command=self.save_horn_config).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="執行 ATH", style="Accent.TButton", command=self.run_ath).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(toolbar, text="更新文字預覽", style="Tool.TButton", command=self.refresh_preview).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="載入最新輸出", style="Tool.TButton", command=self.load_latest_output_preview).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(toolbar, text="開啟目前預覽", style="Tool.TButton", command=self.open_current_preview_external).grid(row=0, column=4, padx=(0, 8))
        ttk.Label(toolbar, textvariable=self.preview_status_var, style="Hint.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(toolbar, textvariable=self.output_dir_var, style="Hint.TLabel", wraplength=520, justify="left").grid(
            row=1,
            column=2,
            columnspan=4,
            sticky="e",
            pady=(10, 0),
        )
        ttk.Label(generation_card, text="目前 ATH cfg", style="CardLabel.TLabel").grid(row=2, column=0, sticky="nw", padx=(0, 14), pady=(0, 8))
        ttk.Label(generation_card, textvariable=self.current_cfg_var, style="Hint.TLabel", wraplength=720, justify="left").grid(
            row=2,
            column=1,
            sticky="nw",
            pady=(0, 8),
        )
        ttk.Label(generation_card, text="最新預覽", style="CardLabel.TLabel").grid(row=3, column=0, sticky="nw", padx=(0, 14), pady=(0, 8))
        ttk.Label(generation_card, textvariable=self.preview_path_var, style="Hint.TLabel", wraplength=720, justify="left").grid(
            row=3,
            column=1,
            sticky="nw",
            pady=(0, 8),
        )
        self._populate_card(generation_card, generation_fields, {}, start_row=4, shared_widget_map=self.horn_widgets)

        mesh_card = ttk.LabelFrame(target, text="Mesh Check", style="Card.TLabelframe", padding=14)
        mesh_card.grid(row=2, column=0, sticky="ew", padx=14, pady=(14, 0))
        mesh_card.columnconfigure(1, weight=1)
        ttk.Label(
            mesh_card,
            text="確認目前 mesh 是否成功建立、群組是否合理，以及右側工作區是否已有可供檢查的 3D / mesh 摘要。",
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        mesh_toolbar = ttk.Frame(mesh_card, style="Card.TFrame")
        mesh_toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        mesh_toolbar.columnconfigure(5, weight=1)
        ttk.Button(mesh_toolbar, text="自動偵測網格", style="Tool.TButton", command=self.autofill_bem_mesh).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(mesh_toolbar, text="檢查網格", style="Tool.TButton", command=self.inspect_bem_mesh).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(mesh_toolbar, text="查看 3D 幾何", style="Tool.TButton", command=lambda: self._select_workspace_tab("Geometry3D")).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(mesh_toolbar, text="查看網格摘要", style="Tool.TButton", command=lambda: self._select_workspace_tab("MeshInfo")).grid(row=0, column=3, padx=(0, 8))
        ttk.Label(mesh_card, text="Mesh 狀態", style="CardLabel.TLabel").grid(row=2, column=0, sticky="nw", padx=(0, 14), pady=(0, 8))
        ttk.Label(mesh_card, textvariable=self.mesh_status_var, style="Hint.TLabel", wraplength=720, justify="left").grid(
            row=2,
            column=1,
            sticky="nw",
            pady=(0, 8),
        )
        ttk.Label(mesh_card, text="群組摘要", style="CardLabel.TLabel").grid(row=3, column=0, sticky="nw", padx=(0, 14), pady=(0, 8))
        ttk.Label(mesh_card, textvariable=self.preview_group_var, style="Hint.TLabel", wraplength=720, justify="left").grid(
            row=3,
            column=1,
            sticky="nw",
            pady=(0, 8),
        )

        controls_card = ttk.LabelFrame(target, text="BEM Run", style="Card.TLabelframe", padding=14)
        controls_card.grid(row=3, column=0, sticky="ew", padx=14, pady=(14, 0))
        controls_card.columnconfigure(0, weight=1)
        ttk.Label(
            controls_card,
            text="目前 BEM backend、頻段、平面與結果狀態都集中在這裡。先在這裡確認可求解，再把同一份基準設計拿去最佳化。",
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        toolbar = ttk.Frame(controls_card, style="Card.TFrame")
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        toolbar.columnconfigure(6, weight=1)
        ttk.Button(toolbar, text="執行 BEM", style="Accent.TButton", command=self.run_bempp).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="重新載入結果", style="Tool.TButton", command=self.load_bem_results).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(toolbar, text="開啟求解器日誌", style="Tool.TButton", command=self.open_bem_solver_log).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="查看 BEM 摘要", style="Tool.TButton", command=lambda: self._select_workspace_tab("Summary")).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(toolbar, text="查看指向性", style="Tool.TButton", command=lambda: self._select_workspace_tab("Polar")).grid(row=0, column=4, padx=(0, 8))
        ttk.Label(toolbar, textvariable=self.bem_status_var, style="Hint.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(toolbar, textvariable=self.bem_result_path_var, style="Hint.TLabel", wraplength=620, justify="left").grid(
            row=1,
            column=2,
            columnspan=5,
            sticky="e",
            pady=(10, 0),
        )
        ttk.Label(toolbar, textvariable=self.run_all_status_var, style="Hint.TLabel", wraplength=720, justify="left").grid(
            row=2,
            column=0,
            columnspan=7,
            sticky="w",
            pady=(6, 0),
        )

        self.build_verify_bem_text = self._make_dark_text(controls_card, height=8, wrap="word")
        self.build_verify_bem_text.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        self.build_verify_bem_text.configure(state="disabled")

        inner_rows = 3
        for description, fields in BEM_FIELD_SECTIONS:
            card = ttk.LabelFrame(controls_card, text=description, style="Card.TLabelframe", padding=14)
            card.grid(row=inner_rows, column=0, sticky="ew", pady=(0, 14))
            card.columnconfigure(1, weight=1)
            self._populate_card(card, fields, self.bem_widgets)
            inner_rows += 1

        summary_card = ttk.LabelFrame(target, text="Verification Summary", style="Card.TLabelframe", padding=14)
        summary_card.grid(row=4, column=0, sticky="ew", padx=14, pady=(14, 18))
        summary_card.columnconfigure(0, weight=1)
        ttk.Label(
            summary_card,
            text="這裡整理目前 Base Design 是否已經可生成、可網格化、可求解，以及還有哪些關鍵警告需要先處理。",
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.verification_summary_text = self._make_dark_text(summary_card, height=11, wrap="word")
        self.verification_summary_text.grid(row=1, column=0, sticky="ew")
        self.verification_summary_text.configure(state="disabled")

    def _build_optimizer_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)

        intro = ttk.LabelFrame(target, text="Optimize", style="Card.TLabelframe", padding=14)
        intro.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=(
                "這一頁不再只是一組 study 參數，而是完整的最佳化上下文頁。"
                "先看目前基準條件、限制條件與 search space，再決定是否開始 study。"
            ),
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w")

        base_card = ttk.LabelFrame(target, text="Optimization Base Conditions", style="Card.TLabelframe", padding=14)
        base_card.grid(row=1, column=0, sticky="ew", padx=14, pady=(14, 0))
        base_card.columnconfigure(0, weight=1)
        ttk.Label(
            base_card,
            text=(
                "Source: Current GUI Design State。Optimize 會從目前 GUI 欄位組出的 DesignRecipe、horn state、BEM state 開始，"
                "不是從隱藏預設值開始。"
            ),
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.optimize_base_conditions_text = self._make_dark_text(base_card, height=12, wrap="word")
        self.optimize_base_conditions_text.grid(row=1, column=0, sticky="ew")
        self.optimize_base_conditions_text.configure(state="disabled")

        constraint_fields = (*OPTIMIZER_OBJECTIVE_FIELDS, *OPTIMIZER_CONSTRAINT_FIELDS)
        constraint_card = ttk.LabelFrame(target, text="Driver & Product Constraints", style="Card.TLabelframe", padding=14)
        constraint_card.grid(row=2, column=0, sticky="ew", padx=14, pady=(14, 0))
        constraint_card.columnconfigure(1, weight=1)
        ttk.Label(
            constraint_card,
            text=(
                "這裡整理單體與產品限制。若未提供明確 JSON / 包裝限制，GUI 會先顯示目前能從 recipe 保守推估的限制與 derived preview。"
            ),
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self._populate_card(constraint_card, constraint_fields, self.optimizer_widgets, start_row=1)
        derived_row = 1 + len(constraint_fields)
        ttk.Label(
            constraint_card,
            text="Derived preview",
            style="CardLabel.TLabel",
        ).grid(row=derived_row, column=0, sticky="nw", padx=(0, 14), pady=(6, 0))
        self.optimize_constraints_text = self._make_dark_text(constraint_card, height=11, wrap="word")
        self.optimize_constraints_text.grid(row=derived_row, column=1, sticky="ew", pady=(6, 0))
        self.optimize_constraints_text.configure(state="disabled")

        search_card = ttk.LabelFrame(target, text="Search Space Preview", style="Card.TLabelframe", padding=14)
        search_card.grid(row=3, column=0, sticky="ew", padx=14, pady=(14, 0))
        search_card.columnconfigure(0, weight=1)
        ttk.Label(
            search_card,
            text="清楚列出 fixed variables、optimized variables、bounds 與目前能說明的原因。若某些欄位因目前模式不啟用，也會在這裡標出。",
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.optimize_search_space_text = self._make_dark_text(search_card, height=14, wrap="word")
        self.optimize_search_space_text.grid(row=1, column=0, sticky="ew")
        self.optimize_search_space_text.configure(state="disabled")

        action_card = ttk.LabelFrame(target, text="Study Controls", style="Card.TLabelframe", padding=14)
        action_card.grid(row=4, column=0, sticky="ew", padx=14, pady=(14, 18))
        action_card.columnconfigure(4, weight=1)
        ttk.Button(action_card, text="開始最佳化", style="Accent.TButton", command=self.run_optimizer_study).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(action_card, text="完成當前 Trial 後停止", style="Tool.TButton", command=self.stop_optimizer_study).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(action_card, text="套用最佳結果", style="Tool.TButton", command=self.apply_best_optimizer_trial).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(action_card, text="開啟 Study 目錄", style="Tool.TButton", command=self.open_optimizer_study_dir).grid(row=0, column=3, padx=(0, 8))
        ttk.Label(action_card, textvariable=self.optimizer_status_var, style="Hint.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(action_card, textvariable=self.optimizer_trial_var, style="Hint.TLabel").grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Label(action_card, textvariable=self.optimizer_best_score_var, style="Hint.TLabel").grid(row=1, column=3, sticky="w", pady=(10, 0))
        ttk.Label(action_card, textvariable=self.optimizer_study_dir_var, style="Hint.TLabel", wraplength=700, justify="left").grid(
            row=2,
            column=0,
            columnspan=5,
            sticky="w",
            pady=(8, 0),
        )
        self._populate_card(action_card, OPTIMIZER_STUDY_FIELDS, self.optimizer_widgets, start_row=3)

    def _build_results_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)

        intro = ttk.LabelFrame(target, text="Results", style="Card.TLabelframe", padding=14)
        intro.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text="右側工作區仍是主要結果顯示區；這一頁負責把常用結果頁與 workspace 動作整理成可導航的入口。",
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w")

        nav_card = ttk.LabelFrame(target, text="Workspace Navigation", style="Card.TLabelframe", padding=14)
        nav_card.grid(row=1, column=0, sticky="ew", padx=14, pady=(14, 0))
        for column in range(3):
            nav_card.columnconfigure(column, weight=1)
        buttons = (
            ("3D 幾何", "Geometry3D"),
            ("指向性", "Polar"),
            ("網格摘要", "MeshInfo"),
            ("BEM 摘要", "Summary"),
            ("最佳化", "Study"),
            ("設定文字", "TextPreview"),
        )
        for index, (label, key) in enumerate(buttons):
            ttk.Button(nav_card, text=label, style="Tool.TButton", command=lambda tab_key=key: self._select_workspace_tab(tab_key)).grid(
                row=index // 3,
                column=index % 3,
                padx=6,
                pady=6,
                sticky="ew",
            )

        action_card = ttk.LabelFrame(target, text="Workspace Actions", style="Card.TLabelframe", padding=14)
        action_card.grid(row=2, column=0, sticky="ew", padx=14, pady=(14, 0))
        action_card.columnconfigure(2, weight=1)
        ttk.Button(action_card, text="載入最新 workspace 結果", style="Tool.TButton", command=self.load_workspace_results).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(action_card, text="開啟最新 workspace", style="Tool.TButton", command=self.open_latest_workspace).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(action_card, text="載入最新輸出預覽", style="Tool.TButton", command=self.load_latest_output_preview).grid(row=0, column=2, padx=(0, 8), sticky="w")

        summary_card = ttk.LabelFrame(target, text="Results Overview", style="Card.TLabelframe", padding=14)
        summary_card.grid(row=3, column=0, sticky="ew", padx=14, pady=(14, 18))
        summary_card.columnconfigure(0, weight=1)
        self.results_overview_text = self._make_dark_text(summary_card, height=12, wrap="word")
        self.results_overview_text.grid(row=0, column=0, sticky="ew")
        self.results_overview_text.configure(state="disabled")

    def _build_optimizer_workspace_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)
        target.rowconfigure(1, weight=1)
        target.rowconfigure(2, weight=1)

        summary_card = ttk.LabelFrame(target, text="Study 摘要", style="Card.TLabelframe", padding=14)
        summary_card.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 10))
        summary_card.columnconfigure(1, weight=1)
        ttk.Label(summary_card, text="狀態", style="CardLabel.TLabel").grid(row=0, column=0, sticky="nw", padx=(0, 10))
        ttk.Label(summary_card, textvariable=self.optimizer_status_var, style="Hint.TLabel", wraplength=920, justify="left").grid(row=0, column=1, sticky="nw")
        ttk.Label(summary_card, text="Trial", style="CardLabel.TLabel").grid(row=1, column=0, sticky="nw", padx=(0, 10), pady=(8, 0))
        ttk.Label(summary_card, textvariable=self.optimizer_trial_var, style="Hint.TLabel").grid(row=1, column=1, sticky="nw", pady=(8, 0))
        ttk.Label(summary_card, text="Best", style="CardLabel.TLabel").grid(row=2, column=0, sticky="nw", padx=(0, 10), pady=(8, 0))
        ttk.Label(summary_card, textvariable=self.optimizer_best_score_var, style="Hint.TLabel").grid(row=2, column=1, sticky="nw", pady=(8, 0))
        ttk.Label(summary_card, text="Study Dir", style="CardLabel.TLabel").grid(row=3, column=0, sticky="nw", padx=(0, 10), pady=(8, 0))
        ttk.Label(summary_card, textvariable=self.optimizer_study_dir_var, style="Hint.TLabel", wraplength=920, justify="left").grid(
            row=3,
            column=1,
            sticky="nw",
            pady=(8, 0),
        )

        log_card = ttk.LabelFrame(target, text="Study Log", style="Card.TLabelframe", padding=14)
        log_card.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 10))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(0, weight=1)
        self.optimizer_log_text = self._make_dark_text(log_card, height=12, wrap="word")
        self.optimizer_log_text.grid(row=0, column=0, sticky="nsew")
        self.optimizer_log_text.configure(state="disabled")

        best_card = ttk.LabelFrame(target, text="Best Trial", style="Card.TLabelframe", padding=14)
        best_card.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 18))
        best_card.columnconfigure(0, weight=1)
        best_card.rowconfigure(0, weight=1)
        self.optimizer_best_text = self._make_dark_text(best_card, height=12, wrap="word")
        self.optimizer_best_text.grid(row=0, column=0, sticky="nsew")
        self.optimizer_best_text.configure(state="disabled")

    def _build_mesh_info_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)
        target.rowconfigure(0, weight=1)
        mesh_card = ttk.LabelFrame(target, text="網格檢查", style="Card.TLabelframe", padding=14)
        mesh_card.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 18))
        mesh_card.columnconfigure(0, weight=1)
        mesh_card.rowconfigure(0, weight=1)
        self.bem_mesh_text = self._make_dark_text(mesh_card, height=20, wrap="word")
        self.bem_mesh_text.grid(row=0, column=0, sticky="nsew")
        self.bem_mesh_text.configure(state="disabled")

    def _build_bem_summary_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)
        target.rowconfigure(0, weight=1)
        summary_card = ttk.LabelFrame(target, text="BEM 摘要", style="Card.TLabelframe", padding=14)
        summary_card.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 18))
        summary_card.columnconfigure(0, weight=1)
        summary_card.rowconfigure(0, weight=1)
        self.bem_summary_text = self._make_dark_text(summary_card, height=20, wrap="word")
        self.bem_summary_text.grid(row=0, column=0, sticky="nsew")
        self.bem_summary_text.configure(state="disabled")

    def _build_polar_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)
        target.rowconfigure(0, weight=1)
        plot_card = ttk.LabelFrame(target, text="極座標結果", style="Card.TLabelframe", padding=14)
        plot_card.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 18))
        plot_card.columnconfigure(0, weight=1)
        plot_card.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(plot_card, style="Card.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(5, weight=1)
        ttk.Label(toolbar, text="顯示模式：", style="CardLabel.TLabel").grid(row=0, column=0, sticky="w")
        mode_combo = ttk.Combobox(
            toolbar,
            textvariable=self.bem_plot_mode_var,
            values=("Smooth Display", "Raw", "Single Freq Polar"),
            state="readonly",
            width=18,
        )
        mode_combo.grid(row=0, column=1, sticky="w", padx=(6, 10))
        mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_bem_plot())
        ttk.Checkbutton(
            toolbar,
            text="X 軸 Log",
            variable=self.bem_plot_log_x_var,
            command=self._refresh_bem_plot,
        ).grid(row=0, column=2, sticky="w", padx=(0, 10))
        ttk.Button(toolbar, text="更新圖表", style="Tool.TButton", command=self._refresh_bem_plot).grid(row=0, column=3, sticky="w")
        ttk.Label(plot_card, textvariable=self.bem_plot_caption_var, style="Hint.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 10))
        self.bem_polar_canvas = tk.Canvas(
            plot_card,
            background=INPUT_BG,
            highlightthickness=1,
            highlightbackground=BORDER,
            relief="flat",
            height=460,
        )
        self.bem_polar_canvas.grid(row=2, column=0, sticky="nsew")
        self.bem_polar_canvas.bind("<Configure>", lambda _event: self._refresh_bem_plot())
        self.after(50, lambda: draw_bem_placeholder(self.bem_polar_canvas, "執行 BEM 後會在此顯示指向性曲線。"))

    def _populate_card(
        self,
        card: ttk.LabelFrame,
        fields: tuple[FieldSpec, ...],
        widget_map: dict[str, dict[str, object]],
        *,
        start_row: int = 0,
        shared_widget_map: dict[str, dict[str, object]] | None = None,
    ) -> None:
        row = start_row
        for spec in fields:
            label_widget = ttk.Label(card, text=spec.label, style="CardLabel.TLabel")
            label_widget.grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=(0, 12))
            control_frame = ttk.Frame(card, style="Card.TFrame")
            control_frame.grid(row=row, column=1, sticky="ew", pady=(0, 12))
            control_frame.columnconfigure(0, weight=1)
            browse_button: ttk.Button | None = None
            shared_data = shared_widget_map.get(spec.key) if shared_widget_map is not None else None

            if spec.kind == "check":
                if shared_data is not None and isinstance(shared_data.get("var"), tk.Variable):
                    var = shared_data["var"]
                else:
                    var = tk.BooleanVar(value=bool(spec.default))
                widget = ttk.Checkbutton(control_frame, variable=var)
                widget.grid(row=0, column=0, sticky="w")
                widget_map[spec.key] = {
                    "spec": spec,
                    "var": var,
                    "widget": widget,
                    "label_widget": label_widget,
                    "control_frame": control_frame,
                }
            elif spec.kind == "combo":
                if shared_data is not None and isinstance(shared_data.get("var"), tk.Variable):
                    var = shared_data["var"]
                else:
                    var = tk.StringVar(value=str(spec.default))
                widget = ttk.Combobox(control_frame, textvariable=var, values=spec.choices, width=spec.width, state="readonly")
                widget.grid(row=0, column=0, sticky="ew")
                widget_map[spec.key] = {
                    "spec": spec,
                    "var": var,
                    "widget": widget,
                    "label_widget": label_widget,
                    "control_frame": control_frame,
                }
            elif spec.kind == "multiline":
                height = 8 if spec.key == "ADVANCED.Raw" else 7
                widget = self._make_dark_text(control_frame, height=height, wrap="word")
                widget.grid(row=0, column=0, sticky="ew")
                widget_map[spec.key] = {
                    "spec": spec,
                    "widget": widget,
                    "label_widget": label_widget,
                    "control_frame": control_frame,
                }
            else:
                entry_frame = ttk.Frame(control_frame, style="Card.TFrame")
                entry_frame.grid(row=0, column=0, sticky="ew")
                entry_frame.columnconfigure(0, weight=1)
                if shared_data is not None and isinstance(shared_data.get("var"), tk.Variable):
                    var = shared_data["var"]
                else:
                    var = tk.StringVar(value=str(spec.default))
                widget = ttk.Entry(entry_frame, textvariable=var, width=spec.width)
                widget.grid(row=0, column=0, sticky="ew")
                widget_map[spec.key] = {
                    "spec": spec,
                    "var": var,
                    "widget": widget,
                    "label_widget": label_widget,
                    "control_frame": control_frame,
                }
                if spec.browse:
                    browse_button = ttk.Button(
                        entry_frame,
                        text="瀏覽",
                        style="Tool.TButton",
                        command=lambda key=spec.key, mode=spec.browse: self.browse_for_field(key, mode),
                    )
                    browse_button.grid(row=0, column=1, padx=(8, 0))
                    widget_map[spec.key]["browse_button"] = browse_button

            helper_text = build_field_hint(spec)
            hint_label = ttk.Label(
                control_frame,
                text=helper_text,
                style="Hint.TLabel",
                wraplength=700,
                justify="left",
            )
            hint_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
            widget_map[spec.key]["hint_label"] = hint_label
            widget_map[spec.key]["base_hint"] = helper_text
            if not helper_text:
                hint_label.grid_remove()
            row += 1

    def _set_field_visible(self, data: dict[str, object], *, visible: bool) -> None:
        label_widget = data.get("label_widget")
        control_frame = data.get("control_frame")
        if isinstance(label_widget, ttk.Label):
            if visible:
                label_widget.grid()
            else:
                label_widget.grid_remove()
        if isinstance(control_frame, ttk.Frame):
            if visible:
                control_frame.grid()
            else:
                control_frame.grid_remove()

    def _set_widget_enabled(self, data: dict[str, object], *, enabled: bool) -> None:
        spec: FieldSpec = data["spec"]
        widget = data["widget"]
        if spec.kind == "combo":
            widget.configure(state="readonly" if enabled else "disabled")
        elif spec.kind == "check":
            widget.state(["!disabled"] if enabled else ["disabled"])
        elif spec.kind == "multiline":
            widget.configure(state="normal" if enabled else "disabled")
        else:
            widget.configure(state="normal" if enabled else "disabled")

        browse_button = data.get("browse_button")
        if browse_button is not None:
            browse_button.state(["!disabled"] if enabled else ["disabled"])

    def apply_field_states(
        self,
        widget_map: dict[str, dict[str, object]],
        rules: dict[str, dict[str, object]],
        *,
        hide_irrelevant: bool,
        always_visible_keys: tuple[str, ...] = (),
    ) -> None:
        always_visible = set(always_visible_keys) if hide_irrelevant else set()
        for key, data in widget_map.items():
            rule = rules.get(key, {"relevant": True, "reason": ""})
            relevant = bool(rule.get("relevant", True))
            reason = str(rule.get("reason", "")).strip()
            visible = relevant or key in always_visible or not hide_irrelevant
            self._set_field_visible(data, visible=visible)
            self._set_widget_enabled(data, enabled=relevant)

            hint_label = data.get("hint_label")
            if isinstance(hint_label, ttk.Label):
                base_hint = str(data.get("base_hint", "")).strip()
                if relevant:
                    hint_text = base_hint
                else:
                    hint_text = f"{base_hint}\nIgnored: {reason}".strip() if base_hint else f"Ignored: {reason}"
                if hint_text:
                    hint_label.configure(text=hint_text)
                    hint_label.grid()
                else:
                    hint_label.grid_remove()

            label_widget = data.get("label_widget")
            if isinstance(label_widget, ttk.Label):
                label_widget.configure(style="CardLabel.TLabel" if relevant else "Hint.TLabel")

    def refresh_dependency_states(self) -> None:
        horn_state = self.collect_horn_state()
        horn_rules = build_guided_field_states(horn_state)
        self.apply_field_states(self.horn_widgets, horn_rules, hide_irrelevant=False)
        self.apply_field_states(self.base_design_widgets, horn_rules, hide_irrelevant=False)
        self.apply_field_states(
            self.guided_widgets,
            horn_rules,
            hide_irrelevant=True,
            always_visible_keys=GUIDED_ALWAYS_VISIBLE_KEYS,
        )

        ath_effective_state = sanitize_ath_state(horn_state)
        bem_rules = build_bem_guided_field_states(self.collect_bem_state(), ath_effective_state)
        self.apply_field_states(self.bem_widgets, bem_rules, hide_irrelevant=False)
        self.apply_field_states(
            self.guided_bem_widgets,
            bem_rules,
            hide_irrelevant=True,
            always_visible_keys=BEM_GUIDED_ALWAYS_VISIBLE_KEYS,
        )

    def _on_dependency_field_changed(self, *_args: object) -> None:
        if self._suspend_dependency_refresh:
            return
        self.refresh_dependency_states()

    def _bind_dependency_traces(self) -> None:
        for key in GUIDED_CONTROLLER_KEYS:
            data = self.horn_widgets.get(key)
            if not data:
                continue
            variable = data.get("var")
            if isinstance(variable, tk.Variable):
                token = variable.trace_add("write", self._on_dependency_field_changed)
                self._dependency_trace_tokens.append((variable, token))

        for key in BEM_GUIDED_CONTROLLER_KEYS:
            data = self.bem_widgets.get(key)
            if not data:
                continue
            variable = data.get("var")
            if isinstance(variable, tk.Variable):
                token = variable.trace_add("write", self._on_dependency_field_changed)
                self._dependency_trace_tokens.append((variable, token))

    def _on_quick_field_changed(self, *_args: object) -> None:
        if self._suspend_quick_sync:
            return
        self._quick_dirty = True

    def _bind_quick_traces(self) -> None:
        for data in self.quick_widgets.values():
            variable = data.get("var")
            if isinstance(variable, tk.Variable):
                token = variable.trace_add("write", self._on_quick_field_changed)
                self._quick_trace_tokens.append((variable, token))

    def _on_context_field_changed(self, *_args: object) -> None:
        self._request_context_refresh()

    def _bind_context_traces(self) -> None:
        for widget_map in (self.global_widgets, self.horn_widgets, self.bem_widgets, self.optimizer_widgets):
            for data in widget_map.values():
                variable = data.get("var")
                if isinstance(variable, tk.Variable):
                    token = variable.trace_add("write", self._on_context_field_changed)
                    self._context_trace_tokens.append((variable, token))

    def _request_context_refresh(self) -> None:
        if self._context_refresh_after_id is not None:
            return
        self._context_refresh_after_id = self.after(80, self._refresh_context_panels)

    def _format_number(self, value: object | None, *, unit: str = "", digits: int = 1) -> str:
        if value is None:
            return "-"
        text = str(value).strip()
        if not text:
            return "-"
        try:
            numeric = float(text)
        except Exception:
            return f"{text}{unit}"
        if abs(numeric - round(numeric)) < 1.0e-9:
            base = str(int(round(numeric)))
        else:
            base = f"{numeric:.{digits}f}"
        return f"{base}{unit}"

    def _format_bool_text(self, value: object) -> str:
        return "yes" if bool(value) else "no"

    def _status_line(self, ok: bool, label: str, detail: str) -> str:
        marker = "[OK]" if ok else "[!]"
        return f"{marker} {label}: {detail}"

    def _friendly_bounds_source(self, source: object, reason: object | None = None) -> str:
        source_text = str(source or "").strip()
        mapping = {
            "driver_profile.fixed_throat": "fixed because tied to driver throat",
            "driver_type": "fixed because current driver type fixes source mode",
            "derived_or_base": "bounded by derived geometry limits and current base recipe",
            "derived_or_target": "bounded by target BW / recommended coverage",
            "derived_or_product": "bounded by product and derived mouth limits",
            "derived_from_mouth": "bounded by current mouth geometry",
            "base_recipe_fallback": "bounded conservatively around current base recipe",
        }
        if source_text in mapping:
            return mapping[source_text]
        reason_text = str(reason or "").strip()
        if reason_text:
            return reason_text
        return source_text or "bounded conservatively from current context"

    def _resolve_optimizer_preview_context(self) -> dict[str, object]:
        from optimizer.design_space import build_design_space, build_initial_seed_params
        from optimizer.driver_profile import (
            ProductConstraints,
            infer_driver_profile_from_recipe,
            infer_product_constraints_from_recipe,
            load_driver_profile,
        )

        optimizer_state = self.collect_optimizer_state()
        recipe = self.collect_design_recipe()

        def _as_optional_float(key: str) -> float | None:
            text = str(optimizer_state.get(key, "")).strip()
            if not text:
                return None
            return float(text)

        target_bw_h = _as_optional_float("OPT.TargetBWH")
        target_bw_v = _as_optional_float("OPT.TargetBWV")
        inferred_constraints = infer_product_constraints_from_recipe(
            recipe,
            target_bw_h_deg=target_bw_h,
            target_bw_v_deg=target_bw_v,
        )
        constraints = replace(
            inferred_constraints,
            max_baffle_width_mm=_as_optional_float("OPT.MaxBaffleWidth") or inferred_constraints.max_baffle_width_mm,
            max_baffle_height_mm=_as_optional_float("OPT.MaxBaffleHeight") or inferred_constraints.max_baffle_height_mm,
            max_depth_mm=_as_optional_float("OPT.MaxDepth") or inferred_constraints.max_depth_mm,
            min_wall_thickness_mm=_as_optional_float("OPT.MinWallThickness") or inferred_constraints.min_wall_thickness_mm,
            target_bw_h_deg=target_bw_h if target_bw_h is not None else inferred_constraints.target_bw_h_deg,
            target_bw_v_deg=target_bw_v if target_bw_v is not None else inferred_constraints.target_bw_v_deg,
            target_low_freq_hz=_as_optional_float("OPT.TargetLowFreq") or inferred_constraints.target_low_freq_hz,
            target_high_freq_hz=_as_optional_float("OPT.TargetHighFreq") or inferred_constraints.target_high_freq_hz,
        )

        profile_path_text = str(optimizer_state.get("OPT.DriverProfilePath", "")).strip()
        if profile_path_text:
            profile_path = Path(profile_path_text).expanduser().resolve()
            driver_profile = load_driver_profile(profile_path)
            driver_source = f"loaded from {profile_path}"
        else:
            profile_path = None
            driver_profile = infer_driver_profile_from_recipe(recipe)
            driver_source = "inferred from current recipe"

        design_space = build_design_space(driver_profile, constraints, base_recipe=recipe)
        seed_params = build_initial_seed_params(driver_profile, constraints)
        return {
            "recipe": recipe,
            "optimizer_state": optimizer_state,
            "driver_profile": driver_profile,
            "driver_source": driver_source,
            "driver_profile_path": profile_path,
            "product_constraints": constraints,
            "design_space": design_space,
            "seed_params": seed_params,
        }

    def _build_base_design_summary_text(self) -> str:
        recipe = self.collect_design_recipe()
        errors = recipe.validate()
        lines = [
            "This page is the baseline snapshot for Generate / BEM / Optimize.",
            "",
            "Current Base Design",
            f"- Case: {recipe.case_name}",
            f"- Throat: {self._format_number(recipe.throat_diameter, unit=' mm')}",
            f"- Horn length: {self._format_number(recipe.horn_length, unit=' mm')}",
            f"- Coverage target: {self._format_number(recipe.coverage_angle, unit=' deg')} (single-angle recipe field)",
            f"- Mouth: {self._format_number(recipe.mouth_width, unit=' mm')} x {self._format_number(recipe.mouth_height, unit=' mm')}",
            f"- Corner radius: {self._format_number(recipe.mouth_corner_radius, unit=' mm')}",
            f"- BEM band: {self._format_number(recipe.bem_f1, unit=' Hz')} -> {self._format_number(recipe.bem_f2, unit=' Hz')} ({recipe.bem_num_freq} pts)",
            f"- Observation plane: {recipe.observation_plane}",
            f"- Symmetry: {self._format_bool_text(recipe.symmetry_enabled)} {recipe.symmetry_planes if recipe.symmetry_planes else ''}".rstrip(),
            f"- Current cfg path: {self.current_cfg_var.get()}",
        ]
        if errors:
            lines.extend(["", "Recipe validation", *[f"- {error}" for error in errors]])
        return "\n".join(lines)

    def _build_build_verify_bem_text(self) -> str:
        ath_state = self.collect_effective_horn_state()
        bem_state = self.collect_effective_bem_state(ath_state)
        bem_runtime = build_bem_runtime_settings(bem_state, ath_state)
        lines = [
            "Current BEM context",
            f"- Enabled: {self._format_bool_text(bem_runtime.get('enabled', False))}",
            f"- Backend: {bem_runtime.get('backend', '-')}",
            f"- Mesh source: {bem_runtime.get('mesh_source_mode', '-')}",
            f"- Group mode: {bem_runtime.get('group_mode', '-')}",
            f"- Frequency: {self._format_number(bem_state.get('BEM.F1'), unit=' Hz')} -> {self._format_number(bem_state.get('BEM.F2'), unit=' Hz')} ({bem_state.get('BEM.NumFreq', '-') } pts)",
            f"- Plane: {bem_state.get('BEM.Plane', '-')} | Symmetry: {bem_state.get('BEM.SymmetryMode', '-')}",
            f"- Mic distance: {self._format_number(bem_state.get('BEM.MicDistance'), unit=' m', digits=2)}",
            f"- Result status: {self.bem_status_var.get()}",
        ]
        return "\n".join(lines)

    def _build_verification_summary_text(self) -> str:
        recipe = self.collect_design_recipe()
        errors = recipe.validate()
        preview_status = self.preview_status_var.get()
        mesh_status = self.mesh_status_var.get()
        bem_status = self.bem_status_var.get()
        ath_ok = ("已載入" in preview_status) or (self.last_generated_preview_file is not None)
        mesh_ok = bool(mesh_status.strip()) and mesh_status not in {"尚未指定", "BEM automation 關閉"}
        bem_ok = any(token in bem_status for token in ("完成", "done", "Done"))

        warnings: list[str] = []
        if not self.current_horn_path.get().strip():
            warnings.append("目前 ATH cfg 尚未另存為檔案；若要追蹤輸出與 workspace，建議先儲存。")
        if errors:
            warnings.append("Base Design 仍有 recipe validation 問題，建議先修正後再執行。")
        if not ath_ok:
            warnings.append("尚未確認可生成的 ATH 輸出；請先執行 ATH 或載入最新輸出。")
        if not mesh_ok:
            warnings.append("尚未確認可用 mesh。若 BEM 需要 `latest_ath_output`，請先執行 ATH 並確認 `.msh` 已產生。")
        if not bem_ok:
            warnings.append("尚未完成 BEM 求解；請先確認 BEM 設定與群組映射。")

        lines = [
            self._status_line(not errors, "Recipe validity", "current GUI state can compile into DesignRecipe" if not errors else "needs fixes"),
            self._status_line(ath_ok, "ATH generation", preview_status),
            self._status_line(mesh_ok, "Mesh availability", mesh_status),
            self._status_line(bem_ok, "BEM solve", bem_status),
            "",
            "Warnings / next checks",
        ]
        lines.extend(f"- {warning}" for warning in warnings) if warnings else lines.append("- No blocking warning detected from current UI snapshot.")
        return "\n".join(lines)

    def _build_optimize_base_conditions_text(self, preview_context: dict[str, object] | None, preview_error: str | None) -> str:
        recipe = self.collect_design_recipe()
        ath_state = sanitize_ath_state(self.collect_horn_state(normalize_locked=True))
        bem_runtime = build_bem_runtime_settings(sanitize_bem_state(self.collect_bem_state(), ath_state), ath_state)
        optimizer_state = self.collect_optimizer_state()
        lines = [
            "Source: Current GUI Design State",
            "- `OptimizationController.start_from_ui()` snapshots current recipe, horn state, BEM state, and global state when you press Start.",
            "",
            "Base recipe snapshot",
            f"- Case: {recipe.case_name}",
            f"- Throat / length / coverage: {self._format_number(recipe.throat_diameter, unit=' mm')} / {self._format_number(recipe.horn_length, unit=' mm')} / {self._format_number(recipe.coverage_angle, unit=' deg')}",
            f"- Mouth / corner: {self._format_number(recipe.mouth_width, unit=' mm')} x {self._format_number(recipe.mouth_height, unit=' mm')} / {self._format_number(recipe.mouth_corner_radius, unit=' mm')}",
            f"- BEM band: {self._format_number(recipe.bem_f1, unit=' Hz')} -> {self._format_number(recipe.bem_f2, unit=' Hz')} ({recipe.bem_num_freq} pts)",
            f"- Observation plane: {recipe.observation_plane}",
            "",
            "BEM / global context",
            f"- Backend: {bem_runtime.get('backend', '-')}",
            f"- Study planes: {optimizer_state.get('OPT.Planes', 'XZ+YZ')}",
            f"- Output root: {self.collect_global_state().get('OutputRootDir', '') or '(default project path)'}",
            f"- Enqueue base recipe: {self._format_bool_text(optimizer_state.get('OPT.EnqueueBase', True))}",
        ]
        if preview_context is not None:
            seed = dict(preview_context.get("seed_params", {}))
            lines.extend(
                [
                    "",
                    "Also prepared for the study",
                    f"- Driver-aware initial seed horn length: {self._format_number(seed.get('horn_length'), unit=' mm')}",
                    f"- Driver-aware initial seed mouth: {self._format_number(seed.get('mouth_width'), unit=' mm')} x {self._format_number(seed.get('mouth_height'), unit=' mm')}",
                ]
            )
        if preview_error:
            lines.extend(["", f"Constraint/search preview error: {preview_error}"])
        return "\n".join(lines)

    def _build_constraints_preview_text(self, preview_context: dict[str, object] | None, preview_error: str | None) -> str:
        if preview_context is None:
            return f"Unable to resolve driver/product constraints preview.\n- {preview_error or 'unknown error'}"
        driver_profile = preview_context["driver_profile"]
        product_constraints = preview_context["product_constraints"]
        design_space = preview_context["design_space"]
        derived = design_space.derived
        lines = [
            "Driver profile",
            f"- Source: {preview_context.get('driver_source', '-')}",
            f"- ID / name: {driver_profile.driver_id} / {driver_profile.name}",
            f"- Type: {driver_profile.driver_type}",
            f"- Throat: {self._format_number(driver_profile.throat_diameter_mm, unit=' mm')}",
            f"- Exit angle: {self._format_number(driver_profile.exit_angle_deg, unit=' deg')}",
            f"- Mounting flange: {self._format_number(driver_profile.mounting_flange_diameter_mm, unit=' mm')}",
            f"- Preferred max coverage: {self._format_number(driver_profile.preferred_max_coverage_deg, unit=' deg')}",
            "",
            "Product constraints",
            f"- Max baffle: {self._format_number(product_constraints.max_baffle_width_mm, unit=' mm')} x {self._format_number(product_constraints.max_baffle_height_mm, unit=' mm')}",
            f"- Max depth: {self._format_number(product_constraints.max_depth_mm, unit=' mm')}",
            f"- Min wall thickness: {self._format_number(product_constraints.min_wall_thickness_mm, unit=' mm')}",
            f"- Target BW H / V: {self._format_number(product_constraints.target_bw_h_deg, unit=' deg')} / {self._format_number(product_constraints.target_bw_v_deg, unit=' deg')}",
            f"- Target low / high: {self._format_number(product_constraints.target_low_freq_hz, unit=' Hz')} / {self._format_number(product_constraints.target_high_freq_hz, unit=' Hz')}",
            "",
            "Derived preview",
            f"- Fixed throat: {self._format_number(derived.fixed_throat_diameter_mm, unit=' mm')}",
            f"- Mouth min: {self._format_number(derived.min_mouth_width_mm, unit=' mm')} x {self._format_number(derived.min_mouth_height_mm, unit=' mm')}",
            f"- Mouth max: {self._format_number(derived.max_mouth_width_mm, unit=' mm')} x {self._format_number(derived.max_mouth_height_mm, unit=' mm')}",
            f"- Horn length min / max: {self._format_number(derived.min_horn_length_mm, unit=' mm')} / {self._format_number(derived.max_horn_length_mm, unit=' mm')}",
            f"- Corner radius max: {self._format_number(derived.max_corner_radius_mm, unit=' mm')}",
            f"- Recommended coverage H: {derived.recommended_coverage_h_range_deg or '-'}",
            f"- Recommended coverage V: {derived.recommended_coverage_v_range_deg or '-'}",
        ]
        if derived.notes:
            lines.extend(["", "Notes", *[f"- {note}" for note in derived.notes[:6]]])
        return "\n".join(lines)

    def _build_search_space_preview_text(self, preview_context: dict[str, object] | None, preview_error: str | None) -> str:
        if preview_context is None:
            return f"Unable to build search-space preview.\n- {preview_error or 'unknown error'}"
        design_space = preview_context["design_space"]
        seed_params = dict(preview_context.get("seed_params", {}))
        lines = ["Fixed variables"]
        fixed_vars = design_space.fixed_variables()
        if fixed_vars:
            for name, variable in fixed_vars.items():
                lines.append(
                    f"- {name}: {variable.fixed_value} | {self._friendly_bounds_source(variable.metadata.get('reason'), variable.metadata.get('activation'))}"
                )
        else:
            lines.append("- (none)")

        lines.extend(["", "Optimized variables"])
        active_rows = [
            (name, variable)
            for name, variable in design_space.active_variables().items()
            if variable.kind != "fixed"
        ]
        if active_rows:
            for name, variable in active_rows:
                if variable.kind == "categorical":
                    bound_text = f"choices={variable.choices or []}"
                else:
                    bound_text = f"[{self._format_number(variable.low)} .. {self._format_number(variable.high)}]"
                lines.append(
                    f"- {name}: {bound_text} | {self._friendly_bounds_source(variable.metadata.get('bounds_source'), variable.metadata.get('reason'))}"
                )
        else:
            lines.append("- (none)")

        inactive_rows = [
            (name, variable)
            for name, variable in design_space.variables.items()
            if not variable.active and variable.kind != "fixed"
        ]
        lines.extend(["", "Inactive / compatibility-gated"])
        if inactive_rows:
            for name, variable in inactive_rows:
                lines.append(
                    f"- {name}: inactive | {self._friendly_bounds_source(variable.metadata.get('activation'), variable.metadata.get('reason'))}"
                )
        else:
            lines.append("- (none)")

        lines.extend(["", "Driver-aware initial seed"])
        if seed_params:
            for key, value in sorted(seed_params.items()):
                lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def _build_results_overview_text(self) -> str:
        lines = [
            "Current result pointers",
            f"- Preview: {self.preview_status_var.get()}",
            f"- Preview file: {self.preview_path_var.get()}",
            f"- Mesh: {self.mesh_status_var.get()}",
            f"- BEM: {self.bem_status_var.get()}",
            f"- BEM result: {self.bem_result_path_var.get()}",
            f"- Optimize: {self.optimizer_status_var.get()}",
            f"- Study dir: {self.optimizer_study_dir_var.get()}",
            f"- Workflow: {self.run_all_stage_var.get()} | {self.run_all_status_var.get()}",
            f"- Workspace: {self.run_all_workspace_var.get()}",
            "",
            "Use the buttons above to jump to the corresponding workspace tab on the right.",
        ]
        return "\n".join(lines)

    def _refresh_context_panels(self) -> None:
        self._context_refresh_after_id = None
        preview_context: dict[str, object] | None = None
        preview_error: str | None = None
        try:
            preview_context = self._resolve_optimizer_preview_context()
        except Exception as exc:
            preview_error = str(exc)

        updates: list[tuple[tk.Text | None, str]] = [
            (self.base_design_summary_text, self._build_base_design_summary_text()),
            (self.build_verify_bem_text, self._build_build_verify_bem_text()),
            (self.verification_summary_text, self._build_verification_summary_text()),
            (self.optimize_base_conditions_text, self._build_optimize_base_conditions_text(preview_context, preview_error)),
            (self.optimize_constraints_text, self._build_constraints_preview_text(preview_context, preview_error)),
            (self.optimize_search_space_text, self._build_search_space_preview_text(preview_context, preview_error)),
            (self.results_overview_text, self._build_results_overview_text()),
        ]
        for widget, text in updates:
            if widget is not None:
                self._set_text_widget(widget, text)

    def sync_quick_to_horn(self) -> None:
        if not self.quick_widgets:
            return
        self._suspend_dependency_refresh = True
        try:
            for key, quick_data in self.quick_widgets.items():
                horn_data = self.horn_widgets.get(key)
                if horn_data is None:
                    continue
                self._set_widget_value(horn_data, self._get_widget_value(quick_data))
        finally:
            self._suspend_dependency_refresh = False
        self._quick_dirty = False
        self.refresh_dependency_states()

    def sync_horn_to_quick(self) -> None:
        if not self.quick_widgets:
            return
        self._suspend_quick_sync = True
        try:
            for key, quick_data in self.quick_widgets.items():
                horn_data = self.horn_widgets.get(key)
                if horn_data is None:
                    continue
                self._set_widget_value(quick_data, self._get_widget_value(horn_data))
        finally:
            self._suspend_quick_sync = False
        self._quick_dirty = False

    def _on_controls_tab_changed(self, _event: tk.Event | None = None) -> None:
        quick_tab = str(self.control_tabs.get("QuickStart", ""))
        if not quick_tab:
            return
        current_tab = str(self.notebook.select())
        previous_tab = str(self._active_controls_tab_id)
        if current_tab == quick_tab:
            self.sync_horn_to_quick()
        elif previous_tab == quick_tab and self._quick_dirty:
            self.sync_quick_to_horn()
        self._active_controls_tab_id = current_tab

    def browse_for_field(self, key: str, mode: str) -> None:
        if mode == "dir":
            chosen = filedialog.askdirectory(initialdir=str(ROOT_DIR))
        else:
            chosen = filedialog.askopenfilename(initialdir=str(ROOT_DIR))
        if not chosen:
            return
        if key in self.global_widgets:
            target = self.global_widgets
        elif key in self.horn_widgets:
            target = self.horn_widgets
        elif key in self.optimizer_widgets:
            target = self.optimizer_widgets
        else:
            target = self.bem_widgets
        self._set_widget_value(target[key], chosen)
        self.status_var.set(f"已為 {key} 選擇路徑。")
        if key not in self.bem_widgets and key not in self.optimizer_widgets:
            self.refresh_preview()
        self._update_runtime_status()

    def _get_widget_value(self, data: dict[str, object]) -> object:
        spec: FieldSpec = data["spec"]
        if spec.kind == "check":
            return bool(data["var"].get())
        if spec.kind == "multiline":
            return str(data["widget"].get("1.0", "end-1c")).rstrip()
        return str(data["var"].get()).strip()

    def _set_widget_value(self, data: dict[str, object], value: object) -> None:
        spec: FieldSpec = data["spec"]
        if spec.kind == "check":
            data["var"].set(bool(value))
        elif spec.kind == "multiline":
            widget = data["widget"]
            widget.delete("1.0", "end")
            if value:
                widget.insert("1.0", str(value))
        else:
            data["var"].set("" if value is None else str(value))

    def _set_text_widget(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def append_optimizer_log(self, line: str) -> None:
        if self.optimizer_log_text is None:
            return
        widget = self.optimizer_log_text
        widget.configure(state="normal")
        if widget.index("end-1c") != "1.0":
            widget.insert("end", "\n")
        widget.insert("end", str(line))
        widget.see("end")
        widget.configure(state="disabled")

    def clear_optimizer_log(self) -> None:
        if self.optimizer_log_text is None:
            return
        self._set_text_widget(self.optimizer_log_text, "")

    def set_optimizer_best_text(self, text: str) -> None:
        if self.optimizer_best_text is None:
            return
        self._set_text_widget(self.optimizer_best_text, text)

    def _reset_optimizer_views(self) -> None:
        self.optimizer_status_var.set("Study idle.")
        self.optimizer_trial_var.set("Trial: 0 / 0")
        self.optimizer_best_score_var.set("Best score: (none)")
        self.optimizer_study_dir_var.set("Study dir: (none)")
        self.clear_optimizer_log()
        self.append_optimizer_log("尚未開始最佳化。")
        self.set_optimizer_best_text("尚未產生任何最佳 trial。")
        self._request_context_refresh()

    def _resolve_current_output_dir(self) -> Path | None:
        cfg_path = self.current_horn_path.get().strip()
        if not cfg_path:
            return None
        try:
            return compute_output_directory(self.collect_global_state(), self.collect_effective_horn_state(), Path(cfg_path))
        except Exception:
            return None

    def _candidate_mesh_files_for_preview(self, preview_file: Path) -> list[Path]:
        candidates = [
            preview_file if preview_file.suffix.lower() == ".msh" else None,
            preview_file.with_suffix(".msh"),
            preview_file.parent / "mesh.msh",
        ]
        return [candidate for candidate in candidates if candidate is not None and candidate.exists()]

    def _update_runtime_status(self) -> None:
        cfg_path = self.current_horn_path.get().strip()
        self.current_cfg_var.set(cfg_path or "尚未開啟號角設定檔。")
        output_dir = self._resolve_current_output_dir()
        if output_dir and cfg_path:
            search_dirs = iter_output_search_directories(output_dir, Path(cfg_path))
            visible = " -> ".join(str(path) for path in search_dirs[:3])
            if len(search_dirs) > 3:
                visible = f"{visible} -> ..."
            self.output_dir_var.set(visible)
        else:
            self.output_dir_var.set("請先開啟或儲存號角設定檔後再解析。")

        if self.last_generated_preview_file is not None:
            self.preview_path_var.set(str(self.last_generated_preview_file))
        elif not self.preview_path_var.get().strip():
            self.preview_path_var.set("尚未載入任何輸出預覽。")

        mesh_file = ""
        if "BEM.MeshFile" in self.bem_widgets:
            effective_bem_state = self.collect_effective_bem_state()
            if not bool(effective_bem_state.get("BEM.Enabled", False)):
                self.mesh_status_var.set("BEM automation 關閉")
            else:
                mesh_source_mode = str(effective_bem_state.get("BEM.MeshSourceMode", "latest_ath_output")).strip().lower()
                if mesh_source_mode == "manual_mesh_file":
                    mesh_file = str(effective_bem_state.get("BEM.MeshFile", "")).strip()
                else:
                    guessed_mesh = guess_latest_mesh_file(
                        self.collect_global_state(),
                        self.collect_effective_horn_state(),
                        self.current_horn_path.get(),
                    )
                    if guessed_mesh is None and self.last_generated_preview_file is not None and self.last_generated_preview_file.suffix.lower() == ".msh":
                        guessed_mesh = self.last_generated_preview_file
                    mesh_file = str(guessed_mesh) if guessed_mesh is not None else ""
                self.mesh_status_var.set(mesh_file or "尚未指定")
        self._refresh_status_card_summary()
        self._request_context_refresh()

    def _format_group_summary(self, detected_groups: list[int], *, group_source: str, count_map: dict[str, int]) -> str:
        if not detected_groups:
            return "分群摘要：尚未偵測到任何群組。"
        source_label = describe_group_source(group_source)
        preview = ", ".join(f"群組 {group_id}:{count_map.get(str(group_id), 0)}" for group_id in detected_groups[:10])
        more = "" if len(detected_groups) <= 10 else f" ...（另有 {len(detected_groups) - 10} 個）"
        return f"分群摘要：來源={source_label} | {preview}{more}"

    def _update_group_status_from_preview_data(self, preview_file: Path, data: dict[str, object]) -> None:
        group_source = str(data.get("group_source", "unknown"))
        detected_groups = [int(value) for value in data.get("detected_groups", [])]
        edge_counts = {str(key): int(value) for key, value in dict(data.get("group_edge_count", {})).items()}
        source_label = describe_group_source(group_source)
        if detected_groups:
            self.group_status_var.set(f"分群狀態：已偵測 {len(detected_groups)} 個群組（{source_label}）")
        else:
            self.group_status_var.set("分群狀態：目前預覽檔沒有可視群組")
        self.preview_group_var.set(self._format_group_summary(detected_groups, group_source=group_source, count_map=edge_counts))

        self._update_runtime_status()

    def collect_global_state(self) -> dict[str, object]:
        state = default_global_state()
        for key, data in self.global_widgets.items():
            state[key] = self._get_widget_value(data)
        return state

    def collect_horn_state(self, *, normalize_locked: bool = False) -> dict[str, object]:
        state = default_horn_state()
        for key, data in self.horn_widgets.items():
            value = self._get_widget_value(data)
            if key == "SOURCE.Contours":
                value = normalize_inline_block(str(value), "Source.Contours")
            state[key] = value
        if normalize_locked:
            return normalize_branch_locked_horn_state(state)
        return state

    def collect_effective_horn_state(self) -> dict[str, object]:
        return sanitize_ath_state(self.collect_horn_state())

    def collect_bem_state(self) -> dict[str, object]:
        state = default_bem_state()
        for key, data in self.bem_widgets.items():
            state[key] = self._get_widget_value(data)
        return state

    def collect_optimizer_state(self) -> dict[str, object]:
        state = default_optimizer_state()
        for key, data in self.optimizer_widgets.items():
            state[key] = self._get_widget_value(data)
        return state

    def collect_effective_bem_state(self, ath_state: dict[str, object] | None = None) -> dict[str, object]:
        effective_ath_state = dict(ath_state) if ath_state is not None else self.collect_effective_horn_state()
        return sanitize_bem_state(self.collect_bem_state(), effective_ath_state)

    def collect_effective_run_payload(self) -> dict[str, object]:
        if self._quick_dirty:
            self.sync_quick_to_horn()
        ath_cfg_state = self.collect_effective_horn_state()
        bem_state = self.collect_effective_bem_state(ath_cfg_state)
        bem_runtime = build_bem_runtime_settings(bem_state, ath_cfg_state)
        ath_run_state = dict(ath_cfg_state)
        if bool(bem_runtime.get("requires_ath_mesh_output", False)):
            ath_run_state["Output.MSH"] = True
        return {
            "ath_cfg_state": ath_cfg_state,
            "ath_run_state": ath_run_state,
            "bem_state": bem_state,
            "bem_runtime": bem_runtime,
        }

    def apply_global_state(self, state: dict[str, object]) -> None:
        for key, data in self.global_widgets.items():
            self._set_widget_value(data, state.get(key, data["spec"].default))

    def apply_horn_state(self, state: dict[str, object]) -> None:
        self._suspend_dependency_refresh = True
        try:
            for key, data in self.horn_widgets.items():
                self._set_widget_value(data, state.get(key, data["spec"].default))
        finally:
            self._suspend_dependency_refresh = False
        self.refresh_dependency_states()
        self.sync_horn_to_quick()
        self.refresh_preview()

    def apply_bem_state(self, state: dict[str, object]) -> None:
        self._suspend_dependency_refresh = True
        try:
            for key, data in self.bem_widgets.items():
                self._set_widget_value(data, state.get(key, data["spec"].default))
        finally:
            self._suspend_dependency_refresh = False
        self.refresh_dependency_states()

    def load_global_config(self, startup: bool = False) -> None:
        if not ATH_GLOBAL_CONFIG.exists():
            self.apply_global_state(default_global_state())
            self.status_var.set("尚未找到 ath.cfg；全域欄位已載入預設值。")
            self._update_runtime_status()
            return
        state = load_global_state(read_text_file(ATH_GLOBAL_CONFIG))
        self.apply_global_state(state)
        if not startup:
            self.status_var.set(f"已載入 {ATH_GLOBAL_CONFIG.name}。")
        self._update_runtime_status()

    def save_global_config(self, silent: bool = False) -> bool:
        state = self.collect_global_state()
        output_root = str(state.get("OutputRootDir", "")).strip()
        if output_root:
            try:
                Path(output_root).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                if not silent:
                    messagebox.showerror(APP_TITLE, f"建立 OutputRootDir 失敗：\n{exc}")
                return False
        ATH_GLOBAL_CONFIG.write_text(render_global_text(state), encoding="utf-8", newline="\n")
        if not silent:
            self.status_var.set(f"已儲存 {ATH_GLOBAL_CONFIG.name}。")
            messagebox.showinfo(APP_TITLE, f"已將全域設定儲存至：\n{ATH_GLOBAL_CONFIG}")
        self._update_runtime_status()
        return True

    def new_horn_config(self, startup: bool = False) -> None:
        self.current_horn_path.set("")
        self.apply_horn_state(default_horn_state())
        self.apply_bem_state(default_bem_state())
        self._reset_optimizer_views()
        self.stop_bem_progress()
        self.bem_status_var.set("閒置")
        self.bem_result_path_var.set("尚未執行任何 BEM 工作。")
        self._set_text_widget(self.bem_mesh_text, "請先執行 ATH 並啟用 `Output.MSH = 1`，或手動指定既有 `.msh` 檔。")
        self._set_text_widget(self.bem_summary_text, "尚未載入任何 BEM 摘要。")
        self.bem_plot_caption_var.set("執行 BEM 後將在此顯示指向性極座標圖。")
        self.preview_status_var.set("預覽狀態：未載入")
        self.group_status_var.set("分群狀態：尚未檢查")
        self.preview_group_var.set("分群摘要：尚未偵測。")
        self.after(50, lambda: draw_bem_placeholder(self.bem_polar_canvas, "執行 BEM 後會在此顯示指向性曲線。"))
        if not startup:
            self.status_var.set("已建立新的號角設定表單。")
        self._update_runtime_status()

    def open_horn_config(self) -> None:
        path = filedialog.askopenfilename(
            title="開啟號角定義",
            initialdir=str(ROOT_DIR),
            filetypes=[("ATH 設定檔", "*.cfg"), ("所有檔案", "*.*")],
        )
        if not path:
            return
        self.apply_horn_state(load_horn_state(read_text_file(Path(path))))
        self.current_horn_path.set(path)
        self._reset_optimizer_views()
        self.resolve_bem_mesh_path(set_status=False)
        self.status_var.set(f"已載入號角設定：{path}")
        self._update_runtime_status()

    def save_horn_config(self) -> bool:
        current = self.current_horn_path.get().strip()
        if not current:
            return self.save_horn_config_as()
        return self._save_horn_to_path(Path(current))

    def save_horn_config_as(self) -> bool:
        path = filedialog.asksaveasfilename(
            title="號角設定另存為",
            initialdir=str(ROOT_DIR),
            defaultextension=".cfg",
            filetypes=[("ATH 設定檔", "*.cfg"), ("所有檔案", "*.*")],
        )
        if not path:
            return False
        return self._save_horn_to_path(Path(path))

    def _save_horn_to_path(self, path: Path) -> bool:
        if self._quick_dirty:
            self.sync_quick_to_horn()
        state = self.collect_effective_horn_state()
        if not str(state.get("Length", "")).strip():
            messagebox.showerror(APP_TITLE, "ATH 號角定義必須填寫 Length。")
            return False
        path.write_text(render_horn_text(state), encoding="utf-8", newline="\n")
        self.current_horn_path.set(str(path))
        self.status_var.set(f"已儲存號角設定：{path}")
        self.refresh_preview()
        self.resolve_bem_mesh_path(set_status=False)
        self._update_runtime_status()
        return True

    def refresh_preview(self) -> None:
        if self._quick_dirty:
            self.sync_quick_to_horn()
        preview = render_horn_text(self.collect_effective_horn_state())
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", preview)
        self.preview_text.configure(state="disabled")
        self._update_runtime_status()

    def apply_auto_enclosure(self) -> None:
        """Auto-fill enclosure values from current horn length parameters."""
        state = self.collect_horn_state()
        updated_state = derive_auto_enclosure(state)
        self.apply_horn_state(updated_state)
        self.status_var.set(
            "已套用 Auto Enclosure："
            f"Spacing={updated_state.get('ENCLOSURE.Spacing', '')} | "
            f"Depth={updated_state.get('ENCLOSURE.Depth', '')} | "
            f"EdgeRadius={updated_state.get('ENCLOSURE.EdgeRadius', '')} | "
            f"FrontRes={updated_state.get('ENCLOSURE.FrontResolution', '')} | "
            f"BackRes={updated_state.get('ENCLOSURE.BackResolution', '')}"
        )
        self._update_runtime_status()

    def _select_workspace_tab(self, key: str) -> None:
        tab = self.workspace_tabs.get(key)
        if tab is not None:
            self.workspace_notebook.select(tab)

    def _update_preview_view_var(self) -> None:
        self.preview_renderer.update_preview_view_var()

    def _on_preview_sensitivity_change(self, _value: str | None = None) -> None:
        self._apply_preview_sensitivity()

    def _on_preview_normals_toggle(self) -> None:
        self._redraw_embedded_preview()

    def _apply_preview_sensitivity(self) -> None:
        sensitivity = max(0.3, min(2.5, float(self.preview_sensitivity_var.get())))
        self.preview_sensitivity_var.set(sensitivity)
        self.preview_sensitivity_label_var.set(f"互動靈敏度 {sensitivity:.2f}x")
        self.preview_renderer.set_interaction_sensitivity(sensitivity)
        if self.opengl_preview is not None and self.opengl_preview.available:
            self.opengl_preview.set_interaction_sensitivity(sensitivity)

    def _reset_preview_view(self, _event: tk.Event | None = None) -> None:
        self.preview_renderer.reset_preview_view(_event)

    def _start_preview_drag(self, event: tk.Event) -> None:
        self.preview_renderer.start_preview_drag(event)

    def _drag_preview_view(self, event: tk.Event) -> None:
        self.preview_renderer.drag_preview_view(event)

    def _end_preview_drag(self, _event: tk.Event) -> None:
        self.preview_renderer.end_preview_drag(_event)

    def _zoom_preview_view(self, event: tk.Event) -> None:
        self.preview_renderer.zoom_preview_view(event)

    def _project_preview_points(self, points: dict[int, tuple[float, float, float]]) -> tuple[dict[int, tuple[float, float]], tuple[float, float, float, float]]:
        return self.preview_renderer.project_preview_points(points)

    def _project_preview_vector(self, vector: tuple[float, float, float]) -> tuple[float, float]:
        return self.preview_renderer.project_preview_vector(vector)

    def _draw_preview_axis_triad(self, canvas: tk.Canvas, width: int, height: int) -> None:
        self.preview_renderer.draw_preview_axis_triad(canvas, width, height)

    def _draw_preview_placeholder(self, message: str) -> None:
        self.preview_renderer.draw_preview_placeholder(message)

    def _redraw_embedded_preview(self, _event: tk.Event | None = None) -> None:
        self.preview_renderer.redraw_embedded_preview(_event)

    def _apply_embedded_preview_error(self, request_id: int, preview_file: Path, exc: Exception) -> None:
        self.preview_controller._apply_embedded_preview_error(request_id, preview_file, exc)

    def _apply_embedded_preview_data(self, request_id: int, preview_file: Path, data: dict[str, object]) -> None:
        self.preview_controller._apply_embedded_preview_data(request_id, preview_file, data)

    def _load_embedded_preview_worker(self, request_id: int, preview_file: Path) -> None:
        self.preview_controller._load_embedded_preview_worker(request_id, preview_file)

    def load_embedded_preview_file(self, preview_file: Path) -> None:
        self.preview_controller.load_embedded_preview_file(preview_file)

    def load_latest_output_preview(self) -> None:
        self.workflow_controller.load_latest_output_preview()

    def collect_design_recipe(self) -> DesignRecipe:
        horn_state = self.collect_horn_state(normalize_locked=True)
        bem_state = self.collect_bem_state()

        def _f(value: object, default: float) -> float:
            try:
                text = str(value).strip()
                return float(text) if text else default
            except Exception:
                return default

        def _i(value: object, default: int) -> int:
            try:
                text = str(value).strip()
                return int(float(text)) if text else default
            except Exception:
                return default

        case_name = Path(self.current_horn_path.get().strip()).stem or "demo_case"
        mouth_shape_raw = str(horn_state.get("Morph.TargetShape", "0")).strip()
        mouth_shape = {"0": "keep", "1": "rect", "2": "round"}.get(mouth_shape_raw, "keep")
        source_mode = "axial" if str(horn_state.get("Source.Velocity", "1")).strip() == "2" else "normal"
        source_shape = "disk" if str(horn_state.get("Source.Shape", "1")).strip() == "2" else "cap"

        source_gain_text = str(bem_state.get("BEM.SourceGain", "1.0")).strip()
        first_gain = source_gain_text.replace(";", ",").split(",")[0].strip() if source_gain_text else "1.0"
        source_velocity = _f(first_gain, 1.0)

        symmetry_mode = str(bem_state.get("BEM.SymmetryMode", "off")).strip().lower()
        symmetry_enabled = symmetry_mode != "off"
        symmetry_planes: tuple[str, ...]
        if symmetry_mode == "half_x_even":
            symmetry_planes = ("x",)
        elif symmetry_mode == "half_y_even":
            symmetry_planes = ("y",)
        elif symmetry_mode == "quarter_xy_even_even":
            symmetry_planes = ("x", "y")
        else:
            symmetry_planes = ()

        return DesignRecipe(
            case_name=case_name,
            throat_diameter=_f(horn_state.get("Throat.Diameter"), 25.4),
            horn_length=_f(horn_state.get("Length"), 160.0),
            coverage_angle=_f(horn_state.get("Coverage.Angle"), 90.0),
            mouth_shape=mouth_shape,
            mouth_width=_f(horn_state.get("Morph.TargetWidth"), 0.0),
            mouth_height=_f(horn_state.get("Morph.TargetHeight"), 0.0),
            mouth_corner_radius=_f(horn_state.get("Morph.CornerRadius"), 35.0),
            source_mode=source_mode,
            source_shape=source_shape,
            source_velocity=source_velocity,
            auto_enclosure_enabled=False,
            output_abec_project_enabled=bool(horn_state.get("Output.ABECProject", False)),
            bem_f1=_f(bem_state.get("BEM.F1"), 200.0),
            bem_f2=_f(bem_state.get("BEM.F2"), 20000.0),
            bem_num_freq=_i(bem_state.get("BEM.NumFreq"), 48),
            observation_plane=str(bem_state.get("BEM.Plane", "XZ")).strip().upper() or "XZ",
            mic_distance=_f(bem_state.get("BEM.MicDistance"), 5.0),
            symmetry_enabled=symmetry_enabled,
            symmetry_planes=symmetry_planes,
            notes="from_current_ui",
        )

    def apply_design_recipe(self, recipe: DesignRecipe) -> None:
        horn_base = self.collect_horn_state()
        bem_base = self.collect_bem_state()
        ath_state = recipe.to_ath_state(base_state=horn_base)
        if recipe.auto_enclosure_enabled:
            ath_state = derive_auto_enclosure(ath_state)
        bem_state = recipe.to_bem_state(base_state=bem_base)
        self.apply_horn_state(ath_state)
        self.apply_bem_state(bem_state)
        self.status_var.set("已將 Recipe 套用到目前欄位。")
        self._update_runtime_status()

    def apply_sample_design(self) -> None:
        self.apply_horn_state(default_horn_state())
        self.apply_bem_state(default_bem_state())
        self.status_var.set("已套用內建 sample design 到目前正式狀態。")
        self._update_runtime_status()

    def run_all_from_current_mode(self) -> None:
        if self._quick_dirty:
            self.sync_quick_to_horn()
        self.run_all_controller.run_all_from_ui()

    def save_design_recipe(self) -> None:
        self.run_all_controller.save_recipe()

    def load_design_recipe(self) -> None:
        self.run_all_controller.load_recipe()

    def open_latest_workspace(self) -> None:
        self.run_all_controller.open_workspace()

    def load_workspace_results(self) -> None:
        self.run_all_controller.reload_latest_workspace_results()

    def run_optimizer_study(self) -> None:
        self.optimization_controller.start_from_ui()

    def stop_optimizer_study(self) -> None:
        self.optimization_controller.request_stop_after_trial()

    def open_optimizer_study_dir(self) -> None:
        self.optimization_controller.open_study_dir()

    def apply_best_optimizer_trial(self) -> None:
        self.optimization_controller.apply_best_trial()

    def open_current_preview_external(self) -> None:
        if self.last_generated_preview_file is None:
            messagebox.showinfo(APP_TITLE, "目前尚未載入任何已生成的預覽檔。")
            return
        mesh_cmd = str(self.collect_global_state().get("MeshCmd", "")).strip()
        if self._open_generated_preview(self.last_generated_preview_file, mesh_cmd):
            self.status_var.set(f"已使用外部程式開啟：{self.last_generated_preview_file.name}")
        else:
            messagebox.showerror(APP_TITLE, f"無法以外部程式開啟預覽檔：\n{self.last_generated_preview_file}")

    def resolve_bem_mesh_path(self, bem_state: dict[str, object] | None = None, *, set_status: bool = True) -> Path | None:
        effective_bem_state = dict(bem_state) if bem_state is not None else self.collect_effective_bem_state()
        mesh_source_mode = str(effective_bem_state.get("BEM.MeshSourceMode", "latest_ath_output")).strip().lower() or "latest_ath_output"
        if mesh_source_mode == "manual_mesh_file":
            mesh_path_text = str(effective_bem_state.get("BEM.MeshFile", "")).strip()
            if not mesh_path_text:
                if set_status:
                    self.status_var.set("BEM 目前使用手動網格模式，但尚未指定 `.msh` 檔。")
                    self.mesh_status_var.set("尚未指定")
                    self._update_runtime_status()
                return None
            mesh_path = Path(mesh_path_text)
            if set_status:
                self.mesh_status_var.set(str(mesh_path))
                self._update_runtime_status()
            return mesh_path
        return self.autofill_bem_mesh(set_status=set_status)

    def autofill_bem_mesh(self, set_status: bool = True) -> Path | None:
        effective_bem_state = self.collect_effective_bem_state()
        mesh_source_mode = str(effective_bem_state.get("BEM.MeshSourceMode", "latest_ath_output")).strip().lower()
        mesh_file = guess_latest_mesh_file(
            self.collect_global_state(),
            self.collect_effective_horn_state(),
            self.current_horn_path.get(),
        )
        if mesh_file is None and self.last_generated_preview_file is not None and self.last_generated_preview_file.suffix.lower() == ".msh":
            mesh_file = self.last_generated_preview_file

        if mesh_file is not None:
            if mesh_source_mode == "manual_mesh_file":
                self._set_widget_value(self.bem_widgets["BEM.MeshFile"], str(mesh_file))
            if set_status:
                self.status_var.set(f"目前使用 BEM 網格：{mesh_file}")
            self.mesh_status_var.set(str(mesh_file))
            self._update_runtime_status()
            return mesh_file

        if set_status:
            self.status_var.set("尚未找到已生成的 `.msh`；請啟用 `Output.MSH = 1` 後執行 ATH，或手動指定。")
        self.mesh_status_var.set("尚未指定")
        self._update_runtime_status()
        return None

    def inspect_bem_mesh(self) -> None:
        self.bem_controller.inspect_bem_mesh()

    def _resolve_bem_result_dir(self) -> Path | None:
        return self.bem_controller.resolve_bem_result_dir()

    def _refresh_bem_plot(self) -> None:
        self.bem_controller.refresh_bem_plot()

    def open_bem_solver_log(self) -> None:
        self.bem_controller.open_bem_solver_log()

    def load_bem_results(self, result_dir: Path | None = None) -> None:
        self.bem_controller.load_bem_results(result_dir)

    def _open_generated_preview(self, preview_file: Path, mesh_cmd: str) -> bool:
        command = build_preview_command(mesh_cmd, preview_file)
        try:
            if command:
                subprocess.Popen(command, cwd=str(preview_file.parent), shell=True)
            else:
                os.startfile(str(preview_file))
        except OSError:
            return False
        return True

    def run_bempp(self) -> None:
        self.workflow_controller.run_bempp()

    def run_ath(self) -> None:
        if self._quick_dirty:
            self.sync_quick_to_horn()
        self.workflow_controller.run_ath()

    def destroy(self) -> None:  # type: ignore[override]
        if self._bem_progress_after_id is not None:
            self.after_cancel(self._bem_progress_after_id)
            self._bem_progress_after_id = None
        if self._context_refresh_after_id is not None:
            self.after_cancel(self._context_refresh_after_id)
            self._context_refresh_after_id = None
        if hasattr(self, "optimization_controller") and self.optimization_controller is not None:
            try:
                self.optimization_controller.shutdown()
            except Exception:
                pass
        if self.opengl_preview is not None:
            self.opengl_preview.shutdown()
        super().destroy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--self-test", action="store_true", help="Run parser / renderer self-tests and exit.")
    parser.add_argument("--check-opengl", action="store_true", help="Probe VTK/OpenGL runtime and Tk bridge status, then exit.")
    parser.add_argument("--check-layering", action="store_true", help="Validate architecture layer import boundaries and exit.")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()
    if args.check_opengl:
        result = probe_vtk_opengl()
        print("vtk_available =", result.vtk_available)
        print("runtime_available =", result.runtime_available)
        print("tk_bridge_available =", result.tk_bridge_available)
        print("has_rendering_tk_dll =", result.has_rendering_tk_dll)
        if result.dll_search_dirs:
            print("dll_search_dirs =")
            for directory in result.dll_search_dirs:
                print("  -", directory)
        if result.vendor:
            print("vendor =", result.vendor)
        if result.renderer:
            print("renderer =", result.renderer)
        if result.version:
            print("version =", result.version)
        if result.runtime_error:
            print("runtime_error =", result.runtime_error)
        if result.tk_bridge_error:
            print("tk_bridge_error =", result.tk_bridge_error)
        print("summary =", result.summary())
        return 0
    if args.check_layering:
        result = check_layering()
        print(format_layering_report(result))
        return 0 if result.ok else 1

    app = AthConfigStudio()
    app.mainloop()
    return 0
