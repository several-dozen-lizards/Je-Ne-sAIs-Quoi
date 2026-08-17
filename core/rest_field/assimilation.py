"""Pure R1 quiet-assimilation reachability projection.

Reachability is an observation over existing owner facts.  It does not create
work, reserve capacity, advance RestField, or execute maintenance.  Biological
rest language grants no authority here: one genuine derived-index load is
reachable only when every owner gate is present and the current RestField
relationship increases reachability above exact bypass.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping


OPERATOR_ID = "memory_vector_missing_row_repair_v1"
RESOURCE_ID = "memory_derived_indexes"
def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _unit(value: Any) -> float | None:
    number = _finite(value)
    return None if number is None else max(0.0, min(1.0, number))


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 9)


def _revision(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("ascii")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _logit_bend(baseline: float, centered_signal: float,
                limit: float) -> float:
    baseline = max(0.0, min(1.0, float(baseline)))
    if baseline in {0.0, 1.0}:
        return baseline
    shift = max(-limit, min(limit, centered_signal * limit))
    logit = math.log(baseline / (1.0 - baseline))
    return 1.0 / (1.0 + math.exp(-(logit + shift)))


def _field_signal(dimensions: Mapping[str, Any],
                  drivers: Mapping[str, Any]) -> float | None:
    admitted = []
    for name, raw_weight in sorted(drivers.items()):
        value = _unit(dimensions.get(name))
        weight = _finite(raw_weight)
        if value is None or weight is None:
            return None
        admitted.append(((value - 0.5) * 2.0 * weight, abs(weight)))
    norm = sum(weight for _value, weight in admitted)
    return (sum(value for value, _weight in admitted) / norm
            if admitted and norm > 0.0 else None)


def _mismatched_dimensions(dimensions: Mapping[str, Any],
                           drivers: Mapping[str, Any]) -> dict[str, float]:
    names = sorted(drivers)
    values = [_unit(dimensions.get(name)) for name in names]
    if not names or any(value is None for value in values):
        return {}
    rotated = values[1:] + values[:1]
    return {name: float(value) for name, value in zip(names, rotated)}


def project_quiet_assimilation(
        *, persona: str, memory_status: Mapping[str, Any],
        quiet_status: Mapping[str, Any], controller_status: Mapping[str, Any],
        lease_status: Mapping[str, Any], ingress_status: Mapping[str, Any],
        rest_status: Mapping[str, Any], foreground_epoch: int) -> dict[str, Any]:
    """Project one R-1-selected operation through four observe-only arms."""
    persona = str(persona or "").strip()
    if not persona:
        raise ValueError("quiet assimilation requires a persona")
    memory = dict(memory_status or {})
    quiet = dict(quiet_status or {})
    controller = dict(controller_status or {})
    leases = dict(lease_status or {})
    ingress = dict(ingress_status or {})
    rest = dict(rest_status or {})

    canonical = memory.get("canonical_records")
    covered = memory.get("vector_covered")
    rows = memory.get("vector_rows")
    gap = memory.get("vector_gap")
    if not isinstance(gap, int):
        gap = (max(0, int(canonical) - int(covered))
               if isinstance(canonical, int) and isinstance(covered, int)
               else None)
    context_complete = bool(
        isinstance(canonical, int)
        and memory.get("context_index_records") == canonical)
    revision_stable = bool(
        isinstance(memory.get("memory_revision"), int)
        and memory.get("memory_revision") == memory.get("persisted_revision"))
    vector_pending_clear = memory.get("vector_pending") == 0
    vector_healthy = memory.get("vector_healthy") is True

    quiet_epoch = quiet.get("foreground_epoch")
    quiet_committed = bool(
        quiet.get("active") is True
        and quiet.get("committed") is True
        and quiet.get("quiet_compatible_maintenance") == 1.0
        and isinstance(quiet_epoch, int)
        and quiet_epoch == int(foreground_epoch))
    active = controller.get("active")
    controller_open = bool(
        controller.get("controller_open") is True
        and not active and not controller.get("replacement_pending"))
    state_available = leases.get("state_available_to_consumer")
    private_authority = memory.get("private_authority")
    low_ingress = _unit(ingress.get("low_ingress"))
    low_interruption = _unit(ingress.get("low_interruption_risk"))

    gates = [
        ("genuine_vector_gap", bool(isinstance(gap, int) and gap > 0),
         None if isinstance(gap, int) else "vector_gap_unavailable"),
        ("canonical_revision_stable", revision_stable, None),
        ("context_index_complete", context_complete, None),
        ("vector_pending_clear", vector_pending_clear, None),
        ("local_vector_model_healthy", vector_healthy, None),
        ("quiet_committed_same_epoch", quiet_committed, None),
        ("maintenance_controller_open", controller_open, None),
        ("state_lease_available", state_available is True,
         None if isinstance(state_available, bool)
         else "state_lease_evidence_unavailable"),
        ("resident_private_authority", private_authority == 1.0,
         None if private_authority is not None
         else "private_authority_unavailable"),
        ("low_external_ingress_available", low_ingress is not None,
         None if low_ingress is not None else "low_ingress_unavailable"),
        ("low_interruption_risk_available", low_interruption is not None,
         None if low_interruption is not None
         else "low_interruption_risk_unavailable"),
    ]
    rendered_gates = [{
        "name": name,
        "passed": bool(passed),
        "absence": absence if absence else None,
    } for name, passed, absence in gates]
    hard_gates_passed = all(row["passed"] for row in rendered_gates)

    # The load leg is the owner's measured uncovered fraction, not a synthetic
    # yes/no fatigue value.  Keeping it continuous also prevents a fully quiet,
    # fully open boundary from pinning the logit baseline at 1.0, where no
    # candidate relationship could be distinguished from exact bypass.
    load_fraction = (
        max(0.0, min(1.0, float(gap) / float(canonical)))
        if isinstance(gap, int) and isinstance(canonical, int)
        and gap > 0 and canonical > 0 else 0.0)
    base_factors = [
        load_fraction,
        low_ingress,
        low_interruption,
        1.0 if controller_open else 0.0,
        1.0 if state_available is True else 0.0,
        1.0 if quiet_committed else 0.0,
    ]
    base = (math.prod(float(value) for value in base_factors)
            ** (1.0 / len(base_factors))
            if all(value is not None for value in base_factors) else None)

    dimensions = dict(rest.get("dimensions") or {})
    drivers = dict(rest.get("drivers") or {})
    limit = _finite(rest.get("max_abs_logit_shift"))
    rest_authorized = bool(
        rest.get("authorized") is True and drivers and limit is not None)
    actual_signal = _field_signal(dimensions, drivers) \
        if rest_authorized else None
    sham_dimensions = {name: 0.5 for name in drivers}
    sham_signal = _field_signal(sham_dimensions, drivers) \
        if rest_authorized else None
    mismatched_dimensions = _mismatched_dimensions(dimensions, drivers)
    mismatch_signal = _field_signal(mismatched_dimensions, drivers) \
        if rest_authorized and mismatched_dimensions else None

    def arm(name: str, signal: float | None, *, exact_bypass=False):
        if base is None:
            value = None
        elif exact_bypass:
            value = base
        elif signal is None or limit is None:
            value = None
        else:
            value = _logit_bend(base, signal, max(0.0, limit))
        return {
            "arm": name,
            "value": _rounded(value),
            "centered_field_signal": (
                0.0 if exact_bypass else _rounded(signal)),
            "field_applied": bool(not exact_bypass and signal is not None),
        }

    arms = {
        "actual": arm("actual", actual_signal),
        "bypass": arm("bypass", 0.0, exact_bypass=True),
        "sham_centered_field": arm("sham_centered_field", sham_signal),
        "candidate_mismatched_field": arm(
            "candidate_mismatched_field", mismatch_signal),
    }
    actual = arms["actual"]["value"]
    bypass = arms["bypass"]["value"]
    field_opens = bool(
        actual is not None and bypass is not None and actual > bypass)
    reachable = bool(hard_gates_passed and rest_authorized and field_opens)
    reasons = [row["name"] for row in rendered_gates if not row["passed"]]
    if not rest_authorized:
        reasons.append("rest_reachability_projection_unauthorized")
    elif not field_opens:
        reasons.append("rest_field_does_not_open_reachability_above_bypass")

    candidate = {
        "operator_id": OPERATOR_ID,
        "resource_id": RESOURCE_ID,
        "truth": "supported" if isinstance(gap, int) else "unavailable",
        "canonical_records": canonical,
        "vector_covered": covered,
        "vector_rows": rows,
        "vector_gap": gap,
        "load_fraction": _rounded(load_fraction),
        "load_present": bool(isinstance(gap, int) and gap > 0),
        "gates": rendered_gates,
        "base_reachability": _rounded(base),
        "arms": arms,
        "actual_minus_bypass": (
            _rounded(actual - bypass)
            if actual is not None and bypass is not None else None),
        "reachable": reachable,
        "blocked_reasons": reasons,
        "private": True,
        "external_effects": False,
        "canonical_memory_mutation_authorized": False,
        "content_free": True,
    }
    revision_basis = {
        "persona": persona,
        "operator_id": OPERATOR_ID,
        "candidate": candidate,
        "rest_config_hash": rest.get("config_hash"),
        "quiet_transition_digest": quiet.get("transition_digest"),
        "foreground_epoch": int(foreground_epoch),
    }
    return {
        "schema_version": 1,
        "stage": "R1",
        "kind": "quiet_assimilation_reachability",
        "persona": persona,
        "candidate_count": 1,
        "reachable_count": int(reachable),
        "candidates": [candidate],
        "projection_revision": _revision(revision_basis),
        "mode": "observe_only",
        "read_only": True,
        "state_writes": 0,
        "model_calls": 0,
        "actions_created": 0,
        "downstream_channels_touched": [],
        "behavior_authority": False,
        "content_free": True,
    }


__all__ = [
    "OPERATOR_ID", "RESOURCE_ID", "project_quiet_assimilation",
]
