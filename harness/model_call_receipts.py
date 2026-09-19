"""Privacy-safe, cycle-scoped receipts for every model boundary.

The prompt and response never enter this module.  A receipt records only the
declared purpose, provider/model identity, timing, usage counts, and transport
outcome.  Callers opt into durable recording with ``model_call_scope``; direct
bench/tests that do not bind a scope retain the clients' in-memory metadata but
do not grow the household ledger.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import math
import os
import threading
import uuid


_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_PATH = os.path.join(_REPO, "logs", "model_calls.jsonl")
_SCOPE = ContextVar("jnaiq_model_call_scope", default=None)
_WRITE_LOCK = threading.Lock()


@contextmanager
def _process_write_lock(path: str):
    """Serialize one receipt line across the household's processes.

    The lock lives beside the ledger, contains no household data, and is held
    only for the append itself.  Thread locking alone cannot protect a shared
    JSONL file when each cockpit is a separate process.
    """
    lock_path = os.path.abspath(path) + ".lock"
    with open(lock_path, "a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

_COUNT_ALIASES = {
    "prompt_tokens": "input_tokens",
    "completion_tokens": "output_tokens",
    "cached_tokens": "cache_read_tokens",
    "cached_input_tokens": "cache_read_tokens",
}
_COUNT_FIELDS = {
    "input_tokens", "output_tokens", "reasoning_tokens",
    "cache_read_tokens", "cache_write_tokens", "total_tokens",
}
_TIMING_FIELDS = {
    "first_token_ms", "total_ms", "provider_ms", "prompt_ms", "gen_ms",
    "load_ms", "connect_ms",
}
_SAFE_FIELDS = {
    "attempts", "wire_attempts", "finish_reason", "streamed",
    "recovered_empty_reply", "completion_limit", "status_code",
    "error_type", "error_code", "spec_name", "thinking_type",
}


def classify_service_error(error, *, provider: str = "") -> dict:
    """Reduce a provider exception to an allowlisted, content-free cause.

    Raw provider bodies can contain account or request material, so they never
    enter receipts.  The classifier may inspect the exception in memory, but
    returns only a stable cause code and optional HTTP status.
    """
    message = str(error or "").lower()
    status = getattr(getattr(error, "response", None), "status_code", None)
    if not isinstance(status, int):
        import re
        match = re.search(r"(?:api|http|status)[ :]+(\d{3})\b", message)
        status = int(match.group(1)) if match else None
    local = str(provider or "").lower() in {"ollama", "local", "localhost"}
    credit_words = (
        "credit balance", "credits exhausted", "credit quota",
        "not enough credits", "out of credits", "insufficient_quota",
        "quota exceeded", "quota_exceeded", "payment required",
        "billing limit", "purchase credits",
    )
    if status == 402 or any(word in message for word in credit_words):
        code = "credit_exhausted"
    elif ("not found (environment" in message
          or "missing required api key" in message
          or "api_key is not set" in message
          or "api key is not set" in message
          or ("needs " in message and "not set" in message)):
        code = "missing_key"
    elif status == 401 or any(word in message for word in (
            "invalid apikey", "invalid api key", "authentication failed",
            "unauthorized", "invalid_api_key")):
        code = "authentication_failed"
    elif status == 403 or any(word in message for word in (
            "permission denied", "denied permission", "endpoint scopes",
            "ip allowlist", "forbidden")):
        code = "permission_denied"
    elif status == 429 or "rate limit" in message or "rate_limit" in message:
        code = "rate_limited"
    elif ("model not found" in message or "model is not installed" in message
          or "not installed" in message or "cannot access that model" in message
          or "not in the model list" in message
          or (status == 404 and "model" in message)):
        code = "model_unavailable"
    elif ("timeout" in type(error).__name__.lower()
          or "timed out" in message or "timeout" in message):
        code = "timeout"
    elif ("connection" in type(error).__name__.lower()
          or "connection refused" in message
          or "failed to establish a new connection" in message
          or "unable to connect" in message
          or "name resolution" in message):
        code = "local_service_unreachable" if local \
            else "provider_unreachable"
    elif status is not None and status >= 500:
        code = "provider_unreachable"
    elif "overloaded" in message or "service unavailable" in message:
        code = "provider_unreachable"
    else:
        code = "provider_error"
    result = {"error_code": code}
    if status is not None:
        result["status_code"] = status
    return result


def new_cycle_id() -> str:
    """Opaque correlation id; contains no persona, prompt, or timestamp."""
    return uuid.uuid4().hex


def model_call_is_scoped() -> bool:
    """True when the current execution context already owns call metadata."""
    return _SCOPE.get() is not None


@contextmanager
def model_call_scope(*, cycle_id: str, persona: str, purpose: str,
                     sink: list | None = None):
    """Bind one semantic purpose to provider calls made inside the block."""
    scope = {
        "cycle_id": str(cycle_id or "").strip(),
        "persona": str(persona or "").strip(),
        "purpose": str(purpose or "unknown").strip() or "unknown",
        "sink": sink,
    }
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


def _number(value, *, integer: bool):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0:
        return None
    return int(value) if integer else round(value, 3)


def _safe_meta(meta: dict | None) -> dict:
    raw = dict(meta or {})
    safe = {}
    for source, target in _COUNT_ALIASES.items():
        if raw.get(target) is None and source in raw:
            raw[target] = raw[source]
    for key in _COUNT_FIELDS:
        value = _number(raw.get(key), integer=True)
        if value is not None:
            safe[key] = value
    for key in _TIMING_FIELDS:
        value = _number(raw.get(key), integer=False)
        if value is not None:
            safe[key] = value
    for key in _SAFE_FIELDS:
        value = raw.get(key)
        if isinstance(value, (bool, int)):
            safe[key] = value
        elif isinstance(value, str) and value:
            safe[key] = value[:80]
    return safe


def record_model_call(provider: str, model: str, meta: dict | None = None,
                      *, status: str = "ok") -> dict | None:
    """Append one content-free call receipt when a live scope is bound.

    Metering is observational: a filesystem or serialization failure can
    never fail the model call that it describes.
    """
    scope = _SCOPE.get()
    if not scope:
        return None
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
        "call_id": uuid.uuid4().hex,
        "cycle_id": scope["cycle_id"],
        "persona": scope["persona"],
        "purpose": scope["purpose"],
        "provider": str(provider or "unknown"),
        "model": str(model or "unknown"),
        "status": str(status or "unknown"),
        **_safe_meta(meta),
    }
    sink = scope.get("sink")
    if isinstance(sink, list):
        sink.append(dict(record))
    try:
        path = os.environ.get("JNSQ_MODEL_CALL_LOG") or _DEFAULT_PATH
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _WRITE_LOCK, _process_write_lock(path):
            with open(path, "a", encoding="utf-8", newline="") as handle:
                handle.write(line)
                handle.flush()
    except Exception:
        pass
    return record
