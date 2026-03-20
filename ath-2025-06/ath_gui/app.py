from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, ttk

from .application.controllers import BemController, PreviewController, WorkflowController
from .domain.auto_enclosure import derive_auto_enclosure
from .domain.bem_specs import BEM_FIELD_SECTIONS
from .domain.config_core import (
    build_field_hint,
    default_global_state,
    default_horn_state,
    load_global_state,
    load_horn_state,
    normalize_inline_block,
    read_text_file,
    render_global_text,
    render_horn_text,
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
    INPUT_BG,
    MUTED,
    ROOT_DIR,
    TEXT,
    FieldSpec,
)
from .infrastructure.bem_bridge import BemLaunch
from .infrastructure.bem_mesh import guess_latest_mesh_file
from .infrastructure.bem_state import default_bem_state
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
        self.bem_widgets: dict[str, dict[str, object]] = {}
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
        self.bem_result_path_var = tk.StringVar(value="尚未執行任何 BEM 工作。")
        self.bem_plot_caption_var = tk.StringVar(value="執行 BEM 後將在此顯示指向性極座標圖。")
        self.bem_plot_mode_var = tk.StringVar(value="band_map")
        self.bem_plot_log_x_var = tk.BooleanVar(value=True)
        self.preview_view_var = tk.StringVar(value="視角：yaw 32°, pitch -18°, zoom 1.00x")
        self.status_card_collapsed = tk.BooleanVar(value=False)
        self.status_card_toggle_var = tk.StringVar(value="收合")
        self.status_card_summary_var = tk.StringVar(value="")
        self.bem_last_result_dir: Path | None = None
        self.bem_last_log_path: Path | None = None
        self.bem_polar_rows: list[dict[str, float]] = []
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
        self.font_family = self._resolve_ui_font_family()
        self._configure_fonts()
        self.preview_controller = PreviewController(self)
        self.bem_controller = BemController(self)
        self.workflow_controller = WorkflowController(self)
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
            fieldbackground=[("readonly", INPUT_BG)],
            background=[("readonly", INPUT_BG)],
            foreground=[("readonly", TEXT)],
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
        ttk.Button(quick_actions, text="存 ath.cfg", style="Compact.Tool.TButton", command=self.save_global_config).grid(row=0, column=4, padx=(0, 4))
        ttk.Button(quick_actions, text="刷新預覽", style="Compact.Tool.TButton", command=self.refresh_preview).grid(row=0, column=5, padx=(0, 4))
        ttk.Button(quick_actions, text="Auto ENC", style="Compact.Tool.TButton", command=self.apply_auto_enclosure).grid(row=0, column=6, padx=(0, 4))
        ttk.Button(quick_actions, text="執行 ATH", style="Compact.Accent.TButton", command=self.run_ath).grid(row=0, column=7, padx=(2, 0))

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

        self.tab_bodies: dict[str, ttk.Frame] = {}
        tab_titles = {
            "Global": "全域",
            "Geometry": "幾何",
            "Morph": "變形",
            "Mesh": "網格",
            "Simulation": "模擬",
            "Output": "輸出",
            "BEM": "BEM",
            "Advanced": "進階",
        }
        for tab_name in ("Global", "Geometry", "Morph", "Mesh", "Simulation", "Output", "BEM", "Advanced"):
            scroll = ScrollableFrame(self.notebook)
            self.notebook.add(scroll, text=tab_titles[tab_name])
            self.tab_bodies[tab_name] = scroll.inner

        self.workspace_notebook = ttk.Notebook(workspace_host)
        self.workspace_notebook.grid(row=0, column=0, sticky="nsew")
        self.workspace_tabs: dict[str, ttk.Frame] = {}
        workspace_titles = {
            "Geometry3D": "3D 幾何",
            "Polar": "指向性",
            "MeshInfo": "網格摘要",
            "Summary": "BEM 摘要",
            "TextPreview": "設定文字",
        }
        for key in ("Geometry3D", "Polar", "MeshInfo", "Summary", "TextPreview"):
            frame = ttk.Frame(self.workspace_notebook, style="App.TFrame")
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            self.workspace_notebook.add(frame, text=workspace_titles[key])
            self.workspace_tabs[key] = frame

        self._build_sections()

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

        details = ttk.Frame(card, style="Card.TFrame")
        details.grid(row=1, column=0, sticky="ew")
        details.columnconfigure(1, weight=1)
        self.status_card_details = details

        labels = [
            ("預覽", self.preview_status_var),
            ("分群", self.group_status_var),
            ("BEM", self.bem_status_var),
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
        group = self.group_status_var.get().replace("分群狀態：", "").strip()
        self.status_card_summary_var.set(f"預覽 {preview} | BEM {bem} | 分群 {group}")

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

    def _build_sections(self) -> None:
        container_rows = {tab: 0 for tab in self.tab_bodies}
        for tab_name, description, fields in FIELD_SECTIONS:
            target = self.tab_bodies[tab_name]
            card = ttk.LabelFrame(target, text=description, style="Card.TLabelframe", padding=14)
            card.grid(row=container_rows[tab_name], column=0, sticky="ew", padx=14, pady=(14, 0))
            card.columnconfigure(1, weight=1)
            self._populate_card(card, fields, self.global_widgets if tab_name == "Global" else self.horn_widgets)
            container_rows[tab_name] += 1

        for body in self.tab_bodies.values():
            body.columnconfigure(0, weight=1)

        self._build_preview_panel(self.workspace_tabs["Geometry3D"])
        self._build_bem_panel(self.tab_bodies["BEM"])
        self._build_polar_panel(self.workspace_tabs["Polar"])
        self._build_mesh_info_panel(self.workspace_tabs["MeshInfo"])
        self._build_bem_summary_panel(self.workspace_tabs["Summary"])

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

        advanced_hint = ttk.LabelFrame(
            self.tab_bodies["Advanced"],
            text="進階區說明",
            style="Card.TLabelframe",
            padding=14,
        )
        advanced_hint.grid(row=container_rows["Advanced"], column=0, sticky="ew", padx=14, pady=(14, 18))
        advanced_hint.columnconfigure(0, weight=1)
        ttk.Label(
            advanced_hint,
            text="右側工作區已整合 3D 幾何、指向性、網格摘要、BEM 摘要與設定文字預覽。"
                 "左側進階頁保留參數輸入，避免預覽區被擠壓。",
            style="Hint.TLabel",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w")

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
        target.rowconfigure(0, weight=1)

        controls_card = ttk.LabelFrame(
            target,
            text="ATH GUI -> BEMPP 工作流",
            style="Card.TLabelframe",
            padding=14,
        )
        controls_card.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        controls_card.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(controls_card, style="Card.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        toolbar.columnconfigure(6, weight=1)
        ttk.Button(toolbar, text="自動偵測網格", style="Tool.TButton", command=self.autofill_bem_mesh).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="檢查網格", style="Tool.TButton", command=self.inspect_bem_mesh).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(toolbar, text="執行 BEM", style="Accent.TButton", command=self.run_bempp).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="重新載入結果", style="Tool.TButton", command=self.load_bem_results).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(toolbar, text="開啟求解器日誌", style="Tool.TButton", command=self.open_bem_solver_log).grid(row=0, column=4, padx=(0, 8))
        ttk.Label(toolbar, text="BEM 狀態：", style="Hint.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Label(toolbar, textvariable=self.bem_status_var, style="Hint.TLabel").grid(row=1, column=1, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(toolbar, textvariable=self.bem_result_path_var, style="Hint.TLabel").grid(row=1, column=3, columnspan=4, sticky="e", pady=(10, 0))

        inner_rows = 1
        for description, fields in BEM_FIELD_SECTIONS:
            card = ttk.LabelFrame(controls_card, text=description, style="Card.TLabelframe", padding=14)
            card.grid(row=inner_rows, column=0, sticky="ew", pady=(0, 14))
            card.columnconfigure(1, weight=1)
            self._populate_card(card, fields, self.bem_widgets)
            inner_rows += 1

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
            values=("band_map", "single_freq_polar"),
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

    def _populate_card(self, card: ttk.LabelFrame, fields: tuple[FieldSpec, ...], widget_map: dict[str, dict[str, object]]) -> None:
        row = 0
        for spec in fields:
            ttk.Label(card, text=spec.label, style="CardLabel.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=(0, 12))
            control_frame = ttk.Frame(card, style="Card.TFrame")
            control_frame.grid(row=row, column=1, sticky="ew", pady=(0, 12))
            control_frame.columnconfigure(0, weight=1)

            if spec.kind == "check":
                var = tk.BooleanVar(value=bool(spec.default))
                widget = ttk.Checkbutton(control_frame, variable=var)
                widget.grid(row=0, column=0, sticky="w")
                widget_map[spec.key] = {"spec": spec, "var": var, "widget": widget}
            elif spec.kind == "combo":
                var = tk.StringVar(value=str(spec.default))
                widget = ttk.Combobox(control_frame, textvariable=var, values=spec.choices, width=spec.width, state="readonly")
                widget.grid(row=0, column=0, sticky="ew")
                widget_map[spec.key] = {"spec": spec, "var": var, "widget": widget}
            elif spec.kind == "multiline":
                height = 8 if spec.key == "ADVANCED.Raw" else 7
                widget = self._make_dark_text(control_frame, height=height, wrap="word")
                widget.grid(row=0, column=0, sticky="ew")
                widget_map[spec.key] = {"spec": spec, "widget": widget}
            else:
                entry_frame = ttk.Frame(control_frame, style="Card.TFrame")
                entry_frame.grid(row=0, column=0, sticky="ew")
                entry_frame.columnconfigure(0, weight=1)
                var = tk.StringVar(value=str(spec.default))
                widget = ttk.Entry(entry_frame, textvariable=var, width=spec.width)
                widget.grid(row=0, column=0, sticky="ew")
                widget_map[spec.key] = {"spec": spec, "var": var, "widget": widget}
                if spec.browse:
                    ttk.Button(
                        entry_frame,
                        text="瀏覽",
                        style="Tool.TButton",
                        command=lambda key=spec.key, mode=spec.browse: self.browse_for_field(key, mode),
                    ).grid(row=0, column=1, padx=(8, 0))

            helper_text = build_field_hint(spec)
            if helper_text:
                ttk.Label(
                    control_frame,
                    text=helper_text,
                    style="Hint.TLabel",
                    wraplength=700,
                    justify="left",
                ).grid(row=1, column=0, sticky="w", pady=(6, 0))
            row += 1

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
        else:
            target = self.bem_widgets
        self._set_widget_value(target[key], chosen)
        self.status_var.set(f"已為 {key} 選擇路徑。")
        if key not in self.bem_widgets:
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

    def _resolve_current_output_dir(self) -> Path | None:
        cfg_path = self.current_horn_path.get().strip()
        if not cfg_path:
            return None
        try:
            return compute_output_directory(self.collect_global_state(), self.collect_horn_state(), Path(cfg_path))
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
            mesh_file = str(self.collect_bem_state().get("BEM.MeshFile", "")).strip()
        self.mesh_status_var.set(mesh_file or "尚未指定")
        self._refresh_status_card_summary()

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

        mesh_candidates = self._candidate_mesh_files_for_preview(preview_file)
        if mesh_candidates and ("BEM.MeshFile" in self.bem_widgets):
            self._set_widget_value(self.bem_widgets["BEM.MeshFile"], str(mesh_candidates[0]))
        self._update_runtime_status()

    def collect_global_state(self) -> dict[str, object]:
        state = default_global_state()
        for key, data in self.global_widgets.items():
            state[key] = self._get_widget_value(data)
        return state

    def collect_horn_state(self) -> dict[str, object]:
        state = default_horn_state()
        for key, data in self.horn_widgets.items():
            value = self._get_widget_value(data)
            if key == "SOURCE.Contours":
                value = normalize_inline_block(str(value), "Source.Contours")
            state[key] = value
        return state

    def collect_bem_state(self) -> dict[str, object]:
        state = default_bem_state()
        for key, data in self.bem_widgets.items():
            state[key] = self._get_widget_value(data)
        return state

    def apply_global_state(self, state: dict[str, object]) -> None:
        for key, data in self.global_widgets.items():
            self._set_widget_value(data, state.get(key, data["spec"].default))

    def apply_horn_state(self, state: dict[str, object]) -> None:
        for key, data in self.horn_widgets.items():
            self._set_widget_value(data, state.get(key, data["spec"].default))
        self.refresh_preview()

    def apply_bem_state(self, state: dict[str, object]) -> None:
        for key, data in self.bem_widgets.items():
            self._set_widget_value(data, state.get(key, data["spec"].default))

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
        self.autofill_bem_mesh(set_status=False)
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
        state = self.collect_horn_state()
        if not str(state.get("Length", "")).strip():
            messagebox.showerror(APP_TITLE, "ATH 號角定義必須填寫 Length。")
            return False
        path.write_text(render_horn_text(state), encoding="utf-8", newline="\n")
        self.current_horn_path.set(str(path))
        self.status_var.set(f"已儲存號角設定：{path}")
        self.refresh_preview()
        self.autofill_bem_mesh(set_status=False)
        self._update_runtime_status()
        return True

    def refresh_preview(self) -> None:
        preview = render_horn_text(self.collect_horn_state())
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

    def open_current_preview_external(self) -> None:
        if self.last_generated_preview_file is None:
            messagebox.showinfo(APP_TITLE, "目前尚未載入任何已生成的預覽檔。")
            return
        mesh_cmd = str(self.collect_global_state().get("MeshCmd", "")).strip()
        if self._open_generated_preview(self.last_generated_preview_file, mesh_cmd):
            self.status_var.set(f"已使用外部程式開啟：{self.last_generated_preview_file.name}")
        else:
            messagebox.showerror(APP_TITLE, f"無法以外部程式開啟預覽檔：\n{self.last_generated_preview_file}")

    def autofill_bem_mesh(self, set_status: bool = True) -> Path | None:
        mesh_file = guess_latest_mesh_file(
            self.collect_global_state(),
            self.collect_horn_state(),
            self.current_horn_path.get(),
        )
        if mesh_file is None and self.last_generated_preview_file is not None and self.last_generated_preview_file.suffix.lower() == ".msh":
            mesh_file = self.last_generated_preview_file

        if mesh_file is not None:
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
        self.workflow_controller.run_ath()

    def destroy(self) -> None:  # type: ignore[override]
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
