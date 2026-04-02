"""Pure scoring primitives for ATH/BEM Optuna objective evaluation."""

from __future__ import annotations

import logging
from typing import Iterable

import numpy as np

from .score_defaults import DEFAULT_STAGE_FACTORS
from .score_types import GeometryStatus, HomProxyWeights, ObjectiveConfig, ScoreBundle


LOGGER = logging.getLogger(__name__)
_FLOAT_EPS = np.finfo(float).eps


def _ensure_1d(values: np.ndarray | Iterable[float], *, name: str, positive_only: bool = False) -> np.ndarray:
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.ndim != 1:
        raise ValueError(f"{name} must be a 1D array.")
    if positive_only and np.any(np.isfinite(array) & (array <= 0.0)):
        raise ValueError(f"{name} must contain positive values.")
    return array


def _ensure_plane_matrix(
    spl_db: np.ndarray,
    angles_deg: np.ndarray,
    *,
    name: str = "spl_db",
) -> np.ndarray:
    matrix = np.asarray(spl_db, dtype=float)
    if matrix.ndim != 2:
        raise ValueError(f"{name} must be a 2D array, got shape {matrix.shape}.")
    if matrix.shape[0] == len(angles_deg):
        return matrix
    if matrix.shape[1] == len(angles_deg):
        return matrix.T
    raise ValueError(
        f"{name} shape {matrix.shape} does not match angle axis length {len(angles_deg)} in either orientation."
    )


def _sorted_plane(spl_db: np.ndarray, angles_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(angles_deg)
    return spl_db[order, :], angles_deg[order]


def _fill_curve_nans(curve: np.ndarray) -> np.ndarray:
    values = np.asarray(curve, dtype=float).reshape(-1)
    finite = np.isfinite(values)
    if np.all(finite):
        return values
    if not np.any(finite):
        return np.zeros_like(values)
    x = np.arange(values.size, dtype=float)
    filled = values.copy()
    filled[~finite] = np.interp(x[~finite], x[finite], values[finite])
    return filled


def _safe_mean(values: np.ndarray | list[float]) -> float:
    array = np.asarray(values, dtype=float).reshape(-1)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return 0.0
    return float(np.mean(finite))


def _safe_rms(values: np.ndarray) -> float:
    array = np.asarray(values, dtype=float)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(finite))))


def normalize_component_value(value: float, scale: float, *, minimum: float = 0.0, fallback: float = 0.0) -> float:
    """Normalize a raw error term by a configurable scale while preventing NaN propagation."""
    if not np.isfinite(value):
        return float(fallback)
    effective_scale = float(scale) if np.isfinite(scale) and scale > _FLOAT_EPS else 1.0
    return float(max(float(value), minimum) / effective_scale)


def select_freq_mask(freqs_hz: np.ndarray, freq_band_hz: tuple[float, float]) -> np.ndarray:
    """Return a boolean mask for the requested frequency band."""
    freqs = _ensure_1d(freqs_hz, name="freqs_hz", positive_only=True)
    low_hz, high_hz = float(freq_band_hz[0]), float(freq_band_hz[1])
    if low_hz > high_hz:
        raise ValueError(f"Frequency band must be ordered, got {freq_band_hz}.")
    mask = np.isfinite(freqs) & (freqs >= low_hz) & (freqs <= high_hz)
    return mask


def select_angle_mask(
    angles_deg: np.ndarray,
    angle_range_deg: tuple[float, float] | None = None,
    *,
    absolute: bool = True,
) -> np.ndarray:
    """Return a boolean mask for a requested angle window."""
    angles = _ensure_1d(angles_deg, name="angles_deg")
    values = np.abs(angles) if absolute else angles
    if angle_range_deg is None:
        return np.isfinite(values)
    low_deg, high_deg = float(angle_range_deg[0]), float(angle_range_deg[1])
    if low_deg > high_deg:
        raise ValueError(f"Angle range must be ordered, got {angle_range_deg}.")
    return np.isfinite(values) & (values >= low_deg) & (values <= high_deg)


