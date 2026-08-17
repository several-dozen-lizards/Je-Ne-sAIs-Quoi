"""Stage-1 calibration and shadow runtime for the synthetic rest field."""
from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import deque
from typing import Any, Mapping

from .organ import (
    DIMENSIONS, JunctionRegistry, RestField, RestObserver, RestSourceRegistry,
)
from .sources import calibration_source_specs


RUNTIME_MODES = frozenset({"disabled", "calibration", "shadow", "live"})
PROCESS_RECOMBINATION_PROBE_MODE = "controlled_private_prompt_probe"
TRACE_RECURRENCE_OBSERVER_MODE = "observe"
MAINTENANCE_CONTEXT_DIMENSIONS = frozenset({
    "readiness", "capacity", "resource_availability",
})


class RestRuntime:
    """Own source receipts now; permit no downstream conduct in Stage 1."""

    def __init__(self, persona_dir: str, *,
                 config: Mapping[str, Any] | None = None,
                 clock=time.time):
        self.persona_dir = os.path.abspath(os.fspath(persona_dir))
        self.config = dict(config or {})
        self.manifest_authorization = dict(
            self.config.get("_manifest_authorization") or {})
        self.experiment_id = str(
            self.config.get("experiment_id") or "")[:96]
        self.mode = str(self.config.get("mode") or "disabled")
        if self.mode not in RUNTIME_MODES:
            raise ValueError(f"unknown Stage-1 rest runtime mode: {self.mode}")
        probe = dict(self.config.get("process_recombination_probe") or {})
        probe_enabled = bool(probe.get("enabled", False))
        probe_mode = str(probe.get("mode") or "disabled")
        probe_experiment_id = str(probe.get("experiment_id") or "")[:96]
        probe_rollback_mode = str(
            probe.get("rollback_mode") or "disabled")
        probe_ownership = str(probe.get("ownership") or "persona_private")
        if probe_enabled:
            if self.mode != "live":
                raise ValueError(
                    "process recombination probe requires live rest runtime")
            if probe_mode != PROCESS_RECOMBINATION_PROBE_MODE:
                raise ValueError(
                    "unknown process recombination probe mode")
            if not probe_experiment_id:
                raise ValueError(
                    "process recombination probe requires experiment_id")
            if probe_rollback_mode != "disabled":
                raise ValueError(
                    "process recombination probe rollback must be disabled")
            if probe_ownership != "persona_private":
                raise ValueError(
                    "process recombination probe must remain persona_private")
        self.process_recombination_probe = {
            "schema_version": 1,
            "enabled": probe_enabled,
            "mode": probe_mode,
            "experiment_id": probe_experiment_id,
            "rollback_mode": probe_rollback_mode,
            "ownership": probe_ownership,
            "authorized": bool(
                probe_enabled
                and self.mode == "live"
                and probe_mode == PROCESS_RECOMBINATION_PROBE_MODE),
        }
        recurrence = dict(
            self.config.get("trace_recurrence_observer") or {})
        recurrence_enabled = bool(recurrence.get("enabled", False))
        recurrence_mode = str(recurrence.get("mode") or "disabled")
        recurrence_experiment_id = str(
            recurrence.get("experiment_id") or "")[:96]
        recurrence_rollback = str(
            recurrence.get("rollback_mode") or "disabled")
        recurrence_ownership = str(
            recurrence.get("ownership") or "persona_private")
        recurrence_source = dict(recurrence.get("source") or {})
        self.trace_recurrence_sources = None
        if recurrence_enabled:
            if not self.process_recombination_probe.get("authorized"):
                raise ValueError(
                    "trace recurrence observer requires authorized P1 probe")
            if recurrence_mode != TRACE_RECURRENCE_OBSERVER_MODE:
                raise ValueError(
                    "trace recurrence observer must remain observe-only")
            if not recurrence_experiment_id:
                raise ValueError(
                    "trace recurrence observer requires experiment_id")
            if recurrence_rollback != "disabled":
                raise ValueError(
                    "trace recurrence observer rollback must be disabled")
            if recurrence_ownership != "persona_private":
                raise ValueError(
                    "trace recurrence observer must remain persona_private")
            if str(recurrence_source.get("kind") or "") != "derived":
                raise ValueError(
                    "trace recurrence source must be derived")
            if set(dict(recurrence_source.get("baselines") or {})) != {
                    "recurrence_propensity", "durable_consequence"}:
                raise ValueError(
                    "trace recurrence source requires exact metrics")
            recurrence_weights = dict(
                recurrence_source.get("weights") or {})
            expected_recurrence_weights = {
                "associative_mobility": {"recurrence_propensity"},
                "trace_retention": {"durable_consequence"},
            }
            if (set(recurrence_weights) != set(
                    expected_recurrence_weights)
                    or any(set(dict(recurrence_weights.get(name) or {}))
                           != metrics for name, metrics in
                           expected_recurrence_weights.items())
                    or any(not math.isfinite(float(weight))
                           or not 0.0 < abs(float(weight)) <= 1.0
                           for row in recurrence_weights.values()
                           for weight in dict(row or {}).values())):
                raise ValueError(
                    "trace recurrence source has unbounded dimensions")
            self.trace_recurrence_sources = RestSourceRegistry({
                "trace_recurrence": recurrence_source})
        self.trace_recurrence_observer = {
            "schema_version": 1,
            "enabled": recurrence_enabled,
            "mode": recurrence_mode,
            "experiment_id": recurrence_experiment_id,
            "rollback_mode": recurrence_rollback,
            "ownership": recurrence_ownership,
            "authorized": bool(
                recurrence_enabled
                and recurrence_mode == TRACE_RECURRENCE_OBSERVER_MODE
                and self.process_recombination_probe.get("authorized")),
            "source_config_hash": (
                self.trace_recurrence_sources.config_hash
                if self.trace_recurrence_sources is not None else None),
            "field_influence": False,
        }
        self.clock = clock
        self._lock = threading.RLock()
        self._last_event_refs = set()
        self._event_ref_order = deque()
        self._observed_ranges: dict[str, dict[str, dict[str, float]]] = {}
        specs = calibration_source_specs()
        configured_specs = dict(self.config.get("sources") or {})
        for name, value in configured_specs.items():
            if name not in specs:
                raise ValueError(f"unknown configured rest source: {name}")
            override = dict(value or {})
            base = dict(specs[name])
            base["baselines"] = {
                **dict(base.get("baselines") or {}),
                **dict(override.pop("baselines", {}) or {}),
            }
            base.update(override)
            specs[name] = base
        if self.mode in {"shadow", "live"} and not any(
                dict(spec.get("weights") or {}) for spec in specs.values()):
            raise ValueError(
                "enabled rest runtime requires explicit source weights")
        self.sources = RestSourceRegistry(specs)
        field_config = {
            "mode": self.mode if self.mode in {"shadow", "live"}
            else "disabled",
        }
        if self.mode in {"shadow", "live"}:
            field_config["dynamics"] = dict(
                self.config.get("dynamics") or {})
        self.field = RestField(
            self.persona_dir, config=field_config, clock=clock)
        self.junctions = JunctionRegistry(
            global_mode=(self.mode if self.mode in {"shadow", "live"}
                         else "disabled"),
            junctions=dict(self.config.get("junctions") or {}),
            allow_conduct=bool(
                self.mode == "live" and self.config.get("allow_conduct")))
        self.junction_drivers = {
            str(junction): {
                str(dimension): float(weight)
                for dimension, weight in dict(raw or {}).items()}
            for junction, raw in dict(
                self.config.get("junction_drivers") or {}).items()}
        self.junction_context_weights = {
            str(junction): {
                str(dimension): float(weight)
                for dimension, weight in dict(raw or {}).items()}
            for junction, raw in dict(
                self.config.get("junction_context_weights") or {}).items()}
        self.conduct_limits = {
            str(junction): float(value)
            for junction, value in dict(
                self.config.get("conduct_limits") or {}).items()}
        for junction, requested in self.junctions.junctions.items():
            if requested != "conduct":
                continue
            drivers = self.junction_drivers.get(junction, {})
            if not drivers or any(
                    dimension not in DIMENSIONS or not math.isfinite(weight)
                    for dimension, weight in drivers.items()):
                raise ValueError(
                    f"conduct junction {junction} requires explicit drivers")
            if sum(abs(weight) for weight in drivers.values()) <= 0.0:
                raise ValueError(
                    f"conduct junction {junction} driver norm must be positive")
            context_weights = self.junction_context_weights.get(junction, {})
            if any(name not in MAINTENANCE_CONTEXT_DIMENSIONS
                   or not math.isfinite(weight)
                   for name, weight in context_weights.items()):
                raise ValueError(
                    f"conduct junction {junction} has invalid context drivers")
            limit = self.conduct_limits.get(junction)
            if limit is None or not math.isfinite(limit) or limit <= 0.0:
                raise ValueError(
                    f"conduct junction {junction} requires a positive limit")
        self.observer = RestObserver(self.persona_dir)
        self.source_receipts_path = os.path.join(
            self.persona_dir, "history", "rest_source_receipts.jsonl")
        self.conduct_receipts_path = os.path.join(
            self.persona_dir, "history", "rest_conduct_receipts.jsonl")
        self.trace_recurrence_projection_path = os.path.join(
            self.persona_dir, "history",
            "rest_trace_recurrence_projections.jsonl")
        self._projected_source_revisions = set()
        self._restore_conduct_recurrence()
        self._trace_recurrence_events = set()
        self._restore_trace_recurrence_events()
        self.receipt_count = 0
        self.conduct_receipt_count = 0
        self.applied_count = 0
        self.last_conduct_receipt = None
        self.trace_recurrence_projection_count = 0

    def _range_snapshot(self, source: str,
                        measurements: Mapping[str, Any]) -> dict:
        ranges = self._observed_ranges.setdefault(source, {})
        for name, raw in dict(measurements or {}).items():
            value = float(raw)
            row = ranges.setdefault(str(name), {"min": value, "max": value})
            row["min"] = min(row["min"], value)
            row["max"] = max(row["max"], value)
        return {
            name: {"min": round(row["min"], 9),
                   "max": round(row["max"], 9)}
            for name, row in sorted(ranges.items())}

    def _influence_receipt(self, aggregate: Mapping[str, Any], *,
                           source_available: bool) -> dict:
        active = list(aggregate.get("active_dimensions") or ())
        candidate_defined = bool(active)
        junctions = []
        for name in sorted(self.junctions.junctions):
            requested = self.junctions.junctions[name]
            effective = self.junctions.effective_mode(name)
            junctions.append({
                "junction": name,
                "requested_mode": requested,
                "effective_mode": effective,
                "applied": False,
            })
        conduct_possible = bool(
            candidate_defined and self.junctions.allow_conduct
            and any(item["effective_mode"] == "conduct" for item in junctions))
        reasons = []
        if not candidate_defined:
            reasons.append("candidate_undefined")
        if self.mode == "calibration":
            reasons.append("runtime_calibration")
        if not self.junctions.allow_conduct:
            reasons.append("conduct_disarmed")
        if not junctions:
            reasons.append("no_junctions_defined")
        elif not any(item["effective_mode"] == "conduct" for item in junctions):
            reasons.append("all_junctions_bypass_or_observe")
        quiet_class = (
            "source_absent" if not source_available
            else "source_present_no_candidate" if not candidate_defined
            else "candidate_present_blocked" if not conduct_possible
            else "candidate_available_conduct_path_untouched")
        return {
            "schema_version": 1,
            "candidate_defined": candidate_defined,
            "candidate_dimensions": active,
            "conduct_possible": conduct_possible,
            "could_have_conducted": conduct_possible,
            "conducted": False,
            "blocked": candidate_defined and not conduct_possible,
            "blocked_reasons": reasons,
            "quiet_classification": quiet_class,
            "junctions": junctions,
            "downstream_channels_touched": [],
            "content_free": True,
        }

    def _append_source_receipt(self, row: Mapping[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.source_receipts_path), exist_ok=True)
        with open(self.source_receipts_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                dict(row), ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _append_conduct_receipt(self, row: Mapping[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.conduct_receipts_path), exist_ok=True)
        with open(self.conduct_receipts_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                dict(row), ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _source_revision_ref(row: Mapping[str, Any]) -> str:
        explicit = str(row.get("source_revision_ref") or "")[:160]
        if explicit:
            return explicit
        legacy = str(row.get("event_ref") or "")[:160]
        prefix = "rest-consolidation-salience:"
        if legacy.startswith(prefix):
            return "rest-consolidation:" + legacy[len(prefix):]
        return ""

    def _restore_conduct_recurrence(self, maximum_bytes: int = 2_000_000):
        """Restore exact source-revision recurrence without loading content."""
        try:
            with open(self.conduct_receipts_path, "rb") as handle:
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
                if (not isinstance(row, dict)
                        or row.get("content_free") is not True
                        or not row.get("junction")):
                    continue
                # A gate-blocked opportunity was deliberately not reserved in
                # memory and must remain eligible after restart. Its receipt
                # is historical truth, not evidence that conduct occurred.
                if row.get("blocked") is True \
                        or row.get("effective_mode") == "gated_bypass":
                    continue
                source_ref = self._source_revision_ref(row)
                if source_ref:
                    self._projected_source_revisions.add((
                        str(row.get("junction")), source_ref))
        except OSError:
            return

    def _restore_trace_recurrence_events(
            self, maximum_bytes: int = 2_000_000):
        try:
            with open(self.trace_recurrence_projection_path, "rb") as handle:
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
                event_ref = str(row.get("event_ref") or "")
                if (row.get("kind") == "rest_trace_recurrence_projection"
                        and event_ref):
                    self._trace_recurrence_events.add(event_ref)
        except OSError:
            return

    def _commit_conduct_receipt(self, row: Mapping[str, Any]) -> dict:
        row = dict(row)
        if self.mode != "disabled":
            self._append_conduct_receipt(row)
            self.conduct_receipt_count += 1
            if row.get("applied"):
                self.applied_count += 1
            self.last_conduct_receipt = row
        return row

    def _route_bounded_probability(
            self, junction: str, baseline: float, *,
            downstream_channel: str, at: float | None = None,
            event_ref: str = "",
            source_revision_ref: str = "",
            work_revision: str = "",
            context_values: Mapping[str, Any] | None = None,
            blocked_reasons=()) -> tuple[float, dict]:
        """Route one bounded probability without compounding source recurrence."""
        now = float(self.clock() if at is None else at)
        baseline_value = max(0.0, min(1.0, float(baseline)))
        junction = str(junction)[:96]
        event_ref = str(event_ref or "")[:160]
        source_revision_ref = str(source_revision_ref or "")[:160]
        work_revision = str(work_revision or "")[:160]
        context_weights = dict(
            self.junction_context_weights.get(junction) or {})
        bounded_context = {}
        for name in context_weights:
            try:
                value = float(dict(context_values or {}).get(name, 0.5))
            except (TypeError, ValueError):
                value = 0.5
            bounded_context[name] = max(0.0, min(1.0, value)) \
                if math.isfinite(value) else 0.5
        blocked_reasons = sorted({
            str(reason)[:96] for reason in (blocked_reasons or ())
            if str(reason or "").strip()})
        recurrence_key = (junction, source_revision_ref)
        with self._lock:
            repeated_source = bool(
                source_revision_ref
                and recurrence_key in self._projected_source_revisions)
            if source_revision_ref and not repeated_source \
                    and not blocked_reasons:
                # Reserve this exact evidence revision before projection so two
                # simultaneous substrate opportunities cannot both conduct.
                self._projected_source_revisions.add(recurrence_key)
        drivers = dict(self.junction_drivers.get(junction) or {})
        field = self.field.peek(now)
        dimensions = dict(field.get("dimensions") or {})
        configured_mode = self.junctions.effective_mode(junction)
        if blocked_reasons:
            conduct_possible = bool(
                configured_mode == "conduct" and drivers
                and self.junctions.allow_conduct)
            row = self._commit_conduct_receipt({
                "schema_version": 1,
                "kind": "rest_junction_projection",
                "experiment_id": self.experiment_id,
                "at": now,
                "event_ref": event_ref,
                "source_revision_ref": source_revision_ref,
                "work_revision": work_revision,
                "junction": junction,
                "runtime_mode": self.mode,
                "field_config_hash": field.get("config_hash"),
                "junction_profile_hash": self.junctions.snapshot().get(
                    "junction_profile_hash"),
                "requested_mode": self.junctions.junctions.get(
                    junction, "bypass"),
                "configured_effective_mode": configured_mode,
                "effective_mode": "gated_bypass",
                "recurrence_kind": "opportunity_blocked_before_projection",
                "source_evidence_changed": True,
                "could_have_conducted": conduct_possible,
                "conducted": False,
                "blocked": True,
                "blocked_reasons": blocked_reasons,
                "quiet_classification": "candidate_present_gate_blocked",
                "driver_dimensions": {
                    name: round(float(weight), 9)
                    for name, weight in sorted(drivers.items())},
                "dimension_values": {
                    name: round(float(dimensions.get(name, 0.5)), 9)
                    for name in sorted(drivers)},
                "context_weights": {
                    name: round(float(weight), 9)
                    for name, weight in sorted(context_weights.items())},
                "context_values": {
                    name: round(value, 9)
                    for name, value in sorted(bounded_context.items())},
                "centered_signal": 0.0,
                "max_abs_logit_shift": round(max(
                    0.0, float(self.conduct_limits.get(junction) or 0.0)), 9),
                "applied_logit_shift": 0.0,
                "baseline": round(baseline_value, 9),
                "proposed": round(baseline_value, 9),
                "output": round(baseline_value, 9),
                "applied": False,
                "model_calls": 0,
                "actions_created": 0,
                "downstream_channels_touched": [],
                "content_free": True,
            })
            return baseline_value, row
        if repeated_source:
            row = self._commit_conduct_receipt({
                "schema_version": 1,
                "kind": "rest_junction_projection",
                "experiment_id": self.experiment_id,
                "at": now,
                "event_ref": event_ref,
                "source_revision_ref": source_revision_ref,
                "work_revision": work_revision,
                "junction": junction,
                "runtime_mode": self.mode,
                "field_config_hash": field.get("config_hash"),
                "junction_profile_hash": self.junctions.snapshot().get(
                    "junction_profile_hash"),
                "requested_mode": self.junctions.junctions.get(
                    junction, "bypass"),
                "configured_effective_mode": self.junctions.effective_mode(
                    junction),
                "effective_mode": "recurrence_preserve",
                "recurrence_kind": "unchanged_source_new_opportunity",
                "source_evidence_changed": False,
                "blocked_reasons": ["unchanged_source_revision"],
                "could_have_conducted": False,
                "conducted": False,
                "blocked": False,
                "quiet_classification": "unchanged_projection_preserved",
                "driver_dimensions": {
                    name: round(float(weight), 9)
                    for name, weight in sorted(drivers.items())},
                "dimension_values": {
                    name: round(float(dimensions.get(name, 0.5)), 9)
                    for name in sorted(drivers)},
                "context_weights": {
                    name: round(float(weight), 9)
                    for name, weight in sorted(context_weights.items())},
                "context_values": {
                    name: round(value, 9)
                    for name, value in sorted(bounded_context.items())},
                "centered_signal": 0.0,
                "max_abs_logit_shift": round(max(
                    0.0, float(self.conduct_limits.get(junction) or 0.0)), 9),
                "applied_logit_shift": 0.0,
                "baseline": round(baseline_value, 9),
                "proposed": round(baseline_value, 9),
                "output": round(baseline_value, 9),
                "applied": False,
                "model_calls": 0,
                "actions_created": 0,
                "downstream_channels_touched": [],
                "content_free": True,
            })
            return baseline_value, row
        norm = (sum(abs(weight) for weight in drivers.values())
                + sum(abs(weight) for weight in context_weights.values()))
        centered_signal = (
            (sum((float(dimensions.get(name, 0.5)) - 0.5) * 2.0 * weight
                 for name, weight in drivers.items())
             + sum((bounded_context.get(name, 0.5) - 0.5) * 2.0 * weight
                   for name, weight in context_weights.items())) / norm
            if norm > 0.0 else 0.0)
        limit = max(0.0, float(self.conduct_limits.get(junction) or 0.0))
        logit_shift = max(-limit, min(limit, centered_signal * limit))
        epsilon = 1e-9
        clipped = max(epsilon, min(1.0 - epsilon, baseline_value))
        logit = math.log(clipped / (1.0 - clipped))
        proposed = 1.0 / (1.0 + math.exp(-(logit + logit_shift)))
        if baseline_value in {0.0, 1.0}:
            proposed = baseline_value
        output, junction_receipt = self.junctions.route(
            junction, baseline_value, proposed)
        applied = bool(junction_receipt.get("applied"))
        row = {
            "schema_version": 1,
            "kind": "rest_junction_projection",
            "experiment_id": self.experiment_id,
            "manifest_authorization": dict(self.manifest_authorization),
            "at": now,
            "event_ref": event_ref,
            "source_revision_ref": source_revision_ref,
            "work_revision": work_revision,
            "junction": junction,
            "runtime_mode": self.mode,
            "field_config_hash": field.get("config_hash"),
            "junction_profile_hash": junction_receipt.get(
                "junction_profile_hash"),
            "requested_mode": junction_receipt.get("requested_mode"),
            "effective_mode": junction_receipt.get("effective_mode"),
            "recurrence_kind": "first_projection_for_source_revision",
            "source_evidence_changed": True,
            "blocked_reasons": [],
            "could_have_conducted": bool(
                self.junctions.effective_mode(junction) == "conduct"),
            "conducted": applied,
            "blocked": False,
            "quiet_classification": (
                "candidate_conducted" if applied
                else "candidate_present_path_bypassed"),
            "driver_dimensions": {
                name: round(float(weight), 9)
                for name, weight in sorted(drivers.items())},
            "dimension_values": {
                name: round(float(dimensions.get(name, 0.5)), 9)
                for name in sorted(drivers)},
            "context_weights": {
                name: round(float(weight), 9)
                for name, weight in sorted(context_weights.items())},
            "context_values": {
                name: round(value, 9)
                for name, value in sorted(bounded_context.items())},
            "centered_signal": round(centered_signal, 9),
            "max_abs_logit_shift": round(limit, 9),
            "applied_logit_shift": round(logit_shift, 9),
            "baseline": round(baseline_value, 9),
            "proposed": round(proposed, 9),
            "output": round(float(output), 9),
            "applied": applied,
            "model_calls": 0,
            "actions_created": 0,
            "downstream_channels_touched": (
                [str(downstream_channel)[:120]] if applied else []),
            "content_free": True,
        }
        row = self._commit_conduct_receipt(row)
        return float(output), row

    def route_consolidation_salience(
            self, baseline: float, *, at: float | None = None,
            event_ref: str = "",
            source_revision_ref: str = "",
            work_revision: str = "") -> tuple[float, dict]:
        """Route bounded trace-retention influence into gist competition."""
        return self._route_bounded_probability(
            "consolidation_salience", baseline,
            downstream_channel="dmn.consolidation_salience",
            at=at, event_ref=event_ref,
            source_revision_ref=source_revision_ref,
            work_revision=work_revision or source_revision_ref)

    def route_associative_recombination_salience(
            self, baseline: float, *, at: float | None = None,
            event_ref: str = "",
            source_revision_ref: str = "",
            work_revision: str = "") -> tuple[float, dict]:
        """Route associative mobility into an existing private candidate."""
        return self._route_bounded_probability(
            "associative_recombination_salience", baseline,
            downstream_channel="dmn.narrative_cluster_salience",
            at=at, event_ref=event_ref,
            source_revision_ref=source_revision_ref,
            work_revision=work_revision or source_revision_ref)

    def route_maintenance_salience(
            self, baseline: float, *, at: float | None = None,
            event_ref: str = "", source_revision_ref: str = "",
            work_revision: str = "",
            context_values: Mapping[str, Any] | None = None,
            blocked_reasons=()) -> tuple[float, dict]:
        """Route rest/readiness/capacity into existing private work only."""
        return self._route_bounded_probability(
            "maintenance_candidate_salience", baseline,
            downstream_channel="dmn.maintenance_candidate_salience",
            at=at, event_ref=event_ref,
            source_revision_ref=source_revision_ref,
            work_revision=work_revision,
            context_values=context_values,
            blocked_reasons=blocked_reasons)

    def observe_trace_recurrence(
            self, *, recurrence_propensity: float, event_ref: str,
            trace_digest: str, condition: str,
            origin_rest_state_digest: str,
            at: float | None = None) -> dict:
        """Project one demonstrated consequence without touching RestField."""
        authorization = self.trace_recurrence_observer
        if not authorization.get("authorized") \
                or self.trace_recurrence_sources is None:
            return {"status": "not_authorized", "recorded": False,
                    "field_advanced": False, "content_free": True}
        now = float(self.clock() if at is None else at)
        event_ref = str(event_ref or "")[:160]
        if not event_ref:
            return {"status": "event_ref_required", "recorded": False,
                    "field_advanced": False, "content_free": True}
        with self._lock:
            if event_ref in self._trace_recurrence_events:
                return {"status": "duplicate", "recorded": False,
                        "field_advanced": False, "content_free": True}
            measurements = {
                "recurrence_propensity": max(
                    0.0, min(1.0, float(recurrence_propensity))),
                "durable_consequence": 1.0,
            }
            projection = self.trace_recurrence_sources.project(
                "trace_recurrence", measurements,
                event_ref=event_ref, at=now)
            row = {
                "schema_version": 1,
                "kind": "rest_trace_recurrence_projection",
                "at": now,
                "experiment_id": authorization.get("experiment_id"),
                "mode": "observe",
                "event_ref": event_ref,
                "trace_digest": str(trace_digest or "")[:64],
                "condition": str(condition or "")[:96],
                "origin_rest_state_digest": str(
                    origin_rest_state_digest or "")[:96],
                "measurements": dict(projection.get("measurements") or {}),
                "candidate_drive": dict(projection.get("drive") or {}),
                "active_dimensions": list(
                    projection.get("active_dimensions") or ()),
                "source_config_hash": authorization.get(
                    "source_config_hash"),
                "field_advanced": False,
                "rest_field_state_changed": False,
                "downstream_channels_touched": [],
                "external_effects": False,
                "content_free": True,
            }
            os.makedirs(
                os.path.dirname(self.trace_recurrence_projection_path),
                exist_ok=True)
            with open(self.trace_recurrence_projection_path, "a",
                      encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(
                    row, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=True, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._trace_recurrence_events.add(event_ref)
            self.trace_recurrence_projection_count += 1
            return {**row, "status": "recorded", "recorded": True}

    def offer(self, packet: Mapping[str, Any], *, at: float | None = None,
              event_ref: str = "") -> dict:
        packet = dict(packet or {})
        if packet.get("content_free") is not True:
            raise ValueError("rest source packet must declare content_free")
        source = str(packet.get("source") or "")
        if self.mode == "disabled":
            return {"mode": self.mode, "source": source,
                    "recorded": False, "field_advanced": False}
        now = float(self.clock() if at is None else at)
        ref = str(event_ref or "")[:160]
        with self._lock:
            if ref and ref in self._last_event_refs:
                return {"mode": self.mode, "source": source,
                        "duplicate_ignored": True, "recorded": False,
                        "field_advanced": False}
            if packet.get("available"):
                aggregate = self.sources.offer(
                    source, dict(packet.get("measurements") or {}),
                    event_ref=ref, at=now)
                admitted = next(
                    (dict(item.get("measurements") or {})
                     for item in aggregate.get("contributions", ())
                     if item.get("source") == source),
                    {})
            else:
                aggregate = self.sources.withdraw(
                    source, event_ref=ref, at=now)
                admitted = {}
            source_spec = self.sources.specs.get(source, {})
            admitted_keys = set(dict(source_spec.get("baselines") or {}))
            raw_measurements = {}
            for key, value in dict(packet.get("measurements") or {}).items():
                if key not in admitted_keys:
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(number):
                    raw_measurements[str(key)] = number
            ranges = self._range_snapshot(source, raw_measurements)
            influence = self._influence_receipt(
                aggregate, source_available=bool(packet.get("available")))
            row = {
                "schema_version": 1,
                "kind": "rest_source_calibration",
                "experiment_id": self.experiment_id,
                "at": now,
                "event_ref": ref,
                "source": source,
                "source_revision": str(
                    source_spec.get("revision") or "")[:80],
                "available": bool(packet.get("available")),
                "availability_reason": (
                    "observed" if packet.get("available") else
                    "unavailable"),
                "raw_measurements": raw_measurements,
                "raw_source_ranges": ranges,
                "raw_source_range_scope": "runtime_session_to_receipt",
                "calibrated_measurements": admitted,
                "measurements": admitted,
                "source_registry_hash": self.sources.config_hash,
                "aggregate_drive": dict(aggregate.get("drive") or {}),
                "active_dimensions": list(
                    aggregate.get("active_dimensions") or ()),
                "runtime_mode": self.mode,
                "gate_state": influence,
                "downstream_junction_influence": influence["junctions"],
                "content_free": True,
            }
            self._append_source_receipt(row)
            self.receipt_count += 1
            field_advanced = False
            if self.mode in {"shadow", "live"}:
                self.field.observe(aggregate, at=now, event_ref=ref)
                self.observer.sample(
                    self.field, at=now, source_snapshot=aggregate,
                    junction_snapshot=self.junctions.snapshot(),
                    influence_snapshot=influence)
                field_advanced = True
            if ref:
                if len(self._event_ref_order) >= 4096:
                    expired = self._event_ref_order.popleft()
                    self._last_event_refs.discard(expired)
                self._event_ref_order.append(ref)
                self._last_event_refs.add(ref)
            return {
                "mode": self.mode,
                "source": source,
                "recorded": True,
                "field_advanced": field_advanced,
                "gate_state": influence,
                "content_free": True,
            }

    def snapshot(self, at: float | None = None) -> dict:
        sources = self.sources.snapshot(at=at)
        return {
            "schema_version": 1,
            "mode": self.mode,
            "experiment_id": self.experiment_id,
            # Keep the causal arming decision visible to read-only observers.
            # This receipt contains only hashes, verdicts, and error classes;
            # it never carries resident content.
            "manifest_authorization": dict(self.manifest_authorization),
            # This authorization is deliberately independent of the field's
            # ordinary conduct junctions.  It is resident-scoped, visible,
            # and completely withdrawn by setting ``enabled: false``.
            "process_recombination_probe": dict(
                self.process_recombination_probe),
            "trace_recurrence_observer": dict(
                self.trace_recurrence_observer),
            "source_registry_hash": self.sources.config_hash,
            "junctions": self.junctions.snapshot(),
            "field": self.field.peek(at),
            "session_source_receipts": self.receipt_count,
            "session_junction_receipts": self.conduct_receipt_count,
            "session_applied_junctions": self.applied_count,
            "session_trace_recurrence_projections":
                self.trace_recurrence_projection_count,
            "last_junction_receipt": self.last_conduct_receipt,
            "latest_source_gate_state": self._influence_receipt(
                sources, source_available=bool(sources.get("contributions"))),
            # Compatibility alias. Its scope is one latest source projection,
            # not the cumulative junction history above.
            "gate_state": {
                **self._influence_receipt(
                    sources,
                    source_available=bool(sources.get("contributions"))),
                "scope": "latest_source_projection",
                "session_conducted_count": self.applied_count,
            },
            "downstream_channels_touched": list(
                (self.last_conduct_receipt or {}).get(
                    "downstream_channels_touched") or []),
        }
