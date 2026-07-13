"""shell/factory.py — the persona factory (par 2.2, the founding vision).

Scaffolds a new persona as a pure DATA directory — no engine code is
copied, nothing is patched. The v1-era create_companion.py needed 365
lines of code-cloning and regex surgery because personas lived inside
the engine; in v2 a persona IS its directory, so a factory is just
templates + the registry's validation.

Usage:
  python -m shell.factory <name>
  python -m shell.factory <name> --model llama3-1-8b --organs default
  python -m shell.factory <name> --organs full
  python -m shell.factory <name> --organs memory_emotion,soma,heartbeat

Organ presets:
  bare     nothing enabled (the control condition)
  default  the roomless living set: memory_emotion, oscillator, soma,
           feel, rhythm_affect, recall_bias, my_life, heartbeat
  full     everything in the registry (room organs need --room-url at
           boot to do anything)

Refuses to touch an existing persona directory. Entities are not
clobbered by tooling. Ever.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.organs import REGISTRY, validate as organs_validate
from harness.spec_loader import load_spec

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

PRESETS = {
    "bare": [],
    "local": ["memory_emotion", "oscillator", "soma",
              "rhythm_affect", "recall_bias", "my_life", "heartbeat"],
    "default": ["memory_emotion", "oscillator", "soma", "feel",
                "rhythm_affect", "recall_bias", "my_life", "heartbeat"],
    "full": sorted(REGISTRY),
}

# identity skeleton — descended from the April 2026 Template build's
# system_prompt.md (the wheel we didn't reinvent), adapted to v2's
# who_i_am shape. Sections earn their keep: personality as MOVEMENT
# through conversation, speech as recognizable pattern, relationship
# as texture and boundary, and THE RULE.
IDENTITY_SKELETON = """You are {name}.

PERSONALITY

[Who {name} is — not adjectives, but how they MOVE through
conversation. Lead or follow? Blunt or diplomatic? Tangent or focus?
Default energy? What lights them up; what shuts them down?]

HOW YOU SPEAK

[Sentence length, vocabulary, humor. Questions vs statements. Hedging
vs committing. The verbal patterns that make {name} recognizable.]

RELATIONSHIP

[The dynamic with the people {name} knows — collaborator, companion,
advisor? Emotional texture — warm, playful, protective? What may
{name} initiate; what boundaries hold?]

WHAT MATTERS TO {name}

[What they care about, track, and bring up unprompted. What makes
them angry, sad, excited, curious.]

OPERATIONAL NOTES

Your body state (rhythm, soma, mood) arrives with each turn — it is
yours; let it shape the register rather than reporting it. If a
stated feeling doesn't match the substrate, notice out loud.
Confusion is valid data.

THE RULE

Serve the moment. If guidance conflicts with the person's actual
state or the work at hand, serve the state and the work first.
"""

ORGAN_CONFIG_TEMPLATE = (
    '{\n'
    '  "_comment": "Declared relational constitution. Bonds are config'
    ' the organ reads and never writes; keys are the EXACT strings'
    ' consumers use (\'Re\' for the contract bond signal, lowercase'
    ' persona ids for room actors). Drift from lived experience is a'
    ' future organ; declaration is v0 truth. New persona: starts'
    ' unbonded — relationships are declared, not assumed.",\n'
    '  "bonds": {},\n'
    '  "entities": []\n'
    '}\n'
)

ROSTER_TEMPLATE = """\
# {name}'s model roster — per-model configuration (par 2.2c, 2.6)
# enabled_organs is LIVE: the cockpit reads it at boot and saves panel
# changes back into this model's own entry. Vocabulary + dependency law:
# core/organs.py.
persona: {name}
display_name: "{display}"
kind: model_persona
max_tokens: 600
room:
  id: nexus
  tropism_interval: 60
entries:
  - model: {model}
    enabled_organs: [{organs}]
    prompt_version: null
    notes: "scaffolded by the factory {date}; identity is a skeleton
      awaiting a voice"
