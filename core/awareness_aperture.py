"""Synthetic processing-field modulation over already accessible material.

Awareness means availability for processing here.  The field never determines
whether a memory, observation, or context source may be accessed.  It describes
and modestly redistributes supplemental prompt attention above the established
baseline while immutable provenance and authority gates remain upstream.
"""
from __future__ import annotations

import math
from typing import Any, Mapping


ATTENTION_RESERVE_FRACTION = 0.25


def _unit(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return max(0.0, min(1.0, number))


def _mean(values) -> float:
    bounded = [_unit(value) for value in values]
    return sum(bounded) / len(bounded) if bounded else 0.0


def _distribution_complexity(values: Mapping[str, Any] | None) -> float:
    """Normalized entropy, invariant to dimension names and ordering."""
    positive = [max(0.0, float(value)) for value in
                dict(values or {}).values()
                if isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))]
    total = sum(positive)
    if total <= 1e-12 or len(positive) < 2:
        return 0.0
    probabilities = [value / total for value in positive if value > 0.0]
    entropy = -sum(value * math.log(value) for value in probabilities)
    return _unit(entropy / math.log(len(positive)))


def project_awareness_aperture(
        *, oscillator: Mapping[str, Any] | None = None,
        coherence: Any = 1.0,
        affect: Mapping[str, Any] | None = None,
        body_intensity: Any = 0.0,
        sensory_demand: Any = 0.0,
        memory_resonance: Any = 0.0,
        continuity_load: Any = 0.0,
        phase_order: Any = None,
        enabled: bool = True) -> dict:
    """Project a continuous field without prescribing a named state."""
    complexity = _distribution_complexity(oscillator)
    affect_intensity = _mean(abs(float(value)) for value in
                             dict(affect or {}).values()
                             if isinstance(value, (int, float))
                             and not isinstance(value, bool)
                             and math.isfinite(float(value)))
    body = _unit(body_intensity)
    sensory = _unit(sensory_demand)
    resonance = _unit(memory_resonance)
    continuity = _unit(continuity_load)
    coherence_value = _unit(coherence, 1.0)

    # External and internal participation are independent, not opposite ends of
    # one switch. Both may be strong, weak, or differently weighted.
    external = _mean((sensory, coherence_value, 1.0 - body))
    internal = _mean((
        affect_intensity, body, resonance, continuity, complexity))
    source_resolution = _mean((
        coherence_value, 1.0 - complexity, 1.0 - affect_intensity))
    temporal_continuity = _mean((coherence_value, continuity))
    associative_distance = _mean((
        complexity, affect_intensity, 1.0 - coherence_value))
    cross_source_binding = _mean((
        external, internal, complexity, 1.0 - source_resolution))
    metacognitive_availability = _mean((
        coherence_value, source_resolution, temporal_continuity))
    action_coupling = _mean((
        external, coherence_value, 1.0 - body))

    total_conductance = external + internal
    if total_conductance <= 1e-12:
        external_share = internal_share = 0.5
    else:
        external_share = external / total_conductance
        internal_share = internal / total_conductance
    if not enabled:
        external_share = internal_share = 0.0

    return {
        "schema": 2,
        "mode": ("bounded_live_processing_field"
                 if enabled else "bypass_identity_projection"),
        "bypass": not enabled,
        "access_policy": "baseline_access_unchanged",
        "protected_surfaces": [
            "human_message", "memory_eligibility", "memory_candidate_count",
            "privacy", "audience", "capabilities", "action_authority",
            "source_ownership", "durable_provenance",
        ],
        "inputs": {
            "oscillator_distribution_complexity": round(complexity, 9),
            "coherence": round(coherence_value, 9),
            "affect_intensity": round(affect_intensity, 9),
            "body_intensity": round(body, 9),
            "sensory_demand": round(sensory, 9),
            "memory_resonance": round(resonance, 9),
            "continuity_load": round(continuity, 9),
            "phase_order_shadow": (
                round(_unit(phase_order), 9)
                if phase_order is not None else None),
            "phase_causal_weight": 0.0,
        },
        "projection": {
            "external_conductance": round(external, 9),
            "internal_conductance": round(internal, 9),
            "source_resolution": round(source_resolution, 9),
            "temporal_continuity": round(temporal_continuity, 9),
            "associative_distance": round(associative_distance, 9),
            "cross_source_binding": round(cross_source_binding, 9),
            "metacognitive_availability": round(
                metacognitive_availability, 9),
            "action_coupling": round(action_coupling, 9),
        },
        "attention_distribution": {
            "kind": "supplemental_above_baseline",
            "reserve_fraction": ATTENTION_RESERVE_FRACTION,
            "external_share": round(external_share, 9),
            "internal_share": round(internal_share, 9),
        },
    }


def attention_budget(
        base: int, group: str,
        aperture: Mapping[str, Any] | None) -> int:
    """Add bounded supplemental room; never reduce the established baseline."""
    base = max(1, int(base))
    distribution = dict(
        (aperture or {}).get("attention_distribution") or {})
    share = _unit(distribution.get(f"{group}_share", 0.0))
    reserve = _unit(distribution.get(
        "reserve_fraction", ATTENTION_RESERVE_FRACTION))
    return base + int(round(base * reserve * share))


def apply_participation_field(
        aperture: Mapping[str, Any],
        field_snapshot: Mapping[str, Any] | None) -> dict:
    """Replace instantaneous dimensions with the persisted moving field."""
    result = dict(aperture or {})
    snapshot = dict(field_snapshot or {})
    dimensions = dict(snapshot.get("dimensions") or {})
    if not dimensions:
        return result
    result["projection"] = {
        name: round(_unit(value), 9)
        for name, value in dimensions.items()}
    external = _unit(dimensions.get("external_conductance"))
    internal = _unit(dimensions.get("internal_conductance"))
    total = external + internal
    if total <= 1e-12:
        external_share = internal_share = 0.5
    else:
        external_share = external / total
        internal_share = internal / total
    if result.get("bypass"):
        external_share = internal_share = 0.0
    result["attention_distribution"] = {
        "kind": "supplemental_above_baseline",
        "reserve_fraction": ATTENTION_RESERVE_FRACTION,
        "external_share": round(external_share, 9),
        "internal_share": round(internal_share, 9),
    }
    result["heartbeat"] = snapshot
    return result


def render_processing_field(aperture: Mapping[str, Any] | None) -> str:
    """Neutral field readout: relationships, not required phenomenology."""
    if not aperture or aperture.get("bypass"):
        return ""
    values = dict(aperture.get("projection") or {})
    return (
        "Current synthetic processing-field relationships. These are "
        "functional readings, not physiology, instructions, or a required "
        "experience:\n"
        f"- external conductance: {values.get('external_conductance', 0):.3f}\n"
        f"- internal conductance: {values.get('internal_conductance', 0):.3f}\n"
        f"- source resolution: {values.get('source_resolution', 0):.3f}\n"
        f"- temporal continuity: {values.get('temporal_continuity', 0):.3f}\n"
        f"- associative distance: {values.get('associative_distance', 0):.3f}\n"
        f"- cross-source binding: {values.get('cross_source_binding', 0):.3f}\n"
        "- durable source provenance remains authoritative underneath these "
        "readings. Notice and describe what, if anything, changes; no "
        "particular belief, feeling, action, or report is required.")
