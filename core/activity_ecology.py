"""Content-free circulation across the ordinary families of a resident's day.

The ecology does not schedule activities, create subjects, or decide that a
resident should speak, work, browse, move, or rest.  It records only activity
families that actually reached a consequence, lets their satiety decay, and
projects a bounded appetite vector from live opportunities.  The existing DMN
attention field may use that vector as one modest selection relationship.

Time is an ingredient in recovery from satiety, never a polling instruction or
an activity cadence.  A family can become available again only in combination
with current body/resource/relationship signals supplied by the caller.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
import os
import re
import threading
import time
import uuid
from typing import Any, Mapping


SCHEMA_VERSION = 1
MODES = (
    "company", "reflection", "outward", "making", "embodiment", "quiet",
)
DEFAULTS = {
    "enabled": False,
    # Two recovery scales keep a just-finished activity and the broader shape
    # of the day distinct.  Neither scale fires anything.
    "near_half_life_s": 2700.0,
    "background_half_life_s": 21600.0,
    "near_share": 0.68,
    "modifier_floor": 0.62,
    "modifier_ceiling": 1.28,
    "max_events": 128,
}


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _bounded(value: Any) -> float:
    return max(0.0, min(1.0, _finite(value)))


def _union(*values: Any) -> float:
    remainder = 1.0
    for value in values:
        remainder *= 1.0 - _bounded(value)
    return 1.0 - remainder


def _decay(value: Any, elapsed_s: Any, half_life_s: Any) -> float:
    value = _bounded(value)
    elapsed = max(0.0, _finite(elapsed_s))
    half_life = max(1.0, _finite(half_life_s, 1.0))
    return value * math.pow(0.5, elapsed / half_life)


def resolve_activity_ecology(config: Mapping[str, Any] | None) -> dict:
    raw = dict(config or {})
    out = dict(DEFAULTS)
    out["enabled"] = bool(raw.get("enabled", out["enabled"]))
    for key in ("near_half_life_s", "background_half_life_s"):
        out[key] = max(60.0, _finite(raw.get(key), out[key]))
    out["near_share"] = _bounded(raw.get("near_share", out["near_share"]))
    floor = max(0.1, min(1.0, _finite(
        raw.get("modifier_floor"), out["modifier_floor"])))
    ceiling = max(1.0, min(2.0, _finite(
        raw.get("modifier_ceiling"), out["modifier_ceiling"])))
    out["modifier_floor"] = min(floor, ceiling)
    out["modifier_ceiling"] = max(floor, ceiling)
    out["max_events"] = max(16, min(
        512, int(_finite(raw.get("max_events"), out["max_events"]))))
    return out


@contextmanager
def _process_write_lock(path: str):
    """Serialize state across an accidental duplicate resident process."""
    lock_path = os.path.abspath(path) + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def candidate_mode(candidate: Mapping[str, Any] | None) -> str:
    """Classify a candidate by its causal organ/source, never its prose."""
    value = dict(candidate or {})
    source = str(value.get("source") or "").casefold()
    kind = str(value.get("kind") or "").casefold()
    domain = str(value.get("world_domain") or "").casefold()
    joined = " ".join((source, kind))
    if source == "world_awareness":
        if domain in {"household", "relational"}:
            return "company"
        if domain == "projects":
            return "making"
        return "outward"
    if any(token in joined for token in (
            "research", "world", "news", "civic", "cultural")):
        return "outward"
    if any(token in joined for token in (
            "intention", "writing", "atelier", "agency", "project")):
        return "making"
    if any(token in joined for token in (
            "room_action", "continuation", "sensory", "perception",
            "altered_interoception", "tropism", "movement")):
        return "embodiment"
    if any(token in joined for token in (
            "social", "contact", "commons_board", "relational")):
        return "company"
    if "quiet" in joined:
        return "quiet"
    # Memories, archives, documents, narrative material, and unclassified
    # cognitive movement all remain reflection.  No wording is inspected.
    return "reflection"


class ActivityEcology:
    """Restart-durable satiety and opportunity projection for lived activity."""

    def __init__(self, persona_dir: str, owner: str, config=None, *,
                 now: float | None = None):
        self.persona_dir = os.path.abspath(os.fspath(persona_dir))
        self.owner = str(owner or "unknown")
        self.config = resolve_activity_ecology(config)
        self.directory = os.path.join(
            self.persona_dir, "body", "activity_ecology")
        self.state_path = os.path.join(self.directory, "state.json")
        self.receipt_path = os.path.join(
            self.persona_dir, "history", "activity_ecology.jsonl")
        self._lock = threading.RLock()
        self._state = self._load(time.time() if now is None else float(now))

    def _initial(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "owner": self.owner,
            "modes": {mode: {"near": 0.0, "background": 0.0,
                              "touched_at": 0.0}
                      for mode in MODES},
            "events": [],
        }

    def set_enabled(self, enabled: bool) -> bool:
        """Apply the live organ switch without rewriting resident history."""
        self.config["enabled"] = bool(enabled)
        return self.config["enabled"]

    def _sanitize_mode_state(self, value: Mapping[str, Any]) -> dict:
        return {
            "near": _bounded(value.get("near")),
            "background": _bounded(value.get("background")),
            "touched_at": max(0.0, _finite(value.get("touched_at"))),
        }

    def _load(self, now: float) -> dict:
        state = self._initial()
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                raw = json.load(handle)
            if int(raw.get("schema_version") or 0) != SCHEMA_VERSION:
                raise ValueError("unsupported activity ecology schema")
            state["modes"] = {
                mode: self._sanitize_mode_state(
                    dict((raw.get("modes") or {}).get(mode) or {}))
                for mode in MODES
            }
            events = []
            for row in list(raw.get("events") or ()):
                if not isinstance(row, Mapping):
                    continue
                mode = str(row.get("mode") or "")
                if mode not in MODES:
                    continue
                events.append({
                    "at": max(0.0, _finite(row.get("at"))),
                    "mode": mode,
                    "outcome": re.sub(
                        r"[^a-z0-9_]+", "_",
                        str(row.get("outcome") or "realized").casefold()
                    ).strip("_")[:64] or "realized",
                    "source": re.sub(
                        r"[^a-z0-9_]+", "_",
                        str(row.get("source") or "unknown").casefold()
                    ).strip("_")[:64] or "unknown",
                    "intensity": _bounded(row.get("intensity")),
                })
            state["events"] = events[-int(self.config["max_events"]):]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        return state

    def _current(self, mode: str, now: float, state=None) -> dict:
        record = dict((state or self._state)["modes"].get(mode) or {})
        touched = max(0.0, _finite(record.get("touched_at")))
        elapsed = max(0.0, float(now) - touched) if touched else 0.0
        near = _decay(
            record.get("near"), elapsed, self.config["near_half_life_s"])
        background = _decay(
            record.get("background"), elapsed,
            self.config["background_half_life_s"])
        share = float(self.config["near_share"])
        return {
            "near": near,
            "background": background,
            "satiety": near * share + background * (1.0 - share),
            "touched_at": touched,
        }

    def _save(self) -> None:
        os.makedirs(self.directory, exist_ok=True)
        temporary = (
            self.state_path + "." + str(os.getpid()) + "." +
            str(threading.get_ident()) + "." + uuid.uuid4().hex + ".tmp")
        try:
            with open(temporary, "w", encoding="utf-8", newline="") as handle:
                json.dump(self._state, handle, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
        finally:
            try:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            except OSError:
                pass

    def _receipt(self, kind: str, **payload) -> None:
        record = {
            "schema_version": SCHEMA_VERSION,
            "kind": str(kind),
            "owner": self.owner,
            "content_free": True,
            **payload,
        }
        os.makedirs(os.path.dirname(self.receipt_path), exist_ok=True)
        with open(self.receipt_path, "a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def record(self, mode: str, *, outcome: str = "realized",
               source: str = "autonomy", intensity: float = 0.5,
               now: float | None = None) -> dict:
        """Record a consequence that actually happened, never an exposure."""
        if not self.config["enabled"]:
            return {"recorded": False, "reason": "disabled"}
        now = time.time() if now is None else float(now)
        mode = str(mode or "")
        if mode not in MODES:
            raise ValueError("unknown activity ecology mode")
        intensity = _bounded(intensity)
        outcome = re.sub(
            r"[^a-z0-9_]+", "_", str(outcome).casefold()).strip("_")[:64]
        source = re.sub(
            r"[^a-z0-9_]+", "_", str(source).casefold()).strip("_")[:64]
        with self._lock, _process_write_lock(self.state_path):
            self._state = self._load(now)
            current = self._current(mode, now)
            # Near satiety responds strongly to the immediate consequence;
            # background satiety accumulates gently across the broader day.
            near_gain = intensity
            background_gain = intensity * 0.42
            updated = {
                "near": _union(current["near"], near_gain),
                "background": _union(
                    current["background"], background_gain),
                "touched_at": now,
            }
            self._state["modes"][mode] = updated
            event = {
                "at": now, "mode": mode,
                "outcome": outcome or "realized",
                "source": source or "autonomy",
                "intensity": intensity,
            }
            self._state["events"].append(event)
            self._state["events"] = self._state["events"][
                -int(self.config["max_events"]):]
            self._save()
            self._receipt("activity_realized", **event)
            return {
                **event,
                "satiety": round(self._current(mode, now)["satiety"], 6),
            }

    def project(self, signals: Mapping[str, Any] | None = None, *,
                now: float | None = None,
                enabled: bool | None = None) -> dict:
        """Project appetites from current relationships and decayed satiety."""
        now = time.time() if now is None else float(now)
        active = (bool(self.config["enabled"])
                  if enabled is None else bool(enabled))
        values = {key: _bounded(value)
                  for key, value in dict(signals or {}).items()}
        with self._lock:
            # Atomic replace makes an unlocked read safe; avoiding the process
            # lock here also keeps status/projection paths genuinely write-free.
            self._state = self._load(now)
            modes = {mode: self._current(mode, now) for mode in MODES}

        # Sparse projections are the normal contract: a caller supplies only
        # the relationships it can currently observe.  An absent opportunity
        # is zero, while the few organism-wide balance terms retain neutral
        # defaults below.
        signal = lambda key: values.get(key, 0.0)
        capacity = values.get("capacity", 0.5)
        readiness = values.get("readiness", capacity)
        coherence = values.get("coherence", 0.5)
        recovery = values.get("recovery_need", 1.0 - capacity)
        recent_load = _union(*(modes[mode]["satiety"] for mode in MODES
                               if mode != "quiet"))
        bases = {
            "company": _union(
                signal("peer_presence") * values.get("relationship", .5),
                signal("relational_change"),
                signal("company_candidate_pressure")) * readiness,
            "reflection": _union(
                signal("unresolved"), signal("memory_pressure"),
                signal("reflection_candidate_pressure")) *
                (0.34 + 0.66 * readiness),
            "outward": _union(
                signal("world_change"), signal("question_pressure"),
                signal("outward_candidate_pressure"),
                signal("outward_available") * .38) * capacity,
            "making": _union(
                signal("project_pressure"),
                signal("making_candidate_pressure"),
                signal("making_available") * .32) * readiness,
            "embodiment": _union(
                signal("body_intensity"),
                signal("embodiment_candidate_pressure"),
                signal("embodiment_available") * .34) * capacity *
                (1.0 - .62 * recovery),
            "quiet": _union(
                recovery, 1.0 - capacity, 1.0 - coherence,
                recent_load * .46),
        }
        if not active:
            bases = {mode: 0.0 for mode in MODES}
        appetites = {}
        for mode in MODES:
            satiety = modes[mode]["satiety"]
            # Recovery from satiety can reopen a family, but only a live base
            # relationship can give it any pull at all.
            appetites[mode] = _bounded(
                bases[mode] * (1.0 - .72 * satiety))
        dominant = sorted(
            (mode for mode in MODES if appetites[mode] > 0.0),
            key=lambda mode: (-appetites[mode], mode))
        return {
            "schema_version": SCHEMA_VERSION,
            "owner": self.owner,
            "enabled": active,
            "observed_at": now,
            "satiety": {mode: round(modes[mode]["satiety"], 6)
                        for mode in MODES},
            "appetite": {mode: round(appetites[mode], 6)
                         for mode in MODES},
            "base_pull": {mode: round(_bounded(bases[mode]), 6)
                          for mode in MODES},
            "dominant_available_modes": dominant[:3],
            "recent_realized": list(self._state.get("events", []))[-12:],
            "policy": {
                "creates_openings": False,
                "creates_topics": False,
                "selects_activity": False,
                "speech_frequency_is_not_success": True,
                "quiet_is_activity": True,
                "elapsed_time_alone_is_insufficient": True,
                "content_free": True,
            },
        }

    def selection_modifier(self, candidate: Mapping[str, Any], projection: dict) -> dict:
        """Return a modest family-level bend for an existing candidate."""
        mode = candidate_mode(candidate)
        if (not self.config["enabled"]
                or not bool(projection.get("enabled", True))):
            return {"mode": mode, "modifier": 1.0,
                    "enabled": False}
        appetite = _bounded((projection.get("appetite") or {}).get(mode))
        satiety = _bounded((projection.get("satiety") or {}).get(mode))
        raw = 1.0 + .46 * (appetite - .5) - .34 * satiety
        modifier = max(
            float(self.config["modifier_floor"]),
            min(float(self.config["modifier_ceiling"]), raw))
        return {
            "mode": mode,
            "appetite": round(appetite, 6),
            "satiety": round(satiety, 6),
            "modifier": round(modifier, 6),
            "enabled": True,
        }

    def snapshot(self, *, now: float | None = None) -> dict:
        """Return stored circulation without inventing current opportunities."""
        return self.project({}, now=now)

    def resource_status(self, *, now: float | None = None) -> dict:
        """Read realized-activity context without projecting or changing it."""
        now = time.time() if now is None else float(now)
        with self._lock:
            state = self._load(now)
        modes = {mode: self._current(mode, now, state=state) for mode in MODES}
        events = list(state.get("events") or ())
        latest_at = max((float(row.get("at") or 0.0) for row in events),
                        default=0.0)
        nonquiet = [modes[mode]["satiety"] for mode in MODES
                    if mode != "quiet"]
        return {
            "enabled": bool(self.config["enabled"]),
            "mode_count": len(MODES),
            "realized_event_count": len(events),
            "latest_realized_age_s": (
                max(0.0, now - latest_at) if latest_at else None),
            "max_nonquiet_satiety": max(nonquiet, default=0.0),
            "quiet_satiety": modes["quiet"]["satiety"],
            "content_free": True,
            "read_only": True,
            "state_replaced": False,
        }
