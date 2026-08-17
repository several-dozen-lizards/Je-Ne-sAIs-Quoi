"""Bounded local-model proposals for room-object environmental metadata.

The model may describe what an object affords.  It may not assign a resident
an emotion, intention, memory, or bodily response.  Resident-side perception
remains the authority that combines these shared facts with each resident's
own current substrate.
"""
from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable, Mapping


DEFAULT_MODEL = "object-profiler-local"

# This is deliberately finite.  Known channels couple to resident-owned
# substrate values; the remaining verbs contribute only undirected ambient
# affordance pressure in the existing room-field projection.
ALLOWED_AFFORDANCES = frozenset({
    "amusement", "belonging", "calm", "comfort", "company", "compare",
    "curiosity", "drink", "focus", "gather", "ground", "hold",
    "illumination", "joy", "look", "notice", "novelty", "play", "pride",
    "read", "reflect", "remember", "resolve", "rest", "review", "ritual",
    "share", "soothe", "switch", "warmth", "watch", "wonder", "write",
})


def _output_schema() -> dict:
    """Ollama grammar: syntax is constrained before host validation."""
    return {
        "type": "object",
        "properties": {
            "affordances": {
                "type": "array", "minItems": 2, "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string",
                                 "enum": sorted(ALLOWED_AFFORDANCES)},
                        "weight": {"type": "number",
                                   "minimum": 0.2, "maximum": 0.85},
                    },
                    "required": ["name", "weight"],
                    "additionalProperties": False,
                },
            },
            "texture": {"type": "string", "minLength": 2,
                        "maxLength": 120},
            "temperature_c": {"type": ["number", "null"],
                              "minimum": -50.0, "maximum": 120.0},
        },
        "required": ["affordances", "texture", "temperature_c"],
        "additionalProperties": False,
    }


def _normalize_model_shape(value: dict) -> dict:
    raw = value.get("affordances")
    if isinstance(raw, list):
        mapped = {}
        for item in raw:
            if not isinstance(item, Mapping):
                raise ObjectProfileError(
                    "profile affordance entries must be objects")
            name = str(item.get("name") or "").strip().lower()
            if name in mapped:
                raise ObjectProfileError(
                    f"profile repeats affordance '{name}'")
            mapped[name] = item.get("weight")
        value["affordances"] = mapped
    return value


class ObjectProfileError(ValueError):
    """A profile could not be produced or did not satisfy host constraints."""


def _json_object(raw: str) -> dict:
    text = str(raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text,
                       flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ObjectProfileError("local model did not return one JSON object") \
            from exc
    if not isinstance(value, dict):
        raise ObjectProfileError("local model profile must be a JSON object")
    return value


def validate_profile(value: Mapping) -> dict:
    """Validate the only environmental fields AI is allowed to propose."""
    raw_affordances = value.get("affordances")
    if not isinstance(raw_affordances, Mapping):
        raise ObjectProfileError("profile affordances must be an object")
    if not 1 <= len(raw_affordances) <= 4:
        raise ObjectProfileError("profile needs one to four affordances")
    affordances = {}
    for raw_name, raw_weight in raw_affordances.items():
        name = str(raw_name or "").strip().lower()
        if name not in ALLOWED_AFFORDANCES:
            raise ObjectProfileError(f"unsupported affordance '{name}'")
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError) as exc:
            raise ObjectProfileError(
                f"affordance '{name}' needs a numeric weight") from exc
        if not math.isfinite(weight) or not 0.05 <= weight <= 1.0:
            raise ObjectProfileError(
                f"affordance '{name}' weight must be 0.05..1.0")
        affordances[name] = round(weight, 3)

    texture = str(value.get("texture") or "").strip()
    if not 2 <= len(texture) <= 120:
        raise ObjectProfileError("profile texture must be 2..120 characters")

    temperature = value.get("temperature_c")
    if temperature is not None:
        try:
            temperature = float(temperature)
        except (TypeError, ValueError) as exc:
            raise ObjectProfileError(
                "profile temperature_c must be numeric or null") from exc
        if not math.isfinite(temperature) or not -50.0 <= temperature <= 120.0:
            raise ObjectProfileError("profile temperature_c is implausible")
        temperature = round(temperature, 2)

    return {
        "affordances": affordances,
        "texture": texture,
        "temperature_c": temperature,
    }


