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
        self._completed_best_trial_summary: dict[str, Any] | None = None
        self._base_recipe_snapshot: DesignRecipe | None = None

    def _extract_display_params_from_frozen_trial(self, trial: Any) -> dict[str, Any]:
        user_attrs = dict(getattr(trial, "user_attrs", {}) or {})
        actual_params = user_attrs.get("design_space.actual_params")
        if isinstance(actual_params, dict):
            return dict(actual_params)
        return dict(getattr(trial, "params", {}) or {})

    def _extract_display_params_from_summary(self, summary: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(summary or {})
        user_attrs = dict(payload.get("user_attrs", {}) or {})
        actual_params = user_attrs.get("design_space.actual_params")
        if isinstance(actual_params, dict):
            return dict(actual_params)
        params = payload.get("params", {})
        if isinstance(params, dict) and params:
            return dict(params)
        return dict(payload.get("raw_params", {}) or {})

    def _extract_recipe_apply_params(self, summary: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
        payload = dict(summary or {})
        user_attrs = dict(payload.get("user_attrs", {}) or {})
        actual_params = user_attrs.get("design_space.actual_params")
        if isinstance(actual_params, dict) and actual_params:
            return dict(actual_params), "decoded"
        params = payload.get("params", {})
        if isinstance(params, dict) and params:
            return dict(params), "summary_params"
        raw_params = payload.get("raw_params", {})
        if isinstance(raw_params, dict) and raw_params:
            return dict(raw_params), "raw_params"
        return {}, "missing"

    def _extract_raw_params_from_summary(self, summary: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(summary or {})
        return dict(payload.get("raw_params", {}) or {})

    def _build_best_trial_summary(
        self,
        *,
        number: Any,
        value: Any,
        params: dict[str, Any],
        raw_params: dict[str, Any],
        user_attrs: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "number": number,
            "value": value,
            "params": dict(params),
            "raw_params": dict(raw_params),
            "user_attrs": dict(user_attrs),
        }

    def _summarize_best_recipe_updates(
        self,
        base_recipe: DesignRecipe,
        summary: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str], str]:
        params, source = self._extract_recipe_apply_params(summary)
        direct_updates = {
            key: value
            for key, value in params.items()
            if key in DesignRecipe.__dataclass_fields__
        }
        validation_errors: list[str] = []
        if direct_updates:
            candidate = replace(base_recipe, **direct_updates)
            validation_errors = candidate.validate()
        return params, direct_updates, validation_errors, source

    def _recipe_from_best_summary(
        self,
        base_recipe: DesignRecipe,
        summary: dict[str, Any] | None,
    ) -> tuple[DesignRecipe | None, dict[str, Any], str, str]:
        params, direct_updates, validation_errors, source = self._summarize_best_recipe_updates(base_recipe, summary)
        if not params:
            return None, {}, "no decoded best params available", source
        if not direct_updates:
            return None, {}, "decoded best params do not intersect with DesignRecipe fields", source
        if validation_errors:
            return None, direct_updates, "candidate base recipe from previous best is invalid: " + " | ".join(validation_errors), source
        return replace(base_recipe, **direct_updates), direct_updates, "", source

    def _summary_is_catastrophic_or_hard_fail(self, summary: dict[str, Any] | None) -> bool:
        payload = dict(summary or {})
        user_attrs = dict(payload.get("user_attrs", {}) or {})
        if bool(user_attrs.get("flags.catastrophic", False)):
            return True
        if bool(user_attrs.get("feasibility.hard_fail", False)):
            return True
        feasibility = user_attrs.get("feasibility")
        if isinstance(feasibility, dict) and bool(feasibility.get("hard_fail", False)):
            return True
        value = payload.get("value")
        try:
            return value is not None and float(value) >= self._catastrophic_threshold()
        except Exception:
            return False

    def _append_best_param_mismatch_log(self, summary: dict[str, Any] | None) -> None:
        params = self._extract_display_params_from_summary(summary)
        available_keys = sorted(params)
        recipe_fields = sorted(DesignRecipe.__dataclass_fields__)
        intersection = sorted(set(available_keys).intersection(recipe_fields))
        self.app.append_optimizer_log(f"[control] available best param keys={available_keys}")
        self.app.append_optimizer_log(f"[control] DesignRecipe field keys={recipe_fields}")
        self.app.append_optimizer_log(f"[control] applicable intersection count={len(intersection)}")

    def _catastrophic_threshold(self) -> float:
        try:
            from optimizer.score_defaults import DEFAULT_CATASTROPHIC_SCORE

            return float(DEFAULT_CATASTROPHIC_SCORE)
        except Exception:
            return 1000.0

    def _append_trial_diagnostics(self, payload: dict[str, Any], *, context: str) -> None:
        value = payload.get("value")
        try:
            numeric_value = float(value) if value is not None else None
        except Exception:
            numeric_value = None
        catastrophic = bool(payload.get("catastrophic", False))
        threshold = float(payload.get("catastrophic_score", self._catastrophic_threshold()) or self._catastrophic_threshold())
        user_attrs = dict(payload.get("user_attrs", {}) or {})
        flags = dict(payload.get("flags", {}) or {})
        if not flags:
            flags = {
                str(key).removeprefix("flags."): flag_value
                for key, flag_value in user_attrs.items()
                if str(key).startswith("flags.")
            }
        feasibility = payload.get("feasibility")
        if not isinstance(feasibility, dict):
            feasibility = user_attrs.get("feasibility")
        hard_fail = False
        issues: list[dict[str, Any]] = []
        if isinstance(feasibility, dict):
            hard_fail = bool(feasibility.get("hard_fail", False))
            raw_issues = feasibility.get("issues", [])
            if isinstance(raw_issues, list):
                issues = [dict(issue) for issue in raw_issues if isinstance(issue, dict)]
        if not (catastrophic or hard_fail or (numeric_value is not None and numeric_value >= threshold)):
            return

        evaluation_stage = str(payload.get("evaluation_stage", "")).strip().lower()
        if not evaluation_stage:
            evaluation_stage = "preflight" if hard_fail else "objective"
        score_pre_feasibility = payload.get("score_pre_feasibility", user_attrs.get("score.pre_feasibility"))
        score_objective_raw = payload.get("score_objective_raw", user_attrs.get("score.objective_raw"))

        trial_number = payload.get("trial_number", "?")
        self.app.append_optimizer_log(
            f"[trial {trial_number}] catastrophic score triggered during {context}; "
            f"value={numeric_value} stage={evaluation_stage} hard_fail={hard_fail} "
            f"score.pre_feasibility={score_pre_feasibility} score.objective_raw={score_objective_raw} "
            f"flags={json.dumps(flags, ensure_ascii=True, sort_keys=True)}"
        )
        if evaluation_stage == "preflight":
            self.app.append_optimizer_log(
                f"[trial {trial_number}] preflight feasibility rejected this geometry before solver/objective execution."
            )
        for issue in issues[:6]:
            code = issue.get("code", "unknown")
            message = issue.get("message", "")
            self.app.append_optimizer_log(f"[trial {trial_number}] issue: {code} | {message}")
        recipe_preview = payload.get("recipe_preview")
        if recipe_preview is None:
            recipe_preview = user_attrs.get("recipe.preview")
        if isinstance(recipe_preview, dict):
            snippet = {
                key: recipe_preview[key]
                for key in ("throat_diameter", "horn_length", "coverage_angle", "mouth_width", "mouth_height", "mouth_corner_radius")
                if key in recipe_preview
            }
            if snippet:
                self.app.append_optimizer_log(
                    f"[trial {trial_number}] recipe.preview={json.dumps(snippet, ensure_ascii=True, sort_keys=True)}"
                )

    def is_running(self) -> bool:
        thread = self._study_thread
        return thread is not None and thread.is_alive()

    def start_from_ui(self) -> None:
        with self._lock:
            if self.is_running():
                messagebox.showinfo(APP_TITLE, "最佳化目前正在執行中，請等待目前 study 完成。")
                return
            previous_best_summary = self.best_trial_summary or self._completed_best_trial_summary
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

            effective_base_recipe = DesignRecipe.from_dict(base_recipe.to_dict())
            handoff_message = ""
            handoff_warning = ""
            previous_is_catastrophic = self._summary_is_catastrophic_or_hard_fail(previous_best_summary)
            if study_config.stage in {"refine", "final"} and previous_best_summary is not None and not previous_is_catastrophic:
                candidate_recipe, direct_updates, reason, source = self._recipe_from_best_summary(base_recipe, previous_best_summary)
                if candidate_recipe is not None:
                    effective_base_recipe = DesignRecipe.from_dict(candidate_recipe.to_dict())
                    handoff_message = (
                        f"[handoff] using previous best trial as base recipe for stage {study_config.stage}; "
                        f"updated fields={sorted(direct_updates)} source={source}"
                    )
                    study_metadata["base_recipe_source"] = "previous_best_trial"
                    study_metadata["base_recipe_handoff_fields"] = sorted(direct_updates)
                    study_metadata["base_recipe_handoff_param_source"] = source
                    if source != "decoded":
                        handoff_warning = (
                            f"[handoff] decoded best params were unavailable; falling back to {source} while preparing stage {study_config.stage}."
                        )
                else:
                    handoff_message = (
                        f"[handoff] previous best trial was available but could not be mapped to a new base recipe; "
                        f"falling back to current GUI state ({reason}; source={source})"
                    )
                    study_metadata["base_recipe_source"] = "current_gui_state_fallback"
            elif study_config.stage in {"refine", "final"} and previous_best_summary is not None and previous_is_catastrophic:
                handoff_message = (
                    f"[handoff] previous best trial is catastrophic or feasibility-hard-failed (value={previous_best_summary.get('value')}); "
                    "falling back to current GUI state for this study."
                )
                study_metadata["base_recipe_source"] = "current_gui_state_catastrophic_fallback"
            else:
                study_metadata["base_recipe_source"] = "current_gui_state"

            self._base_recipe_snapshot = DesignRecipe.from_dict(effective_base_recipe.to_dict())
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
            if handoff_message:
                self.app.append_optimizer_log(handoff_message)
            if handoff_warning:
                self.app.append_optimizer_log(handoff_warning)
            self.app._refresh_status_card_summary()

            self._study_thread = threading.Thread(
                target=self._run_study_worker,
                args=(effective_base_recipe, base_horn_state, base_bem_state, base_global_state, study_config, study_metadata),
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
        summary = self.best_trial_summary or self._completed_best_trial_summary
        if summary is None or self._base_recipe_snapshot is None:
            messagebox.showinfo(APP_TITLE, "目前尚無可套用的最佳 trial。")
            return
        best_params, direct_updates, validation_errors, source = self._summarize_best_recipe_updates(self._base_recipe_snapshot, summary)
        if source != "decoded":
            self.app.append_optimizer_log(
                f"[control] decoded best params were unavailable during apply-back; falling back to {source}. "
                "Only DesignRecipe-compatible keys will be applied."
            )
        if not direct_updates:
            self._append_best_param_mismatch_log(summary)
            messagebox.showinfo(APP_TITLE, "目前最佳 trial 沒有可直接套用到 DesignRecipe 的參數。")
            return
        if validation_errors:
            self.app.append_optimizer_log(
                "[control] best trial could not be applied because the resulting DesignRecipe is invalid: "
                + " | ".join(validation_errors)
            )
            messagebox.showerror(APP_TITLE, "最佳 trial 無法套回 GUI，因為產生的 DesignRecipe 無效。")
            return
        recipe = replace(self._base_recipe_snapshot, **direct_updates)
        self.app.apply_design_recipe(recipe)
        self._base_recipe_snapshot = DesignRecipe.from_dict(recipe.to_dict())
        source_label = "decoded best trial" if source == "decoded" else f"{source} best trial fallback"
        self.app.status_var.set(f"已將 {source_label} 套用回目前 GUI 欄位，現在 GUI 已切換成最佳 trial 作為基底。")
        self.app.notebook.select(self.app.control_tabs["QuickStart"])
        self.app.append_optimizer_log(
            f"[control] {source_label} applied to GUI fields={sorted(direct_updates)}; "
            "current GUI state is now the active optimization base."
        )

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
            summary = self._build_best_trial_summary(
                number=best_trial.number,
                value=best_trial.value,
                params=self._extract_display_params_from_frozen_trial(best_trial),
                raw_params=dict(best_trial.params),
                user_attrs=dict(best_trial.user_attrs),
            )
            self.best_trial_summary = summary
            self._completed_best_trial_summary = dict(summary)
            self.app.after(0, lambda: self._apply_final_success(result.study.study_name, result.study.best_value))
        except Exception as exc:
            # Capture the exception object eagerly for Tk's deferred callback.
            # Python 3.13 clears `exc` at the end of the except block, so a
            # plain closure here can raise NameError later inside `after()`.
            self.app.after(0, lambda error=exc: self._apply_final_error(error))
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
            strategy = str(payload.get("constraint_strategy", "")).strip()
            if strategy:
                self.app.append_optimizer_log(f"[study] constraint strategy={strategy}")
            for note in payload.get("constraint_warnings", []) or []:
                self.app.append_optimizer_log(f"[study] constraint note: {note}")
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
            self._append_trial_diagnostics(payload, context="trial_scored")
            self.app._refresh_status_card_summary()
            return

        if event == "trial_completed":
            value = payload.get("value")
            best_value = payload.get("best_value")
            best_params = dict(payload.get("best_params", {}))
            best_raw_params = dict(payload.get("best_raw_params", {}))
            best_user_attrs = dict(payload.get("best_user_attrs", {}))
            if best_value is not None:
                self.app.optimizer_best_score_var.set(f"Best score: {float(best_value):.6f}")
                self.app.set_optimizer_best_text(self._format_best_trial_text(best_params, best_user_attrs, best_value, raw_params=best_raw_params))
                summary = self._build_best_trial_summary(
                    number=payload.get("best_number"),
                    value=best_value,
                    params=best_params,
                    raw_params=best_raw_params,
                    user_attrs=best_user_attrs,
                )
                self.best_trial_summary = summary
                self._completed_best_trial_summary = dict(summary)
            self.app.optimizer_status_var.set(f"Trial {payload.get('trial_number', '?')} completed")
            self.app.append_optimizer_log(
                f"[trial {payload.get('trial_number', '?')}] completed value={value} best={best_value}"
            )
            self._append_trial_diagnostics(payload, context="trial_completed")
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
                best_params = dict(payload.get("best_params", {}) or {})
                best_raw_params = dict(payload.get("best_raw_params", {}) or {})
                best_user_attrs = dict(payload.get("best_user_attrs", {}) or {})
                self.app.set_optimizer_best_text(self._format_best_trial_text(best_params, best_user_attrs, best_value, raw_params=best_raw_params))
                summary = self._build_best_trial_summary(
                    number=payload.get("best_number"),
                    value=best_value,
                    params=best_params,
                    raw_params=best_raw_params,
                    user_attrs=best_user_attrs,
                )
                self.best_trial_summary = summary
                self._completed_best_trial_summary = dict(summary)
            self.app.optimizer_status_var.set("Study completed")
            self.app.append_optimizer_log(f"[study] completed after {payload.get('completed_trials', 0)} trials")
            self._append_trial_diagnostics(
                {
                    "trial_number": payload.get("best_number", "?"),
                    "value": payload.get("best_value"),
                    "catastrophic": payload.get("best_catastrophic", False),
                    "catastrophic_score": self._catastrophic_threshold(),
                    "feasibility": payload.get("best_feasibility"),
                    "flags": payload.get("best_flags", {}),
                    "recipe_preview": payload.get("best_recipe_preview"),
                    "score_pre_feasibility": payload.get("best_score_pre_feasibility"),
                    "score_objective_raw": payload.get("best_score_objective_raw"),
                    "evaluation_stage": payload.get("best_evaluation_stage"),
                },
                context="study_completed.best",
            )
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
        from optimizer.driver_profile import ProductConstraints

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

        def _as_optional_path(key: str) -> Path | None:
            text = str(optimizer_state.get(key, "")).strip()
            if not text:
                return None
            return Path(text).expanduser().resolve()

        stage = str(optimizer_state.get("OPT.Stage", "coarse")).strip().lower() or "coarse"
        if stage not in {"coarse", "refine", "final"}:
            raise ValueError(f"Unsupported OPT.Stage: {stage}")
        planes = parse_planes_spec(optimizer_state.get("OPT.Planes", "XZ+YZ"))
        study_dir_text = str(optimizer_state.get("OPT.StudyDir", "")).strip()
        study_dir = Path(study_dir_text).expanduser().resolve() if study_dir_text else None
        storage_text = str(optimizer_state.get("OPT.Storage", "")).strip() or None
        study_name = str(optimizer_state.get("OPT.StudyName", "")).strip() or f"{base_recipe.case_name}_gui"
        driver_profile_path = _as_optional_path("OPT.DriverProfilePath")
        product_constraints = ProductConstraints(
            max_baffle_width_mm=_as_optional_float("OPT.MaxBaffleWidth"),
            max_baffle_height_mm=_as_optional_float("OPT.MaxBaffleHeight"),
            max_depth_mm=_as_optional_float("OPT.MaxDepth"),
            min_wall_thickness_mm=_as_optional_float("OPT.MinWallThickness"),
            target_low_freq_hz=_as_optional_float("OPT.TargetLowFreq"),
            target_high_freq_hz=_as_optional_float("OPT.TargetHighFreq"),
        )
        if not any(
            value is not None
            for value in (
                product_constraints.max_baffle_width_mm,
                product_constraints.max_baffle_height_mm,
                product_constraints.max_depth_mm,
                product_constraints.min_wall_thickness_mm,
                product_constraints.target_low_freq_hz,
                product_constraints.target_high_freq_hz,
            )
        ):
            product_constraints = None

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
            driver_profile_path=driver_profile_path,
            product_constraints=product_constraints,
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
            "driver_profile_path": None if driver_profile_path is None else str(driver_profile_path),
            "product_constraints": None if product_constraints is None else product_constraints.to_dict(),
        }
        metadata["planes"] = planes
        return config, metadata

    def _format_best_trial_text(
        self,
        best_params: dict[str, Any],
        best_user_attrs: dict[str, Any],
        best_value: float,
        *,
        raw_params: dict[str, Any] | None = None,
    ) -> str:
        lines = [
            f"Best objective: {float(best_value):.6f}",
            "",
            "Decoded Params:",
        ]
        if best_params:
            lines.extend(f"- {key}: {value}" for key, value in sorted(best_params.items()))
        else:
            lines.append("(none)")
        raw_payload = dict(raw_params or {})
        if raw_payload and raw_payload != best_params:
            lines.extend(["", "Raw Optuna Params:"])
            lines.extend(f"- {key}: {value}" for key, value in sorted(raw_payload.items()))

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
