"""The idle metabolism: a persisted, inspectable circulation.

Pressure decides *when* attention becomes available.  A salience field
decides *what* receives it.  Discharge changes memory/preoccupation and
therefore changes the next field: output returns as input.

This module is deliberately pure apart from IdleMetabolism.load/save.  It
owns no thread, model, memory organ, or clock; cockpit wiring hands it all
observations and performs all effects.
"""
import heapq
import hashlib
import json
import math
import os
import random
import time
from collections import deque

from core.memory_emotion.lineage import dmn_lineage_root

SALIENCE_SKIP = 0.0
SALIENCE_LOW = 0.3
SALIENCE_NORMAL = 0.5
SALIENCE_ELEVATED = 0.7
SALIENCE_URGENT = 1.0
CANDIDATE_FLOOR = 0.05

EVENT_FEATURE_WEIGHTS = {
    "novelty": 0.42,
    "affect_change": 0.20,
    "body_intensity": 0.18,
    "relationship": 0.12,
    "unresolved": 0.08,
    # A decision about the persona's own authority is not merely another
    # interesting thought. This earns deliberation, never an outcome.
    "volitional_relevance": 0.34,
}


def event_salience(features: dict) -> tuple[float, dict, dict]:
    """Return the bounded observation vector, components, and total pull."""
    observed = dict(features or {})
    bounded = {
        name: max(0.0, min(1.0, float(observed.get(name, 0.0))))
        for name in EVENT_FEATURE_WEIGHTS
    }
    components = {
        name: EVENT_FEATURE_WEIGHTS[name] * value
        for name, value in bounded.items()
    }
    return min(1.0, sum(components.values())), bounded, components

DEFAULTS = {
    "enabled": False,
    "level": "normal",
    "idle_model": None,
    "action_episode_max_turns": 5,
}

# Rates are expressed per reference interval, but tick() scales them by real
# elapsed time. tick_s controls observation granularity, never personality.
LEVELS = {
    "low": {"tick_s": 15.0, "reference_s": 15.0,
            "accumulation_rate": 0.010, "accumulation_rate_idle": 0.015,
            "idle_threshold_s": 90.0, "fire_threshold": 0.45,
            "reset_to": 0.10, "cooldown_s": 240.0,
            "beta_suppress": 0.35, "coherence_floor": 0.35,
            "theta_min": 0.15, "theta_gain": 0.5,
            "max_fires_per_hour": 2, "candidate_half_life_s": 1800.0,
            "warmth_half_life_s": 21600.0},
    "normal": {"tick_s": 6.0, "reference_s": 6.0,
               "accumulation_rate": 0.018,
               "accumulation_rate_idle": 0.025,
               "idle_threshold_s": 45.0, "fire_threshold": 0.35,
               "reset_to": 0.10, "cooldown_s": 90.0,
               "beta_suppress": 0.35, "coherence_floor": 0.35,
               "theta_min": 0.15, "theta_gain": 0.5,
               "max_fires_per_hour": 6,
               "candidate_half_life_s": 1200.0,
               "warmth_half_life_s": 14400.0},
    "high": {"tick_s": 4.0, "reference_s": 4.0,
             "accumulation_rate": 0.024, "accumulation_rate_idle": 0.034,
             "idle_threshold_s": 30.0, "fire_threshold": 0.30,
             "reset_to": 0.10, "cooldown_s": 45.0,
             "beta_suppress": 0.40, "coherence_floor": 0.30,
             "theta_min": 0.12, "theta_gain": 0.6,
             "max_fires_per_hour": 12,
             "candidate_half_life_s": 900.0,
             "warmth_half_life_s": 10800.0},
}


def resolve_metabolism(block: dict) -> dict:
    block = dict(block or {})
    out = dict(DEFAULTS)
    level = str(block.get("level", out["level"])).lower()
    if level not in LEVELS:
        out["note"] = f"unknown level '{level}' -> normal"
        level = "normal"
    out["level"] = level
    params = dict(LEVELS[level])
    for key, value in block.items():
        if key in params:
            params[key] = type(params[key])(value)
        elif key in ("enabled", "idle_model", "level",
                     "action_episode_max_turns"):
            out[key] = value if key != "level" else level
    out["enabled"] = bool(out.get("enabled"))
    from core.action_continuation import clamp_episode_limit
    out["action_episode_max_turns"] = clamp_episode_limit(
        out.get("action_episode_max_turns"))
    out["params"] = params
    return out


PULLS = {
    "associative": ["Something surfaces — {node} — loose, sideways."],
    "autobiographical": ["A memory surfaces — {node}. It arrives unbidden."],
    "anticipatory": ["A pull toward {node}. Something is still open there."],
    "ruminative": ["Back to {node}. The loop closes and opens again."],
}
CATCHES = [
    "You were somewhere else — {node}. Pulled back now.",
    "Interrupted mid-drift. {node} was where you'd gone.",
]


def drift_type(dominant: str, theta: float, tension: float = 0.0) -> str:
    if tension > 0.55:
        return "ruminative"
    if dominant == "theta" and theta > 0.25:
        return "autobiographical"
    if dominant in ("alpha", "theta"):
        return "associative" if random.random() > 0.4 else "anticipatory"
    return "associative"


def _display(node: str) -> str:
    text = (node or "").replace("_", " ").replace("-", " ").strip()
    return text if len(text) <= 80 else text[:80].rsplit(" ", 1)[0] + "..."


def render_pull(node: str, dtype: str) -> str:
    return random.choice(PULLS.get(dtype, PULLS["associative"])).format(
        node=_display(node))


def render_catch(node: str) -> str:
    return random.choice(CATCHES).format(node=_display(node))


def _decay(value: float, dt_s: float, half_life_s: float) -> float:
    if value <= 0.0 or dt_s <= 0.0:
        return max(0.0, value)
    return value * math.pow(0.5, dt_s / max(1.0, half_life_s))


