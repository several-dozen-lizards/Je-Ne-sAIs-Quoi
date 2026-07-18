"""Shared-field autonomous SVG creation for the persona-private atelier.

The local model may describe one proposed artifact after an atelier seed wins
ordinary attention.  The host remains the authority boundary: it accepts only
quiet or one validated SVG artifact, performs no fallback provider call, and
returns the lived consequence to the same field that selected it.
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
from core.atelier import Atelier
from harness.model_call_receipts import (
    model_call_scope, new_cycle_id, record_model_call,
)
from shell.agency_controller import AgencyRunOutcome
from shell.autonomy_circulation import (
    circulate_experienced_event, readiness_from_engine,
)


ATELIER_SOURCES = frozenset({"atelier_seed"})
ATELIER_AUTHORITY_TIER = 2
ATELIER_ACTIONS = frozenset({"quiet", "create_svg"})


def _digest(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          default=str, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]


def _finite(value: Any, fallback=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return number if math.isfinite(number) else float(fallback)


@dataclass(frozen=True)
class AtelierConfig:
    model: str
    authority_tier: int = 0
    local_only: bool = True
    max_tokens: int = 3600

    def __post_init__(self):
        model = str(self.model or "").strip()
        if not model:
            raise ValueError("atelier requires an explicit model")
        if self.authority_tier not in {0, 1, 2}:
            raise ValueError("atelier authority_tier must be 0, 1, or 2")
        if type(self.local_only) is not bool:
            raise ValueError("atelier local_only must be a bool")
        if not 800 <= int(self.max_tokens) <= 6000:
            raise ValueError("atelier max_tokens must be 800 through 6000")
        object.__setattr__(self, "model", model)


def resolve_atelier_config(raw, active_model: str) -> AtelierConfig:
    raw = dict(raw or {})
    return AtelierConfig(
        model=str(raw.get("model") or active_model or ""),
        authority_tier=int(raw.get("authority_tier", 0)),
        local_only=bool(raw.get("local_only", True)),
        max_tokens=int(raw.get("max_tokens", 3600)),
    )


def parse_atelier_proposal(text: str) -> dict[str, str]:
    """Extract one exact host-shaped proposal; never execute model data."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""),
                  flags=re.I | re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        proposal = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("atelier model did not return one JSON object") from exc
    if not isinstance(proposal, dict):
        raise ValueError("atelier model did not return one JSON object")
    allowed = {"action", "title", "svg"}
    unknown = set(proposal) - allowed
    if unknown:
        raise ValueError(
            f"atelier proposal contains unknown fields: {sorted(unknown)}")
    if set(proposal) != allowed:
        raise ValueError("atelier proposal must contain action, title, and svg")
    action = str(proposal.get("action") or "").strip().casefold()
    if action not in ATELIER_ACTIONS:
        raise ValueError("atelier proposal action is invalid")
    value = {
        "action": action,
        "title": str(proposal.get("title") or "").strip(),
        "svg": str(proposal.get("svg") or "").strip(),
    }
    if action == "quiet" and (value["title"] or value["svg"]):
        raise ValueError("quiet atelier proposal must not carry an artifact")
    if action == "create_svg" and (not value["title"] or not value["svg"]):
        raise ValueError("SVG atelier proposal requires title and svg")
    return value


