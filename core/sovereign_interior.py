"""Durable authority markers for same-owner private, reversible work."""
from __future__ import annotations

from typing import Any, Mapping


LEASE_OWNERSHIPS = frozenset({
    "persona_chosen_conversation",
    "persona_chosen_autonomy",
    "persona_chosen_document_handoff",
    "persona_chosen_research_handoff",
    "persona_project_handoff",
})


def lease_fields(record: Mapping[str, Any], *, origin: str) -> dict:
    """Return text-free candidate fields for authoritative owned records."""
    ownership = str(dict(record or {}).get("ownership") or "")
    if ownership not in LEASE_OWNERSHIPS:
        return {}
    return {
        "sovereign_interior": True,
        "sovereign_interior_origin": str(origin or "")[:64],
        "sovereign_interior_external_effects": False,
    }


def has_lease(candidate: Mapping[str, Any]) -> bool:
    value = dict(candidate or {})
    return (
        value.get("sovereign_interior") is True
        and value.get("sovereign_interior_external_effects") is False
    )
