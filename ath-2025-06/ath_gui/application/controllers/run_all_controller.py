"""High-level ATH -> mesh -> group map -> BEM orchestration controller."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable, TypeVar

from ...domain.auto_enclosure import derive_auto_enclosure
from ...domain.config_core import normalize_branch_locked_horn_state, render_global_text, render_horn_text
from ...domain.design_recipe import DesignRecipe
from ...domain.specs import APP_TITLE
from ...infrastructure.bem_bridge import start_bem_solver, windows_path_to_wsl
from ...infrastructure.bem_mesh import format_mesh_info_text, inspect_mesh_file
from ...infrastructure.bem_state import build_job_payload
from ...infrastructure.group_mapper import mesh_family_key
from ...infrastructure.project_workspace import (
    ProjectWorkspace,
    create_workspace,
    latest_workspace_for_case,
    load_workspace,
    write_manifest,
)


T = TypeVar("T")

FIXED_SOURCE_GROUPS = [2]
FIXED_WALL_GROUPS = [1, 3]
FIXED_IGNORE_GROUPS = [4]
FIXED_INTERFACE_GROUPS: list[int] = []


class RunAllController:
    def __init__(self, app: Any) -> None:
        self.app = app
        self._run_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.latest_workspace: ProjectWorkspace | None = None

    def is_running(self) -> bool:
        thread = self._run_thread
        return thread is not None and thread.is_alive()

    def run_all(self, recipe: DesignRecipe) -> None:
        with self._lock:
            if self.is_running():
                messagebox.showinfo(APP_TITLE, "Run All 目前正在執行中，請等待完成。")
                return
            self._run_thread = threading.Thread(target=self._run_all_worker, args=(recipe,), daemon=True)
            self._run_thread.start()

    def run_all_from_ui(self) -> None:
        try:
            recipe = self.app.collect_design_recipe()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Run All 參數解析失敗：\n{exc}")
            return
        self.run_all(recipe)

    def save_recipe(self) -> None:
        try:
            recipe = self.app.collect_design_recipe()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Run All 參數解析失敗：\n{exc}")
            return
        errors = recipe.validate()
        if errors:
            messagebox.showerror(APP_TITLE, "Recipe 參數有誤：\n- " + "\n- ".join(errors))
            return

        default_name = f"{recipe.case_name.strip() or 'design'}.recipe.json"
        path = filedialog.asksaveasfilename(
            title="儲存 Design Recipe",
            initialdir=str(self.app.project_root_var.get() or Path.cwd()),
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        Path(path).write_text(json.dumps(recipe.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        self._set_stage("idle", f"Recipe 已儲存：{path}")

    def load_recipe(self) -> None:
        path = filedialog.askopenfilename(
            title="載入 Design Recipe",
            initialdir=str(self.app.project_root_var.get() or Path.cwd()),
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        recipe = DesignRecipe.from_dict(payload)
        errors = recipe.validate()
        if errors:
            messagebox.showerror(APP_TITLE, "Recipe 檔案內容無效：\n- " + "\n- ".join(errors))
            return
        self.app.apply_design_recipe(recipe)
        self._set_stage("idle", f"Recipe 已載入：{path}")

    def open_workspace(self) -> None:
        try:
            recipe = self.app.collect_design_recipe()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Run All 參數解析失敗：\n{exc}")
            return
        workspace = latest_workspace_for_case(recipe.case_name)
        if workspace is None:
            messagebox.showinfo(APP_TITLE, "目前尚未找到此 case 的 workspace。")
            return
        self.latest_workspace = workspace
        try:
            os.startfile(str(workspace.run_root))
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"無法開啟 workspace：\n{exc}")

    def reload_latest_workspace_results(self) -> None:
        try:
            recipe = self.app.collect_design_recipe()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Run All 參數解析失敗：\n{exc}")
            return
        workspace = latest_workspace_for_case(recipe.case_name)
        if workspace is None:
            messagebox.showinfo(APP_TITLE, "目前尚未找到可重載的 workspace。")
            return
        self.latest_workspace = workspace
        if not (workspace.bempp_dir / "summary.json").exists():
            messagebox.showinfo(APP_TITLE, f"workspace 還沒有 BEM 結果：{workspace.bempp_dir}")
            return
        self.app.load_bem_results(workspace.bempp_dir)
        self._set_stage("done", f"已載入 workspace 結果：{workspace.bempp_dir}")

    def load_workspace_and_results(self) -> None:
        path = filedialog.askdirectory(
            title="選擇 workspace run 目錄",
            initialdir=str(self.app.project_root_var.get() or Path.cwd()),
        )
        if not path:
            return
        workspace = load_workspace(path)
        self.latest_workspace = workspace
        if not (workspace.bempp_dir / "summary.json").exists():
            messagebox.showinfo(APP_TITLE, f"workspace 還沒有 BEM 結果：{workspace.bempp_dir}")
            return
        self.app.load_bem_results(workspace.bempp_dir)
        self._set_stage("done", f"已載入 workspace 結果：{workspace.bempp_dir}")

    def _invoke_ui(self, func: Callable[[], T]) -> T:
        done = threading.Event()
        box: dict[str, Any] = {}

        def _runner() -> None:
            try:
                box["result"] = func()
            except Exception as exc:  # pragma: no cover - UI side exceptions are surfaced to caller.
                box["error"] = exc
            finally:
                done.set()

        self.app.after(0, _runner)
        done.wait()
        if "error" in box:
            raise box["error"]
        return box["result"]

    def _set_stage(self, stage: str, detail: str) -> None:
        def _apply() -> None:
            if hasattr(self.app, "run_all_stage_var"):
                self.app.run_all_stage_var.set(stage)
            if hasattr(self.app, "run_all_status_var"):
                self.app.run_all_status_var.set(detail)
            if hasattr(self.app, "run_all_workspace_var"):
                workspace_text = str(self.latest_workspace.run_root) if self.latest_workspace is not None else "(none)"
                self.app.run_all_workspace_var.set(f"Workspace: {workspace_text}")
            self.app.status_var.set(detail)
            self.app._update_runtime_status()

        self.app.after(0, _apply)

    def _wait_for_ath_completion(self, timeout_sec: float = 1800.0) -> None:
        started = time.time()
        while True:
            ath_process = self._invoke_ui(lambda: self.app.ath_process)
            if ath_process is None:
                break
            if time.time() - started > timeout_sec:
                raise TimeoutError("ATH run timed out.")
            time.sleep(0.25)

        status_text = str(self._invoke_ui(lambda: self.app.preview_status_var.get()))
        if "失敗" in status_text or "找不到輸出檔" in status_text:
            raise RuntimeError(f"ATH failed: {status_text}")

    def _update_manifest(self, workspace: ProjectWorkspace, payload: dict[str, Any]) -> None:
        write_manifest(workspace, payload)

    def _run_all_worker(self, recipe: DesignRecipe) -> None:
        started_at = datetime.now().isoformat(timespec="seconds")
        stages: list[dict[str, str]] = []

        def add_stage(stage: str, detail: str) -> None:
            stages.append({"stage": stage, "detail": detail, "time": datetime.now().isoformat(timespec="seconds")})
            self._set_stage(stage, detail)

        workspace: ProjectWorkspace | None = None
        try:
            errors = recipe.validate()
            if errors:
                raise ValueError("Recipe 參數有誤：" + " | ".join(errors))

            add_stage("preparing", "建立 workspace 與初始化流程中...")
            workspace = create_workspace(recipe.case_name)
            self.latest_workspace = workspace

            manifest: dict[str, Any] = {
                "status": "running",
                "started_at": started_at,
                "stages": stages,
                "workspace_paths": {
                    "run_root": str(workspace.run_root),
                    "input": str(workspace.input_dir),
                    "ath": str(workspace.ath_dir),
                    "bempp": str(workspace.bempp_dir),
                    "meta": str(workspace.meta_dir),
                },
                "recipe": recipe.to_dict(),
            }
            self._update_manifest(workspace, manifest)

            add_stage("saving recipe", "寫入 recipe 與 cfg 檔案...")
            global_state = self._invoke_ui(self.app.collect_global_state)
            horn_base = self._invoke_ui(lambda: self.app.collect_horn_state(normalize_locked=True))
            bem_base = self._invoke_ui(self.app.collect_bem_state)

            ath_state = recipe.to_ath_state(base_state=horn_base)
            if recipe.auto_enclosure_enabled:
                ath_state = derive_auto_enclosure(ath_state)
            ath_state = normalize_branch_locked_horn_state(ath_state)
            ath_state["Output.DestDir"] = str(workspace.ath_dir)
            ath_state["Output.SubDir"] = ""
            bem_state = recipe.to_bem_state(base_state=bem_base)

            workspace.design_recipe_path.write_text(
                json.dumps(recipe.to_dict(), indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            workspace.ath_global_cfg_path.write_text(render_global_text(global_state), encoding="utf-8", newline="\n")
            workspace.horn_cfg_path.write_text(render_horn_text(ath_state), encoding="utf-8", newline="\n")

            def _apply_states() -> None:
                self.app.apply_horn_state(ath_state)
                self.app.apply_bem_state(bem_state)
                self.app.current_horn_path.set(str(workspace.horn_cfg_path))
                self.app.refresh_preview()
                self.app._update_runtime_status()

            self._invoke_ui(_apply_states)

            add_stage("running ATH", "啟動 ATH 生成網格中...")
            self._invoke_ui(self.app.run_ath)
            self._wait_for_ath_completion()

            add_stage("scanning mesh", "掃描並檢查 ATH 輸出網格中...")
            from ...infrastructure.bem_mesh import find_generated_mesh_file

            mesh_file = find_generated_mesh_file(workspace.ath_dir, workspace.horn_cfg_path)
            if mesh_file is None or not mesh_file.exists():
                raise FileNotFoundError("Run All 找不到可用的 ATH `.msh` 輸出。")

            bem_state["BEM.MeshFile"] = str(mesh_file)
            mesh_scale = float(bem_state.get("BEM.MeshScaleToMeter", 0.001))
            mesh_info = inspect_mesh_file(mesh_file, mesh_scale_to_meter=mesh_scale)

            def _apply_mesh_info() -> None:
                self.app._set_widget_value(self.app.bem_widgets["BEM.MeshFile"], str(mesh_file))
                self.app._set_text_widget(self.app.bem_mesh_text, format_mesh_info_text(mesh_info))
                detected_groups = [int(value) for value in mesh_info.get("detected_groups", [])]
                count_map = {str(key): int(value) for key, value in dict(mesh_info.get("element_count_per_group", {})).items()}
                source_label = str(mesh_info.get("group_source", "unknown"))
                self.app.group_status_var.set(f"分群狀態：已偵測 {len(detected_groups)} 個群組")
                self.app.preview_group_var.set(
                    self.app._format_group_summary(detected_groups, group_source=source_label, count_map=count_map)
                )
                self.app.mesh_status_var.set(str(mesh_file))
                self.app._update_runtime_status()
                self.app._select_workspace_tab("MeshInfo")

            self._invoke_ui(_apply_mesh_info)

            add_stage("mapping groups", "套用固定分群規則中...")
            detected_groups = {int(value) for value in mesh_info.get("detected_groups", [])}
            required_groups = set(FIXED_SOURCE_GROUPS + FIXED_WALL_GROUPS)
            missing_required = sorted(group_id for group_id in required_groups if group_id not in detected_groups)
            if missing_required:
                raise RuntimeError(
                    "固定分群失敗：mesh 未包含必要群組 "
                    f"{missing_required}，目前偵測到 {sorted(detected_groups)}。"
                )

            group_map_payload = {
                "schema": "ath.group_map.v1",
                "mesh_family": mesh_family_key(mesh_info),
                "source_groups": list(FIXED_SOURCE_GROUPS),
                "wall_groups": list(FIXED_WALL_GROUPS),
                "interface_groups": list(FIXED_INTERFACE_GROUPS),
                "ignore_groups": [group_id for group_id in FIXED_IGNORE_GROUPS if group_id in detected_groups],
                "confidence": "manual_fixed",
                "requires_confirmation": False,
                "reasons": [
                    "Fixed mapping by user request: source=2, wall=1,3, ignore=4.",
                ],
            }

            workspace.group_map_path.write_text(
                json.dumps(group_map_payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            source_groups = [int(value) for value in group_map_payload.get("source_groups", [])]
            wall_groups = [int(value) for value in group_map_payload.get("wall_groups", [])]
            interface_groups = [int(value) for value in group_map_payload.get("interface_groups", [])]
            ignore_groups = [int(value) for value in group_map_payload.get("ignore_groups", [])]
            if not source_groups:
                raise RuntimeError("GroupAutoMapper 沒有產生可用的 source groups。")

            bem_state["BEM.SourceGroups"] = ",".join(str(value) for value in source_groups)
            bem_state["BEM.WallGroups"] = ",".join(str(value) for value in wall_groups)
            bem_state["BEM.InterfaceGroups"] = ",".join(str(value) for value in interface_groups)
            bem_state["BEM.IgnoreGroups"] = ",".join(str(value) for value in ignore_groups)

            self._invoke_ui(lambda: self.app.apply_bem_state(bem_state))

            add_stage("running BEM", "建立 job 並執行 BEM solver 中...")
            job_payload = build_job_payload(bem_state, mesh_file, windows_path_to_wsl(mesh_file))
            workspace.job_path.write_text(json.dumps(job_payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
            runtime_job_path = workspace.bempp_dir / "job.json"
            runtime_job_path.write_text(json.dumps(job_payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

            solver_log = workspace.bempp_dir / "solver.log"
            launch = start_bem_solver(runtime_job_path, solver_log)
            self._invoke_ui(lambda: self.app.bem_status_var.set("執行中"))
            return_code = launch.process.wait()
            launch.log_stream.close()
            if return_code != 0:
                raise RuntimeError(f"BEM solver failed with exit code {return_code}.")

            summary_path = workspace.bempp_dir / "summary.json"
            for _ in range(60):
                if summary_path.exists():
                    break
                time.sleep(0.25)
            if not summary_path.exists():
                raise RuntimeError("BEM solver finished but summary.json was not found.")

            add_stage("loading results", "載入 BEM 結果並更新 GUI 中...")
            self._invoke_ui(lambda: self.app.load_bem_results(workspace.bempp_dir))

            add_stage("done", f"Run All 完成：{workspace.run_root}")
            manifest.update(
                {
                    "status": "done",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "mesh_file": str(mesh_file),
                    "group_map": group_map_payload,
                    "result_dir": str(workspace.bempp_dir),
                }
            )
            self._update_manifest(workspace, manifest)
        except Exception as exc:
            detail = f"Run All 失敗：{exc}"
            add_stage("error", detail)
            if workspace is not None:
                self._update_manifest(
                    workspace,
                    {
                        "status": "error",
                        "started_at": started_at,
                        "finished_at": datetime.now().isoformat(timespec="seconds"),
                        "stages": stages,
                        "error": str(exc),
                    },
                )
            self._invoke_ui(lambda: messagebox.showerror(APP_TITLE, detail))
        finally:
            with self._lock:
                self._run_thread = None
