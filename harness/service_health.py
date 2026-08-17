"""Content-free health events for non-model provider boundaries.

Model inference already has ``model_calls.jsonl``.  Voice and startup checks
need the same recovery semantics without inventing another operational truth
store or retaining provider response bodies.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import threading
import uuid

from harness.model_call_receipts import (_process_write_lock,
                                         classify_service_error)


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG = os.path.join(_ROOT, "logs", "service_health.jsonl")
MAX_READ_BYTES = 2 * 1024 * 1024
_WRITE_LOCK = threading.Lock()


def record_service_health(service: str, provider: str, resource: str = "",
                          *, status: str = "ok", error=None) -> dict:
    """Append one allowlisted lifecycle event; raw errors never cross."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
        "event_id": uuid.uuid4().hex,
        "service": str(service or "unknown")[:60],
        "provider": str(provider or "unknown")[:80],
        "resource": str(resource or "")[:120],
        "status": "ok" if status == "ok" else "error",
    }
    if error is not None:
        record.update(classify_service_error(error, provider=provider))
        record["error_type"] = type(error).__name__[:80]
    try:
        path = os.environ.get("JNSQ_SERVICE_HEALTH_LOG") or DEFAULT_LOG
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _WRITE_LOCK, _process_write_lock(path):
            with open(path, "a", encoding="utf-8", newline="") as handle:
                handle.write(line)
                handle.flush()
    except Exception:
        pass
    return record


def read_service_health(path: str = None,
                        max_bytes: int = MAX_READ_BYTES) -> list[dict]:
    """Read a bounded complete-line tail, newest records last."""
    path = path or os.environ.get("JNSQ_SERVICE_HEALTH_LOG") or DEFAULT_LOG
    if not os.path.exists(path):
        return []
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
            handle.readline()
        lines = handle.read().decode("utf-8", errors="replace").splitlines()
    records = []
    for line in lines:
        try:
            value = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records
