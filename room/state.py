"""room/state.py — the Room's canonical state model (REQUIREMENTS par 6).
The room state is the object; renderers (Godot later) and drivers
(Arduino/servo hardware later) are faces of it. Real-world units from
day one: meters, kilograms, degrees C, newtons — so the sim-to-real
port is a driver swap, not a translation archaeology.

Three property layers per object (design session 2026-07-01):
  physical   — position_m, mass_kg, temperature_c
  meaningful — affordances{} (salience is computed by each persona's
               perception filter against their OWN substrate; the room
               never sees anyone's insides — privacy by architecture)
  functional — capability, proximity-gated: the tool does not exist in
               your action space unless your body is at the object.
               Geography IS the permission system: a private desk in a
               one-member den writes to my_life/; the commons desk
               leaves readable pages in shared space."""
import math
import re
import time
from collections import deque
from threading import Condition

REACH_M = 1.2          # arm's length: capability + contact gate
WALL_MARGIN_M = 0.3    # radial clamp: bodies stay off the lattice
OPTICAL_FOV_DEG = 72.0
DETAIL_FRACTION_RANGE = (0.20, 0.55)
GAZE_COMFORT_DEG = 85.0
CONTRACT_VERSION = "room-2"   # circular rooms, center-origin (yurts).
EXPRESSIVE_MOTIONS = {
    "acknowledge", "angry_gesture", "annoyed_head_shake", "cocky",
    "dismiss", "happy_gesture", "hard_nod", "yes_nod", "long_nod",
    "look_away", "relieved_sigh", "sarcastic_nod", "no_head_shake",
    "thoughtful_head_shake",
}
# room-2 (20260719): members are RECORDS, not bare [x, y] — presence
# has an orientation now. {"position_m": [x, y], "heading_deg": d}.

# ── HEADING LAW (room-2) ─────────────────────────────────────────
# heading_deg: CCW positive, 0 = world +Y (walk in the south door
# facing the center and you stand at zero). Same sign family as
# RoomObject.rot_deg. Renderers: Godot rotation.y =
# deg_to_rad(heading_deg) — signs agree through the [x,y] -> (x,0,-y)
# map, proven by the object path. SVG (y-down) negates.
# Forward vector in world coords: (-sin h, cos h).


def explicit_speech_addressees(text: str, members) -> list:
    """Resolve only unambiguous opening vocatives."""
    words = str(text or "").strip()
    if not words:
        return []
    member_aliases = {}
    for member in members:
        raw = str(member)
        for alias in {raw, raw.replace("_", " "), raw.split("_", 1)[0]}:
            member_aliases[alias.casefold()] = raw
    # A leading roll call ("Ari, Bo, Cy?") addresses every listed
    # resident. Only accept it when every comma-separated item is a known
    # name, so ordinary clauses are not reclassified as routing metadata.
    opening = re.split(r"[?!:]", words, maxsplit=1)[0]
    listed = [part.strip().casefold() for part in opening.split(",")]
    if len(listed) > 1 and all(part in member_aliases for part in listed):
        return list(dict.fromkeys(member_aliases[part] for part in listed))
    found = []
    for member in members:
        raw = str(member)
        aliases = {raw, raw.replace("_", " "), raw.split("_", 1)[0]}
        for alias in sorted(aliases, key=len, reverse=True):
            escaped = re.escape(alias)
            boundary = r"(?:^|[.!?]\s+)"
            direct = re.search(
                rf"{boundary}(?:hey[\s,!:;-]+)?{escaped}"
                rf"(?:\s*[,!?:;-]|\s*$)",
                words, flags=re.IGNORECASE)
            hey = re.search(
                rf"{boundary}hey\s+{escaped}\b",
                words, flags=re.IGNORECASE)
            if direct or hey:
                found.append(raw)
                break
    return found


def heading_toward(frm, to) -> float:
    """The heading that faces `to` from `frm`. Degenerate (same
    point) -> 0.0, the door-neutral default."""
    dx = float(to[0]) - float(frm[0])
    dy = float(to[1]) - float(frm[1])
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return 0.0
    return math.degrees(math.atan2(-dx, dy)) % 360.0


