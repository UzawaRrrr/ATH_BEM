"""Adapt ATH-generated `.msh` files into a Bempp-friendly surface mesh."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import meshio
import numpy as np

from job_model import BemJob


@dataclass
class MeshInfo:
    mesh_file: str
    group_source: str
    detected_groups: list[int]
    active_groups: list[int]
    element_count_per_group: dict[str, int]
    active_element_count_per_group: dict[str, int]
    bbox: list[float]
    mesh_dimension: int
    warnings: list[str]
    vertices: int
    elements: int

    def to_dict(self) -> dict[str, object]:
        return {
            "mesh_file": self.mesh_file,
            "group_source": self.group_source,
            "detected_groups": self.detected_groups,
            "active_groups": self.active_groups,
            "element_count_per_group": self.element_count_per_group,
            "active_element_count_per_group": self.active_element_count_per_group,
            "bbox": self.bbox,
            "mesh_dimension": self.mesh_dimension,
            "warnings": self.warnings,
            "vertices": self.vertices,
            "elements": self.elements,
        }


@dataclass
class PreparedMesh:
    grid_file: Path
    points: np.ndarray
    triangles: np.ndarray
    group_ids: np.ndarray
    mesh_info: MeshInfo


def _bbox_from_points(points: np.ndarray) -> list[float]:
    mins = np.min(points, axis=0)
    maxs = np.max(points, axis=0)
    return [
        float(mins[0]),
        float(maxs[0]),
        float(mins[1]),
        float(maxs[1]),
        float(mins[2]),
        float(maxs[2]),
    ]


def _select_group_ids(mesh: meshio.Mesh, triangle_count: int) -> tuple[np.ndarray, str, list[str]]:
    warnings: list[str] = []
    physical = mesh.cell_data_dict.get("gmsh:physical", {}).get("triangle")
    if physical is not None and len(physical) == triangle_count and np.any(np.asarray(physical) > 0):
        return np.asarray(physical, dtype=np.int32), "gmsh:physical", warnings

    geometrical = mesh.cell_data_dict.get("gmsh:geometrical", {}).get("triangle")
    if geometrical is not None and len(geometrical) == triangle_count:
        warnings.append("Mesh has no positive gmsh:physical tags; using gmsh:geometrical entity tags as group IDs.")
        return np.asarray(geometrical, dtype=np.int32), "gmsh:geometrical", warnings

    warnings.append("Mesh has no gmsh group tags; using synthetic triangle indices as group IDs.")
    return np.arange(1, triangle_count + 1, dtype=np.int32), "synthetic:triangle_index", warnings


def prepare_boundary_mesh(job: BemJob) -> PreparedMesh:
    mesh = meshio.read(job.mesh_file_wsl or job.mesh_file)
    triangles = mesh.cells_dict.get("triangle")
    if triangles is None or len(triangles) == 0:
        raise ValueError("The mesh does not contain any triangle surface elements.")

    points = np.asarray(mesh.points, dtype=float)[:, :3] * job.mesh_scale_to_meter
    triangles = np.asarray(triangles, dtype=np.int64)
    group_ids, group_source, warnings = _select_group_ids(mesh, len(triangles))

    detected_counts = Counter(int(group_id) for group_id in group_ids.tolist())
    detected_groups = sorted(detected_counts)

    ignore_mask = np.ones(len(group_ids), dtype=bool)
    if job.ignore_groups:
        ignore_mask &= ~np.isin(group_ids, np.asarray(job.ignore_groups, dtype=np.int32))
        warnings.append(f"Ignoring groups from boundary import: {job.ignore_groups}")

    active_triangles = triangles[ignore_mask]
    active_group_ids = group_ids[ignore_mask].astype(np.int32)
    if len(active_triangles) == 0:
        raise ValueError("Ignoring the requested groups removed all triangles from the boundary mesh.")

    active_counts = Counter(int(group_id) for group_id in active_group_ids.tolist())
    active_groups = sorted(active_counts)

    field_data = {
        f"group_{group_id}": np.asarray([group_id, 2], dtype=np.int32)
        for group_id in active_groups
    }
    normalized_mesh = meshio.Mesh(
        points=points,
        cells=[("triangle", active_triangles)],
        cell_data={
            "gmsh:physical": [active_group_ids],
            "gmsh:geometrical": [active_group_ids],
        },
        field_data=field_data,
    )

    grid_file = job.job_dir / "boundary_scaled.msh"
    meshio.write(grid_file, normalized_mesh, file_format="gmsh22")

    mesh_info = MeshInfo(
        mesh_file=job.mesh_file,
        group_source=group_source,
        detected_groups=detected_groups,
        active_groups=active_groups,
        element_count_per_group={str(group_id): int(detected_counts[group_id]) for group_id in detected_groups},
        active_element_count_per_group={str(group_id): int(active_counts[group_id]) for group_id in active_groups},
        bbox=_bbox_from_points(points),
        mesh_dimension=2,
        warnings=warnings,
        vertices=int(len(points)),
        elements=int(len(active_triangles)),
    )
    return PreparedMesh(
        grid_file=grid_file,
        points=points,
        triangles=active_triangles,
        group_ids=active_group_ids,
        mesh_info=mesh_info,
    )


def resolve_wall_groups(job: BemJob, available_groups: list[int]) -> tuple[list[int], list[str]]:
    warnings: list[str] = []
    available = set(available_groups)
    missing_sources = sorted(group_id for group_id in job.source_groups if group_id not in available)
    if missing_sources:
        raise ValueError(f"source_groups were not found in the mesh: {missing_sources}")

    missing_explicit_walls = sorted(group_id for group_id in job.wall_groups if group_id not in available)
    if missing_explicit_walls:
        raise ValueError(f"wall_groups were not found in the mesh: {missing_explicit_walls}")

    unresolved = sorted(available - set(job.source_groups) - set(job.wall_groups))
    if job.interface_groups:
        warnings.append(
            "interface_groups are reserved for a future multi-domain solver; the listed groups are currently treated as rigid walls."
        )

    if not job.wall_groups:
        warnings.append("wall_groups was empty; all non-source groups are being treated as rigid walls.")
        return sorted(available - set(job.source_groups)), warnings

    if unresolved:
        warnings.append(
            "Some groups were not explicitly assigned as source or wall; treating them as rigid wall: "
            + ", ".join(str(group_id) for group_id in unresolved)
        )
    return sorted(set(job.wall_groups) | set(unresolved)), warnings
