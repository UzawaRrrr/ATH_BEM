"""Driver-aware design-space construction for the headless optimizer."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from ath_gui.domain.design_recipe import DesignRecipe

from .driver_profile import (
    DEFAULT_COVERAGE_CENTER_DEG,
    DEFAULT_MIN_HORN_LENGTH_MM,
    DerivedDriverConstraints,
    DriverProfile,
    ProductConstraints,
    derive_driver_constraints,
)


DEFAULT_SOURCE_VELOCITY_RANGE = (0.1, 3.0)
DEFAULT_FLOAT_UNIT_RANGE = (0.0, 1.0)
DEFAULT_WIDTH_FLOOR_MM = 80.0
DEFAULT_HEIGHT_FLOOR_MM = 60.0
DEFAULT_HORN_LENGTH_FLOOR_MM = 60.0
DEFAULT_COVERAGE_RANGE_DEG = (30.0, 140.0)
DEFAULT_CORNER_RADIUS_MM = 10.0
DEFAULT_MAX_MOUTH_DIM_MM = 600.0
UNIT_PARAM_PREFIX = "unit__"
SEED_CONSERVATIVE_RATIO = 0.35


def _clamp(value: float, low: float, high: float) -> float:
    return max(float(low), min(float(high), float(value)))


def _safe_mid(low: float, high: float, ratio: float = 0.5) -> float:
    return float(low) + (float(high) - float(low)) * float(ratio)


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


def _coerce_bounds(
    low: float | None,
    high: float | None,
    *,
    fallback_low: float,
    fallback_high: float,
) -> tuple[float, float]:
    resolved_low = float(low) if low is not None else float(fallback_low)
    resolved_high = float(high) if high is not None else float(fallback_high)
    if resolved_high <= resolved_low:
        resolved_high = resolved_low + max(1.0, resolved_low * 0.1)
    return (resolved_low, resolved_high)


def _default_source_mode(profile: DriverProfile, base_recipe: DesignRecipe) -> str:
    if profile.driver_type == "compression_driver":
        return "normal"
    if profile.driver_type == "direct_radiator":
        source_mode = str(base_recipe.source_mode).strip().lower()
        return source_mode or "axial"
    source_mode = str(base_recipe.source_mode).strip().lower()
    return source_mode or "normal"


def _coverage_bounds(
    profile: DriverProfile,
    constraints: ProductConstraints,
    derived: DerivedDriverConstraints,
    base_recipe: DesignRecipe,
) -> tuple[float, float]:
    targets = [float(value) for value in (constraints.target_bw_h_deg, constraints.target_bw_v_deg) if value is not None]
    if targets:
        low = max(DEFAULT_COVERAGE_RANGE_DEG[0], min(targets) - 10.0)
        high_limit = profile.preferred_max_coverage_deg if profile.preferred_max_coverage_deg is not None else DEFAULT_COVERAGE_RANGE_DEG[1]
        high = min(float(high_limit), max(targets) + 10.0)
        if high < low:
            high = low
        return (low, high)

    recommended = derived.recommended_coverage_h_range_deg or derived.recommended_coverage_v_range_deg
    if recommended is not None:
        low, high = recommended
        if high <= low:
            high = low + 5.0
        return (float(low), float(high))

    return _range_around(
        float(base_recipe.coverage_angle or DEFAULT_COVERAGE_CENTER_DEG),
        min_floor=DEFAULT_COVERAGE_RANGE_DEG[0],
        low_factor=0.75,
        high_factor=1.20,
        hard_cap=profile.preferred_max_coverage_deg or DEFAULT_COVERAGE_RANGE_DEG[1],
    )


def _build_variable(
    *,
    name: str,
    kind: Literal["float", "int", "categorical", "fixed"],
    low: float | int | None = None,
    high: float | int | None = None,
    choices: list[Any] | None = None,
    fixed_value: Any | None = None,
    active: bool = True,
    metadata: dict[str, Any] | None = None,
) -> "DesignVariable":
    return DesignVariable(
        name=name,
        kind=kind,
        low=low,
        high=high,
        choices=choices,
        fixed_value=fixed_value,
        active=active,
        metadata=dict(metadata or {}),
    )


@dataclass(slots=True)
class DesignVariable:
    """One optimizer-facing variable inside a constrained design space."""

    name: str
    kind: Literal["float", "int", "categorical", "fixed"]
    low: float | int | None = None
    high: float | int | None = None
    choices: list[Any] | None = None
    fixed_value: Any | None = None
    log: bool = False
    normalize_to_unit: bool = True
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DesignSpace:
    """Driver-aware, recipe-compatible design space used by Optuna."""

    variables: dict[str, DesignVariable]
    driver_profile: DriverProfile
    product_constraints: ProductConstraints
    derived: DerivedDriverConstraints
    notes: list[str] = field(default_factory=list)

    def active_variables(self) -> dict[str, DesignVariable]:
        """Return all active variables."""
        return {name: variable for name, variable in self.variables.items() if variable.active}

    def fixed_variables(self) -> dict[str, DesignVariable]:
        """Return all fixed variables."""
        return {name: variable for name, variable in self.variables.items() if variable.kind == "fixed"}

    def optuna_param_name(self, variable_name: str) -> str:
        """Return the Optuna-facing parameter name for a design variable."""
        variable = self.variables[variable_name]
        if variable.kind in {"float", "int"} and variable.normalize_to_unit:
            return str(variable.metadata.get("unit_param_name", f"{UNIT_PARAM_PREFIX}{variable_name}"))
        return variable_name

    def normalize(self, params: dict[str, Any]) -> dict[str, float]:
        """Normalize numeric params into unit coordinates keyed for Optuna."""
        normalized: dict[str, float] = {}
        merged = {**{name: variable.fixed_value for name, variable in self.fixed_variables().items()}, **dict(params)}
        for name, variable in self.variables.items():
            if name not in merged:
                continue
            value = merged[name]
            if variable.kind == "fixed":
                normalized[self.optuna_param_name(name)] = 0.0
                continue
            if variable.kind == "categorical":
                choices = list(variable.choices or [])
                if not choices:
                    continue
                index = choices.index(value)
                normalized[self.optuna_param_name(name)] = 0.0 if len(choices) == 1 else index / float(len(choices) - 1)
                continue
            if variable.low is None or variable.high is None:
                continue
            low = float(variable.low)
            high = float(variable.high)
            if high <= low:
                normalized[self.optuna_param_name(name)] = 0.0
                continue
            normalized[self.optuna_param_name(name)] = _clamp((float(value) - low) / (high - low), *DEFAULT_FLOAT_UNIT_RANGE)
        return normalized

    def denormalize(self, unit_params: dict[str, Any]) -> dict[str, Any]:
        """Decode unit-space or Optuna-space parameters into actual recipe values."""
        actual: dict[str, Any] = {}
        payload = dict(unit_params)
        for name, variable in self.variables.items():
            optuna_name = self.optuna_param_name(name)
            raw_value = payload.get(optuna_name, payload.get(name))
            if variable.kind == "fixed":
                actual[name] = variable.fixed_value
                continue
            if raw_value is None:
                continue
            if variable.kind == "categorical":
                choices = list(variable.choices or [])
                if raw_value in choices:
                    actual[name] = raw_value
                    continue
                index = int(round(float(raw_value) * max(len(choices) - 1, 0)))
                index = max(0, min(index, max(0, len(choices) - 1)))
                actual[name] = choices[index]
                continue
            if variable.low is None or variable.high is None:
                actual[name] = raw_value
                continue
            low = float(variable.low)
            high = float(variable.high)
            if variable.normalize_to_unit and optuna_name in payload:
                decoded = low + (_clamp(float(raw_value), *DEFAULT_FLOAT_UNIT_RANGE) * (high - low))
            else:
                decoded = float(raw_value)
            if variable.kind == "int":
                actual[name] = int(round(_clamp(decoded, low, high)))
            else:
                actual[name] = _clamp(decoded, low, high)
        return actual

    def to_optuna_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Convert actual params to the Optuna-facing key/value mapping."""
        payload = dict(params)
        optuna_params: dict[str, Any] = {}
        normalized = self.normalize(payload)
        for name, variable in self.variables.items():
            if name not in payload:
                continue
            optuna_name = self.optuna_param_name(name)
            if variable.kind in {"float", "int"} and variable.normalize_to_unit:
                optuna_params[optuna_name] = normalized.get(optuna_name, 0.0)
            elif variable.kind != "fixed":
                optuna_params[optuna_name] = payload[name]
        return optuna_params

    def sample_dict_from_optuna_trial(self, trial: Any) -> dict[str, Any]:
        """Sample unit-space variables from an Optuna trial and decode them."""
        sampled_optuna: dict[str, Any] = {}
        actual: dict[str, Any] = {}
        for name, variable in self.variables.items():
            if not variable.active:
                continue
            optuna_name = self.optuna_param_name(name)
            if variable.kind == "fixed":
                actual[name] = variable.fixed_value
                continue
            if variable.kind == "categorical":
                sampled_optuna[optuna_name] = trial.suggest_categorical(optuna_name, list(variable.choices or []))
                continue
            if variable.kind == "int":
                if variable.normalize_to_unit:
                    sampled_optuna[optuna_name] = trial.suggest_float(optuna_name, *DEFAULT_FLOAT_UNIT_RANGE)
                else:
                    sampled_optuna[optuna_name] = trial.suggest_int(optuna_name, int(variable.low or 0), int(variable.high or 0))
                continue
            if variable.kind == "float":
                if variable.normalize_to_unit:
                    sampled_optuna[optuna_name] = trial.suggest_float(optuna_name, *DEFAULT_FLOAT_UNIT_RANGE)
                else:
                    sampled_optuna[optuna_name] = trial.suggest_float(
                        optuna_name,
                        float(variable.low or 0.0),
                        float(variable.high or 0.0),
                        log=bool(variable.log),
                    )
        actual.update(self.denormalize(sampled_optuna))
        for name, variable in self.fixed_variables().items():
            if variable.active:
                actual[name] = variable.fixed_value
        return actual

    def apply_to_recipe(self, base_recipe: DesignRecipe, params: dict[str, Any]) -> DesignRecipe:
        """Apply active design-space params to a `DesignRecipe`."""
        field_names = set(DesignRecipe.__dataclass_fields__)
        direct_updates: dict[str, Any] = {}
        ath_overrides = dict(base_recipe.ath_overrides)
        bem_overrides = dict(base_recipe.bem_overrides)
        for key, value in dict(params).items():
            variable = self.variables.get(key)
            if variable is not None and not variable.active and variable.kind != "fixed":
                continue
            if key in field_names:
                direct_updates[key] = value
                continue
            if str(key).startswith("ath_overrides."):
                ath_overrides[str(key).removeprefix("ath_overrides.")] = value
                continue
            if str(key).startswith("bem_overrides."):
                bem_overrides[str(key).removeprefix("bem_overrides.")] = value
                continue
            raise KeyError(f"Unknown design-space parameter `{key}`.")
        recipe = replace(base_recipe, **direct_updates, ath_overrides=ath_overrides, bem_overrides=bem_overrides)
        recipe.assert_valid()
        return recipe


