from __future__ import annotations

import csv
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimizer.case_result import CaseArtifacts, CaseResult, CaseStatus
from optimizer.objective import objective_from_result_bundle, optuna_objective_wrapper
from optimizer.result_bridge import (
    case_result_to_score_inputs,
    emit_optimizer_payload,
    emit_optimizer_status_json,
    load_from_optimizer_payload,
    load_polar_data,
)
from optimizer.score_defaults import build_default_objective_config


def _write_csv(path: Path, rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def _make_case_result(case_dir: Path, **kwargs: object) -> CaseResult:
    artifacts = CaseArtifacts(
        case_dir=case_dir,
        summary_json=kwargs.get("summary_json"),
        mesh_info_json=kwargs.get("mesh_info_json"),
        polar_csv=kwargs.get("polar_csv"),
        solution_npz=kwargs.get("solution_npz"),
        optimizer_payload=kwargs.get("optimizer_payload"),
        optimizer_status_json=kwargs.get("optimizer_status_json"),
    )
    status = kwargs.get("status") or CaseStatus()
    return CaseResult(artifacts=artifacts, status=status, meta=dict(kwargs.get("meta", {})))


def test_case_result_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        case_dir = Path(tmp)
        payload = {
            "artifacts": {
                "case_dir": str(case_dir),
                "result_dir": str(case_dir / "bempp"),
                "summary_json": str(case_dir / "bempp" / "summary.json"),
                "logs": {"solver": str(case_dir / "bempp" / "solver.log")},
            },
            "status": {
                "ath_ok": True,
                "bem_ok": False,
                "post_ok": False,
                "mesh_ok": True,
                "geometry_ok": True,
                "self_intersection": False,
                "mesh_quality_ok": True,
                "exit_code": 1,
                "notes": ["solver failed"],
            },
            "meta": {"case_name": "demo"},
        }
        case_result = CaseResult.from_dict(payload)
        roundtrip = CaseResult.from_dict(case_result.to_dict())
        assert roundtrip.to_dict() == case_result.to_dict()


def test_load_from_optimizer_payload_supports_full_and_partial_payloads() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload_path = root / "optimizer_payload.npz"
        status_path = root / "optimizer_status.json"
        freqs_hz = np.asarray([1000.0, 2000.0])
        emit_optimizer_payload(
            payload_path,
            freqs_hz=freqs_hz,
            angles_deg_h=np.asarray([0.0, 10.0]),
            angles_deg_v=np.asarray([0.0, 15.0]),
            spl_h_db=np.asarray([[100.0, 101.0], [99.0, 100.0]]),
            spl_v_db=np.asarray([[100.0, 101.0], [98.0, 99.0]]),
            onaxis_db=np.asarray([100.0, 101.0]),
        )
        emit_optimizer_status_json(status_path, {"ath_ok": True, "bem_ok": True, "post_ok": True, "mesh_ok": True, "geometry_ok": True})
        polar, geom = load_from_optimizer_payload(payload_path, status_path)
        assert polar.has_horizontal and polar.has_vertical
        assert np.allclose(polar.onaxis_db, np.asarray([100.0, 101.0]))
        assert geom.solver_ok is True

        payload_path_partial = root / "optimizer_payload_partial.npz"
        emit_optimizer_payload(
            payload_path_partial,
            freqs_hz=freqs_hz,
            angles_deg_h=np.asarray([0.0, 10.0]),
            angles_deg_v=np.empty(0),
            spl_h_db=np.asarray([[100.0, 101.0], [99.0, 100.0]]),
            spl_v_db=np.empty((0, freqs_hz.size)),
            status={"ath_ok": True, "bem_ok": True, "post_ok": True, "mesh_ok": True, "geometry_ok": True},
        )
        polar_partial, geom_partial = load_from_optimizer_payload(payload_path_partial)
        assert polar_partial.has_horizontal is True
        assert polar_partial.has_vertical is False
        assert geom_partial.mesh_ok is True


def test_canonical_polar_csv_parser_handles_hv_h_only_and_missing_cells() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        canonical_path = root / "polar_hv.csv"
        _write_csv(
            canonical_path,
            [
                ["plane", "angle_deg", "freq_hz", "spl_db"],
                ["H", 0, 1000, 100.0],
                ["H", 10, 1000, 99.0],
                ["H", 0, 2000, 101.0],
                ["H", 10, 2000, 100.0],
                ["V", 0, 1000, 100.0],
                ["V", 15, 1000, 98.0],
                ["V", 0, 2000, 101.0],
                ["V", 15, 2000, 99.0],
            ],
        )
        polar = load_polar_data(_make_case_result(root, polar_csv=canonical_path))
        assert polar.spl_h_db.shape == (2, 2)
        assert polar.spl_v_db.shape == (2, 2)

        h_only_path = root / "polar_h_only.csv"
        _write_csv(
            h_only_path,
            [
                ["plane", "angle_deg", "freq_hz", "spl_db"],
                ["H", 0, 1000, 100.0],
                ["H", 10, 1000, 99.0],
                ["H", 0, 2000, 101.0],
                ["H", 10, 2000, 100.0],
            ],
        )
        polar_h_only = load_polar_data(_make_case_result(root, polar_csv=h_only_path))
        assert polar_h_only.has_horizontal is True
        assert polar_h_only.has_vertical is False

        missing_path = root / "polar_missing.csv"
        _write_csv(
            missing_path,
            [
                ["plane", "angle_deg", "freq_hz", "spl_db"],
                ["H", 0, 1000, 100.0],
                ["H", 10, 1000, 99.0],
                ["H", 0, 2000, 101.0],
            ],
        )
        polar_missing = load_polar_data(_make_case_result(root, polar_csv=missing_path))
        assert np.isnan(polar_missing.spl_h_db[1, 1])


def test_legacy_bundle_fallback_builds_score_inputs_even_with_missing_optional_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        summary_path = root / "summary.json"
        summary_path.write_text(
            '{"status":"done","plane":"XZ","onaxis_db":[100.0,101.0],"beamwidth_6_h_deg":[90.0,88.0]}',
            encoding="utf-8",
        )
        polar_path = root / "polar.csv"
        _write_csv(
            polar_path,
            [
                ["freq_hz", "angle_deg", "spl_db"],
                [1000, 0, 100.0],
                [1000, 10, 99.0],
                [2000, 0, 101.0],
                [2000, 10, 100.0],
            ],
        )
        case_result = _make_case_result(root, summary_json=summary_path, polar_csv=polar_path)
        polar, geom = case_result_to_score_inputs(case_result)
        assert polar.has_horizontal is True
        assert np.allclose(polar.onaxis_db, np.asarray([100.0, 101.0]))
        assert geom.solver_ok is True


def test_objective_from_result_bundle_via_bridge_produces_finite_total() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload_path = root / "optimizer_payload.npz"
        status_path = root / "optimizer_status.json"
        freqs_hz = np.geomspace(1000.0, 8000.0, 8)
        angles_deg_h = np.asarray([-20.0, 0.0, 20.0])
        spl_h_db = np.asarray(
            [
                np.linspace(97.0, 96.0, freqs_hz.size),
                np.linspace(100.0, 99.0, freqs_hz.size),
                np.linspace(97.0, 96.0, freqs_hz.size),
            ]
        )
        emit_optimizer_payload(
            payload_path,
            freqs_hz=freqs_hz,
            angles_deg_h=angles_deg_h,
            angles_deg_v=np.empty(0),
            spl_h_db=spl_h_db,
            spl_v_db=np.empty((0, freqs_hz.size)),
            onaxis_db=spl_h_db[1, :],
            beamwidth_6_h_deg=np.linspace(90.0, 70.0, freqs_hz.size),
        )
        emit_optimizer_status_json(status_path, {"ath_ok": True, "bem_ok": True, "post_ok": True, "mesh_ok": True, "geometry_ok": True})
        case_result = _make_case_result(root, optimizer_payload=payload_path, optimizer_status_json=status_path)
        config = replace(build_default_objective_config(stage="final"), target_bw_h_deg=80.0)
        score = objective_from_result_bundle(case_result, config)
        assert np.isfinite(score.total)


class _FakeTrial:
    def __init__(self, params: dict[str, float] | None = None) -> None:
        self.params = params or {}
        self.user_attrs: dict[str, object] = {}

    def set_user_attr(self, key: str, value: object) -> None:
        self.user_attrs[key] = value


class _FakeRunner:
    def __init__(self, result: CaseResult) -> None:
        self.result = result
        self.seen_params: dict[str, float] | None = None

    def run(self, params: dict[str, float]) -> CaseResult:
        self.seen_params = dict(params)
        return self.result


def test_optuna_wrapper_smoke_with_fake_runner_and_trial() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload_path = root / "optimizer_payload.npz"
        status_path = root / "optimizer_status.json"
        freqs_hz = np.asarray([1000.0, 2000.0, 4000.0])
        emit_optimizer_payload(
            payload_path,
            freqs_hz=freqs_hz,
            angles_deg_h=np.asarray([0.0, 15.0]),
            angles_deg_v=np.empty(0),
            spl_h_db=np.asarray([[100.0, 100.5, 101.0], [98.0, 98.5, 99.0]]),
            spl_v_db=np.empty((0, freqs_hz.size)),
            onaxis_db=np.asarray([100.0, 100.5, 101.0]),
            beamwidth_6_h_deg=np.asarray([90.0, 80.0, 70.0]),
        )
        emit_optimizer_status_json(status_path, {"ath_ok": True, "bem_ok": True, "post_ok": True, "mesh_ok": True, "geometry_ok": True})
        case_result = _make_case_result(root, optimizer_payload=payload_path, optimizer_status_json=status_path)
        runner = _FakeRunner(case_result)
        trial = _FakeTrial(params={"flare": 1.25})
        config = replace(build_default_objective_config(stage="final"), target_bw_h_deg=80.0)

        total = optuna_objective_wrapper(trial, runner, config=config)

        assert np.isfinite(total)
        assert runner.seen_params == {"flare": 1.25}
        assert "score.total" in trial.user_attrs
        assert "score.coverage" in trial.user_attrs
        assert "flags.any_missing" in trial.user_attrs
        assert "flags.catastrophic" in trial.user_attrs
