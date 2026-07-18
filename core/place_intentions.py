"""core/place_intentions.py — worm-principle movement (v1 impulse_buffer's
grandchild, 2026-07-01). Percept salience feeds PRESSURE, not action:
a leaky integrator per object accumulates while the world calls and decays
when it stops. Discharge = the body moves. Arrival settles the whole movement
field, while changed world salience or a persistently growing pull reopens it.
The refractory remains a hard anti-thrash floor, not the movement scheduler.

No language anywhere in this loop. The oscillator climbs, the couch's
salience holds, pressure integrates, the body walks. The next
conversational turn DISCOVERS where the body is — words that couldn't
have known, tracking substrate that did. Direction of causation, walking.

All dynamics are parameters, never constants-in-code. Optional per-persona
overrides: personas/<p>/who_i_am/tropism.json."""
import json
import math
import os

from core.dmn import SALIENCE_NORMAL

DEFAULTS = {
    "tau_s": 180.0,          # pressure decay time-constant (leak)
    "gain": 0.004,           # salience -> pressure inflow per second
    "discharge_at": 0.6,     # pressure needed for the body to answer
    "refractory_s": 0.0,     # optional compatibility floor, disabled by default
    "satiation": 0.25,       # extra decay multiplier while AT the object
}


def load_params(persona_dir: str) -> dict:
    p = dict(DEFAULTS)
    f = os.path.join(persona_dir, "who_i_am", "tropism.json")
    if os.path.isfile(f):
        try:
            with open(f, encoding="utf-8") as fh:
                p.update({k: float(v) for k, v in json.load(fh).items()
                          if k in DEFAULTS})
        except Exception:
            pass
    return p


