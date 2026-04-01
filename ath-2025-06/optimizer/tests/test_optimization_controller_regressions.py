from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ath_gui.application.controllers.optimization_controller import OptimizationController  # noqa: E402
from ath_gui.domain.design_recipe import DesignRecipe  # noqa: E402
from optimizer.score_defaults import DEFAULT_CATASTROPHIC_SCORE  # noqa: E402


class _Var:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: object) -> None:
        self.value = str(value)


class _Notebook:
    def __init__(self) -> None:
        self.selected: object | None = None

    def select(self, tab: object) -> None:
        self.selected = tab


class _FakeThread:
    def __init__(self, target, args=(), daemon: bool | None = None) -> None:
        self.target = target
        self.args = tuple(args)
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return False


class _FakeApp:
    def __init__(self, *, recipe: DesignRecipe, optimizer_state: dict[str, object] | None = None) -> None:
        self._recipe = DesignRecipe.from_dict(recipe.to_dict())
        self._optimizer_state = dict(optimizer_state or {})
        self._quick_dirty = False
        self.logs: list[str] = []
        self.best_text = ""
        self.applied_recipe: DesignRecipe | None = None
        self.selected_workspace_tab: str | None = None
        self.control_tabs = {"QuickStart": "BaseDesignTab"}
        self.notebook = _Notebook()
        self.optimizer_status_var = _Var()
        self.optimizer_trial_var = _Var()
        self.optimizer_best_score_var = _Var()
        self.optimizer_study_dir_var = _Var()
        self.status_var = _Var()

    def after(self, _delay_ms: int, callback) -> None:
        callback()

    def append_optimizer_log(self, message: str) -> None:
        self.logs.append(str(message))

    def clear_optimizer_log(self) -> None:
        self.logs.clear()

    def set_optimizer_best_text(self, text: str) -> None:
        self.best_text = str(text)

    def collect_design_recipe(self) -> DesignRecipe:
        return DesignRecipe.from_dict(self._recipe.to_dict())

    def collect_horn_state(self, *, normalize_locked: bool = True) -> dict[str, object]:
        return {"normalize_locked": normalize_locked}

    def collect_bem_state(self) -> dict[str, object]:
        return {"BEM.Backend": "wsl"}

    def collect_global_state(self) -> dict[str, object]:
        return {"Global.ProjectRoot": "fake"}

    def collect_optimizer_state(self) -> dict[str, object]:
        return dict(self._optimizer_state)

    def sync_quick_to_horn(self) -> None:
        self.logs.append("[fake] sync_quick_to_horn")

    def apply_design_recipe(self, recipe: DesignRecipe) -> None:
        self._recipe = DesignRecipe.from_dict(recipe.to_dict())
        self.applied_recipe = DesignRecipe.from_dict(recipe.to_dict())

    def _select_workspace_tab(self, tab_name: str) -> None:
        self.selected_workspace_tab = str(tab_name)

    def _refresh_status_card_summary(self) -> None:
        return None


def _make_recipe(**overrides: object) -> DesignRecipe:
    payload = {
        "case_name": "handoff_demo",
        "throat_diameter": 25.0,
        "horn_length": 180.0,
        "coverage_angle": 90.0,
        "mouth_width": 140.0,
        "mouth_height": 170.0,
        "mouth_corner_radius": 14.0,
        "source_mode": "normal",
        "source_velocity": 1.0,
        "bem_f1": 1000.0,
        "bem_f2": 8000.0,
        "bem_num_freq": 4,
        "observation_plane": "XZ",
    }
    payload.update(overrides)
    return DesignRecipe(**payload)


def _make_summary(
    *,
    value: float,
    params: dict[str, object] | None = None,
    raw_params: dict[str, object] | None = None,
    actual_params: dict[str, object] | None = None,
    catastrophic: bool = False,
) -> dict[str, object]:
    user_attrs: dict[str, object] = {"flags.catastrophic": catastrophic}
    if actual_params is not None:
        user_attrs["design_space.actual_params"] = dict(actual_params)
    return {
        "number": 1,
        "value": value,
        "params": dict(params or {}),
        "raw_params": dict(raw_params or {}),
        "user_attrs": user_attrs,
    }


