"""Durable persona-private records for witnessed, wrapper-local choices.

This is not a chooser and owns no clock or attention field.  It records the
counterfactual field only after an existing owner has won shared attention.
The salience projection may decide that a fork is worth witnessing; it never
selects an action.  Typed organ owners remain the sole validators and actors.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


MAX_ORIENTATION_CHARS = 1200


class OwnerChoiceRejected(ValueError):
    """A witnessed selection that its typed organ refused to commit."""

    def __init__(self, episode_id: str, reason: str):
        super().__init__(reason)
        self.episode_id = str(episode_id)


def _finite(value: Any, fallback: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return value if math.isfinite(value) else fallback


def _unit(value: Any) -> float:
    return max(0.0, min(1.0, _finite(value)))


def _digest(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]


def witness_projection(candidate: Mapping[str, Any],
                       readiness: Mapping[str, Any] | None = None) -> dict:
    """Describe whether an already-selected movement merits a witnessed fork.

    The projection is deliberately continuous and multi-signal.  Its output
    can open a choice episode, but cannot rank or select the alternatives.
    """
    candidate = dict(candidate or {})
    features = dict(candidate.get("features") or {})
    readiness = dict(readiness or {})
    salience = _unit(candidate.get("salience"))
    recurrence = max(
        _unit(features.get("unresolved")),
        _unit(candidate.get("recurrence")),
        min(1.0, _finite(candidate.get("intention_exposures")) / 3.0),
        min(1.0, _finite(candidate.get("unselected_exposures")) / 3.0),
    )
    embodied = max(
        _unit(features.get("body_intensity")),
        _unit(features.get("affect_change")),
        1.0 - _unit(readiness.get("readiness", 1.0)),
    )
    relationship = _unit(features.get("relationship"))
    volitional = _unit(features.get("volitional_relevance"))
    score = (
        0.38 * salience
        + 0.22 * recurrence
        + 0.16 * embodied
        + 0.14 * relationship
        + 0.10 * volitional
    )
    # A fork needs more than merely clearing the DMN candidate floor.  Any
    # combination of recurrence, embodied charge, or relationship can carry it.
    threshold = 0.20
    return {
        "witness": score >= threshold,
        "score": round(score, 6),
        "threshold": threshold,
        "signals": {
            "salience": salience,
            "recurrence": recurrence,
            "embodied_charge": embodied,
            "relationship": relationship,
            "volitional_relevance": volitional,
        },
        "selects_action": False,
    }


class ChoiceLedger:
    """Append-only reconstruction of forks, selections, and consequences."""

    def __init__(self, persona_dir: str | os.PathLike[str]):
        self.root = Path(persona_dir).resolve() / "body" / "volition"
        self.path = self.root / "choice_episodes.jsonl"
        self._lock = threading.RLock()

    def _append(self, record: Mapping[str, Any]) -> dict:
        value = dict(record)
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                value, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return value

    def records(self) -> list[dict]:
        if not self.path.is_file():
            return []
        found = []
        with self._lock, self.path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    found.append(value)
        return found

    def episodes(self) -> list[dict]:
        views: dict[str, dict] = {}
        for record in self.records():
            episode_id = str(record.get("episode_id") or "")
            if not episode_id:
                continue
            view = views.setdefault(episode_id, {
                "episode_id": episode_id, "events": []})
            view["events"].append(record)
            view.update({
                key: value for key, value in record.items()
                if key not in {"kind", "at", "events"}})
            view["state"] = record.get("kind")
            view["updated_at"] = record.get("at")
        return list(views.values())

    def open_fork(self, *, owner: str, run_id: str,
                  candidate: Mapping[str, Any], options: Sequence[str],
                  projection: Mapping[str, Any]) -> dict:
        options = [str(value).strip() for value in options if str(value).strip()]
        if len(options) < 2 or len(set(options)) != len(options):
            raise ValueError("a witnessed fork requires distinct alternatives")
        candidate = dict(candidate or {})
        episode_id = "choice_" + _digest({
            "owner": owner, "run_id": run_id,
            "candidate_key": candidate.get("key"), "options": options,
        })
        existing = next((
            item for item in self.episodes()
            if item["episode_id"] == episode_id), None)
        if existing is not None:
            return existing
        safe_candidate = {
            key: candidate.get(key) for key in (
                "key", "source", "salience", "seed_id", "project_id",
                "cue_id", "intention_id", "proposal_id")
            if candidate.get(key) is not None
        }
        return self._append({
            "kind": "fork_opened", "episode_id": episode_id,
            "at": time.time(), "owner": str(owner),
            "run_id": str(run_id), "candidate": safe_candidate,
            "options": options, "projection": dict(projection),
            "ownership": "persona_private",
        })

    def commit_choice(self, episode_id: str, *, action: str,
                      orientation: str, basis: str = "") -> dict:
        orientation = str(orientation or "").strip()[:MAX_ORIENTATION_CHARS]
        basis = str(basis or "").strip()[:MAX_ORIENTATION_CHARS]
        episode = next((
            item for item in self.episodes()
            if item["episode_id"] == episode_id), None)
        if episode is None:
            raise ValueError("choice episode does not exist")
        if action not in set(episode.get("options") or []):
            raise ValueError("choice is outside the witnessed counterfactual field")
        return self._append({
            "kind": "choice_committed", "episode_id": episode_id,
            "at": time.time(), "owner": episode.get("owner"),
            "run_id": episode.get("run_id"), "action": action,
            "orientation": orientation, "basis": basis,
        })

    def settle_owner(self, episode_id: str, *, accepted: bool,
                     outcome: str, durable_ref: str = "",
                     reason: str = "") -> dict:
        return self._append({
            "kind": "owner_settled", "episode_id": episode_id,
            "at": time.time(), "accepted": bool(accepted),
            "outcome": str(outcome), "durable_ref": str(durable_ref or ""),
            "reason": str(reason or "")[:400],
        })

    def encounter_consequence(self, episode_id: str, *,
                              candidate_key: str) -> dict:
        return self._append({
            "kind": "consequence_encountered", "episode_id": episode_id,
            "at": time.time(), "candidate_key": str(candidate_key),
        })

    def pending_consequences(self, owner: str) -> list[dict]:
        pending = []
        for episode in self.episodes():
            if episode.get("owner") != owner \
                    or episode.get("state") != "owner_settled":
                continue
            pending.append(episode)
        return pending

    def status(self) -> dict:
        episodes = self.episodes()
        return {
            "episode_count": len(episodes),
            "pending_consequence_count": sum(
                1 for item in episodes
                if item.get("state") == "owner_settled"),
            "owner_counts": {
                owner: sum(1 for item in episodes
                           if item.get("owner") == owner)
                for owner in sorted({
                    str(item.get("owner")) for item in episodes
                    if item.get("owner")})
            },
            "stores_orientation_text": True,
            "projects_orientation_text": False,
            "external_effects": False,
            "journal_access": False,
            "selects_action": False,
        }