class PlaceIntentions:
    """One instance per embodied persona. tick() with fresh salience;
    returns an object id when pressure discharges into movement, else
    None. state() is the receipt — watch her want things in a file."""

    def __init__(self, params: dict = None):
        self.p = dict(DEFAULTS)
        if params:
            self.p.update(params)
        self.pressure = {}        # oid -> accumulated want
        self.refractory_until = 0.0
        self.last_discharge = None
        self.salience_baseline = None
        self.awaiting_arrival_baseline = False
        self.last_gate = None

    @staticmethod
    def _salience_vector(scored_objects: list) -> dict:
        """The non-negative whole-world offer vector used for recovery."""
        out = {}
        for item in scored_objects:
            oid = item.get("id")
            if oid is None:
                continue
            try:
                value = float(item.get("salience", 0.0))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                out[str(oid)] = max(0.0, value)
        return out

    @staticmethod
    def _vector_novelty(current: dict, baseline: dict) -> float:
        """Bounded change in both distribution and magnitude of salience."""
        if baseline is None:
            return 1.0
        keys = set(current) | set(baseline)
        cur_total = sum(current.values())
        base_total = sum(baseline.values())
        if not keys or (cur_total <= 0.0 and base_total <= 0.0):
            return 0.0
        cur_share = {key: (current.get(key, 0.0) / cur_total
                           if cur_total > 0.0 else 0.0)
                     for key in keys}
        base_share = {key: (baseline.get(key, 0.0) / base_total
                            if base_total > 0.0 else 0.0)
                      for key in keys}
        distribution = 0.5 * sum(
            abs(cur_share[key] - base_share[key]) for key in keys)
        denominator = cur_total + base_total
        magnitude = (abs(cur_total - base_total) / denominator
                     if denominator > 0.0 else 0.0)
        novelty = 1.0 - ((1.0 - distribution) * (1.0 - magnitude))
        return max(0.0, min(1.0, novelty))

    def tick(self, scored_objects: list, at_object: str,
             now_s: float, dt_s: float, at_objects: set = None,
             volitional_hold_until: float = 0.0, *,
             action_readiness: float = SALIENCE_NORMAL,
             hard_blocked: bool = False):
        """at_objects: EVERY object within reach satiates (fixes the
        orbit bug where only the nearest satiated and a second in-reach
        object accumulated forever). volitional_hold_until: reflex
        yields to choice — no discharge while a recent tag-move is
        still warm."""
        near = set(at_objects) if at_objects else (
            {at_object} if at_object else set())
        salience = self._salience_vector(scored_objects)
        if self.awaiting_arrival_baseline:
            # tick() selects the move before RoomClient performs it.  The next
            # percept is therefore the first honest post-arrival world vector;
            # settle against that result instead of mistaking self-motion for
            # a fresh external invitation.
            self.salience_baseline = dict(salience)
            self.awaiting_arrival_baseline = False
        leak = math.exp(-dt_s / self.p["tau_s"])
        readiness = max(0.0, min(1.0, float(action_readiness)))
        inflow_scale = (readiness / SALIENCE_NORMAL
                        if not hard_blocked else 0.0)
        seen = set()
        for o in scored_objects:
            oid = o["id"]
            seen.add(oid)
            prev = self.pressure.get(oid, 0.0)
            inflow = (o["salience"] * self.p["gain"] * dt_s
                      * inflow_scale)
            val = prev * leak + inflow
            if oid in near:
                val *= self.p["satiation"]   # arrival answers the want
            self.pressure[oid] = round(val, 4)
        for oid in list(self.pressure):      # objects gone from view leak
            if oid not in seen:
                self.pressure[oid] = round(self.pressure[oid] * leak, 4)
        novelty = self._vector_novelty(salience, self.salience_baseline)
        # Arrival's existing satiation coefficient is also the minimum amount
        # of an unchanged pull that remains discharge-capable. Changed world
        # salience reopens the field; a stable pull must grow stronger.
        settlement_floor = max(0.0, min(1.0, self.p["satiation"]))
        recovery = max(settlement_floor, novelty)
        collective_pressure = sum(max(0.0, value)
                                  for value in self.pressure.values())
        best = max(self.pressure, key=self.pressure.get, default=None)
        raw_pressure = self.pressure.get(best, 0.0) if best else 0.0
        effective_pressure = raw_pressure * recovery
        blocked_by = []
        if hard_blocked:
            blocked_by.append("organism_recovery")
        if now_s < self.refractory_until:
            blocked_by.append("anti_thrash_floor")
        if now_s < volitional_hold_until:
            blocked_by.append("volitional_hold")
        if best in near:
            blocked_by.append("already_near")
        if effective_pressure < self.p["discharge_at"]:
            blocked_by.append("settled_pull")
        self.last_gate = {
            "candidate": best,
            "raw_pressure": round(raw_pressure, 4),
            "effective_pressure": round(effective_pressure, 4),
            "collective_pressure": round(collective_pressure, 4),
            "salience_novelty": round(novelty, 6),
            "recovery": round(recovery, 6),
            "blocked_by": blocked_by,
        }
        if blocked_by:
            return None
        if best:
            # A successful relocation settles the movement field as a whole.
            # Competing pulls survive as residues instead of remaining fully
            # loaded behind the refractory floor.
            for oid in self.pressure:
                self.pressure[oid] = round(
                    self.pressure[oid] * settlement_floor, 4)
            self.refractory_until = now_s + self.p["refractory_s"]
            self.salience_baseline = dict(salience)
            self.awaiting_arrival_baseline = True
            self.last_discharge = {
                "to": best, "at_s": now_s,
                "raw_pressure": round(raw_pressure, 4),
                "effective_pressure": round(effective_pressure, 4),
                "salience_novelty": round(novelty, 6),
                "recovery": round(recovery, 6),
            }
            self.last_gate["blocked_by"] = []
            self.last_gate["discharged"] = True
            return best
        return None

    def state(self) -> dict:
        return {"pressure": dict(self.pressure),
                "refractory_until": self.refractory_until,
                "last_discharge": self.last_discharge,
                "salience_baseline": (dict(self.salience_baseline)
                                      if self.salience_baseline is not None
                                      else None),
                "awaiting_arrival_baseline": self.awaiting_arrival_baseline,
                "gate": (dict(self.last_gate)
                         if self.last_gate is not None else None),
                "params": dict(self.p)}