class AtelierRuntime:
    """One persona's local SVG proposal, commit, and field-return owner."""

    def __init__(self, engine, controller, raw_config=None, *,
                 atelier: Atelier = None, adapter_factory: Callable = None,
                 spec_loader: Callable = None):
        self.engine = engine
        self.controller = controller
        self.config = resolve_atelier_config(
            raw_config, getattr(engine, "model", ""))
        self.atelier = atelier or Atelier(engine.pdir)
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
        enabled = "atelier" in getattr(self.engine, "enabled", set())
        if not enabled:
            return {
                "usable": False, "reason": "atelier organ is disabled",
                "model": self.config.model, "locality": "unknown",
                "provider": None, "event_bridge": False,
                "media": ["svg"], "paid_fallbacks": 0,
            }
        try:
            spec = self._load_spec()
            identity = dict(spec.get("identity") or {})
            locality = str(identity.get("locality") or "unknown")
            adapter = self._model_adapter(spec)
            event_bridge = callable(getattr(adapter, "events", None))
            authority = self.config.authority_tier >= ATELIER_AUTHORITY_TIER
            local_admitted = locality == "local" or not self.config.local_only
            usable = authority and local_admitted and event_bridge
            if not authority:
                reason = "atelier authority tier does not admit private artifacts"
            elif not local_admitted:
                reason = "AT1 refuses non-local creative models"
            elif not event_bridge:
                reason = "atelier model lacks the interruptible event bridge"
            else:
                reason = "local interruptible SVG path admitted"
            return {
                "usable": usable, "reason": reason,
                "model": self.config.model, "locality": locality,
                "provider": identity.get("provider"),
                "event_bridge": event_bridge, "media": ["svg"],
                "paid_fallbacks": 0,
            }
        except Exception as exc:
            return {
                "usable": False,
                "reason": f"atelier model unavailable: {type(exc).__name__}",
                "model": self.config.model, "locality": "unknown",
                "provider": None, "event_bridge": False,
                "media": ["svg"], "paid_fallbacks": 0,
            }

    def readiness(self, field=None) -> dict:
        self._last_readiness = readiness_from_engine(self.engine, field)
        return dict(self._last_readiness)

    @staticmethod
    def eligible(candidate: Mapping[str, Any]) -> bool:
        return str(dict(candidate or {}).get("source") or "") in ATELIER_SOURCES

    def selection_score(self, field, candidate: Mapping[str, Any], *,
                        now: float, readiness: Mapping[str, Any] = None):
        state = dict(readiness or self.readiness(field))
        eligible = self.eligible(candidate) \
            and "atelier" in getattr(self.engine, "enabled", set()) \
            and not state.get("hard_blocked")
        atelier_satiety = field.satiety.warmth("atelier", now)
        readiness_value = (
            max(0.0, min(1.0, _finite(state.get("readiness"))))
            / (1.0 + atelier_satiety) if eligible else 0.0)
        score, meta = field.attention_score(
            dict(candidate), now=now,
            action_readiness=readiness_value,
            action_eligible=eligible)
        return score, {
            **meta, "atelier_eligible": eligible,
            "atelier_readiness": round(readiness_value, 6),
            "atelier_satiety": round(atelier_satiety, 6),
        }

    def _offer_seed(self, field, record: Mapping[str, Any], *, now: float):
        candidate = field.offer_cognitive_event(
            "atelier_seed",
            f"Human-admitted creative material named "
            f"{record.get('label') or 'untitled'} is waiting in the atelier.",
            {"novelty": 1.0, "affect_change": 0.0,
             "body_intensity": 0.0, "relationship": 1.0,
             "unresolved": 1.0},
            key=f"atelier_seed:{record['seed_id']}", now=now,
            raw_ref=record.get("source_digest"),
            ownership="human_admitted",
            receipts=[record.get("source_digest")])
        candidate.update({
            "seed_id": record["seed_id"],
            "satiety_key": f"atelier_seed:{record['seed_id']}",
        })
        return candidate

    def refresh_pending(self, field, *, now: float = None) -> list[dict]:
        """Recur unresolved material only at the caller's actual DMN fire."""
        now = time.time() if now is None else float(now)
        if "atelier" not in getattr(self.engine, "enabled", set()):
            return []
        offered = [self._offer_seed(field, seed, now=now)
                   for seed in self.atelier.pending_seeds()]
        if offered:
            self._emit(
                "atelier_recurred", candidate_count=len(offered),
                candidate_keys=[value.get("key") for value in offered])
        return offered

    def admit_seed(self, field, label: str, brief: str, *,
                   now: float = None) -> dict:
        now = time.time() if now is None else float(now)
        record = self.atelier.admit_seed(label, brief)
        candidate = self._offer_seed(field, record, now=now)
        field.save(now=now)
        self._emit(
            "atelier_seed_admitted", seed_id=record["seed_id"],
            candidate_key=candidate.get("key"),
            content_chars=record.get("chars", 0),
            duplicate=record.get("duplicate", False))
        return {"record": record, "candidate": candidate}

    def _expression_vector(self) -> dict[str, float]:
        values = {}
        for key, value in dict(getattr(self.engine, "cocktail", {}) or {}).items():
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                values[f"cocktail.{str(key)[:60]}"] = max(
                    0.0, min(1.0, float(value)))
        oscillator = getattr(self.engine, "osc", None)
        for key, value in dict(getattr(oscillator, "bands", {}) or {}).items():
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                values[f"band.{str(key)[:60]}"] = max(
                    0.0, min(1.0, float(value)))
        coherence = getattr(oscillator, "coherence", None)
        if callable(coherence):
            coherence = coherence()
        if isinstance(coherence, (int, float)) and math.isfinite(float(coherence)):
            values["band.coherence"] = max(0.0, min(1.0, float(coherence)))
        return values

    def _assembly(self, candidate: Mapping[str, Any], spec):
        seed = self.atelier.seed(candidate.get("seed_id"), include_brief=True)
        task = (
            "This material has won attention inside your private atelier. "
            "It is an invitation, not an order to perform. Notice what you "
            "are feeling now and what visual form, if any, seems to arise "
            "from the material. You may leave it quiet. Do not assign an "
            "emotion to yourself because the brief names one. If an SVG does "
            "take form, make one bounded static composition using only svg, "
            "g, defs, path, rect, circle, ellipse, line, polyline, polygon, "
            "text, tspan, linearGradient, radialGradient, stop, and clipPath. "
            "Use inline attributes only; no CSS, script, animation, event "
            "handlers, foreignObject, embedded media, external links, or "
            "remote references. Give the root a finite viewBox and canvas "
            "between 16 and 4096 units. Return exactly one JSON object with "
            "exactly these keys: action, title, svg. Action is quiet or "
            "create_svg. Quiet requires empty title and svg. create_svg "
            "requires a title and the complete SVG XML encoded as the JSON "
            "string. Nothing will be published, messaged, or installed."
        )
        source = {
            "kind": "seed", "seed_id": seed["seed_id"],
            "source_digest": seed["source_digest"],
            "candidate_key": candidate.get("key"),
            "candidate_salience": candidate.get("salience"),
        }
        envelope = AgencyTaskEnvelope(
            task=task, source_kind="atelier_seed",
            source_ref=str(candidate.get("key")),
            source_digest=seed["source_digest"],
            source_summary="Admitted material is available for possible SVG form.",
            source_ownership=str(candidate.get("ownership") or
                                 "human_admitted"),
            authority_tier=self.config.authority_tier,
        )
        product = self.engine.build_agency_snapshot(
            envelope, substrate_mode="on",
            external_demand_epoch=self.controller.live_epoch(),
            agency_spec=spec, agency_model=self.config.model)
        product.assembly.add(
            "atelier_material",
            f"Material label: {seed['label']}\n\n{seed['brief']}",
            priority=9, budget=1500)
        return product, source, self._expression_vector()

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

    def _commit(self, context, candidate, proposal, source, expression_vector):
        if proposal["action"] == "quiet":
            record = self.atelier.resolve_seed(
                candidate["seed_id"], context.run_id, "quiet")
            return "quiet", record
        record = self.atelier.create_svg(
            context.run_id, proposal["title"], proposal["svg"],
            source=source, expression_vector=expression_vector)
        self.atelier.resolve_seed(
            candidate["seed_id"], context.run_id, "artifact_created",
            artifact_id=record["artifact_id"])
        return "created_svg", record

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
            self._emit(
                "atelier_refused", reason=capability["reason"],
                candidate_key=candidate.get("key"), model=self.config.model)
            return {"started": False, "reason": capability["reason"]}
        spec = self._load_spec()
        try:
            product, source, expression_vector = self._assembly(candidate, spec)
        except Exception as exc:
            return {"started": False, "reason": type(exc).__name__}
        proposal_id = _digest({
            "candidate": candidate.get("key"),
            "updated": candidate.get("updated"),
            "state_ref": product.state_ref,
        })
        run_id = f"atelier-{proposal_id}"
        adapter = self._model_adapter(spec)
        identity = dict(spec.get("identity") or {})

        async def runner(context):
            cycle_id = new_cycle_id()
            events = []
            with model_call_scope(
                    cycle_id=cycle_id,
                    persona=getattr(self.engine, "persona", "unknown"),
                    purpose="atelier_svg"):
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
                    "external demand changed before atelier commit")
            proposal = parse_atelier_proposal(text)
            outcome, record = self._commit(
                context, candidate, proposal, source, expression_vector)
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
            "atelier_proposed", run_id=run_id, proposal_id=proposal_id,
            candidate_key=candidate.get("key"), model=self.config.model,
            locality=capability.get("locality"), medium="svg")
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
        record = dict(result.get("record") or {})
        self._effects.put({
            "kind": "settled", "run_id": run_id,
            "proposal_id": proposal_id, "candidate": dict(candidate),
            "outcome": result.get("outcome") or "quiet",
            "artifact_id": record.get("artifact_id"),
            "record_digest": _digest(record),
            "usage": dict(result.get("usage") or {}),
            "provider_http_attempts": int(
                result.get("provider_http_attempts") or 1),
            "model": self.config.model,
            "provider": capability.get("provider"),
            "locality": capability.get("locality"),
            "readiness": readiness.get("readiness", 0.0),
        })
        self._emit(
            "atelier_effect_ready", run_id=run_id,
            proposal_id=proposal_id, outcome=result.get("outcome"),
            artifact_id=record.get("artifact_id"), medium="svg")

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
            atelier_satiety = field.satiety.touch(
                "atelier", max(0.0, min(1.0, float(
                    source_candidate.get("salience", 0.0)))),
                label="atelier", now=now)
            outcome = str(effect.get("outcome") or "quiet")
            if outcome == "quiet":
                event_text = (
                    "A private atelier pull settled without an artifact. "
                    "Nothing was published, sent, or overwritten.")
                novelty = 0.0
            else:
                event_text = (
                    "A self-chosen private SVG artifact took form in the "
                    "atelier. It remains available to be seen; it was not "
                    "published, sent, installed, or made into memory.")
                novelty = 1.0
            felt = None
            try:
                felt = circulate_experienced_event(self.engine, event_text)
            except Exception as exc:
                self._emit(
                    "atelier_effect_failed", run_id=effect["run_id"],
                    error_type=f"felt_consequence:{type(exc).__name__}")
            usage = dict(effect.get("usage") or {})
            self.atelier.record_receipt({
                "run_id": effect["run_id"],
                "candidate_key": source_candidate.get("key"),
                "outcome": outcome, "artifact_id": effect.get("artifact_id"),
                "seed_id": source_candidate.get("seed_id"), "medium": "svg",
                "model": effect.get("model"),
                "provider": effect.get("provider"),
                "locality": effect.get("locality"), "model_requests": 1,
                "provider_http_attempts": effect.get(
                    "provider_http_attempts", 1),
                **usage, "estimated_cost_usd": 0.0,
                "readiness": effect.get("readiness"),
                "source_satiety": source_satiety,
                "atelier_satiety": atelier_satiety,
            })
            candidate = field.offer_cognitive_event(
                "atelier_effect", event_text,
                {"novelty": novelty,
                 "affect_change": _finite((felt or {}).get(
                     "affect_change"), 0.0),
                 "body_intensity": 0.0, "relationship": 0.0,
                 "unresolved": 0.0},
                key=f"atelier_effect:{effect['run_id']}", now=now,
                raw_ref=effect.get("artifact_id") or effect.get("record_digest"),
                ownership="persona_private",
                receipts=[effect.get("artifact_id")
                          or effect.get("record_digest")])
            admitted.append(candidate)
            self._emit(
                "atelier_field_reentry", run_id=effect["run_id"],
                outcome=outcome, candidate_key=candidate.get("key"),
                artifact_id=effect.get("artifact_id"),
                atelier_satiety=atelier_satiety)
        if admitted:
            field.save(now=now)
            if self._observer is not None:
                self._observer.field_snapshot(field, now)
        return admitted

    def status(self) -> dict:
        return {
            "enabled": "atelier" in getattr(self.engine, "enabled", set()),
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
            "atelier": self.atelier.status(),
        }
