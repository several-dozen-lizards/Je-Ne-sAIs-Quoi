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
import uuid
from collections import deque
from threading import Condition

from core.locomotion import (
    HEADING_EPSILON_DEG, POSITION_EPSILON_M, build_motion_profile,
    signed_heading_delta,
)

REACH_M = 1.2          # arm's length: capability + contact gate
WALL_MARGIN_M = 0.3    # radial clamp: bodies stay off the lattice
ISLAND_BOUNDARY_ID = "jnsq_island_mesh_v1"
# These vectors mirror the authored island build: a broad rim with one
# deliberately pulled-in cove. Godot performs the final exact mesh-footprint
# check; this host-side envelope keeps canonical destinations conservative.
ISLAND_BASE_SAFE_RADIUS_M = 15.5
ISLAND_COVE_ANGLE_RAD = math.radians(205.0)
ISLAND_COVE_HALF_RAD = math.radians(34.0)
ISLAND_COVE_PULL = 0.30
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
TRANSIENT_POSE_LIMITS = {
    "head_yaw_deg": 6.0,
    "head_pitch_deg": 3.5,
    "torso_yaw_deg": 7.0,
    "torso_pitch_deg": 2.5,
    "weight_shift": 0.24,
    "strength": 1.0,
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
    listed_opening = re.sub(
        r"^(?:hey|hi|hello)[\s,!:;-]+", "", opening,
        flags=re.IGNORECASE)
    listed = [part.strip().casefold()
              for part in listed_opening.split(",")]
    if len(listed) > 1 and all(part in member_aliases for part in listed):
        return list(dict.fromkeys(member_aliases[part] for part in listed))
    # A real opening address outranks name-shaped phrases later in the turn.
    # This matters for introductions such as "Hi Ari! This is Bo....
    # Cy is...": the later descriptions must not steal the turn from
    # the person named at the door.
    for alias in sorted(member_aliases, key=len, reverse=True):
        escaped = re.escape(alias)
        leading = re.match(
            rf"^(?:(?:hey|hi|hello)[\s,!:;-]+)?{escaped}"
            rf"(?:\s*[,!?:;-]|\s*$)",
            words, flags=re.IGNORECASE)
        if leading:
            return [member_aliases[alias]]
    found = []
    for member in members:
        raw = str(member)
        aliases = {raw, raw.replace("_", " "), raw.split("_", 1)[0]}
        for alias in sorted(aliases, key=len, reverse=True):
            escaped = re.escape(alias)
            boundary = r"(?:^|[.!?]\s+)"
            direct = re.search(
                rf"{boundary}(?:(?:hey|hi|hello)[\s,!:;-]+{escaped}"
                rf"(?:\s*[,!?:;-]|\s*$)|{escaped}"
                rf"(?:\s*[,!?:]|\s*$))",
                words, flags=re.IGNORECASE)
            hey = re.search(
                rf"{boundary}(?:hey|hi|hello)\s+{escaped}\b",
                words, flags=re.IGNORECASE)
            trailing = re.search(
                rf",\s*{escaped}\s*(?:[.!?]+(?:\s|$)|$)",
                words, flags=re.IGNORECASE)
            if direct or hey or trailing:
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
                 gaze_pitch_deg: float = 0.0, gesture: str = "",
                 movement: dict = None):
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
        self.movement = dict(movement or {})
        # (room-2 additive, 20260720): standing | sitting |
        # sitting_floor. The ACT is universal; the rendered shape is
        # per-body -- bipeds fold, the naga pools.

    @staticmethod
    def _motion_ease(progress: float) -> float:
        value = max(0.0, min(1.0, float(progress)))
        return (2.0 * value * value if value < 0.5
                else 1.0 - ((-2.0 * value + 2.0) ** 2) / 2.0)

    def start_motion(self, motion: dict, now: float = None):
        self.movement = {**dict(motion or {}),
                         "started_at": float(now or time.time())}
        self.position_m = list(self.movement.get("from_m") or self.position_m)
        self.heading_deg = float(self.movement.get(
            "start_heading_deg", self.heading_deg)) % 360.0

    def advance_motion(self, now: float = None):
        """Project canonical pose along an active host-authored trajectory."""
        motion = self.movement
        if not motion:
            return None
        now = float(now or time.time())
        started = float(motion.get("started_at") or now)
        turn_s = max(0.0, float(motion.get("turn_duration_s") or 0.0))
        move_s = max(0.0, float(motion.get("move_duration_s") or 0.0))
        settle_s = max(0.0, float(motion.get("settle_duration_s") or 0.0))
        total_s = turn_s + move_s + settle_s
        elapsed = max(0.0, now - started)
        start = list(motion.get("from_m") or self.position_m)
        destination = list(motion.get("to_m") or start)
        start_heading = float(motion.get(
            "start_heading_deg", self.heading_deg)) % 360.0
        travel_heading = float(motion.get(
            "travel_heading_deg", start_heading)) % 360.0
        arrival_heading = float(motion.get(
            "arrival_heading_deg", travel_heading)) % 360.0
        if elapsed < turn_s and turn_s > 0.0:
            progress = self._motion_ease(elapsed / turn_s)
            self.position_m = start
            self.heading_deg = (start_heading + signed_heading_delta(
                start_heading, travel_heading) * progress) % 360.0
            return None
        elapsed -= turn_s
        if elapsed < move_s and move_s > 0.0:
            progress = self._motion_ease(elapsed / move_s)
            self.position_m = [
                start[index] + (destination[index] - start[index]) * progress
                for index in (0, 1)]
            self.heading_deg = travel_heading
            return None
        self.position_m = destination
        elapsed -= move_s
        if elapsed < settle_s and settle_s > 0.0:
            progress = self._motion_ease(elapsed / settle_s)
            self.heading_deg = (travel_heading + signed_heading_delta(
                travel_heading, arrival_heading) * progress) % 360.0
            return None
        self.heading_deg = arrival_heading
        completed = dict(motion)
        completed["phase"] = "arrived"
        completed["arrived_at"] = started + total_s
        self.movement = {}
        return completed

    def snapshot(self) -> dict:
        result = {"position_m": list(self.position_m),
                "heading_deg": self.heading_deg,
                "face": dict(self.face),
                "posture": self.posture,
                "gesture": self.gesture,
                "gaze_yaw_deg": self.gaze_yaw_deg,
                "gaze_pitch_deg": self.gaze_pitch_deg}
        if self.movement:
            result["movement"] = dict(self.movement)
        return result

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
                 support_surface: str = "yurt_floor",
                 support_oid: str = None,
                 profile_provenance: dict = None,
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
        # Build support is descriptive world state, not a renderer-only
        # convenience.  y_off_m remains the intentional offset relative to
        # this support; ``free`` makes it an absolute world-height offset.
        self.support_surface = str(support_surface or "yurt_floor")
        self.support_oid = str(support_oid) if support_oid else None
        self.profile_provenance = dict(profile_provenance or {})
        self.power = max(0.0, min(1.0, float(power)))
        self.pages = []                         # written artifacts ON the object
        # Commons-board state is content-free at the public snapshot boundary.
        # The append-only records remain in pages for backward-compatible
        # world persistence; per-reader cursors never enter room events.
        self.board_revision = 0
        self.board_reads = {}
        self.memory_ties = []                   # reserved: spatial memory gravity

    def snapshot(self, observer: str = None) -> dict:
        result = {"id": self.id, "name": self.name,
                "position_m": self.position_m, "mass_kg": self.mass_kg,
                "temperature_c": self.temperature_c,
                "affordances": self.affordances,
                "capability": self.capability, "owner": self.owner,
                "description": self.description,
                "texture": self.texture,
                "kind": self.kind, "size_m": self.size_m,
                "rot_deg": self.rot_deg, "y_off_m": self.y_off_m,
                "support_surface": self.support_surface,
                "support_oid": self.support_oid,
                "profile_provenance": dict(self.profile_provenance),
                "power": self.power,
                "pages": len(self.pages)}
        if self.capability == "commons_board":
            from core.commons_board import visible_posts
            present = visible_posts(self)
            result.update({
                "board_revision": int(self.board_revision),
                "active_posts": len(present),
            })
            if observer:
                seen = int(self.board_reads.get(str(observer), 0))
                result["unread_changes"] = max(
                    0, int(self.board_revision) - seen)
        return result


