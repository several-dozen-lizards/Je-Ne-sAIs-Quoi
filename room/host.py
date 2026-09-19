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
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi import BackgroundTasks, FastAPI, Request
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
from core.body_packages import BodyPackageError, inspect_glb
from core.body_candidates import (MAX_CANDIDATE_BYTES, CandidateStager,
                                  append_preview_receipt,
                                  candidate_model_path, list_candidates,
                                  load_candidate,
                                  save_candidate_mapping)
from core.body_recipes import (PILOT_TARGET as BODY_RECIPE_PILOT,
                               list_recipes, load_recipe, save_recipe)
from core.conversation_ledger import ConversationLedger
from core.terrain_surface import load_world_recipes
from core.world_modules import (WorldModuleError, capture_module,
                                compile_stamp, list_modules, load_module,
                                save_module)
from room.local_weather import LocalWeather
from room.object_profile import ObjectProfileError, propose_object_profile
from shell.persona_media import load_persona_avatar
from shell.ui_background import (delete_nexus_background,
                                 load_conversation_background,
                                 load_nexus_background,
                                 save_nexus_background)
from shell.ui_themes import resolve_nexus_theme, resolve_theme, save_nexus_theme
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BODY_CANDIDATE_PILOT = "starter_persona"
MAX_OBJECT_IMPORT_BYTES = 160 * 1024 * 1024
OBJECT_CATALOG_CATEGORIES = {
    "seating", "beds", "surfaces", "pictures", "misc"
}
STATE_FILE = os.environ.get(
    "JNSQ_ROOM_STATE",                      # test isolation forever
    os.path.join(REPO, "room", "room_world.json"))


def _body_candidate_root():
    return os.environ.get(
        "JNSQ_BODY_CANDIDATES",
        os.path.join(REPO, "scratch", "body_candidates"))


def _body_recipe_root():
    return os.environ.get(
        "JNSQ_BODY_RECIPES",
        os.path.join(REPO, "scratch", "body_recipes"))


def _world_recipe_root():
    return os.environ.get(
        "JNSQ_WORLD_RECIPES",
        os.path.join(REPO, "room", "world_recipes"))


def _world_module_root():
    return os.environ.get(
        "JNSQ_WORLD_MODULES",
        os.path.join(REPO, "room", "world_modules"))


def _object_asset_root():
    return os.environ.get(
        "JNSQ_OBJECT_ASSETS",
        os.path.join(REPO, "godot-room", "assets", "objects"))


def _object_thumbnail_root():
    return os.path.join(_object_asset_root(), ".thumbnails")


def _render_object_thumbnail(asset_path: str) -> bool:
    """Render one cached preview locally; failure leaves a labeled fallback."""
    if os.path.splitext(asset_path)[1].lower() != ".glb":
        return False
    blender = os.environ.get("JNSQ_BLENDER", r"E:\Blender\blender.exe")
    script = os.path.join(REPO, "tools", "render_object_thumbnail.py")
    if not os.path.isfile(blender) or not os.path.isfile(script):
        return False
    stem = os.path.splitext(os.path.basename(asset_path))[0]
    root = _object_thumbnail_root()
    os.makedirs(root, exist_ok=True)
    output = os.path.join(root, stem + ".png")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [blender, "--background", "--factory-startup", "--python",
             script, "--", asset_path, output],
            cwd=REPO, timeout=300, creationflags=flags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False)
        return completed.returncode == 0 and os.path.isfile(output)
    except (OSError, subprocess.SubprocessError):
        return False


