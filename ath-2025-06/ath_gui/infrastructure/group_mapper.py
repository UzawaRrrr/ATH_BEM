from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SOURCE_KEYWORDS = ("drv", "driver", "source")
_WALL_KEYWORDS = ("wall", "horn", "baffle", "enclosure")
_INTERFACE_KEYWORDS = ("interface",)
_IGNORE_KEYWORDS = ("ignore", "dummy", "air")


@dataclass(frozen=True, slots=True)
class GroupMapSuggestion:
    source_groups: list[int]
    wall_groups: list[int]
    interface_groups: list[int]
    ignore_groups: list[int]
    confidence: str
    reasons: list[str]
    requires_confirmation: bool
    mesh_family: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ath.group_map.v1",
            "mesh_family": self.mesh_family,
            "source_groups": self.source_groups,
            "wall_groups": self.wall_groups,
            "interface_groups": self.interface_groups,
            "ignore_groups": self.ignore_groups,
            "confidence": self.confidence,
            "requires_confirmation": self.requires_confirmation,
            "reasons": self.reasons,
        }


def _normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _contains_keyword(name: str, keywords: tuple[str, ...]) -> bool:
    normalized = _normalize_name(name)
    return any(keyword in normalized for keyword in keywords)


def mesh_family_key(mesh_info: dict[str, object]) -> str:
    ids = [str(int(value)) for value in mesh_info.get("detected_groups", [])]
    counts = {str(key): int(value) for key, value in dict(mesh_info.get("element_count_per_group", {})).items()}
    names = {str(key): str(value) for key, value in dict(mesh_info.get("group_name_map", {})).items()}
    parts = [
        str(mesh_info.get("group_source", "unknown")),
        ",".join(ids),
        ";".join(f"{key}:{counts.get(key, 0)}" for key in sorted(counts, key=lambda item: int(item))),
        ";".join(f"{key}:{names.get(key, '')}" for key in sorted(names, key=lambda item: int(item))),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def suggest_group_map(mesh_info: dict[str, object]) -> GroupMapSuggestion:
    groups = sorted(int(value) for value in mesh_info.get("detected_groups", []))
    name_map = {int(key): str(value) for key, value in dict(mesh_info.get("group_name_map", {})).items()}
    reasons: list[str] = []

    source: set[int] = set()
    walls: set[int] = set()
    interfaces: set[int] = set()
    ignore: set[int] = set()

    for group_id in groups:
        name = name_map.get(group_id, "")
        if group_id == 1001 or "drvgroup" in _normalize_name(name):
            source.add(group_id)
            reasons.append(f"group {group_id} promoted to source (1001/DrvGroup rule).")
            continue
        if _contains_keyword(name, _SOURCE_KEYWORDS):
            source.add(group_id)
            reasons.append(f"group {group_id} detected as source by name `{name}`.")
            continue
        if _contains_keyword(name, _INTERFACE_KEYWORDS):
            interfaces.add(group_id)
            reasons.append(f"group {group_id} detected as interface by name `{name}`.")
            continue
        if _contains_keyword(name, _IGNORE_KEYWORDS):
            ignore.add(group_id)
            reasons.append(f"group {group_id} detected as ignore by name `{name}`.")
            continue
        if _contains_keyword(name, _WALL_KEYWORDS):
            walls.add(group_id)
            reasons.append(f"group {group_id} detected as wall by name `{name}`.")

    unresolved = [group_id for group_id in groups if group_id not in source | walls | interfaces | ignore]

    # Conservative fill: only auto-assign unresolved groups to wall when source is unambiguous.
    if len(source) == 1:
        for group_id in unresolved:
            walls.add(group_id)
            reasons.append(f"group {group_id} assigned to wall as unresolved fallback.")

    requires_confirmation = False
    confidence = "high"
    if not source:
        confidence = "low"
        requires_confirmation = True
        reasons.append("no source group could be inferred.")
    elif len(source) > 1:
        confidence = "medium"
        requires_confirmation = True
        reasons.append("multiple source-like groups found; please confirm.")
    elif unresolved:
        confidence = "medium"
        requires_confirmation = True
        reasons.append(f"{len(unresolved)} unresolved groups remain.")

    family = mesh_family_key(mesh_info)
    return GroupMapSuggestion(
        source_groups=sorted(source),
        wall_groups=sorted(walls),
        interface_groups=sorted(interfaces),
        ignore_groups=sorted(ignore),
        confidence=confidence,
        reasons=reasons,
        requires_confirmation=requires_confirmation,
        mesh_family=family,
    )


def _group_cache_dir(case_root: Path) -> Path:
    return case_root / "group_maps"


def load_cached_group_map(case_root: Path, mesh_family: str) -> dict[str, object] | None:
    target = _group_cache_dir(case_root) / f"{mesh_family}.json"
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    if str(data.get("mesh_family", "")).strip() != mesh_family:
        return None
    return data


def save_cached_group_map(case_root: Path, payload: dict[str, object]) -> Path:
    mesh_family = str(payload.get("mesh_family", "")).strip()
    if not mesh_family:
        raise ValueError("group map payload requires mesh_family")
    cache_dir = _group_cache_dir(case_root)
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{mesh_family}.json"
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return target
