"""Semantic study-definition layers used to organize optimizer inputs.

This module deliberately separates fixed evaluation environment, hard geometry
limits, acoustic targets, soft geometry preferences, and search-policy toggles.
The current optimizer still consumes the legacy `ProductConstraints` and
`DesignRecipe` interfaces downstream, but `run_optuna_study()` can now adapt
its legacy inputs into these cleaner layers first.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ath_gui.domain.design_recipe import DesignRecipe

from .design_space import OSSE_DEFAULT_VALUES, baseline_mouth_geometry_policy
from .driver_profile import DriverProfile, ProductConstraints
from .score_defaults import build_default_objective_config


DEFAULT_SOURCE_VELOCITY = 1.0
DEFAULT_PREFERENCE_TOLERANCE_RATIO = 0.12
DEFAULT_PREFERENCE_TOLERANCE_FLOOR_MM = 10.0
DEFAULT_PREFERENCE_WEIGHT = 1.0
CANONICAL_OSSE_OVERRIDE_KEYS = ("Term.s", "Term.q", "Term.n", "OS.k")
CANONICAL_TEMPLATE_ATH_OVERRIDE_BLOCKLIST = {
    "Throat.Diameter",
    "Length",
    "Coverage.Angle",
    "Morph.TargetShape",
    "Morph.TargetWidth",
    "Morph.TargetHeight",
    "Morph.CornerRadius",
    "Source.Shape",
    "Source.Velocity",
    "ABEC.f1",
    "ABEC.f2",
    "ABEC.NumFrequencies",
    "Output.ABECProject",
    *CANONICAL_OSSE_OVERRIDE_KEYS,
}
CANONICAL_TEMPLATE_BEM_OVERRIDE_BLOCKLIST = {
    "BEM.F1",
    "BEM.F2",
    "BEM.NumFreq",
    "BEM.Plane",
    "BEM.MicDistance",
    "BEM.SourceGain",
    "BEM.SymmetryMode",
    "BEM.AngleRangeMode",
}


def _dedupe_notes(*groups: list[str]) -> list[str]:
    ordered: list[str] = []
    for group in groups:
        for note in group:
            text = str(note).strip()
            if text and text not in ordered:
                ordered.append(text)
    return ordered


def _positive_or_none(value: Any) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    return numeric if numeric > 0.0 else None


def _preference_tolerance(value_mm: float | None) -> float | None:
    if value_mm is None:
        return None
    return max(DEFAULT_PREFERENCE_TOLERANCE_FLOOR_MM, float(value_mm) * DEFAULT_PREFERENCE_TOLERANCE_RATIO)


@dataclass(slots=True)
class StudyEnvironment:
    """Fixed evaluation environment that must stay outside the design space."""

    bem_f1: float
    bem_f2: float
    bem_num_freq: int
    observation_plane: str
    mic_distance: float
    symmetry_enabled: bool
    symmetry_planes: tuple[str, ...] = field(default_factory=tuple)
    source_mode: str = "normal"
    source_velocity: float = DEFAULT_SOURCE_VELOCITY
    auto_enclosure_enabled: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation of the environment."""
        return asdict(self)


@dataclass(slots=True)
class HardConstraints:
    """True packaging / installation limits that feasibility must not violate."""

    max_baffle_width_mm: float | None = None
    max_baffle_height_mm: float | None = None
    max_depth_mm: float | None = None
    min_wall_thickness_mm: float | None = None
    fixed_throat_diameter_mm: float | None = None
    mounting_flange_diameter_mm: float | None = None
    bolt_circle_diameter_mm: float | None = None
    bolt_count: int | None = None
    max_outer_diameter_mm: float | None = None
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation of the hard limits."""
        return asdict(self)


@dataclass(slots=True)
class AcousticTargets:
    """Band-wide acoustic targets used by scorer-oriented stages."""

    target_bw_h_deg: float | None = None
    target_bw_v_deg: float | None = None
    target_low_freq_hz: float | None = None
    target_high_freq_hz: float | None = None
    score_band_cov_hz: tuple[float, float] | None = None
    score_band_room_hz: tuple[float, float] | None = None
    score_band_load_hz: tuple[float, float] | None = None
    stage: str = "final"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation of the acoustic target layer."""
        return asdict(self)