def test_final_best_summary_keeps_decoded_and_raw_params_separate() -> None:
    base_recipe = _make_recipe()
    app = _FakeApp(recipe=base_recipe)
    controller = OptimizationController(app)

    decoded_params = {
        "horn_length": 222.0,
        "mouth_width": 168.0,
        "mouth_height": 188.0,
    }
    raw_params = {
        "unit__horn_length": 0.73,
        "unit__mouth_width": 0.61,
    }
    fake_best_trial = SimpleNamespace(
        number=7,
        value=12.5,
        params=dict(raw_params),
        user_attrs={"design_space.actual_params": dict(decoded_params)},
    )
    fake_study = SimpleNamespace(
        best_trial=fake_best_trial,
        best_value=12.5,
        study_name="coarse_demo",
    )
    fake_result = SimpleNamespace(study=fake_study, study_dir=Path(tempfile.gettempdir()))

    fake_headless_module = ModuleType("optimizer.headless_case_runner")

    class _FakeHeadlessRunner:
        def __init__(self, **kwargs) -> None:
            self.kwargs = dict(kwargs)

    fake_headless_module.HeadlessCaseRunner = _FakeHeadlessRunner

    fake_study_runner_module = ModuleType("optimizer.study_runner")
    fake_study_runner_module.run_optuna_study = lambda **_kwargs: fake_result
    fake_study_runner_module.suggest_default_params = lambda *_args, **_kwargs: {}
    fake_study_runner_module.write_study_artifacts = lambda *_args, **_kwargs: None

    with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
        sys.modules,
        {
            "optimizer.headless_case_runner": fake_headless_module,
            "optimizer.study_runner": fake_study_runner_module,
        },
        clear=False,
    ), patch(
        "ath_gui.application.controllers.optimization_controller.build_bem_runtime_settings",
        lambda _bem_state, _ath_state: {"backend": "wsl", "launch_options": {}},
    ), patch(
        "ath_gui.application.controllers.optimization_controller.sanitize_bem_state",
        lambda state, _ath_state: dict(state),
    ), patch(
        "ath_gui.application.controllers.optimization_controller.sanitize_ath_state",
        lambda state: dict(state),
    ), patch(
        "ath_gui.application.controllers.optimization_controller.derive_auto_enclosure",
        lambda state: dict(state),
    ):
        controller._run_study_worker(
            base_recipe,
            {},
            {},
            {},
            SimpleNamespace(stage="coarse", trials=1, study_dir=Path(tmp_dir)),
            {"planes": ("XZ", "YZ")},
        )

    assert controller.best_trial_summary is not None
    assert controller.best_trial_summary["params"] == decoded_params
    assert controller.best_trial_summary["raw_params"] == raw_params
    assert controller._completed_best_trial_summary is not None
    assert controller._completed_best_trial_summary["params"] == decoded_params
    assert controller._completed_best_trial_summary["raw_params"] == raw_params


def test_apply_best_trial_prefers_decoded_actual_params() -> None:
    base_recipe = _make_recipe(horn_length=180.0, mouth_width=140.0)
    app = _FakeApp(recipe=base_recipe)
    controller = OptimizationController(app)
    controller._base_recipe_snapshot = DesignRecipe.from_dict(base_recipe.to_dict())
    controller.best_trial_summary = _make_summary(
        value=10.0,
        params={"unit__horn_length": 0.20, "unit__mouth_width": 0.50},
        raw_params={"unit__horn_length": 0.20, "unit__mouth_width": 0.50},
        actual_params={"horn_length": 230.0, "mouth_width": 176.0, "mouth_height": 196.0},
    )

    with patch("ath_gui.application.controllers.optimization_controller.messagebox.showinfo", lambda *_a, **_k: None), patch(
        "ath_gui.application.controllers.optimization_controller.messagebox.showerror",
        lambda *_a, **_k: None,
    ):
        controller.apply_best_trial()

    assert app.applied_recipe is not None
    assert app.applied_recipe.horn_length == 230.0
    assert app.applied_recipe.mouth_width == 176.0
    assert app.applied_recipe.mouth_height == 196.0
    assert "最佳 trial 作為基底" in app.status_var.get()
    assert any("best trial applied to GUI" in line for line in app.logs)
    assert app.notebook.selected == "BaseDesignTab"


def test_refine_stage_uses_previous_non_catastrophic_best_as_effective_base_recipe() -> None:
    base_recipe = _make_recipe(horn_length=180.0, mouth_width=140.0)
    app = _FakeApp(
        recipe=base_recipe,
        optimizer_state={
            "OPT.Stage": "refine",
            "OPT.Trials": "3",
            "OPT.Planes": "XZ",
            "OPT.Seed": "42",
            "OPT.EnqueueBase": True,
        },
    )
    controller = OptimizationController(app)
    controller._completed_best_trial_summary = _make_summary(
        value=12.0,
        params={"horn_length": 240.0, "mouth_width": 180.0},
        raw_params={"unit__horn_length": 0.66},
        actual_params={"horn_length": 240.0, "mouth_width": 180.0, "mouth_height": 205.0},
    )

    fake_config = SimpleNamespace(stage="refine", trials=3, study_dir=Path(tempfile.gettempdir()))

    with patch.object(
        OptimizationController,
        "_build_study_settings",
        lambda self, _optimizer_state, _base_recipe: (fake_config, {"planes": ("XZ",)}),
    ), patch("ath_gui.application.controllers.optimization_controller.threading.Thread", _FakeThread), patch(
        "ath_gui.application.controllers.optimization_controller.messagebox.showinfo",
        lambda *_a, **_k: None,
    ), patch(
        "ath_gui.application.controllers.optimization_controller.messagebox.showerror",
        lambda *_a, **_k: None,
    ):
        controller.start_from_ui()

    assert isinstance(controller._study_thread, _FakeThread)
    effective_recipe = controller._study_thread.args[0]
    metadata = controller._study_thread.args[5]
    assert isinstance(effective_recipe, DesignRecipe)
    assert effective_recipe.horn_length == 240.0
    assert effective_recipe.mouth_width == 180.0
    assert effective_recipe.mouth_height == 205.0
    assert metadata["base_recipe_source"] == "previous_best_trial"
    assert any("using previous best trial as base recipe for stage refine" in line for line in app.logs)


