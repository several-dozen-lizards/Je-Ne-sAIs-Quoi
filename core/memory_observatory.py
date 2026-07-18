"""Read-only memory-store projections for the existing cockpit Observatory.

This module never imports the memory organ and never mutates the store.  The
store index is rebuilt only when the memories.json stat signature changes.
Sensory provenance logs are joined lazily for one requested record.
"""
from datetime import datetime, timezone
import hashlib
import json
import os


def _time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _signature(path):
    try:
        stat = os.stat(path)
        return stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return None


def _source(record):
    fields = record.get("fields") or {}
    sensory = fields.get("sensory_source")
    if sensory:
        return str(sensory), "fields.sensory_source"
    channel, speaker = fields.get("channel"), fields.get("speaker")
    if channel or speaker:
        parts = [str(value) for value in (channel, speaker) if value]
        return " / ".join(parts), "fields.channel + fields.speaker"
    migration = record.get("migration") or fields.get("migration")
    legacy = fields.get("v1")
    if migration or legacy:
        value = migration or legacy
        label = value.get("store") if isinstance(value, dict) else value
        return "migration" + (f" / {label}" if label else ""), (
            "record/fields migration metadata")
    origin = record.get("origin")
    return (str(origin) if origin else "unknown"), "record.origin fallback"


def _digest(value, limit=180):
    return " ".join(str(value or "").split())[:limit]


