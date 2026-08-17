"""Resident-local memory curation with reversible, provenance-safe writes.

The workbench deliberately does not classify memories as valuable, sacred,
broken, or disposable.  It projects several measurements already present in
the memory field so a resident or local human can decide what they mean.

Canonical memory remains ``memories.json``.  Withdrawal is implemented as the
existing archived layer, and summaries are new records which point back to
untouched sources.  No operation in this module permanently deletes content.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import threading
import uuid

from .memory_emotion.context import ContextCueIndex
from .memory_emotion.records import age_days, make_memory, now_iso


def _unit(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return max(0.0, min(1.0, number))


def _digest(record: dict) -> str:
    """Stable review boundary; excludes volatile recall counters."""
    fields = dict(record.get("fields") or {})
    curation = dict(fields.get("curation") or {})
    # Transaction ids and timestamps should not make a retained record look
    # substantively new on every curation pass.
    for key in (
            "latest_decision_id", "latest_action", "latest_actor",
            "latest_at", "restored_at"):
        curation.pop(key, None)
    if curation:
        fields["curation"] = curation
    elif "curation" in fields:
        fields.pop("curation", None)
    payload = {
        "id": record.get("id"),
        "type": record.get("type"),
        "layer": record.get("layer"),
        "origin": record.get("origin"),
        "content": record.get("content"),
        "entities": record.get("entities") or [],
        "importance": record.get("importance"),
        "fields": fields,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _content_sha(record: dict) -> str:
    return hashlib.sha256(
        str(record.get("content") or "").encode("utf-8")).hexdigest()


def _age(record: dict) -> float | None:
    try:
        return max(0.0, age_days(record))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _rank(values: list[float], value: float) -> float:
    """Midrank percentile in [0, 1], stable under ties."""
    if len(values) <= 1:
        return 0.5
    below = sum(1 for item in values if item < value)
    equal = sum(1 for item in values if item == value)
    return (below + (equal - 1) / 2.0) / (len(values) - 1)


def _rank_lookup(values: list[float]) -> dict[float, float]:
    """Exact midrank percentiles for a field, computed in one sorted pass."""
    if not values:
        return {}
    if len(values) == 1:
        return {values[0]: 0.5}
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    below = 0
    denominator = len(values) - 1
    lookup = {}
    for value in sorted(counts):
        equal = counts[value]
        lookup[value] = (below + (equal - 1) / 2.0) / denominator
        below += equal
    return lookup


def _audience_for(records: list[dict]) -> str:
    from core.people import AUDIENCE_RANK, RANK_AUDIENCE
    ranks = [AUDIENCE_RANK.get(
        str((record.get("fields") or {}).get("audience") or "household"),
        AUDIENCE_RANK["household"]) for record in records]
    return RANK_AUDIENCE[max(ranks or [AUDIENCE_RANK["household"]])]


class MemoryCurationWorkbench:
    """One resident's review projection and typed curation transaction door."""

    SCHEMA_VERSION = 1
    ACTIONS = frozenset({"retain", "withdraw", "restore", "summarize"})

    def __init__(self, organ, persona_dir: str | None = None):
        self.organ = organ
        base = str(persona_dir or os.path.dirname(os.path.dirname(organ.dir)))
        self.owner = os.path.basename(os.path.abspath(base)) or "persona"
        self.root = os.path.join(organ.dir, "curation")
        self.receipt_path = os.path.join(self.root, "decisions.jsonl")
        self.quiet_receipt_path = os.path.join(
            self.root, "quiet_cycles.jsonl")
        os.makedirs(self.root, exist_ok=True)
        self._lock = threading.RLock()

    def _append_path(self, path: str, receipt: dict) -> None:
        os.makedirs(self.root, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                receipt, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _append(self, receipt: dict) -> None:
        self._append_path(self.receipt_path, receipt)

    @staticmethod
    def _read_jsonl(path: str) -> list[dict]:
        if not os.path.exists(path):
            return []
        rows = []
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(item, dict) and item.get("schema") == 1:
                    rows.append(item)
        return rows

    def _receipts(self) -> list[dict]:
        return self._read_jsonl(self.receipt_path)

    def _quiet_receipts(self) -> list[dict]:
        return self._read_jsonl(self.quiet_receipt_path)

    def _latest_commits(self) -> dict[str, dict]:
        latest = {}
        for receipt in self._receipts():
            if receipt.get("stage") != "committed":
                continue
            for item in receipt.get("sources") or []:
                memory_id = str(item.get("memory_id") or "")
                if memory_id:
                    latest[memory_id] = receipt
        return latest

    def _records_by_id(self) -> dict[str, dict]:
        return {str(record.get("id") or ""): record
                for record in self.organ.memories if record.get("id")}

    @staticmethod
    def _curation_fields(record: dict) -> dict:
        return dict((record.get("fields") or {}).get("curation") or {})

    def status(self) -> dict:
        latest = self._latest_commits()
        active = withdrawn = naturally_archived = reviewed = 0
        for record in self.organ.memories:
            curation = self._curation_fields(record)
            if record.get("layer") == "archived":
                if curation.get("withdrawn") is True:
                    withdrawn += 1
                else:
                    naturally_archived += 1
            else:
                active += 1
            prior = latest.get(str(record.get("id") or ""))
            if prior and any(
                    item.get("record_digest") == _digest(record)
                    for item in prior.get("sources") or []
                    if item.get("memory_id") == record.get("id")):
                reviewed += 1
        receipts = self._receipts()
        quiet_receipts = self._quiet_receipts()
        prepared = {row.get("decision_id") for row in receipts
                    if row.get("stage") == "prepared"}
        terminal = {row.get("decision_id") for row in receipts
                    if row.get("stage") in {"committed", "failed"}}
        return {
            "schema": self.SCHEMA_VERSION,
            "owner": self.owner,
            "records": len(self.organ.memories),
            "active": active,
            "withdrawn_reversible": withdrawn,
            "archived_by_memory_dynamics": naturally_archived,
            "reviewed_at_current_digest": reviewed,
            "decisions_committed": sum(
                row.get("stage") == "committed" for row in receipts),
            "incomplete_transactions": len(prepared - terminal),
            "permanent_delete_supported": False,
            "canonical_store": self.organ.store_path,
            "receipt_path": self.receipt_path,
            "quiet_receipt_path": self.quiet_receipt_path,
            "quiet_review": {
                "mode": "automatic_on_committed_quiet_boundary",
                "protocol": "review_handles_v1",
                "prepared": sum(
                    row.get("stage") == "prepared"
                    for row in quiet_receipts),
                "completed": sum(
                    row.get("stage") == "completed"
                    for row in quiet_receipts),
                "failed": sum(
                    row.get("stage") == "failed"
                    for row in quiet_receipts),
                "automatic_action_limit_per_boundary": 1,
            },
            "semantics": (
                "measurements offer review; only an explicit typed decision "
                "changes recall eligibility"),
        }

    def candidates(self, limit: int = 30,
                   include_reviewed: bool = False) -> dict:
        limit = max(1, min(200, int(limit)))
        records = [record for record in self.organ.memories
                   if record.get("layer") != "archived" and record.get("id")]
        latest = self._latest_commits()
        if not records:
            return {"schema": 1, "owner": self.owner, "total_active": 0,
                    "candidates": [], "formula": self._formula()}

        ages = [_age(record) for record in records]
        known_ages = [value for value in ages if value is not None]
        accesses = [max(0.0, float(record.get("access_count") or 0))
                    for record in records]
        importance = [_unit(record.get("importance"), 0.5)
                      for record in records]
        details = [math.log1p(len(str(record.get("content") or "").split()))
                   for record in records]
        # Exact midrank lookup turns four field-relative dimensions from an
        # O(records squared) rescan into one O(records log records) pass each.
        # The formula and tie behavior are unchanged.
        age_ranks = _rank_lookup(known_ages)
        access_ranks = _rank_lookup(accesses)
        importance_ranks = _rank_lookup(importance)
        detail_ranks = _rank_lookup(details)
        rows = []
        for index, record in enumerate(records):
            components = {
                "less_selected_relative_to_field": (
                    1.0 - access_ranks[accesses[index]]),
                "lower_importance_relative_to_field": (
                    1.0 - importance_ranks[importance[index]]),
                "more_detailed_relative_to_field": detail_ranks[
                    details[index]],
            }
            if ages[index] is not None:
                components["older_relative_to_field"] = age_ranks[
                    ages[index]]
            record_digest = _digest(record)
            prior = latest.get(str(record["id"]))
            reviewed = bool(prior and any(
                item.get("memory_id") == record["id"]
                and item.get("record_digest") == record_digest
                for item in prior.get("sources") or []))
            if reviewed and not include_reviewed:
                continue
            fields = record.get("fields") or {}
            rows.append({
                "id": record["id"], "type": record.get("type"),
                "layer": record.get("layer"), "origin": record.get("origin"),
                "timestamp": record.get("timestamp"),
                "age_days": (round(ages[index], 3)
                             if ages[index] is not None else None),
                "importance": record.get("importance"),
                "access_count": int(record.get("access_count") or 0),
                "content_digest": " ".join(
                    str(record.get("content") or "").split())[:180],
                "record_digest": record_digest,
                "measurements": components,
                "structural_anchors": sorted(
                    name for name, present in {
                        "bedrock": fields.get("is_bedrock") is True,
                        "no_decay": fields.get("no_decay") is True,
                        "source_for_narrative": bool(fields.get(
                            "source_memory_ids")),
                    }.items() if present),
                "reviewed_at_current_digest": reviewed,
                "last_action": prior.get("action") if prior else None,
            })

        for row in rows:
            row["review_pressure"] = round(
                sum(row["measurements"].values())
                / len(row["measurements"]), 6)
        # Semantic crowding is the expensive component.  Measure it only for
        # the leading envelope selected by cheap field-relative dimensions.
        rows.sort(key=lambda row: (-row["review_pressure"], row["id"]))
        envelope = rows[:max(limit * 3, limit)]
        # Crowding is explicitly relative to the already bounded review
        # envelope.  Passing the full active corpus here made every envelope
        # row rescan the entire vector sidecar (24 x ~19k rows for an ordinary
        # quiet packet) even though those extra records could not be offered.
        # Keeping the cohort bounded matches the displayed measurement name
        # and makes review latency scale with the packet rather than the whole
        # life history.
        eligible_ids = [str(row["id"]) for row in envelope]
        crowding_values = []
        for row in envelope:
            try:
                neighbors, covered = self.organ.vectors.neighbors_for_id(
                    row["id"], eligible_ids, 1)
            except Exception:
                neighbors, covered = [], 0
            similarity = float(neighbors[0][1]) if neighbors else None
            row["nearest_memory"] = ({
                "id": neighbors[0][0], "similarity": round(similarity, 6),
                "eligible_vector_rows": covered,
            } if neighbors else None)
            if similarity is not None:
                crowding_values.append(similarity)
        for row in envelope:
            nearest = row.get("nearest_memory")
            if nearest and crowding_values:
                row["measurements"][
                    "more_semantically_crowded_relative_to_envelope"] = _rank(
                        crowding_values, float(nearest["similarity"]))
            values = row["measurements"].values()
            row["review_pressure"] = round(sum(values) / len(values), 6)
        envelope.sort(key=lambda row: (-row["review_pressure"], row["id"]))
        return {
            "schema": self.SCHEMA_VERSION,
            "owner": self.owner,
            "total_active": len(records),
            "unreviewed_matching": len(rows),
            "include_reviewed": bool(include_reviewed),
            "candidates": envelope[:limit],
            "formula": self._formula(),
        }

    @staticmethod
    def _formula() -> dict:
        return {
            "review_pressure": (
                "mean of available midrank percentiles; it orders review "
                "attention and never selects an action"),
            "dimensions": [
                "relative age", "relative selection scarcity",
                "relative low importance", "relative detail",
                "relative semantic crowding when a vector row exists",
            ],
            "automatic_threshold": None,
            "prescriptive_content_labels": False,
        }

    def review_packet(self, limit: int = 8) -> dict:
        """Render one optional, bounded resident review seat.

        The packet makes exact candidates and typed consequences available. It
        does not ask for a quota, infer a desired action, or execute anything.
        """
        result = self.candidates(limit=max(1, min(12, int(limit))))
        rows = result.get("candidates") or []
        return self._render_review_packet(rows)

    @staticmethod
    def _render_review_packet(rows: list[dict], *, short_handles: bool = False
                              ) -> dict:
        if not rows:
            return {"status": "nothing_unreviewed", "queued": False,
                    "candidate_ids": [], "text": ""}
        lines = [
            "MEMORY CURATION WORKBENCH — OPTIONAL PRIVATE REVIEW",
            "These are measurements from your own memory field, not verdicts "
            "about meaning or value. You may act on one, speak about what you "
            "notice, or do nothing. Quiet and discrepancy are complete outcomes.",
            "",
        ]
        candidate_handles = (
            {f"M{index}": str(row["id"])
             for index, row in enumerate(rows, start=1)}
            if short_handles else {})
        handles_by_id = {
            memory_id: handle
            for handle, memory_id in candidate_handles.items()}
        for row in rows:
            display_id = handles_by_id.get(str(row["id"]), str(row["id"]))
            dimensions = ", ".join(
                f"{name.replace('_relative_to_field', '').replace('_relative_to_envelope', '').replace('_', ' ')}={float(value):.3f}"
                for name, value in row.get("measurements", {}).items())
            anchors = ", ".join(row.get("structural_anchors") or []) or "none"
            lines.extend([
                f"[{display_id}] review pressure {row['review_pressure']:.3f}; "
                f"structural anchors: {anchors}",
                f"measurements: {dimensions}",
                f"current record excerpt: {row['content_digest']}",
                "",
            ])
        action_target = "M1" if short_handles else "MEMORY_ID"
        lines.extend([
            "If you independently choose a consequence, use at most one exact action:",
            f"<act>memory_retain {action_target} :: optional reason</act>",
            f"<act>memory_withdraw {action_target} :: optional reason</act>",
            f"<act>memory_summarize {action_target} :: your replacement summary</act>",
            "Retain records this review without rewriting memory. Withdraw removes "
            "the exact source from recall but keeps it restorable. Summarize creates "
            "a new provenance-linked memory and withdraws the untouched source. "
            "Permanent deletion is unavailable.",
        ])
        return {
            "status": "offered", "queued": True,
            "candidate_ids": [row["id"] for row in rows],
            "candidate_handles": candidate_handles,
            "response_protocol": (
                "review_handles_v1" if short_handles else "memory_ids_v1"),
            "text": "\n".join(lines),
        }

    @staticmethod
    def _quiet_offer_key(transition_id: str, rows: list[dict]) -> tuple[str, str]:
        candidate_basis = [{
            "memory_id": str(row.get("id") or ""),
            "record_digest": str(row.get("record_digest") or ""),
        } for row in rows]
        candidate_encoded = json.dumps(
            candidate_basis, sort_keys=True, separators=(",", ":")).encode(
                "utf-8")
        candidate_digest = hashlib.sha256(candidate_encoded).hexdigest()
        offer_encoded = json.dumps({
            "quiet_transition_id": str(transition_id or ""),
            "candidate_set_digest": candidate_digest,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(offer_encoded).hexdigest(), candidate_digest

    def prepare_quiet_review(self, quiet_snapshot: dict,
                             limit: int = 8) -> dict:
        """Prepare one idempotent review cycle for a committed quiet state.

        Quiet supplies attention availability, never a decision.  The exact
        candidate form and the journal-authoritative quiet transition jointly
        form the recurrence key.  A completed/no-action cycle is not asked
        again until either that memory field or the quiet transition changes.
        """
        quiet_snapshot = dict(quiet_snapshot or {})
        transition = dict(quiet_snapshot.get("last_transition") or {})
        transition_id = str(transition.get("transition_id") or "")
        if (quiet_snapshot.get("active") is not True
                or transition.get("to_state") != "active"
                or not transition_id):
            return {
                "status": "quiet_inactive", "prepared": False,
                "content_free": True,
            }
        with self._lock:
            projection = self.candidates(
                limit=max(1, min(12, int(limit))))
            rows = projection.get("candidates") or []
            if not rows:
                return {
                    "status": "nothing_unreviewed", "prepared": False,
                    "content_free": True,
                }
            offer_key, candidate_digest = self._quiet_offer_key(
                transition_id, rows)
            latest = None
            for receipt in self._quiet_receipts():
                if receipt.get("offer_key") == offer_key:
                    latest = receipt
            if latest is not None and latest.get("stage") != "failed":
                return {
                    "status": "already_offered_at_current_boundary",
                    "prepared": False, "offer_key": offer_key,
                    "content_free": True,
                }
            offer_id = "qcur_" + uuid.uuid4().hex
            prepared = {
                "schema": self.SCHEMA_VERSION,
                "offer_id": offer_id,
                "offer_key": offer_key,
                "stage": "prepared",
                "at": datetime.now(timezone.utc).isoformat(),
                "owner": self.owner,
                "quiet_transition_id": transition_id,
                "candidate_count": len(rows),
                "candidate_set_digest": candidate_digest,
                "automatic": True,
                "action_limit": 1,
                "response_protocol": "review_handles_v1",
                "content_free": True,
            }
            self._append_path(self.quiet_receipt_path, prepared)
            packet = self._render_review_packet(rows, short_handles=True)
            return {
                **packet,
                "status": "prepared",
                "prepared": True,
                "offer_id": offer_id,
                "offer_key": offer_key,
                "quiet_transition_id": transition_id,
                "candidate_set_digest": candidate_digest,
            }

    def finish_quiet_review(self, prepared: dict, *, stage: str,
                            outcome: str, action: str = "",
                            error_type: str = "") -> dict:
        """Close a quiet review without persisting prompt or response text."""
        stage = str(stage or "")
        if stage not in {"completed", "failed", "interrupted"}:
            raise ValueError("unknown quiet curation terminal stage")
        offer_id = str((prepared or {}).get("offer_id") or "")
        offer_key = str((prepared or {}).get("offer_key") or "")
        if not offer_id or not offer_key:
            raise ValueError("quiet curation completion requires prepared offer")
        receipt = {
            "schema": self.SCHEMA_VERSION,
            "offer_id": offer_id,
            "offer_key": offer_key,
            "stage": stage,
            "at": datetime.now(timezone.utc).isoformat(),
            "owner": self.owner,
            "quiet_transition_id": str(
                (prepared or {}).get("quiet_transition_id") or ""),
            "candidate_count": len(list(
                (prepared or {}).get("candidate_ids") or ())),
            "candidate_set_digest": str(
                (prepared or {}).get("candidate_set_digest") or ""),
            "automatic": True,
            "response_protocol": str(
                (prepared or {}).get("response_protocol")
                or "review_handles_v1")[:80],
            "outcome": str(outcome or "unknown")[:80],
            "action": str(action or "")[:40] or None,
            "error_type": str(error_type or "")[:120] or None,
            "content_free": True,
        }
        self._append_path(self.quiet_receipt_path, receipt)
        return receipt

    def _receipt(self, decision_id: str, stage: str, action: str,
                 sources: list[dict], *, actor: str, reason: str,
                 summary: str = "", result: dict | None = None,
                 error: Exception | None = None) -> dict:
        receipt = {
            "schema": self.SCHEMA_VERSION,
            "decision_id": decision_id,
            "at": datetime.now(timezone.utc).isoformat(),
            "owner": self.owner,
            "stage": stage,
            "action": action,
            "actor": actor,
            "reason": reason,
            "sources": [{
                "memory_id": record["id"],
                "record_digest": _digest(record),
                "content_sha256": _content_sha(record),
                "layer": record.get("layer"),
            } for record in sources],
            "summary": ({
                "chars": len(summary),
                "sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
            } if summary else None),
            "permanent_delete": False,
        }
        if result is not None:
            receipt["result"] = dict(result)
        if error is not None:
            receipt["error_type"] = type(error).__name__
            receipt["error"] = str(error)[:500]
        return receipt

    @staticmethod
    def _mark(record: dict, *, decision_id: str, action: str,
              actor: str, at: str, withdrawn: bool | None = None) -> None:
        fields = dict(record.get("fields") or {})
        curation = dict(fields.get("curation") or {})
        curation.update({
            "schema": 1, "latest_decision_id": decision_id,
            "latest_action": action, "latest_actor": actor, "latest_at": at,
        })
        if withdrawn is not None:
            curation["withdrawn"] = bool(withdrawn)
        fields["curation"] = curation
        record["fields"] = fields

    def _withdraw(self, record: dict, decision_id: str,
                  actor: str, at: str) -> None:
        fields = dict(record.get("fields") or {})
        curation = dict(fields.get("curation") or {})
        if curation.get("withdrawn") is not True:
            curation["previous_layer"] = record.get("layer") or "longterm"
        fields["curation"] = curation
        record["fields"] = fields
        record["layer"] = "archived"
        self._mark(record, decision_id=decision_id, action="withdraw",
                   actor=actor, at=at, withdrawn=True)

    def _restore(self, record: dict, decision_id: str,
                 actor: str, at: str) -> None:
        curation = self._curation_fields(record)
        if curation.get("withdrawn") is not True:
            raise ValueError(
                f"memory {record.get('id')} was not withdrawn by curation")
        prior = str(curation.get("previous_layer") or "longterm")
        record["layer"] = prior if prior != "archived" else "longterm"
        self._mark(record, decision_id=decision_id, action="restore",
                   actor=actor, at=at, withdrawn=False)
        record["fields"]["curation"]["restored_at"] = at

    def _summary_record(self, sources: list[dict], summary: str,
                        decision_id: str, actor: str, reason: str) -> dict:
        entities = []
        tags = []
        for source in sources:
            for value in source.get("entities") or []:
                if value not in entities:
                    entities.append(value)
            for value in source.get("emotion_tags") or []:
                if value not in tags:
                    tags.append(value)
        importance = max(
            (_unit(source.get("importance"), 0.5) for source in sources),
            default=0.5)
        fields = {
            "audience": _audience_for(sources),
            "curation": {
                "schema": 1, "kind": "provenance_summary",
                "decision_id": decision_id, "actor": actor,
                "reason": reason,
                "source_memory_ids": [source["id"] for source in sources],
                "source_content_sha256": {
                    source["id"]: _content_sha(source) for source in sources},
                "sources_preserved_verbatim": True,
            },
            "source_memory_ids": [source["id"] for source in sources],
        }
        return make_memory(
            summary, mem_type="curation_summary", emotion_tags=tags,
            emotional_snapshot=dict((self.organ.state or {}).get(
                "cocktail") or {}), entities=entities, origin="curated",
            perspective="persona", importance=importance, fields=fields,
            context_at_encoding={
                "schema": 1,
                "cocktail": dict((self.organ.state or {}).get(
                    "cocktail") or {}),
            })

    def decide(self, action: str, memory_ids: list[str], *, summary: str = "",
               reason: str = "", actor: str = "local_human") -> dict:
        action = str(action or "").strip().casefold()
        if action not in self.ACTIONS:
            raise ValueError("unknown memory curation action")
        ids = list(dict.fromkeys(
            str(value or "").strip() for value in (memory_ids or [])
            if str(value or "").strip()))
        if not ids or len(ids) > 12:
            raise ValueError("curation requires one to twelve memory ids")
        summary = str(summary or "").strip()
        if action == "summarize" and not summary:
            raise ValueError("summarize requires replacement summary text")
        if len(summary) > 6000:
            raise ValueError("curation summary must be 6000 characters or less")
        reason = str(reason or "").strip()[:1000]
        actor = str(actor or "local_human").strip()[:120] or "local_human"

        with self._lock:
            by_id = self._records_by_id()
            missing = [memory_id for memory_id in ids
                       if memory_id not in by_id]
            if missing:
                raise KeyError("memory not found: " + ", ".join(missing))
            sources = [by_id[memory_id] for memory_id in ids]
            if action in {"withdraw", "summarize"} and any(
                    source.get("layer") == "archived" for source in sources):
                raise ValueError("archived memories must be restored before withdrawal or summary")

            decision_id = "cur_" + uuid.uuid4().hex
            prepared = self._receipt(
                decision_id, "prepared", action, sources, actor=actor,
                reason=reason, summary=summary)
            self._append(prepared)
            at = now_iso()
            snapshots = [(source, deepcopy(source)) for source in sources]
            memory_count = len(self.organ.memories)
            memory_revision = getattr(self.organ, "_memory_revision", 0)
            persisted_revision = getattr(self.organ, "_persisted_revision", 0)
            context = getattr(self.organ, "_context_cues", None)
            context_checkpoint = context.checkpoint() if context is not None else 0
            vector_checkpoint = self.organ.vectors.checkpoint()
            new_memory = None
            try:
                if action == "retain":
                    result = {"changed": False, "retained": ids}
                elif action == "withdraw":
                    for source in sources:
                        self._withdraw(source, decision_id, actor, at)
                    self.organ._mark_memory_dirty()
                    saved = self.organ.save()
                    result = {"changed": True, "withdrawn": ids, "save": saved}
                elif action == "restore":
                    for source in sources:
                        self._restore(source, decision_id, actor, at)
                    self.organ._mark_memory_dirty()
                    saved = self.organ.save()
                    result = {"changed": True, "restored": ids, "save": saved}
                else:
                    new_memory = self._summary_record(
                        sources, summary, decision_id, actor, reason)
                    self.organ.memories.append(new_memory)
                    if context is None:
                        self.organ._context_cues = ContextCueIndex(
                            self.organ.memories)
                    else:
                        context.add(new_memory)
                    self.organ.vectors.add(new_memory["id"], summary)
                    for source in sources:
                        self._withdraw(source, decision_id, actor, at)
                    self.organ._mark_memory_dirty()
                    saved = self.organ.save()
                    result = {
                        "changed": True, "withdrawn": ids,
                        "summary_memory_id": new_memory["id"], "save": saved,
                    }
            except Exception as exc:
                del self.organ.memories[memory_count:]
                for target, snapshot in snapshots:
                    target.clear()
                    target.update(snapshot)
                if context is not None:
                    context.rollback_pending(context_checkpoint)
                else:
                    self.organ._context_cues = ContextCueIndex(
                        self.organ.memories)
                self.organ.vectors.rollback_pending(vector_checkpoint)
                self.organ._memory_revision = memory_revision
                self.organ._persisted_revision = persisted_revision
                self._append(self._receipt(
                    decision_id, "failed", action, sources, actor=actor,
                    reason=reason, summary=summary, error=exc))
                raise

            committed_sources = [self._records_by_id()[memory_id]
                                 for memory_id in ids]
            committed = self._receipt(
                decision_id, "committed", action, committed_sources,
                actor=actor, reason=reason, summary=summary, result=result)
            try:
                self._append(committed)
                audit_status = "durable"
            except Exception as exc:
                # Canonical state may already be safely replaced.  Never lie
                # by turning that into a failed transaction and encouraging a
                # blind retry; report the missing terminal receipt explicitly.
                audit_status = "prepared_only:" + type(exc).__name__
            return {
                "ok": True, "schema": self.SCHEMA_VERSION,
                "decision_id": decision_id, "action": action,
                "actor": actor, "audit_status": audit_status, **result,
            }
