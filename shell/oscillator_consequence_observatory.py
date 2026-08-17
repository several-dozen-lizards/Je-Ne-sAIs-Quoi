"""Read-only, content-free view of completed oscillator consequences.

The persona-private ledger is observer-only.  This module never feeds a
receipt back into prompts, state, memory, attention, or action selection.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os

from core.oscillator.consequences import (
    PERSISTED_SCHEMA,
    RECALL_WEIGHT_KEYS,
    VOICE_VECTOR_KEYS,
)
from shell.prompt_assembly_observatory import available_personas


MAX_READ_BYTES = 4 * 1024 * 1024
MAX_RECENT = 80
RECEIPT_NAME = "oscillator_consequence_receipts.jsonl"


def _timestamp(value):
    try:
        text = str(value).strip().replace("Z", "+00:00")
        if (len(text) >= 5 and text[-5] in "+-" and text[-4:].isdigit()
                and text[-3] != ":"):
            text = text[:-2] + ":" + text[-2:]
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _bounded_lines(path, max_bytes=MAX_READ_BYTES):
    if not os.path.isfile(path):
        return [], False
    size = os.path.getsize(path)
    truncated = size > max_bytes
    with open(path, "rb") as handle:
        if truncated:
            handle.seek(-max_bytes, os.SEEK_END)
            handle.readline()
        data = handle.read()
    return data.decode("utf-8", errors="replace").splitlines(), truncated


def _resolve_receipt_path(root, persona):
    wanted = str(persona or "").strip().casefold()
    matches = [item["name"] for item in available_personas(root)
               if item["name"].casefold() == wanted]
    if len(matches) != 1:
        raise ValueError("unknown persona")
    canonical = matches[0]
    return canonical, os.path.join(
        os.path.abspath(root), "personas", canonical, "history",
        RECEIPT_NAME)


def _number(value):
    return value if isinstance(value, (int, float)) else None


def _text(value, default="unknown"):
    text = str(value if value is not None else default).strip()
    return text.replace("\r", " ").replace("\n", " ")[:80] or default


def _numeric_map(value, keys):
    source = dict(value or {})
    return {key: source[key] for key in keys
            if isinstance(source.get(key), (int, float))}


def _record_view(record):
    prompt = dict(record.get("prompt_projection") or {})
    recall = dict(record.get("recall") or {})
    affect = dict(record.get("rhythm_affect") or {})
    conditions = dict(affect.get("conditions") or {})
    temperature = dict(record.get("generation_temperature") or {})
    attention = dict(record.get("attention_budget") or {})
    attention_seats = {}
    for name, value in dict(attention.get("seats") or {}).items():
        seat = dict(value or {})
        attention_seats[_text(name)] = {
            "group": _text(seat.get("group")),
            "base_budget": int(_number(seat.get("base_budget")) or 0),
            "attention_budget": int(
                _number(seat.get("attention_budget")) or 0),
            "effective_budget": int(
                _number(seat.get("effective_budget")) or 0),
            "supplemental_budget": int(
                _number(seat.get("supplemental_budget")) or 0),
            "rendered": bool(seat.get("rendered")),
            "outcome": _text(seat.get("outcome")),
            "tokens_after": int(_number(seat.get("tokens_after")) or 0),
        }
    sensory = dict(record.get("sensory_admission") or {})
    voice = dict(record.get("voice") or {})
    return {
        "cycle_id": _text(record.get("cycle_id"), "missing"),
        "recorded_at": _text(record.get("recorded_at"), "unavailable"),
        "scope": _text(record.get("scope")),
        "mode": _text(record.get("mode")),
        "prompt_projection": {
            key: _text(prompt.get(key)) for key in (
                "raw_rhythm", "processing_field", "debug_api",
                "cockpit_metrics")
        },
        "recall": {
            "status": _text(recall.get("status")),
            "weights_changed": bool(recall.get("weights_changed")),
            "base_weights": _numeric_map(
                recall.get("base_weights"), RECALL_WEIGHT_KEYS),
            "effective_weights": _numeric_map(
                recall.get("effective_weights"), RECALL_WEIGHT_KEYS),
        },
        "rhythm_affect": {
            "mode": _text(affect.get("mode")),
            "applied": bool(affect.get("applied")),
            "cocktail_unchanged": bool(affect.get("cocktail_unchanged")),
            "dominant_band_alias": _text(
                affect.get("dominant_band_alias"), "unavailable"),
            "observed_dwell_seconds": _number(
                affect.get("observed_dwell_seconds")),
            "legacy_eligible": bool(affect.get("legacy_eligible")),
            "conditions": {
                name: {"would_change": bool(
                    dict(conditions.get(name) or {}).get("would_change"))}
                for name in ("mapped", "label_removed", "mismatched", "sham")
            },
        },
        "generation_temperature": {
            "status": _text(temperature.get("status")),
            "computed_value": _number(temperature.get("computed_value")),
            "wire_value": _number(temperature.get("wire_value")),
            "wire_mode": _text(
                temperature.get("wire_mode"), "unavailable"),
            "causal_at_provider": temperature.get("causal_at_provider")
            if isinstance(temperature.get("causal_at_provider"), bool)
            else None,
            "family": _text(temperature.get("family")),
            "provider": _text(temperature.get("provider")),
        },
        "attention_budget": {
            "status": _text(attention.get("status")),
            "rendered_seat_count": int(
                _number(attention.get("rendered_seat_count")) or 0),
            "seats": attention_seats,
            "resident_readout": _text(attention.get("resident_readout")),
        },
        "sensory_admission": {
            "status": _text(sensory.get("status")),
        },
        "voice": {
            "status": _text(voice.get("status")),
            "vector": _numeric_map(voice.get("vector"), VOICE_VECTOR_KEYS),
        },
        "dmn": {"status": _text(
            dict(record.get("dmn") or {}).get("status"))},
        "agency": {"status": _text(
            dict(record.get("agency") or {}).get("status"))},
    }


def summarize_oscillator_consequences(records, *, persona, hours=24,
                                      malformed=0, tail_truncated=False):
    views = [_record_view(record) for record in records]
    temperature_counts = Counter(
        view["generation_temperature"]["status"] for view in views)
    recall_counts = Counter(view["recall"]["status"] for view in views)
    attention_counts = Counter(
        view["attention_budget"]["status"] for view in views)
    prompt_violations = sum(
        view["prompt_projection"]["raw_rhythm"] != "sheathed"
        or view["prompt_projection"]["processing_field"] != "sheathed"
        for view in views)
    affect_applications = sum(
        view["rhythm_affect"]["applied"] for view in views)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persona": persona,
        "window_hours": int(hours),
        "totals": {
            "completed_turn_receipts": len(views),
            "prompt_projection_violations": prompt_violations,
            "rhythm_affect_applications": affect_applications,
            "recall_weights_changed": sum(
                view["recall"]["weights_changed"] for view in views),
            "temperature_causal_at_provider": sum(
                view["generation_temperature"]["causal_at_provider"] is True
                for view in views),
            "attention_supplemental_tokens": sum(
                seat["supplemental_budget"] for view in views
                for seat in view["attention_budget"]["seats"].values()),
            "attention_rendered_blocks": sum(
                seat["rendered"] for view in views
                for seat in view["attention_budget"]["seats"].values()),
        },
        "status_counts": {
            "recall": dict(sorted(recall_counts.items())),
            "generation_temperature": dict(
                sorted(temperature_counts.items())),
            "attention_budget": dict(sorted(attention_counts.items())),
        },
        "recent": list(reversed(views[-MAX_RECENT:])),
        "integrity": {
            "malformed_lines": int(malformed),
            "tail_truncated": bool(tail_truncated),
            "privacy": (
                "persona-private allowlisted numeric/status metadata only; "
                "prompt, reply, memory content and identity, source text, "
                "and resident descriptions excluded"),
            "causal_readback": False,
            "claim_boundary": (
                "a wire receipt establishes application or omission at a "
                "declared boundary; it does not establish attention, benefit, "
                "subjective experience, or a behavioral difference"),
        },
    }


def read_oscillator_consequences(root, persona, *, hours=24,
                                 max_bytes=MAX_READ_BYTES):
    canonical, path = _resolve_receipt_path(root, persona)
    lines, truncated = _bounded_lines(path, max_bytes=max_bytes)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)
              if hours > 0 else None)
    records = []
    malformed = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            malformed += 1
            continue
        stamp = _timestamp(record.get("recorded_at"))
        if cutoff is not None and (stamp is None or stamp < cutoff):
            continue
        if record.get("schema") != PERSISTED_SCHEMA:
            malformed += 1
            continue
        records.append(record)
    return summarize_oscillator_consequences(
        records, persona=canonical, hours=hours, malformed=malformed,
        tail_truncated=truncated)
