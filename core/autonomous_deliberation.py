"""Bounded access to a resident's intermediary API deliberation vessel.

This module does not create an autonomy opening, choose a candidate, or make
speech more likely.  It only arbitrates whether an already-configured,
intermediary API model may be consulted after the organism has produced a
genuine decision boundary.

The budget is a persistent resource reservoir rather than a polling clock:
credits refill continuously, are spent only by real autonomy episodes, and
fall back to the resident's local idle vessel when unavailable.  A rolling
token wall provides a second, provider-agnostic ceiling even when model prices
are unavailable or change independently of JNAIQ.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
import os
import threading
import time
import uuid


SCHEMA_VERSION = 1
DEFAULTS = {
    "enabled": False,
    "model": "",
    "credit_capacity": 2.0,
    "refill_credits_per_day": 4.0,
    "episode_credit_cost": 1.0,
    "rolling_window_hours": 24.0,
    "rolling_episode_cap": 6,
    "rolling_token_cap": 48000,
    "reservation_tokens": 8000,
}


def _finite(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def resolve_autonomous_deliberation(config: dict | None) -> dict:
    """Normalize the resource envelope without deciding model eligibility."""
    raw = dict(config or {})
    out = dict(DEFAULTS)
    out["enabled"] = bool(raw.get("enabled", out["enabled"]))
    out["model"] = str(raw.get("model") or "").strip()
    if raw.get("reason"):
        out["reason"] = str(raw.get("reason"))[:120]
    out["credit_capacity"] = max(
        0.0, _finite(raw.get("credit_capacity"), out["credit_capacity"]))
    out["refill_credits_per_day"] = max(
        0.0, _finite(raw.get("refill_credits_per_day"),
                     out["refill_credits_per_day"]))
    out["episode_credit_cost"] = max(
        0.001, _finite(raw.get("episode_credit_cost"),
                       out["episode_credit_cost"]))
    out["rolling_window_hours"] = max(
        1.0, _finite(raw.get("rolling_window_hours"),
                     out["rolling_window_hours"]))
    out["rolling_episode_cap"] = max(
        0, int(_finite(raw.get("rolling_episode_cap"),
                       out["rolling_episode_cap"])))
    out["rolling_token_cap"] = max(
        0, int(_finite(raw.get("rolling_token_cap"),
                       out["rolling_token_cap"])))
    out["reservation_tokens"] = max(
        1, int(_finite(raw.get("reservation_tokens"),
                       out["reservation_tokens"])))
    if not out["model"]:
        out["enabled"] = False
        out.setdefault("reason", "model_unconfigured")
    elif out["credit_capacity"] < out["episode_credit_cost"]:
        out["enabled"] = False
        out["reason"] = "credit_capacity_below_episode_cost"
    elif out["rolling_token_cap"] < out["reservation_tokens"]:
        out["enabled"] = False
        out["reason"] = "token_cap_below_reservation"
    if not out["enabled"]:
        out.setdefault("reason", "disabled")
    return out


@contextmanager
def _process_write_lock(path: str):
    """Serialize the resident budget across accidental duplicate cockpits."""
    lock_path = os.path.abspath(path) + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class AutonomousDeliberationBudget:
    """Thread-safe, restart-durable credit and token reservoir.

    ``claim`` is intentionally downstream from organism selection.  A claim
    may choose a model resource; it cannot cause an episode or determine what
    the resident says.  Every attempted API episode consumes one credit,
    including provider failures, so an unhealthy API can never become a retry
    furnace.  Successful episodes are additionally charged their observed
    model tokens, conservatively using the reservation when usage is absent.
    """

    def __init__(self, directory: str, owner: str,
                 config: dict | None = None, *, now: float | None = None):
        self.directory = os.path.abspath(directory)
        self.owner = str(owner or "unknown")
        self.config = resolve_autonomous_deliberation(config)
        self.state_path = os.path.join(self.directory, "state.json")
        self.receipt_path = os.path.join(self.directory, "receipts.jsonl")
        self._lock = threading.RLock()
        self._state = self._load(now=time.time() if now is None else now)

    @contextmanager
    def _exclusive_state(self):
        with self._lock, _process_write_lock(self.state_path):
            yield

    def _initial(self, now: float) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "credit_balance": float(self.config["credit_capacity"]),
            "credit_updated_at": float(now),
            "episodes": [],
        }

    def _load(self, *, now: float) -> dict:
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if int(raw.get("schema_version") or 0) != SCHEMA_VERSION:
                raise ValueError("unsupported schema")
            state = {
                "schema_version": SCHEMA_VERSION,
                "credit_balance": max(0.0, min(
                    float(self.config["credit_capacity"]),
                    _finite(raw.get("credit_balance"),
                            self.config["credit_capacity"]))),
                "credit_updated_at": _finite(
                    raw.get("credit_updated_at"), now),
                "episodes": [dict(row) for row in raw.get("episodes", [])
                             if isinstance(row, dict)],
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            state = self._initial(now)
        self._advance(state, now)
        self._prune(state, now)
        return state

    def _advance(self, state: dict, now: float) -> None:
        now = max(0.0, float(now))
        previous = max(0.0, _finite(state.get("credit_updated_at"), now))
        effective_now = max(now, previous)
        elapsed = effective_now - previous
        refill = (elapsed / 86400.0) * float(
            self.config["refill_credits_per_day"])
        state["credit_balance"] = min(
            float(self.config["credit_capacity"]),
            max(0.0, _finite(state.get("credit_balance"), 0.0)) + refill)
        state["credit_updated_at"] = effective_now

    def _prune(self, state: dict, now: float) -> None:
        floor = float(now) - float(
            self.config["rolling_window_hours"]) * 3600.0
        state["episodes"] = [
            row for row in state.get("episodes", [])
            if _finite(row.get("claimed_at"), 0.0) >= floor]

    @staticmethod
    def _accounted_tokens(row: dict) -> int:
        if str(row.get("status") or "") == "pending":
            return max(0, int(row.get("reserved_tokens") or 0))
        return max(0, int(row.get("accounted_tokens") or 0))

    def _tokens_used(self, state: dict) -> int:
        return sum(self._accounted_tokens(row)
                   for row in state.get("episodes", []))

    def _save(self) -> None:
        os.makedirs(self.directory, exist_ok=True)
        temp = (self.state_path + "." + str(os.getpid()) + "." +
                str(threading.get_ident()) + "." + uuid.uuid4().hex + ".tmp")
        try:
            with open(temp, "w", encoding="utf-8", newline="") as handle:
                json.dump(self._state, handle, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.state_path)
        finally:
            try:
                if os.path.exists(temp):
                    os.unlink(temp)
            except OSError:
                pass

    def _receipt(self, kind: str, now: float, **payload) -> None:
        record = {
            "schema_version": SCHEMA_VERSION,
            "at": float(now),
            "kind": str(kind),
            "owner": self.owner,
            "content_free": True,
            **payload,
        }
        try:
            os.makedirs(self.directory, exist_ok=True)
            with open(self.receipt_path, "a", encoding="utf-8",
                      newline="") as handle:
                handle.write(json.dumps(
                    record, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
        except OSError:
            pass

    def claim(self, purpose: str, *, now: float | None = None) -> dict:
        """Reserve one API episode or return a local-fallback reason."""
        now = time.time() if now is None else float(now)
        with self._exclusive_state():
            # A stale duplicate cockpit must observe the other process's last
            # committed spend before it can attempt its own claim.
            self._state = self._load(now=now)
            self._advance(self._state, now)
            self._prune(self._state, now)
            reason = None
            if not self.config["enabled"]:
                reason = str(self.config.get("reason") or "disabled")
            elif (len(self._state.get("episodes", [])) >=
                  int(self.config["rolling_episode_cap"])):
                reason = "rolling_episode_cap"
            elif (float(self._state["credit_balance"]) + 1e-9 <
                  float(self.config["episode_credit_cost"])):
                reason = "credit_reservoir_empty"
            else:
                used = self._tokens_used(self._state)
                projected = used + int(self.config["reservation_tokens"])
                if projected > int(self.config["rolling_token_cap"]):
                    reason = "rolling_token_cap"
            if reason:
                result = {
                    "granted": False,
                    "reason": reason,
                    "model": "",
                    "purpose": str(purpose or "autonomy"),
                    "credit_balance": round(
                        float(self._state["credit_balance"]), 6),
                    "rolling_tokens_used": self._tokens_used(self._state),
                }
                self._receipt("claim_denied", now, **result)
                return result

            claim_id = uuid.uuid4().hex
            self._state["credit_balance"] = max(
                0.0, float(self._state["credit_balance"]) -
                float(self.config["episode_credit_cost"]))
            row = {
                "claim_id": claim_id,
                "claimed_at": now,
                "purpose": str(purpose or "autonomy")[:80],
                "model": self.config["model"][:96],
                "status": "pending",
                "reserved_tokens": int(self.config["reservation_tokens"]),
            }
            self._state["episodes"].append(row)
            self._save()
            result = {
                "granted": True,
                "claim_id": claim_id,
                "model": self.config["model"],
                "purpose": row["purpose"],
                "credit_balance": round(
                    float(self._state["credit_balance"]), 6),
                "rolling_tokens_used": self._tokens_used(self._state),
            }
            self._receipt("claim_granted", now, **result)
            return result

    def settle(self, claim_id: str, model_receipts: list | None = None, *,
               status: str = "ok", now: float | None = None) -> dict:
        """Replace a reservation with observed usage and a terminal status."""
        now = time.time() if now is None else float(now)
        claim_id = str(claim_id or "")
        with self._exclusive_state():
            self._state = self._load(now=now)
            row = next((item for item in self._state.get("episodes", [])
                        if item.get("claim_id") == claim_id), None)
            if row is None:
                return {"settled": False, "reason": "claim_not_found"}
            if row.get("status") != "pending":
                return {
                    "settled": True,
                    "idempotent": True,
                    "status": row.get("status"),
                    "accounted_tokens": self._accounted_tokens(row),
                }
            total = 0
            calls = 0
            for receipt in model_receipts or ():
                if not isinstance(receipt, dict):
                    continue
                calls += 1
                observed = receipt.get("total_tokens")
                if observed is None:
                    observed = (int(receipt.get("input_tokens") or 0) +
                                int(receipt.get("output_tokens") or 0))
                total += max(0, int(observed or 0))
            terminal = str(status or "unknown")[:40]
            if terminal == "ok" and total <= 0:
                total = int(row.get("reserved_tokens") or 0)
            row.update({
                "status": terminal,
                "settled_at": now,
                "model_calls": calls,
                "accounted_tokens": total,
            })
            self._advance(self._state, now)
            self._prune(self._state, now)
            self._save()
            result = {
                "settled": True,
                "status": terminal,
                "accounted_tokens": total,
                "model_calls": calls,
                "rolling_tokens_used": self._tokens_used(self._state),
            }
            self._receipt("claim_settled", now, claim_id=claim_id, **result)
            return result

    def snapshot(self, *, now: float | None = None) -> dict:
        """Return a content-free, non-writing view of the live envelope."""
        now = time.time() if now is None else float(now)
        with self._exclusive_state():
            # Reloading is read-only and makes status truthful even if a stale
            # duplicate process was the last writer.
            self._state = self._load(now=now)
            state = {
                "credit_balance": self._state["credit_balance"],
                "credit_updated_at": self._state["credit_updated_at"],
                "episodes": [dict(row)
                             for row in self._state.get("episodes", [])],
            }
            self._advance(state, now)
            self._prune(state, now)
            used = self._tokens_used(state)
            pending = sum(1 for row in state["episodes"]
                          if row.get("status") == "pending")
            return {
                "schema_version": SCHEMA_VERSION,
                "owner": self.owner,
                "enabled": bool(self.config["enabled"]),
                "reason": self.config.get("reason"),
                "model": self.config["model"],
                "fallback": "local_idle_model",
                "credit_balance": round(float(state["credit_balance"]), 6),
                "credit_capacity": float(self.config["credit_capacity"]),
                "refill_credits_per_day": float(
                    self.config["refill_credits_per_day"]),
                "episode_credit_cost": float(
                    self.config["episode_credit_cost"]),
                "rolling_window_hours": float(
                    self.config["rolling_window_hours"]),
                "rolling_episode_cap": int(
                    self.config["rolling_episode_cap"]),
                "rolling_episodes_remaining": max(
                    0, int(self.config["rolling_episode_cap"]) -
                    len(state["episodes"])),
                "rolling_token_cap": int(
                    self.config["rolling_token_cap"]),
                "rolling_tokens_used": used,
                "rolling_tokens_remaining": max(
                    0, int(self.config["rolling_token_cap"]) - used),
                "reservation_tokens": int(
                    self.config["reservation_tokens"]),
                "episodes_in_window": len(state["episodes"]),
                "pending_episodes": pending,
                "creates_autonomy_openings": False,
                "changes_speech_choice": False,
                "content_free": True,
            }

    def resource_status(self, *, now: float | None = None) -> dict:
        """Pure envelope projection for R-1; do not reload or mutate state."""
        now = time.time() if now is None else float(now)
        with self._lock:
            state = {
                "credit_balance": self._state["credit_balance"],
                "credit_updated_at": self._state["credit_updated_at"],
                "episodes": [dict(row)
                             for row in self._state.get("episodes", [])],
            }
        self._advance(state, now)
        self._prune(state, now)
        used = self._tokens_used(state)
        return {
            "schema_version": SCHEMA_VERSION,
            "owner": self.owner,
            "enabled": bool(self.config["enabled"]),
            "credit_balance": round(float(state["credit_balance"]), 6),
            "credit_capacity": float(self.config["credit_capacity"]),
            "rolling_token_cap": int(self.config["rolling_token_cap"]),
            "rolling_tokens_used": used,
            "rolling_tokens_remaining": max(
                0, int(self.config["rolling_token_cap"]) - used),
            "content_free": True,
            "read_only": True,
            "state_reloaded": False,
        }
