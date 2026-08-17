"""Content-free lineage helpers for autonomous DMN recollections."""


def is_dmn_wandering(memory: dict) -> bool:
    """True only for private DMN products that can seed later products."""
    fields = dict((memory or {}).get("fields") or {})
    return bool(
        fields.get("channel") == "dmn"
        and ((memory or {}).get("type") == "wandering"
             or fields.get("seed_id")
             or fields.get("root_seed_id")))


def dmn_lineage_root(memory: dict, memories_by_id: dict = None) -> str:
    """Return the originating memory id without inspecting memory content.

    New records carry ``root_seed_id``.  Following ``seed_id`` keeps the
    boundary effective for older records without rewriting the live store.
    """
    memory = memory or {}
    memory_id = str(memory.get("id") or "").strip()
    if not is_dmn_wandering(memory):
        return memory_id

    lookup = dict(memories_by_id or {})
    current = memory
    seen = set()
    while current:
        current_id = str(current.get("id") or "").strip()
        if current_id:
            if current_id in seen:
                return memory_id
            seen.add(current_id)
        fields = dict(current.get("fields") or {})
        explicit_root = str(fields.get("root_seed_id") or "").strip()
        if explicit_root:
            return explicit_root
        parent_id = str(fields.get("seed_id") or "").strip()
        if not parent_id:
            return current_id or memory_id
        parent = lookup.get(parent_id)
        if parent is None:
            return parent_id
        if not is_dmn_wandering(parent):
            return parent_id
        current = parent
    return memory_id
