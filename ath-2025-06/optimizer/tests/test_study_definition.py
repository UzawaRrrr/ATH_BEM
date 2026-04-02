from __future__ import annotations

import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ath_gui.domain.design_recipe import DesignRecipe  # noqa: E402
from optimizer.driver_profile import DriverProfile, ProductConstraints  # noqa: E402
from optimizer.study_definition import CanonicalTrialRecipeBuilder, adapt_legacy_study_inputs  # noqa: E402
from optimizer.study_runner import OptunaStudyConfig, run_optuna_study  # noqa: E402


def _make_profile() -> DriverProfile:
    return DriverProfile(
        driver_id="study_def_driver",
        name="Study Def Driver",
        driver_type="compression_driver",
        throat_diameter_mm=25.4,
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
        symmetric_horizontal=False,
        symmetric_vertical=True,
        notes=["legacy constraint note"],
    )


def _make_recipe() -> DesignRecipe:
    return DesignRecipe(
        case_name="study_definition_case",
        throat_diameter=25.4,
        horn_length=180.0,
        coverage_angle=85.0,
        mouth_width=260.0,
        mouth_height=180.0,
        mouth_corner_radius=20.0,
        source_mode="normal",
        source_velocity=1.2,
        auto_enclosure_enabled=False,
        bem_f1=900.0,
        bem_f2=15000.0,
        bem_num_freq=24,
        observation_plane="YZ",
        mic_distance=3.0,
        symmetry_enabled=True,
        symmetry_planes=("x",),
    )


class _FakeRunner:
    def __init__(self) -> None:
        self.calls = 0
        self.seen_params: list[dict[str, float]] = []

    def run(self, params: dict[str, float]) -> dict[str, object]:
        self.calls += 1
        self.seen_params.append(dict(params))
        return {
            "frequencies_hz": [1000.0, 2000.0, 4000.0],
            "angles_deg": [0.0, 15.0],
            "spl_db": [
                [100.0, 98.0],
                [100.5, 98.5],
                [101.0, 99.0],
            ],
            "summary": {
                "status": "done",
                "plane": "YZ",
                "onaxis_db": [100.0, 100.5, 101.0],
                "beamwidth_6_h_deg": [90.0, 80.0, 70.0],
            },
        }