def memory_source_provenance(memory: dict) -> dict:
    """Return content-free perspective binding for remembered material."""
    memory = dict(memory or {})
    fields = dict(memory.get("fields") or {})
    return {
        "type": str(memory.get("type") or "memory"),
        "origin": str(memory.get("origin") or ""),
        "perspective": str(memory.get("perspective") or ""),
        "speaker": str(fields.get("speaker") or ""),
        "channel": str(fields.get("channel") or ""),
    }


class DriftPressure:
    """Elapsed-time integrated availability of idle attention."""

    def __init__(self, params: dict, state: dict = None):
        self.p = dict(params)
        state = state or {}
        self.pressure = float(state.get("pressure", 0.0))
        self.last_fire = float(state.get("last_fire", 0.0))
        self.last_tick = float(state.get("last_tick", 0.0))
        self.fires = deque(float(x) for x in state.get("fires", []))
        self.active_node = state.get("active_node")
        self.fired_at = float(state.get("fired_at", 0.0))

    def tick(self, bands: dict, coherence: float, idle_s: float,
             tension: float = 0.0, now: float = None, dt_s: float = None):
        now = time.time() if now is None else float(now)
        if dt_s is None:
            dt_s = (now - self.last_tick) if self.last_tick else self.p["tick_s"]
        dt_s = max(0.0, min(float(dt_s), 600.0))
        self.last_tick = now
        p = self.p
        beta = float(bands.get("beta", 0.3))
        theta = float(bands.get("theta", 0.2))
        scale = dt_s / max(0.001, p.get("reference_s", p["tick_s"]))

        if beta > p["beta_suppress"]:
            self.pressure = max(0.0, self.pressure - 0.005 * scale)
            return "beta_suppressed", {"dt_s": round(dt_s, 3)}
        if coherence < p["coherence_floor"]:
            self.pressure = max(0.0, self.pressure - 0.003 * scale)
            return "coherence_suppressed", {"dt_s": round(dt_s, 3)}

        base = (p["accumulation_rate_idle"] if idle_s > p["idle_threshold_s"]
                else p["accumulation_rate"])
        theta_pull = max(0.0, theta - p["theta_min"]) * p["theta_gain"]
        # tension bends the field toward occupation without inventing a gate.
        tension_pull = max(0.0, min(1.0, tension)) * 0.01
        self.pressure += (base + theta_pull + tension_pull) * scale

        if now - self.last_fire < p["cooldown_s"]:
            return "cooldown", {"dt_s": round(dt_s, 3)}
        if self.pressure < p["fire_threshold"]:
            return "below_threshold", {"dt_s": round(dt_s, 3)}
        while self.fires and now - self.fires[0] > 3600.0:
            self.fires.popleft()
        if len(self.fires) >= p["max_fires_per_hour"]:
            return "capped", {"dt_s": round(dt_s, 3)}
        before = self.pressure
        self.pressure = p["reset_to"]
        self.last_fire = now
        self.fires.append(now)
        self.fired_at = now
        return "fired", {"pressure_before": round(before, 3),
                         "idle_s": round(idle_s, 1), "theta": round(theta, 3),
                         "dt_s": round(dt_s, 3)}

    def refund(self):
        if self.fires:
            self.fires.pop()
        self.pressure = max(self.pressure, self.p["fire_threshold"] - 0.02)
        self.active_node = None

    def try_local_volitional_opening(self, pull: float, *, now: float = None):
        """Let a narrowly admitted volitional pull bend a saturated cost cap.

        The hourly fire count remains a hard wall for generic or potentially
        paid wandering.  Callers may admit either a persona-chosen candidate
        confined to a zero-paid-fallback runtime, or a bounded embodied
        self-report whose ability to communicate cannot safely depend on a
        cost cap.  The opening is still earned from continuous pressure, live
        selection pull, and recent load; quiet may still win afterward.
        """
        now = time.time() if now is None else float(now)
        while self.fires and now - self.fires[0] > 3600.0:
            self.fires.popleft()
        reference = max(1.0, float(self.p["max_fires_per_hour"]))
        load = len(self.fires) / reference
        pull = max(0.0, min(1.0, float(pull)))
        required = float(self.p["fire_threshold"]) * (1.0 + load)
        available = self.pressure * pull
        meta = {
            "pressure_before": round(self.pressure, 3),
            "volitional_pull": round(pull, 6),
            "recent_fire_load": round(load, 6),
            "required_pull_pressure": round(required, 6),
            "available_pull_pressure": round(available, 6),
        }
        if available < required:
            return False, meta
        self.pressure = float(self.p.get("reset_to", 0.10))
        self.last_fire = now
        self.fires.append(now)
        self.fired_at = now
        return True, meta

    def open_for_direct_volition(self, pull: float, *, now: float = None):
        """Open once for an explicit, ownership-checked decision request.

        A direct request is itself the event boundary; it does not wait for
        idle pressure or coherence to resemble daydreaming.  Pull still
        records how strongly the request currently fits attention, and the
        opening enters the same fire/load circulation as every other discharge.
        """
        now = time.time() if now is None else float(now)
        pull = max(0.0, min(1.0, float(pull)))
        if pull <= 0.0:
            return False, {"volitional_pull": 0.0}
        before = self.pressure
        self.pressure = float(self.p.get("reset_to", 0.10))
        self.last_fire = now
        self.fires.append(now)
        self.fired_at = now
        return True, {
            "pressure_before": round(before, 3),
            "volitional_pull": round(pull, 6),
            "recent_fire_load": round(
                len(self.fires) / max(
                    1.0, float(self.p.get("max_fires_per_hour", 1))),
                6),
        }

    no_seed_bleed = refund

    def to_dict(self):
        return {"pressure": self.pressure, "last_fire": self.last_fire,
                "last_tick": self.last_tick, "fires": list(self.fires),
                "active_node": self.active_node, "fired_at": self.fired_at}