def _mentions(value, needle):
    if isinstance(value, dict):
        return any(_mentions(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(_mentions(item, needle) for item in value)
    return str(value) == str(needle)


def _event_refs(value, refs=None, parent=None):
    refs = set() if refs is None else refs
    if isinstance(value, dict):
        for key, item in value.items():
            _event_refs(item, refs, key)
    elif isinstance(value, list):
        for item in value:
            _event_refs(item, refs, parent)
    elif parent in {"event_id", "event_ids", "raw_offering_ref", "receipts"}:
        if value:
            refs.add(str(value))
    return refs


def _candidate_event_refs(record, candidate_key):
    """Collect only receipts attached to this candidate, not its neighbors."""
    refs = set()

    def visit(value):
        if isinstance(value, dict):
            if str(value.get("key") or "") == str(candidate_key):
                _event_refs(value, refs)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(record)
    candidate = record.get("candidate") or {}
    if (str(candidate.get("key") or "") == str(candidate_key)
            or str(record.get("surviving_key") or "") == str(candidate_key)):
        raw_ref = record.get("raw_offering_ref")
        if raw_ref:
            refs.add(str(raw_ref))
    return refs


class MemoryObservatory:
    """Cached store index plus lazy, honest provenance joins."""

    def __init__(self, memory_path, salience_path, perception_path):
        self.memory_path = str(memory_path)
        self.salience_path = str(salience_path)
        self.perception_path = str(perception_path)
        self._store_signature = None
        self._rows = []
        self._records = {}
        self._provenance_cache = {}

    def _refresh(self):
        signature = _signature(self.memory_path)
        if signature == self._store_signature:
            return
        with open(self.memory_path, encoding="utf-8") as handle:
            records = json.load(handle)
        now = datetime.now(timezone.utc)
        rows, by_id = [], {}
        for record in records:
            mem_id = str(record.get("id") or "")
            if not mem_id:
                continue
            timestamp = _time(record.get("timestamp"))
            age_days = ((now - timestamp).total_seconds() / 86400.0
                        if timestamp else None)
            source, source_rule = _source(record)
            entities = [str(value) for value in (record.get("entities") or [])]
            row = {
                "id": mem_id, "type": record.get("type"),
                "layer": record.get("layer"), "origin": record.get("origin"),
                "source": source, "source_rule": source_rule,
                "entities": entities, "entities_empty": not entities,
                "timestamp": record.get("timestamp"), "age_days": age_days,
                "importance": record.get("importance"),
                "access_count": int(record.get("access_count") or 0),
                "last_access": record.get("last_access"),
                "content_digest": _digest(record.get("content")),
                "access_history_note": "history begins at instrumentation",
            }
            rows.append(row)
            by_id[mem_id] = record
        rows.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
        self._rows, self._records = rows, by_id
        self._store_signature = signature

    def search(self, query="", layer="", origin="", memory_type="",
               source="", entity="", entities_state="all",
               min_age_days=None, max_age_days=None, min_importance=None,
               max_importance=None, access_state="all", min_access=None,
               max_access=None, page=1, per_page=50):
        self._refresh()
        query = str(query or "").casefold().strip()
        source = str(source or "").casefold().strip()
        entity = str(entity or "").casefold().strip()
        matches = []
        for row in self._rows:
            record = self._records[row["id"]]
            haystack = " ".join((row["id"], row["content_digest"],
                                  " ".join(row["entities"]))).casefold()
            if query and query not in haystack:
                continue
            if layer and row["layer"] != layer:
                continue
            if origin and row["origin"] != origin:
                continue
            if memory_type and row["type"] != memory_type:
                continue
            if source and source not in row["source"].casefold():
                continue
            if entity and not any(entity in item.casefold()
                                  for item in row["entities"]):
                continue
            if entities_state == "empty" and not row["entities_empty"]:
                continue
            if entities_state == "present" and row["entities_empty"]:
                continue
            age = row["age_days"]
            if min_age_days is not None and (age is None or age < min_age_days):
                continue
            if max_age_days is not None and (age is None or age > max_age_days):
                continue
            importance = record.get("importance")
            if min_importance is not None and (
                    importance is None or float(importance) < min_importance):
                continue
            if max_importance is not None and (
                    importance is None or float(importance) > max_importance):
                continue
            count = row["access_count"]
            if access_state == "never" and count != 0:
                continue
            if access_state == "selected" and count == 0:
                continue
            if min_access is not None and count < min_access:
                continue
            if max_access is not None and count > max_access:
                continue
            matches.append(row)
        page, per_page = max(1, int(page)), max(1, min(200, int(per_page)))
        start = (page - 1) * per_page
        facets = {
            "layers": sorted({str(row["layer"]) for row in self._rows
                              if row["layer"] is not None}),
            "origins": sorted({str(row["origin"]) for row in self._rows
                               if row["origin"] is not None}),
            "types": sorted({str(row["type"]) for row in self._rows
                             if row["type"] is not None}),
        }
        return {"total": len(matches), "page": page, "per_page": per_page,
                "pages": ((len(matches) + per_page - 1) // per_page),
                "records": matches[start:start + per_page], "facets": facets,
                "cache": {"store_signature": self._store_signature,
                          "strategy": "stat-keyed in-memory index"}}

    def _read_matching_salience(self, candidate_key):
        records = []
        try:
            with open(self.salience_path, encoding="utf-8") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if _mentions(record, candidate_key):
                        records.append(record)
        except FileNotFoundError:
            pass
        return records

    def _read_perception(self, event_ids):
        wanted, records = set(event_ids), []
        if not wanted:
            return records
        try:
            with open(self.perception_path, encoding="utf-8") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if str(record.get("event_id") or "") in wanted:
                        records.append(record)
        except FileNotFoundError:
            pass
        return records

    def _narrative_provenance(self, record):
        """Resolve canonical narrative sources without copying their prose."""
        fields = record.get("fields") or {}
        source_ids = [str(value) for value in
                      fields.get("source_memory_ids", [])]
        projections, gaps = [], []
        for source_id in source_ids:
            source = self._records.get(source_id)
            if source is None:
                gaps.append("source memory missing: " + source_id)
                continue
            source_fields = source.get("fields") or {}
            content = str(source.get("content") or "")
            projections.append({
                "id": source_id,
                "type": source.get("type"),
                "timestamp": source.get("timestamp"),
                "origin": source.get("origin"),
                "audience": source_fields.get("audience", "household"),
                "content_sha256": hashlib.sha256(
                    content.encode("utf-8")).hexdigest(),
            })
        if not source_ids:
            gaps.append("narrative has no source_memory_ids")
        return {
            "cluster_seed_id": fields.get("cluster_seed_id"),
            "cluster_signature": fields.get("cluster_signature"),
            "candidate_memory_count": len(
                fields.get("candidate_memory_ids", [])),
            "source_memory_ids": source_ids,
            "source_memories": projections,
            "gaps": gaps,
            "join_rule": (
                "narrative.fields.source_memory_ids -> memories.json id; "
                "missing IDs remain explicit gaps"),
        }

    def drilldown(self, memory_id):
        self._refresh()
        record = self._records.get(str(memory_id))
        if record is None:
            return None
        row = next(item for item in self._rows if item["id"] == str(memory_id))
        fields = record.get("fields") or {}
        if record.get("type") == "narrative":
            provenance = self._narrative_provenance(record)
            return {"projection": row, "payload": record,
                    "source_projection": {"value": row["source"],
                                          "rule": row["source_rule"]},
                    "access_history": {
                        "times_selected_by_recall": row["access_count"],
                        "last_access": row["last_access"],
                        "note": "history begins at instrumentation"},
                    "provenance": provenance}
        candidate_key = fields.get("candidate_key")
        provenance = {
            "candidate_key": candidate_key,
            "salience_lifecycle": [], "perception_event_ids": [],
            "perception_events": [], "gaps": [],
            "join_rule": "memory.fields.candidate_key -> salience lifecycle -> perception event IDs -> perception.jsonl",
        }
        if not candidate_key:
            provenance["gaps"].append(
                "memory has no candidate_key; join is not available for this record")
        else:
            cache_key = (str(candidate_key), _signature(self.salience_path),
                         _signature(self.perception_path))
            cached = self._provenance_cache.get(cache_key)
            if cached is None:
                lifecycle = self._read_matching_salience(candidate_key)
                event_ids = sorted(set().union(*(
                    _candidate_event_refs(item, candidate_key)
                    for item in lifecycle)) if lifecycle else set())
                events = self._read_perception(event_ids)
                gaps = []
                if not lifecycle:
                    gaps.append("candidate lifecycle missing; it may predate instrumentation or have been carried across a restart")
                if lifecycle and not event_ids:
                    gaps.append("lifecycle found but contains no perception event IDs")
                found = {str(item.get("event_id")) for item in events}
                missing = [item for item in event_ids if item not in found]
                if missing:
                    gaps.append("perception.jsonl has no event for: " + ", ".join(missing))
                cached = {"candidate_key": candidate_key,
                          "salience_lifecycle": lifecycle,
                          "perception_event_ids": event_ids,
                          "perception_events": events, "gaps": gaps,
                          "join_rule": provenance["join_rule"]}
                self._provenance_cache = {cache_key: cached}
            provenance = cached
        return {"projection": row, "payload": record,
                "source_projection": {"value": row["source"],
                                      "rule": row["source_rule"]},
                "access_history": {
                    "times_selected_by_recall": row["access_count"],
                    "last_access": row["last_access"],
                    "note": "history begins at instrumentation"},
                "provenance": provenance}