def test_adapt_legacy_study_inputs_splits_into_five_layers() -> None:
    config = OptunaStudyConfig(stage="refine", target_bw_h_deg=100.0, target_bw_v_deg=70.0)
    recipe = _make_recipe()
    profile = _make_profile()
    constraints = _make_constraints()

    study_definition = adapt_legacy_study_inputs(
        legacy_config=config,
        base_recipe=recipe,
        driver_profile=profile,
        product_constraints=constraints,
    )

    environment = study_definition.study_environment
    assert environment.bem_f1 == 900.0
    assert environment.bem_f2 == 15000.0
    assert environment.bem_num_freq == 24
    assert environment.observation_plane == "YZ"
    assert environment.mic_distance == 3.0
    assert environment.symmetry_enabled is True
    assert environment.symmetry_planes == ("x",)
    assert environment.source_mode == "normal"
    assert environment.source_velocity == 1.2
    assert environment.auto_enclosure_enabled is False

    hard = study_definition.hard_constraints
    assert hard.max_baffle_width_mm == 320.0
    assert hard.max_baffle_height_mm == 240.0
    assert hard.max_depth_mm == 220.0
    assert hard.min_wall_thickness_mm == 4.0
    assert hard.fixed_throat_diameter_mm == 25.4
    assert hard.mounting_flange_diameter_mm == 90.0
    assert hard.bolt_circle_diameter_mm == 76.0
    assert hard.bolt_count == 4

    acoustic = study_definition.acoustic_targets
    assert acoustic.target_bw_h_deg == 100.0
    assert acoustic.target_bw_v_deg == 70.0
    assert acoustic.target_low_freq_hz == 1000.0
    assert acoustic.target_high_freq_hz == 18000.0
    assert acoustic.stage == "refine"
    assert acoustic.score_band_cov_hz == (1000.0, 16000.0)
    assert acoustic.score_band_room_hz == (800.0, 16000.0)
    assert acoustic.score_band_load_hz == (800.0, 8000.0)

    preferences = study_definition.geometry_preferences
    assert preferences.preferred_mouth_width_mm == 260.0
    assert preferences.preferred_mouth_height_mm == 180.0
    assert preferences.preferred_horn_length_mm == 180.0
    assert preferences.mouth_width_tolerance_mm is not None and preferences.mouth_width_tolerance_mm >= 10.0
    assert preferences.horn_length_tolerance_mm is not None and preferences.horn_length_tolerance_mm >= 10.0

    policy = study_definition.search_policy
    assert policy.optimize_throat_diameter is False
    assert policy.optimize_horn_length is True
    assert policy.optimize_coverage_angle is True
    assert policy.optimize_osse is True
    assert policy.optimize_mouth_width is False
    assert policy.optimize_mouth_height is False
    assert policy.optimize_flare is False
    assert policy.optimize_gcurve is False
    assert policy.optimize_morph is False

    legacy_roundtrip = study_definition.to_legacy_product_constraints()
    assert legacy_roundtrip.max_baffle_width_mm == constraints.max_baffle_width_mm
    assert legacy_roundtrip.max_baffle_height_mm == constraints.max_baffle_height_mm
    assert legacy_roundtrip.max_depth_mm == constraints.max_depth_mm
    assert legacy_roundtrip.min_wall_thickness_mm == constraints.min_wall_thickness_mm
    assert legacy_roundtrip.target_bw_h_deg == 100.0
    assert legacy_roundtrip.target_bw_v_deg == 70.0
    assert legacy_roundtrip.target_low_freq_hz == constraints.target_low_freq_hz
    assert legacy_roundtrip.target_high_freq_hz == constraints.target_high_freq_hz
    assert legacy_roundtrip.symmetric_horizontal is False
    assert legacy_roundtrip.symmetric_vertical is True


def test_study_runner_emits_semantic_study_definition_layers() -> None:
    recipe = _make_recipe()
    profile = _make_profile()
    constraints = _make_constraints()
    events: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        run_optuna_study(
            base_recipe=recipe,
            case_runner=object(),
            config=OptunaStudyConfig(
                trials=1,
                stage="coarse",
                study_name="study_definition_event",
                study_dir=Path(tmpdir),
                driver_profile=profile,
                product_constraints=constraints,
            ),
            suggest_fn=lambda _trial, _recipe: {
                "throat_diameter": 25.4,
                "horn_length": 40.0,
                "coverage_angle": 85.0,
                "ath_overrides.Term.s": 0.7,
                "ath_overrides.Term.q": 0.995,
                "ath_overrides.Term.n": 4.0,
                "ath_overrides.OS.k": 1.0,
                "source_velocity": 1.2,
            },
            on_event=events.append,
        )

    started = next(event for event in events if event.get("event") == "study_started")
    assert "study_environment" in started
    assert "hard_constraints" in started
    assert "acoustic_targets" in started
    assert "geometry_preferences" in started
    assert "search_policy" in started
    assert "study_definition" in started
    assert started["study_environment"]["observation_plane"] == "YZ"
    assert started["hard_constraints"]["fixed_throat_diameter_mm"] == 25.4
    assert started["acoustic_targets"]["stage"] == "coarse"
    assert started["search_policy"]["optimize_osse"] is True
    assert started["search_policy"]["optimize_gcurve"] is False


