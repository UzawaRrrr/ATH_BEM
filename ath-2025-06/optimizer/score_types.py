"""Core data models for the Optuna scoring layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np


StageName = Literal["coarse", "refine", "final"]
DetrendKind = Literal["linear_logf", "moving_avg", "none"]
MonotonicityMode = Literal["adjacent", "cumulative"]


def _as_1d_float_array(
    values: np.ndarray | list[float] | tuple[float, ...] | None,
    *,
    name: str,
    allow_empty: bool = False,
    positive_only: bool = False,
) -> np.ndarray:
    if values is None:
        if allow_empty:
            return np.empty(0, dtype=float)
        raise ValueError(f"{name} is required.")
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size == 0 and not allow_empty:
        raise ValueError(f"{name} must not be empty.")
    if positive_only and np.any(np.isfinite(array) & (array <= 0.0)):
        raise ValueError(f"{name} must contain positive values.")
    return array


def _as_optional_curve(
    values: np.ndarray | list[float] | tuple[float, ...] | None,
    *,
    expected_len: int,
    name: str,
) -> np.ndarray | None:
    if values is None:
        return None
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.shape != (expected_len,):
        raise ValueError(f"{name} must have shape ({expected_len},), got {array.shape}.")
    return array


def _as_plane_matrix(
    values: np.ndarray | list[list[float]] | None,
    *,
    angles_len: int,
    freqs_len: int,
    name: str,
) -> np.ndarray:
    if values is None:
        if angles_len == 0:
            return np.empty((0, freqs_len), dtype=float)
        raise ValueError(f"{name} is required when {name.replace('spl_', 'angles_')} is present.")
    array = np.asarray(values, dtype=float)
    if angles_len == 0:
        if array.size != 0:
            raise ValueError(f"{name} must be empty when the corresponding angle axis is empty.")
        return np.empty((0, freqs_len), dtype=float)
    if array.ndim != 2:
        raise ValueError(f"{name} must be a 2D array, got shape {array.shape}.")
    if array.shape == (angles_len, freqs_len):
        return array
    if array.shape == (freqs_len, angles_len):
        return array.T
    raise ValueError(
        f"{name} must have shape ({angles_len}, {freqs_len}) or ({freqs_len}, {angles_len}), got {array.shape}."
    )


def _nearest_zero_curve(spl_db: np.ndarray, angles_deg: np.ndarray) -> np.ndarray | None:
    if spl_db.size == 0 or angles_deg.size == 0:
        return None
    index = int(np.argmin(np.abs(angles_deg)))
    return np.asarray(spl_db[index, :], dtype=float).reshape(-1)


@dataclass(frozen=True)
class PolarData:
    """Parsed polar-domain data consumed by the headless scorer."""

    freqs_hz: np.ndarray
    angles_deg_h: np.ndarray
    angles_deg_v: np.ndarray
    spl_h_db: np.ndarray
    spl_v_db: np.ndarray
    onaxis_db: np.ndarray | None = None
    di_db: np.ndarray | None = None
    sound_power_db: np.ndarray | None = None
    listening_window_db: np.ndarray | None = None
    beamwidth_6_h_deg: np.ndarray | None = None
    beamwidth_6_v_deg: np.ndarray | None = None
    beamwidth_12_h_deg: np.ndarray | None = None
    beamwidth_12_v_deg: np.ndarray | None = None
    extras: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        freqs_hz = _as_1d_float_array(self.freqs_hz, name="freqs_hz", positive_only=True)
        angles_deg_h = _as_1d_float_array(self.angles_deg_h, name="angles_deg_h", allow_empty=True)
        angles_deg_v = _as_1d_float_array(self.angles_deg_v, name="angles_deg_v", allow_empty=True)

        spl_h_db = _as_plane_matrix(
            self.spl_h_db,
            angles_len=len(angles_deg_h),
            freqs_len=len(freqs_hz),
            name="spl_h_db",
        )
        spl_v_db = _as_plane_matrix(
            self.spl_v_db,
            angles_len=len(angles_deg_v),
            freqs_len=len(freqs_hz),
            name="spl_v_db",
        )

        onaxis_db = _as_optional_curve(self.onaxis_db, expected_len=len(freqs_hz), name="onaxis_db")
        if onaxis_db is None:
            onaxis_db = _nearest_zero_curve(spl_h_db, angles_deg_h)
        if onaxis_db is None:
            onaxis_db = _nearest_zero_curve(spl_v_db, angles_deg_v)

        di_db = _as_optional_curve(self.di_db, expected_len=len(freqs_hz), name="di_db")
        sound_power_db = _as_optional_curve(self.sound_power_db, expected_len=len(freqs_hz), name="sound_power_db")
        listening_window_db = _as_optional_curve(
            self.listening_window_db,
            expected_len=len(freqs_hz),
            name="listening_window_db",
        )
        beamwidth_6_h_deg = _as_optional_curve(
            self.beamwidth_6_h_deg,
            expected_len=len(freqs_hz),
            name="beamwidth_6_h_deg",
        )
        beamwidth_6_v_deg = _as_optional_curve(
            self.beamwidth_6_v_deg,
            expected_len=len(freqs_hz),
            name="beamwidth_6_v_deg",
        )
        beamwidth_12_h_deg = _as_optional_curve(
            self.beamwidth_12_h_deg,
            expected_len=len(freqs_hz),
            name="beamwidth_12_h_deg",
        )
        beamwidth_12_v_deg = _as_optional_curve(
            self.beamwidth_12_v_deg,
            expected_len=len(freqs_hz),
            name="beamwidth_12_v_deg",
        )

        if onaxis_db is None and spl_h_db.size == 0 and spl_v_db.size == 0:
            raise ValueError("PolarData must include at least one polar plane or an explicit on-axis curve.")

        object.__setattr__(self, "freqs_hz", freqs_hz)
        object.__setattr__(self, "angles_deg_h", angles_deg_h)
        object.__setattr__(self, "angles_deg_v", angles_deg_v)
        object.__setattr__(self, "spl_h_db", spl_h_db)
        object.__setattr__(self, "spl_v_db", spl_v_db)
        object.__setattr__(self, "onaxis_db", onaxis_db)
        object.__setattr__(self, "di_db", di_db)
        object.__setattr__(self, "sound_power_db", sound_power_db)
        object.__setattr__(self, "listening_window_db", listening_window_db)
        object.__setattr__(self, "beamwidth_6_h_deg", beamwidth_6_h_deg)
        object.__setattr__(self, "beamwidth_6_v_deg", beamwidth_6_v_deg)
        object.__setattr__(self, "beamwidth_12_h_deg", beamwidth_12_h_deg)
        object.__setattr__(self, "beamwidth_12_v_deg", beamwidth_12_v_deg)
        object.__setattr__(self, "extras", dict(self.extras))

    @property
    def has_horizontal(self) -> bool:
        """Return whether the horizontal polar plane is available."""
        return bool(self.angles_deg_h.size and self.spl_h_db.size)

    @property
    def has_vertical(self) -> bool:
        """Return whether the vertical polar plane is available."""
        return bool(self.angles_deg_v.size and self.spl_v_db.size)


@dataclass(frozen=True)
class GeometryStatus:
    """Discrete geometry/mesh/solver status flags used by the scorer."""

    mesh_ok: bool
    solver_ok: bool
    geometry_ok: bool
    self_intersection: bool = False
    mesh_quality_ok: bool = True
    notes: list[str] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "notes", list(self.notes or []))


@dataclass(frozen=True)
class ScoreWeights:
    """Outer weights used by the final scalar objective."""

    w_cov: float
    w_cd: float
    w_hom: float
    w_room: float
    w_di: float
    w_pref: float
    w_load: float
    w_geom: float
    w_hard: float


@dataclass(frozen=True)
class HomProxyWeights:
    """Inner weights for the HOM/diffraction proxy composite."""

    mono: float
    angular: float
    spectral: float
    edge: float


@dataclass(frozen=True)
class ObjectiveConfig:
    """Configuration bundle for the headless scalar objective."""

    freq_band_cov_hz: tuple[float, float]
    freq_band_room_hz: tuple[float, float]
    freq_band_load_hz: tuple[float, float]
    target_bw_h_deg: float | None
    target_bw_v_deg: float | None
    edge_angle_range_h_deg: tuple[float, float]
    edge_angle_range_v_deg: tuple[float, float]
    monotonicity_epsilon_db: float
    roughness_use_log_frequency: bool
    detrend_kind: DetrendKind
    weights: ScoreWeights
    stage: StageName
    failure_score: float
    catastrophic_score: float
    hom_weights: HomProxyWeights
    component_normalizers: dict[str, float] = field(default_factory=dict)
    target_norm_spl_h_db: np.ndarray | None = None
    target_norm_spl_v_db: np.ndarray | None = None
    listening_window_angles_deg: tuple[float, ...] = (-10.0, 0.0, 10.0)
    monotonicity_mode: MonotonicityMode = "adjacent"
    beamwidth_smoothness_eta: float = 0.35

    def __post_init__(self) -> None:
        if self.freq_band_cov_hz[0] > self.freq_band_cov_hz[1]:
            raise ValueError("freq_band_cov_hz must be ordered as (low, high).")
        if self.freq_band_room_hz[0] > self.freq_band_room_hz[1]:
            raise ValueError("freq_band_room_hz must be ordered as (low, high).")
        if self.freq_band_load_hz[0] > self.freq_band_load_hz[1]:
            raise ValueError("freq_band_load_hz must be ordered as (low, high).")
        if self.failure_score < 0.0 or self.catastrophic_score < 0.0:
            raise ValueError("failure_score and catastrophic_score must be non-negative.")
        if self.target_norm_spl_h_db is not None:
            object.__setattr__(self, "target_norm_spl_h_db", np.asarray(self.target_norm_spl_h_db, dtype=float))
        if self.target_norm_spl_v_db is not None:
            object.__setattr__(self, "target_norm_spl_v_db", np.asarray(self.target_norm_spl_v_db, dtype=float))
        object.__setattr__(self, "component_normalizers", dict(self.component_normalizers))


@dataclass(frozen=True)
class ScoreBundle:
    """Final scalar score plus decomposed component scores and flags."""

    total: float
    hard_penalty: float
    coverage_error: float
    cd_error: float
    hom_error: float
    room_error: float
    di_error: float
    preference_error: float
    load_error: float
    geom_error: float
    details: dict[str, float] = field(default_factory=dict)
    flags: dict[str, bool | int | float] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """Return a plain dictionary representation suitable for logs/tests."""
        return {
            "total": float(self.total),
            "hard_penalty": float(self.hard_penalty),
            "coverage_error": float(self.coverage_error),
            "cd_error": float(self.cd_error),
            "hom_error": float(self.hom_error),
            "room_error": float(self.room_error),
            "di_error": float(self.di_error),
            "preference_error": float(self.preference_error),
            "load_error": float(self.load_error),
            "geom_error": float(self.geom_error),
            "details": dict(self.details),
            "flags": dict(self.flags),
            "warnings": tuple(self.warnings),
        }
