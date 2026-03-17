# Project Map

## Purpose

This repository implements a local GA workflow for waveguide optimization:

1. GA proposes geometry parameters.
2. Mesh stage generates mesh (ATH+Gmsh in `real`, synthetic mesh in `mock`).
3. Solver stage generates observation/directivity data (`bempp_cl` solve in `real` when available, synthetic in `mock`).
4. Scoring compares simulated directivity against coverage target and returns scalar fitness.
5. GA iterates on fitness.

## Main Entrypoints

- `scripts/bootstrap_env.sh`
- `scripts/check_dependencies.py`
- `scripts/smoke_test.py`
- `scripts/test_scoring.py`
- `scripts/run_minimal_optimization.py`
- `scripts/benchmark_wsl_solver.py`
- `scripts/run_full_optimization.py`
- `scripts/run_gui.py`

## Core Modules (`src/waveguide_opt`)

- `configuration.py`
  - Loads `config/local_paths.yaml` and runtime knobs.
- `external_tools.py`
  - Unified executable resolution + subprocess calls (Windows/WSL compatible).
- `mesh_pipeline.py`
  - Mesh generation (`mock` or ATH+Gmsh `real`).
- `solver_pipeline.py`
  - Observation generation (`mock` or real-mode backend).
  - Real mode supports split execution:
    - mesh on Windows side
    - solver preferring WSL (`bempp_cl`) with explicit handoff metadata/logging.
- `ga_optimization.py`
  - GA (maximize framework).
- `ga_parameters.py`
  - Loads `config/geometry_params.yaml` for include/exclude, initial values, and bounds.
- `full_optimization_loop.py`
  - End-to-end evaluation and minimal GA run.
  - Also provides full run wrapper using config full GA defaults.
- `directivity_scoring.py`
  - Compatibility wrapper to `scoring/fitness.py`.
- `scoring/io.py`
  - Observation parser (CSV/JSON/NPZ) + mock observation generator.
- `scoring/coverage.py`
  - Coverage target config loader (YAML + legacy CSV) and per-frequency target resolution.
- `scoring/fitness.py`
  - Implements:
    - `J = w_in*E_in + w_out*E_out + w_bw*E_bw + w_smooth*E_smooth + w_eff*E_eff + w_mfg*E_mfg`
    - `fitness = -J`
  - Produces score breakdown and artifacts in `outputs/scoring/`.

## Config/Data Assets

- `config/local_paths.yaml`
  - local tool paths and runtime compatibility settings.
- `config/geometry_params.yaml`
- `config/geometry_params.example.yaml`
  - GA parameter include/exclude + bounds + initial value config.
- `config/ga_settings.yaml`
- `config/ga_settings.example.yaml`
  - GA runtime settings (population, generations, rates, seed, workers).
- `config/coverage_target.yaml`
  - default coverage target profile + weights/frequencies.
- `config/coverage_target.example.yaml`
  - editable reference for coverage tuning.
- `config/solver_settings.yaml`
- `config/solver_settings.example.yaml`
  - BEM and handoff settings.
- `config/coverage_target.example.csv`
  - legacy CSV frequency-override profile.
- `config/ath_database/tritonia/`
  - Tritonia ATH `.cfg` database and source index.
- `scripts/wsl_bempp_solver.py`
  - WSL-side solver runner invoked from Windows host for split pipeline mode.
- `src/waveguide_opt/gui/control_panel.py`
  - PySide6 desktop control panel with 7 tabs:
    - Environment
    - Geometry Parameters
    - GA Settings
    - Coverage / Fitness
    - Solver
    - Run / Monitor
    - Results

## Dependency Graph (Runtime)

1. `scripts/run_minimal_optimization.py`
2. `waveguide_opt.full_optimization_loop.run_minimal_loop`
3. `mesh_pipeline.build_mesh`
4. `solver_pipeline.solve_acoustics`
5. `scoring/fitness.score_observation_csv`
6. returns fitness to `ga_optimization.run_ga` (maximize loop)

## Observation Schema (Detected)

Required logical fields:

- frequency (`frequency_hz` / aliases)
- theta (`theta_deg/theta_rad` / aliases)
- SPL (`spl_db/spl_normalized_db` / aliases)

Optional:

- phi (`phi_deg/phi_rad`), defaults to `0 deg` if missing
- `inside_coverage`
- `efficiency_proxy_db`, `matching_proxy`
- `target_db`
- `x`, `y`, `z`, `r_distance_m`

## Fitness/Scoring Notes

- Coverage-in error and uniformity -> `E_in`
- Coverage-out spill suppression -> `E_out`
- Beamwidth target match (`-6 dB` or configured) -> `E_bw`
- Pattern smoothness across boundary/frequency/side-lobes -> `E_smooth`
- Efficiency/matching proxy -> `E_eff`
- Geometry/manufacturing guardrails -> `E_mfg`

If data is missing for a component (for example unstable beamwidth estimation), it is marked in `skipped_components` and warnings.