class RoomPlace:
    """A traversable named part of a room, without pretending it is an object.

    Places enter perception and navigation, but never the contact, seating, or
    renderer object contracts.  Their coordinates remain subject to the same
    authored movement boundary as every other destination.
    """

    def __init__(self, pid: str, name: str, position_m,
                 affordances: dict = None, description: str = ""):
        self.id = pid
        self.name = name
        self.position_m = list(position_m)
        self.affordances = dict(affordances or {})
        self.description = description

    def snapshot(self) -> dict:
        return {"id": self.id, "name": self.name,
                "position_m": list(self.position_m),
                "affordances": dict(self.affordances),
                "description": self.description,
                "kind": "place"}


class Room:
    def __init__(self, rid: str, name: str, radius_m: float,
                 description: str = "", movement_boundary: str = ""):
        self.id = rid
        self.name = name
        self.radius_m = float(radius_m)         # yurt radius, meters
        self.movement_boundary = str(movement_boundary or "")
        self.shape = ("island" if self.movement_boundary ==
                      ISLAND_BOUNDARY_ID else "circle")
        self.description = description
        self.objects = {}                       # oid -> RoomObject
        self.places = {}                        # pid -> RoomPlace
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
        # One content-free household floor.  It serializes autonomous room
        # replies across resident processes without owning their wording or
        # deciding whether anybody should speak.  Manual/human speech always
        # invalidates a stale claim.  Expiry is crash recovery only, never a
        # conversation pacing clock.
        self._social_floor = {}

    def _sync_motions(self, now: float = None):
        """Advance active trajectories from their own phase thresholds."""
        now = float(now or time.time())
        completed = []
        for name, member in list(self.members.items()):
            motion = member.advance_motion(now)
            if motion:
                completed.append((name, motion))
        for name, motion in completed:
            self.emit(name, "move_arrive", {
                "motion_id": motion.get("motion_id"),
                "position_m": list(self.members[name].position_m),
                "heading_deg": self.members[name].heading_deg,
                "mode": motion.get("mode"),
            })
        return completed

    def _next_motion_completion_s(self, now: float = None):
        now = float(now or time.time())
        remaining = []
        for member in self.members.values():
            motion = member.movement
            if not motion:
                continue
            due = (float(motion.get("started_at") or now)
                   + float(motion.get("total_duration_s") or 0.0))
            remaining.append(max(0.0, due - now))
        return min(remaining) if remaining else None

    def _interrupt_motion(self, member: str, reason: str):
        self._sync_motions()
        body = self.members.get(member)
        if body is None or not body.movement:
            return None
        interrupted = dict(body.movement)
        body.movement = {}
        self.emit(member, "move_stop", {
            "motion_id": interrupted.get("motion_id"),
            "position_m": list(body.position_m),
            "heading_deg": body.heading_deg,
            "reason": str(reason),
        })
        return interrupted

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
        self._sync_motions()
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
        self._sync_motions()
        bounded = max(1.0, min(30.0, timeout))
        completion_s = self._next_motion_completion_s()
        wait_s = (bounded if completion_s is None
                  else min(bounded, max(0.001, completion_s)))
        with self._event_condition:
            self._event_condition.wait_for(lambda: self._seq > since,
                                           timeout=wait_s)
            self._sync_motions()
            evs = [e for e in self.events if e["seq"] > since]
            if surface:
                evs += [e for e in self.surface_events
                        if e["seq"] > since]
                evs.sort(key=lambda event: event["seq"])
            return evs

    def _latest_say_seq(self) -> int:
        return max((int(event.get("seq") or 0) for event in self.events
                    if event.get("kind") == "say"), default=0)

    def _live_social_floor(self, now: float = None) -> dict:
        now = time.time() if now is None else float(now)
        floor = dict(self._social_floor or {})
        if floor and float(floor.get("expires_at") or 0.0) <= now:
            self._social_floor = {}
            return {}
        return floor

    def social_floor_status(self, now: float = None) -> dict:
        with self._event_condition:
            floor = self._live_social_floor(now)
            return {
                "occupied": bool(floor),
                "owner": str(floor.get("owner") or ""),
                "thread_id": str(floor.get("thread_id") or ""),
                "source_seq": int(floor.get("source_seq") or 0),
                "expires_at": float(floor.get("expires_at") or 0.0),
                "latest_say_seq": self._latest_say_seq(),
            }

    def claim_social_floor(self, member: str, source_seq: int,
                           thread_id: str, lease_s: float = 120.0) -> dict:
        """Atomically claim the current speech revision for one resident."""
        now = time.time()
        member = str(member or "")
        source_seq = max(0, int(source_seq or 0))
        thread_id = str(thread_id or "")
        with self._event_condition:
            if member not in self.members:
                return {"ok": False, "reason": "member_not_present"}
            latest_say = self._latest_say_seq()
            if source_seq <= 0 or source_seq != latest_say:
                return {
                    "ok": False, "reason": "speech_revision_superseded",
                    "latest_say_seq": latest_say,
                }
            floor = self._live_social_floor(now)
            if floor:
                if (floor.get("owner") == member
                        and int(floor.get("source_seq") or 0) == source_seq
                        and str(floor.get("thread_id") or "") == thread_id):
                    return {"ok": True, "reused": True, **floor}
                return {
                    "ok": False, "reason": "floor_occupied",
                    "owner": str(floor.get("owner") or ""),
                    "source_seq": int(floor.get("source_seq") or 0),
                }
            # Bounded by expected model-work envelopes. This deadline only
            # recovers a floor orphaned by a dead resident process.
            lease_s = max(30.0, min(300.0, float(lease_s or 120.0)))
            self._social_floor = {
                "claim_id": uuid.uuid4().hex,
                "owner": member,
                "thread_id": thread_id,
                "source_seq": source_seq,
                "claimed_at": now,
                "expires_at": now + lease_s,
            }
            return {"ok": True, "reused": False, **self._social_floor}

    def release_social_floor(self, member: str, claim_id: str,
                             reason: str = "settled") -> dict:
        """Release only the caller's exact current floor claim."""
        with self._event_condition:
            floor = self._live_social_floor()
            if not floor:
                return {"ok": True, "released": False,
                        "reason": "already_open"}
            if (str(floor.get("owner") or "") != str(member or "")
                    or str(floor.get("claim_id") or "")
                    != str(claim_id or "")):
                return {"ok": False, "released": False,
                        "reason": "claim_mismatch"}
            self._social_floor = {}
            self._event_condition.notify_all()
            return {"ok": True, "released": True,
                    "reason": str(reason or "settled")[:80]}

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
        self._interrupt_motion(member, "leave")
        gone = self.members.pop(member, None)
        self.emit(member, "depart", {
            "position_m": list(gone.position_m) if gone else None})

    # ── space ────────────────────────────────────────────────────
    def _dist(self, a, b) -> float:
        return ((a[0]-b[0])**2 + (a[1]-b[1])**2) ** 0.5

    def _clamp_inside(self, pos) -> list:
        """Radial clamp: a body ends up inside the wall, never in it.
        New in room-1 — the rect never checked; the circle does."""
        usable = self._movement_limit(pos)
        d = (pos[0]**2 + pos[1]**2) ** 0.5
        if d <= usable or d == 0:
            return list(pos)
        s = usable / d
        return [pos[0] * s, pos[1] * s]

    def _movement_limit(self, pos) -> float:
        """Supported radius for this bearing.

        Ordinary rooms retain their yurt circle. The Nexus uses the authored
        island vector, including its pulled-in cove; Godot then resolves the
        exact mesh and full body footprint before drawing motion.
        """
        if self.movement_boundary != ISLAND_BOUNDARY_ID:
            return self.radius_m - WALL_MARGIN_M
        angle = math.atan2(float(pos[1]), float(pos[0]))
        delta = ((angle - ISLAND_COVE_ANGLE_RAD + math.pi) %
                 (2.0 * math.pi) - math.pi)
        cove_weight = 0.0
        if abs(delta) < ISLAND_COVE_HALF_RAD:
            cove_weight = 0.5 * (1.0 + math.cos(
                math.pi * delta / ISLAND_COVE_HALF_RAD))
        return (ISLAND_BASE_SAFE_RADIUS_M *
                (1.0 - ISLAND_COVE_PULL * cove_weight) - WALL_MARGIN_M)

    def object_position_supported(self, pos, size_m: float,
                                  support_surface: str) -> bool:
        """Whether a complete object footprint fits its declared support.

        The Nexus uses the same continuous island envelope as bodies.  Yurt
        floors and walls retain the authored room radius.  Exact mesh height,
        slope, and clearance remain renderer responsibilities.
        """
        try:
            x, y = float(pos[0]), float(pos[1])
            size = max(0.02, float(size_m))
        except (TypeError, ValueError, IndexError):
            return False
        distance = (x * x + y * y) ** 0.5
        surface = str(support_surface or "yurt_floor")
        if surface == "yurt_wall":
            return distance <= self.radius_m + 0.15
        footprint = max(0.05, size * 0.5)
        if (self.movement_boundary == ISLAND_BOUNDARY_ID
                and surface in {"island_ground", "object", "free"}):
            return distance + footprint <= self._movement_limit([x, y])
        return distance + footprint <= self.radius_m

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
        self._sync_motions()
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
        self._sync_motions()
        if member not in self.members or oid not in self.objects:
            return False
        obj = self.objects[oid]
        d = self._dist(self.members[member].position_m,
                       obj.position_m)
        # reach measures to the EDGE of a footprint, not the center
        # -- you can touch a couch you're standing at, even though
        # its centroid is a meter into the cushions.
        return d - self._footprint_r(obj) <= REACH_M

    def _commit_motion(self, member: str, destination,
                       arrival_heading_deg: float, *, mode: str,
                       event_data: dict = None, result_data: dict = None
                       ) -> dict:
        """Commit one host-authoritative destination and trajectory.

        Canonical room state owns the resolved endpoint.  The attached pure
        motion profile is the renderer/body contract for how that same vector
        unfolds; it prevents each face from inventing unrelated timing.
        """
        self._interrupt_motion(member, "redirected")
        me = self.members[member]
        frm = list(me.position_m)
        destination = list(destination)
        motion = build_motion_profile(
            frm, destination, start_heading_deg=me.heading_deg,
            arrival_heading_deg=arrival_heading_deg,
            room_scale_m=self.radius_m)
        # Event, result, persistence, and final projected pose must name the
        # profile's exact endpoint.
        frm = list(motion["from_m"])
        destination = list(motion["to_m"])
        motion.update({
            "motion_id": f"{self.id}:{member}:{self._seq + 1}",
            "mode": str(mode),
            # The same host timestamp gates canonical projection, rendering,
            # and any resident-requested next-choice continuation.
            "started_at": time.time(),
        })
        me.posture = "standing"
        heading_change = abs(signed_heading_delta(
            motion["travel_heading_deg"],
            float(arrival_heading_deg) % 360.0))
        data = dict(event_data or {})
        data.update({
            "from_m": frm, "to_m": destination,
            "heading_deg": float(arrival_heading_deg) % 360.0,
            "motion": motion,
        })
        if motion["distance_m"] > POSITION_EPSILON_M:
            me.start_motion(motion, now=motion["started_at"])
            self.emit(member, "move", data)
        elif (abs(motion["pre_turn_deg"]) > HEADING_EPSILON_DEG
              or heading_change > HEADING_EPSILON_DEG):
            me.start_motion(motion, now=motion["started_at"])
            self.emit(member, "turn", data)
        else:
            motion["phase"] = "unchanged"
        result = {
            "ok": True, "position_m": destination,
            "heading_deg": float(arrival_heading_deg) % 360.0,
            "current_position_m": list(me.position_m), "motion": motion,
        }
        result.update(result_data or {})
        if motion["phase"] == "unchanged":
            result["unchanged"] = True
        return result

    def move_to(self, member: str, oid: str) -> dict:
        """Walk to an object. Movement is an event other members
        perceive — presence has a body, always."""
        self._sync_motions()
        if member not in self.members:
            return {"error": f"{member} is not in {self.id}"}
        if oid in self.members and oid != member:
            # walking to a PERSON: land within reach, not on their tail.
            # Presence is social — the event says who you came to.
            me = self.members[member]
            frm = list(me.position_m)
            tgt = self.members[oid].position_m
            destination = self._deconflict(
                [tgt[0], tgt[1] - 0.8], member)
            # arrival: face the one you came to.
            arrival_heading = heading_toward(destination, tgt)
            return self._commit_motion(
                member, destination, arrival_heading, mode="approach",
                event_data={"toward": oid, "toward_member": oid},
                result_data={"at": oid})
        if oid in self.places:
            place = self.places[oid]
            me = self.members[member]
            frm = list(me.position_m)
            destination = self._deconflict(place.position_m, member)
            arrival_heading = heading_toward(frm, destination)
            return self._commit_motion(
                member, destination, arrival_heading, mode="approach",
                event_data={"toward": place.name, "toward_place": oid},
                result_data={"at": place.name, "place": oid})
        if oid not in self.objects:
            return {"error": f"no object, place, or member '{oid}' "
                             f"in {self.id}"}
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
        destination = self._deconflict(
            [obj.position_m[0] - dx / d * stand_off,
             obj.position_m[1] - dy / d * stand_off], member)
        # arrival: face the thing you walked to.
        arrival_heading = heading_toward(destination, obj.position_m)
        return self._commit_motion(
            member, destination, arrival_heading, mode="approach",
            event_data={"toward": obj.name, "toward_object": oid},
            result_data={"at": obj.name, "object": oid})

    def say(self, member: str, text: str, social_depth: int = 0,
            conversation_id: str = "", social_thread_id: str = "",
            social_parent_seq: int = 0, social_api_token_load: float = 0.0,
            social_route: str = "", floor_claim_id: str = ""):
        """Speech is a percept AND a pull: bodies orient toward
        salient sound. The reflex is pre-cognitive — brainstem-level
        orienting, below decision — which is why the WORLD applies
        it; deliberate attention can override it when personas gain
        that actuation. One cause, one event: 'orient' carries every
        heading that changed."""
        self._sync_motions()
        data = {"text": text or ""}
        if conversation_id:
            data["conversation_id"] = str(conversation_id)
        thread_id = str(social_thread_id or conversation_id or "")
        if thread_id:
            data["social_thread_id"] = thread_id
        if social_parent_seq:
            data["social_parent_seq"] = max(0, int(social_parent_seq))
        if social_api_token_load:
            data["social_api_token_load"] = max(
                0.0, float(social_api_token_load))
        if social_route:
            data["social_route"] = str(social_route)[:40]
        addressed_to = explicit_speech_addressees(text, self.members)
        if addressed_to:
            data["addressed_to"] = addressed_to
        if social_depth > 0:
            data["social_depth"] = int(social_depth)
        with self._event_condition:
            floor = self._live_social_floor()
            if floor_claim_id:
                if (not floor
                        or str(floor.get("claim_id") or "")
                        != str(floor_claim_id)
                        or str(floor.get("owner") or "") != str(member)
                        or int(floor.get("source_seq") or 0)
                        != int(social_parent_seq or 0)
                        or int(social_parent_seq or 0)
                        != self._latest_say_seq()):
                    return {
                        "ok": False,
                        "reason": "social_floor_superseded",
                        "latest_say_seq": self._latest_say_seq(),
                    }
            # Any admitted speech is the new room revision. Manual/human
            # speech therefore preempts an in-flight autonomous floor; an
            # autonomous owner consumes its exact claim on publication.
            self._social_floor = {}
            # Condition owns an RLock, so emit remains atomic with floor
            # consumption while retaining the single event sequence clock.
            self.emit(member, "say", data)
            say_seq = self._seq
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
        return {"ok": True, "seq": say_seq,
                "social_thread_id": thread_id}

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

    def set_transient_pose(self, member: str, pose=None, *, active=True,
                           event_id=""):
        """Publish one bounded, nonpersistent postural accommodation.

        This is a body-surface packet, not room history or member state.  It
        cannot name a feeling, select a held gesture, or change posture.  A
        release is always allowed so a body can relinquish an older claim even
        when another body layer has since taken priority.
        """
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        event_id = str(event_id or "")[:64]
        if not active:
            self.emit_surface(member, "transient_pose", {
                "active": False, "event_id": event_id,
                "replacement_selected": False, "action_chain": False})
            return {"ok": True, "active": False,
                    "replacement_selected": False}
        if m.posture != "standing" or m.gesture:
            return {"error": "body layer occupied",
                    "posture": m.posture,
                    "held_gesture": bool(m.gesture)}
        source = pose if isinstance(pose, dict) else {}
        if set(source) != set(TRANSIENT_POSE_LIMITS):
            return {"error": "transient pose vector is incomplete or unknown"}
        clean = {}
        for name, limit in TRANSIENT_POSE_LIMITS.items():
            try:
                value = float(source[name])
            except (TypeError, ValueError):
                return {"error": f"transient pose {name} must be numeric"}
            if not math.isfinite(value) or abs(value) > limit:
                return {"error": f"transient pose {name} exceeds its bound"}
            if name == "strength" and value < 0.0:
                return {"error": "transient pose strength must be nonnegative"}
            clean[name] = round(value, 6)
        self.emit_surface(member, "transient_pose", {
            "active": True, "event_id": event_id, "pose": clean,
            "semantic_label": None, "action_chain": False})
        return {"ok": True, "active": True, "surface_published": True}

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
            self._interrupt_motion(member, "sit")
            m.position_m = self._clamp_inside(spot)
            m.heading_deg = float(getattr(obj, "rot_deg", 0.0)) % 360.0
            m.posture = "sitting"
            self.emit(member, "sit", {"object": obj.name,
                                      "position_m": m.position_m,
                                      "heading_deg": m.heading_deg,
                                      "posture": m.posture})
            return {"ok": True, "on": obj.name}
        self._interrupt_motion(member, "sit")
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
        self._sync_motions()
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        try:
            tx, ty = float(to[0]), float(to[1])
        except (TypeError, ValueError, IndexError):
            return {"error": "walk needs [x, y] meters"}
        if not math.isfinite(tx) or not math.isfinite(ty):
            return {"error": "walk coordinates must be finite"}
        explicit_heading = None
        if heading_deg is not None:
            try:
                explicit_heading = float(heading_deg)
            except (TypeError, ValueError):
                return {"error": "heading_deg must be numeric"}
            if not math.isfinite(explicit_heading):
                return {"error": "heading_deg must be finite"}
        frm = list(m.position_m)
        dest = self._deconflict([tx, ty], member)
        if explicit_heading is not None:
            arrival_heading = explicit_heading % 360.0
        elif self._dist(frm, dest) > 1e-6:
            arrival_heading = heading_toward(frm, dest)
        else:
            arrival_heading = m.heading_deg
        return self._commit_motion(
            member, dest, arrival_heading, mode="coordinate")

    def look_at(self, member: str, oid: str) -> dict:
        """Aim the optical mount without silently moving its body."""
        self._sync_motions()
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
        self._sync_motions()
        me = self.members.get(member)
        if me is None:
            return {"error": f"{member} is not here"}
        target = self.members.get(oid) or self.objects.get(oid)
        if target is None:
            return {"error": f"no object or member '{oid}' in {self.id}"}
        self._interrupt_motion(member, "turn_toward")
        me.heading_deg = heading_toward(me.position_m, target.position_m)
        me.gaze_yaw_deg = 0.0
        me.gaze_pitch_deg = 0.0
        self.emit(member, "turn", {"toward": oid,
                                    "heading_deg": me.heading_deg,
                                    "gaze_yaw_deg": 0.0,
                                    "gaze_pitch_deg": 0.0})
        return {"ok": True, "toward": oid,
                "optical_pose": me.optical_pose()}

    def look_around(self, member: str) -> dict:
        """Choose one ordered head-camera sweep without inventing a result.

        Four is the existing private visual-episode capacity.  Dividing one
        full turn by that capacity gives evenly spaced quarter-turn frames:
        forward first, then three successive rendered orientations.  The
        durable pose is restored after the episode; the frames and their
        per-view frustum facts are the world's answer.
        """
        self._sync_motions()
        me = self.members.get(member)
        if me is None:
            return {"error": f"{member} is not here"}
        self._interrupt_motion(member, "look_around")
        view_count = 4
        step_deg = 360.0 / view_count
        self.emit(member, "look_around", {
            "heading_deg": me.heading_deg,
            "gaze_yaw_deg": me.gaze_yaw_deg,
            "gaze_pitch_deg": me.gaze_pitch_deg,
            "scan_scope_deg": 360.0,
            "sweep_view_count": view_count,
            "sweep_step_deg": step_deg,
        })
        return {"ok": True, "inspection_phase": "scan",
                "scan_scope_deg": 360.0,
                "sweep_view_count": view_count,
                "sweep_step_deg": step_deg,
                "optical_pose": me.optical_pose()}

    def inspect(self, member: str, oid: str) -> dict:
        """Take one voluntary step toward a clearer view, then stop.

        The controller is staged: torso, gaze, and distance never cascade in
        one call.  The next camera frame returns before another choice exists.
        Detail is an angular range derived from the optical field rather than
        a universal distance; a mug and a person therefore ask for different
        vantage points.
        """
        self._sync_motions()
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
            arrival_heading = heading_toward(
                destination, target.position_m)
            me.gaze_yaw_deg = 0.0
            me.gaze_pitch_deg = 0.0
            movement = self._commit_motion(
                member, destination, arrival_heading, mode="inspect",
                event_data={"toward": oid, "inspection": True},
                result_data={
                    "inspection_phase": "reframe",
                    "desired_distance_m": round(desired_distance, 3),
                })
            return {**receipt, **movement,
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

    def snapshot(self, observer: str = None) -> dict:
        self._sync_motions()
        return {"contract_version": CONTRACT_VERSION,
                "id": self.id, "name": self.name,
                "shape": self.shape, "radius_m": self.radius_m,
                "movement_boundary": self.movement_boundary,
                "description": self.description,
                "members": {m: mem.snapshot()
                            for m, mem in self.members.items()},
                "objects": {o.id: o.snapshot(observer=observer)
                            for o in self.objects.values()},
                "places": {p.id: p.snapshot()
                           for p in self.places.values()},
                "last_seq": self._seq}
