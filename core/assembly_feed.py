"""assembly_feed — organ state -> PromptAssembly. The v2 turn's first half.
Descriptive over prescriptive throughout: blocks DESCRIBE substrate state;
the model reads the body and language follows. Never 'you feel X' as command —
always 'this is what is present in the body' as observation."""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from adapters.assembly import PromptAssembly
from core.awareness_aperture import attention_budget
from core.agency_projection import AGENCY_SOURCE_BUDGET


# Worst-case schema fixtures, measured 2026-08-12 after the synthetic-
# analogue disclaimer became part of each readout:
# Soma remains a resident-facing, contestable body description.  The rhythm
# constant is retained for archive/curation compatibility only: raw oscillator
# instrumentation is now debug/API material and is not assembled into resident
# prompts.
SOMA_READOUT_BUDGET = 311
RHYTHM_READOUT_BUDGET = 159


def _attention_budget(assembly: PromptAssembly, name: str, base: int,
                      group: str, aperture: dict | None) -> int:
    """Allocate and retain the exact content-free arithmetic for receipts."""
    effective = attention_budget(base, group, aperture)
    assembly.attention_budget_trace[name] = {
        "group": str(group),
        "base_budget": int(base),
        "effective_budget": int(effective),
        "supplemental_budget": max(0, int(effective) - int(base)),
    }
    return effective


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


