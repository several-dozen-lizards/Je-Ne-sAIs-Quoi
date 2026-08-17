"""R1 consumer for the existing quiet-compatible maintenance socket."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
from typing import Any, Mapping

from core.memory_emotion.vector_maintenance import VectorRepairOperator
from core.rest_field.assimilation import (
    OPERATOR_ID, project_quiet_assimilation)
from shell.agency_controller import AgencyRunOutcome


def _digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


class QuietAssimilationRuntime:
    """Observe reachability and optionally submit the one frozen R1 operator."""

    def __init__(self, engine, controller, leases, config=None, *,
                 clock=time.time, embedder=None):
        self.engine = engine
        self.controller = controller
        self.leases = leases
        self.config = dict(config or {})
        self.clock = clock
        self.enabled = bool(self.config.get("enabled"))
        self.mode = str(self.config.get("mode") or "disabled")
        self.arm = str(self.config.get("arm") or "actual")
        self.execute_authorized = (
            self.config.get("execute_authorized") is True)
        self.experiment_id = str(
            self.config.get("experiment_id") or "")[:96]
        self.operator_id = str(
            self.config.get("operator") or OPERATOR_ID)
        if self.mode not in {"disabled", "observe", "live"}:
            raise ValueError("unknown quiet assimilation mode")
        if self.arm not in {"actual", "bypass", "sham"}:
            raise ValueError("unknown quiet assimilation arm")
        if self.enabled and self.operator_id != OPERATOR_ID:
            raise ValueError("quiet assimilation operator is not frozen")
        if self.enabled and not self.experiment_id:
            raise ValueError("quiet assimilation requires an experiment id")
        if self.enabled and self.mode == "live" and not self.execute_authorized:
            raise ValueError(
                "live quiet assimilation requires explicit execute_authorized")
        self.operator = VectorRepairOperator(
            engine.organ, embedder=embedder) if self.enabled else None
        self.path = os.path.join(
            engine.pdir, "history", "rest_quiet_assimilation.jsonl")
        self._lock = threading.RLock()
        self._seen = set()
        self._submitted = set()
        self._last_projection = None
        self._last_outcome = None

    def _append(self, row: Mapping[str, Any]) -> None:
        row = dict(row)
        if row.get("content_free") is not True:
            raise ValueError("assimilation receipt must be content-free")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        line = json.dumps(
            row, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False) + "\n"
        with self._lock:
            with open(self.path, "a", encoding="ascii", newline="\n") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())

    def _quiet_status(self, captured_epoch: int) -> dict[str, Any]:
        quiet = getattr(self.engine, "quiet_occupancy", None)
        snapshot = dict(quiet.snapshot() or {}) if quiet is not None else {}
        transition = dict(snapshot.get("last_transition") or {})
        transition_id = str(transition.get("transition_id") or "")
        return {
            "active": snapshot.get("active") is True,
            "committed": bool(
                transition.get("committed") is True
                and transition.get("to_state") == "active"),
            "quiet_compatible_maintenance": (
                quiet.conductance("quiet_compatible_maintenance")
                if quiet is not None else None),
            # The committed transition carries its own epoch.  The pure
            # projector compares that owner receipt with the current captured
            # epoch; copying the current value here would make the comparison
            # tautological.
            "foreground_epoch": transition.get("foreground_epoch"),
            "transition_digest": (
                "sha256:" + hashlib.sha256(
                    transition_id.encode("utf-8")).hexdigest()
                if transition_id else None),
        }

    def _ingress_status(self, now: float) -> dict[str, Any]:
        sensory = getattr(self.engine, "perception", None)
        sensory_status = (
            dict(sensory.resource_status(now=now) or {})
            if callable(getattr(sensory, "resource_status", None)) else {})
        mailbox = getattr(self.engine, "resident_event_mailbox", None)
        mailbox_status = (
            dict(mailbox.status() or {})
            if callable(getattr(mailbox, "status", None)) else {})
        depth, capacity = (
            mailbox_status.get("depth"), mailbox_status.get("capacity"))
        load = (max(0.0, min(1.0, float(depth) / float(capacity)))
                if isinstance(depth, (int, float))
                and isinstance(capacity, (int, float))
                and float(capacity) > 0.0 else None)
        controller = dict(self.controller.status() or {}) \
            if self.controller is not None else {}
        return {
            "low_ingress": sensory_status.get("low_ingress"),
            "low_interruption_risk": (
                (1.0 - load) * float(
                    not bool(controller.get("replacement_pending")))
                if load is not None else None),
        }

    def _rest_status(self, now: float) -> dict[str, Any]:
        runtime = getattr(self.engine, "rest_runtime", None)
        if runtime is None:
            return {"authorized": False}
        field = dict(runtime.field.peek(now) or {})
        drivers = dict(runtime.junction_drivers.get(
            "maintenance_candidate_salience") or {})
        authorization = dict(runtime.manifest_authorization or {})
        effective = runtime.junctions.effective_mode(
            "maintenance_candidate_salience")
        return {
            "authorized": bool(
                runtime.mode == "live" and authorization.get("authorized")
                and effective == "conduct" and drivers),
            "dimensions": dict(field.get("dimensions") or {}),
            "drivers": drivers,
            "max_abs_logit_shift": runtime.conduct_limits.get(
                "maintenance_candidate_salience"),
            "config_hash": field.get("config_hash"),
        }

    def project(self, *, captured_epoch: int, now: float | None = None,
                owned_run_id: str = "") -> dict[str, Any]:
        now = float(self.clock() if now is None else now)
        if not self.enabled or self.operator is None:
            return {
                "schema_version": 1, "stage": "R1",
                "kind": "quiet_assimilation_reachability",
                "available": False, "reason": "consumer_disabled",
                "mode": "observe_only", "content_free": True,
                "read_only": True, "state_writes": 0,
                "model_calls": 0, "actions_created": 0,
                "downstream_channels_touched": [],
            }
        memory = dict(self.engine.organ.resource_status() or {})
        memory.update(self.operator.status())
        controller = dict(self.controller.status() or {}) \
            if self.controller is not None else {}
        active = dict(controller.get("active") or {})
        if owned_run_id and active.get("run_id") == owned_run_id:
            controller["active"] = None
        state_available = bool(
            self.leases is not None and (
                self.leases.state.owned_by_current_thread()
                or not self.leases.state.locked()))
        return project_quiet_assimilation(
            persona=str(self.engine.persona),
            memory_status=memory,
            quiet_status=self._quiet_status(captured_epoch),
            controller_status=controller,
            lease_status={"state_available_to_consumer": state_available},
            ingress_status=self._ingress_status(now),
            rest_status=self._rest_status(now),
            foreground_epoch=int(captured_epoch))

    async def _run(self, context, plan, projection_revision: str,
                   captured_epoch: int):
        computed = await asyncio.to_thread(self.operator.compute, plan)

        def deferred(status: str) -> dict[str, Any]:
            return {
                "schema_version": 1,
                "kind": "quiet_assimilation_operator",
                "operator_id": OPERATOR_ID,
                "experiment_id": self.experiment_id,
                "arm": self.arm,
                "execute_authorized": self.execute_authorized,
                "status": status,
                "committed": False,
                "projection_revision": projection_revision,
                "local_model_calls": int(
                    computed.get("local_model_calls") or 0),
                "canonical_memory_writes": 0,
                "authoritative_sidecar_writes": 0,
                "content_free": True,
            }

        epoch_provider = getattr(
            self.engine, "_foreground_demand_epoch_provider", lambda: 0)
        if (int(epoch_provider()) != int(captured_epoch)
                or context.live_epoch() != context.captured_epoch):
            outcome = deferred("deferred_foreground_epoch_changed")
            self._append({**outcome, "at": self.clock()})
            self._last_outcome = outcome
            return AgencyRunOutcome(status="deferred", result=outcome)
        if not self.leases.state.acquire(blocking=False):
            outcome = deferred("deferred_state_lease_occupied")
            self._append({**outcome, "at": self.clock()})
            self._last_outcome = outcome
            return AgencyRunOutcome(status="deferred", result=outcome)
        try:
            if int(epoch_provider()) != int(captured_epoch):
                outcome = deferred("deferred_foreground_epoch_changed")
            else:
                fresh = self.project(
                    captured_epoch=captured_epoch, now=self.clock(),
                    owned_run_id=context.run_id)
                candidates = list(fresh.get("candidates") or ())
                if not candidates or not candidates[0].get("reachable"):
                    outcome = deferred("deferred_reachability_changed")
                else:
                    transaction_id = (
                        "r1_" + _digest({
                            "experiment": self.experiment_id,
                            "run": context.run_id,
                            "plan": plan.get("plan_revision"),
                        })[:40])
                    outcome = self.operator.commit(
                        plan, computed, transaction_id=transaction_id)
                    outcome["kind"] = "quiet_assimilation_operator"
                    outcome["experiment_id"] = self.experiment_id
                    outcome["execute_authorized"] = self.execute_authorized
                    outcome["projection_revision"] = projection_revision
        finally:
            self.leases.state.release()
        self._append({**outcome, "at": self.clock()})
        with self._lock:
            self._last_outcome = dict(outcome)
        return AgencyRunOutcome(
            status=("completed" if outcome.get("committed")
                    or self.arm in {"bypass", "sham"} else "deferred"),
            result=outcome,
            metrics={
                "committed": bool(outcome.get("committed")),
                "local_model_calls": int(
                    outcome.get("local_model_calls") or 0),
                "vector_gap_before": int(
                    dict(outcome.get("before") or {}).get("vector_gap") or 0),
                "vector_gap_after": int(
                    dict(outcome.get("after") or {}).get("vector_gap") or 0),
            })

    def observe(self, *, captured_epoch: int,
                now: float | None = None) -> dict[str, Any]:
        """Record a changed projection and submit only a genuinely reachable arm."""
        now = float(self.clock() if now is None else now)
        projection = self.project(captured_epoch=captured_epoch, now=now)
        revision = str(projection.get("projection_revision") or "")
        recorded = False
        with self._lock:
            if revision and revision not in self._seen:
                self._seen.add(revision)
                recorded = True
                self._last_projection = dict(projection)
        if recorded:
            self._append({
                **projection,
                "at": now,
                "kind": "quiet_assimilation_reachability",
                "observer_receipt_writes": 1,
            })
        candidates = list(projection.get("candidates") or ())
        reachable = bool(candidates and candidates[0].get("reachable"))
        if (self.mode != "live" or not reachable or not revision
                or self.controller is None):
            return {
                "status": "observed",
                "recorded": recorded,
                "reachable": reachable,
                "operator_submitted": False,
                "projection_revision": revision or None,
                "content_free": True,
            }
        with self._lock:
            if revision in self._submitted:
                return {
                    "status": "already_submitted", "recorded": recorded,
                    "reachable": True, "operator_submitted": False,
                    "projection_revision": revision, "content_free": True,
                }
            self._submitted.add(revision)
        try:
            plan = self.operator.plan(self.arm)
            run_id = "quiet-assimilation-" + revision.split(":")[-1][:32]
            future = self.controller.start(
                run_id,
                lambda context: self._run(
                    context, plan, revision, int(captured_epoch)),
                proposal_id=self.experiment_id,
                replace=False,
                interruptible=True)
        except Exception:
            with self._lock:
                self._submitted.discard(revision)
            raise

        def settle(done):
            try:
                done.result()
            except Exception:
                # The shared controller owns failure receipts. A changed owner
                # revision may create a later, distinct opportunity.
                pass

        future.add_done_callback(settle)
        return {
            "status": "submitted",
            "recorded": recorded,
            "reachable": True,
            "operator_submitted": True,
            "projection_revision": revision,
            "content_free": True,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": 1,
                "stage": "R1",
                "enabled": self.enabled,
                "mode": self.mode,
                "arm": self.arm,
                "execute_authorized": self.execute_authorized,
                "experiment_id": self.experiment_id or None,
                "operator_id": self.operator_id,
                "projection_count": len(self._seen),
                "submitted_count": len(self._submitted),
                "last_projection": dict(self._last_projection)
                if self._last_projection else None,
                "last_outcome": dict(self._last_outcome)
                if self._last_outcome else None,
                "content_free": True,
            }


__all__ = ["QuietAssimilationRuntime"]
