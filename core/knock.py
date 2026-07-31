"""Event-driven self-initiated contact junction.

Private impulses and their selection belong to the persona. Ordinary delivery
uses an already-open household conversation channel, not a per-message grant.
No timer manufactures recurrence and silence never adds pressure or revokes
the standing invitation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping


GESTURES = {"speak", "approach_and_speak", "leave_note"}


def _unit(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number if math.isfinite(number) else 0.0))


def _digest(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


class KnockJunction:
    """Append-only impulse/delivery history with standing-policy discharge."""

    def __init__(self, persona_dir, *, owner: str,
                 policy: Mapping[str, Any] | None = None,
                 now_fn: Callable[[], float] = time.time):
        self.owner = str(owner or "").strip().casefold()
        if not self.owner:
            raise ValueError("knock junction requires an owner")
        self.root = Path(persona_dir) / "body" / "knock"
        self.path = self.root / "events.jsonl"
        self.now_fn = now_fn
        raw = dict(policy or {})
        self.policy = {
            "enabled": bool(raw.get("enabled", False)),
            "delivery_open": bool(raw.get("delivery_open", True)),
            "audiences": {
                str(value).strip().casefold()
                for value in raw.get("audiences", ()) if str(value).strip()},
            "gestures": set(raw.get("gestures", ())) & GESTURES,
        }

    def _append(self, event: Mapping[str, Any]) -> dict:
        record = {"schema": 1, **dict(event)}
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return record

    def events(self) -> list[dict]:
        if not self.path.is_file():
            return []
        found = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict) and value.get("schema") == 1:
                found.append(value)
        return found

    def impulses(self) -> list[dict]:
        views: dict[str, dict] = {}
        for event in self.events():
            impulse_id = str(event.get("impulse_id") or "")
            if not impulse_id:
                continue
            view = views.setdefault(impulse_id, {
                "impulse_id": impulse_id, "state": "open",
                "offer_count": 0, "delivery_count": 0,
                "unanswered_count": 0, "failed_count": 0,
            })
            kind = event.get("kind")
            if kind == "impulse_offered":
                view.update({
                    "audience": event.get("audience"),
                    "text": event.get("text"),
                    "source": event.get("source"),
                    "signals": event.get("signals"),
                })
                view["offer_count"] += 1
            elif kind == "gesture_chosen":
                view["chosen_gesture"] = event.get("gesture")
            elif kind == "delivery_succeeded":
                view["delivery_count"] += 1
                view["unanswered_count"] += 1
                view["state"] = "discharged"
            elif kind == "delivery_failed":
                view["failed_count"] += 1
                view["state"] = "open"
            elif kind == "delivery_acknowledged":
                view["unanswered_count"] = max(
                    0, view["unanswered_count"] - 1)
            elif kind == "impulse_released":
                view["state"] = "released"
            view["updated_at"] = event.get("at")
        return list(views.values())

    def offer(self, *, source: str, source_ref: str, audience: str, text: str,
              recurrence: float, relevance: float, readiness: float,
              relationship: float, interruption_cost: float) -> dict:
        """Offer naturally witnessed evidence; this selects and sends nothing."""
        source = str(source or "").strip()
        source_ref = str(source_ref or "").strip()
        audience = str(audience or "").strip()
        text = str(text or "").strip()
        if not source or not source_ref or not audience or not text:
            raise ValueError("knock impulse evidence is incomplete")
        offered_at = float(self.now_fn())
        impulse_id = "knock_" + _digest({
            "owner": self.owner, "source": source,
            "source_ref": source_ref, "audience": audience.casefold(),
            "offered_at": offered_at,
        })
        signals = {
            "recurrence": _unit(recurrence),
            "relevance": _unit(relevance),
            "readiness": _unit(readiness),
            "relationship": _unit(relationship),
            "interruption_cost": _unit(interruption_cost),
        }
        # Availability is an affordance, never a branch output.
        score = (
            .28 * signals["recurrence"]
            + .24 * signals["relevance"]
            + .20 * signals["readiness"]
            + .18 * signals["relationship"]
            - .22 * signals["interruption_cost"])
        eligible = (
            signals["recurrence"] >= .35
            and signals["readiness"] > 0.0
            and score >= .48)
        event = self._append({
            "kind": "impulse_offered", "impulse_id": impulse_id,
            "at": offered_at, "owner": self.owner,
            "source": source, "source_ref_digest": _digest(source_ref),
            "audience": audience, "text": text,
            "signals": signals, "score": round(score, 6),
            "eligible": eligible, "selects_gesture": False,
            "ownership": "persona_private",
        })
        return {
            "impulse_id": impulse_id, "eligible": eligible,
            "score": event["score"], "signals": signals,
            "selects_gesture": False,
        }

    def _impulse(self, impulse_id: str) -> dict:
        found = next((
            value for value in reversed(self.impulses())
            if value["impulse_id"] == impulse_id), None)
        if found is None:
            raise ValueError("knock impulse does not exist")
        return found

    def choose_and_deliver(
            self, impulse_id: str, *, gesture: str,
            deliver: Callable[[dict], Mapping[str, Any]]) -> dict:
        """The owner chooses; standing policy admits; callback delivers."""
        impulse = self._impulse(str(impulse_id or ""))
        gesture = str(gesture or "").strip()
        if impulse["state"] != "open":
            raise ValueError("knock impulse is not open")
        if gesture not in GESTURES:
            raise ValueError("knock gesture is unknown")
        audience_key = str(impulse.get("audience") or "").casefold()
        if not self.policy["enabled"] \
                or not self.policy["delivery_open"] \
                or audience_key not in self.policy["audiences"] \
                or gesture not in self.policy["gestures"]:
            raise ValueError("standing household contact policy does not admit this")
        chosen = self._append({
            "kind": "gesture_chosen", "impulse_id": impulse_id,
            "at": float(self.now_fn()), "gesture": gesture,
            "owner": self.owner, "ownership": "persona_private",
        })
        envelope = {
            "impulse_id": impulse_id, "from": self.owner,
            "to": impulse["audience"], "gesture": gesture,
            "text": impulse["text"],
        }
        try:
            result = dict(deliver(envelope) or {})
            if not result.get("ok"):
                raise RuntimeError("delivery did not confirm success")
        except Exception as exc:
            self._append({
                "kind": "delivery_failed", "impulse_id": impulse_id,
                "at": float(self.now_fn()), "gesture": gesture,
                "audience": impulse.get("audience"),
                "error_type": type(exc).__name__,
            })
            return {
                "ok": False, "impulse_id": impulse_id,
                "gesture": gesture, "restored": True,
                "error_type": type(exc).__name__,
            }
        receipt = self._append({
            "kind": "delivery_succeeded", "impulse_id": impulse_id,
            "at": float(self.now_fn()), "gesture": gesture,
            "audience": impulse.get("audience"),
            "delivery_channel": str(result.get("delivery_channel") or ""),
            "delivery_ref": str(result.get("delivery_ref") or ""),
            "chosen_event_at": chosen["at"],
        })
        return {
            "ok": True, "impulse_id": impulse_id, "gesture": gesture,
            "delivery_ref": receipt["delivery_ref"],
            "audience": receipt["audience"],
            "delivery_channel": receipt["delivery_channel"],
        }

    def status(self) -> dict:
        values = self.impulses()
        return {
            "owner": self.owner,
            "mode": "self_initiated_contact_junction",
            "open_impulses": sum(v["state"] == "open" for v in values),
            "discharged_impulses": sum(
                v["state"] == "discharged" for v in values),
            "policy": {
                "enabled": self.policy["enabled"],
                "delivery_open": self.policy["delivery_open"],
                "audiences": sorted(self.policy["audiences"]),
                "gestures": sorted(self.policy["gestures"]),
            },
            "automatic_pressure_from_silence": False,
            "silence_revokes_standing_invitation": False,
            "chosen_speech_requires_signal_recheck": False,
            "unanswered_delivery_blocks_later_speech": False,
            "per_knock_human_approval": False,
            "runtime_attached": False,
        }
