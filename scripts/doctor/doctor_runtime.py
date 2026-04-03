from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
APP_ROOT = REPO_ROOT / "ath-2025-06"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ath_gui.domain.runtime import RUNTIME_LAYOUT  # noqa: E402


def _build_warnings(report: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    if not bool(report["ath_exe_exists"]):
        warnings.append("`ath.exe` was not found at the resolved path.")
    if not bool(report["toolchain_config_exists"]):
        warnings.append("Local toolchain config is missing; repo-safe defaults are in use.")
    if str(report["toolchain_config_kind"]) == "legacy_machine_local":
        warnings.append("Runtime is using legacy `config/machine.local.json`; prefer `config/toolchain.local.json`.")
    if bool(report["workspace_inside_repo"]):
        warnings.append("`workspace_root` currently points inside the repo; outputs may pollute the source tree.")
    if not bool(report["env_file_exists"]):
        warnings.append("`.env` is missing; only OS env vars, local JSON, and built-in defaults will apply.")
    return warnings


def _build_suggestions(report: dict[str, object]) -> list[str]:
    suggestions: list[str] = []
    if not bool(report["toolchain_config_exists"]) and not bool(report["env_file_exists"]):
        suggestions.append("Run `pwsh ./scripts/bootstrap/bootstrap_windows.ps1 -InitLocalConfig` to create local templates.")
    if not bool(report["workspace_root_exists"]):
        suggestions.append("The external workspace has not been created yet; it will be materialized on first run.")
    if bool(report["workspace_inside_repo"]):
        suggestions.append("Move `workspace_root` to `%LOCALAPPDATA%/ATH_BEM/workspace` or another external writable path.")
    return suggestions


def build_report() -> dict[str, object]:
    repo_entries = sorted(path.name for path in REPO_ROOT.iterdir() if path.name != ".git")
    report: dict[str, object] = {
        "repo_root": str(RUNTIME_LAYOUT.repo_root),
        "app_root": str(RUNTIME_LAYOUT.app_root),
        "data_root": str(RUNTIME_LAYOUT.data_root),
        "env_file_path": str(RUNTIME_LAYOUT.env_file_path),
        "env_file_exists": RUNTIME_LAYOUT.env_file_exists,
        "env_file_error": RUNTIME_LAYOUT.env_file_error,
        "toolchain_config_path": str(RUNTIME_LAYOUT.toolchain_config_path),
        "toolchain_config_exists": RUNTIME_LAYOUT.toolchain_config_exists,
        "toolchain_config_error": RUNTIME_LAYOUT.toolchain_config_error,
        "toolchain_config_kind": RUNTIME_LAYOUT.toolchain_config_kind,
        "windows_venv": str(RUNTIME_LAYOUT.windows_venv) if RUNTIME_LAYOUT.windows_venv is not None else "",
        "default_python_exe": RUNTIME_LAYOUT.default_python_exe,
        "ath_exe": str(RUNTIME_LAYOUT.ath_exe),
        "ath_exe_exists": RUNTIME_LAYOUT.ath_exe.exists(),
        "ath_runtime_dir": str(RUNTIME_LAYOUT.ath_runtime_dir),
        "ath_global_config": str(RUNTIME_LAYOUT.ath_global_config),
        "workspace_root": str(RUNTIME_LAYOUT.workspace_root),
        "workspace_root_exists": RUNTIME_LAYOUT.workspace_root.exists(),
        "projects_root": str(RUNTIME_LAYOUT.projects_root),
        "studies_root": str(RUNTIME_LAYOUT.studies_root),
        "logs_root": str(RUNTIME_LAYOUT.logs_root),
        "temp_root": str(RUNTIME_LAYOUT.temp_root),
        "workspace_inside_repo": RUNTIME_LAYOUT.workspace_inside_repo,
        "default_wsl_venv": RUNTIME_LAYOUT.default_wsl_venv,
        "default_wsl_solver_entry": RUNTIME_LAYOUT.default_wsl_solver_entry,
        "repo_entries": repo_entries,
    }
    report["warnings"] = _build_warnings(report)
    report["suggestions"] = _build_suggestions(report)
    return report


def _print_human_report(report: dict[str, object]) -> None:
    print("Runtime Layout Doctor")
    print(f"Repo root: {report['repo_root']}")
    print(f"App root: {report['app_root']}")
    print(f"Data root: {report['data_root']}")
    print(f"ATH executable: {'OK' if report['ath_exe_exists'] else 'MISSING'}  {report['ath_exe']}")
    print(f"Toolchain config: {'OK' if report['toolchain_config_exists'] else 'MISSING'}  {report['toolchain_config_path']}")
    print(f"Toolchain config kind: {report['toolchain_config_kind']}")
    print(f".env: {'OK' if report['env_file_exists'] else 'MISSING'}  {report['env_file_path']}")
    print(f"Workspace root: {report['workspace_root']}")
    print(f"Projects root: {report['projects_root']}")
    print(f"Studies root: {report['studies_root']}")
    print(f"Logs root: {report['logs_root']}")
    print(f"Temp root: {report['temp_root']}")
    print(f"Workspace inside repo: {report['workspace_inside_repo']}")
    print(f"Default Windows Python: {report['default_python_exe']}")
    print(f"Default WSL venv: {report['default_wsl_venv']}")
    warnings = list(report.get("warnings", []))
    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"  - {item}")
    suggestions = list(report.get("suggestions", []))
    if suggestions:
        print("Suggestions:")
        for item in suggestions:
            print(f"  - {item}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect resolved runtime/layout paths for ATH_BEM.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of a human report.")
    args = parser.parse_args(argv)

    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        _print_human_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
