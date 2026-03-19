from __future__ import annotations

from copy import deepcopy


def _to_float_or_zero(value: object) -> float:
    """Convert numeric-like input to float; treat blanks as 0.0."""
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _fmt(value: float) -> str:
    """Format numbers for ATH cfg fields without noisy trailing zeros."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def derive_auto_enclosure(
    state: dict[str, object],
    xy_extra_total: float = 5.0,
    extra_depth: float = 10.0,
    per_side: bool = False,
) -> dict[str, object]:
    """
    Derive Mesh.Enclosure fields from horn lengths and requested extra margins.

    Rules:
    - total_len = Length + Throat.Ext.Length + Slot.Length
    - side_margin = xy_extra_total/2 when per_side=False
    - side_margin = xy_extra_total when per_side=True
    - ENCLOSURE.Spacing = "L,T,R,B" with side_margin repeated
    - ENCLOSURE.Depth = total_len + extra_depth
    - ENCLOSURE.EdgeType = "1"
    - ENCLOSURE.EdgeRadius = min(side_margin, extra_depth/2)
    """
    result: dict[str, object] = deepcopy(state)

    length_main = _to_float_or_zero(state.get("Length", 0))
    length_throat_ext = _to_float_or_zero(state.get("Throat.Ext.Length", 0))
    length_slot = _to_float_or_zero(state.get("Slot.Length", 0))
    total_len = length_main + length_throat_ext + length_slot

    side_margin = float(xy_extra_total) if per_side else (float(xy_extra_total) / 2.0)
    side_margin = max(side_margin, 0.0)
    extra_depth = max(float(extra_depth), 0.0)

    depth = max(total_len + extra_depth, 0.0)
    edge_radius = max(min(side_margin, extra_depth / 2.0), 0.0)
    side_text = _fmt(side_margin)

    result["ENCLOSURE.Spacing"] = f"{side_text},{side_text},{side_text},{side_text}"
    result["ENCLOSURE.Depth"] = _fmt(depth)
    result["ENCLOSURE.EdgeType"] = "1"
    result["ENCLOSURE.EdgeRadius"] = _fmt(edge_radius)
    return result

