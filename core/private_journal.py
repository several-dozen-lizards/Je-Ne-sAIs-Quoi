"""Persona-owned loose notebook with an append-only, tamper-evident history.

This store is deliberately outside memory, ``my_life`` prompt assembly, the
Writing Desk, and autonomous circulation.  Reading is an explicit act.
"""
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

MAX_ENTRY_CHARS = 120_000


class PrivateJournal:
    def __init__(self, persona_dir, *, owner: str):
        self.owner = str(owner or "").strip().casefold()
        if not self.owner:
            raise ValueError("private journal needs an owner")
        self.root = Path(persona_dir) / "private_journal"
        self.path = self.root / "entries.jsonl"
        self._lock = threading.Lock()

    @staticmethod
    def _digest(record: dict) -> str:
        value = {key: record[key] for key in (
            "schema", "entry_id", "owner", "created_at", "text",
            "previous_digest")}
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _records(self) -> list[dict]:
        if not self.path.is_file():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def append(self, text: str) -> dict:
        text = str(text or "")
        if not text.strip():
            raise ValueError("private journal entry is empty")
        if len(text) > MAX_ENTRY_CHARS:
            raise ValueError(
                f"private journal entry exceeds {MAX_ENTRY_CHARS} characters")
        with self._lock:
            records = self._records()
            record = {
                "schema": 1,
                "entry_id": f"journal_{uuid.uuid4().hex}",
                "owner": self.owner,
                "created_at": time.time(),
                "text": text,
                "previous_digest": (
                    str(records[-1].get("digest") or "") if records else ""),
            }
            record["digest"] = self._digest(record)
            self.root.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(
                    record, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return self._public(record, include_text=False)

    @staticmethod
    def _public(record: dict, *, include_text: bool) -> dict:
        value = {
            "entry_id": record.get("entry_id"),
            "created_at": record.get("created_at"),
            "chars": len(str(record.get("text") or "")),
            "digest": record.get("digest"),
        }
        if include_text:
            value["text"] = str(record.get("text") or "")
        return value

    def entries(self, *, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        return [self._public(record, include_text=False)
                for record in self._records()[-limit:]]

    def read(self, entry_id: str) -> dict:
        wanted = str(entry_id or "")
        for record in reversed(self._records()):
            if record.get("entry_id") == wanted:
                return self._public(record, include_text=True)
        raise ValueError("private journal entry does not exist")

    def resolve(self, selector: str) -> dict:
        """Explicit reader selector; ``latest`` is useful from a blank index."""
        selector = str(selector or "").strip()
        records = self._records()
        if selector.casefold() == "latest":
            if not records:
                raise ValueError("private journal has no entries")
            return self._public(records[-1], include_text=True)
        return self.read(selector)

    def index_context(self, *, limit: int = 100) -> str:
        entries = self.entries(limit=limit)
        if not entries:
            return "Your private journal index is empty."
        lines = [
            "Content-free index of your private journal.",
            "Opening an entry is a separate explicit action:",
        ]
        for entry in reversed(entries):
            lines.append(
                f"- {entry['entry_id']} | created_at "
                f"{float(entry['created_at'] or 0.0):.6f} | "
                f"{int(entry['chars'] or 0)} characters | "
                f"digest {entry['digest']}")
        return "\n".join(lines)

    def verify(self) -> dict:
        prior = ""
        records = self._records()
        for index, record in enumerate(records):
            if record.get("owner") != self.owner:
                return {"ok": False, "count": len(records),
                        "broken_at": index, "reason": "owner_mismatch"}
            if record.get("previous_digest") != prior:
                return {"ok": False, "count": len(records),
                        "broken_at": index, "reason": "chain_mismatch"}
            if record.get("digest") != self._digest(record):
                return {"ok": False, "count": len(records),
                        "broken_at": index, "reason": "digest_mismatch"}
            prior = str(record.get("digest") or "")
        return {"ok": True, "count": len(records),
                "head_digest": prior}

    def status(self) -> dict:
        verified = self.verify()
        return {
            "schema": 1,
            "owner": self.owner,
            "privacy": {
                "scope": "persona_private",
                "automatic_prompt_disclosure": False,
                "automatic_memory_admission": False,
                "automatic_circulation": False,
                "outward_effects": False,
                "mutation": "append_only",
            },
            "entries": self.entries(),
            "integrity": verified,
        }
