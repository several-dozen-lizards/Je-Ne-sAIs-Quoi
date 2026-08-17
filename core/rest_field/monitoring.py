"""Content-free longitudinal monitoring for Stage-1 rest calibration.

The monitor describes the receipt stream.  It does not fit field weights,
instantiate a RestField, alter resident state, or authorize promotion.  Pair
relationships are explicitly exploratory and are compared with deterministic
circular-shift controls so a visually interesting correlation cannot quietly
become a causal story.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping


EXPECTED_SOURCES = frozenset({
    "assembly_pressure",
    "consolidation_backlog",
    "continuity_load",
    "interaction_forcing",
    "rhythm_variation",
    "somatic_activity",
})


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quantile(values: list[float], fraction: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    mix = position - lower
    return ordered[lower] * (1.0 - mix) + ordered[upper] * mix


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 9)


def _summary(values: Iterable[float]) -> dict[str, Any]:
    admitted = sorted(value for value in values if math.isfinite(value))
    if not admitted:
        return {"count": 0}
    return {
        "count": len(admitted),
        "min": _rounded(admitted[0]),
        "p10": _rounded(_quantile(admitted, 0.10)),
        "p50": _rounded(_quantile(admitted, 0.50)),
        "p90": _rounded(_quantile(admitted, 0.90)),
        "max": _rounded(admitted[-1]),
        "mean": _rounded(sum(admitted) / len(admitted)),
    }


def _ks_distance(left: list[float], right: list[float]) -> float | None:
    """Return the exact two-sample empirical CDF distance."""
    if not left or not right:
        return None
    points = sorted(set(left) | set(right))
    distance = max(abs(
        sum(value <= point for value in left) / len(left)
        - sum(value <= point for value in right) / len(right))
        for point in points)
    return _rounded(distance)


def _equal_half_drift(values: list[tuple[float, float]]) -> dict[str, Any]:
    ordered = [value for _, value in sorted(values)]
    half = len(ordered) // 2
    if half < 1:
        return {
            "status": "insufficient_for_equal_halves",
            "count": len(ordered),
        }
    earlier = ordered[:half]
    recent = ordered[-half:]
    earlier_median = _quantile(earlier, 0.5)
    recent_median = _quantile(recent, 0.5)
    scale = (_quantile(ordered, 0.9) or 0.0) - (
        _quantile(ordered, 0.1) or 0.0)
    delta = float(recent_median or 0.0) - float(earlier_median or 0.0)
    return {
        "status": "descriptive",
        "comparison": "equal_temporal_halves",
        "count_each": half,
        "earlier_p50": _rounded(earlier_median),
        "recent_p50": _rounded(recent_median),
        "median_delta": _rounded(delta),
        "median_delta_over_p10_p90_span": (
            _rounded(delta / scale) if scale > 0 else None),
        "empirical_cdf_distance": _ks_distance(earlier, recent),
        "alert_threshold_applied": False,
    }


def _cycle_id(event_ref: str) -> str:
    if not event_ref or event_ref.startswith("rest-consolidation:"):
        return ""
    markers = (
        ":rest-interaction-arrival",
        ":rest-arrival",
        ":rest-continuity",
        ":rest-assembly",
        ":rest-interaction-completion",
        ":rest-completion",
    )
    for marker in markers:
        if marker in event_ref:
            return event_ref.split(marker, 1)[0]
    return ""


def _boundary(row: Mapping[str, Any]) -> str:
    source = str(row.get("source") or "")
    ref = str(row.get("event_ref") or "")
    measurements = dict(row.get("measurements") or {})
    if source == "interaction_forcing":
        if float(measurements.get("arrival_pulse") or 0.0) > 0:
            return "arrival"
        if float(measurements.get("completion_pulse") or 0.0) > 0:
            return "completion"
    if source == "rhythm_variation":
        return "rhythm_completion" if ":rest-completion" in ref \
            else "rhythm_arrival" if ":rest-arrival" in ref else "rhythm"
    if source == "somatic_activity":
        return "soma_completion" if ":rest-completion" in ref \
            else "soma_arrival" if ":rest-arrival" in ref else "soma"
    if source == "continuity_load":
        return "continuity"
    if source == "assembly_pressure":
        return "assembly"
    return source


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    denominator = math.sqrt(
        sum(value * value for value in left_delta)
        * sum(value * value for value in right_delta))
    if denominator <= 0:
        return None
    return sum(a * b for a, b in zip(left_delta, right_delta)) / denominator


def _paired_values(
        ordered_cycles: list[str], vectors: Mapping[str, Mapping[str, float]],
        left_name: str, right_name: str, lag: int) -> tuple[list[float], list[float]]:
    left, right = [], []
    for index, cycle in enumerate(ordered_cycles):
        other_index = index + lag
        if other_index < 0 or other_index >= len(ordered_cycles):
            continue
        other_cycle = ordered_cycles[other_index]
        if left_name not in vectors.get(cycle, {}):
            continue
        if right_name not in vectors.get(other_cycle, {}):
            continue
        left.append(float(vectors[cycle][left_name]))
        right.append(float(vectors[other_cycle][right_name]))
    return left, right


def _circular_shift_control(
        left: list[float], right: list[float], observed: float) -> dict[str, Any]:
    null = []
    for shift in range(1, len(right)):
        rotated = right[shift:] + right[:shift]
        value = _pearson(left, rotated)
        if value is not None:
            null.append(abs(value))
    if not null:
        return {"status": "insufficient", "sample_count": 0}
    absolute = abs(observed)
    exceed = sum(value >= absolute for value in null)
    return {
        "status": "descriptive_null",
        "method": "all_nonzero_circular_shifts",
        "sample_count": len(null),
        "absolute_correlation_p50": _rounded(_quantile(null, 0.5)),
        "absolute_correlation_p90": _rounded(_quantile(null, 0.9)),
        "add_one_upper_tail_probability": _rounded(
            (exceed + 1) / (len(null) + 1)),
    }


def _relationships(
        cycles: Mapping[str, Mapping[str, Any]],
        vectors: Mapping[str, Mapping[str, float]]) -> dict[str, Any]:
    ordered_cycles = [cycle for cycle, _ in sorted(
        cycles.items(), key=lambda item: item[1]["first_at"])]
    metric_names = sorted({
        name for vector in vectors.values() for name in vector})
    rows = []
    for left_name, right_name in combinations(metric_names, 2):
        if left_name.split(".", 1)[0] == right_name.split(".", 1)[0]:
            continue
        candidates = []
        for lag in (-1, 0, 1):
            left, right = _paired_values(
                ordered_cycles, vectors, left_name, right_name, lag)
            correlation = _pearson(left, right)
            if correlation is None:
                continue
            candidates.append((abs(correlation), lag, correlation, left, right))
        if not candidates:
            continue
        _, lag, correlation, left, right = max(
            candidates, key=lambda item: (item[0], -abs(item[1])))
        rows.append({
            "left": left_name,
            "right": right_name,
            "selected_lag_cycles": lag,
            "paired_cycle_count": len(left),
            "correlation": _rounded(correlation),
            "control": _circular_shift_control(left, right, correlation),
            "selection_note": "strongest exploratory lag among -1, 0, +1",
        })
    rows.sort(key=lambda row: (
        -abs(float(row["correlation"])), row["left"], row["right"]))
    return {
        "status": "exploratory_not_preregistered",
        "cycle_count": len(ordered_cycles),
        "pair_count": len(rows),
        "relationships": rows,
        "causal_interpretation_allowed": False,
    }


def monitor(rows: Iterable[Mapping[str, Any]], *,
            terminal_rows: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    admitted = []
    excluded_not_content_free = 0
    excluded_invalid = 0
    duplicate_count = 0
    seen = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            excluded_invalid += 1
            continue
        if raw.get("content_free") is not True:
            excluded_not_content_free += 1
            continue
        source = str(raw.get("source") or "")
        at = _finite(raw.get("at"))
        if not source or at is None:
            excluded_invalid += 1
            continue
        identity = (source, str(raw.get("event_ref") or ""), at)
        if identity in seen:
            duplicate_count += 1
            continue
        seen.add(identity)
        admitted.append(dict(raw))
    admitted.sort(key=lambda row: float(row["at"]))

    source_rows: dict[str, list[dict]] = defaultdict(list)
    metric_values: dict[str, dict[str, list[tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list))
    cycles: dict[str, dict[str, Any]] = {}
    vector_values: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    for row in admitted:
        source = str(row["source"])
        at = float(row["at"])
        source_rows[source].append(row)
        measurements = dict(row.get("measurements") or {})
        for name, raw_value in measurements.items():
            value = _finite(raw_value)
            if value is not None:
                metric_values[source][str(name)].append((at, value))
        cycle = _cycle_id(str(row.get("event_ref") or ""))
        if not cycle:
            continue
        item = cycles.setdefault(cycle, {
            "first_at": at, "last_at": at, "boundaries": set()})
        item["first_at"] = min(item["first_at"], at)
        item["last_at"] = max(item["last_at"], at)
        item["boundaries"].add(_boundary(row))
        for name, raw_value in measurements.items():
            value = _finite(raw_value)
            if value is not None:
                vector_values[cycle][f"{source}.{name}"].append(value)

    vectors = {
        cycle: {name: sum(values) / len(values)
                for name, values in metrics.items()}
        for cycle, metrics in vector_values.items()}

    sources = {}
    for source in sorted(EXPECTED_SOURCES | set(source_rows)):
        records = source_rows.get(source, [])
        timestamps = [float(row["at"]) for row in records]
        gaps = [right - left for left, right in zip(timestamps, timestamps[1:])]
        sources[source] = {
            "receipt_count": len(records),
            "available_count": sum(bool(row.get("available")) for row in records),
            "unavailable_count": sum(
                not bool(row.get("available")) for row in records),
            "first_at": _rounded(timestamps[0]) if timestamps else None,
            "latest_at": _rounded(timestamps[-1]) if timestamps else None,
            "inter_receipt_gap_s": _summary(gaps),
            "metrics": {
                name: {
                    "distribution": _summary(value for _, value in values),
                    "drift": _equal_half_drift(values),
                }
                for name, values in sorted(metric_values[source].items())},
        }

    terminals = {}
    for raw in terminal_rows:
        if not isinstance(raw, Mapping):
            continue
        kind = str(raw.get("kind") or "")
        if kind not in {"conversation_completed", "conversation_failed"}:
            continue
        cycle = str(raw.get("conversation_id") or "")
        if not cycle:
            continue
        terminals[cycle] = {
            "kind": kind,
            "error_type": (
                str(raw.get("error_type") or "")[:80]
                if kind == "conversation_failed" else ""),
        }

    expected_completed = {
        "arrival", "rhythm_arrival", "soma_arrival", "continuity",
        "assembly", "completion", "rhythm_completion", "soma_completion",
    }
    completed = []
    failed = []
    completed_without_rest_completion = []
    open_cycles = []
    for cycle, item in sorted(cycles.items(), key=lambda pair: pair[1]["first_at"]):
        boundaries = set(item["boundaries"])
        summary = {
            "cycle_ref": cycle,
            "first_at": _rounded(item["first_at"]),
            "last_at": _rounded(item["last_at"]),
            "observed_boundaries": sorted(boundaries),
        }
        if "completion" in boundaries:
            summary["missing_after_completion"] = sorted(
                expected_completed - boundaries)
            completed.append(summary)
        elif terminals.get(cycle, {}).get("kind") == "conversation_failed":
            summary["terminal_evidence"] = "conversation_failed"
            summary["error_type"] = terminals[cycle].get("error_type") or ""
            failed.append(summary)
        elif terminals.get(cycle, {}).get("kind") == "conversation_completed":
            summary["terminal_evidence"] = "conversation_completed"
            summary["missing_after_success"] = sorted(
                expected_completed - boundaries)
            completed_without_rest_completion.append(summary)
        else:
            summary["not_yet_observed"] = sorted(
                expected_completed - boundaries)
            open_cycles.append(summary)

    observed = {source for source, records in source_rows.items() if records}
    first_at = float(admitted[0]["at"]) if admitted else None
    last_at = float(admitted[-1]["at"]) if admitted else None
    missing_completed = sum(
        bool(item["missing_after_completion"]) for item in completed)
    missing_completed += len(completed_without_rest_completion)
    gate_reasons = [
        "candidate_not_preregistered",
        "exploratory_relationships_cannot_authorize_promotion",
        "matched_mismatched_and_sham_replay_not_attached",
    ]
    if EXPECTED_SOURCES - observed:
        gate_reasons.append("source_coverage_incomplete")
    if missing_completed:
        gate_reasons.append("completed_cycle_boundary_missingness_present")
    return {
        "schema_version": 1,
        "kind": "rest_stage1_longitudinal_monitor",
        "stream": {
            "receipt_count": len(admitted),
            "duplicate_count": duplicate_count,
            "excluded_not_content_free": excluded_not_content_free,
            "excluded_invalid": excluded_invalid,
            "first_at": _rounded(first_at),
            "last_at": _rounded(last_at),
            "observed_span_s": _rounded(
                last_at - first_at) if first_at is not None else None,
        },
        "coverage": {
            "expected_sources": sorted(EXPECTED_SOURCES),
            "observed_sources": sorted(observed),
            "not_yet_observed": sorted(EXPECTED_SOURCES - observed),
        },
        "sources": sources,
        "cycle_integrity": {
            "cycle_count": len(cycles),
            "completed_cycle_count": len(completed),
            "failed_cycle_count": len(failed),
            "open_or_interrupted_cycle_count": len(open_cycles),
            "completed_cycles_with_missing_boundaries": missing_completed,
            "completed": completed,
            "failed": failed,
            "completed_without_rest_completion": (
                completed_without_rest_completion),
            "open_or_interrupted": open_cycles,
        },
        "relationships": _relationships(cycles, vectors),
        "evidence_gate": {
            "monitoring_ready": bool(admitted and not (EXPECTED_SOURCES - observed)),
            "promotion_ready": False,
            "reasons": gate_reasons,
            "fixed_time_or_turn_threshold_used": False,
            "downstream_conduct_authorized": False,
        },
        "content_free": True,
    }


def _tail_json_rows(path: str | Path, maximum_bytes: int = 2_000_000) -> list:
    """Read a bounded ledger tail and return JSON objects only."""
    try:
        with Path(path).open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            start = max(0, size - maximum_bytes)
            handle.seek(start)
            data = handle.read()
        if start:
            data = data.split(b"\n", 1)[-1]
        rows = []
        for line in data.splitlines():
            try:
                value = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, TypeError, ValueError):
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows
    except OSError:
        return []


def monitor_path(path: str | Path, *,
                 terminal_path: str | Path | None = None) -> dict[str, Any]:
    rows = []
    try:
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    rows.append({})
                    continue
                rows.append(value)
    except OSError:
        rows = []
    terminals = _tail_json_rows(terminal_path) if terminal_path else []
    return monitor(rows, terminal_rows=terminals)


def monitor_junction_path(path: str | Path) -> dict[str, Any]:
    """Summarize durable scalar junction receipts without advancing state."""
    rows = [row for row in _tail_json_rows(path)
            if row.get("kind") == "rest_junction_projection"
            and row.get("content_free") is True]
    deltas = []
    shifts = []
    modes = defaultdict(int)
    applied = 0
    for row in rows:
        baseline = _finite(row.get("baseline"))
        output = _finite(row.get("output"))
        shift = _finite(row.get("applied_logit_shift"))
        if baseline is not None and output is not None:
            deltas.append(output - baseline)
        if shift is not None:
            shifts.append(shift)
        modes[str(row.get("effective_mode") or "unknown")] += 1
        applied += bool(row.get("applied"))
    latest = dict(rows[-1]) if rows else None
    return {
        "schema_version": 1,
        "kind": "rest_junction_history_monitor",
        "receipt_count": len(rows),
        "applied_count": applied,
        "not_applied_count": len(rows) - applied,
        "effective_mode_counts": dict(sorted(modes.items())),
        "salience_delta": _summary(deltas),
        "logit_shift": _summary(shifts),
        "latest": latest,
        "content_free": True,
    }


def monitor_competition(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate private DMN counterfactual receipts without candidate text.

    The actual and bypass projections were produced from the same queue at the
    same instant.  This monitor merely describes those durable receipts; it
    never reconstructs candidates, scores work, or advances the queue.
    """
    admitted = []
    excluded_not_content_free = 0
    excluded_invalid = 0
    for raw in rows:
        if not isinstance(raw, Mapping):
            excluded_invalid += 1
            continue
        if raw.get("kind") != "rest_attention_counterfactual":
            continue
        if raw.get("content_free") is not True:
            excluded_not_content_free += 1
            continue
        candidate_count = raw.get("candidate_count")
        try:
            candidate_count = max(0, int(candidate_count))
        except (TypeError, ValueError):
            excluded_invalid += 1
            continue
        admitted.append((dict(raw), candidate_count))

    cases = defaultdict(int)
    changes = {"changed": 0, "unchanged": 0, "unavailable": 0}
    candidate_counts = []
    actual_scores, bypass_scores = [], []
    actual_runners, bypass_runners = [], []
    actual_margins, bypass_margins = [], []
    field_deltas = []
    exact_identity = {"true": 0, "false": 0, "unavailable": 0}
    legacy_missing = defaultdict(int)
    latest = None
    latest_keys = (
        "at", "schema_version", "candidate_count", "competition_case",
        "bypass_competition_case", "winner_changed", "actual_winner_score",
        "bypass_winner_score", "actual_runner_up_score",
        "bypass_runner_up_score", "actual_winner_margin",
        "bypass_winner_margin", "field_delta", "bypass_exact_identity",
        "content_free",
    )
    for row, candidate_count in admitted:
        candidate_counts.append(float(candidate_count))
        case = str(row.get("competition_case") or "")
        if case not in {
                "no_candidate", "causally_ineligible", "one_candidate",
                "full_competition"}:
            case = (
                "no_candidate" if candidate_count == 0
                else "one_candidate" if candidate_count == 1
                else "full_competition")
        cases[case] += 1
        changed = row.get("winner_changed")
        if changed is True:
            changes["changed"] += 1
        elif changed is False:
            changes["unchanged"] += 1
        else:
            changes["unavailable"] += 1
        identity = row.get("bypass_exact_identity")
        if identity is True:
            exact_identity["true"] += 1
        elif identity is False:
            exact_identity["false"] += 1
        else:
            exact_identity["unavailable"] += 1

        values = {}
        for name, target in (
                ("actual_winner_score", actual_scores),
                ("bypass_winner_score", bypass_scores),
                ("actual_runner_up_score", actual_runners),
                ("bypass_runner_up_score", bypass_runners),
                ("actual_winner_margin", actual_margins),
                ("bypass_winner_margin", bypass_margins)):
            value = _finite(row.get(name))
            values[name] = value
            if value is not None:
                target.append(value)
            elif name not in row:
                legacy_missing[name] += 1
        actual = values["actual_winner_score"]
        bypass = values["bypass_winner_score"]
        if actual is not None and bypass is not None:
            field_deltas.append(actual - bypass)
        latest = {key: row.get(key) for key in latest_keys if key in row}

    return {
        "schema_version": 1,
        "kind": "rest_competition_telemetry_monitor",
        "receipt_count": len(admitted),
        "excluded_not_content_free": excluded_not_content_free,
        "excluded_invalid": excluded_invalid,
        "competition_case_counts": dict(sorted(cases.items())),
        "winner_change_counts": changes,
        "candidate_count": _summary(candidate_counts),
        "actual_winner_score": _summary(actual_scores),
        "bypass_winner_score": _summary(bypass_scores),
        "actual_runner_up_score": _summary(actual_runners),
        "bypass_runner_up_score": _summary(bypass_runners),
        "actual_winner_margin": _summary(actual_margins),
        "bypass_winner_margin": _summary(bypass_margins),
        "field_delta": {
            **_summary(field_deltas),
            "definition": "actual_winner_score_minus_bypass_winner_score",
        },
        "exact_bypass_identity_counts": exact_identity,
        "legacy_receipts_missing_fields": dict(sorted(legacy_missing.items())),
        "latest": latest,
        "replay_boundary": {
            "same_queue_same_timestamp_projection": True,
            "queue_mutated": False,
            "candidate_content_read": False,
            "bypass_recomputed_by_monitor": False,
        },
        "behavior_authority": False,
        "content_free": True,
    }


