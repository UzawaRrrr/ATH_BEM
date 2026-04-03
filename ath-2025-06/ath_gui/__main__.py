from __future__ import annotations

from . import main as _gui_main


def main(argv: list[str] | None = None) -> int:
    return int(_gui_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())

