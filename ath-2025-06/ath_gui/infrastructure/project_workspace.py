from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


_RUN_STAMP_FMT = "%Y%m%d_%H%M%S"


def _sanitize_case_name(case_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(case_name).strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "unnamed_case"


@dataclass(frozen=True, slots=True)
class ProjectWorkspace:
    case_name: str
    case_key: str
    run_id: str
    case_root: Path
    run_root: Path
    input_dir: Path
    ath_dir: Path
    bempp_dir: Path
    meta_dir: Path

    @property
    def design_recipe_path(self) -> Path:
        return self.input_dir / "design_recipe.json"

    @property
    def ath_global_cfg_path(self) -> Path:
        return self.input_dir / "ath_global.cfg"

    @property
    def horn_cfg_path(self) -> Path:
        return self.input_dir / "horn.cfg"

    @property
    def group_map_path(self) -> Path:
        return self.input_dir / "group_map.json"

    @property
    def job_path(self) -> Path:
        return self.input_dir / "job.json"

    @property
    def manifest_path(self) -> Path:
        return self.meta_dir / "run_manifest.json"


def _build_workspace(case_name: str, case_key: str, run_root: Path, run_id: str) -> ProjectWorkspace:
    return ProjectWorkspace(
        case_name=case_name,
        case_key=case_key,
        run_id=run_id,
        case_root=run_root.parent,
        run_root=run_root,
        input_dir=run_root / "input",
        ath_dir=run_root / "ath",
        bempp_dir=run_root / "bempp",
        meta_dir=run_root / "meta",
    )


def create_workspace(case_name: str, *, projects_root: Path | None = None, run_id: str | None = None) -> ProjectWorkspace:
    root = (projects_root or (Path(__file__).resolve().parents[2] / "projects")).resolve()
    case_key = _sanitize_case_name(case_name)
    case_root = root / case_key
    runs_root = case_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    rid = (run_id or datetime.now().strftime(_RUN_STAMP_FMT)).strip()
    run_root = runs_root / rid
    suffix = 1
    while run_root.exists():
        run_root = runs_root / f"{rid}_{suffix:02d}"
        suffix += 1

    workspace = _build_workspace(case_name, case_key, run_root, run_root.name)
    for directory in (workspace.input_dir, workspace.ath_dir, workspace.bempp_dir, workspace.meta_dir):
        directory.mkdir(parents=True, exist_ok=True)

    latest_pointer = case_root / "latest_workspace.txt"
    latest_pointer.write_text(str(workspace.run_root), encoding="utf-8", newline="\n")
    return workspace


def load_workspace(path: str | Path) -> ProjectWorkspace:
    run_root = Path(path).resolve()
    if not run_root.exists():
        raise FileNotFoundError(f"Workspace not found: {run_root}")
    case_root = run_root.parent
    case_key = case_root.name
    manifest = run_root / "meta" / "run_manifest.json"
    case_name = case_key
    if manifest.exists():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            case_name = str(payload.get("case_name") or case_key)
        except Exception:
            case_name = case_key

    workspace = _build_workspace(case_name, case_key, run_root, run_root.name)
    for directory in (workspace.input_dir, workspace.ath_dir, workspace.bempp_dir, workspace.meta_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return workspace


def latest_workspace_for_case(case_name: str, *, projects_root: Path | None = None) -> ProjectWorkspace | None:
    root = (projects_root or (Path(__file__).resolve().parents[2] / "projects")).resolve()
    case_key = _sanitize_case_name(case_name)
    case_root = root / case_key
    pointer = case_root / "latest_workspace.txt"
    if pointer.exists():
        raw = pointer.read_text(encoding="utf-8").strip()
        if raw:
            try:
                return load_workspace(raw)
            except Exception:
                pass

    runs_root = case_root / "runs"
    if not runs_root.exists():
        return None
    candidates = [path for path in runs_root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    latest = sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    return load_workspace(latest)


def write_manifest(workspace: ProjectWorkspace, manifest: dict[str, Any]) -> Path:
    payload = dict(manifest)
    payload.setdefault("schema", "ath.workspace_manifest.v1")
    payload.setdefault("case_name", workspace.case_name)
    payload.setdefault("case_key", workspace.case_key)
    payload.setdefault("run_id", workspace.run_id)
    payload.setdefault("workspace", str(workspace.run_root))
    payload.setdefault("updated_at", datetime.now().isoformat(timespec="seconds"))

    workspace.meta_dir.mkdir(parents=True, exist_ok=True)
    workspace.manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return workspace.manifest_path
