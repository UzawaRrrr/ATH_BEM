from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


APP_TITLE = "ATH 波導設定工作台"


def _resolve_root_dir() -> Path:
    """Resolve ATH project root robustly across layered module locations."""
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "ath.exe").exists() and (candidate / "ath_gui").exists():
            return candidate
    # Fallback for development copies; keeps previous behavior predictable.
    return here.parents[2]


ROOT_DIR = _resolve_root_dir()
ATH_EXE = ROOT_DIR / "ath.exe"
ATH_GLOBAL_CONFIG = ROOT_DIR / "ath.cfg"

BG = "#0b1220"
CARD = "#121b2b"
CARD_ALT = "#182235"
ACCENT = "#37c8b4"
ACCENT_SOFT = "#163742"
TEXT = "#e7eef8"
MUTED = "#91a3bb"
INPUT_BG = "#0f1725"
BORDER = "#2a3950"
BUTTON_BG = "#223149"
BUTTON_ACTIVE = "#2d4364"
BUTTON_TEXT = "#eaf4ff"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str = "text"
    default: object = ""
    quote: bool = False
    width: int = 32
    choices: tuple[str, ...] = ()
    browse: str | None = None
    hint: str = ""
    choice_notes: tuple[tuple[str, str], ...] = ()
    emit_default: bool = False


GLOBAL_FIELDS = (
    FieldSpec("OutputRootDir", "輸出根目錄", quote=True, browse="dir", width=52),
    FieldSpec("MeshCmd", "外部網格檢視命令", quote=True, browse="file", width=52, hint='使用 `%f` 作為生成 `.geo` 檔案路徑的替代符。'),
    FieldSpec("GnuplotPath", "Gnuplot 路徑", quote=True, browse="file", width=52),
)

GEOMETRY_FIELDS = (
    FieldSpec("Throat.Diameter", "喉部直徑 [mm]"),
    FieldSpec(
        "Throat.Profile",
        "喉部輪廓",
        kind="combo",
        default="1",
        choices=("", "1", "3"),
        choice_notes=(("1", "OS-SE 輪廓"), ("3", "圓弧")),
    ),
    FieldSpec("Throat.Angle", "喉部角度 [deg]", default="0"),
    FieldSpec("Throat.Ext.Angle", "喉部延伸角度 [deg]", default="0"),
    FieldSpec("Throat.Ext.Length", "喉部延伸長度 [mm]", default="0"),
    FieldSpec("Slot.Length", "縫槽長度 [mm]", default="0"),
    FieldSpec("Length", "名義長度 [mm]"),
    FieldSpec("Coverage.Angle", "覆蓋角 [deg]"),
    FieldSpec("Term.s", "Term.s", default="0.7"),
    FieldSpec("Term.q", "Term.q", default="0.995"),
    FieldSpec("Term.n", "Term.n", default="4.0"),
    FieldSpec("OS.k", "OS.k", default="1"),
    FieldSpec("Rot", "最終旋轉角 [deg]", default="0"),
    FieldSpec("CircArc.Radius", "圓弧半徑 [mm]"),
    FieldSpec("CircArc.TermAngle", "圓弧終止角 [deg]", default="1"),
)

GUIDING_CURVE_FIELDS = (
    # Optimizer v1.1.08 OSSE-first stage does not search Guiding Curve families.
    # These fields stay available for manual editing, but GCurve / SE / SF paths
    # are intentionally excluded from the current headless optimization space.
    FieldSpec(
        "GCurve.Type",
        "導引曲線類型",
        kind="combo",
        choices=("", "1", "2"),
        choice_notes=(("1", "超橢圓"), ("2", "超公式")),
    ),
    FieldSpec("GCurve.Dist", "導引曲線距離"),
    FieldSpec("GCurve.Width", "導引曲線寬度 [mm]"),
    FieldSpec("GCurve.AspectRatio", "導引曲線長寬比", default="1"),
    FieldSpec("GCurve.SE.n", "導引超橢圓 n", default="3"),
    FieldSpec("GCurve.SF", "超公式 (a,b,m,n1,n2,n3)", width=52),
    FieldSpec("GCurve.Rot", "導引曲線旋轉 [deg]", default="0"),
)

