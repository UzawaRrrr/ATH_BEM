from __future__ import annotations

from .cli import main as _optimizer_main


def main(argv: list[str] | None = None) -> int:
    return int(_optimizer_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())

