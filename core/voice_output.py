"""Voice output policy and append-only playback receipts.

The speaking vessel owns synthesis.  This module only projects the body's
current continuous state into provider-neutral expression controls and records
what the vessel actually did.  It never tells the persona what to feel.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Mapping


OUTPUT_EVENTS = frozenset({"started", "completed", "interrupted", "failed"})
OUTPUT_PROVIDERS = frozenset({
    "disabled", "browser-native", "qwen3-tts", "chatterbox-turbo",
    "hume-octave", "elevenlabs"})

_ACTION = re.compile(r"<act>.*?</act>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_STAGE_LINE = re.compile(
    r"(?m)^\s*\*[^*\n]{2,600}\*\s*$")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_EMOJI = re.compile(
    "[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\U00002600-\U000027BF]+")


def spoken_text(value: str) -> str:
    """Project visible prose into mouth-safe language.

    The written reply remains untouched.  Private actions, standalone embodied
    stage directions, code blocks, URLs, emoji, and Markdown furniture do not
    become bizarre literal speech.
    """
    text = str(value or "")
    text = _ACTION.sub(" ", text)
    text = _FENCE.sub(" ", text)
    text = _STAGE_LINE.sub(" ", text)
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _URL.sub(" a link ", text)
    text = _EMOJI.sub(" ", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}|[-+>] |\d+[.)] )\s*", "", text)
    text = re.sub(r"[*_~`]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def conversation_text(value: str) -> str:
    """Project a reply into the conversation transcript.

    Embodied stage directions are part of the persona's experienced turn, but
    they are not speech and must not masquerade as chat messages.  Keep the
    full reply in memory; remove only explicit action tags and standalone
    ``*stage direction*`` lines from the user-facing transcript.  Inline
    emphasis remains ordinary written conversation.
    """
    text = _ACTION.sub(" ", str(value or ""))
    text = _STAGE_LINE.sub(" ", text)
    text = re.sub(r"[ \t]*\n{3,}", "\n\n", text)
    return text.strip()


def expression_instruction(policy: Mapping | None,
                           previous: Mapping | None = None) -> tuple[str, dict]:
    """Describe acoustic delivery from the continuous expression vector.

    Recent delivery contributes inertia so a changing body bends the voice
    rather than making it jitter between independent vocal snapshots.
    """
    current = dict((policy or {}).get("vector") or {})
    prior = dict(previous or {})
    vector = {}
    for key in ("energy", "settling", "warmth", "tension", "coherence"):
        now = _clamp(current.get(key, 0.5), 0.0, 1.0)
        before = _clamp(prior.get(key, now), 0.0, 1.0)
        vector[key] = round(.68 * now + .32 * before, 4)
    pace = "unhurried" if vector["settling"] > .62 else \
        "quick but unforced" if vector["energy"] > .62 else "conversational"
    spacing = "with roomy phrase endings" if vector["settling"] > .58 else \
        "with close, connected phrasing"
    force = "light vocal force" if vector["energy"] < .36 else \
        "lively vocal energy" if vector["energy"] > .66 else "moderate vocal energy"
    texture = "soft-edged resonance" if vector["warmth"] > .58 else \
        "clear, neutral resonance"
    stability = "steady breath support" if vector["coherence"] > .62 else \
        "small natural hesitations and unevenness"
    tension = "a little tautness in the phrasing" if vector["tension"] > .58 else \
        "an easy, unstrained throat"
    return (f"Speak as spontaneous private conversation: {pace}, {spacing}, "
            f"{force}, {texture}, {stability}, and {tension}. Preserve "
            "natural contractions, emphasis, and sentence-level melodic continuity. "
            "Do not sound like an announcer, narrator, assistant, or customer-service agent.",
            vector)


def normalize_output_config(value: Mapping | None) -> dict:
    """Return the portable, provider-neutral voice selection.

    Unknown providers fail quiet instead of silently sending speech through a
    different vessel.  ``voice`` is a provider-owned identifier; blank means
    that provider's default voice.
    """
    raw = dict(value or {})
    provider = str(raw.get("provider") or "browser-native").strip()
    if provider not in OUTPUT_PROVIDERS:
        provider = "disabled"
    voice = str(raw.get("voice") or "").strip()
    if len(voice) > 160 or any(char in voice for char in "\r\n"):
        voice = ""
    from shell.voice_settings import normalize_voice_tuning
    auto_play = bool(raw.get("auto_play", provider != "disabled"))
    if provider == "disabled":
        auto_play = False
    return {"provider": provider, "voice": voice, "auto_play": auto_play,
            **normalize_voice_tuning(raw)}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def expression_policy(bands: Mapping | None, cocktail: Mapping | None,
                      coherence: float = 1.0) -> dict:
    """Project the whole live state into gentle synthesis controls.

    The ranges are capability bounds, not emotional labels or fixed band
    presets.  Every oscillator band can influence every subsequent utterance.
    """
    b = dict(bands or {})
    c = dict(cocktail or {})
    coh = _clamp(coherence if coherence is not None else 1.0, 0.0, 1.0)

    energy = _clamp(
        .44 * float(b.get("beta", 0.0))
        + .68 * float(b.get("gamma", 0.0))
        + .22 * float(c.get("curiosity", 0.0))
        + .16 * float(c.get("clarity", 0.0)), 0.0, 1.0)
    settling = _clamp(
        .46 * float(b.get("alpha", 0.0))
        + .38 * float(b.get("theta", 0.0))
        + .24 * float(b.get("delta", 0.0))
        + .22 * coh, 0.0, 1.0)
    warmth = _clamp(
        .45 * float(c.get("warmth", 0.0))
        + .35 * float(c.get("tenderness", 0.0))
        + .20 * float(c.get("joy", 0.0)), 0.0, 1.0)
    tension = _clamp(
        .50 * float(c.get("unease", 0.0))
        + .28 * float(c.get("fear", 0.0))
        + .22 * float(c.get("vulnerability", 0.0)), 0.0, 1.0)

    return {
        "rate": round(_clamp(.96 + .30 * energy - .18 * settling
                             + .06 * tension, .72, 1.30), 4),
        "pitch": round(_clamp(.98
                              + .14 * (float(b.get("gamma", 0.0))
                                       - float(b.get("delta", 0.0)))
                              + .07 * warmth - .05 * tension,
                              .82, 1.18), 4),
        "volume": round(_clamp(.70 + .20 * coh + .10 * energy,
                               .58, 1.0), 4),
        "vector": {
            "energy": round(energy, 4),
            "settling": round(settling, 4),
            "warmth": round(warmth, 4),
            "tension": round(tension, 4),
            "coherence": round(coh, 4),
        },
    }


def append_output_receipt(persona_dir: str, event: Mapping) -> dict:
    """Validate and append one local output event; return the stored record."""
    kind = str(event.get("event") or "")
    if kind not in OUTPUT_EVENTS:
        raise ValueError(f"unknown voice output event: {kind or '<empty>'}")
    record = {
        "tick": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": kind,
        "provider": str(event.get("provider") or "unknown")[:80],
        "reason": str(event.get("reason") or "")[:240],
        "policy": dict(event.get("policy") or {}),
        "evidence": dict(event.get("evidence") or {}),
    }
    history = os.path.join(persona_dir, "history")
    os.makedirs(history, exist_ok=True)
    path = os.path.join(history, "voice_output.jsonl")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
