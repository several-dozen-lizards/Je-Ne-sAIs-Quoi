"""shell/cockpit.py — CLIENT #2 of the turn-loop contract: the web cockpit.
One page, three endpoints, zero opinions. The server is deliberately a
pass-through: every route body is a single TurnEngine call. If the cockpit
ever needs to know something the contract doesn't expose, the CONTRACT
grows (versioned), never a side door.

Run:  python shell/cockpit.py [--persona vex] [--model llama3-1-8b] [--port 8642]
Then open http://127.0.0.1:8642 — chat left, instruments right,
receipts drawer below. One turn at a time (one body, one mouth)."""
import argparse
import base64
import binascii
import json
import math
import os
import queue
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shell import env_store  # loads .env into os.environ (idempotent; no-op
env_store.load_env()         # when router-launched, since inherited vars win)
from fastapi import FastAPI, Query
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from shell.contract import TurnEngine, CONTRACT_VERSION
from shell.agency_controller import AgencyRunController
from shell.ui_themes import resolve_theme, save_theme
from shell.persona_media import load_persona_avatar
from shell.ui_background import (delete_conversation_background,
                                 load_conversation_background,
                                 save_conversation_background)
from shell.image_input import public_image_record, store_images, stored_image_path
from core.organs import (legacy_set, validate as validate_organs,
                         OrganConfigError, REGISTRY)
from core.sensory import SensoryEvent
from core.speech import (MAX_AUDIO_BYTES, build_transcriber, turn_admission,
                         validate_audio)
from core.observatory import SalienceObserver
from core.memory_observatory import MemoryObservatory
from core.voice_output import append_output_receipt
from core.documents import DocumentError
from core.conversation_archive import ArchiveError
from harness.model_call_receipts import model_call_scope, new_cycle_id

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ASSET_DIR = os.path.join(REPO, "assets", "jnsq")


def load_roster_entry(persona: str, model: str):
    """Read personas/<persona>/roster.yaml; return (entry, roster) for
    this model. (None, roster) if the model isn't in the entries;
    (None, None) if there is no roster at all — legacy-shim territory
    (vex and other fixtures). The roster is the SOURCE OF TRUTH for
    enabled_organs (par 2.6); the router no longer translates flags."""
    import yaml
    path = os.path.join(REPO, "personas", persona, "roster.yaml")
    if not os.path.exists(path):
        return None, None
    with open(path, encoding="utf-8") as f:
        roster = yaml.safe_load(f) or {}
    for e in roster.get("entries") or []:
        if e.get("model") == model:
            return e, roster
    return None, roster


def _canonical_organs(enabled):
    validate_organs(enabled)
    chosen = set(enabled or [])
    return [oid for oid in REGISTRY if oid in chosen]


def _model_entry_bounds(lines, model: str):
    """Return (start, end, indent) for one roster model entry."""
    import re
    import yaml

    for i, line in enumerate(lines):
        if not re.match(r"^\s*-\s+model\s*:", line):
            continue
        try:
            parsed_line = yaml.safe_load(line.lstrip())
            found_model = parsed_line[0].get("model")
        except Exception:
            continue
        if found_model != model:
            continue
        entry_indent = len(line) - len(line.lstrip(" "))
        end = len(lines)
        for j in range(i + 1, len(lines)):
            stripped = lines[j].strip()
            indent = len(lines[j]) - len(lines[j].lstrip(" "))
            if stripped and (indent < entry_indent
                             or (indent == entry_indent
                                 and re.match(r"^-\s+model\s*:",
                                              lines[j].lstrip()))):
                end = j
                break
        return i, end, entry_indent
    raise ValueError(f"model '{model}' has no roster entry")


def _field_bounds(lines, start: int, end: int, key: str,
                  required_indent=None):
    """Locate a YAML field and its indented continuation lines."""
    import re

    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:")
    for i in range(start, end):
        indent = len(lines[i]) - len(lines[i].lstrip(" "))
        if required_indent is not None and indent != required_indent:
            continue
        if not pattern.match(lines[i]):
            continue
        field_end = i + 1
        while field_end < end:
            stripped = lines[field_end].strip()
            next_indent = (len(lines[field_end])
                           - len(lines[field_end].lstrip(" ")))
            if not stripped or next_indent <= indent:
                break
            field_end += 1
        return i, field_end, indent
    return None, None, required_indent


def _replace_model_organs(text: str, model: str, enabled) -> str:
    """Replace one model entry's enabled_organs while preserving every
    other roster byte, including comments and hand wrapping."""
    import re
    import yaml

    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    wanted = _canonical_organs(enabled)
    start, end, entry_indent = _model_entry_bounds(lines, model)
    key_start, key_end, key_indent = _field_bounds(
        lines, start + 1, end, "enabled_organs")
    if key_indent is None:
        key_indent = entry_indent + 2

    rendered = (" " * key_indent + "enabled_organs: ["
                + ", ".join(wanted) + "]" + newline)
    if key_start is None:
        key_start = key_end = start + 1
    candidate = "".join(lines[:key_start] + [rendered]
                        + lines[key_end:])

    parsed = yaml.safe_load(candidate) or {}
    matches = [e for e in parsed.get("entries") or []
               if e.get("model") == model]
    if len(matches) != 1 or matches[0].get("enabled_organs") != wanted:
        raise ValueError("roster organ edit failed validation")
    return candidate


def _replace_persona_organs(text: str, model: str, enabled) -> str:
    """Save a persona default and make this model inherit it.

    Other models keep their explicit overrides. Comments and hand wrapping
    outside the two edited fields remain byte-for-byte intact.
    """
    import re
    import yaml

    wanted = _canonical_organs(enabled)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)

    # A persona save means the current model must flow through the persona
    # default, while every other model override remains exactly as declared.
    start, end, _indent = _model_entry_bounds(lines, model)
    key_start, key_end, _ = _field_bounds(
        lines, start + 1, end, "enabled_organs")
    if key_start is not None:
        del lines[key_start:key_end]

    top_start, top_end, _ = _field_bounds(
        lines, 0, len(lines), "enabled_organs", required_indent=0)
    rendered = "enabled_organs: [" + ", ".join(wanted) + "]" + newline
    if top_start is not None:
        lines[top_start:top_end] = [rendered]
    else:
        entries_at = next((i for i, line in enumerate(lines)
                           if re.match(r"^entries\s*:", line)), None)
        if entries_at is None:
            raise ValueError("roster has no entries block")
        lines[entries_at:entries_at] = [rendered]

    candidate = "".join(lines)
    parsed = yaml.safe_load(candidate) or {}
    matches = [e for e in parsed.get("entries") or []
               if e.get("model") == model]
    if (parsed.get("enabled_organs") != wanted or len(matches) != 1
            or matches[0].get("enabled_organs") is not None):
        raise ValueError("persona organ edit failed validation")
    return candidate


def roster_organ_preference(entry, roster):
    """Resolve the declared cascade without inventing a preference."""
    if entry is not None and entry.get("enabled_organs") is not None:
        return list(entry["enabled_organs"]), "model"
    if roster is not None and roster.get("enabled_organs") is not None:
        return list(roster["enabled_organs"]), "persona"
    return None, "runtime"


def _save_roster_organs(persona: str, model: str, enabled, scope: str,
                        repo: str = REPO) -> bool:
    path = os.path.join(repo, "personas", persona, "roster.yaml")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8", newline="") as f:
        original = f.read()
    editor = (_replace_persona_organs if scope == "persona"
              else _replace_model_organs)
    candidate = editor(original, model, enabled)
    with open(path + ".prev", "w", encoding="utf-8", newline="") as f:
        f.write(original)
    tmp = path + ".tmp_organs"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(candidate)
    os.replace(tmp, path)
    return True


def save_model_organs(persona: str, model: str, enabled,
                      repo: str = REPO) -> bool:
    """Atomically persist one persona+model organ preference.

    Rosterless fixtures remain runtime-only. Existing rosters fail closed:
    a missing model or invalid edit leaves the original untouched.
    """
    return _save_roster_organs(persona, model, enabled, "model", repo)


def save_persona_organs(persona: str, model: str, enabled,
                        repo: str = REPO) -> bool:
    """Persist a persona default; current model inherits that default."""
    return _save_roster_organs(persona, model, enabled, "persona", repo)


def heartbeat_loop(engine, turn_lock, interval_s: float, stop):
    """The body's own clock: osc/soma advance whether or not anyone is
    talking, via the SAME settle() take_turn uses — one clock, one
    timestamp, no double-ticking. Self-gates per tick on the live
    enabled set (runtime toggleable from the organs panel). Skips
    beats while a turn is in flight: the turn settles itself.
    Receipts (only when steps fire) to <persona>/history/heartbeat.jsonl."""
    import json
    import time
    log = os.path.join(engine.pdir, "history", "heartbeat.jsonl")
    while not stop.wait(interval_s):
        if "heartbeat" not in engine.enabled:
            continue          # runtime toggle: the loop idles, not dies
        if not turn_lock.acquire(blocking=False):
            continue          # a turn is mid-flight; it settles itself
        try:
            steps = engine.settle()
            if steps:
                if engine.osc:
                    engine.osc.save()
                if engine.soma:
                    engine.soma.save()
                with open(log, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "steps": steps,
                        "band": (engine.osc.dominant()
                                 if engine.osc else None)},
                        ensure_ascii=False) + "\n")
        except Exception:
            pass              # the heart must never kill the body
        finally:
            turn_lock.release()


def social_loop(engine, turn_lock, interval_s: float, max_tokens: int,
                stop):
    """The social-pressure thread: unheard speech in your room builds
    pressure; discharge delivers it as a labeled self-initiated turn,
    and the reply is SAID back into the room (reply-to-room-speech IS
    room-speech). Habituation winds conversations down; hourly cap and
    the shared turn lock keep it from ever running away or talking
    over Re. Receipts to <persona>/history/social.jsonl."""
    import json
    import time
    from core.social_pressure import SocialPressure, load_params
    from shell.autonomy_circulation import readiness_from_engine
    sp = SocialPressure(engine.persona, load_params(engine.pdir))
    log = os.path.join(engine.pdir, "history", "social.jsonl")
    cursor, cursor_room = None, None
    last_said = ""
    last = time.time()
    while not stop.wait(interval_s):
        if engine.room is None or not engine.room.room_id:
            continue
        if "social" not in engine.enabled:
            continue          # runtime toggle: the loop idles, not dies
        try:
            rid = engine.room.room_id
            if cursor is None or cursor_room != rid:
                snap = engine.room.snapshot()
                cursor = snap.get("last_seq", 0)
                cursor_room = rid
                # boot-window fix: an unanswered hello from someone
                # STILL IN THE ROOM survives a reboot — presence is
                # the freshness test, no timestamps needed.
                present = set((snap.get("members") or {}).keys())
                r0 = engine.room._req(
                    f"/api/rooms/{rid}/events?since={max(0, cursor - 12)}")
                window = r0.get("events", [])
                my_last_say = max((e["seq"] for e in window
                                   if e.get("kind") == "say"
                                   and e.get("member") == engine.persona),
                                  default=0)
                unanswered = [e for e in window
                              if e.get("kind") == "say"
                              and e.get("member") != engine.persona
                              and e.get("member") in present
                              and e["seq"] > my_last_say]
                if unanswered:
                    sp.note_events(unanswered, dict(engine.organ.bonds))
                continue
            now = time.time()
            dt, last = now - last, now
            r = engine.room._req(
                f"/api/rooms/{rid}/events?since={cursor}")
            evs = r.get("events", [])
            if evs:
                cursor = max(e["seq"] for e in evs)
                sp.note_events(evs, dict(engine.organ.bonds))
            autonomy = readiness_from_engine(
                engine, getattr(engine, "idle_metabolism", None))
            delivery = sp.tick(
                now, dt, action_readiness=autonomy["readiness"],
                hard_blocked=autonomy["hard_blocked"])
            entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     **sp.state(),
                     "autonomy": {
                         key: autonomy[key] for key in (
                             "readiness", "capacity", "support",
                             "hard_blocked", "reasons")}}
            if delivery and turn_lock.acquire(blocking=False):
                try:
                    result = engine.take_turn(delivery["text"],
                                              max_tokens=max_tokens,
                                              speaker=delivery["speaker"],
                                              channel="room")
                    reply = (result.get("reply") or "").strip()
                    if reply and reply == last_said:
                        # stuck record: a verbatim repeat of your own
                        # last say is a malfunction artifact, not
                        # expression. Skip it, receipt it.
                        entry["skipped_repeat"] = True
                        reply = ""
                    if reply:
                        engine.room.say(reply)
                        last_said = reply
                    entry["answered"] = {"to": delivery["speaker"],
                                         "reply_len": len(reply)}
                finally:
                    turn_lock.release()
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass          # the social thread must never kill the body