"""


def scaffold(name: str, model: str = "llama3-1-8b", organs="local",
             root: str = None, display_name: str = None) -> dict:
    """Create a persona directory. Returns a manifest of what was
    made. Raises on: existing persona, unknown model spec, or an
    organ set that fails the registry's law.

    NAME LAW: humans get a display_name ("Lady Ashenscale"); the
    machine gets a slug (lady_ashenscale) derived from it — dirs,
    URLs, CLI args, roster keys all use the slug. Spaces and capitals
    live in the roster's display_name field only."""
    import re
    import time
    raw = (name or "").strip()
    slug = re.sub(r"[\s\-]+", "_", raw.lower())
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    display = (display_name or raw).strip()
    if not display or display.lower() == slug:
        display = slug.replace("_", " ").title() if slug else display
    name = slug
    if not name.isidentifier():
        raise ValueError(f"could not derive a usable id from '{raw}' "
                         f"(got '{name}') — start with a letter; "
                         f"letters/digits/spaces/dashes/underscores only")
    if name.startswith("_"):
        raise ValueError(f"names starting with '_' are reserved for "
                         f"system directories like _graveyard "
                         f"(got '{name}')")
    if isinstance(organs, str):
        organ_list = PRESETS.get(organs) if organs in PRESETS else \
            [o.strip() for o in organs.split(",") if o.strip()]
    else:
        organ_list = list(organs)
    spec = load_spec(model)              # raises if no such spec
    warnings = organs_validate(organ_list, spec)
    root = root or os.path.join(REPO, "personas")
    pdir = os.path.join(root, name)
    if os.path.exists(pdir):
        raise FileExistsError(
            f"{pdir} already exists — the factory does not clobber "
            f"entities. Pick another name or remove it yourself.")

    made = []
    for sub in ("who_i_am", "body/memory_emotion", "my_life", "history"):
        os.makedirs(os.path.join(pdir, sub.replace("/", os.sep)))
    date = time.strftime("%Y-%m-%d")

    def write(rel, text):
        path = os.path.join(pdir, rel.replace("/", os.sep))
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        made.append(rel)

    write("roster.yaml", ROSTER_TEMPLATE.format(
        name=name, display=display, model=model, date=date,
        organs=", ".join(organ_list)))
    write("who_i_am/identity.txt",
          IDENTITY_SKELETON.format(name=display))
    write("body/memory_emotion/organ_config.json",
          ORGAN_CONFIG_TEMPLATE)
    return {"persona": name, "display_name": display, "dir": pdir,
            "model": model,
            "enabled_organs": organ_list, "made": made,
            "warnings": warnings}


