"""Driver and product constraint models for optimizer-side geometry gating.

This module deliberately keeps the rules conservative and geometry-first.
The derived limits are not intended to be exact acoustic theory; they are a
pre-filter that keeps the optimizer away from obviously incompatible or
unmanufacturable regions before ATH/mesh/BEM work starts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Mapping

from .conflict_policy import resolve_conflict_policy

SOUND_SPEED_MM_PER_S = 343_000.0
DEFAULT_BAFFLE_EDGE_MARGIN_MM = 8.0
DEFAULT_MIN_WALL_THICKNESS_MM = 3.0
DEFAULT_MIN_HORN_LENGTH_MM = 60.0
DEFAULT_COVERAGE_CENTER_DEG = 90.0
LOW_FREQ_MOUTH_WAVELENGTH_FACTOR = 0.35
LOW_FREQ_LENGTH_WAVELENGTH_FACTOR = 0.18
HORN_LENGTH_SPAN_FACTOR = 0.90
HORN_LENGTH_RATIO_FACTOR = 0.70
MOUTH_COVERAGE_EXPANSION_REFERENCE_DEG = 110.0
MOUTH_COVERAGE_EXPANSION_LIMIT = (1.0, 2.25)
HORN_COVERAGE_LENGTH_LIMIT = (0.80, 1.80)
BASE_RECIPE_LIMIT_MARGIN_FACTOR = 1.15
INFERRED_PRODUCT_CONSTRAINTS_NOTE = "Product constraints inferred from base recipe; explicit packaging limits are recommended."
COARSE_INFERRED_RELAXATION_NOTE = (
    "Coarse stage is using relaxed recipe-inferred constraints; inferred packaging limits were widened "
    "and low-frequency gating was disabled to avoid over-constraining the search space."
)
COARSE_INFERRED_DEPTH_CONFLICT_NOTE = (
    "Detected a conflict between inferred max_depth and derived horn-length guidance; coarse-stage inferred depth "
    "was widened to avoid an all-catastrophic preflight."
)
COARSE_INFERRED_BAFFLE_MARGIN_FACTOR = 1.45
COARSE_INFERRED_DEPTH_MARGIN_FACTOR = 1.60
COARSE_INFERRED_DEPTH_FLOOR_FACTOR = 1.10


def _clamp(value: float, low: float, high: float) -> float:
    return max(float(low), min(float(high), float(value)))


def _as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _as_notes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _dedupe_notes(*note_groups: list[str]) -> list[str]:
    ordered: list[str] = []
    for group in note_groups:
        for note in group:
            text = str(note).strip()
            if text and text not in ordered:
                ordered.append(text)
    return ordered


def _positive_or_none(*values: float | None) -> float | None:
    candidates = [float(value) for value in values if value is not None and float(value) > 0.0]
    if not candidates:
        return None
    return max(candidates)


def _default_coverage_range(driver_type: str, preferred_max: float | None) -> tuple[float, float]:
    upper = float(preferred_max) if preferred_max is not None else (110.0 if driver_type == "compression_driver" else 120.0)
    lower = 40.0 if driver_type == "compression_driver" else 50.0
    if upper < lower:
        upper = lower
    return (lower, upper)


def _recommended_coverage_range(target: float | None, profile: "DriverProfile") -> tuple[float, float]:
    if target is None:
        return _default_coverage_range(profile.driver_type, profile.preferred_max_coverage_deg)
    low = max(30.0, float(target) - 10.0)
    high_limit = float(profile.preferred_max_coverage_deg) if profile.preferred_max_coverage_deg is not None else 140.0
    high = min(high_limit, float(target) + 10.0)
    if high < low:
        high = low
    return (low, high)


def _coverage_scaled_mouth_dim(
    throat_diameter_mm: float | None,
    target_bw_deg: float | None,
    target_low_freq_hz: float | None,
    preferred_ratio: float,
) -> float | None:
    if throat_diameter_mm is None and target_low_freq_hz is None:
        return None
    estimate = None
    if throat_diameter_mm is not None:
        coverage_reference = DEFAULT_COVERAGE_CENTER_DEG if target_bw_deg is None else max(30.0, float(target_bw_deg))
        coverage_scale = _clamp(
            MOUTH_COVERAGE_EXPANSION_REFERENCE_DEG / coverage_reference,
            MOUTH_COVERAGE_EXPANSION_LIMIT[0],
            MOUTH_COVERAGE_EXPANSION_LIMIT[1],
        )
        estimate = float(throat_diameter_mm) * float(preferred_ratio) * coverage_scale
    if target_low_freq_hz is not None and target_low_freq_hz > 0.0:
        wavelength_mm = SOUND_SPEED_MM_PER_S / float(target_low_freq_hz)
        coverage_reference = DEFAULT_COVERAGE_CENTER_DEG if target_bw_deg is None else max(30.0, float(target_bw_deg))
        coverage_scale = _clamp(DEFAULT_COVERAGE_CENTER_DEG / coverage_reference, 0.75, 1.60)
        low_freq_estimate = wavelength_mm * LOW_FREQ_MOUTH_WAVELENGTH_FACTOR * coverage_scale
        estimate = low_freq_estimate if estimate is None else max(estimate, low_freq_estimate)
    return estimate


@dataclass(slots=True)
class DriverProfile:
    """Fixed physical data for a specific driver family or part number."""

    driver_id: str
    name: str
    driver_type: Literal["compression_driver", "direct_radiator", "other"]
    diaphragm_diameter_mm: float | None = None
    effective_diaphragm_diameter_mm: float | None = None
    throat_diameter_mm: float | None = None
    exit_angle_deg: float | None = None
    mounting_flange_diameter_mm: float | None = None
    bolt_circle_diameter_mm: float | None = None
    bolt_count: int | None = None
    min_adapter_length_mm: float | None = None
    max_outer_diameter_mm: float | None = None
    preferred_min_mouth_to_throat_ratio: float = 3.0
    preferred_max_coverage_deg: float | None = None
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DriverProfile":
        """Build a `DriverProfile` from a plain mapping."""
        data = dict(payload)
        return cls(
            driver_id=str(data["driver_id"]),
            name=str(data["name"]),
            driver_type=str(data["driver_type"]),  # type: ignore[arg-type]
            diaphragm_diameter_mm=_as_optional_float(data.get("diaphragm_diameter_mm")),
            effective_diaphragm_diameter_mm=_as_optional_float(data.get("effective_diaphragm_diameter_mm")),
            throat_diameter_mm=_as_optional_float(data.get("throat_diameter_mm")),
            exit_angle_deg=_as_optional_float(data.get("exit_angle_deg")),
            mounting_flange_diameter_mm=_as_optional_float(data.get("mounting_flange_diameter_mm")),
            bolt_circle_diameter_mm=_as_optional_float(data.get("bolt_circle_diameter_mm")),
            bolt_count=_as_optional_int(data.get("bolt_count")),
            min_adapter_length_mm=_as_optional_float(data.get("min_adapter_length_mm")),
            max_outer_diameter_mm=_as_optional_float(data.get("max_outer_diameter_mm")),
            preferred_min_mouth_to_throat_ratio=float(data.get("preferred_min_mouth_to_throat_ratio", 3.0)),
            preferred_max_coverage_deg=_as_optional_float(data.get("preferred_max_coverage_deg")),
            notes=_as_notes(data.get("notes")),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the profile."""
        return asdict(self)


