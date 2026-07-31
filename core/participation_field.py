"""Persistent continuous-time participation field.

The field is a synthetic availability mechanism, not a physiology claim.  It
evolves analytically across elapsed time, receives content-free perturbations at
natural organism boundaries, and never creates language, thoughts, actions, or
model calls.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from typing import Any, Mapping


DIMENSIONS = (
    "external_conductance",
    "internal_conductance",
    "source_resolution",
    "temporal_continuity",
    "associative_distance",
    "cross_source_binding",
    "metacognitive_availability",
    "action_coupling",
)


def _unit(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(value):
        return float(default)
    return max(0.0, min(1.0, value))


class ParticipationFieldOrgan:
    """Inertial state that catches itself up whenever observed or perturbed."""

    def __init__(self, persona_dir: str, *, clock=time.time,
                 body_step_s: float = 30.0):
        self.dir = os.path.join(persona_dir, "body", "participation_field")
        os.makedirs(self.dir, exist_ok=True)
        self.state_path = os.path.join(self.dir, "state.json")
        self.events_path = os.path.join(self.dir, "events.jsonl")
        self.clock = clock
        self.body_step_s = max(0.001, float(body_step_s))
        self._lock = threading.RLock()
        loaded = self._load()
        self.values = {
            name: _unit((loaded.get("values") or {}).get(name), 0.5)
            for name in DIMENSIONS}
        self.velocities = {
            name: float((loaded.get("velocities") or {}).get(name, 0.0))
            for name in DIMENSIONS}
        self.targets = {
            name: _unit((loaded.get("targets") or {}).get(
                name, self.values[name]))
            for name in DIMENSIONS}
        self.last_ts = float(
            loaded["last_ts"] if loaded.get("last_ts") is not None
            else self.clock())
        self.event_count = int(loaded.get("event_count") or 0)
        self.last_event_ref = str(loaded.get("last_event_ref") or "")

    def _load(self) -> dict:
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save(self) -> None:
        payload = {
            "schema": 1,
            "last_ts": self.last_ts,
            "event_count": self.event_count,
            "last_event_ref": self.last_event_ref,
            "values": self.values,
            "velocities": self.velocities,
            "targets": self.targets,
        }
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.state_path)

    def _advance_unlocked(self, now: float) -> None:
        now = max(self.last_ts, float(now))
        dt = now - self.last_ts
        if dt <= 0.0:
            return
        # The one existing body step defines the time unit. Dimension periods
        # form a geometric family, avoiding a bank of unrelated timer values.
        for index, name in enumerate(DIMENSIONS):
            period = self.body_step_s * (2.0 ** (index / len(DIMENSIONS)))
            omega = 2.0 * math.pi / period
            damping = omega * 0.18
            x0 = self.values[name] - self.targets[name]
            v0 = self.velocities[name]
            wd = omega * math.sqrt(max(1e-9, 1.0 - 0.18 ** 2))
            decay = math.exp(-damping * dt)
            cosine, sine = math.cos(wd * dt), math.sin(wd * dt)
            coefficient = (v0 + damping * x0) / wd
            x = decay * (x0 * cosine + coefficient * sine)
            velocity = decay * (
                -damping * (x0 * cosine + coefficient * sine)
                + (-x0 * wd * sine + coefficient * wd * cosine))
            raw = self.targets[name] + x
            clipped = _unit(raw)
            self.values[name] = clipped
            self.velocities[name] = (
                0.0 if clipped != raw else velocity)
        self.last_ts = now

    def advance(self, now: float | None = None) -> dict:
        with self._lock:
            self._advance_unlocked(self.clock() if now is None else now)
            self._save()
            return self._snapshot_unlocked()

    def observe(self, source: str, projection: Mapping[str, Any], *,
                strength: float = 1.0, ts: float | None = None,
                event_ref: str = "") -> dict:
        with self._lock:
            now = float(self.clock() if ts is None else ts)
            ref = str(event_ref or uuid.uuid4().hex)[:160]
            if ref and ref == self.last_event_ref:
                return {**self._snapshot_unlocked(), "duplicate_ignored": True}
            self._advance_unlocked(now)
            bounded_strength = _unit(strength, 1.0)
            admitted = {
                name: _unit(projection.get(name, self.targets[name]))
                for name in DIMENSIONS}
            for name in DIMENSIONS:
                delta = admitted[name] - self.values[name]
                self.targets[name] = admitted[name]
                # A perturbation changes both destination and momentum. The
                # response is proportional to discrepancy, never a named mode.
                self.velocities[name] += (
                    delta * bounded_strength / self.body_step_s)
            self.event_count += 1
            self.last_event_ref = ref
            self._save()
            receipt = {
                "schema": 1,
                "ts": now,
                "source": str(source)[:96],
                "event_ref": ref,
                "strength": round(bounded_strength, 9),
                "dimensions": admitted,
            }
            with open(self.events_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(receipt, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> dict:
        movement = math.sqrt(sum(
            value * value for value in self.velocities.values()))
        articulation = (
            self.values["metacognitive_availability"]
            + self.values["action_coupling"]
            + max(self.values["external_conductance"],
                  self.values["internal_conductance"])) / 3.0
        return {
            "schema": 1,
            "mode": "continuous_time_participation_field",
            "last_ts": self.last_ts,
            "event_count": self.event_count,
            "dimensions": {
                name: round(value, 9)
                for name, value in self.values.items()},
            "movement": round(movement, 9),
            "articulation_readiness": round(_unit(articulation), 9),
            "articulation_policy": "descriptive_opportunity_only",
            "model_calls": 0,
            "actions_created": 0,
        }

    def snapshot(self, now: float | None = None) -> dict:
        return self.advance(now)
