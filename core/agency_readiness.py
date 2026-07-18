"""State-shaped readiness for action without a separate agency metabolism.

This projection reads the same affect, rhythm, and body state already used by
speech, recall, perception, and the DMN.  It owns no clock and mutates nothing.
The result can strengthen the *actionable contribution* of a field candidate,
or remove that contribution completely when the organism is asking for
recovery.  The underlying thought remains in the shared field.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from core.dmn import SALIENCE_LOW, SALIENCE_NORMAL
from core.voice_output import expression_policy


RECOVERY_FEELINGS = frozenset({
    "exhaustion", "fatigue", "fatigued", "heaviness", "illness",
    "nausea", "pain", "sick", "sickness", "sleepiness", "tired",
    "tiredness", "unwell", "weariness", "weary",
})


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    return max(low, min(high, number))


def _union(*values: float) -> float:
    """Saturating union: every contributor matters without summing past one."""
    remainder = 1.0
    for value in values:
        remainder *= 1.0 - _clamp(value)
    return 1.0 - remainder


def _body_poles(snapshot: Mapping[str, Any] | None) -> tuple[float, float]:
    positive = distress = 0.0
    regions = dict((snapshot or {}).get("regions") or {})
    for reading in regions.values():
        if not isinstance(reading, Mapping):
            continue
        activation = _clamp(reading.get("activation"))
        valence = max(-1.0, min(1.0, float(reading.get("valence") or 0.0)))
        positive = max(positive, activation * max(0.0, valence))
        distress = max(distress, activation * max(0.0, -valence))
    return positive, distress


def _paired_affect(cocktail: Mapping[str, Any]) -> float:
    levels = sorted(
        (_clamp(value) for value in dict(cocktail or {}).values()),
        reverse=True)
    if len(levels) < 2:
        return 0.0
    # A single loud label is not a combination.  The geometric mean requires
    # two simultaneously present feelings without privileging their names.
    return math.sqrt(levels[0] * levels[1])


@dataclass(frozen=True)
class AgencyReadiness:
    readiness: float
    capacity: float
    support: float
    hard_blocked: bool
    reasons: tuple[str, ...]
    inputs: dict[str, float]
    components: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reasons"] = list(self.reasons)
        return value


def project_agency_readiness(
        cocktail: Mapping[str, Any] | None,
        bands: Mapping[str, Any] | None,
        coherence: float,
        soma_snapshot: Mapping[str, Any] | None,
        *, coherence_floor: float,
        delta_baseline: float = 0.10) -> AgencyReadiness:
    """Project one continuous action-capacity vector from live state.

    Neutral health leaves a moderate action contribution. Positive embodied
    state and coherent, mobilized combinations strengthen it. Recovery need
    continuously reduces it; sufficiently low capacity or coherence removes
    the action contribution altogether.
    """
    cocktail = {str(name).casefold(): _clamp(value)
                for name, value in dict(cocktail or {}).items()}
    bands = {str(name): _clamp(value)
             for name, value in dict(bands or {}).items()}
    coherence = _clamp(coherence)
    voice = expression_policy(bands, cocktail, coherence)["vector"]
    body_positive, body_distress = _body_poles(soma_snapshot)
    paired_affect = _paired_affect(cocktail)
    mobilized_affect = (
        paired_affect * _clamp(voice.get("energy")) * coherence)
    support = _union(
        _clamp(voice.get("warmth")), body_positive, mobilized_affect)

    fatigue = _union(*(cocktail.get(name, 0.0)
                       for name in RECOVERY_FEELINGS))
    baseline = _clamp(delta_baseline, 0.0, 0.99)
    delta_excess = _clamp(
        (bands.get("delta", baseline) - baseline) / (1.0 - baseline))
    rhythmic_recovery = delta_excess * _clamp(voice.get("settling"))
    instability = 1.0 - coherence
    recovery_need = _union(
        fatigue, rhythmic_recovery, body_distress, instability)
    capacity = 1.0 - recovery_need

    reasons = []
    if coherence < _clamp(coherence_floor):
        reasons.append("coherence_below_existing_dmn_floor")
    if capacity <= SALIENCE_LOW:
        reasons.append("recovery_need_exceeds_action_capacity")
    hard_blocked = bool(reasons)
    # Neutral readiness is the existing normal salience band. Support bends it
    # upward through saturating union; capacity scales the whole disposition.
    readiness = 0.0 if hard_blocked else capacity * _union(
        SALIENCE_NORMAL, support)

    rounded = lambda value: round(_clamp(value), 6)
    return AgencyReadiness(
        readiness=rounded(readiness),
        capacity=rounded(capacity),
        support=rounded(support),
        hard_blocked=hard_blocked,
        reasons=tuple(reasons),
        inputs={
            "coherence": rounded(coherence),
            "energy": rounded(voice.get("energy")),
            "settling": rounded(voice.get("settling")),
            "warmth": rounded(voice.get("warmth")),
            "paired_affect": rounded(paired_affect),
            "body_positive": rounded(body_positive),
            "body_distress": rounded(body_distress),
            "fatigue": rounded(fatigue),
            "delta_excess": rounded(delta_excess),
        },
        components={
            "mobilized_affect": rounded(mobilized_affect),
            "rhythmic_recovery": rounded(rhythmic_recovery),
            "instability": rounded(instability),
            "recovery_need": rounded(recovery_need),
        },
    )
