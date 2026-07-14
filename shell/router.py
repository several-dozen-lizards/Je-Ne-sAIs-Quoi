"""shell/router.py — launcher + router for N personas (REQUIREMENTS.md §2.3,
§8 step 6). Discovers model_persona tenants from personas/*/roster.yaml,
launches each as its own OS subprocess (a cockpit.py instance, its own
port), and gives callers one stable address per persona regardless of
which port that persona's process actually landed on.

Explicitly NOT the Room (§6) — no shared event bus, no cross-persona
awareness, no perception filters. Isolated processes plus a front door.
That's next; this is the step before it.

human_persona / user (§2.2b) are discovered and listed but never launched
here — reserved shapes, nothing populates them yet.

Run:  python shell/router.py [--port 8700]
Then: GET  /                              -> status page, links to each
           persona's own cockpit UI (not a unified chat page yet)
      GET  /api/personas                  -> registry + live status
      GET  /api/personas/{id}/state       -> proxied to that persona
      POST /api/personas/{id}/turn        -> proxied to that persona
"""
import argparse
import atexit
import glob
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Launched as `python shell\router.py`, sys.path[0] is shell\ itself —
# project-local imports (shell.factory, harness.spec_loader) can't
# resolve without ROOT on the path. Same shim cockpit.py has carried
# since day one; router only started needing it when /api/models and
# /api/personas/create landed (first deferred project imports here).
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
PERSONAS_DIR = os.path.join(ROOT, "personas")
ASSET_DIR = os.path.join(ROOT, "assets", "jnsq")
MANIFEST_PATH = os.path.join(ROOT, "DISTRIBUTION_MANIFEST.json")
VERSION_PATH = os.path.join(ROOT, "VERSION")
PUBLIC_MANIFEST_URL = (
    "https://raw.githubusercontent.com/several-dozen-lizards/"
    "Je-Ne-sAIs-Quoi/main/DISTRIBUTION_MANIFEST.json")

# after the sys.path shim: importing env_store loads the gitignored .env
# into os.environ, so persona subprocesses launched below inherit any
# saved keys at spawn.
from shell import env_store  # noqa: E402
from shell.ui_themes import resolve_theme, save_theme  # noqa: E402
from shell.local_identity import load_local_identity  # noqa: E402
from shell.persona_media import (load_persona_avatar, save_persona_avatar,
                                 write_roster_mapping_scalar,
                                 write_roster_scalar)  # noqa: E402


class TurnRequest(BaseModel):
    message: str
    speaker: str = None
    images: list[dict] = Field(default_factory=list)


class StartRequest(BaseModel):
    model: str = None      # None -> roster's first entry (the primary)


class CreateRequest(BaseModel):
    name: str                  # spaces/caps OK; factory derives the slug
    display_name: str = None   # pretty name (defaults to name as typed)
    model: str = "llama3-1-8b"
    organs: str = "local"     # local needs no remote judge/API key


class PersonaIconRequest(BaseModel):
    icon: str


class PersonaAvatarRequest(BaseModel):
    data_url: str


class VisionRouteRequest(BaseModel):
    model: str | None = None  # null disables fallback; direct vision still works


class ModelCreateRequest(BaseModel):
    name: str
    family: str               # ollama | anthropic | openai_compat
    endpoint: str
    window_tokens: int = None
    base_url: str = None      # openai_compat only: http://host:port/v1
    api_key_env: str = None   # openai_compat: env var NAME, never a value


class ModelDiscoverRequest(BaseModel):
    family: str               # same transport families as model creation
    base_url: str = None      # openai_compat only
    api_key_env: str = None   # env var NAME only; value never crosses API


class ExileRequest(BaseModel):
    confirm_name: str          # must equal the persona id EXACTLY


class VoiceRequest(BaseModel):
    identity: str = None       # who_i_am/identity.txt
    organ_config: str = None   # body/memory_emotion/organ_config.json


class RosterEntryRequest(BaseModel):
    model: str                 # spec name from /api/models
    organs: str = "default"    # bare | default | full | comma list


class EnvKeyRequest(BaseModel):
    name: str                  # env var NAME (UPPER_SNAKE), e.g. OPENAI_API_KEY
    value: str                 # the secret — written to .env, NEVER echoed back


class SystemPromptRequest(BaseModel):
    text: str = ""             # empty/whitespace REVERTS to inherited baseline


class ThemeRequest(BaseModel):
    patch: dict
    reset: bool = False
    replace: bool = False


class UserRequest(BaseModel):
    username: str
    display_name: str = ""
    pronouns: str = ""
    public_profile: dict = Field(default_factory=dict)
    update: bool = False


class BedrockRequest(BaseModel):
    id: str = ""
    text: str
    category: str = "general"
    visibility: str = "private"
    groups: list = Field(default_factory=list)
    share_with: list = Field(default_factory=list)
    never_share_with: list = Field(default_factory=list)


class SharingGroupRequest(BaseModel):
    id: str
    name: str = ""
    access: str = "bounded"
    allow_categories: list = Field(default_factory=list)
    deny_categories: list = Field(default_factory=list)
    instructions: str = ""


