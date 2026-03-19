"""Result writers for ATH BEM solver outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_mesh_info(job_dir: Path, mesh_info: dict[str, object]) -> Path:
    path = job_dir / "mesh_info.json"
    _write_json(path, mesh_info)
    return path


def write_summary(job_dir: Path, summary: dict[str, object]) -> Path:
    path = job_dir / "summary.json"
    _write_json(path, summary)
    return path


def write_polar_csv(job_dir: Path, frequencies_hz: np.ndarray, angles_deg: np.ndarray, spl_db: np.ndarray) -> Path:
    path = job_dir / "polar.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["freq_hz", "angle_deg", "spl_db"])
        for freq_index, freq_hz in enumerate(frequencies_hz):
            for angle_index, angle_deg in enumerate(angles_deg):
                writer.writerow(
                    [
                        f"{float(freq_hz):.12g}",
                        f"{float(angle_deg):.12g}",
                        f"{float(spl_db[freq_index, angle_index]):.12g}",
                    ]
                )
    return path


def write_solution_npz(
    job_dir: Path,
    frequencies_hz: np.ndarray,
    angles_deg: np.ndarray,
    pressure_complex: np.ndarray,
    spl_db: np.ndarray,
) -> Path:
    path = job_dir / "solution.npz"
    np.savez_compressed(
        path,
        frequencies_hz=np.asarray(frequencies_hz, dtype=float),
        angles_deg=np.asarray(angles_deg, dtype=float),
        pressure_complex=np.asarray(pressure_complex, dtype=np.complex128),
        spl_db=np.asarray(spl_db, dtype=float),
    )
    return path
