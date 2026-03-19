"""Load and format BEM result files for the GUI."""

from __future__ import annotations

import csv
import json
from pathlib import Path


STATUS_LABELS = {
    "done": "完成",
    "running": "執行中",
    "idle": "閒置",
    "error": "錯誤",
    "failed": "失敗",
    "unknown": "未知",
}


def describe_bem_status(status: object) -> str:
    """Translate internal BEM status labels into UI-friendly Chinese text."""
    normalized = str(status).strip().lower()
    if not normalized:
        return STATUS_LABELS["unknown"]
    return STATUS_LABELS.get(normalized, str(status))


def default_bem_result_dir(output_dir: Path) -> Path:
    return output_dir / "bempp"


def load_json_file(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_polar_rows(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                {
                    "freq_hz": float(row["freq_hz"]),
                    "angle_deg": float(row["angle_deg"]),
                    "spl_db": float(row["spl_db"]),
                }
            )
    return rows


def load_bem_results(result_dir: Path) -> dict[str, object]:
    summary_path = result_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"在 {summary_path} 找不到 BEM 摘要。")

    mesh_info_path = result_dir / "mesh_info.json"
    polar_path = result_dir / "polar.csv"

    return {
        "result_dir": result_dir,
        "summary": load_json_file(summary_path),
        "mesh_info": load_json_file(mesh_info_path) if mesh_info_path.exists() else {},
        "polar_rows": load_polar_rows(polar_path) if polar_path.exists() else [],
        "log_path": result_dir / "solver.log",
    }


def _format_sequence(values: list[object], *, limit: int = 18) -> str:
    if not values:
        return "（無）"
    if len(values) <= limit:
        return ", ".join(str(value) for value in values)
    visible = ", ".join(str(value) for value in values[:limit])
    return f"{visible}, ... (+{len(values) - limit} more)"


def format_summary_text(results: dict[str, object]) -> str:
    summary = dict(results.get("summary", {}))
    mesh_info = dict(results.get("mesh_info", {}))
    warnings = [str(item) for item in summary.get("warnings", []) if str(item).strip()]
    notes = [str(item) for item in summary.get("notes", []) if str(item).strip()]
    groups = [int(value) for value in mesh_info.get("detected_groups", [])]

    lines = [
        f"狀態：{describe_bem_status(summary.get('status', 'unknown'))}",
        f"網格檔：{summary.get('mesh_file', '')}",
        f"頂點數：{summary.get('vertices', '?')} | 元素數：{summary.get('elements', '?')}",
        f"對稱降階：{'啟用' if summary.get('symmetry_enabled', False) else '關閉'} | 模式：{summary.get('symmetry_mode', 'off')}",
        f"觀測平面：{summary.get('plane', '?')} | 角度範圍：{summary.get('angle_range_mode', 'full_circle')} | 角度點數：{summary.get('theta_count', '?')}",
        f"聲源群組：{_format_sequence(list(summary.get('source_groups', [])))}",
        f"壁面群組：{_format_sequence(list(summary.get('wall_groups', [])))}",
        f"頻率點數：{summary.get('freq_count', '?')} | 執行時間 [s]：{summary.get('runtime_sec', '?')}",
        f"偵測到的網格群組：{_format_sequence(groups)}",
    ]

    if warnings:
        lines.extend(["", "警告："] + [f"- {warning}" for warning in warnings])
    if notes:
        lines.extend(["", "備註："] + [f"- {note}" for note in notes])
    return "\n".join(lines)
