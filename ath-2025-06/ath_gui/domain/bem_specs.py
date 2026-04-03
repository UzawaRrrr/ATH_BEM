"""BEM-specific GUI field definitions and defaults."""

from __future__ import annotations

from .specs import FieldSpec
from .runtime import RUNTIME_LAYOUT


BEM_AUTOMATION_FIELDS = (
    FieldSpec("BEM.Enabled", "啟用 BEM 自動流程", kind="check", default=True, emit_default=True),
    FieldSpec(
        "BEM.Backend",
        "BEM 執行後端",
        kind="combo",
        default="wsl",
        choices=("wsl", "local_python", "conda"),
        hint="wsl = 透過 WSL 啟動；local_python = 本機 Python；conda = conda run -n <env>。",
    ),
    FieldSpec(
        "BEM.MeshSourceMode",
        "網格來源模式",
        kind="combo",
        default="latest_ath_output",
        choices=("latest_ath_output", "manual_mesh_file"),
        hint="latest_ath_output 會優先使用最新 ATH 輸出；manual_mesh_file 則使用指定 .msh。",
    ),
    FieldSpec(
        "BEM.GroupMode",
        "群組指定模式",
        kind="combo",
        default="auto",
        choices=("auto", "manual"),
    ),
    FieldSpec(
        "BEM.AutoGroupStrategy",
        "自動分群策略",
        kind="combo",
        default="fixed_current",
        choices=("fixed_current", "name_heuristic"),
        hint="fixed_current = 使用目前 branch 的固定 mapping；name_heuristic = 依名稱/群組特徵猜測。",
    ),
    FieldSpec(
        "BEM.SolverMode",
        "求解器模式",
        kind="combo",
        default="exterior_velocity_bc",
        choices=("exterior_velocity_bc",),
    ),
    FieldSpec(
        "BEM.ObservationMode",
        "觀測模式",
        kind="combo",
        default="polar_map",
        choices=("polar_map", "custom_directivity"),
        hint="目前 solver 仍使用同一套觀測欄位；此欄位主要控制 Guided Setup 顯示與輸出偏好。",
    ),
    FieldSpec("BEM.WslVenv", "WSL Python venv", default=RUNTIME_LAYOUT.default_wsl_venv, width=52),
    FieldSpec("BEM.WslSolverEntry", "WSL solver 入口", default=RUNTIME_LAYOUT.default_wsl_solver_entry, width=52),
    FieldSpec("BEM.LocalPythonExe", "本機 Python", browse="file", width=52),
    FieldSpec("BEM.CondaExe", "Conda 執行檔", default="conda", browse="file", width=52),
    FieldSpec("BEM.CondaEnv", "Conda 環境名稱", default="bempp", width=32),
)

BEM_MESH_FIELDS = (
    FieldSpec(
        "BEM.MeshFile",
        "網格檔 (.msh)",
        browse="file",
        width=52,
        hint="預設會抓取目前 ATH 輸出目錄下最新的 `.msh` 檔。",
    ),
    FieldSpec("BEM.MeshScaleToMeter", "網格轉公尺比例", default="0.001"),
    FieldSpec("BEM.SourceGroups", "聲源群組", hint="以逗號分隔的群組 ID，例如 `2` 或 `2,5`。"),
    FieldSpec(
        "BEM.WallGroups",
        "壁面群組",
        hint="以逗號分隔的群組 ID。留白時，會把所有非聲源群組當作剛性壁面。",
    ),
    FieldSpec("BEM.InterfaceGroups", "介面群組", hint="預留給未來多域支援。"),
    FieldSpec("BEM.IgnoreGroups", "忽略群組", hint="可選；用來排除匯入邊界中的特定群組。"),
)

