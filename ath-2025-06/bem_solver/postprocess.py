"""Frequency grids, observation points, and result post-processing helpers."""

from __future__ import annotations

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
    figure, axis = plt.subplots(figsize=(10, 6))
    image = axis.pcolormesh(
        frequencies_hz,
        angles_deg,
        spl_relative_db.T,
        shading="auto",
        cmap=klippel_like,
        vmin=-24.0,
        vmax=6.0,
    )
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

    axis.set_title("ATH BEMPP Off-Axis Map (Klippel-like)")
    axis.set_xlabel("Frequency [Hz]")
    axis.set_ylabel("Angle [deg] (0 = +Z axis)")
    axis.set_xscale("log")
    axis.grid(True, alpha=0.25)
    axis.set_ylim(float(np.min(angles_deg)), float(np.max(angles_deg)))
    figure.colorbar(image, ax=axis, label="Relative SPL [dB re: on-axis]")
    figure.tight_layout()
    figure.savefig(output_path, dpi=140)
    plt.close(figure)
    return output_path
