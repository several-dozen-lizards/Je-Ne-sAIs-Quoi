"""Privacy-safe aggregation for the household model-call dashboard."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG = os.path.join(ROOT, "logs", "model_calls.jsonl")
MAX_READ_BYTES = 8 * 1024 * 1024

_RECENT_FIELDS = (
    "ts", "persona", "purpose", "provider", "model", "spec_name",
    "status", "total_ms", "provider_ms", "prompt_ms", "gen_ms", "load_ms",
    "first_token_ms", "input_tokens",
    "output_tokens", "reasoning_tokens", "cache_read_tokens",
    "cache_write_tokens", "finish_reason", "thinking_type", "attempts",
)


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _read_lines(path: str, max_bytes: int = MAX_READ_BYTES):
    if not os.path.exists(path):
        return [], False
    size = os.path.getsize(path)
    truncated = size > max_bytes
    with open(path, "rb") as handle:
        if truncated:
            handle.seek(-max_bytes, os.SEEK_END)
            handle.readline()  # discard the partial first record
        data = handle.read()
    return data.decode("utf-8", errors="replace").splitlines(), truncated


def read_receipts(path: str = None, *, hours: int = 24) -> dict:
    """Read a bounded tail and expose counts only, never prompt content."""
    path = path or os.environ.get("JNSQ_MODEL_CALL_LOG") or DEFAULT_LOG
    lines, truncated = _read_lines(path)
    malformed = 0
    records = []
    cutoff = None
    if hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            malformed += 1
            continue
        stamp = _timestamp(record.get("ts"))
        if cutoff is not None and (stamp is None or stamp < cutoff):
            continue
        records.append(record)
    return summarize_receipts(
        records, hours=hours, malformed=malformed, tail_truncated=truncated)


def _number(record, key):
    value = record.get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _aggregate(records):
    calls = len(records)
    errors = sum(record.get("status") != "ok" for record in records)
    measured = [record for record in records
                if record.get("status") == "ok"
                and isinstance(record.get("total_ms"), (int, float))]
    failed_measured = [record for record in records
                       if record.get("status") != "ok"
                       and isinstance(record.get("total_ms"), (int, float))]
    durations = sorted(_number(record, "total_ms") for record in measured)

    def measured_sum(key):
        values = [_number(record, key) for record in measured
                  if isinstance(record.get(key), (int, float))]
        return round(sum(values), 3) if values else None

    return {
        "calls": calls,
        "errors": errors,
        "model_ms": round(sum(durations), 3),
        "provider_ms": measured_sum("provider_ms"),
        "prompt_ms": measured_sum("prompt_ms"),
        "gen_ms": measured_sum("gen_ms"),
        "load_ms": measured_sum("load_ms"),
        "error_ms": round(sum(
            _number(record, "total_ms") for record in failed_measured), 3),
        "median_ms": round(
            ((durations[(len(durations) - 1) // 2]
              + durations[len(durations) // 2]) / 2), 3)
            if durations else None,
        "input_tokens": int(sum(_number(r, "input_tokens") for r in records)),
        "output_tokens": int(sum(_number(r, "output_tokens") for r in records)),
        "reasoning_tokens": int(sum(
            _number(r, "reasoning_tokens") for r in records)),
        "cache_read_tokens": int(sum(
            _number(r, "cache_read_tokens") for r in records)),
        "cache_write_tokens": int(sum(
            _number(r, "cache_write_tokens") for r in records)),
        "missing_usage": sum(
            r.get("input_tokens") is None and r.get("output_tokens") is None
            for r in records),
        "length_finishes": sum(
            r.get("finish_reason") == "length" for r in records),
    }


def summarize_receipts(records, *, hours=24, malformed=0,
                       tail_truncated=False) -> dict:
    groups = {name: defaultdict(list)
              for name in ("persona", "purpose", "model")}
    for record in records:
        for name in groups:
            groups[name][str(record.get(name) or "unknown")].append(record)
    grouped = {
        name: [dict(key=key, **_aggregate(items))
               for key, items in sorted(values.items())]
        for name, values in groups.items()
    }
    recent = [
        {key: record.get(key) for key in _RECENT_FIELDS
         if record.get(key) is not None}
        for record in records[-60:]
    ]
    recent.reverse()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": int(hours),
        "totals": _aggregate(records),
        "groups": grouped,
        "recent": recent,
        "integrity": {
            "malformed_lines": int(malformed),
            "tail_truncated": bool(tail_truncated),
            "privacy": "content-free counts and route metadata only",
        },
    }
