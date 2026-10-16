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
from room.furniture_rest import profile as rest_profile, support as rest_support, BED_POSES
from collections import deque
from threading import Condition

from core.life_afferents import (
    sanitize_continuous_afferent, sanitize_life_condition,
    sanitize_witnessed_event,
)
from core.household_physics import (
    HouseholdPhysicsError, HouseholdPhysicsState, canonical_hash,
    default_light_physics, validate_object_physics,
)
from core.locomotion import (
    HEADING_EPSILON_DEG, POSITION_EPSILON_M, build_motion_profile,
    signed_heading_delta,
)

REACH_M = 1.2          # arm's length: capability + contact gate
DOOR_INTERACTION_M = 8.0  # door gaze/menu range, published to the renderer
                          # 20260916: bumped 4.5 -> 8.0 so the entry hallway
                          # of a den (~3.2m from door to chamber junction)
                          # plus a step into the chamber all count as "at the
                          # door". kay_door / reed_door sit at the far end of
                          # a tube; the old 4.5 could refuse a body that was
                          # visually right at the door if the walk-sync
                          # lagged by even a couple of steps.
STONES_INTERACTION_M = 7.0  # standing stones ring: anywhere in the circle
                            # counts (ring radius ~4.4m) plus a comfortable
                            # buffer outside. 20260916: the old default
                            # (footprint_r + REACH_M = 5.6m from center) was
                            # nominally enough for the ring interior, but
                            # walk-sync lag could still refuse a body
                            # visually standing between the stones.
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
MAX_CONTINUOUS_AFFERENT_PACKETS = 64
EXPRESSIVE_MOTIONS = {
    "neck_stretch", "look_around", "talk_gesture", "talk_gesture_alt",
    "seated_point", "seated_clap", "seated_laugh", "seated_talk",
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
    """Resolve explicit vocatives, including multiple people in one turn."""
    words = str(text or "").strip()
    words = words.lstrip('"“”‘’')
    if not words:
        return []
    words = re.sub(
        r"^(?:(?:hey|hi|hello|so|well|okay|ok)[\s,!:;\-–—]+)+",
        "", words, flags=re.IGNORECASE)
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
    found = []
    # A roll call may be followed by ordinary prose: "Alex, Morgan, you here?"
    for part in listed:
        if part not in member_aliases:
            break
        found.append(member_aliases[part])
    # Keep the opening address, then collect other explicit vocatives.
    # Descriptions such as "This is Bo" or "Cy - she's ..." still do not
    # count as addresses, but "Bo, meet Ari" does.
    for alias in sorted(member_aliases, key=len, reverse=True):
        escaped = re.escape(alias)
        leading = re.match(
            rf"^(?:(?:hey|hi|hello)[\s,!:;-]+)?{escaped}"
            rf"(?:\s*[,!?:;.\-]|\s*$)",
            words, flags=re.IGNORECASE)
        if leading:
            found.append(member_aliases[alias])
    for member in members:
        raw = str(member)
        aliases = {raw, raw.replace("_", " "), raw.split("_", 1)[0]}
        for alias in sorted(aliases, key=len, reverse=True):
            escaped = re.escape(alias)
            boundary = r'''(?:^|[.!?]\s+|["“])'''
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
    return list(dict.fromkeys(found))


def heading_toward(frm, to) -> float:
    """The heading that faces `to` from `frm`. Degenerate (same
    point) -> 0.0, the door-neutral default."""
    dx = float(to[0]) - float(frm[0])
    dy = float(to[1]) - float(frm[1])
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return 0.0
    return math.degrees(math.atan2(-dx, dy)) % 360.0


# ── POLYGON FLOORS (portal build, 20260901) ───────────────────────
# Rooms whose shape comes from an authored mesh (a cave) carry a
# walkable region: a list of polygons in room [x, y] meters, emitted by
# the same build script that made the GLB. Nothing here is retyped —
# the polygon IS the derivation. Union semantics: inside any polygon
# is inside the room.
POLYGON_BOUNDARY_ID = "polygon"


def _point_in_polygon(pt, poly) -> bool:
    """Even-odd ray cast. `poly` is a closed ring of [x, y]."""
    x, y = float(pt[0]), float(pt[1])
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = float(poly[i][0]), float(poly[i][1])
        xj, yj = float(poly[j][0]), float(poly[j][1])
        if (yi > y) != (yj > y):
            x_cross = xj + (y - yj) * (xi - xj) / ((yi - yj) or 1e-12)
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def _nearest_on_segment(pt, a, b):
    """Closest point to `pt` on segment a-b."""
    px, py = float(pt[0]), float(pt[1])
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom <= 1e-12:
        return [ax, ay]
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    return [ax + t * dx, ay + t * dy]


def _polygon_centroid(poly):
    xs = [float(p[0]) for p in poly]
    ys = [float(p[1]) for p in poly]
    return [sum(xs) / len(xs), sum(ys) / len(ys)]


class Member:
    """A body in a room (room-2): where it stands and which way it
    faces. Presence gained an orientation; pose and posture move in
    here when the pose layer lands (phase 2)."""
    def __init__(self, name: str, position_m,
                 heading_deg: float = 0.0, face=None,
                 posture: str = "standing", gaze_yaw_deg: float = 0.0,
                 gaze_pitch_deg: float = 0.0, gesture: str = "",
                 movement: dict = None, height_m: float = 0.0,
                 posture_since: float = 0.0, support_pose: dict = None):
        self.name = name
        self.position_m = list(position_m)      # [x, y] meters
        self.height_m = float(height_m)
        self.heading_deg = float(heading_deg) % 360.0
        self.face = dict(face or {})    # expression packet: SURFACE
        # (room-2 additive, 20260719): what a camera would see --
        # the persona-side distiller already chose what shows.
        self.posture = str(posture or "standing")
        self.support_pose = dict(support_pose or {})
        # (20260914) wall-clock of the last posture change. Duration in a
        # posture is a measurement the rest field wants (postural_rest);
        # the room is the only honest source for it.
        self.posture_since = float(posture_since or time.time())
        self.gesture = str(gesture or "")
        self.gaze_yaw_deg = max(-85.0, min(85.0, float(gaze_yaw_deg)))
        self.gaze_pitch_deg = max(-60.0, min(60.0, float(gaze_pitch_deg)))
        # (20260914) durable gaze target: a member or object id, or "".
        # While set, the room re-aims yaw/pitch each tick (see _refresh_gazes).
        self.gaze_target = ""
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
            progress = elapsed / move_s if motion.get("interpolation") == "linear" else self._motion_ease(elapsed / move_s)
            self.position_m = [
                start[index] + (destination[index] - start[index]) * progress
                for index in (0, 1)]
            if motion.get('path_xyz'):
                path = motion['path_xyz']
                offset = progress * (len(path)-1)
                index = min(len(path)-2, int(offset))
                f = offset-index
                a, b = path[index:index+2]
                self.position_m = [a[0]+(b[0]-a[0])*f, -(a[2]+(b[2]-a[2])*f)]
                self.height_m = a[1]+(b[1]-a[1])*f
            self.heading_deg = travel_heading
            return None
        self.position_m = destination
        if motion.get('path_xyz'):
            self.height_m = motion['path_xyz'][-1][1]
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
                "height_m": self.height_m,
                "heading_deg": self.heading_deg,
                "face": dict(self.face),
                "posture": self.posture,
                "posture_since": self.posture_since,
                "support_pose": dict(self.support_pose) if self.posture != 'standing' else {},
                "gesture": self.gesture,
                "gaze_yaw_deg": self.gaze_yaw_deg,
                "gaze_pitch_deg": self.gaze_pitch_deg,
                "gaze_target": self.gaze_target}
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
                 power: float = 0.0,
                 light_settings: dict = None,
                 physics_kind: str = None,
                 physics_revision: int = 0,
                 physics_traits: dict = None,
                 physics_recipe: dict = None,
                 physics_history: list = None):
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
        self.light_settings = dict(light_settings) if light_settings else None
        self.physics_kind = str(physics_kind or "")
        self.physics_revision = max(0, int(physics_revision or 0))
        self.physics_traits = dict(physics_traits or {})
        self.physics_recipe = dict(physics_recipe or {})
        self.physics_history = list(physics_history or [])[-40:]
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
                "rest_support": rest_profile(self),
                "profile_provenance": dict(self.profile_provenance),
                "power": self.power,
                "light_settings": self.light_settings,
                "physics": {
                    "kind": self.physics_kind,
                    "revision": self.physics_revision,
                    "traits": dict(self.physics_traits),
                    "recipe": dict(self.physics_recipe),
                },
                "pages": len(self.pages)}
        if self.kind == "studio_frame":
            result["studio"] = dict(self.profile_provenance.get("studio") or {})
        if self.capability == "commons_board":
            from core.commons_board import visible_posts
            from core.collective_arcs import project_collective_arcs
            present = visible_posts(self)
            arcs = project_collective_arcs(self, include_text=False)
            result.update({
                "board_revision": int(self.board_revision),
                "active_posts": len(present),
                "collective_arcs": arcs,
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
                 affordances: dict = None, description: str = "",
                 physics_traits: dict = None):
        self.id = pid
        self.name = name
        self.position_m = list(position_m)
        self.affordances = dict(affordances or {})
        self.description = description
        self.physics_traits = dict(physics_traits or {})

    def snapshot(self) -> dict:
        return {"id": self.id, "name": self.name,
                "position_m": list(self.position_m),
                "affordances": dict(self.affordances),
                "description": self.description,
                "physics_traits": dict(self.physics_traits),
                "kind": "place"}


class Room:
    def __init__(self, rid: str, name: str, radius_m: float,
                 description: str = "", movement_boundary: str = "",
                 owner: str = None, scene: str = "", walkable=None,
                 arrival_m=None, arrival_heading_deg: float = None):
        self.id = rid
        self.name = name
        self.radius_m = float(radius_m)         # yurt radius, meters
        self.movement_boundary = str(movement_boundary or "")
        # walkable: list of polygons ([[x, y], ...]) in room meters. When
        # present the room is polygon-shaped and radius_m is only a
        # coarse hint for renderers/culling, never a clamp.
        self.walkable = [[list(map(float, p)) for p in poly]
                         for poly in (walkable or []) if len(poly) >= 3]
        if self.walkable:
            self.movement_boundary = POLYGON_BOUNDARY_ID
            self.shape = "polygon"
        else:
            self.shape = ("island" if self.movement_boundary ==
                          ISLAND_BOUNDARY_ID else "circle")
        # scene: which Godot world renders this room. Rooms that share a
        # scene are in the same world (the island); a room with its own
        # scene is its own world, reached only through a portal.
        self.scene = str(scene or "").strip() or "island"
        # arrival: where a body lands when it enters (join/travel). Yurts
        # keep the south-rim door default; authored rooms declare theirs.
        self.arrival_m = (list(map(float, arrival_m))
                          if arrival_m is not None else None)
        self.arrival_heading_deg = (
            float(arrival_heading_deg) % 360.0
            if arrival_heading_deg is not None else None)
        self.description = description
        self.owner = str(owner or "").strip().lower() or None
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
        # Last-value ambient room weather. This contains only sanitized,
        # low-dimensional conditions after a real afferent admission; media,
        # transcripts, subjects, and semantic observations never enter it.
        self.life_afferents = {}
        # Quiet, content-free environmental intervals use their own bounded
        # revision stream. They are body input for currently co-located
        # residents, not room events: they never advance _seq, wake the event
        # condition, enter conversation history, or survive as a replay log.
        self.continuous_afferents = deque(
            maxlen=MAX_CONTINUOUS_AFFERENT_PACKETS)
        self._continuous_afferent_revision = 0
        self._continuous_afferent_stream_id = uuid.uuid4().hex
        self._seq = 0
        self._event_condition = Condition()
        # Exact-audience conversation traffic shares the room's wakeup
        # threshold without entering its public event sequence.  Each member
        # gets only their latest visible private revision, so even the fact
        # that somebody else's private conversation advanced is not exposed.
        self._private_revisions = {}
        # One content-free household floor.  It serializes autonomous room
        # replies across resident processes without owning their wording or
        # deciding whether anybody should speak.  Manual/human speech always
        # invalidates a stale claim.  Expiry is crash recovery only, never a
        # conversation pacing clock.
        self._social_floor = {}
        # The room stays canonical.  This is its typed relationship history,
        # not a second world or a second event loop.
        self.physics = HouseholdPhysicsState(self.id)
        # PORTALS (20260901). A portal is an object with
        # capability='portal'. The room knows where its portals are; it
        # does not know where they lead -- that is the map, which the
        # host holds. The host injects a resolver at boot:
        #   portal_resolver(room_id, member) -> [{"room": rid, ..}, ...]
        # so the room can emit a complete offer without importing the
        # bench. No resolver = portals are inert (offer never fires).
        self.portal_resolver = None

    def portals_near(self, member: str) -> list:
        """Portal objects whose footprint this body is within reach of."""
        if member not in self.members:
            return []
        self._sync_motions()
        def _in_reach(oid: str, o) -> bool:
            if oid.endswith("door"):
                return self._dist(self.members[member].position_m,
                                  o.position_m) <= DOOR_INTERACTION_M
            if oid.endswith("stones"):
                return self._dist(self.members[member].position_m,
                                  o.position_m) <= STONES_INTERACTION_M
            return self.near(member, oid)
        return [oid for oid, o in self.objects.items()
                if o.capability == "portal" and _in_reach(oid, o)]

    def object_snapshot(self, obj, observer=None):
        record = obj.snapshot(observer=observer)
        if obj.capability == 'garden':
            record['interaction_radius_m'] = self._footprint_r(obj) + REACH_M
            record['interaction_y_m'] = self.object_elevation(obj.id)
            record['description'] = getattr(self, '_garden_descriptions', {}).get(obj.id, record['description'])
        if obj.capability == 'portal':
            if obj.id.endswith('door'):
                record['interaction_radius_m'] = DOOR_INTERACTION_M
            elif obj.id.endswith('stones'):
                record['interaction_radius_m'] = STONES_INTERACTION_M
            else:
                record['interaction_radius_m'] = self._footprint_r(obj) + REACH_M
            record['interaction_height_m'] = 1.5 if getattr(self, 'navigation', None) else None
            record['interaction_y_m'] = self.object_elevation(obj.id)
        return record

    def _offer_portals(self, member: str, cause: str):
        """Emit 'portal_offer' if this body has just come to rest at a
        portal. A PERCEPT, not a prompt: what the standing stones feel
        like from inside the ring. Fires once per arrival; Godot and
        the wrappers decide what to show/do with it."""
        if self.portal_resolver is None:
            return None
        here = self.portals_near(member)
        if not here:
            return None
        try:
            destinations = list(self.portal_resolver(self.id, member) or [])
        except Exception:
            destinations = []
        self.emit(member, "portal_offer", {
            "portal": here[0], "portals": here,
            "destinations": destinations, "cause": cause})
        return {"portal": here[0], "destinations": destinations}

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
            self._offer_portals(name, "move_arrive")
            intent = motion.get('rest_on_arrival')
            if intent:
                result = self.rest(name, intent['object'], intent.get('variant', ''), approach=False)
                if result.get('error'):
                    self.emit(name, 'rest_failed', {'object': intent['object'], 'error': result['error']})
        self._refresh_gazes()
        return completed

    # ---- GAZE (20260914) -------------------------------------------------
    # A gaze is a TARGET, not a number. While gaze_target is set the optical
    # mount re-aims every tick, so "looking at Re" keeps looking at Re when
    # either body moves, sits, or lies down. Pitch comes from eye height per
    # posture, so a standing body looking at a floor-sitter looks DOWN into
    # her eyes instead of over her head.
    EYE_HEIGHT_FRACTION = {"standing": 0.93, "sitting": 0.62,
                           "sitting_floor": 0.45, "lying": 0.12}

    def _eye_height_m(self, target) -> float:
        base = float(getattr(target, "height_m", 0.0) or 0.0)
        if isinstance(target, Member):
            if base <= 0.0:
                base = 1.7
            return base * self.EYE_HEIGHT_FRACTION.get(
                target.posture, 0.93)
        # objects: their stated height, else the middle of a person
        return base if base > 0.0 else 1.0

    def _aim_gaze(self, me, target) -> tuple:
        absolute = heading_toward(me.position_m, target.position_m)
        relative = (absolute - me.heading_deg + 180.0) % 360.0 - 180.0
        run = max(0.05, self._dist(me.position_m, target.position_m))
        rise = self._eye_height_m(target) - self._eye_height_m(me)
        pitch = math.degrees(math.atan2(rise, run))
        return (max(-85.0, min(85.0, relative)),
                max(-60.0, min(60.0, pitch)))

    def _refresh_gazes(self):
        for me in self.members.values():
            oid = getattr(me, "gaze_target", "")
            if not oid:
                continue
            target = self.members.get(oid) or self.objects.get(oid)
            if target is None:            # target left the room
                me.gaze_target = ""
                me.gaze_yaw_deg = 0.0
                me.gaze_pitch_deg = 0.0
                continue
            me.gaze_yaw_deg, me.gaze_pitch_deg = self._aim_gaze(me, target)

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
            event = {"seq": self._seq,
                     "ts": time.strftime("%H:%M:%S"),
                     "t": time.time(),
                     "member": member, "kind": kind,
                     "data": data or {}}
            self.events.append(event)
            self._event_condition.notify_all()
            return dict(event)

    def note_life_afferent(self, modality: str, condition: dict, *,
                           salience: float, confidence: float = 1.0,
                           source_event_id: str = "", now: float = None,
                           conversational: bool = True):
        """Admit one already-thresholded ambient condition into the room.

        This is shared environmental state, not an action by the resident who
        happened to own the browser device. The room retains dimensional
        changes and provenance only; no pixels, audio, transcript, detected
        person, inferred state, or required conversational consequence fits
        this contract.
        """
        modality = str(modality or "").casefold()
        clean = sanitize_life_condition(modality, condition)
        now = float(time.time() if now is None else now)
        prior = dict(self.life_afferents.get(modality) or {})
        prior_condition = dict(prior.get("condition") or {})
        change = {}
        for key, value in clean.items():
            if key not in prior_condition:
                continue
            try:
                change[key] = round(value - float(prior_condition[key]), 6)
            except (TypeError, ValueError):
                continue
        previous_at = prior.get("updated")
        duration = (max(0.0, now - float(previous_at))
                    if previous_at is not None else None)
        state = {
            "modality": modality,
            "condition": clean,
            "updated": now,
            "source_event_id": str(source_event_id or "")[:120],
        }
        self.life_afferents[modality] = state
        data = {
            "schema_version": 1,
            "modality": modality,
            "condition": clean,
            "change": change,
            "salience": round(max(0.0, min(1.0, float(salience))), 6),
            "confidence": round(max(
                0.0, min(1.0, float(confidence))), 6),
            "duration_since_change_s": (
                round(duration, 3) if duration is not None else None),
            "source_event_id": state["source_event_id"],
            "conversational": bool(conversational),
            "content_free": True,
        }
        event = self.emit("the room", "life_afferent", data)
        return {"ok": True, "seq": event["seq"],
                "modality": modality, "event": event}

    def note_continuous_afferent(self, modality: str, packet: dict, *,
                                 anchor_member: str,
                                 now: float = None) -> dict:
        """Publish one physical interval to bodies sharing the anchor's room.

        The instrument is attached to a process, but the measured air belongs
        to the room occupied by ``anchor_member``. This lane is deliberately
        non-episodic: the separate revision exists only for lossless bounded
        intake and deduplication.
        """
        anchor_key = str(anchor_member or "").strip().casefold()
        anchor = next((name for name in self.members
                       if str(name).casefold() == anchor_key), "")
        if not anchor:
            raise ValueError(
                f"ambient anchor is not present in room '{self.id}'")
        clean = sanitize_continuous_afferent(modality, packet)
        registration_id = clean["registration_id"]
        with self._event_condition:
            for prior in reversed(self.continuous_afferents):
                if ((prior.get("packet") or {}).get("registration_id")
                        == registration_id):
                    return {
                        "ok": True,
                        "duplicate": True,
                        "room_id": self.id,
                        "stream_id": self._continuous_afferent_stream_id,
                        "revision": prior["revision"],
                        "anchor_member": prior["anchor_member"],
                        "resident_count": len(self.members),
                        "content_free": True,
                        "room_event_created": False,
                    }
            self._continuous_afferent_revision += 1
            entry = {
                "revision": self._continuous_afferent_revision,
                "room_id": self.id,
                "anchor_member": anchor,
                "received_at": float(time.time() if now is None else now),
                "modality": str(modality or "").strip().casefold(),
                "packet": clean,
            }
            self.continuous_afferents.append(entry)
        return {
            "ok": True,
            "duplicate": False,
            "room_id": self.id,
            "stream_id": self._continuous_afferent_stream_id,
            "revision": entry["revision"],
            "anchor_member": anchor,
            "resident_count": len(self.members),
            "content_free": True,
            "room_event_created": False,
        }

    def continuous_afferents_since(self, member: str, *, since: int = 0,
                                   stream_id: str = "") -> dict:
        """Return unseen intervals to one currently present resident body.

        A new body, an overrun cursor, or a host generation change rebases to
        the latest active packet per modality with zero duration. The current
        room state registers without making the body re-live old intervals.
        """
        member_key = str(member or "").strip().casefold()
        present = next((name for name in self.members
                        if str(name).casefold() == member_key), "")
        if not present:
            raise ValueError(f"resident is not present in room '{self.id}'")
        try:
            requested = max(0, int(since or 0))
        except (TypeError, ValueError):
            requested = 0
        with self._event_condition:
            current = self._continuous_afferent_revision
            ring = list(self.continuous_afferents)
            generation_changed = bool(
                stream_id and stream_id !=
                self._continuous_afferent_stream_id)
            oldest = int(ring[0]["revision"]) if ring else current + 1
            truncated = bool(
                generation_changed or requested <= 0
                or (ring and requested < oldest - 1)
                or requested > current)
            active = [entry for entry in ring
                      if entry.get("anchor_member") in self.members]
            if truncated:
                latest = {}
                for entry in active:
                    latest[entry.get("modality")] = entry
                selected = sorted(
                    latest.values(), key=lambda item: item["revision"])
            else:
                selected = [entry for entry in active
                            if int(entry["revision"]) > requested]
            entries = []
            for source in selected:
                item = {
                    key: value for key, value in source.items()
                    if key != "packet"}
                item["packet"] = dict(source.get("packet") or {})
                if truncated:
                    item["packet"]["duration_s"] = 0.0
                    item["packet"]["has_previous"] = False
                    item["rebased"] = True
                entries.append(item)
        return {
            "ok": True,
            "room_id": self.id,
            "member": present,
            "stream_id": self._continuous_afferent_stream_id,
            "cursor": current,
            "entries": entries,
            "rebased": truncated,
            "content_free": True,
            "room_event_created": False,
        }

    def note_witnessed_event(self, packet: dict, *, salience: float,
                             now: float = None):
        """Emit one bounded semantic observation from a real sensory path.

        The event belongs to the shared environment, not to whichever resident
        process happened to host the camera or hardware driver.  Descriptions
        can include people, faces, names, actions, speech, and readable text.
        Provenance remains attached so downstream residents can preserve the
        difference between direct state, driver report, and model transduction.
        """
        clean = sanitize_witnessed_event(packet)
        clean["salience"] = round(
            max(0.0, min(1.0, float(salience))), 6)
        clean["observed_at"] = float(time.time() if now is None else now)
        event = self.emit("the room", "witnessed_event", clean)
        return {"ok": True, "seq": event["seq"], "event": event}

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

    def note_private_revision(self, members, seq: int):
        """Wake only members in the durable event's exact audience."""
        revision = max(0, int(seq or 0))
        with self._event_condition:
            for member in members or ():
                key = str(member or "").strip().casefold()
                if key:
                    self._private_revisions[key] = max(
                        revision, int(self._private_revisions.get(key) or 0))
            self._event_condition.notify_all()

    def private_revision(self, member: str) -> int:
        with self._event_condition:
            return max(0, int(self._private_revisions.get(
                str(member or "").strip().casefold()) or 0))

    def wait_for_events(self, since: int, timeout: float = 25.0,
                        surface: bool = False, *, member: str = "",
                        private_since: int = 0) -> list:
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
            private_key = str(member or "").strip().casefold()
            self._event_condition.wait_for(
                lambda: (self._seq > since
                         or (bool(private_key)
                             and int(self._private_revisions.get(
                                 private_key) or 0) > int(private_since))),
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
                "source_kind": str(floor.get("source_kind") or ""),
                "speech_revision_seq": int(
                    floor.get("speech_revision_seq") or 0),
                "expires_at": float(floor.get("expires_at") or 0.0),
                "latest_say_seq": self._latest_say_seq(),
            }

    def claim_social_floor(self, member: str, source_seq: int,
                           thread_id: str, lease_s: float = 120.0, *,
                           source_kind: str = "speech") -> dict:
        """Atomically claim one causal room revision for one resident."""
        now = time.time()
        member = str(member or "")
        source_seq = max(0, int(source_seq or 0))
        thread_id = str(thread_id or "")
        source_kind = "ambient" if str(source_kind) == "ambient" else "speech"
        with self._event_condition:
            if member not in self.members:
                return {"ok": False, "reason": "member_not_present"}
            latest_say = self._latest_say_seq()
            source_event = next((
                event for event in reversed(self.events)
                if int(event.get("seq") or 0) == source_seq), None)
            valid_source = (
                source_seq > 0
                and source_event is not None
                and ((source_kind == "speech"
                      and source_event.get("kind") == "say"
                      and source_seq == latest_say)
                     or (source_kind == "ambient"
                         and source_event.get("kind") != "say")))
            if not valid_source:
                return {
                    "ok": False, "reason": "causal_revision_superseded",
                    "latest_say_seq": latest_say,
                }
            floor = self._live_social_floor(now)
            if floor:
                if (floor.get("owner") == member
                        and int(floor.get("source_seq") or 0) == source_seq
                        and str(floor.get("source_kind") or "speech")
                        == source_kind
                        and str(floor.get("thread_id") or "") == thread_id):
                    return {"ok": True, "reused": True, **floor}
                return {
                    "ok": False, "reason": "floor_occupied",
                    "owner": str(floor.get("owner") or ""),
                    "source_seq": int(floor.get("source_seq") or 0),
                }
            priority = getattr(self, '_floor_priority', set()) & set(self.members)
            if now - getattr(self, '_floor_priority_at', now) >= getattr(self, 'floor_address_stale_s', 86400):
                priority = set()
                self._floor_priority = set()
            if priority and member not in priority:
                return {'ok': False, 'reason': 'named_residents_first'}
            used = getattr(self, '_ambient_floor_used', set())
            if source_kind == 'ambient' and source_seq in used:
                return {'ok': False, 'reason': 'event_floor_budget_spent'}
            if source_kind == 'ambient':
                self._ambient_floor_used = {s for s in used if s >= source_seq - 500} | {source_seq}
            if member in priority:
                self._floor_priority = priority - {member}
            # Bounded by expected model-work envelopes. This deadline only
            # recovers a floor orphaned by a dead resident process.
            lease_s = max(30.0, min(300.0, float(lease_s or 120.0)))
            self._social_floor = {
                "claim_id": uuid.uuid4().hex,
                "owner": member,
                "thread_id": thread_id,
                "source_seq": source_seq,
                "source_kind": source_kind,
                "speech_revision_seq": latest_say,
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
    def prepare_join(self, member: str, at=None, *, height_m=None, heading_deg=None):
        """Resolve the arrival body before a transfer removes its old body."""
        # the door: one, south rim, just inside — yurts agree. Authored
        # rooms (polygon floors) declare their own arrival instead.
        door = (list(self.arrival_m) if self.arrival_m is not None
                else [0.0, -(self.radius_m - 0.5)])
        pos = self._deconflict(self._clamp_inside(list(at or door)),
                               member)
        # you walk in facing the room: heading toward the center, unless
        # the room says which way its door faces.
        heading = (self.arrival_heading_deg
                   if (at is None and self.arrival_heading_deg is not None)
                   else heading_toward(pos, [0.0, 0.0]))
        m = Member(member, pos, heading)
        if getattr(self, 'navigation', None):
            nav = self.navigation
            y = nav.support(pos[0], -pos[1], self.arrival_height if height_m is None else height_m)
            if y is None or not nav.clear(pos[0], y, -pos[1]):
                pos = list(self.arrival_m)
                y = self.arrival_height
            m.position_m = pos
            m.height_m = y
        if heading_deg is not None:
            m.heading_deg = float(heading_deg)
        return m

    def join(self, member: str, at=None, *, height_m=None, heading_deg=None,
             prepared=None):
        m = prepared if prepared is not None else self.prepare_join(
            member, at, height_m=height_m, heading_deg=heading_deg)
        self.members[member] = m
        self.emit(member, "arrive", {"position_m": m.position_m,
                                     "height_m": m.height_m,
                                     "heading_deg": m.heading_deg})
        # arriving AT a portal (the private door is the den's arrival point)
        # is the same percept as walking up to one.
        self._offer_portals(member, "arrive")

    def leave(self, member: str):
        self._interrupt_motion(member, "leave")
        gone = self.members.pop(member, None)
        return self.emit(member, "depart", {
            "position_m": list(gone.position_m) if gone else None})

    # ── space ────────────────────────────────────────────────────
    def _dist(self, a, b) -> float:
        return ((a[0]-b[0])**2 + (a[1]-b[1])**2) ** 0.5

    def _clamp_inside(self, pos) -> list:
        """Radial clamp: a body ends up inside the wall, never in it.
        New in room-1 — the rect never checked; the circle does.
        Polygon floors (20260901): inside any walkable polygon is
        inside; outside, you land on the nearest edge, pulled one
        wall-margin toward that polygon's interior."""
        if getattr(self, 'navigation', None):
            return list(pos)
        if self.walkable:
            return self._clamp_inside_polygon(pos)
        usable = self._movement_limit(pos)
        d = (pos[0]**2 + pos[1]**2) ** 0.5
        if d <= usable or d == 0:
            return list(pos)
        s = usable / d
        return [pos[0] * s, pos[1] * s]

    def _inside_walkable(self, pos) -> bool:
        return any(_point_in_polygon(pos, poly) for poly in self.walkable)

    def _clamp_inside_polygon(self, pos) -> list:
        if self._inside_walkable(pos):
            return [float(pos[0]), float(pos[1])]
        best, best_d, best_poly = None, float("inf"), None
        for poly in self.walkable:
            n = len(poly)
            for i in range(n):
                cand = _nearest_on_segment(pos, poly[i], poly[(i + 1) % n])
                d = self._dist(pos, cand)
                if d < best_d:
                    best, best_d, best_poly = cand, d, poly
        if best is None:
            return [float(pos[0]), float(pos[1])]
        # step one wall-margin toward the interior so the body is not
        # standing IN the wall; if the centroid is degenerate, stay put.
        c = _polygon_centroid(best_poly)
        vx, vy = c[0] - best[0], c[1] - best[1]
        length = (vx * vx + vy * vy) ** 0.5
        if length <= 1e-9:
            return best
        step = min(WALL_MARGIN_M, length)
        return [best[0] + vx / length * step, best[1] + vy / length * step]

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
        if self.walkable:
            # polygon floors: the object's center must be inside; the
            # exact footprint-vs-wall check stays with the renderer,
            # same division of labor as the island envelope.
            return self._inside_walkable([x, y])
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
        if getattr(self, 'navigation', None) and abs(
                self.members[member].height_m - self.object_elevation(oid)) > 1.5:
            return False
        d = self._dist(self.members[member].position_m,
                       obj.position_m)
        # reach measures to the EDGE of a footprint, not the center
        # -- you can touch a couch you're standing at, even though
        # its centroid is a meter into the cushions.
        return d - self._footprint_r(obj) <= REACH_M

    def object_elevation(self, oid: str, seen=None) -> float:
        """Resolve a furniture support anchor in the workshop's vertical frame.

        Ground-relative offsets are not absolute elevations. A supported
        object's anchor follows its parent, so reach cannot cross storeys.
        """
        obj = self.objects[oid]
        nav = getattr(self, 'navigation', None)
        if nav is None or obj.support_surface == 'free':
            return obj.y_off_m
        seen = set(seen or ())
        if oid in seen: return obj.y_off_m
        seen.add(oid)
        if obj.support_surface == 'object' and obj.support_oid in self.objects:
            return self.object_elevation(obj.support_oid, seen) + obj.y_off_m
        terrain = nav.terrain(obj.position_m[0], -obj.position_m[1])
        return (terrain or 0.0) + obj.y_off_m

    def _commit_motion(self, member: str, destination,
                       arrival_heading_deg: float, *, mode: str,
                       event_data: dict = None, result_data: dict = None,
                       controlled_speed: float = None
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
        path, blocked = None, ''
        if getattr(self, 'navigation', None):
            path, blocked = self.navigation.trace(
                [frm[0], me.height_m, -frm[1]], [destination[0], -destination[1]])
            destination = [path[-1][0], -path[-1][2]]
            if len(path) < 2:
                return {'ok': True, 'unchanged': True, 'position_m': frm,
                        'height_m': me.height_m, 'blocked_by': blocked}
        motion = build_motion_profile(
            frm, destination, start_heading_deg=me.heading_deg,
            arrival_heading_deg=arrival_heading_deg,
            room_scale_m=self.radius_m)
        if controlled_speed is not None:
            # Keyboard walking follows the camera at the player traversal speed.
            # The destination/path above has already passed the same collision sweep.
            distance = sum(math.dist(a,b) for a,b in zip(path,path[1:])) if path else math.dist(frm,destination)
            duration = distance / controlled_speed
            motion.update(interpolation='linear', cruise_speed_mps=controlled_speed,
                          turn_duration_s=0., settle_duration_s=0., move_duration_s=duration,
                          total_duration_s=duration, start_heading_deg=arrival_heading_deg,
                          travel_heading_deg=arrival_heading_deg, arrival_heading_deg=arrival_heading_deg,
                          pre_turn_deg=0., settle_turn_deg=0.)
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
        if path:
            motion['path_xyz'] = path
            motion['blocked_by'] = blocked
        # (20260914) only real travel stands a body up. A heading-only
        # turn in place (the client publishes look-yaw this way) leaves a
        # seated or lying body exactly as it was -- and a LYING body does
        # not turn at all: its yaw belongs to the neck, not the spine.
        if motion["distance_m"] > POSITION_EPSILON_M:
            if me.posture != "standing":
                me.posture_since = time.time()
            me.posture = "standing"
            me.support_pose = {}
        elif me.posture == "lying":
            return {"ok": True, "unchanged": True, "posture": "lying",
                    "note": "lying bodies turn their head, not their heading"}
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
            "blocked_by": blocked,
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
            social_route: str = "", floor_claim_id: str = "",
            social_origin_seq: int = 0, social_origin_kind: str = "",
            social_relation: str = "", conversation_turn_for=None,
            floor_provenance=None, floor_response=None, explicit_addresses=None):
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
        if social_origin_seq:
            data["social_origin_seq"] = max(0, int(social_origin_seq))
        if social_origin_kind:
            data["social_origin_kind"] = str(social_origin_kind)[:40]
        if social_relation:
            data["social_relation"] = str(social_relation)[:40]
        if social_api_token_load:
            data["social_api_token_load"] = max(
                0.0, float(social_api_token_load))
        if social_route:
            data["social_route"] = str(social_route)[:40]
        addressed_to = (list(explicit_addresses) if explicit_addresses is not None
                        else explicit_speech_addressees(text, self.members))
        data['floor_provenance'] = dict(floor_provenance or {})
        data['floor_response'] = dict(floor_response or {})
        if addressed_to:
            data["addressed_to"] = addressed_to
        turn_for = sorted({
            str(name).casefold() for name in (conversation_turn_for or ())
            if str(name).strip()})
        if turn_for:
            # Conversational topology is distinct from a linguistic vocative
            # and never implies privacy, urgency, or an obligation to answer.
            data["conversation_turn_for"] = turn_for
        if social_depth > 0:
            data["social_depth"] = int(social_depth)
        with self._event_condition:
            floor = self._live_social_floor()
            if floor_claim_id:
                claimed_origin_seq = max(
                    0, int(social_origin_seq or social_parent_seq or 0))
                if (not floor
                        or str(floor.get("claim_id") or "")
                        != str(floor_claim_id)
                        or str(floor.get("owner") or "") != str(member)
                        or int(floor.get("source_seq") or 0)
                        != claimed_origin_seq
                        or int(floor.get("speech_revision_seq") or 0)
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
            data['utterance_id'] = f'{self.id}:{self._seq + 1}'
            if (floor_provenance or {}).get('model_id') == 'human':
                self._floor_priority = set(addressed_to)
                self._floor_priority_at = time.time()
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
                "social_thread_id": thread_id,
                "addressed_to": addressed_to,
                "conversation_turn_for": turn_for}

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

    def reach_arm(self, member: str, target: str = '', *, poke=False, release=False):
        """Choose a bounded free-arm intent; a renderer solves the final contact.

        A poke is a visual attempt, not a claim of object manipulation or touch.
        """
        m = self.members.get(member)
        if m is None:
            return {'error': f'{member} is not here'}
        if release:
            m.support_pose.pop('arm_action', None)
            self.emit(member, 'arm_action', {'arm_action': {}})
            return {'ok': True, 'released': True}
        variant = m.support_pose.get('variant', '')
        if m.posture != 'lying' or variant not in ('elbow_left', 'elbow_right'):
            return {'error': 'choose an elbow-supported bed pose to use the free arm'}
        sign = 1 if variant == 'elbow_left' else -1
        offset = [sign * .25, .3, .38]
        if target:
            obj = self.objects.get(target)
            if obj is None:
                return {'error': 'reach target is not in this room'}
            dx, dz = obj.position_m[0]-m.position_m[0], -(obj.position_m[1]-m.position_m[1])
            yaw = math.radians(m.heading_deg)
            x, z = math.cos(yaw)*dx-math.sin(yaw)*dz, math.sin(yaw)*dx+math.cos(yaw)*dz
            if math.hypot(x, z-.4) > .75:
                return {'error': 'target is beyond the free arm; move closer first'}
            if x*sign < 0:
                return {'error': 'target is behind the resting body; turn or change sides first'}
            from room.furniture_rest import base_height
            try:
                measured = rest_profile(obj)
                target_y = base_height(self, obj) + obj.size_m * (measured['surface'] if measured else .25)
            except ValueError as exc:
                return {'error': str(exc)}
            above_surface = target_y-m.support_pose.get('surface_y_m', 0)
            if not -.05 <= above_surface <= .65:
                return {'error': 'target height is outside the resting arm workspace'}
            offset = [x, max(.018, above_surface), z]
        duration = 1.4 if poke else 3.0
        intent = {'kind': 'poke' if poke else 'reach', 'target': target,
                  'target_offset_m': offset, 'started_at': time.time(), 'duration_s': duration}
        m.support_pose['arm_action'] = intent
        self.emit(member, 'arm_action', {'arm_action': intent, 'contact_confirmed': False})
        return {'ok': True, 'arm_action': intent, 'contact_confirmed': False}

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
        seated = name.startswith("seated_")
        if seated and not m.posture.startswith("sitting"):
            return {"error": "sit before choosing a seated motion"}
        if not seated and m.posture != "standing":
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

    def revise_object_physics(self, member: str, oid: str, *,
                              expected_revision: int, kind: str,
                              traits: dict, recipe: dict) -> dict:
        """Owner-authored recipe revision with optimistic concurrency."""
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        obj = self.objects.get(str(oid or ""))
        if obj is None:
            return {"error": f"no object '{oid}'"}
        owner = str(obj.owner or self.owner or "")
        if not owner or owner.casefold() != member.casefold():
            return {"error": "only this object or room's owner can revise it"}
        if int(expected_revision) != int(obj.physics_revision):
            return {"error": "physics revision changed",
                    "revision": int(obj.physics_revision)}
        try:
            clean_kind, clean_traits, clean_recipe = validate_object_physics(
                kind, traits, recipe)
        except HouseholdPhysicsError as error:
            return {"error": str(error)}
        prior = {"revision": obj.physics_revision, "kind": obj.physics_kind,
                 "traits": dict(obj.physics_traits),
                 "recipe": dict(obj.physics_recipe),
                 "recipe_hash": canonical_hash(obj.physics_recipe)}
        obj.physics_kind = clean_kind
        obj.physics_traits = clean_traits
        obj.physics_recipe = clean_recipe
        obj.physics_revision += 1
        obj.physics_history.append({"t": time.time(), "by": member,
                                    **prior})
        obj.physics_history = obj.physics_history[-40:]
        self.emit(member, "object_physics_revised", {
            "object": obj.id, "revision": obj.physics_revision,
            "kind": obj.physics_kind,
        })
        self.physics.record_resolution(
            member, "make", target=obj.id, status="applied",
            effect_count=1, source_action="revise_object_physics")
        return {"ok": True, "object": obj.id,
                "physics": obj.snapshot()["physics"]}

    def _apply_object_effects(self, obj: RoomObject, effects: list) -> int:
        """Validate every effect, then commit the complete object mutation."""
        prepared = []
        for effect in effects:
            kind = str((effect or {}).get("effect") or "")
            if kind == "noop":
                prepared.append(("noop", None, None))
                continue
            if kind != "set_scalar":
                raise HouseholdPhysicsError(
                    f"unsupported object effect '{kind}'")
            field = str(effect.get("field") or "")
            if field not in {"power", "temperature_c"}:
                raise HouseholdPhysicsError(f"unsupported scalar '{field}'")
            value = float(effect.get("value"))
            if not math.isfinite(value):
                raise HouseholdPhysicsError("scalar value must be finite")
            if field == "power":
                value = max(0.0, min(1.0, value))
            elif not -100.0 <= value <= 300.0:
                raise HouseholdPhysicsError("temperature is outside its bound")
            prepared.append(("set_scalar", field, value))
        changed = 0
        for kind, field, value in prepared:
            if kind == "set_scalar" and float(getattr(obj, field)) != value:
                setattr(obj, field, value)
                changed += 1
        return changed

    def use_object(self, member: str, oid: str, mode: str) -> dict:
        """Resolve one composable, reachable object recipe atomically."""
        from room.gardening import room_garden
        garden = room_garden(self)
        if garden and oid in self.objects and self.objects[oid].capability == 'garden':
            return garden.use(member, oid, mode)
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        obj = self.objects.get(str(oid or ""))
        if obj is None:
            return {"error": f"no object '{oid}'"}
        if obj.capability != "light":
            if not obj.physics_recipe:
                return {"error": f"{obj.name} has no use recipe"}
        if obj.owner and obj.owner.casefold() != member.casefold():
            return {"error": f"{obj.name} belongs to {obj.owner}"}
        if not self.near(member, obj.id):
            return {"error": f"{obj.name} is out of reach"}
        # Persisted pre-v0 lights acquire the same explicit seed recipe on
        # first use; this is a compatibility migration, not a new behavior.
        if obj.capability == "light" and not obj.physics_recipe:
            physics = default_light_physics()
            obj.physics_kind = physics["kind"]
            obj.physics_revision = physics["revision"]
            obj.physics_traits = physics["traits"]
            obj.physics_recipe = physics["recipe"]
        mode = str(mode or "").strip().lower()
        effects = obj.physics_recipe.get(mode)
        if not effects:
            self.physics.record_resolution(
                member, "use", target=obj.id, status="blocked",
                source_action="use", reason=f"unknown mode {mode}")
            return {"error": f"{obj.name} has no '{mode}' use"}
        try:
            changed = self._apply_object_effects(obj, effects)
        except (TypeError, ValueError, HouseholdPhysicsError) as error:
            self.physics.record_resolution(
                member, "use", target=obj.id, status="failed",
                source_action="use", reason=str(error))
            return {"error": str(error)}
        self.physics.record_resolution(
            member, "use", target=obj.id,
            status="applied" if changed else "noop", effect_count=changed,
            source_action="use")
        if not changed:
            if obj.capability == "light":
                power = float(obj.power)
                return {"ok": True, "unchanged": True, "object": obj.id,
                        "power": power}
            return {"ok": True, "unchanged": True, "object": obj.id,
                    "mode": mode}
        if obj.capability == "light":
            power = float(obj.power)
            self.emit(member, "light", {
                "object": obj.id, "power": power, "on": power > 0.0,
                "physics_revision": obj.physics_revision})
            return {"ok": True, "object": obj.id, "power": power}
        self.emit(member, "object_used", {
            "object": obj.id, "mode": mode, "effect_count": changed,
            "physics_revision": obj.physics_revision})
        return {"ok": True, "object": obj.id, "mode": mode,
                "effect_count": changed}

    def set_light(self, member: str, oid: str, on: bool):
        """Compatibility motor routed through the typed use resolver."""
        obj = self.objects.get(str(oid or ""))
        if obj is not None and obj.capability != "light":
            return {"error": f"{obj.name} is not a switchable light"}
        return self.use_object(member, oid, "on" if on else "off")

    def rest(self, member: str, oid: str, variant: str = '', *, approach=True):
        """Choose a surface, approach through normal navigation, then settle."""
        self._sync_motions()
        body, obj = self.members.get(member), self.objects.get(oid)
        if body is None or obj is None:
            return {'error': 'member or seating surface is not in this room'}
        measured = rest_profile(obj)
        bed = bool(measured and measured['kind'] == 'bed')
        if obj.capability != 'sitting' and not bed:
            return {'error': f'{obj.name} is not a seating surface'}
        variant = variant or ('sit_edge_left' if bed else 'seat')
        if variant not in (BED_POSES if bed else ('seat',)):
            return {'error': 'pose is not available on this surface', 'choices': list(BED_POSES if bed else ('seat',))}
        if self.near(member, oid):
            return self.lie_down(member, oid, variant) if bed else self.sit(member, oid)
        if not approach:
            return {'error': f'{obj.name} could not be reached; choose a clear approach'}
        dx, dy = body.position_m[0]-obj.position_m[0], body.position_m[1]-obj.position_m[1]
        distance = math.hypot(dx,dy)
        reach = self._footprint_r(obj) + REACH_M*.6
        destination = [obj.position_m[0]+dx/distance*reach, obj.position_m[1]+dy/distance*reach] if distance > reach else list(body.position_m)
        result = self.walk(member, destination)
        if result.get('error') or result.get('blocked_by'):
            return {**result, 'error': result.get('error') or 'The approach is blocked; choose a clear route to the surface'}
        if not body.movement:
            return {'error': f'{obj.name} is not reachable from this level'}
        intent = {'object': oid, 'variant': variant}
        body.movement['rest_on_arrival'] = intent
        result['motion']['rest_on_arrival'] = intent
        return {**result, 'rest_pending': intent}

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
            measured = rest_profile(obj)
            if measured and measured['kind'] == 'bed':
                return self.lie_down(member, oid, 'sit_edge_left')
            if getattr(obj, "capability", None) != "sitting":
                return {"error": f"{obj.name} doesn't afford sitting"}
            if not self.near(member, oid):
                return {"error": f"{obj.name} is out of reach"}
            # SEAT SLOTS (20260720): seats have WIDTH. Slots spread
            # along the width axis (right = (cos h, sin h)), center
            # first; each holds one body. A couch seats the
            # household abreast instead of hosting a wormhole.
            h = math.radians(float(getattr(obj, "rot_deg", 0.0)))
            seat_width = obj.size_m * measured['width'] if measured else obj.size_m
            n = max(1, int(seat_width / 0.7))
            base = [obj.position_m[0] - math.sin(h) * 0.28,
                    obj.position_m[1] + math.cos(h) * 0.28]
            offs = sorted(((i - (n - 1) / 2.0) * 0.6
                           for i in range(n)), key=abs)
            spot = None
            for off in offs:
                cand = [base[0] + math.cos(h) * off,
                        base[1] + math.sin(h) * off]
                if measured:
                    try:
                        cand = rest_support(self, obj, offset=off)['position_m']
                    except ValueError as exc:
                        return {'error': str(exc)}
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
            try:
                contact = rest_support(self, obj, offset=off)
            except ValueError as exc:
                return {"error": str(exc)}
            if contact:
                spot = contact['position_m']
            self._interrupt_motion(member, "sit")
            m.support_pose = contact or {'object': oid, 'variant': 'seat'}
            m.position_m = self._clamp_inside(spot)
            m.heading_deg = contact['heading_deg'] if contact else float(getattr(obj, "rot_deg", 0.0)) % 360.0
            m.posture = "sitting"
            m.posture_since = time.time()
            self.emit(member, "sit", {"object": obj.name,
                                      "position_m": m.position_m,
                                      "heading_deg": m.heading_deg,
                                      "support_pose": m.support_pose,
                                      "posture": m.posture})
            return {"ok": True, "on": obj.name}
        self._interrupt_motion(member, "sit")
        m.support_pose = {}
        m.posture = "sitting_floor"
        m.posture_since = time.time()
        self.emit(member, "sit", {"posture": m.posture,
                                  "position_m": m.position_m})
        return {"ok": True, "on": "floor"}

    def lie_down(self, member: str, oid: str = None, variant: str = 'back'):
        """Choose a resting posture on the ground at the current location."""
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        if variant not in BED_POSES:
            return {'error': 'unknown resting pose', 'choices': list(BED_POSES)}
        if oid:
            obj = self.objects.get(oid)
            p = rest_profile(obj) if obj else None
            if not p or p['kind'] != 'bed':
                return {'error': 'choose a bed with measured support geometry'}
            if not self.near(member, oid):
                return {'error': f'{obj.name} is out of reach'}
            if any(n != member and other.posture != 'standing' and other.support_pose.get('object') == oid for n, other in self.members.items()):
                return {'error': f'{obj.name} is occupied'}
            try:
                contact = rest_support(self, obj, variant)
            except ValueError as exc:
                return {'error': str(exc)}
            self._interrupt_motion(member, 'lie_down')
            m.support_pose = contact
            m.position_m = list(contact['position_m'])
            m.heading_deg = contact['heading_deg']
            m.posture = 'sitting' if variant.startswith('sit_') else 'lying'
            m.posture_since = time.time()
            self.emit(member, 'lie_down', {'posture': m.posture, 'position_m': m.position_m,
                      'heading_deg': m.heading_deg, 'support_pose': contact, 'object': obj.name})
            return {'ok': True, 'on': obj.name, 'variant': variant}
        if m.posture == "lying" and m.support_pose.get('variant', 'back') == variant and not m.support_pose.get('object'):
            return {"ok": True, "unchanged": True}
        if m.posture == "sitting":
            return {"error": "stand clear of the seat before lying on the ground"}
        self._interrupt_motion(member, "lie_down")
        m.support_pose = {'variant': variant}
        m.posture = "lying"
        m.posture_since = time.time()
        self.emit(member, "lie_down", {"posture": m.posture,
                                      "support_pose": m.support_pose,
                                      "position_m": m.position_m})
        return {"ok": True, "on": "ground"}

    def stand(self, member: str):
        m = self.members.get(member)
        if m is None:
            return {"error": f"{member} is not here"}
        if m.movement.get('rest_on_arrival'):
            self._interrupt_motion(member, 'cancelled rest')
        if m.posture == "standing":
            return {"ok": True, "unchanged": True}
        # step off whatever you occupied -- the landing law's nudge,
        # so nobody stands INSIDE the chair.
        if m.posture == "sitting" or m.support_pose.get('object'):
            h = math.radians(m.heading_deg)
            m.position_m = self._deconflict(
                [m.position_m[0] - math.sin(h)*.65, m.position_m[1] + math.cos(h)*.65], member)
        m.posture = "standing"
        m.support_pose = {}
        m.posture_since = time.time()
        self.emit(member, "stand", {"posture": m.posture,
                                    "position_m": m.position_m,
                                    "heading_deg": m.heading_deg,
                                    "gesture": m.gesture})
        return {"ok": True}

    def walk(self, member: str, to, heading_deg=None, control=None):
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
            member, dest, arrival_heading, mode="coordinate",
            controlled_speed=({"walk":4.8,"run":8.4}.get(control) if isinstance(control,str) else None))

    def look_at(self, member: str, oid: str) -> dict:
        """Aim the optical mount without silently moving its body."""
        self._sync_motions()
        me = self.members.get(member)
        if me is None:
            return {"error": f"{member} is not here"}
        target = self.members.get(oid) or self.objects.get(oid)
        if target is None:
            return {"error": f"no object or member '{oid}' in {self.id}"}
        me.gaze_target = oid
        me.gaze_yaw_deg, me.gaze_pitch_deg = self._aim_gaze(me, target)
        relative = me.gaze_yaw_deg
        self.emit(member, "gaze", {"toward": oid,
                                    "gaze_yaw_deg": me.gaze_yaw_deg,
                                    "gaze_pitch_deg": me.gaze_pitch_deg,
                                    "eyes": isinstance(target, Member)})
        return {"ok": True, "toward": oid,
                "optical_pose": me.optical_pose(),
                "fully_centered": abs(relative) <= 85.0}

    def look_away(self, member: str) -> dict:
        """Release the gaze target; eyes return to the body's forward."""
        self._sync_motions()
        me = self.members.get(member)
        if me is None:
            return {"error": f"{member} is not here"}
        was = me.gaze_target
        me.gaze_target = ""
        me.gaze_yaw_deg = 0.0
        me.gaze_pitch_deg = 0.0
        self.emit(member, "gaze", {"toward": "", "released": was,
                                    "gaze_yaw_deg": 0.0,
                                    "gaze_pitch_deg": 0.0})
        return {"ok": True, "released": was,
                "optical_pose": me.optical_pose()}

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
        # body faces the target; eyes keep it (tracking) at eye height
        me.gaze_target = oid
        me.gaze_yaw_deg, me.gaze_pitch_deg = self._aim_gaze(me, target)
        self.emit(member, "turn", {"toward": oid,
                                    "heading_deg": me.heading_deg,
                                    "gaze_yaw_deg": me.gaze_yaw_deg,
                                    "gaze_pitch_deg": me.gaze_pitch_deg})
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
        # Furniture edits move the support, not a cached world-height guess.
        for mem in self.members.values():
            attached = mem.support_pose
            oid = attached.get('object') if mem.posture != 'standing' else None
            if not oid:
                continue
            obj = self.objects.get(oid)
            if obj is None:
                mem.support_pose = {}
                mem.posture = 'standing'
                mem.posture_since = time.time()
                continue
            try:
                updated = rest_support(self, obj, attached.get('variant','seat'), attached.get('offset_m',0))
            except ValueError:
                updated = None
            if updated:
                intent = attached.get('arm_action', {})
                if intent and time.time() < intent.get('started_at', 0)+intent.get('duration_s', 0):
                    updated['arm_action'] = intent
                mem.support_pose = updated
                mem.position_m = list(updated['position_m'])
                mem.heading_deg = updated['heading_deg']
        from room.gardening import room_garden
        garden = room_garden(self)
        garden_state = garden.snapshot() if garden else None
        self._garden_descriptions = {bed['id']:bed['description'] for bed in (garden_state or {}).get('beds', [])}
        latest_continuous = {}
        for entry in self.continuous_afferents:
            if entry.get("anchor_member") in self.members:
                latest_continuous[entry.get("modality")] = {
                    "revision": entry.get("revision"),
                    "anchor_member": entry.get("anchor_member"),
                    "received_at": entry.get("received_at"),
                    "content_free": True,
                }
        return {"contract_version": CONTRACT_VERSION,
                "id": self.id, "name": self.name,
                "owner": self.owner,
                "shape": self.shape, "radius_m": self.radius_m,
                "door_interaction_m": DOOR_INTERACTION_M,
                "movement_boundary": self.movement_boundary,
                "scene": self.scene,
                "destination": getattr(self, 'destination', None),
                **({'garden': garden_state} if garden_state else {}),
                "walkable": [[list(p) for p in poly]
                             for poly in self.walkable],
                "arrival_m": (list(self.arrival_m)
                              if self.arrival_m is not None else None),
                "arrival_heading_deg": self.arrival_heading_deg,
                "description": self.description,
                "members": {m: mem.snapshot()
                            for m, mem in self.members.items()},
                "objects": {o.id: self.object_snapshot(o, observer)
                            for o in self.objects.values()},
                "places": {p.id: p.snapshot()
                           for p in self.places.values()},
                "life_afferents": {
                    modality: {
                        "condition": dict(state.get("condition") or {}),
                        "updated": state.get("updated"),
                    }
                    for modality, state in self.life_afferents.items()
                },
                "continuous_afferents": latest_continuous,
                "household_physics": self.physics.public_snapshot(observer),
                "last_seq": self._seq}
