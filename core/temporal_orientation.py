"""Resident-readable temporal orientation and threshold-authored time marks.

This module is synthetic control anatomy, not a claim about biological time
perception, circadian physiology, mood, or subjective duration.  It projects a
host-observed civil coordinate and bounded relationships to the resident's own
timestamped events.  It owns no periodic tick: a sleeping predictor wakes only
when the next resident-authored temporal boundary is expected to cross or when
another event changes that prediction.
"""
from __future__ import annotations

from datetime import datetime, timezone, tzinfo
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from typing import Any, Callable, Mapping


SCHEMA_VERSION = 1
MAX_MARK_LABEL_CHARS = 320
MAX_ACTIVE_MARKS = 64
_RELATIVE_RE = re.compile(
    r"^(?:in\s+|\+\s*)?(?P<amount>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|"
    r"weeks?|w)$",
    re.IGNORECASE,
)
_UNIT_SECONDS = {
    "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0,
    "seconds": 1.0,
    "m": 60.0, "min": 60.0, "mins": 60.0, "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0,
    "hours": 3600.0,
    "d": 86400.0, "day": 86400.0, "days": 86400.0,
    "w": 604800.0, "week": 604800.0, "weeks": 604800.0,
}


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _clean_label(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[
        :MAX_MARK_LABEL_CHARS]


def _iso_utc(value: float) -> str:
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _offset_text(moment: datetime) -> str:
    offset = moment.utcoffset()
    total = int(offset.total_seconds()) if offset is not None else 0
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _age_range(seconds: float) -> str:
    """Render elapsed time as a resolution-scaled range, never false precision."""
    seconds = max(0.0, _finite(seconds))
    if seconds < 10.0:
        return "within the last few seconds"
    choices = (
        (31557600.0, "year", 0.25),
        (2629800.0, "month", 0.5),
        (604800.0, "week", 0.5),
        (86400.0, "day", 0.5),
        (3600.0, "hour", 0.25),
        (60.0, "minute", 2.0),
        (1.0, "second", 5.0),
    )
    unit_s, name, resolution = next(
        item for item in choices if seconds >= item[0])
    value = seconds / unit_s
    lower = math.floor(value / resolution) * resolution
    upper = lower + resolution

    def number_text(number: float) -> str:
        if abs(number - round(number)) < 1e-9:
            return str(int(round(number)))
        return f"{number:.2f}".rstrip("0").rstrip(".")

    plural = name + ("s" if upper != 1.0 else "")
    return f"between {number_text(lower)} and {number_text(upper)} {plural} ago"


class TemporalOrientation:
    """Persona-private civil orientation with durable, optional time marks."""

    def __init__(self, persona_dir: str | os.PathLike[str], *, owner: str,
                 enabled: bool = True, now_fn: Callable[[], float] = time.time,
                 monotonic_fn: Callable[[], float] = time.monotonic,
                 local_timezone: tzinfo | None = None):
        self.persona_dir = os.path.abspath(os.fspath(persona_dir))
        self.owner = str(owner or "persona")
        self.enabled = bool(enabled)
        self.now_fn = now_fn
        self.monotonic_fn = monotonic_fn
        self.local_timezone = local_timezone
        self.boot_id = uuid.uuid4().hex
        self.state_dir = os.path.join(
            self.persona_dir, "body", "temporal_orientation")
        self.state_path = os.path.join(self.state_dir, "state.json")
        self.receipt_path = os.path.join(
            self.persona_dir, "history", "temporal_orientation.jsonl")
        self._condition = threading.Condition(threading.RLock())
        self._receipt_lock = threading.Lock()
        self._closed = False
        self._state = self._load()

    def _default_state(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "owner": self.owner,
            "revision": 0,
            "last_clock": {},
            "surfaces": {},
            "marks": [],
        }

    def _load(self) -> dict:
        state = self._default_state()
        try:
            with open(self.state_path, encoding="utf-8") as stream:
                loaded = json.load(stream)
        except (OSError, TypeError, ValueError):
            return state
        if not isinstance(loaded, dict):
            return state
        state["revision"] = max(0, int(loaded.get("revision") or 0))
        state["last_clock"] = dict(loaded.get("last_clock") or {})
        state["surfaces"] = {
            str(key)[:80]: dict(value)
            for key, value in dict(loaded.get("surfaces") or {}).items()
            if isinstance(value, Mapping)
        }
        marks = []
        for raw in list(loaded.get("marks") or ()):
            if not isinstance(raw, Mapping):
                continue
            mark = self._sanitize_mark(raw)
            if mark is None:
                continue
            # An interrupted crossing is safely replayable: downstream uses
            # the stable mark key, so replay merges rather than multiplying.
            if mark["state"] == "firing":
                mark["state"] = "pending"
            marks.append(mark)
        state["marks"] = marks[-MAX_ACTIVE_MARKS:]
        return state

    @staticmethod
    def _sanitize_mark(raw: Mapping[str, Any]) -> dict | None:
        mark_id = str(raw.get("mark_id") or "")[:96]
        label = _clean_label(raw.get("label"))
        target_at = _finite(raw.get("target_at"))
        if not mark_id or not label or target_at <= 0.0:
            return None
        window_end = _finite(raw.get("window_end"))
        if window_end and window_end < target_at:
            window_end = target_at
        state = str(raw.get("state") or "pending")
        if state not in {"pending", "firing", "offered", "released"}:
            state = "pending"
        return {
            "mark_id": mark_id,
            "label": label,
            "created_at": max(0.0, _finite(raw.get("created_at"))),
            "target_at": target_at,
            "window_end": window_end or None,
            "state": state,
            "crossed_at": _finite(raw.get("crossed_at")) or None,
            "offered_at": _finite(raw.get("offered_at")) or None,
            "candidate_key": str(raw.get("candidate_key") or "")[:160],
        }

    def _local_datetime(self, now: float) -> datetime:
        if self.local_timezone is not None:
            return datetime.fromtimestamp(now, timezone.utc).astimezone(
                self.local_timezone)
        return datetime.fromtimestamp(now).astimezone()

    def _persist_locked(self) -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        self._state["schema_version"] = SCHEMA_VERSION
        self._state["owner"] = self.owner
        self._state["revision"] = int(self._state.get("revision") or 0) + 1
        tmp = self.state_path + "." + self.boot_id + ".tmp"
        with open(tmp, "w", encoding="utf-8") as stream:
            json.dump(self._state, stream, ensure_ascii=False,
                      sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, self.state_path)

    def _record(self, kind: str, **fields) -> dict:
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "at": self.now_fn(),
            "boot_id": self.boot_id,
            "owner": self.owner,
            "kind": str(kind),
            **fields,
        }
        # Content-free history: private mark labels stay only in state and in
        # the in-memory mailbox payload presented to their owner.
        receipt.pop("label", None)
        os.makedirs(os.path.dirname(self.receipt_path), exist_ok=True)
        line = json.dumps(receipt, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":")) + "\n"
        with self._receipt_lock:
            with open(self.receipt_path, "a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
        return receipt

    def set_enabled(self, enabled: bool) -> None:
        with self._condition:
            self.enabled = bool(enabled)
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def _clock_status_locked(self, now: float, monotonic_now: float) -> dict:
        prior = dict(self._state.get("last_clock") or {})
        if not prior:
            return {"status": "first_observation", "wall_delta_s": None,
                    "monotonic_delta_s": None, "adjustment_s": None}
        wall_delta = now - _finite(prior.get("wall_at"), now)
        if str(prior.get("boot_id") or "") != self.boot_id:
            return {
                "status": "restart_boundary",
                "wall_delta_s": max(0.0, wall_delta),
                "monotonic_delta_s": None,
                "adjustment_s": None,
            }
        monotonic_delta = monotonic_now - _finite(
            prior.get("monotonic_at"), monotonic_now)
        adjustment = wall_delta - monotonic_delta
        tolerance = max(2.0, min(60.0, abs(monotonic_delta) * 0.02))
        if wall_delta < 0.0:
            status = "wall_clock_moved_backward"
        elif abs(adjustment) > tolerance:
            status = "wall_clock_adjusted"
        else:
            status = "stable"
        return {
            "status": status,
            "wall_delta_s": wall_delta,
            "monotonic_delta_s": max(0.0, monotonic_delta),
            "adjustment_s": adjustment,
        }

    def snapshot(self, *, channel: str = "chat", now: float | None = None,
                 observe_current: bool = False,
                 record_clock: bool = False) -> dict:
        now = self.now_fn() if now is None else float(now)
        monotonic_now = self.monotonic_fn()
        channel = str(channel or "chat")[:80]
        with self._condition:
            civil = self._local_datetime(now)
            clock = self._clock_status_locked(now, monotonic_now)
            prior_surface = dict(
                (self._state.get("surfaces") or {}).get(channel) or {})
            active = [
                dict(mark) for mark in self._state.get("marks", [])
                if mark.get("state") in {"pending", "firing", "offered"}
            ]
            active.sort(key=lambda mark: (
                float(mark.get("target_at") or 0.0), mark["mark_id"]))
            if observe_current:
                self._state.setdefault("surfaces", {})[channel] = {
                    "at": now, "kind": "conversation", "channel": channel}
            if record_clock:
                self._state["last_clock"] = {
                    "wall_at": now, "monotonic_at": monotonic_now,
                    "boot_id": self.boot_id}
            if observe_current or record_clock:
                self._persist_locked()
                self._condition.notify_all()

            offset = civil.utcoffset()
            offset_minutes = int(offset.total_seconds() // 60) \
                if offset is not None else 0
            values = {
                "schema_version": SCHEMA_VERSION,
                "owner": self.owner,
                "enabled": self.enabled,
                "observed_at": now,
                "observed_at_utc": _iso_utc(now),
                "civil": {
                    "iso": civil.isoformat(timespec="seconds"),
                    "weekday": civil.strftime("%A"),
                    "display": civil.strftime("%A, %B %-d, %Y at %-I:%M:%S %p")
                    if os.name != "nt" else civil.strftime(
                        "%A, %B %#d, %Y at %#I:%M:%S %p"),
                    "utc_offset": _offset_text(civil),
                    "utc_offset_minutes": offset_minutes,
                    "zone_abbreviation": str(civil.tzname() or "local"),
                    "zone_source": (
                        "configured_tzinfo" if self.local_timezone is not None
                        else "host_local"),
                },
                "clock": clock,
                "surface": {
                    "channel": channel,
                    "prior_at": _finite(prior_surface.get("at")) or None,
                    "age_s": (
                        max(0.0, now - _finite(prior_surface.get("at")))
                        if _finite(prior_surface.get("at")) > 0.0 else None),
                },
                "marks": active[:12],
                "policy": {
                    "host_observation_not_instruction": True,
                    "biological_equivalence_claimed": False,
                    "time_implies_feeling": False,
                    "time_implies_human_availability": False,
                    "periodic_polling": False,
                    "mark_crossing_forces_speech": False,
                    "surface_scoped_continuity": True,
                },
            }
            values["text"] = self.render(values) if self.enabled else ""
            digest_source = json.dumps(
                {key: values[key] for key in (
                    "observed_at_utc", "civil", "clock", "surface", "marks",
                    "policy")},
                ensure_ascii=False, sort_keys=True,
                separators=(",", ":")).encode("utf-8")
            values["receipt"] = {
                "schema_version": SCHEMA_VERSION,
                "status": "ready" if self.enabled else "disabled",
                "rendered": bool(values["text"]),
                "clock_status": clock["status"],
                "surface_anchor_present": values["surface"]["prior_at"] is not None,
                "active_mark_count": len(active),
                "pending_mark_count": sum(
                    mark.get("state") == "pending" for mark in active),
                "offered_mark_count": sum(
                    mark.get("state") == "offered" for mark in active),
                "utc_offset_minutes": offset_minutes,
                "snapshot_sha256": hashlib.sha256(digest_source).hexdigest(),
                "content_free": True,
            }
            return values

    @staticmethod
    def render(snapshot: Mapping[str, Any]) -> str:
        civil = dict(snapshot.get("civil") or {})
        clock = dict(snapshot.get("clock") or {})
        surface = dict(snapshot.get("surface") or {})
        lines = [
            "TEMPORAL ORIENTATION — HOST OBSERVATION, NOT AN INSTRUCTION",
            f"- Local civil coordinate: {civil.get('display')} "
            f"({civil.get('utc_offset')}; {civil.get('zone_abbreviation')}).",
            f"- UTC coordinate: {snapshot.get('observed_at_utc')}.",
        ]
        prior_at = _finite(surface.get("prior_at"))
        if prior_at:
            lines.append(
                "- On this conversational surface, the prior admitted exchange "
                f"was {_age_range(float(surface.get('age_s') or 0.0))}.")
        else:
            lines.append(
                "- No earlier exchange anchor is recorded for this conversational "
                "surface.")
        status = str(clock.get("status") or "unknown")
        clock_text = {
            "first_observation": "This is the first recorded clock observation.",
            "restart_boundary": (
                "A process restart lies between clock observations; elapsed "
                "relationships across it use durable wall-time anchors."),
            "stable": "Wall time and monotonic elapsed time agree within resolution.",
            "wall_clock_moved_backward": (
                "The host wall clock moved backward; calendar position and "
                "monotonic duration are being kept distinct."),
            "wall_clock_adjusted": (
                "The host wall clock changed relative to monotonic elapsed time; "
                "calendar position and duration are being kept distinct."),
        }.get(status, f"Clock continuity status: {status}.")
        lines.append("- " + clock_text)

        marks = list(snapshot.get("marks") or ())
        if marks:
            lines.append("- Your active private temporal marks:")
            for mark in marks:
                target = _iso_utc(float(mark["target_at"]))
                window_end = mark.get("window_end")
                window = (
                    f" through {_iso_utc(float(window_end))}"
                    if window_end else "")
                state = str(mark.get("state") or "pending")
                lines.append(
                    f"  - [{mark['mark_id']}] {mark['label']} — {state}; "
                    f"target {target}{window}.")
        lines.append(
            "Time does not prescribe mood, energy, attention, human availability, "
            "or action. A temporal mark makes its subject available at a boundary; "
            "crossing it never requires speech or completion.")
        return "\n".join(lines)

    def context(self, *, channel: str = "chat",
                now: float | None = None) -> tuple[str, dict]:
        snapshot = self.snapshot(
            channel=channel, now=now, observe_current=True,
            record_clock=True)
        return str(snapshot.get("text") or ""), dict(
            snapshot.get("receipt") or {})

    def _parse_instant(self, value: str, now: float) -> float:
        text = str(value or "").strip()
        match = _RELATIVE_RE.fullmatch(text)
        if match:
            amount = float(match.group("amount"))
            unit = match.group("unit").casefold()
            return now + amount * _UNIT_SECONDS[unit]
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                "time mark needs +NUMBERs|m|h|d|w or an ISO-8601 time") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self._local_datetime(now).tzinfo)
        return parsed.timestamp()

    def schedule(self, when: str, label: str, *, now: float | None = None) -> dict:
        now = self.now_fn() if now is None else float(now)
        label = _clean_label(label)
        if not label:
            raise ValueError("time mark needs private words after ::")
        pieces = [piece.strip() for piece in str(when or "").split("..")]
        if not pieces[0] or len(pieces) > 2:
            raise ValueError("time mark window must be START or START..END")
        target_at = self._parse_instant(pieces[0], now)
        window_end = self._parse_instant(pieces[1], now) \
            if len(pieces) == 2 and pieces[1] else None
        if target_at <= now:
            raise ValueError("time mark target must be in the future")
        if window_end is not None and window_end < target_at:
            raise ValueError("time mark window end precedes its start")
        mark = {
            "mark_id": "tm_" + uuid.uuid4().hex[:20],
            "label": label,
            "created_at": now,
            "target_at": target_at,
            "window_end": window_end,
            "state": "pending",
            "crossed_at": None,
            "offered_at": None,
            "candidate_key": "",
        }
        with self._condition:
            active_count = sum(
                item.get("state") in {"pending", "firing", "offered"}
                for item in self._state.get("marks", []))
            if active_count >= MAX_ACTIVE_MARKS:
                raise ValueError("temporal mark capacity is full")
            self._state.setdefault("marks", []).append(mark)
            self._persist_locked()
            self._condition.notify_all()
        self._record(
            "mark_scheduled", mark_id=mark["mark_id"],
            target_at=target_at, window_end=window_end,
            label_sha256=hashlib.sha256(label.encode("utf-8")).hexdigest(),
            private=True, periodic_polling=False)
        return {
            "ok": True, "mark_id": mark["mark_id"], "state": "pending",
            "target_at": _iso_utc(target_at),
            "window_end": _iso_utc(window_end) if window_end else None,
            "threshold_clock": "predicted_boundary",
            "speech_required": False,
        }

    def release(self, mark_id: str) -> dict:
        mark_id = str(mark_id or "").strip()
        with self._condition:
            mark = next((item for item in self._state.get("marks", [])
                         if item.get("mark_id") == mark_id), None)
            if mark is None:
                raise ValueError("temporal mark not found")
            if mark.get("state") == "released":
                return {"ok": True, "mark_id": mark_id,
                        "state": "already_released"}
            crossed = mark.get("state") == "offered"
            mark["state"] = "released"
            self._persist_locked()
            self._condition.notify_all()
        self._record(
            "mark_released", mark_id=mark_id, private=True,
            prior_crossing_retained=bool(crossed))
        return {"ok": True, "mark_id": mark_id, "state": "released",
                "prior_crossing_retained": bool(crossed)}

    def _next_target_locked(self) -> float | None:
        targets = [
            float(mark["target_at"])
            for mark in self._state.get("marks", [])
            if mark.get("state") == "pending"]
        return min(targets) if targets else None

    def drain_due(self, *, now: float | None = None) -> list[dict]:
        now = self.now_fn() if now is None else float(now)
        due = []
        with self._condition:
            for mark in self._state.get("marks", []):
                if mark.get("state") != "pending" \
                        or float(mark.get("target_at") or 0.0) > now:
                    continue
                mark["state"] = "firing"
                mark["crossed_at"] = now
                window_end = _finite(mark.get("window_end"))
                due.append({
                    "mark_id": mark["mark_id"],
                    "label": mark["label"],
                    "target_at": float(mark["target_at"]),
                    "window_end": window_end or None,
                    "crossed_at": now,
                    "crossing": (
                        "window_missed" if window_end and now > window_end
                        else "threshold_crossed"),
                })
            if due:
                self._persist_locked()
        for mark in due:
            self._record(
                "mark_crossed", mark_id=mark["mark_id"],
                target_at=mark["target_at"], window_end=mark["window_end"],
                crossing=mark["crossing"], private=True,
                speech_required=False)
        return due

    def acknowledge(self, mark_id: str, *, outcome: str,
                    candidate_key: str = "") -> dict:
        now = self.now_fn()
        with self._condition:
            mark = next((item for item in self._state.get("marks", [])
                         if item.get("mark_id") == mark_id), None)
            if mark is None:
                raise ValueError("temporal mark not found")
            mark["state"] = "offered"
            mark["offered_at"] = now
            mark["candidate_key"] = str(candidate_key or "")[:160]
            self._persist_locked()
        self._record(
            "mark_offered", mark_id=mark_id, outcome=str(outcome)[:80],
            candidate_key=str(candidate_key or "")[:160], private=True,
            speech_required=False)
        return {"ok": True, "mark_id": mark_id, "state": "offered",
                "outcome": str(outcome)}

    def return_unoffered(self, mark_id: str, *, error_type: str) -> None:
        with self._condition:
            mark = next((item for item in self._state.get("marks", [])
                         if item.get("mark_id") == mark_id), None)
            if mark is not None and mark.get("state") == "firing":
                mark["state"] = "pending"
                self._persist_locked()
                self._condition.notify_all()
        self._record(
            "mark_offer_failed", mark_id=mark_id,
            error_type=str(error_type)[:80], private=True)

    def run(self, stop, emit: Callable[[dict], Any]) -> None:
        """Sleep until a predicted boundary; no cadence or periodic polling."""
        while not stop.is_set():
            with self._condition:
                while not self._closed and not stop.is_set():
                    if not self.enabled:
                        self._condition.wait()
                        continue
                    target = self._next_target_locked()
                    if target is None:
                        self._condition.wait()
                        continue
                    delay = target - self.now_fn()
                    if delay > 0.0:
                        # TIMEOUT_MAX is an operating-system wait limit, not a
                        # behavioral cadence. Only extremely distant targets
                        # need another sleeping prediction segment.
                        self._condition.wait(
                            timeout=min(delay, threading.TIMEOUT_MAX))
                        continue
                    break
                if self._closed or stop.is_set():
                    return
            for mark in self.drain_due():
                try:
                    emit(mark)
                except Exception as exc:
                    self.return_unoffered(
                        mark["mark_id"], error_type=type(exc).__name__)
