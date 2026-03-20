from __future__ import annotations

import math
import tkinter as tk
from typing import Any

from ..domain.specs import ACCENT, BORDER, MUTED, TEXT


PREVIEW_GROUP_COLORS = (
    "#37c8b4",
    "#f3a712",
    "#8e7dff",
    "#ef476f",
    "#4cc9f0",
    "#90be6d",
    "#ffd166",
    "#ff7b72",
)


class PreviewRenderer:
    """Render embedded preview content for both OpenGL and Canvas backends."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.interaction_sensitivity = 1.0

    def set_interaction_sensitivity(self, sensitivity: float) -> None:
        self.interaction_sensitivity = max(0.3, min(2.5, float(sensitivity)))

    def update_preview_view_var(self) -> None:
        self.app.preview_view_var.set(
            f"視角：yaw {self.app.preview_yaw_deg:.0f}°, "
            f"pitch {self.app.preview_pitch_deg:.0f}°, "
            f"zoom {self.app.preview_zoom:.2f}x"
        )

    def reset_preview_view(self, _event: tk.Event | None = None) -> None:
        if self.app.opengl_preview is not None and self.app.opengl_preview.available:
            self.app.opengl_preview.reset_camera()
            return
        self.app.preview_yaw_deg = 32.0
        self.app.preview_pitch_deg = -18.0
        self.app.preview_zoom = 1.0
        self.app.preview_drag_origin = None
        self.app.preview_drag_angles = None
        self.update_preview_view_var()
        self.redraw_embedded_preview()

    def start_preview_drag(self, event: tk.Event) -> None:
        if self.app.opengl_preview is not None and self.app.opengl_preview.available:
            return
        self.app.preview_drag_origin = (int(event.x), int(event.y))
        self.app.preview_drag_angles = (self.app.preview_yaw_deg, self.app.preview_pitch_deg)

    def drag_preview_view(self, event: tk.Event) -> None:
        if self.app.opengl_preview is not None and self.app.opengl_preview.available:
            return
        if self.app.preview_drag_origin is None or self.app.preview_drag_angles is None:
            return
        dx = int(event.x) - self.app.preview_drag_origin[0]
        dy = int(event.y) - self.app.preview_drag_origin[1]
        drag_scale = self.interaction_sensitivity
        self.app.preview_yaw_deg = self.app.preview_drag_angles[0] + (dx * 0.45 * drag_scale)
        self.app.preview_pitch_deg = max(-88.0, min(88.0, self.app.preview_drag_angles[1] - (dy * 0.35 * drag_scale)))
        self.update_preview_view_var()
        self.redraw_embedded_preview()

    def end_preview_drag(self, _event: tk.Event) -> None:
        if self.app.opengl_preview is not None and self.app.opengl_preview.available:
            return
        self.app.preview_drag_origin = None
        self.app.preview_drag_angles = None

    def zoom_preview_view(self, event: tk.Event) -> None:
        if self.app.opengl_preview is not None and self.app.opengl_preview.available:
            return
        delta = 0
        if hasattr(event, "delta") and event.delta:
            delta = 1 if event.delta > 0 else -1
        elif getattr(event, "num", None) == 4:
            delta = 1
        elif getattr(event, "num", None) == 5:
            delta = -1
        if delta == 0:
            return
        zoom_step = max(1.02, 1.0 + (0.12 * self.interaction_sensitivity))
        factor = zoom_step if delta > 0 else 1 / zoom_step
        self.app.preview_zoom = max(0.25, min(6.0, self.app.preview_zoom * factor))
        self.update_preview_view_var()
        self.redraw_embedded_preview()

    def project_preview_points(
        self,
        points: dict[int, tuple[float, float, float]],
    ) -> tuple[dict[int, tuple[float, float]], tuple[float, float, float, float]]:
        xs = [coords[0] for coords in points.values()]
        ys = [coords[1] for coords in points.values()]
        zs = [coords[2] for coords in points.values()]
        center_x = (min(xs) + max(xs)) / 2.0
        center_y = (min(ys) + max(ys)) / 2.0
        center_z = (min(zs) + max(zs)) / 2.0

        projected: dict[int, tuple[float, float]] = {}
        us: list[float] = []
        vs: list[float] = []
        for tag, (x, y, z) in points.items():
            u, v = self.project_preview_vector((x - center_x, y - center_y, z - center_z))
            projected[tag] = (u, v)
            us.append(u)
            vs.append(v)

        return projected, (min(us), max(us), min(vs), max(vs))

    def project_preview_vector(self, vector: tuple[float, float, float]) -> tuple[float, float]:
        """Project a 3D vector to preview canvas UV coordinates using current view angles."""
        yaw = math.radians(self.app.preview_yaw_deg)
        pitch = math.radians(self.app.preview_pitch_deg)
        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)
        cos_pitch = math.cos(pitch)
        sin_pitch = math.sin(pitch)

        x, y, z = vector
        x1 = (cos_yaw * x) - (sin_yaw * y)
        y1 = (sin_yaw * x) + (cos_yaw * y)
        z1 = z

        y2 = (cos_pitch * y1) - (sin_pitch * z1)
        z2 = (sin_pitch * y1) + (cos_pitch * z1)
        return x1, z2

    def draw_preview_axis_triad(self, canvas: tk.Canvas, width: int, height: int) -> None:
        """Draw a small XYZ axis triad that follows current preview view rotation."""
        origin_x = 58
        origin_y = height - 54
        axis_scale = 34
        canvas.create_rectangle(origin_x - 34, origin_y - 34, origin_x + 66, origin_y + 26, outline=BORDER)

        axes = (
            ("X", (1.0, 0.0, 0.0), "#ff6b6b"),
            ("Y", (0.0, 1.0, 0.0), "#51cf66"),
            ("Z", (0.0, 0.0, 1.0), "#4dabf7"),
        )
        for label, vector, color in axes:
            u, v = self.project_preview_vector(vector)
            end_x = origin_x + (u * axis_scale)
            end_y = origin_y - (v * axis_scale)
            canvas.create_line(origin_x, origin_y, end_x, end_y, fill=color, width=2, arrow=tk.LAST)
            canvas.create_text(end_x + 8, end_y, text=label, fill=color, anchor="w", font="AthUiCanvasSmallFont")
        canvas.create_oval(origin_x - 2, origin_y - 2, origin_x + 2, origin_y + 2, fill=TEXT, outline="")

    def draw_preview_placeholder(self, message: str) -> None:
        if self.app.opengl_preview is not None and self.app.opengl_preview.available:
            self.app.opengl_preview.clear(message)
            return
        if self.app.embedded_preview_canvas is None:
            return
        canvas = self.app.embedded_preview_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 200)
        height = max(canvas.winfo_height(), 160)
        canvas.create_text(
            width / 2,
            height / 2,
            text=message,
            fill=MUTED,
            font="AthUiCanvasFont",
            width=max(width - 40, 160),
            justify="center",
        )

    def redraw_embedded_preview(self, _event: tk.Event | None = None) -> None:
        if self.app.opengl_preview is not None and self.app.opengl_preview.available:
            if self.app.preview_geometry is None:
                self.app.opengl_preview.clear("請執行 ATH，或載入最新輸出以在此顯示幾何。")
                return
            group_edges = {
                int(group_id): list(group_data)
                for group_id, group_data in dict(self.app.preview_geometry.get("group_edges", {})).items()
            }
            color_map = {
                group_id: PREVIEW_GROUP_COLORS[index % len(PREVIEW_GROUP_COLORS)]
                for index, group_id in enumerate(sorted(group_edges))
            }
            self.app.opengl_preview.set_geometry(
                self.app.preview_geometry,
                group_color_map=color_map,
                fallback_color=ACCENT,
                show_group_normals=bool(self.app.preview_show_normals_var.get()),
            )
            return

        if self.app.embedded_preview_canvas is None:
            return
        canvas = self.app.embedded_preview_canvas
        if self.app.preview_geometry is None:
            self.draw_preview_placeholder("請執行 ATH，或載入最新輸出以在此顯示幾何。")
            return

        canvas.delete("all")
        width = max(canvas.winfo_width(), 200)
        height = max(canvas.winfo_height(), 160)
        pad = 28

        points = self.app.preview_geometry["points"]
        edges = self.app.preview_geometry["edges"]
        projected, (min_u, max_u, min_v, max_v) = self.project_preview_points(points)

        span_u = max(max_u - min_u, 1e-6)
        span_v = max(max_v - min_v, 1e-6)
        base_scale = min((width - 2 * pad) / span_u, (height - 2 * pad) / span_v)
        scale = base_scale * self.app.preview_zoom
        offset_u = (width - (span_u * scale)) / 2
        offset_v = (height - (span_v * scale)) / 2

        max_edges = 12000
        group_edges = {
            int(group_id): list(group_data)
            for group_id, group_data in dict(self.app.preview_geometry.get("group_edges", {})).items()
        }
        if group_edges:
            sorted_groups = sorted(group_edges)
            color_map = {
                group_id: PREVIEW_GROUP_COLORS[index % len(PREVIEW_GROUP_COLORS)]
                for index, group_id in enumerate(sorted_groups)
            }
            for group_id in sorted_groups:
                grouped = group_edges[group_id]
                step = max(1, len(grouped) // max_edges) if len(grouped) > max_edges else 1
                for index, (a, b) in enumerate(grouped):
                    if index % step != 0:
                        continue
                    u1, v1 = projected[a]
                    u2, v2 = projected[b]
                    x1 = offset_u + ((u1 - min_u) * scale)
                    y1 = height - (offset_v + ((v1 - min_v) * scale))
                    x2 = offset_u + ((u2 - min_u) * scale)
                    y2 = height - (offset_v + ((v2 - min_v) * scale))
                    canvas.create_line(x1, y1, x2, y2, fill=color_map[group_id], width=1)

            legend_x = 14
            legend_y = 14
            canvas.create_rectangle(legend_x, legend_y, legend_x + 188, legend_y + (22 * len(sorted_groups)) + 12, outline=BORDER)
            for index, group_id in enumerate(sorted_groups[:8]):
                y = legend_y + 14 + (index * 22)
                canvas.create_line(legend_x + 10, y, legend_x + 32, y, fill=color_map[group_id], width=3)
                canvas.create_text(legend_x + 40, y, text=f"群組 {group_id}", fill=TEXT, anchor="w", font="AthUiCanvasSmallFont")
        else:
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
        canvas.create_text(
            width - 12,
            12,
            text=self.app.preview_view_var.get(),
            fill=MUTED,
            anchor="ne",
            font="AthUiCanvasSmallFont",
        )
        self.draw_preview_axis_triad(canvas, width, height)
