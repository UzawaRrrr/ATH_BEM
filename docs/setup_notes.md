# Setup Notes

## Environment Detection (this machine)

- OS context used for setup: Windows PowerShell + available WSL
- Python detected: `3.13.12`
- `gmsh`:
  - Windows path found: `C:\Users\UZAWAR\AppData\Local\Microsoft\WinGet\Packages\gmsh.gmsh_Microsoft.Winget.Source_8wekyb3d8bbwe\gmsh-4.13.1-Windows64\gmsh.exe`
  - WSL path found: `/usr/bin/gmsh`
- `ath`:
  - Installed locally from `https://at-horns.eu/release/ath-2025-06.zip`
  - Executable: `tools/ath/ath-2025-06/ath-2025-06/ath.exe`
  - Config file: `tools/ath/ath-2025-06/ath-2025-06/ath.cfg`
- Tritonia ATH configs:
  - Synced from official links under `https://at-horns.eu/ext/`
  - Stored in `config/ath_database/tritonia/` with source index file `index.yaml`
- Python BEM package:
  - `bempp-cl` installed and importable as `bempp_cl.api`

## Design Choices

1. Keep all runtime artifacts local (`logs/`, `outputs/`).
2. Keep dependency footprint small for first successful execution.
3. Separate execution modes:
   - `mock` mode always available locally.
   - `real` mode requires ATH/Gmsh/BEM and fails fast when unavailable.
4. Keep compatibility wrappers for likely legacy import paths.
5. Prefer split real-mode execution on Windows hosts:
   - ATH/Gmsh mesh on Windows side
   - `bempp_cl` solver execution inside WSL via explicit mesh handoff.
6. Desktop GUI is provided via `scripts/run_gui.py` (PySide6), operating through config + script orchestration.
7. GUI persists split config files and run snapshots:
   - `config/local_paths.yaml`
   - `config/geometry_params.yaml`
   - `config/ga_settings.yaml`
   - `config/coverage_target.yaml`
   - `config/solver_settings.yaml`
   - run snapshots under `outputs/runs/<timestamp>_<label>/config/`

## Real-Mode Notes

- `bempp.api` alias is not present, but `bempp_cl.api` is available and used.
- Real mode now attempts actual `bempp_cl` field solve:
  - preferred path: Windows mesh -> WSL bempp runner
  - fallback path: native `bempp_cl` solve
  - emergency fallback: synthetic observation only if BEM solve fails

## Recommended Next Step for Real Mode

1. Set `paths.ath_executable` in `config/local_paths.yaml`.
2. (Optional) set `runtime.coverage_target_path` to a YAML profile, e.g. `config/coverage_target.yaml` (CSV also supported).
3. Verify `python scripts/check_dependencies.py --mode real` passes.
4. Run `python scripts/smoke_test.py --mode real`.
