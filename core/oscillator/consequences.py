"""Content-free receipts for oscillator consequences at provider boundaries."""
from __future__ import annotations

from datetime import datetime
import json
import math
import os
from typing import Any, Mapping


PERSISTED_SCHEMA = "jnaiq.oscillator_consequence.v1"
RECALL_WEIGHT_KEYS = (
    "emotion", "semantic", "importance", "familiarity", "recency", "entity",
)
VOICE_VECTOR_KEYS = (
    "energy", "settling", "warmth", "tension", "coherence",
)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _dynamic_temperature(policy: Mapping[str, Any], computed: float) -> float:
    value = computed
    if policy.get("min") is not None:
        value = max(_finite(policy["min"], value), value)
    if policy.get("max") is not None:
        value = min(_finite(policy["max"], value), value)
    if policy.get("precision") is not None:
        value = round(value, int(policy["precision"]))
    return value


def temperature_delivery_receipt(
        spec: Mapping[str, Any] | None, computed: float) -> dict:
    """Describe whether the computed temperature can reach this exact wire."""
    spec = dict(spec or {})
    identity = dict(spec.get("identity") or {})
    family = str(identity.get("family") or "unknown")
    provider = str(identity.get("provider") or "unknown")
    computed = _finite(computed, 0.7)
    policy = dict((spec.get("sampling") or {}).get("temperature") or {})

    if family == "anthropic":
        wire = max(0.0, min(1.0, computed))
        return {
            "status": "applied" if wire == computed else "applied_clamped",
            "computed_value": round(computed, 6),
            "wire_value": round(wire, 6),
            "wire_mode": "dynamic_0_1",
            "causal_at_provider": True,
            "family": family,
            "provider": provider,
        }
    if family == "llama3-chatml":
        return {
            "status": "applied",
            "computed_value": round(computed, 6),
            "wire_value": round(computed, 6),
            "wire_mode": "dynamic",
            "causal_at_provider": True,
            "family": family,
            "provider": provider,
        }
    if family == "openai_chat":
        mode = str(policy.get("mode") or "dynamic")
        if mode == "omit":
            return {
                "status": "provider_omitted",
                "computed_value": round(computed, 6),
                "wire_value": None,
                "wire_mode": mode,
                "causal_at_provider": False,
                "family": family,
                "provider": provider,
            }
        if mode == "fixed":
            fixed = _finite(policy.get("value"), computed)
            fixed = _dynamic_temperature(policy, fixed)
            return {
                "status": "provider_fixed_override",
                "computed_value": round(computed, 6),
                "wire_value": round(fixed, 6),
                "wire_mode": mode,
                "causal_at_provider": False,
                "family": family,
                "provider": provider,
            }
        wire = _dynamic_temperature(policy, computed)
        return {
            "status": "applied" if wire == computed else "applied_bounded",
            "computed_value": round(computed, 6),
            "wire_value": round(wire, 6),
            "wire_mode": mode,
            "causal_at_provider": True,
            "family": family,
            "provider": provider,
        }
    return {
        "status": "wire_contract_unknown",
        "computed_value": round(computed, 6),
        "wire_value": None,
        "wire_mode": None,
        "causal_at_provider": None,
        "family": family,
        "provider": provider,
    }


