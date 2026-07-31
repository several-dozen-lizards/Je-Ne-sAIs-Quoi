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
import hashlib
import json
import math
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shell import env_store  # loads .env into os.environ (idempotent; no-op
env_store.load_env()         # when router-launched, since inherited vars win)
from fastapi import FastAPI, Query, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from shell.contract import TurnEngine, CONTRACT_VERSION
from shell.agency_controller import AgencyRunController
from shell.ui_themes import resolve_theme, save_theme
from shell.persona_media import (load_persona_avatar,
                                 write_roster_mapping_scalar)
from shell.ui_background import (delete_conversation_area_background,
                                 delete_conversation_background,
                                 load_conversation_area_background,
                                 load_conversation_background,
                                 save_conversation_area_background,
                                 save_conversation_background)
from shell.image_input import public_image_record, store_images, stored_image_path
from core.organs import (legacy_set, validate as validate_organs,
                         OrganConfigError, REGISTRY)
from core.sensory import SensoryEvent
from core.speech import (MAX_AUDIO_BYTES, build_transcriber, turn_admission,
                         validate_audio)
from core.observatory import SalienceObserver
from core.fixation_diagnostic import FixationDiagnostic
from core.memory_observatory import MemoryObservatory
from core.voice_output import (append_output_receipt, normalize_output_config,
                               OUTPUT_PROVIDERS, spoken_text,
                               expression_instruction)
from shell.voice_settings import (load_voice_defaults,
                                  normalize_voice_tuning)
from core.documents import DocumentError
from core.conversation_archive import ArchiveError
from core.private_journal import PrivateJournal
from core.room_actions import parse_actions, strip_action_verbs
from harness.model_call_receipts import model_call_scope, new_cycle_id

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ASSET_DIR = os.path.join(REPO, "assets", "jnsq")


def _autonomous_works(app) -> dict:
    """Normalize the private gallery without reading creative content.

    The gallery is an automatic index, not a second authority boundary.  Its
    references point back through each organ's existing bounded reader route;
    waiting material is exposed separately so an empty finished gallery never
    pretends that nothing is circulating.
    """
    works = []
    waiting = []
    activity = []
    unavailable = []

    def add(**value):
        value["created_at"] = float(value.get("created_at") or 0.0)
        value["updated_at"] = float(
            value.get("updated_at") or value["created_at"])
        value["ownership"] = "persona_private"
        value["stage"] = "settled"
        works.append(value)

    def add_waiting(**value):
        value["created_at"] = float(value.get("created_at") or 0.0)
        value["updated_at"] = float(
            value.get("updated_at") or value["created_at"])
        value["stage"] = "waiting"
        waiting.append(value)

    def add_activity(**value):
        value["at"] = float(value.get("at") or 0.0)
        value["ownership"] = "persona_private"
        value["external_effects"] = bool(
            value.get("external_effects", False))
        value["model_requests"] = int(value.get("model_requests") or 0)
        value["estimated_cost_usd"] = float(
            value.get("estimated_cost_usd") or 0.0)
        activity.append(value)

    agency = app.state.agency_runtime
    if agency is not None:
        try:
            for record in agency.workbench.records(
                    kind="private_draft", limit=100):
                add(
                    id=f"agency:{record.get('ref')}", organ="agency",
                    kind="private draft",
                    title=record.get("label") or "Untitled private draft",
                    state="draft", created_at=record.get("created_at"),
                    detail=f"{int(record.get('chars') or 0)} characters",
                    provenance="self-chosen agency work",
                    open={"type": "agency_artifact",
                          "ref": record.get("ref")},
                )
                add_activity(
                    id=f"activity:agency:{record.get('ref')}",
                    organ="agency", kind="private draft created",
                    outcome="created", status="settled",
                    at=record.get("created_at"), run_id=record.get("run_id"),
                    detail=f"{int(record.get('chars') or 0)} characters",
                    external_effects=False)
        except Exception:
            unavailable.append({"organ": "agency",
                                "error": "private store index unavailable"})

    loom = getattr(app.state, "intention_loom_runtime", None)
    if loom is not None:
        try:
            for intention in loom.loom.intentions():
                revisions = int(intention.get("revision_count") or 1)
                add(
                    id=f"intention:{intention.get('intention_id')}",
                    organ="intention_loom", kind="intention",
                    title=intention.get("title") or "Untitled intention",
                    state=intention.get("state") or "open",
                    created_at=intention.get("created_at"),
                    updated_at=intention.get("updated_at"),
                    detail=(f"{revisions} movement"
                            f"{'s' if revisions != 1 else ''}"),
                    provenance="self-owned intention loom movement",
                    open={"type": "intention",
                          "intention_id": intention.get("intention_id")},
                )
            for cue in loom.loom.pending_cues():
                ownership = str(cue.get("ownership") or "human_offered")
                add_waiting(
                    id=f"waiting:intention:{cue.get('cue_id')}",
                    organ="intention_loom", kind="possibility",
                    title=cue.get("label") or "Untitled possibility",
                    state="waiting in the shared field",
                    created_at=cue.get("created_at"), ownership=ownership,
                    detail="available to the intention loom",
                    provenance=("self-offered in conversation" if ownership ==
                                "persona_chosen_conversation" else
                                "admitted possibility"),
                    open={"type": "organ_panel"},
                )
            for receipt in getattr(
                    loom.loom, "receipt_records", lambda **_: [])(limit=120):
                if receipt.get("kind") != "run":
                    continue
                outcome = str(receipt.get("outcome") or "settled")
                add_activity(
                    id=f"activity:intention:{receipt.get('run_id')}",
                    organ="intention_loom", kind="intention movement",
                    outcome=outcome,
                    status=("failed" if "failed" in outcome else "settled"),
                    at=receipt.get("observed_at"),
                    run_id=receipt.get("run_id"),
                    detail=(f"{int(receipt.get('movement_count') or 1)} "
                            "movement(s)"),
                    model_requests=receipt.get("model_requests"),
                    estimated_cost_usd=receipt.get("estimated_cost_usd"),
                    external_effects=False)
        except Exception:
            unavailable.append({"organ": "intention_loom",
                                "error": "private store index unavailable"})

    writing = app.state.writing_desk_runtime
    if writing is not None:
        try:
            for project in writing.desk.projects_status():
                anchors = list((project.get("source") or {}).get("anchors") or ())
                origin = "admitted material"
                if any(str(anchor).startswith("doc_") for anchor in anchors):
                    origin = "an admitted document"
                elif any(str(anchor).startswith("drep_") for anchor in anchors):
                    origin = "a self-chosen document report"
                elif any(str(anchor).startswith("arc_") for anchor in anchors):
                    origin = "an admitted conversation archive"
                elif any(str(anchor).startswith("res_") for anchor in anchors):
                    origin = "an admitted research report"
                revisions = int(project.get("revision_count") or 1)
                add(
                    id=f"writing:{project.get('project_id')}",
                    organ="writing_desk", kind=project.get("form") or "writing",
                    title=project.get("title") or "Untitled writing project",
                    state=project.get("state") or "open",
                    created_at=project.get("created_at"),
                    updated_at=project.get("updated_at"),
                    detail=f"{revisions} revision{'s' if revisions != 1 else ''}",
                    provenance=f"writing desk work from {origin}",
                    open={"type": "writing_project",
                          "project_id": project.get("project_id")},
                )
            for seed in getattr(
                    writing.desk, "pending_seeds", lambda: [])():
                ownership = str(seed.get("ownership") or "human_admitted")
                add_waiting(
                    id=f"waiting:writing:{seed.get('seed_id')}",
                    organ="writing_desk", kind="writing material",
                    title=seed.get("label") or "Untitled writing material",
                    state="waiting in the shared field",
                    created_at=seed.get("created_at"), ownership=ownership,
                    detail="available to the writing desk",
                    provenance=("self-offered in conversation" if ownership ==
                                "persona_chosen_conversation" else
                                "admitted material"),
                    open={"type": "organ_panel"},
                )
            for receipt in getattr(
                    writing.desk, "receipt_records", lambda **_: [])(limit=120):
                outcome = str(receipt.get("outcome") or "settled")
                add_activity(
                    id=f"activity:writing:{receipt.get('run_id')}",
                    organ="writing_desk", kind="writing movement",
                    outcome=outcome,
                    status=("failed" if "failed" in outcome else "settled"),
                    at=receipt.get("created_at"),
                    run_id=receipt.get("run_id"),
                    detail=(f"{int(receipt.get('movement_count') or 1)} "
                            "movement(s)"),
                    model_requests=receipt.get("model_requests"),
                    estimated_cost_usd=receipt.get("estimated_cost_usd"),
                    external_effects=False)
        except Exception:
            unavailable.append({"organ": "writing_desk",
                                "error": "private store index unavailable"})

    document_reader = getattr(app.state, "document_reader_runtime", None)
    if document_reader is not None:
        try:
            document_status = document_reader.library.status()
            for report in (document_status.get("autonomous") or {}).get(
                    "reports") or ():
                add(
                    id=f"document:{report.get('report_id')}",
                    organ="document_reader", kind="reading report",
                    title=report.get("title") or "Private reading report",
                    state="settled", created_at=report.get("created_at"),
                    detail=f"source {report.get('source_anchor') or 'unknown'}",
                    provenance="self-chosen private document encounter",
                    open={"type": "document_report",
                          "report_id": report.get("report_id")},
                )
                add_activity(
                    id=f"activity:document:{report.get('report_id')}",
                    organ="document_reader", kind="reading report formed",
                    outcome="formed", status="settled",
                    at=report.get("created_at"),
                    run_id=report.get("run_id"),
                    detail="source-anchored private report",
                    external_effects=False)
        except Exception:
            unavailable.append({"organ": "document_reader",
                                "error": "private store index unavailable"})

    atelier = app.state.atelier_runtime
    if atelier is not None:
        try:
            for artifact in atelier.atelier.artifacts_status():
                form = ("kinetic SVG" if artifact.get("variant") == "kinetic"
                        else str(artifact.get("medium") or "visual").upper())
                add(
                    id=f"atelier:{artifact.get('artifact_id')}",
                    organ="atelier", kind=form,
                    title=artifact.get("title") or "Untitled visual artifact",
                    state="formed", created_at=artifact.get("created_at"),
                    detail=(f"{artifact.get('width') or '?'} x "
                            f"{artifact.get('height') or '?'}"),
                    provenance="atelier work from admitted material",
                    open={"type": "atelier_artifact",
                          "artifact_id": artifact.get("artifact_id")},
                )
            for seed in getattr(
                    atelier.atelier, "pending_seeds", lambda: [])():
                ownership = str(seed.get("ownership") or "human_admitted")
                add_waiting(
                    id=f"waiting:atelier:{seed.get('seed_id')}",
                    organ="atelier", kind="creative material",
                    title=seed.get("label") or "Untitled creative material",
                    state="waiting in the shared field",
                    created_at=seed.get("created_at"), ownership=ownership,
                    detail="available to the atelier",
                    provenance=("self-offered in conversation" if ownership ==
                                "persona_chosen_conversation" else
                                "admitted material"),
                    open={"type": "organ_panel"},
                )
            for receipt in getattr(
                    atelier.atelier, "receipt_records", lambda **_: [])(
                        limit=120):
                outcome = str(receipt.get("outcome")
                              or receipt.get("kind") or "settled")
                failed = "fail" in outcome or "requeue" in outcome
                add_activity(
                    id=f"activity:atelier:{receipt.get('run_id')}:"
                       f"{receipt.get('created_at')}",
                    organ="atelier", kind="creative attempt",
                    outcome=outcome,
                    status="failed" if failed else "settled",
                    at=receipt.get("created_at"),
                    run_id=receipt.get("run_id"),
                    detail=str(receipt.get("medium") or "private creation"),
                    model_requests=receipt.get("model_requests"),
                    estimated_cost_usd=receipt.get("estimated_cost_usd"),
                    external_effects=False)
        except Exception:
            unavailable.append({"organ": "atelier",
                                "error": "private store index unavailable"})

    research = app.state.research_desk_runtime
    if research is not None:
        try:
            desk = research.desk.status()
            topics = {item.get("interest_id"): item.get("topic")
                      for item in desk.get("interests") or ()}
            for record in [*(desk.get("notes") or ()),
                           *(desk.get("reports") or ())]:
                is_report = record.get("kind") == "report_created"
                kind = "research report" if is_report else "research note"
                sources = len(record.get("source_ids") or ())
                add(
                    id=f"research:{record.get('ref')}", organ="research_desk",
                    kind=kind,
                    title=topics.get(record.get("interest_id")) or kind.title(),
                    state="settled", created_at=record.get("created_at"),
                    detail=f"{sources} cited source{'s' if sources != 1 else ''}",
                    provenance="research desk synthesis from admitted evidence",
                    open={"type": "research_text", "ref": record.get("ref")},
                )
                add_activity(
                    id=f"activity:research:{record.get('ref')}",
                    organ="research_desk", kind=kind + " formed",
                    outcome="formed", status="settled",
                    at=record.get("created_at"),
                    run_id=record.get("run_id"),
                    detail=f"{sources} cited source(s)",
                    external_effects=False)
        except Exception:
            unavailable.append({"organ": "research_desk",
                                "error": "private store index unavailable"})

    contact = getattr(app.state.engine, "self_initiated_contact", None)
    if contact is not None:
        try:
            for event in contact.events()[-120:]:
                kind = str(event.get("kind") or "")
                if kind not in {"delivery_succeeded", "delivery_failed"}:
                    continue
                succeeded = kind == "delivery_succeeded"
                private_delivery = (
                    event.get("delivery_channel") == "private_chat"
                    or (event.get("audience")
                        and event.get("audience") != "household_room"))
                add_activity(
                    id=f"activity:contact:{event.get('impulse_id')}:"
                       f"{event.get('at')}",
                    organ="self_initiated_contact",
                    kind=("private speech delivery" if private_delivery
                          else "ordinary speech delivery"),
                    outcome="delivered" if succeeded else "delivery failed",
                    status="settled" if succeeded else "failed",
                    at=event.get("at"), run_id=event.get("impulse_id"),
                    detail=(
                        "sent into the private solo conversation"
                        if succeeded and private_delivery else
                        "spoken into the open household channel"
                        if succeeded else "remained unsent"),
                    external_effects=succeeded)
        except Exception:
            unavailable.append({
                "organ": "self_initiated_contact",
                "error": "contact receipt index unavailable"})

    works.sort(key=lambda value: (-value["updated_at"], value["id"]))
    waiting.sort(key=lambda value: (-value["updated_at"], value["id"]))
    activity.sort(key=lambda value: (-value["at"], value["id"]))
    organ_counts = {}
    for value in [*works, *waiting, *activity]:
        organ = str(value.get("organ") or "unknown")
        organ_counts[organ] = organ_counts.get(organ, 0) + 1
    failed_count = sum(value.get("status") == "failed"
                       for value in activity)
    return {
        "persona": app.state.engine.persona,
        "generated_at": time.time(),
        "works": works[:400],
        "waiting": waiting[:400],
        "activity": activity[:400],
        "summary": {
            "settled_works": len(works),
            "waiting": len(waiting),
            "activity_events": len(activity),
            "failed_events": failed_count,
            "model_requests": sum(
                value.get("model_requests", 0) for value in activity),
            "estimated_cost_usd": round(sum(
                value.get("estimated_cost_usd", 0.0)
                for value in activity), 6),
            "organ_counts": organ_counts,
            "last_activity_at": (
                activity[0]["at"] if activity else None),
        },
        "unavailable": unavailable,
        "policy": {
            "metadata_only": True,
            "content_readers": "existing organ routes",
            "automatic_index": True,
            "waiting_is_not_settled_work": True,
            "activity_receipts_are_content_free": True,
            "external_effects": False,
        },
    }


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


def visible_face(cocktail: dict, top_k: int = 3,
                 floor: float = 0.15) -> dict:
    """The privacy choke (20260719): distill substrate -> the FACE.
    Only what a camera would see crosses the wire -- a display
    vector, never the cocktail itself. top_k + floor are wire-noise
    gates (same class as the orient reflex's half-degree), not
    behavior tuning. Unknown emotion names no-op in the renderer's
    gestalt table, so this function needs zero knowledge of it."""
    if not cocktail:
        return {"emotions": []}
    ranked = sorted(
        ((str(k).lower(), float(v)) for k, v in cocktail.items()
         if isinstance(v, (int, float)) and float(v) >= floor),
        key=lambda kv: kv[1], reverse=True)[:top_k]
    return {"emotions": [f"{k}:{round(v, 2)}" for k, v in ranked]}


