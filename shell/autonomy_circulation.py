"""Shared organism boundary for autonomous choices and consequences.

This module owns no thread, clock, pressure field, or private mood.  It reads
the same live state used by ordinary turns and returns experienced events
through the same feel -> soma -> oscillator path.  Callers retain ownership of
their own candidates, receipts, and persistence boundaries.
"""
from __future__ import annotations

from typing import Any, Mapping

from core.agency_readiness import project_agency_readiness
from harness.model_call_receipts import model_call_scope, new_cycle_id


def readiness_from_engine(engine, field=None) -> dict[str, Any]:
    """Project continuous action capacity from the canonical live organism."""
    osc = getattr(engine, "osc", None)
    soma = getattr(engine, "soma", None)
    bands = dict(getattr(osc, "bands", {}) or {}) if osc else {}
    coherence_fn = getattr(osc, "coherence", None) if osc else None
    coherence = coherence_fn() if callable(coherence_fn) else 1.0
    snapshot_fn = getattr(soma, "snapshot", None) if soma else None
    snapshot = snapshot_fn() if callable(snapshot_fn) else {}
    params = getattr(getattr(field, "pressure", None), "p", {}) or {}
    baseline = dict(getattr(osc, "baseline", {}) or {}) if osc else {}
    return project_agency_readiness(
        getattr(engine, "cocktail", {}) or {}, bands, coherence, snapshot,
        coherence_floor=float(params.get("coherence_floor", 0.35)),
        delta_baseline=float(baseline.get("delta", 0.10))).as_dict()


def _affect_change(before: Mapping[str, Any], after: Mapping[str, Any]) -> float:
    keys = set(before or {}) | set(after or {})
    if not keys:
        return 0.0
    changes = []
    for key in keys:
        try:
            changes.append(abs(float((after or {}).get(key, 0.0))
                               - float((before or {}).get(key, 0.0))))
        except (TypeError, ValueError):
            continue
    return max(0.0, min(1.0, sum(changes) / len(changes))) \
        if changes else 0.0


def circulate_experienced_event(
        engine, event_text: str, *,
        somatic_regions: Mapping[str, Mapping[str, float]] = None,
        cycle_id: str = None, model_receipts: list = None
        ) -> dict[str, Any]:
    """Let one factual private event become felt, embodied, and rhythmic.

    The judge describes what arose; the caller never supplies a desired
    feeling.  Measured somatic input (for example locomotion distance) can
    enter as a separate region vector and remains valid when the optional feel
    organ is disabled.
    """
    event_text = str(event_text or "").strip()[:2000]
    before = dict(getattr(engine, "cocktail", {}) or {})
    delta = {"before": before, "felt": {}, "after": before,
             "why": "feel organ disabled or unavailable"}
    organ = getattr(engine, "organ", None)
    judge = getattr(engine, "judge", None)
    if organ is not None and judge is not None \
            and "feel" in getattr(engine, "enabled", set()) \
            and hasattr(organ, "feel_event"):
        with model_call_scope(
                cycle_id=cycle_id or new_cycle_id(),
                persona=getattr(engine, "persona", "unknown"),
                purpose="affect_event", sink=model_receipts):
            delta = organ.feel_event(
                event_text, judge,
                persona_name=getattr(engine, "persona", "persona"),
                pronouns=getattr(engine, "pronouns", ""))
        engine.cocktail = dict(organ.state.get("cocktail", {}))

    osc = getattr(engine, "osc", None)
    soma = getattr(engine, "soma", None)
    emotion_pressure = getattr(osc, "emotion_pressure", None)
    if callable(emotion_pressure) and delta.get("felt"):
        emotion_pressure(delta.get("felt") or {})
    if soma is not None:
        if somatic_regions and hasattr(soma, "sense_regions"):
            soma.sense_regions(dict(somatic_regions))
        soma.feel(getattr(engine, "cocktail", {}) or {})
        soma.tick()
        effects_fn = getattr(soma, "oscillator_effects", None)
        effects = effects_fn() if callable(effects_fn) else {}
        if osc is not None:
            for band, amount in effects.get("band_pressure", {}).items():
                pressure = getattr(osc, "pressure", None)
                if callable(pressure):
                    pressure(band, amount)
        save_soma = getattr(soma, "save", None)
        if callable(save_soma):
            save_soma()
    if osc is not None:
        tick_osc = getattr(osc, "tick", None)
        save_osc = getattr(osc, "save", None)
        if callable(tick_osc):
            tick_osc()
        if callable(save_osc):
            save_osc()

    after = dict(getattr(engine, "cocktail", {}) or {})
    return {
        **delta,
        "after": after,
        "affect_change": round(_affect_change(before, after), 6),
        "somatic_regions": sorted(dict(somatic_regions or {})),
    }
