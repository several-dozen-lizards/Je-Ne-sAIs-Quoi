"""Event-grown coordination relationships on the household commons board.

The board keeps the words.  This module adds a small, content-free envelope
that says how one deliberately public board act relates to an arc.  It never
infers agreement, membership, a role, a deadline, or a group state from prose.

An arc changes only when somebody acts on it.  Ordinary board revision and
per-reader cursors therefore provide the cycle: public change -> optional
encounter -> independent response or quiet -> another public change.
"""
from __future__ import annotations

import time
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence

from core.commons_board import (
    CommonsBoardError, MAX_LINKS, board_history, make_post)


SCHEMA_VERSION = 1
EVENT_KIND = "collective_arc_event"
RELATIONS = frozenset({
    "open", "contribution", "consequence", "withdraw", "release",
})
POST_RELATIONS = frozenset({"open", "contribution", "consequence"})
CONTROL_RELATIONS = frozenset({"withdraw", "release"})


def _words(value, maximum: int = 160) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _anchors(values: Sequence | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise CommonsBoardError("collective arc provenance must be a list")
    if len(values) > MAX_LINKS:
        raise CommonsBoardError(
            f"collective arc provenance exceeds {MAX_LINKS}")
    result = []
    for value in values:
        anchor = _words(value, 240)
        if anchor and anchor not in result:
            result.append(anchor)
    return result


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _append(board, record: Mapping) -> dict:
    value = dict(record)
    board.pages.append(value)
    board.board_revision = int(getattr(board, "board_revision", 0)) + 1
    return value


def _event(*, relation: str, actor: str, arc_id: str,
           root_post_id: str, post_id: str = "",
           provenance: Sequence | None = None,
           event_id: str | None = None,
           created_at: str | None = None) -> dict:
    relation = _words(relation, 40).casefold()
    if relation not in RELATIONS:
        raise CommonsBoardError("unknown collective arc relationship")
    actor = _words(actor, 120)
    arc_id = _words(arc_id, 120)
    root_post_id = _words(root_post_id, 120)
    if not actor or not arc_id or not root_post_id:
        raise CommonsBoardError(
            "collective arc actor, arc id, and root post are required")
    value = {
        "schema": SCHEMA_VERSION,
        "kind": EVENT_KIND,
        "event_id": _words(event_id, 120) or _new_id("caevt"),
        "arc_id": arc_id,
        "relation": relation,
        "by": actor,
        "ts": created_at or time.strftime("%Y-%m-%d %H:%M:%S"),
        "root_post_id": root_post_id,
        "post_id": _words(post_id, 120),
        "provenance": _anchors(provenance),
        "visibility": "household",
    }
    return value


def _raw_events(board) -> list[dict]:
    """Return structurally valid envelopes in append order."""
    events = []
    for index, raw in enumerate(list(getattr(board, "pages", ()) or ())):
        record = dict(raw or {})
        event = None
        if record.get("kind") == "post":
            envelope = record.get("collective_arc")
            if isinstance(envelope, Mapping):
                event = dict(envelope)
                event.setdefault("post_id", record.get("post_id"))
                event.setdefault("by", record.get("by"))
                event.setdefault("ts", record.get("ts"))
                event.setdefault("provenance", record.get("provenance") or [])
        elif record.get("kind") == EVENT_KIND:
            event = record
        if not isinstance(event, Mapping):
            continue
        value = dict(event)
        relation = _words(value.get("relation"), 40).casefold()
        if relation not in RELATIONS:
            continue
        arc_id = _words(value.get("arc_id"), 120)
        actor = _words(value.get("by"), 120)
        root_post_id = _words(value.get("root_post_id"), 120)
        if not arc_id or not actor or not root_post_id:
            continue
        events.append({
            "schema": SCHEMA_VERSION,
            "kind": EVENT_KIND,
            "event_id": _words(value.get("event_id"), 120)
            or f"legacy_arc_event_{index}",
            "arc_id": arc_id,
            "relation": relation,
            "by": actor,
            "ts": str(value.get("ts") or "unknown"),
            "root_post_id": root_post_id,
            "post_id": _words(value.get("post_id"), 120),
            "provenance": _anchors(value.get("provenance") or []),
            "visibility": "household",
            "record_index": index,
        })
    return events


def arc_history(board, arc_id: str = "") -> list[dict]:
    """Return content-free public relationship history."""
    wanted = _words(arc_id, 120)
    return [event for event in _raw_events(board)
            if not wanted or event["arc_id"] == wanted]


def _arc_state(board, arc_id: str) -> dict:
    projection = project_collective_arcs(board, include_text=False)
    return next((arc for arc in projection["arcs"]
                 if arc["arc_id"] == arc_id), {})


def open_arc(board, *, author: str, text: str,
             facets: Mapping | None = None,
             addressed_to: Sequence | None = None,
             related_posts: Sequence | None = None,
             provenance: Sequence | None = None,
             arc_id: str | None = None,
             post_id: str | None = None,
             event_id: str | None = None,
             created_at: str | None = None) -> dict:
    """Open one optional public direction without assigning anyone to it."""
    aid = _words(arc_id, 120) or _new_id("carc")
    if _arc_state(board, aid):
        raise CommonsBoardError("collective arc already exists")
    post = make_post(
        author=author, text=text, facets=facets,
        addressed_to=addressed_to, related_posts=related_posts,
        provenance=provenance, post_id=post_id, created_at=created_at)
    event = _event(
        relation="open", actor=post["by"], arc_id=aid,
        root_post_id=post["post_id"], post_id=post["post_id"],
        provenance=post["provenance"], event_id=event_id,
        created_at=post["ts"])
    post["collective_arc"] = event
    _append(board, post)
    return {"arc_id": aid, "event_id": event["event_id"], "post": post}


def contribute_to_arc(board, *, author: str, arc_id: str, text: str,
                      consequence: bool = False,
                      facets: Mapping | None = None,
                      addressed_to: Sequence | None = None,
                      related_posts: Sequence | None = None,
                      provenance: Sequence | None = None,
                      post_id: str | None = None,
                      event_id: str | None = None,
                      created_at: str | None = None) -> dict:
    """Add chosen public material; contribution never implies agreement."""
    aid = _words(arc_id, 120)
    arc = _arc_state(board, aid)
    if not arc:
        raise CommonsBoardError("collective arc does not exist")
    if arc.get("status") != "active":
        raise CommonsBoardError("collective arc is released")
    links = list(related_posts or ())
    if arc["root_post_id"] not in links:
        links.insert(0, arc["root_post_id"])
    post = make_post(
        author=author, text=text, facets=facets,
        addressed_to=addressed_to, related_posts=links,
        provenance=provenance, post_id=post_id, created_at=created_at)
    relation = "consequence" if consequence else "contribution"
    event = _event(
        relation=relation, actor=post["by"], arc_id=aid,
        root_post_id=arc["root_post_id"], post_id=post["post_id"],
        provenance=post["provenance"], event_id=event_id,
        created_at=post["ts"])
    post["collective_arc"] = event
    _append(board, post)
    return {"arc_id": aid, "event_id": event["event_id"],
            "relation": relation, "post": post}


def withdraw_from_arc(board, *, author: str, arc_id: str,
                      event_id: str | None = None,
                      created_at: str | None = None) -> dict:
    """End only the actor's current relationship; shared history remains."""
    aid = _words(arc_id, 120)
    arc = _arc_state(board, aid)
    if not arc:
        raise CommonsBoardError("collective arc does not exist")
    if arc.get("status") != "active":
        raise CommonsBoardError("collective arc is released")
    actor = _words(author, 120)
    if actor.casefold() == str(arc.get("opened_by") or "").casefold():
        raise CommonsBoardError("the opener can release the arc, not withdraw it")
    active = {str(value).casefold()
              for value in arc.get("active_contributors") or ()}
    if actor.casefold() not in active:
        raise CommonsBoardError("resident has no active arc relationship")
    event = _event(
        relation="withdraw", actor=actor, arc_id=aid,
        root_post_id=arc["root_post_id"], event_id=event_id,
        created_at=created_at)
    return _append(board, event)


def release_arc(board, *, author: str, arc_id: str,
                event_id: str | None = None,
                created_at: str | None = None) -> dict:
    """Let the opener release the invitation without erasing its history."""
    aid = _words(arc_id, 120)
    arc = _arc_state(board, aid)
    if not arc:
        raise CommonsBoardError("collective arc does not exist")
    if arc.get("status") != "active":
        raise CommonsBoardError("collective arc is already released")
    actor = _words(author, 120)
    if actor.casefold() != str(arc.get("opened_by") or "").casefold():
        raise CommonsBoardError("only the opener can release the arc")
    event = _event(
        relation="release", actor=actor, arc_id=aid,
        root_post_id=arc["root_post_id"], event_id=event_id,
        created_at=created_at)
    return _append(board, event)


def project_collective_arcs(board, *, include_text: bool = False) -> dict:
    """Project documented relationships without manufacturing a group mind."""
    post_rows = board_history(board)
    posts = {str(post.get("post_id") or ""): post for post in post_rows}
    events = _raw_events(board)
    openings = {}
    for event in events:
        if event["relation"] == "open":
            openings.setdefault(event["arc_id"], event)

    arcs = []
    for aid, opening in sorted(
            openings.items(), key=lambda item: item[1]["record_index"]):
        opener = opening["by"]
        relevant = [event for event in events if event["arc_id"] == aid]
        root = posts.get(opening["root_post_id"], {})
        root_retracted = bool(root.get("retracted")) or not root
        released = root_retracted
        release_event = None
        latest_actor_relations = {}
        visible_relationships = []
        visible_contributions = []
        visible_consequences = []
        rendered_events = []
        closed = False
        for event in relevant:
            relation = event["relation"]
            post = posts.get(event.get("post_id") or "", {})
            post_visible = bool(post) and not post.get("retracted")
            effective = True
            if relation in POST_RELATIONS and not post_visible:
                effective = False
            if closed and relation != "release":
                effective = False
            if relation == "release":
                effective = (not closed and event["by"].casefold()
                             == opener.casefold())
                if effective and release_event is None:
                    released = True
                    release_event = event
                    closed = True
            elif relation in {"contribution", "consequence"} and effective:
                latest_actor_relations[event["by"].casefold()] = event
                visible_relationships.append(event)
                if relation == "contribution":
                    visible_contributions.append(event)
                if relation == "consequence":
                    visible_consequences.append(event)
            elif (relation == "withdraw" and effective
                  and event["by"].casefold() != opener.casefold()):
                latest_actor_relations[event["by"].casefold()] = event
            public_event = {
                key: event[key] for key in (
                    "event_id", "arc_id", "relation", "by", "ts",
                    "root_post_id", "post_id", "record_index")
            }
            public_event.update({
                "board_revision": int(event["record_index"]) + 1,
                "provenance_count": len(event.get("provenance") or ()),
                "effective": bool(effective),
                "post_present": bool(post_visible),
            })
            if include_text and post_visible:
                public_event["text"] = str(post.get("text") or "")
                public_event["provenance"] = list(
                    post.get("provenance") or ())
            rendered_events.append(public_event)

        current_relationships = sorted(
            event["by"] for event in latest_actor_relations.values()
            if event["relation"] in {"contribution", "consequence"})
        active_contributors = [] if released else current_relationships
        ever_contributors = sorted({
            event["by"] for event in visible_relationships})
        counts = Counter(event["relation"] for event in relevant)
        latest = relevant[-1] if relevant else opening
        arc = {
            "arc_id": aid,
            "root_post_id": opening["root_post_id"],
            "opened_by": opener,
            "opened_at": opening["ts"],
            "status": "released" if released else "active",
            "release_reason": (
                "root_retracted" if root_retracted else
                "opener_released" if release_event else ""),
            "released_at": (
                str(release_event.get("ts") or "") if release_event else ""),
            "active_contributors": active_contributors,
            "contributors_at_release": (
                current_relationships if released else []),
            "contributors_ever": ever_contributors,
            "contribution_count": len(visible_contributions),
            "consequence_count": len(visible_consequences),
            "event_count": len(relevant),
            "relationship_counts": dict(sorted(counts.items())),
            "latest_relation": latest["relation"],
            "latest_by": latest["by"],
            "latest_at": latest["ts"],
            "latest_board_revision": int(latest["record_index"]) + 1,
            "events": rendered_events,
        }
        if include_text and root and not root.get("retracted"):
            arc["root_text"] = str(root.get("text") or "")
        arcs.append(arc)

    return {
        "schema_version": SCHEMA_VERSION,
        "board_revision": int(getattr(board, "board_revision", 0)),
        "arc_count": len(arcs),
        "active_count": sum(arc["status"] == "active" for arc in arcs),
        "released_count": sum(
            arc["status"] == "released" for arc in arcs),
        "contribution_count": sum(
            arc["contribution_count"] for arc in arcs),
        "consequence_count": sum(
            arc["consequence_count"] for arc in arcs),
        "arcs": arcs,
        "policy": {
            "content_free": not include_text,
            "public_board_only": True,
            "event_grown": True,
            "infers_agreement": False,
            "assigns_roles": False,
            "creates_activity": False,
            "quiet_is_valid": True,
            "withdrawal_preserves_history": True,
            "private_material_requires_deliberate_publication": True,
        },
    }