def normalize_offaxis(
    spl_db: np.ndarray,
    angles_deg: np.ndarray,
    onaxis_db: np.ndarray | None = None,
) -> np.ndarray:
    """Normalize a polar slice to the nearest available on-axis curve.

    Parameters
    ----------
    spl_db:
        Polar SPL matrix with shape ``(A, F)`` or ``(F, A)``.
    angles_deg:
        Angle axis with shape ``(A,)``. The array does not need to be symmetric.
    onaxis_db:
        Optional explicit on-axis curve of shape ``(F,)``. When omitted, the
        angle sample nearest to 0 degrees is used.
    """

    angles = _ensure_1d(angles_deg, name="angles_deg")
    matrix = _ensure_plane_matrix(spl_db, angles, name="spl_db")
    if matrix.shape[0] == 0:
        return np.empty_like(matrix)

    if onaxis_db is None:
        onaxis_index = int(np.argmin(np.abs(angles)))
        reference = np.asarray(matrix[onaxis_index, :], dtype=float).reshape(-1)
    else:
        reference = np.asarray(onaxis_db, dtype=float).reshape(-1)
        if reference.shape != (matrix.shape[1],):
            raise ValueError(
                f"onaxis_db must have shape ({matrix.shape[1]},), got {reference.shape}."
            )
    return np.asarray(matrix - reference[np.newaxis, :], dtype=float)


def detrend_curve(
    curve_db: np.ndarray,
    freqs_hz: np.ndarray,
    *,
    kind: str = "linear_logf",
    moving_avg_points: int = 5,
) -> np.ndarray:
    """Return a detrended copy of a 1D curve for smoothness/ripple metrics."""
    curve = _fill_curve_nans(_ensure_1d(curve_db, name="curve_db"))
    freqs = _ensure_1d(freqs_hz, name="freqs_hz", positive_only=True)
    if curve.shape != freqs.shape:
        raise ValueError(f"curve_db shape {curve.shape} does not match freqs_hz shape {freqs.shape}.")
    if curve.size == 0:
        return curve.copy()
    if kind == "none":
        return curve.copy()
    if curve.size == 1:
        return curve - curve[0]

    if kind == "linear_logf":
        x = np.log10(np.maximum(freqs, _FLOAT_EPS))
        coeffs = np.polyfit(x, curve, deg=1)
        trend = np.polyval(coeffs, x)
        return curve - trend
    if kind == "moving_avg":
        window = int(max(1, moving_avg_points))
        if window % 2 == 0:
            window += 1
        if window > curve.size:
            window = curve.size if curve.size % 2 == 1 else max(curve.size - 1, 1)
        if window <= 1:
            return curve - np.mean(curve)
        kernel = np.ones(window, dtype=float) / float(window)
        pad = window // 2
        padded = np.pad(curve, (pad, pad), mode="edge")
        trend = np.convolve(padded, kernel, mode="valid")
        return curve - trend
    raise ValueError(f"Unsupported detrend kind: {kind}")


def coverage_error_from_target(
    norm_spl_db: np.ndarray,
    target_norm_spl_db: np.ndarray,
    freq_mask: np.ndarray,
    angle_mask: np.ndarray,
    *,
    p: float = 2.0,
) -> float:
    """Compute p-norm coverage error against a target normalized off-axis surface."""
    matrix = np.asarray(norm_spl_db, dtype=float)
    target = np.asarray(target_norm_spl_db, dtype=float)
    if matrix.shape != target.shape:
        raise ValueError(f"Target matrix shape {target.shape} does not match data shape {matrix.shape}.")
    if freq_mask.shape != (matrix.shape[1],):
        raise ValueError("freq_mask length does not match the frequency axis.")
    if angle_mask.shape != (matrix.shape[0],):
        raise ValueError("angle_mask length does not match the angle axis.")
    if not np.any(freq_mask) or not np.any(angle_mask):
        return 0.0
    diff = np.abs(matrix[angle_mask, :][:, freq_mask] - target[angle_mask, :][:, freq_mask])
    finite = diff[np.isfinite(diff)]
    if finite.size == 0:
        return 0.0
    return float(np.mean(np.power(finite, p)) ** (1.0 / p))


def beamwidth_tracking_error(
    bw_deg: np.ndarray,
    target_bw_deg: float,
    freq_mask: np.ndarray,
) -> float:
    """Compute beamwidth tracking RMSE against a scalar target beamwidth."""
    beamwidth = _ensure_1d(bw_deg, name="bw_deg")
    if beamwidth.shape != freq_mask.shape:
        raise ValueError("beamwidth length does not match freq_mask length.")
    if not np.any(freq_mask):
        return 0.0
    selected = beamwidth[freq_mask]
    finite = np.isfinite(selected)
    if not np.any(finite):
        return 0.0
    return _safe_rms(selected[finite] - float(target_bw_deg))


