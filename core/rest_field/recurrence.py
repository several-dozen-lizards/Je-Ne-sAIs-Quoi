"""Private, content-free recurrence lineage for controlled trace experiments.

This module does not create recall, attention, work, or meaning.  It observes
event boundaries that already occurred and keeps the experimental arm joined
to a committed narrative trace.  A later durable consequence may be projected
back toward the rest field only through RestRuntime's separate observe-only
source; the live RestField never reads this ledger.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from collections.abc import Mapping


SCHEMA_VERSION = 1
CONDITIONS = frozenset({
    "matched_labeled",
    "matched_label_removed",
    "mismatched_label_removed",
    "random_label_removed",
    "distance_matched_random_label_removed",
    "sham_none",
})
STAGES = frozenset({
    "encoded", "selected", "rendered", "offered", "won", "used",
})
RELATIONS = frozenset({
    "origin", "foreground_recall", "dmn_recall", "dmn_attention",
    "descendant_memory", "narrative_source", "private_intention_cue",
})
HEX = re.compile(r"^[0-9a-f]{16,64}$")


def _unit(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return max(0.0, min(1.0, number))


def _digest(value) -> str:
    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def _safe_hex(value, *, allow_empty=False) -> str | None:
    value = str(value or "").casefold()
    if HEX.fullmatch(value):
        return value
    return None if allow_empty else ""


def _quiet_projection(quiet_controller) -> dict:
    if quiet_controller is None:
        return {
            "quiet_state": "unavailable",
            "reduced_external_conductance": 0.0,
        }
    try:
        snapshot = dict(quiet_controller.snapshot() or {})
    except Exception:
        return {
            "quiet_state": "unavailable",
            "reduced_external_conductance": 0.0,
        }
    profile = dict(snapshot.get("conductance_profile") or {})
    external = max((_unit(profile.get(name), 1.0) for name in (
        "autonomous_outward_initiation",
        "autonomous_bodily_initiation",
        "private_work_admission",
    )), default=1.0)
    return {
        "quiet_state": str(snapshot.get("state") or "unavailable")[:48],
        "reduced_external_conductance": round(1.0 - external, 9),
    }


def _rest_projection(rest_runtime, quiet_controller, *, at: float) -> dict:
    try:
        snapshot = dict(rest_runtime.snapshot(at=at) or {})
    except Exception as exc:
        return {"status": "rest_snapshot_failed",
                "error_type": type(exc).__name__}
    field = dict(snapshot.get("field") or {})
    dimensions = dict(field.get("dimensions") or {})
    if not all(name in dimensions for name in (
            "associative_mobility", "trace_retention")):
        return {"status": "rest_dimensions_unavailable"}
    quiet = _quiet_projection(quiet_controller)
    basis = {
        "rest_experiment_id": str(snapshot.get("experiment_id") or "")[:96],
        "rest_config_hash": str(field.get("config_hash") or "")[:96],
        "rest_event_count": max(0, int(field.get("event_count") or 0)),
        "associative_mobility": round(_unit(
            dimensions.get("associative_mobility"), 0.5), 9),
        "trace_retention": round(_unit(
            dimensions.get("trace_retention"), 0.5), 9),
        **quiet,
    }
    return {
        "status": "ready",
        **basis,
        "rest_state_digest": _digest(basis),
    }


def project_recombination_provenance(
        rest_runtime, quiet_controller, neighborhood: Mapping,
        process_probe: Mapping, attempt_revision: str, *, at: float) -> dict:
    """Describe the synthetic rest relationship at one real appraisal.

    The propensity is an equal-factor geometric relation among the two
    existing rest dimensions, the existing neighborhood locality, and reduced
    external conductance.  It is stored as an observation; it does not gate or
    bend the P1 appraisal.
    """
    p1 = dict(getattr(
        rest_runtime, "process_recombination_probe", {}) or {})
    p2 = dict(getattr(
        rest_runtime, "trace_recurrence_observer", {}) or {})
    base = {
        "schema_version": SCHEMA_VERSION,
        "status": "not_authorized",
        "p1_experiment_id": p1.get("experiment_id"),
        "p2_experiment_id": p2.get("experiment_id"),
        "ownership": "persona_private",
        "content_free": True,
    }
    if not p1.get("authorized") or not p2.get("authorized"):
        return base
    condition = str(dict(process_probe or {}).get("condition") or "")
    if condition not in CONDITIONS:
        return {**base, "status": "probe_condition_unavailable"}
    rest = _rest_projection(rest_runtime, quiet_controller, at=float(at))
    if rest.get("status") != "ready":
        return {**base, "status": rest.get("status", "rest_unavailable"),
                "error_type": rest.get("error_type")}
    locality = _unit(dict(neighborhood or {}).get("semantic_locality"))
    factors = (
        rest["associative_mobility"], rest["trace_retention"], locality,
        rest["reduced_external_conductance"],
    )
    propensity = math.prod(factors) ** (1.0 / len(factors))
    attempt_digest = _digest(str(attempt_revision or ""))
    provenance_basis = {
        "p1_experiment_id": p1.get("experiment_id"),
        "p2_experiment_id": p2.get("experiment_id"),
        "condition": condition,
        "probe_digest": dict(process_probe or {}).get("probe_digest"),
        "attempt_digest": attempt_digest,
        "rest_state_digest": rest["rest_state_digest"],
        "quiet_state": rest["quiet_state"],
        "reduced_external_conductance": rest[
            "reduced_external_conductance"],
        "candidate_locality": round(locality, 9),
        "recurrence_propensity": round(propensity, 9),
    }
    return {
        **base,
        **provenance_basis,
        "status": "ready",
        "provenance_digest": _digest(provenance_basis),
    }


def normalize_recombination_provenance(value: Mapping | None) -> dict:
    """Return only the bounded private provenance allowed into a memory."""
    value = dict(value or {})
    if value.get("status") != "ready" \
            or value.get("condition") not in CONDITIONS \
            or not str(value.get("p1_experiment_id") or "").strip() \
            or not str(value.get("p2_experiment_id") or "").strip():
        return {}
    required_hex = (
        "attempt_digest", "rest_state_digest", "provenance_digest")
    if any(not _safe_hex(value.get(name)) for name in required_hex):
        return {}
    probe_digest = _safe_hex(value.get("probe_digest"), allow_empty=True)
    if value.get("condition") != "sham_none" and not probe_digest:
        return {}
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready",
        "p1_experiment_id": str(value.get("p1_experiment_id") or "")[:96],
        "p2_experiment_id": str(value.get("p2_experiment_id") or "")[:96],
        "condition": value["condition"],
        "probe_digest": probe_digest,
        "attempt_digest": value["attempt_digest"],
        "rest_state_digest": value["rest_state_digest"],
        "provenance_digest": value["provenance_digest"],
        "quiet_state": str(value.get("quiet_state") or "unavailable")[:48],
        "reduced_external_conductance": round(_unit(
            value.get("reduced_external_conductance")), 9),
        "candidate_locality": round(_unit(
            value.get("candidate_locality")), 9),
        "recurrence_propensity": round(_unit(
            value.get("recurrence_propensity")), 9),
        "ownership": "persona_private",
        "content_free": True,
    }


class TraceRecurrenceLedger:
    """Append-only lifecycle and consequence receipts for P2 traces."""

    def __init__(self, persona_dir: str, rest_runtime):
        self.persona_dir = os.path.abspath(os.fspath(persona_dir))
        self.rest_runtime = rest_runtime
        self.authorization = dict(getattr(
            rest_runtime, "trace_recurrence_observer", {}) or {})
        self.authorized = bool(self.authorization.get("authorized"))
        self.path = os.path.join(
            self.persona_dir, "history", "rest_trace_recurrence.jsonl")
        self._lock = threading.RLock()
        self._seen = set()
        self._restore_seen()

    def _restore_seen(self, maximum_bytes=2_000_000):
        try:
            with open(self.path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                start = max(0, size - int(maximum_bytes))
                handle.seek(start)
                data = handle.read()
            if start:
                data = data.split(b"\n", 1)[-1]
            for line in data.splitlines():
                try:
                    row = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, TypeError, ValueError):
                    continue
                key = str(row.get("recurrence_key") or "")
                if HEX.fullmatch(key):
                    self._seen.add(key)
        except OSError:
            return

    @staticmethod
    def provenance(memory: Mapping | None) -> dict:
        return normalize_recombination_provenance(
            dict((memory or {}).get("fields") or {}).get(
                "experimental_recombination"))

    def record(self, memory: Mapping | None, stage: str, *,
               event_ref: str, at: float | None = None,
               relation: str = "foreground_recall",
               consequence: bool = False,
               child_memory_id: str = "",
               quiet_controller=None) -> dict:
        if not self.authorized:
            return {"status": "not_authorized", "recorded": False}
        stage = str(stage or "")
        relation = str(relation or "")
        if stage not in STAGES or relation not in RELATIONS:
            return {"status": "invalid_boundary", "recorded": False}
        provenance = self.provenance(memory)
        if not provenance or provenance.get("p2_experiment_id") != \
                self.authorization.get("experiment_id"):
            return {"status": "not_experimental_trace", "recorded": False}
        memory_id = str((memory or {}).get("id") or "")
        if not memory_id or not str(event_ref or ""):
            return {"status": "event_identity_required", "recorded": False}
        now = float(time.time() if at is None else at)
        trace_digest = _digest(memory_id)[:16]
        event_digest = _digest(str(event_ref))[:16]
        child_digest = (_digest(str(child_memory_id))[:16]
                        if child_memory_id else None)
        recurrence_key = _digest({
            "trace": trace_digest,
            "stage": stage,
            "relation": relation,
            "event": event_digest,
            "child": child_digest,
        })
        with self._lock:
            if recurrence_key in self._seen:
                return {"status": "duplicate", "recorded": False,
                        "recurrence_key": recurrence_key}
            current = _rest_projection(
                self.rest_runtime, quiet_controller, at=now)
            row = {
                "schema_version": SCHEMA_VERSION,
                "kind": "rest_trace_recurrence",
                "at": now,
                "experiment_id": self.authorization.get("experiment_id"),
                "p1_experiment_id": provenance.get("p1_experiment_id"),
                "trace_digest": trace_digest,
                "child_trace_digest": child_digest,
                "event_digest": event_digest,
                "recurrence_key": recurrence_key,
                "stage": stage,
                "relation": relation,
                "condition": provenance.get("condition"),
                "origin_rest_state_digest": provenance.get(
                    "rest_state_digest"),
                "current_rest_state_digest": current.get(
                    "rest_state_digest"),
                "origin_recurrence_propensity": provenance.get(
                    "recurrence_propensity"),
                "durable_consequence": bool(consequence),
                "ownership": "persona_private",
                "external_effects": False,
                "content_free": True,
            }
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") \
                    as handle:
                handle.write(json.dumps(
                    row, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._seen.add(recurrence_key)

        feedback = {"recorded": False, "status": "not_a_consequence"}
        if consequence:
            feedback = self.rest_runtime.observe_trace_recurrence(
                recurrence_propensity=provenance.get(
                    "recurrence_propensity", 0.0),
                event_ref=recurrence_key,
                trace_digest=trace_digest,
                condition=provenance.get("condition"),
                origin_rest_state_digest=provenance.get(
                    "rest_state_digest"),
                at=now)
        return {**row, "status": "recorded", "recorded": True,
                "feedback": feedback}
