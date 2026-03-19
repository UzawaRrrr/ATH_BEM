from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


APP_TITLE = "ATH Config Studio"
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
    FieldSpec("OutputRootDir", "Output Root Directory", quote=True, browse="dir", width=52),
    FieldSpec("MeshCmd", "Mesh Command", quote=True, browse="file", width=52, hint='Use `%f` as the placeholder for the generated `.geo` file path.'),
    FieldSpec("GnuplotPath", "Gnuplot Path", quote=True, browse="file", width=52),
)

GEOMETRY_FIELDS = (
    FieldSpec("Throat.Diameter", "Throat Diameter [mm]"),
    FieldSpec(
        "Throat.Profile",
        "Throat Profile",
        kind="combo",
        default="1",
        choices=("", "1", "3"),
        choice_notes=(("1", "OS-SE profile"), ("3", "circular arc")),
    ),
    FieldSpec("Throat.Angle", "Throat Angle [deg]", default="0"),
    FieldSpec("Throat.Ext.Angle", "Throat Ext. Angle [deg]", default="0"),
    FieldSpec("Throat.Ext.Length", "Throat Ext. Length [mm]", default="0"),
    FieldSpec("Slot.Length", "Slot Length [mm]", default="0"),
    FieldSpec("Length", "Nominal Length [mm]"),
    FieldSpec("Coverage.Angle", "Coverage Angle [deg]"),
    FieldSpec("Term.s", "Term.s", default="0.7"),
    FieldSpec("Term.q", "Term.q", default="0.995"),
    FieldSpec("Term.n", "Term.n", default="4.0"),
    FieldSpec("OS.k", "OS.k", default="1"),
    FieldSpec("Rot", "Final Rotation [deg]", default="0"),
    FieldSpec("CircArc.Radius", "Circular Arc Radius [mm]"),
    FieldSpec("CircArc.TermAngle", "Circular Arc Term Angle [deg]", default="1"),
)

GUIDING_CURVE_FIELDS = (
    FieldSpec(
        "GCurve.Type",
        "Guiding Curve Type",
        kind="combo",
        choices=("", "1", "2"),
        choice_notes=(("1", "superellipse"), ("2", "superformula")),
    ),
    FieldSpec("GCurve.Dist", "Guiding Curve Distance"),
    FieldSpec("GCurve.Width", "Guiding Curve Width [mm]"),
    FieldSpec("GCurve.AspectRatio", "Guiding Curve Aspect Ratio", default="1"),
    FieldSpec("GCurve.SE.n", "Guiding Superellipse n", default="3"),
    FieldSpec("GCurve.SF", "Superformula (a,b,m,n1,n2,n3)", width=52),
    FieldSpec("GCurve.Rot", "Guiding Curve Rotation [deg]", default="0"),
)

MORPH_FIELDS = (
    FieldSpec(
        "Morph.TargetShape",
        "Morph Target Shape",
        kind="combo",
        default="0",
        choices=("", "0", "1", "2"),
        choice_notes=(("0", "keep raw shape"), ("1", "rectangle"), ("2", "circle")),
    ),
    FieldSpec("Morph.TargetWidth", "Morph Target Width [mm]", default="0"),
    FieldSpec("Morph.TargetHeight", "Morph Target Height [mm]", default="0"),
    FieldSpec("Morph.CornerRadius", "Corner Radius [mm]", default="35"),
    FieldSpec("Morph.FixedPart", "Fixed Part (0-1)", default="0"),
    FieldSpec("Morph.Rate", "Morph Rate", default="3"),
    FieldSpec("Morph.AllowShrinkage", "Allow Shrinkage", kind="check", default=False),
)

ROLLBACK_FIELDS = (
    FieldSpec("Rollback", "Enable Rollback", kind="check", default=False),
    FieldSpec("Rollback.StartAt", "Rollback Start (0-1)", default="0.5"),
    FieldSpec("Rollback.Angle", "Rollback Angle [deg]", default="180"),
)

