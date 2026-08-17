"""Persona-private, append-only continuity of intention.

The loom records possibilities, not assignments.  A bounded cue may be
human-offered or may reference a private thought the persona actually had.
Only a later shared-field win can form an intention.  Every change appends a
new record; nothing here starts a project, calls a tool, speaks, publishes,
messages, overwrites, deletes, or grants authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


MAX_LABEL_CHARS = 240
MAX_CUE_CHARS = 6000
MAX_TITLE_CHARS = 180
MAX_STATEMENT_CHARS = 1400
MAX_BASIS_CHARS = 700
MAX_READ_CHARS = 6000
CUE_OWNERSHIPS = frozenset({
    "human_offered", "persona_private", "persona_chosen_conversation"})
TERMINAL_STATES = frozenset({"satisfied", "released"})
RELATION_MOVEMENTS = frozenset({"coexist", "differentiate", "braid"})
CONTINUITY_FEATURES = (
    "novelty", "affect_change", "body_intensity", "relationship",
    "unresolved",
)
CUE_RE = re.compile(r"^cue_[0-9a-f]{16}$")
INTENTION_RE = re.compile(r"^intention_[0-9a-f]{16}$")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":"))
    return _sha(rendered)[:16]


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
    return (value or "possibility")[:48]


def _uncertainty(low: Any, high: Any) -> list[float]:
    try:
        low, high = float(low), float(high)
    except (TypeError, ValueError) as exc:
        raise ValueError("intention uncertainty must be a numeric range") from exc
    if not math.isfinite(low) or not math.isfinite(high) \
            or not 0.0 <= low <= high <= 1.0:
        raise ValueError(
            "intention uncertainty must satisfy 0 <= low <= high <= 1")
    return [round(low, 4), round(high, 4)]


def _continuity(value: Mapping[str, Any] | None) -> dict[str, float]:
    """Validate observed field inputs without inventing missing intensity."""
    value = dict(value or {})
    result = {}
    for name in CONTINUITY_FEATURES:
        try:
            number = float(value.get(name, 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"intention continuity {name} must be numeric") from exc
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError(
                f"intention continuity {name} must be between 0 and 1")
        result[name] = round(number, 6)
    return result


def _tokens(*values: Any) -> set[str]:
    return {
        token for value in values
        for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if token
    }


def _interval_overlap(left: list[Any], right: list[Any]) -> float:
    try:
        a0, a1 = float(left[0]), float(left[1])
        b0, b1 = float(right[0]), float(right[1])
    except (IndexError, TypeError, ValueError):
        return 0.0
    union = max(a1, b1) - min(a0, b0)
    if union <= 0.0:
        return 1.0 if a0 == b0 else 0.0
    return max(0.0, min(a1, b1) - max(a0, b0)) / union


class IntentionLoom:
    """One persona's cue, intention, attention, and receipt ledger."""

    def __init__(self, persona_dir: str | os.PathLike[str], *, now_fn=time.time):
        self.persona_dir = Path(persona_dir).resolve()
        self.root = self.persona_dir / "body" / "intention_loom"
        self.cues = self.root / "cues"
        self.index = self.root / "index.jsonl"
        self.receipts = self.root / "receipts.jsonl"
        self.now_fn = now_fn
        self._lock = threading.RLock()

    def _ensure(self) -> None:
        self.cues.mkdir(parents=True, exist_ok=True)

    def _append(self, path: Path, record: Mapping[str, Any]) -> dict:
        self._ensure()
        value = dict(record)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                value, ensure_ascii=False, sort_keys=True) + "\n")
        return value

    @staticmethod
    def _read_records(path: Path, limit: int = 500) -> list[dict]:
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
        return [dict(value) for value in
                found[-max(1, min(int(limit), 4000)):]]

    def records(self, *, kind: str | None = None,
                limit: int = 200) -> list[dict]:
        with self._lock:
            values = self._read_records(self.index, limit=4000)
        if kind is not None:
            values = [value for value in values if value.get("kind") == kind]
        return values[-max(1, min(int(limit), 1000)):]

    def receipt_records(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return self._read_records(self.receipts, limit=limit)

    def _action_for_run(self, run_id: str) -> dict | None:
        return next((record for record in reversed(self.records(limit=1000))
                     if record.get("run_id") == str(run_id)), None)

    def _cue_path(self, ref: str) -> Path:
        pure = PurePosixPath(str(ref or "").replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts \
                or len(pure.parts) != 2 or pure.parts[0] != "cues":
            raise ValueError("intention cue reference escaped its boundary")
        path = (self.cues / pure.parts[1]).resolve()
        if path.parent != self.cues.resolve():
            raise ValueError("intention cue reference escaped its collection")
        return path

    def admit_cue(self, label: str, content: str, *,
                  ownership: str = "human_offered",
                  source_ref: str = "", source_digest: str = "",
                  continuity: Mapping[str, Any] | None = None) -> dict:
        """Admit a possibility without asserting that the persona wants it."""
        label = _bounded(
            label, name="intention cue label", maximum=MAX_LABEL_CHARS)
        content = _bounded(
            content, name="intention cue content", maximum=MAX_CUE_CHARS)
        ownership = str(ownership or "").strip()
        if ownership not in CUE_OWNERSHIPS:
            raise ValueError("intention cue ownership is invalid")
        source_ref = _bounded(
            source_ref, name="intention cue source reference", maximum=240,
            allow_empty=True)
        content_sha = _sha(content)
        source_digest = _bounded(
            source_digest or content_sha,
            name="intention cue source digest", maximum=80)
        continuity = _continuity(continuity)
        cue_key = {
            'ownership': ownership,
            'content_sha256': content_sha,
            'source_ref': source_ref,
            'source_digest': source_digest,
        }
        cue_id = f"cue_{_digest(cue_key)}"
        with self._lock:
            existing = next((record for record in self.records(
                kind="cue_admitted", limit=1000)
                if record.get("cue_id") == cue_id), None)
            if existing:
                return {**existing, "duplicate": True}
            self._ensure()
            path = self.cues / f"{cue_id}-{_slug(label)}.txt"
            with path.open("x", encoding="utf-8") as handle:
                handle.write(content)
            record = self._append(self.index, {
                "kind": "cue_admitted", "cue_id": cue_id,
                "label": label, "ref": f"cues/{path.name}",
                "chars": len(content), "sha256": content_sha,
                "source_ref": source_ref, "source_digest": source_digest,
                "continuity": continuity,
                "ownership": ownership,
                "created_at": float(self.now_fn()),
            })
            return {**record, "duplicate": False}

    def cue(self, cue_id: str, *, include_content: bool = False) -> dict:
        if not CUE_RE.fullmatch(str(cue_id or "")):
            raise ValueError("intention cue id is invalid")
        record = next((record for record in self.records(
            kind="cue_admitted", limit=1000)
            if record.get("cue_id") == cue_id), None)
        if record is None:
            raise ValueError("intention cue does not exist")
        value = dict(record)
        if include_content:
            text = self._cue_path(value["ref"]).read_text(encoding="utf-8")
            if _sha(text) != value.get("sha256"):
                raise ValueError("intention cue digest changed")
            value["content"] = text[:MAX_READ_CHARS]
            value["content_truncated"] = len(text) > MAX_READ_CHARS
        return value

    def pending_cues(self) -> list[dict]:
        resolved = {record.get("cue_id") for record in self.records(
            kind="cue_resolved", limit=1000)}
        return [record for record in self.records(
            kind="cue_admitted", limit=1000)
            if record.get("cue_id") not in resolved]

    def resolve_cue(self, cue_id: str, run_id: str, outcome: str, *,
                    intention_id: str | None = None) -> dict:
        self.cue(cue_id)
        run_id = _bounded(run_id, name="intention run id", maximum=180)
        outcome = _bounded(
            outcome, name="intention cue outcome", maximum=80)
        with self._lock:
            existing = next((record for record in self.records(
                kind="cue_resolved", limit=1000)
                if record.get("cue_id") == cue_id), None)
            if existing:
                return dict(existing)
            return self._append(self.index, {
                "kind": "cue_resolved", "cue_id": cue_id,
                "run_id": run_id, "outcome": outcome,
                "intention_id": intention_id,
                "ownership": "persona_private",
                "resolved_at": float(self.now_fn()),
            })

    def observe_cue(self, cue_id: str, run_id: str, *, basis: str = "") -> dict:
        """Record one quiet encounter while leaving the possibility alive."""
        self.cue(cue_id)
        run_id = _bounded(run_id, name="intention run id", maximum=180)
        basis = _bounded(
            basis, name="intention observation", maximum=MAX_BASIS_CHARS,
            allow_empty=True)
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this intention run already committed an action")
            return self._append(self.index, {
                "kind": "cue_observed", "cue_id": cue_id,
                "run_id": run_id, "basis": basis,
                "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            })

    def _views(self) -> dict[str, dict]:
        views: dict[str, dict] = {}
        for record in self.records(limit=4000):
            kind = record.get("kind")
            iid = record.get("intention_id")
            if kind == "intention_formed":
                views[iid] = {
                    "intention_id": iid, "state": "open",
                    "title": record.get("title"),
                    "statement": record.get("statement"),
                    "uncertainty": list(record.get("uncertainty") or []),
                    "basis": record.get("basis"),
                    "source": dict(record.get("source") or {}),
                    "continuity": _continuity(record.get("continuity")),
                    "revision_count": 1,
                    "created_at": record.get("created_at"),
                    "updated_at": record.get("created_at"),
                }
            elif iid in views and kind == "intention_reframed":
                views[iid].update({
                    "state": "open", "title": record.get("title"),
                    "statement": record.get("statement"),
                    "uncertainty": list(record.get("uncertainty") or []),
                    "basis": record.get("basis"),
                    "revision_count": int(record.get("revision") or
                                          views[iid]["revision_count"] + 1),
                    "updated_at": record.get("created_at"),
                })
            elif iid in views and kind == "intention_paused":
                views[iid].update({
                    "state": "paused", "basis": record.get("basis"),
                    "updated_at": record.get("created_at"),
                })
            elif iid in views and kind == "intention_resumed":
                views[iid].update({
                    "state": "open", "updated_at": record.get("created_at"),
                })
            elif iid in views and kind == "intention_resolved":
                views[iid].update({
                    "state": record.get("resolution"),
                    "basis": record.get("basis"),
                    "updated_at": record.get("created_at"),
                })
            elif iid in views and kind == "intention_observed":
                views[iid].update({
                    "last_observation": record.get("basis") or "",
                    "last_observed_at": record.get("created_at"),
                })
            elif iid in views and kind == "intention_related":
                views[iid].update({
                    "last_relationship": {
                        "movement": record.get("movement"),
                        "related_intention_id":
                            record.get("related_intention_id"),
                        "basis": record.get("basis") or "",
                        "vector": dict(record.get("vector") or {}),
                    },
                    "updated_at": record.get("created_at"),
                })
            elif iid in views and kind == "intention_braided":
                views[iid].update({
                    "state": "open", "title": record.get("title"),
                    "statement": record.get("statement"),
                    "uncertainty": list(record.get("uncertainty") or []),
                    "basis": record.get("basis"),
                    "revision_count": int(record.get("revision") or
                                          views[iid]["revision_count"] + 1),
                    "last_relationship": {
                        "movement": "braid",
                        "related_intention_id":
                            record.get("related_intention_id"),
                        "basis": record.get("basis") or "",
                        "vector": dict(record.get("vector") or {}),
                    },
                    "updated_at": record.get("created_at"),
                })
        return views

    def intentions(self, *, state: str | None = None) -> list[dict]:
        values = list(self._views().values())
        if state is not None:
            values = [value for value in values if value.get("state") == state]
        return sorted(values, key=lambda value: (
            -float(value.get("updated_at") or 0.0), value["intention_id"]))

    def intention(self, intention_id: str) -> dict:
        if not INTENTION_RE.fullmatch(str(intention_id or "")):
            raise ValueError("intention id is invalid")
        value = self._views().get(str(intention_id))
        if value is None:
            raise ValueError("intention does not exist")
        return dict(value)

    def relationship_vector(self, intention_id: str,
                            related_intention_id: str) -> dict[str, float]:
        """Describe overlap without deciding what the relationship means."""
        left = self.intention(intention_id)
        right = self.intention(related_intention_id)
        if intention_id == related_intention_id:
            raise ValueError("an intention cannot relate to itself")
        left_tokens = _tokens(left.get("title"), left.get("statement"))
        right_tokens = _tokens(right.get("title"), right.get("statement"))
        semantic = (len(left_tokens & right_tokens)
                    / len(left_tokens | right_tokens)
                    if left_tokens or right_tokens else 0.0)
        left_source, right_source = (
            dict(left.get("source") or {}), dict(right.get("source") or {}))
        provenance = 1.0 if (
            left_source.get("source_digest")
            and left_source.get("source_digest")
            == right_source.get("source_digest")) else 0.0
        left_continuity = _continuity(left.get("continuity"))
        right_continuity = _continuity(right.get("continuity"))
        evidence = sum(max(left_continuity[name],
                           right_continuity[name])
                       for name in CONTINUITY_FEATURES) / len(
                           CONTINUITY_FEATURES)
        alignment = 1.0 - sum(
            abs(left_continuity[name] - right_continuity[name])
            for name in CONTINUITY_FEATURES) / len(CONTINUITY_FEATURES)
        continuity = evidence * alignment
        uncertainty = _interval_overlap(
            list(left.get("uncertainty") or []),
            list(right.get("uncertainty") or []))
        stats = self.attention_stats()
        left_attention = stats.get(intention_id, {})
        right_attention = stats.get(related_intention_id, {})
        left_returns = int(left_attention.get("exposures", 0))
        right_returns = int(right_attention.get("exposures", 0))
        recurrence = (min(left_returns, right_returns)
                      / (1.0 + max(left_returns, right_returns)))
        components = {
            "semantic_overlap": semantic,
            "provenance_overlap": provenance,
            "continuity_overlap": continuity,
            "uncertainty_overlap": uncertainty,
            "recurrence_overlap": recurrence,
        }
        bounded_components = {
            key: max(0.0, min(1.0, value))
            for key, value in components.items()
        }
        # Every measured axis contributes equally; no single perfect overlap
        # (for example, matching uncertainty ranges) can declare sameness.
        affinity = sum(bounded_components.values()) / len(bounded_components)
        return {
            **{key: round(value, 6)
               for key, value in bounded_components.items()},
            "affinity": round(affinity, 6),
        }

    def relationships_for(self, intention_id: str) -> list[dict]:
        self.intention(intention_id)
        values = []
        for related in self.intentions():
            related_id = related["intention_id"]
            if related_id == intention_id \
                    or related.get("state") not in {"open", "paused"}:
                continue
            values.append({
                "related_intention_id": related_id,
                "title": related.get("title") or "",
                "state": related.get("state"),
                "vector": self.relationship_vector(
                    intention_id, related_id),
            })
        return sorted(values, key=lambda value: (
            -value["vector"]["affinity"],
            value["related_intention_id"]))

    def form_intention(self, run_id: str, cue_id: str, *, title: str,
                       statement: str, uncertainty_low: Any,
                       uncertainty_high: Any, basis: str) -> dict:
        run_id = _bounded(run_id, name="intention run id", maximum=180)
        cue = self.cue(cue_id)
        title = _bounded(
            title, name="intention title", maximum=MAX_TITLE_CHARS)
        statement = _bounded(
            statement, name="intention statement", maximum=MAX_STATEMENT_CHARS)
        basis = _bounded(
            basis, name="intention basis", maximum=MAX_BASIS_CHARS)
        uncertainty = _uncertainty(uncertainty_low, uncertainty_high)
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this intention run already committed an action")
            if cue_id not in {value.get("cue_id") for value in
                              self.pending_cues()}:
                raise ValueError("only a pending cue may form an intention")
            created_at = float(self.now_fn())
            intention_key = {
                'cue_id': cue_id, 'run_id': run_id,
                'created_at': created_at,
            }
            intention_id = f"intention_{_digest(intention_key)}"
            record = self._append(self.index, {
                "kind": "intention_formed", "intention_id": intention_id,
                "run_id": run_id, "title": title, "statement": statement,
                "uncertainty": uncertainty, "basis": basis,
                "source": {
                    "cue_id": cue_id, "source_ref": cue.get("source_ref"),
                    "source_digest": cue.get("source_digest"),
                    "ownership": cue.get("ownership"),
                },
                "continuity": _continuity(cue.get("continuity")),
                "ownership": "persona_private", "created_at": created_at,
            })
            self.resolve_cue(
                cue_id, run_id, "intention_formed", intention_id=intention_id)
            return record

    def reframe_intention(self, run_id: str, intention_id: str, *,
                          title: str, statement: str, uncertainty_low: Any,
                          uncertainty_high: Any, basis: str) -> dict:
        run_id = _bounded(run_id, name="intention run id", maximum=180)
        current = self.intention(intention_id)
        if current["state"] != "open":
            raise ValueError("only an open intention may be reframed")
        title = _bounded(
            title, name="intention title", maximum=MAX_TITLE_CHARS)
        statement = _bounded(
            statement, name="intention statement", maximum=MAX_STATEMENT_CHARS)
        basis = _bounded(
            basis, name="intention basis", maximum=MAX_BASIS_CHARS)
        uncertainty = _uncertainty(uncertainty_low, uncertainty_high)
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this intention run already committed an action")
            return self._append(self.index, {
                "kind": "intention_reframed", "intention_id": intention_id,
                "run_id": run_id, "revision": current["revision_count"] + 1,
                "title": title, "statement": statement,
                "uncertainty": uncertainty, "basis": basis,
                "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            })

    def relate_intention(self, run_id: str, intention_id: str, *,
                         related_intention_id: str, movement: str,
                         basis: str, title: str = "", statement: str = "",
                         uncertainty_low: Any = 0.0,
                         uncertainty_high: Any = 0.0) -> dict:
        """Append one relationship movement without merging either history."""
        movement = str(movement or "").strip().casefold()
        if movement not in RELATION_MOVEMENTS:
            raise ValueError("intention relationship movement is invalid")
        run_id = _bounded(run_id, name="intention run id", maximum=180)
        basis = _bounded(
            basis, name="intention relationship basis",
            maximum=MAX_BASIS_CHARS)
        current = self.intention(intention_id)
        related = self.intention(related_intention_id)
        if intention_id == related_intention_id:
            raise ValueError("an intention cannot relate to itself")
        if current["state"] not in {"open", "paused"} \
                or related["state"] not in {"open", "paused"}:
            raise ValueError("only continuing intentions may be related")
        vector = self.relationship_vector(
            intention_id, related_intention_id)
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this intention run already committed an action")
            common = {
                "intention_id": intention_id,
                "related_intention_id": related_intention_id,
                "run_id": run_id, "basis": basis, "vector": vector,
                "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            }
            if movement == "braid":
                title = _bounded(
                    title, name="intention title", maximum=MAX_TITLE_CHARS)
                statement = _bounded(
                    statement, name="intention statement",
                    maximum=MAX_STATEMENT_CHARS)
                return self._append(self.index, {
                    **common, "kind": "intention_braided",
                    "revision": current["revision_count"] + 1,
                    "title": title, "statement": statement,
                    "uncertainty": _uncertainty(
                        uncertainty_low, uncertainty_high),
                })
            return self._append(self.index, {
                **common, "kind": "intention_related",
                "movement": movement,
            })

    def pause_intention(self, run_id: str, intention_id: str, *,
                        basis: str) -> dict:
        return self._transition_open(
            run_id, intention_id, kind="intention_paused", basis=basis)

    def resolve_intention(self, run_id: str, intention_id: str, *,
                          resolution: str, basis: str) -> dict:
        resolution = str(resolution or "").casefold()
        if resolution not in TERMINAL_STATES:
            raise ValueError("intention resolution must be satisfied or released")
        return self._transition(
            run_id, intention_id, kind="intention_resolved",
            basis=basis, allowed_states={"open", "paused"},
            resolution=resolution)

    def _transition_open(self, run_id: str, intention_id: str, *,
                         kind: str, basis: str, **extra) -> dict:
        return self._transition(
            run_id, intention_id, kind=kind, basis=basis,
            allowed_states={"open"}, **extra)

    def _transition(self, run_id: str, intention_id: str, *,
                    kind: str, basis: str, allowed_states: set[str],
                    **extra) -> dict:
        run_id = _bounded(run_id, name="intention run id", maximum=180)
        basis = _bounded(
            basis, name="intention basis", maximum=MAX_BASIS_CHARS)
        current = self.intention(intention_id)
        if current["state"] not in allowed_states:
            raise ValueError(
                "the intention's current state does not admit this movement")
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this intention run already committed an action")
            return self._append(self.index, {
                "kind": kind, "intention_id": intention_id,
                "run_id": run_id, "basis": basis,
                "ownership": "persona_private",
                "created_at": float(self.now_fn()), **extra,
            })

    def observe_intention(self, run_id: str, intention_id: str, *,
                          basis: str = "") -> dict:
        """Append what was noticed without changing the intention's state."""
        current = self.intention(intention_id)
        if current["state"] not in {"open", "paused"}:
            raise ValueError("only a continuing intention may be observed")
        run_id = _bounded(run_id, name="intention run id", maximum=180)
        basis = _bounded(
            basis, name="intention observation", maximum=MAX_BASIS_CHARS,
            allow_empty=True)
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this intention run already committed an action")
            return self._append(self.index, {
                "kind": "intention_observed", "intention_id": intention_id,
                "run_id": run_id, "basis": basis,
                "state_observed": current["state"],
                "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            })

    def resume_intention(self, run_id: str, intention_id: str) -> dict:
        run_id = _bounded(run_id, name="intention run id", maximum=180)
        current = self.intention(intention_id)
        if current["state"] != "paused":
            raise ValueError("only a paused intention may resume")
        with self._lock:
            if self._action_for_run(run_id):
                raise ValueError("this intention run already committed an action")
            return self._append(self.index, {
                "kind": "intention_resumed", "intention_id": intention_id,
                "run_id": run_id, "ownership": "persona_private",
                "created_at": float(self.now_fn()),
            })

    def record_receipt(self, value: Mapping[str, Any]) -> dict:
        allowed = {
            "kind", "run_id", "candidate_key", "subject_kind", "subject_id",
            "outcome", "intention_id", "cue_id", "model", "provider",
            "locality", "model_requests", "provider_http_attempts",
            "input_tokens", "output_tokens", "total_tokens", "total_ms",
            "provider_ms", "prompt_ms", "gen_ms", "load_ms",
            "estimated_cost_usd", "readiness", "source_satiety",
            "loom_satiety", "observed_at", *CONTINUITY_FEATURES,
            "movement_count", "work_envelope",
            "failure_stage", "failure_code", "discrepancy",
        }
        record = {str(key): item for key, item in dict(value or {}).items()
                  if key in allowed and item is not None}
        if "discrepancy" in record:
            raw = dict(record.get("discrepancy") or {})
            record["discrepancy"] = {
                "schema": 1,
                "kind": "contract_discrepancy",
                "stage": str(raw.get("stage") or "")[:40],
                "code": str(raw.get("code") or "")[:80],
                "parser_stage": str(
                    raw.get("parser_stage") or raw.get("stage") or "")[:40],
                "relation_type": str(
                    raw.get("relation_type") or "movement_contract")[:80],
                "reason_code": str(
                    raw.get("reason_code") or raw.get("code") or "")[:80],
                "field": str(raw.get("field") or "")[:120],
                "constraint": str(raw.get("constraint") or "")[:400],
                "observed": str(raw.get("observed") or "")[:120],
                "state_changed": False,
                "mutation_applied": False,
                "committed_receipt": False,
                "outward_effect": False,
                "content_included": False,
            }
        record.setdefault("kind", "run")
        if "observed_at" not in record:
            record["observed_at"] = float(self.now_fn())
        with self._lock:
            return self._append(self.receipts, record)

    def record_attention(self, kind: str, *, candidate_key: str,
                         subject_kind: str, subject_id: str,
                         now: float) -> dict:
        if kind not in {"attention_exposed", "attention_selected"}:
            raise ValueError("intention attention receipt kind is invalid")
        return self.record_receipt({
            "kind": kind, "candidate_key": str(candidate_key or "")[:240],
            "subject_kind": str(subject_kind or "")[:40],
            "subject_id": str(subject_id or "")[:180],
            "observed_at": float(now),
        })

    def _receipt_summaries(self) -> tuple[dict[str, dict], dict[str, dict]]:
        """Stream exact content-free lifetime counters from the receipt ledger."""
        attention: dict[str, dict] = {}
        activity: dict[str, dict] = {}
        with self._lock:
            if not self.receipts.is_file():
                return attention, activity
            handle = self.receipts.open(encoding="utf-8")
            try:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(record, dict):
                        continue
                    kind = record.get("kind")
                    if kind in {"attention_exposed", "attention_selected"}:
                        subject_id = str(record.get("subject_id") or "")
                        if not subject_id:
                            continue
                        value = attention.setdefault(subject_id, {
                            "subject_kind": record.get("subject_kind"),
                            "exposures": 0, "selections": 0,
                            "last_exposed_at": None,
                            "last_selected_at": None,
                        })
                        stamp = float(record.get("observed_at") or 0.0)
                        if kind == "attention_exposed":
                            value["exposures"] += 1
                            value["last_exposed_at"] = stamp
                        else:
                            value["selections"] += 1
                            value["last_selected_at"] = stamp
                        continue
                    if kind != "run":
                        continue
                    subject_id = str(
                        record.get("intention_id")
                        or record.get("cue_id") or "")
                    if not subject_id:
                        continue
                    value = activity.setdefault(subject_id, {
                        "run_count": 0, "durable_movements": 0,
                        "quiet_encounters": 0,
                        "contract_discrepancies": 0,
                        "owner_refusals": 0,
                        "last_outcome": None, "last_run_at": None,
                        "last_failure_stage": None,
                        "last_failure_code": None,
                    })
                    outcome = str(record.get("outcome") or "")
                    value["run_count"] += 1
                    if outcome in {"quiet", "project_quiet"}:
                        value["quiet_encounters"] += 1
                    elif outcome == "contract_discrepancy":
                        value["contract_discrepancies"] += 1
                    elif outcome == "owner_rejected":
                        value["owner_refusals"] += 1
                    elif outcome:
                        value["durable_movements"] += max(
                            1, int(record.get("movement_count") or 1))
                    value["last_outcome"] = outcome or None
                    value["last_run_at"] = float(
                        record.get("observed_at") or 0.0)
                    if outcome == "contract_discrepancy":
                        value["last_failure_stage"] = (
                            record.get("failure_stage"))
                        value["last_failure_code"] = (
                            record.get("failure_code"))
            finally:
                handle.close()
        for value in attention.values():
            value["unselected_exposures"] = max(
                0, value["exposures"] - value["selections"])
        return attention, activity

    def attention_stats(self) -> dict[str, dict]:
        return self._receipt_summaries()[0]

    def resource_status(self) -> dict:
        """Count lifecycle occupation without exposing ids or private prose."""
        views = list(self._views().values())
        states = {name: 0 for name in (
            "open", "paused", "satisfied", "released")}
        for value in views:
            state = str(value.get("state") or "")
            if state in states:
                states[state] += 1
        attention, _activity = self._receipt_summaries()
        return {
            "schema_version": 1,
            "pending_cues": len(self.pending_cues()),
            "open_intentions": states["open"],
            "paused_intentions": states["paused"],
            "satisfied_intentions": states["satisfied"],
            "released_intentions": states["released"],
            "unselected_exposures": sum(
                int(value.get("unselected_exposures") or 0)
                for value in attention.values()),
            "content_free": True,
            "read_only": True,
        }

    def continuity_for(self, intention_id: str) -> dict[str, float]:
        """Latest measured consequence, falling back to formation evidence."""
        intention = self.intention(intention_id)
        for record in reversed(self.receipt_records(limit=4000)):
            if record.get("kind") == "run" \
                    and record.get("intention_id") == intention_id:
                return _continuity(record)
        return _continuity(intention.get("continuity"))

    def status(self) -> dict:
        stats, activity = self._receipt_summaries()
        intentions = []
        for intention in self.intentions():
            from core.project_loom import shadow_eligibility
            intentions.append({
                **intention,
                "relationships": self.relationships_for(
                    intention["intention_id"]),
                "project_loom_shadow": shadow_eligibility(intention),
                "attention": stats.get(intention["intention_id"], {
                    "subject_kind": "intention", "exposures": 0,
                    "selections": 0, "unselected_exposures": 0,
                    "last_exposed_at": None, "last_selected_at": None,
                }),
                "activity": activity.get(intention["intention_id"], {
                    "run_count": 0, "durable_movements": 0,
                    "quiet_encounters": 0, "contract_discrepancies": 0,
                    "owner_refusals": 0, "last_outcome": None,
                    "last_run_at": None, "last_failure_stage": None,
                    "last_failure_code": None,
                }),
            })
        pending = []
        for cue in self.pending_cues():
            pending.append({
                **cue,
                "attention": stats.get(cue["cue_id"], {
                    "subject_kind": "cue", "exposures": 0,
                    "selections": 0, "unselected_exposures": 0,
                    "last_exposed_at": None, "last_selected_at": None,
                }),
                "activity": activity.get(cue["cue_id"], {
                    "run_count": 0, "durable_movements": 0,
                    "quiet_encounters": 0, "contract_discrepancies": 0,
                    "owner_refusals": 0, "last_outcome": None,
                    "last_run_at": None, "last_failure_stage": None,
                    "last_failure_code": None,
                }),
            })
        return {
            "root": "body/intention_loom",
            "pending_cues": pending,
            "intentions": intentions,
            "receipts": self.receipt_records(limit=30),
            "policy": {
                "cue_is_not_intention": True,
                "field_win_opens_resource_shaped_interior_work": True,
                "fixed_movement_quota": False,
                "quiet_is_for_now": True,
                "paused_can_self_resume": True,
                "attention_receipts_are_observational": True,
                "neglect_changes_selection": False,
                "relationships_are_descriptive": True,
                "relationships_do_not_auto_merge": True,
                "project_requires_relationship": False,
                "open_private_intention_can_propose_project": True,
                "intention_is_not_consent": True,
                "owned_intention_carries_interior_authority": True,
                "interior_authority_requires_no_external_grant": True,
                "intention_does_not_expand_ownership": True,
                "intention_does_not_change_constitutional_machinery": True,
                "intention_does_not_authorize_external_discharge": True,
                "consent_grants_created_here": False,
                "owned_private_project_handoff": True,
                "same_owner_organ_dispatch": True,
                "external_tools": False,
                "external_messages": False,
                "publication": False,
                "constitutional_overwrite": False,
                "lifecycle_mutation_owned_by_destination": True,
                "external_effects": False,
            },
        }
