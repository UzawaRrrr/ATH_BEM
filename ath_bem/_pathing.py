from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = REPO_ROOT / "ath-2025-06"


def ensure_app_root_on_path() -> Path:
    """Expose the source-tree app root for repo-root launch wrappers.

    The application code intentionally stays under `ath-2025-06/` so the repo
    remains a source checkout rather than an installed package. We keep the
    path tweak here, once, so launch entrypoints stay consistent.
    """
    app_root_text = str(APP_ROOT)
    if app_root_text not in sys.path:
        sys.path.insert(0, app_root_text)
    return APP_ROOT