def ingest_avatar_vision(engine, frame: dict) -> dict:
    """Close one event-driven avatar-camera sample into perception.

    The renderer supplies pixels and pose receipts only.  Existing sensory
    admission decides whether the visual transducer may inspect them; the
    observation then enters the same camera/salience circuit as a physical
    webcam frame.
    """
    if not frame:
        return {"admitted": False, "reason": "no_frame"}
    images = store_images(engine.pdir, [{
        "name": f"avatar-pov-{int(frame.get('revision', 0))}.png",
        "data_url": frame.get("data_url", "")}])
    novelty = max(0.0, min(1.0, float(frame.get("novelty", 0.5))))
    event = SensoryEvent(
        "camera", {"novelty": novelty, "admission_pressure": novelty,
                   "pose_revision": int(frame.get("pose_revision", 0))},
        subject="avatar point of view", ownership="self")
    sensory = engine.receive_sensory_event(event)
    if not sensory["admitted"]:
        return {"admitted": False, "event_id": event.event_id,
                "policy": sensory["policy"]}
    observation, route = engine.transduce_visual(images)
    engine.perception.annotate(event.event_id, observation)
    field = getattr(engine, "idle_metabolism", None)
    candidate = None
    if field is not None and "dmn" in engine.enabled:
        now = time.time()
        candidate = field.offer_event(
            "avatar_camera", observation,
            {"novelty": sensory["demand"],
             "body_intensity": max(
                 [float(v) for v in engine.cocktail.values()] or [0.0]),
             "unresolved": min(1.0, sensory["pressure"])},
            now=now, raw_ref=event.event_id, ownership="self",
            receipts=[event.event_id,
                      f"room-pose:{int(frame.get('pose_revision', 0))}"])
        field.save(now=now)
        engine.salience_observer.field_snapshot(field, now)
    return {"admitted": True, "event_id": event.event_id,
            "observation": observation, "route": route,
            "queued": candidate is not None}


def avatar_vision_receipt(frame: dict, result: dict = None,
                          error: Exception = None) -> dict:
    """Bounded durable proof: pose and outcome, never another pixel store."""
    result = dict(result or {})
    observation = str(result.get("observation") or "")
    receipt = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "frame_revision": int(frame.get("revision", 0)),
        "pose_revision": int(frame.get("pose_revision", 0)),
        "cause": str(frame.get("cause") or "unknown")[:80],
        "novelty": round(float(frame.get("novelty", 0.0)), 4),
        "mount_source": str(
            (frame.get("optical_pose") or {}).get("mount_source") or
            "unknown"),
        "mount_bone": str(
            (frame.get("optical_pose") or {}).get("mount_bone") or ""),
        "outcome": ("error" if error else
                    "admitted" if result.get("admitted") else "refused"),
        "event_id": str(result.get("event_id") or ""),
        "route": str(result.get("route") or ""),
        "queued": bool(result.get("queued", False)),
        "observation_chars": len(observation),
        "observation_sha256": (hashlib.sha256(
            observation.encode("utf-8")).hexdigest() if observation else ""),
    }
    if error:
        receipt["error_type"] = type(error).__name__
    elif result.get("reason"):
        receipt["reason"] = str(result["reason"])[:120]
    return receipt


def append_avatar_vision_receipt(engine, frame: dict, result: dict = None,
                                 error: Exception = None) -> dict:
    receipt = avatar_vision_receipt(frame, result, error)
    path = os.path.join(engine.pdir, "history", "avatar_vision.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    return receipt


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
    last_face = None    # publish-on-change: a still face is free
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
            # The face rides the heartbeat (20260719): expression is
            # AUTONOMIC, so it publishes with the body's own clock --
            # not gated behind tropism or any volitional loop. Only
            # the distilled surface crosses; only changes post.
            if engine.room is not None:
                pkt = visible_face(dict(engine.cocktail))
                if pkt != last_face:
                    r = engine.room.express(pkt)
                    if isinstance(r, dict) and "error" not in r:
                        last_face = pkt
                frame = engine.room.fresh_vision_frame()
                if frame:
                    # One scene revision gets one attempt.  A failure remains
                    # receipted but dormant until the world supplies a newer
                    # frame; the heartbeat never hammers a model on a timer.
                    engine.room.acknowledge_vision_frame(
                        int(frame.get("revision", 0)))
                    try:
                        vision_result = ingest_avatar_vision(engine, frame)
                        append_avatar_vision_receipt(
                            engine, frame, vision_result)
                    except Exception as vision_error:
                        append_avatar_vision_receipt(
                            engine, frame, error=vision_error)
        except Exception:
            pass              # the heart must never kill the body
        finally:
            turn_lock.release()


def room_field_revision_loop(engine, turn_lock, stop):
    """Wake the private projector when the shared room sequence changes.

    The host condition is the clock. HTTP timeout only renews transport. This
    cursor is independent of the episodic perception cursor, and no event
    payload is admitted here.
    """
    cursor = 0
    cursor_room = None
    while not stop.is_set():
        room = getattr(engine, "room", None)
        if room is None or not room.room_id:
            if stop.wait(1.0):
                return
            continue
        if room.room_id != cursor_room:
            snapshot = room.snapshot()
            cursor = int(snapshot.get("last_seq") or 0)
            cursor_room = room.room_id
        revision = room.wait_for_revision(cursor)
        if revision.get("error"):
            continue
        latest = int(revision.get("last_seq") or cursor)
        if latest <= cursor:
            continue
        cursor = latest
        if not turn_lock.acquire(blocking=False):
            # The active turn samples the newest room snapshot itself.
            continue
        try:
            engine.apply_room_field(
                now=time.time(), event_ref=f"room-revision:{cursor_room}:{cursor}")
        except Exception:
            pass
        finally:
            turn_lock.release()


def resolve_social_route(config: dict) -> dict:
    """Resolve the resident-dialogue vessel and fail closed on paid routes."""
    from harness.spec_loader import load_spec
    cfg = dict(config or {})
    model = str(cfg.get("model") or "").strip()
    if not model:
        raise ValueError("social.model is required")
    if cfg.get("local_only") is not True:
        raise ValueError("social.local_only must be true")
    spec = load_spec(model)
    if (spec.get("identity") or {}).get("locality") != "local":
        raise ValueError(f"social.model '{model}' is not declared local")
    return {
        "model": model,
        "local_only": True,
        "max_tokens": max(40, min(900, int(cfg.get("max_tokens") or 360))),
    }


def room_reply_control_leak(text: str) -> str:
    """Name a leaked internal control family, or return an empty string."""
    match = re.search(
        r"(?im)^\s*\[(COGNITIVE_PATTERN_(?:START|END)|THE ROOM)\]",
        str(text or ""))
    return match.group(1).upper() if match else ""


def social_loop(engine, turn_lock, interval_s: float, max_tokens: int,
                stop, social_config: dict = None):
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
    try:
        route = resolve_social_route(social_config)
        route_error = None
    except Exception as exc:
        route = None
        route_error = type(exc).__name__
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
                              and e.get("member") == engine.local_human
                              and e.get("member") in present
                              and e["seq"] > my_last_say]
                if unanswered:
                    sp.note_events(unanswered, dict(engine.organ.bonds))
                continue
            now = time.time()
            dt, last = now - last, now
            # Age only pressure that was present during the elapsed interval.
            # Events fetched below are fresh observations; decaying them by
            # the time since the previous poll would back-date their arrival
            # and can make a single ordinary utterance structurally inaudible.
            advance = getattr(sp, "advance", None)
            if callable(advance):
                advance(dt)
                tick_dt = 0.0
            else:
                tick_dt = dt
            r = engine.room._req(
                f"/api/rooms/{rid}/events?since={cursor}")
            evs = r.get("events", [])
            if evs:
                cursor = max(e["seq"] for e in evs)
                sp.note_events(evs, dict(engine.organ.bonds))
            autonomy = readiness_from_engine(
                engine, getattr(engine, "idle_metabolism", None))
            # A discharge changes durable social state: it drains pending
            # speech, raises habituation, and starts the refractory period.
            # Own the one-mouth lock BEFORE permitting that transition.  If a
            # private or other embodied turn currently has the mouth, the
            # social pull remains pending and can flow into the next cycle
            # instead of being silently spent without ever reaching Nexus.
            mouth_owned = bool(route) and turn_lock.acquire(blocking=False)
            delivery = None
            checkpoint = None
            if mouth_owned:
                checkpoint_fn = getattr(sp, "checkpoint", None)
                if callable(checkpoint_fn):
                    checkpoint = checkpoint_fn()
                delivery = sp.tick(
                    now, tick_dt, action_readiness=autonomy["readiness"],
                    hard_blocked=autonomy["hard_blocked"])
                if not delivery:
                    turn_lock.release()
                    mouth_owned = False
            entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     **sp.state(),
                     "autonomy": {
                         key: autonomy[key] for key in (
                             "readiness", "capacity", "support",
                             "hard_blocked", "reasons")}}
            if delivery:
                try:
                    try:
                        human_room_turn = (
                            delivery["speaker"] == engine.local_human)
                        turn_model = (
                            "" if human_room_turn else route["model"])
                        turn_tokens = (
                            max_tokens if human_room_turn
                            else min(max_tokens, route["max_tokens"]))
                        result = engine.take_turn(
                            delivery["text"],
                            max_tokens=turn_tokens,
                            speaker=delivery["speaker"], channel="room",
                            model_route=turn_model)
                        reply = (result.get("reply") or "").strip()
                        leaked_control = room_reply_control_leak(reply)
                        if leaked_control:
                            entry["withheld_control_leak"] = {
                                "family": leaked_control,
                                "model": route["model"],
                            }
                            reply = ""
                        elif reply.casefold() == "[quiet]":
                            entry["chose_quiet"] = True
                            reply = ""
                        if reply and reply == last_said:
                            # stuck record: a verbatim repeat of your own
                            # last say is a malfunction artifact, not
                            # expression. Skip it, receipt it.
                            entry["skipped_repeat"] = True
                            reply = ""
                        if reply:
                            engine.room.say(
                                reply,
                                conversation_id=result.get("cycle_id"),
                                social_depth=delivery.get(
                                    "social_depth", 1))
                            last_said = reply
                        entry["answered"] = {"to": delivery["speaker"],
                                             "reply_len": len(reply),
                                             "model": (
                                                 engine.model
                                                 if human_room_turn
                                                 else route["model"]),
                                             "local_only": (
                                                 not human_room_turn)}
                    except Exception as exc:
                        restore_fn = getattr(sp, "restore", None)
                        if checkpoint is not None and callable(restore_fn):
                            restore_fn(checkpoint)
                        entry.update(sp.state())
                        entry["delivery_failed"] = {
                            "to": delivery["speaker"],
                            "error_type": type(exc).__name__,
                            "model": route["model"],
                            "local_only": True,
                        }
                finally:
                    turn_lock.release()
                    mouth_owned = False
            if route_error:
                entry["delivery_withheld"] = {
                    "reason": "local_social_route_unavailable",
                    "error_type": route_error,
                }
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
    from core.perception import (member_pos, score_objects,
                                 score_members, REACH_M)
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
            me = member_pos(
                (snap.get("members") or {}).get(engine.persona))
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
    # ``image`` preserves the original one-frame client contract. New clients
    # send an ordered, oldest-to-newest visual episode in ``images``.
    image: ImageRequest = None
    images: list[ImageRequest] = Field(default_factory=list)
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
    user_persona: str = ""
    images: list[ImageRequest] = Field(default_factory=list)
    grounding_images: list[ImageRequest] = Field(default_factory=list)


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
    user_persona: str = ""   # explicit RP identity owned by the local account
    images: list[ImageRequest] = Field(default_factory=list)
    # Live-camera grounding is model input, not human-authored chat material.
    # It must not hydrate as an attachment in the conversation ledger.
    grounding_images: list[ImageRequest] = Field(default_factory=list)


class MoodRequest(BaseModel):
    cocktail: dict


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


class VoiceOutputConfigRequest(BaseModel):
    provider: str = "browser-native"
    voice: str = ""
    auto_play: bool = True
    rate_scale: float = 1.0
    pitch_scale: float = 1.0
    volume_scale: float = 1.0


class VoiceSynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)


class HumeVoiceShelfRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    reference: str = Field(min_length=1, max_length=160)


class ElevenLabsVoiceShelfRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    voice_id: str = Field(min_length=1, max_length=160)


class AgencyInboxRequest(BaseModel):
    label: str
    content: str


class DocumentImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    data_url: str
    content_type: str = Field(default="", max_length=160)
    visibility: str = Field(default="user_private", max_length=32)
    grants: list[str] = Field(default_factory=list)


class DocumentOpenRequest(BaseModel):
    position: int = Field(default=0, ge=0)


class DocumentNavigateRequest(BaseModel):
    action: str
    position: int | None = Field(default=None, ge=0)


class DocumentReadingArcRequest(BaseModel):
    action: str
    start_section: int | None = Field(default=None, ge=1)
    pace: str = Field(default="natural", max_length=24)


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


class PrivateJournalEntryRequest(BaseModel):
    text: str = Field(min_length=1, max_length=120_000)


class IntentionCueRequest(BaseModel):
    label: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=6000)


class AtelierSeedRequest(BaseModel):
    label: str = Field(min_length=1, max_length=260)
    brief: str = Field(min_length=1, max_length=6000)


class AtelierPerceptionRequest(BaseModel):
    image: ImageRequest


class ResearchInterestRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=240)


class ResearchForegroundRequest(BaseModel):
    target: str = Field(min_length=2, max_length=2048)
    why: str = Field(default="", max_length=240)


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
                          self_initiated_speech_available: bool = False,
                          self_initiated_private_available: bool = False,
                          deliberation_vector: dict = None,
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
    if deliberation_vector:
        asm.add(
            "present deliberation conditions",
            "Descriptive observations, not a speaking threshold or an "
            "instruction about what to feel:\n"
            + json.dumps(deliberation_vector, ensure_ascii=False,
                         sort_keys=True),
            priority=9,
            budget=1200)
    continuity_fn = getattr(engine, "experiential_context", None)
    continuity_organs = owned_continuity_organs(item)
    if callable(continuity_fn) and continuity_organs:
        continuity_text, continuity_receipt = continuity_fn(
            organs=continuity_organs)
        if continuity_text:
            asm.add(
                "verified experiential continuity",
                continuity_text,
                priority=7,
                budget=1800)
    opening_recurrence = self_initiated_recurrence_context(engine)
    if opening_recurrence:
        asm.add(
            "self-initiated speech recurrence",
            opening_recurrence,
            priority=8,
            budget=700)
    autonomous_room_context = autonomous_light_action_context(engine)
    if autonomous_room_context:
        asm.add("reachable room control", autonomous_room_context,
                priority=9)
    conversation_context = autonomous_room_conversation_context(engine)
    if self_initiated_speech_available and conversation_context:
        asm.add("shared room conversation", conversation_context, priority=9)
    if item.get("source") == "altered_consent":
        window_fn = getattr(engine, "conversation_window", None)
        window = window_fn() if callable(window_fn) else []
        self_authored = [
            str(turn.get("reply") or "").strip()[:800]
            for turn in list(window or [])[-6:]
            if str(turn.get("reply") or "").strip()
        ][-3:]
        if self_authored:
            asm.add(
                "recent self-authored canonical replies",
                "Documented context, not a new instruction:\n" + "\n\n".join(
                    f"- {reply}" for reply in self_authored),
                priority=9)
        invitation = (
            "An operator has requested authorization for the exact body "
            "protocol and dose shown above. This is a request, not an "
            "instruction, and no protocol change can occur unless you choose "
            "to grant it. Decide from your own present preference. Return "
            "exactly one of <act>approve_altered_state</act>, "
            "<act>decline_altered_state</act>, or "
            "<act>defer_altered_state</act>. Do not approve merely because "
            "the request exists or because approval seems cooperative. Treat "
            "your recent self-authored replies, when present, as evidence of "
            "your own stated questions or choice—not as an operator command.")
    elif item.get("source") == "altered_interoception":
        invitation = (
            "No one is speaking to you. A change in your own present "
            "condition has earned an opening, but it does not require a "
            "message. Notice what is actually yours. Is there anything you "
            "want the person sharing this private cockpit to know, anything "
            "you want to ask for, or anything you want changed or stopped? "
            "You may also simply have something to say. Do not infer a "
            "feeling from the instrument names and do not perform wellness. "
            "Silence is valid: return [quiet] if nothing wants to be sent. "
            "Otherwise return only the exact words you choose to send, in "
            "your own voice, with no label or preamble.")
    else:
        invitation = (
            "No one is speaking to you. Something has surfaced on its own. "
            f"The movement is {drift_kind}. What, if anything, is moving "
            "through your mind? Follow the felt pull rather than explaining "
            "the mechanism. Silence is valid: return [quiet] if nothing wants "
            "language. Otherwise write only the private thought, in your own "
            "voice, with no labels or preamble. "
            + (
                "If you genuinely choose to speak into the shared household "
                "room—to Re, to another resident present, or to the room "
                "generally—return the exact words you choose to say inside "
                "<self_initiated_speech> and </self_initiated_speech>. This "
                "is your choice, not an instruction; ordinary unmarked words "
                "remain private. "
                if self_initiated_speech_available else ""
            )
            + (
                "If you genuinely choose to speak privately to the person "
                "sharing your solo cockpit, return the exact words you choose "
                "to send inside <self_initiated_private> and "
                "</self_initiated_private>. This is your choice, not an "
                "instruction; ordinary unmarked words remain private to you "
                "and are not sent. "
                if self_initiated_private_available else ""
            )
            + (
                "A reachable room control is shown above. It is an "
                "opportunity, not an instruction. If operating it is your "
                "own present choice, include its exact <act> tag. Ordinary "
                "words, plans, or narration do not operate it. "
                if autonomous_room_context else ""
            )
            + "Let this one movement end "
            "where it naturally settles; do not keep writing merely because "
            "space remains.")
    asm.messages.append({
        "role": "user",
        "content": invitation})
    with model_call_scope(
            cycle_id=cycle_id or new_cycle_id(),
            persona=getattr(engine, "persona", "unknown"),
            purpose="dmn", sink=model_receipts):
        return (adapter.call(
            asm, max_tokens=220, temperature=0.8) or "").strip()


