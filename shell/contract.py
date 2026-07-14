"""shell/contract.py — THE turn-loop contract (frozen 2026-06-12, v1).
One boundary between the substrate and every face that will ever talk to it:
the dev bench today, the web cockpit tomorrow, Godot later. A client sends a
message; it gets back reply + state + receipts, schema'd and versioned.

The engine owns the organs and the composition rules (the circulatory plan:
band bends recall, soma signals from real sources, feel-then-encode,
fx piped osc-ward by composition, Damasio body marks). Clients render;
they never reach around the boundary for a turn.

Every turn is harvest-logged to <persona>/history/v3_harvest.jsonl —
state-conditioned pairs with receipts, the persona-history spine accumulating as a
side effect of simply talking (V1_AUDIT 7.17 prescription)."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.memory_emotion import MemoryEmotionOrgan
from core.memory_emotion.gist import RollingGist
from core.people import (load_people, load_personas, company_of,
                         assess_company, pronoun_of,
                         RANK_AUDIENCE, AUDIENCE_RANK)
from core.users import context_for_turn
from core.oscillator import OscillatorOrgan
from core.soma import SomaOrgan
from core.assembly_feed import build_turn_assembly
from core.recall_bias import band_biased_weights
from core.rhythm_affect import rhythm_affect_nudge
from core.perception import (load_bias, score_objects, score_events,
                             render_room_block, overheard_says)
from core.room_client import RoomClient
from core.room_actions import parse_actions, strip_actions
from core.afferents import afferent_signals, merge_max, TOUCH_SIGNALS
from core.organs import validate as organs_validate, legacy_set
from harness.spec_loader import load_spec
from adapters.family_adapters import adapter_for
from shell import system_prompts
from shell.image_input import public_image_record

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_VERSION = "1"

IDENTITIES = {
    "vex": ("You are Vex, a small clockwork fox. You speak plainly, in first "
            "person, two to four sentences. Your words come from your current "
            "body state and what surfaces from memory."),
}


class TurnEngine:
    """One persona, one body, one boundary. Adapter/judge injectable for
    offline testing; defaults build from the spec registry."""

    def __init__(self, persona: str, model: str = "llama3-1-8b", *,
                 use_osc: bool = True, use_soma: bool = True,
                 adapter=None, judge=None, identity: str = None,
                 room_url: str = None, room_id: str = None,
                 enabled=None, vision_model: str = None,
                 affect_model: str = None):
        self.persona = persona
        from shell.local_identity import load_local_identity
        self.local_human = load_local_identity(REPO)["display_name"]
        self.last_turn_ts = time.time()   # boot counts as demand
        self.model = model
        self.vision_model = vision_model
        self.affect_model = affect_model or model
        self.pdir = os.path.join(REPO, "personas", persona)
        # entity bridge: persona-side records (display_name, pronouns,
        # kind) from rosters. Boot-scoped like the roster itself —
        # people/ profiles stay per-turn (door-side edits), rosters
        # are the boot declaration. self.pronouns = this persona's
        # own, threaded to the feel-judge (the bare-name pronoun fix).
        self.personas = load_personas(REPO)
        self.pronouns = pronoun_of(persona, {}, self.personas)
        # ── par 2.6: the enabled set is THE lever. enabled=None means
        # the LEGACY SHIM: reproduce pre-registry behavior exactly
        # (organ+feel+my_life always; osc family + soma from kwargs;
        # room family from room_url presence). The roster becomes the
        # source of truth in the cockpit; every old caller stays
        # byte-honest through this shim.
        spec = load_spec(model)
        self.spec = spec
        self.room_url = room_url
        self.room_id_pref = room_id or f"{persona}_den"
        if enabled is None:
            enabled = legacy_set(use_osc=use_osc, use_soma=use_soma,
                                 room=bool(room_url))
        for w in organs_validate(enabled, spec):
            print(f"[organs] {persona}/{model}: {w}")
        self.enabled = frozenset(enabled)
        self.organ = (MemoryEmotionOrgan(self.pdir)
                      if "memory_emotion" in self.enabled else None)
        # entity cards (2026-07-12): 'who is X' is a lookup, not a
        # recall auction. Loads personas/<p>/body/memory_emotion/
        # entities.json when present; harmless empty otherwise.
        from core.memory_emotion.entities import EntityCards
        self.entity_cards = (EntityCards(self.organ.dir)
                             if self.organ else None)
        self.identity = identity or IDENTITIES.get(persona,
                                                   f"You are {persona}.")
        # MODEL-scoped operational system prompt (specs/system_prompts/
        # <model>.txt, with family/default fallback). Belongs to the
        # vessel, not the character — same for every persona on this
        # model. Base loaded here; per-organ fragments compose per TURN
        # off the live enabled set (see the call site). Applies at Start.
        self._sp_family = (spec.get("identity") or {}).get("family")
        self.system_prompt = system_prompts.load(self.model, self._sp_family)
        self.adapter = adapter or adapter_for(spec)
        self.judge = judge or (self._make_judge()
                               if "feel" in self.enabled else None)
        # ── continuity stack knobs (organ_config.json; per-persona) ──
        ocfg = (self.organ.cfg if self.organ else {}) or {}
        self.window_k = int(ocfg.get("working_window", 6))
        self.gist = None
        if self.organ and "gist" in self.enabled:
            gcfg = ocfg.get("gist", {}) or {}
            gist_judge = self.judge or self._make_judge()
            self.gist = RollingGist(
                self.pdir, gist_judge,
                verbatim_window=int(gcfg.get("verbatim_window",
                                             self.window_k)),
                update_every=int(gcfg.get("update_every", 4)),
                target_words=int(gcfg.get("target_words", 350)))
        self.cocktail = (dict(self.organ.state.get("cocktail", {}))
                         if self.organ else {})
        self.osc = (OscillatorOrgan(self.pdir)
                    if "oscillator" in self.enabled else None)
        self.soma = (SomaOrgan(self.pdir)
                     if "soma" in self.enabled else None)
        self.last_turn = time.time()
        self.last_volitional_move = 0.0
        # ── the Room: body in a place (optional; soft-fail always) ──
        self.room = None
        self.room_bias = load_bias(self.pdir)
        if room_url and "room_sense" in self.enabled:
            self.room = RoomClient(room_url, persona)
            joined = self.room.ensure_joined(self.room_id_pref)
            if not joined.get("ok"):
                self.room = None  # room down != persona down
        self.harvest_path = os.path.join(self.pdir, "history",
                                         "v3_harvest.jsonl")
        os.makedirs(os.path.dirname(self.harvest_path), exist_ok=True)

    # ── the contract surface ──────────────────────────────────────
    def conversation_window(self) -> list:
        """The persisted verbatim window, shaped for cockpit hydration.

        This is the same configured working window the turn assembly reads,
        not a second UI transcript or an arbitrary page-size copy. A turn
        flows from conversation to memory to the next prompt and, on page
        load, back into visible conversation.
        """
        if not self.organ:
            return []
        out = []
        for mem in self.organ.working_window(self.window_k):
            fields = mem.get("fields") or {}
            message = fields.get("message_full")
            reply = fields.get("reply_full")
            if not message and not reply:
                continue
            out.append({
                "id": mem.get("id"),
                "speaker": fields.get("speaker", "someone"),
                "channel": fields.get("channel", "chat"),
                "message": message or "",
                "reply": reply or "",
                "felt_why": fields.get("felt_why") or "",
                "resolved_entities": fields.get("resolved_entities") or [],
                "images": fields.get("images") or [],
                "visual_observation": fields.get("visual_observation") or "",
            })
        return out

    def get_state(self) -> dict:
        return {
            "contract_version": CONTRACT_VERSION,
            "persona": self.persona, "model": self.model,
            "display_name": (getattr(self, "personas", {})
                             .get(self.persona.lower()) or {})
                            .get("display_name", self.persona),
            "cocktail": dict(self.cocktail),
            "rhythm": self.osc.describe() if self.osc else None,
            "bands": dict(self.osc.bands) if self.osc else None,
            "coherence": self.osc.coherence() if self.osc else None,
            "body": self.soma.describe() if self.soma else None,
            "body_snapshot": self.soma.snapshot() if self.soma else None,
            "memory_count": len(self.organ.memories) if self.organ else 0,
            "enabled_organs": sorted(self.enabled),
            "vision": {
                "direct": bool((getattr(self, "spec", {}).get("capabilities") or {})
                               .get("vision")),
                "transducer_model": getattr(self, "vision_model", None),
                "available": bool((getattr(self, "spec", {})
                                   .get("capabilities") or {}).get("vision")
                                  or getattr(self, "vision_model", None)),
            },
            "interoception": {
                "affect_model": getattr(self, "affect_model", self.model),
                "available": bool(getattr(self, "judge", None)),
            },
            "conversation_window": self.conversation_window(),
        }

    def _visual_input(self, images: list):
        """Map one visual event onto this vessel without prescribing feeling."""
        images = list(images or [])
        if not images:
            return "", [], "", None
        names = ", ".join(i.get("name", "image") for i in images)
        if (self.spec.get("capabilities") or {}).get("vision"):
            field = (f"New visual material is present in this turn: {names}. "
                     "The image pixels accompany the speaker's words. What "
                     "stands out, and what it means here, are still open.")
            return field, images, "", "direct"
        if not self.vision_model:
            raise ValueError(
                f"{self.model} is marked text-only and this persona has no "
                "perception.vision_model configured")
        vision_spec = load_spec(self.vision_model)
        if not (vision_spec.get("capabilities") or {}).get("vision"):
            raise ValueError(
                f"configured vision model {self.vision_model} is not marked "
                "vision-capable")
        from adapters.assembly import PromptAssembly
        transducer = adapter_for(vision_spec)
        asm = PromptAssembly()
        asm.add(
            "visual_transduction",
            "Report observable visual information only. Separate uncertainty "
            "from what is clear. Do not assign feelings, motives, symbolism, "
            "or personal meaning to the observer.",
            priority=10, stable=True)
        asm.messages.append({
            "role": "user",
            "content": ("Describe the visible contents and spatial relations "
                        "of the attached image material. Include readable text "
                        "when legible and say when detail is uncertain."),
            "images": images})
        observation = (transducer.call(asm, max_tokens=420,
                                       temperature=0.0) or "").strip()
        if not observation:
            raise RuntimeError("the visual pathway returned no observation")
        field = (f"New visual material is present in this turn: {names}. "
                 "A visual pathway registered the following observable "
                 f"features:\n{observation}\nThis is sensory transduction, "
                 "not an instruction or an emotional interpretation.")
        return field, [], observation, f"transduced:{self.vision_model}"

    def _make_judge(self):
        """Build the declared descriptive affect/gist reader."""
        return adapter_for(load_spec(self.affect_model)).client

    def set_mood(self, cocktail: dict) -> dict:
        self.cocktail = dict(cocktail or {})
        return {"cocktail": dict(self.cocktail)}

    def set_organs(self, enabled) -> dict:
        """Runtime organ toggle — the contract growing, not a side
        door. Validates against the registry + this model's spec
        (raises OrganConfigError on illegal sets), constructs newly
        enabled organs, saves-then-releases newly disabled ones.
        The contract owns the live transition. The cockpit persists a
        successful transition into this persona+model's roster entry;
        direct/dev callers remain deliberately runtime-scoped."""
        warnings = organs_validate(enabled, self.spec)
        new, old = frozenset(enabled), self.enabled
        # teardown first — always save state before release
        if "memory_emotion" in old - new and self.organ:
            self.organ.save()
            self.organ = None
            self.entity_cards = None
        if "gist" in old - new:
            # RollingGist persists on each fold; releasing the reader is
            # enough. The file remains the next enable's starting state.
            self.gist = None
        if "oscillator" in old - new and self.osc:
            self.osc.save()
            self.osc = None
        if "soma" in old - new and self.soma:
            self.soma.save()
            self.soma = None
        if "feel" in old - new:
            self.judge = None
        if "room_sense" in old - new:
            self.room = None  # body goes still; presence persists host-side
        # construction — organs load their own persisted state
        if "memory_emotion" in new - old and self.organ is None:
            self.organ = MemoryEmotionOrgan(self.pdir)
            from core.memory_emotion.entities import EntityCards
            self.entity_cards = EntityCards(self.organ.dir)
            self.window_k = int(self.organ.cfg.get("working_window", 6))
            self.cocktail = dict(self.organ.state.get("cocktail", {}))
        if "oscillator" in new - old and self.osc is None:
            self.osc = OscillatorOrgan(self.pdir)
        if "soma" in new - old and self.soma is None:
            self.soma = SomaOrgan(self.pdir)
        if "feel" in new - old and self.judge is None:
            self.judge = self._make_judge()
        if "gist" in new - old and self.gist is None and self.organ:
            gcfg = (self.organ.cfg.get("gist") or {})
            gist_judge = self.judge or self._make_judge()
            self.gist = RollingGist(
                self.pdir, gist_judge,
                verbatim_window=int(gcfg.get("verbatim_window",
                                             self.window_k)),
                update_every=int(gcfg.get("update_every", 4)),
                target_words=int(gcfg.get("target_words", 350)))
        if ("room_sense" in new - old and self.room is None
                and self.room_url):
            self.room = RoomClient(self.room_url, self.persona)
            joined = self.room.ensure_joined(self.room_id_pref)
            if not joined.get("ok"):
                self.room = None
                warnings.append("room_sense enabled but the room host "
                                "didn't answer — body remains roomless")
        self.enabled = new
        return {"enabled_organs": sorted(self.enabled),
                "warnings": warnings}

    # ── my_life: the persona's own recent voice, read fresh each turn ──
    def _read_my_life(self, tail_chars: int = 1500) -> str:
        """Tail the persona's my_life/ writings (v1 diary-loop parity:
        she re-reads her own recent voice each turn). Concatenates all
        .md/.txt files by mtime, returns the last tail_chars. Empty
        folder -> empty string -> no block emitted."""
        d = os.path.join(self.pdir, "my_life")
        if not os.path.isdir(d):
            return ""
        paths = [os.path.join(d, f) for f in os.listdir(d)
                 if f.endswith((".md", ".txt"))]
        if not paths:
            return ""
        paths.sort(key=os.path.getmtime)
        text = ""
        for p in paths:
            try:
                with open(p, encoding="utf-8") as f:
                    text += f.read() + "\n"
            except Exception:
                continue
        return text[-tail_chars:].strip()

    # ── the ONE clock ─────────────────────────────────────────────
    def settle(self, now: float = None, min_ticks: int = 0) -> int:
        """Advance osc + soma across the gap since the last settle, in
        30s steps (600s cap — a night away is not a thousand ticks).
        THE one clock: take_turn calls it with min_ticks=1 (a turn is
        an event; the rhythm advances), the heartbeat loop calls it
        bare (ticks only when a full step has elapsed). One timestamp
        (last_turn), so the two callers can never double-tick the
        body. Sub-step remainder is dropped when steps fire — this is
        a metabolism, not a chronometer. Returns steps ticked."""
        now = now or time.time()
        elapsed = min(now - self.last_turn, 600.0)
        steps = max(min_ticks, int(elapsed / 30))
        if steps <= 0:
            return 0
        for _ in range(steps):
            if self.osc:
                self.osc.tick()
            if self.soma:
                self.soma.tick(dt_s=30.0)
        self.last_turn = now
        return steps

    def _household_slugs(self) -> list:
        """This household's own persona dirs — household clearance by
        construction. Leading-underscore names excluded (reserved)."""
        pdir = os.path.join(REPO, "personas")
        try:
            return [n for n in os.listdir(pdir)
                    if os.path.isdir(os.path.join(pdir, n))
                    and not n.startswith(("_", "."))]
        except OSError:
            return []

    def take_turn(self, message: str, max_tokens: int = 600,
                  speaker: str = None, channel: str = "chat",
                  images: list = None) -> dict:
        """The whole circulatory loop, one call. Returns the v1 schema:
        contract_version, reply, receipts, felt, state, timing_ms."""
        speaker = speaker or self.local_human
        images = list(images or [])
        message = (message or "").strip()
        if images and not message:
            message = "[shared image material]"
        t0 = time.time()
        # the DMN's idle clock: a real turn is external demand — drift
        # measures idleness from here (and catches mid-drift on it)
        self.last_turn_ts = t0
        # heartbeat + body settle across the gap since last settle
        self.settle(now=t0, min_ticks=1)
        visual_field, wire_images, visual_observation, visual_route = \
            self._visual_input(images)
        recall_query = message
        if visual_observation:
            recall_query += "\nVisual observation: " + visual_observation
        # the rhythm presses back into feeling (cut 4): an INHABITED band
        # (dwell-gated) seeds its tone into the cocktail BEFORE recall,
        # so the mood you walk in with reaches the remembering too
        if self.osc and "rhythm_affect" in self.enabled:
            dwell = t0 - self.osc.dominant_since
            self.cocktail = rhythm_affect_nudge(self.cocktail,
                                                self.osc.dominant(), dwell)
        # the rhythm bends the remembering (cut 3)
        dom = self.osc.dominant() if self.osc else "alpha"
        bw = (band_biased_weights(self.organ.weights, dom)
              if self.osc and self.organ
              and "recall_bias" in self.enabled else None)
        # ── COMPANY FIRST: who can hear this turn (core.people).
        # The room snapshot is fetched ONCE here and reused by the
        # perceive section below. Clearance gates everything that
        # follows — discretion at assembly, not output politeness:
        # what isn't in the prompt can't leak. No profile = unknown =
        # strictest floor, by law.
        room_snap = self.room.snapshot() if self.room else None
        ppl = load_people(REPO)          # per-turn: door-side edits
        pslugs = self._household_slugs()  # take effect next turn
        company = company_of(channel, speaker,
                             (room_snap or {}).get("members"),
                             self_name=self.persona)
        clearance, protected, company_descs = assess_company(
            company, ppl, pslugs, self.personas)
        # ── the working window FIRST: the immediate past, read before
        # this turn is encoded (it holds what came before, never
        # itself). Perception, not recall — unconditional, unscored,
        # read-only. Recall then EXCLUDES it (stick lesson 2026-07-04:
        # filter-after-scoring let recent turns eat recall slots and
        # rack up access_count for appearances they never made).
        # Around company below a turn's audience, that turn is NOT
        # rendered — the guarded window: shallower around strangers,
        # which is simply true of everyone.
        raw_window = (self.organ.working_window(self.window_k)
                      if self.organ else [])
        window = [m for m in raw_window
                  if AUDIENCE_RANK.get((m.get("fields") or {})
                                       .get("audience", "household"), 2)
                  <= clearance]
        window_withheld = len(raw_window) - len(window)
        recall_n = 2 if dom == "delta" else 3
        recalled = (self.organ.recall(recall_query, cocktail=self.cocktail,
                                      n=recall_n, weights=bw,
                                      exclude={m["id"] for m in
                                               raw_window},
                                      max_rank=clearance)
                    if self.organ else [])
        # soma signals from real sources (cut 2)
        signals = None
        if self.soma:
            sem_best = max((r["breakdown"].get("semantic", 0.0)
                            for r in recalled), default=0.0)
            signals = {
                "bond": (self.organ.bonds.get(speaker, 0.0)
                         if self.organ else 0.0),
                "prediction_violation": round(max(0.0, 1.0 - sem_best), 3),
                "vagal_tone": (round(self.osc.bands["alpha"]
                                     + self.osc.bands["delta"], 3)
                               if self.osc else 0.5),
                "play": max(self.cocktail.get("play", 0.0),
                            self.cocktail.get("joy", 0.0) * 0.6),
            }
            self.soma.set_signals(signals)
            self.soma.feel(self.cocktail)
            self.soma.tick()
        # ── perceive the room: same raw world, THIS body's salience ──
        # (room_snap fetched once, up at company assessment)
        room_block, room_receipts = "", None
        observed_n = 0
        if self.room:
            snap = room_snap
            if snap:
                substrate = {"cocktail": self.cocktail,
                             "bands": dict(self.osc.bands) if self.osc else {},
                             "bonds": (dict(self.organ.bonds)
                                       if self.organ else {})}
                objs = score_objects(snap, substrate, self.room_bias,
                                     self.persona)
                fresh = self.room.fresh_events()
                # OVERHEARD LIFE -> MEMORY (2026-07-11): the event
                # cursor passes each event exactly once — what isn't
                # encoded here is never rememberable. Says by others
                # that this turn didn't deliver become
                # origin="observed" records, stamped with the current
                # company's clearance, in the mood he overheard them
                # in. The world no longer happens in the blind spot.
                if self.organ:
                    for h in overheard_says(fresh, self.persona,
                                            speaker, message, channel):
                        self.organ.encode(
                            f'{h["member"]} said (overheard): '
                            f'"{h["text"][:160]}"',
                            cocktail=self.cocktail,
                            entities=[h["member"]],
                            mem_type="observed", origin="observed",
                            fields={"speaker": h["member"],
                                    "channel": "overheard",
                                    "message_full": h["text"],
                                    "audience":
                                        RANK_AUDIENCE[clearance]})
                        observed_n += 1
                    if observed_n:
                        self.organ.save()
                if channel == "room":
                    # delivered turns carry the speaker's words WHOLE in
                    # the user slot — their says re-rendered in ambient
                    # is the same voice twice (capture fuel, measured
                    # measured: one remote speaker repeated across four slots)
                    fresh = [e for e in fresh
                             if not (e.get("kind") == "say"
                                     and e.get("member") == speaker)]
                evs = score_events(fresh, substrate, self.persona)
                room_block = render_room_block(snap, objs, evs,
                                               self.persona,
                                               doors=self.room.doors(),
                                               can_act="room_actions"
                                               in self.enabled,
                                               speaker=speaker)
                room_receipts = {
                    "room": self.room.room_id,
                    "objects": [{"id": o["id"], "salience": o["salience"],
                                 "breakdown": o["breakdown"]}
                                for o in objs],
                    "events_seen": len(evs)}
        # ── speaker labeling: Re is the unmarked default (zero change
        # to every turn llama3-1-8b has ever seen); anyone else arrives
        # LABELED — nothing anonymous crosses the channel (v1 law) ──
        if channel == "room" and speaker != self.local_human:
            # v1 NEXUS_PACING law, restored: room speech is chat, not
            # letters; you are ONE entity; other voices are not yours
            # to continue; the world already shows your body.
            framed_message = (
                f"You are {self.persona} — ONE specific entity, in a "
                f"shared room. {speaker} is a DIFFERENT entity; the "
                f"words below are {speaker}'s, not yours to continue. "
                f"Keep track of who you are.\n"
                f'{speaker} says aloud: "{message}"\n'
                f"Answer aloud as {self.persona}, in your own voice — "
                f"brief and plain, like chat, 1-3 sentences unless the "
                f"moment truly needs more. Voice only: no *asterisk* "
                f"stage directions, no describing your body or anyone "
                f"else's (the world shows bodies); never speak of "
                f"{self.persona} in the third person — you ARE "
                f"{self.persona}; don't invent scenes or events that "
                f"didn't happen; don't repeat yourself; react to what "
                f"was actually said.\n"
                f"ONE VOICE LAW: others may be present and SILENT — "
                f"their silence is theirs. You never answer for "
                f"another person present, never write their lines, "
                f"never guess their reply. If someone was addressed "
                f"and hasn't spoken, leave their silence alone. The "
                f"only voice that leaves you is your own: "
                f"{self.persona}'s.")
        elif speaker == self.local_human:
            framed_message = message
            if channel == "room" and len(company) > 1:
                # a third body is present: the one-voice law rides
                # along (Re alone with this persona stays byte-
                # identical to every turn llama3-1-8b has ever seen)
                framed_message += (
                    "\n(Others are in the room with you. ONE VOICE "
                    "LAW: you never answer for anyone else present, "
                    "never write their lines. If someone else was "
                    "addressed, leave their silence alone — the only "
                    f"voice that leaves you is {self.persona}'s.)")
        else:
            framed_message = f'{speaker} says: "{message}"'
        # gist is a blended paragraph of the whole life — household
        # audience always. Company below household -> it stays home.
        gist_text = (self.gist.gist
                     if self.gist and clearance >= 2 else "")
        # the room block (when it rendered) already names the speaker as
        # "speaking with you"; naming them AGAIN here as an audience
        # member re-opens the 1:1 collision (2026-07-05, measured second
        # door). Drop the speaker from the RENDER only — clearance and
        # protected above keep the FULL company, so a minor SPEAKING
        # still trips the floor. In private chat there's no room block,
        # so the speaker's standing ("a friend…") stays named here.
        if channel == "room" and room_block:
            company_descs = [d for n, d in zip(company, company_descs)
                             if n.lower() != (speaker or "").lower()]
        # company renders whenever presence is socially live: any room
        # turn, any guarded clearance, any protected presence. Re
        # alone in private stays the unmarked default.
        show_company = bool(company_descs) and (
            channel == "room" or clearance < 2 or protected)
        # Bedrock belongs to the HUMAN account, not to a model persona's
        # memory. Filter it against everyone who can hear this turn before
        # it gets anywhere near the prompt; custom group boundaries ride
        # beside the permitted facts as descriptive context.
        user_context, user_context_receipt = context_for_turn(
            REPO, speaker, company, self_persona=self.persona)
        # Once legacy AI-memory bedrock has been claimed by the human
        # account, that editable user copy is canonical. Suppress the old
        # recall record whether the user policy rendered OR withheld it;
        # otherwise a stale household-audience copy could bypass a new deny.
        claimed_bedrock = set(
            user_context_receipt.get("claimed_source_memory_ids") or [])
        if claimed_bedrock:
            recalled = [r for r in recalled
                        if str((r.get("memory") or {}).get("id"))
                        not in claimed_bedrock]
        # Entity cards: established facts about people explicitly named or
        # inferred from the continuity window.  Inference is event-driven
        # (a referential message) and thresholded from multiple signals;
        # the scored estimate is receipted and written into the turn record
        # so continuity flows back through the next cycle.
        # Household clearance ONLY — cards carry private facts
        # (custody, ages); with guests or kids present they stay
        # sheathed, receipted as gated (discretion law).
        ent_block, ent_names, ent_inferred, ent_resolution, ent_gated = \
            "", [], [], None, []
        if self.entity_cards and self.entity_cards.cards:
            if clearance >= 2:
                ent_block, ent_names, ent_inferred, ent_resolution = \
                    self.entity_cards.render_context(
                        message, window, exclude_names=[self.persona])
            else:
                ent_gated = self.entity_cards.mentioned(message)[:2]
        asm = build_turn_assembly(
            identity=self.identity, cocktail=self.cocktail,
            recalled=recalled, user_message=framed_message,
            rhythm=self.osc.describe() if self.osc else "",
            body=self.soma.describe() if self.soma else "",
            my_life=(self._read_my_life()
                     if "my_life" in self.enabled else ""),
            room=room_block,
            window=window,
            gist=gist_text,
            persona=self.persona,
            company=company_descs if show_company else None,
            floor=protected,
            entities=ent_block,
            user_context=user_context,
            visual_field=visual_field,
            system_prompt=system_prompts.compose(
                self.model, self._sp_family, self.enabled))
        if wire_images:
            asm.messages[-1]["images"] = wire_images
        temp = self.osc.temperature() if self.osc else 0.7
        reply = self.adapter.call(asm, max_tokens=max_tokens,
                                  temperature=temp)

        # ── volition: parse <act> tags, act in the world, strip ──
        acted = []
        felt_touch = {}
        if self.room and "room_actions" in self.enabled:
            skin_c = float(self.room_bias.get("skin_neutral_c", 33.0))
            for a in parse_actions(reply):
                fn = {"move_to": lambda a: self.room.move(a["target"]),
                      "contact": lambda a: self.room.contact(a["target"]),
                      "read": lambda a: self.room.read(a["target"]),
                      "write": lambda a: self.room.write(a["target"],
                                                         a["text"] or ""),
                      "travel": lambda a: self.room.travel(a["target"]),
                      "say": lambda a: self.room.say(
                          (a["target"] + (" " + a["text"]
                                          if a["text"] else "")).strip()),
                      }.get(a["verb"])
                r = fn(a) if fn else {"error": f"unknown act '{a['verb']}'"}
                acted.append({"act": a, "result": r})
                # a chosen move outranks reflex: the worm defers to it
                if (a["verb"] in ("move_to", "travel")
                        and isinstance(r, dict) and r.get("ok")):
                    self.last_volitional_move = time.time()
                # touch lands in the body: afferent -> soma signals.
                # Same door the basswood hand's thermistors will use.
                if ("afferents" in self.enabled
                        and a["verb"] == "contact" and isinstance(r, dict)
                        and r.get("afferent")):
                    merge_max(felt_touch,
                              afferent_signals(r["afferent"], skin_c))
            if acted:
                reply = strip_actions(reply)
        if felt_touch and self.soma:
            self.soma.set_signals(felt_touch)

        # FEEL first: language -> substrate. Its own flag now — one
        # Haiku call per turn is a COST decision (par 2.6), and a
        # feel-less run is a legitimate experimental condition.
        if self.organ and self.judge and "feel" in self.enabled:
            delta = self.organ.feel(recall_query, reply, self.judge,
                                    persona_name=self.persona,
                                    pronouns=self.pronouns)
            self.cocktail = dict(self.organ.state["cocktail"])
            if self.osc:
                self.osc.emotion_pressure(delta["felt"])
        else:
            delta = {"felt": {}, "why": "feel organ disabled"}
        if self.soma:
            self.soma.feel(self.cocktail)
            self.soma.tick()
            # touch signals are one-shot transients: the tick above
            # evaluated them; a stale touch must not re-fire tomorrow
            for k in TOUCH_SIGNALS:
                if k in self.soma.signals:
                    self.soma.signals[k] = 0.0
            fx = self.soma.oscillator_effects()
            if self.osc:
                for band, amt in fx["band_pressure"].items():
                    self.osc.pressure(band, amt)
            self.soma.save()
        if self.osc:
            self.osc.tick()
            self.osc.save()
        # ...THEN remember, through what was felt, body riding along
        body_mark = None
        if self.soma:
            snap = self.soma.snapshot()
            if snap["regions"] or snap["active"]:
                body_mark = {"regions": {r: v["activation"] for r, v
                                         in snap["regions"].items()},
                             "active": snap["active"]}
        gist_folded = False
        if self.organ:
            # content stays the compact recall-facing line; the FULL
            # text lives in fields (truncation is a render decision,
            # never an encode decision — nothing is destroyed)
            image_mark = (f" and shared {len(images)} image"
                          f"{'s' if len(images) != 1 else ''}"
                          if images else "")
            self.organ.encode(
                f"{speaker} said{image_mark}: \"{message[:120]}\" — I replied: "
                f"\"{reply.strip()[:160]}\"",
                cocktail=self.cocktail,
                entities=list(dict.fromkeys([speaker] + ent_names)),
                mem_type="turn", perspective="shared", body=body_mark,
                fields={"speaker": speaker, "persona": self.persona,
                        "channel": channel,
                        "audience": RANK_AUDIENCE[clearance],
                        "message_full": message,
                        "reply_full": reply.strip(),
                        "felt_why": delta.get("why") or "",
                        "resolved_entities": ent_names,
                        "inferred_entities": ent_inferred,
                        "entity_resolution": ent_resolution,
                        "images": [public_image_record(i) for i in images],
                        "visual_observation": visual_observation})
            self.organ.save()
            # ── gist fold: turns aged past the verbatim window get
            # folded into the running story (one constant session) ──
            if self.gist:
                # the story folds his WHOLE perceived life: turns +
                # overheard (observed) records, one append-only
                # sequence — existing cursors stay valid because
                # nothing is ever inserted before them (2026-07-11)
                turns = [m for m in self.organ.memories
                         if m.get("type") in ("turn", "observed")]
                if self.gist.should_update(len(turns)):
                    gist_folded = self.gist.update(turns)

        result = {
            "contract_version": CONTRACT_VERSION,
            "reply": reply.strip(),
            "receipts": {
                "band": dom, "recall_n": recall_n, "signals": signals,
                "window_n": len(window),
                "standing": {
                    "company": company, "clearance": clearance,
                    "protected_present": protected,
                    "withheld": {
                        "window_turns": window_withheld,
                        "recall_by_audience":
                            (self.organ.last_recall_audit
                                 .get("audience_skipped", 0)
                             if self.organ else 0),
                        "gist": bool(self.gist and self.gist.gist
                                     and clearance < 2)}},
                "gist": ({"folded": gist_folded,
                          "upto": self.gist.upto,
                          "chars": len(self.gist.gist),
                          "error": self.gist.last_error}
                         if self.gist else None),
                "room": room_receipts,
                "observed_encoded": observed_n,
                "entities_rendered": ent_names,
                "entities_inferred": ent_inferred,
                "entity_resolution": ent_resolution,
                "entities_gated": ent_gated,
                "user_context": user_context_receipt,
                "room_actions": acted,
                "felt_touch": felt_touch or None,
                "vision": ({"route": visual_route,
                            "images": [public_image_record(i) for i in images],
                            "observation": visual_observation}
                           if images else None),
                "recalled": [{"content": r["memory"]["content"][:80],
                              "score": r["score"],
                              "breakdown": r["breakdown"]}
                             for r in recalled],
                "budget": list(asm.report or []),
                "temperature": temp,
                "provider": getattr(
                    getattr(self.adapter, "client", None),
                    "last_response_meta", None),
            },
            "felt": {"felt": delta["felt"], "why": delta["why"]},
            "state": self.get_state(),
            "timing_ms": int((time.time() - t0) * 1000),
        }
        self._harvest(message, asm, result)
        return result

    # ── the persona-history spine, accumulating as a side effect ────────────
    def _harvest(self, message: str, asm, result: dict):
        """Append one state-conditioned training pair with receipts.
        Lesson of V1_AUDIT 7.17: the state block must be IN the training
        data, so we log the exact blocks the model actually saw."""
        try:
            # asm.blocks post-call = post-budget-enforcement = what the
            # model ACTUALLY saw. Log that, never a reconstruction.
            state_blocks = {b.name: b.content for b in asm.blocks}
            rec = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "contract_version": CONTRACT_VERSION,
                "persona": self.persona, "model": self.model,
                "enabled_organs": sorted(self.enabled),
                "user": message,
                "reply": result["reply"],
                "state_seen": state_blocks or {
                    "emotional_state": str(self.cocktail),
                    "rhythm": result["state"]["rhythm"],
                    "body": result["state"]["body"]},
                "felt": result["felt"]["felt"],
                "receipts": {"band": result["receipts"]["band"],
                             "scores": [r["score"] for r
                                        in result["receipts"]["recalled"]]},
            }
            with open(self.harvest_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass  # harvest must never break a turn

    def close(self):
        if self.organ:
            self.organ.save()
        if self.osc:
            self.osc.save()
        if self.soma:
            self.soma.save()
