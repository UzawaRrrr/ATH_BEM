from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PACKAGE_NAME = "ath_gui"
LAYER_NAMES = ("domain", "infrastructure", "presentation", "application")
COMPOSITION_MODULES = {"app", "self_test", "tools", "__init__"}
ROOT_DIR = Path(__file__).resolve().parents[2]
PACKAGE_DIR = ROOT_DIR / PACKAGE_NAME


@dataclass(frozen=True)
class LayerIssue:
    """A single import-layer violation."""

    file: Path
    line: int
    source_module: str
    source_layer: str
    target_module: str
    target_layer: str
    message: str


@dataclass(frozen=True)
class LayerCheckResult:
    """Result payload for architecture-layer checks."""

    issues: tuple[LayerIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def _iter_python_files(base_dir: Path) -> Iterable[Path]:
    for path in base_dir.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _module_from_path(path: Path) -> str:
    rel = path.relative_to(ROOT_DIR).with_suffix("")
    return ".".join(rel.parts)


def _classify_module_layer(module: str) -> str:
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != PACKAGE_NAME:
        return "external"
    head = parts[1]
    if head in LAYER_NAMES:
        return head
    if head == "controllers":
        return "shim"
    if head in COMPOSITION_MODULES:
        return "composition"
    return "legacy_root"


def _allowed_dependencies(source_layer: str) -> set[str]:
    allowed: dict[str, set[str]] = {
        "domain": {"domain"},
        "infrastructure": {"domain", "infrastructure"},
        "presentation": {"domain", "presentation"},
        # application controllers coordinate UI+infrastructure flows.
        "application": {"domain", "infrastructure", "presentation", "application"},
        "composition": {"domain", "infrastructure", "presentation", "application", "composition", "shim", "legacy_root"},
        # legacy shims should only forward to true layers.
        "shim": {"domain", "infrastructure", "presentation", "application"},
        "legacy_root": {"domain", "infrastructure", "presentation", "application"},
    }
    return allowed.get(source_layer, set())


def _resolve_from_import(current_module: str, level: int, module: str | None) -> str | None:
    if level == 0:
        return module

    package_parts = current_module.split(".")[:-1]
    if level - 1 > len(package_parts):
        return None
    anchor = package_parts[: len(package_parts) - (level - 1)]
    if module:
        return ".".join(anchor + module.split("."))
    return ".".join(anchor)


def _collect_import_modules(tree: ast.AST, current_module: str) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_from_import(current_module, node.level, node.module)
            if resolved:
                imports.append((node.lineno, resolved))
    return imports


def check_layering(base_dir: Path | None = None) -> LayerCheckResult:
    """Check ath_gui layer import boundaries.

    Returns all violations found under `base_dir` (defaults to ath_gui package dir).
    """

    scan_dir = base_dir or PACKAGE_DIR
    issues: list[LayerIssue] = []

    for file_path in _iter_python_files(scan_dir):
        module_name = _module_from_path(file_path)
        source_layer = _classify_module_layer(module_name)
        if source_layer == "external":
            continue
        allowed = _allowed_dependencies(source_layer)
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        except SyntaxError as exc:
            issues.append(
                LayerIssue(
                    file=file_path,
                    line=max(1, int(exc.lineno or 1)),
                    source_module=module_name,
                    source_layer=source_layer,
                    target_module="<syntax-error>",
                    target_layer="invalid",
                    message=f"Syntax error: {exc.msg}",
                )
            )
            continue

        for line, imported_module in _collect_import_modules(tree, module_name):
            if not imported_module.startswith(f"{PACKAGE_NAME}."):
                continue
            target_layer = _classify_module_layer(imported_module)
            if target_layer == "composition":
                # Importing top-level runtime entrypoints from lower layers creates cycles.
                if source_layer in {"domain", "infrastructure", "presentation", "application"}:
                    issues.append(
                        LayerIssue(
                            file=file_path,
                            line=line,
                            source_module=module_name,
                            source_layer=source_layer,
                            target_module=imported_module,
                            target_layer=target_layer,
                            message="Layer module must not depend on composition entrypoints.",
                        )
                    )
                continue
            if target_layer not in allowed:
                issues.append(
                    LayerIssue(
                        file=file_path,
                        line=line,
                        source_module=module_name,
                        source_layer=source_layer,
                        target_module=imported_module,
                        target_layer=target_layer,
                        message=f"`{source_layer}` layer cannot import `{target_layer}` module.",
                    )
                )

    return LayerCheckResult(issues=tuple(sorted(issues, key=lambda item: (str(item.file), item.line))))


def format_layering_report(result: LayerCheckResult) -> str:
    """Format layer-check result for CLI/log output."""

    if result.ok:
        return "Layer check passed: no import-boundary violations found."

    lines = [f"Layer check failed: {len(result.issues)} violation(s)."]
    for issue in result.issues:
        lines.append(
            f"- {issue.file.relative_to(ROOT_DIR)}:{issue.line} "
            f"[{issue.source_layer} -> {issue.target_layer}] {issue.message} "
            f"(import: {issue.target_module})"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    result = check_layering()
    print(format_layering_report(result))
    raise SystemExit(0 if result.ok else 1)
