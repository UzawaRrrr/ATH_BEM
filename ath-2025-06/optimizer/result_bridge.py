"""Bridge existing ATH/BEM result bundles into scorer-facing optimizer inputs."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .case_result import CaseResult, CaseStatus, normalize_path
from .score_types import GeometryStatus, PolarData


LOGGER = logging.getLogger(__name__)


_SUMMARY_ARRAY_KEYS: dict[str, tuple[str, ...]] = {
    "onaxis_db": ("onaxis_db", "on_axis_db", "onaxis", "on_axis"),
    "di_db": ("di_db", "directivity_index_db", "di", "directivity_index"),
    "sound_power_db": ("sound_power_db", "soundpower_db", "sound_power", "soundPower"),
    "listening_window_db": ("listening_window_db", "listeningwindow_db", "listening_window", "listeningWindow"),
    "beamwidth_6_h_deg": ("beamwidth_6_h_deg", "beamwidth6_h_deg", "beamwidth_h_deg", "bw6_h_deg"),
    "beamwidth_6_v_deg": ("beamwidth_6_v_deg", "beamwidth6_v_deg", "beamwidth_v_deg", "bw6_v_deg"),
    "beamwidth_12_h_deg": ("beamwidth_12_h_deg", "beamwidth12_h_deg", "bw12_h_deg"),
    "beamwidth_12_v_deg": ("beamwidth_12_v_deg", "beamwidth12_v_deg", "bw12_v_deg"),
}


def _pick_first_present(mapping: dict[str, Any] | None, candidates: Iterable[str]) -> Any:
    """Return the first non-`None` value present under any candidate key."""
    source = dict(mapping or {})
    for key in candidates:
        if key in source and source[key] is not None:
            return source[key]
    return None


def _coerce_optional_path(value: str | Path | None) -> Path | None:
    """Normalize an optional path value into a `Path` instance."""
    return normalize_path(value)


def _coerce_array(value: Any, *, name: str, allow_empty: bool = True) -> np.ndarray:
    """Convert an input sequence to a NumPy float array with clear error messages."""
    if value is None:
        if allow_empty:
            return np.empty(0, dtype=float)
        raise ValueError(f"{name} is required.")
    array = np.asarray(value, dtype=float)
    if array.size == 0 and not allow_empty:
        raise ValueError(f"{name} must not be empty.")
    return array


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"Failed to read JSON from {path}: {exc}") from exc


def _load_summary_mapping(case_result: CaseResult) -> dict[str, Any]:
    raw = case_result.meta.get("summary")
    if isinstance(raw, dict):
        return raw
    path = case_result.artifacts.summary_json
    if path is not None and path.exists():
        return _read_json_file(path)
    return {}


def _load_mesh_info_mapping(case_result: CaseResult) -> dict[str, Any]:
    raw = case_result.meta.get("mesh_info")
    if isinstance(raw, dict):
        return raw
    path = case_result.artifacts.mesh_info_json
    if path is not None and path.exists():
        return _read_json_file(path)
    return {}


def _load_job_mapping(case_result: CaseResult) -> dict[str, Any]:
    raw = case_result.meta.get("job")
    if isinstance(raw, dict):
        return raw
    return {}


def _status_mapping_to_geometry(status_mapping: dict[str, Any] | None, fallback_status: CaseStatus | None = None) -> GeometryStatus:
    """Map canonical/legacy status mappings into scorer-facing geometry status."""
    base = fallback_status or CaseStatus()
    mapping = dict(status_mapping or {})
    case_status = CaseStatus(
        ath_ok=bool(mapping.get("ath_ok", base.ath_ok)),
        bem_ok=bool(mapping.get("bem_ok", base.bem_ok)),
        post_ok=bool(mapping.get("post_ok", base.post_ok)),
        mesh_ok=bool(mapping.get("mesh_ok", base.mesh_ok)),
        geometry_ok=bool(mapping.get("geometry_ok", base.geometry_ok)),
        self_intersection=bool(mapping.get("self_intersection", base.self_intersection)),
        mesh_quality_ok=bool(mapping.get("mesh_quality_ok", base.mesh_quality_ok)),
        exit_code=base.exit_code if mapping.get("exit_code") is None else int(mapping["exit_code"]),
        notes=[str(item) for item in mapping.get("notes", base.notes)],
    )
    return GeometryStatus(
        mesh_ok=case_status.mesh_ok,
        solver_ok=case_status.ath_ok and case_status.bem_ok and case_status.post_ok,
        geometry_ok=case_status.geometry_ok,
        self_intersection=case_status.self_intersection,
        mesh_quality_ok=case_status.mesh_quality_ok,
        notes=list(case_status.notes),
    )


def emit_optimizer_status_json(out_path: Path, status: dict[str, Any]) -> None:
    """Write canonical optimizer status JSON."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(dict(status), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def emit_optimizer_payload(
    out_path: Path,
    *,
    freqs_hz: Any,
    angles_deg_h: Any,
    angles_deg_v: Any,
    spl_h_db: Any,
    spl_v_db: Any,
    onaxis_db: Any = None,
    di_db: Any = None,
    sound_power_db: Any = None,
    listening_window_db: Any = None,
    beamwidth_6_h_deg: Any = None,
    beamwidth_6_v_deg: Any = None,
    beamwidth_12_h_deg: Any = None,
    beamwidth_12_v_deg: Any = None,
    status: dict[str, Any] | None = None,
) -> None:
    """Emit canonical optimizer payload as `np.savez_compressed`."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "freqs_hz": _coerce_array(freqs_hz, name="freqs_hz", allow_empty=False).reshape(-1),
        "angles_deg_h": _coerce_array(angles_deg_h, name="angles_deg_h").reshape(-1),
        "angles_deg_v": _coerce_array(angles_deg_v, name="angles_deg_v").reshape(-1),
        "spl_h_db": np.asarray(spl_h_db, dtype=float),
        "spl_v_db": np.asarray(spl_v_db, dtype=float),
    }
    optional_arrays = {
        "onaxis_db": onaxis_db,
        "di_db": di_db,
        "sound_power_db": sound_power_db,
        "listening_window_db": listening_window_db,
        "beamwidth_6_h_deg": beamwidth_6_h_deg,
        "beamwidth_6_v_deg": beamwidth_6_v_deg,
        "beamwidth_12_h_deg": beamwidth_12_h_deg,
        "beamwidth_12_v_deg": beamwidth_12_v_deg,
    }
    for key, value in optional_arrays.items():
        if value is not None:
            payload[key] = np.asarray(value, dtype=float)
    if status is not None:
        payload["status_json"] = json.dumps(dict(status), ensure_ascii=True)

    np.savez_compressed(out_path, **payload)


def _parse_status_json_text(text: str | bytes | None) -> dict[str, Any]:
    if text is None:
        return {}
    raw = text.decode("utf-8") if isinstance(text, bytes) else str(text)
    if not raw.strip():
        return {}
    return json.loads(raw)


def load_from_optimizer_payload(
    payload_path: Path,
    status_path: Path | None = None,
) -> tuple[PolarData, GeometryStatus]:
    """Load canonical optimizer payload/status artifacts."""
    payload_path = Path(payload_path)
    if not payload_path.exists():
        raise FileNotFoundError(f"optimizer payload not found: {payload_path}")

    with np.load(payload_path, allow_pickle=False) as payload:
        freqs_hz = np.asarray(payload["freqs_hz"], dtype=float).reshape(-1)
        angles_deg_h = np.asarray(payload["angles_deg_h"], dtype=float).reshape(-1) if "angles_deg_h" in payload.files else np.empty(0, dtype=float)
        angles_deg_v = np.asarray(payload["angles_deg_v"], dtype=float).reshape(-1) if "angles_deg_v" in payload.files else np.empty(0, dtype=float)
        spl_h_db = np.asarray(payload["spl_h_db"], dtype=float) if "spl_h_db" in payload.files else np.empty((0, freqs_hz.size), dtype=float)
        spl_v_db = np.asarray(payload["spl_v_db"], dtype=float) if "spl_v_db" in payload.files else np.empty((0, freqs_hz.size), dtype=float)
        optional = {
            key: np.asarray(payload[key], dtype=float)
            for key in (
                "onaxis_db",
                "di_db",
                "sound_power_db",
                "listening_window_db",
                "beamwidth_6_h_deg",
                "beamwidth_6_v_deg",
                "beamwidth_12_h_deg",
                "beamwidth_12_v_deg",
            )
            if key in payload.files
        }
        embedded_status = _parse_status_json_text(payload["status_json"].item() if "status_json" in payload.files else None)

    status_mapping = embedded_status
    status_path = _coerce_optional_path(status_path)
    if status_path is not None and status_path.exists():
        status_mapping = _read_json_file(status_path)

    polar = PolarData(
        freqs_hz=freqs_hz,
        angles_deg_h=angles_deg_h,
        angles_deg_v=angles_deg_v,
        spl_h_db=spl_h_db,
        spl_v_db=spl_v_db,
        onaxis_db=optional.get("onaxis_db"),
        di_db=optional.get("di_db"),
        sound_power_db=optional.get("sound_power_db"),
        listening_window_db=optional.get("listening_window_db"),
        beamwidth_6_h_deg=optional.get("beamwidth_6_h_deg"),
        beamwidth_6_v_deg=optional.get("beamwidth_6_v_deg"),
        beamwidth_12_h_deg=optional.get("beamwidth_12_h_deg"),
        beamwidth_12_v_deg=optional.get("beamwidth_12_v_deg"),
    )
    geom = _status_mapping_to_geometry(status_mapping)
    return polar, geom


def _build_plane_matrix(
    rows: list[dict[str, float]],
    *,
    freqs_hz: np.ndarray,
    angles_deg: np.ndarray,
) -> np.ndarray:
    freq_index = {float(value): idx for idx, value in enumerate(freqs_hz)}
    angle_index = {float(value): idx for idx, value in enumerate(angles_deg)}
    sums = np.zeros((angles_deg.size, freqs_hz.size), dtype=float)
    counts = np.zeros_like(sums)
    for row in rows:
        freq = float(row["freq_hz"])
        angle = float(row["angle_deg"])
        value = float(row["spl_db"])
        sums[angle_index[angle], freq_index[freq]] += value
        counts[angle_index[angle], freq_index[freq]] += 1.0
    matrix = np.divide(
        sums,
        np.maximum(counts, 1.0),
        out=np.full_like(sums, np.nan),
        where=counts > 0.0,
    )
    if np.any(counts == 0.0):
        LOGGER.warning("polar.csv contains incomplete angle/frequency grids; missing cells were filled with NaN.")
    return matrix


def _read_polar_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = [str(name) for name in (reader.fieldnames or [])]
            rows = [dict(row) for row in reader]
    except Exception as exc:
        raise ValueError(f"Failed to parse polar.csv from {path}: {exc}") from exc
    if not rows and not fieldnames:
        raise ValueError(f"polar.csv at {path} is empty.")
    return fieldnames, rows


def _parse_canonical_polar_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    fieldnames, rows = _read_polar_csv_rows(path)
    required = {"plane", "angle_deg", "freq_hz", "spl_db"}
    if not required.issubset({name.lower() for name in fieldnames}):
        raise ValueError(f"polar.csv at {path} is missing required canonical fields: {sorted(required)}")

    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        plane = str(_pick_first_present(row, ("plane", "Plane")) or "").strip().upper()
        if plane not in {"H", "V"}:
            LOGGER.warning("Skipping polar.csv row with unsupported plane label %r.", plane)
            continue
        normalized_rows.append(
            {
                "plane": plane,
                "angle_deg": float(_pick_first_present(row, ("angle_deg", "AngleDeg"))),
                "freq_hz": float(_pick_first_present(row, ("freq_hz", "FreqHz"))),
                "spl_db": float(_pick_first_present(row, ("spl_db", "SplDb"))),
            }
        )

    if not normalized_rows:
        raise ValueError(f"polar.csv at {path} does not contain any usable H/V rows.")

    freqs_hz = np.asarray(sorted({float(row["freq_hz"]) for row in normalized_rows}), dtype=float)
    h_rows = [row for row in normalized_rows if row["plane"] == "H"]
    v_rows = [row for row in normalized_rows if row["plane"] == "V"]
    angles_deg_h = np.asarray(sorted({float(row["angle_deg"]) for row in h_rows}), dtype=float) if h_rows else np.empty(0, dtype=float)
    angles_deg_v = np.asarray(sorted({float(row["angle_deg"]) for row in v_rows}), dtype=float) if v_rows else np.empty(0, dtype=float)
    spl_h_db = _build_plane_matrix(h_rows, freqs_hz=freqs_hz, angles_deg=angles_deg_h) if h_rows else np.empty((0, freqs_hz.size), dtype=float)
    spl_v_db = _build_plane_matrix(v_rows, freqs_hz=freqs_hz, angles_deg=angles_deg_v) if v_rows else np.empty((0, freqs_hz.size), dtype=float)
    return freqs_hz, angles_deg_h, angles_deg_v, spl_h_db, spl_v_db


def _parse_legacy_polar_rows(
    rows: list[dict[str, Any]],
    *,
    plane_hint: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    normalized_rows: list[dict[str, float]] = []
    for row in rows:
        try:
            normalized_rows.append(
                {
                    "angle_deg": float(_pick_first_present(row, ("angle_deg", "AngleDeg"))),
                    "freq_hz": float(_pick_first_present(row, ("freq_hz", "FreqHz"))),
                    "spl_db": float(_pick_first_present(row, ("spl_db", "SplDb"))),
                }
            )
        except Exception:
            continue
    if not normalized_rows:
        raise ValueError("Legacy polar rows do not contain any usable samples.")

    freqs_hz = np.asarray(sorted({float(row["freq_hz"]) for row in normalized_rows}), dtype=float)
    angles_deg = np.asarray(sorted({float(row["angle_deg"]) for row in normalized_rows}), dtype=float)
    matrix = _build_plane_matrix(normalized_rows, freqs_hz=freqs_hz, angles_deg=angles_deg)
    if plane_hint == "v":
        return freqs_hz, np.empty(0, dtype=float), angles_deg, np.empty((0, freqs_hz.size), dtype=float), matrix
    return freqs_hz, angles_deg, np.empty(0, dtype=float), matrix, np.empty((0, freqs_hz.size), dtype=float)


def _load_polar_from_csv(case_result: CaseResult, plane_hint: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    polar_rows_meta = case_result.meta.get("polar_rows")
    if isinstance(polar_rows_meta, list) and polar_rows_meta:
        return _parse_legacy_polar_rows(polar_rows_meta, plane_hint=plane_hint)

    polar_path = case_result.artifacts.polar_csv
    if polar_path is None or not polar_path.exists():
        return None

    fieldnames, rows = _read_polar_csv_rows(polar_path)
    if "plane" in {name.lower() for name in fieldnames}:
        return _parse_canonical_polar_csv(polar_path)
    return _parse_legacy_polar_rows(rows, plane_hint=plane_hint)


def _load_solution_arrays(case_result: CaseResult) -> dict[str, np.ndarray]:
    path = case_result.artifacts.solution_npz
    if path is None or not path.exists():
        return {}
    with np.load(path, allow_pickle=False) as payload:
        return {name: np.asarray(payload[name]) for name in payload.files}


def _plane_hint_from_mappings(summary: dict[str, Any], job: dict[str, Any]) -> str:
    for mapping in (summary, job):
        plane = _pick_first_present(mapping, ("plane", "Plane"))
        if plane is None:
            continue
        if str(plane).strip().upper() == "YZ":
            return "v"
        if str(plane).strip().upper() == "XZ":
            return "h"
    return "h"


def _load_polar_from_meta_arrays(case_result: CaseResult, plane_hint: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    meta = case_result.meta
    direct_freqs = meta.get("freqs_hz", meta.get("frequencies_hz"))
    if direct_freqs is None:
        return None

    if meta.get("spl_h_db") is not None or meta.get("spl_v_db") is not None:
        freqs_hz = np.asarray(direct_freqs, dtype=float).reshape(-1)
        angles_deg_h = np.asarray(meta.get("angles_deg_h", []), dtype=float).reshape(-1)
        angles_deg_v = np.asarray(meta.get("angles_deg_v", []), dtype=float).reshape(-1)
        spl_h_db = np.asarray(meta.get("spl_h_db", np.empty((0, freqs_hz.size))), dtype=float)
        spl_v_db = np.asarray(meta.get("spl_v_db", np.empty((0, freqs_hz.size))), dtype=float)
        return freqs_hz, angles_deg_h, angles_deg_v, spl_h_db, spl_v_db

    if meta.get("angles_deg") is not None and meta.get("spl_db") is not None:
        freqs_hz = np.asarray(direct_freqs, dtype=float).reshape(-1)
        angles_deg = np.asarray(meta.get("angles_deg"), dtype=float).reshape(-1)
        spl_db = np.asarray(meta.get("spl_db"), dtype=float)
        if spl_db.shape == (freqs_hz.size, angles_deg.size):
            spl_db = spl_db.T
        rows = [
            {"freq_hz": float(freq_hz), "angle_deg": float(angle_deg), "spl_db": float(spl_db[angle_index, freq_index])}
            for freq_index, freq_hz in enumerate(freqs_hz)
            for angle_index, angle_deg in enumerate(angles_deg)
        ]
        return _parse_legacy_polar_rows(rows, plane_hint=plane_hint)
    return None


def _extract_optional_curve(meta: dict[str, Any], summary: dict[str, Any], solution_arrays: dict[str, np.ndarray], name: str) -> np.ndarray | None:
    if meta.get(name) is not None:
        return np.asarray(meta[name], dtype=float)
    summary_value = _pick_first_present(summary, _SUMMARY_ARRAY_KEYS[name])
    if summary_value is not None:
        return np.asarray(summary_value, dtype=float)
    if name in solution_arrays:
        return np.asarray(solution_arrays[name], dtype=float)
    return None


def _load_legacy_polar_data(case_result: CaseResult) -> PolarData:
    meta = case_result.meta
    summary = _load_summary_mapping(case_result)
    job = _load_job_mapping(case_result)
    solution_arrays = _load_solution_arrays(case_result)
    plane_hint = _plane_hint_from_mappings(summary, job)

    polar_tuple = _load_polar_from_meta_arrays(case_result, plane_hint) or _load_polar_from_csv(case_result, plane_hint)
    if polar_tuple is None and solution_arrays:
        freqs_hz = np.asarray(_pick_first_present(solution_arrays, ("frequencies_hz", "freqs_hz")), dtype=float).reshape(-1)
        angles_deg = np.asarray(_pick_first_present(solution_arrays, ("angles_deg", "angles_deg_h")), dtype=float).reshape(-1)
        spl_db = np.asarray(solution_arrays["spl_db"], dtype=float)
        if spl_db.shape == (freqs_hz.size, angles_deg.size):
            spl_db = spl_db.T
        polar_tuple = _parse_legacy_polar_rows(
            [
                {"freq_hz": float(freq_hz), "angle_deg": float(angle_deg), "spl_db": float(spl_db[angle_index, freq_index])}
                for freq_index, freq_hz in enumerate(freqs_hz)
                for angle_index, angle_deg in enumerate(angles_deg)
            ],
            plane_hint=plane_hint,
        )

    if polar_tuple is None:
        raise ValueError("Could not build PolarData: no optimizer payload, polar.csv, or solution.npz was available.")

    freqs_hz, angles_deg_h, angles_deg_v, spl_h_db, spl_v_db = polar_tuple
    return PolarData(
        freqs_hz=freqs_hz,
        angles_deg_h=angles_deg_h,
        angles_deg_v=angles_deg_v,
        spl_h_db=spl_h_db,
        spl_v_db=spl_v_db,
        onaxis_db=_extract_optional_curve(meta, summary, solution_arrays, "onaxis_db"),
        di_db=_extract_optional_curve(meta, summary, solution_arrays, "di_db"),
        sound_power_db=_extract_optional_curve(meta, summary, solution_arrays, "sound_power_db"),
        listening_window_db=_extract_optional_curve(meta, summary, solution_arrays, "listening_window_db"),
        beamwidth_6_h_deg=_extract_optional_curve(meta, summary, solution_arrays, "beamwidth_6_h_deg"),
        beamwidth_6_v_deg=_extract_optional_curve(meta, summary, solution_arrays, "beamwidth_6_v_deg"),
        beamwidth_12_h_deg=_extract_optional_curve(meta, summary, solution_arrays, "beamwidth_12_h_deg"),
        beamwidth_12_v_deg=_extract_optional_curve(meta, summary, solution_arrays, "beamwidth_12_v_deg"),
    )


def load_geometry_status(case_result: CaseResult) -> GeometryStatus:
    """Load scorer-facing geometry status from canonical or legacy artifacts."""
    status_path = case_result.artifacts.optimizer_status_json
    payload_path = case_result.artifacts.optimizer_payload
    if payload_path is not None and payload_path.exists():
        if status_path is not None and status_path.exists():
            _, geom = load_from_optimizer_payload(payload_path, status_path)
            return geom
        with np.load(payload_path, allow_pickle=False) as payload:
            has_embedded_status = "status_json" in payload.files
        if has_embedded_status:
            _, geom = load_from_optimizer_payload(payload_path, None)
            return geom
    if status_path is not None and status_path.exists():
        return _status_mapping_to_geometry(_read_json_file(status_path), fallback_status=case_result.status)

    summary = _load_summary_mapping(case_result)
    mesh_info = _load_mesh_info_mapping(case_result)
    notes = list(case_result.status.notes)
    notes.extend(str(item) for item in summary.get("warnings", []) if str(item).strip())
    notes.extend(str(item) for item in summary.get("notes", []) if str(item).strip())
    if summary and str(summary.get("status", "done")).strip().lower() != "done":
        notes.append(f"summary.status={summary.get('status')}")

    mesh_ok = case_result.status.mesh_ok
    if summary.get("mesh_file") or mesh_info:
        mesh_ok = mesh_ok and True
    geometry_ok = case_result.status.geometry_ok
    self_intersection = case_result.status.self_intersection or bool(
        _pick_first_present(mesh_info, ("self_intersection", "selfIntersection"))
    )
    mesh_quality_ok = case_result.status.mesh_quality_ok and int(mesh_info.get("nonmanifold_edge_count", 0)) == 0

    return GeometryStatus(
        solver_ok=case_result.status.ath_ok and case_result.status.bem_ok and case_result.status.post_ok and str(summary.get("status", "done")).strip().lower() == "done",
        mesh_ok=mesh_ok,
        geometry_ok=geometry_ok,
        self_intersection=self_intersection,
        mesh_quality_ok=mesh_quality_ok,
        notes=notes,
    )


def load_polar_data(case_result: CaseResult) -> PolarData:
    """Load `PolarData` from canonical payload first, then legacy artifacts."""
    payload_path = case_result.artifacts.optimizer_payload
    if payload_path is not None and payload_path.exists():
        polar, _ = load_from_optimizer_payload(payload_path, case_result.artifacts.optimizer_status_json)
        return polar
    return _load_legacy_polar_data(case_result)


def case_result_to_score_inputs(case_result: CaseResult | dict[str, Any]) -> tuple[PolarData, GeometryStatus]:
    """Convert a `CaseResult` or compatible dict bundle into scorer inputs."""
    normalized = CaseResult.from_dict(case_result)
    return load_polar_data(normalized), load_geometry_status(normalized)