BEM_SOLVER_FIELDS = (
    FieldSpec(
        "BEM.SourceGain",
        "聲源增益",
        default="1.0",
        hint="以逗號分隔的法向速度振幅（m/s）。單一數值會套用到所有聲源。",
    ),
    FieldSpec(
        "BEM.SourceDirection",
        "聲源方向",
        default="0,0,1",
        hint="每個聲源一個向量，以 `;` 分隔，例如 `0,0,1;0,0,-1`。",
    ),
    FieldSpec(
        "BEM.VelocityModel",
        "速度模型",
        kind="combo",
        default="uniform",
        choices=("uniform",),
    ),
    FieldSpec(
        "BEM.VelocityFrequencyWeighting",
        "速度頻率權重",
        kind="combo",
        default="none",
        choices=("none", "inverse_jw"),
        hint="none = 不加權；inverse_jw = 乘上 1/(jω) 複數權重。",
    ),
    FieldSpec("BEM.F1", "起始頻率 [Hz]", default="200"),
    FieldSpec("BEM.F2", "結束頻率 [Hz]", default="20000"),
    FieldSpec("BEM.NumFreq", "頻率點數", default="48"),
    FieldSpec(
        "BEM.FrequencySpacing",
        "頻率分佈模式",
        kind="combo",
        default="log",
        choices=("log", "linear"),
        hint="log = 對數等比分佈（預設）；linear = 線性等距分佈。",
    ),
    FieldSpec("BEM.Rho0", "空氣密度 rho0 [kg/m^3]", default="1.21"),
    FieldSpec("BEM.C0", "聲速 c0 [m/s]", default="343"),
)

BEM_SYMMETRY_FIELDS = (
    FieldSpec(
        "BEM.SymmetryMode",
        "對稱降階模式",
        kind="combo",
        default="off",
        choices=("off", "half_x_even", "half_y_even", "quarter_xy_even_even"),
    ),
    FieldSpec("BEM.SymmetryXValue", "X 對稱平面位置 [m]", default="0.0"),
    FieldSpec("BEM.SymmetryYValue", "Y 對稱平面位置 [m]", default="0.0"),
    FieldSpec("BEM.SymmetryTolerance", "對稱檢查容差 [m]", default="1.0e-6"),
    FieldSpec("BEM.SymmetryStrict", "嚴格 reduced mesh 檢查", kind="check", default=True, emit_default=True),
    FieldSpec("BEM.SymmetryDebugFull", "輸出 full rebuild debug", kind="check", default=False, emit_default=True),
)

BEM_OBSERVATION_FIELDS = (
    FieldSpec("BEM.MicDistance", "麥克風距離 [m]", default="5.0"),
    FieldSpec(
        "BEM.Plane",
        "觀測平面",
        kind="combo",
        default="XZ",
        choices=("XZ", "YZ"),
    ),
    FieldSpec(
        "BEM.AngleRangeMode",
        "角度採樣範圍",
        kind="combo",
        default="full_circle",
        choices=("full_circle", "half_circle", "quarter_circle"),
        hint="full_circle = -180~180°, half_circle = -90~90°, quarter_circle = -45~45°",
    ),
    FieldSpec("BEM.ThetaCount", "角度取樣數", default="361"),
    FieldSpec("BEM.ReferencePressure", "參考聲壓 [Pa]", default="2.8284271247461903e-05"),
    FieldSpec("BEM.ExportPng", "匯出 PNG", kind="check", default=True, emit_default=True),
    FieldSpec("BEM.ExportBoundaryPressure", "匯出邊界壓力", kind="check", default=False, emit_default=True),
)

BEM_FIELD_SECTIONS = (
    ("BEM automation / backend 設定。", BEM_AUTOMATION_FIELDS),
    ("ATH BEM 網格匯入與群組選取。", BEM_MESH_FIELDS),
    ("外部 Helmholtz 求解器控制。", BEM_SOLVER_FIELDS),
    ("對稱降階設定（1/2 / 1/4）。", BEM_SYMMETRY_FIELDS),
    ("遠場指向性觀測設定。", BEM_OBSERVATION_FIELDS),
)

BEM_GUIDED_CONTROLLER_KEYS = (
    "BEM.Enabled",
    "BEM.Backend",
    "BEM.MeshSourceMode",
    "BEM.GroupMode",
    "BEM.SolverMode",
    "BEM.ObservationMode",
)

BEM_GUIDED_ALWAYS_VISIBLE_KEYS = ("BEM.Enabled",)

