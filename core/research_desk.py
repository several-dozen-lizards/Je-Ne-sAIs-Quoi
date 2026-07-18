"""Persona-private, append-only interests, evidence, notes, and reports."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Mapping


INTEREST_RE = re.compile(r"^interest_[0-9a-f]{16}$")
SOURCE_RE = re.compile(r"^web_[0-9a-f]{16}$")
TERMINAL = frozenset({"paused", "abandoned", "satisfied"})


def _digest(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          default=str, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _bounded(value, name, maximum, *, empty=False):
    text = " ".join(str(value or "").split())
    if not text and not empty:
        raise ValueError(f"{name} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds the {maximum}-character boundary")
    return text


class ResearchDesk:
    def __init__(self, persona_dir: str | os.PathLike[str], *, now_fn=time.time):
        self.root = Path(persona_dir).resolve() / "body" / "research_desk"
        self.index = self.root / "index.jsonl"
        self.receipts = self.root / "receipts.jsonl"
        self.sources = self.root / "sources"
        self.notes = self.root / "notes"
        self.reports = self.root / "reports"
        self.now_fn = now_fn
        self._lock = threading.RLock()

    def _ensure(self):
        for path in (self.root, self.sources, self.notes, self.reports):
            path.mkdir(parents=True, exist_ok=True)

    def _append(self, path: Path, value: Mapping) -> dict:
        self._ensure()
        record = dict(value)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False,
                                    sort_keys=True) + "\n")
        return record

    def records(self, kind=None, limit=500):
        if not self.index.is_file():
            return []
        values = []
        with self._lock, self.index.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict) and (kind is None or item.get("kind") == kind):
                    values.append(item)
        return [dict(value) for value in values[-max(1, min(int(limit), 2000)):]]

    def receipt_records(self, limit=40):
        if not self.receipts.is_file():
            return []
        values = []
        with self._lock, self.receipts.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    values.append(value)
        return values[-max(1, min(int(limit), 200)):]

    def create_interest(self, topic: str, *, origin: str,
                        cue_digest: str = "") -> dict:
        topic = _bounded(topic, "research topic", 240)
        origin = _bounded(origin, "research origin", 80)
        interest_id = "interest_" + _digest(topic.casefold())[:16]
        with self._lock:
            prior = next((r for r in self.records("interest_opened")
                          if r.get("interest_id") == interest_id), None)
            if prior:
                return {**prior, "duplicate": True}
            return {**self._append(self.index, {
                "kind": "interest_opened", "interest_id": interest_id,
                "topic": topic, "origin": origin,
                "cue_digest": str(cue_digest or "")[:64],
                "ownership": "persona_private",
                "created_at": float(self.now_fn())}), "duplicate": False}

    def settle_cue(self, cue_digest: str, outcome: str, run_id: str):
        cue_digest = _bounded(cue_digest, "research cue digest", 64)
        outcome = _bounded(outcome, "research cue outcome", 80)
        with self._lock:
            prior = next((r for r in self.records("cue_settled", limit=2000)
                          if r.get("cue_digest") == cue_digest), None)
            if prior:
                return prior
            return self._append(self.index, {
                "kind": "cue_settled", "cue_digest": cue_digest,
                "outcome": outcome, "run_id": str(run_id or "")[:160],
                "ownership": "persona_private",
                "settled_at": float(self.now_fn())})

    def cue_is_settled(self, cue_digest: str) -> bool:
        return any(r.get("cue_digest") == str(cue_digest)
                   for r in self.records("cue_settled", limit=2000))

    def resolve_interest(self, interest_id: str, state: str, run_id: str):
        self.interest(interest_id)
        state = str(state or "").casefold()
        if state not in TERMINAL:
            raise ValueError("research interest resolution is invalid")
        return self._append(self.index, {
            "kind": "interest_resolved", "interest_id": interest_id,
            "state": state, "run_id": str(run_id or "")[:160],
            "resolved_at": float(self.now_fn()),
            "ownership": "persona_private"})

    def _interest_views(self):
        views = {}
        for record in self.records(limit=2000):
            iid = record.get("interest_id")
            if record.get("kind") == "interest_opened":
                views[iid] = {**record, "state": "open", "search_count": 0,
                              "source_count": 0, "note_count": 0,
                              "report_count": 0, "updated_at": record.get("created_at")}
            elif iid in views and record.get("kind") == "search_recorded":
                views[iid]["search_count"] += 1
                views[iid]["source_count"] += len(record.get("source_ids") or [])
                views[iid]["updated_at"] = record.get("created_at")
            elif iid in views and record.get("kind") == "note_created":
                views[iid]["note_count"] += 1
                views[iid]["updated_at"] = record.get("created_at")
            elif iid in views and record.get("kind") == "report_created":
                views[iid]["report_count"] += 1
                views[iid]["updated_at"] = record.get("created_at")
            elif iid in views and record.get("kind") == "interest_resolved":
                views[iid]["state"] = record.get("state")
                views[iid]["updated_at"] = record.get("resolved_at")
        return views

    def interests(self, state=None):
        values = list(self._interest_views().values())
        if state:
            values = [v for v in values if v.get("state") == state]
        return sorted(values, key=lambda v: -float(v.get("updated_at") or 0))

    def interest(self, interest_id):
        value = self._interest_views().get(str(interest_id))
        if value is None:
            raise ValueError("research interest does not exist")
        return dict(value)

    def record_search(self, interest_id: str, query: str, hits, run_id: str):
        self.interest(interest_id)
        query = _bounded(query, "research query", 300)
        source_ids = []
        with self._lock:
            for hit in list(hits or [])[:10]:
                url = _bounded(hit.get("url"), "research result URL", 2048)
                title = _bounded(hit.get("title") or url, "research result title", 300)
                source_id = "web_" + _digest({
                    "interest_id": interest_id, "url": url})[:16]
                source_ids.append(source_id)
                if not any(r.get("source_id") == source_id
                           for r in self.records("source_admitted", limit=2000)):
                    self._append(self.index, {
                        "kind": "source_admitted", "source_id": source_id,
                        "interest_id": interest_id, "title": title, "url": url,
                        "query": query, "state": "unread",
                        "ownership": "external_untrusted",
                        "created_at": float(self.now_fn())})
            return self._append(self.index, {
                "kind": "search_recorded", "interest_id": interest_id,
                "query": query, "source_ids": source_ids,
                "result_count": len(source_ids), "run_id": str(run_id)[:160],
                "created_at": float(self.now_fn())})

    def source(self, source_id: str):
        if not SOURCE_RE.fullmatch(str(source_id or "")):
            raise ValueError("research source id is invalid")
        record = next((r for r in reversed(self.records("source_admitted", limit=2000))
                       if r.get("source_id") == source_id), None)
        if record is None:
            raise ValueError("research source does not exist")
        return dict(record)

    def unread_sources(self, interest_id=None):
        read = {r.get("source_id") for r in self.records("source_read", limit=2000)}
        unavailable = {r.get("source_id") for r in self.records(
            "source_unavailable", limit=2000)}
        values = [r for r in self.records("source_admitted", limit=2000)
                  if r.get("source_id") not in read
                  and r.get("source_id") not in unavailable]
        if interest_id:
            values = [r for r in values if r.get("interest_id") == interest_id]
        return values

    def mark_source_unavailable(self, source_id: str, reason: str, run_id: str):
        source = self.source(source_id)
        return self._append(self.index, {
            "kind": "source_unavailable", "source_id": source_id,
            "interest_id": source["interest_id"],
            "reason": str(reason or "unavailable")[:240],
            "run_id": str(run_id or "")[:160],
            "observed_at": float(self.now_fn()),
            "ownership": "external_untrusted"})

    def store_evidence(self, source_id: str, *, title: str, url: str,
                       text: str, content_type: str, run_id: str):
        source = self.source(source_id)
        if source.get("url") != url and not url.startswith(("http://", "https://")):
            raise ValueError("research evidence URL is invalid")
        text = str(text or "").strip()[:24000]
        digest = _digest(text)
        self._ensure()
        path = self.sources / f"{source_id}-{digest[:12]}.txt"
        if not path.exists():
            path.write_text(text, encoding="utf-8")
        return self._append(self.index, {
            "kind": "source_read", "source_id": source_id,
            "interest_id": source["interest_id"], "title": str(title)[:300],
            "url": url, "content_type": content_type,
            "content_sha256": digest, "ref": f"sources/{path.name}",
            "chars": len(text), "run_id": str(run_id)[:160],
            "retrieved_at": float(self.now_fn()),
            "ownership": "external_untrusted"})

    def create_text(self, kind: str, interest_id: str, content: str, *,
                    source_ids, run_id: str):
        if kind not in {"note", "report"}:
            raise ValueError("research text kind is invalid")
        self.interest(interest_id)
        content = str(content or "").strip()
        if not content or len(content) > 16000:
            raise ValueError("research text must be 1 through 16000 characters")
        sources = []
        for sid in source_ids or ():
            self.source(sid)
            if sid not in sources:
                sources.append(sid)
        if not sources:
            raise ValueError("research text requires at least one source citation")
        digest = _digest(content)
        folder = self.notes if kind == "note" else self.reports
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{kind}_{digest[:16]}.md"
        if not path.exists():
            path.write_text(content, encoding="utf-8")
        return self._append(self.index, {
            "kind": f"{kind}_created", "interest_id": interest_id,
            f"{kind}_id": f"{kind}_{digest[:16]}",
            "ref": f"{folder.name}/{path.name}", "sha256": digest,
            "chars": len(content), "source_ids": sources,
            "run_id": str(run_id)[:160], "ownership": "persona_private",
            "created_at": float(self.now_fn())})

    def read_text(self, ref: str):
        parts = Path(str(ref or "").replace("\\", "/")).parts
        if len(parts) != 2 or parts[0] not in {"notes", "reports"} or ".." in parts:
            raise ValueError("research text reference escaped its boundary")
        path = (self.root / parts[0] / parts[1]).resolve()
        if path.parent != (self.root / parts[0]).resolve() or not path.is_file():
            raise ValueError("research text does not exist")
        return {"ref": ref, "content": path.read_text(encoding="utf-8")[:16000]}

    def record_receipt(self, value: Mapping):
        allowed = {"kind", "run_id", "candidate_key", "outcome", "action",
                   "interest_id", "source_id", "query", "model", "provider",
                   "locality", "model_requests", "provider_http_attempts",
                   "input_tokens", "output_tokens", "total_tokens",
                   "estimated_cost_usd", "readiness", "source_satiety",
                   "research_satiety", "created_at", "reason"}
        row = {k: v for k, v in dict(value or {}).items()
               if k in allowed and v is not None}
        row.setdefault("kind", "research_desk_run")
        row.setdefault("created_at", float(self.now_fn()))
        return self._append(self.receipts, row)

    def status(self):
        return {"root": "body/research_desk", "interests": self.interests(),
                "unread_sources": self.unread_sources(),
                "notes": self.records("note_created", limit=100),
                "reports": self.records("report_created", limit=100),
                "receipts": self.receipt_records(),
                "policy": {"network": "isolated read-only public HTTP(S)",
                           "cookies": False, "javascript": False,
                           "accounts": False, "forms": False,
                           "uploads": False, "publish": False,
                           "message": False, "personal_browser": False}}
