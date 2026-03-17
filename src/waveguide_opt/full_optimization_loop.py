from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .configuration import ProjectConfig, load_config
from .directivity_scoring import score_observation_csv
from .ga_parameters import load_ga_runtime_setup
from .ga_optimization import Bounds, Individual, run_ga
from .mesh_pipeline import build_mesh
from .solver_pipeline import solve_acoustics
from .utils import create_logger, ensure_directories


@dataclass
class EvaluationResult:
    fitness: float
    total_error: float
    mesh_path: Path
    observation_csv: Path
    mode: str
    details: dict[str, Any]


DEFAULT_BOUNDS: Bounds = {
    "length": (0.12, 0.5),
    "throat_radius": (0.01, 0.05),
    "mouth_radius": (0.05, 0.25),
    "flare": (0.4, 2.5),
}


def evaluate_individual(
    individual: Individual,
    config: ProjectConfig,
    mode: str,
    logger,
    case_tag: str,
) -> EvaluationResult:
    mesh_result = build_mesh(params=individual, config=config, mode=mode, case_name=case_tag, logger=logger)
    solver_result = solve_acoustics(
        mesh_path=mesh_result.mesh_path,
        params=individual,
        config=config,
        mode=mode,
        case_name=case_tag,
        logger=logger,
    )
    score = score_observation_csv(
        observation_csv=solver_result.observation_csv,
        target_db=config.runtime.target_db,
        outside_target_db=config.runtime.outside_target_db,
        spill_weight=config.runtime.spill_weight,
        coverage_half_angle_deg=config.runtime.coverage_half_angle_deg,
        geometry_params=individual,
        geometry_bounds=DEFAULT_BOUNDS,
        objective_weights=config.runtime.objective_weights,
        alpha_frequency_weights=config.runtime.alpha_frequency_weights,
        beta_frequency_weights=config.runtime.beta_frequency_weights,
        gamma_frequency_weights=config.runtime.gamma_frequency_weights,
        beamwidth_db_down=config.runtime.beamwidth_db_down,
        min_efficiency_proxy_db=config.runtime.min_efficiency_proxy_db,
        min_matching_proxy=config.runtime.min_matching_proxy,
        min_energy_concentration=config.runtime.min_energy_concentration,
        mfg_penalty_scale=config.runtime.mfg_penalty_scale,
        smooth_boundary_band_deg=config.runtime.smooth_boundary_band_deg,
        side_lobe_margin_db=config.runtime.side_lobe_margin_db,
        smooth_transition_weight=config.runtime.smooth_transition_weight,
        smooth_boundary_weight=config.runtime.smooth_boundary_weight,
        smooth_sidelobe_weight=config.runtime.smooth_sidelobe_weight,
        default_bw_h_target_deg=config.runtime.default_bw_h_target_deg,
        default_bw_v_target_deg=config.runtime.default_bw_v_target_deg,
        coverage_target_path=config.runtime.coverage_target_path,
        breakdown_output_dir=config.paths.outputs_directory,
        breakdown_case_tag=case_tag,
    )
    logger.info(
        "score case=%s J=%.4f E_in=%.4f E_out=%.4f E_bw=%.4f E_smooth=%.4f E_eff=%.4f E_mfg=%.4f",
        case_tag,
        score.J,
        score.E_in,
        score.E_out,
        score.E_bw,
        score.E_smooth,
        score.E_eff,
        score.E_mfg,
    )
    if score.skipped_components:
        logger.info("score case=%s skipped_components=%s", case_tag, ",".join(score.skipped_components))
    if score.warnings:
        logger.info("score case=%s warnings=%s", case_tag, " | ".join(score.warnings))
    return EvaluationResult(
        fitness=score.fitness,
        total_error=score.total_error,
        mesh_path=mesh_result.mesh_path,
        observation_csv=solver_result.observation_csv,
        mode=mode,
        details={
            "mesh": mesh_result.details,
            "solver": solver_result.details,
            "score": asdict(score),
        },
    )