def tropism_loop(engine, turn_lock, interval_s: float, stop):
    """The worm thread: perceive -> pressure -> maybe move. No language
    in the loop; the body wanders and the next turn discovers where it
    is. Skips ticks while a turn is in flight. Everything receipted to
    <persona>/history/tropism.jsonl."""
    import json
    import time
    from core.place_intentions import PlaceIntentions, load_params
    from core.perception import score_objects, score_members, REACH_M
    from shell.autonomy_circulation import (
        circulate_experienced_event, readiness_from_engine,
    )
    worm = PlaceIntentions(load_params(engine.pdir))
    log = os.path.join(engine.pdir, "history", "tropism.jsonl")
    last = time.time()
    while not stop.wait(interval_s):
        if engine.room is None:
            continue
        if "tropism" not in engine.enabled:
            continue          # runtime toggle: the loop idles, not dies
        if not turn_lock.acquire(blocking=False):
            continue                     # a turn is speaking; don't race it
        try:
            now = time.time()
            dt, last = now - last, now
            snap = engine.room.snapshot()
            me = (snap.get("members") or {}).get(engine.persona)
            if not snap or me is None:
                continue
            st = engine.get_state()
            substrate = {"cocktail": st["cocktail"],
                         "bands": st["bands"] or {},
                         "bonds": (dict(engine.organ.bonds)
                                   if engine.organ else {})}
            objs = score_objects(snap, substrate, engine.room_bias,
                                 engine.persona)
            # the social intake (2026-07-03): members join the worm's
            # diet as bond-weighted candidates. Same shape; the worm
            # can't tell an armchair from a friend — the SALIENCE can.
            objs = objs + score_members(snap, substrate,
                                        engine.room_bias,
                                        engine.persona)
            within = {o["id"] for o in objs if o["dist_m"] <= REACH_M}
            at = min((o for o in objs if o["id"] in within),
                     key=lambda o: o["dist_m"], default=None)
            at = at["id"] if at else None
            hold = getattr(engine, "last_volitional_move", 0.0) + 240.0
            autonomy = readiness_from_engine(
                engine, getattr(engine, "idle_metabolism", None))
            moved_to = worm.tick(objs, at, now, dt, at_objects=within,
                                 volitional_hold_until=hold,
                                 action_readiness=autonomy["readiness"],
                                 hard_blocked=autonomy["hard_blocked"])
            consequence = None
            if moved_to:
                target = moved_to
                result = engine.room.move(target)
                moved_to = {"to": target, "result": result}
                if isinstance(result, dict) and result.get("ok"):
                    destination = result.get("position_m") or me
                    distance_m = math.dist(me, destination)
                    room_scale = max(
                        0.001, float(snap.get("radius_m") or 1.0))
                    movement_load = distance_m / (distance_m + room_scale)
                    event_text = (
                        "An autonomous bodily movement carried the persona "
                        f"toward {target} and arrived after crossing "
                        f"{movement_load:.3f} of the local room scale.")
                    try:
                        consequence = circulate_experienced_event(
                            engine, event_text,
                            somatic_regions={
                                "legs": {"activation": movement_load}})
                        field = getattr(engine, "idle_metabolism", None)
                        if field is not None:
                            candidate = field.offer_event(
                                "proprioception",
                                f"Your body moved toward {target} and arrived.",
                                {
                                    "novelty": 0.0,
                                    "affect_change": consequence.get(
                                        "affect_change", 0.0),
                                    "body_intensity": movement_load,
                                    "relationship": (
                                        1.0 if target in
                                        (snap.get("members") or {}) else 0.0),
                                    "unresolved": 0.0,
                                },
                                key=f"proprioception:move:{target}",
                                now=now, raw_ref=target,
                                ownership="persona_private")
                            field.save(now=now)
                            observer = getattr(
                                engine, "salience_observer", None)
                            if observer is not None:
                                observer.field_snapshot(field, now)
                            consequence["candidate_key"] = candidate.get(
                                "key")
                    except Exception as exc:
                        consequence = {
                            "error": type(exc).__name__,
                            "detail": str(exc)[:160]}
            worm_state = worm.state()
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "at": at, "discharged": moved_to,
                    "pressure": worm_state["pressure"],
                    "gate": worm_state.get("gate"),
                    "autonomy": {
                        key: autonomy[key] for key in (
                            "readiness", "capacity", "support",
                            "hard_blocked", "reasons")},
                    "consequence": ({
                        "felt": sorted(consequence.get("felt") or {}),
                        "why": str(consequence.get("why") or "")[:240],
                        "affect_change": consequence.get("affect_change"),
                        "somatic_regions": consequence.get(
                            "somatic_regions", []),
                        "candidate_key": consequence.get("candidate_key"),
                        "error": consequence.get("error"),
                    } if consequence else None)},
                    ensure_ascii=False) + "\n")
        except Exception:
            pass                          # the worm must never kill the body
        finally:
            turn_lock.release()


class ImageRequest(BaseModel):
    name: str = "image"
    data_url: str


class AmbientFrameRequest(BaseModel):
    image: ImageRequest
    novelty: float = Field(ge=0.0, le=1.0)
    pressure: float = Field(default=0.0, ge=0.0, le=2.0)
    features: dict = Field(default_factory=dict)


class AmbientAudioRequest(BaseModel):
    features: dict = Field(default_factory=dict)
    pressure: float = Field(default=0.0, ge=0.0, le=2.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SubstrateSummaryRequest(BaseModel):
    """One browser interval at the body's existing resolution."""
    batch_id: str = ""
    duration_s: float = Field(ge=0.0, le=600.0)
    audio: dict = None
    camera: dict = None


class SpeechRequest(BaseModel):
    data_url: str
    mime_type: str = "audio/wav"
    features: dict = Field(default_factory=dict)
    pressure: float = Field(default=0.0, ge=0.0, le=2.0)
    speaker: str = None
    auto_turn: bool = False


class SensoryEventRequest(BaseModel):
    modality: str
    features: dict = Field(default_factory=dict)
    subject: str = "environment"
    ownership: str = "ambient"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    content: str = ""


class TurnRequest(BaseModel):
    message: str
    speaker: str = None      # omitted means this installation's local human
                            # anonymous crosses (v1 nexus law, kept)
    images: list[ImageRequest] = Field(default_factory=list)


class MoodRequest(BaseModel):
    cocktail: dict


class OrganRequest(BaseModel):
    enabled: list
    scope: str = "model"


class ThemeRequest(BaseModel):
    scope: str
    patch: dict
    reset: bool = False
    replace: bool = False


class ConversationBackgroundRequest(BaseModel):
    data_url: str


class VoiceOutputRequest(BaseModel):
    event: str
    provider: str = "browser-native"
    reason: str = ""
    policy: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)


class AgencyInboxRequest(BaseModel):
    label: str
    content: str


class DocumentImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    data_url: str
    content_type: str = Field(default="", max_length=160)


class DocumentOpenRequest(BaseModel):
    position: int = Field(default=0, ge=0)


class DocumentNavigateRequest(BaseModel):
    action: str
    position: int | None = Field(default=None, ge=0)


class ArchiveOpenRequest(BaseModel):
    section: int = Field(default=1, ge=1)


class ArchiveNavigateRequest(BaseModel):
    action: str
    section: int | None = Field(default=None, ge=1)


class ArchiveBookmarkRequest(BaseModel):
    anchor: str | None = None


class WritingDeskSeedRequest(BaseModel):
    label: str = Field(min_length=1, max_length=260)
    content: str = ""
    anchors: list[str] = Field(default_factory=list)


class AtelierSeedRequest(BaseModel):
    label: str = Field(min_length=1, max_length=260)
    brief: str = Field(min_length=1, max_length=6000)


class AtelierPerceptionRequest(BaseModel):
    image: ImageRequest


class ResearchInterestRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=240)


def _background_adapter(engine, model: str):
    """Reuse a model vessel across autonomous cycles in this live engine."""
    from adapters.family_adapters import adapter_for
    from harness.spec_loader import load_spec
    cache = getattr(engine, "_background_adapters", None)
    if cache is None:
        cache = {}
        setattr(engine, "_background_adapters", cache)
    adapter = cache.get(model)
    if adapter is None:
        adapter = adapter_for(load_spec(model))
        cache[model] = adapter
    return adapter


def generate_idle_thought(engine, idle_model: str, item: dict,
                          drift_kind: str, sensory_source: str = None, *,
                          cycle_id: str = None,
                          model_receipts: list = None) -> str:
    """Ask the configured idle vessel what arises; do not prescribe feeling.

    Kept separate from dmn_loop so transport failure and prompt law are
    mechanically testable without starting a thread.
    """
    from adapters.assembly import PromptAssembly
    adapter = _background_adapter(engine, idle_model)
    asm = PromptAssembly()
    asm.add("identity", engine.identity, priority=10, stable=True)
    asm.add("current interior", f"Mood: {engine.cocktail}", priority=8)
    if sensory_source:
        modality = {
            "camera": "saw",
            "microphone": "heard",
            "overheard_speech": "overheard speech",
        }.get(str(sensory_source), "perceived")
        asm.add("sensory origin", modality, priority=9)
    asm.add("unbidden pull", item.get("node") or item.get("text") or "",
            priority=9)
    asm.messages.append({
        "role": "user",
        "content": (
            "No one is speaking to you. Something has surfaced on its own. "
            f"The movement is {drift_kind}. What, if anything, is moving "
            "through your mind? Follow the felt pull rather than explaining "
            "the mechanism. Silence is valid: return [quiet] if nothing wants "
            "language. Otherwise write only the private thought, in your own "
            "voice, with no labels or preamble. Let this one movement end "
            "where it naturally settles; do not keep writing merely because "
            "space remains.")})
    with model_call_scope(
            cycle_id=cycle_id or new_cycle_id(),
            persona=getattr(engine, "persona", "unknown"),
            purpose="dmn", sink=model_receipts):
        return (adapter.call(
            asm, max_tokens=220, temperature=0.8) or "").strip()


def attach_idle_metabolism(engine, metabolism: dict):
    """Attach the one persisted field before HTTP or background loops race."""
    from core.dmn import IdleMetabolism
    current = getattr(engine, "idle_metabolism", None)
    if current is not None:
        if getattr(engine, "salience_observer", None) is None:
            path = os.path.join(engine.pdir, "history", "salience.jsonl")
            engine.salience_observer = SalienceObserver(engine.persona, path)
            current.set_observer(engine.salience_observer)
        return current
    state_path = os.path.join(engine.pdir, "body", "dmn_state.json")
    engine.idle_metabolism = IdleMetabolism.load(metabolism["params"], state_path)
    path = os.path.join(engine.pdir, "history", "salience.jsonl")
    engine.salience_observer = SalienceObserver(engine.persona, path)
    engine.idle_metabolism.set_observer(engine.salience_observer)
    return engine.idle_metabolism


def _one_way_id(value) -> str | None:
    """Content-free source identity for consolidation receipts."""
    if not value:
        return None
    import hashlib
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _artifact_sha256(path: str) -> str | None:
    if not path or not os.path.exists(path):
        return None
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gist_turn_records(engine) -> list:
    """One chronological consolidation source, read only by the idle owner."""
    if not getattr(engine, "organ", None):
        return []
    return [memory for memory in engine.organ.memories
            if memory.get("type") in ("turn", "observed")]


def offer_gist_consolidation(engine, field, now: float = None):
    """Project aged narrative backlog into the shared salience field."""
    from core.memory_emotion.gist import render_turn
    gist = getattr(engine, "gist", None)
    if gist is None:
        return None
    records = _gist_turn_records(engine)
    pending = gist.pending_turn_records(records)
    if not pending:
        return None
    pending_chars = sum(len(render_turn(record)) for record in pending)
    return field.offer_consolidation(
        source_cursor=gist.upto,
        eligible_count=len(pending),
        pending_source_chars=pending_chars,
        source_char_budget=gist.source_char_budget,
        first_source_digest=_one_way_id(pending[0].get("id")),
        last_source_digest=_one_way_id(pending[-1].get("id")),
        now=now)


