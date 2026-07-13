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
import time
from collections import deque

REACH_M = 1.2          # arm's length: capability + contact gate
WALL_MARGIN_M = 0.3    # radial clamp: bodies stay off the lattice
CONTRACT_VERSION = "room-1"   # circular rooms, center-origin (yurts)


class RoomObject:
    def __init__(self, oid: str, name: str, position_m,
                 mass_kg: float = 1.0, temperature_c: float = 21.0,
                 affordances: dict = None, capability: str = None,
                 owner: str = None, description: str = "",
                 texture: str = "neutral",
                 kind: str = None, size_m: float = 0.6,
                 rot_deg: float = 0.0, y_off_m: float = 0.0):
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
        self.members = {}                       # name -> [x, y] position
        self.events = deque(maxlen=500)         # the event bus, v0
        self._seq = 0

    # ── event bus ────────────────────────────────────────────────
    def emit(self, member: str, kind: str, data: dict = None):
        self._seq += 1
        self.events.append({"seq": self._seq,
                            "ts": time.strftime("%H:%M:%S"),
                            "t": time.time(),
                            "member": member, "kind": kind,
                            "data": data or {}})

    def events_since(self, since: int) -> list:
        return [e for e in self.events if e["seq"] > since]

    # ── membership (one body, one room — enforced by the host) ──
    def join(self, member: str, at=None):
        # the door: one, south rim, just inside — yurts agree.
        door = [0.0, -(self.radius_m - 0.5)]
        self.members[member] = self._clamp_inside(list(at or door))
        self.emit(member, "arrive", {"position_m": self.members[member]})

    def leave(self, member: str):
        self.members.pop(member, None)
        self.emit(member, "depart", {})

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

    def near(self, member: str, oid: str) -> bool:
        if member not in self.members or oid not in self.objects:
            return False
        return self._dist(self.members[member],
                          self.objects[oid].position_m) <= REACH_M

    def move_to(self, member: str, oid: str) -> dict:
        """Walk to an object. Movement is an event other members
        perceive — presence has a body, always."""
        if member not in self.members:
            return {"error": f"{member} is not in {self.id}"}
        if oid in self.members and oid != member:
            # walking to a PERSON: land within reach, not on their tail.
            # Presence is social — the event says who you came to.
            frm = list(self.members[member])
            tgt = self.members[oid]
            self.members[member] = self._clamp_inside(
                [tgt[0], tgt[1] - 0.8])
            self.emit(member, "move", {"from_m": frm,
                                       "to_m": self.members[member],
                                       "toward": oid,
                                       "toward_member": oid})
            return {"ok": True, "at": oid,
                    "position_m": self.members[member]}
        if oid not in self.objects:
            return {"error": f"no object or member '{oid}' in {self.id}"}
        obj = self.objects[oid]
        frm = list(self.members[member])
        self.members[member] = self._clamp_inside(
            [obj.position_m[0], obj.position_m[1] - 0.5])
        self.emit(member, "move", {"from_m": frm,
                                   "to_m": self.members[member],
                                   "toward": obj.name})
        return {"ok": True, "at": obj.name,
                "position_m": self.members[member]}

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
                "members": {m: p for m, p in self.members.items()},
                "objects": {o.id: o.snapshot()
                            for o in self.objects.values()},
                "last_seq": self._seq}