def consequence_receipt(
        *, spec: Mapping[str, Any] | None, computed_temperature: float,
        recall_enabled: bool, base_recall_weights: Mapping[str, Any] | None,
        effective_recall_weights: Mapping[str, Any] | None,
        awareness_aperture: Mapping[str, Any] | None,
        perception_policy: Mapping[str, Any] | None,
        voice_vector: Mapping[str, Any] | None,
        rhythm_affect: Mapping[str, Any] | None,
        social_projection: bool = False) -> dict:
    """One turn's oscillator outputs, with application boundaries explicit."""
    base = {str(k): _finite(v) for k, v in
            dict(base_recall_weights or {}).items()}
    effective = {str(k): _finite(v) for k, v in
                 dict(effective_recall_weights or {}).items()}
    changed = bool(base and effective and any(
        abs(effective.get(key, 0.0) - value) > 1e-12
        for key, value in base.items()))
    aperture = dict(awareness_aperture or {})
    seats = dict((aperture.get("conductance") or {}).get(
        "attention_seats") or {})
    attention_seats = {}
    for name, value in seats.items():
        seat = dict(value or {})
        attention_seats[str(name)] = {
            "group": str(seat.get("group") or "unknown"),
            "base_budget": max(0, int(seat.get("base_budget") or 0)),
            "attention_budget": max(
                0, int(seat.get("attention_budget") or 0)),
            "effective_budget": max(
                0, int(seat.get("effective_budget") or 0)),
            "supplemental_budget": max(
                0, int(seat.get("supplemental_budget") or 0)),
            "rendered": bool(seat.get("rendered")),
            "outcome": str(seat.get("outcome") or "unknown"),
            "tokens_after": max(0, int(seat.get("tokens_after") or 0)),
        }
    return {
        "schema_version": 1,
        "prompt_projection": {
            "raw_rhythm": "sheathed",
            "processing_field": "sheathed",
            "debug_api": "available",
            "cockpit_metrics": "available",
        },
        "recall": {
            "status": (
                "withheld_social_projection" if social_projection else
                "applied" if recall_enabled else "disabled"),
            "weights_changed": changed if recall_enabled else False,
            "base_weights": base,
            "effective_weights": effective,
        },
        "rhythm_affect": dict(rhythm_affect or {
            "mode": "absent", "applied": False}),
        "generation_temperature": (
            {"status": "withheld_social_projection",
             "computed_value": round(_finite(computed_temperature), 6),
             "causal_at_provider": False}
            if social_projection else
            temperature_delivery_receipt(spec, computed_temperature)),
        "attention_budget": {
            "status": (
                "withheld_social_projection" if social_projection else
                "bypass" if aperture.get("bypass") else
                "applied" if seats else "projected_no_rendered_seats"),
            "rendered_seat_count": len(seats),
            "seats": attention_seats,
            "resident_readout": "sheathed",
        },
        "sensory_admission": {
            "status": "policy_available_separate_event_boundary",
            "policy": dict(perception_policy or {}),
        },
        "voice": {
            "status": "vector_projected_playback_downstream",
            "vector": dict(voice_vector or {}),
        },
        "dmn": {"status": "separate_idle_event_boundary"},
        "agency": {"status": "separate_owned_task_boundary"},
    }


def _short_text(value: Any, default: str = "unknown") -> str:
    text = str(value if value is not None else default).strip()
    return text.replace("\r", " ").replace("\n", " ")[:80] or default


def _optional_finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 6) if math.isfinite(number) else None


def _numeric_allowlist(source: Mapping[str, Any] | None,
                       keys: tuple[str, ...]) -> dict:
    source = dict(source or {})
    result = {}
    for key in keys:
        value = _optional_finite(source.get(key))
        if value is not None:
            result[key] = value
    return result