MORPH_FIELDS = (
    FieldSpec(
        "Morph.TargetShape",
        "Morph 目標形狀",
        kind="combo",
        default="0",
        choices=("", "0", "1", "2"),
        choice_notes=(("0", "維持原始形狀"), ("1", "矩形"), ("2", "圓形")),
    ),
    FieldSpec("Morph.TargetWidth", "Morph 目標寬度 [mm]", default="0"),
    FieldSpec("Morph.TargetHeight", "Morph 目標高度 [mm]", default="0"),
    FieldSpec("Morph.CornerRadius", "角落半徑 [mm]", default="35"),
    FieldSpec("Morph.FixedPart", "固定比例 (0-1)", default="0"),
    FieldSpec("Morph.Rate", "Morph 速率", default="3"),
    FieldSpec("Morph.AllowShrinkage", "允許收縮", kind="check", default=False),
)

ROLLBACK_FIELDS = (
    FieldSpec("Rollback", "啟用 Rollback", kind="check", default=False),
    FieldSpec("Rollback.StartAt", "Rollback 起點 (0-1)", default="0.5"),
    FieldSpec("Rollback.Angle", "Rollback 角度 [deg]", default="180"),
)

MESH_FIELDS = (
    FieldSpec(
        "Mesh.Quadrants",
        "網格象限",
        kind="combo",
        default="1",
        choices=("", "1", "12", "14", "1234"),
        choice_notes=(("1", "僅第 1 象限"), ("12", "第 1+2 象限"), ("14", "第 1+4 象限"), ("1234", "完整網格")),
    ),
    FieldSpec("Mesh.AngularSegments", "角向分段"),
    FieldSpec("Mesh.LengthSegments", "長度分段"),
    FieldSpec("Mesh.CornerSegments", "角落分段"),
    FieldSpec("Mesh.ThroatSegments", "喉部分段"),
    FieldSpec("Mesh.ThroatResolution", "喉部解析度 [mm]", default="5"),
    FieldSpec("Mesh.MouthResolution", "口部解析度 [mm]", default="8"),
    FieldSpec("Mesh.SubdomainSlices", "子域切片", width=40),
    FieldSpec("Mesh.InterfaceOffset", "介面偏移 [mm]", width=40),
    FieldSpec("Mesh.InterfaceDraw", "介面繪製 [mm]", width=40),
    FieldSpec(
        "Mesh.RearShape",
        "後方形狀",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "完整模型"), ("2", "平板圓盤")),
    ),
    FieldSpec("Mesh.WallThickness", "壁厚 [mm]", default="5"),
    FieldSpec("Mesh.RearResolution", "後方解析度 [mm]", default="10"),
)

ENCLOSURE_FIELDS = (
    FieldSpec("ENCLOSURE.Spacing", "邊界間距 (L,T,R,B) [mm]", width=40),
    FieldSpec("ENCLOSURE.Depth", "箱體深度 [mm]"),
    FieldSpec("ENCLOSURE.EdgeRadius", "邊緣半徑 [mm]"),
    FieldSpec(
        "ENCLOSURE.EdgeType",
        "邊緣類型",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "圓角"), ("2", "倒角")),
    ),
    FieldSpec("ENCLOSURE.FrontResolution", "前方解析度 q1,q2,q3,q4", width=40),
    FieldSpec("ENCLOSURE.BackResolution", "後方解析度 q1,q2,q3,q4", width=40),
)

ABEC_FIELDS = (
    FieldSpec(
        "ABEC.SimType",
        "模擬類型",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "無限障板"), ("2", "自由立式號角")),
    ),
    FieldSpec("ABEC.SimProfile", "圓對稱輪廓", default="-1", hint="-1 = 關閉；0 以上 = CircSym 模式使用的 profile index。"),
    FieldSpec("ABEC.f1", "低頻 [Hz]"),
    FieldSpec("ABEC.f2", "高頻 [Hz]"),
    FieldSpec("ABEC.NumFrequencies", "頻率點數"),
    FieldSpec(
        "ABEC.Abscissa",
        "頻率分布",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "對數"), ("2", "線性")),
    ),
    FieldSpec("ABEC.MeshFrequency", "網格基準頻率 [Hz]", default="1000"),
)