def build_initial_seed_params(
    driver_profile: DriverProfile,
    product_constraints: ProductConstraints,
) -> dict[str, Any]:
    """Build a conservative initial seed inside the inferred feasible region."""
    derived = derive_driver_constraints(driver_profile, product_constraints)
    throat = derived.fixed_throat_diameter_mm if derived.fixed_throat_diameter_mm is not None else 25.4
    mouth_width_low, mouth_width_high = _coerce_bounds(
        derived.min_mouth_width_mm,
        derived.max_mouth_width_mm,
        fallback_low=max(DEFAULT_WIDTH_FLOOR_MM, throat * driver_profile.preferred_min_mouth_to_throat_ratio),
        fallback_high=max(DEFAULT_WIDTH_FLOOR_MM * 1.5, throat * driver_profile.preferred_min_mouth_to_throat_ratio * 1.8),
    )
    mouth_height_low, mouth_height_high = _coerce_bounds(
        derived.min_mouth_height_mm,
        derived.max_mouth_height_mm,
        fallback_low=max(DEFAULT_HEIGHT_FLOOR_MM, throat * driver_profile.preferred_min_mouth_to_throat_ratio),
        fallback_high=max(DEFAULT_HEIGHT_FLOOR_MM * 1.5, throat * driver_profile.preferred_min_mouth_to_throat_ratio * 1.8),
    )
    horn_length_low, horn_length_high = _coerce_bounds(
        derived.min_horn_length_mm,
        derived.max_horn_length_mm,
        fallback_low=max(DEFAULT_HORN_LENGTH_FLOOR_MM, float(driver_profile.min_adapter_length_mm or 0.0)),
        fallback_high=max(DEFAULT_HORN_LENGTH_FLOOR_MM * 2.0, (derived.min_horn_length_mm or DEFAULT_HORN_LENGTH_FLOOR_MM) * 1.6),
    )
    recommended_h = derived.recommended_coverage_h_range_deg
    recommended_v = derived.recommended_coverage_v_range_deg
    coverage_candidates = []
    for candidate in (product_constraints.target_bw_h_deg, product_constraints.target_bw_v_deg):
        if candidate is not None:
            coverage_candidates.append(float(candidate))
    if not coverage_candidates:
        for recommended in (recommended_h, recommended_v):
            if recommended is not None:
                coverage_candidates.append(_safe_mid(recommended[0], recommended[1]))
    coverage = sum(coverage_candidates) / len(coverage_candidates) if coverage_candidates else DEFAULT_COVERAGE_CENTER_DEG

    mouth_width = _safe_mid(mouth_width_low, mouth_width_high, SEED_CONSERVATIVE_RATIO)
    mouth_height = _safe_mid(mouth_height_low, mouth_height_high, SEED_CONSERVATIVE_RATIO)
    corner_limit = max(0.0, min(mouth_width, mouth_height) * 0.5)
    if derived.max_corner_radius_mm is not None:
        corner_limit = min(corner_limit, float(derived.max_corner_radius_mm))
    corner_radius = min(max(4.0, min(mouth_width, mouth_height) * 0.12), corner_limit * 0.6 if corner_limit > 0.0 else 0.0)

    return {
        "throat_diameter": throat,
        "horn_length": _safe_mid(horn_length_low, horn_length_high, 0.50),
        "coverage_angle": coverage,
        "mouth_width": mouth_width,
        "mouth_height": mouth_height,
        "mouth_corner_radius": max(0.0, corner_radius),
        "source_mode": "normal" if driver_profile.driver_type == "compression_driver" else "axial",
        "source_velocity": 1.0,
    }


