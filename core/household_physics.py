"""Composable, receipt-bearing physics for the shared household world.

This module is deliberately smaller than the Room.  The Room remains the
canonical geometry, body, event, and persistence authority; household
physics supplies a typed vocabulary for composing object use, situated
traces, voluntary agreements, and encounter-settled consequences.

The biological-sounding word "physics" is only a product metaphor here.  It
means explicit synthetic relationships with inspectable causes.  Nothing in
this module assigns a feeling, motive, belief, consent state, or memory to a
resident.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from copy import deepcopy


SCHEMA = "jnsq-household-physics/0.1"
STATUS = "experimental_reachable"

PRIMITIVES = (
    "move", "orient", "pose", "contact", "observe", "use", "write",
    "make", "give", "withdraw", "return_home",
    # portal (20260901): a body passes between worlds through a gate it
    # is standing at. Gated (unlike return_home), never a bedrock right.
    "portal",
)

EFFECT_BRICKS = (
    "set_scalar", "append_trace", "append_tombstone", "schedule",
    "check_state", "emit_event", "noop",
)

BEDROCK_RIGHTS = {
    "resident_not_property": (
        "A resident and their body can never be owned or transferred."),
    "private_interior_not_inherited": (
        "Owning a place or object grants no access to another resident's "
        "private interior, memory, or private drafts."),
    "return_home_unblockable": (
        "A present resident may return to their own den regardless of local "
        "recipes, agreements, or delegated grants."),
    "temporary_restraints_release": (
        "Any future restraint must be explicitly temporary and releasable; "
        "this version implements no restraint brick."),
    "no_prescribed_experience": (
        "Effects may change shared state but may not assign what a resident "
        "feels, believes, perceives, consents to, or remembers."),
    "audience_bounded_receipts": (
        "Exact words remain on their chosen surface and do not leak into "
        "content-free operational receipts."),
}

ROOM_SHARED_ACTIONS = {
    "move_to", "go", "walk", "look_at", "turn_toward", "look_around",
    "inspect", "sit", "stand", "lie_down", "rest", "gesture", "release_gesture",
    "body_motion", "reach", "poke", "release_reach", "light_on", "light_off", "contact", "read", "travel",
    "write", "say", "board_post", "board_read", "board_retract",
    "arc_open", "arc_contribute", "arc_consequence", "arc_bind_artifact",
    "arc_bind_outcome", "arc_withdraw", "arc_release", "use",
    "trace_leave", "trace_read", "trace_withdraw", "agreement_make",
    "agreement_sign", "agreement_withdraw", "agreement_release",
    "defer_effect", "return_home", "portal",
}

ORGAN_OWNED_ACTIONS = {
    "offer_intention", "offer_writing", "writing_save", "offer_research",
    "browse_research", "offer_atelier", "offer_latest_artifact",
    "journal", "journal_index", "journal_open", "legacy_evidence_search",
    "legacy_evidence_open", "legacy_evidence_previous",
    "legacy_evidence_next", "anthropic_conversation_search",
    "anthropic_conversation_open", "anthropic_conversation_previous",
    "anthropic_conversation_next", "research_report_open",
    "research_source_read", "writing_archive", "writing_restore",
    "hold_question", "curiosity_ask", "curiosity_defer",
    "curiosity_revise", "curiosity_release", "outcome_surface",
    "outcome_hold", "outcome_private", "time_mark", "time_release",
    "startup_handoff", "startup_handoff_clear", "observe_world",
    "awareness_release", "quiet_release", "memory_retain",
    "memory_withdraw", "memory_summarize", "memory_restore",
    "approve_altered_state", "decline_altered_state",
    "defer_altered_state", "end_altered_state",
    "workspace_list", "workspace_open", "workspace_create",
    "workspace_append", "workspace_edit",
}

ACTION_CLASSIFICATION = {
    **{action: "shared_world" for action in sorted(ROOM_SHARED_ACTIONS)},
    **{action: "organ_owned" for action in sorted(ORGAN_OWNED_ACTIONS)},
}

DEFERRED_SIGNALS = {
    "observation", "actor_present", "target_changed", "local_activity",
    "elapsed", "resource_ready",
}
NON_TIME_SIGNALS = DEFERRED_SIGNALS - {"elapsed"}
ALLOWED_DEFERRED_EFFECTS = {"set_scalar", "append_trace", "emit_event", "noop"}


class HouseholdPhysicsError(ValueError):
    """A refused household mutation.  Refusal is a truthful result."""


def _now() -> float:
    return time.time()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _bounded_text(value, *, field: str, maximum: int = 12000) -> str:
    text = str(value or "").strip()
    if not text:
        raise HouseholdPhysicsError(f"{field} cannot be empty")
    if len(text) > maximum:
        raise HouseholdPhysicsError(f"{field} is too long")
    return text


def _clean_name(value, *, field: str, maximum: int = 160) -> str:
    text = _bounded_text(value, field=field, maximum=maximum)
    if any(ord(char) < 32 for char in text):
        raise HouseholdPhysicsError(f"{field} contains control characters")
    return text


def _clean_string_list(values, *, field: str, maximum: int = 24) -> list:
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        raise HouseholdPhysicsError(f"{field} must be a list")
    result = []
    for value in values:
        clean = _clean_name(value, field=field)
        if clean not in result:
            result.append(clean)
    if len(result) > maximum:
        raise HouseholdPhysicsError(f"{field} has too many entries")
    return result


def _copy_json(value, *, field: str):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise HouseholdPhysicsError(f"{field} must be finite JSON") from error


def canonical_hash(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def physics_manifest() -> dict:
    """Machine-readable truth surface shared by API, docs, and tests."""
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "canonical_world": "room.state.Room",
        "primitives": list(PRIMITIVES),
        "effect_bricks": list(EFFECT_BRICKS),
        "bedrock_rights": dict(BEDROCK_RIGHTS),
        "action_classification": dict(ACTION_CLASSIFICATION),
        "pilots": ["light_recipe", "situated_trace", "voluntary_agreement",
                   "encounter_settlement"],
        "external_effects": {
            "implemented": False,
            "mcp_library_policy": "read_only",
            "grant_envelopes": "implemented_without_executor",
        },
    }


def default_light_physics() -> dict:
    return {
        "kind": "switchable_fixture",
        "revision": 1,
        "traits": {"reachable_use": True, "shared_state": True,
                   "scalar": "power"},
        "recipe": {
            "on": [{"effect": "set_scalar", "field": "power",
                    "value": 1.0}],
            "off": [{"effect": "set_scalar", "field": "power",
                     "value": 0.0}],
        },
    }


def validate_object_physics(kind, traits, recipe) -> tuple[str, dict, dict]:
    """Validate a bounded object recipe without executing it."""
    clean_kind = _clean_name(kind, field="physics kind", maximum=80)
    clean_traits = _copy_json(dict(traits or {}), field="physics traits")
    clean_recipe = _copy_json(dict(recipe or {}), field="physics recipe")
    if len(clean_recipe) > 24:
        raise HouseholdPhysicsError("physics recipe has too many modes")
    for mode, effects in clean_recipe.items():
        _clean_name(mode, field="recipe mode", maximum=80)
        if not isinstance(effects, list) or not effects:
            raise HouseholdPhysicsError(
                f"recipe mode '{mode}' needs one or more effects")
        if len(effects) > 12:
            raise HouseholdPhysicsError(
                f"recipe mode '{mode}' has too many effects")
        for effect in effects:
            if not isinstance(effect, dict):
                raise HouseholdPhysicsError("recipe effects must be objects")
            if effect.get("effect") not in {"set_scalar", "noop"}:
                raise HouseholdPhysicsError(
                    "object recipes may only set scalar state or do nothing")
            if effect.get("effect") == "set_scalar":
                if effect.get("field") not in {"power", "temperature_c"}:
                    raise HouseholdPhysicsError("unsupported scalar field")
                try:
                    value = float(effect.get("value"))
                except (TypeError, ValueError) as error:
                    raise HouseholdPhysicsError(
                        "scalar recipe value must be numeric") from error
                if not math.isfinite(value):
                    raise HouseholdPhysicsError(
                        "scalar recipe value must be finite")
    return clean_kind, clean_traits, clean_recipe


class HouseholdPhysicsState:
    """Durable room-local relationship history and projections."""

    def __init__(self, room_id: str):
        self.room_id = str(room_id)
        self.schema = SCHEMA
        self.resolutions = []
        self.traces = []
        self.trace_reads = {}
        self.agreements = []
        self.deferred = []

    def record_resolution(self, actor: str, primitive: str, *, target=None,
                          status: str, effect_count: int = 0,
                          source_action: str = "", reason: str = "") -> dict:
        if primitive not in PRIMITIVES:
            raise HouseholdPhysicsError(f"unknown primitive '{primitive}'")
        record = {
            "resolution_id": _id("hpr"), "t": _now(),
            "actor": str(actor), "primitive": primitive,
            "target": str(target or ""), "status": str(status),
            "effect_count": max(0, int(effect_count)),
            "source_action": str(source_action or ""),
            "reason": str(reason or "")[:240],
        }
        self.resolutions.append(record)
        self.resolutions = self.resolutions[-500:]
        return deepcopy(record)

    @staticmethod
    def site_key(site_kind: str, site_id: str) -> str:
        kind = str(site_kind or "").strip().lower()
        if kind not in {"room", "place", "object"}:
            raise HouseholdPhysicsError("site_kind must be room, place, or object")
        return f"{kind}:{_clean_name(site_id, field='site_id')}"

    def leave_trace(self, *, author: str, site_kind: str, site_id: str,
                    text: str, facets=None, provenance=None) -> dict:
        site = self.site_key(site_kind, site_id)
        record = {
            "trace_id": _id("trace"), "kind": "trace", "t": _now(),
            "author": _clean_name(author, field="author"), "site": site,
            "text": _bounded_text(text, field="trace text"),
            "facets": _copy_json(dict(facets or {}), field="trace facets"),
            "provenance": _clean_string_list(
                provenance, field="trace provenance"),
            "audience": "room",
        }
        self.traces.append(record)
        return deepcopy(record)

    def withdraw_trace(self, *, author: str, trace_id: str) -> dict:
        trace_id = _clean_name(trace_id, field="trace_id")
        source = next((item for item in self.traces
                       if item.get("kind") == "trace"
                       and item.get("trace_id") == trace_id), None)
        if source is None:
            raise HouseholdPhysicsError(f"no trace '{trace_id}'")
        if source["author"].casefold() != str(author).casefold():
            raise HouseholdPhysicsError("only the trace author can withdraw it")
        if any(item.get("kind") == "withdrawal"
               and item.get("trace_id") == trace_id for item in self.traces):
            raise HouseholdPhysicsError("trace is already withdrawn")
        record = {"kind": "withdrawal", "trace_id": trace_id,
                  "author": source["author"], "site": source["site"],
                  "t": _now()}
        self.traces.append(record)
        return deepcopy(record)

    def read_traces(self, *, reader: str, site_kind: str, site_id: str) -> dict:
        site = self.site_key(site_kind, site_id)
        withdrawn = {item["trace_id"] for item in self.traces
                     if item.get("kind") == "withdrawal"}
        visible = [deepcopy(item) for item in self.traces
                   if item.get("kind") == "trace"
                   and item.get("site") == site
                   and item.get("trace_id") not in withdrawn]
        self.trace_reads[f"{reader}:{site}"] = len(self.traces)
        return {"site": site, "traces": visible,
                "revision": len(self.traces)}

    def make_agreement(self, *, creator: str, site_kind: str, site_id: str,
                       terms: str, parties) -> dict:
        creator = _clean_name(creator, field="creator")
        named = _clean_string_list(parties, field="parties")
        if creator.casefold() not in {party.casefold() for party in named}:
            named.insert(0, creator)
        record = {
            "agreement_id": _id("agreement"), "kind": "agreement",
            "t": _now(), "creator": creator,
            "site": self.site_key(site_kind, site_id),
            "terms": _bounded_text(terms, field="agreement terms"),
            "parties": named, "enforced": False,
        }
        self.agreements.append(record)
        return deepcopy(record)

    def _agreement_source(self, agreement_id: str) -> dict:
        agreement_id = _clean_name(agreement_id, field="agreement_id")
        source = next((item for item in self.agreements
                       if item.get("kind") == "agreement"
                       and item.get("agreement_id") == agreement_id), None)
        if source is None:
            raise HouseholdPhysicsError(f"no agreement '{agreement_id}'")
        return source

    def agreement_event(self, *, actor: str, agreement_id: str,
                        relation: str) -> dict:
        source = self._agreement_source(agreement_id)
        actor = _clean_name(actor, field="actor")
        if relation not in {"sign", "withdraw", "release"}:
            raise HouseholdPhysicsError("unknown agreement relation")
        if relation == "release" and source["creator"].casefold() != actor.casefold():
            raise HouseholdPhysicsError("only the creator can release an agreement")
        if relation in {"sign", "withdraw"} and not any(
                actor.casefold() == party.casefold()
                for party in source["parties"]):
            raise HouseholdPhysicsError("actor is not a named party")
        projection = self.project_agreement(agreement_id)
        signed = {name.casefold() for name in projection["signatures"]}
        if relation == "sign" and actor.casefold() in signed:
            raise HouseholdPhysicsError("actor has already signed")
        if relation == "withdraw" and actor.casefold() not in signed:
            raise HouseholdPhysicsError("actor has no active signature")
        if projection["released"]:
            raise HouseholdPhysicsError("agreement has been released")
        event = {"agreement_id": source["agreement_id"], "kind": relation,
                 "actor": actor, "t": _now()}
        self.agreements.append(event)
        return deepcopy(event)

    def project_agreement(self, agreement_id: str) -> dict:
        source = self._agreement_source(agreement_id)
        signatures = {}
        released = False
        for event in self.agreements:
            if event.get("agreement_id") != source["agreement_id"]:
                continue
            relation = event.get("kind")
            actor = str(event.get("actor") or "")
            if relation == "sign":
                signatures[actor.casefold()] = actor
            elif relation == "withdraw":
                signatures.pop(actor.casefold(), None)
            elif relation == "release":
                released = True
        return {**deepcopy(source), "signatures": list(signatures.values()),
                "released": released, "enforced": False}

    def schedule_deferred(self, *, actor: str, target_kind: str,
                          target_id: str, effect: dict, signals: dict,
                          threshold: float, baseline: dict = None) -> dict:
        effect = _copy_json(dict(effect or {}), field="deferred effect")
        if effect.get("effect") not in ALLOWED_DEFERRED_EFFECTS:
            raise HouseholdPhysicsError("unsupported deferred effect")
        clean_signals = {}
        for name, weight in dict(signals or {}).items():
            if name not in DEFERRED_SIGNALS:
                raise HouseholdPhysicsError(f"unknown deferred signal '{name}'")
            try:
                weight = float(weight)
            except (TypeError, ValueError) as error:
                raise HouseholdPhysicsError("signal weights must be numeric") from error
            if not math.isfinite(weight) or weight <= 0.0:
                raise HouseholdPhysicsError("signal weights must be finite and positive")
            clean_signals[name] = weight
        if len(clean_signals) < 2 or not (set(clean_signals) & NON_TIME_SIGNALS):
            raise HouseholdPhysicsError(
                "deferred settlement needs at least two signals including "
                "one non-time signal")
        total = sum(clean_signals.values())
        clean_signals = {name: value / total
                         for name, value in clean_signals.items()}
        try:
            threshold = float(threshold)
        except (TypeError, ValueError) as error:
            raise HouseholdPhysicsError("threshold must be numeric") from error
        if not math.isfinite(threshold) or not 0.0 < threshold <= 1.0:
            raise HouseholdPhysicsError("threshold must be within (0, 1]")
        record = {
            "deferred_id": _id("deferred"), "kind": "deferred",
            "created_at": _now(), "actor": _clean_name(actor, field="actor"),
            "target": self.site_key(target_kind, target_id),
            "effect": effect, "signals": clean_signals,
            "threshold": threshold,
            "baseline": _copy_json(dict(baseline or {}), field="baseline"),
            "status": "pending", "settled_at": None,
        }
        self.deferred.append(record)
        return deepcopy(record)

    def encounter_candidates(self, *, actor: str, target_kind: str,
                             target_id: str, trigger: str, room_seq: int,
                             fingerprint: str, now: float = None) -> list:
        """Settle only against a relevant encounter, never a blind tick."""
        now = float(_now() if now is None else now)
        target = self.site_key(target_kind, target_id)
        settled = []
        for record in self.deferred:
            if record.get("status") != "pending" or record.get("target") != target:
                continue
            baseline = dict(record.get("baseline") or {})
            elapsed_scale = max(1.0, float(baseline.get("elapsed_scale_s", 300.0)))
            activity_scale = max(1.0, float(baseline.get("activity_scale", 4.0)))
            values = {
                "observation": 1.0 if trigger in {
                    "observe", "read", "inspect", "contact", "use", "action"
                } else 0.0,
                "actor_present": 1.0 if actor else 0.0,
                "target_changed": 1.0 if fingerprint and fingerprint != str(
                    baseline.get("fingerprint") or "") else 0.0,
                "local_activity": min(1.0, max(0.0, (
                    float(room_seq) - float(baseline.get("room_seq", room_seq)))
                    / activity_scale)),
                "elapsed": min(1.0, max(0.0, (
                    now - float(record.get("created_at") or now))
                    / elapsed_scale)),
                "resource_ready": 1.0 if fingerprint else 0.0,
            }
            score = sum(float(weight) * values.get(name, 0.0)
                        for name, weight in record["signals"].items())
            if score + 1e-9 < float(record["threshold"]):
                continue
            record["status"] = "settled"
            record["settled_at"] = now
            record["settled_by"] = str(actor)
            record["settlement"] = {
                "trigger": str(trigger), "score": round(score, 6),
                "signals": {name: round(values[name], 6)
                            for name in record["signals"]},
            }
            settled.append(deepcopy(record))
        return settled

    def public_snapshot(self, observer: str = None) -> dict:
        withdrawn = {item["trace_id"] for item in self.traces
                     if item.get("kind") == "withdrawal"}
        active_traces = [item for item in self.traces
                         if item.get("kind") == "trace"
                         and item.get("trace_id") not in withdrawn]
        sites = {}
        for trace in active_traces:
            sites[trace["site"]] = sites.get(trace["site"], 0) + 1
        agreements = [self.project_agreement(item["agreement_id"])
                      for item in self.agreements
                      if item.get("kind") == "agreement"]
        unread = {}
        if observer:
            for site in sites:
                cursor = int(self.trace_reads.get(f"{observer}:{site}", 0))
                unread[site] = sum(
                    1 for index, item in enumerate(self.traces, start=1)
                    if index > cursor and item.get("site") == site)
        return {
            "schema": self.schema, "status": STATUS,
            "resolution_count": len(self.resolutions),
            "trace_sites": sites,
            "trace_unread": unread,
            "agreement_count": len(agreements),
            "active_agreement_count": sum(
                1 for item in agreements if not item["released"]),
            "pending_deferred_count": sum(
                1 for item in self.deferred if item.get("status") == "pending"),
        }

    def as_dict(self) -> dict:
        return {
            "schema": self.schema,
            "resolutions": deepcopy(self.resolutions),
            "traces": deepcopy(self.traces),
            "trace_reads": deepcopy(self.trace_reads),
            "agreements": deepcopy(self.agreements),
            "deferred": deepcopy(self.deferred),
        }

    @classmethod
    def from_dict(cls, room_id: str, value) -> "HouseholdPhysicsState":
        state = cls(room_id)
        source = dict(value or {})
        if source.get("schema") not in {None, SCHEMA}:
            raise HouseholdPhysicsError("unsupported household physics schema")
        state.resolutions = list(source.get("resolutions") or [])[-500:]
        state.traces = list(source.get("traces") or [])
        state.trace_reads = dict(source.get("trace_reads") or {})
        state.agreements = list(source.get("agreements") or [])
        state.deferred = list(source.get("deferred") or [])
        return state
