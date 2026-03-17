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
from waveguide_opt.full_optimization_loop import evaluate_individual
from waveguide_opt.utils import create_logger, ensure_directories


def main() -> int:
    parser = argparse.ArgumentParser(description="Run smoke test for mesh->solver->scoring chain.")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "local_paths.yaml")
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
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
    logger = create_logger(config.paths.logs_directory, "smoke_test")

    candidate = {
        "length": 0.24,
        "throat_radius": 0.02,
        "mouth_radius": 0.12,
        "flare": 1.3,
    }
    case_tag = f"smoke_{int(time.time())}"

    try:
        result = evaluate_individual(
            individual=candidate,
            config=config,
            mode=args.mode,
            logger=logger,
            case_tag=case_tag,
        )
    except Exception as exc:
        logger.exception("Smoke test failed: %s", exc)
        print("Smoke test result: FAIL")
        print(f"Reason: {exc}")
        return 1

    payload = {
        "mode": args.mode,
        "candidate": candidate,
        "fitness": result.fitness,
        "total_error": result.total_error,
        "mesh_path": str(result.mesh_path),
        "observation_csv": str(result.observation_csv),
        "details": result.details,
    }

    report_path = config.paths.outputs_directory / "smoke_test_result.json"
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("Smoke test result: PASS")
    print(f"mode={args.mode}")
    print(f"fitness={result.fitness:.6f}")
    print(f"mesh={result.mesh_path}")
    print(f"observation={result.observation_csv}")
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

