"""Persona-private, text-only projection of recent embodied actions.

The room host remains authoritative over what happened.  This module only
projects completed action receipts for the cockpit and deliberately omits
freeform action text.  Repeated routine movements collapse by semantic
signature so a lived day does not become a wall of identical locomotion.
"""
from __future__ import annotations

from typing import Iterable, Mapping


BODY_ACTION_VERBS = frozenset({
    "move_to", "go", "walk", "look_at", "turn_toward", "look_around",
    "inspect", "sit", "stand", "gesture", "release_gesture",
    "body_motion", "light_on", "light_off", "contact", "read", "write",
    "say", "board_post", "board_read", "board_retract", "travel",
    "startup_handoff", "startup_handoff_clear",
})

ROUTINE_ACTION_VERBS = frozenset({
    "move_to", "go", "walk", "look_at", "turn_toward", "look_around",
})

_HIDDEN_TARGET_VERBS = frozenset({
    "say", "startup_handoff", "startup_handoff_clear",
})


def body_action_receipt(entry: Mapping) -> dict | None:
    """Reduce one executed action to the safe shape retained for the feed."""
    action = dict(entry.get("act") or {})
    verb = str(action.get("verb") or "").strip()
    if verb not in BODY_ACTION_VERBS:
        return None
    result = dict(entry.get("result") or {})
    refused = bool(result.get("error") or result.get("ok") is False)
    target = str(action.get("target") or "").strip()
    if verb in _HIDDEN_TARGET_VERBS:
        target = ""
    return {
        "verb": verb,
        "target": target[:180],
        "status": "refused" if refused else "completed",
        "routine": verb in ROUTINE_ACTION_VERBS,
        "content_free": True,
    }


def body_action_receipts(acted: Iterable[Mapping]) -> list[dict]:
    return [value for value in (
        body_action_receipt(entry) for entry in (acted or ())) if value]


def _action_phrase(resident: str, action: Mapping) -> str:
    verb = str(action.get("verb") or "")
    target = str(action.get("target") or "").strip()
    toward = f" {target}" if target else ""
    phrases = {
        "move_to": f"{resident} moved to{toward}",
        "go": f"{resident} went to{toward}",
        "walk": f"{resident} walked to{toward}",
        "look_at": f"{resident} looked at{toward}",
        "turn_toward": f"{resident} turned toward{toward}",
        "look_around": f"{resident} looked around",
        "inspect": f"{resident} inspected{toward}",
        "sit": f"{resident} sat down" + (f" at {target}" if target else ""),
        "stand": f"{resident} stood up",
        "gesture": f"{resident} made the {target} gesture" if target else
                   f"{resident} gestured",
        "release_gesture": f"{resident} released the gesture",
        "body_motion": f"{resident} moved with {target}" if target else
                       f"{resident} moved",
        "light_on": f"{resident} turned on{toward}",
        "light_off": f"{resident} turned off{toward}",
        "contact": f"{resident} touched{toward}",
        "read": f"{resident} read{toward}",
        "write": f"{resident} wrote on{toward}",
        "say": f"{resident} spoke in the room",
        "board_post": f"{resident} posted to{toward}",
        "board_read": f"{resident} read the board{toward}",
        "board_retract": f"{resident} retracted a board post{toward}",
        "travel": f"{resident} traveled to{toward}",
        "startup_handoff": f"{resident} set private startup bearings",
        "startup_handoff_clear": f"{resident} cleared the startup bearings",
    }
    phrase = phrases.get(verb, f"{resident} acted")
    return " ".join(phrase.split())


def recent_action_feed(memories: Iterable[Mapping], *, resident: str,
                       limit: int = 8, scan_memories: int = 80) -> list[dict]:
    """Project newest actions, coalescing routine duplicates across the scan."""
    source_memories = list(memories or ())[-max(1, int(scan_memories)):]
    projected = []
    routine_seen = {}
    for memory in reversed(source_memories):
        fields = dict(memory.get("fields") or {})
        raw_actions = fields.get("body_actions")
        if raw_actions is None:
            # Backward-compatible projection of autonomous room receipts that
            # predate the dedicated content-free body action field.
            raw_actions = fields.get("room_actions") or ()
            actions = body_action_receipts(raw_actions)
        else:
            actions = [dict(value) for value in raw_actions
                       if isinstance(value, Mapping)]
        source = "autonomous" if fields.get("autonomous") else "conversation"
        for index, action in reversed(list(enumerate(actions))):
            if action.get("verb") not in BODY_ACTION_VERBS:
                continue
            signature = (
                str(action.get("verb") or ""),
                str(action.get("target") or "").casefold(),
                str(action.get("status") or "completed"),
                source,
            )
            if action.get("routine") and signature in routine_seen:
                routine_seen[signature]["repeat_count"] += 1
                continue
            item = {
                "id": f"{memory.get('id') or 'action'}:{index}",
                "at": str(memory.get("timestamp") or ""),
                "source": source,
                "verb": signature[0],
                "target": str(action.get("target") or ""),
                "status": signature[2],
                "routine": bool(action.get("routine")),
                "pronounced": source == "conversation" or not action.get(
                    "routine"),
                "repeat_count": 1,
                "summary": _action_phrase(resident, action),
                "content_free": True,
            }
            projected.append(item)
            if item["routine"]:
                routine_seen[signature] = item
            if len(projected) >= max(1, int(limit)):
                return projected
    return projected
