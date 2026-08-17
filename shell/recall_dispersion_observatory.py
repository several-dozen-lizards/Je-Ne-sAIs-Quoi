"""Read-only summary of persona-private recall dispersion shadows."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os

from core.recall_dispersion import (
    ARM_NAMES,
    LEGACY_SCHEMA,
    PERSISTED_SCHEMA,
    SUPPORTED_SCHEMAS,
)
from shell.prompt_assembly_observatory import available_personas


MAX_READ_BYTES = 4 * 1024 * 1024
MAX_RECENT = 80
RECEIPT_NAME = "recall_dispersion_shadow_receipts.jsonl"


def _timestamp(value):
    try:
        text = str(value).strip().replace("Z", "+00:00")
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


def _resolve_receipt_path(root, persona):
    wanted = str(persona or "").strip().casefold()
    matches = [item["name"] for item in available_personas(root)
               if item["name"].casefold() == wanted]
    if len(matches) != 1:
        raise ValueError("unknown persona")
    canonical = matches[0]
    return canonical, os.path.join(
        os.path.abspath(root), "personas", canonical, "history",
        RECEIPT_NAME)


def _number(value, default=0.0):
    return value if isinstance(value, (int, float)) else default


def _text(value, default="unknown"):
    text = str(value if value is not None else default).strip()
    return text.replace("\r", " ").replace("\n", " ")[:80] or default


def _record_view(record):
    arms = {}
    for name in ARM_NAMES:
        arm = dict(dict(record.get("arms") or {}).get(name) or {})
        arms[name] = {
            "selected_candidate_refs": [str(value)[:20] for value in
                                        list(arm.get(
                                            "selected_candidate_refs") or [])],
            "selected_current_ranks": [int(value) for value in list(
                arm.get("selected_current_ranks") or [])],
            "selected_baseline_ranks": [int(value) for value in list(
                arm.get("selected_baseline_ranks") or [])],
            "selected_count": int(_number(arm.get("selected_count"), 0)),
            "winner_changed_vs_live": bool(
                arm.get("winner_changed_vs_live")),
            "overlap_with_live_count": int(_number(
                arm.get("overlap_with_live_count"), 0)),
            "overlap_with_live_fraction": float(_number(
                arm.get("overlap_with_live_fraction"), 0.0)),
            "mean_current_rank": (
                float(arm["mean_current_rank"])
                if isinstance(arm.get("mean_current_rank"), (int, float))
                else None),
            "normalized_entropy": float(_number(
                arm.get("normalized_entropy"), 0.0)),
            "band_signal": float(_number(
                arm.get("band_signal"),
                _number(arm.get("dispersion_signal"), 0.0))),
            "effective_dispersion": float(_number(
                arm.get("effective_dispersion"),
                _number(arm.get("dispersion_signal"), 0.0))),
            "dispersion_signal": float(_number(
                arm.get("dispersion_signal"), 0.0)),
        }
    memory_block = dict(record.get("memory_block") or {})
    seats = {}
    for name, value in dict(record.get("attention_seats") or {}).items():
        seat = dict(value or {})
        seats[_text(name)] = {
            "group": _text(seat.get("group")),
            "base_budget": int(_number(seat.get("base_budget"), 0)),
            "attention_budget": int(_number(
                seat.get("attention_budget"), 0)),
            "effective_budget": int(_number(
                seat.get("effective_budget"), 0)),
            "supplemental_budget": int(_number(
                seat.get("supplemental_budget"), 0)),
            "rendered": bool(seat.get("rendered")),
            "outcome": _text(seat.get("outcome")),
            "tokens_after": int(_number(seat.get("tokens_after"), 0)),
        }
    admissibility = dict(record.get("admissibility") or {})
    geometry = dict(record.get("score_geometry") or {})
    return {
        "schema": _text(record.get("schema"), "unknown"),
        "cycle_id": _text(record.get("cycle_id"), "missing"),
        "recorded_at": _text(record.get("recorded_at"), "unavailable"),
        "scope": _text(record.get("scope")),
        "mode": _text(record.get("mode")),
        "seed_digest": _text(record.get("seed_digest"), "missing")[:20],
        "candidate_count": int(_number(record.get("candidate_count"), 0)),
        "requested_n": int(_number(record.get("requested_n"), 0)),
        "live_selected_count": int(_number(
            record.get("live_selected_count"), 0)),
        "actual_returned_count": int(_number(
            record.get("actual_returned_count"), 0)),
        "informative": bool(record.get("informative")),
        "score_threshold_used": bool(record.get("score_threshold_used")),
        "admissibility": {
            "claimed_bedrock_excluded_before_scoring": int(_number(
                admissibility.get(
                    "claimed_bedrock_excluded_before_scoring"), 0)),
            "post_recall_defensive_filter_removed": int(_number(
                admissibility.get(
                    "post_recall_defensive_filter_removed"), 0)),
            "comparison_stage": _text(
                admissibility.get("comparison_stage"), "legacy_pre_filter"),
        },
        "score_geometry": {
            "normalization": _text(
                geometry.get("normalization"), "legacy_unavailable"),
            "pool_correction": _text(
                geometry.get("pool_correction"), "legacy_unavailable"),
            "pool_correction_denominator": (
                float(geometry["pool_correction_denominator"])
                if isinstance(geometry.get("pool_correction_denominator"),
                              (int, float)) else None),
            "normalized_winner_gap": (
                float(geometry["normalized_winner_gap"])
                if isinstance(geometry.get("normalized_winner_gap"),
                              (int, float)) else None),
            "normalized_cutoff_gap": (
                float(geometry["normalized_cutoff_gap"])
                if isinstance(geometry.get("normalized_cutoff_gap"),
                              (int, float)) else None),
            "normalized_iqr": (
                float(geometry["normalized_iqr"])
                if isinstance(geometry.get("normalized_iqr"),
                              (int, float)) else None),
        },
        "band_shares": {str(name)[:24]: float(value)
                        for name, value in
                        dict(record.get("band_shares") or {}).items()
                        if isinstance(value, (int, float))},
        "arms": arms,
        "memory_block": {
            "outcome": _text(memory_block.get("outcome"), "absent"),
            "block_budget_tokens": int(_number(
                memory_block.get("block_budget_tokens"), 0)),
            "tokens_after": int(_number(
                memory_block.get("tokens_after"), 0)),
        },
        "attention_seats": seats,
        "live_selection_unchanged": bool(
            record.get("live_selection_unchanged")),
    }


def _mean(values):
    values = [float(value) for value in values
              if isinstance(value, (int, float))]
    return round(sum(values) / len(values), 6) if values else None


def summarize_recall_dispersion(records, *, persona, hours=24,
                                malformed=0, tail_truncated=False):
    all_views = [_record_view(record) for record in records]
    schema_counts = Counter(view["schema"] for view in all_views)
    # Do not average v1's uncorrected stochastic scale into v2. Historical
    # receipts remain counted and inspectable on disk, but current metrics are
    # one experimental contract only.
    views = [view for view in all_views
             if view["schema"] == PERSISTED_SCHEMA]
    arm_summary = {}
    for name in ARM_NAMES:
        arms = [view["arms"][name] for view in views]
        arm_summary[name] = {
            "winner_changes_vs_live": sum(
                arm["winner_changed_vs_live"] for arm in arms),
            "mean_overlap_with_live": _mean([
                arm["overlap_with_live_fraction"] for arm in arms]),
            "mean_normalized_entropy": _mean([
                arm["normalized_entropy"] for arm in arms]),
            "mean_current_rank": _mean([
                arm["mean_current_rank"] for arm in arms]),
            "mean_band_signal": _mean([
                arm["band_signal"] for arm in arms]),
            "mean_effective_dispersion": _mean([
                arm["effective_dispersion"] for arm in arms]),
            "mean_dispersion_signal": _mean([
                arm["dispersion_signal"] for arm in arms]),
        }
    band_names = sorted({name for view in views
                         for name in view["band_shares"]})
    memory_outcomes = Counter(
        view["memory_block"]["outcome"] for view in views)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persona": persona,
        "window_hours": int(hours),
        "current_schema": PERSISTED_SCHEMA,
        "historical": {
            "schema_counts": dict(sorted(schema_counts.items())),
            "legacy_schema": LEGACY_SCHEMA,
            "legacy_receipts_excluded_from_current_metrics": int(
                schema_counts.get(LEGACY_SCHEMA, 0)),
        },
        "totals": {
            "completed_shadow_receipts": len(views),
            "all_supported_receipts": len(all_views),
            "informative_receipts": sum(view["informative"]
                                        for view in views),
            "zero_candidate_receipts": sum(
                view["candidate_count"] == 0 for view in views),
            "live_selection_changed": sum(
                not view["live_selection_unchanged"] for view in views),
            "score_threshold_claims": sum(
                view["score_threshold_used"] for view in views),
            "selection_count_mismatches": sum(
                view["live_selected_count"] != view["actual_returned_count"]
                for view in views),
            "claimed_bedrock_excluded_before_scoring": sum(
                view["admissibility"][
                    "claimed_bedrock_excluded_before_scoring"]
                for view in views),
            "post_recall_defensive_filter_removed": sum(
                view["admissibility"][
                    "post_recall_defensive_filter_removed"]
                for view in views),
            "attention_supplemental_tokens": sum(
                seat["supplemental_budget"] for view in views
                for seat in view["attention_seats"].values()),
            "attention_rendered_blocks": sum(
                seat["rendered"] for view in views
                for seat in view["attention_seats"].values()),
        },
        "memory_block_outcomes": dict(sorted(memory_outcomes.items())),
        "mean_band_shares": {
            name: _mean([view["band_shares"].get(name, 0.0)
                         for view in views]) for name in band_names},
        "mean_score_geometry": {
            key: _mean([view["score_geometry"].get(key)
                        for view in views]) for key in (
                            "pool_correction_denominator",
                            "normalized_winner_gap",
                            "normalized_cutoff_gap",
                            "normalized_iqr")
        },
        "arms": arm_summary,
        "recent": list(reversed(views[-MAX_RECENT:])),
        "integrity": {
            "malformed_lines": int(malformed),
            "tail_truncated": bool(tail_truncated),
            "privacy": (
                "persona-private allowlisted numeric/status metadata and "
                "cycle-salted candidate hashes only; prompt, reply, memory "
                "content and stable memory identity excluded"),
            "causal_readback": False,
            "live_selection_effect": False,
            "claim_boundary": (
                "a shadow difference establishes a counterfactual ranking "
                "difference under one synthetic mapping; it does not establish "
                "benefit, subjective experience, or biological equivalence"),
        },
    }


def read_recall_dispersion(root, persona, *, hours=24,
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
        if record.get("schema") not in SUPPORTED_SCHEMAS:
            malformed += 1
            continue
        records.append(record)
    return summarize_recall_dispersion(
        records, persona=canonical, hours=hours, malformed=malformed,
        tail_truncated=truncated)
