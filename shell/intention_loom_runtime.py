"""DMN-owned, local-only continuity-of-intention motor.

The runtime owns no timer and no second attention field.  Possibility cues and
open intentions recur only at a genuine DMN fire, compete with every other
pull, and permit at most one host-validated append-only loom movement.  IL1
does not execute projects or expose tools, messages, publication, or any
external effect.
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
from core.intention_loom import IntentionLoom
from harness.model_call_receipts import (
    model_call_scope, new_cycle_id, record_model_call,
)
from shell.agency_controller import AgencyRunOutcome
from shell.autonomy_circulation import (
    circulate_experienced_event, readiness_from_engine,
)


LOOM_SOURCES = frozenset({"intention_cue", "intention_open"})
LOOM_AUTHORITY_TIER = 2
LOOM_ACTIONS = frozenset({
    "quiet", "form", "reframe", "pause", "resume", "satisfy", "release",
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
class IntentionLoomConfig:
    model: str
    authority_tier: int = 0
    local_only: bool = True
    max_tokens: int = 620

    def __post_init__(self):
        model = str(self.model or "").strip()
        if not model:
            raise ValueError("intention loom requires an explicit model")
        if not isinstance(self.authority_tier, int) \
                or isinstance(self.authority_tier, bool) \
                or not 0 <= self.authority_tier <= LOOM_AUTHORITY_TIER:
            raise ValueError("intention loom authority_tier must be 0 through 2")
        if type(self.local_only) is not bool:
            raise ValueError("intention loom local_only must be a bool")
        if not isinstance(self.max_tokens, int) \
                or not 256 <= self.max_tokens <= 1000:
            raise ValueError("intention loom max_tokens must be 256 through 1000")
        object.__setattr__(self, "model", model)


def resolve_intention_loom_config(raw: Mapping[str, Any] | None,
                                  active_model: str) -> IntentionLoomConfig:
    raw = dict(raw or {})
    return IntentionLoomConfig(
        model=str(raw.get("model") or active_model or "").strip(),
        authority_tier=int(raw.get("authority_tier", 0)),
        local_only=bool(raw.get("local_only", True)),
        max_tokens=int(raw.get("max_tokens", 620)),
    )


def parse_intention_proposal(text: str) -> dict:
    """Extract one strict bounded proposal; model-shaped data is not authority."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.I)
    if fenced:
        text = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    proposal = None
    try:
        value, end = decoder.raw_decode(text)
        if isinstance(value, dict) and not text[end:].strip():
            proposal = value
    except (TypeError, ValueError):
        pass
    if proposal is None:
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
        raise ValueError("intention loom model did not return one JSON object")
    allowed = {
        "action", "title", "statement", "uncertainty_low",
        "uncertainty_high", "basis",
    }
    unknown = set(proposal) - allowed
    if unknown:
        raise ValueError(
            f"intention proposal contains unknown fields: {sorted(unknown)}")
    if set(proposal) != allowed:
        missing = sorted(allowed - set(proposal))
        raise ValueError(
            f"intention proposal is missing required fields: {missing}")
    action = str(proposal.get("action") or "").strip().casefold()
    if action not in LOOM_ACTIONS:
        raise ValueError("intention proposal action is invalid")
    title = str(proposal.get("title") or "").strip()
    statement = str(proposal.get("statement") or "").strip()
    basis = str(proposal.get("basis") or "").strip()
    low = _finite(proposal.get("uncertainty_low"), -1.0)
    high = _finite(proposal.get("uncertainty_high"), -1.0)
    if action in {"form", "reframe"}:
        if not title or not statement or not basis:
            raise ValueError(
                "forming or reframing an intention requires title, statement, and basis")
        if not 0.0 <= low <= high <= 1.0:
            raise ValueError("intention uncertainty range is invalid")
    else:
        if title or statement or low != 0.0 or high != 0.0:
            raise ValueError(
                "non-wording intention actions must leave wording empty and uncertainty zero")
        if action in {"pause", "resume", "satisfy", "release"} and not basis:
            raise ValueError("intention state change requires a concise basis")
    return {
        "action": action, "title": title, "statement": statement,
        "uncertainty_low": low, "uncertainty_high": high,
        "basis": basis,
    }


