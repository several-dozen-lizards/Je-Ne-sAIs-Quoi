"""DMN-owned, local-first writing desk motor.

This runtime owns no clock and no second attention field.  Human-admitted
seeds and open projects recur only at a real DMN fire, compete in the shared
field, and may produce a resource-shaped sequence of host-validated,
append-only desk movements. WD1 is
strictly local-model-only and has no provider fallback path.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import queue
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from adapters.model_events import collect_legacy_text
from core.agency_projection import AgencyTaskEnvelope
from core.interior_work_envelope import InteriorWorkEnvelope
from core.sovereign_interior import lease_fields
from core.volitional_choice import (
    ChoiceLedger, OwnerChoiceRejected, witness_projection,
)
from core.writing_desk import WritingDesk
from harness.model_call_receipts import (
    model_call_scope, new_cycle_id, record_model_call,
)
from shell.agency_controller import AgencyRunOutcome
from shell.autonomy_circulation import (
    circulate_experienced_event, readiness_from_engine,
)


DESK_SOURCES = frozenset({"writing_desk_seed", "writing_desk_project"})
DESK_AUTHORITY_TIER = 2
DESK_ACTIONS = frozenset({
    "quiet", "start", "revise", "complete", "pause", "abandon",
})


def _digest(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]


def _finite(value: Any, fallback: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return value if math.isfinite(value) else float(fallback)


@dataclass(frozen=True)
class WritingDeskConfig:
    model: str
    authority_tier: int = 0
    local_only: bool = True
    max_tokens: int = 700

    def __post_init__(self):
        model = str(self.model or "").strip()
        if not model:
            raise ValueError("writing desk requires an explicit model")
        if not isinstance(self.authority_tier, int) \
                or isinstance(self.authority_tier, bool) \
                or not 0 <= self.authority_tier <= DESK_AUTHORITY_TIER:
            raise ValueError("writing desk authority_tier must be 0 through 2")
        if type(self.local_only) is not bool:
            raise ValueError("writing desk local_only must be a bool")
        if not isinstance(self.max_tokens, int) \
                or not 128 <= self.max_tokens <= 1200:
            raise ValueError("writing desk max_tokens must be 128 through 1200")
        object.__setattr__(self, "model", model)


def resolve_writing_desk_config(raw: Mapping[str, Any] | None,
                                active_model: str) -> WritingDeskConfig:
    raw = dict(raw or {})
    return WritingDeskConfig(
        model=str(raw.get("model") or active_model or "").strip(),
        authority_tier=int(raw.get("authority_tier", 0)),
        local_only=bool(raw.get("local_only", True)),
        max_tokens=int(raw.get("max_tokens", 700)),
    )


def parse_desk_proposal(text: str) -> dict[str, str]:
    """Extract one strict JSON proposal without executing model-shaped data."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    decoder = json.JSONDecoder()
    proposal = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            proposal = value
            break
    if proposal is None:
        raise ValueError("writing desk model did not return one JSON object")
    allowed = {"action", "title", "form", "content", "orientation"}
    unknown = set(proposal) - allowed
    if unknown:
        raise ValueError(
            f"writing desk proposal contains unknown fields: {sorted(unknown)}")
    action = str(proposal.get("action") or "").strip().casefold()
    if action not in DESK_ACTIONS:
        raise ValueError("writing desk proposal action is invalid")
    return {
        "action": action,
        "title": str(proposal.get("title") or "").strip(),
        "form": str(proposal.get("form") or "").strip(),
        "content": str(proposal.get("content") or "").strip(),
        "orientation": str(proposal.get("orientation") or "").strip(),
    }