SOURCE_FIELDS = (
    FieldSpec(
        "Source.Shape",
        "聲源形狀",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "球面帽"), ("2", "平板圓盤")),
    ),
    FieldSpec("Source.Radius", "聲源半徑 [mm]", default="-1"),
    FieldSpec(
        "Source.Curv",
        "聲源曲率",
        kind="combo",
        default="0",
        choices=("", "-1", "0", "1"),
        choice_notes=(("-1", "內凹"), ("0", "自動"), ("1", "外凸")),
    ),
    FieldSpec(
        "Source.Velocity",
        "聲源速度方向",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "垂直於表面"), ("2", "軸向 / 活塞式")),
    ),
    FieldSpec("SOURCE.Contours", "聲源輪廓 / 腳本", kind="multiline", width=72),
)

LE_FIELDS = (
    FieldSpec("LE", "LE 模型路徑", quote=True, browse="file", width=52),
    FieldSpec("LE.System", "LE System 標籤", default="S1"),
    FieldSpec("LE.Driver", "LE Driver 標籤", default="D1"),
    FieldSpec("LE.Voltage", "LE 電壓 [Vrms]", default="2.83"),
)

POLAR_FIELDS = (
    FieldSpec("POLAR.Tag", "極座標標籤", default="SPL"),
    FieldSpec("POLAR.MapAngleRange", "角度範圍 (a0,a1,N)", width=40),
    FieldSpec("POLAR.NormAngle", "正規化角度 [deg]"),
    FieldSpec("POLAR.Distance", "觀測距離 [m]"),
    FieldSpec("POLAR.Offset", "觀測偏移 [mm]"),
    FieldSpec("POLAR.Inclination", "傾角 [deg]", hint="0 = 水平面；90 = 全空間分析中的垂直面。"),
    FieldSpec("POLAR.Curves", "曲線角度", width=40),
)

OUTPUT_FIELDS = (
    FieldSpec("Output.SubDir", "輸出子目錄", quote=True),
    FieldSpec("Output.DestDir", "輸出目的目錄", quote=True, browse="dir", width=52),
    FieldSpec("Output.STL", "輸出 STL", kind="check", default=True, emit_default=True),
    FieldSpec("Output.MSH", "輸出 MSH", kind="check", default=False, emit_default=True),
    FieldSpec("Output.ABECProject", "輸出 ABEC 專案", kind="check", default=False, emit_default=True),
)

GRID_EXPORT_FIELDS = (
    FieldSpec("GRID.Tag", "Grid 匯出標籤"),
    FieldSpec("GRID.ProfileRange", "輪廓範圍 (from,to)"),
    FieldSpec("GRID.SliceRange", "切片範圍 (from,to)"),
    FieldSpec("GRID.ExportProfiles", "匯出輪廓", kind="check", default=False),
    FieldSpec("GRID.ExportSlices", "匯出切片", kind="check", default=False),
    FieldSpec("GRID.Scale", "縮放", default="1.0"),
    FieldSpec("GRID.Delimiter", "分隔符號", default=";", quote=True),
    FieldSpec("GRID.FileExtension", "副檔名", default="csv", quote=True),
    FieldSpec("GRID.SeparateFiles", "分離輸出檔案", kind="check", default=False),
)

REPORT_FIELDS = (
    FieldSpec("REPORT.Title", "報告標題", quote=True, width=42),
    FieldSpec("REPORT.PolarData", "極座標資料標籤"),
    FieldSpec("REPORT.NormAngle", "報告正規化角度 [deg]"),
    FieldSpec("REPORT.MaxAngle", "最大角度 [deg]"),
    FieldSpec("REPORT.SPL_Range", "SPL 範圍 [dB]"),
    FieldSpec("REPORT.DrvImp_Range", "單體阻抗範圍 [Ohm]"),
    FieldSpec("REPORT.ExcRefSPL", "參考振幅 SPL [dB]"),
    FieldSpec("REPORT.MaxRadius", "輪廓草圖半徑 [mm]"),
    FieldSpec("REPORT.Width", "報告寬度 [px]"),
    FieldSpec("REPORT.Height", "報告高度 [px]"),
    FieldSpec("REPORT.GnuplotCode", "Gnuplot 腳本", quote=True, browse="file", width=52),
)

ADVANCED_FIELDS = (
    FieldSpec("ADVANCED.Raw", "其他 ATH 項目 / 區塊", kind="multiline", width=80),
)