class IntentionLoomRuntime:
    """One persona's local appraisal, append-only commit, and return owner."""

    def __init__(self, engine, controller, raw_config=None, *,
                 loom: IntentionLoom = None,
                 adapter_factory: Callable = None,
                 spec_loader: Callable = None):
        self.engine = engine
        self.controller = controller
        self.config = resolve_intention_loom_config(
            raw_config, getattr(engine, "model", ""))
        self.loom = loom or IntentionLoom(engine.pdir)
        self._adapter_factory = adapter_factory
        self._spec_loader = spec_loader
        self._adapter = None
        self._effects = queue.Queue()
        self._observer = getattr(engine, "salience_observer", None)
        self._last_readiness = None

    def _emit(self, kind: str, **payload) -> None:
        observer = self._observer
        if observer is None:
            return
        try:
            callback = getattr(observer, "autonomy_transition", None)
            if callback is not None:
                callback(kind, time.time(), **payload)
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
        enabled = "intention_loom" in getattr(self.engine, "enabled", set())
        volitional_offer = "offer_intention" in getattr(
            self.engine, "_volitional_actions", {})
        if not enabled:
            return {
                "usable": False, "reason": "intention_loom organ is disabled",
                "model": self.config.model, "locality": "unknown",
                "provider": None, "event_bridge": False,
                "volitional_offer": volitional_offer,
                "paid_fallbacks": 0,
            }
        try:
            spec = self._load_spec()
            identity = dict(spec.get("identity") or {})
            locality = str(identity.get("locality") or "unknown")
            adapter = self._model_adapter(spec)
            event_bridge = callable(getattr(adapter, "events", None))
            authority = self.config.authority_tier >= LOOM_AUTHORITY_TIER
            local_admitted = locality == "local" or not self.config.local_only
            usable = authority and local_admitted and event_bridge
            if not authority:
                reason = "intention authority tier does not admit private ledger writes"
            elif not local_admitted:
                reason = "IL1 refuses non-local intention models"
            elif not event_bridge:
                reason = "intention model lacks the interruptible event bridge"
            else:
                reason = "local interruptible intention path admitted"
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
                "reason": f"intention model unavailable: {type(exc).__name__}",
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
        return str(dict(candidate or {}).get("source") or "") in LOOM_SOURCES

    @staticmethod
    def _subject(candidate: Mapping[str, Any]) -> tuple[str, str]:
        candidate = dict(candidate or {})
        if candidate.get("source") == "intention_cue":
            return "cue", str(candidate.get("cue_id") or "")
        return "intention", str(candidate.get("intention_id") or "")

    def selection_score(self, field, candidate: Mapping[str, Any], *,
                        now: float, readiness: Mapping[str, Any] = None):
        state = dict(readiness or self.readiness(field))
        eligible = self.eligible(candidate) \
            and "intention_loom" in getattr(self.engine, "enabled", set()) \
            and not state.get("hard_blocked")
        loom_satiety = field.satiety.warmth("intention_loom", now)
        value = (max(0.0, min(1.0, _finite(state.get("readiness"))))
                 / (1.0 + loom_satiety) if eligible else 0.0)
        score, meta = field.attention_score(
            dict(candidate), now=now,
            action_readiness=value, action_eligible=eligible)
        kind, subject_id = self._subject(candidate)
        attention = self.loom.attention_stats().get(subject_id, {})
        return score, {
            **meta, "intention_eligible": eligible,
            "intention_readiness": round(value, 6),
            "intention_loom_satiety": round(loom_satiety, 6),
            "intention_subject_kind": kind,
            "intention_exposures": int(attention.get("exposures", 0)),
            "intention_selections": int(attention.get("selections", 0)),
            "intention_unselected_exposures": int(
                attention.get("unselected_exposures", 0)),
            "neglect_changes_selection": False,
        }

    def _offer_cue(self, field, cue: Mapping[str, Any], *, now: float):
        ownership = str(cue.get("ownership") or "human_offered")
        if ownership == "persona_private":
            description = (
                f"A private thought actually occurred and may or may not carry "
                f"continuing intention: {cue.get('label') or 'unnamed thought'}")
        else:
            description = (
                f"A human-offered possibility named "
                f"{cue.get('label') or 'unnamed possibility'} is available. "
                "It is not an assignment or an intention yet.")
        continuity = {
            name: max(0.0, min(1.0, _finite(
                dict(cue.get("continuity") or {}).get(name))))
            for name in (
                "novelty", "affect_change", "body_intensity",
                "relationship", "unresolved")
        }
        candidate = field.offer_cognitive_event(
            "intention_cue", description,
            continuity,
            key=f"intention_cue:{cue['cue_id']}", now=now,
            raw_ref=cue.get("source_digest"), ownership=ownership,
            receipts=[cue.get("source_digest")])
        candidate.update({
            "cue_id": cue["cue_id"],
            "satiety_key": f"intention_cue:{cue['cue_id']}",
        })
        return candidate

    def _offer_intention(self, field, intention: Mapping[str, Any], *,
                         now: float):
        continuity = self.loom.continuity_for(intention["intention_id"])
        candidate = field.offer_cognitive_event(
            "intention_open",
            f"A self-owned intention remains {intention.get('state')}: "
            f"{intention.get('title') or intention['intention_id']}",
            continuity,
            key=f"intention_open:{intention['intention_id']}", now=now,
            raw_ref=intention["intention_id"], ownership="persona_private",
            receipts=[intention["intention_id"]])
        candidate.update({
            "intention_id": intention["intention_id"],
            "satiety_key": f"intention_open:{intention['intention_id']}",
        })
        return candidate

    def _record_exposure(self, candidate: Mapping[str, Any], now: float) -> None:
        kind, subject_id = self._subject(candidate)
        self.loom.record_attention(
            "attention_exposed", candidate_key=candidate.get("key"),
            subject_kind=kind, subject_id=subject_id, now=now)

    def refresh_pending(self, field, *, now: float = None) -> list[dict]:
        """Recur unresolved loom state only at the caller's true DMN fire."""
        now = time.time() if now is None else float(now)
        offered = []
        if "intention_loom" not in getattr(self.engine, "enabled", set()):
            return offered
        for cue in self.loom.pending_cues():
            candidate = self._offer_cue(field, cue, now=now)
            self._record_exposure(candidate, now)
            offered.append(candidate)
        for intention in self.loom.intentions():
            if intention.get("state") not in {"open", "paused"}:
                continue
            candidate = self._offer_intention(field, intention, now=now)
            self._record_exposure(candidate, now)
            offered.append(candidate)
        if offered:
            self._emit(
                "intention_loom_recurred", candidate_count=len(offered),
                candidate_keys=[value.get("key") for value in offered])
        return offered

    def admit_cue(self, field, label: str, content: str, *,
                  now: float = None, ownership: str = "human_offered",
                  source_ref: str = "", source_digest: str = "",
                  continuity: Mapping[str, Any] | None = None) -> dict:
        now = time.time() if now is None else float(now)
        record = self.loom.admit_cue(
            label, content, ownership=ownership, source_ref=source_ref,
            source_digest=source_digest, continuity=continuity)
        candidate = self._offer_cue(field, record, now=now)
        field.save(now=now)
        self._emit(
            "intention_cue_admitted", cue_id=record["cue_id"],
            candidate_key=candidate.get("key"), ownership=ownership,
            duplicate=record.get("duplicate", False))
        return {"record": record, "candidate": candidate}

    def admit_self_cue(self, field, thought: str, *, memory_id: str,
                       now: float = None,
                       continuity: Mapping[str, Any] | None = None) -> dict:
        """Admit a thought only after its lived recurrence supplied evidence."""
        thought = str(thought or "").strip()
        if not thought:
            raise ValueError("private intention cue thought must not be empty")
        label = " ".join(thought.split())[:120]
        source_digest = hashlib.sha256(
            thought.encode("utf-8")).hexdigest()
        return self.admit_cue(
            field, label, thought, now=now, ownership="persona_private",
            source_ref=str(memory_id or "")[:180],
            source_digest=source_digest, continuity=continuity)

    def resume_intention(self, field, intention_id: str, *,
                         now: float = None) -> dict:
        """Let a human re-offer a pause; only a later win may resume it."""
        now = time.time() if now is None else float(now)
        intention = self.loom.intention(intention_id)
        if intention.get("state") != "paused":
            raise ValueError("only a paused intention may be offered to return")
        candidate = self._offer_intention(field, intention, now=now)
        field.save(now=now)
        self._emit(
            "intention_loom_return_offered", intention_id=intention_id,
            candidate_key=candidate.get("key"), ownership="human_offered")
        return {"offered": True, "candidate": candidate}

    def _source_material(self, candidate: Mapping[str, Any]):
        candidate = dict(candidate or {})
        if candidate.get("source") == "intention_cue":
            cue = self.loom.cue(candidate.get("cue_id"), include_content=True)
            source = {
                "kind": "cue", "cue_id": cue["cue_id"],
                "source_ref": cue.get("source_ref"),
                "source_digest": cue.get("source_digest"),
                "ownership": cue.get("ownership"),
            }
            material = (
                f"Possibility label: {cue['label']}\n"
                f"Origin: {cue['ownership']}\n"
                "Possibility text:\n" + cue["content"])
            return None, source, material
        intention = self.loom.intention(candidate.get("intention_id"))
        source = {
            "kind": "intention", "intention_id": intention["intention_id"],
            "source_digest": intention["intention_id"],
            "ownership": "persona_private",
        }
        material = (
            f"Current title: {intention['title']}\n"
            f"Current wording: {intention['statement']}\n"
            f"Current uncertainty range: {intention['uncertainty']}\n"
            f"Current state: {intention['state']}\n"
            f"Revision count: {intention['revision_count']}\n"
            f"Last observed basis: {intention.get('basis') or ''}")
        return intention, source, material

    def _assembly(self, candidate: Mapping[str, Any], spec):
        intention, source, material = self._source_material(candidate)
        if intention is None:
            actions = "quiet or form"
            contract = (
                "A cue is evidence of a possibility, not evidence that you want it. "
                "Choose form only if a continuing intention actually appears present "
                "now. For form, provide a concise title, first-person descriptive "
                "statement, uncertainty_low/high, and a concise basis in the supplied "
                "cue and present state. Quiet means quiet for now, not permanent "
                "rejection; leave wording empty and describe only what was noticed "
                "in basis (or leave basis empty if nothing was articulable), with "
                "both uncertainty values zero.")
            summary = "A bounded possibility cue won shared attention."
        elif intention.get("state") == "paused":
            actions = "quiet, resume, satisfy, or release"
            contract = (
                "This intention was paused, not erased. Notice whether related lived "
                "evidence makes it present again. Resume only if movement is actually "
                "present now. Satisfy or release only as a description of its private "
                "state, never as a claim about outward completion. Quiet leaves its "
                "paused state unchanged. State movements require a concise observed "
                "basis; quiet may describe what was noticed. Leave wording empty and "
                "uncertainty values zero.")
            summary = (
                f"Paused intention {intention['intention_id']} returned through "
                "shared attention.")
        else:
            actions = "quiet, reframe, pause, satisfy, or release"
            contract = (
                "Notice what this recorded intention appears to be now; history is "
                "evidence, not an order to preserve it. Reframe only if its wording "
                "has materially changed; provide the new wording, uncertainty range, "
                "and basis. Pause, satisfy, or release require only a concise basis. "
                "Quiet leaves wording empty and uncertainty zero; basis may briefly "
                "describe what was noticed without changing state.")
            summary = f"Open intention {intention['intention_id']} won attention."
        task = (
            "This is your private Intention Loom. It records continuity without "
            "turning a possibility into a command or an intention into a project. "
            f"Choose exactly one action from: {actions}. {contract} Return exactly "
            "one JSON object with exactly these keys: action, title, statement, "
            "uncertainty_low, uncertainty_high, basis. Do not plan steps, use tools, "
            "message, publish, or claim any outward effect.")
        envelope = AgencyTaskEnvelope(
            task=task, source_kind=str(candidate.get("source")),
            source_ref=str(candidate.get("key")),
            source_digest=str(source.get("source_digest") or _digest(source)),
            source_summary=summary,
            source_ownership=str(source.get("ownership") or
                                 candidate.get("ownership") or
                                 "persona_private"),
            authority_tier=self.config.authority_tier,
        )
        product = self.engine.build_agency_snapshot(
            envelope, substrate_mode="on",
            external_demand_epoch=self.controller.live_epoch(),
            agency_spec=spec, agency_model=self.config.model)
        product.assembly.add(
            "intention_loom_material", material, priority=9, budget=1150)
        return product, intention, source

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

    def _commit(self, context, candidate, proposal, intention):
        action = proposal["action"]
        is_cue = candidate.get("source") == "intention_cue"
        if is_cue and action not in {"quiet", "form"}:
            raise ValueError("a possibility cue admits only quiet or form")
        current_state = None if is_cue else intention.get("state")
        allowed = ({"quiet", "resume", "satisfy", "release"}
                   if current_state == "paused" else
                   {"quiet", "reframe", "pause", "satisfy", "release"})
        if not is_cue and action not in allowed:
            raise ValueError("open intention proposal action is invalid")
        if action == "form":
            record = self.loom.form_intention(
                context.run_id, candidate["cue_id"],
                title=proposal["title"], statement=proposal["statement"],
                uncertainty_low=proposal["uncertainty_low"],
                uncertainty_high=proposal["uncertainty_high"],
                basis=proposal["basis"])
            return "formed", record
        if action == "reframe":
            record = self.loom.reframe_intention(
                context.run_id, intention["intention_id"],
                title=proposal["title"], statement=proposal["statement"],
                uncertainty_low=proposal["uncertainty_low"],
                uncertainty_high=proposal["uncertainty_high"],
                basis=proposal["basis"])
            return "reframed", record
        if action == "pause":
            return "paused", self.loom.pause_intention(
                context.run_id, intention["intention_id"],
                basis=proposal["basis"])
        if action == "resume":
            return "resumed", self.loom.resume_intention(
                context.run_id, intention["intention_id"])
        if action in {"satisfy", "release"}:
            resolution = "satisfied" if action == "satisfy" else "released"
            return resolution, self.loom.resolve_intention(
                context.run_id, intention["intention_id"],
                resolution=resolution, basis=proposal["basis"])
        if is_cue:
            record = self.loom.observe_cue(
                candidate["cue_id"], context.run_id,
                basis=proposal["basis"])
        else:
            record = self.loom.observe_intention(
                context.run_id, intention["intention_id"],
                basis=proposal["basis"])
        return "quiet", record

    def _candidate_current(self, candidate: Mapping[str, Any]) -> bool:
        source = str(dict(candidate or {}).get("source") or "")
        if source == "intention_cue":
            cue_id = candidate.get("cue_id")
            return cue_id in {
                value.get("cue_id") for value in self.loom.pending_cues()}
        if source == "intention_open":
            intention_id = candidate.get("intention_id")
            return intention_id in {
                value.get("intention_id") for value in self.loom.intentions()
                if value.get("state") in {"open", "paused"}}
        return False

    def start_candidate(self, candidate: Mapping[str, Any]) -> dict:
        candidate = dict(candidate or {})
        if not self.eligible(candidate):
            return {"started": False, "reason": "not_eligible"}
        if not self._candidate_current(candidate):
            return {"started": False, "reason": "stale_candidate"}
        readiness = self.readiness(getattr(self.engine, "idle_metabolism", None))
        if readiness.get("hard_blocked"):
            return {"started": False, "reason": "state_blocked",
                    "readiness": readiness}
        capability = self.capability()
        if not capability["usable"]:
            return {"started": False, "reason": capability["reason"]}
        spec = self._load_spec()
        try:
            product, intention, _source = self._assembly(candidate, spec)
        except Exception as exc:
            return {"started": False, "reason": type(exc).__name__}
        proposal_id = _digest({
            "candidate": candidate.get("key"),
            "updated": candidate.get("updated"),
            "state_ref": product.state_ref,
        })
        run_id = f"intention-loom-{proposal_id}"
        adapter = self._model_adapter(spec)
        identity = dict(spec.get("identity") or {})
        subject_kind, subject_id = self._subject(candidate)
        self.loom.record_attention(
            "attention_selected", candidate_key=candidate.get("key"),
            subject_kind=subject_kind, subject_id=subject_id,
            now=time.time())

        async def runner(context):
            cycle_id = new_cycle_id()
            events = []
            attempts = 1
            with model_call_scope(
                    cycle_id=cycle_id,
                    persona=getattr(self.engine, "persona", "unknown"),
                    purpose="intention_loom"):
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
            if context.live_epoch() != context.captured_epoch:
                raise concurrent.futures.CancelledError(
                    "external demand changed before intention commit")
            proposal = parse_intention_proposal(text)
            outcome, record = self._commit(
                context, candidate, proposal, intention)
            usage = self._usage(events)
            return AgencyRunOutcome(
                result={"outcome": outcome, "record": record,
                        "usage": usage,
                        "provider_http_attempts": attempts},
                metrics={"model_requests": 1,
                         "provider_http_attempts": attempts, **usage})

        try:
            future = self.controller.start(
                run_id, runner, proposal_id=proposal_id)
        except Exception as exc:
            return {"started": False, "reason": type(exc).__name__}
        future.add_done_callback(lambda done: self._completed(
            run_id, proposal_id, candidate, readiness, capability, done))
        self._emit(
            "intention_loom_proposed", run_id=run_id,
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
            self._effects.put({
                "kind": "retry", "run_id": run_id,
                "proposal_id": proposal_id, "candidate": dict(candidate),
                "reason": ("interrupted" if isinstance(
                    exc, concurrent.futures.CancelledError)
                    else f"failed:{type(exc).__name__}"),
            })
            return
        record = dict(result.get("record") or {})
        self._effects.put({
            "kind": "settled", "run_id": run_id,
            "proposal_id": proposal_id, "candidate": dict(candidate),
            "outcome": result.get("outcome") or "quiet",
            "intention_id": record.get("intention_id")
                or candidate.get("intention_id"),
            "cue_id": candidate.get("cue_id"),
            "record_digest": _digest(record),
            "usage": dict(result.get("usage") or {}),
            "provider_http_attempts": int(
                result.get("provider_http_attempts") or 1),
            "model": self.config.model,
            "provider": capability.get("provider"),
            "locality": capability.get("locality"),
            "readiness": readiness.get("readiness", 0.0),
        })

    @staticmethod
    def _event_text(outcome: str, intention_id: str | None) -> str:
        if outcome == "quiet":
            return (
                "A private possibility or intention was encountered and left "
                "unchanged for now. Nothing was planned, sent, or changed outside "
                "the loom.")
        if outcome == "formed":
            return (
                "A continuing intention was privately formed and recorded. "
                "It names what appeared to matter; it did not begin a project "
                "or authorize an action.")
        if outcome == "reframed":
            return (
                "A private intention was encountered again and its wording changed. "
                "Its earlier wording remains history; no project or outward action began.")
        if outcome == "paused":
            return (
                "A private intention was paused. Its history remains and related "
                "lived evidence may bring it through attention again.")
        if outcome == "resumed":
            return (
                "A paused private intention appeared to move again and was resumed. "
                "This did not authorize a project or outward action.")
        if outcome == "satisfied":
            return (
                "A private intention appeared satisfied and was recorded as settled. "
                "No external completion was claimed.")
        return (
            "A private intention was released. Its history remains without requiring "
            "continuation or claiming an outward effect.")

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
            source_satiety = field.satiate(source_candidate, now=now)
            prior_loom_satiety = field.satiety.warmth("intention_loom", now)
            loom_satiety = field.satiety.touch(
                "intention_loom",
                max(0.0, min(1.0, float(
                    source_candidate.get("salience", 0.0)))),
                label="intention_loom", now=now)
            outcome = str(effect.get("outcome") or "quiet")
            event_text = self._event_text(
                outcome, effect.get("intention_id"))
            felt = None
            try:
                felt = circulate_experienced_event(self.engine, event_text)
            except Exception as exc:
                self._emit(
                    "intention_loom_effect_failed", run_id=effect["run_id"],
                    error_type=f"felt_consequence:{type(exc).__name__}")
            usage = dict(effect.get("usage") or {})
            continuity = {
                "novelty": 1.0 / (1.0 + source_satiety),
                "affect_change": _finite((felt or {}).get(
                    "affect_change"), 0.0),
                "body_intensity": _finite((felt or {}).get(
                    "body_change"), 0.0),
                "relationship": _finite((source_candidate.get(
                    "features") or {}).get("relationship"), 0.0),
                "unresolved": 1.0 if outcome in {
                    "formed", "reframed", "resumed"} else 0.0,
            }
            self.loom.record_receipt({
                "kind": "run", "run_id": effect["run_id"],
                "candidate_key": source_candidate.get("key"),
                "outcome": outcome,
                "intention_id": effect.get("intention_id"),
                "cue_id": effect.get("cue_id"),
                "model": effect.get("model"),
                "provider": effect.get("provider"),
                "locality": effect.get("locality"),
                "model_requests": 1,
                "provider_http_attempts": effect.get(
                    "provider_http_attempts", 1),
                **usage, "estimated_cost_usd": 0.0,
                "readiness": effect.get("readiness"),
                "source_satiety": source_satiety,
                "loom_satiety": loom_satiety,
                **continuity,
            })
            candidate = field.offer_cognitive_event(
                "intention_effect", event_text,
                continuity,
                key=f"intention_effect:{effect['run_id']}", now=now,
                raw_ref=effect.get("record_digest"),
                ownership="persona_private",
                receipts=[effect.get("record_digest")])
            candidate.update({
                "intention_id": effect.get("intention_id"),
                "intention_movement": outcome,
                "intention_record_digest": effect.get("record_digest"),
            })
            admitted.append(candidate)
            self._emit(
                "intention_loom_field_reentry", run_id=effect["run_id"],
                outcome=outcome, candidate_key=candidate.get("key"),
                intention_id=effect.get("intention_id"),
                loom_satiety_before=prior_loom_satiety,
                loom_satiety_after=loom_satiety)
        if admitted:
            field.save(now=now)
            if self._observer is not None:
                self._observer.field_snapshot(field, now)
        return admitted

    def status(self) -> dict:
        return {
            "enabled": "intention_loom" in getattr(
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
            "loom": self.loom.status(),
        }
