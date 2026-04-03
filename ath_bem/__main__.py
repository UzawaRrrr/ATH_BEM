from __future__ import annotations

import sys


_HELP_TEXT = """usage: python -m ath_bem <command> [args]

commands:
  gui         Launch the ATH GUI.
  optimizer   Run the Optuna optimizer CLI.
  doctor      Run doctor/check commands.
"""


def main(argv: list[str] | None = None) -> int:
    forwarded = list(sys.argv[1:] if argv is None else argv)
    if not forwarded or forwarded[0] in {"-h", "--help", "help"}:
        print(_HELP_TEXT)
        return 0 if forwarded else 1

    command = forwarded.pop(0)
    if command == "gui":
        from .gui import main as gui_main

        return int(gui_main(forwarded))
    if command == "optimizer":
        from .optimizer import main as optimizer_main

        return int(optimizer_main(forwarded))
    if command == "doctor":
        from .doctor import main as doctor_main

        return int(doctor_main(forwarded))

    print(_HELP_TEXT)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