BEM_GUIDED_FIELD_GROUPS: dict[str, tuple[str, ...]] = {
    "BEM_GUIDED_ENABLE": ("BEM.Enabled",),
    "BEM_GUIDED_CONTROLLERS": ("BEM.Backend", "BEM.MeshSourceMode", "BEM.GroupMode", "BEM.SolverMode", "BEM.ObservationMode"),
    "BEM_GUIDED_BACKEND_WSL": ("BEM.WslVenv", "BEM.WslSolverEntry"),
    "BEM_GUIDED_BACKEND_LOCAL": ("BEM.LocalPythonExe",),
    "BEM_GUIDED_BACKEND_CONDA": ("BEM.CondaExe", "BEM.CondaEnv"),
    "BEM_GUIDED_MESH_MANUAL": ("BEM.MeshFile",),
    "BEM_GUIDED_MESH_COMMON": ("BEM.MeshScaleToMeter",),
    "BEM_GUIDED_GROUP_AUTO": ("BEM.AutoGroupStrategy",),
    "BEM_GUIDED_GROUP_MANUAL": ("BEM.SourceGroups", "BEM.WallGroups", "BEM.InterfaceGroups", "BEM.IgnoreGroups"),
    "BEM_GUIDED_SOLVER_COMMON": (
        "BEM.SourceGain",
        "BEM.SourceDirection",
        "BEM.VelocityModel",
        "BEM.VelocityFrequencyWeighting",
        "BEM.F1",
        "BEM.F2",
        "BEM.NumFreq",
        "BEM.FrequencySpacing",
        "BEM.Rho0",
        "BEM.C0",
    ),
    "BEM_GUIDED_SYMMETRY": (
        "BEM.SymmetryMode",
        "BEM.SymmetryXValue",
        "BEM.SymmetryYValue",
        "BEM.SymmetryTolerance",
        "BEM.SymmetryStrict",
        "BEM.SymmetryDebugFull",
    ),
    "BEM_GUIDED_OBSERVATION_COMMON": (
        "BEM.MicDistance",
        "BEM.Plane",
        "BEM.AngleRangeMode",
        "BEM.ThetaCount",
        "BEM.ReferencePressure",
    ),
    "BEM_GUIDED_OBSERVATION_POLAR": ("BEM.ExportPng",),
    "BEM_GUIDED_OBSERVATION_CUSTOM": ("BEM.ExportBoundaryPressure",),
}

BEM_GUIDED_BASE_GROUPS = (
    "BEM_GUIDED_ENABLE",
)