class Member:
    """A body in a room (room-2): where it stands and which way it
    faces. Presence gained an orientation; pose and posture move in
    here when the pose layer lands (phase 2)."""
    def __init__(self, name: str, position_m,
                 heading_deg: float = 0.0, face=None,
                 posture: str = "standing", gaze_yaw_deg: float = 0.0,
                 gaze_pitch_deg: float = 0.0, gesture: str = ""):
        self.name = name
        self.position_m = list(position_m)      # [x, y] meters
        self.heading_deg = float(heading_deg) % 360.0
        self.face = dict(face or {})    # expression packet: SURFACE
        # (room-2 additive, 20260719): what a camera would see --
        # the persona-side distiller already chose what shows.
        self.posture = str(posture or "standing")
        self.gesture = str(gesture or "")
        self.gaze_yaw_deg = max(-85.0, min(85.0, float(gaze_yaw_deg)))
        self.gaze_pitch_deg = max(-60.0, min(60.0, float(gaze_pitch_deg)))
        # (room-2 additive, 20260720): standing | sitting |
        # sitting_floor. The ACT is universal; the rendered shape is
        # per-body -- bipeds fold, the naga pools.

    def snapshot(self) -> dict:
        return {"position_m": list(self.position_m),
                "heading_deg": self.heading_deg,
                "face": dict(self.face),
                "posture": self.posture,
                "gesture": self.gesture,
                "gaze_yaw_deg": self.gaze_yaw_deg,
                "gaze_pitch_deg": self.gaze_pitch_deg}

    def optical_pose(self) -> dict:
        return {"position_m": list(self.position_m),
                "heading_deg": self.heading_deg,
                "gaze_yaw_deg": self.gaze_yaw_deg,
                "gaze_pitch_deg": self.gaze_pitch_deg,
                "posture": self.posture}


class RoomObject:
    def __init__(self, oid: str, name: str, position_m,
                 mass_kg: float = 1.0, temperature_c: float = 21.0,
                 affordances: dict = None, capability: str = None,
                 owner: str = None, description: str = "",
                 texture: str = "neutral",
                 kind: str = None, size_m: float = 0.6,
                 rot_deg: float = 0.0, y_off_m: float = 0.0,
                 power: float = 0.0):
        self.id = oid
        self.name = name
        self.position_m = list(position_m)      # [x, y] meters
        self.mass_kg = mass_kg
        self.temperature_c = temperature_c
        self.affordances = dict(affordances or {})
        self.capability = capability            # e.g. writing / private_writing
        self.owner = owner                      # for private capabilities
        self.description = description
        self.texture = texture                  # afferent-schema field
        self.kind = kind          # render hint: which model file
                                  # (assets/objects/<kind>.glb; <oid>.glb
                                  # overrides; no file -> the box)
        self.size_m = float(size_m)  # render hint: largest horizontal
                                     # extent -- the client auto-fits
                                     # whatever mesh it finds to this
        self.rot_deg = float(rot_deg)  # yaw, degrees CCW from seed
                                       # facing. Prints auto-face the
                                       # center while this stays 0.
        self.y_off_m = float(y_off_m)  # render hint: vertical lift off
                                       # the floor, meters. The lever.
        self.power = max(0.0, min(1.0, float(power)))
        self.pages = []                         # written artifacts ON the object
        self.memory_ties = []                   # reserved: spatial memory gravity

    def snapshot(self) -> dict:
        return {"id": self.id, "name": self.name,
                "position_m": self.position_m, "mass_kg": self.mass_kg,
                "temperature_c": self.temperature_c,
                "affordances": self.affordances,
                "capability": self.capability, "owner": self.owner,
                "description": self.description,
                "kind": self.kind, "size_m": self.size_m,
                "rot_deg": self.rot_deg, "y_off_m": self.y_off_m,
                "power": self.power,
                "pages": len(self.pages)}


