from __future__ import annotations

from pathlib import Path


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


def find_generated_preview_file(output_dir: Path, cfg_path: Path) -> Path | None:
    stem = cfg_path.stem
    preferred = (
        output_dir / "mesh.geo",
        output_dir / f"{stem}.geo",
        output_dir / f"{stem}.msh",
        output_dir / f"{stem}.stl",
    )
    for candidate in preferred:
        if candidate.exists():
            return candidate

    for pattern in ("mesh.geo", "*.geo", "*.msh", "*.stl"):
        matches = sorted(output_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
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


def load_embedded_preview_data(preview_file: Path) -> dict[str, object]:
    import gmsh

    gmsh.initialize()
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
        element_count = 0
        mesh_dimension = 0

        for dimension in (2, 1):
            element_types, element_tags, node_groups = gmsh.model.mesh.getElements(dimension)
            if not element_types:
                continue
            mesh_dimension = dimension
            for element_type, tags, node_group in zip(element_types, element_tags, node_groups):
                _, _, _, nodes_per_element, _, _ = gmsh.model.mesh.getElementProperties(element_type)
                element_count += len(tags)
                flat_nodes = [int(node) for node in node_group]
                for start in range(0, len(flat_nodes), nodes_per_element):
                    connectivity = flat_nodes[start : start + nodes_per_element]
                    if len(connectivity) < 2:
                        continue
                    loop_count = len(connectivity) if dimension == 2 else len(connectivity) - 1
                    for offset in range(loop_count):
                        a = connectivity[offset]
                        b = connectivity[(offset + 1) % len(connectivity)] if dimension == 2 else connectivity[offset + 1]
                        if a != b and a in points and b in points:
                            edges.add((a, b) if a < b else (b, a))
            if edges:
                break

        xs = [point[0] for point in points.values()] or [0.0]
        ys = [point[1] for point in points.values()] or [0.0]
        zs = [point[2] for point in points.values()] or [0.0]
        return {
            "file_name": preview_file.name,
            "points": points,
            "edges": sorted(edges),
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
