#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch desktop GUI control panel.")
    parser.add_argument("--check", action="store_true", help="Validate GUI dependencies/config and exit.")
    args = parser.parse_args()

    try:
        import yaml  # noqa: F401
    except Exception as exc:
        print(f"GUI check: FAIL (yaml import) {exc}")
        return 1

    if args.check:
        cfg = ROOT / "config" / "local_paths.yaml"
        geometry = ROOT / "config" / "geometry_params.yaml"
        ga_settings = ROOT / "config" / "ga_settings.yaml"
        coverage = ROOT / "config" / "coverage_target.yaml"
        solver = ROOT / "config" / "solver_settings.yaml"
        print(f"GUI check: local_paths {'ok' if cfg.exists() else 'missing'} -> {cfg}")
        print(f"GUI check: geometry_params {'ok' if geometry.exists() else 'missing'} -> {geometry}")
        print(f"GUI check: ga_settings {'ok' if ga_settings.exists() else 'missing'} -> {ga_settings}")
        print(f"GUI check: coverage_target {'ok' if coverage.exists() else 'missing'} -> {coverage}")
        print(f"GUI check: solver_settings {'ok' if solver.exists() else 'missing'} -> {solver}")
        try:
            import PySide6  # noqa: F401

            print("GUI check: PySide6 ok")
            return 0
        except Exception as exc:
            print(f"GUI check: FAIL (PySide6 import) {exc}")
            return 1

    try:
        from PySide6.QtWidgets import QApplication
    except Exception as exc:
        print(f"Unable to import PySide6: {exc}")
        print("Install with: python -m pip install PySide6")
        return 1

    from waveguide_opt.gui import ControlPanelWindow

    app = QApplication(sys.argv)
    window = ControlPanelWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
