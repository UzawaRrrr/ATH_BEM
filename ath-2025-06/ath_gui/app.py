from __future__ import annotations

import argparse
import os
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config_core import (
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
from .preview_core import (
    build_preview_command,
    compute_output_directory,
    find_generated_preview_file,
    load_embedded_preview_data,
)
from .self_test import run_self_test
from .specs import (
    APP_TITLE,
    ATH_EXE,
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
from .widgets import ScrollableFrame


class AthConfigStudio(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1320x920")
        self.minsize(1080, 760)
        self.configure(background=BG)

        self.global_widgets: dict[str, dict[str, object]] = {}
        self.horn_widgets: dict[str, dict[str, object]] = {}
        self.current_horn_path = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready.")
        self.ath_process: subprocess.Popen[bytes] | None = None
        self.last_generated_preview_file: Path | None = None
        self.preview_geometry: dict[str, object] | None = None
        self.preview_request_id = 0
        self.preview_path_var = tk.StringVar(value="No generated preview loaded yet.")
        self.preview_meta_var = tk.StringVar(value="Run ATH to generate a .geo preview inside the UI.")

        self._configure_style()
        self._build_shell()
        self.load_global_config(startup=True)
        self.new_horn_config(startup=True)

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
        style.configure("Card.TLabelframe.Label", background=CARD, foreground=ACCENT, font=("Segoe UI Semibold", 10))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 20))
        style.configure("Body.TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("CardLabel.TLabel", background=CARD, foreground=TEXT)
        style.configure("Hint.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure(
            "TEntry",
            fieldbackground=INPUT_BG,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            insertcolor=TEXT,
        )
        style.configure(
            "TCombobox",
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
        style.configure("TCheckbutton", background=CARD, foreground=TEXT)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI Semibold", 10))
        style.map(
            "TNotebook.Tab",
            background=[("selected", CARD), ("active", ACCENT_SOFT), ("!selected", CARD_ALT)],
            foreground=[("selected", TEXT), ("!selected", MUTED)],
        )
        style.configure("Accent.TButton", padding=(12, 7), background=ACCENT, foreground="#081018", bordercolor=ACCENT)
        style.map("Accent.TButton", background=[("active", "#59dac8"), ("pressed", "#2fb8a5")], foreground=[("disabled", MUTED)])
        style.configure("Tool.TButton", padding=(10, 6), background=BUTTON_BG, foreground=BUTTON_TEXT, bordercolor=BORDER)
        style.map("Tool.TButton", background=[("active", BUTTON_ACTIVE), ("pressed", "#355174")], foreground=[("disabled", MUTED)])
        style.configure("Vertical.TScrollbar", background=CARD_ALT, troughcolor=BG, bordercolor=BG, arrowcolor=TEXT)

    def _make_dark_text(self, parent: tk.Misc, *, height: int, wrap: str) -> tk.Text:
        return tk.Text(
            parent,
            height=height,
            wrap=wrap,
            background=INPUT_BG,
            foreground=TEXT,
            insertbackground=TEXT,
            selectbackground=ACCENT,
            selectforeground="#081018",
            relief="flat",
            borderwidth=1,
        )

    def _build_shell(self) -> None:
        root = ttk.Frame(self, style="App.TFrame", padding=18)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        header = ttk.Frame(root, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="A form-based editor for ath.cfg and horn definition files, mapped from the Ath 4.8.2 manual.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        toolbar = ttk.Frame(root, style="App.TFrame", padding=(0, 12, 0, 10))
        toolbar.grid(row=1, column=0, sticky="ew")
        toolbar.columnconfigure(7, weight=1)

        ttk.Button(toolbar, text="New Horn", style="Tool.TButton", command=self.new_horn_config).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="Open Horn CFG", style="Tool.TButton", command=self.open_horn_config).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(toolbar, text="Save Horn", style="Tool.TButton", command=self.save_horn_config).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="Save Horn As", style="Tool.TButton", command=self.save_horn_config_as).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(toolbar, text="Save ath.cfg", style="Tool.TButton", command=self.save_global_config).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(toolbar, text="Refresh Preview", style="Tool.TButton", command=self.refresh_preview).grid(row=0, column=5, padx=(0, 8))
        ttk.Button(toolbar, text="Run ATH", style="Accent.TButton", command=self.run_ath).grid(row=0, column=6, padx=(0, 12))
        ttk.Label(toolbar, text="Current Horn File:", style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(toolbar, textvariable=self.current_horn_path, style="Muted.TLabel").grid(row=1, column=2, columnspan=6, sticky="w", pady=(10, 0))

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=2, column=0, sticky="nsew")

        self.tab_bodies: dict[str, ttk.Frame] = {}
        for tab_name in ("Global", "Geometry", "Morph", "Mesh", "Simulation", "Output", "Preview", "Advanced"):
            scroll = ScrollableFrame(self.notebook)
            self.notebook.add(scroll, text=tab_name)
            self.tab_bodies[tab_name] = scroll.inner

        self._build_sections()

        footer = ttk.Frame(root, style="App.TFrame", padding=(0, 8, 0, 0))
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")

    def _build_sections(self) -> None:
        container_rows = {tab: 0 for tab in self.tab_bodies}
        for tab_name, description, fields in FIELD_SECTIONS:
            target = self.tab_bodies[tab_name]
            card = ttk.LabelFrame(target, text=description, style="Card.TLabelframe", padding=14)
            card.grid(row=container_rows[tab_name], column=0, sticky="ew", padx=14, pady=(14, 0))
            card.columnconfigure(1, weight=1)
            self._populate_card(card, fields, tab_name == "Global")
            container_rows[tab_name] += 1

        for body in self.tab_bodies.values():
            body.columnconfigure(0, weight=1)

        self._build_preview_panel(self.tab_bodies["Preview"])

        preview_card = ttk.LabelFrame(
            self.tab_bodies["Advanced"],
            text="Rendered Horn Config Preview",
            style="Card.TLabelframe",
            padding=14,
        )
        preview_card.grid(row=container_rows["Advanced"], column=0, sticky="nsew", padx=14, pady=(14, 18))
        preview_card.columnconfigure(0, weight=1)
        preview_card.rowconfigure(1, weight=1)
        ttk.Button(preview_card, text="Refresh Preview", style="Tool.TButton", command=self.refresh_preview).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.preview_text = self._make_dark_text(preview_card, height=22, wrap="none")
        self.preview_text.grid(row=1, column=0, sticky="nsew")
        self.preview_text.configure(state="disabled")

    def _build_preview_panel(self, target: ttk.Frame) -> None:
        target.columnconfigure(0, weight=1)
        target.rowconfigure(0, weight=1)

        preview_card = ttk.LabelFrame(
            target,
            text="Embedded Geometry Preview (.geo / .msh / .stl)",
            style="Card.TLabelframe",
            padding=14,
        )
        preview_card.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 18))
        preview_card.columnconfigure(0, weight=1)
        preview_card.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(preview_card, style="Card.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(4, weight=1)
        ttk.Button(toolbar, text="Load Latest Output", style="Tool.TButton", command=self.load_latest_output_preview).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="Open External", style="Tool.TButton", command=self.open_current_preview_external).grid(row=0, column=1, padx=(0, 8))
        ttk.Label(toolbar, textvariable=self.preview_path_var, style="Hint.TLabel").grid(row=0, column=4, sticky="e")

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

        self.embedded_preview_canvas = tk.Canvas(
            preview_card,
            background=INPUT_BG,
            highlightthickness=1,
            highlightbackground=BORDER,
            relief="flat",
        )
        self.embedded_preview_canvas.grid(row=2, column=0, sticky="nsew")
        self.embedded_preview_canvas.bind("<Configure>", self._redraw_embedded_preview)
        self.after(50, lambda: self._draw_preview_placeholder("Run ATH or load the latest output to render the generated geometry here."))

    def _populate_card(self, card: ttk.LabelFrame, fields: tuple[FieldSpec, ...], is_global: bool) -> None:
        widget_map = self.global_widgets if is_global else self.horn_widgets
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
                        text="Browse",
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
        target = self.global_widgets if key in self.global_widgets else self.horn_widgets
        self._set_widget_value(target[key], chosen)
        self.status_var.set(f"Selected path for {key}.")
        self.refresh_preview()

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

    def apply_global_state(self, state: dict[str, object]) -> None:
        for key, data in self.global_widgets.items():
            self._set_widget_value(data, state.get(key, data["spec"].default))

    def apply_horn_state(self, state: dict[str, object]) -> None:
        for key, data in self.horn_widgets.items():
            self._set_widget_value(data, state.get(key, data["spec"].default))
        self.refresh_preview()

    def load_global_config(self, startup: bool = False) -> None:
        if not ATH_GLOBAL_CONFIG.exists():
            self.apply_global_state(default_global_state())
            self.status_var.set("ath.cfg not found yet; global fields are blank.")
            return
        state = load_global_state(read_text_file(ATH_GLOBAL_CONFIG))
        self.apply_global_state(state)
        if not startup:
            self.status_var.set(f"Loaded {ATH_GLOBAL_CONFIG.name}.")

    def save_global_config(self, silent: bool = False) -> bool:
        state = self.collect_global_state()
        output_root = str(state.get("OutputRootDir", "")).strip()
        if output_root:
            try:
                Path(output_root).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                if not silent:
                    messagebox.showerror(APP_TITLE, f"Failed to create OutputRootDir:\n{exc}")
                return False
        ATH_GLOBAL_CONFIG.write_text(render_global_text(state), encoding="utf-8", newline="\n")
        if not silent:
            self.status_var.set(f"Saved {ATH_GLOBAL_CONFIG.name}.")
            messagebox.showinfo(APP_TITLE, f"Saved global configuration to:\n{ATH_GLOBAL_CONFIG}")
        return True

    def new_horn_config(self, startup: bool = False) -> None:
        self.current_horn_path.set("")
        self.apply_horn_state(default_horn_state())
        if not startup:
            self.status_var.set("Started a new horn definition form.")

    def open_horn_config(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Horn Definition",
            initialdir=str(ROOT_DIR),
            filetypes=[("ATH config files", "*.cfg"), ("All files", "*.*")],
        )
        if not path:
            return
        self.apply_horn_state(load_horn_state(read_text_file(Path(path))))
        self.current_horn_path.set(path)
        self.status_var.set(f"Loaded horn config from {path}.")

    def save_horn_config(self) -> bool:
        current = self.current_horn_path.get().strip()
        if not current:
            return self.save_horn_config_as()
        return self._save_horn_to_path(Path(current))

    def save_horn_config_as(self) -> bool:
        path = filedialog.asksaveasfilename(
            title="Save Horn Definition As",
            initialdir=str(ROOT_DIR),
            defaultextension=".cfg",
            filetypes=[("ATH config files", "*.cfg"), ("All files", "*.*")],
        )
        if not path:
            return False
        return self._save_horn_to_path(Path(path))

    def _save_horn_to_path(self, path: Path) -> bool:
        state = self.collect_horn_state()
        if not str(state.get("Length", "")).strip():
            messagebox.showerror(APP_TITLE, "Length is mandatory for an ATH horn definition.")
            return False
        path.write_text(render_horn_text(state), encoding="utf-8", newline="\n")
        self.current_horn_path.set(str(path))
        self.status_var.set(f"Saved horn config to {path}.")
        self.refresh_preview()
        return True

    def refresh_preview(self) -> None:
        preview = render_horn_text(self.collect_horn_state())
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", preview)
        self.preview_text.configure(state="disabled")

    def _draw_preview_placeholder(self, message: str) -> None:
        canvas = self.embedded_preview_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 200)
        height = max(canvas.winfo_height(), 160)
        canvas.create_text(
            width / 2,
            height / 2,
            text=message,
            fill=MUTED,
            font=("Segoe UI", 11),
            width=max(width - 40, 160),
            justify="center",
        )

    def _redraw_embedded_preview(self, _event: tk.Event | None = None) -> None:
        canvas = self.embedded_preview_canvas
        if self.preview_geometry is None:
            self._draw_preview_placeholder("Run ATH or load the latest output to render the generated geometry here.")
            return

        canvas.delete("all")
        width = max(canvas.winfo_width(), 200)
        height = max(canvas.winfo_height(), 160)
        pad = 28

        points = self.preview_geometry["points"]
        edges = self.preview_geometry["edges"]
        projected: dict[int, tuple[float, float]] = {}
        us: list[float] = []
        vs: list[float] = []
        for tag, (x, y, z) in points.items():
            u = x - (0.58 * y)
            v = z + (0.36 * y)
            projected[tag] = (u, v)
            us.append(u)
            vs.append(v)

        span_u = max(max(us) - min(us), 1e-6)
        span_v = max(max(vs) - min(vs), 1e-6)
        scale = min((width - 2 * pad) / span_u, (height - 2 * pad) / span_v)
        offset_u = (width - (span_u * scale)) / 2
        offset_v = (height - (span_v * scale)) / 2
        min_u = min(us)
        min_v = min(vs)

        max_edges = 12000
        step = max(1, len(edges) // max_edges) if len(edges) > max_edges else 1
        for index, (a, b) in enumerate(edges):
            if index % step != 0:
                continue
            u1, v1 = projected[a]
            u2, v2 = projected[b]
            x1 = offset_u + ((u1 - min_u) * scale)
            y1 = height - (offset_v + ((v1 - min_v) * scale))
            x2 = offset_u + ((u2 - min_u) * scale)
            y2 = height - (offset_v + ((v2 - min_v) * scale))
            canvas.create_line(x1, y1, x2, y2, fill=ACCENT, width=1)

        canvas.create_rectangle(1, 1, width - 2, height - 2, outline=BORDER)

    def _apply_embedded_preview_error(self, request_id: int, preview_file: Path, exc: Exception) -> None:
        if request_id != self.preview_request_id:
            return
        self.preview_geometry = None
        self.preview_path_var.set(str(preview_file))
        self.preview_meta_var.set(f"Failed to load embedded preview: {exc}")
        self._draw_preview_placeholder("Embedded preview failed to load. You can still open the file externally.")

    def _apply_embedded_preview_data(self, request_id: int, preview_file: Path, data: dict[str, object]) -> None:
        if request_id != self.preview_request_id:
            return
        self.preview_geometry = data
        self.last_generated_preview_file = preview_file
        bbox = data["bbox"]
        self.preview_path_var.set(str(preview_file))
        self.preview_meta_var.set(
            f"{data['file_name']} | dim {data['mesh_dimension']} | nodes {data['node_count']} | "
            f"edges {data['edge_count']} | elements {data['element_count']} | "
            f"bbox x[{bbox[0]:.1f},{bbox[1]:.1f}] y[{bbox[2]:.1f},{bbox[3]:.1f}] z[{bbox[4]:.1f},{bbox[5]:.1f}]"
        )
        self._redraw_embedded_preview()
        self.notebook.select(self.notebook.tabs()[list(self.tab_bodies.keys()).index("Preview")])

    def _load_embedded_preview_worker(self, request_id: int, preview_file: Path) -> None:
        try:
            data = load_embedded_preview_data(preview_file)
        except Exception as exc:
            self.after(0, lambda exc=exc: self._apply_embedded_preview_error(request_id, preview_file, exc))
            return
        self.after(0, lambda: self._apply_embedded_preview_data(request_id, preview_file, data))

    def load_embedded_preview_file(self, preview_file: Path) -> None:
        self.preview_request_id += 1
        request_id = self.preview_request_id
        self.preview_geometry = None
        self.last_generated_preview_file = preview_file
        self.preview_path_var.set(str(preview_file))
        self.preview_meta_var.set("Loading embedded preview...")
        self._draw_preview_placeholder("Loading generated geometry into the embedded preview...")
        threading.Thread(
            target=self._load_embedded_preview_worker,
            args=(request_id, preview_file),
            daemon=True,
        ).start()

    def load_latest_output_preview(self) -> None:
        cfg_path = self.current_horn_path.get().strip()
        if not cfg_path:
            messagebox.showinfo(APP_TITLE, "Save or open a horn definition first so the output location can be resolved.")
            return
        preview_file = find_generated_preview_file(
            compute_output_directory(self.collect_global_state(), self.collect_horn_state(), Path(cfg_path)),
            Path(cfg_path),
        )
        if preview_file is None:
            messagebox.showinfo(APP_TITLE, "No generated .geo / .msh / .stl file was found for the current project yet.")
            return
        self.load_embedded_preview_file(preview_file)
        self.status_var.set(f"Loaded embedded preview from {preview_file}.")

    def open_current_preview_external(self) -> None:
        if self.last_generated_preview_file is None:
            messagebox.showinfo(APP_TITLE, "There is no generated preview file loaded yet.")
            return
        mesh_cmd = str(self.collect_global_state().get("MeshCmd", "")).strip()
        if self._open_generated_preview(self.last_generated_preview_file, mesh_cmd):
            self.status_var.set(f"Opened external preview: {self.last_generated_preview_file.name}")
        else:
            messagebox.showerror(APP_TITLE, f"Could not open preview externally:\n{self.last_generated_preview_file}")

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

    def _finish_ath_run(self, return_code: int, output_dir: Path, cfg_path: Path) -> None:
        self.ath_process = None
        if return_code != 0:
            self.status_var.set(f"ATH finished with exit code {return_code}.")
            return

        preview_file = find_generated_preview_file(output_dir, cfg_path)
        if preview_file is None:
            self.status_var.set(f"ATH finished, but no previewable output file was found in {output_dir}.")
            return

        self.load_embedded_preview_file(preview_file)
        self.status_var.set(f"ATH finished. Embedded preview loaded: {preview_file.name}")

    def _watch_ath_process(self, process: subprocess.Popen[bytes], output_dir: Path, cfg_path: Path) -> None:
        return_code = process.wait()
        if return_code == 0:
            for _ in range(20):
                if find_generated_preview_file(output_dir, cfg_path) is not None:
                    break
                time.sleep(0.25)
        self.after(0, lambda: self._finish_ath_run(return_code, output_dir, cfg_path))

    def run_ath(self) -> None:
        if not ATH_EXE.exists():
            messagebox.showerror(APP_TITLE, f"ATH executable was not found:\n{ATH_EXE}")
            return
        if self.ath_process is not None and self.ath_process.poll() is None:
            messagebox.showinfo(APP_TITLE, "ATH is already running. Please wait for it to finish.")
            return

        global_state = self.collect_global_state()
        horn_state = self.collect_horn_state()
        if not self.save_global_config(silent=True):
            return
        if not self.save_horn_config():
            return

        cfg_path = self.current_horn_path.get().strip()
        if not cfg_path:
            messagebox.showerror(APP_TITLE, "No horn definition file is available to run.")
            return

        cfg_file = Path(cfg_path)
        output_dir = compute_output_directory(global_state, horn_state, cfg_file)
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        try:
            self.ath_process = subprocess.Popen([str(ATH_EXE), cfg_path], cwd=str(ROOT_DIR), creationflags=flags)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Failed to start ath.exe:\n{exc}")
            return

        threading.Thread(
            target=self._watch_ath_process,
            args=(self.ath_process, output_dir, cfg_file),
            daemon=True,
        ).start()
        self.status_var.set(f"Started ATH with {cfg_path}. Preview will open after generation finishes.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--self-test", action="store_true", help="Run parser / renderer self-tests and exit.")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    app = AthConfigStudio()
    app.mainloop()
    return 0
