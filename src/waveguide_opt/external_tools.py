from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:\\")


def is_wsl() -> bool:
    return "microsoft" in platform.release().lower() or bool(os.environ.get("WSL_DISTRO_NAME"))


def is_windows() -> bool:
    return os.name == "nt"


def _convert_with_wslpath(raw: str, to_windows: bool) -> str:
    mode = "-w" if to_windows else "-u"
    try:
        result = subprocess.run(
            ["wslpath", mode, raw],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return raw
    if result.returncode != 0:
        return raw
    return result.stdout.strip() or raw


def is_wsl_available() -> bool:
    if not is_windows():
        return False
    return shutil.which("wsl.exe") is not None


def _convert_with_wsl_exe(raw: str, to_windows: bool) -> str:
    if not is_wsl_available():
        return raw
    mode = "-w" if to_windows else "-u"
    try:
        result = subprocess.run(
            ["wsl.exe", "-e", "wslpath", mode, raw],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except subprocess.TimeoutExpired:
        return raw
    if result.returncode != 0:
        return raw
    return result.stdout.strip() or raw


def normalize_executable_path(raw: str) -> str:
    candidate = raw.strip()
    if not candidate:
        return candidate
    if is_wsl() and WINDOWS_DRIVE_PATTERN.match(candidate):
        return _convert_with_wslpath(candidate, to_windows=False)
    if is_windows() and candidate.startswith("/mnt/"):
        return _convert_with_wslpath(candidate, to_windows=True)
    return candidate


def windows_path_to_wsl(raw: str | Path) -> str:
    token = str(raw)
    if WINDOWS_DRIVE_PATTERN.match(token):
        return _convert_with_wsl_exe(token, to_windows=False)
    return token


def wsl_path_to_windows(raw: str | Path) -> str:
    token = str(raw)
    if token.startswith("/mnt/"):
        return _convert_with_wsl_exe(token, to_windows=True)
    return token


def resolve_executable(configured: str, fallback_names: Sequence[str]) -> str | None:
    if configured:
        normalized = normalize_executable_path(configured)
        path_candidate = Path(normalized)
        if path_candidate.exists():
            return str(path_candidate)
        located = shutil.which(normalized)
        if located:
            return located

    for item in fallback_names:
        located = shutil.which(item)
        if located:
            return located
    return None


def run_wsl_command(
    command: Sequence[str],
    timeout_seconds: int,
    distro: str = "",
) -> subprocess.CompletedProcess[str]:
    if not is_wsl_available():
        raise RuntimeError("wsl.exe is not available on this system.")
    wsl_cmd: list[str] = ["wsl.exe"]
    if distro.strip():
        wsl_cmd.extend(["-d", distro.strip()])
    wsl_cmd.extend(["-e"])
    wsl_cmd.extend([str(part) for part in command])
    return subprocess.run(
        wsl_cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def wsl_file_readable(path_in_wsl: str, timeout_seconds: int, distro: str = "") -> bool:
    try:
        result = run_wsl_command(
            command=["test", "-r", path_in_wsl],
            timeout_seconds=timeout_seconds,
            distro=distro,
        )
    except RuntimeError:
        return False
    return result.returncode == 0


def run_command(
    command: Sequence[str],
    timeout_seconds: int,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in command],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        cwd=str(cwd) if cwd else None,
    )