def _fact_gated_affordances(profile: dict, snapshot: Mapping) -> dict:
    """Remove category claims that the supplied object facts cannot support."""
    words = " ".join(str(snapshot.get(key) or "").casefold()
                     for key in ("name", "kind", "description", "capability"))
    groups = {
        frozenset({"rest", "comfort", "company"}):
            ("chair", "couch", "sofa", "bed", "seat", "bench", "pillow"),
        frozenset({"write", "read", "share", "review", "compare"}):
            ("book", "paper", "poster", "picture", "desk", "table",
             "board", "screen", "sign", "document"),
        frozenset({"illumination", "switch"}):
            ("lamp", "light", "lantern", "device", "switch"),
        frozenset({"look", "watch", "notice"}):
            ("poster", "picture", "art", "window", "display", "screen",
             "sign", "sculpture"),
        frozenset({"drink"}):
            ("mug", "cup", "glass", "bottle", "vessel", "flask"),
    }
    kept = dict(profile["affordances"])
    for keys, evidence in groups.items():
        if not any(word in words for word in evidence):
            for key in keys:
                kept.pop(key, None)
    thermal = (profile.get("temperature_c")
               if profile.get("temperature_c") is not None
               else snapshot.get("temperature_c", 21.0))
    try:
        thermally_active = abs(float(thermal) - 21.0) >= 4.0
    except (TypeError, ValueError):
        thermally_active = False
    if not thermally_active and float(snapshot.get("power") or 0.0) <= 0.0:
        kept.pop("warmth", None)
    if not kept:
        raise ObjectProfileError(
            "local model proposed no affordance supported by object facts")
    profile["affordances"] = kept
    return profile


def propose_object_profile(
        snapshot: Mapping, *, model_name: str | None = None,
        spec_loader: Callable | None = None,
        client_factory: Callable | None = None) -> dict:
    """Ask one explicitly selected local model for one bounded profile."""
    model_name = str(model_name or os.environ.get(
        "JNSQ_OBJECT_PROFILE_MODEL", DEFAULT_MODEL)).strip()
    if not model_name:
        raise ObjectProfileError("no local object-profile model configured")
    if spec_loader is None:
        from harness.spec_loader import load_spec
        spec_loader = load_spec
    if client_factory is None:
        from harness.clients import client_for
        client_factory = client_for
    try:
        spec = spec_loader(model_name)
    except Exception as exc:
        raise ObjectProfileError(
            f"local object-profile model '{model_name}' is unavailable") from exc
    identity = dict(spec.get("identity") or {})
    if identity.get("provider") != "ollama" \
            or identity.get("locality") not in (None, "local"):
        raise ObjectProfileError(
            "object profiling requires a local Ollama model route")

    allowed = ", ".join(sorted(ALLOWED_AFFORDANCES))
    system = (
        "You profile a selected 3D room object using shared, observable "
        "environmental metadata. Return JSON only. Describe potential uses "
        "and perceptible qualities; never assign any resident an emotion, "
        "memory, intention, belief, bodily response, or biological state. "
        "Choose EXACTLY 2 OR 3 affordance keys only from this list: "
        + allowed + ". Never return four or more. Every key must be a direct "
        "use or property of the object itself, not an activity merely possible "
        "near it. drink is only for vessels; rest/comfort/company only for "
        "seating or bedding; write/read/share/review/compare only for text or "
        "writing surfaces; illumination/switch only for powered lights or "
        "devices; look/watch/notice only for displays, art, or apertures. "
        "Weights are conservative strengths from 0.20 to 0.85; never use 1.0. "
        "warmth requires supplied temperature at least 4C from ambient or an "
        "active powered heat source. Set temperature_c to null unless the "
        "supplied facts establish an active "
        "heat/cold source. Schema: {\"affordances\":[{\"name\":\"key\","
        "\"weight\":0.0}],"
        "\"texture\":\"short tactile/material phrase\","
        "\"temperature_c\":null}. texture must never be empty; use "
        "\"material unknown\" when the facts do not support a material.")
    facts = {key: snapshot.get(key) for key in (
        "name", "kind", "description", "texture", "temperature_c",
        "capability", "power", "size_m")}
    user = ("Profile this selected object. Treat missing facts as unknown; do "
            "not invent active contents, personal history, or ownership.\n"
            + json.dumps(facts, ensure_ascii=False, sort_keys=True))
    try:
        reply = client_factory(spec).chat(
            system, user, max_tokens=240, temperature=0.0,
            output_format=_output_schema())
    except Exception as exc:
        raise ObjectProfileError(
            f"local model '{model_name}' could not profile the object") from exc
    raw = _normalize_model_shape(_json_object(reply))
    if not str(raw.get("texture") or "").strip():
        current_texture = str(snapshot.get("texture") or "").strip()
        raw["texture"] = (current_texture if current_texture
                          and current_texture != "neutral"
                          else "material unknown")
    result = _fact_gated_affordances(validate_profile(raw), snapshot)
    result["model"] = model_name
    return result
