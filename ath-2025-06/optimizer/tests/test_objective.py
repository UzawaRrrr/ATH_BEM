from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimizer.objective import evaluate_objective, objective_from_result_bundle, optuna_objective_wrapper
from optimizer.score_components import aggregate_score
from optimizer.score_defaults import DEFAULT_SCORE_WEIGHTS, DEFAULT_STAGE_FACTORS, build_default_objective_config
from optimizer.score_types import GeometryStatus, PolarData


def _make_full_polar() -> PolarData:
    freqs_hz = np.geomspace(1000.0, 16000.0, 16)
    angles_deg_h = np.linspace(-50.0, 50.0, 21)
    angles_deg_v = np.linspace(-30.0, 30.0, 13)
    logf = np.log10(freqs_hz / freqs_hz[0])

    onaxis_db = 100.0 - 1.2 * logf
    h_norm = -((np.abs(angles_deg_h)[:, np.newaxis] / 42.0) ** 1.5) * (4.0 + 2.0 * logf[np.newaxis, :])
    v_norm = -((np.abs(angles_deg_v)[:, np.newaxis] / 28.0) ** 1.5) * (4.5 + 1.8 * logf[np.newaxis, :])
    spl_h_db = onaxis_db[np.newaxis, :] + h_norm
    spl_v_db = onaxis_db[np.newaxis, :] + v_norm

    beamwidth_6_h_deg = np.linspace(92.0, 70.0, freqs_hz.size)
    beamwidth_6_v_deg = np.linspace(62.0, 44.0, freqs_hz.size)
    di_db = 10.0 * np.log10((360.0 * 180.0) / (beamwidth_6_h_deg * beamwidth_6_v_deg))
    listening_window_db = onaxis_db - 0.7
    sound_power_db = onaxis_db - 3.0

    return PolarData(
        freqs_hz=freqs_hz,
        angles_deg_h=angles_deg_h,
        angles_deg_v=angles_deg_v,
        spl_h_db=spl_h_db,
        spl_v_db=spl_v_db,
        onaxis_db=onaxis_db,
        di_db=di_db,
        sound_power_db=sound_power_db,
        listening_window_db=listening_window_db,
        beamwidth_6_h_deg=beamwidth_6_h_deg,
        beamwidth_6_v_deg=beamwidth_6_v_deg,
    )


def _make_good_geom() -> GeometryStatus:
    return GeometryStatus(mesh_ok=True, solver_ok=True, geometry_ok=True)


def test_catastrophic_failure_returns_catastrophic_score() -> None:
    polar = _make_full_polar()
    geom = GeometryStatus(mesh_ok=True, solver_ok=False, geometry_ok=True)
    config = build_default_objective_config(stage="final")

    score = evaluate_objective(polar, geom, config)

    assert score.total == config.catastrophic_score
    assert bool(score.flags["catastrophic"]) is True


def test_objective_from_result_bundle_handles_missing_components_without_nan() -> None:
    polar = _make_full_polar()
    result_bundle = {
        "frequencies_hz": polar.freqs_hz,
        "angles_deg": polar.angles_deg_h,
        "spl_db": polar.spl_h_db.T,
        "summary": {"status": "done", "plane": "XZ"},
    }
    config = build_default_objective_config(stage="final")

    score = objective_from_result_bundle(result_bundle, config)

    assert np.isfinite(score.total)
    assert np.isfinite(score.coverage_error)
    assert bool(score.flags["any_missing"]) is True


def test_stage_weighting_matches_stage_schedule() -> None:
    polar = _make_full_polar()
    geom = _make_good_geom()

    for stage in ("coarse", "refine", "final"):
        config = replace(
            build_default_objective_config(stage=stage),
            target_bw_h_deg=80.0,
            target_bw_v_deg=52.0,
        )
        score = evaluate_objective(polar, geom, config)
        factors = DEFAULT_STAGE_FACTORS[stage]
        expected = (
            config.weights.w_hard * factors["hard"] * score.hard_penalty
            + config.weights.w_cov * factors["coverage"] * score.coverage_error
            + config.weights.w_cd * factors["cd"] * score.cd_error
            + config.weights.w_hom * factors["hom"] * score.hom_error
            + config.weights.w_room * factors["room"] * score.room_error
            + config.weights.w_di * factors["di"] * score.di_error
            + config.weights.w_pref * factors["pref"] * score.preference_error
            + config.weights.w_load * factors["load"] * score.load_error
            + config.weights.w_geom * factors["geom"] * score.geom_error
        )
        assert np.isclose(score.total, expected)


def test_default_weights_shift_focus_to_coverage_and_di_over_cd() -> None:
    assert DEFAULT_SCORE_WEIGHTS.w_cov > DEFAULT_SCORE_WEIGHTS.w_di
    assert DEFAULT_SCORE_WEIGHTS.w_di > DEFAULT_SCORE_WEIGHTS.w_cd
    assert DEFAULT_SCORE_WEIGHTS.w_cov > DEFAULT_SCORE_WEIGHTS.w_pref
    assert DEFAULT_SCORE_WEIGHTS.w_hom > DEFAULT_SCORE_WEIGHTS.w_cd