def monitor_competition_path(path: str | Path) -> dict[str, Any]:
    """Read a bounded private DMN-ledger tail for competition telemetry."""
    return monitor_competition(_tail_json_rows(path))


def monitor_narrative_probe_path(path: str | Path) -> dict[str, Any]:
    """Summarize blinded process-probe outcomes without reading source text."""
    rows = [row for row in _tail_json_rows(path)
            if row.get("kind") == "narrative_process_probe"
            and row.get("content_free") is True]
    conditions = defaultdict(lambda: {
        "attempt_count": 0, "accepted_count": 0,
        "committed_count": 0, "outcomes": defaultdict(int)})
    for row in rows:
        condition = str(row.get("condition") or "unavailable")[:96]
        bucket = conditions[condition]
        bucket["attempt_count"] += 1
        bucket["accepted_count"] += bool(row.get("accepted_appraisal"))
        bucket["committed_count"] += bool(row.get("committed"))
        bucket["outcomes"][str(
            row.get("appraisal_outcome") or "unknown")[:96]] += 1
    rendered = {}
    for condition, bucket in sorted(conditions.items()):
        count = bucket["attempt_count"]
        rendered[condition] = {
            "attempt_count": count,
            "accepted_count": bucket["accepted_count"],
            "committed_count": bucket["committed_count"],
            "accepted_fraction": _rounded(
                bucket["accepted_count"] / count) if count else None,
            "committed_fraction": _rounded(
                bucket["committed_count"] / count) if count else None,
            "outcomes": dict(sorted(bucket["outcomes"].items())),
        }
    return {
        "schema_version": 1,
        "kind": "narrative_process_probe_monitor",
        "attempt_count": len(rows),
        "conditions": rendered,
        "comparison": "descriptive_blinded_arms",
        "causal_interpretation_allowed": False,
        "promotion_threshold_applied": False,
        "content_free": True,
    }


