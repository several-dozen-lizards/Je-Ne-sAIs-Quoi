"""Persona-private relational questions that require an open conversation.

The organ persists wants directed toward another person.  It cannot initiate a
turn or send a message.  A matching inbound conversation may expose one
question as a witnessed choice; the ordinary persona reply remains the only
place where the question can actually be asked.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from core.volitional_choice import ChoiceLedger


MAX_QUESTION_CHARS = 900
QUESTION_ID = re.compile(r"^question_[0-9a-f]{16}$")


def _digest(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]


def _terms(value: str) -> set[str]:
    return {
        word.casefold() for word in re.findall(r"[A-Za-z0-9']+", value or "")
        if len(word) > 3}


def _overlap(left: str, right: str) -> float:
    a, b = _terms(left), _terms(right)
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


class OutwardCuriosity:
    """Append-only question lifecycle plus ephemeral conversation openings."""

    def __init__(self, persona_dir: str | os.PathLike[str], *,
                 owner: str, choice_ledger: ChoiceLedger = None):
        self.owner = str(owner)
        self.root = Path(persona_dir).resolve() / "body" / "outward_curiosity"
        self.path = self.root / "questions.jsonl"
        self.choice_ledger = choice_ledger or ChoiceLedger(persona_dir)
        self._lock = threading.RLock()
        self._active: dict[str, dict] = {}

    def _append(self, value: Mapping[str, Any]) -> dict:
        record = dict(value)
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def records(self) -> list[dict]:
        if not self.path.is_file():
            return []
        found = []
        with self._lock, self.path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    found.append(value)
        return found

    def questions(self, *, state: str | None = None) -> list[dict]:
        views: dict[str, dict] = {}
        for record in self.records():
            question_id = str(record.get("question_id") or "")
            if not question_id:
                continue
            view = views.setdefault(question_id, {
                "question_id": question_id, "state": "open",
                "opening_count": 0, "presentation_count": 0,
                "deferral_count": 0, "revision_count": 0})
            kind = record.get("kind")
            if kind == "question_formed":
                view.update({
                    "question": record.get("question"),
                    "audience": record.get("audience"),
                    "created_at": record.get("at"),
                })
            elif kind == "question_revised":
                view["question"] = record.get("question")
                view["revision_count"] += 1
            elif kind == "conversation_opening":
                view["opening_count"] += 1
                view["last_message_relevance"] = record.get(
                    "message_relevance", 0.0)
            elif kind == "question_presented":
                view["presentation_count"] += 1
            elif kind == "question_deferred":
                view["deferral_count"] += 1
            elif kind == "question_asked":
                view["state"] = "asked"
            elif kind == "question_released":
                view["state"] = "released"
            view["last_kind"] = kind
            view["updated_at"] = record.get("at")
        values = list(views.values())
        return [item for item in values
                if state is None or item.get("state") == state]

    def form(self, question: str, *, audience: str,
             conversation_id: str) -> dict:
        question = str(question or "").strip()
        audience = str(audience or "").strip()
        if not question or len(question) > MAX_QUESTION_CHARS:
            raise ValueError("private question is empty or too long")
        if not audience:
            raise ValueError("private question requires an exact audience")
        question_id = "question_" + _digest({
            "owner": self.owner, "question": question,
            "audience": audience.casefold(), "conversation": conversation_id,
        })
        if any(item["question_id"] == question_id for item in self.questions()):
            return next(item for item in self.questions()
                        if item["question_id"] == question_id)
        return self._append({
            "kind": "question_formed", "question_id": question_id,
            "at": time.time(), "question": question, "audience": audience,
            "conversation_id": str(conversation_id),
            "ownership": "persona_private",
        })

    def _projection(self, question: Mapping[str, Any],
                    message: str) -> dict:
        recurrence = min(1.0, (
            float(question.get("opening_count") or 0) + 1.0) / 3.0)
        relevance = _overlap(str(question.get("question") or ""), message)
        deferral = min(1.0, float(
            question.get("deferral_count") or 0) / 3.0)
        presentation = min(1.0, float(
            question.get("presentation_count") or 0) / 3.0)
        score = (
            .25  # unresolved want
            + .25  # exact relational opening
            + .22 * recurrence
            + .20 * relevance
            - .18 * deferral
            - .12 * presentation)
        return {
            "eligible": score >= .62,
            "score": round(score, 6),
            "threshold": .62,
            "signals": {
                "unresolved": 1.0, "exact_audience": 1.0,
                "recurrence": round(recurrence, 6),
                "message_relevance": round(relevance, 6),
                "deferral_friction": round(deferral, 6),
                "presentation_satiety": round(presentation, 6),
            },
            "selects_action": False,
        }

    def present(self, *, speaker: str, message: str, channel: str,
                conversation_id: str) -> dict | None:
        """Expose at most one question during an already inbound turn."""
        speaker = str(speaker or "").strip()
        conversation_id = str(conversation_id or "").strip()
        if not speaker or not conversation_id:
            return None
        candidates = []
        for question in self.questions(state="open"):
            if str(question.get("audience") or "").casefold() \
                    != speaker.casefold():
                continue
            projection = self._projection(question, message)
            self._append({
                "kind": "conversation_opening",
                "question_id": question["question_id"], "at": time.time(),
                "conversation_id": conversation_id, "speaker": speaker,
                "channel": str(channel or "chat"),
                "message_relevance": projection["signals"][
                    "message_relevance"],
            })
            if projection["eligible"]:
                candidates.append((projection["score"], question, projection))
        if not candidates:
            return None
        _score, question, projection = max(
            candidates, key=lambda item: (item[0], item[1]["question_id"]))
        episode = self.choice_ledger.open_fork(
            owner="outward_curiosity",
            run_id=f"curiosity-{conversation_id}-{question['question_id']}",
            candidate={
                "key": f"outward_curiosity:{question['question_id']}",
                "source": "outward_curiosity", "salience": projection["score"],
            },
            options=["quiet", "ask", "defer", "revise", "release"],
            projection=projection)
        self._append({
            "kind": "question_presented",
            "question_id": question["question_id"], "at": time.time(),
            "conversation_id": conversation_id,
            "choice_episode_id": episode["episode_id"],
            "projection": projection,
        })
        opening = {
            **question, "conversation_id": conversation_id,
            "choice_episode_id": episode["episode_id"],
            "projection": projection,
        }
        self._active[conversation_id] = opening
        return opening

    @staticmethod
    def render(opening: Mapping[str, Any] | None) -> str:
        if not opening:
            return ""
        qid = opening["question_id"]
        return (
            "A private question you previously kept has become eligible in "
            "this already-open conversation:\n"
            f"{opening['question']}\n\n"
            "This is a witnessed relational fork, not an instruction. You may "
            "ask the question naturally in your visible reply and append "
            f"<act>curiosity_ask {qid}</act>; leave it quiet; append "
            f"<act>curiosity_defer {qid}</act>; revise it privately with "
            f"<act>curiosity_revise {qid} :: NEW QUESTION</act>; or release "
            f"it with <act>curiosity_release {qid}</act>. The action marker "
            "is hidden. Do not claim it was asked unless you actually put the "
            "question in your visible reply."
        )

    def handle(self, action: Mapping[str, Any]) -> dict:
        verb = str(action.get("verb") or "")
        question_id = str(action.get("target") or "")
        conversation_id = str(action.get("_conversation_id") or "")
        speaker = str(action.get("_speaker") or "")
        opening = self._active.get(conversation_id)
        if opening is None or opening.get("question_id") != question_id:
            raise ValueError("question was not offered in this conversation")
        if str(opening.get("audience") or "").casefold() != speaker.casefold():
            raise ValueError("question audience does not match this opening")
        movement = {
            "curiosity_ask": "ask",
            "curiosity_defer": "defer",
            "curiosity_revise": "revise",
            "curiosity_release": "release",
        }.get(verb)
        if movement is None:
            raise ValueError("unknown curiosity movement")
        text = str(action.get("text") or "").strip()
        visible_text = str(action.get("_visible_reply") or "").strip()
        if movement == "ask" and (
                "?" not in visible_text
                or _overlap(
                    str(opening.get("question") or ""), visible_text) <= 0.0):
            raise ValueError(
                "ask marker requires the question in visible reply text")
        if movement == "revise" and (
                not text or len(text) > MAX_QUESTION_CHARS):
            raise ValueError("question revision is empty or too long")
        self.choice_ledger.commit_choice(
            opening["choice_episode_id"], action=movement,
            orientation="", basis="Chosen in an open conversation.")
        kind = {
            "ask": "question_asked", "defer": "question_deferred",
            "revise": "question_revised", "release": "question_released",
        }[movement]
        record = self._append({
            "kind": kind, "question_id": question_id, "at": time.time(),
            "conversation_id": conversation_id, "speaker": speaker,
            **({"question": text} if movement == "revise" else {}),
        })
        self.choice_ledger.settle_owner(
            opening["choice_episode_id"], accepted=True, outcome=movement,
            durable_ref=question_id)
        self.choice_ledger.encounter_consequence(
            opening["choice_episode_id"],
            candidate_key=f"conversation:{conversation_id}")
        self._active.pop(conversation_id, None)
        return {
            "ok": True, "movement": movement,
            "question_id": question_id,
            "record_digest": _digest(record),
        }

    def settle_quiet(self, conversation_id: str) -> dict | None:
        opening = self._active.pop(str(conversation_id or ""), None)
        if opening is None:
            return None
        self.choice_ledger.commit_choice(
            opening["choice_episode_id"], action="quiet",
            orientation="", basis="No curiosity movement was chosen.")
        self.choice_ledger.settle_owner(
            opening["choice_episode_id"], accepted=True, outcome="quiet",
            durable_ref=opening["question_id"])
        self.choice_ledger.encounter_consequence(
            opening["choice_episode_id"],
            candidate_key=f"conversation:{conversation_id}")
        return {"ok": True, "movement": "quiet",
                "question_id": opening["question_id"]}

    def status(self) -> dict:
        questions = self.questions()
        return {
            "owner": self.owner,
            "counts": {
                "open": sum(item["state"] == "open" for item in questions),
                "asked": sum(item["state"] == "asked" for item in questions),
                "released": sum(
                    item["state"] == "released" for item in questions),
            },
            "active_openings": len(self._active),
            "question_text_projected": False,
            "requires_inbound_conversation": True,
            "automatic_messaging": False,
            "external_effects": False,
            "journal_access": False,
        }
