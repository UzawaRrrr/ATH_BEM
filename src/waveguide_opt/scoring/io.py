from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class ObservationPoint:
    frequency_hz: float
    theta_rad: float
    phi_rad: float
    spl_db: float
    inside_coverage: float | None = None
    efficiency_proxy_db: float | None = None
    matching_proxy: float | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    r_distance_m: float | None = None
    target_db: float | None = None


@dataclass
class ObservationData:
    source_path: Path
    points: list[ObservationPoint]
    detected_schema: dict[str, str]
    warnings: list[str] = field(default_factory=list)


def _normalize_key(raw: str) -> str:
    return raw.strip().lower().replace(" ", "_")


def _safe_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _find_first(keys: set[str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in keys:
            return candidate
    return None


def _infer_angle_unit(field_name: str, values: list[float], warnings: list[str]) -> str:
    if "rad" in field_name:
        return "rad"
    if "deg" in field_name:
        return "deg"
    if not values:
        return "deg"
    max_abs = max(abs(value) for value in values)
    if max_abs <= (2.0 * math.pi + 0.2):
        warnings.append(f"Angle unit for '{field_name}' inferred as radians from value range.")
        return "rad"
    warnings.append(f"Angle unit for '{field_name}' inferred as degrees from value range.")
    return "deg"


def _records_from_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        return [dict(row) for row in reader]


def _records_from_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("records", "observations", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, dict)]
    raise ValueError("JSON observation must be a list of objects or contain records/observations/data list.")


def _records_from_npz(path: Path) -> list[dict[str, Any]]:
    data = np.load(path, allow_pickle=True)
    keys = list(data.keys())
    if not keys:
        raise ValueError("NPZ file is empty.")

    lengths = [len(np.ravel(data[key])) for key in keys]
    if len(set(lengths)) != 1:
        raise ValueError("NPZ arrays must have equal length to be interpreted as observation columns.")

    n_rows = lengths[0]
    rows: list[dict[str, Any]] = []
    for index in range(n_rows):
        row: dict[str, Any] = {}
        for key in keys:
            value = np.ravel(data[key])[index]
            row[key] = value.item() if hasattr(value, "item") else value
        rows.append(row)
    return rows


def parse_observation_file(path: Path) -> ObservationData:
    if not path.exists():
        raise FileNotFoundError(f"Observation file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        records = _records_from_csv(path)
    elif suffix == ".json":
        records = _records_from_json(path)
    elif suffix == ".npz":
        records = _records_from_npz(path)
    else:
        raise ValueError(f"Unsupported observation format: {path.suffix}. Supported: .csv .json .npz")

    if not records:
        raise ValueError(f"Observation file has no records: {path}")

    normalized_records = [{_normalize_key(str(key)): value for key, value in record.items()} for record in records]
    keys = set(normalized_records[0].keys())

    freq_key = _find_first(keys, ["frequency_hz", "freq_hz", "frequency", "f_hz", "freq"])
    theta_key = _find_first(
        keys,
        [
            "theta_polar_rad",
            "theta_rad",
            "theta_polar_deg",
            "theta_deg",
            "theta",
        ],
    )
    phi_key = _find_first(
        keys,
        [
            "phi_azimuth_rad",
            "phi_rad",
            "phi_azimuth_deg",
            "phi_deg",
            "phi",
        ],
    )
    spl_key = _find_first(keys, ["spl_normalized_db", "spl_db", "spl_norm_db", "spl"])

    missing_required = []
    if freq_key is None:
        missing_required.append("frequency_hz/frequency")
    if theta_key is None:
        missing_required.append("theta_polar_rad/theta_deg")
    if spl_key is None:
        missing_required.append("spl_normalized_db/spl_db")
    if missing_required:
        available = ", ".join(sorted(keys))
        raise ValueError(
            f"Observation schema missing required fields: {', '.join(missing_required)}. "
            f"Available fields: {available}"
        )

    warnings: list[str] = []
    theta_values = [_safe_float(record.get(theta_key)) for record in normalized_records]
    phi_values = [_safe_float(record.get(phi_key)) for record in normalized_records] if phi_key else []
    theta_values_numeric = [value for value in theta_values if value is not None]
    phi_values_numeric = [value for value in phi_values if value is not None]
    theta_unit = _infer_angle_unit(theta_key, theta_values_numeric, warnings)
    phi_unit = _infer_angle_unit(phi_key or "phi_deg", phi_values_numeric, warnings) if phi_key else "deg"
    if phi_key is None:
        warnings.append("Phi column not found; defaulting phi to 0 deg.")

    optional_keys = {
        "inside_coverage": _find_first(keys, ["inside_coverage"]),
        "efficiency_proxy_db": _find_first(keys, ["efficiency_proxy_db"]),
        "matching_proxy": _find_first(keys, ["matching_proxy"]),
        "target_db": _find_first(keys, ["target_db"]),
        "x": _find_first(keys, ["x"]),
        "y": _find_first(keys, ["y"]),
        "z": _find_first(keys, ["z"]),
        "r_distance_m": _find_first(keys, ["r_distance_m", "r", "distance_m"]),
    }

    points: list[ObservationPoint] = []
    for row_index, record in enumerate(normalized_records):
        frequency_hz = _safe_float(record.get(freq_key))
        theta_value = _safe_float(record.get(theta_key))
        phi_value = _safe_float(record.get(phi_key)) if phi_key else 0.0
        spl_db = _safe_float(record.get(spl_key))
        if frequency_hz is None or theta_value is None or phi_value is None or spl_db is None:
            raise ValueError(
                f"Invalid numeric value at row {row_index + 1} in {path}. "
                f"Required fields: {freq_key}, {theta_key}, {phi_key or 'phi'}, {spl_key}"
            )

        theta_rad = theta_value if theta_unit == "rad" else math.radians(theta_value)
        phi_rad = phi_value if phi_unit == "rad" else math.radians(phi_value)

        points.append(
            ObservationPoint(
                frequency_hz=float(frequency_hz),
                theta_rad=float(theta_rad),
                phi_rad=float(phi_rad),
                spl_db=float(spl_db),
                inside_coverage=_safe_float(record.get(optional_keys["inside_coverage"])) if optional_keys["inside_coverage"] else None,
                efficiency_proxy_db=_safe_float(record.get(optional_keys["efficiency_proxy_db"])) if optional_keys["efficiency_proxy_db"] else None,
                matching_proxy=_safe_float(record.get(optional_keys["matching_proxy"])) if optional_keys["matching_proxy"] else None,
                x=_safe_float(record.get(optional_keys["x"])) if optional_keys["x"] else None,
                y=_safe_float(record.get(optional_keys["y"])) if optional_keys["y"] else None,
                z=_safe_float(record.get(optional_keys["z"])) if optional_keys["z"] else None,
                r_distance_m=_safe_float(record.get(optional_keys["r_distance_m"])) if optional_keys["r_distance_m"] else None,
                target_db=_safe_float(record.get(optional_keys["target_db"])) if optional_keys["target_db"] else None,
            )
        )

    detected_schema = {
        "frequency_key": freq_key,
        "theta_key": theta_key,
        "theta_unit": theta_unit,
        "phi_key": phi_key or "phi_default_0",
        "phi_unit": phi_unit if phi_key else "deg",
        "spl_key": spl_key,
    }
    return ObservationData(source_path=path, points=points, detected_schema=detected_schema, warnings=warnings)


def generate_mock_observation_csv(
    output_path: Path,
    profile: str = "good",
    frequencies_hz: list[float] | None = None,
    horizontal_coverage_deg: float = 90.0,
    vertical_coverage_deg: float = 90.0,
) -> Path:
    frequencies = frequencies_hz or [1000.0, 2000.0, 4000.0]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    h_half = max(horizontal_coverage_deg * 0.5, 1.0)
    v_half = max(vertical_coverage_deg * 0.5, 1.0)
    theta_values = list(range(0, 91, 5))
    phi_values = list(range(0, 360, 30))

    fieldnames = [
        "frequency_hz",
        "theta_deg",
        "phi_deg",
        "spl_db",
        "inside_coverage",
        "efficiency_proxy_db",
        "matching_proxy",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()

        for freq in frequencies:
            freq_tilt = -1.5 * abs(math.log10(max(freq, 1.0) / 2000.0))
            for phi_deg in phi_values:
                phi_rad = math.radians(phi_deg)
                local_limit = 1.0 / math.sqrt(
                    (math.cos(phi_rad) ** 2) / (h_half**2) + (math.sin(phi_rad) ** 2) / (v_half**2)
                )
                for theta_deg in theta_values:
                    theta_ratio = theta_deg / max(local_limit, 1e-6)
                    if profile == "good":
                        spl_db = 2.0 + freq_tilt - 6.0 * (theta_ratio**2)
                        spl_db -= max(0.0, theta_ratio - 1.0) * 12.0
                        eff_proxy = -4.0 + freq_tilt
                        matching_proxy = 0.65
                    else:
                        ripple = 2.5 * math.sin(math.radians(theta_deg * 3.0 + phi_deg))
                        sidelobe = 6.0 if theta_deg > local_limit * 1.15 else 0.0
                        spl_db = 1.0 + freq_tilt - 4.0 * (theta_ratio**1.3) + ripple + sidelobe
                        eff_proxy = -9.0 + freq_tilt
                        matching_proxy = 0.25

                    inside = 1 if theta_deg <= local_limit else 0
                    writer.writerow(
                        {
                            "frequency_hz": float(freq),
                            "theta_deg": float(theta_deg),
                            "phi_deg": float(phi_deg),
                            "spl_db": float(spl_db),
                            "inside_coverage": inside,
                            "efficiency_proxy_db": float(eff_proxy),
                            "matching_proxy": float(matching_proxy),
                        }
                    )

    return output_path

