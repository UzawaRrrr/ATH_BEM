"""GUI field definitions for Optuna study controls."""

from __future__ import annotations

from .specs import FieldSpec


OPTIMIZER_STUDY_FIELDS = (
    FieldSpec(
        "OPT.Stage",
        "Scoring stage",
        kind="combo",
        default="coarse",
        choices=("coarse", "refine", "final"),
        hint="coarse = 快速篩選，refine = 中期收斂，final = 完整評分。",
    ),
    FieldSpec("OPT.Trials", "Trial 數", default="10", hint="第一版 GUI 建議先從 5~20 trials 開始。"),
    FieldSpec(
        "OPT.Planes",
        "評分平面",
        kind="combo",
        default="XZ+YZ",
        choices=("XZ+YZ", "XZ", "YZ"),
        hint="XZ+YZ 會同時評估水平與垂直平面；時間也會較長。",
    ),
    FieldSpec("OPT.StudyName", "Study 名稱", default="", width=40, hint="留白時會自動以 case_name + 時間戳命名。"),
    FieldSpec("OPT.StudyDir", "Study 輸出目錄", default="", browse="dir", width=52),
    FieldSpec(
        "OPT.Storage",
        "Optuna storage",
        default="",
        width=52,
        hint="可選，例如 sqlite:///C:/Users/<you>/AppData/Local/ATH_BEM/workspace/studies/optuna/optuna.db",
    ),
    FieldSpec("OPT.Seed", "Sampler seed", default="42"),
    FieldSpec("OPT.EnqueueBase", "先跑 base recipe", kind="check", default=True, emit_default=True),
)


OPTIMIZER_OBJECTIVE_FIELDS = (
    FieldSpec("OPT.TargetBWH", "目標水平 BW [deg]", default="", hint="留白 = 不指定固定水平 beamwidth 目標。"),
    FieldSpec("OPT.TargetBWV", "目標垂直 BW [deg]", default="", hint="留白 = 不指定固定垂直 beamwidth 目標。"),
)


OPTIMIZER_CONSTRAINT_FIELDS = (
    FieldSpec(
        "OPT.DriverProfilePath",
        "Driver profile JSON",
        default="",
        browse="file",
        width=52,
        hint="可選；留白時會從目前 GUI recipe 保守推估 driver profile。",
    ),
    FieldSpec("OPT.MaxBaffleWidth", "最大障板寬 [mm]", default=""),
    FieldSpec("OPT.MaxBaffleHeight", "最大障板高 [mm]", default=""),
    FieldSpec("OPT.MaxDepth", "最大深度 [mm]", default=""),
    FieldSpec("OPT.MinWallThickness", "最小壁厚 [mm]", default=""),
    FieldSpec("OPT.TargetLowFreq", "目標最低頻 [Hz]", default=""),
    FieldSpec("OPT.TargetHighFreq", "目標最高頻 [Hz]", default=""),
)


OPTIMIZER_FIELD_SECTIONS = (
    ("Study / sampler 控制。", OPTIMIZER_STUDY_FIELDS),
    ("Objective 目標設定。", OPTIMIZER_OBJECTIVE_FIELDS),
    ("Driver / product constraints。", OPTIMIZER_CONSTRAINT_FIELDS),
)


def default_optimizer_state() -> dict[str, object]:
    """Return the default GUI state for optimization controls."""
    fields = (*OPTIMIZER_STUDY_FIELDS, *OPTIMIZER_OBJECTIVE_FIELDS, *OPTIMIZER_CONSTRAINT_FIELDS)
    return {spec.key: spec.default for spec in fields}
