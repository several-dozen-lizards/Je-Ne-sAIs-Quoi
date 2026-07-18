"""Event-driven production binding for the first actionable agency blade.

The runtime does not own a timer or a second salience field.  The existing DMN
winner boundary offers a candidate; this owner may bind that candidate to the
persona-local controller and workbench.  Completed effects return through a
thread-safe handoff and are admitted by the DMN owner on its next boundary.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util
import json
import os
import queue
import time
from typing import Any, Callable, Mapping

from adapters.model_events import AuthorityDecision, tool_capability_status
from core.agency_workbench import (
    FIRST_ACTION_AUTHORITY_TIER, AgencyProposal, PersonaWorkbench,
    proposal_from_candidate, resolve_workbench_config,
)
from shell.autonomy_circulation import (
    circulate_experienced_event, readiness_from_engine,
)


TOOL_TIERS = {
    "inspect_admitted_artifact": "read_private",
    "create_private_draft": "write_private_draft",
}
TIER_REQUIREMENTS = {"read_private": 1, "write_private_draft": 2}
ELIGIBLE_CANDIDATE_KINDS = frozenset({"sensory", "cognitive", "drift"})


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _affect_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> float:
    keys = set(before or {}) | set(after or {})
    if not keys:
        return 0.0
    total = 0.0
    for key in keys:
        try:
            total += abs(float((after or {}).get(key, 0.0))
                         - float((before or {}).get(key, 0.0)))
        except (TypeError, ValueError):
            continue
    return max(0.0, min(1.0, total / len(keys)))


def _body_intensity(engine) -> float:
    soma = getattr(engine, "soma", None)
    if soma is None:
        return 0.0
    try:
        snapshot = dict(soma.snapshot() or {})
    except Exception:
        return 0.0
    values = []
    for region in dict(snapshot.get("regions") or {}).values():
        if isinstance(region, Mapping):
            values.append(region.get("activation", 0.0))
    try:
        return max(0.0, min(1.0, max(float(v) for v in values))) \
            if values else 0.0
    except (TypeError, ValueError):
        return 0.0


class AgencyRuntime:
    """One persona's proposal, authority, workbench, and return owner."""

    def __init__(self, engine, controller, raw_config=None, *,
                 workbench: PersonaWorkbench = None,
                 binding_factory: Callable = None,
                 spec_loader: Callable = None):
        self.engine = engine
        self.controller = controller
        self.config = resolve_workbench_config(
            raw_config, getattr(engine, "model", ""))
        self.workbench = workbench or PersonaWorkbench(engine.pdir)
        self._binding_factory = binding_factory
        self._spec_loader = spec_loader
        self._effects = queue.Queue()
        self._observer = getattr(engine, "salience_observer", None)
        self._last_readiness = None

    def _emit(self, kind: str, **payload) -> None:
        if self._observer is None:
            return
        try:
            self._observer.agency_transition(kind, time.time(), **payload)
        except Exception:
            pass

    def _load_spec(self):
        if self._spec_loader is not None:
            return self._spec_loader(self.config.model)
        from harness.spec_loader import load_spec
        return load_spec(self.config.model)

    def capability(self) -> dict[str, Any]:
        try:
            spec = self._load_spec()
            status = tool_capability_status(spec, event_bridge=True)
            key_name = str((spec.get("identity") or {}).get(
                "api_key_env") or "").strip()
            key_ready = not key_name or bool(os.getenv(key_name))
            dependency_ready = (
                self._binding_factory is not None
                or importlib.util.find_spec("pydantic_ai") is not None)
            usable = status.usable and dependency_ready and key_ready
            reason = (
                status.reason if not status.usable
                else "pydantic agency runtime is not installed"
                if not dependency_ready
                else f"required provider key {key_name} is not set"
                if not key_ready
                else status.reason)
            return {
                "model": self.config.model,
                "declared": status.declared,
                "event_bridge": status.event_bridge,
                "runtime_dependency": dependency_ready,
                "provider_key_required": bool(key_name),
                "provider_key_present": key_ready,
                "usable": usable,
                "reason": reason,
            }
        except Exception as exc:
            return {
                "model": self.config.model,
                "declared": False,
                "event_bridge": False,
                "runtime_dependency": False,
                "provider_key_required": False,
                "provider_key_present": False,
                "usable": False,
                "reason": f"model spec unavailable: {type(exc).__name__}",
            }

    def _authority(self, proposal: AgencyProposal):
        def decide(_state, call, _args, tier):
            tool = str(getattr(call, "tool_name", "") or "")
            expected = TOOL_TIERS.get(tool)
            if "agency" not in getattr(self.engine, "enabled", set()):
                return AuthorityDecision(False, "agency organ is disabled")
            if expected is None or tier != expected:
                return AuthorityDecision(False, "tool or tier is not admitted")
            readiness = self.readiness(
                getattr(self.engine, "idle_metabolism", None))
            if readiness["hard_blocked"]:
                self._emit(
                    "agency_state_blocked",
                    proposal_id=proposal.proposal_id,
                    run_id=proposal.run_id,
                    boundary="before_tool_execute",
                    tool=tool,
                    reasons=readiness["reasons"],
                    capacity=readiness["capacity"],
                    support=readiness["support"])
                return AuthorityDecision(
                    False, "live organism state requires recovery")
            required = TIER_REQUIREMENTS[expected]
            admitted = min(
                int(self.config.authority_tier),
                int(proposal.envelope.authority_tier))
            if required > admitted:
                return AuthorityDecision(
                    False, "persona policy does not admit this authority tier")
            return AuthorityDecision(
                True, "persona-private workbench capability admitted")
        return decide

    def readiness(self, field=None) -> dict[str, Any]:
        """Read the live organism; do not settle it or invent another clock."""
        self._last_readiness = readiness_from_engine(self.engine, field)
        return dict(self._last_readiness)

    def _selection_eligible(self, candidate: Mapping[str, Any]) -> bool:
        candidate = dict(candidate or {})
        return (
            "agency" in getattr(self.engine, "enabled", set())
            and self.config.authority_tier >= FIRST_ACTION_AUTHORITY_TIER
            and candidate.get("kind") in ELIGIBLE_CANDIDATE_KINDS
            and candidate.get("source") not in {
                "agency", "writing_desk_seed", "writing_desk_project",
                "writing_desk_effect", "archive_read", "archive_read_effect",
                "research_cue", "research_interest", "research_source",
                "research_effect",
            }
            and self.controller.status().get("active") is None
        )

    def selection_score(self, field, candidate: Mapping[str, Any], *,
                        now: float, readiness: Mapping[str, Any] = None):
        state = dict(readiness or self.readiness(field))
        eligible = self._selection_eligible(candidate) \
            and not state.get("hard_blocked")
        return field.attention_score(
            dict(candidate), now=now,
            action_readiness=state.get("readiness", 0.0),
            action_eligible=eligible)

    def _binding(self, proposal: AgencyProposal, spec):
        tools = self.workbench.tools_for_run(proposal.run_id)
        kwargs = {
            "substrate_mode": "on",
            "tools": tools,
            "tool_tiers": TOOL_TIERS,
            "authority": self._authority(proposal),
            "model_spec": spec,
            "model_name": self.config.model,
        }
        if self._binding_factory is not None:
            return self._binding_factory(
                self.engine, proposal.envelope, proposal=proposal,
                **kwargs)
        from adapters.pydantic_bridge import BridgeBudget
        from shell.agency_runner import bind_agency_runner
        kwargs["budget"] = BridgeBudget(
            # One optional read followed by one optional private creation.
            admitted_tool_rounds=2,
            correction_turns=0,
            tool_slots=2,
            max_tokens_per_request=400,
        )
        return bind_agency_runner(
            self.engine, proposal.envelope, **kwargs)

    def eligible(self, candidate: Mapping[str, Any]) -> bool:
        return self._selection_eligible(candidate)

    def start_candidate(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        """Offer one already-won candidate; never starts from wall time."""
        if not self.eligible(candidate):
            return {"started": False, "reason": "not_eligible"}
        readiness = self.readiness(getattr(self.engine, "idle_metabolism", None))
        if readiness["hard_blocked"]:
            self._emit(
                "agency_state_blocked",
                candidate_key=str(candidate.get("key") or ""),
                reasons=readiness["reasons"],
                capacity=readiness["capacity"],
                support=readiness["support"])
            return {"started": False, "reason": "state_blocked",
                    "readiness": readiness}
        capability = self.capability()
        if not capability["usable"]:
            self._emit(
                "agency_refused", reason=capability["reason"],
                candidate_key=str(candidate.get("key") or ""),
                model=self.config.model)
            return {"started": False, "reason": capability["reason"]}
        proposal = proposal_from_candidate(
            getattr(self.engine, "persona", ""), candidate,
            self.config.authority_tier)
        try:
            spec = self._load_spec()
            binding = self._binding(proposal, spec)
        except Exception as exc:
            self._emit(
                "agency_refused", proposal_id=proposal.proposal_id,
                run_id=proposal.run_id,
                reason=f"binding unavailable: {type(exc).__name__}")
            return {"started": False, "reason": type(exc).__name__}
        before = dict(getattr(self.engine, "cocktail", {}) or {})
        self._emit(
            "agency_proposed", proposal_id=proposal.proposal_id,
            run_id=proposal.run_id,
            source_ref=proposal.envelope.source_ref,
            source_digest=proposal.envelope.source_digest,
            source_kind=proposal.envelope.source_kind,
            authority_tier=proposal.envelope.authority_tier,
            model=self.config.model)
        try:
            future = self.controller.start(
                proposal.run_id, binding,
                proposal_id=proposal.proposal_id)
        except Exception as exc:
            self._emit(
                "agency_refused", proposal_id=proposal.proposal_id,
                run_id=proposal.run_id, reason=str(exc)[:200])
            return {"started": False, "reason": type(exc).__name__}
        future.add_done_callback(
            lambda done: self._completed(
                proposal, dict(candidate), before, done))
        return {
            "started": True,
            "proposal_id": proposal.proposal_id,
            "run_id": proposal.run_id,
            "future": future,
        }

    def _completed(self, proposal: AgencyProposal,
                   source_candidate: Mapping[str, Any],
                   before: Mapping[str, Any], future) -> None:
        try:
            outcome = future.result()
        except Exception as exc:
            reason = ("interrupted" if isinstance(
                exc, concurrent.futures.CancelledError)
                else f"failed:{type(exc).__name__}")
            self._effects.put({
                "kind": "retry", "reason": reason,
                "run_id": proposal.run_id,
                "proposal_id": proposal.proposal_id,
                "candidate": dict(source_candidate),
            })
            if reason != "interrupted":
                self._emit(
                    "agency_effect_failed", run_id=proposal.run_id,
                    proposal_id=proposal.proposal_id,
                    error_type=type(exc).__name__)
            return
        artifacts = self.workbench.artifacts_for_run(proposal.run_id)
        if getattr(outcome, "status", "completed") == "deferred":
            self._effects.put({
                "kind": "retry", "reason": "authority_deferred",
                "run_id": proposal.run_id,
                "proposal_id": proposal.proposal_id,
                "candidate": dict(source_candidate),
            })
            return
        workbench_ref = str(source_candidate.get("workbench_ref") or "")
        if workbench_ref:
            try:
                self.workbench.mark_inbox_addressed(
                    workbench_ref, proposal.run_id,
                    "private_draft" if artifacts else "quiet")
                self._emit(
                    "agency_input_addressed", run_id=proposal.run_id,
                    proposal_id=proposal.proposal_id, ref=workbench_ref,
                    outcome="private_draft" if artifacts else "quiet")
            except Exception as exc:
                self._emit(
                    "agency_effect_failed", run_id=proposal.run_id,
                    proposal_id=proposal.proposal_id,
                    error_type=f"inbox_resolution:{type(exc).__name__}")
        if not artifacts:
            output = getattr(getattr(outcome, "result", None), "output", "")
            self._effects.put({
                "kind": "settled", "outcome": "quiet",
                "run_id": proposal.run_id,
                "proposal_id": proposal.proposal_id,
                "source_ref": proposal.envelope.source_ref,
                "source_digest": proposal.envelope.source_digest,
                "candidate": dict(source_candidate),
                "output_digest": _digest(str(output or "")),
            })
            self._emit(
                "agency_no_effect", run_id=proposal.run_id,
                proposal_id=proposal.proposal_id,
                status=getattr(outcome, "status", "completed"),
                output_digest=_digest(str(output or "")))
            return
        prior = self.workbench.records(kind="private_draft", limit=200)
        current_refs = {record["ref"] for record in artifacts}
        prior_hashes = {
            record.get("sha256") for record in prior
            if record.get("ref") not in current_refs}
        unique = sum(
            1 for record in artifacts
            if record.get("sha256") not in prior_hashes)
        effect = {
            "kind": "artifact",
            "run_id": proposal.run_id,
            "proposal_id": proposal.proposal_id,
            "source_ref": proposal.envelope.source_ref,
            "source_digest": proposal.envelope.source_digest,
            "artifact_refs": [record["ref"] for record in artifacts],
            "artifact_digests": [record["sha256"][:16]
                                 for record in artifacts],
            "artifact_labels": [record.get("label") or "untitled"
                                for record in artifacts],
            "candidate": dict(source_candidate),
            "novelty": unique / max(1, len(artifacts)),
            "affect_change": _affect_delta(
                before, dict(getattr(self.engine, "cocktail", {}) or {})),
            "body_intensity": _body_intensity(self.engine),
        }
        self._effects.put(effect)
        self._emit(
            "agency_effect_ready", run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            artifact_count=len(artifacts),
            artifact_refs=effect["artifact_refs"])

    def _feed_outcome(self, effect: Mapping[str, Any]) -> dict[str, Any] | None:
        """Return a chosen consequence through feel -> soma -> oscillator."""
        if effect.get("kind") == "artifact":
            labels = ", ".join(effect.get("artifact_labels") or ["untitled"])
            event_text = (
                "A self-chosen private work cycle created an unsent draft "
                f"named: {labels}. Nothing was published or sent.")
        else:
            event_text = (
                "A self-chosen private work cycle ended without creating an "
                "artifact; quiet was allowed and nothing was sent or changed "
                "outside the private workbench.")
        delta = circulate_experienced_event(self.engine, event_text)
        self._emit(
            "agency_felt_consequence", run_id=effect.get("run_id"),
            proposal_id=effect.get("proposal_id"),
            felt=dict(delta.get("felt") or {}),
            why=str(delta.get("why") or "")[:240])
        return delta

    def drain_effects(self, field, *, now: float = None) -> list[dict[str, Any]]:
        """Re-enter completed effects from the DMN owner's locked boundary."""
        now = time.time() if now is None else float(now)
        admitted = []
        while True:
            try:
                effect = self._effects.get_nowait()
            except queue.Empty:
                break
            if effect.get("kind") == "retry":
                candidate = dict(effect.get("candidate") or {})
                salience = float(candidate.get("salience", 0.05))
                field.pressure.refund()
                restored = field.queue.put(
                    candidate, salience, now=now,
                    offer_meta={"operation": "requeued",
                                "reason": effect.get("reason")})
                admitted.append(restored)
                self._emit(
                    "agency_field_reentry", run_id=effect["run_id"],
                    proposal_id=effect["proposal_id"],
                    candidate_key=restored.get("key"),
                    outcome="requeued", reason=effect.get("reason"))
                continue
            source_candidate = dict(effect.get("candidate") or {})
            field.satiate(source_candidate, now=now)
            felt = None
            try:
                felt = self._feed_outcome(effect)
            except Exception as exc:
                self._emit(
                    "agency_effect_failed", run_id=effect.get("run_id"),
                    proposal_id=effect.get("proposal_id"),
                    error_type=f"felt_consequence:{type(exc).__name__}")
            refs = list(effect.get("artifact_refs") or [])
            if refs:
                content = (
                    "Private agency work produced "
                    f"{len(refs)} unsent artifact"
                    f"{'s' if len(refs) != 1 else ''}: " + ", ".join(refs))
                novelty = effect.get("novelty", 0.0)
            else:
                content = (
                    "A private agency cycle settled quietly without creating "
                    "or sending an artifact.")
                novelty = 0.0
            affect_change = (_affect_delta(
                felt.get("before") or {}, felt.get("after") or {})
                             if felt else effect.get("affect_change", 0.0))
            body_intensity = _body_intensity(self.engine)
            candidate = field.offer_cognitive_event(
                "agency", content,
                {
                    "novelty": novelty,
                    "affect_change": affect_change,
                    "body_intensity": body_intensity,
                    "relationship": 0.0,
                    "unresolved": 0.0,
                },
                key=f"agency:{effect['run_id']}", now=now,
                raw_ref=((effect.get("artifact_digests") or
                          [effect.get("output_digest")])[0]),
                ownership="persona_private",
                receipts=(effect.get("artifact_digests") or
                          [effect.get("output_digest")]))
            admitted.append(candidate)
            self._emit(
                "agency_field_reentry", run_id=effect["run_id"],
                proposal_id=effect["proposal_id"],
                candidate_key=candidate.get("key"),
                artifact_refs=refs,
                novelty=novelty,
                affect_change=affect_change,
                body_intensity=body_intensity)
        if admitted:
            field.save(now=now)
            if self._observer is not None:
                self._observer.field_snapshot(field, now)
        return admitted

    def _offer_inbox_record(self, field, record: Mapping[str, Any], *,
                            now: float) -> dict[str, Any]:
        """Project one still-unintegrated admission through normal event math."""
        record = dict(record or {})
        ref = str(record.get("ref") or "")
        digest = str(record.get("sha256") or "")
        candidate = field.offer_cognitive_event(
            "agency_inbox",
            f"An explicitly admitted work item is available as {ref}, "
            f"named {record.get('label') or 'untitled'}.",
            {"novelty": 1.0, "affect_change": 0.0,
             "body_intensity": 0.0, "relationship": 1.0,
             "unresolved": 1.0},
            key=f"agency_inbox:{digest[:20]}", now=now,
            raw_ref=digest[:16], ownership="human_admitted",
            receipts=[digest[:16]])
        candidate["workbench_ref"] = ref
        return candidate

    def refresh_pending(self, field, *, now: float = None) -> list[dict[str, Any]]:
        """Let unresolved admissions recur only at a real owner boundary.

        The caller is the DMN fire path. Repeated unresolvedness therefore
        compounds through the ordinary de-duplicating field rather than a
        timer, priority lane, or command bypass.
        """
        now = time.time() if now is None else float(now)
        offered = []
        for record in self.workbench.pending_inbox():
            candidate = self._offer_inbox_record(field, record, now=now)
            offered.append(candidate)
            self._emit(
                "agency_input_recurred", ref=record["ref"],
                candidate_key=candidate.get("key"),
                salience=round(float(candidate.get("salience", 0.0)), 6))
        return offered

    def admit_text(self, field, label: str, content: str, *,
                   now: float = None) -> dict[str, Any]:
        """Human admission becomes a real cognitive candidate, not a task run."""
        now = time.time() if now is None else float(now)
        record = self.workbench.admit_text(label, content)
        candidate = self._offer_inbox_record(field, record, now=now)
        field.save(now=now)
        if self._observer is not None:
            self._observer.field_snapshot(field, now)
            self._emit(
                "agency_input_admitted", ref=record["ref"],
                candidate_key=candidate.get("key"),
                content_digest=record["sha256"][:16],
                content_chars=record["chars"])
        return {"record": record, "candidate": candidate}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": "agency" in getattr(self.engine, "enabled", set()),
            "config": {
                "model": self.config.model,
                "authority_tier": self.config.authority_tier,
            },
            "capability": self.capability(),
            "controller": self.controller.status(),
            "readiness": self.readiness(
                getattr(self.engine, "idle_metabolism", None)),
            "workbench": self.workbench.status(),
        }
