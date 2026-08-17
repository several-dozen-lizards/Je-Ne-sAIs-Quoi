"""Content-free adapters from existing JNSQ relationships to rest metrics.

Every adapter returns normalized measurements and availability.  The adapters
do not decide field weights, name a state, or infer recovery from activation.
Those candidate relationships belong to an explicit experiment configuration.
"""
from __future__ import annotations

import math
from typing import Any, Mapping


SOURCE_REVISIONS = {
    "assembly_pressure": "1",
    "consolidation_backlog": "1",
    "rhythm_variation": "1",
    "continuity_load": "1",
    "somatic_activity": "1",
    "interaction_forcing": "1",
}


def _finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _unit(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _finite(value, default)))


def _packet(source: str, measurements: Mapping[str, Any] | None = None,
            *, available: bool = True, reason: str = "observed") -> dict:
    if source not in SOURCE_REVISIONS:
        raise ValueError(f"unknown rest source adapter: {source}")
    admitted = {
        str(name): round(_unit(value), 9)
        for name, value in dict(measurements or {}).items()}
    return {
        "schema_version": 1,
        "source": source,
        "source_revision": SOURCE_REVISIONS[source],
        "available": bool(available),
        "reason": str(reason or "observed")[:80],
        "measurements": admitted if available else {},
        "content_free": True,
    }


def calibration_source_specs() -> dict:
    """Typed doors with no candidate-anatomy weights during calibration."""
    metrics = {
        "assembly_pressure": (
            "window_fill", "candidate_loss_fraction", "affected_fraction"),
        "consolidation_backlog": ("backlog_fill", "has_eligible"),
        "rhythm_variation": (
            "distribution_complexity", "distribution_shift", "coherence"),
        "continuity_load": ("window_fill",),
        "somatic_activity": (
            "activation_mean", "activation_peak", "activation_change"),
        "interaction_forcing": ("arrival_pulse", "completion_pulse"),
    }
    return {
        source: {
            "kind": "organ",
            "revision": SOURCE_REVISIONS[source],
            "baselines": {name: 0.0 for name in names},
            "weights": {},
        }
        for source, names in metrics.items()
    }


def assembly_pressure(receipt: Mapping[str, Any] | None) -> dict:
    receipt = dict(receipt or {})
    envelope = dict(receipt.get("envelope") or {})
    window = max(0.0, _finite(envelope.get("practical_window_tokens")))
    after = max(0.0, _finite(receipt.get("estimated_total_tokens_after")))
    candidates = [dict(item or {}) for item in
                  list(receipt.get("candidates") or ())]
    if window <= 0.0:
        return _packet(
            "assembly_pressure", available=False,
            reason="practical_window_unavailable")
    tokens_before = sum(max(0.0, _finite(item.get("tokens_before")))
                        for item in candidates)
    tokens_after = sum(max(0.0, _finite(item.get("tokens_after")))
                       for item in candidates)
    affected = sum(
        str(item.get("outcome") or "") in {"truncated", "dropped"}
        for item in candidates)
    return _packet("assembly_pressure", {
        "window_fill": after / window,
        "candidate_loss_fraction": (
            max(0.0, tokens_before - tokens_after) / tokens_before
            if tokens_before > 0.0 else 0.0),
        "affected_fraction": (
            affected / len(candidates) if candidates else 0.0),
    })


def consolidation_backlog(*, eligible_count: Any,
                          pending_source_chars: Any,
                          source_char_budget: Any) -> dict:
    eligible = max(0.0, _finite(eligible_count))
    pending = max(0.0, _finite(pending_source_chars))
    budget = max(0.0, _finite(source_char_budget))
    if budget <= 0.0:
        return _packet(
            "consolidation_backlog", available=False,
            reason="source_budget_unavailable")
    return _packet("consolidation_backlog", {
        "backlog_fill": (
            pending / (pending + budget) if pending > 0.0 else 0.0),
        "has_eligible": 1.0 if eligible > 0.0 else 0.0,
    })


def _distribution_complexity(values: Mapping[str, Any]) -> float:
    positive = [max(0.0, _finite(value))
                for value in dict(values or {}).values()]
    positive = [value for value in positive if value > 0.0]
    if len(positive) < 2:
        return 0.0
    total = sum(positive)
    probabilities = [value / total for value in positive]
    entropy = -sum(value * math.log(value) for value in probabilities)
    return _unit(entropy / math.log(len(probabilities)))


def rhythm_variation(oscillator) -> dict:
    if oscillator is None:
        return _packet(
            "rhythm_variation", available=False,
            reason="oscillator_unavailable")
    bands = dict(getattr(oscillator, "bands", {}) or {})
    previous = dict(getattr(oscillator, "previous_bands", {}) or {})
    if not bands:
        return _packet(
            "rhythm_variation", available=False,
            reason="distribution_unavailable")
    common = set(bands) & set(previous)
    shift = (sum(abs(_finite(bands[name]) - _finite(previous[name]))
                 for name in common) / 2.0 if common else 0.0)
    coherence = getattr(oscillator, "coherence", None)
    coherence = coherence() if callable(coherence) else coherence
    return _packet("rhythm_variation", {
        "distribution_complexity": _distribution_complexity(bands),
        "distribution_shift": shift,
        "coherence": _unit(coherence, 1.0),
    })


def continuity_load(window_count: Any, capacity: Any) -> dict:
    capacity_value = max(0.0, _finite(capacity))
    if capacity_value <= 0.0:
        return _packet(
            "continuity_load", available=False,
            reason="window_capacity_unavailable")
    return _packet("continuity_load", {
        "window_fill": max(0.0, _finite(window_count)) / capacity_value,
    })


def somatic_activity(soma) -> dict:
    if soma is None:
        return _packet(
            "somatic_activity", available=False,
            reason="soma_unavailable")
    regions = dict(getattr(soma, "regions", {}) or {})
    previous = dict(getattr(soma, "previous_regions", {}) or {})
    if not regions:
        return _packet(
            "somatic_activity", available=False,
            reason="region_state_unavailable")
    current_values = {
        name: _unit(dict(value or {}).get("activation"))
        for name, value in regions.items()}
    peak = max(current_values.values(), default=0.0)
    mean = sum(current_values.values()) / max(1, len(current_values))
    change = sum(abs(value - _unit(
        dict(previous.get(name) or {}).get("activation")))
                 for name, value in current_values.items()) / max(
                     1, len(current_values))
    return _packet("somatic_activity", {
        "activation_mean": mean,
        "activation_peak": peak,
        "activation_change": change,
    })


def interaction_forcing(kind: str) -> dict:
    kind = str(kind or "").strip()
    if kind not in {"arrival", "completion"}:
        return _packet(
            "interaction_forcing", available=False,
            reason="unknown_interaction_boundary")
    return _packet("interaction_forcing", {
        "arrival_pulse": 1.0 if kind == "arrival" else 0.0,
        "completion_pulse": 1.0 if kind == "completion" else 0.0,
    }, reason=kind)