BEM_GUIDED_RULES: dict[str, dict[str, dict[str, object]]] = {
    "BEM.Enabled": {
        "__default__": {
            "inactive_groups": {
                "BEM_GUIDED_CONTROLLERS": "BEM automation is disabled.",
                "BEM_GUIDED_BACKEND_WSL": "BEM automation is disabled.",
                "BEM_GUIDED_BACKEND_LOCAL": "BEM automation is disabled.",
                "BEM_GUIDED_BACKEND_CONDA": "BEM automation is disabled.",
                "BEM_GUIDED_MESH_MANUAL": "BEM automation is disabled.",
                "BEM_GUIDED_MESH_COMMON": "BEM automation is disabled.",
                "BEM_GUIDED_GROUP_AUTO": "BEM automation is disabled.",
                "BEM_GUIDED_GROUP_MANUAL": "BEM automation is disabled.",
                "BEM_GUIDED_SOLVER_COMMON": "BEM automation is disabled.",
                "BEM_GUIDED_SYMMETRY": "BEM automation is disabled.",
                "BEM_GUIDED_OBSERVATION_COMMON": "BEM automation is disabled.",
                "BEM_GUIDED_OBSERVATION_POLAR": "BEM automation is disabled.",
                "BEM_GUIDED_OBSERVATION_CUSTOM": "BEM automation is disabled.",
            },
        },
        "1": {
            "relevant_groups": (
                "BEM_GUIDED_CONTROLLERS",
                "BEM_GUIDED_MESH_COMMON",
                "BEM_GUIDED_SOLVER_COMMON",
                "BEM_GUIDED_SYMMETRY",
                "BEM_GUIDED_OBSERVATION_COMMON",
            ),
        },
    },
    "BEM.Backend": {
        "__default__": {
            "relevant_groups": ("BEM_GUIDED_BACKEND_WSL",),
            "inactive_groups": {
                "BEM_GUIDED_BACKEND_LOCAL": "Only used for Backend = local_python.",
                "BEM_GUIDED_BACKEND_CONDA": "Only used for Backend = conda.",
            },
        },
        "wsl": {
            "relevant_groups": ("BEM_GUIDED_BACKEND_WSL",),
            "inactive_groups": {
                "BEM_GUIDED_BACKEND_LOCAL": "Only used for Backend = local_python.",
                "BEM_GUIDED_BACKEND_CONDA": "Only used for Backend = conda.",
            },
        },
        "local_python": {
            "relevant_groups": ("BEM_GUIDED_BACKEND_LOCAL",),
            "inactive_groups": {
                "BEM_GUIDED_BACKEND_WSL": "Only used for Backend = wsl.",
                "BEM_GUIDED_BACKEND_CONDA": "Only used for Backend = conda.",
            },
        },
        "conda": {
            "relevant_groups": ("BEM_GUIDED_BACKEND_CONDA",),
            "inactive_groups": {
                "BEM_GUIDED_BACKEND_WSL": "Only used for Backend = wsl.",
                "BEM_GUIDED_BACKEND_LOCAL": "Only used for Backend = local_python.",
            },
        },
    },
    "BEM.MeshSourceMode": {
        "__default__": {
            "relevant_groups": ("BEM_GUIDED_MESH_COMMON", "BEM_GUIDED_MESH_MANUAL"),
        },
        "latest_ath_output": {
            "relevant_groups": ("BEM_GUIDED_MESH_COMMON",),
            "inactive_groups": {
                "BEM_GUIDED_MESH_MANUAL": "Mesh file comes from the latest ATH output.",
            },
        },
        "manual_mesh_file": {
            "relevant_groups": ("BEM_GUIDED_MESH_COMMON", "BEM_GUIDED_MESH_MANUAL"),
        },
    },
    "BEM.GroupMode": {
        "__default__": {
            "relevant_groups": ("BEM_GUIDED_GROUP_AUTO",),
            "inactive_groups": {
                "BEM_GUIDED_GROUP_MANUAL": "Only used for GroupMode = manual.",
            },
        },
        "auto": {
            "relevant_groups": ("BEM_GUIDED_GROUP_AUTO",),
            "inactive_groups": {
                "BEM_GUIDED_GROUP_MANUAL": "Only used for GroupMode = manual.",
            },
        },
        "manual": {
            "relevant_groups": ("BEM_GUIDED_GROUP_MANUAL",),
            "inactive_groups": {
                "BEM_GUIDED_GROUP_AUTO": "Only used for GroupMode = auto.",
            },
        },
    },
    "BEM.SolverMode": {
        "__default__": {
            "relevant_groups": ("BEM_GUIDED_SOLVER_COMMON",),
        },
        "exterior_velocity_bc": {
            "relevant_groups": ("BEM_GUIDED_SOLVER_COMMON",),
        },
    },
    "BEM.ObservationMode": {
        "__default__": {
            "relevant_groups": ("BEM_GUIDED_OBSERVATION_COMMON", "BEM_GUIDED_OBSERVATION_POLAR"),
            "inactive_groups": {
                "BEM_GUIDED_OBSERVATION_CUSTOM": "Only used for ObservationMode = custom_directivity.",
            },
        },
        "polar_map": {
            "relevant_groups": ("BEM_GUIDED_OBSERVATION_COMMON", "BEM_GUIDED_OBSERVATION_POLAR"),
            "inactive_groups": {
                "BEM_GUIDED_OBSERVATION_CUSTOM": "Only used for ObservationMode = custom_directivity.",
            },
        },
        "custom_directivity": {
            "relevant_groups": ("BEM_GUIDED_OBSERVATION_COMMON", "BEM_GUIDED_OBSERVATION_CUSTOM"),
            "inactive_groups": {
                "BEM_GUIDED_OBSERVATION_POLAR": "Only used for ObservationMode = polar_map.",
            },
        },
    },
}

BEM_SANITIZE_RESET_VALUES: dict[str, object] = {
    "BEM.WslVenv": "",
    "BEM.WslSolverEntry": "",
    "BEM.LocalPythonExe": "",
    "BEM.CondaExe": "",
    "BEM.CondaEnv": "",
    "BEM.MeshFile": "",
    "BEM.AutoGroupStrategy": "",
    "BEM.SourceGroups": "",
    "BEM.WallGroups": "",
    "BEM.InterfaceGroups": "",
    "BEM.IgnoreGroups": "",
    "BEM.ExportPng": False,
    "BEM.ExportBoundaryPressure": False,
}

BEM_GUIDED_FIELD_SECTIONS = (
    ("BEM Automation", "Guided Setup 中的 BEM 執行控制，不會寫入 ATH cfg。", BEM_AUTOMATION_FIELDS),
    ("Mesh 與 Group Mapping", "依 mesh source / group mode 自動切換顯示欄位。", BEM_MESH_FIELDS),
    ("Solver", "BEM solver 常用參數。", BEM_SOLVER_FIELDS),
    ("Symmetry", "對稱降階設定。", BEM_SYMMETRY_FIELDS),
    ("Observation", "遠場觀測與匯出模式。", BEM_OBSERVATION_FIELDS),
)
