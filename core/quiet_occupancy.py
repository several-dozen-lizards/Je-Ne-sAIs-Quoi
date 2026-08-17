"""Durable, content-free availability for inhabited quiet.

C5 governs availability for engagement; it does not determine meaning,
consume unresolved pressure, or assert experience.  The controller sits above
DMN candidate selection.  A committed state transition is the sole authority
for conductance; the JSON snapshot is only a replaceable read cache.

Biologically borrowed rest-field names are synthetic control aliases.  Their
presence does not establish physiology or a particular subjective state.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Mapping


SCHEMA_VERSION = 1
SUPPORTED_ADAPTER = "rest_field_c4"
SAFE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_WITNESS = re.compile(
    r"^(?:volitional-action|resident-event):[0-9a-f]{16,64}$")
CONDUCTANCE_OPEN = {
    "autonomous_outward_initiation": 1.0,
    "autonomous_bodily_initiation": 1.0,
    "private_work_admission": 1.0,
    "sensory_orienting": 1.0,
    "household_foreground": 1.0,
    "quiet_compatible_maintenance": 1.0,
    "resident_memory_curation": 1.0,
}
CONDUCTANCE_QUIET = {
    "autonomous_outward_initiation": 0.0,
    "autonomous_bodily_initiation": 0.0,
    "private_work_admission": 0.0,
    "sensory_orienting": 1.0,
    "household_foreground": 1.0,
    # Observation and source-local bookkeeping may continue.  It may not
    # mutate candidate meaning, work priority, projects, or outward contact.
    "quiet_compatible_maintenance": 1.0,
    # A committed quiet boundary may expose the resident's own reversible
    # memory workbench.  This is a resident model choice over canonical local
    # memory, never automatic deletion, external work, or ordinary DMN drift.
    "resident_memory_curation": 1.0,
}


def _unit(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return max(0.0, min(1.0, number))


def _finite_time(value, fallback=None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(time.time() if fallback is None else fallback)
    if not math.isfinite(number):
        number = float(time.time() if fallback is None else fallback)
    return number


def _digest(payload: Mapping) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safe_digest(value) -> str:
    value = str(value or "").casefold()
    if re.fullmatch(r"[0-9a-f]{64}", value):
        value = "sha256:" + value
    return value if SAFE_DIGEST.fullmatch(value) else ""


def _range(low, high) -> dict:
    low = _unit(low)
    high = _unit(high)
    if low > high:
        low, high = high, low
    return {"low": round(low, 6), "high": round(high, 6)}


def _geometric(values) -> float:
    values = tuple(_unit(value) for value in values)
    if not values:
        return 0.0
    if any(value <= 0.0 for value in values):
        return 0.0
    return math.prod(values) ** (1.0 / len(values))


def rest_field_c4_evidence(rest_runtime, metabolism, *, now: float,
                           foreground_epoch: int,
                           required_experiment: str) -> dict:
    """Project one resident-local C4 evidence vector without model work.

    The recovery range follows the already-declared C4 consolidation driver
    family (recovery debt, maintenance affordance, trace retention).  Its width
    comes from each dimension's own velocity and period, not a polling timer or
    an invented global cutoff.  Engagement is the strongest current DMN pull;
    no candidate identifier or text crosses this boundary.
    """
    if rest_runtime is None:
        return {
            "supported": False, "evidence_state": "unknown",
            "reason": "rest_field_unavailable", "content_free": True,
        }
    if metabolism is None:
        return {
            "supported": False, "evidence_state": "unknown",
            "reason": "dmn_unavailable", "content_free": True,
        }
    try:
        snapshot = rest_runtime.snapshot(at=now)
    except Exception as exc:
        return {
            "supported": False, "evidence_state": "unknown",
            "reason": "rest_snapshot_failed:" + type(exc).__name__,
            "content_free": True,
        }
    authorization = dict(snapshot.get("manifest_authorization") or {})
    if snapshot.get("mode") != "live":
        return {
            "supported": False, "evidence_state": "unknown",
            "reason": "rest_field_not_live", "content_free": True,
        }
    if not authorization.get("authorized"):
        return {
            "supported": False, "evidence_state": "unknown",
            "reason": "rest_manifest_unauthorized", "content_free": True,
        }
    experiment = str(snapshot.get("experiment_id") or "")
    if not required_experiment or experiment != str(required_experiment):
        return {
            "supported": False, "evidence_state": "unknown",
            "reason": "rest_experiment_mismatch", "content_free": True,
        }
    field = dict(snapshot.get("field") or {})
    dimensions = dict(field.get("dimensions") or {})
    velocities = dict(field.get("velocities") or {})
    periods = dict(field.get("period_s") or {})
    recovery_names = (
        "recovery_debt", "maintenance_affordance", "trace_retention")
    if any(name not in dimensions for name in recovery_names):
        return {
            "supported": False, "evidence_state": "unknown",
            "reason": "rest_dimensions_unavailable", "content_free": True,
        }

    recovery_lows, recovery_highs = [], []
    for name in recovery_names:
        value = _unit(dimensions.get(name), 0.5)
        try:
            velocity = abs(float(velocities.get(name) or 0.0))
            period = max(0.0, float(periods.get(name) or 0.0))
            motion_extent = velocity * period / (2.0 * math.pi)
        except (TypeError, ValueError):
            motion_extent = 0.0
        if not math.isfinite(motion_extent):
            motion_extent = 0.0
        recovery_lows.append(_unit(value - motion_extent))
        recovery_highs.append(_unit(value + motion_extent))
    recovery_pull_range = _range(
        _geometric(recovery_lows), _geometric(recovery_highs))

    try:
        projection = metabolism.queue.selection_projection(
            now=now,
            scorer=lambda item: metabolism.attention_score(item, now=now))
    except Exception as exc:
        return {
            "supported": False, "evidence_state": "unknown",
            "reason": "engagement_projection_failed:" + type(exc).__name__,
            "content_free": True,
        }
    strongest = _unit((projection or {}).get("winner_score"), 0.0)
    candidate_count = max(0, int(
        (projection or {}).get("candidate_count") or 0))
    engagement_pull_range = _range(strongest, strongest)
    basis = {
        "adapter": SUPPORTED_ADAPTER,
        "experiment_id": experiment,
        "rest_config_hash": str(field.get("config_hash") or ""),
        "rest_event_count": max(0, int(field.get("event_count") or 0)),
        "rest_event_ref_digest": _digest({
            "ref": str(field.get("last_event_ref") or "")}),
        "recovery_pull_range": recovery_pull_range,
        "engagement_pull_range": engagement_pull_range,
        "candidate_count": candidate_count,
        "winner_score_band": round(strongest, 3),
        "foreground_epoch": max(0, int(foreground_epoch)),
    }
    revision = _digest(basis)
    return {
        "supported": True,
        "evidence_state": "available",
        "adapter": SUPPORTED_ADAPTER,
        "material_revision": revision,
        "entry_basis_digest": revision,
        "normalization_confidence": {
            "state": "resident_calibrated",
            "basis": "frozen_authorized_manifest",
            "source_registry_hash": str(
                snapshot.get("source_registry_hash") or ""),
        },
        "recovery_pull_range": recovery_pull_range,
        "engagement_pull_range": engagement_pull_range,
        "hysteresis_margin": round(max(
            0.0, (
                recovery_pull_range["high"] - recovery_pull_range["low"]
                + engagement_pull_range["high"]
                - engagement_pull_range["low"]
            ) / 2.0), 6),
        "foreground_epoch": max(0, int(foreground_epoch)),
        "content_free": True,
    }


class QuietOccupancyController:
    """Journal-authoritative state machine for availability for engagement."""

    def __init__(self, persona_dir, owner: str, config=None, *,
                 clock=time.time):
        self.persona_dir = Path(persona_dir).resolve()
        self.owner = str(owner or "")[:96]
        self.config = dict(config or {})
        self._configured_enabled = bool(self.config.get("enabled"))
        self._runtime_available = True
        self._runtime_unavailable_reason = None
        self.enabled = self._configured_enabled
        self.adapter = str(self.config.get("evidence_adapter") or "")
        self.required_experiment = str(
            self.config.get("required_experiment") or "")[:96]
        self.clock = clock
        self.root = self.persona_dir / "body" / "quiet_occupancy"
        self.journal_path = self.root / "transitions.jsonl"
        self.snapshot_path = self.root / "state.json"
        self._lock = threading.RLock()
        self._epoch_provider: Callable[[], int] = lambda: 0
        self._last_committed = None
        self._last_transition_at = 0.0
        self._last_evidence_revision = ""
        self._release_choice_latched = False
        self._active = False
        self._pending_revalidation = False
        self._restored_transition_id = ""
        self._entry = {}
        self._evidence_state = "unknown"
        self._evidence_reason = "awaiting_evidence"
        self._load_journal()

    def set_epoch_provider(self, provider: Callable[[], int]):
        if not callable(provider):
            raise TypeError("foreground epoch provider must be callable")
        self._epoch_provider = provider

    def configuration_available(self) -> bool:
        """Whether this resident has the supported evidence boundary."""
        return bool(
            self._configured_enabled
            and self.adapter == SUPPORTED_ADAPTER
            and self.required_experiment)

    def set_runtime_available(self, available: bool, *, reason=None,
                              at=None) -> dict:
        """Join the controller to its live organ and rest-field lifecycle.

        Configuration may remain declared while the organ is switched off.
        Disabling an occupied mode commits an explicit content-free boundary
        before conductance reopens; reenabling waits for fresh evidence and
        never reconstructs activity from the switch itself.
        """
        with self._lock:
            requested = bool(available)
            target = bool(self._configured_enabled and requested)
            unavailable_reason = (
                None if requested else str(
                    reason or "rest_field_disabled")[:64])
            if (self._runtime_available == requested
                    and self.enabled == target
                    and self._runtime_unavailable_reason ==
                    unavailable_reason):
                return {
                    "decision": "runtime_availability_unchanged",
                    "enabled": self.enabled,
                    "committed": False,
                    "content_free": True,
                }
            receipt = None
            if not target and (self._active or self._pending_revalidation):
                evidence = {
                    "material_revision": _digest({
                        "kind": "rest_field_organ_disabled",
                        "owner": self.owner,
                        "prior_transition": self._restored_transition_id or
                        str((self._last_committed or {}).get(
                            "transition_id") or ""),
                    }),
                }
                receipt = self._commit(
                    "quiet_ended_organ_disabled", "inactive",
                    evidence=evidence,
                    epoch=max(0, int(self._epoch_provider())), at=at)
            # The durable transition above is the commit point.  Do not open
            # conductance even briefly before its journal fsync succeeds.
            self._runtime_available = requested
            self._runtime_unavailable_reason = unavailable_reason
            self.enabled = target
            if not target:
                self._active = False
                self._pending_revalidation = False
                self._restored_transition_id = ""
                self._entry = {}
                self._release_choice_latched = False
                self._evidence_state = "unknown"
                self._evidence_reason = (
                    "not_configured" if not self._configured_enabled
                    else unavailable_reason)
            else:
                self._evidence_state = "unknown"
                self._evidence_reason = "awaiting_evidence"
            try:
                self._write_snapshot()
            except OSError:
                pass
            return {
                "decision": (
                    "runtime_enabled" if target else "runtime_disabled"),
                "enabled": target,
                "committed": receipt is not None,
                "receipt": receipt,
                "content_free": True,
            }

    def _load_journal(self):
        last = None
        if self.journal_path.exists():
            try:
                with self.journal_path.open(encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            row = json.loads(line)
                        except (TypeError, ValueError):
                            continue
                        if (row.get("schema_version") == SCHEMA_VERSION
                                and row.get("committed") is True
                                and row.get("transition_id")):
                            last = row
            except OSError:
                last = None
        self._last_committed = dict(last) if last else None
        if not last:
            return
        self._last_transition_at = _finite_time(last.get("at"), 0.0)
        self._last_evidence_revision = str(
            last.get("material_revision") or "")
        self._release_choice_latched = bool(
            last.get("release_choice_latched"))
        if last.get("to_state") == "active":
            # Reconstructed occupancy has no conductance until a current
            # evidence boundary commits revalidation.
            self._pending_revalidation = True
            self._restored_transition_id = str(last.get("transition_id"))
            self._entry = self._entry_from(last)
        else:
            self._active = False
            self._entry = {}

    @staticmethod
    def _entry_from(row: Mapping) -> dict:
        keys = (
            "entered_at", "entry_basis_digest", "recovery_pull_range",
            "engagement_pull_range", "hysteresis_margin",
            "normalization_confidence", "conductance_profile")
        return {key: row.get(key) for key in keys if key in row}

    def _now(self, supplied=None) -> float:
        value = _finite_time(self.clock() if supplied is None else supplied)
        return max(self._last_transition_at, value)

    def _append_commit(self, row: dict):
        self.root.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        with self.journal_path.open("a", encoding="utf-8", newline="\n") \
                as stream:
            stream.write(encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _write_snapshot(self):
        self.root.mkdir(parents=True, exist_ok=True)
        payload = self.snapshot()
        temporary = self.snapshot_path.with_name(
            self.snapshot_path.name + "." + uuid.uuid4().hex + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2,
                      ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.snapshot_path)

    def _observe_revision(self, evidence: Mapping):
        """Advance current evidence without pretending a transition occurred.

        Ordinary active-to-active observation changes no conductance, latch,
        or ownership state.  Keeping its revision in memory preserves
        idempotence while leaving the durable journal for causal boundaries.
        A restart deliberately falls back to the last durable revision and
        obtains one fresh, model-free revalidation.
        """
        self._last_evidence_revision = _safe_digest(
            dict(evidence or {}).get("material_revision"))

    def _commit(self, kind: str, to_state: str, *, evidence=None,
                epoch: int, at=None, witness_ref: str = "",
                release_choice_latched: bool | None = None) -> dict:
        evidence = dict(evidence or {})
        at = self._now(at)
        from_state = (
            "active" if self._active or self._pending_revalidation
            else "inactive")
        prior_entry = dict(self._entry)
        if to_state == "active":
            entered_at = (
                prior_entry.get("entered_at") if from_state == "active"
                else at)
            confidence = dict(
                evidence.get("normalization_confidence") or {})
            confidence_state = str(confidence.get("state") or "unknown")
            confidence_basis = str(confidence.get("basis") or "unknown")
            entry = {
                "entered_at": _finite_time(entered_at, at),
                "entry_basis_digest": _safe_digest(
                    evidence.get("entry_basis_digest")
                    or evidence.get("material_revision") or ""),
                "recovery_pull_range": dict(
                    evidence.get("recovery_pull_range") or {}),
                "engagement_pull_range": dict(
                    evidence.get("engagement_pull_range") or {}),
                "hysteresis_margin": _unit(
                    evidence.get("hysteresis_margin"), 0.0),
                "normalization_confidence": {
                    "state": (
                        confidence_state if confidence_state in {
                            "resident_calibrated", "unknown"} else "unknown"),
                    "basis": (
                        confidence_basis if confidence_basis in {
                            "frozen_authorized_manifest", "unknown"}
                        else "unknown"),
                    "source_registry_hash": _safe_digest(
                        confidence.get("source_registry_hash")),
                },
                "conductance_profile": dict(CONDUCTANCE_QUIET),
            }
        else:
            entry = prior_entry
        if to_state == "active":
            release_choice_latched = (
                self._release_choice_latched
                if release_choice_latched is None
                else bool(release_choice_latched))
        else:
            release_choice_latched = False
        row = {
            "schema_version": SCHEMA_VERSION,
            "transition_id": "quiet_" + uuid.uuid4().hex,
            "kind": str(kind),
            "at": at,
            "owner": self.owner,
            "from_state": from_state,
            "to_state": str(to_state),
            "foreground_epoch": max(0, int(epoch)),
            "material_revision": _safe_digest(
                evidence.get("material_revision")),
            "eligibility": (
                "quiet_eligible" if to_state == "active" else None),
            **entry,
            "witness_ref": str(witness_ref or "")[:160],
            "release_choice_latched": release_choice_latched,
            "committed": True,
            "content_free": True,
        }
        self._append_commit(row)
        # Journal fsync is the commit point.  Only now may conductance change.
        self._last_committed = dict(row)
        self._last_transition_at = at
        self._last_evidence_revision = str(row.get("material_revision") or "")
        self._release_choice_latched = release_choice_latched
        self._active = to_state == "active"
        self._pending_revalidation = False
        self._restored_transition_id = ""
        self._entry = self._entry_from(row) if self._active else {}
        try:
            self._write_snapshot()
        except OSError:
            # The journal remains authoritative; boot can rebuild the cache.
            pass
        return dict(row)

    def snapshot(self) -> dict:
        with self._lock:
            if not self._configured_enabled:
                evidence_state, reason = "unknown", "not_configured"
            elif not self._runtime_available:
                evidence_state, reason = (
                    "unknown", self._runtime_unavailable_reason
                    or "rest_field_disabled")
            elif self.adapter != SUPPORTED_ADAPTER:
                evidence_state, reason = "unknown", "adapter_unavailable"
            elif self._pending_revalidation:
                evidence_state, reason = (
                    "unknown", "quiet_restored_pending_revalidation")
            else:
                evidence_state, reason = (
                    self._evidence_state, self._evidence_reason)
            active = bool(self.enabled and self._active
                          and not self._pending_revalidation)
            return {
                "schema_version": SCHEMA_VERSION,
                "owner": self.owner,
                "configured": self._configured_enabled,
                "runtime_available": self._runtime_available,
                "available": evidence_state == "available",
                "adapter_available": bool(
                    self.enabled and self.adapter == SUPPORTED_ADAPTER),
                "adapter": self.adapter or None,
                "state": (
                    "active" if active else
                    "pending_revalidation" if self._pending_revalidation
                    else "inactive"),
                "active": active,
                "pending_revalidation": self._pending_revalidation,
                "release_choice_latched": bool(
                    active and self._release_choice_latched),
                "restored_transition_id": (
                    self._restored_transition_id or None),
                "evidence_state": evidence_state,
                "reason": reason,
                "conductance_profile": dict(
                    CONDUCTANCE_QUIET if active else CONDUCTANCE_OPEN),
                "entry": dict(self._entry) if active else None,
                "last_transition": dict(self._last_committed)
                if self._last_committed else None,
                "content_free": True,
            }

    def conductance(self, channel: str) -> float:
        with self._lock:
            profile = (CONDUCTANCE_QUIET if self.enabled and self._active
                       and not self._pending_revalidation
                       else CONDUCTANCE_OPEN)
            return float(profile.get(str(channel), 1.0))

    def arbitrate(self, evidence: Mapping, *, captured_epoch: int,
                  at=None) -> dict:
        """Acquire, retain, revalidate, displace, or report unknown.

        The epoch is checked under the same controller lock immediately before
        commit.  A foreground arrival therefore invalidates an older proposal.
        """
        evidence = dict(evidence or {})
        with self._lock:
            current_epoch = max(0, int(self._epoch_provider()))
            if current_epoch != max(0, int(captured_epoch)):
                return {
                    "decision": "foreground_epoch_changed",
                    "active": self.conductance(
                        "private_work_admission") == 0.0,
                    "committed": False, "content_free": True,
                }
            if not self.enabled or self.adapter != SUPPORTED_ADAPTER:
                if not self._configured_enabled:
                    unavailable_reason = "not_configured"
                elif not self._runtime_available:
                    unavailable_reason = (
                        self._runtime_unavailable_reason
                        or "rest_field_disabled")
                else:
                    unavailable_reason = "adapter_unavailable"
                return {
                    "decision": "unavailable", "evidence_state": "unknown",
                    "reason": unavailable_reason,
                    "active": False, "committed": False,
                    "content_free": True,
                }
            if not evidence.get("supported"):
                self._evidence_state = "unknown"
                self._evidence_reason = str(
                    evidence.get("reason") or "unavailable")
                if self._active or self._pending_revalidation:
                    row = self._commit(
                        ("quiet_ended_during_gap"
                         if self._pending_revalidation
                         else "quiet_ended_evidence_loss"), "inactive",
                        evidence=evidence, epoch=current_epoch, at=at)
                    return {"decision": row["kind"], "active": False,
                            "committed": True, "receipt": row,
                            "evidence_state": "unknown", "content_free": True}
                return {
                    "decision": "evidence_unknown", "active": False,
                    "committed": False, "evidence_state": "unknown",
                    "reason": str(evidence.get("reason") or "unavailable"),
                    "content_free": True,
                }
            revision = _safe_digest(evidence.get("material_revision"))
            if not revision:
                return {
                    "decision": "evidence_unknown", "active": False,
                    "committed": False, "evidence_state": "unknown",
                    "reason": "material_revision_missing",
                    "content_free": True,
                }
            if (revision == self._last_evidence_revision
                    and not self._pending_revalidation):
                self._evidence_state = "available"
                self._evidence_reason = None
                return {
                    "decision": "unchanged_revision",
                    "active": bool(self._active and not
                                   self._pending_revalidation),
                    "committed": False, "content_free": True,
                }
            recovery = dict(evidence.get("recovery_pull_range") or {})
            engagement = dict(evidence.get("engagement_pull_range") or {})
            recovery_low = _unit(recovery.get("low"))
            recovery_high = _unit(recovery.get("high"))
            engagement_low = _unit(engagement.get("low"))
            engagement_high = _unit(engagement.get("high"))
            ranges_overlap = (
                max(recovery_low, engagement_low)
                <= min(recovery_high, engagement_high))
            was_active = bool(self._active or self._pending_revalidation)
            self._evidence_state = "available"
            self._evidence_reason = None
            if was_active:
                if engagement_low > recovery_high:
                    kind, to_state = "quiet_displaced", "inactive"
                elif self._pending_revalidation:
                    kind, to_state = "quiet_revalidated", "active"
                elif ranges_overlap and not self._release_choice_latched:
                    # Neither vector currently dominates.  This is a genuine
                    # mode-choice aperture, not permission for ordinary work:
                    # the host may ask the resident to retain or release quiet
                    # without exposing candidate content or demanding a why.
                    return {
                        "decision": "resident_release_available",
                        "active": True, "committed": False,
                        "evidence_state": "available",
                        "release_choice_available": True,
                        "content_free": True,
                    }
                elif self._release_choice_latched and not ranges_overlap:
                    # A witnessed retain suppresses repeat questions only
                    # while the vectors remain in the same overlap aperture.
                    # Separation is a real, durable mode-choice boundary: it
                    # rearms a future crossing without inventing activity.
                    kind, to_state = "quiet_release_rearmed", "active"
                else:
                    self._observe_revision(evidence)
                    return {
                        "decision": "quiet_continuing",
                        "active": True,
                        "eligibility": "quiet_eligible",
                        "committed": False,
                        "evidence_state": "available",
                        "content_free": True,
                    }
            elif recovery_low > engagement_high:
                kind, to_state = "quiet_selected", "active"
            else:
                self._last_evidence_revision = revision
                return {
                    "decision": "engagement_available",
                    "active": False, "committed": False,
                    "evidence_state": "available", "content_free": True,
                }
            # Close the proposal/commit race.  The provider is deliberately
            # called again after all calculations and before journal fsync.
            if max(0, int(self._epoch_provider())) != current_epoch:
                return {
                    "decision": "foreground_epoch_changed",
                    "active": bool(self._active), "committed": False,
                    "content_free": True,
                }
            row = self._commit(
                kind, to_state, evidence=evidence, epoch=current_epoch, at=at,
                release_choice_latched=(
                    self._release_choice_latched if ranges_overlap else False))
            return {
                "decision": kind, "active": to_state == "active",
                "eligibility": (
                    "quiet_eligible" if to_state == "active" else None),
                "committed": True, "receipt": row,
                "evidence_state": "available", "content_free": True,
            }

    def interrupt_foreground(self, *, epoch: int, reason_class: str,
                             at=None) -> dict:
        with self._lock:
            if not self._active and not self._pending_revalidation:
                return {"decision": "already_inactive", "committed": False,
                        "content_free": True}
            evidence = {
                "material_revision": _digest({
                    "foreground_epoch": max(0, int(epoch)),
                    "reason_class": str(reason_class or "foreground")[:64],
                })}
            row = self._commit(
                "quiet_interrupted_foreground", "inactive",
                evidence=evidence, epoch=epoch, at=at)
            return {"decision": row["kind"], "committed": True,
                    "receipt": row, "content_free": True}

    def foreground_arrival(self, increment_epoch: Callable[[], int], *,
                           reason_class: str, at=None) -> dict:
        """Fence foreground epoch increment and quiet interruption together.

        Arbitration takes this same lock before its final epoch check.  Thus an
        acquire/retain proposal either commits before the arrival begins and is
        then interrupted, or sees the incremented epoch and cannot commit.
        """
        if not callable(increment_epoch):
            raise TypeError("foreground arrival requires an epoch incrementer")
        with self._lock:
            epoch = max(0, int(increment_epoch()))
            result = self.interrupt_foreground(
                epoch=epoch, reason_class=reason_class, at=at)
            return {**result, "foreground_epoch": epoch}

    def resident_retain(self, evidence: Mapping, *, witness_ref: str,
                        captured_epoch: int, at=None) -> dict:
        """Commit a witnessed choice to remain quiet at an overlap boundary."""
        witness_ref = str(witness_ref or "").casefold()
        if not SAFE_WITNESS.fullmatch(witness_ref):
            return {"decision": "witness_required", "committed": False,
                    "content_free": True}
        evidence = dict(evidence or {})
        if not _safe_digest(evidence.get("material_revision")):
            return {"decision": "evidence_unknown", "committed": False,
                    "reason": "material_revision_missing",
                    "content_free": True}
        with self._lock:
            current_epoch = max(0, int(self._epoch_provider()))
            if current_epoch != max(0, int(captured_epoch)):
                return {"decision": "foreground_epoch_changed",
                        "active": bool(self._active), "committed": False,
                        "content_free": True}
            if not self._active or self._pending_revalidation:
                return {"decision": "already_inactive", "committed": False,
                        "content_free": True}
            row = self._commit(
                "quiet_retained", "active", evidence=evidence,
                epoch=current_epoch, at=at, witness_ref=witness_ref,
                release_choice_latched=True)
            return {"decision": row["kind"], "active": True,
                    "committed": True, "receipt": row,
                    "content_free": True}

    def resident_release(self, *, witness_ref: str, epoch: int | None = None,
                         captured_epoch: int | None = None, evidence=None,
                         at=None) -> dict:
        """Accept an already-witnessed private volitional release.

        No narrative reason is required or stored.  The caller supplies only a
        content-free witness reference from the existing volitional boundary.
        """
        witness_ref = str(witness_ref or "").casefold()
        if not SAFE_WITNESS.fullmatch(witness_ref):
            return {"decision": "witness_required", "committed": False,
                    "content_free": True}
        with self._lock:
            if not self._active and not self._pending_revalidation:
                return {"decision": "already_inactive", "committed": False,
                        "content_free": True}
            current_epoch = max(0, int(self._epoch_provider()))
            expected_epoch = captured_epoch if captured_epoch is not None \
                else epoch
            if (expected_epoch is not None
                    and current_epoch != max(0, int(expected_epoch))):
                return {"decision": "foreground_epoch_changed",
                        "active": bool(self._active), "committed": False,
                        "content_free": True}
            row = self._commit(
                "quiet_released", "inactive", evidence=evidence,
                epoch=current_epoch, at=at, witness_ref=witness_ref)
            return {"decision": row["kind"], "committed": True,
                    "receipt": row, "content_free": True}