class Room:
    def __init__(self, rid: str, name: str, radius_m: float,
                 description: str = ""):
        self.id = rid
        self.name = name
        self.radius_m = float(radius_m)         # yurt radius, meters
        self.shape = "circle"                   # center-origin [x, y]
        self.description = description
        self.objects = {}                       # oid -> RoomObject
        self.members = {}                       # name -> Member (room-2)
        self.events = deque(maxlen=500)         # the event bus, v0
        # SURFACE channel (20260719): body-surface deltas (faces) are
        # STATE notifications with last-value semantics, not episodic
        # history -- they live in their own ring so face churn never
        # flushes conversation out of the 500-window, never wakes the
        # longpoll, never enters logs or perception by default.
        # Windows that render bodies opt in (?surface=1). One clock:
        # both rings share _seq, so one cursor walks the union.
        self.surface_events = deque(maxlen=100)
        self._seq = 0
        self._event_condition = Condition()

    # ── event bus ────────────────────────────────────────────────
    def emit(self, member: str, kind: str, data: dict = None):
        with self._event_condition:
            self._seq += 1
            self.events.append({"seq": self._seq,
                                "ts": time.strftime("%H:%M:%S"),
                                "t": time.time(),
                                "member": member, "kind": kind,
                                "data": data or {}})
            self._event_condition.notify_all()

    def emit_surface(self, member: str, kind: str, data: dict = None):
        # Same clock, separate transient ring. A state-threshold listener may
        # wake without admitting the surface packet into episodic history.
        with self._event_condition:
            self._seq += 1
            self.surface_events.append({"seq": self._seq,
                                        "ts": time.strftime("%H:%M:%S"),
                                        "t": time.time(),
                                        "member": member, "kind": kind,
                                        "data": data or {}})
            self._event_condition.notify_all()

    def events_since(self, since: int, surface: bool = False) -> list:
        with self._event_condition:
            evs = [e for e in self.events if e["seq"] > since]
            if surface:
                evs += [e for e in self.surface_events
                        if e["seq"] > since]
                evs.sort(key=lambda e: e["seq"])
            return evs

    def wait_for_events(self, since: int, timeout: float = 25.0,
                        surface: bool = False) -> list:
        """Block until the event vector advances beyond ``since``.

        The timeout only renews the HTTP transport; it does not cause a room
        tick or scheduled behavior. State wakes listeners by threshold: a new
        sequence value exists.
        """
        with self._event_condition:
            self._event_condition.wait_for(lambda: self._seq > since,
                                           timeout=max(1.0, min(30.0,
                                                                timeout)))
            evs = [e for e in self.events if e["seq"] > since]
            if surface:
                evs += [e for e in self.surface_events
                        if e["seq"] > since]
                evs.sort(key=lambda event: event["seq"])
            return evs

    # ── membership (one body, one room — enforced by the host) ──
    def join(self, member: str, at=None):
        # the door: one, south rim, just inside — yurts agree.
        door = [0.0, -(self.radius_m - 0.5)]
        pos = self._deconflict(self._clamp_inside(list(at or door)),
                               member)
        # you walk in facing the room: heading toward the center.
        m = Member(member, pos, heading_toward(pos, [0.0, 0.0]))
        self.members[member] = m
        self.emit(member, "arrive", {"position_m": m.position_m,
                                     "heading_deg": m.heading_deg})

    def leave(self, member: str):
        gone = self.members.pop(member, None)
        self.emit(member, "depart", {
            "position_m": list(gone.position_m) if gone else None})

    # ── space ────────────────────────────────────────────────────
    def _dist(self, a, b) -> float:
        return ((a[0]-b[0])**2 + (a[1]-b[1])**2) ** 0.5

    def _clamp_inside(self, pos) -> list:
        """Radial clamp: a body ends up inside the wall, never in it.
        New in room-1 — the rect never checked; the circle does."""
        usable = self.radius_m - WALL_MARGIN_M
        d = (pos[0]**2 + pos[1]**2) ** 0.5
        if d <= usable or d == 0:
            return list(pos)
        s = usable / d
        return [pos[0] * s, pos[1] * s]

    @staticmethod
    def _footprint_r(obj) -> float:
        """Floor-standing things project a footprint (half their
        size). Hung things (posters) and hand-sized things (mugs)
        don't -- you approach them close."""
        size = float(getattr(obj, "size_m", 0.6))
        if size >= 0.5 and float(getattr(obj, "y_off_m", 0.0)) < 0.8:
            return size * 0.5
        return 0.0

    def _deconflict(self, pos, exclude: str):
        """The PERSONAL-SPACE law (20260720): bodies have volume.
        A landing point within 0.4 m of another body slides
        sideways in deterministic steps until clear."""
        def clear(p):
            for name, mm in self.members.items():
                if name == exclude:
                    continue
                if self._dist(p, mm.position_m) < 0.4:
                    return False
            return True
        p0 = self._clamp_inside(list(pos))
        if clear(p0):
            return p0
        for i in range(1, 9):
            for sx in (1.0, -1.0):
                cand = self._clamp_inside(
                    [pos[0] + sx * 0.45 * i, pos[1]])
                if clear(cand):
                    return cand
        return p0    # genuinely crowded room: overlap beats exile

    def near(self, member: str, oid: str) -> bool:
        if member not in self.members or oid not in self.objects:
            return False
        obj = self.objects[oid]
        d = self._dist(self.members[member].position_m,
                       obj.position_m)
        # reach measures to the EDGE of a footprint, not the center
        # -- you can touch a couch you're standing at, even though
        # its centroid is a meter into the cushions.
        return d - self._footprint_r(obj) <= REACH_M

    def move_to(self, member: str, oid: str) -> dict:
        """Walk to an object. Movement is an event other members
        perceive — presence has a body, always."""
        if member not in self.members:
            return {"error": f"{member} is not in {self.id}"}
        # moving implies standing: walking out of a chair stands you
        # up first (the window reads any move event as standing).
        self.members[member].posture = "standing"
        if oid in self.members and oid != member:
            # walking to a PERSON: land within reach, not on their tail.
            # Presence is social — the event says who you came to.
            me = self.members[member]
            frm = list(me.position_m)
            tgt = self.members[oid].position_m
            me.position_m = self._deconflict(
                [tgt[0], tgt[1] - 0.8], member)
            # arrival: face the one you came to.
            me.heading_deg = heading_toward(me.position_m, tgt)
            self.emit(member, "move", {"from_m": frm,
                                       "to_m": me.position_m,
                                       "heading_deg": me.heading_deg,
                                       "toward": oid,
                                       "toward_member": oid})
            return {"ok": True, "at": oid,
                    "position_m": me.position_m,
                    "heading_deg": me.heading_deg}
        if oid not in self.objects:
            return {"error": f"no object or member '{oid}' in {self.id}"}
        obj = self.objects[oid]
        me = self.members[member]
        frm = list(me.position_m)
        # LANDING LAW v2 (20260720): footprint-aware, approach-aware.
        # Floor-standing things project a footprint; you land at the
        # near EDGE plus a margin, from the direction you came --
        # nobody stands inside the couch. Hung and hand-sized things
        # keep the classic close approach.
        fr = self._footprint_r(obj)
        stand_off = (fr + 0.35) if fr > 0.0 else 0.5
        dx = obj.position_m[0] - frm[0]
        dy = obj.position_m[1] - frm[1]
        d = (dx * dx + dy * dy) ** 0.5
        if d < 1e-6:
            dx, dy, d = 0.0, -1.0, 1.0
        me.position_m = self._deconflict(
            [obj.position_m[0] - dx / d * stand_off,
             obj.position_m[1] - dy / d * stand_off], member)
        # arrival: face the thing you walked to.
        me.heading_deg = heading_toward(me.position_m, obj.position_m)
        self.emit(member, "move", {"from_m": frm,
                                   "to_m": me.position_m,
                                   "heading_deg": me.heading_deg,
                                   "toward": obj.name})
        return {"ok": True, "at": obj.name,
                "position_m": me.position_m,
                "heading_deg": me.heading_deg}

    def say(self, member: str, text: str, social_depth: int = 0):
        """Speech is a percept AND a pull: bodies orient toward
        salient sound. The reflex is pre-cognitive — brainstem-level
        orienting, below decision — which is why the WORLD applies
        it; deliberate attention can override it when personas gain
        that actuation. One cause, one event: 'orient' carries every
        heading that changed."""
        data = {"text": text or ""}
        addressed_to = explicit_speech_addressees(text, self.members)
        if addressed_to:
            data["addressed_to"] = addressed_to
        if social_depth > 0:
            data["social_depth"] = int(social_depth)
        self.emit(member, "say", data)
        spk = self.members.get(member)
        if spk is None:
            return
        turned = {}
        for name, m in self.members.items():
            if name == member:
                continue
            if m.posture != "standing":
                continue      # seated bodies keep the seat's facing;
                              # the glance is the window's head-look
            h = heading_toward(m.position_m, spk.position_m)
            # wrap-safe delta: 359.9 and 0.1 are neighbors, not a turn
            d = (h - m.heading_deg + 180.0) % 360.0 - 180.0
            if abs(d) < 0.5:
                continue          # already facing them: no event noise
            m.heading_deg = h
            turned[name] = h
        if turned:
            self.emit(member, "orient", {"toward": member,
                                         "headings": turned})

    def set_face(self, member: str, face: dict):
        """The face is body surface (room-2 additive): what a camera
        would see, never the cocktail behind it -- the persona-side
        distiller already chose what shows (privacy by architecture).
        Sanitizes the packet, stores last-known, emits 'expression'
        only on change: a still face costs zero events."""
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        pkt = {}
        src = face if isinstance(face, dict) else {}
        emos = src.get("emotions")
        if isinstance(emos, list):
            clean = []
            for item in emos[:8]:
                s = str(item)[:48]
                name_, sep, val = s.rpartition(":")
                if not sep:
                    continue
                try:
                    v = max(0.0, min(1.0, float(val)))
                except ValueError:
                    continue
                clean.append(f"{name_.strip().lower()}:{v:.2f}")
            pkt["emotions"] = clean
        for k in ("tension", "threat", "emotional_arousal",
                  "centering_softness"):
            if k in src:
                try:
                    pkt[k] = max(0.0, min(1.0, float(src[k])))
                except (TypeError, ValueError):
                    continue
        if pkt == m.face:
            return {"ok": True, "unchanged": True}
        m.face = pkt
        # surface channel: faces are state, not history -- the delta
        # rides the silent ring; logs and perception never see it.
        self.emit_surface(member, "expression", {"face": dict(pkt)})
        return {"ok": True}

    def set_gesture(self, member: str, gesture: str):
        """Choose a visible whole-body shape without assigning a feeling.

        The room stores semantic intent; each compatible body resolves that
        intent through its own rig. Unknown bodies may render less of it, but
        every window agrees what the member chose.
        """
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        name = str(gesture or "").strip().lower()
        allowed = {"attentive", "weary", "guarded", "open",
                   "curious_tilt"}
        if name and name not in allowed:
            return {"error": f"unknown gesture '{name}'"}
        if m.posture != "standing" and name:
            return {"error": "stand before choosing a whole-body gesture"}
        if name == m.gesture:
            return {"ok": True, "unchanged": True, "gesture": name}
        m.gesture = name
        self.emit(member, "gesture", {"gesture": name,
                                      "released": not bool(name)})
        return {"ok": True, "gesture": name}

    def perform_motion(self, member: str, motion: str):
        """Emit one resident-chosen body motion without assigning a feeling.

        Motions are episodic events, not persistent member state: the authored
        clip plays once, then the body returns to its responsive idle layers.
        """
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        name = str(motion or "").strip().lower()
        if name not in EXPRESSIVE_MOTIONS:
            return {"error": f"unknown body motion '{name}'"}
        if m.posture != "standing":
            return {"error": "stand before choosing a whole-body motion"}
        self.emit(member, "motion", {"motion": name})
        return {"ok": True, "motion": name}

    def set_light(self, member: str, oid: str, on: bool):
        """Switch a reachable light without assigning meaning to the act."""
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        obj = self.objects.get(str(oid or ""))
        if obj is None:
            return {"error": f"no object '{oid}'"}
        if obj.capability != "light":
            return {"error": f"{obj.name} is not a switchable light"}
        if obj.owner and obj.owner.casefold() != member.casefold():
            return {"error": f"{obj.name} belongs to {obj.owner}"}
        if not self.near(member, obj.id):
            return {"error": f"{obj.name} is out of reach"}
        power = 1.0 if on else 0.0
        if obj.power == power:
            return {"ok": True, "unchanged": True, "object": obj.id,
                    "power": power}
        obj.power = power
        self.emit(member, "light", {"object": obj.id, "power": power,
                                    "on": bool(on)})
        return {"ok": True, "object": obj.id, "power": power}

    def sit(self, member: str, oid: str = None):
        """Sitting is an ACT -- episodic, perceivable, main bus:
        'the persona settled onto the armchair' belongs in the log and in
        perception. With an object: requires the 'sitting'
        affordance and reach; the sitter occupies it, aligned to
        its facing. Without: sit where you stand, on the floor.
        The rendered shape is each window's per-body business."""
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        if oid:
            obj = self.objects.get(oid)
            if obj is None:
                return {"error": f"no object '{oid}'"}
            if getattr(obj, "capability", None) != "sitting":
                return {"error": f"{obj.name} doesn't afford sitting"}
            if not self.near(member, oid):
                return {"error": f"{obj.name} is out of reach"}
            # SEAT SLOTS (20260720): seats have WIDTH. Slots spread
            # along the width axis (right = (cos h, sin h)), center
            # first; each holds one body. A couch seats the
            # household abreast instead of hosting a wormhole.
            h = math.radians(float(getattr(obj, "rot_deg", 0.0)))
            n = max(1, int(float(getattr(obj, "size_m", 0.6)) / 0.7))
            base = [obj.position_m[0] - math.sin(h) * 0.28,
                    obj.position_m[1] + math.cos(h) * 0.28]
            offs = sorted(((i - (n - 1) / 2.0) * 0.6
                           for i in range(n)), key=abs)
            spot = None
            for off in offs:
                cand = [base[0] + math.cos(h) * off,
                        base[1] + math.sin(h) * off]
                taken = any(
                    nm != member
                    and mm.posture.startswith("sitting")
                    and self._dist(cand, mm.position_m) < 0.35
                    for nm, mm in self.members.items())
                if not taken:
                    spot = cand
                    break
            if spot is None:
                return {"error": f"{obj.name} is full"}
            m.position_m = self._clamp_inside(spot)
            m.heading_deg = float(getattr(obj, "rot_deg", 0.0)) % 360.0
            m.posture = "sitting"
            self.emit(member, "sit", {"object": obj.name,
                                      "position_m": m.position_m,
                                      "heading_deg": m.heading_deg,
                                      "posture": m.posture})
            return {"ok": True, "on": obj.name}
        m.posture = "sitting_floor"
        self.emit(member, "sit", {"posture": m.posture,
                                  "position_m": m.position_m})
        return {"ok": True, "on": "floor"}

    def stand(self, member: str):
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        if m.posture == "standing":
            return {"ok": True, "unchanged": True}
        # step off whatever you occupied -- the landing law's nudge,
        # so nobody stands INSIDE the chair.
        if m.posture == "sitting":
            m.position_m = self._deconflict(
                [m.position_m[0], m.position_m[1] - 0.5], member)
        m.posture = "standing"
        self.emit(member, "stand", {"posture": m.posture,
                                    "position_m": m.position_m,
                                    "heading_deg": m.heading_deg,
                                    "gesture": m.gesture})
        return {"ok": True}

    def walk(self, member: str, to, heading_deg=None):
        """FREE WALKING (20260720): the room is a PLACE, not a menu
        of destinations. Raw [x, y] meters -- clamped inside the
        wall, deconflicted from other bodies, heading follows
        travel. Stand by the door. Drift toward the poster. Take
        the corner because you feel like it: position itself
        becomes expressive."""
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        try:
            tx, ty = float(to[0]), float(to[1])
        except (TypeError, ValueError, IndexError):
            return {"error": "walk needs [x, y] meters"}
        explicit_heading = None
        if heading_deg is not None:
            try:
                explicit_heading = float(heading_deg)
            except (TypeError, ValueError):
                return {"error": "heading_deg must be numeric"}
            if not math.isfinite(explicit_heading):
                return {"error": "heading_deg must be finite"}
        m.posture = "standing"
        frm = list(m.position_m)
        dest = self._deconflict([tx, ty], member)
        m.position_m = dest
        if explicit_heading is not None:
            m.heading_deg = explicit_heading % 360.0
        elif self._dist(frm, dest) > 1e-6:
            m.heading_deg = heading_toward(frm, dest)
        self.emit(member, "move", {"from_m": frm, "to_m": dest,
                                   "heading_deg": m.heading_deg})
        return {"ok": True, "position_m": dest,
                "heading_deg": m.heading_deg}

    def look_at(self, member: str, oid: str) -> dict:
        """Aim the optical mount without silently moving its body."""
        me = self.members.get(member)
        if me is None:
            return {"error": f"{member} is not here"}
        target = self.members.get(oid) or self.objects.get(oid)
        if target is None:
            return {"error": f"no object or member '{oid}' in {self.id}"}
        absolute = heading_toward(me.position_m, target.position_m)
        relative = (absolute - me.heading_deg + 180.0) % 360.0 - 180.0
        me.gaze_yaw_deg = max(-85.0, min(85.0, relative))
        me.gaze_pitch_deg = 0.0
        self.emit(member, "gaze", {"toward": oid,
                                    "gaze_yaw_deg": me.gaze_yaw_deg,
                                    "gaze_pitch_deg": me.gaze_pitch_deg})
        return {"ok": True, "toward": oid,
                "optical_pose": me.optical_pose(),
                "fully_centered": abs(relative) <= 85.0}

    def turn_toward(self, member: str, oid: str) -> dict:
        """Turn the body toward a target and recenter its optical mount."""
        me = self.members.get(member)
        if me is None:
            return {"error": f"{member} is not here"}
        target = self.members.get(oid) or self.objects.get(oid)
        if target is None:
            return {"error": f"no object or member '{oid}' in {self.id}"}
        me.heading_deg = heading_toward(me.position_m, target.position_m)
        me.gaze_yaw_deg = 0.0
        me.gaze_pitch_deg = 0.0
        self.emit(member, "turn", {"toward": oid,
                                    "heading_deg": me.heading_deg,
                                    "gaze_yaw_deg": 0.0,
                                    "gaze_pitch_deg": 0.0})
        return {"ok": True, "toward": oid,
                "optical_pose": me.optical_pose()}

    def inspect(self, member: str, oid: str) -> dict:
        """Take one voluntary step toward a clearer view, then stop.

        The controller is staged: torso, gaze, and distance never cascade in
        one call.  The next camera frame returns before another choice exists.
        Detail is an angular range derived from the optical field rather than
        a universal distance; a mug and a person therefore ask for different
        vantage points.
        """
        me = self.members.get(member)
        if me is None:
            return {"error": f"{member} is not here"}
        target = self.members.get(oid) or self.objects.get(oid)
        if target is None or target is me:
            return {"error": f"no inspectable target '{oid}' in {self.id}"}
        bearing = heading_toward(me.position_m, target.position_m)
        torso_error = (bearing - me.heading_deg + 180.0) % 360.0 - 180.0
        optical_heading = me.heading_deg + me.gaze_yaw_deg
        gaze_error = (bearing - optical_heading + 180.0) % 360.0 - 180.0
        distance = max(0.05, self._dist(me.position_m, target.position_m))
        target_span = (0.55 if oid in self.members else
                       max(0.08, float(getattr(target, "size_m", 0.6))))
        angular_size = math.degrees(
            2.0 * math.atan2(target_span * 0.5, distance))
        detail_min = OPTICAL_FOV_DEG * DETAIL_FRACTION_RANGE[0]
        detail_max = OPTICAL_FOV_DEG * DETAIL_FRACTION_RANGE[1]
        center_band = OPTICAL_FOV_DEG * 0.10
        receipt = {"ok": True, "toward": oid,
                   "angular_size_deg": round(angular_size, 3),
                   "detail_range_deg": [round(detail_min, 3),
                                        round(detail_max, 3)]}

        if abs(torso_error) > GAZE_COMFORT_DEG:
            result = self.turn_toward(member, oid)
            return {**receipt, **result, "inspection_phase": "turn"}
        if abs(gaze_error) > center_band:
            result = self.look_at(member, oid)
            return {**receipt, **result, "inspection_phase": "gaze"}
        if angular_size < detail_min or angular_size > detail_max:
            desired_angle = OPTICAL_FOV_DEG * math.sqrt(
                DETAIL_FRACTION_RANGE[0] * DETAIL_FRACTION_RANGE[1])
            desired_distance = target_span / (
                2.0 * math.tan(math.radians(desired_angle) * 0.5))
            if oid in self.members:
                desired_distance = max(0.8, desired_distance)
            else:
                desired_distance = max(
                    self._footprint_r(target) + 0.30, desired_distance)
            dx = me.position_m[0] - target.position_m[0]
            dy = me.position_m[1] - target.position_m[1]
            length = max(1e-6, (dx * dx + dy * dy) ** 0.5)
            destination = self._deconflict([
                target.position_m[0] + dx / length * desired_distance,
                target.position_m[1] + dy / length * desired_distance,
            ], member)
            before = list(me.position_m)
            me.position_m = destination
            me.posture = "standing"
            me.heading_deg = heading_toward(destination, target.position_m)
            me.gaze_yaw_deg = 0.0
            me.gaze_pitch_deg = 0.0
            self.emit(member, "move", {
                "from_m": before, "to_m": destination,
                "heading_deg": me.heading_deg, "toward": oid,
                "inspection": True})
            return {**receipt, "inspection_phase": "reframe",
                    "position_m": list(destination),
                    "heading_deg": me.heading_deg,
                    "desired_distance_m": round(desired_distance, 3),
                    "optical_pose": me.optical_pose()}
        return {**receipt, "inspection_phase": "framed",
                "unchanged": True, "optical_pose": me.optical_pose()}

    # ── touch: the afferent schema (same shape sim OR hardware) ──
    def contact(self, member: str, oid: str, force_n: float = 5.0) -> dict:
        """One afferent schema, two future backends: these exact fields
        are what a Velostat/thermistor/piezo stack emits. A simulated
        touch and a hardware touch land in the soma identically."""
        if not self.near(member, oid):
            return {"error": "out of reach — walk to it first"}
        obj = self.objects[oid]
        percept = {"contact": True, "object": obj.name,
                   "force_n": force_n,
                   "pressure_kpa": round(force_n / 0.002 / 1000, 2),
                   "temperature_c": obj.temperature_c,
                   "texture": obj.texture,
                   "affordances": obj.affordances}
        self.emit(member, "contact", {"object": obj.name,
                                      "force_n": force_n})
        return {"ok": True, "afferent": percept}

    def snapshot(self) -> dict:
        return {"contract_version": CONTRACT_VERSION,
                "id": self.id, "name": self.name,
                "shape": self.shape, "radius_m": self.radius_m,
                "description": self.description,
                "members": {m: mem.snapshot()
                            for m, mem in self.members.items()},
                "objects": {o.id: o.snapshot()
                            for o in self.objects.values()},
                "last_seq": self._seq}
