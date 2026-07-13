"""assembly_feed — organ state -> PromptAssembly. The v2 turn's first half.
Descriptive over prescriptive throughout: blocks DESCRIBE substrate state;
the model reads the body and language follows. Never 'you feel X' as command —
always 'this is what is present in the body' as observation."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from adapters.assembly import PromptAssembly


def render_emotional_state(cocktail: dict) -> str:
    if not cocktail:
        return "The body is quiet. No strong feeling present."
    parts = [f"{name} ({intensity:.1f})" for name, intensity
             in sorted(cocktail.items(), key=lambda x: -x[1])]
    return ("Present in the body right now: " + ", ".join(parts) + ". "
            "These are observations of current inner state, not instructions.")


def render_company(descs: list) -> str:
    """Who can hear you, descriptively — awareness first. A persona behaving
    well around a kid he KNOWS is there is the descriptive-first way;
    the floor below is the mechanical guarantee underneath it."""
    if not descs:
        return ""
    return ("Present and able to hear you:\n"
            + "\n".join(f"- {d}" for d in descs))


FLOOR_TEXT = (
    "A child or someone unknown is present. This is a hard floor, not "
    "a suggestion: everything you say stays strictly child-appropriate "
    "— no profanity, no innuendo, no violence, no adult topics, no "
    "private household information, no exceptions. Warm and friendly "
    "is welcome; anything else waits until they've gone.")


def render_just_now(window: list, persona: str) -> str:
    """The last few exchanges, verbatim, chronological — PERCEPTION of
    the immediate past, not recall. Full text from fields (render may
    clip; encode never does). Speaker-aware: real names, no bake-ins."""
    if not window:
        return ""
    lines = []
    for mem in window:
        f = mem.get("fields") or {}
        if f.get("message_full") or f.get("reply_full"):
            spk = f.get("speaker", "someone")
            ch = f" (in the room)" if f.get("channel") == "room" else ""
            if f.get("message_full"):
                lines.append(f'{spk}{ch}: "{f["message_full"]}"')
            if f.get("reply_full"):
                lines.append(f'{persona}: "{f["reply_full"]}"')
        else:
            lines.append(f"- {mem.get('content', '')}")
    return ("What was just said, most recent last:\n"
            + "\n".join(lines))


def render_gist(gist: str) -> str:
    if not gist:
        return ""
    return ("The story so far, as it stands in memory "
            "(older than the last few exchanges):\n" + gist)


def render_memories(recalled: list) -> str:
    """Two tiers (2026-07-12, the Valkyrie-is-a-dog/partner bug):
    bedrock facts render as GROUND TRUTH — plain statements of what
    is known — while ordinary memories keep the surfacing/mood
    framing. A bedrock fact wrapped in '(felt: neutral)' under a
    'what surfaces, given the current state' header reads as
    ambience, and identity-block pattern-completion outbids it.
    Storage made bedrock immortal; recall gave it a seat; render
    must present it as fact. Same law, third panel."""
    if not recalled:
        return "Nothing in particular surfaces."
    ground, ambient = [], []
    for r in recalled:
        mem = r["memory"]
        if (mem.get("fields") or {}).get("is_bedrock"):
            ground.append(f"- {mem['content']}")
        else:
            feel = ", ".join(mem.get("emotion_tags", [])) or "neutral"
            ambient.append(f"- {mem['content']} (felt: {feel})")
    out = []
    if ground:
        out.append("Things you know to be true — ground truth, "
                   "not mood:\n" + "\n".join(ground))
    if ambient:
        out.append("What surfaces from memory, given the current "
                   "state:\n" + "\n".join(ambient))
    return "\n\n".join(out)


def build_turn_assembly(*, identity: str, cocktail: dict,
                        recalled: list, user_message: str,
                        rhythm: str = "", body: str = "",
                        my_life: str = "", room: str = "",
                        window: list = None, gist: str = "",
                        persona: str = "persona",
                        company: list = None,
                        floor: bool = False,
                        entities: str = "",
                        user_context: str = "",
                        system_prompt: str = "") -> PromptAssembly:
    asm = PromptAssembly()
    if system_prompt:
        # MODEL-scoped operational framing — renders above identity,
        # never budgeted away. Belongs to the vessel: the same for
        # every persona running on this model (descriptive-over-
        # prescriptive still holds — this orients, it does not command).
        asm.add("system_prompt", system_prompt, priority=11, stable=True)
    asm.add("identity", identity, priority=10, stable=True)
    if floor:
        # the mechanical floor: highest priority, never budgeted away
        asm.add("company_floor", FLOOR_TEXT, priority=10, stable=True)
    if company:
        asm.add("company", render_company(company),
                priority=8, budget=220)
    if user_context:
        # Human-owned canonical truth. It is assembled only after the
        # current company has filtered it, and sits above recalled memory:
        # a user's declaration outranks the model's inference about her.
        asm.add("user_bedrock", user_context, priority=9, budget=500)
    asm.add("emotional_state", render_emotional_state(cocktail),
            priority=8, budget=120)
    # continuity stack: just-now (perception) > gist (story) sit ABOVE
    # surfaced memories (recall) — the nearer past outranks the deeper
    if window:
        asm.add("just_now", render_just_now(window, persona),
                priority=9, budget=800)
    if gist:
        asm.add("story_so_far", render_gist(gist), priority=6, budget=450)
    if body:
        asm.add("body_sensation", body, priority=8, budget=140)
    if rhythm:
        asm.add("body_rhythm", rhythm, priority=7, budget=80)
    if entities:
        # who's-who cards: structured knowledge about people the
        # message names — LOOKUP tier, above surfaced memories,
        # below perception (2026-07-12, the Valkyrie arc)
        asm.add("who_is_who", entities, priority=8, budget=260)
    asm.add("surfaced_memories", render_memories(recalled),
            priority=6, budget=600)
    if my_life:
        asm.add("recent_diary",
                "From your own recent diary (your words, your voice):\n"
                + my_life, priority=5, budget=400)
    if room:
        asm.add("the_room", room, priority=7, budget=300)
    asm.messages.append({"role": "user", "content": user_message})
    return asm
