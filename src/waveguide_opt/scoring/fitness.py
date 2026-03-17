from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .coverage import (
    classify_coverage,
    elliptical_coverage_limit_deg,
    load_coverage_target,
    resolve_frequency_target,
)
from .io import ObservationPoint, parse_observation_file


@dataclass
class FrequencyScore:
    frequency_hz: float
    alpha_f: float
    beta_f: float
    gamma_f: float
    target_level_db: float
    spill_threshold_db: float
    bw_h_target_deg: float | None
    bw_v_target_deg: float | None
    inside_count: int
    outside_count: int
    inside_mean_db: float
    inside_std_db: float
    outside_mean_db: float
    on_axis_db: float
    bw_h_sim_deg: float | None
    bw_v_sim_deg: float | None
    bw_h_skipped: bool
    bw_v_skipped: bool
    bw_skip_reason: str
    e_in_f: float
    e_out_f: float
    e_bw_f: float
    e_boundary_f: float
    e_sidelobe_f: float
    e_eff_f: float
    eff_proxy_mode: str
    efficiency_proxy_db: float | None
    matching_proxy_mean: float | None
    matching_error_f: float
    energy_concentration: float | None


@dataclass
class ScoreBreakdown:
    fitness: float
    total_cost: float
    total_error: float
    objective: str
    maximize_conversion: str
    J: float
    E_in: float
    E_out: float
    E_bw: float
    E_smooth: float
    E_eff: float
    E_mfg: float
    E_smooth_transition: float
    E_smooth_boundary: float
    E_smooth_sidelobe: float
    w_in: float
    w_out: float
    w_bw: float
    w_smooth: float
    w_eff: float
    w_mfg: float
    inside_count: int
    outside_count: int
    frequency_count: int
    beamwidth_skipped: bool
    beamwidth_skipped_frequencies: list[float]
    skipped_components: list[str]
    warnings: list[str]
    source_observation: str
    coverage_target_source: str
    score_json_path: str | None
    score_csv_path: str | None
    frequency_metrics: list[dict[str, Any]]


def _safe_float(raw: Any, default: float | None = None) -> float | None:
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _mean(values: list[float], default: float = 0.0) -> float:
    return sum(values) / len(values) if values else default


def _variance(values: list[float]) -> float:
    if not values:
        return 0.0
    avg = _mean(values)
    return _mean([(value - avg) ** 2 for value in values])


def _weighted_mean(values: list[tuple[float, float]], default: float = 0.0) -> float:
    weight_sum = sum(max(weight, 0.0) for _, weight in values)
    if weight_sum <= 0.0:
        return default
    return sum(value * max(weight, 0.0) for value, weight in values) / weight_sum