MESH_FIELDS = (
    FieldSpec(
        "Mesh.Quadrants",
        "Mesh Quadrants",
        kind="combo",
        default="1",
        choices=("", "1", "12", "14", "1234"),
        choice_notes=(("1", "quadrant 1 only"), ("12", "quadrants 1+2"), ("14", "quadrants 1+4"), ("1234", "full mesh")),
    ),
    FieldSpec("Mesh.AngularSegments", "Angular Segments"),
    FieldSpec("Mesh.LengthSegments", "Length Segments"),
    FieldSpec("Mesh.CornerSegments", "Corner Segments"),
    FieldSpec("Mesh.ThroatSegments", "Throat Segments"),
    FieldSpec("Mesh.ThroatResolution", "Throat Resolution [mm]", default="5"),
    FieldSpec("Mesh.MouthResolution", "Mouth Resolution [mm]", default="8"),
    FieldSpec("Mesh.SubdomainSlices", "Subdomain Slices", width=40),
    FieldSpec("Mesh.InterfaceOffset", "Interface Offset [mm]", width=40),
    FieldSpec("Mesh.InterfaceDraw", "Interface Draw [mm]", width=40),
    FieldSpec(
        "Mesh.RearShape",
        "Rear Shape",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "full model"), ("2", "flat disc")),
    ),
    FieldSpec("Mesh.WallThickness", "Wall Thickness [mm]", default="5"),
    FieldSpec("Mesh.RearResolution", "Rear Resolution [mm]", default="10"),
)

ENCLOSURE_FIELDS = (
    FieldSpec("ENCLOSURE.Spacing", "Spacing (L,T,R,B) [mm]", width=40),
    FieldSpec("ENCLOSURE.Depth", "Enclosure Depth [mm]"),
    FieldSpec("ENCLOSURE.EdgeRadius", "Edge Radius [mm]"),
    FieldSpec(
        "ENCLOSURE.EdgeType",
        "Edge Type",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "rounded"), ("2", "chamfered")),
    ),
    FieldSpec("ENCLOSURE.FrontResolution", "Front Resolution q1,q2,q3,q4", width=40),
    FieldSpec("ENCLOSURE.BackResolution", "Back Resolution q1,q2,q3,q4", width=40),
)

ABEC_FIELDS = (
    FieldSpec(
        "ABEC.SimType",
        "Simulation Type",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "infinite baffle"), ("2", "free-standing horn")),
    ),
    FieldSpec("ABEC.SimProfile", "Circular Symmetry Profile", default="-1", hint="-1 = disabled; 0 and above = profile index used for CircSym mode."),
    FieldSpec("ABEC.f1", "Low Frequency [Hz]"),
    FieldSpec("ABEC.f2", "High Frequency [Hz]"),
    FieldSpec("ABEC.NumFrequencies", "Number of Frequencies"),
    FieldSpec(
        "ABEC.Abscissa",
        "Frequency Spacing",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "logarithmic"), ("2", "linear")),
    ),
    FieldSpec("ABEC.MeshFrequency", "Mesh Frequency [Hz]", default="1000"),
)

SOURCE_FIELDS = (
    FieldSpec(
        "Source.Shape",
        "Source Shape",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "spherical cap"), ("2", "flat disc")),
    ),
    FieldSpec("Source.Radius", "Source Radius [mm]", default="-1"),
    FieldSpec(
        "Source.Curv",
        "Source Curvature",
        kind="combo",
        default="0",
        choices=("", "-1", "0", "1"),
        choice_notes=(("-1", "concave"), ("0", "automatic"), ("1", "convex")),
    ),
    FieldSpec(
        "Source.Velocity",
        "Source Velocity",
        kind="combo",
        default="1",
        choices=("", "1", "2"),
        choice_notes=(("1", "normal to surface"), ("2", "axial / pistonic")),
    ),
    FieldSpec("SOURCE.Contours", "Source Contours / Script", kind="multiline", width=72),
)

LE_FIELDS = (
    FieldSpec("LE", "LE Model Path", quote=True, browse="file", width=52),
    FieldSpec("LE.System", "LE System Tag", default="S1"),
    FieldSpec("LE.Driver", "LE Driver Tag", default="D1"),
    FieldSpec("LE.Voltage", "LE Voltage [Vrms]", default="2.83"),
)

