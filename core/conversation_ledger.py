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
import re
import threading
import uuid


SCHEMA_VERSION = 1
TERMINAL_KINDS = {"conversation_completed", "conversation_failed",
                  "conversation_interrupted", "conversation_snapshot"}
SELF_INITIATED_SOURCES = frozenset({
    "self_initiated_contact", "self_initiated_private_contact",
})
DEFAULT_TEXT_ARCHIVE_BYTES = 1024 * 1024
_ARCHIVE_PART_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})(?:-part-(?P<part>\d{3}))?\.txt$")
_CONVERSATION_MARKER_RE = re.compile(r"^Conversation ID: (.+)$", re.MULTILINE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one_line(value) -> str:
    return " ".join(str(value or "").replace("\x00", "").splitlines()).strip()


class TextConversationArchive:
    """Readable, dated projection of a canonical conversation ledger.

    The JSONL ledger remains the source of truth.  These files are a
    human-openable mirror, split by date and then by a length threshold.
    """

    def __init__(self, directory: str, *, owner: str, scope: str,
                 max_bytes: int = DEFAULT_TEXT_ARCHIVE_BYTES):
        self.directory = os.path.abspath(directory)
        self.owner = str(owner)
        self.scope = str(scope)
        self.max_bytes = max(4096, int(max_bytes))
        self._projected = set()
        os.makedirs(self.directory, exist_ok=True)
        self._load_projected_ids()

    def _load_projected_ids(self):
        try:
            names = os.listdir(self.directory)
        except OSError:
            return
        for name in names:
            if not _ARCHIVE_PART_RE.fullmatch(name):
                continue
            path = os.path.join(self.directory, name)
            try:
                with open(path, encoding="utf-8") as handle:
                    self._projected.update(
                        _CONVERSATION_MARKER_RE.findall(handle.read()))
            except OSError:
                continue

    @staticmethod
    def _archive_date(record: dict) -> str:
        stamp = str(record.get("occurred_at")
                    or record.get("recorded_at") or "")
        match = re.match(r"^(\d{4}-\d{2}-\d{2})", stamp)
        return match.group(1) if match else datetime.now(
            timezone.utc).date().isoformat()

    def _header(self, date: str) -> str:
        return (
            "JNAIQ Conversation Archive\n"
            f"Owner: {self.owner}\n"
            f"Scope: {self.scope}\n"
            f"Date: {date} (UTC)\n"
            "Readable mirror; canonical lifecycle data remains in "
            "conversations.jsonl.\n\n"
        )

    def _path_for(self, date: str, entry_bytes: int) -> tuple[str, str]:
        candidates = []
        try:
            names = os.listdir(self.directory)
        except OSError:
            names = []
        for name in names:
            match = _ARCHIVE_PART_RE.fullmatch(name)
            if match and match.group("date") == date:
                candidates.append((
                    int(match.group("part") or 1),
                    os.path.join(self.directory, name)))
        if not candidates:
            return os.path.join(self.directory, f"{date}.txt"), self._header(date)
        part, path = max(candidates)
        try:
            current_bytes = os.path.getsize(path)
        except OSError:
            current_bytes = 0
        if current_bytes and current_bytes + entry_bytes <= self.max_bytes:
            return path, ""
        part += 1
        return os.path.join(
            self.directory, f"{date}-part-{part:03d}.txt"), self._header(date)

    def render(self, records: list[dict]) -> tuple[str, str]:
        admission = next((
            row for row in records
            if row.get("kind") == "conversation_admitted"), None)
        terminal = next((
            row for row in reversed(records)
            if row.get("kind") in TERMINAL_KINDS), None)
        if terminal is None:
            return "", ""
        base = admission or terminal
        cid = _one_line(terminal.get("conversation_id"))
        timestamp = str(base.get("occurred_at")
                        or base.get("recorded_at") or "")
        channel = _one_line(base.get("channel") or "chat")
        source = _one_line(base.get("source") or "turn")
        speaker = _one_line(base.get("speaker") or "Human")
        message = str(base.get("message") or "")
        images = list(base.get("images") or [])
        kind = terminal.get("kind")
        status = {
            "conversation_completed": "completed",
            "conversation_failed": "failed",
            "conversation_interrupted": "interrupted",
            "conversation_snapshot": "completed (historical snapshot)",
        }.get(kind, _one_line(kind))
        lines = [
            "=" * 80,
            f"[{timestamp}] {channel} conversation",
            f"Source: {source}",
            "",
            f"{speaker}:",
            message,
        ]
        if images:
            lines.extend(["", "Shared image references:"])
            for image in images:
                if isinstance(image, dict):
                    value = (image.get("name") or image.get("path")
                             or image.get("id") or image)
                else:
                    value = image
                lines.append(f"- {_one_line(value)}")
        reply = str(terminal.get("reply") or "")
        if not reply and kind in {"conversation_failed",
                                  "conversation_interrupted"}:
            reply = "".join(str(row.get("text") or "") for row in records
                            if row.get("kind") == "conversation_delta")
        if reply:
            lines.extend(["", f"{_one_line(self.owner).title() or 'Assistant'}:",
                          reply])
            if kind != "conversation_completed":
                lines.append("[partial reply preserved before termination]")
        if kind == "conversation_failed":
            lines.extend([
                "",
                "Failure: "
                f"{_one_line(terminal.get('error_type'))}: "
                f"{_one_line(terminal.get('error'))}",
            ])
        elif kind == "conversation_interrupted":
            lines.extend([
                "",
                f"Interruption: {_one_line(terminal.get('reason'))}",
            ])
        lines.extend(["", f"Status: {status}", f"Conversation ID: {cid}", "", ""])
        return cid, "\n".join(lines)

    def project(self, records: list[dict]) -> bool:
        cid, entry = self.render(records)
        if not cid or not entry or cid in self._projected:
            return False
        encoded = entry.encode("utf-8")
        terminal = next(row for row in reversed(records)
                        if row.get("kind") in TERMINAL_KINDS)
        date = self._archive_date(terminal)
        path, header = self._path_for(date, len(encoded))
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            if header:
                handle.write(header)
            handle.write(entry)
            handle.flush()
            os.fsync(handle.fileno())
        self._projected.add(cid)
        return True


def sync_text_archive(path: str, *, owner: str, scope: str = "persona",
                      text_archive_dir: str = None,
                      text_archive_max_bytes: int =
                      DEFAULT_TEXT_ARCHIVE_BYTES) -> dict:
    """Project terminal JSONL conversations without mutating the ledger."""
    path = os.path.abspath(path)
    archive = TextConversationArchive(
        text_archive_dir or os.path.join(os.path.dirname(path), "chat_archives"),
        owner=owner, scope=scope, max_bytes=text_archive_max_bytes)
    conversations = {}
    invalid_records = 0
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    invalid_records += 1
                    continue
                cid = str(record.get("conversation_id") or "")
                if cid:
                    conversations.setdefault(cid, []).append(record)
    projected = 0
    terminal = 0
    for records in conversations.values():
        if any(row.get("kind") in TERMINAL_KINDS for row in records):
            terminal += 1
            projected += int(archive.project(records))
    return {
        "ledger": path,
        "text_archive": archive.directory,
        "terminal_conversations": terminal,
        "projected": projected,
        "already_projected": terminal - projected,
        "invalid_records": invalid_records,
    }


class ConversationLedger:
    """One append-only JSONL stream with crash recovery and idempotent IDs."""

    def __init__(self, path: str, *, owner: str, scope: str = "persona",
                 text_archive_dir: str = None,
                 text_archive_max_bytes: int = DEFAULT_TEXT_ARCHIVE_BYTES):
        self.path = os.path.abspath(path)
        self.owner = str(owner)
        self.scope = str(scope)
        self._lock = threading.RLock()
        self._states = {}
        self._conversation_records = {}
        self._latest_inbound_by_thread = {}
        self._records = 0
        self._text_archive_error = ""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        archive_dir = text_archive_dir or os.path.join(
            os.path.dirname(self.path), "chat_archives")
        self.text_archive = TextConversationArchive(
            archive_dir, owner=self.owner, scope=self.scope,
            max_bytes=text_archive_max_bytes)
        self._load_state()
        self._recover_open_admissions()
        self._sync_text_archive()
        # Completed conversations are now represented in both durable stores;
        # retain only genuinely open lifecycle records in runtime memory.
        self._conversation_records = {
            cid: records for cid, records in self._conversation_records.items()
            if self._states.get(cid) == "conversation_admitted"}

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
                if cid:
                    self._conversation_records.setdefault(cid, []).append(record)
                if cid and record.get("kind") != "conversation_delta":
                    self._states[cid] = record.get("kind")
                self._track_inbound_boundary(record)

    @staticmethod
    def _recorded_epoch(record: dict) -> float:
        value = str(record.get("occurred_at")
                    or record.get("recorded_at") or "").strip()
        if not value:
            return 0.0
        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return 0.0

    def _track_inbound_boundary(self, record: dict):
        """Remember genuine human chat admissions by their durable thread.

        Browser presence is transport reachability, not conversational demand.
        Self-initiated resident deliveries therefore never advance this clock.
        """
        if record.get("kind") not in {
                "conversation_admitted", "conversation_snapshot"}:
            return
        if str(record.get("channel") or "chat") != "chat":
            return
        source = str(record.get("source") or "turn")
        if source in SELF_INITIATED_SOURCES:
            return
        if not str(record.get("message") or "").strip() \
                and not list(record.get("images") or ()):
            return
        thread_id = _one_line(record.get("conversation_thread_id"))
        if not thread_id:
            return
        boundary = {
            "conversation_id": str(record.get("conversation_id") or ""),
            "thread_id": thread_id,
            "recorded_at": str(record.get("occurred_at")
                               or record.get("recorded_at") or ""),
            "recorded_epoch": self._recorded_epoch(record),
            "content_included": False,
        }
        prior = self._latest_inbound_by_thread.get(thread_id)
        if prior is None or boundary["recorded_epoch"] >= \
                float(prior.get("recorded_epoch") or 0.0):
            self._latest_inbound_by_thread[thread_id] = boundary

    def latest_inbound_boundary(self, thread_id: str) -> dict | None:
        """Return content-free identity for the latest durable human turn."""
        with self._lock:
            boundary = self._latest_inbound_by_thread.get(
                _one_line(thread_id))
            return dict(boundary) if boundary else None

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
            if cid:
                self._conversation_records.setdefault(cid, []).append(payload)
            if cid and payload.get("kind") != "conversation_delta":
                self._states[cid] = payload.get("kind")
            self._track_inbound_boundary(payload)
            if payload.get("kind") in TERMINAL_KINDS:
                try:
                    self.text_archive.project(
                        self._conversation_records.get(cid, []))
                    self._text_archive_error = ""
                except OSError as error:
                    # The canonical fsync has already succeeded.  A readable
                    # mirror failure must not turn a completed conversation
                    # into a false provider failure; startup sync retries it.
                    self._text_archive_error = str(error)[:500]
                self._conversation_records.pop(cid, None)
        return payload

    def _sync_text_archive(self):
        for cid, records in self._conversation_records.items():
            if self._states.get(cid) in TERMINAL_KINDS:
                try:
                    self.text_archive.project(records)
                    self._text_archive_error = ""
                except OSError as error:
                    self._text_archive_error = str(error)[:500]

    def _recover_open_admissions(self):
        pending = [cid for cid, kind in self._states.items()
                   if kind == "conversation_admitted"]
        for cid in pending:
            self.interrupt(cid, reason="process_restarted_before_terminal_record")

    def admit(self, *, conversation_id: str = "", channel: str = "chat",
              speaker: str = "", speaker_account: str = "",
              user_persona: str = "", message: str = "", images=None,
              source: str = "turn", conversation_thread_id: str = "") -> str:
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
                "conversation_thread_id": _one_line(
                    conversation_thread_id),
            })
        return cid

    def admit_once(self, **fields) -> tuple[str, bool, str]:
        """Atomically admit a client-stable id and report prior state."""
        cid = str(fields.get("conversation_id") or
                  ("conversation_" + uuid.uuid4().hex))
        fields["conversation_id"] = cid
        with self._lock:
            prior = str(self._states.get(cid) or "")
            if prior:
                return cid, False, prior
            self.admit(**fields)
            return cid, True, "conversation_admitted"

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
                "conversations": len(self._states), "pending": pending,
                "text_archive": self.text_archive.directory,
                "text_archive_files": len([
                    name for name in os.listdir(self.text_archive.directory)
                    if _ARCHIVE_PART_RE.fullmatch(name)]),
                "text_archive_error": self._text_archive_error}