def persistent_consequence_receipt(
        receipt: Mapping[str, Any] | None, *, cycle_id: str,
        recorded_at: str | None = None) -> dict | None:
    """Strict allowlist for the persona-private, observer-only ledger.

    The live receipt may grow over time.  Persistence does not inherit those
    additions automatically: prompt/reply text, memories, source identifiers,
    and resident descriptions have no route through this function.
    """
    if not receipt:
        return None
    source = dict(receipt)
    prompt = dict(source.get("prompt_projection") or {})
    recall = dict(source.get("recall") or {})
    rhythm_affect = dict(source.get("rhythm_affect") or {})
    temperature = dict(source.get("generation_temperature") or {})
    attention = dict(source.get("attention_budget") or {})
    sensory = dict(source.get("sensory_admission") or {})
    voice = dict(source.get("voice") or {})
    conditions = dict(rhythm_affect.get("conditions") or {})
    condition_view = {}
    for name in ("mapped", "label_removed", "mismatched", "sham"):
        value = dict(conditions.get(name) or {})
        condition_view[name] = {
            "would_change": bool(value.get("would_change")),
        }
    attention_seats = {}
    for name, value in dict(attention.get("seats") or {}).items():
        seat = dict(value or {})
        attention_seats[_short_text(name)] = {
            "group": _short_text(seat.get("group")),
            "base_budget": int(max(0, _finite(
                seat.get("base_budget")))),
            "attention_budget": int(max(0, _finite(
                seat.get("attention_budget")))),
            "effective_budget": int(max(0, _finite(
                seat.get("effective_budget")))),
            "supplemental_budget": int(max(0, _finite(
                seat.get("supplemental_budget")))),
            "rendered": bool(seat.get("rendered")),
            "outcome": _short_text(seat.get("outcome")),
            "tokens_after": int(max(0, _finite(
                seat.get("tokens_after")))),
        }
    record = {
        "schema": PERSISTED_SCHEMA,
        "schema_version": 1,
        "cycle_id": _short_text(cycle_id, "missing"),
        "recorded_at": (
            _short_text(recorded_at) if recorded_at else
            datetime.now().astimezone().isoformat(timespec="seconds")),
        "scope": "persona_private",
        "mode": "observer_only_no_readback",
        "prompt_projection": {
            key: _short_text(prompt.get(key)) for key in (
                "raw_rhythm", "processing_field", "debug_api",
                "cockpit_metrics")
        },
        "recall": {
            "status": _short_text(recall.get("status")),
            "weights_changed": bool(recall.get("weights_changed")),
            "base_weights": _numeric_allowlist(
                recall.get("base_weights"), RECALL_WEIGHT_KEYS),
            "effective_weights": _numeric_allowlist(
                recall.get("effective_weights"), RECALL_WEIGHT_KEYS),
        },
        "rhythm_affect": {
            "mode": _short_text(rhythm_affect.get("mode")),
            "applied": bool(rhythm_affect.get("applied")),
            "cocktail_unchanged": bool(
                rhythm_affect.get("cocktail_unchanged")),
            "dominant_band_alias": _short_text(
                rhythm_affect.get("dominant_band_alias"), "unavailable"),
            "observed_dwell_seconds": _optional_finite(
                rhythm_affect.get("observed_dwell_seconds")),
            "legacy_eligible": bool(rhythm_affect.get("legacy_eligible")),
            "conditions": condition_view,
        },
        "generation_temperature": {
            "status": _short_text(temperature.get("status")),
            "computed_value": _optional_finite(
                temperature.get("computed_value")),
            "wire_value": _optional_finite(temperature.get("wire_value")),
            "wire_mode": _short_text(
                temperature.get("wire_mode"), "unavailable"),
            "causal_at_provider": (
                temperature.get("causal_at_provider")
                if isinstance(temperature.get("causal_at_provider"), bool)
                else None),
            "family": _short_text(temperature.get("family")),
            "provider": _short_text(temperature.get("provider")),
        },
        "attention_budget": {
            "status": _short_text(attention.get("status")),
            "rendered_seat_count": int(
                max(0, _finite(attention.get("rendered_seat_count")))),
            "seats": attention_seats,
            "resident_readout": _short_text(
                attention.get("resident_readout")),
        },
        "sensory_admission": {
            "status": _short_text(sensory.get("status")),
        },
        "voice": {
            "status": _short_text(voice.get("status")),
            "vector": _numeric_allowlist(
                voice.get("vector"), VOICE_VECTOR_KEYS),
        },
        "dmn": {
            "status": _short_text(
                dict(source.get("dmn") or {}).get("status")),
        },
        "agency": {
            "status": _short_text(
                dict(source.get("agency") or {}).get("status")),
        },
        "integrity": {
            "content_excluded": [
                "prompt", "reply", "memory_content", "memory_identity",
                "source_text", "resident_description",
            ],
            "causal_readback": False,
        },
    }
    return record


def append_consequence_receipt(path: str,
                               receipt: Mapping[str, Any] | None) -> bool:
    """Append and fsync one already-allowlisted observer receipt."""
    if not receipt:
        return False
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    payload = json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True
