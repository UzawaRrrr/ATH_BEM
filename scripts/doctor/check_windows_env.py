from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
APP_ROOT = REPO_ROOT / "ath-2025-06"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ath_gui.domain.runtime import RUNTIME_LAYOUT  # noqa: E402


WINDOWS_MODULES = ("numpy", "scipy", "meshio", "matplotlib", "vtk", "gmsh", "optuna")


def _module_presence(names: tuple[str, ...]) -> dict[str, bool]:
    return {name: importlib.util.find_spec(name) is not None for name in names}


def build_report(*, run_self_test: bool = False) -> dict[str, Any]:
    modules = _module_presence(WINDOWS_MODULES)
    self_test = {"requested": run_self_test, "ok": None, "returncode": None}
    if run_self_test:
        result = subprocess.run(
            [sys.executable, str(APP_ROOT / "ath_config_gui.py"), "--self-test"],
            capture_output=True,
            text=True,
            check=False,
        )
        self_test = {
            "requested": True,
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    ok = all(modules.values()) and bool(RUNTIME_LAYOUT.ath_exe.exists())
    if run_self_test:
        ok = ok and bool(self_test["ok"])
    return {
        "python": sys.executable,
        "repo_root": str(REPO_ROOT),
        "ath_exe": str(RUNTIME_LAYOUT.ath_exe),
        "ath_exe_exists": RUNTIME_LAYOUT.ath_exe.exists(),
        "env_file_path": str(RUNTIME_LAYOUT.env_file_path),
        "env_file_exists": RUNTIME_LAYOUT.env_file_exists,
        "toolchain_config_path": str(RUNTIME_LAYOUT.toolchain_config_path),
        "toolchain_config_exists": RUNTIME_LAYOUT.toolchain_config_exists,
        "workspace_root": str(RUNTIME_LAYOUT.workspace_root),
        "modules": modules,
        "self_test": self_test,
        "ok": ok,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the Windows-side ATH_BEM environment.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a human report.")
    parser.add_argument("--run-self-test", action="store_true", help="Run ath_config_gui.py --self-test as part of the check.")
    args = parser.parse_args(argv)

    report = build_report(run_self_test=args.run_self_test)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print("Windows Environment Doctor")
        print(f"Python: {report['python']}")
        print(f"ATH executable: {'OK' if report['ath_exe_exists'] else 'MISSING'}  {report['ath_exe']}")
        print(f".env: {'OK' if report['env_file_exists'] else 'MISSING'}  {report['env_file_path']}")
        print(f"Toolchain config: {'OK' if report['toolchain_config_exists'] else 'MISSING'}  {report['toolchain_config_path']}")
        print(f"Workspace root: {report['workspace_root']}")
        print("Modules:")
        for name, ok in dict(report["modules"]).items():
            print(f"  - {name}: {'OK' if ok else 'MISSING'}")
        if args.run_self_test:
            info = dict(report["self_test"])
            print(f"Self-test: {'OK' if info.get('ok') else 'FAILED'}")
            if info.get("stderr"):
                print(info["stderr"])
    return 0 if bool(report["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