def monitor_trace_recurrence_path(
        path: str | Path, projection_path: str | Path) -> dict[str, Any]:
    """Summarize P2 lifecycle and observe-only return projections."""
    rows = [row for row in _tail_json_rows(path)
            if row.get("kind") == "rest_trace_recurrence"
            and row.get("content_free") is True]
    projections = [row for row in _tail_json_rows(projection_path)
                   if row.get("kind") ==
                   "rest_trace_recurrence_projection"
                   and row.get("content_free") is True]
    stages, relations, conditions = defaultdict(int), defaultdict(int), \
        defaultdict(lambda: {
            "event_count": 0, "consequence_count": 0,
            "distinct_trace_digests": set()})
    trace_digests = set()
    for row in rows:
        stage = str(row.get("stage") or "unknown")[:96]
        relation = str(row.get("relation") or "unknown")[:96]
        condition = str(row.get("condition") or "unknown")[:96]
        trace_digest = str(row.get("trace_digest") or "")[:64]
        stages[stage] += 1
        relations[relation] += 1
        bucket = conditions[condition]
        bucket["event_count"] += 1
        bucket["consequence_count"] += bool(
            row.get("durable_consequence"))
        if trace_digest:
            bucket["distinct_trace_digests"].add(trace_digest)
            trace_digests.add(trace_digest)
    rendered_conditions = {
        condition: {
            "event_count": bucket["event_count"],
            "consequence_count": bucket["consequence_count"],
            "distinct_trace_count": len(bucket["distinct_trace_digests"]),
        }
        for condition, bucket in sorted(conditions.items())
    }
    field_changed = sum(bool(row.get("rest_field_state_changed"))
                        for row in projections)
    return {
        "schema_version": 1,
        "kind": "rest_trace_recurrence_monitor",
        "event_count": len(rows),
        "distinct_trace_count": len(trace_digests),
        "durable_consequence_count": sum(
            bool(row.get("durable_consequence")) for row in rows),
        "stage_counts": dict(sorted(stages.items())),
        "relation_counts": dict(sorted(relations.items())),
        "conditions": rendered_conditions,
        "observe_only_projection_count": len(projections),
        "rest_field_state_change_count": field_changed,
        "field_influence": False,
        "causal_interpretation_allowed": False,
        "promotion_threshold_applied": False,
        "content_free": True,
    }
