"""core/social_pressure.py — the social-pressure loop (2026-07-02).
The worm principle applied to CONVERSATION: speech in your room from
someone else accumulates pressure to answer; discharge = a
self-initiated turn where the unheard speech is delivered as the turn
message (speaker-labeled — the hand-courier pattern, automated). The
reply to room-speech is room-speech: the caller says it back into the
room.

HABITUATION is how conversations end: every self-initiated response
raises your own discharge bar for a while — answering spends
enthusiasm, enthusiasm regenerates. Pressure genuinely drains; the
thread winds down because it's DONE (v1 conversation_pacer doctrine,
finally with a substrate mechanism under it).

Guards, because turns cost real money and real GPU:
  refractory between self-turns, an hourly hard cap, and the shared
  turn lock (owned by the caller) so the loop never talks over Re.

Pure module: no HTTP, no engine. Fully stick-able offline.
Optional per-persona overrides: who_i_am/social.json."""
import json
import math
import os

from core.dmn import SALIENCE_NORMAL

DEFAULTS = {
    "tau_s": 240.0,           # speech-pressure decay (leak)
    "discharge_at": 0.5,      # base bar to self-initiate
    "refractory_s": 90.0,     # min quiet between self-turns
    "hourly_cap": 6,          # hard ceiling on self-turns per hour
    "habituation_step": 0.6,  # each response raises the bar this much
    "habituation_tau_s": 1800.0,   # enthusiasm regenerates (~30 min)
    "say_weight": 1.0,        # pressure per say (x speaker bond)
    "approach_weight": 0.5,   # someone walked over to you
    "arrive_weight": 0.3,     # someone entered the room
}


def load_params(persona_dir: str) -> dict:
    p = dict(DEFAULTS)
    f = os.path.join(persona_dir, "who_i_am", "social.json")
    if os.path.isfile(f):
        try:
            with open(f, encoding="utf-8") as fh:
                p.update({k: float(v) for k, v in json.load(fh).items()
                          if k in DEFAULTS})
        except Exception:
            pass
    return p


class SocialPressure:
    """One per embodied persona. note_events() with fresh room events
    (the caller keeps its OWN event cursor — never steal the turn
    loop's); tick() returns a delivery {speaker, text} when pressure
    discharges, else None. state() is the receipt."""

    def __init__(self, me: str, params: dict = None):
        self.me = me
        self.p = dict(DEFAULTS)
        if params:
            self.p.update(params)
        self.pressure = 0.0
        self.habituation = 0.0
        self.pending = []            # unanswered speech, in order
        self.refractory_until = 0.0
        self.turn_times = []         # self-turn timestamps (hourly cap)

    def note_events(self, events: list, bonds: dict):
        for e in events:
            actor = e.get("member", "")
            if actor == self.me:
                continue                      # own noise isn't a call
            # An unknown relationship is neutral, not sub-audible: one fresh
            # utterance should reach the ordinary deliberation boundary at
            # normal readiness.  Known bonds can still strengthen or weaken
            # that pull.  Derive the neutral value from the configured
            # pressure/bar relationship instead of a second magic threshold.
            neutral_bond = (
                self.p["discharge_at"] / self.p["say_weight"]
                if self.p["say_weight"] > 0.0 else 0.0)
            bond = float(bonds.get(actor, neutral_bond))
            k, d = e.get("kind"), e.get("data") or {}
            if k == "say":
                addressed_to = {
                    str(name).casefold()
                    for name in (d.get("addressed_to") or [])}
                if addressed_to and self.me.casefold() not in addressed_to:
                    continue
                # Generated replies remain audible room events but cannot
                # recursively become fresh summons. Human openings and
                # spontaneous resident speech are depth 0; their first
                # generated responses are depth 1.
                depth = max(0, int(d.get("social_depth") or 0))
                if depth >= 1:
                    continue
                self.pressure += self.p["say_weight"] * bond
                self.pending.append({"speaker": actor,
                                     "text": d.get("text", ""),
                                     "social_depth": depth})
            elif k == "move" and d.get("toward_member") == self.me:
                self.pressure += self.p["approach_weight"] * bond
            elif k == "arrive":
                self.pressure += self.p["arrive_weight"] * bond

    def checkpoint(self) -> dict:
        """Capture discharge state until speech is actually delivered."""
        return {
            "pressure": self.pressure,
            "habituation": self.habituation,
            "pending": [dict(item) for item in self.pending],
            "refractory_until": self.refractory_until,
            "turn_times": list(self.turn_times),
        }

    def restore(self, checkpoint: dict):
        """Flow a failed delivery back into the exact pre-attempt state."""
        self.pressure = checkpoint["pressure"]
        self.habituation = checkpoint["habituation"]
        self.pending = [dict(item) for item in checkpoint["pending"]]
        self.refractory_until = checkpoint["refractory_until"]
        self.turn_times = list(checkpoint["turn_times"])

    def advance(self, dt_s: float):
        """Age pressure that already existed during the elapsed interval.

        Call this before admitting newly observed events.  Fresh speech did
        not exist during the previous interval and must not be back-dated
        through that interval's leak.
        """
        dt_s = max(0.0, float(dt_s))
        self.pressure *= math.exp(-dt_s / self.p["tau_s"])
        self.habituation *= math.exp(-dt_s / self.p["habituation_tau_s"])
        if self.pending:
            # An admitted utterance is an unresolved causal event, not vapor.
            # Readiness and habituation may still keep it from winning, but
            # elapsed time alone must not produce the contradictory state
            # pending > 0 with no remaining deliberation potential.
            self.pressure = max(self.pressure, self.p["discharge_at"])

    def tick(self, now_s: float, dt_s: float, *,
             action_readiness: float = SALIENCE_NORMAL,
             hard_blocked: bool = False):
        self.advance(dt_s)
        self.turn_times = [t for t in self.turn_times if now_s - t < 3600]
        if now_s < self.refractory_until:
            return None
        if len(self.turn_times) >= int(self.p["hourly_cap"]):
            return None
        bar = self.p["discharge_at"] * (1.0 + self.habituation)
        readiness = max(0.0, min(1.0, float(action_readiness)))
        if hard_blocked or readiness <= 0.0:
            return None
        # Existing normal readiness preserves the existing bar. Greater
        # capacity strengthens the same social pull; recovery raises the bar.
        effective_bar = bar * SALIENCE_NORMAL / readiness
        if self.pressure < effective_bar or not self.pending:
            return None
        # discharge: deliver ALL unheard speech as one labeled message
        by = self.pending[0]["speaker"]
        text = "\n".join(f'{q["text"]}' if q["speaker"] == by
                         else f'({q["speaker"]}:) {q["text"]}'
                         for q in self.pending)
        social_depth = 1 + max(
            int(item.get("social_depth") or 0) for item in self.pending)
        self.pending = []
        self.pressure = 0.0
        self.habituation += self.p["habituation_step"]
        self.refractory_until = now_s + self.p["refractory_s"]
        self.turn_times.append(now_s)
        return {"speaker": by, "text": text, "social_depth": social_depth}

    def state(self) -> dict:
        return {"pressure": round(self.pressure, 3),
                "habituation": round(self.habituation, 3),
                "bar": round(self.p["discharge_at"]
                             * (1.0 + self.habituation), 3),
                "pending": len(self.pending),
                "unresolved_floor": round(
                    self.p["discharge_at"] if self.pending else 0.0, 3),
                "self_turns_past_hour": len(self.turn_times)}