FIELD_SECTIONS = (
    ("Global", "ath.exe 啟動時使用的全域設定。", GLOBAL_FIELDS),
    ("Geometry", "第 4.1.1 章的核心波導幾何與輪廓設定。", GEOMETRY_FIELDS),
    ("Geometry", "隱式形狀定義的導引曲線控制。", GUIDING_CURVE_FIELDS),
    ("Morph", "口部外形 Morph 與 rollback 控制。", MORPH_FIELDS),
    ("Morph", "自由立式號角的 rollback 控制。", ROLLBACK_FIELDS),
    ("Mesh", "網格密度、介面與背牆設定。", MESH_FIELDS),
    ("Mesh", "選用的箱體區塊。", ENCLOSURE_FIELDS),
    ("Simulation", "ABEC / BEM 模擬設定。", ABEC_FIELDS),
    ("Simulation", "聲源定義與內嵌腳本。", SOURCE_FIELDS),
    ("Simulation", "選用的集總元件模型。", LE_FIELDS),
    ("Simulation", "單一可編輯的極座標觀測區塊。", POLAR_FIELDS),
    ("Output", "輸出開關與目的地覆寫。", OUTPUT_FIELDS),
    ("Output", "選用的 grid 匯出區塊。", GRID_EXPORT_FIELDS),
    ("Output", "選用的報告區塊。", REPORT_FIELDS),
    ("Advanced", "未知或進階的 ATH 項目會保留在這裡。", ADVANCED_FIELDS),
)

SIMPLE_FIELD_SPECS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        *GLOBAL_FIELDS,
        *GEOMETRY_FIELDS,
        *GUIDING_CURVE_FIELDS,
        *MORPH_FIELDS,
        *ROLLBACK_FIELDS,
        *MESH_FIELDS,
        *ENCLOSURE_FIELDS,
        *ABEC_FIELDS,
        *SOURCE_FIELDS,
        *LE_FIELDS,
        *POLAR_FIELDS,
        *OUTPUT_FIELDS,
        *GRID_EXPORT_FIELDS,
        *REPORT_FIELDS,
        *ADVANCED_FIELDS,
    )
}


def _reuse_field_specs(*keys: str) -> tuple[FieldSpec, ...]:
    return tuple(SIMPLE_FIELD_SPECS[key] for key in keys)


QUICK_GEOMETRY_FIELDS = _reuse_field_specs(
    "Throat.Diameter",
    "Throat.Angle",
    "Length",
    "Coverage.Angle",
)

QUICK_SHAPE_FIELDS = _reuse_field_specs(
    "GCurve.Type",
    "GCurve.Width",
    "GCurve.AspectRatio",
    "Morph.TargetShape",
    "Morph.TargetWidth",
    "Morph.TargetHeight",
    "Morph.CornerRadius",
)

QUICK_SIM_FIELDS = _reuse_field_specs(
    "ABEC.SimType",
    "ABEC.f1",
    "ABEC.f2",
    "ABEC.NumFrequencies",
    "POLAR.Distance",
    "Output.SubDir",
    "Output.STL",
    "Output.MSH",
    "Output.ABECProject",
)

QUICK_FIELD_SECTIONS = (
    ("基本幾何", "常用的號角幾何參數。", QUICK_GEOMETRY_FIELDS),
    ("口部 / 外形", "常用的口部尺寸與外形控制。", QUICK_SHAPE_FIELDS),
    ("分析 / 輸出", "基本分析頻段與常用輸出開關。", QUICK_SIM_FIELDS),
)

GUIDED_CONTROLLER_KEYS = (
    "Throat.Profile",
    "GCurve.Type",
    "Morph.TargetShape",
    "Rollback",
    "ABEC.SimType",
)

GUIDED_ALWAYS_VISIBLE_KEYS = GUIDED_CONTROLLER_KEYS

