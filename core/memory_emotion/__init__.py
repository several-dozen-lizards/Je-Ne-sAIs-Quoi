"""memory_emotion — the core organ. Memory and emotion as ONE unit.

The triad (excavated from v1, V1_AUDIT 7.6/7.7):
  1. WHAT'S KEPT    — encode importance: emotional intensity + love multiplier
  2. WHAT SURFACES  — recall scoring: emotional resonance dominant (default 40%)
  3. WHAT SURVIVES  — decay: emotion tags + bonded entities extend halflife

v1 bugs fixed in this port (V1_AUDIT 7.6 B1-B3):
  B1: entity matching is case-correct against declared entities
  B2: NO hardcoded names — entities/bonds come from the persona's own config
  B3: "recency" split honestly: familiarity (access freq) + recency (age)

Laws honored: per-persona data only (no shared emotional state, ever);
schema_version on disk (par 2.2a); every recall returns its score breakdown
(observability); archived, never silently deleted (comment-out principle).
"""
SCHEMA_VERSION = 1

from .organ import MemoryEmotionOrgan  # noqa: F401
