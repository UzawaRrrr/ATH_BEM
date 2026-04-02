"""Headless scoring helpers for Optuna-driven ATH/BEM optimization.

This package stays import-light on purpose: solver-side code may import
submodules such as `optimizer.result_bridge` inside WSL or other headless
Python environments that do not have GUI dependencies like `tkinter`.
"""

from __future__ import annotations

from importlib import import_module


_EXPORTS: dict[str, tuple[str, str]] = {
    "CaseArtifacts": (".case_result", "CaseArtifacts"),
    "CaseResult": (".case_result", "CaseResult"),
    "CaseStatus": (".case_result", "CaseStatus"),
    "normalize_path": (".case_result", "normalize_path"),
    "DerivedDriverConstraints": (".driver_profile", "DerivedDriverConstraints"),
    "DriverProfile": (".driver_profile", "DriverProfile"),
    "ProductConstraints": (".driver_profile", "ProductConstraints"),
    "derive_driver_constraints": (".driver_profile", "derive_driver_constraints"),
    "dump_driver_profile": (".driver_profile", "dump_driver_profile"),
    "load_driver_profile": (".driver_profile", "load_driver_profile"),
    "DesignSpace": (".design_space", "DesignSpace"),
    "DesignVariable": (".design_space", "DesignVariable"),
    "build_default_baseline_recipe": (".design_space", "build_default_baseline_recipe"),
    "build_design_space": (".design_space", "build_design_space"),
    "build_initial_seed_params": (".design_space", "build_initial_seed_params"),
    "FeasibilityIssue": (".feasibility", "FeasibilityIssue"),
    "FeasibilityResult": (".feasibility", "FeasibilityResult"),
    "feasibility_penalty": (".feasibility", "feasibility_penalty"),
    "merge_feasibility_results": (".feasibility", "merge_feasibility_results"),
    "validate_params_against_design_space": (".feasibility", "validate_params_against_design_space"),
    "validate_recipe_against_driver": (".feasibility", "validate_recipe_against_driver"),
    "evaluate_objective": (".objective", "evaluate_objective"),
    "objective_from_result_bundle": (".objective", "objective_from_result_bundle"),
    "optuna_objective_wrapper": (".objective", "optuna_objective_wrapper"),
    "case_result_to_score_inputs": (".result_bridge", "case_result_to_score_inputs"),
    "emit_optimizer_payload": (".result_bridge", "emit_optimizer_payload"),
    "emit_optimizer_status_json": (".result_bridge", "emit_optimizer_status_json"),
    "load_from_optimizer_payload": (".result_bridge", "load_from_optimizer_payload"),
    "load_geometry_status": (".result_bridge", "load_geometry_status"),
    "load_polar_data": (".result_bridge", "load_polar_data"),
    "DEFAULT_COMPONENT_NORMALIZERS": (".score_defaults", "DEFAULT_COMPONENT_NORMALIZERS"),
    "DEFAULT_HOM_PROXY_WEIGHTS": (".score_defaults", "DEFAULT_HOM_PROXY_WEIGHTS"),
    "DEFAULT_SCORE_WEIGHTS": (".score_defaults", "DEFAULT_SCORE_WEIGHTS"),
    "DEFAULT_STAGE_FACTORS": (".score_defaults", "DEFAULT_STAGE_FACTORS"),
    "build_default_objective_config": (".score_defaults", "build_default_objective_config"),
    "GeometryStatus": (".score_types", "GeometryStatus"),
    "HomProxyWeights": (".score_types", "HomProxyWeights"),
    "ObjectiveConfig": (".score_types", "ObjectiveConfig"),
    "PolarData": (".score_types", "PolarData"),
    "ScoreBundle": (".score_types", "ScoreBundle"),
    "ScoreWeights": (".score_types", "ScoreWeights"),
    "HeadlessCaseRunner": (".headless_case_runner", "HeadlessCaseRunner"),
    "StudyEnvironment": (".study_definition", "StudyEnvironment"),
    "HardConstraints": (".study_definition", "HardConstraints"),
    "AcousticTargets": (".study_definition", "AcousticTargets"),
    "GeometryPreferences": (".study_definition", "GeometryPreferences"),
    "SearchPolicy": (".study_definition", "SearchPolicy"),
    "StudyDefinition": (".study_definition", "StudyDefinition"),
    "CanonicalTrialRecipeBuild": (".study_definition", "CanonicalTrialRecipeBuild"),
    "CanonicalTrialRecipeBuilder": (".study_definition", "CanonicalTrialRecipeBuilder"),
    "adapt_legacy_study_inputs": (".study_definition", "adapt_legacy_study_inputs"),
    "build_trial_recipe": (".study_definition", "build_trial_recipe"),
    "PreStudyAuditItem": (".prestudy_audit", "PreStudyAuditItem"),
    "PreStudyAuditResult": (".prestudy_audit", "PreStudyAuditResult"),
    "run_prestudy_audit": (".prestudy_audit", "run_prestudy_audit"),
    "ConflictDecision": (".conflict_policy", "ConflictDecision"),
    "resolve_conflict_policy": (".conflict_policy", "resolve_conflict_policy"),
    "build_preflight_flags": (".conflict_policy", "build_preflight_flags"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> object:
    """Lazily resolve public exports on first access."""
    module_info = _EXPORTS.get(name)
    if module_info is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = module_info
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
