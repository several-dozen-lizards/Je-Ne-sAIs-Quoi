"""Household and persona voice-output tuning.

Tuning scales the continuous body-derived policy; it never replaces it with a
fixed delivery or assigns an emotional state.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


DEFAULTS = {"rate_scale": 1.0, "pitch_scale": 1.0,
            "volume_scale": 1.0}
BOUNDS = {"rate_scale": (0.65, 1.40), "pitch_scale": (0.75, 1.25),
          "volume_scale": (0.0, 1.25)}


def normalize_voice_tuning(value: Mapping | None) -> dict:
    raw = dict(value or {})
    result = {}
    for key, default in DEFAULTS.items():
        low, high = BOUNDS[key]
        try:
            number = float(raw.get(key, default))
        except (TypeError, ValueError):
            number = default
        result[key] = round(max(low, min(high, number)), 4)
    return result


def voice_defaults_path(root: str | Path) -> Path:
    return Path(root) / "voice_defaults.json"


def load_voice_defaults(root: str | Path) -> dict:
    path = voice_defaults_path(root)
    try:
        return normalize_voice_tuning(json.loads(path.read_text("utf-8")))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)


def save_voice_defaults(root: str | Path, value: Mapping | None) -> dict:
    result = normalize_voice_tuning(value)
    path = voice_defaults_path(root)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return result
