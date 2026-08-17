"""Event-driven ingress for resident-owned work waiting on attention.

Payloads live only in process memory.  Durable receipts deliberately contain
only lifecycle metadata so camera frames, acoustic features, room content, and
model text cannot leak through the observability seam.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum
import json
import os
import threading
import time
import uuid
from typing import Any, Callable


class ResidentEventKind(str, Enum):
    CAMERA_EPISODE = "camera_episode"
    CAMERA_INTERPRETATION = "camera_interpretation"
    ORIENTATION_OFFER = "orientation_offer"
    ACOUSTIC_FEATURES = "acoustic_features"
    ROOM_REVISION = "room_revision"
    TEMPORAL_THRESHOLD = "temporal_threshold"
    WORLD_AWARENESS = "world_awareness"
    AUTONOMOUS_OUTCOME = "autonomous_outcome"


@dataclass(frozen=True)
class ResidentEvent:
    """One threshold- or revision-triggered event awaiting resident attention."""

    kind: ResidentEventKind
    source: str
    trigger: str
    payload: Any = field(repr=False, compare=False)
    coalesce_key: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    offered_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not isinstance(self.kind, ResidentEventKind):
            object.__setattr__(self, "kind", ResidentEventKind(self.kind))
        for name in ("source", "trigger"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"resident event {name} is required")


class ResidentEventMailbox:
    """A bounded, coalescing mailbox with an event-driven attention worker.

    The mailbox does not decide whether an event is salient and it never calls
    a model by itself.  Upstream anatomy decides when to offer an event; the
    supplied handler preserves the existing admission and consequence paths.
    """

    SCHEMA_VERSION = 1

    def __init__(self, receipt_path: str | None = None, max_pending: int = 32):
        if int(max_pending) < 1:
            raise ValueError("max_pending must be positive")
        self.receipt_path = str(receipt_path or "")
        self.max_pending = int(max_pending)
        self.boot_id = uuid.uuid4().hex
        self._condition = threading.Condition()
        self._receipt_lock = threading.Lock()
        self._pending: deque[ResidentEvent] = deque()
        self._by_key: dict[str, ResidentEvent] = {}
        self._counts: Counter[str] = Counter()
        self._closed = False

    def offer(self, event: ResidentEvent) -> dict:
        """Offer an event, replacing an older pending event with the same key."""
        if not isinstance(event, ResidentEvent):
            raise TypeError("mailbox accepts ResidentEvent values")
        with self._condition:
            if self._closed:
                return self._record(event, "rejected", outcome="closed")

            prior = self._by_key.get(event.coalesce_key) if event.coalesce_key else None
            if prior is not None:
                for index, pending in enumerate(self._pending):
                    if pending.event_id == prior.event_id:
                        self._pending[index] = event
                        break
                self._by_key[event.coalesce_key] = event
                self._record(prior, "superseded", outcome="newer_event")
                receipt = self._record(
                    event, "offered", outcome="coalesced", coalesced=True)
                # Typed workers share this condition.  Every lane must recheck
                # its own predicate; waking an unrelated lane cannot consume
                # the only causal wakeup.
                self._condition.notify_all()
                return receipt

            if len(self._pending) >= self.max_pending:
                return self._record(event, "rejected", outcome="capacity")

            self._pending.append(event)
            if event.coalesce_key:
                self._by_key[event.coalesce_key] = event
            receipt = self._record(event, "offered", outcome="queued")
            self._condition.notify_all()
            return receipt

    def run(self, turn_lock, handler: Callable[[ResidentEvent], str | None], stop,
            kinds=None):
        """Dispatch one typed lane; event arrival and lease release are its clocks."""
        allowed = (frozenset(ResidentEventKind(kind) for kind in kinds)
                   if kinds is not None else None)
        while True:
            event = self._take(stop, allowed)
            if event is None:
                return
            turn_lock.acquire()
            try:
                self._record(event, "started")
                try:
                    outcome = str(handler(event) or "handled")
                except Exception as exc:
                    self._record(
                        event, "failed", outcome=exc.__class__.__name__)
                else:
                    self._record(event, "settled", outcome=outcome)
            finally:
                turn_lock.release()

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def status(self) -> dict:
        with self._condition:
            pending = list(self._pending)
            return {
                "schema_version": self.SCHEMA_VERSION,
                "closed": self._closed,
                "depth": len(pending),
                "capacity": self.max_pending,
                "pending_by_kind": dict(Counter(e.kind.value for e in pending)),
                "lifecycle_counts": dict(self._counts),
                "oldest_age_s": (
                    round(max(0.0, time.time() - pending[0].offered_at), 3)
                    if pending else None),
                "payload_persistence": "none",
                "receipt_content": "lifecycle_metadata_only",
            }

    def _take(self, stop, allowed=None) -> ResidentEvent | None:
        with self._condition:
            while True:
                if self._closed or stop.is_set():
                    return None
                index = next((index for index, event in enumerate(self._pending)
                              if allowed is None or event.kind in allowed), None)
                if index is not None:
                    break
                self._condition.wait()
            event = self._pending[index]
            del self._pending[index]
            if (event.coalesce_key
                    and self._by_key.get(event.coalesce_key) is event):
                del self._by_key[event.coalesce_key]
            return event

    def _record(self, event: ResidentEvent, stage: str, *, outcome: str = "",
                coalesced: bool = False) -> dict:
        with self._condition:
            self._counts[stage] += 1
            receipt = {
                "schema_version": self.SCHEMA_VERSION,
                "at": time.time(),
                "boot_id": self.boot_id,
                "event_id": event.event_id,
                "kind": event.kind.value,
                "source": str(event.source),
                "trigger": str(event.trigger),
                "stage": stage,
                "outcome": str(outcome),
                "coalesced": bool(coalesced),
                "queue_depth": len(self._pending),
            }
        if self.receipt_path:
            directory = os.path.dirname(self.receipt_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            line = json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n"
            with self._receipt_lock:
                with open(self.receipt_path, "a", encoding="utf-8") as stream:
                    stream.write(line)
                    stream.flush()
                    os.fsync(stream.fileno())
        return dict(receipt)
