"""Read-only household browser for canonical conversation ledgers.

The text archives are useful human-openable mirrors, but the append-only
``conversations.jsonl`` files remain lifecycle truth.  This module projects
those ledgers for the local Nexus UI without changing, repairing, or closing
any conversation record.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


TERMINAL_KINDS = {
    "conversation_completed",
    "conversation_failed",
    "conversation_interrupted",
    "conversation_snapshot",
}
_STATUS = {
    "conversation_completed": "completed",
    "conversation_failed": "failed",
    "conversation_interrupted": "interrupted",
    "conversation_snapshot": "completed",
}
_SPACE_RE = re.compile(r"\s+")


def _inside(parent: str, child: str) -> bool:
    parent = os.path.realpath(parent)
    child = os.path.realpath(child)
    try:
        return os.path.commonpath([parent, child]) == parent
    except ValueError:
        return False


def _persona_archives(root: str) -> list[dict]:
    personas_dir = os.path.join(os.path.abspath(root), "personas")
    found = []
    try:
        entries = list(os.scandir(personas_dir))
    except OSError:
        return found
    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        persona_dir = entry.path
        if not _inside(personas_dir, persona_dir):
            continue
        roster_path = os.path.join(persona_dir, "roster.yaml")
        if not os.path.isfile(roster_path):
            continue
        try:
            with open(roster_path, encoding="utf-8") as handle:
                roster = yaml.safe_load(handle) or {}
        except (OSError, TypeError, ValueError, yaml.YAMLError):
            continue
        if roster.get("kind", "model_persona") != "model_persona":
            continue
        ledger = os.path.join(persona_dir, "history", "conversations.jsonl")
        found.append({
            "id": entry.name,
            "label": str(roster.get("display_name") or entry.name),
            "kind": "persona",
            "ledger": ledger,
            "has_archive": os.path.isfile(ledger),
        })
    return sorted(found, key=lambda item: item["label"].casefold())


def available_archives(root: str) -> list[dict]:
    """Return the explicit Nexus/persona archive allowlist."""
    root = os.path.abspath(root)
    room_ledger = os.path.join(root, "room", "conversations.jsonl")
    return [{
        "id": "nexus",
        "label": "Nexus",
        "kind": "nexus",
        "ledger": room_ledger,
        "has_archive": os.path.isfile(room_ledger),
    }, *_persona_archives(root)]


def _resolve_archive(root: str, owner: str) -> dict:
    wanted = str(owner or "").strip()
    for item in available_archives(root):
        if item["id"] == wanted:
            return item
    raise ValueError(f"unknown conversation archive '{wanted}'")


def _one_line(value, limit: int = 180) -> str:
    text = _SPACE_RE.sub(" ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:max(1, limit - 1)].rstrip() + "…"


def _terminal_conversations(path: str) -> tuple[list[dict], int]:
    conversations: dict[str, list[dict]] = {}
    malformed = 0
    if not os.path.isfile(path):
        return [], malformed
    try:
        with open(path, encoding="utf-8") as handle:
            for ordinal, line in enumerate(handle):
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    malformed += 1
                    continue
                cid = str(record.get("conversation_id") or "")
                if not cid:
                    continue
                record["_archive_ordinal"] = ordinal
                conversations.setdefault(cid, []).append(record)
    except OSError:
        return [], malformed

    projected = []
    for cid, records in conversations.items():
        terminal = next((row for row in reversed(records)
                         if row.get("kind") in TERMINAL_KINDS), None)
        if terminal is None:
            continue
        admission = next((row for row in records
                          if row.get("kind") == "conversation_admitted"), None)
        base = admission or terminal
        reply = str(terminal.get("reply") or "")
        if not reply and terminal.get("kind") in {
                "conversation_failed", "conversation_interrupted"}:
            reply = "".join(str(row.get("text") or "") for row in records
                            if row.get("kind") == "conversation_delta")
        started_at = str(base.get("occurred_at")
                         or base.get("recorded_at")
                         or terminal.get("occurred_at")
                         or terminal.get("recorded_at") or "")
        images = []
        for image in list(base.get("images") or []):
            if isinstance(image, dict):
                images.append(str(image.get("name") or image.get("path")
                                  or image.get("id") or "image"))
            else:
                images.append(str(image))
        projected.append({
            "conversation_id": cid,
            "started_at": started_at,
            "recorded_at": str(terminal.get("recorded_at") or started_at),
            "speaker": str(base.get("speaker") or "Human"),
            "channel": str(base.get("channel") or "chat"),
            "source": str(base.get("source") or "turn"),
            "message": str(base.get("message") or ""),
            "reply": reply,
            "images": images,
            "status": _STATUS.get(terminal.get("kind"),
                                  str(terminal.get("kind") or "unknown")),
            "error": str(terminal.get("error") or ""),
            "error_type": str(terminal.get("error_type") or ""),
            "interruption_reason": str(terminal.get("reason") or ""),
            "_memory_id": str(terminal.get("memory_id")
                              or (terminal.get("fields") or {}).get(
                                  "memory_id") or ""),
            "_archive_ordinal": int(terminal.get("_archive_ordinal") or 0),
        })
    projected.sort(key=lambda row: (row["started_at"],
                                    row["_archive_ordinal"]), reverse=True)
    # A completed lifecycle can later be backfilled from the memory organ as
    # a historical snapshot.  They carry the same exact memory_id, so collapse
    # that causal duplicate without guessing from text similarity or timing.
    deduplicated = []
    memory_positions = {}
    for row in projected:
        memory_id = row.get("_memory_id")
        if not memory_id:
            deduplicated.append(row)
            continue
        prior = memory_positions.get(memory_id)
        if prior is None:
            memory_positions[memory_id] = len(deduplicated)
            deduplicated.append(row)
            continue
        existing = deduplicated[prior]
        if (existing.get("source") == "memory_backfill"
                and row.get("source") != "memory_backfill"):
            deduplicated[prior] = row
    return deduplicated, malformed


def _matches(record: dict, query: str) -> bool:
    if not query:
        return True
    needle = query.casefold()
    return needle in "\n".join(str(record.get(key) or "") for key in (
        "started_at", "speaker", "channel", "source", "message", "reply",
        "status", "error", "interruption_reason")).casefold()


def _public_owner(item: dict) -> dict:
    return {key: item[key] for key in (
        "id", "label", "kind", "has_archive")}


def _archive_timezone(name: str):
    wanted = str(name or "UTC").strip()[:100] or "UTC"
    try:
        return ZoneInfo(wanted), wanted
    except (ValueError, ZoneInfoNotFoundError):
        return timezone.utc, "UTC"


def _day_key(record: dict, tz) -> str:
    raw_stamp = record.get("started_at") or record.get("recorded_at") or ""
    stamp = str(raw_stamp).strip()
    try:
        # The room ledger contains both modern ISO-8601 receipts and older
        # Unix-second receipts.  They are the same time axis, not separate
        # calendar labels.
        if re.fullmatch(r"-?\d+(?:\.\d+)?", stamp):
            epoch = float(stamp)
            if abs(epoch) >= 100_000_000_000:
                epoch /= 1000.0
            parsed = datetime.fromtimestamp(epoch, tz=timezone.utc)
        else:
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(tz).date().isoformat()
    except (OSError, OverflowError, TypeError, ValueError):
        match = re.match(r"^(\d{4}-\d{2}-\d{2})", stamp)
        return match.group(1) if match else "unknown"


def _group_days(conversations: list[dict], tz) -> dict[str, list[dict]]:
    days = {}
    for conversation in conversations:
        days.setdefault(_day_key(conversation, tz), []).append(conversation)
    return days


def list_days(root: str, owner: str, *, query: str = "", offset: int = 0,
              limit: int = 45, timezone_name: str = "UTC") -> dict:
    """List local-calendar days; search selects days, not partial transcripts."""
    archive = _resolve_archive(root, owner)
    offset = max(0, int(offset))
    limit = max(1, min(180, int(limit)))
    query = str(query or "").strip()[:500]
    tz, resolved_timezone = _archive_timezone(timezone_name)
    conversations, malformed = _terminal_conversations(archive["ledger"])
    grouped = _group_days(conversations, tz)
    day_rows = []
    for day, records in grouped.items():
        matching = [record for record in records if _matches(record, query)]
        if query and not matching:
            continue
        speakers = []
        for record in reversed(records):
            speaker = str(record.get("speaker") or "")
            if speaker and speaker not in speakers:
                speakers.append(speaker)
        newest = records[0]
        day_rows.append({
            "day": day,
            "entry_count": len(records),
            "matching_entry_count": len(matching) if query else len(records),
            "speakers": speakers,
            "first_at": records[-1]["started_at"],
            "last_at": newest["started_at"],
            "latest_preview": _one_line(newest.get("message"), 150),
        })
    day_rows.sort(key=lambda row: row["day"], reverse=True)
    page = day_rows[offset:offset + limit]
    return {
        "owner": _public_owner(archive),
        "timezone": resolved_timezone,
        "query": query,
        "offset": offset,
        "limit": limit,
        "total_days": len(day_rows),
        "total_entries": sum(row["entry_count"] for row in day_rows),
        "has_more": offset + len(page) < len(day_rows),
        "days": page,
        "integrity": {
            "source": "canonical_conversation_ledger",
            "read_only": True,
            "malformed_lines": malformed,
            "open_conversations_omitted": True,
            "search_selects_complete_days": True,
        },
    }


def read_day(root: str, owner: str, day: str, *,
             timezone_name: str = "UTC") -> dict:
    """Read every terminal entry in one exact local-calendar day."""
    archive = _resolve_archive(root, owner)
    wanted = str(day or "").strip()
    try:
        datetime.strptime(wanted, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"invalid archive day '{wanted}'") from error
    tz, resolved_timezone = _archive_timezone(timezone_name)
    conversations, malformed = _terminal_conversations(archive["ledger"])
    grouped = _group_days(conversations, tz)
    if wanted not in grouped:
        raise ValueError(f"unknown archive day '{wanted}'")
    ordered_days = sorted(grouped, reverse=True)
    index = ordered_days.index(wanted)
    records = list(reversed(grouped[wanted]))
    public_records = [{key: value for key, value in record.items()
                       if not key.startswith("_")} for record in records]
    return {
        "owner": _public_owner(archive),
        "timezone": resolved_timezone,
        "day": wanted,
        "entry_count": len(public_records),
        "conversations": public_records,
        "newer_day": ordered_days[index - 1] if index > 0 else None,
        "older_day": (ordered_days[index + 1]
                      if index + 1 < len(ordered_days) else None),
        "integrity": {
            "source": "canonical_conversation_ledger",
            "read_only": True,
            "malformed_lines": malformed,
            "complete_local_day": True,
        },
    }


def list_conversations(root: str, owner: str, *, query: str = "",
                       offset: int = 0, limit: int = 60) -> dict:
    """List bounded previews from one allowlisted canonical ledger."""
    archive = _resolve_archive(root, owner)
    offset = max(0, int(offset))
    limit = max(1, min(200, int(limit)))
    query = str(query or "").strip()[:500]
    conversations, malformed = _terminal_conversations(archive["ledger"])
    matches = [row for row in conversations if _matches(row, query)]
    page = matches[offset:offset + limit]
    return {
        "owner": _public_owner(archive),
        "query": query,
        "offset": offset,
        "limit": limit,
        "total": len(matches),
        "has_more": offset + len(page) < len(matches),
        "conversations": [{
            "conversation_id": row["conversation_id"],
            "started_at": row["started_at"],
            "speaker": row["speaker"],
            "channel": row["channel"],
            "source": row["source"],
            "status": row["status"],
            "message_preview": _one_line(row["message"]),
            "reply_preview": _one_line(row["reply"]),
            "image_count": len(row["images"]),
        } for row in page],
        "integrity": {
            "source": "canonical_conversation_ledger",
            "read_only": True,
            "malformed_lines": malformed,
            "open_conversations_omitted": True,
        },
    }


def read_conversation(root: str, owner: str,
                      conversation_id: str) -> dict:
    """Read one exact terminal conversation from an allowlisted ledger."""
    archive = _resolve_archive(root, owner)
    conversations, malformed = _terminal_conversations(archive["ledger"])
    wanted = str(conversation_id or "")
    for index, row in enumerate(conversations):
        if row["conversation_id"] != wanted:
            continue
        item = {key: value for key, value in row.items()
                if not key.startswith("_archive_")}
        return {
            "owner": _public_owner(archive),
            "conversation": item,
            "newer_conversation_id": (
                conversations[index - 1]["conversation_id"]
                if index > 0 else None),
            "older_conversation_id": (
                conversations[index + 1]["conversation_id"]
                if index + 1 < len(conversations) else None),
            "integrity": {
                "source": "canonical_conversation_ledger",
                "read_only": True,
                "malformed_lines": malformed,
            },
        }
    raise ValueError(f"unknown conversation '{wanted}'")
