from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _resolve_app_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "ath_gui").exists() and (candidate / "ath_config_gui.py").exists():
            return candidate
    return here.parents[2]


APP_ROOT = _resolve_app_root()
REPO_ROOT = APP_ROOT.parent
DEFAULT_ENV_FILE_PATH = REPO_ROOT / ".env"
DEFAULT_TOOLCHAIN_CONFIG_PATH = REPO_ROOT / "config" / "toolchain.local.json"
LEGACY_MACHINE_CONFIG_PATH = REPO_ROOT / "config" / "machine.local.json"


def _coerce_path(raw: object, *, base_dir: Path) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    expanded = Path(text).expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (base_dir / expanded).resolve()


def _load_machine_config(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"{path}: {exc}"
    if isinstance(payload, dict):
        return payload, ""
    return {}, f"{path}: expected a JSON object at the top level."


def _load_env_file(path: Path) -> tuple[dict[str, str], str]:
    if not path.exists():
        return {}, ""
    values: dict[str, str] = {}
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                values[key] = value
    except Exception as exc:
        return {}, f"{path}: {exc}"
    return values, ""


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _env_lookup(dotenv: dict[str, str], *keys: str) -> str:
    for key in keys:
        text = str(os.environ.get(key, "")).strip()
        if text:
            return text
        file_value = str(dotenv.get(key, "")).strip()
        if file_value:
            return file_value
    return ""


def _default_data_root() -> Path:
    local_app_data = str(os.environ.get("LOCALAPPDATA", "")).strip()
    if local_app_data:
        return (Path(local_app_data).expanduser() / "ATH_BEM").resolve()

    xdg_data_home = str(os.environ.get("XDG_DATA_HOME", "")).strip()
    if xdg_data_home:
        return (Path(xdg_data_home).expanduser() / "ath_bem").resolve()

    home = Path.home().expanduser()
    if os.name == "nt":
        return (home / "AppData" / "Local" / "ATH_BEM").resolve()
    return (home / ".local" / "share" / "ath_bem").resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class RuntimeLayout:
    repo_root: Path
    app_root: Path
    data_root: Path
    env_file_path: Path
    env_file_exists: bool
    env_file_error: str
    toolchain_config_path: Path
    toolchain_config_exists: bool
    toolchain_config_error: str
    toolchain_config_kind: str
    windows_venv: Path | None
    ath_exe: Path
    ath_runtime_dir: Path
    ath_global_config: Path
    workspace_root: Path
    projects_root: Path
    studies_root: Path
    logs_root: Path
    temp_root: Path
    workspace_inside_repo: bool
    default_wsl_venv: str
    default_wsl_solver_entry: str
    default_python_exe: str


def resolve_runtime_layout() -> RuntimeLayout:
    env_file_path = _coerce_path(os.environ.get("ATH_ENV_FILE"), base_dir=REPO_ROOT) or DEFAULT_ENV_FILE_PATH
    dotenv, env_file_error = _load_env_file(env_file_path)

    explicit_config = _coerce_path(
        _env_lookup(dotenv, "ATH_TOOLCHAIN_CONFIG", "ATH_MACHINE_CONFIG"),
        base_dir=REPO_ROOT,
    )
    if explicit_config is not None:
        config_path = explicit_config
        config_kind = "explicit"
    elif DEFAULT_TOOLCHAIN_CONFIG_PATH.exists():
        config_path = DEFAULT_TOOLCHAIN_CONFIG_PATH
        config_kind = "toolchain_local"
    elif LEGACY_MACHINE_CONFIG_PATH.exists():
        config_path = LEGACY_MACHINE_CONFIG_PATH
        config_kind = "legacy_machine_local"
    else:
        config_path = DEFAULT_TOOLCHAIN_CONFIG_PATH
        config_kind = "default_missing"

    machine_config, machine_config_error = _load_machine_config(config_path)

    windows_venv = (
        _coerce_path(_env_lookup(dotenv, "ATH_WINDOWS_VENV"), base_dir=REPO_ROOT)
        or _coerce_path(machine_config.get("windows_venv"), base_dir=REPO_ROOT)
        or ((REPO_ROOT / ".venv").resolve() if (REPO_ROOT / ".venv").exists() else None)
    )
    default_python_path = (
        _coerce_path(_env_lookup(dotenv, "ATH_PYTHON"), base_dir=REPO_ROOT)
        or _coerce_path(machine_config.get("python_exe"), base_dir=REPO_ROOT)
        or ((windows_venv / "Scripts" / "python.exe").resolve() if windows_venv is not None else None)
    )

    ath_exe = (
        _coerce_path(_env_lookup(dotenv, "ATH_EXE"), base_dir=REPO_ROOT)
        or _coerce_path(machine_config.get("ath_exe"), base_dir=REPO_ROOT)
        or (APP_ROOT / "ath.exe").resolve()
    )
    ath_runtime_dir = (
        _coerce_path(_env_lookup(dotenv, "ATH_RUNTIME_DIR"), base_dir=REPO_ROOT)
        or _coerce_path(machine_config.get("ath_runtime_dir"), base_dir=REPO_ROOT)
        or ath_exe.parent.resolve()
    )
    ath_global_config = (
        _coerce_path(_env_lookup(dotenv, "ATH_GLOBAL_CONFIG"), base_dir=REPO_ROOT)
        or _coerce_path(machine_config.get("ath_global_config"), base_dir=REPO_ROOT)
        or (ath_runtime_dir / "ath.cfg").resolve()
    )
    data_root = _default_data_root()
    workspace_root = (
        _coerce_path(_env_lookup(dotenv, "ATH_WORKSPACE_ROOT"), base_dir=REPO_ROOT)
        or _coerce_path(machine_config.get("workspace_root"), base_dir=REPO_ROOT)
        or (data_root / "workspace").resolve()
    )
    projects_root = (workspace_root / "projects").resolve()
    studies_root = (workspace_root / "studies").resolve()
    logs_root = (
        _coerce_path(_env_lookup(dotenv, "ATH_LOGS_ROOT"), base_dir=REPO_ROOT)
        or _coerce_path(machine_config.get("logs_root"), base_dir=REPO_ROOT)
        or (workspace_root / "logs").resolve()
    )
    temp_root = (
        _coerce_path(_env_lookup(dotenv, "ATH_TEMP_ROOT"), base_dir=REPO_ROOT)
        or _coerce_path(machine_config.get("temp_root"), base_dir=REPO_ROOT)
        or (workspace_root / "temp").resolve()
    )

    default_wsl_venv = (
        _first_text(
            _env_lookup(dotenv, "ATH_WSL_VENV"),
            machine_config.get("wsl_venv"),
        )
        or "~/venvs/bempp-wsl"
    )
    default_wsl_solver_entry = (
        _first_text(
            _env_lookup(dotenv, "ATH_SOLVER_PATH", "ATH_WSL_SOLVER_ENTRY"),
            machine_config.get("solver_path"),
            machine_config.get("wsl_solver_entry"),
        )
        or ""
    )
    default_python_exe = str(default_python_path or "")
    workspace_inside_repo = _is_relative_to(workspace_root, REPO_ROOT)

    return RuntimeLayout(
        repo_root=REPO_ROOT,
        app_root=APP_ROOT,
        data_root=data_root,
        env_file_path=env_file_path,
        env_file_exists=env_file_path.exists(),
        env_file_error=env_file_error,
        toolchain_config_path=config_path,
        toolchain_config_exists=config_path.exists(),
        toolchain_config_error=machine_config_error,
        toolchain_config_kind=config_kind,
        windows_venv=windows_venv,
        ath_exe=ath_exe,
        ath_runtime_dir=ath_runtime_dir,
        ath_global_config=ath_global_config,
        workspace_root=workspace_root,
        projects_root=projects_root,
        studies_root=studies_root,
        logs_root=logs_root,
        temp_root=temp_root,
        workspace_inside_repo=workspace_inside_repo,
        default_wsl_venv=default_wsl_venv,
        default_wsl_solver_entry=default_wsl_solver_entry,
        default_python_exe=default_python_exe,
    )


RUNTIME_LAYOUT = resolve_runtime_layout()
