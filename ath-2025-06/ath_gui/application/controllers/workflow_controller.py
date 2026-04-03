"""Workflow-level controllers for ATH and BEM execution paths."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from tkinter import messagebox
from typing import Any

from ...domain.config_core import render_horn_text
from ...domain.specs import APP_TITLE, ATH_EXE, ATH_RUNTIME_DIR, ROOT_DIR
from ...infrastructure.bem_bridge import start_bem_solver, windows_path_to_wsl
from ...infrastructure.bem_mesh import format_mesh_info_text, inspect_mesh_file
from ...infrastructure.bem_results import (
    create_bem_result_run_dir,
    default_bem_result_dir,
    write_latest_bem_result_dir,
)
from ...infrastructure.bem_state import (
    apply_group_map_to_bem_state,
    build_job_payload,
    resolve_group_map_payload,
)
from ...infrastructure.preview_core import compute_output_directory, find_generated_preview_file


class WorkflowController:
    """Handle ATH/BEM workflow actions while keeping Tk view layer thinner."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def load_latest_output_preview(self) -> None:
        cfg_path = self.app.current_horn_path.get().strip()
        if not cfg_path:
            messagebox.showinfo(APP_TITLE, "請先儲存或開啟號角設定檔，才能解析輸出目錄。")
            return
        preview_file = find_generated_preview_file(
            compute_output_directory(self.app.collect_global_state(), self.app.collect_effective_horn_state(), Path(cfg_path)),
            Path(cfg_path),
        )
        if preview_file is None:
            messagebox.showinfo(APP_TITLE, "目前專案尚未找到可預覽的 .geo / .msh / .stl 輸出檔。")
            return
        self.app.load_embedded_preview_file(preview_file)
        self.app.resolve_bem_mesh_path(set_status=False)
        self.app.status_var.set(f"已載入內嵌預覽：{preview_file}")

    def _watch_bem_process(self, launch: Any, result_dir: Path) -> None:
        return_code = launch.process.wait()
        launch.log_stream.close()
        if return_code == 0:
            for _ in range(40):
                if (result_dir / "summary.json").exists():
                    break
                time.sleep(0.25)
        self.app.after(0, lambda: self._finish_bem_run(return_code, result_dir))

    def _finish_bem_run(self, return_code: int, result_dir: Path) -> None:
        self.app.bem_launch = None
        summary_path = result_dir / "summary.json"
        if summary_path.exists():
            try:
                self.app.load_bem_results(result_dir)
            except Exception:
                pass

        if return_code == 0:
            self.app.stop_bem_progress("BEM 已完成")
            self.app.bem_status_var.set("完成")
            self.app.status_var.set(f"BEM 執行完成，結果已從 {result_dir} 載入。")
            self.app._update_runtime_status()
            return

        self.app.stop_bem_progress("BEM 執行失敗")
        self.app.bem_status_var.set("錯誤")
        self.app.status_var.set(f"BEM 執行失敗，退出碼 {return_code}。請檢查 solver.log。")
        self.app._update_runtime_status()

    def run_bempp(self) -> None:
        if self.app.bem_launch is not None and self.app.bem_launch.process.poll() is None:
            messagebox.showinfo(APP_TITLE, "BEM 正在執行中，請等待完成。")
            return

        if not self.app.save_global_config(silent=True):
            return
        if not self.app.save_horn_config():
            return

        cfg_path = self.app.current_horn_path.get().strip()
        if not cfg_path:
            messagebox.showerror(APP_TITLE, "執行 BEM 前請先儲存目前號角設定。")
            return

        payload = self.app.collect_effective_run_payload()
        ath_state = dict(payload["ath_cfg_state"])
        bem_state = dict(payload["bem_state"])
        bem_runtime = dict(payload["bem_runtime"])
        if not bool(bem_runtime.get("enabled", False)):
            messagebox.showinfo(APP_TITLE, "BEM automation 目前停用；如需執行 BEM，請先啟用 `BEM.Enabled`。")
            return

        mesh_file = self.app.resolve_bem_mesh_path(bem_state, set_status=False)
        if mesh_file is None or not Path(mesh_file).exists():
            messagebox.showerror(
                APP_TITLE,
                "目前沒有可供 BEM 使用的 `.msh` 檔。\n\n請啟用 `Output.MSH = 1` 並執行 ATH，或手動指定網格檔。",
            )
            return

        global_state = self.app.collect_global_state()
        output_dir = compute_output_directory(global_state, ath_state, Path(cfg_path))
        result_dir = create_bem_result_run_dir(
            output_dir,
            cfg_path=Path(cfg_path),
            mesh_file=Path(mesh_file),
        )
        job_file = result_dir / "job.json"
        log_file = result_dir / "solver.log"
        group_map_file = result_dir / "group_map.json"

        try:
            mesh_info = inspect_mesh_file(
                Path(mesh_file),
                mesh_scale_to_meter=float(bem_state.get("BEM.MeshScaleToMeter", 0.001)),
            )
            group_map_payload = resolve_group_map_payload(bem_state, mesh_info, ath_state)
            group_map_file.write_text(json.dumps(group_map_payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
            runtime_bem_state = apply_group_map_to_bem_state(bem_state, group_map_payload)
            self.app._set_text_widget(self.app.bem_mesh_text, format_mesh_info_text(mesh_info))
            detected_groups = [int(value) for value in mesh_info.get("detected_groups", [])]
            count_map = {str(key): int(value) for key, value in dict(mesh_info.get("element_count_per_group", {})).items()}
            group_source = str(mesh_info.get("group_source", "unknown"))
            self.app.group_status_var.set(f"分群狀態：已偵測 {len(detected_groups)} 個群組")
            self.app.preview_group_var.set(
                self.app._format_group_summary(detected_groups, group_source=group_source, count_map=count_map)
            )
            payload = build_job_payload(runtime_bem_state, Path(mesh_file), windows_path_to_wsl(Path(mesh_file)))
            job_file.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
            self.app.bem_launch = start_bem_solver(job_file, log_file, **dict(bem_runtime.get("launch_options", {})))
        except Exception as exc:
            try:
                if result_dir.exists() and not any(result_dir.iterdir()):
                    result_dir.rmdir()
            except Exception:
                pass
            self.app.bem_status_var.set("錯誤")
            messagebox.showerror(APP_TITLE, f"啟動 BEM 失敗：\n{exc}")
            return

        self.app.bem_last_result_dir = result_dir
        self.app.bem_last_log_path = log_file
        write_latest_bem_result_dir(output_dir, result_dir)
        self.app.bem_result_path_var.set(str(result_dir))
        self.app.start_bem_progress("BEM 求解中")
        self.app.bem_status_var.set("執行中")
        self.app.mesh_status_var.set(str(mesh_file))
        self.app.status_var.set(f"已啟動 BEM 求解：{Path(mesh_file).name}，結果將寫入 {result_dir}。")
        self.app._update_runtime_status()
        threading.Thread(
            target=self._watch_bem_process,
            args=(self.app.bem_launch, result_dir),
            daemon=True,
        ).start()

    def _finish_ath_run(self, return_code: int, output_dir: Path, cfg_path: Path) -> None:
        self.app.ath_process = None
        if return_code != 0:
            self.app.preview_status_var.set("預覽狀態：ATH 產生失敗")
            self.app.status_var.set(f"ATH 已結束，退出碼 {return_code}。")
            self.app._update_runtime_status()
            return

        preview_file = find_generated_preview_file(output_dir, cfg_path)
        if preview_file is None:
            self.app.preview_status_var.set("預覽狀態：找不到輸出檔")
            self.app.status_var.set(f"ATH 已完成，但在 {output_dir} 找不到可預覽的輸出檔。")
            self.app._update_runtime_status()
            return

        self.app.load_embedded_preview_file(preview_file)
        self.app.resolve_bem_mesh_path(set_status=False)
        self.app.status_var.set(f"ATH 已完成，已載入預覽：{preview_file.name}")
        self.app._update_runtime_status()

    def _watch_ath_process(self, process: subprocess.Popen[bytes], output_dir: Path, cfg_path: Path) -> None:
        return_code = process.wait()
        if return_code == 0:
            for _ in range(20):
                if find_generated_preview_file(output_dir, cfg_path) is not None:
                    break
                time.sleep(0.25)
        self.app.after(0, lambda: self._finish_ath_run(return_code, output_dir, cfg_path))

    def run_ath(self, *, run_state: dict[str, object] | None = None, cfg_path_override: Path | None = None) -> None:
        if not ATH_EXE.exists():
            messagebox.showerror(APP_TITLE, f"找不到 ATH 執行檔：\n{ATH_EXE}")
            return
        if self.app.ath_process is not None and self.app.ath_process.poll() is None:
            messagebox.showinfo(APP_TITLE, "ATH 正在執行中，請等待完成。")
            return

        if not self.app.save_global_config(silent=True):
            return

        if run_state is None:
            if not self.app.save_horn_config():
                return
            cfg_path = self.app.current_horn_path.get().strip()
            if not cfg_path:
                messagebox.showerror(APP_TITLE, "目前沒有可執行的號角設定檔。")
                return
            cfg_file = Path(cfg_path)
        else:
            cfg_text = str(cfg_path_override) if cfg_path_override is not None else self.app.current_horn_path.get().strip()
            if not cfg_text.strip():
                messagebox.showerror(APP_TITLE, "目前沒有可執行的號角設定檔。")
                return
            cfg_file = Path(cfg_text)
            cfg_file.write_text(render_horn_text(run_state), encoding="utf-8", newline="\n")
            self.app.current_horn_path.set(str(cfg_file))
            cfg_path = str(cfg_file)

        global_state = self.app.collect_global_state()
        horn_state = dict(run_state) if run_state is not None else self.app.collect_effective_horn_state()
        output_dir = compute_output_directory(global_state, horn_state, cfg_file)
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        try:
            self.app.ath_process = subprocess.Popen([str(ATH_EXE), cfg_path], cwd=str(ATH_RUNTIME_DIR), creationflags=flags)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"啟動 ath.exe 失敗：\n{exc}")
            return

        threading.Thread(
            target=self._watch_ath_process,
            args=(self.app.ath_process, output_dir, cfg_file),
            daemon=True,
        ).start()
        self.app.preview_status_var.set("預覽狀態：ATH 執行中")
        self.app.status_var.set(f"已啟動 ATH：{cfg_path}。完成後將自動載入預覽。")
        self.app._update_runtime_status()
