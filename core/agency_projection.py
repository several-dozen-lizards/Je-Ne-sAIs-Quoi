"""Read-only, allowlisted state projection for dormant agency runs.

The ordinary turn is a circulatory act.  This module is not: it samples
descriptive state without settling the body, recalling memory, consuming room
events, writing files, or calling a model.  The sample is explicitly an
observation window rather than a claim of atomic simultaneity.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


# Inherited from existing prompt block budgets rather than invented as new
# prose-tuning values: source ~= who_is_who (260 tokens), task ~= one full
# surfaced-memory block (600 tokens).
AGENCY_SOURCE_BUDGET = 260
AGENCY_TASK_BUDGET = 600
AGENCY_CONTROL_TEMPERATURE = 0.7
SUBSTRATE_MODES = frozenset({"on", "control"})


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _copy(value):
    return copy.deepcopy(value)


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({
            str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _finite(value, fallback=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return number if math.isfinite(number) else float(fallback)


@dataclass(frozen=True)
class AgencyTaskEnvelope:
    """One explicitly admitted synthetic/proposal task and its provenance."""

    task: str
    source_kind: str
    source_ref: str
    source_digest: str
    source_summary: str
    source_ownership: str
    authority_tier: int
    audience_mode: str = "private_interior"
    output_channel: str = "none"
    task_digest: str = field(init=False)

    def __post_init__(self):
        text_fields = (
            "task", "source_kind", "source_ref", "source_digest",
            "source_summary", "source_ownership",
        )
        for name in text_fields:
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"agency envelope {name} must not be empty")
            object.__setattr__(self, name, value)
        if len(self.task) > AGENCY_TASK_BUDGET * 4:
            raise ValueError(
                "agency task exceeds the inherited task block budget")
        if len(self.source_summary) > AGENCY_SOURCE_BUDGET * 4:
            raise ValueError(
                "agency source summary exceeds the inherited source budget")
        if not isinstance(self.authority_tier, int) \
                or self.authority_tier < 0:
            raise ValueError("agency authority_tier must be a nonnegative int")
        if self.audience_mode != "private_interior":
            raise ValueError(
                "P2C2B1 admits only private_interior agency tasks")
        if self.output_channel != "none":
            raise ValueError(
                "P2C2B1 agency tasks have no output channel")
        object.__setattr__(self, "task_digest", _digest(self.task))

    def receipt(self) -> dict:
        return {
            "task_digest": self.task_digest,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "source_digest": self.source_digest,
            "source_ownership": self.source_ownership,
            "authority_tier": self.authority_tier,
            "audience_mode": self.audience_mode,
            "output_channel": self.output_channel,
            "task_chars": len(self.task),
            "source_summary_chars": len(self.source_summary),
        }


@dataclass(frozen=True)
class AgencyStateProjection:
    persona: str
    model: str
    substrate_mode: str
    sampled_started_at: float
    sampled_finished_at: float
    external_demand_epoch: int
    enabled_organs: tuple[str, ...]
    cocktail: Mapping[str, float]
    oscillator: Mapping[str, Any]
    soma: Mapping[str, Any]
    perception: Mapping[str, Any]
    field: Mapping[str, Any]
    state_ref: str

    def __post_init__(self):
        if self.substrate_mode not in SUBSTRATE_MODES:
            raise ValueError("unknown agency substrate mode")
        for name in ("cocktail", "oscillator", "soma",
                     "perception", "field"):
            object.__setattr__(
                self, name, _freeze(_copy(dict(getattr(self, name)))))
        object.__setattr__(
            self, "enabled_organs", tuple(self.enabled_organs))

    @property
    def sample_window_ms(self) -> float:
        return round(max(
            0.0,
            (self.sampled_finished_at - self.sampled_started_at) * 1000.0),
            3)

    @property
    def suggested_temperature(self) -> float:
        return _finite(
            self.oscillator.get(
                "suggested_temperature",
                AGENCY_CONTROL_TEMPERATURE),
            AGENCY_CONTROL_TEMPERATURE)

    def receipt(self) -> dict:
        return {
            "state_ref": self.state_ref,
            "substrate_mode": self.substrate_mode,
            "external_demand_epoch": self.external_demand_epoch,
            "sample_window_ms": self.sample_window_ms,
            "suggested_temperature": self.suggested_temperature,
            "enabled_organ_count": len(self.enabled_organs),
            "perception_modalities": sorted(
                key for key in self.perception if key != "_policy"),
            "source_candidate_present": bool(
                self.field.get("source_candidate")),
            "excluded_sensitive_classes": [
                "conversation_window", "recalled_memories", "user_bedrock",
                "diary", "gist", "entity_cards", "room_events",
                "room_actions", "sensory_semantic_content",
            ],
        }


@dataclass(frozen=True)
class AgencyAssemblyProduct:
    assembly: Any
    projection: AgencyStateProjection
    state_ref: str
    temperature: float
    projection_receipt: Mapping[str, Any]

    def __post_init__(self):
        object.__setattr__(
            self, "projection_receipt",
            _freeze(_copy(dict(self.projection_receipt))))


def _perception_projection(snapshot: Mapping[str, Any], sampled_at: float):
    projected = {}
    for modality, raw in sorted(
            dict((snapshot or {}).get("modalities") or {}).items()):
        raw = dict(raw or {})
        updated = _finite(raw.get("updated"), sampled_at)
        item = {
            "event_id": str(raw.get("event_id") or ""),
            "ownership": str(raw.get("ownership") or "ambient"),
            "confidence": round(_finite(raw.get("confidence"), 0.0), 6),
            "age_s": round(max(0.0, sampled_at - updated), 3),
            "demand": round(_finite(raw.get("demand"), 0.0), 6),
            "pressure": round(_finite(raw.get("pressure"), 0.0), 6),
            "admitted": bool(raw.get("admitted")),
        }
        projected[str(modality)] = item
    policy = {
        str(key): value for key, value in
        dict((snapshot or {}).get("policy") or {}).items()
        if isinstance(value, (int, float, bool))
    }
    if policy:
        projected["_policy"] = policy
    return projected


def _field_projection(engine, envelope, sampled_at):
    field = getattr(engine, "idle_metabolism", None)
    observer = getattr(engine, "salience_observer", None)
    if field is None or observer is None:
        return {}
    view = observer.project_field(field, now=sampled_at)
    pressure = {
        str(key): value for key, value in
        dict(view.get("field_pressure") or {}).items()
        if isinstance(value, (int, float, bool))
    }
    source = None
    for candidate in view.get("candidates") or []:
        if str(candidate.get("key") or "") == envelope.source_ref:
            source = {
                "key": envelope.source_ref,
                "kind": candidate.get("kind"),
                "source": candidate.get("source"),
                "salience_total": candidate.get("salience_total"),
                "ownership": candidate.get("ownership"),
                "source_digest": envelope.source_digest,
            }
            break
    return {"pressure": pressure, "source_candidate": source}


def sample_agency_state(
        engine, envelope: AgencyTaskEnvelope, *,
        substrate_mode: str, external_demand_epoch: int,
        model_name: str = None,
        now_fn=time.time) -> AgencyStateProjection:
    """Sample one fresh projection without entering ordinary circulation."""
    if not isinstance(envelope, AgencyTaskEnvelope):
        raise TypeError("agency projection requires AgencyTaskEnvelope")
    if substrate_mode not in SUBSTRATE_MODES:
        raise ValueError("unknown agency substrate mode")
    started = float(now_fn())
    persona = str(getattr(engine, "persona", ""))
    model = str(model_name or getattr(engine, "model", ""))

    if substrate_mode == "control":
        state = {
            "mode": "control",
            "marker": "neutral agency substrate control",
            "external_demand_epoch": int(external_demand_epoch),
        }
        finished = float(now_fn())
        return AgencyStateProjection(
            persona=persona,
            model=model,
            substrate_mode=substrate_mode,
            sampled_started_at=started,
            sampled_finished_at=finished,
            external_demand_epoch=int(external_demand_epoch),
            enabled_organs=(),
            cocktail={},
            oscillator={
                "control_marker": state["marker"],
                "suggested_temperature": AGENCY_CONTROL_TEMPERATURE,
            },
            soma={},
            perception={},
            field={},
            state_ref=_digest(state),
        )

    cocktail = {
        str(key): _finite(value) for key, value in
        dict(getattr(engine, "cocktail", {}) or {}).items()
    }
    enabled = tuple(sorted(getattr(engine, "enabled", ()) or ()))

    oscillator = {}
    osc = getattr(engine, "osc", None)
    if osc is not None:
        oscillator = {
            "bands": {
                str(key): _finite(value)
                for key, value in dict(getattr(osc, "bands", {}) or {}).items()
            },
            "coherence": _finite(osc.coherence(), 1.0),
            "description": str(osc.describe() or ""),
            "suggested_temperature": _finite(
                osc.temperature(), AGENCY_CONTROL_TEMPERATURE),
        }

    soma = {}
    body = getattr(engine, "soma", None)
    if body is not None:
        soma = {
            "description": str(body.describe() or ""),
            "snapshot": _copy(body.snapshot()),
        }

    perception = {}
    sensory = getattr(engine, "perception", None)
    if sensory is not None:
        snapshot = sensory.snapshot(
            oscillator.get("bands") or None,
            oscillator.get("coherence", 1.0))
        perception = _perception_projection(snapshot, started)

    field = _field_projection(engine, envelope, started)
    finished = float(now_fn())
    reference_perception = _copy(perception)
    for item in reference_perception.values():
        if isinstance(item, dict):
            item.pop("age_s", None)
    canonical = {
        "persona": persona,
        "model": model,
        "substrate_mode": substrate_mode,
        "external_demand_epoch": int(external_demand_epoch),
        "enabled_organs": enabled,
        "cocktail": cocktail,
        "oscillator": oscillator,
        "soma": soma,
        "perception": reference_perception,
        "field": field,
        "source": envelope.receipt(),
    }
    return AgencyStateProjection(
        persona=persona,
        model=model,
        substrate_mode=substrate_mode,
        sampled_started_at=started,
        sampled_finished_at=finished,
        external_demand_epoch=int(external_demand_epoch),
        enabled_organs=enabled,
        cocktail=cocktail,
        oscillator=oscillator,
        soma=soma,
        perception=perception,
        field=field,
        state_ref=_digest(canonical),
    )
