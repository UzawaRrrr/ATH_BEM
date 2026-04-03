"""Windows-to-WSL launch helpers for the external Bempp solver."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from ..domain.specs import ROOT_DIR
from ..domain.runtime import RUNTIME_LAYOUT


DEFAULT_WSL_VENV = RUNTIME_LAYOUT.default_wsl_venv
DEFAULT_WSL_SOLVER_ROOT = "~/bem_solver"
DEFAULT_WSL_SOLVER_ENTRY = RUNTIME_LAYOUT.default_wsl_solver_entry


@dataclass
class BemLaunch:
    process: subprocess.Popen[str]
    log_stream: TextIO
    bash_command: str


def windows_path_to_wsl(path: str | Path) -> str:
    text = str(Path(path))
    if len(text) >= 2 and text[1] == ":":
        drive = text[0].lower()
        suffix = text[2:].replace("\\", "/").lstrip("/")
        return f"/mnt/{drive}/{suffix}"
    return text.replace("\\", "/")


def expand_wsl_user_path(path: str) -> str:
    """Expand a user-relative WSL path into a shell-safe HOME-based path.

    We use `${HOME}` instead of `~` because the final command is quoted with
    `shlex.quote()`, and quoted tildes do not expand in bash.
    """
    text = str(path).strip()
    if text == "~":
        return "${HOME}"
    if text.startswith("~/"):
        return "${HOME}/" + text[2:]
    return text


def quote_bash_path(path: str) -> str:
    """Quote a bash path while still allowing `${HOME}` expansion."""
    text = str(path)
    if "${HOME}" in text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return shlex.quote(text)


def resolve_wsl_executable() -> str:
    """Resolve `wsl.exe` to a stable absolute path when available."""
    discovered = shutil.which("wsl.exe")
    if discovered:
        return discovered
    fallback = Path(r"C:\Windows\System32\wsl.exe")
    return str(fallback) if fallback.exists() else "wsl.exe"


def build_bem_solver_command(
    job_file_wsl: str,
    *,
    wsl_venv: str = DEFAULT_WSL_VENV,
    wsl_solver_root: str = DEFAULT_WSL_SOLVER_ROOT,
    wsl_solver_entry: str = DEFAULT_WSL_SOLVER_ENTRY,
    repo_solver_dir: Path | None = None,
) -> str:
    solver_dir = repo_solver_dir or (ROOT_DIR / "bem_solver")
    if not solver_dir.exists():
        raise FileNotFoundError(
            f"BEM solver directory not found: {solver_dir}\n"
            f"Resolved ROOT_DIR={ROOT_DIR}. Please verify project layout."
        )
    solver_dir_wsl = windows_path_to_wsl(solver_dir.resolve())
    repo_solver_entry = f"{solver_dir_wsl}/solver_cli.py"
    # Keep backward compatibility: caller can still override a custom WSL entry.
    if str(wsl_solver_entry).strip() and str(wsl_solver_entry).strip() != DEFAULT_WSL_SOLVER_ENTRY:
        solver_entry = expand_wsl_user_path(wsl_solver_entry)
    else:
        solver_entry = repo_solver_entry

    # Preserve old argument for compatibility even though sync is removed.
    _ = wsl_solver_root
    venv_root = expand_wsl_user_path(wsl_venv)
    venv_python = f"{venv_root}/bin/python"
    solver_entry_q = quote_bash_path(solver_entry)
    job_q = shlex.quote(job_file_wsl)
    venv_python_q = quote_bash_path(venv_python)

    run_command = f"{venv_python_q} {solver_entry_q} {job_q}"
    return f"set -euo pipefail && {run_command}"


def start_bem_solver(
    job_file: Path,
    log_file: Path,
    *,
    backend: str = "wsl",
    wsl_venv: str = DEFAULT_WSL_VENV,
    wsl_solver_root: str = DEFAULT_WSL_SOLVER_ROOT,
    wsl_solver_entry: str = DEFAULT_WSL_SOLVER_ENTRY,
    local_python_exe: str = "",
    conda_exe: str = "conda",
    conda_env: str = "bempp",
) -> BemLaunch:
    solver_entry = (ROOT_DIR / "bem_solver" / "solver_cli.py").resolve()
    if not solver_entry.exists():
        raise FileNotFoundError(f"BEM solver entry not found: {solver_entry}")

    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_stream = log_file.open("w", encoding="utf-8", newline="\n")
    normalized_backend = str(backend).strip().lower() or "wsl"
    if normalized_backend == "wsl":
        job_file_wsl = windows_path_to_wsl(job_file.resolve())
        command_text = build_bem_solver_command(
            job_file_wsl,
            wsl_venv=wsl_venv,
            wsl_solver_root=wsl_solver_root,
            wsl_solver_entry=wsl_solver_entry,
        )
        process = subprocess.Popen(
            [resolve_wsl_executable(), "bash", "-lc", command_text],
            cwd=str(ROOT_DIR),
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return BemLaunch(process=process, log_stream=log_stream, bash_command=command_text)

    if normalized_backend == "local_python":
        command = [
            str(local_python_exe).strip() or sys.executable,
            str(solver_entry),
            str(job_file.resolve()),
        ]
        process = subprocess.Popen(
            command,
            cwd=str(ROOT_DIR),
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return BemLaunch(process=process, log_stream=log_stream, bash_command=" ".join(shlex.quote(part) for part in command))

    if normalized_backend == "conda":
        command = [
            str(conda_exe).strip() or "conda",
            "run",
            "-n",
            str(conda_env).strip() or "bempp",
            "python",
            str(solver_entry),
            str(job_file.resolve()),
        ]
        process = subprocess.Popen(
            command,
            cwd=str(ROOT_DIR),
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return BemLaunch(process=process, log_stream=log_stream, bash_command=" ".join(shlex.quote(part) for part in command))

    raise ValueError(f"Unsupported BEM backend: {backend}")
