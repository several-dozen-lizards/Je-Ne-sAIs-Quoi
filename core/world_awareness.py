"""Persona-private, typed awareness episodes from existing JNSQ senses.

This organ is a circulation junction, not a second canonical store.  Weather,
room, project, relationship, resource, and public-research systems retain
ownership of their facts.  The junction remembers only what changed, where it
came from, whether it crossed a descriptive noticeability boundary, and
whether the resident has already been offered that change.

Biologically borrowed awareness language is a functional alias.  An episode
does not prescribe interest, feeling, speech, investigation, or action.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
DOMAINS = frozenset({
    "weather", "seasonal_light", "local_news", "civic", "household",
    "resources", "capabilities", "projects", "relational", "cultural",
})
EXTERNAL_RESEARCH_DOMAINS = frozenset({"local_news", "civic", "cultural"})
MAX_EPISODES = 96
MAX_SUMMARY_CHARS = 900


def _bounded(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _clean(value: Any, limit: int = MAX_SUMMARY_CHARS) -> str:
    return " ".join(str(value or "").split())[:limit]


def _digest(value: Any) -> str:
    wire = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()


def noticeability(dimensions: Mapping[str, Any], *, familiarity: float = 0.0,
                  explicit: bool = False) -> dict:
    """Project a multidimensional change without declaring what it means.

    Complementary accumulation keeps several modest relationships capable of
    crossing together.  Consequence and explicit resident inspection lower
    the boundary; familiarity raises it.  The components and formula remain
    visible so a crossing is falsifiable rather than a magic salience number.
    """
    values = {
        name: _bounded(dimensions.get(name))
        for name in ("novelty", "locality", "consequence", "provenance",
                     "freshness", "chosen_interest")
    }
    weights = {
        "novelty": .78, "locality": .48, "consequence": .86,
        "provenance": .42, "freshness": .36, "chosen_interest": .92,
    }
    remainder = 1.0
    for name, value in values.items():
        remainder *= 1.0 - value * weights[name]
    pressure = 1.0 - remainder
    familiarity = _bounded(familiarity)
    boundary = .66 + .16 * familiarity - .24 * values["consequence"]
    if explicit:
        boundary -= .34
    boundary = max(.24, min(.88, boundary))
    return {
        "dimensions": values,
        "weights": weights,
        "pressure": round(pressure, 6),
        "boundary": round(boundary, 6),
        "crossed": pressure >= boundary,
        "explicit": bool(explicit),
        "familiarity": round(familiarity, 6),
        "formula": "1-product(1-dimension*weight) against adaptive boundary",
    }


class WorldAwareness:
    """Persist bounded persona-private episode state and content-free receipts."""

    def __init__(self, persona_dir: str, *, owner: str = "persona",
                 enabled: bool = True, now_fn=time.time):
        self.persona_dir = os.path.abspath(os.fspath(persona_dir))
        self.owner = str(owner or "persona")
        self.enabled = bool(enabled)
        self.now_fn = now_fn
        self.boot_id = uuid.uuid4().hex
        self.state_dir = os.path.join(
            self.persona_dir, "body", "world_awareness")
        self.state_path = os.path.join(self.state_dir, "state.json")
        self.receipt_path = os.path.join(
            self.persona_dir, "history", "world_awareness.jsonl")
        self._lock = threading.RLock()
        self._receipt_lock = threading.Lock()
        self._state = self._load()

    def _default_state(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "owner": self.owner,
            "revision": 0,
            "latest": {},
            "domain_observations": {},
            "episodes": [],
        }

    def _load(self) -> dict:
        state = self._default_state()
        try:
            with open(self.state_path, encoding="utf-8") as stream:
                loaded = json.load(stream)
        except (OSError, TypeError, ValueError):
            return state
        if not isinstance(loaded, dict):
            return state
        state["revision"] = max(0, int(loaded.get("revision") or 0))
        state["latest"] = {
            str(key): str(value) for key, value in
            dict(loaded.get("latest") or {}).items()
            if str(key).split(":", 1)[0] in DOMAINS
        }
        state["domain_observations"] = {
            domain: max(0, int(count or 0)) for domain, count in
            dict(loaded.get("domain_observations") or {}).items()
            if domain in DOMAINS
        }
        episodes = []
        for value in list(loaded.get("episodes") or ())[-MAX_EPISODES:]:
            if not isinstance(value, Mapping):
                continue
            episode = self._sanitize_episode(value)
            if episode is not None:
                episodes.append(episode)
        state["episodes"] = episodes
        return state

    @staticmethod
    def _sanitize_episode(value: Mapping[str, Any]) -> dict | None:
        domain = str(value.get("domain") or "")
        episode_id = str(value.get("episode_id") or "")[:96]
        summary = _clean(value.get("summary"))
        if domain not in DOMAINS or not episode_id or not summary:
            return None
        return {
            "episode_id": episode_id,
            "domain": domain,
            "source_key": str(value.get("source_key") or "")[:160],
            "summary": summary,
            "facts": dict(value.get("facts") or {}),
            "provenance": dict(value.get("provenance") or {}),
            "observed_at": float(value.get("observed_at") or 0.0),
            "valid_until": (float(value["valid_until"])
                            if value.get("valid_until") is not None else None),
            "fingerprint": str(value.get("fingerprint") or "")[:80],
            "noticeability": dict(value.get("noticeability") or {}),
            "baseline": bool(value.get("baseline")),
            "state": (str(value.get("state") or "registered")
                      if str(value.get("state") or "registered") in {
                          "registered", "available", "offered", "opened",
                          "released"} else "registered"),
            "rendered_at": (float(value["rendered_at"])
                            if value.get("rendered_at") is not None else None),
            "offered_at": (float(value["offered_at"])
                           if value.get("offered_at") is not None else None),
        }

    def _persist_locked(self) -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        self._state["schema_version"] = SCHEMA_VERSION
        self._state["owner"] = self.owner
        self._state["revision"] = int(self._state.get("revision") or 0) + 1
        tmp = self.state_path + "." + self.boot_id + ".tmp"
        with open(tmp, "w", encoding="utf-8") as stream:
            json.dump(self._state, stream, ensure_ascii=False,
                      sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, self.state_path)

    def _record(self, kind: str, **fields) -> dict:
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "at": self.now_fn(),
            "boot_id": self.boot_id,
            "owner": self.owner,
            "kind": str(kind),
            **fields,
        }
        for forbidden in ("summary", "facts", "url", "query", "focus"):
            receipt.pop(forbidden, None)
        os.makedirs(os.path.dirname(self.receipt_path), exist_ok=True)
        line = json.dumps(receipt, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":")) + "\n"
        with self._receipt_lock:
            with open(self.receipt_path, "a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
        return receipt

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def observe(self, domain: str, *, source_key: str, summary: str,
                facts: Mapping[str, Any] | None = None,
                provenance: Mapping[str, Any] | None = None,
                dimensions: Mapping[str, Any] | None = None,
                observed_at: float | None = None,
                valid_until: float | None = None,
                explicit: bool = False,
                fingerprint_basis: Mapping[str, Any] | None = None) -> dict:
        domain = str(domain or "").casefold().strip()
        if domain not in DOMAINS:
            raise ValueError(f"unknown awareness domain: {domain}")
        summary = _clean(summary)
        if not summary:
            raise ValueError("awareness observation needs a summary")
        source_key = _clean(source_key, 160) or domain
        observed_at = self.now_fn() if observed_at is None else float(observed_at)
        facts = dict(facts or {})
        provenance = dict(provenance or {})
        fingerprint = _digest({
            "domain": domain, "source_key": source_key,
            **({"basis": dict(fingerprint_basis)}
               if fingerprint_basis is not None else
               {"summary": summary, "facts": facts}),
            "provenance": provenance,
        })
        latest_key = f"{domain}:{source_key}"
        with self._lock:
            if self._state.get("latest", {}).get(latest_key) == fingerprint:
                return {
                    "changed": False, "crossed": False,
                    "domain": domain, "fingerprint": fingerprint,
                    "reason": "unchanged",
                }
            observations = int(
                self._state.setdefault("domain_observations", {}).get(
                    domain, 0) or 0)
            baseline = observations == 0
            familiarity = min(1.0, math.log1p(observations) / math.log(12.0))
            projection = noticeability(
                dimensions or {}, familiarity=familiarity,
                explicit=explicit)
            # A first ordinary sample establishes coordinates. It is not a
            # fabricated change. Explicit inspection and high-consequence
            # observations can still cross on their first encounter.
            crossed = bool(projection["crossed"] and (
                not baseline or explicit or
                projection["dimensions"]["consequence"] >= .85))
            episode_id = "wa_" + _digest({
                "domain": domain, "fingerprint": fingerprint,
                "observed_at": observed_at,
            })[:24]
            episode = {
                "episode_id": episode_id,
                "domain": domain,
                "source_key": source_key,
                "summary": summary,
                "facts": facts,
                "provenance": provenance,
                "observed_at": observed_at,
                "valid_until": valid_until,
                "fingerprint": fingerprint,
                "noticeability": {**projection, "crossed": crossed},
                "baseline": baseline,
                "state": "available" if crossed else "registered",
                "rendered_at": None,
                "offered_at": None,
            }
            self._state.setdefault("latest", {})[latest_key] = fingerprint
            self._state["domain_observations"][domain] = observations + 1
            self._state.setdefault("episodes", []).append(episode)
            self._state["episodes"] = self._state["episodes"][-MAX_EPISODES:]
            self._persist_locked()
        self._record(
            "episode_observed", episode_id=episode_id, domain=domain,
            source_key_sha256=_digest(source_key), fingerprint=fingerprint,
            baseline=baseline, crossed=crossed,
            pressure=projection["pressure"], boundary=projection["boundary"],
            explicit=bool(explicit), content_free=True)
        return {"changed": True, "crossed": crossed,
                "domain": domain, "episode": dict(episode)}

    def latest_episode(self, domain: str, *, source_key: str = "") -> dict | None:
        """Return the latest private episode for one typed source."""
        domain = str(domain or "").casefold().strip()
        source_key = str(source_key or "")
        with self._lock:
            value = next((
                episode for episode in reversed(self._state["episodes"])
                if episode.get("domain") == domain
                and (not source_key
                     or episode.get("source_key") == source_key)), None)
            return dict(value) if value is not None else None

    def acknowledge(self, episode_id: str, *, outcome: str = "offered") -> dict:
        with self._lock:
            episode = next((value for value in self._state["episodes"]
                            if value["episode_id"] == episode_id), None)
            if episode is None:
                raise ValueError("awareness episode not found")
            episode["state"] = "offered"
            episode["offered_at"] = self.now_fn()
            self._persist_locked()
        self._record("episode_offered", episode_id=episode_id,
                     domain=episode["domain"], outcome=str(outcome)[:120],
                     content_free=True)
        return {"ok": True, "episode_id": episode_id,
                "state": "offered", "outcome": outcome}

    def release(self, episode_id: str) -> dict:
        with self._lock:
            episode = next((value for value in self._state["episodes"]
                            if value["episode_id"] == episode_id), None)
            if episode is None:
                raise ValueError("awareness episode not found")
            episode["state"] = "released"
            self._persist_locked()
        self._record("episode_released", episode_id=episode_id,
                     domain=episode["domain"], content_free=True)
        return {"ok": True, "episode_id": episode_id, "state": "released"}

    @staticmethod
    def render(episodes: Iterable[Mapping[str, Any]], *, explicit=False) -> str:
        values = list(episodes)
        if not values:
            return ""
        lead = (
            "WORLD AWARENESS — EXPLICIT PRIVATE OBSERVATION"
            if explicit else
            "WORLD AWARENESS — CHANGES AVAILABLE TO NOTICE")
        lines = [lead]
        for episode in values:
            provenance = dict(episode.get("provenance") or {})
            source = _clean(provenance.get("source") or
                            episode.get("source_key"), 120)
            lines.append(
                f"- [{episode.get('domain')}] {episode.get('summary')} "
                f"(observed {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(episode.get('observed_at') or 0.0)))}; "
                f"source {source or 'host observation'}).")
        lines.append(
            "These are sourced changes and capacities, not instructions about "
            "what matters, what you feel, whether to investigate, or whether "
            "to speak. Quiet, discrepancy, and disinterest remain valid.")
        return "\n".join(lines)

    def claim_context(self, *, domains: Iterable[str] | None = None,
                      maximum: int = 6) -> tuple[str, dict]:
        allowed = ({str(value).casefold() for value in domains}
                   if domains is not None else None)
        with self._lock:
            selected = [
                episode for episode in reversed(self._state["episodes"])
                if episode.get("state") == "available"
                and episode.get("rendered_at") is None
                and (allowed is None or episode.get("domain") in allowed)
            ][:max(1, min(12, int(maximum)))]
            selected.reverse()
            if selected:
                now = self.now_fn()
                for episode in selected:
                    episode["rendered_at"] = now
                self._persist_locked()
        text = self.render(selected)
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": "ready" if self.enabled else "disabled",
            "rendered": bool(text and self.enabled),
            "episode_count": len(selected),
            "domains": sorted({value["domain"] for value in selected}),
            "content_free": True,
        }
        if text and self.enabled:
            self._record("context_rendered", episode_count=len(selected),
                         domains=receipt["domains"], content_free=True)
            return text, receipt
        return "", receipt

    def open_domain(self, domain: str, *, maximum: int = 6) -> tuple[str, dict]:
        domain = str(domain or "").casefold().strip()
        if domain not in DOMAINS:
            raise ValueError(f"unknown awareness domain: {domain}")
        with self._lock:
            selected = [
                value for value in reversed(self._state["episodes"])
                if value["domain"] == domain and value["state"] != "released"
            ][:max(1, min(12, int(maximum)))]
            selected.reverse()
            if selected:
                for episode in selected:
                    episode["state"] = "opened"
                self._persist_locked()
        text = self.render(selected, explicit=True)
        self._record("domain_opened", domain=domain,
                     episode_count=len(selected), content_free=True)
        return text, {
            "ok": True, "domain": domain, "queued": bool(text),
            "episode_count": len(selected), "content_free": True,
        }

    def snapshot(self) -> dict:
        with self._lock:
            episodes = [dict(value) for value in self._state["episodes"]]
            return {
                "schema_version": SCHEMA_VERSION,
                "owner": self.owner,
                "enabled": self.enabled,
                "revision": self._state["revision"],
                "domains": sorted(DOMAINS),
                "external_research_domains": sorted(
                    EXTERNAL_RESEARCH_DOMAINS),
                "episodes": episodes[-24:],
                "counts": {
                    "total": len(episodes),
                    "available": sum(value["state"] == "available"
                                     for value in episodes),
                    "by_domain": {
                        domain: sum(value["domain"] == domain
                                    for value in episodes)
                        for domain in sorted(DOMAINS)
                    },
                },
                "policy": {
                    "canonical_sources_remain_external": True,
                    "private_by_default": True,
                    "automatic_memory": False,
                    "forces_interest": False,
                    "forces_speech": False,
                    "biological_equivalence_claimed": False,
                },
                "receipt": {
                    "status": "ready" if self.enabled else "disabled",
                    "episode_count": len(episodes),
                    "available_count": sum(
                        value["state"] == "available" for value in episodes),
                    "content_free": True,
                },
            }
