"""Objective evaluation and Optuna integration for ATH/BEM runs."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .case_result import CaseResult
from .result_bridge import case_result_to_score_inputs
from .score_components import (
    aggregate_score,
    angular_roughness_penalty,
    beamwidth_tracking_error,
    catastrophic_penalty,
    constant_directivity_error,
    coverage_error_from_target,
    di_smoothness_error,
    edge_kink_penalty,
    geometry_penalty,
    hom_proxy_error,
    listening_window_smoothness_error,
    load_proxy_error,
    monotonicity_penalty,
    normalize_component_value,
    normalize_offaxis,
    onaxis_ripple_error,
    room_response_error,
    select_freq_mask,
    sound_power_smoothness_error,
    spectral_roughness_penalty,
)
from .score_defaults import build_default_objective_config
from .score_types import GeometryStatus, ObjectiveConfig, PolarData, ScoreBundle


LOGGER = logging.getLogger(__name__)


def _push_warning(warnings: list[str], message: str) -> None:
    if message in warnings:
        return
    warnings.append(message)
    LOGGER.warning(message)


def _mapping_from_bundle(result_bundle: Any) -> dict[str, Any]:
    if isinstance(result_bundle, dict):
        return dict(result_bundle)
    if is_dataclass(result_bundle) and not isinstance(result_bundle, (PolarData, GeometryStatus, ScoreBundle)):
        return {
            field_name: getattr(result_bundle, field_name)
            for field_name in getattr(result_bundle, "__dataclass_fields__", {})
        }
    if hasattr(result_bundle, "__dict__"):
        return dict(vars(result_bundle))
    raise TypeError(f"Unsupported result bundle type: {type(result_bundle)!r}")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_polar_csv(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                {
                    "freq_hz": float(row["freq_hz"]),
                    "angle_deg": float(row["angle_deg"]),
                    "spl_db": float(row["spl_db"]),
                }
            )
    return rows


def _polar_rows_to_matrix(rows: list[dict[str, float]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not rows:
        raise ValueError("polar_rows is empty.")
    freq_values = sorted({float(row["freq_hz"]) for row in rows if np.isfinite(float(row["freq_hz"]))})
    angle_values = sorted({float(row["angle_deg"]) for row in rows if np.isfinite(float(row["angle_deg"]))})
    if not freq_values or not angle_values:
        raise ValueError("polar_rows does not contain any valid frequencies or angles.")

    freq_index = {value: index for index, value in enumerate(freq_values)}
    angle_index = {value: index for index, value in enumerate(angle_values)}
    sums = np.zeros((len(angle_values), len(freq_values)), dtype=float)
    counts = np.zeros_like(sums)
    for row in rows:
        try:
            freq = float(row["freq_hz"])
            angle = float(row["angle_deg"])
            value = float(row["spl_db"])
        except Exception:
            continue
        if not (np.isfinite(freq) and np.isfinite(angle) and np.isfinite(value)):
            continue
        sums[angle_index[angle], freq_index[freq]] += value
        counts[angle_index[angle], freq_index[freq]] += 1.0

    if not np.any(counts > 0.0):
        raise ValueError("polar_rows does not contain any usable SPL samples.")

    filled = np.divide(
        sums,
        np.maximum(counts, 1.0),
        out=np.full_like(sums, np.nan),
        where=counts > 0.0,
    )
    onaxis_index = int(np.argmin(np.abs(np.asarray(angle_values, dtype=float))))
    onaxis_curve = filled[onaxis_index, :]
    finite = np.isfinite(filled)
    global_fallback = float(np.nanmedian(filled[finite])) if np.any(finite) else 0.0
    for row_index in range(filled.shape[0]):
        missing = ~np.isfinite(filled[row_index, :])
        if np.any(missing):
            replacement = np.where(np.isfinite(onaxis_curve), onaxis_curve, global_fallback)
            filled[row_index, missing] = replacement[missing]

    return (
        np.asarray(freq_values, dtype=float),
        np.asarray(angle_values, dtype=float),
        np.asarray(filled, dtype=float),
    )


def _extract_result_dir(payload: dict[str, Any]) -> Path | None:
    candidates: list[Any] = []
    if "result_dir" in payload:
        candidates.append(payload.get("result_dir"))
    workspace_paths = payload.get("workspace_paths")
    if isinstance(workspace_paths, dict):
        candidates.append(workspace_paths.get("bempp"))
    for candidate in candidates:
        if candidate is None:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    return None


def _augment_payload_from_result_dir(payload: dict[str, Any]) -> dict[str, Any]:
    result_dir = _extract_result_dir(payload)
    if result_dir is None:
        return payload
    enriched = dict(payload)
    if "summary" not in enriched:
        summary_path = result_dir / "summary.json"
        if summary_path.exists():
            enriched["summary"] = _read_json(summary_path)
    if "mesh_info" not in enriched:
        mesh_info_path = result_dir / "mesh_info.json"
        if mesh_info_path.exists():
            enriched["mesh_info"] = _read_json(mesh_info_path)
    if "job" not in enriched:
        job_path = result_dir / "job.json"
        if job_path.exists():
            enriched["job"] = _read_json(job_path)
    if "polar_rows" not in enriched:
        polar_path = result_dir / "polar.csv"
        if polar_path.exists():
            enriched["polar_rows"] = _read_polar_csv(polar_path)
    return enriched


def _infer_plane_label(payload: dict[str, Any]) -> str:
    for source in (payload, payload.get("summary"), payload.get("job")):
        if isinstance(source, dict) and source.get("plane") is not None:
            label = str(source.get("plane")).strip().upper()
            if label == "YZ":
                return "v"
            if label == "XZ":
                return "h"
    return "h"


def _make_placeholder_polar() -> PolarData:
    return PolarData(
        freqs_hz=np.asarray([1000.0], dtype=float),
        angles_deg_h=np.asarray([0.0], dtype=float),
        angles_deg_v=np.empty(0, dtype=float),
        spl_h_db=np.asarray([[0.0]], dtype=float),
        spl_v_db=np.empty((0, 1), dtype=float),
        onaxis_db=np.asarray([0.0], dtype=float),
    )


def _extract_geometry_status(payload: dict[str, Any]) -> GeometryStatus:
    geom = payload.get("geom") or payload.get("geometry_status")
    if isinstance(geom, GeometryStatus):
        return geom

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    mesh_info = payload.get("mesh_info") if isinstance(payload.get("mesh_info"), dict) else {}

    solver_ok = bool(payload["solver_ok"]) if "solver_ok" in payload else str(summary.get("status", "done")).lower() == "done"
    mesh_ok = bool(payload["mesh_ok"]) if "mesh_ok" in payload else bool(summary.get("mesh_file") or mesh_info)
    geometry_ok = bool(payload["geometry_ok"]) if "geometry_ok" in payload else mesh_ok
    self_intersection = bool(payload["self_intersection"]) if "self_intersection" in payload else False
    mesh_quality_ok = (
        bool(payload["mesh_quality_ok"])
        if "mesh_quality_ok" in payload
        else int(mesh_info.get("nonmanifold_edge_count", 0)) == 0
    )

    notes: list[str] = []
    notes.extend(str(item) for item in summary.get("warnings", []) if str(item).strip())
    notes.extend(str(item) for item in summary.get("notes", []) if str(item).strip())
    notes.extend(str(item) for item in payload.get("notes", []) if str(item).strip())
    return GeometryStatus(
        mesh_ok=mesh_ok,
        solver_ok=solver_ok,
        geometry_ok=geometry_ok,
        self_intersection=self_intersection,
        mesh_quality_ok=mesh_quality_ok,
        notes=notes,
    )


def _load_generic_plane(payload: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if payload.get("frequencies_hz") is not None and payload.get("angles_deg") is not None and payload.get("spl_db") is not None:
        freqs = np.asarray(payload["frequencies_hz"], dtype=float).reshape(-1)
        angles = np.asarray(payload["angles_deg"], dtype=float).reshape(-1)
        spl = np.asarray(payload["spl_db"], dtype=float)
        if spl.ndim != 2:
            raise ValueError(f"spl_db must be 2D, got shape {spl.shape}.")
        if spl.shape == (freqs.size, angles.size):
            spl = spl.T
        elif spl.shape != (angles.size, freqs.size):
            raise ValueError(
                f"spl_db must have shape ({angles.size}, {freqs.size}) or ({freqs.size}, {angles.size}), got {spl.shape}."
            )
        return freqs, angles, spl

    if payload.get("freqs_hz") is not None and payload.get("angles_deg") is not None and payload.get("spl_db") is not None:
        freqs = np.asarray(payload["freqs_hz"], dtype=float).reshape(-1)
        angles = np.asarray(payload["angles_deg"], dtype=float).reshape(-1)
        spl = np.asarray(payload["spl_db"], dtype=float)
        if spl.shape == (freqs.size, angles.size):
            spl = spl.T
        return freqs, angles, spl

    if payload.get("polar_rows") is not None:
        return _polar_rows_to_matrix(list(payload["polar_rows"]))

    result_dir = _extract_result_dir(payload)
    if result_dir is None:
        raise ValueError("No generic plane data was found in the result bundle.")

    solution_path = result_dir / "solution.npz"
    if solution_path.exists():
        with np.load(solution_path) as solution:
            freqs = np.asarray(solution["frequencies_hz"], dtype=float).reshape(-1)
            angles = np.asarray(solution["angles_deg"], dtype=float).reshape(-1)
            spl = np.asarray(solution["spl_db"], dtype=float)
        if spl.shape == (freqs.size, angles.size):
            spl = spl.T
        elif spl.shape != (angles.size, freqs.size):
            raise ValueError(f"solution.npz spl_db has unexpected shape {spl.shape}.")
        return freqs, angles, spl

    polar_csv_path = result_dir / "polar.csv"
    if polar_csv_path.exists():
        return _polar_rows_to_matrix(_read_polar_csv(polar_csv_path))

    raise ValueError(f"No polar data could be loaded from {result_dir}.")


def _extract_polar_data(payload: dict[str, Any]) -> PolarData:
    polar = payload.get("polar") or payload.get("polar_data")
    if isinstance(polar, PolarData):
        return polar

    direct_freqs = payload.get("freqs_hz", payload.get("frequencies_hz"))
    if direct_freqs is not None and (payload.get("spl_h_db") is not None or payload.get("spl_v_db") is not None):
        freqs = np.asarray(direct_freqs, dtype=float).reshape(-1)
        extras = dict(payload.get("extras", {}))
        for key in ("throat_reflection", "radiation_efficiency"):
            if payload.get(key) is not None:
                extras[key] = payload[key]
        return PolarData(
            freqs_hz=freqs,
            angles_deg_h=np.asarray(payload.get("angles_deg_h", []), dtype=float).reshape(-1),
            angles_deg_v=np.asarray(payload.get("angles_deg_v", []), dtype=float).reshape(-1),
            spl_h_db=np.asarray(payload.get("spl_h_db", np.empty((0, freqs.size))), dtype=float),
            spl_v_db=np.asarray(payload.get("spl_v_db", np.empty((0, freqs.size))), dtype=float),
            onaxis_db=payload.get("onaxis_db"),
            di_db=payload.get("di_db"),
            sound_power_db=payload.get("sound_power_db"),
            listening_window_db=payload.get("listening_window_db"),
            beamwidth_6_h_deg=payload.get("beamwidth_6_h_deg"),
            beamwidth_6_v_deg=payload.get("beamwidth_6_v_deg"),
            beamwidth_12_h_deg=payload.get("beamwidth_12_h_deg"),
            beamwidth_12_v_deg=payload.get("beamwidth_12_v_deg"),
            extras=extras,
        )

    freqs, angles, spl = _load_generic_plane(payload)
    plane_label = _infer_plane_label(payload)
    angles_h = angles if plane_label == "h" else np.empty(0, dtype=float)
    angles_v = angles if plane_label == "v" else np.empty(0, dtype=float)
    spl_h = spl if plane_label == "h" else np.empty((0, freqs.size), dtype=float)
    spl_v = spl if plane_label == "v" else np.empty((0, freqs.size), dtype=float)

    extras = dict(payload.get("extras", {}))
    for key in ("throat_reflection", "radiation_efficiency"):
        if payload.get(key) is not None:
            extras[key] = payload[key]

    return PolarData(
        freqs_hz=freqs,
        angles_deg_h=angles_h,
        angles_deg_v=angles_v,
        spl_h_db=spl_h,
        spl_v_db=spl_v,
        onaxis_db=payload.get("onaxis_db"),
        di_db=payload.get("di_db"),
        sound_power_db=payload.get("sound_power_db"),
        listening_window_db=payload.get("listening_window_db"),
        beamwidth_6_h_deg=payload.get("beamwidth_6_h_deg"),
        beamwidth_6_v_deg=payload.get("beamwidth_6_v_deg"),
        beamwidth_12_h_deg=payload.get("beamwidth_12_h_deg"),
        beamwidth_12_v_deg=payload.get("beamwidth_12_v_deg"),
        extras=extras,
    )


def _interpolate_crossing(angle_a: float, value_a: float, angle_b: float, value_b: float, threshold_db: float) -> float:
    if not (np.isfinite(angle_a) and np.isfinite(value_a) and np.isfinite(angle_b) and np.isfinite(value_b)):
        return abs(float(angle_a))
    if abs(value_b - value_a) <= np.finfo(float).eps:
        return abs(float(angle_b))
    t = (float(threshold_db) - float(value_a)) / (float(value_b) - float(value_a))
    t = float(np.clip(t, 0.0, 1.0))
    return abs(float(angle_a) + t * (float(angle_b) - float(angle_a)))


def _estimate_edge_extent(
    angles_deg: np.ndarray,
    curve_db: np.ndarray,
    zero_index: int,
    *,
    threshold_db: float,
    direction: str,
) -> float:
    indices = range(zero_index - 1, -1, -1) if direction == "left" else range(zero_index + 1, len(angles_deg))
    previous_index = zero_index
    if not np.isfinite(curve_db[zero_index]) or curve_db[zero_index] < threshold_db:
        return 0.0
    last_finite_index = zero_index
    for index in indices:
        if not np.isfinite(curve_db[index]):
            continue
        last_finite_index = index
        if curve_db[index] >= threshold_db:
            previous_index = index
            continue
        return _interpolate_crossing(
            angles_deg[previous_index],
            curve_db[previous_index],
            angles_deg[index],
            curve_db[index],
            threshold_db,
        )
    return abs(float(angles_deg[last_finite_index]))


def _estimate_beamwidth_curve(
    norm_spl_db: np.ndarray | None,
    angles_deg: np.ndarray,
    *,
    threshold_db: float = -6.0,
) -> np.ndarray | None:
    if norm_spl_db is None:
        return None
    angles = np.asarray(angles_deg, dtype=float).reshape(-1)
    matrix = np.asarray(norm_spl_db, dtype=float)
    if angles.size == 0 or matrix.size == 0:
        return None
    if matrix.shape[0] != angles.size:
        raise ValueError(f"norm_spl_db shape {matrix.shape} does not match angles length {angles.size}.")
    order = np.argsort(angles)
    angles = angles[order]
    matrix = matrix[order, :]
    zero_index = int(np.argmin(np.abs(angles)))
    one_sided = (not np.any(angles < 0.0)) or (not np.any(angles > 0.0))
    output = np.full(matrix.shape[1], np.nan, dtype=float)
    for freq_index in range(matrix.shape[1]):
        curve = matrix[:, freq_index]
        left = _estimate_edge_extent(angles, curve, zero_index, threshold_db=threshold_db, direction="left")
        right = _estimate_edge_extent(angles, curve, zero_index, threshold_db=threshold_db, direction="right")
        if np.isfinite(left) and np.isfinite(right):
            output[freq_index] = left + right
        elif np.isfinite(left) and one_sided:
            output[freq_index] = 2.0 * left
        elif np.isfinite(right) and one_sided:
            output[freq_index] = 2.0 * right
        elif np.isfinite(left):
            output[freq_index] = left
        elif np.isfinite(right):
            output[freq_index] = right
    return output


def _average_available(values: list[np.ndarray | None]) -> np.ndarray | None:
    arrays = [np.asarray(value, dtype=float).reshape(-1) for value in values if value is not None]
    if not arrays:
        return None
    return np.nanmean(np.vstack(arrays), axis=0)


def _nearest_target_average(spl_db: np.ndarray, angles_deg: np.ndarray, targets_deg: tuple[float, ...]) -> np.ndarray:
    angles = np.asarray(angles_deg, dtype=float).reshape(-1)
    matrix = np.asarray(spl_db, dtype=float)
    if angles.size == 0 or matrix.size == 0:
        raise ValueError("Cannot estimate listening window from an empty plane.")
    indices: list[int] = []
    for target_deg in targets_deg:
        index = int(np.argmin(np.abs(angles - float(target_deg))))
        if index not in indices:
            indices.append(index)
    return np.mean(matrix[indices, :], axis=0)


def _estimate_listening_window_curve(
    polar: PolarData,
    config: ObjectiveConfig,
    warnings: list[str],
    flags: dict[str, bool | int | float],
) -> np.ndarray | None:
    if polar.listening_window_db is not None:
        flags["listening_window_provided"] = True
        return np.asarray(polar.listening_window_db, dtype=float)

    curves: list[np.ndarray] = []
    if polar.has_horizontal:
        curves.append(_nearest_target_average(polar.spl_h_db, polar.angles_deg_h, config.listening_window_angles_deg))
    if polar.has_vertical:
        curves.append(_nearest_target_average(polar.spl_v_db, polar.angles_deg_v, config.listening_window_angles_deg))
    if curves:
        flags["listening_window_proxy"] = True
        return np.mean(np.vstack(curves), axis=0)

    flags["listening_window_missing"] = True
    _push_warning(warnings, "listening_window_db is unavailable and could not be approximated from polar data.")
    return None


def _plane_sound_power_proxy(spl_db: np.ndarray, angles_deg: np.ndarray) -> np.ndarray:
    angles = np.asarray(angles_deg, dtype=float).reshape(-1)
    matrix = np.asarray(spl_db, dtype=float)
    theta_rad = np.deg2rad(np.abs(angles))
    weights = np.sin(theta_rad)
    if not np.any(weights > 0.0):
        weights = np.ones_like(theta_rad)
    linear_power = np.power(10.0, matrix / 10.0)
    mean_linear = np.average(linear_power, axis=0, weights=weights)
    return 10.0 * np.log10(np.maximum(mean_linear, np.finfo(float).tiny))


def _estimate_sound_power_curve(
    polar: PolarData,
    warnings: list[str],
    flags: dict[str, bool | int | float],
) -> np.ndarray | None:
    if polar.sound_power_db is not None:
        flags["sound_power_provided"] = True
        return np.asarray(polar.sound_power_db, dtype=float)

    curves: list[np.ndarray] = []
    if polar.has_horizontal:
        curves.append(_plane_sound_power_proxy(polar.spl_h_db, polar.angles_deg_h))
    if polar.has_vertical:
        curves.append(_plane_sound_power_proxy(polar.spl_v_db, polar.angles_deg_v))
    if curves:
        flags["sound_power_proxy"] = True
        return np.mean(np.vstack(curves), axis=0)

    flags["sound_power_missing"] = True
    _push_warning(warnings, "sound_power_db is unavailable and no polar proxy could be constructed.")
    return None


def _estimate_di_curve(
    polar: PolarData,
    beamwidth_h_deg: np.ndarray | None,
    beamwidth_v_deg: np.ndarray | None,
    warnings: list[str],
    flags: dict[str, bool | int | float],
) -> np.ndarray | None:
    if polar.di_db is not None:
        flags["di_provided"] = True
        return np.asarray(polar.di_db, dtype=float)
    if beamwidth_h_deg is None and beamwidth_v_deg is None:
        flags["di_missing"] = True
        _push_warning(warnings, "di_db is unavailable and beamwidth-based DI proxy could not be constructed.")
        return None

    bw_h = np.asarray(beamwidth_h_deg if beamwidth_h_deg is not None else beamwidth_v_deg, dtype=float)
    bw_v = np.asarray(beamwidth_v_deg if beamwidth_v_deg is not None else beamwidth_h_deg, dtype=float)
    safe_bw_h = np.maximum(np.abs(bw_h), 1.0)
    safe_bw_v = np.maximum(np.abs(bw_v), 1.0)
    flags["di_proxy"] = True
    return 10.0 * np.log10(np.maximum((360.0 * 180.0) / (safe_bw_h * safe_bw_v), np.finfo(float).tiny))


def _metric_with_fallback(
    label: str,
    warnings: list[str],
    func: Callable[[], float],
    *,
    fallback: float = 0.0,
) -> float:
    try:
        value = float(func())
    except Exception as exc:
        _push_warning(warnings, f"{label} failed; using fallback {fallback:.3f}. Reason: {exc}")
        return float(fallback)
    if not np.isfinite(value):
        _push_warning(warnings, f"{label} produced a non-finite value; using fallback {fallback:.3f}.")
        return float(fallback)
    return value


def evaluate_objective(
    polar: PolarData,
    geom: GeometryStatus,
    config: ObjectiveConfig,
) -> ScoreBundle:
    """Evaluate the scalar objective and all component scores for a parsed result."""
    warnings: list[str] = []
    flags: dict[str, bool | int | float] = {
        "solver_ok": geom.solver_ok,
        "mesh_ok": geom.mesh_ok,
        "geometry_ok": geom.geometry_ok,
        "self_intersection": geom.self_intersection,
        "mesh_quality_ok": geom.mesh_quality_ok,
        "has_horizontal": polar.has_horizontal,
        "has_vertical": polar.has_vertical,
    }
    details: dict[str, float] = {}

    freqs_hz = np.asarray(polar.freqs_hz, dtype=float).reshape(-1)
    cov_mask = select_freq_mask(freqs_hz, config.freq_band_cov_hz)
    room_mask = select_freq_mask(freqs_hz, config.freq_band_room_hz)
    load_mask = select_freq_mask(freqs_hz, config.freq_band_load_hz)
    flags["coverage_band_empty"] = not np.any(cov_mask)
    flags["room_band_empty"] = not np.any(room_mask)
    flags["load_band_empty"] = not np.any(load_mask)

    hard_raw = catastrophic_penalty(geom, config.catastrophic_score)
    hard_norm = normalize_component_value(hard_raw, config.component_normalizers.get("hard_penalty", 1.0))
    details["hard.raw"] = hard_raw

    if hard_raw >= config.catastrophic_score:
        flags["catastrophic"] = True
        flags["any_missing"] = True
        return aggregate_score(
            components={
                "hard": hard_norm,
                "coverage": 0.0,
                "cd": 0.0,
                "hom": 0.0,
                "room": 0.0,
                "di": 0.0,
                "load": 0.0,
                "geom": 0.0,
            },
            config=config,
            details=details,
            flags=flags,
            warnings=warnings,
        )

    onaxis_db = np.asarray(polar.onaxis_db, dtype=float).reshape(-1)
    norm_h = normalize_offaxis(polar.spl_h_db, polar.angles_deg_h, onaxis_db=onaxis_db) if polar.has_horizontal else None
    norm_v = normalize_offaxis(polar.spl_v_db, polar.angles_deg_v, onaxis_db=onaxis_db) if polar.has_vertical else None

    beamwidth_6_h = (
        np.asarray(polar.beamwidth_6_h_deg, dtype=float).reshape(-1)
        if polar.beamwidth_6_h_deg is not None
        else _estimate_beamwidth_curve(norm_h, polar.angles_deg_h, threshold_db=-6.0)
    )
    beamwidth_6_v = (
        np.asarray(polar.beamwidth_6_v_deg, dtype=float).reshape(-1)
        if polar.beamwidth_6_v_deg is not None
        else _estimate_beamwidth_curve(norm_v, polar.angles_deg_v, threshold_db=-6.0)
    )
    if beamwidth_6_h is not None and np.any(np.isfinite(beamwidth_6_h)):
        details["beamwidth_6_h.mean"] = float(np.nanmean(beamwidth_6_h))
    if beamwidth_6_v is not None and np.any(np.isfinite(beamwidth_6_v)):
        details["beamwidth_6_v.mean"] = float(np.nanmean(beamwidth_6_v))

    coverage_terms: list[float] = []
    coverage_raw_terms: list[float] = []
    if polar.has_horizontal:
        if config.target_norm_spl_h_db is not None:
            raw = _metric_with_fallback(
                "coverage_error.horizontal.target",
                warnings,
                lambda: coverage_error_from_target(
                    norm_h,
                    np.asarray(config.target_norm_spl_h_db, dtype=float),
                    cov_mask,
                    np.ones(len(polar.angles_deg_h), dtype=bool),
                ),
            )
            coverage_terms.append(normalize_component_value(raw, config.component_normalizers.get("coverage_target_db", 1.0)))
            coverage_raw_terms.append(raw)
            flags["coverage_h_target"] = True
            details["coverage_h.raw"] = raw
        elif config.target_bw_h_deg is not None and beamwidth_6_h is not None:
            raw = _metric_with_fallback(
                "coverage_error.horizontal.beamwidth",
                warnings,
                lambda: beamwidth_tracking_error(beamwidth_6_h, config.target_bw_h_deg, cov_mask),
            )
            coverage_terms.append(normalize_component_value(raw, config.component_normalizers.get("coverage_beamwidth_deg", 1.0)))
            coverage_raw_terms.append(raw)
            flags["coverage_h_beamwidth"] = True
            details["coverage_h.raw"] = raw
        else:
            flags["coverage_h_missing"] = True
    else:
        flags["coverage_h_missing"] = True

    if polar.has_vertical:
        if config.target_norm_spl_v_db is not None:
            raw = _metric_with_fallback(
                "coverage_error.vertical.target",
                warnings,
                lambda: coverage_error_from_target(
                    norm_v,
                    np.asarray(config.target_norm_spl_v_db, dtype=float),
                    cov_mask,
                    np.ones(len(polar.angles_deg_v), dtype=bool),
                ),
            )
            coverage_terms.append(normalize_component_value(raw, config.component_normalizers.get("coverage_target_db", 1.0)))
            coverage_raw_terms.append(raw)
            flags["coverage_v_target"] = True
            details["coverage_v.raw"] = raw
        elif config.target_bw_v_deg is not None and beamwidth_6_v is not None:
            raw = _metric_with_fallback(
                "coverage_error.vertical.beamwidth",
                warnings,
                lambda: beamwidth_tracking_error(beamwidth_6_v, config.target_bw_v_deg, cov_mask),
            )
            coverage_terms.append(normalize_component_value(raw, config.component_normalizers.get("coverage_beamwidth_deg", 1.0)))
            coverage_raw_terms.append(raw)
            flags["coverage_v_beamwidth"] = True
            details["coverage_v.raw"] = raw
        else:
            flags["coverage_v_missing"] = True
    else:
        flags["coverage_v_missing"] = True

    coverage_score = float(np.mean(coverage_terms)) if coverage_terms else 0.0
    details["coverage.raw_mean"] = float(np.mean(coverage_raw_terms)) if coverage_raw_terms else 0.0

    cd_terms: list[float] = []
    if polar.has_horizontal:
        raw = _metric_with_fallback(
            "constant_directivity.horizontal",
            warnings,
            lambda: constant_directivity_error(norm_h, freqs_hz, cov_mask, detrend_kind=config.detrend_kind),
        )
        details["cd_h.raw"] = raw
        cd_terms.append(normalize_component_value(raw, config.component_normalizers.get("cd_db", 1.0)))
    if polar.has_vertical:
        raw = _metric_with_fallback(
            "constant_directivity.vertical",
            warnings,
            lambda: constant_directivity_error(norm_v, freqs_hz, cov_mask, detrend_kind=config.detrend_kind),
        )
        details["cd_v.raw"] = raw
        cd_terms.append(normalize_component_value(raw, config.component_normalizers.get("cd_db", 1.0)))
    cd_score = float(np.mean(cd_terms)) if cd_terms else 0.0
    if not cd_terms:
        flags["cd_missing"] = True

    hom_terms: list[float] = []
    if polar.has_horizontal:
        mono_h = _metric_with_fallback(
            "hom_proxy.horizontal.monotonicity",
            warnings,
            lambda: monotonicity_penalty(
                norm_h,
                polar.angles_deg_h,
                freq_mask=cov_mask,
                epsilon_db=config.monotonicity_epsilon_db,
                compare_mode=config.monotonicity_mode,
            ),
        )
        ang_h = _metric_with_fallback(
            "hom_proxy.horizontal.angular_roughness",
            warnings,
            lambda: angular_roughness_penalty(norm_h, polar.angles_deg_h, freq_mask=cov_mask),
        )
        spec_h = _metric_with_fallback(
            "hom_proxy.horizontal.spectral_roughness",
            warnings,
            lambda: spectral_roughness_penalty(
                norm_h,
                freqs_hz,
                freq_mask=cov_mask,
                use_log_frequency=config.roughness_use_log_frequency,
            ),
        )
        edge_h = _metric_with_fallback(
            "hom_proxy.horizontal.edge_kink",
            warnings,
            lambda: edge_kink_penalty(norm_h, polar.angles_deg_h, config.edge_angle_range_h_deg, freq_mask=cov_mask),
        )
        raw_hom_h = hom_proxy_error(mono_h, ang_h, spec_h, edge_h, inner_weights=config.hom_weights)
        details["hom_h.mono"] = mono_h
        details["hom_h.angular"] = ang_h
        details["hom_h.spectral"] = spec_h
        details["hom_h.edge"] = edge_h
        details["hom_h.raw"] = raw_hom_h
        hom_terms.append(normalize_component_value(raw_hom_h, config.component_normalizers.get("hom_db", 1.0)))
    if polar.has_vertical:
        mono_v = _metric_with_fallback(
            "hom_proxy.vertical.monotonicity",
            warnings,
            lambda: monotonicity_penalty(
                norm_v,
                polar.angles_deg_v,
                freq_mask=cov_mask,
                epsilon_db=config.monotonicity_epsilon_db,
                compare_mode=config.monotonicity_mode,
            ),
        )
        ang_v = _metric_with_fallback(
            "hom_proxy.vertical.angular_roughness",
            warnings,
            lambda: angular_roughness_penalty(norm_v, polar.angles_deg_v, freq_mask=cov_mask),
        )
        spec_v = _metric_with_fallback(
            "hom_proxy.vertical.spectral_roughness",
            warnings,
            lambda: spectral_roughness_penalty(
                norm_v,
                freqs_hz,
                freq_mask=cov_mask,
                use_log_frequency=config.roughness_use_log_frequency,
            ),
        )
        edge_v = _metric_with_fallback(
            "hom_proxy.vertical.edge_kink",
            warnings,
            lambda: edge_kink_penalty(norm_v, polar.angles_deg_v, config.edge_angle_range_v_deg, freq_mask=cov_mask),
        )
        raw_hom_v = hom_proxy_error(mono_v, ang_v, spec_v, edge_v, inner_weights=config.hom_weights)
        details["hom_v.mono"] = mono_v
        details["hom_v.angular"] = ang_v
        details["hom_v.spectral"] = spec_v
        details["hom_v.edge"] = edge_v
        details["hom_v.raw"] = raw_hom_v
        hom_terms.append(normalize_component_value(raw_hom_v, config.component_normalizers.get("hom_db", 1.0)))
    hom_score = float(np.mean(hom_terms)) if hom_terms else 0.0
    if not hom_terms:
        flags["hom_missing"] = True

    listening_window_curve = _estimate_listening_window_curve(polar, config, warnings, flags)
    sound_power_curve = _estimate_sound_power_curve(polar, warnings, flags)

    onaxis_raw = _metric_with_fallback(
        "room_response.onaxis",
        warnings,
        lambda: onaxis_ripple_error(onaxis_db, freqs_hz, room_mask, detrend_kind=config.detrend_kind),
    )
    details["room.onaxis_raw"] = onaxis_raw

    listening_window_raw: float | None = None
    if listening_window_curve is not None:
        listening_window_raw = _metric_with_fallback(
            "room_response.listening_window",
            warnings,
            lambda: listening_window_smoothness_error(
                listening_window_curve,
                freqs_hz,
                room_mask,
                detrend_kind=config.detrend_kind,
            ),
        )
        details["room.listening_window_raw"] = listening_window_raw

    sound_power_raw: float | None = None
    if sound_power_curve is not None:
        sound_power_raw = _metric_with_fallback(
            "room_response.sound_power",
            warnings,
            lambda: sound_power_smoothness_error(
                sound_power_curve,
                freqs_hz,
                room_mask,
                detrend_kind=config.detrend_kind,
            ),
        )
        details["room.sound_power_raw"] = sound_power_raw

    room_raw = room_response_error(onaxis_raw, listening_window_raw, sound_power_raw)
    room_score = normalize_component_value(room_raw, config.component_normalizers.get("room_db", 1.0))
    details["room.raw"] = room_raw

    di_curve = _estimate_di_curve(polar, beamwidth_6_h, beamwidth_6_v, warnings, flags)
    beamwidth_mean = _average_available([beamwidth_6_h, beamwidth_6_v])
    di_raw = _metric_with_fallback(
        "di_response.smoothness",
        warnings,
        lambda: di_smoothness_error(
            di_curve,
            freqs_hz,
            cov_mask,
            beamwidth_deg=beamwidth_mean,
            beamwidth_smoothness_eta=config.beamwidth_smoothness_eta,
        ),
    )
    di_score = normalize_component_value(di_raw, config.component_normalizers.get("di_db", 1.0))
    details["di.raw"] = di_raw

    has_load_proxy = any(key in polar.extras for key in ("throat_reflection", "radiation_efficiency"))
    if not has_load_proxy:
        flags["load_missing"] = True
    load_raw = _metric_with_fallback(
        "load_proxy",
        warnings,
        lambda: load_proxy_error(polar.extras, freqs_hz, load_mask),
    )
    load_score = normalize_component_value(load_raw, config.component_normalizers.get("load_ratio", 1.0))
    details["load.raw"] = load_raw

    geom_raw = geometry_penalty(geom, config.failure_score)
    geom_score = normalize_component_value(
        geom_raw,
        config.component_normalizers.get("geom_penalty", config.failure_score),
    )
    details["geom.raw"] = geom_raw

    components = {
        "hard": hard_norm,
        "coverage": coverage_score,
        "cd": cd_score,
        "hom": hom_score,
        "room": room_score,
        "di": di_score,
        "load": load_score,
        "geom": geom_score,
    }
    flags["catastrophic"] = False
    flags["any_missing"] = any(
        bool(value)
        for key, value in flags.items()
        if any(token in key for token in ("missing", "band_empty"))
    )
    return aggregate_score(
        components=components,
        config=config,
        details=details,
        flags=flags,
        warnings=warnings,
    )


def objective_from_result_bundle(
    result_bundle: dict[str, Any] | Any,
    config: ObjectiveConfig,
) -> ScoreBundle:
    """Convert a case result bundle into scorer inputs and evaluate the objective."""
    if isinstance(result_bundle, ScoreBundle):
        return result_bundle
    if isinstance(result_bundle, tuple) and len(result_bundle) == 2:
        first, second = result_bundle
        if isinstance(first, PolarData) and isinstance(second, GeometryStatus):
            return evaluate_objective(first, second, config)

    if isinstance(result_bundle, PolarData):
        return evaluate_objective(result_bundle, GeometryStatus(mesh_ok=True, solver_ok=True, geometry_ok=True), config)
    if isinstance(result_bundle, CaseResult):
        polar, geom = case_result_to_score_inputs(result_bundle)
        return evaluate_objective(polar, geom, config)

    polar, geom = case_result_to_score_inputs(result_bundle)
    return evaluate_objective(polar, geom, config)


def _set_trial_attr(trial: Any, key: str, value: Any) -> None:
    if not hasattr(trial, "set_user_attr"):
        return
    try:
        trial.set_user_attr(key, value)
    except Exception as exc:
        LOGGER.warning("Failed to set trial user_attr %s: %s", key, exc)


def optuna_objective_wrapper(
    trial: Any,
    case_runner: Any,
    parser_bridge: Callable[[Any], tuple[PolarData, GeometryStatus]] | None = None,
    config: ObjectiveConfig | None = None,
) -> float:
    """Thin Optuna wrapper around a case runner, bridge, and the headless scorer."""
    effective_config = config or build_default_objective_config(stage="final")
    params = dict(getattr(trial, "params", {}) or {})
    runner = case_runner.run if hasattr(case_runner, "run") else case_runner
    raw_result = runner(params)
    bridge = parser_bridge or case_result_to_score_inputs
    polar, geom = bridge(raw_result)
    score_bundle = evaluate_objective(polar, geom, effective_config)

    _set_trial_attr(trial, "score.total", score_bundle.total)
    _set_trial_attr(trial, "score.coverage", score_bundle.coverage_error)
    _set_trial_attr(trial, "score.cd", score_bundle.cd_error)
    _set_trial_attr(trial, "score.hom", score_bundle.hom_error)
    _set_trial_attr(trial, "score.room", score_bundle.room_error)
    _set_trial_attr(trial, "score.di", score_bundle.di_error)
    _set_trial_attr(trial, "score.load", score_bundle.load_error)
    _set_trial_attr(trial, "score.geom", score_bundle.geom_error)
    _set_trial_attr(trial, "score.hard", score_bundle.hard_penalty)
    _set_trial_attr(trial, "flags.any_missing", bool(score_bundle.flags.get("any_missing", False)))
    _set_trial_attr(trial, "flags.catastrophic", bool(score_bundle.flags.get("catastrophic", False)))
    for key, value in score_bundle.details.items():
        _set_trial_attr(trial, f"detail.{key}", value)
    for key, value in score_bundle.flags.items():
        _set_trial_attr(trial, f"flags.{key}", value)
    return float(score_bundle.total)
