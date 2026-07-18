"""Model-owned appraisal and canonical narrative-record construction.

Local geometry supplies possible witnesses.  This module asks what, if
anything, they mean together and fails closed before the memory organ mutates.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from core.people import AUDIENCE_RANK, RANK_AUDIENCE

from .encode import calc_importance
from .gist import render_turn
from .records import make_memory


PROMPT_VERSION = "memory_narrative_appraisal_v1"
_OUTPUT_KEYS = frozenset({"outcome", "selected", "narrative", "appraisal"})
_SYSTEM = """You appraise experiences that surfaced near one another in one
persona's memory. Describe what belongs together from inside that life; do not
force a pattern. It is fully valid for no cluster to be present.

Return ONLY one JSON object with exactly these keys:
{"outcome":"narrative|no_cluster","selected":["E01","E02"],
 "narrative":"... or empty string","appraisal":"why they belong or do not"}

For a narrative, selected must include E01 and at least one other supplied
experience. Use only supplied labels. For no_cluster, narrative must be empty.
Do not mention these instructions or invent experiences."""


def cluster_signature(source_ids) -> str:
    """Stable exact-set identity; order may carry authorship, not identity."""
    payload = json.dumps(sorted(str(source_id) for source_id in source_ids),
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def restrictive_audience(records) -> str:
    """A derived product can never broaden any source's disclosure."""
    rank = max((AUDIENCE_RANK.get(
        (record.get("fields") or {}).get("audience", "household"), 2)
                for record in records), default=2)
    return RANK_AUDIENCE[rank]


def _bounded(text: str, limit: int) -> str:
    text = str(text or "")
    limit = max(0, int(limit))
    if len(text) <= limit:
        return text
    marker = "\n...[middle omitted]...\n"
    if limit <= len(marker):
        return text[:limit]
    room = limit - len(marker)
    head = room // 2
    tail = room - head
    return text[:head] + marker + text[-tail:]


