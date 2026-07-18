"""Persona-owned, append-only workbench for the first actionable agency cut.

The workbench is deliberately smaller than a filesystem tool.  A persona may
inspect only human-admitted inbox records and may create only new private
drafts beneath its own ``body/autonomy`` interior.  It cannot select paths,
overwrite, delete, publish, message, or mutate the repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from core.agency_projection import (
    AGENCY_SOURCE_BUDGET, AGENCY_TASK_BUDGET, AgencyTaskEnvelope,
)


MAX_INBOX_CHARS = AGENCY_TASK_BUDGET * 40
MAX_DRAFT_CHARS = AGENCY_TASK_BUDGET * 20
MAX_TOOL_READ_CHARS = AGENCY_TASK_BUDGET * 8
MAX_LABEL_CHARS = AGENCY_SOURCE_BUDGET
FIRST_ACTION_AUTHORITY_TIER = 2


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _bounded_text(value: Any, *, name: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds the {maximum}-character boundary")
    return text


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return (value or "item")[:48]


@dataclass(frozen=True)
class AgencyWorkbenchConfig:
    """Persona-owned policy ceiling; the organ remains the live on/off gate."""

    model: str
    authority_tier: int

    def __post_init__(self):
        model = str(self.model or "").strip()
        if not model:
            raise ValueError("agency workbench requires an explicit model")
        tier = self.authority_tier
        if not isinstance(tier, int) or isinstance(tier, bool):
            raise ValueError("agency authority_tier must be an integer")
        if tier < 0 or tier > FIRST_ACTION_AUTHORITY_TIER:
            raise ValueError(
                "first agency workbench admits authority tiers 0 through 2")
        object.__setattr__(self, "model", model)


def resolve_workbench_config(raw: Mapping[str, Any] | None,
                             active_model: str) -> AgencyWorkbenchConfig:
    """Resolve fail-closed roster policy without inventing a second switch."""
    raw = dict(raw or {})
    return AgencyWorkbenchConfig(
        model=str(raw.get("model") or active_model or "").strip(),
        authority_tier=int(raw.get("authority_tier", 0)),
    )


@dataclass(frozen=True)
class AgencyProposal:
    proposal_id: str
    run_id: str
    envelope: AgencyTaskEnvelope


def proposal_from_candidate(persona: str, candidate: Mapping[str, Any],
                            authority_tier: int) -> AgencyProposal:
    """Describe one already-won field candidate as optional private work."""
    candidate = dict(candidate or {})
    key = _bounded_text(
        candidate.get("key"), name="agency candidate key", maximum=1024)
    kind = _bounded_text(
        candidate.get("kind") or "field_candidate",
        name="agency candidate kind", maximum=80)
    node = _bounded_text(
        candidate.get("node") or candidate.get("text") or key,
        name="agency candidate description",
        maximum=AGENCY_SOURCE_BUDGET * 4)
    source = str(candidate.get("source") or "interior").strip()
    source_ownership = (
        "human_admitted" if source == "agency_inbox"
        else "ambient" if kind in {"sensory", "cognitive"}
        else "persona_private")
    source_digest = _digest({
        "key": key, "kind": kind, "source": source,
        "updated": candidate.get("updated"), "node": node,
    })
    proposal_id = _digest({
        "persona": persona, "source_digest": source_digest,
        "authority_tier": authority_tier,
    })
    task = (
        "Something has won attention in your own field. Decide what, if "
        "anything, genuinely appears to want doing with it. Silence is a "
        "valid outcome: answer [quiet] if no private work wants to happen. "
        "An inbox reference, if present in the source description, may be "
        "inspected with inspect_admitted_artifact. If carrying the thread "
        "forward would produce something worth keeping, you may create one "
        "new private, unsent draft with create_private_draft. Do not claim "
        "that anything was sent, published, deleted, or changed outside your "
        "private workbench."
    )
    envelope = AgencyTaskEnvelope(
        task=task,
        source_kind=kind,
        source_ref=key,
        source_digest=source_digest,
        source_summary=node,
        source_ownership=source_ownership,
        authority_tier=authority_tier,
    )
    return AgencyProposal(
        proposal_id=proposal_id,
        run_id=f"agency-{proposal_id}",
        envelope=envelope,
    )


class PersonaWorkbench:
    """One persona's bounded inbox, append-only artifacts, and receipts."""

    def __init__(self, persona_dir: str | os.PathLike[str]):
        self.persona_dir = Path(persona_dir).resolve()
        self.root = self.persona_dir / "body" / "autonomy"
        self.inbox = self.root / "inbox"
        self.artifacts = self.root / "artifacts"
        self.index = self.root / "index.jsonl"
        self._lock = threading.RLock()

    def _ensure(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def _path_for_ref(self, ref: str, *, bucket: str | None = None) -> Path:
        ref = str(ref or "").strip().replace("\\", "/")
        pure = PurePosixPath(ref)
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 2:
            raise ValueError("workbench reference is outside the admitted shape")
        if pure.parts[0] not in {"inbox", "artifacts"}:
            raise ValueError("workbench reference names an unknown collection")
        if bucket is not None and pure.parts[0] != bucket:
            raise ValueError(f"workbench reference is not in {bucket}")
        base = self.inbox if pure.parts[0] == "inbox" else self.artifacts
        path = (base / pure.parts[1]).resolve()
        if path.parent != base.resolve():
            raise ValueError("workbench reference escaped its collection")
        return path

    def _append_index(self, record: Mapping[str, Any]) -> None:
        self._ensure()
        with self.index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                dict(record), ensure_ascii=False, sort_keys=True) + "\n")

    def _create(self, bucket: str, label: str, content: str, *,
                run_id: str | None, ownership: str) -> dict[str, Any]:
        self._ensure()
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        stamp = int(time.time() * 1000)
        extension = ".txt" if bucket == "inbox" else ".md"
        stem = f"{stamp}-{_slug(label)}-{digest[:10]}"
        directory = self.inbox if bucket == "inbox" else self.artifacts
        path = directory / f"{stem}{extension}"
        collision = 0
        while True:
            try:
                with path.open("x", encoding="utf-8") as handle:
                    handle.write(content)
                break
            except FileExistsError:
                collision += 1
                path = directory / f"{stem}-{collision}{extension}"
        ref = f"{bucket}/{path.name}"
        record = {
            "ref": ref,
            "kind": "admitted_input" if bucket == "inbox" else "private_draft",
            "label": label,
            "created_at": time.time(),
            "chars": len(content),
            "sha256": digest,
            "ownership": ownership,
            "run_id": run_id,
        }
        self._append_index(record)
        return dict(record)

    def admit_text(self, label: str, content: str) -> dict[str, Any]:
        """Persist one explicitly human-admitted text without overwriting."""
        label = _bounded_text(
            label, name="inbox label", maximum=MAX_LABEL_CHARS)
        content = _bounded_text(
            content, name="inbox content", maximum=MAX_INBOX_CHARS)
        with self._lock:
            return self._create(
                "inbox", label, content, run_id=None,
                ownership="human_admitted")

    def inspect(self, ref: str) -> dict[str, Any]:
        """Read one inbox record through a bounded, reference-only door."""
        path = self._path_for_ref(ref, bucket="inbox")
        if not path.is_file():
            raise ValueError("admitted inbox reference does not exist")
        text = path.read_text(encoding="utf-8")
        bounded = text[:MAX_TOOL_READ_CHARS]
        return {
            "ref": str(ref),
            "content": bounded,
            "chars_returned": len(bounded),
            "source_chars": len(text),
            "truncated": len(bounded) < len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }

    def read_artifact(self, ref: str) -> dict[str, Any]:
        """Return one persona-private artifact to its local cockpit owner."""
        path = self._path_for_ref(ref, bucket="artifacts")
        if not path.is_file():
            raise ValueError("private artifact reference does not exist")
        text = path.read_text(encoding="utf-8")
        return {
            "ref": str(ref),
            "content": text,
            "chars": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }

    def create_draft(self, run_id: str, title: str,
                     content: str) -> dict[str, Any]:
        """Create one new private draft; no caller controls its path."""
        run_id = _bounded_text(
            run_id, name="agency run id", maximum=160)
        title = _bounded_text(
            title, name="draft title", maximum=MAX_LABEL_CHARS)
        content = _bounded_text(
            content, name="draft content", maximum=MAX_DRAFT_CHARS)
        with self._lock:
            if self.artifacts_for_run(run_id):
                raise ValueError(
                    "this agency run has already created its private draft")
            return self._create(
                "artifacts", title, content, run_id=run_id,
                ownership="persona_private")

    def records(self, *, kind: str | None = None,
                limit: int = 50) -> list[dict[str, Any]]:
        if not self.index.is_file():
            return []
        found = []
        with self._lock, self.index.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if kind is None or record.get("kind") == kind:
                    found.append(record)
        return [dict(item) for item in found[-max(1, min(int(limit), 200)):]]

    def artifacts_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return [record for record in self.records(kind="private_draft", limit=200)
                if record.get("run_id") == run_id]

    def pending_inbox(self) -> list[dict[str, Any]]:
        """Return admitted inputs that have no append-only resolution receipt."""
        admitted = self.records(kind="admitted_input", limit=200)
        addressed = {
            record.get("source_ref") for record in
            self.records(kind="inbox_resolution", limit=200)
        }
        return [record for record in admitted
                if record.get("ref") not in addressed]

    def mark_inbox_addressed(self, ref: str, run_id: str,
                             outcome: str) -> dict[str, Any]:
        """Close an admitted input by appending history, never mutating it."""
        path = self._path_for_ref(ref, bucket="inbox")
        if not path.is_file():
            raise ValueError("addressed inbox reference does not exist")
        run_id = _bounded_text(
            run_id, name="agency run id", maximum=160)
        outcome = _bounded_text(
            outcome, name="agency inbox outcome", maximum=80)
        with self._lock:
            existing = next((
                record for record in
                self.records(kind="inbox_resolution", limit=200)
                if record.get("source_ref") == ref), None)
            if existing:
                return dict(existing)
            record = {
                "kind": "inbox_resolution",
                "source_ref": ref,
                "addressed_at": time.time(),
                "run_id": run_id,
                "outcome": outcome,
                "ownership": "persona_private",
            }
            self._append_index(record)
            return dict(record)

    def tools_for_run(self, run_id: str):
        """Return the only two callable capabilities in the first blade."""
        async def inspect_admitted_artifact(ref: str) -> dict:
            """Inspect one explicitly human-admitted private inbox reference."""
            return self.inspect(ref)

        async def create_private_draft(title: str, content: str) -> dict:
            """Create one new private unsent draft without overwriting a file."""
            return self.create_draft(run_id, title, content)

        return inspect_admitted_artifact, create_private_draft

    def status(self) -> dict[str, Any]:
        return {
            "root": "body/autonomy",
            "inbox": self.records(kind="admitted_input", limit=20),
            "pending_inbox": self.pending_inbox(),
            "artifacts": self.records(kind="private_draft", limit=20),
            "policy": {
                "inspect": "human-admitted inbox only",
                "create": "new private drafts only",
                "overwrite": False,
                "delete": False,
                "external_effects": False,
            },
        }
