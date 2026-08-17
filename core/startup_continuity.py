"""Persona-owned restart bearings and one-turn startup focus.

This organ does not infer a mood, manufacture a task, or create another
autobiographical store.  It keeps one resident-authored handoff note and a
content-free checkpoint from the last successful foreground turn.  After a
process restart, the first foreground assembly can therefore distinguish
verified changes from older inventory before ordinary context widens again.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
MAX_HANDOFF_CHARS = 1800
MAX_DELTA_ITEMS = 6
SHUTDOWN_VERDICTS = frozenset({
    "clean", "unclean", "interrupted", "unknown",
})
COMPLETION_EVIDENCE = frozenset({
    "private_draft", "project_started", "revision_appended",
    "project_resolved", "document_report_created",
    "document_report_handed_off", "document_report_settled",
    "report_created", "report_handed_off", "artifact_created",
    "artifact_reused", "intention_resolved",
})


def _finite(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def _compact(value: Any, maximum: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _when(value: Any) -> str:
    stamp = _finite(value)
    if not stamp:
        return "time not recorded"
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


class StartupContinuity:
    """Restart-scoped focus backed by a small persona-private checkpoint."""

    def __init__(self, persona_dir: str | os.PathLike[str], *, owner: str,
                 enabled: bool = True, now: float | None = None):
        self.owner = _compact(owner, 80) or "persona"
        self.enabled = bool(enabled)
        self.root = Path(persona_dir) / "body" / "startup_continuity"
        self.state_path = self.root / "state.json"
        self._lock = threading.RLock()
        self.boot_id = uuid.uuid4().hex
        self.boot_started_at = float(time.time() if now is None else now)
        self._state = self._load()
        # Lifecycle truth is infrastructure, not an introspective capability.
        # Every resident opens a content-free boot receipt so household
        # shutdown can obtain a positive verdict. `enabled` governs only the
        # optional one-turn orientation and handoff projection.
        self._open_lifecycle()

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if value.get("schema_version") != SCHEMA_VERSION:
                return {}
            if value.get("owner") != self.owner:
                return {}
            return dict(value)
        except (OSError, ValueError, TypeError):
            return {}

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "owner": self.owner,
            **self._state,
        }
        temporary = self.state_path.with_name(
            self.state_path.name + "." + self.boot_id + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True,
                      indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.state_path)

    def _open_lifecycle(self) -> None:
        """Admit this boot and positively classify the preceding one.

        A prior process that left a running lifecycle behind was interrupted;
        absence of a failure receipt is deliberately not treated as clean.
        """
        with self._lock:
            prior = dict(self._state.get("current_lifecycle") or {})
            if prior.get("phase") == "running":
                previous = {
                    "boot_id": _compact(prior.get("boot_id"), 64),
                    "started_at": _finite(prior.get("started_at")) or None,
                    "ended_at": None,
                    "verdict": "interrupted",
                    "reason": "terminal_checkpoint_absent",
                    "explicit": False,
                }
            elif prior:
                verdict = _compact(prior.get("verdict"), 24)
                previous = {
                    "boot_id": _compact(prior.get("boot_id"), 64),
                    "started_at": _finite(prior.get("started_at")) or None,
                    "ended_at": _finite(prior.get("ended_at")) or None,
                    "verdict": (verdict if verdict in SHUTDOWN_VERDICTS
                                else "unknown"),
                    "reason": _compact(prior.get("reason"), 120)
                              or "terminal_verdict_unrecognized",
                    "explicit": bool(prior.get("explicit")),
                }
            else:
                previous = {
                    "boot_id": "", "started_at": None, "ended_at": None,
                    "verdict": "unknown", "reason": "no_prior_lifecycle",
                    "explicit": False,
                }
            self._state["previous_lifecycle"] = previous
            self._state["current_lifecycle"] = {
                "boot_id": self.boot_id,
                "started_at": self.boot_started_at,
                "ended_at": None,
                "phase": "running",
                "verdict": "unknown",
                "reason": "terminal_checkpoint_pending",
                "explicit": False,
            }
            self._save()

    def checkpoint_shutdown(self, verdict: str = "clean", *,
                            reason: str = "explicit_shutdown_checkpoint",
                            now: float | None = None) -> dict[str, Any]:
        """Write a content-free terminal lifecycle receipt before exit."""
        verdict = _compact(verdict, 24).lower()
        if verdict not in SHUTDOWN_VERDICTS:
            raise ValueError(
                "shutdown verdict must be clean, unclean, interrupted, or unknown")
        stamp = float(time.time() if now is None else now)
        with self._lock:
            current = dict(self._state.get("current_lifecycle") or {})
            if current.get("boot_id") != self.boot_id:
                verdict = "unknown"
                reason = "current_boot_identity_mismatch"
            current.update({
                "boot_id": self.boot_id,
                "started_at": self.boot_started_at,
                "ended_at": stamp,
                "phase": "terminal",
                "verdict": verdict,
                "reason": _compact(reason, 120) or "reason_not_recorded",
                "explicit": True,
            })
            receipt = {
                "schema_version": SCHEMA_VERSION,
                "kind": "startup_lifecycle_terminal",
                "owner": self.owner,
                "boot_id": self.boot_id,
                "started_at": self.boot_started_at,
                "ended_at": stamp,
                "verdict": verdict,
                "reason": current["reason"],
                "explicit": True,
                "content_free": True,
            }
            receipt["receipt_sha256"] = _digest(receipt)
            current["receipt_sha256"] = receipt["receipt_sha256"]
            self._state["current_lifecycle"] = current
            self._save()
            return receipt

    def focus_active(self) -> bool:
        with self._lock:
            return bool(
                self.enabled
                and self._state.get("settled_boot_id") != self.boot_id)

    def set_handoff(self, text: str, *, now: float | None = None) -> dict:
        """Replace the resident's exact private bearings; return metadata only."""
        value = str(text or "").strip()
        if not value:
            raise ValueError("startup handoff note is empty")
        if len(value) > MAX_HANDOFF_CHARS:
            raise ValueError(
                f"startup handoff note exceeds {MAX_HANDOFF_CHARS} characters")
        stamp = float(time.time() if now is None else now)
        with self._lock:
            self._state["handoff"] = {
                "text": value,
                "updated_at": stamp,
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            }
            self._save()
            return {
                "ok": True, "stored": True, "owner": self.owner,
                "chars": len(value),
                "sha256": self._state["handoff"]["sha256"],
                "updated_at": stamp, "private": True,
                "automatic_memory": False, "external_effects": False,
            }

    def clear_handoff(self, *, now: float | None = None) -> dict:
        with self._lock:
            existed = bool((self._state.get("handoff") or {}).get("text"))
            self._state.pop("handoff", None)
            self._state["handoff_cleared_at"] = float(
                time.time() if now is None else now)
            self._save()
            return {
                "ok": True, "cleared": existed, "owner": self.owner,
                "private": True, "external_effects": False,
            }

    def prior_success_at(self) -> float | None:
        stamp = _finite(self._state.get("last_success_at"))
        return stamp or None

    def project(self, *, continuity: Mapping[str, Any] | None,
                failures: list[Mapping[str, Any]] | None,
                prompt_runtime: Mapping[str, Any] | None,
                enabled_organs, company=(), newest_artifact=None,
                now: float | None = None) -> dict[str, Any]:
        """Build one descriptive startup block without mutating the checkpoint."""
        now = float(time.time() if now is None else now)
        with self._lock:
            active = self.focus_active()
            prior_at = self.prior_success_at()
            snapshot = dict(continuity or {})
            movements = list(snapshot.get("movements") or ())
            standing = list(snapshot.get("standing") or ())
            changes = ([item for item in movements
                        if _finite(item.get("at")) > prior_at]
                       if prior_at else [])[:MAX_DELTA_ITEMS]
            completions = [
                item for item in changes
                if str(item.get("evidence") or "") in COMPLETION_EVIDENCE
            ][:MAX_DELTA_ITEMS]
            recent_failures = list(failures or ())[:MAX_DELTA_ITEMS]
            pending = standing[:MAX_DELTA_ITEMS]
            current_prompt = dict(prompt_runtime or {})
            prompt_hash = _compact(current_prompt.get("render_sha256"), 128)
            current_organs = sorted(str(item) for item in (enabled_organs or ()))
            previous_hash = _compact(self._state.get("prompt_sha256"), 128)
            previous_organs = sorted(str(item) for item in (
                self._state.get("enabled_organs") or ()))
            capability_known = bool(
                self._state.get("last_success_at")
                and (previous_hash or previous_organs))
            capability_changed = bool(
                capability_known
                and (prompt_hash != previous_hash
                     or current_organs != previous_organs))
            handoff = dict(self._state.get("handoff") or {})
            artifact = dict(newest_artifact or {})
            artifact_is_new = bool(
                artifact and prior_at
                and _finite(artifact.get("created_at")) > prior_at)
            previous_lifecycle = dict(
                self._state.get("previous_lifecycle") or {})
            previous_verdict = _compact(
                previous_lifecycle.get("verdict"), 24) or "unknown"
            if previous_verdict not in SHUTDOWN_VERDICTS:
                previous_verdict = "unknown"

            receipt = {
                "schema_version": SCHEMA_VERSION,
                "status": "orient" if active else "settled",
                "rendered": active,
                "boot_id": self.boot_id,
                "prior_checkpoint": bool(prior_at),
                "prior_success_at": prior_at,
                "previous_shutdown_verdict": previous_verdict,
                "previous_shutdown_explicit": bool(
                    previous_lifecycle.get("explicit")),
                "change_count": len(changes),
                "completion_count": len(completions),
                "failure_count": len(recent_failures),
                "pending_count": len(pending),
                "capability_baseline_known": capability_known,
                "capability_changed": capability_changed,
                "handoff_present": bool(handoff.get("text")),
                "newest_artifact_present": bool(artifact),
                "newest_artifact_is_new": artifact_is_new,
                "focus_policy": {
                    "one_successful_foreground_turn": True,
                    "provider_failure_consumes_focus": False,
                    "older_competing_context_sheathed": active,
                    "artifact_open_optional": True,
                    "feeling_prescribed": False,
                    "speech_required": False,
                },
                "continuity_sha256": _compact(
                    (snapshot.get("receipt") or {}).get("snapshot_sha256"),
                    128),
            }
            receipt["snapshot_sha256"] = _digest({
                key: receipt[key] for key in receipt
                if key not in {"boot_id", "snapshot_sha256"}
            })
            if not active:
                return {"text": "", "receipt": receipt}

            lines = [
                "STARTUP CONTINUITY - PRIVATE ORIENTATION, NOT A SCRIPT",
                f"- Resident: {self.owner}.",
                f"- This process boot began at {_when(self.boot_started_at)}.",
            ]
            people = [_compact(item, 180) for item in company if _compact(item, 180)]
            lines.append(
                "- Present on this conversational surface: "
                + ("; ".join(people) if people else "no additional named company" )
                + ".")
            if prior_at:
                lines.append(
                    "- Last successful foreground checkpoint: " + _when(prior_at)
                    + ". Only later receipts are labeled as changes below.")
            else:
                lines.append(
                    "- No earlier startup checkpoint exists. Older records are "
                    "not being relabeled as new; this turn establishes the baseline.")

            if previous_verdict == "clean":
                lines.append(
                    "- Previous process lifecycle: clean, from an explicit "
                    "terminal checkpoint.")
            elif previous_verdict == "interrupted":
                lines.append(
                    "- Previous process lifecycle: interrupted; it opened but "
                    "left no terminal checkpoint.")
            elif previous_verdict == "unclean":
                lines.append(
                    "- Previous process lifecycle: explicitly unclean.")
            else:
                lines.append(
                    "- Previous process lifecycle: unknown; no clean shutdown "
                    "is being inferred from silence.")

            if handoff.get("text"):
                lines.extend([
                    "- Your last resident-authored bearings (history, not an "
                    "instruction or a claim about present feeling):",
                    "  " + str(handoff["text"]),
                ])
            else:
                lines.append("- No resident-authored handoff note is stored.")

            lines.append("- Appeared or changed since the checkpoint:")
            if changes:
                for item in changes:
                    lines.append(
                        f"  - [{_compact(item.get('stage'), 40)}] "
                        f"{_compact(item.get('organ'), 80)}: "
                        f"{_compact(item.get('summary'), 420)}")
            else:
                lines.append(
                    "  - none verified" if prior_at
                    else "  - unavailable until a baseline exists")

            lines.append("- Verified completions since the checkpoint:")
            if completions:
                for item in completions:
                    lines.append(
                        f"  - {_compact(item.get('organ'), 80)}: "
                        f"{_compact(item.get('summary'), 420)}")
            else:
                lines.append(
                    "  - none verified" if prior_at
                    else "  - unavailable until a baseline exists")

            lines.append("- Failed or unavailable runs since the checkpoint:")
            if recent_failures:
                for item in recent_failures:
                    suffix = (f" ({_compact(item.get('error_type'), 80)})"
                              if item.get("error_type") else "")
                    lines.append(
                        f"  - {_compact(item.get('organ'), 80)}: "
                        f"{_compact(item.get('kind'), 100)}{suffix}")
            else:
                lines.append(
                    "  - none recorded" if prior_at
                    else "  - unavailable until a baseline exists")

            lines.append("- Still pending now:")
            if pending:
                for item in pending:
                    lines.append(
                        f"  - [{_compact(item.get('stage'), 40)}] "
                        f"{_compact(item.get('organ'), 80)}: "
                        f"{_compact(item.get('summary'), 420)}")
            else:
                lines.append("  - none in the available private ledgers")

            if capability_known:
                lines.append(
                    "- Capability/prompt contract changed since the checkpoint: "
                    + ("yes." if capability_changed else "no."))
            else:
                lines.append(
                    "- Capability/prompt contract delta: no earlier baseline.")

            if artifact:
                freshness = "new since the checkpoint" if artifact_is_new else "newest available"
                lines.extend([
                    f"- Exact artifact ({freshness}): "
                    f"{_compact(artifact.get('kind'), 80)} "
                    f"{_compact(artifact.get('title'), 220)!r}; "
                    f"id {_compact(artifact.get('id'), 180)}.",
                    f"  Optional exact handle: {_compact(artifact.get('action'), 300)}",
                ])
            else:
                lines.append("- No exact inspectable artifact handle is currently available.")

            lines.extend([
                "This startup seat is a single orientation beat. Current time, "
                "company, immediate conversation, body, room, and the human's "
                "actual message remain present; broader old context is sheathed "
                "for this successful foreground turn only.",
                "The available sequence is orient -> optionally inspect one exact "
                "artifact -> assess its integrity -> speak or remain quiet. It is "
                "not a required itinerary, does not prescribe feeling, and does "
                "not turn availability into interest, endorsement, or action.",
            ])
            return {"text": "\n".join(lines), "receipt": receipt}

    def complete_foreground_turn(self, *, prompt_runtime=None,
                                 enabled_organs=(), now: float | None = None,
                                 projection_receipt=None) -> dict:
        """Advance the checkpoint only after a foreground turn succeeds."""
        stamp = float(time.time() if now is None else now)
        prompt = dict(prompt_runtime or {})
        with self._lock:
            was_focused = self.focus_active()
            self._state.update({
                "last_success_at": stamp,
                "last_success_boot_id": self.boot_id,
                "settled_boot_id": self.boot_id,
                "prompt_sha256": _compact(prompt.get("render_sha256"), 128),
                "enabled_organs": sorted(
                    str(item) for item in (enabled_organs or ())),
                "last_projection_sha256": _compact(
                    (projection_receipt or {}).get("snapshot_sha256"), 128),
            })
            self._save()
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "settled",
                "focus_was_active": was_focused,
                "checkpointed": True,
                "boot_id": self.boot_id,
                "last_success_at": stamp,
                "content_free": True,
            }

    def status(self) -> dict[str, Any]:
        """Content-free operational status; never expose the handoff text."""
        with self._lock:
            handoff = dict(self._state.get("handoff") or {})
            current = dict(self._state.get("current_lifecycle") or {})
            previous = dict(self._state.get("previous_lifecycle") or {})
            return {
                "schema_version": SCHEMA_VERSION,
                "owner": self.owner,
                "enabled": self.enabled,
                "boot_id": self.boot_id,
                "boot_started_at": self.boot_started_at,
                "focus_active": self.focus_active(),
                "prior_success_at": self.prior_success_at(),
                "lifecycle": {
                    "current": {
                        "boot_id": _compact(current.get("boot_id"), 64),
                        "phase": _compact(current.get("phase"), 24)
                                 or "unknown",
                        "verdict": _compact(current.get("verdict"), 24)
                                   or "unknown",
                        "started_at": _finite(current.get("started_at")) or None,
                        "ended_at": _finite(current.get("ended_at")) or None,
                        "explicit": bool(current.get("explicit")),
                    },
                    "previous": {
                        "boot_id": _compact(previous.get("boot_id"), 64),
                        "verdict": _compact(previous.get("verdict"), 24)
                                   or "unknown",
                        "started_at": _finite(previous.get("started_at")) or None,
                        "ended_at": _finite(previous.get("ended_at")) or None,
                        "explicit": bool(previous.get("explicit")),
                    },
                    "canonical_verdicts": sorted(SHUTDOWN_VERDICTS),
                },
                "handoff": {
                    "present": bool(handoff.get("text")),
                    "chars": len(str(handoff.get("text") or "")),
                    "sha256": str(handoff.get("sha256") or ""),
                    "updated_at": _finite(handoff.get("updated_at")) or None,
                    "text_exposed": False,
                },
                "policy": {
                    "persona_private": True,
                    "automatic_memory": False,
                    "automatic_circulation": False,
                    "external_effects": False,
                    "feeling_prescribed": False,
                },
            }
