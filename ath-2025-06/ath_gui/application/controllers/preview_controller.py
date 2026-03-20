"""Preview workflow controller for embedded geometry loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...infrastructure.preview_core import describe_group_source, load_embedded_preview_data


class PreviewController:
    """Coordinate preview loading and UI updates for the Tk app."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def _apply_embedded_preview_error(self, request_id: int, preview_file: Path, exc: Exception) -> None:
        if request_id != self.app.preview_request_id:
            return
        self.app.preview_geometry = None
        self.app.preview_path_var.set(str(preview_file))
        self.app.preview_status_var.set("預覽狀態：載入失敗")
        self.app.group_status_var.set("分群狀態：無法分析")
        self.app.preview_group_var.set("分群摘要：預覽載入失敗，無法取得群組資訊。")
        self.app.preview_meta_var.set(f"內嵌預覽載入失敗：{exc}")
        self.app._draw_preview_placeholder("內嵌預覽載入失敗；你仍可使用外部程式開啟該檔案。")
        self.app._update_runtime_status()

    def _apply_embedded_preview_data(self, request_id: int, preview_file: Path, data: dict[str, object]) -> None:
        if request_id != self.app.preview_request_id:
            return
        self.app.preview_geometry = data
        self.app.last_generated_preview_file = preview_file
        bbox = data["bbox"]
        self.app.preview_path_var.set(str(preview_file))
        self.app.preview_status_var.set("預覽狀態：已載入")
        group_source = describe_group_source(str(data.get("group_source", "unknown")))
        self.app.preview_meta_var.set(
            f"{data['file_name']} | 維度 {data['mesh_dimension']} | 節點 {data['node_count']} | "
            f"邊線 {data['edge_count']} | 元素 {data['element_count']} | 群組來源 {group_source} | "
            f"bbox x[{bbox[0]:.1f},{bbox[1]:.1f}] y[{bbox[2]:.1f},{bbox[3]:.1f}] z[{bbox[4]:.1f},{bbox[5]:.1f}]"
        )
        self.app._update_group_status_from_preview_data(preview_file, data)
        self.app._redraw_embedded_preview()
        self.app._select_workspace_tab("Geometry3D")

    def _load_embedded_preview_worker(self, request_id: int, preview_file: Path) -> None:
        try:
            data = load_embedded_preview_data(preview_file)
        except Exception as exc:
            self._apply_embedded_preview_error(request_id, preview_file, exc)
            return
        self._apply_embedded_preview_data(request_id, preview_file, data)

    def load_embedded_preview_file(self, preview_file: Path) -> None:
        self.app.preview_request_id += 1
        request_id = self.app.preview_request_id
        self.app.preview_geometry = None
        self.app.last_generated_preview_file = preview_file
        self.app.preview_path_var.set(str(preview_file))
        self.app.preview_status_var.set("預覽狀態：載入中")
        self.app.group_status_var.set("分群狀態：分析中")
        self.app.preview_group_var.set("分群摘要：正在分析預覽檔。")
        self.app.preview_meta_var.set("正在載入內嵌預覽...")
        self.app._draw_preview_placeholder("正在將幾何匯入內嵌預覽...")
        self.app._update_runtime_status()
        self.app.after(10, lambda: self._load_embedded_preview_worker(request_id, preview_file))
