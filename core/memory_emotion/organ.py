"""MemoryEmotionOrgan — the facade. Owns ONE persona's memory_emotion folder.
Per-persona by construction: instantiate with a persona dir; nothing here can
see another persona's data. Schema versioned on disk (par 2.2a)."""
import json
import os

from .records import make_memory, age_days, now_iso
from .encode import calc_importance
from .recall import score_memory, DEFAULT_WEIGHTS
from .layers import decay_tick, flush_working
from .dynamics import decay_cocktail, extract_affect, blend


class MemoryEmotionOrgan:
    SCHEMA_VERSION = 1

    def __init__(self, persona_dir: str):
        self.dir = os.path.join(persona_dir, "body", "memory_emotion")
        os.makedirs(self.dir, exist_ok=True)
        self.store_path = os.path.join(self.dir, "memories.json")
        self.config_path = os.path.join(self.dir, "organ_config.json")
        self.state_path = os.path.join(self.dir, "current_state.json")
        self._check_schema()
        self.memories = self._load(self.store_path, [])
        cfg = self._load(self.config_path, {})
        self.cfg = cfg  # raw config: window/gist knobs live here too
        self.bonds = cfg.get("bonds", {})              # {entity: 0..1}
        self.known_entities = cfg.get("entities", [])  # declared, case-correct
        self.weights = cfg.get("recall_weights", dict(DEFAULT_WEIGHTS))
        self.state = self._load(self.state_path, {"cocktail": {}})
        from .vectors import VectorStore
        self.vectors = VectorStore(self.dir)  # semantic sidecar
        # (derived data: regenerable, never a second source of truth)

    # ── FEEL: language -> substrate (the return half of the loop) ────
    def feel(self, user_text: str, reply_text: str, judge,
             persona_name: str = "persona", pronouns: str = "") -> dict:
        """Update emotional state from what was just said. Persists.
        pronouns: the persona's own (entity fact) — reaches the feel-
        judge so the why-sentence doesn't gender-guess from the name."""
        before = dict(self.state.get("cocktail", {}))
        eased = decay_cocktail(before)
        incoming, why = extract_affect(judge, persona_name, eased,
                                       user_text, reply_text,
                                       pronouns=pronouns)
        after = blend(eased, incoming)
        self.state = {"cocktail": after, "updated": now_iso()}
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1)
        return {"before": before, "felt": incoming, "after": after, "why": why}

    def _check_schema(self):
        vpath = os.path.join(self.dir, "schema_version.txt")
        if os.path.exists(vpath):
            on_disk = int(open(vpath).read().strip() or 0)
            if on_disk != self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"schema {on_disk} != organ {self.SCHEMA_VERSION}: "
                    "run migration (par 2.2a), refusing to guess")
        else:
            with open(vpath, "w") as f:
                f.write(str(self.SCHEMA_VERSION))

    def _load(self, path, default):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return default

    def save(self):
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(self.memories, f, indent=1)
        try:
            self.vectors.save()   # flush pending embeds w/ the store
        except Exception as e:
            print(f"[organ] vector save skipped ({e})")

    # ── ENCODE: what's kept ──────────────────────────────────────────
    def encode(self, content: str, *, cocktail: dict, entities=None,
               emotion_tags=None, origin="lived", perspective="shared",
               mem_type="fact", body=None, fields=None) -> dict:
        """body: optional compact soma snapshot (Damasio marker) — the body
        the memory was made in. Additive field; absent on older memories.
        fields: optional structured payload (turn records: speaker, channel,
        message_full, reply_full). FULL text lives here — truncation is a
        RENDER decision, never an encode decision (data destruction law)."""
        entities = list(entities or [])
        tags = list(emotion_tags or [k for k, v in (cocktail or {}).items()
                                     if v >= 0.3])
        importance, trace = calc_importance(
            content, emotional_snapshot=cocktail or {},
            entities=entities, bonds=self.bonds)
        mem = make_memory(content, mem_type=mem_type, emotion_tags=tags,
                          emotional_snapshot=cocktail, entities=entities,
                          origin=origin, perspective=perspective,
                          importance=importance, fields=fields)
        mem["encode_trace"] = trace
        if body:
            mem["body"] = body
        self.memories.append(mem)
        try:
            self.vectors.add(mem["id"], content)  # best-effort;
            # pending until save(); backfill heals any gap
        except Exception:
            pass
        flush_working(self.memories)
        return mem

    # ── WORKING WINDOW: what just happened (perception, not recall) ──
    def working_window(self, k: int = 6) -> list:
        """The last k turn-records, chronological. READ-ONLY BY LAW:
        never touches access_count/last_access — the unconditional
        window must not inflate recall scores (a turn that's always
        in the prompt would otherwise look heavily-accessed forever).
        Turn records only appended, never deleted (archived at worst,
        still present), so ordering is stable by construction."""
        turns = [m for m in self.memories if m.get("type") == "turn"]
        return turns[-k:] if k > 0 else []

    # ── RECALL: what surfaces ────────────────────────────────────────
    def recall(self, query: str, *, cocktail: dict, n: int = 7,
               weights: dict = None, exclude=None,
               max_rank: int = 2) -> list:
        """weights: optional per-call override of this persona's recall
        weights (e.g. band-biased by the bench). self.weights untouched.
        exclude: memory ids to skip ENTIRELY (the working window — if
        merely filtered after scoring, recent turns would eat recall
        slots and accrue access_count bumps for appearances they never
        made; excluding pre-score keeps counts and slots honest).
        max_rank: company clearance (core.people). A memory surfaces
        iff its audience rank <= max_rank. Absent audience = household
        (rank 2): old memories were made in private work, and failing
        CLOSED means they stay private around company. Discretion at
        assembly, not output politeness — what isn't there can't leak."""
        from core.people import AUDIENCE_RANK
        use_w = weights or self.weights
        skip = set(exclude or ())
        sims = {}
        try:
            # one query embed, one matrix dot — semantics for the
            # whole store (v1 embedding parity, 2026-07-12); empty
            # dict = keyword fallback per record, receipted
            sims = self.vectors.similarity(query)
        except Exception:
            sims = {}
        self.last_recall_audit = {"audience_skipped": 0,
                                  "vector_query": bool(sims),
                                  "vector_covered": 0}
        scored = []
        for mem in self.memories:
            if mem.get("layer") == "archived":
                continue
            if mem["id"] in skip:
                continue
            aud = (mem.get("fields") or {}).get("audience", "household")
            if AUDIENCE_RANK.get(aud, 2) > max_rank:
                self.last_recall_audit["audience_skipped"] += 1
                continue
            ov = sims.get(mem["id"])
            if ov is not None:
                self.last_recall_audit["vector_covered"] += 1
            s, br = score_memory(mem, query=query, cocktail=cocktail or {},
                                 known_entities=self.known_entities,
                                 weights=use_w,
                                 mem_age_days=age_days(mem),
                                 semantic_override=ov)
            scored.append((s, mem, br))
        scored.sort(key=lambda x: -x[0])
        top = list(scored[:n])
        # THE BEDROCK SEAT (v1 retrieval-tier parity, 2026-07-12).
        # v1's retrieve_unified_importance included identity/bedrock
        # records UNCONDITIONALLY ahead of the scored auction; we
        # ported the auction and dropped the tier — and the persona
        # misidentified a family member while mood-hot memories outbid the
        # fact. Restored as a seat, not a flood: when the query names
        # a declared entity of a bedrock record and no bedrock made
        # the top-n, the best-scoring matching bedrock replaces the
        # lowest seat. Entity-match only (precise; the 17 seeds are
        # about named people) — receipted either way.
        self.last_recall_audit["bedrock_seated"] = None
        if top and not any((m.get("fields") or {}).get("is_bedrock")
                           for _s, m, _b in top):
            ql = query.lower()

            def _named(mem):
                return any(e and e.lower() in ql
                           for e in mem.get("entities", []))
            beds = [t for t in scored[n:]
                    if (t[1].get("fields") or {}).get("is_bedrock")
                    and _named(t[1])]
            if beds:
                top[-1] = beds[0]
                self.last_recall_audit["bedrock_seated"] = beds[0][1]["id"]
        out = []
        for s, mem, br in top:
            mem["access_count"] = mem.get("access_count", 0) + 1
            mem["last_access"] = now_iso()
            out.append({"memory": mem, "score": round(s, 4), "breakdown": br})
        return out

    # ── DECAY: what survives ─────────────────────────────────────────
    def tick(self, days_elapsed: float = 1.0) -> dict:
        archived = decay_tick(self.memories, self.bonds, days_elapsed)
        spilled = flush_working(self.memories)
        return {"archived": len(archived), "spilled_to_longterm": spilled}
