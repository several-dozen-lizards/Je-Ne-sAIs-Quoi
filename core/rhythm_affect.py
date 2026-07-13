"""rhythm_affect — the LAST arc of the circle (circulatory cut 4).
Rhythm presses back into emotion: a band the body has INHABITED (dwell-gated,
not merely visited) gently seeds its feeling-tone into the cocktail.

This is the one coupling with runaway potential (sad -> theta -> sadder),
so the damping is the design:
  1. DWELL GATE  — no nudge until dominance has lasted DWELL_GATE_S.
  2. TINY NUDGE  — NUDGE per turn. The rhythm whispers.
  3. HARD CAP    — this path alone can never push a feeling past CAP.
                   The body can make you wistful, not despairing.
  4. DECAY WINS  — the cocktail's own per-turn decay (x0.8) opposes the
                   nudge every turn; the closed loop has a fixed point
                   far below CAP (proven by the spiral probe in
                   harness/run_rhythm_affect.py, 50 round trips).
Pure function, declarative map, NO organ imports — the contract composes."""

DWELL_GATE_S = 600.0      # inhabit a band 10 min before it colors feeling
NUDGE = 0.03              # per-turn seed size
CAP = 0.35                # ceiling for rhythm-seeded intensity

BAND_FEELING = {
    "delta": "heaviness",
    "theta": "melancholy",
    "alpha": "calm",
    "beta": "restlessness",
    "gamma": "intensity",
}


def rhythm_affect_nudge(cocktail: dict, dominant_band: str,
                        dwell_seconds: float) -> dict:
    """Return a NEW cocktail with the dwell-gated, capped nudge applied.
    Never mutates. Returns the input copied unchanged if gate not met."""
    out = dict(cocktail or {})
    if dwell_seconds < DWELL_GATE_S:
        return out
    feeling = BAND_FEELING.get(dominant_band)
    if not feeling:
        return out
    current = out.get(feeling, 0.0)
    if current >= CAP:
        return out
    out[feeling] = round(min(CAP, current + NUDGE), 3)
    return out
