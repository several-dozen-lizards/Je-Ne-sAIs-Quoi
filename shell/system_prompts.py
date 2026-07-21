"""shell/system_prompts.py — MODEL-scoped operational system prompts.

A system prompt here belongs to the MODEL (the vessel), not the persona
(the character). Every persona running on <model> gets the same one. Its
job is functional: orient whatever persona is running (who they are at
the mechanical level, who they're talking to), keep them driving the
room / action-grammar / output shape their vessel needs, and hold the
thread — NEVER to prescribe character or feeling. That stays the persona
instructions + the organs (descriptive-over-prescriptive).

Storage: specs/system_prompts/<model>.txt, keyed by model name (sibling
to specs/models/). Precedence when a persona boots on <model>:
    specs/system_prompts/<model>.txt           the model's own prompt
    specs/system_prompts/_family_<family>.txt  a family baseline
    specs/system_prompts/_default.txt          a global baseline
    ""                                          nothing -> no block
A bare install renders exactly as before (no file -> no block); an
override is purely additive. Writes keep a <file>.prev; clearing the
text reverts to the inherited baseline (removes the model's own file)."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SP_DIR = os.path.join(ROOT, "specs", "system_prompts")
_MODEL_RE = re.compile(r"[a-z0-9][a-z0-9_-]*$")  # the factory slug law


def _model_path(model: str) -> str:
    m = (model or "").strip()
    if not _MODEL_RE.match(m):
        raise ValueError(f"model name must be a lowercase slug "
                         f"(got '{model}')")
    return os.path.join(SP_DIR, f"{m}.txt")


def _read(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def load(model: str, family: str = None) -> str:
    """Resolve the system prompt a persona booting on <model> carries,
    walking model -> family -> default -> empty. Never raises for a
    missing file (empty is the valid 'no system prompt' state)."""
    try:
        own = _read(_model_path(model))
    except ValueError:
        own = None
    if own is not None:
        return own
    if family:
        fam = _read(os.path.join(SP_DIR, f"_family_{family}.txt"))
        if fam is not None:
            return fam
    dflt = _read(os.path.join(SP_DIR, "_default.txt"))
    return dflt if dflt is not None else ""


def read(model: str, family: str = None) -> dict:
    """For the editor: the model's OWN override text (None if it has
    none), what would actually load (resolved), and where that comes
    from — so the UI can say 'inherited from family' honestly."""
    own = _read(_model_path(model))
    fam_txt = (_read(os.path.join(SP_DIR, f"_family_{family}.txt"))
               if family else None)
    if own is not None:
        source = "model"
    elif fam_txt is not None:
        source = "family"
    elif _read(os.path.join(SP_DIR, "_default.txt")) is not None:
        source = "default"
    else:
        source = "none"
    return {"model": model, "own": own,
            "resolved": load(model, family), "source": source}


def write(model: str, text: str) -> dict:
    """Upsert the model's system prompt. VALIDATE-FIRST on the model
    name (raises before touching disk). Empty/whitespace text REVERTS to
    the inherited baseline (removes the model's own file). Keeps a
    <file>.prev on overwrite. Atomic: unique tmp + os.replace."""
    import shutil
    path = _model_path(model)  # raises on a bad name, before any disk op
    os.makedirs(SP_DIR, exist_ok=True)
    if text is None or not text.strip():
        if os.path.exists(path):
            shutil.copy2(path, path + ".prev")
            os.remove(path)
        return {"model": model, "written": False, "reverted": True,
                "note": "override cleared — reverts to the inherited "
                        "baseline at next Start"}
    if os.path.exists(path):
        shutil.copy2(path, path + ".prev")
    tmp = f"{path}.tmp_{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return {"model": model, "written": True, "reverted": False,
            "note": "saved; a persona on this model reads it at next Start"}


# ── per-organ instruction fragments (model x organ) ────────────────
# An organ a persona can USE (room_actions today; future actionable
# organs) may need the model TOLD how — per model (verbose for a small
# vessel, terse for a big one). Fragments compose onto the base at TURN
# time from the LIVE enabled set, so ticking an organ off un-appends its
# instructions on the very next turn. Descriptive organs (emotions,
# soma, gist) need no fragment — they feed state blocks the model just
# reads. Seed empty -> composed prompt == base (no behavior change).

def _organ_path(model: str, organ: str) -> str:
    m, o = (model or "").strip(), (organ or "").strip()
    if not _MODEL_RE.match(m):
        raise ValueError(f"model name must be a lowercase slug (got '{model}')")
    if not _MODEL_RE.match(o):
        raise ValueError(f"organ id must be a lowercase slug (got '{organ}')")
    return os.path.join(SP_DIR, "organs", m, f"{o}.txt")


def load_organ(model: str, organ: str, family: str = None) -> str:
    """Resolve one organ's fragment for <model>: model -> family ->
    default -> empty. Empty = 'this organ adds nothing on this model'."""
    try:
        own = _read(_organ_path(model, organ))
    except ValueError:
        own = None
    if own is not None:
        return own
    if family:
        fam = _read(os.path.join(SP_DIR, "organs", f"_family_{family}",
                                 f"{organ}.txt"))
        if fam is not None:
            return fam
    dflt = _read(os.path.join(SP_DIR, "organs", "_default", f"{organ}.txt"))
    if dflt is not None:
        return dflt
    # Structured actionable sources are also the default legacy fragment.
    # This keeps unpinned vessels capable without maintaining a second,
    # drift-prone copy of each motor grammar.
    source = os.path.join(
        ROOT, "specs", "organ_instructions", f"{organ}.yaml")
    if os.path.isfile(source):
        try:
            from core.prompt_sources import load_organ_instruction, render_legacy
            record = load_organ_instruction(source)
            if record.organ_kind == "actionable":
                return render_legacy(record)
        except Exception:
            # One malformed optional source cannot break a legacy turn.
            return ""
    return ""


def compose(model: str, family: str, enabled) -> str:
    """The full system prompt a persona carries THIS turn: the base
    (model/family/default) then the fragment of every ENABLED organ that
    has one, in REGISTRY order (deterministic, not enabled-set order).
    Called per turn against the LIVE enabled set — a panel toggle applies
    on the next turn. No fragments -> returns exactly the base."""
    from core.organs import REGISTRY
    parts = []
    base = load(model, family)
    if base.strip():
        parts.append(base)
    en = set(enabled or ())
    for oid in REGISTRY:  # registry order = stable composition
        if oid in en:
            frag = load_organ(model, oid, family)
            if frag.strip():
                parts.append(frag)
    return "\n\n".join(parts)


def read_organ(model: str, organ: str, family: str = None) -> dict:
    """Editor view of one organ fragment: own text (None if inherited),
    what resolves, and the source (model / family / default / none)."""
    own = _read(_organ_path(model, organ))
    fam_txt = (_read(os.path.join(SP_DIR, "organs", f"_family_{family}",
                                  f"{organ}.txt")) if family else None)
    if own is not None:
        source = "model"
    elif fam_txt is not None:
        source = "family"
    elif _read(os.path.join(SP_DIR, "organs", "_default",
                            f"{organ}.txt")) is not None:
        source = "default"
    elif load_organ(model, organ, family):
        source = "structured_default"
    else:
        source = "none"
    return {"model": model, "organ": organ, "own": own,
            "resolved": load_organ(model, organ, family), "source": source}


def write_organ(model: str, organ: str, text: str) -> dict:
    """Upsert one organ's fragment for <model>. VALIDATE-FIRST on both
    names (raises before disk); empty text reverts to inherited (removes
    the file). Keeps <file>.prev; atomic tmp + os.replace."""
    import shutil
    path = _organ_path(model, organ)  # raises on bad names, before disk
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if text is None or not text.strip():
        if os.path.exists(path):
            shutil.copy2(path, path + ".prev")
            os.remove(path)
        return {"model": model, "organ": organ, "written": False,
                "reverted": True,
                "note": "fragment cleared — reverts to inherited at next Start"}
    if os.path.exists(path):
        shutil.copy2(path, path + ".prev")
    tmp = f"{path}.tmp_{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return {"model": model, "organ": organ, "written": True,
            "reverted": False,
            "note": "saved; applies to a persona with this organ ON at "
                    "next Start"}
