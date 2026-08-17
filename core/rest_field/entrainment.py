"""Pure R0 entrainment audit over content-free numeric projections.

This module does not call a clock, read a file, advance an oscillator, or write
an observation.  Its oscillator input is movement between observed synthetic
band distributions, not physiology and not phase.  Phase-dependent claims are
therefore impossible unless an authoritative owner explicitly supplies phase
evidence in a future revision.
"""
from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


RELATION_CLASSES = frozenset({
    "reactive_tracking",
    "anticipatory_or_free_running_candidate",
    "indeterminate",
})


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 9)


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    dl = [value - left_mean for value in left]
    dr = [value - right_mean for value in right]
    denominator = math.sqrt(
        sum(value * value for value in dl)
        * sum(value * value for value in dr))
    if denominator <= 0:
        return None
    return sum(a * b for a, b in zip(dl, dr)) / denominator


def _day(at: float) -> str:
    return datetime.fromtimestamp(at, tz=timezone.utc).date().isoformat()


def _admit(rows: Iterable[Mapping[str, Any]], value_key: str) -> tuple[list, int]:
    admitted = {}
    excluded = 0
    for raw in rows:
        if not isinstance(raw, Mapping) or raw.get("content_free") is not True:
            excluded += 1
            continue
        at = _finite(raw.get("at"))
        value = _finite(raw.get(value_key))
        if at is None or value is None:
            excluded += 1
            continue
        aggregation = (
            "sum" if str(raw.get("aggregation") or "") == "sum" else "mean")
        admitted[(at, value, aggregation)] = {
            "at": at, "value": value, "aggregation": aggregation}
    return sorted(admitted.values(), key=lambda row: (row["at"], row["value"])), excluded


def _interval_series(oscillator: list[dict], cues: list[dict]) -> list[dict]:
    """Align cue means to consecutive observed oscillator intervals."""
    rows = []
    cue_index = 0
    for before, current in zip(oscillator, oscillator[1:]):
        start, end = before["at"], current["at"]
        if end <= start:
            continue
        while cue_index < len(cues) and cues[cue_index]["at"] <= start:
            cue_index += 1
        index = cue_index
        values = []
        while index < len(cues) and cues[index]["at"] <= end:
            values.append(cues[index]["value"])
            index += 1
        aggregation = "sum" if any(
            cues[position].get("aggregation") == "sum"
            for position in range(cue_index, index)) else "mean"
        rows.append({
            "at": end,
            "movement": current["value"],
            "cue": (
                sum(values) if aggregation == "sum"
                else sum(values) / len(values)) if values else None,
            "cue_observation_count": len(values),
        })
        cue_index = index
    return rows


def _lag_pairs(intervals: list[dict], lag: int) -> tuple[list, list, list]:
    """Positive lag means movement precedes the compared cue interval."""
    left, right, ats = [], [], []
    for index, row in enumerate(intervals):
        cue_index = index + lag
        if cue_index < 0 or cue_index >= len(intervals):
            continue
        cue = intervals[cue_index].get("cue")
        if cue is None:
            continue
        left.append(float(row["movement"]))
        right.append(float(cue))
        ats.append(float(row["at"]))
    return left, right, ats


