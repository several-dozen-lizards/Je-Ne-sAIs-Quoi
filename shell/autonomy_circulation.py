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


def affect_projection_from_engine(engine, cocktail=None) -> dict[str, Any]:
    """Read the persona-owned atlas without making it an organ dependency."""
    organ = getattr(engine, "organ", None)
    atlas = getattr(organ, "affect_atlas", None)
    if atlas is None or not getattr(atlas, "enabled", False):
        return {}
    try:
        return dict(atlas.project(
            dict(cocktail if cocktail is not None else
                 getattr(engine, "cocktail", {}) or {})) or {})
    except Exception:
        return {}


def embody_affect_from_engine(engine, cocktail=None) -> dict[str, Any]:
    """Compose current affect and its descriptive atlas routes into soma."""
    soma = getattr(engine, "soma", None)
    if soma is None:
        return {}
    state = dict(cocktail if cocktail is not None else
                 getattr(engine, "cocktail", {}) or {})
    projection = affect_projection_from_engine(engine, state)
    if projection:
        try:
            soma.feel(state, affect_projection=projection)
            return projection
        except TypeError:
            # Compatibility with deliberately tiny bench doubles.
            pass
    soma.feel(state)
    return projection


def _affect_recurrence(before: Mapping[str, Any], after: Mapping[str, Any]) -> float:
    after_total = sum(max(0.0, float(value)) for value in
                      dict(after or {}).values()
                      if isinstance(value, (int, float)))
    if after_total <= 0.0:
        return 0.0
    shared = sum(min(max(0.0, float(dict(before or {}).get(key, 0.0))),
                     max(0.0, float(value)))
                 for key, value in dict(after or {}).items()
                 if isinstance(value, (int, float)))
    return max(0.0, min(1.0, shared / after_total))


def emit_affect_counterfactual(engine, delta: Mapping[str, Any], *,
                               model_receipts=None, now=None) -> dict[str, Any]:
    """Run one event-triggered, unapplied process-analogue comparison."""
    felt = dict(dict(delta or {}).get("felt") or {})
    organ = getattr(engine, "organ", None)
    atlas = getattr(organ, "affect_atlas", None)
    if not felt or atlas is None or not getattr(atlas, "enabled", False):
        return {}
    soma = getattr(engine, "soma", None)
    snapshot_fn = getattr(soma, "snapshot", None) if soma else None
    snapshot = snapshot_fn() if callable(snapshot_fn) else {}
    regions = dict(snapshot.get("regions") or {})
    body_activation = max((float(value.get("activation") or 0.0)
                           for value in regions.values()), default=0.0)
    signals = dict(getattr(soma, "signals", {}) or {}) if soma else {}
    osc = getattr(engine, "osc", None)
    coherence_fn = getattr(osc, "coherence", None) if osc else None
    coherence = coherence_fn() if callable(coherence_fn) else .5
    degraded = any(str(dict(item or {}).get("status") or "").casefold()
                   in {"degraded", "error", "failed"}
                   for item in list(model_receipts or []))
    try:
        capacity = float(readiness_from_engine(engine).get("capacity", .5))
    except Exception:
        capacity = .5
    observed = {
        "model_success": not degraded,
        "coherence": coherence,
        "novelty": signals.get("prediction_violation", .5),
        "recurrence": _affect_recurrence(
            dict(delta or {}).get("before") or {},
            dict(delta or {}).get("after") or getattr(
                engine, "cocktail", {}) or {}),
        "social": signals.get("bond", .5),
        "body_activation": body_activation,
        "capacity": capacity,
    }
    try:
        projection = dict(atlas.counterfactual(felt, observed) or {})
    except Exception as exc:
        projection = {
            "schema": 1, "mode": "shadow", "applied": False,
            "status": "projection_error", "error_type": type(exc).__name__,
            "downstream_channels_touched": [], "external_effects": False,
        }
    observer = getattr(engine, "salience_observer", None)
    emit = getattr(observer, "affect_counterfactual", None)
    if callable(emit):
        emit(projection, now=now)
    return projection


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


def _body_change(before: Mapping[str, Any], after: Mapping[str, Any]) -> float:
    """Strongest observed regional activation change, without naming a feeling."""
    before_regions = dict((before or {}).get("regions") or {})
    after_regions = dict((after or {}).get("regions") or {})
    changes = []
    for name in set(before_regions) | set(after_regions):
        try:
            prior = float(dict(before_regions.get(name) or {}).get(
                "activation", 0.0))
            current = float(dict(after_regions.get(name) or {}).get(
                "activation", 0.0))
        except (TypeError, ValueError):
            continue
        changes.append(abs(current - prior))
    return max(0.0, min(1.0, max(changes))) if changes else 0.0


def circulate_experienced_event(
        engine, event_text: str, *,
        somatic_regions: Mapping[str, Mapping[str, float]] = None,
        cycle_id: str = None, model_receipts: list = None,
        tolerate_affect_failure: bool = False
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
        try:
            with model_call_scope(
                    cycle_id=cycle_id or new_cycle_id(),
                    persona=getattr(engine, "persona", "unknown"),
                    purpose="affect_event", sink=model_receipts):
                delta = organ.feel_event(
                    event_text, judge,
                    persona_name=getattr(engine, "persona", "persona"),
                    pronouns=getattr(engine, "pronouns", ""))
            engine.cocktail = dict(organ.state.get("cocktail", {}))
        except Exception as affect_error:
            if not tolerate_affect_failure:
                raise
            delta = {
                "before": before, "felt": {}, "after": before,
                "why": "affect unavailable; measured body input continued",
                "affect_error_type": type(affect_error).__name__,
            }

    osc = getattr(engine, "osc", None)
    soma = getattr(engine, "soma", None)
    soma_snapshot = getattr(soma, "snapshot", None) if soma else None
    body_before = soma_snapshot() if callable(soma_snapshot) else {}
    emotion_pressure = getattr(osc, "emotion_pressure", None)
    if callable(emotion_pressure) and delta.get("felt"):
        emotion_pressure(delta.get("felt") or {})
    if soma is not None:
        if somatic_regions and hasattr(soma, "sense_regions"):
            soma.sense_regions(dict(somatic_regions))
        atlas_projection = embody_affect_from_engine(engine)
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
    soma_snapshot = getattr(soma, "snapshot", None) if soma else None
    body_after = soma_snapshot() if callable(soma_snapshot) else {}
    counterfactual = emit_affect_counterfactual(
        engine, delta, model_receipts=model_receipts)
    return {
        **delta,
        "after": after,
        "affect_change": round(_affect_change(before, after), 6),
        "body_change": round(_body_change(body_before, body_after), 6),
        "somatic_regions": sorted(dict(somatic_regions or {})),
        "affect_error_type": str(delta.get("affect_error_type") or ""),
        "affect_atlas": {
            "enabled": bool(atlas_projection) if soma is not None else False,
            "resolved_count": len((atlas_projection or {}).get(
                "resolutions") or []) if soma is not None else 0,
            "fiber_count": len((atlas_projection or {}).get(
                "fibers") or []) if soma is not None else 0,
            "counterfactual_status": counterfactual.get("status"),
        },
    }
