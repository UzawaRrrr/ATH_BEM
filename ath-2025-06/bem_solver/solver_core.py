"""Exterior Helmholtz Bempp solver core for ATH meshes."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy.sparse.linalg import gmres as scipy_gmres

from job_model import BemJob
from mesh_adapter import PreparedMesh
from postprocess import build_frequency_axis, build_observation_points, pressure_to_spl
from symmetry import build_image_transforms
from symmetry_mesh import validate_reduced_mesh_against_symmetry, write_mirrored_meshes

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


def _solve_linear_system(
    lhs: object,
    rhs: np.ndarray,
    *,
    tol: float = 1.0e-5,
    x0: np.ndarray | None = None,
) -> tuple[np.ndarray, int, int]:
    iterations = 0

    def _callback(_residual: np.ndarray) -> None:
        nonlocal iterations
        iterations += 1

    gmres_kwargs: dict[str, object] = {}
    if x0 is not None:
        x0_vector = np.asarray(x0, dtype=np.complex128).reshape(-1)
        rhs_vector = np.asarray(rhs).reshape(-1)
        if x0_vector.size == rhs_vector.size:
            gmres_kwargs["x0"] = x0_vector
    solution, info = scipy_gmres(lhs, rhs, rtol=tol, atol=0.0, callback=_callback, **gmres_kwargs)
    return np.asarray(solution, dtype=np.complex128), int(info), int(iterations)


def _build_velocity_coefficients(
    velocity_space: object,
    *,
    gain: float,
    direction: list[float],
) -> np.ndarray:
    return (
        np.ones(velocity_space.grid_dof_count, dtype=np.complex128)
        * gain
        * _direction_correction(velocity_space, direction)
    )


def compute_velocity_frequency_weighting(mode: str, omega: float) -> complex:
    """Return the per-frequency complex source-velocity weighting factor."""
    normalized = str(mode).strip().lower()
    if normalized == "none":
        return 1.0 + 0.0j
    if normalized == "inverse_jw":
        if not np.isfinite(omega) or omega <= 0.0:
            raise ValueError(f"inverse_jw requires a positive angular frequency, got {omega!r}.")
        return 1.0 / (1j * omega)
    raise ValueError(f"Unsupported velocity_frequency_weighting mode: {mode!r}")


def transform_direction(direction: list[float], image: object) -> np.ndarray:
    """Transform a direction vector by the linear part of an image transform."""
    vector = np.asarray(direction, dtype=float).reshape(3)
    matrix = np.asarray(getattr(image, "matrix"), dtype=float)
    return matrix @ vector


def solve_exterior_velocity_bc(job: BemJob, prepared_mesh: PreparedMesh) -> SolverResult:
    """Dispatch to the standard or symmetry-reduced solver path."""
    if job.symmetry.enabled:
        return solve_exterior_velocity_bc_with_symmetry(job, prepared_mesh)
    return solve_exterior_velocity_bc_standard(job, prepared_mesh)


def solve_exterior_velocity_bc_standard(job: BemJob, prepared_mesh: PreparedMesh) -> SolverResult:
    import bempp_cl.api
    from bempp_cl.api.operators.boundary import helmholtz, sparse
    from bempp_cl.api.operators.potential import helmholtz as helmholtz_potential

    frequencies_hz = build_frequency_axis(job)
    _theta_rad, angles_deg, observation_points = build_observation_points(job)
    warnings_out: list[str] = []
    notes = [
        "Rigid-wall behavior is modeled as zero normal velocity on all non-source surface groups.",
        f"Velocity model: {job.velocity_model}",
        "Symmetry reduction: disabled",
    ]

    grid = bempp_cl.api.import_grid(str(prepared_mesh.grid_file))
    pressure_space = bempp_cl.api.function_space(grid, "P", 1)
    identity_wf = sparse.identity(pressure_space, pressure_space, pressure_space).weak_form()

    pressure_complex = np.zeros((len(frequencies_hz), len(angles_deg)), dtype=np.complex128)
    source_gain = job.expanded_source_gain()
    source_direction = job.expanded_source_direction()

    source_metadata: list[dict[str, object]] = []
    for source_index, group_id in enumerate(job.source_groups):
        velocity_space = bempp_cl.api.function_space(grid, "DP", 0, segments=[group_id])
        if velocity_space.grid_dof_count == 0:
            raise ValueError(f"Source group {group_id} resolved to an empty Bempp segment.")
        base_coefficients = _build_velocity_coefficients(
            velocity_space,
            gain=source_gain[source_index],
            direction=source_direction[source_index],
        )
        source_metadata.append(
            {
                "source_index": source_index,
                "group_id": group_id,
                "velocity_space": velocity_space,
                "base_coefficients": base_coefficients,
            }
        )

    previous_solution_by_source: dict[int, np.ndarray] = {}
    for freq_index, freq_hz in enumerate(frequencies_hz):
        omega = 2.0 * np.pi * freq_hz
        wave_number = omega / job.c0
        velocity_weighting = compute_velocity_frequency_weighting(job.velocity_frequency_weighting, omega)
        lhs = helmholtz.double_layer(pressure_space, pressure_space, pressure_space, wave_number).weak_form() - 0.5 * identity_wf
        pressure_potential = helmholtz_potential.double_layer(pressure_space, observation_points, wave_number)

        for source_meta in source_metadata:
            source_index = int(source_meta["source_index"])
            group_id = int(source_meta["group_id"])
            velocity_space = source_meta["velocity_space"]
            base_coefficients = source_meta["base_coefficients"]
            weighted_coefficients = np.asarray(base_coefficients * velocity_weighting, dtype=np.complex128)
            velocity_boundary = bempp_cl.api.GridFunction(velocity_space, coefficients=weighted_coefficients)

            rhs = 1j * omega * job.rho0 * (
                helmholtz.single_layer(velocity_space, pressure_space, pressure_space, wave_number).weak_form()
                @ weighted_coefficients
            )
            pressure_coefficients, info, iterations = _solve_linear_system(
                lhs,
                rhs,
                x0=previous_solution_by_source.get(source_index),
            )
            previous_solution_by_source[source_index] = pressure_coefficients

            if info != 0:
                warnings_out.append(f"GMRES returned info={info} for source group {group_id} at {freq_hz:.3f} Hz.")
            if freq_index == 0:
                notes.append(f"Source group {group_id}: {iterations} GMRES iterations at {freq_hz:.3f} Hz.")

            pressure_boundary = bempp_cl.api.GridFunction(pressure_space, coefficients=pressure_coefficients)
            mic_pressure = (
                pressure_potential * pressure_boundary
                - 1j
                * omega
                * job.rho0
                * (helmholtz_potential.single_layer(velocity_space, observation_points, wave_number) * velocity_boundary)
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


def solve_exterior_velocity_bc_with_symmetry(job: BemJob, prepared_mesh: PreparedMesh) -> SolverResult:
    import bempp_cl.api
    from bempp_cl.api.operators.boundary import helmholtz, sparse
    from bempp_cl.api.operators.potential import helmholtz as helmholtz_potential

    frequencies_hz = build_frequency_axis(job)
    _theta_rad, angles_deg, observation_points = build_observation_points(job)
    warnings_out: list[str] = []
    notes = [
        "Rigid-wall behavior is modeled as zero normal velocity on all non-source surface groups.",
        f"Velocity model: {job.velocity_model}",
        f"Symmetry reduction: {job.symmetry.mode_label}",
    ]

    validation = validate_reduced_mesh_against_symmetry(prepared_mesh, job.symmetry)
    warnings_out.extend(validation.warnings)
    images = build_image_transforms(job.symmetry)
    mirrored_meshes = write_mirrored_meshes(prepared_mesh, images, job.job_dir / "symmetry")
    for mirrored in mirrored_meshes:
        notes.append(
            "Mirrored mesh "
            f"{mirrored.name}: det={mirrored.determinant:.6g}, "
            f"orientation_reversing={mirrored.orientation_reversing}, "
            f"winding_reversed={mirrored.winding_reversed}."
        )

    base_grid = bempp_cl.api.import_grid(str(prepared_mesh.grid_file))
    pressure_space = bempp_cl.api.function_space(base_grid, "P", 1)
    identity_wf = sparse.identity(pressure_space, pressure_space, pressure_space).weak_form()

    mirrored_grids = {item.name: bempp_cl.api.import_grid(str(item.mesh_file)) for item in mirrored_meshes}
    mirrored_pressure_spaces = {
        item.name: bempp_cl.api.function_space(mirrored_grids[item.name], "P", 1)
        for item in mirrored_meshes
    }

    pressure_complex = np.zeros((len(frequencies_hz), len(angles_deg)), dtype=np.complex128)
    source_gain = job.expanded_source_gain()
    source_direction = job.expanded_source_direction()

    source_metadata: list[dict[str, object]] = []
    for source_index, group_id in enumerate(job.source_groups):
        base_direction = source_direction[source_index]
        velocity_space = bempp_cl.api.function_space(base_grid, "DP", 0, segments=[group_id])
        if velocity_space.grid_dof_count == 0:
            raise ValueError(f"Source group {group_id} resolved to an empty Bempp segment.")
        base_coefficients = _build_velocity_coefficients(
            velocity_space,
            gain=source_gain[source_index],
            direction=base_direction,
        )
        mirrored_velocity_spaces: dict[str, object] = {}
        mirrored_base_coefficients: dict[str, np.ndarray] = {}
        for item in mirrored_meshes:
            mirrored_velocity_space = bempp_cl.api.function_space(mirrored_grids[item.name], "DP", 0, segments=[group_id])
            if mirrored_velocity_space.grid_dof_count != velocity_space.grid_dof_count:
                raise ValueError(
                    f"Mirrored source space DOF mismatch for group {group_id} in image {item.name}: "
                    f"{mirrored_velocity_space.grid_dof_count} != {velocity_space.grid_dof_count}"
                )
            mirrored_velocity_spaces[item.name] = mirrored_velocity_space
            transformed_direction = transform_direction(base_direction, item.image).tolist()
            mirrored_base_coefficients[item.name] = _build_velocity_coefficients(
                mirrored_velocity_space,
                gain=source_gain[source_index],
                direction=transformed_direction,
            )
            notes.append(
                "Mirrored source setup "
                f"group={group_id}, image={item.name}, direction={transformed_direction}, "
                f"dof={mirrored_velocity_space.grid_dof_count}, coeff_dtype={mirrored_base_coefficients[item.name].dtype}, "
                "parity_sign_applied_in_operator_terms=True."
            )

        source_metadata.append(
            {
                "source_index": source_index,
                "group_id": group_id,
                "velocity_space": velocity_space,
                "base_coefficients": base_coefficients,
                "mirrored_velocity_spaces": mirrored_velocity_spaces,
                "mirrored_base_coefficients": mirrored_base_coefficients,
            }
        )

    previous_solution_by_source: dict[int, np.ndarray] = {}
    for freq_index, freq_hz in enumerate(frequencies_hz):
        omega = 2.0 * np.pi * freq_hz
        wave_number = omega / job.c0
        velocity_weighting = compute_velocity_frequency_weighting(job.velocity_frequency_weighting, omega)

        lhs = helmholtz.double_layer(pressure_space, pressure_space, pressure_space, wave_number).weak_form() - 0.5 * identity_wf
        pressure_potential = helmholtz_potential.double_layer(pressure_space, observation_points, wave_number)
        mirrored_pressure_potentials: dict[str, object] = {}
        for item in mirrored_meshes:
            lhs = lhs + (
                item.image.sign
                * helmholtz.double_layer(
                    mirrored_pressure_spaces[item.name],
                    pressure_space,
                    pressure_space,
                    wave_number,
                ).weak_form()
            )
            mirrored_pressure_potentials[item.name] = helmholtz_potential.double_layer(
                mirrored_pressure_spaces[item.name],
                observation_points,
                wave_number,
            )

        for source_meta in source_metadata:
            source_index = int(source_meta["source_index"])
            group_id = int(source_meta["group_id"])
            velocity_space = source_meta["velocity_space"]
            base_coefficients = source_meta["base_coefficients"]
            mirrored_velocity_spaces = dict(source_meta["mirrored_velocity_spaces"])
            mirrored_base_coefficients = dict(source_meta["mirrored_base_coefficients"])
            weighted_coefficients = np.asarray(base_coefficients * velocity_weighting, dtype=np.complex128)
            mirrored_weighted_coefficients = {
                item.name: np.asarray(
                    mirrored_base_coefficients[item.name] * velocity_weighting,
                    dtype=np.complex128,
                )
                for item in mirrored_meshes
            }
            velocity_boundary = bempp_cl.api.GridFunction(velocity_space, coefficients=weighted_coefficients)
            mirrored_velocity_boundaries = {
                item.name: bempp_cl.api.GridFunction(
                    mirrored_velocity_spaces[item.name],
                    coefficients=mirrored_weighted_coefficients[item.name],
                )
                for item in mirrored_meshes
            }

            rhs = 1j * omega * job.rho0 * (
                helmholtz.single_layer(velocity_space, pressure_space, pressure_space, wave_number).weak_form()
                @ weighted_coefficients
            )
            for item in mirrored_meshes:
                rhs = rhs + (
                    1j
                    * omega
                    * job.rho0
                    * item.image.sign
                    * (
                        helmholtz.single_layer(
                            mirrored_velocity_spaces[item.name],
                            pressure_space,
                            pressure_space,
                            wave_number,
                        ).weak_form()
                        @ mirrored_weighted_coefficients[item.name]
                    )
                )

            pressure_coefficients, info, iterations = _solve_linear_system(
                lhs,
                rhs,
                x0=previous_solution_by_source.get(source_index),
            )
            previous_solution_by_source[source_index] = pressure_coefficients

            if info != 0:
                warnings_out.append(
                    f"GMRES returned info={info} for source group {group_id} at {freq_hz:.3f} Hz "
                    f"with symmetry mode {job.symmetry.mode_label}."
                )
            if freq_index == 0:
                notes.append(
                    f"Source group {group_id}: {iterations} GMRES iterations at {freq_hz:.3f} Hz "
                    f"with symmetry mode {job.symmetry.mode_label}."
                )

            pressure_boundary = bempp_cl.api.GridFunction(pressure_space, coefficients=pressure_coefficients)
            mic_pressure = (
                pressure_potential * pressure_boundary
                - 1j
                * omega
                * job.rho0
                * (helmholtz_potential.single_layer(velocity_space, observation_points, wave_number) * velocity_boundary)
            )

            for item in mirrored_meshes:
                mirrored_pressure = bempp_cl.api.GridFunction(
                    mirrored_pressure_spaces[item.name],
                    coefficients=pressure_coefficients,
                )
                mic_pressure = mic_pressure + (
                    item.image.sign
                    * (
                        mirrored_pressure_potentials[item.name] * mirrored_pressure
                        - 1j
                        * omega
                        * job.rho0
                        * (
                            helmholtz_potential.single_layer(
                                mirrored_velocity_spaces[item.name],
                                observation_points,
                                wave_number,
                            )
                            * mirrored_velocity_boundaries[item.name]
                        )
                    )
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
