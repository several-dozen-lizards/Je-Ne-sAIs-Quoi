"""Version-pinned runtime selection for the compiled prompt core.

Null or ``legacy`` keeps the existing identity/system-prompt path.  A compiled
pin must name the family-bound shared profile and its exact revision.  Any
validation or compilation failure produces a content-free legacy-fallback
receipt; partially compiled text never reaches a provider.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from core.prompt_compiler import compile_shadow_prompt
from core.prompt_shadow import load_bound_profile
from core.prompt_sources import (
    PromptSourceError,
    load_organ_instruction,
    load_persona_identity,
    load_vessel_instruction,
)


RUNTIME_SCHEMA_VERSION = 1
LEGACY_SELECTOR = "legacy"
_PROFILE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PromptRuntimeResult:
    text: str | None
    receipt: dict


def parse_compiled_pin(value: str) -> tuple[str, str]:
    value = str(value or "").strip()
    if value.count("@") != 1:
        raise PromptSourceError(
            "compiled prompt pin must be profile@revision")
    profile_id, revision = value.split("@", 1)
    if not _PROFILE_RE.fullmatch(profile_id):
        raise PromptSourceError("compiled prompt profile ID is invalid")
    if not _REVISION_RE.fullmatch(revision):
        raise PromptSourceError("compiled prompt revision is invalid")
    return profile_id, revision


def _legacy_receipt(requested, reason: str) -> dict:
    return {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "status": "ready",
        "mode": "legacy",
        "requested": requested,
        "reason": reason,
    }


def resolve_prompt_runtime(*, repo: str | Path, persona: str, family: str,
                           enabled_organs, requested) -> PromptRuntimeResult:
    """Resolve one boot/transition prompt artifact without provider contact."""
    normalized = None if requested is None else str(requested).strip()
    if not normalized:
        return PromptRuntimeResult(
            None, _legacy_receipt(None, "unversioned"))
    if normalized == LEGACY_SELECTOR:
        return PromptRuntimeResult(
            None, _legacy_receipt(LEGACY_SELECTOR, "explicit_legacy"))

    root = Path(repo).resolve()
    try:
        pinned_profile, pinned_revision = parse_compiled_pin(normalized)
        profile, binding = load_bound_profile(
            family,
            root / "specs" / "render_profiles" / "bindings.yaml",
            root / "specs" / "render_profiles",
        )
        if pinned_profile != profile.profile_id:
            raise PromptSourceError(
                "prompt pin does not match the family-bound profile")
        if pinned_revision != profile.revision:
            raise PromptSourceError(
                "prompt pin revision does not match the loaded profile")
        identity = load_persona_identity(
            root / "personas" / persona / "who_i_am" / "identity.yaml")
        vessel = load_vessel_instruction(
            root / "specs" / "vessel_instructions" / "_default.yaml")
        organ_records = tuple(
            load_organ_instruction(path)
            for path in sorted(
                (root / "specs" / "organ_instructions").glob("*.yaml"))
        )
        compiled = compile_shadow_prompt(
            identity, organ_records, enabled_organs, profile, vessel=vessel)
        manifest = compiled.manifest
        return PromptRuntimeResult(compiled.text, {
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "status": "ready",
            "mode": "compiled",
            "requested": normalized,
            "profile": profile.profile_id,
            "profile_revision": profile.revision,
            "binding_source": binding.source,
            "render_sha256": manifest["render_sha256"],
            "render_chars": manifest["render_chars"],
            "semantic_ids": len(manifest["semantic_ids"]),
            "included_organ_sources": list(
                manifest["included_organ_sources"]),
            "enabled_actionable_capabilities": list(
                manifest["enabled_actionable_capabilities"]),
        })
    except Exception as exc:
        return PromptRuntimeResult(None, {
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "status": "fallback_legacy",
            "mode": "legacy",
            "requested": normalized,
            "error_type": type(exc).__name__,
            "error_digest": _digest(str(exc)),
        })
