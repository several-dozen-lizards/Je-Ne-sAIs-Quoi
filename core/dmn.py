"""The idle metabolism: a persisted, inspectable circulation.

Pressure decides *when* attention becomes available.  A salience field
decides *what* receives it.  Discharge changes memory/preoccupation and
therefore changes the next field: output returns as input.

This module is deliberately pure apart from IdleMetabolism.load/save.  It
owns no thread, model, memory organ, or clock; cockpit wiring hands it all
observations and performs all effects.
"""
import heapq
import json
import math
import os
import random
import time
from collections import deque

SALIENCE_SKIP = 0.0
SALIENCE_LOW = 0.3
SALIENCE_NORMAL = 0.5
SALIENCE_ELEVATED = 0.7
SALIENCE_URGENT = 1.0

DEFAULTS = {"enabled": False, "level": "normal", "idle_model": None}

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
        elif key in ("enabled", "idle_model", "level"):
            out[key] = value if key != "level" else level
    out["enabled"] = bool(out.get("enabled"))
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


class DMNQueue:
    """A de-duplicating, decaying field of competing impulses."""

    def __init__(self, items=None, half_life_s: float = 1200.0):
        self._heap = []
        self._seq = 0
        self.half_life_s = float(half_life_s)
        for item in items or []:
            self.put(item, item.get("salience", SALIENCE_NORMAL),
                     now=item.get("updated") or item.get("born"))

    def put(self, item: dict, salience: float, now: float = None):
        now = time.time() if now is None else float(now)
        item = dict(item)
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
            salience = 1.0 - (1.0 - old_s) * (1.0 - float(salience))
            item = {**existing, **item}
        item.update({"key": key,
                     "salience": max(0.0, min(1.0, float(salience))),
                     "born": item.get("born", now), "updated": now})
        self._seq += 1
        kept.append((-item["salience"], self._seq, item))
        heapq.heapify(kept)
        self._heap = kept
        return item

    def _effective(self, item, now):
        return _decay(float(item.get("salience", 0.0)),
                      float(now) - float(item.get("updated", now)),
                      self.half_life_s)

    def decay(self, floor: float = 0.05, now: float = None, rate=None):
        now = time.time() if now is None else float(now)
        keep, dropped = [], 0
        for _neg, seq, item in self._heap:
            value = (float(item.get("salience", 0.0)) * float(rate)
                     if rate is not None else self._effective(item, now))
            if value < floor:
                dropped += 1
                continue
            item["salience"], item["updated"] = value, now
            keep.append((-value, seq, item))
        heapq.heapify(keep)
        self._heap = keep
        return dropped

    def pop(self, now: float = None):
        self.decay(now=now)
        return None if not self._heap else heapq.heappop(self._heap)[2]

    def items(self, now: float = None):
        self.decay(now=now)
        return [row[2] for row in sorted(self._heap)]

    def __len__(self):
        return len(self._heap)


class IdleMetabolism:
    """Persisted pressure + salience + warmth, one source of truth."""

    VERSION = 1

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

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = {"version": self.VERSION, "pressure": self.pressure.to_dict(),
                "candidates": self.queue.items(),
                "preoccupations": self.preoccupation.nodes,
                "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    def offer_memory(self, memory: dict, recall_score: float,
                     emotional_charge: float = 0.0, now: float = None):
        key = memory.get("id")
        if not key:
            return None
        warmth = self.preoccupation.warmth(key, now)
        # Recall fit, affect, and recurrence all influence the same field.
        salience = max(0.05, min(1.0, 0.45 * float(recall_score) +
                                0.25 * float(emotional_charge) +
                                0.30 * warmth))
        return self.queue.put({"kind": "drift", "key": key,
                               "seed_id": key,
                               "node": (memory.get("content") or "")[:240],
                               "entities": list(memory.get("entities") or [])[:4]},
                              salience, now=now)

    def discharge(self, now: float = None):
        item = self.queue.pop(now)
        if item:
            self.preoccupation.touch(item["key"],
                                     0.15 + 0.35 * item["salience"],
                                     label=item.get("node"), now=now)
        return item
