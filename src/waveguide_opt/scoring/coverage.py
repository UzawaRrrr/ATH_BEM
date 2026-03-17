from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class FrequencyTarget:
    frequency_hz: float
    in_coverage_target_db: float
    out_of_coverage_threshold_db: float
    horizontal_target_beamwidth_deg: float | None = None
    vertical_target_beamwidth_deg: float | None = None
    alpha_f: float | None = None
    beta_f: float | None = None
    gamma_f: float | None = None
    min_efficiency_proxy_db: float | None = None
    min_matching_proxy: float | None = None


@dataclass
class CoverageTarget:
    horizontal_coverage_deg: float = 90.0
    vertical_coverage_deg: float = 90.0
    transition_margin_deg: float = 8.0
    in_coverage_target_db: float = 0.0
    out_of_coverage_threshold_db: float = -12.0
    horizontal_target_beamwidth_deg: float | None = None
    vertical_target_beamwidth_deg: float | None = None
    alpha_frequency_weights: dict[float, float] = field(default_factory=dict)
    beta_frequency_weights: dict[float, float] = field(default_factory=dict)
    gamma_frequency_weights: dict[float, float] = field(default_factory=dict)
    min_efficiency_proxy_db: float | None = None
    min_matching_proxy: float | None = None
    per_frequency: dict[float, FrequencyTarget] = field(default_factory=dict)
    source_path: Path | None = None
    configured: bool = False
    warnings: list[str] = field(default_factory=list)


def _safe_float(raw: Any, default: float | None = None) -> float | None:
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _parse_frequency_map(raw: Any) -> dict[float, float]:
    if not isinstance(raw, dict):
        return {}
    parsed: dict[float, float] = {}
    for key, value in raw.items():
        freq = _safe_float(key)
        weight = _safe_float(value)
        if freq is None or weight is None:
            continue
        parsed[float(freq)] = float(weight)
    return parsed


def _nearest_frequency_value(map_data: dict[float, float], frequency_hz: float, default: float) -> float:
    if not map_data:
        return float(default)
    nearest = min(map_data.keys(), key=lambda candidate: abs(candidate - frequency_hz))
    return float(map_data[nearest])


def _nearest_frequency_target(target: CoverageTarget, frequency_hz: float) -> FrequencyTarget | None:
    if not target.per_frequency:
        return None
    nearest = min(target.per_frequency.keys(), key=lambda candidate: abs(candidate - frequency_hz))
    return target.per_frequency.get(nearest)


def default_coverage_target() -> CoverageTarget:
    return CoverageTarget()


def _parse_frequency_entry(raw: dict[str, Any], base: CoverageTarget) -> FrequencyTarget | None:
    frequency_hz = _safe_float(raw.get("frequency_hz"))
    if frequency_hz is None:
        return None
    return FrequencyTarget(
        frequency_hz=float(frequency_hz),
        in_coverage_target_db=float(_safe_float(raw.get("in_coverage_target_db"), base.in_coverage_target_db)),
        out_of_coverage_threshold_db=float(
            _safe_float(
                raw.get("out_of_coverage_threshold_db", raw.get("spill_threshold_db")),
                base.out_of_coverage_threshold_db,
            )
        ),
        horizontal_target_beamwidth_deg=_safe_float(raw.get("horizontal_target_beamwidth_deg", raw.get("bw_h_target_deg"))),
        vertical_target_beamwidth_deg=_safe_float(raw.get("vertical_target_beamwidth_deg", raw.get("bw_v_target_deg"))),
        alpha_f=_safe_float(raw.get("alpha_f")),
        beta_f=_safe_float(raw.get("beta_f")),
        gamma_f=_safe_float(raw.get("gamma_f")),
        min_efficiency_proxy_db=_safe_float(raw.get("min_efficiency_proxy_db")),
        min_matching_proxy=_safe_float(raw.get("min_matching_proxy")),
    )


