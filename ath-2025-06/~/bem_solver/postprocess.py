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
    theta_rad = np.linspace(-np.pi, np.pi, job.theta_count, endpoint=True, dtype=float)
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
    from matplotlib import pyplot as plt

    output_path = job_dir / "polar.png"
    figure, axis = plt.subplots(figsize=(10, 6))
    image = axis.pcolormesh(
        frequencies_hz,
        angles_deg,
        spl_db.T,
        shading="auto",
        cmap="viridis",
    )
    axis.set_title("ATH BEMPP Directivity")
    axis.set_xlabel("Frequency [Hz]")
    axis.set_ylabel("Angle [deg]")
    axis.set_xscale("log")
    axis.grid(True, alpha=0.25)
    figure.colorbar(image, ax=axis, label="SPL [dB]")
    figure.tight_layout()
    figure.savefig(output_path, dpi=140)
    plt.close(figure)
    return output_path