def execute_gist_consolidation(engine, field, item: dict, receipt,
                               now: float = None) -> dict:
    """Commit one bounded fold or restore the candidate without data loss."""
    import time as _time
    gist = getattr(engine, "gist", None)
    if gist is None:
        reason = "gist_disabled"
        field.pressure.refund()
        field.queue.put(
            item, item.get("salience", 0.0), now=now,
            offer_meta={"operation": "requeued", "reason": reason})
        receipt("consolidation", outcome="requeued", reason=reason,
                candidate_key=item.get("key"), consumed_count=0)
        field.save(now=now)
        return {"committed": False, "reason": reason,
                "consumed_count": 0}
    records = _gist_turn_records(engine)
    cursor_before = int(gist.upto)
    gist_hash_before = _artifact_sha256(gist.path)
    if not gist.pending_turn_records(records):
        # A persisted candidate can outlive the backlog it represented across
        # a restart. Drop that stale projection, refund the fire, and let the
        # next field winner be chosen; requeueing it would create a dead loop.
        field.pressure.refund()
        receipt(
            "consolidation", outcome="obsolete",
            reason="no_aged_sources", candidate_key=item.get("key"),
            candidate_salience=round(float(item.get("salience", 0.0)), 6),
            source_cursor_before=cursor_before,
            source_cursor_after=cursor_before, consumed_count=0,
            gist_sha256_before=gist_hash_before,
            gist_sha256_after=gist_hash_before,
            model=getattr(
                engine, "gist_model",
                getattr(engine, "affect_model", None)),
            duration_ms=0.0)
        field.save(now=now)
        return {"committed": False, "obsolete": True,
                "reason": "no_aged_sources", "consumed_count": 0}
    started = _time.perf_counter()
    with model_call_scope(
            cycle_id=new_cycle_id(),
            persona=getattr(engine, "persona", "unknown"),
            purpose="gist"):
        changed = bool(gist.update(records, force=True))
    duration_ms = (_time.perf_counter() - started) * 1000.0
    cursor_after = int(gist.upto)
    gist_hash_after = _artifact_sha256(gist.path)
    consumed = max(0, cursor_after - cursor_before)
    consumed_records = records[cursor_before:cursor_after]
    common = {
        "candidate_key": item.get("key"),
        "candidate_salience": round(float(item.get("salience", 0.0)), 6),
        "eligible_count": int(item.get("eligible_count", 0)),
        "pending_source_chars": int(item.get("pending_source_chars", 0)),
        "source_char_budget": int(item.get("source_char_budget", 0)),
        "source_cursor_before": cursor_before,
        "source_cursor_after": cursor_after,
        "consumed_count": consumed,
        "first_consumed_digest": (
            _one_way_id(consumed_records[0].get("id"))
            if consumed_records else None),
        "last_consumed_digest": (
            _one_way_id(consumed_records[-1].get("id"))
            if consumed_records else None),
        "gist_sha256_before": gist_hash_before,
        "gist_sha256_after": gist_hash_after,
        "model": getattr(
            engine, "gist_model",
            getattr(engine, "affect_model", None)),
        "duration_ms": round(duration_ms, 3),
    }
    if changed and consumed > 0:
        field.satiate(item, now=now)
        receipt("consolidation", outcome="committed", **common)
        field.save(now=now)
        return {"committed": True, **common}

    reason = gist.last_error or "no_fold_committed"
    field.pressure.refund()
    field.queue.put(
        item, item.get("salience", 0.0), now=now,
        offer_meta={"operation": "requeued", "reason": reason})
    receipt("consolidation", outcome="requeued",
            reason=str(reason)[:200], **common)
    field.save(now=now)
    return {"committed": False, "reason": reason, **common}


def project_narrative_neighborhood(engine, seed_id: str) -> dict | None:
    """Read one local episodic neighborhood from the live memory organ."""
    organ = getattr(engine, "organ", None)
    if organ is None or not hasattr(organ, "vectors") \
            or not hasattr(organ, "_context_cues"):
        return None
    from core.memory_emotion.clusters import project_local_neighborhood
    configured_window = int(getattr(
        engine, "window_k", (getattr(organ, "cfg", {}) or {}).get(
            "working_window", 6)))
    working_ids = {memory.get("id") for memory in
                   organ.working_window(configured_window)}
    return project_local_neighborhood(
        organ.memories, organ.vectors, organ._context_cues,
        str(seed_id), working_ids=working_ids)


def offer_narrative_cluster(engine, field, hit: dict,
                            now: float = None):
    """Offer one naturally recalled seed's local witnesses after a fire."""
    memory = (hit or {}).get("memory") or {}
    seed_id = memory.get("id")
    if not seed_id:
        return None
    neighborhood = project_narrative_neighborhood(engine, seed_id)
    if not neighborhood:
        return None
    return field.offer_narrative_cluster(
        neighborhood, (hit or {}).get("score", 0.0), now=now)


def _narrative_judge(model: str, engine=None):
    """Build the declared idle vessel's direct structured reader."""
    if engine is not None:
        return _background_adapter(engine, model).client
    from adapters.family_adapters import adapter_for
    from harness.spec_loader import load_spec
    return adapter_for(load_spec(model)).client


def execute_narrative_cluster(engine, field, item: dict, receipt,
                              idle_model: str, now: float = None) -> dict:
    """Revalidate, appraise, and atomically admit one winning neighborhood."""
    import time as _time
    organ = getattr(engine, "organ", None)
    fresh = (project_narrative_neighborhood(engine, item.get("seed_id"))
             if organ is not None else None)
    candidate_ids = list(item.get("candidate_ids") or [])
    if not fresh or fresh.get("status") != "ready" \
            or fresh.get("candidate_ids") != candidate_ids:
        field.pressure.refund()
        result = {"status": "obsolete", "committed": False,
                  "reason": "neighborhood_changed"}
        receipt(
            "narrative_cluster", outcome="obsolete",
            reason=result["reason"], candidate_key=item.get("key"),
            seed_digest=_one_way_id(item.get("seed_id")),
            candidate_count=len(candidate_ids), model=idle_model,
            duration_ms=0.0)
        if getattr(engine, "salience_observer", None) is not None:
            engine.salience_observer.discharge(
                item, "obsolete", "",
                {"candidate_key": item.get("key"),
                 "reason": result["reason"]}, now)
        field.save(now=now)
        return result

    if not idle_model:
        field.pressure.refund()
        field.queue.put(
            item, item.get("salience", 0.0), now=now,
            offer_meta={"operation": "requeued",
                        "reason": "no_idle_model"})
        result = {"status": "provider_error", "committed": False,
                  "reason": "no_idle_model", "retryable": True}
        receipt("narrative_cluster", outcome="requeued",
                reason="no_idle_model", candidate_key=item.get("key"),
                candidate_count=len(candidate_ids), duration_ms=0.0)
        field.save(now=now)
        return result

    from core.memory_emotion.narrative import appraise_neighborhood
    canonical_before = _artifact_sha256(organ.store_path)
    started = _time.perf_counter()
    output_budget = int(getattr(getattr(engine, "gist", None),
                                "max_tokens", 700))
    source_budget = getattr(getattr(engine, "gist", None),
                            "source_char_budget", None)
    try:
        judge = _narrative_judge(idle_model, engine=engine)
        with model_call_scope(
                cycle_id=new_cycle_id(),
                persona=getattr(engine, "persona", "unknown"),
                purpose="narrative"):
            appraisal = appraise_neighborhood(
                judge, organ.memories, fresh,
                model=idle_model, max_tokens=output_budget,
                source_char_budget=source_budget)
    except Exception as error:
        appraisal = {
            "status": "provider_error", "reason": str(error),
            "retryable": True, "model": idle_model,
            "prompt_version": None,
        }
    if appraisal.get("status") == "narrative":
        context_builder = getattr(engine, "memory_context_snapshot", None)
        current_context = (context_builder(now=now)
                           if callable(context_builder) else None)
        admitted = organ.admit_narrative(
            appraisal, fresh, current_context)
    elif appraisal.get("status") == "no_cluster":
        admitted = {"status": "no_cluster", "committed": False,
                    "selected_count": appraisal.get("selected_count", 0)}
    else:
        admitted = {"status": appraisal.get("status", "invalid"),
                    "committed": False,
                    "reason": appraisal.get("reason", "appraisal_failed"),
                    "retryable": appraisal.get("retryable", False)}
    duration_ms = (_time.perf_counter() - started) * 1000.0
    outcome = admitted.get("status", "invalid")
    retryable = bool(admitted.get("retryable")) \
        or outcome == "write_failed"
    refundable = outcome in {"provider_error", "invalid", "write_failed"}
    if refundable:
        field.pressure.refund()
    if retryable:
        field.queue.put(
            item, item.get("salience", 0.0), now=now,
            offer_meta={"operation": "requeued", "reason": outcome})

    common = {
        "candidate_key": item.get("key"),
        "candidate_salience": round(float(item.get("salience", 0.0)), 6),
        "seed_digest": _one_way_id(item.get("seed_id")),
        "candidate_set_digest": _one_way_id("|".join(sorted(candidate_ids))),
        "candidate_count": len(candidate_ids),
        "selected_count": int(admitted.get(
            "selected_count", len(appraisal.get("selected_ids") or []))),
        "semantic_width": int(fresh.get("semantic_width", 0)),
        "context_width": int(fresh.get("context_width", 0)),
        "semantic_locality": round(float(
            fresh.get("semantic_locality") or 0.0), 6),
        "channel_overlap": int(fresh.get("channel_overlap", 0)),
        "seed_recall_score": round(float(
            item.get("seed_recall_score", 0.0)), 6),
        "seed_warmth": round(float(item.get("seed_warmth", 0.0)), 6),
        "outcome": ("requeued" if retryable else outcome),
        "reason": str(admitted.get("reason") or "")[:200] or None,
        "cluster_signature": appraisal.get("cluster_signature"),
        "new_memory_digest": _one_way_id(admitted.get("memory_id")),
        "audience": admitted.get("audience"),
        "model": idle_model,
        "prompt_version": appraisal.get("prompt_version"),
        "duration_ms": round(duration_ms, 3),
        "canonical_sha256_before": canonical_before,
        "canonical_sha256_after": _artifact_sha256(organ.store_path),
        "vectors_sha256_after": _artifact_sha256(
            getattr(organ.vectors, "vec_path", None)),
        "vector_ids_sha256_after": _artifact_sha256(
            getattr(organ.vectors, "ids_path", None)),
        "vector_error": admitted.get("vector_error"),
    }
    receipt("narrative_cluster", **common)
    if admitted.get("committed"):
        field.satiate(item, now=now)
    if getattr(engine, "salience_observer", None) is not None:
        engine.salience_observer.discharge(
            item, outcome, "", {
                key: common[key] for key in (
                    "candidate_key", "candidate_count", "selected_count",
                    "cluster_signature", "new_memory_digest", "model",
                    "prompt_version", "duration_ms")}, now)
    field.save(now=now)
    return {**admitted, **common}


