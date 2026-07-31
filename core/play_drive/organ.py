"""Persona-private play momentum, initially isolated in shadow mode.

The organ receives only bounded numeric evidence from its owning TurnEngine.
It neither interprets prose nor chooses an action.  Append-only observations
can be replayed into the same vector after restart; the returned projections
describe hypothetical attention/body coupling but touch neither.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 2
READABLE_SCHEMAS = frozenset({1, 2})
DIMENSIONS = (
    "capture", "approach", "reciprocity", "novelty",
    "activation", "tension", "inhibition", "satiation", "refractory",
)
HALF_LIVES_S = {
    "capture": 1800.0,
    "approach": 900.0,
    "reciprocity": 3600.0,
    "novelty": 1200.0,
    "activation": 720.0,
    "tension": 2400.0,
    "inhibition": 1200.0,
    "satiation": 3600.0,
    "refractory": 900.0,
}
SIGNALS = {
    "play_tone", "novelty", "prediction_violation", "recurrence",
    "affordance", "capacity", "coherence", "social_affinity",
    "interaction_presence", "social_presence", "object_affordance",
    "relational_resonance", "orientation_coupling",
    "chosen_action", "action_success", "witnessed_response",
    "satisfaction", "release", "interruption", "refusal", "mismatch",
    "recovery_load", "overstimulation", "body_activation",
    "rhythm_complexity", "rhythm_flux",
}


def _unit(value: Any) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0


def _union(old: float, gain: float) -> float:
    old, gain = _unit(old), _unit(gain)
    return 1.0 - (1.0 - old) * (1.0 - gain)


def _union_many(*values: float) -> float:
    remainder = 1.0
    for value in values:
        remainder *= 1.0 - _unit(value)
    return 1.0 - remainder


def _digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


class PlayDriveOrgan:
    """Append-only potential play arcs owned by exactly one persona."""

    def __init__(self, persona_dir: str | os.PathLike[str], *, owner: str,
                 clock=time.time):
        self.owner = str(owner or "").strip()
        if not self.owner:
            raise ValueError("play drive requires an exact owner")
        self.root = Path(persona_dir).resolve() / "body" / "play_drive"
        self.events_path = self.root / "events.jsonl"
        self.clock = clock

    @staticmethod
    def _decay(vector: Mapping[str, Any], dt_s: float) -> dict[str, float]:
        dt_s = max(0.0, float(dt_s))
        return {
            name: _unit(vector.get(name)) * math.exp(
                -math.log(2.0) * dt_s / HALF_LIVES_S[name])
            for name in DIMENSIONS
        }

    @classmethod
    def advance(cls, prior: Mapping[str, Any], signals: Mapping[str, Any],
                *, dt_s: float = 0.0) -> dict[str, float]:
        """Advance one vector from converging evidence, without semantics."""
        v = cls._decay(prior, dt_s)
        s = {name: _unit(signals.get(name)) for name in SIGNALS}

        # Novelty is not play by itself.  Some already-present play evidence
        # must gate every other contributor, so a surprising conversation or
        # successful work action cannot manufacture a play arc.
        relational_invitation = s["social_affinity"] * max(
            s["interaction_presence"],
            s["social_presence"] * (
                .55 + .25 * s["relational_resonance"]
                + .20 * s["orientation_coupling"]))
        invitation = _union_many(
            .58 * s["novelty"],
            .46 * s["prediction_violation"],
            .52 * s["affordance"],
            .48 * s["object_affordance"],
            .44 * relational_invitation,
            .34 * s["recurrence"],
            .26 * s["witnessed_response"])
        aftermath_opening = (
            (1.0 - v["satiation"]) * (1.0 - v["refractory"]))
        # A latent play tone is not a standing command. It can catch only
        # where the current world/relationship supplies an invitation, the
        # organism has capacity, and the previous arc has left room to recur.
        capture_gain = (
            s["play_tone"] * invitation * s["capacity"]
            * aftermath_opening)
        v["capture"] = _union(v["capture"], capture_gain)
        v["novelty"] = _union(
            v["novelty"],
            .62 * s["novelty"] + .38 * s["prediction_violation"])
        # "Activation" is the synthetic arousal analogue: a content-free
        # convergence of already-present capture, body activation, and actual
        # oscillator distribution motion. Rhythm cannot manufacture play.
        activation_gain = v["capture"] * s["capacity"] * (
            .36 * s["body_activation"] + .28 * s["rhythm_flux"]
            + .22 * s["rhythm_complexity"]
            + .14 * s["prediction_violation"])
        v["activation"] = _union(v["activation"], activation_gain)

        inhibition_gain = (
            .28 * s["recovery_load"] + .24 * s["overstimulation"]
            + .20 * s["mismatch"] + .18 * s["refusal"]
            + .10 * s["interruption"])
        v["inhibition"] = _union(v["inhibition"], inhibition_gain)

        readiness = (
            .34 * s["capacity"] + .22 * s["coherence"]
            + .18 * s["affordance"] + .14 * s["social_affinity"]
            + .12 * s["body_activation"])
        approach_goal = v["capture"] * readiness * (1.0 - v["inhibition"])
        approach_goal = _union(
            approach_goal, v["activation"] * v["capture"]
            * (1.0 - v["inhibition"]))
        movement_evidence = max(
            s["chosen_action"] * (.35 + .65 * s["action_success"])
            * v["capture"],
            approach_goal)
        v["approach"] = _union(v["approach"], .42 * movement_evidence)

        reciprocal_evidence = s["witnessed_response"] * (
            .35 + .35 * s["action_success"] + .30 * v["approach"])
        v["reciprocity"] = _union(v["reciprocity"], reciprocal_evidence)

        satisfying = max(s["satisfaction"], s["release"])
        v["satiation"] = _union(
            v["satiation"],
            .72 * satisfying + .18 * v["reciprocity"] * s["satisfaction"]
            + .10 * s["interruption"])
        tension_gain = (
            .34 * v["approach"] * (1.0 - satisfying)
            + .22 * v["capture"] * (1.0 - s["action_success"])
            + .18 * v["reciprocity"] * (1.0 - s["satisfaction"]))
        tension_relief = max(
            satisfying, .72 * s["refusal"], .55 * s["interruption"])
        v["tension"] = _union(v["tension"], tension_gain) * (
            1.0 - .82 * tension_relief)

        refractory_gain = max(
            s["release"], .72 * v["satiation"],
            .68 * s["overstimulation"])
        v["refractory"] = _union(v["refractory"], refractory_gain)
        return {name: round(_unit(v[name]), 9) for name in DIMENSIONS}

    @staticmethod
    def _empty() -> dict[str, float]:
        return {name: 0.0 for name in DIMENSIONS}

    def _records(self) -> list[dict]:
        if not self.events_path.is_file():
            return []
        records = []
        with self.events_path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if (isinstance(value, dict)
                        and value.get("schema") in READABLE_SCHEMAS
                        and value.get("owner") == self.owner):
                    records.append(value)
        return records

    def _replay(self, records: list[dict], now: float) -> tuple[dict, dict]:
        field = self._empty()
        arcs: dict[str, dict] = {}
        last_ts = None
        for record in sorted(records, key=lambda item: float(item["ts"])):
            ts = float(record["ts"])
            dt = 0.0 if last_ts is None else max(0.0, ts - last_ts)
            field = self.advance(field, record.get("signals") or {}, dt_s=dt)
            arc_id = str(record.get("arc_id") or "")
            arc = arcs.setdefault(
                arc_id, {"vector": self._empty(), "last_ts": None,
                         "event_count": 0, "last_kind": None})
            arc_dt = 0.0 if arc["last_ts"] is None else max(
                0.0, ts - float(arc["last_ts"]))
            arc["vector"] = self.advance(
                arc["vector"], record.get("signals") or {}, dt_s=arc_dt)
            arc.update({"last_ts": ts, "event_count": arc["event_count"] + 1,
                        "last_kind": record.get("kind")})
            last_ts = ts
        if last_ts is not None:
            field = self._decay(field, max(0.0, now - last_ts))
        for arc in arcs.values():
            if arc["last_ts"] is not None:
                arc["vector"] = self._decay(
                    arc["vector"], max(0.0, now - float(arc["last_ts"])))
        return field, arcs

    @staticmethod
    def shadow_projection(vector: Mapping[str, Any]) -> dict:
        """Describe possible couplings. Nothing consumes these values yet."""
        v = {name: _unit(vector.get(name)) for name in DIMENSIONS}
        pull = (
            .34 * v["capture"] + .28 * v["approach"]
            + .16 * v["activation"] + .12 * v["tension"]
            + .06 * v["novelty"] + .04 * v["reciprocity"])
        resistance = (
            .45 * v["inhibition"] + .32 * v["satiation"]
            + .23 * v["refractory"])
        attention_delta = max(-.18, min(.18, .18 * (pull - resistance)))
        return {
            "mode": "shadow",
            "applied": False,
            "downstream_channels_touched": [],
            "hypothetical_attention_delta": round(attention_delta, 9),
            "hypothetical_somatic_pressure": {
                "activation": round(
                    _unit(.31 * v["activation"] + .27 * v["approach"]
                          + .23 * v["tension"] + .19 * v["capture"]), 9),
                "settling": round(
                    _unit(.44 * v["satiation"] + .34 * v["refractory"]
                          + .22 * v["inhibition"]), 9),
            },
        }

    @staticmethod
    def rhythm_participation(
            bands: Mapping[str, Any],
            previous_bands: Mapping[str, Any] | None = None) -> dict:
        """Reduce a distribution and its real trajectory without band lore."""
        values = [_unit(value) for value in dict(bands or {}).values()]
        total = sum(values)
        if not values or total <= 0.0:
            return {"complexity": 0.0, "flux": 0.0,
                    "previous_available": False}
        shares = [value / total for value in values]
        if len(shares) <= 1:
            complexity = 0.0
        else:
            complexity = -sum(
                share * math.log(share)
                for share in shares if share > 0.0) / math.log(len(shares))
        previous = dict(previous_bands or {})
        common = [name for name in dict(bands or {}) if name in previous]
        flux = 0.0
        if common:
            prior_total = sum(_unit(previous[name]) for name in common)
            current_total = sum(_unit(dict(bands)[name]) for name in common)
            if prior_total > 0.0 and current_total > 0.0:
                # Total-variation distance is bounded 0..1 and independent of
                # the names assigned to the oscillator dimensions.
                flux = .5 * sum(abs(
                    _unit(dict(bands)[name]) / current_total
                    - _unit(previous[name]) / prior_total)
                    for name in common)
        return {
            "complexity": round(_unit(complexity), 9),
            "flux": round(_unit(flux), 9),
            "previous_available": bool(common),
        }

    def snapshot(self, now: float | None = None) -> dict:
        now = float(self.clock() if now is None else now)
        records = self._records()
        field, arcs = self._replay(records, now)
        active = []
        for arc_id, arc in arcs.items():
            vector = {name: round(_unit(value), 9)
                      for name, value in arc["vector"].items()}
            momentum = max(
                vector["capture"], vector["approach"], vector["activation"],
                vector["tension"])
            if momentum >= .08:
                active.append({
                    "arc_id": arc_id,
                    "vector": vector,
                    "event_count": arc["event_count"],
                    "last_kind": arc["last_kind"],
                    "last_ts": arc["last_ts"],
                    "shadow": self.shadow_projection(vector),
                })
        active.sort(key=lambda item: (
            -max(item["vector"]["capture"], item["vector"]["approach"],
                 item["vector"]["activation"], item["vector"]["tension"]),
            item["arc_id"]))
        vector = {name: round(_unit(value), 9)
                  for name, value in field.items()}
        return {
            "schema": SCHEMA_VERSION,
            "owner": self.owner,
            "ownership": "persona_private",
            "mode": "shadow",
            "event_count": len(records),
            "vector": vector,
            "active_arcs": active[:12],
            "shadow": self.shadow_projection(vector),
            "cross_persona_reads": False,
            "external_effects": False,
        }

    def counterfactual_attention(
            self, candidates: list[Mapping[str, Any]], *,
            now: float | None = None) -> dict:
        """Project an explicit-affinity bid without touching candidate state."""
        now = float(self.clock() if now is None else now)
        snapshot = self.snapshot(now)
        attention_delta = float(
            snapshot["shadow"]["hypothetical_attention_delta"])
        rows = []
        for candidate in candidates:
            key = str(candidate.get("key") or "")
            if not key:
                continue
            base = _unit(candidate.get("base_score"))
            affinity = _unit(candidate.get("play_affinity"))
            delta = (
                attention_delta * affinity * (1.0 - base)
                if attention_delta >= 0.0
                else attention_delta * affinity * base)
            hypothetical = _unit(base + delta)
            rows.append({
                "candidate_ref": "candidate_" + _digest(key),
                "base_score": round(base, 9),
                "play_affinity": round(affinity, 9),
                "hypothetical_delta": round(delta, 9),
                "hypothetical_score": round(hypothetical, 9),
            })
        original = sorted(
            rows, key=lambda row: (
                -row["base_score"], row["candidate_ref"]))
        counterfactual = sorted(
            rows, key=lambda row: (
                -row["hypothetical_score"], row["candidate_ref"]))

        def margin(ordered, field):
            if not ordered:
                return 0.0
            return max(0.0, float(ordered[0][field])
                       - (float(ordered[1][field])
                          if len(ordered) > 1 else 0.0))

        eligible = sum(
            1 for row in rows if row["play_affinity"] > 0.0)
        return {
            "schema": 1,
            "owner": self.owner,
            "ownership": "persona_private",
            "mode": "shadow",
            "applied": False,
            "downstream_channels_touched": [],
            "external_effects": False,
            "eligibility": "explicit_witnessed_play_affinity",
            "candidate_count": len(rows),
            "eligible_count": eligible,
            "play_event_count": snapshot["event_count"],
            "attention_delta": round(attention_delta, 9),
            "original_winner_ref": (
                original[0]["candidate_ref"] if original else None),
            "counterfactual_winner_ref": (
                counterfactual[0]["candidate_ref"]
                if counterfactual else None),
            "original_margin": round(
                margin(original, "base_score"), 9),
            "counterfactual_margin": round(
                margin(counterfactual, "hypothetical_score"), 9),
            "candidates": rows[:48],
        }

    def observe(self, kind: str, signals: Mapping[str, Any], *,
                source_ref: str, event_ref: str, ts: float | None = None) -> dict:
        kind = str(kind or "").strip()[:64]
        source_ref = str(source_ref or "").strip()
        event_ref = str(event_ref or "").strip()
        if not kind or not source_ref or not event_ref:
            raise ValueError(
                "play observation requires kind, source ref, and event ref")
        bounded = {name: _unit(signals.get(name))
                   for name in SIGNALS if name in signals}
        records = self._records()
        if any(record.get("event_ref") == event_ref for record in records):
            result = self.snapshot(ts)
            result["duplicate_ignored"] = True
            return result
        now = float(self.clock() if ts is None else ts)
        if records and now < max(float(record["ts"]) for record in records):
            raise ValueError("play observations must be monotonic")
        record = {
            "schema": SCHEMA_VERSION,
            "owner": self.owner,
            "ownership": "persona_private",
            "kind": kind,
            "arc_id": "play_arc_" + _digest(
                f"{self.owner.casefold()}:{source_ref}"),
            "event_ref": event_ref,
            "ts": now,
            "signals": bounded,
            "mode": "shadow",
            "downstream_channels_touched": [],
        }
        self.root.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return self.snapshot(now)

    def save(self):
        """Compatibility with the organ lifecycle; the ledger is fsynced."""
        return self.snapshot()