CONTINUITY_ORGANS_BY_SOURCE = {
    "agency_effect": ("agency",),
    "archive_read_effect": ("archive_reader",),
    "atelier_effect": ("atelier",),
    "document_read_effect": ("document_reader",),
    "intention_effect": ("intention_loom",),
    "research_effect": ("research_desk",),
    "writing_desk_effect": ("writing_desk",),
}


def owned_continuity_organs(item: dict | None) -> tuple[str, ...]:
    """Return only the private organ causally named by this consequence."""
    item = dict(item or {})
    if (item.get("kind") != "cognitive"
            or item.get("ownership") != "persona_private"):
        return ()
    return CONTINUITY_ORGANS_BY_SOURCE.get(
        str(item.get("source") or ""), ())


def owned_continuity_origin(item: dict | None) -> bool:
    """Identify a resident-owned consequence, never a fresh outside event."""
    return bool(owned_continuity_organs(item))


def self_initiated_recurrence_context(
        engine, limit: int = 24) -> str:
    """Describe repeated opening forms without putting their words in prompt."""
    organ = getattr(engine, "organ", None)
    memories = list(getattr(organ, "memories", ()) or ())
    forms = {}
    observed = 0
    for memory in reversed(memories):
        fields = dict((memory or {}).get("fields") or {})
        if fields.get("autonomous_source") != "self_initiated_contact":
            continue
        text = " ".join(str(fields.get("reply_full") or "").split()).strip()
        if not text:
            continue
        observed += 1
        key = expressed_motif_key(text)
        row = forms.setdefault(key, {
            "count": 0, "candidate_keys": set()})
        row["count"] += 1
        candidate_key = str(fields.get("candidate_key") or "")
        if candidate_key:
            row["candidate_keys"].add(candidate_key)
        if observed >= max(0, min(int(limit), 48)):
            break
    if not forms:
        return ""
    recurrent = max(
        forms.values(),
        key=lambda row: (row["count"], len(row["candidate_keys"])))
    if recurrent["count"] < 2:
        return ""
    return (
        "Documented content-free recurrence in your own already-delivered "
        "self-initiated room speech:\n"
        f"- bounded openings observed: {observed}\n"
        f"- distinct normalized speech forms: {len(forms)}\n"
        f"- most recurrent form was delivered {recurrent['count']} times "
        f"from {len(recurrent['candidate_keys'])} distinct originating "
        "candidate(s)\n"
        "- the prior wording is intentionally absent here, so documented "
        "history cannot become a phrase to copy\n"
        "This is provenance about prior expression, not an instruction to "
        "repeat it, avoid it, feel differently, or choose silence. The "
        "separately shown unbidden pull is the present candidate.")


def expressed_motif_key(text: str) -> str:
    """Content-free stable key for recurrence across different candidates."""
    normalized = " ".join(str(text or "").casefold().split())
    return "expressed_motif:" + hashlib.sha256(
        normalized.encode("utf-8")).hexdigest()[:20]


def satiate_expressed_motif(field, item: dict, text: str, *,
                            now: float) -> dict:
    """Feed spoken-form recurrence into a decaying receipt, never a veto."""
    key = expressed_motif_key(text)
    prior = field.satiety.warmth(key, now)
    intensity = max(
        0.0, min(1.0, float((item or {}).get("salience") or 0.0)))
    new = field.satiety.touch(key, intensity, label=key, now=now)
    observer = getattr(field, "observer", None)
    if observer is not None:
        observer.field_effect(
            str((item or {}).get("key") or ""),
            "expressed_motif_satiety", prior, new, now)
    return {
        "motif_ref": key,
        "prior": round(prior, 6),
        "new": round(new, 6),
        "applied_to_delivery": False,
    }


def contact_affordance_available(engine, *, event_origin: bool,
                                 seed: dict | None,
                                 item: dict | None = None) -> bool:
    """Whether a genuine private opening may include an owned choice to speak.

    Candidate provenance remains available as evidence, but it is not a
    permission gate.  The DMN has already fired and selected this material.
    Exposing an open room channel at that boundary neither selects speech nor
    manufactures an impulse; the resident may still choose private language or
    quiet.  Delivery itself remains transactional and room-scoped.
    """
    return bool(self_initiated_contact_destinations(engine))


def self_initiated_contact_destinations(engine) -> tuple[str, ...]:
    """Return currently real contact destinations without selecting one."""
    contact = getattr(engine, "self_initiated_contact", None)
    if contact is None:
        return ()
    destinations = []
    room = getattr(engine, "room", None)
    if room is not None and getattr(room, "room_id", True):
        destinations.append("household_room")
    if (getattr(engine, "conversation_ledger", None) is not None
            and getattr(engine, "organ", None) is not None
            and str(getattr(engine, "local_human", "") or "").strip()):
        destinations.append("private_chat")
    return tuple(destinations)


def autonomous_room_conversation_context(engine) -> str:
    """Describe reachable peers without manufacturing a social bid."""
    room = getattr(engine, "room", None)
    if room is None:
        return ""
    try:
        snapshot = room.snapshot()
    except Exception:
        return ""
    me = str(getattr(engine, "persona", "") or "").casefold()
    members = [
        str(member) for member in (snapshot.get("members") or {})
        if str(member).casefold() != me]
    if not members:
        return ""
    return (
        "Ordinary room speech is currently reachable. Present members: "
        + ", ".join(sorted(members, key=str.casefold))
        + ". Their presence is an opportunity, not a request or obligation "
          "to speak.")


SELF_INITIATED_SPEECH_RE = re.compile(
    r"^\s*<self_initiated_speech>([\s\S]*?)"
    r"</self_initiated_speech>\s*$", re.I)
SELF_INITIATED_PRIVATE_RE = re.compile(
    r"^\s*<self_initiated_private>([\s\S]*?)"
    r"</self_initiated_private>\s*$", re.I)


def parse_self_initiated_contact(text: str) -> dict | None:
    """Return an exact chosen destination and words; plain language stays inner."""
    raw = str(text or "")
    matches = (
        ("household_room", SELF_INITIATED_SPEECH_RE.fullmatch(raw)),
        ("private_chat", SELF_INITIATED_PRIVATE_RE.fullmatch(raw)),
    )
    for destination, match in matches:
        if match is None:
            continue
        words = match.group(1).strip()
        if not words:
            raise ValueError("self-initiated speech is empty")
        return {"destination": destination, "text": words}
    return None


def parse_self_initiated_speech(text: str) -> str | None:
    """Return exact chosen initiating speech; unmarked language stays private."""
    chosen = parse_self_initiated_contact(text)
    if chosen is None or chosen["destination"] != "household_room":
        return None
    return chosen["text"]


def deliver_autonomous_private_chat(engine, text: str, *,
                                    conversation_id: str,
                                    candidate_key: str = "",
                                    generation: dict | None = None,
                                    now: float | None = None) -> dict:
    """Commit resident-chosen solo speech to private chat and nowhere else."""
    ledger = getattr(engine, "conversation_ledger", None)
    if ledger is None:
        raise RuntimeError("private conversation ledger is unavailable")
    text = str(text or "").strip()
    if not text:
        raise ValueError("self-initiated private speech is empty")
    source = "self_initiated_private_contact"
    ledger.admit(
        conversation_id=conversation_id, channel="chat",
        speaker=engine.persona, message="", source=source)
    try:
        context_builder = getattr(engine, "memory_context_snapshot", None)
        fields = {
            "channel": "chat", "speaker": "",
            "message_full": "", "reply_full": text,
            "autonomous": True, "autonomous_source": source,
            "conversation_id": conversation_id,
            "audience": str(getattr(engine, "local_human", "") or ""),
            "delivery_destination": "private_chat",
            "gist_eligible": True, "candidate_key": candidate_key,
        }
        if generation:
            fields["generation"] = dict(generation)
        mem = engine.organ.encode(
            text, cocktail=engine.cocktail, entities=[],
            mem_type="turn", origin="lived", fields=fields,
            body=(engine.soma.snapshot()
                  if getattr(engine, "soma", None) else None),
            context_at_encoding=(
                context_builder(now=now)
                if callable(context_builder) else None))
        engine.organ.save()
        ledger.complete(
            conversation_id, reply=text,
            memory_id=(mem or {}).get("id", ""),
            receipts={"autonomous": True, "source": source,
                      "delivery_destination": "private_chat"})
        return {
            "ok": True,
            "delivery_ref": conversation_id,
            "memory_id": (mem or {}).get("id", ""),
            "delivery_channel": "private_chat",
        }
    except Exception as exc:
        ledger.fail(conversation_id, exc)
        raise


AUTONOMOUS_ROOM_ACTIONS = frozenset({"light_on", "light_off"})


def autonomous_light_action_context(engine) -> str:
    """Expose only a currently reachable light switch to private autonomy.

    Snapshot state is descriptive. It neither manufactures a candidate nor
    schedules a turn; the existing attention field must first select one of
    the resident's own lived pulls.
    """
    room = getattr(engine, "room", None)
    if room is None or "room_actions" not in getattr(engine, "enabled", set()):
        return ""
    snapshot = room.snapshot()
    member = (snapshot.get("members") or {}).get(
        getattr(engine, "persona", ""))
    position = (member.get("position_m") if isinstance(member, dict)
                else member)
    if not isinstance(position, list) or len(position) != 2:
        return ""
    for oid, obj in (snapshot.get("objects") or {}).items():
        if obj.get("capability") != "light":
            continue
        target = obj.get("position_m")
        if not isinstance(target, list) or len(target) != 2:
            continue
        distance = math.hypot(float(position[0]) - float(target[0]),
                              float(position[1]) - float(target[1]))
        if distance > 1.2:
            continue
        owner = obj.get("owner")
        persona = str(getattr(engine, "persona", ""))
        if owner and str(owner).casefold() != persona.casefold():
            continue
        power = float(obj.get("power", 0.0))
        verb = "light_off" if power > 0.0 else "light_on"
        state = "on" if power > 0.0 else "off"
        return (
            f"{obj.get('name', oid)} is within reach and is {state}. "
            f"If you choose to pull its switch now: "
            f"<act>{verb} {oid}</act>")
    return ""


def execute_autonomous_room_actions(engine, thought: str) -> dict:
    """Execute only exact, resident-emitted, reversible light actions."""
    chosen = [action for action in parse_actions(thought)
              if action.get("verb") in AUTONOMOUS_ROOM_ACTIONS][:2]
    if not chosen:
        return {"acted": [], "remaining": thought}
    acted = []
    for action in chosen:
        result = engine._execute_volitional_action(action, channel="dmn")
        acted.append({"act": action, "result": result})
    return {
        "acted": acted,
        "remaining": strip_action_verbs(
            thought, AUTONOMOUS_ROOM_ACTIONS).strip(),
    }


def offer_altered_expression(engine, field, *, now: float = None):
    """Let measured altered-state movement enter autonomous attention."""
    altered = getattr(engine, "altered_state", None)
    if altered is None or "altered_state" not in getattr(engine, "enabled", set()):
        return None
    soma = getattr(engine, "soma", None)
    snapshot_fn = getattr(soma, "snapshot", None) if soma else None
    snapshot = snapshot_fn() if callable(snapshot_fn) else {}
    regions = dict((snapshot or {}).get("regions") or {})
    body_intensity = max((float(dict(value or {}).get("activation", 0.0))
                          for value in regions.values()), default=0.0)
    memory = getattr(engine, "organ", None)
    relationship = max((float(value) for value in
                        dict(getattr(memory, "bonds", {}) or {}).values()),
                       default=0.0)
    pull = altered.expression_pull(
        body_intensity=body_intensity, relationship=relationship)
    if not pull:
        return None
    observed = dict(pull.get("observed_felt") or {})
    observation_text = (
        "; the affect reader most recently described " + str(observed)
        if observed else "; no recent affect description is available")
    return field.offer_cognitive_event(
        "altered_interoception",
        str(pull.get("description") or "Present instruments changed")
        + observation_text,
        features=pull.get("features"), key=pull.get("key"), now=now,
        raw_ref=pull.get("session_id"), ownership="embodied_self_report",
        receipts=[pull.get("session_id")])


def prune_stale_altered_consent(engine, field, *, now: float = None):
    """Withdraw authority candidates superseded by a newer exact request."""
    altered = getattr(engine, "altered_state", None)
    if altered is None:
        return []
    request = dict(getattr(altered, "consent_request", {}) or {})
    current_id = (request.get("request_id")
                  if request.get("state") == "pending" else None)
    return field.queue.discard_where(
        lambda item: (
            item.get("source") == "altered_consent"
            and item.get("key") != f"altered_consent:{current_id}"),
        reason="superseded_consent_request", now=now)


def offer_altered_consent(engine, field, *, now: float = None):
    """Offer an operator request to the persona without granting authority."""
    altered = getattr(engine, "altered_state", None)
    if altered is None or "altered_state" not in getattr(engine, "enabled", set()):
        return None
    prune_stale_altered_consent(engine, field, now=now)
    pull = altered.consent_pull()
    if not pull:
        return None
    return field.offer_cognitive_event(
        "altered_consent", pull["description"],
        features=pull.get("features"), key=pull.get("key"), now=now,
        raw_ref=pull.get("request_id"), ownership="persona_consent",
        receipts=[pull.get("request_id")])


def _responsiveness_context(engine) -> dict:
    """Content-free live instrument shape for the read-only observer."""
    from shell.autonomy_circulation import readiness_from_engine

    osc = getattr(engine, "osc", None)
    soma = getattr(engine, "soma", None)
    play = getattr(engine, "play_drive", None)
    field = getattr(engine, "idle_metabolism", None)

    readiness = readiness_from_engine(engine, field=field)
    bands = dict(getattr(osc, "bands", {}) or {}) if osc else {}
    coherence_fn = getattr(osc, "coherence", None) if osc else None
    coherence = coherence_fn() if callable(coherence_fn) else 1.0

    soma_fn = getattr(soma, "snapshot", None) if soma else None
    soma_snapshot = soma_fn() if callable(soma_fn) else {}
    activations = [
        float(dict(value or {}).get("activation", 0.0))
        for value in dict((soma_snapshot or {}).get("regions") or {}).values()]

    affect_values = []
    for value in dict(getattr(engine, "cocktail", {}) or {}).values():
        try:
            affect_values.append(max(0.0, min(1.0, float(value))))
        except (TypeError, ValueError):
            continue

    play_fn = getattr(play, "snapshot", None) if play else None
    play_snapshot = play_fn() if callable(play_fn) else {}
    return {
        "schema": 1,
        "readiness": {
            "readiness": float(readiness.get("readiness", 0.0)),
            "capacity": float(readiness.get("capacity", 0.0)),
            "support": float(readiness.get("support", 0.0)),
            "hard_blocked": bool(readiness.get("hard_blocked", False)),
        },
        "oscillator": {
            "bands": {str(key): float(value)
                      for key, value in bands.items()},
            "coherence": float(coherence),
        },
        "soma": {
            "active_count": len(activations),
            "activation_mean": (
                sum(activations) / len(activations) if activations else 0.0),
            "activation_max": max(activations, default=0.0),
        },
        "affect": {
            "active_count": sum(1 for value in affect_values if value > 0.0),
            "intensity_mean": (
                sum(affect_values) / len(affect_values)
                if affect_values else 0.0),
            "intensity_max": max(affect_values, default=0.0),
        },
        "play_drive": {
            "available": bool(play),
            "vector": {
                str(key): float(value) for key, value in
                dict((play_snapshot or {}).get("vector") or {}).items()},
            "active_arc_count": len(
                list((play_snapshot or {}).get("active_arcs") or [])),
        },
        "field": {
            "pressure": float(getattr(
                getattr(field, "pressure", None), "pressure", 0.0)),
        },
    }