@dataclass(slots=True)
class ProductConstraints:
    """Product, baffle, and packaging limits that bound horn geometry."""

    max_baffle_width_mm: float | None = None
    max_baffle_height_mm: float | None = None
    max_depth_mm: float | None = None
    min_wall_thickness_mm: float | None = None
    target_bw_h_deg: float | None = None
    target_bw_v_deg: float | None = None
    target_low_freq_hz: float | None = None
    target_high_freq_hz: float | None = None
    symmetric_horizontal: bool = True
    symmetric_vertical: bool = True
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProductConstraints":
        """Build `ProductConstraints` from a plain mapping."""
        data = dict(payload)
        return cls(
            max_baffle_width_mm=_as_optional_float(data.get("max_baffle_width_mm")),
            max_baffle_height_mm=_as_optional_float(data.get("max_baffle_height_mm")),
            max_depth_mm=_as_optional_float(data.get("max_depth_mm")),
            min_wall_thickness_mm=_as_optional_float(data.get("min_wall_thickness_mm")),
            target_bw_h_deg=_as_optional_float(data.get("target_bw_h_deg")),
            target_bw_v_deg=_as_optional_float(data.get("target_bw_v_deg")),
            target_low_freq_hz=_as_optional_float(data.get("target_low_freq_hz")),
            target_high_freq_hz=_as_optional_float(data.get("target_high_freq_hz")),
            symmetric_horizontal=bool(data.get("symmetric_horizontal", True)),
            symmetric_vertical=bool(data.get("symmetric_vertical", True)),
            notes=_as_notes(data.get("notes")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the constraints."""
        return asdict(self)


@dataclass(slots=True)
class DerivedDriverConstraints:
    """Derived geometry limits used by the optimizer-side design space."""

    fixed_throat_diameter_mm: float | None
    min_mouth_width_mm: float | None
    min_mouth_height_mm: float | None
    max_mouth_width_mm: float | None
    max_mouth_height_mm: float | None
    min_horn_length_mm: float | None
    max_horn_length_mm: float | None
    max_corner_radius_mm: float | None
    recommended_coverage_h_range_deg: tuple[float, float] | None
    recommended_coverage_v_range_deg: tuple[float, float] | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the derived limits."""
        return asdict(self)


def load_driver_profile(path: str | Path) -> DriverProfile:
    """Load a driver profile from a JSON file."""
    profile_path = Path(path).expanduser().resolve()
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    return DriverProfile.from_dict(payload)


def dump_driver_profile(path: str | Path, profile: DriverProfile) -> None:
    """Write a driver profile to a JSON file."""
    profile_path = Path(path).expanduser().resolve()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps(profile.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def is_recipe_inferred_constraints(product_constraints: ProductConstraints) -> bool:
    """Return whether the constraints were inferred from a `DesignRecipe` fallback."""
    notes = {str(note).strip() for note in product_constraints.notes}
    return INFERRED_PRODUCT_CONSTRAINTS_NOTE in notes


def relax_inferred_product_constraints(
    product_constraints: ProductConstraints,
    *,
    stage: str,
    min_depth_floor_mm: float | None = None,
) -> ProductConstraints:
    """Relax recipe-inferred constraints for early coarse-stage exploration.

    This helper only changes constraints that were inferred from a recipe fallback.
    Explicit user-provided packaging limits remain untouched. The coarse-stage
    relaxation widens inferred width/height/depth ceilings and disables the
    inferred low-frequency horn-length gate, because recipe-derived `bem_f1`
    should not behave like a hard geometry requirement during coarse search.
    """
    decision = resolve_conflict_policy(
        "inferred_constraints",
        stage=stage,
        constraints_are_inferred_fallback=is_recipe_inferred_constraints(product_constraints),
    )
    if decision.strategy != "relax_coarse_only":
        return product_constraints

    max_depth = (
        float(product_constraints.max_depth_mm) * COARSE_INFERRED_DEPTH_MARGIN_FACTOR
        if product_constraints.max_depth_mm is not None
        else None
    )
    if min_depth_floor_mm is not None:
        floor_depth = max(0.0, float(min_depth_floor_mm) * COARSE_INFERRED_DEPTH_FLOOR_FACTOR)
        max_depth = floor_depth if max_depth is None else max(max_depth, floor_depth)

    notes = _dedupe_notes(
        list(product_constraints.notes),
        [COARSE_INFERRED_RELAXATION_NOTE],
        [COARSE_INFERRED_DEPTH_CONFLICT_NOTE] if min_depth_floor_mm is not None else [],
    )
    return replace(
        product_constraints,
        max_baffle_width_mm=(
            float(product_constraints.max_baffle_width_mm) * COARSE_INFERRED_BAFFLE_MARGIN_FACTOR
            if product_constraints.max_baffle_width_mm is not None
            else None
        ),
        max_baffle_height_mm=(
            float(product_constraints.max_baffle_height_mm) * COARSE_INFERRED_BAFFLE_MARGIN_FACTOR
            if product_constraints.max_baffle_height_mm is not None
            else None
        ),
        max_depth_mm=max_depth,
        target_low_freq_hz=None,
        notes=notes,
    )


def derive_driver_constraints(
    profile: DriverProfile,
    product_constraints: ProductConstraints,
) -> DerivedDriverConstraints:
    """Derive conservative geometry limits from driver and product inputs.

    Heuristics used here are intentionally conservative and packaging-oriented:
    they are meant to reject obviously bad regions before expensive geometry and
    acoustics steps, not to claim exact waveguide theory. The mouth lower bounds
    combine throat ratio and coarse coverage/low-frequency estimates; the horn
    length lower bound grows with mouth expansion, requested coverage tightness,
    and low-frequency reach.
    """
    notes = list(profile.notes) + list(product_constraints.notes)
    wall_thickness = (
        float(product_constraints.min_wall_thickness_mm)
        if product_constraints.min_wall_thickness_mm is not None
        else DEFAULT_MIN_WALL_THICKNESS_MM
    )
    edge_margin = max(DEFAULT_BAFFLE_EDGE_MARGIN_MM, wall_thickness)

    fixed_throat = _as_optional_float(profile.throat_diameter_mm)
    preferred_ratio = max(1.5, float(profile.preferred_min_mouth_to_throat_ratio or 3.0))
    reference_width_min = _coverage_scaled_mouth_dim(
        fixed_throat,
        product_constraints.target_bw_h_deg,
        product_constraints.target_low_freq_hz,
        preferred_ratio,
    )
    reference_height_min = _coverage_scaled_mouth_dim(
        fixed_throat,
        product_constraints.target_bw_v_deg,
        product_constraints.target_low_freq_hz,
        preferred_ratio,
    )
    throat_ratio_min = fixed_throat * preferred_ratio if fixed_throat is not None else None
    min_mouth_width = _positive_or_none(reference_width_min, throat_ratio_min)
    min_mouth_height = _positive_or_none(reference_height_min, throat_ratio_min)

    max_mouth_width = None
    if product_constraints.max_baffle_width_mm is not None:
        max_mouth_width = max(0.0, float(product_constraints.max_baffle_width_mm) - (2.0 * edge_margin))
    max_mouth_height = None
    if product_constraints.max_baffle_height_mm is not None:
        max_mouth_height = max(0.0, float(product_constraints.max_baffle_height_mm) - (2.0 * edge_margin))

    reference_throat = fixed_throat
    if reference_throat is None:
        reference_throat = _positive_or_none(profile.effective_diaphragm_diameter_mm, profile.diaphragm_diameter_mm)
        if reference_throat is not None:
            reference_throat *= 0.35
    if reference_throat is None:
        reference_throat = 25.4

    coverage_values = [
        float(value)
        for value in (product_constraints.target_bw_h_deg, product_constraints.target_bw_v_deg)
        if value is not None
    ]
    coverage_reference = sum(coverage_values) / len(coverage_values) if coverage_values else DEFAULT_COVERAGE_CENTER_DEG
    coverage_factor = _clamp(
        MOUTH_COVERAGE_EXPANSION_REFERENCE_DEG / max(30.0, coverage_reference),
        HORN_COVERAGE_LENGTH_LIMIT[0],
        HORN_COVERAGE_LENGTH_LIMIT[1],
    )
    reference_mouth = _positive_or_none(min_mouth_width, min_mouth_height)
    if reference_mouth is None:
        reference_mouth = reference_throat * preferred_ratio
    expansion_ratio = max(1.0, reference_mouth / max(reference_throat, 1.0))
    span_length = max(0.0, reference_mouth - reference_throat) * HORN_LENGTH_SPAN_FACTOR * coverage_factor
    ratio_length = reference_throat * max(0.0, expansion_ratio - 1.0) * HORN_LENGTH_RATIO_FACTOR
    low_freq_length = None
    if product_constraints.target_low_freq_hz is not None and product_constraints.target_low_freq_hz > 0.0:
        wavelength_mm = SOUND_SPEED_MM_PER_S / float(product_constraints.target_low_freq_hz)
        low_freq_length = wavelength_mm * LOW_FREQ_LENGTH_WAVELENGTH_FACTOR * coverage_factor
    min_horn_length = max(
        DEFAULT_MIN_HORN_LENGTH_MM,
        float(profile.min_adapter_length_mm or 0.0),
        float(span_length),
        float(ratio_length),
        float(low_freq_length or 0.0),
    )
    max_horn_length = _as_optional_float(product_constraints.max_depth_mm)

    max_corner_radius = None
    corner_refs = [value for value in (max_mouth_width, max_mouth_height) if value is not None]
    if corner_refs:
        max_corner_radius = max(0.0, min(corner_refs) * 0.5 - wall_thickness)

    if fixed_throat is not None:
        notes.append("throat_diameter is fixed by the driver profile.")
    if max_mouth_width is not None and min_mouth_width is not None and max_mouth_width < min_mouth_width:
        notes.append("max mouth width from packaging is smaller than the derived minimum width.")
    if max_mouth_height is not None and min_mouth_height is not None and max_mouth_height < min_mouth_height:
        notes.append("max mouth height from packaging is smaller than the derived minimum height.")
    if max_horn_length is not None and max_horn_length < min_horn_length:
        notes.append("max depth is smaller than the derived minimum horn length.")

    return DerivedDriverConstraints(
        fixed_throat_diameter_mm=fixed_throat,
        min_mouth_width_mm=min_mouth_width,
        min_mouth_height_mm=min_mouth_height,
        max_mouth_width_mm=max_mouth_width,
        max_mouth_height_mm=max_mouth_height,
        min_horn_length_mm=min_horn_length,
        max_horn_length_mm=max_horn_length,
        max_corner_radius_mm=max_corner_radius,
        recommended_coverage_h_range_deg=_recommended_coverage_range(product_constraints.target_bw_h_deg, profile),
        recommended_coverage_v_range_deg=_recommended_coverage_range(product_constraints.target_bw_v_deg, profile),
        notes=notes,
    )


def infer_driver_profile_from_recipe(
    recipe: Any,
    *,
    driver_id: str = "inferred_driver",
    name: str = "Inferred Driver",
    driver_type: Literal["compression_driver", "direct_radiator", "other"] = "compression_driver",
) -> DriverProfile:
    """Build a conservative fallback profile from an existing `DesignRecipe`."""
    return DriverProfile(
        driver_id=driver_id,
        name=name,
        driver_type=driver_type,
        throat_diameter_mm=float(getattr(recipe, "throat_diameter", 25.4)),
        min_adapter_length_mm=max(0.0, float(getattr(recipe, "horn_length", DEFAULT_MIN_HORN_LENGTH_MM)) * 0.10),
        preferred_min_mouth_to_throat_ratio=3.0,
        preferred_max_coverage_deg=max(90.0, float(getattr(recipe, "coverage_angle", DEFAULT_COVERAGE_CENTER_DEG)) * 1.20),
        notes=["Profile inferred from base recipe; provide an explicit JSON profile for production studies."],
        metadata={"source": "recipe_inference"},
    )


def infer_product_constraints_from_recipe(
    recipe: Any,
    *,
    target_bw_h_deg: float | None = None,
    target_bw_v_deg: float | None = None,
) -> ProductConstraints:
    """Build fallback packaging constraints from an existing `DesignRecipe`."""
    mouth_width = max(0.0, float(getattr(recipe, "mouth_width", 0.0)))
    mouth_height = max(0.0, float(getattr(recipe, "mouth_height", 0.0)))
    horn_length = max(0.0, float(getattr(recipe, "horn_length", 0.0)))
    bem_f1 = float(getattr(recipe, "bem_f1", 0.0))
    bem_f2 = float(getattr(recipe, "bem_f2", 0.0))
    return ProductConstraints(
        max_baffle_width_mm=mouth_width * BASE_RECIPE_LIMIT_MARGIN_FACTOR if mouth_width > 0.0 else None,
        max_baffle_height_mm=mouth_height * BASE_RECIPE_LIMIT_MARGIN_FACTOR if mouth_height > 0.0 else None,
        max_depth_mm=horn_length * BASE_RECIPE_LIMIT_MARGIN_FACTOR if horn_length > 0.0 else None,
        min_wall_thickness_mm=DEFAULT_MIN_WALL_THICKNESS_MM,
        target_bw_h_deg=target_bw_h_deg if target_bw_h_deg is not None else float(getattr(recipe, "coverage_angle", DEFAULT_COVERAGE_CENTER_DEG)),
        target_bw_v_deg=target_bw_v_deg if target_bw_v_deg is not None else float(getattr(recipe, "coverage_angle", DEFAULT_COVERAGE_CENTER_DEG)),
        target_low_freq_hz=bem_f1 if bem_f1 > 0.0 else None,
        target_high_freq_hz=bem_f2 if bem_f2 > 0.0 else None,
        notes=[INFERRED_PRODUCT_CONSTRAINTS_NOTE],
    )
