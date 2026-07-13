"""shell/cockpit.py — CLIENT #2 of the turn-loop contract: the web cockpit.
One page, three endpoints, zero opinions. The server is deliberately a
pass-through: every route body is a single TurnEngine call. If the cockpit
ever needs to know something the contract doesn't expose, the CONTRACT
grows (versioned), never a side door.

Run:  python shell/cockpit.py [--persona vex] [--model llama3-1-8b] [--port 8642]
Then open http://127.0.0.1:8642 — chat left, instruments right,
receipts drawer below. One turn at a time (one body, one mouth)."""
import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shell import env_store  # loads .env into os.environ (idempotent; no-op
env_store.load_env()         # when router-launched, since inherited vars win)
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shell.contract import TurnEngine, CONTRACT_VERSION
from shell.ui_themes import resolve_theme, save_theme
from shell.persona_media import load_persona_avatar
from core.organs import (legacy_set, validate as validate_organs,
                         OrganConfigError, REGISTRY)

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
            delivery = sp.tick(now, dt)
            entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     **sp.state()}
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
            moved_to = worm.tick(objs, at, now, dt, at_objects=within,
                                 volitional_hold_until=hold)
            if moved_to:
                r = engine.room.move(moved_to)
                moved_to = {"to": moved_to, "result": r}
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "at": at, "discharged": moved_to,
                    "pressure": worm.state()["pressure"]},
                    ensure_ascii=False) + "\n")
        except Exception:
            pass                          # the worm must never kill the body
        finally:
            turn_lock.release()


class TurnRequest(BaseModel):
    message: str
    speaker: str = None      # omitted means this installation's local human
                            # anonymous crosses (v1 nexus law, kept)


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


def generate_idle_thought(engine, idle_model: str, item: dict,
                          drift_kind: str) -> str:
    """Ask the configured idle vessel what arises; do not prescribe feeling.

    Kept separate from dmn_loop so transport failure and prompt law are
    mechanically testable without starting a thread.
    """
    from adapters.assembly import PromptAssembly
    from adapters.family_adapters import adapter_for
    from harness.spec_loader import load_spec
    spec = load_spec(idle_model)
    adapter = adapter_for(spec)
    asm = PromptAssembly()
    asm.add("identity", engine.identity, priority=10, stable=True)
    asm.add("current interior", f"Mood: {engine.cocktail}", priority=8)
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
            "voice, with no labels or preamble.")})
    return (adapter.call(asm, max_tokens=220, temperature=0.8) or "").strip()


