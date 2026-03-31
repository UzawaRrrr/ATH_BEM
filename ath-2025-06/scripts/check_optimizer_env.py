"""Environment doctor for the ATH/BEM Optuna optimization workflow."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


THIS_DIR = Path(__file__).resolve().parent
ROOT_DIR = THIS_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ath_gui.domain.specs import ATH_EXE  # noqa: E402
from ath_gui.infrastructure.bem_bridge import DEFAULT_WSL_VENV  # noqa: E402


LOCAL_ORCHESTRATION_MODULES = ("numpy", "optuna", "gmsh")
LOCAL_FULL_SOLVER_MODULES = ("numpy", "scipy", "meshio", "gmsh", "bempp_cl")
WSL_SOLVER_MODULES = ("numpy", "scipy", "meshio", "gmsh", "bempp_cl")


def _module_presence(names: tuple[str, ...]) -> dict[str, bool]:
    """Check which Python modules are importable in the current interpreter."""
    return {name: importlib.util.find_spec(name) is not None for name in names}


def _all_ok(status: dict[str, bool]) -> bool:
    """Return True when every module check succeeded."""
    return all(bool(value) for value in status.values())


def _check_wsl_solver_env(wsl_venv: str) -> dict[str, Any]:
    """Inspect the configured WSL Python environment used by the solver."""
    raw_root = str(wsl_venv).strip()
    if raw_root == "~":
        expanded_root = "${HOME}"
    elif raw_root.startswith("~/"):
        expanded_root = "${HOME}/" + raw_root[2:]
    else:
        expanded_root = raw_root
    python_path = f"{expanded_root.rstrip('/')}/bin/python"
    payload = {
        "available": False,
        "python": python_path,
        "modules": {name: False for name in WSL_SOLVER_MODULES},
        "error": "",
    }
    python_expr = f'"{python_path}"' if "${HOME}" in python_path else shlex.quote(python_path)
    command = (
        "set -e\n"
        f"if [ ! -x {python_expr} ]; then\n"
        '  echo \'{"available": false, "error": "missing_python"}\'\n'
        "  exit 0\n"
        "fi\n"
        f"{python_expr} - <<'PY'\n"
        "import importlib.util\n"
        "import json\n"
        f"mods = {list(WSL_SOLVER_MODULES)!r}\n"
        'print(json.dumps({"available": True, "modules": {name: importlib.util.find_spec(name) is not None for name in mods}}))\n'
        "PY\n"
    )
    try:
        result = subprocess.run(
            ["wsl.exe", "bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        payload["error"] = str(exc)
        return payload

    if result.returncode != 0:
        payload["error"] = (result.stderr or result.stdout or f"return code {result.returncode}").strip()
        return payload

    try:
        parsed = json.loads(result.stdout.strip() or "{}")
    except Exception as exc:
        payload["error"] = f"Invalid JSON from WSL check: {exc}"
        return payload

    payload["available"] = bool(parsed.get("available", False))
    payload["modules"] = {
        name: bool(dict(parsed.get("modules", {})).get(name, False))
        for name in WSL_SOLVER_MODULES
    }
    payload["error"] = str(parsed.get("error", "")).strip()
    return payload


def build_report(wsl_venv: str) -> dict[str, Any]:
    """Collect the local and WSL dependency report used by the doctor CLI."""
    local_orchestration = _module_presence(LOCAL_ORCHESTRATION_MODULES)
    local_full_solver = _module_presence(LOCAL_FULL_SOLVER_MODULES)
    wsl_solver = _check_wsl_solver_env(wsl_venv)

    ath_ok = ATH_EXE.exists()
    local_orchestration_ready = ath_ok and _all_ok(local_orchestration)
    local_full_solver_ready = ath_ok and _all_ok(local_full_solver)
    wsl_solver_ready = bool(wsl_solver.get("available")) and _all_ok(dict(wsl_solver.get("modules", {})))

    if local_orchestration_ready and wsl_solver_ready:
        recommendation = "hybrid"
        reason = "Use the local Windows .venv for ATH/Optuna orchestration, and use the WSL solver venv for Bempp."
    elif local_full_solver_ready:
        recommendation = "local_only"
        reason = "A pure local run is technically possible, but it is still less aligned with the current Windows->WSL architecture."
    elif wsl_solver_ready and not local_orchestration_ready:
        recommendation = "incomplete_local"
        reason = "The WSL solver is ready, but the local orchestration environment is still missing ATH/Optuna requirements."
    else:
        recommendation = "not_ready"
        reason = "Neither the recommended hybrid topology nor a full local solver environment is currently ready."

    return {
        "ath_exe": str(ATH_EXE),
        "ath_exe_exists": ath_ok,
        "local_python": sys.executable,
        "local_orchestration": local_orchestration,
        "local_orchestration_ready": local_orchestration_ready,
        "local_full_solver": local_full_solver,
        "local_full_solver_ready": local_full_solver_ready,
        "wsl_solver": wsl_solver,
        "wsl_solver_ready": wsl_solver_ready,
        "recommended_topology": recommendation,
        "recommendation_reason": reason,
    }


def _print_human_report(report: dict[str, Any]) -> None:
    print("Optimizer Environment Doctor")
    print(f"ATH executable: {'OK' if report['ath_exe_exists'] else 'MISSING'}  {report['ath_exe']}")
    print(f"Local orchestration Python: {report['local_python']}")
    print("Local orchestration modules:")
    for name, ok in dict(report["local_orchestration"]).items():
        print(f"  - {name}: {'OK' if ok else 'MISSING'}")
    print("Local full-solver modules:")
    for name, ok in dict(report["local_full_solver"]).items():
        print(f"  - {name}: {'OK' if ok else 'MISSING'}")

    wsl_solver = dict(report["wsl_solver"])
    print(f"WSL solver Python: {wsl_solver.get('python', '')}")
    if str(wsl_solver.get("error", "")).strip():
        print(f"WSL solver error: {wsl_solver['error']}")
    print("WSL solver modules:")
    for name, ok in dict(wsl_solver.get("modules", {})).items():
        print(f"  - {name}: {'OK' if ok else 'MISSING'}")

    print()
    print(f"Recommended topology: {report['recommended_topology']}")
    print(report["recommendation_reason"])


def main(argv: list[str] | None = None) -> int:
    """Run the environment doctor and print a recommendation."""
    parser = argparse.ArgumentParser(description="Check local/WSL environments for ATH+BEM Optuna runs.")
    parser.add_argument("--wsl-venv", default=DEFAULT_WSL_VENV, help="WSL venv used by the BEM solver.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of a text report.")
    args = parser.parse_args(argv)

    report = build_report(args.wsl_venv)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        _print_human_report(report)

    topology = str(report.get("recommended_topology", "not_ready"))
    return 0 if topology in {"hybrid", "local_only"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
