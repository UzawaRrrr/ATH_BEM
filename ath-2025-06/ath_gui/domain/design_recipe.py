from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .bem_specs import BEM_FIELD_SECTIONS
from .config_core import default_horn_state


_VALID_SYMMETRY_PLANES = {"x", "y"}

BEM_FIELD_DEFAULTS = {
    spec.key: spec.default
    for _description, fields in BEM_FIELD_SECTIONS
    for spec in fields
}


def default_recipe_bem_state() -> dict[str, object]:
    return dict(BEM_FIELD_DEFAULTS)


@dataclass(slots=True)
class DesignRecipe:
    """High-level ATH+BEM design input that compiles into existing states."""

    case_name: str = "demo_case"
    throat_diameter: float = 25.4
    horn_length: float = 160.0
    coverage_angle: float = 90.0

    flare_style: str = "os"
    mouth_shape: str = "rect"
    mouth_width: float = 260.0
    mouth_height: float = 200.0
    mouth_corner_radius: float = 35.0

    source_mode: str = "normal"
    source_shape: str = "cap"
    source_velocity: float = 1.0

    auto_enclosure_enabled: bool = True
    output_abec_project_enabled: bool = True

    bem_f1: float = 200.0
    bem_f2: float = 20000.0
    bem_num_freq: int = 48
    observation_plane: str = "XZ"
    mic_distance: float = 5.0

    symmetry_enabled: bool = False
    symmetry_planes: tuple[str, ...] = field(default_factory=tuple)

    notes: str = ""

    ath_overrides: dict[str, object] = field(default_factory=dict)
    bem_overrides: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DesignRecipe":
        data = dict(payload)
        planes = data.get("symmetry_planes", ())
        if isinstance(planes, list):
            data["symmetry_planes"] = tuple(str(item) for item in planes)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema"] = "ath.design_recipe.v1"
        data["symmetry_planes"] = list(self.symmetry_planes)
        return data

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.case_name.strip():
            errors.append("case_name is required.")
        if any(ch in self.case_name for ch in '<>:"/\\|?*'):
            errors.append("case_name contains forbidden path characters.")
        if self.throat_diameter <= 0:
            errors.append("throat_diameter must be > 0.")
        if self.horn_length <= 0:
            errors.append("horn_length must be > 0.")
        if self.coverage_angle <= 0:
            errors.append("coverage_angle must be > 0.")
        if self.mouth_shape.strip().lower() != "keep":
            if self.mouth_width <= 0 or self.mouth_height <= 0:
                errors.append("mouth_width and mouth_height must be > 0 when mouth_shape is not `keep`.")
        if self.mouth_corner_radius < 0:
            errors.append("mouth_corner_radius must be >= 0.")
        if self.source_velocity <= 0:
            errors.append("source_velocity must be > 0.")
        if self.bem_f1 <= 0 or self.bem_f2 < self.bem_f1:
            errors.append("bem_f1/bem_f2 must satisfy 0 < bem_f1 <= bem_f2.")
        if self.bem_num_freq < 1:
            errors.append("bem_num_freq must be >= 1.")
        if self.mic_distance <= 0:
            errors.append("mic_distance must be > 0.")

        plane = self.observation_plane.strip().upper()
        if plane not in {"XZ", "YZ"}:
            errors.append("observation_plane must be XZ or YZ.")

        unknown_planes = [axis for axis in self.symmetry_planes if str(axis).lower() not in _VALID_SYMMETRY_PLANES]
        if unknown_planes:
            errors.append(f"Unsupported symmetry planes: {unknown_planes}")
        if self.symmetry_enabled and not self.symmetry_planes:
            errors.append("symmetry_planes must be set when symmetry_enabled is true.")

        if not isinstance(self.ath_overrides, dict):
            errors.append("ath_overrides must be an object.")
        if not isinstance(self.bem_overrides, dict):
            errors.append("bem_overrides must be an object.")
        return errors

    def assert_valid(self) -> None:
        errors = self.validate()
        if errors:
            raise ValueError("Invalid DesignRecipe: " + " | ".join(errors))

    def to_ath_state(self, *, base_state: dict[str, object] | None = None) -> dict[str, object]:
        self.assert_valid()
        state = default_horn_state() if base_state is None else dict(base_state)

        state["Throat.Diameter"] = f"{self.throat_diameter:g}"
        state["Length"] = f"{self.horn_length:g}"
        state["Coverage.Angle"] = f"{self.coverage_angle:g}"

        shape_key = self.mouth_shape.strip().lower()
        target_shape = {"keep": "0", "rect": "1", "round": "2"}.get(shape_key, "1")
        state["Morph.TargetShape"] = target_shape
        state["Morph.TargetWidth"] = f"{self.mouth_width:g}"
        state["Morph.TargetHeight"] = f"{self.mouth_height:g}"
        state["Morph.CornerRadius"] = f"{self.mouth_corner_radius:g}"

        source_shape = self.source_shape.strip().lower()
        state["Source.Shape"] = "2" if source_shape in {"disk", "piston", "flat"} else "1"
        source_mode = self.source_mode.strip().lower()
        state["Source.Velocity"] = "2" if source_mode in {"axial", "piston"} else "1"

        state["ABEC.f1"] = f"{self.bem_f1:g}"
        state["ABEC.f2"] = f"{self.bem_f2:g}"
        state["ABEC.NumFrequencies"] = str(int(self.bem_num_freq))

        state["Output.MSH"] = True
        state["Output.ABECProject"] = bool(self.output_abec_project_enabled)

        for key, value in self.ath_overrides.items():
            state[str(key)] = value
        return state

    def to_bem_state(self, *, base_state: dict[str, object] | None = None) -> dict[str, object]:
        self.assert_valid()
        state = default_recipe_bem_state() if base_state is None else dict(base_state)

        state["BEM.F1"] = f"{self.bem_f1:g}"
        state["BEM.F2"] = f"{self.bem_f2:g}"
        state["BEM.NumFreq"] = str(int(self.bem_num_freq))
        state["BEM.Plane"] = self.observation_plane.strip().upper()
        state["BEM.MicDistance"] = f"{self.mic_distance:g}"
        state["BEM.SourceGain"] = f"{self.source_velocity:g}"

        planes = {axis.lower() for axis in self.symmetry_planes}
        if not self.symmetry_enabled or not planes:
            symmetry_mode = "off"
        elif planes == {"x", "y"}:
            symmetry_mode = "quarter_xy_even_even"
            state["BEM.AngleRangeMode"] = "quarter_circle"
        elif planes == {"x"}:
            symmetry_mode = "half_x_even"
            state["BEM.AngleRangeMode"] = "half_circle"
        elif planes == {"y"}:
            symmetry_mode = "half_y_even"
            state["BEM.AngleRangeMode"] = "half_circle"
        else:
            symmetry_mode = "off"
        state["BEM.SymmetryMode"] = symmetry_mode

        for key, value in self.bem_overrides.items():
            state[str(key)] = value
        return state