def dmn_loop(engine, turn_lock, metabolism: dict, stop):
    """The idle circulation: substrate -> pressure -> candidates -> lived record.

    Sampling frequency is merely observation granularity. DriftPressure uses
    measured dt, candidates persist and compete, and discharge warms the seed
    that produced it. Every gate transition and effect leaves a receipt.
    """
    import json as _json
    import random
    import time as _time
    from core.dmn import IdleMetabolism, drift_type, render_catch
    params = metabolism["params"]
    hist = os.path.join(REPO, "personas", engine.persona, "history")
    os.makedirs(hist, exist_ok=True)
    rpath = os.path.join(hist, "dmn.jsonl")
    state_path = os.path.join(engine.pdir, "body", "dmn_state.json")
    field = IdleMetabolism.load(params, state_path)
    engine.idle_metabolism = field

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
    boot_turn_ts = engine.last_turn_ts
    last_verdict = None
    last_pressure_band = int(field.pressure.pressure / 0.05)
    while not stop.wait(params["tick_s"]):
        try:
            if "dmn" not in engine.enabled or not metabolism["enabled"]:
                continue
            with turn_lock:
                bands = dict(engine.osc.bands) if engine.osc else {}
                coh = 0.5
                if engine.osc:
                    _c = getattr(engine.osc, "coherence", None)
                    # coherence is a METHOD on OscillatorOrgan (asked
                    # the bone 2026-07-12, after guessing cost a bounce)
                    coh = float(_c()) if callable(_c) else (
                        float(_c) if _c is not None else 0.5)
                idle_s = _time.time() - engine.last_turn_ts
                dp = field.pressure
                if (dp.active_node and dp.fired_at >= boot_turn_ts
                        and engine.last_turn_ts > dp.fired_at):
                    receipt("catch", node=dp.active_node[:80],
                            text=render_catch(dp.active_node))
                    dp.active_node = None
                    field.save()
                now = _time.time()
                verdict, ev = dp.tick(bands, coh, idle_s, now=now)
                pressure_band = int(dp.pressure / 0.05)
                if verdict != last_verdict:
                    receipt("verdict", verdict=verdict,
                            pressure=round(dp.pressure, 3), **(ev or {}))
                    last_verdict = verdict
                    field.save()
                    last_pressure_band = pressure_band
                if verdict != "fired":
                    # Persist on field movement, not on an arbitrary timer.
                    # A crash can lose <0.05 pressure, never a whole state turn.
                    if pressure_band != last_pressure_band:
                        field.save()
                        last_pressure_band = pressure_band
                    continue
                # wander AWAY, not at the just-now: exclude the
                # verbatim window (rumination is not wandering) and
                # avoid re-drifting to the previous seed when there's
                # anywhere else to go (recency-loop fix, 2026-07-12)
                hits = []
                if engine.organ:
                    win_ids = {m["id"] for m in
                               engine.organ.working_window(12)}
                    hits = engine.organ.recall(
                        "", cocktail=engine.cocktail, n=3,
                        exclude=win_ids)
                if not hits:
                    dp.refund()
                    receipt("no_seed", **ev)
                    field.save()
                    continue

                affect = max([float(v) for v in engine.cocktail.values()] or [0.0])
                for hit in hits:
                    field.offer_memory(hit["memory"], hit.get("score", 0.0),
                                       emotional_charge=affect, now=now)
                item = field.discharge(now)
                if not item:
                    dp.refund()
                    receipt("no_candidate", **ev)
                    field.save()
                    continue
                seed = next((h["memory"] for h in hits
                             if h["memory"].get("id") == item.get("seed_id")),
                            None)
                if seed is None:
                    seed = next((m for m in engine.organ.memories
                                 if m.get("id") == item.get("seed_id")), None)
                if seed is None:
                    dp.refund()
                    receipt("stale_candidate", key=item.get("key"), **ev)
                    field.save()
                    continue
                node = item.get("node") or (seed.get("content") or "")[:240]
                dom = engine.osc.dominant() if engine.osc else "alpha"
                dt = drift_type(dom, bands.get("theta", 0.2))
                idle_model = metabolism.get("idle_model")
                if not idle_model:
                    dp.refund()
                    field.queue.put(item, item.get("salience", 0.5), now=now)
                    receipt("no_idle_model", key=item.get("key"), **ev)
                    field.save()
                    continue
                try:
                    thought = generate_idle_thought(engine, idle_model, item, dt)
                except Exception as gen_error:
                    dp.refund()
                    field.queue.put(item, item.get("salience", 0.5), now=now)
                    receipt("generation_error", model=idle_model,
                            error=str(gen_error)[:200], **ev)
                    field.save()
                    continue
                if not thought or thought.lower() == "[quiet]":
                    receipt("quiet", model=idle_model, node=node[:80], **ev)
                    field.save()
                    continue
                mem = engine.organ.encode(
                    thought, cocktail=engine.cocktail,
                    entities=list(seed.get("entities") or [])[:4],
                    mem_type="wandering", origin="lived",
                    fields={"channel": "dmn", "drift_type": dt,
                            "seed_id": seed.get("id"),
                            "gist_eligible": True,
                            "audience": "household"})
                engine.organ.save()
                gist_folded = bool(engine.gist and
                                   engine.gist.update_idle(engine.organ.memories))
                dp.active_node = node
                receipt("drift", drift_type=dt, node=node,
                        text=thought, seed_id=seed.get("id"),
                        salience=round(item.get("salience", 0.0), 3),
                        queue_remaining=len(field.queue), model=idle_model,
                        gist_folded=gist_folded,
                        mem_id=(mem or {}).get("id"), **ev)
                field.save()
        except Exception as e:
            try:
                receipt("error", error=str(e)[:200])
            except Exception:
                pass      # the idle mind must never kill the body


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
              turn_lock=None, speaker: str = None) -> FastAPI:
    from shell.local_identity import load_local_identity
    app = FastAPI(title="JNSQ cockpit", version=CONTRACT_VERSION)
    if os.path.isdir(ASSET_DIR):
        app.mount("/assets", StaticFiles(directory=ASSET_DIR),
                  name="jnsq-assets")
    app.state.engine = engine
    app.state.turn_lock = turn_lock or threading.Lock()
    app.state.max_tokens = max_tokens
    app.state.speaker = speaker or load_local_identity(REPO)["display_name"]

    @app.get("/", response_class=HTMLResponse)
    def page():
        import json
        with open(os.path.join(HERE, "cockpit.html"), encoding="utf-8") as f:
            return f.read().replace("/*CONFIG*/", json.dumps({
                "primary_user": app.state.speaker,
                "persona_avatar": "/api/avatar"}))

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

    @app.get("/api/state")
    def state():
        return app.state.engine.get_state()

    @app.get("/api/theme")
    def theme():
        result = resolve_theme(REPO, app.state.engine.persona,
                               app.state.engine.model)
        result["display_name"] = (
            app.state.engine.personas.get(app.state.engine.persona.lower())
            or {}).get("display_name", app.state.engine.persona)
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
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "a turn is already in flight (one body, one mouth)"})
        try:
            return app.state.engine.take_turn(req.message,
                                              max_tokens=app.state.max_tokens,
                                              speaker=req.speaker or
                                                      app.state.speaker)
        except Exception as e:
            # a lost turn should fail as WORDS, never a plain-text 500
            # the UI can't parse. Traceback still lands in the tenant log.
            import traceback
            traceback.print_exc()
            return JSONResponse(status_code=504, content={
                "error": turn_failure_message(app.state.engine, e)})
        finally:
            app.state.turn_lock.release()

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
                        room_id=args.room or room_cfg.get("id"))
    shared_lock = threading.Lock()
    app = build_app(engine, max_tokens=args.max_tokens,
                    turn_lock=shared_lock, speaker=args.speaker)
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
    from core.dmn import resolve_metabolism
    metabolism = resolve_metabolism((roster or {}).get("metabolism"))
    if metabolism.get("idle_model"):
        _sp = os.path.join(REPO, "specs", "models",
                           f"{metabolism['idle_model']}.yaml")
        if not os.path.exists(_sp):
            print(f"[cockpit] WARN metabolism.idle_model "
                  f"'{metabolism['idle_model']}' has no spec — "
                  f"discharge tiers that spend it will refuse")
    threading.Thread(target=dmn_loop,
                     args=(engine, shared_lock, metabolism, stop),
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
        engine.close()


if __name__ == "__main__":
    main()
