"""Tk canvas plotting for BEM directivity results."""

from __future__ import annotations

import base64
import io
import math
import tkinter as tk
from typing import Any

import numpy as np

from ..domain.specs import ACCENT, BORDER, INPUT_BG, MUTED, TEXT
from .bandmap_display import BandMapData, BandMapDisplayOptions, BandMapRenderData, prepare_bandmap_render_data


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


def _format_freq_tick(freq_hz: float) -> str:
    if freq_hz >= 1000.0:
        if freq_hz >= 10000.0 or abs((freq_hz / 1000.0) - round(freq_hz / 1000.0)) < 1e-9:
            return f"{freq_hz / 1000.0:.0f}k"
        return f"{freq_hz / 1000.0:.1f}k"
    if freq_hz >= 100.0:
        return f"{freq_hz:.0f}"
    return f"{freq_hz:.1f}"


def _build_log_ticks(min_freq: float, max_freq: float, *, max_ticks: int = 10) -> list[float]:
    if min_freq <= 0:
        min_freq = 1.0
    min_decade = int(math.floor(math.log10(min_freq)))
    max_decade = int(math.ceil(math.log10(max_freq)))
    candidates: list[float] = []
    for decade in range(min_decade, max_decade + 1):
        base = 10**decade
        for factor in (1.0, 2.0, 5.0):
            tick = base * factor
            if min_freq <= tick <= max_freq:
                candidates.append(float(tick))
    ticks = sorted(set(candidates))
    if len(ticks) <= max_ticks:
        return ticks
    step = max(1, len(ticks) // max_ticks)
    reduced = ticks[::step]
    if ticks[-1] not in reduced:
        reduced.append(ticks[-1])
    return sorted(set(reduced))


def _build_linear_ticks(min_value: float, max_value: float, *, target_count: int = 6) -> list[float]:
    span = max(max_value - min_value, 1e-9)
    raw_step = span / max(target_count - 1, 1)
    magnitude = 10 ** math.floor(math.log10(raw_step))
    for multiplier in (1.0, 2.0, 2.5, 5.0, 10.0):
        step = multiplier * magnitude
        if span / step <= target_count + 1:
            break
    start = math.ceil(min_value / step) * step
    ticks: list[float] = []
    value = start
    while value <= max_value + (step * 0.5):
        if min_value - 1e-9 <= value <= max_value + 1e-9:
            ticks.append(float(value))
        value += step
    if min_value not in ticks:
        ticks.insert(0, float(min_value))
    if max_value not in ticks:
        ticks.append(float(max_value))
    return sorted(set(round(tick, 6) for tick in ticks))


def _build_angle_ticks(min_angle: float, max_angle: float) -> tuple[list[float], list[float]]:
    span = max(max_angle - min_angle, 1e-9)
    if span <= 40:
        major_step = 5.0
    elif span <= 90:
        major_step = 10.0
    elif span <= 180:
        major_step = 15.0
    else:
        major_step = 30.0
    minor_step = major_step / 2.0
    majors = _build_linear_ticks(min_angle, max_angle, target_count=max(4, int(span / major_step) + 1))
    minors = _build_linear_ticks(min_angle, max_angle, target_count=max(6, int(span / minor_step) + 1))
    return majors, minors


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
    return _draw_band_map_smooth(canvas, polar_rows, log_x=log_x)


def _get_bandmap_render_data(canvas: tk.Canvas, polar_rows: list[dict[str, float]]) -> BandMapRenderData:
    cache_key = (
        len(polar_rows),
        tuple(
            (
                round(float(row.get("freq_hz", 0.0)), 6),
                round(float(row.get("angle_deg", 0.0)), 6),
                round(float(row.get("spl_db", 0.0)), 6),
            )
            for row in polar_rows
        ),
    )
    cached_key = getattr(canvas, "_bandmap_cache_key", None)
    cached_data = getattr(canvas, "_bandmap_cache_data", None)
    if cached_key == cache_key and isinstance(cached_data, BandMapRenderData):
        return cached_data
    render_data = prepare_bandmap_render_data(
        polar_rows,
        options=BandMapDisplayOptions(
            dense_freq_points=320,
            dense_angle_points=181,
            sigma_angle=0.8,
            sigma_logfreq=0.45,
            enable_smoothing=True,
            vmin_db=-24.0,
            vmax_db=6.0,
        ),
    )
    setattr(canvas, "_bandmap_cache_key", cache_key)
    setattr(canvas, "_bandmap_cache_data", render_data)
    return render_data


def _build_klippel_colormap() -> Any:
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        "klippel_like",
        [
            "#0a2342",
            "#153e75",
            "#225ea8",
            "#1d91c0",
            "#41b6c4",
            "#7fcdbb",
            "#c7e9b4",
            "#ffffbf",
            "#fee08b",
            "#fdae61",
            "#f46d43",
            "#d73027",
        ],
        N=256,
    )


