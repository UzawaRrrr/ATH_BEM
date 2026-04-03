from __future__ import annotations

from ._pathing import ensure_app_root_on_path


ensure_app_root_on_path()

from optimizer.cli import main as _optimizer_main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    return int(_optimizer_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())

