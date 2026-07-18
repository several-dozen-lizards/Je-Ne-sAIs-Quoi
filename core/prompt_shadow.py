"""Content-free live projection of the still-unwired prompt compiler.

The live model continues to receive legacy identity and system-prompt text.
This module loads structured sources only when a persona owns an identity
record, resolves a shared profile by family/default, compiles in memory, drops
the rendered text, and returns only the immutable-shape manifest as plain data.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

from core.prompt_compiler import (
    RenderProfile,
    compile_shadow_prompt,
    load_render_profile,
)
from core.prompt_sources import (
    PromptSourceError,
    load_organ_instruction,
    load_persona_identity,
    load_vessel_instruction,
)


BINDING_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def _identifier(value, label: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise PromptSourceError(
            f"{label} must match ^[a-z][a-z0-9_-]*$")
    return text


def _mapping(value, label: str) -> dict:
    if not isinstance(value, Mapping):
        raise PromptSourceError(f"{label} must be a mapping")
    return dict(value)


def _keys(value: Mapping, allowed: set[str], label: str) -> None:
    unknown = set(value) - set(allowed)
    missing = set(allowed) - set(value)
    if unknown:
        raise PromptSourceError(
            f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        raise PromptSourceError(
            f"{label} is missing fields: {', '.join(sorted(missing))}")


def _plain(value):
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _error_digest(exc: Exception) -> str:
    return hashlib.sha256(str(exc).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ProfileBindings:
    schema_version: int
    default_profile: str
    families: Mapping[str, str]

    def __post_init__(self):
        if self.schema_version != BINDING_SCHEMA_VERSION:
            raise PromptSourceError(
                f"profile binding schema {self.schema_version} "
                f"!= supported {BINDING_SCHEMA_VERSION}")


@dataclass(frozen=True)
class BindingResolution:
    profile_id: str
    source: str


def load_profile_bindings(path: str | Path) -> ProfileBindings:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PromptSourceError(
            f"cannot read profile bindings {path}: {exc}") from exc
    raw = _mapping(raw, "profile bindings")
    _keys(
        raw,
        {"schema_version", "default_profile", "families"},
        "profile bindings",
    )
    if type(raw["schema_version"]) is not int:
        raise PromptSourceError(
            "profile binding schema_version must be an int")
    families_raw = _mapping(raw["families"], "profile binding families")
    families = {}
    for family, profile in families_raw.items():
        family_id = _identifier(family, "profile binding family")
        profile_id = _identifier(profile, f"profile for family {family_id}")
        families[family_id] = profile_id
    return ProfileBindings(
        schema_version=raw["schema_version"],
        default_profile=_identifier(
            raw["default_profile"], "default_profile"),
        families=MappingProxyType(families),
    )


def resolve_profile_binding(
        family: str,
        bindings: ProfileBindings,
) -> BindingResolution:
    family = _identifier(family, "model family")
    if family in bindings.families:
        return BindingResolution(
            bindings.families[family], f"family:{family}")
    return BindingResolution(bindings.default_profile, "default")


def load_bound_profile(
        family: str,
        bindings_path: str | Path,
        profiles_dir: str | Path,
) -> tuple[RenderProfile, BindingResolution]:
    bindings = load_profile_bindings(bindings_path)
    resolution = resolve_profile_binding(family, bindings)
    path = Path(profiles_dir) / f"{resolution.profile_id}.yaml"
    profile = load_render_profile(path)
    if profile.profile_id != resolution.profile_id:
        raise PromptSourceError(
            f"bound profile {resolution.profile_id!r} loaded "
            f"mismatched ID {profile.profile_id!r}")
    return profile, resolution


def project_prompt_shadow(
        repo: str | Path,
        persona: str,
        family: str,
        enabled_organs,
) -> dict:
    """Compile then discard shadow text; return JSON-safe, content-free state."""
    persona = _identifier(persona, "persona")
    family = _identifier(family, "model family")
    root = Path(repo).resolve()
    identity_path = (
        root / "personas" / persona / "who_i_am" / "identity.yaml")
    if not identity_path.is_file():
        return {
            "status": "unavailable",
            "persona": persona,
            "family": family,
            "reason": "identity_source_absent",
        }
    try:
        identity = load_persona_identity(identity_path)
        vessel = load_vessel_instruction(
            root / "specs" / "vessel_instructions" / "_default.yaml")
        organ_dir = root / "specs" / "organ_instructions"
        organ_records = tuple(
            load_organ_instruction(path)
            for path in sorted(organ_dir.glob("*.yaml"))
        )
        profile, binding = load_bound_profile(
            family,
            root / "specs" / "render_profiles" / "bindings.yaml",
            root / "specs" / "render_profiles",
        )
        compiled = compile_shadow_prompt(
            identity,
            organ_records,
            enabled_organs,
            profile,
            vessel=vessel,
        )
        return {
            "status": "ready",
            "persona": persona,
            "family": family,
            "binding": {
                "profile": binding.profile_id,
                "source": binding.source,
            },
            "manifest": _plain(compiled.manifest),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "persona": persona,
            "family": family,
            "error_type": type(exc).__name__,
            "error_digest": _error_digest(exc),
        }
