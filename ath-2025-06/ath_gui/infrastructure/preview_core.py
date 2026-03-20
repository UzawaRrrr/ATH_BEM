from __future__ import annotations

from collections import Counter
from pathlib import Path


GROUP_SOURCE_LABELS = {
    "gmsh physical groups": "Gmsh 物理群組",
    "gmsh surface entities": "Gmsh 曲面實體",
    "unknown": "未知來源",
}


def describe_group_source(group_source: str) -> str:
    """Return a localized label for the preview/group source."""
    normalized = str(group_source).strip()
    if not normalized:
        return GROUP_SOURCE_LABELS["unknown"]
    return GROUP_SOURCE_LABELS.get(normalized, normalized)


def compute_output_directory(global_state: dict[str, object], horn_state: dict[str, object], cfg_path: Path) -> Path:
    dest_dir = str(horn_state.get("Output.DestDir", "")).strip()
    if dest_dir:
        return Path(dest_dir)

    output_root = str(global_state.get("OutputRootDir", "")).strip()
    base_dir = Path(output_root) if output_root else cfg_path.parent

    output_subdir = str(horn_state.get("Output.SubDir", "")).strip()
    if output_subdir:
        base_dir = base_dir / output_subdir

    return base_dir / cfg_path.stem


def iter_output_search_directories(output_dir: Path, cfg_path: Path) -> list[Path]:
    """Enumerate plausible ATH output directories for preview and mesh discovery.

    ATH often writes into a project-named subdirectory beneath `Output.DestDir`,
    and may additionally create nested ABEC project folders such as
    `ABEC_FreeStanding`. This helper collects those locations in a stable order.
    """
    stem = cfg_path.stem
    seen: set[str] = set()
    ordered: list[Path] = []

    def add(candidate: Path | None) -> None:
        if candidate is None:
            return
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            return
        seen.add(key)
        ordered.append(candidate)

    project_dir = output_dir if output_dir.name.lower() == stem.lower() else output_dir / stem
    add(project_dir)
    add(output_dir)

    def child_priority(path: Path) -> tuple[int, float, str]:
        has_abec = 0 if (path / "Project.abec").exists() or (path / "bem_mesh.geo").exists() else 1
        try:
            mtime = -path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (has_abec, mtime, path.name.lower())

    def is_relevant_child(path: Path) -> bool:
        if path.name.lower() == "results":
            return False
        markers = (
            path.name.lower() == stem.lower(),
            (path / f"{stem}.msh").exists(),
            (path / "mesh.msh").exists(),
            (path / "mesh.geo").exists(),
            (path / "Project.abec").exists(),
            (path / "bem_mesh.geo").exists(),
            (path / "config.txt").exists(),
        )
        return any(markers)

    snapshot = list(ordered)
    for base in snapshot:
        if not base.exists() or not base.is_dir():
            continue
        children = [child for child in base.iterdir() if child.is_dir() and is_relevant_child(child)]
        for child in sorted(children, key=child_priority):
            add(child)

    return ordered


def find_generated_preview_file(output_dir: Path, cfg_path: Path) -> Path | None:
    stem = cfg_path.stem
    search_dirs = iter_output_search_directories(output_dir, cfg_path)

    abec_dirs = [directory for directory in search_dirs if (directory / "Project.abec").exists() or (directory / "bem_mesh.geo").exists()]
    plain_dirs = [directory for directory in search_dirs if directory not in abec_dirs]

    # Prefer meshes that belong to the generated ABEC project because they
    # usually carry compact physical groups suitable for embedded group preview.
    for directory in abec_dirs + plain_dirs:
        for candidate in (directory / f"{stem}.msh", directory / "mesh.msh"):
            if candidate.exists():
                return candidate

    for directory in plain_dirs + abec_dirs:
        preferred = (
            directory / "mesh.geo",
            directory / f"{stem}.geo",
            directory / f"{stem}.stl",
            directory / "bem_mesh.geo",
        )
        for candidate in preferred:
            if candidate.exists():
                return candidate

    for directory in search_dirs:
        if not directory.exists() or not directory.is_dir():
            continue
        for pattern in ("*.msh", "mesh.geo", "*.geo", "*.stl"):
            matches = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
            if matches:
                return matches[0]
    return None


def build_preview_command(mesh_cmd: str, preview_file: Path) -> str | None:
    command = mesh_cmd.strip()
    if not command:
        return None

    target = f'"{preview_file}"'
    if "%f -" in command:
        command = command.replace("%f -", target)
    elif "%f" in command:
        command = command.replace("%f", target)
    else:
        command = f"{command} {target}"

    while command.endswith(" -"):
        command = command[:-2].rstrip()
    return command.strip()


