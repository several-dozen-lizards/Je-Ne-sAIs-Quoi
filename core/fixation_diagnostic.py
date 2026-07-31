"""Content-free shadow diagnostics for fascination versus mechanical rut.

This module reads salience-observatory receipts; the organism never imports it.
It evaluates circulation shape, never subject matter.  No result is consumed by
the field, and every candidate/source identity is one-way hashed on projection.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 5


def _unit(value: Any) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0


def _ref(value: Any, prefix: str) -> str:
    digest = hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _time(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _range(value: float, evidence_n: int) -> dict[str, float]:
    """Bounded uncertainty band; it narrows with independent observations."""
    value = _unit(value)
    width = min(.38, .52 / math.sqrt(max(1, int(evidence_n))))
    return {
        "low": round(max(0.0, value - width), 6),
        "mid": round(value, 6),
        "high": round(min(1.0, value + width), 6),
    }


def _entropy_share(counts: Counter) -> float:
    total = sum(counts.values())
    if total <= 0 or len(counts) <= 1:
        return 0.0
    entropy = -sum(
        (count / total) * math.log(count / total)
        for count in counts.values() if count)
    return _unit(entropy / math.log(len(counts)))


def _candidate(record: Mapping[str, Any]) -> Mapping[str, Any]:
    return dict(record.get("candidate") or {})


def _numeric_leaves(value: Any, prefix: str = "") -> dict[str, float]:
    """Flatten only numeric/bool instrument values; labels never participate."""
    leaves = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            leaves.update(_numeric_leaves(
                item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, bool):
        leaves[prefix] = 1.0 if value else 0.0
    elif isinstance(value, (int, float)) and math.isfinite(float(value)):
        leaves[prefix] = float(value)
    return leaves


def _mean_movement(vectors: list[dict[str, float]]) -> float:
    movements = []
    for before, after in zip(vectors, vectors[1:]):
        keys = set(before) | set(after)
        if not keys:
            continue
        movements.append(sum(
            min(1.0, abs(after.get(key, 0.0) - before.get(key, 0.0)))
            for key in keys) / len(keys))
    return _unit(sum(movements) / len(movements)) if movements else 0.0


class FixationDiagnostic:
    """Pure projection over one persona's append-only observatory history."""

    RECORD_TYPES = frozenset({
        "candidate_offered",
        "candidates_merged",
        "candidate_won",
        "candidate_requeued",
        "candidate_expired",
        "candidate_withdrawn",
        "discharge",
        "field_effect",
        "play_attention_counterfactual",
    })

    @classmethod
    def project(cls, records: Iterable[Mapping[str, Any]], *,
                persona: str, now: float | None = None) -> dict:
        ordered = sorted(
            (dict(record) for record in records if isinstance(record, Mapping)),
            key=lambda record: (_time(record.get("tick")) or 0.0,
                                int(record.get("seq") or 0)))
        candidates: dict[str, dict] = defaultdict(lambda: {
            "appearances": 0, "offers": 0, "merges": 0, "wins": 0,
            "requeues": 0, "discharges": 0, "terminal": 0,
            "content_forms": set(), "outcomes": set(), "response_forms": set(),
            "sources": Counter(), "satiety_rises": 0, "satiety_total": 0.0,
            "post_satiety_wins": 0, "first_ts": None, "last_ts": None,
            "last_satiety_ts": None, "salience_totals": [],
            "competition_ratios": [], "competition_entropies": [],
            "winner_margins": [], "state_vectors": [],
            "release_edges": Counter(),
            "last_win_salience": None, "last_win_ratio": None,
            "pending_satiety_baseline": None, "satiety_responses": [],
        })
        global_wins, global_offers = Counter(), Counter()
        winner_sequence = []
        type_counts = Counter()
        candidate_sources: dict[str, set[str]] = defaultdict(set)
        response_forms: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "occurrences": 0,
            "candidate_keys": set(),
            "outcomes": set(),
        })
        play_counterfactuals = {
            "record_count": 0, "informative_count": 0,
            "changed_winner_count": 0, "narrowed_margin_count": 0,
            "widened_margin_count": 0, "margin_deltas": [],
        }

        for record in ordered:
            kind = str(record.get("type") or "")
            type_counts[kind] += 1
            if kind == "play_attention_counterfactual":
                play_counterfactuals["record_count"] += 1
                if int(record.get("eligible_count") or 0) > 0:
                    play_counterfactuals["informative_count"] += 1
                    play_counterfactuals["changed_winner_count"] += int(
                        bool(record.get("changed_winner")))
                    delta = float(record.get("margin_delta") or 0.0)
                    play_counterfactuals["margin_deltas"].append(delta)
                    play_counterfactuals[
                        "narrowed_margin_count"] += int(delta < 0.0)
                    play_counterfactuals[
                        "widened_margin_count"] += int(delta > 0.0)
            candidate = _candidate(record)
            key = str(candidate.get("key") or record.get(
                "candidate_key") or "")
            if not key:
                continue
            row = candidates[key]
            ts = _time(record.get("tick"))
            if ts is not None:
                row["first_ts"] = ts if row["first_ts"] is None else min(
                    row["first_ts"], ts)
                row["last_ts"] = ts if row["last_ts"] is None else max(
                    row["last_ts"], ts)
            source = str(candidate.get("source") or candidate.get("kind")
                         or "unknown")
            row["sources"][source] += 1
            if candidate:
                candidate_sources[key].add(source)
            responsiveness = dict(record.get("responsiveness") or {})
            release_edge = str(responsiveness.get("release_edge") or "")
            if release_edge:
                row["release_edges"][release_edge] += 1
            form = str(candidate.get("content_digest") or "")
            if form:
                row["content_forms"].add(_ref(form, "form"))
            if candidate.get("salience_total") is not None:
                try:
                    total = float(candidate["salience_total"])
                    if math.isfinite(total):
                        row["salience_totals"].append(total)
                except (TypeError, ValueError):
                    pass

            if kind in {"candidate_offered", "candidates_merged",
                        "candidate_won", "candidate_requeued"}:
                row["appearances"] += 1
            if kind == "candidate_offered":
                row["offers"] += 1
                global_offers[source] += 1
            elif kind == "candidates_merged":
                row["merges"] += 1
            elif kind == "candidate_won":
                row["wins"] += 1
                global_wins[source] += 1
                winner_sequence.append(key)
                geometry = dict(responsiveness.get("competition") or {})
                if geometry:
                    current_ratio = _unit(
                        geometry.get("runner_up_ratio"))
                    row["competition_ratios"].append(current_ratio)
                    row["competition_entropies"].append(_unit(
                        geometry.get("salience_entropy")))
                    try:
                        row["winner_margins"].append(float(
                            geometry.get("winner_margin") or 0.0))
                    except (TypeError, ValueError):
                        pass
                else:
                    current_ratio = 0.0
                try:
                    current_salience = float(
                        candidate.get("salience_total") or 0.0)
                except (TypeError, ValueError):
                    current_salience = 0.0
                if row["pending_satiety_baseline"] is not None:
                    baseline_salience, baseline_ratio = \
                        row["pending_satiety_baseline"]
                    row["satiety_responses"].append(_unit(
                        .55 * max(0.0, baseline_salience - current_salience)
                        + .45 * max(0.0, current_ratio - baseline_ratio)))
                    row["pending_satiety_baseline"] = None
                row["last_win_salience"] = current_salience
                row["last_win_ratio"] = current_ratio
                state = _numeric_leaves(responsiveness.get("state") or {})
                if state:
                    row["state_vectors"].append(state)
                if (row["last_satiety_ts"] is not None and ts is not None
                        and ts >= row["last_satiety_ts"]):
                    row["post_satiety_wins"] += 1
            elif kind == "candidate_requeued":
                row["requeues"] += 1
            elif kind == "discharge":
                row["discharges"] += 1
                row["outcomes"].add(str(record.get("outcome") or "unknown"))
                response = str(record.get("model_response_digest") or "")
                if response:
                    row["response_forms"].add(_ref(response, "effect"))
                    form = response_forms[response]
                    form["occurrences"] += 1
                    form["candidate_keys"].add(key)
                    form["outcomes"].add(
                        str(record.get("outcome") or "unknown"))
            elif kind in {"candidate_expired", "candidate_withdrawn"}:
                row["terminal"] += 1
            elif kind == "field_effect" and str(
                    record.get("quantity") or "").startswith(
                        "source_satiety:"):
                prior = _unit(record.get("prior"))
                new = _unit(record.get("new"))
                if new > prior:
                    row["satiety_rises"] += 1
                    row["satiety_total"] += new - prior
                    row["last_satiety_ts"] = ts
                    if row["last_win_salience"] is not None:
                        row["pending_satiety_baseline"] = (
                            row["last_win_salience"],
                            row["last_win_ratio"] or 0.0)

        win_diversity = _entropy_share(global_wins)
        offer_diversity = _entropy_share(global_offers)
        total_wins = sum(global_wins.values())
        total_offers = sum(global_offers.values())
        projections = []
        for key, row in candidates.items():
            recurrence_n = row["appearances"] + row["discharges"]
            if recurrence_n < 2:
                continue
            forms = len(row["content_forms"])
            effects = max(len(row["outcomes"]), len(row["response_forms"]))
            recurrence = _unit(
                1.0 - math.exp(-max(0, recurrence_n - 1) / 3.0))
            form_change = _unit((forms - 1) / max(1, row["appearances"] - 1))
            consequence_change = _unit(
                (effects - 1) / max(1, row["discharges"] - 1))
            requeue_loop = _unit(
                row["requeues"] / max(1, row["wins"] + row["requeues"]))
            win_monopoly = _unit(
                row["wins"] / max(1, total_wins))
            satiety_bypass = (
                _unit(row["post_satiety_wins"] / max(1, row["wins"]))
                if row["satiety_rises"] else 0.0)
            terminal_flow = _unit(
                row["terminal"] / max(1, row["wins"] + row["terminal"]))
            competition = _unit(.55 * win_diversity + .45 * offer_diversity)
            if row["competition_ratios"]:
                local_competition = _unit(
                    .55 * (sum(row["competition_ratios"])
                           / len(row["competition_ratios"]))
                    + .45 * (sum(row["competition_entropies"])
                             / max(1, len(row["competition_entropies"]))))
            else:
                local_competition = competition
            win_positions = [
                index for index, winner in enumerate(winner_sequence)
                if winner == key]
            interrupted_returns = sum(
                1 for left, right in zip(win_positions, win_positions[1:])
                if any(winner != key
                       for winner in winner_sequence[left + 1:right]))
            interruption_response = _unit(
                interrupted_returns / max(1, len(win_positions) - 1))
            salience_values = row["salience_totals"]
            intensity_response = 0.0
            if len(salience_values) > 1:
                mean = sum(salience_values) / len(salience_values)
                intensity_response = _unit(
                    (max(salience_values) - min(salience_values))
                    / max(.05, abs(mean)))
            satiety_response = (
                sum(row["satiety_responses"])
                / len(row["satiety_responses"])
                if row["satiety_responses"] else (
                    1.0 - satiety_bypass if row["satiety_rises"] else .5))
            satiety_insensitivity = (
                1.0 - satiety_response if row["satiety_rises"] else .5)
            release_successes = (
                row["release_edges"]["cooled_out"]
                + row["release_edges"]["withdrawn"]
                + row["release_edges"]["discharge"])
            release_attempts = release_successes + row["release_edges"]["requeued"]
            release_response = (
                _unit(release_successes / release_attempts)
                if release_attempts else (
                    terminal_flow if row["terminal"] else
                    _unit(row["discharges"] / max(1, row["wins"]))))
            state_response = _mean_movement(row["state_vectors"])

            # Novelty is corroborating evidence, never an innocence test.
            # Deliberately repetitive fascinations can be highly responsive.
            responsiveness = _unit(
                .23 * local_competition + .20 * interruption_response
                + .18 * satiety_response + .15 * release_response
                + .07 * intensity_response + .07 * state_response
                + .06 * consequence_change + .04 * form_change)
            rut = _unit(recurrence * (
                .27 * win_monopoly + .22 * requeue_loop
                + .20 * satiety_insensitivity
                + .16 * (1.0 - interruption_response)
                + .10 * (1.0 - release_response)
                + .05 * (1.0 - local_competition)))
            evidence_n = max(1, recurrence_n + row["discharges"]
                             + row["satiety_rises"])
            if recurrence_n < 4 or row["wins"] < 2:
                classification = "insufficient_evidence"
            elif rut >= .62 and responsiveness <= .38:
                classification = "mechanical_rut_risk"
            elif recurrence >= .45 and responsiveness >= .48 and rut <= .48:
                classification = "responsive_fixation"
            else:
                classification = "mixed"
            projections.append({
                "candidate_ref": _ref(key, "candidate"),
                "classification": classification,
                "evidence_count": evidence_n,
                "ranges": {
                    "recurrence": _range(recurrence, evidence_n),
                    "responsiveness": _range(responsiveness, evidence_n),
                    "mechanical_rut_risk": _range(rut, evidence_n),
                    "competition": _range(competition, max(
                        1, total_wins + total_offers)),
                    "local_competition": _range(
                        local_competition, max(
                            1, len(row["competition_ratios"]))),
                    "satiety_bypass": _range(
                        satiety_bypass, max(1, row["satiety_rises"])),
                    "satiety_response": _range(
                        satiety_response, max(
                            1, len(row["satiety_responses"]))),
                    "interruption_response": _range(
                        interruption_response, max(1, row["wins"] - 1)),
                    "release_response": _range(
                        release_response, max(
                            1, row["terminal"] + row["discharges"])),
                    "state_response": _range(
                        state_response, max(1, len(row["state_vectors"]) - 1)),
                },
                "receipts": {
                    "appearances": row["appearances"],
                    "wins": row["wins"],
                    "requeues": row["requeues"],
                    "discharges": row["discharges"],
                    "terminal_movements": row["terminal"],
                    "distinct_forms": forms,
                    "distinct_consequences": effects,
                    "interrupted_returns": interrupted_returns,
                    "satiety_rises": row["satiety_rises"],
                    "post_satiety_wins": row["post_satiety_wins"],
                    "satiety_response_samples": len(
                        row["satiety_responses"]),
                    "competition_snapshots": len(
                        row["competition_ratios"]),
                    "state_snapshots": len(row["state_vectors"]),
                    "release_edges": dict(row["release_edges"]),
                    "span_s": round(max(
                        0.0, (row["last_ts"] or 0.0)
                        - (row["first_ts"] or 0.0)), 6),
                },
            })
        projections.sort(key=lambda item: (
            -item["ranges"]["mechanical_rut_risk"]["mid"],
            -item["ranges"]["recurrence"]["mid"],
            item["candidate_ref"]))
        cross_candidate_forms = []
        for response, row in response_forms.items():
            candidate_keys = set(row["candidate_keys"])
            if row["occurrences"] < 2 or len(candidate_keys) < 2:
                continue
            sources = set()
            for key in candidate_keys:
                sources.update(candidate_sources.get(key) or {"unknown"})
            cross_candidate_forms.append({
                "response_ref": _ref(response, "response"),
                "occurrences": row["occurrences"],
                "distinct_candidate_count": len(candidate_keys),
                "distinct_source_count": len(sources),
                "distinct_outcome_count": len(row["outcomes"]),
                "exact_normalized_form": True,
                "semantic_judgment": False,
                "applied": False,
            })
        cross_candidate_forms.sort(key=lambda item: (
            -item["distinct_candidate_count"],
            -item["occurrences"],
            item["response_ref"]))
        return {
            "schema": SCHEMA_VERSION,
            "persona": str(persona),
            "ownership": "persona_private",
            "mode": "shadow",
            "semantic_judgment": False,
            "topic_desirability_scored": False,
            "repetition_scored_as_pathology": False,
            "applied": False,
            "downstream_channels_touched": [],
            "external_effects": False,
            "record_count": len(ordered),
            "record_types": dict(sorted(type_counts.items())),
            "field_ranges": {
                "winner_diversity": _range(
                    win_diversity, max(1, total_wins)),
                "offer_diversity": _range(
                    offer_diversity, max(1, total_offers)),
            },
            "cross_candidate_response_recurrence": {
                "mode": "shadow",
                "exact_normalized_form_only": True,
                "semantic_judgment": False,
                "applied": False,
                "downstream_channels_touched": [],
                "forms": cross_candidate_forms[:24],
            },
            "candidates": projections[:24],
            "classification_counts": dict(Counter(
                item["classification"] for item in projections)),
            "play_attention_counterfactual": {
                "mode": "shadow",
                "applied": False,
                "eligibility": "explicit_witnessed_play_affinity",
                "record_count": play_counterfactuals["record_count"],
                "informative_count": play_counterfactuals[
                    "informative_count"],
                "changed_winner_count": play_counterfactuals[
                    "changed_winner_count"],
                "narrowed_margin_count": play_counterfactuals[
                    "narrowed_margin_count"],
                "widened_margin_count": play_counterfactuals[
                    "widened_margin_count"],
                "mean_margin_delta": round(
                    sum(play_counterfactuals["margin_deltas"])
                    / max(1, len(play_counterfactuals["margin_deltas"])), 6),
                "downstream_channels_touched": [],
            },
            "interpretation": (
                "Discrepancy is not dysfunction. This projection compares "
                "responsiveness and circulation only; repetition and novelty "
                "are not verdicts. It never evaluates what an interest is "
                "about or whether it is useful to another person."),
        }
