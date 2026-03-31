"""Minimal synthetic demo for the headless ATH/BEM objective scorer."""

from __future__ import annotations

import argparse
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np

from .case_result import CaseArtifacts, CaseResult, CaseStatus
from .driver_profile import DriverProfile, ProductConstraints
from .objective import evaluate_objective, optuna_objective_wrapper
from .result_bridge import emit_optimizer_payload, emit_optimizer_status_json
from .score_defaults import build_default_objective_config
from .score_types import GeometryStatus, PolarData
from .study_runner import OptunaStudyConfig, run_optuna_study
from ath_gui.domain.design_recipe import DesignRecipe


def build_synthetic_demo_case() -> tuple[PolarData, GeometryStatus]:
    """Create a small synthetic H/V polar dataset for local scorer smoke tests."""
    freqs_hz = np.geomspace(800.0, 16000.0, 24)
    angles_deg_h = np.linspace(-60.0, 60.0, 25)
    angles_deg_v = np.linspace(-40.0, 40.0, 17)
    logf = np.log10(freqs_hz / freqs_hz[0])

    onaxis_db = 102.0 - (1.4 * logf)
    h_loss = -((np.abs(angles_deg_h)[:, np.newaxis] / 45.0) ** 1.4) * (4.5 + 2.5 * logf[np.newaxis, :])
    v_loss = -((np.abs(angles_deg_v)[:, np.newaxis] / 30.0) ** 1.5) * (4.0 + 2.0 * logf[np.newaxis, :])

    spl_h_db = onaxis_db[np.newaxis, :] + h_loss
    spl_v_db = onaxis_db[np.newaxis, :] + v_loss

    beamwidth_6_h_deg = np.linspace(95.0, 68.0, freqs_hz.size)
    beamwidth_6_v_deg = np.linspace(70.0, 42.0, freqs_hz.size)
    listening_window_db = onaxis_db - 0.8
    sound_power_db = onaxis_db - 3.0
    di_db = 10.0 * np.log10((360.0 * 180.0) / (beamwidth_6_h_deg * beamwidth_6_v_deg))

    polar = PolarData(
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
    geom = GeometryStatus(mesh_ok=True, solver_ok=True, geometry_ok=True)
    return polar, geom


def main() -> None:
    """Run the synthetic demo and print a compact score summary."""
    polar, geom = build_synthetic_demo_case()
    config = replace(build_default_objective_config(stage="final"), target_bw_h_deg=80.0, target_bw_v_deg=50.0)
    score = evaluate_objective(polar, geom, config)
    print(f"total={score.total:.4f}")
    print(
        "components:",
        f"cov={score.coverage_error:.4f}",
        f"cd={score.cd_error:.4f}",
        f"hom={score.hom_error:.4f}",
        f"room={score.room_error:.4f}",
        f"di={score.di_error:.4f}",
        f"load={score.load_error:.4f}",
        f"geom={score.geom_error:.4f}",
    )
    print(f"flags={score.flags}")


def run_fake_optuna_bridge_demo() -> None:
    """Run a minimal fake case runner + fake trial smoke demo through the bridge."""

    class _FakeTrial:
        def __init__(self) -> None:
            self.params = {"flare": 1.25, "mouth_ratio": 0.8}
            self.user_attrs: dict[str, object] = {}

        def set_user_attr(self, key: str, value: object) -> None:
            self.user_attrs[key] = value

    class _FakeRunner:
        def __init__(self, result: CaseResult) -> None:
            self.result = result

        def run(self, params: dict[str, float]) -> CaseResult:
            print(f"runner params={params}")
            return self.result

    polar, _ = build_synthetic_demo_case()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload_path = root / "optimizer_payload.npz"
        status_path = root / "optimizer_status.json"
        emit_optimizer_payload(
            payload_path,
            freqs_hz=polar.freqs_hz,
            angles_deg_h=polar.angles_deg_h,
            angles_deg_v=polar.angles_deg_v,
            spl_h_db=polar.spl_h_db,
            spl_v_db=polar.spl_v_db,
            onaxis_db=polar.onaxis_db,
            di_db=polar.di_db,
            sound_power_db=polar.sound_power_db,
            listening_window_db=polar.listening_window_db,
            beamwidth_6_h_deg=polar.beamwidth_6_h_deg,
            beamwidth_6_v_deg=polar.beamwidth_6_v_deg,
        )
        emit_optimizer_status_json(
            status_path,
            {
                "ath_ok": True,
                "bem_ok": True,
                "post_ok": True,
                "mesh_ok": True,
                "geometry_ok": True,
            },
        )
        case_result = CaseResult(
            artifacts=CaseArtifacts(
                case_dir=root,
                optimizer_payload=payload_path,
                optimizer_status_json=status_path,
            ),
            status=CaseStatus(),
        )
        trial = _FakeTrial()
        runner = _FakeRunner(case_result)
        config = replace(build_default_objective_config(stage="final"), target_bw_h_deg=80.0, target_bw_v_deg=50.0)
        total = optuna_objective_wrapper(trial, runner, config=config)
        print(f"optuna total={total:.4f}")
        print(f"trial attrs keys={sorted(trial.user_attrs)[:8]} ... total={len(trial.user_attrs)}")


def run_fake_study_feasibility_demo() -> None:
    """Run a tiny study through driver_profile -> design_space -> feasibility."""

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

    base_recipe = DesignRecipe(
        case_name="study_demo",
        throat_diameter=25.0,
        horn_length=210.0,
        coverage_angle=88.0,
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
    driver_profile = DriverProfile(
        driver_id="demo_cd",
        name="Demo CD",
        driver_type="compression_driver",
        throat_diameter_mm=25.0,
        min_adapter_length_mm=8.0,
        preferred_min_mouth_to_throat_ratio=3.0,
        preferred_max_coverage_deg=110.0,
    )
    product_constraints = ProductConstraints(
        max_baffle_width_mm=280.0,
        max_baffle_height_mm=220.0,
        max_depth_mm=240.0,
        min_wall_thickness_mm=4.0,
        target_bw_h_deg=90.0,
        target_bw_v_deg=60.0,
        target_low_freq_hz=1000.0,
    )

    with tempfile.TemporaryDirectory() as tmp:
        runner = _FakeRunner()
        result = run_optuna_study(
            base_recipe=base_recipe,
            case_runner=runner,
            config=OptunaStudyConfig(
                trials=2,
                stage="final",
                study_name="fake_study_demo",
                study_dir=Path(tmp),
                seed=123,
                driver_profile=driver_profile,
                product_constraints=product_constraints,
            ),
        )
        best_trial = result.study.best_trial
        print(f"study best={best_trial.value:.6f}")
        print(f"runner calls={runner.calls}")
        print(f"best params={best_trial.user_attrs.get('design_space.actual_params', {})}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synthetic demos for the optimizer scorer/bridge.")
    parser.add_argument("--mode", choices=("scorer", "bridge", "study"), default="scorer")
    args = parser.parse_args()
    if args.mode == "bridge":
        run_fake_optuna_bridge_demo()
    elif args.mode == "study":
        run_fake_study_feasibility_demo()
    else:
        main()
