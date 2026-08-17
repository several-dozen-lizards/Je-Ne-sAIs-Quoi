"""Change-sensitive exposure for resident-owned reading possibilities.

This is a membrane, not a scheduler.  A runtime supplies a content-free
revision of the material it could presently offer.  Only a changed revision
may refresh candidates into the existing attention field; selection, quiet,
and action remain downstream decisions owned by that field and the resident.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Mapping


REVISION_RE = re.compile(r"[0-9a-f]{16,64}")
ALLOWED_ORGANS = frozenset({"document_reader", "research_desk"})
ALLOWED_CANDIDATE_SOURCES = frozenset({
    "document_read", "document_report",
    "research_cue", "research_interest", "research_discovery",
    "research_source",
    "research_synthesis", "research_report", "research_garden",
    "research_opportunity",
})


def _one_way(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


class InterestForagingField:
    """Persist inventory crossings without creating an activity cadence."""

    def __init__(self, state_path: str | os.PathLike[str],
                 receipt_path: str | os.PathLike[str], *, now_fn=time.time):
        self.state_path = Path(state_path)
        self.receipt_path = Path(receipt_path)
        self.now_fn = now_fn
        self._lock = threading.RLock()
        self._state = self._load()

    def _load(self) -> dict:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, TypeError, ValueError):
            value = {}
        organs = {}
        for organ, record in dict(value.get("organs") or {}).items():
            record = dict(record or {})
            revision = str(record.get("revision") or "")
            if organ not in ALLOWED_ORGANS or not REVISION_RE.fullmatch(revision):
                continue
            organs[organ] = {
                "revision": revision,
                "observed_at": _number(record.get("observed_at")),
                "candidate_count": max(0, int(_number(
                    record.get("candidate_count")))),
                "candidate_sources": sorted({
                    str(source)[:80] for source in
                    (record.get("candidate_sources") or ())
                    if str(source) in ALLOWED_CANDIDATE_SOURCES}),
                "refresh_ok": bool(record.get("refresh_ok", True)),
            }
        return {"schema": 1, "organs": organs}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        rendered = json.dumps(self._state, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.state_path)

    def _receipt(self, value: Mapping[str, Any]) -> None:
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.receipt_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"schema": 1, **dict(value)}, ensure_ascii=False,
                sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def observe(self, organ: str, runtime, field, *, now: float | None = None,
                reason: str = "inventory_observed") -> dict:
        """Refresh once when an organ's own durable/cue revision changes.

        Failed refreshes are recorded as observations and do not become a
        timer-driven retry storm.  A later source revision can try again.
        """
        organ = str(organ or "").strip()
        if organ not in ALLOWED_ORGANS:
            raise ValueError("interest foraging organ is not admitted")
        now = float(self.now_fn() if now is None else now)
        revision = str(runtime.foraging_revision() or "").strip().casefold()
        if not REVISION_RE.fullmatch(revision):
            raise ValueError("interest foraging revision is not content-free")
        reason = re.sub(r"[^a-z0-9_]+", "_", str(reason).casefold()).strip("_")
        reason = reason[:80] or "inventory_observed"
        with self._lock:
            prior = dict(self._state["organs"].get(organ) or {})
            if prior.get("revision") == revision:
                return {
                    "changed": False, "organ": organ, "revision": revision,
                    "candidate_count": prior.get("candidate_count", 0),
                    "candidate_sources": list(prior.get("candidate_sources") or ()),
                    "refresh_ok": bool(prior.get("refresh_ok", True)),
                }
            offered = []
            error_type = None
            try:
                offered = list(runtime.refresh_pending(field, now=now) or ())
            except Exception as exc:  # the membrane must not kill circulation
                error_type = type(exc).__name__
            sources = sorted({
                str(item.get("source") or "")[:80]
                for item in offered if isinstance(item, Mapping)
                and str(item.get("source") or "")
                in ALLOWED_CANDIDATE_SOURCES})
            key_digests = sorted({
                _one_way(item.get("key")) for item in offered
                if isinstance(item, Mapping) and item.get("key")})
            record = {
                "revision": revision, "observed_at": now,
                "candidate_count": len(offered),
                "candidate_sources": sources,
                "refresh_ok": error_type is None,
            }
            self._state["organs"][organ] = record
            self._receipt({
                "kind": ("foraging_inventory_changed" if error_type is None
                         else "foraging_refresh_failed"),
                "organ": organ, "reason": reason,
                "prior_revision": prior.get("revision"),
                "revision": revision, "observed_at": now,
                "candidate_count": len(offered),
                "candidate_sources": sources,
                "candidate_key_digests": key_digests,
                **({"error_type": error_type} if error_type else {}),
            })
            self._save()
            return {"changed": True, "organ": organ, **record,
                    "candidate_key_digests": key_digests,
                    **({"error_type": error_type} if error_type else {})}

    def status(self) -> dict:
        with self._lock:
            return {
                "schema": 1,
                "policy": {
                    "trigger": "source_revision_crossing",
                    "selection": "shared_attention_field",
                    "model_call_on_exposure": False,
                    "external_effects_on_exposure": False,
                    "quiet_is_valid": True,
                },
                "organs": json.loads(json.dumps(self._state["organs"])),
            }
