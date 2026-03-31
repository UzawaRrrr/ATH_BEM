"""Headless scoring helpers for Optuna-driven ATH/BEM optimization."""

from .case_result import CaseArtifacts, CaseResult, CaseStatus, normalize_path
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
    "GeometryStatus",
    "HeadlessCaseRunner",
    "HomProxyWeights",
    "ObjectiveConfig",
    "PolarData",
    "ScoreBundle",
    "ScoreWeights",
    "build_default_objective_config",
    "case_result_to_score_inputs",
    "evaluate_objective",
    "emit_optimizer_payload",
    "emit_optimizer_status_json",
    "load_from_optimizer_payload",
    "load_geometry_status",
    "load_polar_data",
    "normalize_path",
    "objective_from_result_bundle",
    "optuna_objective_wrapper",
]


def __getattr__(name: str) -> object:
    """Lazily import heavier runtime helpers only when requested."""
    if name == "HeadlessCaseRunner":
        from .headless_case_runner import HeadlessCaseRunner

        return HeadlessCaseRunner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
