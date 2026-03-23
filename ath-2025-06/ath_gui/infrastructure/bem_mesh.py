"""ATH mesh discovery and inspection helpers for the BEM GUI."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .preview_core import compute_output_directory, describe_group_source, iter_output_search_directories


def find_generated_mesh_file(output_dir: Path, cfg_path: Path) -> Path | None:
    stem = cfg_path.stem
    search_dirs = iter_output_search_directories(output_dir, cfg_path)
    abec_dirs = [directory for directory in search_dirs if (directory / "Project.abec").exists() or (directory / "bem_mesh.geo").exists()]
    plain_dirs = [directory for directory in search_dirs if directory not in abec_dirs]

    # Prefer ABEC project meshes first when available, then the main horn mesh.
    for directory in abec_dirs + plain_dirs:
        preferred = (
            directory / f"{stem}.msh",
            directory / "mesh.msh",
        )
        for candidate in preferred:
            if candidate.exists():
                return candidate

    for directory in abec_dirs + plain_dirs:
        if not directory.exists() or not directory.is_dir():
            continue
        matches = sorted(directory.glob("*.msh"), key=lambda path: path.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]
    return None


def guess_latest_mesh_file(global_state: dict[str, object], horn_state: dict[str, object], cfg_path: str) -> Path | None:
    if not cfg_path.strip():
        return None
    cfg_file = Path(cfg_path)
    return find_generated_mesh_file(
        compute_output_directory(global_state, horn_state, cfg_file),
        cfg_file,
    )


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


def inspect_mesh_file(mesh_file: Path, *, mesh_scale_to_meter: float = 1.0) -> dict[str, object]:
    import gmsh

    # Run-All executes mesh inspection in a worker thread; disable Gmsh's
    # interrupt signal hook to avoid Python main-thread signal restrictions.
    gmsh.initialize(interruptible=False)
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        gmsh.open(str(mesh_file))
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        if len(node_tags) == 0:
            raise ValueError("網格內沒有任何節點。")

        points = [
            (
                float(coords[index * 3]) * mesh_scale_to_meter,
                float(coords[index * 3 + 1]) * mesh_scale_to_meter,
                float(coords[index * 3 + 2]) * mesh_scale_to_meter,
            )
            for index in range(len(node_tags))
        ]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        zs = [point[2] for point in points]

        entity_counts: list[tuple[int, int]] = []
        physical_counts: list[tuple[int, int]] = []
        total_elements = 0

        for dimension, entity_tag in gmsh.model.getEntities(2):
            element_types, element_tags, _node_groups = gmsh.model.mesh.getElements(dimension, entity_tag)
            surface_count = 0
            for element_type, tags in zip(element_types, element_tags):
                _, element_dimension, _element_order, _nodes_per_element, _, _ = gmsh.model.mesh.getElementProperties(element_type)
                if element_dimension == 2:
                    surface_count += len(tags)
            if surface_count == 0:
                continue
            total_elements += surface_count
            entity_counts.append((int(entity_tag), int(surface_count)))
            for physical_tag in _physical_groups_for_entity(gmsh, dimension, entity_tag):
                if physical_tag > 0:
                    physical_counts.append((int(physical_tag), int(surface_count)))

        if total_elements == 0:
            raise ValueError("網格內沒有任何表面三角形元素。")

        warnings: list[str] = []
        group_name_map: dict[str, str] = {}
        if physical_counts:
            group_source = "gmsh physical groups"
            counts = Counter()
            for group_id, amount in physical_counts:
                counts[group_id] += amount
            for group_id in counts:
                try:
                    group_name_map[str(group_id)] = str(gmsh.model.getPhysicalName(2, int(group_id)) or "")
                except Exception:
                    group_name_map[str(group_id)] = ""
        else:
            group_source = "gmsh surface entities"
            counts = Counter()
            for group_id, amount in entity_counts:
                counts[group_id] += amount
            for group_id in counts:
                try:
                    group_name_map[str(group_id)] = str(gmsh.model.getEntityName(2, int(group_id)) or "")
                except Exception:
                    group_name_map[str(group_id)] = ""
            warnings.append("找不到 Gmsh 物理群組；目前改用曲面實體標籤作為群組 ID。")

        return {
            "mesh_file": str(mesh_file),
            "mesh_scale_to_meter": mesh_scale_to_meter,
            "mesh_dimension": 2,
            "node_count": len(points),
            "element_count": total_elements,
            "group_source": group_source,
            "detected_groups": sorted(int(group_id) for group_id in counts),
            "element_count_per_group": {str(group_id): int(counts[group_id]) for group_id in sorted(counts)},
            "group_name_map": group_name_map,
            "bbox": (
                min(xs),
                max(xs),
                min(ys),
                max(ys),
                min(zs),
                max(zs),
            ),
            "warnings": warnings,
        }
    finally:
        gmsh.finalize()


def _format_sequence(values: list[int], *, limit: int = 18) -> str:
    if not values:
        return "（無）"
    if len(values) <= limit:
        return ", ".join(str(value) for value in values)
    visible = ", ".join(str(value) for value in values[:limit])
    return f"{visible}, ... (+{len(values) - limit} more)"


def format_mesh_info_text(info: dict[str, object]) -> str:
    bbox = info.get("bbox", (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    groups = [int(value) for value in info.get("detected_groups", [])]
    counts = info.get("element_count_per_group", {})
    name_map = {str(key): str(value) for key, value in dict(info.get("group_name_map", {})).items()}
    node_count = info.get("node_count", info.get("vertices", "?"))
    element_count = info.get("element_count", info.get("elements", "?"))
    count_pairs = ", ".join(
        f"{group_id}:{counts[str(group_id)]}"
        for group_id in groups[:18]
        if str(group_id) in counts
    )
    if len(groups) > 18:
        count_pairs = f"{count_pairs}, ... (+{len(groups) - 18} more)"

    lines = [
        f"網格檔：{info.get('mesh_file', '')}",
        f"群組來源：{describe_group_source(str(info.get('group_source', 'unknown')))}",
        f"網格維度：{info.get('mesh_dimension', '?')}",
        f"節點數：{node_count} | 表面元素數：{element_count}",
        "包圍盒 [m]："
        f"x[{bbox[0]:.4f}, {bbox[1]:.4f}] "
        f"y[{bbox[2]:.4f}, {bbox[3]:.4f}] "
        f"z[{bbox[4]:.4f}, {bbox[5]:.4f}]",
        f"偵測到的群組：{_format_sequence(groups)}",
        f"各群組元素數：{count_pairs or '（無）'}",
    ]
    named_preview = ", ".join(
        f"{group_id}:{name_map.get(str(group_id), '') or '-'}"
        for group_id in groups[:18]
    )
    if named_preview:
        lines.append(f"群組名稱：{named_preview}")

    total_area = info.get("total_area_m2")
    if isinstance(total_area, (int, float)):
        lines.append(f"總表面積 [m^2]：{float(total_area):.6e}")

    area_per_group = info.get("area_per_group_m2", {})
    if isinstance(area_per_group, dict) and area_per_group:
        try:
            area_pairs = ", ".join(
                f"{group_id}:{float(area_per_group[group_id]):.3e}"
                for group_id in sorted(area_per_group, key=lambda value: int(str(value)))
            )
        except Exception:
            area_pairs = ", ".join(f"{group_id}:{area}" for group_id, area in area_per_group.items())
        lines.append(f"各群組面積 [m^2]：{area_pairs}")

    boundary_edge_count = info.get("boundary_edge_count")
    nonmanifold_edge_count = info.get("nonmanifold_edge_count")
    connected_component_count = info.get("connected_component_count")
    if isinstance(boundary_edge_count, (int, float)) and isinstance(nonmanifold_edge_count, (int, float)):
        component_text = "?"
        if isinstance(connected_component_count, (int, float)):
            component_text = str(int(connected_component_count))
        lines.append(
            "邊界拓樸："
            f"開邊 {int(boundary_edge_count)} | "
            f"非流形邊 {int(nonmanifold_edge_count)} | "
            f"連通分量 {component_text}"
        )

    boundary_role = info.get("boundary_role_diagnostics", {})
    if isinstance(boundary_role, dict) and boundary_role:
        lines.append(
            "source/wall 覆蓋："
            f"source={float(boundary_role.get('source_area_ratio', 0.0)):.1%} | "
            f"wall={float(boundary_role.get('wall_area_ratio', 0.0)):.1%}"
        )
        lines.append(
            f"source 群組：{_format_sequence(list(boundary_role.get('source_groups_present', [])))} | "
            f"wall 群組：{_format_sequence(list(boundary_role.get('wall_groups_present', [])))}"
        )

    warnings = [str(item) for item in info.get("warnings", []) if str(item).strip()]
    if warnings:
        lines.extend(["警告："] + [f"- {warning}" for warning in warnings])
    return "\n".join(lines)
