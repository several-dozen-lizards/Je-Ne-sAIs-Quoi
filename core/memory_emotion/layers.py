"""Layers + decay: WHAT SURVIVES.
Ports v1 memory_layers protection math verbatim (V1_AUDIT 7.7):
each emotion tag = +20% halflife (cap 3.0x); bonded/tracked entity = 2.0x.
Emotionally significant memories of loved ones decay slowest. By design.
Archived, never deleted (comment-out principle)."""
from .records import age_days

BASE_HALFLIFE_DAYS = 30.0
ARCHIVE_THRESHOLD = 0.05
WORKING_CAPACITY = 50


def emotion_protection(mem: dict) -> float:
    n = len(mem.get("emotion_tags", []))
    return min(1.0 + n * 0.2, 3.0) if n else 1.0


def entity_protection(mem: dict, bonds: dict) -> float:
    for e in mem.get("entities", []):
        if bonds.get(e, 0.0) > 0.10:
            return 2.0
    return 1.0


def decay_tick(memories: list, bonds: dict, days_elapsed: float) -> list:
    """Apply halflife decay with protections. Returns archived memories."""
    archived = []
    for mem in memories:
        if mem.get("layer") != "longterm":
            continue
        f = mem.get("fields") or {}
        if f.get("is_bedrock") or f.get("no_decay"):
            continue  # no halflife: bedrock identity facts, and
                      # no_decay strata (e.g. the migrated v1 life —
                      # a preserved stratum; Re-approved 2026-07-11)
        hl = BASE_HALFLIFE_DAYS * emotion_protection(mem) * entity_protection(mem, bonds)
        mem["decay_health"] = mem.get("decay_health", 1.0) * (0.5 ** (days_elapsed / hl))
        if mem["decay_health"] < ARCHIVE_THRESHOLD:
            mem["layer"] = "archived"
            archived.append(mem)
    return archived


def flush_working(memories: list, capacity: int = WORKING_CAPACITY) -> int:
    """Working layer over capacity: oldest spill to longterm. Returns count."""
    working = [m for m in memories if m.get("layer") == "working"]
    if len(working) <= capacity:
        return 0
    working.sort(key=lambda m: m["timestamp"])
    spill = working[: len(working) - capacity]
    for m in spill:
        m["layer"] = "longterm"
    return len(spill)
