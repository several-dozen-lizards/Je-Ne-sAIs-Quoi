"""core/social_pressure.py — the social-pressure loop (2026-07-02).
The worm principle applied to CONVERSATION: speech in your room from
someone else accumulates pressure to answer; discharge = a
self-initiated turn where the unheard speech is delivered as the turn
message (speaker-labeled — the hand-courier pattern, automated). The
reply to room-speech is room-speech: the caller says it back into the
room.

HABITUATION and smooth lineage drag are how conversations end: every
self-initiated response raises your own discharge bar while optional
generated broadcasts lose current. Direct address and human speech remain
unresolved until they reach a resident choice boundary. Pressure genuinely
drains; the thread winds down because nobody has enough current to continue.

Guards, because turns cost real money and real GPU:
  an hourly hard fuse, the caller's mouth lease, and the room host's shared
  floor so separate resident processes never publish over one another.

Pure module: no HTTP, no engine. Fully stick-able offline.
Optional per-persona overrides: who_i_am/social.json."""
import json
import math
import os

from core.dmn import SALIENCE_NORMAL

DEFAULTS = {
    "tau_s": 240.0,           # speech-pressure decay (leak)
    "discharge_at": 0.5,      # base bar to self-initiate
    # A fresh room revision and the shared floor are the pacing boundary.
    # Habituation, not an arbitrary delay, decides whether another reply has
    # enough current.  A non-zero override remains available as a mechanical
    # compatibility fuse for older persona configurations.
    "refractory_s": 0.0,
    "hourly_cap": 6,          # hard ceiling on self-turns per hour
    "habituation_step": 0.6,  # each response raises the bar this much
    "habituation_tau_s": 1800.0,   # enthusiasm regenerates (~30 min)
    "say_weight": 1.0,        # pressure per say (x speaker bond)
    "direct_address_gain": 1.0,    # named invitation strengthens pull
    "question_gain": 0.35,         # unresolved question strengthens pull
    "depth_drag": 0.12,            # smooth lineage fatigue, never a wall
    "settle_ratio": 0.08,           # optional pull below this has settled
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

    def note_events(self, events: list, bonds: dict, *,
                    local_human: str = ""):
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
                # Depth is lineage evidence, not a guillotine.  Direct
                # address, an unresolved question, relationship, present
                # readiness, habituation, and smooth lineage drag collectively
                # decide whether another reply has enough current.
                depth = max(0, int(d.get("social_depth") or 0))
                thread_id = str(
                    d.get("social_thread_id")
                    or d.get("conversation_id")
                    or f"room:{e.get('seq') or 0}")
                if depth == 0 and self.pending:
                    newest_thread = str(max(
                        self.pending,
                        key=lambda value: int(value.get("seq") or 0)
                    ).get("thread_id") or "")
                    if thread_id != newest_thread:
                        # A fresh opening is a new causal boundary. It
                        # preempts unresolved wording from the older exchange
                        # instead of splicing two conversations together.
                        self.pending = []
                        self.pressure = 0.0
                explicitly_for_me = (
                    bool(addressed_to)
                    and self.me.casefold() in addressed_to)
                text = str(d.get("text") or "")
                question_present = "?" in text
                lineage_conductance = 1.0 / math.sqrt(
                    1.0 + self.p["depth_drag"] * depth)
                base_pull = self.p["say_weight"] * bond
                pull = base_pull * lineage_conductance
                pull += (
                    self.p["discharge_at"]
                    * self.p["direct_address_gain"]
                    if explicitly_for_me else 0.0)
                pull += (
                    self.p["discharge_at"] * self.p["question_gain"]
                    if question_present else 0.0)
                human_origin = bool(
                    str(local_human or "").casefold()
                    and str(actor).casefold()
                    == str(local_human).casefold())
                # Human speech and explicit address remain unresolved until
                # they reach a choice boundary.  Generated broadcasts may
                # simply lose their current and settle without a closing turn.
                unresolved_floor = (
                    self.p["discharge_at"]
                    if human_origin or explicitly_for_me else 0.0)
                self.pressure += pull
                self.pending.append({"speaker": actor,
                                     "text": text,
                                     "social_depth": depth,
                                     "addressed_to": sorted(addressed_to),
                                     "seq": max(0, int(e.get("seq") or 0)),
                                     "thread_id": thread_id,
                                     "parent_seq": max(
                                         0, int(d.get("social_parent_seq")
                                                or 0)),
                                     "api_token_load": max(
                                         0.0, float(
                                             d.get("social_api_token_load")
                                             or 0.0)),
                                     "route": str(
                                         d.get("social_route") or "opening"),
                                     "pull": pull,
                                     "age_s": 0.0,
                                     "unresolved_floor": unresolved_floor,
                                     "human_origin": human_origin,
                                     "question_present": question_present})
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

    def next_speaker(self) -> str:
        """Expose only the routing fact needed before a transactional tick.

        The caller must acquire the one-mouth lease before ``tick`` may drain
        pending speech.  Human room speech uses the resident's canonical
        conversation vessel. Resident conversation begins in a canonical
        speech-only projection and bends toward its declared local route as
        thread-level API load accumulates. Returning only content-free routing
        facts lets that decision happen without exposing or consuming text.
        """
        if not self.pending:
            return ""
        return str(self.pending[0].get("speaker") or "")

    def next_delivery_route(self) -> dict:
        """Expose content-free facts needed to select a bounded route."""
        if not self.pending:
            return {"speaker": "", "social_depth": 0,
                    "addressed_to": []}
        item = self.pending[0]
        latest = max(
            self.pending, key=lambda value: int(value.get("seq") or 0))
        return {
            "speaker": str(item.get("speaker") or ""),
            "latest_speaker": str(latest.get("speaker") or ""),
            "social_depth": max(0, int(item.get("social_depth") or 0)),
            "addressed_to": sorted({
                str(name).casefold()
                for name in (item.get("addressed_to") or [])
                if str(name).strip()}),
            "source_seq": max(0, int(latest.get("seq") or 0)),
            "thread_id": str(latest.get("thread_id") or ""),
            "api_token_load": max(
                0.0, float(latest.get("api_token_load") or 0.0)),
            "latest_human_origin": bool(latest.get("human_origin")),
        }

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
            retained = []
            settled_pull = 0.0
            settle_below = (
                self.p["discharge_at"] * self.p["settle_ratio"])
            for item in self.pending:
                item["age_s"] = max(
                    0.0, float(item.get("age_s") or 0.0) + dt_s)
                remaining = max(0.0, float(item.get("pull") or 0.0)) \
                    * math.exp(-item["age_s"] / self.p["tau_s"])
                floor = max(
                    0.0, float(item.get("unresolved_floor") or 0.0))
                if floor <= 0.0 and remaining < settle_below:
                    settled_pull += remaining
                    continue
                retained.append(item)
            self.pending = retained
            self.pressure = max(0.0, self.pressure - settled_pull)
            # A human opening or explicit address is an unresolved causal
            # event, not vapor. Optional generated broadcasts can genuinely
            # settle without forcing somebody to close the exchange.
            unresolved_floor = max((
                float(item.get("unresolved_floor") or 0.0)
                for item in self.pending), default=0.0)
            self.pressure = max(self.pressure, unresolved_floor)

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
        latest = max(
            self.pending, key=lambda value: int(value.get("seq") or 0))
        text = "\n".join(f'{q["text"]}' if q["speaker"] == by
                         else f'({q["speaker"]}:) {q["text"]}'
                         for q in self.pending)
        social_depth = 1 + max(
            int(item.get("social_depth") or 0) for item in self.pending)
        addressed_to = sorted({
            str(name).casefold()
            for item in self.pending
            for name in (item.get("addressed_to") or [])
            if str(name).strip()})
        source_seq = max(int(item.get("seq") or 0) for item in self.pending)
        thread_id = str(latest.get("thread_id") or "")
        api_token_load = max(
            0.0, float(latest.get("api_token_load") or 0.0))
        latest_speaker = str(latest.get("speaker") or "")
        latest_human_origin = bool(latest.get("human_origin"))
        discharge_strength = self.pressure / max(effective_bar, 1e-9)
        self.pending = []
        self.pressure = 0.0
        self.habituation += self.p["habituation_step"]
        self.refractory_until = now_s + self.p["refractory_s"]
        self.turn_times.append(now_s)
        return {"speaker": by, "latest_speaker": latest_speaker,
                "text": text, "social_depth": social_depth,
                "addressed_to": addressed_to,
                "source_seq": source_seq, "thread_id": thread_id,
                "api_token_load": api_token_load,
                "latest_human_origin": latest_human_origin,
                "discharge_strength": round(discharge_strength, 6)}

    def state(self) -> dict:
        return {"pressure": round(self.pressure, 3),
                "habituation": round(self.habituation, 3),
                "bar": round(self.p["discharge_at"]
                             * (1.0 + self.habituation), 3),
                "pending": len(self.pending),
                "unresolved_floor": round(
                    max((float(item.get("unresolved_floor") or 0.0)
                         for item in self.pending), default=0.0), 3),
                "thread_id": str(max(
                    self.pending,
                    key=lambda item: int(item.get("seq") or 0),
                    default={}).get("thread_id") or ""),
                "source_seq": max((int(item.get("seq") or 0)
                                    for item in self.pending), default=0),
                "self_turns_past_hour": len(self.turn_times)}
