"""Headless scoring helpers for Optuna-driven ATH/BEM optimization."""

from .case_result import CaseArtifacts, CaseResult, CaseStatus, normalize_path
from .design_space import DesignSpace, DesignVariable, build_default_baseline_recipe, build_design_space, build_initial_seed_params
from .driver_profile import (
    DerivedDriverConstraints,
    DriverProfile,
    ProductConstraints,
    derive_driver_constraints,
    dump_driver_profile,
    load_driver_profile,
)
from .feasibility import (
    FeasibilityIssue,
    FeasibilityResult,
    feasibility_penalty,
    merge_feasibility_results,
    validate_params_against_design_space,
    validate_recipe_against_driver,
)
from .objective import evaluate_objective, objective_from_result_bundle, optuna_objective_wrapper
from .result_bridge import (
    case_result_to_score_inputs,
    emit_optimizer_payload,
    emit_optimizer_status_json,
    load_from_optimizer_payload,
    load_geometry_status,
    load_polar_data,
)
from .score_defaults import (
    DEFAULT_COMPONENT_NORMALIZERS,
    DEFAULT_HOM_PROXY_WEIGHTS,
    DEFAULT_SCORE_WEIGHTS,
    DEFAULT_STAGE_FACTORS,
    build_default_objective_config,
)
from .score_types import GeometryStatus, HomProxyWeights, ObjectiveConfig, PolarData, ScoreBundle, ScoreWeights

__all__ = [
    "DEFAULT_COMPONENT_NORMALIZERS",
    "DEFAULT_HOM_PROXY_WEIGHTS",
    "DEFAULT_SCORE_WEIGHTS",
    "DEFAULT_STAGE_FACTORS",
    "CaseArtifacts",
    "CaseResult",
    "CaseStatus",
    "DerivedDriverConstraints",
    "DesignSpace",
    "DesignVariable",
    "DriverProfile",
    "FeasibilityIssue",
    "FeasibilityResult",
    "GeometryStatus",
    "HeadlessCaseRunner",
    "HomProxyWeights",
    "ObjectiveConfig",
    "PolarData",
    "ProductConstraints",
    "ScoreBundle",
    "ScoreWeights",
    "build_default_objective_config",
    "build_default_baseline_recipe",
    "build_design_space",
    "build_initial_seed_params",
    "case_result_to_score_inputs",
    "derive_driver_constraints",
    "evaluate_objective",
    "emit_optimizer_payload",
    "emit_optimizer_status_json",
    "dump_driver_profile",
    "feasibility_penalty",
    "load_from_optimizer_payload",
    "load_driver_profile",
    "load_geometry_status",
    "load_polar_data",
    "merge_feasibility_results",
    "normalize_path",
    "objective_from_result_bundle",
    "optuna_objective_wrapper",
    "validate_params_against_design_space",
    "validate_recipe_against_driver",
]


def __getattr__(name: str) -> object:
    """Lazily import heavier runtime helpers only when requested."""
    if name == "HeadlessCaseRunner":
        from .headless_case_runner import HeadlessCaseRunner

        return HeadlessCaseRunner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
