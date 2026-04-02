from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import optuna


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ath_gui.domain.design_recipe import DesignRecipe  # noqa: E402
from optimizer.design_space import build_design_space, build_initial_seed_params  # noqa: E402
from optimizer.driver_profile import DriverProfile, ProductConstraints  # noqa: E402
from optimizer.study_runner import OptunaStudyConfig, run_optuna_study  # noqa: E402


def _make_profile() -> DriverProfile:
    return DriverProfile(
        driver_id="demo_cd",
        name="Demo CD",
        driver_type="compression_driver",
        throat_diameter_mm=25.0,
        min_adapter_length_mm=8.0,
        preferred_min_mouth_to_throat_ratio=3.0,
        preferred_max_coverage_deg=110.0,
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


def _make_base_recipe() -> DesignRecipe:
    return DesignRecipe(
        case_name="study_smoke",
        throat_diameter=25.0,
        horn_length=210.0,
        coverage_angle=85.0,
        mouth_width=140.0,
        mouth_height=185.0,
        mouth_corner_radius=16.0,
        source_mode="normal",
        source_velocity=1.0,
        bem_f1=1000.0,
        bem_f2=8000.0,
        bem_num_freq=4,
        observation_plane="XZ",
    )


def test_build_design_space_respects_fixed_and_bounded_fields() -> None:
    space = build_design_space(_make_profile(), _make_constraints(), base_recipe=_make_base_recipe())

    throat = space.variables["throat_diameter"]
    assert throat.kind == "fixed"
    assert throat.fixed_value == 25.0
    assert space.variables["source_mode"].kind == "fixed"
    assert space.variables["source_velocity"].kind == "fixed"
    assert space.variables["source_velocity"].fixed_value == 1.0
    assert float(space.variables["horn_length"].high or 0.0) <= 240.0 + 1.0e-9
    assert "mouth_width" not in space.variables
    assert "mouth_height" not in space.variables
    assert "mouth_corner_radius" not in space.variables
    assert "bem_f1" not in space.variables
    assert "bem_f2" not in space.variables
    assert "bem_num_freq" not in space.variables
    assert "observation_plane" not in space.variables
    assert "mic_distance" not in space.variables
    assert "symmetry_enabled" not in space.variables
    assert "symmetry_planes" not in space.variables
    assert "flare_style" not in space.variables
    assert "ath_overrides.Term.s" in space.variables
    assert "ath_overrides.Term.q" in space.variables
    assert "ath_overrides.Term.n" in space.variables
    assert "ath_overrides.OS.k" in space.variables
    assert "GCurve.Type" not in space.variables
    assert "GCurve.SE.n" not in space.variables
    assert "GCurve.SF" not in space.variables
    assert "Morph.TargetWidth" not in space.variables
    assert any("BEM frequency band" in note for note in space.notes)
    assert any("OS-SE optimizer v1 only exposes core Term.s/Term.q/Term.n/OS.k parameters" in note for note in space.notes)
    assert any("Flare family, GCurve, superellipse, superformula, and Morph variables" in note for note in space.notes)


def test_conflicting_max_depth_caps_horn_length_search_window() -> None:
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
    base_recipe = _make_base_recipe()
    space = build_design_space(profile, constraints, base_recipe=base_recipe)

    horn = space.variables["horn_length"]
    assert float(horn.high or 0.0) <= 160.0 + 1.0e-9
    assert float(horn.low or 0.0) < float(horn.high or 0.0)
    assert any("Horn-length heuristic minimum exceeds max depth" in note for note in space.notes)


def test_initial_seed_stays_inside_design_space_and_roundtrips() -> None:
    profile = _make_profile()
    constraints = _make_constraints()
    base_recipe = DesignRecipe.from_dict({**_make_base_recipe().to_dict(), "source_velocity": 1.35})
    space = build_design_space(profile, constraints, base_recipe=base_recipe)
    seed = build_initial_seed_params(profile, constraints, base_recipe=base_recipe)
    optuna_params = space.to_optuna_params(seed)
    decoded = space.denormalize(optuna_params)

    for name, variable in space.variables.items():
        if name not in seed or variable.kind == "fixed":
            continue
        if variable.low is not None:
            assert float(seed[name]) >= float(variable.low) - 1.0e-9
        if variable.high is not None:
            assert float(seed[name]) <= float(variable.high) + 1.0e-9
    assert abs(float(decoded["horn_length"]) - float(seed["horn_length"])) < 1.0e-6
    assert abs(float(decoded["coverage_angle"]) - float(seed["coverage_angle"])) < 1.0e-6
    assert seed["source_velocity"] == 1.35
    assert seed["ath_overrides.Term.s"] == 0.7
    assert seed["ath_overrides.Term.q"] == 0.995
    assert seed["ath_overrides.Term.n"] == 4.0
    assert seed["ath_overrides.OS.k"] == 1.0
    assert "unit__source_velocity" not in optuna_params


def test_apply_to_recipe_keeps_fixed_environment_out_of_search_space() -> None:
    base_recipe = _make_base_recipe()
    profile = _make_profile()
    constraints = _make_constraints()
    space = build_design_space(profile, constraints, base_recipe=base_recipe)

    updated = space.apply_to_recipe(
        base_recipe,
        {
            "horn_length": 225.0,
            "coverage_angle": 92.0,
            "ath_overrides.Term.s": 0.72,
            "ath_overrides.Term.q": 0.991,
            "ath_overrides.Term.n": 4.5,
            "ath_overrides.OS.k": 1.08,
            "source_velocity": 1.0,
        },
    )

    assert updated.horn_length == 225.0
    assert updated.coverage_angle == 92.0
    assert updated.source_velocity == 1.0
    assert updated.bem_f1 == base_recipe.bem_f1
    assert updated.bem_f2 == base_recipe.bem_f2
    assert updated.bem_num_freq == base_recipe.bem_num_freq
    assert updated.observation_plane == base_recipe.observation_plane
    assert updated.mic_distance == base_recipe.mic_distance
    assert updated.ath_overrides["Term.s"] == 0.72
    assert updated.ath_overrides["Term.q"] == 0.991
    assert updated.ath_overrides["Term.n"] == 4.5
    assert updated.ath_overrides["OS.k"] == 1.08


class _FakeRunner:
    def __init__(self) -> None:
        self.calls = 0
        self.seen_params: list[dict[str, float]] = []

    def run(self, params: dict[str, float]) -> dict[str, object]:
        self.calls += 1
        self.seen_params.append(dict(params))
        freqs = [1000.0, 2000.0, 4000.0]
        angles = [0.0, 15.0]
        return {
            "frequencies_hz": freqs,
            "angles_deg": angles,
            "spl_db": [
                [100.0, 98.0],
                [100.5, 98.5],
                [101.0, 99.0],
            ],
            "summary": {
                "status": "done",
                "plane": "XZ",
                "onaxis_db": [100.0, 100.5, 101.0],
                "beamwidth_6_h_deg": [90.0, 80.0, 70.0],
            },
        }


def test_study_runner_smoke_blocks_infeasible_trials_and_runs_feasible_trials() -> None:
    profile = _make_profile()
    constraints = _make_constraints()
    base_recipe = _make_base_recipe()

    with tempfile.TemporaryDirectory() as tmp_invalid, tempfile.TemporaryDirectory() as tmp_valid:
        invalid_runner = _FakeRunner()
        invalid_result = run_optuna_study(
            base_recipe=base_recipe,
            case_runner=invalid_runner,
            config=OptunaStudyConfig(
                trials=1,
                stage="final",
                study_name="invalid_smoke",
                study_dir=Path(tmp_invalid),
                seed=123,
                driver_profile=profile,
                product_constraints=constraints,
            ),
            suggest_fn=lambda _trial, _recipe: {
                "throat_diameter": 25.0,
                "horn_length": 120.0,
                "coverage_angle": 85.0,
                "ath_overrides.Term.s": 0.7,
                "ath_overrides.Term.q": 0.995,
                "ath_overrides.Term.n": 4.0,
                "ath_overrides.OS.k": 1.0,
                "source_velocity": 1.0,
            },
        )
        assert invalid_runner.calls == 0
        invalid_user_attrs = invalid_result.study.trials[0].user_attrs
        assert invalid_user_attrs["feasibility.hard_fail"] is True
        assert invalid_user_attrs["flags.preflight_hard_fail"] is True
        assert invalid_user_attrs["flags.constraint_conflict"] is True
        assert invalid_user_attrs["flags.missing_required_param"] is False
        assert invalid_user_attrs["flags.any_missing"] is False
        assert invalid_user_attrs["flags.catastrophic"] is True

        valid_runner = _FakeRunner()
        valid_result = run_optuna_study(
            base_recipe=base_recipe,
            case_runner=valid_runner,
            config=OptunaStudyConfig(
                trials=1,
                stage="final",
                study_name="valid_smoke",
                study_dir=Path(tmp_valid),
                seed=456,
                driver_profile=profile,
                product_constraints=constraints,
            ),
            suggest_fn=lambda _trial, _recipe: {
                "throat_diameter": 25.0,
                "horn_length": 210.0,
                "coverage_angle": 88.0,
                "ath_overrides.Term.s": 0.7,
                "ath_overrides.Term.q": 0.995,
                "ath_overrides.Term.n": 4.0,
                "ath_overrides.OS.k": 1.0,
                "source_velocity": 1.0,
            },
        )
        assert valid_runner.calls == 1
        assert valid_result.study.trials[0].user_attrs["feasibility.hard_fail"] is False
        assert "design_space.actual_params" in valid_result.study.trials[0].user_attrs


def test_study_runner_blocks_invalid_osse_proxy_before_runner() -> None:
    profile = _make_profile()
    constraints = _make_constraints()
    base_recipe = _make_base_recipe()

    with tempfile.TemporaryDirectory() as tmp_invalid:
        invalid_runner = _FakeRunner()
        invalid_result = run_optuna_study(
            base_recipe=base_recipe,
            case_runner=invalid_runner,
            config=OptunaStudyConfig(
                trials=1,
                stage="final",
                study_name="invalid_osse_smoke",
                study_dir=Path(tmp_invalid),
                seed=321,
                driver_profile=profile,
                product_constraints=constraints,
            ),
            suggest_fn=lambda _trial, _recipe: {
                "throat_diameter": 25.0,
                "horn_length": 210.0,
                "coverage_angle": 60.0,
                "ath_overrides.Term.s": 0.85,
                "ath_overrides.Term.q": 0.96,
                "ath_overrides.Term.n": 6.0,
                "ath_overrides.OS.k": 1.25,
                "source_velocity": 1.0,
            },
        )
        assert invalid_runner.calls == 0
        trial = invalid_result.study.trials[0]
        feasibility = trial.user_attrs["feasibility"]
        assert trial.user_attrs["feasibility.hard_fail"] is True
        assert feasibility["derived_metrics"]["osse_valid"] == 0.0
        assert any(issue["code"] == "osse_slope_too_steep" for issue in feasibility["issues"])


def _run_all() -> None:
    test_build_design_space_respects_fixed_and_bounded_fields()
    test_conflicting_max_depth_caps_horn_length_search_window()
    test_initial_seed_stays_inside_design_space_and_roundtrips()
    test_apply_to_recipe_keeps_fixed_environment_out_of_search_space()
    test_study_runner_smoke_blocks_infeasible_trials_and_runs_feasible_trials()
    test_study_runner_blocks_invalid_osse_proxy_before_runner()


if __name__ == "__main__":
    _run_all()
    print("test_design_space.py: ok")
