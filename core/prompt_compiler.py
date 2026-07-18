"""Shadow composition of durable prompt sources through shared render profiles.

P1 remains unwired from TurnEngine and provider adapters.  It proves that one
persona source and only the currently enabled structured organ sources can
produce a deterministic prompt artifact without duplicate semantic ownership.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from types import MappingProxyType
from typing import Iterable, Mapping

import yaml

from core.organs import (
    REGISTRY,
    OrganConfigError,
    validate as validate_organs,
)
from core.prompt_sources import (
    NEWLINES,
    PromptSourceError,
    PromptSourceRecord,
    PromptStatement,
)


PROFILE_SCHEMA_VERSION = 1


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _nonempty(value, label: str) -> str:
    text = str(value or "")
    if not text.strip():
        raise PromptSourceError(f"{label} must not be empty")
    return text


def _blank_lines(value, label: str) -> int:
    if type(value) is not int or value < 0:
        raise PromptSourceError(f"{label} must be a nonnegative int")
    return value


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({
            str(key): _freeze(item) for key, item in value.items()
        })
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class RenderProfile:
    schema_version: int
    profile_id: str
    revision: str
    scope: str
    newline: str
    vessel_heading: str
    identity_heading: str
    capability_heading: str
    enabled_capabilities_template: str
    no_enabled_capabilities: str
    organ_heading_template: str
    statement_separator_blank_lines: int
    section_separator_blank_lines: int
    terminal_newline: bool
    stable_prefix: bool

    def __post_init__(self):
        if self.schema_version != PROFILE_SCHEMA_VERSION:
            raise PromptSourceError(
                f"render profile schema {self.schema_version} "
                f"!= supported {PROFILE_SCHEMA_VERSION}")
        if self.scope != "shared":
            raise PromptSourceError(
                "P1 render profiles must be shared, not model-owned")
        if self.newline not in NEWLINES:
            raise PromptSourceError(
                f"profile newline must be one of {sorted(NEWLINES)}")
        _blank_lines(
            self.statement_separator_blank_lines,
            "statement_separator_blank_lines",
        )
        _blank_lines(
            self.section_separator_blank_lines,
            "section_separator_blank_lines",
        )
        if type(self.terminal_newline) is not bool:
            raise PromptSourceError("terminal_newline must be a bool")
        if type(self.stable_prefix) is not bool:
            raise PromptSourceError("stable_prefix must be a bool")
        capability_fields = [
            name for _literal, name, _format_spec, _conversion
            in Formatter().parse(self.enabled_capabilities_template)
            if name is not None
        ]
        if capability_fields != ["capabilities"]:
            raise PromptSourceError(
                "enabled_capabilities_template must contain exactly "
                "{capabilities}")
        fields = [
            name for _literal, name, _format_spec, _conversion
            in Formatter().parse(self.organ_heading_template)
            if name is not None
        ]
        if fields != ["organ"]:
            raise PromptSourceError(
                "organ_heading_template must contain exactly {organ}")


@dataclass(frozen=True)
class CompiledPrompt:
    text: str
    manifest: Mapping[str, object]


def load_render_profile(path: str | Path) -> RenderProfile:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PromptSourceError(
            f"cannot read render profile {path}: {exc}") from exc
    raw = _mapping(raw, "render profile")
    _keys(
        raw,
        {"schema_version", "profile", "profile_revision", "scope", "layout"},
        "render profile",
    )
    if type(raw["schema_version"]) is not int:
        raise PromptSourceError("render profile schema_version must be an int")
    layout = _mapping(raw["layout"], "render profile layout")
    _keys(
        layout,
        {
            "newline",
            "vessel_heading",
            "identity_heading",
            "capability_heading",
            "enabled_capabilities_template",
            "no_enabled_capabilities",
            "organ_heading_template",
            "statement_separator_blank_lines",
            "section_separator_blank_lines",
            "terminal_newline",
            "stable_prefix",
        },
        "render profile layout",
    )
    return RenderProfile(
        schema_version=raw["schema_version"],
        profile_id=_nonempty(raw["profile"], "profile"),
        revision=_nonempty(raw["profile_revision"], "profile_revision"),
        scope=str(raw["scope"] or "").strip(),
        newline=str(layout["newline"] or "").strip(),
        vessel_heading=_nonempty(
            layout["vessel_heading"], "vessel_heading"),
        identity_heading=_nonempty(
            layout["identity_heading"], "identity_heading"),
        capability_heading=_nonempty(
            layout["capability_heading"], "capability_heading"),
        enabled_capabilities_template=_nonempty(
            layout["enabled_capabilities_template"],
            "enabled_capabilities_template",
        ),
        no_enabled_capabilities=_nonempty(
            layout["no_enabled_capabilities"],
            "no_enabled_capabilities",
        ),
        organ_heading_template=_nonempty(
            layout["organ_heading_template"], "organ_heading_template"),
        statement_separator_blank_lines=_blank_lines(
            layout["statement_separator_blank_lines"],
            "statement_separator_blank_lines",
        ),
        section_separator_blank_lines=_blank_lines(
            layout["section_separator_blank_lines"],
            "section_separator_blank_lines",
        ),
        terminal_newline=layout["terminal_newline"],
        stable_prefix=layout["stable_prefix"],
    )


def _record_map(
        organ_records: Iterable[PromptSourceRecord],
) -> dict[str, PromptSourceRecord]:
    records = {}
    for record in organ_records:
        if not isinstance(record, PromptSourceRecord):
            raise PromptSourceError(
                "organ_records contains a non-PromptSourceRecord")
        if record.source_kind != "organ_instruction":
            raise PromptSourceError(
                "organ_records may contain only organ_instruction sources")
        if record.source_id in records:
            raise PromptSourceError(
                f"duplicate organ prompt source {record.source_id!r}")
        if record.source_id not in REGISTRY:
            raise PromptSourceError(
                f"organ prompt source {record.source_id!r} "
                "is absent from the organ registry")
        expected = tuple(REGISTRY[record.source_id].deps)
        if record.dependencies != expected:
            raise PromptSourceError(
                f"organ prompt source {record.source_id!r} dependencies "
                f"{record.dependencies!r} != registry {expected!r}")
        records[record.source_id] = record
    return records


def _claim_semantics(
        owner: str,
        statements: Iterable[PromptStatement],
        claims: dict[str, str],
) -> None:
    for statement in statements:
        for semantic in statement.semantics:
            prior = claims.get(semantic)
            if prior is not None:
                raise PromptSourceError(
                    f"compiled semantic collision {semantic!r}: "
                    f"{prior} and {owner}")
            claims[semantic] = owner


def _section(
        heading: str,
        statements: tuple[PromptStatement, ...],
        profile: RenderProfile,
) -> str:
    newline = NEWLINES[profile.newline]
    statement_separator = newline * (
        profile.statement_separator_blank_lines + 1)
    return (
        heading
        + newline
        + statement_separator.join(item.text for item in statements)
    )


def compile_shadow_prompt(
        identity: PromptSourceRecord,
        organ_records: Iterable[PromptSourceRecord],
        enabled_organs: Iterable[str],
        profile: RenderProfile,
        vessel: PromptSourceRecord | None = None,
) -> CompiledPrompt:
    """Compile one content artifact without touching the live prompt path.

    Persona capability-instruction statements are omitted because capability
    meaning belongs to the modular organ source.  Therefore an unchecked organ
    contributes neither its own text nor a stale copy retained in identity.
    """
    if not isinstance(identity, PromptSourceRecord) \
            or identity.source_kind != "persona_identity":
        raise PromptSourceError(
            "compile_shadow_prompt requires one persona_identity source")
    if not isinstance(profile, RenderProfile):
        raise PromptSourceError(
            "compile_shadow_prompt requires a RenderProfile")
    if vessel is not None and (
            not isinstance(vessel, PromptSourceRecord)
            or vessel.source_kind != "vessel_instruction"):
        raise PromptSourceError(
            "vessel must be a vessel_instruction source when present")

    if isinstance(enabled_organs, (str, bytes)):
        raise PromptSourceError("enabled_organs must be an iterable of IDs")
    enabled = set(str(value) for value in enabled_organs)
    try:
        validate_organs(enabled)
    except OrganConfigError as exc:
        raise PromptSourceError(
            f"enabled organ set is invalid: {exc}") from exc
    records = _record_map(tuple(organ_records))

    identity_statements = tuple(
        statement for statement in identity.statements
        if statement.category != "capability_instruction"
    )
    if not identity_statements:
        raise PromptSourceError(
            "persona identity has no non-capability statements to render")
    omitted = tuple(
        {
            "source": f"persona_identity:{identity.source_id}",
            "statement_id": statement.statement_id,
            "semantic_ids": statement.semantics,
            "reason": "capability_owned_by_modular_organ",
        }
        for statement in identity.statements
        if statement.category == "capability_instruction"
    )

    ordered_enabled = tuple(
        organ_id for organ_id in REGISTRY if organ_id in enabled)
    included_organs = tuple(
        organ_id for organ_id in ordered_enabled if organ_id in records)
    claims: dict[str, str] = {}
    identity_owner = f"persona_identity:{identity.source_id}"
    _claim_semantics(identity_owner, identity_statements, claims)

    sections = []
    if vessel is not None:
        vessel_owner = f"vessel_instruction:{vessel.source_id}"
        _claim_semantics(vessel_owner, vessel.statements, claims)
        sections.append({
            "source_kind": "vessel_instruction",
            "source_id": vessel.source_id,
            "revision": vessel.revision,
            "heading": profile.vessel_heading,
            "statements": vessel.statements,
        })
    sections.append({
        "source_kind": "persona_identity",
        "source_id": identity.source_id,
        "revision": identity.revision,
        "heading": profile.identity_heading,
        "statements": identity_statements,
    })
    actionable_enabled = tuple(
        organ_id for organ_id in included_organs
        if records[organ_id].organ_kind == "actionable"
    )
    if actionable_enabled:
        capability_text = profile.enabled_capabilities_template.format(
            capabilities=", ".join(actionable_enabled))
        capability_semantics = (
            "capability_state.explicit",
            *(f"capability_state.{organ_id}.enabled"
              for organ_id in actionable_enabled),
        )
    else:
        capability_text = profile.no_enabled_capabilities
        capability_semantics = (
            "capability_state.explicit",
            "capability_state.none_enabled",
        )
    capability_statement = PromptStatement(
        statement_id="actionable_capability_state",
        category="capability_state",
        text=capability_text,
        semantics=capability_semantics,
    )
    _claim_semantics(
        "capability_state:actionable", (capability_statement,), claims)
    sections.append({
        "source_kind": "capability_state",
        "source_id": "actionable",
        "revision": profile.revision,
        "heading": profile.capability_heading,
        "statements": (capability_statement,),
    })
    for organ_id in included_organs:
        record = records[organ_id]
        owner = f"organ_instruction:{organ_id}"
        _claim_semantics(owner, record.statements, claims)
        sections.append({
            "source_kind": "organ_instruction",
            "source_id": organ_id,
            "revision": record.revision,
            "heading": profile.organ_heading_template.format(organ=organ_id),
            "statements": record.statements,
        })

    newline = NEWLINES[profile.newline]
    section_separator = newline * (
        profile.section_separator_blank_lines + 1)
    text = section_separator.join(
        _section(section["heading"], section["statements"], profile)
        for section in sections
    )
    if profile.terminal_newline:
        text += newline

    manifest_sections = tuple({
        "source_kind": section["source_kind"],
        "source_id": section["source_id"],
        "revision": section["revision"],
        "statement_ids": tuple(
            item.statement_id for item in section["statements"]),
        "semantic_ids": tuple(
            semantic
            for item in section["statements"]
            for semantic in item.semantics
        ),
    } for section in sections)
    manifest = {
        "schema_version": 1,
        "profile": profile.profile_id,
        "profile_revision": profile.revision,
        "profile_scope": profile.scope,
        "stable_prefix": profile.stable_prefix,
        "persona": identity.source_id,
        "identity_revision": identity.revision,
        "vessel": vessel.source_id if vessel is not None else None,
        "vessel_revision": vessel.revision if vessel is not None else None,
        "enabled_organs": ordered_enabled,
        "available_organ_sources": tuple(
            organ_id for organ_id in REGISTRY if organ_id in records),
        "included_organ_sources": included_organs,
        "enabled_actionable_capabilities": actionable_enabled,
        "sections": manifest_sections,
        "semantic_ids": tuple(claims),
        "omitted": omitted,
        "render_chars": len(text),
        "render_sha256": _digest(text),
    }
    return CompiledPrompt(text=text, manifest=_freeze(manifest))
