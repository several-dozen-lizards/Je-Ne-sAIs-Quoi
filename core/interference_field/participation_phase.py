"""Shadow phase projection from temporally situated organism participation.

This is not an EEG simulator and assigns no experiential meaning to an angle.
Each source owns a carrier whose phase advances with observed event cadence.
Carriers couple only when their numeric participation vectors are similar.
The resulting phase therefore summarizes timing, recurrence, and shared state;
it never enters prompt, attention, memory, feeling, soma, or action selection.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _unit(value: Any) -> float:
    return max(0.0, min(1.0, _finite(value)))


def normalize_participation(value: Mapping[str, Any] | None) -> dict[str, float]:
    """Accept a bounded numeric vector; reject prose and nested structures."""
    result = {}
    for key, raw in dict(value or {}).items():
        name = str(key)[:64]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        result[name] = round(_unit(raw), 9)
    return result


def _cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 0.0
    dot = sum(float(left.get(key, 0.0)) * float(right.get(key, 0.0))
              for key in keys)
    left_norm = math.sqrt(sum(float(left.get(key, 0.0)) ** 2
                              for key in keys))
    right_norm = math.sqrt(sum(float(right.get(key, 0.0)) ** 2
                               for key in keys))
    if left_norm <= 1e-12 or right_norm <= 1e-12:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _circular_mean(phases: list[float]) -> float | None:
    if not phases:
        return None
    x = sum(math.cos(value) for value in phases)
    y = sum(math.sin(value) for value in phases)
    if abs(x) + abs(y) <= 1e-12:
        return None
    return math.atan2(y, x)


def _wrap(value: float) -> float:
    return value % (2.0 * math.pi)


def _signed_delta(target: float, current: float) -> float:
    return (target - current + math.pi) % (2.0 * math.pi) - math.pi


def project_participation_phase(events, *, at=None) -> dict:
    """Replay timestamped events through a content-free coupled phase field.

    Cadence is learned from the median of the observed positive gaps. A source
    carrier advances faster when an event is strong, and is pulled toward the
    circular mean of other carriers in proportion to numeric-state similarity.
    No source label is assigned a direction, frequency, or psychological role.
    """
    ordered = sorted(
        (dict(row) for row in events if isinstance(row, Mapping)
         and "ts" in row),
        key=lambda row: _finite(row.get("ts")))
    gaps = [max(0.0, _finite(right["ts"]) - _finite(left["ts"]))
            for left, right in zip(ordered, ordered[1:])
            if _finite(right["ts"]) > _finite(left["ts"])]
    positive = sorted(gap for gap in gaps if gap > 0.0)
    if positive:
        middle = len(positive) // 2
        cadence = (positive[middle] if len(positive) % 2 else
                   (positive[middle - 1] + positive[middle]) / 2.0)
    else:
        cadence = 1.0
    cadence = max(0.001, cadence)

    carriers: dict[str, dict] = {}
    recent_gaps = deque(maxlen=16)
    last_ts = None
    for row in ordered:
        ts = _finite(row.get("ts"))
        if last_ts is not None:
            dt = max(0.0, ts - last_ts)
            if dt > 0.0:
                recent_gaps.append(dt)
            local_cadence = (
                sorted(recent_gaps)[len(recent_gaps) // 2]
                if recent_gaps else cadence)
            advance = 2.0 * math.pi * dt / max(0.001, local_cadence)
            for state in carriers.values():
                state["phase"] = _wrap(
                    state["phase"] + advance * state["rate"])

        source = str(row.get("source") or "unknown")[:96]
        vector = normalize_participation(row.get("participation"))
        magnitude = _unit(row.get("magnitude", 1.0))
        state = carriers.setdefault(source, {
            "phase": 0.0, "vector": {}, "events": 0, "coupling_sum": 0.0,
            "rate": 1.0})

        peers = []
        similarities = []
        for name, peer in carriers.items():
            if name == source or not peer["vector"] or not vector:
                continue
            similarity = _cosine(vector, peer["vector"])
            if similarity > 0.0:
                peers.append(peer["phase"])
                similarities.append(similarity)
        target = _circular_mean(peers)
        coupling = (sum(similarities) / len(similarities)
                    if similarities else 0.0)
        if target is not None:
            state["phase"] = _wrap(
                state["phase"]
                + _signed_delta(target, state["phase"])
                * coupling * magnitude * 0.5)

        # Participation intensity changes traversal without assigning any
        # particular vector component a named experiential direction.
        intensity = (sum(vector.values()) / len(vector)) if vector else 0.0
        state["phase"] = _wrap(
            state["phase"] + math.pi * magnitude * intensity)
        state["rate"] = 0.5 + intensity
        state["vector"] = vector
        state["events"] += 1
        state["coupling_sum"] += coupling
        last_ts = ts

    target_at = (_finite(at) if at is not None else
                 (_finite(last_ts) if last_ts is not None else 0.0))
    if last_ts is not None and target_at > last_ts:
        advance = 2.0 * math.pi * (target_at - last_ts) / cadence
        for state in carriers.values():
            state["phase"] = _wrap(
                state["phase"] + advance * state["rate"])

    phases = [state["phase"] for state in carriers.values()]
    order = 0.0
    if phases:
        order = abs(sum(complex(math.cos(value), math.sin(value))
                        for value in phases) / len(phases))
    return {
        "schema": 1,
        "mode": "shadow_participation_phase",
        "downstream_channels_touched": [],
        "event_count": len(ordered),
        "source_count": len(carriers),
        "observed_median_cadence_s": round(cadence, 9),
        "phase_order": round(order, 9),
        "projected_at": target_at,
        "sources": {
            name: {
                "phase_rad": round(state["phase"], 9),
                "event_count": state["events"],
                "mean_coupling": round(
                    state["coupling_sum"] / max(1, state["events"]), 9),
                "participation_dimensions": sorted(state["vector"]),
            }
            for name, state in sorted(carriers.items())
        },
    }