def _physical_groups_for_entity(gmsh_module: object, dimension: int, entity_tag: int) -> list[int]:
    model = gmsh_module.model
    try:
        return [int(tag) for tag in model.getPhysicalGroupsForEntity(dimension, entity_tag)]
    except Exception:
        attached: list[int] = []
        for dim, physical_tag in model.getPhysicalGroups():
            if dim != dimension:
                continue
            entities = model.getEntitiesForPhysicalGroup(dim, physical_tag)
            if entity_tag in entities:
                attached.append(int(physical_tag))
        return attached


def load_embedded_preview_data(preview_file: Path) -> dict[str, object]:
    import gmsh

    gmsh.initialize(interruptible=False)
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        gmsh.open(str(preview_file))
        if preview_file.suffix.lower() == ".geo":
            try:
                gmsh.model.mesh.generate(2)
            except Exception:
                gmsh.model.mesh.generate(1)

        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        if len(node_tags) == 0:
            try:
                gmsh.model.mesh.generate(2)
                node_tags, coords, _ = gmsh.model.mesh.getNodes()
            except Exception:
                pass

        points = {
            int(tag): (
                float(coords[index * 3]),
                float(coords[index * 3 + 1]),
                float(coords[index * 3 + 2]),
            )
            for index, tag in enumerate(node_tags)
        }

        edges: set[tuple[int, int]] = set()
        group_edges: dict[int, set[tuple[int, int]]] = {}
        group_triangles: dict[int, list[tuple[int, int, int]]] = {}
        group_element_counts: Counter[int] = Counter()
        element_count = 0
        mesh_dimension = 0
        saw_physical_groups = False

        for dimension in (2, 1):
            dimension_entities = gmsh.model.getEntities(dimension)
            if not dimension_entities:
                continue
            mesh_dimension = dimension
            for _entity_dim, entity_tag in dimension_entities:
                element_types, element_tags, node_groups = gmsh.model.mesh.getElements(dimension, entity_tag)
                if not element_types:
                    continue

                attached_groups = _physical_groups_for_entity(gmsh, dimension, entity_tag)
                if attached_groups:
                    saw_physical_groups = True
                    target_groups = attached_groups
                else:
                    target_groups = [int(entity_tag)]

                entity_edges: set[tuple[int, int]] = set()
                entity_elements = 0
                for element_type, tags, node_group in zip(element_types, element_tags, node_groups):
                    _, _, _, nodes_per_element, _, _ = gmsh.model.mesh.getElementProperties(element_type)
                    element_count += len(tags)
                    entity_elements += len(tags)
                    flat_nodes = [int(node) for node in node_group]
                    for start in range(0, len(flat_nodes), nodes_per_element):
                        connectivity = flat_nodes[start : start + nodes_per_element]
                        if len(connectivity) < 2:
                            continue
                        if dimension == 2 and len(connectivity) >= 3:
                            a = connectivity[0]
                            b = connectivity[1]
                            c = connectivity[2]
                            if a in points and b in points and c in points:
                                for group_id in target_groups:
                                    group_triangles.setdefault(int(group_id), []).append((a, b, c))
                        loop_count = len(connectivity) if dimension == 2 else len(connectivity) - 1
                        for offset in range(loop_count):
                            a = connectivity[offset]
                            b = connectivity[(offset + 1) % len(connectivity)] if dimension == 2 else connectivity[offset + 1]
                            if a != b and a in points and b in points:
                                edge = (a, b) if a < b else (b, a)
                                edges.add(edge)
                                entity_edges.add(edge)

                for group_id in target_groups:
                    group_edges.setdefault(int(group_id), set()).update(entity_edges)
                    group_element_counts[int(group_id)] += entity_elements
            if edges:
                break

        xs = [point[0] for point in points.values()] or [0.0]
        ys = [point[1] for point in points.values()] or [0.0]
        zs = [point[2] for point in points.values()] or [0.0]
        detected_groups = sorted(int(group_id) for group_id in group_edges)
        return {
            "file_name": preview_file.name,
            "points": points,
            "edges": sorted(edges),
            "group_edges": {int(group_id): sorted(group_edges[group_id]) for group_id in detected_groups},
            "group_triangles": {
                int(group_id): list(group_triangles.get(group_id, []))
                for group_id in detected_groups
            },
            "detected_groups": detected_groups,
            "group_edge_count": {str(group_id): len(group_edges[group_id]) for group_id in detected_groups},
            "group_triangle_count": {str(group_id): len(group_triangles.get(group_id, [])) for group_id in detected_groups},
            "group_element_count": {str(group_id): int(group_element_counts[group_id]) for group_id in detected_groups},
            "group_source": "gmsh physical groups" if saw_physical_groups else "gmsh surface entities",
            "node_count": len(points),
            "edge_count": len(edges),
            "element_count": element_count,
            "mesh_dimension": mesh_dimension,
            "bbox": (
                min(xs),
                max(xs),
                min(ys),
                max(ys),
                min(zs),
                max(zs),
            ),
        }
    finally:
        gmsh.finalize()