@dataclass(slots=True)
class GeometryPreferences:
    """Soft geometry preferences used as score-side regularization only."""

    preferred_mouth_width_mm: float | None = None
    preferred_mouth_height_mm: float | None = None
    preferred_horn_length_mm: float | None = None
    mouth_width_tolerance_mm: float | None = None
    mouth_height_tolerance_mm: float | None = None
    horn_length_tolerance_mm: float | None = None
    mouth_width_weight: float = DEFAULT_PREFERENCE_WEIGHT
    mouth_height_weight: float = DEFAULT_PREFERENCE_WEIGHT
    horn_length_weight: float = DEFAULT_PREFERENCE_WEIGHT
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation of the preference layer."""
        return asdict(self)


@dataclass(slots=True)
class SearchPolicy:
    """Switches that define which geometry families the current study may optimize."""

    optimize_throat_diameter: bool = False
    optimize_horn_length: bool = True
    optimize_coverage_angle: bool = True
    optimize_osse: bool = True
    optimize_mouth_width: bool = False
    optimize_mouth_height: bool = False
    optimize_flare: bool = False
    optimize_gcurve: bool = False
    optimize_morph: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation of the search policy."""
        return asdict(self)


@dataclass(slots=True)
class StudyDefinition:
    """Bundled semantic study definition derived from legacy launch inputs."""

    driver_profile: DriverProfile
    study_environment: StudyEnvironment
    hard_constraints: HardConstraints
    acoustic_targets: AcousticTargets
    geometry_preferences: GeometryPreferences
    search_policy: SearchPolicy
    notes: list[str] = field(default_factory=list)

    def to_legacy_product_constraints(self) -> ProductConstraints:
        """Rebuild a legacy `ProductConstraints` object for compatibility."""
        legacy_horizontal = self.hard_constraints.metadata.get("legacy.symmetric_horizontal", True)
        legacy_vertical = self.hard_constraints.metadata.get("legacy.symmetric_vertical", True)
        notes = _dedupe_notes(
            list(self.hard_constraints.notes),
            list(self.acoustic_targets.notes),
            list(self.notes),
        )
        return ProductConstraints(
            max_baffle_width_mm=self.hard_constraints.max_baffle_width_mm,
            max_baffle_height_mm=self.hard_constraints.max_baffle_height_mm,
            max_depth_mm=self.hard_constraints.max_depth_mm,
            min_wall_thickness_mm=self.hard_constraints.min_wall_thickness_mm,
            target_bw_h_deg=self.acoustic_targets.target_bw_h_deg,
            target_bw_v_deg=self.acoustic_targets.target_bw_v_deg,
            target_low_freq_hz=self.acoustic_targets.target_low_freq_hz,
            target_high_freq_hz=self.acoustic_targets.target_high_freq_hz,
            symmetric_horizontal=bool(legacy_horizontal),
            symmetric_vertical=bool(legacy_vertical),
            notes=notes,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation of the full study definition."""
        return {
            "driver_profile": self.driver_profile.to_dict(),
            "study_environment": self.study_environment.to_dict(),
            "hard_constraints": self.hard_constraints.to_dict(),
            "acoustic_targets": self.acoustic_targets.to_dict(),
            "geometry_preferences": self.geometry_preferences.to_dict(),
            "search_policy": self.search_policy.to_dict(),
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class CanonicalTrialRecipeBuild:
    """Canonical trial recipe plus a traceable source summary."""

    recipe: DesignRecipe
    source_summary: dict[str, Any]


def _safe_template(base_template: DesignRecipe | None) -> DesignRecipe:
    return base_template or DesignRecipe()


def _filtered_template_ath_overrides(base_template: DesignRecipe | None) -> dict[str, Any]:
    template = _safe_template(base_template)
    return {
        str(key): value
        for key, value in dict(template.ath_overrides).items()
        if str(key) not in CANONICAL_TEMPLATE_ATH_OVERRIDE_BLOCKLIST
    }


def _filtered_template_bem_overrides(base_template: DesignRecipe | None) -> dict[str, Any]:
    template = _safe_template(base_template)
    return {
        str(key): value
        for key, value in dict(template.bem_overrides).items()
        if str(key) not in CANONICAL_TEMPLATE_BEM_OVERRIDE_BLOCKLIST
    }


class CanonicalTrialRecipeBuilder:
    """Build a full trial recipe from semantic study layers and decoded params.

    This builder is the canonical source of truth for trial geometry. It avoids
    residual `replace(base_recipe, ...)` composition by assigning every recipe
    field from an explicit owner:

    - StudyEnvironment owns BEM/source/symmetry runtime settings.
    - HardConstraints + AcousticTargets feed the fixed mouth-geometry policy.
    - Active decoded params own the currently optimized geometry dimensions.
    - The optional base template only supplies non-optimized family/mode fields
      and non-conflicting override blocks.
    """

    def __init__(
        self,
        *,
        study_definition: StudyDefinition,
        driver_profile: DriverProfile,
        base_template: DesignRecipe | None = None,
    ) -> None:
        self.study_definition = study_definition
        self.driver_profile = driver_profile
        self.base_template = _safe_template(base_template)

    def _canonical_mouth_geometry(self, params: dict[str, Any]) -> tuple[float, float, float, str]:
        """Return canonical mouth geometry for the current policy."""
        legacy_constraints = self.study_definition.to_legacy_product_constraints()
        mouth_width, mouth_height, corner_radius = baseline_mouth_geometry_policy(self.driver_profile, legacy_constraints)
        source = "baseline_mouth_geometry_policy"
        if self.study_definition.search_policy.optimize_mouth_width and "mouth_width" in params:
            mouth_width = float(params["mouth_width"])
            source = "search_policy.optimize_mouth_width"
        if self.study_definition.search_policy.optimize_mouth_height and "mouth_height" in params:
            mouth_height = float(params["mouth_height"])
            source = "search_policy.optimize_mouth_height" if source == "baseline_mouth_geometry_policy" else f"{source}+height"
        if "mouth_corner_radius" in params:
            corner_radius = float(params["mouth_corner_radius"])
            source = "search_policy.explicit_mouth_corner_radius" if source == "baseline_mouth_geometry_policy" else f"{source}+corner"
        return (float(mouth_width), float(mouth_height), float(corner_radius), source)

    def build(self, active_params: dict[str, Any]) -> CanonicalTrialRecipeBuild:
        """Build the canonical trial recipe from semantic layers and decoded params."""
        params = dict(active_params)
        template = self.base_template
        environment = self.study_definition.study_environment
        targets = self.study_definition.acoustic_targets
        hard = self.study_definition.hard_constraints

        if "throat_diameter" in params:
            throat_diameter = float(params["throat_diameter"])
            throat_source = "decoded_params.throat_diameter"
        elif hard.fixed_throat_diameter_mm is not None:
            throat_diameter = float(hard.fixed_throat_diameter_mm)
            throat_source = "hard_constraints.fixed_throat_diameter_mm"
        else:
            throat_diameter = float(template.throat_diameter)
            throat_source = "base_template.throat_diameter_fallback"

        if "horn_length" in params:
            horn_length = float(params["horn_length"])
            horn_source = "decoded_params.horn_length"
        elif self.study_definition.geometry_preferences.preferred_horn_length_mm is not None:
            horn_length = float(self.study_definition.geometry_preferences.preferred_horn_length_mm)
            horn_source = "geometry_preferences.preferred_horn_length_mm"
        else:
            horn_length = float(template.horn_length)
            horn_source = "base_template.horn_length_fallback"

        if "coverage_angle" in params:
            coverage_angle = float(params["coverage_angle"])
            coverage_source = "decoded_params.coverage_angle"
        else:
            target_candidates = [
                float(value)
                for value in (targets.target_bw_h_deg, targets.target_bw_v_deg)
                if value is not None
            ]
            if target_candidates:
                coverage_angle = sum(target_candidates) / len(target_candidates)
                coverage_source = "acoustic_targets.target_bw_*"
            else:
                coverage_angle = float(template.coverage_angle)
                coverage_source = "base_template.coverage_angle_fallback"

        mouth_width, mouth_height, mouth_corner_radius, mouth_source = self._canonical_mouth_geometry(params)

        ath_overrides = _filtered_template_ath_overrides(template)
        for key, default in OSSE_DEFAULT_VALUES.items():
            override_key = str(key).removeprefix("ath_overrides.")
            ath_overrides[override_key] = float(template.ath_overrides.get(override_key, default))
        for key, value in params.items():
            if str(key).startswith("ath_overrides."):
                ath_overrides[str(key).removeprefix("ath_overrides.")] = value

        bem_overrides = _filtered_template_bem_overrides(template)
        for key, value in params.items():
            if str(key).startswith("bem_overrides."):
                bem_overrides[str(key).removeprefix("bem_overrides.")] = value

        note_parts = [part for part in [template.notes.strip()] if part]
        note_parts.append("[canonical-builder] environment=StudyEnvironment")
        note_parts.append(f"[canonical-builder] mouth_policy={mouth_source}")
        recipe = DesignRecipe(
            case_name=str(template.case_name),
            throat_diameter=float(throat_diameter),
            horn_length=float(horn_length),
            coverage_angle=float(coverage_angle),
            flare_style=str(template.flare_style),
            mouth_shape=str(template.mouth_shape),
            mouth_width=float(mouth_width),
            mouth_height=float(mouth_height),
            mouth_corner_radius=float(mouth_corner_radius),
            source_mode=str(environment.source_mode),
            source_shape=str(template.source_shape),
            source_velocity=float(environment.source_velocity),
            auto_enclosure_enabled=bool(environment.auto_enclosure_enabled),
            output_abec_project_enabled=bool(template.output_abec_project_enabled),
            bem_f1=float(environment.bem_f1),
            bem_f2=float(environment.bem_f2),
            bem_num_freq=int(environment.bem_num_freq),
            observation_plane=str(environment.observation_plane),
            mic_distance=float(environment.mic_distance),
            symmetry_enabled=bool(environment.symmetry_enabled),
            symmetry_planes=tuple(environment.symmetry_planes),
            notes=" | ".join(note_parts),
            ath_overrides=ath_overrides,
            bem_overrides=bem_overrides,
        )
        recipe.assert_valid()
        source_summary = {
            "builder": "CanonicalTrialRecipeBuilder",
            "geometry_source_of_truth": "semantic_study_layers+decoded_params",
            "throat_source": throat_source,
            "horn_length_source": horn_source,
            "coverage_source": coverage_source,
            "mouth_geometry_policy": mouth_source,
            "mouth_geometry": {
                "mouth_width": float(mouth_width),
                "mouth_height": float(mouth_height),
                "mouth_corner_radius": float(mouth_corner_radius),
            },
            "environment_source": "StudyEnvironment",
            "template_fields_used": {
                "case_name": str(template.case_name),
                "flare_style": str(template.flare_style),
                "mouth_shape": str(template.mouth_shape),
                "source_shape": str(template.source_shape),
                "output_abec_project_enabled": bool(template.output_abec_project_enabled),
            },
            "ath_override_keys": sorted(ath_overrides),
            "bem_override_keys": sorted(bem_overrides),
            "active_param_keys": sorted(str(key) for key in params),
        }
        return CanonicalTrialRecipeBuild(recipe=recipe, source_summary=source_summary)


def build_trial_recipe(
    *,
    study_definition: StudyDefinition,
    active_params: dict[str, Any],
    driver_profile: DriverProfile,
    base_template: DesignRecipe | None = None,
) -> DesignRecipe:
    """Convenience wrapper that returns only the canonical `DesignRecipe`."""
    builder = CanonicalTrialRecipeBuilder(
        study_definition=study_definition,
        driver_profile=driver_profile,
        base_template=base_template,
    )
    return builder.build(active_params).recipe


def adapt_legacy_study_inputs(
    *,
    legacy_config: Any,
    base_recipe: DesignRecipe,
    driver_profile: DriverProfile,
    product_constraints: ProductConstraints,
) -> StudyDefinition:
    """Adapt legacy config/recipe/constraint inputs into semantic study layers.

    `legacy_config` is intentionally typed as `Any` to avoid coupling this module
    back to `study_runner.OptunaStudyConfig`. The adapter expects an object with
    `stage`, `target_bw_h_deg`, and `target_bw_v_deg` attributes.
    """
    stage = str(getattr(legacy_config, "stage", "final") or "final")
    objective_config = build_default_objective_config(stage=stage)

    target_bw_h = getattr(legacy_config, "target_bw_h_deg", None)
    target_bw_v = getattr(legacy_config, "target_bw_v_deg", None)
    resolved_target_bw_h = float(target_bw_h) if target_bw_h is not None else product_constraints.target_bw_h_deg
    resolved_target_bw_v = float(target_bw_v) if target_bw_v is not None else product_constraints.target_bw_v_deg

    source_velocity = _positive_or_none(base_recipe.source_velocity) or DEFAULT_SOURCE_VELOCITY
    environment_notes: list[str] = []
    if _positive_or_none(base_recipe.source_velocity) is None:
        environment_notes.append("source_velocity was missing or invalid in the base recipe and fell back to 1.0.")
    environment_notes.append("StudyEnvironment stays fixed during optimization and never enters the design space.")
    study_environment = StudyEnvironment(
        bem_f1=float(base_recipe.bem_f1),
        bem_f2=float(base_recipe.bem_f2),
        bem_num_freq=int(base_recipe.bem_num_freq),
        observation_plane=str(base_recipe.observation_plane).strip().upper(),
        mic_distance=float(base_recipe.mic_distance),
        symmetry_enabled=bool(base_recipe.symmetry_enabled),
        symmetry_planes=tuple(str(axis) for axis in base_recipe.symmetry_planes),
        source_mode=str(base_recipe.source_mode),
        source_velocity=float(source_velocity),
        auto_enclosure_enabled=bool(base_recipe.auto_enclosure_enabled),
        notes=environment_notes,
    )

    hard_constraints = HardConstraints(
        max_baffle_width_mm=product_constraints.max_baffle_width_mm,
        max_baffle_height_mm=product_constraints.max_baffle_height_mm,
        max_depth_mm=product_constraints.max_depth_mm,
        min_wall_thickness_mm=product_constraints.min_wall_thickness_mm,
        fixed_throat_diameter_mm=driver_profile.throat_diameter_mm,
        mounting_flange_diameter_mm=driver_profile.mounting_flange_diameter_mm,
        bolt_circle_diameter_mm=driver_profile.bolt_circle_diameter_mm,
        bolt_count=driver_profile.bolt_count,
        max_outer_diameter_mm=driver_profile.max_outer_diameter_mm,
        notes=_dedupe_notes(
            list(product_constraints.notes),
            ["HardConstraints only carry non-negotiable packaging / installation limits."],
        ),
        metadata={
            "legacy.symmetric_horizontal": bool(product_constraints.symmetric_horizontal),
            "legacy.symmetric_vertical": bool(product_constraints.symmetric_vertical),
        },
    )

    acoustic_targets = AcousticTargets(
        target_bw_h_deg=resolved_target_bw_h,
        target_bw_v_deg=resolved_target_bw_v,
        target_low_freq_hz=product_constraints.target_low_freq_hz,
        target_high_freq_hz=product_constraints.target_high_freq_hz,
        score_band_cov_hz=tuple(objective_config.freq_band_cov_hz),
        score_band_room_hz=tuple(objective_config.freq_band_room_hz),
        score_band_load_hz=tuple(objective_config.freq_band_load_hz),
        stage=stage,
        notes=[
            "AcousticTargets carry beamwidth and score-band intent; they are not packaging limits.",
        ],
    )

    geometry_preferences = GeometryPreferences(
        preferred_mouth_width_mm=_positive_or_none(base_recipe.mouth_width),
        preferred_mouth_height_mm=_positive_or_none(base_recipe.mouth_height),
        preferred_horn_length_mm=_positive_or_none(base_recipe.horn_length),
        mouth_width_tolerance_mm=_preference_tolerance(_positive_or_none(base_recipe.mouth_width)),
        mouth_height_tolerance_mm=_preference_tolerance(_positive_or_none(base_recipe.mouth_height)),
        horn_length_tolerance_mm=_preference_tolerance(_positive_or_none(base_recipe.horn_length)),
        notes=[
            "GeometryPreferences adapt legacy base-recipe dimensions into soft geometry targets.",
            "These preferences regularize scoring but do not become hard feasibility limits.",
        ],
    )

    search_policy = SearchPolicy(
        optimize_throat_diameter=(driver_profile.throat_diameter_mm is None),
        optimize_horn_length=True,
        optimize_coverage_angle=True,
        optimize_osse=True,
        optimize_mouth_width=False,
        optimize_mouth_height=False,
        optimize_flare=False,
        optimize_gcurve=False,
        optimize_morph=False,
        notes=[
            "Current policy keeps mouth family, flare, GCurve, and Morph disabled while the semantic study-definition layer settles.",
        ],
    )

    notes = [
        "Legacy optimizer inputs were adapted into StudyEnvironment / HardConstraints / AcousticTargets / GeometryPreferences / SearchPolicy layers.",
    ]
    if driver_profile.metadata.get("source") == "recipe_inference":
        notes.append("DriverProfile is currently inferred from the base recipe.")
    return StudyDefinition(
        driver_profile=driver_profile,
        study_environment=study_environment,
        hard_constraints=hard_constraints,
        acoustic_targets=acoustic_targets,
        geometry_preferences=geometry_preferences,
        search_policy=search_policy,
        notes=notes,
    )
