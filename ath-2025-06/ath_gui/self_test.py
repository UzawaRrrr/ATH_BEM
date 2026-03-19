from __future__ import annotations

import tempfile
from pathlib import Path

from .config_core import (
    default_horn_state,
    load_global_state,
    load_horn_state,
    render_global_text,
    render_horn_text,
)
from .preview_core import build_preview_command, find_generated_preview_file, load_embedded_preview_data


def run_self_test() -> int:
    sample = """
Length = 94
Throat.Diameter = 25.4
Coverage.Angle = 45
Mesh.AngularSegments = 120
Output.STL = 1
Output.ABECProject = 1
ABEC.Polars:SPL = {
  MapAngleRange = 0,90,19
  NormAngle = 20
  Offset = 95
}
Mesh.Enclosure = {
  Spacing = 30,30,30,200
  Depth = 200
}
Source.Contours = {
point p1 4.68 0 2
line p1 WG0 0
}
CustomThing = 42
""".strip()

    state = load_horn_state(sample)
    assert state["Length"] == "94"
    assert state["Throat.Diameter"] == "25.4"
    assert state["POLAR.Tag"] == "SPL"
    assert state["POLAR.Offset"] == "95"
    assert state["ENCLOSURE.Depth"] == "200"
    assert "CustomThing = 42" in str(state["ADVANCED.Raw"])

    rendered = render_horn_text(state)
    assert "ABEC.Polars:SPL = {" in rendered
    assert "Mesh.Enclosure = {" in rendered
    assert "Source.Contours = {" in rendered
    assert "CustomThing = 42" in rendered

    default_rendered = render_horn_text(default_horn_state())
    assert "Output.STL = 1" in default_rendered
    assert "Output.MSH = 0" in default_rendered
    assert "Output.ABECProject = 0" in default_rendered

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        cfg_file = temp_dir / "demo.cfg"
        cfg_file.write_text("", encoding="utf-8")
        (temp_dir / "demo.stl").write_text("solid demo", encoding="utf-8")
        assert find_generated_preview_file(temp_dir, cfg_file) == temp_dir / "demo.stl"
        (temp_dir / "demo.msh").write_text("$MeshFormat", encoding="utf-8")
        assert find_generated_preview_file(temp_dir, cfg_file) == temp_dir / "demo.msh"
        (temp_dir / "mesh.geo").write_text("Point(1) = {0, 0, 0, 1};", encoding="utf-8")
        assert find_generated_preview_file(temp_dir, cfg_file) == temp_dir / "mesh.geo"

    with tempfile.TemporaryDirectory() as temp_geo_dir_name:
        temp_geo_dir = Path(temp_geo_dir_name)
        geo_file = temp_geo_dir / "mesh.geo"
        geo_file.write_text(
            "\n".join(
                (
                    "Point(1) = {0, 0, 0, 1};",
                    "Point(2) = {10, 0, 0, 1};",
                    "Point(3) = {10, 0, 10, 1};",
                    "Point(4) = {0, 0, 10, 1};",
                    "Line(1) = {1, 2};",
                    "Line(2) = {2, 3};",
                    "Line(3) = {3, 4};",
                    "Line(4) = {4, 1};",
                    "Curve Loop(1) = {1, 2, 3, 4};",
                    "Plane Surface(1) = {1};",
                )
            ),
            encoding="utf-8",
        )
        preview_data = load_embedded_preview_data(geo_file)
        assert preview_data["node_count"] > 0
        assert preview_data["edge_count"] > 0

    preview_command = build_preview_command(
        r"E:\pythonGATH\.venv\Scripts\python.exe E:\pythonGATH\.venv\Scripts\gmsh %f -",
        Path(r"E:\tmp\demo.msh"),
    )
    assert preview_command == r'E:\pythonGATH\.venv\Scripts\python.exe E:\pythonGATH\.venv\Scripts\gmsh "E:\tmp\demo.msh"'

    global_state = load_global_state(
        'OutputRootDir = "D:/Horns"\nMeshCmd = "E:/pythonGATH/.venv/Scripts/python.exe gmsh"\n'
    )
    assert global_state["OutputRootDir"] == "D:/Horns"
    assert "OutputRootDir" in render_global_text(global_state)
    return 0
