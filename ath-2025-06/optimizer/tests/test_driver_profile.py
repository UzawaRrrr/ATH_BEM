from __future__ import annotations

import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimizer.driver_profile import (  # noqa: E402
    DriverProfile,
    ProductConstraints,
    derive_driver_constraints,
    dump_driver_profile,
    infer_driver_profile_from_recipe,
    infer_product_constraints_from_recipe,
    is_recipe_inferred_constraints,
    load_driver_profile,
    relax_inferred_product_constraints,
)
from ath_gui.domain.design_recipe import DesignRecipe  # noqa: E402


def _make_profile() -> DriverProfile:
    return DriverProfile(
        driver_id="jbl_2409h",
        name="JBL 2409H",
        driver_type="compression_driver",
        diaphragm_diameter_mm=38.0,
        effective_diaphragm_diameter_mm=34.0,
        throat_diameter_mm=25.0,
        exit_angle_deg=10.0,
        mounting_flange_diameter_mm=90.0,
        bolt_circle_diameter_mm=76.0,
        bolt_count=4,
        min_adapter_length_mm=8.0,
        preferred_min_mouth_to_throat_ratio=3.0,
        preferred_max_coverage_deg=110.0,
    )


def _make_constraints() -> ProductConstraints:
    return ProductConstraints(
        max_baffle_width_mm=320.0,
        max_baffle_height_mm=240.0,
        max_depth_mm=220.0,
        min_wall_thickness_mm=4.0,
        target_bw_h_deg=90.0,
        target_bw_v_deg=60.0,
        target_low_freq_hz=1000.0,
        target_high_freq_hz=18000.0,
    )


def test_driver_profile_json_roundtrip_and_derive() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "driver.json"
        profile = _make_profile()
        constraints = _make_constraints()

        dump_driver_profile(path, profile)
        loaded = load_driver_profile(path)
        derived = derive_driver_constraints(loaded, constraints)

        assert loaded.to_dict() == profile.to_dict()
        assert derived.fixed_throat_diameter_mm == 25.0
        assert derived.min_mouth_width_mm is not None and derived.min_mouth_width_mm >= 75.0
        assert derived.min_mouth_height_mm is not None and derived.min_mouth_height_mm >= 75.0
        assert derived.min_horn_length_mm is not None and derived.min_horn_length_mm >= 8.0
        assert derived.max_horn_length_mm == 220.0
        assert derived.max_mouth_width_mm is not None and derived.max_mouth_width_mm < 320.0


def test_coarse_relaxed_inferred_constraints_do_not_lock_the_design_space() -> None:
    recipe = DesignRecipe(
        case_name="inferred_lock_case",
        throat_diameter=25.0,
        horn_length=160.0,
        coverage_angle=90.0,
        mouth_width=140.0,
        mouth_height=170.0,
        mouth_corner_radius=14.0,
        bem_f1=200.0,
        bem_f2=12000.0,
        bem_num_freq=8,
    )
    profile = infer_driver_profile_from_recipe(recipe)
    inferred = infer_product_constraints_from_recipe(recipe)
    original = derive_driver_constraints(profile, inferred)
    relaxed = relax_inferred_product_constraints(inferred, stage="coarse")
    relaxed_derived = derive_driver_constraints(profile, relaxed)

    assert is_recipe_inferred_constraints(inferred) is True
    assert inferred.target_low_freq_hz == 200.0
    assert original.min_mouth_width_mm is not None and original.max_mouth_width_mm is not None
    assert original.min_mouth_width_mm > original.max_mouth_width_mm
    assert original.min_horn_length_mm is not None and original.max_horn_length_mm is not None
    assert original.min_horn_length_mm > original.max_horn_length_mm

    assert relaxed.target_low_freq_hz is None
    assert relaxed.max_baffle_width_mm is not None and inferred.max_baffle_width_mm is not None
    assert relaxed.max_baffle_width_mm > inferred.max_baffle_width_mm
    assert relaxed.max_depth_mm is not None and inferred.max_depth_mm is not None
    assert relaxed.max_depth_mm > inferred.max_depth_mm
    assert relaxed_derived.min_mouth_width_mm is not None and relaxed_derived.max_mouth_width_mm is not None
    assert relaxed_derived.min_mouth_width_mm < relaxed_derived.max_mouth_width_mm
    assert relaxed_derived.min_horn_length_mm is not None and relaxed_derived.max_horn_length_mm is not None
    assert relaxed_derived.min_horn_length_mm < relaxed_derived.max_horn_length_mm


def _run_all() -> None:
    test_driver_profile_json_roundtrip_and_derive()
    test_coarse_relaxed_inferred_constraints_do_not_lock_the_design_space()


if __name__ == "__main__":
    _run_all()
    print("test_driver_profile.py: ok")
