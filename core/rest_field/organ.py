"""Persistent, event-driven synthetic rest relationships.

The four public components intentionally remain small:

* :class:`RestField` owns causal state and pure time projection;
* :class:`RestSourceRegistry` translates numeric organ, derived, or manual
  sources through the same typed interface;
* :class:`JunctionRegistry` makes bypass/observe/conduct explicit; and
* :class:`RestObserver` writes durable projections that causal code never
  reads.

Names such as ``recovery_debt`` are functional aliases, not measurements of
biology or claims about subjective experience.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
import threading
import time
from typing import Any, Mapping


SCHEMA_VERSION = 1
DIMENSIONS = (
    "recovery_debt",
    "maintenance_affordance",
    "associative_mobility",
    "trace_retention",
)
SOURCE_KINDS = frozenset({"organ", "derived", "manual"})
JUNCTION_MODES = frozenset({"bypass", "observe", "conduct"})
GLOBAL_MODES = frozenset({"disabled", "shadow", "live"})


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _unit(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _finite(value, default)))


def _signed(value: Any, default: float = 0.0) -> float:
    return max(-1.0, min(1.0, _finite(value, default)))


def _canonical(value: Any) -> Any:
    """Return a stable JSON value, excluding no fields by implication."""
    if isinstance(value, Mapping):
        return {str(key): _canonical(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("configuration numbers must be finite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"configuration value is not JSON-safe: {type(value).__name__}")


def canonical_config_hash(config: Mapping[str, Any] | None) -> str:
    payload = json.dumps(
        _canonical(dict(config or {})), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _append_jsonl(path: str, row: Mapping[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(
            dict(row), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class RestSourceRegistry:
    """One typed door for organ inputs, derived bridges, and manual pushes.

    A source spec contains numeric baselines and a matrix from measurements to
    field dimensions. This keeps a bridge as a relationship between existing
    values instead of a semantic ``when X, do Y`` branch.
    """

    def __init__(self, specs: Mapping[str, Mapping[str, Any]] | None = None):
        self.specs = {}
        self._active = {}
        for name, raw in dict(specs or {}).items():
            spec = dict(raw or {})
            kind = str(spec.get("kind") or "organ")
            if kind not in SOURCE_KINDS:
                raise ValueError(f"unknown rest source kind: {kind}")
            baselines = {
                str(key): _unit(value, 0.5)
                for key, value in dict(spec.get("baselines") or {}).items()}
            calibration = {}
            for metric, raw_range in dict(
                    spec.get("calibration") or {}).items():
                if str(metric) not in baselines:
                    raise ValueError(
                        f"unknown calibrated metric in source {name}: {metric}")
                range_spec = dict(raw_range or {})
                low = _unit(range_spec.get("low"), baselines[str(metric)])
                middle = _unit(
                    range_spec.get("middle"), baselines[str(metric)])
                high = _unit(range_spec.get("high"), baselines[str(metric)])
                if not low <= middle <= high or low == high:
                    raise ValueError(
                        f"invalid calibration range for {name}.{metric}")
                calibration[str(metric)] = {
                    "low": low, "middle": middle, "high": high}
            weights = {}
            for dimension, row in dict(spec.get("weights") or {}).items():
                if dimension not in DIMENSIONS:
                    raise ValueError(
                        f"unknown rest-field dimension in source {name}: {dimension}")
                weights[dimension] = {
                    str(metric): _finite(weight)
                    for metric, weight in dict(row or {}).items()}
            self.specs[str(name)] = {
                "kind": kind,
                "revision": str(spec.get("revision") or "1")[:80],
                "baselines": baselines,
                "calibration": calibration,
                "weights": weights,
                "gain": max(0.0, _finite(spec.get("gain"), 1.0)),
            }
        self.config_hash = canonical_config_hash(self.specs)

    def project(self, name: str, measurements: Mapping[str, Any], *,
                strength: float = 1.0, event_ref: str = "",
                at: float | None = None) -> dict:
        source_name = str(name)
        if source_name not in self.specs:
            raise KeyError(f"unregistered rest source: {source_name}")
        spec = self.specs[source_name]
        raw_admitted = {
            metric: _unit(dict(measurements or {}).get(metric), baseline)
            for metric, baseline in spec["baselines"].items()}
        admitted = {}
        for metric, value in raw_admitted.items():
            calibration = spec["calibration"].get(metric)
            if calibration is None:
                admitted[metric] = value
                continue
            low = calibration["low"]
            middle = calibration["middle"]
            high = calibration["high"]
            if value >= middle:
                width = high - middle
                normalized = (0.5 if width <= 0.0 else
                              0.5 + 0.5 * (value - middle) / width)
            else:
                width = middle - low
                normalized = (0.5 if width <= 0.0 else
                              0.5 - 0.5 * (middle - value) / width)
            admitted[metric] = _unit(normalized)
        gain = spec["gain"] * _unit(strength, 1.0)
        drive = {}
        for dimension in DIMENSIONS:
            total = sum(
                (admitted.get(metric, neutral) - neutral) * 2.0 * weight
                for metric, weight in spec["weights"].get(dimension, {}).items()
                for neutral in (
                    0.5 if metric in spec["calibration"] else
                    spec["baselines"].get(metric, 0.5),))
            drive[dimension] = round(_signed(total * gain), 9)
        active_dimensions = sorted(
            dimension for dimension, row in spec["weights"].items()
            if row)
        return {
            "schema_version": SCHEMA_VERSION,
            "source": source_name[:96],
            "source_kind": spec["kind"],
            "source_revision": spec["revision"],
            "source_registry_hash": self.config_hash,
            "at": _finite(time.time() if at is None else at),
            "event_ref": str(event_ref)[:160],
            "raw_measurements": raw_admitted,
            "measurements": admitted,
            "drive": drive,
            "active_dimensions": active_dimensions,
            "strength": round(_unit(strength, 1.0), 9),
            "content_free": True,
        }

    def offer(self, name: str, measurements: Mapping[str, Any], *,
              strength: float = 1.0, event_ref: str = "",
              at: float | None = None) -> dict:
        """Retain one source's latest numeric contribution and superpose all."""
        projection = self.project(
            name, measurements, strength=strength,
            event_ref=event_ref, at=at)
        self._active[str(name)] = projection
        return self.snapshot(event_ref=event_ref, at=projection["at"])

    def withdraw(self, name: str, *, event_ref: str = "",
                 at: float | None = None) -> dict:
        self._active.pop(str(name), None)
        return self.snapshot(event_ref=event_ref, at=at)

    def snapshot(self, *, event_ref: str = "",
                 at: float | None = None) -> dict:
        contributions = [deepcopy(self._active[name])
                         for name in sorted(self._active)]
        active_dimensions = sorted({
            dimension
            for item in contributions
            for dimension in item.get("active_dimensions", ())
        })
        drive = {
            dimension: round(_signed(sum(
                _signed(item.get("drive", {}).get(dimension))
                for item in contributions
                if dimension in item.get("active_dimensions", ()))), 9)
            for dimension in DIMENSIONS}
        return {
            "schema_version": SCHEMA_VERSION,
            "source": "rest_source_registry",
            "source_kind": "derived",
            "source_revision": "1",
            "source_registry_hash": self.config_hash,
            "at": _finite(time.time() if at is None else at),
            "event_ref": str(event_ref or "")[:160],
            "drive": drive,
            "active_dimensions": active_dimensions,
            "contributions": contributions,
            "strength": 1.0,
            "content_free": True,
        }


