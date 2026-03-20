"""CLI entry point for the ATH-specific Bempp exterior solver."""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from export_results import write_mesh_info, write_polar_csv, write_solution_npz, write_summary
from job_model import BemJob
from mesh_adapter import assess_boundary_role_coverage, prepare_boundary_mesh, resolve_wall_groups
from postprocess import export_polar_png
from solver_core import solve_exterior_velocity_bc


def _build_summary(
    *,
    status: str,
    job: BemJob,
    vertices: int,
    elements: int,
    runtime_sec: float,
    warnings: list[str],
    notes: list[str],
    boundary_role_diagnostics: dict[str, object] | None = None,
) -> dict[str, object]:
    summary = {
        "status": status,
        "mesh_file": job.mesh_file,
        "vertices": vertices,
        "elements": elements,
        "source_groups": job.source_groups,
        "wall_groups": job.wall_groups,
        "plane": job.plane,
        "angle_range_mode": job.angle_range_mode,
        "theta_count": job.theta_count,
        "freq_count": job.num_freq,
        "runtime_sec": round(runtime_sec, 3),
        "symmetry_enabled": job.symmetry.enabled,
        "symmetry_mode": job.symmetry.mode_label,
        "warnings": warnings,
        "notes": notes,
    }
    if boundary_role_diagnostics:
        summary["boundary_role_diagnostics"] = boundary_role_diagnostics
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ATH Bempp exterior Helmholtz solver")
    parser.add_argument("job_json", help="Path to job.json")
    args = parser.parse_args(argv)

    started_at = time.time()
    job_path = Path(args.job_json).expanduser().resolve()
    job_dir = job_path.parent
    job_dir.mkdir(parents=True, exist_ok=True)

    print(f"[bem_solver] Loading job from {job_path}")

    job: BemJob | None = None
    prepared_mesh = None
    mesh_warnings: list[str] = []
    solver_notes: list[str] = []
    boundary_role_diagnostics: dict[str, object] | None = None

    try:
        job = BemJob.from_json_file(job_path)
        prepared_mesh = prepare_boundary_mesh(job)

        resolved_walls, role_warnings = resolve_wall_groups(job, prepared_mesh.mesh_info.active_groups)
        job.wall_groups = resolved_walls
        boundary_role_diagnostics, boundary_warnings = assess_boundary_role_coverage(job, prepared_mesh)
        prepared_mesh.mesh_info.boundary_role_diagnostics = boundary_role_diagnostics
        mesh_warnings = list(prepared_mesh.mesh_info.warnings) + role_warnings + boundary_warnings
        prepared_mesh.mesh_info.warnings = mesh_warnings
        write_mesh_info(job_dir, prepared_mesh.mesh_info.to_dict())

        print(
            "[bem_solver] Mesh ready: "
            f"{prepared_mesh.mesh_info.vertices} vertices, "
            f"{prepared_mesh.mesh_info.elements} triangles, "
            f"{len(prepared_mesh.mesh_info.active_groups)} active groups."
        )
        print(f"[bem_solver] Source groups: {job.source_groups}")
        print(f"[bem_solver] Wall groups: {job.wall_groups}")
        if boundary_role_diagnostics:
            print(
                "[bem_solver] Boundary coverage: "
                f"source_area={float(boundary_role_diagnostics.get('source_area_m2', 0.0)):.6e} m^2 "
                f"({float(boundary_role_diagnostics.get('source_area_ratio', 0.0)):.1%}), "
                f"wall_area={float(boundary_role_diagnostics.get('wall_area_m2', 0.0)):.6e} m^2 "
                f"({float(boundary_role_diagnostics.get('wall_area_ratio', 0.0)):.1%})."
            )

        result = solve_exterior_velocity_bc(job, prepared_mesh)
        solver_notes = list(result.notes)

        write_polar_csv(job_dir, result.frequencies_hz, result.angles_deg, result.spl_db)
        write_solution_npz(job_dir, result.frequencies_hz, result.angles_deg, result.pressure_complex, result.spl_db)

        if job.export_png:
            try:
                export_polar_png(job_dir, result.frequencies_hz, result.angles_deg, result.spl_db)
            except Exception as exc:
                mesh_warnings.append(f"PNG export failed: {exc}")

        summary = _build_summary(
            status="done",
            job=job,
            vertices=prepared_mesh.mesh_info.vertices,
            elements=prepared_mesh.mesh_info.elements,
            runtime_sec=time.time() - started_at,
            warnings=mesh_warnings + result.warnings,
            notes=solver_notes,
            boundary_role_diagnostics=boundary_role_diagnostics,
        )
        write_summary(job_dir, summary)
        print("[bem_solver] Solve completed successfully.")
        return 0

    except Exception as exc:
        print(f"[bem_solver] ERROR: {exc}", file=sys.stderr)
        traceback.print_exc()

        if prepared_mesh is not None:
            try:
                write_mesh_info(job_dir, prepared_mesh.mesh_info.to_dict())
            except Exception:
                pass

        if job is None:
            summary = {
                "status": "error",
                "mesh_file": "",
                "vertices": 0,
                "elements": 0,
                "source_groups": [],
                "wall_groups": [],
                "freq_count": 0,
                "runtime_sec": round(time.time() - started_at, 3),
                "warnings": [str(exc)],
                "notes": ["The solver failed before job validation completed."],
            }
        else:
            vertices = prepared_mesh.mesh_info.vertices if prepared_mesh is not None else 0
            elements = prepared_mesh.mesh_info.elements if prepared_mesh is not None else 0
            summary = _build_summary(
                status="error",
                job=job,
                vertices=vertices,
                elements=elements,
                runtime_sec=time.time() - started_at,
                warnings=mesh_warnings + [str(exc)],
                notes=solver_notes,
                boundary_role_diagnostics=boundary_role_diagnostics,
            )

        write_summary(job_dir, summary)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