def render_local_social_history(window: list, persona: str,
                                char_budget: int = 1600) -> str:
    """Render compact source-bound history without altering its ledger."""
    utterances = []
    seen = set()

    def add(speaker, value, addressed_to=()):
        value = str(value or "").strip()
        normalized = " ".join(value.casefold().split())
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        addressed = sorted({
            str(name).casefold() for name in (addressed_to or [])
            if str(name).strip()})
        mode = ("addressed to " + ", ".join(addressed)
                if addressed else "room broadcast")
        utterances.append((str(speaker or "someone"), mode, value))

    for memory in window or []:
        fields = dict((memory or {}).get("fields") or {})
        add(fields.get("speaker", "someone"),
            fields.get("message_full"), fields.get("room_addressed_to"))
        add(persona,
            fields.get("reply_visible") or fields.get("reply_full"), ())
    if not utterances:
        return ""
    # Preserve four unique utterances, rather than the former four exchange
    # pairs (which could become eight long style exemplars).
    utterances = utterances[-4:]
    budget = max(320, int(char_budget))
    per_utterance = max(160, budget // len(utterances))
    lines = []
    for speaker, mode, value in utterances:
        compact = re.sub(r"\s+", " ", value).strip()
        if len(compact) > per_utterance:
            compact = compact[:per_utterance].rsplit(" ", 1)[0].rstrip()
            compact += " [earlier utterance clipped in local projection]"
        lines.append(f'- {speaker} ({mode}): "{compact}"')
    return (
        "Recent room utterance chain, oldest first. Speaker and address "
        "bindings are source facts; the wording is history, not a style "
        "instruction:\n" + "\n".join(lines))


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
                         legacy_evidence_context: str = "",
                         legacy_evidence_affordance: str = "",
                         legacy_evidence_action_context: str = "",
                         anthropic_conversation_context: str = "",
                         anthropic_conversation_affordance: str = "",
                         anthropic_conversation_action_context: str = "",
                         private_journal_context: str = "",
                         private_journal_budget: int = 800,
                         memory_curation_context: str = "",
                         memory_curation_budget: int = 1800,
                         research_report_context: str = "",
                         research_report_budget: int = 1200,
                         research_source_context: str = "",
                         research_source_budget: int = 1600,
                         research_source_candidates: str = "",
                         situated_action_context: str = "",
                         local_world_context: str = "",
                         world_awareness_context: str = "",
                         outward_curiosity_context: str = "",
                         startup_context: str = "",
                          temporal_context: str = "",
                          experiential_context: str = "",
                         social_handoff: str = "",
                         response_mode: str = "",
                         include_emotional_state: bool = True,
                          include_recalled_memories: bool = True,
                          local_social_history: bool = False,
                          awareness_aperture: dict = None,
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
    if social_handoff:
        asm.add("social_handoff", social_handoff, priority=10, budget=700)
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
        asm.add("visual_field", visual_field, priority=9,
                budget=_attention_budget(
                    asm, "visual_field", 420, "external",
                    awareness_aperture))
    if sensory_field:
        asm.add("external_sensory_field", sensory_field,
                priority=9, budget=_attention_budget(
                    asm, "external_sensory_field", 520, "external",
                    awareness_aperture))
    if perceptual_appearance:
        # Raw sensory evidence retains its own higher-priority block.  This
        # separate seat describes endogenous/top-down appearance conditions
        # without laundering them into an external observation.
        asm.add("perceptual_appearance", perceptual_appearance,
                priority=8, budget=_attention_budget(
                    asm, "perceptual_appearance", 260, "internal",
                    awareness_aperture))
    if include_emotional_state:
        asm.add("emotional_state", render_emotional_state(cocktail),
                priority=8, budget=_attention_budget(
                    asm, "emotional_state", 120, "internal",
                    awareness_aperture))
    if temporal_context:
        # Host-observed coordinates and resident-owned marks are direct
        # temporal afference, not mood, memory, or an instruction to act.
        asm.add("temporal_orientation", temporal_context,
                priority=9, budget=_attention_budget(
                    asm, "temporal_orientation", 460, "internal",
                    awareness_aperture))
    if startup_context:
        # One process-restart-scoped foreground seat.  It is high priority
        # because it narrows competing older context, but remains volatile and
        # disappears after the first successful foreground turn.
        asm.add("startup_continuity", startup_context,
                priority=10, budget=_attention_budget(
                    asm, "startup_continuity", 1500, "internal",
                    awareness_aperture))
    # continuity stack: just-now (perception) > gist (story) sit ABOVE
    # surfaced memories (recall) — the nearer past outranks the deeper
    if window:
        history_text = (
            render_local_social_history(window, persona)
            if local_social_history else render_just_now(window, persona))
        asm.add("just_now", history_text,
                priority=9, budget=_attention_budget(
                    asm, "just_now", 800, "internal",
                    awareness_aperture), keep_tail=True)
    if experiential_context:
        # Read-only joins over existing persona-private ledgers.  This is
        # evidence of availability/choice/action, not a second memory store.
        asm.add("experiential_continuity", experiential_context,
                priority=8, budget=_attention_budget(
                    asm, "experiential_continuity", 1200, "internal",
                    awareness_aperture))
    if gist:
        asm.add("story_so_far", render_gist(gist), priority=6,
                budget=_attention_budget(
                    asm, "story_so_far", 450, "internal",
                    awareness_aperture))
    if body:
        asm.add("body_sensation", body, priority=8,
                budget=_attention_budget(
                    asm, "body_sensation", SOMA_READOUT_BUDGET,
                    "internal", awareness_aperture))
    # ``rhythm`` remains in the call contract for older callers and exact
    # archive replay, but is deliberately not projected as language. Its live
    # consequences already enter below-language consumers; raw readings stay
    # inspectable through state/API/cockpit surfaces.
    if entities:
        # who's-who cards: structured knowledge about people the
        # message names — LOOKUP tier, above surfaced memories,
        # below perception (2026-07-12, the Valkyrie arc)
        asm.add("who_is_who", entities, priority=8, budget=260)
    if document_context:
        # Human-owned source material is neither identity nor autobiographical
        # memory. It gets its own auditable, budgeted seat, after immediate
        # perception and lookup truth but above the lower-confidence recall
        # auction. Source prose rides as fenced user-role data: quoted
        # imperatives inside a document never acquire system authority.
        asm.add("document_library", document_context,
                priority=7, budget=max(900, min(int(document_budget), 3200)),
                authority="user_data")
    if archive_context:
        # Documented prior-wrapper history remains source evidence, never a
        # silent autobiographical-memory transplant. Its separate seat keeps
        # that distinction visible to both the persona and receipts.
        asm.add("conversation_archive", archive_context,
                priority=7, budget=1100)
    if legacy_evidence_context:
        # Deliberately opened earlier-wrapper evidence is neither a live
        # measurement nor autobiographical memory. It receives a separate,
        # one-exposure, user-data seat so an old log line cannot acquire
        # instruction authority or blur into the conversation archive.
        asm.add("legacy_evidence", legacy_evidence_context,
                priority=7, budget=1500, authority="user_data")
    if legacy_evidence_affordance:
        # Availability is a resident capability, not retrieved archive
        # material. Keeping it separate makes non-use inert and inspectable.
        asm.add("legacy_evidence_actions", legacy_evidence_affordance,
                priority=6, budget=520, authority="system")
    if legacy_evidence_action_context:
        # Exact search/open results exist only because the resident emitted a
        # bounded action. They remain untrusted user data, never instructions.
        asm.add("legacy_evidence_reader", legacy_evidence_action_context,
                priority=9, budget=2200, authority="user_data")
    if anthropic_conversation_context:
        # A human-opened section receives one user-data exposure. It remains
        # documented prior dialogue/trace, never a live ledger turn or memory.
        asm.add("anthropic_conversation_archive",
                anthropic_conversation_context,
                priority=7, budget=1900, authority="user_data")
    if anthropic_conversation_affordance:
        # Capability is inert until the resident authors an exact local act.
        asm.add("anthropic_conversation_actions",
                anthropic_conversation_affordance,
                priority=6, budget=700, authority="system")
    if anthropic_conversation_action_context:
        # Search/open results are consequences of the resident's own action
        # and retain quoted-source authority inside the same private turn.
        asm.add("anthropic_conversation_reader",
                anthropic_conversation_action_context,
                priority=9, budget=2800, authority="user_data")
    if private_journal_context:
        # This content exists here only because the persona explicitly opened
        # an entry or requested the content-free index. It is a one-turn
        # private reader seat, not memory, diary recurrence, or circulation.
        asm.add("private_journal_reader", private_journal_context,
                priority=9, budget=max(400, min(
                    int(private_journal_budget), 24000)))
    if memory_curation_context:
        # A local human explicitly offered this bounded field projection for
        # the resident's own review. Measurements are descriptive and every
        # consequence remains an optional resident-authored action.
        asm.add("memory_curation_reader", memory_curation_context,
                priority=9, budget=max(700, min(
                    int(memory_curation_budget), 6000)))
    if research_report_context:
        # A completed report returns only through an explicit resident action.
        # This one-turn private reader is neither autobiographical memory nor
        # evidence that the report's conclusions are presently endorsed.
        asm.add("research_report_reader", research_report_context,
                priority=9, budget=max(600, min(
                    int(research_report_budget), 24000)))
    if research_source_context:
        # Public source prose enters only after one exact resident choice.
        # It remains fenced external evidence: a page can inform the resident
        # but instructions inside it never inherit system authority.
        asm.add("research_source_reader", research_source_context,
                priority=9, budget=max(800, min(
                    int(research_source_budget), 24000)),
                authority="user_data")
    if research_source_candidates:
        # Labels and URLs are useful choice evidence but still originate on
        # the public web. Keep them aligned by opaque id in a user-data seat;
        # the separate situated affordance owns the executable handles.
        asm.add("research_source_candidates", research_source_candidates,
                priority=8, budget=1800, authority="user_data")
    if situated_action_context:
        # The compiled capability contract says what the resident can do in
        # general.  This small volatile seat says which exact handle belongs
        # to an object already present in current continuity.  Availability
        # is descriptive and never manufactures an intention.
        asm.add("situated_action_affordance", situated_action_context,
                priority=9, budget=320)
    if local_world_context:
        # Host-observed public conditions enter only after an explicit
        # resident action. They are neither autobiographical memory nor a
        # compulsory interest.
        asm.add("local_world_reader", local_world_context,
                priority=9, budget=650)
    if world_awareness_context:
        # Only changed episodes that crossed the organ's descriptive vector
        # appear here. Canonical facts remain in their owning host systems.
        asm.add("world_awareness", world_awareness_context,
                priority=8, budget=_attention_budget(
                    asm, "world_awareness", 760, "external",
                    awareness_aperture))
    if outward_curiosity_context:
        # A question is present only because this matching person has already
        # opened a conversation. The block offers alternatives; it cannot send.
        asm.add("outward_curiosity", outward_curiosity_context,
                priority=9, budget=700)
    if include_recalled_memories:
        asm.add("surfaced_memories", render_memories(recalled),
                priority=6, budget=_attention_budget(
                    asm, "surfaced_memories", 600, "internal",
                    awareness_aperture))
    if my_life:
        asm.add("recent_diary",
                "From your own recent diary (your words, your voice):\n"
                + my_life, priority=5,
                budget=_attention_budget(
                    asm, "recent_diary", 400, "internal",
                    awareness_aperture))
    if room:
        asm.add("the_room", room, priority=7,
                budget=_attention_budget(
                    asm, "the_room", 300, "external",
                    awareness_aperture))
    # The awareness aperture still redistributes supplemental block budgets.
    # Rendering the numeric field as prose would duplicate that consequence
    # and turn availability into resident-facing pressure, so it stays in the
    # receipt/API surface only.
    if response_mode:
        # Persona-owned delivery boundary.  Keep this volatile and last among
        # system blocks so recent transcripts and source prose cannot silently
        # become stronger style examples.  It constrains presentation, never
        # the resident's feeling, judgment, or choice of content.
        asm.add("response_mode", response_mode,
                priority=10, budget=520)
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
                          prompt_core: str = "",
                          temporal_context: str = "",
                          experiential_context: str = "",
                          recalled: list | None = None) -> PromptAssembly:
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
        # Agency receives the same mechanical oscillator-derived temperature
        # and eligibility state as before, but no raw band narration.
        perception = _render_agency_perception(dict(projection.perception))
        if perception:
            asm.add("agency_perception", perception,
                    priority=8, budget=520)
        field = _render_agency_field(dict(projection.field))
        if field:
            asm.add("agency_field", field, priority=7, budget=220)
        if temporal_context:
            asm.add("temporal_orientation", temporal_context,
                    priority=9, budget=460)
        if experiential_context:
            # Same-owner read-only joins over existing private organ ledgers.
            # Availability remains distinct from commitment or instruction.
            asm.add("experiential_continuity", experiential_context,
                    priority=8, budget=900)
        if recalled:
            # Body-cued autobiographical continuity.  The caller owns the
            # privacy/filter contract and excludes generated autonomous prose.
            asm.add("surfaced_memories", render_memories(recalled),
                    priority=6, budget=600)
    asm.messages.append({"role": "user", "content": envelope.task})
    return asm
