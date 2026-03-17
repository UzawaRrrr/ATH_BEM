from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .configuration import ProjectConfig
from .external_tools import resolve_executable, run_command


@dataclass
class MeshResult:
    mesh_path: Path
    mode_used: str
    details: dict[str, Any]


def _write_mock_mesh(mesh_path: Path, params: dict[str, float]) -> None:
    mesh_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "mock_mesh",
        "params": params,
    }
    mesh_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_geo_file(geo_path: Path, params: dict[str, float]) -> None:
    length = max(params.get("length", 0.2), 0.05)
    throat = max(params.get("throat_radius", 0.02), 0.005)
    mouth = max(params.get("mouth_radius", 0.1), throat + 0.001)

    geo_content = f"""
lc = {max(length / 30.0, 0.003):.6f};

Point(1) = {{0, 0, 0, lc}};
Point(2) = {{{length:.6f}, 0, 0, lc}};
Point(3) = {{0, {throat:.6f}, 0, lc}};
Point(4) = {{{length:.6f}, {mouth:.6f}, 0, lc}};

Line(1) = {{1, 2}};
Line(2) = {{2, 4}};
Line(3) = {{4, 3}};
Line(4) = {{3, 1}};
Curve Loop(1) = {{1, 2, 3, 4}};
Plane Surface(1) = {{1}};
Extrude {{0, 0, {throat:.6f}}} {{
  Surface{{1}};
}}
"""
    geo_path.parent.mkdir(parents=True, exist_ok=True)
    geo_path.write_text(geo_content.strip() + "\n", encoding="utf-8")


def build_mesh(
    params: dict[str, float],
    config: ProjectConfig,
    mode: str,
    case_name: str,
    logger,
) -> MeshResult:
    mesh_path = config.paths.mesh_output_directory / f"{case_name}.msh"
    temp_geo = config.paths.temp_directory / f"{case_name}.geo"

    if mode == "mock":
        _write_mock_mesh(mesh_path, params)
        logger.info("Mock mesh generated at %s", mesh_path)
        return MeshResult(mesh_path=mesh_path, mode_used="mock", details={"backend": "mock"})

    ath_executable = resolve_executable(config.paths.ath_executable, fallback_names=["ath"])
    if not ath_executable:
        raise RuntimeError("Real mode requires ATH executable. Set paths.ath_executable in config/local_paths.yaml.")

    gmsh_executable = resolve_executable(config.paths.gmsh_executable, fallback_names=["gmsh"])
    if not gmsh_executable:
        raise RuntimeError("Gmsh executable not found. Set paths.gmsh_executable in config/local_paths.yaml.")

    ath_parent = Path(ath_executable).resolve().parent if Path(ath_executable).exists() else None
    if ath_parent:
        ath_cfg = ath_parent / "ath.cfg"
        if not ath_cfg.exists():
            raise RuntimeError(f"ATH executable found but missing ath.cfg near executable: {ath_cfg}")

    ath_result = run_command(
        [ath_executable],
        timeout_seconds=config.runtime.timeout_seconds,
        cwd=ath_parent,
    )
    logger.info("ATH check command rc=%s", ath_result.returncode)
    if ath_result.stdout:
        logger.info("ATH stdout: %s", ath_result.stdout.strip())
    if ath_result.stderr:
        logger.info("ATH stderr: %s", ath_result.stderr.strip())
    if ath_result.returncode != 0:
        raise RuntimeError("ATH check command failed in real mode.")
    if "Ath" not in (ath_result.stdout or "") and "Usage" not in (ath_result.stdout or ""):
        logger.warning("ATH output did not match expected banner/usage text.")

    _write_geo_file(temp_geo, params)
    gmsh_cmd = [gmsh_executable, str(temp_geo), "-3", "-o", str(mesh_path)]
    gmsh_result = run_command(gmsh_cmd, timeout_seconds=config.runtime.timeout_seconds)
    logger.info("Gmsh command rc=%s", gmsh_result.returncode)
    if gmsh_result.stdout:
        logger.info("Gmsh stdout: %s", gmsh_result.stdout.strip())
    if gmsh_result.stderr:
        logger.info("Gmsh stderr: %s", gmsh_result.stderr.strip())

    if gmsh_result.returncode != 0:
        raise RuntimeError("Gmsh mesh generation failed in real mode.")
    if not mesh_path.exists():
        raise RuntimeError("Gmsh command finished but mesh file was not produced.")

    return MeshResult(
        mesh_path=mesh_path,
        mode_used="real",
        details={
            "backend": "ath+gmsh",
            "ath_executable": ath_executable,
            "ath_cwd": str(ath_parent) if ath_parent else "",
            "gmsh_executable": gmsh_executable,
        },
    )
