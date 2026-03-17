#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path
from typing import Any


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


def _write_synthetic_csv(
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
                writer.writerow(
                    {
                        "frequency_hz": float(freq),
                        "theta_deg": float(theta),
                        "phi_deg": 0.0,
                        "spl_db": _synthetic_spl(theta, freq, params),
                        "inside_coverage": int(inside),
                        "target_db": target_db if inside else outside_target_db,
                        "efficiency_proxy_db": efficiency_proxy_db,
                        "matching_proxy": matching_proxy,
                    }
                )


def _write_bempp_csv(
    output_path: Path,
    mesh_path: Path,
    frequencies_hz: list[float],
    coverage_half_angle_deg: float,
    target_db: float,
    outside_target_db: float,
    bempp_tol: float,
    bempp_max_iter: int,
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
        "tolerance": float(bempp_tol),
        "max_iterations": int(bempp_max_iter),
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
                tol=float(bempp_tol),
                maxiter=int(bempp_max_iter),
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


def _parse_frequencies(raw: str) -> list[float]:
    result: list[float] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        result.append(float(token))
    if not result:
        raise ValueError("No valid frequencies provided.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="WSL-side BEM solver runner with mesh handoff validation.")
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frequencies", type=str, required=True)
    parser.add_argument("--coverage-half-angle-deg", type=float, required=True)
    parser.add_argument("--target-db", type=float, required=True)
    parser.add_argument("--outside-target-db", type=float, required=True)
    parser.add_argument("--params-json", type=str, required=True)
    parser.add_argument("--bempp-tol", type=float, default=1.0e-5)
    parser.add_argument("--bempp-max-iter", type=int, default=400)
    parser.add_argument("--require-bempp", action="store_true")
    args = parser.parse_args()

    started = time.perf_counter()
    mesh_path = args.mesh
    if not mesh_path.exists():
        raise FileNotFoundError(f"Mesh not found in WSL: {mesh_path}")

    frequencies = _parse_frequencies(args.frequencies)
    params = json.loads(args.params_json)
    if not isinstance(params, dict):
        raise ValueError("--params-json must decode to an object.")
    params = {str(k): float(v) for k, v in params.items()}

    bempp_import_seconds = None
    bempp_available = False
    t_import = time.perf_counter()
    try:
        import bempp_cl.api  # type: ignore  # noqa: F401

        bempp_available = True
        bempp_import_seconds = time.perf_counter() - t_import
    except Exception:
        bempp_available = False
        bempp_import_seconds = time.perf_counter() - t_import
        if args.require_bempp:
            raise RuntimeError("bempp_cl.api is not importable in WSL solver environment.")

    mesh_read_seconds = None
    mesh_readable = False
    t_mesh = time.perf_counter()
    try:
        import meshio  # type: ignore

        meshio.read(mesh_path)
        mesh_readable = True
        mesh_read_seconds = time.perf_counter() - t_mesh
    except Exception:
        mesh_readable = False
        mesh_read_seconds = time.perf_counter() - t_mesh

    solver_mode = "synthetic"
    solver_details: dict[str, Any] = {}
    bempp_error = ""

    if bempp_available:
        try:
            solver_details = _write_bempp_csv(
                output_path=args.output,
                mesh_path=mesh_path,
                frequencies_hz=frequencies,
                coverage_half_angle_deg=args.coverage_half_angle_deg,
                target_db=args.target_db,
                outside_target_db=args.outside_target_db,
                bempp_tol=max(args.bempp_tol, 1.0e-8),
                bempp_max_iter=max(args.bempp_max_iter, 1),
            )
            solver_mode = "bempp_cl"
        except Exception as exc:
            bempp_error = str(exc)
            if args.require_bempp:
                raise

    if solver_mode != "bempp_cl":
        _write_synthetic_csv(
            output_path=args.output,
            frequencies_hz=frequencies,
            coverage_half_angle_deg=args.coverage_half_angle_deg,
            target_db=args.target_db,
            outside_target_db=args.outside_target_db,
            params=params,
        )

    total_seconds = time.perf_counter() - started
    print(
        json.dumps(
            {
                "status": "ok",
                "mesh": str(mesh_path),
                "output": str(args.output),
                "solver_mode": solver_mode,
                "bempp_available": bempp_available,
                "bempp_import_seconds": bempp_import_seconds,
                "mesh_readable_by_meshio": mesh_readable,
                "mesh_read_seconds": mesh_read_seconds,
                "bempp_error": bempp_error,
                "solver_details": solver_details,
                "solver_total_seconds": total_seconds,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
