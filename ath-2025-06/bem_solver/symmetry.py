"""Symmetry configuration, validation, and image transform helpers."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Literal

Axis = Literal["x", "y", "z"]
Parity = Literal["even", "odd"]

AXIS_TO_INDEX: dict[Axis, int] = {"x": 0, "y": 1, "z": 2}


@dataclass(frozen=True)
class SymmetryPlane:
    """One Cartesian reflection plane used for model reduction."""

    axis: Axis
    value: float
    parity: Parity

    @property
    def sign(self) -> int:
        """Return +1 for even symmetry and -1 for odd symmetry."""
        return 1 if self.parity == "even" else -1

    @property
    def axis_index(self) -> int:
        """Return the coordinate index for the selected axis."""
        return AXIS_TO_INDEX[self.axis]


@dataclass(frozen=True)
class SymmetryConfig:
    """User-facing symmetry reduction settings."""

    enabled: bool = False
    planes: tuple[SymmetryPlane, ...] = ()
    tolerance: float = 1.0e-6
    require_strict_reduced_mesh: bool = True
    debug_full_rebuild: bool = False
    mode_label: str = "off"


@dataclass(frozen=True)
class ImageTransform:
    """A composed mirror transform used by the symmetry-reduced solver."""

    name: str
    matrix: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    offset: tuple[float, float, float]
    sign: int
    planes: tuple[SymmetryPlane, ...]

    def apply_to_points(self, points: object) -> object:
        """Apply the image transform to a set of 3D points."""
        import numpy as np

        matrix = np.asarray(self.matrix, dtype=float)
        offset = np.asarray(self.offset, dtype=float)
        point_array = np.asarray(points, dtype=float)
        return (point_array @ matrix.T) + offset


def _parse_plane(entry: dict[str, object]) -> SymmetryPlane:
    axis = str(entry.get("axis", "")).strip().lower()
    if axis not in AXIS_TO_INDEX:
        raise ValueError(f"Unsupported symmetry plane axis: {axis!r}")
    parity = str(entry.get("parity", "even")).strip().lower()
    if parity not in {"even", "odd"}:
        raise ValueError(f"Unsupported symmetry parity: {parity!r}")
    return SymmetryPlane(
        axis=axis,  # type: ignore[arg-type]
        value=float(entry.get("value", 0.0)),
        parity=parity,  # type: ignore[arg-type]
    )


def parse_symmetry_config(payload: dict[str, object] | None) -> SymmetryConfig:
    """Parse symmetry settings from job/config payload."""
    if not payload:
        return SymmetryConfig()

    enabled = bool(payload.get("enabled", False))
    plane_entries = payload.get("planes", [])
    if plane_entries is None:
        plane_entries = []
    if not isinstance(plane_entries, list):
        raise ValueError("symmetry.planes must be a list.")

    planes = tuple(_parse_plane(dict(entry)) for entry in plane_entries)
    config = SymmetryConfig(
        enabled=enabled and len(planes) > 0,
        planes=planes,
        tolerance=float(payload.get("tolerance", 1.0e-6)),
        require_strict_reduced_mesh=bool(payload.get("require_strict_reduced_mesh", True)),
        debug_full_rebuild=bool(payload.get("debug_full_rebuild", False)),
        mode_label=str(payload.get("mode_label", "custom" if planes else "off")),
    )
    validate_symmetry_config(config)
    return config


def validate_symmetry_config(config: SymmetryConfig) -> None:
    """Validate supported symmetry modes for the current solver."""
    if not config.enabled:
        return
    if not config.planes:
        raise ValueError("symmetry.enabled=true requires at least one plane.")
    if len(config.planes) > 2:
        raise ValueError("V1 symmetry reduction supports at most two orthogonal symmetry planes.")
    if config.tolerance <= 0:
        raise ValueError("symmetry.tolerance must be greater than zero.")

    axes = [plane.axis for plane in config.planes]
    if len(set(axes)) != len(axes):
        raise ValueError("symmetry planes must use distinct axes.")

    if len(config.planes) == 2:
        first, second = config.planes
        if first.axis == second.axis:
            raise ValueError("quarter-model symmetry requires two orthogonal axes.")


def build_image_transforms(config: SymmetryConfig) -> list[ImageTransform]:
    """Return all non-identity image transforms for the active symmetry set."""
    if not config.enabled:
        return []

    transforms: list[ImageTransform] = []
    for count in range(1, len(config.planes) + 1):
        for selected in combinations(config.planes, count):
            matrix = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
            offset = [0.0, 0.0, 0.0]
            sign = 1
            name_parts: list[str] = []
            for plane in selected:
                axis_index = plane.axis_index
                matrix[axis_index][axis_index] *= -1.0
                offset[axis_index] += 2.0 * plane.value
                sign *= plane.sign
                name_parts.append(f"{plane.axis}{'e' if plane.parity == 'even' else 'o'}")
            transforms.append(
                ImageTransform(
                    name="_".join(name_parts),
                    matrix=(tuple(matrix[0]), tuple(matrix[1]), tuple(matrix[2])),
                    offset=(offset[0], offset[1], offset[2]),
                    sign=sign,
                    planes=tuple(selected),
                )
            )
    return transforms
