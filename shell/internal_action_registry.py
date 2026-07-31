"""Typed, persona-local dispatch for low-risk wrapper-internal actions."""
from __future__ import annotations

from typing import Callable, Mapping


class InternalActionRegistry:
    """Dispatch exact capabilities to owning organs; owns no capability itself."""

    def __init__(self):
        self._owners: dict[str, tuple[str, Callable]] = {}

    def register(self, capability: str, owner: str, consumer: Callable) -> None:
        capability = str(capability or "").strip()
        owner = str(owner or "").strip()
        if not capability or not owner or not callable(consumer):
            raise ValueError("internal action registration is invalid")
        if capability in self._owners:
            raise ValueError("internal action capability is already registered")
        self._owners[capability] = (owner, consumer)

    def submit(self, selection: Mapping) -> dict:
        selection = dict(selection or {})
        capability = str(selection.get("capability") or "")
        registered = self._owners.get(capability)
        if registered is None:
            raise ValueError(
                "unknown interior capability has no destination organ")
        owner, consumer = registered
        if selection.get("owner") != owner:
            raise ValueError(
                "interior dispatch destination ownership mismatch")
        if selection.get("authority_scope") \
                != "wrapper_local_private_reversible" \
                or selection.get("external_effects") is not False:
            raise ValueError(
                "dispatch crossed the sovereign-interior scope boundary")
        return dict(consumer(selection) or {})

    def status(self) -> dict:
        return {
            "capabilities": {
                capability: {"owner": owner}
                for capability, (owner, _consumer) in self._owners.items()},
            "external_effects": False,
            "dispatch_semantics": "same_owner_destination_admission",
            "human_grant_required": False,
            "arbitrary_paths": False,
            "cross_persona": False,
        }
