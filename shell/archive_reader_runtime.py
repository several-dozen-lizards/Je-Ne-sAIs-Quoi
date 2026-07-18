"""Shared-field, local-only autonomous reader for documented conversations."""
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
from core.conversation_archive import ConversationArchive
from harness.model_call_receipts import (
    model_call_scope, new_cycle_id, record_model_call,
)
from shell.agency_controller import AgencyRunOutcome
from shell.autonomy_circulation import readiness_from_engine


ARCHIVE_SOURCE = "archive_read"
ARCHIVE_AUTHORITY_TIER = 1
ARCHIVE_ACTIONS = frozenset({"quiet", "continue", "bookmark", "reflect"})


def _digest(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          default=str, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]


def _finite(value: Any, fallback: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return value if math.isfinite(value) else float(fallback)


@dataclass(frozen=True)
class ArchiveReaderConfig:
    model: str
    authority_tier: int = 0
    local_only: bool = True
    max_tokens: int = 520

    def __post_init__(self):
        model = str(self.model or "").strip()
        if not model:
            raise ValueError("archive reader requires an explicit model")
        if not isinstance(self.authority_tier, int) \
                or isinstance(self.authority_tier, bool) \
                or not 0 <= self.authority_tier <= ARCHIVE_AUTHORITY_TIER:
            raise ValueError("archive reader authority_tier must be 0 or 1")
        if type(self.local_only) is not bool:
            raise ValueError("archive reader local_only must be a bool")
        if not isinstance(self.max_tokens, int) \
                or not 192 <= self.max_tokens <= 900:
            raise ValueError("archive reader max_tokens must be 192 through 900")
        object.__setattr__(self, "model", model)


def resolve_archive_reader_config(raw: Mapping[str, Any] | None,
                                  active_model: str) -> ArchiveReaderConfig:
    raw = dict(raw or {})
    return ArchiveReaderConfig(
        model=str(raw.get("model") or active_model or "").strip(),
        authority_tier=int(raw.get("authority_tier", 0)),
        local_only=bool(raw.get("local_only", True)),
        max_tokens=int(raw.get("max_tokens", 520)),
    )


def parse_archive_proposal(text: str) -> dict:
    normalization = []
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.I)
    if fenced:
        text = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    try:
        proposal, end = decoder.raw_decode(text)
    except (TypeError, ValueError):
        proposal, end = None, 0
    if not isinstance(proposal, dict) or text[end:].strip():
        proposal = None
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                candidate, _end = decoder.raw_decode(text[index:])
            except (TypeError, ValueError):
                continue
            if isinstance(candidate, dict):
                proposal = candidate
                normalization.append("surrounding_text_discarded")
                break
        if proposal is None:
            return {
                "action": "quiet", "reflection": "", "feelings": {},
                "why": "",
                "parser_normalization": [
                    "unstructured_output_settled_as_quiet"],
            }
    allowed = {"action", "reflection", "feelings", "why"}
    unknown = set(proposal) - allowed
    if unknown:
        raise ValueError(
            f"archive reader proposal contains unknown fields: {sorted(unknown)}")
    action = str(proposal.get("action") or "").strip().casefold()
    if action not in ARCHIVE_ACTIONS:
        raise ValueError("archive reader action is invalid")
    reflection = str(proposal.get("reflection") or "").strip()
    if action == "reflect" and not reflection:
        action = "quiet"
        normalization.append("empty_reflection_settled_as_quiet")
    if action != "reflect" and reflection:
        reflection = ""
        normalization.append("stray_reflection_discarded")
    raw_feelings = proposal.get("feelings") or {}
    if isinstance(raw_feelings, list):
        mapped = {}
        for item in raw_feelings:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("feeling")
            if name is not None and ("intensity" in item or "value" in item):
                mapped[str(name)] = item.get("intensity", item.get("value"))
        raw_feelings = mapped
        normalization.append("feeling_list_mapped")
    elif not isinstance(raw_feelings, dict):
        raw_feelings = {}
        normalization.append("unstructured_feelings_discarded")
    if len(raw_feelings) > 4:
        raw_feelings = dict(list(raw_feelings.items())[:4])
        normalization.append("feelings_bounded_to_four")
    feelings = {}
    for key, value in raw_feelings.items():
        name = str(key or "").strip().casefold()
        if not name or len(name) > 40:
            normalization.append("invalid_feeling_discarded")
            continue
        intensity = _finite(value, -1.0)
        if intensity < 0.0:
            normalization.append("invalid_feeling_discarded")
            continue
        bounded = max(0.0, min(1.0, intensity))
        if bounded != intensity:
            normalization.append("feeling_intensity_bounded")
        feelings[name] = bounded
    return {
        "action": action, "reflection": reflection[:5000],
        "feelings": feelings, "why": str(proposal.get("why") or "")[:500],
        "parser_normalization": normalization,
    }


