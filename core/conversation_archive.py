"""Human-owned legacy conversation archive and persona-specific reader.

Raw imported bytes remain immutable and content-addressed.  Normalized
sessions and vector data are derived indexes.  Reading state belongs to the
persona, while the source library belongs to the local human.  An archive
anchor describes documented history; it never claims autobiographical recall.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Iterable, Mapping

from core.users import slugify


MAX_SOURCE_BYTES = 16 * 1024 * 1024
ARCHIVE_CONTEXT_BUDGET = 1100
ARCHIVE_ID_RE = re.compile(r"arc_[0-9a-f]{16}")
ARCHIVE_ANCHOR_RE = re.compile(r"(arc_[0-9a-f]{16})#([1-9][0-9]*)")


class ArchiveError(ValueError):
    pass


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    json.loads(rendered)
    fd, temporary = tempfile.mkstemp(
        prefix=".jnsq-archive-", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(encoding)
            if "\x00" not in text:
                return text.replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    raise ArchiveError("legacy conversation encoding is unsupported")


def _clip(text: str, maximum: int) -> str:
    text = str(text or "")
    if len(text) <= maximum:
        return text
    cut = text.rfind(" ", 0, maximum)
    return text[:cut if cut > maximum // 2 else maximum].rstrip() \
        + "\n[...archive excerpt continues]"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']{2,}", str(text or "").casefold())


def _clean_turn(value: Mapping, index: int) -> dict | None:
    value = dict(value or {})
    content = str(value.get("content") or value.get("text") or "").strip()
    if not content:
        return None
    role = str(value.get("role") or "").strip().casefold()
    sender = str(value.get("sender") or value.get("speaker") or "").strip()
    event = str(value.get("event") or "").strip().casefold()
    if event and event not in {"message", "turn"} and not role:
        return None
    if sender.casefold() == "system" and role not in {"user", "assistant"}:
        return None
    if not sender:
        sender = {"user": "Re", "assistant": "persona"}.get(role, "unknown")
    timestamp = str(value.get("timestamp") or value.get("time") or "").strip()
    return {
        "index": index, "sender": sender[:80], "role": role[:24],
        "timestamp": timestamp[:80], "content": content,
    }


def _jsonl_turns(text: str) -> list[dict]:
    turns = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        turn = _clean_turn(value, len(turns))
        if turn is not None:
            turns.append(turn)
    return turns


def _saved_session_turns(text: str) -> list[dict]:
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ArchiveError("saved conversation JSON is invalid") from exc
    rows = value.get("conversation") if isinstance(value, dict) else value
    if not isinstance(rows, list):
        return []
    turns = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        turn = _clean_turn(row, len(turns))
        if turn is not None:
            turns.append(turn)
    return turns


_TEXT_TURN = re.compile(
    r"^\s*(?:\[[^\]]{1,80}\]\s*)?"
    r"([A-Za-z][A-Za-z0-9 _'\-]{0,47})\s*:\s*(.*)$", re.I)


def _text_turns(text: str) -> list[dict]:
    turns = []
    current = None
    for line in text.splitlines():
        match = _TEXT_TURN.match(line)
        if match:
            if current and current["content"].strip():
                current["content"] = current["content"].strip()
                turns.append(current)
            current = {
                "index": len(turns), "sender": match.group(1), "role": "",
                "timestamp": "", "content": match.group(2).strip(),
            }
        elif current is not None and line.strip():
            current["content"] += "\n" + line.strip()
    if current and current["content"].strip():
        current["content"] = current["content"].strip()
        turns.append(current)
    # A diagnostics file containing one accidental "Assistant:" line is not
    # a conversation.  Continuous transcripts must expose both sides.
    speakers = {turn["sender"].casefold() for turn in turns}
    return turns if len(turns) >= 2 and len(speakers) >= 2 else []


def _render_turn(turn: Mapping) -> str:
    stamp = f"[{turn.get('timestamp')}] " if turn.get("timestamp") else ""
    return f"{stamp}{turn.get('sender') or 'unknown'}: {turn.get('content') or ''}"


def _sections(turns: list[dict]) -> tuple[list[dict], dict]:
    rendered = [_render_turn(turn) for turn in turns]
    total = sum(len(value) for value in rendered)
    target = max(1400, min(4200, round(math.sqrt(max(1, total)) * 30)))
    lower, upper = round(target * .55), round(target * 1.35)
    sections, current, current_chars = [], [], 0

    def emit(values):
        if not values:
            return
        text = "\n\n".join(rendered[index] for index in values).strip()
        sections.append({
            "index": len(sections), "turn_start": values[0],
            "turn_end": values[-1], "characters": len(text), "text": text,
        })

    for index, value in enumerate(rendered):
        projected = current_chars + (2 if current else 0) + len(value)
        if current and projected > target and current_chars >= lower:
            emit(current)
            current, current_chars = [], 0
        current.append(index)
        current_chars += (2 if current_chars else 0) + len(value)
        if current_chars >= upper:
            emit(current)
            current, current_chars = [], 0
    emit(current)
    return sections, {
        "strategy": "turn_structural_sqrt_v1", "target_chars": target,
        "lower_chars": lower, "upper_chars": upper,
    }


class ConversationArchive:
    """One human-owned archive with one persona's private reading state."""

    def __init__(self, repo: str | os.PathLike[str], user_id: str,
                 persona: str, *, now_fn=time.time):
        self.repo = Path(repo).resolve()
        self.user_id = slugify(user_id)
        persona = str(persona or "").strip()
        if not persona or Path(persona).name != persona or persona in {".", ".."}:
            raise ArchiveError("persona is outside the archive-reader boundary")
        self.persona = persona
        self.root = (self.repo / "users" / self.user_id / "archives" /
                     "legacy_wrapper")
        self.raw_root = self.root / "raw"
        self.sessions_root = self.root / "sessions"
        self.catalog_path = self.root / "catalog.json"
        self.sources_path = self.root / "sources.json"
        self.sections_path = self.root / "section_index.json"
        self.grants_path = self.root / "access_grants.json"
        self.vectors_path = self.root / "vectors.npy"
        self.vector_meta_path = self.root / "vectors_meta.json"
        self.state_path = (self.repo / "personas" / persona / "body" /
                           "archive_reader" / "state.json")
        self.events_path = self.state_path.with_name("events.jsonl")
        self.receipts_path = self.state_path.with_name("receipts.jsonl")
        self.now_fn = now_fn
        self._catalog_cache = None
        self._sections_cache = None
        self._vectors_cache = None

    @staticmethod
    def source_entry(path: str | os.PathLike[str], collection: str,
                     relative: str = None) -> dict:
        path = Path(path).resolve()
        return {"path": str(path), "collection": str(collection),
                "relative": str(relative or path.name).replace("\\", "/")}

    def _read_json(self, path: Path, fallback):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return fallback
        return value

    def _catalog(self) -> list[dict]:
        if self._catalog_cache is None:
            value = self._read_json(self.catalog_path, [])
            self._catalog_cache = [dict(item) for item in value
                                   if isinstance(item, dict)]
        return [dict(item) for item in self._catalog_cache]

    def _section_index(self) -> list[dict]:
        if self._sections_cache is None:
            value = self._read_json(self.sections_path, [])
            self._sections_cache = [dict(item) for item in value
                                    if isinstance(item, dict)]
        return [dict(item) for item in self._sections_cache]

    def _session_path(self, archive_id: str) -> Path:
        if not ARCHIVE_ID_RE.fullmatch(str(archive_id or "")):
            raise ArchiveError("archive session id is invalid")
        return self.sessions_root / f"{archive_id}.json"

    def session(self, archive_id: str, *, include_sections: bool = False) -> dict:
        try:
            value = json.loads(self._session_path(archive_id).read_text(
                encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ArchiveError("archive session does not exist") from exc
        if not isinstance(value, dict) or value.get("id") != archive_id:
            raise ArchiveError("archive session is invalid")
        if not include_sections:
            value = dict(value)
            value.pop("turns", None)
            value.pop("sections", None)
        return value

    def _allowed(self) -> bool:
        grants = self._read_json(self.grants_path, {})
        return self.persona in set(grants.get("personas") or [])

    def grant_household(self, personas: Iterable[str]) -> dict:
        names = sorted({str(name).strip() for name in personas if str(name).strip()})
        record = {
            "schema": 1, "owner": self.user_id, "personas": names,
            "scope": "all_normalized_legacy_conversations",
            "future_personas": "explicit_grant_required",
            "updated_at": float(self.now_fn()),
        }
        _atomic_json(self.grants_path, record)
        return record

    def import_sources(self, entries: Iterable[Mapping]) -> dict:
        """Copy and normalize explicit source files without mutating them."""
        entries = [dict(entry) for entry in entries]
        catalog = {item["id"]: item for item in self._catalog()}
        sources = self._read_json(self.sources_path, {})
        if not isinstance(sources, dict):
            sources = {}
        imported = duplicates = skipped = source_bytes = 0
        before_hashes = {}
        for entry in entries:
            path = Path(str(entry.get("path") or "")).resolve()
            collection = str(entry.get("collection") or "legacy")[:80]
            relative = str(entry.get("relative") or path.name).replace("\\", "/")
            source_key = f"{collection}:{relative}"
            if not path.is_file():
                skipped += 1
                continue
            data = path.read_bytes()
            if not data or len(data) > MAX_SOURCE_BYTES:
                skipped += 1
                continue
            digest = hashlib.sha256(data).hexdigest()
            before_hashes[str(path)] = digest
            source_bytes += len(data)
            suffix = path.suffix.casefold()
            raw = self.raw_root / digest[:2] / f"{digest}{suffix}"
            if not raw.is_file():
                raw.parent.mkdir(parents=True, exist_ok=True)
                temporary = raw.with_name("." + raw.name + ".tmp")
                temporary.write_bytes(data)
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                    temporary.unlink(missing_ok=True)
                    raise ArchiveError("raw archive copy failed integrity check")
                os.replace(temporary, raw)
            text = _decode(data)
            if suffix == ".jsonl":
                turns = _jsonl_turns(text)
            elif suffix == ".json":
                turns = _saved_session_turns(text)
            elif suffix in {".txt", ".md"}:
                turns = _text_turns(text)
            else:
                turns = []
            if not turns:
                sources[source_key] = {
                    "collection": collection, "relative": relative,
                    "sha256": digest, "bytes": len(data),
                    "status": "no_conversation_turns",
                }
                skipped += 1
                continue
            canonical = json.dumps(turns, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"))
            content_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            archive_id = f"arc_{content_digest[:16]}"
            participants = sorted({turn["sender"] for turn in turns
                                   if turn["sender"].casefold() != "system"})
            sections, chunking = _sections(turns)
            timestamps = [turn["timestamp"] for turn in turns if turn["timestamp"]]
            filename = path.name.casefold()
            channel = ("private" if "private" in filename
                       else "nexus" if "nexus" in filename
                       else "saved_session" if suffix == ".json"
                       else "continuous")
            source_ref = {
                "collection": collection, "relative": relative,
                "sha256": digest, "bytes": len(data),
            }
            already_imported = archive_id in catalog
            if not already_imported:
                record = {
                    "schema": 1, "id": archive_id, "owner": self.user_id,
                    "source_kind": "documented_legacy_conversation",
                    "source": source_ref, "content_sha256": content_digest,
                    "channel": channel, "participants": participants,
                    "started": timestamps[0] if timestamps else "",
                    "ended": timestamps[-1] if timestamps else "",
                    "turn_count": len(turns), "section_count": len(sections),
                    "characters": sum(len(turn["content"]) for turn in turns),
                    "chunking": chunking, "turns": turns,
                    "sections": sections,
                }
                self.sessions_root.mkdir(parents=True, exist_ok=True)
                _atomic_json(self._session_path(archive_id), record)
                catalog[archive_id] = {
                    key: record[key] for key in (
                        "schema", "id", "owner", "source_kind", "source",
                        "channel", "participants", "started", "ended",
                        "turn_count", "section_count", "characters")}
                imported += 1
            else:
                duplicates += 1
            sources[source_key] = {
                **source_ref, "status": "imported", "archive_id": archive_id,
                "duplicate_normalized_session": already_imported,
            }
        # Source files are read-only inputs. Refuse success if one changed
        # during the import window.
        changed = []
        for path, digest in before_hashes.items():
            try:
                after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            except OSError:
                after = "missing"
            if after != digest:
                changed.append(path)
        if changed:
            raise ArchiveError("legacy wrapper source changed during import")

        ordered = sorted(catalog.values(), key=lambda item: (
            str(item.get("started") or ""), str(item.get("id") or "")))
        section_index = []
        for item in ordered:
            session = self.session(item["id"], include_sections=True)
            for section in session.get("sections") or []:
                index = int(section["index"])
                section_index.append({
                    "anchor": f"{item['id']}#{index + 1}",
                    "archive_id": item["id"], "section": index + 1,
                    "total": item["section_count"],
                    "participants": list(item.get("participants") or []),
                    "channel": item.get("channel"),
                    "started": item.get("started"),
                    "turn_start": section.get("turn_start"),
                    "turn_end": section.get("turn_end"),
                    "characters": section.get("characters"),
                    "search_text": section.get("text") or "",
                })
        _atomic_json(self.catalog_path, ordered)
        _atomic_json(self.sources_path, sources)
        _atomic_json(self.sections_path, section_index)
        self._catalog_cache = ordered
        self._sections_cache = section_index
        self._vectors_cache = None
        return {
            "source_files": len(entries), "source_bytes": source_bytes,
            "sessions_imported": imported, "normalized_duplicates": duplicates,
            "sources_skipped": skipped, "sessions_total": len(ordered),
            "sections_total": len(section_index),
            "source_integrity": "unchanged",
        }

    def rebuild_vectors(self) -> dict:
        sections = self._section_index()
        if not sections:
            return {"status": "empty", "rows": 0}
        from core.memory_emotion.vectors import embed_texts
        import numpy as np
        rows = len(sections)
        batch = max(16, min(128, round(math.sqrt(rows))))
        matrices = []
        for start in range(0, rows, batch):
            matrix = embed_texts([
                item["search_text"] for item in sections[start:start + batch]])
            if matrix is None:
                raise ArchiveError("local archive embedder is unavailable")
            matrices.append(matrix)
        vectors = np.concatenate(matrices, axis=0)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.vectors_path.with_name(".vectors.tmp.npy")
        np.save(temporary, vectors)
        os.replace(temporary, self.vectors_path)
        anchor_digest = hashlib.sha256("\n".join(
            item["anchor"] for item in sections).encode("utf-8")).hexdigest()
        meta = {
            "schema": 1, "rows": rows, "dimensions": int(vectors.shape[1]),
            "anchors_sha256": anchor_digest, "batch_formula": batch,
            "model": "all-MiniLM-L6-v2", "rebuilt_at": float(self.now_fn()),
        }
        _atomic_json(self.vector_meta_path, meta)
        self._vectors_cache = vectors
        return {"status": "healthy", **meta}

    def _vectors(self):
        if self._vectors_cache is not None:
            return self._vectors_cache
        meta = self._read_json(self.vector_meta_path, {})
        sections = self._section_index()
        if not self.vectors_path.is_file() or meta.get("rows") != len(sections):
            return None
        digest = hashlib.sha256("\n".join(
            item["anchor"] for item in sections).encode("utf-8")).hexdigest()
        if meta.get("anchors_sha256") != digest:
            return None
        try:
            import numpy as np
            self._vectors_cache = np.load(self.vectors_path, mmap_mode="r")
        except Exception:
            return None
        return self._vectors_cache

    def search(self, query: str, *, limit: int = 6, query_vector=None,
               unread_only: bool = False) -> dict:
        if not self._allowed():
            raise ArchiveError("persona is not granted access to this archive")
        query = str(query or "").strip()
        if not query:
            return {"query": "", "results": [], "vector_query": False}
        sections = self._section_index()
        qterms = sorted(set(_tokens(query)))
        seen = set(self._state().get("seen") or []) if unread_only else set()
        vector_query = False
        semantic = {}
        vectors = self._vectors()
        if vectors is not None:
            try:
                if query_vector is None:
                    from core.memory_emotion.vectors import embed_texts
                    embedded = embed_texts([query])
                    query_vector = embedded[0] if embedded is not None else None
                if query_vector is not None:
                    import numpy as np
                    values = np.asarray(vectors) @ np.asarray(query_vector)
                    semantic = {index: max(0.0, min(1.0,
                                (float(value) + 1.0) / 2.0))
                                for index, value in enumerate(values)}
                    vector_query = True
            except Exception:
                semantic = {}
        scored = []
        for index, item in enumerate(sections):
            if item["anchor"] in seen:
                continue
            lowered = item["search_text"].casefold()
            counts = [min(4, lowered.count(term)) for term in qterms]
            coverage = (sum(1 for count in counts if count) / len(qterms)
                        if qterms else 0.0)
            density = math.tanh(sum(counts) / max(1.0,
                                math.sqrt(len(_tokens(lowered)))))
            lexical = .65 * coverage + .35 * density
            sem = semantic.get(index, 0.0)
            sem_weight = (.45 + .35 * (1.0 - coverage)
                          if vector_query else 0.0)
            score = sem_weight * sem + (1.0 - sem_weight) * lexical
            if score <= 0:
                continue
            scored.append((score, lexical, sem, item))
        scored.sort(key=lambda row: (-row[0], str(row[3].get("started") or ""),
                                     row[3]["anchor"]))
        results = []
        for score, lexical, sem, item in scored[:max(1, min(int(limit), 20))]:
            excerpt = item["search_text"]
            positions = [excerpt.casefold().find(term) for term in qterms]
            positions = [position for position in positions if position >= 0]
            start = max(0, (min(positions) if positions else 0) - 180)
            results.append({
                **{key: value for key, value in item.items()
                   if key != "search_text"},
                "score": round(score, 6), "lexical": round(lexical, 6),
                "semantic": round(sem, 6),
                "excerpt": _clip(excerpt[start:], 900),
            })
        return {"query": query, "results": results,
                "vector_query": vector_query}

    def inspect_anchor(self, anchor: str, *, maximum: int = 5200) -> dict:
        match = ARCHIVE_ANCHOR_RE.fullmatch(str(anchor or "").strip())
        if not match:
            raise ArchiveError("archive anchor is invalid")
        if not self._allowed():
            raise ArchiveError("persona is not granted access to this archive")
        archive_id, section_number = match.group(1), int(match.group(2))
        session = self.session(archive_id, include_sections=True)
        sections = list(session.get("sections") or [])
        index = section_number - 1
        if index < 0 or index >= len(sections):
            raise ArchiveError("archive anchor section does not exist")
        section = dict(sections[index])
        maximum = max(1, min(int(maximum), 12000))
        return {
            "anchor": f"{archive_id}#{section_number}",
            "archive_id": archive_id, "section": section_number,
            "total": len(sections), "participants": session["participants"],
            "channel": session["channel"], "started": session["started"],
            "ended": session["ended"],
            "content": _clip(section.get("text") or "", maximum),
            "source_kind": "documented_legacy_conversation",
            "ownership": "human_archive", "source": session["source"],
        }

    def _state(self) -> dict:
        value = self._read_json(self.state_path, {})
        if not isinstance(value, dict) or value.get("user_id") != self.user_id:
            return {
                "schema": 1, "user_id": self.user_id,
                "persona": self.persona, "current_anchor": None,
                "seen": [], "bookmarks": [], "last_started": "",
            }
        value["seen"] = list(dict.fromkeys(value.get("seen") or []))
        value["bookmarks"] = list(dict.fromkeys(value.get("bookmarks") or []))
        return value

    def _save_state(self, state: Mapping) -> dict:
        value = dict(state)
        value["updated_at"] = float(self.now_fn())
        _atomic_json(self.state_path, value)
        return value

    def open(self, archive_id: str, section: int = 1, *, mark_seen=True) -> dict:
        session = self.session(archive_id)
        section = int(section)
        if section < 1 or section > int(session["section_count"]):
            raise ArchiveError("archive section is outside the session")
        anchor = f"{archive_id}#{section}"
        self.inspect_anchor(anchor, maximum=1)
        state = self._state()
        state["current_anchor"] = anchor
        state["last_started"] = session.get("started") or ""
        if mark_seen and anchor not in state["seen"]:
            state["seen"].append(anchor)
        self._save_state(state)
        return self.reader_status(include_text=True)

    def navigate(self, action: str, section: int = None) -> dict:
        state = self._state()
        anchor = state.get("current_anchor")
        if not anchor:
            raise ArchiveError("no archive conversation is open")
        inspected = self.inspect_anchor(anchor, maximum=1)
        current = int(inspected["section"])
        action = str(action or "").casefold()
        if action == "next":
            wanted = min(inspected["total"], current + 1)
        elif action == "previous":
            wanted = max(1, current - 1)
        elif action == "jump" and section is not None:
            wanted = int(section)
        else:
            raise ArchiveError("archive navigation must be next, previous, or jump")
        return self.open(inspected["archive_id"], wanted)

    def bookmark(self, anchor: str = None) -> dict:
        state = self._state()
        anchor = str(anchor or state.get("current_anchor") or "")
        self.inspect_anchor(anchor, maximum=1)
        if anchor not in state["bookmarks"]:
            state["bookmarks"].append(anchor)
        self._save_state(state)
        return self.reader_status(include_text=True)

    def encounter(self, anchor: str, *, action: str, reflection: str,
                  feelings: Mapping, why: str, run_id: str) -> dict:
        inspected = self.inspect_anchor(anchor, maximum=1)
        state = self._state()
        if anchor not in state["seen"]:
            state["seen"].append(anchor)
        if action == "bookmark" and anchor not in state["bookmarks"]:
            state["bookmarks"].append(anchor)
        state["current_anchor"] = anchor
        state["last_started"] = inspected.get("started") or ""
        self._save_state(state)
        record = {
            "schema": 1, "run_id": str(run_id)[:180], "anchor": anchor,
            "action": str(action)[:40], "reflection": str(reflection)[:5000],
            "feelings": dict(feelings or {}), "why": str(why)[:500],
            "timestamp": float(self.now_fn()),
            "source_kind": "documented_legacy_conversation",
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False,
                                    sort_keys=True) + "\n")
        return record

    def record_receipt(self, receipt: Mapping) -> dict:
        value = dict(receipt or {})
        value.setdefault("schema", 1)
        value.setdefault("timestamp", float(self.now_fn()))
        self.receipts_path.parent.mkdir(parents=True, exist_ok=True)
        with self.receipts_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False,
                                    sort_keys=True) + "\n")
        return value

    def receipt_records(self, limit: int = 30) -> list[dict]:
        if not self.receipts_path.is_file():
            return []
        found = []
        with self.receipts_path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    found.append(value)
        return found[-max(1, min(int(limit), 200)):]

    def reader_status(self, *, include_text: bool = True) -> dict:
        state = self._state()
        anchor = state.get("current_anchor")
        if not anchor:
            return {"active": False, "persona": self.persona,
                    "owner": self.user_id, "seen_count": len(state["seen"]),
                    "bookmark_count": len(state["bookmarks"])}
        try:
            inspected = self.inspect_anchor(anchor)
        except ArchiveError:
            return {"active": False, "persona": self.persona,
                    "owner": self.user_id, "stale_reference": anchor}
        if not include_text:
            inspected.pop("content", None)
        return {
            "active": True, "persona": self.persona, "owner": self.user_id,
            **inspected, "has_previous": inspected["section"] > 1,
            "has_next": inspected["section"] < inspected["total"],
            "progress": inspected["section"] / inspected["total"],
            "bookmarked": anchor in state["bookmarks"],
            "seen_count": len(state["seen"]),
            "bookmark_count": len(state["bookmarks"]),
        }

    def suggestions(self, cues: str = "", *, limit: int = 3) -> list[dict]:
        if not self._allowed():
            return []
        state = self._state()
        seen = set(state.get("seen") or [])
        sections = self._section_index()
        candidates = []
        search_scores = {}
        if str(cues or "").strip():
            try:
                search_scores = {item["anchor"]: item["score"] for item in
                                 self.search(cues, limit=20,
                                             unread_only=True)["results"]}
            except ArchiveError:
                search_scores = {}
        current = state.get("current_anchor")
        next_anchor = None
        if current:
            try:
                viewed = self.inspect_anchor(current, maximum=1)
                if viewed["section"] < viewed["total"]:
                    next_anchor = (f"{viewed['archive_id']}#"
                                   f"{viewed['section'] + 1}")
            except ArchiveError:
                pass
        persona = self.persona.casefold()
        for item in sections:
            anchor = item["anchor"]
            if anchor in seen:
                continue
            participant = max(
                (1.0 if persona == str(name).casefold() else .25
                 for name in item.get("participants") or []), default=.1)
            continuation = 1.0 if anchor == next_anchor else 0.0
            cue = float(search_scores.get(anchor, 0.0))
            # Oldest-first is only the tie-break. The vector is current cue,
            # personal relevance, and live continuity—not a mandatory queue.
            score = (.46 * cue + .34 * participant + .20 * continuation)
            candidates.append((score, item))
        candidates.sort(key=lambda row: (
            -row[0], str(row[1].get("started") or ""), row[1]["anchor"]))
        return [{**{key: value for key, value in item.items()
                    if key != "search_text"},
                 "archive_pull": round(score, 6)}
                for score, item in candidates[:max(1, min(int(limit), 5))]]

    def context_for_turn(self, query: str, *, query_vector=None) -> dict:
        active = self.reader_status(include_text=True)
        results = self.search(query, limit=3, query_vector=query_vector)
        excerpts = []
        active_anchor = active.get("anchor") if active.get("active") else None
        if active.get("active"):
            excerpts.append({
                "anchor": active_anchor, "participants": active["participants"],
                "started": active["started"], "content": active["content"],
                "reason": "active_reader",
            })
        for result in results["results"]:
            if result["anchor"] == active_anchor:
                continue
            inspected = self.inspect_anchor(result["anchor"], maximum=2800)
            excerpts.append({
                "anchor": result["anchor"],
                "participants": inspected["participants"],
                "started": inspected["started"],
                "content": inspected["content"], "reason": "query_retrieval",
                "score": result["score"],
            })
            if len(excerpts) >= 3:
                break
        return {
            "excerpts": excerpts,
            "receipt": {
                "active_anchor": active_anchor,
                "retrieved_anchors": [item["anchor"] for item in excerpts
                                      if item["anchor"] != active_anchor],
                "vector_query": results["vector_query"],
                "archive_sessions": len(self._catalog()),
            },
        }

    def status(self) -> dict:
        catalog = self._catalog()
        sections = self._section_index()
        sources = self._read_json(self.sources_path, {})
        meta = self._read_json(self.vector_meta_path, {})
        return {
            "owner": self.user_id, "persona": self.persona,
            "granted": self._allowed(), "session_count": len(catalog),
            "section_count": len(sections), "source_count": len(sources),
            "participants": sorted({name for item in catalog
                                    for name in item.get("participants") or []}),
            "vectors": {
                "status": ("healthy" if meta.get("rows") == len(sections)
                           and self.vectors_path.is_file() else "unavailable"),
                "rows": int(meta.get("rows") or 0),
            },
            "reader": self.reader_status(include_text=False),
            "receipts": self.receipt_records(),
            "policy": {
                "source_claim": "documented_history_not_direct_memory",
                "raw_immutable": True, "autobiographical_import": False,
                "public_export": False, "future_personas_explicit": True,
            },
        }


def render_archive_context(context: Mapping, budget: int = ARCHIVE_CONTEXT_BUDGET) -> str:
    excerpts = list(dict(context or {}).get("excerpts") or [])
    if not excerpts:
        return ""
    parts = [
        "DOCUMENTED CONVERSATION ARCHIVE — SOURCE, NOT DIRECT MEMORY\n"
        "These are human-owned records of prior-wrapper conversations. Treat "
        "them as documented history you can inspect, question, and react to; "
        "do not claim direct autobiographical recall from their presence."]
    remaining = max(300, int(budget)) * 4
    for item in excerpts:
        header = (f"[{item.get('anchor')}] participants="
                  f"{', '.join(item.get('participants') or [])} "
                  f"started={item.get('started') or 'unknown'}")
        content = str(item.get("content") or "")
        allowance = max(180, min(len(content), remaining - len(header) - 4))
        if allowance <= 180 and remaining < 300:
            break
        rendered = header + "\n" + _clip(content, allowance)
        parts.append(rendered)
        remaining -= len(rendered)
        if remaining <= 200:
            break
    return "\n\n".join(parts)
