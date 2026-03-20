"""Workflow-level controllers for ATH and BEM execution paths."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from tkinter import messagebox
from typing import Any

from ...domain.specs import APP_TITLE, ATH_EXE, ROOT_DIR
from ...infrastructure.bem_bridge import start_bem_solver, windows_path_to_wsl
from ...infrastructure.bem_results import (
    create_bem_result_run_dir,
    default_bem_result_dir,
    write_latest_bem_result_dir,
)
from ...infrastructure.bem_state import build_job_payload
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
            compute_output_directory(self.app.collect_global_state(), self.app.collect_horn_state(), Path(cfg_path)),
            Path(cfg_path),
        )
        if preview_file is None:
            messagebox.showinfo(APP_TITLE, "目前專案尚未找到可預覽的 .geo / .msh / .stl 輸出檔。")
            return
        self.app.load_embedded_preview_file(preview_file)
        self.app.autofill_bem_mesh(set_status=False)
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
            self.app.bem_status_var.set("完成")
            self.app.status_var.set(f"BEM 執行完成，結果已從 {result_dir} 載入。")
            self.app._update_runtime_status()
            return

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

        bem_state = self.app.collect_bem_state()
        mesh_path_text = str(bem_state.get("BEM.MeshFile", "")).strip()
        mesh_file = Path(mesh_path_text) if mesh_path_text else self.app.autofill_bem_mesh(set_status=False)
        if mesh_file is None or not Path(mesh_file).exists():
            messagebox.showerror(
                APP_TITLE,
                "目前沒有可供 BEM 使用的 `.msh` 檔。\n\n請啟用 `Output.MSH = 1` 並執行 ATH，或手動指定網格檔。",
            )
            return

        global_state = self.app.collect_global_state()
        horn_state = self.app.collect_horn_state()
        output_dir = compute_output_directory(global_state, horn_state, Path(cfg_path))
        result_dir = create_bem_result_run_dir(
            output_dir,
            cfg_path=Path(cfg_path),
            mesh_file=Path(mesh_file),
        )
        job_file = result_dir / "job.json"
        log_file = result_dir / "solver.log"

        try:
            payload = build_job_payload(bem_state, Path(mesh_file), windows_path_to_wsl(Path(mesh_file)))
            job_file.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
            self.app.bem_launch = start_bem_solver(job_file, log_file)
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
        self.app.autofill_bem_mesh(set_status=False)
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

    def run_ath(self) -> None:
        if not ATH_EXE.exists():
            messagebox.showerror(APP_TITLE, f"找不到 ATH 執行檔：\n{ATH_EXE}")
            return
        if self.app.ath_process is not None and self.app.ath_process.poll() is None:
            messagebox.showinfo(APP_TITLE, "ATH 正在執行中，請等待完成。")
            return

        global_state = self.app.collect_global_state()
        horn_state = self.app.collect_horn_state()
        if not self.app.save_global_config(silent=True):
            return
        if not self.app.save_horn_config():
            return

        cfg_path = self.app.current_horn_path.get().strip()
        if not cfg_path:
            messagebox.showerror(APP_TITLE, "目前沒有可執行的號角設定檔。")
            return

        cfg_file = Path(cfg_path)
        output_dir = compute_output_directory(global_state, horn_state, cfg_file)
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        try:
            self.app.ath_process = subprocess.Popen([str(ATH_EXE), cfg_path], cwd=str(ROOT_DIR), creationflags=flags)
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
