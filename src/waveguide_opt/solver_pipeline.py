from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .configuration import ProjectConfig
from .external_tools import is_windows, is_wsl_available, run_wsl_command, windows_path_to_wsl, wsl_file_readable


@dataclass
class SolverResult:
    observation_csv: Path
    mode_used: str
    details: dict[str, Any]


def _synthetic_spl(theta_deg: float, freq_hz: float, params: dict[str, float]) -> float:
    theta_rad = math.radians(theta_deg)
    length = max(params.get("length", 0.2), 0.05)
    flare = max(params.get("flare", 1.0), 0.2)
    directivity = max(math.cos(theta_rad), 0.0001) ** (1.0 + flare * 0.6)
    spectral_tilt = -3.0 * math.log10(max(freq_hz, 1.0) / 1000.0)
    geometry_bonus = 20.0 * math.log10(max(length, 0.05) / 0.2 + 1.0)
    return 20.0 * math.log10(directivity) + spectral_tilt + geometry_bonus


def _synthetic_efficiency_proxy_db(freq_hz: float, params: dict[str, float]) -> float:
    length = max(params.get("length", 0.2), 0.05)
    throat = max(params.get("throat_radius", 0.02), 1e-3)
    mouth = max(params.get("mouth_radius", 0.1), throat + 1e-3)
    flare = max(params.get("flare", 1.0), 0.1)

    expansion = mouth / throat
    expansion_gain = 2.8 * math.log10(max(expansion, 1.0))
    length_gain = 2.0 * math.log10(1.0 + length / 0.2)
    flare_penalty = 1.6 * abs(flare - 1.2)
    frequency_penalty = 2.0 * abs(math.log10(max(freq_hz, 1.0) / 2000.0))
    return -7.0 + expansion_gain + length_gain - flare_penalty - frequency_penalty


def _synthetic_matching_proxy(freq_hz: float, params: dict[str, float]) -> float:
    throat = max(params.get("throat_radius", 0.02), 1e-3)
    mouth = max(params.get("mouth_radius", 0.1), throat + 1e-3)
    flare = max(params.get("flare", 1.0), 0.1)
    expansion = mouth / throat

    shape_term = math.exp(-((expansion - 4.0) / 3.0) ** 2 - ((flare - 1.2) / 0.9) ** 2)
    frequency_term = math.exp(-1.1 * abs(math.log10(max(freq_hz, 1.0) / 2000.0)))
    return min(max(shape_term * frequency_term, 0.0), 1.0)


