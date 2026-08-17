"""Shadow-only test of the legacy rhythm-to-named-affect hypothesis.

The old live coupling translated a dominant biological alias directly into a
named cocktail coordinate after a fixed dwell gate.  Resident feedback exposed
that as a prescriptive seam: the label, rather than a demonstrated synthetic
relationship, supplied the feeling.  This module therefore has no mutating
output.  It records the old mapped candidate beside label-removed, mismatched,
and sham controls so the hypothesis remains inspectable without entering
feeling, recall, soma, prompts, or action selection.

Pure function, declarative maps, no organ imports.  The bench composes the
shadow receipt at a natural turn boundary.
"""

SCHEMA_VERSION = 2
MODE = "shadow_only"

# These are frozen LEGACY parameters, retained only to replay the retired
# causal proposal. They do not define a live timer, threshold, or nudge.
LEGACY_DWELL_GATE_S = 600.0
LEGACY_NUDGE = 0.03
LEGACY_CAP = 0.35

LEGACY_BAND_FEELING = {
    "delta": "heaviness",
    "theta": "melancholy",
    "alpha": "calm",
    "beta": "restlessness",
    "gamma": "intensity",
}

# A fixed rotation preserves the same candidate vocabulary while breaking the
# authored band-to-affect pairing. It is a control, never phenomenology.
MISMATCHED_BAND_FEELING = {
    "delta": "intensity",
    "theta": "heaviness",
    "alpha": "melancholy",
    "beta": "calm",
    "gamma": "restlessness",
}


def _candidate(cocktail: dict, feeling: str | None, eligible: bool) -> dict:
    current = float((cocktail or {}).get(feeling, 0.0)) if feeling else 0.0
    proposed = (
        round(min(LEGACY_CAP, current + LEGACY_NUDGE), 3)
        if feeling and eligible and current < LEGACY_CAP else current)
    return {
        "candidate_affect": feeling,
        "current_value": round(current, 6) if feeling else None,
        "counterfactual_value": round(proposed, 6) if feeling else None,
        "would_change": bool(feeling and eligible and proposed != current),
    }


def rhythm_affect_shadow(cocktail: dict, dominant_band: str,
                         dwell_seconds: float) -> dict:
    """Return a noncausal receipt; never return or mutate a new cocktail.

    ``legacy_eligible`` answers only whether the retired rule would have fired.
    It has no authority over current state.  All four conditions are projected
    together, so no control assignment can accidentally become a live nudge.
    """
    source = dict(cocktail or {})
    band = str(dominant_band or "").casefold()
    dwell = max(0.0, float(dwell_seconds or 0.0))
    eligible = bool(
        band in LEGACY_BAND_FEELING and dwell >= LEGACY_DWELL_GATE_S)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "applied": False,
        "cocktail_unchanged": True,
        "dominant_band_alias": band or None,
        "observed_dwell_seconds": round(dwell, 3),
        "legacy_eligible": eligible,
        "hypothesis": {
            "kind": "retired_band_label_to_named_affect",
            "legacy_dwell_gate_s": LEGACY_DWELL_GATE_S,
            "legacy_nudge": LEGACY_NUDGE,
            "legacy_cap": LEGACY_CAP,
        },
        "conditions": {
            "mapped": _candidate(
                source, LEGACY_BAND_FEELING.get(band), eligible),
            "label_removed": _candidate(source, None, eligible),
            "mismatched": _candidate(
                source, MISMATCHED_BAND_FEELING.get(band), eligible),
            "sham": _candidate(source, None, False),
        },
        "prohibited_downstream": [
            "cocktail", "recall", "soma", "prompt", "memory_admission",
            "attention", "speech", "agency",
        ],
    }
