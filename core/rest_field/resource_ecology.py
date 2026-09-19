"""Read-only, content-free R-1 resource ecology projection.

This module owns no resource.  It accepts bounded snapshots from existing
owners, refuses content-bearing shapes, and projects the relationship among
real load, ingress, interruption risk, measured slack, and private authority.
It never writes, schedules work, changes RestField, or executes maintenance.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping


SCHEMA_VERSION = 1
EVIDENCE_STATES = frozenset({"supported", "partial", "unavailable"})
FRESHNESS_CLASSES = frozenset({
    "live", "history_window", "stale", "unknown",
})
FACTOR_NAMES = (
    "genuine_unintegrated_load",
    "low_external_ingress",
    "low_interruption_risk",
    "measured_resource_slack",
    "private_authority_to_act",
)


RESOURCE_SPECS = {
    "prompt_context_capacity": {
        "owner": "adapters.assembly.PromptAssembly",
        "receipt_owner": "prompt_assembly_receipts.jsonl / PAC0",
        "consumption_event": (
            "PromptAssembly.enforce_budgets records practical-window use and "
            "retained, truncated, or dropped candidate outcomes"),
        "restorative_operation": None,
        "operation_absence": (
            "no bounded pre-assembly packet compaction operator is currently "
            "owned by PromptAssembly"),
        "privacy_boundary": "prompt/source text and content digests excluded",
        "authority_boundary": "PromptAssembly remains the only budget owner",
        "foreground_boundary": "observation cannot change budgets or blocks",
        "measurements": frozenset({
            "assemblies", "practical_window_tokens", "occupied_tokens",
            "available_tokens", "load_fraction", "truncated_candidates",
            "dropped_candidates", "provider_input_tokens",
        }),
    },
    "dmn_candidate_congestion": {
        "owner": "core.dmn.IdleMetabolism / DMNQueue",
        "receipt_owner": "IdleMetabolism.resource_status",
        "consumption_event": (
            "candidate offer, merge, or requeue occupies the decaying field"),
        "restorative_operation": (
            "existing win/discharge, proved withdrawal, or natural expiry "
            "releases a candidate"),
        "operation_absence": None,
        "privacy_boundary": "candidate keys, nodes, and receipts excluded",
        "authority_boundary": "DMNQueue alone owns candidate lifecycle",
        "foreground_boundary": "snapshot_items only; no decay or pop",
        "measurements": frozenset({
            "candidate_count", "eligible_count", "requeued_count",
            "revised_candidate_count", "oldest_age_s", "load_fraction",
        }),
    },
    "consolidation_backlog": {
        "owner": "core.memory_emotion.gist.RollingGist + IdleMetabolism",
        "receipt_owner": "RollingGist.resource_status",
        "consumption_event": (
            "new gist-eligible canonical records beyond the durable cursor "
            "increase pending source count and characters"),
        "restorative_operation": (
            "an ordinary winning consolidation transaction advances the "
            "durable cursor by the consumed contiguous source count"),
        "operation_absence": None,
        "privacy_boundary": "source records and gist text excluded",
        "authority_boundary": "RollingGist cursor remains authoritative",
        "foreground_boundary": "pending-source projection is read-only",
        "measurements": frozenset({
            "source_cursor", "eligible_count", "pending_source_chars",
            "source_char_budget", "load_fraction",
        }),
    },
    "maintenance_controller_capacity": {
        "owner": "shell.agency_controller.AgencyRunController",
        "receipt_owner": "AgencyRunController.status",
        "consumption_event": "one active private run occupies the shared slot",
        "restorative_operation": (
            "the controller's existing terminal boundary releases the slot"),
        "operation_absence": None,
        "privacy_boundary": "proposal content and model response excluded",
        "authority_boundary": "controller remains the single slot owner",
        "foreground_boundary": "foreground interruption policy is unchanged",
        "measurements": frozenset({
            "capacity", "occupied", "available", "slack_fraction",
            "controller_open", "replacement_pending",
        }),
    },
    "resident_leases": {
        "owner": "core.resident_leases.ResidentLeaseSet",
        "receipt_owner": "ResidentLeaseSet.status",
        "consumption_event": "mouth/state acquire and contention occupy leases",
        "restorative_operation": "NamedLease.release releases its exact lease",
        "operation_absence": None,
        "privacy_boundary": "cycle payload and deliberation content excluded",
        "authority_boundary": "typed mouth/state leases remain authoritative",
        "foreground_boundary": "status never acquires or releases a lease",
        "measurements": frozenset({
            "capacity", "occupied", "available", "slack_fraction",
            "contentions", "wait_s", "max_wait_s",
        }),
    },
    "model_call_use": {
        "owner": "harness.model_call_receipts",
        "receipt_owner": "model_calls.jsonl / model_call_dashboard",
        "consumption_event": (
            "a scoped provider call records route, usage, cost evidence when "
            "available, and transport outcome"),
        "restorative_operation": None,
        "operation_absence": (
            "receipts do not own provider quota, replenish tokens, or prove a "
            "configured resident budget"),
        "privacy_boundary": "prompt and response never enter the ledger",
        "authority_boundary": "provider/configured route owns real limits",
        "foreground_boundary": "aggregation cannot defer or reroute a call",
        "measurements": frozenset({
            "calls", "errors", "input_tokens", "output_tokens",
            "missing_usage", "local_calls", "api_calls",
            "estimated_cost_usd", "configured_budget", "slack_fraction",
        }),
    },
    "document_reader_load": {
        "owner": "shell.document_reader_runtime.DocumentReaderRuntime",
        "receipt_owner": "DocumentReaderRuntime.resource_status",
        "consumption_event": (
            "an active/paused reading arc, circulating foreground packet, or "
            "hourly fire cap occupies reader attention"),
        "restorative_operation": (
            "ordinary completion/abandonment settles an arc; the existing "
            "rolling fire window renews capacity"),
        "operation_absence": None,
        "privacy_boundary": "document ids, titles, anchors, and text excluded",
        "authority_boundary": "DocumentLibrary and reader runtime own arcs",
        "foreground_boundary": "snapshot_items only; no queue decay",
        "measurements": frozenset({
            "active_arcs", "paused_arcs", "unfinished_arcs",
            "foreground_packet_count", "recent_fire_count",
            "max_fires_per_hour", "hourly_capped",
            "cap_release_remaining_s", "load_fraction",
        }),
    },
    "intention_project_load": {
        "owner": (
            "IntentionLoom + ProjectLoom + WritingDesk"),
        "receipt_owner": (
            "owner resource_status count projections"),
        "consumption_event": (
            "pending cues, unresolved intentions, project proposals/handoffs, "
            "seeds, and open or paused owned projects occupy continuity"),
        "restorative_operation": (
            "resident-authored pause, resume, satisfy, or release transitions "
            "and owner project outcomes reorganize authoritative append-only "
            "lifecycles"),
        "operation_absence": None,
        "privacy_boundary": "cue/intention ids and prose excluded",
        "authority_boundary": "resident remains author of lifecycle changes",
        "foreground_boundary": "counts do not create or resolve intentions",
        "measurements": frozenset({
            "pending_cues", "open_intentions", "paused_intentions",
            "satisfied_intentions", "released_intentions",
            "unselected_exposures", "project_proposals",
            "pending_project_adoptions", "project_owner_outcomes",
            "pending_project_seeds", "owned_projects", "open_projects",
            "paused_projects", "completed_projects", "abandoned_projects",
            "archived_projects", "load_fraction", "private_authority",
        }),
    },
    "activity_ecology_context": {
        "owner": "core.activity_ecology.ActivityEcology",
        "receipt_owner": "ActivityEcology.resource_status",
        "consumption_event": (
            "realized waking activity consequences update bounded per-mode "
            "satiety history, showing activity distribution but not finite "
            "resource consumption"),
        "restorative_operation": None,
        "operation_absence": (
            "natural satiety decay is not a maintenance operation and activity "
            "ecology exposes no authoritative finite capacity to replenish"),
        "privacy_boundary": (
            "candidate, event provenance, and activity content excluded"),
        "authority_boundary": (
            "ActivityEcology remains the consequence/satiety owner"),
        "foreground_boundary": (
            "resource status does not project appetite or alter selection"),
        "measurements": frozenset({
            "enabled", "mode_count", "realized_event_count",
            "latest_realized_age_s", "max_nonquiet_satiety",
            "quiet_satiety",
        }),
    },
    "sensory_substrate_capacity": {
        "owner": "core.substrate.SubstrateAccumulator",
        "receipt_owner": "SubstrateAccumulator.resource_status",
        "consumption_event": (
            "accepted audio/camera body-resolution intervals occupy each "
            "modality's existing 600-second duration buffer"),
        "restorative_operation": (
            "the existing TurnEngine body step calls drain_step and releases "
            "the exact consumed duration"),
        "operation_absence": None,
        "privacy_boundary": (
            "weighted signals, band pressure, and latest receipts excluded"),
        "authority_boundary": (
            "SubstrateAccumulator remains the only transport-buffer owner"),
        "foreground_boundary": "resource status never calls drain_step",
        "measurements": frozenset({
            "capacity_s", "occupied_s", "available_s", "active_modalities",
            "interval_count", "load_fraction", "slack_fraction",
        }),
    },
    "memory_derived_indexes": {
        "owner": "core.memory_emotion.organ.MemoryEmotionOrgan",
        "receipt_owner": "MemoryEmotionOrgan.resource_status",
        "consumption_event": (
            "canonical admissions advance memory revision and may leave a "
            "derived context/vector index coverage gap"),
        "restorative_operation": (
            "rebuild the reproducible ContextCueIndex from canonical memory; "
            "the existing offline vector-sidecar rebuild is separately guarded"),
        "operation_absence": None,
        "privacy_boundary": "memory ids, text, vectors, and reasons excluded",
        "authority_boundary": "memories.json remains canonical",
        "foreground_boundary": (
            "R-1 observes only; any later swap requires resident state lease"),
        "measurements": frozenset({
            "canonical_records", "memory_revision", "persisted_revision",
            "context_index_records", "vector_records", "vector_covered",
            "vector_rows", "vector_pending", "vector_gap",
            "vector_healthy", "index_gap",
            "curation_incomplete_transactions", "load_fraction",
            "private_authority",
        }),
    },
    "hardware_slack": {
        "owner": "no authoritative JNAIQ hardware-resource monitor found",
        "receipt_owner": "unavailable",
        "consumption_event": (
            "local model, vision, voice, Atelier, and rendering processes can "
            "contend, but R-1 has no authoritative numeric owner receipt"),
        "restorative_operation": None,
        "operation_absence": "no reliable sampled release operation exists",
        "privacy_boundary": "process command lines are not inspected",
        "authority_boundary": "absence remains unavailable, never zero load",
        "foreground_boundary": "R-1 does not launch a hardware sampler",
        "measurements": frozenset({
            "cpu_available", "gpu_available", "vram_available",
            "slack_fraction",
        }),
    },
    "external_ingress": {
        "owner": "SensoryOrgan + ResidentEventMailbox",
        "receipt_owner": "owner resource_status snapshots",
        "consumption_event": (
            "admitted sensory crossings and pending Nexus mailbox events are "
            "real interruption/ingress evidence"),
        "restorative_operation": (
            "ordinary transduction/settlement drains the owner's pending work"),
        "operation_absence": None,
        "privacy_boundary": "media, speech, event payloads, and subjects excluded",
        "authority_boundary": "sensory/mailbox owners retain admission authority",
        "foreground_boundary": "status cannot admit, drain, or settle ingress",
        "measurements": frozenset({
            "sensory_modalities", "fresh_sensory_modalities",
            "latest_sensory_age_s", "max_sensory_pressure",
            "mailbox_depth", "mailbox_capacity", "mailbox_load_fraction",
            "low_ingress", "low_interruption_risk",
        }),
    },
}


_FORBIDDEN_KEYS = frozenset({
    "text", "content", "prompt", "reply", "node", "memory", "memory_id",
    "candidate", "candidate_id", "cue_id", "intention_id", "document_id",
    "doc_id", "anchor", "source_id", "event_id", "cycle_id", "run_id",
    "title", "statement", "reason", "rationale", "digest",
})


def _unit(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return max(0.0, min(1.0, number))


def _revision(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _validate_measurements(resource_id: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{resource_id} measurements must be a mapping")
    allowed = RESOURCE_SPECS[resource_id]["measurements"]
    result = {}
    for key, item in value.items():
        key = str(key)
        if key.casefold() in _FORBIDDEN_KEYS or key not in allowed:
            raise ValueError(
                f"{resource_id} measurement is not allowlisted: {key}")
        if item is None or isinstance(item, bool):
            result[key] = item
        elif isinstance(item, (int, float)) and math.isfinite(float(item)):
            result[key] = item
        else:
            raise ValueError(
                f"{resource_id} measurement must be numeric, bool, or null: {key}")
    return dict(sorted(result.items()))


def _normalize_evidence(persona: str, resource_id: str,
                        raw: Mapping[str, Any] | None) -> dict[str, Any]:
    spec = RESOURCE_SPECS[resource_id]
    value = dict(raw or {})
    evidence_persona = str(value.get("persona") or "")
    if evidence_persona and evidence_persona != persona:
        raise ValueError(
            f"cross-persona resource evidence refused for {resource_id}")
    requested = str(value.get("status") or "unavailable")
    if requested not in EVIDENCE_STATES:
        raise ValueError(f"invalid evidence state for {resource_id}")
    freshness = str(value.get("freshness") or "unknown")
    if freshness not in FRESHNESS_CLASSES:
        raise ValueError(f"invalid freshness class for {resource_id}")
    measurements = _validate_measurements(
        resource_id, value.get("measurements") or {})
    absence = sorted({
        str(item)[:160] for item in value.get("absence_reasons") or ()
        if str(item).strip()
    })
    status = requested
    if status == "supported" and not measurements:
        status = "partial"
        absence.append("owner supplied no allowlisted measurement")
    revision_basis = {
        "resource_id": resource_id,
        "persona": persona,
        "status": status,
        "freshness": freshness,
        "evidence_at": value.get("evidence_at"),
        "measurements": measurements,
        "absence_reasons": absence,
    }
    return {
        "resource_id": resource_id,
        "owner": spec["owner"],
        "receipt_owner": spec["receipt_owner"],
        "status": status,
        "freshness": freshness,
        "evidence_at": value.get("evidence_at"),
        "evidence_revision": _revision(revision_basis),
        "measurements": measurements,
        "absence_reasons": absence,
        "consumption_or_occupation_event": spec["consumption_event"],
        "release_renewal_or_reorganization": spec["restorative_operation"],
        "restorative_operation_absence": spec["operation_absence"],
        "boundaries": {
            "privacy": spec["privacy_boundary"],
            "authority": spec["authority_boundary"],
            "foreground_protection": spec["foreground_boundary"],
        },
    }


def _factor(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    measurement = {
        "genuine_unintegrated_load": "load_fraction",
        "low_external_ingress": "low_ingress",
        "low_interruption_risk": "low_interruption_risk",
        "measured_resource_slack": "slack_fraction",
        "private_authority_to_act": "private_authority",
    }[name]
    contributions = []
    for row in rows:
        value = _unit(row["measurements"].get(measurement))
        if (value is not None
                and row["status"] != "unavailable"
                and row["freshness"] in {"live", "history_window"}):
            contributions.append({
                "resource_id": row["resource_id"],
                "value": round(value, 9),
                "status": row["status"],
                "freshness": row["freshness"],
                "evidence_revision": row["evidence_revision"],
            })
    if not contributions:
        return {
            "factor": name, "status": "unavailable", "value": None,
            "contributions": [],
            "absence": f"no fresh owner supplies {measurement}",
        }
    values = [item["value"] for item in contributions]
    if name == "genuine_unintegrated_load":
        combined = 1.0 - math.prod(1.0 - value for value in values)
        formula = "probabilistic_union_of_owner_native_load_fractions"
    elif name == "private_authority_to_act":
        combined = max(values)
        formula = "maximum_real_private_authority_among_reachable_owners"
    else:
        combined = math.prod(values) ** (1.0 / len(values))
        formula = "geometric_mean_with_zero_preserved"
    status = ("supported" if all(
        item["status"] == "supported" for item in contributions)
              else "partial")
    return {
        "factor": name, "status": status, "value": round(combined, 9),
        "formula": formula, "contributions": contributions, "absence": None,
    }


def project_resource_ecology(*, persona: str,
                             evidence: Mapping[str, Mapping[str, Any]],
                             observed_at: Any) -> dict[str, Any]:
    """Return a deterministic R-1 projection over owner-supplied evidence."""
    persona = str(persona or "").strip()
    if not persona or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
                          for char in persona.casefold()):
        raise ValueError("resource ecology requires a bounded persona name")
    unknown = sorted(set(evidence) - set(RESOURCE_SPECS))
    if unknown:
        raise ValueError("unknown resource evidence: " + ", ".join(unknown))
    rows = [_normalize_evidence(
        persona, resource_id, evidence.get(resource_id))
        for resource_id in RESOURCE_SPECS]
    factors = [_factor(name, rows) for name in FACTOR_NAMES]
    complete = all(item["value"] is not None for item in factors)
    if complete:
        affordance = math.prod(item["value"] for item in factors) ** 0.2
        affordance = round(affordance, 9)
        status = ("supported" if all(
            item["status"] == "supported" for item in factors)
                  else "partial")
    else:
        affordance = None
        status = ("partial" if any(
            item["value"] is not None for item in factors)
                  else "unavailable")
    result = {
        "schema_version": SCHEMA_VERSION,
        "stage": "R-1",
        "persona": persona,
        "observed_at": observed_at,
        "mode": "observe_only",
        "content_free": True,
        "read_only": True,
        "actions_created": 0,
        "model_calls": 0,
        "state_writes": 0,
        "downstream_channels_touched": [],
        "resources": rows,
        "assimilation_affordance": {
            "status": status,
            "value": affordance,
            "formula": (
                "five_factor_geometric_mean_with_zero_preserved; unavailable "
                "when any factor is absent"),
            "factors": factors,
            "excludes": [
                "clock_time", "night", "recovery_debt",
                "biological_sleep_labels",
            ],
            "behavior_authority": False,
        },
    }
    result["projection_revision"] = _revision(result)
    return result


def unavailable_evidence(persona: str, reason: str) -> dict[str, Any]:
    """Build an explicit all-unavailable input without fabricated zeros."""
    return {
        resource_id: {
            "persona": persona, "status": "unavailable",
            "freshness": "unknown", "measurements": {},
            "absence_reasons": [reason],
        }
        for resource_id in RESOURCE_SPECS
    }


__all__ = [
    "FACTOR_NAMES", "RESOURCE_SPECS", "SCHEMA_VERSION",
    "project_resource_ecology", "unavailable_evidence",
]
