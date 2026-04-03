"""Headless ATH -> mesh -> BEM automation runner for Optuna workflows."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ath_gui.domain.auto_enclosure import derive_auto_enclosure
from ath_gui.domain.config_core import (
    default_global_state,
    default_horn_state,
    load_global_state,
    load_horn_state,
    read_text_file,
    render_global_text,
    render_horn_text,
    sanitize_ath_state,
)
from ath_gui.domain.design_recipe import DesignRecipe
from ath_gui.domain.specs import ATH_EXE, ATH_GLOBAL_CONFIG, ATH_RUNTIME_DIR, ROOT_DIR
from ath_gui.domain.runtime import RUNTIME_LAYOUT
from ath_gui.infrastructure.bem_bridge import start_bem_solver, windows_path_to_wsl
from ath_gui.infrastructure.bem_mesh import find_generated_mesh_file, inspect_mesh_file
from ath_gui.infrastructure.bem_state import (
    apply_group_map_to_bem_state,
    build_bem_runtime_settings,
    build_job_payload,
    default_bem_state,
    resolve_group_map_payload,
    sanitize_bem_state,
)
from ath_gui.infrastructure.project_workspace import ProjectWorkspace, create_workspace, write_manifest

from .case_result import CaseArtifacts, CaseResult, CaseStatus
from .result_bridge import emit_optimizer_payload, emit_optimizer_status_json, load_from_optimizer_payload


LOGGER = logging.getLogger(__name__)

RecipeTransform = Callable[[DesignRecipe, dict[str, Any]], DesignRecipe]


def _frequency_axis_from_job(job_payload: dict[str, Any]) -> np.ndarray:
    """Build the solver frequency axis from a serialized BEM job payload."""
    f1 = float(job_payload.get("f1", 1000.0))
    f2 = float(job_payload.get("f2", f1))
    num_freq = max(1, int(job_payload.get("num_freq", 1)))
    spacing = str(job_payload.get("frequency_spacing", "log")).strip().lower() or "log"
    if num_freq == 1:
        return np.asarray([f1], dtype=float)
    if spacing == "linear":
        return np.linspace(f1, f2, num_freq, dtype=float)
    return np.geomspace(f1, f2, num_freq, dtype=float)


def _coerce_notes(*groups: list[str] | tuple[str, ...]) -> list[str]:
    """Flatten note groups while dropping empty strings."""
    notes: list[str] = []
    for group in groups:
        for item in group:
            text = str(item).strip()
            if text:
                notes.append(text)
    return notes


def _unique_strings(values: list[str]) -> list[str]:
    """Preserve string order while removing duplicates."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


@contextmanager
def _temporary_global_config(path: Path, rendered_text: str) -> Any:
    """Temporarily patch `ath.cfg` for headless ATH execution."""
    original_exists = path.exists()
    original_text = read_text_file(path) if original_exists else None
    path.write_text(rendered_text, encoding="utf-8", newline="\n")
    try:
        yield
    finally:
        if original_exists and original_text is not None:
            path.write_text(original_text, encoding="utf-8", newline="\n")
        elif path.exists():
            path.unlink()


