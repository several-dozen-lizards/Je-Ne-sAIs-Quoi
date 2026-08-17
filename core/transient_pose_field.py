"""Resident-owned optional postural accommodation to motion evidence.

This is synthetic control anatomy, not biological posture or a claim about
subjective attention.  A motion crossing can make a small body vector
available.  Rhythm/body readiness and current occupation shape whether the
resident admits and selects it.  Selection cannot name a feeling, choose a
semantic gesture, create language or memory, or start another action.
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


class TransientPoseField:
    """Event-driven choice field; it owns no timer or semantic pose names."""

    SCHEMA_VERSION = 1

    def __init__(self, receipt_path: str | None = None):
        self.receipt_path = str(receipt_path or "")
        self._lock = threading.Lock()
        self._receipt_lock = threading.Lock()
        self._last_target = None
        self._habituation = 0.0
        self._selected = set()
        self._surface_active = False
        self._counts = Counter()
        self._last_outcome = "quiet"

    def offer(self, *, x: float, y: float, attention: float,
              motion: float = 0.0, novelty: float = 0.0,
              displacement: float = 0.0, bands=None,
              coherence: float = 1.0, readiness: float = 0.0,
              hard_blocked: bool = False, occupied: bool = False,
              active_private_work: bool = False) -> dict:
        """Offer one screen-relative tug without granting body authority."""
        target = (_axis(x), _axis(y))
        attention = _unit(attention)
        motion = _unit(motion)
        novelty = _unit(novelty)
        displacement = _unit(displacement)
        readiness = _unit(readiness)
        occupied = bool(occupied or active_private_work)
        # These are converging evidence dimensions, not a pose label.  Raw
        # motion is deliberately the lightest component because the browser's
        # adaptive novelty already measures change against its local baseline.
        evidence = _unit(
            attention * 0.50 + novelty * 0.25
            + displacement * 0.15 + motion * 0.10)
        event_id = uuid.uuid4().hex

        with self._lock:
            if self._last_target is None:
                similarity = 0.0
                habituation = self._habituation * 0.25
            else:
                distance = math.dist(target, self._last_target)
                similarity = _unit(1.0 - distance)
                habituation = _unit(
                    self._habituation * (0.38 + 0.42 * similarity)
                    + similarity * evidence * 0.22)
            self._last_target = target
            self._habituation = habituation

            policy = SensoryOrgan.policy(
                bands=bands, coherence=coherence, occupied=occupied)
            # Whole-body accommodation asks for slightly more converging
            # evidence than eye orientation, while remaining shaped by the
            # same oscillator-derived permeability.
            boundary = _unit(policy["threshold"] + 0.06)
            admitted = evidence >= boundary
            available_pull = evidence * (0.48 + 0.52 * readiness)
            if occupied:
                # Strong evidence may still be registered internally while a
                # current body/work owner keeps outward selection quiet.
                available_pull *= 0.74
            selected_pull = available_pull * (1.0 - 0.72 * habituation)
            selected = bool(
                admitted and not hard_blocked and selected_pull >= boundary)
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

        # The selected vector is ephemeral motor material.  It is returned to
        # the actuator seam, but _record() never receives or persists it.
        span = max(1e-6, 1.0 - boundary)
        strength = _unit((selected_pull - boundary) / span)
        vector = ({
            "head_yaw_deg": round(target[0] * 6.0 * strength, 4),
            "head_pitch_deg": round(target[1] * 3.5 * strength, 4),
            "torso_yaw_deg": round(target[0] * 7.0 * strength, 4),
            "torso_pitch_deg": round(target[1] * 2.5 * strength, 4),
            "weight_shift": round(target[0] * 0.24 * strength, 4),
            "strength": round(strength, 6),
        } if selected else {})
        receipt = {
            "schema_version": self.SCHEMA_VERSION,
            "event_id": event_id,
            "stage": outcome,
            "internally_admitted": admitted,
            "selected": selected,
            "surface_published": False,
            "evidence": round(evidence, 6),
            "selected_pull": round(selected_pull, 6),
            "boundary": round(boundary, 6),
            "readiness": round(readiness, 6),
            "habituation": round(habituation, 6),
            "occupied": occupied,
            "active_private_work": bool(active_private_work),
            "hard_blocked": bool(hard_blocked),
            "quiet_valid": True,
            "action_chain": False,
        }
        self._record(receipt)
        return {**receipt, "vector": vector}

    def record_publication(self, event_id: str, published: bool) -> dict:
        """Bind a transient room-surface publication to an exact selection."""
        event_id = str(event_id or "")
        with self._lock:
            selected = event_id in self._selected
            published = bool(selected and published)
            self._selected.discard(event_id)
            if published:
                self._surface_active = True
                self._counts["surface_published"] += 1
                stage = "selected_surface_published"
            else:
                self._counts["selected_unpublished"] += int(selected)
                stage = "selected_unpublished" if selected else "not_selected"
        receipt = {
            "schema_version": self.SCHEMA_VERSION,
            "event_id": event_id,
            "stage": stage,
            "selected": selected,
            "surface_published": published,
            "render_claimed": False,
            "quiet_valid": True,
            "action_chain": False,
        }
        self._record(receipt)
        return receipt

    def release(self) -> dict:
        """Relinquish the transient surface claim; choose no replacement."""
        with self._lock:
            was_active = self._surface_active
            self._surface_active = False
            if was_active:
                self._counts["released"] += 1
        receipt = {
            "schema_version": self.SCHEMA_VERSION,
            "event_id": uuid.uuid4().hex,
            "stage": "released" if was_active else "already_quiet",
            "selected": False,
            "surface_published": False,
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
                "mode": "causal_optional_transient_pose",
                "event_clock": "motion_threshold_crossing",
                "surface_active": self._surface_active,
                "last_outcome": self._last_outcome,
                "habituation": round(self._habituation, 6),
                "lifecycle_counts": dict(self._counts),
                "quiet_valid": True,
                "action_chain": False,
                "creates_language": False,
                "creates_memory": False,
                "chooses_named_gesture": False,
                "changes_posture": False,
                "stores_target_coordinates": False,
                "stores_pose_vector": False,
                "receipt_content": "content_free_control_metadata_only",
            }

    def _record(self, receipt: dict):
        if not self.receipt_path:
            return
        record = {"at": time.time(), **receipt}
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        directory = os.path.dirname(self.receipt_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self._receipt_lock:
            with open(self.receipt_path, "a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
