"""C4: bounded rest-field circulation into already-existing private work.

This module can alter only the salience projection of material that an organ
has independently declared pending. It cannot create work, call a model,
select a winner, or execute an effect.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from typing import Any, Mapping

from core.dmn import event_salience


def _bounded(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    if number != number or number in {float("inf"), float("-inf")}:
        number = float(default)
    return max(0.0, min(1.0, number))


def _revision(prefix: str, payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def offer_maintenance_candidate(
        runtime, field, source: str, content: str,
        features: Mapping[str, Any] | None = None, *, key: str,
        now: float, raw_ref=None, ownership=None, receipts=None,
        revision_facts: Mapping[str, Any] | None = None):
    """Project one real pending record through the C4 junction.

    `work_revision` identifies durable source evidence. `source_revision`
    additionally identifies the content-free organism/resource context of
    this genuine DMN opportunity. Exact repetition therefore preserves decay,
    while changed work or changed capacity replaces the projection rather
    than probabilistically unioning it.
    """
    features = dict(features or {})
    baseline, bounded_features, _components = event_salience(features)
    receipt_refs = [str(value or "")[:160] for value in (receipts or ())]
    work_revision = _revision("maintenance-work", {
        "source": str(source or "")[:80],
        "key": str(key or "")[:160],
        "raw_ref": str(raw_ref or "")[:160],
        "receipts": receipt_refs,
        "features": {name: round(float(value), 6)
                     for name, value in sorted(bounded_features.items())},
        "revision_facts": dict(revision_facts or {}),
    })

    state = dict(runtime.readiness(field) or {})
    controller = getattr(runtime, "controller", None)
    controller_state = (
        dict(controller.status() or {}) if controller is not None else {})
    active = dict(controller_state.get("active") or {})
    controller_open = bool(controller_state.get("controller_open", True))
    active_key = str(getattr(
        getattr(runtime, "engine", None),
        "_maintenance_active_candidate_key", "") or "")
    blocked_reasons = []
    if state.get("hard_blocked"):
        blocked_reasons.append("organ_recovery_blocked")
    if not controller_open:
        blocked_reasons.append("private_work_controller_closed")
    if active:
        blocked_reasons.append(
            "already_running" if active_key == str(key)
            else "private_work_capacity_occupied")

    context = {
        "readiness": _bounded(state.get("readiness")),
        "capacity": _bounded(state.get("capacity")),
        "resource_availability": 0.0 if active or not controller_open else 1.0,
    }
    conduct_opportunity = bool(getattr(
        field, "_maintenance_conduct_opportunity", False))
    rest_runtime = getattr(
        getattr(runtime, "engine", None), "rest_runtime", None)
    driven_field = {}
    if rest_runtime is not None and conduct_opportunity:
        try:
            snapshot = rest_runtime.field.peek(now)
            dimensions = dict(snapshot.get("dimensions") or {})
            drivers = dict(rest_runtime.junction_drivers.get(
                "maintenance_candidate_salience") or {})
            driven_field = {
                name: round(_bounded(dimensions.get(name), .5), 3)
                for name in sorted(drivers)}
        except (AttributeError, TypeError, ValueError):
            driven_field = {}
    projection_revision = _revision(
        "maintenance-opportunity" if conduct_opportunity
        else "maintenance-inventory", {
            "work_revision": work_revision,
            **({
                "context": {name: round(value, 3)
                            for name, value in sorted(context.items())},
                "rest_dimensions": driven_field,
                "blocked_reasons": blocked_reasons,
            } if conduct_opportunity else {}),
        })

    offered = baseline
    junction_receipt = {}
    if rest_runtime is not None and conduct_opportunity:
        offered, junction_receipt = rest_runtime.route_maintenance_salience(
            baseline, at=now,
            event_ref=projection_revision + ":dmn_fire",
            source_revision_ref=projection_revision,
            work_revision=work_revision,
            context_values=context,
            blocked_reasons=blocked_reasons)
    projection_context = {
        **{name: round(value, 6) for name, value in context.items()},
        "gate": (
            blocked_reasons[0] if conduct_opportunity and blocked_reasons
            else "open" if conduct_opportunity
            else "awaiting_substrate_fire"),
        "blocked_reasons": (
            list(blocked_reasons) if conduct_opportunity else []),
        "work_revision": work_revision,
        "content_free": True,
    }
    return field.offer_cognitive_event(
        source, content, features, key=key, now=now, raw_ref=raw_ref,
        ownership=ownership, receipts=receipts, salience=offered,
        source_revision=projection_revision, work_revision=work_revision,
        salience_receipt=junction_receipt,
        projection_context=projection_context)


@contextmanager
def maintenance_fire(field):
    """Open C4 conduct only around one already-earned DMN fire."""
    marker = "_maintenance_conduct_opportunity"
    prior = getattr(field, marker, None)
    setattr(field, marker, True)
    try:
        yield
    finally:
        if prior is None:
            try:
                delattr(field, marker)
            except AttributeError:
                pass
        else:
            setattr(field, marker, prior)


def selection_gate(engine, candidate: Mapping[str, Any]) -> dict:
    """Return current resource truth for a projected maintenance candidate."""
    candidate = dict(candidate or {})
    if not candidate.get("work_revision"):
        return {"eligible": True, "gate": "not_maintenance"}
    runtimes = (
        getattr(engine, name, None) for name in (
            "intention_loom_runtime", "writing_desk_runtime",
            "archive_reader_runtime", "document_reader_runtime",
            "research_desk_runtime", "atelier_runtime"))
    controller = next((getattr(runtime, "controller", None)
                       for runtime in runtimes if runtime is not None), None)
    if controller is None:
        return {"eligible": False, "gate": "controller_unavailable"}
    status = dict(controller.status() or {})
    if not status.get("controller_open", True):
        return {"eligible": False, "gate": "controller_closed"}
    active = dict(status.get("active") or {})
    if not active:
        return {"eligible": True, "gate": "open"}
    active_key = str(getattr(
        engine, "_maintenance_active_candidate_key", "") or "")
    return {
        "eligible": False,
        "gate": ("already_running" if active_key == str(candidate.get("key"))
                 else "capacity_blocked"),
        "active_run_id": str(active.get("run_id") or "")[:120],
    }
