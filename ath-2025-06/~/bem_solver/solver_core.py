"""Exterior Helmholtz Bempp solver core for ATH meshes."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from job_model import BemJob
from postprocess import build_frequency_axis, build_observation_points, pressure_to_spl

warnings.filterwarnings("ignore", message="splu requires CSC matrix format")
warnings.filterwarnings("ignore", message="splu converted its input to CSC format")
try:
    from pyopencl import CompilerWarning

    warnings.filterwarnings("ignore", category=CompilerWarning)
except Exception:
    pass


@dataclass
class SolverResult:
    frequencies_hz: np.ndarray
    angles_deg: np.ndarray
    pressure_complex: np.ndarray
    spl_db: np.ndarray
    warnings: list[str]
    notes: list[str]


def _direction_correction(space_u: object, direction: list[float]) -> np.ndarray:
    vector = np.asarray(direction, dtype=float)
    norm = np.linalg.norm(vector)
    if norm <= 1e-12:
        return np.ones(space_u.grid_dof_count, dtype=float)
    vector = vector / norm

    corrections = np.ones(space_u.grid_dof_count, dtype=float)
    normals = space_u.grid.normals
    for index, element in enumerate(space_u.support_elements):
        normal = np.asarray(normals[element, :], dtype=float)
        normal_norm = np.linalg.norm(normal)
        if normal_norm <= 1e-12:
            corrections[index] = 1.0
            continue
        corrections[index] = float(np.dot(vector, normal / normal_norm))
    return corrections


def solve_exterior_velocity_bc(job: BemJob, grid_file: str) -> SolverResult:
    import bempp_cl.api
    from bempp_cl.api.linalg import gmres
    from bempp_cl.api.operators.boundary import helmholtz, sparse
    from bempp_cl.api.operators.potential import helmholtz as helmholtz_potential

    frequencies_hz = build_frequency_axis(job)
    _theta_rad, angles_deg, observation_points = build_observation_points(job)
    warnings_out: list[str] = []
    notes = [
        "Rigid-wall behavior is modeled as zero normal velocity on all non-source surface groups.",
        f"Velocity model: {job.velocity_model}",
    ]

    grid = bempp_cl.api.import_grid(grid_file)
    pressure_space = bempp_cl.api.function_space(grid, "P", 1)
    identity = sparse.identity(pressure_space, pressure_space, pressure_space)

    pressure_complex = np.zeros((len(frequencies_hz), len(angles_deg)), dtype=np.complex128)
    source_gain = job.expanded_source_gain()
    source_direction = job.expanded_source_direction()

    for source_index, group_id in enumerate(job.source_groups):
        velocity_space = bempp_cl.api.function_space(grid, "DP", 0, segments=[group_id])
        if velocity_space.grid_dof_count == 0:
            raise ValueError(f"Source group {group_id} resolved to an empty Bempp segment.")

        base_coefficients = (
            np.ones(velocity_space.grid_dof_count, dtype=np.complex128)
            * source_gain[source_index]
            * _direction_correction(velocity_space, source_direction[source_index])
        )

        for freq_index, freq_hz in enumerate(frequencies_hz):
            omega = 2.0 * np.pi * freq_hz
            wave_number = omega / job.c0
            velocity_boundary = bempp_cl.api.GridFunction(
                velocity_space,
                coefficients=base_coefficients,
            )

            double_layer = helmholtz.double_layer(pressure_space, pressure_space, pressure_space, wave_number)
            single_layer = helmholtz.single_layer(velocity_space, pressure_space, pressure_space, wave_number)
            lhs = double_layer - 0.5 * identity
            rhs = 1j * omega * job.rho0 * (single_layer * velocity_boundary)

            pressure_boundary, info, iterations = gmres(
                lhs,
                rhs,
                tol=1e-5,
                return_iteration_count=True,
            )
            if info != 0:
                warnings_out.append(
                    f"GMRES returned info={info} for source group {group_id} at {freq_hz:.3f} Hz."
                )
            if freq_index == 0:
                notes.append(f"Source group {group_id}: {iterations} GMRES iterations at {freq_hz:.3f} Hz.")

            double_layer_potential = helmholtz_potential.double_layer(pressure_space, observation_points, wave_number)
            single_layer_potential = helmholtz_potential.single_layer(velocity_space, observation_points, wave_number)
            mic_pressure = (
                double_layer_potential * pressure_boundary
                - 1j * omega * job.rho0 * (single_layer_potential * velocity_boundary)
            )
            pressure_complex[freq_index, :] += np.asarray(mic_pressure).reshape(-1)

    spl_db = pressure_to_spl(pressure_complex, job.reference_pressure)
    return SolverResult(
        frequencies_hz=frequencies_hz,
        angles_deg=angles_deg,
        pressure_complex=pressure_complex,
        spl_db=spl_db,
        warnings=warnings_out,
        notes=notes,
    )