def coverage_error(
    *,
    norm_spl_db: np.ndarray | None,
    freq_mask: np.ndarray,
    angle_mask: np.ndarray | None = None,
    target_norm_spl_db: np.ndarray | None = None,
    bw_deg: np.ndarray | None = None,
    target_bw_deg: float | None = None,
    p: float = 2.0,
) -> float:
    """Compute the primary coverage objective over the full evaluation band.

    The scorer can operate either in target-matrix mode or in beamwidth-tracking
    mode. In both cases this term remains the main band-wide optimization target.
    """
    if norm_spl_db is not None and target_norm_spl_db is not None:
        matrix = np.asarray(norm_spl_db, dtype=float)
        effective_angle_mask = (
            np.asarray(angle_mask, dtype=bool).reshape(-1)
            if angle_mask is not None
            else np.ones(matrix.shape[0], dtype=bool)
        )
        return coverage_error_from_target(matrix, np.asarray(target_norm_spl_db, dtype=float), freq_mask, effective_angle_mask, p=p)
    if bw_deg is not None and target_bw_deg is not None:
        return beamwidth_tracking_error(np.asarray(bw_deg, dtype=float), target_bw_deg, freq_mask)
    raise ValueError("coverage_error requires either target curves or beamwidth inputs.")


def constant_directivity_error(
    norm_spl_db: np.ndarray,
    freqs_hz: np.ndarray,
    freq_mask: np.ndarray,
    *,
    angle_mask: np.ndarray | None = None,
    detrend_kind: str = "linear_logf",
) -> float:
    """Measure how frequency-invariant each off-axis curve remains within a band.

    This remains available as a small guardrail term, but it is intentionally no
    longer treated as the primary optimization direction.
    """
    freqs = _ensure_1d(freqs_hz, name="freqs_hz", positive_only=True)
    matrix = np.asarray(norm_spl_db, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != freqs.size:
        raise ValueError(f"norm_spl_db must have shape (A, {freqs.size}), got {matrix.shape}.")
    if freq_mask.shape != (freqs.size,):
        raise ValueError("freq_mask length does not match freqs_hz.")
    effective_angle_mask = (
        np.asarray(angle_mask, dtype=bool).reshape(-1)
        if angle_mask is not None
        else np.ones(matrix.shape[0], dtype=bool)
    )
    if effective_angle_mask.shape != (matrix.shape[0],):
        raise ValueError("angle_mask length does not match the angle axis.")
    if np.sum(freq_mask) < 2 or not np.any(effective_angle_mask):
        return 0.0

    selected_freqs = freqs[freq_mask]
    penalties: list[float] = []
    for curve in matrix[effective_angle_mask, :]:
        detrended = detrend_curve(curve[freq_mask], selected_freqs, kind=detrend_kind)
        penalties.append(float(np.std(detrended)))
    return _safe_mean(penalties)


def _side_sequences(angles_deg: np.ndarray) -> list[np.ndarray]:
    if angles_deg.size == 0:
        return []
    zero_index = int(np.argmin(np.abs(angles_deg)))
    positive = np.where(angles_deg > 0.0)[0]
    negative = np.where(angles_deg < 0.0)[0]
    positive = positive[np.argsort(np.abs(angles_deg[positive]))]
    negative = negative[np.argsort(np.abs(angles_deg[negative]))]
    sequences: list[np.ndarray] = []
    if positive.size:
        sequences.append(np.concatenate(([zero_index], positive)))
    if negative.size:
        sequences.append(np.concatenate(([zero_index], negative)))
    return [sequence for sequence in sequences if sequence.size >= 2]


def monotonicity_penalty(
    norm_spl_db: np.ndarray,
    angles_deg: np.ndarray,
    *,
    freq_mask: np.ndarray | None = None,
    angle_mask: np.ndarray | None = None,
    epsilon_db: float = 0.5,
    compare_mode: str = "adjacent",
) -> float:
    """Penalize off-axis inversion where a larger angle becomes too loud relative to a smaller angle."""
    angles = _ensure_1d(angles_deg, name="angles_deg")
    matrix = _ensure_plane_matrix(norm_spl_db, angles, name="norm_spl_db")
    matrix, angles = _sorted_plane(matrix, angles)
    effective_freq_mask = (
        np.asarray(freq_mask, dtype=bool).reshape(-1)
        if freq_mask is not None
        else np.ones(matrix.shape[1], dtype=bool)
    )
    effective_angle_mask = (
        np.asarray(angle_mask, dtype=bool).reshape(-1)
        if angle_mask is not None
        else np.ones(matrix.shape[0], dtype=bool)
    )
    if effective_freq_mask.shape != (matrix.shape[1],):
        raise ValueError("freq_mask length does not match the frequency axis.")
    if effective_angle_mask.shape != (matrix.shape[0],):
        raise ValueError("angle_mask length does not match the angle axis.")
    if not np.any(effective_freq_mask) or np.sum(effective_angle_mask) < 2:
        return 0.0

    filtered_angles = angles[effective_angle_mask]
    filtered_matrix = matrix[effective_angle_mask, :][:, effective_freq_mask]
    penalties: list[float] = []
    for sequence in _side_sequences(filtered_angles):
        curves = filtered_matrix[sequence, :]
        if compare_mode == "adjacent":
            violation = curves[1:, :] - curves[:-1, :] - float(epsilon_db)
        elif compare_mode == "cumulative":
            reference = np.maximum.accumulate(curves[:-1, :], axis=0)
            violation = curves[1:, :] - reference - float(epsilon_db)
        else:
            raise ValueError(f"Unsupported compare_mode: {compare_mode}")
        penalties.append(_safe_mean(np.maximum(0.0, violation)))
    return _safe_mean(penalties)


def angular_roughness_penalty(
    norm_spl_db: np.ndarray,
    angles_deg: np.ndarray,
    *,
    freq_mask: np.ndarray | None = None,
    angle_mask: np.ndarray | None = None,
) -> float:
    """Measure angular jaggedness by the RMS of a second derivative across angle."""
    angles = _ensure_1d(angles_deg, name="angles_deg")
    matrix = _ensure_plane_matrix(norm_spl_db, angles, name="norm_spl_db")
    matrix, angles = _sorted_plane(matrix, angles)
    effective_freq_mask = (
        np.asarray(freq_mask, dtype=bool).reshape(-1)
        if freq_mask is not None
        else np.ones(matrix.shape[1], dtype=bool)
    )
    effective_angle_mask = (
        np.asarray(angle_mask, dtype=bool).reshape(-1)
        if angle_mask is not None
        else np.ones(matrix.shape[0], dtype=bool)
    )
    if not np.any(effective_freq_mask) or np.sum(effective_angle_mask) < 3:
        return 0.0
    selected_angles = angles[effective_angle_mask]
    if np.unique(selected_angles).size < 3:
        return 0.0
    selected = np.asarray(matrix[effective_angle_mask, :][:, effective_freq_mask], dtype=float)
    step = np.median(np.diff(selected_angles))
    if not np.isfinite(step) or abs(step) <= _FLOAT_EPS:
        return 0.0
    selected = np.apply_along_axis(_fill_curve_nans, 0, selected)
    first = np.gradient(selected, selected_angles, axis=0, edge_order=1)
    second = np.gradient(first, selected_angles, axis=0, edge_order=1) * (step**2)
    return _safe_rms(second)


def resample_curve_to_equal_log_frequency(
    curve_db: np.ndarray,
    freqs_hz: np.ndarray,
    *,
    use_log_frequency: bool = True,
    num_points: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Resample a 1D curve onto an evenly spaced frequency axis or log-frequency axis."""
    curve = _fill_curve_nans(_ensure_1d(curve_db, name="curve_db"))
    freqs = _ensure_1d(freqs_hz, name="freqs_hz", positive_only=True)
    if curve.shape != freqs.shape:
        raise ValueError(f"curve_db shape {curve.shape} does not match freqs_hz shape {freqs.shape}.")
    if curve.size <= 1:
        return freqs.copy(), curve.copy()
    x = np.log10(freqs) if use_log_frequency else freqs
    points = int(num_points or len(freqs))
    points = max(points, len(freqs))
    target_x = np.linspace(float(np.min(x)), float(np.max(x)), points, dtype=float)
    target_curve = np.interp(target_x, x, curve)
    target_freqs = np.power(10.0, target_x) if use_log_frequency else target_x
    return target_freqs, target_curve


def spectral_roughness_penalty(
    norm_spl_db: np.ndarray,
    freqs_hz: np.ndarray,
    *,
    freq_mask: np.ndarray | None = None,
    angle_mask: np.ndarray | None = None,
    use_log_frequency: bool = True,
) -> float:
    """Measure frequency-domain roughness using a second derivative along frequency."""
    freqs = _ensure_1d(freqs_hz, name="freqs_hz", positive_only=True)
    matrix = np.asarray(norm_spl_db, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != freqs.size:
        raise ValueError(f"norm_spl_db must have shape (A, {freqs.size}), got {matrix.shape}.")
    effective_freq_mask = (
        np.asarray(freq_mask, dtype=bool).reshape(-1)
        if freq_mask is not None
        else np.ones(freqs.size, dtype=bool)
    )
    effective_angle_mask = (
        np.asarray(angle_mask, dtype=bool).reshape(-1)
        if angle_mask is not None
        else np.ones(matrix.shape[0], dtype=bool)
    )
    if np.sum(effective_freq_mask) < 3 or not np.any(effective_angle_mask):
        return 0.0

    selected_freqs = freqs[effective_freq_mask]
    penalties: list[float] = []
    for curve in matrix[effective_angle_mask, :]:
        resampled_freqs, resampled_curve = resample_curve_to_equal_log_frequency(
            curve[effective_freq_mask],
            selected_freqs,
            use_log_frequency=use_log_frequency,
        )
        if resampled_curve.size < 3:
            continue
        x = np.log10(resampled_freqs) if use_log_frequency else resampled_freqs
        step = np.median(np.diff(x))
        if not np.isfinite(step) or abs(step) <= _FLOAT_EPS:
            continue
        first = np.gradient(resampled_curve, x, edge_order=1)
        second = np.gradient(first, x, edge_order=1) * (step**2)
        penalties.append(_safe_rms(second))
    return _safe_mean(penalties)


def edge_kink_penalty(
    norm_spl_db: np.ndarray,
    angles_deg: np.ndarray,
    edge_angle_range_deg: tuple[float, float],
    *,
    freq_mask: np.ndarray | None = None,
) -> float:
    """Measure local angular roughness around the nominal coverage edge region."""
    edge_mask = select_angle_mask(angles_deg, edge_angle_range_deg, absolute=True)
    if not np.any(edge_mask):
        return 0.0
    return angular_roughness_penalty(
        norm_spl_db,
        angles_deg,
        freq_mask=freq_mask,
        angle_mask=edge_mask,
    )


def hom_proxy_error(
    mono_value: float,
    angular_value: float,
    spectral_value: float,
    edge_value: float,
    *,
    inner_weights: HomProxyWeights,
) -> float:
    """Combine HOM/diffraction proxy metrics into a single raw proxy error."""
    return (
        float(inner_weights.mono) * float(max(mono_value, 0.0))
        + float(inner_weights.angular) * float(max(angular_value, 0.0))
        + float(inner_weights.spectral) * float(max(spectral_value, 0.0))
        + float(inner_weights.edge) * float(max(edge_value, 0.0))
    )


def _curve_ripple_error(
    curve_db: np.ndarray,
    freqs_hz: np.ndarray,
    *,
    freq_mask: np.ndarray,
    detrend_kind: str,
) -> float:
    if np.sum(freq_mask) < 2:
        return 0.0
    selected_freqs = np.asarray(freqs_hz, dtype=float).reshape(-1)[freq_mask]
    selected_curve = np.asarray(curve_db, dtype=float).reshape(-1)[freq_mask]
    detrended = detrend_curve(selected_curve, selected_freqs, kind=detrend_kind)
    return _safe_rms(detrended)


def onaxis_ripple_error(
    curve_db: np.ndarray,
    freqs_hz: np.ndarray,
    freq_mask: np.ndarray,
    *,
    detrend_kind: str = "linear_logf",
) -> float:
    """Measure on-axis ripple after detrending the global spectral tilt."""
    return _curve_ripple_error(curve_db, freqs_hz, freq_mask=freq_mask, detrend_kind=detrend_kind)


def listening_window_smoothness_error(
    curve_db: np.ndarray,
    freqs_hz: np.ndarray,
    freq_mask: np.ndarray,
    *,
    detrend_kind: str = "linear_logf",
) -> float:
    """Measure listening-window smoothness after detrending."""
    return _curve_ripple_error(curve_db, freqs_hz, freq_mask=freq_mask, detrend_kind=detrend_kind)


def sound_power_smoothness_error(
    curve_db: np.ndarray,
    freqs_hz: np.ndarray,
    freq_mask: np.ndarray,
    *,
    detrend_kind: str = "linear_logf",
) -> float:
    """Measure sound-power curve smoothness after detrending."""
    return _curve_ripple_error(curve_db, freqs_hz, freq_mask=freq_mask, detrend_kind=detrend_kind)


def room_response_error(
    onaxis_value: float,
    listening_window_value: float | None,
    sound_power_value: float | None,
) -> float:
    """Combine room-facing smoothness terms into a single raw score."""
    values = [float(onaxis_value)]
    if listening_window_value is not None and np.isfinite(listening_window_value):
        values.append(float(listening_window_value))
    if sound_power_value is not None and np.isfinite(sound_power_value):
        values.append(float(sound_power_value))
    return _safe_mean(values)


def _second_difference_rms_curve(
    curve_db: np.ndarray | None,
    freqs_hz: np.ndarray,
    *,
    freq_mask: np.ndarray,
    use_log_frequency: bool = True,
) -> float:
    if curve_db is None:
        return 0.0
    curve = np.asarray(curve_db, dtype=float).reshape(-1)
    freqs = _ensure_1d(freqs_hz, name="freqs_hz", positive_only=True)
    if curve.shape != freqs.shape:
        raise ValueError(f"curve shape {curve.shape} does not match freqs shape {freqs.shape}.")
    if np.sum(freq_mask) < 3:
        return 0.0
    resampled_freqs, resampled_curve = resample_curve_to_equal_log_frequency(
        curve[freq_mask],
        freqs[freq_mask],
        use_log_frequency=use_log_frequency,
    )
    if resampled_curve.size < 3:
        return 0.0
    x = np.log10(resampled_freqs) if use_log_frequency else resampled_freqs
    step = np.median(np.diff(x))
    if not np.isfinite(step) or abs(step) <= _FLOAT_EPS:
        return 0.0
    first = np.gradient(resampled_curve, x, edge_order=1)
    second = np.gradient(first, x, edge_order=1) * (step**2)
    return _safe_rms(second)


def di_smoothness_error(
    di_db: np.ndarray | None,
    freqs_hz: np.ndarray,
    freq_mask: np.ndarray,
    *,
    beamwidth_deg: np.ndarray | None = None,
    beamwidth_smoothness_eta: float = 0.35,
) -> float:
    """Measure DI smoothness and optionally beamwidth smoothness in log-frequency.

    This is a smoothness helper, not an absolute DI-target fitting term. It is
    intended to penalize jittery DI / beamwidth behavior without forcing a rigid
    high-frequency constant-directivity template.
    """
    di_term = _second_difference_rms_curve(di_db, freqs_hz, freq_mask=freq_mask, use_log_frequency=True)
    bw_term = _second_difference_rms_curve(
        beamwidth_deg,
        freqs_hz,
        freq_mask=freq_mask,
        use_log_frequency=True,
    )
    return float(di_term + float(beamwidth_smoothness_eta) * bw_term)


def load_proxy_error(
    metrics: dict[str, object] | None,
    freqs_hz: np.ndarray,
    freq_mask: np.ndarray,
) -> float:
    """Estimate acoustic loading quality from optional throat/load proxies when available."""
    if not metrics:
        return 0.0
    penalties: list[float] = []
    if "throat_reflection" in metrics and metrics["throat_reflection"] is not None:
        reflection = np.asarray(metrics["throat_reflection"])
        if reflection.ndim == 0:
            penalties.append(float(abs(reflection.item())))
        else:
            magnitude = np.abs(reflection).reshape(-1)
            if magnitude.shape == freq_mask.shape:
                magnitude = magnitude[freq_mask]
            penalties.append(_safe_mean(magnitude))
    if "radiation_efficiency" in metrics and metrics["radiation_efficiency"] is not None:
        efficiency = np.asarray(metrics["radiation_efficiency"], dtype=float).reshape(-1)
        if efficiency.shape == freq_mask.shape:
            efficiency = efficiency[freq_mask]
        penalties.append(_safe_mean(np.maximum(0.0, 1.0 - efficiency)))
    return _safe_mean(penalties)


def geometry_penalty(geom: GeometryStatus, failure_score: float) -> float:
    """Return non-catastrophic geometry/mesh penalties."""
    penalty = 0.0
    if geom.self_intersection:
        penalty += float(failure_score)
    if not geom.mesh_quality_ok:
        penalty += 0.5 * float(failure_score)
    return penalty


def catastrophic_penalty(geom: GeometryStatus, catastrophic_score: float) -> float:
    """Return the catastrophic penalty for solver/mesh/geometry failures."""
    if (not geom.solver_ok) or (not geom.mesh_ok) or (not geom.geometry_ok):
        return float(catastrophic_score)
    return 0.0


def aggregate_score(
    *,
    components: dict[str, float],
    config: ObjectiveConfig,
    details: dict[str, float] | None = None,
    flags: dict[str, bool | int | float] | None = None,
    warnings: list[str] | tuple[str, ...] | None = None,
) -> ScoreBundle:
    """Aggregate normalized component scores into the final scalar objective."""
    stage_factors = DEFAULT_STAGE_FACTORS.get(config.stage)
    if stage_factors is None:
        raise ValueError(f"Unsupported stage: {config.stage}")

    safe_components = {
        "hard": float(components.get("hard", 0.0) if np.isfinite(components.get("hard", 0.0)) else 0.0),
        "coverage": float(
            components.get("coverage", 0.0) if np.isfinite(components.get("coverage", 0.0)) else 0.0
        ),
        "cd": float(components.get("cd", 0.0) if np.isfinite(components.get("cd", 0.0)) else 0.0),
        "hom": float(components.get("hom", 0.0) if np.isfinite(components.get("hom", 0.0)) else 0.0),
        "room": float(components.get("room", 0.0) if np.isfinite(components.get("room", 0.0)) else 0.0),
        "di": float(components.get("di", 0.0) if np.isfinite(components.get("di", 0.0)) else 0.0),
        "load": float(components.get("load", 0.0) if np.isfinite(components.get("load", 0.0)) else 0.0),
        "geom": float(components.get("geom", 0.0) if np.isfinite(components.get("geom", 0.0)) else 0.0),
    }

    contributions = {
        "hard": config.weights.w_hard * stage_factors["hard"] * safe_components["hard"],
        "coverage": config.weights.w_cov * stage_factors["coverage"] * safe_components["coverage"],
        "cd": config.weights.w_cd * stage_factors["cd"] * safe_components["cd"],
        "hom": config.weights.w_hom * stage_factors["hom"] * safe_components["hom"],
        "room": config.weights.w_room * stage_factors["room"] * safe_components["room"],
        "di": config.weights.w_di * stage_factors["di"] * safe_components["di"],
        "load": config.weights.w_load * stage_factors["load"] * safe_components["load"],
        "geom": config.weights.w_geom * stage_factors["geom"] * safe_components["geom"],
    }
    total = float(sum(contributions.values()))
    merged_details = dict(details or {})
    merged_details.update({f"contribution.{name}": float(value) for name, value in contributions.items()})
    merged_details.update({f"stage_factor.{name}": float(value) for name, value in stage_factors.items()})

    merged_flags = dict(flags or {})
    merged_flags.setdefault("catastrophic", bool(safe_components["hard"] >= config.catastrophic_score))
    merged_flags.setdefault("stage_is_coarse", config.stage == "coarse")
    merged_flags.setdefault("stage_is_refine", config.stage == "refine")
    merged_flags.setdefault("stage_is_final", config.stage == "final")

    return ScoreBundle(
        total=total,
        hard_penalty=safe_components["hard"],
        coverage_error=safe_components["coverage"],
        cd_error=safe_components["cd"],
        hom_error=safe_components["hom"],
        room_error=safe_components["room"],
        di_error=safe_components["di"],
        load_error=safe_components["load"],
        geom_error=safe_components["geom"],
        details=merged_details,
        flags=merged_flags,
        warnings=tuple(warnings or ()),
    )
