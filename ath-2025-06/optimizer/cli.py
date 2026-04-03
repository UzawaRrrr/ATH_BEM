"""Run end-to-end ATH/BEM optimization with Optuna."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Any, Callable

from ath_gui.domain.design_recipe import DesignRecipe
from ath_gui.infrastructure.bem_bridge import DEFAULT_WSL_VENV
from optimizer.headless_case_runner import HeadlessCaseRunner
from optimizer.study_runner import (
    OptunaStudyConfig,
    parse_planes_spec,
    run_optuna_study,
    suggest_default_params,
    write_study_artifacts,
)


def _load_callable(spec: str | None) -> Callable[..., Any] | None:
    """Load a Python callable from `module:function` notation."""
    text = str(spec or "").strip()
    if not text:
        return None
    if ":" not in text:
        raise ValueError("Callable imports must use `module:function` format.")
    module_name, attr_name = text.split(":", 1)
    module = importlib.import_module(module_name)
    func = getattr(module, attr_name)
    if not callable(func):
        raise TypeError(f"Imported object is not callable: {text}")
    return func


def main(argv: list[str] | None = None) -> int:
    """Run a complete Optuna study using the headless ATH/BEM runner."""
    parser = argparse.ArgumentParser(description="Run ATH/BEM Optuna optimization.")
    parser.add_argument("--recipe", required=True, help="Path to a base design_recipe.json file.")
    parser.add_argument("--base-horn-cfg", default="", help="Optional base horn.cfg used as the ATH state template.")
    parser.add_argument("--trials", type=int, default=10, help="Number of Optuna trials to run.")
    parser.add_argument("--stage", choices=("coarse", "refine", "final"), default="final", help="Scoring stage.")
    parser.add_argument("--target-bw-h", type=float, default=None, help="Horizontal target beamwidth for scoring.")
    parser.add_argument("--target-bw-v", type=float, default=None, help="Vertical target beamwidth for scoring.")
    parser.add_argument("--projects-root", default="", help="Optional workspace root override.")
    parser.add_argument("--backend", choices=("wsl", "local_python", "conda"), default="wsl", help="BEM launch backend.")
    parser.add_argument("--wsl-venv", default=DEFAULT_WSL_VENV, help="WSL solver venv path.")
    parser.add_argument("--local-solver-python", default="", help="Local Python interpreter for `local_python` backend.")
    parser.add_argument("--conda-exe", default="conda", help="Conda executable for `conda` backend.")
    parser.add_argument("--conda-env", default="bempp", help="Conda environment for `conda` backend.")
    parser.add_argument("--planes", nargs="+", default=["XZ", "YZ"], help="Observation planes to run.")
    parser.add_argument("--study-name", default="", help="Optional Optuna study name.")
    parser.add_argument("--storage", default="", help="Optional Optuna storage URL, for example sqlite:///optuna.db.")
    parser.add_argument("--seed", type=int, default=42, help="TPE sampler seed.")
    parser.add_argument("--study-dir", default="", help="Directory for study metadata outputs.")
    parser.add_argument("--enqueue-base", action="store_true", help="Evaluate the base recipe before sampled trials.")
    parser.add_argument("--suggest-fn", default="", help="Optional `module:function` trial suggestion hook.")
    parser.add_argument("--recipe-transform", default="", help="Optional `module:function` recipe transform hook.")
    args = parser.parse_args(argv)

    recipe_path = Path(args.recipe).expanduser().resolve()
    base_recipe = DesignRecipe.from_dict(json.loads(recipe_path.read_text(encoding="utf-8")))
    suggest_fn = _load_callable(args.suggest_fn) or suggest_default_params
    recipe_transform = _load_callable(args.recipe_transform)
    if recipe_transform is not None and not callable(recipe_transform):
        raise TypeError("--recipe-transform must resolve to a callable.")

    runner = HeadlessCaseRunner(
        base_recipe_path=recipe_path,
        base_horn_cfg_path=Path(args.base_horn_cfg).expanduser().resolve() if str(args.base_horn_cfg).strip() else None,
        projects_root=Path(args.projects_root).expanduser().resolve() if str(args.projects_root).strip() else None,
        planes=parse_planes_spec(args.planes),
        backend=args.backend,
        wsl_venv=args.wsl_venv,
        local_solver_python=args.local_solver_python,
        conda_exe=args.conda_exe,
        conda_env=args.conda_env,
        recipe_transform=recipe_transform,  # type: ignore[arg-type]
    )

    study_config = OptunaStudyConfig(
        trials=int(args.trials),
        stage=args.stage,
        target_bw_h_deg=args.target_bw_h,
        target_bw_v_deg=args.target_bw_v,
        study_name=args.study_name,
        study_dir=Path(args.study_dir).expanduser().resolve() if str(args.study_dir).strip() else None,
        storage=str(args.storage).strip() or None,
        seed=int(args.seed),
        enqueue_base=bool(args.enqueue_base),
    )

    result = run_optuna_study(
        base_recipe=base_recipe,
        case_runner=runner,
        config=study_config,
        suggest_fn=suggest_fn,  # type: ignore[arg-type]
    )
    write_study_artifacts(
        result.study,
        result.study_dir,
        metadata={
            "recipe": str(recipe_path),
            "base_horn_cfg": str(Path(args.base_horn_cfg).expanduser().resolve()) if str(args.base_horn_cfg).strip() else "",
            "stage": study_config.stage,
            "target_bw_h": study_config.target_bw_h_deg,
            "target_bw_v": study_config.target_bw_v_deg,
            "backend": args.backend,
            "planes": list(parse_planes_spec(args.planes)),
            "study_name": result.config.study_name,
            "storage": study_config.storage,
            "seed": study_config.seed,
            "trials": study_config.trials,
        },
    )

    best_trial = result.study.best_trial
    print(f"Study name: {result.study.study_name}")
    print(f"Best value: {result.study.best_value}")
    print(f"Best params: {json.dumps(best_trial.params, ensure_ascii=True, sort_keys=True)}")
    print(f"Artifacts: {result.study_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