def _load_yaml_target(path: Path) -> CoverageTarget:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Coverage target YAML must contain a mapping: {path}")

    target = CoverageTarget(
        horizontal_coverage_deg=float(_safe_float(data.get("horizontal_coverage_deg"), 90.0)),
        vertical_coverage_deg=float(_safe_float(data.get("vertical_coverage_deg"), 90.0)),
        transition_margin_deg=float(_safe_float(data.get("transition_margin_deg"), 8.0)),
        in_coverage_target_db=float(_safe_float(data.get("in_coverage_target_db"), 0.0)),
        out_of_coverage_threshold_db=float(_safe_float(data.get("out_of_coverage_threshold_db"), -12.0)),
        horizontal_target_beamwidth_deg=_safe_float(data.get("horizontal_target_beamwidth_deg")),
        vertical_target_beamwidth_deg=_safe_float(data.get("vertical_target_beamwidth_deg")),
        alpha_frequency_weights=_parse_frequency_map(
            data.get("alpha_frequency_weights") or data.get("frequency_weights")
        ),
        beta_frequency_weights=_parse_frequency_map(
            data.get("beta_frequency_weights") or data.get("frequency_weights")
        ),
        gamma_frequency_weights=_parse_frequency_map(
            data.get("gamma_frequency_weights") or data.get("frequency_weights")
        ),
        min_efficiency_proxy_db=_safe_float(data.get("min_efficiency_proxy_db")),
        min_matching_proxy=_safe_float(data.get("min_matching_proxy")),
        source_path=path,
        configured=True,
    )

    raw_profiles = data.get("per_frequency", {})
    if isinstance(raw_profiles, list):
        for item in raw_profiles:
            if not isinstance(item, dict):
                continue
            entry = _parse_frequency_entry(item, target)
            if entry is None:
                continue
            target.per_frequency[entry.frequency_hz] = entry
    elif isinstance(raw_profiles, dict):
        for key, item in raw_profiles.items():
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched.setdefault("frequency_hz", key)
            entry = _parse_frequency_entry(enriched, target)
            if entry is None:
                continue
            target.per_frequency[entry.frequency_hz] = entry

    return target


