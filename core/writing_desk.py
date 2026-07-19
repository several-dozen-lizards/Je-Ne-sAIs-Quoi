"""Persona-private, append-only projects for autonomous writing.

The desk is a capability boundary, not a filesystem tool.  Human-admitted
seeds may contain bounded text and/or canonical document anchors.  A persona
may turn one seed into one project, append fresh revisions, or append a state
transition.  Callers never choose paths; nothing is overwritten, deleted,
published, messaged, or copied into autobiographical memory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from core.agency_projection import AGENCY_SOURCE_BUDGET, AGENCY_TASK_BUDGET


MAX_SEED_CHARS = AGENCY_TASK_BUDGET * 40
MAX_REVISION_CHARS = AGENCY_TASK_BUDGET * 20
MAX_READ_CHARS = AGENCY_TASK_BUDGET * 8
MAX_LABEL_CHARS = AGENCY_SOURCE_BUDGET
RESOLUTIONS = frozenset({"paused", "completed", "abandoned"})
SEED_OWNERSHIPS = frozenset({"human_admitted",
                             "persona_chosen_research_handoff"})
ANCHOR_RE = re.compile(
    r"^(?:(?:doc_|arc_)[0-9a-f]{16}#[1-9][0-9]*|"
    r"res_[0-9a-f]{16}#1)$")
PROJECT_RE = re.compile(r"^project_[0-9a-f]{16}$")


def _bounded(value: Any, *, name: str, maximum: int,
             allow_empty: bool = False) -> str:
    text = str(value or "").strip()
    if not text and not allow_empty:
        raise ValueError(f"{name} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds the {maximum}-character boundary")
    return text


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-")
    return (value or "item")[:48]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":"))
    return _sha(rendered)[:16]


def _anchors(values) -> list[str]:
    found = []
    for raw in values or ():
        value = str(raw or "").strip()
        if not ANCHOR_RE.fullmatch(value):
            raise ValueError("writing desk source anchor is invalid")
        if value not in found:
            found.append(value)
    return found


class WritingDesk:
    """One persona's seed, project, revision, and receipt ledger."""

    def __init__(self, persona_dir: str | os.PathLike[str], *, now_fn=time.time):
        self.persona_dir = Path(persona_dir).resolve()
        self.root = self.persona_dir / "body" / "writing_desk"
        self.seeds = self.root / "seeds"
        self.projects = self.root / "projects"
        self.index = self.root / "index.jsonl"
        self.receipts = self.root / "receipts.jsonl"
        self.now_fn = now_fn
        self._lock = threading.RLock()

    def _ensure(self) -> None:
        self.seeds.mkdir(parents=True, exist_ok=True)
        self.projects.mkdir(parents=True, exist_ok=True)

    def _append(self, path: Path, record: Mapping[str, Any]) -> dict:
        self._ensure()
        value = dict(record)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                value, ensure_ascii=False, sort_keys=True) + "\n")
        return value

    def _read_records(self, path: Path, limit: int = 500) -> list[dict]:
        if not path.is_file():
            return []
        found = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    found.append(value)
        return [dict(value) for value in found[-max(1, min(int(limit), 2000)):]]

    def records(self, *, kind: str | None = None,
                limit: int = 100) -> list[dict]:
        with self._lock:
            values = self._read_records(self.index, limit=2000)
        if kind is not None:
            values = [value for value in values if value.get("kind") == kind]
        return values[-max(1, min(int(limit), 500)):]

    def receipt_records(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return self._read_records(self.receipts, limit=limit)

    def _action_for_run(self, run_id: str) -> dict | None:
        return next((record for record in reversed(self.records(limit=500))
                     if record.get("run_id") == run_id), None)

    def _seed_path(self, ref: str) -> Path:
        pure = PurePosixPath(str(ref or "").replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts \
                or len(pure.parts) != 2 or pure.parts[0] != "seeds":
            raise ValueError("writing desk seed reference escaped its boundary")
        path = (self.seeds / pure.parts[1]).resolve()
        if path.parent != self.seeds.resolve():
            raise ValueError("writing desk seed reference escaped its collection")
        return path

    def _project_dir(self, project_id: str) -> Path:
        project_id = str(project_id or "")
        if not PROJECT_RE.fullmatch(project_id):
            raise ValueError("writing desk project id is invalid")
        path = (self.projects / project_id).resolve()
        if path.parent != self.projects.resolve():
            raise ValueError("writing desk project escaped its collection")
        return path

    def admit_seed(self, label: str, *, content: str = "",
                   anchors=(), ownership: str = "human_admitted") -> dict:
        """Admit bounded material without starting autonomous work."""
        label = _bounded(label, name="writing desk seed label",
                         maximum=MAX_LABEL_CHARS)
        content = _bounded(content, name="writing desk seed content",
                           maximum=MAX_SEED_CHARS, allow_empty=True)
        anchors = _anchors(anchors)
        ownership = str(ownership or "").strip()
        if ownership not in SEED_OWNERSHIPS:
            raise ValueError("writing desk seed ownership is invalid")
        if not content and not anchors:
            raise ValueError(
                "writing desk seed needs text or an exact source anchor")
        source_digest = _digest({"content": content, "anchors": anchors,
                                 "ownership": ownership})
        seed_id = f"seed_{source_digest}"
        with self._lock:
            existing = next((record for record in self.records(
                kind="seed_admitted", limit=500)
                if record.get("seed_id") == seed_id), None)
            if existing:
                return {**existing, "duplicate": True}
            ref = None
            content_sha = None
            if content:
                self._ensure()
                content_sha = _sha(content)
                path = self.seeds / f"{seed_id}-{_slug(label)}.txt"
                with path.open("x", encoding="utf-8") as handle:
                    handle.write(content)
                ref = f"seeds/{path.name}"
            record = self._append(self.index, {
                "kind": "seed_admitted",
                "seed_id": seed_id,
                "label": label,
                "ref": ref,
                "anchors": anchors,
                "chars": len(content),
                "sha256": content_sha,
                "source_digest": source_digest,
                "ownership": ownership,
                "created_at": float(self.now_fn()),
            })
            return {**record, "duplicate": False}

    def seed(self, seed_id: str, *, include_content: bool = False) -> dict:
        record = next((record for record in self.records(
            kind="seed_admitted", limit=500)
            if record.get("seed_id") == str(seed_id)), None)
        if record is None:
            raise ValueError("writing desk seed does not exist")
        value = dict(record)
        if include_content and value.get("ref"):
            text = self._seed_path(value["ref"]).read_text(encoding="utf-8")
            value["content"] = text[:MAX_READ_CHARS]
            value["content_truncated"] = len(text) > MAX_READ_CHARS
        return value

    def pending_seeds(self) -> list[dict]:
        admitted = self.records(kind="seed_admitted", limit=500)
        resolved = {record.get("seed_id") for record in
                    self.records(kind="seed_resolved", limit=500)}
        return [record for record in admitted
                if record.get("seed_id") not in resolved]

    def resolve_seed(self, seed_id: str, run_id: str, outcome: str, *,
                     project_id: str | None = None) -> dict:
        self.seed(seed_id)
        run_id = _bounded(run_id, name="writing desk run id", maximum=160)
        outcome = _bounded(outcome, name="writing desk seed outcome", maximum=80)
        with self._lock:
            existing = next((record for record in self.records(
                kind="seed_resolved", limit=500)
                if record.get("seed_id") == seed_id), None)
            if existing:
                return existing
            return self._append(self.index, {
                "kind": "seed_resolved", "seed_id": seed_id,
                "run_id": run_id, "outcome": outcome,
                "project_id": project_id,
                "ownership": "persona_private",
                "resolved_at": float(self.now_fn()),
            })

    def _views(self) -> dict[str, dict]:
        views = {}
        for record in self.records(limit=2000):
            kind = record.get("kind")
            project_id = record.get("project_id")
            if not project_id:
                continue
            if kind == "project_started":
                views[project_id] = {
                    "project_id": project_id,
                    "title": record.get("title"),
                    "form": record.get("form"),
                    "state": "open",
                    "source": dict(record.get("source") or {}),
                    "created_at": record.get("created_at"),
                    "updated_at": record.get("created_at"),
                    "revision_count": 1,
                    "latest_revision": record.get("revision_ref"),
                    "latest_sha256": record.get("sha256"),
                }
            elif project_id in views and kind == "revision_appended":
                views[project_id].update({
                    "state": "open",
                    "updated_at": record.get("created_at"),
                    "revision_count": int(record.get("revision", 0)),
                    "latest_revision": record.get("revision_ref"),
                    "latest_sha256": record.get("sha256"),
                })
            elif project_id in views and kind == "project_resolved":
                views[project_id].update({
                    "state": record.get("resolution"),
                    "updated_at": record.get("resolved_at"),
                })
            elif project_id in views and kind == "project_resumed":
                views[project_id].update({
                    "state": "open",
                    "updated_at": record.get("resumed_at"),
                })
        return views

    def projects_status(self, *, state: str | None = None) -> list[dict]:
        values = list(self._views().values())
        if state is not None:
            values = [value for value in values if value.get("state") == state]
        return sorted(values, key=lambda value: (
            -float(value.get("updated_at") or 0.0), value["project_id"]))

    def project(self, project_id: str, *, include_content: bool = False) -> dict:
        view = self._views().get(str(project_id))
        if view is None:
            raise ValueError("writing desk project does not exist")
        value = dict(view)
        if include_content:
            pure = PurePosixPath(str(value["latest_revision"]).replace("\\", "/"))
            if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 4 \
                    or pure.parts[0] != "projects" \
                    or pure.parts[1] != project_id \
                    or pure.parts[2] != "revisions":
                raise ValueError("writing desk revision reference is invalid")
            path = (self.root / Path(*pure.parts)).resolve()
            expected = (self._project_dir(project_id) / "revisions").resolve()
            if path.parent != expected:
                raise ValueError("writing desk revision escaped its project")
            text = path.read_text(encoding="utf-8")
            value["content"] = text[:MAX_READ_CHARS]
            value["content_truncated"] = len(text) > MAX_READ_CHARS
        return value

    def _write_revision(self, project_id: str, revision: int,
                        content: str) -> tuple[str, str]:
        project_dir = self._project_dir(project_id)
        revisions = project_dir / "revisions"
        revisions.mkdir(parents=True, exist_ok=True)
        path = revisions / f"{revision:06d}.md"
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
        return (f"projects/{project_id}/revisions/{path.name}", _sha(content))

    def start_project(self, run_id: str, title: str, form: str,
                      content: str, *, source: Mapping[str, Any]) -> dict:
        run_id = _bounded(run_id, name="writing desk run id", maximum=160)
        title = _bounded(title, name="writing desk title", maximum=MAX_LABEL_CHARS)
        form = _bounded(form, name="writing desk form", maximum=80)
        content = _bounded(content, name="writing desk revision",
                           maximum=MAX_REVISION_CHARS)
        source = dict(source or {})
        source["anchors"] = _anchors(source.get("anchors") or ())
        source_digest = _bounded(
            source.get("source_digest") or _digest(source),
            name="writing desk source digest", maximum=80)
        source["source_digest"] = source_digest
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this writing desk run already committed an action")
            prior = next((project for project in self.projects_status()
                          if (project.get("source") or {}).get(
                              "source_digest") == source_digest), None)
            if prior:
                raise ValueError("this source already belongs to a writing project")
            created_at = float(self.now_fn())
            project_key = {
                "run_id": run_id, "source_digest": source_digest,
                "created_at": created_at,
            }
            project_id = f"project_{_digest(project_key)}"
            revision_ref, content_sha = self._write_revision(
                project_id, 1, content)
            return self._append(self.index, {
                "kind": "project_started", "project_id": project_id,
                "run_id": run_id, "title": title, "form": form,
                "source": source, "revision": 1,
                "revision_ref": revision_ref,
                "chars": len(content), "sha256": content_sha,
                "ownership": "persona_private",
                "created_at": created_at,
            })

    def append_revision(self, run_id: str, project_id: str,
                        content: str) -> dict:
        run_id = _bounded(run_id, name="writing desk run id", maximum=160)
        content = _bounded(content, name="writing desk revision",
                           maximum=MAX_REVISION_CHARS)
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this writing desk run already committed an action")
            project = self.project(project_id)
            if project["state"] != "open":
                raise ValueError("only an open writing project may receive a revision")
            content_sha = _sha(content)
            if content_sha == project.get("latest_sha256"):
                raise ValueError("writing desk rejected an unchanged revision")
            revision = int(project["revision_count"]) + 1
            revision_ref, content_sha = self._write_revision(
                project_id, revision, content)
            return self._append(self.index, {
                "kind": "revision_appended", "project_id": project_id,
                "run_id": run_id, "revision": revision,
                "revision_ref": revision_ref,
                "chars": len(content), "sha256": content_sha,
                "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            })

    def resolve_project(self, run_id: str, project_id: str,
                        resolution: str) -> dict:
        run_id = _bounded(run_id, name="writing desk run id", maximum=160)
        resolution = str(resolution or "").casefold()
        if resolution not in RESOLUTIONS:
            raise ValueError(
                f"writing desk resolution must be one of {sorted(RESOLUTIONS)}")
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this writing desk run already committed an action")
            project = self.project(project_id)
            if project["state"] != "open":
                raise ValueError("only an open writing project may be resolved")
            return self._append(self.index, {
                "kind": "project_resolved", "project_id": project_id,
                "run_id": run_id, "resolution": resolution,
                "ownership": "persona_private",
                "resolved_at": float(self.now_fn()),
            })

    def resume_project(self, run_id: str, project_id: str) -> dict:
        run_id = _bounded(run_id, name="writing desk run id", maximum=160)
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this writing desk run already committed an action")
            project = self.project(project_id)
            if project["state"] != "paused":
                raise ValueError("only a paused writing project may resume")
            return self._append(self.index, {
                "kind": "project_resumed", "project_id": project_id,
                "run_id": run_id, "ownership": "persona_private",
                "resumed_at": float(self.now_fn()),
            })

    def record_receipt(self, record: Mapping[str, Any]) -> dict:
        """Append content-free model/action accounting."""
        allowed = {
            "kind", "run_id", "candidate_key", "outcome", "reason",
            "project_id", "seed_id", "model", "provider", "locality",
            "model_requests", "provider_http_attempts", "input_tokens",
            "output_tokens", "total_tokens", "estimated_cost_usd",
            "readiness", "affinity", "source_satiety", "desk_satiety",
            "created_at",
        }
        value = {key: item for key, item in dict(record or {}).items()
                 if key in allowed and item is not None}
        value.setdefault("kind", "writing_desk_run")
        value.setdefault("created_at", float(self.now_fn()))
        with self._lock:
            return self._append(self.receipts, value)

    def status(self) -> dict:
        return {
            "root": "body/writing_desk",
            "pending_seeds": self.pending_seeds(),
            "projects": self.projects_status(),
            "receipts": self.receipt_records(limit=30),
            "policy": {
                "inspect": "admitted seeds, owned projects, admitted anchors",
                "create": "one append-only project action per field win",
                "overwrite": False,
                "delete": False,
                "publish": False,
                "message": False,
                "external_effects": False,
            },
        }