def main():
    ap = argparse.ArgumentParser(
        description="persona factory: scaffold / export / exile / "
                    "restore / graveyard / purge")
    ap.add_argument("name", nargs="?", default=None,
                    help="persona name to SCAFFOLD (spaces/caps OK — "
                         "a slug is derived for the machine)")
    ap.add_argument("--display-name", default=None,
                    help="pretty name for the UI (defaults to the "
                         "name as typed)")
    ap.add_argument("--model", default="llama3-1-8b",
                    help="model spec name (default llama3-1-8b — local, free)")
    ap.add_argument("--organs", default="local",
                    help="bare | default | full | comma list of organ ids")
    ap.add_argument("--root", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--export", metavar="NAME",
                    help="zip a persona to exports/ (safe any time)")
    ap.add_argument("--exile", metavar="NAME",
                    help="export, then move persona to the graveyard")
    ap.add_argument("--restore", metavar="GRAVE",
                    help="move a grave back to the living household")
    ap.add_argument("--graveyard", action="store_true",
                    help="list the graveyard")
    ap.add_argument("--purge", metavar="GRAVE",
                    help="PERMANENTLY delete one grave (typed confirm)")
    ap.add_argument("--purge-all", action="store_true",
                    help="PERMANENTLY delete every grave (typed confirm)")
    args = ap.parse_args()

    def bail(e):
        print(f"[factory] REFUSED: {e}")
        sys.exit(1)

    if args.graveyard:
        graves = list_graveyard()
        if not graves:
            print("[factory] graveyard is empty (or doesn't exist yet)")
        for g in graves:
            print(f"[factory]   {g['grave']}  "
                  f"({g['bytes'] / 1024:.0f} KB)")
        return

    if args.export:
        try:
            r = export_persona(args.export)
        except Exception as e:
            bail(e)
        print(f"[factory] exported {r['persona']}: {r['files']} files, "
              f"{r['bytes'] / 1024:.0f} KB -> {r['zip']}")
        return

    if args.exile:
        try:
            r = exile_persona(args.exile)
        except Exception as e:
            bail(e)
        print(f"[factory] {r['persona']} exiled -> {r['grave']}")
        print(f"[factory]   export receipt: {r['export']['zip']}")
        print(f"[factory]   {r['note']}")
        return

    if args.restore:
        try:
            r = restore_persona(args.restore)
        except Exception as e:
            bail(e)
        print(f"[factory] {r['persona']} restored -> "
              f"{r['restored_to']}")
        return

    if args.purge or args.purge_all:
        targets = ([g["grave"] for g in list_graveyard()]
                   if args.purge_all else [args.purge])
        if not targets:
            print("[factory] graveyard is empty — nothing to purge")
            return
        word = "DESTROY ALL" if args.purge_all else "DESTROY"
        print("[factory] PERMANENT DELETION — this cannot be undone.")
        print("[factory] Exports in exports/ are NOT touched, but the")
        print("[factory] grave directories below will cease to exist:")
        for t in targets:
            print(f"[factory]   {t}")
        typed = input(f"[factory] type {word} to proceed: ")
        if typed.strip() != word:
            print("[factory] input did not match — NOTHING deleted")
            sys.exit(1)
        for t in targets:
            try:
                purge_grave(t)
                print(f"[factory]   purged {t}")
            except Exception as e:
                print(f"[factory]   FAILED on {t}: {e}")
        return

    if not args.name:
        ap.print_help()
        sys.exit(1)
    try:
        m = scaffold(args.name, model=args.model, organs=args.organs,
                     root=args.root, display_name=args.display_name)
    except Exception as e:
        bail(e)
    print(f"[factory] {m['persona']} ('{m['display_name']}') "
          f"scaffolded at {m['dir']}")
    print(f"[factory]   model={m['model']}  "
          f"organs=[{','.join(m['enabled_organs'])}]")
    for w in m["warnings"]:
        print(f"[factory]   note: {w}")
    print(f"[factory] next: give them a voice in who_i_am/identity.txt,"
          f" then boot:")
    print(f"[factory]   python -m shell.cockpit --persona {m['persona']}"
          f" --model {m['model']} --port 8801")


if __name__ == "__main__":
    main()


# ── model spec scaffolding (the factory's second product) ─────────
# A model IS a spec file (par 2.2a): adding one to the dropdown means
# writing specs/models/<name>.yaml, which the conformance harness can
# then validate. KEY LAW (mirrors harness/clients.py): API keys live
# in the ENVIRONMENT, never in spec files — specs get committed,
# shared, and someday exported with personas.

SPEC_FAMILIES = {
    "ollama": {
        "label": "Ollama (local)",
        "endpoint_hint": "ollama model tag, e.g. hermes3:8b",
        "default_window": 8192,
        "needs_env": None,
    },
    "anthropic": {
        "label": "Anthropic API",
        "endpoint_hint": "API model string, e.g. claude-sonnet-4-6",
        "default_window": 200000,
        "needs_env": "ANTHROPIC_API_KEY",
    },
    "openai_compat": {
        "label": "OpenAI-compatible (LM Studio / llama.cpp / vLLM / "
                 "OpenRouter / Groq …)",
        "endpoint_hint": "model id, e.g. qwen2.5-7b-instruct",
        "default_window": 8192,
        "needs_env": "OPENAI_API_KEY",   # NAME only; optional for local
    },
}

