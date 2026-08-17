"""Validation for reversible, content-free rest-field experiments."""
from __future__ import annotations

import math
from typing import Any, Mapping

from .organ import DIMENSIONS, canonical_config_hash
from .sources import calibration_source_specs


REQUIRED_CONTROLS = frozenset({
    "disabled",
    "source_ablated",
    "mismatched_measurements",
    "source_label_permuted",
    "interval_order_permuted",
    "synthetic_boundaries",
})

# A frozen manifest may conduct only through these private, reversible internal
# competition seams. Adding a method to RestRuntime does not grant authority;
# this allowlist and the manifest must both name it.
BOUNDED_CONDUCT_JUNCTIONS = {
    "consolidation_salience": frozenset({
        "recovery_debt", "maintenance_affordance", "trace_retention"}),
    "associative_recombination_salience": frozenset({
        "associative_mobility"}),
    "maintenance_candidate_salience": frozenset({
        "recovery_debt", "maintenance_affordance"}),
}
BOUNDED_CONTEXT_DRIVERS = {
    "maintenance_candidate_salience": frozenset({
        "readiness", "capacity", "resource_availability"}),
}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate_manifest(manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate an experiment without loading it into a resident runtime."""
    value = dict(manifest or {})
    errors, warnings = [], []
    if int(value.get("schema_version") or 0) != 1:
        errors.append("schema_version_must_be_1")
    experiment_id = str(value.get("experiment_id") or "").strip()
    if not experiment_id:
        errors.append("experiment_id_required")
    status = str(value.get("status") or "draft")
    if status not in {"draft", "frozen"}:
        errors.append("status_must_be_draft_or_frozen")
    cutoff = _finite(value.get("discovery_cutoff_at"))
    if status == "frozen" and cutoff is None:
        errors.append("frozen_manifest_requires_discovery_cutoff_at")
    phase = str(value.get("phase") or "shadow")
    if phase not in {"shadow", "bounded_conduct"}:
        errors.append("phase_must_be_shadow_or_bounded_conduct")

    candidate = dict(value.get("candidate") or {})
    sources = dict(candidate.get("sources") or {})
    expected = calibration_source_specs()
    if set(sources) != set(expected):
        errors.append("candidate_must_declare_all_calibration_sources")
    active_weights = 0
    for source, expected_spec in expected.items():
        spec = dict(sources.get(source) or {})
        baselines = dict(spec.get("baselines") or {})
        if set(baselines) != set(expected_spec["baselines"]):
            errors.append(f"{source}:baseline_metric_set_mismatch")
        for metric, raw in baselines.items():
            number = _finite(raw)
            if number is None or not 0.0 <= number <= 1.0:
                errors.append(f"{source}:{metric}:baseline_out_of_range")
        calibration = dict(spec.get("calibration") or {})
        for metric, raw_range in calibration.items():
            if metric not in baselines:
                errors.append(f"{source}:{metric}:unknown_calibration_metric")
                continue
            range_spec = dict(raw_range or {})
            low = _finite(range_spec.get("low"))
            middle = _finite(range_spec.get("middle"))
            high = _finite(range_spec.get("high"))
            if (low is None or middle is None or high is None
                    or not 0.0 <= low <= middle <= high <= 1.0
                    or low == high):
                errors.append(f"{source}:{metric}:invalid_calibration_range")
        for dimension, raw_row in dict(spec.get("weights") or {}).items():
            if dimension not in DIMENSIONS:
                errors.append(f"{source}:{dimension}:unknown_dimension")
                continue
            for metric, raw_weight in dict(raw_row or {}).items():
                if metric not in baselines:
                    errors.append(f"{source}:{dimension}:{metric}:unknown_metric")
                    continue
                weight = _finite(raw_weight)
                if weight is None or not -1.0 <= weight <= 1.0:
                    errors.append(
                        f"{source}:{dimension}:{metric}:weight_out_of_range")
                elif weight != 0.0:
                    active_weights += 1
    if not active_weights:
        errors.append("candidate_requires_at_least_one_nonzero_weight")

    dynamics = dict(candidate.get("dynamics") or {})
    if set(dynamics) != set(DIMENSIONS):
        errors.append("candidate_requires_dynamics_for_every_dimension")
    for dimension in DIMENSIONS:
        spec = dict(dynamics.get(dimension) or {})
        period = _finite(spec.get("period_s"))
        damping = _finite(spec.get("damping_ratio"))
        if period is None or period <= 0.0:
            errors.append(f"{dimension}:period_s_must_be_positive")
        if damping is None or not 0.0 <= damping < 1.0:
            errors.append(f"{dimension}:damping_ratio_out_of_range")

    controls = {str(item) for item in list(value.get("controls") or ())}
    missing_controls = sorted(REQUIRED_CONTROLS - controls)
    if missing_controls:
        errors.append("missing_required_controls:" + ",".join(missing_controls))
    junctions = dict(value.get("junctions") or {})
    conduct_junctions = sorted(
        name for name, mode in junctions.items() if str(mode) == "conduct")
    conduct_authorized = False
    if conduct_junctions or value.get("allow_conduct") is True:
        if phase != "bounded_conduct":
            errors.append("conduct_requires_bounded_conduct_phase")
        unknown_conduct = sorted(
            set(conduct_junctions) - set(BOUNDED_CONDUCT_JUNCTIONS))
        if unknown_conduct:
            errors.append(
                "conduct_scope_contains_unapproved_junctions:"
                + ",".join(unknown_conduct))
        if value.get("allow_conduct") is not True:
            errors.append("bounded_conduct_requires_explicit_allow_conduct")
        if str(value.get("rollback_mode") or "") != "bypass":
            errors.append("bounded_conduct_requires_bypass_rollback")
        driver_profiles = dict(value.get("junction_drivers") or {})
        context_profiles = dict(value.get("junction_context_weights") or {})
        limit_profiles = dict(value.get("conduct_limits") or {})
        for junction in conduct_junctions:
            drivers = dict(driver_profiles.get(junction) or {})
            allowed_dimensions = BOUNDED_CONDUCT_JUNCTIONS.get(
                junction, frozenset())
            if (not drivers or any(
                    dimension not in allowed_dimensions
                    or _finite(weight) is None
                    for dimension, weight in drivers.items())
                    or sum(abs(float(weight))
                           for weight in drivers.values()) <= 0.0):
                errors.append(
                    f"{junction}:bounded_conduct_requires_explicit_drivers")
            context = dict(context_profiles.get(junction) or {})
            allowed_context = BOUNDED_CONTEXT_DRIVERS.get(
                junction, frozenset())
            if allowed_context:
                if (set(context) != set(allowed_context)
                        or any(_finite(weight) is None
                               for weight in context.values())
                        or sum(abs(float(weight))
                               for weight in context.values()) <= 0.0):
                    errors.append(
                        f"{junction}:bounded_conduct_requires_context_drivers")
            elif context:
                errors.append(
                    f"{junction}:context_drivers_not_allowed")
            limit = _finite(limit_profiles.get(junction))
            if limit is None or not 0.0 < limit <= 1.0:
                errors.append(
                    f"{junction}:bounded_conduct_limit_must_be_in_0_1")
        conduct_authorized = not errors
    if status == "draft":
        warnings.append("draft_manifest_must_be_frozen_before_confirmation")

    canonical_candidate = {
        "sources": sources,
        "dynamics": dynamics,
    }
    return {
        "schema_version": 1,
        "kind": "rest_experiment_manifest_validation",
        "experiment_id": experiment_id,
        "status": status,
        "phase": phase,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "active_weight_count": active_weights,
        "required_controls": sorted(REQUIRED_CONTROLS),
        "declared_controls": sorted(controls),
        "candidate_hash": canonical_config_hash(canonical_candidate),
        "discovery_cutoff_at": cutoff,
        "conduct_authorized": conduct_authorized,
        "authorized_conduct_junctions": (
            conduct_junctions if conduct_authorized else []),
        "content_free": True,
    }


def validate_runtime_authorization(
        config: Mapping[str, Any] | None,
        manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    """Bind one live runtime to the exact frozen candidate and junctions."""
    runtime = dict(config or {})
    frozen = dict(manifest or {})
    validation = validate_manifest(frozen)
    errors = []
    if not validation.get("conduct_authorized"):
        errors.append("manifest_does_not_authorize_conduct")
    runtime_experiment = str(runtime.get("experiment_id") or "")
    if runtime_experiment != str(frozen.get("experiment_id") or ""):
        errors.append("experiment_id_mismatch")

    sources = calibration_source_specs()
    for name, value in dict(runtime.get("sources") or {}).items():
        if name not in sources:
            errors.append(f"runtime_unknown_source:{name}")
            continue
        override = dict(value or {})
        base = dict(sources[name])
        base["baselines"] = {
            **dict(base.get("baselines") or {}),
            **dict(override.pop("baselines", {}) or {}),
        }
        base.update(override)
        sources[name] = base
    runtime_candidate_hash = canonical_config_hash({
        "sources": sources,
        "dynamics": dict(runtime.get("dynamics") or {}),
    })
    if runtime_candidate_hash != validation.get("candidate_hash"):
        errors.append("candidate_profile_mismatch")

    profile_keys = (
        "junctions", "junction_drivers", "junction_context_weights",
        "conduct_limits", "allow_conduct", "rollback_mode")
    runtime_profile_hash = canonical_config_hash({
        key: runtime.get(key) for key in profile_keys})
    manifest_profile_hash = canonical_config_hash({
        key: frozen.get(key) for key in profile_keys})
    if runtime_profile_hash != manifest_profile_hash:
        errors.append("junction_profile_mismatch")
    authorized = bool(
        runtime.get("mode") == "live"
        and runtime.get("allow_conduct") is True
        and not errors)
    return {
        "schema_version": 1,
        "experiment_id": runtime_experiment,
        "manifest_experiment_id": str(frozen.get("experiment_id") or ""),
        "authorized": authorized,
        "errors": errors,
        "candidate_hash": runtime_candidate_hash,
        "manifest_candidate_hash": validation.get("candidate_hash"),
        "junction_profile_hash": runtime_profile_hash,
        "manifest_junction_profile_hash": manifest_profile_hash,
        "content_free": True,
    }
