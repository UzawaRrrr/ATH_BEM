from __future__ import annotations

import sys

from ath_gui.app import AthConfigStudio, main
from ath_gui.config_core import *  # noqa: F401,F403
from ath_gui.preview_core import *  # noqa: F401,F403
from ath_gui.self_test import run_self_test
from ath_gui.specs import *  # noqa: F401,F403
from ath_gui.widgets import ScrollableFrame


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