class JunctionRegistry:
    """Route proposals while making exact bypass identity the default law."""

    def __init__(self, *, global_mode: str = "disabled",
                 junctions: Mapping[str, str] | None = None,
                 allow_conduct: bool = False):
        mode = str(global_mode)
        if mode not in GLOBAL_MODES:
            raise ValueError(f"unknown rest-field global mode: {mode}")
        self.global_mode = mode
        self.allow_conduct = bool(allow_conduct)
        self.junctions = {}
        for name, raw_mode in dict(junctions or {}).items():
            junction_mode = str(raw_mode)
            if junction_mode not in JUNCTION_MODES:
                raise ValueError(
                    f"unknown rest junction mode for {name}: {junction_mode}")
            if junction_mode == "conduct" and not self.allow_conduct:
                raise ValueError("rest junction conduct mode is not armed")
            self.junctions[str(name)] = junction_mode
        self.config_hash = canonical_config_hash({
            "global_mode": self.global_mode,
            "allow_conduct": self.allow_conduct,
            "junctions": self.junctions,
        })

    def effective_mode(self, name: str) -> str:
        requested = self.junctions.get(str(name), "bypass")
        if self.global_mode == "disabled":
            return "bypass"
        if self.global_mode == "shadow":
            return "observe" if requested != "bypass" else "bypass"
        return requested

    def route(self, name: str, baseline: Any, proposed: Any) -> tuple[Any, dict]:
        effective = self.effective_mode(name)
        # Returning the original baseline object is deliberate. Bypass and
        # observation cannot alter ordering, serialization, or object identity.
        output = proposed if effective == "conduct" else baseline
        return output, {
            "schema_version": SCHEMA_VERSION,
            "junction": str(name)[:96],
            "global_mode": self.global_mode,
            "requested_mode": self.junctions.get(str(name), "bypass"),
            "effective_mode": effective,
            "applied": effective == "conduct",
            "junction_profile_hash": self.config_hash,
        }

    def snapshot(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "global_mode": self.global_mode,
            "allow_conduct": self.allow_conduct,
            "junctions": dict(self.junctions),
            "junction_profile_hash": self.config_hash,
        }


