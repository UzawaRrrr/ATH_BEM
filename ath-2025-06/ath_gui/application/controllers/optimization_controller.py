"""GUI controller for Optuna-based optimization studies."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox
from typing import Any

from ...domain.design_recipe import DesignRecipe
from ...domain.specs import APP_TITLE
from ...infrastructure.bem_state import build_bem_runtime_settings
from ...infrastructure.bem_bridge import DEFAULT_WSL_VENV, DEFAULT_WSL_SOLVER_ENTRY
from ...infrastructure.bem_state import sanitize_bem_state
from ...domain.config_core import sanitize_ath_state
from ...domain.auto_enclosure import derive_auto_enclosure


class OptimizationController:
    """Coordinate GUI-driven Optuna studies without coupling Tk to scorer internals."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._study_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop_after_trial = threading.Event()
        self.latest_study_dir: Path | None = None
        self.best_trial_summary: dict[str, Any] | None = None
        self._base_recipe_snapshot: DesignRecipe | None = None

    def is_running(self) -> bool:
        thread = self._study_thread
        return thread is not None and thread.is_alive()

    def start_from_ui(self) -> None:
        with self._lock:
            if self.is_running():
                messagebox.showinfo(APP_TITLE, "最佳化目前正在執行中，請等待目前 study 完成。")
                return
            try:
                if getattr(self.app, "_quick_dirty", False):
                    self.app.sync_quick_to_horn()
                base_recipe = self.app.collect_design_recipe()
                base_horn_state = self.app.collect_horn_state(normalize_locked=True)
                base_bem_state = self.app.collect_bem_state()
                base_global_state = self.app.collect_global_state()
                optimizer_state = self.app.collect_optimizer_state()
                study_config, study_metadata = self._build_study_settings(optimizer_state, base_recipe)
            except Exception as exc:
                messagebox.showerror(APP_TITLE, f"最佳化參數解析失敗：\n{exc}")
                return

            self._base_recipe_snapshot = DesignRecipe.from_dict(base_recipe.to_dict())
            self.best_trial_summary = None
            self.latest_study_dir = study_config.study_dir
            self._stop_after_trial.clear()
            self.app.clear_optimizer_log()
            self.app.set_optimizer_best_text("尚未產生任何最佳 trial。")
            self.app.optimizer_status_var.set("準備啟動最佳化...")
            self.app.optimizer_trial_var.set(f"Trial: 0 / {study_config.trials}")
            self.app.optimizer_best_score_var.set("Best score: (none)")
            self.app.optimizer_study_dir_var.set(str(study_config.study_dir or "(auto)"))
            self.app.status_var.set("最佳化準備中...")
            self.app._select_workspace_tab("Study")
            self.app._refresh_status_card_summary()

            self._study_thread = threading.Thread(
                target=self._run_study_worker,
                args=(base_recipe, base_horn_state, base_bem_state, base_global_state, study_config, study_metadata),
                daemon=True,
            )
            self._study_thread.start()

    def request_stop_after_trial(self) -> None:
        if not self.is_running():
            messagebox.showinfo(APP_TITLE, "目前沒有正在執行的最佳化 study。")
            return
        self._stop_after_trial.set()
        self.app.optimizer_status_var.set("已請求在目前 trial 完成後停止。")
        self.app.status_var.set("最佳化將在目前 trial 完成後停止。")
        self.app.append_optimizer_log("[control] stop requested after current trial")
        self.app._refresh_status_card_summary()

    def shutdown(self) -> None:
        """Request a cooperative stop when the GUI is closing."""
        self._stop_after_trial.set()

    def open_study_dir(self) -> None:
        if self.latest_study_dir is None or not self.latest_study_dir.exists():
            messagebox.showinfo(APP_TITLE, "目前尚無可開啟的 study 目錄。")
            return
        try:
            os.startfile(str(self.latest_study_dir))
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"無法開啟 study 目錄：\n{exc}")

    def apply_best_trial(self) -> None:
        if self.best_trial_summary is None or self._base_recipe_snapshot is None:
            messagebox.showinfo(APP_TITLE, "目前尚無可套用的最佳 trial。")
            return
        best_params = dict(self.best_trial_summary.get("params", {}))
        direct_updates = {
            key: value
            for key, value in best_params.items()
            if key in DesignRecipe.__dataclass_fields__
        }
        if not direct_updates:
            messagebox.showinfo(APP_TITLE, "目前最佳 trial 沒有可直接套用到 DesignRecipe 的參數。")
            return
        recipe = replace(self._base_recipe_snapshot, **direct_updates)
        self.app.apply_design_recipe(recipe)
        self.app.status_var.set("已將最佳 trial 套用回目前 GUI 欄位。")
        self.app.notebook.select(self.app.control_tabs["QuickStart"])
        self.app.append_optimizer_log("[control] best trial applied to GUI fields")

    def _run_study_worker(
        self,
        base_recipe: DesignRecipe,
        base_horn_state: dict[str, object],
        base_bem_state: dict[str, object],
        base_global_state: dict[str, object],
        study_config: Any,
        study_metadata: dict[str, Any],
    ) -> None:
        try:
            from optimizer.headless_case_runner import HeadlessCaseRunner
            from optimizer.study_runner import run_optuna_study, suggest_default_params, write_study_artifacts

            ath_state = base_recipe.to_ath_state(base_state=base_horn_state)
            if base_recipe.auto_enclosure_enabled:
                ath_state = derive_auto_enclosure(ath_state)
            ath_state = sanitize_ath_state(ath_state)
            bem_runtime = build_bem_runtime_settings(sanitize_bem_state(base_bem_state, ath_state), ath_state)
            launch_options = dict(bem_runtime.get("launch_options", {}))

            runner = HeadlessCaseRunner(
                base_recipe=base_recipe,
                base_global_state=base_global_state,
                base_horn_state=base_horn_state,
                base_bem_state=base_bem_state,
                projects_root=None,
                planes=study_metadata["planes"],
                backend=str(bem_runtime.get("backend", "wsl")),
                wsl_venv=str(launch_options.get("wsl_venv", DEFAULT_WSL_VENV)),
                wsl_solver_entry=str(launch_options.get("wsl_solver_entry", DEFAULT_WSL_SOLVER_ENTRY)),
                local_solver_python=str(launch_options.get("local_python_exe", "")),
                conda_exe=str(launch_options.get("conda_exe", "conda")),
                conda_env=str(launch_options.get("conda_env", "bempp")),
            )

            result = run_optuna_study(
                base_recipe=base_recipe,
                case_runner=runner,
                config=study_config,
                suggest_fn=suggest_default_params,
                on_event=self._handle_study_event,
                stop_event=self._stop_after_trial,
            )
            write_study_artifacts(result.study, result.study_dir, metadata=study_metadata)
            self.latest_study_dir = result.study_dir
            best_trial = result.study.best_trial
            self.best_trial_summary = {
                "number": best_trial.number,
                "value": best_trial.value,
                "params": dict(best_trial.params),
                "user_attrs": dict(best_trial.user_attrs),
            }
            self.app.after(0, lambda: self._apply_final_success(result.study.study_name, result.study.best_value))
        except Exception as exc:
            self.app.after(0, lambda: self._apply_final_error(exc))
        finally:
            self._stop_after_trial.clear()
            with self._lock:
                self._study_thread = None

    def _handle_study_event(self, payload: dict[str, Any]) -> None:
        self.app.after(0, lambda: self._apply_study_event(payload))

    def _apply_study_event(self, payload: dict[str, Any]) -> None:
        event = str(payload.get("event", "")).strip()
        if event == "study_started":
            study_dir = str(payload.get("study_dir", "")).strip()
            self.latest_study_dir = Path(study_dir) if study_dir else None
            self.app.optimizer_status_var.set(f"Study started: {payload.get('study_name', '')}")
            self.app.optimizer_trial_var.set(f"Trial: 0 / {payload.get('trials', '?')}")
            self.app.optimizer_study_dir_var.set(study_dir or "(auto)")
            self.app.append_optimizer_log(f"[study] started {payload.get('study_name', '')}")
            self.app._refresh_status_card_summary()
            return

        if event == "trial_started":
            trial_index = int(payload.get("trial_index", 0))
            total_trials = int(payload.get("total_trials", 0))
            self.app.optimizer_status_var.set(f"Running trial {trial_index}/{total_trials}")
            self.app.optimizer_trial_var.set(f"Trial: {trial_index} / {total_trials}")
            self.app.append_optimizer_log(
                f"[trial {payload.get('trial_number', '?')}] started with params={json.dumps(payload.get('params', {}), ensure_ascii=True, sort_keys=True)}"
            )
            self.app._refresh_status_card_summary()
            return

        if event == "trial_scored":
            value = payload.get("value")
            self.app.append_optimizer_log(f"[trial {payload.get('trial_number', '?')}] score={value}")
            self.app._refresh_status_card_summary()
            return

        if event == "trial_completed":
            value = payload.get("value")
            best_value = payload.get("best_value")
            best_params = dict(payload.get("best_params", {}))
            best_user_attrs = dict(payload.get("best_user_attrs", {}))
            if best_value is not None:
                self.app.optimizer_best_score_var.set(f"Best score: {float(best_value):.6f}")
                self.app.set_optimizer_best_text(self._format_best_trial_text(best_params, best_user_attrs, best_value))
                self.best_trial_summary = {
                    "number": payload.get("best_number"),
                    "value": best_value,
                    "params": best_params,
                    "user_attrs": best_user_attrs,
                }
            self.app.optimizer_status_var.set(f"Trial {payload.get('trial_number', '?')} completed")
            self.app.append_optimizer_log(
                f"[trial {payload.get('trial_number', '?')}] completed value={value} best={best_value}"
            )
            self.app._refresh_status_card_summary()
            return

        if event == "stop_requested":
            self.app.optimizer_status_var.set("Stopping after current trial...")
            self.app.append_optimizer_log(f"[study] stop requested after trial {payload.get('after_trial', '?')}")
            self.app._refresh_status_card_summary()
            return

        if event == "study_completed":
            best_value = payload.get("best_value")
            if best_value is not None:
                self.app.optimizer_best_score_var.set(f"Best score: {float(best_value):.6f}")
            self.app.optimizer_status_var.set("Study completed")
            self.app.append_optimizer_log(f"[study] completed after {payload.get('completed_trials', 0)} trials")
            self.app._refresh_status_card_summary()
            return

    def _apply_final_success(self, study_name: str, best_value: float) -> None:
        self.app.optimizer_status_var.set(f"Study completed: {study_name}")
        self.app.status_var.set(f"最佳化完成，best score = {best_value:.6f}")
        self.app._select_workspace_tab("Study")
        self.app._refresh_status_card_summary()

    def _apply_final_error(self, exc: Exception) -> None:
        self.app.optimizer_status_var.set("Study failed")
        self.app.status_var.set(f"最佳化失敗：{exc}")
        self.app.append_optimizer_log(f"[error] {exc}")
        self.app._refresh_status_card_summary()
        messagebox.showerror(APP_TITLE, f"最佳化失敗：\n{exc}")

    def _build_study_settings(self, optimizer_state: dict[str, object], base_recipe: DesignRecipe) -> tuple[Any, dict[str, Any]]:
        from optimizer.study_runner import OptunaStudyConfig, parse_planes_spec

        def _as_int(key: str, *, minimum: int = 1) -> int:
            text = str(optimizer_state.get(key, "")).strip()
            value = int(float(text or minimum))
            if value < minimum:
                raise ValueError(f"{key} must be >= {minimum}")
            return value

        def _as_optional_float(key: str) -> float | None:
            text = str(optimizer_state.get(key, "")).strip()
            if not text:
                return None
            return float(text)

        stage = str(optimizer_state.get("OPT.Stage", "coarse")).strip().lower() or "coarse"
        if stage not in {"coarse", "refine", "final"}:
            raise ValueError(f"Unsupported OPT.Stage: {stage}")
        planes = parse_planes_spec(optimizer_state.get("OPT.Planes", "XZ+YZ"))
        study_dir_text = str(optimizer_state.get("OPT.StudyDir", "")).strip()
        study_dir = Path(study_dir_text).expanduser().resolve() if study_dir_text else None
        storage_text = str(optimizer_state.get("OPT.Storage", "")).strip() or None
        study_name = str(optimizer_state.get("OPT.StudyName", "")).strip() or f"{base_recipe.case_name}_gui"

        config = OptunaStudyConfig(
            trials=_as_int("OPT.Trials", minimum=1),
            stage=stage,
            target_bw_h_deg=_as_optional_float("OPT.TargetBWH"),
            target_bw_v_deg=_as_optional_float("OPT.TargetBWV"),
            study_name=study_name,
            study_dir=study_dir,
            storage=storage_text,
            seed=_as_int("OPT.Seed", minimum=0),
            enqueue_base=bool(optimizer_state.get("OPT.EnqueueBase", True)),
        )
        metadata = {
            "recipe_case_name": base_recipe.case_name,
            "stage": config.stage,
            "target_bw_h": config.target_bw_h_deg,
            "target_bw_v": config.target_bw_v_deg,
            "planes": list(planes),
            "study_name": config.study_name,
            "storage": config.storage,
            "seed": config.seed,
            "trials": config.trials,
        }
        metadata["planes"] = planes
        return config, metadata

    def _format_best_trial_text(self, best_params: dict[str, Any], best_user_attrs: dict[str, Any], best_value: float) -> str:
        lines = [
            f"Best objective: {float(best_value):.6f}",
            "",
            "Params:",
        ]
        if best_params:
            lines.extend(f"- {key}: {value}" for key, value in sorted(best_params.items()))
        else:
            lines.append("(none)")

        score_keys = (
            "score.total",
            "score.coverage",
            "score.cd",
            "score.hom",
            "score.room",
            "score.di",
            "score.load",
            "score.geom",
            "score.hard",
        )
        lines.extend(["", "Scores:"])
        for key in score_keys:
            if key in best_user_attrs:
                lines.append(f"- {key}: {best_user_attrs[key]}")

        flag_keys = sorted(key for key in best_user_attrs if key.startswith("flags."))
        if flag_keys:
            lines.extend(["", "Flags:"])
            lines.extend(f"- {key}: {best_user_attrs[key]}" for key in flag_keys)
        return "\n".join(lines)
