"""Persona-bound, read-only input adapter for the R0 entrainment audit."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from core.rest_field.entrainment import audit_entrainment
from core.rest_field.monitoring import _tail_json_rows


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _revision(rows) -> str:
    payload = json.dumps(
        rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _inventory(owner: str, contract: str, rows: list, projected: list, *,
               phase: str | None = None) -> dict[str, Any]:
    timestamps = [_finite(row.get("at")) for row in projected]
    latest = max((value for value in timestamps if value is not None),
                 default=None)
    status = "supported" if projected else "unavailable"
    if contract.startswith("mixed") or phase == "unavailable":
        status = "partial" if projected else "unavailable"
    value = {
        "status": status,
        "owner": owner,
        "ledger_contract": contract,
        "bounded_tail_row_count": len(rows),
        "admitted_content_free_projection_count": len(projected),
        "latest_evidence_at": latest,
        "evidence_revision": _revision(projected),
        "freshness_judgment": "not_inferred_no_owner_threshold",
        "content_fields_returned": False,
    }
    if phase is not None:
        value["phase_evidence"] = phase
    return value


def collect_entrainment_audit(
        persona_dir: str | Path, *,
        source_receipts_path: str | Path | None = None) -> dict[str, Any]:
    """Project existing owner histories without writing or advancing organs."""
    root = Path(persona_dir).resolve()
    history = root / "history"
    source_path = Path(source_receipts_path).resolve() \
        if source_receipts_path is not None \
        else history / "rest_source_receipts.jsonl"
    # The caller may supply the RestRuntime-owned canonical receipt path, but
    # it must remain within this resident's private directory.
    try:
        source_path.relative_to(root)
    except ValueError:
        raise ValueError("rest source receipts must belong to the persona")

    source_rows = _tail_json_rows(source_path)
    perception_rows = _tail_json_rows(history / "perception.jsonl")
    nexus_rows = _tail_json_rows(history / "resident_event_mailbox.jsonl")
    quiet_rows = _tail_json_rows(
        root / "body" / "quiet_occupancy" / "transitions.jsonl")

    oscillator = []
    for row in source_rows:
        if (row.get("content_free") is not True
                or row.get("source") != "rhythm_variation"
                or not bool(row.get("available"))):
            continue
        at = _finite(row.get("at"))
        raw = dict(row.get("raw_measurements") or {})
        movement = _finite(raw.get("distribution_shift"))
        if movement is None:
            movement = _finite(
                dict(row.get("measurements") or {}).get("distribution_shift"))
        if at is not None and movement is not None:
            oscillator.append({
                "at": at, "movement": movement, "content_free": True})

    brightness, acoustic = [], []
    for row in perception_rows:
        at = _finite(row.get("timestamp"))
        modality = str(row.get("modality") or "")
        features = row.get("features")
        features = features if isinstance(features, Mapping) else {}
        if at is None:
            continue
        if modality == "camera":
            value = _finite(features.get("brightness"))
            if value is not None:
                brightness.append(
                    {"at": at, "value": value, "content_free": True})
        elif modality == "audio":
            value = _finite(row.get("demand"))
            if value is None:
                value = _finite(features.get("rms"))
            if value is not None:
                acoustic.append(
                    {"at": at, "value": value, "content_free": True})

    nexus = []
    for row in nexus_rows:
        # ResidentEventMailbox receipts are structurally content-free by owner
        # contract. Count only `offered` so one lifecycle is not multiplied by
        # its eventual lease/claim/completion stages.
        at = _finite(row.get("at"))
        if at is not None and row.get("stage") == "offered":
            nexus.append({
                "at": at, "value": 1.0, "aggregation": "sum",
                "content_free": True})

    quiet = []
    for row in quiet_rows:
        at = _finite(row.get("at"))
        state = str(row.get("to_state") or "")
        if (row.get("content_free") is True and at is not None
                and state in {"active", "inactive"}):
            quiet.append({
                "at": at, "to_state": state, "content_free": True})

    inventory = {
        "oscillator_movement": _inventory(
            "RestRuntime rhythm_variation source receipt",
            "content_free", source_rows, oscillator,
            phase="unavailable"),
        "camera_brightness": _inventory(
            "SensoryPathway perception ledger",
            "mixed_content_ledger_numeric_allowlist_projection",
            perception_rows, brightness),
        "acoustic_activity": _inventory(
            "SensoryPathway perception ledger",
            "mixed_content_ledger_numeric_allowlist_projection",
            perception_rows, acoustic),
        "nexus_activity": _inventory(
            "ResidentEventMailbox lifecycle receipt ledger",
            "owner_structural_content_free", nexus_rows, nexus),
        "quiet_occupancy": _inventory(
            "QuietOccupancyController transition journal",
            "content_free", quiet_rows, quiet),
    }
    result = audit_entrainment(
        oscillator,
        {
            "brightness": brightness,
            "acoustic_activity": acoustic,
            "nexus_activity": nexus,
        },
        quiet_transitions=quiet,
        inventory=inventory,
        phase_available=False)
    result["persona_bound"] = True
    result["source_adapter"] = {
        "bounded_tail_bytes_per_ledger": 2_000_000,
        "new_history_writer_added": False,
        "mixed_perception_content_returned": False,
    }
    return result


__all__ = ["collect_entrainment_audit"]