def test_canonical_trial_recipe_builder_uses_fixed_mouth_geometry_policy() -> None:
    recipe = DesignRecipe.from_dict({**_make_recipe().to_dict(), "mouth_width": 111.0, "mouth_height": 112.0, "mouth_corner_radius": 9.0})
    profile = _make_profile()
    constraints = _make_constraints()
    study_definition = adapt_legacy_study_inputs(
        legacy_config=OptunaStudyConfig(stage="final"),
        base_recipe=recipe,
        driver_profile=profile,
        product_constraints=constraints,
    )
    builder = CanonicalTrialRecipeBuilder(
        study_definition=study_definition,
        driver_profile=profile,
        base_template=recipe,
    )

    built = builder.build(
        {
            "throat_diameter": 25.4,
            "horn_length": 205.0,
            "coverage_angle": 92.0,
            "ath_overrides.Term.s": 0.72,
            "ath_overrides.Term.q": 0.991,
            "ath_overrides.Term.n": 4.5,
            "ath_overrides.OS.k": 1.08,
        }
    )
    preview = built.recipe

    assert preview.horn_length == 205.0
    assert preview.coverage_angle == 92.0
    assert preview.bem_f1 == recipe.bem_f1
    assert preview.bem_f2 == recipe.bem_f2
    assert preview.bem_num_freq == recipe.bem_num_freq
    assert preview.observation_plane == recipe.observation_plane
    assert preview.mic_distance == recipe.mic_distance
    assert preview.source_mode == recipe.source_mode
    assert preview.source_velocity == recipe.source_velocity
    assert preview.mouth_width != 111.0
    assert preview.mouth_height != 112.0
    assert preview.mouth_corner_radius != 9.0
    assert built.source_summary["mouth_geometry_policy"] == "baseline_mouth_geometry_policy"
    assert built.source_summary["environment_source"] == "StudyEnvironment"
    assert preview.ath_overrides["Term.s"] == 0.72
    assert preview.ath_overrides["Term.q"] == 0.991
    assert preview.ath_overrides["Term.n"] == 4.5
    assert preview.ath_overrides["OS.k"] == 1.08


def test_study_runner_trial_preview_uses_consistent_canonical_mouth_geometry() -> None:
    recipe = DesignRecipe.from_dict({**_make_recipe().to_dict(), "mouth_width": 111.0, "mouth_height": 112.0, "mouth_corner_radius": 9.0})
    profile = _make_profile()
    constraints = _make_constraints()
    events: list[dict[str, object]] = []
    runner = _FakeRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_optuna_study(
            base_recipe=recipe,
            case_runner=runner,
            config=OptunaStudyConfig(
                trials=2,
                stage="final",
                study_name="canonical_recipe_preview",
                study_dir=Path(tmpdir),
                driver_profile=profile,
                product_constraints=constraints,
            ),
            suggest_fn=lambda trial, _recipe: {
                "throat_diameter": 25.4,
                "horn_length": 205.0 + float(trial.number),
                "coverage_angle": 88.0 + float(trial.number),
                "ath_overrides.Term.s": 0.7,
                "ath_overrides.Term.q": 0.995,
                "ath_overrides.Term.n": 4.0,
                "ath_overrides.OS.k": 1.0,
            },
            on_event=events.append,
        )

    assert runner.calls == 2
    previews = [trial.user_attrs["recipe.preview"] for trial in result.study.trials]
    sources = [trial.user_attrs["recipe.canonical_sources"] for trial in result.study.trials]
    assert previews[0]["mouth_width"] == previews[1]["mouth_width"]
    assert previews[0]["mouth_height"] == previews[1]["mouth_height"]
    assert previews[0]["mouth_corner_radius"] == previews[1]["mouth_corner_radius"]
    assert previews[0]["mouth_width"] != 111.0
    assert previews[0]["mouth_height"] != 112.0
    assert sources[0]["mouth_geometry_policy"] == "baseline_mouth_geometry_policy"
    assert sources[1]["mouth_geometry_policy"] == "baseline_mouth_geometry_policy"
    assert previews[0]["horn_length"] != previews[1]["horn_length"]
    assert previews[0]["coverage_angle"] != previews[1]["coverage_angle"]


def _run_all() -> None:
    test_adapt_legacy_study_inputs_splits_into_five_layers()
    test_study_runner_emits_semantic_study_definition_layers()
    test_canonical_trial_recipe_builder_uses_fixed_mouth_geometry_policy()
    test_study_runner_trial_preview_uses_consistent_canonical_mouth_geometry()


if __name__ == "__main__":
    _run_all()
    print("test_study_definition.py: ok")
