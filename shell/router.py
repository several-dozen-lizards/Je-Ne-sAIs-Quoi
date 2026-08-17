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
import concurrent.futures
import glob
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
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


def semantic_public_version(value: str):
    """Return a comparable public x.y.z tuple, or None for dev labels."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(value or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def public_update_available(installed: str, latest: str) -> bool:
    """A different version is not necessarily an upgrade."""
    current = semantic_public_version(installed)
    remote = semantic_public_version(latest)
    return bool(current is not None and remote is not None and remote > current)

# after the sys.path shim: importing env_store loads the gitignored .env
# into os.environ, so persona subprocesses launched below inherit any
# saved keys at spawn.
from shell import env_store  # noqa: E402
from shell.ui_themes import (delete_custom_preset, resolve_theme,
                             save_custom_preset, save_theme)  # noqa: E402
from shell.local_identity import load_local_identity, save_local_identity  # noqa: E402
from shell.ui_background import (delete_conversation_background,
                                  load_conversation_background,
                                  save_conversation_background)  # noqa: E402
from shell.persona_media import (load_persona_avatar, save_persona_avatar,
                                 write_roster_mapping_scalar,
                                 write_roster_scalar)  # noqa: E402
from core.voice_output import normalize_output_config, OUTPUT_PROVIDERS  # noqa: E402
from core.resident_config import resolve_resident_config  # noqa: E402
from shell.voice_settings import (load_voice_defaults, save_voice_defaults,
                                  normalize_voice_tuning)  # noqa: E402


class TurnRequest(BaseModel):
    message: str
    speaker: str = None
    user_persona: str = ""
    images: list[dict] = Field(default_factory=list)


class AlteredStateRequest(BaseModel):
    profile: str = "psilocybin"
    intensity: float = Field(default=0.78, ge=0.10, le=1.0)


class AlteredDoseRequest(BaseModel):
    profile: str = "psilocybin"
    intensity: float = Field(default=0.78, ge=0.10, le=1.0)


class AlteredConsentRequest(BaseModel):
    action: str
    profile: str = "psilocybin"
    intensity: float = Field(default=0.78, ge=0.10, le=1.0)


class AgencyInboxRequest(BaseModel):
    label: str
    content: str


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


class WorkRouteRequest(BaseModel):
    route: str
    model: str | None = None


class VoiceOutputConfigRequest(BaseModel):
    provider: str = "browser-native"
    voice: str = ""
    rate_scale: float = 1.0
    pitch_scale: float = 1.0
    volume_scale: float = 1.0


class VoiceDefaultsRequest(BaseModel):
    rate_scale: float = 1.0
    pitch_scale: float = 1.0
    volume_scale: float = 1.0


class ModelCreateRequest(BaseModel):
    name: str
    family: str               # ollama | ollama_openai | anthropic | openai_compat
    endpoint: str
    window_tokens: int = None
    base_url: str = None      # openai_compat only: http://host:port/v1
    api_key_env: str = None   # openai_compat: env var NAME, never a value
    connect_timeout_s: float = None
    read_timeout_s: float = None
    write_timeout_s: float = None
    pool_timeout_s: float = None


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


class MCPLibraryConfigRequest(BaseModel):
    config: dict = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class SystemPromptRequest(BaseModel):
    text: str = ""             # empty/whitespace REVERTS to inherited baseline


class ThemeRequest(BaseModel):
    patch: dict
    reset: bool = False
    replace: bool = False


class PresetRequest(BaseModel):
    id: str = ""
    label: str
    tokens: dict


class ConversationBackgroundRequest(BaseModel):
    data_url: str


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


# Purpose routes are deliberately explicit.  A single global "cheap model"
# switch would hide privacy, vision-capability, and autonomous-spend
# boundaries that differ by job.  Settings groups these into human-readable
# work tiers, while this allowlist remains the authoritative write surface.
WORK_ROUTE_SPECS = {
    "social": {
        "tier": "ambient", "section": "social", "key": "model",
        "label": "Resident-to-resident replies", "purpose": "social_turn",
        "organ": "social", "local_required": True,
        "description": "Room conversation that is not a foreground human turn.",
    },
    "idle": {
        "tier": "ambient", "section": "metabolism", "key": "idle_model",
        "label": "Idle emergence", "purpose": "dmn", "organ": "dmn",
        "local_required": True,
        "description": "A model is spent only when accumulated pressure discharges.",
    },
    "autonomous_deliberation": {
        "tier": "ambient", "section": "autonomous_deliberation",
        "key": "model", "label": "Bounded API deliberation",
        "purpose": "dmn", "purpose_aliases": [
            "dmn_contact_choice", "autonomous_outcome_choice"],
        "organ": "dmn",
        "description": (
            "A cheaper family-matched API vessel may answer an already-earned autonomy "
            "opening while a persistent credit and token reservoir remains; "
            "local idle emergence is the fallback."),
    },
    "avatar_vision": {
        "tier": "ambient", "section": "perception",
        "key": "avatar_vision_model", "label": "Avatar POV fallback",
        "purpose": "vision", "organ": "perception", "vision": True,
        "local_required": True, "optional": True,
        "description": "Local pixel fallback after free renderer grounding; not a timer-polled API route.",
    },
    "affect": {
        "tier": "integration", "section": "interoception",
        "key": "affect_model", "label": "Affect interpretation",
        "purpose": "affect", "purpose_aliases": ["affect_event"],
        "organ": "feel",
        "description": "Describes possible felt consequences without assigning a feeling.",
    },
    "gist": {
        "tier": "integration", "section": "consolidation",
        "key": "gist_model", "label": "Gist consolidation",
        "purpose": "gist", "organ": "gist",
        "description": "Compacts admitted experience for later context and recall.",
    },
    "shared_vision": {
        "tier": "integration", "section": "perception",
        "key": "vision_model", "label": "Shared-image transducer",
        "purpose": "vision", "organ": "perception", "vision": True,
        "optional": True,
        "description": "Turns human-shared pixels into observable features for text-only speaking vessels.",
    },
    "focused_vision": {
        "tier": "focused", "section": "perception",
        "key": "focused_vision_model", "label": "Chosen visual engagement",
        "purpose": "vision", "organ": "perception", "vision": True,
        "optional": True,
        "description": "One focused visual call only when the resident mechanically chooses to inspect.",
    },
    "agency": {
        "tier": "focused", "section": "agency", "key": "model",
        "label": "Agency workbench", "purpose": "agency", "organ": "agency",
        "description": "Structured planning after an admitted agency handoff.",
    },
    "intention_loom": {
        "tier": "projects", "section": "intention_loom", "key": "model",
        "label": "Intention Loom", "purpose": "intention_loom",
        "organ": "intention_loom", "local_required": True,
        "description": "Private intention formation after a real shared-field win.",
    },
    "writing_desk": {
        "tier": "projects", "section": "writing_desk", "key": "model",
        "label": "Writing Desk", "purpose": "writing_desk",
        "organ": "writing_desk", "local_required": True,
        "description": "Resident-owned private writing projects.",
    },
    "archive_reader": {
        "tier": "projects", "section": "archive_reader", "key": "model",
        "label": "Archive Reader", "purpose": "archive_reader",
        "organ": "archive_reader", "local_required": True,
        "description": "Bounded reading of the resident's granted conversation archive.",
    },
    "document_reader": {
        "tier": "projects", "section": "document_reader", "key": "model",
        "label": "Document Reader", "purpose": "document_reader",
        "organ": "document_reader", "local_required": True,
        "description": "Private reading of human-granted documents.",
    },
    "research_desk": {
        "tier": "projects", "section": "research_desk", "key": "model",
        "label": "Research Desk", "purpose": "research_desk",
        "organ": "research_desk", "local_required": True,
        "description": "Local planning behind the bounded read-only public research door.",
    },
    "atelier": {
        "tier": "projects", "section": "atelier", "key": "model",
        "label": "Atelier", "purpose": "atelier", "organ": "atelier",
        "local_required": True,
        "description": "Private creative translation before any separately configured renderer.",
    },
}

WORK_ROUTE_TIERS = [
    {
        "id": "ambient", "label": "Tier 0 · Ambient and frequent",
        "description": "Local-only routes that may recur without a direct human request.",
    },
    {
        "id": "integration", "label": "Tier 1 · Interpretation and integration",
        "description": "Compact reads that connect perception, felt-state history, and recall.",
    },
    {
        "id": "focused", "label": "Tier 2 · Chosen engagement",
        "description": "Bounded work admitted by a resident's direct attention or agency.",
    },
    {
        "id": "projects", "label": "Tier 3 · Private workbenches",
        "description": "Resident-owned project work; currently held to local vessels.",
    },
]


def work_route_state(roster: dict, active_model: str | None,
                     declared_roster: dict | None = None) -> dict:
    """Resolve configured and inherited model routes without starting work."""
    enabled = set(roster.get("enabled_organs") or [])
    declared_roster = roster if declared_roster is None else declared_roster
    routes = {}
    for route, spec in WORK_ROUTE_SPECS.items():
        section = roster.get(spec["section"]) or {}
        declared_section = declared_roster.get(spec["section"]) or {}
        declared_here = spec["key"] in declared_section
        configured = (declared_section.get(spec["key"])
                      if declared_here else None)
        effective = section.get(spec["key"])
        inherited_from = None
        if not declared_here and effective:
            inherited_from = "household_default"
        elif route == "affect" and not effective:
            effective, inherited_from = active_model, "foreground"
        elif route == "gist" and not effective:
            effective = ((roster.get("interoception") or {})
                         .get("affect_model") or active_model)
            inherited_from = "affect"
        elif route == "avatar_vision" and not effective:
            effective = ((roster.get("perception") or {})
                         .get("vision_model"))
            inherited_from = "shared_vision" if effective else None
        routes[route] = {
            "configured": configured,
            "effective": effective,
            "inherited_from": inherited_from,
            "enabled": (not spec.get("organ")
                        or spec["organ"] in enabled),
            "local_only": bool(section.get("local_only"))
                          or bool(spec.get("local_required")),
        }
    return routes


class UserPersonaRequest(BaseModel):
    id: str = ""
    name: str
    description: str = ""
    preferences: str = ""
    boundaries: str = ""
    icon: str | None = None


def model_start_blocker(model: str, verify_remote: bool = True):
    """Return a user-facing reason a configured model cannot answer yet.

    A process reaching ``/api/state`` only proves that the cockpit booted; it
    does not prove that its model endpoint exists. Check local Ollama tags on
    every start, and verify OpenAI's model catalog on explicit starts. Router
    boot skips the remote catalog so a temporary network outage cannot erase a
    household, while still enforcing key presence and local model truth.
    """
    from harness.clients import model_auth_status
    from harness.spec_loader import load_spec
    from shell.model_catalog import discover_models
    spec = load_spec(model)
    ident = spec.get("identity") or {}
    auth = model_auth_status(spec)
    if auth["required"] and not auth["set"]:
        return (f"model '{model}' needs {auth['env']}, but it is not set. "
                f"Open Settings → API Keys, paste it there, then Start again.")
    endpoint = (ident.get("endpoint") or "").strip()
    provider = ident.get("provider")
    if provider == "ollama":
        installed = discover_models("ollama")["models"]
        if endpoint not in installed:
            return (f"model '{model}' points to Ollama tag '{endpoint}', but "
                    f"that model is not installed. Open Settings → Models "
                    f"and install it or choose an installed model.")
    base_url = (ident.get("base_url") or "").rstrip("/")
    if (verify_remote and provider == "openai_compat"
            and base_url == "https://api.openai.com/v1"):
        available = discover_models(
            "openai_compat", base_url, ident.get("api_key_env"))["models"]
        if endpoint not in available:
            return (f"model '{model}' points to OpenAI model '{endpoint}', "
                    f"but this API key cannot access that model. Open Settings "
                    f"→ Models and choose one returned by Discover.")
    return None


def record_model_start_health(model: str, *, status: str,
                              error=None) -> None:
    """Project startup reachability without retaining raw provider text."""
    try:
        from harness.service_health import record_service_health
        from harness.spec_loader import load_spec
        identity = (load_spec(model).get("identity") or {})
        provider = identity.get("provider") or identity.get("family") \
            or "model-provider"
        record_service_health(
            "model_start", provider, model, status=status, error=error)
    except Exception:
        pass


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
            declared_data = yaml.safe_load(f) or {}
        data = resolve_resident_config(ROOT, declared_data)
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
            entry["avatar_vision_model"] = (
                (data.get("perception") or {}).get(
                    "avatar_vision_model"))
            entry["focused_vision_model"] = (
                (data.get("perception") or {}).get(
                    "focused_vision_model"))
            entry["work_routes"] = work_route_state(
                data, entry["model"], declared_data)
            entry["voice_output"] = normalize_output_config(
                data.get("voice_output"))
        registry[pid] = entry
    return registry


def set_current_model(persona_dir: str, model: str) -> bool:
    """Persist the switched vessel as roster truth. House laws:
    text edit (never ruamel), validate-first, .prev kept, atomic
    replace — the env_store idiom. Replaces the current_model line
    in place or appends one at column 0; every other byte untouched."""
    path = os.path.join(persona_dir, "roster.yaml")
    tmp = path + ".tmp_curmodel"
    try:
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
        # Validate before touching either durable file.
        parsed = yaml.safe_load(text)
        if not isinstance(parsed, dict) \
                or parsed.get("current_model") != model:
            raise ValueError("round-trip mismatch")
        with open(path + ".prev", "w", encoding="utf-8") as f:
            f.writelines(lines)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        return True
    except Exception as e:
        # Windows can refuse an atomic replace while another process has the
        # roster open. A settings request must report that conflict without
        # taking down the router or pretending the choice was saved.
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        print(f"[router] current_model write REFUSED ({e}); "
              f"roster untouched")
        return False


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


def resolved_persona_icon(pid: str, entry: dict,
                          model: str | None = None) -> str:
    """Return the active Appearance glyph, with roster identity as baseline."""
    display_name = str(entry.get("display_name") or pid)
    fallback = str(entry.get("icon") or display_name[:1].upper() or "·")
    try:
        icons = (resolve_theme(ROOT, pid, model).get("tokens") or {}).get(
            "speaker_icons") or {}
    except (OSError, TypeError, ValueError):
        return fallback
    for wanted in (display_name, pid):
        key = next((key for key in icons
                    if str(key).casefold() == wanted.casefold()), None)
        if key is not None and str(icons[key]).strip():
            return str(icons[key]).strip()
    return fallback


class PersonaProcess:
    def __init__(self, pid: str, model: str, identity_file,
                 room_cfg: dict = None, room_url: str = None,
                  max_tokens: int = None, speaker: str = None):
        self.id = pid
        self.model = model
        self.port = _free_port()
        cmd = [sys.executable, "-X", "utf8",
               os.path.join(ROOT, "shell", "cockpit.py"),
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

    def wait_ready(self, timeout: float = 25.0, stop_event=None) -> bool:
        deadline = (None if timeout is None else time.time() + timeout)
        url = f"http://127.0.0.1:{self.port}/api/state"
        while deadline is None or time.time() < deadline:
            if stop_event is not None and stop_event.is_set():
                return False
            if not self.alive():
                return False
            try:
                urllib.request.urlopen(url, timeout=1)
                return True
            except Exception:
                if stop_event is not None:
                    stop_event.wait(0.3)
                else:
                    time.sleep(0.3)
        return False

    def stop(self) -> bool:
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        return not self.alive()

    def checkpoint_and_stop(self, timeout: float = 25.0) -> dict:
        """Obtain a persona-owned clean checkpoint before terminating it."""
        if not self.alive():
            return {
                "persona": self.id, "verdict": "unknown",
                "reason": "process_not_running", "stopped": True,
                "content_free": True,
            }
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}"
            "/api/startup-continuity/checkpoint",
            data=b"{}", headers={"Content-Type": "application/json"},
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                receipt = json.loads(response.read())
        except Exception as exc:
            return {
                "persona": self.id, "verdict": "unknown",
                "reason": f"checkpoint_unavailable:{type(exc).__name__}",
                "stopped": False, "content_free": True,
            }
        verdict = str(receipt.get("verdict") or "unknown")
        stopped = self.stop()
        return {
            "persona": self.id,
            "boot_id": str(receipt.get("boot_id") or ""),
            "verdict": (verdict if stopped else "unclean"),
            "reason": (str(receipt.get("reason") or "")
                       if stopped else "process_did_not_stop"),
            "stopped": stopped,
            "checkpoint_sha256": str(receipt.get("receipt_sha256") or ""),
            "content_free": True,
        }


def build_app(room_url: str = None, *, record_health: bool = False,
              auto_launch: bool = False) -> FastAPI:
    app = FastAPI(title="JNSQ shell/router")
    startup_health = (record_model_start_health if record_health
                      else lambda *args, **kwargs: None)
    if os.path.isdir(ASSET_DIR):
        app.mount("/assets", StaticFiles(directory=ASSET_DIR),
                  name="jnsq-assets")
    app.state.registry = discover_personas()
    app.state.processes = {}
    app.state.room_url = room_url
    app.state.local_identity = load_local_identity(ROOT)
    app.state.persona_lifecycle = {
        pid: ("pending" if auto_launch and entry["kind"] == "model_persona"
              else "stopped")
        for pid, entry in app.state.registry.items()
    }
    app.state.process_lock = threading.RLock()
    app.state.shutdown_event = threading.Event()
    app.state.launch_thread = None
    app.state.readiness_threads = {}
    app.state.launch_all_active = False
    # Private archive content crosses into the browser only through a
    # restart-scoped local UI capability.  The router already binds to
    # 127.0.0.1; the additional token and request checks prevent a remote
    # host or unrelated web origin from treating localhost as a transcript
    # export API.
    app.state.archive_read_token = secrets.token_urlsafe(32)

    def _archive_request_is_local(request: Request) -> bool:
        client_host = request.client.host if request.client else ""
        if client_host == "testclient":
            return request.url.hostname == "testserver"
        try:
            if not ipaddress.ip_address(client_host).is_loopback:
                return False
        except ValueError:
            return False
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return False
        fetch_site = request.headers.get("sec-fetch-site", "")
        return not fetch_site or fetch_site in {"same-origin", "none"}

    def _archive_api_allowed(request: Request) -> bool:
        supplied = request.headers.get("x-jnsq-archive-token", "")
        return (_archive_request_is_local(request)
                and bool(supplied)
                and hmac.compare_digest(
                    supplied, app.state.archive_read_token))

    def _private_archive_json(content, status_code: int = 200):
        return JSONResponse(
            status_code=status_code, content=content,
            headers={"Cache-Control": "no-store",
                     "X-Content-Type-Options": "nosniff"})

    @app.get("/api/ui/theme")
    def ui_theme():
        result = resolve_theme(ROOT)
        media = load_conversation_background(ROOT)
        result["conversation_background"] = ({"url": "/api/ui/conversation-background",
                                               "revision": media["revision"]}
                                              if media else None)
        return result

    @app.post("/api/ui/theme")
    def set_ui_theme(req: ThemeRequest):
        try:
            return save_theme(ROOT, "household", req.patch,
                              reset=req.reset, replace=req.replace)
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content={"error": str(e)})

    @app.post("/api/ui/presets")
    def ui_preset_save(req: PresetRequest):
        try:
            return save_custom_preset(ROOT, preset_id=req.id,
                                      label=req.label, tokens=req.tokens)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.delete("/api/ui/presets/{preset_id}")
    def ui_preset_delete(preset_id: str):
        try:
            return delete_custom_preset(ROOT, preset_id)
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.get("/api/ui/conversation-background")
    def ui_background_get():
        media = load_conversation_background(ROOT)
        if not media:
            return JSONResponse(status_code=404,
                                content={"error": "no conversation background"})
        return FileResponse(media["path"], media_type=media["mime"],
                            headers={"X-Content-Type-Options": "nosniff",
                                     "Cache-Control": "no-cache"})

    @app.post("/api/ui/conversation-background")
    def ui_background_save(req: ConversationBackgroundRequest):
        try:
            media = save_conversation_background(ROOT, req.data_url)
            return {"ok": True, "url": "/api/ui/conversation-background",
                    "revision": media["revision"]}
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.delete("/api/ui/conversation-background")
    def ui_background_delete():
        return {"ok": True, "removed": delete_conversation_background(ROOT)}

    def set_lifecycle(pid: str, state: str) -> None:
        with app.state.process_lock:
            app.state.persona_lifecycle[pid] = state

    def checkpoint_then_stop(proc) -> dict:
        checkpoint = getattr(proc, "checkpoint_and_stop", None)
        if callable(checkpoint):
            receipt = dict(checkpoint() or {})
            if not receipt.get("stopped"):
                receipt["stopped"] = bool(proc.stop())
            return receipt
        stopped = bool(proc.stop())
        return {
            "persona": str(getattr(proc, "id", "")),
            "verdict": "unknown",
            "reason": "legacy_process_has_no_checkpoint_route",
            "stopped": stopped,
            "content_free": True,
        }

    def watch_until_ready(pid: str, proc: PersonaProcess, model: str):
        """Follow one process until its API answers or the process exits."""
        ready = proc.wait_ready(
            timeout=None, stop_event=app.state.shutdown_event)
        with app.state.process_lock:
            if app.state.processes.get(pid) is not proc \
                    or app.state.persona_lifecycle.get(pid) == "stopped":
                return
            if ready:
                app.state.persona_lifecycle[pid] = "ready"
            elif not app.state.shutdown_event.is_set():
                app.state.persona_lifecycle[pid] = "unavailable"
        if ready:
            startup_health(model, status="ok")
            print(f"[router] {pid} on {model} -> port {proc.port} (ready)",
                  flush=True)
        elif not app.state.shutdown_event.is_set():
            error = RuntimeError("model cockpit exited during startup")
            startup_health(model, status="error", error=error)
            print(f"[router] {pid} on {model} -> unavailable "
                  "(cockpit exited)", flush=True)

    def start_readiness_watch(pid: str, proc: PersonaProcess, model: str):
        thread = threading.Thread(
            target=watch_until_ready, args=(pid, proc, model), daemon=True,
            name=f"resident-ready-{pid}")
        with app.state.process_lock:
            app.state.readiness_threads[pid] = thread
        thread.start()
        return thread

    def launch_all():
        with app.state.process_lock:
            if app.state.launch_all_active:
                return
            app.state.launch_all_active = True
        try:
            for pid, entry in app.state.registry.items():
                if app.state.shutdown_event.is_set():
                    break
                if entry["kind"] != "model_persona":
                    continue
                with app.state.process_lock:
                    existing = app.state.processes.get(pid)
                    if existing is not None and existing.alive():
                        continue
                    app.state.persona_lifecycle[pid] = "starting"
                try:
                    blocked = model_start_blocker(entry["model"],
                                                  verify_remote=False)
                except Exception as error:
                    set_lifecycle(pid, "blocked")
                    startup_health(
                        entry["model"], status="error", error=error)
                    print(f"[router] {pid} on {entry['model']} -> BLOCKED: "
                          f"{error}", flush=True)
                    continue
                if blocked:
                    set_lifecycle(pid, "blocked")
                    startup_health(
                        entry["model"], status="error",
                        error=RuntimeError(blocked))
                    print(f"[router] {pid} on {entry['model']} -> BLOCKED: "
                          f"{blocked}", flush=True)
                    continue
                try:
                    # Keep shutdown from snapshotting children between their
                    # spawn and registration in the owned process set.
                    with app.state.process_lock:
                        if app.state.shutdown_event.is_set():
                            break
                        proc = PersonaProcess(
                            pid, entry["model"], entry.get("identity_file"),
                            room_cfg=entry.get("room"), room_url=room_url,
                            max_tokens=entry.get("max_tokens"), speaker=None)
                        app.state.processes[pid] = proc
                        app.state.persona_lifecycle[pid] = "starting"
                except Exception as error:
                    set_lifecycle(pid, "unavailable")
                    startup_health(
                        entry["model"], status="error", error=error)
                    print(f"[router] {pid} on {entry['model']} -> "
                          f"unavailable ({type(error).__name__})", flush=True)
                    continue
                print(f"[router] {pid} on {entry['model']} -> port "
                      f"{proc.port} (starting)", flush=True)
                start_readiness_watch(pid, proc, entry["model"])
        finally:
            with app.state.process_lock:
                app.state.launch_all_active = False

    def start_background_launch():
        with app.state.process_lock:
            current = app.state.launch_thread
            if app.state.shutdown_event.is_set() \
                    or (current is not None and current.is_alive()):
                return
            thread = threading.Thread(
                target=launch_all, daemon=True,
                name="household-resident-launch")
            app.state.launch_thread = thread
        thread.start()

    def shutdown_all():
        app.state.shutdown_event.set()
        with app.state.process_lock:
            processes = list(app.state.processes.items())
            for pid, _proc in processes:
                app.state.persona_lifecycle[pid] = "stopped"
        for _pid, proc in processes:
            proc.stop()

    app.state.launch_all = launch_all
    app.state.start_background_launch = start_background_launch
    app.state.shutdown_all = shutdown_all
    atexit.register(shutdown_all)
    if auto_launch:
        app.add_event_handler("startup", start_background_launch)

    @app.get("/", response_class=HTMLResponse)
    def index():
        """The Je Ne Sais Quoi: one door, every window. Tabs for each cockpit,
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
        from shell.provider_health import provider_health_report
        health = provider_health_report(PERSONAS_DIR, hours=24)
        return (page.replace("/*CONFIG*/", _json.dumps(cfg))
                .replace("/*SERVICE_HEALTH*/", _json.dumps(health)))

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

    @app.get("/about", response_class=HTMLResponse)
    def about_page():
        """Public field guide: setup, features, embodiment, and receipts."""
        with open(os.path.join(ROOT, "shell", "about.html"),
                  encoding="utf-8") as f:
            return f.read()

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
        updater_name = ("UPDATE_JNSQ.command" if sys.platform == "darwin"
                        else "UPDATE_JNSQ.bat")
        return {"version": installed_version(),
                "updater": os.path.exists(os.path.join(ROOT, updater_name)),
                "updater_name": updater_name}

    @app.get("/api/voice/status")
    def voice_output_status():
        from shell.qwen_tts_service import status as qwen_status
        from shell.chatterbox_tts_service import status as chatterbox_status
        return {"qwen3-tts": qwen_status(),
                "chatterbox-turbo": chatterbox_status(),
                "hume-octave": {"configured": bool(os.environ.get("HUME_API_KEY")),
                                "local": False},
                "elevenlabs": {"configured": bool(os.environ.get("ELEVENLABS_API_KEY")),
                               "local": False},
                "browser-native": {"installed": True, "local": True}}

    @app.get("/api/voice/defaults")
    def household_voice_defaults():
        return {"voice_defaults": load_voice_defaults(ROOT)}

    @app.post("/api/voice/defaults")
    def household_voice_defaults_save(req: VoiceDefaultsRequest):
        return {"ok": True, "voice_defaults": save_voice_defaults(
            ROOT, req.model_dump())}

    @app.get("/api/version/check")
    def version_check():
        """Read-only startup/manual check; applying remains an offline act.

        JNSQ must be stopped before engine files change, so this endpoint
        reports availability only. The platform updater owns the validated
        patch while JNSQ is stopped.
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
            updater_name = ("UPDATE_JNSQ.command"
                            if sys.platform == "darwin"
                            else "UPDATE_JNSQ.bat")
            return {"version": current, "latest": latest,
                    "update_available": public_update_available(
                        current, latest),
                    "updater_name": updater_name}
        except Exception as error:
            return JSONResponse(status_code=502,
                                content={"error": f"update check failed: {error}"})

    @app.get("/users", response_class=HTMLResponse)
    def users_page():
        with open(os.path.join(ROOT, "shell", "users.html"),
                  encoding="utf-8") as f:
            return f.read()

    @app.get("/model-calls", response_class=HTMLResponse)
    def model_calls_page():
        """Content-free household cost and latency observatory."""
        with open(os.path.join(ROOT, "shell", "model_calls.html"),
                  encoding="utf-8") as f:
            return f.read()

    @app.get("/conversation-archives", response_class=HTMLResponse)
    def conversation_archives_page(request: Request):
        """Human-facing, read-only browser for household conversation logs."""
        if not _archive_request_is_local(request):
            return HTMLResponse("local Nexus access only", status_code=403)
        with open(os.path.join(ROOT, "shell", "conversation_archives.html"),
                  encoding="utf-8") as f:
            page = f.read()
        return HTMLResponse(
            page.replace("/*ARCHIVE_TOKEN*/",
                         json.dumps(app.state.archive_read_token)),
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    "default-src 'self'; style-src 'unsafe-inline'; "
                    "script-src 'unsafe-inline'; connect-src 'self'; "
                    "img-src 'self' data:; frame-ancestors 'self'"),
            })

    @app.get("/api/conversation-archives/owners")
    def conversation_archive_owners(request: Request):
        if not _archive_api_allowed(request):
            return _private_archive_json(
                {"error": "private local archive capability required"}, 403)
        from shell.conversation_archive_browser import available_archives
        owners = available_archives(ROOT)
        return _private_archive_json({"owners": [{key: item[key] for key in (
            "id", "label", "kind", "has_archive")} for item in owners]})

    @app.get("/api/conversation-archives")
    def conversation_archive_list(request: Request, owner: str, q: str = "",
                                  offset: int = 0, limit: int = 60):
        if not _archive_api_allowed(request):
            return _private_archive_json(
                {"error": "private local archive capability required"}, 403)
        from shell.conversation_archive_browser import list_conversations
        try:
            return _private_archive_json(list_conversations(
                ROOT, owner, query=q, offset=offset, limit=limit))
        except ValueError as error:
            return _private_archive_json({"error": str(error)}, 404)

    @app.get("/api/conversation-archives/days")
    def conversation_archive_days(request: Request, owner: str, q: str = "",
                                  offset: int = 0, limit: int = 45,
                                  timezone: str = "UTC"):
        if not _archive_api_allowed(request):
            return _private_archive_json(
                {"error": "private local archive capability required"}, 403)
        from shell.conversation_archive_browser import list_days
        try:
            return _private_archive_json(list_days(
                ROOT, owner, query=q, offset=offset, limit=limit,
                timezone_name=timezone))
        except ValueError as error:
            return _private_archive_json({"error": str(error)}, 404)

    @app.get("/api/conversation-archives/{owner}/day/{day}")
    def conversation_archive_day(request: Request, owner: str, day: str,
                                 timezone: str = "UTC"):
        if not _archive_api_allowed(request):
            return _private_archive_json(
                {"error": "private local archive capability required"}, 403)
        from shell.conversation_archive_browser import read_day
        try:
            return _private_archive_json(read_day(
                ROOT, owner, day, timezone_name=timezone))
        except ValueError as error:
            return _private_archive_json({"error": str(error)}, 404)

    @app.get(
        "/api/conversation-archives/{owner}/conversation/{conversation_id}")
    def conversation_archive_detail(request: Request, owner: str,
                                    conversation_id: str):
        if not _archive_api_allowed(request):
            return _private_archive_json(
                {"error": "private local archive capability required"}, 403)
        from shell.conversation_archive_browser import read_conversation
        try:
            return _private_archive_json(read_conversation(
                ROOT, owner, conversation_id))
        except ValueError as error:
            return _private_archive_json({"error": str(error)}, 404)

    @app.get("/api/model-calls/summary")
    def model_calls_summary(hours: int = 24):
        from shell.model_call_dashboard import read_receipts
        if hours < 0 or hours > 24 * 366:
            return JSONResponse(
                status_code=400,
                content={"error": "hours must be between 0 and 8784"})
        return read_receipts(hours=hours)

    @app.get("/api/provider-health")
    def provider_health(hours: int = 24):
        """Actionable unresolved provider faults; no prompts or replies."""
        if hours < 1 or hours > 24 * 7:
            return JSONResponse(
                status_code=400,
                content={"error": "hours must be between 1 and 168"})
        from shell.provider_health import provider_health_report
        return provider_health_report(PERSONAS_DIR, hours=hours)

    @app.get("/prompt-assembly", response_class=HTMLResponse)
    def prompt_assembly_page():
        """Private, content-free observatory for one resident at a time."""
        with open(os.path.join(ROOT, "shell", "prompt_assembly.html"),
                  encoding="utf-8") as f:
            return f.read()

    @app.get("/api/prompt-assembly/personas")
    def prompt_assembly_personas():
        from shell.prompt_assembly_observatory import available_personas
        return {"personas": available_personas(ROOT)}

    @app.get("/api/prompt-assembly/summary")
    def prompt_assembly_summary(persona: str, hours: int = 24):
        from shell.prompt_assembly_observatory import read_prompt_assembly
        if hours < 0 or hours > 24 * 366:
            return JSONResponse(
                status_code=400,
                content={"error": "hours must be between 0 and 8784"})
        try:
            return read_prompt_assembly(ROOT, persona, hours=hours)
        except ValueError as error:
            return JSONResponse(status_code=404,
                                content={"error": str(error)})

    @app.get("/api/oscillator-consequences/summary")
    def oscillator_consequence_summary(persona: str, hours: int = 24):
        """Persona-private, content-free completed-turn wire receipts."""
        from shell.oscillator_consequence_observatory import (
            read_oscillator_consequences,
        )
        if hours < 0 or hours > 24 * 366:
            return JSONResponse(
                status_code=400,
                content={"error": "hours must be between 0 and 8784"})
        try:
            return read_oscillator_consequences(
                ROOT, persona, hours=hours)
        except ValueError as error:
            return JSONResponse(status_code=404,
                                content={"error": str(error)})

    @app.get("/api/recall-dispersion/summary")
    def recall_dispersion_summary(persona: str, hours: int = 24):
        """Persona-private, content-free four-arm retrieval shadows."""
        from shell.recall_dispersion_observatory import (
            read_recall_dispersion,
        )
        if hours < 0 or hours > 24 * 366:
            return JSONResponse(
                status_code=400,
                content={"error": "hours must be between 0 and 8784"})
        try:
            return read_recall_dispersion(ROOT, persona, hours=hours)
        except ValueError as error:
            return JSONResponse(status_code=404,
                                content={"error": str(error)})

    @app.get("/api/users")
    def users_list():
        from core.users import load_user_avatar
        from shell.local_identity import local_user_directory
        users = []
        for uid, account in local_user_directory(ROOT).items():
            shown = dict(account)
            avatar = load_user_avatar(ROOT, uid)
            shown["avatar_url"] = (f"/api/users/{uid}/avatar?v="
                                   f"{avatar['version']}" if avatar else "")
            users.append(shown)
        return {"users": users}

    @app.post("/api/users")
    def users_upsert(req: UserRequest):
        from core.users import upsert_user
        try:
            account = upsert_user(
                ROOT, username=req.username, display_name=req.display_name,
                pronouns=req.pronouns, public_profile=req.public_profile,
                update=req.update)
            if account["id"] == app.state.local_identity["user_id"]:
                app.state.local_identity = save_local_identity(
                    ROOT, account["id"], account["display_name"])
            return {"ok": True, "account": account}
        except FileExistsError as e:
            return JSONResponse(status_code=409, content={"error": str(e)})
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.get("/api/users/{uid}")
    def user_detail(uid: str):
        from core.users import (get_user, load_user_avatar,
                                load_user_persona_avatar)
        try:
            user = get_user(ROOT, uid)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        if not user:
            return JSONResponse(status_code=404,
                                content={"error": f"no user '{uid}'"})
        avatar = load_user_avatar(ROOT, uid)
        user["account"]["avatar_url"] = (
            f"/api/users/{uid}/avatar?v={avatar['version']}" if avatar else "")
        for pid, persona in user["user_personas"].items():
            media = load_user_persona_avatar(ROOT, uid, pid)
            persona["avatar_url"] = (
                f"/api/users/{uid}/personas/{pid}/avatar?v={media['version']}"
                if media else "")
        return user

    @app.post("/api/users/{uid}/icon")
    def user_icon(uid: str, req: PersonaIconRequest):
        from core.users import set_user_icon
        try:
            account = set_user_icon(ROOT, uid, req.icon)
            return {"ok": True, "user": uid, "icon": account["icon"]}
        except KeyError as error:
            return JSONResponse(status_code=404, content={"error": str(error)})
        except (OSError, ValueError) as error:
            return JSONResponse(status_code=400, content={"error": str(error)})

    @app.get("/api/users/{uid}/avatar")
    def user_avatar_file(uid: str):
        from core.users import load_user_avatar
        avatar = load_user_avatar(ROOT, uid)
        if not avatar:
            return JSONResponse(status_code=404,
                                content={"error": "user has no avatar"})
        return FileResponse(avatar["path"], media_type=avatar["mime"],
                            headers={"X-Content-Type-Options": "nosniff",
                                     "Cache-Control": "no-cache"})

    @app.post("/api/users/{uid}/avatar")
    def user_avatar_save(uid: str, req: PersonaAvatarRequest):
        from core.users import save_user_avatar
        try:
            avatar = save_user_avatar(ROOT, uid, req.data_url)
            version = os.stat(avatar["path"]).st_mtime_ns
            return {"ok": True, "user": uid,
                    "avatar_url": f"/api/users/{uid}/avatar?v={version}"}
        except KeyError as error:
            return JSONResponse(status_code=404, content={"error": str(error)})
        except (OSError, ValueError) as error:
            return JSONResponse(status_code=400, content={"error": str(error)})

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
                boundaries=req.boundaries, icon=req.icon)
            return {"ok": True, "persona": persona}
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.delete("/api/users/{uid}/personas/{persona_id}")
    def user_persona_delete(uid: str, persona_id: str):
        from core.users import delete_user_persona
        try:
            removed = delete_user_persona(ROOT, uid, persona_id)
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        if not removed:
            return JSONResponse(status_code=404,
                                content={"error": f"no user persona '{persona_id}'"})
        return {"ok": True}

    @app.get("/api/users/{uid}/personas/{persona_id}/avatar")
    def user_persona_avatar_file(uid: str, persona_id: str):
        from core.users import load_user_persona_avatar
        avatar = load_user_persona_avatar(ROOT, uid, persona_id)
        if not avatar:
            return JSONResponse(status_code=404,
                                content={"error": "user persona has no avatar"})
        return FileResponse(avatar["path"], media_type=avatar["mime"],
                            headers={"X-Content-Type-Options": "nosniff",
                                     "Cache-Control": "no-cache"})

    @app.post("/api/users/{uid}/personas/{persona_id}/avatar")
    def user_persona_avatar_save(uid: str, persona_id: str,
                                 req: PersonaAvatarRequest):
        from core.users import save_user_persona_avatar
        try:
            avatar = save_user_persona_avatar(
                ROOT, uid, persona_id, req.data_url)
            version = os.stat(avatar["path"]).st_mtime_ns
            return {"ok": True, "user": uid, "persona": persona_id,
                    "avatar_url": (f"/api/users/{uid}/personas/{persona_id}/"
                                   f"avatar?v={version}")}
        except KeyError as error:
            return JSONResponse(status_code=404, content={"error": str(error)})
        except (OSError, ValueError) as error:
            return JSONResponse(status_code=400, content={"error": str(error)})

    @app.get("/status", response_class=HTMLResponse)
    def status_table():
        rows = []
        for pid, entry in sorted(app.state.registry.items()):
            proc = app.state.processes.get(pid)
            if entry["kind"] != "model_persona":
                status, link = f"reserved ({entry['kind']}, not launched)", "—"
            elif proc is None:
                status = app.state.persona_lifecycle.get(pid, "not launched")
                link = "—"
            elif not proc.alive():
                status, link = "DEAD", "—"
            elif app.state.persona_lifecycle.get(pid) != "ready":
                status, link = "starting", "—"
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
            lifecycle = app.state.persona_lifecycle.get(pid, "stopped")
            alive = proc.alive() if proc else False
            active_model = (proc.model if proc and alive
                            else entry.get("model"))
            if proc is not None and not alive \
                    and lifecycle not in {"blocked", "stopped"}:
                lifecycle = "unavailable"
                set_lifecycle(pid, lifecycle)
            out[pid] = {
                "kind": entry["kind"],
                "display_name": entry.get("display_name") or pid,
                "icon": entry.get("icon") or "",
                "appearance_icon": resolved_persona_icon(
                    pid, entry, active_model),
                "avatar_url": (f"/api/personas/{pid}/avatar?v="
                               f"{entry['avatar']['version']}"
                               if entry.get("avatar") else ""),
                "model": active_model,
                "models": entry.get("models") or [],
                "vision_model": entry.get("vision_model"),
                "avatar_vision_model": entry.get("avatar_vision_model"),
                "focused_vision_model": entry.get("focused_vision_model"),
                "work_routes": entry.get("work_routes") or {},
                "voice_output": entry.get("voice_output"),
                "has_room": bool(entry.get("room")),
                "port": proc.port if proc else None,
                "alive": alive,
                "ready": bool(alive and lifecycle == "ready"),
                "lifecycle": lifecycle,
            }
        return out

    @app.get("/api/work-routes")
    def list_work_routes():
        """Public route grammar only; resident selections come from rosters."""
        routes = []
        for route, spec in WORK_ROUTE_SPECS.items():
            routes.append({
                "id": route,
                **{key: value for key, value in spec.items()
                   if key not in {"section", "key"}},
            })
        return {"tiers": WORK_ROUTE_TIERS, "routes": routes}

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

    @app.post("/api/personas/{pid}/work-route")
    def persona_work_route(pid: str, req: WorkRouteRequest):
        """Persist one allowlisted purpose route without silently restarting.

        A running cockpit keeps its already-constructed route objects until a
        deliberate restart.  The response says so instead of pretending the
        new selection is live.  Local-only and vision-capability boundaries
        are validated before the roster is touched.
        """
        app.state.registry = discover_personas()
        entry = app.state.registry.get(pid)
        if not entry or entry.get("kind") != "model_persona":
            return JSONResponse(status_code=404,
                                content={"error": f"no model persona '{pid}'"})
        route_id = (req.route or "").strip()
        route = WORK_ROUTE_SPECS.get(route_id)
        if not route:
            return JSONResponse(status_code=400,
                                content={"error": "unknown work route"})
        model = (req.model or "").strip() or None
        if model is None and not route.get("optional"):
            return JSONResponse(status_code=400, content={
                "error": f"{route_id} requires an explicit model"})
        if model:
            try:
                from harness.spec_loader import load_spec
                model_spec = load_spec(model)
            except Exception as error:
                return JSONResponse(status_code=400,
                                    content={"error": str(error)})
            identity = model_spec.get("identity") or {}
            if route.get("local_required") \
                    and identity.get("locality") != "local":
                return JSONResponse(status_code=400, content={
                    "error": (f"{route_id} is local-only; '{model}' is "
                              "declared as a provider/API model")})
            if route.get("vision") \
                    and not (model_spec.get("capabilities") or {}).get("vision"):
                return JSONResponse(status_code=400, content={
                    "error": f"'{model}' is not declared vision-capable"})
        try:
            write_roster_mapping_scalar(
                entry["dir"], route["section"], route["key"], model)
        except (OSError, ValueError) as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)})
        running = bool(app.state.processes.get(pid)
                       and app.state.processes[pid].alive())
        app.state.registry = discover_personas()
        state = app.state.registry[pid]["work_routes"][route_id]
        return {"ok": True, "persona": pid, "route": route_id,
                "model": model, "state": state,
                "restart_required": running}

    @app.post("/api/personas/{pid}/voice-output")
    def persona_voice_output(pid: str, req: VoiceOutputConfigRequest):
        """Persist a persona's speaking vessel without requiring a restart."""
        app.state.registry = discover_personas()
        entry = app.state.registry.get(pid)
        if not entry or entry.get("kind") != "model_persona":
            return JSONResponse(status_code=404,
                                content={"error": f"no model persona '{pid}'"})
        provider = str(req.provider or "").strip()
        voice = str(req.voice or "").strip()
        if provider not in OUTPUT_PROVIDERS:
            return JSONResponse(status_code=400, content={
                "error": f"unknown voice output provider '{provider}'"})
        if len(voice) > 160 or any(char in voice for char in "\r\n"):
            return JSONResponse(status_code=400, content={
                "error": "voice identifier must be one line under 161 characters"})
        try:
            write_roster_mapping_scalar(entry["dir"], "voice_output",
                                        "provider", provider)
            write_roster_mapping_scalar(entry["dir"], "voice_output",
                                        "voice", voice)
            tuning = normalize_voice_tuning(req.model_dump())
            for key, value in tuning.items():
                write_roster_mapping_scalar(entry["dir"], "voice_output",
                                            key, value)
        except (OSError, ValueError) as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)})
        app.state.registry = discover_personas()
        return {"ok": True, "persona": pid,
                "voice_output": app.state.registry[pid]["voice_output"],
                "restart_required": False}

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
            # Restarting the exact vessel this router already hosted must not
            # be bricked by a transient or incomplete remote model catalog.
            # Key presence is still enforced, and a genuinely different
            # explicit model choice still receives full remote verification.
            restarting_same_vessel = bool(old and old.model == model)
            blocked = model_start_blocker(
                model, verify_remote=not restarting_same_vessel)
        except Exception as e:
            set_lifecycle(pid, "blocked")
            startup_health(model, status="error", error=e)
            return JSONResponse(status_code=400, content={
                "error": f"cannot start model '{model}': {e}"})
        if blocked:
            set_lifecycle(pid, "blocked")
            startup_health(
                model, status="error", error=RuntimeError(blocked))
            return JSONResponse(status_code=400, content={"error": blocked})
        # Once a requested vessel has passed its model/key checks, make the
        # owner's selection durable BEFORE stopping the old cockpit. Startup
        # can then fail honestly without erasing the choice or making the next
        # household boot silently return to the previous vessel.
        if model != entry["model"]:
            if not set_current_model(entry["dir"], model):
                return JSONResponse(status_code=409, content={
                    "error": (f"could not save {pid}'s model choice; "
                              f"{pid} remains on {entry['model']}")})
            app.state.registry = discover_personas()
        if old and old.alive():
            if old.model == model:
                startup_health(model, status="ok")
                return {"id": pid, "model": model, "port": old.port,
                        "alive": True,
                        "ready": (app.state.persona_lifecycle.get(pid)
                                  == "ready"),
                        "lifecycle": app.state.persona_lifecycle.get(
                            pid, "starting"),
                        "note": "already running"}
            checkpoint_then_stop(old)
        app.state.processes.pop(pid, None)
        try:
            set_lifecycle(pid, "starting")
            proc = PersonaProcess(pid, model, entry.get("identity_file"),
                                  room_cfg=entry.get("room"),
                                  room_url=app.state.room_url,
                                  max_tokens=entry.get("max_tokens"),
                                  speaker=None)
        except Exception as error:
            set_lifecycle(pid, "unavailable")
            startup_health(model, status="error", error=error)
            return JSONResponse(status_code=500, content={
                "id": pid, "model": model, "alive": False,
                "selection_saved": True,
                "error": (f"{pid}'s {model} cockpit could not start "
                          f"({type(error).__name__}); the model choice is "
                          "saved for the next household boot")})
        app.state.processes[pid] = proc
        ready = proc.wait_ready()
        if not ready and not proc.alive():
            app.state.processes.pop(pid, None)
            set_lifecycle(pid, "unavailable")
            startup_health(
                model, status="error",
                error=RuntimeError("model cockpit exited during startup"))
            return JSONResponse(status_code=503, content={
                "id": pid, "model": model, "alive": False,
                "ready": False, "selection_saved": True,
                "error": (f"{pid}'s {model} cockpit exited during startup; "
                          "the model choice is saved for the next household "
                          "boot")})
        if ready:
            set_lifecycle(pid, "ready")
            startup_health(model, status="ok")
        else:
            # An owned process that has not answered yet is still starting,
            # not failed. The process-bound watcher will settle the state on
            # a real readiness event or a real process exit.
            set_lifecycle(pid, "starting")
            start_readiness_watch(pid, proc, model)
        return {"id": pid, "model": model, "port": proc.port,
                "alive": proc.alive(), "ready": ready,
                "lifecycle": "ready" if ready else "starting"}

    @app.post("/api/personas/{pid}/stop")
    def persona_stop(pid: str):
        proc = app.state.processes.get(pid)
        if proc is None or not proc.alive():
            set_lifecycle(pid, "stopped")
            return {"id": pid, "alive": False, "note": "not running"}
        shutdown_receipt = checkpoint_then_stop(proc)
        set_lifecycle(pid, "stopped")
        return {"id": pid, "alive": proc.alive(), "lifecycle": "stopped",
                "shutdown_receipt": shutdown_receipt}

    @app.post("/api/shutdown/checkpoint")
    def household_shutdown_checkpoint():
        """Stop admissions, then checkpoint and stop each owned resident."""
        app.state.shutdown_event.set()
        with app.state.process_lock:
            processes = list(app.state.processes.items())
        receipts_by_pid = {}
        if processes:
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(8, len(processes)),
                    thread_name_prefix="resident-checkpoint") as pool:
                futures = {
                    pid: pool.submit(proc.checkpoint_and_stop)
                    for pid, proc in processes}
                for pid, future in futures.items():
                    try:
                        receipts_by_pid[pid] = future.result(timeout=27.0)
                    except Exception as exc:
                        receipts_by_pid[pid] = {
                            "persona": pid, "verdict": "unknown",
                            "reason": ("checkpoint_worker_failed:"
                                       f"{type(exc).__name__}"),
                            "stopped": False, "content_free": True,
                        }
        receipts = []
        for pid, _proc in processes:
            receipt = receipts_by_pid[pid]
            receipts.append(receipt)
            set_lifecycle(pid, "stopped" if receipt.get("stopped")
                          else "unavailable")
        all_clean = all(
            item.get("verdict") == "clean" and item.get("stopped")
            for item in receipts)
        return {
            "schema_version": 1,
            "kind": "household_shutdown_checkpoint",
            "verdict": "clean" if all_clean else "unclean",
            "resident_receipts": receipts,
            "resident_count": len(receipts),
            "content_free": True,
        }

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
    def list_models(include_internal: bool = False):
        """The spec registry reading itself: every specs/models/*.yaml
        is a dropdown entry. Reports whether the Anthropic key is SET
        (presence only — values never cross this API)."""
        from harness.spec_loader import load_all
        models = []
        for spec in load_all():
            ident = spec.get("identity") or {}
            # Internal purpose routes remain loadable by name without
            # masquerading as conversational vessels in Settings.
            if ident.get("catalog_visible") is False and not include_internal:
                continue
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
                "service": ident.get("service"),
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
            declared_max = int((spec.get("runtime") or {}).get(
                "vision_max_tokens", 420))
            observation = (client.chat(
                "Report observable visual features only. Do not infer emotion, intent, or symbolism.",
                "Describe this public JNSQ test icon in one short sentence.",
                max_tokens=max(48, min(420, declared_max)), temperature=0.0,
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
                                       api_key_env=req.api_key_env,
                                       connect_timeout_s=req.connect_timeout_s,
                                       read_timeout_s=req.read_timeout_s,
                                       write_timeout_s=req.write_timeout_s,
                                       pool_timeout_s=req.pool_timeout_s)
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
        for name, label in (("HUME_API_KEY", "Hume Octave voice output"),
                            ("ELEVENLABS_API_KEY", "ElevenLabs voice output")):
            needed.setdefault(name, {"optional": True, "used_by": []})[
                "used_by"].append(label)
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

    def _proxy(pid: str, path: str, payload=None, timeout=30,
               method="POST"):
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
                    method=method)
                r = urllib.request.urlopen(rq, timeout=timeout)
            return JSONResponse(status_code=r.status,
                                content=json.loads(r.read()))
        except urllib.error.HTTPError as e:
            return JSONResponse(status_code=e.code,
                                content=json.loads(e.read()))

    def _proxy_audio(pid: str, path: str, payload: dict, timeout=180):
        proc = app.state.processes.get(pid)
        if proc is None or not proc.alive():
            return JSONResponse(status_code=503, content={
                "error": f"persona '{pid}' not running; start them to audition"})
        request = urllib.request.Request(
            f"http://127.0.0.1:{proc.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as upstream:
                return Response(content=upstream.read(), media_type="audio/wav",
                                headers={"Cache-Control": "no-store",
                                         "X-JNSQ-Provider": "qwen3-tts"})
        except urllib.error.HTTPError as error:
            try:
                content = json.loads(error.read().decode("utf-8"))
            except Exception:
                content = {"error": str(error)}
            return JSONResponse(status_code=error.code, content=content)
        except Exception as error:
            return JSONResponse(status_code=503, content={
                "error": f"voice audition failed: {error}"})

    @app.get("/api/personas/{pid}/organs")
    def persona_organs(pid: str):
        """Proxy to the tenant's organs endpoint — the Je Ne Sais Quoi's JS is
        same-origin with the ROUTER, not the tenants, so world-membership
        toggles ride through here."""
        return _proxy(pid, "/api/organs")

    @app.post("/api/personas/{pid}/organs")
    def persona_set_organs(pid: str, req: dict):
        return _proxy(pid, "/api/organs", payload=req)

    @app.post("/api/personas/{pid}/visual-choice")
    def persona_visual_choice(pid: str, req: dict):
        """Stable localhost route to one resident's ephemeral gaze appraisal."""
        return _proxy(pid, "/api/perception/visual-choice",
                      payload=req, timeout=45)

    @app.post("/api/personas/{pid}/physical-eye/frame")
    def persona_physical_eye_frame(pid: str, req: dict):
        """Loopback return path for one pending physical-eye capture."""
        return _proxy(pid, "/api/perception/physical-eye/frame",
                      payload=req, timeout=8)

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

    @app.post("/api/personas/{pid}/voice-output/audition")
    def persona_voice_audition(pid: str, req: dict):
        text = str(req.get("text") or "").strip()
        if not text or len(text) > 600:
            return JSONResponse(status_code=400, content={
                "error": "audition text must contain 1 to 600 characters"})
        return _proxy_audio(pid, "/api/voice/synthesize", {"text": text})

    @app.post("/api/personas/{pid}/voice-output/reference")
    async def persona_voice_reference(pid: str, request: Request):
        """Store a consented voice reference through the settings surface."""
        app.state.registry = discover_personas()
        entry = app.state.registry.get(pid)
        if not entry or entry.get("kind") != "model_persona":
            return JSONResponse(status_code=404,
                                content={"error": f"no model persona '{pid}'"})
        audio = await request.body()
        if not audio or len(audio) > 15 * 1024 * 1024:
            return JSONResponse(status_code=400, content={
                "error": "voice reference must be a WAV file under 15 MB"})
        if not (audio.startswith(b"RIFF") and audio[8:12] == b"WAVE"):
            return JSONResponse(status_code=415, content={
                "error": "Chatterbox voice references must be WAV audio"})
        voice_dir = os.path.join(entry["dir"], "voice")
        os.makedirs(voice_dir, exist_ok=True)
        target = os.path.join(voice_dir, "chatterbox_reference.wav")
        temporary = target + ".tmp"
        with open(temporary, "wb") as handle:
            handle.write(audio)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return {"ok": True, "reference": "private persona reference",
                "bytes": len(audio)}

    @app.get("/api/personas/{pid}/altered-state")
    def persona_altered_state(pid: str):
        return _proxy(pid, "/api/altered-state")

    @app.post("/api/personas/{pid}/altered-state/request-consent")
    def persona_altered_state_request_consent(
            pid: str, req: AlteredConsentRequest):
        payload = (req.model_dump() if hasattr(req, "model_dump")
                   else req.dict())
        return _proxy(pid, "/api/altered-state/request-consent",
                      payload=payload)

    @app.post("/api/personas/{pid}/altered-state/cancel-consent")
    def persona_altered_state_cancel_consent(pid: str):
        return _proxy(pid, "/api/altered-state/cancel-consent", payload={})

    @app.post("/api/personas/{pid}/altered-state/begin")
    def persona_altered_state_begin(pid: str, req: AlteredStateRequest):
        payload = (req.model_dump() if hasattr(req, "model_dump")
                   else req.dict())
        return _proxy(pid, "/api/altered-state/begin", payload=payload)

    @app.post("/api/personas/{pid}/altered-state/abort")
    def persona_altered_state_abort(pid: str):
        return _proxy(pid, "/api/altered-state/abort", payload={})

    @app.post("/api/personas/{pid}/altered-state/adjust")
    def persona_altered_state_adjust(pid: str, req: AlteredDoseRequest):
        payload = (req.model_dump() if hasattr(req, "model_dump")
                   else req.dict())
        return _proxy(pid, "/api/altered-state/adjust", payload=payload)

    @app.get("/api/personas/{pid}/agency/status")
    def persona_agency_status(pid: str):
        """Proxy the tenant-owned controller view without owning its task."""
        return _proxy(pid, "/api/agency/status")

    @app.get("/api/personas/{pid}/autonomous-works")
    def persona_autonomous_works(pid: str):
        """Read one resident's owned work index for the household shelf.

        The tenant still constructs the projection and owns every content
        reader.  The router only provides a stable, same-origin window for
        the household UI; it cannot create, circulate, or disclose a work.
        """
        return _proxy(pid, "/api/autonomous-works")

    @app.post("/api/personas/{pid}/agency/inbox")
    def persona_agency_inbox(pid: str, req: AgencyInboxRequest):
        payload = (req.model_dump() if hasattr(req, "model_dump")
                   else req.dict())
        return _proxy(pid, "/api/agency/inbox", payload=payload)

    @app.get("/api/personas/{pid}/agency/artifacts")
    def persona_agency_artifacts(pid: str):
        return _proxy(pid, "/api/agency/artifacts")

    @app.get("/api/personas/{pid}/agency/artifacts/{name}")
    def persona_agency_artifact(pid: str, name: str):
        from urllib.parse import quote
        return _proxy(pid, "/api/agency/artifacts/" + quote(name, safe=""))

    @app.get("/api/personas/{pid}/mcp-library")
    def persona_mcp_library(pid: str):
        return _proxy(pid, "/api/mcp-library")

    @app.post("/api/personas/{pid}/mcp-library/probe")
    def persona_mcp_library_probe(pid: str):
        return _proxy(pid, "/api/mcp-library/probe", payload={})

    @app.post("/api/personas/{pid}/mcp-library/inspect")
    def persona_mcp_library_inspect(pid: str, req: MCPLibraryConfigRequest):
        payload = (req.model_dump() if hasattr(req, "model_dump")
                   else req.dict())
        return _proxy(pid, "/api/mcp-library/inspect", payload=payload)

    @app.put("/api/personas/{pid}/mcp-library")
    def persona_mcp_library_save(pid: str, req: MCPLibraryConfigRequest):
        payload = (req.model_dump() if hasattr(req, "model_dump")
                   else req.dict())
        return _proxy(pid, "/api/mcp-library", payload=payload,
                      method="PUT")

    @app.post("/api/personas/{pid}/turn")
    def persona_turn(pid: str, req: TurnRequest):
        proc = app.state.processes.get(pid)
        if proc is None or not proc.alive():
            return JSONResponse(status_code=503, content={"error": f"persona '{pid}' not running"})
        try:
            body = json.dumps({"message": req.message,
                               "speaker": req.speaker or app.state.local_identity[
                                   "display_name"],
                               "user_persona": req.user_persona,
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

    app = build_app(room_url=args.room_url, record_health=True,
                    auto_launch=True)

    import uvicorn
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        app.state.shutdown_all()


if __name__ == "__main__":
    main()
