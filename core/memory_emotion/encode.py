"""Encode-side importance: WHAT'S KEPT.
Ports v1 _calculate_turn_importance faithfully (V1_AUDIT 7.6), including
"Love as Meaning-Making": bond strength to involved entities multiplies
importance. Love is the worth-keeping filter. Names parameterized (B2 fix)."""
import re


def calc_importance(content: str, *, emotional_snapshot: dict,
                    entities: list, bonds: dict,
                    base: float = 0.5, list_boost_threshold: int = 3) -> tuple:
    """Returns (importance, trace) — trace is the receipt (observability law).

    bonds: {entity_name: bond_strength 0..1} from the persona's own config.
    """
    trace = []
    importance = base

    # Multi-entity boost (v1: lists of 3+ entities matter)
    if len(entities) >= list_boost_threshold:
        importance = max(importance, 0.9)
        trace.append(f"list_boost: {len(entities)} entities -> {importance:.2f}")

    # Emotional intensity boost (v1: avg intensity * 0.1)
    if emotional_snapshot:
        avg = sum(emotional_snapshot.values()) / max(len(emotional_snapshot), 1)
        importance += avg * 0.1
        trace.append(f"emotion_intensity: avg={avg:.2f} -> +{avg * 0.1:.3f}")

    # LOVE AS MEANING-MAKING (v1 Layer 4, ported in spirit, B4 FIXED):
    # strongest bonded entity involved multiplies importance once.
    # B4: v1 used substring matching ("Re" matched inside "spare") which
    # fired the love filter spuriously. Word-boundary match required.
    def _mentioned(name: str) -> bool:
        return bool(re.search(rf"\b{re.escape(name)}\b", content, re.IGNORECASE))

    involved = [(e, b) for e, b in bonds.items()
                if b > 0.10 and (e in entities or _mentioned(e))]
    if involved:
        entity, bond = max(involved, key=lambda x: x[1])
        mult = 1.0 + bond
        importance *= mult
        trace.append(f"love_multiplier: {entity} bond={bond:.2f} -> x{mult:.2f}")

    importance = min(importance, 1.0)
    trace.append(f"final={importance:.3f}")
    return importance, trace
