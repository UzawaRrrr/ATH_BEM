"""Tk canvas plotting for BEM directivity results."""

from __future__ import annotations

import math
import tkinter as tk

from ..domain.specs import ACCENT, BORDER, INPUT_BG, MUTED, TEXT


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


def _color_lerp(color_a: tuple[int, int, int], color_b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(color_a[0] + ((color_b[0] - color_a[0]) * t)),
        int(color_a[1] + ((color_b[1] - color_a[1]) * t)),
        int(color_a[2] + ((color_b[2] - color_a[2]) * t)),
    )


def _klippel_like_color(value_db: float, vmin: float = -24.0, vmax: float = 6.0) -> str:
    """Map dB value to a Klippel-like color ramp."""
    anchors = [
        (10, 35, 66),
        (21, 62, 117),
        (34, 94, 168),
        (29, 145, 192),
        (65, 182, 196),
        (127, 205, 187),
        (199, 233, 180),
        (255, 255, 191),
        (254, 224, 139),
        (253, 174, 97),
        (244, 109, 67),
        (215, 48, 39),
    ]
    if vmax <= vmin:
        return "#808080"
    normalized = (value_db - vmin) / (vmax - vmin)
    normalized = max(0.0, min(1.0, normalized))
    position = normalized * (len(anchors) - 1)
    index = int(math.floor(position))
    if index >= len(anchors) - 1:
        color = anchors[-1]
    else:
        color = _color_lerp(anchors[index], anchors[index + 1], position - index)
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


def _draw_single_frequency_polar(canvas: tk.Canvas, polar_rows: list[dict[str, float]], *, preferred_hz: float = 1000.0) -> str:
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
    caption = f"單頻極座標 @ {target_freq:.1f} Hz"
    canvas.create_text(width / 2, 18, text=caption, fill=TEXT, font="AthUiHeadingFont")
    canvas.create_rectangle(1, 1, width - 2, height - 2, outline=BORDER)
    return caption


