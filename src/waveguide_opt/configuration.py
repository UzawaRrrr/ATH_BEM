from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "local_paths.yaml"
FALLBACK_CONFIG_PATH = PROJECT_ROOT / "config" / "local_paths.example.yaml"


@dataclass
class LocalPaths:
    ath_executable: str
    gmsh_executable: str
    working_directory: Path
    mesh_output_directory: Path
    solver_output_directory: Path
    temp_directory: Path
    logs_directory: Path
    outputs_directory: Path


@dataclass
class RuntimeSettings:
    default_mode: str
    timeout_seconds: int
    frequencies_hz: list[float]
    coverage_half_angle_deg: float
    coverage_target_path: str
    target_db: float
    outside_target_db: float
    spill_weight: float
    beamwidth_db_down: float
    min_efficiency_proxy_db: float
    min_matching_proxy: float
    min_energy_concentration: float
    mfg_penalty_scale: float
    smooth_boundary_band_deg: float
    side_lobe_margin_db: float
    smooth_transition_weight: float
    smooth_boundary_weight: float
    smooth_sidelobe_weight: float
    default_bw_h_target_deg: float
    default_bw_v_target_deg: float
    objective_weights: dict[str, float]
    alpha_frequency_weights: dict[float, float]
    beta_frequency_weights: dict[float, float]
    gamma_frequency_weights: dict[float, float]
    solver_prefer_wsl: bool
    bempp_tolerance: float
    bempp_max_iterations: int
    wsl_python_executable: str
    wsl_distro: str
    wsl_solver_repeated_runs: int
    ga_parameters_path: str
    full_population_size: int
    full_generations: int
    full_mutation_scale: float
    full_elite_count: int
    random_seed: int


@dataclass
class ProjectConfig:
    paths: LocalPaths
    runtime: RuntimeSettings
    config_path: Path


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _resolve_path(base: Path, raw: str) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base / candidate).resolve()


def _resolve_executable_token(base: Path, raw: str, default: str) -> str:
    value = str(raw or default).strip()
    if not value:
        return ""
    token = Path(value).expanduser()
    if token.is_absolute():
        return str(token)
    if "/" in value or "\\" in value or value.startswith("."):
        return str((base / token).resolve())
    return value


