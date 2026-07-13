"""Recall-side scoring: WHAT SURFACES.
Ports v1 _calculate_base_score (V1_AUDIT 7.6) with weights as per-persona
substrate config and the honest factor split (B3 fix). Emotional resonance
stays the dominant factor by default — mood-congruent recall is the PRIMARY
mechanism, not an add-on."""
import math
import re

DEFAULT_WEIGHTS = {
    "emotion": 0.40,      # current cocktail vs memory emotion_tags (v1: 40%)
    "semantic": 0.25,     # keyword overlap (embedding hook later)
    "importance": 0.20,   # encode-time importance (itself love-weighted)
    "familiarity": 0.05,  # access frequency (v1 mislabeled this "recency")
    "recency": 0.05,      # TRUE recency: age-based (new, honest)
    "entity": 0.05,       # shared declared entities (B1/B2 fixed)
}


def score_memory(mem: dict, *, query: str, cocktail: dict,
                 known_entities: list, weights: dict = None,
                 mem_age_days: float = 0.0,
                 semantic_override: float = None) -> tuple:
    """Returns (score, breakdown). Breakdown ships with every recall.
    semantic_override: cosine from the vector sidecar (v1 embedding
    parity, 2026-07-12) — when None, keyword overlap is the fallback."""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    # 1. emotional resonance: how much the CURRENT mood lights this memory up
    emotion = sum(cocktail.get(tag, 0.0) for tag in mem.get("emotion_tags", []))

    # 2. semantic: vector cosine when the sidecar has this record;
    # keyword overlap otherwise (v0 behavior, receipted as fallback)
    if semantic_override is not None:
        semantic = semantic_override
    else:
        q_words = set(re.findall(r"\w+", query.lower()))
        blob = mem.get("content", "").lower()
        semantic = (sum(1 for wd in q_words if wd in blob) / len(q_words)) if q_words else 0.0

    # 3. importance (encode-side product of the love filter)
    importance = mem.get("importance", 0.0)

    # 4. familiarity: well-trodden memories (named honestly now)
    familiarity = min(mem.get("access_count", 0) / 10.0, 1.0)

    # 5. recency: exponential falloff, ~30-day scale
    recency = math.exp(-mem_age_days / 30.0)

    # 6. entity proximity: case-correct match of DECLARED entities in the query
    q_lower = query.lower()
    q_entities = {e for e in known_entities if e.lower() in q_lower}
    m_entities = set(mem.get("entities", []))
    entity = (len(q_entities & m_entities) / len(q_entities)) if q_entities else 0.0

    parts = {"emotion": emotion, "semantic": semantic, "importance": importance,
             "familiarity": familiarity, "recency": recency, "entity": entity}
    score = sum(parts[k] * w[k] for k in parts)
    breakdown = {k: round(parts[k] * w[k], 4) for k in parts}
    breakdown["total"] = round(score, 4)
    return score, breakdown
