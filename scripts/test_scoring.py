#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from waveguide_opt.configuration import load_config
from waveguide_opt.full_optimization_loop import DEFAULT_BOUNDS
from waveguide_opt.scoring.fitness import score_observation_csv
from waveguide_opt.scoring.io import generate_mock_observation_csv, parse_observation_file
from waveguide_opt.utils import create_logger, ensure_directories


def main() -> int:
    parser = argparse.ArgumentParser(description="Run parser + scoring validation on mock observation data.")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "local_paths.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    ensure_directories(
        [
            config.paths.logs_directory,
            config.paths.outputs_directory,
            config.paths.solver_output_directory,
        ]
    )
    logger = create_logger(config.paths.logs_directory, "test_scoring")

    good_csv = config.paths.solver_output_directory / "scoring_test_good.csv"
    bad_csv = config.paths.solver_output_directory / "scoring_test_bad.csv"
    generate_mock_observation_csv(
        output_path=good_csv,
        profile="good",
        frequencies_hz=config.runtime.frequencies_hz,
        horizontal_coverage_deg=config.runtime.default_bw_h_target_deg,
        vertical_coverage_deg=config.runtime.default_bw_v_target_deg,
    )
    generate_mock_observation_csv(
        output_path=bad_csv,
        profile="bad",
        frequencies_hz=config.runtime.frequencies_hz,
        horizontal_coverage_deg=config.runtime.default_bw_h_target_deg,
        vertical_coverage_deg=config.runtime.default_bw_v_target_deg,
    )

    # Parser validation: same function supports CSV/JSON/NPZ input families.
    parsed_good = parse_observation_file(good_csv)
    parsed_bad = parse_observation_file(bad_csv)
    logger.info("Parsed good schema: %s", parsed_good.detected_schema)
    logger.info("Parsed bad schema: %s", parsed_bad.detected_schema)

    geometry_candidate = {
        "length": 0.24,
        "throat_radius": 0.02,
        "mouth_radius": 0.12,
        "flare": 1.2,
    }
    common_kwargs = {
        "target_db": config.runtime.target_db,
        "outside_target_db": config.runtime.outside_target_db,
        "spill_weight": config.runtime.spill_weight,
        "coverage_half_angle_deg": config.runtime.coverage_half_angle_deg,
        "geometry_params": geometry_candidate,
        "geometry_bounds": DEFAULT_BOUNDS,
        "objective_weights": config.runtime.objective_weights,
        "alpha_frequency_weights": config.runtime.alpha_frequency_weights,
        "beta_frequency_weights": config.runtime.beta_frequency_weights,
        "gamma_frequency_weights": config.runtime.gamma_frequency_weights,
        "beamwidth_db_down": config.runtime.beamwidth_db_down,
        "default_bw_h_target_deg": config.runtime.default_bw_h_target_deg,
        "default_bw_v_target_deg": config.runtime.default_bw_v_target_deg,
        "smooth_boundary_band_deg": config.runtime.smooth_boundary_band_deg,
        "side_lobe_margin_db": config.runtime.side_lobe_margin_db,
        "smooth_transition_weight": config.runtime.smooth_transition_weight,
        "smooth_boundary_weight": config.runtime.smooth_boundary_weight,
        "smooth_sidelobe_weight": config.runtime.smooth_sidelobe_weight,
        "min_efficiency_proxy_db": config.runtime.min_efficiency_proxy_db,
        "min_matching_proxy": config.runtime.min_matching_proxy,
        "min_energy_concentration": config.runtime.min_energy_concentration,
        "mfg_penalty_scale": config.runtime.mfg_penalty_scale,
        "coverage_target_path": config.runtime.coverage_target_path,
        "breakdown_output_dir": config.paths.outputs_directory,
    }

    good_score = score_observation_csv(
        observation_csv=good_csv,
        breakdown_case_tag="test_scoring_good",
        **common_kwargs,
    )
    bad_score = score_observation_csv(
        observation_csv=bad_csv,
        breakdown_case_tag="test_scoring_bad",
        **common_kwargs,
    )

    passed = good_score.total_cost < bad_score.total_cost and good_score.fitness > bad_score.fitness
    if not passed:
        logger.error(
            "Score ordering failed: good.total_cost=%.4f bad.total_cost=%.4f",
            good_score.total_cost,
            bad_score.total_cost,
        )

    payload = {
        "pass": passed,
        "coverage_target_path": config.runtime.coverage_target_path,
        "good_observation": str(good_csv),
        "bad_observation": str(bad_csv),
        "good_score": good_score.__dict__,
        "bad_score": bad_score.__dict__,
    }
    report_path = config.paths.outputs_directory / "test_scoring_result.json"
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if passed:
        print("test_scoring: PASS")
    else:
        print("test_scoring: FAIL")
    print(f"good_total_cost={good_score.total_cost:.6f}")
    print(f"bad_total_cost={bad_score.total_cost:.6f}")
    print(f"report={report_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
