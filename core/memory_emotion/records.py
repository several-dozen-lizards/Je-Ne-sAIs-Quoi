"""Memory records: creation + validation. One format, versioned."""
import uuid
from datetime import datetime, timezone

from .context import normalize_context


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_memory(content: str, *, mem_type: str = "fact",
                emotion_tags=None, emotional_snapshot=None,
                entities=None, origin: str = "lived",
                perspective: str = "shared",
                importance: float = 0.5, fields=None,
                context_at_encoding=None) -> dict:
    """origin: lived | read | observed | sensory   (v1 epistemics + perception)
    perspective: user | persona | shared (parameterized — no names baked in)
    fields: optional structured payload (one record, two renders — the
    working window renders fields verbatim; recall renders content).
    For turn records: speaker, channel, message_full, reply_full.
    Additive; absent on older memories."""
    mem = {
        "id": str(uuid.uuid4()),
        "type": mem_type,
        "content": content,
        "entities": list(entities or []),
        "origin": origin,
        "perspective": perspective,
        "emotion_tags": list(emotion_tags or []),
        "emotional_snapshot": dict(emotional_snapshot or {}),
        "importance": float(importance),
        "timestamp": now_iso(),
        "access_count": 0,
        "last_access": None,
        "layer": "working",
        "decay_health": 1.0,
    }
    if fields:
        mem["fields"] = dict(fields)
    context = normalize_context(context_at_encoding)
    if context is not None:
        mem["context_at_encoding"] = context
    return mem


def age_days(mem: dict) -> float:
    t = datetime.fromisoformat(mem["timestamp"])
    return max(0.0, (datetime.now(timezone.utc) - t).total_seconds() / 86400.0)
