#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from waveguide_opt.configuration import load_config
from waveguide_opt.mesh_pipeline import build_mesh
from waveguide_opt.solver_pipeline import solve_acoustics
from waveguide_opt.utils import create_logger, ensure_directories


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark WSL solver handoff first-run and repeated-run behavior.")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "local_paths.yaml")
    parser.add_argument("--mode", choices=["real", "mock"], default="real")
    args = parser.parse_args()

    config = load_config(args.config)
    ensure_directories(
        [
            config.paths.logs_directory,
            config.paths.outputs_directory,
            config.paths.mesh_output_directory,
            config.paths.solver_output_directory,
            config.paths.temp_directory,
        ]
    )
    logger = create_logger(config.paths.logs_directory, "benchmark_wsl_solver")

    candidate = {
        "length": 0.24,
        "throat_radius": 0.02,
        "mouth_radius": 0.12,
        "flare": 1.3,
    }
    case_name = f"wsl_bench_{int(time.time())}"

    mesh = build_mesh(params=candidate, config=config, mode=args.mode, case_name=case_name, logger=logger)
    solver = solve_acoustics(
        mesh_path=mesh.mesh_path,
        params=candidate,
        config=config,
        mode=args.mode,
        case_name=case_name,
        logger=logger,
    )
    wsl_benchmark = solver.details.get("wsl_benchmark", {})
    report = {
        "case_name": case_name,
        "mode": args.mode,
        "mesh_path": str(mesh.mesh_path),
        "observation_csv": str(solver.observation_csv),
        "solver_details": solver.details,
    }
    report_path = config.paths.outputs_directory / "wsl_solver_benchmark_result.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("benchmark_wsl_solver: PASS")
    print(f"observation={solver.observation_csv}")
    print(f"report={report_path}")
    if wsl_benchmark:
        print(f"first_run_seconds={wsl_benchmark.get('first_run_seconds')}")
        print(f"repeated_run_average_seconds={wsl_benchmark.get('repeated_run_average_seconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
