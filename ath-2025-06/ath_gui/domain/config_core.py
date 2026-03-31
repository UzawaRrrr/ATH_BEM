from __future__ import annotations

from pathlib import Path

from .specs import (
    ABEC_FIELDS,
    ADVANCED_FIELDS,
    ENCLOSURE_FIELDS,
    GEOMETRY_FIELDS,
    GLOBAL_FIELDS,
    GUIDED_BASE_GROUPS,
    GUIDED_FIELD_GROUPS,
    GUIDED_MANAGED_KEYS,
    GUIDED_RULES,
    GUIDED_SANITIZE_RESET_VALUES,
    GRID_EXPORT_FIELDS,
    GUIDING_CURVE_FIELDS,
    HORN_SAMPLE_VALUES,
    LE_FIELDS,
    MORPH_FIELDS,
    MESH_FIELDS,
    OUTPUT_FIELDS,
    POLAR_FIELDS,
    REPORT_FIELDS,
    ROLLBACK_FIELDS,
    SIMPLE_FIELD_SPECS,
    SOURCE_FIELDS,
    FieldSpec,
)


def strip_comment(line: str) -> str:
    out: list[str] = []
    in_quotes = False
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
        if char == ";" and not in_quotes:
            break
        out.append(char)
    return "".join(out)


def count_brace_delta(text: str) -> int:
    delta = 0
    in_quotes = False
    for char in text:
        if char == '"':
            in_quotes = not in_quotes
        elif not in_quotes and char == "{":
            delta += 1
        elif not in_quotes and char == "}":
            delta -= 1
    return delta


def unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text


