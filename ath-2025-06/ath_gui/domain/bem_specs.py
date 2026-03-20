"""BEM-specific GUI field definitions and defaults."""

from __future__ import annotations

from .specs import FieldSpec


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
        "BEM.SolverMode",
        "求解器模式",
        kind="combo",
        default="exterior_velocity_bc",
        choices=("exterior_velocity_bc",),
    ),
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
    FieldSpec("BEM.F1", "起始頻率 [Hz]", default="200"),
    FieldSpec("BEM.F2", "結束頻率 [Hz]", default="20000"),
    FieldSpec("BEM.NumFreq", "頻率點數", default="48"),
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
    ("ATH BEM 網格匯入與群組選取。", BEM_MESH_FIELDS),
    ("外部 Helmholtz 求解器控制。", BEM_SOLVER_FIELDS),
    ("對稱降階設定（1/2 / 1/4）。", BEM_SYMMETRY_FIELDS),
    ("遠場指向性觀測設定。", BEM_OBSERVATION_FIELDS),
)