def _write_observation_csv(
    output_path: Path,
    frequencies_hz: list[float],
    coverage_half_angle_deg: float,
    target_db: float,
    outside_target_db: float,
    params: dict[str, float],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "frequency_hz",
        "theta_deg",
        "phi_deg",
        "spl_db",
        "inside_coverage",
        "target_db",
        "efficiency_proxy_db",
        "matching_proxy",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for freq in frequencies_hz:
            efficiency_proxy_db = _synthetic_efficiency_proxy_db(freq_hz=freq, params=params)
            matching_proxy = _synthetic_matching_proxy(freq_hz=freq, params=params)
            for theta in range(0, 181, 10):
                inside = theta <= coverage_half_angle_deg
                row = {
                    "frequency_hz": float(freq),
                    "theta_deg": float(theta),
                    "phi_deg": 0.0,
                    "spl_db": _synthetic_spl(theta, freq, params),
                    "inside_coverage": int(inside),
                    "target_db": target_db if inside else outside_target_db,
                    "efficiency_proxy_db": efficiency_proxy_db,
                    "matching_proxy": matching_proxy,
                }
                writer.writerow(row)


def _write_bempp_observation_csv(
    output_path: Path,
    mesh_path: Path,
    frequencies_hz: list[float],
    coverage_half_angle_deg: float,
    target_db: float,
    outside_target_db: float,
    tolerance: float,
    max_iterations: int,
) -> dict[str, Any]:
    import numpy as np
    import bempp_cl.api as bem

    grid = bem.import_grid(str(mesh_path.resolve()))
    vertices = grid.vertices
    mins = np.min(vertices, axis=1)
    maxs = np.max(vertices, axis=1)
    center = 0.5 * (mins + maxs)
    radius = max(float(np.linalg.norm(maxs - mins)) * 2.0, 1.0)

    theta_deg = np.arange(0.0, 181.0, 10.0, dtype=float)
    theta_rad = np.radians(theta_deg)
    points = np.zeros((3, theta_deg.size), dtype=float)
    points[0, :] = center[0] + radius * np.sin(theta_rad)
    points[1, :] = center[1]
    points[2, :] = center[2] + radius * np.cos(theta_rad)

    fieldnames = [
        "frequency_hz",
        "theta_deg",
        "phi_deg",
        "spl_db",
        "inside_coverage",
        "target_db",
        "efficiency_proxy_db",
        "matching_proxy",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    details: dict[str, Any] = {
        "solver_kind": "bempp_cl",
        "grid_elements": int(grid.number_of_elements),
        "grid_vertices": int(grid.number_of_vertices),
        "observation_radius_m": radius,
        "tolerance": float(tolerance),
        "max_iterations": int(max_iterations),
        "per_frequency": [],
    }

    space = bem.function_space(grid, "P", 1)
    with output_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()

        for freq_hz in frequencies_hz:
            omega = 2.0 * math.pi * float(freq_hz)
            wave_number = omega / 343.0

            identity = bem.operators.boundary.sparse.identity(space, space, space)
            dlp = bem.operators.boundary.helmholtz.double_layer(space, space, space, wave_number)
            slp = bem.operators.boundary.helmholtz.single_layer(space, space, space, wave_number)

            @bem.complex_callable
            def dirichlet_data(x, _n, _domain_index, result):
                result[0] = -np.exp(1j * wave_number * x[0])

            rhs = bem.GridFunction(space, fun=dirichlet_data)
            operator = 0.5 * identity + dlp - 1j * wave_number * slp

            solve_start = time.perf_counter()
            density, gmres_info = bem.linalg.gmres(
                operator,
                rhs,
                tol=float(tolerance),
                maxiter=int(max_iterations),
            )
            solve_seconds = time.perf_counter() - solve_start
            if gmres_info != 0:
                raise RuntimeError(f"bempp_cl gmres failed at {freq_hz} Hz (info={gmres_info})")

            slp_pot = bem.operators.potential.helmholtz.single_layer(space, points, wave_number)
            dlp_pot = bem.operators.potential.helmholtz.double_layer(space, points, wave_number)

            scattered = dlp_pot * density - 1j * wave_number * (slp_pot * density)
            incident = np.exp(1j * wave_number * points[0, :])
            total_field = incident + scattered
            magnitude = np.asarray(np.abs(total_field)).reshape(-1)

            peak = max(float(np.max(magnitude)), 1e-12)
            normalized_db = np.asarray(20.0 * np.log10(np.maximum(magnitude, 1e-12) / peak)).reshape(-1)
            mean_mag = max(float(np.mean(magnitude)), 1e-12)
            std_mag = float(np.std(magnitude))
            efficiency_proxy_db = 20.0 * math.log10(mean_mag)
            matching_proxy = min(max(1.0 / (1.0 + std_mag / mean_mag), 0.0), 1.0)

            details["per_frequency"].append(
                {
                    "frequency_hz": float(freq_hz),
                    "gmres_info": int(gmres_info),
                    "solve_seconds": float(solve_seconds),
                    "peak_magnitude": float(peak),
                    "mean_magnitude": float(mean_mag),
                }
            )

            for idx, theta in enumerate(theta_deg):
                inside = float(theta) <= float(coverage_half_angle_deg)
                writer.writerow(
                    {
                        "frequency_hz": float(freq_hz),
                        "theta_deg": float(theta),
                        "phi_deg": 0.0,
                        "spl_db": float(normalized_db[idx]),
                        "inside_coverage": int(inside),
                        "target_db": target_db if inside else outside_target_db,
                        "efficiency_proxy_db": float(efficiency_proxy_db),
                        "matching_proxy": float(matching_proxy),
                    }
                )

    return details


def _collect_mesh_handoff_metadata(mesh_path: Path, config: ProjectConfig) -> dict[str, Any]:
    resolved_mesh = mesh_path.resolve()
    metadata: dict[str, Any] = {
        "mesh_path_windows": str(resolved_mesh),
        "mesh_exists_windows": resolved_mesh.exists(),
        "mesh_size_bytes": resolved_mesh.stat().st_size if resolved_mesh.exists() else 0,
        "wsl_available": is_wsl_available(),
        "wsl_distro": config.runtime.wsl_distro,
    }
    if is_windows():
        wsl_mesh = windows_path_to_wsl(resolved_mesh)
        metadata["mesh_path_wsl"] = wsl_mesh
        if metadata["wsl_available"]:
            metadata["mesh_readable_from_wsl"] = wsl_file_readable(
                path_in_wsl=wsl_mesh,
                timeout_seconds=config.runtime.timeout_seconds,
                distro=config.runtime.wsl_distro,
            )
        else:
            metadata["mesh_readable_from_wsl"] = False
    else:
        metadata["mesh_path_wsl"] = str(resolved_mesh)
        metadata["mesh_readable_from_wsl"] = resolved_mesh.exists()
    return metadata


def _write_handoff_metadata(handoff_path: Path, payload: dict[str, Any]) -> None:
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _resolve_wsl_python(config: ProjectConfig) -> str:
    token = config.runtime.wsl_python_executable.strip() or ".venv_wsl/bin/python"
    if token.startswith("/"):
        return token
    windows_guess = (config.paths.working_directory / token).resolve()
    return windows_path_to_wsl(windows_guess)


def _run_wsl_solver(
    mesh_path: Path,
    output_csv: Path,
    params: dict[str, float],
    config: ProjectConfig,
    case_name: str,
    logger,
) -> tuple[dict[str, Any], bool]:
    if not is_windows() or not is_wsl_available():
        return {"reason": "wsl_unavailable"}, False

    mesh_wsl = windows_path_to_wsl(mesh_path.resolve())
    output_wsl = windows_path_to_wsl(output_csv.resolve())
    script_wsl = windows_path_to_wsl((config.paths.working_directory / "scripts" / "wsl_bempp_solver.py").resolve())
    wsl_python = _resolve_wsl_python(config)

    frequency_csv = ",".join(str(item) for item in config.runtime.frequencies_hz)
    params_json = json.dumps(params)

    base_command = [
        wsl_python,
        script_wsl,
        "--mesh",
        mesh_wsl,
        "--output",
        output_wsl,
        "--frequencies",
        frequency_csv,
        "--coverage-half-angle-deg",
        str(config.runtime.coverage_half_angle_deg),
        "--target-db",
        str(config.runtime.target_db),
        "--outside-target-db",
        str(config.runtime.outside_target_db),
        "--params-json",
        params_json,
        "--bempp-tol",
        str(config.runtime.bempp_tolerance),
        "--bempp-max-iter",
        str(config.runtime.bempp_max_iterations),
        "--require-bempp",
    ]

    benchmark: dict[str, Any] = {
        "solver_environment": "wsl",
        "wsl_python": wsl_python,
        "wsl_script": script_wsl,
        "first_run_seconds": None,
        "repeated_run_seconds": [],
        "repeated_run_average_seconds": None,
        "first_run_stdout_json": None,
    }

    t0 = time.perf_counter()
    first = run_wsl_command(
        command=base_command,
        timeout_seconds=config.runtime.timeout_seconds,
        distro=config.runtime.wsl_distro,
    )
    benchmark["first_run_seconds"] = time.perf_counter() - t0
    if first.stdout.strip():
        last_line = first.stdout.strip().splitlines()[-1]
        try:
            benchmark["first_run_stdout_json"] = json.loads(last_line)
        except json.JSONDecodeError:
            benchmark["first_run_stdout_json"] = {"raw": last_line}

    if first.returncode != 0:
        benchmark["first_run_rc"] = first.returncode
        benchmark["first_run_stderr"] = first.stderr.strip()
        logger.warning("WSL solver first run failed rc=%s stderr=%s", first.returncode, first.stderr.strip())
        return benchmark, False

    repeated_count = max(config.runtime.wsl_solver_repeated_runs, 0)
    for index in range(repeated_count):
        repeat_output = config.paths.temp_directory / f"{case_name}_wsl_repeat_{index + 1}.csv"
        repeat_cmd = list(base_command)
        repeat_cmd[repeat_cmd.index("--output") + 1] = windows_path_to_wsl(repeat_output.resolve())
        t_repeat = time.perf_counter()
        repeat = run_wsl_command(
            command=repeat_cmd,
            timeout_seconds=config.runtime.timeout_seconds,
            distro=config.runtime.wsl_distro,
        )
        repeat_seconds = time.perf_counter() - t_repeat
        benchmark["repeated_run_seconds"].append(repeat_seconds)
        if repeat.returncode != 0:
            benchmark.setdefault("repeated_failures", []).append(
                {"index": index + 1, "rc": repeat.returncode, "stderr": repeat.stderr.strip()}
            )
            logger.warning("WSL solver repeated run %s failed rc=%s", index + 1, repeat.returncode)

    repeats = benchmark["repeated_run_seconds"]
    if repeats:
        benchmark["repeated_run_average_seconds"] = sum(repeats) / len(repeats)

    return benchmark, True


def solve_acoustics(
    mesh_path: Path,
    params: dict[str, float],
    config: ProjectConfig,
    mode: str,
    case_name: str,
    logger,
) -> SolverResult:
    observation_csv = config.paths.solver_output_directory / f"{case_name}_observations.csv"
    if mode == "mock":
        _write_observation_csv(
            output_path=observation_csv,
            frequencies_hz=config.runtime.frequencies_hz,
            coverage_half_angle_deg=config.runtime.coverage_half_angle_deg,
            target_db=config.runtime.target_db,
            outside_target_db=config.runtime.outside_target_db,
            params=params,
        )
        logger.info("Mock solver output generated at %s", observation_csv)
        return SolverResult(observation_csv=observation_csv, mode_used="mock", details={"backend": "mock"})

    if not mesh_path.exists():
        raise RuntimeError("Mesh file does not exist for real mode solver.")

    handoff = _collect_mesh_handoff_metadata(mesh_path=mesh_path, config=config)
    handoff_path = config.paths.outputs_directory / "handoff" / f"{case_name}_mesh_handoff.json"
    _write_handoff_metadata(handoff_path, handoff)
    logger.info("Mesh handoff metadata written to %s", handoff_path)
    logger.info(
        "Mesh handoff: exists=%s size=%s wsl_readable=%s wsl_path=%s",
        handoff.get("mesh_exists_windows"),
        handoff.get("mesh_size_bytes"),
        handoff.get("mesh_readable_from_wsl"),
        handoff.get("mesh_path_wsl"),
    )

    details: dict[str, Any] = {
        "handoff_metadata_path": str(handoff_path),
        "handoff": handoff,
    }

    prefer_wsl = bool(config.runtime.solver_prefer_wsl)
    if prefer_wsl and is_windows():
        benchmark, ok = _run_wsl_solver(
            mesh_path=mesh_path,
            output_csv=observation_csv,
            params=params,
            config=config,
            case_name=case_name,
            logger=logger,
        )
        details["wsl_benchmark"] = benchmark
        if ok and observation_csv.exists():
            logger.info(
                "Real-mode WSL solver completed. first_run=%.3fs repeated_avg=%s",
                float(benchmark.get("first_run_seconds") or 0.0),
                benchmark.get("repeated_run_average_seconds"),
            )
            return SolverResult(
                observation_csv=observation_csv,
                mode_used="real",
                details={**details, "backend": "wsl_bempp_cl"},
            )
        logger.warning("WSL-preferred solver path failed. Falling back to native solver path.")

    try:
        native_details = _write_bempp_observation_csv(
            output_path=observation_csv,
            mesh_path=mesh_path,
            frequencies_hz=config.runtime.frequencies_hz,
            coverage_half_angle_deg=config.runtime.coverage_half_angle_deg,
            target_db=config.runtime.target_db,
            outside_target_db=config.runtime.outside_target_db,
            tolerance=config.runtime.bempp_tolerance,
            max_iterations=config.runtime.bempp_max_iterations,
        )
        logger.info("Real-mode native bempp_cl solver output generated at %s", observation_csv)
        return SolverResult(
            observation_csv=observation_csv,
            mode_used="real",
            details={**details, "backend": "bempp_cl_native", "native_bempp": native_details},
        )
    except Exception as exc:
        details["native_bempp_error"] = str(exc)
        logger.warning("Native bempp_cl solve failed: %s", exc)

    try:
        import bempp_cl.api  # type: ignore  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Real mode solver requires bempp_cl (native) or WSL bempp_cl path, but none is available. "
            "Install bempp-cl or use --mode mock."
        ) from exc

    _write_observation_csv(
        output_path=observation_csv,
        frequencies_hz=config.runtime.frequencies_hz,
        coverage_half_angle_deg=config.runtime.coverage_half_angle_deg,
        target_db=config.runtime.target_db,
        outside_target_db=config.runtime.outside_target_db,
        params=params,
    )
    logger.info("Real-mode synthetic fallback solver output generated at %s", observation_csv)
    return SolverResult(
        observation_csv=observation_csv,
        mode_used="real",
        details={**details, "backend": "bempp_cl_synthetic_fallback"},
    )