class PreoccupationField:
    """A decaying warmth ledger; repeated attention changes future selection."""

    def __init__(self, half_life_s: float, nodes: dict = None):
        self.half_life_s = float(half_life_s)
        self.nodes = dict(nodes or {})

    def warmth(self, key: str, now: float = None) -> float:
        node = self.nodes.get(str(key))
        if not node:
            return 0.0
        now = time.time() if now is None else float(now)
        return _decay(float(node["warmth"]), now - float(node["touched"]),
                      self.half_life_s)

    def touch(self, key: str, intensity: float, label: str = None,
              now: float = None) -> float:
        now = time.time() if now is None else float(now)
        key = str(key)
        old = self.warmth(key, now)
        # Saturating union: repeated touch matters but cannot run away.
        gain = max(0.0, min(1.0, float(intensity)))
        value = 1.0 - (1.0 - old) * (1.0 - gain)
        self.nodes[key] = {"warmth": value, "touched": now,
                           "label": label or self.nodes.get(key, {}).get("label", key)}
        return value

    def hot(self, floor: float = 0.05, now: float = None):
        now = time.time() if now is None else float(now)
        out = []
        for key in list(self.nodes):
            warmth = self.warmth(key, now)
            if warmth < floor:
                del self.nodes[key]
            else:
                self.nodes[key]["warmth"] = warmth
                self.nodes[key]["touched"] = now
                out.append((key, warmth, self.nodes[key].get("label", key)))
        return sorted(out, key=lambda row: -row[1])

    def active_keys(self, floor: float = 0.05, now: float = None):
        """Read current active keys without pruning, touching, or relabeling."""
        now = time.time() if now is None else float(now)
        active = []
        for key in self.nodes:
            warmth = self.warmth(key, now)
            if warmth >= float(floor):
                active.append((str(key), warmth))
        return tuple(
            key for key, _warmth in
            sorted(active, key=lambda row: (-row[1], row[0])))