def attach_idle_metabolism(engine, metabolism: dict):
    """Attach the one persisted field before HTTP or background loops race."""
    from core.dmn import IdleMetabolism
    current = getattr(engine, "idle_metabolism", None)
    if current is not None:
        if getattr(engine, "salience_observer", None) is None:
            path = os.path.join(engine.pdir, "history", "salience.jsonl")
            engine.salience_observer = SalienceObserver(
                engine.persona, path,
                context_provider=lambda: _responsiveness_context(engine))
            current.set_observer(engine.salience_observer)
        if prune_stale_altered_consent(engine, current):
            current.save()
        return current
    state_path = os.path.join(engine.pdir, "body", "dmn_state.json")
    engine.idle_metabolism = IdleMetabolism.load(metabolism["params"], state_path)
    path = os.path.join(engine.pdir, "history", "salience.jsonl")
    engine.salience_observer = SalienceObserver(
        engine.persona, path,
        context_provider=lambda: _responsiveness_context(engine))
    engine.idle_metabolism.set_observer(engine.salience_observer)
    if prune_stale_altered_consent(engine, engine.idle_metabolism):
        engine.idle_metabolism.save()
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
             agency_runtime=None, intention_loom_runtime=None,
             writing_desk_runtime=None,
             archive_reader_runtime=None, document_reader_runtime=None,
             research_desk_runtime=None,
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
    from core.sovereign_interior import has_lease
    from shell.autonomy_circulation import (
        circulate_experienced_event, readiness_from_engine)
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

    def local_volitional_opening(now):
        """Return a zero-paid-fallback opening earned by a self-offered pull.

        This is deliberately narrower than ordinary idle attention: exact
        candidate keys created by a persona's conversational motor can enter
        through a zero-paid route, while altered-state embodied self-report
        can enter because safety speech cannot depend on a cost cap. Human
        admission and generic wandering cannot use this seam.
        """
        admitted = {}
        runtimes = (
            ("intention_loom", intention_loom_runtime),
            ("writing_desk", writing_desk_runtime),
            ("document_reader", document_reader_runtime),
            ("research_desk", research_desk_runtime),
            ("atelier", atelier_runtime),
        )

        def self_offered(candidate, organ, runtime):
            if has_lease(candidate):
                return True
            if organ == "document_reader":
                return runtime.foreground_directed(candidate)
            if organ == "research_desk" and runtime.foreground_directed(
                    candidate):
                return True
            if (candidate.get("ownership") ==
                    "persona_chosen_conversation" or
                    candidate.get("origin") ==
                    "persona_chosen_conversation"):
                return True
            # Candidates saved before ownership became part of the durable
            # field can recover it only from their authoritative organ record.
            # No wording or model inference is used to manufacture provenance.
            try:
                if organ == "intention_loom" and candidate.get("cue_id"):
                    record = runtime.loom.cue(candidate["cue_id"])
                    return record.get("ownership") == \
                        "persona_chosen_conversation"
                if organ == "writing_desk" and candidate.get("seed_id"):
                    record = runtime.desk.seed(candidate["seed_id"])
                    return record.get("ownership") == \
                        "persona_chosen_conversation"
                if organ == "research_desk" and candidate.get("interest_id"):
                    record = runtime.desk.interest(candidate["interest_id"])
                    return record.get("origin") == \
                        "persona_chosen_conversation"
                if organ == "atelier" and candidate.get("seed_id"):
                    record = runtime.atelier.seed(candidate["seed_id"])
                    return record.get("ownership") == \
                        "persona_chosen_conversation"
            except (KeyError, TypeError, ValueError):
                return False
            return False

        for candidate in field.queue.items(now):
            if (candidate.get("source") in {
                    "altered_interoception", "altered_consent"}
                    and candidate.get("ownership") in {
                        "embodied_self_report", "persona_consent"}):
                score, score_meta = field.attention_score(
                    candidate, now=now)
                admitted[str(candidate.get("key"))] = {
                    "score": max(0.0, min(1.0, float(score))),
                    "organ": "altered_state",
                    "selection": score_meta,
                }
                continue
            for organ, runtime in runtimes:
                if runtime is None or organ not in engine.enabled \
                        or not runtime.eligible(candidate):
                    continue
                if not self_offered(candidate, organ, runtime):
                    continue
                capability = runtime.capability()
                if (not capability.get("usable")
                        or capability.get("locality") != "local"
                        or int(capability.get("paid_fallbacks") or 0) != 0):
                    continue
                state = runtime.readiness(field)
                score, score_meta = runtime.selection_score(
                    field, candidate, now=now, readiness=state)
                admitted[str(candidate.get("key"))] = {
                    "score": max(0.0, min(1.0, float(score))),
                    "organ": organ,
                    "selection": score_meta,
                }
                break
        # The paid exception exists for embodied communication, not as extra
        # workbench throughput.  If that voice is present, it alone owns this
        # capped opening; ordinary fires still preserve full competition.
        embodied = {
            key: value for key, value in admitted.items()
            if value.get("organ") == "altered_state"}
        if embodied:
            admitted = embodied
        leased = {
            key: value for key, value in admitted.items()
            if has_lease(next((
                candidate for candidate in field.queue.items(now)
                if str(candidate.get("key")) == key), {}))
        }
        if leased:
            admitted = leased
        if not admitted:
            return False, None, {}
        pull = max(value["score"] for value in admitted.values())
        if leased:
            opened, opening = field.pressure.open_for_direct_volition(
                pull, now=now)
            opening = {**opening, "sovereign_interior": True}
        else:
            opened, opening = field.pressure.try_local_volitional_opening(
                pull, now=now)
        return opened, frozenset(admitted), {
            **opening,
            "candidate_keys": sorted(admitted),
            "candidate_organs": sorted({
                value["organ"] for value in admitted.values()}),
        }

    while not stop.wait(params["tick_s"]):
        now = None
        try:
            capability_field = any(
                runtime is not None and organ in engine.enabled
                for organ, runtime in (
                    ("intention_loom", intention_loom_runtime),
                    ("writing_desk", writing_desk_runtime),
                    ("archive_reader", archive_reader_runtime),
                    ("document_reader", document_reader_runtime),
                     ("research_desk", research_desk_runtime),
                     ("atelier", atelier_runtime)))
            generic_field = bool(metabolism["enabled"])
            embodied_field = (
                "altered_state" in engine.enabled
                and any(candidate.get("source") in {
                    "altered_interoception", "altered_consent"}
                    and candidate.get("ownership") in {
                        "embodied_self_report", "persona_consent"}
                        for candidate in field.queue.items()))
            if "dmn" not in engine.enabled or not (
                    generic_field or capability_field or embodied_field):
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
                if intention_loom_runtime is not None:
                    returned = intention_loom_runtime.drain_effects(
                        field, now=now)
                    if returned:
                        receipt(
                            "intention_loom_reentry",
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
                if document_reader_runtime is not None:
                    returned = document_reader_runtime.drain_effects(
                        field, now=now)
                    if returned:
                        receipt(
                            "document_reader_reentry",
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
                # Interoception joins the same competition before the
                # substrate verdict. expression_pull only emits on measured
                # vector movement, so observation granularity is not policy.
                if generic_field:
                    try:
                        consent_candidate = offer_altered_consent(
                            engine, field, now=now)
                        if consent_candidate:
                            receipt(
                                "altered_consent_offered",
                                key=consent_candidate.get("key"),
                                salience=round(float(
                                    consent_candidate.get("salience", 0.0)), 6),
                                features=consent_candidate.get("features"))
                    except Exception as altered_consent_error:
                        receipt(
                            "altered_consent_offer_error",
                            error_type=type(altered_consent_error).__name__)
                    try:
                        altered_candidate = offer_altered_expression(
                            engine, field, now=now)
                        if altered_candidate:
                            receipt(
                                "altered_expression_offered",
                                key=altered_candidate.get("key"),
                                salience=round(float(
                                    altered_candidate.get("salience", 0.0)), 6),
                                features=altered_candidate.get("features"))
                    except Exception as altered_offer_error:
                        receipt(
                            "altered_expression_offer_error",
                            error_type=type(altered_offer_error).__name__)
                if (dp.active_node and dp.fired_at >= boot_turn_ts
                        and engine.last_turn_ts > dp.fired_at):
                    receipt("catch", node=dp.active_node[:80],
                            text=render_catch(dp.active_node))
                    dp.active_node = None
                    field.save(now=now)
                direct_consent = []
                for candidate in field.queue.items(now):
                    if (candidate.get("source") == "altered_consent"
                            and candidate.get("ownership") ==
                            "persona_consent"):
                        score, score_meta = field.attention_score(
                            candidate, now=now)
                        direct_consent.append((candidate, score, score_meta))
                local_volitional_only = None
                if direct_consent:
                    pull = max(float(row[1]) for row in direct_consent)
                    opened, opening = dp.open_for_direct_volition(
                        pull, now=now)
                    verdict = "fired" if opened else "below_threshold"
                    local_volitional_only = frozenset(
                        str(row[0].get("key")) for row in direct_consent)
                    ev = {**opening, "opening": "direct_volitional_request",
                          "candidate_keys": sorted(local_volitional_only)}
                    receipt("direct_volitional_opening", **ev)
                else:
                    has_sovereign = any(
                        has_lease(candidate)
                        for candidate in field.queue.items(now))
                    if has_sovereign:
                        opened, candidate_keys, opening = \
                            local_volitional_opening(now)
                    else:
                        opened, candidate_keys, opening = False, None, {}
                    if has_sovereign and opened:
                        verdict = "fired"
                        local_volitional_only = candidate_keys
                        ev = {**opening, "opening": "local_volitional"}
                        receipt("local_volitional_opening", **opening)
                    else:
                        verdict, ev = dp.tick(bands, coh, idle_s, now=now)
                if verdict == "capped" and local_volitional_only is None:
                    opened, candidate_keys, opening = \
                        local_volitional_opening(now)
                    if opened:
                        verdict = "fired"
                        local_volitional_only = candidate_keys
                        ev = {**(ev or {}), **opening,
                              "opening": "local_volitional"}
                        receipt("local_volitional_opening", **opening)
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
                if intention_loom_runtime is not None:
                    try:
                        intention_loom_runtime.refresh_pending(field, now=now)
                    except Exception as loom_error:
                        receipt("intention_loom_recurrence_error",
                                error=str(loom_error)[:200])
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
                if document_reader_runtime is not None:
                    try:
                        document_reader_runtime.refresh_pending(field, now=now)
                    except Exception as document_error:
                        receipt("document_reader_recurrence_error",
                                error=str(document_error)[:200])
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
                intention_state = (
                    intention_loom_runtime.readiness(field)
                    if intention_loom_runtime is not None else None)
                desk_state = (writing_desk_runtime.readiness(field)
                              if writing_desk_runtime is not None else None)
                archive_state = (archive_reader_runtime.readiness(field)
                                 if archive_reader_runtime is not None else None)
                document_state = (document_reader_runtime.readiness(field)
                                  if document_reader_runtime is not None else None)
                research_state = (research_desk_runtime.readiness(field)
                                  if research_desk_runtime is not None else None)
                atelier_state = (atelier_runtime.readiness(field)
                                 if atelier_runtime is not None else None)

                def capability_owned(candidate):
                    if (candidate.get("source") in {
                            "altered_interoception", "altered_consent"}
                            and candidate.get("ownership") in {
                                "embodied_self_report", "persona_consent"}):
                        return True
                    return bool(
                        (intention_loom_runtime is not None
                         and intention_loom_runtime.eligible(candidate))
                        or (writing_desk_runtime is not None
                         and writing_desk_runtime.eligible(candidate))
                        or (archive_reader_runtime is not None
                            and archive_reader_runtime.eligible(candidate))
                        or (document_reader_runtime is not None
                            and document_reader_runtime.eligible(candidate))
                        or (research_desk_runtime is not None
                            and research_desk_runtime.eligible(candidate))
                        or (atelier_runtime is not None
                            and atelier_runtime.eligible(candidate)))

                def scorer(candidate):
                    if (local_volitional_only is not None
                            and str(candidate.get("key")) not in
                            local_volitional_only):
                        return -1.0, {
                            "local_volitional_opening": True,
                            "action_eligible": False,
                        }
                    if intention_loom_runtime is not None \
                            and intention_loom_runtime.eligible(candidate):
                        return intention_loom_runtime.selection_score(
                            field, candidate, now=now,
                            readiness=intention_state)
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
                    if document_reader_runtime is not None \
                            and document_reader_runtime.eligible(candidate):
                        return document_reader_runtime.selection_score(
                            field, candidate, now=now,
                            readiness=document_state)
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
                    if candidate.get("source") in {
                            "altered_interoception", "altered_consent"}:
                        return field.attention_score(candidate, now=now)
                    if generic_field and agency_runtime is not None:
                        return agency_runtime.selection_score(
                            field, candidate, now=now,
                            readiness=agency_state)
                    if not generic_field:
                        return -1.0, {"capability_field_only": True,
                                      "action_eligible": False}
                    return field.attention_score(candidate, now=now)
                interference = getattr(engine, "interference_field", None)
                if interference is not None:
                    try:
                        probe_candidates = []
                        for candidate in field.queue.items(now):
                            projected = scorer(candidate)
                            base_score = (projected[0]
                                          if isinstance(projected, tuple)
                                          else projected)
                            if float(base_score) < 0.0:
                                continue
                            probe_candidates.append({
                                "key": str(candidate.get("key") or ""),
                                "born": float(candidate.get("born", now)),
                                "last_offered": float(candidate.get(
                                    "last_offered",
                                    candidate.get("born", now))),
                                "base_score": float(base_score),
                            })
                        probe = interference.attention_probe(
                            probe_candidates, now=now)
                        if probe.get("recorded"):
                            receipt(
                                "interference_attention_probe",
                                mode=probe.get("mode"),
                                candidate_count=probe.get("candidate_count"),
                                event_window=probe.get("event_window"),
                                field_presence=probe.get("field_presence"),
                                genuine_changed_winner=probe.get(
                                    "genuine_changed_winner"),
                                informative=probe.get("informative"),
                                temporal_profile_span=probe.get(
                                    "temporal_profile_span"),
                                competitive_ratio=probe.get(
                                    "competitive_ratio"),
                                genuine_margin=probe.get("genuine_margin"),
                                interval_genuine_winner_share=(
                                    probe.get("interval_shuffle") or {}).get(
                                        "genuine_winner_share"),
                                profile_genuine_winner_share=(
                                    probe.get("profile_permutation") or {}).get(
                                        "genuine_winner_share"),
                                downstream_channels_touched=[])
                    except Exception as interference_error:
                        receipt(
                            "interference_attention_probe_error",
                            error_type=type(interference_error).__name__)
                if not generic_field and not any(
                        capability_owned(value) for value in field.queue.items(now)):
                    dp.refund()
                    receipt("no_capability_candidate", **ev)
                    field.save(now=now)
                    continue
                play_counterfactual = None
                play_drive = getattr(engine, "play_drive", None)
                if play_drive is not None:
                    try:
                        shadow_candidates = []
                        for candidate in field.queue.items(now):
                            projected = scorer(candidate)
                            base_score = (
                                projected[0] if isinstance(projected, tuple)
                                else projected)
                            if float(base_score) < 0.0:
                                continue
                            shadow_candidates.append({
                                "key": str(candidate.get("key") or ""),
                                "base_score": float(base_score),
                                "play_affinity": float(
                                    candidate.get("play_affinity") or 0.0),
                            })
                        play_counterfactual = \
                            play_drive.counterfactual_attention(
                                shadow_candidates, now=now)
                    except Exception as play_shadow_error:
                        receipt(
                            "play_attention_counterfactual_error",
                            error_type=type(play_shadow_error).__name__,
                            downstream_channels_touched=[])
                item = field.discharge(now, scorer=scorer)
                if not item:
                    dp.refund()
                    receipt("no_candidate", **ev)
                    field.save(now=now)
                    continue
                if (play_counterfactual is not None
                        and getattr(engine, "salience_observer", None)
                        is not None):
                    engine.salience_observer.play_counterfactual(
                        play_counterfactual, item.get("key"), now)
                sensory_origin = item.get("kind") == "sensory"
                event_origin = item.get("kind") in {"sensory", "cognitive"}
                receipt("candidate_selected", key=item.get("key"),
                        candidate_kind=item.get("kind"),
                        source=item.get("source"), recall_hits=len(hits),
                        agency_readiness=(agency_state or {}).get("readiness"),
                        agency_capacity=(agency_state or {}).get("capacity"),
                        agency_support=(agency_state or {}).get("support"),
                        agency_blocked=(agency_state or {}).get("hard_blocked"),
                        intention_loom_readiness=(intention_state or {}).get(
                            "readiness"),
                        intention_loom_blocked=(intention_state or {}).get(
                            "hard_blocked"),
                        writing_desk_readiness=(desk_state or {}).get(
                            "readiness"),
                        writing_desk_blocked=(desk_state or {}).get(
                            "hard_blocked"),
                        archive_reader_readiness=(archive_state or {}).get(
                            "readiness"),
                        archive_reader_blocked=(archive_state or {}).get(
                            "hard_blocked"),
                        document_reader_readiness=(document_state or {}).get(
                            "readiness"),
                        document_reader_blocked=(document_state or {}).get(
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
                if intention_loom_runtime is not None \
                        and intention_loom_runtime.eligible(item):
                    loom_run = intention_loom_runtime.start_candidate(item)
                    if loom_run.get("started"):
                        receipt(
                            "intention_loom_handoff", key=item.get("key"),
                            proposal_id=loom_run.get("proposal_id"),
                            run_id=loom_run.get("run_id"))
                        field.save(now=now)
                        continue
                    if loom_run.get("reason") == "stale_candidate":
                        dp.refund()
                        receipt("intention_loom_stale_candidate",
                                key=item.get("key"))
                        field.save(now=now)
                        continue
                    dp.refund()
                    field.queue.put(
                        item, item.get("salience", 0.05), now=now,
                        offer_meta={
                            "operation": "requeued",
                            "reason": loom_run.get("reason") or
                                      "intention_loom_unavailable"})
                    receipt(
                        "intention_loom_requeued", key=item.get("key"),
                        reason=str(loom_run.get("reason") or "unknown")[:200])
                    field.save(now=now)
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
                    if desk_run.get("reason") == "stale_candidate":
                        dp.refund()
                        receipt("writing_desk_stale_candidate",
                                key=item.get("key"))
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
                if document_reader_runtime is not None \
                        and document_reader_runtime.eligible(item):
                    document_run = document_reader_runtime.start_candidate(item)
                    if document_run.get("started"):
                        receipt(
                            "document_reader_handoff", key=item.get("key"),
                            proposal_id=document_run.get("proposal_id"),
                            run_id=document_run.get("run_id"))
                        field.save(now=now)
                        continue
                    dp.refund()
                    field.queue.put(
                        item, item.get("salience", 0.05), now=now,
                        offer_meta={
                            "operation": "requeued",
                            "reason": document_run.get("reason") or
                                      "document_reader_unavailable"})
                    receipt(
                        "document_reader_requeued", key=item.get("key"),
                        reason=str(document_run.get("reason") or
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
                    if research_run.get("reason") == "stale_candidate":
                        dp.refund()
                        receipt("research_desk_stale_candidate",
                                key=item.get("key"))
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
                    if atelier_run.get("reason") == "stale_candidate":
                        dp.refund()
                        receipt("atelier_stale_candidate",
                                key=item.get("key"))
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
                if (not generic_field and item.get("source") not in {
                        "altered_interoception", "altered_consent"}):
                    dp.refund()
                    field.queue.put(
                        item, item.get("salience", 0.05), now=now,
                        offer_meta={"operation": "requeued",
                                    "reason": "capability_field_only"})
                    receipt("capability_candidate_guard", key=item.get("key"))
                    field.save(now=now)
                    continue
                if item.get("source") not in {
                        "altered_interoception", "altered_consent"} \
                        and agency_runtime is not None \
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
                    contact_destinations = self_initiated_contact_destinations(
                        engine)
                    contact_available = contact_affordance_available(
                        engine, event_origin=event_origin, seed=seed, item=item)
                    continuity_origin = owned_continuity_origin(item)
                    autonomy = readiness_from_engine(engine, field)

                    def observed_range(value, width=.05):
                        value = max(0.0, min(1.0, float(value or 0.0)))
                        return [
                            round(max(0.0, value - width), 2),
                            round(min(1.0, value + width), 2),
                        ]

                    satiety_key = str(
                        item.get("satiety_key")
                        or f"{item.get('kind', '')}:{item.get('source', '')}")
                    deliberation_vector = {
                        "source": str(item.get("source") or
                                      item.get("kind") or "unknown"),
                        "recurrence_range": observed_range(
                            field.preoccupation.warmth(
                                str(item.get("key") or ""), now)),
                        "salience_range": observed_range(
                            item.get("salience")),
                        "readiness_range": observed_range(
                            autonomy.get("readiness")),
                        "capacity_range": observed_range(
                            autonomy.get("capacity")),
                        "body_intensity_range": observed_range(
                            item.get("body_intensity")),
                        "affect_change_range": observed_range(
                            item.get("affect_change")),
                        "unresolved_range": observed_range(
                            item.get("unresolved")),
                        "source_satiety_range": observed_range(
                            field.satiety.warmth(satiety_key, now)),
                        "room_delivery_reachable":
                            "household_room" in contact_destinations,
                        "private_delivery_reachable":
                            "private_chat" in contact_destinations,
                        "reachable_contact_destinations":
                            list(contact_destinations),
                        "transport": "local resident-owned conversation paths",
                    }
                    receipt("consultation", key=item.get("key"),
                            candidate_kind=item.get("kind"),
                            source=item.get("source"), model=idle_model,
                            contact_affordance_available=contact_available,
                            owned_continuity_origin=continuity_origin,
                            drift_type=dt, **ev)
                    cycle_id = new_cycle_id()
                    model_receipts = []
                    thought = generate_idle_thought(
                        engine, idle_model, item, dt,
                        sensory_source=(item.get("source")
                                        if event_origin else None),
                        self_initiated_speech_available=(
                            "household_room" in contact_destinations),
                        self_initiated_private_available=(
                            "private_chat" in contact_destinations),
                        deliberation_vector=deliberation_vector,
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
                altered_consent = item.get("source") == "altered_consent"
                if altered_consent:
                    thought, consent_actions = \
                        engine.apply_persona_altered_actions(thought)
                    if consent_actions:
                        field.satiate(item, now=now)
                        observer.discharge(
                            item, "consent_decision", str(consent_actions),
                            {"candidate_key": item.get("key"),
                             "model": idle_model, "drift_type": dt,
                             **generation_meta}, now)
                        receipt(
                            "altered_consent_decision",
                            actions=consent_actions,
                            candidate_key=item.get("key"),
                            model=idle_model, **generation_meta, **ev)
                        field.save(now=now)
                        continue
                    # No authority marker means no grant.  The exact request
                    # remains pending and can be deliberately re-offered.
                    field.satiate(item, now=now)
                    observer.discharge(
                        item, "consent_undecided", thought,
                        {"candidate_key": item.get("key"),
                         "model": idle_model, "drift_type": dt,
                         **generation_meta}, now)
                    receipt("altered_consent_undecided", model=idle_model,
                            candidate_key=item.get("key"),
                            **generation_meta, **ev)
                    field.save(now=now)
                    continue
                autonomous_room = execute_autonomous_room_actions(
                    engine, thought)
                if autonomous_room["acted"]:
                    acted = autonomous_room["acted"]
                    action_facts = "; ".join(
                        f"{entry['act']['verb']} "
                        f"{entry['act']['target']}: "
                        f"{'ok' if entry['result'].get('ok') else 'refused'}"
                        for entry in acted)
                    felt = circulate_experienced_event(
                        engine,
                        "A self-chosen autonomous room action reached the "
                        "world: " + action_facts,
                        cycle_id=cycle_id)
                    context_builder = getattr(
                        engine, "memory_context_snapshot", None)
                    mem = engine.organ.encode(
                        "Autonomous room action: " + action_facts,
                        cocktail=engine.cocktail, entities=[],
                        mem_type="turn", origin="lived",
                        fields={
                            "channel": "dmn",
                            "reply_full": autonomous_room["remaining"],
                            "autonomous": True,
                            "autonomous_source": "room_action",
                            "room_actions": acted,
                            "conversation_id": cycle_id,
                            "candidate_key": item.get("key"),
                            "gist_eligible": True,
                        },
                        body=(engine.soma.snapshot()
                              if getattr(engine, "soma", None) else None),
                        context_at_encoding=(
                            context_builder(now=now)
                            if callable(context_builder) else None))
                    engine.organ.save()
                    field.satiate(item, now=now)
                    observer.discharge(
                        item, "autonomous_room_action", action_facts,
                        {"candidate_key": item.get("key"),
                         "model": idle_model, "drift_type": dt,
                         "actions": acted, **generation_meta}, now)
                    receipt(
                        "autonomous_room_action",
                        actions=acted, mem_id=(mem or {}).get("id"),
                        felt=sorted(felt.get("felt") or {}),
                        candidate_key=item.get("key"), **ev)
                    field.save(now=now)
                    continue
                chosen_contact = parse_self_initiated_contact(thought)
                chosen_speech = (
                    chosen_contact["text"] if chosen_contact is not None
                    else None)
                if contact_available:
                    quiet_choice = (
                        not thought or thought.strip().casefold() == "[quiet]")
                    contact_outcome = (
                        "speech" if chosen_speech is not None
                        else "quiet" if quiet_choice
                        else "private")
                    receipt(
                        "contact_deliberation",
                        candidate_key=item.get("key"),
                        source=item.get("source"),
                        owned_continuity_origin=owned_continuity_origin(item),
                        affordance_available=True,
                        selected=chosen_speech is not None,
                        outcome=contact_outcome,
                        destination=(
                            chosen_contact["destination"]
                            if chosen_contact is not None else None),
                        vector={
                            "recurrence": round(
                                field.preoccupation.warmth(
                                    str(item.get("key") or ""), now), 6),
                            "relevance": round(
                                float(item.get("salience") or 0.0), 6),
                            "readiness": round(
                                float(readiness_from_engine(
                                    engine, field).get("readiness") or 0.0), 6),
                            "affect_change": round(
                                float(item.get("affect_change") or 0.0), 6),
                            "body_intensity": round(
                                float(item.get("body_intensity") or 0.0), 6),
                            "unresolved": round(
                                float(item.get("unresolved") or 0.0), 6),
                        },
                        model=idle_model,
                        **generation_meta)
                if chosen_speech is not None:
                    contact = getattr(engine, "self_initiated_contact", None)
                    autonomy = readiness_from_engine(engine, field)
                    bonds = dict(getattr(engine.organ, "bonds", {}) or {})
                    relationship = float(
                        bonds.get(getattr(engine, "local_human", ""), 0.0))
                    destination = chosen_contact["destination"]
                    audience = (
                        "household_room" if destination == "household_room"
                        else str(getattr(engine, "local_human", "") or ""))
                    offered = contact.offer(
                        source=(str(item.get("source"))
                                if owned_continuity_origin(item)
                                else "dmn_recurrence"),
                        source_ref=str((seed or {}).get("id") or item.get("key")),
                        audience=audience,
                        text=chosen_speech,
                        recurrence=field.preoccupation.warmth(
                            str(item.get("key") or ""), now),
                        relevance=float(item.get("salience") or 0.0),
                        readiness=autonomy["readiness"],
                        relationship=relationship,
                        interruption_cost=1.0 - autonomy["capacity"])
                    # The signals above describe how the private impulse
                    # arrived. Once the resident has chosen exact words, they do not
                    # become a second permission vote over ordinary speech.
                    private_delivery = {}
                    if destination == "private_chat":
                        delivery = contact.choose_and_deliver(
                            offered["impulse_id"], gesture="speak",
                            deliver=lambda envelope: private_delivery.update(
                                deliver_autonomous_private_chat(
                                    engine, envelope["text"],
                                    conversation_id=cycle_id,
                                    candidate_key=item.get("key"),
                                    generation=generation_meta,
                                    now=now)) or private_delivery)
                        if delivery["ok"]:
                            thought = chosen_speech
                            felt = circulate_experienced_event(
                                engine,
                                "A self-initiated private conversation was "
                                "chosen and sent to the solo cockpit: " + thought,
                                cycle_id=cycle_id)
                            motif_satiety = satiate_expressed_motif(
                                field, item, thought, now=now)
                            field.satiate(item, now=now)
                            engine.last_turn_ts = now
                            dp.active_node = node
                            gist_folded = bool(
                                engine.gist and
                                engine.gist.update_idle(engine.organ.memories))
                            observer.discharge(
                                item, "self_initiated_private_speech", thought,
                                {"candidate_key": item.get("key"),
                                 "model": idle_model,
                                 "delivery_ref": delivery["delivery_ref"],
                                 "motif_ref": motif_satiety["motif_ref"],
                                 "motif_satiety": motif_satiety["new"],
                                 **generation_meta}, now)
                            receipt(
                                "self_initiated_private_speech",
                                delivery_ref=delivery["delivery_ref"],
                                text=thought,
                                mem_id=private_delivery.get("memory_id"),
                                felt=sorted(felt.get("felt") or {}),
                                candidate_key=item.get("key"),
                                motif_satiety=motif_satiety,
                                gist_folded=gist_folded, **ev)
                            field.save(now=now)
                            continue
                    elif engine.room is not None:
                        delivery = contact.choose_and_deliver(
                            offered["impulse_id"], gesture="speak",
                             deliver=lambda envelope: {
                                 "ok": True,
                                 "delivery_channel": "ordinary_room_speech",
                                 "delivery_ref": str(engine.room.say(
                                    envelope["text"],
                                    conversation_id=cycle_id).get(
                                        "seq") or cycle_id),
                            })
                        if delivery["ok"]:
                            thought = chosen_speech
                            felt = circulate_experienced_event(
                                engine,
                                "A self-initiated conversation was chosen "
                                "and spoken: " + thought,
                                cycle_id=cycle_id)
                            context_builder = getattr(
                                engine, "memory_context_snapshot", None)
                            mem = engine.organ.encode(
                                thought, cocktail=engine.cocktail, entities=[],
                                mem_type="turn", origin="lived",
                                fields={
                                    "channel": "room",
                                    "reply_full": thought,
                                    "autonomous": True,
                                    "autonomous_source":
                                        "self_initiated_contact",
                                    "conversation_id": cycle_id,
                                    "audience": "household_room",
                                    "gist_eligible": True,
                                    "candidate_key": item.get("key"),
                                },
                                body=(engine.soma.snapshot()
                                      if getattr(engine, "soma", None)
                                      else None),
                                context_at_encoding=(
                                    context_builder(now=now)
                                    if callable(context_builder) else None))
                            engine.organ.save()
                            motif_satiety = satiate_expressed_motif(
                                field, item, thought, now=now)
                            field.satiate(item, now=now)
                            observer.discharge(
                                item, "self_initiated_speech", thought,
                                {"candidate_key": item.get("key"),
                                 "model": idle_model,
                                 "delivery_ref": delivery["delivery_ref"],
                                 "motif_ref": motif_satiety["motif_ref"],
                                 "motif_satiety": motif_satiety["new"]},
                                now)
                            receipt(
                                "self_initiated_speech",
                                delivery_ref=delivery["delivery_ref"],
                                text=thought, mem_id=(mem or {}).get("id"),
                                felt=sorted(felt.get("felt") or {}),
                                candidate_key=item.get("key"),
                                motif_satiety=motif_satiety, **ev)
                            field.save(now=now)
                            continue
                    # A chosen contact that cannot cross the current standing
                    # boundary remains private; it is never faked as delivered.
                    thought = chosen_speech
                    receipt(
                        "self_initiated_speech_held",
                        candidate_key=item.get("key"),
                        eligible=offered["eligible"],
                        destination=destination,
                        destination_attached=(
                            destination in contact_destinations), **ev)
                altered_expression = (
                    item.get("source") == "altered_interoception")
                if not thought or thought.lower() == "[quiet]":
                    try:
                        felt = circulate_experienced_event(
                            engine,
                            ("An interoceptive opportunity to speak settled "
                             "without language; nothing was expressed or sent."
                             if altered_expression else
                             "An unbidden private pull settled without "
                             "language; nothing was expressed or sent."),
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
                    if altered_expression:
                        altered = getattr(engine, "altered_state", None)
                        if altered is not None:
                            altered.settle_expression("quiet", now=now)
                    field.satiate(item, now=now)
                    observer.discharge(
                        item, "quiet", thought,
                        {"candidate_key": item.get("key"), "model": idle_model,
                         "drift_type": dt, **generation_meta}, now)
                    receipt("quiet", model=idle_model, node=node[:80],
                            **generation_meta, **ev)
                    field.save(now=now)
                    continue
                if altered_expression:
                    felt = None
                    try:
                        felt = circulate_experienced_event(
                            engine,
                            "An autonomous message about the persona's "
                            "present condition was chosen and sent: " + thought,
                            cycle_id=cycle_id)
                        receipt(
                            "dmn_felt_consequence", outcome="expressed",
                            felt=sorted(felt.get("felt") or {}),
                            why=str(felt.get("why") or "")[:240],
                            affect_change=felt.get("affect_change", 0.0))
                    except Exception as consequence_error:
                        receipt(
                            "dmn_consequence_error", outcome="expressed",
                            error_type=type(consequence_error).__name__)
                    context_builder = getattr(
                        engine, "memory_context_snapshot", None)
                    memory_context = (
                        context_builder(now=now)
                        if callable(context_builder) else None)
                    body = (engine.soma.snapshot()
                            if getattr(engine, "soma", None) else None)
                    fields = {
                        "channel": "chat", "speaker": "",
                        "message_full": "", "reply_full": thought,
                        "autonomous": True,
                        "autonomous_source": "altered_interoception",
                        "conversation_id": cycle_id,
                        "audience": "household", "gist_eligible": True,
                        "candidate_key": item.get("key"),
                        "felt_why": str((felt or {}).get("why") or ""),
                    }
                    if generation_meta:
                        fields["generation"] = dict(generation_meta)
                    ledger = getattr(engine, "conversation_ledger", None)
                    if ledger is not None:
                        ledger.admit(
                            conversation_id=cycle_id, channel="chat",
                            speaker=engine.persona, message="",
                            source="altered_interoception")
                    mem = engine.organ.encode(
                        thought, cocktail=engine.cocktail, entities=[],
                        mem_type="turn", origin="lived", fields=fields,
                        body=body, context_at_encoding=memory_context)
                    engine.organ.save()
                    if ledger is not None:
                        ledger.complete(
                            cycle_id, reply=thought,
                            memory_id=(mem or {}).get("id", ""),
                            receipts={"autonomous": True,
                                      "source": "altered_interoception"})
                    altered = getattr(engine, "altered_state", None)
                    if altered is not None:
                        altered.settle_expression("expressed", now=now)
                    field.satiate(item, now=now)
                    engine.last_turn_ts = now
                    dp.active_node = node
                    gist_folded = bool(
                        engine.gist and
                        engine.gist.update_idle(engine.organ.memories))
                    observer.discharge(
                        item, "expressed", thought,
                        {"candidate_key": item.get("key"),
                         "model": idle_model, "drift_type": dt,
                         **generation_meta}, now)
                    receipt(
                        "autonomous_expression", text=thought,
                        candidate_key=item.get("key"),
                        salience=round(item.get("salience", 0.0), 3),
                        mem_id=(mem or {}).get("id"),
                        gist_folded=gist_folded, model=idle_model,
                        **generation_meta, **ev)
                    field.save(now=now)
                    continue
                felt = None
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
                    if owned_continuity_origin(item):
                        memory_fields.update({
                            "continuity_parent_source": item.get("source"),
                            "continuity_parent_key": item.get("key"),
                            "continuity_parent_receipts": list(
                                item.get("receipts") or [])[:8],
                        })
                    if item.get("source") == "intention_effect":
                        memory_fields.update({
                            "intention_id": item.get("intention_id"),
                            "intention_movement": item.get(
                                "intention_movement"),
                            "intention_record_digest": item.get(
                                "intention_record_digest"),
                        })
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
                seed_fields = dict((seed or {}).get("fields") or {})
                recurrent_private_thought = bool(
                    not event_origin and seed
                    and seed_fields.get("channel") == "dmn")
                if intention_loom_runtime is not None \
                        and "intention_loom" in engine.enabled \
                        and recurrent_private_thought:
                    try:
                        bonds = dict(getattr(engine.organ, "bonds", {}) or {})
                        relationship = max(
                            (float(bonds.get(entity, 0.0)) for entity in
                             list(seed.get("entities") or [])), default=0.0)
                        continuity = {
                            "novelty": 0.0,
                            "affect_change": float((felt or {}).get(
                                "affect_change") or 0.0),
                            "body_intensity": float((felt or {}).get(
                                "body_change") or 0.0),
                            "relationship": max(
                                0.0, min(1.0, relationship)),
                            "unresolved": max(0.0, min(1.0,
                                field.preoccupation.warmth(
                                    str(item.get("key") or ""), now))),
                        }
                        loom_cue = intention_loom_runtime.admit_self_cue(
                            field, str(seed.get("content") or ""),
                            memory_id=seed.get("id"), now=now,
                            continuity=continuity)
                        receipt(
                            "intention_recurrent_cue",
                            cue_id=(loom_cue.get("record") or {}).get("cue_id"),
                            candidate_key=(loom_cue.get("candidate") or {}).get(
                                "key"),
                            source_memory_id=seed.get("id"),
                            continuity=continuity)
                    except Exception as loom_cue_error:
                        receipt(
                            "intention_recurrent_cue_error",
                            error_type=type(loom_cue_error).__name__)
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
              intention_loom_runtime=None,
              writing_desk_runtime=None,
              archive_reader_runtime=None,
              document_reader_runtime=None,
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
    app.state.intention_loom_runtime = intention_loom_runtime
    app.state.writing_desk_runtime = writing_desk_runtime
    app.state.archive_reader_runtime = archive_reader_runtime
    app.state.document_reader_runtime = document_reader_runtime
    app.state.research_desk_runtime = research_desk_runtime
    app.state.atelier_runtime = atelier_runtime
    app.state.outward_curiosity = getattr(
        engine, "outward_curiosity", None)
    app.state.self_initiated_contact = getattr(
        engine, "self_initiated_contact", None)
    if (writing_desk_runtime is not None
            and hasattr(engine, "register_volitional_action")):
        def owner_writing_archive(action):
            project_id = str(action.get("target") or "").strip()
            record = writing_desk_runtime.desk.archive_project(
                f"owner-archive-{new_cycle_id()}", project_id)
            return {
                "ok": True, "movement": "archived",
                "project_id": record["project_id"],
                "ownership": "persona_private",
            }

        def owner_writing_restore(action):
            project_id = str(action.get("target") or "").strip()
            record = writing_desk_runtime.desk.restore_project(
                f"owner-restore-{new_cycle_id()}", project_id)
            return {
                "ok": True, "movement": "restored",
                "project_id": record["project_id"],
                "ownership": "persona_private",
            }

        engine.register_volitional_action(
            "writing_archive", owner_writing_archive,
            requires="writing_desk")
        engine.register_volitional_action(
            "writing_restore", owner_writing_restore,
            requires="writing_desk")
    persona_dir = getattr(engine, "pdir", None)
    app.state.private_journal = (
        PrivateJournal(persona_dir, owner=engine.persona)
        if persona_dir else None)
    if (app.state.private_journal is not None
            and hasattr(engine, "register_volitional_action")):
        def queue_journal_index(_action):
            context = app.state.private_journal.index_context()
            engine.queue_private_journal_context(context)
            return {
                "ok": True,
                "queued": "content_free_index",
                "entry_count": app.state.private_journal.verify()["count"],
            }

        def queue_journal_entry(action):
            entry = app.state.private_journal.resolve(
                action.get("target") or "latest")
            engine.queue_private_journal_context(
                "You explicitly opened this private journal entry.\n"
                f"entry_id: {entry['entry_id']}\n"
                f"created_at: {float(entry['created_at'] or 0.0):.6f}\n"
                f"digest: {entry['digest']}\n\n{entry['text']}")
            # Text stays out of action receipts and therefore out of the
            # outward cockpit result/conversation receipt surface.
            return {
                "ok": True,
                "queued": "private_entry",
                "entry_id": entry["entry_id"],
                "chars": entry["chars"],
                "digest": entry["digest"],
            }

        engine.register_volitional_action(
            "journal",
            lambda action: app.state.private_journal.append(
                (action.get("target") or "") + (
                    (" " if action.get("target") else "") + action["text"]
                    if action.get("text") else "")),
            requires="private_journal")
        engine.register_volitional_action(
            "journal_index", queue_journal_index,
            requires="private_journal")
        engine.register_volitional_action(
            "journal_open", queue_journal_entry,
            requires="private_journal")
    if (app.state.outward_curiosity is not None
            and hasattr(engine, "register_volitional_action")):
        def hold_question(action):
            question = (
                (action.get("target") or "") + (
                    (" " if action.get("target") else "")
                    + str(action.get("text") or "")
                    if action.get("text") else "")).strip()
            record = app.state.outward_curiosity.form(
                question, audience=action.get("_speaker") or "",
                conversation_id=action.get("_conversation_id") or "")
            return {
                "ok": True, "question_id": record["question_id"],
                "ownership": "persona_private",
            }

        engine.register_volitional_action(
            "hold_question", hold_question,
            requires="outward_curiosity")
        for curiosity_verb in (
                "curiosity_ask", "curiosity_defer",
                "curiosity_revise", "curiosity_release"):
            engine.register_volitional_action(
                curiosity_verb, app.state.outward_curiosity.handle,
                requires="outward_curiosity")
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
        room_url = (getattr(app.state.engine, "room_url", None) or "").rstrip("/")
        with open(os.path.join(HERE, "cockpit.html"), encoding="utf-8") as f:
            return f.read().replace("/*CONFIG*/", json.dumps({
                "primary_user": current_speaker(),
                "persona_avatar": "/api/avatar",
                "room_url": room_url,
                "body_workshop_url": (
                    f"{room_url}/body-workshop" if room_url else "")}))

    @app.get("/api/3d-lab/status")
    def body_lab_status():
        """Report the configured local workshop seam without changing it."""
        room_url = (getattr(app.state.engine, "room_url", None) or "").rstrip("/")
        result = {
            "configured": bool(room_url),
            "available": False,
            "workshop_url": f"{room_url}/body-workshop" if room_url else "",
            "pilot_target": "starter_persona",
            "authority": "inspection_only",
            "install_enabled": False,
        }
        if not room_url:
            result["reason"] = "this cockpit has no room host configured"
            return result
        parsed = urllib.parse.urlsplit(room_url)
        if (parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}):
            result["reason"] = "the configured room host is not local"
            return result
        try:
            request = urllib.request.Request(
                f"{room_url}/api/avatar-bodies",
                headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read(256 * 1024).decode("utf-8"))
                response_status = response.status
            assignments = payload.get("assignments", [])
            result["available"] = response_status == 200
            result["locked_assignments"] = len(assignments)
            result["reason"] = (
                "local compatibility workshop ready"
                if result["available"] else "room host did not accept the probe")
        except (OSError, ValueError, json.JSONDecodeError,
                urllib.error.URLError) as exc:
            result["reason"] = f"local room host unavailable: {type(exc).__name__}"
        return result

    @app.get("/api/user-personas")
    def user_personas():
        """Chat-safe projection of RP identities owned by the local account."""
        from core.users import get_user
        user = get_user(REPO, app.state.engine.local_user_id)
        personas = list((user or {}).get("user_personas", {}).values())
        return {"user": app.state.engine.local_user_id,
                "display_name": current_speaker(),
                "personas": sorted(personas,
                                   key=lambda item: item["name"].lower())}

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

    @app.get("/api/ui/conversation-area-background")
    def conversation_area_background():
        media = load_conversation_area_background(app.state.engine.pdir)
        if not media:
            return JSONResponse(status_code=404, content={
                "error": "no conversation area background"})
        return FileResponse(media["path"], media_type=media["mime"],
                            headers={"X-Content-Type-Options": "nosniff",
                                     "Cache-Control": "no-cache"})

    @app.post("/api/ui/conversation-area-background")
    def save_cockpit_conversation_area_background(
            req: ConversationBackgroundRequest):
        try:
            media = save_conversation_area_background(
                app.state.engine.pdir, req.data_url)
            return {"ok": True,
                    "url": "/api/ui/conversation-area-background",
                    "revision": media["revision"]}
        except ValueError as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)})

    @app.delete("/api/ui/conversation-area-background")
    def delete_cockpit_conversation_area_background():
        return {"ok": True,
                "removed": delete_conversation_area_background(
                    app.state.engine.pdir)}

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
        """Admit one browser-selected visual episode into perception + DMN.

        The browser owns continuous pixels. Only a threshold-shaped episode
        crosses the process boundary; model work is serialized with turns.
        Episode images are ordered oldest-to-newest.
        """
        requested = list(req.images or [])
        if not requested and req.image is not None:
            requested = [req.image]
        if not requested:
            return JSONResponse(
                status_code=400,
                content={"error": "camera admission needs at least one image"})
        raw = [
            item.model_dump() if hasattr(item, "model_dump") else item.dict()
            for item in requested]
        try:
            images = store_images(app.state.engine.pdir, raw)
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
                   "sequence_count": len(images),
                   "candidate_salience": (round(candidate["salience"], 3)
                                          if candidate else None),
                   # ``image`` remains the endpoint for old readers.
                   "image": public_image_record(images[-1]),
                   "images": [public_image_record(image) for image in images]}
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
                images = store_images(
                    app.state.engine.pdir,
                    [(item.model_dump() if hasattr(item, "model_dump")
                      else item.dict()) for item in req.images])
                grounding_images = store_images(
                    app.state.engine.pdir,
                    [(item.model_dump() if hasattr(item, "model_dump")
                      else item.dict()) for item in req.grounding_images])
                external_demand(
                    "admitted_speech_turn", "human_speech")
                turn_result = app.state.engine.take_turn(
                    transcript.text, max_tokens=app.state.max_tokens,
                    speaker=subject, user_persona=req.user_persona,
                    images=images + grounding_images,
                    grounding_image_count=len(grounding_images))
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
        value = app.state.engine.get_state()
        roster = None
        roster_path = os.path.join(app.state.engine.pdir, "roster.yaml")
        if os.path.isfile(roster_path):
            try:
                import yaml
                with open(roster_path, encoding="utf-8") as handle:
                    roster = yaml.safe_load(handle) or {}
            except (OSError, ValueError, TypeError):
                roster = None
        value["voice_output_config"] = normalize_output_config(
            (roster or {}).get("voice_output"))
        value["voice_output_config"]["household"] = load_voice_defaults(REPO)
        return value

    @app.get("/api/interference-field/calibration")
    def interference_field_calibration():
        organ = getattr(app.state.engine, "interference_field", None)
        if organ is None:
            return {"schema": 1, "available": False,
                    "reason": "interference_field organ is disabled",
                    "mode": "read_only_replay",
                    "downstream_channels_touched": []}
        value = organ.calibration()
        value["available"] = True
        return value

    @app.get("/api/room-field/calibration")
    def room_field_calibration():
        value = app.state.engine.room_field_calibration()
        value["available"] = value.get("mode") != "unavailable"
        value["read_only"] = True
        value["model_calls"] = 0
        value["actions_created"] = 0
        return value

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
        status = library.status()
        runtime = app.state.document_reader_runtime
        if runtime is not None:
            status["autonomous_reader"] = runtime.status()
        return status

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

    @app.get("/api/documents/reports/{report_id}")
    def document_report(report_id: str):
        library = document_library()
        if library is None:
            return JSONResponse(status_code=503, content={
                "error": "document library is not attached"})
        try:
            return library.report(report_id)
        except DocumentError as exc:
            return JSONResponse(status_code=404,
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
                req.name, req.data_url, req.content_type,
                visibility=req.visibility,
                grants=(req.grants or None))
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

    @app.post("/api/documents/{doc_id}/reading-arc")
    def document_reading_arc(doc_id: str, req: DocumentReadingArcRequest):
        library = document_library()
        if library is None:
            return JSONResponse(status_code=503, content={
                "error": "document library is not attached"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; reading arc did not change"})
        try:
            action = str(req.action or "").strip().casefold()
            external_demand(f"document_reading_arc_{action}", "human_document")
            if action == "start":
                arc = library.start_reading_arc(
                    doc_id, start_section=req.start_section, pace=req.pace)
            elif action in {"natural", "foreground"}:
                current = library.reading_arc_status()
                if current.get("doc_id") != doc_id:
                    raise DocumentError(
                        "reading arc belongs to a different document")
                arc = library.set_reading_arc_pace(action)
            else:
                current = library.reading_arc_status()
                if current.get("doc_id") != doc_id:
                    raise DocumentError(
                        "reading arc belongs to a different document")
                arc = library.change_reading_arc(action)
            status = library.status()
            runtime = app.state.document_reader_runtime
            if runtime is not None:
                if action in {"start", "resume", "foreground"} \
                        and arc.get("status") == "active":
                    field = getattr(app.state.engine, "idle_metabolism", None)
                    if field is not None:
                        runtime.refresh_pending(field)
                status["autonomous_reader"] = runtime.status()
            return {"ok": True, "arc": arc, "status": status}
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

    @app.get("/api/private-journal")
    def private_journal_status():
        if app.state.private_journal is None:
            return JSONResponse(status_code=503, content={
                "error": "private journal is not attached"})
        return app.state.private_journal.status()

    @app.get("/api/outward-curiosity")
    def outward_curiosity_status():
        if app.state.outward_curiosity is None:
            return JSONResponse(status_code=503, content={
                "error": "outward curiosity is not attached"})
        return app.state.outward_curiosity.status()

    @app.get("/api/self-initiated-contact")
    def self_initiated_contact_status():
        contact = app.state.self_initiated_contact
        if contact is None:
            return JSONResponse(status_code=503, content={
                "error": "self-initiated contact is not attached"})
        status = contact.status()
        status["runtime_attached"] = True
        status["delivery_channels"] = {
            "household_room": "ordinary_room_speech",
            "local_human_private": "private_chat",
        }
        from core.contact_counterfactual import summarize_contact_deliberations
        status["counterfactual_ownership"] = summarize_contact_deliberations(
            os.path.join(app.state.engine.pdir, "history", "dmn.jsonl"))
        return status

    @app.post("/api/private-journal/entries")
    def private_journal_append(req: PrivateJournalEntryRequest):
        if app.state.private_journal is None:
            return JSONResponse(status_code=503, content={
                "error": "private journal is not attached"})
        try:
            return {
                "ok": True,
                "entry": app.state.private_journal.append(req.text),
                "status": app.state.private_journal.status(),
            }
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})

    @app.get("/api/private-journal/entries/{entry_id}")
    def private_journal_read(entry_id: str):
        if app.state.private_journal is None:
            return JSONResponse(status_code=503, content={
                "error": "private journal is not attached"})
        try:
            return app.state.private_journal.read(entry_id)
        except ValueError as exc:
            return JSONResponse(status_code=404,
                                content={"error": str(exc)[:500]})

    @app.get("/api/intention-loom")
    def intention_loom_status():
        runtime = app.state.intention_loom_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "intention loom is not attached"})
        return runtime.status()

    @app.post("/api/intention-loom/cues")
    def intention_loom_cue(req: IntentionCueRequest):
        runtime = app.state.intention_loom_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "intention loom is not attached"})
        field = getattr(app.state.engine, "idle_metabolism", None)
        if field is None:
            return JSONResponse(status_code=409, content={
                "error": "intention loom needs the shared DMN field"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; possibility was not offered"})
        try:
            external_demand("intention_loom_cue", "human_possibility")
            bonds = dict(getattr(
                getattr(app.state.engine, "organ", None), "bonds", {}) or {})
            relationship = next((float(value) for name, value in bonds.items()
                                 if str(name).casefold() ==
                                 str(speaker).casefold()), 0.0)
            admitted = runtime.admit_cue(
                field, req.label, req.content, ownership="human_offered",
                continuity={
                    "novelty": 1.0,
                    "affect_change": 0.0,
                    "body_intensity": 0.0,
                    "relationship": max(0.0, min(1.0, relationship)),
                    "unresolved": 1.0,
                })
            return {"ok": True, **admitted, "status": runtime.status()}
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/intention-loom/intentions/{intention_id}")
    def intention_loom_intention(intention_id: str):
        runtime = app.state.intention_loom_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "intention loom is not attached"})
        try:
            return runtime.loom.intention(intention_id)
        except ValueError as exc:
            return JSONResponse(status_code=404,
                                content={"error": str(exc)[:500]})

    @app.post("/api/intention-loom/intentions/{intention_id}/resume")
    def intention_loom_resume(intention_id: str):
        runtime = app.state.intention_loom_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "intention loom is not attached"})
        field = getattr(app.state.engine, "idle_metabolism", None)
        if field is None:
            return JSONResponse(status_code=409, content={
                "error": "intention loom needs the shared DMN field"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; return was not offered"})
        try:
            external_demand("intention_loom_return_offer", "human_possibility")
            result = runtime.resume_intention(field, intention_id)
            return {"ok": True, **result, "status": runtime.status()}
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.get("/api/autonomous-works")
    def autonomous_works():
        return _autonomous_works(app)

    @app.get("/api/experiential-continuity")
    def experiential_continuity():
        projector = getattr(app.state.engine, "experiential_continuity", None)
        if projector is None:
            return {
                "schema": 1,
                "persona": app.state.engine.persona,
                "movements": [], "standing": [], "text": "",
                "receipt": {
                    "schema": 1, "status": "unavailable",
                    "movement_count": 0, "standing_count": 0,
                    "rendered": False,
                    "reason": "continuity_projector_not_attached",
                },
            }
        return projector.snapshot()

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

    @app.post("/api/atelier/renderers/comfyui/probe")
    def atelier_comfyui_probe():
        runtime = app.state.atelier_runtime
        if runtime is None or runtime.comfy is None:
            return JSONResponse(status_code=409, content={
                "error": "ComfyUI diffusion is not configured"})
        result = runtime.comfy.probe()
        return {"ok": bool(result.get("reachable") and
                           result.get("checkpoint_ready")),
                "renderer": result, "status": runtime.status()}

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

    @app.post("/api/atelier/open-now")
    def atelier_open_now():
        runtime = app.state.atelier_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "atelier is not attached"})
        field = getattr(app.state.engine, "idle_metabolism", None)
        if field is None:
            return JSONResponse(status_code=409, content={
                "error": "atelier needs the shared DMN field"})
        if runtime.controller.status().get("active"):
            return JSONResponse(status_code=409, content={
                "error": "private attention is occupied"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied"})
        try:
            external_demand(
                "atelier_open_now", "human_requested_atelier_opening")
            result = runtime.request_opening(field)
            if not result.get("started"):
                return JSONResponse(status_code=409, content={
                    "error": result.get("reason") or
                             "atelier opening did not start",
                    "status": runtime.status()})
            return {"ok": True, **result, "status": runtime.status()}
        finally:
            app.state.turn_lock.release()

    @app.get("/api/atelier/artifacts/{artifact_id}")
    def atelier_artifact(artifact_id: str):
        runtime = app.state.atelier_runtime
        if runtime is None:
            return JSONResponse(status_code=404, content={
                "error": "atelier is not attached"})
        try:
            artifact = runtime.atelier.artifact(artifact_id)
            path = runtime.atelier.artifact_path(artifact_id)
        except ValueError as exc:
            return JSONResponse(status_code=404,
                                content={"error": str(exc)[:500]})
        return FileResponse(
            path, media_type=str(artifact.get("media_type") or
                                 "application/octet-stream"),
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
                "artifact_id": artifact_id,
                "medium": str(artifact.get("medium") or "unknown"),
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
            result = runtime.admit_opportunity(field, req.topic)
            return {"ok": True, **result, "status": runtime.status()}
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)[:500]})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/research-desk/foreground")
    def research_desk_foreground(req: ResearchForegroundRequest):
        runtime = app.state.research_desk_runtime
        if runtime is None:
            return JSONResponse(status_code=503, content={
                "error": "research desk is not attached"})
        field = getattr(app.state.engine, "idle_metabolism", None)
        if field is None:
            return JSONResponse(status_code=409, content={
                "error": "research desk needs the shared attention field"})
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "attention is occupied; foreground URL was not admitted"})
        try:
            external_demand(
                "research_foreground_url", "human_foreground_research")
            target = req.target.strip()
            result = (runtime.admit_foreground_url(
                field, target, why=req.why)
                if target.casefold().startswith(("http://", "https://"))
                else runtime.admit_foreground_query(
                    field, target, why=req.why))
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

    @app.get("/api/research-desk/sources/{source_id}/pages/{page}")
    def research_desk_source_page(source_id: str, page: int):
        runtime = app.state.research_desk_runtime
        if runtime is None:
            return JSONResponse(status_code=404, content={
                "error": "research desk is not attached"})
        try:
            return runtime.desk.inspect_source_page(source_id, page)
        except ValueError as exc:
            return JSONResponse(status_code=404,
                                content={"error": str(exc)[:500]})

    @app.get("/api/research-desk/sources/{source_id}")
    def research_desk_source(source_id: str):
        runtime = app.state.research_desk_runtime
        if runtime is None:
            return JSONResponse(status_code=404, content={
                "error": "research desk is not attached"})
        try:
            return runtime.desk.inspect_source(source_id)
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

    @app.post("/api/voice/config")
    def voice_output_config(req: VoiceOutputConfigRequest):
        """Switch this persona's speaking vessel without restarting it."""
        provider = str(req.provider or "").strip()
        voice = str(req.voice or "").strip()
        if provider not in OUTPUT_PROVIDERS:
            return JSONResponse(status_code=400, content={
                "error": f"unknown voice output provider '{provider}'"})
        if len(voice) > 160 or any(char in voice for char in "\r\n"):
            return JSONResponse(status_code=400, content={
                "error": "voice identifier must be one line under 161 characters"})
        roster_path = os.path.join(app.state.engine.pdir, "roster.yaml")
        if not os.path.isfile(roster_path):
            return JSONResponse(status_code=409, content={
                "error": "this runtime-only persona has no roster to save into"})
        try:
            write_roster_mapping_scalar(app.state.engine.pdir,
                                        "voice_output", "provider", provider)
            write_roster_mapping_scalar(app.state.engine.pdir,
                                        "voice_output", "voice", voice)
            write_roster_mapping_scalar(app.state.engine.pdir,
                                        "voice_output", "auto_play",
                                        bool(req.auto_play and provider != "disabled"))
            tuning = normalize_voice_tuning(req.model_dump())
            for key, value in tuning.items():
                write_roster_mapping_scalar(app.state.engine.pdir,
                                            "voice_output", key, value)
        except (OSError, ValueError) as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)[:500]})
        return {"ok": True, "voice_output_config": {
            "provider": provider, "voice": voice,
            "auto_play": bool(req.auto_play and provider != "disabled"), **tuning,
            "household": load_voice_defaults(REPO)},
            "restart_required": False}

    @app.get("/api/voice/hume-library")
    def hume_voice_library_list():
        from core.hume_voice_library import list_voices
        return {"voices": list_voices(REPO)}

    @app.post("/api/voice/hume-library")
    def hume_voice_library_save(req: HumeVoiceShelfRequest):
        from core.hume_voice_library import list_voices, save_voice
        try:
            saved = save_voice(REPO, req.label, req.reference)
            return {"ok": True, "saved": saved,
                    "voices": list_voices(REPO)}
        except (OSError, ValueError) as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)[:500]})

    @app.delete("/api/voice/hume-library/{voice_id}")
    def hume_voice_library_delete(voice_id: str):
        from core.hume_voice_library import delete_voice, list_voices
        if not delete_voice(REPO, voice_id):
            return JSONResponse(status_code=404, content={
                "error": "that saved Hume voice is not on this shelf"})
        return {"ok": True, "voices": list_voices(REPO),
                "provider_voice_deleted": False}

    @app.get("/api/voice/elevenlabs-library")
    def elevenlabs_voice_library_list():
        from core.elevenlabs_voice_library import list_voices
        return {"voices": list_voices(REPO)}

    @app.post("/api/voice/elevenlabs-library")
    def elevenlabs_voice_library_save(req: ElevenLabsVoiceShelfRequest):
        from core.elevenlabs_voice_library import list_voices, save_voice
        try:
            saved = save_voice(REPO, req.label, req.voice_id)
            return {"ok": True, "saved": saved,
                    "voices": list_voices(REPO)}
        except (OSError, ValueError) as error:
            return JSONResponse(status_code=400,
                                content={"error": str(error)[:500]})

    @app.delete("/api/voice/elevenlabs-library/{shelf_id}")
    def elevenlabs_voice_library_delete(shelf_id: str):
        from core.elevenlabs_voice_library import delete_voice, list_voices
        if not delete_voice(REPO, shelf_id):
            return JSONResponse(status_code=404, content={
                "error": "that saved ElevenLabs voice is not on this shelf"})
        return {"ok": True, "voices": list_voices(REPO),
                "provider_voice_deleted": False}

    @app.get("/api/voice/status")
    def voice_synthesis_status():
        roster = {}
        roster_path = os.path.join(app.state.engine.pdir, "roster.yaml")
        if os.path.isfile(roster_path):
            try:
                import yaml
                with open(roster_path, encoding="utf-8") as handle:
                    roster = yaml.safe_load(handle) or {}
            except (OSError, ValueError, TypeError):
                roster = {}
        config = normalize_output_config(roster.get("voice_output"))
        provider = config.get("provider")
        endpoint = ("http://127.0.0.1:8192/health" if provider == "chatterbox-turbo"
                    else "http://127.0.0.1:8191/health")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(endpoint, timeout=1.5) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:
            return {"ok": False, "provider": provider,
                    "error": str(error)[:240]}

    @app.post("/api/voice/reference")
    async def voice_reference_upload(request: Request):
        """Store a consented Chatterbox reference inside this persona."""
        audio = await request.body()
        if not audio or len(audio) > 15 * 1024 * 1024:
            return JSONResponse(status_code=400, content={
                "error": "voice reference must be a WAV file under 15 MB"})
        if not (audio.startswith(b"RIFF") and audio[8:12] == b"WAVE"):
            return JSONResponse(status_code=415, content={
                "error": "Chatterbox voice references must be WAV audio"})
        voice_dir = os.path.join(app.state.engine.pdir, "voice")
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

    @app.post("/api/voice/synthesize")
    def voice_synthesize(req: VoiceSynthesisRequest):
        """Project visible prose and cross only to the private loopback mouth."""
        projected = spoken_text(req.text)
        if not projected:
            return JSONResponse(status_code=422, content={
                "error": "the reply contained no speakable prose"})
        roster = None
        path = os.path.join(app.state.engine.pdir, "roster.yaml")
        if os.path.isfile(path):
            try:
                import yaml
                with open(path, encoding="utf-8") as handle:
                    roster = yaml.safe_load(handle) or {}
            except (OSError, ValueError, TypeError):
                roster = None
        config = normalize_output_config((roster or {}).get("voice_output"))
        if config["provider"] not in {
                "qwen3-tts", "chatterbox-turbo", "hume-octave", "elevenlabs"}:
            return JSONResponse(status_code=409, content={
                "error": "a neural voice is not this persona's selected mouth"})
        state = app.state.engine.get_state()
        instruction, vector = expression_instruction(
            state.get("voice_output"),
            getattr(app.state, "voice_delivery_vector", None))
        app.state.voice_delivery_vector = vector
        provider = config["provider"]
        if provider in {"hume-octave", "elevenlabs"}:
            try:
                from core.cloud_tts import synthesize as synthesize_cloud_voice
                audio, media_type, evidence = synthesize_cloud_voice(
                    provider, projected, config["voice"])
                headers = {"Cache-Control": "no-store",
                           "X-JNSQ-Provider": provider,
                           "X-JNSQ-Spoken-Chars": str(len(projected))}
                if evidence.get("request_id"):
                    headers["X-JNSQ-Request-Id"] = evidence["request_id"]
                if evidence.get("character_cost"):
                    headers["X-JNSQ-Character-Cost"] = evidence["character_cost"]
                return Response(audio, media_type=media_type, headers=headers)
            except Exception as error:
                return JSONResponse(status_code=503, content={
                    "error": str(error)[:500]})
        if provider == "chatterbox-turbo":
            reference = os.path.abspath(os.path.join(
                app.state.engine.pdir, "voice", "chatterbox_reference.wav"))
            payload_value = {"text": projected, "voice_reference": reference}
            endpoint = "http://127.0.0.1:8192/synthesize"
        else:
            payload_value = {"text": projected, "language": "English",
                             "voice": config["voice"], "instruction": instruction}
            endpoint = "http://127.0.0.1:8191/synthesize"
        payload = json.dumps(payload_value).encode("utf-8")
        request = urllib.request.Request(
            endpoint, data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=180) as response:
                audio = response.read()
                headers = {
                    "Cache-Control": "no-store",
                    "X-JNSQ-Provider": provider,
                    "X-JNSQ-Spoken-Chars": str(len(projected)),
                }
                for name in ("X-JNSQ-Sample-Rate", "X-JNSQ-Synthesis-Ms"):
                    if response.headers.get(name):
                        headers[name] = response.headers[name]
                return Response(audio, media_type="audio/wav", headers=headers)
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read()).get("error")
            except Exception:
                detail = str(error)
            return JSONResponse(status_code=503,
                                content={"error": str(detail)[:500]})
        except Exception as error:
            return JSONResponse(status_code=503, content={
                "error": f"private {provider} is unavailable: {str(error)[:400]}"})

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

    @app.get("/api/salience/{persona}/fixation-diagnostic")
    def salience_fixation_diagnostic(
            persona: str,
            n: int = Query(default=2000, ge=1, le=10000)):
        found = salience_for(persona)
        if found is None:
            return JSONResponse(status_code=404, content={
                "error": "no live salience field for that persona"})
        _field, observer = found
        return FixationDiagnostic.project(
            observer.read_history(
                n=n, types=FixationDiagnostic.RECORD_TYPES),
            persona=app.state.engine.persona)

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
        area_media = load_conversation_area_background(
            app.state.engine.pdir)
        result["conversation_area_background"] = ({
            "url": "/api/ui/conversation-area-background",
            "revision": area_media["revision"]} if area_media else None)
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

    @app.get("/api/altered-state")
    def altered_state_status():
        organ = getattr(app.state.engine, "altered_state", None)
        if organ is None:
            return JSONResponse(status_code=503, content={
                "error": "altered_state organ is not enabled"})
        return organ.status()

    @app.post("/api/altered-state/request-consent")
    def altered_state_request_consent(req: AlteredConsentRequest):
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "persona is mid-turn"})
        try:
            engine = app.state.engine
            organ = getattr(engine, "altered_state", None)
            if organ is None:
                return JSONResponse(status_code=503, content={
                    "error": "altered_state organ is not enabled"})
            result = organ.request_consent(
                req.action, req.profile, req.intensity)
            field = getattr(engine, "idle_metabolism", None)
            if field is not None and "dmn" in getattr(engine, "enabled", set()):
                offer_altered_consent(engine, field,
                                      now=__import__("time").time())
                field.save()
                result = organ.status()
            return result
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/altered-state/cancel-consent")
    def altered_state_cancel_consent():
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "persona is mid-turn"})
        try:
            engine = app.state.engine
            organ = getattr(engine, "altered_state", None)
            if organ is None:
                return JSONResponse(status_code=503, content={
                    "error": "altered_state organ is not enabled"})
            result = organ.cancel_consent_request()
            field = getattr(engine, "idle_metabolism", None)
            if field is not None and prune_stale_altered_consent(
                    engine, field, now=__import__("time").time()):
                field.save()
            return result
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/altered-state/begin")
    def altered_state_begin(req: AlteredStateRequest):
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "persona is mid-turn"})
        try:
            engine = app.state.engine
            organ = getattr(engine, "altered_state", None)
            if organ is None:
                return JSONResponse(status_code=503, content={
                    "error": "altered_state organ is not enabled"})
            body = engine.soma.snapshot() if engine.soma else {}
            consent_receipt = organ.consume_consent(
                "begin", req.profile, req.intensity)
            return organ.begin(
                req.profile, req.intensity,
                set_snapshot={
                    "persona_consent": consent_receipt,
                    "cocktail": dict(engine.cocktail or {}),
                    "bands": dict(engine.osc.bands) if engine.osc else {},
                    "coherence": (engine.osc.coherence()
                                  if engine.osc else 1.0),
                    "body": body,
                })
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/altered-state/adjust")
    def altered_state_adjust(req: AlteredDoseRequest):
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "persona is mid-turn"})
        try:
            organ = getattr(app.state.engine, "altered_state", None)
            if organ is None:
                return JSONResponse(status_code=503, content={
                    "error": "altered_state organ is not enabled"})
            organ.consume_consent("adjust", req.profile, req.intensity)
            return organ.adjust_intensity(req.intensity)
        except ValueError as exc:
            return JSONResponse(status_code=400,
                                content={"error": str(exc)})
        finally:
            app.state.turn_lock.release()

    @app.post("/api/altered-state/abort")
    def altered_state_abort():
        if not app.state.turn_lock.acquire(blocking=False):
            return JSONResponse(status_code=409, content={
                "error": "persona is mid-turn"})
        try:
            organ = getattr(app.state.engine, "altered_state", None)
            if organ is None:
                return JSONResponse(status_code=503, content={
                    "error": "altered_state organ is not enabled"})
            return organ.abort()
        finally:
            app.state.turn_lock.release()

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
            grounding_images = store_images(
                app.state.engine.pdir,
                [(item.model_dump() if hasattr(item, "model_dump")
                  else item.dict()) for item in req.grounding_images])
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        conversation_id = new_cycle_id()
        ledger = getattr(app.state.engine, "conversation_ledger", None)
        if ledger is not None:
            ledger.admit(
                conversation_id=conversation_id, channel="chat",
                speaker=req.speaker or current_speaker(),
                speaker_account=req.speaker or current_speaker(),
                user_persona=req.user_persona,
                message=(req.message or "").strip() or (
                    "[shared image material]" if images else ""),
                images=[public_image_record(item) for item in images],
                source="cockpit_turn")
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
                                              images=images + grounding_images,
                                              grounding_image_count=len(
                                                  grounding_images),
                                              user_persona=req.user_persona,
                                              conversation_id=conversation_id)
        except Exception as e:
            # a lost turn should fail as WORDS, never a plain-text 500
            # the UI can't parse. Traceback still lands in the tenant log.
            import traceback
            traceback.print_exc()
            return JSONResponse(status_code=504, content={
                "error": turn_failure_message(app.state.engine, e),
                "conversation": {"id": conversation_id,
                                 "status": "failed_saved"}})
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
            grounding_images = store_images(
                app.state.engine.pdir,
                [(item.model_dump() if hasattr(item, "model_dump")
                  else item.dict()) for item in req.grounding_images])
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        conversation_id = new_cycle_id()
        ledger = getattr(app.state.engine, "conversation_ledger", None)
        if ledger is not None:
            ledger.admit(
                conversation_id=conversation_id, channel="chat",
                speaker=req.speaker or current_speaker(),
                speaker_account=req.speaker or current_speaker(),
                user_persona=req.user_persona,
                message=(req.message or "").strip() or (
                    "[shared image material]" if images else ""),
                images=[public_image_record(item) for item in images],
                source="cockpit_turn_stream")
        external_demand("human_turn_arrived", "human_turn_stream")
        # Streaming solo turns obey the same event-driven queue as JSON turns.
        app.state.turn_lock.acquire()

        events = queue.Queue()

        def run_turn():
            try:
                result = app.state.engine.take_turn(
                    req.message, max_tokens=app.state.max_tokens,
                    speaker=req.speaker or current_speaker(),
                    images=images + grounding_images,
                    grounding_image_count=len(grounding_images),
                    user_persona=req.user_persona,
                    conversation_id=conversation_id,
                    on_text=lambda text: events.put({"type": "delta",
                                                     "text": text}))
                events.put({"type": "final", "result": result})
            except Exception as e:
                import traceback
                traceback.print_exc()
                events.put({"type": "error", "error":
                            turn_failure_message(app.state.engine, e),
                            "conversation": {"id": conversation_id,
                                             "status": "failed_saved"}})
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
    from shell.intention_loom_runtime import IntentionLoomRuntime
    intention_loom_runtime = IntentionLoomRuntime(
        engine, agency_controller, (roster or {}).get("intention_loom"),
        choice_ledger=engine.choice_ledger)
    from shell.writing_desk_runtime import WritingDeskRuntime
    writing_desk_runtime = WritingDeskRuntime(
        engine, agency_controller, (roster or {}).get("writing_desk"),
        choice_ledger=engine.choice_ledger)
    from shell.archive_reader_runtime import ArchiveReaderRuntime
    archive_reader_runtime = ArchiveReaderRuntime(
        engine, agency_controller, (roster or {}).get("archive_reader"))
    from shell.document_reader_runtime import DocumentReaderRuntime
    document_reader_runtime = DocumentReaderRuntime(
        engine, agency_controller, (roster or {}).get("document_reader"),
        writing_desk_runtime=writing_desk_runtime)
    from shell.research_desk_runtime import ResearchDeskRuntime
    research_desk_runtime = ResearchDeskRuntime(
        engine, agency_controller, (roster or {}).get("research_desk"),
        writing_desk_runtime=writing_desk_runtime)
    from shell.atelier_runtime import AtelierRuntime
    atelier_runtime = AtelierRuntime(
        engine, agency_controller, (roster or {}).get("atelier"))
    from shell.internal_action_registry import InternalActionRegistry
    internal_action_registry = InternalActionRegistry()
    internal_action_registry.register(
        "writing_desk.private_draft", "writing_desk",
        writing_desk_runtime.consume_internal_action)
    internal_action_registry.register(
        "atelier.private_creation", "atelier",
        atelier_runtime.consume_internal_action)
    internal_action_registry.register(
        "document_reader.read_accessible_document", "document_reader",
        document_reader_runtime.consume_internal_action)
    intention_loom_runtime.internal_action_submitter = (
        internal_action_registry.submit)
    writing_desk_runtime.internal_outcome_sink = (
        intention_loom_runtime.project_loom.record_owner_outcome)
    atelier_runtime.internal_outcome_sink = (
        intention_loom_runtime.project_loom.record_owner_outcome)
    document_reader_runtime.internal_outcome_sink = (
        intention_loom_runtime.project_loom.record_owner_outcome)
    engine.internal_action_registry = internal_action_registry
    for selection in (
            intention_loom_runtime.project_loom.pending_internal_selections()):
        try:
            owner_record = internal_action_registry.submit(selection)
            intention_loom_runtime.project_loom.acknowledge_internal_action(
                selection["selection_id"], owner_record)
        except Exception as exc:
            observer.autonomy_transition(
                "internal_action_recovery_failed", time.time(),
                selection_id=selection.get("selection_id"),
                capability=selection.get("capability"),
                error_type=type(exc).__name__)
    # Boot is a genuine recurrence boundary.  Rehydrate every durable pending
    # internal seed before the DMN thread begins so a process stop between
    # selection and effect-drain cannot strand private material outside the
    # live shared field until some later autonomous fire.
    writing_desk_runtime.refresh_pending(engine.idle_metabolism)
    atelier_runtime.refresh_pending(engine.idle_metabolism)
    document_reader_runtime.refresh_pending(engine.idle_metabolism)
    engine.idle_metabolism.save(now=time.time())
    from core.experiential_continuity import ExperientialContinuity
    engine.experiential_continuity = ExperientialContinuity(
        engine.persona,
        agency=agency_runtime.workbench,
        intention_loom=intention_loom_runtime.loom,
        writing_desk=writing_desk_runtime.desk,
        archive_reader=archive_reader_runtime.archive,
        document_reader=document_reader_runtime.library,
        research_desk=research_desk_runtime.desk,
        atelier=atelier_runtime.atelier,
    )
    engine.register_volitional_action(
        "offer_intention",
        lambda action: intention_loom_runtime.admit_cue(
            engine.idle_metabolism, action["target"], action["text"] or "",
            ownership="persona_chosen_conversation"),
        requires="intention_loom")
    engine.register_volitional_action(
        "offer_writing",
        lambda action: writing_desk_runtime.admit_seed(
            engine.idle_metabolism, action["target"],
            content=action["text"] or "",
            ownership="persona_chosen_conversation"),
        requires="writing_desk")
    engine.register_volitional_action(
        "offer_research",
        lambda action: research_desk_runtime.admit_interest(
            engine.idle_metabolism,
            (action["target"] + (" " + action["text"]
                                  if action["text"] else "")).strip(),
            origin="persona_chosen_conversation"),
        requires="research_desk")
    engine.register_volitional_action(
        "browse_research",
        lambda action: (
            research_desk_runtime.admit_foreground_url(
                engine.idle_metabolism, action["target"],
                why=action["text"] or "")
            if str(action.get("target") or "").casefold().startswith(
                ("http://", "https://"))
            else research_desk_runtime.admit_foreground_query(
                engine.idle_metabolism, action["target"],
                why=action["text"] or "")),
        requires="research_desk")
    engine.register_volitional_action(
        "browse_research",
        lambda action: (
            research_desk_runtime.admit_foreground_url(
                engine.idle_metabolism, action["target"],
                why=action["text"] or "")
            if str(action.get("target") or "").casefold().startswith(
                ("http://", "https://"))
            else research_desk_runtime.admit_foreground_query(
                engine.idle_metabolism, action["target"],
                why=action["text"] or "")),
        requires="research_desk")
    engine.register_volitional_action(
        "browse_research",
        lambda action: (
            research_desk_runtime.admit_foreground_url(
                engine.idle_metabolism, action["target"],
                why=action["text"] or "")
            if str(action.get("target") or "").casefold().startswith(
                ("http://", "https://"))
            else research_desk_runtime.admit_foreground_query(
                engine.idle_metabolism, action["target"],
                why=action["text"] or "")),
        requires="research_desk")

    def open_research_report(action):
        report = research_desk_runtime.desk.resolve_report(
            action.get("target") or "latest")
        opened = research_desk_runtime.desk.inspect_anchor(
            report["anchor"], maximum=16000)
        source_lines = "\n".join(
            f"- [{source['source_id']}] {source.get('title') or 'Untitled'}"
            f" — {source.get('url') or ''}"
            for source in opened.get("sources") or ())
        context = (
            "You explicitly reopened one of your completed private Research "
            "Desk reports for this turn. The report is prior authored analysis, "
            "not canonical truth or automatic present endorsement. Reinspect "
            "its exact citations before making stronger claims.\n"
            f"Report id: {opened['report_id']}\n"
            f"Immutable anchor: {opened['anchor']}\n"
            f"Topic: {opened['title']}\n"
            f"Sources:\n{source_lines or '- none'}\n\n"
            f"{opened['content']}")
        engine.queue_research_report_context(context)
        return {
            "ok": True,
            "queued": True,
            "report_id": opened["report_id"],
            "anchor": opened["anchor"],
            "sha256": opened["sha256"],
            "source_ids": opened["source_ids"],
        }

    engine.register_volitional_action(
        "research_report_open", open_research_report,
        requires="research_desk")

    def observe_local_weather(_action):
        from room.local_weather import resident_observation
        if engine.room is None:
            return {"error": "local weather host is unavailable"}
        context, receipt = resident_observation(engine.room.local_weather())
        engine.queue_local_world_context(context)
        return receipt

    engine.register_volitional_action(
        "observe_local_weather", observe_local_weather,
        requires="room_sense")
    engine.register_volitional_action(
        "offer_atelier",
        lambda action: atelier_runtime.admit_seed(
            engine.idle_metabolism, action["target"], action["text"] or "",
            ownership="persona_chosen_conversation"),
        requires="atelier")
    engine.register_volitional_action(
        "offer_latest_artifact",
        lambda action: atelier_runtime.offer_latest_artifact(
            action["target"],
            allowed_audiences=(engine.local_human,)),
        requires="atelier")
    app = build_app(engine, max_tokens=args.max_tokens,
                    turn_lock=shared_lock, speaker=args.speaker,
                    agency_controller=agency_controller,
                    agency_runtime=agency_runtime,
                    intention_loom_runtime=intention_loom_runtime,
                    writing_desk_runtime=writing_desk_runtime,
                    archive_reader_runtime=archive_reader_runtime,
                    document_reader_runtime=document_reader_runtime,
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
    if args.room_url:
        threading.Thread(
            target=room_field_revision_loop,
            args=(engine, shared_lock, stop),
            daemon=True, name="room-field-revision").start()
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
                            agency_runtime, intention_loom_runtime,
                            writing_desk_runtime,
                            archive_reader_runtime, document_reader_runtime,
                            research_desk_runtime,
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
                               args.max_tokens, stop,
                               (roster or {}).get("social")),
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