class RelationshipRequest(BaseModel):
    user: str
    status: str = "neutral"
    groups: list = Field(default_factory=list)
    note: str = ""


class UserPersonaRequest(BaseModel):
    id: str = ""
    name: str
    description: str = ""
    preferences: str = ""
    boundaries: str = ""


def model_start_blocker(model: str):
    """Return a user-facing reason an installed model cannot start yet."""
    from harness.clients import model_auth_status
    from harness.spec_loader import load_spec
    auth = model_auth_status(load_spec(model))
    if auth["required"] and not auth["set"]:
        return (f"model '{model}' needs {auth['env']}, but it is not set. "
                f"Open Settings → API Keys, paste it there, then Start again.")
    return None


def _free_port() -> int:
    """Ask the OS for a genuinely free port. Small bind/close race window,
    but far more reliable than hand-picking — repeated WinError 10048 on
    guessed ports cost real time earlier today."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def discover_personas() -> dict:
    """Scan personas/*/roster.yaml — the roster IS the registry (par 1: no
    two sources of truth). Only model_persona is launchable right now;
    human_persona / user are recorded, not started (par 2.2b, reserved)."""
    registry = {}
    for roster_path in sorted(glob.glob(os.path.join(PERSONAS_DIR, "*", "roster.yaml"))):
        persona_dir = os.path.dirname(roster_path)
        pid = os.path.basename(persona_dir)
        with open(roster_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        kind = data.get("kind", "model_persona")  # pre-kind rosters default here
        avatar = load_persona_avatar(persona_dir)
        entry = {"id": pid, "kind": kind, "dir": persona_dir,
                 "display_name": data.get("display_name") or pid,
                 "icon": data.get("icon") or "",
                 "avatar": avatar}
        if kind == "model_persona":
            entries = data.get("entries") or []
            # current_model: the persisted vessel choice (top-level
            # scalar, written by set_current_model on a switched
            # start). Must name a roster entry — a stale/typo'd value
            # falls back to the primary rather than blocking the scan.
            cur = data.get("current_model")
            if cur and not any(e.get("model") == cur for e in entries):
                print(f"[router] {pid}: current_model '{cur}' not in "
                      f"roster entries — falling back to primary")
                cur = None
            entry["model"] = cur or (entries[0]["model"]
                                     if entries else None)
            entry["models"] = [e.get("model") for e in entries
                               if e.get("model")]  # switchable set (UI)
            id_file = os.path.join(persona_dir, "who_i_am", "identity.txt")
            entry["identity_file"] = id_file if os.path.exists(id_file) else None
            entry["room"] = data.get("room")  # constitutional: den + worm
            entry["max_tokens"] = data.get("max_tokens")  # reply ceiling
            entry["vision_model"] = ((data.get("perception") or {})
                                     .get("vision_model"))
        registry[pid] = entry
    return registry


def set_current_model(persona_dir: str, model: str) -> bool:
    """Persist the switched vessel as roster truth. House laws:
    text edit (never ruamel), validate-first, .prev kept, atomic
    replace — the env_store idiom. Replaces the current_model line
    in place or appends one at column 0; every other byte untouched."""
    path = os.path.join(persona_dir, "roster.yaml")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    new_line = f"current_model: {model}\n"
    out, replaced = [], False
    for ln in lines:
        if ln.startswith("current_model:"):
            out.append(new_line)
            replaced = True
        else:
            out.append(ln)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(new_line)
    text = "".join(out)
    try:  # validate-first: a write that would corrupt is REFUSED
        parsed = yaml.safe_load(text)
        if not isinstance(parsed, dict) \
                or parsed.get("current_model") != model:
            raise ValueError("round-trip mismatch")
    except Exception as e:
        print(f"[router] current_model write REFUSED ({e}); "
              f"roster untouched")
        return False
    with open(path + ".prev", "w", encoding="utf-8") as f:
        f.writelines(lines)
    tmp = path + ".tmp_curmodel"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def set_persona_icon(persona_dir: str, icon: str) -> str:
    """Persist one persona's display glyph in its roster entity record.

    This is presentation metadata, not a theme token: it follows the persona
    anywhere the household renders their name. The text edit preserves every
    unrelated roster byte, validates before replace, and keeps ``.prev``.
    """
    value = (icon or "").strip()
    if not value:
        raise ValueError("persona icon cannot be empty")
    if len(value) > 16:
        raise ValueError("persona icon must be 16 characters or fewer")
    return write_roster_scalar(persona_dir, "icon", value)


class PersonaProcess:
    def __init__(self, pid: str, model: str, identity_file,
                 room_cfg: dict = None, room_url: str = None,
                  max_tokens: int = None, speaker: str = None):
        self.id = pid
        self.model = model
        self.port = _free_port()
        cmd = [sys.executable, os.path.join(ROOT, "shell", "cockpit.py"),
               "--persona", pid, "--model", model, "--port", str(self.port)]
        if identity_file:
            cmd += ["--identity-file", identity_file]
        if max_tokens:
            cmd += ["--max-tokens", str(max_tokens)]
        if speaker:
            cmd += ["--speaker", speaker]
        # a body needs both the WHAT and the WHERE. The WHAT
        # (enabled_organs, room id, loop intervals) now lives in the
        # roster, which the COCKPIT reads itself (par 2.6, one source
        # of truth) — the router only supplies the WHERE, the runtime
        # room-host URL that changes every boot.
        if room_cfg and room_url:
            cmd += ["--room-url", room_url]
        logdir = os.path.join(ROOT, "logs")
        os.makedirs(logdir, exist_ok=True)
        self.log = open(os.path.join(logdir, f"cockpit_{pid}.log"), "a",
                        encoding="utf-8")
        self.log.write(f"\n=== spawn {time.strftime('%Y-%m-%d %H:%M:%S')} "
                       f"port {self.port} model {model} ===\n")
        self.log.flush()
        self.proc = subprocess.Popen(cmd, cwd=ROOT,
                                     stdout=self.log,
                                     stderr=subprocess.STDOUT)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def wait_ready(self, timeout: float = 25.0) -> bool:
        deadline = time.time() + timeout
        url = f"http://127.0.0.1:{self.port}/api/state"
        while time.time() < deadline:
            if not self.alive():
                return False
            try:
                urllib.request.urlopen(url, timeout=1)
                return True
            except Exception:
                time.sleep(0.3)
        return False

    def stop(self):
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def build_app(room_url: str = None) -> FastAPI:
    app = FastAPI(title="JNSQ shell/router")
    if os.path.isdir(ASSET_DIR):
        app.mount("/assets", StaticFiles(directory=ASSET_DIR),
                  name="jnsq-assets")
    app.state.registry = discover_personas()
    app.state.processes = {}
    app.state.room_url = room_url
    app.state.local_identity = load_local_identity(ROOT)

    @app.get("/api/ui/theme")
    def ui_theme():
        return resolve_theme(ROOT)

    @app.post("/api/ui/theme")
    def set_ui_theme(req: ThemeRequest):
        try:
            return save_theme(ROOT, "household", req.patch,
                              reset=req.reset, replace=req.replace)
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content={"error": str(e)})

    def launch_all():
        for pid, entry in app.state.registry.items():
            if entry["kind"] != "model_persona":
                continue
            proc = PersonaProcess(pid, entry["model"],
                                  entry.get("identity_file"),
                                  room_cfg=entry.get("room"),
                                  room_url=room_url,
                                  max_tokens=entry.get("max_tokens"),
                                  speaker=app.state.local_identity["display_name"])
            app.state.processes[pid] = proc
            ready = proc.wait_ready()
            print(f"[router] {pid} on {entry['model']} -> port {proc.port} "
                 f"({'ready' if ready else 'NOT RESPONDING'})")

    def shutdown_all():
        for proc in app.state.processes.values():
            proc.stop()

    app.state.launch_all = launch_all
    app.state.shutdown_all = shutdown_all
    atexit.register(shutdown_all)

    @app.get("/", response_class=HTMLResponse)
    def index():
        """The Je Ne sAIs Quoi: one door, every window. Tabs for each cockpit,
        the world viewer, and side-by-side — all iframes kept mounted
        so switching never reloads a conversation."""
        import json as _json
        cfg = {"personas": {}, "room_url": room_url or "",
               "local_identity": app.state.local_identity}
        for pid, entry in sorted(app.state.registry.items()):
            proc = app.state.processes.get(pid)
            if proc and proc.alive():
                cfg["personas"][pid] = {
                    "url": f"http://127.0.0.1:{proc.port}/",
                    "model": entry.get("model", "")}
        with open(os.path.join(ROOT, "shell", "fangwall.html"),
                  encoding="utf-8") as f:
            page = f.read()
        return page.replace("/*CONFIG*/", _json.dumps(cfg))

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page():
        """Shared settings surface used by the public workspace.

        The page fetches mutable values from same-origin APIs; the injected
        object contains identity labels and room availability only, never a
        key value or persona interior.
        """
        import json as _json
        cfg = {"room_url": room_url or "",
               "local_identity": app.state.local_identity}
        with open(os.path.join(ROOT, "shell", "settings.html"),
                  encoding="utf-8") as f:
            page = f.read()
        return page.replace("/*CONFIG*/", _json.dumps(cfg))

    def installed_version() -> str:
        try:
            if os.path.exists(MANIFEST_PATH):
                with open(MANIFEST_PATH, encoding="utf-8") as f:
                    value = json.load(f).get("version")
                if value:
                    return str(value)
            with open(VERSION_PATH, encoding="utf-8") as f:
                return f.read().strip() or "development"
        except (OSError, ValueError, TypeError):
            return "development"

    @app.get("/api/version")
    def version_info():
        return {"version": installed_version(),
                "updater": os.path.exists(os.path.join(ROOT,
                                                        "UPDATE_JNSQ.bat"))}

    @app.get("/api/version/check")
    def version_check():
        """User-invoked remote check; applying remains an offline act.

        JNSQ must be stopped before engine files change, so this endpoint
        reports availability only. UPDATE_JNSQ.bat owns the validated patch.
        """
        request = urllib.request.Request(
            PUBLIC_MANIFEST_URL,
            headers={"User-Agent": "JNSQ-Version-Check",
                     "Cache-Control": "no-cache"})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                remote = json.loads(response.read().decode("utf-8"))
            latest = str(remote.get("version") or "")
            if not latest:
                raise ValueError("GitHub manifest has no version")
            current = installed_version()
            return {"version": current, "latest": latest,
                    "update_available": current != latest}
        except Exception as error:
            return JSONResponse(status_code=502,
                                content={"error": f"update check failed: {error}"})

    @app.get("/users", response_class=HTMLResponse)
    def users_page():
        with open(os.path.join(ROOT, "shell", "users.html"),
                  encoding="utf-8") as f:
            return f.read()

    @app.get("/api/users")
    def users_list():
        from core.users import list_users
        return {"users": list(list_users(ROOT).values())}

    @app.post("/api/users")
    def users_upsert(req: UserRequest):
        from core.users import upsert_user
        try:
            account = upsert_user(
                ROOT, username=req.username, display_name=req.display_name,
                pronouns=req.pronouns, public_profile=req.public_profile,
                update=req.update)
            return {"ok": True, "account": account}
        except FileExistsError as e:
            return JSONResponse(status_code=409, content={"error": str(e)})
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.get("/api/users/{uid}")
    def user_detail(uid: str):
        from core.users import get_user
        try:
            user = get_user(ROOT, uid)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        if not user:
            return JSONResponse(status_code=404,
                                content={"error": f"no user '{uid}'"})
        return user

    @app.post("/api/users/{uid}/bedrock")
    def user_bedrock(uid: str, req: BedrockRequest):
        from core.users import put_bedrock_fact
        try:
            fact = put_bedrock_fact(
                ROOT, uid, fact_id=req.id, text=req.text,
                category=req.category, visibility=req.visibility,
                groups=req.groups, share_with=req.share_with,
                never_share_with=req.never_share_with)
            return {"ok": True, "fact": fact}
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.post("/api/users/{uid}/bedrock/import-legacy")
    def user_bedrock_import_legacy(uid: str):
        from core.users import import_legacy_bedrock
        try:
            result = import_legacy_bedrock(ROOT, uid)
            return {"ok": True, **result}
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})

    @app.delete("/api/users/{uid}/bedrock/{fact_id}")
    def user_bedrock_delete(uid: str, fact_id: str):
        from core.users import delete_bedrock_fact
        try:
            removed = delete_bedrock_fact(ROOT, uid, fact_id)
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        if not removed:
            return JSONResponse(status_code=404,
                                content={"error": f"no fact '{fact_id}'"})
        return {"ok": True}

    @app.post("/api/users/{uid}/groups")
    def user_group(uid: str, req: SharingGroupRequest):
        from core.users import put_group
        try:
            group = put_group(
                ROOT, uid, group_id=req.id, name=req.name,
                access=req.access, allow_categories=req.allow_categories,
                deny_categories=req.deny_categories,
                instructions=req.instructions)
            return {"ok": True, "group": group}
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.post("/api/users/{uid}/relationships")
    def user_relationship(uid: str, req: RelationshipRequest):
        from core.users import put_relationship
        try:
            relation = put_relationship(
                ROOT, uid, req.user, status=req.status,
                groups=req.groups, note=req.note)
            return {"ok": True, "relationship": relation}
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.post("/api/users/{uid}/personas")
    def user_persona(uid: str, req: UserPersonaRequest):
        from core.users import put_user_persona
        try:
            persona = put_user_persona(
                ROOT, uid, persona_id=req.id, name=req.name,
                description=req.description, preferences=req.preferences,
                boundaries=req.boundaries)
            return {"ok": True, "persona": persona}
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.get("/status", response_class=HTMLResponse)
    def status_table():
        rows = []
        for pid, entry in sorted(app.state.registry.items()):
            proc = app.state.processes.get(pid)
            if entry["kind"] != "model_persona":
                status, link = f"reserved ({entry['kind']}, not launched)", "—"
            elif proc is None:
                status, link = "not launched", "—"
            elif not proc.alive():
                status, link = "DEAD", "—"
            else:
                status = f"running on :{proc.port}"
                link = f'<a href="http://127.0.0.1:{proc.port}/">open cockpit</a>'
            rows.append(f"<tr><td>{pid}</td><td>{entry['kind']}</td>"
                       f"<td>{entry.get('model','—')}</td>"
                       f"<td>{status}</td><td>{link}</td></tr>")
        return ("<html><body style='font-family:monospace;background:#111;"
               "color:#eee;padding:2rem'><h2>JNSQ shell/router</h2>"
               "<table border=1 cellpadding=8 style='border-color:#444'>"
               "<tr><th>persona</th><th>kind</th><th>model</th>"
               "<th>status</th><th>link</th></tr>" + "".join(rows) +
               "</table></body></html>")

    @app.get("/api/personas")
    def list_personas():
        # re-discover every call: factory-born personas appear without
        # a router restart (the roster scan is cheap; staleness isn't)
        app.state.registry = discover_personas()
        out = {}
        for pid, entry in app.state.registry.items():
            proc = app.state.processes.get(pid)
            out[pid] = {
                "kind": entry["kind"],
                "display_name": entry.get("display_name") or pid,
                "icon": entry.get("icon") or "",
                "avatar_url": (f"/api/personas/{pid}/avatar?v="
                               f"{entry['avatar']['version']}"
                               if entry.get("avatar") else ""),
                "model": (proc.model if proc and proc.alive()
                          else entry.get("model")),
                "models": entry.get("models") or [],
                "vision_model": entry.get("vision_model"),
                "has_room": bool(entry.get("room")),
                "port": proc.port if proc else None,
                "alive": proc.alive() if proc else False,
            }
        return out

    @app.post("/api/personas/{pid}/icon")
    def persona_icon(pid: str, req: PersonaIconRequest):
        app.state.registry = discover_personas()
        entry = app.state.registry.get(pid)
        if not entry:
            return JSONResponse(status_code=404,
                                content={"error": f"no persona '{pid}'"})
        try:
            icon = set_persona_icon(entry["dir"], req.icon)
        except (OSError, ValueError) as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        app.state.registry = discover_personas()
        return {"ok": True, "persona": pid, "icon": icon}

    @app.get("/api/personas/{pid}/avatar")
    def persona_avatar_file(pid: str):
        app.state.registry = discover_personas()
        entry = app.state.registry.get(pid)
        avatar = entry.get("avatar") if entry else None
        if not avatar:
            return JSONResponse(status_code=404,
                                content={"error": "persona has no avatar"})
        return FileResponse(
            avatar["path"], media_type=avatar["mime"],
            headers={"X-Content-Type-Options": "nosniff",
                     "Cache-Control": "no-cache"})

    @app.post("/api/personas/{pid}/avatar")
    def persona_avatar_save(pid: str, req: PersonaAvatarRequest):
        app.state.registry = discover_personas()
        entry = app.state.registry.get(pid)
        if not entry:
            return JSONResponse(status_code=404,
                                content={"error": f"no persona '{pid}'"})
        try:
            save_persona_avatar(entry["dir"], req.data_url)
        except (OSError, ValueError) as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)})
        app.state.registry = discover_personas()
        avatar = app.state.registry[pid]["avatar"]
        return {"ok": True, "persona": pid,
                "avatar_url": (f"/api/personas/{pid}/avatar?v="
                               f"{avatar['version']}")}

    @app.post("/api/personas/{pid}/vision")
    def persona_vision_route(pid: str, req: VisionRouteRequest):
        """Declare the fallback visual vessel for one persona.

        Active models marked vision-capable still receive pixels directly;
        this route is consulted only when the active vessel is text-only.
        """
        app.state.registry = discover_personas()
        entry = app.state.registry.get(pid)
        if not entry or entry.get("kind") != "model_persona":
            return JSONResponse(status_code=404,
                                content={"error": f"no model persona '{pid}'"})
        model = (req.model or "").strip() or None
        if model:
            try:
                from harness.spec_loader import load_spec
                spec = load_spec(model)
            except Exception as error:
                return JSONResponse(status_code=400,
                                    content={"error": str(error)})
            if not (spec.get("capabilities") or {}).get("vision"):
                return JSONResponse(status_code=400, content={
                    "error": f"'{model}' is not declared vision-capable"})
        try:
            write_roster_mapping_scalar(entry["dir"], "perception",
                                        "vision_model", model)
        except (OSError, ValueError) as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)})
        was_running = bool(app.state.processes.get(pid)
                           and app.state.processes[pid].alive())
        app.state.registry = discover_personas()
        return {"ok": True, "persona": pid, "vision_model": model,
                "restart_required": was_running}

    @app.post("/api/personas/{pid}/start")
    def persona_start(pid: str, req: StartRequest = None):
        """Start (or restart-with-a-different-model) one persona.
        Model switching IS stop+start: the cockpit re-reads the roster
        entry for the requested model, so the right organ set comes up
        with it (par 2.6 — configuration follows the roster)."""
        app.state.registry = discover_personas()
        entry = app.state.registry.get(pid)
        if entry is None or entry["kind"] != "model_persona":
            return JSONResponse(status_code=404, content={
                "error": f"no launchable persona '{pid}'"})
        old = app.state.processes.get(pid)
        requested = req.model if req and req.model else None
        if requested is None and old and old.alive():
            requested = old.model  # NO COERCION: a model-less start
            # keeps the running vessel — it must never silently
            # revert a switched persona to the roster primary
            # (the 2026-07-11 fangwall revert bug)
        model = requested or entry["model"]
        if entry.get("models") and model not in entry["models"]:
            return JSONResponse(status_code=400, content={
                "error": f"'{model}' is not in {pid}'s roster "
                         f"({entry['models']}) — add an entry first"})
        try:
            blocked = model_start_blocker(model)
        except Exception as e:
            return JSONResponse(status_code=400, content={
                "error": f"cannot start model '{model}': {e}"})
        if blocked:
            return JSONResponse(status_code=400, content={"error": blocked})
        if old and old.alive():
            if old.model == model:
                return {"id": pid, "model": model, "port": old.port,
                        "alive": True, "note": "already running"}
            old.stop()
        proc = PersonaProcess(pid, model, entry.get("identity_file"),
                              room_cfg=entry.get("room"),
                              room_url=app.state.room_url,
                              max_tokens=entry.get("max_tokens"),
                              speaker=app.state.local_identity["display_name"])
        app.state.processes[pid] = proc
        ready = proc.wait_ready()
        # a switched start becomes roster truth: survives restarts,
        # router boots, and the fangwall's own re-renders
        if model != entry["model"]:
            if set_current_model(entry["dir"], model):
                app.state.registry = discover_personas()
        return {"id": pid, "model": model, "port": proc.port,
                "alive": proc.alive(), "ready": ready}

    @app.post("/api/personas/{pid}/stop")
    def persona_stop(pid: str):
        proc = app.state.processes.get(pid)
        if proc is None or not proc.alive():
            return {"id": pid, "alive": False, "note": "not running"}
        proc.stop()
        return {"id": pid, "alive": proc.alive()}

    @app.post("/api/personas/create")
    def persona_create(req: CreateRequest):
        """The factory, one button away. Scaffolds only — starting is
        a separate, deliberate act (give them a voice first)."""
        from shell.factory import scaffold
        try:
            m = scaffold(req.name, model=req.model, organs=req.organs,
                         display_name=req.display_name)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        app.state.registry = discover_personas()
        return m

    @app.post("/api/personas/{pid}/export")
    def persona_export(pid: str):
        """Zip the whole persona to exports/ — safe while running
        (append-only logs may straddle the snapshot; the zip is still
        valid). A receipt, never a mutation."""
        from shell.factory import export_persona
        try:
            return export_persona(pid)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.post("/api/personas/{pid}/exile")
    def persona_exile(pid: str, req: ExileRequest):
        """'Delete' as the API knows it: auto-export, then move to the
        graveyard. TWO walls here (stopped-first, typed exact name) and
        a third by construction — this endpoint CANNOT destroy bytes.
        Purge exists only at the factory CLI, behind a typed DESTROY.
        Alive -> gone is always two acts in two contexts."""
        if req.confirm_name != pid:
            return JSONResponse(status_code=400, content={
                "error": f"confirmation mismatch: typed "
                         f"'{req.confirm_name}', persona is '{pid}' — "
                         f"nothing was touched"})
        proc = app.state.processes.get(pid)
        if proc and proc.alive():
            return JSONResponse(status_code=409, content={
                "error": f"'{pid}' is RUNNING — stop it first. The "
                         f"graveyard does not take the living."})
        from shell.factory import exile_persona
        try:
            r = exile_persona(pid)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        app.state.processes.pop(pid, None)
        app.state.registry = discover_personas()
        return r

    @app.get("/api/personas/{pid}/voice")
    def persona_voice_get(pid: str):
        """The voice editor's read side: identity.txt + organ_config
        as text. Works on stopped personas — that's the Egg Law's
        whole point (voice BEFORE first start)."""
        from shell.factory import read_voice
        try:
            out = read_voice(pid)
        except Exception as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        proc = app.state.processes.get(pid)
        out["running"] = bool(proc and proc.alive())
        return out

    @app.post("/api/personas/{pid}/voice")
    def persona_voice_save(pid: str, req: VoiceRequest):
        """Save side. VALIDATE-FIRST lives in the factory: bad JSON or
        an empty identity is a 400 and NOTHING is written. Each saved
        file keeps a .prev. Running personas pick edits up at next
        Start."""
        from shell.factory import write_voice
        try:
            return write_voice(pid, identity=req.identity,
                               organ_config=req.organ_config)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.post("/api/personas/{pid}/roster")
    def persona_roster_add(pid: str, req: RosterEntryRequest):
        """Append a model entry to the roster — append-only, byte
        exact: existing lines are never rewritten, validate-after
        self-reverts on any surprise. The dropdown repopulates on the
        next /api/personas (re-discovery reads the roster fresh)."""
        from shell.factory import add_roster_entry
        try:
            r = add_roster_entry(pid, req.model, organs=req.organs)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        app.state.registry = discover_personas()
        return r

    @app.get("/api/models")
    def list_models():
        """The spec registry reading itself: every specs/models/*.yaml
        is a dropdown entry. Reports whether the Anthropic key is SET
        (presence only — values never cross this API)."""
        from harness.spec_loader import load_all
        models = []
        for spec in load_all():
            ident = spec.get("identity") or {}
            capabilities = spec.get("capabilities") or {}
            runtime = spec.get("runtime") or {}
            base_url = ident.get("base_url") or ""
            if "api.z.ai" in base_url:
                vendor = "Z.AI"
            elif "api.openai.com" in base_url:
                vendor = "OpenAI"
            elif ident.get("provider") == "anthropic_api" \
                    or ident.get("family") == "anthropic":
                vendor = "Anthropic"
            elif ident.get("locality") == "local":
                vendor = "local"
            else:
                vendor = ident.get("provider") or ident.get("family")
            key_env = ident.get("api_key_env")
            if not key_env and (ident.get("family") == "anthropic"
                                or ident.get("provider") == "anthropic_api"):
                key_env = "ANTHROPIC_API_KEY"
            if key_env == "ANTHROPIC_API_KEY":
                try:
                    from harness.clients import resolve_anthropic_key
                    available = bool(resolve_anthropic_key())
                except Exception:
                    available = False
            else:
                available = (ident.get("locality") == "local"
                             or not key_env or bool(os.environ.get(key_env)))
            models.append({
                "name": ident.get("name"),
                "family": ident.get("family"),
                "provider": ident.get("provider"),
                "vendor": vendor,
                "locality": ident.get("locality"),
                "endpoint": ident.get("endpoint"),
                "base_url": base_url or None,
                "api_key_env": ident.get("api_key_env"),
                "vision": bool(capabilities.get("vision")),
                "cost": runtime.get("cost") or "not documented in this spec",
                "latency": runtime.get("latency_class") or "unknown",
                "key_env": key_env,
                "available": available,
            })
        try:
            from harness.clients import resolve_anthropic_key
            resolve_anthropic_key()
            key_set = True
        except Exception:
            key_set = False
        return {"models": models, "anthropic_key_set": key_set}

    @app.post("/api/models/{model}/vision/test")
    def model_vision_test(model: str):
        """Send JNSQ's public icon through one declared visual vessel.

        This endpoint is never automatic: the Settings button is the explicit
        act that may incur a provider charge. No persona or user image is used.
        """
        try:
            import base64
            from adapters.family_adapters import adapter_for
            from harness.spec_loader import load_spec
            spec = load_spec(model)
            if not (spec.get("capabilities") or {}).get("vision"):
                raise ValueError(f"'{model}' is not declared vision-capable")
            icon_path = os.path.join(ASSET_DIR, "favicon-48.png")
            with open(icon_path, "rb") as handle:
                encoded = base64.b64encode(handle.read()).decode("ascii")
            client = adapter_for(spec).client
            observation = (client.chat(
                "Report observable visual features only. Do not infer emotion, intent, or symbolism.",
                "Describe this public JNSQ test icon in one short sentence.",
                max_tokens=420, temperature=0.0,
                images=[{"media_type": "image/png", "data": encoded,
                         "detail": "low"}]) or "").strip()
            if not observation:
                raise RuntimeError("the model returned no observation text")
            return {"ok": True, "model": model,
                    "observation": observation[:500]}
        except Exception as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)})

    @app.post("/api/models/create")
    def model_create(req: ModelCreateRequest):
        from shell.factory import scaffold_model_spec
        try:
            return scaffold_model_spec(req.name, req.family,
                                       req.endpoint, req.window_tokens,
                                       base_url=req.base_url,
                                       api_key_env=req.api_key_env)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.post("/api/models/discover")
    def model_discover(req: ModelDiscoverRequest):
        """Ask a provider's model-list endpoint what this installation can
        access. Credentials stay server-side; only model IDs come back.
        Manual endpoint entry remains available when a provider has no list."""
        from shell.model_catalog import discover_models
        try:
            return discover_models(req.family, base_url=req.base_url,
                                   api_key_env=req.api_key_env)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.get("/api/env")
    def list_env_keys():
        """Which env-var keys the installed specs NEED and whether each
        is SET — PRESENCE ONLY, values never cross this API. Powers the
        Keys panel. A key is 'optional' only if EVERY model using it is a
        local (no-auth) openai_compat server."""
        from harness.spec_loader import load_all
        needed = {}
        for spec in load_all():
            ident = spec.get("identity") or {}
            fam = ident.get("family")
            provider = ident.get("provider")
            if fam == "anthropic" or provider == "anthropic_api":
                name, optional = "ANTHROPIC_API_KEY", False
            elif fam == "openai_chat" or provider == "openai_compat":
                name = ident.get("api_key_env") or "OPENAI_API_KEY"
                optional = ident.get("locality") == "local"
            else:
                continue  # ollama / local: no key
            slot = needed.setdefault(name, {"optional": True, "used_by": []})
            slot["used_by"].append(ident.get("name"))
            slot["optional"] = slot["optional"] and optional
        keys = [{"env": n, "set": bool(os.environ.get(n)),
                 "optional": v["optional"], "used_by": v["used_by"]}
                for n, v in sorted(needed.items())]
        return {"keys": keys}

    @app.post("/api/env")
    def set_env_key(req: EnvKeyRequest):
        """VALIDATE-FIRST write of a key VALUE into the gitignored .env,
        live in this process at once. Personas already running pick it up
        at their next Start. Response is PRESENCE ONLY — the value is
        never echoed or logged."""
        try:
            return env_store.set_key(req.name, req.value)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.get("/api/models/{model}/system_prompt")
    def get_system_prompt(model: str):
        """The MODEL-scoped operational prompt: the model's own override
        text (null if inherited), what actually resolves, and the source
        (model / family / default / none) so the UI is honest about
        inheritance. Shared by every persona on this model."""
        from shell import system_prompts
        from harness.spec_loader import load_spec
        try:
            fam = (load_spec(model).get("identity") or {}).get("family")
        except Exception:
            fam = None
        return system_prompts.read(model, fam)

    @app.post("/api/models/{model}/system_prompt")
    def set_system_prompt(model: str, req: SystemPromptRequest):
        """VALIDATE-FIRST write of the model's system prompt (keeps a
        .prev; empty text reverts to the inherited baseline). Applies to
        any persona on this model at its next Start."""
        from shell import system_prompts
        try:
            return system_prompts.write(model, req.text)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.get("/api/models/{model}/organ_prompts")
    def get_organ_prompts(model: str):
        """Every organ's instruction fragment for <model> (own / resolved
        / source) + its registry desc for labels. These compose onto the
        base system prompt when a persona has that organ ON; descriptive
        organs simply carry empty fragments."""
        from shell import system_prompts
        from harness.spec_loader import load_spec
        from core.organs import REGISTRY
        try:
            fam = (load_spec(model).get("identity") or {}).get("family")
        except Exception:
            fam = None
        organs = []
        for oid, od in REGISTRY.items():
            r = system_prompts.read_organ(model, oid, fam)
            r["desc"] = od.desc
            organs.append(r)
        return {"model": model, "organs": organs}

    @app.post("/api/models/{model}/organs/{organ}/system_prompt")
    def set_organ_prompt(model: str, organ: str, req: SystemPromptRequest):
        """VALIDATE-FIRST write of one organ's fragment for <model>
        (.prev kept; empty reverts to inherited). Applies to a persona
        with that organ ON at next Start."""
        from shell import system_prompts
        try:
            return system_prompts.write_organ(model, organ, req.text)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    def _proxy(pid: str, path: str, payload=None, timeout=30):
        proc = app.state.processes.get(pid)
        if proc is None or not proc.alive():
            return JSONResponse(status_code=503, content={
                "error": f"persona '{pid}' not running"})
        url = f"http://127.0.0.1:{proc.port}{path}"
        try:
            if payload is None:
                r = urllib.request.urlopen(url, timeout=timeout)
            else:
                rq = urllib.request.Request(
                    url, data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST")
                r = urllib.request.urlopen(rq, timeout=timeout)
            return JSONResponse(status_code=r.status,
                                content=json.loads(r.read()))
        except urllib.error.HTTPError as e:
            return JSONResponse(status_code=e.code,
                                content=json.loads(e.read()))

    @app.get("/api/personas/{pid}/organs")
    def persona_organs(pid: str):
        """Proxy to the tenant's organs endpoint — the Je Ne sAIs Quoi's JS is
        same-origin with the ROUTER, not the tenants, so world-membership
        toggles ride through here."""
        return _proxy(pid, "/api/organs")

    @app.post("/api/personas/{pid}/organs")
    def persona_set_organs(pid: str, req: dict):
        return _proxy(pid, "/api/organs", payload=req)

    @app.get("/api/personas/{pid}/state")
    def persona_state(pid: str):
        proc = app.state.processes.get(pid)
        if proc is None or not proc.alive():
            return JSONResponse(status_code=503, content={"error": f"persona '{pid}' not running"})
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{proc.port}/api/state", timeout=30)
            return JSONResponse(status_code=r.status, content=json.loads(r.read()))
        except urllib.error.HTTPError as e:
            return JSONResponse(status_code=e.code, content=json.loads(e.read()))

    @app.post("/api/personas/{pid}/turn")
    def persona_turn(pid: str, req: TurnRequest):
        proc = app.state.processes.get(pid)
        if proc is None or not proc.alive():
            return JSONResponse(status_code=503, content={"error": f"persona '{pid}' not running"})
        try:
            body = json.dumps({"message": req.message,
                               "speaker": req.speaker or app.state.local_identity[
                                   "display_name"],
                               "images": req.images}).encode()
            r2 = urllib.request.Request(f"http://127.0.0.1:{proc.port}/api/turn", data=body,
                                        headers={"Content-Type": "application/json"}, method="POST")
            r3 = urllib.request.urlopen(r2, timeout=90)
            return JSONResponse(status_code=r3.status, content=json.loads(r3.read()))
        except urllib.error.HTTPError as e:
            return JSONResponse(status_code=e.code, content=json.loads(e.read()))

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8700)
    ap.add_argument("--room-url", default=None,
                    help="room host base url; tenants whose roster "
                         "declares a room get bodies there")
    args = ap.parse_args()

    app = build_app(room_url=args.room_url)
    app.state.launch_all()

    import uvicorn
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        app.state.shutdown_all()


if __name__ == "__main__":
    main()
