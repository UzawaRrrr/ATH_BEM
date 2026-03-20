"""Reduced-mesh validation and mirrored mesh generation for symmetry solving."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import meshio
import numpy as np

from mesh_adapter import PreparedMesh
from symmetry import AXIS_TO_INDEX, ImageTransform, SymmetryConfig


@dataclass
class SymmetryValidationReport:
    """Summary of reduced-mesh checks against configured symmetry planes."""

    valid: bool
    side_sign_by_axis: dict[str, int]
    vertices_on_plane_by_axis: dict[str, int]
    plane_face_count_by_axis: dict[str, int]
    crossing_triangle_count_by_axis: dict[str, int]
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "side_sign_by_axis": self.side_sign_by_axis,
            "vertices_on_plane_by_axis": self.vertices_on_plane_by_axis,
            "plane_face_count_by_axis": self.plane_face_count_by_axis,
            "crossing_triangle_count_by_axis": self.crossing_triangle_count_by_axis,
            "warnings": self.warnings,
        }


@dataclass
class MirroredMesh:
    """A mirrored copy of the reduced boundary mesh."""

    name: str
    image: ImageTransform
    mesh_file: Path
    determinant: float
    orientation_reversing: bool
    winding_reversed: bool


def is_orientation_reversing(image: ImageTransform) -> bool:
    """Return True if the image transform flips orientation (determinant < 0)."""
    matrix = np.asarray(image.matrix, dtype=float)
    determinant = float(np.linalg.det(matrix))
    return determinant < 0.0


def validate_reduced_mesh_against_symmetry(
    prepared_mesh: PreparedMesh,
    symmetry: SymmetryConfig,
) -> SymmetryValidationReport:
    """Check that the imported mesh is a valid half/quarter reduced model."""
    points = np.asarray(prepared_mesh.points, dtype=float)
    triangles = np.asarray(prepared_mesh.triangles, dtype=np.int64)
    tolerance = symmetry.tolerance

    side_sign_by_axis: dict[str, int] = {}
    vertices_on_plane_by_axis: dict[str, int] = {}
    plane_face_count_by_axis: dict[str, int] = {}
    crossing_triangle_count_by_axis: dict[str, int] = {}
    warnings: list[str] = []

    for plane in symmetry.planes:
        axis_index = AXIS_TO_INDEX[plane.axis]
        signed = points[:, axis_index] - plane.value
        positive = int(np.count_nonzero(signed > tolerance))
        negative = int(np.count_nonzero(signed < -tolerance))
        on_plane = int(np.count_nonzero(np.abs(signed) <= tolerance))

        if positive and negative:
            side_sign = 0
        elif positive:
            side_sign = 1
        elif negative:
            side_sign = -1
        else:
            side_sign = 0

        tri_signed = signed[triangles]
        crossing = int(np.count_nonzero((np.min(tri_signed, axis=1) < -tolerance) & (np.max(tri_signed, axis=1) > tolerance)))
        on_plane_faces = int(np.count_nonzero(np.max(np.abs(tri_signed), axis=1) <= tolerance))

        side_sign_by_axis[plane.axis] = side_sign
        vertices_on_plane_by_axis[plane.axis] = on_plane
        plane_face_count_by_axis[plane.axis] = on_plane_faces
        crossing_triangle_count_by_axis[plane.axis] = crossing

        if side_sign == 0 and (positive or negative):
            raise ValueError(
                f"Mesh spans both sides of symmetry plane {plane.axis}={plane.value:.6g}; "
                "this is not a valid reduced half/quarter model."
            )
        if crossing > 0:
            raise ValueError(
                f"Mesh has {crossing} triangles crossing symmetry plane {plane.axis}={plane.value:.6g}; "
                "please cut the mesh exactly on the symmetry plane."
            )
        if symmetry.require_strict_reduced_mesh and on_plane_faces > 0:
            raise ValueError(
                f"Mesh contains {on_plane_faces} triangles lying on symmetry plane {plane.axis}={plane.value:.6g}. "
                "Do not include cut-cap symmetry faces in the reduced boundary mesh."
            )
        if on_plane > 0:
            warnings.append(
                f"Plane {plane.axis}={plane.value:.6g}: detected {on_plane} vertices on the symmetry rim."
            )

    return SymmetryValidationReport(
        valid=True,
        side_sign_by_axis=side_sign_by_axis,
        vertices_on_plane_by_axis=vertices_on_plane_by_axis,
        plane_face_count_by_axis=plane_face_count_by_axis,
        crossing_triangle_count_by_axis=crossing_triangle_count_by_axis,
        warnings=warnings,
    )


def write_mirrored_meshes(
    prepared_mesh: PreparedMesh,
    images: list[ImageTransform],
    output_dir: Path,
) -> list[MirroredMesh]:
    """Write mirrored reduced meshes while preserving triangle and group ordering."""
    output_dir.mkdir(parents=True, exist_ok=True)
    field_data = {
        f"group_{group_id}": np.asarray([group_id, 2], dtype=np.int32)
        for group_id in sorted(set(int(value) for value in prepared_mesh.group_ids.tolist()))
    }

    base_triangles = np.asarray(prepared_mesh.triangles, dtype=np.int64)
    mirrored_meshes: list[MirroredMesh] = []
    for image in images:
        mirrored_points = image.apply_to_points(np.asarray(prepared_mesh.points, dtype=float))
        matrix = np.asarray(image.matrix, dtype=float)
        determinant = float(np.linalg.det(matrix))
        orientation_reversing = is_orientation_reversing(image)
        mirrored_triangles = (
            base_triangles[:, [0, 2, 1]]
            if orientation_reversing
            else base_triangles
        )
        mesh = meshio.Mesh(
            points=mirrored_points,
            cells=[("triangle", mirrored_triangles)],
            cell_data={
                "gmsh:physical": [np.asarray(prepared_mesh.group_ids, dtype=np.int32)],
                "gmsh:geometrical": [np.asarray(prepared_mesh.group_ids, dtype=np.int32)],
            },
            field_data=field_data,
        )
        mesh_file = output_dir / f"boundary_{image.name}.msh"
        meshio.write(mesh_file, mesh, file_format="gmsh22")
        mirrored_meshes.append(
            MirroredMesh(
                name=image.name,
                image=image,
                mesh_file=mesh_file,
                determinant=determinant,
                orientation_reversing=orientation_reversing,
                winding_reversed=orientation_reversing,
            )
        )

    return mirrored_meshes