def dmn_loop(engine, turn_lock, metabolism: dict, stop,
             agency_runtime=None, writing_desk_runtime=None,
             archive_reader_runtime=None, research_desk_runtime=None,
             atelier_runtime=None):
    """The idle circulation: substrate -> pressure -> candidates -> lived record.

    Sampling frequency is merely observation granularity. DriftPressure uses
    measured dt, candidates persist and compete, and discharge warms the seed
    that produced it. Every gate transition and effect leaves a receipt.
    """
    import json as _json
    import random
    import time as _time
    from core.dmn import drift_type, render_catch
    from shell.autonomy_circulation import circulate_experienced_event
    params = metabolism["params"]
    hist = os.path.join(REPO, "personas", engine.persona, "history")
    os.makedirs(hist, exist_ok=True)
    rpath = os.path.join(hist, "dmn.jsonl")
    field = attach_idle_metabolism(engine, metabolism)
    observer = engine.salience_observer

    def receipt(kind, **kw):
        rec = {"t": _time.strftime("%Y-%m-%d %H:%M:%S"),
               "kind": kind, **kw}
        with open(rpath, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + "\n")

    receipt("boot", level=metabolism["level"],
            enabled=metabolism["enabled"],
            idle_model=metabolism.get("idle_model"),
            restored_candidates=len(field.queue),
            restored_preoccupations=len(field.preoccupation.nodes))
    observer.field_snapshot(field, _time.time())
    boot_turn_ts = engine.last_turn_ts
    last_verdict = None
    last_pressure_band = int(field.pressure.pressure / 0.05)
    while not stop.wait(params["tick_s"]):
        now = None
        try:
            capability_field = any(
                runtime is not None and organ in engine.enabled
                for organ, runtime in (
                    ("writing_desk", writing_desk_runtime),
                    ("archive_reader", archive_reader_runtime),
                    ("research_desk", research_desk_runtime),
                    ("atelier", atelier_runtime)))
            generic_field = bool(metabolism["enabled"])
            if "dmn" not in engine.enabled or not (
                    generic_field or capability_field):
                continue
            with turn_lock:
                now = _time.time()
                if agency_runtime is not None:
                    returned = agency_runtime.drain_effects(field, now=now)
                    if returned:
                        receipt(
                            "agency_reentry",
                            candidate_count=len(returned),
                            candidate_keys=[item.get("key")
                                            for item in returned])
                if writing_desk_runtime is not None:
                    returned = writing_desk_runtime.drain_effects(
                        field, now=now)
                    if returned:
                        receipt(
                            "writing_desk_reentry",
                            candidate_count=len(returned),
                            candidate_keys=[item.get("key")
                                            for item in returned])
                if archive_reader_runtime is not None:
                    returned = archive_reader_runtime.drain_effects(
                        field, now=now)
                    if returned:
                        receipt(
                            "archive_reader_reentry",
                            candidate_count=len(returned),
                            candidate_keys=[item.get("key")
                                            for item in returned])
                if research_desk_runtime is not None:
                    returned = research_desk_runtime.drain_effects(
                        field, now=now)
                    if returned:
                        receipt(
                            "research_desk_reentry",
                            candidate_count=len(returned),
                            candidate_keys=[item.get("key")
                                            for item in returned])
                if atelier_runtime is not None:
                    returned = atelier_runtime.drain_effects(field, now=now)
                    if returned:
                        receipt(
                            "atelier_reentry",
                            candidate_count=len(returned),
                            candidate_keys=[item.get("key")
                                            for item in returned])
                bands = dict(engine.osc.bands) if engine.osc else {}
                coh = 0.5
                if engine.osc:
                    _c = getattr(engine.osc, "coherence", None)
                    # coherence is a METHOD on OscillatorOrgan (asked
                    # the bone 2026-07-12, after guessing cost a bounce)
                    coh = float(_c()) if callable(_c) else (
                        float(_c) if _c is not None else 0.5)
                idle_s = now - engine.last_turn_ts
                dp = field.pressure
                if (dp.active_node and dp.fired_at >= boot_turn_ts
                        and engine.last_turn_ts > dp.fired_at):
                    receipt("catch", node=dp.active_node[:80],
                            text=render_catch(dp.active_node))
                    dp.active_node = None
                    field.save(now=now)
                verdict, ev = dp.tick(bands, coh, idle_s, now=now)
                pressure_band = int(dp.pressure / 0.05)
                if verdict != last_verdict:
                    receipt("verdict", verdict=verdict,
                            pressure=round(dp.pressure, 3), **(ev or {}))
                    last_verdict = verdict
                    field.save(now=now)
                    last_pressure_band = pressure_band
                if verdict != "fired":
                    # Persist on field movement, not on an arbitrary timer.
                    # A crash can lose <0.05 pressure, never a whole state turn.
                    if pressure_band != last_pressure_band:
                        field.save(now=now)
                        last_pressure_band = pressure_band
                    continue
                # Explicitly admitted work stays an unresolved, relationship-
                # relevant pull until the persona addresses it.  It recurs
                # only at this genuine field boundary and still has to win.
                if agency_runtime is not None:
                    try:
                        agency_runtime.refresh_pending(field, now=now)
                    except Exception as agency_error:
                        receipt("agency_recurrence_error",
                                error=str(agency_error)[:200])
                if writing_desk_runtime is not None:
                    try:
                        writing_desk_runtime.refresh_pending(field, now=now)
                    except Exception as desk_error:
                        receipt("writing_desk_recurrence_error",
                                error=str(desk_error)[:200])
                if archive_reader_runtime is not None:
                    try:
                        archive_reader_runtime.refresh_pending(field, now=now)
                    except Exception as archive_error:
                        receipt("archive_reader_recurrence_error",
                                error=str(archive_error)[:200])
                if research_desk_runtime is not None:
                    try:
                        research_desk_runtime.refresh_pending(field, now=now)
                    except Exception as research_error:
                        receipt("research_desk_recurrence_error",
                                error=str(research_error)[:200])
                if atelier_runtime is not None:
                    try:
                        atelier_runtime.refresh_pending(field, now=now)
                    except Exception as atelier_error:
                        receipt("atelier_recurrence_error",
                                error=str(atelier_error)[:200])
                # Consolidation becomes available only through a real
                # substrate fire. It enters the same field and may lose to a
                # stronger sensory or memory pull; no schedule bypasses choice.
                if generic_field:
                    offer_gist_consolidation(engine, field, now=now)
                # wander AWAY, not at the just-now: exclude the
                # verbatim window (rumination is not wandering) and
                # avoid re-drifting to the previous seed when there's
                # anywhere else to go (recency-loop fix, 2026-07-12)
                hits = []
                if generic_field and engine.organ:
                    win_ids = {m["id"] for m in
                               engine.organ.working_window(12)}
                    hits = engine.organ.recall(
                        "", cocktail=engine.cocktail, n=3,
                        exclude=win_ids)
                if hits:
                    try:
                        offer_narrative_cluster(
                            engine, field, hits[0], now=now)
                    except Exception as cluster_error:
                        receipt("narrative_offer_error",
                                error=str(cluster_error)[:200])
                affect = max([float(v) for v in engine.cocktail.values()] or [0.0])
                for hit in hits:
                    field.offer_memory(hit["memory"], hit.get("score", 0.0),
                                       emotional_charge=affect, now=now)
                agency_state = (agency_runtime.readiness(field)
                                if agency_runtime is not None else None)
                desk_state = (writing_desk_runtime.readiness(field)
                              if writing_desk_runtime is not None else None)
                archive_state = (archive_reader_runtime.readiness(field)
                                 if archive_reader_runtime is not None else None)
                research_state = (research_desk_runtime.readiness(field)
                                  if research_desk_runtime is not None else None)
                atelier_state = (atelier_runtime.readiness(field)
                                 if atelier_runtime is not None else None)

                def capability_owned(candidate):
                    return bool(
                        (writing_desk_runtime is not None
                         and writing_desk_runtime.eligible(candidate))
                        or (archive_reader_runtime is not None
                            and archive_reader_runtime.eligible(candidate))
                        or (research_desk_runtime is not None
                            and research_desk_runtime.eligible(candidate))
                        or (atelier_runtime is not None
                            and atelier_runtime.eligible(candidate)))

                def scorer(candidate):
                    if writing_desk_runtime is not None \
                            and writing_desk_runtime.eligible(candidate):
                        return writing_desk_runtime.selection_score(
                            field, candidate, now=now,
                            readiness=desk_state)
                    if archive_reader_runtime is not None \
                            and archive_reader_runtime.eligible(candidate):
                        return archive_reader_runtime.selection_score(
                            field, candidate, now=now,
                            readiness=archive_state)
                    if research_desk_runtime is not None \
                            and research_desk_runtime.eligible(candidate):
                        return research_desk_runtime.selection_score(
                            field, candidate, now=now,
                            readiness=research_state)
                    if atelier_runtime is not None \
                            and atelier_runtime.eligible(candidate):
                        return atelier_runtime.selection_score(
                            field, candidate, now=now,
                            readiness=atelier_state)
                    if generic_field and agency_runtime is not None:
                        return agency_runtime.selection_score(
                            field, candidate, now=now,
                            readiness=agency_state)
                    if not generic_field:
                        return -1.0, {"capability_field_only": True,
                                      "action_eligible": False}
                    return field.attention_score(candidate, now=now)
                if not generic_field and not any(
                        capability_owned(value) for value in field.queue.items(now)):
                    dp.refund()
                    receipt("no_capability_candidate", **ev)
                    field.save(now=now)
                    continue
                item = field.discharge(now, scorer=scorer)
                if not item:
                    dp.refund()
                    receipt("no_candidate", **ev)
                    field.save(now=now)
                    continue
                sensory_origin = item.get("kind") == "sensory"
                event_origin = item.get("kind") in {"sensory", "cognitive"}
                receipt("candidate_selected", key=item.get("key"),
                        candidate_kind=item.get("kind"),
                        source=item.get("source"), recall_hits=len(hits),
                        agency_readiness=(agency_state or {}).get("readiness"),
                        agency_capacity=(agency_state or {}).get("capacity"),
                        agency_support=(agency_state or {}).get("support"),
                        agency_blocked=(agency_state or {}).get("hard_blocked"),
                        writing_desk_readiness=(desk_state or {}).get(
                            "readiness"),
                        writing_desk_blocked=(desk_state or {}).get(
                            "hard_blocked"),
                        archive_reader_readiness=(archive_state or {}).get(
                            "readiness"),
                        archive_reader_blocked=(archive_state or {}).get(
                            "hard_blocked"),
                        research_desk_readiness=(research_state or {}).get(
                            "readiness"),
                        research_desk_blocked=(research_state or {}).get(
                            "hard_blocked"),
                        atelier_readiness=(atelier_state or {}).get(
                            "readiness"),
                        atelier_blocked=(atelier_state or {}).get(
                            "hard_blocked"),
                        **ev)
                if item.get("kind") == "consolidation":
                    execute_gist_consolidation(
                        engine, field, item, receipt, now=now)
                    continue
                if item.get("kind") == "narrative_cluster":
                    execute_narrative_cluster(
                        engine, field, item, receipt,
                        metabolism.get("idle_model"), now=now)
                    continue
                if writing_desk_runtime is not None \
                        and writing_desk_runtime.eligible(item):
                    desk_run = writing_desk_runtime.start_candidate(item)
                    if desk_run.get("started"):
                        receipt(
                            "writing_desk_handoff", key=item.get("key"),
                            proposal_id=desk_run.get("proposal_id"),
                            run_id=desk_run.get("run_id"))
                        field.save(now=now)
                        continue
                    # A desk-owned source cannot silently fall through to an
                    # idle thought or general agency. Preserve it until its
                    # exact local capability is available again.
                    dp.refund()
                    field.queue.put(
                        item, item.get("salience", 0.05), now=now,
                        offer_meta={
                            "operation": "requeued",
                            "reason": desk_run.get("reason") or
                                      "writing_desk_unavailable"})
                    receipt(
                        "writing_desk_requeued", key=item.get("key"),
                        reason=str(desk_run.get("reason") or "unknown")[:200])
                    field.save(now=now)
                    continue
                if archive_reader_runtime is not None \
                        and archive_reader_runtime.eligible(item):
                    archive_run = archive_reader_runtime.start_candidate(item)
                    if archive_run.get("started"):
                        receipt(
                            "archive_reader_handoff", key=item.get("key"),
                            proposal_id=archive_run.get("proposal_id"),
                            run_id=archive_run.get("run_id"))
                        field.save(now=now)
                        continue
                    # Archive-owned history never falls through to ordinary
                    # agency or an idle-thought prompt. Keep the exact anchor
                    # pending until its local capability is available.
                    dp.refund()
                    field.queue.put(
                        item, item.get("salience", 0.05), now=now,
                        offer_meta={
                            "operation": "requeued",
                            "reason": archive_run.get("reason") or
                                      "archive_reader_unavailable"})
                    receipt(
                        "archive_reader_requeued", key=item.get("key"),
                        reason=str(archive_run.get("reason") or
                                   "unknown")[:200])
                    field.save(now=now)
                    continue
                if research_desk_runtime is not None \
                        and research_desk_runtime.eligible(item):
                    research_run = research_desk_runtime.start_candidate(item)
                    if research_run.get("started"):
                        receipt(
                            "research_desk_handoff", key=item.get("key"),
                            proposal_id=research_run.get("proposal_id"),
                            run_id=research_run.get("run_id"))
                        field.save(now=now)
                        continue
                    dp.refund()
                    field.queue.put(
                        item, item.get("salience", 0.05), now=now,
                        offer_meta={
                            "operation": "requeued",
                            "reason": research_run.get("reason") or
                                      "research_desk_unavailable"})
                    receipt(
                        "research_desk_requeued", key=item.get("key"),
                        reason=str(research_run.get("reason") or
                                   "unknown")[:200])
                    field.save(now=now)
                    continue
                if atelier_runtime is not None \
                        and atelier_runtime.eligible(item):
                    atelier_run = atelier_runtime.start_candidate(item)
                    if atelier_run.get("started"):
                        receipt(
                            "atelier_handoff", key=item.get("key"),
                            proposal_id=atelier_run.get("proposal_id"),
                            run_id=atelier_run.get("run_id"))
                        field.save(now=now)
                        continue
                    # Creative material belongs to the atelier boundary.  A
                    # missing renderer must not turn it into idle narration or
                    # a paid general-agency call.
                    dp.refund()
                    field.queue.put(
                        item, item.get("salience", 0.05), now=now,
                        offer_meta={
                            "operation": "requeued",
                            "reason": atelier_run.get("reason") or
                                      "atelier_unavailable"})
                    receipt(
                        "atelier_requeued", key=item.get("key"),
                        reason=str(atelier_run.get("reason") or
                                   "unknown")[:200])
                    field.save(now=now)
                    continue
                if not generic_field:
                    dp.refund()
                    field.queue.put(
                        item, item.get("salience", 0.05), now=now,
                        offer_meta={"operation": "requeued",
                                    "reason": "capability_field_only"})
                    receipt("capability_candidate_guard", key=item.get("key"))
                    field.save(now=now)
                    continue
                if agency_runtime is not None \
                        and agency_runtime.eligible(item):
                    agency = agency_runtime.start_candidate(item)
                    if agency.get("started"):
                        receipt(
                            "agency_handoff", key=item.get("key"),
                            proposal_id=agency.get("proposal_id"),
                            run_id=agency.get("run_id"))
                        field.save(now=now)
                        continue
                    # An agency-owned admission cannot silently degrade into
                    # paid wandering when its exact execution capability is
                    # unavailable. Preserve the unresolved pull at the same
                    # field boundary; a later real fire may try again.
                    dp.refund()
                    field.queue.put(
                        item, item.get("salience", 0.05), now=now,
                        offer_meta={
                            "operation": "requeued",
                            "reason": agency.get("reason") or
                                      "agency_unavailable"})
                    receipt(
                        "agency_requeued", key=item.get("key"),
                        reason=str(agency.get("reason") or "unknown")[:200])
                    field.save(now=now)
                    continue
                seed = None
                if not event_origin:
                    seed = next((h["memory"] for h in hits
                                 if h["memory"].get("id") == item.get("seed_id")),
                                None)
                    if item.get("seed_id") and seed is None:
                        seed = next((m for m in engine.organ.memories
                                     if m.get("id") == item.get("seed_id")), None)
                    if seed is None:
                        dp.refund()
                        receipt("stale_candidate", key=item.get("key"), **ev)
                        field.save(now=now)
                        continue
                node = item.get("node") or (seed.get("content") or "")[:240]
                dom = engine.osc.dominant() if engine.osc else "alpha"
                dt = drift_type(dom, bands.get("theta", 0.2))
                idle_model = metabolism.get("idle_model")
                if not idle_model:
                    dp.refund()
                    field.queue.put(
                        item, item.get("salience", 0.5), now=now,
                        offer_meta={"operation": "requeued",
                                    "reason": "no_idle_model"})
                    receipt("no_idle_model", key=item.get("key"), **ev)
                    field.save(now=now)
                    continue
                try:
                    receipt("consultation", key=item.get("key"),
                            candidate_kind=item.get("kind"),
                            source=item.get("source"), model=idle_model,
                            drift_type=dt, **ev)
                    cycle_id = new_cycle_id()
                    model_receipts = []
                    thought = generate_idle_thought(
                        engine, idle_model, item, dt,
                        sensory_source=(item.get("source")
                                        if event_origin else None),
                        cycle_id=cycle_id,
                        model_receipts=model_receipts)
                    generation = (model_receipts[-1]
                                  if model_receipts else {})
                    generation_meta = {
                        key: generation[key] for key in (
                            "call_id", "finish_reason", "output_tokens")
                        if generation.get(key) is not None}
                    receipt("consultation_result", model=idle_model,
                            **generation_meta)
                except Exception as gen_error:
                    dp.refund()
                    observer.discharge(
                        item, "error", str(gen_error),
                        {"candidate_key": item.get("key"), "model": idle_model,
                         "drift_type": dt}, now)
                    field.queue.put(
                        item, item.get("salience", 0.5), now=now,
                        offer_meta={"operation": "requeued",
                                    "reason": "generation_error"})
                    receipt("generation_error", model=idle_model,
                            error=str(gen_error)[:200], **ev)
                    field.save(now=now)
                    continue
                if not thought or thought.lower() == "[quiet]":
                    try:
                        felt = circulate_experienced_event(
                            engine,
                            "An unbidden private pull settled without "
                            "language; nothing was expressed or sent.",
                            cycle_id=cycle_id)
                        receipt(
                            "dmn_felt_consequence", outcome="quiet",
                            felt=sorted(felt.get("felt") or {}),
                            why=str(felt.get("why") or "")[:240],
                            affect_change=felt.get("affect_change", 0.0))
                    except Exception as consequence_error:
                        receipt(
                            "dmn_consequence_error", outcome="quiet",
                            error_type=type(consequence_error).__name__)
                    field.satiate(item, now=now)
                    observer.discharge(
                        item, "quiet", thought,
                        {"candidate_key": item.get("key"), "model": idle_model,
                         "drift_type": dt, **generation_meta}, now)
                    receipt("quiet", model=idle_model, node=node[:80],
                            **generation_meta, **ev)
                    field.save(now=now)
                    continue
                try:
                    felt = circulate_experienced_event(
                        engine,
                        "An unbidden private thought arose in the mind: "
                        + thought, cycle_id=cycle_id)
                    receipt(
                        "dmn_felt_consequence", outcome="private",
                        felt=sorted(felt.get("felt") or {}),
                        why=str(felt.get("why") or "")[:240],
                        affect_change=felt.get("affect_change", 0.0))
                except Exception as consequence_error:
                    receipt(
                        "dmn_consequence_error", outcome="private",
                        error_type=type(consequence_error).__name__)
                memory_fields = {
                    "channel": "dmn", "drift_type": dt,
                    "gist_eligible": True, "audience": "household"}
                if generation_meta:
                    memory_fields["generation"] = dict(generation_meta)
                if event_origin:
                    memory_fields.update({
                        "event_source": item.get("source"),
                        "candidate_key": item.get("key"),
                        "perception_event_ids": list(
                        item.get("perception_event_ids") or [])})
                    if sensory_origin:
                        memory_fields["sensory_source"] = item.get("source")
                else:
                    memory_fields["seed_id"] = seed.get("id")
                context_builder = getattr(
                    engine, "memory_context_snapshot", None)
                memory_context = (
                    context_builder(now=now)
                    if callable(context_builder) else None)
                mem = engine.organ.encode(
                    thought, cocktail=engine.cocktail,
                    entities=([] if event_origin else
                              list(seed.get("entities") or [])[:4]),
                    mem_type="wandering",
                    origin=("sensory" if sensory_origin else "lived"),
                    fields=memory_fields,
                    context_at_encoding=memory_context)
                engine.organ.save()
                field.satiate(item, now=now)
                gist_folded = bool(engine.gist and
                                   engine.gist.update_idle(engine.organ.memories))
                dp.active_node = node
                observer.discharge(
                    item, "private", thought,
                    {"candidate_key": item.get("key"), "model": idle_model,
                     "drift_type": dt, **generation_meta}, now)
                receipt("drift", drift_type=dt, node=node,
                        text=thought,
                        origin=("sensory" if sensory_origin else "lived"),
                        seed_id=(seed.get("id") if seed else None),
                        candidate_key=(item.get("key")
                                       if event_origin else None),
                        sensory_source=item.get("source"),
                        salience=round(item.get("salience", 0.0), 3),
                        queue_remaining=len(field.queue), model=idle_model,
                        gist_folded=gist_folded,
                        mem_id=(mem or {}).get("id"),
                        **generation_meta, **ev)
                field.save(now=now)
        except Exception as e:
            try:
                receipt("error", error=str(e)[:200])
            except Exception:
                pass      # the idle mind must never kill the body
        finally:
            if now is not None:
                observer.field_snapshot(field, now)


