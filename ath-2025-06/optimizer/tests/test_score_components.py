from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimizer.score_components import (
    angular_roughness_penalty,
    constant_directivity_error,
    di_smoothness_error,
    monotonicity_penalty,
    normalize_offaxis,
    spectral_roughness_penalty,
)


def test_normalize_offaxis_uses_explicit_zero_degree() -> None:
    angles_deg = np.asarray([-10.0, 0.0, 10.0])
    spl_db = np.asarray(
        [
            [95.0, 96.0],
            [100.0, 101.0],
            [97.0, 98.0],
        ]
    )
    normalized = normalize_offaxis(spl_db, angles_deg)
    expected = spl_db - spl_db[1, :][np.newaxis, :]
    np.testing.assert_allclose(normalized, expected)


def test_normalize_offaxis_uses_nearest_angle_when_zero_is_missing() -> None:
    angles_deg = np.asarray([-3.0, 7.0, 17.0])
    spl_db = np.asarray(
        [
            [100.0, 101.0],
            [98.0, 99.0],
            [93.0, 94.0],
        ]
    )
    normalized = normalize_offaxis(spl_db, angles_deg)
    expected = spl_db - spl_db[0, :][np.newaxis, :]
    np.testing.assert_allclose(normalized, expected)


def test_normalize_offaxis_uses_explicit_onaxis_curve() -> None:
    angles_deg = np.asarray([-10.0, 10.0])
    spl_db = np.asarray(
        [
            [95.0, 96.0],
            [94.0, 95.0],
        ]
    )
    normalized = normalize_offaxis(spl_db, angles_deg, onaxis_db=np.asarray([100.0, 101.0]))
    expected = spl_db - np.asarray([100.0, 101.0])[np.newaxis, :]
    np.testing.assert_allclose(normalized, expected)


def test_constant_directivity_error_prefers_constant_polar() -> None:
    freqs_hz = np.geomspace(1000.0, 16000.0, 16)
    angles_deg = np.linspace(-40.0, 40.0, 9)
    constant_norm = -(np.abs(angles_deg)[:, np.newaxis] / 20.0) * np.ones((1, freqs_hz.size))
    logf = np.log10(freqs_hz / freqs_hz[0])
    widening_norm = constant_norm * (1.0 + 2.0 * (logf**2)[np.newaxis, :])
    freq_mask = np.ones(freqs_hz.size, dtype=bool)

    constant_score = constant_directivity_error(constant_norm, freqs_hz, freq_mask)
    widening_score = constant_directivity_error(widening_norm, freqs_hz, freq_mask)

    assert constant_score < 1e-6
    assert widening_score > constant_score + 0.1


def test_monotonicity_penalty_detects_inversion() -> None:
    angles_deg = np.asarray([-30.0, -15.0, 0.0, 15.0, 30.0])
    freqs_hz = np.geomspace(1000.0, 8000.0, 8)
    freq_mask = np.ones(freqs_hz.size, dtype=bool)

    smooth = np.asarray(
        [
            [-6.0] * freqs_hz.size,
            [-3.0] * freqs_hz.size,
            [0.0] * freqs_hz.size,
            [-3.0] * freqs_hz.size,
            [-6.0] * freqs_hz.size,
        ]
    )
    inverted = smooth.copy()
    inverted[4, 3:6] = -1.0

    smooth_score = monotonicity_penalty(smooth, angles_deg, freq_mask=freq_mask)
    inverted_score = monotonicity_penalty(inverted, angles_deg, freq_mask=freq_mask)

    assert smooth_score < 1e-6
    assert inverted_score > 0.1


def test_angular_roughness_penalty_increases_with_sidelobe() -> None:
    freqs_hz = np.geomspace(1000.0, 10000.0, 12)
    angles_deg = np.linspace(-50.0, 50.0, 21)
    freq_mask = np.ones(freqs_hz.size, dtype=bool)
    smooth = -((np.abs(angles_deg)[:, np.newaxis] / 40.0) ** 1.6) * np.ones((1, freqs_hz.size))
    rough = smooth.copy()
    rough[15, 5:9] += 4.0

    smooth_score = angular_roughness_penalty(smooth, angles_deg, freq_mask=freq_mask)
    rough_score = angular_roughness_penalty(rough, angles_deg, freq_mask=freq_mask)

    assert rough_score > smooth_score


def test_spectral_roughness_penalty_increases_with_narrowband_ripple() -> None:
    freqs_hz = np.geomspace(800.0, 16000.0, 32)
    angles_deg = np.linspace(-20.0, 20.0, 5)
    base_curve = -((np.abs(angles_deg)[:, np.newaxis] / 15.0) ** 1.2) * (1.0 + 0.1 * np.log10(freqs_hz / 800.0))
    smooth = base_curve.copy()
    rough = base_curve.copy()
    rough[:, 14:18] += np.asarray([0.0, 2.5, -2.5, 0.0])
    freq_mask = np.ones(freqs_hz.size, dtype=bool)

    smooth_score = spectral_roughness_penalty(smooth, freqs_hz, freq_mask=freq_mask)
    rough_score = spectral_roughness_penalty(rough, freqs_hz, freq_mask=freq_mask)

    assert rough_score > smooth_score


def test_di_smoothness_error_tracks_shape_not_absolute_di_offset() -> None:
    freqs_hz = np.geomspace(1000.0, 16000.0, 24)
    freq_mask = np.ones(freqs_hz.size, dtype=bool)
    logf = np.log10(freqs_hz / freqs_hz[0])
    base_di = 7.0 + 3.5 * logf
    shifted_di = base_di + 5.0
    wiggly_di = base_di + 0.7 * np.sin(np.linspace(0.0, 5.0 * np.pi, freqs_hz.size))

    base_score = di_smoothness_error(base_di, freqs_hz, freq_mask)
    shifted_score = di_smoothness_error(shifted_di, freqs_hz, freq_mask)
    wiggly_score = di_smoothness_error(wiggly_di, freqs_hz, freq_mask)

    assert np.isclose(base_score, shifted_score)
    assert wiggly_score > shifted_score
