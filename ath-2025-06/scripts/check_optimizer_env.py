"""Compatibility wrapper for the repo-root optimizer doctor entrypoint."""

from __future__ import annotations

from pathlib import Path
import sys


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    # Keep the legacy file path executable while the repo-root `ath_bem`
    # package becomes the preferred source-tree launcher.
    sys.path.insert(0, str(REPO_ROOT))

from ath_bem.doctor import main as _doctor_main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    forwarded = sys.argv[1:] if argv is None else argv
    return int(_doctor_main(["optimizer", *forwarded]))


if __name__ == "__main__":
    raise SystemExit(main())
