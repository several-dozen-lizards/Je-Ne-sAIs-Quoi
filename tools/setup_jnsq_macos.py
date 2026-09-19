"""Compatibility import for the former setup module name."""
from tools.setup_jnaiq_macos import *  # noqa: F401,F403
from tools.setup_jnaiq_macos import main


if __name__ == "__main__":
    raise SystemExit(main())
