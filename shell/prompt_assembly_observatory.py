"""Bounded, allowlisted summaries of one resident's PAC0 receipt ledger.

The observatory reads only prompt-assembly metadata.  It never reads canonical
prompt sources, conversation ledgers, memories, or harvest content.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os

from harness.document_omission_shadow import analyze_document_recovery_demands


MAX_READ_BYTES = 4 * 1024 * 1024
MAX_RECENT = 80
RECEIPT_NAME = "prompt_assembly_receipts.jsonl"


def _timestamp(value):
    try:
        text = str(value).strip().replace("Z", "+00:00")
        # Python 3.10 accepts the extended ISO offset (``-04:00``) but not
        # the basic form (``-0400``) emitted by older receipt writers.
        if (len(text) >= 5 and text[-5] in "+-" and text[-4:].isdigit()
                and text[-3] != ":"):
            text = text[:-2] + ":" + text[-2:]
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _bounded_lines(path, max_bytes=MAX_READ_BYTES):
    if not os.path.isfile(path):
        return [], False
    size = os.path.getsize(path)
    truncated = size > max_bytes
    with open(path, "rb") as handle:
        if truncated:
            handle.seek(-max_bytes, os.SEEK_END)
            handle.readline()
        data = handle.read()
    return data.decode("utf-8", errors="replace").splitlines(), truncated


def available_personas(root):
    """Enumerate real persona directories; never accept a caller-owned path."""
    personas_root = os.path.join(os.path.abspath(root), "personas")
    if not os.path.isdir(personas_root):
        return []
    result = []
    with os.scandir(personas_root) as entries:
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            if not os.path.isfile(os.path.join(entry.path, "roster.yaml")):
                continue
            receipt_path = os.path.join(
                entry.path, "history", RECEIPT_NAME)
            result.append({
                "name": entry.name,
                "has_receipts": os.path.isfile(receipt_path),
            })
    return sorted(result, key=lambda item: item["name"].casefold())


def _resolve_receipt_path(root, persona):
    wanted = str(persona or "").strip().casefold()
    if not wanted:
        raise ValueError("persona is required")
    matches = [item["name"] for item in available_personas(root)
               if item["name"].casefold() == wanted]
    if len(matches) != 1:
        raise ValueError("unknown persona")
    return matches[0], os.path.join(
        os.path.abspath(root), "personas", matches[0], "history",
        RECEIPT_NAME)


def _number(value, default=0):
    return value if isinstance(value, (int, float)) else default


def _candidate_view(candidate):
    """Strict allowlist: deliberately excludes both content and digests."""
    return {
        "ordinal": int(_number(candidate.get("ordinal"))),
        "name": str(candidate.get("name") or "unnamed"),
        "outcome": str(candidate.get("outcome") or "unknown"),
        "reason": str(candidate.get("reason") or "unknown"),
        "priority": _number(candidate.get("priority")),
        "stable": bool(candidate.get("stable")),
        "block_budget_tokens": _number(
            candidate.get("block_budget_tokens")),
        "keep_tail": bool(candidate.get("keep_tail")),
        "chars_before": _number(candidate.get("chars_before")),
        "chars_after": _number(candidate.get("chars_after")),
        "tokens_before": _number(candidate.get("tokens_before")),
        "tokens_after": _number(candidate.get("tokens_after")),
        "transformation_count": len(candidate.get("transformations") or ()),
    }


def _message_view(message):
    return {
        "ordinal": int(_number(message.get("ordinal"))),
        "role": str(message.get("role") or "unknown"),
        "chars": _number(message.get("chars")),
        "tokens": _number(message.get("tokens")),
        "image_count": _number(message.get("image_count")),
    }


def _record_view(record):
    envelope = dict(record.get("envelope") or {})
    submission = dict(record.get("submission") or {})
    serialization = dict(record.get("serialization") or {})
    candidates = [_candidate_view(item) for item in
                  (record.get("candidates") or ()) if isinstance(item, dict)]
    messages = [_message_view(item) for item in
                (record.get("messages") or ()) if isinstance(item, dict)]
    practical_window = _number(envelope.get("practical_window_tokens"))
    reply_reserve = _number(envelope.get("reply_reserve_tokens"))
    estimated_before = int(
        sum(item["tokens_before"] for item in candidates)
        + sum(item["tokens"] for item in messages)
        + reply_reserve)
    has_block_cut = any(
        item["outcome"] == "truncated" for item in candidates)
    has_window_drop = any(
        item["outcome"] == "dropped" for item in candidates)
    global_pressure = bool(
        practical_window and estimated_before > practical_window)
    if has_window_drop:
        cut_classification = "global_window_pressure_drop"
    elif has_block_cut and global_pressure:
        cut_classification = "block_cap_with_global_pressure"
    elif has_block_cut:
        cut_classification = "block_cap_only"
    else:
        cut_classification = "no_cut"
    return {
        "cycle_id": str(record.get("cycle_id") or ""),
        "recorded_at": str(record.get("recorded_at") or ""),
        "policy": str((record.get("policy") or {}).get("name") or "unknown"),
        "practical_window_tokens": practical_window,
        "reply_reserve_tokens": reply_reserve,
        "requested_completion_tokens": _number(
            envelope.get("requested_completion_tokens"), None),
        "estimated_total_tokens_after": _number(
            record.get("estimated_total_tokens_after")),
        "estimated_total_tokens_before_policy": estimated_before,
        "global_window_pressure_before_policy": global_pressure,
        "has_per_block_cut": has_block_cut,
        "has_window_drop": has_window_drop,
        "cut_classification": cut_classification,
        "provider": str(submission.get("provider") or "unknown"),
        "model": str(submission.get("model") or "unknown"),
        "attempted": bool(submission.get("attempted")),
        "accepted": bool(submission.get("accepted")),
        "provider_input_tokens": _number(
            submission.get("provider_input_tokens"), None),
        "usage_evidence": str(
            submission.get("usage_evidence") or "unavailable"),
        "finish_reason": submission.get("finish_reason"),
        "error_type": submission.get("error_type"),
        "adapter_family": str(
            serialization.get("adapter_family") or "unknown"),
        "system_chars": _number(serialization.get("system_chars")),
        "user_chars": _number(serialization.get("user_chars")),
        "image_count": _number(serialization.get("image_count")),
        "candidates": candidates,
        "messages": messages,
    }


def summarize_prompt_assembly(records, *, persona, hours=24, malformed=0,
                              tail_truncated=False):
    document_shadow = analyze_document_recovery_demands(records)
    views = [_record_view(record) for record in records]
    block_groups = defaultdict(lambda: {
        "eligible": 0, "retained": 0, "truncated": 0, "dropped": 0,
        "chars_before": 0, "chars_after": 0,
    })
    for view in views:
        for candidate in view["candidates"]:
            group = block_groups[candidate["name"]]
            group["eligible"] += 1
            outcome = candidate["outcome"]
            if outcome in {"retained", "truncated", "dropped"}:
                group[outcome] += 1
            group["chars_before"] += candidate["chars_before"]
            group["chars_after"] += candidate["chars_after"]
    blocks = []
    for name, values in block_groups.items():
        blocks.append({
            "name": name,
            **values,
            "withheld_chars": max(
                0, values["chars_before"] - values["chars_after"]),
        })
    blocks.sort(key=lambda item: (-item["dropped"], -item["truncated"],
                                  -item["eligible"], item["name"]))
    candidates = [candidate for view in views
                  for candidate in view["candidates"]]
    metered = sum(view["provider_input_tokens"] is not None for view in views)
    block_cap_only = [view for view in views
                      if view["has_per_block_cut"]
                      and not view["global_window_pressure_before_policy"]]
    block_cap_with_pressure = [view for view in views
                               if view["has_per_block_cut"]
                               and view["global_window_pressure_before_policy"]]
    window_drop = [view for view in views if view["has_window_drop"]]
    no_cut = [view for view in views
              if not view["has_per_block_cut"] and not view["has_window_drop"]]
    totals = {
        "assemblies": len(views),
        "submission_attempts": sum(view["attempted"] for view in views),
        "provider_returns": sum(view["accepted"] for view in views),
        "provider_failures": sum(
            view["attempted"] and not view["accepted"] for view in views),
        "metered_returns": metered,
        "unmetered_returns": sum(
            view["accepted"] and view["provider_input_tokens"] is None
            for view in views),
        "eligible_candidates": len(candidates),
        "retained_candidates": sum(
            item["outcome"] == "retained" for item in candidates),
        "truncated_candidates": sum(
            item["outcome"] == "truncated" for item in candidates),
        "dropped_candidates": sum(
            item["outcome"] == "dropped" for item in candidates),
        "chars_before": int(sum(item["chars_before"] for item in candidates)),
        "chars_after": int(sum(item["chars_after"] for item in candidates)),
    }
    cut_pressure = {
        "block_cap_only_assemblies": len(block_cap_only),
        "block_cap_with_global_pressure_assemblies": len(
            block_cap_with_pressure),
        "window_pressure_drop_assemblies": len(window_drop),
        "no_cut_assemblies": len(no_cut),
        "block_cap_only_truncated_candidates": sum(
            item["outcome"] == "truncated"
            for view in block_cap_only for item in view["candidates"]),
        "global_pressure_truncated_candidates": sum(
            item["outcome"] == "truncated"
            for view in block_cap_with_pressure
            for item in view["candidates"]),
        "window_pressure_dropped_candidates": sum(
            item["outcome"] == "dropped"
            for view in window_drop for item in view["candidates"]),
        "classification_basis": (
            "content-free pre-policy estimated tokens compared with the "
            "declared practical window; classification describes pressure, "
            "not whether a cut was beneficial or harmful"),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persona": persona,
        "window_hours": int(hours),
        "totals": totals,
        "blocks": blocks,
        "cut_pressure": cut_pressure,
        "document_shadow": document_shadow,
        "recent": list(reversed(views[-MAX_RECENT:])),
        "integrity": {
            "malformed_lines": int(malformed),
            "tail_truncated": bool(tail_truncated),
            "privacy": (
                "allowlisted receipt metadata only; prompt text, replies, "
                "digests, memories, and canonical sources excluded"),
            "claim_boundary": (
                "provider return and token accounting do not prove attention "
                "to every submitted element"),
            "recoverability": (
                "Recoverability is not measured by PAC0; canonical owners "
                "remain authoritative"),
        },
    }


def read_prompt_assembly(root, persona, *, hours=24,
                         max_bytes=MAX_READ_BYTES):
    canonical, path = _resolve_receipt_path(root, persona)
    lines, truncated = _bounded_lines(path, max_bytes=max_bytes)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)
              if hours > 0 else None)
    records = []
    malformed = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            malformed += 1
            continue
        stamp = _timestamp(record.get("recorded_at"))
        if cutoff is not None and (stamp is None or stamp < cutoff):
            continue
        if record.get("schema") != "jnsq.prompt_assembly_decision.v0":
            malformed += 1
            continue
        records.append(record)
    return summarize_prompt_assembly(
        records, persona=canonical, hours=hours, malformed=malformed,
        tail_truncated=truncated)
