"""Adapt ATH-generated `.msh` files into a Bempp-friendly surface mesh."""

from __future__ import annotations

from collections import Counter, defaultdict
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
    total_area_m2: float
    area_per_group_m2: dict[str, float]
    boundary_edge_count: int
    nonmanifold_edge_count: int
    connected_component_count: int
    boundary_role_diagnostics: dict[str, object] | None = None

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
            "total_area_m2": self.total_area_m2,
            "area_per_group_m2": self.area_per_group_m2,
            "boundary_edge_count": self.boundary_edge_count,
            "nonmanifold_edge_count": self.nonmanifold_edge_count,
            "connected_component_count": self.connected_component_count,
            "boundary_role_diagnostics": self.boundary_role_diagnostics or {},
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


def _resolve_mesh_file_for_runtime(job: BemJob) -> str:
    candidates = [str(job.mesh_file_wsl or "").strip(), str(job.mesh_file or "").strip()]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    for candidate in candidates:
        if candidate:
            return candidate
    raise ValueError("No mesh file path is available in job payload.")


def _triangle_areas(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    p0 = points[triangles[:, 0]]
    p1 = points[triangles[:, 1]]
    p2 = points[triangles[:, 2]]
    cross = np.cross(p1 - p0, p2 - p0)
    return 0.5 * np.linalg.norm(cross, axis=1)


def _edge_topology_stats(triangles: np.ndarray) -> tuple[int, int, int]:
    edge_to_triangles: dict[tuple[int, int], list[int]] = {}
    for tri_index, (a, b, c) in enumerate(np.asarray(triangles, dtype=np.int64)):
        for u, v in ((int(a), int(b)), (int(b), int(c)), (int(c), int(a))):
            edge = (u, v) if u < v else (v, u)
            edge_to_triangles.setdefault(edge, []).append(tri_index)

    boundary_edge_count = 0
    nonmanifold_edge_count = 0
    parent = list(range(len(triangles)))

    def find_root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find_root(left)
        root_right = find_root(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for attached in edge_to_triangles.values():
        if len(attached) == 1:
            boundary_edge_count += 1
            continue
        if len(attached) > 2:
            nonmanifold_edge_count += 1
        first = attached[0]
        for other in attached[1:]:
            union(first, other)

    connected_component_count = len({find_root(index) for index in range(len(triangles))})
    return boundary_edge_count, nonmanifold_edge_count, connected_component_count


def prepare_boundary_mesh(job: BemJob) -> PreparedMesh:
    mesh = meshio.read(_resolve_mesh_file_for_runtime(job))
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
    triangle_areas = _triangle_areas(points, active_triangles)
    total_area_m2 = float(np.sum(triangle_areas))
    area_per_group_raw: dict[int, float] = defaultdict(float)
    for group_id, area in zip(active_group_ids.tolist(), triangle_areas.tolist()):
        area_per_group_raw[int(group_id)] += float(area)
    area_per_group_m2 = {
        str(group_id): float(area_per_group_raw[group_id]) for group_id in sorted(area_per_group_raw)
    }
    boundary_edge_count, nonmanifold_edge_count, connected_component_count = _edge_topology_stats(active_triangles)

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
        total_area_m2=total_area_m2,
        area_per_group_m2=area_per_group_m2,
        boundary_edge_count=boundary_edge_count,
        nonmanifold_edge_count=nonmanifold_edge_count,
        connected_component_count=connected_component_count,
    )
    if nonmanifold_edge_count > 0:
        mesh_info.warnings.append(
            f"Mesh has {nonmanifold_edge_count} non-manifold edges; BEM coupling may be unreliable."
        )
    if connected_component_count > 1:
        mesh_info.warnings.append(
            f"Boundary has {connected_component_count} disconnected surface components."
        )
    if len(active_groups) <= 1:
        mesh_info.warnings.append(
            "Only one active mesh group was detected; verify that waveguide wall and source surfaces were both exported."
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


def assess_boundary_role_coverage(job: BemJob, prepared_mesh: PreparedMesh) -> tuple[dict[str, object], list[str]]:
    """Compute source/wall coverage diagnostics for imported acoustic boundary mesh."""

    area_per_group = {
        int(group_id): float(area) for group_id, area in prepared_mesh.mesh_info.area_per_group_m2.items()
    }
    available_groups = set(int(group_id) for group_id in prepared_mesh.mesh_info.active_groups)
    source_set = set(int(group_id) for group_id in job.source_groups)
    wall_set = set(int(group_id) for group_id in job.wall_groups)

    source_present = sorted(source_set & available_groups)
    wall_present = sorted(wall_set & available_groups)
    source_area_m2 = float(sum(area_per_group.get(group_id, 0.0) for group_id in source_present))
    wall_area_m2 = float(sum(area_per_group.get(group_id, 0.0) for group_id in wall_present))
    total_area_m2 = max(float(prepared_mesh.mesh_info.total_area_m2), np.finfo(float).tiny)
    source_area_ratio = float(source_area_m2 / total_area_m2)
    wall_area_ratio = float(wall_area_m2 / total_area_m2)

    diagnostics = {
        "available_groups": sorted(available_groups),
        "source_groups_present": source_present,
        "wall_groups_present": wall_present,
        "source_area_m2": source_area_m2,
        "wall_area_m2": wall_area_m2,
        "total_area_m2": float(prepared_mesh.mesh_info.total_area_m2),
        "source_area_ratio": source_area_ratio,
        "wall_area_ratio": wall_area_ratio,
        "boundary_edge_count": int(prepared_mesh.mesh_info.boundary_edge_count),
        "nonmanifold_edge_count": int(prepared_mesh.mesh_info.nonmanifold_edge_count),
        "connected_component_count": int(prepared_mesh.mesh_info.connected_component_count),
    }

    warnings: list[str] = []
    if not wall_present:
        warnings.append(
            "No rigid wall groups are present in the active boundary mesh. "
            "This behaves like an open/source-only radiator, not a coupled waveguide boundary."
        )
    if source_area_ratio >= 0.95:
        warnings.append(
            f"Source area occupies {source_area_ratio:.1%} of active boundary area; "
            "check physical groups because wall surfaces may be missing."
        )
    if prepared_mesh.mesh_info.group_source.startswith("synthetic"):
        warnings.append(
            "Group IDs are synthetic triangle indices; physical group mapping is unavailable. "
            "Source/wall assignment is likely unreliable."
        )
    if prepared_mesh.mesh_info.nonmanifold_edge_count > 0:
        warnings.append(
            f"Detected {prepared_mesh.mesh_info.nonmanifold_edge_count} non-manifold edges; "
            "acoustic boundary conditions may not represent the intended wall coupling."
        )
    if prepared_mesh.mesh_info.connected_component_count > 1:
        warnings.append(
            f"Detected {prepared_mesh.mesh_info.connected_component_count} disconnected boundary components; "
            "verify that throat/source and waveguide walls are in the same acoustic boundary."
        )

    return diagnostics, warnings