def test_stage_contributions_prioritize_coverage_then_di_then_cd() -> None:
    for stage in ("coarse", "refine", "final"):
        bundle = aggregate_score(
            components={
                "hard": 0.0,
                "coverage": 1.0,
                "cd": 1.0,
                "hom": 1.0,
                "room": 1.0,
                "di": 1.0,
                "preference": 1.0,
                "load": 1.0,
                "geom": 1.0,
            },
            config=build_default_objective_config(stage=stage),
        )
        contributions = bundle.details
        assert contributions["contribution.coverage"] > contributions["contribution.cd"]
        if stage == "coarse":
            assert contributions["contribution.cd"] == 0.0
            assert contributions["contribution.di"] == 0.0
            assert contributions["contribution.preference"] == 0.0
        elif stage == "refine":
            assert contributions["contribution.di"] > contributions["contribution.cd"]
            assert contributions["contribution.coverage"] > contributions["contribution.preference"]
        else:
            assert contributions["contribution.di"] > contributions["contribution.cd"]
            assert contributions["contribution.coverage"] > contributions["contribution.di"]
            assert contributions["contribution.coverage"] > contributions["contribution.preference"]


class _FakeTrial:
    def __init__(self) -> None:
        self.params: dict[str, float] = {"flare": 1.1}
        self.user_attrs: dict[str, object] = {
            "geometry_preferences": {
                "preferred_horn_length_mm": 180.0,
                "horn_length_tolerance_mm": 20.0,
                "horn_length_weight": 1.0,
            },
            "recipe.preview": {
                "horn_length": 190.0,
            },
        }

    def set_user_attr(self, key: str, value: object) -> None:
        self.user_attrs[key] = value


def test_optuna_objective_wrapper_records_trial_attrs() -> None:
    polar = _make_full_polar()
    geom = _make_good_geom()
    config = replace(
        build_default_objective_config(stage="final"),
        target_bw_h_deg=80.0,
        target_bw_v_deg=52.0,
    )
    trial = _FakeTrial()

    total = optuna_objective_wrapper(
        trial,
        case_runner=lambda received_params: {"params": dict(received_params)},
        parser_bridge=lambda _result: (polar, geom),
        config=config,
    )

    assert np.isfinite(total)
    assert "score.total" in trial.user_attrs
    assert "score.coverage" in trial.user_attrs
    assert "score.preference" in trial.user_attrs
    assert "flags.any_missing" in trial.user_attrs
    assert "flags.catastrophic" in trial.user_attrs


def test_geometry_preferences_improve_score_when_acoustics_are_equal() -> None:
    polar = _make_full_polar()
    geom = _make_good_geom()
    config = replace(
        build_default_objective_config(stage="final"),
        target_bw_h_deg=80.0,
        target_bw_v_deg=52.0,
    )
    preferences = {
        "preferred_horn_length_mm": 180.0,
        "horn_length_tolerance_mm": 20.0,
        "horn_length_weight": 1.0,
    }

    closer = evaluate_objective(
        polar,
        geom,
        config,
        geometry_preferences=preferences,
        recipe_geometry={"horn_length": 185.0, "mouth_width": 260.0, "mouth_height": 180.0},
    )
    farther = evaluate_objective(
        polar,
        geom,
        config,
        geometry_preferences=preferences,
        recipe_geometry={"horn_length": 260.0, "mouth_width": 260.0, "mouth_height": 180.0},
    )

    assert closer.preference_error < farther.preference_error
    assert closer.total < farther.total


def test_acoustic_gain_can_still_beat_preference_penalty() -> None:
    geom = _make_good_geom()
    config = replace(
        build_default_objective_config(stage="final"),
        target_bw_h_deg=80.0,
        target_bw_v_deg=52.0,
    )
    preferences = {
        "preferred_horn_length_mm": 180.0,
        "horn_length_tolerance_mm": 20.0,
        "horn_length_weight": 1.0,
    }
    acoustic_good = _make_full_polar()
    acoustic_bad_base = _make_full_polar()
    acoustic_bad = replace(
        acoustic_bad_base,
        beamwidth_6_h_deg=np.linspace(120.0, 105.0, acoustic_bad_base.freqs_hz.size),
        beamwidth_6_v_deg=np.linspace(82.0, 68.0, acoustic_bad_base.freqs_hz.size),
    )

    preferred_but_bad = evaluate_objective(
        acoustic_bad,
        geom,
        config,
        geometry_preferences=preferences,
        recipe_geometry={"horn_length": 180.0, "mouth_width": 260.0, "mouth_height": 180.0},
    )
    off_preference_but_good = evaluate_objective(
        acoustic_good,
        geom,
        config,
        geometry_preferences=preferences,
        recipe_geometry={"horn_length": 245.0, "mouth_width": 260.0, "mouth_height": 180.0},
    )

    assert preferred_but_bad.preference_error < off_preference_but_good.preference_error
    assert off_preference_but_good.coverage_error < preferred_but_bad.coverage_error
    assert off_preference_but_good.total < preferred_but_bad.total
