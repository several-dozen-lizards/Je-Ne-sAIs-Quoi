"""Resident-owned optional orientation toward content-free motion evidence.

This is synthetic control anatomy, not a claim about biological orienting or
subjective attention.  Browser motion makes an opportunity available.  The
resident's existing rhythm/body readiness, current occupation, and recurrence
shape whether that opportunity is admitted and selected.  No selection can
create language, emotion, memory, or a follow-up action chain.
"""
from __future__ import annotations

from collections import Counter
import json
import math
import os
import threading
import time
import uuid

from core.sensory import SensoryOrgan


def _unit(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _axis(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(-1.0, min(1.0, number))


class OrientationField:
    """Event-driven opportunity field with no clock or autonomous thread."""

    SCHEMA_VERSION = 1

    def __init__(self, receipt_path: str | None = None):
        self.receipt_path = str(receipt_path or "")
        self._lock = threading.Lock()
        self._receipt_lock = threading.Lock()
        self._last_target = None
        self._habituation = 0.0
        self._selected = set()
        self._outward_active = False
        self._counts = Counter()
        self._last_outcome = "quiet"

    def offer(self, *, x: float, y: float, evidence: float,
              bands=None, coherence: float = 1.0,
              readiness: float = 0.0, hard_blocked: bool = False,
              occupied: bool = False, active_private_work: bool = False) -> dict:
        """Offer motion without granting it motor authority."""
        target = (_axis(x), _axis(y))
        evidence = _unit(evidence)
        readiness = _unit(readiness)
        occupied = bool(occupied or active_private_work)
        event_id = uuid.uuid4().hex

        with self._lock:
            if self._last_target is None:
                similarity = 0.0
                habituation = self._habituation * 0.25
            else:
                distance = math.dist(target, self._last_target)
                similarity = _unit(1.0 - distance)
                # Recurrence strengthens satiation; displacement loosens it.
                # This advances only when the world supplies another event.
                retention = 0.35 + 0.45 * similarity
                habituation = _unit(
                    self._habituation * retention
                    + similarity * evidence * 0.20)
            self._last_target = target
            self._habituation = habituation

            policy = SensoryOrgan.policy(
                bands=bands, coherence=coherence, occupied=occupied)
            threshold = _unit(policy["threshold"])
            admitted = evidence >= threshold
            available_pull = evidence * (0.55 + 0.45 * readiness)
            selected_pull = available_pull * (1.0 - 0.65 * habituation)
            selected = bool(
                admitted and not hard_blocked and selected_pull >= threshold)
            if selected:
                self._selected.add(event_id)
                outcome = "selected"
            elif admitted:
                outcome = "admitted_quiet"
            else:
                outcome = "available"
            self._last_outcome = outcome
            self._counts["available"] += 1
            if admitted:
                self._counts["internally_admitted"] += 1
            if selected:
                self._counts["selected"] += 1
            else:
                self._counts["quiet"] += 1

        receipt = {
            "schema_version": self.SCHEMA_VERSION,
            "event_id": event_id,
            "stage": outcome,
            "internally_admitted": admitted,
            "selected": selected,
            "expressed": False,
            "evidence": round(evidence, 6),
            "selected_pull": round(selected_pull, 6),
            "boundary": round(threshold, 6),
            "readiness": round(readiness, 6),
            "habituation": round(habituation, 6),
            "occupied": occupied,
            "active_private_work": bool(active_private_work),
            "hard_blocked": bool(hard_blocked),
            "quiet_valid": True,
            "action_chain": False,
        }
        self._record(receipt)
        return dict(receipt)

    def record_expression(self, event_id: str, expressed: bool) -> dict:
        """Bind an actuator receipt to an exact selected opportunity."""
        event_id = str(event_id or "")
        with self._lock:
            selected = event_id in self._selected
            expressed = bool(selected and expressed)
            self._selected.discard(event_id)
            if expressed:
                self._outward_active = True
                self._counts["outwardly_expressed"] += 1
                stage = "outwardly_expressed"
            else:
                self._counts["selected_unexpressed"] += int(selected)
                stage = "selected_unexpressed" if selected else "not_selected"
        receipt = {
            "schema_version": self.SCHEMA_VERSION,
            "event_id": event_id,
            "stage": stage,
            "selected": selected,
            "expressed": expressed,
            "quiet_valid": True,
            "action_chain": False,
        }
        self._record(receipt)
        return receipt

    def release(self) -> dict:
        """Relinquish an existing gaze claim; never choose a replacement."""
        with self._lock:
            was_active = self._outward_active
            self._outward_active = False
            if was_active:
                self._counts["released"] += 1
        receipt = {
            "schema_version": self.SCHEMA_VERSION,
            "event_id": uuid.uuid4().hex,
            "stage": "released" if was_active else "already_quiet",
            "selected": False,
            "expressed": False,
            "replacement_selected": False,
            "action_chain": False,
        }
        if was_active:
            self._record(receipt)
        return receipt

    def status(self) -> dict:
        with self._lock:
            return {
                "schema_version": self.SCHEMA_VERSION,
                "mode": "causal_optional_orientation",
                "event_clock": "motion_threshold_crossing",
                "outward_active": self._outward_active,
                "last_outcome": self._last_outcome,
                "habituation": round(self._habituation, 6),
                "lifecycle_counts": dict(self._counts),
                "quiet_valid": True,
                "action_chain": False,
                "creates_language": False,
                "creates_memory": False,
                "stores_target_coordinates": False,
                "receipt_content": "content_free_control_metadata_only",
            }

    def _record(self, receipt: dict):
        if not self.receipt_path:
            return
        record = {"at": time.time(), **receipt}
        # Target coordinates never enter the receipt schema.
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        directory = os.path.dirname(self.receipt_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self._receipt_lock:
            with open(self.receipt_path, "a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
