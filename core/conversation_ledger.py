"""Append-only conversation truth.

Memory is selective and harvest is derivative.  This ledger is neither: it
records that a conversational event was admitted before work begins and then
records how it ended.  A crash can therefore leave an honest open admission,
never an interaction that only existed in the UI.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import threading
import uuid


SCHEMA_VERSION = 1
TERMINAL_KINDS = {"conversation_completed", "conversation_failed",
                  "conversation_interrupted", "conversation_snapshot"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationLedger:
    """One append-only JSONL stream with crash recovery and idempotent IDs."""

    def __init__(self, path: str, *, owner: str, scope: str = "persona"):
        self.path = os.path.abspath(path)
        self.owner = str(owner)
        self.scope = str(scope)
        self._lock = threading.RLock()
        self._states = {}
        self._records = 0
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._load_state()
        self._recover_open_admissions()

    def _load_state(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    continue
                self._records += 1
                cid = str(record.get("conversation_id") or "")
                if cid and record.get("kind") != "conversation_delta":
                    self._states[cid] = record.get("kind")

    def _append(self, record: dict) -> dict:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "record_id": "conversation_record_" + uuid.uuid4().hex,
            "recorded_at": _now(),
            "owner": self.owner,
            "scope": self.scope,
            **record,
        }
        encoded = (json.dumps(payload, ensure_ascii=False,
                              separators=(",", ":")) + "\n")
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            self._records += 1
            cid = str(payload.get("conversation_id") or "")
            if cid and payload.get("kind") != "conversation_delta":
                self._states[cid] = payload.get("kind")
        return payload

    def _recover_open_admissions(self):
        pending = [cid for cid, kind in self._states.items()
                   if kind == "conversation_admitted"]
        for cid in pending:
            self.interrupt(cid, reason="process_restarted_before_terminal_record")

    def admit(self, *, conversation_id: str = "", channel: str = "chat",
              speaker: str = "", speaker_account: str = "",
              user_persona: str = "", message: str = "", images=None,
              source: str = "turn") -> str:
        cid = str(conversation_id or ("conversation_" + uuid.uuid4().hex))
        with self._lock:
            if cid in self._states:
                return cid
            self._append({
                "kind": "conversation_admitted",
                "conversation_id": cid,
                "channel": str(channel or "chat"),
                "speaker": str(speaker or ""),
                "speaker_account": str(speaker_account or speaker or ""),
                "user_persona": str(user_persona or ""),
                "message": str(message or ""),
                "images": list(images or []),
                "source": str(source or "turn"),
            })
        return cid

    def complete(self, conversation_id: str, *, reply: str = "",
                 memory_id: str = "", timing_ms=None, receipts=None) -> dict:
        return self._terminal(conversation_id, "conversation_completed", {
            "reply": str(reply or ""),
            "memory_id": str(memory_id or ""),
            "timing_ms": timing_ms,
            "receipts": dict(receipts or {}),
        })

    def delta(self, conversation_id: str, text: str) -> dict:
        """Persist streamed speech before a client is allowed to display it."""
        cid = str(conversation_id or "")
        if not cid or self._states.get(cid) != "conversation_admitted":
            raise ValueError(f"conversation '{cid}' is not open")
        return self._append({"kind": "conversation_delta",
                             "conversation_id": cid,
                             "text": str(text or "")})

    def fail(self, conversation_id: str, error: BaseException) -> dict:
        return self._terminal(conversation_id, "conversation_failed", {
            "error_type": type(error).__name__,
            "error": str(error)[:2000],
        })

    def interrupt(self, conversation_id: str, *, reason: str) -> dict:
        return self._terminal(conversation_id, "conversation_interrupted", {
            "reason": str(reason or "interrupted")[:500],
        })

    def _terminal(self, conversation_id: str, kind: str, fields: dict) -> dict:
        cid = str(conversation_id or "")
        if not cid:
            raise ValueError("a terminal conversation record needs an id")
        with self._lock:
            existing = self._states.get(cid)
            if existing in TERMINAL_KINDS:
                return {"conversation_id": cid, "kind": existing,
                        "duplicate": True}
            if existing is None:
                raise ValueError(f"conversation '{cid}' was not admitted")
            return self._append({"kind": kind, "conversation_id": cid,
                                 **fields})

    def snapshot(self, *, conversation_id: str, channel: str, speaker: str,
                 message: str, reply: str, timestamp: str = "",
                 source: str = "legacy", fields=None) -> bool:
        """Import one historical completed pair without inventing a lifecycle."""
        cid = str(conversation_id)
        with self._lock:
            if cid in self._states:
                return False
            self._append({
                "kind": "conversation_snapshot",
                "conversation_id": cid,
                "occurred_at": str(timestamp or ""),
                "channel": str(channel or "chat"),
                "speaker": str(speaker or ""),
                "message": str(message or ""),
                "reply": str(reply or ""),
                "source": str(source or "legacy"),
                "fields": dict(fields or {}),
            })
            return True

    def backfill_memories(self, memories) -> int:
        added = 0
        for memory in memories or []:
            if memory.get("type") != "turn":
                continue
            fields = memory.get("fields") or {}
            mid = str(memory.get("id") or "")
            if not mid:
                continue
            added += int(self.snapshot(
                conversation_id="memory:" + mid,
                channel=fields.get("channel", "chat"),
                speaker=fields.get("speaker", ""),
                message=fields.get("message_full", ""),
                reply=fields.get("reply_full", memory.get("content", "")),
                timestamp=memory.get("timestamp", ""),
                source="memory_backfill",
                fields={
                    "memory_id": mid,
                    "autonomous": bool(fields.get("autonomous")),
                    "user_persona": fields.get("user_persona"),
                    "speaker_account": fields.get("speaker_account"),
                }))
        return added

    def status(self) -> dict:
        pending = sum(kind == "conversation_admitted"
                      for kind in self._states.values())
        return {"schema_version": SCHEMA_VERSION, "records": self._records,
                "conversations": len(self._states), "pending": pending}
