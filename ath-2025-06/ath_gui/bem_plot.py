"""Minimal Tk canvas plotting for BEM polar results."""

from __future__ import annotations

import math
import tkinter as tk

from .specs import ACCENT, BORDER, INPUT_BG, MUTED, TEXT


def draw_placeholder(canvas: tk.Canvas, message: str) -> None:
    canvas.delete("all")
    width = max(canvas.winfo_width(), 260)
    height = max(canvas.winfo_height(), 220)
    canvas.create_rectangle(1, 1, width - 2, height - 2, outline=BORDER)
    canvas.create_text(
        width / 2,
        height / 2,
        text=message,
        fill=MUTED,
        font="AthUiCanvasFont",
        width=max(width - 40, 180),
        justify="center",
    )


def _group_rows_by_frequency(polar_rows: list[dict[str, float]]) -> dict[float, list[dict[str, float]]]:
    grouped: dict[float, list[dict[str, float]]] = {}
    for row in polar_rows:
        grouped.setdefault(float(row["freq_hz"]), []).append(row)
    return grouped


def draw_polar_plot(canvas: tk.Canvas, polar_rows: list[dict[str, float]], *, preferred_hz: float = 1000.0) -> str:
    if not polar_rows:
        draw_placeholder(canvas, "請執行 BEM 並載入 `polar.csv`，即可在此顯示指向性曲線。")
        return ""

    grouped = _group_rows_by_frequency(polar_rows)
    frequencies = sorted(grouped)
    target_freq = min(frequencies, key=lambda value: (abs(value - preferred_hz), value))
    rows = sorted(grouped[target_freq], key=lambda item: item["angle_deg"])
    if len(rows) < 3:
        draw_placeholder(canvas, "可用的極座標取樣不足，無法繪圖。")
        return ""

    canvas.delete("all")
    width = max(canvas.winfo_width(), 260)
    height = max(canvas.winfo_height(), 220)
    canvas.configure(background=INPUT_BG, highlightbackground=BORDER)

    center_x = width / 2
    center_y = height / 2 + 8
    radius_limit = min(width, height) * 0.37

    spl_values = [float(row["spl_db"]) for row in rows]
    spl_min = math.floor(min(spl_values) / 5.0) * 5.0
    spl_max = math.ceil(max(spl_values) / 5.0) * 5.0
    if math.isclose(spl_min, spl_max):
        spl_min -= 5.0
        spl_max += 5.0
    spl_span = max(spl_max - spl_min, 1e-6)

    for ring_index in range(1, 5):
        ring_radius = radius_limit * (ring_index / 4.0)
        canvas.create_oval(
            center_x - ring_radius,
            center_y - ring_radius,
            center_x + ring_radius,
            center_y + ring_radius,
            outline=BORDER,
        )
        label_value = spl_min + spl_span * (ring_index / 4.0)
        canvas.create_text(center_x + 6, center_y - ring_radius - 8, text=f"{label_value:.0f} dB", fill=MUTED, anchor="w", font="AthUiCanvasSmallFont")

    for angle_deg in range(-180, 181, 45):
        angle_rad = math.radians(angle_deg)
        x = center_x + math.sin(angle_rad) * radius_limit
        y = center_y - math.cos(angle_rad) * radius_limit
        canvas.create_line(center_x, center_y, x, y, fill=BORDER)
        label_x = center_x + math.sin(angle_rad) * (radius_limit + 16)
        label_y = center_y - math.cos(angle_rad) * (radius_limit + 16)
        canvas.create_text(label_x, label_y, text=f"{angle_deg}°", fill=MUTED, font="AthUiCanvasSmallFont")

    polyline: list[float] = []
    for row in rows:
        angle_rad = math.radians(float(row["angle_deg"]))
        normalized = (float(row["spl_db"]) - spl_min) / spl_span
        radius = max(0.08, normalized) * radius_limit
        x = center_x + math.sin(angle_rad) * radius
        y = center_y - math.cos(angle_rad) * radius
        polyline.extend((x, y))

    canvas.create_line(*polyline, fill=ACCENT, width=2, smooth=True)
    canvas.create_oval(center_x - 2, center_y - 2, center_x + 2, center_y + 2, fill=TEXT, outline="")

    caption = f"極座標 SPL @ {target_freq:.1f} Hz"
    canvas.create_text(width / 2, 18, text=caption, fill=TEXT, font="AthUiHeadingFont")
    canvas.create_rectangle(1, 1, width - 2, height - 2, outline=BORDER)
    return caption
