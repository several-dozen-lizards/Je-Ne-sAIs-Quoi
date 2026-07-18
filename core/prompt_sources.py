"""Versioned, model-neutral prompt sources for the shadow compiler.

This module is deliberately unwired.  It loads durable persona-identity and
organ-instruction records, validates them strictly, renders the legacy text
artifact exactly, and exposes semantic collisions before prose is assembled.

The records own meaning.  Renderers own phrasing.  Provider adapters remain
downstream and are not imported here.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

import yaml


SCHEMA_VERSION = 1
SOURCE_KINDS = frozenset({
    "persona_identity",
    "organ_instruction",
    "vessel_instruction",
})
IDENTITY_CATEGORIES = frozenset({
    "self_conception",
    "continuity",
    "tendency",
    "expression",
    "capability_instruction",
    "relationship",
    "value",
    "operating_stance",
})
ORGAN_CATEGORIES = frozenset({
    "mechanics",
    "action_grammar",
    "expression_boundary",
})
VESSEL_CATEGORIES = frozenset({
    "orientation",
    "interpretation_boundary",
    "capability_boundary",
})
ORGAN_KINDS = frozenset({"actionable", "descriptive"})
NEWLINES = MappingProxyType({"lf": "\n", "crlf": "\r\n"})
_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")


class PromptSourceError(ValueError):
    """A prompt source is malformed or cannot be compiled safely."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strict_mapping(value, label: str) -> dict:
    if not isinstance(value, Mapping):
        raise PromptSourceError(f"{label} must be a mapping")
    return dict(value)


