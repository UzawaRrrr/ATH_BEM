"""Reusable Optuna study orchestration shared by CLI and GUI."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import optuna

from ath_gui.domain.design_recipe import DesignRecipe

from .design_space import DesignSpace, build_design_space, build_initial_seed_params
from .driver_profile import (
    DriverProfile,
    ProductConstraints,
    infer_driver_profile_from_recipe,
    infer_product_constraints_from_recipe,
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
from .objective import optuna_objective_wrapper
from .score_defaults import build_default_objective_config


SuggestFunction = Callable[[optuna.trial.Trial, DesignRecipe], dict[str, Any]]
StudyEventCallback = Callable[[dict[str, Any]], None]


def _range_around(
    value: float,
    *,
    min_floor: float,
    low_factor: float,
    high_factor: float,
    hard_cap: float | None = None,
) -> tuple[float, float]:
    base = float(value) if value and value > 0.0 else float(min_floor)
    low = max(float(min_floor), base * float(low_factor))
    high = max(low + 1.0e-6, base * float(high_factor))
    if hard_cap is not None:
        high = min(high, float(hard_cap))
    if high <= low:
        high = low + max(1.0, low * 0.1)
    return (low, high)


def suggest_default_params(trial: optuna.trial.Trial, base_recipe: DesignRecipe) -> dict[str, Any]:
    """Build a default driver-aware design space and sample actual params from it."""
    profile = infer_driver_profile_from_recipe(base_recipe)
    constraints = infer_product_constraints_from_recipe(base_recipe)
    design_space = build_design_space(profile, constraints, base_recipe=base_recipe)
    return design_space.sample_dict_from_optuna_trial(trial)


def parse_planes_spec(value: str | tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    """Normalize UI/CLI plane selections into canonical `(XZ, YZ)` tuples."""
    if value is None:
        return ("XZ", "YZ")
    if isinstance(value, (tuple, list)):
        raw_values = [str(item).strip().upper() for item in value]
    else:
        text = str(value).strip().upper()
        if text in {"", "XZ+YZ", "BOTH", "ALL"}:
            raw_values = ["XZ", "YZ"]
        elif "+" in text:
            raw_values = [part.strip() for part in text.split("+") if part.strip()]
        elif "," in text:
            raw_values = [part.strip() for part in text.split(",") if part.strip()]
        else:
            raw_values = [text]
    normalized: list[str] = []
    for item in raw_values:
        if item not in {"XZ", "YZ"}:
            raise ValueError(f"Unsupported optimizer plane selection: {item!r}")
        if item not in normalized:
            normalized.append(item)
    return tuple(normalized or ["XZ", "YZ"])


@dataclass(slots=True)
class OptunaStudyConfig:
    """Canonical study settings shared by CLI and GUI launch paths."""

    trials: int = 10
    stage: str = "final"
    target_bw_h_deg: float | None = None
    target_bw_v_deg: float | None = None
    study_name: str = ""
    study_dir: Path | None = None
    storage: str | None = None
    seed: int = 42
    enqueue_base: bool = False
    driver_profile_path: Path | None = None
    driver_profile: DriverProfile | None = None
    product_constraints: ProductConstraints | None = None
    feasibility_soft_scale: float = 1.0


@dataclass(slots=True)
class StudyRunResult:
    """Final study result returned after optimization finishes."""

    study: optuna.Study
    study_dir: Path
    config: OptunaStudyConfig


class _DecodedParamsTrialProxy:
    """Proxy a trial while exposing decoded params to the objective wrapper."""

    def __init__(self, trial: Any, params: dict[str, Any]) -> None:
        self._trial = trial
        self.params = dict(params)

    def set_user_attr(self, key: str, value: Any) -> None:
        self._trial.set_user_attr(key, value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _serialize_issue(issue: FeasibilityIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "severity": issue.severity,
        "message": issue.message,
        "value": _json_safe(issue.value),
        "limit": _json_safe(issue.limit),
    }


def _serialize_feasibility(result: FeasibilityResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "hard_fail": result.hard_fail,
        "soft_penalty": float(result.soft_penalty),
        "issues": [_serialize_issue(issue) for issue in result.issues],
        "derived_metrics": _json_safe(result.derived_metrics),
    }


def _trial_display_params(trial: optuna.trial.FrozenTrial | Any) -> dict[str, Any]:
    user_attrs = dict(getattr(trial, "user_attrs", {}) or {})
    actual = user_attrs.get("design_space.actual_params")
    if isinstance(actual, dict):
        return dict(actual)
    return dict(getattr(trial, "params", {}) or {})


def _serialize_trial(trial: optuna.trial.FrozenTrial) -> dict[str, Any]:
    return {
        "number": trial.number,
        "state": str(trial.state),
        "value": trial.value,
        "params": _trial_display_params(trial),
        "raw_params": dict(trial.params),
        "user_attrs": dict(trial.user_attrs),
    }


def _safe_best_trial(study: optuna.Study) -> optuna.trial.FrozenTrial | None:
    try:
        return study.best_trial
    except Exception:
        return None


def write_study_artifacts(
    study: optuna.Study,
    study_dir: Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist best-trial and study metadata in a JSON-friendly format."""
    study_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(metadata or {})
    best_trial = _safe_best_trial(study)
    (study_dir / "study_config.json").write_text(
        json.dumps(_json_safe(payload), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (study_dir / "best_trial.json").write_text(
        json.dumps(_serialize_trial(best_trial) if best_trial is not None else {}, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (study_dir / "trials.json").write_text(
        json.dumps([_serialize_trial(trial) for trial in study.trials], indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _resolve_driver_profile(config: OptunaStudyConfig, base_recipe: DesignRecipe) -> DriverProfile:
    if config.driver_profile is not None:
        return config.driver_profile
    if config.driver_profile_path is not None:
        return load_driver_profile(config.driver_profile_path)
    return infer_driver_profile_from_recipe(base_recipe)


def _resolve_product_constraints(config: OptunaStudyConfig, base_recipe: DesignRecipe) -> ProductConstraints:
    constraints = config.product_constraints or infer_product_constraints_from_recipe(
        base_recipe,
        target_bw_h_deg=config.target_bw_h_deg,
        target_bw_v_deg=config.target_bw_v_deg,
    )
    return replace(
        constraints,
        target_bw_h_deg=config.target_bw_h_deg if config.target_bw_h_deg is not None else constraints.target_bw_h_deg,
        target_bw_v_deg=config.target_bw_v_deg if config.target_bw_v_deg is not None else constraints.target_bw_v_deg,
    )


def _recipe_to_design_space_params(recipe: DesignRecipe, design_space: DesignSpace) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for name, variable in design_space.variables.items():
        if not variable.active and variable.kind != "fixed":
            continue
        if hasattr(recipe, name):
            params[name] = getattr(recipe, name)
        elif variable.kind == "fixed":
            params[name] = variable.fixed_value
    return params


def _enqueue_if_feasible(study: optuna.Study, design_space: DesignSpace, params: dict[str, Any]) -> None:
    feasibility = validate_params_against_design_space(params, design_space)
    if feasibility.hard_fail:
        return
    study.enqueue_trial(design_space.to_optuna_params(params))


def run_optuna_study(
    *,
    base_recipe: DesignRecipe,
    case_runner: Any,
    config: OptunaStudyConfig,
    suggest_fn: SuggestFunction | None = None,
    on_event: StudyEventCallback | None = None,
    stop_event: Any | None = None,
) -> StudyRunResult:
    """Run an Optuna study and emit coarse progress events for GUI/CLI consumers."""
    driver_profile = _resolve_driver_profile(config, base_recipe)
    product_constraints = _resolve_product_constraints(config, base_recipe)
    design_space = build_design_space(driver_profile, product_constraints, base_recipe=base_recipe)
    use_design_space_sampler = suggest_fn is None or suggest_fn is suggest_default_params
    effective_suggest = suggest_fn or suggest_default_params

    objective_config = build_default_objective_config(stage=config.stage)
    objective_config = replace(
        objective_config,
        target_bw_h_deg=config.target_bw_h_deg if config.target_bw_h_deg is not None else objective_config.target_bw_h_deg,
        target_bw_v_deg=config.target_bw_v_deg if config.target_bw_v_deg is not None else objective_config.target_bw_v_deg,
    )

    study_name = str(config.study_name).strip() or f"{base_recipe.case_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    study_dir = (config.study_dir or (Path(__file__).resolve().parents[1] / "projects" / "optuna" / study_name)).resolve()
    sampler = optuna.samplers.TPESampler(seed=int(config.seed))
    storage = None if config.storage is None else (str(config.storage).strip() or None)
    study = optuna.create_study(
        direction="minimize",
        sampler=sampler,
        study_name=study_name,
        storage=storage,
        load_if_exists=bool(storage),
    )

    seed_params = build_initial_seed_params(driver_profile, product_constraints)
    _enqueue_if_feasible(study, design_space, seed_params)
    if config.enqueue_base:
        _enqueue_if_feasible(study, design_space, _recipe_to_design_space_params(base_recipe, design_space))

    def emit(event: str, **payload: Any) -> None:
        if on_event is None:
            return
        on_event({"event": event, **payload})

    emit(
        "study_started",
        study_name=study_name,
        study_dir=str(study_dir),
        trials=int(config.trials),
        stage=config.stage,
        driver_profile=_json_safe(driver_profile.to_dict()),
        product_constraints=_json_safe(product_constraints.to_dict()),
        design_space_notes=list(design_space.notes),
    )

    def objective(trial: optuna.trial.Trial) -> float:
        params = design_space.sample_dict_from_optuna_trial(trial) if use_design_space_sampler else effective_suggest(trial, base_recipe)
        trial.set_user_attr("recipe.base_case_name", base_recipe.case_name)
        trial.set_user_attr("recipe.params_count", len(params))
        trial.set_user_attr("driver_profile.driver_id", driver_profile.driver_id)
        trial.set_user_attr("driver_profile.name", driver_profile.name)
        trial.set_user_attr("design_space.actual_params", _json_safe(dict(params)))
        trial.set_user_attr("design_space.fixed_params", _json_safe({name: variable.fixed_value for name, variable in design_space.fixed_variables().items()}))
        emit(
            "trial_started",
            trial_number=int(trial.number),
            trial_index=int(trial.number) + 1,
            total_trials=int(config.trials),
            params=dict(params),
        )

        params_result = validate_params_against_design_space(params, design_space)
        recipe = design_space.apply_to_recipe(base_recipe, params)
        recipe_result = validate_recipe_against_driver(recipe, driver_profile, product_constraints)
        combined_result = merge_feasibility_results(params_result, recipe_result)
        pre_score_penalty = feasibility_penalty(
            combined_result,
            catastrophic_score=objective_config.catastrophic_score,
            soft_scale=config.feasibility_soft_scale,
        )

        trial.set_user_attr("recipe.preview", _json_safe(recipe.to_dict()))
        trial.set_user_attr("feasibility", _serialize_feasibility(combined_result))
        trial.set_user_attr("feasibility.ok", combined_result.ok)
        trial.set_user_attr("feasibility.hard_fail", combined_result.hard_fail)
        trial.set_user_attr("score.pre_feasibility", float(pre_score_penalty))
        trial.set_user_attr("score.feasibility_soft", float(combined_result.soft_penalty))

        if combined_result.hard_fail:
            trial.set_user_attr("score.objective_raw", None)
            trial.set_user_attr("score.total", float(pre_score_penalty))
            trial.set_user_attr("flags.any_missing", True)
            trial.set_user_attr("flags.catastrophic", True)
            emit(
                "trial_scored",
                trial_number=int(trial.number),
                value=float(pre_score_penalty),
            )
            return float(pre_score_penalty)

        proxy_trial = _DecodedParamsTrialProxy(trial, params)
        raw_score = optuna_objective_wrapper(proxy_trial, case_runner=case_runner, config=objective_config)
        total = float(pre_score_penalty) + float(raw_score)
        trial.set_user_attr("score.objective_raw", float(raw_score))
        trial.set_user_attr("score.total", float(total))
        emit(
            "trial_scored",
            trial_number=int(trial.number),
            value=float(total),
        )
        return float(total)

    def callback(study_obj: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        best_trial = _safe_best_trial(study_obj)
        emit(
            "trial_completed",
            trial_number=int(trial.number),
            value=trial.value,
            state=str(trial.state),
            params=_trial_display_params(trial),
            raw_params=dict(trial.params),
            user_attrs=dict(trial.user_attrs),
            best_number=None if best_trial is None else int(best_trial.number),
            best_value=None if best_trial is None else best_trial.value,
            best_params={} if best_trial is None else _trial_display_params(best_trial),
            best_raw_params={} if best_trial is None else dict(best_trial.params),
            best_user_attrs={} if best_trial is None else dict(best_trial.user_attrs),
        )
        if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
            emit("stop_requested", after_trial=int(trial.number))
            study_obj.stop()

    study.optimize(objective, n_trials=max(1, int(config.trials)), callbacks=[callback])
    best_trial = _safe_best_trial(study)
    emit(
        "study_completed",
        study_name=study_name,
        study_dir=str(study_dir),
        best_number=None if best_trial is None else int(best_trial.number),
        best_value=None if best_trial is None else best_trial.value,
        best_params={} if best_trial is None else _trial_display_params(best_trial),
        best_raw_params={} if best_trial is None else dict(best_trial.params),
        best_user_attrs={} if best_trial is None else dict(best_trial.user_attrs),
        completed_trials=len(study.trials),
    )
    return StudyRunResult(study=study, study_dir=study_dir, config=replace(config, study_name=study_name, study_dir=study_dir))
