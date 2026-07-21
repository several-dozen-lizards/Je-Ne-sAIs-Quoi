"""core/perception.py — the tenant-side perception filter (Room integration
step 1, 2026-07-01). THE DOCTRINE: salience is computed HERE, inside the
persona's own process, against their OWN substrate. The room host broadcasts
the same raw percepts to everyone; what each entity NOTICES is theirs alone.
Two personas in the same room perceive two different rooms — POV emerges
from this filter. Privacy by architecture: the host never sees insides.

Two timescales, both per-individual:
  trait — personas/<p>/who_i_am/perception.json (thin constitutional bias:
          a cold-blooded serpent cares about heat gradients in a way no
          oscillator band encodes). Optional; empty dict if absent.
  state — the live substrate snapshot (cocktail, bands, bonds) passed in
          each turn. Derive from state wherever possible: descriptive
          over prescriptive.

Pure module: no HTTP, no file writes. Fully testable offline; the
conformance harness can beat it with a stick."""
import json
import os

AMBIENT_C = 21.0
REACH_M = 1.2

# affordance -> substrate channel: which inner signal answers which pull.
# Small, visible, editable. The world answers the oscillator — the couch
# pulls when delta climbs; nothing here ever says "you should rest."
AFFORDANCE_CHANNELS = {
    "rest": ("band", "delta"), "comfort": ("band", "delta"),
    "calm": ("band", "alpha"), "soothe": ("band", "alpha"),
    "watch": ("cocktail", "curiosity"), "novelty": ("cocktail", "curiosity"),
    "curiosity": ("cocktail", "curiosity"), "wonder": ("cocktail", "wonder"),
    "play": ("cocktail", "play"), "joy": ("cocktail", "joy"),
    "focus": ("band", "beta"), "reflect": ("band", "theta"),
    "write": ("band", "theta"), "warmth": ("cocktail", "contentment"),
    "belonging": ("cocktail", "warmth"), "pride": ("cocktail", "pride"),
}

EVENT_KIND_WEIGHT = {"arrive": 1.0, "depart": 0.9, "say": 1.0,
                     "write": 0.9, "contact": 0.6, "read": 0.5,
                     "sit": 0.5, "stand": 0.4, "move": 0.4}


