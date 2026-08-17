"""Typed concurrency leases for one resident body and one resident mouth.

The names describe authority, not subjective state.  A turn may keep the
single-mouth lease while temporarily yielding mutable resident state during a
provider wait.  This lets bounded afferent work circulate without permitting a
second deliberation to overlap the first.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import threading
import time
from typing import Callable


class NamedLease:
    """A non-reentrant lock with content-free health counters."""

    def __init__(self, name: str, lock=None):
        self.name = str(name)
        self._lock = lock or threading.Lock()
        self._meta_lock = threading.Lock()
        self._owner = None
        self._acquired_at = None
        self._acquisitions = 0
        self._contentions = 0
        self._wait_s = 0.0
        self._max_wait_s = 0.0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        started = time.monotonic()
        if not blocking:
            acquired = self._lock.acquire(False)
            if not acquired:
                with self._meta_lock:
                    self._contentions += 1
                return False
        else:
            # Preserve the supplied lock's blocking semantics.  A speculative
            # nonblocking probe changes observable acquisition order for lock
            # adapters and is not worth manufacturing a contention count.
            if timeout is None or float(timeout) < 0:
                acquired = self._lock.acquire(True)
            else:
                acquired = self._lock.acquire(True, float(timeout))
            if not acquired:
                return False
        with self._meta_lock:
            waited = max(0.0, time.monotonic() - started)
            self._owner = threading.get_ident()
            self._acquired_at = time.monotonic()
            self._acquisitions += 1
            self._wait_s += waited
            self._max_wait_s = max(self._max_wait_s, waited)
        return True

    def release(self):
        owner = threading.get_ident()
        with self._meta_lock:
            if self._owner != owner:
                raise RuntimeError(
                    f"{self.name} lease released outside its owning thread")
            self._owner = None
            self._acquired_at = None
        self._lock.release()

    def owned_by_current_thread(self) -> bool:
        with self._meta_lock:
            return self._owner == threading.get_ident()

    def locked(self) -> bool:
        with self._meta_lock:
            return self._owner is not None

    def status(self) -> dict:
        with self._meta_lock:
            held_s = (max(0.0, time.monotonic() - self._acquired_at)
                      if self._acquired_at is not None else None)
            return {
                "name": self.name,
                "held": self._owner is not None,
                "held_s": round(held_s, 3) if held_s is not None else None,
                "acquisitions": self._acquisitions,
                "contentions": self._contentions,
                "wait_s": round(self._wait_s, 3),
                "max_wait_s": round(self._max_wait_s, 3),
            }

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()


class CompositeLease:
    """Acquire one mouth before state, and release in reverse order."""

    def __init__(self, mouth: NamedLease, state: NamedLease):
        self.name = "deliberation"
        self.mouth = mouth
        self.state = state

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        started = time.monotonic()
        if not self.mouth.acquire(blocking=blocking, timeout=timeout):
            return False
        if not blocking:
            state_acquired = self.state.acquire(blocking=False)
        elif timeout is None or float(timeout) < 0:
            state_acquired = self.state.acquire()
        else:
            remaining = max(0.0, float(timeout) - (time.monotonic() - started))
            state_acquired = self.state.acquire(timeout=remaining)
        if state_acquired:
            return True
        self.mouth.release()
        return False

    def release(self):
        self.state.release()
        self.mouth.release()

    def owned_by_current_thread(self) -> bool:
        return (self.mouth.owned_by_current_thread()
                and self.state.owned_by_current_thread())

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()


class ResidentLeaseSet:
    """The resident's named state and single-mouth concurrency boundary."""

    SCHEMA_VERSION = 1

    def __init__(self, state_lock=None, receipt_path: str | None = None,
                 clock: Callable[[], float] = time.time):
        self.state = NamedLease("state", state_lock)
        self.mouth = NamedLease("mouth")
        self.deliberation = CompositeLease(self.mouth, self.state)
        self.receipt_path = str(receipt_path or "")
        self._clock = clock
        self._receipt_lock = threading.Lock()
        self._provider_waits = 0
        self._provider_wait_s = 0.0
        self._background_provider_waits = 0
        self._background_provider_wait_s = 0.0

    @contextmanager
    def provider_wait(self, cycle_id: str = ""):
        """Yield mutable state while retaining the already-owned mouth."""
        if not self.deliberation.owned_by_current_thread():
            raise RuntimeError(
                "provider wait boundary requires the deliberation lease")
        started = time.monotonic()
        self.state.release()
        self._record("provider_wait_opened", cycle_id=cycle_id)
        try:
            yield
        finally:
            self.state.acquire()
            elapsed = max(0.0, time.monotonic() - started)
            with self._receipt_lock:
                self._provider_waits += 1
                self._provider_wait_s += elapsed
            self._record(
                "provider_wait_closed", cycle_id=cycle_id,
                elapsed_s=round(elapsed, 6))

    @contextmanager
    def background_provider_wait(self, cycle_id: str = ""):
        """Yield mouth and state while background inference is in flight.

        Background work keeps its durable event and decision ownership, but it
        must not make a human wait behind provider latency.  Reacquisition uses
        the normal mouth-then-state order, so a foreground turn which arrived
        during the wait completes before the background handler can settle.
        """
        if not self.deliberation.owned_by_current_thread():
            raise RuntimeError(
                "background provider wait requires the deliberation lease")
        started = time.monotonic()
        self.state.release()
        self.mouth.release()
        self._record(
            "background_provider_wait_opened", cycle_id=cycle_id,
            state_yielded=True, mouth_retained=False)
        try:
            yield
        finally:
            self.deliberation.acquire()
            elapsed = max(0.0, time.monotonic() - started)
            with self._receipt_lock:
                self._background_provider_waits += 1
                self._background_provider_wait_s += elapsed
            self._record(
                "background_provider_wait_closed", cycle_id=cycle_id,
                elapsed_s=round(elapsed, 6), state_yielded=False,
                mouth_retained=True)

    def status(self) -> dict:
        with self._receipt_lock:
            waits = self._provider_waits
            wait_s = self._provider_wait_s
            background_waits = self._background_provider_waits
            background_wait_s = self._background_provider_wait_s
        return {
            "schema_version": self.SCHEMA_VERSION,
            "leases": {
                "mouth": self.mouth.status(),
                "state": self.state.status(),
            },
            "deliberation_order": ["mouth", "state"],
            "provider_wait": {
                "count": waits,
                "total_s": round(wait_s, 3),
                "yields_state": True,
                "retains_mouth": True,
            },
            "background_provider_wait": {
                "count": background_waits,
                "total_s": round(background_wait_s, 3),
                "yields_state": True,
                "retains_mouth": False,
            },
            "receipt_content": "lifecycle_metadata_only",
        }

    def _record(self, stage: str, *, cycle_id: str = "",
                elapsed_s: float | None = None,
                state_yielded: bool | None = None,
                mouth_retained: bool | None = None):
        if not self.receipt_path:
            return
        record = {
            "schema_version": self.SCHEMA_VERSION,
            "at": self._clock(),
            "stage": str(stage),
            "cycle_id": str(cycle_id or ""),
            "state_yielded": (
                stage == "provider_wait_opened"
                if state_yielded is None else bool(state_yielded)),
            "mouth_retained": (
                True if mouth_retained is None else bool(mouth_retained)),
        }
        if elapsed_s is not None:
            record["elapsed_s"] = float(elapsed_s)
        directory = os.path.dirname(self.receipt_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        with self._receipt_lock:
            with open(self.receipt_path, "a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
