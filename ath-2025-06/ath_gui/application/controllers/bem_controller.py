"""BEM result and mesh inspection controller."""

from __future__ import annotations

import os
from pathlib import Path
from tkinter import messagebox
from typing import Any

from ...domain.specs import APP_TITLE
from ...infrastructure.bem_mesh import format_mesh_info_text, inspect_mesh_file
from ...infrastructure.bem_results import default_bem_result_dir, describe_bem_status, format_summary_text, load_bem_results
from ...infrastructure.preview_core import compute_output_directory, describe_group_source
from ...presentation.bem_plot import draw_directivity_view


class BemController:
    """Coordinate BEM mesh inspection and result loading for the UI."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def inspect_bem_mesh(self) -> None:
        ath_state = self.app.collect_effective_horn_state()
        state = self.app.collect_effective_bem_state(ath_state)
        mesh_path = self.app.resolve_bem_mesh_path(state, set_status=False)
        if mesh_path is None or not Path(mesh_path).exists():
            messagebox.showerror(
                APP_TITLE,
                "目前沒有可供 BEM 檢查的 `.msh` 檔。\n\n請啟用 `Output.MSH = 1` 並執行 ATH，或手動指定網格檔。",
            )
            return

        try:
            mesh_info = inspect_mesh_file(
                Path(mesh_path),
                mesh_scale_to_meter=float(state.get("BEM.MeshScaleToMeter", 0.001)),
            )
        except Exception as exc:
            self.app.bem_status_var.set("錯誤")
            self.app.group_status_var.set("分群狀態：網格檢查失敗")
            self.app.status_var.set("BEM 網格檢查失敗。")
            messagebox.showerror(APP_TITLE, f"檢查網格失敗：\n{exc}")
            return

        self.app._set_text_widget(self.app.bem_mesh_text, format_mesh_info_text(mesh_info))
        self.app.bem_status_var.set("閒置")
        groups = [int(value) for value in mesh_info.get("detected_groups", [])]
        source_label = describe_group_source(str(mesh_info.get("group_source", "unknown")))
        self.app.group_status_var.set(
            f"分群狀態：已偵測 {len(groups)} 個群組（{source_label}）"
        )
        self.app.preview_group_var.set(
            self.app._format_group_summary(
                groups,
                group_source=str(mesh_info.get("group_source", "unknown")),
                count_map={str(key): int(value) for key, value in dict(mesh_info.get("element_count_per_group", {})).items()},
            )
        )
        self.app.status_var.set(f"已檢查 BEM 網格：{Path(mesh_path).name}")
        self.app.mesh_status_var.set(str(mesh_path))
        self.app._update_runtime_status()
        self.app._select_workspace_tab("MeshInfo")

    def resolve_bem_result_dir(self) -> Path | None:
        cfg_path = self.app.current_horn_path.get().strip()
        if not cfg_path:
            return self.app.bem_last_result_dir
        output_dir = compute_output_directory(self.app.collect_global_state(), self.app.collect_effective_horn_state(), Path(cfg_path))
        return default_bem_result_dir(output_dir)

    def refresh_bem_plot(self) -> None:
        caption = draw_directivity_view(
            self.app.bem_polar_canvas,
            self.app.bem_polar_rows,
            mode=str(self.app.bem_plot_mode_var.get()).strip() or "band_map",
            preferred_hz=1000.0,
            log_x=bool(self.app.bem_plot_log_x_var.get()),
        )
        if caption:
            self.app.bem_plot_caption_var.set(caption)

    def open_bem_solver_log(self) -> None:
        if self.app.bem_last_log_path is None or not self.app.bem_last_log_path.exists():
            messagebox.showinfo(APP_TITLE, "目前尚無可開啟的 BEM 求解器日誌。")
            return
        try:
            os.startfile(str(self.app.bem_last_log_path))
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"無法開啟求解器日誌：\n{exc}")

    def load_bem_results(self, result_dir: Path | None = None) -> None:
        target_dir = result_dir or self.resolve_bem_result_dir()
        if target_dir is None:
            messagebox.showinfo(APP_TITLE, "目前沒有可載入的 BEM 結果目錄。")
            return
        try:
            results = load_bem_results(target_dir)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"載入 BEM 結果失敗：\n{exc}")
            return

        self.app.bem_last_result_dir = target_dir
        self.app.bem_last_log_path = Path(results["log_path"])
        self.app.bem_polar_rows = list(results["polar_rows"])
        self.app._set_text_widget(self.app.bem_summary_text, format_summary_text(results))
        if results["mesh_info"]:
            self.app._set_text_widget(self.app.bem_mesh_text, format_mesh_info_text(results["mesh_info"]))
        else:
            self.app._set_text_widget(self.app.bem_mesh_text, "這次 BEM 執行沒有找到 mesh_info.json。")
        self.app.bem_status_var.set(describe_bem_status(results["summary"].get("status", "done")))
        if str(results["summary"].get("status", "done")).strip().lower() == "done":
            self.app.stop_bem_progress("BEM 已完成")
        self.app.bem_result_path_var.set(str(target_dir))
        self.refresh_bem_plot()
        self.app.status_var.set(f"已載入 BEM 結果：{target_dir}")
        self.app._update_runtime_status()
        self.app._select_workspace_tab("Polar")
