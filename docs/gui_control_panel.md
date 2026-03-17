# GUI Control Panel

Launch:

```bash
python scripts/run_gui.py
```

Check only:

```bash
python scripts/run_gui.py --check
```

## Tabs (v1)

1. `Environment`
- ATH executable path
- Gmsh path
- WSL distro / command path
- project root
- mesh exchange directory
- outputs directory
- logs directory
- real/mock toggle

2. `Geometry Parameters`
- one row per parameter with:
  - `include_in_ga`
  - `parameter_name`
  - `initial_value`
  - `min_value`
  - `max_value`
  - `mutation_scale`
  - `unit`
  - `notes`

3. `GA Settings`
- population size
- generations
- crossover rate
- mutation rate
- elitism
- random seed
- early stopping
- invalid candidate penalty
- workers

4. `Coverage / Fitness`
- horizontal/vertical coverage
- transition margin
- in-coverage target dB
- out-of-coverage threshold dB
- frequency list / frequency band
- `w_in`, `w_out`, `w_bw`, `w_smooth`, `w_eff`, `w_mfg`

5. `Solver`
- bempp tolerance
- max iterations
- retry policy
- timeout
- warm-up enabled
- failure penalty
- WSL execution toggle
- mesh handoff options

6. `Run / Monitor`
- buttons:
  - check dependencies
  - smoke test
  - minimal optimization
  - full optimization
  - stop current run
- live log output
- current status
- current generation
- current candidate
- best fitness
- best candidate summary

7. `Results`
- latest run summary
- score breakdown
- best parameters
- open output folder
- export config snapshot
- load previous config snapshot

## Config Files Managed

- `config/local_paths.yaml`
- `config/geometry_params.yaml`
- `config/ga_settings.yaml`
- `config/coverage_target.yaml`
- `config/solver_settings.yaml`

Per run, GUI creates reproducible snapshots before execution:

- `outputs/runs/<timestamp>_<run_label>/config/local_paths.yaml`
- `outputs/runs/<timestamp>_<run_label>/config/geometry_params.yaml`
- `outputs/runs/<timestamp>_<run_label>/config/ga_settings.yaml`
- `outputs/runs/<timestamp>_<run_label>/config/coverage_target.yaml`
- `outputs/runs/<timestamp>_<run_label>/config/solver_settings.yaml`

The GUI does not directly call low-level solver internals. It writes config and launches existing script entry points.

## Run Buttons

- Dependency check: `scripts/check_dependencies.py`
- Smoke test: `scripts/smoke_test.py`
- Minimal optimization: `scripts/run_minimal_optimization.py`
- Full optimization: `scripts/run_full_optimization.py`

## Notes

- GUI intentionally avoids heavy 3D rendering in v1.
- WSL split pipeline settings are exposed under solver/handoff controls.
