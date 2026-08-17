"""Organic, append-only posts for a household commons board.

The words are the post.  Facets are optional, overlapping descriptions that
may be attached by the author or a later local describer; they never select a
prompt shape or require a post to fit a category.  Retraction appends a
tombstone so resident-owned history is not silently rewritten.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Mapping, Sequence


POST_SCHEMA = 1
MAX_TEXT_CHARS = 8000
MAX_FACETS = 16
MAX_LINKS = 16


class CommonsBoardError(ValueError):
    pass


def _words(value, *, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def normalize_facets(raw: Mapping | None) -> dict[str, float]:
    """Return a sparse, open vocabulary vector; there is no type enum."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise CommonsBoardError("board facets must be a mapping")
    if len(raw) > MAX_FACETS:
        raise CommonsBoardError(f"board facets exceed {MAX_FACETS}")
    facets = {}
    for name, value in raw.items():
        key = _words(name, maximum=64).casefold()
        if not key:
            raise CommonsBoardError("board facet names cannot be empty")
        try:
            weight = float(value)
        except (TypeError, ValueError) as exc:
            raise CommonsBoardError("board facet weights must be numeric") from exc
        if not 0.0 <= weight <= 1.0:
            raise CommonsBoardError("board facet weights must be within 0 and 1")
        if weight > 0.0:
            facets[key] = round(weight, 6)
    return facets


def _strings(values: Sequence | None, *, label: str) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise CommonsBoardError(f"board {label} must be a list")
    if len(values) > MAX_LINKS:
        raise CommonsBoardError(f"board {label} exceed {MAX_LINKS}")
    normalized = []
    for value in values:
        item = _words(value, maximum=240)
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def make_post(*, author: str, text: str, facets: Mapping | None = None,
              addressed_to: Sequence | None = None,
              related_posts: Sequence | None = None,
              provenance: Sequence | None = None,
              post_id: str | None = None, created_at: str | None = None) -> dict:
    """Create one freeform household post without assigning a type."""
    author = _words(author, maximum=120)
    if not author:
        raise CommonsBoardError("board post author is required")
    text = str(text or "").strip()
    if not text:
        raise CommonsBoardError("board post text is required")
    if len(text) > MAX_TEXT_CHARS:
        raise CommonsBoardError(f"board post exceeds {MAX_TEXT_CHARS} characters")
    pid = _words(post_id, maximum=120) or f"post_{uuid.uuid4().hex}"
    return {
        "schema": POST_SCHEMA,
        "kind": "post",
        "post_id": pid,
        "by": author,
        "ts": created_at or time.strftime("%Y-%m-%d %H:%M:%S"),
        "text": text,
        "visibility": "household",
        "addressed_to": _strings(addressed_to, label="addressees"),
        "facets": normalize_facets(facets),
        "related_posts": _strings(related_posts, label="relationships"),
        "provenance": _strings(provenance, label="provenance anchors"),
    }


def legacy_post(page: Mapping, index: int = 0) -> dict:
    """Give an old shared-desk page a stable post envelope without loss."""
    page = dict(page or {})
    seed = "\x1f".join((str(page.get("by") or "unknown"),
                         str(page.get("ts") or ""),
                         str(page.get("text") or ""), str(index)))
    return {
        "schema": POST_SCHEMA,
        "kind": "post",
        "post_id": "legacy_" + hashlib.sha256(
            seed.encode("utf-8")).hexdigest()[:24],
        "by": str(page.get("by") or "unknown"),
        "ts": str(page.get("ts") or "unknown"),
        "text": str(page.get("text") or ""),
        "visibility": "household",
        "addressed_to": [], "facets": {}, "related_posts": [],
        "provenance": [], "legacy_page": True,
    }


def append_post(board, **values) -> dict:
    post = make_post(**values)
    board.pages.append(post)
    board.board_revision = int(getattr(board, "board_revision", 0)) + 1
    return post


def board_history(board) -> list[dict]:
    """Return posts plus retraction state for owner/audit operations."""
    posts = []
    retracted = set()
    for index, raw in enumerate(list(getattr(board, "pages", ()) or ())):
        record = dict(raw or {})
        if record.get("kind") == "retraction":
            retracted.add(str(record.get("post_id") or ""))
            continue
        post = (record if record.get("kind") == "post"
                else legacy_post(record, index))
        posts.append(post)
    return [{**post, "retracted": post["post_id"] in retracted}
            for post in posts]


def visible_posts(board) -> list[dict]:
    """Project only present posts; tombstoned words remain taken down."""
    return [post for post in board_history(board) if not post["retracted"]]


def retract_post(board, *, author: str, post_id: str,
                 created_at: str | None = None) -> dict:
    author = _words(author, maximum=120)
    post_id = _words(post_id, maximum=120)
    posts = {post["post_id"]: post for post in board_history(board)}
    post = posts.get(post_id)
    if post is None:
        raise CommonsBoardError("board post does not exist")
    if str(post.get("by") or "").casefold() != author.casefold():
        raise CommonsBoardError("only the author can retract a board post")
    if post.get("retracted"):
        raise CommonsBoardError("board post is already retracted")
    record = {
        "schema": POST_SCHEMA,
        "kind": "retraction",
        "post_id": post_id,
        "by": author,
        "ts": created_at or time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    board.pages.append(record)
    board.board_revision = int(getattr(board, "board_revision", 0)) + 1
    return record


def read_board(board, member: str) -> dict:
    before = max(0, int(getattr(board, "board_revision", 0)) - int(
        dict(getattr(board, "board_reads", {}) or {}).get(member, 0)))
    board.board_reads[str(member)] = int(getattr(board, "board_revision", 0))
    return {
        "posts": visible_posts(board),
        "revision": int(getattr(board, "board_revision", 0)),
        "unread_before": before,
    }