GUIDED_FIELD_GROUPS: dict[str, tuple[str, ...]] = {
    "GUIDED_PROFILE_CONTROLLER": ("Throat.Profile",),
    "GUIDED_GCURVE_CONTROLLER": ("GCurve.Type",),
    "GUIDED_MORPH_CONTROLLER": ("Morph.TargetShape",),
    "GUIDED_ROLLBACK_CONTROLLER": ("Rollback",),
    "GUIDED_ABEC_CONTROLLER": ("ABEC.SimType",),
    "GUIDED_BASE_GEOMETRY": (
        "Throat.Diameter",
        "Length",
        "Throat.Angle",
        "Throat.Ext.Angle",
        "Throat.Ext.Length",
        "Slot.Length",
        "Rot",
    ),
    "GUIDED_COVERAGE": ("Coverage.Angle",),
    "GUIDED_PROFILE_OS": ("Term.s", "Term.q", "Term.n", "OS.k"),
    "GUIDED_PROFILE_CIRCARC": ("CircArc.Radius", "CircArc.TermAngle"),
    "GUIDED_GCURVE_COMMON": ("GCurve.Dist", "GCurve.Width", "GCurve.AspectRatio", "GCurve.Rot"),
    "GUIDED_GCURVE_SUPERELLIPSE": ("GCurve.SE.n",),
    "GUIDED_GCURVE_SUPERFORMULA": ("GCurve.SF",),
    "GUIDED_MORPH_DIMENSIONS": ("Morph.TargetWidth", "Morph.TargetHeight"),
    "GUIDED_MORPH_CORNER": ("Morph.CornerRadius",),
    "GUIDED_MORPH_BEHAVIOR": ("Morph.FixedPart", "Morph.Rate", "Morph.AllowShrinkage"),
    "GUIDED_ROLLBACK_DETAILS": ("Rollback.StartAt", "Rollback.Angle"),
    "GUIDED_ABEC_COMMON": (
        "ABEC.SimProfile",
        "ABEC.f1",
        "ABEC.f2",
        "ABEC.NumFrequencies",
        "ABEC.Abscissa",
        "ABEC.MeshFrequency",
    ),
    "GUIDED_POLAR_COMMON": (
        "POLAR.Tag",
        "POLAR.MapAngleRange",
        "POLAR.NormAngle",
        "POLAR.Distance",
        "POLAR.Offset",
        "POLAR.Inclination",
        "POLAR.Curves",
    ),
    "GUIDED_OUTPUT_COMMON": ("Output.SubDir", "Output.STL", "Output.MSH", "Output.ABECProject"),
}

GUIDED_BASE_GROUPS = (
    "GUIDED_PROFILE_CONTROLLER",
    "GUIDED_MORPH_CONTROLLER",
    "GUIDED_ABEC_CONTROLLER",
    "GUIDED_BASE_GEOMETRY",
    "GUIDED_COVERAGE",
    "GUIDED_ABEC_COMMON",
    "GUIDED_POLAR_COMMON",
    "GUIDED_OUTPUT_COMMON",
)

