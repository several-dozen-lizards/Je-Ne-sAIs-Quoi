"""room/host.py — the room host process (REQUIREMENTS par 6, v0).
Own process, descendant of the v1 Nexus-server pattern generalized to N
room instances. Personas are separate processes that act here via API;
if the host dies, the people survive and the places respawn.

One body, one room: enforced HERE, at the world's door. A member exists
in at most one room; travel is the only way between them, and it emits
departure/arrival percepts on both sides — walking is an event.

Geography as permissions, wired live:
  private_writing desk (owner's den) -> appends to that persona's
      my_life/journal.md, which the turn-loop's recent_diary block
      already reads. The desk writes; tomorrow's turn re-reads it.
  writing desk (commons) -> page object ON the desk; reading requires
      walking to it. Who can read = who can walk there.

Run:  python room/host.py [--port 8720]"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Windows often lacks the wasm mimetype; without it the Godot web
# export is served as octet-stream and the browser refuses streaming
# compilation. Register it before any static mount exists.
import mimetypes
mimetypes.add_type("application/wasm", ".wasm")

from room.layout import build_world, build_persona_den
from room.state import CONTRACT_VERSION
from shell.persona_media import load_persona_avatar
from shell.ui_background import (delete_nexus_background,
                                 load_conversation_background,
                                 load_nexus_background,
                                 save_nexus_background)
from shell.ui_themes import resolve_nexus_theme, resolve_theme, save_nexus_theme

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.environ.get(
    "JNSQ_ROOM_STATE",                      # test isolation forever
    os.path.join(REPO, "room", "room_world.json"))


def _named_theme_value(mapping: dict, *names):
    """Case-insensitive lookup for display names and stable ids."""
    folded = {str(key).casefold(): value for key, value in
              (mapping or {}).items()}
    for name in names:
        if name is not None and str(name).casefold() in folded:
            return folded[str(name).casefold()]
    return None

# ── THE WORLD LOCK (audit finding 2, 2026-07-05) ──
# One world, one writer at a time. Three live actors + heartbeats +
# tropism all mutate concurrently through FastAPI's threadpool; this
# asyncio.Lock in the middleware serializes every request — mutations
# AND reads — so no actor ever sees a half-moved body or races the
# persist. asyncio (not threading): a threading.Lock held across
# `await call_next` would block the event loop and deadlock.
import asyncio
WORLD_LOCK = asyncio.Lock()


def _obj_record(o, custom: bool) -> dict:
    """Full object record for the save: the world remembers its
    furniture entirely now, not just where it stands."""
    return {"position_m": list(o.position_m), "name": o.name,
            "kind": o.kind, "size_m": o.size_m,
            "rot_deg": getattr(o, "rot_deg", 0.0),
            "y_off_m": getattr(o, "y_off_m", 0.0),
            "description": o.description, "texture": o.texture,
            "capability": o.capability, "owner": o.owner,
            "affordances": dict(o.affordances),
            "temperature_c": o.temperature_c, "mass_kg": o.mass_kg,
            "custom": custom}


def _save_world(app):
    """Positions, presence, events, pages -> disk. The world survives
    its own host now; a bounce is no longer an amnesia event."""
    import json
    seed = getattr(app.state, "seed_ids", {})
    d = {"where": dict(app.state.where),
         "rooms": {rid: {"members": {m: list(p) for m, p
                                     in r.members.items()},
                         "seq": r._seq,
                         "events": list(r.events)[-200:],
                         "objects": {oid: _obj_record(
                                         o, oid not in
                                         seed.get(rid, set()))
                                     for oid, o in r.objects.items()},
                         "pages": {oid: o.pages for oid, o
                                   in r.objects.items() if o.pages}}
                   for rid, r in app.state.rooms.items()}}
    tmp = STATE_FILE + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)   # atomic; unique tmp per process


def _load_world(app):
    """Rebuild the seed world, then re-place everyone where they were."""
    import json
    if not os.path.exists(STATE_FILE):
        return False
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        for rid, saved in d.get("rooms", {}).items():
            room = app.state.rooms.get(rid)
            if not room:
                continue
            room.members = {m: room._clamp_inside(list(p)) for m, p
                            in saved.get("members", {}).items()}
            # clamp-on-restore: legacy saves (rect era) may hold
            # positions outside the yurt wall; the door law applies
            # to history too.
            room._seq = saved.get("seq", 0)
            room.events.clear()
            room.events.extend(saved.get("events", []))
            # furniture stays where it was put — and now, WHAT it is:
            # full records restore seed objects' edits and reconstruct
            # runtime-created (custom) ones. Legacy saves (bare [x,y]
            # lists) still restore position only. The layout seed is a
            # founding arrangement, not a nightly reset.
            from room.state import RoomObject
            for oid, rec in saved.get("objects", {}).items():
                if isinstance(rec, list):            # legacy format
                    if oid in room.objects and len(rec) == 2:
                        room.objects[oid].position_m = [float(rec[0]),
                                                        float(rec[1])]
                    continue
                if not isinstance(rec, dict):
                    continue
                pos = rec.get("position_m", [0.0, 0.0])
                if oid in room.objects:
                    o = room.objects[oid]
                    o.position_m = [float(pos[0]), float(pos[1])]
                    for f in ("name", "kind", "size_m", "rot_deg",
                              "y_off_m", "description", "texture"):
                        if rec.get(f) is not None:
                            setattr(o, f, rec[f])
                elif rec.get("custom"):
                    room.objects[oid] = RoomObject(
                        oid, rec.get("name", oid), pos,
                        mass_kg=float(rec.get("mass_kg", 1.0)),
                        temperature_c=float(
                            rec.get("temperature_c", 21.0)),
                        affordances=rec.get("affordances") or {},
                        capability=rec.get("capability"),
                        owner=rec.get("owner"),
                        description=rec.get("description", ""),
                        texture=rec.get("texture", "neutral"),
                        kind=rec.get("kind"),
                        size_m=float(rec.get("size_m", 0.6)),
                        rot_deg=float(rec.get("rot_deg", 0.0)),
                        y_off_m=float(rec.get("y_off_m", 0.0)))
            for oid, pages in saved.get("pages", {}).items():
                if oid in room.objects:
                    room.objects[oid].pages = pages
        app.state.where = dict(d.get("where", {}))
        return True
    except Exception:
        return False


class JoinReq(BaseModel):
    member: str
    room: str


class LeaveReq(BaseModel):
    member: str


class ThemeRequest(BaseModel):
    patch: dict
    reset: bool = False
    replace: bool = False


class ConversationBackgroundRequest(BaseModel):
    data_url: str


class PersonReq(BaseModel):
    display_name: str
    kind: str = "human"          # human | user | ai
    standing: str = "unknown"    # core.people STANDING_RANK keys
    note: str = ""
    update: bool = False         # explicit consent to overwrite


class TravelReq(BaseModel):
    member: str
    to: str


class ActionReq(BaseModel):
    member: str
    action: str            # move_to | contact | say | write | read
    object: str = None
    text: str = None
    force_n: float = 5.0


class ObjectMoveReq(BaseModel):
    position_m: list       # [x, y] meters, center-origin
    by: str = "Re"         # whose hand moved it (the editor is a hand)


class ObjectCreateReq(BaseModel):
    name: str
    oid: str = None        # slugged from name when absent
    kind: str = None       # render hint: which model file
    size_m: float = 0.6
    position_m: list = [0.0, 0.0]
    description: str = ""
    texture: str = "neutral"
    by: str = "Re"


class ObjectUpdateReq(BaseModel):
    name: str = None       # only non-None fields change
    kind: str = None
    size_m: float = None
    rot_deg: float = None  # yaw, degrees
    y_off_m: float = None  # vertical lift, meters (the lever)
    description: str = None
    texture: str = None
    by: str = "Re"


def build_app() -> FastAPI:
    app = FastAPI(title="JNSQ room host", version=CONTRACT_VERSION)
    jnsq_assets = os.path.join(REPO, "assets", "jnsq")
    if os.path.isdir(jnsq_assets):
        app.mount("/assets", StaticFiles(directory=jnsq_assets),
                  name="jnsq-assets")
    world = build_world()
    app.state.rooms = world["rooms"]
    app.state.adjacency = world["adjacency"]
    app.state.where = {}    # member -> room id (one body, one room)
    # who came from the seed: anything else in a save is a runtime
    # creation (the curator's, or someday the household's own)
    app.state.seed_ids = {rid: set(r.objects.keys())
                          for rid, r in app.state.rooms.items()}
    # A persona roster declares a den; world boot closes that declaration
    # into geography. New personas therefore never point at a missing room.
    pdir = os.path.join(REPO, "personas")
    try:
        persona_names = os.listdir(pdir)
    except OSError:
        persona_names = []
    for pid in persona_names:
        roster_path = os.path.join(pdir, pid, "roster.yaml")
        if pid.startswith(("_", ".")) or not os.path.isfile(roster_path):
            continue
        display = pid.replace("_", " ").title()
        declared_room = f"{pid}_den"
        try:
            import yaml
            with open(roster_path, encoding="utf-8") as f:
                roster = yaml.safe_load(f) or {}
                display = roster.get("display_name") or display
                declared_room = (roster.get("room") or {}).get("id") \
                    or declared_room
        except Exception:
            pass
        rid = declared_room
        if rid == f"{pid}_den" and rid not in app.state.rooms:
            den = build_persona_den(pid, display)
            app.state.rooms[rid] = den
            app.state.adjacency[rid] = ["nexus"]
            app.state.adjacency.setdefault("nexus", []).append(rid)
            app.state.seed_ids[rid] = set(den.objects)
    if _load_world(app):
        print("[room host] world state restored from disk")

    def _room_of(member: str):
        rid = app.state.where.get(member)
        return app.state.rooms.get(rid) if rid else None

    @app.middleware("http")
    async def _persist_after_mutation(request, call_next):
        # /3d (the web-exported Godot client; MBs of WASM) and
        # /tuning are read-only file serves. They must never queue
        # behind the world lock -- the lock serializes world
        # mutations, not downloads -- and never trigger a persist.
        p = request.url.path
        if p.startswith("/3d") or p.startswith("/models") \
                or p.startswith("/avatars") or p == "/tuning":
            return await call_next(request)
        # Long-poll listeners wait on Room._event_condition. They must not
        # hold the global world lock or they would prevent the mutation that
        # advances the very sequence they are waiting for.
        if p.endswith("/events/wait"):
            return await call_next(request)
        async with WORLD_LOCK:
            resp = await call_next(request)
            if request.method in ("POST", "DELETE"):
                _save_world(app)
        return resp

    @app.get("/", response_class=HTMLResponse)
    def viewer():
        import json
        from shell.local_identity import load_local_identity
        with open(os.path.join(REPO, "room", "viewer.html"),
                  encoding="utf-8") as f:
            return f.read().replace("/*CONFIG*/", json.dumps(
                load_local_identity(REPO)))

    def _nexus_background_for(result: dict):
        nexus_tokens = ((result.get("layers") or {}).get("nexus") or {}).get(
            "tokens") or {}
        nexus_owns_image = nexus_tokens.get("background") == "image"
        media = load_nexus_background(REPO) if nexus_owns_image else None
        source = "nexus" if media else "household"
        media = media or load_conversation_background(REPO)
        return media, source

    def _with_nexus_background(result: dict):
        media, source = _nexus_background_for(result)
        result["conversation_background"] = ({
            "url": "/api/ui/conversation-background",
            "revision": media["revision"],
            "source": source,
        } if media else None)
        return result

    @app.get("/api/ui/theme")
    def nexus_ui_theme():
        return _with_nexus_background(resolve_nexus_theme(REPO))

    @app.post("/api/ui/theme")
    def set_nexus_ui_theme(req: ThemeRequest):
        try:
            result = save_nexus_theme(REPO, req.patch, reset=req.reset,
                                      replace=req.replace)
            return _with_nexus_background(result)
        except ValueError as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)})

    @app.get("/api/ui/conversation-background")
    def nexus_ui_background():
        media, _source = _nexus_background_for(resolve_nexus_theme(REPO))
        if not media:
            return JSONResponse(status_code=404,
                                content={"error": "no conversation background"})
        return FileResponse(media["path"], media_type=media["mime"],
                            headers={"X-Content-Type-Options": "nosniff",
                                     "Cache-Control": "no-cache"})

    @app.post("/api/ui/conversation-background")
    def nexus_ui_background_save(req: ConversationBackgroundRequest):
        try:
            media = save_nexus_background(REPO, req.data_url)
            return {"ok": True, "url": "/api/ui/conversation-background",
                    "revision": media["revision"], "source": "nexus"}
        except ValueError as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)})

    @app.delete("/api/ui/conversation-background")
    def nexus_ui_background_delete():
        return {"ok": True, "removed": delete_nexus_background(REPO)}

    @app.get("/api/world")
    def world_view():
        return {"contract_version": CONTRACT_VERSION,
                "rooms": {rid: {"name": r.name,
                                "members": list(r.members.keys()),
                                "objects": list(r.objects.keys())}
                          for rid, r in app.state.rooms.items()},
                "adjacency": app.state.adjacency,
                "where": dict(app.state.where)}

    @app.get("/api/rooms/{rid}")
    def room_state(rid: str):
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        return room.snapshot()

    @app.get("/api/rooms/{rid}/events")
    def room_events(rid: str, since: int = 0):
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        return {"events": room.events_since(since)}

    @app.get("/api/rooms/{rid}/events/wait")
    def room_events_wait(rid: str, since: int = 0,
                         timeout: float = 25.0):
        """Long-poll until this room's event sequence advances.

        Renderers wait on an actual state threshold rather than waking on a
        blind browser timer. The bounded timeout merely renews the connection.
        """
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        events = room.wait_for_events(since, timeout)
        return {"events": events, "last_seq": room._seq}

    @app.get("/api/personas")
    def personas():
        """Who COULD be here: persona dirs on disk (the world's host
        may offer them as bodies; minds arrive separately — a stopped
        persona placed here is a body on stage; ensure_joined recovers
        the position when the mind starts). Leading-underscore names
        are reserved (disposal laws) and never offered. display_name
        read from roster.yaml, read-only, soft-fail to the slug."""
        pdir = os.path.join(REPO, "personas")
        out = []
        try:
            names = sorted(os.listdir(pdir))
        except OSError:
            names = []
        for n in names:
            if n.startswith("_") or n.startswith("."):
                continue
            if not os.path.isdir(os.path.join(pdir, n)):
                continue
            disp = n
            icon = ""
            rpath = os.path.join(pdir, n, "roster.yaml")
            if os.path.exists(rpath):
                try:
                    import yaml
                    with open(rpath, encoding="utf-8") as f:
                        roster = yaml.safe_load(f) or {}
                    disp = roster.get("display_name") or n
                    icon = str(roster.get("icon") or "").strip()
                except Exception:
                    pass          # a broken roster never breaks the list
            avatar = load_persona_avatar(os.path.join(pdir, n))
            tokens = resolve_theme(REPO, n)["tokens"]
            speaker_color = (_named_theme_value(
                tokens.get("speaker_colors"), disp, n)
                or tokens.get("accent2"))
            out.append({"id": n, "display_name": disp,
                        "icon": icon or disp[:1].upper(),
                        "speaker_color": speaker_color,
                        "avatar_url": (f"/api/personas/{n}/avatar?v="
                                       f"{avatar['version']}"
                                       if avatar else "")})
        return {"personas": out}

    @app.get("/api/personas/{pid}/avatar")
    def persona_avatar(pid: str):
        """Serve one validated roster avatar from the room's own origin."""
        personas_root = os.path.realpath(os.path.join(REPO, "personas"))
        persona_dir = os.path.realpath(os.path.join(personas_root, pid))
        try:
            inside = os.path.commonpath([personas_root, persona_dir]) \
                == personas_root
        except ValueError:
            inside = False
        avatar = (load_persona_avatar(persona_dir)
                  if inside and os.path.isdir(persona_dir) else None)
        if not avatar:
            return JSONResponse(status_code=404, content={
                "error": f"persona '{pid}' has no avatar"})
        return FileResponse(avatar["path"], media_type=avatar["mime"])

    @app.get("/api/users")
    def users_list():
        """Human accounts that can be present and speak in the Nexus."""
        from core.users import load_user_avatar
        from shell.local_identity import local_user_directory
        users = []
        household_tokens = resolve_theme(REPO)["tokens"]
        for uid, account in sorted(local_user_directory(REPO).items()):
            display = account.get("display_name") or uid
            username = account.get("username") or uid
            avatar = load_user_avatar(REPO, uid)
            users.append({"id": uid, "display_name": display,
                          "username": username,
                          "icon": str(account.get("icon") or
                                      display[:1].upper()),
                          "speaker_color": (_named_theme_value(
                              household_tokens.get("speaker_colors"),
                              display, uid, username, "User")
                              or household_tokens.get("accent")),
                          "avatar_url": (f"/api/users/{uid}/avatar?v="
                                         f"{avatar['version']}"
                                         if avatar else "")})
        return {"users": users}

    @app.get("/api/users/{uid}/avatar")
    def user_avatar(uid: str):
        """Serve one validated local account avatar from the room origin."""
        from core.users import load_user_avatar
        avatar = load_user_avatar(REPO, uid)
        if not avatar:
            return JSONResponse(status_code=404, content={
                "error": f"user '{uid}' has no avatar"})
        return FileResponse(avatar["path"], media_type=avatar["mime"],
                            headers={"X-Content-Type-Options": "nosniff",
                                     "Cache-Control": "no-cache"})

    @app.get("/api/people")
    def people_list():
        """Profiled humans and outside AIs (people/<slug>/profile.yaml).
        The world's known-entity registry; personas live elsewhere."""
        from core.people import load_people
        ppl = load_people(REPO)
        return {"people": [
            {"id": slug, "display_name": p.get("display_name", slug),
             "kind": p.get("kind", "human"),
             "standing": p.get("standing", "unknown")}
            for slug, p in sorted(ppl.items())]}

    @app.post("/api/people")
    def people_upsert(req: PersonReq):
        """Classify at the door. VALIDATE-FIRST: bad standing/kind ->
        400, nothing written. Create refuses clobber; update requires
        the explicit flag. Profiles are machine-owned flat YAML (keep
        prose in `note`; comments do not survive updates)."""
        from core.people import STANDING_RANK, KINDS
        if req.standing not in STANDING_RANK:
            return JSONResponse(status_code=400, content={
                "error": f"standing must be one of "
                         f"{sorted(STANDING_RANK)}"})
        if req.kind not in KINDS:
            return JSONResponse(status_code=400, content={
                "error": f"kind must be one of {sorted(KINDS)}"})
        disp = req.display_name.strip()
        if not disp:
            return JSONResponse(status_code=400,
                                content={"error": "a name is required"})
        slug = "".join(c if c.isalnum() else "_"
                       for c in disp.lower()).strip("_")
        while "__" in slug:
            slug = slug.replace("__", "_")
        if not slug or slug.startswith("_"):
            return JSONResponse(status_code=400,
                                content={"error": f"bad slug '{slug}'"})
        pdir = os.path.join(REPO, "people", slug)
        path = os.path.join(pdir, "profile.yaml")
        exists = os.path.exists(path)
        if exists and not req.update:
            return JSONResponse(status_code=409, content={
                "error": f"'{slug}' already has a profile — "
                         "edit it instead (update flag)"})
        import yaml
        prof = {}
        if exists:
            try:
                with open(path, encoding="utf-8") as f:
                    prof = yaml.safe_load(f) or {}
            except Exception:
                prof = {}
        prof.update({"display_name": disp, "kind": req.kind,
                     "standing": req.standing})
        if req.note:
            prof["note"] = req.note
        os.makedirs(pdir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(prof, f, allow_unicode=True,
                           sort_keys=False)
        if req.standing == "user":
            # The room's old "user (account)" door now creates the actual
            # account branch too. One action, one human, both world presence
            # and private account truth connected.
            from core.users import upsert_user, list_users
            upsert_user(REPO, username=disp, display_name=disp,
                        pronouns=prof.get("pronouns", ""),
                        update=slug in list_users(REPO))
        return {"ok": True, "id": slug,
                "created": not exists, "standing": req.standing}

    @app.post("/api/join")
    def join(req: JoinReq):
        if req.member in app.state.where:
            return JSONResponse(status_code=409, content={
                "error": f"{req.member} is already in "
                         f"{app.state.where[req.member]} — one body, "
                         "one room; travel instead"})
        room = app.state.rooms.get(req.room)
        if not room and req.room == f"{req.member.lower()}_den":
            roster_path = os.path.join(REPO, "personas",
                                       req.member.lower(), "roster.yaml")
            if os.path.isfile(roster_path):
                display = req.member.replace("_", " ").title()
                try:
                    import yaml
                    with open(roster_path, encoding="utf-8") as f:
                        display = (yaml.safe_load(f) or {}).get(
                            "display_name") or display
                except Exception:
                    pass
                room = build_persona_den(req.member, display)
                app.state.rooms[room.id] = room
                app.state.adjacency[room.id] = ["nexus"]
                app.state.adjacency.setdefault("nexus", []).append(room.id)
                app.state.seed_ids[room.id] = set(room.objects)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{req.room}'"})
        room.join(req.member)
        app.state.where[req.member] = req.room
        return {"ok": True, "room": room.snapshot()}

    @app.post("/api/leave")
    def leave(req: LeaveReq):
        """The door out — join's mirror. Departure is a PERCEPT
        (room.leave emits 'depart'; the others see you go). Works for
        any member: a removed persona's tenant soft-409s on its next
        act until it rejoins — the world never breaks, it just no
        longer contains them."""
        rid = app.state.where.get(req.member)
        if rid is None:
            return JSONResponse(status_code=409, content={
                "error": f"{req.member} is nowhere — nothing to leave"})
        room = app.state.rooms.get(rid)
        if room:
            room.leave(req.member)          # departure percept fires
        del app.state.where[req.member]
        return {"ok": True, "left": rid}

    @app.post("/api/travel")
    def travel(req: TravelReq):
        here = _room_of(req.member)
        if here is None:
            return JSONResponse(status_code=409, content={
                "error": f"{req.member} is nowhere — join a room first"})
        if req.to not in app.state.adjacency.get(here.id, []):
            return JSONResponse(status_code=409, content={
                "error": f"no door from {here.id} to {req.to}"})
        dest = app.state.rooms[req.to]
        here.leave(req.member)              # departure percept, this side
        dest.join(req.member)               # arrival percept, that side
        app.state.where[req.member] = dest.id
        return {"ok": True, "from": here.id, "to": dest.id,
                "room": dest.snapshot()}

    @app.post("/api/act")
    def act(req: ActionReq):
        room = _room_of(req.member)
        if room is None:
            return JSONResponse(status_code=409, content={
                "error": f"{req.member} is nowhere — join a room first"})

        if req.action == "move_to":
            return room.move_to(req.member, req.object)

        if req.action == "contact":
            return room.contact(req.member, req.object, req.force_n)

        if req.action == "say":
            room.emit(req.member, "say", {"text": req.text or ""})
            return {"ok": True}

        if req.action == "write":
            obj = room.objects.get(req.object)
            if obj is None or not room.near(req.member, req.object):
                return {"error": "walk to a desk first"}
            if obj.capability == "private_writing":
                if obj.owner != req.member.lower():
                    return {"error": f"that desk is {obj.owner}'s"}
                path = os.path.join(REPO, "personas", obj.owner,
                                    "my_life", "journal.md")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M')}] "
                            f"{req.text}\n")
                room.emit(req.member, "write", {"object": obj.name,
                                                "private": True})
                return {"ok": True, "wrote_to": "my_life/journal.md",
                        "note": "your turn-loop reads this back to you"}
            if obj.capability == "writing":
                obj.pages.append({"by": req.member,
                                  "ts": time.strftime("%Y-%m-%d %H:%M"),
                                  "text": req.text or ""})
                room.emit(req.member, "write", {"object": obj.name,
                                                "private": False})
                return {"ok": True, "page": len(obj.pages)}
            return {"error": f"{obj.name} is not a writing surface"}

        if req.action == "read":
            obj = room.objects.get(req.object)
            if obj is None or not room.near(req.member, req.object):
                return {"error": "walk to it first"}
            room.emit(req.member, "read", {"object": obj.name})
            return {"ok": True, "pages": obj.pages}

        return JSONResponse(status_code=400,
                            content={"error": f"unknown action "
                                              f"'{req.action}'"})

    @app.post("/api/rooms/{rid}/objects/{oid}/position")
    def object_move(rid: str, oid: str, req: ObjectMoveReq):
        """Rearrange furniture. VALIDATE-FIRST: [x, y] numeric, inside
        the room, or 400 and nothing moves. The move is a percept
        ('rearrange') so every window -- 2D, 3D, log -- sees it; the
        POST middleware persists it, so it survives restarts (the
        layout seed is a starting arrangement, not a nightly reset)."""
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        obj = room.objects.get(oid)
        if obj is None:
            return JSONResponse(status_code=404, content={
                "error": f"no object '{oid}' in {rid}"})
        p = req.position_m
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            return JSONResponse(status_code=400, content={
                "error": "position_m must be [x, y] numbers"})
        if (x * x + y * y) ** 0.5 > room.radius_m:
            return JSONResponse(status_code=400, content={
                "error": f"[{x:.2f}, {y:.2f}] is outside the yurt "
                         f"(r={room.radius_m})"})
        frm = list(obj.position_m)
        obj.position_m = [x, y]
        room.emit(req.by, "rearrange", {"oid": oid, "object": obj.name,
                                        "from_m": frm, "to_m": [x, y]})
        return {"ok": True, "oid": oid, "position_m": [x, y]}

    @app.post("/api/rooms/{rid}/objects")
    def object_create(rid: str, req: ObjectCreateReq):
        """A new thing enters the world. VALIDATE-FIRST: unique oid
        (never underscore-leading -- reserved), inside the yurt, sane
        size, or 400/409 and nothing exists. Creation is a percept
        ('object_added', full snapshot aboard); the save reconstructs
        custom objects entirely, so what enters the world STAYS."""
        from room.state import RoomObject
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        disp = (req.name or "").strip()
        if not disp:
            return JSONResponse(status_code=400,
                                content={"error": "a name is required"})
        oid = req.oid or "".join(c if c.isalnum() else "_"
                                 for c in disp.lower()).strip("_")
        while "__" in oid:
            oid = oid.replace("__", "_")
        if not oid or oid.startswith("_"):
            return JSONResponse(status_code=400,
                                content={"error": f"bad oid '{oid}'"})
        if req.oid and (oid in room.objects or oid in room.members):
            # an EXPLICIT oid collision is an error; an auto-slugged
            # one just counts up -- the no-typing path never bounces
            # you to a keyboard over a name clash.
            return JSONResponse(status_code=409, content={
                "error": f"'{oid}' already exists in {rid}"})
        if oid in room.objects or oid in room.members:
            var_base = oid
            n = 2
            while oid in room.objects or oid in room.members:
                oid = f"{var_base}_{n}"
                n += 1
        p = req.position_m
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            return JSONResponse(status_code=400, content={
                "error": "position_m must be [x, y] numbers"})
        if (x * x + y * y) ** 0.5 > room.radius_m:
            return JSONResponse(status_code=400, content={
                "error": f"[{x:.2f}, {y:.2f}] is outside the yurt "
                         f"(r={room.radius_m})"})
        if not (0.02 <= req.size_m <= 6.0):
            return JSONResponse(status_code=400, content={
                "error": "size_m must be 0.02..6.0"})
        obj = RoomObject(oid, disp, [x, y],
                         description=req.description,
                         texture=req.texture,
                         kind=(req.kind or "").strip() or None,
                         size_m=req.size_m)
        room.objects[oid] = obj
        room.emit(req.by, "object_added",
                  {"oid": oid, "object": disp,
                   "snapshot": obj.snapshot()})
        return {"ok": True, "oid": oid, "object": obj.snapshot()}

    @app.post("/api/rooms/{rid}/objects/{oid}/update")
    def object_update(rid: str, oid: str, req: ObjectUpdateReq):
        """Adjust a thing's hints: name, kind, size, description,
        texture. Only supplied fields change; position has its own
        door. Emits 'object_updated' with the fresh snapshot."""
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        obj = room.objects.get(oid)
        if obj is None:
            return JSONResponse(status_code=404, content={
                "error": f"no object '{oid}' in {rid}"})
        if req.size_m is not None and not (0.02 <= req.size_m <= 6.0):
            return JSONResponse(status_code=400, content={
                "error": "size_m must be 0.02..6.0"})
        if req.name is not None and not req.name.strip():
            return JSONResponse(status_code=400,
                                content={"error": "name can't be empty"})
        if req.y_off_m is not None and not (-1.0 <= req.y_off_m <= 3.0):
            return JSONResponse(status_code=400, content={
                "error": "y_off_m must be -1.0..3.0"})
        for f in ("name", "kind", "size_m", "rot_deg",
                  "y_off_m", "description", "texture"):
            v = getattr(req, f)
            if v is not None:
                setattr(obj, f, v.strip() if isinstance(v, str) else v)
        obj.rot_deg = float(obj.rot_deg) % 360.0
        if obj.kind == "":
            obj.kind = None
        room.emit(req.by, "object_updated",
                  {"oid": oid, "object": obj.name,
                   "snapshot": obj.snapshot()})
        return {"ok": True, "object": obj.snapshot()}

    @app.delete("/api/rooms/{rid}/objects/{oid}")
    def object_remove(rid: str, oid: str, force: bool = False,
                      by: str = "Re"):
        """A thing leaves the world. Refuses to take written pages
        with it unless forced (exile-then-purge: content is not
        collateral). Departure is a percept ('object_removed')."""
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        obj = room.objects.get(oid)
        if obj is None:
            return JSONResponse(status_code=404, content={
                "error": f"no object '{oid}' in {rid}"})
        if obj.pages and not force:
            return JSONResponse(status_code=409, content={
                "error": f"{obj.name} holds {len(obj.pages)} written "
                         "page(s) -- force=true to remove anyway"})
        del room.objects[oid]
        app.state.seed_ids.get(rid, set()).discard(oid)
        room.emit(by, "object_removed", {"oid": oid,
                                         "object": obj.name})
        return {"ok": True, "removed": oid}

    @app.get("/api/models")
    def models_manifest():
        """What art exists: filenames in assets/objects + avatars.
        The 3D client resolves oid/kind -> file from THIS list, then
        fetches only what exists -- drop a GLB in the folder, refresh,
        it's in the room. No export, no restart."""
        def _ls(sub):
            d = os.path.join(REPO, "godot-room", "assets", sub)
            try:
                return sorted(f for f in os.listdir(d)
                              if f.lower().endswith(
                                  (".glb", ".png", ".jpg", ".jpeg")))
            except OSError:
                return []
        return {"objects": _ls("objects"), "avatars": _ls("avatars")}

    @app.get("/tuning")
    def tuning():
        """room_tuning.json over HTTP. The web-exported 3D client
        can't watch the file on disk, so it polls this instead --
        same dials, same panel; the FILE stays the interface, this
        is just a window onto it."""
        import json
        path = os.path.join(REPO, "room_tuning.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return JSONResponse(
                status_code=500,
                content={"error": "room_tuning.json didn't parse"})

    # The 3D window, browser edition: godot-room's web export served
    # at /3d. Soft-skip when no export exists -- the host never
    # breaks on a machine that hasn't exported yet.
    web_dir = os.path.join(REPO, "godot-room", "export", "web")
    if os.path.isdir(web_dir):
        app.mount("/3d", StaticFiles(directory=web_dir, html=True))
        print("[room host] 3D web export mounted at /3d")

    # runtime art: models served straight from the assets folders --
    # the 3D client fetches these at load instead of packing them
    # into the export. The folder IS the asset pipeline now.
    for prefix, sub in (("/models", "objects"), ("/avatars", "avatars")):
        d = os.path.join(REPO, "godot-room", "assets", sub)
        if os.path.isdir(d):
            app.mount(prefix, StaticFiles(directory=d))

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8720)
    args = ap.parse_args()
    app = build_app()
    print(f"[room host] {len(app.state.rooms)} rooms | contract "
          f"{CONTRACT_VERSION} | http://127.0.0.1:{args.port}")
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
