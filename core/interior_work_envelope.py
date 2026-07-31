"""Readiness- and resource-shaped authority for same-owner interior work.

The envelope is not an approval gate.  A field win already supplies authority
for private, reversible work.  This module only answers how much work remains
prudent inside that admission, using the capacity already present and the
measured size of each movement.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping


def _unit(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    if not math.isfinite(number):
        number = fallback
    return max(0.0, min(1.0, number))


def movement_weight(movement: Mapping[str, Any],
                    *, response_floor_tokens: int = 128) -> float:
    """Approximate a movement's share of a minimally useful model response."""
    rendered = json.dumps(
        dict(movement), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"))
    approximate_tokens = max(1.0, len(rendered.encode("utf-8")) / 4.0)
    return max(1.0, approximate_tokens / max(1, response_floor_tokens))


@dataclass
class InteriorWorkEnvelope:
    """Consumable work mass derived from readiness and the configured window."""

    available: float
    spent: float = 0.0

    @classmethod
    def from_readiness(cls, readiness: Mapping[str, Any], *,
                       response_tokens: int,
                       response_floor_tokens: int = 128):
        state = dict(readiness or {})
        readiness_value = _unit(state.get("readiness"))
        capacity = _unit(state.get("capacity"), readiness_value)
        support = _unit(state.get("support"), readiness_value)
        # The harmonic-like blend makes a weak component matter without making
        # discrepancy dysfunction. One baseline movement belongs to the win;
        # additional room scales continuously with present support/capacity and
        # the response window already allocated to this local turn.
        carried = (readiness_value * capacity * support) ** (1.0 / 3.0)
        window = max(1.0, float(response_tokens) /
                     max(1, response_floor_tokens))
        return cls(1.0 + carried * (window - 1.0))

    def admit(self, movement: Mapping[str, Any]) -> bool:
        weight = movement_weight(movement)
        # One coherent private movement belongs to the field win even when its
        # serialized payload is larger than the approximate response floor.
        # Readiness limits continuation depth; it does not revoke the first
        # same-owner, reversible act.
        if self.spent <= 1e-9:
            self.spent = weight
            return True
        if self.spent + weight > self.available + 1e-9:
            return False
        self.spent += weight
        return True

    def status(self) -> dict:
        return {
            "available_mass": round(self.available, 6),
            "spent_mass": round(self.spent, 6),
            "remaining_mass": round(max(0.0, self.available - self.spent), 6),
        }