class RestField:
    """Four partially independent relationships with pure time projection."""

    def __init__(self, persona_dir: str, *, config: Mapping[str, Any],
                 clock=time.time):
        self.persona_dir = os.path.abspath(os.fspath(persona_dir))
        self.config = _canonical(dict(config or {}))
        self.mode = str(self.config.get("mode") or "disabled")
        if self.mode not in GLOBAL_MODES:
            raise ValueError(f"unknown rest-field mode: {self.mode}")
        self.config_hash = canonical_config_hash(self.config)
        self.clock = clock
        self._lock = threading.RLock()
        self.dir = os.path.join(self.persona_dir, "body", "rest_field")
        self.state_path = os.path.join(self.dir, "state.json")
        self.events_path = os.path.join(self.dir, "events.jsonl")
        dynamics = dict(self.config.get("dynamics") or {})
        if self.mode != "disabled" and set(dynamics) != set(DIMENSIONS):
            raise ValueError(
                "enabled rest field requires explicit dynamics for every "
                "dimension")
        self.periods = {}
        self.damping = {}
        for name in DIMENSIONS:
            spec = dict(dynamics.get(name) or {})
            if self.mode == "disabled" and not spec:
                # Disabled state never projects or persists; these values are
                # inert placeholders rather than an authored timescale.
                self.periods[name] = 1.0
                self.damping[name] = 0.0
                continue
            period = _finite(spec.get("period_s"), -1.0)
            damping = _finite(spec.get("damping_ratio"), -1.0)
            if period <= 0.0:
                raise ValueError(f"{name}.period_s must be positive")
            if not 0.0 <= damping < 1.0:
                raise ValueError(
                    f"{name}.damping_ratio must be in [0, 1)")
            self.periods[name] = period
            self.damping[name] = damping
        self._state = self._default_state()
        if self.mode != "disabled":
            os.makedirs(self.dir, exist_ok=True)
            self._state = self._load()

    def _default_state(self) -> dict:
        now = _finite(self.clock())
        return {
            "schema_version": SCHEMA_VERSION,
            "config_hash": self.config_hash,
            "previous_config_hash": None,
            "last_ts": now,
            "event_count": 0,
            "last_event_ref": "",
            "values": {name: 0.5 for name in DIMENSIONS},
            "velocities": {name: 0.0 for name in DIMENSIONS},
            "targets": {name: 0.5 for name in DIMENSIONS},
            "last_source": None,
        }

    def _load(self) -> dict:
        state = self._default_state()
        try:
            with open(self.state_path, encoding="utf-8") as stream:
                loaded = json.load(stream)
        except (OSError, TypeError, ValueError):
            return state
        if not isinstance(loaded, Mapping):
            return state
        stored_hash = str(loaded.get("config_hash") or "")
        if stored_hash and stored_hash != self.config_hash:
            # Period and damping changes reinterpret velocity and phase. Reset
            # rather than laundering an old trajectory through new anatomy.
            state["previous_config_hash"] = stored_hash
            return state
        state.update({
            "previous_config_hash": (
                stored_hash if stored_hash and stored_hash != self.config_hash
                else loaded.get("previous_config_hash")),
            "last_ts": _finite(loaded.get("last_ts"), state["last_ts"]),
            "event_count": max(0, int(loaded.get("event_count") or 0)),
            "last_event_ref": str(loaded.get("last_event_ref") or "")[:160],
            "last_source": loaded.get("last_source"),
        })
        for key, default in (("values", 0.5), ("targets", 0.5)):
            state[key] = {
                name: _unit(dict(loaded.get(key) or {}).get(name), default)
                for name in DIMENSIONS}
        state["velocities"] = {
            name: _finite(dict(loaded.get("velocities") or {}).get(name))
            for name in DIMENSIONS}
        state["config_hash"] = self.config_hash
        return state

    def _persist_unlocked(self) -> None:
        if self.mode == "disabled":
            return
        payload = deepcopy(self._state)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, self.state_path)

    def _project(self, state: Mapping[str, Any], at: float) -> dict:
        projected = deepcopy(dict(state))
        last_ts = _finite(projected.get("last_ts"), at)
        target_ts = max(last_ts, _finite(at, last_ts))
        dt = target_ts - last_ts
        if dt <= 0.0:
            return projected
        for name in DIMENSIONS:
            target = _unit(projected["targets"].get(name), 0.5)
            x0 = _unit(projected["values"].get(name), 0.5) - target
            v0 = _finite(projected["velocities"].get(name))
            omega = 2.0 * math.pi / self.periods[name]
            ratio = self.damping[name]
            decay_rate = omega * ratio
            wd = omega * math.sqrt(max(1e-12, 1.0 - ratio * ratio))
            decay = math.exp(-decay_rate * dt)
            cosine, sine = math.cos(wd * dt), math.sin(wd * dt)
            coefficient = (v0 + decay_rate * x0) / wd
            relative = decay * (x0 * cosine + coefficient * sine)
            velocity = decay * (
                -decay_rate * (x0 * cosine + coefficient * sine)
                + (-x0 * wd * sine + coefficient * wd * cosine))
            raw = target + relative
            bounded = _unit(raw)
            projected["values"][name] = bounded
            projected["velocities"][name] = (
                0.0 if bounded != raw else velocity)
        projected["last_ts"] = target_ts
        return projected

    def _receipt(self, state: Mapping[str, Any], *, projected_at: float) -> dict:
        phases = {}
        for name in DIMENSIONS:
            target = _unit(state["targets"].get(name), 0.5)
            relative = _unit(state["values"].get(name), 0.5) - target
            scaled_velocity = _finite(state["velocities"].get(name)) / (
                2.0 * math.pi / self.periods[name])
            phases[name] = round(math.atan2(relative, scaled_velocity), 9)
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "config_hash": self.config_hash,
            "previous_config_hash": state.get("previous_config_hash"),
            "projected_at": projected_at,
            "last_causal_ts": _finite(self._state.get("last_ts")),
            "event_count": int(state.get("event_count") or 0),
            "last_event_ref": str(state.get("last_event_ref") or ""),
            "last_source": state.get("last_source"),
            "dimensions": {
                name: round(_unit(state["values"].get(name), 0.5), 9)
                for name in DIMENSIONS},
            "targets": {
                name: round(_unit(state["targets"].get(name), 0.5), 9)
                for name in DIMENSIONS},
            "velocities": {
                name: round(_finite(state["velocities"].get(name)), 12)
                for name in DIMENSIONS},
            "phase_rad": phases,
            "period_s": {name: round(self.periods[name], 9)
                         for name in DIMENSIONS},
            "downstream_channels_touched": [],
            "model_calls": 0,
            "actions_created": 0,
        }

    def peek(self, at: float | None = None) -> dict:
        """Project without changing causal memory or writing any file."""
        with self._lock:
            target = _finite(self.clock() if at is None else at)
            projected = self._project(self._state, target)
            return self._receipt(projected, projected_at=target)

    def causal_snapshot(self) -> dict:
        """Return the last committed state without catching it up."""
        with self._lock:
            at = _finite(self._state.get("last_ts"))
            return self._receipt(self._state, projected_at=at)

    def observe(self, source_projection: Mapping[str, Any], *,
                at: float | None = None, event_ref: str = "") -> dict:
        if self.mode == "disabled":
            return {**self.causal_snapshot(), "ignored": "globally_disabled"}
        with self._lock:
            now = _finite(self.clock() if at is None else at)
            ref = str(event_ref or source_projection.get("event_ref") or "")[:160]
            if ref and ref == self._state.get("last_event_ref"):
                return {**self.causal_snapshot(), "duplicate_ignored": True}
            projected = self._project(self._state, now)
            drive = dict(source_projection.get("drive") or {})
            active_dimensions = {
                str(name) for name in
                source_projection.get("active_dimensions", DIMENSIONS)
                if str(name) in DIMENSIONS}
            strength = _unit(source_projection.get("strength"), 1.0)
            for name in DIMENSIONS:
                if name not in active_dimensions:
                    continue
                destination = _unit(0.5 + 0.5 * _signed(drive.get(name)))
                old_target = _unit(projected["targets"].get(name), 0.5)
                projected["targets"][name] = (
                    old_target + (destination - old_target) * strength)
                discrepancy = destination - _unit(
                    projected["values"].get(name), 0.5)
                projected["velocities"][name] = _finite(
                    projected["velocities"].get(name)) + (
                        discrepancy * strength / self.periods[name])
            projected["event_count"] = int(projected.get("event_count") or 0) + 1
            projected["last_event_ref"] = ref
            projected["last_source"] = {
                "source": str(source_projection.get("source") or "unknown")[:96],
                "source_kind": str(
                    source_projection.get("source_kind") or "organ")[:24],
                "source_revision": str(
                    source_projection.get("source_revision") or "")[:80],
                "source_registry_hash": str(
                    source_projection.get("source_registry_hash") or "")[:64],
            }
            self._state = projected
            self._persist_unlocked()
            event = {
                "schema_version": SCHEMA_VERSION,
                "at": now,
                "event_ref": ref,
                "config_hash": self.config_hash,
                **projected["last_source"],
                "drive": {name: round(_signed(drive.get(name)), 9)
                          for name in DIMENSIONS},
                "strength": round(strength, 9),
                "content_free": True,
                "downstream_channels_touched": [],
            }
            _append_jsonl(self.events_path, event)
            return self._receipt(self._state, projected_at=now)

    def save(self) -> None:
        with self._lock:
            self._persist_unlocked()