@dataclass(slots=True)
class HeadlessCaseRunner:
    """Run the existing ATH/BEM workflow without the GUI and return `CaseResult`."""

    base_recipe: DesignRecipe | None = None
    base_recipe_path: Path | None = None
    base_horn_cfg_path: Path | None = None
    base_global_state: dict[str, object] | None = None
    base_horn_state: dict[str, object] | None = None
    base_bem_state: dict[str, object] | None = None
    global_config_path: Path = ATH_GLOBAL_CONFIG
    projects_root: Path | None = None
    planes: tuple[str, ...] = ("XZ", "YZ")
    backend: str = "wsl"
    wsl_venv: str = RUNTIME_LAYOUT.default_wsl_venv
    wsl_solver_entry: str = RUNTIME_LAYOUT.default_wsl_solver_entry
    local_solver_python: str = ""
    conda_exe: str = "conda"
    conda_env: str = "bempp"
    ath_timeout_sec: float = 1800.0
    bem_timeout_sec: float = 7200.0
    poll_interval_sec: float = 0.25
    recipe_transform: RecipeTransform | None = None

    def run(self, params: dict[str, Any] | None = None) -> CaseResult:
        """Execute a headless ATH+BEM run and return bridge-ready artifacts."""
        base_recipe = self._load_base_recipe()
        recipe = self._apply_params(base_recipe, dict(params or {}))
        workspace: ProjectWorkspace | None = None
        manifest: dict[str, Any] = {}
        logs: dict[str, Path] = {}
        try:
            workspace = create_workspace(recipe.case_name, projects_root=self.projects_root)
            manifest = self._initial_manifest(workspace, recipe)
            write_manifest(workspace, manifest)
            logs = {"ath": workspace.ath_dir / "ath.log"}

            global_state = self._load_global_state()
            ath_state = self._build_ath_state(recipe, workspace)
            base_bem_state = self._build_bem_state(recipe, ath_state)

            self._write_inputs(workspace, recipe, global_state, ath_state)
            manifest["stages"].append({"stage": "running ATH", "detail": "ATH mesh generation", "time": self._timestamp()})
            write_manifest(workspace, manifest)

            mesh_file = self._run_ath(workspace, global_state, ath_state)
            mesh_info = inspect_mesh_file(
                mesh_file,
                mesh_scale_to_meter=float(base_bem_state.get("BEM.MeshScaleToMeter", 0.001)),
            )

            manifest["mesh_file"] = str(mesh_file)
            manifest["stages"].append({"stage": "mapping groups", "detail": "BEM group mapping", "time": self._timestamp()})
            write_manifest(workspace, manifest)

            group_map_payload = resolve_group_map_payload(base_bem_state, mesh_info, ath_state)
            workspace.group_map_path.write_text(
                json.dumps(group_map_payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            runtime_bem_state = apply_group_map_to_bem_state(base_bem_state, group_map_payload)
            bem_runtime = self._build_launch_settings(runtime_bem_state, ath_state)

            plane_runs: dict[str, dict[str, Any]] = {}
            for plane in self._normalized_planes():
                plane_runs[plane] = self._run_bem_plane(
                    workspace=workspace,
                    mesh_file=mesh_file,
                    ath_state=ath_state,
                    runtime_bem_state=runtime_bem_state,
                    bem_runtime=bem_runtime,
                    plane=plane,
                    mesh_info=mesh_info,
                    group_map_payload=group_map_payload,
                )
                logs[f"solver_{plane.lower()}"] = plane_runs[plane]["log_file"]

            combined_status = self._combine_status(mesh_info, plane_runs)
            self._emit_combined_payload(workspace, plane_runs, combined_status)

            manifest.update(
                {
                    "status": "done" if combined_status["bem_ok"] and combined_status["post_ok"] else "error",
                    "finished_at": self._timestamp(),
                    "group_map": group_map_payload,
                    "result_dir": str(workspace.bempp_dir),
                    "plane_runs": {
                        plane: {
                            "result_dir": str(run["result_dir"]),
                            "summary_json": str(run["summary_json"]) if run["summary_json"] is not None else None,
                            "optimizer_payload": str(run["optimizer_payload"]),
                            "optimizer_status_json": str(run["optimizer_status_json"]),
                            "exit_code": run["exit_code"],
                        }
                        for plane, run in plane_runs.items()
                    },
                }
            )
            write_manifest(workspace, manifest)

            artifacts = CaseArtifacts(
                case_dir=workspace.run_root,
                output_dir=workspace.bempp_dir,
                horn_cfg_path=workspace.horn_cfg_path,
                global_cfg_path=workspace.ath_global_cfg_path,
                optimizer_payload=workspace.bempp_dir / "optimizer_payload.npz",
                optimizer_status_json=workspace.bempp_dir / "optimizer_status.json",
                logs=logs,
            )
            status = CaseStatus.from_dict(combined_status)
            meta = {
                "recipe": recipe.to_dict(),
                "workspace_paths": {
                    "run_root": str(workspace.run_root),
                    "input": str(workspace.input_dir),
                    "ath": str(workspace.ath_dir),
                    "bempp": str(workspace.bempp_dir),
                    "meta": str(workspace.meta_dir),
                },
                "group_map": group_map_payload,
                "plane_runs": {
                    plane: {
                        "result_dir": str(run["result_dir"]),
                        "summary_json": str(run["summary_json"]) if run["summary_json"] is not None else None,
                        "optimizer_payload": str(run["optimizer_payload"]),
                        "optimizer_status_json": str(run["optimizer_status_json"]),
                    }
                    for plane, run in plane_runs.items()
                },
            }
            return CaseResult(artifacts=artifacts, status=status, meta=meta)
        except Exception as exc:
            notes = _unique_strings([str(exc)])
            LOGGER.exception("Headless ATH/BEM run failed: %s", exc)
            status_payload = {
                "ath_ok": False,
                "bem_ok": False,
                "post_ok": False,
                "mesh_ok": False,
                "geometry_ok": False,
                "self_intersection": False,
                "mesh_quality_ok": True,
                "exit_code": 1,
                "notes": notes,
            }
            if workspace is not None:
                self._emit_failure_payload(workspace.bempp_dir, status_payload)
                manifest.update({"status": "error", "finished_at": self._timestamp(), "error": str(exc)})
                write_manifest(workspace, manifest)
                output_dir = workspace.bempp_dir
                case_dir = workspace.run_root
                horn_cfg_path = workspace.horn_cfg_path
                global_cfg_path = workspace.ath_global_cfg_path
            else:
                output_dir = ROOT_DIR
                case_dir = ROOT_DIR
                horn_cfg_path = None
                global_cfg_path = self.global_config_path if self.global_config_path.exists() else None
            artifacts = CaseArtifacts(
                case_dir=case_dir,
                output_dir=output_dir,
                horn_cfg_path=horn_cfg_path,
                global_cfg_path=global_cfg_path,
                optimizer_payload=(output_dir / "optimizer_payload.npz") if workspace is not None else None,
                optimizer_status_json=(output_dir / "optimizer_status.json") if workspace is not None else None,
                logs=logs,
            )
            return CaseResult(
                artifacts=artifacts,
                status=CaseStatus.from_dict(status_payload),
                meta={
                    "recipe": recipe.to_dict(),
                    "workspace_paths": (
                        {
                            "run_root": str(workspace.run_root),
                            "input": str(workspace.input_dir),
                            "ath": str(workspace.ath_dir),
                            "bempp": str(workspace.bempp_dir),
                            "meta": str(workspace.meta_dir),
                        }
                        if workspace is not None
                        else {}
                    ),
                    "error": str(exc),
                },
            )

    def _load_base_recipe(self) -> DesignRecipe:
        if self.base_recipe is not None:
            return DesignRecipe.from_dict(self.base_recipe.to_dict())
        if self.base_recipe_path is not None:
            payload = json.loads(Path(self.base_recipe_path).read_text(encoding="utf-8"))
            return DesignRecipe.from_dict(payload)
        return DesignRecipe()

    def _apply_params(self, base_recipe: DesignRecipe, params: dict[str, Any]) -> DesignRecipe:
        if self.recipe_transform is not None:
            recipe = self.recipe_transform(base_recipe, params)
            recipe.assert_valid()
            return recipe

        field_names = set(DesignRecipe.__dataclass_fields__)
        direct_updates: dict[str, Any] = {}
        ath_overrides = dict(base_recipe.ath_overrides)
        bem_overrides = dict(base_recipe.bem_overrides)
        for key, value in params.items():
            if key in field_names:
                direct_updates[key] = value
                continue
            if str(key).startswith("ath_overrides."):
                ath_overrides[str(key).removeprefix("ath_overrides.")] = value
                continue
            if str(key).startswith("bem_overrides."):
                bem_overrides[str(key).removeprefix("bem_overrides.")] = value
                continue
            raise KeyError(
                f"Unknown optimization parameter `{key}`. "
                "Map trial params to DesignRecipe fields or use `ath_overrides.*` / `bem_overrides.*`."
            )
        recipe = replace(base_recipe, **direct_updates, ath_overrides=ath_overrides, bem_overrides=bem_overrides)
        recipe.assert_valid()
        return recipe

    def _load_global_state(self) -> dict[str, object]:
        if self.base_global_state is not None:
            return dict(self.base_global_state)
        if self.global_config_path.exists():
            return load_global_state(read_text_file(self.global_config_path))
        return default_global_state()

    def _build_ath_state(self, recipe: DesignRecipe, workspace: ProjectWorkspace) -> dict[str, object]:
        ath_state = recipe.to_ath_state(base_state=self._load_base_horn_state())
        if recipe.auto_enclosure_enabled:
            ath_state = derive_auto_enclosure(ath_state)
        ath_state = sanitize_ath_state(ath_state)
        ath_state["Output.DestDir"] = str(workspace.ath_dir)
        ath_state["Output.SubDir"] = ""
        return ath_state

    def _load_base_horn_state(self) -> dict[str, object]:
        if self.base_horn_state is not None:
            return dict(self.base_horn_state)
        base_path = self.base_horn_cfg_path
        if base_path is None and self.base_recipe_path is not None:
            sibling = self.base_recipe_path.expanduser().resolve().parent / "horn.cfg"
            if sibling.exists():
                base_path = sibling
        if base_path is not None and Path(base_path).exists():
            return load_horn_state(read_text_file(Path(base_path)))
        return default_horn_state()

    def _build_bem_state(self, recipe: DesignRecipe, ath_state: dict[str, object]) -> dict[str, object]:
        base_state = dict(self.base_bem_state) if self.base_bem_state is not None else default_bem_state()
        return sanitize_bem_state(recipe.to_bem_state(base_state=base_state), ath_state)

    def _write_inputs(
        self,
        workspace: ProjectWorkspace,
        recipe: DesignRecipe,
        global_state: dict[str, object],
        ath_state: dict[str, object],
    ) -> None:
        workspace.design_recipe_path.write_text(
            json.dumps(recipe.to_dict(), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        workspace.ath_global_cfg_path.write_text(render_global_text(global_state), encoding="utf-8", newline="\n")
        workspace.horn_cfg_path.write_text(render_horn_text(ath_state), encoding="utf-8", newline="\n")

    def _run_ath(self, workspace: ProjectWorkspace, global_state: dict[str, object], ath_state: dict[str, object]) -> Path:
        if not ATH_EXE.exists():
            raise FileNotFoundError(f"ATH executable not found: {ATH_EXE}")

        rendered_global = render_global_text(global_state)
        log_path = workspace.ath_dir / "ath.log"
        with _temporary_global_config(ATH_GLOBAL_CONFIG, rendered_global):
            with log_path.open("w", encoding="utf-8", newline="\n") as log_handle:
                process = subprocess.Popen(
                    [str(ATH_EXE), str(workspace.horn_cfg_path)],
                    cwd=str(ATH_RUNTIME_DIR),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                try:
                    return_code = process.wait(timeout=self.ath_timeout_sec)
                except subprocess.TimeoutExpired as exc:
                    process.kill()
                    raise TimeoutError(f"ATH timed out after {self.ath_timeout_sec:.1f}s.") from exc
        if return_code != 0:
            raise RuntimeError(f"ATH failed with exit code {return_code}.")

        started = time.time()
        while True:
            mesh_file = find_generated_mesh_file(workspace.ath_dir, workspace.horn_cfg_path)
            if mesh_file is not None and mesh_file.exists():
                return mesh_file
            if time.time() - started > max(5.0, self.poll_interval_sec * 4.0):
                break
            time.sleep(self.poll_interval_sec)
        raise FileNotFoundError("ATH completed but no `.msh` mesh could be found in the workspace output.")

    def _build_launch_settings(self, runtime_bem_state: dict[str, object], ath_state: dict[str, object]) -> dict[str, object]:
        bem_runtime = build_bem_runtime_settings(runtime_bem_state, ath_state)
        bem_runtime["backend"] = self.backend
        bem_runtime["launch_options"] = {
            "backend": self.backend,
            "wsl_venv": self.wsl_venv,
            "wsl_solver_entry": self.wsl_solver_entry,
            "local_python_exe": self.local_solver_python,
            "conda_exe": self.conda_exe,
            "conda_env": self.conda_env,
        }
        return bem_runtime

    def _run_bem_plane(
        self,
        *,
        workspace: ProjectWorkspace,
        mesh_file: Path,
        ath_state: dict[str, object],
        runtime_bem_state: dict[str, object],
        bem_runtime: dict[str, object],
        plane: str,
        mesh_info: dict[str, object],
        group_map_payload: dict[str, object],
    ) -> dict[str, Any]:
        plane_key = plane.strip().lower()
        result_dir = workspace.bempp_dir / f"plane_{plane_key}"
        result_dir.mkdir(parents=True, exist_ok=True)

        plane_state = dict(runtime_bem_state)
        plane_state["BEM.Plane"] = plane
        job_payload = build_job_payload(plane_state, mesh_file, windows_path_to_wsl(mesh_file))

        job_file = result_dir / "job.json"
        group_map_file = result_dir / "group_map.json"
        log_file = result_dir / "solver.log"
        job_file.write_text(json.dumps(job_payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        group_map_file.write_text(json.dumps(group_map_payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

        launch = start_bem_solver(job_file, log_file, **dict(bem_runtime.get("launch_options", {})))
        try:
            try:
                return_code = launch.process.wait(timeout=self.bem_timeout_sec)
            except subprocess.TimeoutExpired as exc:
                launch.process.kill()
                raise TimeoutError(f"BEM {plane} timed out after {self.bem_timeout_sec:.1f}s.") from exc
        finally:
            launch.log_stream.close()

        summary_path = result_dir / "summary.json"
        optimizer_payload = result_dir / "optimizer_payload.npz"
        optimizer_status_json = result_dir / "optimizer_status.json"
        started = time.time()
        while time.time() - started <= max(5.0, self.poll_interval_sec * 4.0):
            if summary_path.exists() or optimizer_status_json.exists():
                break
            time.sleep(self.poll_interval_sec)

        status_payload = {
            "ath_ok": True,
            "bem_ok": return_code == 0,
            "post_ok": return_code == 0,
            "mesh_ok": True,
            "geometry_ok": True,
            "self_intersection": False,
            "mesh_quality_ok": int(mesh_info.get("nonmanifold_edge_count", 0)) == 0,
            "exit_code": int(return_code),
            "notes": [],
        }
        if return_code != 0:
            status_payload["notes"] = [f"BEM plane {plane} failed with exit code {return_code}."]

        if not optimizer_payload.exists():
            self._emit_plane_failure_payload(result_dir, plane, status_payload, job_payload)
        elif not optimizer_status_json.exists():
            emit_optimizer_status_json(optimizer_status_json, status_payload)

        return {
            "plane": plane,
            "result_dir": result_dir,
            "job_file": job_file,
            "log_file": log_file,
            "summary_json": summary_path if summary_path.exists() else None,
            "optimizer_payload": optimizer_payload if optimizer_payload.exists() else result_dir / "optimizer_payload.npz",
            "optimizer_status_json": optimizer_status_json,
            "exit_code": int(return_code),
            "status": status_payload,
        }

    def _emit_plane_failure_payload(
        self,
        result_dir: Path,
        plane: str,
        status_payload: dict[str, Any],
        job_payload: dict[str, Any],
    ) -> None:
        freqs_hz = _frequency_axis_from_job(job_payload)
        plane_upper = plane.strip().upper()
        if plane_upper == "YZ":
            emit_optimizer_payload(
                result_dir / "optimizer_payload.npz",
                freqs_hz=freqs_hz,
                angles_deg_h=np.empty(0, dtype=float),
                angles_deg_v=np.asarray([0.0], dtype=float),
                spl_h_db=np.empty((0, len(freqs_hz)), dtype=float),
                spl_v_db=np.zeros((1, len(freqs_hz)), dtype=float),
                onaxis_db=np.zeros(len(freqs_hz), dtype=float),
                status=status_payload,
            )
        else:
            emit_optimizer_payload(
                result_dir / "optimizer_payload.npz",
                freqs_hz=freqs_hz,
                angles_deg_h=np.asarray([0.0], dtype=float),
                angles_deg_v=np.empty(0, dtype=float),
                spl_h_db=np.zeros((1, len(freqs_hz)), dtype=float),
                spl_v_db=np.empty((0, len(freqs_hz)), dtype=float),
                onaxis_db=np.zeros(len(freqs_hz), dtype=float),
                status=status_payload,
            )
        emit_optimizer_status_json(result_dir / "optimizer_status.json", status_payload)

    def _combine_status(self, mesh_info: dict[str, object], plane_runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
        notes = _coerce_notes(
            [str(item) for item in mesh_info.get("warnings", [])],
            *[run["status"].get("notes", []) for run in plane_runs.values()],
        )
        return {
            "ath_ok": True,
            "bem_ok": all(bool(run["status"].get("bem_ok", False)) for run in plane_runs.values()),
            "post_ok": all(bool(run["status"].get("post_ok", False)) for run in plane_runs.values()),
            "mesh_ok": True,
            "geometry_ok": True,
            "self_intersection": False,
            "mesh_quality_ok": int(mesh_info.get("nonmanifold_edge_count", 0)) == 0,
            "exit_code": 0 if all(run["exit_code"] == 0 for run in plane_runs.values()) else 1,
            "notes": _unique_strings(notes),
        }

    def _emit_combined_payload(
        self,
        workspace: ProjectWorkspace,
        plane_runs: dict[str, dict[str, Any]],
        combined_status: dict[str, Any],
    ) -> None:
        payloads = {
            plane: load_from_optimizer_payload(run["optimizer_payload"], run["optimizer_status_json"])[0]
            for plane, run in plane_runs.items()
        }
        freqs_hz = self._shared_frequency_axis(payloads)
        polar_h = payloads.get("XZ")
        polar_v = payloads.get("YZ")

        angles_deg_h = (
            np.asarray(polar_h.angles_deg_h, dtype=float)
            if polar_h is not None and len(polar_h.angles_deg_h) > 0
            else np.empty(0, dtype=float)
        )
        spl_h_db = (
            np.asarray(polar_h.spl_h_db, dtype=float)
            if polar_h is not None and polar_h.spl_h_db.size > 0
            else np.empty((0, len(freqs_hz)), dtype=float)
        )
        angles_deg_v = (
            np.asarray(polar_v.angles_deg_v, dtype=float)
            if polar_v is not None and len(polar_v.angles_deg_v) > 0
            else np.empty(0, dtype=float)
        )
        spl_v_db = (
            np.asarray(polar_v.spl_v_db, dtype=float)
            if polar_v is not None and polar_v.spl_v_db.size > 0
            else np.empty((0, len(freqs_hz)), dtype=float)
        )

        onaxis_db = None
        for polar in (polar_h, polar_v):
            if polar is not None and polar.onaxis_db is not None:
                onaxis_db = np.asarray(polar.onaxis_db, dtype=float)
                break
        if onaxis_db is None:
            onaxis_db = np.zeros(len(freqs_hz), dtype=float)

        emit_optimizer_payload(
            workspace.bempp_dir / "optimizer_payload.npz",
            freqs_hz=freqs_hz,
            angles_deg_h=angles_deg_h,
            angles_deg_v=angles_deg_v,
            spl_h_db=spl_h_db,
            spl_v_db=spl_v_db,
            onaxis_db=onaxis_db,
            di_db=self._first_optional_curve(payloads, "di_db"),
            sound_power_db=self._first_optional_curve(payloads, "sound_power_db"),
            listening_window_db=self._first_optional_curve(payloads, "listening_window_db"),
            beamwidth_6_h_deg=self._first_optional_curve(payloads, "beamwidth_6_h_deg"),
            beamwidth_6_v_deg=self._first_optional_curve(payloads, "beamwidth_6_v_deg"),
            beamwidth_12_h_deg=self._first_optional_curve(payloads, "beamwidth_12_h_deg"),
            beamwidth_12_v_deg=self._first_optional_curve(payloads, "beamwidth_12_v_deg"),
            status=combined_status,
        )
        emit_optimizer_status_json(workspace.bempp_dir / "optimizer_status.json", combined_status)

    def _emit_failure_payload(self, output_dir: Path, status_payload: dict[str, Any]) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        freqs_hz = np.asarray([1000.0], dtype=float)
        emit_optimizer_payload(
            output_dir / "optimizer_payload.npz",
            freqs_hz=freqs_hz,
            angles_deg_h=np.asarray([0.0], dtype=float),
            angles_deg_v=np.asarray([0.0], dtype=float),
            spl_h_db=np.zeros((1, 1), dtype=float),
            spl_v_db=np.zeros((1, 1), dtype=float),
            onaxis_db=np.zeros(1, dtype=float),
            status=status_payload,
        )
        emit_optimizer_status_json(output_dir / "optimizer_status.json", status_payload)

    def _shared_frequency_axis(self, payloads: dict[str, Any]) -> np.ndarray:
        axes = [np.asarray(polar.freqs_hz, dtype=float) for polar in payloads.values()]
        if not axes:
            return np.asarray([1000.0], dtype=float)
        reference = axes[0]
        for axis in axes[1:]:
            if len(reference) != len(axis) or not np.allclose(reference, axis, rtol=1e-8, atol=1e-8):
                raise ValueError("Plane payload frequency axes do not match; combined optimizer payload cannot be built.")
        return reference

    def _first_optional_curve(self, payloads: dict[str, Any], attribute: str) -> np.ndarray | None:
        for polar in payloads.values():
            value = getattr(polar, attribute, None)
            if value is not None:
                return np.asarray(value, dtype=float)
        return None

    def _normalized_planes(self) -> tuple[str, ...]:
        normalized: list[str] = []
        for plane in self.planes:
            label = str(plane).strip().upper()
            if label not in {"XZ", "YZ"}:
                raise ValueError(f"Unsupported BEM observation plane: {plane!r}")
            if label not in normalized:
                normalized.append(label)
        if not normalized:
            raise ValueError("At least one BEM plane must be configured.")
        return tuple(normalized)

    def _initial_manifest(self, workspace: ProjectWorkspace, recipe: DesignRecipe) -> dict[str, Any]:
        return {
            "status": "running",
            "started_at": self._timestamp(),
            "stages": [{"stage": "preparing", "detail": "headless runner setup", "time": self._timestamp()}],
            "workspace_paths": {
                "run_root": str(workspace.run_root),
                "input": str(workspace.input_dir),
                "ath": str(workspace.ath_dir),
                "bempp": str(workspace.bempp_dir),
                "meta": str(workspace.meta_dir),
            },
            "recipe": recipe.to_dict(),
        }

    def _timestamp(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S")
