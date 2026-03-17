#!/usr/bin/env python
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from waveguide_opt.configuration import load_config
from waveguide_opt.external_tools import (
    is_windows,
    is_wsl_available,
    resolve_executable,
    run_wsl_command,
    windows_path_to_wsl,
    wsl_file_readable,
)
from waveguide_opt.utils import ensure_directories


def check_import(module_name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module_name)
        return True, "ok"
    except Exception as exc:  # pragma: no cover - defensive path
        return False, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Python and external dependencies.")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "local_paths.yaml")
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    args = parser.parse_args()

    config = load_config(args.config)

    required_modules = ["yaml", "tqdm"]
    optional_modules = [
        "numpy",
        "scipy",
        "pandas",
        "matplotlib",
        "shapely",
        "meshio",
        "numba",
        "psutil",
        "sklearn",
        "pyvista",
        "PySide6",
        "gmsh",
        "bempp.api",
        "bempp_cl.api",
    ]

    failures: list[str] = []
    print("== Python Modules ==")
    for module in required_modules:
        ok, detail = check_import(module)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] required module: {module}")
        if not ok:
            print(f"       detail: {detail}")
            failures.append(f"required module missing: {module}")

    print("\n== Optional Modules ==")
    for module in optional_modules:
        ok, detail = check_import(module)
        status = "PASS" if ok else "WARN"
        print(f"[{status}] optional module: {module}")
        if not ok:
            print(f"       detail: {detail}")

    print("\n== Executables ==")
    gmsh_exec = resolve_executable(config.paths.gmsh_executable, ["gmsh"])
    ath_exec = resolve_executable(config.paths.ath_executable, ["ath"])
    gmsh_ok = gmsh_exec is not None
    ath_ok = ath_exec is not None

    print(f"[{'PASS' if gmsh_ok else 'FAIL'}] gmsh executable: {gmsh_exec or 'not found'}")
    if args.mode == "real" and not gmsh_ok:
        failures.append("gmsh executable missing in real mode")

    ath_status = "PASS" if ath_ok else ("FAIL" if args.mode == "real" else "WARN")
    print(f"[{ath_status}] ath executable: {ath_exec or 'not found'}")
    if args.mode == "real" and not ath_ok:
        failures.append("ath executable missing in real mode")
    if ath_ok:
        ath_cfg = Path(ath_exec).resolve().parent / "ath.cfg"
        cfg_ok = ath_cfg.exists()
        cfg_status = "PASS" if cfg_ok else ("FAIL" if args.mode == "real" else "WARN")
        print(f"[{cfg_status}] ath cfg: {ath_cfg if cfg_ok else 'not found near executable'}")
        if args.mode == "real" and not cfg_ok:
            failures.append("ath.cfg missing near ath executable")

    print("\n== Directories ==")
    required_dirs = [
        config.paths.logs_directory,
        config.paths.outputs_directory,
        config.paths.mesh_output_directory,
        config.paths.solver_output_directory,
        config.paths.temp_directory,
    ]
    ensure_directories(required_dirs)
    for directory in required_dirs:
        writable = directory.exists() and os_access_write(directory)
        status = "PASS" if writable else "FAIL"
        print(f"[{status}] writable dir: {directory}")
        if not writable:
            failures.append(f"directory not writable: {directory}")

    print("\n== Local Databases ==")
    tritonia_index = ROOT / "config" / "ath_database" / "tritonia" / "index.yaml"
    tritonia_status = "PASS" if tritonia_index.exists() else "WARN"
    print(f"[{tritonia_status}] Tritonia cfg index: {tritonia_index if tritonia_index.exists() else 'missing'}")
    if config.runtime.coverage_target_path:
        target_file = Path(config.runtime.coverage_target_path)
        target_ok = target_file.exists()
        target_status = "PASS" if target_ok else ("FAIL" if args.mode == "real" else "WARN")
        print(f"[{target_status}] coverage target file: {target_file if target_ok else 'missing'}")
        if args.mode == "real" and not target_ok:
            failures.append("configured coverage_target_path does not exist")
    if config.runtime.ga_parameters_path:
        ga_file = Path(config.runtime.ga_parameters_path)
        ga_ok = ga_file.exists()
        ga_status = "PASS" if ga_ok else ("WARN" if args.mode == "mock" else "FAIL")
        print(f"[{ga_status}] geometry/GA parameters file: {ga_file if ga_ok else 'missing'}")
        if args.mode == "real" and not ga_ok:
            failures.append("configured ga_parameters_path does not exist")

    if args.mode == "real":
        bempp_ok, bempp_detail = check_import("bempp.api")
        bempp_cl_ok, bempp_cl_detail = check_import("bempp_cl.api")
        if bempp_ok or bempp_cl_ok:
            backend = "bempp.api" if bempp_ok else "bempp_cl.api"
            print(f"[PASS] real solver backend: {backend}")
        else:
            print("[FAIL] real solver backend: bempp.api / bempp_cl.api")
            print(f"       bempp.api detail: {bempp_detail}")
            print(f"       bempp_cl.api detail: {bempp_cl_detail}")
            failures.append("bempp backend missing in real mode")

        if config.runtime.solver_prefer_wsl and is_windows():
            print("\n== WSL Solver Path ==")
            if not is_wsl_available():
                print("[FAIL] wsl.exe not available")
                failures.append("wsl.exe missing while solver_prefer_wsl=true")
            else:
                print("[PASS] wsl.exe available")
                wsl_python = config.runtime.wsl_python_executable.strip() or ".venv_wsl/bin/python"
                if not wsl_python.startswith("/"):
                    wsl_python = windows_path_to_wsl((config.paths.working_directory / wsl_python).resolve())
                py_check = run_wsl_command(
                    [wsl_python, "--version"],
                    timeout_seconds=config.runtime.timeout_seconds,
                    distro=config.runtime.wsl_distro,
                )
                if py_check.returncode == 0:
                    print(f"[PASS] WSL python: {wsl_python}")
                else:
                    print(f"[FAIL] WSL python: {wsl_python}")
                    print(f"       detail: {py_check.stderr.strip() or py_check.stdout.strip()}")
                    failures.append("WSL python executable check failed")

                bempp_check = run_wsl_command(
                    [wsl_python, "-c", "import bempp_cl.api; print('ok')"],
                    timeout_seconds=config.runtime.timeout_seconds,
                    distro=config.runtime.wsl_distro,
                )
                if bempp_check.returncode == 0:
                    print("[PASS] WSL bempp_cl.api import")
                else:
                    print("[WARN] WSL bempp_cl.api import")
                    print(f"       detail: {bempp_check.stderr.strip() or bempp_check.stdout.strip()}")

                mesh_dir_wsl = windows_path_to_wsl(config.paths.mesh_output_directory.resolve())
                readable = wsl_file_readable(
                    path_in_wsl=mesh_dir_wsl,
                    timeout_seconds=config.runtime.timeout_seconds,
                    distro=config.runtime.wsl_distro,
                )
                print(f"[{'PASS' if readable else 'WARN'}] WSL readable mesh dir: {mesh_dir_wsl}")

    if failures:
        print("\nOverall: FAIL")
        for issue in failures:
            print(f"- {issue}")
        return 1

    print("\nOverall: PASS")
    return 0


def os_access_write(path: Path) -> bool:
    probe = path / ".write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
