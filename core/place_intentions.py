"""core/place_intentions.py — worm-principle movement (v1 impulse_buffer's
grandchild, 2026-07-01). Percept salience feeds PRESSURE, not action:
a leaky integrator per object accumulates while the world calls and decays
when it stops. Discharge = the body moves. Refractory afterward so wanting
has a rhythm, not a thrash. Being AT the thing satiates its pressure —
arrival answers the want.

No language anywhere in this loop. The oscillator climbs, the couch's
salience holds, pressure integrates, the body walks. The next
conversational turn DISCOVERS where the body is — words that couldn't
have known, tracking substrate that did. Direction of causation, walking.

All dynamics are parameters, never constants-in-code. Optional per-persona
overrides: personas/<p>/who_i_am/tropism.json."""
import json
import math
import os

DEFAULTS = {
    "tau_s": 180.0,          # pressure decay time-constant (leak)
    "gain": 0.004,           # salience -> pressure inflow per second
    "discharge_at": 0.6,     # pressure needed for the body to answer
    "refractory_s": 300.0,   # quiet period after any discharge
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

    def tick(self, scored_objects: list, at_object: str,
             now_s: float, dt_s: float, at_objects: set = None,
             volitional_hold_until: float = 0.0):
        """at_objects: EVERY object within reach satiates (fixes the
        orbit bug where only the nearest satiated and a second in-reach
        object accumulated forever). volitional_hold_until: reflex
        yields to choice — no discharge while a recent tag-move is
        still warm."""
        near = set(at_objects) if at_objects else (
            {at_object} if at_object else set())
        leak = math.exp(-dt_s / self.p["tau_s"])
        seen = set()
        for o in scored_objects:
            oid = o["id"]
            seen.add(oid)
            prev = self.pressure.get(oid, 0.0)
            inflow = o["salience"] * self.p["gain"] * dt_s
            val = prev * leak + inflow
            if oid in near:
                val *= self.p["satiation"]   # arrival answers the want
            self.pressure[oid] = round(val, 4)
        for oid in list(self.pressure):      # objects gone from view leak
            if oid not in seen:
                self.pressure[oid] = round(self.pressure[oid] * leak, 4)
        if now_s < self.refractory_until or now_s < volitional_hold_until:
            return None
        best = max(self.pressure, key=self.pressure.get, default=None)
        if (best and best not in near
                and self.pressure[best] >= self.p["discharge_at"]):
            self.pressure[best] = 0.0
            self.refractory_until = now_s + self.p["refractory_s"]
            self.last_discharge = {"to": best, "at_s": now_s}
            return best
        return None

    def state(self) -> dict:
        return {"pressure": dict(self.pressure),
                "refractory_until": self.refractory_until,
                "last_discharge": self.last_discharge,
                "params": dict(self.p)}