def quote_value(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    if text.startswith('"') and text.endswith('"'):
        return text
    return f'"{text}"'


def is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_simple_block(lines: list[str]) -> dict[str, str] | None:
    block: dict[str, str] = {}
    for raw in lines:
        cleaned = strip_comment(raw).strip()
        if not cleaned:
            continue
        if "{" in cleaned or "}" in cleaned:
            return None
        if "=" not in cleaned:
            return None
        key, value = cleaned.split("=", 1)
        block[key.strip()] = value.strip()
    return block


def parse_top_level_items(text: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw_line = lines[i]
        cleaned = strip_comment(raw_line).strip()
        if not cleaned:
            i += 1
            continue
        if "=" not in cleaned:
            items.append({"type": "raw", "raw": raw_line})
            i += 1
            continue
        key, value = cleaned.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("{"):
            raw_lines = [raw_line]
            if count_brace_delta(value) == 0:
                body_text = value[1:-1].strip()
                body_lines = [body_text] if body_text else []
                items.append({"type": "block", "key": key, "body_lines": body_lines, "raw": raw_line})
                i += 1
                continue

            brace_balance = count_brace_delta(value)
            i += 1
            while i < len(lines) and brace_balance > 0:
                current = lines[i]
                raw_lines.append(current)
                brace_balance += count_brace_delta(strip_comment(current))
                i += 1
            items.append(
                {
                    "type": "block",
                    "key": key,
                    "body_lines": raw_lines[1:-1],
                    "raw": "\n".join(raw_lines),
                }
            )
            continue
        items.append({"type": "scalar", "key": key, "value": value, "raw": raw_line})
        i += 1
    return items


def default_global_state() -> dict[str, object]:
    return {spec.key: spec.default for spec in GLOBAL_FIELDS} | {"GLOBAL.Extras": ""}


def default_horn_state() -> dict[str, object]:
    state = {
        spec.key: spec.default
        for spec in (
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
    state.update(HORN_SAMPLE_VALUES)
    return state


def _guided_group_keys(group_names: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    keys: list[str] = []
    for group_name in group_names:
        keys.extend(GUIDED_FIELD_GROUPS.get(group_name, ()))
    return tuple(dict.fromkeys(keys))


def _state_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return is_truthy(str(value))


def _apply_guided_rule_case(
    field_states: dict[str, dict[str, object]],
    rule_cases: dict[str, dict[str, object]],
    case_key: str,
) -> None:
    case = rule_cases.get(case_key, rule_cases.get("__default__", {}))
    relevant_groups = tuple(case.get("relevant_groups", ()))
    inactive_groups = dict(case.get("inactive_groups", {}))

    for key in _guided_group_keys(relevant_groups):
        state = field_states.setdefault(key, {"relevant": True, "reason": ""})
        state["relevant"] = True
        state["reason"] = ""

    for group_name, reason in inactive_groups.items():
        for key in _guided_group_keys([group_name]):
            state = field_states.setdefault(key, {"relevant": True, "reason": ""})
            state["relevant"] = False
            state["reason"] = str(reason).strip()


def build_guided_field_states(state: dict[str, object] | None = None) -> dict[str, dict[str, object]]:
    """Evaluate which horn fields are currently relevant under Guided Setup rules."""

    current = default_horn_state()
    if state:
        current.update(state)

    field_states = {
        key: {"relevant": False, "reason": ""}
        for key in GUIDED_MANAGED_KEYS
    }
    for key in _guided_group_keys(GUIDED_BASE_GROUPS):
        field_states[key] = {"relevant": True, "reason": ""}

    throat_profile = str(current.get("Throat.Profile", "")).strip()
    _apply_guided_rule_case(field_states, GUIDED_RULES["Throat.Profile"], throat_profile)

    if throat_profile == "1":
        gcurve_type = str(current.get("GCurve.Type", "")).strip()
        _apply_guided_rule_case(field_states, GUIDED_RULES["GCurve.Type"], gcurve_type)
    else:
        _apply_guided_rule_case(field_states, GUIDED_RULES["GCurve.Type"], "__inactive__")

    morph_target_shape = str(current.get("Morph.TargetShape", "")).strip()
    _apply_guided_rule_case(field_states, GUIDED_RULES["Morph.TargetShape"], morph_target_shape)

    sim_type = str(current.get("ABEC.SimType", "")).strip()
    _apply_guided_rule_case(field_states, GUIDED_RULES["ABEC.SimType"], sim_type)

    if sim_type == "2":
        rollback_case = "1" if _state_truthy(current.get("Rollback", False)) else "__default__"
        _apply_guided_rule_case(field_states, GUIDED_RULES["Rollback"], rollback_case)
    else:
        _apply_guided_rule_case(field_states, GUIDED_RULES["Rollback"], "__inactive__")

    return field_states


def sanitize_state_by_rules(state: dict[str, object]) -> dict[str, object]:
    """Keep raw UI state intact, but neutralize irrelevant branches for save/run/render."""

    sanitized = default_horn_state()
    sanitized.update(state)

    for key, field_state in build_guided_field_states(sanitized).items():
        if bool(field_state.get("relevant", True)):
            continue
        if key in GUIDED_SANITIZE_RESET_VALUES:
            sanitized[key] = GUIDED_SANITIZE_RESET_VALUES[key]
            continue
        spec = SIMPLE_FIELD_SPECS.get(key)
        if spec is not None and spec.kind == "check":
            sanitized[key] = False
        else:
            sanitized[key] = ""

    return sanitized


def sanitize_ath_state(state: dict[str, object]) -> dict[str, object]:
    """Explicit ATH-side sanitize entry point used before save/preview/run."""

    return sanitize_state_by_rules(state)


def normalize_branch_locked_horn_state(state: dict[str, object]) -> dict[str, object]:
    """Drop or neutralize values that belong to inactive parameter branches.

    This mirrors GUI dependency locking semantics so disabled branches do not
    accidentally leak stale values into rendered cfg output.
    """
    return sanitize_ath_state(state)


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def normalize_inline_block(text: str, assignment_key: str) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    if not lines:
        return ""
    first = strip_comment(lines[0]).strip()
    if first == "{":
        lines = lines[1:]
        if lines and strip_comment(lines[-1]).strip() == "}":
            lines = lines[:-1]
    elif first.startswith(f"{assignment_key} ="):
        remainder = first.split("=", 1)[1].strip()
        if remainder == "{":
            lines = lines[1:]
            if lines and strip_comment(lines[-1]).strip() == "}":
                lines = lines[:-1]
        else:
            return remainder
    return "\n".join(lines).strip()


def load_global_state(text: str) -> dict[str, object]:
    state = default_global_state()
    extras: list[str] = []
    for item in parse_top_level_items(text):
        if item["type"] != "scalar":
            raw = str(item["raw"]).rstrip()
            if raw:
                extras.append(raw)
            continue
        key = str(item["key"])
        value = str(item["value"])
        spec = SIMPLE_FIELD_SPECS.get(key)
        if spec is None:
            extras.append(str(item["raw"]).rstrip())
            continue
        if spec.kind == "check":
            state[key] = is_truthy(value)
        elif spec.quote:
            state[key] = unquote(value)
        else:
            state[key] = value.strip()
    state["GLOBAL.Extras"] = "\n".join(line for line in extras if line).strip()
    return state


def load_horn_state(text: str) -> dict[str, object]:
    state = default_horn_state()
    extras: list[str] = []
    polar_loaded = False
    grid_loaded = False

    for item in parse_top_level_items(text):
        item_type = str(item["type"])
        if item_type == "raw":
            raw = str(item["raw"]).rstrip()
            if raw:
                extras.append(raw)
            continue

        key = str(item["key"])
        if item_type == "scalar":
            value = str(item["value"])
            spec = SIMPLE_FIELD_SPECS.get(key)
            if spec is None:
                extras.append(str(item["raw"]).rstrip())
                continue
            if spec.kind == "check":
                state[key] = is_truthy(value)
            elif spec.quote:
                state[key] = unquote(value)
            else:
                state[key] = value.strip()
            continue

        body_lines = [line.rstrip() for line in item["body_lines"]]
        if key == "Source.Contours":
            state["SOURCE.Contours"] = "\n".join(body_lines).strip()
            continue
        if key == "Mesh.Enclosure":
            parsed = parse_simple_block(body_lines)
            if parsed is None or "Plan" in parsed:
                extras.append(str(item["raw"]).rstrip())
                continue
            enclosure_ok = True
            for subkey, value in parsed.items():
                target = f"ENCLOSURE.{subkey}"
                spec = SIMPLE_FIELD_SPECS.get(target)
                if spec is None:
                    enclosure_ok = False
                    break
                state[target] = unquote(value) if spec.quote else value.strip()
            if not enclosure_ok:
                extras.append(str(item["raw"]).rstrip())
            continue
        if key.startswith("ABEC.Polars:"):
            if polar_loaded:
                extras.append(str(item["raw"]).rstrip())
                continue
            parsed = parse_simple_block(body_lines)
            if parsed is None:
                extras.append(str(item["raw"]).rstrip())
                continue
            polar_loaded = True
            state["POLAR.Tag"] = key.split(":", 1)[1]
            for subkey, value in parsed.items():
                target = f"POLAR.{subkey}"
                if target in SIMPLE_FIELD_SPECS:
                    state[target] = unquote(value) if SIMPLE_FIELD_SPECS[target].quote else value.strip()
            continue
        if key.startswith("GridExport:"):
            if grid_loaded:
                extras.append(str(item["raw"]).rstrip())
                continue
            parsed = parse_simple_block(body_lines)
            if parsed is None:
                extras.append(str(item["raw"]).rstrip())
                continue
            grid_loaded = True
            state["GRID.Tag"] = key.split(":", 1)[1]
            for subkey, value in parsed.items():
                target = f"GRID.{subkey}"
                spec = SIMPLE_FIELD_SPECS.get(target)
                if spec is None:
                    continue
                state[target] = is_truthy(value) if spec.kind == "check" else (unquote(value) if spec.quote else value.strip())
            continue
        if key == "Report":
            parsed = parse_simple_block(body_lines)
            if parsed is None:
                extras.append(str(item["raw"]).rstrip())
                continue
            for subkey, value in parsed.items():
                target = f"REPORT.{subkey}"
                spec = SIMPLE_FIELD_SPECS.get(target)
                if spec is None:
                    continue
                state[target] = unquote(value) if spec.quote else value.strip()
            continue

        extras.append(str(item["raw"]).rstrip())

    state["ADVANCED.Raw"] = "\n\n".join(block for block in extras if block).strip()
    return state


def render_scalar(key: str, value: object, spec: FieldSpec) -> str | None:
    if spec.kind == "check":
        if not spec.emit_default and bool(value) == bool(spec.default):
            return None
        return f"{key} = {'1' if bool(value) else '0'}"

    text = str(value).strip()
    default_text = str(spec.default).strip()
    if not text:
        return None
    if not spec.emit_default and text == default_text and key not in {"Length", "Throat.Diameter", "Coverage.Angle"}:
        return None
    rendered = quote_value(text) if spec.quote else text
    return f"{key} = {rendered}"


def render_block(key: str, lines: list[str]) -> list[str]:
    body = [line.rstrip() for line in lines if line.strip()]
    if not body:
        return []
    return [f"{key} = {{", *[f"  {line}" for line in body], "}"]


def render_global_text(state: dict[str, object]) -> str:
    lines: list[str] = ["; Generated by ATH Config Studio", ""]
    for spec in GLOBAL_FIELDS:
        rendered = render_scalar(spec.key, state.get(spec.key, spec.default), spec)
        if rendered:
            lines.append(rendered)
    extras = str(state.get("GLOBAL.Extras", "")).strip()
    if extras:
        lines.extend(["", extras])
    return "\n".join(lines).strip() + "\n"


def render_horn_text(state: dict[str, object]) -> str:
    sections: list[tuple[str, list[str]]] = []

    def emit_group(title: str, specs: tuple[FieldSpec, ...]) -> None:
        group_lines: list[str] = []
        for spec in specs:
            if spec.kind == "multiline":
                continue
            rendered = render_scalar(spec.key, state.get(spec.key, spec.default), spec)
            if rendered:
                group_lines.append(rendered)
        if group_lines:
            sections.append((title, group_lines))

    emit_group("Geometry", GEOMETRY_FIELDS)
    emit_group("Guiding Curve", GUIDING_CURVE_FIELDS)
    emit_group("Morph", MORPH_FIELDS)
    emit_group("Rollback", ROLLBACK_FIELDS)
    emit_group("Mesh", MESH_FIELDS)

    enclosure_body: list[str] = []
    for spec in ENCLOSURE_FIELDS:
        rendered = render_scalar(spec.key.removeprefix("ENCLOSURE."), state.get(spec.key, spec.default), spec)
        if rendered:
            enclosure_body.append(rendered)
    enclosure_block = render_block("Mesh.Enclosure", enclosure_body)
    if enclosure_block:
        sections.append(("Enclosure", enclosure_block))

    emit_group("ABEC", ABEC_FIELDS)
    emit_group("Source", tuple(spec for spec in SOURCE_FIELDS if spec.key != "SOURCE.Contours"))

    source_contours = str(state.get("SOURCE.Contours", "")).strip()
    if source_contours:
        if "\n" in source_contours:
            cleaned = normalize_inline_block(source_contours, "Source.Contours")
            sections.append(("Source Contours", render_block("Source.Contours", cleaned.splitlines())))
        else:
            sections.append(("Source Contours", [f"Source.Contours = {source_contours}"]))

    emit_group("LE Model", LE_FIELDS)
    emit_group("Output", OUTPUT_FIELDS)

    polar_body: list[str] = []
    polar_tag = str(state.get("POLAR.Tag", "SPL")).strip() or "SPL"
    for spec in POLAR_FIELDS:
        if spec.key == "POLAR.Tag":
            continue
        rendered = render_scalar(spec.key.removeprefix("POLAR."), state.get(spec.key, spec.default), spec)
        if rendered:
            polar_body.append(rendered)
    polar_block = render_block(f"ABEC.Polars:{polar_tag}", polar_body)
    if polar_block:
        sections.append(("Polar Map", polar_block))

    grid_body: list[str] = []
    grid_tag = str(state.get("GRID.Tag", "")).strip()
    for spec in GRID_EXPORT_FIELDS:
        if spec.key == "GRID.Tag":
            continue
        rendered = render_scalar(spec.key.removeprefix("GRID."), state.get(spec.key, spec.default), spec)
        if rendered:
            grid_body.append(rendered)
    if grid_tag and grid_body:
        sections.append(("Grid Export", render_block(f"GridExport:{grid_tag}", grid_body)))

    report_body: list[str] = []
    for spec in REPORT_FIELDS:
        rendered = render_scalar(spec.key.removeprefix("REPORT."), state.get(spec.key, spec.default), spec)
        if rendered:
            report_body.append(rendered)
    report_block = render_block("Report", report_body)
    if report_block:
        sections.append(("Report", report_block))

    lines: list[str] = ["; Generated by ATH Config Studio", "; Manual reference: Ath 4.8.2 User Guide, Chapter 4"]
    for title, section_lines in sections:
        lines.extend(["", f"; {title}", *section_lines])

    advanced = str(state.get("ADVANCED.Raw", "")).strip()
    if advanced:
        lines.extend(["", "; Advanced / Preserved Blocks", advanced])

    return "\n".join(lines).strip() + "\n"


def build_field_hint(spec: FieldSpec) -> str:
    parts: list[str] = []
    if spec.choice_notes:
        parts.append(" | ".join(f"{value} = {label}" for value, label in spec.choice_notes))
    if spec.hint:
        parts.append(spec.hint)
    return "\n".join(parts).strip()
