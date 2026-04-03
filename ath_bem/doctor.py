from __future__ import annotations

import argparse
from importlib import import_module

from ._pathing import ensure_app_root_on_path


def _dispatch(command: str, argv: list[str] | None = None) -> int:
    if command == "runtime":
        module = import_module("scripts.doctor.doctor_runtime")
        return int(module.main(argv or []))
    if command == "windows":
        module = import_module("scripts.doctor.check_windows_env")
        return int(module.main(argv))
    if command == "wsl":
        module = import_module("scripts.doctor.check_wsl_env")
        return int(module.main(argv))
    if command == "optimizer":
        ensure_app_root_on_path()
        module = import_module("optimizer.env_doctor")
        return int(module.main(argv))
    raise ValueError(f"Unsupported doctor command: {command}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ATH_BEM doctor checks from the repo root.")
    parser.add_argument(
        "tool",
        choices=("runtime", "windows", "wsl", "optimizer"),
        help="Doctor tool to execute.",
    )
    args, forwarded = parser.parse_known_args(argv)
    return _dispatch(args.tool, forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