def _draw_band_map_with_matplotlib(
    canvas: tk.Canvas,
    *,
    data: BandMapData,
    raw_reference: BandMapData,
    mode: str,
    log_x: bool,
    vmin: float = -24.0,
    vmax: float = 6.0,
) -> str:
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import ticker
    from matplotlib import pyplot as plt

    width = max(canvas.winfo_width(), 520)
    height = max(canvas.winfo_height(), 360)
    figure_dpi = 110
    figure = plt.Figure(figsize=(width / figure_dpi, height / figure_dpi), dpi=figure_dpi, facecolor=INPUT_BG)
    axis = figure.add_subplot(111, facecolor=INPUT_BG)
    colormap = _build_klippel_colormap()

    on_axis_index = int(np.argmin(np.abs(data.angles_deg)))
    relative_db = data.spl_db - data.spl_db[on_axis_index, :][np.newaxis, :]
    freq_axis = np.asarray(data.freq_hz, dtype=float)
    angle_axis = np.asarray(data.angles_deg, dtype=float)

    if mode == "raw":
        image = axis.pcolormesh(
            freq_axis,
            angle_axis,
            relative_db,
            shading="nearest",
            cmap=colormap,
            vmin=vmin,
            vmax=vmax,
            antialiased=False,
            rasterized=True,
        )
    else:
        levels = np.linspace(vmin, vmax, 121, dtype=float)
        image = axis.contourf(
            freq_axis,
            angle_axis,
            relative_db,
            levels=levels,
            cmap=colormap,
            vmin=vmin,
            vmax=vmax,
            extend="both",
        )
        contour_levels = [-12.0, -6.0]
        contour = axis.contour(
            freq_axis,
            angle_axis,
            relative_db,
            levels=contour_levels,
            colors="#111111",
            linewidths=0.8,
            alpha=0.78,
        )
        if len(getattr(contour, "levels", [])) > 0:
            axis.clabel(contour, fmt={-12.0: "-12 dB", -6.0: "-6 dB"}, fontsize=7, inline=True)

    if log_x:
        axis.set_xscale("log")

    common_ticks = [500, 1000, 2000, 5000, 10000, 20000]
    min_freq = float(np.min(freq_axis))
    max_freq = float(np.max(freq_axis))
    x_ticks = [tick for tick in common_ticks if min_freq <= tick <= max_freq]
    if x_ticks:
        axis.set_xticks(x_ticks)
    axis.xaxis.set_major_formatter(
        ticker.FuncFormatter(
            lambda value, _pos: f"{value/1000:.0f}k" if value >= 1000.0 else f"{value:.0f}"
        )
    )
    axis.set_yticks(np.arange(math.ceil(float(np.min(angle_axis)) / 15.0) * 15.0, float(np.max(angle_axis)) + 0.1, 15.0))
    axis.tick_params(axis="both", colors=TEXT, labelsize=9)

    axis.grid(True, which="major", color="#3c4c63", alpha=0.34, linewidth=0.7)
    axis.grid(True, which="minor", color="#2a384d", alpha=0.16, linewidth=0.45)
    axis.set_xlabel(f"Frequency [Hz] ({'log' if log_x else 'linear'})", color=MUTED, fontsize=9)
    axis.set_ylabel("Angle [deg]", color=MUTED, fontsize=9)

    colorbar = figure.colorbar(image, ax=axis, pad=0.02, ticks=[-24, -18, -12, -6, 0, 6])
    colorbar.ax.tick_params(labelsize=8, colors=TEXT)
    colorbar.outline.set_edgecolor(BORDER)
    colorbar.set_label("Relative SPL [dB re: on-axis]", color=MUTED, fontsize=8)
    colorbar.ax.yaxis.label.set_color(MUTED)

    raw_nf = raw_reference.spl_db.shape[1]
    raw_na = raw_reference.spl_db.shape[0]
    caption = (
        f"頻段離軸圖 ({'Smooth Display' if mode != 'raw' else 'Raw'}) | "
        f"raw {raw_nf} freq × {raw_na} angles"
    )
    axis.set_title(
        f"Band Map ({'Smooth Display' if mode != 'raw' else 'Raw'}) | raw {raw_nf}x{raw_na}",
        color=TEXT,
        fontsize=10,
        pad=8,
    )
    figure.tight_layout()

    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=figure_dpi, facecolor=figure.get_facecolor())
    plt.close(figure)
    encoded = base64.b64encode(buffer.getvalue())
    image_tk = tk.PhotoImage(data=encoded)
    canvas.delete("all")
    canvas.create_image(width / 2, height / 2, image=image_tk, anchor="center")
    setattr(canvas, "_bandmap_photo", image_tk)
    return caption