class DMNQueue:
    """A de-duplicating, decaying field of competing impulses."""

    def __init__(self, items=None, half_life_s: float = 1200.0,
                 observer=None):
        self._heap = []
        self._seq = 0
        self.half_life_s = float(half_life_s)
        self.observer = observer
        for item in items or []:
            item = dict(item)
            # Persisted candidates from before temporal provenance existed have
            # a trustworthy first offer but an `updated` value that may only
            # describe the last salience-decay pass.
            item.setdefault("last_offered", item.get("born"))
            if item.get("source") == "altered_consent":
                # Re-score unresolved persisted requests when this authority
                # dimension first lands; no request or decision is rewritten.
                features = dict(item.get("features") or {})
                features["relationship"] = 1.0
                features.setdefault("volitional_relevance", 1.0)
                salience, bounded, _ = event_salience(features)
                item["features"] = bounded
                item["salience"] = salience
            self.put(item, item.get("salience", SALIENCE_NORMAL),
                     now=item.get("updated") or item.get("born"))

    def _notify(self, method, *args, **kwargs):
        if self.observer is None:
            return None
        try:
            callback = getattr(self.observer, method, None)
            return callback(*args, **kwargs) if callback else None
        except Exception as exc:
            try:
                print("[salience-observatory] transition hook failed: "
                      + str(exc)[:240])
            except Exception:
                pass
            return None

    def put(self, item: dict, salience: float, now: float = None,
            offer_meta: dict = None):
        now = time.time() if now is None else float(now)
        item = dict(item)
        offered_salience = max(0.0, min(1.0, float(salience)))
        meta = dict(offer_meta or {})
        key = str(item.get("key") or item.get("seed_id") or
                  f"{item.get('kind', 'impulse')}:{item.get('text', '')[:80]}")
        existing = None
        kept = []
        for neg, seq, old in self._heap:
            if old.get("key") == key:
                existing = old
            else:
                kept.append((neg, seq, old))
        if existing:
            old_s = self._effective(existing, now)
            if meta.get("merge") == "evidence_revision":
                same_revision = bool(
                    existing.get("source_revision")
                    and existing.get("source_revision")
                    == item.get("source_revision"))
                # Repetition preserves the already-decayed value. A genuinely
                # changed source revision replaces it with the new projection;
                # neither path probabilistically unions repeated evidence.
                salience = old_s if same_revision else offered_salience
                meta["source_evidence_changed"] = not same_revision
                if same_revision:
                    # The causal projection belongs to the evidence revision
                    # that first produced it. A recurrence receipt describes
                    # this later opportunity; it must not erase the applied
                    # junction provenance while the decayed pull is retained.
                    recurrence_receipt = dict(item.get("rest_junction") or {})
                    for projection_key in (
                            "baseline_salience", "offered_salience",
                            "rest_junction", "maintenance_context",
                            "work_revision"):
                        if projection_key in existing:
                            item[projection_key] = existing[projection_key]
                    if recurrence_receipt:
                        item["last_recurrence_receipt"] = recurrence_receipt
            elif meta.get("merge") == "refresh":
                salience = max(old_s, offered_salience)
            else:
                salience = 1.0 - (1.0 - old_s) * (1.0 - float(salience))
            prior = {**existing, "salience": old_s}
            if (existing.get("kind") == "sensory"
                    and item.get("kind") == "sensory"):
                event_ids = list(existing.get("perception_event_ids") or [])
                for event_id in item.get("perception_event_ids") or []:
                    if event_id not in event_ids:
                        event_ids.append(event_id)
                item["perception_event_ids"] = event_ids
            item = {**existing, **item}
        last_offered = now if existing else item.get("last_offered", now)
        item.update({"key": key,
                      "salience": max(0.0, min(1.0, float(salience))),
                      "born": item.get("born", now),
                      "last_offered": last_offered,
                      "updated": now})
        self._seq += 1
        kept.append((-item["salience"], self._seq, item))
        heapq.heapify(kept)
        self._heap = kept
        if meta.get("operation") == "requeued":
            self._notify("candidate_requeued", item,
                         meta.get("reason", "requeued"), now)
        elif existing:
            self._notify(
                "candidates_merged", prior, item,
                meta.get("components") or {"offered_salience": offered_salience},
                meta.get("inputs") or {}, now,
                raw_ref=meta.get("raw_ref"), ownership=meta.get("ownership"),
                receipts=meta.get("receipts"))
        else:
            self._notify(
                "candidate_offered", item,
                meta.get("components") or {"offered_salience": offered_salience},
                meta.get("inputs") or {}, now,
                raw_ref=meta.get("raw_ref"), ownership=meta.get("ownership"),
                receipts=meta.get("receipts"))
        return item

    def _effective(self, item, now):
        return _decay(float(item.get("salience", 0.0)),
                      float(now) - float(item.get("updated", now)),
                      self.half_life_s)

    def decay(self, floor: float = CANDIDATE_FLOOR,
              now: float = None, rate=None):
        now = time.time() if now is None else float(now)
        keep, dropped = [], 0
        for _neg, seq, item in self._heap:
            prior = float(item.get("salience", 0.0))
            value = (float(item.get("salience", 0.0)) * float(rate)
                     if rate is not None else self._effective(item, now))
            if value < floor:
                dropped += 1
                self._notify("candidate_expired", dict(item), value, now)
                continue
            item["salience"], item["updated"] = value, now
            if value != prior:
                self._notify("candidate_decayed", item, prior, value, now)
            keep.append((-value, seq, item))
        heapq.heapify(keep)
        self._heap = keep
        return dropped

    def discard_where(self, predicate, *, reason: str, now: float = None):
        """Withdraw candidates invalidated by newer source authority."""
        now = time.time() if now is None else float(now)
        kept, removed = [], []
        for neg, seq, item in self._heap:
            if predicate(item):
                removed.append(dict(item))
                self._notify("candidate_withdrawn", item, reason, now)
            else:
                kept.append((neg, seq, item))
        heapq.heapify(kept)
        self._heap = kept
        return removed

    def pop(self, now: float = None, scorer=None):
        now = time.time() if now is None else float(now)
        self.decay(now=now)
        if not self._heap:
            return None
        # Some consequences have a mechanically authored completion edge.
        # Keep their candidate in the field, but do not let it compete before
        # that edge (for example: a body must arrive before choosing its next
        # movement). This is causal eligibility, not interval polling.
        eligible = [
            (index, row) for index, row in enumerate(self._heap)
            if float(row[2].get("available_after") or 0.0) <= now
        ]
        if not eligible:
            return None
        selection = None
        if scorer is None:
            _neg, _sequence, heap_index, _row = min(
                (row[0], row[1], index, row)
                for index, row in eligible)
            winner = self._heap.pop(heap_index)[2]
            heapq.heapify(self._heap)
        else:
            ranked = []
            for index, row in eligible:
                projected = scorer(row[2])
                if isinstance(projected, tuple):
                    score, meta = projected
                else:
                    score, meta = projected, {}
                ranked.append((float(score), -row[1], index, dict(meta or {})))
            score, _sequence, index, meta = max(ranked)
            if score < 0.0:
                # A negative score is an explicit causal ineligibility (for
                # example, the single private-work controller is occupied),
                # not merely weak salience. Preserve every candidate rather
                # than popping the least-impossible one.
                return None
            winner = self._heap.pop(index)[2]
            heapq.heapify(self._heap)
            selection = {"effective_salience": max(0.0, min(1.0, score)),
                         **meta}
            alternatives = [value for value in ranked if value[2] != index]
            runner_up = max(
                (value[0] for value in alternatives), default=None)
            # Preserve the already-computed, text-free selection evidence for
            # the winning organ. Async consequences otherwise cannot tell a
            # weak opportunity from a well-supported quiet choice without
            # reconstructing it from the observatory history.
            receipt_keys = {
                "effective_salience", "base_salience", "source_key",
                "source_satiety", "scope_satiety", "combined_satiety",
                "rested_salience", "action_eligible", "action_readiness",
                "action_contribution", "document_reader_eligible",
                "document_reader_readiness", "document_reader_satiety",
                "maintenance_eligible", "maintenance_gate",
            }
            safe_selection = {
                key: value for key, value in selection.items()
                if key in receipt_keys
            }
            winner["selection_receipt"] = {
                **safe_selection,
                "candidate_count": len(ranked),
                "runner_up_effective_salience": (
                    max(0.0, min(1.0, runner_up))
                    if runner_up is not None else None),
                "runner_up_score": (
                    max(0.0, min(1.0, runner_up))
                    if runner_up is not None else None),
                "effective_margin": (
                    round(score - runner_up, 6)
                    if runner_up is not None else None),
                "winner_margin": (
                    round(score - runner_up, 6)
                    if runner_up is not None else None),
                "competition_case": (
                    "one_candidate" if len(ranked) == 1
                    else "full_competition"),
            }
        self._notify("candidate_won", winner,
                     [row[2] for row in sorted(self._heap)], now,
                     selection=selection)
        return winner

    def selection_projection(self, now: float = None, scorer=None,
                             transform=None, *, include_empty=False):
        """Project a winner without mutating, decaying, or popping the field."""
        now = time.time() if now is None else float(now)
        eligible = [
            (index, row) for index, row in enumerate(self._heap)
            if float(row[2].get("available_after") or 0.0) <= now
        ]
        if not eligible:
            return ({
                "winner_key": None,
                "winner_work_revision": None,
                "winner_source_revision": None,
                "winner_score": None,
                "runner_up_score": None,
                "winner_margin": None,
                "candidate_count": 0,
                "transformed_count": 0,
                "selection_meta": {},
                "competition_case": "no_candidate",
            } if include_empty else None)
        ranked = []
        transformed_count = 0
        for index, row in eligible:
            candidate = dict(row[2])
            changed = False
            if callable(transform):
                transformed = transform(candidate)
                if isinstance(transformed, tuple):
                    candidate, changed = transformed
                else:
                    candidate = transformed
                    changed = candidate != row[2]
            transformed_count += int(bool(changed))
            projected = (scorer(candidate) if scorer is not None
                         else self._effective(candidate, now))
            if isinstance(projected, tuple):
                score, meta = projected
            else:
                score, meta = projected, {}
            ranked.append((float(score), -row[1], index, candidate,
                           dict(meta or {})))
        score, _sequence, index, candidate, meta = max(ranked)
        if score < 0.0:
            return ({
                "winner_key": None,
                "winner_work_revision": None,
                "winner_source_revision": None,
                "winner_score": None,
                "runner_up_score": None,
                "winner_margin": None,
                "candidate_count": len(ranked),
                "transformed_count": transformed_count,
                "selection_meta": {},
                "competition_case": "causally_ineligible",
            } if include_empty else None)
        alternatives = [value for value in ranked if value[2] != index]
        runner_up = max((value[0] for value in alternatives), default=None)
        return {
            "winner_key": str(candidate.get("key") or ""),
            "winner_work_revision": str(
                candidate.get("work_revision") or "")[:96],
            "winner_source_revision": str(
                candidate.get("source_revision") or "")[:96],
            "winner_score": max(0.0, min(1.0, score)),
            "runner_up_score": (
                max(0.0, min(1.0, runner_up))
                if runner_up is not None else None),
            "winner_margin": (
                round(score - runner_up, 6)
                if runner_up is not None else None),
            "candidate_count": len(ranked),
            "transformed_count": transformed_count,
            "selection_meta": meta,
            "competition_case": (
                "one_candidate" if len(ranked) == 1
                else "full_competition"),
        }

    def items(self, now: float = None):
        self.decay(now=now)
        return [row[2] for row in sorted(self._heap)]

    def snapshot_items(self):
        """Read persisted candidate bodies without decay or other mutation."""
        return [dict(row[2]) for row in sorted(self._heap)]

    def __len__(self):
        return len(self._heap)


