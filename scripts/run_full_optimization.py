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

from waveguide_opt.full_optimization_loop import run_full_loop


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full GA optimization loop.")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "local_paths.yaml")
    parser.add_argument("--mode", choices=["mock", "real"], default=None)
    parser.add_argument("--population-size", type=int, default=None)
    parser.add_argument("--generations", type=int, default=None)
    parser.add_argument("--mutation-scale", type=float, default=None)
    parser.add_argument("--elite-count", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    try:
        result = run_full_loop(
            config_path=args.config,
            mode=args.mode,
            population_size=args.population_size,
            generations=args.generations,
            mutation_scale=args.mutation_scale,
            elite_count=args.elite_count,
            seed=args.seed,
        )
    except Exception as exc:
        print("Full optimization: FAIL")
        print(f"Reason: {exc}")
        return 1

    print("Full optimization: PASS")
    print(f"mode={result['mode']}")
    print(f"best score={result['best_score']:.6f}")
    print("best candidate:")
    print(json.dumps(result["best_candidate"], indent=2))
    print(f"result={result['result_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
