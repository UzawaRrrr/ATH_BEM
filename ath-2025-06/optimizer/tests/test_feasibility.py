from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ath_gui.domain.design_recipe import DesignRecipe  # noqa: E402
from optimizer.design_space import build_design_space  # noqa: E402
from optimizer.driver_profile import (  # noqa: E402
    COARSE_INFERRED_RELAXATION_NOTE,
    INFERRED_PRODUCT_CONSTRAINTS_NOTE,
    DriverProfile,
    ProductConstraints,
)
from optimizer.feasibility import (  # noqa: E402
    feasibility_penalty,
    validate_params_against_design_space,
    validate_recipe_against_driver,
)


def _make_profile() -> DriverProfile:
    return DriverProfile(
        driver_id="demo_cd",
        name="Demo CD",
        driver_type="compression_driver",
        throat_diameter_mm=25.0,
        exit_angle_deg=10.0,
        mounting_flange_diameter_mm=90.0,
        preferred_min_mouth_to_throat_ratio=3.0,
        preferred_max_coverage_deg=110.0,
        min_adapter_length_mm=8.0,
    )


def _make_constraints() -> ProductConstraints:
    return ProductConstraints(
        max_baffle_width_mm=280.0,
        max_baffle_height_mm=220.0,
        max_depth_mm=240.0,
        min_wall_thickness_mm=4.0,
        target_bw_h_deg=90.0,
        target_bw_v_deg=60.0,
        target_low_freq_hz=1000.0,
    )


def _make_recipe(**overrides: float) -> DesignRecipe:
    recipe = DesignRecipe(
        case_name="feasibility_case",
        throat_diameter=25.0,
        horn_length=210.0,
        coverage_angle=88.0,
        mouth_width=130.0,
        mouth_height=185.0,
        mouth_corner_radius=16.0,
        source_velocity=1.0,
        ath_overrides={
            "Term.s": 0.7,
            "Term.q": 0.995,
            "Term.n": 4.0,
            "OS.k": 1.0,
        },
    )
    return DesignRecipe.from_dict({**recipe.to_dict(), **overrides})


def test_feasibility_hard_fail_and_soft_penalty_cases() -> None:
    profile = _make_profile()
    constraints = _make_constraints()
    design_space = build_design_space(profile, constraints, base_recipe=_make_recipe())

    ok_result = validate_recipe_against_driver(_make_recipe(), profile, constraints)
    assert ok_result.ok is True
    assert ok_result.hard_fail is False

    throat_mismatch = validate_recipe_against_driver(_make_recipe(throat_diameter=26.0), profile, constraints)
    assert throat_mismatch.hard_fail is True

    mouth_too_small = validate_recipe_against_driver(_make_recipe(mouth_width=60.0, mouth_height=55.0), profile, constraints)
    assert mouth_too_small.hard_fail is True

    corner_invalid = validate_recipe_against_driver(_make_recipe(mouth_corner_radius=80.0), profile, constraints)
    assert corner_invalid.hard_fail is True

    coverage_soft = validate_recipe_against_driver(_make_recipe(coverage_angle=118.0), profile, constraints)
    assert coverage_soft.ok is True
    assert coverage_soft.hard_fail is False
    assert coverage_soft.soft_penalty > 0.0

    params_ok = validate_params_against_design_space(
        {
            "throat_diameter": 25.0,
            "horn_length": 210.0,
            "coverage_angle": 88.0,
            "ath_overrides.Term.s": 0.7,
            "ath_overrides.Term.q": 0.995,
            "ath_overrides.Term.n": 4.0,
            "ath_overrides.OS.k": 1.0,
            "mouth_width": 130.0,
            "mouth_height": 185.0,
            "mouth_corner_radius": 16.0,
            "source_velocity": 1.0,
        },
        design_space,
    )
    assert params_ok.ok is True
    assert params_ok.hard_fail is False
    assert feasibility_penalty(coverage_soft, catastrophic_score=1000.0) > 0.0

    osse_ok = validate_recipe_against_driver(_make_recipe(), profile, constraints)
    assert osse_ok.hard_fail is False
    assert osse_ok.derived_metrics["osse_valid"] == 1.0
    assert osse_ok.derived_metrics["osse_monotonic_ok"] == 1.0
    assert "osse_throat_slope_proxy_deg" in osse_ok.derived_metrics
    assert "osse_terminal_proxy_mm" in osse_ok.derived_metrics
    assert "osse_curvature_proxy" in osse_ok.derived_metrics


def test_explicit_packaging_conflict_now_fails_fast() -> None:
    profile = _make_profile()
    constraints = ProductConstraints(
        max_baffle_width_mm=320.0,
        max_baffle_height_mm=240.0,
        max_depth_mm=160.0,
        min_wall_thickness_mm=4.0,
        target_bw_h_deg=60.0,
        target_bw_v_deg=60.0,
        target_low_freq_hz=1200.0,
    )
    recipe = _make_recipe(horn_length=160.0, mouth_width=160.0, mouth_height=185.0, coverage_angle=60.0)

    result = validate_recipe_against_driver(recipe, profile, constraints)

    assert result.hard_fail is True
    assert any(issue.code == "horn_too_short" and issue.severity == "hard" for issue in result.issues)
    assert feasibility_penalty(result, catastrophic_score=1000.0) >= 1000.0


def test_inferred_coarse_packaging_conflict_can_be_soft_penalized() -> None:
    profile = _make_profile()
    constraints = ProductConstraints(
        max_baffle_width_mm=320.0,
        max_baffle_height_mm=240.0,
        max_depth_mm=160.0,
        min_wall_thickness_mm=4.0,
        target_bw_h_deg=60.0,
        target_bw_v_deg=60.0,
        target_low_freq_hz=1200.0,
        notes=[INFERRED_PRODUCT_CONSTRAINTS_NOTE, COARSE_INFERRED_RELAXATION_NOTE],
    )
    recipe = _make_recipe(horn_length=160.0, mouth_width=160.0, mouth_height=185.0, coverage_angle=60.0)

    result = validate_recipe_against_driver(recipe, profile, constraints, conflict_stage="coarse")

    assert result.hard_fail is False
    assert result.ok is True
    assert any(issue.code == "horn_too_short" and issue.severity == "soft" for issue in result.issues)
    assert feasibility_penalty(result, catastrophic_score=1000.0) < 1000.0


def test_extreme_osse_proxy_is_rejected_before_expensive_pipeline() -> None:
    profile = _make_profile()
    constraints = _make_constraints()
    recipe = _make_recipe(
        coverage_angle=60.0,
        ath_overrides={
            "Term.s": 0.85,
            "Term.q": 0.96,
            "Term.n": 6.0,
            "OS.k": 1.25,
        },
    )

    result = validate_recipe_against_driver(recipe, profile, constraints)

    assert result.hard_fail is True
    assert any(issue.code == "osse_slope_too_steep" for issue in result.issues)
    assert result.derived_metrics["osse_valid"] == 0.0
    assert result.derived_metrics["osse_terminal_proxy_mm"] > recipe.throat_diameter


def _run_all() -> None:
    test_feasibility_hard_fail_and_soft_penalty_cases()
    test_explicit_packaging_conflict_now_fails_fast()
    test_inferred_coarse_packaging_conflict_can_be_soft_penalized()
    test_extreme_osse_proxy_is_rejected_before_expensive_pipeline()


if __name__ == "__main__":
    _run_all()
    print("test_feasibility.py: ok")