def _catalog_category(stem: str, detail: dict) -> str:
    metadata = detail.get("metadata") if isinstance(detail, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    explicit = str(metadata.get("category", "")).strip().lower()
    if explicit in OBJECT_CATALOG_CATEGORIES:
        return explicit
    folded = stem.lower().replace("-", "_")
    if any(word in folded for word in (
            "chair", "couch", "sofa", "bench", "stool", "seat")):
        return "seating"
    if "bed" in folded:
        return "beds"
    if any(word in folded for word in (
            "desk", "table", "shelf", "cabinet", "counter",
            "nightstand", "surface")):
        return "surfaces"
    if (detail.get("format") in {"png", "jpg", "jpeg"}
            or any(word in folded for word in (
                "poster", "picture", "painting", "portrait", "frame"))):
        return "pictures"
    return "misc"


def _catalog_item(stem: str, detail: dict) -> dict:
    metadata = detail.get("metadata") if isinstance(detail, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    category = _catalog_category(stem, detail)
    default_sizes = {
        "seating": 1.6, "beds": 2.0, "surfaces": 1.4,
        "pictures": 1.0, "misc": 0.8,
    }
    try:
        size = float(metadata.get("default_size_m", default_sizes[category]))
    except (TypeError, ValueError):
        size = default_sizes[category]
    display = str(metadata.get("display_name", "")).strip()
    if not display:
        display = stem.replace("_", " ").replace("-", " ").title()
    image_format = detail.get("format") in {"png", "jpg", "jpeg"}
    thumbnail_path = os.path.join(_object_thumbnail_root(), stem + ".png")
    thumbnail_ready = image_format or os.path.isfile(thumbnail_path)
    thumbnail_url = ("/models/" + str(detail.get("filename", ""))
                     if image_format else
                     "/model-thumbnails/" + stem + ".png")
    return {
        "kind": stem,
        "filename": detail.get("filename", ""),
        "display_name": display,
        "category": category,
        "format": detail.get("format", ""),
        "bytes": int(detail.get("bytes", 0)),
        "packaged": bool(detail.get("packaged", False)),
        "size_m": max(0.02, min(6.0, size)),
        "capability": metadata.get("capability")
        or metadata.get("jnaiq_capability"),
        "thumbnail_url": thumbnail_url,
        "thumbnail_ready": thumbnail_ready,
    }


def _named_theme_value(mapping: dict, *names):
    """Case-insensitive lookup for display names and stable ids."""
    folded = {str(key).casefold(): value for key, value in
              (mapping or {}).items()}
    for name in names:
        if name is not None and str(name).casefold() in folded:
            return folded[str(name).casefold()]
    return None

# ── THE WORLD LOCK (audit finding 2, 2026-07-05) ──
# One world, one writer at a time. N live actors + heartbeats +
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
            "support_surface": getattr(o, "support_surface", "yurt_floor"),
            "support_oid": getattr(o, "support_oid", None),
            "description": o.description, "texture": o.texture,
            "capability": o.capability, "owner": o.owner,
            "affordances": dict(o.affordances),
            "temperature_c": o.temperature_c, "mass_kg": o.mass_kg,
            "profile_provenance": dict(getattr(
                o, "profile_provenance", {}) or {}),
            "power": getattr(o, "power", 0.0),
            "board_revision": int(getattr(o, "board_revision", 0)),
            "board_reads": dict(getattr(o, "board_reads", {}) or {}),
            "custom": custom}


OBJECT_SUPPORT_SURFACES = {
    "yurt_floor", "yurt_wall", "island_ground", "object", "free"
}


def _object_support_error(room, oid: str, position_m, size_m: float,
                          support_surface: str, support_oid: str | None,
                          candidate_positions: dict | None = None,
                          candidate_sizes: dict | None = None):
    """Validate one durable support declaration before any mutation."""
    surface = str(support_surface or "yurt_floor")
    if surface not in OBJECT_SUPPORT_SURFACES:
        return f"invalid support surface '{surface}'"
    if not room.object_position_supported(position_m, size_m, surface):
        place = "island" if surface in {
            "island_ground", "object", "free"} else "yurt"
        return f"'{oid}' has no supported footprint on the {place}"
    if surface != "object":
        if support_oid:
            return "support_oid is only valid for object support"
        return None
    target_id = str(support_oid or "")
    if not target_id or target_id == oid:
        return "object support needs a different support_oid"
    target = room.objects.get(target_id)
    if target is None:
        return f"no supporting object '{target_id}'"
    try:
        target_position = dict(candidate_positions or {}).get(
            target_id, target.position_m)
        target_size = dict(candidate_sizes or {}).get(
            target_id, getattr(target, "size_m", 0.6))
        distance = room._dist(position_m, target_position)
        usable = max(0.08, float(target_size) * 0.55)
    except (TypeError, ValueError, IndexError):
        return f"invalid supporting object '{target_id}'"
    if distance > usable:
        return f"'{oid}' is not over supporting object '{target_id}'"
    # Refuse a support loop even if older persisted state contains a longer
    # chain. A relationship graph may be deep; it may never be cyclic.
    seen = {str(oid)}
    cursor = target
    while cursor is not None and getattr(cursor, "support_surface", "") == "object":
        cursor_id = str(getattr(cursor, "support_oid", "") or "")
        if not cursor_id:
            break
        if cursor_id in seen:
            return "object support would create a cycle"
        seen.add(cursor_id)
        cursor = room.objects.get(cursor_id)
    return None


def _detach_supported_children(room, removed_oids) -> dict:
    """Drop surviving dependants to their local ground when support leaves."""
    removed = {str(oid) for oid in removed_oids}
    detached = {}
    for oid, obj in room.objects.items():
        if oid in removed or getattr(obj, "support_oid", None) not in removed:
            continue
        distance = room._dist(obj.position_m, [0.0, 0.0])
        obj.support_surface = (
            "island_ground" if room.shape == "island"
            and distance > room.radius_m else "yurt_floor")
        obj.support_oid = None
        detached[oid] = obj.snapshot()
    return detached


def _save_world(app):
    """Positions, presence, events, pages -> disk. The world survives
    its own host now; a bounce is no longer an amnesia event."""
    import json
    seed = getattr(app.state, "seed_ids", {})
    d = {"where": dict(app.state.where),
         "rooms": {rid: {"members": {m: mem.snapshot() for m, mem
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
            # members: room-2 records restore whole; legacy saves
            # (bare [x, y] lists) restore position and default the
            # heading toward the center — the same tolerance idiom
            # as objects below. Clamp-on-restore: legacy saves may
            # hold positions outside the yurt wall; the door law
            # applies to history too.
            from room.state import Member, heading_toward
            room.members = {}
            for m, rec in saved.get("members", {}).items():
                if isinstance(rec, dict):
                    mpos = room._clamp_inside(list(
                        rec.get("position_m", [0.0, 0.0])))
                    room.members[m] = Member(m, mpos, float(
                        rec.get("heading_deg",
                                heading_toward(mpos, [0.0, 0.0]))),
                        rec.get("face"),
                        rec.get("posture", "standing"),
                        rec.get("gaze_yaw_deg", 0.0),
                        rec.get("gaze_pitch_deg", 0.0),
                        rec.get("gesture", ""),
                        rec.get("movement") or {})
                elif isinstance(rec, list) and len(rec) == 2:
                    mpos = room._clamp_inside(list(rec))
                    room.members[m] = Member(
                        m, mpos, heading_toward(mpos, [0.0, 0.0]))
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
                              "y_off_m", "support_surface", "support_oid",
                              "description", "texture", "power"):
                        if rec.get(f) is not None:
                            setattr(o, f, rec[f])
                    if rec.get("affordances") is not None:
                        o.affordances = dict(rec.get("affordances") or {})
                    if rec.get("temperature_c") is not None:
                        o.temperature_c = float(rec["temperature_c"])
                    o.profile_provenance = dict(
                        rec.get("profile_provenance") or {})
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
                        y_off_m=float(rec.get("y_off_m", 0.0)),
                        support_surface=rec.get(
                            "support_surface", "yurt_floor"),
                        support_oid=rec.get("support_oid"),
                        profile_provenance=rec.get(
                            "profile_provenance") or {},
                        power=float(rec.get("power", 0.0)))
            for oid, pages in saved.get("pages", {}).items():
                if oid in room.objects:
                    obj = room.objects[oid]
                    obj.pages = pages
                    rec = dict(saved.get("objects", {}).get(oid) or {})
                    obj.board_revision = max(
                        len(pages), int(rec.get("board_revision", 0) or 0))
                    obj.board_reads = {
                        str(member): max(0, int(revision or 0))
                        for member, revision in
                        dict(rec.get("board_reads") or {}).items()}
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
    action: str            # move_to | body_motion | say | write | express
    object: str = None
    text: str = None
    force_n: float = 5.0
    face: dict = None      # express: the visible-surface packet
    to: list = None        # walk: [x, y] meters, anywhere inside
    heading_deg: float = None  # embodied walk: camera/body heading
    conversation_id: str = None
    social_depth: int = 0      # generated reply lineage; 0 = opening
    social_thread_id: str = None
    social_parent_seq: int = 0
    social_api_token_load: float = 0.0
    social_route: str = None
    floor_claim_id: str = None
    pose: dict = None          # transient selected body vector
    active: bool = True        # transient surface claim/release
    event_id: str = None       # content-free selection provenance
    facets: dict = None        # optional open-vocabulary descriptions
    addressed_to: list = None # address, never a privacy claim on the board
    related_posts: list = None
    provenance: list = None    # bounded source anchors, not source contents
    post_id: str = None        # board_retract target


class AvatarVisionFrameReq(BaseModel):
    member: str
    data_url: str
    images: list = None
    pose_revision: int
    cause: str = "scene_change"
    novelty: float = 1.0
    optical_pose: dict = None
    scene_grounding: dict = None


class SocialFloorClaimReq(BaseModel):
    member: str
    source_seq: int
    thread_id: str = ""
    lease_s: float = 120.0


class SocialFloorReleaseReq(BaseModel):
    member: str
    claim_id: str
    reason: str = "settled"


class BodyMappingReq(BaseModel):
    roles: dict = None
    expressions: dict = None
    optical_origin: dict = None


class BodyPreviewReceiptReq(BaseModel):
    revision_id: str
    renderer: str
    outcome: str
    room_connected: bool
    head_role: str = ""
    head_resolved: bool = False
    optical_node: str = ""
    optical_resolved: bool = False
    optical_position_m: list
    pov_ready: bool = False
    frame_data_url: str
    pov_frame_data_url: str = None


class BodyRecipeReq(BaseModel):
    name: str
    body_family: str = "jnaiq-humanoid-01"
    pilot_target: str = BODY_RECIPE_PILOT
    parameters: dict = None
    face: dict = None
    identity: dict = None
    source_candidate: dict = None
    surface: dict = None


class ObjectMoveReq(BaseModel):
    position_m: list       # [x, y] meters, center-origin
    by: str = "Re"         # whose hand moved it (the editor is a hand)


class ObjectTransformReq(BaseModel):
    position_m: list       # atomic build commit: position + yaw + lift + size
    rot_deg: float
    y_off_m: float
    size_m: float | None = None
    support_surface: str | None = None
    support_oid: str | None = None
    by: str = "Re"


class ObjectTransformItem(BaseModel):
    oid: str
    position_m: list
    rot_deg: float
    y_off_m: float
    size_m: float | None = None
    support_surface: str | None = None
    support_oid: str | None = None


class ObjectBatchTransformReq(BaseModel):
    objects: list[ObjectTransformItem]
    by: str = "Re"


class ObjectCreateReq(BaseModel):
    name: str
    oid: str | None = None  # slugged from name when absent
    kind: str | None = None # render hint: which model file
    size_m: float = 0.6
    position_m: list = [0.0, 0.0]
    rot_deg: float = 0.0
    y_off_m: float = 0.0
    support_surface: str = "yurt_floor"
    support_oid: str | None = None
    description: str = ""
    texture: str = "neutral"
    capability: str | None = None
    by: str = "Re"


class ObjectBatchCreateReq(BaseModel):
    objects: list[ObjectCreateReq]
    by: str = "Re"


class ObjectBatchDeleteReq(BaseModel):
    oids: list[str]
    by: str = "Re"


class WorldModuleCaptureReq(BaseModel):
    name: str
    oids: list[str]
    by: str = "Re"


class WorldModuleStampReq(BaseModel):
    anchor_m: list
    rot_deg: float = 0.0
    by: str = "Re"


class ObjectUpdateReq(BaseModel):
    name: str = None       # only non-None fields change
    kind: str = None
    size_m: float = None
    rot_deg: float = None  # yaw, degrees
    y_off_m: float = None  # vertical lift, meters (the lever)
    description: str = None
    texture: str = None
    capability: str = None  # affordance stamp: 'sitting' etc.
                            # (20260720: sitting made these consumed)
    by: str = "Re"


class ObjectProfileReq(BaseModel):
    """One explicit, local-only AI environmental-profile request."""
    model: str | None = None
    by: str = "Re"


def build_app() -> FastAPI:
    app = FastAPI(title="JNAIQ room host", version=CONTRACT_VERSION)
    app.state.avatar_vision = {}
    app.state.local_weather = LocalWeather(
        os.environ.get("JNSQ_LOCAL_WEATHER",
                       os.path.join(REPO, "room", "local_weather.json")),
        os.path.join(REPO, "room_tuning.json"))
    app.state.weather_wakeup = asyncio.Event()
    app.state.weather_task = None
    jnaiq_assets = os.path.join(REPO, "assets", "jnaiq")
    if os.path.isdir(jnaiq_assets):
        app.mount("/assets", StaticFiles(directory=jnaiq_assets),
                  name="jnaiq-assets")
    world = build_world()
    app.state.rooms = world["rooms"]
    app.state.adjacency = world["adjacency"]
    recipes = load_world_recipes(_world_recipe_root())
    app.state.world_recipes = {
        recipe.recipe_id: recipe for recipe in recipes}
    app.state.terrain_surfaces = {}
    for recipe in recipes:
        for surface in recipe.terrain_surfaces:
            app.state.terrain_surfaces[surface.surface_id] = {
                "recipe": recipe, "surface": surface}
    app.state.where = {}    # member -> room id (one body, one room)
    # who came from the seed: anything else in a save is a runtime
    # creation (the curator's, or someday the household's own)
    app.state.seed_ids = {rid: set(r.objects.keys())
                          for rid, r in app.state.rooms.items()}
    app.state.conversation_ledger = ConversationLedger(
        os.path.join(os.path.dirname(os.path.abspath(STATE_FILE)),
                     "conversations.jsonl"),
        owner="nexus", scope="room")
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
                if roster.get("kind", "model_persona") != "model_persona":
                    continue
                display = roster.get("display_name") or display
                declared_room = (roster.get("room") or {}).get("id") \
                    or declared_room
        except Exception:
            continue
        rid = declared_room
        if rid == f"{pid}_den" and rid not in app.state.rooms:
            den = build_persona_den(pid, display)
            app.state.rooms[rid] = den
            app.state.adjacency[rid] = ["nexus"]
            app.state.adjacency.setdefault("nexus", []).append(rid)
            app.state.seed_ids[rid] = set(den.objects)
    if _load_world(app):
        print("[room host] world state restored from disk")
    for rid, room in app.state.rooms.items():
        for event in room.events:
            if event.get("kind") != "say":
                continue
            app.state.conversation_ledger.snapshot(
                conversation_id=f"room:{rid}:{event.get('seq')}",
                channel="room", speaker=event.get("member", ""),
                message=(event.get("data") or {}).get("text", ""),
                reply="", timestamp=str(event.get("t") or ""),
                source="room_event_backfill",
                fields={"room_id": rid, "room_seq": event.get("seq")})

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
        if p.startswith("/3d"):
            response = await call_next(request)
            # Godot's package is hundreds of megabytes, so `no-store` would
            # make every visit download it again.  `no-cache` keeps the local
            # copy but requires its ETag to be revalidated before reuse.  A
            # rebuilt camera/client package can therefore never leave an old
            # runtime alive behind newly rendered UI state.
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
            return response
        if p.startswith("/terrain-canary") or p.startswith("/models") \
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

    @app.get("/chat", response_class=HTMLResponse)
    def nexus_chat():
        """Scene-free Nexus conversation and presence surface."""
        with open(os.path.join(REPO, "room", "viewer_public.html"),
                  encoding="utf-8") as f:
            return f.read()

    @app.get("/chat", response_class=HTMLResponse)
    def nexus_chat():
        """Scene-free Nexus conversation and presence surface."""
        with open(os.path.join(REPO, "room", "viewer_public.html"),
                  encoding="utf-8") as f:
            return f.read()

    def _weather_semantic_revision(value: dict) -> str:
        status = dict((value or {}).get("status") or {})
        semantic = {
            "enabled": bool((value or {}).get("enabled")),
            "location_label": str((value or {}).get("location_label") or ""),
            "observed_at": status.get("observed_at"),
            "valid_until": status.get("valid_until"),
            "weather": status.get("weather"),
            "current": status.get("current"),
            "error": status.get("error"),
        }
        return hashlib.sha256(json.dumps(
            semantic, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str).encode("utf-8")).hexdigest()

    def _emit_weather_revision(before: str, result: dict):
        after = _weather_semantic_revision(result)
        if after == before:
            return
        # Content-free shared change event. Each resident reads the canonical
        # coordinate-free weather status through their own awareness organ.
        # The event does not expose coordinates or inject weather prose.
        for room in app.state.rooms.values():
            room.emit("household_weather", "weather_revision", {
                "revision": after,
                "provider": str(
                    dict(result.get("status") or {}).get("source") or ""),
            })

    async def _weather_cycle():
        failures = 0
        while True:
            weather = app.state.local_weather
            if weather.due():
                before = _weather_semantic_revision(weather.public_status())
                result = await asyncio.to_thread(weather.refresh)
                failures = 0 if result["status"].get("ok") else failures + 1
                _emit_weather_revision(before, result)
            if not weather.config.get("enabled"):
                delay = None
            else:
                try:
                    valid = dt.datetime.fromisoformat(
                        str(weather.status["valid_until"]).replace(
                            "Z", "+00:00"))
                    if valid.tzinfo is None:
                        valid = valid.replace(tzinfo=dt.timezone.utc)
                    delay = max(1.0, (
                        valid.astimezone(dt.timezone.utc)
                        - dt.datetime.now(dt.timezone.utc)).total_seconds())
                except (KeyError, TypeError, ValueError):
                    # Network failure recovery is a bounded curve, not the
                    # room's observation cadence.
                    delay = min(900.0, 30.0 * (2 ** min(failures, 5)))
            app.state.weather_wakeup.clear()
            try:
                if delay is None:
                    await app.state.weather_wakeup.wait()
                else:
                    await asyncio.wait_for(
                        app.state.weather_wakeup.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    @app.on_event("startup")
    async def _start_weather_cycle():
        app.state.weather_task = asyncio.create_task(_weather_cycle())

    @app.on_event("shutdown")
    async def _stop_weather_cycle():
        task = app.state.weather_task
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @app.get("/weather-sync")
    def weather_sync_status():
        return app.state.local_weather.public_status()

    @app.post("/weather-sync")
    async def weather_sync_config(request: Request):
        payload = await request.json()
        if not isinstance(payload, dict) or not isinstance(
                payload.get("enabled"), bool):
            return JSONResponse(status_code=400, content={
                "error": "weather sync requires an enabled boolean"})
        try:
            result = app.state.local_weather.configure(
                enabled=payload["enabled"],
                latitude=payload.get("latitude"),
                longitude=payload.get("longitude"),
                location_label=payload.get("location_label", ""))
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        app.state.weather_wakeup.set()
        return result

    @app.post("/weather-sync/refresh")
    async def refresh_weather():
        before = _weather_semantic_revision(
            app.state.local_weather.public_status())
        result = await asyncio.to_thread(app.state.local_weather.refresh)
        if not result["status"].get("ok"):
            return JSONResponse(status_code=502, content=result)
        _emit_weather_revision(before, result)
        app.state.weather_wakeup.set()
        return result

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
                "where": dict(app.state.where),
                "world_recipes": [
                    recipe.summary()
                    for recipe in app.state.world_recipes.values()],
                "terrain_surfaces": {
                    surface_id: {
                        **entry["surface"].summary(),
                        "world_recipe_id": entry["recipe"].recipe_id,
                        "world_recipe_revision_id":
                            entry["recipe"].revision_id,
                        "stage": entry["recipe"].stage,
                    }
                    for surface_id, entry
                    in app.state.terrain_surfaces.items()}}

    @app.get("/api/world-recipes")
    def world_recipes():
        return {
            "schema": "jnaiq-world-recipe-index/0.1",
            "recipes": [
                recipe.summary()
                for recipe in app.state.world_recipes.values()],
        }

    @app.get("/api/terrain-surfaces/{surface_id}")
    def terrain_surface_recipe(surface_id: str):
        entry = app.state.terrain_surfaces.get(surface_id)
        if entry is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"no terrain surface '{surface_id}'"})
        return {
            **entry["surface"].recipe_payload(),
            "world_recipe_id": entry["recipe"].recipe_id,
            "world_recipe_revision_id": entry["recipe"].revision_id,
            "stage": entry["recipe"].stage,
        }

    @app.get("/api/terrain-surfaces/{surface_id}/sample")
    def terrain_surface_sample(
            surface_id: str, x_m: float, z_m: float):
        entry = app.state.terrain_surfaces.get(surface_id)
        if entry is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"no terrain surface '{surface_id}'"})
        try:
            sample = entry["surface"].sample(x_m, z_m)
        except ValueError as error:
            return JSONResponse(
                status_code=400, content={"error": str(error)})
        return {
            **sample,
            "world_recipe_id": entry["recipe"].recipe_id,
            "world_recipe_revision_id": entry["recipe"].revision_id,
            "stage": entry["recipe"].stage,
        }

    @app.get("/api/rooms/{rid}")
    def room_state(rid: str, member: str = None):
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        return room.snapshot(observer=member)

    @app.get("/api/rooms/{rid}/events")
    def room_events(rid: str, since: int = 0, surface: int = 0):
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        # surface=1 opts into body-surface deltas (faces) -- windows
        # that render bodies want them; logs and perception don't.
        return {"events": room.events_since(since, bool(surface))}

    @app.get("/api/rooms/{rid}/events/wait")
    def room_events_wait(rid: str, since: int = 0,
                         timeout: float = 25.0, surface: int = 0):
        """Long-poll until this room's event sequence advances.

        Renderers wait on an actual state threshold rather than waking on a
        blind browser timer. The bounded timeout merely renews the connection.
        """
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        events = room.wait_for_events(since, timeout, bool(surface))
        return {"events": events, "last_seq": room._seq}

    @app.get("/api/rooms/{rid}/social-floor")
    def social_floor_status(rid: str):
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        return room.social_floor_status()

    @app.post("/api/rooms/{rid}/social-floor/claim")
    def social_floor_claim(rid: str, req: SocialFloorClaimReq):
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        result = room.claim_social_floor(
            req.member, req.source_seq, req.thread_id, req.lease_s)
        if not result.get("ok"):
            return JSONResponse(status_code=409, content=result)
        return result

    @app.post("/api/rooms/{rid}/social-floor/release")
    def social_floor_release(rid: str, req: SocialFloorReleaseReq):
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        result = room.release_social_floor(
            req.member, req.claim_id, req.reason)
        if not result.get("ok"):
            return JSONResponse(status_code=409, content=result)
        return result

    @app.post("/api/rooms/{rid}/vision/frame")
    def avatar_vision_frame(rid: str, req: AvatarVisionFrameReq):
        room = app.state.rooms.get(rid)
        if room is None or req.member not in room.members:
            return JSONResponse(status_code=404,
                                content={"error": "observer is not in room"})
        raw_images = list(req.images or [])
        if not raw_images:
            raw_images = [{"data_url": req.data_url,
                           "ordinal": 0, "relative_yaw_deg": 0.0}]
        if len(raw_images) > 4:
            return JSONResponse(status_code=413,
                                content={"error": "POV episode has too many frames"})
        images = []
        total_chars = 0
        for ordinal, item in enumerate(raw_images):
            item = dict(item or {})
            data_url = str(item.get("data_url") or "")
            if not data_url.startswith("data:image/png;base64,"):
                return JSONResponse(
                    status_code=400,
                    content={"error": "every POV frame must be PNG data"})
            if len(data_url) > 2_000_000:
                return JSONResponse(status_code=413,
                                    content={"error": "POV frame is too large"})
            total_chars += len(data_url)
            images.append({
                "data_url": data_url,
                "ordinal": ordinal,
                "relative_yaw_deg": float(
                    item.get("relative_yaw_deg", ordinal * 90.0)),
            })
        if total_chars > 8_000_000:
            return JSONResponse(status_code=413,
                                content={"error": "POV episode is too large"})
        key = (rid, req.member.casefold())
        previous = app.state.avatar_vision.get(key) or {}
        revision = int(previous.get("revision", 0)) + 1
        record = {"revision": revision, "member": req.member,
                  "pose_revision": int(req.pose_revision),
                  "cause": str(req.cause)[:80],
                  "novelty": max(0.0, min(1.0, float(req.novelty))),
                  "optical_pose": dict(req.optical_pose or {}),
                  "scene_grounding": dict(req.scene_grounding or {}),
                  "data_url": images[0]["data_url"],
                  "images": images}
        app.state.avatar_vision[key] = record
        return {"ok": True, "revision": revision}

    @app.get("/api/rooms/{rid}/vision/{member}")
    def avatar_vision_latest(rid: str, member: str, since: int = 0):
        record = app.state.avatar_vision.get((rid, member.casefold()))
        if not record or int(record["revision"]) <= int(since):
            return {"frame": None, "revision": int(since)}
        return {"frame": record, "revision": record["revision"]}

    @app.get("/api/personas")
    def personas():
        """Who COULD be here: roster-backed model personas (the world's host
        may offer them as bodies; minds arrive separately — a stopped
        persona placed here is a body on stage; ensure_joined recovers the
        position when the mind starts). A directory alone is fixture/storage,
        not household membership: roster.yaml is the canonical registry."""
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
            rpath = os.path.join(pdir, n, "roster.yaml")
            if not os.path.exists(rpath):
                continue
            try:
                import yaml
                with open(rpath, encoding="utf-8") as f:
                    roster = yaml.safe_load(f) or {}
                if roster.get("kind", "model_persona") != "model_persona":
                    continue
                disp = roster.get("display_name") or n
                icon = str(roster.get("icon") or "").strip()
            except Exception:
                continue          # malformed membership is not guessed
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
            # speech + the orienting reflex live in the world model
            cid, admitted, prior_state = (
                app.state.conversation_ledger.admit_once(
                conversation_id=req.conversation_id or "",
                channel="room", speaker=req.member,
                message=req.text or "", source="nexus_speech"))
            if not admitted:
                return {"ok": True, "duplicate": True, "conversation": {
                    "id": cid, "status": prior_state}}
            try:
                publication = room.say(
                    req.member, req.text or "",
                    social_depth=max(0, int(req.social_depth or 0)),
                    conversation_id=cid,
                    social_thread_id=req.social_thread_id or "",
                    social_parent_seq=max(
                        0, int(req.social_parent_seq or 0)),
                    social_api_token_load=max(
                        0.0, float(req.social_api_token_load or 0.0)),
                    social_route=req.social_route or "",
                    floor_claim_id=req.floor_claim_id or "")
                if not (publication or {}).get("ok"):
                    reason = str((publication or {}).get("reason")
                                 or "room_speech_rejected")
                    raise RuntimeError(reason)
            except BaseException as error:
                app.state.conversation_ledger.fail(cid, error)
                if str(error) == "social_floor_superseded":
                    return JSONResponse(status_code=409, content={
                        "ok": False,
                        "error": "social_floor_superseded",
                        "conversation": {"id": cid, "status": "failed"},
                    })
                raise
            terminal = app.state.conversation_ledger.complete(
                cid, reply="", receipts={"room_id": room.id,
                                          "room_seq": publication["seq"],
                                          "social_thread_id": publication.get(
                                              "social_thread_id") or ""})
            return {"ok": True, "conversation": {
                "id": cid, "status": "saved",
                "record_id": terminal.get("record_id", "")},
                "seq": publication["seq"],
                "social_thread_id": publication.get(
                    "social_thread_id") or ""}

        if req.action == "express":
            # body-surface update: the face, never the feelings
            return room.set_face(req.member, req.face or {})

        if req.action == "sit":
            # affordance-gated: chairs carry capability='sitting'
            return room.sit(req.member, req.object or None)

        if req.action == "stand":
            return room.stand(req.member)

        if req.action == "gesture":
            return room.set_gesture(req.member, req.object or "")

        if req.action == "release_gesture":
            return room.set_gesture(req.member, "")

        if req.action == "body_motion":
            return room.perform_motion(req.member, req.object or "")

        if req.action == "transient_pose":
            return room.set_transient_pose(
                req.member, req.pose, active=req.active,
                event_id=req.event_id or "")

        if req.action == "light_on":
            return room.set_light(req.member, req.object, True)

        if req.action == "light_off":
            return room.set_light(req.member, req.object, False)

        if req.action == "walk":
            # free walking: the room is a place, not a menu
            return room.walk(req.member, req.to or [], req.heading_deg)

        if req.action == "look_at":
            return room.look_at(req.member, req.object)

        if req.action == "turn_toward":
            return room.turn_toward(req.member, req.object)

        if req.action == "look_around":
            return room.look_around(req.member)

        if req.action == "inspect":
            return room.inspect(req.member, req.object)

        if req.action in {"board_post", "board_read", "board_retract"}:
            from core.commons_board import (
                CommonsBoardError, append_post, read_board, retract_post)
            obj = room.objects.get(req.object)
            if obj is None or not room.near(req.member, req.object):
                return {"error": "walk to the board first"}
            if obj.capability != "commons_board":
                return {"error": f"{obj.name} is not a commons board"}
            try:
                if req.action == "board_post":
                    post = append_post(
                        obj, author=req.member, text=req.text or "",
                        facets=req.facets, addressed_to=req.addressed_to,
                        related_posts=req.related_posts,
                        provenance=req.provenance)
                    room.emit(req.member, "board_post", {
                        "object": obj.name, "post_id": post["post_id"],
                        "revision": obj.board_revision,
                        "facet_count": len(post["facets"]),
                        "addressed_count": len(post["addressed_to"]),
                        "snapshot": obj.snapshot(),
                    })
                    return {"ok": True, "post_id": post["post_id"],
                            "revision": obj.board_revision}
                if req.action == "board_read":
                    # Reading updates only this resident's private cursor. It
                    # neither announces a receipt nor obliges a response.
                    result = read_board(obj, req.member)
                    return {"ok": True, **result}
                record = retract_post(
                    obj, author=req.member, post_id=req.post_id or req.text or "")
                room.emit(req.member, "board_retract", {
                    "object": obj.name, "post_id": record["post_id"],
                    "revision": obj.board_revision,
                    "snapshot": obj.snapshot()})
                return {"ok": True, "post_id": record["post_id"],
                        "revision": obj.board_revision, "retracted": True}
            except CommonsBoardError as exc:
                return {"error": str(exc)}

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
            if obj.capability == "commons_board":
                # Backward-compatible motor grammar: old vessels may still
                # call this a writing surface. It creates the same untyped
                # post; no legacy action supplies or invents a facet.
                from core.commons_board import CommonsBoardError, append_post
                try:
                    post = append_post(
                        obj, author=req.member, text=req.text or "")
                except CommonsBoardError as exc:
                    return {"error": str(exc)}
                room.emit(req.member, "board_post", {
                    "object": obj.name, "post_id": post["post_id"],
                    "revision": obj.board_revision,
                    "facet_count": 0, "addressed_count": 0,
                    "snapshot": obj.snapshot()})
                return {"ok": True, "post_id": post["post_id"],
                        "revision": obj.board_revision}
            return {"error": f"{obj.name} is not a writing surface"}

        if req.action == "read":
            obj = room.objects.get(req.object)
            if obj is None or not room.near(req.member, req.object):
                return {"error": "walk to it first"}
            if obj.capability == "commons_board":
                from core.commons_board import read_board
                return {"ok": True, **read_board(obj, req.member)}
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
                "error": "position must contain two numeric coordinates"})
        surface = getattr(obj, "support_surface", "yurt_floor")
        support_oid = getattr(obj, "support_oid", None)
        error = _object_support_error(
            room, oid, [x, y], getattr(obj, "size_m", 0.6),
            surface, support_oid)
        if error:
            return JSONResponse(status_code=400, content={"error": error})
        frm = list(obj.position_m)
        obj.position_m = [x, y]
        room.emit(req.by, "rearrange", {"oid": oid, "object": obj.name,
                                        "from_m": frm, "to_m": [x, y]})
        return {"ok": True, "oid": oid, "position_m": [x, y]}

    @app.post("/api/rooms/{rid}/objects/{oid}/transform")
    def object_transform(rid: str, oid: str, req: ObjectTransformReq):
        """Commit an arrange preview atomically after validating every field."""
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        obj = room.objects.get(oid)
        if obj is None:
            return JSONResponse(status_code=404, content={
                "error": f"no object '{oid}' in {rid}"})
        try:
            x, y = float(req.position_m[0]), float(req.position_m[1])
            rot = float(req.rot_deg) % 360.0
            lift = float(req.y_off_m)
            size = (float(req.size_m) if req.size_m is not None
                    else float(getattr(obj, "size_m", 0.6)))
        except (TypeError, ValueError, IndexError):
            return JSONResponse(status_code=400, content={
                "error": "position, rotation, lift, and size must be numeric"})
        surface = str(req.support_surface or getattr(
            obj, "support_surface", "yurt_floor"))
        support_oid = ((req.support_oid or getattr(obj, "support_oid", None))
                       if surface == "object" else None)
        error = _object_support_error(
            room, oid, [x, y], size, surface, support_oid)
        if error:
            return JSONResponse(status_code=400, content={"error": error})
        if not (-1.0 <= lift <= 3.0):
            return JSONResponse(status_code=400, content={
                "error": "y_off_m must be -1.0..3.0"})
        if not (0.02 <= size <= 6.0):
            return JSONResponse(status_code=400, content={
                "error": "size_m must be 0.02..6.0"})
        before = {"position_m": list(obj.position_m),
                  "rot_deg": float(getattr(obj, "rot_deg", 0.0)),
                  "y_off_m": float(getattr(obj, "y_off_m", 0.0)),
                  "size_m": float(getattr(obj, "size_m", 0.6)),
                  "support_surface": getattr(
                      obj, "support_surface", "yurt_floor"),
                  "support_oid": getattr(obj, "support_oid", None)}
        obj.position_m = [x, y]
        obj.rot_deg = rot
        obj.y_off_m = lift
        obj.size_m = size
        obj.support_surface = surface
        obj.support_oid = support_oid
        room.emit(req.by, "object_updated", {
            "oid": oid, "object": obj.name, "before": before,
            "snapshot": obj.snapshot(), "arrange_commit": True})
        return {"ok": True, "oid": oid, "object": obj.snapshot()}

    @app.post("/api/rooms/{rid}/objects/transform-batch")
    def object_transform_batch(rid: str, req: ObjectBatchTransformReq):
        """Validate every member of a selection set, then commit all or none."""
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        if not req.objects:
            return JSONResponse(status_code=400,
                                content={"error": "objects cannot be empty"})
        seen = set()
        prepared = []
        before = {}
        candidate_positions = {}
        candidate_sizes = {}
        for candidate in req.objects:
            existing = room.objects.get(candidate.oid)
            if existing is None:
                continue
            try:
                candidate_positions[candidate.oid] = [
                    float(candidate.position_m[0]),
                    float(candidate.position_m[1])]
                candidate_sizes[candidate.oid] = (
                    float(candidate.size_m) if candidate.size_m is not None
                    else float(getattr(existing, "size_m", 0.6)))
            except (TypeError, ValueError, IndexError):
                continue
        for item in req.objects:
            oid = item.oid
            if oid in seen:
                return JSONResponse(status_code=400, content={
                    "error": f"duplicate object '{oid}'"})
            seen.add(oid)
            obj = room.objects.get(oid)
            if obj is None:
                return JSONResponse(status_code=404, content={
                    "error": f"no object '{oid}' in {rid}"})
            try:
                x, y = float(item.position_m[0]), float(item.position_m[1])
                rot = float(item.rot_deg) % 360.0
                lift = float(item.y_off_m)
                size = (float(item.size_m) if item.size_m is not None
                        else float(getattr(obj, "size_m", 0.6)))
            except (TypeError, ValueError, IndexError):
                return JSONResponse(status_code=400, content={
                    "error": f"invalid transform for '{oid}'"})
            surface = str(item.support_surface or getattr(
                obj, "support_surface", "yurt_floor"))
            support_oid = ((item.support_oid or getattr(
                obj, "support_oid", None)) if surface == "object" else None)
            error = _object_support_error(
                room, oid, [x, y], size, surface, support_oid,
                candidate_positions, candidate_sizes)
            if error:
                return JSONResponse(status_code=400, content={"error": error})
            if not (-1.0 <= lift <= 3.0):
                return JSONResponse(status_code=400, content={
                    "error": f"invalid lift for '{oid}'"})
            if not (0.02 <= size <= 6.0):
                return JSONResponse(status_code=400, content={
                    "error": f"invalid size for '{oid}'"})
            before[oid] = {"position_m": list(obj.position_m),
                           "rot_deg": float(obj.rot_deg),
                           "y_off_m": float(obj.y_off_m),
                           "size_m": float(obj.size_m),
                           "support_surface": getattr(
                               obj, "support_surface", "yurt_floor"),
                           "support_oid": getattr(obj, "support_oid", None)}
            prepared.append((oid, obj, x, y, rot, lift, size,
                             surface, support_oid))
        snapshots = {}
        for oid, obj, x, y, rot, lift, size, surface, support_oid in prepared:
            obj.position_m = [x, y]
            obj.rot_deg = rot
            obj.y_off_m = lift
            obj.size_m = size
            obj.support_surface = surface
            obj.support_oid = support_oid
            snapshots[oid] = obj.snapshot()
        room.emit(req.by, "objects_transformed", {
            "oids": list(snapshots), "before": before,
            "snapshots": snapshots, "arrange_commit": True})
        return {"ok": True, "objects": snapshots}

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
            rot = float(req.rot_deg) % 360.0
            lift = float(req.y_off_m)
        except (TypeError, ValueError, IndexError):
            return JSONResponse(status_code=400, content={
                "error": "position, rotation, and lift must be numeric"})
        if not (0.02 <= req.size_m <= 6.0):
            return JSONResponse(status_code=400, content={
                "error": "size_m must be 0.02..6.0"})
        if not (-1.0 <= lift <= 3.0):
            return JSONResponse(status_code=400, content={
                "error": "y_off_m must be -1.0..3.0"})
        surface = str(req.support_surface or "yurt_floor")
        support_oid = req.support_oid if surface == "object" else None
        error = _object_support_error(
            room, oid, [x, y], req.size_m, surface, support_oid)
        if error:
            return JSONResponse(status_code=400, content={"error": error})
        obj = RoomObject(oid, disp, [x, y],
                         description=req.description,
                         texture=req.texture,
                          kind=(req.kind or "").strip() or None,
                          size_m=req.size_m,
                          support_surface=surface,
                          support_oid=support_oid)
        obj.rot_deg = rot
        obj.y_off_m = lift
        obj.capability = (req.capability or "").strip() or None
        room.objects[oid] = obj
        room.emit(req.by, "object_added",
                  {"oid": oid, "object": disp,
                   "snapshot": obj.snapshot()})
        return {"ok": True, "oid": oid, "object": obj.snapshot()}

    @app.post("/api/rooms/{rid}/objects/create-batch")
    def object_create_batch(rid: str, req: ObjectBatchCreateReq):
        """Validate and create a selection set as one world mutation."""
        from room.state import RoomObject
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        if not req.objects:
            return JSONResponse(status_code=400,
                                content={"error": "objects cannot be empty"})
        reserved = set(room.objects) | set(room.members)
        prepared = []
        for spec in req.objects:
            disp = (spec.name or "").strip()
            if not disp:
                return JSONResponse(status_code=400,
                                    content={"error": "a name is required"})
            base = spec.oid or "".join(
                c if c.isalnum() else "_" for c in disp.lower()).strip("_")
            while "__" in base:
                base = base.replace("__", "_")
            if not base or base.startswith("_"):
                return JSONResponse(status_code=400,
                                    content={"error": f"bad oid '{base}'"})
            oid = base
            if spec.oid and oid in reserved:
                return JSONResponse(status_code=409, content={
                    "error": f"'{oid}' already exists in {rid}"})
            n = 2
            while oid in reserved:
                oid = f"{base}_{n}"
                n += 1
            reserved.add(oid)
            try:
                x, y = (float(spec.position_m[0]),
                        float(spec.position_m[1]))
                rot = float(spec.rot_deg) % 360.0
                lift = float(spec.y_off_m)
            except (TypeError, ValueError, IndexError):
                return JSONResponse(status_code=400, content={
                    "error": f"invalid transform for '{oid}'"})
            if not (0.02 <= spec.size_m <= 6.0):
                return JSONResponse(status_code=400, content={
                    "error": f"invalid size for '{oid}'"})
            if not (-1.0 <= lift <= 3.0):
                return JSONResponse(status_code=400, content={
                    "error": f"invalid lift for '{oid}'"})
            surface = str(spec.support_surface or "yurt_floor")
            support_oid = spec.support_oid if surface == "object" else None
            error = _object_support_error(
                room, oid, [x, y], spec.size_m, surface, support_oid)
            if error:
                return JSONResponse(status_code=400, content={"error": error})
            prepared.append((oid, disp, spec, x, y, rot, lift,
                             surface, support_oid))
        snapshots = {}
        for oid, disp, spec, x, y, rot, lift, surface, support_oid in prepared:
            obj = RoomObject(
                oid, disp, [x, y], description=spec.description,
                texture=spec.texture,
                kind=(spec.kind or "").strip() or None,
                size_m=spec.size_m,
                support_surface=surface,
                support_oid=support_oid)
            obj.rot_deg = rot
            obj.y_off_m = lift
            obj.capability = (spec.capability or "").strip() or None
            room.objects[oid] = obj
            snapshots[oid] = obj.snapshot()
        room.emit(req.by, "objects_added", {
            "oids": list(snapshots), "snapshots": snapshots})
        return {"ok": True, "objects": snapshots}

    @app.post("/api/rooms/{rid}/objects/delete-batch")
    def object_delete_batch(rid: str, req: ObjectBatchDeleteReq):
        """Remove a selection set only after every member is removable."""
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        if not req.oids or len(set(req.oids)) != len(req.oids):
            return JSONResponse(status_code=400, content={
                "error": "oids must be a non-empty unique list"})
        snapshots = {}
        for oid in req.oids:
            obj = room.objects.get(oid)
            if obj is None:
                return JSONResponse(status_code=404, content={
                    "error": f"no object '{oid}' in {rid}"})
            if obj.pages:
                return JSONResponse(status_code=409, content={
                    "error": f"{obj.name} holds written pages"})
            snapshots[oid] = obj.snapshot()
        detached = _detach_supported_children(room, req.oids)
        for oid in req.oids:
            del room.objects[oid]
            app.state.seed_ids.get(rid, set()).discard(oid)
        room.emit(req.by, "objects_removed", {
            "oids": list(req.oids), "snapshots": snapshots,
            "detached_snapshots": detached})
        return {"ok": True, "removed": list(req.oids),
                "objects": snapshots, "detached_snapshots": detached}

    @app.get("/api/world-modules")
    def world_module_index():
        """Inspectable library; corrupt/quarantined files are not advertised."""
        return {"schema": "jnaiq-world-module-index/0.1",
                "modules": [{
                    "module_id": module.module_id,
                    "name": module.name,
                    "member_count": len(module.members)}
                    for module in list_modules(_world_module_root())]}

    @app.get("/api/world-modules/{module_id}")
    def world_module_read(module_id: str):
        """Return one complete recipe only when the editor chooses it."""
        try:
            module = load_module(_world_module_root(), module_id)
        except WorldModuleError as exc:
            return JSONResponse(status_code=404,
                                content={"error": str(exc)})
        return {"ok": True, "module": module.as_dict()}

    @app.post("/api/rooms/{rid}/world-modules")
    def world_module_capture(rid: str, req: WorldModuleCaptureReq):
        """Save a selection as relative semantics without changing the room."""
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        if not req.oids or len(req.oids) != len(set(req.oids)):
            return JSONResponse(status_code=400, content={
                "error": "oids must be a non-empty unique list"})
        missing = [oid for oid in req.oids if oid not in room.objects]
        if missing:
            return JSONResponse(status_code=404, content={
                "error": f"no object '{missing[0]}' in {rid}"})
        try:
            module = capture_module(req.name, (
                (oid, room.objects[oid].snapshot()) for oid in req.oids))
            path = save_module(_world_module_root(), module)
        except WorldModuleError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)})
        room.emit(req.by, "world_module_saved", {
            "module_id": module.module_id, "name": module.name,
            "member_count": len(module.members)})
        return {"ok": True, "module": module.as_dict(),
                "receipt": {"schema": module.schema,
                            "stored_as": path.name,
                            "live_room_changed": False}}

    @app.post("/api/rooms/{rid}/world-modules/{module_id}/stamp")
    def world_module_stamp(rid: str, module_id: str,
                           req: WorldModuleStampReq):
        """Compile a module through the existing atomic create-batch door."""
        if rid not in app.state.rooms:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        try:
            module = load_module(_world_module_root(), module_id)
            specs = [ObjectCreateReq(**spec)
                     for spec in compile_stamp(
                         module, req.anchor_m, req.rot_deg)]
        except (WorldModuleError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)})
        result = object_create_batch(
            rid, ObjectBatchCreateReq(objects=specs, by=req.by))
        if isinstance(result, JSONResponse):
            return result
        app.state.rooms[rid].emit(req.by, "world_module_stamped", {
            "module_id": module.module_id, "name": module.name,
            "oids": list(result["objects"]),
            "anchor_m": [float(req.anchor_m[0]), float(req.anchor_m[1])],
            "rot_deg": float(req.rot_deg) % 360.0})
        return {"ok": True, "module_id": module.module_id,
                "objects": result["objects"]}

    @app.post("/api/rooms/{rid}/objects/{oid}/profile")
    def object_profile(rid: str, oid: str, req: ObjectProfileReq):
        """Explicitly ask a local model for bounded environmental metadata.

        The model cannot grant capabilities, change ownership/placement, or
        prescribe resident response. Validation completes before the object is
        mutated, so a missing model or malformed reply leaves the world alone.
        """
        room = app.state.rooms.get(rid)
        if not room:
            return JSONResponse(status_code=404,
                                content={"error": f"no room '{rid}'"})
        obj = room.objects.get(oid)
        if obj is None:
            return JSONResponse(status_code=404, content={
                "error": f"no object '{oid}' in {rid}"})
        provenance = dict(getattr(obj, "profile_provenance", {}) or {})
        if obj.affordances and provenance.get("source") != \
                "local_ai_explicit":
            return JSONResponse(status_code=409, content={
                "error": "object already has authored affordances; AI Profile "
                         "will not overwrite them"})
        before_guard = {
            "capability": obj.capability, "owner": obj.owner,
            "position_m": list(obj.position_m),
            "support_surface": getattr(obj, "support_surface", "yurt_floor"),
            "support_oid": getattr(obj, "support_oid", None),
        }
        try:
            proposal = propose_object_profile(
                obj.snapshot(), model_name=req.model)
        except ObjectProfileError as exc:
            return JSONResponse(status_code=502, content={"error": str(exc)})
        obj.affordances = dict(proposal["affordances"])
        obj.texture = str(proposal["texture"])
        if proposal.get("temperature_c") is not None:
            obj.temperature_c = float(proposal["temperature_c"])
        obj.profile_provenance = {
            "schema": 1,
            "source": "local_ai_explicit",
            "model": str(proposal["model"]),
            "applied_by": str(req.by),
            "applied_at": round(time.time(), 3),
        }
        # Keep the authority boundary executable rather than documentary.
        assert obj.capability == before_guard["capability"]
        assert obj.owner == before_guard["owner"]
        assert obj.position_m == before_guard["position_m"]
        assert getattr(obj, "support_surface", "yurt_floor") == \
            before_guard["support_surface"]
        assert getattr(obj, "support_oid", None) == before_guard["support_oid"]
        snapshot = obj.snapshot()
        room.emit(req.by, "object_profiled", {
            "oid": oid, "object": obj.name, "snapshot": snapshot,
            "model": proposal["model"],
            "affordance_keys": sorted(obj.affordances),
        })
        return {"ok": True, "object": snapshot}

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
                  "y_off_m", "description", "texture", "capability"):
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
        detached = _detach_supported_children(room, [oid])
        del room.objects[oid]
        app.state.seed_ids.get(rid, set()).discard(oid)
        room.emit(by, "object_removed", {"oid": oid,
                                         "object": obj.name,
                                         "detached_snapshots": detached})
        return {"ok": True, "removed": oid,
                "detached_snapshots": detached}

    @app.get("/api/models")
    def models_manifest():
        """What art exists: filenames in assets/objects + avatars.
        The 3D client resolves oid/kind -> file from THIS list, then
        fetches only what exists -- drop a GLB in the folder, refresh,
        it's in the room. No export, no restart."""
        def _ls(sub):
            d = (_object_asset_root() if sub == "objects" else
                 os.path.join(REPO, "godot-room", "assets", sub))
            try:
                return sorted(f for f in os.listdir(d)
                              if f.lower().endswith(
                                  (".glb", ".png", ".jpg", ".jpeg")))
            except OSError:
                return []
        objects = _ls("objects")
        details = {}
        for filename in objects:
            stem, ext = os.path.splitext(filename)
            path = os.path.join(_object_asset_root(), filename)
            detail = {"filename": filename,
                      "format": ext.lstrip(".").lower(),
                      "bytes": os.path.getsize(path),
                      "packaged": False,
                      "metadata": {}}
            sidecar = path + ".scenery.json"
            try:
                import json
                with open(sidecar, encoding="utf-8") as handle:
                    package = json.load(handle)
                metadata = package.get("metadata", {})
                stats = package.get("stats", {})
                if (package.get("schema") == "jnaiq-scenery-package-1"
                        and isinstance(metadata, dict)
                        and isinstance(stats, dict)):
                    detail.update({
                        "packaged": True,
                        "schema": package["schema"],
                        "metadata": {str(k): v for k, v in metadata.items()
                                     if isinstance(v, (str, int, float, bool))},
                        "stats": {str(k): v for k, v in stats.items()
                                  if isinstance(v, (str, int, float, bool,
                                                    list))},
                    })
            except (OSError, ValueError, TypeError):
                pass
            # GLB wins when an image and a model share a curator kind.
            if stem not in details or detail["format"] == "glb":
                details[stem] = detail
        model_stems = {stem for stem, detail in details.items()
                       if detail.get("format") == "glb"}
        catalog = []
        for stem, detail in details.items():
            # Embedded GLB textures are served as runtime dependencies, not
            # advertised as hundreds of separate paintings in the catalog.
            if (detail.get("format") in {"png", "jpg", "jpeg"}
                    and any(stem.startswith(model + "_")
                            for model in model_stems)):
                continue
            catalog.append(_catalog_item(stem, detail))
        catalog.sort(key=lambda item: (
            item["category"], item["display_name"].casefold()))
        return {"objects": objects, "avatars": _ls("avatars"),
                "object_details": details, "catalog": catalog,
                "catalog_categories": [
                    "seating", "beds", "surfaces", "pictures", "misc"]}

    @app.post("/api/models/import")
    async def import_object_model(request: Request,
                                  background_tasks: BackgroundTasks):
        """Install one bounded local catalog asset without placing it.

        The browser sends the chosen file as the raw request body. Validation
        and an atomic rename happen before the manifest can expose it; an
        existing asset is never overwritten implicitly.
        """
        raw_name = urllib.parse.unquote(
            request.headers.get("x-jnaiq-filename", "")).strip()
        category = request.headers.get(
            "x-jnaiq-category", "misc").strip().lower()
        if category not in OBJECT_CATALOG_CATEGORIES:
            return JSONResponse(status_code=400, content={
                "error": "category must be seating, beds, surfaces, "
                         "pictures, or misc"})
        original = os.path.basename(raw_name)
        stem, ext = os.path.splitext(original)
        ext = ext.lower()
        if ext not in {".glb", ".png", ".jpg", ".jpeg"}:
            return JSONResponse(status_code=400, content={
                "error": "import supports GLB, PNG, JPG, or JPEG files"})
        safe_stem = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
        if not safe_stem:
            return JSONResponse(status_code=400, content={
                "error": "the file needs a usable name"})
        declared = request.headers.get("content-length")
        try:
            if declared and int(declared) > MAX_OBJECT_IMPORT_BYTES:
                return JSONResponse(status_code=413, content={
                    "error": "object import exceeds the 160 MB limit"})
        except ValueError:
            return JSONResponse(status_code=400, content={
                "error": "invalid Content-Length"})
        body = await request.body()
        if not body:
            return JSONResponse(status_code=400,
                                content={"error": "the file is empty"})
        if len(body) > MAX_OBJECT_IMPORT_BYTES:
            return JSONResponse(status_code=413, content={
                "error": "object import exceeds the 160 MB limit"})
        if ext == ".glb" and body[:4] != b"glTF":
            return JSONResponse(status_code=400, content={
                "error": "the GLB header is invalid"})
        if ext == ".png" and body[:8] != b"\x89PNG\r\n\x1a\n":
            return JSONResponse(status_code=400, content={
                "error": "the PNG header is invalid"})
        if ext in {".jpg", ".jpeg"} and body[:2] != b"\xff\xd8":
            return JSONResponse(status_code=400, content={
                "error": "the JPEG header is invalid"})

        import json
        import tempfile
        root = _object_asset_root()
        os.makedirs(root, exist_ok=True)
        target = os.path.join(root, safe_stem + ext)
        if os.path.exists(target):
            return JSONResponse(status_code=409, content={
                "error": f"an asset named '{safe_stem}' already exists"})
        fd, temporary = tempfile.mkstemp(
            prefix=".jnaiq_object_import_", suffix=ext, dir=root)
        inspection = None
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            if ext == ".glb":
                try:
                    inspection = inspect_glb(temporary)
                except BodyPackageError as exc:
                    return JSONResponse(status_code=400, content={
                        "error": f"GLB validation failed: {exc}"})
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

        display_name = stem.replace("_", " ").replace("-", " ").strip()
        display_name = " ".join(part.capitalize()
                                for part in display_name.split())
        sidecar = target + ".scenery.json"
        package = {
            "schema": "jnaiq-scenery-package-1",
            "asset": safe_stem,
            "metadata": {
                "category": category,
                "display_name": display_name or safe_stem,
                "imported_locally": True,
            },
            "stats": {
                "bytes": len(body),
                "sha256": (inspection or {}).get("asset", {}).get("sha256")
                or hashlib.sha256(body).hexdigest(),
                "meshes": int((inspection or {}).get(
                    "structure", {}).get("meshes", 0)),
            },
        }
        fd, temporary = tempfile.mkstemp(
            prefix=".jnaiq_object_metadata_", suffix=".json", dir=root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(package, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, sidecar)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        manifest = models_manifest()
        item = next((item for item in manifest["catalog"]
                     if item["kind"] == safe_stem), None)
        if ext == ".glb":
            background_tasks.add_task(_render_object_thumbnail, target)
        return {"ok": True, "catalog_item": item,
                "thumbnail_pending": ext == ".glb",
                "message": f"Imported {item['display_name']}"}

    @app.get("/api/avatar-bodies/{asset}/compatibility")
    def avatar_body_compatibility(asset: str):
        """Read a known avatar GLB's structure; never install or rewrite it."""
        filename = os.path.basename(asset)
        if filename != asset or not filename.casefold().endswith(".glb"):
            return JSONResponse(status_code=400, content={
                "error": "asset must be one GLB filename"})
        root = os.path.join(REPO, "godot-room", "assets", "avatars")
        path = os.path.join(root, filename)
        if not os.path.isfile(path):
            return JSONResponse(status_code=404, content={
                "error": f"no avatar asset '{filename}'"})
        try:
            return inspect_glb(path)
        except (BodyPackageError, OSError) as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})

    @app.get("/api/avatar-bodies")
    def avatar_body_assignments():
        """Describe current identity-bound bodies and the candidate policy.

        This is intentionally not a mutable assignment registry.  The live
        Godot resolver remains authoritative and candidates remain separate.
        """
        root = os.path.join(REPO, "godot-room", "assets", "avatars")
        try:
            assets = sorted(f for f in os.listdir(root)
                            if f.casefold().endswith(".glb"))
        except OSError:
            assets = []
        available = {asset.casefold(): asset for asset in assets}
        members = set()
        for room in app.state.rooms.values():
            members.update(str(name) for name in room.members)
        assignments = []
        for member in sorted(members, key=str.casefold):
            expected = member.casefold() + ".glb"
            current = available.get(expected)
            assignments.append({
                "member": member,
                "current_asset": current,
                "resolver": "identity_filename",
                "locked": True,
                "status": "current" if current else "renderer_fallback",
            })
        return {
            "assignments": assignments,
            "assets": assets,
            "candidate_policy": {
                "pilot_target": BODY_CANDIDATE_PILOT,
                "current_assignments_mutable": False,
                "candidate_install_enabled": False,
            },
        }

    @app.get("/api/avatar-bodies/candidates")
    def body_candidates():
        return {"candidates": list_candidates(
            _body_candidate_root(), BODY_CANDIDATE_PILOT),
            "pilot_target": BODY_CANDIDATE_PILOT,
            "install_enabled": False}

    @app.get("/api/avatar-bodies/builder/recipes")
    def body_builder_recipes():
        return {
            "schema": "jnaiq-body-builder/0.1",
            "body_family": "jnaiq-humanoid-01",
            "pilot_target": BODY_RECIPE_PILOT,
            "recipes": list_recipes(_body_recipe_root()),
            "install_enabled": False,
            "current_assignments_mutable": False,
        }

    @app.post("/api/avatar-bodies/builder/recipes")
    def create_body_builder_recipe(req: BodyRecipeReq):
        try:
            return save_recipe(_body_recipe_root(), req.model_dump())
        except BodyPackageError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})

    @app.get("/api/avatar-bodies/builder/recipes/{recipe_id}")
    def get_body_builder_recipe(recipe_id: str):
        try:
            return load_recipe(_body_recipe_root(), recipe_id)
        except BodyPackageError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.put("/api/avatar-bodies/builder/recipes/{recipe_id}")
    def revise_body_builder_recipe(recipe_id: str, req: BodyRecipeReq):
        try:
            return save_recipe(
                _body_recipe_root(), req.model_dump(), recipe_id)
        except BodyPackageError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})

    @app.post("/api/avatar-bodies/candidates")
    async def stage_body_candidate(request: Request, filename: str):
        """Stream one GLB into local quarantine and inspect it for Testy."""
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_CANDIDATE_BYTES:
                    return JSONResponse(status_code=413, content={
                        "error": "candidate exceeds 256 MiB limit"})
            except ValueError:
                return JSONResponse(status_code=400, content={
                    "error": "invalid Content-Length"})
        try:
            stager = CandidateStager(_body_candidate_root(), filename,
                                     BODY_CANDIDATE_PILOT)
        except (BodyPackageError, OSError) as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        try:
            async for chunk in request.stream():
                stager.write(chunk)
            return stager.finalize()
        except BodyPackageError as exc:
            stager.abort()
            message = str(exc)
            return JSONResponse(status_code=(413 if "exceeds" in message else 422),
                                content={"error": message})
        except Exception:
            stager.abort()
            return JSONResponse(status_code=500, content={
                "error": "candidate staging failed cleanly"})

    @app.get("/api/avatar-bodies/candidates/{candidate_id}/mapping")
    def candidate_mapping(candidate_id: str):
        try:
            return load_candidate(_body_candidate_root(), candidate_id,
                                  BODY_CANDIDATE_PILOT)
        except BodyPackageError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.post("/api/avatar-bodies/candidates/{candidate_id}/mapping")
    def save_body_mapping(candidate_id: str, req: BodyMappingReq):
        try:
            return save_candidate_mapping(
                _body_candidate_root(), candidate_id, BODY_CANDIDATE_PILOT,
                {"roles": req.roles or {},
                 "expressions": req.expressions or {},
                 "optical_origin": req.optical_origin or {}})
        except BodyPackageError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})

    @app.get("/api/avatar-bodies/candidates/{candidate_id}/model")
    def candidate_preview_model(candidate_id: str):
        """Serve one settled quarantine GLB to the sealed preview only."""
        try:
            path = candidate_model_path(
                _body_candidate_root(), candidate_id, BODY_CANDIDATE_PILOT)
        except BodyPackageError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        return FileResponse(path, media_type="model/gltf-binary",
                            filename="candidate.glb")

    @app.post("/api/avatar-bodies/candidates/{candidate_id}/preview-receipts")
    def body_preview_receipt(candidate_id: str, req: BodyPreviewReceiptReq):
        try:
            return append_preview_receipt(
                _body_candidate_root(), candidate_id, BODY_CANDIDATE_PILOT,
                req.model_dump())
        except BodyPackageError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})

    @app.get("/api/avatar-bodies/candidates/{candidate_id}/preview.png")
    def body_preview_image(candidate_id: str):
        try:
            candidate_model_path(
                _body_candidate_root(), candidate_id, BODY_CANDIDATE_PILOT)
            directory = os.path.join(_body_candidate_root(), candidate_id)
            path = os.path.join(directory, "preview.png")
            if not os.path.isfile(path):
                raise BodyPackageError("candidate has no settled preview frame")
        except BodyPackageError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        return FileResponse(path, media_type="image/png")

    @app.get("/api/avatar-bodies/candidates/{candidate_id}/preview-pov.png")
    def body_preview_pov_image(candidate_id: str):
        try:
            candidate_model_path(
                _body_candidate_root(), candidate_id, BODY_CANDIDATE_PILOT)
            directory = os.path.join(_body_candidate_root(), candidate_id)
            path = os.path.join(directory, "preview_pov.png")
            if not os.path.isfile(path):
                raise BodyPackageError("candidate has no settled POV frame")
        except BodyPackageError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        return FileResponse(path, media_type="image/png")

    @app.get("/body-workshop")
    def body_workshop():
        """The read-only compatibility workshop; candidate work starts here."""
        path = os.path.join(REPO, "room", "body_workshop.html")
        if not os.path.isfile(path):
            return JSONResponse(status_code=404, content={
                "error": "body workshop is not installed"})
        return FileResponse(path, media_type="text/html")

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

    @app.post("/tuning")
    async def update_tuning(request: Request):
        """Validate and persist only dials the running room applies live."""
        import json
        import tempfile
        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse(status_code=400,
                                content={"error": "tuning must be an object"})
        ranges = {
            "ambient_energy": (0.0, 0.5),
            "crown_energy": (0.0, 3.0),
            "lamp_energy": (0.0, 3.0),
            "lamp_range_f": (0.0, 1.5),
            "glow_intensity": (0.0, 2.0),
            "mural_emit": (0.0, 1.0),
            "hour_override": (-1.0, 24.0),
        }
        updates = {}
        try:
            for key, (low, high) in ranges.items():
                if key in payload:
                    value = float(payload[key])
                    if not low <= value <= high:
                        raise ValueError(f"{key} is outside {low}-{high}")
                    updates[key] = round(value, 3)
            if "weather" in payload:
                weather = str(payload["weather"]).lower()
                if weather not in {"clear", "cloudy", "rain", "storm"}:
                    raise ValueError("weather is not recognized")
                updates["weather"] = weather
            if "rain_inside" in payload:
                if not isinstance(payload["rain_inside"], bool):
                    raise ValueError("rain_inside must be true or false")
                updates["rain_inside"] = payload["rain_inside"]
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        if not updates:
            return JSONResponse(status_code=400,
                                content={"error": "no live tuning values supplied"})

        path = os.path.join(REPO, "room_tuning.json")
        try:
            current = {}
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    current = json.load(f)
            current.update(updates)
            fd, temporary = tempfile.mkstemp(
                prefix="room_tuning_", suffix=".json", dir=REPO)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(current, f, indent=2)
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except Exception:
            return JSONResponse(status_code=500,
                                content={"error": "room tuning did not save"})
        return current

    # The 3D window, browser edition: godot-room's web export served
    # at /3d. Soft-skip when no export exists -- the host never
    # breaks on a machine that hasn't exported yet.
    web_dir = os.path.join(REPO, "godot-room", "export", "web")
    if os.path.isdir(web_dir):
        app.mount("/3d", StaticFiles(directory=web_dir, html=True))
        print("[room host] 3D web export mounted at /3d")

    terrain_canary_dir = os.path.join(
        REPO, "terrain3d-canary", "export", "web")
    if os.path.isdir(terrain_canary_dir):
        app.mount(
            "/terrain-canary",
            StaticFiles(directory=terrain_canary_dir, html=True))
        print("[room host] Terrain3D canary mounted at /terrain-canary")

    # runtime art: models served straight from the assets folders --
    # the 3D client fetches these at load instead of packing them
    # into the export. The folder IS the asset pipeline now.
    for prefix, sub in (("/models", "objects"), ("/avatars", "avatars")):
        d = (_object_asset_root() if sub == "objects" else
             os.path.join(REPO, "godot-room", "assets", sub))
        if os.path.isdir(d):
            app.mount(prefix, StaticFiles(directory=d))
    thumbnail_dir = _object_thumbnail_root()
    os.makedirs(thumbnail_dir, exist_ok=True)
    app.mount("/model-thumbnails", StaticFiles(directory=thumbnail_dir))

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