def _angular_distance_deg(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def _estimate_half_beamwidth_deg(theta_spl_pairs: list[tuple[float, float]], db_down: float) -> float | None:
    if not theta_spl_pairs:
        return None
    samples = sorted((theta, spl) for theta, spl in theta_spl_pairs if 0.0 <= theta <= 90.0)
    if len(samples) < 3:
        return None
    axis_theta, axis_spl = min(samples, key=lambda pair: pair[0])
    threshold = axis_spl - db_down
    prev_theta = axis_theta
    prev_spl = axis_spl
    for theta, spl in samples:
        if theta <= axis_theta:
            prev_theta = theta
            prev_spl = spl
            continue
        if spl <= threshold:
            delta = spl - prev_spl
            if abs(delta) < 1e-9:
                return theta
            ratio = (threshold - prev_spl) / delta
            ratio = min(max(ratio, 0.0), 1.0)
            return prev_theta + ratio * (theta - prev_theta)
        prev_theta = theta
        prev_spl = spl
    return None


def _estimate_plane_beamwidth_deg(
    rows: list[dict[str, float]],
    phi_center_deg: float,
    phi_tolerance_deg: float,
    db_down: float,
) -> tuple[float | None, bool, str]:
    plane = [
        (row["theta_deg"], row["spl_db"])
        for row in rows
        if _angular_distance_deg(row["phi_deg"], phi_center_deg) <= phi_tolerance_deg
    ]
    if len(plane) < 4:
        return None, True, "insufficient plane samples"
    half_bw = _estimate_half_beamwidth_deg(plane, db_down=db_down)
    if half_bw is None:
        return None, True, "unable to locate -dB crossing"
    return 2.0 * half_bw, False, ""


def _geometry_manufacturability_penalty(
    geometry_params: dict[str, float] | None,
    geometry_bounds: dict[str, tuple[float, float]] | None,
) -> float:
    if not geometry_params:
        return 0.0
    penalty = 0.0
    bounds = geometry_bounds or {}
    for key, value in geometry_params.items():
        if key not in bounds:
            continue
        low, high = bounds[key]
        span = max(high - low, 1e-9)
        if value < low:
            penalty += ((low - value) / span) ** 2 * 20.0
        elif value > high:
            penalty += ((value - high) / span) ** 2 * 20.0

    length = float(geometry_params.get("length", 0.2))
    throat = float(geometry_params.get("throat_radius", 0.02))
    mouth = float(geometry_params.get("mouth_radius", 0.1))
    flare = float(geometry_params.get("flare", 1.0))

    if mouth <= throat:
        penalty += (throat - mouth + 0.001) * 500.0

    expansion = mouth / max(throat, 1e-6)
    if expansion < 1.5:
        penalty += (1.5 - expansion) ** 2 * 8.0
    if expansion > 14.0:
        penalty += ((expansion - 14.0) / 2.0) ** 2 * 8.0

    slope = (mouth - throat) / max(length, 1e-6)
    if slope < 0.04:
        penalty += (0.04 - slope) ** 2 * 20.0
    if slope > 1.25:
        penalty += (slope - 1.25) ** 2 * 20.0

    if throat < 0.008:
        penalty += ((0.008 - throat) * 100.0) ** 2
    if length < 0.08:
        penalty += ((0.08 - length) * 60.0) ** 2

    penalty += 0.25 * (flare - 1.2) ** 2
    return penalty


def _point_to_row(point: ObservationPoint) -> dict[str, float]:
    return {
        "frequency_hz": point.frequency_hz,
        "theta_deg": math.degrees(point.theta_rad),
        "phi_deg": math.degrees(point.phi_rad),
        "spl_db": point.spl_db,
        "inside_override": point.inside_coverage if point.inside_coverage is not None else math.nan,
        "efficiency_proxy_db": point.efficiency_proxy_db if point.efficiency_proxy_db is not None else math.nan,
        "matching_proxy": point.matching_proxy if point.matching_proxy is not None else math.nan,
        "target_db": point.target_db if point.target_db is not None else math.nan,
    }


def _safe_case_tag(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_") or "score"


def _write_score_artifacts(score: ScoreBreakdown, output_dir: Path, case_tag: str) -> tuple[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    scoring_dir = output_dir / "scoring"
    scoring_dir.mkdir(parents=True, exist_ok=True)

    safe_tag = _safe_case_tag(case_tag)
    json_path = scoring_dir / f"score_{safe_tag}.json"
    json_path.write_text(json.dumps(score.__dict__, indent=2), encoding="utf-8")

    csv_path = scoring_dir / "score_summary.csv"
    fieldnames = [
        "case_tag",
        "total_cost",
        "fitness",
        "E_in",
        "E_out",
        "E_bw",
        "E_smooth",
        "E_eff",
        "E_mfg",
        "inside_count",
        "outside_count",
        "frequency_count",
    ]
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(
            {
                "case_tag": safe_tag,
                "total_cost": score.total_cost,
                "fitness": score.fitness,
                "E_in": score.E_in,
                "E_out": score.E_out,
                "E_bw": score.E_bw,
                "E_smooth": score.E_smooth,
                "E_eff": score.E_eff,
                "E_mfg": score.E_mfg,
                "inside_count": score.inside_count,
                "outside_count": score.outside_count,
                "frequency_count": score.frequency_count,
            }
        )

    return str(json_path), str(csv_path)


def score_observation_file(
    observation_file: Path,
    target_db: float,
    outside_target_db: float,
    spill_weight: float,
    coverage_half_angle_deg: float = 45.0,
    geometry_params: dict[str, float] | None = None,
    geometry_bounds: dict[str, tuple[float, float]] | None = None,
    objective_weights: dict[str, float] | None = None,
    alpha_frequency_weights: dict[float, float] | None = None,
    beta_frequency_weights: dict[float, float] | None = None,
    gamma_frequency_weights: dict[float, float] | None = None,
    beamwidth_db_down: float = 6.0,
    default_bw_h_target_deg: float | None = None,
    default_bw_v_target_deg: float | None = None,
    smooth_boundary_band_deg: float = 8.0,
    side_lobe_margin_db: float = 3.0,
    smooth_transition_weight: float = 0.5,
    smooth_boundary_weight: float = 0.3,
    smooth_sidelobe_weight: float = 0.2,
    min_efficiency_proxy_db: float = -6.0,
    min_matching_proxy: float = 0.45,
    min_energy_concentration: float = 0.65,
    mfg_penalty_scale: float = 1.0,
    coverage_target_path: str = "",
    breakdown_output_dir: Path | None = None,
    breakdown_case_tag: str | None = None,
) -> ScoreBreakdown:
    default_weights = {
        "w_in": 0.40,
        "w_out": 0.30,
        "w_bw": 0.15,
        "w_smooth": 0.05,
        "w_eff": 0.05,
        "w_mfg": 0.05,
    }
    weights = dict(default_weights)
    for key, value in (objective_weights or {}).items():
        if key not in weights:
            continue
        parsed = _safe_float(value)
        if parsed is not None:
            weights[key] = float(parsed)

    coverage_target = load_coverage_target(coverage_target_path)
    warnings = list(coverage_target.warnings)
    skipped_components: list[str] = []

    try:
        observation = parse_observation_file(observation_file)
    except Exception as exc:
        huge = 1e6
        score = ScoreBreakdown(
            fitness=-huge,
            total_cost=huge,
            total_error=huge,
            objective="J = w_in*E_in + w_out*E_out + w_bw*E_bw + w_smooth*E_smooth + w_eff*E_eff + w_mfg*E_mfg",
            maximize_conversion="fitness = -J",
            J=huge,
            E_in=huge,
            E_out=0.0,
            E_bw=0.0,
            E_smooth=0.0,
            E_eff=0.0,
            E_mfg=0.0,
            E_smooth_transition=0.0,
            E_smooth_boundary=0.0,
            E_smooth_sidelobe=0.0,
            w_in=weights["w_in"],
            w_out=weights["w_out"],
            w_bw=weights["w_bw"],
            w_smooth=weights["w_smooth"],
            w_eff=weights["w_eff"],
            w_mfg=weights["w_mfg"],
            inside_count=0,
            outside_count=0,
            frequency_count=0,
            beamwidth_skipped=True,
            beamwidth_skipped_frequencies=[],
            skipped_components=["parser"],
            warnings=[f"Parser error: {exc}"],
            source_observation=str(observation_file),
            coverage_target_source=str(coverage_target.source_path) if coverage_target.source_path else "",
            score_json_path=None,
            score_csv_path=None,
            frequency_metrics=[],
        )
        if breakdown_output_dir:
            score_json, score_csv = _write_score_artifacts(score, breakdown_output_dir, breakdown_case_tag or "parser_error")
            score.score_json_path = score_json
            score.score_csv_path = score_csv
        return score

    warnings.extend(observation.warnings)
    rows_by_frequency: dict[float, list[dict[str, float]]] = defaultdict(list)
    inside_count = 0
    outside_count = 0

    for point in observation.points:
        row = _point_to_row(point)
        inside, boundary_distance_deg = classify_coverage(
            theta_rad=point.theta_rad,
            phi_rad=point.phi_rad,
            target=coverage_target,
            inside_override=point.inside_coverage,
        )
        row["inside_coverage"] = 1.0 if inside else 0.0
        row["boundary_distance_deg"] = boundary_distance_deg
        row["coverage_limit_deg"] = elliptical_coverage_limit_deg(point.phi_rad, coverage_target)
        if inside:
            inside_count += 1
        else:
            outside_count += 1
        rows_by_frequency[row["frequency_hz"]].append(row)

    if not rows_by_frequency:
        warnings.append("No valid observation rows were parsed.")
        skipped_components.append("all")

    bw_h_default = float(
        default_bw_h_target_deg
        if default_bw_h_target_deg is not None
        else coverage_target.horizontal_coverage_deg
        if coverage_target.configured
        else coverage_half_angle_deg * 2.0
    )
    bw_v_default = float(
        default_bw_v_target_deg
        if default_bw_v_target_deg is not None
        else coverage_target.vertical_coverage_deg
        if coverage_target.configured
        else coverage_half_angle_deg * 2.0
    )

    frequency_scores: list[FrequencyScore] = []
    point_cache: dict[float, dict[tuple[int, int], float]] = {}
    beamwidth_skipped_frequencies: list[float] = []

    for frequency_hz in sorted(rows_by_frequency.keys()):
        rows = rows_by_frequency[frequency_hz]
        freq_target = resolve_frequency_target(
            target=coverage_target,
            frequency_hz=frequency_hz,
            default_target_db=target_db,
            default_outside_db=outside_target_db,
            default_bw_h_deg=bw_h_default,
            default_bw_v_deg=bw_v_default,
            runtime_alpha=alpha_frequency_weights,
            runtime_beta=beta_frequency_weights,
            runtime_gamma=gamma_frequency_weights,
            runtime_min_efficiency_proxy_db=min_efficiency_proxy_db,
            runtime_min_matching_proxy=min_matching_proxy,
        )

        inside_rows = [row for row in rows if row["inside_coverage"] > 0.5]
        outside_rows = [row for row in rows if row["inside_coverage"] <= 0.5]
        inside_spl = [row["spl_db"] for row in inside_rows]
        outside_spl = [row["spl_db"] for row in outside_rows]
        on_axis_db = min(rows, key=lambda item: abs(item["theta_deg"]))["spl_db"]
        inside_mean_db = _mean(inside_spl, default=on_axis_db)
        inside_std_db = math.sqrt(_variance(inside_spl))
        outside_mean_db = _mean(outside_spl, default=freq_target.out_of_coverage_threshold_db)

        local_target_db = (
            float(freq_target.in_coverage_target_db)
            if not math.isnan(freq_target.in_coverage_target_db)
            else target_db
        )
        if inside_rows and not math.isnan(inside_rows[0].get("target_db", math.nan)):
            local_target_db = float(_mean([row["target_db"] for row in inside_rows], default=local_target_db))

        in_point_mse = _mean([(value - local_target_db) ** 2 for value in inside_spl], default=0.0)
        in_ripple = _variance(inside_spl)
        e_in_f = in_point_mse + 0.25 * in_ripple

        spill_threshold_db = float(freq_target.out_of_coverage_threshold_db)
        e_out_f = spill_weight * _mean(
            [max(0.0, value - spill_threshold_db) ** 2 for value in outside_spl],
            default=0.0,
        )

        bw_h_sim, bw_h_skipped, bw_h_reason = _estimate_plane_beamwidth_deg(
            rows,
            phi_center_deg=0.0,
            phi_tolerance_deg=15.0,
            db_down=beamwidth_db_down,
        )
        bw_v_sim, bw_v_skipped, bw_v_reason = _estimate_plane_beamwidth_deg(
            rows,
            phi_center_deg=90.0,
            phi_tolerance_deg=15.0,
            db_down=beamwidth_db_down,
        )

        bw_skip_reason = ""
        bw_numerator = 0.0
        bw_denominator = 0.0
        if bw_h_sim is not None and freq_target.horizontal_target_beamwidth_deg is not None:
            bw_numerator += float(freq_target.beta_f or 1.0) * (
                bw_h_sim - float(freq_target.horizontal_target_beamwidth_deg)
            ) ** 2
            bw_denominator += max(float(freq_target.beta_f or 1.0), 0.0)
        else:
            bw_skip_reason = f"h:{bw_h_reason}"
        if bw_v_sim is not None and freq_target.vertical_target_beamwidth_deg is not None:
            bw_numerator += float(freq_target.gamma_f or 1.0) * (
                bw_v_sim - float(freq_target.vertical_target_beamwidth_deg)
            ) ** 2
            bw_denominator += max(float(freq_target.gamma_f or 1.0), 0.0)
        else:
            bw_skip_reason = f"{bw_skip_reason}; v:{bw_v_reason}".strip("; ")
        if bw_denominator > 0.0:
            e_bw_f = bw_numerator / bw_denominator
        else:
            e_bw_f = 0.0
            beamwidth_skipped_frequencies.append(float(frequency_hz))

        boundary_rows = [row for row in rows if row["boundary_distance_deg"] <= smooth_boundary_band_deg]
        boundary_rows.sort(key=lambda item: (item["phi_deg"], item["theta_deg"]))
        boundary_diffs = []
        for prev, cur in zip(boundary_rows, boundary_rows[1:]):
            if _angular_distance_deg(prev["phi_deg"], cur["phi_deg"]) > 45.0:
                continue
            boundary_diffs.append((cur["spl_db"] - prev["spl_db"]) ** 2)
        e_boundary_f = _mean(boundary_diffs, default=0.0)

        outside_peak = max(outside_spl) if outside_spl else spill_threshold_db
        side_lobe_limit = spill_threshold_db + side_lobe_margin_db
        e_sidelobe_f = max(0.0, outside_peak - side_lobe_limit) ** 2

        efficiency_values = [row["efficiency_proxy_db"] for row in rows if not math.isnan(row["efficiency_proxy_db"])]
        matching_values = [row["matching_proxy"] for row in rows if not math.isnan(row["matching_proxy"])]
        matching_mean = _mean(matching_values, default=math.nan) if matching_values else None
        min_matching_local = float(freq_target.min_matching_proxy or min_matching_proxy)
        matching_error = 0.0
        if matching_mean is not None:
            matching_error = max(0.0, min_matching_local - matching_mean) ** 2

        if efficiency_values:
            eff_proxy_db = _mean(efficiency_values)
            min_eff_local = float(freq_target.min_efficiency_proxy_db or min_efficiency_proxy_db)
            e_eff_f = max(0.0, min_eff_local - eff_proxy_db) ** 2 + matching_error
            eff_mode = "efficiency_proxy_db+matching_proxy" if matching_mean is not None else "efficiency_proxy_db"
            energy_concentration = None
        else:
            inside_energy = _mean([10.0 ** (value / 10.0) for value in inside_spl], default=0.0)
            outside_energy = _mean([10.0 ** (value / 10.0) for value in outside_spl], default=0.0)
            denom = inside_energy + outside_energy
            energy_concentration = inside_energy / denom if denom > 0.0 else 0.0
            e_eff_f = max(0.0, min_energy_concentration - energy_concentration) ** 2 + matching_error
            eff_mode = (
                "energy_concentration_proxy+matching_proxy"
                if matching_mean is not None
                else "energy_concentration_proxy"
            )
            eff_proxy_db = None

        frequency_scores.append(
            FrequencyScore(
                frequency_hz=float(frequency_hz),
                alpha_f=float(freq_target.alpha_f or 1.0),
                beta_f=float(freq_target.beta_f or 1.0),
                gamma_f=float(freq_target.gamma_f or 1.0),
                target_level_db=local_target_db,
                spill_threshold_db=spill_threshold_db,
                bw_h_target_deg=freq_target.horizontal_target_beamwidth_deg,
                bw_v_target_deg=freq_target.vertical_target_beamwidth_deg,
                inside_count=len(inside_rows),
                outside_count=len(outside_rows),
                inside_mean_db=inside_mean_db,
                inside_std_db=inside_std_db,
                outside_mean_db=outside_mean_db,
                on_axis_db=on_axis_db,
                bw_h_sim_deg=bw_h_sim,
                bw_v_sim_deg=bw_v_sim,
                bw_h_skipped=bw_h_skipped,
                bw_v_skipped=bw_v_skipped,
                bw_skip_reason=bw_skip_reason,
                e_in_f=e_in_f,
                e_out_f=e_out_f,
                e_bw_f=e_bw_f,
                e_boundary_f=e_boundary_f,
                e_sidelobe_f=e_sidelobe_f,
                e_eff_f=e_eff_f,
                eff_proxy_mode=eff_mode,
                efficiency_proxy_db=eff_proxy_db,
                matching_proxy_mean=matching_mean,
                matching_error_f=matching_error,
                energy_concentration=energy_concentration,
            )
        )

        point_cache[frequency_hz] = {
            (int(round(row["theta_deg"] * 1000.0)), int(round(row["phi_deg"] * 1000.0))): row["spl_db"]
            for row in rows
        }

    e_in = _weighted_mean([(item.e_in_f, item.alpha_f) for item in frequency_scores], default=0.0)
    e_out = _weighted_mean([(item.e_out_f, item.alpha_f) for item in frequency_scores], default=0.0)
    e_bw = _weighted_mean(
        [
            (
                item.e_bw_f,
                max(item.beta_f if item.bw_h_sim_deg is not None else 0.0, 0.0)
                + max(item.gamma_f if item.bw_v_sim_deg is not None else 0.0, 0.0),
            )
            for item in frequency_scores
        ],
        default=0.0,
    )
    e_eff = _weighted_mean([(item.e_eff_f, item.alpha_f) for item in frequency_scores], default=0.0)

    e_smooth_boundary = _weighted_mean([(item.e_boundary_f, item.alpha_f) for item in frequency_scores], default=0.0)
    e_smooth_sidelobe = _weighted_mean([(item.e_sidelobe_f, item.alpha_f) for item in frequency_scores], default=0.0)

    transition_terms: list[tuple[float, float]] = []
    sorted_frequencies = sorted(point_cache.keys())
    for current, nxt in zip(sorted_frequencies, sorted_frequencies[1:]):
        points_a = point_cache[current]
        points_b = point_cache[nxt]
        common = set(points_a.keys()) & set(points_b.keys())
        if not common:
            continue
        transition_error = _mean([(points_b[key] - points_a[key]) ** 2 for key in common], default=0.0)
        alpha_a = next(item.alpha_f for item in frequency_scores if item.frequency_hz == current)
        alpha_b = next(item.alpha_f for item in frequency_scores if item.frequency_hz == nxt)
        transition_terms.append((transition_error, 0.5 * (alpha_a + alpha_b)))
    e_smooth_transition = _weighted_mean(transition_terms, default=0.0)
    e_smooth = (
        max(smooth_transition_weight, 0.0) * e_smooth_transition
        + max(smooth_boundary_weight, 0.0) * e_smooth_boundary
        + max(smooth_sidelobe_weight, 0.0) * e_smooth_sidelobe
    )

    e_mfg = _geometry_manufacturability_penalty(geometry_params, geometry_bounds) * max(mfg_penalty_scale, 0.0)

    j_value = (
        weights["w_in"] * e_in
        + weights["w_out"] * e_out
        + weights["w_bw"] * e_bw
        + weights["w_smooth"] * e_smooth
        + weights["w_eff"] * e_eff
        + weights["w_mfg"] * e_mfg
    )
    fitness = -j_value

    if beamwidth_skipped_frequencies:
        skipped_components.append("E_bw")
    if not any(item.efficiency_proxy_db is not None for item in frequency_scores):
        warnings.append("Efficiency proxy column missing; using energy concentration proxy for E_eff.")

    score = ScoreBreakdown(
        fitness=fitness,
        total_cost=j_value,
        total_error=j_value,
        objective="J = w_in*E_in + w_out*E_out + w_bw*E_bw + w_smooth*E_smooth + w_eff*E_eff + w_mfg*E_mfg",
        maximize_conversion="fitness = -J",
        J=j_value,
        E_in=e_in,
        E_out=e_out,
        E_bw=e_bw,
        E_smooth=e_smooth,
        E_eff=e_eff,
        E_mfg=e_mfg,
        E_smooth_transition=e_smooth_transition,
        E_smooth_boundary=e_smooth_boundary,
        E_smooth_sidelobe=e_smooth_sidelobe,
        w_in=weights["w_in"],
        w_out=weights["w_out"],
        w_bw=weights["w_bw"],
        w_smooth=weights["w_smooth"],
        w_eff=weights["w_eff"],
        w_mfg=weights["w_mfg"],
        inside_count=inside_count,
        outside_count=outside_count,
        frequency_count=len(frequency_scores),
        beamwidth_skipped=bool(beamwidth_skipped_frequencies),
        beamwidth_skipped_frequencies=beamwidth_skipped_frequencies,
        skipped_components=sorted(set(skipped_components)),
        warnings=warnings,
        source_observation=str(observation.source_path),
        coverage_target_source=str(coverage_target.source_path) if coverage_target.source_path else "",
        score_json_path=None,
        score_csv_path=None,
        frequency_metrics=[item.__dict__ for item in frequency_scores],
    )

    if breakdown_output_dir:
        score_json, score_csv = _write_score_artifacts(
            score=score,
            output_dir=breakdown_output_dir,
            case_tag=breakdown_case_tag or observation_file.stem,
        )
        score.score_json_path = score_json
        score.score_csv_path = score_csv
    return score


def score_observation_csv(
    observation_csv: Path,
    target_db: float,
    outside_target_db: float,
    spill_weight: float,
    coverage_half_angle_deg: float = 45.0,
    geometry_params: dict[str, float] | None = None,
    geometry_bounds: dict[str, tuple[float, float]] | None = None,
    objective_weights: dict[str, float] | None = None,
    alpha_frequency_weights: dict[float, float] | None = None,
    beta_frequency_weights: dict[float, float] | None = None,
    gamma_frequency_weights: dict[float, float] | None = None,
    beamwidth_db_down: float = 6.0,
    default_bw_h_target_deg: float | None = None,
    default_bw_v_target_deg: float | None = None,
    smooth_boundary_band_deg: float = 8.0,
    side_lobe_margin_db: float = 3.0,
    smooth_transition_weight: float = 0.5,
    smooth_boundary_weight: float = 0.3,
    smooth_sidelobe_weight: float = 0.2,
    min_efficiency_proxy_db: float = -6.0,
    min_matching_proxy: float = 0.45,
    min_energy_concentration: float = 0.65,
    mfg_penalty_scale: float = 1.0,
    coverage_target_path: str = "",
    breakdown_output_dir: Path | None = None,
    breakdown_case_tag: str | None = None,
) -> ScoreBreakdown:
    return score_observation_file(
        observation_file=observation_csv,
        target_db=target_db,
        outside_target_db=outside_target_db,
        spill_weight=spill_weight,
        coverage_half_angle_deg=coverage_half_angle_deg,
        geometry_params=geometry_params,
        geometry_bounds=geometry_bounds,
        objective_weights=objective_weights,
        alpha_frequency_weights=alpha_frequency_weights,
        beta_frequency_weights=beta_frequency_weights,
        gamma_frequency_weights=gamma_frequency_weights,
        beamwidth_db_down=beamwidth_db_down,
        default_bw_h_target_deg=default_bw_h_target_deg,
        default_bw_v_target_deg=default_bw_v_target_deg,
        smooth_boundary_band_deg=smooth_boundary_band_deg,
        side_lobe_margin_db=side_lobe_margin_db,
        smooth_transition_weight=smooth_transition_weight,
        smooth_boundary_weight=smooth_boundary_weight,
        smooth_sidelobe_weight=smooth_sidelobe_weight,
        min_efficiency_proxy_db=min_efficiency_proxy_db,
        min_matching_proxy=min_matching_proxy,
        min_energy_concentration=min_energy_concentration,
        mfg_penalty_scale=mfg_penalty_scale,
        coverage_target_path=coverage_target_path,
        breakdown_output_dir=breakdown_output_dir,
        breakdown_case_tag=breakdown_case_tag,
    )
