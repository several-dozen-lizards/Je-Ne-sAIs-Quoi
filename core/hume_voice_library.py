"""Private household shelf for reusable Hume voice references."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import time
import uuid


_LOCK = threading.Lock()
_REF = re.compile(r"^[^\r\n]{1,160}$")


def _path(repo: str | Path) -> Path:
    return Path(repo) / "hume_voice_library.json"


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


def save_voice(repo: str | Path, label: str, reference: str) -> dict:
    label = str(label or "").strip()
    reference = str(reference or "").strip()
    if not label or len(label) > 80 or any(c in label for c in "\r\n"):
        raise ValueError("voice label must be one line between 1 and 80 characters")
    if not _REF.fullmatch(reference):
        raise ValueError("Hume voice reference must be one line under 161 characters")
    with _LOCK:
        rows = _read(repo)
        existing = next((row for row in rows if row.get("reference") == reference), None)
        if existing is None:
            existing = {"id": uuid.uuid4().hex, "reference": reference,
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            rows.append(existing)
        existing["label"] = label
        existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rows.sort(key=lambda row: str(row.get("label") or "").casefold())
        target = _path(repo)
        temporary = target.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"version": 1, "voices": rows}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return dict(existing)


def delete_voice(repo: str | Path, voice_id: str) -> bool:
    voice_id = str(voice_id or "").strip()
    with _LOCK:
        rows = _read(repo)
        kept = [row for row in rows if row.get("id") != voice_id]
        if len(kept) == len(rows):
            return False
        target = _path(repo)
        temporary = target.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"version": 1, "voices": kept}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return True
