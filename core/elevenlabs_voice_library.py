"""Private household shelf for reusable ElevenLabs voice IDs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import time
import uuid


_LOCK = threading.Lock()
_VOICE_ID = re.compile(r"^[^\r\n]{1,160}$")


def _path(repo: str | Path) -> Path:
    return Path(repo) / "elevenlabs_voice_library.json"


def _read(repo: str | Path) -> list[dict]:
    try:
        value = json.loads(_path(repo).read_text(encoding="utf-8"))
        rows = value.get("voices", []) if isinstance(value, dict) else []
        return [dict(row) for row in rows if isinstance(row, dict)]
    except (OSError, ValueError, TypeError):
        return []


def list_voices(repo: str | Path) -> list[dict]:
    with _LOCK:
        return _read(repo)


def save_voice(repo: str | Path, label: str, voice_id: str) -> dict:
    label = str(label or "").strip()
    voice_id = str(voice_id or "").strip()
    if not label or len(label) > 80 or any(c in label for c in "\r\n"):
        raise ValueError("voice label must be one line between 1 and 80 characters")
    if not _VOICE_ID.fullmatch(voice_id):
        raise ValueError("ElevenLabs voice ID must be one line under 161 characters")
    with _LOCK:
        rows = _read(repo)
        existing = next((row for row in rows if row.get("voice_id") == voice_id), None)
        if existing is None:
            existing = {"id": uuid.uuid4().hex, "voice_id": voice_id,
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            rows.append(existing)
        existing["label"] = label
        existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rows.sort(key=lambda row: str(row.get("label") or "").casefold())
        target = _path(repo)
        temporary = target.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"version": 1, "voices": rows}, handle,
                      ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return dict(existing)


def delete_voice(repo: str | Path, shelf_id: str) -> bool:
    shelf_id = str(shelf_id or "").strip()
    with _LOCK:
        rows = _read(repo)
        kept = [row for row in rows if row.get("id") != shelf_id]
        if len(kept) == len(rows):
            return False
        target = _path(repo)
        temporary = target.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"version": 1, "voices": kept}, handle,
                      ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return True
