"""Bounded, resident-chosen continuation after a room action.

The continuation marker grants no action by itself.  It preserves one
resident-owned request to see the world's actual answer before choosing again.
The DMN owns the later model call, so the ordinary turn lease can be released
between steps and human speech or shutdown can interrupt the episode.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from typing import Any, Mapping


CONTINUATION_SOURCE = "room_action_continuation"
CONTINUATION_OWNERSHIP = "persona_action_continuation"
MAX_ACTION_EPISODE_TURNS = 5
CONTINUABLE_ROOM_ACTIONS = frozenset({
    "light_on", "light_off", "board_post", "board_read", "board_retract",
    "move_to", "go", "walk", "look_at", "turn_toward", "look_around", "inspect",
})
_CONTINUE_RE = re.compile(r"<continue\s*/\s*>", re.IGNORECASE)
_REQUEST_MORE_RE = re.compile(
    r"<request_more_turns\s*/\s*>", re.IGNORECASE)


def continuation_requested(text: str) -> bool:
    """Return whether the resident emitted the exact continuation marker."""
    value = str(text or "")
    return bool(_CONTINUE_RE.search(value) or _REQUEST_MORE_RE.search(value))


def continuation_mode(text: str) -> str | None:
    """Return the resident's requested capacity route, if any.

    The ordinary marker prefers the one automatic local reserve and later
    falls through to a human grant.  The explicit request marker preserves
    that reserve and asks for a human-granted block immediately.
    """
    value = str(text or "")
    if _REQUEST_MORE_RE.search(value):
        return "request"
    if _CONTINUE_RE.search(value):
        return "continue"
    return None


def strip_continuation_marker(text: str) -> str:
    """Remove the control marker without changing the resident's other text."""
    value = _CONTINUE_RE.sub("", str(text or ""))
    value = _REQUEST_MORE_RE.sub("", value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    return value.strip()


def clamp_episode_limit(value: Any) -> int:
    """Normalize configuration beneath the non-negotiable circuit breaker."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = MAX_ACTION_EPISODE_TURNS
    return max(1, min(MAX_ACTION_EPISODE_TURNS, parsed))


def _finite(value: Any) -> Any:
    """Return a JSON-safe projection without interpreting world semantics."""
    if isinstance(value, Mapping):
        return {str(key): _finite(item) for key, item in value.items()
                if str(key) != "events"}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def room_state_digest(room_or_snapshot: Any) -> str:
    """Digest durable room state while ignoring the append-only event ring."""
    try:
        snapshot = (room_or_snapshot.snapshot()
                    if callable(getattr(room_or_snapshot, "snapshot", None))
                    else room_or_snapshot)
        payload = json.dumps(
            _finite(dict(snapshot or {})), ensure_ascii=False,
            sort_keys=True, separators=(",", ":"))
    except Exception:
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def action_signature(action: Mapping[str, Any]) -> str:
    value = dict(action or {})
    payload = "\0".join((
        str(value.get("verb") or "").strip().casefold(),
        str(value.get("target") or "").strip(),
        str(value.get("text") or "").strip(),
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def is_continuation_candidate(candidate: Mapping[str, Any]) -> bool:
    """Validate the narrow durable shape before granting a direct opening."""
    value = dict(candidate or {})
    episode = dict(value.get("action_episode") or {})
    try:
        completed = int(episode.get("completed_steps") or 0)
        block_completed = int(
            episode.get("block_completed_steps", completed) or 0)
        maximum = int(episode.get("max_turns") or 0)
    except (TypeError, ValueError):
        return False
    return (
        value.get("kind") == "cognitive"
        and value.get("source") == CONTINUATION_SOURCE
        and value.get("ownership") == CONTINUATION_OWNERSHIP
        and bool(str(episode.get("episode_id") or "").strip())
        and completed > 0
        and 0 <= block_completed < maximum <= MAX_ACTION_EPISODE_TURNS
    )


class ActionTurnAuthority:
    """Durable, content-private authority for one pending turn-block request.

    Public status contains only lifecycle metadata.  The private candidate is
    retained solely so an approved episode can resume from the actual last
    world result after a restart; it is never returned through status.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: str | None = None, clock=time.time):
        self.path = str(path or "")
        self._clock = clock
        self._lock = threading.Lock()
        self._state = {"schema_version": self.SCHEMA_VERSION,
                       "pending": None, "last_resolution": None}
        self._load()

    def _load(self):
        if not self.path or not os.path.isfile(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as stream:
                value = json.load(stream)
            if isinstance(value, dict):
                self._state.update({
                    "pending": value.get("pending"),
                    "last_resolution": value.get("last_resolution"),
                })
        except (OSError, ValueError, TypeError):
            # A damaged optional authority ledger cannot manufacture a grant.
            self._state["pending"] = None

    def _save(self):
        if not self.path:
            return
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(self._state, stream, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    @staticmethod
    def _public(request: Mapping[str, Any] | None) -> dict | None:
        if not request:
            return None
        value = dict(request)
        return {key: value.get(key) for key in (
            "request_id", "episode_id", "state", "requested_turns",
            "block_index", "completed_steps", "requested_at")}

    def status(self) -> dict:
        with self._lock:
            return {
                "schema_version": self.SCHEMA_VERSION,
                "pending": self._public(self._state.get("pending")),
                "last_resolution": dict(
                    self._state.get("last_resolution") or {}),
                "grant_semantics": "capacity_not_obligation",
                "block_turn_limit": MAX_ACTION_EPISODE_TURNS,
            }

    def pending_candidate(self) -> dict:
        """Return the private resume candidate without resolving its grant."""
        with self._lock:
            request = dict(self._state.get("pending") or {})
            if request.get("state") != "pending":
                raise ValueError("there is no pending action-turn request")
            return dict(request.get("candidate") or {})

    def request(self, candidate: Mapping[str, Any], *, now=None) -> dict:
        now = self._clock() if now is None else float(now)
        episode = dict(dict(candidate or {}).get("action_episode") or {})
        episode_id = str(episode.get("episode_id") or "").strip()
        if not episode_id:
            raise ValueError("action-turn request requires an episode id")
        request_id = hashlib.sha256(
            f"{episode_id}\0{episode.get('block_index')}\0{now}".encode(
                "utf-8")).hexdigest()[:20]
        with self._lock:
            existing = dict(self._state.get("pending") or {})
            if existing.get("state") == "pending":
                public = self._public(existing) or {}
                if existing.get("episode_id") == episode_id:
                    return {**public, "accepted": True}
                return {**public, "accepted": False}
            request = {
                "request_id": request_id,
                "episode_id": episode_id,
                "state": "pending",
                "requested_turns": int(
                    episode.get("max_turns") or MAX_ACTION_EPISODE_TURNS),
                "block_index": int(episode.get("block_index") or 0),
                "completed_steps": int(
                    episode.get("completed_steps") or 0),
                "requested_at": now,
                "candidate": _finite(dict(candidate or {})),
            }
            self._state["pending"] = request
            self._save()
            return {**(self._public(request) or {}), "accepted": True}

    def resolve(self, decision: str, *, now=None) -> dict:
        decision = str(decision or "").strip().casefold()
        if decision not in {"approve", "decline"}:
            raise ValueError("decision must be approve or decline")
        now = self._clock() if now is None else float(now)
        with self._lock:
            request = dict(self._state.get("pending") or {})
            if request.get("state") != "pending":
                raise ValueError("there is no pending action-turn request")
            candidate = (dict(request.get("candidate") or {})
                         if decision == "approve" else None)
            resolution = {
                **(self._public(request) or {}),
                "state": "approved" if decision == "approve" else "declined",
                "resolved_at": now,
            }
            self._state["pending"] = None
            self._state["last_resolution"] = resolution
            self._save()
        return {"resolution": resolution, "candidate": candidate}


def _feedback_text(action: Mapping[str, Any], result: Mapping[str, Any],
                   *, world_changed: bool, extra: str = "") -> str:
    action = dict(action or {})
    result = dict(result or {})
    # Board words remain available to their reader through `extra`, but do not
    # leak into operational result receipts or action signatures.
    result.pop("posts", None)
    rendered = json.dumps(
        _finite(result), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"))[:1400]
    target = str(action.get("target") or "").strip()
    lines = [
        "A room action you chose has completed.",
        "Recorded action: " + str(action.get("verb") or "unknown")
        + (" " + target if target else ""),
        "Recorded world result: " + rendered,
        "The durable room-state projection "
        + ("changed." if world_changed else "did not change."),
    ]
    if str(extra or "").strip():
        lines.append(str(extra).strip()[:6000])
    return "\n".join(lines)


def _consequence_available_after(result: Mapping[str, Any], now: float) -> float:
    """Return the host-authored edge after which a next choice may compete."""
    motion = dict(dict(result or {}).get("motion") or {})
    try:
        started = float(motion.get("started_at") or now)
        duration = max(0.0, float(motion.get("total_duration_s") or 0.0))
    except (TypeError, ValueError):
        return float(now)
    return max(float(now), started + duration)


def offer_action_continuation(
        field, *, origin_item: Mapping[str, Any], action: Mapping[str, Any],
        result: Mapping[str, Any], cycle_id: str, before_state_digest: str,
        after_state_digest: str, max_turns: Any = MAX_ACTION_EPISODE_TURNS,
        hard_blocked: bool = False, feedback_extra: str = "",
        request_mode: str = "continue", local_extension_available: bool = True,
        authority: ActionTurnAuthority | None = None,
        now: float | None = None) -> dict:
    """Offer one next-step choice after an explicitly marked room action."""
    now = time.time() if now is None else float(now)
    maximum = clamp_episode_limit(max_turns)
    prior = dict(dict(origin_item or {}).get("action_episode") or {})
    completed = max(0, int(prior.get("completed_steps") or 0)) + 1
    block_completed = max(0, int(
        prior.get("block_completed_steps",
                  prior.get("completed_steps") or 0))) + 1
    episode_id = str(prior.get("episode_id") or cycle_id or "").strip()
    block_index = max(0, int(prior.get("block_index") or 0))
    local_extension_used = bool(prior.get("local_extension_used"))
    signature = action_signature(action)
    changed = bool(before_state_digest and after_state_digest
                   and before_state_digest != after_state_digest)
    if not before_state_digest or not after_state_digest:
        changed = bool(dict(result or {}).get("ok")
                       and not dict(result or {}).get("unchanged"))
    repeated_unchanged = bool(
        prior.get("previous_action_signature") == signature
        and prior.get("after_state_digest") == after_state_digest
        and not changed)

    common = {
        "episode_id": episode_id,
        "completed_steps": completed,
        "block_completed_steps": block_completed,
        "block_index": block_index,
        "max_turns": maximum,
        "local_extension_used": local_extension_used,
        "world_changed": changed,
    }
    if field is None:
        return {**common, "status": "stopped", "stop_reason": "no_field"}
    if not episode_id:
        return {**common, "status": "stopped", "stop_reason": "no_episode_id"}
    if hard_blocked:
        return {**common, "status": "stopped",
                "stop_reason": "resource_boundary"}
    if not local_extension_available:
        return {**common, "status": "stopped",
                "stop_reason": "no_local_route"}
    if repeated_unchanged:
        return {**common, "status": "stopped",
                "stop_reason": "repeated_unchanged_action"}

    from core.dmn import event_salience

    features = {
        "novelty": 0.75 if changed else 0.35,
        "unresolved": 1.0,
        "volitional_relevance": 1.0,
    }
    salience, bounded, components = event_salience(features)
    episode = {
        **common,
        "previous_action_signature": signature,
        "before_state_digest": str(before_state_digest or ""),
        "after_state_digest": str(after_state_digest or ""),
    }
    node = _feedback_text(
        action, result, world_changed=changed, extra=feedback_extra)
    available_after = _consequence_available_after(result, now)

    if block_completed >= maximum:
        next_episode = {
            **episode,
            "block_completed_steps": 0,
            "block_index": block_index + 1,
            "grant_source": "operator",
        }
        next_candidate = {
            "kind": "cognitive",
            "source": CONTINUATION_SOURCE,
            "key": (f"{CONTINUATION_SOURCE}:{episode_id}:"
                    f"block:{block_index + 1}:1"),
            "node": node[:8000],
            "features": bounded,
            "ownership": CONTINUATION_OWNERSHIP,
            "action_episode": next_episode,
            "perception_event_ids": [],
            "available_after": available_after,
        }
        use_local = (
            str(request_mode or "continue") != "request"
            and not local_extension_used
            and bool(local_extension_available))
        if use_local:
            next_episode["local_extension_used"] = True
            next_episode["grant_source"] = "automatic_local"
            candidate = field.queue.put(
                next_candidate, salience, now=now, offer_meta={
                    "components": components, "inputs": bounded,
                    "raw_ref": episode_id,
                    "ownership": CONTINUATION_OWNERSHIP, "receipts": []})
            return {
                **common, "status": "enqueued", "stop_reason": None,
                "candidate_key": candidate.get("key"),
                "candidate": candidate, "grant_source": "automatic_local",
                "block_index": block_index + 1,
                "block_completed_steps": 0,
                "local_extension_used": True,
            }
        if authority is None:
            return {**common, "status": "stopped",
                    "stop_reason": "turn_cap"}
        request = authority.request(next_candidate, now=now)
        if not request.get("accepted"):
            return {**common, "status": "stopped",
                    "stop_reason": "another_request_pending"}
        return {
            **common, "status": "awaiting_approval",
            "stop_reason": "approval_required", "request": request,
            "request_id": request.get("request_id"),
        }

    key = f"{CONTINUATION_SOURCE}:{episode_id}:{completed + 1}"
    candidate = field.queue.put({
        "kind": "cognitive",
        "source": CONTINUATION_SOURCE,
        "key": key,
        "node": node[:8000],
        "features": bounded,
        "ownership": CONTINUATION_OWNERSHIP,
        "action_episode": episode,
        "perception_event_ids": [],
        "available_after": available_after,
    }, salience, now=now, offer_meta={
        "components": components,
        "inputs": bounded,
        "raw_ref": episode_id,
        "ownership": CONTINUATION_OWNERSHIP,
        "receipts": [],
    })
    return {**common, "status": "enqueued", "stop_reason": None,
            "candidate_key": candidate.get("key"), "candidate": candidate}