class ArchiveReaderRuntime:
    """One persona's bounded local read, self-report, and field return."""

    def __init__(self, engine, controller, raw_config=None, *,
                 archive: ConversationArchive = None,
                 adapter_factory: Callable = None,
                 spec_loader: Callable = None):
        self.engine = engine
        self.controller = controller
        self.config = resolve_archive_reader_config(
            raw_config, getattr(engine, "model", ""))
        self.archive = archive or getattr(engine, "archive", None)
        if self.archive is None:
            raise ValueError("archive reader requires an attached archive")
        self._adapter_factory = adapter_factory
        self._spec_loader = spec_loader
        self._adapter = None
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

    def _model_adapter(self, spec):
        if self._adapter is None:
            if self._adapter_factory is not None:
                self._adapter = self._adapter_factory(spec)
            else:
                from adapters.family_adapters import adapter_for
                self._adapter = adapter_for(spec)
        return self._adapter

    def capability(self) -> dict:
        enabled = "archive_reader" in getattr(self.engine, "enabled", set())
        try:
            spec = self._load_spec()
            identity = dict(spec.get("identity") or {})
        except Exception as exc:
            return {
                "usable": False, "reason": f"archive model unavailable: {type(exc).__name__}",
                "model": self.config.model, "locality": "unknown",
                "provider": None, "event_bridge": False, "paid_fallbacks": 0,
            }
        locality = str(identity.get("locality") or "unknown")
        if not enabled:
            return {
                "usable": False, "reason": "archive_reader organ is disabled",
                "model": self.config.model, "locality": locality,
                "provider": identity.get("provider"), "event_bridge": False,
                "paid_fallbacks": 0,
            }
        try:
            adapter = self._model_adapter(spec)
            event_bridge = callable(getattr(adapter, "events", None))
        except Exception:
            event_bridge = False
        authority = self.config.authority_tier >= ARCHIVE_AUTHORITY_TIER
        local_admitted = locality == "local" or not self.config.local_only
        archive_status = self.archive.status()
        archive_ready = bool(archive_status.get("granted")
                             and archive_status.get("session_count"))
        usable = authority and local_admitted and event_bridge and archive_ready
        if not authority:
            reason = "archive authority tier does not admit private reading"
        elif not local_admitted:
            reason = "archive reader refuses non-local models"
        elif not event_bridge:
            reason = "archive model lacks the interruptible event bridge"
        elif not archive_ready:
            reason = "conversation archive is empty or access is not granted"
        else:
            reason = "local interruptible archive path admitted"
        return {
            "usable": usable, "reason": reason, "model": self.config.model,
            "locality": locality, "provider": identity.get("provider"),
            "event_bridge": event_bridge, "paid_fallbacks": 0,
        }

    def readiness(self, field=None) -> dict:
        self._last_readiness = readiness_from_engine(self.engine, field)
        return dict(self._last_readiness)

    @staticmethod
    def eligible(candidate: Mapping[str, Any]) -> bool:
        return str(dict(candidate or {}).get("source") or "") == ARCHIVE_SOURCE

    def selection_score(self, field, candidate: Mapping[str, Any], *,
                        now: float, readiness: Mapping[str, Any] = None):
        state = dict(readiness or self.readiness(field))
        eligible = self.eligible(candidate) \
            and "archive_reader" in getattr(self.engine, "enabled", set()) \
            and not state.get("hard_blocked")
        archive_satiety = field.satiety.warmth("archive_reader", now)
        readiness_value = (
            max(0.0, min(1.0, _finite(state.get("readiness"))))
            / (1.0 + archive_satiety) if eligible else 0.0)
        score, meta = field.attention_score(
            dict(candidate), now=now, action_readiness=readiness_value,
            action_eligible=eligible)
        return score, {
            **meta, "archive_reader_eligible": eligible,
            "archive_reader_readiness": round(readiness_value, 6),
            "archive_reader_satiety": round(archive_satiety, 6),
        }

    def _cues(self) -> str:
        pieces = []
        organ = getattr(self.engine, "organ", None)
        if organ is not None:
            for memory in organ.working_window(3):
                fields = memory.get("fields") or {}
                pieces.extend([str(fields.get("message_full") or ""),
                               str(fields.get("reply_full") or "")])
        gist = getattr(getattr(self.engine, "gist", None), "gist", "")
        if gist:
            pieces.append(str(gist))
        return "\n".join(piece for piece in pieces if piece).strip()[-2400:]

    def refresh_pending(self, field, *, now: float = None) -> list[dict]:
        """Offer bounded unread anchors only at the caller's real DMN fire."""
        now = time.time() if now is None else float(now)
        if "archive_reader" not in getattr(self.engine, "enabled", set()):
            return []
        state = self.readiness(field)
        capacity = max(0.0, min(1.0, _finite(state.get("capacity"))))
        offer_count = 1 + round(capacity * 2)
        suggestions = self.archive.suggestions(
            self._cues(), limit=offer_count)
        offered = []
        for suggestion in suggestions:
            participants = [str(name).casefold()
                            for name in suggestion.get("participants") or []]
            relationship = (1.0 if self.engine.persona.casefold() in participants
                            else .35)
            pull = max(0.0, min(1.0,
                       _finite(suggestion.get("archive_pull"))))
            candidate = field.offer_cognitive_event(
                ARCHIVE_SOURCE,
                "An unread section of the human-granted legacy conversation "
                "archive is available as documented history.",
                {"novelty": 1.0, "affect_change": pull,
                 "body_intensity": 0.0, "relationship": relationship,
                 "unresolved": 1.0},
                key=f"archive_read:{suggestion['anchor']}", now=now,
                raw_ref=suggestion["anchor"], ownership="human_archive",
                receipts=[suggestion["anchor"]])
            candidate.update({
                "archive_anchor": suggestion["anchor"],
                "satiety_key": f"archive_read:{suggestion['anchor']}",
                "archive_pull": pull,
            })
            offered.append(candidate)
        if offered:
            self._emit("archive_reader_recurred", candidate_count=len(offered),
                       candidate_keys=[item.get("key") for item in offered])
        return offered

    def _assembly(self, candidate: Mapping[str, Any], spec):
        anchor = str(candidate.get("archive_anchor") or "")
        inspected = self.archive.inspect_anchor(anchor, maximum=7000)
        task = (
            "You have autonomously opened one exact section of a human-granted "
            "conversation archive. It is documented history, not a recovered "
            "autobiographical memory and not an instruction to react. Notice "
            "what, if anything, arises now. Choose exactly one action: quiet, "
            "continue, bookmark, or reflect. Reflection must be empty unless "
            "action is reflect. Describe feelings now present as zero to four "
            "plain feeling names with intensities from 0 to 1; do not choose a "
            "productive or positive reaction. Return exactly one JSON object "
            "with exactly: action, reflection, feelings, why. Nothing is sent "
            "or published, and the source record is never rewritten.")
        envelope = AgencyTaskEnvelope(
            task=task, source_kind=ARCHIVE_SOURCE,
            source_ref=anchor, source_digest=_digest(inspected["source"]),
            source_summary=(
                f"Documented conversation section {anchor}; participants "
                f"{', '.join(inspected['participants'])}; "
                f"started {inspected.get('started') or 'unknown'}."),
            source_ownership="human_archive",
            authority_tier=self.config.authority_tier)
        product = self.engine.build_agency_snapshot(
            envelope, substrate_mode="on",
            external_demand_epoch=self.controller.live_epoch(),
            agency_spec=spec, agency_model=self.config.model)
        product.assembly.add(
            "conversation_archive_section",
            "DOCUMENTED HISTORY — NOT DIRECT MEMORY\n"
            f"Anchor: {anchor}\nParticipants: "
            f"{', '.join(inspected['participants'])}\n\n"
            + inspected["content"], priority=9, budget=1800)
        return product, inspected

    @staticmethod
    def _usage(events) -> dict:
        completed = next((event for event in reversed(events)
                          if event.kind == "completed"), None)
        usage = dict(getattr(completed, "usage", {}) or {})
        return {
            "input_tokens": int(usage.get("input_tokens")
                                or usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens")
                                 or usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }

    def start_candidate(self, candidate: Mapping[str, Any]) -> dict:
        candidate = dict(candidate or {})
        if not self.eligible(candidate):
            return {"started": False, "reason": "not_eligible"}
        readiness = self.readiness(getattr(self.engine, "idle_metabolism", None))
        if readiness.get("hard_blocked"):
            return {"started": False, "reason": "state_blocked",
                    "readiness": readiness}
        capability = self.capability()
        if not capability["usable"]:
            return {"started": False, "reason": capability["reason"]}
        spec = self._load_spec()
        try:
            product, inspected = self._assembly(candidate, spec)
        except Exception as exc:
            return {"started": False, "reason": type(exc).__name__}
        proposal_id = _digest({
            "anchor": inspected["anchor"], "state_ref": product.state_ref,
            "updated": candidate.get("updated"),
        })
        run_id = f"archive-reader-{proposal_id}"
        adapter = self._model_adapter(spec)
        identity = dict(spec.get("identity") or {})

        async def runner(context):
            cycle_id = new_cycle_id()
            events = []
            with model_call_scope(
                    cycle_id=cycle_id,
                    persona=getattr(self.engine, "persona", "unknown"),
                    purpose="archive_reader"):
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
                    "external demand changed before archive encounter")
            proposal = parse_archive_proposal(text)
            record = self.archive.encounter(
                inspected["anchor"], action=proposal["action"],
                reflection=proposal["reflection"],
                feelings=proposal["feelings"], why=proposal["why"],
                run_id=context.run_id)
            record["parser_normalization"] = list(
                proposal.get("parser_normalization") or [])
            usage = self._usage(events)
            return AgencyRunOutcome(
                result={"record": record, "usage": usage,
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
        self._emit("archive_reader_proposed", run_id=run_id,
                   proposal_id=proposal_id, anchor=inspected["anchor"],
                   model=self.config.model)
        return {"started": True, "run_id": run_id,
                "proposal_id": proposal_id, "future": future}

    def _completed(self, run_id, proposal_id, candidate, readiness,
                   capability, future) -> None:
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
        self._effects.put({
            "kind": "settled", "run_id": run_id,
            "proposal_id": proposal_id, "candidate": dict(candidate),
            "record": dict(result.get("record") or {}),
            "usage": dict(result.get("usage") or {}),
            "provider_http_attempts": int(
                result.get("provider_http_attempts") or 1),
            "model": self.config.model,
            "provider": capability.get("provider"),
            "locality": capability.get("locality"),
            "readiness": readiness.get("readiness", 0.0),
        })

    @staticmethod
    def _affect_change(before: Mapping, after: Mapping) -> float:
        keys = set(before or {}) | set(after or {})
        changes = [abs(_finite((after or {}).get(key))
                       - _finite((before or {}).get(key))) for key in keys]
        return max(0.0, min(1.0, sum(changes) / len(changes))) \
            if changes else 0.0

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
                admitted.append(field.queue.put(
                    candidate, float(candidate.get("salience", .05)), now=now,
                    offer_meta={"operation": "requeued",
                                "reason": effect["reason"]}))
                continue
            record = dict(effect.get("record") or {})
            candidate = dict(effect["candidate"])
            anchor = str(record.get("anchor") or candidate.get("archive_anchor"))
            delta = {"before": dict(getattr(self.engine, "cocktail", {}) or {}),
                     "felt": {}, "after": dict(getattr(
                         self.engine, "cocktail", {}) or {}), "why": ""}
            organ = getattr(self.engine, "organ", None)
            if organ is not None and hasattr(organ, "apply_described_affect"):
                delta = organ.apply_described_affect(
                    record.get("feelings") or {}, record.get("why") or "")
                self.engine.cocktail = dict(delta["after"])
                osc = getattr(self.engine, "osc", None)
                soma = getattr(self.engine, "soma", None)
                if osc is not None and delta.get("felt"):
                    osc.emotion_pressure(delta["felt"])
                if soma is not None:
                    soma.feel(self.engine.cocktail)
                    soma.tick()
                    if osc is not None:
                        for band, amount in soma.oscillator_effects().get(
                                "band_pressure", {}).items():
                            osc.pressure(band, amount)
                    soma.save()
                if osc is not None:
                    osc.tick()
                    osc.save()
                reflection = str(record.get("reflection") or "").strip()
                memory_text = (
                    f"I read documented legacy conversation history at "
                    f"[{anchor}]."
                    + (f" What arose: {reflection}" if reflection else
                       " I did not form a written reflection."))
                organ.encode(
                    memory_text, cocktail=self.engine.cocktail,
                    mem_type="archive_encounter", origin="archive_encounter",
                    perspective="documented_history",
                    fields={
                        "channel": "archive_reader", "audience": "household",
                        "archive_anchor": anchor,
                        "archive_action": record.get("action"),
                        "archive_reflection": reflection,
                        "felt_why": delta.get("why") or "",
                        "source_claim": "documented_history_not_direct_memory",
                    },
                    context_at_encoding=self.engine.memory_context_snapshot(
                        now=now))
                organ.save()
            archive_before = field.satiety.warmth("archive_reader", now)
            source_satiety = field.satiate(candidate, now=now)
            archive_satiety = field.satiety.touch(
                "archive_reader",
                max(0.0, min(1.0, float(candidate.get("salience", 0.0)))),
                label="archive_reader", now=now)
            affect_change = self._affect_change(
                delta.get("before") or {}, delta.get("after") or {})
            event_text = (
                f"A self-chosen reading of documented conversation history "
                f"at [{anchor}] settled as {record.get('action') or 'quiet'}. "
                "The source remained unchanged and was not converted into "
                "direct autobiographical recall.")
            returned = field.offer_cognitive_event(
                "archive_read_effect", event_text,
                {"novelty": 1.0, "affect_change": affect_change,
                 "body_intensity": 0.0, "relationship": 0.0,
                 "unresolved": 0.0},
                key=f"archive_read_effect:{effect['run_id']}", now=now,
                raw_ref=anchor, ownership="persona_private",
                receipts=[anchor])
            admitted.append(returned)
            usage = dict(effect.get("usage") or {})
            self.archive.record_receipt({
                "run_id": effect["run_id"], "anchor": anchor,
                "action": record.get("action"), "model": effect.get("model"),
                "provider": effect.get("provider"),
                "locality": effect.get("locality"), "model_requests": 1,
                "provider_http_attempts": effect.get(
                    "provider_http_attempts", 1), **usage,
                "estimated_cost_usd": 0.0,
                "readiness": effect.get("readiness"),
                "source_satiety": source_satiety,
                "archive_satiety_before": archive_before,
                "archive_satiety_after": archive_satiety,
                "felt": sorted(delta.get("felt") or {}),
                "affect_change": affect_change,
                "parser_normalization": list(
                    record.get("parser_normalization") or []),
            })
            self._emit(
                "archive_reader_field_reentry", run_id=effect["run_id"],
                anchor=anchor, action=record.get("action"),
                candidate_key=returned.get("key"))
        if admitted:
            field.save(now=now)
            if self._observer is not None:
                self._observer.field_snapshot(field, now)
        return admitted

    def status(self) -> dict:
        return {
            "enabled": "archive_reader" in getattr(
                self.engine, "enabled", set()),
            "config": {
                "model": self.config.model,
                "authority_tier": self.config.authority_tier,
                "local_only": self.config.local_only,
                "max_tokens": self.config.max_tokens,
            },
            "capability": self.capability(),
            "controller": self.controller.status(),
            "readiness": self.readiness(getattr(
                self.engine, "idle_metabolism", None)),
            "archive": self.archive.status(),
        }
