"""Default weights, bands, and stage schedules for the headless scorer."""

from __future__ import annotations

from dataclasses import replace

from .score_types import HomProxyWeights, ObjectiveConfig, ScoreWeights


DEFAULT_SCORE_WEIGHTS = ScoreWeights(
    w_hard=1.0,
    w_cov=1.0,
    # Coverage remains the dominant optimization target.
    w_cd=0.15,
    # HOM/room/load/geom stay as guardrails, not the main search direction.
    w_hom=0.5,
    w_room=0.3,
    # DI is a smoothness helper, not an absolute target template.
    w_di=0.35,
    # Geometry preferences are soft regularization only; they should never
    # overpower coverage tracking or force hard geometry limits.
    w_pref=0.12,
    w_load=0.15,
    w_geom=0.25,
)

DEFAULT_HOM_PROXY_WEIGHTS = HomProxyWeights(
    mono=1.0,
    angular=0.8,
    spectral=0.8,
    edge=1.0,
)

DEFAULT_COMPONENT_NORMALIZERS: dict[str, float] = {
    "coverage_target_db": 3.0,
    "coverage_beamwidth_deg": 15.0,
    "cd_db": 3.0,
    "hom_db": 2.5,
    "room_db": 2.0,
    "di_db": 2.0,
    "preference_penalty": 1.0,
    "load_ratio": 1.0,
    "geom_penalty": 100.0,
    "hard_penalty": 1.0,
}

DEFAULT_STAGE_FACTORS: dict[str, dict[str, float]] = {
    "coarse": {
        "hard": 1.0,
        "coverage": 1.0,
        # Coarse stage searches for viable coverage first. Do not let
        # constant-directivity or smoothness terms dominate early exploration.
        "cd": 0.0,
        "hom": 0.0,
        "room": 0.0,
        "di": 0.0,
        "pref": 0.0,
        "load": 0.0,
        "geom": 0.0,
    },
    "refine": {
        "hard": 1.0,
        "coverage": 1.0,
        # Refine keeps coverage in charge while introducing a modest DI
        # smoothness helper and only a very small CD guardrail.
        "cd": 0.15,
        "hom": 0.3,
        "room": 0.2,
        "di": 0.5,
        "pref": 0.2,
        "load": 0.0,
        "geom": 0.0,
    },
    "final": {
        "hard": 1.0,
        "coverage": 1.0,
        # Final stage keeps a small constant-directivity guardrail, but the
        # main objective remains band-wide coverage with DI smoothness support.
        "cd": 0.25,
        "hom": 0.6,
        "room": 0.5,
        "di": 1.0,
        "pref": 0.35,
        "load": 0.35,
        "geom": 0.35,
    },
}

DEFAULT_FAILURE_SCORE = 100.0
DEFAULT_CATASTROPHIC_SCORE = 1000.0


def build_default_objective_config(*, stage: str = "final") -> ObjectiveConfig:
    """Build a conservative default `ObjectiveConfig` suitable for pure Optuna runs."""
    normalizers = dict(DEFAULT_COMPONENT_NORMALIZERS)
    normalizers["geom_penalty"] = DEFAULT_FAILURE_SCORE
    return ObjectiveConfig(
        freq_band_cov_hz=(1000.0, 16000.0),
        freq_band_room_hz=(800.0, 16000.0),
        freq_band_load_hz=(800.0, 8000.0),
        target_bw_h_deg=None,
        target_bw_v_deg=None,
        edge_angle_range_h_deg=(35.0, 55.0),
        edge_angle_range_v_deg=(20.0, 40.0),
        monotonicity_epsilon_db=0.5,
        roughness_use_log_frequency=True,
        detrend_kind="linear_logf",
        weights=DEFAULT_SCORE_WEIGHTS,
        stage=stage,  # type: ignore[arg-type]
        failure_score=DEFAULT_FAILURE_SCORE,
        catastrophic_score=DEFAULT_CATASTROPHIC_SCORE,
        hom_weights=DEFAULT_HOM_PROXY_WEIGHTS,
        component_normalizers=normalizers,
    )


def with_stage(config: ObjectiveConfig, stage: str) -> ObjectiveConfig:
    """Return a copy of `config` with only the stage changed."""
    return replace(config, stage=stage)  # type: ignore[arg-type]
