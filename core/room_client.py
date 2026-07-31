"""core/room_client.py — thin tenant-side client for the room host API.
Pure I/O, zero interpretation: raw snapshots and raw events in, actions
out. All salience/meaning happens in core/perception.py against the
persona's own substrate — this file must never grow opinions.

Tracks last_seq so events() returns only what's new since the persona
last looked around. Failures degrade soft: the room going down must
never break a turn (same law as harvest)."""
import json
import urllib.request
import urllib.error


class RoomClient:
    def __init__(self, base_url: str, member: str, timeout_s: float = 3.0):
        self.base = base_url.rstrip("/")
        self.member = member
        self.timeout = timeout_s
        self.room_id = None
        self.last_seq = 0
        self.last_vision_revision = 0

    def _req(self, path: str, body: dict = None, timeout_s: float = None):
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method="POST" if body is not None else "GET",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(
                    req, timeout=(self.timeout if timeout_s is None
                                  else float(timeout_s))) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                return {"error": f"http {e.code}"}
        except Exception as e:
            return {"error": f"room unreachable: {e.__class__.__name__}"}

    # ── presence ─────────────────────────────────────────────────
    def ensure_joined(self, room: str) -> dict:
        """Join, or recover position if already somewhere (409)."""
        r = self._req("/api/join", {"member": self.member, "room": room})
        if r.get("ok"):
            self.room_id = room
            return r
        w = self._req("/api/world")
        here = (w.get("where") or {}).get(self.member)
        if here:
            self.room_id = here
            return {"ok": True, "recovered": True, "room_id": here}
        return r

    def travel(self, to: str) -> dict:
        r = self._req("/api/travel", {"member": self.member, "to": to})
        if r.get("ok"):
            self.room_id = to
            self.last_seq = 0
        return r

    # ── perception feed (raw; the filter interprets) ─────────────
    def snapshot(self) -> dict:
        if not self.room_id:
            return {}
        r = self._req(f"/api/rooms/{self.room_id}")
        return r if "error" not in r else {}

    def local_weather(self) -> dict:
        """Read the host's coordinate-free local-weather status."""
        return self._req("/weather-sync")

    def fresh_events(self) -> list:
        if not self.room_id:
            return []
        r = self._req(f"/api/rooms/{self.room_id}/events"
                      f"?since={self.last_seq}")
        evs = r.get("events", [])
        if evs:
            self.last_seq = max(e["seq"] for e in evs)
        return evs

    def wait_for_revision(self, since: int, timeout_s: float = 25.0) -> dict:
        """Wait for shared state to advance without consuming event history.

        Surface packets are included only so face/posture revisions can cross
        the threshold. The caller uses the sequence, not packet content.
        """
        if not self.room_id:
            return {"last_seq": int(since), "changed": False}
        bounded = max(1.0, min(25.0, float(timeout_s)))
        r = self._req(
            f"/api/rooms/{self.room_id}/events/wait"
            f"?since={int(since)}&timeout={bounded}&surface=1",
            timeout_s=bounded + 2.0)
        last_seq = int(r.get("last_seq", since) or since)
        return {
            "last_seq": last_seq,
            "changed": last_seq > int(since),
            "room_id": self.room_id,
            "error": r.get("error"),
        }

    def doors(self) -> list:
        """Adjacency from the current room (cached; world topology is
        stable in v0)."""
        if not self.room_id:
            return []
        if not hasattr(self, "_adj"):
            w = self._req("/api/world")
            self._adj = w.get("adjacency", {}) if "error" not in w else {}
        return list(self._adj.get(self.room_id, []))

    # ── actions ──────────────────────────────────────────────────
    def act(self, action: str, obj: str = None, text: str = None,
            force_n: float = 5.0) -> dict:
        body = {"member": self.member, "action": action,
                "object": obj, "text": text, "force_n": force_n}
        # pydantic v2: explicit null fails `str = None` fields; omit instead
        return self._req("/api/act",
                         {k: v for k, v in body.items() if v is not None})

    def move(self, obj):
        return self.act("move_to", obj)

    def contact(self, obj, force_n=5.0):
        return self.act("contact", obj, force_n=force_n)

    def write(self, obj, text):
        return self.act("write", obj, text=text)

    def read(self, obj):
        return self.act("read", obj)

    def say(self, text, conversation_id=None, social_depth=0):
        body = {"member": self.member, "action": "say", "text": text}
        if conversation_id:
            body["conversation_id"] = conversation_id
        if social_depth:
            body["social_depth"] = int(social_depth)
        return self._req("/api/act", body)

    def express(self, face: dict):
        """Publish the visible face (body SURFACE, never insides --
        the caller's distiller already chose what shows)."""
        return self._req("/api/act", {"member": self.member,
                                      "action": "express",
                                      "face": face or {}})

    def sit(self, obj=None):
        """Sit on an object (needs the 'sitting' affordance and
        reach) or, with no object, on the floor where you stand."""
        if obj:
            return self.act("sit", obj)
        return self._req("/api/act", {"member": self.member,
                                      "action": "sit"})

    def stand(self):
        return self._req("/api/act", {"member": self.member,
                                      "action": "stand"})

    def gesture(self, name: str):
        return self.act("gesture", name)

    def release_gesture(self):
        return self._req("/api/act", {"member": self.member,
                                      "action": "release_gesture"})

    def body_motion(self, name: str):
        return self.act("body_motion", name)

    def light_on(self, obj: str):
        return self.act("light_on", obj)

    def light_off(self, obj: str):
        return self.act("light_off", obj)

    def walk(self, x: float, y: float, heading_deg=None):
        """Walk anywhere: raw meters, center-origin. The room is a
        place, not a menu of destinations."""
        body = {"member": self.member, "action": "walk",
                "to": [float(x), float(y)]}
        if heading_deg is not None:
            body["heading_deg"] = float(heading_deg)
        return self._req("/api/act", body)

    def look_at(self, target: str):
        return self.act("look_at", target)

    def turn_toward(self, target: str):
        return self.act("turn_toward", target)

    def inspect(self, target: str):
        return self.act("inspect", target)
    def fresh_vision_frame(self) -> dict:
        """Return this body's newest private optical frame once."""
        if not self.room_id:
            return {}
        result = self._req(
            f"/api/rooms/{self.room_id}/vision/{self.member}"
            f"?since={self.last_vision_revision}")
        frame = result.get("frame") or {}
        return frame

    def acknowledge_vision_frame(self, revision: int) -> None:
        self.last_vision_revision = max(self.last_vision_revision,
                                        int(revision or 0))
