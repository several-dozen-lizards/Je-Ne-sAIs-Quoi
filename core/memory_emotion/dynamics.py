"""Emotion dynamics: the RETURN HALF of the bidirectional loop.
Language -> substrate: after each exchange, affect is extracted (LLM-judged,
never keyword lexicons — house rules), blended into current state with
momentum, and decayed toward quiet. The next recall runs on a state the
conversation itself produced. State persists: feelings outlive the turn."""
import json
import re

DECAY_PER_TURN = 0.80      # intensities ease toward quiet each turn
FLOOR = 0.05               # below this, a feeling has passed
MOMENTUM = 0.6             # how much new affect moves the existing state

JUDGE_SYSTEM = (
    "You read the emotional impact of an exchange on a persona. Given their "
    "current inner state and the exchange, return the feelings NOW PRESENT "
    "in them after it — names and intensities 0.0-1.0. Use plain lowercase "
    "feeling words (joy, warmth, fear, sadness, curiosity, loneliness, pride, "
    "comfort, unease...). 1-4 feelings. If the persona's pronouns are "
    "given, use exactly those pronouns for them in the why sentence — "
    "never guess gender from the name. Respond ONLY with JSON: "
    '{"feelings": {"<name>": <intensity>, ...}, '
    '"why": "<one short sentence>"}')


def decay_cocktail(cocktail: dict, factor: float = DECAY_PER_TURN) -> dict:
    return {k: round(v * factor, 3) for k, v in cocktail.items()
            if v * factor >= FLOOR}


def extract_affect(judge, persona_name: str, current: dict,
                   user_text: str, reply_text: str,
                   pronouns: str = "") -> tuple:
    state = ", ".join(f"{k}={v}" for k, v in current.items()) or "quiet"
    # pronouns ride the PERSONA line: the judge writes a free why-
    # sentence about the persona and a bare name invites gender-
    # guessing (measured when a bare name was gendered). Entity facts in,
    # correct language out — descriptive over prescriptive.
    who = f"{persona_name} ({pronouns})" if pronouns else persona_name
    raw = judge.chat(
        JUDGE_SYSTEM,
        f"PERSONA: {who}\nCURRENT STATE: {state}\n\n"
        f"OTHER SAID: {user_text}\n{persona_name.upper()} REPLIED: {reply_text}",
        max_tokens=160, temperature=0.0)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}, "affect parse failed; state unchanged"
    data = json.loads(m.group(0))
    feelings = {k.lower(): max(0.0, min(1.0, float(v)))
                for k, v in data.get("feelings", {}).items()}
    return feelings, data.get("why", "")


def blend(current: dict, incoming: dict, momentum: float = MOMENTUM) -> dict:
    out = dict(current)
    for k, v in incoming.items():
        out[k] = round(max(out.get(k, 0.0), out.get(k, 0.0) * (1 - momentum)
                           + v * momentum), 3)
    return {k: v for k, v in out.items() if v >= FLOOR}
