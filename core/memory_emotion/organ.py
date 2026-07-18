"""MemoryEmotionOrgan — the facade. Owns ONE persona's memory_emotion folder.
Per-persona by construction: instantiate with a persona dir; nothing here can
see another persona's data. Schema versioned on disk (par 2.2a)."""
import json
import math
import os
import time

from .records import make_memory, age_days, now_iso
from .encode import calc_importance
from .recall import score_memory, DEFAULT_WEIGHTS
from .layers import decay_tick, flush_working
from .dynamics import (decay_cocktail, extract_affect,
                       extract_event_affect, blend)
from .context import ContextCueIndex, normalize_context
from .narrative import build_narrative_memory


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
        self._memory_revision = 0
        self._persisted_revision = 0
        cfg = self._load(self.config_path, {})
        self.cfg = cfg  # raw config: window/gist knobs live here too
        self.bonds = cfg.get("bonds", {})              # {entity: 0..1}
        self.known_entities = cfg.get("entities", [])  # declared, case-correct
        self.weights = cfg.get("recall_weights", dict(DEFAULT_WEIGHTS))
        self.state = self._load(self.state_path, {"cocktail": {}})
        from .vectors import VectorStore
        self.vectors = VectorStore(self.dir)  # semantic sidecar
        # (derived data: regenerable, never a second source of truth)
        self.vectors.boot_health_check(
            (memory.get("id") for memory in self.memories),
            persona=os.path.basename(os.path.abspath(persona_dir)))
        self._context_cues = ContextCueIndex(self.memories)

    def vector_status(self) -> dict:
        """Read-only boot health + current sidecar coverage projection."""
        return self.vectors.health_status(
            memory.get("id") for memory in self.memories)

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

    def feel_event(self, event_text: str, judge,
                   persona_name: str = "persona", pronouns: str = "") -> dict:
        """Let a private consequence alter state through the same return path."""
        before = dict(self.state.get("cocktail", {}))
        eased = decay_cocktail(before)
        incoming, why = extract_event_affect(
            judge, persona_name, eased, event_text, pronouns=pronouns)
        after = blend(eased, incoming)
        self.state = {"cocktail": after, "updated": now_iso()}
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, indent=1)
        return {"before": before, "felt": incoming, "after": after, "why": why}

    def apply_described_affect(self, feelings: dict, why: str = "") -> dict:
        """Apply one already-described local self-report through normal dynamics.

        The caller must have asked the persona what arose; this method never
        chooses a desired emotion. It only validates and blends that bounded
        description so a local autonomous read can return to state without a
        second paid judge call.
        """
        incoming = {}
        for key, value in list(dict(feelings or {}).items())[:4]:
            name = str(key or "").strip().casefold()
            if not name or len(name) > 40 \
                    or not all(char.isalpha() or char in " _-" for char in name):
                continue
            try:
                intensity = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(intensity):
                continue
            incoming[name] = max(0.0, min(1.0, intensity))
        before = dict(self.state.get("cocktail", {}))
        eased = decay_cocktail(before)
        after = blend(eased, incoming)
        self.state = {"cocktail": after, "updated": now_iso()}
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, indent=1)
        return {"before": before, "felt": incoming, "after": after,
                "why": str(why or "")[:500]}

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

    def _save_canonical(self):
        """Atomically replace the single source of memory truth."""
        temporary = self.store_path + ".tmp"
        try:
            try:
                payload = json.dumps(
                    self.memories, ensure_ascii=False,
                    separators=(",", ":")).encode("utf-8")
            except UnicodeEncodeError:
                # Preserve even malformed legacy surrogate data rather than
                # turning a formatting optimization into memory loss.
                payload = json.dumps(
                    self.memories, ensure_ascii=True,
                    separators=(",", ":")).encode("utf-8")
            with open(temporary, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.store_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _mark_memory_dirty(self):
        self._memory_revision = getattr(self, "_memory_revision", 0) + 1

    def save(self):
        revision = getattr(self, "_memory_revision", None)
        persisted = getattr(self, "_persisted_revision", None)
        canonical = (revision is None or persisted is None
                     or revision != persisted
                     or not os.path.exists(self.store_path))
        if canonical:
            self._save_canonical()
            if revision is not None:
                self._persisted_revision = revision
        result = {"canonical": canonical, "vectors_added": 0,
                  "vector_error": None}
        try:
            result["vectors_added"] = self.vectors.save()
        except Exception as e:
            print(f"[organ] vector save skipped ({e})")
            result["vector_error"] = str(e)
        return result

    def admit_narrative(self, appraisal: dict, neighborhood: dict,
                        context_at_encoding: dict | None) -> dict:
        """Commit one accepted synthesis or leave every source untouched."""
        status = appraisal.get("status")
        if status == "no_cluster":
            return {"status": "no_cluster", "committed": False,
                    "selected_count": appraisal.get("selected_count", 0)}
        if status != "narrative":
            return {"status": "invalid", "committed": False,
                    "reason": appraisal.get("reason", "appraisal_not_ready")}

        signature = appraisal.get("cluster_signature")
        if any(memory.get("type") == "narrative"
               and (memory.get("fields") or {}).get("cluster_signature")
               == signature for memory in self.memories):
            return {"status": "duplicate", "committed": False,
                    "cluster_signature": signature}
        try:
            memory = build_narrative_memory(
                appraisal, self.memories, neighborhood,
                context_at_encoding)
        except Exception as error:
            return {"status": "invalid", "committed": False,
                    "reason": str(error)}

        memory_checkpoint = len(self.memories)
        revision_checkpoint = getattr(self, "_memory_revision", None)
        context_checkpoint = self._context_cues.checkpoint()
        vector_checkpoint = self.vectors.checkpoint()
        self.memories.append(memory)
        self._mark_memory_dirty()
        self._context_cues.add(memory)
        self.vectors.add(memory["id"], memory["content"])
        try:
            saved = self.save()
        except Exception as error:
            del self.memories[memory_checkpoint:]
            if revision_checkpoint is not None:
                self._memory_revision = revision_checkpoint
            self._context_cues.rollback_pending(context_checkpoint)
            self.vectors.rollback_pending(vector_checkpoint)
            return {"status": "write_failed", "committed": False,
                    "reason": str(error),
                    "cluster_signature": signature}
        return {
            "status": "committed", "committed": True,
            "memory_id": memory["id"],
            "cluster_signature": signature,
            "selected_count": len(appraisal["selected_ids"]),
            "candidate_count": len(appraisal["candidate_ids"]),
            "audience": appraisal["audience"],
            "model": appraisal["model"],
            "prompt_version": appraisal["prompt_version"],
            "vectors_added": saved["vectors_added"],
            "vector_error": saved["vector_error"],
        }

    # ── ENCODE: what's kept ──────────────────────────────────────────
    def encode(self, content: str, *, cocktail: dict, entities=None,
               emotion_tags=None, origin="lived", perspective="shared",
               mem_type="fact", body=None, fields=None,
               context_at_encoding=None) -> dict:
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
                          importance=importance, fields=fields,
                          context_at_encoding=context_at_encoding)
        mem["encode_trace"] = trace
        if body:
            mem["body"] = body
        self.memories.append(mem)
        self._mark_memory_dirty()
        context_cues = getattr(self, "_context_cues", None)
        if context_cues is not None:
            context_cues.add(mem)
        try:
            self.vectors.add(mem["id"], content)  # best-effort;
            # pending until save(); backfill heals any gap
        except Exception:
            pass
        flush_working(self.memories)
        return mem

    # ── WORKING WINDOW: what just happened (perception, not recall) ──
    def working_window(self, k: int = 6, channel: str = None) -> list:
        """The last k turn-records, chronological. READ-ONLY BY LAW:
        never touches access_count/last_access — the unconditional
        window must not inflate recall scores (a turn that's always
        in the prompt would otherwise look heavily-accessed forever).
        Turn records only appended, never deleted (archived at worst,
        still present), so ordering is stable by construction."""
        turns = [m for m in self.memories if m.get("type") == "turn"
                 and (channel is None
                      or (m.get("fields") or {}).get("channel", "chat")
                      == channel)]
        return turns[-k:] if k > 0 else []

    # ── RECALL: what surfaces ────────────────────────────────────────
    def recall(self, query: str, *, cocktail: dict, n: int = 7,
               weights: dict = None, exclude=None,
               max_rank: int = 2, cue_context: dict = None,
               use_cues: bool = True,
               semantic_query_vector=None) -> list:
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
        started = time.perf_counter()
        use_w = weights or self.weights
        skip = set(exclude or ())
        eligible = []
        audience_skipped = 0
        for mem in self.memories:
            if mem.get("layer") == "archived" or mem["id"] in skip:
                continue
            audience = (mem.get("fields") or {}).get(
                "audience", "household")
            if AUDIENCE_RANK.get(audience, 2) > max_rank:
                audience_skipped += 1
                continue
            eligible.append(mem)

        sims = {}
        try:
            # one query embed, one matrix dot — semantics for the
            # whole store (v1 embedding parity, 2026-07-12); empty
            # dict = keyword fallback per record, receipted
            if semantic_query_vector is None:
                sims = self.vectors.similarity(query)
            else:
                sims = self.vectors.similarity(
                    query, query_vector=semantic_query_vector)
        except Exception:
            sims = {}
        current_context = (normalize_context(cue_context)
                           if cue_context is not None else
                           {"schema": 1,
                            "cocktail": dict(cocktail or {})})
        if "cocktail" not in current_context:
            current_context["cocktail"] = dict(cocktail or {})

        eligible_count = len(eligible)
        neighborhood = max(max(0, int(n)),
                           math.ceil(math.sqrt(eligible_count))
                           if eligible_count else 0)
        indexed = {mem["id"]: index
                   for index, mem in enumerate(eligible)}
        semantic_ranked = sorted(
            (mem for mem in eligible if mem["id"] in sims),
            key=lambda mem: (-sims[mem["id"]], indexed[mem["id"]]))
        semantic_candidates = semantic_ranked[:neighborhood]

        context_cues = getattr(self, "_context_cues", None)
        if context_cues is None or context_cues.size != len(self.memories):
            context_cues = ContextCueIndex(self.memories)
            self._context_cues = context_cues
        context_ids, context_covered = context_cues.top_k_with_coverage(
            current_context, indexed, neighborhood)
        context_candidates = [eligible[indexed[memory_id]]
                              for memory_id in context_ids]

        query_lower = query.lower()
        bedrock_anchors = [
            mem for mem in eligible
            if (mem.get("fields") or {}).get("is_bedrock")
            and any(entity and entity.lower() in query_lower
                    for entity in mem.get("entities", []))
        ]

        fallback_reason = None
        if not use_cues:
            candidates = eligible
            fallback_reason = "control_full_scan"
        elif query.strip() and not sims:
            candidates = eligible
            fallback_reason = "semantic_unavailable_full_scan"
        elif not query.strip() and not context_candidates:
            candidates = eligible
            fallback_reason = "context_unavailable_full_scan"
        else:
            candidate_ids = {
                mem["id"] for mem in
                semantic_candidates + context_candidates + bedrock_anchors
            }
            candidates = [mem for mem in eligible
                          if mem["id"] in candidate_ids]

        cue_done = time.perf_counter()
        self.last_recall_audit = {
            "eligible_records": eligible_count,
            "semantic_candidates": len(semantic_candidates),
            "context_candidates": len(context_candidates),
            "candidate_union": len(candidates),
            "records_scored": 0,
            "candidate_fraction": 0.0,
            "vector_query": bool(sims),
            "vector_covered": sum(
                1 for mem in eligible if mem["id"] in sims),
            "context_covered": context_covered,
            "fallback_reason": fallback_reason,
            "cue_ms": round((cue_done - started) * 1000.0, 3),
            "score_ms": 0.0,
            "total_ms": 0.0,
            "audience_skipped": audience_skipped,
            "bedrock_seated": None,
        }
        scored = []
        score_started = time.perf_counter()
        for mem in candidates:
            ov = sims.get(mem["id"])
            s, br = score_memory(mem, query=query, cocktail=cocktail or {},
                                 known_entities=self.known_entities,
                                 weights=use_w,
                                 mem_age_days=age_days(mem),
                                 semantic_override=ov)
            scored.append((s, mem, br))
        scored.sort(key=lambda x: -x[0])
        score_done = time.perf_counter()
        self.last_recall_audit["records_scored"] = len(scored)
        self.last_recall_audit["candidate_fraction"] = round(
            len(scored) / eligible_count, 6) if eligible_count else 0.0
        self.last_recall_audit["score_ms"] = round(
            (score_done - score_started) * 1000.0, 3)
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
        if top:
            self._mark_memory_dirty()
        self.last_recall_audit["total_ms"] = round(
            (time.perf_counter() - started) * 1000.0, 3)
        return out

    # ── DECAY: what survives ─────────────────────────────────────────
    def tick(self, days_elapsed: float = 1.0) -> dict:
        decay_changed = bool(days_elapsed) and any(
            memory.get("layer") == "longterm"
            and not (memory.get("fields") or {}).get("is_bedrock")
            and not (memory.get("fields") or {}).get("no_decay")
            for memory in self.memories)
        archived = decay_tick(self.memories, self.bonds, days_elapsed)
        spilled = flush_working(self.memories)
        if decay_changed or spilled:
            self._mark_memory_dirty()
        return {"archived": len(archived), "spilled_to_longterm": spilled}