def build_default_baseline_recipe(
    driver_profile: DriverProfile,
    product_constraints: ProductConstraints,
) -> DesignRecipe:
    """Build a baseline `DesignRecipe` from driver/product inputs only."""
    params = build_initial_seed_params(driver_profile, product_constraints)
    recipe = DesignRecipe(
        case_name=f"{driver_profile.driver_id}_baseline",
        throat_diameter=float(params["throat_diameter"]),
        horn_length=float(params["horn_length"]),
        coverage_angle=float(params["coverage_angle"]),
        mouth_width=float(params["mouth_width"]),
        mouth_height=float(params["mouth_height"]),
        mouth_corner_radius=float(params["mouth_corner_radius"]),
        source_mode=str(params["source_mode"]),
        source_velocity=float(params["source_velocity"]),
    )
    recipe.assert_valid()
    return recipe


def build_design_space(
    driver_profile: DriverProfile,
    product_constraints: ProductConstraints,
    base_recipe: DesignRecipe | None = None,
) -> DesignSpace:
    """Build a driver-constrained design space compatible with `DesignRecipe`."""
    effective_base = base_recipe or build_default_baseline_recipe(driver_profile, product_constraints)
    derived = derive_driver_constraints(driver_profile, product_constraints)
    notes = list(derived.notes)
    variables: dict[str, DesignVariable] = {}

    if derived.fixed_throat_diameter_mm is not None:
        variables["throat_diameter"] = _build_variable(
            name="throat_diameter",
            kind="fixed",
            fixed_value=float(derived.fixed_throat_diameter_mm),
            metadata={"reason": "driver_profile.fixed_throat"},
        )
    else:
        throat_low, throat_high = _range_around(
            float(effective_base.throat_diameter),
            min_floor=15.0,
            low_factor=0.80,
            high_factor=1.20,
            hard_cap=60.0,
        )
        variables["throat_diameter"] = _build_variable(
            name="throat_diameter",
            kind="float",
            low=throat_low,
            high=throat_high,
            metadata={"bounds_source": "base_recipe_fallback"},
        )

    variables["source_mode"] = _build_variable(
        name="source_mode",
        kind="fixed",
        fixed_value=_default_source_mode(driver_profile, effective_base),
        metadata={"reason": "driver_type"},
    )

    horn_low, horn_high = _coerce_bounds(
        derived.min_horn_length_mm,
        derived.max_horn_length_mm,
        fallback_low=max(DEFAULT_HORN_LENGTH_FLOOR_MM, _range_around(effective_base.horn_length, min_floor=60.0, low_factor=0.75, high_factor=1.30)[0]),
        fallback_high=_range_around(effective_base.horn_length, min_floor=60.0, low_factor=0.75, high_factor=1.30)[1],
    )
    variables["horn_length"] = _build_variable(
        name="horn_length",
        kind="float",
        low=horn_low,
        high=horn_high,
        metadata={"bounds_source": "derived_or_base"},
    )

    coverage_low, coverage_high = _coverage_bounds(driver_profile, product_constraints, derived, effective_base)
    variables["coverage_angle"] = _build_variable(
        name="coverage_angle",
        kind="float",
        low=coverage_low,
        high=coverage_high,
        metadata={"bounds_source": "derived_or_target"},
    )

    width_fallback = _range_around(effective_base.mouth_width if effective_base.mouth_width > 0.0 else 250.0, min_floor=80.0, low_factor=0.70, high_factor=1.25)
    height_fallback = _range_around(effective_base.mouth_height if effective_base.mouth_height > 0.0 else 180.0, min_floor=60.0, low_factor=0.70, high_factor=1.25)
    width_low, width_high = _coerce_bounds(
        derived.min_mouth_width_mm,
        derived.max_mouth_width_mm,
        fallback_low=max(DEFAULT_WIDTH_FLOOR_MM, width_fallback[0]),
        fallback_high=min(DEFAULT_MAX_MOUTH_DIM_MM, width_fallback[1]),
    )
    height_low, height_high = _coerce_bounds(
        derived.min_mouth_height_mm,
        derived.max_mouth_height_mm,
        fallback_low=max(DEFAULT_HEIGHT_FLOOR_MM, height_fallback[0]),
        fallback_high=min(DEFAULT_MAX_MOUTH_DIM_MM, height_fallback[1]),
    )
    mouth_shape = str(effective_base.mouth_shape).strip().lower()
    mouth_vars_active = mouth_shape != "keep"
    variables["mouth_width"] = _build_variable(
        name="mouth_width",
        kind="float",
        low=width_low,
        high=width_high,
        active=mouth_vars_active,
        metadata={"bounds_source": "derived_or_product", "activation": f"mouth_shape={mouth_shape}"},
    )
    variables["mouth_height"] = _build_variable(
        name="mouth_height",
        kind="float",
        low=height_low,
        high=height_high,
        active=mouth_vars_active,
        metadata={"bounds_source": "derived_or_product", "activation": f"mouth_shape={mouth_shape}"},
    )

    corner_high = min(width_high, height_high) * 0.5
    if derived.max_corner_radius_mm is not None:
        corner_high = min(corner_high, float(derived.max_corner_radius_mm))
    corner_high = max(0.0, corner_high)
    variables["mouth_corner_radius"] = _build_variable(
        name="mouth_corner_radius",
        kind="float",
        low=0.0,
        high=max(DEFAULT_CORNER_RADIUS_MM, corner_high),
        active=mouth_vars_active,
        metadata={"bounds_source": "derived_from_mouth"},
    )

    velocity_low, velocity_high = _range_around(
        effective_base.source_velocity if effective_base.source_velocity > 0.0 else 1.0,
        min_floor=DEFAULT_SOURCE_VELOCITY_RANGE[0],
        low_factor=0.50,
        high_factor=1.80,
        hard_cap=DEFAULT_SOURCE_VELOCITY_RANGE[1],
    )
    variables["source_velocity"] = _build_variable(
        name="source_velocity",
        kind="float",
        low=velocity_low,
        high=velocity_high,
        metadata={"bounds_source": "base_recipe_fallback"},
    )

    return DesignSpace(
        variables=variables,
        driver_profile=driver_profile,
        product_constraints=product_constraints,
        derived=derived,
        notes=notes,
    )
