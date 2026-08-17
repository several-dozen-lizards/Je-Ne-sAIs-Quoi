"""Resident-owned circulation of autonomous consequences into conversation.

Canonical organs continue to own their records and content.  This junction
keeps only an append-only lifecycle and exact durable references, reconstructs
inspectable detail from those owners, and offers at most one consequence at an
already-inbound private conversational boundary.  Eligibility is not speech:
the resident may surface, hold, leave private, or remain quiet.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import threading
import time
from typing import Any, Mapping


MAX_SUMMARY_CHARS = 520
MAX_DETAIL_CHARS = 1600
MAX_REFS = 8
WORD_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}", re.I)
STOP_WORDS = frozenset({
    "about", "after", "again", "also", "and", "are", "because", "been",
    "before", "being", "but", "can", "could", "did", "does", "for", "from",
    "had", "has", "have", "how", "into", "its", "just", "more", "not", "now",
    "our", "out", "private", "that", "the", "their", "there", "this", "through",
    "was", "were", "what", "when", "where", "which", "while", "with", "would",
    "you", "your",
})


def _text(value: Any, maximum: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _tokens(value: Any) -> set[str]:
    return {
        token.casefold() for token in WORD_RE.findall(str(value or ""))
        if token.casefold() not in STOP_WORDS
    }


class AutonomousOutcomeJunction:
    """Append-only consequence lifecycle with an inbound resident choice fork."""

    SCHEMA_VERSION = 1

    def __init__(self, persona_root, *, owner: str, audience: str,
                 continuity, now_fn=time.time):
        self.owner = _text(owner, 80) or "persona"
        self.audience = _text(audience, 120).casefold()
        self.continuity = continuity
        self.now_fn = now_fn
        self.root = Path(persona_root) / "body" / "autonomous_outcomes"
        self.path = self.root / "outcomes.jsonl"
        self.thread_path = self.root / "conversation_thread.json"
        self._lock = threading.RLock()
        self._active: dict[str, dict] = {}
        self._active_decisions: dict[str, dict] = {}
        self._thread_subscribers: dict[str, set[queue.Queue]] = {}
        self._thread_touched: dict[str, float] = {}
        self._present_threads: set[str] = set()

    def conversation_thread_id(self) -> str:
        """Return the persona-owned private thread across dynamic ports."""
        with self._lock:
            if self.thread_path.is_file():
                try:
                    stored = json.loads(
                        self.thread_path.read_text(encoding="utf-8"))
                    thread_id = self._thread_id(stored.get("thread_id"))
                    if thread_id:
                        return thread_id
                except (OSError, TypeError, ValueError):
                    pass
            thread_id = "thread_" + secrets.token_hex(16)
            record = {
                "schema_version": self.SCHEMA_VERSION,
                "thread_id": thread_id,
                "owner": self.owner,
                "audience": self.audience,
                "content_included": False,
            }
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                with self.thread_path.open(
                        "w", encoding="utf-8", newline="\n") as stream:
                    json.dump(record, stream, ensure_ascii=False,
                              sort_keys=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError:
                return "thread_" + _digest({
                    "owner": self.owner, "audience": self.audience,
                    "root": str(self.root),
                })[:32]
            return thread_id

    def _append(self, value: Mapping[str, Any]) -> dict:
        record = dict(value or {})
        record.setdefault("schema_version", self.SCHEMA_VERSION)
        record.setdefault("at", float(self.now_fn()))
        self.root.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        return record

    def records(self, limit: int = 4000) -> list[dict]:
        if not self.path.is_file():
            return []
        found = []
        with self._lock, self.path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    found.append(value)
        return found[-max(1, min(int(limit), 10000)):]

    @staticmethod
    def _outcome_id(entry: Mapping[str, Any]) -> str:
        refs = [str(value) for value in entry.get("refs") or () if value]
        identity = {
            "organ": entry.get("organ"), "run_id": entry.get("run_id"),
            "evidence": entry.get("evidence"), "refs": refs,
            "at": float(entry.get("at") or 0.0),
        }
        if not identity["run_id"] and not refs:
            identity["summary_digest"] = _digest(entry.get("summary"))
        return "outcome_" + _digest(identity)[:20]

    def _source_entries(self) -> list[dict]:
        if self.continuity is None:
            return []
        snapshot = self.continuity.snapshot(
            max_movements=200, max_standing=0)
        entries = []
        for raw in snapshot.get("movements") or ():
            entry = dict(raw or {})
            entry["outcome_id"] = self._outcome_id(entry)
            entry["summary"] = _text(entry.get("summary"), MAX_SUMMARY_CHARS)
            entry["detail"] = _text(entry.get("detail"), MAX_DETAIL_CHARS)
            entry["refs"] = [
                _text(value, 240) for value in entry.get("refs") or ()
                if _text(value, 240)
            ][:MAX_REFS]
            entry["outcome_class"] = str(
                entry.get("outcome_class") or "substantive")
            raw_consequence = dict(entry.get("consequence") or {})
            entry["consequence"] = {
                "schema": 1,
                "kind": _text(raw_consequence.get("kind") or "generic", 80),
                "status": _text(raw_consequence.get("status") or "none", 40),
                "understanding": _text(
                    raw_consequence.get("understanding"), 800),
                "changed": _text(raw_consequence.get("changed"), 600),
                "unresolved": _text(raw_consequence.get("unresolved"), 600),
                "resident_authored": bool(
                    raw_consequence.get("resident_authored")),
                "source_content_included": False,
            }
            entries.append(entry)
        return entries

    def establish_baseline(self) -> dict:
        """Mark pre-deployment history without presenting it as fresh activity."""
        if self.records(limit=1):
            return {"created": False, "count": 0}
        entries = self._source_entries()
        for entry in entries:
            self._append(self._registration(entry, kind="outcome_baseline"))
        self._append({"kind": "baseline_complete", "count": len(entries),
                      "content_included": False})
        return {"created": True, "count": len(entries)}

    @staticmethod
    def _registration(entry: Mapping[str, Any], *, kind: str) -> dict:
        consequence = dict(entry.get("consequence") or {})
        return {
            "kind": kind,
            "outcome_id": entry.get("outcome_id"),
            "organ": entry.get("organ"),
            "stage": entry.get("stage"),
            "outcome_class": entry.get("outcome_class"),
            "summary": entry.get("summary"),
            "summary_digest": _digest(entry.get("summary")),
            "detail_digest": _digest(entry.get("detail")),
            "consequence_schema": int(consequence.get("schema") or 1),
            "consequence_kind": _text(consequence.get("kind"), 80),
            "consequence_status": _text(consequence.get("status"), 40),
            "consequence_digest": _digest(consequence),
            "inspectable_consequence": bool(any(
                consequence.get(field) for field in (
                    "understanding", "changed", "unresolved"))),
            "refs": list(entry.get("refs") or ())[:MAX_REFS],
            "evidence": entry.get("evidence"),
            "run_id": entry.get("run_id"),
            "occurred_at": float(entry.get("at") or 0.0),
            "canonical_content_copied": False,
        }

    def _views(self) -> dict[str, dict]:
        views: dict[str, dict] = {}
        for record in self.records():
            outcome_id = str(record.get("outcome_id") or "")
            if not outcome_id:
                continue
            kind = str(record.get("kind") or "")
            view = views.setdefault(outcome_id, {
                "outcome_id": outcome_id, "state": "open",
                "presentation_count": 0, "quiet_count": 0,
                "hold_count": 0,
            })
            if kind in {"outcome_registered", "outcome_baseline"}:
                view.update({
                    key: record.get(key) for key in (
                        "organ", "stage", "outcome_class", "summary", "refs",
                        "evidence", "run_id", "occurred_at",
                        "consequence_schema", "consequence_kind",
                        "consequence_status", "consequence_digest",
                        "inspectable_consequence")
                })
                if kind == "outcome_baseline":
                    view["state"] = "baseline"
            elif kind in {"outcome_presented",
                          "outcome_active_thread_presented"}:
                view["presentation_count"] += 1
                view["last_presented_at"] = record.get("at")
            elif kind == "outcome_quiet":
                view["quiet_count"] += 1
            elif kind == "outcome_held":
                view["hold_count"] += 1
                view["state"] = "held"
            elif kind == "outcome_surfaced":
                view["state"] = "surfaced"
            elif kind == "outcome_private":
                view["state"] = "private"
            elif kind == "outcome_delivery_failed":
                view["delivery_failure_count"] = int(
                    view.get("delivery_failure_count") or 0) + 1
                view["state"] = "open"
        return views

    def register_new(self, organs=None) -> list[dict]:
        """Register fresh canonical consequences once and return only those."""
        allowed = ({str(value) for value in organs}
                   if organs is not None else None)
        created = []
        with self._lock:
            views = self._views()
            for entry in self._source_entries():
                if allowed is not None and str(entry.get("organ")) not in allowed:
                    continue
                if entry["outcome_id"] in views:
                    continue
                self._append(self._registration(
                    entry, kind="outcome_registered"))
                created.append(entry)
                views[entry["outcome_id"]] = entry
        return created

    def refresh(self) -> list[dict]:
        self.register_new()
        entries = self._source_entries()
        views = self._views()
        return [{**entry, **views.get(entry["outcome_id"], {})}
                for entry in entries]

    @staticmethod
    def _thread_id(value: Any) -> str:
        return _text(value, 180)

    def subscribe(self, thread_id: str) -> queue.Queue:
        """Mark one exact visible conversation stream as open."""
        thread_id = self._thread_id(thread_id)
        if not thread_id:
            raise ValueError("conversation thread id is required")
        subscriber = queue.Queue(maxsize=8)
        with self._lock:
            self._thread_subscribers.setdefault(thread_id, set()).add(
                subscriber)
        return subscriber

    def unsubscribe(self, thread_id: str, subscriber: queue.Queue) -> int:
        thread_id = self._thread_id(thread_id)
        with self._lock:
            listeners = self._thread_subscribers.get(thread_id)
            if listeners is None:
                return 0
            listeners.discard(subscriber)
            if not listeners:
                self._thread_subscribers.pop(thread_id, None)
                self._present_threads.discard(thread_id)
                self._thread_touched.pop(thread_id, None)
            remaining = len(listeners)
        try:
            subscriber.put_nowait(None)
        except queue.Full:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(None)
            except queue.Full:
                pass
        return remaining

    def set_thread_presence(self, thread_id: str, present: bool) -> dict:
        """Apply one browser visibility transition; no heartbeat is required."""
        thread_id = self._thread_id(thread_id)
        if not thread_id:
            raise ValueError("conversation thread id is required")
        with self._lock:
            was_present = thread_id in self._present_threads
            if present:
                self._present_threads.add(thread_id)
                self._thread_touched[thread_id] = float(self.now_fn())
            elif not self._thread_subscribers.get(thread_id):
                self._present_threads.discard(thread_id)
                self._thread_touched.pop(thread_id, None)
            is_present = thread_id in self._present_threads
        return {"ok": True, "present": is_present,
                "changed": was_present != is_present}

    def touch_thread(self, thread_id: str) -> bool:
        thread_id = self._thread_id(thread_id)
        with self._lock:
            if thread_id not in self._present_threads:
                return False
            self._thread_touched[thread_id] = float(self.now_fn())
            return True

    def thread_active(self, thread_id: str) -> bool:
        thread_id = self._thread_id(thread_id)
        with self._lock:
            return thread_id in self._present_threads

    def active_thread(self) -> str:
        with self._lock:
            active = [
                (self._thread_touched.get(thread_id, 0.0), thread_id)
                for thread_id in self._present_threads
            ]
        return max(active, default=(0.0, ""))[1]

    def publish(self, thread_id: str) -> int:
        """Wake the exact open window after a durable lifecycle change."""
        thread_id = self._thread_id(thread_id)
        with self._lock:
            listeners = list(self._thread_subscribers.get(thread_id) or ())
        revision = int(float(self.now_fn()) * 1000000)
        delivered = 0
        for subscriber in listeners:
            try:
                subscriber.put_nowait(revision)
                delivered += 1
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(revision)
                    delivered += 1
                except (queue.Empty, queue.Full):
                    continue
        return delivered

    def _current(self, outcome_id: str) -> dict | None:
        return next((
            value for value in self.refresh()
            if value.get("outcome_id") == str(outcome_id or "")), None)

    def best_open_outcome(self, conversation_text: str) -> str:
        """Choose one strongest typed consequence for an active-thread scan."""
        now = float(self.now_fn())
        candidates = []
        for outcome in self.refresh():
            if outcome.get("state") not in {"open", "held"}:
                continue
            projection = self._projection(outcome, conversation_text, now)
            candidates.append((
                projection["score"], float(outcome.get("at") or 0.0),
                str(outcome.get("outcome_id") or "")))
        return max(candidates, default=(0.0, 0.0, ""))[2]

    @staticmethod
    def _boundary_digest(thread_id: str, boundary_id: str) -> str:
        return _digest({
            "thread_id": str(thread_id or ""),
            "boundary_id": str(boundary_id or ""),
        })

    def boundary_available(self, *, thread_id: str, boundary_id: str,
                           boundary_at: float = 0.0) -> bool:
        """One durable human admission can host at most one outcome choice.

        Presence keeps the transport reachable. It is intentionally absent
        from this authority check. The timestamp fallback lets pre-cut
        presentations consume the current boundary after a normal restart.
        """
        thread_id = self._thread_id(thread_id)
        boundary_id = _text(boundary_id, 240)
        if not thread_id or not boundary_id:
            return False
        digest = self._boundary_digest(thread_id, boundary_id)
        floor = max(0.0, float(boundary_at or 0.0))
        for record in reversed(self.records()):
            if record.get("kind") != "outcome_active_thread_presented" \
                    or self._thread_id(record.get("thread_id")) != thread_id:
                continue
            recorded_digest = str(record.get("boundary_digest") or "")
            if recorded_digest == digest:
                return False
            if not recorded_digest and floor > 0.0 \
                    and float(record.get("at") or 0.0) >= floor:
                return False
        return True

    def claim_spontaneous(self, *, outcome_id: str, thread_id: str,
                          conversation_text: str, readiness: float,
                          boundary_id: str = "",
                          boundary_at: float = 0.0) -> dict | None:
        """Offer one new consequence at an actually open conversation stream."""
        thread_id = self._thread_id(thread_id)
        if not self.thread_active(thread_id):
            return None
        if not self.boundary_available(
                thread_id=thread_id, boundary_id=boundary_id,
                boundary_at=boundary_at):
            return None
        outcome = self._current(outcome_id)
        if outcome is None or outcome.get("state") not in {"open", "held"}:
            return None
        now = float(self.now_fn())
        base = self._projection(outcome, conversation_text, now)
        ready = max(0.0, min(1.0, float(readiness or 0.0)))
        consequence = float(base["signals"]["consequence"])
        unresolved = float(base["signals"]["unresolved"])
        relevance = float(base["signals"]["message_relevance"])
        recency = float(base["signals"]["recency"])
        novelty = float(base["signals"]["presentation_novelty"])
        score = (.30 * relevance + .20 * consequence + .15 * unresolved
                 + .13 * recency + .10 * novelty + .12 * ready)
        eligible = (
            str(outcome.get("outcome_class") or "") != "quiet"
            and score >= .52)
        if not eligible:
            self._append({
                "kind": "outcome_active_thread_below_boundary",
                "outcome_id": outcome_id, "thread_id": thread_id,
                "score": round(score, 6), "threshold": .52,
                "signals": {
                    **base["signals"], "readiness": round(ready, 6)},
                "content_included": False,
            })
            return None
        decision_id = "outcome_decision_" + _digest({
            "outcome_id": outcome_id, "thread_id": thread_id,
            "at": now})[:20]
        opening = {
            **outcome, "decision_id": decision_id,
            "thread_id": thread_id,
            "projection": {
                "eligible": True, "score": round(score, 6),
                "threshold": .52,
                "signals": {
                    **base["signals"], "readiness": round(ready, 6)},
                "selects_speech": False,
            },
        }
        boundary_digest = self._boundary_digest(thread_id, boundary_id)
        with self._lock:
            if not self.boundary_available(
                    thread_id=thread_id, boundary_id=boundary_id,
                    boundary_at=boundary_at):
                return None
            opening["boundary_digest"] = boundary_digest
            self._active_decisions[decision_id] = opening
            self._thread_touched[thread_id] = now
            self._append({
                "kind": "outcome_active_thread_presented",
                "outcome_id": outcome_id, "decision_id": decision_id,
                "thread_id": thread_id,
                "boundary_digest": boundary_digest,
                "score": round(score, 6),
                "signals": opening["projection"]["signals"],
                "content_included": False, "selects_speech": False,
            })
        return opening

    def settle_spontaneous(self, decision_id: str, *, movement: str,
                           visible_reply: str = "", delivery_ref: str = "",
                           failure: str = "") -> dict:
        """Settle the resident's dedicated active-thread decision."""
        movement = str(movement or "")
        if movement not in {"surfaced", "held", "private", "quiet",
                            "delivery_failed"}:
            raise ValueError("unknown active-thread outcome movement")
        with self._lock:
            opening = self._active_decisions.pop(str(decision_id or ""), None)
        if opening is None:
            raise ValueError("active-thread outcome decision is not open")
        visible = _text(visible_reply, 12000)
        if movement == "surfaced" and len(_tokens(visible)) < 2:
            raise ValueError("surfaced outcome requires substantive chosen speech")
        kind = ("outcome_delivery_failed" if movement == "delivery_failed"
                else f"outcome_{movement}")
        record = self._append({
            "kind": kind, "outcome_id": opening["outcome_id"],
            "decision_id": opening["decision_id"],
            "thread_id": opening["thread_id"],
            "visible_reply_digest": (
                _digest(visible) if movement == "surfaced" else ""),
            "visible_reply_included": False,
            "delivery_ref": _text(delivery_ref, 240),
            "failure": _text(failure, 160),
        })
        self.publish(opening["thread_id"])
        return {
            "ok": movement != "delivery_failed", "movement": movement,
            "outcome_id": opening["outcome_id"],
            "thread_id": opening["thread_id"],
            "record_digest": _digest(record),
        }

    def _projection(self, outcome: Mapping[str, Any], message: str,
                    now: float) -> dict:
        message_tokens = _tokens(message)
        outcome_tokens = _tokens(
            f"{outcome.get('organ')} {outcome.get('summary')} "
            f"{outcome.get('detail')}")
        overlap = len(message_tokens & outcome_tokens)
        relevance = (overlap / max(1, min(len(message_tokens), 8)))
        relevance = max(0.0, min(1.0, relevance))
        outcome_class = str(outcome.get("outcome_class") or "substantive")
        consequence = {
            "quiet": .2, "substantive": 1.0, "obstruction": 1.0,
        }.get(outcome_class, .65)
        unresolved = 1.0 if outcome_class == "obstruction" else (
            .55 if outcome.get("stage") in {"available", "considered"} else .2)
        age = max(0.0, now - float(outcome.get("at") or now))
        recency = math.exp(-age / (48.0 * 3600.0))
        presentations = int(outcome.get("presentation_count") or 0)
        holds = int(outcome.get("hold_count") or 0)
        novelty = 1.0 / (1.0 + presentations + (1.5 * holds))
        score = (.34 * relevance + .22 * consequence + .18 * unresolved
                 + .16 * recency + .10 * novelty)
        return {
            "eligible": score >= .48,
            "score": round(score, 6), "threshold": .48,
            "signals": {
                "message_relevance": round(relevance, 6),
                "consequence": round(consequence, 6),
                "unresolved": round(unresolved, 6),
                "recency": round(recency, 6),
                "presentation_novelty": round(novelty, 6),
            },
            "selects_action": False,
        }

    def present(self, *, speaker: str, message: str, channel: str,
                conversation_id: str, thread_id: str = "") -> dict | None:
        speaker = _text(speaker, 120)
        conversation_id = _text(conversation_id, 180)
        if (str(channel or "chat") != "chat" or not conversation_id
                or not speaker or (self.audience and
                    speaker.casefold() != self.audience)):
            return None
        now = float(self.now_fn())
        candidates = []
        for outcome in self.refresh():
            if outcome.get("state") not in {"open", "held"}:
                continue
            projection = self._projection(outcome, message, now)
            if projection["eligible"]:
                candidates.append((projection["score"], outcome, projection))
        if not candidates:
            return None
        _score, outcome, projection = max(
            candidates, key=lambda value: (
                value[0], float(value[1].get("at") or 0.0),
                value[1].get("outcome_id")))
        thread_id = self._thread_id(thread_id)
        if thread_id:
            self.touch_thread(thread_id)
        opening = {**outcome, "conversation_id": conversation_id,
                   "thread_id": thread_id,
                   "speaker": speaker, "projection": projection}
        self._active[conversation_id] = opening
        self._append({
            "kind": "outcome_presented",
            "outcome_id": outcome["outcome_id"],
            "conversation_id": conversation_id,
            "thread_id": thread_id,
            "speaker": speaker.casefold(),
            "score": projection["score"],
            "signals": projection["signals"],
            "content_included": False,
        })
        return opening

    @staticmethod
    def render(opening: Mapping[str, Any] | None) -> str:
        if not opening:
            return ""
        outcome_id = opening["outcome_id"]
        refs = ", ".join(f"[{value}]" for value in opening.get("refs") or ())
        detail = str(opening.get("detail") or "").strip()
        consequence = dict(opening.get("consequence") or {})
        lines = [
            "PRIVATE AUTONOMOUS OUTCOME JUNCTION — RESIDENT CHOICE, NOT A TASK",
            "A consequence from your own autonomous work became eligible at "
            "this already-inbound conversation boundary. The organ has not "
            "spoken for you and eligibility is not an obligation to mention it.",
            f"Organ: {opening.get('organ')}. Outcome class: "
            f"{opening.get('outcome_class')}. What completed: "
            f"{opening.get('summary')}",
        ]
        typed_lines = []
        if consequence.get("understanding"):
            typed_lines.append("What landed: " + str(
                consequence["understanding"]))
        if consequence.get("changed"):
            typed_lines.append("What changed: " + str(consequence["changed"]))
        if consequence.get("unresolved"):
            typed_lines.append("Still unresolved: " + str(
                consequence["unresolved"]))
        if typed_lines:
            lines.append("Inspectable consequence:\n" + "\n".join(
                f"- {value}" for value in typed_lines))
        elif detail:
            lines.append(f"Inspectable consequence: {detail}")
        if refs:
            lines.append(f"Exact durable reference(s): {refs}")
        lines.append(
            "Choose freely: mention it naturally in your visible reply and append "
            f"<act>outcome_surface {outcome_id}</act>; keep it eligible for a "
            f"later relevant boundary with <act>outcome_hold {outcome_id}</act>; "
            f"or leave it private with <act>outcome_private {outcome_id}</act>. "
            "The marker is hidden. You may also do none of these and remain quiet. "
            "Do not claim source or artifact contents that are not shown here."
        )
        return "\n".join(lines)

    def handle(self, action: Mapping[str, Any]) -> dict:
        verb = str(action.get("verb") or "")
        outcome_id = str(action.get("target") or "")
        conversation_id = str(action.get("_conversation_id") or "")
        speaker = str(action.get("_speaker") or "")
        opening = self._active.get(conversation_id)
        if opening is None or opening.get("outcome_id") != outcome_id:
            raise ValueError("outcome was not offered in this conversation")
        if opening.get("speaker", "").casefold() != speaker.casefold():
            raise ValueError("outcome audience does not match this conversation")
        movement = {
            "outcome_surface": "surfaced",
            "outcome_hold": "held",
            "outcome_private": "private",
        }.get(verb)
        if movement is None:
            raise ValueError("unknown autonomous outcome movement")
        visible = _text(action.get("_visible_reply"), 12000)
        if movement == "surfaced" and len(_tokens(visible)) < 2:
            raise ValueError(
                "surface marker requires substantive visible reply text")
        record = self._append({
            "kind": f"outcome_{movement}", "outcome_id": outcome_id,
            "conversation_id": conversation_id,
            "thread_id": opening.get("thread_id") or "",
            "speaker": speaker.casefold(),
            "visible_reply_digest": (
                _digest(visible) if movement == "surfaced" else ""),
            "visible_reply_included": False,
        })
        self._active.pop(conversation_id, None)
        return {"ok": True, "movement": movement,
                "outcome_id": outcome_id,
                "record_digest": _digest(record)}

    def settle_quiet(self, conversation_id: str) -> dict | None:
        opening = self._active.pop(str(conversation_id or ""), None)
        if opening is None:
            return None
        self._append({
            "kind": "outcome_quiet",
            "outcome_id": opening["outcome_id"],
            "conversation_id": opening["conversation_id"],
            "thread_id": opening.get("thread_id") or "",
            "content_included": False,
        })
        return {"ok": True, "movement": "quiet",
                "outcome_id": opening["outcome_id"]}

    def status(self) -> dict:
        views = self._views().values()
        counts = {}
        for item in views:
            state = str(item.get("state") or "open")
            counts[state] = counts.get(state, 0) + 1
        return {
            "schema_version": self.SCHEMA_VERSION,
            "owner": self.owner, "audience": self.audience,
            "counts": counts, "active_openings": len(self._active),
            "active_thread_decisions": len(self._active_decisions),
            "active_conversation_threads": len([
                thread_id for thread_id in self._present_threads]),
            "active_event_streams": sum(
                len(listeners)
                for listeners in self._thread_subscribers.values()),
            "requires_inbound_conversation": True,
            "supports_active_conversation": True,
            "active_conversation_clock": "durable_inbound_boundary",
            "organ_completion_selects_speech": False,
            "automatic_notifications": False,
            "canonical_content_copied": False,
            "external_effects": False,
        }