def turn_failure_message(engine, exc: Exception) -> str:
    """Give the cockpit an honest transport-specific failure message."""
    import re
    from harness.clients import model_auth_status
    ident = (getattr(engine, "spec", {}) or {}).get("identity") or {}
    raw = re.sub(r"\s+", " ", str(exc)).strip()[:500]
    provider = ident.get("provider")
    if provider == "openai_compat" or ident.get("family") == "openai_chat":
        auth = model_auth_status(engine.spec)
        if auth["required"] and not auth["set"]:
            return (f"turn failed: model '{engine.model}' needs "
                    f"{auth['env']}, but it is not set. Open the keys tab, "
                    f"paste it there, restart this persona, and try again.")
        if "API 401" in raw:
            return (f"turn failed: the API rejected {auth['env']} (401). "
                    f"Update it in the keys tab, restart this persona, "
                    f"and try again.")
        return f"turn failed on API model '{engine.model}': {raw}"
    if provider == "anthropic_api" or ident.get("family") == "anthropic":
        return f"turn failed on Anthropic model '{engine.model}': {raw}"
    return (f"turn failed: {exc.__class__.__name__} - {raw}. If this is "
            f"a local model, check VRAM contention with `ollama ps`. "
            f"The turn was lost; say it again.")


def build_app(engine: TurnEngine, max_tokens: int = 600,
              turn_lock=None, speaker: str = None,
              agency_controller=None, agency_runtime=None,
              writing_desk_runtime=None,
              archive_reader_runtime=None,
              research_desk_runtime=None,
              atelier_runtime=None) -> FastAPI:
    from shell.local_identity import load_local_identity
    app = FastAPI(title="JNSQ cockpit", version=CONTRACT_VERSION)
    if os.path.isdir(ASSET_DIR):
        app.mount("/assets", StaticFiles(directory=ASSET_DIR),
                  name="jnsq-assets")
    app.state.engine = engine
    app.state.turn_lock = turn_lock or threading.Lock()
    app.state.max_tokens = max_tokens
    app.state.speaker = speaker
    app.state.agency_controller = agency_controller
    app.state.agency_runtime = agency_runtime
    app.state.writing_desk_runtime = writing_desk_runtime
    app.state.archive_reader_runtime = archive_reader_runtime
    app.state.research_desk_runtime = research_desk_runtime
    app.state.atelier_runtime = atelier_runtime
    memory_views = {}

    def current_speaker():
        """Explicit test/bridge speakers stay pinned; local chat follows account display name."""
        return (app.state.speaker
                if app.state.speaker is not None
                else load_local_identity(REPO)["display_name"])

    def external_demand(reason: str, source: str):
        controller = app.state.agency_controller
        if controller is None:
            return None
        return controller.external_demand(reason, source=source)

    def decode_speech(req):
        prefix = f"data:{req.mime_type};base64,"
        if not req.data_url.startswith(prefix):
            raise ValueError("speech payload type does not match its data URL")
        encoded = req.data_url[len(prefix):]
        if len(encoded) > (MAX_AUDIO_BYTES * 4 // 3) + 8:
            raise ValueError("speech segment exceeds the 8 MB safety boundary")
        try:
            audio = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("speech segment is not valid base64")
        validate_audio(audio, req.mime_type)
        return audio

    @app.get("/", response_class=HTMLResponse)
    def page():
        import json
        with open(os.path.join(HERE, "cockpit.html"), encoding="utf-8") as f:
            return f.read().replace("/*CONFIG*/", json.dumps({
                "primary_user": current_speaker(),
                "persona_avatar": "/api/avatar"}))

    @app.get("/api/ui/conversation-background")
    def conversation_background():
        media = load_conversation_background(REPO)
        if not media:
            return JSONResponse(status_code=404,
                                content={"error": "no conversation background"})
        return FileResponse(media["path"], media_type=media["mime"],
                            headers={"X-Content-Type-Options": "nosniff",
                                     "Cache-Control": "no-cache"})

    @app.post("/api/ui/conversation-background")
    def save_cockpit_conversation_background(
            req: ConversationBackgroundRequest):
        try:
            media = save_conversation_background(REPO, req.data_url)
            return {"ok": True, "url": "/api/ui/conversation-background",
                    "revision": media["revision"]}
        except ValueError as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)})

    @app.delete("/api/ui/conversation-background")
    def delete_cockpit_conversation_background():
        return {"ok": True,
                "removed": delete_conversation_background(REPO)}

    @app.get("/api/avatar")
    def avatar():
        media = load_persona_avatar(app.state.engine.pdir)
        if not media:
            return JSONResponse(status_code=404,
                                content={"error": "persona has no avatar"})
        return FileResponse(
            media["path"], media_type=media["mime"],
            headers={"X-Content-Type-Options": "nosniff",
                     "Cache-Control": "no-cache"})

    @app.get("/api/images/{image_id}")
    def turn_image(image_id: str):
        found = stored_image_path(app.state.engine.pdir, image_id)
        if not found:
            return JSONResponse(status_code=404,
                                content={"error": "image not found"})
        path, mime = found
        return FileResponse(
            path, media_type=mime,
            headers={"X-Content-Type-Options": "nosniff",
                     "Cache-Control": "private, max-age=31536000, immutable"})

    @app.post("/api/perception/camera")
    def camera_percept(req: AmbientFrameRequest):
        """Admit one browser-selected change frame into perception + DMN.

        The browser owns continuous pixels. Only a threshold-crossing frame
        crosses the process boundary; model work is serialized with turns.
        """
        raw = (req.image.model_dump() if hasattr(req.image, "model_dump")
               else req.image.dict())
        try:
            images = store_images(app.state.engine.pdir, [raw])
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied — camera event remains local"})
        try:
            features = dict(req.features or {})
            features["novelty"] = req.novelty
            features["admission_pressure"] = req.pressure
            event = SensoryEvent("camera", features,
                                 subject="environment", ownership="ambient")
            sensory = app.state.engine.receive_sensory_event(event)
            if not sensory["admitted"]:
                return {"ok": True, "admitted": False,
                        "pressure": sensory["pressure"],
                        "policy": sensory["policy"], "queued": False}
            observation, route = app.state.engine.transduce_visual(images)
            app.state.engine.perception.annotate(event.event_id, observation)
            field = getattr(app.state.engine, "idle_metabolism", None)
            candidate = None
            if field is not None and "dmn" in app.state.engine.enabled:
                body_intensity = max(
                    [float(v) for v in app.state.engine.cocktail.values()] or [0.0])
                field_now = __import__("time").time()
                candidate = field.offer_event(
                    "camera", observation,
                    {"novelty": sensory["demand"],
                     "body_intensity": body_intensity,
                     "unresolved": min(1.0, sensory["pressure"])},
                    now=field_now, raw_ref=event.event_id,
                    ownership=event.ownership, receipts=[event.event_id])
                field.save(now=field_now)
                app.state.engine.salience_observer.field_snapshot(
                    field, field_now)
            rec = {"ts": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
                   "source": "camera", "novelty": round(req.novelty, 3),
                   "pressure": round(req.pressure, 3), "route": route,
                   "event_id": event.event_id, "admitted": True,
                   "policy": sensory["policy"],
                   "band_pressure": sensory["band_pressure"],
                   "observation": observation,
                   "candidate_salience": (round(candidate["salience"], 3)
                                          if candidate else None),
                   "image": public_image_record(images[0])}
            return {"ok": True, **rec, "queued": candidate is not None}
        except Exception as e:
            return JSONResponse(status_code=504,
                                content={"error": str(e)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/perception/audio")
    def audio_percept(req: AmbientAudioRequest):
        """Admit browser-computed acoustic features; raw audio stays local."""
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; acoustic event remains local"})
        try:
            features = dict(req.features or {})
            features["admission_pressure"] = req.pressure
            content = (
                "An acoustic change registered "
                f"(level {float(features.get('rms', 0)):.2f}, "
                f"onset {float(features.get('onset', 0)):.2f}, "
                f"spectral change {float(features.get('spectral_flux', 0)):.2f}, "
                f"speech-like structure "
                f"{float(features.get('speech_likelihood', 0)):.2f})."
            )
            event = SensoryEvent("audio", features, subject="environment",
                                 ownership="ambient",
                                 confidence=req.confidence, content=content)
            sensory = app.state.engine.receive_sensory_event(event)
            candidate = None
            field = getattr(app.state.engine, "idle_metabolism", None)
            if (sensory["admitted"] and field is not None
                    and "dmn" in app.state.engine.enabled):
                field_now = __import__("time").time()
                candidate = field.offer_event(
                    "microphone", content,
                    {"novelty": sensory["demand"],
                     "body_intensity": max(
                         sensory["features"].get("rms", 0),
                         sensory["features"].get("onset", 0)),
                     "unresolved": 1.0 - req.confidence},
                    now=field_now, raw_ref=event.event_id,
                    ownership=event.ownership, receipts=[event.event_id])
                field.save(now=field_now)
                app.state.engine.salience_observer.field_snapshot(
                    field, field_now)
            return {"ok": True, "event_id": event.event_id,
                    "admitted": sensory["admitted"],
                    "pressure": sensory["pressure"],
                    "policy": sensory["policy"],
                    "band_pressure": sensory["band_pressure"],
                    "description": content,
                    "candidate_salience": (round(candidate["salience"], 3)
                                             if candidate else None),
                    "queued": candidate is not None,
                    "state": app.state.engine.get_state()}
        except (TypeError, ValueError) as e:
            return JSONResponse(status_code=400,
                                content={"error": str(e)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/perception/substrate")
    def substrate_summary(req: SubstrateSummaryRequest):
        """Cheap room-to-body transport beside the attention channel.

        Deliberately no turn_lock: this route cannot delay or reject an
        expensive admission event. TurnEngine's small accumulator owns its
        own lock, and the existing body step remains the sole consumer.
        """
        try:
            payload = (req.model_dump() if hasattr(req, "model_dump")
                       else req.dict())
            return app.state.engine.offer_substrate_summary(payload)
        except (TypeError, ValueError) as e:
            return JSONResponse(status_code=400,
                                content={"error": str(e)[:500]})

    @app.post("/api/perception/speech")
    def speech_percept(req: SpeechRequest):
        """Transcribe one edge-segmented utterance, then decide its channel.

        Recognition establishes what was heard. Provenance remains ``other``;
        only an explicit voice-channel choice plus collective evidence may
        promote it into the ordinary one-body/one-mouth turn path.
        """
        transcriber = getattr(app.state.engine, "speech_transcriber", None)
        if transcriber is None:
            return JSONResponse(status_code=503, content={
                "error": "speech transcription is not configured or available"})
        try:
            audio = decode_speech(req)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; the speech segment stayed local"})
        try:
            transcript = transcriber.transcribe(audio, req.mime_type)
            subject = req.speaker or current_speaker()
            features = dict(req.features or {})
            features["admission_pressure"] = req.pressure
            event = SensoryEvent(
                "audio", features, subject=subject, ownership="other",
                confidence=transcript.confidence, content=transcript.text)
            sensory = app.state.engine.receive_sensory_event(event)
            admission = turn_admission(
                transcript.confidence, features, sensory, req.auto_turn)
            observer = app.state.engine.salience_observer
            if admission["admitted"]:
                admission_outcome = "conversation"
            elif sensory["admitted"] and transcript.text:
                admission_outcome = "ambient"
            else:
                admission_outcome = "discarded"
            osc = getattr(app.state.engine, "osc", None)
            osc_bands = getattr(osc, "bands", {}) if osc else {}
            if not isinstance(osc_bands, dict):
                osc_bands = {}
            osc_coherence = None
            coherence_fn = getattr(osc, "coherence", None) if osc else None
            if callable(coherence_fn):
                candidate_coherence = coherence_fn()
                if isinstance(candidate_coherence, (int, float)):
                    osc_coherence = float(candidate_coherence)
            observer.admission_boundary(
                admission.get("evidence"), admission.get("score", 0.0),
                admission.get("boundary", 0.0), sensory.get("policy"),
                {"bands": dict(osc_bands), "coherence": osc_coherence},
                admission_outcome, event.timestamp, event_id=event.event_id)
            turn_result = None
            candidate = None
            if admission["admitted"] and transcript.text:
                external_demand(
                    "admitted_speech_turn", "human_speech")
                turn_result = app.state.engine.take_turn(
                    transcript.text, max_tokens=app.state.max_tokens,
                    speaker=subject)
            elif transcript.text:
                field = getattr(app.state.engine, "idle_metabolism", None)
                if (sensory["admitted"] and field is not None
                        and "dmn" in app.state.engine.enabled):
                    field_now = __import__("time").time()
                    candidate = field.offer_event(
                        "overheard_speech", transcript.text,
                        {"novelty": sensory["demand"],
                         "body_intensity": max(
                             float(features.get("rms", 0.0)),
                             float(features.get("onset", 0.0))),
                         "unresolved": 1.0 - transcript.confidence},
                        now=field_now, raw_ref=event.event_id,
                        ownership=event.ownership, receipts=[event.event_id])
                    field.save(now=field_now)
                    observer.field_snapshot(field, field_now)
            return {
                "ok": True, "event_id": event.event_id,
                "subject": subject, "ownership": "other",
                "transcript": transcript.as_dict(),
                "sensory": {"admitted": sensory["admitted"],
                            "pressure": sensory["pressure"],
                            "policy": sensory["policy"],
                            "band_pressure": sensory["band_pressure"]},
                "admission": admission, "turn": turn_result,
                "queued": candidate is not None,
                "candidate_salience": (round(candidate["salience"], 3)
                                       if candidate else None),
                "state": (turn_result or {}).get("state")
                         or app.state.engine.get_state()}
        except (TypeError, ValueError) as e:
            return JSONResponse(status_code=400,
                                content={"error": str(e)[:500]})
        except Exception as e:
            return JSONResponse(status_code=504,
                                content={"error": str(e)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/perception/event")
    def sensory_event(req: SensoryEventRequest):
        """Shared door for hardware drivers and later STT/appraisal layers."""
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; sensory event remains pending"})
        try:
            event = SensoryEvent(
                req.modality, req.features, subject=req.subject,
                ownership=req.ownership, confidence=req.confidence,
                content=req.content)
            result = app.state.engine.receive_sensory_event(event)
            return {"ok": True, "event_id": event.event_id,
                    "admitted": result["admitted"],
                    "subject": event.subject, "ownership": event.ownership,
                    "pressure": result["pressure"],
                    "policy": result["policy"],
                    "band_pressure": result["band_pressure"],
                    "state": app.state.engine.get_state()}
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content={"error": str(e)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/state")
    def state():
        return app.state.engine.get_state()

    def document_library():
        library = getattr(app.state.engine, "documents", None)
        if library is None:
            return None
        return library

    def conversation_archive():
        return getattr(app.state.engine, "archive", None)

    @app.get("/api/documents")
    def documents_status():
        library = document_library()
        if library is None:
            return JSONResponse(status_code=503, content={
                "error": "document library is not attached"})
        return library.status()

    @app.get("/api/documents/search")
    def documents_search(q: str = "", n: int = Query(default=8, ge=1,
                                                       le=20)):
        library = document_library()
        if library is None:
            return JSONResponse(status_code=503, content={
                "error": "document library is not attached"})
        try:
            return library.search(q, n=n)
        except DocumentError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})

    @app.post("/api/documents/import")
    def document_import(req: DocumentImportRequest):
        library = document_library()
        if library is None:
            return JSONResponse(status_code=503, content={
                "error": "document library is not attached"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; the document was not imported"})
        try:
            external_demand("document_import", "human_document")
            record = library.import_data_url(
                req.name, req.data_url, req.content_type)
            reader = library.open(record["id"], 0)
            return {"ok": True, "document": record, "reader": reader,
                    "status": library.status()}
        except DocumentError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/documents/{doc_id}/open")
    def document_open(doc_id: str, req: DocumentOpenRequest):
        library = document_library()
        if library is None:
            return JSONResponse(status_code=503, content={
                "error": "document library is not attached"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; reader position did not move"})
        try:
            external_demand("document_open", "human_document")
            return {"ok": True, "reader": library.open(
                doc_id, req.position)}
        except DocumentError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/documents/reader")
    def document_reader_status():
        library = document_library()
        if library is None:
            return JSONResponse(status_code=503, content={
                "error": "document library is not attached"})
        return library.reader_status(include_text=True)

    @app.post("/api/documents/reader/navigate")
    def document_navigate(req: DocumentNavigateRequest):
        library = document_library()
        if library is None:
            return JSONResponse(status_code=503, content={
                "error": "document library is not attached"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; reader position did not move"})
        try:
            external_demand("document_navigation", "human_document")
            return {"ok": True, "reader": library.navigate(
                req.action, req.position)}
        except DocumentError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/archive")
    def archive_status():
        archive = conversation_archive()
        if archive is None:
            return JSONResponse(status_code=503, content={
                "error": "conversation archive is not attached"})
        status = archive.status()
        runtime = app.state.archive_reader_runtime
        if runtime is not None:
            status["autonomous_reader"] = runtime.status()
        return status

    @app.get("/api/archive/search")
    def archive_search(q: str = "", n: int = Query(default=8, ge=1,
                                                     le=20)):
        archive = conversation_archive()
        if archive is None:
            return JSONResponse(status_code=503, content={
                "error": "conversation archive is not attached"})
        try:
            return archive.search(q, limit=n)
        except ArchiveError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})

    @app.post("/api/archive/{archive_id}/open")
    def archive_open(archive_id: str, req: ArchiveOpenRequest):
        archive = conversation_archive()
        if archive is None:
            return JSONResponse(status_code=503, content={
                "error": "conversation archive is not attached"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; archive position did not move"})
        try:
            external_demand("archive_open", "human_archive")
            return {"ok": True, "reader": archive.open(
                archive_id, req.section)}
        except ArchiveError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/archive/reader")
    def archive_reader_status():
        archive = conversation_archive()
        if archive is None:
            return JSONResponse(status_code=503, content={
                "error": "conversation archive is not attached"})
        return archive.reader_status(include_text=True)

    @app.post("/api/archive/reader/navigate")
    def archive_navigate(req: ArchiveNavigateRequest):
        archive = conversation_archive()
        if archive is None:
            return JSONResponse(status_code=503, content={
                "error": "conversation archive is not attached"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; archive position did not move"})
        try:
            external_demand("archive_navigation", "human_archive")
            return {"ok": True, "reader": archive.navigate(
                req.action, req.section)}
        except ArchiveError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/archive/reader/bookmark")
    def archive_bookmark(req: ArchiveBookmarkRequest):
        archive = conversation_archive()
        if archive is None:
            return JSONResponse(status_code=503, content={
                "error": "conversation archive is not attached"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; bookmark was not changed"})
        try:
            external_demand("archive_bookmark", "human_archive")
            return {"ok": True, "reader": archive.bookmark(req.anchor)}
        except ArchiveError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/writing-desk")
    def writing_desk_status():
        runtime = app.state.writing_desk_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "writing desk is not attached"})
        return runtime.status()

    @app.post("/api/writing-desk/seeds")
    def writing_desk_seed(req: WritingDeskSeedRequest):
        runtime = app.state.writing_desk_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "writing desk is not attached"})
        field = getattr(app.state.engine, "idle_metabolism", None)
        if field is None:
            return JSONResponse(status_code=409, content={
                "error": "writing desk needs the shared DMN field"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; material was not admitted"})
        try:
            external_demand("writing_desk_seed", "human_writing_material")
            admitted = runtime.admit_seed(
                field, req.label, content=req.content,
                anchors=req.anchors)
            return {"ok": True, **admitted, "status": runtime.status()}
        except (ValueError, DocumentError) as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/writing-desk/projects/{project_id}")
    def writing_desk_project(project_id: str):
        runtime = app.state.writing_desk_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "writing desk is not attached"})
        try:
            return runtime.desk.project(project_id, include_content=True)
        except ValueError as exc:
            return JSONResponse(status_code=404,
                                content={"error": str(exc)[:500]})

    @app.post("/api/writing-desk/projects/{project_id}/resume")
    def writing_desk_resume(project_id: str):
        runtime = app.state.writing_desk_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "writing desk is not attached"})
        field = getattr(app.state.engine, "idle_metabolism", None)
        if field is None:
            return JSONResponse(status_code=409, content={
                "error": "writing desk needs the shared DMN field"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; project did not resume"})
        try:
            external_demand("writing_desk_resume", "human_writing_material")
            result = runtime.resume_project(field, project_id)
            return {"ok": True, **result, "status": runtime.status()}
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/atelier")
    def atelier_status():
        runtime = app.state.atelier_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "atelier is not attached"})
        return runtime.status()

    @app.post("/api/atelier/seeds")
    def atelier_seed(req: AtelierSeedRequest):
        runtime = app.state.atelier_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "atelier is not attached"})
        field = getattr(app.state.engine, "idle_metabolism", None)
        if field is None:
            return JSONResponse(status_code=409, content={
                "error": "atelier needs the shared DMN field"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; material was not admitted"})
        try:
            external_demand("atelier_seed", "human_creative_material")
            admitted = runtime.admit_seed(field, req.label, req.brief)
            return {"ok": True, **admitted, "status": runtime.status()}
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/atelier/artifacts/{artifact_id}")
    def atelier_artifact(artifact_id: str):
        runtime = app.state.atelier_runtime
        if runtime is None:
            return JSONResponse(status_code=404, content={
                "error": "atelier is not attached"})
        try:
            path = runtime.atelier.artifact_path(artifact_id)
        except ValueError as exc:
            return JSONResponse(status_code=404,
                                content={"error": str(exc)[:500]})
        return FileResponse(
            path, media_type="image/svg+xml",
            headers={
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, max-age=31536000, immutable",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'none'; style-src 'none'; "
                    "img-src 'none'; object-src 'none'; frame-ancestors 'none'; "
                    "sandbox"),
            })

    @app.post("/api/atelier/artifacts/{artifact_id}/perceive")
    def atelier_artifact_perceive(
            artifact_id: str, req: AtelierPerceptionRequest):
        """Explicitly return a browser-rasterized artifact through vision."""
        runtime = app.state.atelier_runtime
        if runtime is None:
            return JSONResponse(status_code=404, content={
                "error": "atelier is not attached"})
        try:
            artifact = runtime.atelier.artifact(artifact_id)
        except ValueError as exc:
            return JSONResponse(status_code=404,
                                content={"error": str(exc)[:500]})
        raw = (req.image.model_dump() if hasattr(req.image, "model_dump")
               else req.image.dict())
        raw["name"] = f"{artifact_id}.png"
        try:
            images = store_images(app.state.engine.pdir, [raw])
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; the artifact remains unseen"})
        try:
            external_demand("atelier_artifact_perception",
                            "human_creative_admission")
            event = SensoryEvent(
                "camera", {"novelty": 1.0, "admission_pressure": 1.0},
                subject=f"self-created artifact {artifact.get('title')}",
                ownership="self", confidence=1.0)
            sensory = app.state.engine.receive_sensory_event(event)
            if not sensory["admitted"]:
                return {"ok": True, "admitted": False,
                        "event_id": event.event_id,
                        "pressure": sensory["pressure"],
                        "policy": sensory["policy"], "queued": False}
            observation, route = app.state.engine.transduce_visual(images)
            app.state.engine.perception.annotate(event.event_id, observation)
            field = getattr(app.state.engine, "idle_metabolism", None)
            candidate = None
            if field is not None and "dmn" in app.state.engine.enabled:
                field_now = __import__("time").time()
                candidate = field.offer_event(
                    "atelier_artifact", observation,
                    {"novelty": sensory["demand"],
                     "body_intensity": max(
                         [float(value) for value in
                          app.state.engine.cocktail.values()] or [0.0]),
                     "unresolved": 0.0},
                    now=field_now, raw_ref=artifact_id,
                    ownership="self",
                    receipts=[event.event_id, artifact_id])
                field.save(now=field_now)
                app.state.engine.salience_observer.field_snapshot(
                    field, field_now)
            runtime.atelier.record_receipt({
                "kind": "atelier_perception", "outcome": "admitted",
                "artifact_id": artifact_id, "medium": "svg",
                "locality": "local", "model_requests": 0,
                "provider_http_attempts": 0, "estimated_cost_usd": 0.0,
            })
            return {
                "ok": True, "admitted": True,
                "artifact_id": artifact_id, "event_id": event.event_id,
                "route": route, "observation": observation,
                "image": public_image_record(images[0]),
                "queued": candidate is not None,
                "candidate_salience": (round(candidate["salience"], 3)
                                       if candidate else None),
            }
        except Exception as exc:
            return JSONResponse(status_code=504,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/research-desk")
    def research_desk_status():
        runtime = app.state.research_desk_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "research desk is not attached"})
        return runtime.status()

    @app.post("/api/research-desk/interests")
    def research_desk_interest(req: ResearchInterestRequest):
        runtime = app.state.research_desk_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "research desk is not attached"})
        field = getattr(app.state.engine, "idle_metabolism", None)
        if field is None:
            return JSONResponse(status_code=409, content={
                "error": "research desk needs the shared DMN field"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; interest was not offered"})
        try:
            external_demand("research_interest_offer", "human_research_offer")
            result = runtime.admit_interest(field, req.topic)
            return {"ok": True, **result, "status": runtime.status()}
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/research-desk/text/{kind}/{name}")
    def research_desk_text(kind: str, name: str):
        runtime = app.state.research_desk_runtime
        if runtime is None:
            return JSONResponse(status_code=404, content={
                "error": "research desk is not attached"})
        try:
            return runtime.desk.read_text(f"{kind}/{name}")
        except ValueError as exc:
            return JSONResponse(status_code=404,
                                content={"error": str(exc)[:500]})

    @app.get("/api/agency/status")
    def agency_status():
        controller = app.state.agency_controller
        if controller is None:
            return {
                "persona": app.state.engine.persona,
                "external_demand_epoch": 0,
                "active": None,
                "replacement_pending": None,
                "latest_terminal": None,
                "controller_open": False,
            }
        status = controller.status()
        runtime = app.state.agency_runtime
        if runtime is not None:
            status["runtime"] = runtime.status()
        return status

    @app.post("/api/agency/inbox")
    def agency_inbox(req: AgencyInboxRequest):
        """Explicitly admit text to one persona's private workbench field."""
        runtime = app.state.agency_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "agency workbench is not attached"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; the work item was not saved"})
        try:
            field = getattr(app.state.engine, "idle_metabolism", None)
            if field is None:
                return JSONResponse(status_code=409, content={
                    "error": "no salience field is attached"})
            return {"ok": True, **runtime.admit_text(
                field, req.label, req.content)}
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/agency/artifacts")
    def agency_artifacts():
        runtime = app.state.agency_runtime
        if runtime is None:
            return {"artifacts": []}
        return {"artifacts": runtime.workbench.records(
            kind="private_draft", limit=100)}

    @app.get("/api/agency/artifacts/{name}")
    def agency_artifact(name: str):
        runtime = app.state.agency_runtime
        if runtime is None:
            return JSONResponse(status_code=404, content={
                "error": "agency workbench is not attached"})
        try:
            return runtime.workbench.read_artifact(f"artifacts/{name}")
        except ValueError as exc:
            return JSONResponse(status_code=404,
                                content={"error": str(exc)[:500]})

    @app.post("/api/voice/output")
    def voice_output(req: VoiceOutputRequest):
        """Record vessel behavior without storing the words it spoke."""
        try:
            return {"ok": True, "receipt": append_output_receipt(
                app.state.engine.pdir, req.model_dump())}
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content={"error": str(e)[:500]})

    def salience_for(persona):
        if str(persona).lower() != app.state.engine.persona.lower():
            return None
        field = getattr(app.state.engine, "idle_metabolism", None)
        observer = getattr(app.state.engine, "salience_observer", None)
        return (field, observer) if field is not None and observer is not None else None

    def memory_for(persona):
        if str(persona).lower() != app.state.engine.persona.lower():
            return None
        pdir = app.state.engine.pdir
        key = os.path.abspath(pdir)
        if key not in memory_views:
            memory_views[key] = MemoryObservatory(
                os.path.join(pdir, "body", "memory_emotion", "memories.json"),
                os.path.join(pdir, "history", "salience.jsonl"),
                os.path.join(pdir, "history", "perception.jsonl"))
        return memory_views[key]

    @app.get("/api/memory/{persona}/status")
    def memory_status(persona: str):
        if str(persona).lower() != app.state.engine.persona.lower():
            return JSONResponse(status_code=404, content={
                "error": "no memory organ for that persona"})
        organ = getattr(app.state.engine, "organ", None)
        if organ is None or not hasattr(organ, "vector_status"):
            return JSONResponse(status_code=503, content={
                "error": "memory vector status unavailable"})
        return organ.vector_status()

    @app.get("/api/memory/{persona}/records")
    def memory_records(persona: str, q: str = "", layer: str = "",
                       origin: str = "", memory_type: str = "",
                       source: str = "", entity: str = "",
                       entities_state: str = "all",
                       min_age_days: float = Query(default=None, ge=0),
                       max_age_days: float = Query(default=None, ge=0),
                       min_importance: float = Query(default=None),
                       max_importance: float = Query(default=None),
                       access_state: str = "all",
                       min_access: int = Query(default=None, ge=0),
                       max_access: int = Query(default=None, ge=0),
                       page: int = Query(default=1, ge=1),
                       per_page: int = Query(default=50, ge=1, le=200)):
        view = memory_for(persona)
        if view is None:
            return JSONResponse(status_code=404, content={
                "error": "no memory store for that persona"})
        if entities_state not in {"all", "empty", "present"}:
            return JSONResponse(status_code=400, content={
                "error": "entities_state must be all, empty, or present"})
        if access_state not in {"all", "never", "selected"}:
            return JSONResponse(status_code=400, content={
                "error": "access_state must be all, never, or selected"})
        return view.search(
            query=q, layer=layer, origin=origin, memory_type=memory_type,
            source=source, entity=entity, entities_state=entities_state,
            min_age_days=min_age_days, max_age_days=max_age_days,
            min_importance=min_importance, max_importance=max_importance,
            access_state=access_state, min_access=min_access,
            max_access=max_access, page=page, per_page=per_page)

    @app.get("/api/memory/{persona}/record/{memory_id}")
    def memory_record(persona: str, memory_id: str):
        view = memory_for(persona)
        if view is None:
            return JSONResponse(status_code=404, content={
                "error": "no memory store for that persona"})
        result = view.drilldown(memory_id)
        if result is None:
            return JSONResponse(status_code=404, content={
                "error": "memory record not found"})
        return result

    @app.get("/api/salience/{persona}/field")
    def salience_field(persona: str):
        found = salience_for(persona)
        if found is None:
            return JSONResponse(status_code=404, content={
                "error": "no live salience field for that persona"})
        field, observer = found
        return observer.project_field(field)

    @app.get("/api/salience/{persona}/history")
    def salience_history(persona: str, n: int = Query(default=200, ge=1,
                                                       le=2000),
                             types: str = ""):
        found = salience_for(persona)
        if found is None:
            return JSONResponse(status_code=404, content={
                "error": "no live salience field for that persona"})
        _field, observer = found
        wanted = [value.strip() for value in types.split(",") if value.strip()]
        return {"persona": persona,
                "records": observer.read_history(n=n, types=wanted)}

    @app.get("/api/salience/{persona}/candidate/{candidate_id}")
    def salience_candidate(persona: str, candidate_id: str):
        found = salience_for(persona)
        if found is None:
            return JSONResponse(status_code=404, content={
                "error": "no live salience field for that persona"})
        _field, observer = found
        records = observer.candidate_history(candidate_id)
        if not records:
            return JSONResponse(status_code=404, content={
                "error": "candidate has no observatory lifecycle"})
        return {"persona": persona, "candidate_key": candidate_id,
                "records": records}

    @app.get("/api/salience/{persona}/events")
    def salience_events(persona: str):
        found = salience_for(persona)
        if found is None:
            return JSONResponse(status_code=404, content={
                "error": "no live salience field for that persona"})
        _field, observer = found

        def stream():
            subscriber = observer.subscribe()
            try:
                yield "data: " + str(observer.revision) + "\n\n"
                while True:
                    yield "data: " + str(subscriber.get()) + "\n\n"
            finally:
                observer.unsubscribe(subscriber)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.get("/api/theme")
    def theme():
        result = resolve_theme(REPO, app.state.engine.persona,
                               app.state.engine.model)
        result["display_name"] = (
            app.state.engine.personas.get(app.state.engine.persona.lower())
            or {}).get("display_name", app.state.engine.persona)
        media = load_conversation_background(REPO)
        result["conversation_background"] = ({
            "url": "/api/ui/conversation-background",
            "revision": media["revision"]} if media else None)
        return result

    @app.post("/api/theme")
    def set_theme(req: ThemeRequest):
        try:
            return save_theme(
                REPO, req.scope, req.patch,
                persona=app.state.engine.persona,
                model=app.state.engine.model,
                reset=req.reset, replace=req.replace)
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content={"error": str(e)})

    @app.post("/api/mood")
    def mood(req: MoodRequest):
        return app.state.engine.set_mood(req.cocktail)

    @app.get("/api/organs")
    def organs():
        capability = (app.state.engine.spec.get("module_capability") or {})
        validated = set(capability.get("validated") or [])
        walls = set(capability.get("saturates_on") or [])
        entry, roster = load_roster_entry(app.state.engine.persona,
                                          app.state.engine.model)
        model_enabled = (list(entry["enabled_organs"])
                         if entry is not None
                         and entry.get("enabled_organs") is not None
                         else None)
        persona_enabled = (list(roster["enabled_organs"])
                           if roster is not None
                           and roster.get("enabled_organs") is not None
                           else None)
        _declared, scope = roster_organ_preference(entry, roster)
        return {"registry": [{"id": o.organ_id, "deps": list(o.deps),
                              "desc": o.desc, "cost": o.cost,
                              "loop": o.loop,
                              "validated": o.organ_id in validated,
                              "blocked": o.organ_id in walls}
                             for o in REGISTRY.values()],
                "enabled": sorted(app.state.engine.enabled),
                "persona": app.state.engine.persona,
                "model": app.state.engine.model,
                "scope": scope,
                "persona_enabled": persona_enabled,
                "model_enabled": model_enabled,
                "persisted": scope != "runtime",
                "can_persist": entry is not None}

    @app.post("/api/organs")
    def set_organs(req: OrganRequest):
        if req.scope not in {"persona", "model"}:
            return JSONResponse(status_code=400, content={
                "error": "organ scope must be 'persona' or 'model'"})
        # organs must never swap while a turn is mid-flight
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "a turn is in flight — try again in a moment"})
        try:
            before = sorted(app.state.engine.enabled)
            result = app.state.engine.set_organs(req.enabled)
            if "agency" in before \
                    and "agency" not in result["enabled_organs"]:
                external_demand(
                    "agency_organ_disabled", "organ_configuration")
            try:
                saver = (save_persona_organs if req.scope == "persona"
                         else save_model_organs)
                persisted = saver(app.state.engine.persona,
                                  app.state.engine.model,
                                  result["enabled_organs"])
            except Exception as e:
                # Roster truth and the running body must never diverge.
                app.state.engine.set_organs(before)
                return JSONResponse(status_code=500, content={
                    "error": f"organ preference was not saved ({e}); "
                             "live selection restored"})
            result.update({"persisted": persisted,
                           "scope": req.scope if persisted else "runtime",
                           "persona": app.state.engine.persona,
                           "model": app.state.engine.model})
            return result
        except OrganConfigError as e:
            return JSONResponse(status_code=400,
                                content={"error": str(e)})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/turn")
    def turn(req: TurnRequest):
        try:
            images = store_images(
                app.state.engine.pdir,
                [(item.model_dump() if hasattr(item, "model_dump")
                  else item.dict()) for item in req.images])
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        external_demand("human_turn_arrived", "human_turn")
        # A human turn is durable demand, not a best-effort sensory event.
        # If Nexus speech currently owns the one-mouth lock, wait for that
        # utterance to finish and take the next turn instead of dropping the
        # solo message with a 409. Lock release is the event; no polling clock.
        app.state.turn_lock.acquire()
        try:
            return app.state.engine.take_turn(req.message,
                                              max_tokens=app.state.max_tokens,
                                              speaker=req.speaker or
                                                      current_speaker(),
                                              images=images)
        except Exception as e:
            # a lost turn should fail as WORDS, never a plain-text 500
            # the UI can't parse. Traceback still lands in the tenant log.
            import traceback
            traceback.print_exc()
            return JSONResponse(status_code=504, content={
                "error": turn_failure_message(app.state.engine, e)})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/turn/stream")
    def turn_stream(req: TurnRequest):
        """Stream visible model text, then the fully-circulated turn result."""
        try:
            images = store_images(
                app.state.engine.pdir,
                [(item.model_dump() if hasattr(item, "model_dump")
                  else item.dict()) for item in req.images])
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        external_demand("human_turn_arrived", "human_turn_stream")
        # Streaming solo turns obey the same event-driven queue as JSON turns.
        app.state.turn_lock.acquire()

        events = queue.Queue()

        def run_turn():
            try:
                result = app.state.engine.take_turn(
                    req.message, max_tokens=app.state.max_tokens,
                    speaker=req.speaker or current_speaker(), images=images,
                    on_text=lambda text: events.put({"type": "delta",
                                                     "text": text}))
                events.put({"type": "final", "result": result})
            except Exception as e:
                import traceback
                traceback.print_exc()
                events.put({"type": "error", "error":
                            turn_failure_message(app.state.engine, e)})
            finally:
                app.state.turn_lock.release()

        threading.Thread(target=run_turn, daemon=True).start()

        def stream_events():
            while True:
                event = events.get()
                yield json.dumps(event, ensure_ascii=False) + "\n"
                if event["type"] in {"final", "error"}:
                    return

        return StreamingResponse(stream_events(),
                                 media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="vex")
    ap.add_argument("--model", default="llama3-1-8b")
    ap.add_argument("--port", type=int, default=8642)
    ap.add_argument("--speaker", default=None,
                    help="local human speaking through this cockpit")
    ap.add_argument("--no-osc", action="store_true")
    ap.add_argument("--no-soma", action="store_true")
    ap.add_argument("--identity-file", default=None,
                    help="path to a plain-text identity block; overrides "
                         "the IDENTITIES fallback/placeholder in contract.py")
    ap.add_argument("--max-tokens", type=int, default=600,
                    help="reply ceiling per turn (not a floor — the model "
                         "still chooses how much of it to use)")
    ap.add_argument("--room-url", default=None,
                    help="room host base url, e.g. http://127.0.0.1:8721 — "
                         "gives this persona a body in a place")
    ap.add_argument("--room", default=None,
                    help="room id to join (default: <persona>_den)")
    ap.add_argument("--tropism", action="store_true",
                    help="legacy alias for --enable tropism")
    ap.add_argument("--tropism-interval", type=float, default=None,
                    help="seconds between worm ticks (default: roster "
                         "room.tropism_interval, else 60)")
    ap.add_argument("--social", action="store_true",
                    help="legacy alias for --enable social")
    ap.add_argument("--social-interval", type=float, default=None,
                    help="seconds between social ticks (default: roster "
                         "room.social_interval, else 20)")
    ap.add_argument("--heartbeat-interval", type=float, default=10.0,
                    help="seconds between heartbeat checks (settle "
                         "steps remain 30s; this is just the pulse "
                         "check cadence)")
    ap.add_argument("--enable", default="",
                    help="comma list of organ ids to force-enable on top "
                         "of the roster (dev override)")
    ap.add_argument("--disable", default="",
                    help="comma list of organ ids to force-disable "
                         "(dev override; wins over --enable)")
    args = ap.parse_args()

    identity = None
    if args.identity_file:
        with open(args.identity_file, encoding="utf-8") as f:
            identity = f.read().strip()

    # ── par 2.6 resolution: roster is the source of truth; CLI is a
    # dev override; no roster (fixtures like vex) = the legacy set ──
    entry, roster = load_roster_entry(args.persona, args.model)
    room_cfg = (roster or {}).get("room") or {}
    declared_organs, _organ_scope = roster_organ_preference(entry, roster)
    if declared_organs is not None:
        enabled = set(declared_organs)
    else:
        enabled = legacy_set(use_osc=not args.no_osc,
                             use_soma=not args.no_soma,
                             room=bool(args.room_url))
    on = {s.strip() for s in args.enable.split(",") if s.strip()}
    off = {s.strip() for s in args.disable.split(",") if s.strip()}
    if args.tropism:
        on.add("tropism")
    if args.social:
        on.add("social")
    if args.no_osc:
        off |= {"oscillator", "rhythm_affect", "recall_bias"}
    if args.no_soma:
        off |= {"soma", "afferents"}
    enabled = (enabled | on) - off

    import uvicorn
    engine = TurnEngine(args.persona, args.model, enabled=enabled,
                        identity=identity,
                        room_url=args.room_url,
                        room_id=args.room or room_cfg.get("id"),
                        vision_model=((roster or {}).get("perception") or {})
                                     .get("vision_model"),
                        affect_model=((roster or {}).get("interoception") or {})
                                     .get("affect_model", args.model),
                        gist_model=((roster or {}).get("consolidation") or {})
                                   .get("gist_model"),
                        prompt_version=(entry or {}).get("prompt_version"))
    speech_cfg = (((roster or {}).get("perception") or {}).get("speech")
                  or {})
    try:
        engine.speech_transcriber = build_transcriber(speech_cfg)
    except ValueError as e:
        print(f"[cockpit] WARN speech transcription disabled: {e}")
        engine.speech_transcriber = None
    from core.dmn import resolve_metabolism
    metabolism = resolve_metabolism((roster or {}).get("metabolism"))
    attach_idle_metabolism(engine, metabolism)
    shared_lock = threading.Lock()
    observer = engine.salience_observer
    agency_controller = AgencyRunController(
        engine.persona,
        receipt_sink=lambda kind, now, payload:
        observer.agency_transition(kind, now, **payload))
    from shell.agency_runtime import AgencyRuntime
    agency_runtime = AgencyRuntime(
        engine, agency_controller, (roster or {}).get("agency"))
    from shell.writing_desk_runtime import WritingDeskRuntime
    writing_desk_runtime = WritingDeskRuntime(
        engine, agency_controller, (roster or {}).get("writing_desk"))
    from shell.archive_reader_runtime import ArchiveReaderRuntime
    archive_reader_runtime = ArchiveReaderRuntime(
        engine, agency_controller, (roster or {}).get("archive_reader"))
    from shell.research_desk_runtime import ResearchDeskRuntime
    research_desk_runtime = ResearchDeskRuntime(
        engine, agency_controller, (roster or {}).get("research_desk"))
    from shell.atelier_runtime import AtelierRuntime
    atelier_runtime = AtelierRuntime(
        engine, agency_controller, (roster or {}).get("atelier"))
    app = build_app(engine, max_tokens=args.max_tokens,
                    turn_lock=shared_lock, speaker=args.speaker,
                    agency_controller=agency_controller,
                    agency_runtime=agency_runtime,
                    writing_desk_runtime=writing_desk_runtime,
                    archive_reader_runtime=archive_reader_runtime,
                    research_desk_runtime=research_desk_runtime,
                    atelier_runtime=atelier_runtime)
    stop = threading.Event()
    # threads spawn unconditionally where their preconditions allow
    # and SELF-GATE per tick on the live enabled set — so runtime
    # toggles from the UI work without spawn/kill machinery (an idle
    # tick costs nothing). The heartbeat needs no room at all.
    threading.Thread(target=heartbeat_loop,
                     args=(engine, shared_lock,
                           args.heartbeat_interval, stop),
                     daemon=True, name="heart").start()
    # the idle metabolism: per-roster `metabolism:` block (top-level,
    # like pronouns/current_model) — {enabled, level, idle_model}.
    # Thread spawns unconditionally and self-gates per tick, so the
    # fangwall "dmn" organ toggle works at runtime like every organ.
    if metabolism.get("idle_model"):
        _sp = os.path.join(REPO, "specs", "models",
                           f"{metabolism['idle_model']}.yaml")
        if not os.path.exists(_sp):
            print(f"[cockpit] WARN metabolism.idle_model "
                  f"'{metabolism['idle_model']}' has no spec — "
                  f"discharge tiers that spend it will refuse")
    threading.Thread(target=dmn_loop,
                      args=(engine, shared_lock, metabolism, stop,
                            agency_runtime, writing_desk_runtime,
                            archive_reader_runtime, research_desk_runtime,
                            atelier_runtime),
                     daemon=True, name="dmn").start()
    if args.room_url:
        threading.Thread(target=tropism_loop,
                         args=(engine, shared_lock,
                               args.tropism_interval
                               or room_cfg.get("tropism_interval") or 60.0,
                               stop),
                         daemon=True, name="worm").start()
    if args.room_url:
        threading.Thread(target=social_loop,
                         args=(engine, shared_lock,
                               args.social_interval
                               or room_cfg.get("social_interval") or 20.0,
                               args.max_tokens, stop),
                         daemon=True, name="social").start()
    st = engine.get_state()
    print(f"[cockpit] {args.persona} on {args.model} | contract v"
          f"{CONTRACT_VERSION} | identity={'file' if identity else 'DEFAULT/PLACEHOLDER'} | "
          f"max_tokens={args.max_tokens} | {st['memory_count']} memories | "
          f"organs=[{','.join(sorted(engine.enabled))}] | "
          f"http://127.0.0.1:{args.port}")
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        stop.set()
        agency_controller.close()
        engine.close()


if __name__ == "__main__":
    main()
