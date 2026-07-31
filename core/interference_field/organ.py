"""A shadow sensorium for temporal relationships among otherwise neutral events.

The field is deliberately presemantic: sources retain provenance, never assigned
qualities. Three leaky traces at geometrically separated timescales turn event
history into opponent axes. A rectified (squared) readout makes disagreement
causally measurable without connecting it to attention, memory, or prompts.
"""
import json
import hashlib
import itertools
import math
import os
import random
import time
import uuid
from collections import deque

from .participation_phase import (
    normalize_participation,
    project_participation_phase,
)


SCHEMA_VERSION = 1
DEFAULT_TIMESCALES_S = (2.0, 8.0, 32.0)


def _finite(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


class InterferenceFieldOrgan:
    """Event-driven, persisted, replayable shadow field.

    `observe` is the only live input door. `project` is pure and is also used by
    the experiment harness, so controls exercise the same mathematics as live
    state. The organ owns no timer; elapsed time itself advances the traces.
    """

    def __init__(self, persona_dir: str, timescales_s=None, *, clock=time.time):
        self.dir = os.path.join(persona_dir, "body", "interference_field")
        os.makedirs(self.dir, exist_ok=True)
        self.state_path = os.path.join(self.dir, "state.json")
        self.events_path = os.path.join(self.dir, "events.jsonl")
        self.attention_probes_path = os.path.join(
            self.dir, "attention_probes.jsonl")
        self.clock = clock
        requested = tuple(timescales_s or DEFAULT_TIMESCALES_S)
        if len(requested) != 3 or any(_finite(v) <= 0 for v in requested):
            raise ValueError("interference field requires three positive timescales")
        self.timescales_s = tuple(sorted(_finite(v) for v in requested))
        loaded = self._load()
        stored_scales = tuple(loaded.get("timescales_s") or ())
        if len(stored_scales) == 3 and all(_finite(v) > 0 for v in stored_scales):
            self.timescales_s = tuple(sorted(_finite(v) for v in stored_scales))
        self.traces = [_finite(v) for v in loaded.get("traces", (0, 0, 0))][:3]
        self.traces += [0.0] * (3 - len(self.traces))
        self.last_ts = loaded.get("last_ts")
        self.event_count = int(loaded.get("event_count") or 0)
        self.sources = dict(loaded.get("sources") or {})
        self.source_traces = {}
        for name, values in dict(loaded.get("source_traces") or {}).items():
            traces = [_finite(value) for value in list(values or ())[:3]]
            traces += [0.0] * (3 - len(traces))
            self.source_traces[str(name)[:96]] = traces
        self.last_event_ref = str(loaded.get("last_event_ref") or "")

    def _load(self):
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def project(events, *, timescales_s=DEFAULT_TIMESCALES_S, at=None):
        """Replay timestamped `{ts, magnitude}` events without persistence."""
        scales = tuple(sorted(float(v) for v in timescales_s))
        traces = [0.0, 0.0, 0.0]
        last = None
        count = 0
        for event in sorted(events, key=lambda item: float(item["ts"])):
            ts = float(event["ts"])
            if last is not None:
                dt = max(0.0, ts - last)
                traces = [v * math.exp(-dt / tau)
                          for v, tau in zip(traces, scales)]
            magnitude = max(0.0, _finite(event.get("magnitude"), 1.0))
            traces = [v + magnitude for v in traces]
            last = ts
            count += 1
        target = last if at is None else float(at)
        if last is not None and target > last:
            dt = target - last
            traces = [v * math.exp(-dt / tau)
                      for v, tau in zip(traces, scales)]
        return InterferenceFieldOrgan._snapshot(traces, scales, count, target)

    @staticmethod
    def _snapshot(traces, scales, count, at):
        fast, medium, slow = traces
        axis_1 = fast - medium
        axis_2 = medium - slow
        axis_3 = fast + medium - 2.0 * slow
        energy = axis_1 * axis_1 + axis_2 * axis_2
        total = fast + medium + slow
        agreement = 1.0 if total <= 1e-12 else max(
            0.0, 1.0 - (abs(axis_1) + abs(axis_2)) / total)
        angle = math.atan2(axis_2, axis_1) if energy > 1e-18 else 0.0
        return {
            "schema": SCHEMA_VERSION,
            "mode": "shadow",
            "downstream_channels_touched": [],
            "timescales_s": list(scales),
            "traces": [round(v, 9) for v in traces],
            "axes": [round(axis_1, 9), round(axis_2, 9), round(axis_3, 9)],
            "nonlinear_energy": round(energy, 9),
            "field_angle_rad": round(angle, 9),
            "agreement": round(agreement, 9),
            "event_count": int(count),
            "projected_at": at,
        }

    @staticmethod
    def _relational_overlap(source_traces):
        values = list(source_traces.values())
        if len(values) < 2:
            return [0.0, 0.0, 0.0]
        overlap = []
        for index in range(3):
            axis = [max(0.0, float(row[index])) for row in values]
            sum_sq = sum(value * value for value in axis)
            denominator = (len(axis) - 1) * sum_sq
            cross = sum(axis) ** 2 - sum_sq
            overlap.append(0.0 if denominator <= 1e-18 else
                           max(0.0, min(1.0, cross / denominator)))
        return [round(value, 9) for value in overlap]

    @staticmethod
    def project_relational(events, *, timescales_s=DEFAULT_TIMESCALES_S,
                           at=None):
        """Replay per-source traces; source names carry no assigned quality."""
        scales = tuple(sorted(float(value) for value in timescales_s))
        source_traces, last = {}, None
        for event in sorted(events, key=lambda item: float(item["ts"])):
            ts = float(event["ts"])
            if last is not None:
                dt = max(0.0, ts - last)
                for name in source_traces:
                    source_traces[name] = [
                        value * math.exp(-dt / tau)
                        for value, tau in zip(source_traces[name], scales)]
            label = str(event.get("source") or "unknown")[:96]
            source_traces.setdefault(label, [0.0, 0.0, 0.0])
            amount = max(0.0, _finite(event.get("magnitude"), 1.0))
            source_traces[label] = [value + amount
                                    for value in source_traces[label]]
            last = ts
        target = last if at is None else float(at)
        if last is not None and target > last:
            dt = target - last
            for name in source_traces:
                source_traces[name] = [
                    value * math.exp(-dt / tau)
                    for value, tau in zip(source_traces[name], scales)]
        return {
            "relational_overlap": InterferenceFieldOrgan._relational_overlap(
                source_traces),
            "source_count": len(source_traces),
        }

    def snapshot(self, now=None):
        target = _finite(self.clock() if now is None else now)
        traces = list(self.traces)
        if self.last_ts is not None and target > float(self.last_ts):
            dt = target - float(self.last_ts)
            traces = [v * math.exp(-dt / tau)
                      for v, tau in zip(traces, self.timescales_s)]
            source_traces = {
                name: [value * math.exp(-dt / tau)
                       for value, tau in zip(values, self.timescales_s)]
                for name, values in self.source_traces.items()}
        else:
            source_traces = {name: list(values)
                             for name, values in self.source_traces.items()}
        result = self._snapshot(
            traces, self.timescales_s, self.event_count, target)
        result.update({"sources": dict(self.sources),
                       "relational_overlap": self._relational_overlap(
                           source_traces),
                       "relational_source_count": len(source_traces),
                       "last_event_ref": self.last_event_ref})
        return result

    def recent_events(self, limit=256):
        """Read a bounded, deduplicated replay window without mutating state."""
        rows = deque(maxlen=max(2, min(2048, int(limit))))
        try:
            with open(self.events_path, encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(row, dict) and "ts" in row:
                        rows.append(row)
        except OSError:
            return [], 0
        unique, seen, duplicates = [], set(), 0
        for row in rows:
            ref = str(row.get("event_ref") or "")
            key = ref or (row.get("ts"), row.get("source"), row.get("magnitude"))
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            unique.append(row)
        return unique, duplicates

    @staticmethod
    def _carry(gaps, scales):
        if not gaps:
            return [0.0 for _ in scales]
        return [round(sum(math.exp(-gap / tau) for gap in gaps) / len(gaps), 6)
                for tau in scales]

    @staticmethod
    def _quantile(values, fraction):
        ordered = sorted(float(value) for value in values)
        if not ordered:
            return None
        position = max(0.0, min(1.0, float(fraction))) * (len(ordered) - 1)
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    @staticmethod
    def _control_distribution(observed, samples):
        """Describe where an observed three-scale vector falls in null samples."""
        count = len(samples)
        result = []
        for axis, actual in enumerate(observed):
            values = [float(sample[axis]) for sample in samples]
            greater_or_equal = sum(value >= float(actual) for value in values)
            below_or_equal = sum(value <= float(actual) for value in values)
            result.append({
                "observed": round(float(actual), 9),
                "null_mean": round(sum(values) / count, 9) if count else None,
                "null_p05": (round(InterferenceFieldOrgan._quantile(
                    values, 0.05), 9) if count else None),
                "null_p95": (round(InterferenceFieldOrgan._quantile(
                    values, 0.95), 9) if count else None),
                "empirical_percentile": (round(below_or_equal / count, 6)
                                         if count else None),
                # Add-one correction prevents a finite permutation ensemble
                # from reporting impossible certainty.
                "upper_tail_probability": (round(
                    (greater_or_equal + 1) / (count + 1), 6)
                    if count else None),
            })
        return result

    @staticmethod
    def _session_gap_boundary(gaps):
        """Find the strongest multiplicative break in positive observed gaps."""
        positive = sorted(set(float(gap) for gap in gaps if float(gap) > 0.0))
        if len(positive) < 2:
            return None
        ratios = [right / left for left, right in zip(positive, positive[1:])]
        index = max(range(len(ratios)), key=ratios.__getitem__)
        return math.sqrt(positive[index] * positive[index + 1])

    def calibration(self, limit=256):
        """Replay one event window through data-derived geometric families."""
        events, duplicates = self.recent_events(limit)
        ordered = sorted(events, key=lambda row: float(row["ts"]))
        gaps = [max(0.0, float(right["ts"]) - float(left["ts"]))
                for left, right in zip(ordered, ordered[1:])
                if float(right["ts"]) > float(left["ts"])]
        if gaps:
            sorted_gaps = sorted(gaps)
            middle = len(sorted_gaps) // 2
            median = (sorted_gaps[middle] if len(sorted_gaps) % 2 else
                      (sorted_gaps[middle - 1] + sorted_gaps[middle]) / 2.0)
        else:
            median = self.timescales_s[1]
        median = max(0.001, median)
        families = {
            "current": tuple(self.timescales_s),
            "cadence": (median / 4.0, median, median * 4.0),
            "weather": (median, median * 4.0, median * 16.0),
        }
        at = float(ordered[-1]["ts"]) if ordered else self.clock()
        replay = {}
        for name, scales in families.items():
            projection = self.project(ordered, timescales_s=scales, at=at)
            relational = self.project_relational(
                ordered, timescales_s=scales, at=at)
            replay[name] = {
                "timescales_s": [round(value, 6) for value in scales],
                "mean_carry_to_next_event": self._carry(gaps, scales),
                "axes": projection["axes"],
                "nonlinear_energy": projection["nonlinear_energy"],
                "relational_overlap": relational["relational_overlap"],
            }
        dyad_names = {"conversation:human_arrival",
                      "conversation:persona_completion"}
        dyad = [row for row in ordered if str(row.get("source")) in dyad_names]
        transitions, transition_gaps = {}, {}
        for left, right in zip(dyad, dyad[1:]):
            edge = f"{left.get('source')} -> {right.get('source')}"
            gap = max(0.0, float(right["ts"]) - float(left["ts"]))
            transitions[edge] = transitions.get(edge, 0) + 1
            transition_gaps.setdefault(edge, []).append(gap)
        transition_receipts = {}
        for edge, values in transition_gaps.items():
            ordered_values = sorted(values)
            center = len(values) // 2
            med = (ordered_values[center] if len(values) % 2 else
                   (ordered_values[center - 1] + ordered_values[center]) / 2.0)
            transition_receipts[edge] = {
                "count": len(values), "minimum_s": round(min(values), 6),
                "median_s": round(med, 6),
                "maximum_s": round(max(values), 6)}
        cadence_scales = families["cadence"]
        actual_rel = self.project_relational(
            dyad, timescales_s=cadence_scales, at=at)
        labels = [row.get("source") for row in dyad]
        shuffled_labels = list(labels)
        random.Random(1701).shuffle(shuffled_labels)
        source_shuffled = [dict(row, source=label)
                           for row, label in zip(dyad, shuffled_labels)]
        source_control = self.project_relational(
            source_shuffled, timescales_s=cadence_scales, at=at)
        dyad_gaps = [float(right["ts"]) - float(left["ts"])
                     for left, right in zip(dyad, dyad[1:])]
        shuffled_gaps = list(dyad_gaps)
        random.Random(2903).shuffle(shuffled_gaps)
        timing_shuffled = []
        if dyad:
            cursor = float(dyad[0]["ts"])
            timing_shuffled.append(dict(dyad[0], ts=cursor))
            for row, gap in zip(dyad[1:], shuffled_gaps):
                cursor += gap
                timing_shuffled.append(dict(row, ts=cursor))
        timing_control = self.project_relational(
            timing_shuffled, timescales_s=cadence_scales,
            at=(float(timing_shuffled[-1]["ts"])
                if timing_shuffled else at))
        # Use a bounded, deterministic ensemble: reproducible receipts without
        # allowing calibration work to grow with wall-clock time.
        permutation_count = min(256, max(32, len(dyad) * 4))
        source_samples, timing_samples = [], []
        for sample_index in range(permutation_count):
            sample_labels = list(labels)
            random.Random(1701 + sample_index * 7919).shuffle(sample_labels)
            source_projection = self.project_relational(
                [dict(row, source=label)
                 for row, label in zip(dyad, sample_labels)],
                timescales_s=cadence_scales, at=at)
            source_samples.append(source_projection["relational_overlap"])

            sample_gaps = list(dyad_gaps)
            random.Random(2903 + sample_index * 7919).shuffle(sample_gaps)
            sample_events = []
            if dyad:
                cursor = float(dyad[0]["ts"])
                sample_events.append(dict(dyad[0], ts=cursor))
                for row, gap in zip(dyad[1:], sample_gaps):
                    cursor += gap
                    sample_events.append(dict(row, ts=cursor))
            timing_projection = self.project_relational(
                sample_events, timescales_s=cadence_scales,
                at=(float(sample_events[-1]["ts"]) if sample_events else at))
            timing_samples.append(timing_projection["relational_overlap"])

        session_boundary = self._session_gap_boundary(dyad_gaps)
        sessions, current_session = [], []
        for index, row in enumerate(dyad):
            if (index and session_boundary is not None and
                    float(row["ts"]) - float(dyad[index - 1]["ts"]) >
                    session_boundary):
                sessions.append(current_session)
                current_session = []
            current_session.append(row)
        if current_session:
            sessions.append(current_session)
        session_receipts = [{
            "event_count": len(session),
            "duration_s": round(float(session[-1]["ts"]) -
                                float(session[0]["ts"]), 6),
        } for session in sessions]
        return {
            "schema": 1,
            "mode": "read_only_replay",
            "downstream_channels_touched": [],
            "event_window": len(ordered),
            "duplicate_receipts_ignored": duplicates,
            "intervals": {
                "count": len(gaps),
                "minimum_s": round(min(gaps), 6) if gaps else None,
                "median_s": round(median, 6) if gaps else None,
                "maximum_s": round(max(gaps), 6) if gaps else None,
            },
            "families": replay,
            "participation_phase": self.participation_phase_probe(
                limit=limit, now=at),
            "relational": {
                "event_window": len(dyad),
                "source_counts": {
                    name: sum(1 for row in dyad if row.get("source") == name)
                    for name in sorted(dyad_names)},
                "transitions": transition_receipts,
                "cadence_overlap": actual_rel["relational_overlap"],
                "source_shuffled_overlap": source_control[
                    "relational_overlap"],
                "timing_shuffled_overlap": timing_control[
                    "relational_overlap"],
                "permutation_lab": {
                    "sample_count": permutation_count,
                    "source_label_null": self._control_distribution(
                        actual_rel["relational_overlap"], source_samples),
                    "interval_order_null": self._control_distribution(
                        actual_rel["relational_overlap"], timing_samples),
                },
                "sessions": {
                    "method": "largest_multiplicative_gap_break",
                    "boundary_s": (round(session_boundary, 6)
                                   if session_boundary is not None else None),
                    "count": len(sessions),
                    "spans": session_receipts,
                },
                "controls_ready": len(dyad) >= 4 and len(set(labels)) >= 2,
            },
        }

    @staticmethod
    def _temporal_profile(age_s, scales):
        weights = [math.exp(-max(0.0, float(age_s)) / float(tau))
                   for tau in scales]
        total = sum(weights)
        return ([value / total for value in weights] if total > 1e-18
                else [0.0 for _ in scales])

    @staticmethod
    def _field_profile(traces):
        positive = [max(0.0, float(value)) for value in traces]
        total = sum(positive)
        profile = ([value / total for value in positive] if total > 1e-18
                   else [1.0 / len(positive) for _ in positive])
        # One neutral event adds one unit to every scale. Mean trace therefore
        # has a natural unit without a fitted gain. Silence tends continuously
        # to zero; repeated/overlapping history saturates rather than exploding.
        presence = 1.0 - math.exp(
            -total / max(1.0, float(len(positive))))
        return profile, presence

    @classmethod
    def _project_attention(cls, candidates, traces, scales):
        field_profile, presence = cls._field_profile(traces)
        projected = []
        for candidate in candidates:
            receptive = cls._temporal_profile(candidate["age_s"], scales)
            similarity = sum(
                math.sqrt(left * right)
                for left, right in zip(field_profile, receptive))
            compatibility = (1.0 - presence) + presence * similarity
            projected.append({
                **candidate,
                "temporal_similarity": round(similarity, 9),
                "field_compatibility": round(compatibility, 9),
                "projected_score": round(
                    float(candidate["base_score"]) * compatibility, 9),
            })
        projected.sort(
            key=lambda row: (-row["projected_score"], row["candidate_ref"]))
        return projected, round(presence, 9)

    def attention_probe(self, candidates, *, now=None, samples=64):
        """Compare genuine and counterfactual field effects without selecting.

        Candidates contain only a stable key, temporal provenance, and the score
        already produced by the ordinary attention auction. The durable receipt
        hashes that key and never records candidate prose, memory ids, or prompt
        data. Salience-decay bookkeeping is deliberately not temporal evidence.
        """
        target = _finite(self.clock() if now is None else now)
        admitted = []
        for candidate in candidates or ():
            try:
                key = str(candidate["key"])
                born = float(candidate["born"])
                last_offered = float(candidate.get("last_offered", born))
                base_score = float(candidate["base_score"])
            except (KeyError, TypeError, ValueError):
                continue
            if not key or not math.isfinite(born) \
                    or not math.isfinite(last_offered) \
                    or not math.isfinite(base_score) or base_score < 0.0:
                continue
            admitted.append({
                "candidate_ref": hashlib.sha256(key.encode(
                    "utf-8", errors="replace")).hexdigest()[:16],
                "age_s": max(0.0, target - last_offered),
                "residence_age_s": max(0.0, target - born),
                "base_score": max(0.0, min(1.0, base_score)),
            })
        if len(admitted) < 2:
            return {"recorded": False, "reason": "fewer_than_two_candidates",
                    "candidate_count": len(admitted)}

        events, duplicates = self.recent_events(256)
        ordered = sorted(events, key=lambda row: float(row["ts"]))
        if len(ordered) < 3:
            return {"recorded": False, "reason": "fewer_than_three_events",
                    "candidate_count": len(admitted)}
        gaps = [float(right["ts"]) - float(left["ts"])
                for left, right in zip(ordered, ordered[1:])
                if float(right["ts"]) > float(left["ts"])]
        if not gaps:
            return {"recorded": False, "reason": "no_positive_event_gaps",
                    "candidate_count": len(admitted)}
        median = self._quantile(gaps, 0.5)
        scales = (max(0.001, median / 4.0), max(0.001, median),
                  max(0.001, median * 4.0))
        genuine = self.project(ordered, timescales_s=scales, at=target)
        actual, presence = self._project_attention(
            admitted, genuine["traces"], scales)

        bounded_samples = max(16, min(256, int(samples)))
        interval_winners = {}
        for index in range(bounded_samples):
            shuffled = list(gaps)
            random.Random(4409 + index * 7919).shuffle(shuffled)
            replay, cursor = [], float(ordered[0]["ts"])
            replay.append(dict(ordered[0], ts=cursor))
            for row, gap in zip(ordered[1:], shuffled):
                cursor += gap
                replay.append(dict(row, ts=cursor))
            projection = self.project(
                replay, timescales_s=scales, at=target)
            ranked, _ = self._project_attention(
                admitted, projection["traces"], scales)
            winner = ranked[0]["candidate_ref"]
            interval_winners[winner] = interval_winners.get(winner, 0) + 1

        profile_winners = {}
        for permuted in set(itertools.permutations(genuine["traces"])):
            ranked, _ = self._project_attention(admitted, permuted, scales)
            winner = ranked[0]["candidate_ref"]
            profile_winners[winner] = profile_winners.get(winner, 0) + 1

        base = sorted(
            admitted,
            key=lambda row: (-row["base_score"], row["candidate_ref"]))
        profiles = [self._temporal_profile(row["age_s"], scales)
                    for row in admitted]
        profile_span = max(
            (sum(abs(left - right)
                 for left, right in zip(first, second)) / 2.0
             for first, second in itertools.combinations(profiles, 2)),
            default=0.0)
        compatibility_values = [
            float(row["field_compatibility"]) for row in actual]
        compatibility_span = (
            max(compatibility_values) - min(compatibility_values))
        base_margin = max(
            0.0, float(base[0]["base_score"]) - float(base[1]["base_score"]))
        # This is a dimensionless descriptive ratio, not a tuned threshold:
        # how much differential field leverage exists relative to the auction's
        # own leading margin. `inf` means leverage exists across an exact tie.
        competitive_ratio = (
            compatibility_span / base_margin if base_margin > 1e-12
            else (float("inf") if compatibility_span > 1e-12 else 0.0))
        informative = profile_span > 1e-12 and presence > 1e-12
        receipt = {
            "schema": 2,
            "mode": "shadow_attention_comparison",
            "downstream_channels_touched": [],
            "observed_at": target,
            "event_window": len(ordered),
            "duplicate_receipts_ignored": duplicates,
            "candidate_count": len(admitted),
            "timescales_s": [round(value, 6) for value in scales],
            "field_presence": presence,
            "informative": informative,
            "temporal_profile_span": round(profile_span, 9),
            "field_compatibility_span": round(compatibility_span, 9),
            "base_margin": round(base_margin, 9),
            "competitive_ratio": (
                "infinite" if math.isinf(competitive_ratio)
                else round(competitive_ratio, 9)),
            "base_winner_ref": base[0]["candidate_ref"],
            "genuine_winner_ref": actual[0]["candidate_ref"],
            "genuine_changed_winner": (
                actual[0]["candidate_ref"] != base[0]["candidate_ref"]),
            "genuine_margin": round(
                actual[0]["projected_score"]
                - actual[1]["projected_score"], 9),
            "candidates": [{
                "candidate_ref": row["candidate_ref"],
                "age_s": round(row["age_s"], 6),
                "residence_age_s": round(row["residence_age_s"], 6),
                "base_score": round(row["base_score"], 9),
                "temporal_similarity": row["temporal_similarity"],
                "field_compatibility": row["field_compatibility"],
                "projected_score": row["projected_score"],
            } for row in actual],
            "interval_shuffle": {
                "sample_count": bounded_samples,
                "winner_counts": interval_winners,
                "genuine_winner_share": round(
                    interval_winners.get(
                        actual[0]["candidate_ref"], 0) / bounded_samples, 6),
            },
            "profile_permutation": {
                "sample_count": sum(profile_winners.values()),
                "winner_counts": profile_winners,
                "genuine_winner_share": round(
                    profile_winners.get(
                        actual[0]["candidate_ref"], 0)
                    / max(1, sum(profile_winners.values())), 6),
            },
        }
        with open(self.attention_probes_path, "a",
                  encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return {"recorded": True, **receipt}

    def participation_phase_probe(self, limit=256, *, now=None):
        """Replay natural events through the isolated participation-phase lane."""
        events, duplicates = self.recent_events(limit)
        target = _finite(self.clock() if now is None else now)
        projection = project_participation_phase(events, at=target)
        ordered = sorted(events, key=lambda row: float(row["ts"]))
        gaps = [float(right["ts"]) - float(left["ts"])
                for left, right in zip(ordered, ordered[1:])]
        shuffled_gaps = list(gaps)
        random.Random(7301).shuffle(shuffled_gaps)
        timing_control = []
        if ordered:
            cursor = float(ordered[0]["ts"])
            timing_control.append(dict(ordered[0], ts=cursor))
            for row, gap in zip(ordered[1:], shuffled_gaps):
                cursor += gap
                timing_control.append(dict(row, ts=cursor))
        participation = [normalize_participation(row.get("participation"))
                         for row in ordered]
        shuffled_participation = list(participation)
        random.Random(9109).shuffle(shuffled_participation)
        participation_control = [
            dict(row, participation=vector)
            for row, vector in zip(ordered, shuffled_participation)]
        timing_projection = project_participation_phase(
            timing_control, at=(float(timing_control[-1]["ts"])
                                if timing_control else target))
        participation_projection = project_participation_phase(
            participation_control, at=target)
        projection.update({
            "duplicate_receipts_ignored": duplicates,
            "participation_event_count": sum(
                bool(normalize_participation(row.get("participation")))
                for row in events),
            "controls": {
                "interval_order_shuffle": {
                    "phase_order": timing_projection["phase_order"],
                    "changed": (timing_projection["phase_order"]
                                != projection["phase_order"]),
                },
                "participation_assignment_shuffle": {
                    "phase_order": participation_projection["phase_order"],
                    "changed": (participation_projection["phase_order"]
                                != projection["phase_order"]),
                },
            },
        })
        return projection

    def observe(self, source: str, magnitude: float = 1.0, *, ts=None,
                event_ref: str = "", participation=None):
        now = _finite(self.clock() if ts is None else ts)
        event_ref = str(event_ref or uuid.uuid4().hex)
        # A conversation cycle is one percept even if transport retries the
        # same call. Idempotency belongs at the organ boundary, not only in a
        # well-behaved caller.
        if event_ref == self.last_event_ref:
            result = self.snapshot(now)
            result["duplicate_ignored"] = True
            return result
        if self.last_ts is not None and now < float(self.last_ts):
            raise ValueError("interference events must be monotonic")
        if self.last_ts is not None:
            dt = now - float(self.last_ts)
            self.traces = [v * math.exp(-dt / tau)
                           for v, tau in zip(self.traces, self.timescales_s)]
            for name in self.source_traces:
                self.source_traces[name] = [
                    value * math.exp(-dt / tau)
                    for value, tau in zip(
                        self.source_traces[name], self.timescales_s)]
        amount = max(0.0, _finite(magnitude, 1.0))
        self.traces = [v + amount for v in self.traces]
        self.last_ts = now
        self.event_count += 1
        label = str(source or "unknown")[:96]
        self.sources[label] = int(self.sources.get(label, 0)) + 1
        self.source_traces.setdefault(label, [0.0, 0.0, 0.0])
        self.source_traces[label] = [value + amount
                                     for value in self.source_traces[label]]
        self.last_event_ref = event_ref
        record = {"schema": SCHEMA_VERSION, "ts": now, "source": label,
                  "magnitude": amount, "event_ref": self.last_event_ref}
        vector = normalize_participation(participation)
        if vector:
            record["participation"] = vector
        with open(self.events_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.save()
        return self.snapshot(now)

    def save(self):
        tmp = self.state_path + ".tmp"
        state = {"schema": SCHEMA_VERSION,
                 "timescales_s": list(self.timescales_s),
                 "traces": self.traces, "last_ts": self.last_ts,
                 "event_count": self.event_count, "sources": self.sources,
                 "source_traces": self.source_traces,
                 "last_event_ref": self.last_event_ref}
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.state_path)
