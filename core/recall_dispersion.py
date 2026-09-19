"""Content-free, shadow-only counterfactuals for recall dispersion.

The oscillator band names used here are synthetic control aliases.  This
module tests one candidate relationship -- more dispersion as the configured
``theta`` component rises -- without claiming physiology or prescribing an
experience.  It cannot select live memories: callers receive metrics and
ephemeral hashes only.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import os
from typing import Any, Mapping, Sequence


LEGACY_SCHEMA = "jnaiq.recall_dispersion_shadow.v1"
PERSISTED_SCHEMA = "jnaiq.recall_dispersion_shadow.v2"
SUPPORTED_SCHEMAS = (LEGACY_SCHEMA, PERSISTED_SCHEMA)
ARM_NAMES = (
    "band_weighted_deterministic",
    "unmodulated_deterministic",
    "theta_conditioned_dispersion",
    "mismatched_beta_dispersion",
)
BAND_KEYS = ("delta", "theta", "alpha", "beta", "gamma")


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _unit(value: Any) -> float:
    return max(0.0, min(1.0, _finite(value)))


def _band_shares(bands: Mapping[str, Any] | None) -> dict:
    values = {
        str(name): max(0.0, _finite(value))
        for name, value in dict(bands or {}).items()
    }
    total = sum(values.values())
    if total <= 1e-12:
        return {name: 0.0 for name in sorted(values)}
    return {name: round(value / total, 9)
            for name, value in sorted(values.items())}


def _seed(cycle_id: str) -> bytes:
    material = (PERSISTED_SCHEMA + "\x00" + str(cycle_id)).encode("utf-8")
    return hashlib.sha256(material).digest()


def _candidate_hash(seed: bytes, reference: str) -> str:
    return hashlib.sha256(
        seed + b"\x00candidate\x00" + str(reference).encode("utf-8")
    ).hexdigest()[:20]


def _common_gumbel(seed: bytes, reference: str) -> float:
    digest = hashlib.sha256(
        seed + b"\x00common-noise\x00" + str(reference).encode("utf-8")
    ).digest()
    integer = int.from_bytes(digest[:8], "big")
    uniform = (integer + 0.5) / (2 ** 64)
    return -math.log(-math.log(uniform))


def _normalized_scores(rows: Sequence[dict], key: str) -> dict:
    values = [_finite(row.get(key)) for row in rows]
    if not values:
        return {}
    low, high = min(values), max(values)
    if high - low <= 1e-12:
        return {row["reference"]: 0.0 for row in rows}
    return {
        row["reference"]: (value - low) / (high - low)
        for row, value in zip(rows, values)
    }


def _entropy(normalized: Mapping[str, float], dispersion: float) -> float:
    if not normalized or dispersion <= 1e-12:
        return 0.0
    logits = [value / dispersion for value in normalized.values()]
    peak = max(logits)
    weights = [math.exp(value - peak) for value in logits]
    total = sum(weights)
    probabilities = [value / total for value in weights]
    entropy = -sum(p * math.log(p) for p in probabilities if p > 0.0)
    ceiling = math.log(len(probabilities))
    return round(entropy / ceiling, 9) if ceiling > 0.0 else 0.0


def _rank(rows: Sequence[dict], score_key: str) -> list:
    return sorted(rows, key=lambda row: (
        -_finite(row.get(score_key)), int(row.get("ordinal") or 0)))


def _dispersed_rank(rows: Sequence[dict], normalized: Mapping[str, float],
                    dispersion: float, seed: bytes) -> list:
    if dispersion <= 1e-12:
        return _rank(rows, "current_score")
    return sorted(rows, key=lambda row: (
        -(normalized[row["reference"]] / dispersion
          + _common_gumbel(seed, row["reference"])),
        int(row.get("ordinal") or 0),
    ))


def _select_with_bedrock(ranked: Sequence[dict], requested_n: int) -> list:
    """Mirror the live named-bedrock seat without touching live selection."""
    count = max(0, int(requested_n))
    selected = list(ranked[:count])
    if not selected or any(row.get("named_bedrock") for row in selected):
        return selected
    replacement = next((row for row in ranked[count:]
                        if row.get("named_bedrock")), None)
    if replacement is not None:
        selected[-1] = replacement
    return selected


def _arm_view(name: str, ranked: Sequence[dict], requested_n: int,
              current_rank: Mapping[str, int], baseline_rank: Mapping[str, int],
              live_refs: Sequence[str], hashes: Mapping[str, str],
              band_signal: float, dispersion: float, entropy: float) -> dict:
    selected = _select_with_bedrock(ranked, requested_n)
    refs = [row["reference"] for row in selected]
    live_set = set(live_refs)
    overlap = sum(reference in live_set for reference in refs)
    denominator = max(1, min(len(live_refs), len(refs)))
    winner = refs[0] if refs else None
    live_winner = live_refs[0] if live_refs else None
    return {
        "name": name,
        "selected_candidate_refs": [hashes[reference]
                                    for reference in refs],
        "selected_current_ranks": [current_rank[reference]
                                   for reference in refs],
        "selected_baseline_ranks": [baseline_rank[reference]
                                    for reference in refs],
        "selected_count": len(refs),
        "winner_changed_vs_live": bool(winner != live_winner),
        "overlap_with_live_count": overlap,
        "overlap_with_live_fraction": round(overlap / denominator, 9),
        "mean_current_rank": (round(sum(current_rank[reference]
                                             for reference in refs)
                                        / len(refs), 6)
                              if refs else None),
        "normalized_entropy": round(_unit(entropy), 9),
        "band_signal": round(_unit(band_signal), 9),
        "effective_dispersion": round(_unit(dispersion), 9),
        # Compatibility name for older summary clients. In v2 this is the
        # pool-corrected value, not the raw band share.
        "dispersion_signal": round(_unit(dispersion), 9),
    }


def _quantile(values: Sequence[float], fraction: float) -> float | None:
    ordered = sorted(_finite(value) for value in values)
    if not ordered:
        return None
    position = _unit(fraction) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _score_geometry(current: Sequence[dict], normalized: Mapping[str, float],
                    requested_n: int, correction: float) -> dict:
    ranked = [normalized[row["reference"]] for row in current]
    selected = min(max(0, int(requested_n)), len(ranked))
    winner_gap = (ranked[0] - ranked[1] if len(ranked) > 1 else None)
    cutoff_gap = (ranked[selected - 1] - ranked[selected]
                  if selected > 0 and selected < len(ranked) else None)
    q25 = _quantile(ranked, .25)
    q75 = _quantile(ranked, .75)
    return {
        "normalization": "candidate_min_max_0_1",
        "pool_correction": "max_1_log1p_candidate_count",
        "pool_correction_denominator": round(correction, 9),
        "normalized_winner_gap": (
            round(max(0.0, winner_gap), 9)
            if winner_gap is not None else None),
        "normalized_cutoff_gap": (
            round(max(0.0, cutoff_gap), 9)
            if cutoff_gap is not None else None),
        "normalized_iqr": (
            round(max(0.0, q75 - q25), 9)
            if q25 is not None and q75 is not None else None),
    }


def build_recall_dispersion_shadow(
        rows: Sequence[Mapping[str, Any]], *, requested_n: int,
        bands: Mapping[str, Any] | None, cycle_id: str,
        pre_excluded_claimed_bedrock_count: int = 0) -> dict:
    """Replay already-eligible scored candidates through four shadow arms.

    Each input row needs an internal ``reference``, current and unmodulated
    scores, and may mark ``named_bedrock``.  References never leave this
    function; persisted selections use hashes salted to this one cycle.
    """
    clean = []
    for ordinal, source in enumerate(rows):
        row = dict(source or {})
        reference = str(row.get("reference") or "")
        if not reference:
            continue
        clean.append({
            "reference": reference,
            "current_score": _finite(row.get("current_score")),
            "baseline_score": _finite(row.get("baseline_score")),
            "named_bedrock": bool(row.get("named_bedrock")),
            "ordinal": int(row.get("ordinal", ordinal)),
        })

    seed = _seed(cycle_id)
    seed_digest = hashlib.sha256(seed).hexdigest()[:20]
    hashes = {row["reference"]: _candidate_hash(seed, row["reference"])
              for row in clean}
    current = _rank(clean, "current_score")
    baseline = _rank(clean, "baseline_score")
    current_rank = {row["reference"]: index + 1
                    for index, row in enumerate(current)}
    baseline_rank = {row["reference"]: index + 1
                     for index, row in enumerate(baseline)}
    live = _select_with_bedrock(current, requested_n)
    live_refs = [row["reference"] for row in live]
    normalized = _normalized_scores(clean, "current_score")
    shares = _band_shares(bands)
    theta_signal = _unit(shares.get("theta", 0.0))
    mismatch_signal = _unit(shares.get("beta", 0.0))
    candidate_count = len(clean)
    correction = max(1.0, math.log1p(candidate_count))
    theta_dispersion = theta_signal / correction
    mismatch_dispersion = mismatch_signal / correction

    arm_rankings = {
        "band_weighted_deterministic": (current, 0.0, 0.0, 0.0),
        "unmodulated_deterministic": (baseline, 0.0, 0.0, 0.0),
        "theta_conditioned_dispersion": (
            _dispersed_rank(clean, normalized, theta_dispersion, seed),
            theta_signal, theta_dispersion,
            _entropy(normalized, theta_dispersion)),
        "mismatched_beta_dispersion": (
            _dispersed_rank(clean, normalized, mismatch_dispersion, seed),
            mismatch_signal, mismatch_dispersion,
            _entropy(normalized, mismatch_dispersion)),
    }
    arms = {
        name: _arm_view(name, ranking, requested_n, current_rank,
                        baseline_rank, live_refs, hashes, band_signal,
                        dispersion, entropy)
        for name, (ranking, band_signal, dispersion, entropy)
        in arm_rankings.items()
    }
    selected_count = len(live_refs)
    return {
        "schema": PERSISTED_SCHEMA,
        "schema_version": 2,
        "mode": "shadow_only_no_selection_effect",
        "scope": "persona_private",
        "cycle_id": str(cycle_id)[:80],
        "seed_digest": seed_digest,
        "candidate_count": candidate_count,
        "requested_n": max(0, int(requested_n)),
        "live_selected_count": selected_count,
        "informative": candidate_count > selected_count > 0,
        "score_threshold_used": False,
        "admissibility": {
            "claimed_bedrock_excluded_before_scoring": max(
                0, int(pre_excluded_claimed_bedrock_count)),
            "comparison_stage": "final_recall_admissible_candidates",
        },
        "band_shares": shares,
        "score_geometry": _score_geometry(
            current, normalized, requested_n, correction),
        "dispersion_mapping": {
            "intended": (
                "normalized_theta_share_divided_by_"
                "max_1_log1p_candidate_count"),
            "mismatched_control": (
                "normalized_beta_share_divided_by_"
                "max_1_log1p_candidate_count"),
            "common_random_variates": True,
        },
        "arms": arms,
        "live_selection_unchanged": True,
        "downstream_channels_touched": [],
        "integrity": {
            "candidate_references": "cycle_salted_hashes",
            "content_present": False,
            "causal_readback": False,
            "synthetic_analogue_boundary": True,
        },
    }


def _optional_geometry_value(source: Mapping[str, Any], key: str):
    value = dict(source.get("score_geometry") or {}).get(key)
    if value is None:
        return None
    return round(max(0.0, _finite(value)), 9)


def finalize_recall_dispersion_shadow(
        receipt: Mapping[str, Any] | None, *,
        actual_returned_count: int,
        post_filter_removed_count: int = 0,
        memory_block: Mapping[str, Any] | None = None,
        attention_seats: Mapping[str, Any] | None = None,
        recorded_at: str | None = None) -> dict | None:
    """Strict allowlist for a completed-turn private observer receipt."""
    if not receipt or receipt.get("schema") != PERSISTED_SCHEMA:
        return None
    source = dict(receipt)
    arm_source = dict(source.get("arms") or {})
    arms = {}
    for name in ARM_NAMES:
        arm = dict(arm_source.get(name) or {})
        arms[name] = {
            "selected_candidate_refs": [str(value)[:20] for value in
                                        list(arm.get(
                                            "selected_candidate_refs") or [])],
            "selected_current_ranks": [max(1, int(value)) for value in
                                       list(arm.get(
                                           "selected_current_ranks") or [])],
            "selected_baseline_ranks": [max(1, int(value)) for value in
                                        list(arm.get(
                                            "selected_baseline_ranks") or [])],
            "selected_count": max(0, int(arm.get("selected_count") or 0)),
            "winner_changed_vs_live": bool(
                arm.get("winner_changed_vs_live")),
            "overlap_with_live_count": max(
                0, int(arm.get("overlap_with_live_count") or 0)),
            "overlap_with_live_fraction": round(_unit(
                arm.get("overlap_with_live_fraction")), 9),
            "mean_current_rank": (
                round(_finite(arm.get("mean_current_rank")), 6)
                if arm.get("mean_current_rank") is not None else None),
            "normalized_entropy": round(_unit(
                arm.get("normalized_entropy")), 9),
            "band_signal": round(_unit(
                arm.get("band_signal")), 9),
            "effective_dispersion": round(_unit(
                arm.get("effective_dispersion") or
                arm.get("dispersion_signal")), 9),
            "dispersion_signal": round(_unit(
                arm.get("dispersion_signal")), 9),
        }
    block = dict(memory_block or {})
    seat_source = dict(attention_seats or {})
    seats = {}
    for name, value in seat_source.items():
        seat = dict(value or {})
        seats[str(name)[:80]] = {
            "group": str(seat.get("group") or "unknown")[:24],
            "base_budget": max(0, int(seat.get("base_budget") or 0)),
            "attention_budget": max(
                0, int(seat.get("attention_budget") or
                       seat.get("effective_budget") or
                       seat.get("budget") or 0)),
            "effective_budget": max(
                0, int(seat.get("effective_budget") or
                       seat.get("budget") or 0)),
            "supplemental_budget": max(
                0, int(seat.get("supplemental_budget") or 0)),
            "rendered": bool(seat.get("rendered")),
            "outcome": str(seat.get("outcome") or "unknown")[:40],
            "tokens_after": max(0, int(seat.get("tokens_after") or 0)),
        }
    return {
        "schema": PERSISTED_SCHEMA,
        "schema_version": 2,
        "cycle_id": str(source.get("cycle_id") or "missing")[:80],
        "recorded_at": recorded_at or datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "scope": "persona_private",
        "mode": "observer_only_no_readback",
        "seed_digest": str(source.get("seed_digest") or "")[:20],
        "candidate_count": max(0, int(source.get("candidate_count") or 0)),
        "requested_n": max(0, int(source.get("requested_n") or 0)),
        "live_selected_count": max(
            0, int(source.get("live_selected_count") or 0)),
        "actual_returned_count": max(0, int(actual_returned_count)),
        "informative": bool(source.get("informative")),
        "score_threshold_used": False,
        "admissibility": {
            "claimed_bedrock_excluded_before_scoring": max(
                0, int(dict(source.get("admissibility") or {}).get(
                    "claimed_bedrock_excluded_before_scoring") or 0)),
            "post_recall_defensive_filter_removed": max(
                0, int(post_filter_removed_count)),
            "comparison_stage": "final_recall_admissible_candidates",
        },
        "band_shares": {
            name: round(_unit(
                dict(source.get("band_shares") or {}).get(name)), 9)
            for name in BAND_KEYS},
        "dispersion_mapping": {
            "intended": (
                "normalized_theta_share_divided_by_"
                "max_1_log1p_candidate_count"),
            "mismatched_control": (
                "normalized_beta_share_divided_by_"
                "max_1_log1p_candidate_count"),
            "common_random_variates": True,
        },
        "score_geometry": {
            "normalization": "candidate_min_max_0_1",
            "pool_correction": "max_1_log1p_candidate_count",
            "pool_correction_denominator": round(max(
                1.0, _finite(dict(source.get("score_geometry") or {}).get(
                    "pool_correction_denominator"), 1.0)), 9),
            "normalized_winner_gap": _optional_geometry_value(
                source, "normalized_winner_gap"),
            "normalized_cutoff_gap": _optional_geometry_value(
                source, "normalized_cutoff_gap"),
            "normalized_iqr": _optional_geometry_value(
                source, "normalized_iqr"),
        },
        "arms": arms,
        "memory_block": {
            "outcome": str(block.get("outcome") or "absent")[:40],
            "block_budget_tokens": max(
                0, int(block.get("block_budget_tokens") or 0)),
            "tokens_after": max(0, int(block.get("tokens_after") or 0)),
        },
        "attention_seats": seats,
        "live_selection_unchanged": True,
        "downstream_channels_touched": [],
        "integrity": {
            "content_excluded": [
                "prompt", "reply", "memory_content", "memory_identity",
                "source_text", "resident_description",
            ],
            "candidate_references": "cycle_salted_hashes",
            "causal_readback": False,
            "synthetic_analogue_boundary": True,
        },
    }


def append_recall_dispersion_receipt(path: str,
                                     receipt: Mapping[str, Any] | None) -> bool:
    if not receipt:
        return False
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    payload = json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True