class RestObserver:
    """Durable observation-plane storage with no causal feedback path."""

    def __init__(self, persona_dir: str):
        self.dir = os.path.join(
            os.path.abspath(os.fspath(persona_dir)), "history")
        self.samples_path = os.path.join(self.dir, "rest_field_samples.jsonl")
        self._lock = threading.Lock()

    def sample(self, field: RestField, *, at: float | None = None,
               source_snapshot: Mapping[str, Any] | None = None,
               junction_snapshot: Mapping[str, Any] | None = None,
               influence_snapshot: Mapping[str, Any] | None = None) -> dict:
        projection = field.peek(at)
        sources = dict(source_snapshot or {})
        if sources and sources.get("content_free") is not True:
            raise ValueError(
                "rest observer source snapshot must declare content_free")
        row = {
            "schema_version": SCHEMA_VERSION,
            "kind": "rest_field_observation",
            "sampled_at": projection["projected_at"],
            "field": projection,
            "source_snapshot": _canonical(sources),
            "junction_snapshot": _canonical(dict(junction_snapshot or {})),
            "influence_snapshot": _canonical(dict(influence_snapshot or {})),
            "causal_plane_reads_this_log": False,
        }
        with self._lock:
            _append_jsonl(self.samples_path, row)
        return row

    def read_samples(self, limit: int = 2048) -> list[dict]:
        rows = []
        try:
            with open(self.samples_path, encoding="utf-8") as stream:
                for line in stream:
                    try:
                        value = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(value, dict):
                        rows.append(value)
        except OSError:
            return []
        return rows[-max(1, min(100_000, int(limit))):]