def parse_desk_movements(text: str) -> list[dict[str, str]]:
    """Parse one movement or an explicitly ordered private movement sequence."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    decoder = json.JSONDecoder()
    value = None
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            decoded, _end = decoder.raw_decode(text[index:])
        except (TypeError, ValueError):
            continue
        if isinstance(decoded, (dict, list)):
            value = decoded
            break
    if isinstance(value, dict) and set(value) == {"movements"}:
        value = value["movements"]
    if isinstance(value, dict):
        return [parse_desk_proposal(json.dumps(value))]
    if not isinstance(value, list) or not value:
        raise ValueError("writing desk model did not return movements")
    return [parse_desk_proposal(json.dumps(item)) for item in value]


class WritingDeskRuntime:
    """One persona's local proposal, append-only commit, and return owner."""

    def __init__(self, engine, controller, raw_config=None, *,
                 desk: WritingDesk = None, adapter_factory: Callable = None,
                 spec_loader: Callable = None,
                 choice_ledger: ChoiceLedger = None):
        self.engine = engine
        self.controller = controller
        self.config = resolve_writing_desk_config(
            raw_config, getattr(engine, "model", ""))
        self.desk = desk or WritingDesk(engine.pdir)
        self.choice_ledger = choice_ledger or ChoiceLedger(engine.pdir)
        self._adapter_factory = adapter_factory
        self._spec_loader = spec_loader
        self._adapter = None
        self._effects = queue.Queue()
        self._observer = getattr(engine, "salience_observer", None)
        self._last_readiness = None
        self.internal_outcome_sink = None

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

    def _model_adapter(self, spec):
        if self._adapter is None:
            if self._adapter_factory is not None:
                self._adapter = self._adapter_factory(spec)
            else:
                from adapters.family_adapters import adapter_for
                self._adapter = adapter_for(spec)
        return self._adapter

    def capability(self) -> dict:
        enabled = "writing_desk" in getattr(self.engine, "enabled", set())
        volitional_offer = "offer_writing" in getattr(
            self.engine, "_volitional_actions", {})
        if not enabled:
            try:
                identity = dict((self._load_spec().get("identity") or {}))
            except Exception:
                identity = {}
            return {
                "usable": False, "reason": "writing_desk organ is disabled",
                "model": self.config.model,
                "locality": str(identity.get("locality") or "unknown"),
                "provider": identity.get("provider"),
                "event_bridge": False,
                "volitional_offer": volitional_offer,
                "paid_fallbacks": 0,
            }
        try:
            spec = self._load_spec()
            identity = dict(spec.get("identity") or {})
            locality = str(identity.get("locality") or "unknown")
            adapter = self._model_adapter(spec)
            event_bridge = callable(getattr(adapter, "events", None))
            authority = self.config.authority_tier >= DESK_AUTHORITY_TIER
            local_admitted = locality == "local" or not self.config.local_only
            usable = enabled and authority and local_admitted and event_bridge
            if not authority:
                reason = "writing desk authority tier does not admit private writes"
            elif not local_admitted:
                reason = "WD1 refuses non-local writing models"
            elif not event_bridge:
                reason = "writing desk model lacks the interruptible event bridge"
            else:
                reason = "local interruptible writing path admitted"
            return {
                "usable": usable, "reason": reason,
                "model": self.config.model, "locality": locality,
                "provider": identity.get("provider"),
                "event_bridge": event_bridge,
                "volitional_offer": volitional_offer,
                "paid_fallbacks": 0,
            }
        except Exception as exc:
            return {
                "usable": False,
                "reason": f"writing desk model unavailable: {type(exc).__name__}",
                "model": self.config.model, "locality": "unknown",
                "provider": None, "event_bridge": False,
                "volitional_offer": volitional_offer,
                "paid_fallbacks": 0,
            }

    def readiness(self, field=None) -> dict:
        self._last_readiness = readiness_from_engine(self.engine, field)
        return dict(self._last_readiness)

    @staticmethod
    def eligible(candidate: Mapping[str, Any]) -> bool:
        return str(dict(candidate or {}).get("source") or "") in DESK_SOURCES

    def selection_score(self, field, candidate: Mapping[str, Any], *,
                        now: float, readiness: Mapping[str, Any] = None):
        state = dict(readiness or self.readiness(field))
        eligible = self.eligible(candidate) \
            and "writing_desk" in getattr(self.engine, "enabled", set())
        desk_satiety = field.satiety.warmth("writing_desk", now)
        readiness_value = (
            max(0.0, min(1.0, _finite(state.get("readiness"))))
            / (1.0 + desk_satiety) if eligible else 0.0)
        score, meta = field.attention_score(
            dict(candidate), now=now,
            action_readiness=readiness_value,
            action_eligible=eligible, scope_satiety=desk_satiety)
        return score, {
            **meta, "writing_desk_eligible": eligible,
            "writing_desk_readiness": round(readiness_value, 6),
            "writing_desk_satiety": round(desk_satiety, 6),
        }

    def _offer_seed(self, field, record: Mapping[str, Any], *, now: float):
        ownership = str(record.get("ownership") or "human_admitted")
        if ownership == "persona_chosen_research_handoff":
            description = (
                f"A self-chosen cited research handoff named "
                f"{record.get('label') or 'untitled'} is waiting on the desk.")
            relationship = .3
        elif ownership == "persona_chosen_conversation":
            description = (
                f"Self-chosen writing material named "
                f"{record.get('label') or 'untitled'} is waiting on the desk.")
            relationship = 1.0
        else:
            description = (
                f"Human-admitted writing material named "
                f"{record.get('label') or 'untitled'} is waiting on the desk.")
            relationship = 1.0
        candidate = field.offer_cognitive_event(
            "writing_desk_seed",
            description,
            {"novelty": 1.0, "affect_change": 0.0,
             "body_intensity": 0.0, "relationship": relationship,
             "unresolved": 1.0},
            key=f"writing_desk_seed:{record['seed_id']}", now=now,
            raw_ref=record.get("source_digest"),
            ownership=ownership,
            receipts=[record.get("source_digest")])
        candidate.update({
            "seed_id": record["seed_id"],
            "satiety_key": f"writing_desk_seed:{record['seed_id']}",
            **lease_fields(record, origin="writing_desk_seed"),
        })
        return candidate

    def _offer_project(self, field, project: Mapping[str, Any], *, now: float):
        candidate = field.offer_cognitive_event(
            "writing_desk_project",
            f"An open {project.get('form') or 'writing'} project named "
            f"{project.get('title') or 'untitled'} remains unresolved.",
            {"novelty": 0.0, "affect_change": 0.0,
             "body_intensity": 0.0, "relationship": 1.0,
             "unresolved": 1.0},
            key=f"writing_desk_project:{project['project_id']}", now=now,
            raw_ref=str(project.get("latest_sha256") or "")[:16],
            ownership="persona_private",
            receipts=[str(project.get("latest_sha256") or "")[:16]])
        candidate.update({
            "project_id": project["project_id"],
            "satiety_key": f"writing_desk_project:{project['project_id']}",
        })
        return candidate

    def refresh_pending(self, field, *, now: float = None) -> list[dict]:
        """Recur unresolved desk state only at the caller's true DMN fire."""
        now = time.time() if now is None else float(now)
        offered = []
        if "writing_desk" not in getattr(self.engine, "enabled", set()):
            return offered
        for seed in self.desk.pending_seeds():
            offered.append(self._offer_seed(field, seed, now=now))
        for project in self.desk.projects_status(state="open"):
            offered.append(self._offer_project(field, project, now=now))
        if offered:
            self._emit(
                "writing_desk_recurred", candidate_count=len(offered),
                candidate_keys=[value.get("key") for value in offered])
        return offered

    def admit_seed(self, field, label: str, *, content: str = "",
                   anchors=(), now: float = None,
                   ownership: str = "human_admitted") -> dict:
        now = time.time() if now is None else float(now)
        # Validate every anchor against this human-owned library before the
        # reference is admitted.  No source text is copied into the seed.
        anchors = list(anchors or ())
        for anchor in anchors:
            self._inspect_anchor(anchor, maximum=1)
        record = self.desk.admit_seed(
            label, content=content, anchors=anchors, ownership=ownership)
        candidate = self._offer_seed(field, record, now=now)
        field.save(now=now)
        self._emit(
            "writing_desk_seed_admitted", seed_id=record["seed_id"],
            candidate_key=candidate.get("key"),
            content_chars=record.get("chars", 0),
            anchor_count=len(record.get("anchors") or []),
            ownership=record.get("ownership"),
            duplicate=record.get("duplicate", False))
        return {"record": record, "candidate": candidate}

    def consume_internal_action(self, selection: Mapping[str, Any]) -> dict:
        """Owner-validate one wrapper-local draft handoff without executing it."""
        selection = dict(selection or {})
        if selection.get("capability") != "writing_desk.private_draft" \
                or selection.get("owner") != "writing_desk":
            raise ValueError("internal action is not owned by Writing Desk")
        if selection.get("authority_scope") \
                != "wrapper_local_private_reversible" \
                or selection.get("external_effects") is not False \
                or selection.get("tool_binding") is not None \
                or selection.get("scheduler_slot") is not None:
            raise ValueError("internal writing action exceeded wrapper authority")
        payload = dict(selection.get("payload") or {})
        provenance = dict(payload.get("project_loom_provenance") or {})
        allowed_provenance = {
            "proposal_id", "orientation_id", "candidate_id", "selection_mode"}
        if not set(provenance).issubset(allowed_provenance) \
                or not {"proposal_id", "candidate_id"}.issubset(provenance) \
                or any(not str(value or "").strip()
                       for value in provenance.values()):
            raise ValueError("internal writing action provenance is incomplete")
        label = str(payload.get("label") or "").strip()
        content = str(payload.get("content") or "").strip()
        if not label or not content:
            raise ValueError("internal writing action needs bounded private material")
        record = self.desk.admit_seed(
            label, content=content,
            ownership="persona_project_handoff")
        self._emit(
            "writing_desk_internal_action_admitted",
            selection_id=selection.get("selection_id"),
            seed_id=record.get("seed_id"),
            duplicate=record.get("duplicate", False),
            capability="writing_desk.private_draft",
            ownership="persona_project_handoff")
        return record

    def _inspect_anchor(self, anchor: str, maximum: int = 5200) -> dict:
        """Resolve only an exact admitted anchor; never search or accept paths."""
        if str(anchor).startswith("doc_"):
            return self.engine.documents.inspect_anchor(
                anchor, maximum=maximum)
        if str(anchor).startswith("drep_"):
            return self.engine.documents.inspect_report_anchor(
                anchor, maximum=maximum)
        if str(anchor).startswith("arc_"):
            archive = getattr(self.engine, "archive", None)
            if archive is None:
                raise ValueError("conversation archive is not attached")
            return archive.inspect_anchor(anchor, maximum=maximum)
        if str(anchor).startswith("res_"):
            research = getattr(self.engine, "research_desk", None)
            if research is None:
                raise ValueError("research desk is not attached")
            return research.inspect_anchor(anchor, maximum=maximum)
        raise ValueError("writing desk source anchor is invalid")

    def resume_project(self, field, project_id: str, *, now: float = None):
        now = time.time() if now is None else float(now)
        run_id = f"human-resume-{_digest({'project_id': project_id, 'now': now})}"
        record = self.desk.resume_project(run_id, project_id)
        candidate = self._offer_project(
            field, self.desk.project(project_id), now=now)
        field.save(now=now)
        return {"record": record, "candidate": candidate}

    def _source_material(self, candidate: Mapping[str, Any]):
        candidate = dict(candidate or {})
        if candidate.get("source") == "writing_desk_seed":
            seed = self.desk.seed(candidate.get("seed_id"), include_content=True)
            anchors = list(seed.get("anchors") or [])
            pieces = []
            if seed.get("content"):
                pieces.append("Human-admitted seed text:\n" + seed["content"])
            for anchor in anchors:
                inspected = self._inspect_anchor(anchor)
                pieces.append(
                    f"Admitted source anchor [{anchor}] "
                    f"{inspected.get('title') or 'Untitled'}:\n"
                    + inspected["content"])
            source = {
                "kind": "seed", "seed_id": seed["seed_id"],
                "source_digest": seed["source_digest"],
                "anchors": anchors,
                "candidate_key": candidate.get("key"),
                "candidate_salience": candidate.get("salience"),
            }
            return None, source, "\n\n".join(pieces)
        project = self.desk.project(
            candidate.get("project_id"), include_content=True)
        source = dict(project.get("source") or {})
        anchors = list(source.get("anchors") or [])
        pieces = [
            f"Open project: {project['title']}\n"
            f"Form so far: {project['form']}\n"
            f"Revision count: {project['revision_count']}\n"
            "Current revision:\n" + project.get("content", "")]
        for anchor in anchors:
            inspected = self._inspect_anchor(anchor)
            pieces.append(
                f"Admitted source anchor [{anchor}] "
                f"{inspected.get('title') or 'Untitled'}:\n"
                + inspected["content"])
        return project, source, "\n\n".join(pieces)

    def _assembly(self, candidate: Mapping[str, Any], spec, *,
                  witnessed: bool = False):
        project, source, material = self._source_material(candidate)
        if project is None:
            actions = "quiet or start"
            action_contract = (
                "For start, title, form, and content must all be nonempty. "
                "For quiet, leave title, form, and content empty.")
            summary = "Admitted material is available for a possible new project."
        else:
            actions = "quiet, revise, complete, pause, or abandon"
            action_contract = (
                "For revise, content must be a fresh complete revision and "
                "title/form must be empty. For complete, pause, abandon, or "
                "quiet, title, form, and content must be empty.")
            summary = f"Open writing project {project['project_id']}."
        orientation_contract = (
            " Also describe your present, revisable orientation toward the "
            "fork in orientation. It is evidence you encounter, not a score "
            "or justification forced to agree with the action."
            if witnessed else "")
        task = (
            "This is your private writing desk. The material won attention "
            "through your ordinary field; it is not an order to produce. "
            "Notice what form, if any, the material appears to want now. "
            f"Choose one action, or an ordered sequence of actions, from: "
            f"{actions}. {action_contract} "
            f"{orientation_contract} Return exactly one JSON object and no "
            "prose outside it. For one movement use exactly these keys: "
            "action, title, form, content, orientation. For a sequence use "
            "exactly one movements key containing objects with those exact "
            "keys. Do not pad a sequence: stop when the work settles. Nothing will "
            "be published or sent. Do not claim any external effect."
        )
        source_digest = str(source.get("source_digest") or _digest(source))
        envelope = AgencyTaskEnvelope(
            task=task, source_kind=str(candidate.get("source")),
            source_ref=str(candidate.get("key")),
            source_digest=source_digest,
            source_summary=summary,
            source_ownership=str(candidate.get("ownership") or
                                 "persona_private"),
            authority_tier=self.config.authority_tier,
        )
        product = self.engine.build_agency_snapshot(
            envelope, substrate_mode="on",
            external_demand_epoch=self.controller.live_epoch(),
            agency_spec=spec, agency_model=self.config.model)
        product.assembly.add(
            "writing_desk_material", material,
            priority=9, budget=1200)
        return product, project, source

    @staticmethod
    def _usage(events) -> dict:
        completed = next((event for event in reversed(events)
                          if event.kind == "completed"), None)
        usage = dict(getattr(completed, "usage", {}) or {})
        normalized = {
            "input_tokens": int(usage.get("input_tokens")
                                or usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens")
                                 or usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }
        for key in ("total_ms", "provider_ms", "prompt_ms", "gen_ms",
                    "load_ms"):
            if isinstance(usage.get(key), (int, float)):
                normalized[key] = float(usage[key])
        return normalized

    def _commit(self, context, candidate, proposal, project, source, *,
                run_id=None):
        commit_run_id = str(run_id or context.run_id)
        action = proposal["action"]
        is_seed = candidate.get("source") == "writing_desk_seed"
        if is_seed and action not in {"quiet", "start"}:
            raise ValueError("new writing material admits only quiet or start")
        if not is_seed and action not in {
                "quiet", "revise", "complete", "pause", "abandon"}:
            raise ValueError("open project proposal action is invalid")
        if action == "start":
            if not proposal["title"] or not proposal["form"] \
                    or not proposal["content"]:
                raise ValueError("start proposal is missing title, form, or content")
            record = self.desk.start_project(
                commit_run_id, proposal["title"], proposal["form"],
                proposal["content"], source=source)
            self.desk.resolve_seed(
                candidate["seed_id"], commit_run_id, "project_started",
                project_id=record["project_id"])
            return "started", record
        if action == "revise":
            if proposal["title"] or proposal["form"] or not proposal["content"]:
                raise ValueError("revision proposal has an invalid shape")
            return "revised", self.desk.append_revision(
                commit_run_id, project["project_id"], proposal["content"])
        if action in {"complete", "pause", "abandon"}:
            if proposal["title"] or proposal["form"] or proposal["content"]:
                raise ValueError("resolution proposal must not carry draft content")
            resolution = {
                "complete": "completed", "pause": "paused",
                "abandon": "abandoned",
            }[action]
            return resolution, self.desk.resolve_project(
                commit_run_id, project["project_id"], resolution)
        if proposal["title"] or proposal["form"] or proposal["content"]:
            raise ValueError("quiet proposal must not carry draft content")
        if is_seed:
            record = self.desk.resolve_seed(
                candidate["seed_id"], commit_run_id, "quiet")
        else:
            record = {"project_id": project["project_id"]}
        return "quiet", record

    def _candidate_current(self, candidate: Mapping[str, Any]) -> bool:
        source = str(dict(candidate or {}).get("source") or "")
        if source == "writing_desk_seed":
            seed_id = candidate.get("seed_id")
            return seed_id in {
                value.get("seed_id") for value in self.desk.pending_seeds()}
        if source == "writing_desk_project":
            project_id = candidate.get("project_id")
            return project_id in {
                value.get("project_id")
                for value in self.desk.projects_status(state="open")}
        return False

    def start_candidate(self, candidate: Mapping[str, Any]) -> dict:
        candidate = dict(candidate or {})
        if not self.eligible(candidate):
            return {"started": False, "reason": "not_eligible"}
        if not self._candidate_current(candidate):
            return {"started": False, "reason": "stale_candidate"}
        readiness = self.readiness(getattr(self.engine, "idle_metabolism", None))
        capability = self.capability()
        if not capability["usable"]:
            self._emit(
                "writing_desk_refused", reason=capability["reason"],
                candidate_key=candidate.get("key"),
                model=self.config.model)
            return {"started": False, "reason": capability["reason"]}
        spec = self._load_spec()
        projection = witness_projection(candidate, readiness)
        try:
            product, project, source = self._assembly(
                candidate, spec, witnessed=projection["witness"])
        except Exception as exc:
            return {"started": False, "reason": type(exc).__name__}
        proposal_id = _digest({
            "candidate": candidate.get("key"),
            "updated": candidate.get("updated"),
            "state_ref": product.state_ref,
        })
        run_id = f"writing-desk-{proposal_id}"
        options = (
            ["quiet", "start"] if candidate.get("source") == "writing_desk_seed"
            else ["quiet", "revise", "complete", "pause", "abandon"])
        episode = (
            self.choice_ledger.open_fork(
                owner="writing_desk", run_id=run_id, candidate=candidate,
                options=options, projection=projection)
            if projection["witness"] else None)
        episode_id = (episode or {}).get("episode_id")
        adapter = self._model_adapter(spec)
        identity = dict(spec.get("identity") or {})

        async def runner(context):
            cycle_id = new_cycle_id()
            events = []
            with model_call_scope(
                    cycle_id=cycle_id,
                    persona=getattr(self.engine, "persona", "unknown"),
                    purpose="writing_desk"):
                try:
                    events = [event async for event in adapter.events(
                        product.assembly, tools=(), exchanges=(),
                        max_tokens=self.config.max_tokens,
                        temperature=product.temperature,
                        cancel=context.cancellation)]
                    usage = self._usage(events)
                    attempts = 1 + len(getattr(
                        getattr(adapter, "event_transport", None),
                        "last_attempt_receipts", ()) or ())
                    record_model_call(
                        str(identity.get("provider") or "unknown"),
                        str(identity.get("endpoint") or self.config.model),
                        {**usage, "attempts": attempts}, status="ok")
                    text = collect_legacy_text(events, context.cancellation)
                except Exception as exc:
                    record_model_call(
                        str(identity.get("provider") or "unknown"),
                        str(identity.get("endpoint") or self.config.model),
                        {"error_type": type(exc).__name__}, status="failed")
                    raise
            context.cancellation.raise_if_cancelled()
            proposals = parse_desk_movements(text)
            envelope = InteriorWorkEnvelope.from_readiness(
                readiness, response_tokens=self.config.max_tokens)
            admitted_proposals = []
            for proposal in proposals:
                if not envelope.admit(proposal):
                    break
                admitted_proposals.append(proposal)
                if proposal["action"] in {
                        "quiet", "complete", "pause", "abandon"}:
                    break
            if not admitted_proposals:
                raise ValueError("interior work envelope admitted no movement")
            if candidate.get("source") == "writing_desk_seed":
                admitted_proposals = admitted_proposals[:1]
            proposal = admitted_proposals[0]
            if episode_id:
                self.choice_ledger.commit_choice(
                    episode_id, action=proposal["action"],
                    orientation=proposal.get("orientation") or "")
            movements = []
            current_project = project
            try:
                for index, movement in enumerate(admitted_proposals):
                    movement_run_id = (
                        context.run_id if index == 0
                        else f"{context.run_id}:movement:{index + 1}")
                    outcome, record = self._commit(
                        context, candidate, movement, current_project, source,
                        run_id=movement_run_id)
                    movements.append({
                        "outcome": outcome, "record": record,
                        "run_id": movement_run_id})
                    if record.get("project_id"):
                        current_project = self.desk.project(
                            record["project_id"], include_content=True)
            except Exception as exc:
                if episode_id:
                    self.choice_ledger.settle_owner(
                        episode_id, accepted=False, outcome="rejected",
                        reason=f"{type(exc).__name__}: {exc}")
                    raise OwnerChoiceRejected(
                        episode_id, f"{type(exc).__name__}: {exc}") from exc
                raise
            outcome = movements[-1]["outcome"]
            record = movements[-1]["record"]
            if episode_id:
                self.choice_ledger.settle_owner(
                    episode_id, accepted=True, outcome=outcome,
                    durable_ref=str(record.get("project_id") or ""))
            usage = self._usage(events)
            return AgencyRunOutcome(
                result={"outcome": outcome, "record": record,
                        "movements": movements,
                        "movement_count": len(movements),
                        "work_envelope": envelope.status(),
                        "choice_episode_id": episode_id,
                        "usage": usage,
                        "provider_http_attempts": attempts},
                metrics={"model_requests": 1,
                         "provider_http_attempts": 1 + len(getattr(
                             getattr(adapter, "event_transport", None),
                             "last_attempt_receipts", ()) or ()),
                         **usage})

        try:
            future = self.controller.start(
                run_id, runner, proposal_id=proposal_id,
                interruptible=False)
        except Exception as exc:
            return {"started": False, "reason": type(exc).__name__}
        future.add_done_callback(lambda done: self._completed(
            run_id, proposal_id, candidate, readiness, capability, done))
        self._emit(
            "writing_desk_proposed", run_id=run_id,
            proposal_id=proposal_id, candidate_key=candidate.get("key"),
            model=self.config.model, locality=capability.get("locality"))
        return {"started": True, "run_id": run_id,
                "proposal_id": proposal_id, "future": future}

    def _completed(self, run_id: str, proposal_id: str,
                   candidate: Mapping[str, Any], readiness: Mapping[str, Any],
                   capability: Mapping[str, Any], future) -> None:
        try:
            outcome = future.result()
            result = dict(getattr(outcome, "result", {}) or {})
        except Exception as exc:
            if isinstance(exc, OwnerChoiceRejected):
                self._effects.put({
                    "kind": "settled", "run_id": run_id,
                    "proposal_id": proposal_id, "candidate": dict(candidate),
                    "outcome": "owner_rejected", "project_id": None,
                    "record_digest": _digest({
                        "episode_id": exc.episode_id,
                        "reason": str(exc)}),
                    "choice_episode_id": exc.episode_id,
                    "usage": {}, "provider_http_attempts": 1,
                    "model": self.config.model,
                    "provider": capability.get("provider"),
                    "locality": capability.get("locality"),
                    "readiness": readiness.get("readiness", 0.0),
                })
                return
            self._effects.put({
                "kind": "retry", "run_id": run_id,
                "proposal_id": proposal_id, "candidate": dict(candidate),
                "reason": ("interrupted" if isinstance(
                    exc, concurrent.futures.CancelledError)
                    else f"failed:{type(exc).__name__}"),
            })
            return
        record = dict(result.get("record") or {})
        usage = dict(result.get("usage") or {})
        effect = {
            "kind": "settled", "run_id": run_id,
            "proposal_id": proposal_id, "candidate": dict(candidate),
            "outcome": result.get("outcome") or "quiet",
            "movement_count": int(result.get("movement_count") or 1),
            "work_envelope": dict(result.get("work_envelope") or {}),
            "project_id": record.get("project_id"),
            "record_digest": _digest(record),
            "choice_episode_id": result.get("choice_episode_id"),
            "usage": usage,
            "provider_http_attempts": int(
                result.get("provider_http_attempts") or 1),
            "model": self.config.model,
            "provider": capability.get("provider"),
            "locality": capability.get("locality"),
            "readiness": readiness.get("readiness", 0.0),
        }
        self._effects.put(effect)
        self._emit(
            "writing_desk_effect_ready", run_id=run_id,
            proposal_id=proposal_id, outcome=effect["outcome"],
            project_id=effect.get("project_id"))

    def drain_effects(self, field, *, now: float = None) -> list[dict]:
        now = time.time() if now is None else float(now)
        admitted = []
        while True:
            try:
                effect = self._effects.get_nowait()
            except queue.Empty:
                break
            if effect["kind"] == "retry":
                candidate = dict(effect["candidate"])
                field.pressure.refund()
                restored = field.queue.put(
                    candidate, float(candidate.get("salience", 0.05)),
                    now=now, offer_meta={
                        "operation": "requeued", "reason": effect["reason"]})
                admitted.append(restored)
                continue
            source_candidate = dict(effect["candidate"])
            project_satiety = field.satiate(source_candidate, now=now)
            prior_desk_satiety = field.satiety.warmth("writing_desk", now)
            desk_satiety = field.satiety.touch(
                "writing_desk",
                max(0.0, min(1.0, float(
                    source_candidate.get("salience", 0.0)))),
                label="writing_desk", now=now)
            outcome = str(effect.get("outcome") or "quiet")
            if outcome == "quiet":
                event_text = (
                    "A private writing-desk pull settled without a project "
                    "change. Nothing was published, sent, or overwritten.")
                novelty = 0.0
            elif outcome == "owner_rejected":
                event_text = (
                    "A witnessed private writing choice was refused by the "
                    "Writing Desk owner. No project changed; the unresolved "
                    "choice and refusal remain durable.")
                novelty = .35
            else:
                event_text = (
                    f"A self-chosen private writing-desk action {outcome} "
                    "an owned project. Nothing was published, sent, deleted, "
                    "or overwritten.")
                novelty = 1.0
            felt = None
            try:
                felt = circulate_experienced_event(self.engine, event_text)
            except Exception as exc:
                self._emit(
                    "writing_desk_effect_failed", run_id=effect["run_id"],
                    error_type=f"felt_consequence:{type(exc).__name__}")
            usage = dict(effect.get("usage") or {})
            self.desk.record_receipt({
                "run_id": effect["run_id"],
                "candidate_key": source_candidate.get("key"),
                "outcome": outcome, "project_id": effect.get("project_id"),
                "seed_id": source_candidate.get("seed_id"),
                "model": effect.get("model"),
                "provider": effect.get("provider"),
                "locality": effect.get("locality"),
                "model_requests": 1,
                "movement_count": effect.get("movement_count", 1),
                "work_envelope": effect.get("work_envelope", {}),
                "provider_http_attempts": effect.get(
                    "provider_http_attempts", 1),
                **usage, "estimated_cost_usd": 0.0,
                "readiness": effect.get("readiness"),
                "source_satiety": project_satiety,
                "desk_satiety": desk_satiety,
            })
            if self.internal_outcome_sink is not None \
                    and source_candidate.get("seed_id"):
                try:
                    self.internal_outcome_sink(
                        source_candidate["seed_id"],
                        run_id=effect["run_id"], outcome=outcome,
                        durable_ref=effect.get("project_id") or "",
                        usage={**usage, "estimated_cost_usd": 0.0})
                except ValueError:
                    pass
            candidate = field.offer_cognitive_event(
                "writing_desk_effect", event_text,
                {"novelty": novelty,
                 "affect_change": _finite((felt or {}).get(
                     "affect_change"), 0.0),
                 "body_intensity": 0.0, "relationship": 0.0,
                 "unresolved": 0.0},
                key=f"writing_desk_effect:{effect['run_id']}", now=now,
                raw_ref=effect.get("record_digest"),
                ownership="persona_private",
                receipts=[effect.get("record_digest")])
            if effect.get("choice_episode_id"):
                self.choice_ledger.encounter_consequence(
                    effect["choice_episode_id"],
                    candidate_key=str(candidate.get("key") or ""))
                candidate["choice_episode_id"] = effect["choice_episode_id"]
            admitted.append(candidate)
            self._emit(
                "writing_desk_field_reentry", run_id=effect["run_id"],
                outcome=outcome, candidate_key=candidate.get("key"),
                project_id=effect.get("project_id"),
                desk_satiety_before=prior_desk_satiety,
                desk_satiety_after=desk_satiety)
        for episode in self.choice_ledger.pending_consequences(
                "writing_desk"):
            outcome = str(episode.get("outcome") or "unknown")
            accepted = bool(episode.get("accepted"))
            event_text = (
                f"A previously witnessed private writing choice returned after "
                f"restart. Its owner {'accepted' if accepted else 'refused'} "
                f"the selected branch; the durable outcome is {outcome}.")
            try:
                felt = circulate_experienced_event(self.engine, event_text)
            except Exception:
                felt = {}
            candidate = field.offer_cognitive_event(
                "choice_consequence", event_text,
                {"novelty": .35,
                 "affect_change": _finite((felt or {}).get(
                     "affect_change"), 0.0),
                 "body_intensity": _finite((felt or {}).get(
                     "body_change"), 0.0),
                 "relationship": 0.0, "unresolved": 0.0},
                key=f"choice_consequence:{episode['episode_id']}", now=now,
                raw_ref=episode["episode_id"], ownership="persona_private",
                receipts=[episode["episode_id"]])
            candidate["choice_episode_id"] = episode["episode_id"]
            self.choice_ledger.encounter_consequence(
                episode["episode_id"],
                candidate_key=str(candidate.get("key") or ""))
            admitted.append(candidate)
        if admitted:
            field.save(now=now)
            if self._observer is not None:
                self._observer.field_snapshot(field, now)
        return admitted

    def status(self) -> dict:
        return {
            "enabled": "writing_desk" in getattr(
                self.engine, "enabled", set()),
            "config": {
                "model": self.config.model,
                "authority_tier": self.config.authority_tier,
                "local_only": self.config.local_only,
                "max_tokens": self.config.max_tokens,
            },
            "capability": self.capability(),
            "controller": self.controller.status(),
            "readiness": self.readiness(
                getattr(self.engine, "idle_metabolism", None)),
            "desk": self.desk.status(),
            "choice_junction": self.choice_ledger.status(),
        }
