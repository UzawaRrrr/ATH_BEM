from __future__ import annotations

from ._pathing import ensure_app_root_on_path


ensure_app_root_on_path()

from ath_gui import main as _gui_main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    return int(_gui_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())

