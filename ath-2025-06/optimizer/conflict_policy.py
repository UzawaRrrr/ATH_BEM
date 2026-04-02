"""Centralized conflict-policy decisions for optimizer preflight and study setup."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Literal


ConflictStrategy = Literal["fail_fast", "relax_coarse_only", "cap_and_soft_penalize"]
ConflictKind = Literal[
    "horn_length_vs_max_depth",
    "mouth_vs_packaging",
    "inferred_constraints",
    "osse_proxy_out_of_range",
    "mode_conflict",
]


@dataclass(slots=True)
class ConflictDecision:
    """Resolved conflict strategy for a specific conflict kind and stage."""

    kind: ConflictKind
    strategy: ConflictStrategy
    stage: str
    constraints_are_inferred_fallback: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation of the decision."""
        return asdict(self)


def _normalize_stage(stage: str | None) -> str:
    text = str(stage or "final").strip().lower()
    return text or "final"


def resolve_conflict_policy(
    kind: ConflictKind,
    *,
    stage: str | None,
    constraints_are_inferred_fallback: bool,
) -> ConflictDecision:
    """Resolve conflict handling into a single policy decision.

    Rules for v1.1.10:
    - explicit hard constraints => `fail_fast`
    - inferred fallback + coarse => `relax_coarse_only` or `cap_and_soft_penalize`
    - refine/final => strict again
    - geometries that can still be explored under a capped window use
      `cap_and_soft_penalize`
    """
    stage_name = _normalize_stage(stage)
    if kind == "inferred_constraints":
        if constraints_are_inferred_fallback and stage_name == "coarse":
            return ConflictDecision(kind, "relax_coarse_only", stage_name, constraints_are_inferred_fallback, "recipe_inferred_coarse_relax")
        return ConflictDecision(kind, "fail_fast", stage_name, constraints_are_inferred_fallback, "strict_constraints_outside_coarse")

    if kind == "horn_length_vs_max_depth":
        if constraints_are_inferred_fallback and stage_name == "coarse":
            return ConflictDecision(kind, "cap_and_soft_penalize", stage_name, constraints_are_inferred_fallback, "coarse_inferred_horn_depth_conflict")
        return ConflictDecision(kind, "fail_fast", stage_name, constraints_are_inferred_fallback, "strict_horn_depth_conflict")

    if kind == "mouth_vs_packaging":
        if constraints_are_inferred_fallback and stage_name == "coarse":
            return ConflictDecision(kind, "relax_coarse_only", stage_name, constraints_are_inferred_fallback, "coarse_inferred_mouth_packaging_conflict")
        return ConflictDecision(kind, "fail_fast", stage_name, constraints_are_inferred_fallback, "strict_mouth_packaging_conflict")

    if kind == "osse_proxy_out_of_range":
        return ConflictDecision(kind, "fail_fast", stage_name, constraints_are_inferred_fallback, "unstable_osse_proxy")

    if kind == "mode_conflict":
        return ConflictDecision(kind, "fail_fast", stage_name, constraints_are_inferred_fallback, "unsupported_mode_combination")

    return ConflictDecision(kind, "fail_fast", stage_name, constraints_are_inferred_fallback, "default_fail_fast")


def is_missing_required_param_issue(code: str) -> bool:
    """Return whether an issue code means required input is missing."""
    text = str(code).strip()
    return text.startswith("missing_")


def is_constraint_conflict_issue(code: str) -> bool:
    """Return whether an issue code represents a constraint or mode conflict."""
    text = str(code).strip()
    if not text or is_missing_required_param_issue(text):
        return False
    if text.endswith("_above_bound") or text.endswith("_below_bound"):
        return True
    if text.startswith("fixed_") or text.startswith("categorical_"):
        return True
    prefixes = (
        "throat_",
        "mouth_",
        "horn_",
        "coverage_",
        "aspect_",
        "osse_",
        "mounting_flange_",
        "outer_diameter_",
        "flare_",
        "gcurve_",
        "mode_",
    )
    return text.startswith(prefixes)


def build_preflight_flags(*, hard_fail: bool, issues: Iterable[Any]) -> dict[str, bool]:
    """Build clear preflight flags from feasibility issues."""
    codes: list[str] = []
    for issue in issues:
        if isinstance(issue, dict):
            codes.append(str(issue.get("code", "")))
        else:
            codes.append(str(getattr(issue, "code", "")))
    missing_required = any(is_missing_required_param_issue(code) for code in codes)
    constraint_conflict = any(is_constraint_conflict_issue(code) for code in codes)
    return {
        "preflight_hard_fail": bool(hard_fail),
        "constraint_conflict": bool(constraint_conflict),
        "missing_required_param": bool(missing_required),
        "catastrophic": bool(hard_fail),
        # Backward-compatible alias for older log/test readers.
        "any_missing": bool(missing_required),
    }