def _load_csv_target(path: Path) -> CoverageTarget:
    target = CoverageTarget(source_path=path, configured=True)
    with path.open("r", newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            entry = _parse_frequency_entry(
                {
                    "frequency_hz": row.get("frequency_hz"),
                    "in_coverage_target_db": row.get("in_coverage_target_db", row.get("target_db")),
                    "out_of_coverage_threshold_db": row.get(
                        "out_of_coverage_threshold_db",
                        row.get("outside_target_db", row.get("spill_threshold_db")),
                    ),
                    "horizontal_target_beamwidth_deg": row.get("horizontal_target_beamwidth_deg", row.get("bw_h_target_deg")),
                    "vertical_target_beamwidth_deg": row.get("vertical_target_beamwidth_deg", row.get("bw_v_target_deg")),
                    "alpha_f": row.get("alpha_f"),
                    "beta_f": row.get("beta_f"),
                    "gamma_f": row.get("gamma_f"),
                    "min_efficiency_proxy_db": row.get("min_efficiency_proxy_db"),
                    "min_matching_proxy": row.get("min_matching_proxy"),
                },
                target,
            )
            if entry is None:
                continue
            target.per_frequency[entry.frequency_hz] = entry
    return target


def load_coverage_target(path_token: str | Path | None) -> CoverageTarget:
    if not path_token:
        return default_coverage_target()
    path = Path(path_token)
    if not path.exists():
        return CoverageTarget(source_path=path, warnings=[f"Coverage target file not found: {path}"])
    if path.suffix.lower() in {".yaml", ".yml"}:
        return _load_yaml_target(path)
    if path.suffix.lower() == ".csv":
        return _load_csv_target(path)
    return CoverageTarget(
        source_path=path,
        warnings=[f"Unsupported coverage target format '{path.suffix}', using defaults."],
    )


def resolve_frequency_target(
    target: CoverageTarget,
    frequency_hz: float,
    default_target_db: float,
    default_outside_db: float,
    default_bw_h_deg: float | None,
    default_bw_v_deg: float | None,
    runtime_alpha: dict[float, float] | None,
    runtime_beta: dict[float, float] | None,
    runtime_gamma: dict[float, float] | None,
    runtime_min_efficiency_proxy_db: float | None,
    runtime_min_matching_proxy: float | None,
) -> FrequencyTarget:
    nearest = _nearest_frequency_target(target, frequency_hz)

    alpha_map = dict(runtime_alpha or {})
    beta_map = dict(runtime_beta or {})
    gamma_map = dict(runtime_gamma or {})
    alpha_map.update(target.alpha_frequency_weights)
    beta_map.update(target.beta_frequency_weights)
    gamma_map.update(target.gamma_frequency_weights)

    resolved = FrequencyTarget(
        frequency_hz=frequency_hz,
        in_coverage_target_db=default_target_db,
        out_of_coverage_threshold_db=default_outside_db,
        horizontal_target_beamwidth_deg=default_bw_h_deg,
        vertical_target_beamwidth_deg=default_bw_v_deg,
        alpha_f=_nearest_frequency_value(alpha_map, frequency_hz, 1.0),
        beta_f=_nearest_frequency_value(beta_map, frequency_hz, 1.0),
        gamma_f=_nearest_frequency_value(gamma_map, frequency_hz, 1.0),
        min_efficiency_proxy_db=runtime_min_efficiency_proxy_db,
        min_matching_proxy=runtime_min_matching_proxy,
    )

    if target.configured:
        resolved.in_coverage_target_db = target.in_coverage_target_db
        resolved.out_of_coverage_threshold_db = target.out_of_coverage_threshold_db
        if target.horizontal_target_beamwidth_deg is not None:
            resolved.horizontal_target_beamwidth_deg = target.horizontal_target_beamwidth_deg
        if target.vertical_target_beamwidth_deg is not None:
            resolved.vertical_target_beamwidth_deg = target.vertical_target_beamwidth_deg
        if target.min_efficiency_proxy_db is not None:
            resolved.min_efficiency_proxy_db = target.min_efficiency_proxy_db
        if target.min_matching_proxy is not None:
            resolved.min_matching_proxy = target.min_matching_proxy

    if nearest is not None:
        resolved.in_coverage_target_db = nearest.in_coverage_target_db
        resolved.out_of_coverage_threshold_db = nearest.out_of_coverage_threshold_db
        if nearest.horizontal_target_beamwidth_deg is not None:
            resolved.horizontal_target_beamwidth_deg = nearest.horizontal_target_beamwidth_deg
        if nearest.vertical_target_beamwidth_deg is not None:
            resolved.vertical_target_beamwidth_deg = nearest.vertical_target_beamwidth_deg
        if nearest.alpha_f is not None:
            resolved.alpha_f = nearest.alpha_f
        if nearest.beta_f is not None:
            resolved.beta_f = nearest.beta_f
        if nearest.gamma_f is not None:
            resolved.gamma_f = nearest.gamma_f
        if nearest.min_efficiency_proxy_db is not None:
            resolved.min_efficiency_proxy_db = nearest.min_efficiency_proxy_db
        if nearest.min_matching_proxy is not None:
            resolved.min_matching_proxy = nearest.min_matching_proxy

    return resolved


def elliptical_coverage_limit_deg(phi_rad: float, target: CoverageTarget) -> float:
    h_half = max(target.horizontal_coverage_deg * 0.5, 1.0)
    v_half = max(target.vertical_coverage_deg * 0.5, 1.0)
    denom = (math.cos(phi_rad) ** 2) / (h_half**2) + (math.sin(phi_rad) ** 2) / (v_half**2)
    if denom <= 0.0:
        return min(h_half, v_half)
    return 1.0 / math.sqrt(denom)


def classify_coverage(
    theta_rad: float,
    phi_rad: float,
    target: CoverageTarget,
    inside_override: float | None,
) -> tuple[bool, float]:
    theta_deg = math.degrees(theta_rad)
    limit_deg = elliptical_coverage_limit_deg(phi_rad, target)
    boundary_distance_deg = abs(theta_deg - limit_deg)
    if inside_override is not None:
        return inside_override > 0.5, boundary_distance_deg
    return theta_deg <= limit_deg, boundary_distance_deg
