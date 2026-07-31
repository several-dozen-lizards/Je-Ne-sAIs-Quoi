"""Content-private comparison of contact and non-contact deliberations."""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any


VECTOR_KEYS = (
    "recurrence",
    "relevance",
    "readiness",
    "affect_change",
    "body_intensity",
    "unresolved",
)


def _number(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _distance(left: dict, right: dict) -> float:
    a = dict(left.get("vector") or {})
    b = dict(right.get("vector") or {})
    return sum(abs(_number(a.get(key)) - _number(b.get(key)))
               for key in VECTOR_KEYS) / len(VECTOR_KEYS)


def summarize_contact_deliberations(path, *, tail: int = 4000) -> dict:
    """Match speech choices to structurally similar private/quiet choices.

    This is descriptive evidence only. It never scores, gates, rewards, or
    modifies a resident's future choices, and it never returns generated text.
    """
    records = []
    source = Path(path)
    if source.is_file():
        recent = deque(maxlen=max(1, min(int(tail), 20_000)))
        with source.open(encoding="utf-8") as stream:
            for line in stream:
                recent.append(line)
        for line in recent:
            try:
                value = json.loads(line)
            except (TypeError, ValueError):
                continue
            if value.get("kind") == "contact_deliberation":
                records.append(value)

    speech = [item for item in records if item.get("outcome") == "speech"]
    controls = [item for item in records
                if item.get("outcome") in {"private", "quiet"}]
    unused = set(range(len(controls)))
    pairs = []
    for chosen in speech:
        same_source = [
            index for index in unused
            if controls[index].get("source") == chosen.get("source")]
        candidates = same_source or list(unused)
        if not candidates:
            break
        index = min(candidates, key=lambda value:
                    _distance(chosen, controls[value]))
        control = controls[index]
        unused.remove(index)
        pairs.append({
            "speech_candidate_key": chosen.get("candidate_key"),
            "control_candidate_key": control.get("candidate_key"),
            "control_outcome": control.get("outcome"),
            "source": chosen.get("source"),
            "same_source": chosen.get("source") == control.get("source"),
            "vector_distance": round(_distance(chosen, control), 6),
            "speech_vector": {
                key: _number((chosen.get("vector") or {}).get(key))
                for key in VECTOR_KEYS},
            "control_vector": {
                key: _number((control.get("vector") or {}).get(key))
                for key in VECTOR_KEYS},
        })

    return {
        "schema": 1,
        "deliberations": len(records),
        "speech": len(speech),
        "speech_destinations": {
            "household_room": sum(
                item.get("destination") == "household_room"
                for item in speech),
            "private_chat": sum(
                item.get("destination") == "private_chat"
                for item in speech),
            "legacy_unspecified": sum(
                not item.get("destination") for item in speech),
        },
        "private": sum(item.get("outcome") == "private" for item in records),
        "quiet": sum(item.get("outcome") == "quiet" for item in records),
        "owned_continuity": sum(
            bool(item.get("owned_continuity_origin")) for item in records),
        "matched_pairs": pairs,
        "policy": {
            "descriptive_only": True,
            "content_private": True,
            "changes_selection": False,
            "speech_frequency_is_not_success": True,
            "quiet_is_valid": True,
            "pairing_is_not_causal_proof": True,
        },
    }
