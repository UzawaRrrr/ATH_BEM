from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCAL_CONFIG_PATH = PROJECT_ROOT / "config" / "local_paths.yaml"
LOCAL_CONFIG_EXAMPLE = PROJECT_ROOT / "config" / "local_paths.example.yaml"
GEOMETRY_CONFIG_PATH = PROJECT_ROOT / "config" / "geometry_params.yaml"
GEOMETRY_CONFIG_EXAMPLE = PROJECT_ROOT / "config" / "geometry_params.example.yaml"
GA_SETTINGS_CONFIG_PATH = PROJECT_ROOT / "config" / "ga_settings.yaml"
GA_SETTINGS_CONFIG_EXAMPLE = PROJECT_ROOT / "config" / "ga_settings.example.yaml"
SOLVER_SETTINGS_CONFIG_PATH = PROJECT_ROOT / "config" / "solver_settings.yaml"
SOLVER_SETTINGS_CONFIG_EXAMPLE = PROJECT_ROOT / "config" / "solver_settings.example.yaml"
COVERAGE_CONFIG_EXAMPLE = PROJECT_ROOT / "config" / "coverage_target.example.yaml"

DEFAULT_WEIGHTS = {
    "w_in": 0.40,
    "w_out": 0.30,
    "w_bw": 0.15,
    "w_smooth": 0.05,
    "w_eff": 0.05,
    "w_mfg": 0.05,
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _save_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _ensure_file(target: Path, example: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if example.exists():
        target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        target.write_text("", encoding="utf-8")


def _get_nested(data: dict[str, Any], key_path: str, default: Any = None) -> Any:
    node: Any = data
    for key in key_path.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def _set_nested(data: dict[str, Any], key_path: str, value: Any) -> None:
    node = data
    parts = key_path.split(".")
    for key in parts[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[parts[-1]] = value


def _path_token(path: Path) -> str:
    p = path.resolve()
    try:
        return str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


class ControlPanelWindow(QMainWindow):
    candidate_re = re.compile(r"case=([^ ]+)\s+candidate=(\{.*\})")
    fitness_re = re.compile(r"case=([^ ]+)\s+fitness=([-+0-9.eE]+)")
    generation_re = re.compile(r"GA generations.*?([0-9]+)/([0-9]+)")

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Waveguide Optimization Control Panel")
        self.resize(1480, 940)

        _ensure_file(LOCAL_CONFIG_PATH, LOCAL_CONFIG_EXAMPLE)
        _ensure_file(GEOMETRY_CONFIG_PATH, GEOMETRY_CONFIG_EXAMPLE)
        _ensure_file(GA_SETTINGS_CONFIG_PATH, GA_SETTINGS_CONFIG_EXAMPLE)
        _ensure_file(SOLVER_SETTINGS_CONFIG_PATH, SOLVER_SETTINGS_CONFIG_EXAMPLE)

        self.local_defaults = _load_yaml(LOCAL_CONFIG_EXAMPLE)
        self.local_config = _load_yaml(LOCAL_CONFIG_PATH)
        _ensure_file(self.coverage_config_path, COVERAGE_CONFIG_EXAMPLE)

        self.geometry_config = _load_yaml(GEOMETRY_CONFIG_PATH)
        self.ga_settings_config = _load_yaml(GA_SETTINGS_CONFIG_PATH)
        self.coverage_config = _load_yaml(self.coverage_config_path)
        self.solver_settings_config = _load_yaml(SOLVER_SETTINGS_CONFIG_PATH)

        self.process: QProcess | None = None
        self.current_command_label = ""
        self.last_run_snapshot_dir: Path | None = None
        self.case_candidates: dict[str, dict[str, Any]] = {}
        self.best_fitness: float | None = None
        self.best_candidate: dict[str, Any] = {}

        self.env_widgets: dict[str, QWidget] = {}
        self.ga_widgets: dict[str, QWidget] = {}
        self.cover_widgets: dict[str, QWidget] = {}
        self.solver_widgets: dict[str, QWidget] = {}
        self.weight_widgets: dict[str, QDoubleSpinBox] = {}

        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        self.status_label = QLabel("Ready")
        root_layout.addWidget(self.status_label)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        self._build_environment_tab()
        self._build_geometry_tab()
        self._build_ga_tab()
        self._build_coverage_tab()
        self._build_solver_tab()
        self._build_run_tab()
        self._build_results_tab()

        self.load_from_files()

    @property
    def coverage_config_path(self) -> Path:
        token = _get_nested(self.local_config, "runtime.coverage_target_path", "config/coverage_target.yaml")
        p = Path(str(token)).expanduser()
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    @property
    def outputs_root(self) -> Path:
        token = _get_nested(self.local_config, "paths.outputs_directory", "outputs")
        p = Path(str(token)).expanduser()
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    def _add_widget(self, form: QFormLayout, registry: dict[str, QWidget], key: str, label: str, kind: str, options: list[str] | None = None) -> None:
        if kind == "int":
            widget: QWidget = QSpinBox()
            cast = widget
            cast.setRange(-1_000_000, 1_000_000)
        elif kind == "float":
            widget = QDoubleSpinBox()
            cast = widget
            cast.setRange(-1e12, 1e12)
            cast.setDecimals(6)
        elif kind == "bool":
            widget = QCheckBox()
        elif kind == "combo":
            widget = QComboBox()
            cast = widget
            cast.addItems(options or [])
        else:
            widget = QLineEdit()
        form.addRow(label, widget)
        registry[key] = widget

    def _read_widget(self, w: QWidget) -> Any:
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QSpinBox):
            return int(w.value())
        if isinstance(w, QDoubleSpinBox):
            return float(w.value())
        if isinstance(w, QLineEdit):
            return w.text().strip()
        return None

    def _write_widget(self, w: QWidget, value: Any) -> None:
        if isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, QComboBox):
            idx = w.findText(str(value))
            w.setCurrentIndex(idx if idx >= 0 else 0)
        elif isinstance(w, QSpinBox):
            w.setValue(int(value) if str(value).strip() else 0)
        elif isinstance(w, QDoubleSpinBox):
            w.setValue(float(value) if str(value).strip() else 0.0)
        elif isinstance(w, QLineEdit):
            w.setText(str(value))

    def _build_environment_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        box = QGroupBox("Environment")
        form = QFormLayout(box)
        fields = [
            ("paths.ath_executable", "ATH executable path", "str"),
            ("paths.gmsh_executable", "Gmsh path", "str"),
            ("runtime.wsl_distro", "WSL distro", "str"),
            ("runtime.wsl_python_executable", "WSL command path", "str"),
            ("paths.working_directory", "Project root", "str"),
            ("paths.mesh_output_directory", "Mesh exchange directory", "str"),
            ("paths.outputs_directory", "Outputs directory", "str"),
            ("paths.logs_directory", "Logs directory", "str"),
            ("runtime.default_mode", "Mode", "combo"),
        ]
        for key, label, kind in fields:
            self._add_widget(form, self.env_widgets, key, label, kind, ["mock", "real"] if kind == "combo" else None)
        layout.addWidget(box)

        row = QHBoxLayout()
        btn_save = QPushButton("Save Environment")
        btn_reload = QPushButton("Reload Environment")
        btn_save.clicked.connect(self.save_local_config)
        btn_reload.clicked.connect(self.load_local_widgets)
        row.addWidget(btn_save)
        row.addWidget(btn_reload)
        row.addStretch(1)
        layout.addLayout(row)
        self.tabs.addTab(tab, "1) Environment")

    def _build_geometry_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.param_table = QTableWidget(0, 8)
        self.param_table.setHorizontalHeaderLabels([
            "include_in_ga", "parameter_name", "initial_value", "min_value", "max_value", "mutation_scale", "unit", "notes"
        ])
        self.param_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.param_table)

        row = QHBoxLayout()
        self.btn_add_param = QPushButton("Add Parameter")
        self.btn_remove_param = QPushButton("Remove Selected")
        self.btn_save_param = QPushButton("Save Geometry Parameters")
        self.btn_reload_param = QPushButton("Reload Geometry Parameters")
        self.btn_add_param.clicked.connect(self.add_parameter_row)
        self.btn_remove_param.clicked.connect(self.remove_selected_parameter_rows)
        self.btn_save_param.clicked.connect(self.save_geometry_parameters)
        self.btn_reload_param.clicked.connect(self.load_geometry_to_table)
        for b in [self.btn_add_param, self.btn_remove_param, self.btn_save_param, self.btn_reload_param]:
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)
        self.tabs.addTab(tab, "2) Geometry Parameters")
    def _build_ga_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        box = QGroupBox("GA Settings")
        form = QFormLayout(box)
        fields = [
            ("population_size", "Population size", "int"),
            ("generations", "Generations", "int"),
            ("crossover_rate", "Crossover rate", "float"),
            ("mutation_rate", "Mutation rate", "float"),
            ("mutation_scale", "Mutation scale (engine)", "float"),
            ("elitism", "Elitism", "int"),
            ("random_seed", "Random seed", "int"),
            ("early_stopping_generations", "Early stopping", "int"),
            ("invalid_candidate_penalty", "Invalid candidate penalty", "float"),
            ("workers", "Workers", "int"),
        ]
        for key, label, kind in fields:
            self._add_widget(form, self.ga_widgets, key, label, kind)
        layout.addWidget(box)

        row = QHBoxLayout()
        btn_save = QPushButton("Save GA Settings")
        btn_reload = QPushButton("Reload GA Settings")
        btn_save.clicked.connect(self.save_ga_settings_config)
        btn_reload.clicked.connect(self.load_ga_widgets)
        row.addWidget(btn_save)
        row.addWidget(btn_reload)
        row.addStretch(1)
        layout.addLayout(row)
        self.tabs.addTab(tab, "3) GA Settings")

    def _build_coverage_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        box = QGroupBox("Coverage / Fitness")
        form = QFormLayout(box)
        fields = [
            ("horizontal_coverage_deg", "Horizontal coverage deg", "float"),
            ("vertical_coverage_deg", "Vertical coverage deg", "float"),
            ("transition_margin_deg", "Transition margin deg", "float"),
            ("in_coverage_target_db", "In-coverage target dB", "float"),
            ("out_of_coverage_threshold_db", "Out-of-coverage threshold dB", "float"),
            ("horizontal_target_beamwidth_deg", "Horizontal target beamwidth deg", "float"),
            ("vertical_target_beamwidth_deg", "Vertical target beamwidth deg", "float"),
        ]
        for key, label, kind in fields:
            self._add_widget(form, self.cover_widgets, key, label, kind)
        layout.addWidget(box)

        freq_box = QGroupBox("Frequency")
        freq_form = QFormLayout(freq_box)
        self.frequency_list_edit = QLineEdit()
        self.frequency_band_edit = QLineEdit()
        freq_form.addRow("Frequency list (comma)", self.frequency_list_edit)
        freq_form.addRow("Frequency band", self.frequency_band_edit)
        layout.addWidget(freq_box)

        weight_box = QGroupBox("Objective Weights")
        weight_form = QFormLayout(weight_box)
        for key in ["w_in", "w_out", "w_bw", "w_smooth", "w_eff", "w_mfg"]:
            spin = QDoubleSpinBox()
            spin.setRange(-1e6, 1e6)
            spin.setDecimals(6)
            self.weight_widgets[key] = spin
            weight_form.addRow(key, spin)
        layout.addWidget(weight_box)

        row = QHBoxLayout()
        btn_save = QPushButton("Save Coverage/Fitness")
        btn_reload = QPushButton("Reload Coverage/Fitness")
        btn_save.clicked.connect(self.save_coverage_config)
        btn_reload.clicked.connect(self.load_coverage_widgets)
        row.addWidget(btn_save)
        row.addWidget(btn_reload)
        row.addStretch(1)
        layout.addLayout(row)
        self.tabs.addTab(tab, "4) Coverage / Fitness")

    def _build_solver_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        box = QGroupBox("Solver")
        form = QFormLayout(box)
        fields = [
            ("bempp_tolerance", "BEMPP tolerance", "float"),
            ("bempp_max_iterations", "Max iterations", "int"),
            ("retry_policy", "Retry policy", "str"),
            ("timeout_seconds", "Timeout seconds", "int"),
            ("warm_up_enabled", "Warm-up enabled", "bool"),
            ("failure_penalty", "Failure penalty", "float"),
            ("wsl_execution_enabled", "WSL execution", "bool"),
            ("mesh_handoff.required", "Mesh handoff required", "bool"),
            ("mesh_handoff.validate_readability", "Validate mesh readability", "bool"),
            ("mesh_handoff.repeated_benchmark_runs", "Benchmark repeats", "int"),
            ("mesh_handoff.wsl_distro", "WSL distro override", "str"),
            ("mesh_handoff.wsl_command_path", "WSL command override", "str"),
        ]
        for key, label, kind in fields:
            self._add_widget(form, self.solver_widgets, key, label, kind)
        layout.addWidget(box)

        row = QHBoxLayout()
        btn_save = QPushButton("Save Solver Settings")
        btn_reload = QPushButton("Reload Solver Settings")
        btn_save.clicked.connect(self.save_solver_settings_config)
        btn_reload.clicked.connect(self.load_solver_widgets)
        row.addWidget(btn_save)
        row.addWidget(btn_reload)
        row.addStretch(1)
        layout.addLayout(row)
        self.tabs.addTab(tab, "5) Solver")

    def _build_run_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        row = QHBoxLayout()
        self.btn_check = QPushButton("Check Dependencies")
        self.btn_smoke = QPushButton("Smoke Test")
        self.btn_minimal = QPushButton("Minimal Optimization")
        self.btn_full = QPushButton("Full Optimization")
        self.btn_stop = QPushButton("Stop Current Run")
        for b in [self.btn_check, self.btn_smoke, self.btn_minimal, self.btn_full, self.btn_stop]:
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Run mode"))
        self.run_mode_combo = QComboBox()
        self.run_mode_combo.addItems(["mock", "real"])
        ctrl.addWidget(self.run_mode_combo)
        ctrl.addWidget(QLabel("Minimal population"))
        self.min_pop_spin = QSpinBox()
        self.min_pop_spin.setRange(2, 100000)
        ctrl.addWidget(self.min_pop_spin)
        ctrl.addWidget(QLabel("Minimal generations"))
        self.min_gen_spin = QSpinBox()
        self.min_gen_spin.setRange(1, 100000)
        ctrl.addWidget(self.min_gen_spin)
        ctrl.addStretch(1)
        layout.addLayout(ctrl)

        mbox = QGroupBox("Monitor")
        mform = QFormLayout(mbox)
        self.monitor_status = QLabel("Idle")
        self.monitor_generation = QLabel("-")
        self.monitor_best_fitness = QLabel("-")
        self.monitor_current_candidate = QTextEdit()
        self.monitor_current_candidate.setReadOnly(True)
        self.monitor_current_candidate.setMaximumHeight(120)
        self.monitor_best_candidate = QTextEdit()
        self.monitor_best_candidate.setReadOnly(True)
        self.monitor_best_candidate.setMaximumHeight(120)
        mform.addRow("Status", self.monitor_status)
        mform.addRow("Generation", self.monitor_generation)
        mform.addRow("Best fitness", self.monitor_best_fitness)
        mform.addRow("Current candidate", self.monitor_current_candidate)
        mform.addRow("Best candidate", self.monitor_best_candidate)
        layout.addWidget(mbox)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, stretch=1)

        self.btn_check.clicked.connect(self.run_check_dependencies)
        self.btn_smoke.clicked.connect(self.run_smoke_test)
        self.btn_minimal.clicked.connect(self.run_minimal_optimization)
        self.btn_full.clicked.connect(self.run_full_optimization)
        self.btn_stop.clicked.connect(self.stop_process)

        self.tabs.addTab(tab, "6) Run / Monitor")

    def _build_results_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.results_summary = QTextEdit()
        self.results_summary.setReadOnly(True)
        self.results_score = QTextEdit()
        self.results_score.setReadOnly(True)
        self.results_best = QTextEdit()
        self.results_best.setReadOnly(True)
        layout.addWidget(QLabel("Latest run summary"))
        layout.addWidget(self.results_summary)
        layout.addWidget(QLabel("Score breakdown"))
        layout.addWidget(self.results_score)
        layout.addWidget(QLabel("Best parameters"))
        layout.addWidget(self.results_best)

        row = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh Results")
        self.btn_open_outputs = QPushButton("Open Output Folder")
        self.btn_export_snapshot = QPushButton("Export Config Snapshot")
        self.btn_load_snapshot = QPushButton("Load Previous Config")
        for b in [self.btn_refresh, self.btn_open_outputs, self.btn_export_snapshot, self.btn_load_snapshot]:
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)

        self.btn_refresh.clicked.connect(self.refresh_results)
        self.btn_open_outputs.clicked.connect(self.open_output_folder)
        self.btn_export_snapshot.clicked.connect(self.export_config_snapshot)
        self.btn_load_snapshot.clicked.connect(self.load_config_snapshot)

        self.tabs.addTab(tab, "7) Results")

    def add_parameter_row(self, include: bool = True, name: str = "", initial: float = 0.0, low: float = 0.0, high: float = 1.0, mutation_scale: float = 0.1, unit: str = "", notes: str = "") -> None:
        row = self.param_table.rowCount()
        self.param_table.insertRow(row)
        c = QTableWidgetItem()
        c.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        c.setCheckState(Qt.CheckState.Checked if include else Qt.CheckState.Unchecked)
        self.param_table.setItem(row, 0, c)
        self.param_table.setItem(row, 1, QTableWidgetItem(name))
        self.param_table.setItem(row, 2, QTableWidgetItem(str(initial)))
        self.param_table.setItem(row, 3, QTableWidgetItem(str(low)))
        self.param_table.setItem(row, 4, QTableWidgetItem(str(high)))
        self.param_table.setItem(row, 5, QTableWidgetItem(str(mutation_scale)))
        self.param_table.setItem(row, 6, QTableWidgetItem(unit))
        self.param_table.setItem(row, 7, QTableWidgetItem(notes))

    def remove_selected_parameter_rows(self) -> None:
        for row in sorted({i.row() for i in self.param_table.selectedIndexes()}, reverse=True):
            self.param_table.removeRow(row)

    def _parse_frequency_list(self) -> list[float]:
        text = self.frequency_list_edit.text().strip()
        if not text:
            return []
        return [float(t.strip()) for t in text.split(",") if t.strip()]
    def load_local_widgets(self) -> None:
        self.local_config = _load_yaml(LOCAL_CONFIG_PATH)
        for key, w in self.env_widgets.items():
            value = _get_nested(self.local_config, key, _get_nested(self.local_defaults, key, ""))
            self._write_widget(w, value)
        mode = str(_get_nested(self.local_config, "runtime.default_mode", "mock"))
        idx = self.run_mode_combo.findText(mode)
        self.run_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def save_local_config(self) -> bool:
        data = _load_yaml(LOCAL_CONFIG_PATH)
        for key, w in self.env_widgets.items():
            _set_nested(data, key, self._read_widget(w))
        mode = str(_get_nested(data, "runtime.default_mode", "mock")).strip().lower()
        if mode not in {"mock", "real"}:
            QMessageBox.warning(self, "Invalid mode", "default mode must be mock or real")
            return False
        if not str(_get_nested(data, "paths.working_directory", "")).strip():
            QMessageBox.warning(self, "Invalid environment", "Project root cannot be empty")
            return False
        _set_nested(data, "runtime.ga_parameters_path", _path_token(GEOMETRY_CONFIG_PATH))
        _set_nested(data, "runtime.coverage_target_path", _path_token(self.coverage_config_path))
        _save_yaml(LOCAL_CONFIG_PATH, data)
        self.local_config = data
        self._append_log(f"[INFO] Saved local config: {LOCAL_CONFIG_PATH}")
        return True

    def load_geometry_to_table(self) -> None:
        self.geometry_config = _load_yaml(GEOMETRY_CONFIG_PATH)
        self.param_table.setRowCount(0)
        params = self.geometry_config.get("parameters", {})
        if not isinstance(params, dict):
            params = {}
        for name, raw in params.items():
            if not isinstance(raw, dict):
                continue
            include = bool(raw.get("include_in_ga", raw.get("include", True)))
            initial = float(raw.get("initial_value", raw.get("initial", 0.0)))
            low = float(raw.get("min_value", 0.0))
            high = float(raw.get("max_value", 1.0))
            bounds = raw.get("bounds")
            if isinstance(bounds, (list, tuple)) and len(bounds) >= 2:
                low = float(bounds[0])
                high = float(bounds[1])
                if "initial_value" not in raw and "initial" not in raw:
                    initial = 0.5 * (low + high)
            self.add_parameter_row(include, str(name), initial, low, high, float(raw.get("mutation_scale", 0.1)), str(raw.get("unit", "")), str(raw.get("notes", "")))

    def save_geometry_parameters(self) -> bool:
        payload: dict[str, Any] = {"parameters": {}}
        for row in range(self.param_table.rowCount()):
            include_item = self.param_table.item(row, 0)
            name_item = self.param_table.item(row, 1)
            init_item = self.param_table.item(row, 2)
            low_item = self.param_table.item(row, 3)
            high_item = self.param_table.item(row, 4)
            mut_item = self.param_table.item(row, 5)
            unit_item = self.param_table.item(row, 6)
            notes_item = self.param_table.item(row, 7)
            name = name_item.text().strip() if name_item else ""
            if not name:
                continue
            try:
                initial = float(init_item.text() if init_item else "0")
                low = float(low_item.text() if low_item else "0")
                high = float(high_item.text() if high_item else "1")
                mut = float(mut_item.text() if mut_item else "0.1")
            except ValueError:
                QMessageBox.warning(self, "Invalid geometry", f"Row {row+1} contains non-numeric values")
                return False
            if high <= low:
                QMessageBox.warning(self, "Invalid geometry", f"Row {row+1}: max must be greater than min")
                return False
            if initial < low or initial > high:
                QMessageBox.warning(self, "Invalid geometry", f"Row {row+1}: initial must be inside bounds")
                return False
            if mut < 0:
                QMessageBox.warning(self, "Invalid geometry", f"Row {row+1}: mutation_scale must be >= 0")
                return False
            include = include_item.checkState() == Qt.CheckState.Checked if include_item else True
            payload["parameters"][name] = {
                "include_in_ga": include,
                "initial_value": initial,
                "min_value": low,
                "max_value": high,
                "mutation_scale": mut,
                "unit": unit_item.text().strip() if unit_item else "",
                "notes": notes_item.text().strip() if notes_item else "",
            }
        if not payload["parameters"]:
            QMessageBox.warning(self, "Invalid geometry", "At least one parameter is required")
            return False
        _save_yaml(GEOMETRY_CONFIG_PATH, payload)
        self.geometry_config = payload
        local = _load_yaml(LOCAL_CONFIG_PATH)
        _set_nested(local, "runtime.ga_parameters_path", _path_token(GEOMETRY_CONFIG_PATH))
        _save_yaml(LOCAL_CONFIG_PATH, local)
        self.local_config = local
        self._append_log(f"[INFO] Saved geometry config: {GEOMETRY_CONFIG_PATH}")
        return True

    def load_ga_widgets(self) -> None:
        self.ga_settings_config = _load_yaml(GA_SETTINGS_CONFIG_PATH)
        defaults = {
            "population_size": 20,
            "generations": 20,
            "crossover_rate": 0.5,
            "mutation_rate": 0.1,
            "mutation_scale": 0.08,
            "elitism": 2,
            "random_seed": 42,
            "early_stopping_generations": 0,
            "invalid_candidate_penalty": 1000000.0,
            "workers": 1,
        }
        for key, w in self.ga_widgets.items():
            self._write_widget(w, _get_nested(self.ga_settings_config, key, defaults[key]))
        self.min_pop_spin.setValue(max(2, int(_get_nested(self.ga_settings_config, "population_size", 6))))
        self.min_gen_spin.setValue(max(1, min(int(_get_nested(self.ga_settings_config, "generations", 2)), 10)))

    def save_ga_settings_config(self) -> bool:
        data: dict[str, Any] = {}
        for key, w in self.ga_widgets.items():
            _set_nested(data, key, self._read_widget(w))
        pop = int(_get_nested(data, "population_size", 0))
        gen = int(_get_nested(data, "generations", 0))
        crossover = float(_get_nested(data, "crossover_rate", -1))
        mrate = float(_get_nested(data, "mutation_rate", -1))
        mscale = float(_get_nested(data, "mutation_scale", mrate))
        elitism = int(_get_nested(data, "elitism", 0))
        workers = int(_get_nested(data, "workers", 0))
        if pop < 2 or gen < 1 or elitism < 1 or elitism > pop or workers < 1:
            QMessageBox.warning(self, "Invalid GA settings", "Check population/generations/elitism/workers values")
            return False
        if not (0.0 <= crossover <= 1.0 and 0.0 <= mrate <= 1.0 and mscale > 0):
            QMessageBox.warning(self, "Invalid GA settings", "Rates must be in range and mutation_scale > 0")
            return False
        _save_yaml(GA_SETTINGS_CONFIG_PATH, data)
        self.ga_settings_config = data

        local = _load_yaml(LOCAL_CONFIG_PATH)
        _set_nested(local, "runtime.full_population_size", pop)
        _set_nested(local, "runtime.full_generations", gen)
        _set_nested(local, "runtime.ga_crossover_rate", crossover)
        _set_nested(local, "runtime.ga_mutation_rate", mrate)
        _set_nested(local, "runtime.full_mutation_scale", mscale)
        _set_nested(local, "runtime.full_elite_count", elitism)
        _set_nested(local, "runtime.random_seed", int(_get_nested(data, "random_seed", 42)))
        _set_nested(local, "runtime.ga_early_stopping_generations", int(_get_nested(data, "early_stopping_generations", 0)))
        _set_nested(local, "runtime.ga_invalid_candidate_penalty", float(_get_nested(data, "invalid_candidate_penalty", 1000000.0)))
        _set_nested(local, "runtime.ga_workers", workers)
        _save_yaml(LOCAL_CONFIG_PATH, local)
        self.local_config = local
        self._append_log(f"[INFO] Saved GA settings: {GA_SETTINGS_CONFIG_PATH}")
        return True
    def load_solver_widgets(self) -> None:
        self.solver_settings_config = _load_yaml(SOLVER_SETTINGS_CONFIG_PATH)
        defaults = {
            "bempp_tolerance": 1.0e-5,
            "bempp_max_iterations": 400,
            "retry_policy": "retry_once",
            "timeout_seconds": 120,
            "warm_up_enabled": False,
            "failure_penalty": 1000000.0,
            "wsl_execution_enabled": True,
            "mesh_handoff": {
                "required": True,
                "validate_readability": True,
                "repeated_benchmark_runs": 1,
                "wsl_distro": "",
                "wsl_command_path": ".venv_wsl/bin/python",
            },
        }
        for key, w in self.solver_widgets.items():
            self._write_widget(w, _get_nested(self.solver_settings_config, key, _get_nested(defaults, key, "")))

    def save_solver_settings_config(self) -> bool:
        data: dict[str, Any] = {}
        for key, w in self.solver_widgets.items():
            _set_nested(data, key, self._read_widget(w))
        tol = float(_get_nested(data, "bempp_tolerance", -1))
        iters = int(_get_nested(data, "bempp_max_iterations", 0))
        timeout = int(_get_nested(data, "timeout_seconds", 0))
        penalty = float(_get_nested(data, "failure_penalty", -1))
        repeats = int(_get_nested(data, "mesh_handoff.repeated_benchmark_runs", -1))
        if tol <= 0 or iters <= 0 or timeout <= 0 or penalty < 0 or repeats < 0:
            QMessageBox.warning(self, "Invalid solver settings", "Tolerance/iterations/timeout/penalty/repeats are invalid")
            return False
        _save_yaml(SOLVER_SETTINGS_CONFIG_PATH, data)
        self.solver_settings_config = data

        local = _load_yaml(LOCAL_CONFIG_PATH)
        _set_nested(local, "runtime.bempp_tolerance", tol)
        _set_nested(local, "runtime.bempp_max_iterations", iters)
        _set_nested(local, "runtime.solver_retry_policy", str(_get_nested(data, "retry_policy", "retry_once")))
        _set_nested(local, "runtime.timeout_seconds", timeout)
        _set_nested(local, "runtime.solver_warmup_enabled", bool(_get_nested(data, "warm_up_enabled", False)))
        _set_nested(local, "runtime.solver_failure_penalty", penalty)
        _set_nested(local, "runtime.solver_prefer_wsl", bool(_get_nested(data, "wsl_execution_enabled", True)))
        _set_nested(local, "runtime.mesh_handoff_required", bool(_get_nested(data, "mesh_handoff.required", True)))
        _set_nested(local, "runtime.mesh_handoff_validate_readability", bool(_get_nested(data, "mesh_handoff.validate_readability", True)))
        _set_nested(local, "runtime.wsl_solver_repeated_runs", repeats)
        distro = str(_get_nested(data, "mesh_handoff.wsl_distro", "")).strip()
        cmd = str(_get_nested(data, "mesh_handoff.wsl_command_path", "")).strip()
        if distro:
            _set_nested(local, "runtime.wsl_distro", distro)
        if cmd:
            _set_nested(local, "runtime.wsl_python_executable", cmd)
        _save_yaml(LOCAL_CONFIG_PATH, local)
        self.local_config = local
        self._append_log(f"[INFO] Saved solver settings: {SOLVER_SETTINGS_CONFIG_PATH}")
        return True

    def load_coverage_widgets(self) -> None:
        self.local_config = _load_yaml(LOCAL_CONFIG_PATH)
        _ensure_file(self.coverage_config_path, COVERAGE_CONFIG_EXAMPLE)
        self.coverage_config = _load_yaml(self.coverage_config_path)

        defaults = {
            "horizontal_coverage_deg": 90.0,
            "vertical_coverage_deg": 60.0,
            "transition_margin_deg": 8.0,
            "in_coverage_target_db": 0.0,
            "out_of_coverage_threshold_db": -12.0,
            "horizontal_target_beamwidth_deg": 90.0,
            "vertical_target_beamwidth_deg": 60.0,
        }
        for key, w in self.cover_widgets.items():
            self._write_widget(w, self.coverage_config.get(key, defaults[key]))

        frequencies = self.coverage_config.get("frequencies_hz")
        if not isinstance(frequencies, list):
            frequencies = _get_nested(self.local_config, "runtime.frequencies_hz", [])
        self.frequency_list_edit.setText(", ".join(str(x) for x in frequencies) if isinstance(frequencies, list) else "")

        band = self.coverage_config.get("frequency_band_hz")
        if band is None:
            band = _get_nested(self.local_config, "runtime.frequency_band_hz", "")
        self.frequency_band_edit.setText(str(band))

        weights = self.coverage_config.get("objective_weights")
        if not isinstance(weights, dict):
            weights = _get_nested(self.local_config, "runtime.objective_weights", {})
        if not isinstance(weights, dict):
            weights = {}
        for key, w in self.weight_widgets.items():
            w.setValue(float(weights.get(key, DEFAULT_WEIGHTS[key])))

    def save_coverage_config(self) -> bool:
        data = _load_yaml(self.coverage_config_path)
        for key, w in self.cover_widgets.items():
            data[key] = self._read_widget(w)
        try:
            freqs = self._parse_frequency_list()
        except ValueError:
            QMessageBox.warning(self, "Invalid frequency list", "Frequency list must be numeric comma-separated values")
            return False
        if any(f <= 0 for f in freqs):
            QMessageBox.warning(self, "Invalid frequency list", "All frequencies must be > 0")
            return False

        hcov = float(data.get("horizontal_coverage_deg", 0.0))
        vcov = float(data.get("vertical_coverage_deg", 0.0))
        tm = float(data.get("transition_margin_deg", -1.0))
        if hcov <= 0 or vcov <= 0 or tm < 0:
            QMessageBox.warning(self, "Invalid coverage", "Coverage angles must be > 0 and transition margin >= 0")
            return False

        weights = {key: float(w.value()) for key, w in self.weight_widgets.items()}
        data["objective_weights"] = weights
        data["frequencies_hz"] = freqs
        data["frequency_band_hz"] = self.frequency_band_edit.text().strip()
        _save_yaml(self.coverage_config_path, data)
        self.coverage_config = data

        local = _load_yaml(LOCAL_CONFIG_PATH)
        _set_nested(local, "runtime.coverage_target_path", _path_token(self.coverage_config_path))
        _set_nested(local, "runtime.frequencies_hz", freqs)
        _set_nested(local, "runtime.frequency_band_hz", self.frequency_band_edit.text().strip())
        _set_nested(local, "runtime.objective_weights", weights)
        _set_nested(local, "runtime.coverage_half_angle_deg", hcov * 0.5)
        _set_nested(local, "runtime.target_db", float(data.get("in_coverage_target_db", 0.0)))
        _set_nested(local, "runtime.outside_target_db", float(data.get("out_of_coverage_threshold_db", -12.0)))
        _set_nested(local, "runtime.default_bw_h_target_deg", float(data.get("horizontal_target_beamwidth_deg", hcov)))
        _set_nested(local, "runtime.default_bw_v_target_deg", float(data.get("vertical_target_beamwidth_deg", vcov)))
        _set_nested(local, "runtime.alpha_frequency_weights", data.get("alpha_frequency_weights", {}))
        _set_nested(local, "runtime.beta_frequency_weights", data.get("beta_frequency_weights", {}))
        _set_nested(local, "runtime.gamma_frequency_weights", data.get("gamma_frequency_weights", {}))
        _set_nested(local, "runtime.min_efficiency_proxy_db", float(data.get("min_efficiency_proxy_db", _get_nested(local, "runtime.min_efficiency_proxy_db", -6.0))))
        _set_nested(local, "runtime.min_matching_proxy", float(data.get("min_matching_proxy", _get_nested(local, "runtime.min_matching_proxy", 0.45))))
        _save_yaml(LOCAL_CONFIG_PATH, local)
        self.local_config = local
        self._append_log(f"[INFO] Saved coverage config: {self.coverage_config_path}")
        return True

    def save_all_configs(self) -> bool:
        if not self.save_local_config():
            return False
        if not self.save_geometry_parameters():
            return False
        if not self.save_ga_settings_config():
            return False
        if not self.save_coverage_config():
            return False
        if not self.save_solver_settings_config():
            return False
        self.status_label.setText("Config saved")
        return True

    def load_from_files(self) -> None:
        self.load_local_widgets()
        self.load_geometry_to_table()
        self.load_ga_widgets()
        self.load_coverage_widgets()
        self.load_solver_widgets()
        self.refresh_results()
        self.status_label.setText("Config reloaded")

    def _append_log(self, text: str) -> None:
        if not text:
            return
        self.log_view.append(text.rstrip())
        for line in text.splitlines():
            self._process_monitor_line(line.strip())

    def _process_monitor_line(self, line: str) -> None:
        if not line:
            return
        m = self.generation_re.search(line)
        if m:
            self.monitor_generation.setText(f"{m.group(1)} / {m.group(2)}")
        m = self.candidate_re.search(line)
        if m:
            case_id = m.group(1)
            raw = m.group(2)
            try:
                cand = json.loads(raw)
            except json.JSONDecodeError:
                cand = {"raw": raw}
            self.case_candidates[case_id] = cand
            self.monitor_current_candidate.setPlainText(json.dumps(cand, indent=2))
        m = self.fitness_re.search(line)
        if m:
            case_id = m.group(1)
            fit = float(m.group(2))
            if self.best_fitness is None or fit > self.best_fitness:
                self.best_fitness = fit
                self.monitor_best_fitness.setText(str(fit))
                self.best_candidate = self.case_candidates.get(case_id, {})
                self.monitor_best_candidate.setPlainText(json.dumps(self.best_candidate, indent=2) if self.best_candidate else "")

    def _set_running(self, running: bool) -> None:
        for b in [self.btn_check, self.btn_smoke, self.btn_minimal, self.btn_full]:
            b.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.monitor_status.setText("Running" if running else "Idle")
    def _build_runtime_snapshot(self, mode: str, snapshot_geometry: Path, snapshot_coverage: Path) -> dict[str, Any]:
        runtime_raw = _get_nested(self.local_config, "runtime", {})
        runtime: dict[str, Any] = dict(runtime_raw if isinstance(runtime_raw, dict) else {})
        runtime["default_mode"] = mode

        ga = self.ga_settings_config if isinstance(self.ga_settings_config, dict) else {}
        runtime["full_population_size"] = int(ga.get("population_size", runtime.get("full_population_size", 20)))
        runtime["full_generations"] = int(ga.get("generations", runtime.get("full_generations", 20)))
        runtime["ga_crossover_rate"] = float(ga.get("crossover_rate", runtime.get("ga_crossover_rate", 0.5)))
        runtime["ga_mutation_rate"] = float(ga.get("mutation_rate", runtime.get("ga_mutation_rate", 0.1)))
        runtime["full_mutation_scale"] = float(ga.get("mutation_scale", ga.get("mutation_rate", runtime.get("full_mutation_scale", 0.08))))
        runtime["full_elite_count"] = int(ga.get("elitism", runtime.get("full_elite_count", 2)))
        runtime["random_seed"] = int(ga.get("random_seed", runtime.get("random_seed", 42)))
        runtime["ga_early_stopping_generations"] = int(ga.get("early_stopping_generations", runtime.get("ga_early_stopping_generations", 0)))
        runtime["ga_invalid_candidate_penalty"] = float(ga.get("invalid_candidate_penalty", runtime.get("ga_invalid_candidate_penalty", 1000000.0)))
        runtime["ga_workers"] = int(ga.get("workers", runtime.get("ga_workers", 1)))

        cov = self.coverage_config if isinstance(self.coverage_config, dict) else {}
        hcov = float(cov.get("horizontal_coverage_deg", runtime.get("coverage_half_angle_deg", 45.0) * 2.0))
        vcov = float(cov.get("vertical_coverage_deg", runtime.get("default_bw_v_target_deg", 90.0)))
        runtime["coverage_half_angle_deg"] = hcov * 0.5
        runtime["target_db"] = float(cov.get("in_coverage_target_db", runtime.get("target_db", 0.0)))
        runtime["outside_target_db"] = float(cov.get("out_of_coverage_threshold_db", runtime.get("outside_target_db", -12.0)))
        runtime["default_bw_h_target_deg"] = float(cov.get("horizontal_target_beamwidth_deg", hcov))
        runtime["default_bw_v_target_deg"] = float(cov.get("vertical_target_beamwidth_deg", vcov))
        if isinstance(cov.get("frequencies_hz"), list) and cov.get("frequencies_hz"):
            runtime["frequencies_hz"] = [float(x) for x in cov["frequencies_hz"]]
        if cov.get("frequency_band_hz") is not None:
            runtime["frequency_band_hz"] = str(cov.get("frequency_band_hz"))
        if isinstance(cov.get("objective_weights"), dict):
            runtime["objective_weights"] = {k: float(cov["objective_weights"].get(k, DEFAULT_WEIGHTS[k])) for k in DEFAULT_WEIGHTS}
        for key in ["alpha_frequency_weights", "beta_frequency_weights", "gamma_frequency_weights"]:
            if isinstance(cov.get(key), dict):
                runtime[key] = cov[key]
        if "min_efficiency_proxy_db" in cov:
            runtime["min_efficiency_proxy_db"] = float(cov["min_efficiency_proxy_db"])
        if "min_matching_proxy" in cov:
            runtime["min_matching_proxy"] = float(cov["min_matching_proxy"])

        solver = self.solver_settings_config if isinstance(self.solver_settings_config, dict) else {}
        runtime["bempp_tolerance"] = float(solver.get("bempp_tolerance", runtime.get("bempp_tolerance", 1.0e-5)))
        runtime["bempp_max_iterations"] = int(solver.get("bempp_max_iterations", runtime.get("bempp_max_iterations", 400)))
        runtime["solver_retry_policy"] = str(solver.get("retry_policy", runtime.get("solver_retry_policy", "retry_once")))
        runtime["timeout_seconds"] = int(solver.get("timeout_seconds", runtime.get("timeout_seconds", 120)))
        runtime["solver_warmup_enabled"] = bool(solver.get("warm_up_enabled", runtime.get("solver_warmup_enabled", False)))
        runtime["solver_failure_penalty"] = float(solver.get("failure_penalty", runtime.get("solver_failure_penalty", 1000000.0)))
        runtime["solver_prefer_wsl"] = bool(solver.get("wsl_execution_enabled", runtime.get("solver_prefer_wsl", True)))
        handoff = solver.get("mesh_handoff") if isinstance(solver.get("mesh_handoff"), dict) else {}
        runtime["mesh_handoff_required"] = bool(handoff.get("required", runtime.get("mesh_handoff_required", True)))
        runtime["mesh_handoff_validate_readability"] = bool(handoff.get("validate_readability", runtime.get("mesh_handoff_validate_readability", True)))
        runtime["wsl_solver_repeated_runs"] = int(handoff.get("repeated_benchmark_runs", runtime.get("wsl_solver_repeated_runs", 1)))
        distro = str(handoff.get("wsl_distro", "")).strip()
        command = str(handoff.get("wsl_command_path", "")).strip()
        if distro:
            runtime["wsl_distro"] = distro
        if command:
            runtime["wsl_python_executable"] = command

        runtime["ga_parameters_path"] = str(snapshot_geometry.resolve())
        runtime["coverage_target_path"] = str(snapshot_coverage.resolve())
        return runtime

    def _create_run_snapshot(self, label: str, mode: str) -> tuple[Path, Path]:
        run_dir = self.outputs_root / "runs" / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{label}"
        config_dir = run_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        snap_local = config_dir / "local_paths.yaml"
        snap_geometry = config_dir / "geometry_params.yaml"
        snap_ga = config_dir / "ga_settings.yaml"
        snap_cov = config_dir / "coverage_target.yaml"
        snap_solver = config_dir / "solver_settings.yaml"

        _save_yaml(snap_geometry, self.geometry_config)
        _save_yaml(snap_ga, self.ga_settings_config)
        _save_yaml(snap_cov, self.coverage_config)
        _save_yaml(snap_solver, self.solver_settings_config)

        local_data = _load_yaml(LOCAL_CONFIG_PATH)
        local_data["runtime"] = self._build_runtime_snapshot(mode, snap_geometry, snap_cov)
        _save_yaml(snap_local, local_data)

        manifest = {
            "created_at": datetime.now().isoformat(),
            "label": label,
            "mode": mode,
            "config_files": {
                "local_paths": str(snap_local),
                "geometry_params": str(snap_geometry),
                "ga_settings": str(snap_ga),
                "coverage_target": str(snap_cov),
                "solver_settings": str(snap_solver),
            },
        }
        (run_dir / "run_snapshot_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.last_run_snapshot_dir = run_dir
        return snap_local, run_dir

    def _start_process(self, script: str, args: list[str], label: str) -> None:
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "Process running", "Another command is currently running")
            return
        if not self.save_all_configs():
            self.status_label.setText("Config validation failed")
            return
        mode = self.run_mode_combo.currentText().strip().lower()
        if mode not in {"mock", "real"}:
            QMessageBox.warning(self, "Invalid mode", "Run mode must be mock or real")
            return

        config_path, run_dir = self._create_run_snapshot(label, mode)
        cmd_args = list(args) + ["--config", str(config_path)]

        self.current_command_label = label
        self.case_candidates = {}
        self.best_fitness = None
        self.best_candidate = {}
        self.monitor_generation.setText("-")
        self.monitor_current_candidate.setPlainText("")
        self.monitor_best_fitness.setText("-")
        self.monitor_best_candidate.setPlainText("")

        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        self.process.setArguments([str(PROJECT_ROOT / script)] + cmd_args)
        self.process.setWorkingDirectory(str(PROJECT_ROOT))
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)

        self._append_log(f"[RUN] {label}: {script} {' '.join(cmd_args)}")
        self._append_log(f"[RUN] snapshot_dir={run_dir}")
        self.status_label.setText(f"Running: {label}")
        self._set_running(True)
        self.process.start()

    def _on_stdout(self) -> None:
        if not self.process:
            return
        self._append_log(bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace"))

    def _on_stderr(self) -> None:
        if not self.process:
            return
        self._append_log(bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace"))

    def _on_finished(self, exit_code: int, _exit_status) -> None:  # type: ignore[override]
        self._set_running(False)
        status = "PASS" if exit_code == 0 else "FAIL"
        self.monitor_status.setText(f"Finished: {status}")
        self.status_label.setText(f"Finished: {self.current_command_label} [{status}]")
        self._append_log(f"[DONE] {self.current_command_label} exit_code={exit_code}")
        self.refresh_results()

    def stop_process(self) -> None:
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self._append_log("[INFO] Process terminated by user")
            self._set_running(False)
            self.status_label.setText("Process stopped")

    def run_check_dependencies(self) -> None:
        self._start_process("scripts/check_dependencies.py", ["--mode", self.run_mode_combo.currentText()], "check_dependencies")

    def run_smoke_test(self) -> None:
        self._start_process("scripts/smoke_test.py", ["--mode", self.run_mode_combo.currentText()], "smoke_test")

    def run_minimal_optimization(self) -> None:
        self._start_process(
            "scripts/run_minimal_optimization.py",
            ["--mode", self.run_mode_combo.currentText(), "--population-size", str(self.min_pop_spin.value()), "--generations", str(self.min_gen_spin.value())],
            "minimal_optimization",
        )

    def run_full_optimization(self) -> None:
        self.ga_settings_config = _load_yaml(GA_SETTINGS_CONFIG_PATH)
        pop = int(self.ga_settings_config.get("population_size", 20))
        gen = int(self.ga_settings_config.get("generations", 20))
        mut = float(self.ga_settings_config.get("mutation_scale", self.ga_settings_config.get("mutation_rate", 0.08)))
        elite = int(self.ga_settings_config.get("elitism", 2))
        args = [
            "--mode", self.run_mode_combo.currentText(),
            "--population-size", str(pop),
            "--generations", str(gen),
            "--mutation-scale", str(mut),
            "--elite-count", str(elite),
        ]
        self._start_process("scripts/run_full_optimization.py", args, "full_optimization")
    def _result_roots(self) -> list[Path]:
        roots: list[Path] = []
        if self.last_run_snapshot_dir:
            roots.append(self.last_run_snapshot_dir / "outputs")
        roots.append(self.outputs_root)
        roots.append(PROJECT_ROOT / "outputs")
        unique: list[Path] = []
        seen: set[str] = set()
        for p in roots:
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)
        return unique

    def _latest_result_path(self) -> Path | None:
        for root in self._result_roots():
            for name in ["full_optimization_result.json", "minimal_optimization_result.json", "smoke_test_result.json"]:
                candidate = root / name
                if candidate.exists():
                    return candidate
        return None

    def _latest_score_path(self) -> Path | None:
        newest: Path | None = None
        newest_mtime = 0.0
        for root in self._result_roots():
            score_dir = root / "scoring"
            if not score_dir.exists():
                continue
            for path in score_dir.glob("score_*.json"):
                mtime = path.stat().st_mtime
                if mtime > newest_mtime:
                    newest = path
                    newest_mtime = mtime
        return newest

    def refresh_results(self) -> None:
        latest = self._latest_result_path()
        if latest is None:
            self.results_summary.setPlainText("No run result found")
            self.results_best.setPlainText("")
        else:
            try:
                payload = json.loads(latest.read_text(encoding="utf-8"))
                self.results_summary.setPlainText(json.dumps(payload, indent=2)[:4000])
                if "best_candidate" in payload:
                    self.results_best.setPlainText(json.dumps(payload.get("best_candidate", {}), indent=2))
                elif "candidate" in payload:
                    self.results_best.setPlainText(json.dumps(payload.get("candidate", {}), indent=2))
                else:
                    self.results_best.setPlainText("")
            except Exception as exc:
                self.results_summary.setPlainText(f"Failed to read latest result: {exc}")
                self.results_best.setPlainText("")

        score = self._latest_score_path()
        if score is None:
            self.results_score.setPlainText("No score breakdown found")
        else:
            try:
                self.results_score.setPlainText(json.dumps(json.loads(score.read_text(encoding="utf-8")), indent=2)[:5000])
            except Exception as exc:
                self.results_score.setPlainText(f"Failed to read score breakdown: {exc}")

    def open_output_folder(self) -> None:
        out = self.outputs_root
        out.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(out))  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(out)], check=False)
        except Exception as exc:
            QMessageBox.warning(self, "Open folder failed", str(exc))

    def export_config_snapshot(self) -> None:
        default_name = f"config_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path_str, _ = QFileDialog.getSaveFileName(self, "Export Config Snapshot", str(self.outputs_root / default_name), "JSON Files (*.json)")
        if not path_str:
            return
        payload = {
            "meta": {"exported_at": datetime.now().isoformat(), "project_root": str(PROJECT_ROOT)},
            "paths": {
                "local_paths": str(LOCAL_CONFIG_PATH),
                "geometry_params": str(GEOMETRY_CONFIG_PATH),
                "ga_settings": str(GA_SETTINGS_CONFIG_PATH),
                "coverage_target": str(self.coverage_config_path),
                "solver_settings": str(SOLVER_SETTINGS_CONFIG_PATH),
            },
            "local_paths": _load_yaml(LOCAL_CONFIG_PATH),
            "geometry_params": _load_yaml(GEOMETRY_CONFIG_PATH),
            "ga_settings": _load_yaml(GA_SETTINGS_CONFIG_PATH),
            "coverage_target": _load_yaml(self.coverage_config_path),
            "solver_settings": _load_yaml(SOLVER_SETTINGS_CONFIG_PATH),
        }
        out = Path(path_str)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._append_log(f"[INFO] Exported config snapshot: {out}")

    def load_config_snapshot(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Load Previous Config", str(self.outputs_root), "JSON Files (*.json)")
        if not path_str:
            return
        path = Path(path_str)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.warning(self, "Invalid snapshot", f"Unable to parse snapshot: {exc}")
            return

        local_cfg = payload.get("local_paths") or payload.get("local_config")
        geometry_cfg = payload.get("geometry_params") or payload.get("ga_config")
        ga_cfg = payload.get("ga_settings")
        coverage_cfg = payload.get("coverage_target") or payload.get("coverage_config")
        solver_cfg = payload.get("solver_settings")

        if not isinstance(local_cfg, dict) or not isinstance(geometry_cfg, dict) or not isinstance(coverage_cfg, dict):
            QMessageBox.warning(self, "Invalid snapshot", "Snapshot missing required config payload")
            return

        _save_yaml(LOCAL_CONFIG_PATH, local_cfg)
        self.local_config = local_cfg
        _save_yaml(GEOMETRY_CONFIG_PATH, geometry_cfg)
        if isinstance(ga_cfg, dict):
            _save_yaml(GA_SETTINGS_CONFIG_PATH, ga_cfg)
        if isinstance(solver_cfg, dict):
            _save_yaml(SOLVER_SETTINGS_CONFIG_PATH, solver_cfg)
        _save_yaml(self.coverage_config_path, coverage_cfg)

        self._append_log(f"[INFO] Loaded config snapshot: {path}")
        self.load_from_files()
