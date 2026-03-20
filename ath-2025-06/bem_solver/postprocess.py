"""Frequency grids, observation points, and result post-processing helpers."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from job_model import BemJob


def build_frequency_axis(job: BemJob) -> np.ndarray:
    if job.num_freq == 1:
        return np.asarray([job.f1], dtype=float)
    return np.geomspace(job.f1, job.f2, job.num_freq, dtype=float)


def build_observation_points(job: BemJob) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if job.angle_range_mode == "half_circle":
        theta_start = -0.5 * np.pi
        theta_end = 0.5 * np.pi
    elif job.angle_range_mode == "quarter_circle":
        theta_start = -0.25 * np.pi
        theta_end = 0.25 * np.pi
    else:
        theta_start = -np.pi
        theta_end = np.pi

    theta_rad = np.linspace(theta_start, theta_end, job.theta_count, endpoint=True, dtype=float)
    if job.plane == "YZ":
        points = job.mic_distance * np.asarray(
            [np.zeros_like(theta_rad), np.sin(theta_rad), np.cos(theta_rad)],
            dtype=float,
        )
    else:
        points = job.mic_distance * np.asarray(
            [np.sin(theta_rad), np.zeros_like(theta_rad), np.cos(theta_rad)],
            dtype=float,
        )
    return theta_rad, np.degrees(theta_rad), points


def pressure_to_spl(pressure: np.ndarray, reference_pressure: float) -> np.ndarray:
    magnitude = np.maximum(np.abs(pressure), np.finfo(float).tiny)
    return 20.0 * np.log10(magnitude / reference_pressure)


def export_polar_png(job_dir: Path, frequencies_hz: np.ndarray, angles_deg: np.ndarray, spl_db: np.ndarray) -> Path:
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib import pyplot as plt
    from matplotlib import ticker

    if spl_db.size == 0:
        raise ValueError("Cannot export polar PNG because SPL matrix is empty.")

    # Klippel-like readability: visualize off-axis loss relative to on-axis.
    on_axis_index = int(np.argmin(np.abs(angles_deg)))
    on_axis_curve = spl_db[:, on_axis_index][:, np.newaxis]
    spl_relative_db = spl_db - on_axis_curve

    klippel_like = LinearSegmentedColormap.from_list(
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

    output_path = job_dir / "polar.png"
    figure, axis = plt.subplots(figsize=(12.5, 7.5), dpi=150, constrained_layout=True)
    image = axis.pcolormesh(
        frequencies_hz,
        angles_deg,
        spl_relative_db.T,
        shading="nearest",
        cmap=klippel_like,
        vmin=-24.0,
        vmax=6.0,
        antialiased=False,
        rasterized=True,
    )
    if len(frequencies_hz) >= 2 and len(angles_deg) >= 2:
        contour_levels = [-18.0, -12.0, -9.0, -6.0, -3.0, 0.0, 3.0]
        contour = axis.contour(
            frequencies_hz,
            angles_deg,
            spl_relative_db.T,
            levels=contour_levels,
            colors="black",
            linewidths=0.55,
            alpha=0.45,
        )
        axis.clabel(contour, fmt="%ddB", fontsize=7, inline=True)

    axis.set_title(
        f"ATH BEMPP Off-Axis Map (Klippel-like) | {len(frequencies_hz)} freq x {len(angles_deg)} angles",
        fontsize=12,
    )
    axis.set_xlabel("Frequency [Hz]")
    axis.set_ylabel("Angle [deg] (0 = +Z axis)")
    axis.set_xscale("log")
    freq_min = float(np.min(frequencies_hz))
    freq_max = float(np.max(frequencies_hz))
    if math.isclose(freq_min, freq_max):
        freq_min = max(freq_min * 0.95, 1.0)
        freq_max = max(freq_max * 1.05, freq_min + 1.0)
    axis.set_xlim(freq_min, freq_max)
    axis.set_ylim(float(np.min(angles_deg)), float(np.max(angles_deg)))

    axis.xaxis.set_major_locator(ticker.LogLocator(base=10.0, subs=(1.0, 2.0, 5.0)))
    axis.xaxis.set_minor_locator(ticker.LogLocator(base=10.0, subs=np.arange(1.0, 10.0) * 0.1))
    axis.xaxis.set_major_formatter(ticker.EngFormatter(unit="Hz", sep=" "))
    angle_span = float(np.max(angles_deg) - np.min(angles_deg))
    if angle_span <= 90.0:
        y_major_step = 10.0
    elif angle_span <= 180.0:
        y_major_step = 15.0
    else:
        y_major_step = 30.0
    axis.yaxis.set_major_locator(ticker.MultipleLocator(y_major_step))
    axis.yaxis.set_minor_locator(ticker.MultipleLocator(max(y_major_step / 2.0, 1.0)))
    axis.tick_params(axis="both", which="major", labelsize=10)
    axis.tick_params(axis="both", which="minor", labelsize=8)
    axis.grid(True, which="major", alpha=0.30, linewidth=0.8)
    axis.grid(True, which="minor", alpha=0.16, linewidth=0.5)

    colorbar = figure.colorbar(
        image,
        ax=axis,
        label="Relative SPL [dB re: on-axis]",
        ticks=[-24, -18, -12, -6, 0, 6],
    )
    colorbar.ax.tick_params(labelsize=9)
    figure.savefig(output_path, dpi=280, bbox_inches="tight")
    plt.close(figure)
    return output_path
