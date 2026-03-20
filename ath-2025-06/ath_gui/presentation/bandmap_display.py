"""Display-only processing pipeline for BEM band-map rendering."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

try:
    from scipy.interpolate import RegularGridInterpolator
    from scipy.ndimage import gaussian_filter

    SCIPY_AVAILABLE = True
except Exception:
    RegularGridInterpolator = None  # type: ignore[assignment]
    gaussian_filter = None  # type: ignore[assignment]
    SCIPY_AVAILABLE = False


@dataclass(frozen=True)
class BandMapDisplayOptions:
    dense_freq_points: int = 320
    dense_angle_points: int = 181
    sigma_angle: float = 0.8
    sigma_logfreq: float = 0.45
    enable_smoothing: bool = True
    vmin_db: float = -24.0
    vmax_db: float = 6.0


@dataclass(frozen=True)
class BandMapData:
    freq_hz: np.ndarray
    angles_deg: np.ndarray
    spl_db: np.ndarray  # shape (na, nf)


@dataclass(frozen=True)
class BandMapRenderData:
    raw: BandMapData
    display: BandMapData
    used_interpolation: bool
    used_smoothing: bool
    notes: tuple[str, ...]


def _safe_db_fill(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    finite_mask = np.isfinite(array)
    if np.all(finite_mask):
        return array
    if np.any(finite_mask):
        replacement = float(np.nanmedian(array[finite_mask]))
    else:
        replacement = 0.0
    return np.where(finite_mask, array, replacement)


def _deduplicate_sorted_axis(axis_values: np.ndarray, matrix: np.ndarray, axis: int) -> tuple[np.ndarray, np.ndarray]:
    unique_values, inverse = np.unique(axis_values, return_inverse=True)
    if len(unique_values) == len(axis_values):
        return axis_values, matrix

    if axis == 0:
        reduced = np.zeros((len(unique_values), matrix.shape[1]), dtype=float)
        counts = np.zeros(len(unique_values), dtype=float)
        for old_index, new_index in enumerate(inverse):
            reduced[new_index, :] += matrix[old_index, :]
            counts[new_index] += 1.0
        reduced /= counts[:, np.newaxis]
        return unique_values, reduced

    reduced = np.zeros((matrix.shape[0], len(unique_values)), dtype=float)
    counts = np.zeros(len(unique_values), dtype=float)
    for old_index, new_index in enumerate(inverse):
        reduced[:, new_index] += matrix[:, old_index]
        counts[new_index] += 1.0
    reduced /= counts[np.newaxis, :]
    return unique_values, reduced


def normalize_bandmap_axes(freq_hz: np.ndarray, angles_deg: np.ndarray, spl_db: np.ndarray) -> BandMapData:
    """Normalize axis order, sanitize values, and return Z as (na, nf)."""
    freq = np.asarray(freq_hz, dtype=float).reshape(-1)
    angles = np.asarray(angles_deg, dtype=float).reshape(-1)
    z = np.asarray(spl_db, dtype=float)

    if z.ndim != 2:
        raise ValueError(f"spl_db must be a 2D array, got shape {z.shape}.")
    if z.shape == (len(angles), len(freq)):
        pass
    elif z.shape == (len(freq), len(angles)):
        z = z.T
    else:
        raise ValueError(
            f"spl_db shape {z.shape} does not match freq/angle lengths ({len(freq)}, {len(angles)})."
        )

    z = _safe_db_fill(z)
    freq = np.where(np.isfinite(freq), freq, np.nan)
    angles = np.where(np.isfinite(angles), angles, np.nan)
    finite_freq = np.isfinite(freq) & (freq > 0.0)
    finite_angles = np.isfinite(angles)
    if not np.any(finite_freq):
        raise ValueError("No valid positive frequency entries were found.")
    if not np.any(finite_angles):
        raise ValueError("No valid angle entries were found.")

    freq = freq[finite_freq]
    z = z[:, finite_freq]
    angles = angles[finite_angles]
    z = z[finite_angles, :]

    freq_order = np.argsort(freq)
    angle_order = np.argsort(angles)
    freq = freq[freq_order]
    angles = angles[angle_order]
    z = z[angle_order, :][:, freq_order]

    freq, z = _deduplicate_sorted_axis(freq, z, axis=1)
    angles, z = _deduplicate_sorted_axis(angles, z, axis=0)
    return BandMapData(freq_hz=freq, angles_deg=angles, spl_db=z)


def build_raw_bandmap_data(polar_rows: list[dict[str, float]]) -> BandMapData:
    """Build a dense rectangular raw matrix from polar CSV rows."""
    if not polar_rows:
        raise ValueError("No polar rows were supplied.")

    freq_values = sorted({float(row["freq_hz"]) for row in polar_rows if math.isfinite(float(row["freq_hz"]))})
    angle_values = sorted({float(row["angle_deg"]) for row in polar_rows if math.isfinite(float(row["angle_deg"]))})
    if len(freq_values) < 1 or len(angle_values) < 1:
        raise ValueError("Polar data does not contain valid frequency/angle values.")

    freq_index = {freq: index for index, freq in enumerate(freq_values)}
    angle_index = {angle: index for index, angle in enumerate(angle_values)}
    sums = np.zeros((len(angle_values), len(freq_values)), dtype=float)
    counts = np.zeros((len(angle_values), len(freq_values)), dtype=float)
    for row in polar_rows:
        try:
            freq = float(row["freq_hz"])
            angle = float(row["angle_deg"])
            value = float(row["spl_db"])
        except Exception:
            continue
        if not (math.isfinite(freq) and math.isfinite(angle) and math.isfinite(value)):
            continue
        fi = freq_index.get(freq)
        ai = angle_index.get(angle)
        if fi is None or ai is None:
            continue
        sums[ai, fi] += value
        counts[ai, fi] += 1.0

    valid_mask = counts > 0.0
    if not np.any(valid_mask):
        raise ValueError("No valid SPL entries were found in polar data.")
    filled = np.divide(sums, np.maximum(counts, 1.0), out=np.full_like(sums, np.nan), where=valid_mask)

    # Fill missing entries by per-frequency on-axis fallback first, then global median.
    on_axis_index = int(np.argmin(np.abs(np.asarray(angle_values, dtype=float))))
    freq_fallback = filled[on_axis_index, :]
    global_fallback = float(np.nanmedian(filled[np.isfinite(filled)]))
    for ai in range(filled.shape[0]):
        missing = ~np.isfinite(filled[ai, :])
        if np.any(missing):
            replacement = np.where(np.isfinite(freq_fallback), freq_fallback, global_fallback)
            filled[ai, missing] = replacement[missing]
    return normalize_bandmap_axes(
        np.asarray(freq_values, dtype=float),
        np.asarray(angle_values, dtype=float),
        filled,
    )


def make_log_frequency_grid(freq_hz: np.ndarray, dense_points: int) -> np.ndarray:
    minimum = float(np.min(freq_hz))
    maximum = float(np.max(freq_hz))
    if len(freq_hz) <= 1 or math.isclose(minimum, maximum):
        return np.asarray([minimum], dtype=float)
    return np.geomspace(minimum, maximum, max(int(dense_points), 2), dtype=float)


def _interpolate_numpy(
    angles_deg: np.ndarray,
    log_freq: np.ndarray,
    z: np.ndarray,
    target_angles_deg: np.ndarray,
    target_log_freq: np.ndarray,
) -> np.ndarray:
    temp = np.empty((len(target_angles_deg), z.shape[1]), dtype=float)
    for fi in range(z.shape[1]):
        temp[:, fi] = np.interp(target_angles_deg, angles_deg, z[:, fi])

    out = np.empty((len(target_angles_deg), len(target_log_freq)), dtype=float)
    for ai in range(temp.shape[0]):
        out[ai, :] = np.interp(target_log_freq, log_freq, temp[ai, :])
    return out


def interpolate_bandmap_display(
    raw: BandMapData,
    *,
    dense_freq_points: int,
    dense_angle_points: int,
) -> tuple[BandMapData, bool]:
    """Interpolate raw data on (angle, log10(freq)) display grid."""
    freq = raw.freq_hz
    angles = raw.angles_deg
    z = raw.spl_db
    if len(freq) < 2 or len(angles) < 2:
        return raw, False

    display_freq = make_log_frequency_grid(freq, dense_freq_points)
    display_angles = np.linspace(float(np.min(angles)), float(np.max(angles)), max(int(dense_angle_points), 2), dtype=float)
    log_freq = np.log10(freq)
    log_display = np.log10(display_freq)

    if SCIPY_AVAILABLE and RegularGridInterpolator is not None:
        interpolator = RegularGridInterpolator(
            (angles, log_freq),
            z,
            method="linear",
            bounds_error=False,
            fill_value=None,
        )
        grid_angles, grid_logf = np.meshgrid(display_angles, log_display, indexing="ij")
        points = np.column_stack((grid_angles.reshape(-1), grid_logf.reshape(-1)))
        display_z = interpolator(points).reshape(len(display_angles), len(display_freq))
    else:
        display_z = _interpolate_numpy(angles, log_freq, z, display_angles, log_display)

    display_z = _safe_db_fill(display_z)
    return BandMapData(freq_hz=display_freq, angles_deg=display_angles, spl_db=display_z), True


def _gaussian_kernel1d(sigma: float) -> np.ndarray:
    sigma = float(max(sigma, 1e-6))
    radius = int(max(1, round(3.0 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-(x * x) / (2.0 * sigma * sigma))
    kernel /= np.sum(kernel)
    return kernel


def _gaussian_smooth_numpy(z: np.ndarray, sigma_angle: float, sigma_logfreq: float) -> np.ndarray:
    out = np.asarray(z, dtype=float)
    for axis, sigma in ((0, sigma_angle), (1, sigma_logfreq)):
        if sigma <= 1e-6:
            continue
        kernel = _gaussian_kernel1d(sigma)
        pad = len(kernel) // 2
        if axis == 0:
            padded = np.pad(out, ((pad, pad), (0, 0)), mode="edge")
            smoothed = np.empty_like(out)
            for fi in range(out.shape[1]):
                smoothed[:, fi] = np.convolve(padded[:, fi], kernel, mode="valid")
        else:
            padded = np.pad(out, ((0, 0), (pad, pad)), mode="edge")
            smoothed = np.empty_like(out)
            for ai in range(out.shape[0]):
                smoothed[ai, :] = np.convolve(padded[ai, :], kernel, mode="valid")
        out = smoothed
    return out


def smooth_bandmap_display(
    display: BandMapData,
    *,
    sigma_angle: float,
    sigma_logfreq: float,
    enable_smoothing: bool,
) -> tuple[BandMapData, bool]:
    if not enable_smoothing or display.spl_db.size == 0:
        return display, False
    if display.spl_db.shape[0] < 2 or display.spl_db.shape[1] < 2:
        return display, False

    if SCIPY_AVAILABLE and gaussian_filter is not None:
        smoothed = gaussian_filter(
            display.spl_db,
            sigma=(max(float(sigma_angle), 0.0), max(float(sigma_logfreq), 0.0)),
            mode="nearest",
        )
    else:
        smoothed = _gaussian_smooth_numpy(display.spl_db, sigma_angle=sigma_angle, sigma_logfreq=sigma_logfreq)
    return BandMapData(freq_hz=display.freq_hz, angles_deg=display.angles_deg, spl_db=_safe_db_fill(smoothed)), True


def prepare_bandmap_render_data(
    polar_rows: list[dict[str, float]],
    *,
    options: BandMapDisplayOptions | None = None,
) -> BandMapRenderData:
    opts = options or BandMapDisplayOptions()
    notes: list[str] = []
    raw = build_raw_bandmap_data(polar_rows)
    display, used_interpolation = interpolate_bandmap_display(
        raw,
        dense_freq_points=opts.dense_freq_points,
        dense_angle_points=opts.dense_angle_points,
    )
    if used_interpolation:
        notes.append(
            f"display interpolation: angle/freq {raw.spl_db.shape[0]}x{raw.spl_db.shape[1]} -> "
            f"{display.spl_db.shape[0]}x{display.spl_db.shape[1]}"
        )
    else:
        notes.append("display interpolation skipped: raw grid too small")

    display_smoothed, used_smoothing = smooth_bandmap_display(
        display,
        sigma_angle=opts.sigma_angle,
        sigma_logfreq=opts.sigma_logfreq,
        enable_smoothing=opts.enable_smoothing,
    )
    if used_smoothing:
        notes.append(f"display smoothing enabled: sigma(angle={opts.sigma_angle}, logfreq={opts.sigma_logfreq})")
    else:
        notes.append("display smoothing skipped")
    return BandMapRenderData(
        raw=raw,
        display=display_smoothed,
        used_interpolation=used_interpolation,
        used_smoothing=used_smoothing,
        notes=tuple(notes),
    )
