"""BEM GUI state helpers and job.json serialization."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from ..domain.bem_specs import (
    BEM_FIELD_SECTIONS,
    BEM_GUIDED_BASE_GROUPS,
    BEM_GUIDED_FIELD_GROUPS,
    BEM_GUIDED_RULES,
    BEM_SANITIZE_RESET_VALUES,
)
from ..domain.runtime import RUNTIME_LAYOUT
from .group_mapper import mesh_family_key, suggest_group_map


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


def _state_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _guided_group_keys(group_names: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    keys: list[str] = []
    for group_name in group_names:
        keys.extend(BEM_GUIDED_FIELD_GROUPS.get(group_name, ()))
    return tuple(dict.fromkeys(keys))


def _apply_guided_rule_case(
    field_states: dict[str, dict[str, object]],
    rule_cases: dict[str, dict[str, object]],
    case_key: str,
) -> None:
    case = rule_cases.get(case_key, rule_cases.get("__default__", {}))
    relevant_groups = tuple(case.get("relevant_groups", ()))
    inactive_groups = dict(case.get("inactive_groups", {}))

    for key in _guided_group_keys(relevant_groups):
        state = field_states.setdefault(key, {"relevant": True, "reason": ""})
        state["relevant"] = True
        state["reason"] = ""

    for group_name, reason in inactive_groups.items():
        for key in _guided_group_keys([group_name]):
            state = field_states.setdefault(key, {"relevant": True, "reason": ""})
            state["relevant"] = False
            state["reason"] = str(reason).strip()


def build_bem_guided_field_states(state: dict[str, object] | None = None, ath_state: dict[str, object] | None = None) -> dict[str, dict[str, object]]:
    current = normalize_bem_state(state)
    field_states = {
        key: {"relevant": False, "reason": ""}
        for key in BEM_FIELD_SPECS
    }
    for key in _guided_group_keys(BEM_GUIDED_BASE_GROUPS):
        field_states[key] = {"relevant": True, "reason": ""}

    enabled_key = "1" if _state_truthy(current.get("BEM.Enabled", False)) else "__default__"
    _apply_guided_rule_case(field_states, BEM_GUIDED_RULES["BEM.Enabled"], enabled_key)
    if enabled_key != "1":
        return field_states

    backend = str(current.get("BEM.Backend", "wsl")).strip().lower() or "wsl"
    _apply_guided_rule_case(field_states, BEM_GUIDED_RULES["BEM.Backend"], backend)

    mesh_source_mode = str(current.get("BEM.MeshSourceMode", "latest_ath_output")).strip().lower() or "latest_ath_output"
    _apply_guided_rule_case(field_states, BEM_GUIDED_RULES["BEM.MeshSourceMode"], mesh_source_mode)

    group_mode = str(current.get("BEM.GroupMode", "auto")).strip().lower() or "auto"
    _apply_guided_rule_case(field_states, BEM_GUIDED_RULES["BEM.GroupMode"], group_mode)

    solver_mode = str(current.get("BEM.SolverMode", "exterior_velocity_bc")).strip().lower() or "exterior_velocity_bc"
    _apply_guided_rule_case(field_states, BEM_GUIDED_RULES["BEM.SolverMode"], solver_mode)

    observation_mode = str(current.get("BEM.ObservationMode", "polar_map")).strip().lower() or "polar_map"
    _apply_guided_rule_case(field_states, BEM_GUIDED_RULES["BEM.ObservationMode"], observation_mode)

    sim_type = str((ath_state or {}).get("ABEC.SimType", "")).strip()
    if sim_type and sim_type != "2" and group_mode == "auto":
        state = field_states.setdefault("BEM.AutoGroupStrategy", {"relevant": True, "reason": ""})
        state["reason"] = "Infinite-baffle mode falls back to name-based auto mapping."

    return field_states


def sanitize_bem_state(state: dict[str, object] | None, ath_state: dict[str, object] | None = None) -> dict[str, object]:
    sanitized = normalize_bem_state(state)
    rules = build_bem_guided_field_states(sanitized, ath_state)
    for key, field_state in rules.items():
        if bool(field_state.get("relevant", True)):
            continue
        if key in BEM_SANITIZE_RESET_VALUES:
            sanitized[key] = BEM_SANITIZE_RESET_VALUES[key]
            continue
        spec = BEM_FIELD_SPECS.get(key)
        if spec is not None and spec.kind == "check":
            sanitized[key] = False
        else:
            sanitized[key] = ""

    backend = str(sanitized.get("BEM.Backend", "wsl")).strip().lower() or "wsl"
    sanitized["BEM.Backend"] = backend if backend in {"wsl", "local_python", "conda"} else "wsl"

    mesh_source_mode = str(sanitized.get("BEM.MeshSourceMode", "latest_ath_output")).strip().lower() or "latest_ath_output"
    sanitized["BEM.MeshSourceMode"] = (
        mesh_source_mode if mesh_source_mode in {"latest_ath_output", "manual_mesh_file"} else "latest_ath_output"
    )

    group_mode = str(sanitized.get("BEM.GroupMode", "auto")).strip().lower() or "auto"
    sanitized["BEM.GroupMode"] = group_mode if group_mode in {"auto", "manual"} else "auto"

    solver_mode = str(sanitized.get("BEM.SolverMode", "exterior_velocity_bc")).strip().lower() or "exterior_velocity_bc"
    sanitized["BEM.SolverMode"] = solver_mode if solver_mode in {"exterior_velocity_bc"} else "exterior_velocity_bc"

    observation_mode = str(sanitized.get("BEM.ObservationMode", "polar_map")).strip().lower() or "polar_map"
    sanitized["BEM.ObservationMode"] = (
        observation_mode if observation_mode in {"polar_map", "custom_directivity"} else "polar_map"
    )

    sim_type = str((ath_state or {}).get("ABEC.SimType", "")).strip()
    if group_mode == "auto" and sim_type and sim_type != "2" and str(sanitized.get("BEM.AutoGroupStrategy", "")).strip() == "fixed_current":
        sanitized["BEM.AutoGroupStrategy"] = "name_heuristic"

    if not _state_truthy(sanitized.get("BEM.Enabled", False)):
        sanitized["BEM.Enabled"] = False

    return sanitized


def build_bem_runtime_settings(state: dict[str, object] | None, ath_state: dict[str, object] | None = None) -> dict[str, object]:
    sanitized = sanitize_bem_state(state, ath_state)
    backend = str(sanitized.get("BEM.Backend", "wsl")).strip().lower() or "wsl"
    mesh_source_mode = str(sanitized.get("BEM.MeshSourceMode", "latest_ath_output")).strip().lower() or "latest_ath_output"
    group_mode = str(sanitized.get("BEM.GroupMode", "auto")).strip().lower() or "auto"
    return {
        "enabled": bool(sanitized.get("BEM.Enabled", False)),
        "backend": backend,
        "mesh_source_mode": mesh_source_mode,
        "group_mode": group_mode,
        "requires_ath_mesh_output": bool(sanitized.get("BEM.Enabled", False)) and mesh_source_mode == "latest_ath_output",
        "launch_options": {
            "backend": backend,
            "wsl_venv": str(sanitized.get("BEM.WslVenv", "")).strip() or RUNTIME_LAYOUT.default_wsl_venv,
            "wsl_solver_entry": str(sanitized.get("BEM.WslSolverEntry", "")).strip() or RUNTIME_LAYOUT.default_wsl_solver_entry,
            "local_python_exe": str(sanitized.get("BEM.LocalPythonExe", "")).strip() or sys.executable,
            "conda_exe": str(sanitized.get("BEM.CondaExe", "")).strip() or "conda",
            "conda_env": str(sanitized.get("BEM.CondaEnv", "")).strip() or "bempp",
        },
    }


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


_FIXED_SOURCE_GROUPS = [2]
_FIXED_WALL_GROUPS = [1, 3]
_FIXED_IGNORE_GROUPS = [4]
_FIXED_INTERFACE_GROUPS: list[int] = []


def resolve_group_map_payload(
    state: dict[str, object] | None,
    mesh_info: dict[str, object],
    ath_state: dict[str, object] | None = None,
) -> dict[str, object]:
    merged = sanitize_bem_state(state, ath_state)
    group_mode = str(merged.get("BEM.GroupMode", "auto")).strip().lower() or "auto"
    detected_groups = {int(value) for value in mesh_info.get("detected_groups", [])}

    if group_mode == "manual":
        source_groups = parse_int_list(merged.get("BEM.SourceGroups", ""))
        wall_groups = parse_int_list(merged.get("BEM.WallGroups", ""))
        interface_groups = parse_int_list(merged.get("BEM.InterfaceGroups", ""))
        ignore_groups = parse_int_list(merged.get("BEM.IgnoreGroups", ""))
        if not source_groups:
            raise ValueError("Manual group mode requires at least one source group.")
        missing_groups = sorted(
            group_id
            for group_id in source_groups + wall_groups + interface_groups + ignore_groups
            if group_id not in detected_groups
        )
        if missing_groups:
            raise ValueError(f"Mesh does not contain the configured group IDs: {missing_groups}")
        return {
            "schema": "ath.group_map.v1",
            "mesh_family": mesh_family_key(mesh_info),
            "source_groups": source_groups,
            "wall_groups": wall_groups,
            "interface_groups": interface_groups,
            "ignore_groups": ignore_groups,
            "confidence": "manual",
            "requires_confirmation": False,
            "reasons": ["Manual group mapping from current BEM state."],
        }

    strategy = str(merged.get("BEM.AutoGroupStrategy", "fixed_current")).strip().lower() or "fixed_current"
    sim_type = str((ath_state or {}).get("ABEC.SimType", "")).strip()
    if strategy == "fixed_current" and sim_type and sim_type != "2":
        strategy = "name_heuristic"

    if strategy == "fixed_current":
        required_groups = set(_FIXED_SOURCE_GROUPS + _FIXED_WALL_GROUPS)
        missing_required = sorted(group_id for group_id in required_groups if group_id not in detected_groups)
        if missing_required:
            raise ValueError(
                "Fixed auto mapping requires groups "
                f"{sorted(required_groups)}, but mesh only contains {sorted(detected_groups)}."
            )
        return {
            "schema": "ath.group_map.v1",
            "mesh_family": mesh_family_key(mesh_info),
            "source_groups": list(_FIXED_SOURCE_GROUPS),
            "wall_groups": list(_FIXED_WALL_GROUPS),
            "interface_groups": list(_FIXED_INTERFACE_GROUPS),
            "ignore_groups": [group_id for group_id in _FIXED_IGNORE_GROUPS if group_id in detected_groups],
            "confidence": "manual_fixed",
            "requires_confirmation": False,
            "reasons": ["Fixed mapping by current branch rule: source=2, wall=1,3, ignore=4."],
        }

    suggestion = suggest_group_map(mesh_info)
    payload = suggestion.to_dict()
    payload["reasons"] = list(payload.get("reasons", [])) + ["Auto strategy: name_heuristic"]
    return payload


def apply_group_map_to_bem_state(state: dict[str, object] | None, group_map_payload: dict[str, object]) -> dict[str, object]:
    merged = normalize_bem_state(state)
    merged["BEM.SourceGroups"] = ",".join(str(value) for value in group_map_payload.get("source_groups", []))
    merged["BEM.WallGroups"] = ",".join(str(value) for value in group_map_payload.get("wall_groups", []))
    merged["BEM.InterfaceGroups"] = ",".join(str(value) for value in group_map_payload.get("interface_groups", []))
    merged["BEM.IgnoreGroups"] = ",".join(str(value) for value in group_map_payload.get("ignore_groups", []))
    return merged


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
    angle_range_mode = str(merged.get("BEM.AngleRangeMode", "full_circle")).strip().lower() or "full_circle"
    frequency_spacing = str(merged.get("BEM.FrequencySpacing", "log")).strip().lower() or "log"
    velocity_frequency_weighting = str(merged.get("BEM.VelocityFrequencyWeighting", "none")).strip().lower() or "none"

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
        symmetry_tolerance = float(merged.get("BEM.SymmetryTolerance", 1.0e-6))
        symmetry_x_value = float(merged.get("BEM.SymmetryXValue", 0.0))
        symmetry_y_value = float(merged.get("BEM.SymmetryYValue", 0.0))
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
    if angle_range_mode not in {"full_circle", "half_circle", "quarter_circle"}:
        raise ValueError("Angle range mode must be one of: full_circle, half_circle, quarter_circle.")
    if frequency_spacing not in {"log", "linear"}:
        raise ValueError("Frequency spacing must be one of: log, linear.")
    if velocity_frequency_weighting not in {"none", "inverse_jw"}:
        raise ValueError("Velocity frequency weighting must be one of: none, inverse_jw.")

    symmetry_mode = str(merged.get("BEM.SymmetryMode", "off")).strip().lower() or "off"
    symmetry: dict[str, object] = {
        "enabled": False,
        "planes": [],
        "tolerance": symmetry_tolerance,
        "require_strict_reduced_mesh": bool(merged.get("BEM.SymmetryStrict", True)),
        "debug_full_rebuild": bool(merged.get("BEM.SymmetryDebugFull", False)),
        "mode_label": symmetry_mode,
    }
    if symmetry["tolerance"] <= 0:
        raise ValueError("Symmetry tolerance must be greater than zero.")

    if symmetry_mode == "half_x_even":
        symmetry["enabled"] = True
        symmetry["planes"] = [{"axis": "x", "value": symmetry_x_value, "parity": "even"}]
    elif symmetry_mode == "half_y_even":
        symmetry["enabled"] = True
        symmetry["planes"] = [{"axis": "y", "value": symmetry_y_value, "parity": "even"}]
    elif symmetry_mode == "quarter_xy_even_even":
        symmetry["enabled"] = True
        symmetry["planes"] = [
            {"axis": "x", "value": symmetry_x_value, "parity": "even"},
            {"axis": "y", "value": symmetry_y_value, "parity": "even"},
        ]
    elif symmetry_mode != "off":
        raise ValueError(f"Unsupported symmetry mode: {symmetry_mode}")

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
        "velocity_frequency_weighting": velocity_frequency_weighting,
        "f1": f1,
        "f2": f2,
        "num_freq": num_freq,
        "frequency_spacing": frequency_spacing,
        "rho0": rho0,
        "c0": c0,
        "mic_distance": mic_distance,
        "plane": plane,
        "angle_range_mode": angle_range_mode,
        "theta_count": theta_count,
        "reference_pressure": reference_pressure,
        "export_png": bool(merged["BEM.ExportPng"]),
        "export_boundary_pressure": bool(merged["BEM.ExportBoundaryPressure"]),
        "symmetry": symmetry,
    }
