"""Windows-to-WSL launch helpers for the external Bempp solver."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .specs import ROOT_DIR


DEFAULT_WSL_VENV = "~/venvs/bempp-wsl"
DEFAULT_WSL_SOLVER_ROOT = "~/bem_solver"
DEFAULT_WSL_SOLVER_ENTRY = "~/bem_solver/solver_cli.py"


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


def build_bem_solver_command(
    job_file_wsl: str,
    *,
    wsl_venv: str = DEFAULT_WSL_VENV,
    wsl_solver_root: str = DEFAULT_WSL_SOLVER_ROOT,
    wsl_solver_entry: str = DEFAULT_WSL_SOLVER_ENTRY,
    repo_solver_dir: Path | None = None,
) -> str:
    solver_dir = repo_solver_dir or (ROOT_DIR / "bem_solver")
    solver_dir_wsl = windows_path_to_wsl(solver_dir.resolve())
    solver_root = expand_wsl_user_path(wsl_solver_root)
    solver_entry = expand_wsl_user_path(wsl_solver_entry)
    venv_root = expand_wsl_user_path(wsl_venv)
    venv_python = f"{venv_root}/bin/python"
    solver_root_q = quote_bash_path(solver_root)
    solver_entry_q = quote_bash_path(solver_entry)
    job_q = shlex.quote(job_file_wsl)
    venv_python_q = quote_bash_path(venv_python)

    sync_command = f"mkdir -p {solver_root_q} && cp -r {shlex.quote(solver_dir_wsl)}/. {solver_root_q}/"
    run_command = f"{venv_python_q} {solver_entry_q} {job_q}"
    return f"set -euo pipefail && {sync_command} && {run_command}"


def start_bem_solver(
    job_file: Path,
    log_file: Path,
    *,
    wsl_venv: str = DEFAULT_WSL_VENV,
    wsl_solver_root: str = DEFAULT_WSL_SOLVER_ROOT,
    wsl_solver_entry: str = DEFAULT_WSL_SOLVER_ENTRY,
) -> BemLaunch:
    job_file_wsl = windows_path_to_wsl(job_file.resolve())
    bash_command = build_bem_solver_command(
        job_file_wsl,
        wsl_venv=wsl_venv,
        wsl_solver_root=wsl_solver_root,
        wsl_solver_entry=wsl_solver_entry,
    )

    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_stream = log_file.open("w", encoding="utf-8", newline="\n")
    process = subprocess.Popen(
        ["wsl.exe", "bash", "-lc", bash_command],
        cwd=str(ROOT_DIR),
        stdout=log_stream,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return BemLaunch(process=process, log_stream=log_stream, bash_command=bash_command)