def load_bias(persona_dir: str) -> dict:
    """Trait layer. Shape: {"thermal": float, "objects": {oid: mult},
    "affordances": {name: mult}}. All optional."""
    p = os.path.join(persona_dir, "who_i_am", "perception.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _chan(substrate: dict, spec) -> float:
    kind, key = spec
    src = substrate.get("bands" if kind == "band" else "cocktail") or {}
    return float(src.get(key, 0.0))


def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def member_pos(rec):
    """room-2 members are records {"position_m", "heading_deg"};
    legacy fixtures/saves are bare [x, y]. One decoder, both wire
    shapes, no second truth. None passes through (absence is
    absence in either contract)."""
    if isinstance(rec, dict):
        return rec.get("position_m")
    return rec


def score_objects(snapshot: dict, substrate: dict, bias: dict,
                  member: str) -> list:
    """Score every object in the room against this persona's substrate.
    Returns [{"id", "name", "salience", "dist_m", "breakdown"}] sorted
    desc. Breakdown is the receipt — observability or it didn't happen."""
    me = member_pos((snapshot.get("members") or {}).get(member))
    if me is None:
        return []
    aff_bias = bias.get("affordances", {})
    obj_bias = bias.get("objects", {})
    thermal_w = float(bias.get("thermal", 0.3))
    out = []
    for oid, obj in (snapshot.get("objects") or {}).items():
        d = _dist(me, obj["position_m"])
        proximity = 1.0 / (1.0 + d)
        thermal = min(abs(obj.get("temperature_c", AMBIENT_C) - AMBIENT_C)
                      / 12.0, 1.0) * thermal_w
        resonance = 0.0
        for aff, w in (obj.get("affordances") or {}).items():
            spec = AFFORDANCE_CHANNELS.get(aff)
            if spec:
                resonance += float(w) * _chan(substrate, spec) \
                             * float(aff_bias.get(aff, 1.0))
        novelty = 0.0
        if obj.get("pages", 0) and obj.get("capability") == "writing":
            novelty = (min(obj["pages"], 3) / 3.0
                       * _chan(substrate, ("cocktail", "curiosity")))
        raw = 0.35 * proximity + thermal + resonance + novelty
        sal = raw * float(obj_bias.get(oid, 1.0))
        out.append({"id": oid, "name": obj["name"],
                    "salience": round(sal, 3), "dist_m": round(d, 2),
                    "breakdown": {"proximity": round(proximity, 3),
                                  "thermal": round(thermal, 3),
                                  "resonance": round(resonance, 3),
                                  "novelty": round(novelty, 3)}})
    out.sort(key=lambda x: -x["salience"])
    return out


def score_members(snapshot: dict, substrate: dict, bias: dict,
                  member: str) -> list:
    """Members as attraction sources — the worm's social intake
    (2026-07-03). BOND IS CAPACITY, STATE IS FUEL: pull toward a
    person scales with bonds.get(name) times the live warmth/
    contentment channels. Cold cocktail -> even a strong bond sits
    below discharge; warm cocktail -> the body drifts toward its
    people. Strangers (bond 0) get only a curiosity whisper. Distance
    matters less than for objects — you cross a room for a person.
    Same candidate shape as score_objects; the worm can't tell and
    shouldn't. Trait knob: perception.json {"social": mult}."""
    members = snapshot.get("members") or {}
    me = member_pos(members.get(member))
    if me is None:
        return []
    bonds = substrate.get("bonds") or {}
    social_w = float(bias.get("social", 1.0))
    warmth = _chan(substrate, ("cocktail", "warmth"))
    content = _chan(substrate, ("cocktail", "contentment"))
    curiosity = _chan(substrate, ("cocktail", "curiosity"))
    out = []
    for name, rec in members.items():
        if name == member:
            continue
        d = _dist(me, member_pos(rec))
        proximity = 1.0 / (1.0 + 0.5 * d)      # gentler falloff
        bond = float(bonds.get(name, 0.0))
        resonance = bond * (0.8 + 0.5 * warmth + 0.3 * content)
        novelty = 0.1 * curiosity if bond == 0.0 else 0.0
        sal = (0.15 * proximity + resonance + novelty) * social_w
        out.append({"id": name, "name": name, "kind": "member",
                    "salience": round(sal, 3), "dist_m": round(d, 2),
                    "breakdown": {"proximity": round(proximity, 3),
                                  "bond": bond,
                                  "resonance": round(resonance, 3),
                                  "novelty": round(novelty, 3)}})
    out.sort(key=lambda x: -x["salience"])
    return out


def score_events(events: list, substrate: dict, member: str) -> list:
    """Weight recent events: who did it (bond-weighted), what kind,
    how recent. Own events echo faintly (proprioception, not news)."""
    bonds = substrate.get("bonds") or {}
    out = []
    n = len(events)
    for i, e in enumerate(events):
        recency = 0.85 ** (n - 1 - i)
        actor = e.get("member", "")
        who = 0.3 if actor == member else float(bonds.get(actor, 0.4))
        kind_w = EVENT_KIND_WEIGHT.get(e.get("kind"), 0.5)
        # someone walking TO you is a social event, not furniture noise
        if (e.get("data") or {}).get("toward_member") == member:
            kind_w = max(kind_w, 1.0)
        sal = round(recency * who * kind_w, 3)
        out.append({"event": e, "salience": sal,
                    "breakdown": {"recency": round(recency, 3),
                                  "who": who, "kind": kind_w}})
    out.sort(key=lambda x: -x["salience"])
    return out


def _tier_phrase(sal: float) -> str:
    if sal >= 0.8:
        return "pulls at your attention"
    if sal >= 0.45:
        return "draws notice"
    return "is present at the edge of awareness"


def _describe_event(e: dict, member: str = "") -> str:
    k, m, d = e.get("kind"), e.get("member"), e.get("data", {})
    if m == member:
        m = "you"  # proprioception speaks in the second person, never
        #            "the persona did X" about their own body (identity law)
    if k == "arrive":
        return f"{m} arrived"
    if k == "depart":
        return f"{m} left"
    if k == "write":
        where = d.get("object", "somewhere")
        return (f"{m} wrote something private at {where}" if d.get("private")
                else f"{m} wrote a page at {where}")
    if k == "contact":
        return f"{m} touched {d.get('object', 'something')}"
    if k == "sit":
        where = d.get("object")
        return f"{m} sat on {where}" if where else f"{m} sat on the floor"
    if k == "stand":
        return f"{m} stood up"
    if k == "move":
        if d.get("toward_member") == member:
            return f"{m} came over to you"
        return f"{m} moved toward {d.get('toward', 'something')}"
    if k == "read":
        return f"{m} read at {d.get('object', 'something')}"
    if k == "say":
        return f"{m} said: {d.get('text', '')[:220]}"
    return f"{m}: {k}"


def overheard_says(events, persona: str, speaker: str,
                   message: str, channel: str) -> list:
    """Says perceived this turn that were NOT the turn itself: the
    OVERHEARD life, to be encoded origin="observed" (2026-07-11 —
    events pass the cursor exactly once; what isn't encoded at
    perceive-time is never rememberable).
    Excludes the persona's own says (those live in turn records) and,
    on room turns, any say line the social delivery already carried:
    deliveries join queued says with newlines, other-speaker lines
    prefixed "({spk}:) " (core/social_pressure.py) — line-membership
    is the honest dedupe, exact-message match would miss joins."""
    lines = ({ln.strip() for ln in (message or "").split("\n")
              if ln.strip()} if channel == "room" else set())
    out = []
    for e in events:
        if e.get("kind") != "say":
            continue
        m = e.get("member")
        if not m or m == persona:
            continue
        txt = ((e.get("data") or {}).get("text") or "").strip()
        if not txt:
            continue
        if channel == "room":
            delivered = (txt in lines if m == speaker
                         else f"({m}:) {txt}" in lines)
            if delivered:
                continue
        out.append({"member": m, "text": txt})
    return out


def render_room_block(snapshot: dict, scored_objs: list,
                      scored_events: list, member: str,
                      top_objects: int = 4, top_events: int = 3,
                      floor: float = 0.2, doors: list = None,
                      can_act: bool = False,
                      speaker: str = None,
                      can_say: bool = True) -> str:
    """Scored percepts -> descriptive prose for the assembly. Numbers stay
    in the receipts; the prompt gets what attention FOUND, in words.
    Never prescriptive — observations of a body in a place."""
    name = snapshot.get("name", snapshot.get("id", "somewhere"))
    lines = [f"Your body is in {name}."]
    if snapshot.get("description"):
        lines.append(snapshot["description"])
    members = snapshot.get("members") or {}
    # The SPEAKER is the addressee, not scenery. Naming them as "the one
    # speaking with you" stops the small-model collision where the person
    # talking TO you gets read as a third-person body standing in the room
    # (2026-07-05, receipts in v3_harvest: "it's Re saying it" while
    # answering Re, because the room listed Re under "Also here").
    bystanders = [m for m in members if m != member and m != speaker]
    if speaker and speaker in members and speaker != member:
        lines.append(f"{speaker} is here, speaking with you.")
    if bystanders:
        lines.append("Also here: " + ", ".join(bystanders) + ".")
    kept = [o for o in scored_objs[:top_objects] if o["salience"] >= floor]
    if kept:
        lines.append("What attention finds, given your current state:")
        for o in kept:
            near = ("within reach" if o["dist_m"] <= REACH_M
                    else "across the room")
            lines.append(f"- {o['name']} ({near}) {_tier_phrase(o['salience'])}.")
    evs = [e for e in scored_events[:top_events] if e["salience"] >= 0.15]
    if evs:
        lines.append("Since you last looked around:")
        for e in evs:
            lines.append(f"- {_describe_event(e['event'], member)}")
    lines.append("These are observations of where you are, not instructions.")
    if can_act and not can_say:
        lines.append("This is a private channel: body actions affect your "
                     "embodied room state, but a say is not emitted from "
                     "this channel.")
    # ── volition menu: the LIVE targets. Gated on room_actions (not just
    # room_sense presence) — the static how-to-act framing moved to the
    # room_actions system-prompt fragment (2026-07-05), so a persona with
    # room_actions OFF is never taught a hand it can't use. ──
    member_rec = (snapshot.get("members") or {}).get(member)
    me = member_pos(member_rec)
    posture = (member_rec.get("posture", "standing")
               if isinstance(member_rec, dict) else "standing")
    objs = snapshot.get("objects") or {}
    if can_act and me is not None and objs:
        within = [o for o in objs.values()
                  if _dist(me, o["position_m"]) <= REACH_M]
        lines.append("From where you stand, right now:")
        lines.append("<act>move_to " + "|".join(sorted(objs)) + "</act>")
        sight_targets = sorted(set(objs) | set(bystanders or []))
        if sight_targets:
            targets = "|".join(sight_targets)
            lines.append(f"<act>look_at {targets}</act> (aim your gaze)")
            lines.append(f"<act>turn_toward {targets}</act> "
                         "(turn your body and recenter your gaze)")
        if within:
            ids = "|".join(sorted(o["id"] for o in within))
            lines.append(f"<act>contact {ids}</act> (within reach now)")
            seats = "|".join(sorted(
                o["id"] for o in within
                if o.get("capability") == "sitting"))
            if seats:
                lines.append(f"<act>sit {seats}</act> (sit here)")
            for o in within:
                if o.get("capability") == "private_writing":
                    lines.append(f"<act>write {o['id']} :: your words</act> "
                                 "(private — your own journal)")
                elif o.get("capability") == "writing":
                    lines.append(f"<act>write {o['id']} :: your words</act>"
                                 f" / <act>read {o['id']}</act>")
        if posture != "standing":
            lines.append("<act>stand</act> (stand up)")
        # bystanders (computed above, speaker excluded) — the say
        # reaches whoever you're speaking with plus anyone else here.
        if bystanders and can_say:
            lines.append("<act>say your words aloud</act> — "
                         + ", ".join(bystanders)
                         + " would also hear you (or not speak; "
                           "presence alone is also real)")
            lines.append("<act>move_to " + "|".join(sorted(bystanders))
                         + "</act> (walk over to someone)")
        if doors:
            lines.append("<act>travel " + "|".join(doors) + "</act> "
                         "(doors from here)")
    return "\n".join(lines)