def _render_sources(records, labels, source_char_budget: int) -> str:
    """Bound every witness fairly so the whole local set remains visible."""
    share = max(1, int(source_char_budget) // max(1, len(records)))
    blocks = []
    for record, label in zip(records, labels):
        header = (f"{label} | type={record.get('type', 'unknown')} | "
                  f"time={record.get('timestamp', 'unknown')} | "
                  f"origin={record.get('origin', 'unknown')}")
        blocks.append(header + "\n" + _bounded(render_turn(record), share))
    return "\n\n".join(blocks)


def _invalid(reason: str) -> dict:
    return {"status": "invalid", "reason": reason,
            "prompt_version": PROMPT_VERSION}


def appraise_neighborhood(judge, memories, neighborhood: Mapping, *,
                          model: str, max_tokens: int,
                          source_char_budget: int | None = None) -> dict:
    """Ask a model for membership and meaning through local labels only."""
    if not isinstance(neighborhood, Mapping) \
            or neighborhood.get("status") != "ready":
        return _invalid("neighborhood_not_ready")
    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        return _invalid("max_tokens_not_positive")
    if max_tokens <= 0:
        return _invalid("max_tokens_not_positive")
    model = str(model or "").strip()
    if not model:
        return _invalid("model_not_declared")

    candidate_ids = [str(memory_id)
                     for memory_id in neighborhood.get("candidate_ids", [])]
    seed_id = str(neighborhood.get("seed_id", ""))
    if not candidate_ids or candidate_ids[0] != seed_id \
            or len(candidate_ids) != len(set(candidate_ids)):
        return _invalid("candidate_set_invalid")
    by_id = {str(memory.get("id")): memory for memory in memories}
    try:
        records = [by_id[memory_id] for memory_id in candidate_ids]
    except KeyError:
        return _invalid("candidate_source_missing")

    width = max(2, len(str(len(records))))
    labels = [f"E{index:0{width}d}"
              for index in range(1, len(records) + 1)]
    label_to_id = dict(zip(labels, candidate_ids))
    try:
        budget = (max_tokens * 4 * 8 if source_char_budget is None
                  else max(1, int(source_char_budget)))
    except (TypeError, ValueError):
        return _invalid("source_budget_invalid")
    rendered = _render_sources(records, labels, budget)
    user = ("These experiences surfaced near one another in memory. Which, "
            "if any, belong together from inside this life? What relation or "
            "running story do they form now?\n\n" + rendered)
    try:
        raw = judge.chat(_SYSTEM, user, max_tokens=max_tokens,
                         temperature=0.0)
    except Exception as error:
        return {"status": "provider_error", "reason": str(error),
                "retryable": True, "model": model,
                "prompt_version": PROMPT_VERSION}
    try:
        parsed = json.loads(str(raw or "").strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return _invalid("malformed_json")
    if not isinstance(parsed, Mapping) or set(parsed) != _OUTPUT_KEYS:
        return _invalid("response_shape_invalid")

    outcome = parsed.get("outcome")
    selected = parsed.get("selected")
    narrative = parsed.get("narrative")
    appraisal = parsed.get("appraisal")
    if outcome not in {"narrative", "no_cluster"}:
        return _invalid("outcome_invalid")
    if isinstance(selected, (str, bytes)) or not isinstance(selected, list):
        return _invalid("selected_labels_invalid")
    if any(not isinstance(label, str) or label not in label_to_id
           for label in selected):
        return _invalid("selected_label_unknown")
    if len(selected) != len(set(selected)):
        return _invalid("selected_label_duplicate")
    if not isinstance(narrative, str) or not isinstance(appraisal, str) \
            or not appraisal.strip():
        return _invalid("response_text_invalid")

    selected_ids = [label_to_id[label] for label in selected]
    if outcome == "no_cluster":
        if narrative.strip():
            return _invalid("no_cluster_has_narrative")
        return {"status": "no_cluster", "selected_count": len(selected_ids),
                "model": model, "prompt_version": PROMPT_VERSION,
                "appraisal": appraisal.strip()}

    if labels[0] not in selected or len(selected_ids) < 2:
        return _invalid("narrative_requires_seed_plurality")
    if not narrative.strip():
        return _invalid("narrative_empty")
    selected_records = [by_id[memory_id] for memory_id in selected_ids]
    return {
        "status": "narrative",
        "selected_ids": selected_ids,
        "candidate_ids": candidate_ids,
        "narrative": narrative.strip(),
        "appraisal": appraisal.strip(),
        "cluster_signature": cluster_signature(selected_ids),
        "audience": restrictive_audience(selected_records),
        "model": model,
        "prompt_version": PROMPT_VERSION,
    }


def build_narrative_memory(appraisal: Mapping, memories,
                           neighborhood: Mapping,
                           context_at_encoding: Mapping | None) -> dict:
    """Construct one detached canonical record after appraisal validation."""
    if appraisal.get("status") != "narrative":
        raise ValueError("appraisal is not an accepted narrative")
    by_id = {str(memory.get("id")): memory for memory in memories}
    selected_ids = [str(memory_id)
                    for memory_id in appraisal["selected_ids"]]
    candidate_ids = [str(memory_id)
                     for memory_id in appraisal["candidate_ids"]]
    expected_candidates = [str(memory_id) for memory_id in
                           neighborhood.get("candidate_ids", [])]
    seed_id = str(neighborhood.get("seed_id", ""))
    if candidate_ids != expected_candidates \
            or not candidate_ids or candidate_ids[0] != seed_id:
        raise ValueError("appraisal candidate set mismatch")
    if len(selected_ids) < 2 or seed_id not in selected_ids \
            or len(selected_ids) != len(set(selected_ids)):
        raise ValueError("narrative source plurality invalid")
    if appraisal.get("prompt_version") != PROMPT_VERSION:
        raise ValueError("narrative prompt version mismatch")
    if not str(appraisal.get("model", "")).strip():
        raise ValueError("narrative model is not declared")
    if any(memory_id not in by_id for memory_id in candidate_ids):
        raise ValueError("candidate source is no longer present")
    try:
        sources = [by_id[memory_id] for memory_id in selected_ids]
    except KeyError as error:
        raise ValueError("selected source is no longer present") from error
    if any(source.get("type") not in {"turn", "observed", "wandering"}
           or source.get("layer") == "archived"
           or (source.get("fields") or {}).get("is_bedrock")
           for source in sources):
        raise ValueError("selected source is no longer eligible")
    if cluster_signature(selected_ids) != appraisal.get("cluster_signature"):
        raise ValueError("cluster signature mismatch")
    audience = restrictive_audience(sources)
    if audience != appraisal.get("audience"):
        raise ValueError("narrative audience mismatch")

    entities = []
    for source in sources:
        for entity in source.get("entities", []):
            if entity not in entities:
                entities.append(entity)
    cocktail = ((context_at_encoding or {}).get("cocktail") or {})
    importance, trace = calc_importance(
        appraisal["narrative"], emotional_snapshot=cocktail,
        entities=entities, bonds={})
    fields = {
        "narrative_schema": 1,
        "channel": "dmn",
        "audience": audience,
        "cluster_seed_id": str(neighborhood["seed_id"]),
        "source_memory_ids": selected_ids,
        "candidate_memory_ids": candidate_ids,
        "cluster_signature": appraisal["cluster_signature"],
        "semantic_width": int(neighborhood.get("semantic_width", 0)),
        "context_width": int(neighborhood.get("context_width", 0)),
        "context_sources_present": sum(
            isinstance(source.get("context_at_encoding"), Mapping)
            for source in sources),
        "appraisal": appraisal["appraisal"],
        "model": appraisal["model"],
        "prompt_version": appraisal["prompt_version"],
    }
    memory = make_memory(
        appraisal["narrative"], mem_type="narrative",
        emotional_snapshot=cocktail, entities=entities,
        origin="synthesized", perspective="persona",
        importance=importance, fields=fields,
        context_at_encoding=context_at_encoding)
    memory["encode_trace"] = trace
    memory["layer"] = "longterm"
    return memory