def test_catastrophic_previous_best_falls_back_to_current_gui_state() -> None:
    base_recipe = _make_recipe(horn_length=185.0, mouth_width=142.0)
    app = _FakeApp(
        recipe=base_recipe,
        optimizer_state={
            "OPT.Stage": "final",
            "OPT.Trials": "2",
            "OPT.Planes": "XZ+YZ",
            "OPT.Seed": "7",
            "OPT.EnqueueBase": True,
        },
    )
    controller = OptimizationController(app)
    controller._completed_best_trial_summary = _make_summary(
        value=DEFAULT_CATASTROPHIC_SCORE,
        params={"horn_length": 260.0, "mouth_width": 210.0},
        raw_params={"unit__horn_length": 0.99},
        actual_params={"horn_length": 260.0, "mouth_width": 210.0},
        catastrophic=True,
    )

    fake_config = SimpleNamespace(stage="final", trials=2, study_dir=Path(tempfile.gettempdir()))

    with patch.object(
        OptimizationController,
        "_build_study_settings",
        lambda self, _optimizer_state, _base_recipe: (fake_config, {"planes": ("XZ", "YZ")}),
    ), patch("ath_gui.application.controllers.optimization_controller.threading.Thread", _FakeThread), patch(
        "ath_gui.application.controllers.optimization_controller.messagebox.showinfo",
        lambda *_a, **_k: None,
    ), patch(
        "ath_gui.application.controllers.optimization_controller.messagebox.showerror",
        lambda *_a, **_k: None,
    ):
        controller.start_from_ui()

    assert isinstance(controller._study_thread, _FakeThread)
    effective_recipe = controller._study_thread.args[0]
    metadata = controller._study_thread.args[5]
    assert isinstance(effective_recipe, DesignRecipe)
    assert effective_recipe.horn_length == base_recipe.horn_length
    assert effective_recipe.mouth_width == base_recipe.mouth_width
    assert metadata["base_recipe_source"] == "current_gui_state_catastrophic_fallback"
    assert any("previous best trial is catastrophic" in line for line in app.logs)


def test_catastrophic_trial_diagnostics_are_written_to_controller_log() -> None:
    app = _FakeApp(recipe=_make_recipe())
    controller = OptimizationController(app)

    controller._apply_study_event(
        {
            "event": "trial_scored",
            "trial_number": 5,
            "value": DEFAULT_CATASTROPHIC_SCORE,
            "catastrophic": True,
            "catastrophic_score": DEFAULT_CATASTROPHIC_SCORE,
            "score_pre_feasibility": DEFAULT_CATASTROPHIC_SCORE,
            "score_objective_raw": None,
            "evaluation_stage": "preflight",
            "feasibility": {
                "hard_fail": True,
                "issues": [
                    {
                        "code": "mouth_too_large",
                        "message": "mouth width exceeds inferred max_baffle_width_mm",
                    }
                ],
            },
            "flags": {"catastrophic": True, "any_missing": False},
            "recipe_preview": {
                "horn_length": 120.0,
                "mouth_width": 320.0,
                "mouth_height": 200.0,
            },
        }
    )

    joined = "\n".join(app.logs)
    assert "score=1000.0" in joined
    assert "catastrophic score triggered" in joined
    assert "hard_fail=True" in joined
    assert "stage=preflight" in joined
    assert "score.pre_feasibility=1000.0" in joined
    assert "before solver/objective execution" in joined
    assert "mouth_too_large" in joined
    assert "exceeds inferred max_baffle_width_mm" in joined
    assert "recipe.preview=" in joined
    assert "mouth_width" in joined


def _run_all() -> None:
    test_final_best_summary_keeps_decoded_and_raw_params_separate()
    test_apply_best_trial_prefers_decoded_actual_params()
    test_refine_stage_uses_previous_non_catastrophic_best_as_effective_base_recipe()
    test_catastrophic_previous_best_falls_back_to_current_gui_state()
    test_catastrophic_trial_diagnostics_are_written_to_controller_log()


if __name__ == "__main__":
    _run_all()
    print("test_optimization_controller_regressions.py: ok")
