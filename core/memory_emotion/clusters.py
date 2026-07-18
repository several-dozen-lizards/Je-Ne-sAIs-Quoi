"""Read-only local episodic neighborhoods for offline narrative appraisal.

Geometry proposes who may be considered together.  It never declares a
cluster, changes source records, increments recall counts, or calls a model.
"""
from __future__ import annotations

import math
import statistics


EPISODIC_TYPES = frozenset({"turn", "observed", "wandering"})


def derived_width(count: int) -> int:
    """A local rank width that moves with the admitted cohort."""
    count = max(0, int(count))
    return math.ceil(math.log2(count)) if count > 1 else 0


def eligible_episodics(memories, working_ids=()) -> list[dict]:
    """Project the canonical episodic cohort in stable corpus order."""
    working = {str(memory_id) for memory_id in working_ids}
    return [memory for memory in memories
            if memory.get("type") in EPISODIC_TYPES
            and memory.get("layer") != "archived"
            and str(memory.get("id")) not in working
            and not (memory.get("fields") or {}).get("is_bedrock")]


def project_local_neighborhood(memories, vectors, context_cues, seed_id: str,
                               working_ids=()) -> dict:
    """Union semantic and explicit-context neighbors around one seed.

    Context is optional evidence from ``context_at_encoding`` only.  Legacy
    episodes remain fully eligible through the semantic channel.
    """
    cohort = eligible_episodics(memories, working_ids=working_ids)
    by_id = {str(memory.get("id")): memory for memory in cohort}
    seed_id = str(seed_id)
    seed = by_id.get(seed_id)
    if seed is None:
        return {
            "status": "unavailable", "reason": "seed_not_eligible",
            "seed_id": seed_id, "eligible_count": len(cohort),
            "candidate_ids": [],
        }

    eligible_ids = [str(memory.get("id")) for memory in cohort]
    semantic_width = derived_width(len(cohort))
    semantic_rows, vector_covered = vectors.neighbors_for_id(
        seed_id, eligible_ids, semantic_width)
    semantic_ids = [memory_id for memory_id, _score in semantic_rows]
    semantic_scores = [score for _memory_id, score in semantic_rows]

    explicit_ids = [str(memory.get("id")) for memory in cohort
                    if isinstance(memory.get("context_at_encoding"), dict)]
    context_width = (derived_width(len(explicit_ids))
                     if isinstance(seed.get("context_at_encoding"), dict)
                     else 0)
    context_ids, context_covered = [], len(explicit_ids)
    if context_width and context_cues is not None:
        ranked, measured_coverage = context_cues.top_k_with_coverage(
            seed["context_at_encoding"], explicit_ids, context_width + 1)
        context_ids = [memory_id for memory_id in ranked
                       if memory_id != seed_id][:context_width]
        context_covered = measured_coverage

    candidate_ids = [seed_id]
    for memory_id in semantic_ids + context_ids:
        if memory_id not in candidate_ids:
            candidate_ids.append(memory_id)

    return {
        "status": "ready",
        "seed_id": seed_id,
        "eligible_count": len(cohort),
        "vector_covered": vector_covered + (1 if seed_id in vectors.row else 0),
        "explicit_context_covered": context_covered,
        "semantic_width": semantic_width,
        "context_width": context_width,
        "semantic_ids": semantic_ids,
        "context_ids": context_ids,
        "candidate_ids": candidate_ids,
        "semantic_locality": (
            float(statistics.median(semantic_scores))
            if semantic_scores else None),
        "channel_overlap": len(set(semantic_ids) & set(context_ids)),
    }
