from __future__ import annotations

import tempfile
from importlib.util import find_spec
from pathlib import Path

from .domain.config_core import (
    build_guided_field_states,
    default_horn_state,
    load_global_state,
    load_horn_state,
    normalize_branch_locked_horn_state,
    render_global_text,
    render_horn_text,
    sanitize_ath_state,
    sanitize_state_by_rules,
)
from .domain.design_recipe import DesignRecipe
from .domain.specs import ATH_EXE, QUICK_FIELD_SECTIONS, ROOT_DIR, SIMPLE_FIELD_SPECS
from .infrastructure.bem_bridge import build_bem_solver_command, expand_wsl_user_path, quote_bash_path, windows_path_to_wsl
from .infrastructure.group_mapper import suggest_group_map
from .infrastructure.project_workspace import create_workspace, latest_workspace_for_case, write_manifest
from .infrastructure.bem_results import describe_bem_status, format_summary_text
from .infrastructure.bem_state import (
    apply_group_map_to_bem_state,
    build_bem_guided_field_states,
    build_bem_runtime_settings,
    build_job_payload,
    default_bem_state,
    resolve_group_map_payload,
    sanitize_bem_state,
)
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
    for _title, _description, fields in QUICK_FIELD_SECTIONS:
        for spec in fields:
            assert spec.key in SIMPLE_FIELD_SPECS

    branch_state = default_horn_state()
    branch_state["Throat.Profile"] = "1"
    branch_state["GCurve.Type"] = "2"
    branch_state["GCurve.Dist"] = "0.618"
    branch_state["GCurve.Width"] = "150"
    branch_state["GCurve.AspectRatio"] = "0.825"
    branch_state["GCurve.SE.n"] = "0"
    branch_state["GCurve.SF"] = "1,1,4,3.5,5,5"
    branch_state["Morph.TargetShape"] = "0"
    branch_state["Morph.TargetWidth"] = "200"
    branch_state["Morph.TargetHeight"] = "120"
    normalized_branch = normalize_branch_locked_horn_state(branch_state)
    assert normalized_branch["GCurve.SE.n"] == ""
    assert normalized_branch["GCurve.SF"] == "1,1,4,3.5,5,5"
    assert normalized_branch["Morph.TargetWidth"] == "0"
    assert normalized_branch["Morph.TargetHeight"] == "0"
    branch_rendered = render_horn_text(normalized_branch)
    assert "GCurve.SE.n" not in branch_rendered

    arc_state = default_horn_state()
    arc_state["Throat.Profile"] = "3"
    arc_state["GCurve.Type"] = "2"
    arc_state["GCurve.SF"] = "1,2,3,4,5,6"
    arc_state["Term.s"] = "0.51"
    arc_state["CircArc.Radius"] = "78"
    arc_state["CircArc.TermAngle"] = "23"
    sanitized_arc = sanitize_state_by_rules(arc_state)
    assert sanitized_arc["GCurve.Type"] == ""
    assert sanitized_arc["GCurve.SF"] == ""
    assert sanitized_arc["Term.s"] == ""
    assert sanitized_arc["CircArc.Radius"] == "78"
    assert sanitized_arc["CircArc.TermAngle"] == "23"

    rollback_state = default_horn_state()
    rollback_state["ABEC.SimType"] = "1"
    rollback_state["Rollback"] = True
    rollback_state["Rollback.StartAt"] = "0.3"
    rollback_state["Rollback.Angle"] = "55"
    sanitized_rollback = sanitize_state_by_rules(rollback_state)
    assert sanitized_rollback["Rollback"] is False
    assert sanitized_rollback["Rollback.StartAt"] == ""
    assert sanitized_rollback["Rollback.Angle"] == ""

    guided_state = build_guided_field_states(
        {
            "Throat.Profile": "1",
            "GCurve.Type": "2",
            "Morph.TargetShape": "0",
            "ABEC.SimType": "1",
            "Rollback": True,
        }
    )
    assert guided_state["GCurve.Type"]["relevant"] is True
    assert guided_state["GCurve.SF"]["relevant"] is True
    assert guided_state["GCurve.SE.n"]["relevant"] is False
    assert guided_state["Coverage.Angle"]["relevant"] is False
    assert guided_state["Morph.TargetWidth"]["relevant"] is False
    assert guided_state["Rollback"]["relevant"] is False

    effective_ath_state = sanitize_ath_state(
        {
            "ABEC.SimType": "2",
            "Throat.Profile": "1",
            "GCurve.Type": "1",
            "Morph.TargetShape": "1",
            "Rollback": False,
        }
    )
    bem_guided_state = build_bem_guided_field_states(
        {
            "BEM.Enabled": True,
            "BEM.Backend": "conda",
            "BEM.MeshSourceMode": "latest_ath_output",
            "BEM.GroupMode": "auto",
            "BEM.ObservationMode": "polar_map",
        },
        effective_ath_state,
    )
    assert bem_guided_state["BEM.Enabled"]["relevant"] is True
    assert bem_guided_state["BEM.MeshFile"]["relevant"] is False
    assert bem_guided_state["BEM.AutoGroupStrategy"]["relevant"] is True
    assert bem_guided_state["BEM.SourceGroups"]["relevant"] is False
    assert bem_guided_state["BEM.CondaExe"]["relevant"] is True
    assert bem_guided_state["BEM.WslVenv"]["relevant"] is False
    assert bem_guided_state["BEM.ExportPng"]["relevant"] is True
    assert bem_guided_state["BEM.ExportBoundaryPressure"]["relevant"] is False

    disabled_bem_state = sanitize_bem_state(
        {
            "BEM.Enabled": False,
            "BEM.Backend": "conda",
            "BEM.MeshSourceMode": "manual_mesh_file",
            "BEM.MeshFile": "E:/tmp/manual.msh",
            "BEM.GroupMode": "manual",
            "BEM.SourceGroups": "2",
            "BEM.WallGroups": "1,3",
        },
        effective_ath_state,
    )
    assert disabled_bem_state["BEM.Enabled"] is False
    assert disabled_bem_state["BEM.Backend"] == "wsl"
    assert disabled_bem_state["BEM.MeshFile"] == ""
    assert disabled_bem_state["BEM.SourceGroups"] == ""

    latest_mesh_bem_state = sanitize_bem_state(
        {
            "BEM.Enabled": True,
            "BEM.MeshSourceMode": "latest_ath_output",
            "BEM.MeshFile": "E:/tmp/should_be_cleared.msh",
            "BEM.GroupMode": "auto",
            "BEM.AutoGroupStrategy": "fixed_current",
        },
        {"ABEC.SimType": "1"},
    )
    assert latest_mesh_bem_state["BEM.MeshFile"] == ""
    assert latest_mesh_bem_state["BEM.AutoGroupStrategy"] == "name_heuristic"

    runtime_settings = build_bem_runtime_settings(
        {
            "BEM.Enabled": True,
            "BEM.Backend": "local_python",
            "BEM.LocalPythonExe": "E:/Python/python.exe",
            "BEM.MeshSourceMode": "latest_ath_output",
            "BEM.GroupMode": "manual",
        },
        effective_ath_state,
    )
    assert runtime_settings["enabled"] is True
    assert runtime_settings["backend"] == "local_python"
    assert runtime_settings["requires_ath_mesh_output"] is True
    assert dict(runtime_settings["launch_options"])["local_python_exe"] == "E:/Python/python.exe"

    auto_group_payload = resolve_group_map_payload(
        {
            "BEM.Enabled": True,
            "BEM.GroupMode": "auto",
            "BEM.AutoGroupStrategy": "fixed_current",
        },
        {
            "group_source": "gmsh physical groups",
            "detected_groups": [1, 2, 3, 4],
            "element_count_per_group": {"1": 10, "2": 20, "3": 30, "4": 5},
        },
        {"ABEC.SimType": "2"},
    )
    assert auto_group_payload["source_groups"] == [2]
    assert auto_group_payload["wall_groups"] == [1, 3]
    mapped_bem_state = apply_group_map_to_bem_state(default_bem_state(), auto_group_payload)
    assert mapped_bem_state["BEM.SourceGroups"] == "2"
    assert mapped_bem_state["BEM.WallGroups"] == "1,3"

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
        assert job_payload["frequency_spacing"] == "log"
        assert job_payload["velocity_frequency_weighting"] == "none"
        assert dict(job_payload["symmetry"])["enabled"] is False

        bem_state["BEM.SymmetryMode"] = "quarter_xy_even_even"
        bem_state["BEM.SymmetryXValue"] = "0.0"
        bem_state["BEM.SymmetryYValue"] = "0.0"
        bem_state["BEM.AngleRangeMode"] = "half_circle"
        bem_state["BEM.FrequencySpacing"] = "linear"
        bem_state["BEM.VelocityFrequencyWeighting"] = "inverse_jw"
        job_payload = build_job_payload(bem_state, mesh_file, "/mnt/e/tmp/demo.msh")
        symmetry_payload = dict(job_payload["symmetry"])
        assert job_payload["angle_range_mode"] == "half_circle"
        assert job_payload["frequency_spacing"] == "linear"
        assert job_payload["velocity_frequency_weighting"] == "inverse_jw"
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

    recipe = DesignRecipe(case_name="Autima_basic", symmetry_enabled=True, symmetry_planes=("x",))
    compiled_ath = recipe.to_ath_state()
    compiled_bem = recipe.to_bem_state()
    assert compiled_ath["Output.MSH"] is True
    assert compiled_bem["BEM.SymmetryMode"] == "half_x_even"

    suggestion = suggest_group_map(
        {
            "group_source": "gmsh physical groups",
            "detected_groups": [1001, 2, 3],
            "element_count_per_group": {"1001": 40, "2": 400, "3": 120},
            "group_name_map": {"1001": "DrvGroup", "2": "HornWall", "3": "InterfaceMain"},
        }
    )
    assert suggestion.source_groups == [1001]
    assert 2 in suggestion.wall_groups
    assert 3 in suggestion.interface_groups

    with tempfile.TemporaryDirectory() as temp_project_name:
        projects_root = Path(temp_project_name)
        workspace = create_workspace("Autima_basic", projects_root=projects_root)
        assert workspace.input_dir.exists()
        assert workspace.bempp_dir.exists()
        write_manifest(workspace, {"status": "done"})
        latest = latest_workspace_for_case("Autima_basic", projects_root=projects_root)
        assert latest is not None
        assert latest.run_root == workspace.run_root

    layer_result = check_layering()
    assert layer_result.ok, format_layering_report(layer_result)
    return 0