def _strict_keys(value: Mapping, allowed: set[str], label: str) -> None:
    unknown = set(value) - set(allowed)
    missing = set(allowed) - set(value)
    if unknown:
        raise PromptSourceError(
            f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        raise PromptSourceError(
            f"{label} is missing fields: {', '.join(sorted(missing))}")


def _identifier(value, label: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise PromptSourceError(
            f"{label} must match ^[a-z][a-z0-9_.-]*$")
    return text


def _nonempty(value, label: str) -> str:
    text = str(value or "")
    if not text.strip():
        raise PromptSourceError(f"{label} must not be empty")
    return text


@dataclass(frozen=True)
class LegacyRender:
    newline: str
    separator_blank_lines: int
    terminal_newline: bool

    def __post_init__(self):
        if self.newline not in NEWLINES:
            raise PromptSourceError(
                f"legacy newline must be one of {sorted(NEWLINES)}")
        if (type(self.separator_blank_lines) is not int
                or self.separator_blank_lines < 0):
            raise PromptSourceError(
                "legacy separator_blank_lines must be a nonnegative int")
        if type(self.terminal_newline) is not bool:
            raise PromptSourceError(
                "legacy terminal_newline must be a bool")


@dataclass(frozen=True)
class PromptStatement:
    statement_id: str
    category: str
    text: str
    semantics: tuple[str, ...]


@dataclass(frozen=True)
class PromptSourceRecord:
    schema_version: int
    source_kind: str
    source_id: str
    revision: str
    statements: tuple[PromptStatement, ...]
    legacy_render: LegacyRender
    organ_kind: str | None = None
    dependencies: tuple[str, ...] = ()

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION:
            raise PromptSourceError(
                f"prompt source schema {self.schema_version} "
                f"!= supported {SCHEMA_VERSION}")
        if self.source_kind not in SOURCE_KINDS:
            raise PromptSourceError(
                f"unknown prompt source kind {self.source_kind!r}")

    @property
    def statement_ids(self) -> tuple[str, ...]:
        return tuple(item.statement_id for item in self.statements)

    @property
    def semantic_ids(self) -> tuple[str, ...]:
        return tuple(
            semantic
            for statement in self.statements
            for semantic in statement.semantics
        )


def _legacy(value) -> LegacyRender:
    raw = _strict_mapping(value, "legacy_render")
    _strict_keys(
        raw,
        {"newline", "separator_blank_lines", "terminal_newline"},
        "legacy_render",
    )
    return LegacyRender(
        newline=str(raw["newline"]),
        separator_blank_lines=raw["separator_blank_lines"],
        terminal_newline=raw["terminal_newline"],
    )


def _statements(value, categories: frozenset[str]) -> tuple[PromptStatement, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise PromptSourceError("statements must be a list")
    if not value:
        raise PromptSourceError("statements must not be empty")
    statements = []
    seen_statements = set()
    seen_semantics = set()
    for index, item in enumerate(value):
        raw = _strict_mapping(item, f"statements[{index}]")
        _strict_keys(
            raw, {"id", "category", "text", "semantics"},
            f"statements[{index}]",
        )
        statement_id = _identifier(raw["id"], f"statements[{index}].id")
        if statement_id in seen_statements:
            raise PromptSourceError(
                f"duplicate statement id {statement_id!r}")
        seen_statements.add(statement_id)
        category = str(raw["category"] or "").strip()
        if category not in categories:
            raise PromptSourceError(
                f"statement {statement_id!r} category must be one of "
                f"{sorted(categories)}")
        semantics_raw = raw["semantics"]
        if (isinstance(semantics_raw, (str, bytes))
                or not isinstance(semantics_raw, list)
                or not semantics_raw):
            raise PromptSourceError(
                f"statement {statement_id!r} semantics must be a nonempty list")
        semantics = tuple(
            _identifier(value, f"statement {statement_id!r} semantic id")
            for value in semantics_raw
        )
        if len(set(semantics)) != len(semantics):
            raise PromptSourceError(
                f"statement {statement_id!r} repeats a semantic id")
        overlap = seen_semantics.intersection(semantics)
        if overlap:
            raise PromptSourceError(
                "one source may own each semantic id only once; repeated: "
                + ", ".join(sorted(overlap)))
        seen_semantics.update(semantics)
        statements.append(PromptStatement(
            statement_id=statement_id,
            category=category,
            text=_nonempty(raw["text"], f"statement {statement_id!r} text"),
            semantics=semantics,
        ))
    return tuple(statements)


def _load_yaml(path: str | Path) -> dict:
    path = Path(path)
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PromptSourceError(
            f"cannot read prompt source {path}: {exc}") from exc
    return _strict_mapping(value, "prompt source")


def load_persona_identity(path: str | Path) -> PromptSourceRecord:
    raw = _load_yaml(path)
    _strict_keys(
        raw,
        {"schema_version", "persona", "identity_revision",
         "statements", "legacy_render"},
        "persona identity",
    )
    if type(raw["schema_version"]) is not int:
        raise PromptSourceError("schema_version must be an int")
    return PromptSourceRecord(
        schema_version=raw["schema_version"],
        source_kind="persona_identity",
        source_id=_identifier(raw["persona"], "persona"),
        revision=_nonempty(raw["identity_revision"], "identity_revision"),
        statements=_statements(raw["statements"], IDENTITY_CATEGORIES),
        legacy_render=_legacy(raw["legacy_render"]),
    )


def load_organ_instruction(path: str | Path) -> PromptSourceRecord:
    raw = _load_yaml(path)
    _strict_keys(
        raw,
        {"schema_version", "organ", "organ_revision", "kind",
         "dependencies", "statements", "legacy_render"},
        "organ instruction",
    )
    if type(raw["schema_version"]) is not int:
        raise PromptSourceError("schema_version must be an int")
    kind = str(raw["kind"] or "").strip()
    if kind not in ORGAN_KINDS:
        raise PromptSourceError(
            f"organ kind must be one of {sorted(ORGAN_KINDS)}")
    deps = raw["dependencies"]
    if isinstance(deps, (str, bytes)) or not isinstance(deps, list):
        raise PromptSourceError("organ dependencies must be a list")
    dependencies = tuple(
        _identifier(value, "organ dependency") for value in deps)
    if len(set(dependencies)) != len(dependencies):
        raise PromptSourceError("organ dependencies must be unique")
    return PromptSourceRecord(
        schema_version=raw["schema_version"],
        source_kind="organ_instruction",
        source_id=_identifier(raw["organ"], "organ"),
        revision=_nonempty(raw["organ_revision"], "organ_revision"),
        statements=_statements(raw["statements"], ORGAN_CATEGORIES),
        legacy_render=_legacy(raw["legacy_render"]),
        organ_kind=kind,
        dependencies=dependencies,
    )


def load_vessel_instruction(path: str | Path) -> PromptSourceRecord:
    raw = _load_yaml(path)
    _strict_keys(
        raw,
        {"schema_version", "vessel", "vessel_revision",
         "statements", "legacy_render"},
        "vessel instruction",
    )
    if type(raw["schema_version"]) is not int:
        raise PromptSourceError("schema_version must be an int")
    return PromptSourceRecord(
        schema_version=raw["schema_version"],
        source_kind="vessel_instruction",
        source_id=_identifier(raw["vessel"], "vessel"),
        revision=_nonempty(raw["vessel_revision"], "vessel_revision"),
        statements=_statements(raw["statements"], VESSEL_CATEGORIES),
        legacy_render=_legacy(raw["legacy_render"]),
    )


def render_legacy(record: PromptSourceRecord) -> str:
    """Rebuild the pre-compiler text artifact, including newline policy."""
    newline = NEWLINES[record.legacy_render.newline]
    separator = newline * (record.legacy_render.separator_blank_lines + 1)
    # YAML normalizes block-scalar line endings to LF. The legacy renderer
    # owns the requested artifact policy, including newlines *inside* a
    # multi-line statement, not only the separators between statements.
    def normalize(value: str) -> str:
        return value.replace("\r\n", "\n").replace("\r", "\n").replace(
            "\n", newline)

    rendered = separator.join(normalize(item.text)
                              for item in record.statements)
    if record.legacy_render.terminal_newline:
        rendered += newline
    return rendered


def semantic_collisions(
        records: Iterable[PromptSourceRecord],
) -> Mapping[str, tuple[str, ...]]:
    """Return semantic IDs claimed by more than one durable source."""
    owners: dict[str, list[str]] = {}
    for record in records:
        owner = f"{record.source_kind}:{record.source_id}"
        for semantic in record.semantic_ids:
            owners.setdefault(semantic, []).append(owner)
    return MappingProxyType({
        semantic: tuple(values)
        for semantic, values in sorted(owners.items())
        if len(values) > 1
    })


def assert_no_semantic_collisions(
        records: Iterable[PromptSourceRecord],
) -> None:
    collisions = semantic_collisions(records)
    if not collisions:
        return
    details = "; ".join(
        f"{semantic} -> {', '.join(owners)}"
        for semantic, owners in collisions.items()
    )
    raise PromptSourceError(f"semantic collisions: {details}")


def render_manifest(record: PromptSourceRecord) -> Mapping[str, object]:
    """Return a content-free receipt for one deterministic legacy render."""
    rendered = render_legacy(record)
    source_shape = "\n".join(
        f"{item.statement_id}|{item.category}|{','.join(item.semantics)}"
        for item in record.statements
    )
    return MappingProxyType({
        "schema_version": record.schema_version,
        "source_kind": record.source_kind,
        "source_id": record.source_id,
        "revision": record.revision,
        "renderer": "legacy_text_v1",
        "statement_ids": record.statement_ids,
        "semantic_ids": record.semantic_ids,
        "source_shape_sha256": _digest(source_shape),
        "render_sha256": _digest(rendered),
        "render_chars": len(rendered),
        "newline": record.legacy_render.newline,
        "terminal_newline": record.legacy_render.terminal_newline,
    })
