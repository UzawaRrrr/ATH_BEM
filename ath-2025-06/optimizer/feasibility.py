"""Geometry feasibility checks for the optimizer-side preflight layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ath_gui.domain.design_recipe import DesignRecipe

from .design_space import DesignSpace
from .driver_profile import DriverProfile, ProductConstraints, derive_driver_constraints


THROAT_DIAMETER_TOL_MM = 0.2
SHORT_HORN_IS_HARD_FAIL = True
EXTREME_ASPECT_RATIO_SOFT_LIMIT = 2.5
EXTREME_ASPECT_RATIO_HARD_LIMIT = 4.0
SOFT_ASPECT_RATIO_PENALTY = 7.5
COVERAGE_SOFT_EXCESS_DEG = 5.0
COVERAGE_HARD_EXCESS_DEG = 20.0
COVERAGE_SOFT_PENALTY = 6.0
EXIT_ANGLE_SOFT_THRESHOLD_DEG = 15.0
EXIT_ANGLE_SOFT_PENALTY = 4.0
INSTALL_CONFLICT_SOFT_MARGIN_MM = 5.0
INSTALL_CONFLICT_HARD_MARGIN_MM = 0.0
MOUTH_RATIO_HARD_FLOOR = 1.5
HORN_SHORT_SOFT_PENALTY = 12.0
PACKAGING_CONFLICT_SHORT_HORN_SOFT_PENALTY = 18.0


def _clamp_nonnegative(value: float) -> float:
    return max(0.0, float(value))


def _coalesce_numeric(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _append_issue(
    issues: list["FeasibilityIssue"],
    *,
    code: str,
    severity: Literal["hard", "soft"],
    message: str,
    value: Any = None,
    limit: Any = None,
) -> None:
    issues.append(FeasibilityIssue(code=code, severity=severity, message=message, value=value, limit=limit))


@dataclass(slots=True)
class FeasibilityIssue:
    """A single geometry feasibility warning or failure."""

    code: str
    severity: Literal["hard", "soft"]
    message: str
    value: Any | None = None
    limit: Any | None = None


@dataclass(slots=True)
class FeasibilityResult:
    """Aggregated feasibility outcome used before the expensive pipeline."""

    ok: bool
    hard_fail: bool
    soft_penalty: float
    issues: list[FeasibilityIssue]
    derived_metrics: dict[str, float] = field(default_factory=dict)


def merge_feasibility_results(*results: FeasibilityResult) -> FeasibilityResult:
    """Merge multiple feasibility checks into one result."""
    issues: list[FeasibilityIssue] = []
    metrics: dict[str, float] = {}
    soft_penalty = 0.0
    hard_fail = False
    for result in results:
        issues.extend(result.issues)
        metrics.update(result.derived_metrics)
        soft_penalty += float(result.soft_penalty)
        hard_fail = hard_fail or bool(result.hard_fail)
    return FeasibilityResult(
        ok=(not hard_fail),
        hard_fail=hard_fail,
        soft_penalty=soft_penalty,
        issues=issues,
        derived_metrics=metrics,
    )


def _finalize_result(issues: list[FeasibilityIssue], *, soft_penalty: float, metrics: dict[str, float]) -> FeasibilityResult:
    hard_fail = any(issue.severity == "hard" for issue in issues)
    return FeasibilityResult(
        ok=(not hard_fail),
        hard_fail=hard_fail,
        soft_penalty=float(soft_penalty),
        issues=issues,
        derived_metrics=dict(metrics),
    )


def _evaluate_geometry(
    *,
    throat_diameter_mm: float | None,
    mouth_width_mm: float | None,
    mouth_height_mm: float | None,
    mouth_corner_radius_mm: float | None,
    horn_length_mm: float | None,
    coverage_angle_deg: float | None,
    flare_angle_deg: float | None,
    driver_profile: DriverProfile,
    product_constraints: ProductConstraints,
) -> FeasibilityResult:
    issues: list[FeasibilityIssue] = []
    soft_penalty = 0.0
    derived = derive_driver_constraints(driver_profile, product_constraints)
    metrics: dict[str, float] = {}

    throat = _coalesce_numeric(throat_diameter_mm)
    mouth_width = _coalesce_numeric(mouth_width_mm)
    mouth_height = _coalesce_numeric(mouth_height_mm)
    corner_radius = _coalesce_numeric(mouth_corner_radius_mm)
    horn_length = _coalesce_numeric(horn_length_mm)
    coverage = _coalesce_numeric(coverage_angle_deg)
    flare_angle = _coalesce_numeric(flare_angle_deg)

    if throat is not None:
        metrics["throat_diameter_mm"] = throat
    if mouth_width is not None:
        metrics["mouth_width_mm"] = mouth_width
    if mouth_height is not None:
        metrics["mouth_height_mm"] = mouth_height
    if horn_length is not None:
        metrics["horn_length_mm"] = horn_length
    if coverage is not None:
        metrics["coverage_angle_deg"] = coverage

    if driver_profile.throat_diameter_mm is not None and throat is not None:
        expected_throat = float(driver_profile.throat_diameter_mm)
        metrics["throat_delta_mm"] = abs(throat - expected_throat)
        if abs(throat - expected_throat) > THROAT_DIAMETER_TOL_MM:
            _append_issue(
                issues,
                code="throat_mismatch",
                severity="hard",
                message="Recipe throat diameter does not match the fixed driver throat.",
                value=throat,
                limit=expected_throat,
            )

    if mouth_width is not None and derived.min_mouth_width_mm is not None:
        if mouth_width < float(derived.min_mouth_width_mm):
            _append_issue(
                issues,
                code="mouth_width_too_small",
                severity="hard",
                message="Mouth width is below the derived minimum.",
                value=mouth_width,
                limit=derived.min_mouth_width_mm,
            )
    if mouth_height is not None and derived.min_mouth_height_mm is not None:
        if mouth_height < float(derived.min_mouth_height_mm):
            _append_issue(
                issues,
                code="mouth_height_too_small",
                severity="hard",
                message="Mouth height is below the derived minimum.",
                value=mouth_height,
                limit=derived.min_mouth_height_mm,
            )
    if mouth_width is not None and derived.max_mouth_width_mm is not None:
        if mouth_width > float(derived.max_mouth_width_mm):
            _append_issue(
                issues,
                code="mouth_width_too_large",
                severity="hard",
                message="Mouth width exceeds the packaging limit.",
                value=mouth_width,
                limit=derived.max_mouth_width_mm,
            )
    if mouth_height is not None and derived.max_mouth_height_mm is not None:
        if mouth_height > float(derived.max_mouth_height_mm):
            _append_issue(
                issues,
                code="mouth_height_too_large",
                severity="hard",
                message="Mouth height exceeds the packaging limit.",
                value=mouth_height,
                limit=derived.max_mouth_height_mm,
            )

    if corner_radius is not None:
        if corner_radius < 0.0:
            _append_issue(
                issues,
                code="corner_radius_negative",
                severity="hard",
                message="Mouth corner radius must be non-negative.",
                value=corner_radius,
                limit=0.0,
            )
        if mouth_width is not None and mouth_height is not None:
            radius_limit = min(mouth_width, mouth_height) * 0.5
            metrics["corner_radius_limit_mm"] = radius_limit
            if corner_radius > radius_limit:
                _append_issue(
                    issues,
                    code="corner_radius_too_large",
                    severity="hard",
                    message="Corner radius is too large for the current mouth opening.",
                    value=corner_radius,
                    limit=radius_limit,
                )

    if horn_length is not None and derived.min_horn_length_mm is not None and horn_length < float(derived.min_horn_length_mm):
        packaging_conflict = bool(
            derived.max_horn_length_mm is not None
            and float(derived.max_horn_length_mm) < float(derived.min_horn_length_mm)
        )
        severity: Literal["hard", "soft"] = "hard" if SHORT_HORN_IS_HARD_FAIL else "soft"
        if packaging_conflict:
            severity = "soft"
        _append_issue(
            issues,
            code="horn_too_short",
            severity=severity,
            message=(
                "Horn length is shorter than the derived minimum."
                if not packaging_conflict
                else "Horn length is shorter than the derived heuristic minimum, but packaging depth is the limiting constraint."
            ),
            value=horn_length,
            limit=derived.min_horn_length_mm,
        )
        if severity == "soft":
            soft_penalty += PACKAGING_CONFLICT_SHORT_HORN_SOFT_PENALTY if packaging_conflict else HORN_SHORT_SOFT_PENALTY
    if horn_length is not None and derived.max_horn_length_mm is not None and horn_length > float(derived.max_horn_length_mm):
        _append_issue(
            issues,
            code="horn_too_deep",
            severity="hard",
            message="Horn length exceeds the product max depth.",
            value=horn_length,
            limit=derived.max_horn_length_mm,
        )

    if mouth_width is not None and mouth_height is not None and mouth_width > 0.0 and mouth_height > 0.0:
        aspect_ratio = max(mouth_width / mouth_height, mouth_height / mouth_width)
        metrics["mouth_aspect_ratio"] = aspect_ratio
        if aspect_ratio > EXTREME_ASPECT_RATIO_SOFT_LIMIT:
            _append_issue(
                issues,
                code="aspect_ratio_unreasonable",
                severity="soft",
                message="Mouth aspect ratio is unusually extreme.",
                value=aspect_ratio,
                limit=EXTREME_ASPECT_RATIO_SOFT_LIMIT,
            )
            soft_penalty += SOFT_ASPECT_RATIO_PENALTY * min(aspect_ratio / EXTREME_ASPECT_RATIO_SOFT_LIMIT, EXTREME_ASPECT_RATIO_HARD_LIMIT)

    if coverage is not None and driver_profile.preferred_max_coverage_deg is not None:
        preferred_max = float(driver_profile.preferred_max_coverage_deg)
        coverage_excess = coverage - preferred_max
        metrics["coverage_excess_deg"] = max(0.0, coverage_excess)
        if coverage_excess > COVERAGE_HARD_EXCESS_DEG:
            _append_issue(
                issues,
                code="coverage_too_large_hard",
                severity="hard",
                message="Coverage request exceeds the driver preference by too much.",
                value=coverage,
                limit=preferred_max,
            )
        elif coverage_excess > COVERAGE_SOFT_EXCESS_DEG:
            _append_issue(
                issues,
                code="coverage_too_large_soft",
                severity="soft",
                message="Coverage request is above the driver's preferred range.",
                value=coverage,
                limit=preferred_max,
            )
            soft_penalty += COVERAGE_SOFT_PENALTY * (coverage_excess / COVERAGE_SOFT_EXCESS_DEG)

    if driver_profile.exit_angle_deg is not None and flare_angle is not None:
        exit_delta = abs(float(driver_profile.exit_angle_deg) - flare_angle)
        metrics["exit_angle_delta_deg"] = exit_delta
        if exit_delta > EXIT_ANGLE_SOFT_THRESHOLD_DEG:
            _append_issue(
                issues,
                code="exit_continuity_proxy",
                severity="soft",
                message="Flare angle differs significantly from the driver exit angle.",
                value=flare_angle,
                limit=driver_profile.exit_angle_deg,
            )
            soft_penalty += EXIT_ANGLE_SOFT_PENALTY * (exit_delta / EXIT_ANGLE_SOFT_THRESHOLD_DEG)

    if throat is not None and mouth_width is not None and mouth_height is not None and throat > 0.0:
        mouth_to_throat_ratio = min(mouth_width, mouth_height) / throat
        metrics["mouth_to_throat_ratio"] = mouth_to_throat_ratio
        required_ratio = max(MOUTH_RATIO_HARD_FLOOR, float(driver_profile.preferred_min_mouth_to_throat_ratio) * 0.90)
        if mouth_to_throat_ratio < required_ratio:
            _append_issue(
                issues,
                code="mouth_to_throat_ratio_too_low",
                severity="hard",
                message="Mouth-to-throat ratio is too low for a viable expansion.",
                value=mouth_to_throat_ratio,
                limit=required_ratio,
            )

    if mouth_width is not None and mouth_height is not None:
        install_clearance = min(mouth_width, mouth_height)
        flange_limit = _coalesce_numeric(driver_profile.mounting_flange_diameter_mm)
        outer_limit = _coalesce_numeric(driver_profile.max_outer_diameter_mm)
        for label, limit in (("mounting_flange", flange_limit), ("outer_diameter", outer_limit)):
            if limit is None:
                continue
            metrics[f"{label}_clearance_mm"] = install_clearance - limit
            if install_clearance < (limit + INSTALL_CONFLICT_HARD_MARGIN_MM):
                _append_issue(
                    issues,
                    code=f"{label}_install_conflict_hard",
                    severity="hard",
                    message=f"Mouth opening is smaller than the driver {label} proxy limit.",
                    value=install_clearance,
                    limit=limit,
                )
            elif install_clearance < (limit + INSTALL_CONFLICT_SOFT_MARGIN_MM):
                _append_issue(
                    issues,
                    code=f"{label}_install_conflict_soft",
                    severity="soft",
                    message=f"Mouth opening leaves little clearance around the driver {label} proxy limit.",
                    value=install_clearance,
                    limit=limit + INSTALL_CONFLICT_SOFT_MARGIN_MM,
                )
                soft_penalty += 5.0

    return _finalize_result(issues, soft_penalty=soft_penalty, metrics=metrics)


def validate_recipe_against_driver(
    recipe: DesignRecipe,
    driver_profile: DriverProfile,
    product_constraints: ProductConstraints | None = None,
) -> FeasibilityResult:
    """Validate a concrete `DesignRecipe` against driver and product limits."""
    constraints = product_constraints or ProductConstraints()
    flare_angle = None
    if isinstance(recipe.ath_overrides, dict):
        raw_flare_angle = recipe.ath_overrides.get("Flare.Angle")
        if raw_flare_angle is not None:
            flare_angle = float(raw_flare_angle)
    return _evaluate_geometry(
        throat_diameter_mm=recipe.throat_diameter,
        mouth_width_mm=recipe.mouth_width,
        mouth_height_mm=recipe.mouth_height,
        mouth_corner_radius_mm=recipe.mouth_corner_radius,
        horn_length_mm=recipe.horn_length,
        coverage_angle_deg=recipe.coverage_angle,
        flare_angle_deg=flare_angle,
        driver_profile=driver_profile,
        product_constraints=constraints,
    )


def validate_params_against_design_space(params: dict[str, Any], design_space: DesignSpace) -> FeasibilityResult:
    """Validate decoded params against explicit design-space bounds and geometry."""
    issues: list[FeasibilityIssue] = []
    metrics: dict[str, float] = {}
    merged_params = {name: variable.fixed_value for name, variable in design_space.fixed_variables().items()}
    merged_params.update(dict(params))

    for name, variable in design_space.active_variables().items():
        if variable.kind != "fixed" and name not in merged_params:
            _append_issue(
                issues,
                code=f"missing_{name}",
                severity="hard",
                message="Active design-space variable is missing from params.",
                value=name,
            )

    for name, value in merged_params.items():
        variable = design_space.variables.get(name)
        if variable is None:
            continue
        if variable.kind == "fixed":
            if variable.fixed_value is not None and value != variable.fixed_value:
                _append_issue(
                    issues,
                    code=f"fixed_{name}_mismatch",
                    severity="hard",
                    message="Fixed design-space variable was overridden.",
                    value=value,
                    limit=variable.fixed_value,
                )
            continue
        if variable.kind == "categorical":
            if value not in list(variable.choices or []):
                _append_issue(
                    issues,
                    code=f"categorical_{name}_invalid",
                    severity="hard",
                    message="Categorical value is not allowed by the design space.",
                    value=value,
                    limit=list(variable.choices or []),
                )
            continue
        if variable.low is not None and float(value) < float(variable.low):
            _append_issue(
                issues,
                code=f"{name}_below_bound",
                severity="hard",
                message="Parameter is below the design-space lower bound.",
                value=value,
                limit=variable.low,
            )
        if variable.high is not None and float(value) > float(variable.high):
            _append_issue(
                issues,
                code=f"{name}_above_bound",
                severity="hard",
                message="Parameter is above the design-space upper bound.",
                value=value,
                limit=variable.high,
            )
        metrics[f"{name}"] = float(value)

    geometry_result = _evaluate_geometry(
        throat_diameter_mm=merged_params.get("throat_diameter"),
        mouth_width_mm=merged_params.get("mouth_width"),
        mouth_height_mm=merged_params.get("mouth_height"),
        mouth_corner_radius_mm=merged_params.get("mouth_corner_radius"),
        horn_length_mm=merged_params.get("horn_length"),
        coverage_angle_deg=merged_params.get("coverage_angle"),
        flare_angle_deg=merged_params.get("flare_angle_deg"),
        driver_profile=design_space.driver_profile,
        product_constraints=design_space.product_constraints,
    )
    bounds_result = _finalize_result(issues, soft_penalty=0.0, metrics=metrics)
    return merge_feasibility_results(bounds_result, geometry_result)


def feasibility_penalty(
    result: FeasibilityResult,
    catastrophic_score: float,
    soft_scale: float = 1.0,
) -> float:
    """Convert feasibility issues into a scalar pre-score penalty."""
    base = float(catastrophic_score) if result.hard_fail else 0.0
    return base + (_clamp_nonnegative(result.soft_penalty) * float(soft_scale))
