# ATH GUI Layer Layout

This project now reserves explicit folders for layered architecture:

- `presentation/`
  - UI-facing modules (Tk window composition, view widgets, render adapters).
- `application/`
  - Use-case / workflow orchestration.
  - `application/controllers/` now contains the active controllers.
- `domain/`
  - Domain rules, schema, and business logic.
- `infrastructure/`
  - External adapters (filesystem, solver bridge, mesh/result loaders, preview ingestion).

Detailed enforcement and dependency rules live in:

- `LAYER_CONTRACT.md`

## Current migration status

- Active modules are now organized under:
  - `domain/`: `specs.py`, `bem_specs.py`, `config_core.py`, `auto_enclosure.py`
  - `infrastructure/`: `preview_core.py`, `bem_bridge.py`, `bem_mesh.py`, `bem_results.py`, `bem_state.py`
  - `presentation/`: `bem_plot.py`, `widgets.py`, `opengl_preview.py`, `preview_renderer.py`
  - `application/controllers/`: workflow / preview / BEM controllers
- `ath_gui/controllers/` and previous root-level module names are retained as
  compatibility shims so older imports keep working.

## Automated guardrail

- Run `python ath_config_gui.py --check-layering` to detect import-boundary violations.
- `--self-test` also includes layer-boundary checks.