GUIDED_RULES: dict[str, dict[str, dict[str, object]]] = {
    "Throat.Profile": {
        "__default__": {
            "relevant_groups": ("GUIDED_COVERAGE",),
            "inactive_groups": {
                "GUIDED_PROFILE_OS": "Only used for the OS-SE throat profile.",
                "GUIDED_PROFILE_CIRCARC": "Only used for the circular-arc throat profile.",
                "GUIDED_GCURVE_CONTROLLER": "Guiding Curve is only available for the OS-SE throat profile.",
                "GUIDED_GCURVE_COMMON": "Guiding Curve details are only available for the OS-SE throat profile.",
                "GUIDED_GCURVE_SUPERELLIPSE": "Only used for GCurve.Type = superellipse.",
                "GUIDED_GCURVE_SUPERFORMULA": "Only used for GCurve.Type = superformula.",
            },
        },
        "1": {
            "relevant_groups": ("GUIDED_COVERAGE", "GUIDED_PROFILE_OS", "GUIDED_GCURVE_CONTROLLER"),
            "inactive_groups": {
                "GUIDED_PROFILE_CIRCARC": "Only used for the circular-arc throat profile.",
            },
        },
        "3": {
            "relevant_groups": ("GUIDED_COVERAGE", "GUIDED_PROFILE_CIRCARC"),
            "inactive_groups": {
                "GUIDED_PROFILE_OS": "Only used for the OS-SE throat profile.",
                "GUIDED_GCURVE_CONTROLLER": "Guiding Curve is only available for the OS-SE throat profile.",
                "GUIDED_GCURVE_COMMON": "Guiding Curve details are only available for the OS-SE throat profile.",
                "GUIDED_GCURVE_SUPERELLIPSE": "Only used for GCurve.Type = superellipse.",
                "GUIDED_GCURVE_SUPERFORMULA": "Only used for GCurve.Type = superformula.",
            },
        },
    },
    "GCurve.Type": {
        "__inactive__": {
            "inactive_groups": {
                "GUIDED_GCURVE_COMMON": "Guiding Curve is only available when Throat.Profile = OS-SE.",
                "GUIDED_GCURVE_SUPERELLIPSE": "Only used for GCurve.Type = superellipse.",
                "GUIDED_GCURVE_SUPERFORMULA": "Only used for GCurve.Type = superformula.",
            },
        },
        "__default__": {
            "relevant_groups": ("GUIDED_COVERAGE",),
            "inactive_groups": {
                "GUIDED_GCURVE_COMMON": "Only used when a Guiding Curve type is selected.",
                "GUIDED_GCURVE_SUPERELLIPSE": "Only used for GCurve.Type = superellipse.",
                "GUIDED_GCURVE_SUPERFORMULA": "Only used for GCurve.Type = superformula.",
            },
        },
        "1": {
            "relevant_groups": ("GUIDED_GCURVE_COMMON", "GUIDED_GCURVE_SUPERELLIPSE"),
            "inactive_groups": {
                "GUIDED_COVERAGE": "Coverage.Angle is ignored while Guiding Curve drives the mouth coverage.",
                "GUIDED_GCURVE_SUPERFORMULA": "Only used for GCurve.Type = superformula.",
            },
        },
        "2": {
            "relevant_groups": ("GUIDED_GCURVE_COMMON", "GUIDED_GCURVE_SUPERFORMULA"),
            "inactive_groups": {
                "GUIDED_COVERAGE": "Coverage.Angle is ignored while Guiding Curve drives the mouth coverage.",
                "GUIDED_GCURVE_SUPERELLIPSE": "Only used for GCurve.Type = superellipse.",
            },
        },
    },
    "Morph.TargetShape": {
        "__default__": {
            "inactive_groups": {
                "GUIDED_MORPH_DIMENSIONS": "Morph dimensions are only used when a target shape is selected.",
                "GUIDED_MORPH_CORNER": "Corner radius is only used for rectangular morph targets.",
                "GUIDED_MORPH_BEHAVIOR": "Morph behavior settings are only used when a target shape is selected.",
            },
        },
        "0": {
            "inactive_groups": {
                "GUIDED_MORPH_DIMENSIONS": "Morph dimensions are only used when a target shape is selected.",
                "GUIDED_MORPH_CORNER": "Corner radius is only used for rectangular morph targets.",
                "GUIDED_MORPH_BEHAVIOR": "Morph behavior settings are only used when a target shape is selected.",
            },
        },
        "1": {
            "relevant_groups": ("GUIDED_MORPH_DIMENSIONS", "GUIDED_MORPH_CORNER", "GUIDED_MORPH_BEHAVIOR"),
        },
        "2": {
            "relevant_groups": ("GUIDED_MORPH_DIMENSIONS", "GUIDED_MORPH_BEHAVIOR"),
            "inactive_groups": {
                "GUIDED_MORPH_CORNER": "Corner radius is only used for rectangular morph targets.",
            },
        },
    },
    "ABEC.SimType": {
        "__default__": {
            "inactive_groups": {
                "GUIDED_ROLLBACK_CONTROLLER": "Rollback is only used for the free-standing horn simulation mode.",
                "GUIDED_ROLLBACK_DETAILS": "Rollback details are only used for the free-standing horn simulation mode.",
            },
        },
        "1": {
            "inactive_groups": {
                "GUIDED_ROLLBACK_CONTROLLER": "Rollback is only used for the free-standing horn simulation mode.",
                "GUIDED_ROLLBACK_DETAILS": "Rollback details are only used for the free-standing horn simulation mode.",
            },
        },
        "2": {
            "relevant_groups": ("GUIDED_ROLLBACK_CONTROLLER",),
            "inactive_groups": {
                "GUIDED_ROLLBACK_DETAILS": "Rollback details are only used when Rollback is enabled.",
            },
        },
    },
    "Rollback": {
        "__inactive__": {
            "inactive_groups": {
                "GUIDED_ROLLBACK_DETAILS": "Rollback details are only used for the free-standing horn simulation mode.",
            },
        },
        "__default__": {
            "inactive_groups": {
                "GUIDED_ROLLBACK_DETAILS": "Rollback details are only used when Rollback is enabled.",
            },
        },
        "1": {
            "relevant_groups": ("GUIDED_ROLLBACK_DETAILS",),
        },
    },
}