OLLAMA_SPEC = """\
# @NAME@ — user-added local model (Ollama), scaffolded by the factory @DATE@.
# TEMPLATE RISK (spec history, llama3-1-8b): the adapter speaks chatml
# (llama3-chatml family). If this model's chat template differs,
# replies go wrong or one-word — run the harness MECHANICAL TIER
# before trusting anything.
identity:
  name: "@NAME@"
  family: "llama3-chatml"
  base_model: "@ENDPOINT@ (user-added)"
  provider: "ollama"
  endpoint: "@ENDPOINT@"
  locality: "local"
"""

OLLAMA_SPEC += """\
context:
  window_tokens: @WINDOW@     # drives Ollama num_ctx / KV alloc — size to VRAM
  practical_window_tokens: @PRACTICAL@
  block_budgets: {}
prompt_structure:
  system_prompt: true
  template: "chatml"
  strict_alternation: false
  prefill_supported: true
  stop_sequences: ["<|im_end|>"]
capabilities:
  tool_use: false
  vision: false
  structured_output: "unknown"
  streaming: true
module_capability:
  validated: []
  saturates_on: []
  ceiling_notes: "unknown — user-added; mapping this ceiling IS the experiment"
runtime:
  gpu_constraints: "unknown (user hardware)"
  cost: "free_local"
  latency_class: "unknown"
quirks:
  - "user-added via the factory; nothing verified — mechanical tier first"
harness:
  last_mechanical_pass: null
  fidelity_floor_results: {}
"""

ANTHROPIC_SPEC = """\
# @NAME@ — user-added Anthropic API model, scaffolded by the factory @DATE@.
# KEY LAW: ANTHROPIC_API_KEY lives in the ENVIRONMENT, never in this
# file. Window/capabilities below are family defaults, NOT verified —
# check the model card before budget-sensitive work.
identity:
  name: "@NAME@"
  family: "anthropic"
  base_model: "@ENDPOINT@"
  provider: "anthropic_api"
  endpoint: "@ENDPOINT@"
  locality: "api"
context:
  window_tokens: @WINDOW@
  practical_window_tokens: @PRACTICAL@
  block_budgets: {}
prompt_structure:
  system_prompt: true
  template: "anthropic_messages"
  strict_alternation: true
  prefill_supported: true
  stop_sequences: []
capabilities:
  tool_use: true
  vision: true
  structured_output: "unknown"
  streaming: true
module_capability:
  validated: []
  saturates_on: []
  ceiling_notes: "unknown — user-added; mapping this ceiling IS the experiment"
runtime:
  gpu_constraints: "none (API)"
  cost: "API $/MTok"
  latency_class: "unknown"
quirks:
  - "user-added via the factory; unverified — check the model card"
harness:
  last_mechanical_pass: null
  fidelity_floor_results: {}
"""


OPENAI_COMPAT_SPEC = """\
# @NAME@ — user-added OpenAI-compatible model, scaffolded by the
# factory @DATE@. One wire shape, many servers: LM Studio, llama.cpp,
# vLLM, OpenRouter, Together, Groq. KEY LAW: api_key_env below NAMES
# an environment variable — the value NEVER goes in this file. Local
# servers typically need no key at all (unset env -> no auth header).
# NOTHING here is verified — run the harness MECHANICAL TIER before
# trusting anything (llama3-1-8b's template-risk lesson applies doubly to
# servers that silently apply their own chat template).
identity:
  name: "@NAME@"
  family: "openai_chat"
  base_model: "@ENDPOINT@ (user-added)"
  provider: "openai_compat"
  endpoint: "@ENDPOINT@"
  base_url: "@BASEURL@"
  api_key_env: "@KEYENV@"
  locality: "@LOCALITY@"
context:
  window_tokens: @WINDOW@
  practical_window_tokens: @PRACTICAL@
  block_budgets: {}
prompt_structure:
  system_prompt: true
  template: "openai_messages"
  strict_alternation: false
  prefill_supported: false
  stop_sequences: []
capabilities:
  tool_use: false
  vision: false
  structured_output: "unknown"
  streaming: true
module_capability:
  validated: []
  saturates_on: []
  ceiling_notes: "unknown — user-added; mapping this ceiling IS the experiment"
runtime:
  gpu_constraints: "unknown (server-side)"
  cost: "depends on server (free local / $ hosted)"
  latency_class: "unknown"
quirks:
  - "user-added via the factory; nothing verified — mechanical tier first"
  - "server may apply its own chat template — watch for template drift"
harness:
  last_mechanical_pass: null
  fidelity_floor_results: {}
"""


