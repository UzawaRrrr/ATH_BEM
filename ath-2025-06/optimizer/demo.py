"""Minimal synthetic demo for the headless ATH/BEM objective scorer."""

from __future__ import annotations

import argparse
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np

from .case_result import CaseArtifacts, CaseResult, CaseStatus
from .objective import evaluate_objective, optuna_objective_wrapper
from .result_bridge import emit_optimizer_payload, emit_optimizer_status_json
from .score_defaults import build_default_objective_config
from .score_types import GeometryStatus, PolarData


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synthetic demos for the optimizer scorer/bridge.")
    parser.add_argument("--mode", choices=("scorer", "bridge"), default="scorer")
    args = parser.parse_args()
    if args.mode == "bridge":
        run_fake_optuna_bridge_demo()
    else:
        main()
