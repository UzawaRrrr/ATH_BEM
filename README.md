# Waveguide Optimization (GA + ATH + Mesh + Acoustic/BEM + Coverage Scoring)

This repository provides a local, reproducible workflow for waveguide optimization:

1. Generate geometry parameters with a genetic algorithm (GA).
2. Build mesh from parameters (ATH + Gmsh in `real` mode, local mock in `mock` mode).
3. Run acoustic solve (BEM-backed in `real` mode when available, synthetic fallback in `mock` mode).
4. Generate observation/directivity data.
5. Score coverage error and iterate GA.

## Project Flow

Text pipeline:

`GA individual -> mesh generation -> solver -> observation CSV -> scoring -> fitness -> GA update`

Main implementation lives in `src/waveguide_opt/`.

## Scoring Objective

The GA objective follows:

`J = w_in*E_in + w_out*E_out + w_bw*E_bw + w_smooth*E_smooth + w_eff*E_eff + w_mfg*E_mfg`

where `J` is minimized. For GA maximize loops, this project uses:

`fitness = -J`

Term meaning:

- Coverage in-target level error
- Coverage in-target ripple/unevenness
- Outside-coverage spill penalty
- Beamwidth target error (`-6 dB` beamwidth; horizontal + vertical when available)
- Pattern smoothness/stability (boundary roughness, side-lobes, cross-frequency jumps)
- Efficiency/matching proxy penalty
- Geometry smooth/manufacturing penalty

Primary scoring knobs live in `config/coverage_target.yaml` (`objective_weights`, frequency list, coverage targets, optional alpha/beta/gamma maps). Runtime compatibility mirrors are also written to `config/local_paths.yaml`.
Detailed formula and implementation notes: `docs/fitness_design.md`.

GA parameter include/exclude + bounds are managed in:

- `config/geometry_params.yaml`
- example: `config/geometry_params.example.yaml`

Main editable config files:

- `config/local_paths.yaml`
- `config/geometry_params.yaml`
- `config/ga_settings.yaml`
- `config/coverage_target.yaml`
- `config/solver_settings.yaml`

## Environment Requirements

- Windows + WSL (recommended for shell script usage)
- Python 3.10+ (tested with Python 3.13)
- Gmsh CLI (`gmsh`) available
- ATH executable available if you want `--mode real`
- Optional for real acoustic solve: `bempp-cl` (or compatible `bempp` API)

## WSL Usage

From project root:

```bash
bash scripts/bootstrap_env.sh
```

To bootstrap and install ATH in one step:

```bash
INSTALL_ATH=1 bash scripts/bootstrap_env.sh
```

If ATH/Gmsh are installed on Windows only, set paths in `config/local_paths.yaml` using Windows paths or `/mnt/c/...` paths.
`bootstrap_env.sh` will print the exact activate path. In mixed Windows+WSL setups it may create `.venv_wsl`.

## Configure ATH / Gmsh Paths

Install ATH locally from official release (includes `ath.cfg`):

```bash
python scripts/install_ath.py
```

This command also syncs Tritonia ATH configs into:

- `config/ath_database/tritonia/`
- index file: `config/ath_database/tritonia/index.yaml`

Optional frequency-specific target profile example:

- preferred YAML:
  - `config/coverage_target.example.yaml`
  - `config/coverage_target.yaml`
- legacy CSV still supported:
  - `config/coverage_target.example.csv`
- set `runtime.coverage_target_path` to use any of the above

1. Copy and edit local config:

```bash
cp config/local_paths.example.yaml config/local_paths.yaml
```

2. Fill at least:
- `paths.ath_executable`
- `paths.gmsh_executable`
- `runtime.solver_prefer_wsl` (default `true` on this repo)
- `runtime.wsl_python_executable` (default `.venv_wsl/bin/python`)

`mock` mode does not require ATH/BEM.

## Split Pipeline (Windows Mesh + WSL Solver)

Real mode now supports an explicit handoff boundary:

1. Mesh generation can run on Windows (ATH/Gmsh native path).
2. Solver prefers WSL/Linux (`bempp_cl`) when `runtime.solver_prefer_wsl: true`.
3. Mesh handoff is validated before solve:
   - mesh file exists on Windows side
   - mesh path converted to WSL path
   - readability check from WSL (`test -r`)
4. Handoff metadata is persisted to:
   - `outputs/handoff/<case>_mesh_handoff.json`

WSL solver runner script:

- `scripts/wsl_bempp_solver.py`
- called automatically from real mode on Windows hosts when WSL is available.

## Create Virtual Environment