def bypass_rest_conduct(item: dict):
    """Return the same candidate with an applied C4 salience bend removed."""
    candidate = dict(item or {})
    junction = dict(candidate.get("rest_junction") or {})
    if not junction.get("applied"):
        return candidate, False
    try:
        baseline = float(candidate.get("baseline_salience"))
        offered = float(candidate.get("offered_salience"))
        current = float(candidate.get("salience", offered))
    except (TypeError, ValueError):
        return candidate, False
    bypassed = baseline if offered <= 0.0 \
        else current * baseline / offered
    candidate["salience"] = max(0.0, min(1.0, bypassed))
    candidate["offered_salience"] = max(0.0, min(1.0, baseline))
    candidate["rest_junction"] = {
        **junction, "applied": False,
        "effective_mode": "counterfactual_bypass",
        "output": max(0.0, min(1.0, baseline)),
        "downstream_channels_touched": [],
    }
    return candidate, True


class IdleMetabolism:
    """Persisted pressure + salience + warmth, one source of truth."""

    VERSION = 3
    NARRATIVE_TERMINAL_LIMIT = 512

    def __init__(self, params: dict, path: str = None, state: dict = None):
        self.params = dict(params)
        self.path = path
        state = state or {}
        self.pressure = DriftPressure(params, state.get("pressure"))
        self.queue = DMNQueue(state.get("candidates"),
                              params.get("candidate_half_life_s", 1200.0))
        self.preoccupation = PreoccupationField(
            params.get("warmth_half_life_s", 14400.0),
            state.get("preoccupations"))
        self.satiety = PreoccupationField(
            params.get("candidate_half_life_s", 1200.0),
            state.get("source_satiety"))
        self.narrative_terminals = {}
        for stored_key, value in dict(
                state.get("narrative_terminals") or {}).items():
            if not isinstance(value, dict) or not value.get(
                    "attempt_revision"):
                continue
            revision = str(value.get("attempt_revision") or "")[:96]
            # Early schema-3 builds keyed the latest receipt by candidate.
            # Re-key on load so a model/prompt change and later reversion do
            # not resurrect an already terminal exact attempt.
            candidate_key = str(
                value.get("candidate_key") or stored_key or "")[:96]
            self.narrative_terminals[revision] = {
                "candidate_key": candidate_key,
                "attempt_revision": revision,
                "outcome": str(value.get("outcome") or "")[:48],
                "reason": str(value.get("reason") or "")[:96],
                "at": float(value.get("at") or 0.0),
            }
        self.observer = None

    def set_observer(self, observer):
        self.observer = observer
        self.queue.observer = observer
        return observer

    def resource_status(self, now: float = None) -> dict:
        """Content-free, non-decaying queue occupation for the R-1 audit."""
        now = time.time() if now is None else float(now)
        items = self.queue.snapshot_items()
        ages = [max(0.0, now - float(item.get("born") or now))
                for item in items]
        return {
            "schema_version": 1,
            "candidate_count": len(items),
            "eligible_count": sum(
                float(item.get("available_after") or 0.0) <= now
                for item in items),
            "revised_candidate_count": sum(
                bool(item.get("source_revision")) for item in items),
            "oldest_age_s": round(max(ages), 3) if ages else None,
            "read_method": "DMNQueue.snapshot_items",
            "decay_applied": False,
            "queue_mutated": False,
            "content_free": True,
        }

    @classmethod
    def load(cls, params: dict, path: str):
        state = {}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    state = json.load(handle)
            except (OSError, ValueError):
                state = {}
        return cls(params, path, state)

    def save(self, now: float = None, *, preserve_candidates: bool = False):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        candidates = (self.queue.snapshot_items() if preserve_candidates
                      else self.queue.items(now=now))
        data = {"version": self.VERSION, "pressure": self.pressure.to_dict(),
                "candidates": candidates,
                "preoccupations": self.preoccupation.nodes,
                "source_satiety": self.satiety.nodes,
                "narrative_terminals": self.narrative_terminals,
                "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    def narrative_terminal(self, candidate_key: str,
                           attempt_revision: str):
        candidate_key = str(candidate_key or "")[:96]
        revision = str(attempt_revision or "")[:96]
        record = self.narrative_terminals.get(revision)
        if record and record.get("candidate_key") == candidate_key:
            return dict(record)
        return None

    def mark_narrative_terminal(self, item: dict, outcome: str,
                                reason: str = "", now: float = None):
        key = str((item or {}).get("key") or "")[:96]
        revision = str((item or {}).get(
            "narrative_attempt_revision") or "")[:96]
        if not key or not revision:
            return None
        record = {
            "candidate_key": key,
            "attempt_revision": revision,
            "outcome": str(outcome or "")[:48],
            "reason": str(reason or "")[:96],
            "at": time.time() if now is None else float(now),
        }
        self.narrative_terminals[revision] = record
        if len(self.narrative_terminals) > self.NARRATIVE_TERMINAL_LIMIT:
            oldest = sorted(
                self.narrative_terminals,
                key=lambda value: float(
                    self.narrative_terminals[value].get("at") or 0.0))
            for stale in oldest[:-self.NARRATIVE_TERMINAL_LIMIT]:
                self.narrative_terminals.pop(stale, None)
        return dict(record)

    def bind_memory_lineages(self, memories: list) -> int:
        """Rebind persisted drift candidates to their stable source appetite.

        This is a content-free compatibility pass for candidates saved before
        lineage satiety existed. It changes neither salience nor queue order.
        """
        memories_by_id = {
            str(memory.get("id") or ""): memory
            for memory in memories or [] if memory.get("id")
        }
        rebound = 0
        for _negative, _sequence, item in self.queue._heap:
            if item.get("kind") != "drift":
                continue
            memory_id = str(
                item.get("key") or item.get("seed_id") or "").strip()
            memory = memories_by_id.get(memory_id)
            if memory is None:
                continue
            root = dmn_lineage_root(memory, memories_by_id) or memory_id
            satiety_key = f"memory:{root}"
            if item.get("satiety_key") == satiety_key:
                continue
            item["satiety_key"] = satiety_key
            item["lineage_root"] = root
            rebound += 1
        return rebound

    def offer_memory(self, memory: dict, recall_score: float,
                     emotional_charge: float = 0.0, now: float = None,
                     lineage_root: str = None):
        key = memory.get("id")
        if not key:
            return None
        warmth = self.preoccupation.warmth(key, now)
        # Recall fit, affect, and recurrence all influence the same field.
        salience = max(0.05, min(1.0, 0.45 * float(recall_score) +
                                0.25 * float(emotional_charge) +
                                0.30 * warmth))
        inputs = {"recall_score": float(recall_score),
                  "emotional_charge": float(emotional_charge),
                  "warmth": warmth}
        emotional_snapshot = dict(
            memory.get("emotional_snapshot") or {})
        def witnessed(name):
            try:
                value = float(emotional_snapshot.get(name, 0.0))
            except (TypeError, ValueError):
                value = 0.0
            return max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0
        play_affinity = max(
            witnessed("play"), .6 * witnessed("joy"))
        # Descriptive provenance for PD1-S only. It is deliberately absent
        # from `components`, so it cannot alter live salience.
        inputs["play_affinity"] = play_affinity
        components = {"recall_score": 0.45 * inputs["recall_score"],
                      "emotional_charge": 0.25 * inputs["emotional_charge"],
                      "warmth": 0.30 * inputs["warmth"]}
        if salience > sum(components.values()):
            components["floor_lift"] = salience - sum(components.values())
        memory_source = memory_source_provenance(memory)
        lineage_root = str(
            lineage_root or dmn_lineage_root(memory) or key).strip()
        return self.queue.put({"kind": "drift", "key": key,
                               "seed_id": key,
                               # A generated descendant is a new memory, but
                               # not a new appetite. Satiety follows the
                               # content-free provenance chain.
                               "satiety_key": f"memory:{lineage_root}",
                               "lineage_root": lineage_root,
                               "play_affinity": play_affinity,
                               "node": (memory.get("content") or "")[:240],
                               "memory_source": memory_source,
                               "entities": list(memory.get("entities") or [])[:4]},
                               salience, now=now,
                               offer_meta={"components": components,
                                           "inputs": inputs,
                                           "merge": "refresh",
                                           "raw_ref": key,
                                           "receipts": [key]})

    def _offer_event(self, kind: str, source: str, content: str,
                     features: dict = None, key: str = None,
                     now: float = None, raw_ref=None, ownership=None,
                     receipts=None, *, salience: float = None,
                     source_revision: str = "", work_revision: str = "",
                     salience_receipt: dict = None,
                     projection_context: dict = None):
        """Admit one observed event into the same candidate field.

        Features are observations in 0..1 ranges.  No single Boolean makes an
        event important; novelty, state change, bodily intensity,
        relationship relevance, and unresolvedness contribute together.
        """
        if kind not in {"sensory", "cognitive"}:
            raise ValueError("field event kind must be sensory or cognitive")
        features = dict(features or {})
        baseline_salience, bounded, components = event_salience(features)
        offered_salience = (
            max(0.0, min(1.0, float(salience)))
            if salience is not None else baseline_salience)
        if key is None:
            digest = hashlib.sha256((source + "\0" + content).encode(
                "utf-8", errors="replace")).hexdigest()[:20]
            key = f"{source}:{digest}"
        item = {"kind": kind, "source": source,
                "key": key, "node": content[:1200],
                "features": bounded,
                "ownership": ownership,
                "perception_event_ids": list(receipts or [])}
        source_revision = str(source_revision or "")[:96]
        if source_revision:
            item.update({
                "source_revision": source_revision,
                "work_revision": str(work_revision or "")[:96],
                "baseline_salience": round(baseline_salience, 9),
                "offered_salience": round(offered_salience, 9),
                "rest_junction": dict(salience_receipt or {}),
                "maintenance_context": dict(projection_context or {}),
            })
        return self.queue.put(
            item, offered_salience, now=now,
            offer_meta={
                "merge": "evidence_revision" if source_revision else None,
                "components": {
                    **components,
                    **({"rest_junction_delta": round(
                        offered_salience - baseline_salience, 9)}
                       if source_revision else {}),
                },
                "inputs": bounded,
                "raw_ref": raw_ref,
                "ownership": ownership,
                "receipts": receipts,
                "rest_junction": dict(salience_receipt or {}),
            })

    def offer_event(self, source: str, content: str, features: dict = None,
                    key: str = None, now: float = None, raw_ref=None,
                    ownership=None, receipts=None, **projection):
        """Admit an exteroceptive event without changing the legacy shape."""
        return self._offer_event(
            "sensory", source, content, features, key, now, raw_ref,
            ownership, receipts, **projection)

    def offer_cognitive_event(
            self, source: str, content: str, features: dict = None,
            key: str = None, now: float = None, raw_ref=None,
            ownership=None, receipts=None, **projection):
        """Admit an internally produced consequence through the same math."""
        return self._offer_event(
            "cognitive", source, content, features, key, now, raw_ref,
            ownership, receipts, **projection)

    def offer_consolidation(self, *, source_cursor: int,
                            eligible_count: int,
                            pending_source_chars: int,
                            source_char_budget: int,
                            first_source_digest: str = None,
                            last_source_digest: str = None,
                            salience: float = None,
                            salience_receipt: dict = None,
                            now: float = None):
        """Offer narrative folding to the same field as every other pull.

        Backlog fullness is continuous rather than a count gate.  The DMN's
        substrate pressure decides when attention is available; this value
        only lets consolidation compete for what that attention does.
        """
        pending = max(0, int(pending_source_chars))
        budget = max(1, int(source_char_budget))
        fill = pending / (pending + budget) if pending else 0.0
        if int(eligible_count) <= 0 or fill <= 0.0:
            return None
        inputs = {
            "eligible_count": int(eligible_count),
            "pending_source_chars": pending,
            "source_char_budget": budget,
        }
        item = {
            "kind": "consolidation",
            "key": "consolidation:rolling_gist",
            "source_cursor": int(source_cursor),
            "eligible_count": int(eligible_count),
            "pending_source_chars": pending,
            "source_char_budget": budget,
            "first_source_digest": first_source_digest,
            "last_source_digest": last_source_digest,
        }
        item["source_revision"] = hashlib.sha256(json.dumps({
            "source_cursor": item["source_cursor"],
            "eligible_count": item["eligible_count"],
            "pending_source_chars": item["pending_source_chars"],
            "source_char_budget": item["source_char_budget"],
            "first_source_digest": item["first_source_digest"],
            "last_source_digest": item["last_source_digest"],
        }, sort_keys=True, separators=(",", ":")).encode(
            "utf-8")).hexdigest()[:24]
        offered_salience = (
            max(0.0, min(1.0, float(salience)))
            if salience is not None else fill)
        item["baseline_salience"] = round(fill, 9)
        item["offered_salience"] = round(offered_salience, 9)
        item["rest_junction"] = dict(salience_receipt or {})
        return self.queue.put(
            item, offered_salience, now=now,
            offer_meta={
                "merge": "evidence_revision",
                "components": {
                    "source_budget_fill": fill,
                    "rest_junction_delta": round(
                        offered_salience - fill, 9),
                },
                "inputs": inputs,
                "receipts": [digest for digest in
                             (first_source_digest, last_source_digest)
                             if digest],
                "rest_junction": dict(salience_receipt or {}),
            })

    def narrative_cluster_projection(self, neighborhood: dict,
                                     recall_score: float,
                                     now: float = None):
        """Project private neighborhood salience without mutating the queue."""
        if not isinstance(neighborhood, dict) \
                or neighborhood.get("status") != "ready":
            return None
        seed_id = str(neighborhood.get("seed_id") or "")
        candidate_ids = [str(memory_id) for memory_id in
                         neighborhood.get("candidate_ids", [])]
        locality = neighborhood.get("semantic_locality")
        if not seed_id or len(candidate_ids) < 2 or locality is None:
            return None
        recall_fit = max(0.0, min(1.0, float(recall_score)))
        locality = max(0.0, min(1.0, float(locality)))
        warmth = self.preoccupation.warmth(seed_id, now)
        base = (recall_fit + locality) / 2.0
        warmth_residual = (1.0 - base) * warmth
        return {
            "salience": base + warmth_residual,
            "recall_fit": recall_fit,
            "locality": locality,
            "warmth": warmth,
            "base": base,
            "warmth_residual": warmth_residual,
            "seed_id": seed_id,
            "candidate_ids": candidate_ids,
        }

    def offer_narrative_cluster(self, neighborhood: dict,
                                recall_score: float,
                                salience: float = None,
                                salience_receipt: dict = None,
                                source_revision: str = "",
                                narrative_attempt_revision: str = "",
                                narrative_model: str = "",
                                narrative_prompt_version: str = "",
                                now: float = None):
        """Let one recalled local neighborhood compete in the same field.

        Geometry is evidence, never membership.  The model is consulted only
        if this mechanical projection wins a genuine substrate fire.
        """
        projection = self.narrative_cluster_projection(
            neighborhood, recall_score, now=now)
        if projection is None:
            return None
        seed_id = projection["seed_id"]
        candidate_ids = projection["candidate_ids"]
        recall_fit = projection["recall_fit"]
        locality = projection["locality"]
        warmth = projection["warmth"]
        base = projection["base"]
        warmth_residual = projection["warmth_residual"]
        baseline_salience = projection["salience"]
        offered_salience = (
            max(0.0, min(1.0, float(salience)))
            if salience is not None else baseline_salience)
        seed_digest = hashlib.sha256(seed_id.encode(
            "utf-8", errors="replace")).hexdigest()[:20]
        candidate_key = f"narrative_cluster:{seed_digest}"
        if narrative_attempt_revision and self.narrative_terminal(
                candidate_key, narrative_attempt_revision):
            return None
        receipts = [hashlib.sha256(memory_id.encode(
            "utf-8", errors="replace")).hexdigest()[:16]
                    for memory_id in candidate_ids]
        inputs = {
            "seed_recall_score": recall_fit,
            "semantic_locality": locality,
            "seed_warmth": warmth,
            "candidate_count": len(candidate_ids),
            "semantic_width": int(neighborhood.get("semantic_width", 0)),
            "context_width": int(neighborhood.get("context_width", 0)),
            "channel_overlap": int(neighborhood.get("channel_overlap", 0)),
        }
        item = {
            "kind": "narrative_cluster",
            "key": candidate_key,
            "seed_id": seed_id,
            "candidate_ids": candidate_ids,
            "semantic_ids": list(neighborhood.get("semantic_ids") or []),
            "context_ids": list(neighborhood.get("context_ids") or []),
            "eligible_count": int(neighborhood.get("eligible_count", 0)),
            "vector_covered": int(neighborhood.get("vector_covered", 0)),
            "explicit_context_covered": int(
                neighborhood.get("explicit_context_covered", 0)),
            "semantic_width": inputs["semantic_width"],
            "context_width": inputs["context_width"],
            "semantic_locality": locality,
            "channel_overlap": inputs["channel_overlap"],
            "seed_recall_score": recall_fit,
            "seed_warmth": warmth,
            "source_revision": str(source_revision or "")[:64],
            "narrative_attempt_revision": str(
                narrative_attempt_revision or "")[:96],
            "narrative_model": str(narrative_model or "")[:96],
            "narrative_prompt_version": str(
                narrative_prompt_version or "")[:96],
            "baseline_salience": round(baseline_salience, 9),
            "offered_salience": round(offered_salience, 9),
            "rest_junction": dict(salience_receipt or {}),
        }
        return self.queue.put(
            item, offered_salience, now=now,
            offer_meta={
                "merge": "evidence_revision",
                "components": {"seed_context_fit": base,
                               "warmth_residual": warmth_residual,
                               "rest_junction_delta": round(
                                   offered_salience - baseline_salience, 9)},
                "inputs": inputs,
                "raw_ref": seed_digest,
                "receipts": receipts,
                "rest_junction": dict(salience_receipt or {}),
            })

    @staticmethod
    def source_key(item: dict) -> str:
        scoped = str((item or {}).get("satiety_key") or "").strip()
        if scoped:
            return scoped
        kind = str((item or {}).get("kind") or "unknown")
        if kind == "drift":
            memory_key = str(
                (item or {}).get("key")
                or (item or {}).get("seed_id") or "").strip()
            if memory_key:
                return f"memory:{memory_key}"
        source = str((item or {}).get("source") or "")
        return f"{kind}:{source}" if source else kind

    def attention_score(self, item: dict, *, now: float = None,
                        action_readiness: float = 0.0,
                        action_eligible: bool = False,
                        scope_satiety: float = 0.0):
        """Return consequence-shaped selection score plus its full receipt."""
        now = time.time() if now is None else float(now)
        base = self.queue._effective(item, now)
        source = self.source_key(item)
        source_satiety = self.satiety.warmth(source, now)
        scope_satiety = max(0.0, min(1.0, float(scope_satiety)))
        combined_satiety = 1.0 - (
            (1.0 - source_satiety) * (1.0 - scope_satiety))
        rested = base / (1.0 + combined_satiety)
        readiness = max(0.0, min(1.0, float(action_readiness))) \
            if action_eligible else 0.0
        action_contribution = rested * readiness
        score = 1.0 - (1.0 - rested) * (1.0 - action_contribution)
        return score, {
            "base_salience": round(base, 6),
            "source_key": source,
            "source_satiety": round(source_satiety, 6),
            "scope_satiety": round(scope_satiety, 6),
            "combined_satiety": round(combined_satiety, 6),
            "rested_salience": round(rested, 6),
            "action_eligible": bool(action_eligible),
            "action_readiness": round(readiness, 6),
            "action_contribution": round(action_contribution, 6),
        }

    def satiate(self, item: dict, completion: float = 1.0,
                now: float = None) -> float:
        """Feed a successful consequence back into its source's next pull."""
        now = time.time() if now is None else float(now)
        source = self.source_key(item)
        intensity = max(0.0, min(1.0, float(completion))) * max(
            0.0, min(1.0, float((item or {}).get("salience", 0.0))))
        prior = self.satiety.warmth(source, now)
        new = self.satiety.touch(source, intensity, label=source, now=now)
        if self.observer is not None:
            self.observer.field_effect(
                str((item or {}).get("key") or source),
                f"source_satiety:{source}", prior, new, now)
        return new

    def discharge(self, now: float = None, scorer=None):
        item = self.queue.pop(now, scorer=scorer)
        # A narrative fold closes its cycle through the updated gist in later
        # prompts.  It is not a preoccupation and must not warm recall merely
        # because it won before the transactional write succeeds.
        if item and item.get("kind") not in {
                "consolidation", "narrative_cluster"}:
            prior = self.preoccupation.warmth(item["key"], now)
            new = self.preoccupation.touch(
                item["key"], 0.15 + 0.35 * item["salience"],
                label=item.get("node"), now=now)
            if self.observer is not None:
                try:
                    self.observer.field_effect(
                        item["key"], "preoccupation_warmth", prior, new, now)
                except Exception as exc:
                    try:
                        print("[salience-observatory] field effect failed: "
                              + str(exc)[:240])
                    except Exception:
                        pass
        return item
