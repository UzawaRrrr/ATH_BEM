from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimizer.conflict_policy import build_preflight_flags, resolve_conflict_policy  # noqa: E402
from optimizer.feasibility import FeasibilityIssue  # noqa: E402


def test_conflict_policy_stage_behavior_is_predictable() -> None:
    explicit_coarse = resolve_conflict_policy(
        "horn_length_vs_max_depth",
        stage="coarse",
        constraints_are_inferred_fallback=False,
    )
    inferred_coarse = resolve_conflict_policy(
        "horn_length_vs_max_depth",
        stage="coarse",
        constraints_are_inferred_fallback=True,
    )
    inferred_refine = resolve_conflict_policy(
        "horn_length_vs_max_depth",
        stage="refine",
        constraints_are_inferred_fallback=True,
    )
    inferred_constraints_coarse = resolve_conflict_policy(
        "inferred_constraints",
        stage="coarse",
        constraints_are_inferred_fallback=True,
    )
    inferred_constraints_final = resolve_conflict_policy(
        "inferred_constraints",
        stage="final",
        constraints_are_inferred_fallback=True,
    )
    osse_conflict = resolve_conflict_policy(
        "osse_proxy_out_of_range",
        stage="coarse",
        constraints_are_inferred_fallback=True,
    )
    future_mode_conflict = resolve_conflict_policy(
        "mode_conflict",
        stage="coarse",
        constraints_are_inferred_fallback=True,
    )

    assert explicit_coarse.strategy == "fail_fast"
    assert inferred_coarse.strategy == "cap_and_soft_penalize"
    assert inferred_refine.strategy == "fail_fast"
    assert inferred_constraints_coarse.strategy == "relax_coarse_only"
    assert inferred_constraints_final.strategy == "fail_fast"
    assert osse_conflict.strategy == "fail_fast"
    assert future_mode_conflict.strategy == "fail_fast"


def test_preflight_flags_split_missing_and_constraint_conflict() -> None:
    missing_only = build_preflight_flags(
        hard_fail=True,
        issues=[
            FeasibilityIssue(code="missing_horn_length", severity="hard", message="missing"),
        ],
    )
    conflict_only = build_preflight_flags(
        hard_fail=True,
        issues=[
            FeasibilityIssue(code="horn_too_deep", severity="hard", message="too deep"),
        ],
    )

    assert missing_only["preflight_hard_fail"] is True
    assert missing_only["missing_required_param"] is True
    assert missing_only["constraint_conflict"] is False
    assert missing_only["catastrophic"] is True
    assert missing_only["any_missing"] is True

    assert conflict_only["preflight_hard_fail"] is True
    assert conflict_only["missing_required_param"] is False
    assert conflict_only["constraint_conflict"] is True
    assert conflict_only["catastrophic"] is True
    assert conflict_only["any_missing"] is False


def _run_all() -> None:
    test_conflict_policy_stage_behavior_is_predictable()
    test_preflight_flags_split_missing_and_constraint_conflict()


if __name__ == "__main__":
    _run_all()
    print("test_conflict_policy.py: ok")
