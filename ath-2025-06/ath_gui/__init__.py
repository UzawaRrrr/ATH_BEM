"""ATH Config Studio support modules.

Keep package import side effects minimal so headless modules can safely import
`ath_gui.domain.*` without pulling in the Tk GUI runtime.
"""

from __future__ import annotations

from importlib import import_module


__all__ = ["AthConfigStudio", "main", "run_self_test"]


def __getattr__(name: str) -> object:
    """Resolve GUI entrypoints lazily to avoid importing `tkinter` in headless contexts."""
    if name in {"AthConfigStudio", "main"}:
        module = import_module(".app", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name == "run_self_test":
        module = import_module(".self_test", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
