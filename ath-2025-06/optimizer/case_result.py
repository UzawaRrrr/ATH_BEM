"""Canonical case-result containers for ATH/BEM automation runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def normalize_path(value: str | Path | None) -> Path | None:
    """Normalize an optional path-like value into a `Path` instance."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(text).expanduser()


def _serialize_path(value: Path | None) -> str | None:
    return None if value is None else str(value)


def _normalize_logs(payload: dict[str, Any] | None) -> dict[str, Path]:
    logs: dict[str, Path] = {}
    for key, value in dict(payload or {}).items():
        path = normalize_path(value)
        if path is not None:
            logs[str(key)] = path
    return logs


def _pick_path(mapping: dict[str, Any], *candidates: str) -> Path | None:
    for key in candidates:
        path = normalize_path(mapping.get(key))
        if path is not None:
            return path
    return None


@dataclass(frozen=True, slots=True)
class CaseArtifacts:
    """Filesystem artifacts produced by an ATH/BEM automation run."""

    case_dir: Path
    output_dir: Path | None = None
    horn_cfg_path: Path | None = None
    global_cfg_path: Path | None = None
    summary_json: Path | None = None
    mesh_info_json: Path | None = None
    polar_csv: Path | None = None
    solution_npz: Path | None = None
    optimizer_payload: Path | None = None
    optimizer_status_json: Path | None = None
    logs: dict[str, Path] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CaseArtifacts:
        """Build artifacts from either nested or legacy dict payloads."""
        data = dict(payload)
        workspace_paths = data.get("workspace_paths") if isinstance(data.get("workspace_paths"), dict) else {}
        result_dir = _pick_path(data, "result_dir", "bempp_dir")
        if result_dir is None:
            result_dir = _pick_path(workspace_paths, "bempp")
        workspace = _pick_path(data, "case_dir", "run_root", "workspace")
        if workspace is None:
            workspace = _pick_path(workspace_paths, "run_root")
        output_dir = _pick_path(data, "output_dir")
        if output_dir is None and workspace is not None:
            output_dir = workspace
        if output_dir is None and result_dir is not None:
            output_dir = result_dir
        case_dir = workspace or output_dir or result_dir
        if case_dir is None:
            summary_path = _pick_path(data, "summary_json")
            mesh_info_path = _pick_path(data, "mesh_info_json")
            polar_path = _pick_path(data, "polar_csv")
            solution_path = _pick_path(data, "solution_npz")
            candidate = summary_path or mesh_info_path or polar_path or solution_path
            if candidate is not None:
                case_dir = candidate.parent
        if case_dir is None:
            if any(
                key in data
                for key in ("freqs_hz", "frequencies_hz", "spl_db", "spl_h_db", "spl_v_db", "summary", "mesh_info", "polar_rows")
            ):
                case_dir = Path.cwd()
            else:
                raise ValueError("CaseArtifacts.from_dict could not infer a case_dir from the supplied payload.")

        summary_json = _pick_path(data, "summary_json")
        mesh_info_json = _pick_path(data, "mesh_info_json")
        polar_csv = _pick_path(data, "polar_csv")
        solution_npz = _pick_path(data, "solution_npz")
        optimizer_payload = _pick_path(data, "optimizer_payload")
        optimizer_status_json = _pick_path(data, "optimizer_status_json")

        if result_dir is not None:
            summary_json = summary_json or (result_dir / "summary.json")
            mesh_info_json = mesh_info_json or (result_dir / "mesh_info.json")
            polar_csv = polar_csv or (result_dir / "polar.csv")
            solution_npz = solution_npz or (result_dir / "solution.npz")
            optimizer_payload = optimizer_payload or (result_dir / "optimizer_payload.npz")
            optimizer_status_json = optimizer_status_json or (result_dir / "optimizer_status.json")

        logs = _normalize_logs(data.get("logs"))
        log_path = _pick_path(data, "log_path", "solver_log")
        if log_path is not None and "solver" not in logs:
            logs["solver"] = log_path

        return cls(
            case_dir=case_dir,
            output_dir=output_dir,
            horn_cfg_path=_pick_path(data, "horn_cfg_path", "cfg_path") or _pick_path(workspace_paths, "horn_cfg_path"),
            global_cfg_path=_pick_path(data, "global_cfg_path") or _pick_path(workspace_paths, "ath_global_cfg_path"),
            summary_json=summary_json,
            mesh_info_json=mesh_info_json,
            polar_csv=polar_csv,
            solution_npz=solution_npz,
            optimizer_payload=optimizer_payload,
            optimizer_status_json=optimizer_status_json,
            logs=logs,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize artifacts to a JSON-compatible dict."""
        return {
            "case_dir": str(self.case_dir),
            "output_dir": _serialize_path(self.output_dir),
            "horn_cfg_path": _serialize_path(self.horn_cfg_path),
            "global_cfg_path": _serialize_path(self.global_cfg_path),
            "summary_json": _serialize_path(self.summary_json),
            "mesh_info_json": _serialize_path(self.mesh_info_json),
            "polar_csv": _serialize_path(self.polar_csv),
            "solution_npz": _serialize_path(self.solution_npz),
            "optimizer_payload": _serialize_path(self.optimizer_payload),
            "optimizer_status_json": _serialize_path(self.optimizer_status_json),
            "logs": {key: str(value) for key, value in self.logs.items()},
        }


@dataclass(frozen=True, slots=True)
class CaseStatus:
    """Discrete automation/run status flags mapped to scorer-facing geometry status."""

    ath_ok: bool = True
    bem_ok: bool = True
    post_ok: bool = True
    mesh_ok: bool = True
    geometry_ok: bool = True
    self_intersection: bool = False
    mesh_quality_ok: bool = True
    exit_code: int | None = None
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CaseStatus:
        """Build status from nested or legacy dict payloads."""
        data = dict(payload)
        exit_code_value = data.get("exit_code")
        if exit_code_value is None and data.get("return_code") is not None:
            exit_code_value = data.get("return_code")
        return cls(
            ath_ok=bool(data.get("ath_ok", True)),
            bem_ok=bool(data.get("bem_ok", data.get("solver_ok", True))),
            post_ok=bool(data.get("post_ok", True)),
            mesh_ok=bool(data.get("mesh_ok", True)),
            geometry_ok=bool(data.get("geometry_ok", True)),
            self_intersection=bool(data.get("self_intersection", False)),
            mesh_quality_ok=bool(data.get("mesh_quality_ok", True)),
            exit_code=None if exit_code_value is None else int(exit_code_value),
            notes=[str(item) for item in data.get("notes", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize status to a JSON-compatible dict."""
        return {
            "ath_ok": self.ath_ok,
            "bem_ok": self.bem_ok,
            "post_ok": self.post_ok,
            "mesh_ok": self.mesh_ok,
            "geometry_ok": self.geometry_ok,
            "self_intersection": self.self_intersection,
            "mesh_quality_ok": self.mesh_quality_ok,
            "exit_code": self.exit_code,
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class CaseResult:
    """Canonical run result wrapper consumed by the bridge layer."""

    artifacts: CaseArtifacts
    status: CaseStatus
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | CaseResult) -> CaseResult:
        """Build a `CaseResult` from nested, legacy, or already-normalized payloads."""
        if isinstance(payload, cls):
            return payload
        data = dict(payload)

        artifacts_payload = data.get("artifacts") if isinstance(data.get("artifacts"), dict) else data
        status_payload = data.get("status") if isinstance(data.get("status"), dict) else data
        artifacts = CaseArtifacts.from_dict(artifacts_payload)
        status = CaseStatus.from_dict(status_payload)

        meta = dict(data.get("meta", {}))
        for key in (
            "summary",
            "mesh_info",
            "job",
            "polar_rows",
            "freqs_hz",
            "frequencies_hz",
            "angles_deg",
            "spl_db",
            "angles_deg_h",
            "angles_deg_v",
            "spl_h_db",
            "spl_v_db",
            "onaxis_db",
            "di_db",
            "sound_power_db",
            "listening_window_db",
            "beamwidth_6_h_deg",
            "beamwidth_6_v_deg",
            "beamwidth_12_h_deg",
            "beamwidth_12_v_deg",
            "workspace_paths",
            "group_map",
            "result_dir",
            "log_path",
            "case_name",
            "run_id",
        ):
            if key in data and key not in meta:
                meta[key] = data[key]

        return cls(artifacts=artifacts, status=status, meta=meta)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the case result to a nested JSON-compatible dict."""
        return {
            "artifacts": self.artifacts.to_dict(),
            "status": self.status.to_dict(),
            "meta": dict(self.meta),
        }