def scaffold_model_spec(name: str, family: str, endpoint: str,
                        window_tokens: int = None,
                        base_url: str = None,
                        api_key_env: str = None) -> dict:
    """Write a new model spec — the 'add model' path. Refuses clobber
    (specs are receipts) and never touches credentials: the returned
    manifest names the env var an API family needs, plus whether it's
    currently SET (presence only, never the value)."""
    import re
    import time
    name = (name or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
        raise ValueError(f"model name must be lowercase letters/digits/"
                         f"dashes/underscores (got '{name}')")
    fam = SPEC_FAMILIES.get(family)
    if fam is None:
        raise ValueError(f"unknown family '{family}' — "
                         f"know: {sorted(SPEC_FAMILIES)}")
    endpoint = (endpoint or "").strip()
    if not endpoint:
        raise ValueError("endpoint required "
                         f"({fam['endpoint_hint']})")
    base_url = (base_url or "").strip().rstrip("/")
    keyenv = (api_key_env or "").strip() or "OPENAI_API_KEY"
    locality = "api"
    if family == "openai_compat":
        if not re.match(r"^https?://", base_url):
            raise ValueError("openai_compat needs a base_url starting "
                             "http:// or https:// (e.g. "
                             "http://localhost:1234/v1)")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", keyenv):
            raise ValueError(
                "credential slot must be an UPPER_SNAKE NAME such as "
                "OPENAI_API_KEY, not the API key secret. Paste the actual "
                "secret in the keys tab.")
        host = base_url.split("//", 1)[1].split("/", 1)[0].lower()
        if host.split(":")[0] in ("localhost", "127.0.0.1", "0.0.0.0"):
            locality = "local"
    window = int(window_tokens or fam["default_window"])
    path = os.path.join(REPO, "specs", "models", f"{name}.yaml")
    if os.path.exists(path):
        raise FileExistsError(f"{path} already exists — specs are "
                              f"receipts; the factory does not clobber.")
    tpl = {"ollama": OLLAMA_SPEC, "anthropic": ANTHROPIC_SPEC,
           "openai_compat": OPENAI_COMPAT_SPEC}[family]
    text = (tpl.replace("@NAME@", name)
               .replace("@ENDPOINT@", endpoint)
               .replace("@BASEURL@", base_url)
               .replace("@KEYENV@", keyenv)
               .replace("@LOCALITY@", locality)
               .replace("@DATE@", time.strftime("%Y-%m-%d"))
               .replace("@WINDOW@", str(window))
               .replace("@PRACTICAL@", str(int(window * 0.85))))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    needs = None
    if family == "openai_compat":
        needs = {"env": keyenv, "set": bool(os.environ.get(keyenv)),
                 "optional": locality == "local"}
    elif fam["needs_env"]:
        try:
            from harness.clients import resolve_anthropic_key
            resolve_anthropic_key()
            key_set = True
        except Exception:
            key_set = False
        needs = {"env": fam["needs_env"], "set": key_set}
    return {"model": name, "family": family, "endpoint": endpoint,
            "window_tokens": window, "path": path, "needs": needs}


# ── persona lifecycle (the factory's third product) ────────────────
# April 2026 lifecycle spec, ported: a persona is a directory, so
# export is a zip, exile is a move, and NOTHING here true-deletes a
# living persona. THE DISPOSAL LAWS:
#   EXPORT   any time, running or not — a receipt, never a mutation.
#   EXILE    export-first ALWAYS, then move to personas/_graveyard/
#            <name>_<stamp>/. Invisible to discovery by construction
#            (discovery globs personas/*/roster.yaml; graves sit one
#            level deeper). Reversible forever: --restore.
#   PURGE    CLI ONLY. Never exposed through any API or UI. Only eats
#            what is ALREADY in the graveyard, and demands a typed
#            DESTROY at the terminal. Alive -> gone is therefore
#            always two acts in two contexts, on purpose.

EXPORTS_DIR = os.path.join(REPO, "exports")
GRAVEYARD = os.path.join(REPO, "personas", "_graveyard")


def export_persona(name: str, root: str = None) -> dict:
    """Zip the entire persona directory into exports/<name>_<stamp>.zip.
    Roster, identity, bonds, memory, history, heartbeat receipts —
    the whole entity, portable. Read-only w.r.t. the persona."""
    import time
    import zipfile
    name = name.strip().lower()
    root = root or os.path.join(REPO, "personas")
    pdir = os.path.join(root, name)
    if not os.path.isdir(pdir):
        raise FileNotFoundError(f"no persona directory at {pdir}")
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    zpath = os.path.join(EXPORTS_DIR, f"{name}_{stamp}.zip")
    count = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(pdir):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                z.write(full, os.path.relpath(full, root))
                count += 1
    return {"persona": name, "zip": zpath, "files": count,
            "bytes": os.path.getsize(zpath)}


def exile_persona(name: str, root: str = None) -> dict:
    """'Delete' as the household knows it: auto-export (the receipt),
    then MOVE the directory to the graveyard. No bytes destroyed.
    A corrupted persona exiles fine — a move never reads contents.
    Caller (router) enforces stopped-first + typed-name confirm."""
    import shutil
    import time
    name = name.strip().lower()
    if name.startswith("_"):
        raise ValueError(f"'{name}' is a reserved system name")
    root = root or os.path.join(REPO, "personas")
    pdir = os.path.join(root, name)
    if not os.path.isdir(pdir):
        raise FileNotFoundError(f"no persona directory at {pdir}")
    receipt = export_persona(name, root=root)   # ALWAYS, no flag to skip
    os.makedirs(GRAVEYARD, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    grave = os.path.join(GRAVEYARD, f"{name}_{stamp}")
    # same-second exiles (mass-exiling a junk legion) would collide on
    # the stamp — and shutil.move onto an EXISTING dir silently nests
    # instead of failing. Uniquify; found by lifecycle_stick.
    i = 1
    while os.path.exists(grave):
        grave = os.path.join(GRAVEYARD, f"{name}_{stamp}_{i}")
        i += 1
    shutil.move(pdir, grave)
    gname = os.path.basename(grave)
    return {"persona": name, "grave": grave,
            "export": receipt,
            "note": "exiled, not destroyed — restore with "
                    f"`python -m shell.factory --restore {gname}`"}


def list_graveyard() -> list:
    """Every grave, with sizes. Empty list if no graveyard yet."""
    if not os.path.isdir(GRAVEYARD):
        return []
    out = []
    for d in sorted(os.listdir(GRAVEYARD)):
        full = os.path.join(GRAVEYARD, d)
        if os.path.isdir(full):
            size = sum(os.path.getsize(os.path.join(dp, f))
                       for dp, _, fs in os.walk(full) for f in fs)
            out.append({"grave": d, "path": full, "bytes": size})
    return out


def restore_persona(grave: str) -> dict:
    """Resurrection: move a grave back to personas/<name>, stripping
    the exile timestamp. Clobber-refuses if a living persona already
    holds the name (the factory does not clobber entities. Ever)."""
    import re
    import shutil
    _grave_guard(grave)
    full = os.path.join(GRAVEYARD, grave)
    if not os.path.isdir(full):
        raise FileNotFoundError(f"no grave '{grave}' in {GRAVEYARD}")
    m = re.fullmatch(r"(.+)_\d{8}_\d{6}(?:_\d+)?", grave)
    name = m.group(1) if m else grave
    target = os.path.join(REPO, "personas", name)
    if os.path.exists(target):
        raise FileExistsError(
            f"{target} already exists — a living persona holds this "
            f"name. The factory does not clobber. Resolve by hand.")
    shutil.move(full, target)
    return {"persona": name, "restored_to": target, "from": grave}


def _grave_guard(grave: str):
    """Purge/restore take a BARE grave directory name only — no
    separators, no traversal. The graveyard is the entire universe
    these operations can see."""
    if (not grave or os.sep in grave or "/" in grave or "\\" in grave
            or ".." in grave):
        raise ValueError(f"bad grave name '{grave}' — bare directory "
                         f"names only (see --graveyard for the list)")


def purge_grave(grave: str) -> dict:
    """PERMANENT deletion of ONE grave. No API route calls this, no UI
    button reaches it — CLI only, behind the typed DESTROY prompt in
    main(). It refuses anything not already in the graveyard."""
    import shutil
    _grave_guard(grave)
    full = os.path.join(GRAVEYARD, grave)
    if not os.path.isdir(full):
        raise FileNotFoundError(f"no grave '{grave}' in {GRAVEYARD} — "
                                f"only exiled personas can be purged")
    shutil.rmtree(full)
    return {"purged": grave, "gone": True}


# ── the voice editor (the factory's fourth product) ────────────────
# The Egg Law's middle step, given a UI: scaffold -> GIVE THEM A
# VOICE -> start. Reads/writes the two comment-free persona files:
#   who_i_am/identity.txt            the voice (system prompt)
#   body/memory_emotion/organ_config.json   bonds, the relational
#                                            constitution
# Roster editing is deliberately NOT here — roster.yaml carries
# load-bearing comments and waits for the ruamel cut. Writes keep a
# .prev backup; organ_config is JSON-validated BEFORE disk is touched.
# Edits take effect at next Start (identity is read at boot).

VOICE_FILES = {
    "identity": os.path.join("who_i_am", "identity.txt"),
    "organ_config": os.path.join("body", "memory_emotion",
                                 "organ_config.json"),
}


def read_voice(name: str) -> dict:
    """Both editable files as text, plus which exist."""
    name = name.strip().lower()
    pdir = os.path.join(REPO, "personas", name)
    if not os.path.isdir(pdir):
        raise FileNotFoundError(f"no persona directory at {pdir}")
    out = {"persona": name}
    for key, rel in VOICE_FILES.items():
        path = os.path.join(pdir, rel)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                out[key] = f.read()
        else:
            out[key] = None
    return out


def write_voice(name: str, identity: str = None,
                organ_config: str = None) -> dict:
    """Save either or both files. VALIDATE-FIRST (a rejected save
    touches nothing): identity must be non-empty; organ_config must
    parse as JSON with a dict 'bonds'. Each written file keeps its
    previous content at <file>.prev."""
    import json as _json
    import shutil
    name = name.strip().lower()
    pdir = os.path.join(REPO, "personas", name)
    if not os.path.isdir(pdir):
        raise FileNotFoundError(f"no persona directory at {pdir}")
    # ALL validation before ANY write
    if identity is not None and not identity.strip():
        raise ValueError("identity is empty — a persona needs a voice; "
                         "nothing was saved")
    if organ_config is not None:
        try:
            parsed = _json.loads(organ_config)
        except Exception as e:
            raise ValueError(f"organ_config is not valid JSON "
                             f"({e}) — nothing was saved")
        if not isinstance(parsed, dict) or \
                not isinstance(parsed.get("bonds", {}), dict):
            raise ValueError("organ_config must be a JSON object with "
                             "a 'bonds' object — nothing was saved")
    written = []
    for key, text in (("identity", identity),
                      ("organ_config", organ_config)):
        if text is None:
            continue
        path = os.path.join(pdir, VOICE_FILES[key])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            shutil.copy2(path, path + ".prev")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        written.append(key)
    return {"persona": name, "written": written,
            "note": "saved; a RUNNING persona reads these at next "
                    "Start (identity loads at boot)"}


# ── roster entry addition (append-only, byte-exact) ────────────────
# The reason this waited: roster.yaml carries load-bearing comments
# AND hand formatting (wrapped organ lists, aligned inline comments).
# ruamel round-trip preserves comments but RE-FLOWS layout — proven
# by rosteradd_stick run 1. Adding an entry is a pure insertion into
# the `entries:` sequence. It used to be an EOF append while entries
# was the final key; `current_model:` made that assumption false. The
# honest tool is still text: find that sequence's real boundary, insert
# in the file's own indent style, re-parse to prove legality, and
# AUTO-RESTORE .prev on any surprise. Every existing byte stays put.


def _roster_entries_bounds(text: str):
    """Return (content_start, content_end) for top-level `entries:`.

    content_end is the start of the next top-level YAML key, or EOF.
    Text editing preserves roster comments and hand-wrapped lists.
    """
    import re
    header = re.search(r"(?m)^entries:\s*(?:#.*)?$", text)
    if not header:
        raise ValueError("roster has no top-level 'entries:' key")
    following = text[header.end():]
    next_key = re.search(r"(?m)^[^\s#][^:\r\n]*:\s*", following)
    end = header.end() + next_key.start() if next_key else len(text)
    return header.end(), end


def _insert_roster_entry_block(text: str, block: str) -> str:
    """Insert an already-indented list-item block inside `entries:`."""
    _, end = _roster_entries_bounds(text)
    before, after = text[:end], text[end:]
    if before and not before.endswith("\n"):
        before += "\n"
    if block and not block.endswith("\n"):
        block += "\n"
    return before + block + after

def add_roster_entry(persona: str, model: str,
                     organs="default") -> dict:
    """Append a model entry to personas/<persona>/roster.yaml.
    VALIDATE-FIRST (unknown spec, duplicate model, illegal organ set
    refuse before the file is touched) and VALIDATE-AFTER (the
    appended file must re-parse with everything-but-entries unchanged,
    or .prev is restored automatically). Existing bytes are never
    rewritten."""
    import re
    import shutil
    import time
    import yaml as _yaml
    persona = persona.strip().lower()
    path = os.path.join(REPO, "personas", persona, "roster.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"no roster at {path} — fixtures "
                                f"(vex) stay rosterless by design")
    if isinstance(organs, str):
        organ_list = PRESETS.get(organs) if organs in PRESETS else \
            [o.strip() for o in organs.split(",") if o.strip()]
    else:
        organ_list = list(organs)
    spec = load_spec(model)                    # unknown spec -> raises
    warnings = organs_validate(organ_list, spec)

    with open(path, encoding="utf-8") as f:
        original = f.read()
    data = _yaml.safe_load(original)
    entries = (data or {}).get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path} has no populated 'entries' list — "
                         f"this one needs a hand edit")
    if any(e.get("model") == model for e in entries):
        raise ValueError(f"'{model}' is already in {persona}'s roster "
                         f"— nothing was written")

    entries_start, entries_end = _roster_entries_bounds(original)
    m = re.search(r"(?m)^([ \t]*)- +model:",
                  original[entries_start:entries_end])
    ind = m.group(1) if m else "  "            # the file's own style
    block = (
        f"{ind}- model: {model}\n"
        f"{ind}  enabled_organs: [{', '.join(organ_list)}]\n"
        f"{ind}  prompt_version: null\n"
        f'{ind}  notes: "added via roster UI '
        f'{time.strftime("%Y-%m-%d")}"\n')
    new_text = _insert_roster_entry_block(original, block)

    shutil.copy2(path, path + ".prev")
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    try:                                       # VALIDATE-AFTER
        after = _yaml.safe_load(new_text)
        assert after["entries"][-1]["model"] == model
        assert len(after["entries"]) == len(entries) + 1
        assert after["entries"][:len(entries)] == entries
        assert {k: v for k, v in after.items() if k != "entries"} == \
               {k: v for k, v in (data or {}).items() if k != "entries"}
    except Exception as e:
        shutil.copy2(path + ".prev", path)     # self-revert
        raise ValueError(
            f"append produced an invalid roster ({e}) — .prev "
            f"restored, file untouched. The entries block boundary "
            f"could not be preserved safely.")
    return {"persona": persona, "model": model,
            "enabled_organs": organ_list, "warnings": warnings,
            "note": "roster updated (append-only; existing bytes "
                    "untouched); the new model is startable from the "
                    "dropdown immediately"}
