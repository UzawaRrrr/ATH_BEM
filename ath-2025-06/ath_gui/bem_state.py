"""BEM GUI state helpers and job.json serialization."""

from __future__ import annotations

import re
from pathlib import Path

from .bem_specs import BEM_FIELD_SECTIONS


BEM_FIELD_SPECS = {
    spec.key: spec
    for _description, fields in BEM_FIELD_SECTIONS
    for spec in fields
}


def default_bem_state() -> dict[str, object]:
    return {spec.key: spec.default for spec in BEM_FIELD_SPECS.values()}


def normalize_bem_state(state: dict[str, object] | None = None) -> dict[str, object]:
    normalized = default_bem_state()
    if not state:
        return normalized
    for key, value in state.items():
        if key in normalized:
            normalized[key] = value
    return normalized


def _split_numeric_tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[\s,;]+", text.strip()) if token]


def parse_int_list(value: object) -> list[int]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        return [int(token) for token in _split_numeric_tokens(text)]
    except ValueError as exc:
        raise ValueError("Groups must be integers separated by commas, spaces, or semicolons.") from exc


def parse_float_list(value: object) -> list[float]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        return [float(token) for token in _split_numeric_tokens(text)]
    except ValueError as exc:
        raise ValueError("Numeric values must be separated by commas, spaces, or semicolons.") from exc


def parse_direction_list(value: object) -> list[list[float]]:
    text = str(value or "").strip()
    if not text:
        return [[0.0, 0.0, 1.0]]

    vectors: list[list[float]] = []
    for chunk in [item.strip() for item in text.replace("\n", ";").split(";") if item.strip()]:
        parts = [token for token in re.split(r"[\s,]+", chunk) if token]
        if len(parts) != 3:
            raise ValueError("Each source direction must use three numbers, for example `0,0,1`.")
        try:
            vectors.append([float(part) for part in parts])
        except ValueError as exc:
            raise ValueError("Source directions must contain numeric XYZ values.") from exc
    return vectors


def _broadcast_scalars(values: list[float], target_count: int, label: str) -> list[float]:
    if not values:
        raise ValueError(f"{label} must contain at least one value.")
    if len(values) == 1:
        return values * target_count
    if len(values) != target_count:
        raise ValueError(f"{label} must contain either 1 value or exactly {target_count} values.")
    return values


def _broadcast_vectors(values: list[list[float]], target_count: int, label: str) -> list[list[float]]:
    if not values:
        raise ValueError(f"{label} must contain at least one vector.")
    if len(values) == 1:
        return values * target_count
    if len(values) != target_count:
        raise ValueError(f"{label} must contain either 1 vector or exactly {target_count} vectors.")
    return values


def build_job_payload(state: dict[str, object], mesh_file: Path, mesh_file_wsl: str) -> dict[str, object]:
    merged = normalize_bem_state(state)
    source_groups = parse_int_list(merged["BEM.SourceGroups"])
    if not source_groups:
        raise ValueError("Source groups are required before launching BEM.")

    source_gain = _broadcast_scalars(parse_float_list(merged["BEM.SourceGain"]), len(source_groups), "Source gain")
    source_direction = _broadcast_vectors(parse_direction_list(merged["BEM.SourceDirection"]), len(source_groups), "Source direction")

    if not mesh_file.exists():
        raise ValueError(f"Mesh file was not found: {mesh_file}")

    solver_mode = str(merged["BEM.SolverMode"]).strip() or "exterior_velocity_bc"
    plane = str(merged["BEM.Plane"]).strip().upper() or "XZ"

    try:
        mesh_scale_to_meter = float(merged["BEM.MeshScaleToMeter"])
        f1 = float(merged["BEM.F1"])
        f2 = float(merged["BEM.F2"])
        num_freq = int(float(merged["BEM.NumFreq"]))
        rho0 = float(merged["BEM.Rho0"])
        c0 = float(merged["BEM.C0"])
        mic_distance = float(merged["BEM.MicDistance"])
        theta_count = int(float(merged["BEM.ThetaCount"]))
        reference_pressure = float(merged["BEM.ReferencePressure"])
    except ValueError as exc:
        raise ValueError("BEM numeric fields contain an invalid value.") from exc

    if mesh_scale_to_meter <= 0:
        raise ValueError("Mesh scale to meter must be greater than zero.")
    if f1 <= 0 or f2 < f1:
        raise ValueError("Frequency start/stop must satisfy `0 < start <= stop`.")
    if num_freq < 1:
        raise ValueError("Frequency points must be at least 1.")
    if mic_distance <= 0:
        raise ValueError("Mic distance must be greater than zero.")
    if theta_count < 3:
        raise ValueError("Theta count must be at least 3.")
    if plane not in {"XZ", "YZ"}:
        raise ValueError("Observation plane must be either `XZ` or `YZ`.")

    return {
        "mesh_file": mesh_file.resolve().as_posix(),
        "mesh_file_wsl": mesh_file_wsl,
        "mesh_scale_to_meter": mesh_scale_to_meter,
        "solver_mode": solver_mode,
        "source_groups": source_groups,
        "wall_groups": parse_int_list(merged["BEM.WallGroups"]),
        "interface_groups": parse_int_list(merged["BEM.InterfaceGroups"]),
        "ignore_groups": parse_int_list(merged["BEM.IgnoreGroups"]),
        "source_gain": source_gain,
        "source_direction": source_direction,
        "velocity_model": str(merged["BEM.VelocityModel"]).strip() or "uniform",
        "f1": f1,
        "f2": f2,
        "num_freq": num_freq,
        "rho0": rho0,
        "c0": c0,
        "mic_distance": mic_distance,
        "plane": plane,
        "theta_count": theta_count,
        "reference_pressure": reference_pressure,
        "export_png": bool(merged["BEM.ExportPng"]),
        "export_boundary_pressure": bool(merged["BEM.ExportBoundaryPressure"]),
    }