def run_minimal_loop(
    config_path: Path | None = None,
    mode: str | None = None,
    population_size: int = 6,
    generations: int = 2,
    mutation_scale: float = 0.1,
    elite_count: int = 2,
    seed: int | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    selected_mode = (mode or config.runtime.default_mode).lower().strip()
    if selected_mode not in {"mock", "real"}:
        raise ValueError("mode must be one of: mock, real")

    ensure_directories(
        [
            config.paths.logs_directory,
            config.paths.outputs_directory,
            config.paths.mesh_output_directory,
            config.paths.solver_output_directory,
            config.paths.temp_directory,
        ]
    )
    logger = create_logger(config.paths.logs_directory, "minimal_optimization")
    logger.info("Starting minimal optimization in mode=%s", selected_mode)

    ga_setup = load_ga_runtime_setup(
        path_token=config.runtime.ga_parameters_path,
        fallback_bounds=DEFAULT_BOUNDS,
        base_dir=config.paths.working_directory,
    )
    logger.info(
        "GA parameter setup source=%s enabled=%s disabled=%s",
        ga_setup.source_path or "default",
        ",".join(ga_setup.enabled_params),
        ",".join(ga_setup.disabled_params),
    )
    for warning in ga_setup.warnings:
        logger.warning("GA parameter warning: %s", warning)

    counter = {"value": 0}
    evaluation_cache: dict[str, EvaluationResult] = {}

    def evaluate_fn(individual: Individual) -> float:
        counter["value"] += 1
        case_tag = f"ga_eval_{counter['value']:04d}_{int(time.time())}"
        full_individual = dict(ga_setup.fixed_params)
        full_individual.update(individual)
        logger.info("case=%s candidate=%s", case_tag, json.dumps(full_individual, sort_keys=True))
        result = evaluate_individual(full_individual, config, selected_mode, logger, case_tag)
        evaluation_cache[case_tag] = result
        logger.info("case=%s fitness=%.6f total_error=%.6f", case_tag, result.fitness, result.total_error)
        return result.fitness

    ga_seed = seed if seed is not None else config.runtime.random_seed
    ga_result = run_ga(
        evaluate_fn=evaluate_fn,
        bounds=ga_setup.bounds,
        population_size=population_size,
        generations=generations,
        mutation_scale=mutation_scale,
        elite_count=elite_count,
        seed=ga_seed,
    )

    payload = {
        "mode": selected_mode,
        "population_size": population_size,
        "generations": generations,
        "seed": ga_seed,
        "best_candidate": {**ga_setup.fixed_params, **ga_result.best_individual},
        "best_candidate_ga_only": ga_result.best_individual,
        "best_score": ga_result.best_fitness,
        "history": ga_result.history,
        "ga_parameters": {
            "source_path": ga_setup.source_path,
            "enabled": ga_setup.enabled_params,
            "disabled": ga_setup.disabled_params,
            "fixed_params": ga_setup.fixed_params,
            "initial_params": ga_setup.initial_params,
            "warnings": ga_setup.warnings,
        },
        "evaluations": {
            key: {
                "fitness": value.fitness,
                "total_error": value.total_error,
                "mesh_path": str(value.mesh_path),
                "observation_csv": str(value.observation_csv),
                "mode": value.mode,
                "details": value.details,
            }
            for key, value in evaluation_cache.items()
        },
    }

    result_path = config.paths.outputs_directory / "minimal_optimization_result.json"
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Minimal optimization finished. Result stored at %s", result_path)

    payload["result_path"] = str(result_path)
    return payload


def run_full_loop(
    config_path: Path | None = None,
    mode: str | None = None,
    population_size: int | None = None,
    generations: int | None = None,
    mutation_scale: float | None = None,
    elite_count: int | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    payload = run_minimal_loop(
        config_path=config_path,
        mode=mode,
        population_size=population_size if population_size is not None else config.runtime.full_population_size,
        generations=generations if generations is not None else config.runtime.full_generations,
        mutation_scale=mutation_scale if mutation_scale is not None else config.runtime.full_mutation_scale,
        elite_count=elite_count if elite_count is not None else config.runtime.full_elite_count,
        seed=seed,
    )
    full_path = config.paths.outputs_directory / "full_optimization_result.json"
    full_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["result_path"] = str(full_path)
    return payload
