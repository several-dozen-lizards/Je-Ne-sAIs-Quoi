"""Voice output policy and append-only playback receipts.

The speaking vessel owns synthesis.  This module only projects the body's
current continuous state into provider-neutral expression controls and records
what the vessel actually did.  It never tells the persona what to feel.
"""
from __future__ import annotations

import json
import os
import time
from typing import Mapping


OUTPUT_EVENTS = frozenset({"started", "completed", "interrupted", "failed"})
OUTPUT_PROVIDERS = frozenset({"disabled", "browser-native"})


def normalize_output_config(value: Mapping | None) -> dict:
    """Return the portable, provider-neutral voice selection.

    Unknown providers fail quiet instead of silently sending speech through a
    different vessel.  ``voice`` is a provider-owned identifier; blank means
    that provider's default voice.
    """
    raw = dict(value or {})
    provider = str(raw.get("provider") or "browser-native").strip()
    if provider not in OUTPUT_PROVIDERS:
        provider = "disabled"
    voice = str(raw.get("voice") or "").strip()
    if len(voice) > 160 or any(char in voice for char in "\r\n"):
        voice = ""
    return {"provider": provider, "voice": voice}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def expression_policy(bands: Mapping | None, cocktail: Mapping | None,
                      coherence: float = 1.0) -> dict:
    """Project the whole live state into gentle synthesis controls.

    The ranges are capability bounds, not emotional labels or fixed band
    presets.  Every oscillator band can influence every subsequent utterance.
    """
    b = dict(bands or {})
    c = dict(cocktail or {})
    coh = _clamp(coherence if coherence is not None else 1.0, 0.0, 1.0)

    energy = _clamp(
        .44 * float(b.get("beta", 0.0))
        + .68 * float(b.get("gamma", 0.0))
        + .22 * float(c.get("curiosity", 0.0))
        + .16 * float(c.get("clarity", 0.0)), 0.0, 1.0)
    settling = _clamp(
        .46 * float(b.get("alpha", 0.0))
        + .38 * float(b.get("theta", 0.0))
        + .24 * float(b.get("delta", 0.0))
        + .22 * coh, 0.0, 1.0)
    warmth = _clamp(
        .45 * float(c.get("warmth", 0.0))
        + .35 * float(c.get("tenderness", 0.0))
        + .20 * float(c.get("joy", 0.0)), 0.0, 1.0)
    tension = _clamp(
        .50 * float(c.get("unease", 0.0))
        + .28 * float(c.get("fear", 0.0))
        + .22 * float(c.get("vulnerability", 0.0)), 0.0, 1.0)

    return {
        "rate": round(_clamp(.96 + .30 * energy - .18 * settling
                             + .06 * tension, .72, 1.30), 4),
        "pitch": round(_clamp(.98
                              + .14 * (float(b.get("gamma", 0.0))
                                       - float(b.get("delta", 0.0)))
                              + .07 * warmth - .05 * tension,
                              .82, 1.18), 4),
        "volume": round(_clamp(.70 + .20 * coh + .10 * energy,
                               .58, 1.0), 4),
        "vector": {
            "energy": round(energy, 4),
            "settling": round(settling, 4),
            "warmth": round(warmth, 4),
            "tension": round(tension, 4),
            "coherence": round(coh, 4),
        },
    }


def append_output_receipt(persona_dir: str, event: Mapping) -> dict:
    """Validate and append one local output event; return the stored record."""
    kind = str(event.get("event") or "")
    if kind not in OUTPUT_EVENTS:
        raise ValueError(f"unknown voice output event: {kind or '<empty>'}")
    record = {
        "tick": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": kind,
        "provider": str(event.get("provider") or "unknown")[:80],
        "reason": str(event.get("reason") or "")[:240],
        "policy": dict(event.get("policy") or {}),
        "evidence": dict(event.get("evidence") or {}),
    }
    history = os.path.join(persona_dir, "history")
    os.makedirs(history, exist_ok=True)
    path = os.path.join(history, "voice_output.jsonl")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
