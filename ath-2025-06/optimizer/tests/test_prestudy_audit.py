from __future__ import annotations

import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ath_gui.domain.design_recipe import DesignRecipe  # noqa: E402
from optimizer.driver_profile import (  # noqa: E402
    DriverProfile,
    ProductConstraints,
    infer_driver_profile_from_recipe,
)
from optimizer.study_runner import OptunaStudyConfig, run_optuna_study  # noqa: E402


class _FakeRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, params: dict[str, float]) -> dict[str, object]:
        self.calls += 1
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
                "plane": "XZ",
                "onaxis_db": [100.0, 100.5, 101.0],
                "beamwidth_6_h_deg": [90.0, 80.0, 70.0],
            },
        }


def _make_profile() -> DriverProfile:
    return DriverProfile(
        driver_id="audit_driver",
        name="Audit Driver",
        driver_type="compression_driver",
        throat_diameter_mm=25.0,
        mounting_flange_diameter_mm=90.0,
        min_adapter_length_mm=8.0,
        preferred_min_mouth_to_throat_ratio=3.0,
        preferred_max_coverage_deg=110.0,
    )


def _make_recipe() -> DesignRecipe:
    return DesignRecipe(
        case_name="audit_case",
        throat_diameter=25.0,
        horn_length=160.0,
        coverage_angle=90.0,
        mouth_width=140.0,
        mouth_height=170.0,
        mouth_corner_radius=14.0,
        source_mode="normal",
        source_velocity=1.0,
        bem_f1=200.0,
        bem_f2=12000.0,
        bem_num_freq=8,
        observation_plane="XZ",
    )


def test_prestudy_audit_fails_fast_for_explicit_empty_constraint_set() -> None:
    recipe = _make_recipe()
    profile = _make_profile()
    constraints = ProductConstraints(
        max_baffle_width_mm=90.0,
        max_baffle_height_mm=60.0,
        max_depth_mm=80.0,
        min_wall_thickness_mm=4.0,
        target_bw_h_deg=60.0,
        target_bw_v_deg=60.0,
        target_low_freq_hz=1200.0,
        notes=["explicit packaging"],
    )
    runner = _FakeRunner()
    events: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_optuna_study(
            base_recipe=recipe,
            case_runner=runner,
            config=OptunaStudyConfig(
                trials=3,
                stage="final",
                study_name="audit_fail_fast",
                study_dir=Path(tmpdir),
                driver_profile=profile,
                product_constraints=constraints,
            ),
            on_event=events.append,
        )

    assert runner.calls == 0
    assert len(result.study.trials) == 0
    audit_event = next(event for event in events if event.get("event") == "study_audit")
    assert audit_event["passed"] is False
    audit = audit_event["audit"]
    assert audit["constraints_are_inferred_fallback"] is False
    assert any(item["severity"] == "conflict" for item in audit["conflicts"])
    assert any(item["code"] in {"mouth_width_empty", "mouth_height_empty", "horn_length_empty"} for item in audit["conflicts"])
    aborted = next(event for event in events if event.get("event") == "study_aborted")
    assert aborted["reason"] == "prestudy_audit_failed"


def test_prestudy_audit_marks_inferred_coarse_constraints_as_fallback_with_warnings() -> None:
    recipe = _make_recipe()
    profile = infer_driver_profile_from_recipe(recipe)
    runner = _FakeRunner()
    events: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_optuna_study(
            base_recipe=recipe,
            case_runner=runner,
            config=OptunaStudyConfig(
                trials=1,
                stage="coarse",
                study_name="audit_inferred_coarse",
                study_dir=Path(tmpdir),
                driver_profile=profile,
                product_constraints=None,
            ),
            suggest_fn=lambda _trial, _recipe: {
                "throat_diameter": 25.0,
                "horn_length": 170.0,
                "coverage_angle": 90.0,
                "ath_overrides.Term.s": 0.7,
                "ath_overrides.Term.q": 0.995,
                "ath_overrides.Term.n": 4.0,
                "ath_overrides.OS.k": 1.0,
                "source_velocity": 1.0,
            },
            on_event=events.append,
        )

    assert len(result.study.trials) == 1
    audit_event = next(event for event in events if event.get("event") == "study_audit")
    assert audit_event["passed"] is True
    audit = audit_event["audit"]
    assert audit["constraints_are_inferred_fallback"] is True
    assert "recipe_inferred_relaxed_for_coarse" in audit["constraint_strategy"]
    assert any(item["code"] == "inferred_constraints_fallback" for item in audit["warnings"])
    assert any(item["code"] == "inferred_constraints_relaxed" for item in audit["warnings"])


def _run_all() -> None:
    test_prestudy_audit_fails_fast_for_explicit_empty_constraint_set()
    test_prestudy_audit_marks_inferred_coarse_constraints_as_fallback_with_warnings()


if __name__ == "__main__":
    _run_all()
    print("test_prestudy_audit.py: ok")
