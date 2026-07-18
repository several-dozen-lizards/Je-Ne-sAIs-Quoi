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
import math
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
from core.documents import (DocumentLibrary, private_document_access,
                            render_document_context)
from core.conversation_archive import (
    ConversationArchive, render_archive_context,
)
from core.memory_emotion.vectors import embed_texts
from core.oscillator import OscillatorOrgan
from core.soma import SomaOrgan
from core.sensory import SensoryEvent, SensoryOrgan
from core.substrate import (BODY_STEP_S, SUBSTRATE_COUPLING_GAIN,
                            SubstrateAccumulator, audio_band_pressure)
from core.voice_output import expression_policy
from core.assembly_feed import (build_agency_assembly, build_turn_assembly,
                                render_sensory_field)
from core.agency_projection import (
    AgencyAssemblyProduct, AgencyTaskEnvelope, sample_agency_state,
)
from core.recall_bias import band_biased_weights
from core.rhythm_affect import rhythm_affect_nudge
from core.perception import (load_bias, score_objects, score_events,
                             render_room_block, overheard_says)
from core.room_client import RoomClient
from core.room_actions import parse_actions, visible_reply
from core.prompt_runtime import resolve_prompt_runtime
from core.afferents import afferent_signals, merge_max, TOUCH_SIGNALS
from core.organs import validate as organs_validate, legacy_set
from harness.spec_loader import load_spec
from harness.model_call_receipts import (
    model_call_is_scoped, model_call_scope, new_cycle_id,
)
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
                 affect_model: str = None, gist_model: str = None,
                 prompt_version=None):
        self.persona = persona
        from shell.local_identity import load_local_identity
        local_identity = load_local_identity(REPO)
        self.local_human = local_identity["display_name"]
        self.local_user_id = local_identity["user_id"]
        self.last_turn_ts = time.time()   # boot counts as demand
        self.model = model
        self.vision_model = vision_model
        self.affect_model = affect_model or model
        # Backward-compatible purpose split: old rosters declared only one
        # background judge, so gist follows affect unless it is explicit.
        self.gist_model = gist_model or self.affect_model
        self._injected_judge = judge
        self.pdir = os.path.join(REPO, "personas", persona)
        self.documents = DocumentLibrary(
            REPO, self.local_user_id, persona)
        self.archive = ConversationArchive(
            REPO, self.local_user_id, persona)
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
        self.prompt_version_requested = prompt_version
        self._compiled_prompt_core = None
        self.prompt_runtime = {}
        self._refresh_prompt_runtime()
        self.prompt_shadow = self._project_prompt_shadow()
        self.adapter = adapter or adapter_for(spec)
        self.judge = judge or (self._make_judge()
                               if "feel" in self.enabled else None)
        # ── continuity stack knobs (organ_config.json; per-persona) ──
        ocfg = (self.organ.cfg if self.organ else {}) or {}
        self.window_k = int(ocfg.get("working_window", 6))
        self.gist = None
        if self.organ and "gist" in self.enabled:
            gcfg = ocfg.get("gist", {}) or {}
            gist_judge = self._make_gist_judge()
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
        self.perception = (SensoryOrgan(self.pdir)
                           if "perception" in self.enabled else None)
        # Cheap room summaries arrive independently of the expensive
        # attention lock. This buffer is transport only; settle() remains the
        # sole body clock and drains at most one duration-weighted profile per
        # real body step.
        self.substrate = SubstrateAccumulator()
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

        The cockpit is the private-chat surface, so its transcript hydrates
        only direct chat turns. Nexus turns remain in the persona's durable
        life and in the room event stream, but never masquerade as private
        conversation after a page load.
        """
        if not self.organ:
            return []
        out = []
        for mem in self.organ.working_window(self.window_k, channel="chat"):
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
        bands = dict(self.osc.bands) if self.osc else {}
        coherence = self.osc.coherence() if self.osc else 1.0
        perception = getattr(self, "perception", None)
        return {
            "contract_version": CONTRACT_VERSION,
            "persona": self.persona, "model": self.model,
            "display_name": (getattr(self, "personas", {})
                             .get(self.persona.lower()) or {})
                            .get("display_name", self.persona),
            "cocktail": dict(self.cocktail),
            "rhythm": self.osc.describe() if self.osc else None,
            "bands": bands if self.osc else None,
            "coherence": coherence if self.osc else None,
            "voice_output": expression_policy(
                bands, self.cocktail, coherence),
            "body": self.soma.describe() if self.soma else None,
            "body_snapshot": self.soma.snapshot() if self.soma else None,
            "perception": (perception.snapshot(
                dict(self.osc.bands) if self.osc else None,
                self.osc.coherence() if self.osc else 1.0)
                if perception else None),
            "memory_count": len(self.organ.memories) if self.organ else 0,
            "enabled_organs": sorted(self.enabled),
            "prompt_runtime": json.loads(json.dumps(
                getattr(self, "prompt_runtime", {
                    "status": "ready", "mode": "legacy",
                    "reason": "not_resolved",
                }))),
            "prompt_shadow": json.loads(json.dumps(
                getattr(self, "prompt_shadow", {
                    "status": "unavailable",
                    "reason": "not_projected",
                }))),
            "vision": {
                "direct": bool((getattr(self, "spec", {}).get("capabilities") or {})
                               .get("vision")),
                "transducer_model": getattr(self, "vision_model", None),
                "available": bool((getattr(self, "spec", {})
                                   .get("capabilities") or {}).get("vision")
                                  or getattr(self, "vision_model", None)),
            },
            "speech": (getattr(self, "speech_transcriber", None).status()
                       if getattr(self, "speech_transcriber", None) else
                       {"available": False}),
            "interoception": {
                "affect_model": getattr(self, "affect_model", self.model),
                "available": bool(getattr(self, "judge", None)),
            },
            "consolidation": {
                "gist_model": getattr(
                    self, "gist_model",
                    getattr(self, "affect_model", self.model)),
                "available": bool(getattr(self, "gist", None)),
            },
            "conversation_window": self.conversation_window(),
            "documents": (self.documents.status()
                          if getattr(self, "documents", None) else {
                              "document_count": 0, "documents": [],
                              "reader": {"active": False}}),
            "archive": (self.archive.status()
                        if getattr(self, "archive", None) else {
                            "session_count": 0, "section_count": 0,
                            "reader": {"active": False}}),
        }

    def _project_prompt_shadow(self) -> dict:
        """Compile and discard the unwired prompt; retain only its manifest."""
        try:
            from core.prompt_shadow import project_prompt_shadow
            return project_prompt_shadow(
                REPO, self.persona,
                getattr(self, "_sp_family", "unknown"),
                self.enabled)
        except Exception as exc:
            # Shadow compilation cannot become a new boot dependency while the
            # legacy prompt remains authoritative. Keep the failure visible
            # without returning source text or a machine path through state.
            import hashlib
            return {
                "status": "failed",
                "persona": self.persona,
                "family": getattr(self, "_sp_family", "unknown"),
                "error_type": type(exc).__name__,
                "error_digest": hashlib.sha256(
                    str(exc).encode("utf-8")).hexdigest()[:16],
            }

    def _refresh_prompt_runtime(self) -> dict:
        resolved = resolve_prompt_runtime(
            repo=REPO,
            persona=self.persona,
            family=getattr(self, "_sp_family", "unknown"),
            enabled_organs=self.enabled,
            requested=getattr(self, "prompt_version_requested", None),
        )
        self._compiled_prompt_core = resolved.text
        self.prompt_runtime = dict(resolved.receipt)
        return self.prompt_runtime

    def project_agency_state(
            self, envelope: AgencyTaskEnvelope, *,
            substrate_mode: str, external_demand_epoch: int,
            agency_model: str = None):
        """Read one fresh allowlisted state window without circulation."""
        return sample_agency_state(
            self, envelope, substrate_mode=substrate_mode,
            external_demand_epoch=external_demand_epoch,
            model_name=agency_model)

    def memory_context_snapshot(self, now: float = None) -> dict:
        """Copy the observed substrate at one memory-encoding boundary."""
        from core.memory_emotion.context import normalize_context
        context = {"schema": 1, "cocktail": dict(self.cocktail or {})}
        if self.osc is not None:
            context["bands"] = dict(self.osc.bands)
            context["coherence"] = self.osc.coherence()
        field = getattr(self, "idle_metabolism", None)
        preoccupation = getattr(field, "preoccupation", None)
        if preoccupation is not None:
            context["warmth_keys"] = list(
                preoccupation.active_keys(now=now))
        return normalize_context(context)

    def build_agency_snapshot(
            self, envelope: AgencyTaskEnvelope, *,
            substrate_mode: str, external_demand_epoch: int,
            agency_spec: dict = None, agency_model: str = None):
        """Build one ephemeral provider assembly plus content-free receipt."""
        projection = self.project_agency_state(
            envelope, substrate_mode=substrate_mode,
            external_demand_epoch=external_demand_epoch,
            agency_model=agency_model)
        selected_spec = agency_spec or getattr(self, "spec", {})
        selected_family = ((selected_spec.get("identity") or {}).get("family")
                           or getattr(self, "_sp_family", "unknown"))
        selected_model = str(agency_model or self.model)
        if agency_spec is None:
            compiled_core = getattr(self, "_compiled_prompt_core", None)
            prompt_receipt = getattr(self, "prompt_runtime", None)
            selected_system_prompt = self.system_prompt
        else:
            resolved = resolve_prompt_runtime(
                repo=REPO, persona=self.persona, family=selected_family,
                enabled_organs=self.enabled,
                requested=getattr(self, "prompt_version_requested", None))
            compiled_core = resolved.text
            prompt_receipt = resolved.receipt
            selected_system_prompt = system_prompts.load(
                selected_model, selected_family)
        assembly = build_agency_assembly(
            identity=self.identity,
            system_prompt=(selected_system_prompt
                           if not compiled_core else ""),
            prompt_core=compiled_core or "",
            envelope=envelope,
            projection=projection)
        receipt = {
            **envelope.receipt(),
            **projection.receipt(),
            "block_names": [block.name for block in assembly.blocks],
            "block_char_counts": {
                block.name: len(block.content)
                for block in assembly.blocks},
            "prompt": json.loads(json.dumps(getattr(
                self, "prompt_runtime", {
                    "schema_version": 1, "status": "ready",
                    "mode": "legacy", "reason": "not_resolved",
                }) if prompt_receipt is None else prompt_receipt)),
        }
        return AgencyAssemblyProduct(
            assembly=assembly,
            projection=projection,
            state_ref=projection.state_ref,
            temperature=projection.suggested_temperature,
            projection_receipt=receipt)

    def _visual_input(self, images: list, *, cycle_id: str = None,
                      model_receipts: list = None):
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
        observation, route = self.transduce_visual(
            images, cycle_id=cycle_id, model_receipts=model_receipts)
        field = (f"New visual material is present in this turn: {names}. "
                 "A visual pathway registered the following observable "
                 f"features:\n{observation}\nThis is sensory transduction, "
                 "not an instruction or an emotional interpretation.")
        return field, [], observation, route

    def transduce_visual(self, images: list, model: str = None, *,
                         cycle_id: str = None,
                         model_receipts: list = None):
        """Turn admitted pixels into an observation without taking a turn.

        Ambient camera frames use the declared narrow transducer even when the
        speaking vessel can see directly: seeing and deciding to speak remain
        separate events.  A direct-vision current model is an honest fallback.
        """
        chosen = model or self.vision_model
        if not chosen and (self.spec.get("capabilities") or {}).get("vision"):
            chosen = self.model
        if not chosen:
            raise ValueError("ambient vision needs perception.vision_model or "
                             "a vision-capable current model")
        vision_spec = load_spec(chosen)
        if not (vision_spec.get("capabilities") or {}).get("vision"):
            raise ValueError(
                f"configured vision model {chosen} is not marked "
                "vision-capable")
        from adapters.assembly import PromptAssembly
        adapters = getattr(self, "_aux_adapters", None)
        if adapters is None:
            adapters = {}
            self._aux_adapters = adapters
        transducer = adapters.get(chosen)
        if transducer is None:
            transducer = adapter_for(vision_spec)
            adapters[chosen] = transducer
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
        visual_cycle = cycle_id or new_cycle_id()

        def invoke():
            return (transducer.call(
                asm, max_tokens=420, temperature=0.0) or "").strip()

        if model_call_is_scoped():
            observation = invoke()
        else:
            with model_call_scope(
                    cycle_id=visual_cycle,
                    persona=getattr(self, "persona", "unknown"),
                    purpose="vision", sink=model_receipts):
                observation = invoke()
        if not observation:
            raise RuntimeError("the visual pathway returned no observation")
        return observation, f"transduced:{chosen}"

    def receive_sensory_event(self, event: SensoryEvent) -> dict:
        """Bench-compose one edge event into perception, soma, and rhythm.

        The perception organ returns raw effects; it never imports its
        siblings.  Semantic content is recorded but cannot directly paint an
        emotion, and ``other`` ownership remains other throughout this path.
        """
        if not self.perception or "perception" not in self.enabled:
            raise ValueError("perception organ is disabled")
        result = self.perception.ingest(
            event, dict(self.osc.bands) if self.osc else None,
            self.osc.coherence() if self.osc else 1.0)
        if not result["admitted"]:
            return result
        if self.soma:
            self.soma.set_signals(result["signals"])
            self.soma.tick(dt_s=1.0, now=event.timestamp)
            fx = self.soma.oscillator_effects()
            if self.osc:
                for band, amount in fx["band_pressure"].items():
                    self.osc.pressure(band, amount)
            # Edge features are afferent pulses, not a permanent stimulus.
            # Their effects persist in regions/rhythm; stale onset must not
            # re-fire on every later heartbeat.
            for name in result["signals"]:
                self.soma.signals[name] = 0.0
            self.soma.save()
        if self.osc:
            for band, amount in result["band_pressure"].items():
                self.osc.pressure(band, amount)
            self.osc.tick()
            self.osc.save()
        return result

    @staticmethod
    def _substrate_number(value, low=0.0, high=1.0):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return low
        if not math.isfinite(value):
            return low
        return max(low, min(high, value))

    def offer_substrate_summary(self, summary: dict) -> dict:
        """Queue a cheap interval summary without attention or semantics.

        This method never calls a model, never enters SensoryOrgan.ingest(),
        and never offers a DMN candidate. Its own accumulator lock is the only
        lock on the HTTP path.
        """
        summary = dict(summary or {})
        duration = self._substrate_number(
            summary.get("duration_s"), 0.0, 600.0)
        batch_id = str(summary.get("batch_id") or "")[:120]
        queued = {}

        if isinstance(summary.get("audio"), dict):
            audio = summary["audio"]
            audio_duration = self._substrate_number(
                audio.get("duration_s", duration), 0.0, 600.0)
            active = bool(audio.get("active", True))
            if active:
                pressure, receipt = audio_band_pressure(audio)
                receipt.update({
                    "batch_id": batch_id,
                    "sample_count": int(self._substrate_number(
                        audio.get("sample_count"), 0.0, 1_000_000.0)),
                    "floor_ready": bool(audio.get("floor_ready")),
                    "noise_floor": {
                        band: self._substrate_number(value, 0.0, 1e12)
                        for band, value in
                        (audio.get("noise_floor") or {}).items()
                        if band in ("delta", "theta", "alpha",
                                    "beta", "gamma")},
                    "floor_mean": {
                        band: self._substrate_number(value, 0.0, 1e12)
                        for band, value in
                        (audio.get("noise_floor") or {}).items()
                        if band in ("delta", "theta", "alpha",
                                    "beta", "gamma")},
                    "floor_sigma": {
                        band: self._substrate_number(value, 0.0, 1e12)
                        for band, value in
                        (audio.get("floor_sigma") or {}).items()
                        if band in ("delta", "theta", "alpha",
                                    "beta", "gamma")},
                    "floor_n": {
                        band: int(self._substrate_number(
                            value, 0.0, 1_000_000.0))
                        for band, value in
                        (audio.get("floor_n") or {}).items()
                        if band in ("delta", "theta", "alpha",
                                    "beta", "gamma")},
                    "band_power_mean": {
                        band: self._substrate_number(value, 0.0, 1e12)
                        for band, value in
                        (audio.get("band_power_mean") or {}).items()
                        if band in ("delta", "theta", "alpha",
                                    "beta", "gamma")},
                    "total_level": dict(audio.get("total_level") or {}),
                    "band_variance": dict(
                        audio.get("band_variance") or {}),
                    "band_trajectory": dict(
                        audio.get("band_trajectory") or {}),
                    "noise_floor_limitation": (
                        "sound present during the first interval may be "
                        "learned as room floor"),
                })
                queued["audio"] = self.substrate.offer(
                    "audio", audio_duration, pressure, receipt=receipt)
            else:
                queued["audio"] = self.substrate.offer(
                    "audio", 0.0, {}, active=False)

        if isinstance(summary.get("camera"), dict):
            camera = summary["camera"]
            camera_duration = self._substrate_number(
                camera.get("duration_s", duration), 0.0, 600.0)
            active = bool(camera.get("active", True))
            if active:
                allowed = ("motion", "novelty", "brightness",
                           "color_warmth", "saturation", "edge_density",
                           "stability", "brightness_delta", "edge_change")
                source = camera.get("features") or {}
                features = {}
                feature_receipts = {}
                for name in allowed:
                    stats = source.get(name, {})
                    mean = stats.get("mean") if isinstance(stats, dict) else stats
                    features[name] = self._substrate_number(mean)
                    if isinstance(stats, dict):
                        feature_receipts[name] = {
                            key: self._substrate_number(
                                value, -1e12, 1e12)
                            for key, value in stats.items()
                            if key in ("mean", "variance", "first", "last",
                                       "trajectory")}
                demand_stats = camera.get("demand") or {}
                demand = self._substrate_number(
                    demand_stats.get("mean") if isinstance(demand_stats, dict)
                    else demand_stats)
                event = SensoryEvent("camera", features,
                                     subject="environment",
                                     ownership="ambient")
                signals, pressure = SensoryOrgan._body_effects(event, demand)
                receipt = {
                    "batch_id": batch_id,
                    "sample_count": int(self._substrate_number(
                        camera.get("sample_count"), 0.0, 1_000_000.0)),
                    "features": feature_receipts,
                    "demand": (dict(demand_stats)
                               if isinstance(demand_stats, dict)
                               else {"mean": demand}),
                    "authored_prior": (
                        "existing numeric camera features to oscillator "
                        "bands; not physics and not a feeling claim"),
                }
                queued["camera"] = self.substrate.offer(
                    "camera", camera_duration, pressure, signals=signals,
                    receipt=receipt)
            else:
                queued["camera"] = self.substrate.offer(
                    "camera", 0.0, {}, active=False)

        return {"ok": True, "batch_id": batch_id, "queued": queued,
                "coupling_gain": SUBSTRATE_COUPLING_GAIN,
                "body_step_s": BODY_STEP_S,
                "attention_channel_touched": False,
                "model_calls": 0, "dmn_candidates": 0}

    def _drain_substrate_step(self):
        receipt = self.substrate.drain_step(BODY_STEP_S)
        if not receipt:
            return None
        if self.osc:
            for band, amount in receipt["band_pressure"].items():
                self.osc.pressure(band, amount)
        if self.soma:
            self.soma.set_signals(receipt["signals"])
        return receipt

    def _make_judge(self, model: str = None):
        """Build one declared descriptive background reader."""
        return adapter_for(load_spec(model or self.affect_model)).client

    def _make_gist_judge(self):
        """Resolve gist independently while preserving injected fixtures."""
        injected = getattr(self, "_injected_judge", None)
        if injected is not None:
            return injected
        if (getattr(self, "gist_model", self.affect_model)
                == self.affect_model
                and getattr(self, "judge", None) is not None):
            return self.judge
        return self._make_judge(
            getattr(self, "gist_model", self.affect_model))

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
        if "perception" in old - new and self.perception:
            self.perception.save()
            self.perception = None
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
        if "perception" in new - old and self.perception is None:
            self.perception = SensoryOrgan(self.pdir)
        if "feel" in new - old and self.judge is None:
            self.judge = self._make_judge()
        if "gist" in new - old and self.gist is None and self.organ:
            gcfg = (self.organ.cfg.get("gist") or {})
            gist_judge = self._make_gist_judge()
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
        self._refresh_prompt_runtime()
        self.prompt_shadow = self._project_prompt_shadow()
        return {"enabled_organs": sorted(self.enabled),
                "warnings": warnings,
                "prompt_runtime": json.loads(json.dumps(
                    self.prompt_runtime)),
                "prompt_shadow": json.loads(json.dumps(self.prompt_shadow))}

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
        steps = max(min_ticks, int(elapsed / BODY_STEP_S))
        if steps <= 0:
            return 0
        for _ in range(steps):
            substrate_receipt = self._drain_substrate_step()
            if self.osc:
                self.osc.tick()
            if self.soma:
                self.soma.tick(dt_s=BODY_STEP_S)
                if substrate_receipt:
                    for name in substrate_receipt["signals"]:
                        self.soma.signals[name] = 0.0
            if substrate_receipt and self.perception:
                substrate_receipt["observed_bands"] = (
                    dict(self.osc.bands) if self.osc else {})
                substrate_receipt["observed_mean_distribution_shift"] = (
                    sum(self.osc._coherence_window)
                    / len(self.osc._coherence_window)
                    if self.osc and self.osc._coherence_window else 0.0)
                self.perception.record_substrate(substrate_receipt)
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
                  images: list = None, on_text=None) -> dict:
        """The whole circulatory loop, one call. Returns the v1 schema:
        contract_version, reply, receipts, felt, state, timing_ms."""
        speaker = speaker or self.local_human
        images = list(images or [])
        message = (message or "").strip()
        if images and not message:
            message = "[shared image material]"
        t0 = time.time()
        cycle_id = new_cycle_id()
        model_receipts = []
        # the DMN's idle clock: a real turn is external demand — drift
        # measures idleness from here (and catches mid-drift on it)
        self.last_turn_ts = t0
        # heartbeat + body settle across the gap since last settle
        self.settle(now=t0, min_ticks=1)
        with model_call_scope(
                cycle_id=cycle_id, persona=self.persona,
                purpose="vision", sink=model_receipts):
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
        # Document access is human-owned and private by default.  The source
        # store participates only in a direct local-human chat; room company
        # never receives it merely because a model might promise discretion.
        documents = getattr(self, "documents", None)
        document_context = None
        document_context_text = ""
        document_receipt = {
            "rendered": False, "withheld": False,
            "reason": "library_empty", "active_anchor": None,
            "retrieved_anchors": [], "vector_query": False,
            "library_documents": 0,
        }
        archive = getattr(self, "archive", None)
        archive_context_text = ""
        archive_receipt = {
            "rendered": False, "withheld": False,
            "reason": "archive_empty_or_disabled",
            "active_anchor": None, "retrieved_anchors": [],
            "vector_query": False, "archive_sessions": 0,
        }
        shared_query_vector = None
        try:
            has_documents = bool(documents and documents.has_documents())
            document_receipt["library_documents"] = (
                len(documents.list_documents()) if has_documents else 0)
            access_allowed, access_reason = private_document_access(
                speaker, self.local_human, channel)
            document_allowed = has_documents and access_allowed
            if document_allowed:
                embedded = embed_texts([recall_query])
                shared_query_vector = (
                    embedded[0] if embedded is not None else None)
                document_context = documents.context_for_turn(
                    recall_query, query_vector=shared_query_vector)
                document_context_text = render_document_context(
                    document_context)
                document_receipt.update(document_context["receipt"])
                document_receipt.update({
                    "rendered": bool(document_context_text),
                    "withheld": False,
                    "reason": ("context_available" if document_context_text
                               else "no_matching_or_active_sections"),
                })
            elif has_documents:
                document_receipt.update({
                    "withheld": True,
                    "reason": access_reason,
                })
        except Exception as exc:
            document_receipt.update({
                "reason": "document_context_unavailable",
                "error_type": type(exc).__name__,
            })
            shared_query_vector = None

        try:
            archive_status = archive.status() if archive is not None else {}
            has_archive = bool(
                "archive_reader" in self.enabled
                and archive_status.get("granted")
                and archive_status.get("session_count"))
            archive_receipt["archive_sessions"] = int(
                archive_status.get("session_count") or 0)
            access_allowed, access_reason = private_document_access(
                speaker, self.local_human, channel)
            if has_archive and access_allowed:
                if shared_query_vector is None:
                    embedded = embed_texts([recall_query])
                    shared_query_vector = (
                        embedded[0] if embedded is not None else None)
                archive_context = archive.context_for_turn(
                    recall_query, query_vector=shared_query_vector)
                archive_context_text = render_archive_context(archive_context)
                archive_receipt.update(archive_context["receipt"])
                archive_receipt.update({
                    "rendered": bool(archive_context_text),
                    "withheld": False,
                    "reason": ("context_available" if archive_context_text
                               else "no_matching_or_active_sections"),
                })
            elif has_archive:
                archive_receipt.update({
                    "withheld": True, "reason": access_reason,
                })
        except Exception as exc:
            archive_receipt.update({
                "reason": "archive_context_unavailable",
                "error_type": type(exc).__name__,
            })

        if self.organ:
            recall_kwargs = {
                "cocktail": self.cocktail, "n": recall_n, "weights": bw,
                "exclude": {m["id"] for m in raw_window},
                "max_rank": clearance,
                "cue_context": self.memory_context_snapshot(now=t0),
            }
            if shared_query_vector is not None:
                recall_kwargs["semantic_query_vector"] = shared_query_vector
            recalled = self.organ.recall(recall_query, **recall_kwargs)
        else:
            recalled = []
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
                    observed_context = self.memory_context_snapshot(now=t0)
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
                                        RANK_AUDIENCE[clearance]},
                            context_at_encoding=observed_context)
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
        compiled_core = getattr(self, "_compiled_prompt_core", None)
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
            sensory_field=render_sensory_field(
                self.perception.snapshot() if self.perception else {}, t0),
            document_context=document_context_text,
            archive_context=archive_context_text,
            system_prompt=(system_prompts.compose(
                self.model, self._sp_family, self.enabled)
                if not compiled_core else ""),
            prompt_core=compiled_core or "")
        if wire_images:
            asm.messages[-1]["images"] = wire_images
        temp = self.osc.temperature() if self.osc else 0.7
        with model_call_scope(
                cycle_id=cycle_id, persona=self.persona,
                purpose="turn", sink=model_receipts):
            if on_text:
                reply = self.adapter.call(asm, max_tokens=max_tokens,
                                          temperature=temp, on_text=on_text)
            else:
                reply = self.adapter.call(asm, max_tokens=max_tokens,
                                          temperature=temp)

        # ── volition: parse <act> tags, act in the world, strip ──
        acted = []
        felt_touch = {}
        if self.room and "room_actions" in self.enabled:
            skin_c = float(self.room_bias.get("skin_neutral_c", 33.0))
            successful_says = []
            for action_index, a in enumerate(parse_actions(reply)):
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
                if (a["verb"] == "say" and isinstance(r, dict)
                        and r.get("ok")):
                    successful_says.append(action_index)
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
                reply = visible_reply(reply, successful_says)
        if felt_touch and self.soma:
            self.soma.set_signals(felt_touch)

        # FEEL first: language -> substrate. Its own flag now — one
        # Haiku call per turn is a COST decision (par 2.6), and a
        # feel-less run is a legitimate experimental condition.
        if self.organ and self.judge and "feel" in self.enabled:
            with model_call_scope(
                    cycle_id=cycle_id, persona=self.persona,
                    purpose="affect", sink=model_receipts):
                delta = self.organ.feel(
                    recall_query, reply, self.judge,
                    persona_name=self.persona, pronouns=self.pronouns)
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
                context_at_encoding=self.memory_context_snapshot(),
                fields={"speaker": speaker, "persona": self.persona,
                        "channel": channel,
                        "audience": RANK_AUDIENCE[clearance],
                        "message_full": message,
                        "reply_full": reply.strip(),
                        "felt_why": delta.get("why") or "",
                        "resolved_entities": ent_names,
                        "inferred_entities": ent_inferred,
                        "entity_resolution": ent_resolution,
                        "document_anchors": sorted(set(
                            ([document_receipt.get("active_anchor")]
                             if document_receipt.get("active_anchor") else [])
                            + list(document_receipt.get(
                                "retrieved_anchors") or []))),
                        "archive_anchors": sorted(set(
                            ([archive_receipt.get("active_anchor")]
                             if archive_receipt.get("active_anchor") else [])
                            + list(archive_receipt.get(
                                "retrieved_anchors") or []))),
                        "images": [public_image_record(i) for i in images],
                        "visual_observation": visual_observation})
            self.organ.save()

        result = {
            "contract_version": CONTRACT_VERSION,
            "cycle_id": cycle_id,
            "reply": reply.strip(),
            "receipts": {
                "model_calls": list(model_receipts),
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
                "gist": ({"folded": False,
                          "owner": "idle_dmn",
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
                "documents": document_receipt,
                "archive": archive_receipt,
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
                "prompt": json.loads(json.dumps(getattr(
                    self, "prompt_runtime", {
                        "schema_version": 1, "status": "ready",
                        "mode": "legacy", "reason": "not_resolved",
                    }))),
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
        if self.perception:
            self.perception.save()
