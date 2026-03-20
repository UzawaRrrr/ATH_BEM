from __future__ import annotations

import tempfile
from importlib.util import find_spec
from pathlib import Path

from .domain.config_core import (
    default_horn_state,
    load_global_state,
    load_horn_state,
    render_global_text,
    render_horn_text,
)
from .domain.specs import ATH_EXE, ROOT_DIR
from .infrastructure.bem_bridge import build_bem_solver_command, expand_wsl_user_path, quote_bash_path, windows_path_to_wsl
from .infrastructure.bem_results import describe_bem_status, format_summary_text
from .infrastructure.bem_state import build_job_payload, default_bem_state
from .infrastructure.preview_core import (
    build_preview_command,
    describe_group_source,
    find_generated_preview_file,
    iter_output_search_directories,
    load_embedded_preview_data,
)
from .tools.check_layering import check_layering, format_layering_report
from bem_solver.symmetry import build_image_transforms, parse_symmetry_config


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
        assert find_generated_preview_file(temp_dir, cfg_file) == temp_dir / "demo.msh"

    with tempfile.TemporaryDirectory() as temp_root_name:
        temp_root = Path(temp_root_name)
        cfg_file = temp_root / "demo.cfg"
        cfg_file.write_text("", encoding="utf-8")
        project_dir = temp_root / "demo"
        abec_dir = project_dir / "ABEC_FreeStanding"
        abec_dir.mkdir(parents=True)
        (project_dir / "mesh.geo").write_text("Point(1) = {0, 0, 0, 1};", encoding="utf-8")
        (project_dir / "demo.msh").write_text("$MeshFormat", encoding="utf-8")
        (abec_dir / "Project.abec").write_text("[MeshFiles]\nC0=demo.msh,M1\n", encoding="utf-8")
        (abec_dir / "demo.msh").write_text("$MeshFormat", encoding="utf-8")
        search_dirs = iter_output_search_directories(temp_root, cfg_file)
        assert project_dir in search_dirs
        assert abec_dir in search_dirs
        assert find_generated_preview_file(temp_root, cfg_file) == abec_dir / "demo.msh"

    if find_spec("gmsh") is not None:
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

    assert windows_path_to_wsl(Path(r"E:\tmp\demo\job.json")) == "/mnt/e/tmp/demo/job.json"
    assert expand_wsl_user_path("~/venvs/bempp-wsl") == "${HOME}/venvs/bempp-wsl"
    assert quote_bash_path("${HOME}/venvs/bempp-wsl/bin/python") == '"${HOME}/venvs/bempp-wsl/bin/python"'
    bem_command = build_bem_solver_command("/mnt/e/tmp/demo/job.json")
    assert '"${HOME}/venvs/bempp-wsl/bin/python"' in bem_command
    assert "source " not in bem_command
    assert "cp -r" not in bem_command
    assert "/ath-2025-06/bem_solver/solver_cli.py" in bem_command
    assert ATH_EXE.exists()
    assert (ROOT_DIR / "bem_solver").exists()

    with tempfile.TemporaryDirectory() as temp_mesh_dir_name:
        temp_mesh_dir = Path(temp_mesh_dir_name)
        mesh_file = temp_mesh_dir / "demo.msh"
        mesh_file.write_text("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n", encoding="utf-8")
        bem_state = default_bem_state()
        bem_state["BEM.SourceGroups"] = "2"
        job_payload = build_job_payload(bem_state, mesh_file, "/mnt/e/tmp/demo.msh")
        assert job_payload["solver_mode"] == "exterior_velocity_bc"
        assert job_payload["source_groups"] == [2]
        assert job_payload["source_gain"] == [1.0]
        assert job_payload["source_direction"] == [[0.0, 0.0, 1.0]]
        assert job_payload["angle_range_mode"] == "full_circle"
        assert dict(job_payload["symmetry"])["enabled"] is False

        bem_state["BEM.SymmetryMode"] = "quarter_xy_even_even"
        bem_state["BEM.SymmetryXValue"] = "0.0"
        bem_state["BEM.SymmetryYValue"] = "0.0"
        bem_state["BEM.AngleRangeMode"] = "half_circle"
        job_payload = build_job_payload(bem_state, mesh_file, "/mnt/e/tmp/demo.msh")
        symmetry_payload = dict(job_payload["symmetry"])
        assert job_payload["angle_range_mode"] == "half_circle"
        assert symmetry_payload["enabled"] is True
        assert len(list(symmetry_payload["planes"])) == 2

    symmetry = parse_symmetry_config(
        {
            "enabled": True,
            "planes": [
                {"axis": "x", "value": 0.0, "parity": "even"},
                {"axis": "y", "value": 0.0, "parity": "odd"},
            ],
        }
    )
    images = build_image_transforms(symmetry)
    assert len(images) == 3
    assert sorted(image.sign for image in images) == [-1, -1, 1]

    formatted_summary = format_summary_text(
        {
            "summary": {
                "status": "done",
                "mesh_file": "E:/tmp/demo.msh",
                "vertices": 42,
                "elements": 21,
                "source_groups": [2],
                "wall_groups": [1, 3],
                "freq_count": 8,
                "runtime_sec": 1.23,
                "symmetry_enabled": True,
                "symmetry_mode": "half_x_even",
                "warnings": ["demo warning"],
                "notes": ["demo note"],
            },
            "mesh_info": {"detected_groups": [1, 2, 3]},
        }
    )
    assert "狀態：完成" in formatted_summary
    assert "demo warning" in formatted_summary
    assert "demo note" in formatted_summary
    assert describe_group_source("gmsh physical groups") == "Gmsh 物理群組"
    assert describe_bem_status("done") == "完成"

    layer_result = check_layering()
    assert layer_result.ok, format_layering_report(layer_result)
    return 0
