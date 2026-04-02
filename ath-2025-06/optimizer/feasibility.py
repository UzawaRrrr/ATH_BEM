"""Geometry feasibility checks for the optimizer-side preflight layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

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
OSSE_SAMPLE_COUNT = 96
OSSE_Q_RANGE = (0.96, 0.999)
OSSE_S_RANGE = (0.50, 0.85)
OSSE_N_RANGE = (3.0, 6.0)
OSSE_K_RANGE = (0.80, 1.25)
OSSE_MIN_TERMINAL_RATIO_HARD = 1.20
OSSE_MAX_TERMINAL_RATIO_SOFT = 4.25
OSSE_MAX_TERMINAL_RATIO_HARD = 5.25
OSSE_MAX_SLOPE_SOFT_DEG = 30.0
OSSE_MAX_SLOPE_HARD_DEG = 45.0
OSSE_MIN_SLOPE_SOFT_DEG = 1.0
OSSE_CURVATURE_SOFT_LIMIT = 0.16
OSSE_CURVATURE_HARD_LIMIT = 0.28
OSSE_EXIT_DELTA_SOFT_DEG = 12.0
OSSE_EXIT_DELTA_HARD_DEG = 22.0
OSSE_STEEP_SLOPE_SOFT_PENALTY = 8.0
OSSE_CURVATURE_SOFT_PENALTY = 7.0
OSSE_EXIT_DELTA_SOFT_PENALTY = 4.5
OSSE_TERMINAL_RATIO_SOFT_PENALTY = 5.5
OSSE_FLAT_SLOPE_SOFT_PENALTY = 3.0


def _clamp_nonnegative(value: float) -> float:
    return max(0.0, float(value))


def _coalesce_numeric(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _is_finite_number(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except Exception:
        return False


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


def _extract_osse_inputs(ath_overrides: dict[str, Any] | None) -> dict[str, float] | None:
    """Extract OS-SE core terms from `ath_overrides`, filling missing values with stable defaults."""
    payload = dict(ath_overrides or {})
    keys_present = {"Term.s", "Term.q", "Term.n", "OS.k"}.intersection(payload)
    if not keys_present:
        return None
    defaults = {
        "Term.s": 0.7,
        "Term.q": 0.995,
        "Term.n": 4.0,
        "OS.k": 1.0,
    }
    result: dict[str, float] = {}
    for key, default in defaults.items():
        raw_value = payload.get(key, default)
        result[key] = float(raw_value)
    return result


def _evaluate_osse_geometry(
    *,
    osse_inputs: dict[str, float] | None,
    throat_diameter_mm: float | None,
    horn_length_mm: float | None,
    coverage_angle_deg: float | None,
    driver_profile: DriverProfile,
    product_constraints: ProductConstraints,
) -> FeasibilityResult:
    """Evaluate a stable OS-SE proxy profile for monotonicity, slope, and terminal behavior.

    The proxy here is intentionally approximate. It does not try to reconstruct
    ATH's full internal OS-SE implementation; instead it builds a smooth,
    normalized expansion curve from `Term.s`, `Term.q`, `Term.n`, and `OS.k`
    and derives robust safety proxies such as monotonic expansion, equivalent
    terminal ratio, throat slope, and curvature. The goal is early rejection of
    numerically unstable or obviously implausible OS-SE combinations before the
    expensive mesh/BEM pipeline starts.
    """
    if osse_inputs is None:
        return FeasibilityResult(ok=True, hard_fail=False, soft_penalty=0.0, issues=[], derived_metrics={})

    issues: list[FeasibilityIssue] = []
    soft_penalty = 0.0
    metrics: dict[str, float] = {}

    throat = _coalesce_numeric(throat_diameter_mm)
    horn_length = _coalesce_numeric(horn_length_mm)
    coverage = _coalesce_numeric(coverage_angle_deg)
    if throat is None or horn_length is None or horn_length <= 0.0:
        _append_issue(
            issues,
            code="osse_missing_base_geometry",
            severity="hard",
            message="OS-SE proxy evaluation requires finite throat diameter and horn length.",
            value={"throat_diameter_mm": throat, "horn_length_mm": horn_length},
        )
        metrics["osse_valid"] = 0.0
        metrics["osse_monotonic_ok"] = 0.0
        return _finalize_result(issues, soft_penalty=soft_penalty, metrics=metrics)

    term_s = float(osse_inputs["Term.s"])
    term_q = float(osse_inputs["Term.q"])
    term_n = float(osse_inputs["Term.n"])
    os_k = float(osse_inputs["OS.k"])
    metrics["osse_term_s"] = term_s
    metrics["osse_term_q"] = term_q
    metrics["osse_term_n"] = term_n
    metrics["osse_os_k"] = os_k

    for name, value, limits in (
        ("Term.s", term_s, OSSE_S_RANGE),
        ("Term.q", term_q, OSSE_Q_RANGE),
        ("Term.n", term_n, OSSE_N_RANGE),
        ("OS.k", os_k, OSSE_K_RANGE),
    ):
        if not _is_finite_number(value):
            _append_issue(
                issues,
                code="osse_nonfinite_input",
                severity="hard",
                message=f"OS-SE parameter {name} is not finite.",
                value=value,
            )
        elif float(value) < float(limits[0]) or float(value) > float(limits[1]):
            _append_issue(
                issues,
                code="osse_parameter_out_of_range",
                severity="hard",
                message=f"OS-SE parameter {name} is outside the stable proxy range.",
                value=value,
                limit=limits,
            )
    if issues:
        metrics["osse_valid"] = 0.0
        metrics["osse_monotonic_ok"] = 0.0
        return _finalize_result(issues, soft_penalty=soft_penalty, metrics=metrics)

    throat_radius = throat * 0.5
    coverage_ref = max(30.0, coverage if coverage is not None else 90.0)
    q_softness = np.clip((term_q - OSSE_Q_RANGE[0]) / max(OSSE_Q_RANGE[1] - OSSE_Q_RANGE[0], 1.0e-9), 0.0, 1.0)
    coverage_factor = np.clip(110.0 / coverage_ref, 0.75, 2.40)
    shape_gain = (
        1.0
        + 0.55 * ((term_s - OSSE_S_RANGE[0]) / (OSSE_S_RANGE[1] - OSSE_S_RANGE[0]))
        + 0.20 * ((term_n - OSSE_N_RANGE[0]) / (OSSE_N_RANGE[1] - OSSE_N_RANGE[0]))
        + 0.30 * q_softness
    )
    terminal_ratio = max(1.05, os_k * coverage_factor * shape_gain)
    terminal_diameter = throat * terminal_ratio
    delta_radius = max(0.0, terminal_diameter * 0.5 - throat_radius)

    u = np.linspace(0.0, 1.0, OSSE_SAMPLE_COUNT, dtype=float)
    blend = term_s * u + (1.0 - term_s) * np.power(u, max(term_n, 1.0e-9))
    q_exponent = 1.0 + 2.5 * (1.0 - q_softness)
    curve = q_softness * blend + (1.0 - q_softness) * np.power(np.clip(blend, 0.0, 1.0), q_exponent)
    radius_profile = throat_radius + (delta_radius * curve)
    axial_mm = u * horn_length

    if not bool(np.all(np.isfinite(radius_profile))) or not bool(np.all(np.isfinite(axial_mm))):
        _append_issue(
            issues,
            code="osse_invalid_profile",
            severity="hard",
            message="OS-SE proxy sampling generated non-finite geometry.",
        )
        metrics["osse_valid"] = 0.0
        metrics["osse_monotonic_ok"] = 0.0
        return _finalize_result(issues, soft_penalty=soft_penalty, metrics=metrics)

    radial_delta = np.diff(radius_profile)
    monotonic_ok = bool(np.all(radial_delta >= -1.0e-6))
    min_delta = float(np.min(radial_delta)) if radial_delta.size else 0.0
    if not monotonic_ok:
        _append_issue(
            issues,
            code="osse_non_monotonic",
            severity="hard",
            message="OS-SE proxy profile is not monotonically expanding.",
            value=min_delta,
            limit=0.0,
        )

    dr_dx = np.gradient(radius_profile, axial_mm)
    d2r_dx2 = np.gradient(dr_dx, axial_mm)
    if not bool(np.all(np.isfinite(dr_dx))) or not bool(np.all(np.isfinite(d2r_dx2))):
        _append_issue(
            issues,
            code="osse_invalid_derivatives",
            severity="hard",
            message="OS-SE proxy derivatives are not finite.",
        )

    throat_slice = max(6, OSSE_SAMPLE_COUNT // 10)
    throat_slope = float(np.polyfit(axial_mm[:throat_slice], radius_profile[:throat_slice], 1)[0])
    throat_slope_deg = float(np.degrees(np.arctan(max(0.0, throat_slope))))
    max_slope_deg = float(np.degrees(np.arctan(max(0.0, float(np.max(dr_dx))))))
    curvature_proxy = float(np.max(np.abs(d2r_dx2)) * horn_length / max(delta_radius, 1.0e-6)) if delta_radius > 0.0 else 0.0

    metrics["osse_valid"] = 1.0 if not any(issue.severity == "hard" for issue in issues) else 0.0
    metrics["osse_monotonic_ok"] = 1.0 if monotonic_ok else 0.0
    metrics["osse_min_delta_mm"] = min_delta
    metrics["osse_throat_slope_proxy_deg"] = throat_slope_deg
    metrics["osse_max_slope_proxy_deg"] = max_slope_deg
    metrics["osse_terminal_proxy_mm"] = terminal_diameter
    metrics["osse_terminal_ratio"] = terminal_ratio
    metrics["osse_curvature_proxy"] = curvature_proxy

    if terminal_ratio < OSSE_MIN_TERMINAL_RATIO_HARD:
        _append_issue(
            issues,
            code="osse_terminal_ratio_too_low",
            severity="hard",
            message="OS-SE terminal proxy is too close to the throat and risks a degenerate expansion.",
            value=terminal_ratio,
            limit=OSSE_MIN_TERMINAL_RATIO_HARD,
        )
    elif terminal_ratio > OSSE_MAX_TERMINAL_RATIO_HARD:
        _append_issue(
            issues,
            code="osse_terminal_ratio_too_high",
            severity="hard",
            message="OS-SE terminal proxy is implausibly aggressive for a stable first-stage search.",
            value=terminal_ratio,
            limit=OSSE_MAX_TERMINAL_RATIO_HARD,
        )
    elif terminal_ratio > OSSE_MAX_TERMINAL_RATIO_SOFT:
        _append_issue(
            issues,
            code="osse_terminal_ratio_high_soft",
            severity="soft",
            message="OS-SE terminal proxy is very aggressive and may be difficult to realize.",
            value=terminal_ratio,
            limit=OSSE_MAX_TERMINAL_RATIO_SOFT,
        )
        soft_penalty += OSSE_TERMINAL_RATIO_SOFT_PENALTY * min(terminal_ratio / OSSE_MAX_TERMINAL_RATIO_SOFT, 1.5)

    if max_slope_deg > OSSE_MAX_SLOPE_HARD_DEG:
        _append_issue(
            issues,
            code="osse_slope_too_steep",
            severity="hard",
            message="OS-SE proxy flare becomes too steep for a stable geometry.",
            value=max_slope_deg,
            limit=OSSE_MAX_SLOPE_HARD_DEG,
        )
    elif max_slope_deg > OSSE_MAX_SLOPE_SOFT_DEG:
        _append_issue(
            issues,
            code="osse_slope_steep_soft",
            severity="soft",
            message="OS-SE proxy flare is steeper than the preferred stable region.",
            value=max_slope_deg,
            limit=OSSE_MAX_SLOPE_SOFT_DEG,
        )
        soft_penalty += OSSE_STEEP_SLOPE_SOFT_PENALTY * min(max_slope_deg / OSSE_MAX_SLOPE_SOFT_DEG, 1.5)
    elif max_slope_deg < OSSE_MIN_SLOPE_SOFT_DEG and terminal_ratio < 1.45:
        _append_issue(
            issues,
            code="osse_profile_too_flat_soft",
            severity="soft",
            message="OS-SE proxy flare is very flat and may not deliver meaningful expansion.",
            value=max_slope_deg,
            limit=OSSE_MIN_SLOPE_SOFT_DEG,
        )
        soft_penalty += OSSE_FLAT_SLOPE_SOFT_PENALTY

    if curvature_proxy > OSSE_CURVATURE_HARD_LIMIT:
        _append_issue(
            issues,
            code="osse_curvature_too_high",
            severity="hard",
            message="OS-SE proxy curvature is too sharp for a stable numerical profile.",
            value=curvature_proxy,
            limit=OSSE_CURVATURE_HARD_LIMIT,
        )
    elif curvature_proxy > OSSE_CURVATURE_SOFT_LIMIT:
        _append_issue(
            issues,
            code="osse_curvature_high_soft",
            severity="soft",
            message="OS-SE proxy curvature is higher than the preferred stable region.",
            value=curvature_proxy,
            limit=OSSE_CURVATURE_SOFT_LIMIT,
        )
        soft_penalty += OSSE_CURVATURE_SOFT_PENALTY * min(curvature_proxy / OSSE_CURVATURE_SOFT_LIMIT, 1.5)

    if driver_profile.exit_angle_deg is not None:
        exit_delta = abs(float(driver_profile.exit_angle_deg) - throat_slope_deg)
        metrics["osse_exit_angle_delta_deg"] = exit_delta
        if exit_delta > OSSE_EXIT_DELTA_HARD_DEG:
            _append_issue(
                issues,
                code="osse_exit_continuity_hard",
                severity="hard",
                message="OS-SE throat slope proxy is too far from the driver exit angle.",
                value=throat_slope_deg,
                limit=driver_profile.exit_angle_deg,
            )
        elif exit_delta > OSSE_EXIT_DELTA_SOFT_DEG:
            _append_issue(
                issues,
                code="osse_exit_continuity_soft",
                severity="soft",
                message="OS-SE throat slope proxy departs from the preferred driver exit continuity.",
                value=throat_slope_deg,
                limit=driver_profile.exit_angle_deg,
            )
            soft_penalty += OSSE_EXIT_DELTA_SOFT_PENALTY * min(exit_delta / OSSE_EXIT_DELTA_SOFT_DEG, 1.5)

    metrics["osse_valid"] = 1.0 if not any(issue.severity == "hard" for issue in issues) else 0.0
    return _finalize_result(issues, soft_penalty=soft_penalty, metrics=metrics)


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
    osse_inputs = None
    if isinstance(recipe.ath_overrides, dict):
        raw_flare_angle = recipe.ath_overrides.get("Flare.Angle")
        if raw_flare_angle is not None:
            flare_angle = float(raw_flare_angle)
        osse_inputs = _extract_osse_inputs(recipe.ath_overrides)
    base_result = _evaluate_geometry(
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
    osse_result = _evaluate_osse_geometry(
        osse_inputs=osse_inputs,
        throat_diameter_mm=recipe.throat_diameter,
        horn_length_mm=recipe.horn_length,
        coverage_angle_deg=recipe.coverage_angle,
        driver_profile=driver_profile,
        product_constraints=constraints,
    )
    return merge_feasibility_results(base_result, osse_result)


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
