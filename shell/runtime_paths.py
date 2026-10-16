"""Canonical installation paths with read-only legacy fallbacks."""
from __future__ import annotations

import json
from pathlib import Path


RUNFILE_NAMES = ("jnaiq_running.json", "jnsq_running.json",
                 ".jnsq_running.json")


def active_runfile(root: str | Path) -> Path:
    """Return the current receipt, preferring JNAIQ but accepting old installs."""
    base = Path(root)
    for name in RUNFILE_NAMES:
        candidate = base / name
        if candidate.exists():
            return candidate
    return base / RUNFILE_NAMES[0]


def load_run_state(root: str | Path) -> dict:
    value = json.loads(active_runfile(root).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Household run receipt must be an object")
    return value
