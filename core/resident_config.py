"""Household-wide resident configuration inheritance.

The roster remains the canonical resident record.  Shared defaults supply
capability wiring that should not have to be copied into every resident, and a
private household overlay may narrow those defaults for one installation.

Inheritance is one-way and descriptive::

    specs/resident_defaults.yaml
      -> shell/household_resident_overrides.yaml (optional, private)
      -> personas/<id>/roster.yaml

Mappings merge recursively.  Lists, scalars, and explicit ``null`` values
replace the inherited value, so a resident can always diverge deliberately.
"""
from __future__ import annotations

from copy import deepcopy
import os
from typing import Any, Mapping

import yaml


DEFAULTS_RELATIVE_PATH = os.path.join("specs", "resident_defaults.yaml")
HOUSEHOLD_RELATIVE_PATH = os.path.join(
    "shell", "household_resident_overrides.yaml")


def deep_merge(base: Mapping[str, Any] | None,
               overlay: Mapping[str, Any] | None) -> dict:
    """Return a deep copy with ``overlay`` taking precedence.

    Only mappings combine.  Everything else is a complete choice by the more
    specific layer; this makes ``null`` a meaningful, fail-closed override.
    """
    out = deepcopy(dict(base or {}))
    for key, value in dict(overlay or {}).items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _load_mapping(path: str, *, optional: bool) -> dict:
    if not os.path.exists(path):
        if optional:
            return {}
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"resident configuration must be a mapping: {path}")
    return value


def resolve_resident_config(repo: str, roster: Mapping[str, Any] | None,
                            *, require_defaults: bool = False) -> dict:
    """Resolve effective configuration for any current or future resident.

    ``require_defaults`` is useful for installation/audit checks.  Runtime
    callers leave it false so isolated tests and legacy fixture repositories
    without a shared-default file keep working.
    """
    defaults = _load_mapping(
        os.path.join(repo, DEFAULTS_RELATIVE_PATH),
        optional=not require_defaults)
    household = _load_mapping(
        os.path.join(repo, HOUSEHOLD_RELATIVE_PATH), optional=True)
    return deep_merge(deep_merge(defaults, household), roster or {})
