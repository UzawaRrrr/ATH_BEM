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


WSL_MODULES = ("bempp_cl", "numpy", "scipy", "meshio", "matplotlib", "gmsh")


def _module_presence(names: tuple[str, ...]) -> dict[str, bool]:
    return {name: importlib.util.find_spec(name) is not None for name in names}


def build_report(*, check_solver_cli: bool = False) -> dict[str, Any]:
    modules = _module_presence(WSL_MODULES)
    solver_cli = {"requested": check_solver_cli, "ok": None, "returncode": None}
    if check_solver_cli:
        result = subprocess.run(
            [sys.executable, str(APP_ROOT / "bem_solver" / "solver_cli.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        solver_cli = {
            "requested": True,
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    ok = all(modules.values())
    if check_solver_cli:
        ok = ok and bool(solver_cli["ok"])
    return {
        "python": sys.executable,
        "repo_root": str(REPO_ROOT),
        "solver_cli": solver_cli,
        "modules": modules,
        "ok": ok,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the WSL-side ATH_BEM solver environment.")
    parser.add_argument("--venv", default="", help="Optional venv path for display only.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a human report.")
    parser.add_argument("--check-solver-cli", action="store_true", help="Run bem_solver/solver_cli.py --help.")
    args = parser.parse_args(argv)

    report = build_report(check_solver_cli=args.check_solver_cli)
    if args.venv:
        report["venv"] = str(Path(args.venv).expanduser())

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print("WSL Environment Doctor")
        print(f"Python: {report['python']}")
        if args.venv:
            print(f"Venv: {report['venv']}")
        print("Modules:")
        for name, ok in dict(report["modules"]).items():
            print(f"  - {name}: {'OK' if ok else 'MISSING'}")
        if args.check_solver_cli:
            info = dict(report["solver_cli"])
            print(f"solver_cli --help: {'OK' if info.get('ok') else 'FAILED'}")
            if info.get("stderr"):
                print(info["stderr"])
    return 0 if bool(report["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