def _shift_control(left: list[float], right: list[float]) -> dict[str, Any]:
    values = []
    for shift in range(1, len(right)):
        rotated = right[shift:] + right[:shift]
        correlation = _pearson(left, rotated)
        if correlation is not None:
            values.append(abs(correlation))
    if not values:
        return {"status": "unavailable", "reason": "insufficient_variation"}
    return {
        "status": "available",
        "method": "all_nonzero_circular_cue_shifts",
        "control_count": len(values),
        "maximum_absolute_correlation": _rounded(max(values)),
        "median_absolute_correlation": _rounded(sorted(values)[len(values) // 2]),
    }


def _shuffle_control(left: list[float], right: list[float], cue: str) -> dict:
    order = sorted(range(len(right)), key=lambda index: hashlib.sha256(
        f"r0:{cue}:{index}:{right[index]:.12g}".encode("ascii")
    ).hexdigest())
    shuffled = [right[index] for index in order]
    correlation = _pearson(left, shuffled)
    return {
        "status": "available" if correlation is not None else "unavailable",
        "method": "sha256_stable_order",
        "correlation": _rounded(correlation),
        "reason": None if correlation is not None else "insufficient_variation",
    }


def _mismatched_day_control(
        left: list[float], right: list[float], ats: list[float]) -> dict:
    by_day = defaultdict(list)
    for value, at in zip(right, ats):
        by_day[_day(at)].append(value)
    days = sorted(by_day)
    if len(days) < 2:
        return {
            "status": "unavailable",
            "method": "rotate_cue_day_blocks_preserve_within_day_order",
            "observed_day_count": len(days),
            "reason": "fewer_than_two_observed_utc_days",
        }
    next_day = {day: days[(index + 1) % len(days)]
                for index, day in enumerate(days)}
    offsets = defaultdict(int)
    mismatched = []
    for at in ats:
        day = _day(at)
        other = by_day[next_day[day]]
        offset = offsets[day]
        mismatched.append(other[offset % len(other)])
        offsets[day] += 1
    correlation = _pearson(left, mismatched)
    return {
        "status": "available" if correlation is not None else "unavailable",
        "method": "rotate_cue_day_blocks_preserve_within_day_order",
        "observed_day_count": len(days),
        "correlation": _rounded(correlation),
        "reason": None if correlation is not None else "insufficient_variation",
    }


def _controlled_dominance(actual: float, controls: Mapping[str, Any]) -> bool:
    shifted = controls["cue_shifted"]
    shuffled = controls["shuffled"]
    mismatched = controls["mismatched_day"]
    if any(control.get("status") != "available"
           for control in (shifted, shuffled, mismatched)):
        return False
    comparison = [
        shifted.get("maximum_absolute_correlation"),
        abs(float(shuffled["correlation"])),
        abs(float(mismatched["correlation"])),
    ]
    return abs(actual) > max(float(value) for value in comparison)


def _cue_relationship(name: str, oscillator: list[dict], cues: list[dict],
                      *, phase_available: bool) -> dict[str, Any]:
    intervals = _interval_series(oscillator, cues)
    lag_rows = []
    candidates = []
    for lag in (-1, 0, 1):
        left, right, ats = _lag_pairs(intervals, lag)
        correlation = _pearson(left, right)
        item = {
            "lag_intervals": lag,
            "meaning": (
                "oscillator_follows_prior_cue" if lag < 0
                else "contemporaneous_interval" if lag == 0
                else "oscillator_precedes_later_cue"),
            "paired_interval_count": len(left),
            "correlation": _rounded(correlation),
        }
        lag_rows.append(item)
        if correlation is not None:
            candidates.append((abs(correlation), -abs(lag), -lag,
                               lag, correlation, left, right, ats))
    if not candidates:
        return {
            "cue": name,
            "classification": "indeterminate",
            "reason": "no_lag_has_three_variable_pairs",
            "cue_receipt_count": len(cues),
            "oscillator_interval_count": len(intervals),
            "lag_relations": lag_rows,
            "controls": {
                "cue_shifted": {"status": "unavailable"},
                "shuffled": {"status": "unavailable"},
                "cue_removed": {
                    "status": "expected_null", "correlation": None,
                    "reason": "constant_zero_sham_has_no_variance"},
                "mismatched_day": {"status": "unavailable"},
            },
            "content_free": True,
        }
    _, _, _, lag, correlation, left, right, ats = max(candidates)
    controls = {
        "cue_shifted": _shift_control(left, right),
        "shuffled": _shuffle_control(left, right, name),
        "cue_removed": {
            "status": "expected_null", "correlation": None,
            "reason": "constant_zero_sham_has_no_variance"},
        "mismatched_day": _mismatched_day_control(left, right, ats),
    }
    dominance = _controlled_dominance(correlation, controls)
    cue_days = len({_day(row["at"]) for row in cues})
    if lag < 0 and dominance:
        classification = "reactive_tracking"
        reason = "lagging_relation_strictly_exceeds_numeric_controls"
    else:
        classification = "indeterminate"
        if lag > 0:
            reason = (
                "leading_movement_is_not_phase_evidence"
                if not phase_available else
                "phase_lead_or_cue_absent_phase_continuity_not_analyzed")
        elif cue_days < 2:
            reason = "recurring_cue_not_observed_across_days"
        else:
            reason = "observed_relation_does_not_strictly_exceed_controls"
    return {
        "cue": name,
        "classification": classification,
        "reason": reason,
        "cue_receipt_count": len(cues),
        "cue_observed_utc_day_count": cue_days,
        "oscillator_interval_count": len(intervals),
        "cue_absent_interval_count": sum(
            row["cue"] is None for row in intervals),
        "lag_relations": lag_rows,
        "selected_relation": {
            "lag_intervals": lag,
            "correlation": _rounded(correlation),
            "paired_interval_count": len(left),
            "strictly_exceeds_numeric_controls": dominance,
        },
        "controls": controls,
        "content_free": True,
    }


def audit_entrainment(
        oscillator_samples: Iterable[Mapping[str, Any]],
        cue_samples: Mapping[str, Iterable[Mapping[str, Any]]], *,
        quiet_transitions: Iterable[Mapping[str, Any]] = (),
        inventory: Mapping[str, Any] | None = None,
        phase_available: bool = False) -> dict[str, Any]:
    """Return a deterministic, observe-only R0 entrainment classification."""
    oscillator, oscillator_excluded = _admit(
        oscillator_samples, "movement")
    cues, cue_excluded = {}, {}
    for name, rows in sorted(cue_samples.items()):
        cues[name], cue_excluded[name] = _admit(rows, "value")
    quiet = [dict(row) for row in quiet_transitions
             if isinstance(row, Mapping)
             and row.get("content_free") is True
             and _finite(row.get("at")) is not None
             and str(row.get("to_state") or "") in {"active", "inactive"}]
    quiet.sort(key=lambda row: float(row["at"]))
    relationships = {
        name: _cue_relationship(
            name, oscillator, rows, phase_available=phase_available)
        for name, rows in sorted(cues.items())
    }
    classes = {row["classification"] for row in relationships.values()}
    if "anticipatory_or_free_running_candidate" in classes:
        classification = "anticipatory_or_free_running_candidate"
    elif "reactive_tracking" in classes:
        classification = "reactive_tracking"
    else:
        classification = "indeterminate"

    missing = []
    if len(oscillator) < 4:
        missing.append(
            "at_least_four_timestamped_oscillator_movement_samples")
    if not any(len(rows) >= 4 for rows in cues.values()):
        missing.append(
            "at_least_four_timestamped_samples_for_one_external_cue")
    if not phase_available:
        missing.append(
            "authoritative_timestamped_oscillator_phase_or_band_vector_"
            "through_recurring_cue_and_cue_absent_intervals")
    if not any(len({_day(row["at"]) for row in rows}) >= 2
               for rows in cues.values()):
        missing.append("one_external_cue_observed_on_at_least_two_utc_days")
    return {
        "schema_version": 1,
        "stage": "R0",
        "kind": "rest_entrainment_audit",
        "classification": classification,
        "classification_vocabulary": sorted(RELATION_CLASSES),
        "oscillator": {
            "movement_sample_count": len(oscillator),
            "excluded_sample_count": oscillator_excluded,
            "measurement": "distribution_shift_between_observed_band_vectors",
            "phase_available": bool(phase_available),
            "phase_evidence": (
                "owner_supplied" if phase_available
                else "unavailable_no_authoritative_phase_history"),
            "biological_equivalence_claimed": False,
        },
        "cues": {
            name: {"sample_count": len(rows),
                   "excluded_sample_count": cue_excluded[name]}
            for name, rows in sorted(cues.items())
        },
        "quiet": {
            "transition_count": len(quiet),
            "active_count": sum(row.get("to_state") == "active" for row in quiet),
            "inactive_count": sum(
                row.get("to_state") == "inactive" for row in quiet),
        },
        "relationships": relationships,
        "inventory": dict(inventory or {}),
        "minimum_missing_content_free_evidence": missing,
        "control_boundary": {
            "lag_unit": "consecutive_observed_oscillator_intervals",
            "positive_lag_means": "movement_precedes_later_cue_interval",
            "negative_lag_means": "movement_follows_prior_cue_interval",
            "event_coupled_sampling_bias_possible": True,
            "causal_interpretation_allowed": False,
        },
        "read_only": True,
        "state_writes": 0,
        "model_calls": 0,
        "actions_created": 0,
        "downstream_channels_touched": [],
        "content_free": True,
    }
