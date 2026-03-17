from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .ga_optimization import Bounds, Individual


DEFAULT_PARAMETER_SPEC: dict[str, dict[str, Any]] = {
    "length": {"initial": 0.24, "include_in_ga": True, "bounds": [0.12, 0.5]},
    "throat_radius": {"initial": 0.02, "include_in_ga": True, "bounds": [0.01, 0.05]},
    "mouth_radius": {"initial": 0.12, "include_in_ga": True, "bounds": [0.05, 0.25]},
    "flare": {"initial": 1.3, "include_in_ga": True, "bounds": [0.4, 2.5]},
}


@dataclass
class GARuntimeSetup:
    bounds: Bounds
    fixed_params: Individual
    initial_params: Individual
    enabled_params: list[str]
    disabled_params: list[str]
    source_path: str
    warnings: list[str]


def _safe_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _safe_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    token = str(raw).strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    return default


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _resolve_path(base: Path, raw: str) -> Path:
    token = Path(str(raw)).expanduser()
    if token.is_absolute():
        return token
    return (base / token).resolve()


def _merge_specs(
    fallback_bounds: Bounds,
    file_data: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    warnings: list[str] = []
    result: dict[str, dict[str, Any]] = {}
    for name, default in DEFAULT_PARAMETER_SPEC.items():
        result[name] = dict(default)
    for name, bounds in fallback_bounds.items():
        entry = result.setdefault(
            name,
            {"initial": 0.5 * (bounds[0] + bounds[1]), "include_in_ga": True, "bounds": list(bounds)},
        )
        entry["bounds"] = [float(bounds[0]), float(bounds[1])]
        entry.setdefault("initial", 0.5 * (float(bounds[0]) + float(bounds[1])))
        entry.setdefault("include_in_ga", True)

    raw_params = file_data.get("parameters")
    if isinstance(raw_params, dict):
        for name, raw_entry in raw_params.items():
            if not isinstance(raw_entry, dict):
                warnings.append(f"Parameter '{name}' ignored because entry is not a mapping.")
                continue
            existing = result.get(name, {"initial": 0.0, "include_in_ga": True, "bounds": [0.0, 1.0]})
            bounds = raw_entry.get("bounds", existing.get("bounds", [0.0, 1.0]))
            if "min_value" in raw_entry or "max_value" in raw_entry:
                bounds = [
                    raw_entry.get("min_value", existing.get("bounds", [0.0, 1.0])[0]),
                    raw_entry.get("max_value", existing.get("bounds", [0.0, 1.0])[1]),
                ]
            if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                bounds = existing.get("bounds", [0.0, 1.0])
                warnings.append(f"Parameter '{name}' has invalid bounds; fallback applied.")
            low = _safe_float(bounds[0], 0.0)
            high = _safe_float(bounds[1], low + 1.0)
            if high <= low:
                high = low + 1e-6
                warnings.append(f"Parameter '{name}' had non-increasing bounds; adjusted.")
            initial_default = existing.get("initial", 0.5 * (low + high))
            initial_raw = raw_entry.get("initial_value")
            if initial_raw is None:
                initial_raw = raw_entry.get("initial")
            initial = _safe_float(initial_raw, float(initial_default))
            include_raw = raw_entry.get("include_in_ga")
            if include_raw is None:
                include_raw = raw_entry.get("include")
            include = _safe_bool(include_raw, bool(existing.get("include_in_ga", True)))
            result[str(name)] = {
                "initial": float(initial),
                "include_in_ga": include,
                "bounds": [float(low), float(high)],
            }
    return result, warnings


def load_ga_runtime_setup(
    path_token: str,
    fallback_bounds: Bounds,
    base_dir: Path,
) -> GARuntimeSetup:
    source = _resolve_path(base_dir, path_token) if path_token else Path("")
    file_data = _read_yaml(source) if source and source.exists() else {}
    merged, warnings = _merge_specs(fallback_bounds=fallback_bounds, file_data=file_data)

    bounds: Bounds = {}
    fixed: Individual = {}
    initial: Individual = {}
    enabled: list[str] = []
    disabled: list[str] = []

    for name, entry in merged.items():
        low, high = float(entry["bounds"][0]), float(entry["bounds"][1])
        value = float(entry["initial"])
        value = min(max(value, low), high)
        include = bool(entry["include_in_ga"])
        initial[name] = value
        if include:
            bounds[name] = (low, high)
            enabled.append(name)
        else:
            fixed[name] = value
            disabled.append(name)

    if not bounds:
        raise ValueError("GA parameter configuration disabled all parameters; enable at least one parameter.")

    return GARuntimeSetup(
        bounds=bounds,
        fixed_params=fixed,
        initial_params=initial,
        enabled_params=enabled,
        disabled_params=disabled,
        source_path=str(source) if source else "",
        warnings=warnings,
    )
