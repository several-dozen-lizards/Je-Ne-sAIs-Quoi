"""Persona-private, append-only interests, evidence, notes, and reports."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


INTEREST_RE = re.compile(r"^interest_[0-9a-f]{16}$")
OPPORTUNITY_RE = re.compile(r"^opportunity_[0-9a-f]{16}$")
SOURCE_RE = re.compile(r"^web_[0-9a-f]{16}$")
REPORT_RE = re.compile(r"^report_[0-9a-f]{16}$")
REPORT_ANCHOR_RE = re.compile(r"^res_([0-9a-f]{16})#1$")
PDF_PAGE_MARKER_RE = re.compile(
    r"(?m)^\[PDF page ([1-9][0-9]*) of ([1-9][0-9]*)\]\n")
TERMINAL = frozenset({"paused", "abandoned", "satisfied"})
CLAIM_RELATIONSHIPS = frozenset({
    "supports", "qualifies", "conflicts", "different_definition",
    "different_timeframe", "contextualizes", "unclear", "unresolved",
})
CLAIM_DIRECTNESS = frozenset({
    "source_statement", "resident_inference", "present_endorsement",
})
CLAIM_VISIBILITY = frozenset({"private", "shareable"})
CLAIM_CITATION_RE = re.compile(
    r"^\[(web_[0-9a-f]{16})(?: p\.([1-9][0-9]{0,2}))?\]$")


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

    def create_opportunity(self, topic: str, *, origin: str) -> dict:
        """Record an affordance without manufacturing resident interest."""
        topic = _bounded(topic, "research opportunity", 240)
        origin = _bounded(origin, "research opportunity origin", 80)
        opportunity_id = "opportunity_" + _digest({
            "topic": topic.casefold(), "origin": origin})[:16]
        prior = next((record for record in self.records(
            "opportunity_opened", limit=2000)
            if record.get("opportunity_id") == opportunity_id), None)
        if prior:
            return {**prior, "duplicate": True}
        return {**self._append(self.index, {
            "kind": "opportunity_opened",
            "opportunity_id": opportunity_id,
            "topic": topic, "origin": origin,
            "ownership": "human_offered",
            "created_at": float(self.now_fn()),
        }), "duplicate": False}

    def settle_opportunity(self, opportunity_id: str, *, outcome: str,
                           run_id: str) -> dict:
        if not OPPORTUNITY_RE.fullmatch(str(opportunity_id or "")):
            raise ValueError("research opportunity id is invalid")
        prior = next((record for record in self.records(
            "opportunity_settled", limit=2000)
            if record.get("opportunity_id") == opportunity_id), None)
        if prior:
            return {**prior, "duplicate": True}
        return {**self._append(self.index, {
            "kind": "opportunity_settled",
            "opportunity_id": opportunity_id,
            "outcome": str(outcome or "quiet")[:80],
            "run_id": str(run_id or "")[:160],
            "ownership": "persona_private",
            "settled_at": float(self.now_fn()),
        }), "duplicate": False}

    def pending_opportunities(self) -> list[dict]:
        settled = {record.get("opportunity_id") for record in self.records(
            "opportunity_settled", limit=2000)}
        return [record for record in self.records(
            "opportunity_opened", limit=2000)
            if record.get("opportunity_id") not in settled]

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
                web_range_id = str(
                    hit.get("web_range_id") or "public_web")[:120]
                source_class = str(
                    hit.get("source_class") or "unclassified_public")[:80]
                volatility = str(hit.get("volatility") or "medium")[:16]
                foreground = bool(hit.get("foreground", False))
                fetch_reason = str(hit.get("fetch_reason") or "")[:500]
                source_id = "web_" + _digest({
                    "interest_id": interest_id, "url": url})[:16]
                source_ids.append(source_id)
                if not any(r.get("source_id") == source_id
                           for r in self.records("source_admitted", limit=2000)):
                    self._append(self.index, {
                        "kind": "source_admitted", "source_id": source_id,
                        "interest_id": interest_id, "title": title, "url": url,
                        "query": query, "state": "unread",
                        "web_range_id": web_range_id,
                        "source_class": source_class,
                        "volatility": volatility,
                        "foreground": foreground,
                        "fetch_reason": fetch_reason,
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
                       text: str, content_type: str, run_id: str,
                       page_count: int = 0, extracted_pages=(),
                       extraction_truncated: bool = False,
                       web_range_id: str = "public_web",
                       source_class: str = "unclassified_public",
                       volatility: str = "medium", discovered_links=()):
        source = self.source(source_id)
        if source.get("url") != url and not url.startswith(("http://", "https://")):
            raise ValueError("research evidence URL is invalid")
        text = str(text or "").strip()[:24000]
        page_count = max(0, int(page_count or 0))
        pages = tuple(sorted({int(page) for page in extracted_pages or ()
                              if 1 <= int(page) <= page_count}))
        if content_type != "application/pdf":
            page_count, pages, extraction_truncated = 0, (), False
        digest = _digest(text)
        self._ensure()
        path = self.sources / f"{source_id}-{digest[:12]}.txt"
        if not path.exists():
            path.write_text(text, encoding="utf-8")
        return self._append(self.index, {
            "kind": "source_read", "source_id": source_id,
            "interest_id": source["interest_id"], "title": str(title)[:300],
            "url": url, "content_type": content_type,
            "page_count": page_count, "extracted_pages": list(pages),
            "extraction_truncated": bool(extraction_truncated),
            "content_sha256": digest, "ref": f"sources/{path.name}",
            "chars": len(text), "run_id": str(run_id)[:160],
            "web_range_id": str(web_range_id or "public_web")[:120],
            "source_class": str(
                source_class or "unclassified_public")[:80],
            "volatility": str(volatility or "medium")[:16],
            "discovered_links": list(dict.fromkeys(
                str(link)[:2048] for link in discovered_links or ()))[:24],
            "retrieved_at": float(self.now_fn()),
            "ownership": "external_untrusted"})

    def read_sources(self, interest_id: str) -> list[dict]:
        """Return the latest immutable evidence snapshot for each read source."""
        self.interest(interest_id)
        latest = {}
        for record in self.records("source_read", limit=2000):
            if record.get("interest_id") == interest_id:
                latest[record.get("source_id")] = dict(record)
        return sorted(latest.values(), key=lambda item: float(
            item.get("retrieved_at") or 0.0))

    def comparison_sources(self, interest_id: str, maximum: int) -> list[dict]:
        """Return one not-yet-reported source set, or no unfinished demand."""
        maximum = max(2, min(int(maximum), 4))
        sources = self.read_sources(interest_id)[-maximum:]
        if len(sources) < 2:
            return []
        source_ids = [source["source_id"] for source in sources]
        compared = {
            tuple(record.get("source_ids") or ())
            for record in self.records("report_created", limit=2000)
            if record.get("interest_id") == interest_id
        }
        covered = {source_id for source_set in compared
                   for source_id in source_set}
        return ([] if tuple(source_ids) in compared
                or all(source_id in covered for source_id in source_ids)
                else sources)

    def _evidence_snapshot(self, source_id: str) -> tuple[dict, dict, str]:
        """Resolve one immutable evidence snapshot and verify its digest."""
        source_id = str(source_id or "")
        if not SOURCE_RE.fullmatch(source_id):
            raise ValueError("research evidence source id is invalid")
        source = self.source(source_id)
        read = next((record for record in reversed(self.records(
            "source_read", limit=2000))
            if record.get("source_id") == source_id), None)
        if read is None:
            raise ValueError("research evidence source has not been read")
        parts = PurePosixPath(str(read.get("ref") or "").replace(
            "\\", "/")).parts
        if len(parts) != 2 or parts[0] != "sources" or ".." in parts:
            raise ValueError("research evidence reference escaped its boundary")
        path = (self.sources / parts[1]).resolve()
        if path.parent != self.sources.resolve() or not path.is_file():
            raise ValueError("research evidence snapshot does not exist")
        full_content = path.read_text(encoding="utf-8")
        if _digest(full_content) != read.get("content_sha256"):
            raise ValueError("research evidence snapshot digest changed")
        return source, read, full_content

    def inspect_source_page(self, source_id: str, page: int) -> dict:
        """Open one exact host-marked PDF page from stored evidence only."""
        source, read, full_content = self._evidence_snapshot(source_id)
        if read.get("content_type") != "application/pdf":
            raise ValueError("research evidence source is not a PDF")
        try:
            page = int(page)
        except (TypeError, ValueError) as exc:
            raise ValueError("research PDF page is invalid") from exc
        page_count = int(read.get("page_count") or 0)
        extracted_pages = [int(value) for value in
                           read.get("extracted_pages") or ()]
        if page < 1 or page > page_count or page not in extracted_pages:
            raise ValueError("research PDF page was not extracted")
        markers = list(PDF_PAGE_MARKER_RE.finditer(full_content))
        matches = [match for match in markers
                   if int(match.group(1)) == page]
        if len(matches) != 1:
            raise ValueError("research PDF page marker is missing or ambiguous")
        marker = matches[0]
        if int(marker.group(2)) != page_count:
            raise ValueError("research PDF page marker disagrees with provenance")
        next_marker = next((candidate for candidate in markers
                            if candidate.start() > marker.start()), None)
        content = full_content[
            marker.end():next_marker.start() if next_marker else None].strip()
        if not content:
            raise ValueError("research PDF page contained no stored text")
        return {
            "source_id": source_id,
            "citation": f"[{source_id} p.{page}]",
            "title": read.get("title") or source.get("title"),
            "url": read.get("url") or source.get("url"),
            "page": page, "page_count": page_count,
            "content": content,
            "content_sha256": read.get("content_sha256"),
            "extraction_truncated": bool(
                read.get("extraction_truncated", False)),
            "ownership": "external_untrusted",
            "network_request": False,
        }

    def inspect_source(self, source_id: str, maximum: int = 24000) -> dict:
        """Open one exact stored web snapshot without revisiting the network."""
        source, read, full_content = self._evidence_snapshot(source_id)
        maximum = max(1, min(int(maximum), 24000))
        return {
            "source_id": source_id,
            "citation": f"[{source_id}]",
            "title": read.get("title") or source.get("title"),
            "url": read.get("url") or source.get("url"),
            "content_type": read.get("content_type"),
            "content": full_content[:maximum],
            "content_sha256": read.get("content_sha256"),
            "web_range_id": read.get("web_range_id")
                or source.get("web_range_id"),
            "source_class": read.get("source_class")
                or source.get("source_class"),
            "volatility": read.get("volatility") or source.get("volatility"),
            "retrieved_at": read.get("retrieved_at"),
            "ownership": "external_untrusted",
            "network_request": False,
        }

    def inspect_evidence_set(self, source_ids, *, maximum: int = 7200) -> dict:
        """Resolve two-to-four exact same-interest snapshots without paths."""
        ids = []
        for raw in source_ids or ():
            source_id = str(raw or "")
            if not SOURCE_RE.fullmatch(source_id):
                raise ValueError("research evidence set contains an invalid source")
            if source_id not in ids:
                ids.append(source_id)
        if not 2 <= len(ids) <= 4:
            raise ValueError("research comparison requires two through four sources")
        maximum = max(len(ids), min(int(maximum), 16000))
        per_source = max(1, maximum // len(ids))
        items = []
        interest_id = None
        for source_id in ids:
            source, read, full_content = self._evidence_snapshot(source_id)
            if interest_id is None:
                interest_id = source["interest_id"]
            elif source["interest_id"] != interest_id:
                raise ValueError("research comparison crossed interest boundaries")
            items.append({
                "source_id": source_id,
                "title": read.get("title") or source.get("title"),
                "url": read.get("url") or source.get("url"),
                "content_type": read.get("content_type"),
                "page_count": int(read.get("page_count") or 0),
                "extracted_pages": list(read.get("extracted_pages") or ()),
                "extraction_truncated": bool(
                    read.get("extraction_truncated", False)),
                "content_sha256": read.get("content_sha256"),
                "content": full_content[:per_source],
            })
        return {
            "interest_id": interest_id,
            "topic": self.interest(interest_id)["topic"],
            "source_ids": ids,
            "source_set_digest": _digest(ids)[:16],
            "sources": items,
        }

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
        content_digest = _digest(content)
        record_digest = _digest({
            "kind": kind, "interest_id": interest_id,
            "content_sha256": content_digest, "source_ids": sources})
        folder = self.notes if kind == "note" else self.reports
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{kind}_{record_digest[:16]}.md"
        if not path.exists():
            path.write_text(content, encoding="utf-8")
        text_id = f"{kind}_{record_digest[:16]}"
        record = {
            "kind": f"{kind}_created", "interest_id": interest_id,
            f"{kind}_id": text_id,
            "ref": f"{folder.name}/{path.name}", "sha256": content_digest,
            "source_set_digest": _digest(sources)[:16],
            "chars": len(content), "source_ids": sources,
            "run_id": str(run_id)[:160], "ownership": "persona_private",
            "created_at": float(self.now_fn())}
        if kind == "report":
            record["anchor"] = f"res_{record_digest[:16]}#1"
        return self._append(self.index, record)

    def record_claim_observations(self, interest_id: str, claims, *,
                                  allowed_source_ids, run_id: str) -> list[dict]:
        """Append source-bounded assessments; never collapse disagreement."""
        self.interest(interest_id)
        allowed = {str(value) for value in allowed_source_ids or ()}
        records = []
        for raw in list(claims or ())[:8]:
            value = dict(raw or {})
            claim = _bounded(value.get("claim"), "research claim", 500)
            relationship = str(
                value.get("relationship") or "unresolved").casefold()
            if relationship not in CLAIM_RELATIONSHIPS:
                raise ValueError("research claim relationship is invalid")
            directness = str(
                value.get("directness") or "resident_inference").casefold()
            if directness not in CLAIM_DIRECTNESS:
                raise ValueError("research claim directness is invalid")
            visibility = str(
                value.get("visibility") or "private").casefold()
            if visibility not in CLAIM_VISIBILITY:
                raise ValueError("research claim visibility is invalid")
            valid_time = str(value.get("valid_time") or "unknown").strip()[:240]
            valid_time_basis = str(
                value.get("valid_time_basis") or "unknown").casefold()
            if valid_time_basis not in {
                    "source_stated", "resident_inferred", "unknown"}:
                raise ValueError("research claim valid-time basis is invalid")
            relevance_cue = str(
                value.get("relevance_cue") or "").strip()[:500]
            try:
                low = float(value.get("confidence_low"))
                high = float(value.get("confidence_high"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "research claim confidence range is invalid") from exc
            if not 0.0 <= low <= high <= 1.0:
                raise ValueError(
                    "research claim confidence range is invalid")
            citations = []
            source_ids = []
            for citation in list(value.get("citations") or ())[:8]:
                citation = str(citation or "").strip()
                match = CLAIM_CITATION_RE.fullmatch(citation)
                if match is None or match.group(1) not in allowed:
                    raise ValueError(
                        "research claim citation escaped its evidence set")
                if match.group(2):
                    self.inspect_source_page(
                        match.group(1), int(match.group(2)))
                else:
                    self.inspect_source(match.group(1), maximum=1)
                if citation not in citations:
                    citations.append(citation)
                if match.group(1) not in source_ids:
                    source_ids.append(match.group(1))
            if not citations:
                raise ValueError(
                    "research claim requires an exact snapshot citation")
            claim_key = _digest(" ".join(claim.casefold().split()))[:16]
            observation_id = "claim_" + _digest({
                "claim": claim, "relationship": relationship,
                "directness": directness,
                "confidence": [low, high], "citations": citations,
                "valid_time": valid_time,
                "valid_time_basis": valid_time_basis,
            })[:16]
            prior = next((record for record in self.records(
                "claim_observed", limit=2000)
                if record.get("observation_id") == observation_id), None)
            if prior:
                records.append({**prior, "duplicate": True})
                continue
            volatility = sorted({
                str(self.source(source_id).get("volatility") or "medium")
                for source_id in source_ids})
            records.append({**self._append(self.index, {
                "kind": "claim_observed",
                "observation_id": observation_id,
                "claim_key": claim_key,
                "claim": claim,
                "relationship": relationship,
                "directness": directness,
                "confidence_low": round(low, 4),
                "confidence_high": round(high, 4),
                "citations": citations,
                "source_ids": source_ids,
                "source_volatility": volatility,
                "valid_time": valid_time,
                "valid_time_basis": valid_time_basis,
                "encountered_at": float(self.now_fn()),
                "relevance_cue": relevance_cue,
                "visibility": visibility,
                "interest_id": interest_id,
                "run_id": str(run_id or "")[:160],
                "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            }), "duplicate": False})
        return records

    def epistemic_garden(self) -> list[dict]:
        groups = {}
        for record in self.records("claim_observed", limit=2000):
            group = groups.setdefault(record["claim_key"], {
                "claim_key": record["claim_key"],
                "claim": record["claim"],
                "interest_id": record["interest_id"],
                "observations": [],
            })
            group["observations"].append(dict(record))
        values = []
        for group in groups.values():
            relationships = sorted({
                item["relationship"] for item in group["observations"]})
            lows = [float(item["confidence_low"])
                    for item in group["observations"]]
            highs = [float(item["confidence_high"])
                     for item in group["observations"]]
            # Conflict is explicitly described by the resident in context.
            # Confidence spread, age, or differing numbers never manufactures it.
            discrepancy = bool(set(relationships) & {
                "conflicts", "different_definition",
                "different_timeframe", "unclear"})
            citations = list(dict.fromkeys(
                citation for item in group["observations"]
                for citation in item.get("citations") or ()))
            volatility = sorted({
                level for item in group["observations"]
                for level in item.get("source_volatility") or ("medium",)})
            volatility_weights = {"low": .15, "medium": .45, "high": .8}
            volatility_pressure = sum(
                volatility_weights.get(level, .45) for level in volatility
            ) / max(1, len(volatility))
            garden_digest = _digest({
                "claim_key": group["claim_key"],
                "observations": [
                    item["observation_id"]
                    for item in group["observations"]],
            })[:16]
            values.append({
                **group, "relationships": relationships,
                "confidence_low": min(lows),
                "confidence_high": max(highs),
                "citations": citations,
                "source_volatility": volatility,
                "volatility_pressure": round(volatility_pressure, 4),
                "discrepancy": discrepancy,
                "garden_digest": garden_digest,
            })
        return sorted(values, key=lambda value: (
            not value["discrepancy"], value["claim_key"]))

    def settle_garden_opportunity(self, garden_digest: str, *,
                                  outcome: str, run_id: str) -> dict:
        garden_digest = _bounded(
            garden_digest, "garden opportunity digest", 64)
        prior = next((record for record in self.records(
            "garden_opportunity_settled", limit=2000)
            if record.get("garden_digest") == garden_digest), None)
        if prior:
            return {**prior, "duplicate": True}
        return {**self._append(self.index, {
            "kind": "garden_opportunity_settled",
            "garden_digest": garden_digest,
            "outcome": str(outcome or "quiet")[:80],
            "run_id": str(run_id or "")[:160],
            "ownership": "persona_private",
            "created_at": float(self.now_fn()),
        }), "duplicate": False}

    def pending_garden_opportunities(self) -> list[dict]:
        settled = {record.get("garden_digest") for record in self.records(
            "garden_opportunity_settled", limit=2000)}
        return [value for value in self.epistemic_garden()
                if value["discrepancy"]
                and value["garden_digest"] not in settled]

    def shared_epistemic_garden(self) -> list[dict]:
        """Expose only observations the resident explicitly marked shareable."""
        values = []
        for garden in self.epistemic_garden():
            observations = [
                item for item in garden["observations"]
                if item.get("visibility") == "shareable"]
            if not observations:
                continue
            values.append({
                **garden,
                "observations": observations,
                "citations": list(dict.fromkeys(
                    citation for item in observations
                    for citation in item.get("citations") or ())),
            })
        return values

    def report(self, report_id: str) -> dict:
        report_id = str(report_id or "")
        if not REPORT_RE.fullmatch(report_id):
            raise ValueError("research report id is invalid")
        record = next((r for r in reversed(self.records(
            "report_created", limit=2000))
            if r.get("report_id") == report_id), None)
        if record is None:
            raise ValueError("research report does not exist")
        value = dict(record)
        value.setdefault("anchor", f"res_{report_id[7:]}#1")
        return value

    def resolve_report(self, target: str = "latest") -> dict:
        """Resolve an explicit report selector without exposing filesystem paths."""
        target = str(target or "latest").strip()
        if target.casefold() == "latest":
            records = self.records("report_created", limit=2000)
            if not records:
                raise ValueError("no research reports exist")
            return self.report(records[-1]["report_id"])
        anchor = REPORT_ANCHOR_RE.fullmatch(target)
        if anchor is not None:
            return self.report(f"report_{anchor.group(1)}")
        return self.report(target)

    def inspect_anchor(self, anchor: str, maximum: int = 5200) -> dict:
        """Resolve one immutable report revision without accepting a path."""
        match = REPORT_ANCHOR_RE.fullmatch(str(anchor or ""))
        if match is None:
            raise ValueError("research report anchor is invalid")
        maximum = max(1, min(int(maximum), 16000))
        record = self.report(f"report_{match.group(1)}")
        if record["anchor"] != anchor:
            raise ValueError("research report anchor does not match its record")
        full_text = self.read_text(record["ref"])["content"]
        if _digest(full_text) != record.get("sha256"):
            raise ValueError("research report digest changed")
        text = full_text[:maximum]
        interest = self.interest(record["interest_id"])
        sources = []
        for source_id in record.get("source_ids") or ():
            source = self.source(source_id)
            sources.append({
                "source_id": source_id,
                "title": source.get("title"),
                "url": source.get("url"),
            })
        return {
            "anchor": anchor,
            "title": interest.get("topic") or "Research report",
            "content": text,
            "report_id": record["report_id"],
            "interest_id": record["interest_id"],
            "source_ids": list(record.get("source_ids") or ()),
            "sources": sources,
            "sha256": record.get("sha256"),
            "ownership": "persona_private",
        }

    def mark_report_handed_off(self, report_id: str, *, seed_id: str,
                               run_id: str) -> dict:
        report = self.report(report_id)
        prior = next((r for r in reversed(self.records(
            "report_handed_off", limit=2000))
            if r.get("report_id") == report_id), None)
        if prior:
            return {**prior, "duplicate": True}
        return {**self._append(self.index, {
            "kind": "report_handed_off",
            "report_id": report_id,
            "interest_id": report["interest_id"],
            "anchor": report["anchor"],
            "seed_id": str(seed_id or "")[:160],
            "run_id": str(run_id or "")[:160],
            "ownership": "persona_private",
            "created_at": float(self.now_fn()),
        }), "duplicate": False}

    def pending_reports(self) -> list[dict]:
        handed_off = {r.get("report_id") for r in self.records(
            "report_handed_off", limit=2000)}
        open_interests = {r["interest_id"] for r in self.interests(state="open")}
        values = []
        for record in self.records("report_created", limit=2000):
            report_id = record.get("report_id")
            if report_id in handed_off or record.get("interest_id") not in open_interests:
                continue
            value = dict(record)
            value.setdefault("anchor", f"res_{str(report_id)[7:]}#1")
            values.append(value)
        return values

    def read_text(self, ref: str):
        parts = PurePosixPath(str(ref or "").replace("\\", "/")).parts
        if len(parts) != 2 or parts[0] not in {"notes", "reports"} or ".." in parts:
            raise ValueError("research text reference escaped its boundary")
        path = (self.root / parts[0] / parts[1]).resolve()
        if path.parent != (self.root / parts[0]).resolve() or not path.is_file():
            raise ValueError("research text does not exist")
        return {"ref": ref, "content": path.read_text(encoding="utf-8")[:16000]}

    def record_receipt(self, value: Mapping):
        allowed = {"kind", "run_id", "candidate_key", "outcome", "action",
                   "interest_id", "source_id", "query", "model", "provider",
                   "report_id", "anchor", "seed_id",
                   "source_ids", "source_set_digest",
                   "content_type", "page_count", "extracted_pages",
                   "extraction_truncated",
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
        source_reads = self.records("source_read", limit=2000)
        return {"root": "body/research_desk", "interests": self.interests(),
                "opportunities": self.pending_opportunities(),
                "unread_sources": self.unread_sources(),
                "pdf_read_count": sum(
                    record.get("content_type") == "application/pdf"
                    for record in source_reads),
                "notes": self.records("note_created", limit=100),
                "reports": [self.report(r["report_id"]) for r in self.records(
                    "report_created", limit=100)],
                "shared_epistemic_garden": self.shared_epistemic_garden(),
                "private_garden_count": sum(
                    not any(item.get("visibility") == "shareable"
                            for item in garden["observations"])
                    for garden in self.epistemic_garden()),
                "pending_garden_count": len(
                    self.pending_garden_opportunities()),
                "pending_reports": self.pending_reports(),
                "handoffs": self.records("report_handed_off", limit=100),
                "receipts": self.receipt_records(),
                "policy": {"network": "isolated read-only public HTTP(S)",
                           "content_types": ["text/html", "text/plain",
                                             "application/json",
                                             "application/pdf"],
                           "pdf": {"max_pages": 48,
                                   "page_provenance": True,
                                   "exact_page_navigation": True,
                                   "navigation_refetches": False,
                                   "ocr": False,
                                   "active_content": False,
                                   "embedded_files": False},
                           "cookies": False, "javascript": False,
                           "accounts": False, "forms": False,
                           "uploads": False, "publish": False,
                           "message": False, "personal_browser": False}}
