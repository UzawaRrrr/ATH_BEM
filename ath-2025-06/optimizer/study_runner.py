"""Reusable Optuna study orchestration shared by CLI and GUI."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import optuna

from ath_gui.domain.design_recipe import DesignRecipe

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
    return low, high


def suggest_default_params(trial: optuna.trial.Trial, base_recipe: DesignRecipe) -> dict[str, Any]:
    """Default relative search space centered around the base recipe."""
    mouth_width_base = base_recipe.mouth_width if base_recipe.mouth_width > 0 else 250.0
    mouth_height_base = base_recipe.mouth_height if base_recipe.mouth_height > 0 else 180.0
    corner_base = max(0.0, base_recipe.mouth_corner_radius)
    source_velocity_base = base_recipe.source_velocity if base_recipe.source_velocity > 0 else 1.0

    horn_length_range = _range_around(base_recipe.horn_length, min_floor=60.0, low_factor=0.75, high_factor=1.30)
    coverage_range = _range_around(base_recipe.coverage_angle, min_floor=40.0, low_factor=0.75, high_factor=1.20, hard_cap=140.0)
    mouth_width_range = _range_around(mouth_width_base, min_floor=80.0, low_factor=0.70, high_factor=1.25)
    mouth_height_range = _range_around(mouth_height_base, min_floor=60.0, low_factor=0.70, high_factor=1.25)
    throat_range = _range_around(base_recipe.throat_diameter, min_floor=15.0, low_factor=0.80, high_factor=1.20, hard_cap=60.0)
    velocity_range = _range_around(source_velocity_base, min_floor=0.1, low_factor=0.50, high_factor=1.80, hard_cap=3.0)
    corner_high = max(10.0, corner_base * 1.5 + 10.0)

    return {
        "horn_length": trial.suggest_float("horn_length", *horn_length_range),
        "coverage_angle": trial.suggest_float("coverage_angle", *coverage_range),
        "mouth_width": trial.suggest_float("mouth_width", *mouth_width_range),
        "mouth_height": trial.suggest_float("mouth_height", *mouth_height_range),
        "mouth_corner_radius": trial.suggest_float("mouth_corner_radius", 0.0, corner_high),
        "throat_diameter": trial.suggest_float("throat_diameter", *throat_range),
        "source_velocity": trial.suggest_float("source_velocity", *velocity_range),
    }


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


@dataclass(slots=True)
class StudyRunResult:
    """Final study result returned after optimization finishes."""

    study: optuna.Study
    study_dir: Path
    config: OptunaStudyConfig


def _serialize_trial(trial: optuna.trial.FrozenTrial) -> dict[str, Any]:
    return {
        "number": trial.number,
        "state": str(trial.state),
        "value": trial.value,
        "params": dict(trial.params),
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
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
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
    if config.enqueue_base:
        study.enqueue_trial({})

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
    )

    def objective(trial: optuna.trial.Trial) -> float:
        params = effective_suggest(trial, base_recipe)
        trial.set_user_attr("recipe.base_case_name", base_recipe.case_name)
        trial.set_user_attr("recipe.params_count", len(params))
        emit(
            "trial_started",
            trial_number=int(trial.number),
            trial_index=int(trial.number) + 1,
            total_trials=int(config.trials),
            params=dict(params),
        )
        value = optuna_objective_wrapper(trial, case_runner=case_runner, config=objective_config)
        emit(
            "trial_scored",
            trial_number=int(trial.number),
            value=float(value),
        )
        return value

    def callback(study_obj: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        best_trial = _safe_best_trial(study_obj)
        emit(
            "trial_completed",
            trial_number=int(trial.number),
            value=trial.value,
            state=str(trial.state),
            params=dict(trial.params),
            user_attrs=dict(trial.user_attrs),
            best_number=None if best_trial is None else int(best_trial.number),
            best_value=None if best_trial is None else best_trial.value,
            best_params={} if best_trial is None else dict(best_trial.params),
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
        best_params={} if best_trial is None else dict(best_trial.params),
        best_user_attrs={} if best_trial is None else dict(best_trial.user_attrs),
        completed_trials=len(study.trials),
    )
    return StudyRunResult(study=study, study_dir=study_dir, config=replace(config, study_name=study_name, study_dir=study_dir))
