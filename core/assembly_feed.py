"""assembly_feed — organ state -> PromptAssembly. The v2 turn's first half.
Descriptive over prescriptive throughout: blocks DESCRIBE substrate state;
the model reads the body and language follows. Never 'you feel X' as command —
always 'this is what is present in the body' as observation."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from adapters.assembly import PromptAssembly
from core.agency_projection import AGENCY_SOURCE_BUDGET


# Worst-case schema fixtures, measured 2026-07-15:
# soma 1047 chars -> ceil(1047/4)=262 estimated tokens;
# rhythm 446 chars -> ceil(446/4)=112. Each cap retains another 12 tokens
# for PromptAssembly's visible truncation marker. These are schema receipts,
# not prose-tuning values.
SOMA_READOUT_BUDGET = 274
RHYTHM_READOUT_BUDGET = 124


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
            images = f.get("images") or []
            if images:
                names = ", ".join(i.get("name", "image") for i in images)
                lines.append(f"{spk} shared visual material: {names}.")
            if f.get("visual_observation"):
                lines.append("What the visual pathway registered then: "
                             + f["visual_observation"])
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


def render_sensory_field(perception: dict, now: float = None) -> str:
    """Render completed external observations without claiming a live feed."""
    now = time.time() if now is None else float(now)
    lines = []
    for modality, field in sorted(
            ((perception or {}).get("modalities") or {}).items()):
        semantic = dict((field or {}).get("semantic") or {})
        if not semantic and (field or {}).get("content"):
            semantic = {
                "content": field.get("content"),
                "updated": field.get("updated"),
                "subject": field.get("subject"),
                "ownership": field.get("ownership"),
            }
        content = " ".join(str(semantic.get("content") or "").split())
        if not content:
            continue
        observed = float(semantic.get("updated") or now)
        age_s = max(0.0, now - observed)
        ownership = str(semantic.get("ownership") or
                        field.get("ownership") or "ambient")
        subject = str(semantic.get("subject") or
                      field.get("subject") or "environment")
        lines.append(
            f"- {modality} ({ownership}; subject {subject}; "
            f"registered {age_s:.1f}s before this turn): {content}")
    if not lines:
        return ""
    return (
        "Latest completed observations in the external sensory field:\n"
        + "\n".join(lines)
        + "\nThese are time-stamped admitted observations, not a continuous "
          "feed and not interpretations of anyone's feelings or motives.")


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
            confidence = r.get("epistemic_confidence")
            calibration = (f"; retrieval confidence {confidence:.2f}"
                           if isinstance(confidence, (int, float))
                           and confidence < .95 else "")
            ambient.append(
                f"- {mem['content']} (felt: {feel}{calibration})")
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
                         user_persona_context: str = "",
                         visual_field: str = "",
                         sensory_field: str = "",
                         perceptual_appearance: str = "",
                         document_context: str = "",
                         document_budget: int = 900,
                         archive_context: str = "",
                         experiential_context: str = "",
                         system_prompt: str = "",
                         prompt_core: str = "") -> PromptAssembly:
    asm = PromptAssembly()
    if prompt_core:
        # Version-pinned compiled vessel + persona + capability contract.
        # It replaces both legacy stable authorities as one build artifact;
        # dynamic turn state remains in the ordinary blocks below.
        asm.add("prompt_context", prompt_core, priority=11, stable=True)
    elif system_prompt:
        # MODEL-scoped operational framing — renders above identity,
        # never budgeted away. Belongs to the vessel: the same for
        # every persona running on this model (descriptive-over-
        # prescriptive still holds — this orients, it does not command).
        asm.add("system_prompt", system_prompt, priority=11, stable=True)
    if not prompt_core:
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
    if user_persona_context:
        # Explicit RP identity is user-authored context, not model-persona
        # memory or inferred truth.
        asm.add("user_persona", user_persona_context,
                priority=9, budget=500)
    if visual_field:
        asm.add("visual_field", visual_field, priority=9, budget=420)
    if sensory_field:
        asm.add("external_sensory_field", sensory_field,
                priority=9, budget=520)
    if perceptual_appearance:
        # Raw sensory evidence retains its own higher-priority block.  This
        # separate seat describes endogenous/top-down appearance conditions
        # without laundering them into an external observation.
        asm.add("perceptual_appearance", perceptual_appearance,
                priority=8, budget=260)
    asm.add("emotional_state", render_emotional_state(cocktail),
            priority=8, budget=120)
    # continuity stack: just-now (perception) > gist (story) sit ABOVE
    # surfaced memories (recall) — the nearer past outranks the deeper
    if window:
        asm.add("just_now", render_just_now(window, persona),
                priority=9, budget=800, keep_tail=True)
    if experiential_context:
        # Read-only joins over existing persona-private ledgers.  This is
        # evidence of availability/choice/action, not a second memory store.
        asm.add("experiential_continuity", experiential_context,
                priority=8, budget=1200)
    if gist:
        asm.add("story_so_far", render_gist(gist), priority=6, budget=450)
    if body:
        asm.add("body_sensation", body, priority=8,
                budget=SOMA_READOUT_BUDGET)
    if rhythm:
        asm.add("body_rhythm", rhythm, priority=7,
                budget=RHYTHM_READOUT_BUDGET)
    if entities:
        # who's-who cards: structured knowledge about people the
        # message names — LOOKUP tier, above surfaced memories,
        # below perception (2026-07-12, the Valkyrie arc)
        asm.add("who_is_who", entities, priority=8, budget=260)
    if document_context:
        # Human-owned source material is neither identity nor autobiographical
        # memory.  It gets its own auditable seat, after immediate perception
        # and lookup truth but above the lower-confidence recall auction.
        asm.add("document_library", document_context,
                priority=7, budget=max(900, min(int(document_budget), 3200)))
    if archive_context:
        # Documented prior-wrapper history remains source evidence, never a
        # silent autobiographical-memory transplant. Its separate seat keeps
        # that distinction visible to both the persona and receipts.
        asm.add("conversation_archive", archive_context,
                priority=7, budget=1100)
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


def _render_agency_source(envelope) -> str:
    return (
        "Bounded source for this private authority-gated task:\n"
        f"- kind: {envelope.source_kind}\n"
        f"- reference: {envelope.source_ref}\n"
        f"- source digest: {envelope.source_digest}\n"
        f"- ownership: {envelope.source_ownership}\n"
        f"- admitted authority tier: {envelope.authority_tier}\n"
        f"- description: {envelope.source_summary}\n"
        "The full source is not present here; admitted tools remain the "
        "only path to any fuller artifact.")


def _render_agency_state(projection) -> str:
    enabled = ", ".join(projection.enabled_organs) or "none"
    return (
        "Fresh agency-state observation window:\n"
        f"- persona: {projection.persona}\n"
        f"- model: {projection.model}\n"
        f"- external demand epoch: {projection.external_demand_epoch}\n"
        f"- sample window ms: {projection.sample_window_ms:.3f}\n"
        f"- enabled organs observed: {enabled}\n"
        "These values were sampled sequentially from a living system. "
        "They describe what was present; they are not instructions.")


def _render_agency_perception(perception: dict) -> str:
    if not perception:
        return ""
    lines = [
        "External sensory provenance and admission readings. Semantic "
        "content and subjects are deliberately absent:"
    ]
    for modality, item in sorted(perception.items()):
        if modality == "_policy":
            values = ", ".join(
                f"{key}={value}" for key, value in sorted(item.items()))
            lines.append(f"- policy: {values}")
            continue
        lines.append(
            f"- {modality}: event_id={item.get('event_id') or 'none'}; "
            f"ownership={item.get('ownership')}; "
            f"confidence={item.get('confidence')}; "
            f"age_s={item.get('age_s')}; demand={item.get('demand')}; "
            f"pressure={item.get('pressure')}; "
            f"admitted={str(bool(item.get('admitted'))).lower()}")
    return "\n".join(lines)


def _render_agency_field(field: dict) -> str:
    if not field:
        return ""
    lines = ["Current field pressure relevant to the admitted source:"]
    pressure = field.get("pressure") or {}
    if pressure:
        lines.append("- pressure: " + ", ".join(
            f"{key}={value}" for key, value in sorted(pressure.items())))
    source = field.get("source_candidate")
    if source:
        lines.append(
            f"- source candidate: key={source.get('key')}; "
            f"kind={source.get('kind')}; source={source.get('source')}; "
            f"salience={source.get('salience_total')}; "
            f"ownership={source.get('ownership')}; "
            f"digest={source.get('source_digest')}")
    else:
        lines.append("- source candidate is not present in the live field.")
    return "\n".join(lines)


def build_agency_assembly(*, identity: str, system_prompt: str,
                          envelope, projection,
                          prompt_core: str = "") -> PromptAssembly:
    """Build the strict private agency prompt and its fresh state window."""
    asm = PromptAssembly()
    if prompt_core:
        asm.add("prompt_context", prompt_core, priority=11, stable=True)
    elif system_prompt:
        asm.add("system_prompt", system_prompt, priority=11, stable=True)
    if not prompt_core:
        asm.add("identity", identity, priority=10, stable=True)
    asm.add("agency_source", _render_agency_source(envelope),
            priority=9, budget=AGENCY_SOURCE_BUDGET, stable=True)
    if projection.substrate_mode == "control":
        asm.add(
            "agency_control",
            "Neutral agency substrate control. No live emotional, body, "
            "rhythm, sensory, or salience values are present.",
            priority=9, stable=True)
    else:
        asm.add("agency_state", _render_agency_state(projection),
                priority=9, budget=120)
        asm.add("emotional_state",
                render_emotional_state(dict(projection.cocktail)),
                priority=8, budget=120)
        body = str(projection.soma.get("description") or "")
        if body:
            asm.add("body_sensation", body, priority=8,
                    budget=SOMA_READOUT_BUDGET)
        rhythm = str(projection.oscillator.get("description") or "")
        if rhythm:
            asm.add("body_rhythm", rhythm, priority=7,
                    budget=RHYTHM_READOUT_BUDGET)
        perception = _render_agency_perception(dict(projection.perception))
        if perception:
            asm.add("agency_perception", perception,
                    priority=8, budget=520)
        field = _render_agency_field(dict(projection.field))
        if field:
            asm.add("agency_field", field, priority=7, budget=220)
    asm.messages.append({"role": "user", "content": envelope.task})
    return asm