WSL:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
```

## Install Dependencies

WSL:

```bash
python -m pip install -r requirements.txt
```

PowerShell:

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Run Dependency Check

```bash
python scripts/check_dependencies.py --mode mock
python scripts/check_dependencies.py --mode real
```

In `--mode real`, dependency check also reports WSL solver path status when enabled.

## Run Smoke Test

Mock mode (recommended first):

```bash
python scripts/smoke_test.py --mode mock
```

Real mode:

```bash
python scripts/smoke_test.py --mode real
```

## Run Scoring Test

Validate parser + scoring with synthetic good/bad datasets:

```bash
python scripts/test_scoring.py
```

## Run Minimal Optimization

```bash
python scripts/run_minimal_optimization.py --mode mock --population-size 6 --generations 2
```

## Run Full Optimization

```bash
python scripts/run_full_optimization.py --mode mock
```

You can override full-run GA options with CLI flags:

```bash
python scripts/run_full_optimization.py --mode real --population-size 24 --generations 30 --mutation-scale 0.08 --elite-count 3
```

Real mode (requires ATH + Gmsh + BEM availability):

```bash
python scripts/run_minimal_optimization.py --mode real --population-size 4 --generations 1
```

For real mode with WSL solver, per-case benchmark info is included under `evaluations.*.details.wsl_benchmark` in:

- `outputs/minimal_optimization_result.json`

Standalone benchmark helper:

```bash
python scripts/benchmark_wsl_solver.py --mode real
```

## Desktop GUI Control Panel

Launch:

```bash
python scripts/run_gui.py
```

Validation-only check (no window):

```bash
python scripts/run_gui.py --check
```

GUI v1 supports:

- `1) Environment`
  - ATH path, Gmsh path, WSL distro/command path, project root, mesh/output/log dirs, real/mock toggle
- `2) Geometry Parameters`
  - editable table with:
    - `include_in_ga`
    - `parameter_name`
    - `initial_value`
    - `min_value`
    - `max_value`
    - `mutation_scale`
    - `unit`
    - `notes`
- `3) GA Settings`
  - population, generations, crossover/mutation rate, elitism, seed, early stopping, invalid penalty, workers
- `4) Coverage / Fitness`
  - coverage target angles/margins, in/out targets, frequency list/band, objective weights (`w_in..w_mfg`)
- `5) Solver`
  - BEM tolerance/iterations/retry/timeout/warmup/failure penalty, WSL toggle, mesh handoff options
- `6) Run / Monitor`
  - run buttons: dependency check, smoke, minimal, full, stop
  - live log
  - status/generation/current candidate/best fitness/best candidate summary
- `7) Results`
  - latest run summary, score breakdown, best parameters
  - open output folder
  - export config snapshot
  - load previous snapshot

GUI behavior:

- loads the five config files on startup
- edits/validates/saves each config independently
- keeps explicit `include_in_ga` per geometry parameter (not inferred from bounds)
- creates a per-run reproducible snapshot before each run under:
  - `outputs/runs/<timestamp>_<run_label>/config/`
- launches scripts with the snapshot `--config` so the run is reproducible

## Real Mode vs Mock Mode

- `real`:
  - Requires ATH path configured.
  - Requires Gmsh executable.
  - Prefers WSL `bempp_cl` solver path on Windows (`solver_prefer_wsl: true`).
  - Falls back to native `bempp_cl` path if WSL solver path fails.
  - Uses synthetic emergency fallback only when both BEM solve paths fail.
  - Fails fast when required external dependencies are missing.
- `mock`:
  - Generates synthetic mesh/observation data locally.
  - Always keeps GA + scoring chain executable for local validation.
  - Intended for CI/smoke/debug, not physically accurate acoustics.

## Output Layout

- `logs/`: runtime logs for dependency checks, smoke test, optimization.
- `outputs/`: result JSON, generated CSV, scored artifacts.
- `outputs/handoff/`: mesh handoff metadata (Windows->WSL boundary).
- `outputs/mesh/`: mesh files.
- `outputs/solver/`: solver observations.
- `outputs/scoring/`: score breakdown JSON and summary CSV.
- `outputs/tmp/`: temporary intermediate files.

Observation parser supports:

- CSV / JSON / NPZ
- required logical fields: frequency + theta + SPL
- optional: phi, inside_coverage, efficiency_proxy_db, matching_proxy, x/y/z/r_distance_m
- angle unit auto-detection from field name/value range

Current pipeline CSV columns are typically:
`frequency_hz`, `theta_deg`, `phi_deg`, `spl_db`, `inside_coverage`, `target_db`, `efficiency_proxy_db`, `matching_proxy`.

## Troubleshooting

1. `ATH executable not configured`:
   - Set `paths.ath_executable` in `config/local_paths.yaml`.
2. `Gmsh executable not found`:
   - Install Gmsh and set `paths.gmsh_executable` (or ensure `gmsh` is in `PATH`).
3. `bempp.api / bempp_cl.api not importable` in real mode:
   - Install compatible BEM package (for example `bempp-cl`), or run `--mode mock`.
4. WSL solver path fails in real mode:
   - Check `runtime.wsl_python_executable` (default `.venv_wsl/bin/python`).
   - Run `python scripts/check_dependencies.py --mode real` to inspect WSL checks.
   - Inspect `outputs/handoff/*.json` and runtime logs for path/readability details.
5. Windows/WSL path mismatch:
   - Use `/mnt/c/...` in WSL, `C:\...` in PowerShell.
6. Missing output directories:
   - Scripts auto-create directories, but verify write permission in project root.

## Quick Start (1-3 Commands)

1. `bash scripts/bootstrap_env.sh`
2. `source <path printed by bootstrap_env.sh>`
3. `python scripts/smoke_test.py --mode mock`
