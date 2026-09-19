"""Assemble R-1 evidence from existing owners without reading their content.

Every owner call used here is an explicit content-free status projection.  The
module contains no filesystem writer and no maintenance operation.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from core.rest_field.resource_ecology import (
    RESOURCE_SPECS,
    project_resource_ecology,
    unavailable_evidence,
)


def _bounded(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return max(0.0, min(1.0, value))


def _available(persona: str, measurements: Mapping[str, Any], *,
               status: str = "supported", freshness: str = "live",
               evidence_at: Any = None, absence=()) -> dict[str, Any]:
    return {
        "persona": persona,
        "status": status,
        "freshness": freshness,
        "evidence_at": evidence_at,
        "measurements": dict(measurements),
        "absence_reasons": list(absence),
    }


def _missing(persona: str, reason: str) -> dict[str, Any]:
    return _available(
        persona, {}, status="unavailable", freshness="unknown",
        absence=(reason,))


def _prompt_evidence(persona: str, summary: Mapping[str, Any] | None):
    if not summary:
        return _missing(persona, "prompt receipt summary unavailable")
    if str(summary.get("persona") or "") != persona:
        raise ValueError("prompt summary persona does not match audit persona")
    totals = dict(summary.get("totals") or {})
    recent = list(summary.get("recent") or ())
    latest = dict(recent[0]) if recent else {}
    window = latest.get("practical_window_tokens")
    occupied = latest.get("estimated_total_tokens_before_policy")
    load = (min(1.0, max(0.0, float(occupied) / float(window)))
            if isinstance(window, (int, float)) and float(window) > 0
            and isinstance(occupied, (int, float)) else None)
    available = (max(0, int(window) - int(occupied))
                 if isinstance(window, (int, float))
                 and isinstance(occupied, (int, float)) else None)
    measurements = {
        "assemblies": int(totals.get("assemblies") or 0),
        "practical_window_tokens": window,
        "occupied_tokens": occupied,
        "available_tokens": available,
        "load_fraction": load,
        "truncated_candidates": int(
            totals.get("truncated_candidates") or 0),
        "dropped_candidates": int(totals.get("dropped_candidates") or 0),
        "provider_input_tokens": latest.get("provider_input_tokens"),
    }
    absence = []
    if not latest:
        absence.append("no assembly exists in the selected history window")
    if latest and latest.get("provider_input_tokens") is None:
        absence.append("latest provider input usage is unmetered")
    return _available(
        persona, measurements, status=("supported" if latest else "partial"),
        freshness="history_window", evidence_at=summary.get("generated_at"),
        absence=absence)


def _dmn_evidence(persona: str, engine, observed_at):
    field = getattr(engine, "idle_metabolism", None)
    method = getattr(field, "resource_status", None)
    if not callable(method):
        return _missing(persona, "IdleMetabolism resource status unavailable")
    status = method(now=observed_at)
    return _available(persona, {
        key: status.get(key) for key in (
            "candidate_count", "eligible_count", "revised_candidate_count",
            "oldest_age_s")
    }, evidence_at=observed_at,
        absence=("DMNQueue has no authoritative normalized capacity",))


def _gist_evidence(persona: str, engine, observed_at):
    gist = getattr(engine, "gist", None)
    organ = getattr(engine, "organ", None)
    method = getattr(gist, "resource_status", None)
    if not callable(method) or organ is None:
        return _missing(persona, "RollingGist owner is not configured")
    status = method(getattr(organ, "memories", ()))
    return _available(persona, {
        key: status.get(key) for key in (
            "source_cursor", "eligible_count", "pending_source_chars",
            "source_char_budget", "load_fraction")
    }, evidence_at=observed_at)


def _controller_evidence(persona: str, controller, observed_at):
    method = getattr(controller, "status", None)
    if not callable(method):
        return _missing(persona, "maintenance controller unavailable")
    status = method()
    active = bool(status.get("active"))
    opened = bool(status.get("controller_open"))
    occupied = int(active)
    return _available(persona, {
        "capacity": 1,
        "occupied": occupied,
        "available": int(opened and not active),
        "slack_fraction": float(opened and not active),
        "controller_open": opened,
        "replacement_pending": bool(status.get("replacement_pending")),
    }, evidence_at=observed_at)


def _lease_evidence(persona: str, leases, observed_at):
    method = getattr(leases, "status", None)
    if not callable(method):
        return _missing(persona, "resident lease status unavailable")
    status = method()
    rows = list(dict(status.get("leases") or {}).values())
    occupied = sum(bool(row.get("held")) for row in rows)
    capacity = len(rows)
    return _available(persona, {
        "capacity": capacity,
        "occupied": occupied,
        "available": max(0, capacity - occupied),
        "slack_fraction": (
            (capacity - occupied) / capacity if capacity else None),
        "contentions": sum(int(row.get("contentions") or 0) for row in rows),
        "wait_s": round(sum(float(row.get("wait_s") or 0.0)
                            for row in rows), 3),
        "max_wait_s": max(
            (float(row.get("max_wait_s") or 0.0) for row in rows),
            default=0.0),
    }, evidence_at=observed_at)


def _model_evidence(persona: str, engine,
                    summary: Mapping[str, Any] | None, observed_at):
    if not summary:
        return _missing(persona, "model-call receipt summary unavailable")
    persona_group = next((dict(row) for row in
                          (summary.get("groups") or {}).get("persona", ())
                          if str(row.get("key") or "") == persona), {})
    recent = [dict(row) for row in summary.get("recent") or ()
              if str(row.get("persona") or "") == persona]
    local_providers = {"ollama", "local", "localhost"}
    local_calls = sum(str(row.get("provider") or "").casefold()
                      in local_providers for row in recent)
    api_calls = sum(bool(str(row.get("provider") or ""))
                    and str(row.get("provider") or "").casefold()
                    not in local_providers for row in recent)
    budget = getattr(engine, "autonomous_deliberation_budget", None)
    budget_status = {}
    snapshot = getattr(budget, "resource_status", None)
    if callable(snapshot):
        budget_status = dict(snapshot(now=observed_at) or {})
    token_cap = budget_status.get("rolling_token_cap")
    token_remaining = budget_status.get("rolling_tokens_remaining")
    credit_capacity = budget_status.get("credit_capacity")
    credit_balance = budget_status.get("credit_balance")
    slack_values = []
    if isinstance(token_cap, (int, float)) and float(token_cap) > 0 \
            and isinstance(token_remaining, (int, float)):
        slack_values.append(float(token_remaining) / float(token_cap))
    if isinstance(credit_capacity, (int, float)) and float(credit_capacity) > 0 \
            and isinstance(credit_balance, (int, float)):
        slack_values.append(float(credit_balance) / float(credit_capacity))
    slack = (math.prod(_bounded(value) for value in slack_values)
             ** (1.0 / len(slack_values)) if slack_values else None)
    measurements = {
        "calls": int(persona_group.get("calls") or 0),
        "errors": int(persona_group.get("errors") or 0),
        "input_tokens": int(persona_group.get("input_tokens") or 0),
        "output_tokens": int(persona_group.get("output_tokens") or 0),
        "missing_usage": int(persona_group.get("missing_usage") or 0),
        "local_calls": local_calls,
        "api_calls": api_calls,
        "estimated_cost_usd": None,
        "configured_budget": bool(budget_status.get("enabled")),
        "slack_fraction": slack,
    }
    absence = ["model-call ledger has no authoritative cost field"]
    if not budget_status.get("enabled"):
        absence.append("no configured autonomous route budget is active")
    if not persona_group:
        absence.append("no persona calls exist in the selected history window")
    return _available(
        persona, measurements, status="partial", freshness="history_window",
        evidence_at=summary.get("generated_at") or observed_at,
        absence=absence)


def _document_evidence(persona: str, runtime, observed_at):
    method = getattr(runtime, "resource_status", None)
    if not callable(method):
        return _missing(persona, "document reader owner is unavailable")
    status = method(now=observed_at)
    return _available(persona, {
        key: status.get(key) for key in (
            "active_arcs", "paused_arcs", "unfinished_arcs",
            "foreground_packet_count", "recent_fire_count",
            "max_fires_per_hour", "hourly_capped",
            "cap_release_remaining_s")
    }, evidence_at=observed_at,
        absence=("document reader supplies no normalized total arc capacity",))


def _intention_evidence(persona: str, runtime, writing_runtime, observed_at):
    loom = getattr(runtime, "loom", None)
    method = getattr(loom, "resource_status", None)
    status = method() if callable(method) else {}
    measurements = {key: status.get(key) for key in (
        "pending_cues", "open_intentions", "paused_intentions",
        "satisfied_intentions", "released_intentions",
        "unselected_exposures")}

    project_loom = getattr(runtime, "project_loom", None)
    project_method = getattr(project_loom, "resource_status", None)
    project_status = project_method() if callable(project_method) else {}
    measurements.update({
        "project_proposals": project_status.get("proposal_count"),
        "pending_project_adoptions": project_status.get(
            "pending_owner_adoption_count"),
        "project_owner_outcomes": project_status.get("owner_outcome_count"),
    })

    desk = getattr(writing_runtime, "desk", None)
    desk_method = getattr(desk, "resource_status", None)
    desk_status = desk_method() if callable(desk_method) else {}
    measurements.update({
        "pending_project_seeds": desk_status.get("pending_seed_count"),
        "owned_projects": desk_status.get("project_count"),
        "open_projects": desk_status.get("open_project_count"),
        "paused_projects": desk_status.get("paused_project_count"),
        "completed_projects": desk_status.get("completed_project_count"),
        "abandoned_projects": desk_status.get("abandoned_project_count"),
        "archived_projects": desk_status.get("archived_project_count"),
    })
    unresolved = sum(int(measurements.get(key) or 0) for key in (
        "pending_cues", "open_intentions", "paused_intentions"))
    unresolved += sum(int(measurements.get(key) or 0) for key in (
        "pending_project_adoptions", "pending_project_seeds",
        "open_projects", "paused_projects"))
    measurements["private_authority"] = float(unresolved > 0)
    absence = [
        "intention/project owners supply no normalized total capacity"]
    if not status:
        absence.append("IntentionLoom owner is unavailable")
    if not project_status:
        absence.append("ProjectLoom owner is unavailable")
    if not desk_status:
        absence.append("WritingDesk owner is unavailable")
    owner_count = sum(bool(value) for value in (
        status, project_status, desk_status))
    if not owner_count:
        return _missing(persona, "intention and project owners are unavailable")
    return _available(
        persona, measurements,
        status="partial",
        evidence_at=observed_at, absence=absence)


def _memory_evidence(persona: str, engine, workbench, observed_at):
    organ = getattr(engine, "organ", None)
    method = getattr(organ, "resource_status", None)
    if not callable(method):
        return _missing(persona, "MemoryEmotionOrgan owner is unavailable")
    status = method()
    measurements = {key: status.get(key) for key in (
        "canonical_records", "memory_revision", "persisted_revision",
        "context_index_records", "vector_records", "vector_covered",
        "vector_rows", "vector_pending", "vector_gap", "vector_healthy",
        "index_gap", "load_fraction", "private_authority")}
    curation = getattr(workbench, "status", None)
    if callable(curation):
        measurements["curation_incomplete_transactions"] = int(
            curation().get("incomplete_transactions") or 0)
    absence = []
    if status.get("vector_covered") != status.get("canonical_records"):
        absence.append("derived vector coverage differs from canonical count")
    return _available(persona, measurements, evidence_at=observed_at,
                      absence=absence)


def _activity_evidence(persona: str, engine, observed_at):
    ecology = getattr(engine, "activity_ecology", None)
    method = getattr(ecology, "resource_status", None)
    if not callable(method):
        return _missing(persona, "ActivityEcology owner is unavailable")
    status = method(now=observed_at)
    return _available(
        persona, {key: status.get(key) for key in (
            "enabled", "mode_count", "realized_event_count",
            "latest_realized_age_s", "max_nonquiet_satiety",
            "quiet_satiety")},
        status="partial", evidence_at=observed_at,
        absence=(
            "activity satiety is context, not authoritative finite capacity",))


def _substrate_evidence(persona: str, engine, observed_at):
    substrate = getattr(engine, "substrate", None)
    method = getattr(substrate, "resource_status", None)
    if not callable(method):
        return _missing(persona, "SubstrateAccumulator owner is unavailable")
    status = method()
    return _available(persona, {key: status.get(key) for key in (
        "capacity_s", "occupied_s", "available_s", "active_modalities",
        "interval_count", "load_fraction", "slack_fraction")},
        evidence_at=observed_at)


def _ingress_evidence(persona: str, engine, mailbox, controller, observed_at):
    sensory = getattr(engine, "perception", None)
    sensory_method = getattr(sensory, "resource_status", None)
    sensory_status = (sensory_method(now=observed_at)
                      if callable(sensory_method) else {})
    mailbox_method = getattr(mailbox, "status", None)
    mailbox_status = mailbox_method() if callable(mailbox_method) else {}
    depth = mailbox_status.get("depth")
    capacity = mailbox_status.get("capacity")
    mailbox_load = (float(depth) / float(capacity)
                    if isinstance(depth, (int, float))
                    and isinstance(capacity, (int, float))
                    and float(capacity) > 0 else None)
    controller_status = (controller.status()
                         if callable(getattr(controller, "status", None))
                         else {})
    low_ingress = sensory_status.get("low_ingress")
    low_interruption = None
    if mailbox_load is not None:
        low_interruption = (1.0 - _bounded(mailbox_load)) * float(
            not bool(controller_status.get("replacement_pending")))
    measurements = {
        "sensory_modalities": sensory_status.get("sensory_modalities"),
        "fresh_sensory_modalities": sensory_status.get(
            "fresh_sensory_modalities"),
        "latest_sensory_age_s": sensory_status.get("latest_sensory_age_s"),
        "max_sensory_pressure": sensory_status.get("max_sensory_pressure"),
        "mailbox_depth": depth,
        "mailbox_capacity": capacity,
        "mailbox_load_fraction": mailbox_load,
        "low_ingress": low_ingress,
        "low_interruption_risk": low_interruption,
    }
    absence = []
    if low_ingress is None:
        absence.append(
            "no sensory crossing remains inside the owner's retention horizon")
    if mailbox_load is None:
        absence.append("mailbox capacity evidence unavailable")
    return _available(
        persona, measurements, status=("supported" if not absence else "partial"),
        evidence_at=observed_at, absence=absence)


def collect_resource_ecology(*, engine, leases=None, controller=None,
                             document_reader=None, intention_runtime=None,
                             writing_runtime=None,
                             memory_curation=None, mailbox=None,
                             prompt_summary=None, model_summary=None,
                             observed_at=None) -> dict[str, Any]:
    """Collect current owner snapshots and return the pure R-1 projection."""
    persona = str(getattr(engine, "persona", "") or "").strip()
    if not persona:
        raise ValueError("engine has no persona binding")
    evidence = unavailable_evidence(persona, "owner evidence not collected")
    evidence.update({
        "prompt_context_capacity": _prompt_evidence(persona, prompt_summary),
        "dmn_candidate_congestion": _dmn_evidence(
            persona, engine, observed_at),
        "consolidation_backlog": _gist_evidence(
            persona, engine, observed_at),
        "maintenance_controller_capacity": _controller_evidence(
            persona, controller, observed_at),
        "resident_leases": _lease_evidence(persona, leases, observed_at),
        "model_call_use": _model_evidence(
            persona, engine, model_summary, observed_at),
        "document_reader_load": _document_evidence(
            persona, document_reader, observed_at),
        "intention_project_load": _intention_evidence(
            persona, intention_runtime, writing_runtime, observed_at),
        "activity_ecology_context": _activity_evidence(
            persona, engine, observed_at),
        "sensory_substrate_capacity": _substrate_evidence(
            persona, engine, observed_at),
        "memory_derived_indexes": _memory_evidence(
            persona, engine, memory_curation, observed_at),
        "hardware_slack": _missing(
            persona, "no authoritative JNAIQ CPU/GPU/VRAM monitor exists"),
        "external_ingress": _ingress_evidence(
            persona, engine, mailbox, controller, observed_at),
    })
    return project_resource_ecology(
        persona=persona, evidence=evidence, observed_at=observed_at)


__all__ = ["collect_resource_ecology"]