def _resolve_optional_path_token(base: Path, raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    token = Path(value).expanduser()
    if token.is_absolute():
        return str(token)
    return str((base / token).resolve())


def _parse_frequency_weight_map(raw: Any) -> dict[float, float]:
    if not isinstance(raw, dict):
        return {}
    parsed: dict[float, float] = {}
    for key, value in raw.items():
        try:
            freq = float(key)
            weight = float(value)
        except (TypeError, ValueError):
            continue
        parsed[freq] = weight
    return parsed


def _normalize_mode(raw_mode: str) -> str:
    mode = (raw_mode or "mock").strip().lower()
    if mode not in {"mock", "real"}:
        return "mock"
    return mode


def _parse_bool(raw: Any, default: bool) -> bool:
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


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            result[key] = _merge_dict(base[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Path | None = None) -> ProjectConfig:
    config_file = config_path or DEFAULT_CONFIG_PATH
    fallback_data = _read_yaml(FALLBACK_CONFIG_PATH)
    config_data = _merge_dict(fallback_data, _read_yaml(config_file))

    base = PROJECT_ROOT
    paths_data = config_data.get("paths", {})
    runtime_data = config_data.get("runtime", {})
    objective_weights_data = runtime_data.get("objective_weights")
    legacy_weights_data = runtime_data.get("scoring_weights")
    objective_raw = objective_weights_data if isinstance(objective_weights_data, dict) else {}
    legacy_raw = legacy_weights_data if isinstance(legacy_weights_data, dict) else {}
    default_objective_weights = {
        "w_in": 0.40,
        "w_out": 0.30,
        "w_bw": 0.15,
        "w_smooth": 0.05,
        "w_eff": 0.05,
        "w_mfg": 0.05,
    }
    parsed_objective_weights = dict(default_objective_weights)

    for key, value in legacy_raw.items():
        if key == "outside_spill":
            parsed_objective_weights["w_out"] = float(value)
        elif key == "geometry":
            parsed_objective_weights["w_mfg"] = float(value)

    for key, value in objective_raw.items():
        if key not in parsed_objective_weights:
            continue
        try:
            parsed_objective_weights[str(key)] = float(value)
        except (TypeError, ValueError):
            continue

    paths = LocalPaths(
        ath_executable=_resolve_executable_token(base, str(paths_data.get("ath_executable", "")), ""),
        gmsh_executable=_resolve_executable_token(base, str(paths_data.get("gmsh_executable", "gmsh")), "gmsh"),
        working_directory=_resolve_path(base, str(paths_data.get("working_directory", "."))),
        mesh_output_directory=_resolve_path(base, str(paths_data.get("mesh_output_directory", "outputs/mesh"))),
        solver_output_directory=_resolve_path(base, str(paths_data.get("solver_output_directory", "outputs/solver"))),
        temp_directory=_resolve_path(base, str(paths_data.get("temp_directory", "outputs/tmp"))),
        logs_directory=_resolve_path(base, str(paths_data.get("logs_directory", "logs"))),
        outputs_directory=_resolve_path(base, str(paths_data.get("outputs_directory", "outputs"))),
    )

    runtime = RuntimeSettings(
        default_mode=_normalize_mode(str(runtime_data.get("default_mode", "mock"))),
        timeout_seconds=int(runtime_data.get("timeout_seconds", 120)),
        frequencies_hz=[float(item) for item in runtime_data.get("frequencies_hz", [1000.0, 2000.0, 4000.0])],
        coverage_half_angle_deg=float(runtime_data.get("coverage_half_angle_deg", 45.0)),
        coverage_target_path=_resolve_optional_path_token(base, str(runtime_data.get("coverage_target_path", ""))),
        target_db=float(runtime_data.get("target_db", 0.0)),
        outside_target_db=float(runtime_data.get("outside_target_db", -20.0)),
        spill_weight=float(runtime_data.get("spill_weight", 1.5)),
        beamwidth_db_down=float(runtime_data.get("beamwidth_db_down", 6.0)),
        min_efficiency_proxy_db=float(runtime_data.get("min_efficiency_proxy_db", -6.0)),
        min_matching_proxy=float(runtime_data.get("min_matching_proxy", 0.45)),
        min_energy_concentration=float(runtime_data.get("min_energy_concentration", 0.65)),
        mfg_penalty_scale=float(runtime_data.get("mfg_penalty_scale", runtime_data.get("geometry_penalty_scale", 1.0))),
        smooth_boundary_band_deg=float(runtime_data.get("smooth_boundary_band_deg", 8.0)),
        side_lobe_margin_db=float(runtime_data.get("side_lobe_margin_db", 3.0)),
        smooth_transition_weight=float(runtime_data.get("smooth_transition_weight", 0.5)),
        smooth_boundary_weight=float(runtime_data.get("smooth_boundary_weight", 0.3)),
        smooth_sidelobe_weight=float(runtime_data.get("smooth_sidelobe_weight", 0.2)),
        default_bw_h_target_deg=float(runtime_data.get("default_bw_h_target_deg", 2.0 * float(runtime_data.get("coverage_half_angle_deg", 45.0)))),
        default_bw_v_target_deg=float(runtime_data.get("default_bw_v_target_deg", 2.0 * float(runtime_data.get("coverage_half_angle_deg", 45.0)))),
        objective_weights=parsed_objective_weights,
        alpha_frequency_weights=_parse_frequency_weight_map(runtime_data.get("alpha_frequency_weights")),
        beta_frequency_weights=_parse_frequency_weight_map(runtime_data.get("beta_frequency_weights")),
        gamma_frequency_weights=_parse_frequency_weight_map(runtime_data.get("gamma_frequency_weights")),
        solver_prefer_wsl=_parse_bool(runtime_data.get("solver_prefer_wsl"), True),
        bempp_tolerance=float(runtime_data.get("bempp_tolerance", 1.0e-5)),
        bempp_max_iterations=int(runtime_data.get("bempp_max_iterations", 400)),
        wsl_python_executable=str(runtime_data.get("wsl_python_executable", ".venv_wsl/bin/python")),
        wsl_distro=str(runtime_data.get("wsl_distro", "")),
        wsl_solver_repeated_runs=int(runtime_data.get("wsl_solver_repeated_runs", 1)),
        ga_parameters_path=_resolve_optional_path_token(
            base, str(runtime_data.get("ga_parameters_path", "config/geometry_params.yaml"))
        ),
        full_population_size=int(runtime_data.get("full_population_size", 20)),
        full_generations=int(runtime_data.get("full_generations", 20)),
        full_mutation_scale=float(runtime_data.get("full_mutation_scale", 0.08)),
        full_elite_count=int(runtime_data.get("full_elite_count", 2)),
        random_seed=int(runtime_data.get("random_seed", 42)),
    )

    return ProjectConfig(paths=paths, runtime=runtime, config_path=config_file)
