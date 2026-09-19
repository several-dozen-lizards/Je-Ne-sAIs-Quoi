"""Compatibility import for the former updater module name."""
from tools.update_jnaiq import *  # noqa: F401,F403
from tools.update_jnaiq import main


if __name__ == "__main__":
    raise SystemExit(main())