def _draw_band_map_raw(canvas: tk.Canvas, polar_rows: list[dict[str, float]], *, log_x: bool = True) -> str:
    try:
        render_data = _get_bandmap_render_data(canvas, polar_rows)
    except Exception as exc:
        draw_placeholder(canvas, f"Raw band map 資料處理失敗：{exc}")
        return ""
    try:
        return _draw_band_map_with_matplotlib(
            canvas,
            data=render_data.raw,
            raw_reference=render_data.raw,
            mode="raw",
            log_x=log_x,
        )
    except Exception as exc:
        draw_placeholder(canvas, f"Raw band map 繪圖失敗：{exc}")
        return ""


def _draw_band_map_smooth(canvas: tk.Canvas, polar_rows: list[dict[str, float]], *, log_x: bool = True) -> str:
    try:
        render_data = _get_bandmap_render_data(canvas, polar_rows)
    except Exception as exc:
        draw_placeholder(canvas, f"Smooth band map 資料處理失敗：{exc}")
        return ""
    try:
        return _draw_band_map_with_matplotlib(
            canvas,
            data=render_data.display,
            raw_reference=render_data.raw,
            mode="smooth",
            log_x=log_x,
        )
    except Exception as exc:
        draw_placeholder(canvas, f"Smooth band map 繪圖失敗：{exc}")
        return ""


def draw_directivity_view(
    canvas: tk.Canvas,
    polar_rows: list[dict[str, float]],
    *,
    mode: str = "band_map",
    preferred_hz: float = 1000.0,
    log_x: bool = True,
) -> str:
    normalized_mode = str(mode).strip().lower().replace(" ", "_")
    if not polar_rows:
        draw_placeholder(canvas, "請執行 BEM 並載入 `polar.csv`，即可在此顯示指向性。")
        return ""
    if normalized_mode in {"single_freq_polar", "single_freq"}:
        return _draw_single_frequency_polar(canvas, polar_rows, preferred_hz=preferred_hz)
    if normalized_mode in {"band_map_raw", "raw"}:
        return _draw_band_map_raw(canvas, polar_rows, log_x=log_x)
    if normalized_mode in {"band_map", "band_map_smooth", "smooth_display", "smooth"}:
        return _draw_band_map_smooth(canvas, polar_rows, log_x=log_x)
    return _draw_band_map_smooth(canvas, polar_rows, log_x=log_x)