GUIDED_SANITIZE_RESET_VALUES: dict[str, object] = {
    "Coverage.Angle": "",
    "Term.s": "",
    "Term.q": "",
    "Term.n": "",
    "OS.k": "",
    "CircArc.Radius": "",
    "CircArc.TermAngle": "",
    "GCurve.Type": "",
    "GCurve.Dist": "",
    "GCurve.Width": "",
    "GCurve.AspectRatio": "",
    "GCurve.SE.n": "",
    "GCurve.SF": "",
    "GCurve.Rot": "",
    "Morph.TargetWidth": "0",
    "Morph.TargetHeight": "0",
    "Morph.CornerRadius": "",
    "Morph.FixedPart": "",
    "Morph.Rate": "",
    "Morph.AllowShrinkage": False,
    "Rollback": False,
    "Rollback.StartAt": "",
    "Rollback.Angle": "",
}

GUIDED_FIELD_SECTIONS = (
    ("設計模式", "先選擇情境控制欄位，下面會只顯示目前 relevant 的設定。", _reuse_field_specs(*GUIDED_CONTROLLER_KEYS)),
    (
        "輪廓與導引",
        "依 throat/profile 與 guiding curve 類型動態切換欄位；完整欄位仍保留在原本分頁。",
        _reuse_field_specs(
            "Throat.Diameter",
            "Length",
            "Throat.Angle",
            "Throat.Ext.Angle",
            "Throat.Ext.Length",
            "Slot.Length",
            "Rot",
            "Coverage.Angle",
            "Term.s",
            "Term.q",
            "Term.n",
            "OS.k",
            "CircArc.Radius",
            "CircArc.TermAngle",
            "GCurve.Dist",
            "GCurve.Width",
            "GCurve.AspectRatio",
            "GCurve.SE.n",
            "GCurve.SF",
            "GCurve.Rot",
        ),
    ),
    (
        "口部 Morph",
        "依目標形狀只顯示需要的口部尺寸與 Morph 細項。",
        _reuse_field_specs(
            "Morph.TargetWidth",
            "Morph.TargetHeight",
            "Morph.CornerRadius",
            "Morph.FixedPart",
            "Morph.Rate",
            "Morph.AllowShrinkage",
        ),
    ),
    (
        "Rollback",
        "Rollback 只在對應模擬模式下可用，並在啟用後顯示細項。",
        _reuse_field_specs("Rollback.StartAt", "Rollback.Angle"),
    ),
    (
        "模擬與輸出",
        "保留常用 ABEC、極座標與輸出欄位；進階調整仍可到完整分頁。",
        _reuse_field_specs(
            "ABEC.SimProfile",
            "ABEC.f1",
            "ABEC.f2",
            "ABEC.NumFrequencies",
            "ABEC.Abscissa",
            "ABEC.MeshFrequency",
            "POLAR.Tag",
            "POLAR.MapAngleRange",
            "POLAR.NormAngle",
            "POLAR.Distance",
            "POLAR.Offset",
            "POLAR.Inclination",
            "POLAR.Curves",
            "Output.SubDir",
            "Output.STL",
            "Output.MSH",
            "Output.ABECProject",
        ),
    ),
)

_guided_field_keys: list[str] = []
for _fields in GUIDED_FIELD_GROUPS.values():
    _guided_field_keys.extend(_fields)
GUIDED_MANAGED_KEYS = tuple(dict.fromkeys(_guided_field_keys))

HORN_SAMPLE_VALUES = {
    "Throat.Diameter": "25.4",
    "Throat.Angle": "10",
    "Coverage.Angle": "45",
    "Length": "60",
    "Term.s": "1",
    "Term.q": "0.98",
    "Term.n": "4",
    "Mesh.LengthSegments": "24",
    "Mesh.AngularSegments": "64",
    "Mesh.ThroatResolution": "4",
    "Mesh.MouthResolution": "8",
}
