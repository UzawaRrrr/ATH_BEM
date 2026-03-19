from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


APP_TITLE = "ATH 波導設定工作台"
ROOT_DIR = Path(__file__).resolve().parent.parent
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