POLAR_FIELDS = (
    FieldSpec("POLAR.Tag", "Polar Tag", default="SPL"),
    FieldSpec("POLAR.MapAngleRange", "Map Angle Range (a0,a1,N)", width=40),
    FieldSpec("POLAR.NormAngle", "Normalize Angle [deg]"),
    FieldSpec("POLAR.Distance", "Observation Distance [m]"),
    FieldSpec("POLAR.Offset", "Observation Offset [mm]"),
    FieldSpec("POLAR.Inclination", "Inclination [deg]", hint="0 = horizontal plane, 90 = vertical plane in full-space analysis."),
    FieldSpec("POLAR.Curves", "Curve Angles", width=40),
)

OUTPUT_FIELDS = (
    FieldSpec("Output.SubDir", "Output Subdirectory", quote=True),
    FieldSpec("Output.DestDir", "Output Destination Directory", quote=True, browse="dir", width=52),
    FieldSpec("Output.STL", "Generate STL", kind="check", default=True, emit_default=True),
    FieldSpec("Output.MSH", "Generate MSH", kind="check", default=False, emit_default=True),
    FieldSpec("Output.ABECProject", "Generate ABEC Project", kind="check", default=False, emit_default=True),
)

GRID_EXPORT_FIELDS = (
    FieldSpec("GRID.Tag", "Grid Export Tag"),
    FieldSpec("GRID.ProfileRange", "Profile Range (from,to)"),
    FieldSpec("GRID.SliceRange", "Slice Range (from,to)"),
    FieldSpec("GRID.ExportProfiles", "Export Profiles", kind="check", default=False),
    FieldSpec("GRID.ExportSlices", "Export Slices", kind="check", default=False),
    FieldSpec("GRID.Scale", "Scale", default="1.0"),
    FieldSpec("GRID.Delimiter", "Delimiter", default=";", quote=True),
    FieldSpec("GRID.FileExtension", "File Extension", default="csv", quote=True),
    FieldSpec("GRID.SeparateFiles", "Separate Files", kind="check", default=False),
)

REPORT_FIELDS = (
    FieldSpec("REPORT.Title", "Report Title", quote=True, width=42),
    FieldSpec("REPORT.PolarData", "Polar Data Tag"),
    FieldSpec("REPORT.NormAngle", "Report Norm Angle [deg]"),
    FieldSpec("REPORT.MaxAngle", "Max Angle [deg]"),
    FieldSpec("REPORT.SPL_Range", "SPL Range [dB]"),
    FieldSpec("REPORT.DrvImp_Range", "Driver Impedance Range [Ohm]"),
    FieldSpec("REPORT.ExcRefSPL", "Reference Excursion SPL [dB]"),
    FieldSpec("REPORT.MaxRadius", "Profile Sketch Radius [mm]"),
    FieldSpec("REPORT.Width", "Report Width [px]"),
    FieldSpec("REPORT.Height", "Report Height [px]"),
    FieldSpec("REPORT.GnuplotCode", "Gnuplot Script", quote=True, browse="file", width=52),
)

ADVANCED_FIELDS = (
    FieldSpec("ADVANCED.Raw", "Additional ATH Items / Blocks", kind="multiline", width=80),
)

FIELD_SECTIONS = (
    ("Global", "ATH global configuration used by ath.exe on startup.", GLOBAL_FIELDS),
    ("Geometry", "Core waveguide geometry and profile settings from Chapter 4.1.1.", GEOMETRY_FIELDS),
    ("Geometry", "Guiding curve controls for implicit shape definition.", GUIDING_CURVE_FIELDS),
    ("Morph", "Mouth outline morphing and rollback controls.", MORPH_FIELDS),
    ("Morph", "Rollback controls for free-standing horns.", ROLLBACK_FIELDS),
    ("Mesh", "Mesh density, interfaces, and rear wall settings.", MESH_FIELDS),
    ("Mesh", "Optional stock enclosure block.", ENCLOSURE_FIELDS),
    ("Simulation", "ABEC / BEM setup.", ABEC_FIELDS),
    ("Simulation", "Source definition and optional inline source script.", SOURCE_FIELDS),
    ("Simulation", "Optional lumped element model.", LE_FIELDS),
    ("Simulation", "Single editable polar observation block.", POLAR_FIELDS),
    ("Output", "Program output switches and destination overrides.", OUTPUT_FIELDS),
    ("Output", "Optional grid export block.", GRID_EXPORT_FIELDS),
    ("Output", "Optional report block.", REPORT_FIELDS),
    ("Advanced", "Unknown or advanced ATH items are preserved here.", ADVANCED_FIELDS),
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
