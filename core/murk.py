"""Persona-private mutable scratch space before memory or intention.

The working set contains current text.  Its audit trail is deliberately
content-free, so revision can replace words and release can genuinely remove
them without an append-only copy surviving elsewhere in this organ.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any


MAX_FRAGMENT_CHARS = 12_000
MAX_FRAGMENTS = 2_000


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unit(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number if math.isfinite(number) else 0.0))


class Murk:
    """Mutable current fragments with a content-free append-only audit."""

    def __init__(self, persona_dir, *, owner: str):
        self.owner = str(owner or "").strip().casefold()
        if not self.owner:
            raise ValueError("murk needs an owner")
        self.root = Path(persona_dir) / "body" / "murk"
        self.path = self.root / "fragments.json"
        self.audit_path = self.root / "audit.jsonl"
        self._lock = threading.RLock()

    def _load(self) -> dict:
        if not self.path.is_file():
            return {"schema": 1, "owner": self.owner, "fragments": []}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("schema") != 1 or value.get("owner") != self.owner:
            raise ValueError("murk working set owner or schema mismatch")
        fragments = value.get("fragments")
        if not isinstance(fragments, list):
            raise ValueError("murk working set is malformed")
        return value

    def _save(self, value: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def _audit(self, *, operation: str, fragment_id: str, at: float,
               old_digest: str = "", new_digest: str = "") -> None:
        record = {
            "schema": 1,
            "owner": self.owner,
            "operation": operation,
            "fragment_id": fragment_id,
            "at": at,
            "old_digest": old_digest,
            "new_digest": new_digest,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _public(fragment: dict, *, include_text: bool,
                now: float | None = None) -> dict:
        now = time.time() if now is None else float(now)
        age_days = max(
            0.0, (now - float(fragment.get("touched_at") or now)) / 86400.0)
        recurrence = _unit(
            math.log1p(float(fragment.get("revisit_count") or 0)) / math.log(8))
        unfinished = _unit(fragment.get("unfinished", 1.0))
        contradiction = _unit(fragment.get("contradiction", 0.0))
        # Prominence fades continuously but recurring, unfinished, or
        # contradictory material resists disappearance.  It selects nothing.
        retention = math.exp(-math.log(2) * age_days / 21.0)
        prominence = _unit(
            .48 * retention + .22 * recurrence
            + .18 * unfinished + .12 * contradiction)
        value = {
            "fragment_id": fragment["fragment_id"],
            "created_at": fragment["created_at"],
            "touched_at": fragment["touched_at"],
            "chars": len(fragment["text"]),
            "digest": _digest(fragment["text"]),
            "revisit_count": int(fragment.get("revisit_count") or 0),
            "signals": {
                "age_days": round(age_days, 6),
                "recurrence": round(recurrence, 6),
                "unfinished": round(unfinished, 6),
                "contradiction": round(contradiction, 6),
                "prominence": round(prominence, 6),
            },
        }
        if include_text:
            value["text"] = fragment["text"]
        return value

    def create(self, text: str, *, unfinished: float = 1.0,
               contradiction: float = 0.0, now: float | None = None) -> dict:
        text = str(text or "")
        if not text.strip():
            raise ValueError("murk fragment is empty")
        if len(text) > MAX_FRAGMENT_CHARS:
            raise ValueError(
                f"murk fragment exceeds {MAX_FRAGMENT_CHARS} characters")
        at = time.time() if now is None else float(now)
        with self._lock:
            value = self._load()
            if len(value["fragments"]) >= MAX_FRAGMENTS:
                raise ValueError("murk fragment capacity reached")
            fragment = {
                "fragment_id": f"murk_{uuid.uuid4().hex}",
                "created_at": at,
                "touched_at": at,
                "text": text,
                "revisit_count": 0,
                "unfinished": _unit(unfinished),
                "contradiction": _unit(contradiction),
            }
            value["fragments"].append(fragment)
            self._save(value)
            self._audit(
                operation="created", fragment_id=fragment["fragment_id"],
                at=at, new_digest=_digest(text))
            return self._public(fragment, include_text=False, now=at)

    def fragments(self, *, limit: int = 100,
                  now: float | None = None) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        values = self._load()["fragments"]
        return [
            self._public(item, include_text=False, now=now)
            for item in values[-limit:]
        ]

    def _find(self, value: dict, selector: str) -> tuple[int, dict]:
        selector = str(selector or "").strip()
        fragments = value["fragments"]
        if selector.casefold() == "latest":
            if not fragments:
                raise ValueError("murk has no fragments")
            return len(fragments) - 1, fragments[-1]
        for index in range(len(fragments) - 1, -1, -1):
            if fragments[index].get("fragment_id") == selector:
                return index, fragments[index]
        raise ValueError("murk fragment does not exist")

    def open(self, selector: str, *, now: float | None = None) -> dict:
        at = time.time() if now is None else float(now)
        with self._lock:
            value = self._load()
            _index, fragment = self._find(value, selector)
            fragment["touched_at"] = at
            fragment["revisit_count"] = int(
                fragment.get("revisit_count") or 0) + 1
            self._save(value)
            self._audit(
                operation="revisited", fragment_id=fragment["fragment_id"],
                at=at, old_digest=_digest(fragment["text"]),
                new_digest=_digest(fragment["text"]))
            return self._public(fragment, include_text=True, now=at)

    def revise(self, selector: str, text: str, *,
               unfinished: float | None = None,
               contradiction: float | None = None,
               now: float | None = None) -> dict:
        text = str(text or "")
        if not text.strip():
            raise ValueError("murk revision is empty; release it explicitly")
        if len(text) > MAX_FRAGMENT_CHARS:
            raise ValueError(
                f"murk fragment exceeds {MAX_FRAGMENT_CHARS} characters")
        at = time.time() if now is None else float(now)
        with self._lock:
            value = self._load()
            _index, fragment = self._find(value, selector)
            old_digest = _digest(fragment["text"])
            fragment["text"] = text
            fragment["touched_at"] = at
            fragment["revisit_count"] = int(
                fragment.get("revisit_count") or 0) + 1
            if unfinished is not None:
                fragment["unfinished"] = _unit(unfinished)
            if contradiction is not None:
                fragment["contradiction"] = _unit(contradiction)
            self._save(value)
            self._audit(
                operation="revised", fragment_id=fragment["fragment_id"],
                at=at, old_digest=old_digest, new_digest=_digest(text))
            return self._public(fragment, include_text=False, now=at)

    def release(self, selector: str, *, now: float | None = None) -> dict:
        """Remove current text; the audit retains no recoverable content."""
        at = time.time() if now is None else float(now)
        with self._lock:
            value = self._load()
            index, fragment = self._find(value, selector)
            fragment_id = fragment["fragment_id"]
            old_digest = _digest(fragment["text"])
            del value["fragments"][index]
            self._save(value)
            self._audit(
                operation="released", fragment_id=fragment_id, at=at,
                old_digest=old_digest)
            return {"fragment_id": fragment_id, "released": True}

    def index_context(self, *, limit: int = 100) -> str:
        fragments = self.fragments(limit=limit)
        if not fragments:
            return "Your murk is empty."
        lines = [
            "Content-free index of your private mutable murk.",
            "Opening, revising, and releasing are separate explicit actions:",
        ]
        for item in sorted(
                fragments,
                key=lambda entry: (
                    entry["signals"]["prominence"], entry["touched_at"]),
                reverse=True):
            lines.append(
                f"- {item['fragment_id']} | touched_at "
                f"{float(item['touched_at']):.6f} | {item['chars']} characters "
                f"| prominence {item['signals']['prominence']:.6f} | "
                f"digest {item['digest']}")
        return "\n".join(lines)

    def status(self) -> dict:
        fragments = self.fragments(limit=1000)
        return {
            "schema": 1,
            "owner": self.owner,
            "mode": "private_mutable_scratch",
            "fragment_count": len(fragments),
            "fragments": fragments,
            "privacy": {
                "scope": "persona_private",
                "automatic_prompt_disclosure": False,
                "automatic_memory_admission": False,
                "automatic_intention_admission": False,
                "automatic_circulation": False,
                "outward_effects": False,
                "content_free_audit": True,
            },
            "decay": {
                "prominence_only": True,
                "automatic_content_deletion": False,
                "explicit_release_erases_working_text": True,
            },
        }
