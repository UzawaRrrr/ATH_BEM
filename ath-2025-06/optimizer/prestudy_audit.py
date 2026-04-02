"""Pre-study audit for semantic study-definition inputs.

The goal of this layer is to detect empty or internally contradictory
constraint sets before Optuna starts sampling trials. That keeps users from
seeing `trial 1 catastrophic` when the study definition was already impossible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .conflict_policy import resolve_conflict_policy
from .design_space import DesignSpace, build_initial_seed_params
from .driver_profile import DerivedDriverConstraints, DriverProfile, ProductConstraints, is_recipe_inferred_constraints
from .feasibility import THROAT_DIAMETER_TOL_MM, merge_feasibility_results, validate_params_against_design_space, validate_recipe_against_driver
from .study_definition import CanonicalTrialRecipeBuilder, StudyDefinition


@dataclass(slots=True)
class PreStudyAuditItem:
    """One structured audit warning or conflict."""

    code: str
    severity: Literal["warning", "conflict"]
    message: str
    value: Any | None = None
    limit: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary representation."""
        return asdict(self)


@dataclass(slots=True)
class PreStudyAuditResult:
    """Structured pre-study audit result used before `study.optimize()`."""

    passed: bool
    warnings: list[PreStudyAuditItem]
    conflicts: list[PreStudyAuditItem]
    derived_constraint_summary: dict[str, Any] = field(default_factory=dict)
    constraints_are_inferred_fallback: bool = False
    constraint_strategy: str = ""
    canonical_seed_preview: dict[str, Any] = field(default_factory=dict)
    canonical_seed_sources: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary representation."""
        return {
            "passed": bool(self.passed),
            "warnings": [item.to_dict() for item in self.warnings],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "derived_constraint_summary": dict(self.derived_constraint_summary),
            "constraints_are_inferred_fallback": bool(self.constraints_are_inferred_fallback),
            "constraint_strategy": str(self.constraint_strategy),
            "canonical_seed_preview": dict(self.canonical_seed_preview),
            "canonical_seed_sources": dict(self.canonical_seed_sources),
        }


def _append_item(
    target: list[PreStudyAuditItem],
    *,
    code: str,
    severity: Literal["warning", "conflict"],
    message: str,
    value: Any = None,
    limit: Any = None,
) -> None:
    target.append(
        PreStudyAuditItem(
            code=code,
            severity=severity,
            message=message,
            value=value,
            limit=limit,
        )
    )


def _derived_summary(derived: DerivedDriverConstraints) -> dict[str, Any]:
    return {
        "fixed_throat_diameter_mm": derived.fixed_throat_diameter_mm,
        "min_mouth_width_mm": derived.min_mouth_width_mm,
        "min_mouth_height_mm": derived.min_mouth_height_mm,
        "max_mouth_width_mm": derived.max_mouth_width_mm,
        "max_mouth_height_mm": derived.max_mouth_height_mm,
        "min_horn_length_mm": derived.min_horn_length_mm,
        "max_horn_length_mm": derived.max_horn_length_mm,
        "max_corner_radius_mm": derived.max_corner_radius_mm,
        "recommended_coverage_h_range_deg": derived.recommended_coverage_h_range_deg,
        "recommended_coverage_v_range_deg": derived.recommended_coverage_v_range_deg,
        "notes": list(derived.notes),
    }


def run_prestudy_audit(
    *,
    study_definition: StudyDefinition,
    driver_profile: DriverProfile,
    product_constraints: ProductConstraints,
    derived_constraints: DerivedDriverConstraints,
    design_space: DesignSpace,
    canonical_recipe_builder: CanonicalTrialRecipeBuilder,
    stage: str,
    constraint_strategy: str,
) -> PreStudyAuditResult:
    """Audit constraint consistency and canonical seed feasibility before trials.

    Explicit constraints fail fast when they define an empty feasible set.
    Recipe-inferred fallback constraints are treated more gently: the audit
    still records them clearly, and coarse-stage relaxed strategies may pass
    with warnings as long as the effective canonical seed remains feasible.
    """
    warnings: list[PreStudyAuditItem] = []
    conflicts: list[PreStudyAuditItem] = []
    inferred_fallback = is_recipe_inferred_constraints(product_constraints)
    stage_name = str(stage).strip().lower()
    inferred_decision = resolve_conflict_policy(
        "inferred_constraints",
        stage=stage_name,
        constraints_are_inferred_fallback=inferred_fallback,
    )

    if inferred_fallback:
        _append_item(
            warnings,
            code="inferred_constraints_fallback",
            severity="warning",
            message="This study is using recipe-derived fallback constraints; explicit production constraints are recommended.",
            value=constraint_strategy,
        )
    if "relaxed" in str(constraint_strategy):
        _append_item(
            warnings,
            code="inferred_constraints_relaxed",
            severity="warning",
            message="Coarse-stage inferred constraints were relaxed before optimization to avoid over-constraining the search space.",
            value=constraint_strategy,
        )

    if (
        derived_constraints.fixed_throat_diameter_mm is not None
        and driver_profile.throat_diameter_mm is not None
        and abs(float(derived_constraints.fixed_throat_diameter_mm) - float(driver_profile.throat_diameter_mm)) > THROAT_DIAMETER_TOL_MM
    ):
        _append_item(
            conflicts,
            code="fixed_throat_driver_conflict",
            severity="conflict",
            message="HardConstraints fixed throat conflicts with the driver profile throat.",
            value=derived_constraints.fixed_throat_diameter_mm,
            limit=driver_profile.throat_diameter_mm,
        )

    for code, minimum, maximum, label in (
        ("mouth_width_empty", derived_constraints.min_mouth_width_mm, derived_constraints.max_mouth_width_mm, "mouth width"),
        ("mouth_height_empty", derived_constraints.min_mouth_height_mm, derived_constraints.max_mouth_height_mm, "mouth height"),
        ("horn_length_empty", derived_constraints.min_horn_length_mm, derived_constraints.max_horn_length_mm, "horn length"),
    ):
        if minimum is None or maximum is None:
            continue
        if float(minimum) > float(maximum):
            kind = "horn_length_vs_max_depth" if code == "horn_length_empty" else "mouth_vs_packaging"
            decision = resolve_conflict_policy(
                kind,  # type: ignore[arg-type]
                stage=stage_name,
                constraints_are_inferred_fallback=inferred_fallback,
            )
            target = warnings if decision.strategy == "relax_coarse_only" else conflicts
            severity: Literal["warning", "conflict"] = "warning" if target is warnings else "conflict"
            _append_item(
                target,
                code=code,
                severity=severity,
                message=f"Derived {label} constraints define an empty feasible interval.",
                value=minimum,
                limit=maximum,
            )

    for code, limit, label in (
        ("max_baffle_width_invalid", product_constraints.max_baffle_width_mm, "max_baffle_width_mm"),
        ("max_baffle_height_invalid", product_constraints.max_baffle_height_mm, "max_baffle_height_mm"),
        ("max_depth_invalid", product_constraints.max_depth_mm, "max_depth_mm"),
    ):
        if limit is not None and float(limit) <= 0.0:
            _append_item(
                conflicts,
                code=code,
                severity="conflict",
                message=f"Hard packaging limit `{label}` must be positive when provided.",
                value=limit,
                limit=0.0,
            )

    for label, packaging_limit, install_limit in (
        ("width", product_constraints.max_baffle_width_mm, driver_profile.mounting_flange_diameter_mm or driver_profile.max_outer_diameter_mm),
        ("height", product_constraints.max_baffle_height_mm, driver_profile.mounting_flange_diameter_mm or driver_profile.max_outer_diameter_mm),
    ):
        if packaging_limit is None or install_limit is None:
            continue
        if float(packaging_limit) <= float(install_limit):
            _append_item(
                conflicts,
                code=f"packaging_{label}_install_impossible",
                severity="conflict",
                message=f"Hard packaging {label} limit is smaller than the driver install clearance proxy.",
                value=packaging_limit,
                limit=install_limit,
            )

    seed_params = build_initial_seed_params(driver_profile, product_constraints, base_recipe=canonical_recipe_builder.base_template)
    seed_build = canonical_recipe_builder.build(seed_params)
    seed_recipe = seed_build.recipe
    params_feasibility = validate_params_against_design_space(seed_params, design_space, conflict_stage=stage_name)
    recipe_feasibility = validate_recipe_against_driver(seed_recipe, driver_profile, product_constraints, conflict_stage=stage_name)
    seed_feasibility = merge_feasibility_results(params_feasibility, recipe_feasibility)

    if seed_feasibility.hard_fail:
        target = warnings if inferred_decision.strategy == "relax_coarse_only" else conflicts
        severity = "warning" if target is warnings else "conflict"
        issue_codes = [issue.code for issue in seed_feasibility.issues if issue.severity == "hard"]
        _append_item(
            target,
            code="canonical_seed_infeasible",
            severity=severity,
            message="Canonical seed recipe fails basic preflight feasibility.",
            value=issue_codes,
        )
    elif seed_feasibility.soft_penalty > 0.0:
        _append_item(
            warnings,
            code="canonical_seed_soft_penalty",
            severity="warning",
            message="Canonical seed recipe is feasible but already carries soft feasibility penalties.",
            value=seed_feasibility.soft_penalty,
        )

    passed = not conflicts
    return PreStudyAuditResult(
        passed=passed,
        warnings=warnings,
        conflicts=conflicts,
        derived_constraint_summary=_derived_summary(derived_constraints),
        constraints_are_inferred_fallback=inferred_fallback,
        constraint_strategy=str(constraint_strategy),
        canonical_seed_preview=seed_recipe.to_dict(),
        canonical_seed_sources=dict(seed_build.source_summary),
    )