def _draw_band_map(canvas: tk.Canvas, polar_rows: list[dict[str, float]], *, log_x: bool = True) -> str:
    grouped = _group_rows_by_frequency(polar_rows)
    if not grouped:
        draw_placeholder(canvas, "尚未有可用頻段資料。")
        return ""

    frequencies = sorted(grouped)
    angle_set = sorted({float(row["angle_deg"]) for rows in grouped.values() for row in rows})
    if len(frequencies) < 2 or len(angle_set) < 2:
        draw_placeholder(canvas, "頻率或角度取樣不足，無法顯示頻段離軸圖。")
        return ""

    matrix: dict[tuple[float, float], float] = {}
    for freq, rows in grouped.items():
        for row in rows:
            matrix[(freq, float(row["angle_deg"]))] = float(row["spl_db"])

    on_axis_angle = min(angle_set, key=lambda angle: abs(angle))
    relative_values: list[float] = []
    for freq in frequencies:
        reference = matrix.get((freq, on_axis_angle))
        if reference is None:
            continue
        for angle in angle_set:
            value = matrix.get((freq, angle), reference) - reference
            relative_values.append(value)

    if not relative_values:
        draw_placeholder(canvas, "離軸資料不完整，無法顯示頻段圖。")
        return ""

    canvas.delete("all")
    width = max(canvas.winfo_width(), 360)
    height = max(canvas.winfo_height(), 280)
    left = 58
    right = width - 28
    top = 22
    bottom = height - 48
    plot_w = max(right - left, 12)
    plot_h = max(bottom - top, 12)

    min_freq = max(float(frequencies[0]), 1e-6)
    max_freq = max(float(frequencies[-1]), min_freq + 1e-6)
    min_angle = float(angle_set[0])
    max_angle = float(angle_set[-1])
    angle_span = max(max_angle - min_angle, 1e-6)

    if log_x:
        log_min = math.log10(min_freq)
        log_max = math.log10(max_freq)
        log_span = max(log_max - log_min, 1e-9)

        def freq_to_x(freq: float) -> float:
            return left + ((math.log10(max(freq, min_freq)) - log_min) / log_span) * plot_w
    else:
        freq_span = max(max_freq - min_freq, 1e-9)

        def freq_to_x(freq: float) -> float:
            return left + ((freq - min_freq) / freq_span) * plot_w

    def angle_to_y(angle: float) -> float:
        return bottom - ((angle - min_angle) / angle_span) * plot_h

    freq_edges: list[float] = []
    for index, freq in enumerate(frequencies):
        if index == 0:
            next_freq = frequencies[index + 1]
            freq_edges.append(freq - ((next_freq - freq) / 2.0))
        else:
            prev_freq = frequencies[index - 1]
            freq_edges.append((prev_freq + freq) / 2.0)
    freq_edges.append(frequencies[-1] + ((frequencies[-1] - frequencies[-2]) / 2.0))

    angle_edges: list[float] = []
    for index, angle in enumerate(angle_set):
        if index == 0:
            next_angle = angle_set[index + 1]
            angle_edges.append(angle - ((next_angle - angle) / 2.0))
        else:
            prev_angle = angle_set[index - 1]
            angle_edges.append((prev_angle + angle) / 2.0)
    angle_edges.append(angle_set[-1] + ((angle_set[-1] - angle_set[-2]) / 2.0))

    for fi, freq in enumerate(frequencies):
        x0 = freq_to_x(max(freq_edges[fi], min_freq))
        x1 = freq_to_x(max(freq_edges[fi + 1], min_freq))
        if x1 < x0:
            x0, x1 = x1, x0
        for ai, angle in enumerate(angle_set):
            y0 = angle_to_y(angle_edges[ai + 1])
            y1 = angle_to_y(angle_edges[ai])
            spl_rel = matrix.get((freq, angle), matrix.get((freq, on_axis_angle), 0.0)) - matrix.get((freq, on_axis_angle), 0.0)
            color = _klippel_like_color(spl_rel, vmin=-24.0, vmax=6.0)
            canvas.create_rectangle(x0, y0, x1, y1, outline="", fill=color)

    canvas.create_rectangle(left, top, right, bottom, outline=BORDER)

    if log_x:
        tick_freqs = [100, 200, 500, 1000, 2000, 5000, 10000, 20000]
        tick_freqs = [freq for freq in tick_freqs if min_freq <= freq <= max_freq]
    else:
        tick_freqs = [min_freq + ((max_freq - min_freq) * ratio) for ratio in (0.0, 0.25, 0.5, 0.75, 1.0)]

    for freq in tick_freqs:
        x = freq_to_x(freq)
        canvas.create_line(x, bottom, x, bottom + 5, fill=BORDER)
        label = f"{int(freq)}" if freq >= 100 else f"{freq:.1f}"
        canvas.create_text(x, bottom + 16, text=label, fill=MUTED, font="AthUiCanvasSmallFont")

    angle_ticks = [min_angle, (min_angle + max_angle) / 2.0, max_angle]
    for angle in angle_ticks:
        y = angle_to_y(angle)
        canvas.create_line(left - 5, y, left, y, fill=BORDER)
        canvas.create_text(left - 8, y, text=f"{angle:.0f}°", fill=MUTED, anchor="e", font="AthUiCanvasSmallFont")

    canvas.create_text((left + right) / 2, height - 18, text="Frequency [Hz]", fill=MUTED, font="AthUiCanvasSmallFont")
    canvas.create_text(18, (top + bottom) / 2, text="Angle [deg]", fill=MUTED, angle=90, font="AthUiCanvasSmallFont")

    legend_x0 = right - 170
    legend_y0 = top + 12
    legend_w = 150
    legend_h = 14
    for i in range(legend_w):
        value = -24.0 + (30.0 * (i / max(legend_w - 1, 1)))
        color = _klippel_like_color(value, vmin=-24.0, vmax=6.0)
        canvas.create_line(legend_x0 + i, legend_y0, legend_x0 + i, legend_y0 + legend_h, fill=color)
    canvas.create_rectangle(legend_x0, legend_y0, legend_x0 + legend_w, legend_y0 + legend_h, outline=BORDER)
    canvas.create_text(legend_x0, legend_y0 + legend_h + 10, text="-24 dB", fill=MUTED, anchor="w", font="AthUiCanvasSmallFont")
    canvas.create_text(legend_x0 + legend_w, legend_y0 + legend_h + 10, text="+6 dB", fill=MUTED, anchor="e", font="AthUiCanvasSmallFont")

    caption = f"頻段離軸圖（{'Log X' if log_x else 'Linear X'}）"
    canvas.create_text((left + right) / 2, 10, text=caption, fill=TEXT, font="AthUiHeadingFont")
    return caption


def draw_directivity_view(
    canvas: tk.Canvas,
    polar_rows: list[dict[str, float]],
    *,
    mode: str = "band_map",
    preferred_hz: float = 1000.0,
    log_x: bool = True,
) -> str:
    if not polar_rows:
        draw_placeholder(canvas, "請執行 BEM 並載入 `polar.csv`，即可在此顯示指向性。")
        return ""
    if mode == "single_freq_polar":
        return _draw_single_frequency_polar(canvas, polar_rows, preferred_hz=preferred_hz)
    return _draw_band_map(canvas, polar_rows, log_x=log_x)
